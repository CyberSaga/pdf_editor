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

import dataclasses
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import CommitStatus, RejectReason  # noqa: E402
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
from model.text_commit.verify import (  # noqa: E402
    VerificationFailure,
    capture_page_state,
    verify_tier0_commit,
)
from test_scripts.type0_fixture_builder import (  # noqa: E402
    CJK_TEXT,
    REPLACEMENT_EQUAL_ADVANCE,
    REPLACEMENT_LONGER,
    build_identity_h_fixture,
    install_oc_layer,
    set_text_matrix,
    wrap_content_in_marked_content,
)

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
    # Raw BYTES, not just length -- same PyMuPDF build + same input must
    # produce deterministic Flate output; a length-only check would not
    # catch a default that compresses correctly but differently.
    assert doc_a.xref_stream_raw(plan_a.stream_xref) == doc_b.xref_stream_raw(
        plan_b.stream_xref
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
    assert doc_a.xref_stream_raw(plan_a.stream_xref) == doc_b.xref_stream_raw(
        plan_b.stream_xref
    )
    doc_a.close()
    doc_b.close()


def test_apply_then_revert_compress_false_leaves_non_stream_objects_unchanged():
    """Every OTHER object (page tree, fonts, xref count) is untouched by a
    compress=False apply+revert cycle -- only the content stream's own
    storage encoding changes, and (see the next test) it does NOT revert to
    its original encoding, by design."""
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


def test_revert_compress_false_does_not_restore_original_storage_encoding():
    """Documents the true (not the initially-assumed) invariant: revert
    restores DECODED bytes exactly, but a compress=False apply+revert cycle
    leaves the content stream's own object dict permanently uncompressed --
    it is NOT restored to the stream's original (possibly compressed)
    encoding. Safe because nothing in this codebase reads a content
    stream's storage encoding (only ``xref_stream()``/decoded content), but
    a future reader must not assume "revert" means "byte-identical stream
    object," only "byte-identical decoded content."""
    original = _padded_stream()
    doc = _stream_doc(original)  # built with default compress=True
    page = doc[0]
    content_xref = page.get_contents()[0]
    original_obj = doc.xref_object(content_xref)
    assert "/Filter" in original_obj  # the original IS compressed

    plan = _prepare(doc, page)
    applied = apply_patchset(doc, page, _patchset_for(plan), compress=False)
    applied.revert(doc, compress=False)

    reverted_obj = doc.xref_object(content_xref)
    assert "/Filter" not in reverted_obj  # storage encoding NOT restored
    assert reverted_obj != original_obj
    assert doc.xref_stream(content_xref) == original  # decoded content IS
    doc.close()


def test_mismatched_compress_apply_true_revert_false_still_round_trips():
    """apply and revert set ``compress`` independently by design (a caller
    reverting on a different document/path than it applied to is free to
    choose differently) -- decoded content must stay exact even when the
    two calls disagree, since neither reads storage encoding."""
    original = _padded_stream()
    doc = _stream_doc(original)
    plan = _prepare(doc, doc[0])
    applied = apply_patchset(doc, doc[0], _patchset_for(plan), compress=True)
    applied.revert(doc, compress=False)
    assert doc.xref_stream(plan.stream_xref) == original
    doc.close()


def test_mismatched_compress_apply_false_revert_true_still_round_trips():
    original = _padded_stream()
    doc = _stream_doc(original)
    plan = _prepare(doc, doc[0])
    applied = apply_patchset(doc, doc[0], _patchset_for(plan), compress=False)
    applied.revert(doc, compress=True)
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


def test_render_primitives_output_identical_between_compress_true_and_false():
    """Sanity check on the raw primitive sequence (not PlanPreviewRenderer
    itself -- see the next test for that): token + PNG bytes are identical
    whichever compress value the apply/revert pair uses."""

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


def test_preview_renderer_output_identical_between_compress_true_and_false():
    """The compress flag changes nothing a caller of the REAL
    ``PlanPreviewRenderer.render()`` can observe -- proven by monkeypatching
    both scratch-only call sites to force compress=True for a control run,
    never by hand-replicating the pipeline (which could silently drift from
    what render() actually does)."""
    import model.text_commit.patch as patch_module
    import model.text_commit.preview as preview_module

    def _run(force_compress_true: bool) -> tuple[str | None, bytes]:
        doc = _stream_doc(_padded_stream())
        session = open_preview_session(doc, 0, "p3c-parity")
        assert session is not None
        renderer = PlanPreviewRenderer(session)
        orig_apply = preview_module.apply_patchset
        orig_revert = patch_module.AppliedPatch.revert
        if force_compress_true:

            def forced_apply(scratch, page, patchset, *, compress=False):
                return orig_apply(scratch, page, patchset, compress=True)

            def forced_revert(self, doc_, *, compress=False):
                return orig_revert(self, doc_, compress=True)

            preview_module.apply_patchset = forced_apply
            patch_module.AppliedPatch.revert = forced_revert
        try:
            result = renderer.render(_preview_request(doc, 1, "Price 2025"))
        finally:
            preview_module.apply_patchset = orig_apply
            patch_module.AppliedPatch.revert = orig_revert
        renderer.close()
        doc.close()
        return result.plan_token, result.png_bytes

    token_shipped, png_shipped = _run(False)
    token_forced_true, png_forced_true = _run(True)
    assert token_shipped is not None
    assert token_shipped == token_forced_true
    assert png_shipped == png_forced_true


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


def test_repeated_preview_keystrokes_stream_storage_stays_single_representation():
    """The scratch's uncompressed content-stream storage is a ONE-TIME
    expansion, replaced in place every keystroke, never an accumulation.

    ``tracemalloc`` cannot prove this: the uncompressed bytes live in
    MuPDF's C heap (an ``fz_buffer`` inside the scratch ``fitz.Document``),
    not the Python allocator, so a Python-heap-only instrument would stay
    flat even if the C-side representation grew without bound every
    keystroke. This asserts directly on the stored representation
    PyMuPDF reports (``xref_stream_raw``) instead: every keystroke reverts
    the same content stream back to its untouched original bytes, so the
    raw (uncompressed) length after revert must be IDENTICAL every single
    time -- any growth at all is exactly the accumulation regression this
    test exists to catch.
    """
    doc = _stream_doc(_padded_stream(n_pad=200_000))
    session = open_preview_session(doc, 0, "p3c-mem")
    assert session is not None
    renderer = PlanPreviewRenderer(session)

    result = renderer.render(_preview_request(doc, 0, "Price 2025"))
    assert result.plan_token is not None, result.reject_reason
    scratch = renderer._scratch
    content_xref = scratch[0].get_contents()[0]

    raw_lens = [len(scratch.xref_stream_raw(content_xref))]
    for i in range(1, 21):
        result = renderer.render(_preview_request(doc, i, f"Price 2{i % 10}25"))
        assert result.plan_token is not None, result.reject_reason
        raw_lens.append(len(scratch.xref_stream_raw(content_xref)))

    assert len(set(raw_lens)) == 1, raw_lens
    renderer.close()
    doc.close()


# ---------------------------------------------------------------- Group F
# tier / font-class coverage: the compress flag is observationally invisible
# through the REAL PlanPreviewRenderer.render() for every admitted candidate
# class, not just the Tier 0 simple-font case Groups A-E use.  Guard-pins
# (green by design): each drives render() twice -- shipped (compress=False)
# vs a forced compress=True control -- and any behavioral difference the
# flag ever grows breaks the byte-equality below.

_T1_TARGET = "iii"
_T1_GROWTH = "MMM"  # helv M=833/1000 vs i=222/1000: ~22pt ink growth at 12pt
_T1_TAIL = " " * 12 + "tail"


def _tier1_composite_doc() -> fitz.Document:
    """The Tier 1 Slice 1 composite fixture (same-line kern oracle), copied
    from ``test_text_commit_tier1_slice1._composite_doc`` per the house
    copy-not-import pattern for simple-font builders."""
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + _T1_TARGET.encode() + b") Tj "
        b"/F1 9 Tf (" + _T1_TAIL.encode() + b") Tj "
        b"0 -20 Td /F1 12 Tf (world) Tj ET"
    )
    return _stream_doc(stream)


