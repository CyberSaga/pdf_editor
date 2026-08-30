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

Two read-only Task 14 sections sit beside that funnel.  The glyph-overlap
census records operator / horizontal-scale intersections plus an independent
all-gates vector, while the vocabulary counterfactual measures closed
replacement vocabularies without emitting document text or font identities.

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
from collections.abc import Callable
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.cid_fonts import (  # noqa: E402
    _MAX_TOUNICODE_RECORDS,
    CidCapabilityFailure,
    IdentityHCidCapability,
)
from model.text_commit.dto import CommitStatus  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import read_page_streams  # noqa: E402
from model.text_commit.marked_content import (  # noqa: E402
    CLASS_OC_LAYER_VISIBLE,
    admit_show_wrappers,
    splice_range_within_wrapper,
)
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
from scripts.type0_vocabulary import (  # noqa: E402
    VOCABULARIES,
    system_candidate_supplier,
)

GLYPH_OVERLAP_OPERATOR_CLASSES = (
    "single_hex_tj",
    "literal_tj",
    "tj_array",
    "quote_ops",
)
GLYPH_OVERLAP_HSCALE_CLASSES = (
    "hscale_default",
    "hscale_non_default",
)
GLYPH_OVERLAP_VERDICTS = (
    "cid_unavailable",
    "odd_byte_length",
    "source_undecodable",
    "glyph_ok",
    "type0_cid_out_of_map_range",
    "type0_gid_zero",
    "type0_gid_beyond_glyph_count",
    "type0_glyph_missing",
)
GLYPH_OVERLAP_REACH_CLASSES = (
    "glyph_present_no_tounicode_cid",
    "tounicode_cid_without_glyph",
    "tounicode_cid_with_glyph",
)
GLYPH_OVERLAP_SOLE_LOSS_CLASSES = (
    "all_gates_pass",
    "tj_array_only",
    "hscale_only",
    "tj_array_and_hscale_only",
    "other",
)
TOUNICODE_UNPARSEABLE_DETAILS = (
    "ToUnicode stream over the parse budget",
    "no bfchar or bfrange records",
    "malformed bfchar block",
    "bfchar record count disagrees with declaration",
    "bfchar source code is not 2 bytes",
    "bfchar destination is not valid UTF-16BE",
    "array-destination bfrange is outside the v1 grammar",
    "malformed bfrange block",
    "bfrange record count disagrees with declaration",
    "bfrange source codes are not 2 bytes",
    "bfrange low code exceeds high code",
    "bfrange destination is not a single Unicode scalar",
    "bfrange increments past the Unicode range",
    "ToUnicode record count over the parse budget",
    "ToUnicode is present but its stream is unreadable or empty",
)

VOCABULARY_BASE_BUCKETS = (
    "encodable_now",
    "type0_unicode_unmapped",
    "type0_tounicode_ambiguous",
    "type0_glyph_missing",
    "type0_gid_zero",
    "type0_gid_beyond_glyph_count",
    "type0_cid_out_of_map_range",
    "cid_unavailable",
)
AUGMENTABLE_VERDICTS = (
    "type0_unicode_unmapped",
    "type0_glyph_missing",
)
VOCABULARY_DERIVED_BUCKETS = (
    *(f"candidate_supply|{verdict}" for verdict in VOCABULARY_BASE_BUCKETS),
    "candidate_could_supply",
    "after_augmentation",
)
VOCABULARY_ALL_BUCKETS = (
    *VOCABULARY_BASE_BUCKETS,
    *VOCABULARY_DERIVED_BUCKETS,
)
VOCABULARY_WEIGHTINGS = (
    "font_weighted",
    "page_weighted",
    "show_weighted",
)


def _glyph_overlap_operator_class(show: object) -> str:
    """Closed operator taxonomy for the independent glyph census.

    ``tj_array`` measures glyph availability after replay has discarded kern
    numbers; it does not claim that the production byte binder accepts arrays.
    """
    operator = getattr(show, "operator", "")
    string_kind = getattr(show, "string_kind", "")
    if operator == "TJ":
        return "tj_array"
    if operator in ("'", '"'):
        return "quote_ops"
    if operator == "Tj" and string_kind == "hex":
        return "single_hex_tj"
    return "literal_tj"


