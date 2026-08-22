"""Red-light matrix for Task 13 P3-B — production replay reuse.

One complete bounded slice (plans/task13-p3b-replay-reuse.md): a single
prepare captures the page's decoded content streams ONCE and derives bind,
the plan's stream selection, and the fingerprint's stream portion from that
one coherent read; the preview keystroke loop retains the production
``PageReplay`` (Shape A) in a session-scoped single-slot cache keyed by
(page xref, ordered stream xrefs, decoded-byte digests) and may reuse it
only after lookup-time pull-validation re-proves those digests on freshly
read bytes.  A refused or malformed replay must never become retainable
evidence; the cache must never weaken any existing staleness layer.

Import discipline: names that P3-B introduces are resolved lazily inside
tests (``_evidence()`` / keyword arguments), so the red run reports each
contract's own failure instead of one module-level collection error.

Guard-pin tests (documented in their docstrings) assert behavior that must
SURVIVE the change (e.g. early-gate rejects read zero streams); everything
else fails before implementation.
"""
from __future__ import annotations

import gc
import hashlib
import sys
import weakref
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    BindingFailure,
    bind_source_text,
    page_fingerprint,
    read_page_streams,
)
from model.text_commit.patch import (  # noqa: E402
    PatchSet,
    StalePlanError,
    apply_patchset,
)
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    prepare_plan,
)
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)
from model.text_commit.replay import (  # noqa: E402
    DEFAULT_MAX_REPLAY_BYTES,
    replay_page_streams,
)

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # helv digits share widths: advance-neutral
REPLACEMENT_2 = "Price 2026"  # a second advance-neutral keystroke
DOWNSTREAM = "Downstream line stays"
DOWNSTREAM_REPLACEMENT = "Downstream line stayz"  # helv s == z == 500/1000

# A page over DEFAULT_MAX_REPLAY_BYTES once decoded (compresses tiny in the
# xref, decodes big — the guard measures decoded bytes).
_OVER_BUDGET_STREAM = b"q Q\n" * (DEFAULT_MAX_REPLAY_BYTES // 4 + 16)
# Unterminated literal string: the lexer cannot account for it.
_MALFORMED_STREAM = b"BT /F1 12 Tf 72 700 Td (never closed"


def _evidence():
    """Lazy import of the P3-B module so each test reports its own red."""
    from model.text_commit import evidence

    return evidence


def _capture(doc: fitz.Document, page: fitz.Page):
    from model.text_commit.inspect import capture_page_streams

    return capture_page_streams(doc, page)


# ------------------------------------------------------------------ fixtures


def _tier0_doc(stream: bytes | None = None) -> fitz.Document:
    """Page whose only content is a raw literal-Tj stream (plus a neighbor).

    Same shape as ``test_text_commit_tier0._tier0_doc`` — the canonical
    accepted-path fixture (Helvetica/WinAnsi, advance-neutral digits).
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if stream is None:
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


def _two_stream_doc() -> fitz.Document:
    """The same page split across TWO /Contents streams (state carries)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream_a = b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
    stream_b = b"0 -40 Td (" + DOWNSTREAM.encode() + b") Tj ET"
    xref_a = doc.get_new_xref()
    doc.update_object(xref_a, "<<>>")
    doc.update_stream(xref_a, stream_a)
    xref_b = doc.get_new_xref()
    doc.update_object(xref_b, "<<>>")
    doc.update_stream(xref_b, stream_b)
    doc.xref_set_key(page.xref, "Contents", f"[{xref_a} 0 R {xref_b} 0 R]")
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


def _prepare(
    doc: fitz.Document,
    registry: DocumentFontRegistry,
    *,
    target: str = TARGET,
    replacement: str = REPLACEMENT,
    use_origin: bool = True,
    **kwargs,
):
    page = doc[0]
    origin = tuple(_span(page, target)["origin"]) if use_origin else None
    return prepare_plan(
        doc,
        page,
        target_text=target,
        replacement_text=replacement,
        expected_origin=origin,
        target_bbox=None,
        registry=registry,
        **kwargs,
    )


def _preview_request(
    doc: fitz.Document,
    generation: int,
    *,
    target: str = TARGET,
    replacement: str = REPLACEMENT,
) -> PlanPreviewRequest:
    span = _span(doc[0], target)
    bbox = tuple(span["bbox"])
    clip = (bbox[0] - 4.0, bbox[1] - 4.0, bbox[2] + 4.0, bbox[3] + 4.0)
    return PlanPreviewRequest(
        session_key="sess-p3b",
        generation=generation,
        target_text=target,
        replacement_text=replacement,
        expected_origin=tuple(span["origin"]),
        target_bbox=bbox,
        clip_rect=clip,
        render_scale=2.0,
    )


class _ReplayCounter:
    """Counts every ``replay_page_streams`` execution, wherever it is called.

    Patches the name in each namespace that can invoke a replay on the
    prepare path (inspect's bind fallback and evidence's resolve); the
    wrapper delegates to the real function so results stay production-real.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0

        def counting(streams, **kw):
            self.count += 1
            return replay_page_streams(streams, **kw)

        import model.text_commit.inspect as inspect_mod

        monkeypatch.setattr(inspect_mod, "replay_page_streams", counting)
        try:
            import model.text_commit.evidence as evidence_mod
        except ImportError:
            pass
        else:
            if hasattr(evidence_mod, "replay_page_streams"):
                monkeypatch.setattr(
                    evidence_mod, "replay_page_streams", counting
                )


class _StreamReadCounter:
    """Counts decoded content-stream reads (``xref_stream`` per xref)."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, content_xrefs: set[int]
    ) -> None:
        self.reads: dict[int, int] = {}
        original = fitz.Document.xref_stream
        counter = self

        def counting(self_doc, xref, *args, **kwargs):
            if xref in content_xrefs:
                counter.reads[xref] = counter.reads.get(xref, 0) + 1
            return original(self_doc, xref, *args, **kwargs)

        monkeypatch.setattr(fitz.Document, "xref_stream", counting)


