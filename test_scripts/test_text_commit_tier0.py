"""Red-light tests for the Tier 0 lossless stream patch (plan Task 6).

Only the deliberately narrow case — one unambiguous run bound to one
complete literal-string Tj, simple Latin encoding, equal advance — selects
Tier 0.  Preparation runs scratch-first (live document untouched), commit
applies exactly one validated PatchSet, and verification proves stream,
resource, geometry, and raster identity outside the target halo.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_requests import StyleOverrides  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    FontResourceAction,
    RejectReason,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    prepare_tier0_plan,
)
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import page_fingerprint, replay_page  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # helv digits share widths: advance-neutral
DOWNSTREAM = "Downstream line stays"

# The same target written as a hex-string operand, delimiters included.
HEX_TARGET_TOKEN = b"<" + TARGET.encode("ascii").hex().encode("ascii") + b">"
# helv: '(' and 'r' are both 333/1000, so this stays advance-neutral while
# forcing the literal writer to escape a delimiter.
HEX_REPLACEMENT = "P(ice 2025"
HEX_REPLACEMENT_TOKEN = b"(P\\(ice 2025)"


def _tier0_doc() -> fitz.Document:
    """Page whose only content is a raw literal-Tj stream (plus a neighbor)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"0 -40 Td (" + DOWNSTREAM.encode() + b") Tj ET"
    )
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
    return doc


