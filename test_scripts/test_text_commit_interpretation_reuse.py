"""P3-D Stage-A red-light tests: post-patch page interpretation reuse."""
from __future__ import annotations

import inspect
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.text_commit.engine as engine_module  # noqa: E402
import model.text_commit.patch as patch_module  # noqa: E402
import model.text_commit.preview as preview_module  # noqa: E402
from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import page_fingerprint, read_page_streams  # noqa: E402
from model.text_commit.interpretation import (  # noqa: E402
    PageInterpretation,
    interpret_page,
)
from model.text_commit.patch import PatchSet, apply_patchset  # noqa: E402
from model.text_commit.plan import PreparedEdit, prepare_plan  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)
from model.text_commit.verify import (  # noqa: E402
    VerificationFailure,
    capture_page_state,
    verify_tier0_commit,
)
from scripts.probe_p3d_interpretation_equivalence import (  # noqa: E402
    _fixture,
)

TARGET = "Price 2024"


def _stream_doc(*, rotate: int = 0, tier1: bool = False) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    target = b"iii" if tier1 else TARGET.encode()
    tail = b" /F1 9 Tf (            tail) Tj" if tier1 else b""
    stream = b"BT /F1 12 Tf 72 700 Td (" + target + b") Tj" + tail + b" ET"
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    if rotate:
        page.set_rotation(rotate)
    return doc


def _span(page: fitz.Page, target: str = TARGET) -> dict[str, Any]:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if target in "".join(ch["c"] for ch in span["chars"]):
                    return span
    raise AssertionError(target)


def _prepare(
    doc: fitz.Document,
    *,
    target: str = TARGET,
    replacement: str = "Price 2025",
    max_tier: int = 0,
) -> PreparedEdit:
    page = doc[0]
    plan = prepare_plan(
        doc,
        page,
        target_text=target,
        replacement_text=replacement,
        expected_origin=None,
        target_bbox=None,
        registry=DocumentFontRegistry(doc),
        max_tier=max_tier,
    )
    assert isinstance(plan, PreparedEdit), plan
    return plan


def _patchset(plan: PreparedEdit) -> PatchSet:
    return PatchSet(
        page_xref=plan.page_xref,
        replacements=(plan.replacement,),
        expected_page_fingerprint=plan.page_fingerprint,
    )


def _request(doc: fitz.Document, *, generation: int = 1) -> PlanPreviewRequest:
    return PlanPreviewRequest(
        session_key="p3d-stage-a",
        generation=generation,
        target_text=TARGET,
        replacement_text="Price 2025",
        expected_origin=None,
        target_bbox=None,
        clip_rect=tuple(float(v) for v in doc[0].rect),
        render_scale=1.5,
    )


def _pixmap_signature(pixmap: fitz.Pixmap) -> tuple[Any, ...]:
    return (
        tuple(pixmap.irect),
        pixmap.width,
        pixmap.height,
        pixmap.stride,
        pixmap.n,
        pixmap.alpha,
        pixmap.xres,
        pixmap.yres,
        bytes(pixmap.samples),
        pixmap.tobytes("png"),
    )