def _glyph_overlap_verdict(
    show: object, cid: IdentityHCidCapability | None
) -> str:
    if cid is None:
        return "cid_unavailable"
    data = getattr(show, "decoded_bytes", b"")
    if len(data) % 2:
        return "odd_byte_length"
    decoded = cid.decode_show_bytes(data)
    if isinstance(decoded, CidCapabilityFailure):
        return "source_undecodable"
    source_cids = tuple(
        int.from_bytes(data[index : index + 2], "big")
        for index in range(0, len(data), 2)
    )
    failure = cid.glyph_gate(source_cids, decoded)
    return "glyph_ok" if failure is None else failure.reason


def _cid_has_outline(cid: IdentityHCidCapability, code: int) -> bool:
    gid = cid.gid_for(code)
    if isinstance(gid, CidCapabilityFailure) or gid == 0:
        return False
    if gid >= cid.glyphs.num_glyphs:
        return False
    length = cid.glyphs.glyph_data_length(gid)
    return length is not None and length > 0


def _record_font_glyph_reach(
    cid: IdentityHCidCapability, reach: Counter[str]
) -> None:
    """Fold one font's CID/ToUnicode reach into aggregate count slugs."""
    mapped: set[int] = set()
    for kind, lo, hi, _text in cid.tounicode.records:
        for code in range(lo, hi + 1):
            if len(mapped) >= _MAX_TOUNICODE_RECORDS:
                break
            mapped.add(code)
        if len(mapped) >= _MAX_TOUNICODE_RECORDS:
            break

    for code in mapped:
        reach[
            "tounicode_cid_with_glyph"
            if _cid_has_outline(cid, code)
            else "tounicode_cid_without_glyph"
        ] += 1

    cid_limit = (
        len(cid.cidtogid_table) // 2
        if cid.cidtogid_table is not None
        else cid.glyphs.num_glyphs
    )
    for code in range(min(cid_limit, _MAX_TOUNICODE_RECORDS)):
        if code not in mapped and _cid_has_outline(cid, code):
            reach["glyph_present_no_tounicode_cid"] += 1


def _glyph_overlap_census(
    show: object,
    capability: object,
    operator_x_glyph: Counter[str],
    hscale_x_glyph: Counter[str],
) -> None:
    cid = getattr(capability, "cid", None)
    verdict = _glyph_overlap_verdict(show, cid)
    operator = _glyph_overlap_operator_class(show)
    hscale = (
        "hscale_default"
        if getattr(show, "hscale", 0.0) == 100.0
        else "hscale_non_default"
    )
    operator_x_glyph[f"{operator}|{verdict}"] += 1
    hscale_x_glyph[f"{hscale}|{verdict}"] += 1


def _residual_state_losses(show: object) -> tuple[str, ...]:
    """All residual state failures in production's stable priority order."""
    losses: list[str] = []
    if getattr(show, "render_mode", 1) != 0:
        losses.append("state:render_mode")
    if getattr(show, "rise", 1.0) != 0.0:
        losses.append("state:rise")
    if getattr(show, "hscale", 0.0) != 100.0:
        losses.append("state:hscale")
    if not getattr(show, "in_bt", False):
        losses.append("state:not_in_bt")
    if not getattr(show, "origin_reliable", False):
        losses.append("state:origin_unreliable")
    return tuple(losses)