def _cid_doc() -> fitz.Document:
    return build_identity_h_fixture().doc


def _cid_oc_doc() -> fitz.Document:
    """Default-visible pure /OC layer around the CID show -- the admitted
    marked-content class (``test_text_commit_mc_admission``'s idiom)."""
    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="Lyr7Q", label="L7Q", on=True)
    wrap_content_in_marked_content(fixture, "/OC /Lyr7Q BDC")
    return fixture.doc


def _cid_rot90_doc() -> fitz.Document:
    fixture = build_identity_h_fixture()
    set_text_matrix(fixture, (0.0, 1.0, -1.0, 0.0))  # quarter-turn Tm
    return fixture.doc


def _render_class_case(
    doc: fitz.Document,
    *,
    target: str,
    replacement: str,
    max_tier: int,
    force_compress_true: bool,
    counter: _UpdateStreamCounter | None = None,
):
    """One real render() pass over an arbitrary fixture class."""
    import model.text_commit.patch as patch_module
    import model.text_commit.preview as preview_module

    session = open_preview_session(doc, 0, "p3c-class-matrix", max_tier=max_tier)
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    span = _span(doc[0], target)
    request = PlanPreviewRequest(
        session_key="p3c-class-matrix",
        generation=1,
        target_text=target,
        replacement_text=replacement,
        expected_origin=tuple(float(v) for v in span["origin"]),
        target_bbox=tuple(float(v) for v in span["bbox"]),
        clip_rect=tuple(doc[0].rect),
        render_scale=1.0,
    )
    orig_apply = preview_module.apply_patchset
    orig_revert = patch_module.AppliedPatch.revert
    if force_compress_true:

        def forced_apply(scratch, page, patchset, *, compress=False):
            return orig_apply(scratch, page, patchset, compress=True)

        def forced_revert(self, doc_, *, compress=False):
            return orig_revert(self, doc_, compress=True)

        preview_module.apply_patchset = forced_apply
        patch_module.AppliedPatch.revert = forced_revert
    if counter is not None:
        counter.install()
    try:
        result = renderer.render(request)
    finally:
        if counter is not None:
            counter.uninstall()
        preview_module.apply_patchset = orig_apply
        patch_module.AppliedPatch.revert = orig_revert
    renderer.close()
    return result


