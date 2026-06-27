from __future__ import annotations

import io
import os
import shutil
import sys
import time
from pathlib import Path

import fitz
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QDialog

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LARGE_PDF_NAMES = (
    "TIA-942-B-2017 Rev Full.pdf",
    "2024_ASHRAE_content.pdf",
)


def _make_pdf(path: Path, texts: list[str]) -> Path:
    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()
    return path


def _make_pdf_with_image(path: Path) -> Path:
    image = Image.new("RGB", (24, 24), color=(220, 20, 60))
    buf = io.BytesIO()
    image.save(buf, format="PNG")

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "audit sample", fontsize=12, fontname="helv")
    page.insert_image(fitz.Rect(72, 100, 160, 188), stream=buf.getvalue())
    doc.save(path)
    doc.close()
    return path


def _make_pdf_with_many_images(path: Path, image_count: int = 4) -> Path:
    doc = fitz.open()
    for index in range(image_count):
        image = Image.new("RGB", (48, 48), color=((20 + index * 30) % 255, 120, 220))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        payload = buf.getvalue()
        page = doc.new_page()
        page.insert_text((72, 72), f"image page {index + 1}", fontsize=12, fontname="helv")
        page.insert_image(fitz.Rect(72, 100, 220, 248), stream=payload)
    doc.save(path)
    doc.close()
    return path


def _large_pdf_path(name: str) -> Path:
    path = REPO_ROOT / "test_files" / name
    if not path.exists():
        pytest.skip(f"missing large test PDF: {path}")
    return path


def _make_encrypted_pdf(path: Path, user_pw: str, owner_pw: str = "ownerpw") -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "confidential content", fontsize=12, fontname="helv")
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw=owner_pw,
        user_pw=user_pw,
        permissions=int(fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY),
    )
    doc.close()
    return path


