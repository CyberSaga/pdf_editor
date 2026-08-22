"""Task 13 P3-C red-light tests.

Disable Flate compression on the two ``fitz.Document.update_stream`` calls
``PlanPreviewRenderer.render`` makes per keystroke (apply + revert) -- both
land only on a session-scoped scratch document that is never serialized to
any artifact a user or the live document ever sees. The live commit path
(``TieredCommitEngine.commit``) and every other existing caller of
``apply_patchset``/``AppliedPatch.revert`` keep the default ``compress=True``
unchanged. See ``plans/task13-p3c-preview-postprepare-latency.md``.
"""
from __future__ import annotations

import gc
import sys
import tracemalloc
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import CommitStatus  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.evidence import compute_evidence_key  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import page_fingerprint, read_page_streams  # noqa: E402
from model.text_commit.patch import PatchSet, apply_patchset  # noqa: E402
from model.text_commit.plan import PreparedEdit, prepare_plan  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)
from model.text_commit.verify import capture_page_state, verify_tier0_commit  # noqa: E402

TARGET = "Price 2024"

_FONT_OBJECT = (
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
    "/Encoding /WinAnsiEncoding >>"
)


def _padded_stream(n_pad: int = 20_000) -> bytes:
    parts = [b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET\n"]
    line = bytearray()
    i = 0
    while len(line) < n_pad:
        a, b = (i % 89) + 1, (i % 97) + 1
        line += b"q 1 0 0 1 %d %d cm Q\n" % (a, b)
        i += 1
    parts.append(bytes(line))
    return b"".join(parts)


def _stream_doc(stream: bytes) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, _FONT_OBJECT)
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def _span(page: fitz.Page, probe: str = TARGET) -> dict:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if probe in text:
                    return span
    raise AssertionError(f"{probe!r} not found")


def _prepare(doc: fitz.Document, page: fitz.Page, *, replacement_text: str = "Price 2025", registry=None):
    reg = registry or DocumentFontRegistry(doc)
    span = _span(page)
    plan = prepare_plan(
        doc, page,
        target_text=TARGET, replacement_text=replacement_text,
        expected_origin=tuple(span["origin"]), target_bbox=None,
        registry=reg,
    )
    assert isinstance(plan, PreparedEdit), getattr(plan, "reason", plan)
    return plan


def _patchset_for(plan: PreparedEdit) -> PatchSet:
    return PatchSet(
        page_xref=plan.page_xref,
        replacements=(plan.replacement,),
        expected_page_fingerprint=plan.page_fingerprint,
    )


def _preview_request(doc: fitz.Document, generation: int, replacement: str) -> PlanPreviewRequest:
    span = _span(doc[0])
    bbox = tuple(float(v) for v in span["bbox"])
    return PlanPreviewRequest(
        session_key="p3c-test",
        generation=generation,
        target_text=TARGET,
        replacement_text=replacement,
        expected_origin=tuple(float(v) for v in span["origin"]),
        target_bbox=bbox,
        clip_rect=bbox,
        render_scale=1.0,
    )


class _UpdateStreamCounter:
    """Counts fitz.Document.update_stream calls, split by resolved compress."""

    def __init__(self) -> None:
        self.compressed = 0
        self.uncompressed = 0
        self._orig = None

    def install(self) -> None:
        self._orig = fitz.Document.update_stream
        counter = self
        orig = self._orig

        def counting(doc_self, xref=0, stream=None, new=1, compress=1):
            if compress:
                counter.compressed += 1
            else:
                counter.uncompressed += 1
            return orig(doc_self, xref, stream, new, compress)

        fitz.Document.update_stream = counting

    def uninstall(self) -> None:
        if self._orig is not None:
            fitz.Document.update_stream = self._orig
            self._orig = None

    def take(self) -> tuple[int, int]:
        c, u = self.compressed, self.uncompressed
        self.compressed = 0
        self.uncompressed = 0
        return c, u


# ---------------------------------------------------------------- Group A
# apply_patchset(compress=...) contract


def test_apply_patchset_compress_false_decodes_identically_to_compress_true():
    doc_a = _stream_doc(_padded_stream())
    doc_b = _stream_doc(_padded_stream())
    plan_a = _prepare(doc_a, doc_a[0])
    plan_b = _prepare(doc_b, doc_b[0])
    apply_patchset(doc_a, doc_a[0], _patchset_for(plan_a), compress=True)
    apply_patchset(doc_b, doc_b[0], _patchset_for(plan_b), compress=False)
    assert doc_a.xref_stream(plan_a.stream_xref) == doc_b.xref_stream(plan_b.stream_xref)
    doc_a.close()
    doc_b.close()


