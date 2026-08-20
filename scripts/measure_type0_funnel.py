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
from model.text_commit.marked_content import admit_show_wrappers  # noqa: E402
from model.text_commit.plan import PlanRejection  # noqa: E402
from model.text_commit.transforms import admission_verdict  # noqa: E402
from model.text_commit.replay import (  # noqa: E402
    DEFAULT_MAX_REPLAY_BYTES,
    replay_page_streams,
)
from scripts.trm_taxonomy import (  # noqa: E402
    ABS_SCALE_FLOOR,
    CARDINAL_DIRECTIONS,
    LOOSE_REL_TOL,
    SHAPE_UNIFORM_ROTATED,
    baseline_scale,
    classify_user_matrix,
    combined_linear,
    page_rotate_slug,
    visual_baseline_direction,
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
    "trm_rotated_admitted",
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


def _trm_census(
    show: object,
    page: fitz.Page,
    capability: object,
    user_shape: Counter[str],
    visual_direction: Counter[str],
    page_rotate: Counter[str],
    overlap: Counter[str],
    predicted: Counter[str],
    near_miss: Counter[str],
) -> tuple[bool, bool]:
    """Task 13 P2 census fold for ONE show reaching the TRM gate rotated.

    Read-only aggregation, slugs only.  The ``predicted`` chain runs the
    SAME downstream gates the funnel's main path runs, under BOTH
    candidate admission scopes (plan §3's any-uniform-rotation and the
    quarter-turn v1 candidate) — its terminal counts are the exact sets
    the Priority 2 implementation must newly admit.  ``near_miss``
    surfaces quarter turns written with rounded decimals that the strict
    tolerance misses (diagnostic only, never predicted).

    Returns ``(gate_member, downstream_member)`` for the quarter-turn v1
    scope — the SET-identity acceptance (predicted vs production
    admission) compares memberships in memory; only counts are ever
    emitted.
    """
    linear = combined_linear(show.tm, show.ctm)
    shape = classify_user_matrix(linear)
    user_shape[shape] += 1
    direction = visual_baseline_direction(page, linear)
    visual_direction[direction] += 1
    page_rotate[page_rotate_slug(getattr(page, "rotation", 0))] += 1
    overlap["wrapped_p1_admitted" if show.mc_stack else "never_wrapped"] += 1

    strict_uniform = shape == SHAPE_UNIFORM_ROTATED
    strict_cardinal = direction in CARDINAL_DIRECTIONS
    loose_uniform = (
        classify_user_matrix(linear, rel_tol=LOOSE_REL_TOL)
        == SHAPE_UNIFORM_ROTATED
    )
    loose_cardinal = (
        visual_baseline_direction(page, linear, rel_tol=LOOSE_REL_TOL)
        in CARDINAL_DIRECTIONS
    )
    if loose_uniform and not strict_uniform:
        near_miss["shape_uniform_only_at_1e3"] += 1
    if loose_cardinal and not strict_cardinal:
        near_miss["direction_cardinal_only_at_1e3"] += 1
    if (loose_uniform and loose_cardinal) and not (
        strict_uniform and strict_cardinal
    ):
        near_miss["quarter_turn_only_at_1e3"] += 1

    # Production's replay floor is ABSOLUTE (a <= _EPS): a degenerate
    # scale passing the relative shape gates must never be predicted.
    if not strict_uniform or baseline_scale(linear) <= ABS_SCALE_FLOOR:
        return (False, False)
    gate_member = strict_cardinal
    predicted["any_uniform_rotation"] += 1
    if strict_cardinal:
        predicted["quarter_turn_uniform"] += 1
    if _residual_state_loss(show) is not None:
        return (gate_member, False)
    predicted["and_default_state"] += 1
    cid = getattr(capability, "cid", None)
    if cid is None:
        return (gate_member, False)
    predicted["and_scope_accepted"] += 1
    decoded = cid.decode_show_bytes(show.decoded_bytes)
    if isinstance(decoded, CidCapabilityFailure):
        return (gate_member, False)
    predicted["and_source_decoded"] += 1
    reproduced = cid.encode_first_wins(decoded)
    if (
        isinstance(reproduced, CidCapabilityFailure)
        or reproduced != show.decoded_bytes
    ):
        return (gate_member, False)
    predicted["and_bytes_reproduced"] += 1
    source_cids = tuple(
        int.from_bytes(show.decoded_bytes[i : i + 2], "big")
        for i in range(0, len(show.decoded_bytes), 2)
    )
    if cid.glyph_gate(source_cids, decoded) is not None:
        return (gate_member, False)
    predicted["predicted_source_bindable"] += 1
    predicted["predicted_source_bindable_chars"] += len(decoded)
    if strict_cardinal:
        predicted["predicted_source_bindable_quarter_turn"] += 1
    strict = cid.encode_strict(decoded)
    if isinstance(strict, CidCapabilityFailure):
        return (gate_member, False)
    if cid.glyph_gate(strict, decoded) is not None:
        return (gate_member, False)
    predicted["predicted_replacement_encodable"] += 1
    if strict_cardinal:
        predicted["predicted_replacement_encodable_quarter_turn"] += 1
    return (gate_member, gate_member)


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
    # Task 13 P2 census: matrix taxonomy of the shows dying at the TRM
    # gate below — aggregate slugs only (plan §10), no admission change.
    trm_user_shape: Counter[str] = Counter()
    trm_visual_direction: Counter[str] = Counter()
    trm_page_rotate: Counter[str] = Counter()
    trm_overlap: Counter[str] = Counter()
    trm_predicted: Counter[str] = Counter()
    trm_near_miss: Counter[str] = Counter()
    # Task 13 P2 acceptance: predicted vs production admission compared as
    # SETS (identity keys stay in memory; the report emits counts and the
    # symmetric difference only — never a key).
    trm_predicted_gate: set[tuple[int, int, int]] = set()
    trm_predicted_downstream: set[tuple[int, int, int]] = set()
    trm_production_gate: set[tuple[int, int, int]] = set()
    trm_production_downstream: set[tuple[int, int, int]] = set()
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
            if getattr(show, "mc_depth", 1) != 0 or show.mc_stack:
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
                # Task 13 P1: the gate now mirrors the PRODUCTION admission
                # (boundary guard included); a wrapped show that fails it is
                # attributed to its stable MC_* code — the old blanket
                # "state:marked_content_wrapper" slug is retired with the
                # blanket gate itself.
                wrappers = tuple(
                    replay.mc_wrappers[i]
                    for i in show.mc_stack
                    if 0 <= i < len(replay.mc_wrappers)
                )
                rejection = admit_show_wrappers(
                    doc,
                    page,
                    show,
                    wrappers=wrappers,
                    emc_underflows=replay.mc_emc_underflows,
                )
                if rejection is not None:
                    loss_reasons[rejection.reason] += 1
                    continue
            shows_counter["outside_marked_content"] += 1
            trm_rotated_candidate = not getattr(
                show, "trm_uniform_scaled", False
            )
            if trm_rotated_candidate:
                # Census population unchanged: exactly the shows the
                # pre-P2 blanket gate killed.  The gate itself now mirrors
                # the PRODUCTION quarter-turn admission; a refused show is
                # attributed to its stable trm_* code — the old blanket
                # "state:trm_not_uniform_scaled" slug is retired with the
                # blanket gate itself (same pattern as P1's retirement of
                # "state:marked_content_wrapper").
                show_key = (page_index, show.stream_xref, show.seq)
                predicted_gate, predicted_downstream = _trm_census(
                    show,
                    page,
                    capability,
                    trm_user_shape,
                    trm_visual_direction,
                    trm_page_rotate,
                    trm_overlap,
                    trm_predicted,
                    trm_near_miss,
                )
                if predicted_gate:
                    trm_predicted_gate.add(show_key)
                if predicted_downstream:
                    trm_predicted_downstream.add(show_key)
                verdict = admission_verdict(page, show.tm, show.ctm)
                if verdict.reject_reason is not None:
                    loss_reasons[f"state:{verdict.reject_reason}"] += 1
                    continue
                trm_production_gate.add(show_key)
                shows_counter["trm_rotated_admitted"] += 1
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
            if trm_rotated_candidate:
                trm_production_downstream.add(
                    (page_index, show.stream_xref, show.seq)
                )
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
        "trm_census": {
            "user_shape": dict(sorted(trm_user_shape.items())),
            "visual_direction": dict(sorted(trm_visual_direction.items())),
            "page_rotate": dict(sorted(trm_page_rotate.items())),
            "overlap": dict(sorted(trm_overlap.items())),
            "predicted": dict(sorted(trm_predicted.items())),
            "near_miss": dict(sorted(trm_near_miss.items())),
            # SET-identity acceptance (Task 13 P2): counts and symmetric
            # differences only — the membership keys never leave memory.
            "acceptance": {
                "predicted_gate": len(trm_predicted_gate),
                "production_gate": len(trm_production_gate),
                "gate_symmetric_difference": len(
                    trm_predicted_gate ^ trm_production_gate
                ),
                "gate_membership_exact": (
                    trm_predicted_gate == trm_production_gate
                ),
                "predicted_downstream": len(trm_predicted_downstream),
                "production_downstream": len(trm_production_downstream),
                "downstream_symmetric_difference": len(
                    trm_predicted_downstream ^ trm_production_downstream
                ),
                "downstream_membership_exact": (
                    trm_predicted_downstream == trm_production_downstream
                ),
            },
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