def _pump_events(ms: int = 100) -> None:
    app = QApplication.instance()
    assert app is not None
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _wait_until(predicate, timeout_ms: int = 1000) -> bool:
    app = QApplication.instance()
    assert app is not None
    end = time.time() + timeout_ms / 1000.0
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def mvc(monkeypatch, qapp):
    monkeypatch.setattr("controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)

    from controller.pdf_controller import PDFController
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    yield model, view, controller
    model.close()
    view.close()
    _pump_events(50)


def test_optimize_dialog_defaults_to_balanced_and_switches_to_custom(qapp) -> None:
    from view.pdf_view import OptimizePdfDialog

    dialog = OptimizePdfDialog()

    assert dialog.preset_combo.currentText() == "平衡"
    assert dialog.image_target_dpi_suffix.text() == "dpi"
    assert dialog.image_threshold_dpi_suffix.text() == "dpi"
    assert dialog.image_quality_slider.value() == 60

    dialog.metadata_checkbox.setChecked(not dialog.metadata_checkbox.isChecked())

    assert dialog.preset_combo.currentText() == "自訂"


def test_pdf_model_optimizer_facade_uses_internal_module() -> None:
    from model.pdf_model import PDFModel
    from model.pdf_optimizer import PdfOptimizeOptions as InternalPdfOptimizeOptions

    options = PDFModel.preset_optimize_options("平衡")

    assert isinstance(options, InternalPdfOptimizeOptions)
    assert options.preset == "平衡"


def test_fast_preset_enables_object_streams(tmp_path: Path) -> None:
    """R4.5: 快速 must enable object streams (cheap structural shrink).

    It is the only preset where the flip is both effective and unblocked: 平衡 already
    sets it True, 極致壓縮 forces linearize=True (which strips objstms in
    normalize_optimize_options). 快速 has linearize=False, so the flip survives
    normalization and reaches the save settings as use_objstms=1.
    """
    from model.pdf_model import PDFModel
    from model.pdf_optimizer import fast_save_kwargs, normalize_optimize_options

    options = PDFModel.preset_optimize_options("快速")
    assert options.use_object_streams is True
    # linearize is False, so normalization must NOT strip object streams.
    assert options.linearize is False
    normalized = normalize_optimize_options(options)
    assert normalized.use_object_streams is True
    # The win must actually reach the PyMuPDF save settings (use_objstms=1).
    assert fast_save_kwargs(normalized)["use_objstms"] == 1


def test_file_tab_exposes_optimize_copy_action(mvc) -> None:
    _model, view, _controller = mvc

    action = getattr(view, "_action_optimize_copy", None)

    assert action is not None
    assert action.text() == "另存為最佳化的副本"


def test_save_optimized_copy_uses_working_doc_and_preserves_live_doc(tmp_path: Path) -> None:
    from model.pdf_model import PDFModel, PdfOptimizeOptions

    source = _make_pdf_with_image(tmp_path / "source.pdf")
    output = tmp_path / "optimized.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        before_bytes = model.doc.tobytes(no_new_id=1)

        result = model.save_optimized_copy(str(output), PdfOptimizeOptions())

        after_bytes = model.doc.tobytes(no_new_id=1)

        assert output.exists() is True
        assert result.output_path == str(output)
        assert result.optimized_bytes > 0
        assert before_bytes == after_bytes
    finally:
        model.close()


def test_save_optimized_copy_preserves_encryption(tmp_path: Path) -> None:
    """R5.5: optimizing an encrypted PDF must not silently drop password protection.

    Before the fix, the working doc is rebuilt from decrypted ``tobytes`` and saved
    without encryption, so 另存為最佳化的副本 of a password-protected PDF produced an
    unprotected copy. Option A re-applies the session password to the optimized output.
    """
    from model.pdf_model import PDFModel

    source = _make_encrypted_pdf(tmp_path / "encrypted-source.pdf", user_pw="secret")
    output = tmp_path / "encrypted-optimized.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source), password="secret")
        model.save_optimized_copy(str(output), model.preset_optimize_options("平衡"))

        # Fresh handle rejects the wrong password (still locked).
        wrong = fitz.open(str(output))
        try:
            assert wrong.needs_pass, (
                "optimized copy of an encrypted PDF must remain password-protected"
            )
            assert wrong.authenticate("wrong-password") == 0, (
                "optimized copy must reject an incorrect password"
            )
        finally:
            wrong.close()

        # Fresh handle opens with the original password.
        reopened = fitz.open(str(output))
        try:
            assert reopened.needs_pass
            assert reopened.authenticate("secret") != 0, (
                "optimized copy must open with the original password"
            )
        finally:
            reopened.close()
    finally:
        model.close()


def test_optimized_copy_keeps_user_auth_as_user_not_owner(tmp_path: Path) -> None:
    """R5-02: a source opened with a restricted *user* password must not be promoted to
    owner access in the optimized copy (the old code wrote owner_pw == user_pw)."""
    from model.pdf_model import PDFModel

    source = _make_encrypted_pdf(tmp_path / "user-source.pdf", user_pw="secret", owner_pw="ownerpw")
    # Sanity: the fixture is a genuine user/owner split.
    probe = fitz.open(str(source))
    try:
        assert probe.authenticate("secret") == 2, "fixture user password should auth as user (2)"
    finally:
        probe.close()
    probe2 = fitz.open(str(source))
    try:
        assert probe2.authenticate("ownerpw") in (4, 6), "fixture owner password should auth as owner"
    finally:
        probe2.close()

    output = tmp_path / "user-optimized.pdf"
    model = PDFModel()
    try:
        model.open_pdf(str(source), password="secret")  # user-level auth (auth_level == 2)
        model.save_optimized_copy(str(output), model.preset_optimize_options("平衡"))
    finally:
        model.close()

    out = fitz.open(str(output))
    try:
        assert out.needs_pass, "optimized copy of an encrypted source must stay protected"
        level = out.authenticate("secret")
        assert level == 2, (
            f"user credential must authenticate as user (2) in the copy, got {level} — "
            f"R5-02 promotion (owner_pw == user_pw)"
        )
        assert not (int(out.permissions) & int(fitz.PDF_PERM_MODIFY)), (
            "user-level copy must not grant modify permission (permission mask promoted)"
        )
    finally:
        out.close()


def test_optimized_copy_uses_descriptor_captured_before_background(
    tmp_path: Path, monkeypatch
) -> None:
    """R5-03: encryption is decided from an immutable descriptor captured up front, not
    from live model state read after the (background) optimize completes."""
    from model.pdf_model import PDFModel

    source = _make_encrypted_pdf(tmp_path / "race-source.pdf", user_pw="secret", owner_pw="ownerpw")
    output = tmp_path / "race-optimized.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source), password="secret")
        # Simulate an active-session change landing AFTER the working doc is written but
        # before re-encryption: mutate the live password the buggy code reads at the end.
        original_save = model._save_optimized_working_doc

        def _save_then_switch(working_doc, dest, opts):
            original_save(working_doc, dest, opts)
            model.password = "intruder-pw"

        monkeypatch.setattr(model, "_save_optimized_working_doc", _save_then_switch)
        model.save_optimized_copy(str(output), model.preset_optimize_options("平衡"))
    finally:
        model.close()

    out = fitz.open(str(output))
    try:
        assert out.authenticate("secret") != 0, (
            "copy must open with the ORIGINAL password captured before the switch (R5-03)"
        )
    finally:
        out.close()
    out2 = fitz.open(str(output))
    try:
        assert out2.authenticate("intruder-pw") == 0, (
            "copy must NOT be encrypted with the switched-in live password (R5-03 race)"
        )
    finally:
        out2.close()


def test_optimized_copy_failure_leaves_no_plaintext_at_output(
    tmp_path: Path, monkeypatch
) -> None:
    """R5-04: if re-encryption fails, the destination must not be left holding plaintext."""
    import model.pdf_optimizer as optimizer_mod
    from model.pdf_model import PDFModel

    source = _make_encrypted_pdf(tmp_path / "fail-source.pdf", user_pw="secret", owner_pw="ownerpw")
    output = tmp_path / "fail-optimized.pdf"

    def _boom(*args, **kwargs):
        raise RuntimeError("injected encryption failure")

    monkeypatch.setattr(optimizer_mod, "reapply_source_encryption", _boom)

    model = PDFModel()
    try:
        model.open_pdf(str(source), password="secret")
        with pytest.raises(optimizer_mod.PdfOptimizeError):
            model.save_optimized_copy(str(output), model.preset_optimize_options("平衡"))
    finally:
        model.close()

    assert not output.exists(), (
        "a failed encrypted optimize must not leave a plaintext file at the output path (R5-04)"
    )


def test_optimize_binds_to_passed_session_not_active(tmp_path: Path) -> None:
    """R5-03 (Codex F1/F2): optimize must read the *requested* session's document, not
    whichever tab is active when the background worker runs."""
    from model.pdf_model import PDFModel

    a = _make_pdf(tmp_path / "A.pdf", ["AAAA-doc-A-content"])
    b = _make_pdf(tmp_path / "B.pdf", ["BBBB-doc-B-content"])
    output = tmp_path / "bound-optimized.pdf"

    model = PDFModel()
    try:
        a_sid = model.open_pdf(str(a))
        b_sid = model.open_pdf(str(b), append=True)  # B becomes active
        assert model.get_active_session_id() == b_sid
        # Request optimization of A while B is the active tab.
        model.save_optimized_copy(
            str(output), model.preset_optimize_options("平衡"), session_id=a_sid
        )
    finally:
        model.close()

    doc = fitz.open(str(output))
    try:
        text = "".join(page.get_text() for page in doc)
        assert "AAAA-doc-A-content" in text, "optimize must use the requested session A's content"
        assert "BBBB-doc-B-content" not in text, "optimize leaked the active session B's content"
    finally:
        doc.close()


def test_optimize_preserves_owner_only_encryption(tmp_path: Path) -> None:
    """R5-02 (Codex F3): an owner-password-only source (blank user password, restricted
    permissions) must not become an unprotected, unrestricted optimized copy."""
    from model.pdf_model import PDFModel

    src = tmp_path / "owner-only.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "restricted", fontsize=12, fontname="helv")
    doc.save(
        str(src),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="ownerpw",
        user_pw="",  # blank user password -> opens without a prompt, but copy is restricted
        permissions=int(fitz.PDF_PERM_PRINT),  # copy/modify NOT granted
    )
    doc.close()

    probe = fitz.open(str(src))
    try:
        assert not probe.needs_pass, "owner-only source should open without a password"
        assert (probe.metadata or {}).get("encryption"), "fixture must actually be encrypted"
    finally:
        probe.close()

    output = tmp_path / "owner-only-optimized.pdf"
    model = PDFModel()
    try:
        model.open_pdf(str(src))  # no password needed
        model.save_optimized_copy(str(output), model.preset_optimize_options("平衡"))
    finally:
        model.close()

    res = fitz.open(str(output))
    try:
        assert (res.metadata or {}).get("encryption"), (
            "owner-only encryption must be preserved in the optimized copy (R5-02)"
        )
        assert not (int(res.permissions) & int(fitz.PDF_PERM_COPY)), (
            "the copy restriction must survive optimization"
        )
    finally:
        res.close()


def test_save_optimized_copy_avoids_live_doc_tobytes_for_clean_session(
    tmp_path: Path, monkeypatch
) -> None:
    from model.pdf_model import PDFModel, PdfOptimizeOptions

    source = _make_pdf_with_image(tmp_path / "clean-source.pdf")
    output = tmp_path / "clean-optimized.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        original_tobytes = fitz.Document.tobytes

        def guarded_tobytes(self, *args, **kwargs):
            if self is model.doc:
                raise AssertionError("clean file-backed optimize should not serialize the live document")
            return original_tobytes(self, *args, **kwargs)

        monkeypatch.setattr(fitz.Document, "tobytes", guarded_tobytes)

        result = model.save_optimized_copy(str(output), PdfOptimizeOptions())

        assert output.exists() is True
        assert result.output_path == str(output)
        assert result.optimized_bytes > 0
    finally:
        model.close()


def test_save_optimized_copy_prefers_parallel_image_rewrite_for_clean_source(
    tmp_path: Path, monkeypatch
) -> None:
    from model.pdf_model import PDFModel, PdfOptimizeOptions

    source = _make_pdf_with_many_images(tmp_path / "parallel-source.pdf")
    output = tmp_path / "parallel-optimized.pdf"

    calls: list[dict] = []

    def fake_parallel(self, working_doc, image_usage, options, source_path):
        calls.append(
            {
                "image_count": len(image_usage),
                "source_path": str(source_path),
                "preset": options.preset,
            }
        )

    monkeypatch.setattr(
        PDFModel,
        "_rewrite_images_from_source_in_parallel",
        fake_parallel,
        raising=False,
    )

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        result = model.save_optimized_copy(str(output), PdfOptimizeOptions())

        assert output.exists() is True
        assert result.optimized_bytes > 0
        assert calls
        assert calls[0]["image_count"] >= 4
        assert calls[0]["source_path"] == str(source.resolve())
    finally:
        model.close()


def test_save_optimized_copy_prefers_parallel_image_rewrite_for_dirty_session(
    tmp_path: Path, monkeypatch
) -> None:
    from model.pdf_model import PDFModel, PdfOptimizeOptions

    source = _make_pdf_with_many_images(tmp_path / "dirty-parallel-source.pdf")
    output = tmp_path / "dirty-parallel-optimized.pdf"

    calls: list[dict] = []

    def fake_parallel(self, working_doc, extracted_images, options):
        calls.append(
            {
                "image_count": len(extracted_images),
                "preset": options.preset,
            }
        )

    monkeypatch.setattr(
        PDFModel,
        "_rewrite_extracted_images_in_parallel",
        fake_parallel,
        raising=False,
    )

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        active_sid = model.get_active_session_id()
        assert active_sid is not None
        monkeypatch.setattr(model, "session_has_unsaved_changes", lambda session_id: session_id == active_sid)

        result = model.save_optimized_copy(str(output), PdfOptimizeOptions())

        assert output.exists() is True
        assert result.optimized_bytes > 0
        assert calls
        assert calls[0]["image_count"] >= 4
    finally:
        model.close()


def test_fast_preset_skips_content_cleanup(tmp_path: Path, monkeypatch) -> None:
    from model.pdf_model import PDFModel

    source = _make_pdf_with_image(tmp_path / "fast-cleanup-source.pdf")
    output = tmp_path / "fast-cleanup-output.pdf"

    clean_calls: list[int] = []

    def fake_clean_contents(page):
        clean_calls.append(page.number)

    monkeypatch.setattr(fitz.Page, "clean_contents", fake_clean_contents)

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        result = model.save_optimized_copy(str(output), model.preset_optimize_options("快速"))

        assert result.optimized_bytes > 0
        assert clean_calls == []
    finally:
        model.close()


def test_fast_preset_skips_font_subsetting(tmp_path: Path, monkeypatch) -> None:
    from model.pdf_model import PDFModel

    source = _make_pdf_with_image(tmp_path / "fast-font-source.pdf")
    output = tmp_path / "fast-font-output.pdf"

    subset_calls: list[int] = []

    def fake_subset_fonts(doc):
        subset_calls.append(len(doc))

    monkeypatch.setattr(fitz.Document, "subset_fonts", fake_subset_fonts)

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        result = model.save_optimized_copy(str(output), model.preset_optimize_options("快速"))

        assert result.optimized_bytes > 0
        assert subset_calls == []
    finally:
        model.close()


def test_balanced_preset_keeps_cleanup_and_subset_for_small_jobs(tmp_path: Path, monkeypatch) -> None:
    from model.pdf_model import PDFModel

    source = _make_pdf_with_image(tmp_path / "balanced-small-source.pdf")
    output = tmp_path / "balanced-small-output.pdf"

    clean_calls: list[int] = []
    subset_calls: list[int] = []

    def fake_clean_contents(page):
        clean_calls.append(page.number)

    def fake_subset_fonts(doc):
        subset_calls.append(len(doc))

    monkeypatch.setattr(fitz.Page, "clean_contents", fake_clean_contents)
    monkeypatch.setattr(fitz.Document, "subset_fonts", fake_subset_fonts)

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        result = model.save_optimized_copy(str(output), model.preset_optimize_options("平衡"))

        assert result.optimized_bytes > 0
        assert clean_calls
        assert subset_calls
    finally:
        model.close()


def test_balanced_preset_skips_cleanup_for_large_jobs(tmp_path: Path, monkeypatch) -> None:
    from model.pdf_model import PDFModel
    from model import pdf_optimizer

    source = _make_pdf_with_many_images(tmp_path / "balanced-large-source.pdf", image_count=40)
    output = tmp_path / "balanced-large-output.pdf"

    clean_calls: list[int] = []
    subset_calls: list[int] = []
    rewrite_calls: list[int] = []

    def fake_clean_contents(page):
        clean_calls.append(page.number)

    def fake_subset_fonts(doc):
        subset_calls.append(len(doc))

    def fake_rewrite_images(
        self,
        working_doc,
        options,
        source_path=None,
        *,
        image_usage=None,
        allow_extracted_parallel_fallback=True,
    ):
        rewrite_calls.append(len(working_doc))

    monkeypatch.setattr(fitz.Page, "clean_contents", fake_clean_contents)
    monkeypatch.setattr(fitz.Document, "subset_fonts", fake_subset_fonts)
    monkeypatch.setattr(PDFModel, "_rewrite_images_with_pillow", fake_rewrite_images, raising=False)
    monkeypatch.setattr(pdf_optimizer, "is_large_optimize_job", lambda original_bytes, image_usage: True)

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        result = model.save_optimized_copy(str(output), model.preset_optimize_options("平衡"))

        assert result.optimized_bytes > 0
        assert clean_calls == []
        assert subset_calls
        assert rewrite_calls
    finally:
        model.close()


def test_extreme_preset_keeps_cleanup_and_subset_for_large_jobs(tmp_path: Path, monkeypatch) -> None:
    from model.pdf_model import PDFModel

    source = _make_pdf_with_many_images(tmp_path / "extreme-large-source.pdf", image_count=40)
    output = tmp_path / "extreme-large-output.pdf"

    clean_calls: list[int] = []
    subset_calls: list[int] = []

    def fake_clean_contents(page):
        clean_calls.append(page.number)

    def fake_subset_fonts(doc):
        subset_calls.append(len(doc))

    monkeypatch.setattr(fitz.Page, "clean_contents", fake_clean_contents)
    monkeypatch.setattr(fitz.Document, "subset_fonts", fake_subset_fonts)

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        result = model.save_optimized_copy(str(output), model.preset_optimize_options("極致壓縮"))

        assert result.optimized_bytes > 0
        assert clean_calls
        assert subset_calls
    finally:
        model.close()


def test_save_optimized_copy_dirty_session_preserves_unsaved_edits(tmp_path: Path, monkeypatch) -> None:
    from model.pdf_model import PDFModel, PdfOptimizeOptions

    source = _make_pdf(tmp_path / "dirty-source.pdf", ["original text"])
    output = tmp_path / "dirty-output.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        active_sid = model.get_active_session_id()
        assert active_sid is not None
        model.doc[0].insert_text((72, 140), "unsaved edit", fontsize=12, fontname="helv")
        monkeypatch.setattr(model, "session_has_unsaved_changes", lambda session_id: session_id == active_sid)

        result = model.save_optimized_copy(str(output), PdfOptimizeOptions(optimize_images=False))

        assert result.optimized_bytes > 0
        with fitz.open(str(output)) as optimized_doc:
            assert "unsaved edit" in optimized_doc[0].get_text("text")
    finally:
        model.close()


@pytest.mark.parametrize("preset_name", ["快速", "平衡", "極致壓縮"])
def test_save_optimized_copy_accepts_all_presets(tmp_path: Path, preset_name: str) -> None:
    from model.pdf_model import PDFModel

    source = _make_pdf_with_image(tmp_path / f"{preset_name}-source.pdf")
    output = tmp_path / f"{preset_name}-optimized.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        result = model.save_optimized_copy(str(output), model.preset_optimize_options(preset_name))

        assert output.exists() is True
        assert result.output_path == str(output)
        assert result.optimized_bytes > 0
        assert result.applied_preset == preset_name
    finally:
        model.close()


def test_build_pdf_audit_report_groups_known_categories(tmp_path: Path) -> None:
    from model.pdf_model import PDFModel

    source = _make_pdf_with_image(tmp_path / "audit.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        report = model.build_pdf_audit_report()
    finally:
        model.close()

    categories = {item.label: item for item in report.items}
    assert "圖片" in categories
    assert "字體" in categories
    assert "內容串流" in categories
    assert "其他/未分類" in categories
    assert report.total_bytes >= 1
    assert categories["圖片"].bytes_used >= 1
    assert categories["字體"].bytes_used >= 1


def test_build_pdf_audit_report_caches_active_document_results(tmp_path: Path, monkeypatch) -> None:
    from model.pdf_model import PDFModel

    source = _make_pdf_with_image(tmp_path / "audit-cache.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        calls: list[int] = []
        original_xref_size_bytes = PDFModel._xref_size_bytes

        def counting_xref_size_bytes(doc, xref: int) -> int:
            calls.append(int(xref))
            return original_xref_size_bytes(doc, xref)

        monkeypatch.setattr(PDFModel, "_xref_size_bytes", staticmethod(counting_xref_size_bytes))

        report1 = model.build_pdf_audit_report()
        first_call_count = len(calls)
        report2 = model.build_pdf_audit_report()

        assert first_call_count > 0
        assert len(calls) == first_call_count
        assert report2 == report1

        model.doc[0].insert_text((72, 220), "cache bust", fontsize=12, fontname="helv")
        model.edit_count += 1

        report3 = model.build_pdf_audit_report()

        assert len(calls) > first_call_count
        assert report3.total_bytes >= report2.total_bytes
    finally:
        model.close()


def test_pdf_audit_report_dialog_uses_table_and_stacked_bar(qapp, tmp_path: Path) -> None:
    from model.pdf_model import PDFModel
    from view.pdf_view import PdfAuditReportDialog

    source = _make_pdf_with_image(tmp_path / "audit-dialog.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        report = model.build_pdf_audit_report()
    finally:
        model.close()

    dialog = PdfAuditReportDialog(report)

    assert dialog.table.rowCount() == len(report.items)
    assert dialog.table.columnCount() == 4
    assert dialog.stacked_bar.segment_count() >= 1
    assert dialog.layout().indexOf(dialog.hover_name_label) < dialog.layout().indexOf(dialog.stacked_bar)
    tooltips = dialog.stacked_bar.segment_tooltips()
    meaningful_labels = {item.label for item in report.items if item.bytes_used > 0}
    assert tooltips
    assert all(tip in meaningful_labels for tip in tooltips)
    dialog.stacked_bar.hovered_label_changed.emit(tooltips[0])
    assert tooltips[0] in dialog.hover_name_label.text()


def test_start_optimize_pdf_copy_saves_and_opens_new_tab(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf_with_image(tmp_path / "Current.pdf")
    output = tmp_path / "Current.optimized.pdf"
    controller.open_pdf(str(current))
    _pump_events(120)

    original_sid = model.get_active_session_id()
    original_meta = model.get_session_meta(original_sid)
    original_page_count = len(model.doc)

    import view.pdf_view as pdf_view_module

    def fake_exec(self) -> int:
        return QDialog.Accepted

    monkeypatch.setattr(pdf_view_module.OptimizePdfDialog, "exec", fake_exec)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "PDF (*.pdf)")),
    )

    controller.start_optimize_pdf_copy()
    assert _wait_until(lambda: len(model.session_ids) == 2, timeout_ms=1500)

    assert output.exists() is True
    assert len(model.session_ids) == 2
    assert model.get_active_session_id() != original_sid

    controller._switch_to_session_id(original_sid)
    _pump_events(50)
    assert len(model.doc) == original_page_count
    assert model.get_session_meta(original_sid)["path"] == original_meta["path"]


def test_start_optimize_pdf_copy_rejects_current_path_collision(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf_with_image(tmp_path / "Current.pdf")
    controller.open_pdf(str(current))
    _pump_events(120)

    errors: list[str] = []
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda _view, msg: errors.append(str(msg)))

    import view.pdf_view as pdf_view_module

    monkeypatch.setattr(pdf_view_module.OptimizePdfDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(current), "PDF (*.pdf)")),
    )

    controller.start_optimize_pdf_copy()
    _pump_events(50)

    assert len(model.session_ids) == 1
    assert errors
    assert any("新的輸出路徑" in msg for msg in errors)


