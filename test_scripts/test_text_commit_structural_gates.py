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

import math
import sys
from pathlib import Path

import fitz
import pytest

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
    "trm_uniform_scaled": True,  # inspect.py G7 -> UNSUPPORTED_TEXT_STATE
    "operator": "Tj",  # plan.py    -> NOT_SINGLE_LITERAL_TJ
    # "hex" is equally admissible since 2026-08-01; every fixture here is
    # literal, so one nominal value still suffices.
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


def test_planner_accepts_uniformly_scaled_text_matrix():
    """G7 (relaxed 2026-08-01): the TeX/dvips idiom is a Tier 0 candidate.

    ``/F1 1 Tf`` with ``10 0 0 10 ... Tm`` renders at 10pt with a *uniform,
    axis-aligned, positive* scale — visually indistinguishable from
    ``/F1 10 Tf``.  The equal-advance proof is scale-invariant (both sides
    are measured in text space and multiplied by the same factor), so this
    shape is admitted; rotation, shear, and reflection are not, and are
    pinned by the two tests below.

    This test was ``test_planner_rejects_uniformly_scaled_text_matrix``
    before the relaxation; it is revised rather than deleted so the
    fixture's isolation guarantee (:func:`_assert_only_off_nominal`) keeps
    covering the same content-stream shape.
    """
    doc = _stream_doc(
        b"BT /F1 1 Tf 10 0 0 10 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    show = _target_show(doc)
    assert show.tm == (10.0, 0.0, 0.0, 10.0, 72.0, 700.0)
    assert show.ctm == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)  # scale is in Tm, not cm
    assert show.font_size == 1.0  # float, per the size-stays-float rule
    assert show.trm_uniform_scale == pytest.approx(10.0)
    _assert_only_off_nominal(show)  # nothing is off-nominal any more

    prepared = _plan(doc)
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.font_size == 1.0  # the Tf size, not the effective size
    doc.close()


# Deleting the ``abs(b) > _EPS or abs(c) > _EPS`` half of
# ``replay._uniform_scale`` makes every matrix below return its ``a``, so
# each of these three MUST fail on that mutation.  A 90-degree rotation
# would not: its ``a`` is 0 and the ``a > 0`` guard catches it anyway.
@pytest.mark.parametrize(
    ("label", "text_matrix"),
    [
        ("rotation_45", b"0.7071 0.7071 -0.7071 0.7071"),  # b and c both set
        ("shear_b", b"1 0.5 0 1"),  # only b set
        ("shear_c", b"1 0 0.5 1"),  # only c set
    ],
)
def test_planner_rejects_off_axis_text_matrix(label, text_matrix):
    """G7: rotation and shear keep ``a == d > 0`` but are not Tier 0."""
    doc = _stream_doc(
        b"BT /F1 12 Tf " + text_matrix + b" 72 700 Tm ("
        + TARGET.encode()
        + b") Tj ET"
    )
    show = _target_show(doc)
    assert show.tm[0] == pytest.approx(show.tm[3])  # the a == d guard is happy
    assert show.tm[0] > 0.0  # so is the a > 0 guard
    assert show.trm_uniform_scale is None
    _assert_only_off_nominal(show, "trm_uniform_scaled")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "rotated, sheared, reflected" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )


# ``point_reflection`` is the only fixture here that pins the ``a > 0``
# guard: delete it and ``_uniform_scale`` returns -10.0, so upside-down
# text would plan (and the fallback bbox would come out inverted).  The
# other two are guarded by ``a == d`` / ``b == c == 0`` and pin nothing on
# their own — they are kept as documentation of the refused shapes.
@pytest.mark.parametrize(
    ("label", "text_matrix"),
    [
        ("point_reflection", b"-10 0 0 -10"),  # a == d < 0
        ("mirror_x", b"-10 0 0 10"),  # a == -d
        ("rotation_90", b"0 10 -10 0"),  # a == d == 0
    ],
)
def test_planner_rejects_reflected_or_rotated_text_matrix(label, text_matrix):
    """G7: a negative or degenerate scale is never a Tier 0 candidate."""
    doc = _stream_doc(
        b"BT /F1 1 Tf " + text_matrix + b" 300 400 Tm ("
        + TARGET.encode()
        + b") Tj ET"
    )
    show = _target_show(doc)
    assert show.tm[0] <= 0.0
    assert show.trm_uniform_scale is None
    _assert_only_off_nominal(show, "trm_uniform_scaled")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "rotated, sheared, reflected" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 1 Tf 10 0 0 10 300 400 Tm (" + TARGET.encode() + b") Tj ET"
    )


# ------------------------------------------------- fallback target geometry