def _sole_loss_class(
    show: object,
    page: fitz.Page,
    capability: object,
    replay: object,
    wrapper_classes: dict[int, str],
    source_evidence: dict[tuple[int, bytes], tuple[object, object, object]],
    *,
    within_budget: bool,
) -> str:
    """Classify one Type0 show by an independent full production gate vector."""
    operator = getattr(show, "operator", "")
    op_single_hex = operator == "Tj" and getattr(show, "string_kind", "") == "hex"
    op_tj_array = operator == "TJ"

    wrappers = tuple(
        replay.mc_wrappers[index]
        for index in getattr(show, "mc_stack", ())
        if 0 <= index < len(replay.mc_wrappers)
    )
    mc_depth = getattr(show, "mc_depth", 1)
    if not wrappers and mc_depth == 0:
        mc_ok = True
    else:
        mc_ok = (
            len(wrappers) == mc_depth
            and replay.mc_emc_underflows == 0
            and all(
                wrapper_classes.get(wrapper.wrapper_id)
                == CLASS_OC_LAYER_VISIBLE
                for wrapper in wrappers
            )
            and all(
                splice_range_within_wrapper(
                    wrapper,
                    stream_xref=show.stream_xref,
                    start=show.op_start,
                    end=show.op_end,
                )
                for wrapper in wrappers
            )
        )

    trm_ok = bool(getattr(show, "trm_uniform_scaled", False))
    if not trm_ok:
        trm_ok = admission_verdict(page, show.tm, show.ctm).reject_reason is None

    hscale_ok = getattr(show, "hscale", 0.0) == 100.0
    other_state_ok = not (
        set(_residual_state_losses(show)) - {"state:hscale"}
    )
    cid = getattr(capability, "cid", None)
    cid_ok = cid is not None
    decode_ok = reproduce_ok = glyph_ok = False
    if cid is not None:
        data = getattr(show, "decoded_bytes", b"")
        evidence_key = (capability.font_xref, data)
        cached = source_evidence.get(evidence_key)
        if cached is None:
            decoded = cid.decode_show_bytes(data)
            reproduced: object = None
            glyph_failure: object = None
            if not isinstance(decoded, CidCapabilityFailure):
                reproduced = cid.encode_first_wins(decoded)
                source_cids = tuple(
                    int.from_bytes(data[index : index + 2], "big")
                    for index in range(0, len(data), 2)
                )
                glyph_failure = cid.glyph_gate(source_cids, decoded)
            cached = (decoded, reproduced, glyph_failure)
            source_evidence[evidence_key] = cached
        decoded, reproduced, glyph_failure = cached
        if not isinstance(decoded, CidCapabilityFailure):
            decode_ok = True
            reproduce_ok = (
                not isinstance(reproduced, CidCapabilityFailure)
                and reproduced == data
            )
            glyph_ok = glyph_failure is None

    downstream_ok = all(
        (
            within_budget,
            mc_ok,
            trm_ok,
            other_state_ok,
            cid_ok,
            decode_ok,
            reproduce_ok,
            glyph_ok,
        )
    )
    if downstream_ok and op_single_hex and hscale_ok:
        return "all_gates_pass"
    if downstream_ok and op_tj_array and hscale_ok:
        return "tj_array_only"
    if downstream_ok and op_single_hex and not hscale_ok:
        return "hscale_only"
    if downstream_ok and op_tj_array and not hscale_ok:
        return "tj_array_and_hscale_only"
    return "other"


def _type0_font_population(
    doc: fitz.Document, registry: DocumentFontRegistry
) -> tuple[dict[int, object], Counter[int], int]:
    capabilities: dict[int, object] = {}
    pages_per_font: Counter[int] = Counter()
    resolution_mismatches = 0
    for page_index in range(doc.page_count):
        page = doc[page_index]
        seen: set[int] = set()
        for entry in page.get_fonts(full=True):
            font_xref = int(entry[0])
            if font_xref <= 0 or entry[2] != "Type0":
                continue
            capability = registry.capability(page, entry[4])
            if capability is None or capability.subtype != "Type0":
                continue
            if capability.font_xref != font_xref:
                resolution_mismatches += 1
                continue
            capabilities.setdefault(font_xref, capability)
            if font_xref not in seen:
                seen.add(font_xref)
                pages_per_font[font_xref] += 1
    return capabilities, pages_per_font, resolution_mismatches


_CORPUS_UNION_PER_FONT_CAP = 65_536