def test_start_optimize_pdf_copy_runs_work_in_background(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf_with_image(tmp_path / "Current.pdf")
    output = tmp_path / "Current.optimized.pdf"
    controller.open_pdf(str(current))
    _pump_events(120)

    import view.pdf_view as pdf_view_module
    from model.pdf_model import PdfOptimizationResult

    monkeypatch.setattr(pdf_view_module.OptimizePdfDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "PDF (*.pdf)")),
    )

    def fake_save_optimized_copy(_model, _snapshot, path: str, _options, credentials=None):
        time.sleep(0.25)
        shutil.copy2(str(current), path)
        return PdfOptimizationResult(
            output_path=path,
            original_bytes=current.stat().st_size,
            optimized_bytes=Path(path).stat().st_size,
            bytes_saved=0,
            percent_saved=0.0,
            applied_preset="平衡",
            applied_summary=["平衡"],
        )

    monkeypatch.setattr(
        "controller.pdf_controller.pdf_optimizer.save_optimized_copy_from_snapshot",
        fake_save_optimized_copy,
    )

    start = time.time()
    controller.start_optimize_pdf_copy()
    elapsed = time.time() - start

    assert elapsed < 0.15
    _pump_events(500)
    assert len(model.session_ids) == 2


def test_start_optimize_pdf_copy_cancels_active_background_loading(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf_with_image(tmp_path / "Current.pdf")
    output = tmp_path / "Current.optimized.pdf"
    controller.open_pdf(str(current))
    _pump_events(120)

    sid = model.get_active_session_id()
    assert sid is not None
    load_gen_before = controller._load_gen_by_session.get(sid, 0)
    stale_gen_before = controller._stale_index_gen_by_session.get(sid, 0)

    import view.pdf_view as pdf_view_module
    from model.pdf_model import PdfOptimizationResult

    monkeypatch.setattr(pdf_view_module.OptimizePdfDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "PDF (*.pdf)")),
    )

    def fake_save_optimized_copy(_model, _snapshot, path: str, _options, credentials=None):
        time.sleep(0.25)
        shutil.copy2(str(current), path)
        return PdfOptimizationResult(
            output_path=path,
            original_bytes=current.stat().st_size,
            optimized_bytes=Path(path).stat().st_size,
            bytes_saved=0,
            percent_saved=0.0,
            applied_preset="平衡",
            applied_summary=["平衡"],
        )

    monkeypatch.setattr(
        "controller.pdf_controller.pdf_optimizer.save_optimized_copy_from_snapshot",
        fake_save_optimized_copy,
    )

    controller.start_optimize_pdf_copy()

    assert controller._load_gen_by_session[sid] > load_gen_before
    assert controller._stale_index_gen_by_session[sid] > stale_gen_before
    assert _wait_until(lambda: controller._optimize_thread is None, timeout_ms=2000)


