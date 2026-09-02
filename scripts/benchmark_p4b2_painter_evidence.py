#!/usr/bin/env python3
"""P4-B2 perf: cost of building per-page painter evidence (Stage F).

Times :func:`scripts.painter_evidence.build_page_painter_evidence` — one
derotated display list, one glyph-device run, one bbox-device run, the TJ
re-lex, the cursor replay, the window-search join and the per-glyph O1/O2
bounds — over every page of the given documents, cold (fresh oracle cache)
and warm (oracle cache kept), plus an O1-only variant (no fontTools) that
approximates what a production slice would pay.

Output is aggregate only: nearest-rank percentiles in milliseconds, page
and show counts, and the evidence counters (closed slugs).  Nothing
textual, no filenames.  Raw JSON goes to the gitignored ``benchmarks/``.

Usage::

    python scripts/benchmark_p4b2_painter_evidence.py <pdf> [more...]
        [--repeat N] [--json]
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import read_page_streams  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402
from scripts.painter_evidence import build_page_painter_evidence  # noqa: E402

BUCKET_KEYS = ("shows_lt_50", "shows_50_199", "shows_200_499", "shows_ge_500")


def _percentiles(samples_ms: list[float]) -> dict[str, float | int]:
    """Nearest-rank percentiles (``benchmark_p3c_postprepare_latency``
    precedent: ``ceil`` never lands one order statistic low)."""
    ordered = sorted(samples_ms)
    n = len(ordered)
    if n == 0:
        return {"n": 0}

    def rank(fraction: float) -> float:
        return ordered[min(n - 1, max(0, math.ceil(n * fraction) - 1))]

    return {
        "n": n,
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(rank(0.95), 3),
        "p99_ms": round(rank(0.99), 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
    }


def _bucket(show_count: int) -> str:
    if show_count < 50:
        return "shows_lt_50"
    if show_count < 200:
        return "shows_50_199"
    if show_count < 500:
        return "shows_200_499"
    return "shows_ge_500"


def benchmark_document(
    doc: fitz.Document, *, repeat: int = 1
) -> dict[str, object]:
    registry = DocumentFontRegistry(doc)
    cold: list[float] = []
    warm: list[float] = []
    o1_only: list[float] = []
    by_bucket: dict[str, list[float]] = {key: [] for key in BUCKET_KEYS}
    counters: Counter[str] = Counter()
    pages = 0
    shows = 0
    tj_shows = 0
    builds = 0
    warm_oracles: dict = {}
    for page_index in range(doc.page_count):
        page = doc[page_index]
        try:
            streams = read_page_streams(doc, page)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            continue
        replay = replay_page_streams(streams, max_decoded_bytes=None)
        pages += 1
        shows += len(replay.shows)
        tj_shows += sum(1 for show in replay.shows if show.operator == "TJ")
        capabilities = registry.page_capabilities(page)
        for _ in range(repeat):
            start = time.perf_counter()
            evidence = build_page_painter_evidence(
                doc, page, registry=registry, replay=replay, capabilities=capabilities, oracles={}
            )
            elapsed = (time.perf_counter() - start) * 1e3
            builds += evidence.builds
            counters.update(evidence.counters)
            evidence.release()
            cold.append(elapsed)
            by_bucket[_bucket(len(replay.shows))].append(elapsed)

            start = time.perf_counter()
            evidence = build_page_painter_evidence(
                doc,
                page,
                registry=registry,
                replay=replay,
                capabilities=capabilities,
                oracles=warm_oracles,
            )
            warm.append((time.perf_counter() - start) * 1e3)
            evidence.release()

            # O1-only: an oracle cache that answers "unavailable" for every
            # font skips fontTools entirely (device runs + join only).
            start = time.perf_counter()
            evidence = build_page_painter_evidence(
                doc,
                page,
                registry=registry,
                replay=replay,
                capabilities=capabilities,
                oracles={cap.font_xref: None for cap in capabilities.values()},
            )
            o1_only.append((time.perf_counter() - start) * 1e3)
            evidence.release()
    return {
        "pages": pages,
        "shows": shows,
        "tj_shows": tj_shows,
        "builds": builds,
        "builds_equal_pages_times_repeat": builds == pages * repeat,
        "cold": _percentiles(cold),
        "warm": _percentiles(warm),
        "o1_only": _percentiles(o1_only),
        "by_show_bucket": {key: _percentiles(values) for key, values in by_bucket.items()},
        "counters": dict(sorted(counters.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="PDF files (never echoed)")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--json", action="store_true", help="compact JSON")
    args = parser.parse_args(argv)
    fitz.TOOLS.mupdf_display_errors(False)
    report: dict[str, object] = {}
    for index, path in enumerate(args.paths):
        doc = fitz.open(path)
        try:
            report[f"doc_{index}"] = benchmark_document(doc, repeat=args.repeat)
        finally:
            doc.close()
    print(json.dumps(report, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