def _corpus_union(
    capabilities: dict[int, object],
) -> tuple[tuple[str, ...], int]:
    chars: dict[str, None] = {}
    truncated_fonts = 0
    for capability in capabilities.values():
        cid = getattr(capability, "cid", None)
        if cid is None:
            continue
        font_chars: dict[str, None] = {}
        records = cid.tounicode.records
        truncated = False
        for record_index, (kind, lo, hi, text) in enumerate(records):
            if kind == "char":
                if len(text) == 1:
                    font_chars.setdefault(text, None)
                if (
                    len(font_chars) >= _CORPUS_UNION_PER_FONT_CAP
                    and record_index + 1 < len(records)
                ):
                    truncated = True
                    break
                continue
            for offset in range(hi - lo + 1):
                try:
                    char = chr(ord(text) + offset)
                except ValueError:
                    break
                if (
                    char not in font_chars
                    and len(font_chars) >= _CORPUS_UNION_PER_FONT_CAP
                ):
                    truncated = True
                    break
                font_chars.setdefault(char, None)
            if truncated:
                break
        if truncated:
            truncated_fonts += 1
        for char in font_chars:
            chars.setdefault(char, None)
    return tuple(chars), truncated_fonts


ReverseCidIndex = tuple[
    dict[str, set[int]], tuple[tuple[int, int, int], ...]
]


def _reverse_cid_index(
    cid: IdentityHCidCapability,
) -> ReverseCidIndex:
    """Index bfchar records and bfrange intervals without span expansion."""
    char_records: dict[str, set[int]] = {}
    ranges: list[tuple[int, int, int]] = []
    for kind, lo, hi, text in cid.tounicode.records:
        if kind == "char":
            if len(text) == 1:
                char_records.setdefault(text, set()).add(lo)
            continue
        ranges.append((lo, hi, ord(text)))
    return char_records, tuple(ranges)


def _lookup_reverse_cids(index: ReverseCidIndex, char: str) -> set[int]:
    """Return the exact CID set represented by one reverse index."""
    char_records, ranges = index
    matches = set(char_records.get(char, ()))
    codepoint = ord(char)
    for lo, hi, base_ord in ranges:
        offset = codepoint - base_ord
        if 0 <= offset <= hi - lo:
            matches.add(lo + offset)
    return matches


def _vocabulary_verdict(
    capability: object,
    char: str,
    reverse_index: ReverseCidIndex | None,
) -> str:
    cid = getattr(capability, "cid", None)
    if cid is None or reverse_index is None:
        return "cid_unavailable"
    encoded = _lookup_reverse_cids(reverse_index, char)
    if not encoded:
        return "type0_unicode_unmapped"
    if len(encoded) > 1:
        return "type0_tounicode_ambiguous"
    failure = cid.glyph_gate(tuple(encoded), char)
    return "encodable_now" if failure is None else failure.reason


def _blank_vocabulary_counts() -> dict[str, int]:
    return {bucket: 0 for bucket in VOCABULARY_ALL_BUCKETS}