def _assert_class_case_identical_and_uncompressed(
    doc_factory, *, target: str, replacement: str, max_tier: int, expect_tier: int
):
    counter = _UpdateStreamCounter()
    doc = doc_factory()
    shipped = _render_class_case(
        doc,
        target=target,
        replacement=replacement,
        max_tier=max_tier,
        force_compress_true=False,
        counter=counter,
    )
    doc.close()
    compressed, uncompressed = counter.take()
    assert shipped.plan_token is not None, shipped.reject_reason
    assert (compressed, uncompressed) == (0, 2), (compressed, uncompressed)
    assert shipped.prepared is not None
    assert shipped.prepared.tier.value == expect_tier, shipped.prepared.tier

    doc = doc_factory()
    control = _render_class_case(
        doc,
        target=target,
        replacement=replacement,
        max_tier=max_tier,
        force_compress_true=True,
    )
    doc.close()
    assert control.reject_reason is None, control.reject_reason
    assert control.plan_token == shipped.plan_token
    assert control.png_bytes == shipped.png_bytes
    return shipped


def test_preview_render_tier1_kern_growth_identical_and_uncompressed():
    """Tier 1 kern-compensated transplant WITH ink growth: the compress flag
    must be invisible through verify_tier1_commit + the growth-zone gates,
    and the growth evidence must be present on the shipped candidate."""
    shipped = _assert_class_case_identical_and_uncompressed(
        _tier1_composite_doc,
        target=_T1_TARGET,
        replacement=_T1_GROWTH,
        max_tier=1,
        expect_tier=1,
    )
    assert shipped.prepared.has_ink_growth is True
    assert shipped.prepared.growth_direction


def test_preview_render_type0_cid_tier0_identical_and_uncompressed():
    _assert_class_case_identical_and_uncompressed(
        _cid_doc,
        target=CJK_TEXT,
        replacement=REPLACEMENT_EQUAL_ADVANCE,
        max_tier=0,
        expect_tier=0,
    )


def test_preview_render_type0_cid_tier1_identical_and_uncompressed():
    _assert_class_case_identical_and_uncompressed(
        _cid_doc,
        target=CJK_TEXT,
        replacement=REPLACEMENT_LONGER,
        max_tier=1,
        expect_tier=1,
    )


