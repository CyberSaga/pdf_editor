"""Red-light tests for the P0-A replay resource guard (Task 12).

``replay_page_streams`` is the only production path into
``lex_content_stream``, which materializes the full token list: a measured
~72 MB decoded page stream became ~54.7M StreamToken objects and ~10 GB of
RSS before a single show op was bound.  The guard must refuse *before*
tokenization — at the chokepoint only — with the stable reason
``content_stream_too_large_for_safe_replay``.

Frozen invariants these tests pin (plan §6, 2026-08-12):

* Refusal happens BEFORE any lex call (spy raises if invoked).
* The budget is summed across the page's ordered stream list, not
  per-stream (state carries across streams; the lexer walks all of them).
* The reason survives VERBATIM to ``BindingFailure`` and ``PlanRejection``
  — never collapsed into ``malformed_stream``, ``no_source_match``, or
  ``verification_failed``.  (A ``no_source_match`` collapse would even be
  re-labelled ``target_reconstruction_unverified`` by
  ``_reconstruction_aware_reason`` on run-joined targets: a double lie.)
* ``read_page_streams`` and fingerprint hashing stay UNGUARDED: commit
  verification must still hash oversized streams, or a perf limit becomes
  a correctness failure.

All fixtures are synthetic (generated vector-path operators); nothing is
derived from any real document.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit import replay as replay_module  # noqa: E402
from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    BindingFailure,
    bind_source_text,
    page_fingerprint,
    read_page_streams,
)
from model.text_commit.plan import PlanRejection, prepare_tier0_plan  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402

# The stable reason string is the contract (telemetry/UI-facing); the tests
# spell it out rather than importing the constant so a rename cannot silently
# rewrite the expectation.
TOO_LARGE = "content_stream_too_large_for_safe_replay"

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # helv digits share widths: advance-neutral

# One well-formed painting chunk; repeated it makes an arbitrarily large but
# perfectly lexable stream (no shows, no malformed tokens).
_PATH_CHUNK = b"10 20 m 30 40 l 50 60 70 80 90 100 c S\n"

# The default-budget fixture must exceed any admissible default.  8 MiB is
# the calibration ceiling from the plan (§9: ~0.77 tokens/byte and ~133x RSS
# amplification pre-streaming put even 8 MiB at ~1 GB transient RSS).
_DEFAULT_BUDGET_CEILING = 8 * 1024 * 1024
_OVERSIZED_STREAM_BYTES = _DEFAULT_BUDGET_CEILING + 65536

_TEXT_PREFIX = b"BT /F1 12 Tf 72 700 Td (Price 2024) Tj ET\n"


def _vector_junk(total_bytes: int) -> bytes:
    return _PATH_CHUNK * (total_bytes // len(_PATH_CHUNK) + 1)


def _stream_doc(stream: bytes) -> fitz.Document:
    """One page whose only content is ``stream``, with /F1 = Helvetica.

    Same xref surgery as ``test_text_commit_structural_gates._stream_doc``:
    a known-good Tier 0 baseline page so only the stream size is off-nominal.
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


@pytest.fixture(scope="module")
def oversized_doc():
    """A page holding TARGET plus enough vector junk to exceed any default.

    The target IS present and would bind cleanly on a small page — the
    refusal must be about resources, not a match failure.
    """
    stream = _TEXT_PREFIX + _vector_junk(_OVERSIZED_STREAM_BYTES)
    assert len(stream) >= _OVERSIZED_STREAM_BYTES
    doc = _stream_doc(stream)
    yield doc
    doc.close()


# ----------------------------------------------------------- reason contract


def test_reason_constant_registered():
    """The stable code joins RejectReason's telemetry/UI vocabulary."""
    assert RejectReason.CONTENT_STREAM_TOO_LARGE == TOO_LARGE


def test_default_budget_constant_is_bounded():
    """The default budget exists and cannot exceed the calibration ceiling.

    Pins the oversized fixture's validity: if the default is ever raised
    past 8 MiB this fails, forcing the fixture (and the calibration
    argument) to grow with it.
    """
    from model.text_commit.replay import DEFAULT_MAX_REPLAY_BYTES

    assert 0 < DEFAULT_MAX_REPLAY_BYTES <= _DEFAULT_BUDGET_CEILING