def _vocabulary_counterfactual(
    capabilities: dict[int, object],
    pages_per_font: Counter[int],
    bindable_shows: Counter[int],
    replayed_font_xrefs: set[int],
    tj_array_only_by_font: Counter[int],
    hscale_only_by_font: Counter[int],
    font_resolution_mismatch: int,
    candidate_has_glyph: Callable[[str], bool] | None,
) -> dict[str, object]:
    vocabularies = dict(VOCABULARIES)
    corpus_union, corpus_union_truncated_fonts = _corpus_union(capabilities)
    vocabularies["corpus_union"] = corpus_union
    weighted: dict[str, dict[str, dict[str, int]]] = {
        weighting: {
            name: _blank_vocabulary_counts() for name in vocabularies
        }
        for weighting in VOCABULARY_WEIGHTINGS
    }
    candidate_cache: dict[str, bool] = {}
    priority_b = Counter(
        {
            "baseline_numerator": 0,
            "augmentation_numerator": 0,
            "tj_array_numerator": 0,
            "hscale_numerator": 0,
        }
    )

    for font_xref, capability in capabilities.items():
        cid = getattr(capability, "cid", None)
        reverse_index = _reverse_cid_index(cid) if cid is not None else None
        weights = {
            "font_weighted": 1,
            "page_weighted": pages_per_font[font_xref],
            # Integer show-character opportunities.  Dividing by the
            # vocabulary length yields Σ bindable_shows(font) × rate.
            "show_weighted": bindable_shows[font_xref],
        }
        corpus_now = 0
        corpus_augmentation = 0
        for name, chars in vocabularies.items():
            for char in chars:
                verdict = _vocabulary_verdict(
                    capability, char, reverse_index
                )
                candidate = False
                if verdict != "encodable_now" and candidate_has_glyph:
                    cached_candidate = candidate_cache.get(char)
                    if cached_candidate is None:
                        try:
                            cached_candidate = bool(candidate_has_glyph(char))
                        except (
                            RuntimeError,
                            ValueError,
                            fitz.mupdf.FzErrorBase,
                        ):
                            cached_candidate = False
                        candidate_cache[char] = cached_candidate
                    candidate = cached_candidate
                augmentable = verdict in AUGMENTABLE_VERDICTS and candidate
                if name == "corpus_union":
                    if verdict == "encodable_now":
                        corpus_now += 1
                    elif augmentable:
                        corpus_augmentation += 1
                for weighting, weight in weights.items():
                    values = weighted[weighting][name]
                    values[verdict] += weight
                    if candidate:
                        values[f"candidate_supply|{verdict}"] += weight
                    if augmentable:
                        values["candidate_could_supply"] += weight
                    if verdict == "encodable_now" or augmentable:
                        values["after_augmentation"] += weight

        priority_b["baseline_numerator"] += (
            bindable_shows[font_xref] * corpus_now
        )
        priority_b["augmentation_numerator"] += (
            bindable_shows[font_xref] * corpus_augmentation
        )
        priority_b["tj_array_numerator"] += (
            tj_array_only_by_font[font_xref] * corpus_now
        )
        priority_b["hscale_numerator"] += (
            hscale_only_by_font[font_xref] * corpus_now
        )

    return {
        "fonts_evaluated": len(capabilities),
        "fonts_with_replayed_shows": len(replayed_font_xrefs),
        "replayed_fonts_not_in_population": len(
            replayed_font_xrefs - set(capabilities)
        ),
        "population_fonts_without_shows": len(
            set(capabilities) - replayed_font_xrefs
        ),
        "font_resolution_mismatch": font_resolution_mismatch,
        "font_page_references": sum(pages_per_font.values()),
        "bindable_shows": sum(bindable_shows.values()),
        "corpus_union_truncated_fonts": corpus_union_truncated_fonts,
        "priority_go_units": {
            "unit_a_self_proxy": {
                "augmentation_show_equivalents": 0,
                "tj_array_show_equivalents": sum(
                    tj_array_only_by_font.values()
                ),
                "hscale_show_equivalents": sum(
                    hscale_only_by_font.values()
                ),
            },
            "unit_b_corpus_union": {
                "vocabulary_size": len(corpus_union),
                **dict(priority_b),
            },
        },
        **weighted,
    }


def _residual_state_loss(show: object) -> str | None:
    """First failing residual default-state condition, as a stable
    ``state:*`` loss slug — or None when clear.  Marked-content and Tm
    uniformity are NOT here: they are their own funnel stages."""
    losses = _residual_state_losses(show)
    return losses[0] if losses else None


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