def test_preview_render_visible_oc_wrapper_identical_and_uncompressed():
    _assert_class_case_identical_and_uncompressed(
        _cid_oc_doc,
        target=CJK_TEXT,
        replacement=REPLACEMENT_EQUAL_ADVANCE,
        max_tier=0,
        expect_tier=0,
    )


def test_preview_render_rotated_quarter_turn_identical_and_uncompressed():
    _assert_class_case_identical_and_uncompressed(
        _cid_rot90_doc,
        target=CJK_TEXT,
        replacement=REPLACEMENT_EQUAL_ADVANCE,
        max_tier=0,
        expect_tier=0,
    )


# ---------------------------------------------------------------- Group G
# verification failures REMAIN failures under compress=False, and revert
# still restores the decoded bytes afterward.  These are the first tests in
# the suite to FORCE the V0a-V0d gates (every pre-existing test pins them
# positively); guard-pins for the compress slice, forced-failure firsts for
# the verifier.


def _apply_uncompressed_for_failure(doc: fitz.Document):
    page = doc[0]
    plan = _prepare(doc, page)
    pre_state = capture_page_state(doc, page, plan)
    applied = apply_patchset(doc, page, _patchset_for(plan), compress=False)
    return page, plan, pre_state, applied


def _assert_verify_fails(doc, page, plan, pre_state, detail_substring: str):
    failure = verify_tier0_commit(
        doc, page, plan, pre_state, reopen_probe=False, cached_reopen_probe_ok=True
    )
    assert isinstance(failure, VerificationFailure), failure
    assert failure.reason == RejectReason.VERIFICATION_FAILED
    assert detail_substring in failure.detail, failure.detail
    return failure


def _assert_reverts_exactly(doc, plan, pre_state, applied) -> None:
    xref = plan.replacement.stream_xref
    applied.revert(doc, compress=False)
    assert doc.xref_stream(xref) == dict(pre_state.streams)[xref]


def test_outside_range_stream_mutation_still_fails_verify_under_compress_false():
    """V0a: bytes outside the declared splice range changed after apply."""
    doc = _stream_doc(_padded_stream())
    page, plan, pre_state, applied = _apply_uncompressed_for_failure(doc)
    xref = plan.replacement.stream_xref
    doc.update_stream(xref, doc.xref_stream(xref) + b" ")
    _assert_verify_fails(
        doc, page, plan, pre_state, "target stream changed outside the declared range"
    )
    # revert restores the pre-apply decoded bytes, overwriting the
    # injected mutation along with the splice.
    _assert_reverts_exactly(doc, plan, pre_state, applied)
    doc.close()


def test_nontarget_origin_movement_still_fails_verify_under_compress_false():
    """V0c: a non-target span origin that differs from the pre-state."""
    doc = _stream_doc(_padded_stream())
    page, plan, pre_state, applied = _apply_uncompressed_for_failure(doc)
    tampered = dataclasses.replace(pre_state, nontarget_origins=((0.0, 0.0),))
    _assert_verify_fails(doc, page, plan, tampered, "non-target span geometry changed")
    _assert_reverts_exactly(doc, plan, pre_state, applied)
    doc.close()


def test_outside_halo_pixel_change_still_fails_verify_under_compress_false():
    """V0d: one flipped pixel byte far outside the target halo (the page's
    bottom-right corner; the target sits near the top-left)."""
    doc = _stream_doc(_padded_stream())
    page, plan, pre_state, applied = _apply_uncompressed_for_failure(doc)
    samples = pre_state.pixmap_samples
    flipped = samples[:-1] + bytes([samples[-1] ^ 0xFF])
    tampered = dataclasses.replace(pre_state, pixmap_samples=flipped)
    _assert_verify_fails(
        doc, page, plan, tampered, "pixels changed outside the target halo"
    )
    _assert_reverts_exactly(doc, plan, pre_state, applied)
    doc.close()


def test_font_resource_mutation_still_fails_verify_under_compress_false():
    """V0b (fonts): a font resource added between apply and verify."""
    doc = _stream_doc(_padded_stream())
    page, plan, pre_state, applied = _apply_uncompressed_for_failure(doc)
    extra_font = doc.get_new_xref()
    doc.update_object(extra_font, _FONT_OBJECT)
    doc.xref_set_key(page.xref, "Resources/Font/F9", f"{extra_font} 0 R")
    _assert_verify_fails(doc, page, plan, pre_state, "font resource table changed")
    _assert_reverts_exactly(doc, plan, pre_state, applied)
    doc.close()