def _mk_snapshot(ev, page_xref: int, streams: list[tuple[int, bytes]]):
    return ev.PageStreamSnapshot(
        page_xref=page_xref,
        streams=tuple(streams),
        key=ev.compute_evidence_key(page_xref, streams),
    )


_TEXT_STREAM = b"BT /F1 12 Tf 72 700 Td (hello) Tj ET"


# ==================================================== A. evidence contracts


def test_evidence_key_composition():
    ev = _evidence()
    streams = [(7, b"aa"), (9, b"bb")]
    key = ev.compute_evidence_key(5, streams)
    assert key.page_xref == 5
    assert key.stream_xrefs == (7, 9)
    assert key.stream_digests == (
        hashlib.sha256(b"aa").hexdigest(),
        hashlib.sha256(b"bb").hexdigest(),
    )
    # Order is part of identity: state carries across the stream sequence.
    assert ev.compute_evidence_key(5, list(reversed(streams))) != key
    # So is the page xref and every digest.
    assert ev.compute_evidence_key(6, streams) != key
    assert ev.compute_evidence_key(5, [(7, b"aa"), (9, b"bc")]) != key


def test_replay_evidence_refuses_refused_replay():
    ev = _evidence()
    streams = [(3, _OVER_BUDGET_STREAM)]
    replay = replay_page_streams(streams)
    assert replay.refusal_reason == RejectReason.CONTENT_STREAM_TOO_LARGE
    with pytest.raises(ValueError):
        ev.ReplayEvidence(key=ev.compute_evidence_key(1, streams), replay=replay)


def test_replay_evidence_refuses_malformed_replay():
    ev = _evidence()
    streams = [(3, _MALFORMED_STREAM)]
    replay = replay_page_streams(streams)
    assert replay.malformed, "fixture must actually be malformed"
    with pytest.raises(ValueError):
        ev.ReplayEvidence(key=ev.compute_evidence_key(1, streams), replay=replay)


