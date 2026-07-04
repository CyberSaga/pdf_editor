from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest


def _make_pdf(path: Path, text: str) -> Path:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


def test_optimize_request_types_are_frozen() -> None:
    from model.pdf_optimizer import OptimizeOutputCredentials, OptimizeSourceSnapshot

    credentials = OptimizeOutputCredentials(owner_password="owner", user_password="user")
    snapshot = OptimizeSourceSnapshot(
        session_id="sid",
        source_path="C:/source.pdf",
        source_size=12,
        source_mtime_ns=34,
        source_bytes=None,
        overlay_metadata=(),
        encryption=None,
        secure_save_required=False,
    )

    with pytest.raises(FrozenInstanceError):
        credentials.user_password = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.session_id = "other"  # type: ignore[misc]


def test_pdf_model_facade_reexports_immutable_optimize_types() -> None:
    from model.pdf_model import OptimizeOutputCredentials, OptimizeSourceSnapshot
    from model.pdf_optimizer import (
        OptimizeOutputCredentials as OptimizerCredentials,
        OptimizeSourceSnapshot as OptimizerSnapshot,
    )

    assert OptimizeOutputCredentials is OptimizerCredentials
    assert OptimizeSourceSnapshot is OptimizerSnapshot


def test_capture_rejects_missing_explicit_session_instead_of_using_active(tmp_path: Path) -> None:
    from model.pdf_model import PDFModel
    from model.pdf_optimizer import PdfOptimizeError, capture_optimize_source

    source = _make_pdf(tmp_path / "active.pdf", "ACTIVE")
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        with pytest.raises(PdfOptimizeError, match="session"):
            capture_optimize_source(model, "closed-or-missing")
    finally:
        model.close()


def test_clean_snapshot_is_file_descriptor_and_survives_session_close(tmp_path: Path) -> None:
    from model.pdf_model import PDFModel, PdfOptimizeOptions
    from model.pdf_optimizer import capture_optimize_source, save_optimized_copy_from_snapshot

    source = _make_pdf(tmp_path / "source.pdf", "BOUND-A")
    output = tmp_path / "output.pdf"
    model = PDFModel()
    try:
        sid = model.open_pdf(str(source))
        snapshot = capture_optimize_source(model, sid)
        assert snapshot.source_path == str(source.resolve())
        assert snapshot.source_bytes is None
        assert snapshot.source_size == source.stat().st_size
        assert snapshot.source_mtime_ns == source.stat().st_mtime_ns

        model.close_session(sid)
        save_optimized_copy_from_snapshot(model, snapshot, str(output), PdfOptimizeOptions(optimize_images=False))
    finally:
        model.close()

    with fitz.open(output) as result:
        assert "BOUND-A" in result[0].get_text()


def test_dirty_snapshot_freezes_document_and_overlay_state(tmp_path: Path) -> None:
    from model.pdf_model import PDFModel, PdfOptimizeOptions
    from model.pdf_optimizer import capture_optimize_source, save_optimized_copy_from_snapshot

    source = _make_pdf(tmp_path / "source.pdf", "ORIGINAL")
    output = tmp_path / "output.pdf"
    model = PDFModel()
    try:
        sid = model.open_pdf(str(source))
        model.doc[0].insert_text((72, 110), "UNSAVED")
        model.tools.watermark.add_watermark([1], "FROZEN-WATERMARK")
        snapshot = capture_optimize_source(model, sid)
        assert snapshot.source_path is None
        assert snapshot.source_bytes
        assert snapshot.overlay_metadata

        # Mutating and closing the live session after capture cannot alter the request.
        model.tools.watermark.update_watermark(
            model.tools.watermark.get_watermarks()[0]["id"], text="MUTATED-WATERMARK"
        )
        model.close_session(sid)
        save_optimized_copy_from_snapshot(model, snapshot, str(output), PdfOptimizeOptions(optimize_images=False))
    finally:
        model.close()

    with fitz.open(output) as result:
        text = result[0].get_text()
        assert "UNSAVED" in text
        assert "FROZEN-WATERMAR" in text
        assert "MUTATED-WATERMARK" not in text


def test_output_credentials_reject_both_blank() -> None:
    from model.pdf_optimizer import OptimizeOutputCredentials, PdfOptimizeError

    with pytest.raises(PdfOptimizeError, match="blank"):
        OptimizeOutputCredentials(owner_password="", user_password="")