# ------------------------------------------------------------ replay guard


def test_oversized_streams_refuse_before_lex(monkeypatch):
    def _boom(data):
        raise AssertionError(
            "lex_content_stream must not run for a refused page"
        )

    monkeypatch.setattr(replay_module, "lex_content_stream", _boom)
    stream = b"0 0 m 10 10 l S\n" * 128  # 2 KiB
    result = replay_page_streams([(5, stream)], max_decoded_bytes=1024)
    assert result.refusal_reason == TOO_LARGE
    assert result.shows == ()
    assert not result.malformed
    assert result.stream_xrefs == (5,)


def test_budget_is_summed_across_streams(monkeypatch):
    """Two streams each under budget must still refuse when their sum is over.

    Replay state carries across the page's stream sequence, so the lexer
    walks all of them; a per-stream budget would be a hole.
    """

    def _boom(data):
        raise AssertionError(
            "lex_content_stream must not run for a refused page"
        )

    monkeypatch.setattr(replay_module, "lex_content_stream", _boom)
    seven_hundred = b"0 0 m 10 10 l S\n" * 44  # 704 bytes
    result = replay_page_streams(
        [(5, seven_hundred), (7, seven_hundred)], max_decoded_bytes=1024
    )
    assert result.refusal_reason == TOO_LARGE
    assert result.shows == ()
    assert result.stream_xrefs == (5, 7)


def test_streams_within_budget_replay_identically():
    stream = b"BT /F1 12 Tf 72 700 Td (Hello) Tj ET"
    guarded = replay_page_streams([(5, stream)], max_decoded_bytes=1 << 20)
    default = replay_page_streams([(5, stream)])
    assert guarded == default
    assert default.refusal_reason is None
    assert len(default.shows) == 1
    assert default.shows[0].decoded_bytes == b"Hello"


def test_none_budget_disables_the_guard():
    stream = b"0 0 m 10 10 l S\n" * 4096  # 64 KiB
    refused = replay_page_streams([(5, stream)], max_decoded_bytes=1024)
    assert refused.refusal_reason == TOO_LARGE
    unguarded = replay_page_streams([(5, stream)], max_decoded_bytes=None)
    assert unguarded.refusal_reason is None
    assert not unguarded.malformed


def test_budget_boundary_is_strictly_greater_than():
    """Boundary pin (feature already red-lit above): total == budget must
    replay, total == budget + 1 must refuse — nails the strict ``>`` so a
    ``>=`` or off-by-k drift cannot land silently."""
    stream = b"BT /F1 12 Tf 72 700 Td (Hello) Tj ET"
    exact = replay_page_streams([(5, stream)], max_decoded_bytes=len(stream))
    assert exact.refusal_reason is None
    assert len(exact.shows) == 1
    over = replay_page_streams([(5, stream)], max_decoded_bytes=len(stream) - 1)
    assert over.refusal_reason == TOO_LARGE
    assert over.shows == ()


# ------------------------------------------------- verbatim reason propagation


def test_bind_refuses_oversized_page_with_verbatim_reason(oversized_doc):
    result = bind_source_text(
        oversized_doc,
        oversized_doc[0],
        target_text=TARGET,
        expected_origin=None,
    )
    assert isinstance(result, BindingFailure)
    assert result.reason == TOO_LARGE
    # The exact collapse modes the invariant forbids:
    assert result.reason not in {
        RejectReason.MALFORMED_STREAM,
        RejectReason.NO_MATCH,
        RejectReason.VERIFICATION_FAILED,
    }