def test_resolve_replay_cold_miss_builds_evidence():
    ev = _evidence()
    snapshot = _mk_snapshot(ev, 11, [(3, _TEXT_STREAM)])
    resolved = ev.resolve_replay(snapshot, None)
    assert resolved.from_cache is False
    assert resolved.evidence is not None
    assert resolved.evidence.key == snapshot.key
    assert resolved.evidence.replay is resolved.replay
    assert len(resolved.replay.shows) == 1


def test_resolve_replay_warm_hit_reuses_replay_object(monkeypatch):
    ev = _evidence()
    snapshot = _mk_snapshot(ev, 11, [(3, _TEXT_STREAM)])
    cached = ev.resolve_replay(snapshot, None).evidence
    counter = _ReplayCounter(monkeypatch)
    fresh_snapshot = _mk_snapshot(ev, 11, [(3, _TEXT_STREAM)])
    resolved = ev.resolve_replay(fresh_snapshot, cached)
    assert counter.count == 0, "a validated hit must not replay"
    assert resolved.from_cache is True
    assert resolved.replay is cached.replay
    assert resolved.evidence is cached


def test_resolve_replay_stale_bytes_rebuild(monkeypatch):
    ev = _evidence()
    cached = ev.resolve_replay(
        _mk_snapshot(ev, 11, [(3, _TEXT_STREAM)]), None
    ).evidence
    counter = _ReplayCounter(monkeypatch)
    mutated = _TEXT_STREAM.replace(b"hello", b"world")
    resolved = ev.resolve_replay(_mk_snapshot(ev, 11, [(3, mutated)]), cached)
    assert counter.count == 1
    assert resolved.from_cache is False
    assert resolved.evidence is not None
    assert resolved.evidence.key != cached.key
    assert resolved.replay.shows[0].decoded_bytes == b"world"


def test_resolve_replay_never_trusts_callers_lookup(monkeypatch):
    """A buggy cache handing back wrong-keyed evidence must still miss."""
    ev = _evidence()
    wrong = ev.resolve_replay(
        _mk_snapshot(ev, 11, [(3, b"BT /F1 12 Tf (x) Tj ET")]), None
    ).evidence
    counter = _ReplayCounter(monkeypatch)
    snapshot = _mk_snapshot(ev, 11, [(3, _TEXT_STREAM)])
    resolved = ev.resolve_replay(snapshot, wrong)
    assert counter.count == 1, "wrong-keyed evidence must force a fresh replay"
    assert resolved.from_cache is False
    assert resolved.replay.shows[0].decoded_bytes == b"hello"


def test_resolve_replay_refused_replay_yields_no_evidence():
    ev = _evidence()
    snapshot = _mk_snapshot(ev, 11, [(3, _OVER_BUDGET_STREAM)])
    resolved = ev.resolve_replay(snapshot, None)
    assert resolved.evidence is None
    assert resolved.replay.refusal_reason == RejectReason.CONTENT_STREAM_TOO_LARGE


def test_resolve_replay_malformed_replay_yields_no_evidence():
    ev = _evidence()
    snapshot = _mk_snapshot(ev, 11, [(3, _MALFORMED_STREAM)])
    resolved = ev.resolve_replay(snapshot, None)
    assert resolved.evidence is None
    assert resolved.replay.malformed


def test_cache_single_slot_semantics():
    ev = _evidence()
    e1 = ev.resolve_replay(_mk_snapshot(ev, 11, [(3, _TEXT_STREAM)]), None).evidence
    e2 = ev.resolve_replay(
        _mk_snapshot(ev, 11, [(3, _TEXT_STREAM.replace(b"hello", b"world"))]),
        None,
    ).evidence
    cache = ev.ReplayEvidenceCache()
    assert cache.entry_count == 0
    assert cache.lookup(e1.key) is None
    assert cache.misses == 1
    cache.store(e1)
    assert cache.entry_count == 1
    assert cache.lookup(e1.key) is e1
    assert cache.hits == 1
    cache.store(e2)
    assert cache.entry_count == 1, "single slot: store replaces"
    assert cache.lookup(e1.key) is None
    assert cache.lookup(e2.key) is e2
    assert cache.stores == 2
    cache.clear()
    assert cache.entry_count == 0
    assert cache.lookup(e2.key) is None


# ================================================== B. read-once plumbing