def _rendered_span_bbox(doc: fitz.Document) -> tuple[float, float, float, float]:
    """MuPDF's own page-space bbox for the target — an independent oracle."""
    for block in doc[0].get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if TARGET in "".join(ch["c"] for ch in span["chars"]):
                    return tuple(span["bbox"])
    raise AssertionError("target span not rendered")


def test_fallback_target_bbox_follows_the_text_matrix_scale():
    """No caller bbox + a scaled Tm: the halo must be in PAGE space.

    ``_advance`` measures in *text* space, so at ``a == d == 0.5`` the
    fallback bbox derived straight from it is twice as wide and twice as
    tall as the glyphs actually painted.  An over-wide halo is the
    dangerous direction: ``verify`` asserts raster identity *outside* it,
    so corruption in the inflated margin is a false ACCEPT.
    """
    doc = _stream_doc(
        b"BT /F1 24 Tf 0.5 0 0 0.5 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    page = doc[0]
    capability = DocumentFontRegistry(doc).capability(page, "F1")
    assert capability is not None
    text_space_advance = capability.string_width(TARGET, 24.0)
    assert text_space_advance is not None

    prepared = _plan(doc)  # _plan passes target_bbox=None
    assert isinstance(prepared, PreparedEdit), prepared
    x0, y0, x1, y1 = prepared.target_bbox_page

    assert x1 - x0 == pytest.approx(0.5 * text_space_advance, abs=0.01)
    assert y1 - y0 == pytest.approx(0.5 * 24.0 * 1.35, abs=0.01)
    # Origin (72, 700) in user space is (72, 142) in MuPDF page space.
    assert x0 == pytest.approx(72.0, abs=0.01)
    assert y0 == pytest.approx(142.0 - 0.5 * 24.0, abs=0.01)

    # Independent oracle: MuPDF's own layout of the same stream.
    rx0, _, rx1, _ = _rendered_span_bbox(doc)
    assert x0 == pytest.approx(rx0, abs=1.0)
    assert x1 == pytest.approx(rx1, abs=1.0)
    doc.close()


def test_fallback_target_bbox_includes_the_page_user_unit_scale():
    """No caller bbox + ``/UserUnit != 1``: the page scale counts too.

    MuPDF folds ``/UserUnit`` into ``page.rect`` and
    ``page.transformation_matrix`` (2.0 at ``/UserUnit 2``), so
    ``binding.origin_page`` already carries that factor while ``_advance``
    and ``font_size`` are still text space.  Applying only the Tm scale
    leaves the halo off by the ``/UserUnit`` factor: here the net page
    scale is ``0.5 * 2 == 1`` and the glyphs are full size, so a half-size
    halo makes ``verify`` V0c report the replacement "not extractable at
    the target" and reject a valid edit.
    """
    doc = _stream_doc(
        b"BT /F1 24 Tf 0.5 0 0 0.5 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    doc.xref_set_key(doc[0].xref, "UserUnit", "2")
    page = doc[0]  # re-fetch: the page's transform is read when it is loaded
    matrix = page.transformation_matrix
    assert math.hypot(matrix.a, matrix.b) == pytest.approx(
        2.0
    ), "fixture: /UserUnit did not reach the page transform"

    capability = DocumentFontRegistry(doc).capability(page, "F1")
    assert capability is not None
    text_space_advance = capability.string_width(TARGET, 24.0)
    assert text_space_advance is not None

    prepared = _plan(doc)  # _plan passes target_bbox=None
    assert isinstance(prepared, PreparedEdit), prepared
    x0, y0, x1, y1 = prepared.target_bbox_page

    # Net page scale is 0.5 (Tm) * 2 (/UserUnit) == 1: full-size glyphs.
    assert x1 - x0 == pytest.approx(text_space_advance, abs=0.01)
    assert y1 - y0 == pytest.approx(24.0 * 1.35, abs=0.01)
    # Origin (72, 700) in user space is (144, 284) in MuPDF page space.
    assert x0 == pytest.approx(144.0, abs=0.01)
    assert y0 == pytest.approx(284.0 - 24.0, abs=0.01)

    # Independent oracle: MuPDF's own layout of the same stream.
    rx0, _, rx1, _ = _rendered_span_bbox(doc)
    assert x0 == pytest.approx(rx0, abs=1.0)
    assert x1 == pytest.approx(rx1, abs=1.0)
    doc.close()


def test_fallback_target_bbox_is_not_inflated_by_a_sub_unit_user_unit():
    """The *dangerous* direction of the same defect: an inflated halo.

    ``/UserUnit 0.5`` halves the page transform, so ``2 0 0 2 Tm`` again
    nets to page scale 1.  Ignoring the page factor scales the halo by 2 on
    each axis -- 4x the area -- and verification cannot catch that: V0d
    proves raster identity only *outside* the halo, so the inflated margin
    absorbs corruption instead of reporting it.  Pinning both directions
    also pins the multiply: dividing by the page scale passes the
    ``/UserUnit 2`` case above and fails here.
    """
    doc = _stream_doc(
        b"BT /F1 24 Tf 2 0 0 2 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    doc.xref_set_key(doc[0].xref, "UserUnit", "0.5")
    page = doc[0]  # re-fetch: the page's transform is read when it is loaded
    matrix = page.transformation_matrix
    assert math.hypot(matrix.a, matrix.b) == pytest.approx(
        0.5
    ), "fixture: /UserUnit did not reach the page transform"

    capability = DocumentFontRegistry(doc).capability(page, "F1")
    assert capability is not None
    text_space_advance = capability.string_width(TARGET, 24.0)
    assert text_space_advance is not None

    prepared = _plan(doc)  # _plan passes target_bbox=None
    assert isinstance(prepared, PreparedEdit), prepared
    x0, y0, x1, y1 = prepared.target_bbox_page

    # Net page scale is 2 (Tm) * 0.5 (/UserUnit) == 1 again.
    assert x1 - x0 == pytest.approx(text_space_advance, abs=0.01)
    assert y1 - y0 == pytest.approx(24.0 * 1.35, abs=0.01)
    # Origin (72, 700) in user space is (36, 71) in MuPDF page space.
    assert x0 == pytest.approx(36.0, abs=0.01)
    assert y0 == pytest.approx(71.0 - 24.0, abs=0.01)

    # Independent oracle: MuPDF's own layout of the same stream.
    rx0, _, rx1, _ = _rendered_span_bbox(doc)
    assert x0 == pytest.approx(rx0, abs=1.0)
    assert x1 == pytest.approx(rx1, abs=1.0)
    doc.close()


def test_fallback_target_bbox_is_unchanged_at_unit_scale():
    """Control: the scale correction must be a no-op at ``a == d == 1``."""
    doc = _stream_doc(
        b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    capability = DocumentFontRegistry(doc).capability(doc[0], "F1")
    assert capability is not None
    advance = capability.string_width(TARGET, 12.0)

    prepared = _plan(doc)
    assert isinstance(prepared, PreparedEdit), prepared
    x0, y0, x1, y1 = prepared.target_bbox_page
    assert x1 - x0 == pytest.approx(advance, abs=0.01)
    assert y1 - y0 == pytest.approx(12.0 * 1.35, abs=0.01)
    doc.close()


@pytest.mark.parametrize("rotation", [90, 270])
def test_fallback_target_bbox_follows_page_rotate(rotation):
    """No caller bbox + ``/Rotate 90/270``: shape must follow the visual matrix.

    ``page.transformation_matrix`` alone omits /Rotate in PyMuPDF; the
    fallback must also apply ``page.rotation_matrix`` so the halo matches
    pixmap ink (vertical under 90/270). Building from unrotated
    ``origin_page`` along page-x leaves a horizontal halo while glyphs run
    vertically in visual space.
    """
    doc = _stream_doc(
        b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    doc[0].set_rotation(rotation)
    data = doc.tobytes()
    doc.close()
    doc = fitz.open("pdf", data)
    page = doc[0]
    assert page.rotation == rotation

    capability = DocumentFontRegistry(doc).capability(page, "F1")
    assert capability is not None
    advance = capability.string_width(TARGET, 12.0)
    assert advance is not None
    # Analytic oracle: same user-space construction the planner must use,
    # mapped through the full visual matrix (not rawdict — glyph ink ≠ the
    # 1.0/0.35 ascent/descent heuristic).
    user = fitz.Rect(72.0, 700.0 - 0.35 * 12.0, 72.0 + advance, 700.0 + 12.0)
    expected = user * page.transformation_matrix * page.rotation_matrix

    prepared = _plan(doc)
    assert isinstance(prepared, PreparedEdit), prepared
    x0, y0, x1, y1 = prepared.target_bbox_page
    assert x0 == pytest.approx(expected.x0, abs=0.05)
    assert y0 == pytest.approx(expected.y0, abs=0.05)
    assert x1 == pytest.approx(expected.x1, abs=0.05)
    assert y1 == pytest.approx(expected.y1, abs=0.05)
    # Orientation: under 90/270 the advance runs along a visual axis where
    # height dominates width (the broken formula keeps width >> height).
    assert (y1 - y0) > (x1 - x0)

    # Independent: first dark pixmap pixels must sit inside the halo.
    pix = page.get_pixmap(dpi=72)
    samples = bytes(pix.samples)
    n = pix.n
    found = False
    for y in range(pix.height):
        for x in range(pix.width):
            i = (y * pix.width + x) * n
            if samples[i] < 200:
                assert x0 - 2.0 <= x <= x1 + 2.0
                assert y0 - 2.0 <= y <= y1 + 2.0
                found = True
                break
        if found:
            break
    assert found, "fixture: no dark pixmap pixels found"
    doc.close()