def test_apply_patchset_compress_false_actually_skips_compression():
    doc_a = _stream_doc(_padded_stream())
    doc_b = _stream_doc(_padded_stream())
    plan_a = _prepare(doc_a, doc_a[0])
    plan_b = _prepare(doc_b, doc_b[0])
    apply_patchset(doc_a, doc_a[0], _patchset_for(plan_a), compress=True)
    apply_patchset(doc_b, doc_b[0], _patchset_for(plan_b), compress=False)
    raw_compressed = doc_a.xref_stream_raw(plan_a.stream_xref)
    raw_uncompressed = doc_b.xref_stream_raw(plan_b.stream_xref)
    assert len(raw_compressed) < len(raw_uncompressed)
    doc_a.close()
    doc_b.close()


def test_apply_patchset_default_compress_matches_explicit_true():
    doc_a = _stream_doc(_padded_stream())
    doc_b = _stream_doc(_padded_stream())
    plan_a = _prepare(doc_a, doc_a[0])
    plan_b = _prepare(doc_b, doc_b[0])
    apply_patchset(doc_a, doc_a[0], _patchset_for(plan_a))  # default
    apply_patchset(doc_b, doc_b[0], _patchset_for(plan_b), compress=True)
    assert len(doc_a.xref_stream_raw(plan_a.stream_xref)) == len(
        doc_b.xref_stream_raw(plan_b.stream_xref)
    )
    doc_a.close()
    doc_b.close()


# ---------------------------------------------------------------- Group B
# AppliedPatch.revert(compress=...) contract


def test_revert_compress_false_restores_decoded_bytes_exactly():
    original = _padded_stream()
    doc = _stream_doc(original)
    plan = _prepare(doc, doc[0])
    applied = apply_patchset(doc, doc[0], _patchset_for(plan), compress=False)
    applied.revert(doc, compress=False)
    assert doc.xref_stream(plan.stream_xref) == original
    doc.close()


def test_revert_default_compress_matches_explicit_true():
    original = _padded_stream()
    doc_a = _stream_doc(original)
    doc_b = _stream_doc(original)
    plan_a = _prepare(doc_a, doc_a[0])
    plan_b = _prepare(doc_b, doc_b[0])
    applied_a = apply_patchset(doc_a, doc_a[0], _patchset_for(plan_a))
    applied_b = apply_patchset(doc_b, doc_b[0], _patchset_for(plan_b))
    applied_a.revert(doc_a)  # default
    applied_b.revert(doc_b, compress=True)
    assert len(doc_a.xref_stream_raw(plan_a.stream_xref)) == len(
        doc_b.xref_stream_raw(plan_b.stream_xref)
    )
    doc_a.close()
    doc_b.close()


def test_apply_then_revert_compress_false_leaves_object_graph_unchanged():
    original = _padded_stream()
    doc = _stream_doc(original)
    page = doc[0]
    font_xref = int(page.get_fonts(full=True)[0][0])
    before = {
        "xref_length": doc.xref_length(),
        "page_obj": doc.xref_object(page.xref),
        "font_obj": doc.xref_object(font_xref),
    }
    plan = _prepare(doc, page)
    applied = apply_patchset(doc, page, _patchset_for(plan), compress=False)
    applied.revert(doc, compress=False)
    after = {
        "xref_length": doc.xref_length(),
        "page_obj": doc.xref_object(page.xref),
        "font_obj": doc.xref_object(font_xref),
    }
    assert before == after
    assert doc.xref_stream(plan.stream_xref) == original
    doc.close()


# ---------------------------------------------------------------- Group C
# fingerprint / evidence-key never observe storage encoding


def test_page_fingerprint_identical_regardless_of_stream_compress_state():
    doc_a = _stream_doc(_padded_stream())
    doc_b = _stream_doc(_padded_stream())
    plan_a = _prepare(doc_a, doc_a[0])
    plan_b = _prepare(doc_b, doc_b[0])
    apply_patchset(doc_a, doc_a[0], _patchset_for(plan_a), compress=True)
    apply_patchset(doc_b, doc_b[0], _patchset_for(plan_b), compress=False)
    assert page_fingerprint(doc_a, doc_a[0]) == page_fingerprint(doc_b, doc_b[0])
    doc_a.close()
    doc_b.close()