def test_accepted_prepare_reads_each_stream_exactly_once(monkeypatch):
    """The P3-A census's three read sites collapse into one coherent read."""
    doc = _tier0_doc()
    page = doc[0]
    content = set(page.get_contents())
    registry = DocumentFontRegistry(doc)
    counter = _StreamReadCounter(monkeypatch, content)
    plan = _prepare(doc, registry)
    assert isinstance(plan, PreparedEdit), plan
    assert counter.reads == {xref: 1 for xref in content}, counter.reads


def test_two_stream_accepted_prepare_reads_each_stream_exactly_once(monkeypatch):
    doc = _two_stream_doc()
    page = doc[0]
    content = set(page.get_contents())
    assert len(content) == 2
    registry = DocumentFontRegistry(doc)
    counter = _StreamReadCounter(monkeypatch, content)
    plan = _prepare(doc, registry)
    assert isinstance(plan, PreparedEdit), plan
    assert counter.reads == {xref: 1 for xref in content}, counter.reads


def test_early_gate_rejection_reads_no_streams(monkeypatch):
    """GUARD-PIN: cheap early rejects must keep paying zero stream reads."""
    doc = _tier0_doc()
    content = set(doc[0].get_contents())
    registry = DocumentFontRegistry(doc)
    counter = _StreamReadCounter(monkeypatch, content)
    rejection = _prepare(doc, registry, replacement=TARGET, use_origin=False)
    assert isinstance(rejection, PlanRejection)
    assert rejection.reason == RejectReason.NO_CHANGE
    assert counter.reads == {}


def test_prepare_accepts_evidence_cache_and_cold_result_is_equal():
    ev = _evidence()
    doc = _tier0_doc()
    registry = DocumentFontRegistry(doc)
    plan_uncached = _prepare(doc, registry)
    cache = ev.ReplayEvidenceCache()
    plan_cached = _prepare(doc, registry, evidence_cache=cache)
    assert isinstance(plan_uncached, PreparedEdit)
    assert plan_cached == plan_uncached
    assert cache.entry_count == 1


def test_warm_prepared_edit_equals_cold(monkeypatch):
    ev = _evidence()
    doc = _tier0_doc()
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    cold = _prepare(doc, registry, evidence_cache=cache)
    assert isinstance(cold, PreparedEdit)
    counter = _ReplayCounter(monkeypatch)
    warm = _prepare(doc, registry, evidence_cache=cache)
    assert counter.count == 0, "second keystroke on unchanged page must not replay"
    assert warm == cold


def test_page_fingerprint_streams_kwarg_equivalence():
    doc = _tier0_doc()
    page = doc[0]
    fresh = page_fingerprint(doc, page)
    streams = read_page_streams(doc, page)
    assert page_fingerprint(doc, page, streams=streams) == fresh
    tampered = [(xref, data + b" ") for xref, data in streams]
    assert page_fingerprint(doc, page, streams=tampered) != fresh


def test_bind_source_text_resolved_equivalence():
    ev = _evidence()
    doc = _tier0_doc()
    page = doc[0]
    direct = bind_source_text(
        doc, page, target_text=TARGET, expected_origin=None
    )
    resolved = ev.resolve_replay(_capture(doc, page), None)
    via_resolved = bind_source_text(
        doc, page, target_text=TARGET, expected_origin=None, resolved=resolved
    )
    assert not isinstance(direct, BindingFailure), direct
    assert via_resolved == direct


def test_bind_source_text_resolved_refusal_verbatim():
    ev = _evidence()
    doc = _tier0_doc(stream=_OVER_BUDGET_STREAM)
    page = doc[0]
    resolved = ev.resolve_replay(_capture(doc, page), None)
    failure = bind_source_text(
        doc, page, target_text=TARGET, expected_origin=None, resolved=resolved
    )
    assert isinstance(failure, BindingFailure)
    assert failure.reason == RejectReason.CONTENT_STREAM_TOO_LARGE


# ============================================ C. reuse + invalidation matrix


