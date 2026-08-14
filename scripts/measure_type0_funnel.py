#!/usr/bin/env python3
"""Read-only Type0/CID coverage funnel (Task 12 P0-D acceptance).

Walks every text-showing operator of the given documents through the
P0-D evidence chain and reports the DUAL funnel the plan requires:

- **source-bindable**: direct single hex ``Tj`` on a Type0 font →
  within the production replay budget → outside any BDC/EMC
  marked-content wrapper → uniform-scaled (unrotated, unsheared) text
  matrix → residual default text state → capability (scope) accepted →
  source decodes → reverse encoding reproduces the source bytes →
  source CIDs pass the GID/glyph/width gates.  Marked-content and Tm
  survival are their own stages (Task 12 sealing record) because they
  are the corpus's dominant losses; the residual state conditions
  attribute first-fail ``state:*`` loss slugs;
- **replacement-encodable (self-proxy)**: the source's own text put back
  through the strict replacement gates (encode, glyph, width) — the
  corpus text's own encodability, before any user intent exists.

Plus an end-to-end sample: on an IN-MEMORY copy of each document, one
bindable show per page runs the real ``TieredCommitEngine`` prepare →
commit → save/reopen probe, with the reversed source string as the
replacement (same multiset of glyphs → an equal-advance Tier 0 case).
The original file is never written, and nothing textual is ever printed:
documents are positional (``doc_0``…), and every output value is a count
keyed by a stable stage or reason-code slug (plan §10 data policy).

Show weighting counts operators; char weighting counts decoded source
characters. The per-document sections ARE the document weighting.

Usage::

    python scripts/measure_type0_funnel.py <pdf> [more...] [--json]
    [--no-e2e]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.cid_fonts import CidCapabilityFailure  # noqa: E402
from model.text_commit.dto import CommitStatus  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import read_page_streams  # noqa: E402
from model.text_commit.plan import PlanRejection  # noqa: E402
from model.text_commit.replay import (  # noqa: E402
    DEFAULT_MAX_REPLAY_BYTES,
    replay_page_streams,
)
from scripts.wrapper_taxonomy import (  # noqa: E402
    VERDICT_ADMISSIBLE,
    classify_wrappers,
    show_verdict,
)

_STAGES = (
    "shows_total",
    "on_type0_font",
    "single_hex_tj",
    "within_replay_budget",
    "outside_marked_content",
    "uniform_trm",
    "default_text_state",
    "scope_accepted",
    "source_decoded",
    "source_bytes_reproduced",
    "source_gid_glyph_ok",
    "source_bindable",
    "replacement_encodable_proxy",
)


def _residual_state_loss(show: object) -> str | None:
    """First failing residual default-state condition, as a stable
    ``state:*`` loss slug — or None when clear.  Marked-content and Tm
    uniformity are NOT here: they are their own funnel stages."""
    if getattr(show, "render_mode", 1) != 0:
        return "state:render_mode"
    if getattr(show, "rise", 1.0) != 0.0:
        return "state:rise"
    if getattr(show, "hscale", 0.0) != 100.0:
        return "state:hscale"
    if not getattr(show, "in_bt", False):
        return "state:not_in_bt"
    if not getattr(show, "origin_reliable", False):
        return "state:origin_unreliable"
    return None


def funnel_document(doc: fitz.Document, *, run_e2e: bool) -> dict[str, object]:
    registry = DocumentFontRegistry(doc)
    shows_counter: Counter[str] = Counter()
    chars_counter: Counter[str] = Counter()
    loss_reasons: Counter[str] = Counter()
    # Task 13 P1 census: taxonomy of the wrappers behind the
    # state:marked_content_wrapper loss, aggregate slugs only (plan §10).
    census_wrapper_classes: Counter[str] = Counter()
    census_show_verdicts: Counter[str] = Counter()
    census_char_verdicts: Counter[str] = Counter()
    census_stack_depth: Counter[str] = Counter()
    census_overlap: Counter[str] = Counter()
    e2e = {
        "pages_attempted": 0,
        "prepared": 0,
        "committed": 0,
        "reopen_extraction_ok": 0,
    }
    e2e_reject_reasons: Counter[str] = Counter()

    for page_index in range(doc.page_count):
        page = doc[page_index]
        streams = read_page_streams(doc, page)
        total_bytes = sum(len(data) for _, data in streams)
        # Diagnostics enumerate every show (audit_tier_coverage precedent);
        # the production budget is reported as its own funnel stage.
        replay = replay_page_streams(streams, max_decoded_bytes=None)
        if replay.malformed:
            # A partially-replayed page contributes truncated counts —
            # make that visible instead of silently folding it in.
            loss_reasons["page_replay_malformed"] += 1
        within_budget = total_bytes <= DEFAULT_MAX_REPLAY_BYTES
        page_bindable: list[tuple[object, str]] = []
        wrapper_classes = classify_wrappers(doc, page, replay)
        page_counted_wrappers: set[int] = set()

        for show in replay.shows:
            shows_counter["shows_total"] += 1
            if show.font_resource is None:
                continue
            capability = registry.capability(page, show.font_resource)
            if capability is None or capability.subtype != "Type0":
                continue
            shows_counter["on_type0_font"] += 1
            # Hex-only, mirroring the production plan gate (the locked v1
            # scope refuses literal-string Type0 operands).
            if show.operator != "Tj" or show.string_kind != "hex":
                loss_reasons["not_single_hex_tj"] += 1
                continue
            shows_counter["single_hex_tj"] += 1
            if not within_budget:
                loss_reasons["content_stream_too_large_for_safe_replay"] += 1
                continue
            shows_counter["within_replay_budget"] += 1
            if getattr(show, "mc_depth", 1) != 0:
                loss_reasons["state:marked_content_wrapper"] += 1
                verdict = show_verdict(show, wrapper_classes, replay)
                census_show_verdicts[verdict] += 1
                # 2 bytes per CID across the whole v1 scope — cheap,
                # decode-free char weighting for the gated population
                census_char_verdicts[verdict] += len(show.decoded_bytes) // 2
                census_stack_depth[str(len(show.mc_stack))] += 1
                for wrapper_id in show.mc_stack:
                    if wrapper_id not in page_counted_wrappers:
                        page_counted_wrappers.add(wrapper_id)
                        census_wrapper_classes[wrapper_classes[wrapper_id]] += 1
                if (
                    verdict == VERDICT_ADMISSIBLE
                    and getattr(show, "trm_uniform_scaled", False)
                    and _residual_state_loss(show) is None
                ):
                    census_overlap["admissible_uniform_trm_default_state"] += 1
                continue
            shows_counter["outside_marked_content"] += 1
            if not getattr(show, "trm_uniform_scaled", False):
                loss_reasons["state:trm_not_uniform_scaled"] += 1
                continue
            shows_counter["uniform_trm"] += 1
            residual_loss = _residual_state_loss(show)
            if residual_loss is not None:
                loss_reasons[residual_loss] += 1
                continue
            shows_counter["default_text_state"] += 1
            if capability.cid is None:
                loss_reasons[
                    capability.tier0_reject_reason or "capability_unavailable"
                ] += 1
                continue
            shows_counter["scope_accepted"] += 1
            cid = capability.cid
            decoded = cid.decode_show_bytes(show.decoded_bytes)
            if isinstance(decoded, CidCapabilityFailure):
                loss_reasons[decoded.reason] += 1
                continue
            shows_counter["source_decoded"] += 1
            chars_counter["source_decoded"] += len(decoded)
            reproduced = cid.encode_first_wins(decoded)
            if (
                isinstance(reproduced, CidCapabilityFailure)
                or reproduced != show.decoded_bytes
            ):
                loss_reasons["type0_source_bytes_not_reproduced"] += 1
                continue
            shows_counter["source_bytes_reproduced"] += 1
            source_cids = tuple(
                int.from_bytes(show.decoded_bytes[i : i + 2], "big")
                for i in range(0, len(show.decoded_bytes), 2)
            )
            glyph_failure = cid.glyph_gate(source_cids, decoded)
            if glyph_failure is not None:
                loss_reasons[glyph_failure.reason] += 1
                continue
            shows_counter["source_gid_glyph_ok"] += 1
            shows_counter["source_bindable"] += 1
            chars_counter["source_bindable"] += len(decoded)

            strict = cid.encode_strict(decoded)
            if isinstance(strict, CidCapabilityFailure):
                loss_reasons[f"proxy:{strict.reason}"] += 1
                continue
            proxy_glyphs = cid.glyph_gate(strict, decoded)
            if proxy_glyphs is not None:
                loss_reasons[f"proxy:{proxy_glyphs.reason}"] += 1
                continue
            shows_counter["replacement_encodable_proxy"] += 1
            chars_counter["replacement_encodable_proxy"] += len(decoded)
            page_bindable.append((show, decoded))

        if run_e2e and page_bindable:
            _run_e2e_sample(
                doc, page_index, page_bindable, e2e, e2e_reject_reasons
            )

    return {
        "pages": doc.page_count,
        "funnel_shows": {stage: shows_counter[stage] for stage in _STAGES},
        "funnel_chars": dict(sorted(chars_counter.items())),
        "loss_reasons": dict(sorted(loss_reasons.items())),
        "mc_census": {
            "wrapper_classes": dict(sorted(census_wrapper_classes.items())),
            "show_verdicts": dict(sorted(census_show_verdicts.items())),
            "char_verdicts": dict(sorted(census_char_verdicts.items())),
            "stack_depth": dict(sorted(census_stack_depth.items())),
            "overlap": dict(sorted(census_overlap.items())),
        },
        "e2e_sample": e2e,
        "e2e_reject_reasons": dict(sorted(e2e_reject_reasons.items())),
    }


def _run_e2e_sample(
    doc: fitz.Document,
    page_index: int,
    bindable: list[tuple[object, str]],
    e2e: dict[str, int],
    reject_reasons: Counter[str],
) -> None:
    """One real prepare→commit→reopen per page, on an in-memory copy."""
    candidate = next(
        (
            (show, text)
            for show, text in bindable
            if text[::-1] != text
        ),
        None,
    )
    if candidate is None:
        return
    _, target_text = candidate
    replacement_text = target_text[::-1]
    e2e["pages_attempted"] += 1

    copy = fitz.open(stream=doc.tobytes(), filetype="pdf")
    try:
        engine = TieredCommitEngine(copy, max_tier=1)
        page = copy[page_index]
        prepared = engine.prepare(
            page,
            target_text=target_text,
            replacement_text=replacement_text,
            expected_origin=None,
        )
        if isinstance(prepared, PlanRejection):
            reject_reasons[f"prepare:{prepared.reason}"] += 1
            return
        e2e["prepared"] += 1
        outcome = engine.commit(prepared)
        if outcome.status is not CommitStatus.COMMITTED:
            # CommitOutcome has no .reason field — the fallback chain's
            # last entry carries the failure attribution when present.
            label = (
                outcome.fallback_chain[-1]
                if outcome.fallback_chain
                else outcome.status.value
            )
            reject_reasons[f"commit:{label}"] += 1
            return
        e2e["committed"] += 1
        reopened = fitz.open(stream=copy.tobytes(), filetype="pdf")
        try:
            extracted = "".join(reopened[page_index].get_text().split())
            if replacement_text.replace(" ", "") in extracted:
                e2e["reopen_extraction_ok"] += 1
            else:
                reject_reasons["reopen:extraction_mismatch"] += 1
        finally:
            reopened.close()
    finally:
        copy.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="PDF files")
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    parser.add_argument(
        "--no-e2e", action="store_true", help="skip the per-page commit sample"
    )
    args = parser.parse_args(argv)

    fitz.TOOLS.mupdf_display_errors(False)
    report: dict[str, object] = {}
    for index, path in enumerate(args.paths):
        doc = fitz.open(path)
        try:
            report[f"doc_{index}"] = funnel_document(
                doc, run_e2e=not args.no_e2e
            )
        finally:
            doc.close()
    print(json.dumps(report, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
