"""Red-light tests for text-state replay and source binding (plan Task 3).

Replay must interpret q/Q, cm, BT/ET, Tf, Tm, Td, TD, T*, TL, Tc, Tw, Tz,
Ts, Tr, Tj, TJ, ' and " over the ordered page stream list, recording exact
per-stream byte ranges.  Binding must corroborate text matches with
rawdict geometry and refuse — with stable reason codes — anything
ambiguous, malformed, inside a Form XObject, or in unsupported text state.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    BindingFailure,
    SourceSpanBinding,
    bind_source_text,
)
from model.text_commit.replay import replay_page_streams  # noqa: E402


def _replay_one(stream: bytes, xref: int = 5):
    return replay_page_streams([(xref, stream)])


# ---------------------------------------------------------------- replay


def test_replay_simple_tj_records_state_and_ranges():
    stream = b"BT /F1 12 Tf 72 700 Td (Hello) Tj ET"
    replay = _replay_one(stream)
    assert not replay.malformed
    assert len(replay.shows) == 1
    show = replay.shows[0]
    assert show.operator == "Tj"
    assert show.font_resource == "F1"
    assert show.font_size == 12.0
    assert show.decoded_bytes == b"Hello"
    assert show.in_bt
    assert show.origin_user == pytest.approx((72.0, 700.0))
    assert stream[show.string_start : show.string_end] == b"(Hello)"
    assert show.string_kind == "literal"
    assert show.stream_xref == 5


def test_replay_td_td_tstar_tl_positioning():
    stream = (
        b"BT /F1 10 Tf 20 TL 72 700 Td (a) Tj "
        b"0 -12 Td (b) Tj "
        b"T* (c) Tj "
        b"-2 -14 TD (d) Tj "
        b"T* (e) Tj ET"
    )
    replay = _replay_one(stream)
    origins = [s.origin_user for s in replay.shows]
    assert origins[0] == pytest.approx((72.0, 700.0))
    assert origins[1] == pytest.approx((72.0, 688.0))
    assert origins[2] == pytest.approx((72.0, 668.0))  # T* uses TL=20
    assert origins[3] == pytest.approx((70.0, 654.0))  # TD moves and sets TL=14
    assert origins[4] == pytest.approx((70.0, 640.0))  # T* uses TL=14
    assert all(s.origin_reliable for s in replay.shows)


def test_replay_cm_and_tm_compose_and_q_restores():
    stream = (
        b"q 2 0 0 2 10 20 cm BT /F1 12 Tf 1 0 0 1 50 100 Tm (x) Tj ET Q "
        b"BT /F1 12 Tf (y) Tj ET"
    )
    replay = _replay_one(stream)
    x_show, y_show = replay.shows
    assert x_show.origin_user == pytest.approx((110.0, 220.0))
    # A uniform positive scale is measured, not refused: the factor is what
    # page-space geometry (the fallback target bbox) is derived from.
    assert x_show.trm_uniform_scale == pytest.approx(2.0)
    assert x_show.trm_uniform_scaled
    assert x_show.gs_depth == 1
    assert y_show.origin_user == pytest.approx((0.0, 0.0))
    assert y_show.trm_uniform_scale == pytest.approx(1.0)  # pure translation
    assert y_show.gs_depth == 0


def test_replay_rotation_in_cm_has_no_uniform_scale():
    stream = b"q BT 0 1 -1 0 0 0 cm 1 0 0 1 442 -200 Tm /F1 12 Tf (R) Tj ET Q"
    replay = _replay_one(stream)
    show = replay.shows[0]
    assert show.origin_user == pytest.approx((200.0, 442.0))
    assert show.trm_uniform_scale is None
    assert not show.trm_uniform_scaled


def test_replay_records_spacing_scaling_rise_render_mode():
    stream = b"BT /F1 12 Tf 1.5 Tc 2.5 Tw 80 Tz 3 Ts 2 Tr 10 20 Td (s) Tj ET"
    show = _replay_one(stream).shows[0]
    assert show.char_spacing == 1.5
    assert show.word_spacing == 2.5
    assert show.hscale == 80.0
    assert show.rise == 3.0
    assert show.render_mode == 2


def test_replay_q_restores_text_state_parameters():
    stream = (
        b"BT /F1 12 Tf q 5 Tc /F2 8 Tf 10 700 Td (in) Tj Q 10 650 Td (out) Tj ET"
    )
    replay = _replay_one(stream)
    inner, outer = replay.shows
    assert inner.char_spacing == 5.0
    assert inner.font_resource == "F2"
    assert inner.font_size == 8.0
    assert outer.char_spacing == 0.0
    assert outer.font_resource == "F1"
    assert outer.font_size == 12.0


def test_replay_tj_array_joins_strings_and_spans_array():
    stream = b"BT /F1 12 Tf 72 700 Td [(A) -120 (V) 15 <2042>] TJ ET"
    show = _replay_one(stream).shows[0]
    assert show.operator == "TJ"
    assert show.decoded_bytes == b"AV B"
    assert show.string_kind == "array"
    assert show.array_item_count == 3
    assert stream[show.string_start : show.string_end] == b"[(A) -120 (V) 15 <2042>]"


def test_replay_hex_string_tj():
    stream = b"BT /helv 12 Tf 1 0 0 1 72 742 Tm [<48656c6c6f>] TJ ET"
    show = _replay_one(stream).shows[0]
    assert show.decoded_bytes == b"Hello"
    assert show.array_item_count == 1


def test_replay_quote_operators_advance_line_and_set_spacing():
    stream = (
        b"BT /F1 12 Tf 20 TL 72 700 Td (l1) Tj (l2) ' 3 1.5 (l3) \" ET"
    )
    replay = _replay_one(stream)
    assert [s.operator for s in replay.shows] == ["Tj", "'", '"']
    assert replay.shows[1].origin_user == pytest.approx((72.0, 680.0))
    quote2 = replay.shows[2]
    assert quote2.origin_user == pytest.approx((72.0, 660.0))
    assert quote2.word_spacing == 3.0
    assert quote2.char_spacing == 1.5
    assert quote2.decoded_bytes == b"l3"


def test_replay_second_show_without_reposition_is_unreliable():
    stream = b"BT /F1 12 Tf 72 700 Td (a) Tj (b) Tj ET"
    replay = _replay_one(stream)
    assert replay.shows[0].origin_reliable
    assert not replay.shows[1].origin_reliable


def test_replay_state_carries_across_streams():
    replay = replay_page_streams(
        [
            (10, b"q 1 0 0 1 30 40 cm"),
            (11, b"BT /F1 12 Tf 72 700 Td (x) Tj ET Q"),
        ]
    )
    show = replay.shows[0]
    assert show.stream_xref == 11
    assert show.origin_user == pytest.approx((102.0, 740.0))
    assert show.gs_depth == 1


def test_replay_malformed_stream_flagged():
    replay = _replay_one(b"BT /F1 12 Tf (never closed")
    assert replay.malformed


def test_replay_records_xobject_invocation_and_mc_depth():
    stream = b"/P <</MCID 0>> BDC BT /F1 9 Tf 5 5 Td (m) Tj ET EMC /FX0 Do"
    replay = _replay_one(stream)
    assert replay.has_xobject_invocation
    assert replay.shows[0].mc_depth == 1


def test_replay_show_outside_bt_recorded_as_such():
    replay = _replay_one(b"/F1 12 Tf 10 10 Td (x) Tj")
    assert not replay.shows[0].in_bt


# ---------------------------------------------------------------- binding


def _span_origin(page: fitz.Page, probe: str) -> tuple[float, float]:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if probe in text:
                    return tuple(span["origin"])
    raise AssertionError(f"span {probe!r} not found")


def _single_page_doc() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=12.0, fontname="helv")
    page.insert_text((72, 200), "Second line", fontsize=12.0, fontname="helv")
    return doc


def test_bind_simple_page_text_succeeds():
    doc = _single_page_doc()
    page = doc[0]
    origin = _span_origin(page, "Hello World")
    binding = bind_source_text(
        doc, page, target_text="Hello World", expected_origin=origin
    )
    assert isinstance(binding, SourceSpanBinding), binding
    assert binding.stream_xref in page.get_contents()
    assert binding.show.decoded_bytes == b"Hello World"
    assert len(binding.stream_digest) == 64
    assert binding.origin_page == pytest.approx(origin, abs=0.5)
    doc.close()


def test_bind_duplicate_text_distinct_origins_disambiguates():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Duplicate", fontsize=12.0, fontname="helv")
    page.insert_text((72, 300), "Duplicate", fontsize=12.0, fontname="helv")
    origin_2 = (72.0, 300.0)
    binding = bind_source_text(
        doc, page, target_text="Duplicate", expected_origin=origin_2
    )
    assert isinstance(binding, SourceSpanBinding), binding
    assert binding.origin_page == pytest.approx(origin_2, abs=0.5)
    doc.close()


def test_bind_duplicate_text_same_origin_is_ambiguous():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Twin", fontsize=12.0, fontname="helv")
    xref = page.get_contents()[0]
    doc.update_stream(xref, doc.xref_stream(xref) * 2)  # duplicate the show op
    binding = bind_source_text(
        doc, page, target_text="Twin", expected_origin=(72.0, 100.0)
    )
    assert isinstance(binding, BindingFailure)
    assert binding.reason == RejectReason.AMBIGUOUS_MATCH
    doc.close()


def test_bind_missing_text_reports_no_match():
    doc = _single_page_doc()
    binding = bind_source_text(
        doc, doc[0], target_text="Nonexistent", expected_origin=(50.0, 50.0)
    )
    assert isinstance(binding, BindingFailure)
    assert binding.reason == RejectReason.NO_MATCH
    doc.close()


def test_bind_form_xobject_target_refused():
    """Confirmed target-in-XObject keeps ``TARGET_IN_FORM_XOBJECT``."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Page-level text", fontsize=12.0, fontname="helv")

    # Embed the missing target inside a Form XObject the page invokes.
    form_xref = doc.get_new_xref()
    doc.update_object(
        form_xref,
        "<< /Type /XObject /Subtype /Form /BBox [0 0 200 50] "
        "/Resources << /Font << /F1 1 0 R >> >> >>",
    )
    # Helvetica resource for the form: reuse a page font if present, else
    # install one under the form's own Resources below.
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.update_object(
        form_xref,
        f"<< /Type /XObject /Subtype /Form /BBox [0 0 200 50] "
        f"/Resources << /Font << /F1 {font_xref} 0 R >> >> >>",
    )
    doc.update_stream(
        form_xref,
        b"BT /F1 12 Tf 0 10 Td (XObject text inside) Tj ET",
    )
    doc.xref_set_key(
        page.xref,
        "Resources",
        f"<< /XObject << /FX1 {form_xref} 0 R >> "
        f"/Font << /F1 {font_xref} 0 R >> >>",
    )
    page_xref = page.get_contents()[0]
    invoke = b"\nq 1 0 0 1 72 650 cm /FX1 Do Q\n"
    doc.update_stream(page_xref, doc.xref_stream(page_xref) + invoke)

    binding = bind_source_text(
        doc, page, target_text="XObject text inside", expected_origin=(80.0, 160.0)
    )
    assert isinstance(binding, BindingFailure)
    assert binding.reason == RejectReason.TARGET_IN_FORM_XOBJECT
    doc.close()