def _warm_cache(doc: fitz.Document, registry: DocumentFontRegistry, cache):
    plan = _prepare(doc, registry, evidence_cache=cache)
    assert isinstance(plan, PreparedEdit), plan
    assert cache.entry_count == 1
    return plan


def test_missed_hook_mutation_rebuilds_never_reuses(monkeypatch):
    """Mutation class with NO signal (direct update_stream): digests decide."""
    ev = _evidence()
    doc = _tier0_doc()
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    _warm_cache(doc, registry, cache)
    old_key = cache.lookup_any().key
    content_xref = doc[0].get_contents()[0]
    mutated = (
        b"BT /F1 12 Tf 72 700 Td (Other text) Tj "
        b"0 -40 Td (" + DOWNSTREAM.encode() + b") Tj ET"
    )
    doc.update_stream(content_xref, mutated)  # no dirty hook fires
    counter = _ReplayCounter(monkeypatch)
    result = _prepare(doc, registry, use_origin=False, evidence_cache=cache)
    assert counter.count == 1, "stale evidence must be rebuilt, not reused"
    assert isinstance(result, PlanRejection)
    assert result.reason == RejectReason.NO_MATCH
    assert cache.entry_count == 1
    assert cache.lookup_any().key != old_key


def test_stream_xref_replaced_same_bytes_misses(monkeypatch):
    """Identity is part of the key: same bytes at a NEW xref must miss."""
    ev = _evidence()
    doc = _tier0_doc()
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    _warm_cache(doc, registry, cache)
    page = doc[0]
    old_xref = page.get_contents()[0]
    stream_bytes = doc.xref_stream(old_xref)
    new_xref = doc.get_new_xref()
    doc.update_object(new_xref, "<<>>")
    doc.update_stream(new_xref, stream_bytes)
    doc.xref_set_key(page.xref, "Contents", f"{new_xref} 0 R")
    counter = _ReplayCounter(monkeypatch)
    plan = _prepare(doc, registry, evidence_cache=cache)
    assert counter.count == 1
    assert isinstance(plan, PreparedEdit), plan
    assert plan.stream_xref == new_xref


def test_streams_reordered_misses(monkeypatch):
    ev = _evidence()
    doc = _two_stream_doc()
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    _warm_cache(doc, registry, cache)
    page = doc[0]
    xref_a, xref_b = page.get_contents()
    doc.xref_set_key(page.xref, "Contents", f"[{xref_b} 0 R {xref_a} 0 R]")
    counter = _ReplayCounter(monkeypatch)
    _prepare(doc, registry, use_origin=False, evidence_cache=cache)
    assert counter.count == 1, "reordered /Contents must miss"


def test_stream_added_misses(monkeypatch):
    ev = _evidence()
    doc = _two_stream_doc()
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    _warm_cache(doc, registry, cache)
    page = doc[0]
    xref_a, xref_b = page.get_contents()
    extra = doc.get_new_xref()
    doc.update_object(extra, "<<>>")
    doc.update_stream(extra, b" ")
    doc.xref_set_key(
        page.xref, "Contents", f"[{xref_a} 0 R {xref_b} 0 R {extra} 0 R]"
    )
    counter = _ReplayCounter(monkeypatch)
    _prepare(doc, registry, evidence_cache=cache)
    assert counter.count == 1, "an added stream must miss"


def test_stream_removed_misses(monkeypatch):
    ev = _evidence()
    doc = _two_stream_doc()
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    _warm_cache(doc, registry, cache)
    page = doc[0]
    xref_a, _xref_b = page.get_contents()
    doc.xref_set_key(page.xref, "Contents", f"{xref_a} 0 R")
    counter = _ReplayCounter(monkeypatch)
    _prepare(doc, registry, use_origin=False, evidence_cache=cache)
    assert counter.count == 1, "a removed stream must miss"


