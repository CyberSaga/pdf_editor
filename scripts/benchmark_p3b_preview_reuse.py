"""Task 13 P3-B acceptance harness — preview replay reuse, latency + memory.

Measures the production preview path (``PlanPreviewRenderer.render``) on a
deterministic synthetic dense page and verifies the slice's acceptance
contract in REPLAY COUNTS, not milliseconds:

    cold first render        -> exactly 1 replay
    warm later keystrokes    -> exactly 0 replays
    post-mutation prepare    -> exactly 1 replay (rebuild, never reuse)
    false cache hits         -> 0

plus bounded-memory semantics (single cache entry, replaced/closed replays
collectible) and informational latency percentiles.  Verify stages never
replay (they only hash streams), so per-render replay counts are exact.

Synthetic corpus only — deterministic, privacy-free, reproducible by any
reviewer; no document text or paths beyond this script appear in the
report.  The report is aggregate-only JSON under the gitignored
``benchmarks/``.  The 4 MiB replay budget is consumed verbatim; there is
no unbounded flag here.

Run:  .venv\\Scripts\\python.exe scripts/benchmark_p3b_preview_reuse.py
"""
from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import time
import tracemalloc
import weakref
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

import model.text_commit.evidence as evidence_mod  # noqa: E402
import model.text_commit.inspect as inspect_mod  # noqa: E402
from model.text_commit.evidence import ReplayEvidenceCache  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.plan import PreparedEdit, prepare_plan  # noqa: E402
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
WARM_KEYSTROKES = 30
SMALL_KEYSTROKES = 100
MUTATION_ROUNDS = 8
OPEN_CLOSE_ROUNDS = 12


class ReplayCounter:
    """Counts every replay execution on the production path (both namespaces)."""

    def __init__(self) -> None:
        self.count = 0
        self._originals: list[tuple[object, str, object]] = []

    def install(self) -> None:
        def counting(streams, **kw):  # noqa: ANN001, ANN003 - shim
            self.count += 1
            return replay_page_streams(streams, **kw)

        for mod in (inspect_mod, evidence_mod):
            self._originals.append(
                (mod, "replay_page_streams", mod.replay_page_streams)
            )
            mod.replay_page_streams = counting  # type: ignore[attr-defined]

    def uninstall(self) -> None:
        for mod, name, original in self._originals:
            setattr(mod, name, original)
        self._originals.clear()

    def take(self) -> int:
        value, self.count = self.count, 0
        return value