def test_plan_rejection_reason_survives_verbatim(oversized_doc):
    page = oversized_doc[0]
    fingerprint_before = page_fingerprint(oversized_doc, page)
    xrefs_before = oversized_doc.xref_length()
    result = prepare_tier0_plan(
        oversized_doc,
        page,
        target_text=TARGET,
        replacement_text=REPLACEMENT,
        expected_origin=None,
        target_bbox=None,
        registry=DocumentFontRegistry(oversized_doc),
    )
    # Zero mutation: same read-only pins as the structural-gate suite.
    assert page_fingerprint(oversized_doc, page) == fingerprint_before
    assert oversized_doc.xref_length() == xrefs_before
    assert isinstance(result, PlanRejection)
    assert result.reason == TOO_LARGE


def _xobject_doc(xobj_stream: bytes) -> fitz.Document:
    """Page whose direct stream lacks TARGET but invokes a Form XObject."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(
        content_xref, b"BT /F1 12 Tf 72 700 Td (Other text) Tj ET /X1 Do"
    )
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    xobj_xref = doc.get_new_xref()
    doc.update_object(
        xobj_xref, "<< /Type /XObject /Subtype /Form /BBox [0 0 595 842] >>"
    )
    doc.update_stream(xobj_xref, xobj_stream)
    doc.xref_set_key(
        page.xref,
        "Resources",
        f"<< /Font << /F1 {font_xref} 0 R >> "
        f"/XObject << /X1 {xobj_xref} 0 R >> >>",
    )
    return doc


def test_oversized_form_xobject_with_target_surfaces_refusal():
    """A target inside an over-budget invoked Form XObject must surface the
    refusal — not a fabricated TARGET_IN_FORM_XOBJECT "confirmed" claim
    (nothing was scanned) and not NO_MATCH (which
    ``_reconstruction_aware_reason`` could rewrite into a fabricated
    ``target_reconstruction_unverified`` diagnosis on run-joined targets).
    """
    doc = _xobject_doc(_TEXT_PREFIX + _vector_junk(_OVERSIZED_STREAM_BYTES))
    try:
        result = bind_source_text(
            doc, doc[0], target_text=TARGET, expected_origin=None
        )
        assert isinstance(result, BindingFailure)
        assert result.reason == TOO_LARGE
    finally:
        doc.close()


def test_oversized_form_xobject_without_target_still_refuses():
    """Absence is equally unprovable: NO_MATCH claims the document lacks the
    text, but an unscannable invoked XObject means nobody looked — the
    refusal must win over the unprovable claim."""
    doc = _xobject_doc(_vector_junk(_OVERSIZED_STREAM_BYTES))
    try:
        result = bind_source_text(
            doc, doc[0], target_text=TARGET, expected_origin=None
        )
        assert isinstance(result, BindingFailure)
        assert result.reason == TOO_LARGE
        assert result.reason != RejectReason.NO_MATCH
    finally:
        doc.close()


def test_small_form_xobject_scan_still_confirms_target():
    """Scope pin: under-budget XObject scans keep the old behavior — the
    target confirmed inside an invoked Form XObject still reports
    TARGET_IN_FORM_XOBJECT, and the refusal path does not fire."""
    doc = _xobject_doc(b"BT /F1 12 Tf 72 700 Td (Price 2024) Tj ET")
    try:
        result = bind_source_text(
            doc, doc[0], target_text=TARGET, expected_origin=None
        )
        assert isinstance(result, BindingFailure)
        assert result.reason == RejectReason.TARGET_IN_FORM_XOBJECT
    finally:
        doc.close()


# ------------------------------------------------------------- scope pins
# These two pass before the guard exists and must KEEP passing after: they
# fail only if the guard lands in the wrong place (read_page_streams or the
# fingerprint path), which is exactly the overreach the plan forbids.


def test_read_page_streams_stays_unguarded(oversized_doc):
    streams = read_page_streams(oversized_doc, oversized_doc[0])
    total = sum(len(data) for _, data in streams)
    assert total >= _OVERSIZED_STREAM_BYTES


def test_oversized_stream_stays_hashable_for_verification(oversized_doc):
    streams = read_page_streams(oversized_doc, oversized_doc[0])
    digest = hashlib.sha256(streams[0][1]).hexdigest()
    assert len(digest) == 64
    assert page_fingerprint(oversized_doc, oversized_doc[0])