def test_start_optimize_pdf_copy_completion_message_uses_human_units(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf_with_image(tmp_path / "Current.pdf")
    output = tmp_path / "Current.optimized.pdf"
    controller.open_pdf(str(current))
    _pump_events(120)

    import view.pdf_view as pdf_view_module
    from model.pdf_model import PdfOptimizationResult

    messages: list[str] = []
    monkeypatch.setattr(
        "controller.pdf_controller.QMessageBox.information",
        staticmethod(lambda _parent, _title, text: messages.append(str(text))),
    )
    monkeypatch.setattr(pdf_view_module.OptimizePdfDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "PDF (*.pdf)")),
    )

    def fake_save_optimized_copy(_model, _snapshot, path: str, _options, credentials=None):
        shutil.copy2(str(current), path)
        return PdfOptimizationResult(
            output_path=path,
            original_bytes=8 * 1024 * 1024,
            optimized_bytes=3 * 1024 * 1024,
            bytes_saved=5 * 1024 * 1024,
            percent_saved=62.5,
            applied_preset="撟唾﹛",
            applied_summary=["撟唾﹛"],
        )

    monkeypatch.setattr(
        "controller.pdf_controller.pdf_optimizer.save_optimized_copy_from_snapshot",
        fake_save_optimized_copy,
    )

    controller.start_optimize_pdf_copy()
    _pump_events(500)

    assert messages
    assert "MB" in messages[-1]