def _build_doc(*, dense: bool) -> fitz.Document:
    """One-page synthetic doc: Helvetica/WinAnsi literal-Tj shows.

    ``dense`` pads the stream with vector path ops to ~2.5 MiB decoded
    (under the 4 MiB budget) so the replay walk pays a corpus-like lexing
    bill; the small variant keeps the same show shape at trivial size.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    parts = [b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "]
    n_rows = 400 if dense else 8
    for i in range(n_rows):
        parts.append(b"0 -1.5 Td (Row %04d) Tj " % i)
    parts.append(b"ET\n")
    if dense:
        # Token-dense, raster-free padding: the replay bill scales with
        # lexed tokens and gs-stack traffic (the CAD shape), while keeping
        # the pixmap/verify raster cost off this harness's ruler — a
        # stroke-heavy pad would swamp every timing with rasterization,
        # which is not what this slice changes.
        pad_target = int(2.5 * 1024 * 1024)
        line = bytearray()
        i = 0
        while len(line) < pad_target:
            a = (i % 89) + 1
            b = (i % 97) + 1
            line += b"q 1 0 0 1 %d %d cm Q\n" % (a, b)
            i += 1
        parts.append(bytes(line))
    stream = b"".join(parts)
    assert len(stream) < DEFAULT_MAX_REPLAY_BYTES, "must stay within budget"
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


def _request(doc: fitz.Document, generation: int, replacement: str) -> PlanPreviewRequest:
    span = _span(doc[0], TARGET)
    bbox = tuple(span["bbox"])
    clip = (bbox[0] - 4.0, bbox[1] - 4.0, bbox[2] + 4.0, bbox[3] + 4.0)
    return PlanPreviewRequest(
        session_key="p3b-acceptance",
        generation=generation,
        target_text=TARGET,
        replacement_text=replacement,
        expected_origin=tuple(span["origin"]),
        target_bbox=bbox,
        clip_rect=clip,
        render_scale=2.0,
    )


def _percentiles(samples_ms: list[float]) -> dict:
    ordered = sorted(samples_ms)
    return {
        "n": len(ordered),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
    }


def run_latency(counter: ReplayCounter) -> tuple[dict, list[str]]:
    """Dense-page renderer scenarios: cold, warm keystrokes, second cold."""
    failures: list[str] = []
    doc = _build_doc(dense=True)
    decoded_total = sum(
        len(doc.xref_stream(x) or b"") for x in doc[0].get_contents()
    )
    # Prepare-level isolation first (the P3-A-comparable pair): what the
    # replay walk costs cold vs what a validated warm prepare costs.
    registry = DocumentFontRegistry(doc)
    prep_cache = ReplayEvidenceCache()
    span = _span(doc[0], TARGET)
    prep_kwargs = dict(
        target_text=TARGET,
        replacement_text="Price 2025",
        expected_origin=tuple(span["origin"]),
        target_bbox=None,
        registry=registry,
        evidence_cache=prep_cache,
    )
    counter.take()
    t0 = time.perf_counter()
    prep_cold = prepare_plan(doc, doc[0], **prep_kwargs)
    prep_cold_ms = (time.perf_counter() - t0) * 1000.0
    prep_cold_replays = counter.take()
    warm_prep_ms: list[float] = []
    for _ in range(10):
        t0 = time.perf_counter()
        prepare_plan(doc, doc[0], **prep_kwargs)
        warm_prep_ms.append((time.perf_counter() - t0) * 1000.0)
    prep_warm_replays = counter.take()
    if not isinstance(prep_cold, PreparedEdit):
        failures.append(f"dense cold prepare rejected: {prep_cold.reason}")
    if prep_cold_replays != 1:
        failures.append(f"dense cold prepare replays {prep_cold_replays} != 1")
    if prep_warm_replays != 0:
        failures.append(f"dense warm prepares replayed {prep_warm_replays} != 0")

    session = open_preview_session(doc, 0, "p3b-acceptance")
    assert session is not None
    tracemalloc.start()
    renderer = PlanPreviewRenderer(session)
    counter.take()
    t0 = time.perf_counter()
    cold = renderer.render(_request(doc, 1, "Price 2025"))
    cold_ms = (time.perf_counter() - t0) * 1000.0
    cold_replays = counter.take()
    if not cold.plan_token:
        failures.append(f"cold render rejected: {cold.reject_reason}")
    if cold_replays != 1:
        failures.append(f"cold render replays: {cold_replays} != 1")

    warm_ms: list[float] = []
    warm_replays_total = 0
    warm_tokens = 0
    for i in range(WARM_KEYSTROKES):
        replacement = f"Price 2{i % 10}25"
        t0 = time.perf_counter()
        result = renderer.render(_request(doc, 2 + i, replacement))
        warm_ms.append((time.perf_counter() - t0) * 1000.0)
        warm_replays_total += counter.take()
        if result.plan_token:
            warm_tokens += 1
    if warm_replays_total != 0:
        failures.append(f"warm keystrokes replayed {warm_replays_total} times != 0")
    if warm_tokens != WARM_KEYSTROKES:
        failures.append(f"warm accepted {warm_tokens}/{WARM_KEYSTROKES}")
    _current, tm_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    cache = renderer._evidence_cache  # introspection, same as the matrix
    entry = cache.lookup_any()
    n_shows = len(entry.replay.shows) if entry is not None else 0
    single_entry_ok = cache.entry_count == 1 and cache.stores == 1
    if not single_entry_ok:
        failures.append(
            f"dense session cache not single-store: entries={cache.entry_count} "
            f"stores={cache.stores}"
        )
    hits = cache.hits

    second = PlanPreviewRenderer(session)
    counter.take()
    t0 = time.perf_counter()
    cold2 = second.render(_request(doc, 999, "Price 2925"))
    cold2_ms = (time.perf_counter() - t0) * 1000.0
    cold2_replays = counter.take()
    if cold2_replays != 1:
        failures.append(f"fresh renderer cold replays: {cold2_replays} != 1")
    if cold2.plan_token != second.render(_request(doc, 1000, "Price 2925")).plan_token:
        failures.append("fresh renderer warm token != its own cold token")
    counter.take()
    second.close()
    renderer.close()
    doc.close()
    report = {
        "decoded_stream_bytes": decoded_total,
        "retained_replay_shows": n_shows,
        "cold_prepare": {"ms": round(prep_cold_ms, 3), "replays": prep_cold_replays},
        "warm_prepares": {**_percentiles(warm_prep_ms), "replays_total": prep_warm_replays},
        "cold_render": {"ms": round(cold_ms, 3), "replays": cold_replays},
        "second_cold_render": {"ms": round(cold2_ms, 3), "replays": cold2_replays},
        "warm_renders": {
            **_percentiles(warm_ms),
            "replays_total": warm_replays_total,
            "cache_hits": hits,
            "accepted": warm_tokens,
        },
        "warm_loop_tracemalloc_peak_bytes": tm_peak,
    }
    return report, failures


def run_mutation(counter: ReplayCounter) -> tuple[dict, list[str]]:
    """Prepare-level missed-hook mutation loop: every round must rebuild."""
    failures: list[str] = []
    doc = _build_doc(dense=False)
    registry = DocumentFontRegistry(doc)
    cache = ReplayEvidenceCache()
    replaced_refs: list[weakref.ref] = []
    rebuild_ms: list[float] = []
    fingerprints: set[str] = set()
    counter.take()
    for i in range(MUTATION_ROUNDS):
        page = doc[0]
        span = _span(page, TARGET)
        t0 = time.perf_counter()
        plan = prepare_plan(
            doc,
            page,
            target_text=TARGET,
            replacement_text="Price 2025",
            expected_origin=tuple(span["origin"]),
            target_bbox=None,
            registry=registry,
            evidence_cache=cache,
        )
        rebuild_ms.append((time.perf_counter() - t0) * 1000.0)
        replays = counter.take()
        if replays != 1:
            failures.append(f"mutation round {i}: replays {replays} != 1")
        if not isinstance(plan, PreparedEdit):
            failures.append(f"mutation round {i}: rejected {plan.reason}")
        else:
            if plan.page_fingerprint in fingerprints:
                failures.append(f"mutation round {i}: fingerprint reused (false hit)")
            fingerprints.add(plan.page_fingerprint)
        entry = cache.lookup_any()
        if entry is not None:
            replaced_refs.append(weakref.ref(entry.replay))
        # Direct update_stream: the unsignalled mutation class.
        content_xref = page.get_contents()[0]
        doc.update_stream(content_xref, (doc.xref_stream(content_xref) or b"") + b" ")
    del entry
    gc.collect()
    alive = sum(1 for r in replaced_refs if r() is not None)
    if alive > 1:
        failures.append(f"replaced replays alive after gc: {alive} > 1")
    doc.close()
    return {
        "rounds": MUTATION_ROUNDS,
        "rebuild": _percentiles(rebuild_ms),
        "distinct_fingerprints": len(fingerprints),
        "replaced_replays_alive_after_gc": alive,
    }, failures


def run_memory(counter: ReplayCounter) -> tuple[dict, list[str]]:
    """Bounded-retention loops on the small doc (semantics, not timing)."""
    failures: list[str] = []
    doc = _build_doc(dense=False)
    session = open_preview_session(doc, 0, "p3b-acceptance")
    assert session is not None

    renderer = PlanPreviewRenderer(session)
    entry_counts = set()
    for i in range(SMALL_KEYSTROKES):
        result = renderer.render(_request(doc, i, f"Price 2{i % 10}25"))
        if not result.plan_token:
            failures.append(f"keystroke {i} rejected: {result.reject_reason}")
            break
        entry_counts.add(renderer._evidence_cache.entry_count)
    stores = renderer._evidence_cache.stores
    if entry_counts != {1}:
        failures.append(f"keystroke loop entry counts drifted: {sorted(entry_counts)}")
    if stores != 1:
        failures.append(f"keystroke loop stores {stores} != 1")
    renderer.close()

    refs: list[weakref.ref] = []
    for i in range(OPEN_CLOSE_ROUNDS):
        r = PlanPreviewRenderer(session)
        result = r.render(_request(doc, i, "Price 2025"))
        entry = r._evidence_cache.lookup_any()
        if result.plan_token and entry is not None:
            refs.append(weakref.ref(entry.replay))
        del entry
        r.close()
    gc.collect()
    leaked = sum(1 for ref in refs if ref() is not None)
    if leaked != 0:
        failures.append(f"open/close leaked {leaked} retained replays")
    counter.take()
    doc.close()
    return {
        "keystrokes": SMALL_KEYSTROKES,
        "keystroke_entry_counts": sorted(entry_counts),
        "keystroke_stores": stores,
        "open_close_rounds": OPEN_CLOSE_ROUNDS,
        "open_close_leaked_replays": leaked,
    }, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ROOT / "benchmarks" / "p3b-acceptance-2026-08-22.json",
        help="aggregate-only report path (gitignored benchmarks/ by default)",
    )
    args = parser.parse_args(argv)

    counter = ReplayCounter()
    counter.install()
    try:
        latency, fail_a = run_latency(counter)
        mutation, fail_b = run_mutation(counter)
        memory, fail_c = run_memory(counter)
    finally:
        counter.uninstall()
    failures = fail_a + fail_b + fail_c
    report = {
        "harness": "p3b-preview-replay-reuse-acceptance",
        "corpus": "synthetic-deterministic (this script)",
        "acceptance": {
            "passed": not failures,
            "failures": failures,
            "contract": {
                "cold_replays": 1,
                "warm_replays": 0,
                "post_mutation_replays": 1,
                "false_hits": 0,
            },
        },
        "latency": latency,
        "mutation": mutation,
        "memory": memory,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["acceptance"], indent=2))
    print(f"cold {latency['cold_render']['ms']} ms / warm p50 "
          f"{latency['warm_renders']['p50_ms']} ms (report: {args.json_out})")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
