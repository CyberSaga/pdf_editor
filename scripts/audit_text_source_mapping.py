#!/usr/bin/env python3
"""Read-only audit: how much visible text binds to source operators.

For every rawdict span in every corpus PDF, attempt the Task 3 source
binding and tally outcomes ("bound" or a stable RejectReason code).  This
is the empirical coverage metric for the V2 tiered commit engine.

Privacy: the report contains only file stem, page counts, and outcome
tallies — never document text, raw streams, absolute paths, or
device-specific metadata.

Usage::

    python scripts/audit_text_source_mapping.py [--corpus DIR] [--pages N]

Default corpus: ``test_corpus/fidelity`` (generated on the fly if absent).
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.inspect import SourceSpanBinding, bind_source_text  # noqa: E402


def audit_page(doc: fitz.Document, page: fitz.Page) -> Counter:
    counts: Counter = Counter()
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if not text.strip():
                    continue
                binding = bind_source_text(
                    doc,
                    page,
                    target_text=text,
                    expected_origin=tuple(span["origin"]),
                )
                if isinstance(binding, SourceSpanBinding):
                    counts["bound"] += 1
                else:
                    counts[binding.reason] += 1
    return counts


def audit_document(doc: fitz.Document, max_pages: int = 5) -> Counter:
    counts: Counter = Counter()
    for page_idx in range(min(doc.page_count, max_pages)):
        counts += audit_page(doc, doc[page_idx])
    return counts


def _format_counts(counts: Counter) -> str:
    if not counts:
        return "no text spans"
    return " ".join(f"{key}={counts[key]}" for key in sorted(counts))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        default="test_corpus/fidelity",
        help="directory of corpus PDFs (generated on the fly if absent)",
    )
    parser.add_argument(
        "--pages", type=int, default=5, help="max pages audited per document"
    )
    args = parser.parse_args(argv)

    corpus_dir = Path(args.corpus)
    if not corpus_dir.is_dir() or not any(corpus_dir.glob("*.pdf")):
        from scripts.build_fidelity_corpus import build_corpus

        build_corpus(corpus_dir)

    totals: Counter = Counter()
    for pdf_path in sorted(corpus_dir.glob("*.pdf")):
        try:
            doc = fitz.open(str(pdf_path))
        except (RuntimeError, ValueError) as exc:
            print(f"  {pdf_path.stem}: unreadable ({type(exc).__name__})")
            continue
        counts = audit_document(doc, max_pages=args.pages)
        doc.close()
        totals += counts
        print(f"  {pdf_path.stem}: {_format_counts(counts)}")

    spans = sum(totals.values())
    bound = totals.get("bound", 0)
    print(f"\ntotal spans={spans} {_format_counts(totals)}")
    if spans:
        print(f"bound: {bound}/{spans} ({100.0 * bound / spans:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