def test_annotation_mutation_still_fails_verify_under_compress_false():
    """V0b (annots): an annotation added between apply and verify."""
    doc = _stream_doc(_padded_stream())
    page, plan, pre_state, applied = _apply_uncompressed_for_failure(doc)
    page.add_highlight_annot(fitz.Rect(300.0, 300.0, 340.0, 320.0))
    _assert_verify_fails(doc, page, plan, pre_state, "annotations changed")
    _assert_reverts_exactly(doc, plan, pre_state, applied)
    doc.close()


def test_unextractable_replacement_still_fails_verify_under_compress_false():
    """V0c (extraction): verify against a plan whose replacement_text was
    never spliced.  (The sibling 'source text still present' branch is not
    forcible on this fixture: the halo clip contains only the replacement,
    and every substring of it is a substring of replacement_text, which
    short-circuits the gate's first condition.)"""
    doc = _stream_doc(_padded_stream())
    page, plan, pre_state, applied = _apply_uncompressed_for_failure(doc)
    tampered_plan = dataclasses.replace(plan, replacement_text="Absent Zebra")
    _assert_verify_fails(
        doc, page, tampered_plan, pre_state, "replacement text not extractable"
    )
    _assert_reverts_exactly(doc, plan, pre_state, applied)
    doc.close()


def test_preview_verify_failure_reverts_scratch_and_rejects_under_compress_false():
    """A VerificationFailure returned inside the REAL render() still yields
    a rejection result AND a decoded-byte-exact scratch revert, with the
    same 0-compressed / 2-uncompressed call shape as an accepted render."""
    import model.text_commit.preview as preview_module

    doc = _stream_doc(_padded_stream())
    live_xref = doc[0].get_contents()[0]
    live_bytes = doc.xref_stream(live_xref)
    session = open_preview_session(doc, 0, "p3c-inject")
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    orig_verify = preview_module.verify_tier0_commit
    counter = _UpdateStreamCounter()

    def failing_verify(*args, **kwargs):
        return VerificationFailure(RejectReason.VERIFICATION_FAILED, "injected by test")

    preview_module.verify_tier0_commit = failing_verify
    counter.install()
    try:
        result = renderer.render(_preview_request(doc, 1, "Price 2025"))
    finally:
        counter.uninstall()
        preview_module.verify_tier0_commit = orig_verify
    compressed, uncompressed = counter.take()
    assert result.plan_token is None
    assert result.reject_reason == RejectReason.VERIFICATION_FAILED
    assert result.png_bytes == b""
    assert (compressed, uncompressed) == (0, 2)  # apply + revert both ran
    scratch = renderer._scratch
    assert scratch.xref_stream(live_xref) == live_bytes
    renderer.close()
    doc.close()


def test_preview_verifier_exception_still_reverts_scratch_under_compress_false():
    """A verifier that RAISES inside render() propagates, but the finally
    clause still reverts the scratch to decoded-byte identity."""
    import model.text_commit.preview as preview_module

    doc = _stream_doc(_padded_stream())
    live_xref = doc[0].get_contents()[0]
    live_bytes = doc.xref_stream(live_xref)
    session = open_preview_session(doc, 0, "p3c-crash")
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    orig_verify = preview_module.verify_tier0_commit
    counter = _UpdateStreamCounter()

    def raising_verify(*args, **kwargs):
        raise RuntimeError("injected verifier crash")

    preview_module.verify_tier0_commit = raising_verify
    counter.install()
    try:
        with pytest.raises(RuntimeError, match="injected verifier crash"):
            renderer.render(_preview_request(doc, 1, "Price 2025"))
    finally:
        counter.uninstall()
        preview_module.verify_tier0_commit = orig_verify
    compressed, uncompressed = counter.take()
    assert (compressed, uncompressed) == (0, 2)  # apply + revert both ran
    scratch = renderer._scratch
    assert scratch.xref_stream(live_xref) == live_bytes
    renderer.close()
    doc.close()
