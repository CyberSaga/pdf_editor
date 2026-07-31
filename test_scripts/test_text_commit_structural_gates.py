"""Structural-gate rejection tests for the Tier 0 planner (plan Task 6).

``test_text_commit_tier0.py`` varies only the *request* (replacement text,
style/geometry overrides), so every gate that depends on the *shape of the
content stream* was unreachable from it: a mutation audit deleted the
``mc_depth`` and ``render_mode``/``rise``/``hscale`` gates and the whole
suite stayed green.  This module closes that hole by varying the document
instead — one purpose-built raw content stream per gate.

Two rules make these tests mutation-proof rather than merely green:

* ``RejectReason.UNSUPPORTED_TEXT_STATE`` has four emission sites and
  ``FONT_FACE_UNAVAILABLE`` has two, so pinning the reason alone would let
  a test survive deletion of its own gate by tripping a neighbour.  Every
  test also pins a short, stable substring of ``PlanRejection.detail``.
* Every fixture must reach its gate, not trip an earlier one.  Each test
  asserts the replayed ``ShowOp`` really carries the intended off-nominal
  field *and nothing else* (:func:`_assert_only_off_nominal`), and replays
  a positive control — the same stream with the off-nominal construct
  removed — proving the fixture is otherwise a clean Tier 0 candidate.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import page_fingerprint, replay_page  # noqa: E402
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    prepare_tier0_plan,
)
from model.text_commit.replay import ShowOp  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # helv digits share widths: advance-neutral
LEAD_IN = "Lead-in"  # distinct bytes: never collides with TARGET when matching

# The nominal (Tier-0-eligible) value of every ShowOp field the planner or
# the binder gates on, in the order they are checked.
_NOMINAL: dict[str, object] = {
    "origin_reliable": True,  # inspect.py G6 -> UNTRACKED_ADVANCE
    "in_bt": True,  # inspect.py G5 -> UNSUPPORTED_TEXT_STATE
    "trm_translation_only": True,  # inspect.py G7 -> UNSUPPORTED_TEXT_STATE
    "operator": "Tj",  # plan.py    -> NOT_SINGLE_LITERAL_TJ
    "string_kind": "literal",  # plan.py    -> NOT_SINGLE_LITERAL_TJ
    "render_mode": 0,  # plan.py G2 -> UNSUPPORTED_TEXT_STATE
    "rise": 0.0,  # plan.py G3 -> UNSUPPORTED_TEXT_STATE
    "hscale": 100.0,  # plan.py G4 -> UNSUPPORTED_TEXT_STATE
    "mc_depth": 0,  # plan.py G1 -> UNSUPPORTED_TEXT_STATE
}


def _stream_doc(stream: bytes) -> fitz.Document:
    """One page whose only content is ``stream``, with /F1 = Helvetica.

    Same xref surgery as ``test_text_commit_tier0._tier0_doc``; only the
    content-stream bytes vary, so the font resource and page shape stay a
    known-good Tier 0 baseline in every fixture.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
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


def _plan(doc: fitz.Document) -> PreparedEdit | PlanRejection:
    """Run the planner and assert it left the live document untouched.

    ``expected_origin``/``target_bbox`` are deliberately ``None``: the
    off-nominal fixtures need not be renderable by MuPDF's own extractor
    (no font selected, text outside BT/ET), and binding is byte-level, so
    passing rawdict geometry would couple these tests to rendering rather
    than to the gate under test.
    """
    page = doc[0]
    fingerprint_before = page_fingerprint(doc, page)
    xrefs_before = doc.xref_length()
    result = prepare_tier0_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=REPLACEMENT,
        expected_origin=None,
        target_bbox=None,
        registry=DocumentFontRegistry(doc),
    )
    assert page_fingerprint(doc, page) == fingerprint_before  # read-only
    assert doc.xref_length() == xrefs_before
    return result


