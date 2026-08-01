#!/usr/bin/env python3
"""Read-only audit: per-page Tier 0 / Tier 1 / legacy show-op coverage.

Replays every page's content streams and classifies each text-showing
operator into ``tier0_eligible`` (would pass every structural Tier 0 gate
``model/text_commit/plan.py`` checks, independent of any specific
replacement text), ``tier1_candidate`` (font passes the Task 10d
widths-based gates and the Task 10e glyph proxy, but is not a single-string
``Tj``, or some other Tier 0-only restriction), or
``legacy_only``. Never mutates the document -- no scratch commit, no
``prepare_tier0_plan`` call -- and never emits document text, extracted
strings, or file paths: only counts, booleans, and stable
:class:`~model.text_commit.dto.RejectReason` codes.

Also flags pages whose content stream(s) are shared with another page
(``shared_content_stream``): mutating a shared stream in place would leak
across pages, a hazard called out for the Tier 1 transplant strategy.

Usage::

    python scripts/audit_tier_coverage.py <pdf> [--password PW] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry, FontCapability  # noqa: E402
from model.text_commit.inspect import read_page_streams  # noqa: E402
from model.text_commit.replay import ShowOp, replay_page_streams  # noqa: E402

TIER0_ELIGIBLE = "tier0_eligible"
TIER1_CANDIDATE = "tier1_candidate"
LEGACY_ONLY = "legacy_only"


def _classify_show(
    show: ShowOp, capability: FontCapability | None
) -> tuple[str, str | None]:
    """Structural-only classification (no replacement text is known here)."""
    unsupported_state = (
        show.render_mode != 0
        or show.rise != 0.0
        or show.hscale != 100.0
        or show.mc_depth != 0
        or not show.in_bt
        or not show.trm_uniform_scaled
    )
    single_string_tj = show.operator == "Tj" and show.string_kind in (
        "literal",
        "hex",
    )

    tier0_eligible = (
        single_string_tj
        and not unsupported_state
        and show.origin_reliable
        and capability is not None
        and capability.tier0_reject_reason is None
        and (capability.face is not None or capability.ascii_repertoire_attested)
    )
    if tier0_eligible:
        return TIER0_ELIGIBLE, None

    tier1_candidate = (
        show.operator in ("Tj", "TJ")
        and not unsupported_state
        and show.origin_reliable
        and capability is not None
        and capability.tier0_reject_reason is None
        and (capability.face is not None or capability.ascii_repertoire_attested)
    )

    if unsupported_state:
        reason = RejectReason.UNSUPPORTED_TEXT_STATE
    elif not show.origin_reliable:
        reason = RejectReason.UNTRACKED_ADVANCE
    elif capability is None:
        reason = RejectReason.FONT_FACE_UNAVAILABLE
    elif capability.tier0_reject_reason is not None:
        reason = capability.tier0_reject_reason
    elif not single_string_tj:
        reason = RejectReason.NOT_SINGLE_LITERAL_TJ
    else:
        reason = RejectReason.UNSUPPORTED_TEXT_STATE

    return (TIER1_CANDIDATE if tier1_candidate else LEGACY_ONLY), reason


def _stream_page_owners(doc: fitz.Document) -> dict[int, set[int]]:
    owners: dict[int, set[int]] = defaultdict(set)
    for page_idx in range(doc.page_count):
        for xref in doc[page_idx].get_contents():
            owners[xref].add(page_idx)
    return owners


def audit_page(
    doc: fitz.Document,
    page: fitz.Page,
    registry: DocumentFontRegistry,
    stream_owners: dict[int, set[int]],
) -> dict[str, object]:
    streams = read_page_streams(doc, page)
    replay = replay_page_streams(streams)

    counts: Counter[str] = Counter()
    reject_reasons: Counter[str] = Counter()
    for show in replay.shows:
        capability = (
            registry.capability(page, show.font_resource)
            if show.font_resource is not None
            else None
        )
        tier, reason = _classify_show(show, capability)
        counts[tier] += 1
        if reason is not None:
            reject_reasons[reason] += 1

    shared = any(len(stream_owners[xref]) > 1 for xref in page.get_contents())

    return {
        "page": page.number + 1,
        "shows_total": len(replay.shows),
        "tier0_eligible": counts[TIER0_ELIGIBLE],
        "tier1_candidate": counts[TIER1_CANDIDATE],
        "legacy_only": counts[LEGACY_ONLY],
        "reject_reason_counts": dict(sorted(reject_reasons.items())),
        "shared_content_stream": shared,
    }


def audit_document(doc: fitz.Document) -> list[dict[str, object]]:
    registry = DocumentFontRegistry(doc)
    stream_owners = _stream_page_owners(doc)
    return [
        audit_page(doc, doc[page_idx], registry, stream_owners)
        for page_idx in range(doc.page_count)
    ]


def _format_row(row: dict[str, object]) -> str:
    reasons = row["reject_reason_counts"]
    reasons_str = (
        ",".join(f"{k}={v}" for k, v in reasons.items()) if reasons else "-"  # type: ignore[union-attr]
    )
    return (
        f"page={row['page']} shows={row['shows_total']} "
        f"tier0={row['tier0_eligible']} tier1={row['tier1_candidate']} "
        f"legacy={row['legacy_only']} shared_stream={row['shared_content_stream']} "
        f"reasons=[{reasons_str}]"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="path to the PDF to audit")
    parser.add_argument("--password", default=None, help="owner/user password")
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON rows"
    )
    args = parser.parse_args(argv)

    doc = fitz.open(args.pdf)
    try:
        if doc.needs_pass:
            if not args.password or doc.authenticate(args.password) == 0:
                print("error: password required or incorrect", file=sys.stderr)
                return 2

        rows = audit_document(doc)
    finally:
        doc.close()

    if args.json:
        print(json.dumps(rows))
    else:
        for row in rows:
            print(_format_row(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