def _hex_tier0_doc() -> fitz.Document:
    """:func:`_tier0_doc`'s page with the target as a HEX-string ``Tj``.

    Written by hand because nothing in this suite generates one: PyMuPDF's
    ``insert_text`` emits ``[<...>]TJ`` (an *array*), so the shape that
    dominates real corpora — a bare hex ``Tj`` — had no fixture at all.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 12 Tf 72 700 Td " + HEX_TARGET_TOKEN + b" Tj "
        b"0 -40 Td (" + DOWNSTREAM.encode() + b") Tj ET"
    )
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
    return doc


def _span(page: fitz.Page, probe: str) -> dict:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if probe in text:
                    return span
    raise AssertionError(f"span {probe!r} not found")


def _prepare(doc: fitz.Document, engine: TieredCommitEngine, **overrides):
    page = doc[0]
    span = _span(page, TARGET)
    kwargs = {
        "target_text": TARGET,
        "replacement_text": REPLACEMENT,
        "expected_origin": tuple(span["origin"]),
        "target_bbox": tuple(span["bbox"]),
    }
    kwargs.update(overrides)
    return engine.prepare(page, **kwargs)


# ---------------------------------------------------------------- planning


def test_planner_selects_tier0_for_narrow_case():
    doc = _tier0_doc()
    prepared = _prepare(doc, TieredCommitEngine(doc))
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.replacement.replacement_bytes == b"(" + REPLACEMENT.encode() + b")"
    assert prepared.replacement.expected_bytes == b"(" + TARGET.encode() + b")"
    assert prepared.token
    doc.close()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"replacement_text": TARGET}, RejectReason.NO_CHANGE),
        ({"replacement_text": ""}, RejectReason.EMPTY_REPLACEMENT),
        ({"replacement_text": "a\nb"}, RejectReason.MULTILINE_REPLACEMENT),
        (
            {"style_overrides": StyleOverrides(font_family="cour")},
            RejectReason.STYLE_OVERRIDE_PRESENT,
        ),
        (
            {"new_rect": fitz.Rect(10, 10, 100, 40)},
            RejectReason.GEOMETRY_OVERRIDE_PRESENT,
        ),
        (
            {"replacement_text": "Price 20245"},
            RejectReason.ADVANCE_MISMATCH,
        ),
        (
            {"replacement_text": "Price 2W24"},  # helv W is wider than a digit
            RejectReason.ADVANCE_MISMATCH,
        ),
        (
            {"replacement_text": "Précé 2025"},
            RejectReason.ENCODING_FAILED,
        ),
    ],
)
def test_planner_rejects_each_gate_with_stable_reason(overrides, reason):
    doc = _tier0_doc()
    rejection = _prepare(doc, TieredCommitEngine(doc), **overrides)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == reason
    doc.close()


def test_planner_rejects_tj_array_pages():
    """``insert_text`` writes ``[<...>]TJ`` — an ARRAY, not a hex ``Tj``.

    This case was named ``..._hex_tj_...`` until 2026-08-01 and was read as
    covering hex strings; it never did.  The operator is ``TJ``, so it
    failed on the operator half of the gate and the string-kind half stayed
    uncovered (see :func:`_hex_tier0_doc`).  TJ arrays remain out of scope
    in v1 — admitting one means compensating its kerns — so the rejection
    itself is unchanged; only the claim it makes is now honest.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=12.0, fontname="helv")
    show = replay_page(doc, page).shows[0]
    assert show.operator == "TJ"
    assert show.string_kind == "array"

    engine = TieredCommitEngine(doc)
    span = _span(page, "Hello World")
    rejection = engine.prepare(
        page,
        target_text="Hello World",
        replacement_text="Hallo World",  # a/e advance-neutral in helv
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(rejection, PlanRejection)
    assert rejection.reason == RejectReason.NOT_SINGLE_LITERAL_TJ
    assert "TJ" in rejection.detail
    doc.close()


def test_planner_accepts_hex_tj_and_writes_an_escaped_literal():
    """A hex operand is replaced by a freshly encoded LITERAL string.

    The patch writer already replaces the whole operand byte range, so the
    hex relaxation needs no new writer — but that property is exactly what
    the relaxation rests on, so it is pinned here: ``expected_bytes`` must
    span the ``<``/``>`` delimiters, or the splice would leave them behind.
    """
    doc = _hex_tier0_doc()
    page = doc[0]
    show = replay_page(doc, page).shows[0]
    assert show.operator == "Tj"
    assert show.string_kind == "hex"

    span = _span(page, TARGET)
    prepared = TieredCommitEngine(doc).prepare(
        page,
        target_text=TARGET,
        replacement_text=HEX_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.replacement.expected_bytes == HEX_TARGET_TOKEN
    assert prepared.replacement.expected_bytes[:1] == b"<"
    assert prepared.replacement.expected_bytes[-1:] == b">"
    assert prepared.replacement.replacement_bytes == HEX_REPLACEMENT_TOKEN
    doc.close()


def test_commit_replaces_a_hex_operand_with_a_literal_string():
    """End to end: the committed stream carries the escaped literal."""
    doc = _hex_tier0_doc()
    engine = TieredCommitEngine(doc)
    page = doc[0]
    stream_xref = page.get_contents()[0]
    stream_before = doc.xref_stream(stream_xref)
    downstream_before = _span(page, DOWNSTREAM)["origin"]

    span = _span(page, TARGET)
    prepared = engine.prepare(
        page,
        target_text=TARGET,
        replacement_text=HEX_REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )
    assert isinstance(prepared, PreparedEdit), prepared
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH

    stream_after = doc.xref_stream(stream_xref)
    assert HEX_TARGET_TOKEN not in stream_after
    assert HEX_REPLACEMENT_TOKEN in stream_after
    start = prepared.replacement.start
    end = prepared.replacement.end
    assert stream_after[:start] == stream_before[:start]
    assert stream_after[start + len(HEX_REPLACEMENT_TOKEN):] == stream_before[end:]

    page = doc[0]
    text = page.get_text()
    assert HEX_REPLACEMENT in text
    assert TARGET not in text
    downstream_after = _span(page, DOWNSTREAM)["origin"]
    assert downstream_after[0] == pytest.approx(downstream_before[0], abs=0.1)
    assert downstream_after[1] == pytest.approx(downstream_before[1], abs=0.1)
    doc.close()


def test_planner_rejects_pending_maintenance():
    doc = _tier0_doc()
    rejection = _prepare(
        doc, TieredCommitEngine(doc), page_has_pending_maintenance=True
    )
    assert isinstance(rejection, PlanRejection)
    assert rejection.reason == RejectReason.PENDING_MAINTENANCE
    doc.close()


def test_planner_rejects_widget_pages():
    doc = _tier0_doc()
    page = doc[0]
    widget = fitz.Widget()
    widget.field_name = "field1"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(300, 300, 420, 322)
    page.add_widget(widget)
    rejection = _prepare(doc, TieredCommitEngine(doc))
    assert isinstance(rejection, PlanRejection)
    assert rejection.reason == RejectReason.SIGNED_OR_WIDGET_TARGET
    doc.close()


def test_prepare_never_mutates_the_live_document():
    # tobytes() equality cannot prove this (the trailer /ID changes on every
    # serialization — see PITFALLS: generation is not byte-deterministic), so
    # compare the page fingerprint (streams + fonts + annots) and xref count.
    doc = _tier0_doc()
    engine = TieredCommitEngine(doc)
    fingerprint_before = page_fingerprint(doc, doc[0])
    xrefs_before = doc.xref_length()

    prepared = _prepare(doc, engine)
    assert isinstance(prepared, PreparedEdit)
    assert page_fingerprint(doc, doc[0]) == fingerprint_before
    assert doc.xref_length() == xrefs_before  # scratch-first: no new objects

    rejection = _prepare(doc, engine, replacement_text="Price 20245")
    assert isinstance(rejection, PlanRejection)
    assert page_fingerprint(doc, doc[0]) == fingerprint_before
    assert doc.xref_length() == xrefs_before
    doc.close()


def test_prepare_tier0_plan_requires_registry_for_direct_use():
    doc = _tier0_doc()
    page = doc[0]
    span = _span(page, TARGET)
    prepared = prepare_tier0_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
        registry=DocumentFontRegistry(doc),
    )
    assert isinstance(prepared, PreparedEdit)
    doc.close()


# ---------------------------------------------------------------- commit


def test_commit_applies_one_patchset_and_preserves_everything_else():
    doc = _tier0_doc()
    page = doc[0]
    annot = page.add_highlight_annot(fitz.Rect(72, 200, 200, 215))
    annot_xref, annot_rect = annot.xref, tuple(annot.rect)

    engine = TieredCommitEngine(doc)
    fonts_before = page.get_fonts(full=True)
    stream_xref = page.get_contents()[0]
    stream_before = doc.xref_stream(stream_xref)
    downstream_before = _span(page, DOWNSTREAM)["origin"]

    prepared = _prepare(doc, engine)
    assert isinstance(prepared, PreparedEdit)
    outcome = engine.commit(prepared)

    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    assert outcome.allows_external_reflow is False
    assert len(outcome.font_outcomes) == 1
    assert outcome.font_outcomes[0].action == FontResourceAction.SOURCE_RESOURCE_REUSED
    assert outcome.verified_properties

    page = doc[0]
    text = page.get_text()
    assert REPLACEMENT in text
    assert TARGET not in text
    assert DOWNSTREAM in text

    # stream identity outside the declared range
    stream_after = doc.xref_stream(stream_xref)
    start = prepared.replacement.start
    end = prepared.replacement.end
    assert stream_after[:start] == stream_before[:start]
    assert stream_after[start + len(prepared.replacement.replacement_bytes):] == (
        stream_before[end:]
    )

    # font resources, downstream geometry, annotations
    assert page.get_fonts(full=True) == fonts_before
    downstream_after = _span(page, DOWNSTREAM)["origin"]
    assert downstream_after[0] == pytest.approx(downstream_before[0], abs=0.1)
    assert downstream_after[1] == pytest.approx(downstream_before[1], abs=0.1)
    annots_after = [(a.xref, tuple(a.rect)) for a in page.annots()]
    assert annots_after == [(annot_xref, annot_rect)]
    doc.close()


def test_commit_raster_identical_outside_target_halo():
    doc = _tier0_doc()
    engine = TieredCommitEngine(doc)
    page = doc[0]
    span = _span(page, TARGET)
    pre = page.get_pixmap(dpi=96)

    prepared = _prepare(doc, engine)
    assert isinstance(prepared, PreparedEdit)
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED

    post = doc[0].get_pixmap(dpi=96)
    assert pre.samples != post.samples  # the edit itself must be visible

    scale = 96.0 / 72.0
    x0, y0, x1, y1 = span["bbox"]
    halo = (
        int((x0 - 2) * scale),
        int((y0 - 2) * scale),
        int((x1 + 2) * scale) + 1,
        int((y1 + 2) * scale) + 1,
    )
    stride = pre.stride
    n = pre.n
    for y in range(pre.height):
        row_pre = pre.samples[y * stride : (y + 1) * stride]
        row_post = post.samples[y * stride : (y + 1) * stride]
        if row_pre == row_post:
            continue
        assert halo[1] <= y <= halo[3], f"row {y} differs outside halo"
        for x in range(pre.width):
            if row_pre[x * n : (x + 1) * n] != row_post[x * n : (x + 1) * n]:
                assert halo[0] <= x <= halo[2], f"pixel {x},{y} outside halo"
    doc.close()


def test_stale_plan_returns_stale_without_mutation():
    doc = _tier0_doc()
    engine = TieredCommitEngine(doc)
    prepared = _prepare(doc, engine)
    assert isinstance(prepared, PreparedEdit)

    doc[0].insert_text((400, 400), "Concurrent change", fontsize=9.0, fontname="helv")
    fingerprint_before = page_fingerprint(doc, doc[0])
    xrefs_before = doc.xref_length()
    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.STALE_PLAN
    assert page_fingerprint(doc, doc[0]) == fingerprint_before
    assert doc.xref_length() == xrefs_before
    doc.close()


def test_failed_verification_reverts_the_live_document(monkeypatch):
    import model.text_commit.engine as engine_module
    from model.text_commit.verify import VerificationFailure

    doc = _tier0_doc()
    engine = TieredCommitEngine(doc)
    prepared = _prepare(doc, engine)
    assert isinstance(prepared, PreparedEdit)

    stream_xref = doc[0].get_contents()[0]
    stream_before = doc.xref_stream(stream_xref)

    real_verify = engine_module.verify_tier0_commit
    calls = {"n": 0}

    def _fail_on_live(*args, **kwargs):
        calls["n"] += 1
        return VerificationFailure(
            reason=RejectReason.VERIFICATION_FAILED, detail="injected"
        )

    monkeypatch.setattr(engine_module, "verify_tier0_commit", _fail_on_live)
    outcome = engine.commit(prepared)
    monkeypatch.setattr(engine_module, "verify_tier0_commit", real_verify)

    assert calls["n"] >= 1
    assert outcome.status is CommitStatus.FAILED
    assert doc.xref_stream(stream_xref) == stream_before  # reverted
    assert TARGET in doc[0].get_text()
    doc.close()
