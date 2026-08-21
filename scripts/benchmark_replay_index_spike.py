"""Task 13 P3-A latency/index census harness. Read-only; aggregate-only.

Decomposes today's per-keystroke prepare cost by stage (stream read,
replay, bind, fingerprint, plan, end-to-end engine prepare) and measures
the two spike index shapes (``scripts/replay_index_spike.py``) for build
latency, warm-lookup latency, and retained memory, across the five
scenarios from the plan (`plans/task13-p3a-replay-index-spike.md` §3).

Data policy (Task 12/13, verbatim): the emitted report carries ONLY
counts, timings, byte lengths, booleans, and stable reason codes — never
document text, filenames, paths, font names, or rejection detail strings
(details interpolate font/basefont names; only ``.reason`` is recorded).
Documents are labeled ``doc_0``, ``doc_1``, … by argument position.

Budget: every build and replay call uses the production
``DEFAULT_MAX_REPLAY_BYTES`` unless ``--diagnostic-unbounded`` /
``unbounded=True`` is passed explicitly — clearly labeled in the report,
never a production behavior claim. Content mutation for the
``post_mutation_rebuild`` scenario happens on an in-memory COPY of the
stream list only; the document is never written.

Usage::

    "<venv>/python.exe" scripts/benchmark_replay_index_spike.py FILE...
        [--iterations N] [--max-pages N] [--json] [--out PATH]
        [--diagnostic-unbounded]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    BindingFailure,
    bind_source_text,
    page_fingerprint,
    read_page_streams,
)
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    prepare_plan,
)
from model.text_commit.replay import (  # noqa: E402
    DEFAULT_MAX_REPLAY_BYTES,
    replay_page_streams,
)

from scripts.replay_index_spike import (  # noqa: E402
    MaterializedShowTable,
    ReplayIndexRefusedError,
    SparseCheckpointIndex,
)

STAGE_NAMES: tuple[str, ...] = (
    "read_streams",
    "replay",
    "bind",
    "fingerprint",
    "prepare_plan",
    "engine_prepare",
    "shape_a_build",
    "shape_a_lookup",
    "shape_b_build",
    "shape_b_lookup",
)

SCENARIO_NAMES: tuple[str, ...] = (
    "cold_first_edit",
    "warm_second_target",
    "warm_changed_replacement",
    "post_mutation_rebuild",
    "different_page",
)


def _timed(fn, iterations: int) -> tuple[list[float], object]:
    """Run ``fn`` ``iterations`` times; return per-run ms and last result."""
    samples: list[float] = []
    result: object = None
    for _ in range(max(1, iterations)):
        start = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples, result


def _stat(samples: list[float]) -> dict[str, object]:
    if not samples:
        return {"n": 0}
    return {
        "n": len(samples),
        "median_ms": round(statistics.median(samples), 3),
        "min_ms": round(min(samples), 3),
        "max_ms": round(max(samples), 3),
    }


def _page_decoded_size(doc: fitz.Document, page: fitz.Page) -> int:
    return sum(len(doc.xref_stream(xref) or b"") for xref in page.get_contents())


def _pick_targets(shows) -> list[str]:
    """Up to two distinct latin-1-decodable target texts, longest first."""
    seen: list[str] = []
    for show in sorted(shows, key=lambda s: -len(s.decoded_bytes)):
        if not show.decoded_bytes:
            continue
        try:
            text = show.decoded_bytes.decode("latin-1")
        except UnicodeDecodeError:  # pragma: no cover - latin-1 total
            continue
        if text not in seen:
            seen.append(text)
        if len(seen) == 2:
            break
    return seen


def _reason_of(outcome) -> str | None:
    """Stable reason code only — never the detail string (data policy)."""
    if isinstance(outcome, (PlanRejection, BindingFailure)):
        return str(outcome.reason)
    return None


def _count_stream_reads(doc: fitz.Document, fn):
    """Run ``fn`` while counting doc.xref_stream calls and bytes."""
    calls = {"n": 0, "bytes": 0}
    original = doc.xref_stream

    def _counting(xref: int):
        data = original(xref)
        calls["n"] += 1
        calls["bytes"] += len(data or b"")
        return data

    doc.xref_stream = _counting  # type: ignore[method-assign]
    try:
        result = fn()
    finally:
        del doc.xref_stream  # restore the class method
    return calls, result


def _measure_page(
    doc: fitz.Document,
    engine: TieredCommitEngine,
    page_index: int,
    *,
    iterations: int,
    max_decoded_bytes: int | None,
    other_page_index: int | None,
) -> dict[str, object]:
    page = doc[page_index]
    record: dict[str, object] = {"page_index": page_index}
    stages: dict[str, dict[str, object]] = {name: {"n": 0} for name in STAGE_NAMES}
    scenarios: dict[str, dict[str, object]] = {
        name: {"n": 0} for name in SCENARIO_NAMES
    }

    read_samples, streams = _timed(lambda: read_page_streams(doc, page), iterations)
    stages["read_streams"] = _stat(read_samples)
    decoded_total = sum(len(data) for _, data in streams)
    record["decoded_bytes_total"] = decoded_total
    record["n_streams"] = len(streams)

    replay_samples, replay = _timed(
        lambda: replay_page_streams(streams, max_decoded_bytes=max_decoded_bytes),
        iterations,
    )
    stages["replay"] = _stat(replay_samples)
    record["replay_refusal"] = replay.refusal_reason
    record["n_shows"] = len(replay.shows)
    record["replay_malformed"] = replay.malformed

    targets = _pick_targets(replay.shows)
    record["n_targets_probed"] = len(targets)
    page_xref = doc.page_xref(page_index)

    if targets:
        target = targets[0]
        bind_samples, binding = _timed(
            lambda: bind_source_text(
                doc,
                page,
                target_text=target,
                expected_origin=None,
                registry=engine.registry,
            ),
            iterations,
        )
        stages["bind"] = _stat(bind_samples)
        record["bind_reason"] = _reason_of(binding)

        fp_samples, _ = _timed(lambda: page_fingerprint(doc, page), iterations)
        stages["fingerprint"] = _stat(fp_samples)

        def _plan(replacement: str):
            return prepare_plan(
                doc,
                page,
                target_text=target,
                replacement_text=replacement,
                expected_origin=None,
                target_bbox=None,
                registry=engine.registry,
                style_overrides=None,
                new_rect=None,
                page_has_pending_maintenance=False,
                max_tier=0,
            )

        reads, _ = _count_stream_reads(doc, lambda: _plan(target[:-1] or "Y"))
        record["prepare_plan_stream_reads"] = reads

        plan_samples, plan_outcome = _timed(
            lambda: _plan(target[:-1] or "Y"), iterations
        )
        stages["prepare_plan"] = _stat(plan_samples)
        record["prepare_plan_reason"] = _reason_of(plan_outcome)
        scenarios["cold_first_edit"] = _stat(plan_samples)

        keystroke_samples, _ = _timed(
            lambda: _plan((target[:-1] or "Y") + "Z"), iterations
        )
        scenarios["warm_changed_replacement"] = _stat(keystroke_samples)

        engine_samples, engine_outcome = _timed(
            lambda: engine.prepare(
                page,
                target_text=target,
                replacement_text=target[:-1] or "Y",
                expected_origin=None,
            ),
            1,  # scratch clone + verify is heavy; once is honest enough
        )
        stages["engine_prepare"] = _stat(engine_samples)
        record["engine_prepare_reason"] = _reason_of(engine_outcome)

    # ---------------------------------------------------------- Shape A
    tracemalloc.start()
    a_build_samples, table = _timed(
        lambda: MaterializedShowTable.build(
            page_xref, streams, max_decoded_bytes=max_decoded_bytes
        ),
        iterations,
    )
    _, a_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    stages["shape_a_build"] = _stat(a_build_samples)
    shape_a: dict[str, object] = {
        "build_peak_tracemalloc_bytes": a_peak,
        "refused": table.refusal_reason is not None,
    }
    if table.refusal_reason is None:
        shape_a["memory_footprint"] = table.memory_footprint()
        if targets:
            target_bytes = targets[0].encode("latin-1")
            a_lookup_samples, hits = _timed(
                lambda: table.lookup(target_bytes), iterations
            )
            stages["shape_a_lookup"] = _stat(a_lookup_samples)
            shape_a["lookup_hits"] = len(hits)  # type: ignore[arg-type]
            if len(targets) == 2:
                second = targets[1].encode("latin-1")
                second_samples, _ = _timed(lambda: table.lookup(second), iterations)
                scenarios["warm_second_target"] = _stat(second_samples)
    record["shape_a"] = shape_a

    # ---------------------------------------------------------- Shape B
    tracemalloc.start()
    b_build_samples, index = _timed(
        lambda: SparseCheckpointIndex.build(
            page_xref, streams, max_decoded_bytes=max_decoded_bytes
        ),
        iterations,
    )
    _, b_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    stages["shape_b_build"] = _stat(b_build_samples)
    shape_b: dict[str, object] = {
        "build_peak_tracemalloc_bytes": b_peak,
        "refused": index.refusal_reason is not None,
    }
    if index.refusal_reason is None:
        shape_b["memory_footprint"] = index.memory_footprint()
        if targets:
            target_bytes = targets[0].encode("latin-1")

            def _b_lookup() -> int:
                try:
                    seqs = index.candidate_seqs(streams, target_bytes)
                    for seq in seqs:
                        index.restore_show(streams, seq)
                    return len(seqs)
                except ReplayIndexRefusedError:  # pragma: no cover
                    return -1

            b_lookup_samples, n_hits = _timed(_b_lookup, iterations)
            stages["shape_b_lookup"] = _stat(b_lookup_samples)
            shape_b["lookup_hits"] = n_hits

    # post-mutation rebuild: in-memory stream-list copy only, never the doc
    mutated = [(xref, data + b" ") for xref, data in streams]
    rebuild_samples, _ = _timed(
        lambda: SparseCheckpointIndex.build(
            page_xref, mutated, max_decoded_bytes=max_decoded_bytes
        ),
        iterations,
    )
    scenarios["post_mutation_rebuild"] = _stat(rebuild_samples)
    record["shape_b"] = shape_b

    if other_page_index is not None:
        other = doc[other_page_index]
        other_streams = read_page_streams(doc, other)
        other_samples, _ = _timed(
            lambda: SparseCheckpointIndex.build(
                doc.page_xref(other_page_index),
                other_streams,
                max_decoded_bytes=max_decoded_bytes,
            ),
            iterations,
        )
        scenarios["different_page"] = _stat(other_samples)

    record["stages"] = stages
    record["scenarios"] = scenarios
    return record


def measure_document(
    doc: fitz.Document,
    *,
    label: str,
    iterations: int = 3,
    unbounded: bool = False,
    max_pages: int = 3,
) -> dict[str, object]:
    """Aggregate-only measurement report for one open document.

    Page selection: the LARGEST within-budget pages carry the latency
    story (an over-budget page refuses in milliseconds and would crowd
    them out of a pure top-by-size pick), so the full stage/scenario
    treatment goes to the top ``max_pages`` within-budget pages.
    Over-budget pages get a light refusal-cost probe (read + refused
    replay, production budget) — and the FULL treatment with the guard
    off only under ``unbounded=True``, labeled as diagnostic.
    """
    max_decoded_bytes = None if unbounded else DEFAULT_MAX_REPLAY_BYTES
    engine = TieredCommitEngine(doc)

    sizes = []
    for page_index in range(doc.page_count):
        sizes.append((_page_decoded_size(doc, doc[page_index]), page_index))
    sizes.sort(reverse=True)
    within = [
        page_index
        for size, page_index in sizes
        if size <= DEFAULT_MAX_REPLAY_BYTES
    ]
    over = [
        page_index
        for size, page_index in sizes
        if size > DEFAULT_MAX_REPLAY_BYTES
    ]
    selected = within[:max_pages]
    if unbounded:
        selected = selected + over[:2]

    pages: list[dict[str, object]] = []
    for position, page_index in enumerate(selected):
        other = selected[(position + 1) % len(selected)]
        pages.append(
            _measure_page(
                doc,
                engine,
                page_index,
                iterations=iterations,
                max_decoded_bytes=max_decoded_bytes,
                other_page_index=other if other != page_index else None,
            )
        )

    # Refusal-cost probes: production budget, read + refused replay only.
    refusal_probes: list[dict[str, object]] = []
    for page_index in over[:2]:
        probe_page = doc[page_index]
        probe_read_samples, probe_streams = _timed(
            lambda p=probe_page: read_page_streams(doc, p), iterations
        )
        probe_replay_samples, probe_replay = _timed(
            lambda s=probe_streams: replay_page_streams(
                s, max_decoded_bytes=DEFAULT_MAX_REPLAY_BYTES
            ),
            iterations,
        )
        refusal_probes.append(
            {
                "page_index": page_index,
                "decoded_bytes_total": sum(
                    len(data) for _, data in probe_streams
                ),
                "read_streams": _stat(probe_read_samples),
                "refused_replay": _stat(probe_replay_samples),
                "refusal_reason": probe_replay.refusal_reason,
            }
        )

    # Top-level stage aggregate: median of per-page medians.
    stages: dict[str, dict[str, object]] = {}
    for name in STAGE_NAMES:
        medians = [
            page["stages"][name]["median_ms"]  # type: ignore[index]
            for page in pages
            if page["stages"][name].get("n", 0)  # type: ignore[index]
        ]
        stages[name] = (
            {
                "n_pages": len(medians),
                "median_of_medians_ms": round(statistics.median(medians), 3),
            }
            if medians
            else {"n_pages": 0}
        )

    return {
        "label": label,
        "iterations": iterations,
        "unbounded": unbounded,
        "budget_bytes": DEFAULT_MAX_REPLAY_BYTES,
        "counts": {
            "pages_total": doc.page_count,
            "pages_measured": len(pages),
            "pages_over_budget": len(over),
        },
        "stages": stages,
        "over_budget_probes": refusal_probes,
        "pages": pages,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help="PDF files")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--diagnostic-unbounded",
        action="store_true",
        help="ALSO measure over-budget pages with the guard disabled "
        "(diagnostic channel only; clearly labeled, never a production "
        "behavior claim)",
    )
    args = parser.parse_args(argv)

    reports = []
    for position, path in enumerate(args.paths):
        doc = fitz.open(path)
        try:
            reports.append(
                measure_document(
                    doc,
                    label=f"doc_{position}",
                    iterations=args.iterations,
                    unbounded=args.diagnostic_unbounded,
                    max_pages=args.max_pages,
                )
            )
        finally:
            doc.close()

    payload = json.dumps({"documents": reports}, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.write_text(payload, encoding="utf-8")
    if args.json or args.out is None:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
