#!/usr/bin/env python3
"""Headless runtime + memory baseline for the text-commit engine.

Pre-Task-11 baseline (``TODOS.md``): measures p50/p95/p99 for cold and warm
``prepare``, a preview-session open plus one generation, the raster/
verification render cost (the V0 path), ``commit`` plus revert, undo/redo via
the reversal patchset pair, peak plus resident memory around the dense-file
prepare, and memory growth after repeated preview-session teardown. Budgets
are derived from these numbers LATER (Task 12) -- this script only measures.

Model-layer only: no Qt import anywhere in this module, matching the layer
rule that the preview/commit engine stays reachable headlessly.

**Corpus finding** (see ``corpus_findings`` in the emitted JSON): computed at
run time by ``_corpus_findings()`` calling
``audit_tier_coverage.audit_document()`` (read-only) against all six
``test_files/*.pdf`` fixtures -- never a fixed claim baked into this
docstring or the JSON, so it cannot go stale as ``model/text_commit/
plan.py``'s Tier 0 gates evolve. The active gate set is labeled inline via
``_TIER0_GATES_ACTIVE``: as of ``post-D1`` (hex-string ``Tj`` and
uniform-positive-scale text matrices admitted, not just literal ``Tj`` +
pure translation), ``test-large-file.pdf`` has 5,853 ``tier0_eligible``
shows out of 35,844; the other five fixtures remain at 0.
**Superseded 2026-08-01** -- an earlier revision of this paragraph asserted
``tier0_eligible_count == 0`` across all six fixtures and that literally
all 35,844 shows on ``test-large-file.pdf`` failed
``UNSUPPORTED_TEXT_STATE`` because the producer bakes font-size scale into
an absolute ``Tm`` operand instead of ``Tf`` size + ``Td`` translation;
both were true only pre-D1. Kept here for provenance, not as current fact.

Real-corpus prepare/preview numbers below still measure a REJECT path --
no disk-loaded fixture's *first non-empty show* (what ``_pick_real_target``
binds to) is itself Tier-0-eligible -- which still exercises the expensive
per-page replay/bind cost that dominates real keystrokes. The specific gate
that fires is recorded per-call in ``reject_reason_cold``/
``reject_reason_warm``/``reject_reasons_seen``, not asserted here: on
``test-large-file.pdf``'s densest page the picked target is itself one
element of a ``TJ`` array (never a single ``Tj``), so ``prepare()`` rejects
with ``NOT_SINGLE_LITERAL_TJ`` -- a structural gate ``prepare_tier0_plan``
has always checked *before* the text-state gate, unaffected by D1's
hex/uniform-scale relaxation, so this was already the real per-call reason
pre-D1 too. The superseded ``UNSUPPORTED_TEXT_STATE`` claim above described
``audit_tier_coverage.py``'s corpus-wide aggregate classification (which
prioritizes differently -- see its ``_classify_show``), not what this one
benchmarked ``prepare()`` call on this one target actually returns. ACCEPT-
path numbers (commit, isolated verification, undo/redo) use one minimal
literal-``Tj`` target injected into a throwaway scratch copy: a fresh
synthetic single page for the "small" tier, and one appended content stream
on the *actual* densest page of ``test-large-file.pdf`` for the "dense"
tier. Every accept-path number is labeled ``synthetic`` in the JSON --
never presented as if it were measured on unmodified corpus content.

**Load-bearing PyMuPDF finding, discovered while building the accept-path
fixture** (see ``pitfalls_found`` in the JSON -- scoped to what was actually
measured, not generalized past it): on ``test_files/test-large-file.pdf``
(PyMuPDF 1.27.1), all five font objects on the target page have their
dictionary keys re-ordered (same keys, same length, different order --
first divergence at char 6: ``/BaseFont`` vs ``/Type``) by the FIRST
``tobytes(encryption=PDF_ENCRYPT_KEEP)`` round trip -- confirmed idempotent
on every round trip after that first one. Because
``page_fingerprint`` hashes each font dependency object's ``xref_object()``
string verbatim, and ``TieredCommitEngine.prepare()``'s scratch-first
self-consistency check (``page_fingerprint`` -> ``_build_scratch_copy`` ->
``page_fingerprint`` again) performs exactly that first round trip
internally, every accept-path candidate on THIS file fails with
``VERIFICATION_FAILED`` / "page fingerprint changed since the plan was
prepared" on the very first ``prepare()`` attempt -- even a genuinely
Tier-0-eligible one. This was tested on one disk-loaded file from one
producer; whether every disk-loaded PDF re-orders this way (versus one
whose on-disk key order already matches PyMuPDF's canonical layout) is
untested and NOT claimed here. It is consistent with why the existing
synthetic-fixture unit tests (built via ``fitz.open()`` + ``new_page()``,
never loaded from disk, so there is no pre-existing on-disk order to
disagree with) never observed it. Real-corpus REJECT-path numbers in this
report are unaffected: ``prepare()`` returns before ``_build_scratch_copy``
runs on rejection. This benchmark works around the mismatch for its own
ACCEPT-path fixture by canonicalizing with one round trip before ever
calling ``prepare()`` -- see ``_canonicalize_once``.
**Superseded 2026-08-01** -- the production fix in ``model/text_commit/inspect.py``
now resolves the dictionary-key reordering issue by using order-independent
digest calculation in ``_canonical_object_digest``, replacing the raw
``xref_object()`` strings with structured key/value hashing. The workaround
in ``_canonicalize_once`` below is no longer required for correctness but
is retained as a harmless no-op for continuity with prior benchmark runs.

Never prints, logs, returns, or writes extracted document text anywhere --
only counts, booleans, reason codes, timings, and byte lengths. PlanRejection
detail strings (which interpolate font/basefont names) are never surfaced;
only the stable ``reason`` code is recorded.

Usage::

    "<venv>/python.exe" scripts/benchmark_text_commit_baseline.py [--iterations N] [--out PATH]
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import CommitStatus  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.inspect import page_fingerprint, read_page_streams  # noqa: E402
from model.text_commit.patch import apply_patchset, build_reversal_patchset  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)
from model.text_commit.replay import replay_page_streams  # noqa: E402
from model.text_commit.verify import (  # noqa: E402
    VerificationFailure,
    capture_page_state,
    verify_tier0_commit,
)
from scripts.audit_tier_coverage import audit_document  # noqa: E402

logger = logging.getLogger(__name__)

try:
    import psutil
except ImportError:
    psutil = None

_SMALL_PDF = ROOT / "test_files" / "1.pdf"
_DENSE_PDF = ROOT / "test_files" / "test-large-file.pdf"
_OTHER_CORPUS_PDFS = (
    ROOT / "test_files" / "test-colored-background.pdf",
    ROOT / "test_files" / "test-complexed-layout.pdf",
    ROOT / "test_files" / "test-horizontal-texts.pdf",
    ROOT / "test_files" / "test-vertical-texts.pdf",
)
_ALL_CORPUS_PDFS = (_SMALL_PDF, *_OTHER_CORPUS_PDFS, _DENSE_PDF)
_TIER0_GATES_ACTIVE = (
    "post-D1 (landed 2026-08-01): model/text_commit/plan.py Tier 0 admits "
    "hex-string Tj (not just literal) and uniform-positive-scale text "
    "matrices (not just pure translation); tier1_candidate additionally "
    "reflects the Task 10d /Widths-based gates and the Task 10e "
    "glyph-availability proxy -- see scripts/audit_tier_coverage.py"
)
_SLOW_OP_SECONDS = 2.0
_SLOW_OP_ITERATIONS = 5
_INJECT_TARGET = "BENCHXQ"
_INJECT_REPLACEMENT = "QXHCNEB"  # a permutation: same multiset, equal advance


# --------------------------------------------------------------- percentiles


def _percentiles(samples: list[float]) -> dict[str, Any]:
    if not samples:
        return {"n": 0, "p50": None, "p95": None, "p99": None, "mean": None}
    ordered = sorted(samples)
    n = len(ordered)

    def _pct(p: float) -> float:
        idx = min(n - 1, int(round(p / 100.0 * (n - 1))))
        return ordered[idx]

    return {
        "n": n,
        "p50": _pct(50.0),
        "p95": _pct(95.0),
        "p99": _pct(99.0),
        "mean": statistics.fmean(ordered),
        "min": ordered[0],
        "max": ordered[-1],
    }


def _adaptive_run(
    fn: Any, requested_iterations: int
) -> tuple[list[float], list[Any], dict[str, Any]]:
    """Run ``fn()`` up to ``requested_iterations`` times, timing each call.

    If the first sample exceeds ``_SLOW_OP_SECONDS``, the run is capped at
    ``_SLOW_OP_ITERATIONS`` total and that decision is recorded honestly
    rather than silently truncating the sample.
    """
    durations: list[float] = []
    results: list[Any] = []
    cap = requested_iterations
    dropped = False
    for i in range(requested_iterations):
        t0 = time.perf_counter()
        result = fn()
        t1 = time.perf_counter()
        durations.append(t1 - t0)
        results.append(result)
        if i == 0 and durations[0] > _SLOW_OP_SECONDS and cap > _SLOW_OP_ITERATIONS:
            cap = _SLOW_OP_ITERATIONS
            dropped = True
        if len(durations) >= cap:
            break
    meta = {
        "iterations_requested": requested_iterations,
        "iterations_run": len(durations),
        "dropped_to_slow_op_cap": dropped,
        "slow_op_threshold_seconds": _SLOW_OP_SECONDS,
    }
    return durations, results, meta


# ------------------------------------------------------------- doc plumbing


def _canonicalize_once(doc: fitz.Document) -> bytes:
    """One ``tobytes(encryption=KEEP)`` round trip.

    Stabilizes PDF-dictionary key ordering for objects loaded from disk (see
    module docstring) so a *second* round trip -- the one
    ``TieredCommitEngine.prepare()`` performs internally for its scratch-
    first proof -- reproduces the identical byte layout and the page
    fingerprint comparison passes.

    **Superseded 2026-08-01** -- this workaround is no longer required for
    correctness. The production fix in ``model/text_commit/inspect.py``
    (``_canonical_object_digest``) now handles the dictionary-key reordering
    issue directly in the fingerprint calculation. This function is retained
    as a harmless no-op for continuity with prior benchmark runs.
    """
    return doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)


def _page_show_counts(doc: fitz.Document) -> list[int]:
    counts: list[int] = []
    for i in range(doc.page_count):
        page = doc[i]
        streams = read_page_streams(doc, page)
        replay = replay_page_streams(streams)
        counts.append(len(replay.shows))
    return counts


def _densest_page(doc: fitz.Document) -> tuple[int, dict[str, Any]]:
    counts = _page_show_counts(doc)
    max_idx = max(range(len(counts)), key=lambda i: counts[i])
    ordered = sorted(counts)
    n = len(ordered)
    p50 = ordered[n // 2]
    stats = {
        "page_count": doc.page_count,
        "shows_total": sum(counts),
        "densest_page_index": max_idx,
        "densest_page_shows": counts[max_idx],
        "p50_shows_per_page": p50,
    }
    return max_idx, stats


def _corpus_findings(pdf_paths: tuple[Path, ...]) -> dict[str, Any]:
    """Data-driven Tier 0 / Tier 1 / legacy show-op counts for the corpus.

    Calls ``audit_tier_coverage.audit_document`` (read-only -- no scratch
    commit, no ``prepare_tier0_plan`` call) against each fixture and sums
    its per-page counts, so this tracks whatever
    ``model/text_commit/plan.py``'s Tier 0 gates currently accept instead
    of asserting a fixed historical claim that gate changes silently
    invalidate. Counts only: no document text, no reject-reason detail
    strings, only the same stable counters ``audit_tier_coverage.py``'s own
    CLI prints.
    """
    per_file: dict[str, dict[str, int]] = {}
    agg = {"shows_total": 0, "tier0_eligible": 0, "tier1_candidate": 0, "legacy_only": 0}
    for pdf_path in pdf_paths:
        doc = fitz.open(str(pdf_path))
        try:
            rows = audit_document(doc)
        finally:
            doc.close()
        file_counts = {
            "shows_total": sum(int(r["shows_total"]) for r in rows),
            "tier0_eligible": sum(int(r["tier0_eligible"]) for r in rows),
            "tier1_candidate": sum(int(r["tier1_candidate"]) for r in rows),
            "legacy_only": sum(int(r["legacy_only"]) for r in rows),
        }
        per_file[pdf_path.name] = file_counts
        for key in agg:
            agg[key] += file_counts[key]

    return {
        "gates_active": _TIER0_GATES_ACTIVE,
        "per_file": per_file,
        "aggregate": agg,
    }


def _origin_in_page_space(page: fitz.Page, show: Any) -> tuple[float, float]:
    point = fitz.Point(*show.origin_user) * page.transformation_matrix
    return (point.x, point.y)


def _pick_real_target(
    doc: fitz.Document, page: fitz.Page
) -> tuple[str, tuple[float, float]] | None:
    """First non-empty show on ``page``, bound by its own origin.

    Never returns text that fails to round-trip through latin-1 (the
    show's ``decoded_bytes`` always does, by construction of the replay).
    """
    streams = read_page_streams(doc, page)
    replay = replay_page_streams(streams)
    for show in replay.shows:
        if not show.decoded_bytes:
            continue
        text = show.decoded_bytes.decode("latin-1")
        if not text.strip():
            continue
        return text, _origin_in_page_space(page, show)
    return None


# ------------------------------------------------------- accept-path fixtures


def _synthetic_minimal_fixture() -> bytes:
    """A brand-new single-page doc with one literal-Tj target (Tier 0 shape).

    Mirrors ``test_scripts/test_text_commit_tier0.py``'s ``_tier0_doc()``.
    Never loaded from disk, so the key-reordering pitfall above does not
    apply -- canonicalized anyway for uniformity with the injected fixture.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + _INJECT_TARGET.encode() + b") Tj ET"
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
    canon = _canonicalize_once(doc)
    doc.close()
    return canon


def _inject_literal_tj_fixture(source_path: Path, page_index: int) -> bytes:
    """Append one literal-Tj target to a real page's own content streams.

    Adds a new font resource and a new content-stream entry -- never
    mutates any existing stream or resource -- then canonicalizes once so
    the engine's own internal scratch round trip is idempotent against it.
    """
    doc = fitz.open(str(source_path))
    page = doc[page_index]

    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    _, font_dict = doc.xref_get_key(page.xref, "Resources/Font")
    new_font_dict = font_dict[:-2] + f"/FBench {font_xref} 0 R>>"
    doc.xref_set_key(page.xref, "Resources/Font", new_font_dict)

    stream_xref = doc.get_new_xref()
    doc.update_object(stream_xref, "<<>>")
    injected = (
        b"BT /FBench 12 Tf 36 700 Td (" + _INJECT_TARGET.encode() + b") Tj ET"
    )
    doc.update_stream(stream_xref, injected)
    existing = page.get_contents()
    refs = " ".join(f"{x} 0 R" for x in (*existing, stream_xref))
    doc.xref_set_key(page.xref, "Contents", f"[{refs}]")

    canon = _canonicalize_once(doc)
    doc.close()
    return canon


def _fixture_target_origin(
    fixture_bytes: bytes, page_index: int
) -> tuple[float, float]:
    """Locate the injected target's own show op and return its origin.

    The injected target is the only show whose text we control; find it by
    exact match rather than assuming it is first (small fixture: it is;
    dense fixture: the injected show is appended last).
    """
    doc = fitz.open("pdf", fixture_bytes)
    try:
        page = doc[page_index]
        streams = read_page_streams(doc, page)
        replay = replay_page_streams(streams)
        target_bytes = _INJECT_TARGET.encode("latin-1")
        for show in replay.shows:
            if show.decoded_bytes == target_bytes:
                return _origin_in_page_space(page, show)
        raise AssertionError("injected accept-path target not found in fixture")
    finally:
        doc.close()


# ------------------------------------------------------------------ real-corpus


def _real_corpus_prepare(pdf_path: Path, page_index: int, iterations: int) -> dict[str, Any]:
    doc = fitz.open(str(pdf_path))
    page = doc[page_index]
    picked = _pick_real_target(doc, page)
    doc.close()
    if picked is None:
        return {"not_measurable": "page has no show operators to bind a target from"}
    text, origin = picked

    def _cold_once() -> str:
        d = fitz.open(str(pdf_path))
        try:
            p = d[page_index]
            engine = TieredCommitEngine(d)
            result = engine.prepare(
                p, target_text=text, replacement_text=text + "!",
                expected_origin=origin, target_bbox=None,
            )
            return result.reason if isinstance(result, PlanRejection) else "accepted"
        finally:
            d.close()

    cold_durations, cold_reasons, cold_meta = _adaptive_run(_cold_once, iterations)

    warm_doc = fitz.open(str(pdf_path))
    warm_page = warm_doc[page_index]
    warm_engine = TieredCommitEngine(warm_doc)

    def _warm_once() -> str:
        result = warm_engine.prepare(
            warm_page, target_text=text, replacement_text=text + "!",
            expected_origin=origin, target_bbox=None,
        )
        return result.reason if isinstance(result, PlanRejection) else "accepted"

    warm_durations, warm_reasons, warm_meta = _adaptive_run(_warm_once, iterations)
    warm_doc.close()

    return {
        "target_page_index": page_index,
        "reject_reason_cold": sorted(set(cold_reasons)),
        "reject_reason_warm": sorted(set(warm_reasons)),
        "cold_prepare_seconds": {**_percentiles(cold_durations), **cold_meta},
        "warm_prepare_seconds": {**_percentiles(warm_durations), **warm_meta},
    }


def _real_corpus_preview(pdf_path: Path, page_index: int, iterations: int) -> dict[str, Any]:
    doc = fitz.open(str(pdf_path))
    page = doc[page_index]
    picked = _pick_real_target(doc, page)
    if picked is None:
        doc.close()
        return {"not_measurable": "page has no show operators to bind a target from"}
    text, origin = picked
    rect = tuple(page.rect)

    t0 = time.perf_counter()
    session = open_preview_session(doc, page_index, "bench-reject-session")
    t1 = time.perf_counter()
    open_session_seconds = t1 - t0
    snapshot_bytes_len = len(session.snapshot_bytes) if session is not None else None
    doc.close()
    if session is None:
        return {"not_measurable": "encrypted document could not be snapshotted"}

    renderer = PlanPreviewRenderer(session)
    reasons: set[str] = set()
    generation_counter = {"value": 0}

    def _generation_once() -> None:
        req = PlanPreviewRequest(
            session_key="bench-reject-session", generation=generation_counter["value"],
            target_text=text, replacement_text=text + "!", expected_origin=origin,
            target_bbox=None, clip_rect=rect, render_scale=1.0,
        )
        generation_counter["value"] += 1
        result = renderer.render(req)
        if result.reject_reason is not None:
            reasons.add(result.reject_reason)

    durations, _results, meta = _adaptive_run(_generation_once, iterations)
    renderer.close()

    return {
        "target_page_index": page_index,
        "open_preview_session_seconds": open_session_seconds,
        "session_snapshot_bytes": snapshot_bytes_len,
        "reject_reasons_seen": sorted(reasons),
        "preview_generation_render_headless_seconds": {**_percentiles(durations), **meta},
        "note": (
            "headless model-layer render() only; excludes the Qt preview "
            "worker's thread-hop, debounce, and QImage conversion -- a "
            "lower bound on true key-to-preview latency, not the full path"
        ),
    }


# ------------------------------------------------------------------ accept-path


def _accept_path_metrics(
    fixture_bytes: bytes, page_index: int, label: str, iterations: int
) -> dict[str, Any]:
    origin = _fixture_target_origin(fixture_bytes, page_index)

    doc = fitz.open("pdf", fixture_bytes)
    page = doc[page_index]
    engine = TieredCommitEngine(doc)

    # --- cold prepare (fresh open each iteration) ---
    def _cold_prepare_once() -> str:
        d = fitz.open("pdf", fixture_bytes)
        try:
            p = d[page_index]
            e = TieredCommitEngine(d)
            result = e.prepare(
                p, target_text=_INJECT_TARGET, replacement_text=_INJECT_REPLACEMENT,
                expected_origin=origin, target_bbox=None,
            )
            return type(result).__name__
        finally:
            d.close()

    cold_durations, cold_types, cold_meta = _adaptive_run(_cold_prepare_once, iterations)

    # --- warm prepare (repeat on the same open session; never mutates live doc) ---
    def _warm_prepare_once() -> str:
        result = engine.prepare(
            page, target_text=_INJECT_TARGET, replacement_text=_INJECT_REPLACEMENT,
            expected_origin=origin, target_bbox=None,
        )
        return type(result).__name__

    warm_durations, warm_types, warm_meta = _adaptive_run(_warm_prepare_once, iterations)

    # --- commit / isolated raster-verify / revert / undo / redo loop ---
    commit_durations: list[float] = []
    verify_isolated_durations: list[float] = []
    undo_durations: list[float] = []
    redo_durations: list[float] = []
    commit_iterations_requested = iterations
    commit_iterations_run = 0
    dropped_commit = False
    for i in range(commit_iterations_requested):
        pre_streams = read_page_streams(doc, page)
        pre_fingerprint = page_fingerprint(doc, page)
        prepared = engine.prepare(
            page, target_text=_INJECT_TARGET, replacement_text=_INJECT_REPLACEMENT,
            expected_origin=origin, target_bbox=None,
        )
        if not isinstance(prepared, PreparedEdit):
            raise AssertionError(
                f"accept-path fixture {label} unexpectedly rejected: {prepared.reason}"
            )

        t0 = time.perf_counter()
        outcome = engine.commit(prepared)
        t1 = time.perf_counter()
        if outcome.status != CommitStatus.COMMITTED:
            raise AssertionError(f"accept-path fixture {label} commit did not succeed")
        commit_durations.append(t1 - t0)

        # Self-compare raster/verification cost: re-run V0's capture+compare
        # on the now-stable, just-committed page against itself (no further
        # mutation). Every row matches, so the per-pixel diff loop in
        # _first_diff_outside_halo never runs -- this isolates the fixed
        # 2x-raster + V0e-reopen cost, not real pixel-diff work (see the
        # "raster_verification_selfcompare_note" this produces below).
        t0 = time.perf_counter()
        self_state = capture_page_state(doc, page, prepared)
        result = verify_tier0_commit(doc, page, prepared, self_state)
        t1 = time.perf_counter()
        if isinstance(result, VerificationFailure):
            raise AssertionError(
                f"accept-path fixture {label} self-verification unexpectedly failed"
            )
        verify_isolated_durations.append(t1 - t0)

        reversal = build_reversal_patchset(doc, page, pre_streams, pre_fingerprint)
        if reversal is None:
            raise AssertionError(
                f"accept-path fixture {label} produced a multi-stream diff; "
                "reversal patchset unavailable"
            )
        forward_patchset, inverse_patchset = reversal

        t0 = time.perf_counter()
        apply_patchset(doc, page, inverse_patchset)  # undo
        t1 = time.perf_counter()
        undo_durations.append(t1 - t0)

        t0 = time.perf_counter()
        apply_patchset(doc, page, forward_patchset)  # redo
        t1 = time.perf_counter()
        redo_durations.append(t1 - t0)

        apply_patchset(doc, page, inverse_patchset)  # revert to pre-commit state

        commit_iterations_run += 1
        if (
            i == 0
            and commit_durations[0] > _SLOW_OP_SECONDS
            and commit_iterations_requested > _SLOW_OP_ITERATIONS
        ):
            commit_iterations_requested = _SLOW_OP_ITERATIONS
            dropped_commit = True
        if commit_iterations_run >= commit_iterations_requested:
            break

    doc.close()

    commit_meta = {
        "iterations_requested": iterations,
        "iterations_run": commit_iterations_run,
        "dropped_to_slow_op_cap": dropped_commit,
        "slow_op_threshold_seconds": _SLOW_OP_SECONDS,
    }

    return {
        "label": label,
        "note": "synthetic accept-path fixture; not measured on unmodified corpus content",
        "cold_prepare_seconds": {**_percentiles(cold_durations), **cold_meta},
        "warm_prepare_seconds": {**_percentiles(warm_durations), **warm_meta},
        "cold_prepare_result_types": sorted(set(cold_types)),
        "warm_prepare_result_types": sorted(set(warm_types)),
        "commit_seconds": {**_percentiles(commit_durations), **commit_meta},
        "raster_verification_selfcompare_seconds": _percentiles(verify_isolated_durations),
        "raster_verification_selfcompare_note": (
            "measured by re-running capture_page_state + verify_tier0_commit "
            "against the just-committed page compared to ITSELF (no further "
            "mutation) -- every row matches, so _first_diff_outside_halo's "
            "per-pixel inner loop is never entered; this number is dominated "
            "by 2x page.get_pixmap(dpi=96) plus V0e's whole-document tobytes() "
            "reopen check, NOT by real pixel-diff work. It is a lower bound, "
            "not the cost of verifying an edit that actually changed pixels"
        ),
        "undo_via_reversal_patchset_seconds": _percentiles(undo_durations),
        "redo_via_reversal_patchset_seconds": _percentiles(redo_durations),
    }


def _accept_path_preview(
    fixture_bytes: bytes, page_index: int, label: str, iterations: int
) -> dict[str, Any]:
    origin = _fixture_target_origin(fixture_bytes, page_index)
    doc = fitz.open("pdf", fixture_bytes)
    page = doc[page_index]
    rect = tuple(page.rect)
    session = open_preview_session(doc, page_index, f"bench-accept-{label}")
    doc.close()
    if session is None:
        return {"not_measurable": "encrypted document could not be snapshotted"}

    renderer = PlanPreviewRenderer(session)
    tokens: set[bool] = set()
    generation_counter = {"value": 0}

    def _generation_once() -> None:
        req = PlanPreviewRequest(
            session_key=f"bench-accept-{label}", generation=generation_counter["value"],
            target_text=_INJECT_TARGET, replacement_text=_INJECT_REPLACEMENT,
            expected_origin=origin, target_bbox=None, clip_rect=rect, render_scale=1.0,
        )
        generation_counter["value"] += 1
        result = renderer.render(req)
        tokens.add(result.plan_token is not None)

    durations, _results, meta = _adaptive_run(_generation_once, iterations)
    renderer.close()

    return {
        "label": label,
        "note": "synthetic accept-path fixture; includes the raster (not just classify+bind)",
        "all_calls_accepted": tokens == {True},
        "preview_generation_render_headless_seconds": {**_percentiles(durations), **meta},
    }


# ---------------------------------------------------------------------- memory


def _memory_peak_dense_prepare_reject(dense_path: Path, page_index: int) -> dict[str, Any]:
    doc = fitz.open(str(dense_path))
    page = doc[page_index]
    picked = _pick_real_target(doc, page)
    doc.close()
    if picked is None:
        return {"not_measurable": "page has no show operators to bind a target from"}
    text, origin = picked

    gc.collect()
    tracemalloc.start()
    d = fitz.open(str(dense_path))
    p = d[page_index]
    engine = TieredCommitEngine(d)
    result = engine.prepare(
        p, target_text=text, replacement_text=text + "!",
        expected_origin=origin, target_bbox=None,
    )
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    d.close()
    return {
        "scenario": "fresh fitz.open + one prepare() call on the real, natural reject-path target",
        "result_type": type(result).__name__,
        "current_bytes": current,
        "peak_bytes": peak,
    }


def _memory_peak_dense_prepare_accept(fixture_bytes: bytes, page_index: int) -> dict[str, Any]:
    origin = _fixture_target_origin(fixture_bytes, page_index)
    gc.collect()
    tracemalloc.start()
    d = fitz.open("pdf", fixture_bytes)
    p = d[page_index]
    engine = TieredCommitEngine(d)
    result = engine.prepare(
        p, target_text=_INJECT_TARGET, replacement_text=_INJECT_REPLACEMENT,
        expected_origin=origin, target_bbox=None,
    )
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    d.close()
    return {
        "scenario": (
            "synthetic accept-path fixture; one prepare() call that reaches "
            "the scratch-copy build + scratch verify (heavier than reject-path)"
        ),
        "result_type": type(result).__name__,
        "current_bytes": current,
        "peak_bytes": peak,
    }


def _teardown_leak(dense_path: Path, page_index: int, cycles: int = 25) -> dict[str, Any]:
    doc = fitz.open(str(dense_path))
    page = doc[page_index]
    picked = _pick_real_target(doc, page)
    rect = tuple(page.rect)
    doc.close()
    if picked is None:
        return {"not_measurable": "page has no show operators to bind a target from"}
    text, origin = picked

    rss_before = psutil.Process().memory_info().rss if psutil is not None else None

    gc.collect()
    tracemalloc.start()
    tracemalloc.clear_traces()
    before_current, _ = tracemalloc.get_traced_memory()

    for cycle in range(cycles):
        d = fitz.open(str(dense_path))
        session = open_preview_session(d, page_index, f"bench-teardown-{cycle}")
        d.close()
        if session is None:
            continue
        renderer = PlanPreviewRenderer(session)
        req = PlanPreviewRequest(
            session_key=f"bench-teardown-{cycle}", generation=0,
            target_text=text, replacement_text=text + "!", expected_origin=origin,
            target_bbox=None, clip_rect=rect,
            render_scale=1.0,
        )
        renderer.render(req)  # forces PlanPreviewRenderer._ensure_scratch open
        renderer.close()
        del renderer, session, req

    gc.collect()
    after_current, after_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    rss_after = psutil.Process().memory_info().rss if psutil is not None else None

    return {
        "cycles": cycles,
        "one_render_per_cycle": True,
        "tracemalloc_current_growth_bytes": after_current - before_current,
        "tracemalloc_peak_bytes_over_cycles": after_peak,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "rss_growth_bytes": (
            None if rss_before is None or rss_after is None else rss_after - rss_before
        ),
        "psutil_available": psutil is not None,
    }


# --------------------------------------------------------------------- main


def _versions() -> dict[str, Any]:
    return {
        "python": sys.version,
        "pymupdf": fitz.__doc__.splitlines()[0] if fitz.__doc__ else None,
        "pymupdf_version": getattr(fitz, "version", None),
    }


def _dig(d: dict[str, Any], *path: str) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _interpretive_notes(report: dict[str, Any]) -> list[str]:
    """Facts that make the raw percentiles above usable without re-deriving
    them -- each stated once, each traceable back to a field in this JSON.
    """
    notes: list[str] = []

    cold_p50 = _dig(report, "accept_path", "dense_injected", "cold_prepare_seconds", "p50")
    warm_p50 = _dig(report, "accept_path", "dense_injected", "warm_prepare_seconds", "p50")
    dense_n = _dig(report, "accept_path", "dense_injected", "cold_prepare_seconds", "n")
    dropped = _dig(
        report, "accept_path", "dense_injected", "cold_prepare_seconds", "dropped_to_slow_op_cap"
    )
    if cold_p50 is not None and warm_p50 is not None:
        notes.append(
            f"accept_path.dense_injected: warm prepare p50 ({warm_p50:.3f}s) is "
            f"within noise of cold prepare p50 ({cold_p50:.3f}s) -- prepare() "
            "re-pays a whole-document tobytes(encryption=KEEP) scratch snapshot "
            "on every single call, so there is no warm-up to amortize on this "
            "402-page document. Likely the single most consequential number "
            "here for Task 11 per-keystroke cost."
        )
    if dense_n is not None and dropped:
        notes.append(
            f"accept_path.dense_injected timing fields ran n={dense_n} (the "
            "first sample exceeded the 2s slow-op threshold, capping the run). "
            "At n=5, p95 and p99 are both literally the max of 5 samples -- "
            "not a tail estimate. Read them as 'the slowest of 5', not as a "
            "percentile in the statistical sense."
        )

    session_open = _dig(report, "real_corpus", "dense_preview", "open_preview_session_seconds")
    snapshot_len = _dig(report, "real_corpus", "dense_preview", "session_snapshot_bytes")
    gen_p95_reject = _dig(
        report, "real_corpus", "dense_preview",
        "preview_generation_render_headless_seconds", "p95",
    )
    gen_p95_accept = _dig(
        report, "accept_path", "dense_injected_preview",
        "preview_generation_render_headless_seconds", "p95",
    )
    if session_open is not None:
        parts = [
            "preview.py already avoids the per-call scratch-rebuild cost that "
            "engine.prepare() pays: open_preview_session() pays the whole-"
            f"document snapshot once ({session_open:.3f}s",
        ]
        if snapshot_len is not None:
            parts.append(f", {snapshot_len} bytes")
        parts.append("), then each generation is cheap")
        generation_parts = []
        if gen_p95_reject is not None:
            generation_parts.append(f"reject-path p95={gen_p95_reject:.3f}s")
        if gen_p95_accept is not None:
            generation_parts.append(f"accept-path p95={gen_p95_accept:.3f}s")
        if generation_parts:
            parts.append(" (" + ", ".join(generation_parts) + ")")
        parts.append(
            " -- PlanPreviewRenderer reusing one scratch document per session "
            "is doing architecturally what engine.prepare() does not."
        )
        notes.append("".join(parts))

    peak_accept = _dig(report, "memory", "dense_prepare_accept_path", "peak_bytes")
    peak_reject = _dig(report, "memory", "dense_prepare_reject_path", "peak_bytes")
    if peak_accept is not None and peak_reject is not None:
        notes.append(
            f"peak memory (tracemalloc) around one dense-file prepare() call: "
            f"{peak_accept} bytes on the accept path vs {peak_reject} bytes on "
            "the reject path -- the accept path's whole-document scratch copy "
            "roughly doubles the source PDF's size in memory; the reject path "
            "never builds one."
        )

    growth = _dig(report, "memory", "preview_session_teardown_leak", "tracemalloc_current_growth_bytes")
    psutil_ok = _dig(report, "memory", "psutil_available")
    if growth is not None:
        notes.append(
            f"preview-session teardown over 25 open/render/close cycles: "
            f"{growth} bytes of net tracemalloc growth, psutil "
            + ("available" if psutil_ok else "UNAVAILABLE (no RSS cross-check)")
            + " -- tracemalloc only sees Python-side allocations, not MuPDF's "
            "C-side buffers, so this is not a clean no-leak verdict, only a "
            "Python-heap-side data point."
        )

    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument(
        "--out",
        default=str(ROOT / "benchmarks" / "baseline-2026-08-01.json"),
    )
    args = parser.parse_args(argv)

    if not _SMALL_PDF.exists() or not _DENSE_PDF.exists():
        print("error: expected test_files/1.pdf and test_files/test-large-file.pdf", file=sys.stderr)
        return 2

    small_doc = fitz.open(str(_SMALL_PDF))
    small_counts = _page_show_counts(small_doc)
    small_shows_total = sum(small_counts)
    small_stats = {
        "page_count": small_doc.page_count,
        "shows_total": small_shows_total,
        "densest_page_index": 0,
        "densest_page_shows": small_shows_total,
        "p50_shows_per_page": small_shows_total,
    }
    small_doc.close()

    dense_doc = fitz.open(str(_DENSE_PDF))
    dense_page_index, dense_stats = _densest_page(dense_doc)
    dense_doc.close()

    report: dict[str, Any] = {
        "meta": {
            **_versions(),
            "iterations_requested_default": args.iterations,
            "small_pdf": _SMALL_PDF.name,
            "dense_pdf": _DENSE_PDF.name,
        },
        "corpus_page_stats": {
            "small": small_stats,
            "dense": dense_stats,
        },
        "corpus_findings": _corpus_findings(_ALL_CORPUS_PDFS),
        "pitfalls_found": (
            "Scoped to what was measured (one file, one producer -- not "
            "generalized): on test_files/test-large-file.pdf (PyMuPDF 1.27.1), "
            "all five font objects on the target page have their dictionary "
            "keys reordered (same keys, same length, different order; first "
            "divergence at char 6: /BaseFont vs /Type) by the FIRST "
            "tobytes(encryption=KEEP) round trip -- confirmed idempotent on "
            "every round trip after that first one. Because page_fingerprint() "
            "hashes each font dependency object's xref_object() string "
            "verbatim, and TieredCommitEngine.prepare()'s scratch-first "
            "self-consistency check (_build_scratch_copy) performs exactly "
            "that first round trip internally, every accept-path candidate on "
            "THIS file fails with VERIFICATION_FAILED/'page fingerprint "
            "changed' on the very first prepare() attempt, even a genuinely "
            "Tier-0-eligible one. Whether every disk-loaded PDF reorders this "
            "way is untested. Real-corpus REJECT-path numbers in this report "
            "are unaffected (prepare() returns before _build_scratch_copy runs "
            "on rejection). Existing synthetic-fixture unit tests never "
            "observed this: their docs are built fresh via "
            "fitz.open()+new_page(), with no pre-existing on-disk key order to "
            "disagree with. Workaround used by this script's own accept-path "
            "fixture: canonicalize with one tobytes(encryption=KEEP)+reopen "
            "round trip before the first prepare() call (see "
            "_canonicalize_once)."
        ),
        "real_corpus": {
            "small_prepare": _real_corpus_prepare(_SMALL_PDF, 0, args.iterations),
            "small_preview": _real_corpus_preview(_SMALL_PDF, 0, args.iterations),
            "dense_prepare": _real_corpus_prepare(_DENSE_PDF, dense_page_index, args.iterations),
            "dense_preview": _real_corpus_preview(_DENSE_PDF, dense_page_index, args.iterations),
        },
    }

    small_fixture = _synthetic_minimal_fixture()
    dense_fixture = _inject_literal_tj_fixture(_DENSE_PDF, dense_page_index)

    report["accept_path"] = {
        "small_synthetic": _accept_path_metrics(
            small_fixture, 0, "synthetic_minimal_single_page", args.iterations
        ),
        "small_synthetic_preview": _accept_path_preview(
            small_fixture, 0, "synthetic_minimal_single_page", args.iterations
        ),
        "dense_injected": _accept_path_metrics(
            dense_fixture, dense_page_index, "real_dense_page_injected_target", args.iterations
        ),
        "dense_injected_preview": _accept_path_preview(
            dense_fixture, dense_page_index, "real_dense_page_injected_target", args.iterations
        ),
    }

    report["memory"] = {
        "dense_prepare_reject_path": _memory_peak_dense_prepare_reject(
            _DENSE_PDF, dense_page_index
        ),
        "dense_prepare_accept_path": _memory_peak_dense_prepare_accept(
            dense_fixture, dense_page_index
        ),
        "preview_session_teardown_leak": _teardown_leak(_DENSE_PDF, dense_page_index, cycles=25),
        "psutil_available": psutil is not None,
    }

    report["stale_generation_drop_rate"] = {
        "not_measurable_headless": True,
        "reason": (
            "the generation counter that drops stale preview raster callbacks "
            "(view/text_editing.py: _plan_generation) lives in the Qt "
            "coordinator, out of reach for a headless model-layer script and "
            "out of scope for this CLAUDE.md layer boundary; measure in-app later"
        ),
    }

    report["notes"] = _interpretive_notes(report)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
