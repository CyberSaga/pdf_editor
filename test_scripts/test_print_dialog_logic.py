# -*- coding: utf-8 -*-
"""Logic checks for unified print dialog pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.printing.base_driver import PrintJobOptions
from src.printing.layout import compute_target_draw_rect
from src.printing.page_selection import resolve_page_indices


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run() -> int:
    # page ranges + odd/even + reverse share logic
    indices = resolve_page_indices(
        total_pages=10,
        page_ranges="1,3,5-8",
        page_subset="odd",
        reverse_order=False,
    )
    _assert(indices == [0, 2, 4, 6], f"unexpected odd subset result: {indices}")

    indices_reversed = resolve_page_indices(
        total_pages=10,
        page_ranges="1,3,5-8",
        page_subset="odd",
        reverse_order=True,
    )
    _assert(
        indices_reversed == [6, 4, 2, 0],
        f"unexpected reverse result: {indices_reversed}",
    )

    # scale rect behavior
    fit_rect = compute_target_draw_rect(
        target_width=600,
        target_height=800,
        source_width=1200,
        source_height=600,
        scale_mode="fit",
        scale_percent=100,
    )
    _assert(abs(fit_rect[2] - 600) < 1e-6, "fit width should be 600")
    _assert(abs(fit_rect[3] - 300) < 1e-6, "fit height should be 300")

    actual_rect = compute_target_draw_rect(
        target_width=600,
        target_height=800,
        source_width=300,
        source_height=200,
        scale_mode="actual",
        scale_percent=100,
    )
    _assert(abs(actual_rect[2] - 300) < 1e-6, "actual width should be source width")
    _assert(abs(actual_rect[3] - 200) < 1e-6, "actual height should be source height")

    custom_rect = compute_target_draw_rect(
        target_width=600,
        target_height=800,
        source_width=300,
        source_height=200,
        scale_mode="custom",
        scale_percent=150,
    )
    _assert(abs(custom_rect[2] - 450) < 1e-6, "custom width should be 150%")
    _assert(abs(custom_rect[3] - 300) < 1e-6, "custom height should be 150%")

    # PrintJobOptions normalization
    opts = PrintJobOptions(
        scale_mode="custom",
        scale_percent=15,  # clamp to 25
        page_subset="ODD",
        reverse_order=1,
        paper_size="A4",
        orientation="LANDSCAPE",
    ).normalized()
    _assert(opts.scale_mode == "custom", f"scale_mode mismatch: {opts.scale_mode}")
    _assert(opts.scale_percent == 25, f"scale_percent mismatch: {opts.scale_percent}")
    _assert(opts.page_subset == "odd", f"page_subset mismatch: {opts.page_subset}")
    _assert(opts.reverse_order is True, "reverse_order should be True")
    _assert(opts.paper_size == "a4", f"paper_size mismatch: {opts.paper_size}")
    _assert(opts.orientation == "landscape", f"orientation mismatch: {opts.orientation}")

    print("[PASS] unified print dialog logic checks")
    return 0


if __name__ == "__main__":
    sys.exit(run())