def _target_show(doc: fitz.Document) -> ShowOp:
    """The replayed show op the binder will select for ``TARGET``.

    Guards against the three false greens that would make a gate test pass
    for the wrong reason: a stream the replay flags malformed
    (MALFORMED_STREAM), a target that never shows up (NO_MATCH), and a
    duplicated target (AMBIGUOUS_MATCH) — all of which are checked before
    any structural gate.
    """
    replay = replay_page(doc, doc[0])
    assert not replay.malformed, "fixture stream must replay cleanly"
    matches = [s for s in replay.shows if s.decoded_bytes == TARGET.encode("latin-1")]
    assert len(matches) == 1, f"expected 1 {TARGET!r} show op, got {len(matches)}"
    return matches[0]


def _assert_only_off_nominal(show: ShowOp, *off_nominal: str) -> None:
    """Exactly ``off_nominal`` differ from Tier 0's nominal text state.

    The anti-false-green guard: it proves the fixture trips the gate under
    test and no other, so the test cannot stay green through deletion of
    its own gate by falling into a neighbouring gate that shares the same
    :class:`RejectReason`.
    """
    for name, nominal in _NOMINAL.items():
        actual = getattr(show, name)
        if name in off_nominal:
            assert actual != nominal, f"{name} was meant to be off-nominal"
        else:
            assert actual == nominal, f"{name} drifted to {actual!r}, breaks isolation"


def _assert_control_plans_cleanly(stream: bytes) -> None:
    """The fixture minus its off-nominal construct is a Tier 0 candidate."""
    doc = _stream_doc(stream)
    show = _target_show(doc)
    _assert_only_off_nominal(show)
    prepared = _plan(doc)
    assert isinstance(prepared, PreparedEdit), f"control fixture rejected: {prepared}"
    doc.close()


# ------------------------------------------------- plan.py structural gates


def test_planner_rejects_marked_content_target():
    """G1: a Tj inside BDC/EMC (tagged PDF) is not patchable in place."""
    doc = _stream_doc(
        b"/P <</MCID 0>> BDC BT /F1 12 Tf 72 700 Td ("
        + TARGET.encode()
        + b") Tj ET EMC"
    )
    show = _target_show(doc)
    assert show.mc_depth == 1
    _assert_only_off_nominal(show, "mc_depth")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "marked-content" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


def test_planner_rejects_nonzero_render_mode():
    """G2: stroke/clip render modes change what the same bytes paint."""
    doc = _stream_doc(b"BT /F1 12 Tf 2 Tr 72 700 Td (" + TARGET.encode() + b") Tj ET")
    show = _target_show(doc)
    assert show.render_mode == 2
    _assert_only_off_nominal(show, "render_mode")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "render_mode=2" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


def test_planner_rejects_nonzero_text_rise():
    """G3: a raised/lowered baseline (superscript run) is not Tier 0."""
    doc = _stream_doc(b"BT /F1 12 Tf 3 Ts 72 700 Td (" + TARGET.encode() + b") Tj ET")
    show = _target_show(doc)
    assert show.rise == 3.0
    _assert_only_off_nominal(show, "rise")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "rise=3.0" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


def test_planner_rejects_non_default_horizontal_scale():
    """G4: condensed/expanded text invalidates the equal-advance proof."""
    doc = _stream_doc(b"BT /F1 12 Tf 80 Tz 72 700 Td (" + TARGET.encode() + b") Tj ET")
    show = _target_show(doc)
    assert show.hscale == 80.0
    _assert_only_off_nominal(show, "hscale")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "hscale=80.0" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


def test_planner_rejects_show_op_with_no_font_selected():
    """G8: a Tj with no preceding Tf has no face to measure advance with."""
    doc = _stream_doc(b"BT 72 700 Td (" + TARGET.encode() + b") Tj ET")
    show = _target_show(doc)
    assert show.font_resource is None
    assert show.font_size == 0.0
    _assert_only_off_nominal(show)  # only the font selection is off-nominal

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.FONT_FACE_UNAVAILABLE
    # Distinguishes this gate from the resource-lookup gate below, which
    # also fires FONT_FACE_UNAVAILABLE (and would swallow this case:
    # capability(page, None) is None too).
    assert "no font selected" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