def test_secure_snapshot_forces_garbage_four(tmp_path: Path, monkeypatch) -> None:
    from model.pdf_model import PDFModel, PdfOptimizeOptions
    from model.pdf_optimizer import capture_optimize_source, save_optimized_copy_from_snapshot

    source = _make_pdf(tmp_path / "source.pdf", "secure")
    output = tmp_path / "output.pdf"
    observed: list[dict[str, int]] = []
    model = PDFModel()
    try:
        sid = model.open_pdf(str(source))
        session = model._sessions_by_id[sid]
        session.secure_save_required = True
        snapshot = capture_optimize_source(model, sid)
        original = model._fast_save_kwargs

        def capture_kwargs(options):
            kwargs = original(options)
            observed.append(kwargs)
            return kwargs

        monkeypatch.setattr(model, "_fast_save_kwargs", capture_kwargs)
        save_optimized_copy_from_snapshot(model, snapshot, str(output), PdfOptimizeOptions(optimize_images=False))
    finally:
        model.close()

    assert [entry["garbage"] for entry in observed] == [4]


def test_plain_output_is_installed_atomically_from_sibling(tmp_path: Path, monkeypatch) -> None:
    import model.pdf_optimizer as optimizer
    from model.pdf_model import PDFModel, PdfOptimizeOptions

    source = _make_pdf(tmp_path / "source.pdf", "atomic")
    output = tmp_path / "output.pdf"
    replacements: list[tuple[Path, Path]] = []
    real_replace = optimizer.os.replace

    def recording_replace(src, dst):
        replacements.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(optimizer.os, "replace", recording_replace)
    model = PDFModel()
    try:
        sid = model.open_pdf(str(source))
        snapshot = optimizer.capture_optimize_source(model, sid)
        optimizer.save_optimized_copy_from_snapshot(
            model, snapshot, str(output), PdfOptimizeOptions(optimize_images=False)
        )
    finally:
        model.close()

    install_src, install_dst = replacements[-1]
    assert install_dst == output
    assert install_src.parent == output.parent
    assert install_src != output


def test_optimize_worker_consumes_snapshot_not_session_id(monkeypatch) -> None:
    import controller.pdf_controller as controller_module
    from controller.pdf_controller import OptimizePdfCopyRequest, _OptimizePdfCopyWorker
    from model.pdf_optimizer import OptimizeSourceSnapshot

    snapshot = OptimizeSourceSnapshot(
        session_id="captured",
        source_path="C:/captured.pdf",
        source_size=1,
        source_mtime_ns=2,
        source_bytes=None,
        overlay_metadata=(),
        encryption=None,
        secure_save_required=False,
    )
    request = OptimizePdfCopyRequest(
        output_path="C:/output.pdf", options=object(), source=snapshot
    )
    calls: list[OptimizeSourceSnapshot] = []

    def fake_save(model, source, output_path, options, credentials=None):
        calls.append(source)
        return object()

    monkeypatch.setattr(controller_module.pdf_optimizer, "save_optimized_copy_from_snapshot", fake_save)
    worker = _OptimizePdfCopyWorker(object(), request)
    worker.run()

    assert calls == [snapshot]


@pytest.mark.parametrize(
    ("auth_level", "known", "counterpart", "expected"),
    [
        (2, "user-known", "", ("", "user-known")),
        (4, "owner-known", "", ("owner-known", "")),
        (6, "shared", None, ("shared", "shared")),
        (None, None, "new-owner", ("new-owner", "")),
    ],
)
def test_rotated_credentials_preserve_known_auth_role(
    auth_level, known, counterpart, expected
) -> None:
    from model.pdf_optimizer import (
        EncryptionDescriptor,
        credentials_for_encryption,
    )

    descriptor = EncryptionDescriptor(
        "sid", known, fitz.PDF_ENCRYPT_AES_256, -1, auth_level, True
    )
    credentials = credentials_for_encryption(descriptor, counterpart)

    assert (credentials.owner_password, credentials.user_password) == expected


def test_owner_only_rotation_rejects_no_password_choice() -> None:
    from model.pdf_optimizer import (
        EncryptionDescriptor,
        PdfOptimizeError,
        credentials_for_encryption,
    )

    descriptor = EncryptionDescriptor(
        "sid", None, fitz.PDF_ENCRYPT_AES_256, -1, None, True
    )
    with pytest.raises(PdfOptimizeError, match="both be blank"):
        credentials_for_encryption(descriptor, "")


