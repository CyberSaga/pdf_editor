"""P4-B2 commit 7: the evidence-cost benchmark's shape (measurement itself
is run manually on the sealed corpus and recorded in the spike plan)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_p4b2_painter_evidence import (  # noqa: E402
    BUCKET_KEYS,
    _percentiles,
    benchmark_document,
)
from test_scripts.test_text_commit_duplicate_painter_gate import (  # noqa: E402
    _build_second_show_doc,
)


def test_percentiles_are_nearest_rank_with_ceil() -> None:
    stats = _percentiles([1.0, 2.0, 3.0, 4.0, 100.0])
    assert stats["n"] == 5
    assert stats["p50_ms"] == 3.0
    assert stats["p95_ms"] == 100.0
    assert stats["p99_ms"] == 100.0
    assert stats["min_ms"] == 1.0 and stats["max_ms"] == 100.0
    assert _percentiles([]) == {"n": 0}


def test_benchmark_builds_once_per_page_per_repeat_and_is_aggregate_only() -> None:
    fixture, _ = _build_second_show_doc(offset=1.0)
    try:
        report = benchmark_document(fixture.doc, repeat=2)
    finally:
        fixture.doc.close()
    assert report["pages"] == 1
    assert report["shows"] == 2
    assert report["builds"] == 2
    assert report["builds_equal_pages_times_repeat"] is True
    assert set(report["by_show_bucket"]) == set(BUCKET_KEYS)
    assert report["cold"]["n"] == 2 and report["warm"]["n"] == 2 and report["o1_only"]["n"] == 2
    # Warm (oracle cached) and O1-only never exceed the cold cost.
    assert report["warm"]["min_ms"] <= report["cold"]["max_ms"]
    assert report["o1_only"]["min_ms"] <= report["cold"]["max_ms"]
    assert all(key.isascii() for key in report["counters"])
    assert all(isinstance(value, int) for value in report["counters"].values())