def test_bind_miss_on_xobject_page_reports_no_match_not_form_xobject():
    """A page that merely invokes an XObject must not rebrand every miss.

    Production used to fire ``TARGET_IN_FORM_XOBJECT`` whenever
    ``has_xobject_invocation`` was true — 98.6% of corpus pages — even when
    the target bytes were nowhere in any invoked Form XObject.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Page-level text", fontsize=12.0, fontname="helv")
    form_xref = doc.get_new_xref()
    doc.update_object(
        form_xref,
        "<< /Type /XObject /Subtype /Form /BBox [0 0 100 20] >>",
    )
    doc.update_stream(form_xref, b"BT /F1 12 Tf 0 0 Td (logo) Tj ET")
    doc.xref_set_key(
        page.xref, "Resources", f"<< /XObject << /FX1 {form_xref} 0 R >> >>"
    )
    page_xref = page.get_contents()[0]
    invoke = b"\nq 1 0 0 1 72 650 cm /FX1 Do Q\n"
    doc.update_stream(page_xref, doc.xref_stream(page_xref) + invoke)

    binding = bind_source_text(
        doc, page, target_text="Nonexistent target", expected_origin=(50.0, 50.0)
    )
    assert isinstance(binding, BindingFailure)
    assert binding.reason == RejectReason.NO_MATCH
    doc.close()


def test_bind_geometry_disagreement_is_evidence_mismatch():
    doc = _single_page_doc()
    binding = bind_source_text(
        doc, doc[0], target_text="Hello World", expected_origin=(400.0, 500.0)
    )
    assert isinstance(binding, BindingFailure)
    assert binding.reason == RejectReason.EVIDENCE_MISMATCH
    doc.close()


def test_bind_rotated_text_refused_as_unsupported_state():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(
        (200, 400), "Rotated 90", fontsize=12.0, fontname="helv", rotate=90
    )
    origin = _span_origin(page, "Rotated 90")
    binding = bind_source_text(
        doc, page, target_text="Rotated 90", expected_origin=origin
    )
    assert isinstance(binding, BindingFailure)
    assert binding.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    doc.close()


def test_bind_malformed_stream_refused():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Fine text", fontsize=12.0, fontname="helv")
    xref = page.get_contents()[0]
    doc.update_stream(xref, doc.xref_stream(xref) + b"\nBT (broken")
    binding = bind_source_text(
        doc, page, target_text="Fine text", expected_origin=(72.0, 100.0)
    )
    assert isinstance(binding, BindingFailure)
    assert binding.reason == RejectReason.MALFORMED_STREAM
    doc.close()


def test_binding_failures_carry_detail_text():
    doc = _single_page_doc()
    binding = bind_source_text(
        doc, doc[0], target_text="Nonexistent", expected_origin=(50.0, 50.0)
    )
    assert isinstance(binding, BindingFailure)
    assert binding.detail
    doc.close()