def test_planner_rejects_font_resource_missing_from_page_resources():
    """G9: Tf names /F9, but the page's /Resources /Font only defines /F1."""
    doc = _stream_doc(b"BT /F9 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET")
    show = _target_show(doc)
    assert show.font_resource == "F9"  # non-None: passes the G8 gate
    _assert_only_off_nominal(show)

    registry = DocumentFontRegistry(doc)
    assert registry.capability(doc[0], "F9") is None
    assert registry.capability(doc[0], "F1") is not None  # the page itself is sound

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.FONT_FACE_UNAVAILABLE
    assert "not resolvable" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


# ---------------------------------------------- inspect.py structural gates


def test_planner_rejects_show_op_outside_bt_et():
    """G5: text shown with no enclosing BT/ET block."""
    doc = _stream_doc(b"/F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj")
    show = _target_show(doc)
    assert show.in_bt is False
    _assert_only_off_nominal(show, "in_bt")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "outside BT/ET" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


def test_planner_rejects_origin_that_depends_on_a_preceding_advance():
    """G6: a second Tj with no repositioning op between the two.

    The target's origin is then the first show's *consumed advance*, which
    the replay does not compute — so the byte range cannot be corroborated
    against page geometry and the plan must refuse.
    """
    doc = _stream_doc(
        b"BT /F1 12 Tf 72 700 Td ("
        + LEAD_IN.encode()
        + b") Tj ("
        + TARGET.encode()
        + b") Tj ET"
    )
    replay = replay_page(doc, doc[0])
    assert not replay.malformed
    assert len(replay.shows) == 2
    # The FIRST show is reliable (Td set the origin); only the second one,
    # which is the target, inherits an untracked advance.
    assert replay.shows[0].origin_reliable is True
    assert replay.shows[0].decoded_bytes == LEAD_IN.encode("latin-1")

    show = _target_show(doc)
    assert show.seq == 1
    assert show.origin_reliable is False
    _assert_only_off_nominal(show, "origin_reliable")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNTRACKED_ADVANCE
    assert "preceding show operator" in rejection.detail
    doc.close()

    # Control: the same two shows, with a Td between them.
    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td ("
        + LEAD_IN.encode()
        + b") Tj 0 -14 Td ("
        + TARGET.encode()
        + b") Tj ET"
    )


def test_planner_rejects_uniformly_scaled_text_matrix():
    """G7: the TeX/dvips idiom of baking the point size into Tm.

    ``/F1 1 Tf`` with ``10 0 0 10 ... Tm`` renders at 10pt with a *uniform*
    (unrotated, unsheared) scale — visually indistinguishable from
    ``/F1 10 Tf``, but the byte-level advance arithmetic Tier 0 relies on
    no longer holds, so it must be refused just like a rotation.
    """
    doc = _stream_doc(
        b"BT /F1 1 Tf 10 0 0 10 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    show = _target_show(doc)
    assert show.tm == (10.0, 0.0, 0.0, 10.0, 72.0, 700.0)
    assert show.ctm == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)  # scale is in Tm, not cm
    assert show.tm[1] == 0.0 and show.tm[2] == 0.0  # uniform scale, not a rotation
    assert show.font_size == 1.0  # float, per the size-stays-float rule
    assert show.trm_translation_only is False
    _assert_only_off_nominal(show, "trm_translation_only")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "rotated, scaled, or sheared" in rejection.detail
    doc.close()

    # Control: identical stream with the Tm scale factors set to 1.
    _assert_control_plans_cleanly(
        b"BT /F1 1 Tf 1 0 0 1 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