def test_format_size_units_covers_kb_mb_and_gb(mvc) -> None:
    _model, _view, controller = mvc

    assert controller._format_size_units(900) == "900 bytes"
    assert controller._format_size_units(1536) == "1.50 KB (1,536 bytes)"
    assert controller._format_size_units(8 * 1024 * 1024) == "8.00 MB (8,388,608 bytes)"
    assert controller._format_size_units(3 * 1024 * 1024 * 1024) == "3.00 GB (3,221,225,472 bytes)"


def test_pil_png_debug_logging_is_suppressed() -> None:
    import logging

    assert logging.getLogger("PIL.PngImagePlugin").getEffectiveLevel() >= logging.INFO


@pytest.mark.parametrize("source_name", LARGE_PDF_NAMES)
def test_large_file_optimize_submission_keeps_progress_dialog_responsive(
    mvc, monkeypatch, tmp_path: Path, source_name: str
) -> None:
    model, _view, controller = mvc
    current = _large_pdf_path(source_name)
    output = tmp_path / f"{current.stem}.optimized.pdf"
    controller.open_pdf(str(current))
    _pump_events(120)

    import view.pdf_view as pdf_view_module
    from model.pdf_model import PdfOptimizationResult

    monkeypatch.setattr(pdf_view_module.OptimizePdfDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "PDF (*.pdf)")),
    )

    def fake_save_optimized_copy(_model, _snapshot, path: str, _options, credentials=None):
        time.sleep(0.35)
        shutil.copy2(str(current), path)
        return PdfOptimizationResult(
            output_path=path,
            original_bytes=current.stat().st_size,
            optimized_bytes=max(1, current.stat().st_size - 8 * 1024 * 1024),
            bytes_saved=min(current.stat().st_size - 1, 8 * 1024 * 1024),
            percent_saved=7.0,
            applied_preset="平衡",
            applied_summary=["平衡"],
        )

    monkeypatch.setattr(
        "controller.pdf_controller.pdf_optimizer.save_optimized_copy_from_snapshot",
        fake_save_optimized_copy,
    )

    start = time.time()
    controller.start_optimize_pdf_copy()
    elapsed = time.time() - start

    assert elapsed < 0.15
    assert controller._optimize_progress_dialog is not None
    assert controller._optimize_progress_dialog.isVisible()
    assert controller.view._action_optimize_copy.isEnabled() is False
    _pump_events(120)
    assert controller._optimize_progress_dialog is not None
    assert controller._optimize_progress_dialog.isVisible()
    assert _wait_until(lambda: len(model.session_ids) == 2, timeout_ms=2000)