def test_app_close_waits_for_optimizer_worker() -> None:
    from controller.pdf_controller import PDFController

    calls: list[str] = []
    controller = PDFController.__new__(PDFController)
    controller._thumbnail_coordinator = SimpleNamespace(
        cancel=lambda: None, wait_for_done=lambda timeout_ms: True
    )
    controller._print_coordinator = SimpleNamespace(
        has_active_job=lambda: False, begin_close_pending=lambda: None
    )
    controller._optimize_thread = object()
    controller._optimize_worker = object()
    controller._optimize_paused_session_id = "sid"
    controller._set_optimize_ui_busy = lambda busy: None
    controller.view = SimpleNamespace(close=lambda: calls.append("closed"))
    event = SimpleNamespace(
        ignore=lambda: calls.append("ignored"), accept=lambda: calls.append("accepted")
    )

    controller.handle_app_close(event)
    assert calls == ["ignored"]

    controller._on_optimize_thread_finished()
    assert calls == ["ignored", "closed"]


def _controller_with_encryption(auth_level, password):
    from controller.pdf_controller import PDFController
    from model.pdf_optimizer import EncryptionDescriptor, OptimizeSourceSnapshot

    controller = PDFController.__new__(PDFController)
    controller.view = object()
    descriptor = EncryptionDescriptor(
        "sid", password, fitz.PDF_ENCRYPT_AES_256, -1, auth_level, True
    )
    source = OptimizeSourceSnapshot(
        session_id="sid",
        source_path="C:/source.pdf",
        source_size=1,
        source_mtime_ns=2,
        source_bytes=None,
        overlay_metadata=(),
        encryption=descriptor,
        secure_save_required=False,
    )
    return controller, source


def test_rotation_prompt_uses_editable_strong_default(monkeypatch) -> None:
    import controller.pdf_controller as controller_module

    controller, source = _controller_with_encryption(2, "known-user")
    defaults: list[str] = []

    def fake_get_text(_parent, _title, _label, _echo, default):
        defaults.append(default)
        return "edited-owner", True

    monkeypatch.setattr(controller_module.QInputDialog, "getText", fake_get_text)
    accepted, credentials = controller._prompt_optimize_output_credentials(source)

    assert accepted is True
    assert len(defaults[0]) >= 24
    assert credentials.owner_password == "edited-owner"
    assert credentials.user_password == "known-user"


def test_blank_counterpart_requires_warning_acknowledgement(monkeypatch) -> None:
    import controller.pdf_controller as controller_module

    controller, source = _controller_with_encryption(4, "known-owner")
    monkeypatch.setattr(
        controller_module.QInputDialog, "getText", lambda *args: ("", True)
    )
    monkeypatch.setattr(
        controller_module.QMessageBox,
        "question",
        lambda *args: controller_module.QMessageBox.No,
    )
    accepted, credentials = controller._prompt_optimize_output_credentials(source)
    assert accepted is False
    assert credentials is None

    monkeypatch.setattr(
        controller_module.QMessageBox,
        "question",
        lambda *args: controller_module.QMessageBox.Yes,
    )
    accepted, credentials = controller._prompt_optimize_output_credentials(source)
    assert accepted is True
    assert credentials.owner_password == "known-owner"
    assert credentials.user_password == ""


def test_shared_auth_skips_rotation_prompt(monkeypatch) -> None:
    import controller.pdf_controller as controller_module

    controller, source = _controller_with_encryption(6, "shared")
    monkeypatch.setattr(
        controller_module.QInputDialog,
        "getText",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not prompt")),
    )
    accepted, credentials = controller._prompt_optimize_output_credentials(source)
    assert accepted is True
    assert credentials.owner_password == "shared"
    assert credentials.user_password == "shared"


def test_close_pending_suppresses_optimizer_result_ui(monkeypatch) -> None:
    import controller.pdf_controller as controller_module
    from controller.pdf_controller import PDFController

    calls: list[str] = []
    controller = PDFController.__new__(PDFController)
    controller._optimize_close_pending = True
    controller._hide_optimize_progress_dialog = lambda: calls.append("hidden")
    controller.open_pdf = lambda path: calls.append(f"opened:{path}")
    controller.view = object()
    result = SimpleNamespace(output_path="C:/result.pdf")
    monkeypatch.setattr(
        controller_module.QMessageBox,
        "information",
        lambda *args: calls.append("message"),
    )
    monkeypatch.setattr(
        controller_module, "show_error", lambda *args: calls.append("error")
    )

    controller._on_optimize_copy_succeeded(result)
    controller._on_optimize_copy_failed(RuntimeError("failed"))

    assert calls == ["hidden", "hidden"]