@pytest.mark.parametrize(
    "fixture",
    (
        _fixture("plain-a4"),
        _fixture("letter", width=612, height=792),
        _fixture("crop-rotate90", rotate=90, cropbox=(10.25, 20.5, 560.75, 800.25)),
        _fixture("unit-2.5-rotate270", rotate=270, user_unit=2.5),
        _fixture("unit-.4-crop-rotate180", rotate=180, user_unit=0.4, cropbox=(5.25, 10.5, 570.25, 820.5)),
        _fixture("inherited-rotate90", rotate=90, inherited_rotation=True),
        _fixture("type0-visible", type0=True, visible_oc=True),
        _fixture("type0-hidden", type0=True, hidden_oc=True),
        _fixture("rotated-tm", rotated_tm=True),
        _fixture("type3", type3=True),
        _fixture("off-page", off_page_text=True, cropbox=(20, 30, 570, 810)),
        _fixture("apless-rotate90", rotate=90, apless_annot=True),
        _fixture("freetext", free_text=True),
    ),
    ids=lambda fixture: fixture.name,
)
def test_interpretation_primitives_match_page_utilities(fixture) -> None:
    doc = fitz.open("pdf", fixture.pdf)
    page = doc[0]
    interpretation = interpret_page(page)
    try:
        assert _pixmap_signature(interpretation.pixmap(dpi=96)) == _pixmap_signature(
            page.get_pixmap(dpi=96, annots=True)
        )
        assert interpretation.rawdict() == page.get_text("rawdict")
        rng = random.Random(0xA93D)
        clips = [fitz.Rect(page.cropbox)]
        for _ in range(6):
            rect = page.cropbox
            x0 = rng.uniform(rect.x0, max(rect.x0, rect.x1 - 1))
            y0 = rng.uniform(rect.y0, max(rect.y0, rect.y1 - 1))
            clips.append(
                fitz.Rect(
                    x0,
                    y0,
                    rng.uniform(x0 + 0.1, rect.x1),
                    rng.uniform(y0 + 0.1, rect.y1),
                )
            )
        for clip in clips:
            assert interpretation.clipped_text(clip) == page.get_text("text", clip=clip)
        for matrix in (fitz.Matrix(1.333, 1.333), fitz.Matrix(1.5, 1.5), fitz.Matrix(2, 2), fitz.Matrix(3, 3)):
            clip = fitz.Rect(page.rect)
            assert _pixmap_signature(
                interpretation.pixmap(matrix=matrix, clip=clip)
            ) == _pixmap_signature(
                page.get_pixmap(matrix=matrix, clip=clip, annots=True)
            )
    finally:
        interpretation.release()
        doc.close()


def test_interpretation_restores_rotation_and_fingerprint() -> None:
    doc = _stream_doc(rotate=270)
    page = doc[0]
    before = (page.rotation, page_fingerprint(doc, page))
    interpretation = interpret_page(page)
    assert (page.rotation, page_fingerprint(doc, page)) == before
    assert interpretation._text_list is not interpretation._raster_list
    interpretation.release()
    doc.close()


def test_interpretation_reuses_one_list_when_unrotated() -> None:
    doc = _stream_doc()
    interpretation = interpret_page(doc[0])
    assert interpretation._text_list is interpretation._raster_list
    interpretation.release()
    doc.close()