@pytest.mark.parametrize("source_name", LARGE_PDF_NAMES)
def test_large_file_optimized_copy_passes_integrity_validation(tmp_path: Path, source_name: str) -> None:
    from test_scripts.validate_optimized_pdf import validate_pdf_integrity

    from model.pdf_model import PDFModel

    source = _large_pdf_path(source_name)
    output = tmp_path / f"{source.stem}.optimized.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        result = model.save_optimized_copy(str(output), model.preset_optimize_options("平衡"))
    finally:
        model.close()

    assert output.exists() is True
    assert result.optimized_bytes > 0
    integrity = validate_pdf_integrity(output)
    assert integrity["passed"] is True
    assert integrity["fitz"]["ok"] is True
    assert integrity["pikepdf"]["ok"] is True
    assert integrity["pypdf"]["ok"] is True


def test_save_optimized_working_doc_raises_domain_error_when_no_pikepdf_and_linearize(
    tmp_path: Path, monkeypatch
) -> None:
    from model import pdf_optimizer
    from model.pdf_model import PDFModel, PdfOptimizeOptions

    monkeypatch.setattr(pdf_optimizer, "_pikepdf", lambda: None)

    model = PDFModel()
    working_doc = fitz.open()
    working_doc.new_page()
    temp_save = tmp_path / "gated-working.pdf"
    try:
        with pytest.raises(RuntimeError) as excinfo:
            model._save_optimized_working_doc(working_doc, temp_save, PdfOptimizeOptions(linearize=True))

        err_cls = getattr(pdf_optimizer, "PdfOptimizeError", None)
        assert err_cls is not None
        assert isinstance(excinfo.value, err_cls)
        assert "pikepdf" in str(excinfo.value)
        assert temp_save.exists() is False
    finally:
        working_doc.close()
        model.close()


