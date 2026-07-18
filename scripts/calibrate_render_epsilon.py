#!/usr/bin/env python3
"""Measure repeated-render pixel noise to calibrate ε for V1d render-diff.

Renders each corpus PDF page N times at a fixed DPI and computes the
per-pixel absolute difference between the baseline (first render) and
every subsequent render.  The output is a JSON report with per-case
statistics and a recommended integer ε (the max observed noise + safety
margin), suitable for hard-coding into ``verify_commit_fidelity.py``.

Usage::

    python scripts/calibrate_render_epsilon.py [CORPUS_DIR] [--output FILE]
                                               [--iterations N] [--dpi D]

Default corpus: ``test_corpus/fidelity/``
Default output: stdout (JSON)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import fitz
import numpy as np

DEFAULT_DPI = 96
DEFAULT_ITERATIONS = 30


@dataclass(frozen=True)
class RenderNoiseStats:
    max_abs_diff: int
    mean_abs_diff: float
    p99_abs_diff: int
    p999_abs_diff: int
    iterations: int
    dpi: int
    pixel_count: int


def _render_page(doc: fitz.Document, page_num: int, dpi: int) -> np.ndarray:
    page = doc[page_num]
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )


def measure_page_noise(
    doc: fitz.Document,
    page_num: int = 0,
    iterations: int = DEFAULT_ITERATIONS,
    dpi: int = DEFAULT_DPI,
) -> RenderNoiseStats:
    if iterations < 2:
        raise ValueError("iterations must be >= 2 (need at least one comparison)")

    baseline = _render_page(doc, page_num, dpi)
    pixel_count = baseline.shape[0] * baseline.shape[1]

    all_diffs: list[np.ndarray] = []
    for _ in range(iterations - 1):
        rendered = _render_page(doc, page_num, dpi)
        diff = np.abs(rendered.astype(np.int16) - baseline.astype(np.int16))
        all_diffs.append(diff)

    if not all_diffs:
        return RenderNoiseStats(
            max_abs_diff=0,
            mean_abs_diff=0.0,
            p99_abs_diff=0,
            p999_abs_diff=0,
            iterations=iterations,
            dpi=dpi,
            pixel_count=pixel_count,
        )

    stacked = np.concatenate([d.ravel() for d in all_diffs])

    return RenderNoiseStats(
        max_abs_diff=int(np.max(stacked)),
        mean_abs_diff=float(np.mean(stacked)),
        p99_abs_diff=int(np.percentile(stacked, 99)),
        p999_abs_diff=int(np.percentile(stacked, 99.9)),
        iterations=iterations,
        dpi=dpi,
        pixel_count=pixel_count,
    )


def calibrate_corpus(
    corpus_dir: Path,
    iterations: int = DEFAULT_ITERATIONS,
    dpi: int = DEFAULT_DPI,
) -> dict[str, RenderNoiseStats]:
    results: dict[str, RenderNoiseStats] = {}
    for pdf_path in sorted(corpus_dir.glob("*.pdf")):
        case_name = pdf_path.stem
        doc = fitz.open(str(pdf_path))
        try:
            stats = measure_page_noise(doc, page_num=0, iterations=iterations, dpi=dpi)
            results[case_name] = stats
        finally:
            doc.close()
    return results


def recommended_epsilon(report: dict[str, RenderNoiseStats]) -> int:
    if not report:
        return 0
    max_noise = max(s.max_abs_diff for s in report.values())
    margin = max(1, max_noise)
    return max_noise + margin


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate render-diff ε")
    parser.add_argument(
        "corpus_dir",
        nargs="?",
        default="test_corpus/fidelity",
        help="directory containing corpus PDFs",
    )
    parser.add_argument("--output", "-o", help="write JSON report to file")
    parser.add_argument(
        "--iterations", "-n", type=int, default=DEFAULT_ITERATIONS,
        help=f"render repetitions per page (default {DEFAULT_ITERATIONS})",
    )
    parser.add_argument(
        "--dpi", type=int, default=DEFAULT_DPI,
        help=f"render resolution (default {DEFAULT_DPI})",
    )
    args = parser.parse_args(argv)

    corpus_path = Path(args.corpus_dir)
    if not corpus_path.is_dir():
        print(f"error: corpus directory not found: {corpus_path}", file=sys.stderr)
        return 1

    report = calibrate_corpus(corpus_path, iterations=args.iterations, dpi=args.dpi)
    eps = recommended_epsilon(report)

    data = {
        "recommended_epsilon": eps,
        "dpi": args.dpi,
        "iterations": args.iterations,
        "cases": {name: asdict(stats) for name, stats in report.items()},
    }

    text = json.dumps(data, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"report written to {args.output}")
    else:
        print(text)

    print(f"\nrecommended ε = {eps}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