def test_evidence_key_identical_regardless_of_stream_compress_state():
    doc_a = _stream_doc(_padded_stream())
    doc_b = _stream_doc(_padded_stream())
    plan_a = _prepare(doc_a, doc_a[0])
    plan_b = _prepare(doc_b, doc_b[0])
    apply_patchset(doc_a, doc_a[0], _patchset_for(plan_a), compress=True)
    apply_patchset(doc_b, doc_b[0], _patchset_for(plan_b), compress=False)
    key_a = compute_evidence_key(doc_a[0].xref, tuple(read_page_streams(doc_a, doc_a[0])))
    key_b = compute_evidence_key(doc_b[0].xref, tuple(read_page_streams(doc_b, doc_b[0])))
    assert key_a == key_b
    doc_a.close()
    doc_b.close()


# ---------------------------------------------------------------- Group D
# preview integration + count-based regression gate


def test_render_pipeline_output_identical_between_compress_true_and_false():
    """The compress flag on the scratch-only splice/revert changes nothing a
    caller of PlanPreviewRenderer.render() can observe."""

    def _run(compress: bool) -> tuple[str, bytes]:
        doc = _stream_doc(_padded_stream())
        page = doc[0]
        plan = _prepare(doc, page)
        pre_state = capture_page_state(doc, page, plan)
        applied = apply_patchset(doc, page, _patchset_for(plan), compress=compress)
        try:
            verification = verify_tier0_commit(
                doc, page, plan, pre_state,
                reopen_probe=False, cached_reopen_probe_ok=True,
            )
            assert isinstance(verification, tuple), verification
            clip = fitz.Rect(plan.target_bbox_page) & page.rect
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), clip=clip, annots=True)
            png = pixmap.tobytes("png")
        finally:
            applied.revert(doc, compress=compress)
        doc.close()
        return plan.token, png

    token_true, png_true = _run(True)
    token_false, png_false = _run(False)
    assert token_true == token_false
    assert png_true == png_false


def test_preview_render_makes_zero_compressed_update_stream_calls():
    doc = _stream_doc(_padded_stream())
    session = open_preview_session(doc, 0, "p3c-test")
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    counter = _UpdateStreamCounter()
    counter.install()
    try:
        result = renderer.render(_preview_request(doc, 1, "Price 2025"))
    finally:
        counter.uninstall()
    compressed, uncompressed = counter.take()
    assert result.plan_token is not None, result.reject_reason
    assert compressed == 0
    assert uncompressed == 2  # apply + revert, both on the scratch
    renderer.close()
    doc.close()


def test_engine_commit_still_uses_compressed_update_stream():
    """Regression guard: the live commit path must NOT be affected by this
    slice -- its output is what actually gets saved."""
    doc = _stream_doc(_padded_stream())
    engine = TieredCommitEngine(doc)
    page = doc[0]
    plan = _prepare(doc, page, registry=engine.registry)
    counter = _UpdateStreamCounter()
    counter.install()
    try:
        outcome = engine.commit(plan)
    finally:
        counter.uninstall()
    compressed, uncompressed = counter.take()
    assert outcome.status == CommitStatus.COMMITTED, outcome
    assert compressed >= 1
    assert uncompressed == 0
    doc.close()


# ---------------------------------------------------------------- Group E
# bounded memory: the uncompressed stream is a one-time expansion


def test_repeated_preview_keystrokes_stream_memory_stays_bounded():
    doc = _stream_doc(_padded_stream(n_pad=200_000))
    session = open_preview_session(doc, 0, "p3c-mem")
    assert session is not None
    renderer = PlanPreviewRenderer(session)

    result = renderer.render(_preview_request(doc, 0, "Price 2025"))
    assert result.plan_token is not None, result.reject_reason
    gc.collect()

    tracemalloc.start()
    result = renderer.render(_preview_request(doc, 1, "Price 2126"))
    assert result.plan_token is not None, result.reject_reason
    gc.collect()
    _, peak_early = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tracemalloc.start()
    for i in range(2, 22):
        result = renderer.render(_preview_request(doc, i, f"Price 2{i % 10}25"))
        assert result.plan_token is not None, result.reject_reason
    gc.collect()
    _, peak_late = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # 20 more keystrokes on the same single content stream must not
    # multiply the peak footprint -- the uncompressed representation
    # replaces itself in place every keystroke, never accumulates.
    assert peak_late < peak_early * 3, (peak_early, peak_late)
    renderer.close()
    doc.close()