def test_rotate_mutation_hits_replay_but_fingerprint_stays_fresh(monkeypatch):
    """Non-replay dependency: /Rotate must NOT invalidate replay evidence,
    and must still invalidate everything fingerprint-derived."""
    ev = _evidence()
    doc = _tier0_doc()
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    plan_before = _prepare(doc, registry, use_origin=False, evidence_cache=cache)
    assert isinstance(plan_before, PreparedEdit)
    doc.xref_set_key(doc[0].xref, "Rotate", "90")
    counter = _ReplayCounter(monkeypatch)
    result = _prepare(doc, registry, use_origin=False, evidence_cache=cache)
    assert counter.count == 0, "/Rotate does not change content streams: HIT"
    fresh_fp = page_fingerprint(doc, doc[0])
    assert fresh_fp != plan_before.page_fingerprint
    if isinstance(result, PreparedEdit):
        assert result.page_fingerprint == fresh_fp
        assert result.token != plan_before.token


def test_annotation_mutation_hits_replay_but_fingerprint_stays_fresh(monkeypatch):
    ev = _evidence()
    doc = _tier0_doc()
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    plan_before = _prepare(doc, registry, evidence_cache=cache)
    assert isinstance(plan_before, PreparedEdit)
    doc[0].add_text_annot((30, 30), "note")
    counter = _ReplayCounter(monkeypatch)
    result = _prepare(doc, registry, evidence_cache=cache)
    assert counter.count == 0, "annotations are not content streams: HIT"
    assert isinstance(result, PreparedEdit), result
    fresh_fp = page_fingerprint(doc, doc[0])
    assert result.page_fingerprint == fresh_fp
    assert result.page_fingerprint != plan_before.page_fingerprint
    assert result.token != plan_before.token


def test_mutation_after_lookup_still_stale_at_apply():
    """The cache must not replace the apply-time staleness layer."""
    ev = _evidence()
    doc = _tier0_doc()
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    plan = _warm_cache(doc, registry, cache)
    content_xref = doc[0].get_contents()[0]
    doc.update_stream(content_xref, doc.xref_stream(content_xref) + b" ")
    with pytest.raises(StalePlanError):
        apply_patchset(
            doc,
            doc[0],
            PatchSet(
                page_xref=plan.page_xref,
                replacements=(plan.replacement,),
                expected_page_fingerprint=plan.page_fingerprint,
            ),
        )


def test_over_budget_page_caches_nothing():
    ev = _evidence()
    doc = _tier0_doc(stream=_OVER_BUDGET_STREAM)
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    first = _prepare(doc, registry, use_origin=False, evidence_cache=cache)
    assert isinstance(first, PlanRejection)
    assert first.reason == RejectReason.CONTENT_STREAM_TOO_LARGE
    assert cache.entry_count == 0, "a refusal must never become warm evidence"
    second = _prepare(doc, registry, use_origin=False, evidence_cache=cache)
    assert isinstance(second, PlanRejection)
    assert second.reason == RejectReason.CONTENT_STREAM_TOO_LARGE


def test_malformed_page_caches_nothing():
    ev = _evidence()
    doc = _tier0_doc(stream=_MALFORMED_STREAM)
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    result = _prepare(doc, registry, use_origin=False, evidence_cache=cache)
    assert isinstance(result, PlanRejection)
    assert result.reason == RejectReason.MALFORMED_STREAM
    assert cache.entry_count == 0


def test_engine_prepare_stays_ephemeral(monkeypatch):
    """GUARD-PIN: TieredCommitEngine.prepare gets no cache in this slice."""
    doc = _tier0_doc()
    engine = TieredCommitEngine(doc)
    page = doc[0]
    span = _span(page, TARGET)
    counter = _ReplayCounter(monkeypatch)
    kwargs = dict(
        target_text=TARGET,
        replacement_text=REPLACEMENT,
        expected_origin=tuple(span["origin"]),
    )
    first = engine.prepare(page, **kwargs)
    assert isinstance(first, PreparedEdit), first
    after_first = counter.count
    assert after_first >= 1
    second = engine.prepare(page, **kwargs)
    assert isinstance(second, PreparedEdit), second
    assert counter.count == 2 * after_first, "engine.prepare must not reuse"


# ============================================================== D. memory