@pytest.mark.parametrize("failure_call", (1, 2))
def test_interpretation_build_failure_restores_rotation(monkeypatch, failure_call: int) -> None:
    doc = _stream_doc(rotate=90)
    page = doc[0]
    original = fitz.Page.get_displaylist
    calls = 0

    def injected(page_self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise RuntimeError(f"displaylist failure {failure_call}")
        return original(page_self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_displaylist", injected)
    with pytest.raises(RuntimeError, match=f"displaylist failure {failure_call}"):
        interpret_page(page)
    assert page.rotation == 90
    doc.close()


def test_release_is_idempotent_and_methods_fail_after_release() -> None:
    doc = _stream_doc()
    interpretation = interpret_page(doc[0])
    interpretation.release()
    interpretation.release()
    for call in (
        lambda: interpretation.pixmap(),
        interpretation.rawdict,
        lambda: interpretation.clipped_text(fitz.Rect(0, 0, 20, 20)),
    ):
        with pytest.raises(RuntimeError, match="released"):
            call()
    doc.close()


def test_capture_page_state_interpretation_and_reuse_rawdict_parity(monkeypatch) -> None:
    doc = _stream_doc(tier1=True)
    page = doc[0]
    plan = _prepare(doc, target="iii", replacement="MMM", max_tier=1)
    assert plan.has_ink_growth
    default = capture_page_state(doc, page, plan)
    interpretation = interpret_page(page)
    try:
        assert capture_page_state(doc, page, plan, interpretation=interpretation) == default
    finally:
        interpretation.release()

    original = fitz.Page.get_textpage
    calls = 0

    def counting(page_self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(page_self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_textpage", counting)
    assert capture_page_state(doc, page, plan) == default
    assert calls == 2
    calls = 0
    assert capture_page_state(doc, page, plan, reuse_rawdict=True) == default
    assert calls == 1
    doc.close()


def test_verify_with_post_interpretation_matches_default() -> None:
    doc_default = _stream_doc()
    doc_reuse = _stream_doc()
    results = []
    for doc, reuse in ((doc_default, False), (doc_reuse, True)):
        page = doc[0]
        plan = _prepare(doc)
        pre = capture_page_state(doc, page, plan, reuse_rawdict=reuse)
        applied = apply_patchset(doc, page, _patchset(plan), compress=False)
        interpretation = interpret_page(page) if reuse else None
        try:
            results.append(
                verify_tier0_commit(
                    doc,
                    page,
                    plan,
                    pre,
                    interpretation=interpretation,
                )
            )
        finally:
            if interpretation is not None:
                interpretation.release()
            applied.revert(doc, compress=False)
    assert results[0] == results[1]
    assert not isinstance(results[0], VerificationFailure)
    doc_default.close()
    doc_reuse.close()


def test_preapply_interpretation_is_stale_and_fails_v0c() -> None:
    doc = _stream_doc()
    page = doc[0]
    plan = _prepare(doc)
    pre = capture_page_state(doc, page, plan)
    stale = interpret_page(page)
    applied = apply_patchset(doc, page, _patchset(plan), compress=False)
    try:
        result = verify_tier0_commit(doc, page, plan, pre, interpretation=stale)
        assert isinstance(result, VerificationFailure)
        assert result.reason == RejectReason.VERIFICATION_FAILED
        assert result.detail == "replacement text not extractable at the target"
    finally:
        stale.release()
        applied.revert(doc, compress=False)
        doc.close()


class LegacyPostInterpretation:
    def __init__(self, page: fitz.Page, engaged: list[bool]) -> None:
        self.page = page
        self.engaged = engaged

    def pixmap(self, *, dpi=None, matrix=fitz.Identity, clip=None):
        self.engaged.append(True)
        return self.page.get_pixmap(dpi=dpi, matrix=matrix, clip=clip, annots=True)

    def rawdict(self):
        self.engaged.append(True)
        return self.page.get_text("rawdict")

    def clipped_text(self, clip_dict_space):
        self.engaged.append(True)
        return self.page.get_text("text", clip=clip_dict_space)

    def release(self) -> None:
        self.engaged.append(True)


class PrimitiveCounter:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.counts: Counter[str] = Counter()
        for obj, name, key in (
            (fitz.Page, "get_pixmap", "page_pixmap"),
            (fitz.Page, "get_text", "page_text"),
            (fitz.Page, "get_textpage", "page_textpage"),
            (fitz.Page, "get_displaylist", "page_displaylist"),
            (fitz.DisplayList, "get_pixmap", "displaylist_pixmap"),
            (fitz.DisplayList, "get_textpage", "displaylist_textpage"),
            (PageInterpretation, "clipped_text", "clipped_stext"),
        ):
            original = getattr(obj, name)

            def counting(*args, _original=original, _key=key, **kwargs):
                self.counts[_key] += 1
                return _original(*args, **kwargs)

            monkeypatch.setattr(obj, name, counting)


def _render_counted(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rotate: int,
    legacy: bool,
) -> tuple[Any, Counter[str], list[bool]]:
    doc = _stream_doc(rotate=rotate)
    session = open_preview_session(doc, 0, "p3d-stage-a")
    assert session is not None
    renderer = PlanPreviewRenderer(session)

    class StageADisabledBaseline:
        def capture(self, scratch, page, prepared):
            return capture_page_state(
                scratch, page, prepared, reuse_rawdict=True
            )

        def clear(self) -> None:
            return None

    # Keep this file's explicit Stage-A contract available after the
    # conditional Stage-B cache becomes the production default.
    renderer._pre_state_baseline = StageADisabledBaseline()
    engaged: list[bool] = []
    if legacy:
        monkeypatch.setattr(
            preview_module,
            "interpret_page",
            lambda page: LegacyPostInterpretation(page, engaged),
        )
    else:
        original = preview_module.interpret_page

        def counted_interpret(page):
            engaged.append(True)
            return original(page)

        monkeypatch.setattr(preview_module, "interpret_page", counted_interpret)
    counter = PrimitiveCounter(monkeypatch)
    result = renderer.render(_request(doc))
    renderer.close()
    doc.close()
    return result, counter.counts, engaged


@pytest.mark.parametrize("rotate", (0, 270))
def test_preview_stage_a_counts_and_legacy_identity(monkeypatch, rotate: int) -> None:
    with monkeypatch.context() as shipped_patch:
        shipped, shipped_counts, shipped_engaged = _render_counted(
            shipped_patch, rotate=rotate, legacy=False
        )
    with monkeypatch.context() as legacy_patch:
        legacy, legacy_counts, legacy_engaged = _render_counted(
            legacy_patch, rotate=rotate, legacy=True
        )
    assert shipped.plan_token is not None, shipped.reject_reason
    assert legacy.plan_token is not None, legacy.reject_reason
    assert shipped_engaged and legacy_engaged
    assert (
        shipped.png_bytes,
        shipped.plan_token,
        shipped.reject_reason,
        shipped.clip_rect,
        shipped.prepared,
    ) == (
        legacy.png_bytes,
        legacy.plan_token,
        legacy.reject_reason,
        legacy.clip_rect,
        legacy.prepared,
    )
    assert shipped_counts["page_pixmap"] == 1
    assert shipped_counts["page_text"] == 2
    assert shipped_counts["page_textpage"] == 1
    assert shipped_counts["page_displaylist"] == (2 if rotate == 0 else 3)
    assert shipped_counts["displaylist_pixmap"] == 3
    assert shipped_counts["displaylist_textpage"] == 1
    assert shipped_counts["clipped_stext"] == 1
    assert legacy_counts["page_pixmap"] == 3
    assert legacy_counts["page_text"] == 3
    assert legacy_counts["page_textpage"] == 3
    assert legacy_counts["page_displaylist"] == 3
    assert legacy_counts["displaylist_textpage"] == 0
    assert legacy_counts["clipped_stext"] == 0


def test_preview_releases_before_revert(monkeypatch) -> None:
    doc = _stream_doc()
    session = open_preview_session(doc, 0, "p3d-stage-a")
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    events: list[str] = []
    real_interpret = preview_module.interpret_page
    real_revert = patch_module.AppliedPatch.revert

    def wrapped_interpret(page):
        interpretation = real_interpret(page)
        real_release = interpretation.release

        def release():
            events.append("release")
            real_release()

        interpretation.release = release
        return interpretation

    def wrapped_revert(applied, scratch, *, compress=True):
        events.append("revert")
        return real_revert(applied, scratch, compress=compress)

    monkeypatch.setattr(preview_module, "interpret_page", wrapped_interpret)
    monkeypatch.setattr(patch_module.AppliedPatch, "revert", wrapped_revert)
    result = renderer.render(_request(doc))
    assert result.plan_token is not None
    assert events[-2:] == ["release", "revert"]
    renderer.close()
    doc.close()


def test_interpret_page_exception_after_apply_reverts_exactly(monkeypatch) -> None:
    doc = _stream_doc()
    live_stream = tuple(read_page_streams(doc, doc[0]))
    session = open_preview_session(doc, 0, "p3d-stage-a")
    assert session is not None
    renderer = PlanPreviewRenderer(session)

    def fail_interpret(_page):
        raise RuntimeError("post interpretation failed")

    monkeypatch.setattr(preview_module, "interpret_page", fail_interpret)
    with pytest.raises(RuntimeError, match="post interpretation failed"):
        renderer.render(_request(doc))
    assert renderer._scratch is not None
    assert tuple(read_page_streams(renderer._scratch, renderer._scratch[0])) == live_stream
    renderer.close()
    doc.close()


def test_live_engine_source_has_no_preview_reuse_arguments() -> None:
    source = inspect.getsource(engine_module.TieredCommitEngine)
    assert "interpret_page" not in source
    assert "reuse_rawdict" not in source
    assert "interpretation=" not in source
    capture_signature = inspect.signature(capture_page_state)
    assert capture_signature.parameters["reuse_rawdict"].default is False
    assert capture_signature.parameters["interpretation"].default is None
