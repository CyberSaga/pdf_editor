"""Shared page selection utilities for preview and print submission."""

from __future__ import annotations

from typing import List

from .pdf_renderer import PDFRenderer

_PAGE_SUBSET_VALUES = {"all", "odd", "even"}


def normalize_page_subset(value: str | None) -> str:
    subset = (value or "all").strip().lower()
    return subset if subset in _PAGE_SUBSET_VALUES else "all"


def resolve_page_indices(
    total_pages: int,
    page_ranges: str | None,
    page_subset: str | None = "all",
    reverse_order: bool = False,
) -> List[int]:
    """
    Resolve final 0-based page indices after applying:
    1) page range parsing
    2) odd/even subset filtering
    3) reverse ordering
    """
    base = PDFRenderer.parse_page_ranges(page_ranges, total_pages)
    subset = normalize_page_subset(page_subset)

    if subset == "odd":
        base = [idx for idx in base if (idx + 1) % 2 == 1]
    elif subset == "even":
        base = [idx for idx in base if (idx + 1) % 2 == 0]

    if reverse_order:
        base = list(reversed(base))
    return base