def test_repeated_keystrokes_keep_single_entry():
    ev = _evidence()
    doc = _tier0_doc()
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    for i in range(25):
        replacement = f"Price 20{i % 10}5"
        result = _prepare(doc, registry, replacement=replacement, evidence_cache=cache)
        assert isinstance(result, PreparedEdit), result
        assert cache.entry_count == 1
    assert cache.stores == 1, "an unchanged page generation stores once"
    assert cache.hits == 24


def test_replaced_replay_is_collectible(monkeypatch):
    ev = _evidence()
    doc = _tier0_doc()
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    _warm_cache(doc, registry, cache)
    ref = weakref.ref(cache.lookup_any().replay)
    content_xref = doc[0].get_contents()[0]
    doc.update_stream(content_xref, doc.xref_stream(content_xref) + b" ")
    _prepare(doc, registry, evidence_cache=cache)
    gc.collect()
    assert ref() is None, "replaced PageReplay must not accumulate"


def test_cache_clear_releases_replay():
    ev = _evidence()
    doc = _tier0_doc()
    registry = DocumentFontRegistry(doc)
    cache = ev.ReplayEvidenceCache()
    _warm_cache(doc, registry, cache)
    ref = weakref.ref(cache.lookup_any().replay)
    cache.clear()
    gc.collect()
    assert ref() is None


# ============================================ E. preview renderer integration


def test_preview_warm_keystroke_replays_zero_times(monkeypatch):
    doc = _tier0_doc()
    session = open_preview_session(doc, 0, "sess-p3b")
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    try:
        cold = renderer.render(_preview_request(doc, 1))
        assert cold.plan_token, cold.reject_reason
        counter = _ReplayCounter(monkeypatch)
        warm = renderer.render(
            _preview_request(doc, 2, replacement=REPLACEMENT_2)
        )
        assert warm.plan_token, warm.reject_reason
        assert counter.count == 0, (
            "second keystroke must reuse the session's PageReplay "
            "(also proves splice+revert restores digest-identical bytes)"
        )
        assert warm.plan_token != cold.plan_token
    finally:
        renderer.close()


def test_preview_second_target_same_page_hits(monkeypatch):
    doc = _tier0_doc()
    session = open_preview_session(doc, 0, "sess-p3b")
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    try:
        cold = renderer.render(_preview_request(doc, 1))
        assert cold.plan_token, cold.reject_reason
        counter = _ReplayCounter(monkeypatch)
        renderer.render(
            _preview_request(
                doc, 2, target=DOWNSTREAM, replacement=DOWNSTREAM_REPLACEMENT
            )
        )
        assert counter.count == 0, "same page generation: any target reuses"
    finally:
        renderer.close()


def test_preview_warm_token_equals_fresh_renderer_cold_token():
    """GUARD-PIN: a warm result must be indistinguishable from a cold
    re-render.  Green before implementation too (trivially cold == cold);
    after the slice the left side becomes a genuine warm hit and the
    equality is the reuse-correctness invariant."""
    doc = _tier0_doc()
    session = open_preview_session(doc, 0, "sess-p3b")
    assert session is not None
    warm_renderer = PlanPreviewRenderer(session)
    cold_renderer = PlanPreviewRenderer(session)
    try:
        warm_renderer.render(_preview_request(doc, 1))
        warm = warm_renderer.render(_preview_request(doc, 2))
        cold = cold_renderer.render(_preview_request(doc, 2))
        assert warm.plan_token
        assert warm.plan_token == cold.plan_token
        assert warm.png_bytes == cold.png_bytes
        assert warm.prepared == cold.prepared
    finally:
        warm_renderer.close()
        cold_renderer.close()


def test_preview_close_releases_retained_replay():
    ev = _evidence()
    doc = _tier0_doc()
    session = open_preview_session(doc, 0, "sess-p3b")
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    result = renderer.render(_preview_request(doc, 1))
    assert result.plan_token, result.reject_reason
    cache = renderer._evidence_cache
    assert isinstance(cache, ev.ReplayEvidenceCache)
    entry = cache.lookup_any()
    assert entry is not None, "an accepted preview must retain evidence"
    ref = weakref.ref(entry.replay)
    del entry
    renderer.close()
    gc.collect()
    assert cache.entry_count == 0
    assert ref() is None, "session close must release the retained replay"