def funnel_document(
    doc: fitz.Document,
    *,
    run_e2e: bool,
    candidate_has_glyph: Callable[[str], bool] | None = None,
) -> dict[str, object]:
    registry = DocumentFontRegistry(doc)
    (
        type0_capabilities,
        pages_per_type0_font,
        font_resolution_mismatch,
    ) = _type0_font_population(doc, registry)
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
    glyph_operator: Counter[str] = Counter()
    glyph_hscale: Counter[str] = Counter()
    glyph_sole_loss: Counter[str] = Counter()
    tj_array_only_by_font: Counter[int] = Counter()
    hscale_only_by_font: Counter[int] = Counter()
    font_glyph_reach: Counter[str] = Counter()
    glyph_reach_fonts_seen: set[int] = set()
    replayed_type0_font_xrefs: set[int] = set()
    bindable_shows_by_font: Counter[int] = Counter()
    source_evidence: dict[
        tuple[int, bytes], tuple[object, object, object]
    ] = {}
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
            replayed_type0_font_xrefs.add(capability.font_xref)
            _glyph_overlap_census(
                show, capability, glyph_operator, glyph_hscale
            )
            sole_loss = _sole_loss_class(
                show,
                page,
                capability,
                replay,
                wrapper_classes,
                source_evidence,
                within_budget=within_budget,
            )
            glyph_sole_loss[sole_loss] += 1
            if sole_loss == "tj_array_only":
                tj_array_only_by_font[capability.font_xref] += 1
            elif sole_loss == "hscale_only":
                hscale_only_by_font[capability.font_xref] += 1
            if (
                capability.cid is not None
                and capability.font_xref not in glyph_reach_fonts_seen
            ):
                glyph_reach_fonts_seen.add(capability.font_xref)
                _record_font_glyph_reach(
                    capability.cid, font_glyph_reach
                )
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
            decoded, reproduced, glyph_failure = source_evidence[
                (capability.font_xref, show.decoded_bytes)
            ]
            if isinstance(decoded, CidCapabilityFailure):
                loss_reasons[decoded.reason] += 1
                continue
            shows_counter["source_decoded"] += 1
            chars_counter["source_decoded"] += len(decoded)
            if (
                isinstance(reproduced, CidCapabilityFailure)
                or reproduced != show.decoded_bytes
            ):
                loss_reasons["type0_source_bytes_not_reproduced"] += 1
                continue
            shows_counter["source_bytes_reproduced"] += 1
            if glyph_failure is not None:
                loss_reasons[glyph_failure.reason] += 1
                continue
            shows_counter["source_gid_glyph_ok"] += 1
            shows_counter["source_bindable"] += 1
            chars_counter["source_bindable"] += len(decoded)
            bindable_shows_by_font[capability.font_xref] += 1

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
        "glyph_overlap_census": {
            "operator_x_glyph": dict(sorted(glyph_operator.items())),
            "hscale_x_glyph": dict(sorted(glyph_hscale.items())),
            "font_glyph_reach": dict(sorted(font_glyph_reach.items())),
            "sole_loss": {
                slug: glyph_sole_loss[slug]
                for slug in GLYPH_OVERLAP_SOLE_LOSS_CLASSES
            },
            "cid_unavailable_reasons": dict(
                sorted(
                    Counter(
                        capability.tier0_reject_reason
                        or "capability_unavailable"
                        for capability in type0_capabilities.values()
                        if capability.cid is None
                    ).items()
                )
            ),
            "tounicode_unparseable_details": dict(
                sorted(
                    Counter(
                        capability.tier0_reject_detail
                        for capability in type0_capabilities.values()
                        if capability.cid is None
                        and capability.tier0_reject_reason
                        == "type0_tounicode_unparseable"
                        and capability.tier0_reject_detail is not None
                    ).items()
                )
            ),
        },
        "vocabulary_counterfactual": _vocabulary_counterfactual(
            type0_capabilities,
            pages_per_type0_font,
            bindable_shows_by_font,
            replayed_type0_font_xrefs,
            tj_array_only_by_font,
            hscale_only_by_font,
            font_resolution_mismatch,
            candidate_has_glyph,
        ),
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
    candidate_has_glyph = system_candidate_supplier()
    for index, path in enumerate(args.paths):
        doc = fitz.open(path)
        try:
            report[f"doc_{index}"] = funnel_document(
                doc,
                run_e2e=not args.no_e2e,
                candidate_has_glyph=candidate_has_glyph,
            )
        finally:
            doc.close()
    print(json.dumps(report, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