def test_optimize_capabilities_reflect_pikepdf_availability(monkeypatch) -> None:
    from model import pdf_optimizer
    from model.pdf_model import PDFModel

    monkeypatch.setattr(pdf_optimizer, "_pikepdf", lambda: None)
    caps_absent = pdf_optimizer.optimize_capabilities()

    assert caps_absent == {"linearize": False, "object_streams": True}
    assert PDFModel.optimize_capabilities() == caps_absent

    fake_pikepdf = object()
    monkeypatch.setattr(pdf_optimizer, "_pikepdf", lambda: fake_pikepdf)
    caps_present = pdf_optimizer.optimize_capabilities()

    assert caps_present == {"linearize": True, "object_streams": True}
    assert PDFModel.optimize_capabilities() == caps_present


def test_optimize_copy_error_is_not_double_prefixed(tmp_path: Path, monkeypatch) -> None:
    from model import pdf_optimizer
    from model.pdf_model import PDFModel, PdfOptimizeOptions

    monkeypatch.setattr(pdf_optimizer, "_pikepdf", lambda: None)
    source = _make_pdf(tmp_path / "noprefix-source.pdf", ["double prefix probe"])
    output = tmp_path / "noprefix-output.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        with pytest.raises(RuntimeError) as excinfo:
            model.save_optimized_copy(str(output), PdfOptimizeOptions(optimize_images=False, linearize=True))

        message = str(excinfo.value)
        assert not message.startswith("最佳化 PDF 失敗: 最佳化 PDF 失敗:")
        err_cls = getattr(pdf_optimizer, "PdfOptimizeError", None)
        assert err_cls is not None
        assert isinstance(excinfo.value, err_cls)
        assert "pikepdf" in message
        assert output.exists() is False
    finally:
        model.close()


def test_optimize_dialog_capability_gate_disables_and_unchecks(qapp) -> None:
    from view.pdf_view import OptimizePdfDialog

    dialog = OptimizePdfDialog(capabilities={"linearize": False, "object_streams": False})

    assert dialog.linearize_checkbox.isEnabled() is False
    assert dialog.linearize_checkbox.isChecked() is False
    assert dialog.object_streams_checkbox.isEnabled() is False
    assert dialog.object_streams_checkbox.isChecked() is False
    assert "pikepdf" in dialog.linearize_checkbox.toolTip()
    assert "pikepdf" in dialog.object_streams_checkbox.toolTip()
    # The capability gate must not flip the preset combo to 自訂.
    assert dialog.preset_combo.currentText() == "平衡"

    options = dialog.get_options()
    assert options.linearize is False
    assert options.use_object_streams is False


def test_optimize_dialog_preset_cannot_recheck_gated_checkbox(qapp) -> None:
    from view.pdf_view import OptimizePdfDialog

    dialog = OptimizePdfDialog(capabilities={"linearize": False, "object_streams": False})

    dialog.preset_combo.setCurrentText("極致壓縮")

    assert dialog.preset_combo.currentText() == "極致壓縮"
    assert dialog.linearize_checkbox.isChecked() is False
    assert dialog.object_streams_checkbox.isChecked() is False
    assert dialog.get_options().linearize is False
    assert dialog.get_options().use_object_streams is False


def test_optimize_dialog_without_capabilities_keeps_packaging_controls_enabled(qapp) -> None:
    from view.pdf_view import OptimizePdfDialog

    dialog = OptimizePdfDialog()

    assert dialog.linearize_checkbox.isEnabled() is True
    assert dialog.object_streams_checkbox.isEnabled() is True
    assert dialog.preset_combo.currentText() == "平衡"


def test_save_optimized_copy_with_linearize_succeeds_when_pikepdf_present(tmp_path: Path) -> None:
    from model import pdf_optimizer
    from model.pdf_model import PDFModel, PdfOptimizeOptions

    if pdf_optimizer._pikepdf() is None:
        pytest.skip("pikepdf not installed in this environment")

    source = _make_pdf_with_image(tmp_path / "linearize-source.pdf")
    output = tmp_path / "linearize-output.pdf"

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        result = model.save_optimized_copy(str(output), PdfOptimizeOptions(linearize=True))

        assert output.exists() is True
        assert result.optimized_bytes > 0
        with fitz.open(str(output)) as optimized_doc:
            assert len(optimized_doc) == 1
    finally:
        model.close()
