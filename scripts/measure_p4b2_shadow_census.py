#!/usr/bin/env python3
"""P4-B2 shadow census: baseline / reach / exact duplicate-painter arms.

Runs the sealed Type0 census (``scripts/measure_type0_funnel.py``) UNCHANGED
and shadows its duplicate-painter gate with two more arms on every row:

- ``baseline`` — the production gate at the frozen P4-B1 tip (the answer the
  census receives; this harness returns it unchanged);
- ``reach``    — the same gate with ``plan._painter_advance`` stubbed to
  ``None`` (the review's collapse-to-reach control);
- ``exact``    — the spike gate (``scripts/painter_evidence``) on evidence the
  harness builds from its OWN copy of each document, one bundle per page.

The census's own numbers are asserted against the sealed constants BEFORE
anything is emitted; a mismatch exits non-zero with an empty stdout.  Every
value emitted is an integer under a closed key (plan §7.1); document
identity, text, font names, layer labels and exception text stay in memory.

Load-bearing accounting (twin ROW counts, not glyph counts): a row is
``trace_load_bearing`` when a twin/verdict reason falls in
``_TRACE_LOAD_BEARING_REASONS`` or the row has unattributed overlap; a row
is ``device_load_bearing`` when a twin/verdict reason falls in
``_DEVICE_LOAD_BEARING_REASONS`` (device/oracle-only failure slugs: the
production gate has no oracle, so these never fire there); a row is
``trace_or_device_load_bearing`` when either rule fires (union, counted
once).  ``row_reason.<slug>`` counts rows carrying that slug for every
slug in the closed ``EVENT_REASONS`` set (``scripts/painter_evidence``).

Usage::

    python scripts/measure_p4b2_shadow_census.py <pdf> [more...] [--json]
        [--expect all_gates_pass=6624] ...

Read-only: nothing is written; no document is saved.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit import plan as plan_module  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry, FontCapability  # noqa: E402
from model.text_commit.plan import _renderable_bbox, _same_font_object  # noqa: E402
from model.text_commit.replay import ShowOp  # noqa: E402
from model.text_commit.transforms import map_text_quad_to_visual  # noqa: E402
from scripts import measure_type0_funnel  # noqa: E402
from scripts.painter_evidence import (  # noqa: E402
    EVENT_REASONS,
    MISSING_WINDOW_REASONS,
    RENDER_MODE_KEYS,
    PagePainterEvidence,
    build_page_painter_evidence,
    exact_duplicate_painter_verdict,
)
from scripts.painter_geometry import (  # noqa: E402
    GeometryUnavailable,
    OutlineOracle,
    place_text_rect,
    rects_overlap,
)

logger = logging.getLogger(__name__)

SEALED_KEYS = (
    "source_bindable",
    "all_gates_pass",
    "duplicate_painter_only",
    "tj_array_only",
    "hscale_only",
)

EXACT_CELLS = (
    "exact_safe",
    "exact_overlap_same_baseline",
    "exact_overlap_cross_baseline",
    "ambiguous",
    "unavailable",
    "error",
)

_TRACE_LOAD_BEARING_REASONS = frozenset(
    {"ocg_or_absent", "multiple_windows", "unknown", "tr_clip"}
)

# Device/oracle-only failure slugs: reasons the exact arm's outline oracle
# can hit that a trace-free, device-free production slice could never see
# (there is no oracle in production).  Intersected with EVENT_REASONS so a
# renamed or retired slug drops out here instead of drifting the closed key
# set; nothing in the requested list below is missing from EVENT_REASONS as
# of this writing.
_DEVICE_LOAD_BEARING_REASONS = frozenset(
    {
        "oracle_disagreement",
        "oracle_unavailable",
        "fz_text_shared",
        "degenerate_stroke",
        "no_ink_rect",
        "conservative_overlap",
        "vertical_writing",
    }
) & frozenset(EVENT_REASONS)

# row_reason.<slug> counter keys, one per slug in the closed EVENT_REASONS
# set (event reasons + the verdict reasons emitted by
# exact_duplicate_painter_verdict, which are a subset of EVENT_REASONS).
ROW_REASON_KEYS: tuple[str, ...] = tuple(f"row_reason.{slug}" for slug in EVENT_REASONS)

SHADOW_COUNTER_KEYS: tuple[str, ...] = (
    (
        "rows_type0_shows",
        "rows_source_bindable",
        "rows_all_gates_pass",
        "rows_duplicate_painter_only",
        "rows_tj_array_only",
        "rows_hscale_only",
        "rows_other",
        "gate_calls",
        "no_twins",
        "twin_rows",
        "delta_rows",
        "reach_safe_twin_rows",
        "reach_all_gates_pass",
    )
    + tuple(f"d_{cell}" for cell in EXACT_CELLS)
    + tuple(f"r_{cell}" for cell in EXACT_CELLS)
    + tuple(f"p_{cell}" for cell in EXACT_CELLS)
    + (
        "p_target_placement_unproven",
        "t_join_available",
        "t_join_ambiguous",
        "tj_twin_rows",
        "tj_twin_decided",
        "target_join_ambiguous",
        "twin_join_ambiguous",
    )
    + tuple(f"missing_window.{reason}" for reason in MISSING_WINDOW_REASONS)
    + (
        "verdict_invariant_ambiguity",
        "multiple_windows",
        "oracle_disagreement",
        "oracle_unavailable",
        "identity_refuted_by_outline",
        "twin_ink_in_target_bbox",
        "twin_oc_hidden",
        "unattributed_glyphs_total",
        "unattributed_glyphs_overlap_target",
        "trace_load_bearing",
        "device_load_bearing",
        "trace_or_device_load_bearing",
        "tier0_bbox_would_reject",
        "font_has_fpgm_prep",
    )
    + ROW_REASON_KEYS
    + RENDER_MODE_KEYS
    + (
        "form_xobject_pages",
        "evidence_builds",
        "evidence_pages",
        "exact_error",
        "composed_all_gates_pass",
        "composed_all_gates_pass_hazard_model",
        "composed_with_p_exact_safe",
    )
)

IDENTITY_KEYS = (
    "d_partition",
    "r_partition",
    "p_partition",
    "delta_identity",
    "composed_identity",
)

REPORT_KEYS = ("status", "documents", "pages", "sealed", "counters", "identities")


class SealedMismatch(Exception):
    """The baseline census did not reproduce a sealed constant."""

    def __init__(self, key: str, expected: int, observed: int) -> None:
        super().__init__(f"sealed_constant_mismatch: {key} expected {expected} observed {observed}")
        self.key = key
        self.expected = expected
        self.observed = observed


@dataclass(frozen=True)
class SealedConstants:
    """Sealed corpus numbers (defaults: the P4-B1 round-4 sealing record)."""

    source_bindable: int = 6811
    all_gates_pass: int = 6624
    duplicate_painter_only: int = 187
    tj_array_only: int = 112
    hscale_only: int = 0

    def as_dict(self) -> dict[str, int]:
        return {key: int(getattr(self, key)) for key in SEALED_KEYS}


@dataclass
class _RowRecord:
    """One duplicate-gate call, all three arms (identity stays in memory)."""

    has_twins: bool
    baseline_admits: bool
    reach_admits: bool
    exact_kind: str
    exact_reason: str | None
    target_unproven: bool
    twin_ink_in_target_bbox: bool
    twin_kinds: tuple[str, ...]
    twin_reasons: tuple[str | None, ...]
    tj_twin: bool
    unattributed_overlap: int
    identity_refuted: int
    tier0_bbox_would_reject: bool
    sole_loss: str | None = None


@dataclass
class _DocumentShadow:
    """Harness-owned resources for one census document."""

    doc: fitz.Document
    registry: DocumentFontRegistry
    oracles: dict[int, OutlineOracle | None] = field(default_factory=dict)
    evidence: dict[int, PagePainterEvidence | None] = field(default_factory=dict)

    def close(self) -> None:
        for bundle in self.evidence.values():
            if bundle is not None:
                bundle.release()
        self.evidence.clear()
        self.doc.close()


def _open_shadow_copy(doc: fitz.Document) -> fitz.Document:
    """The harness's own Document for the same bytes: never the census's."""
    name = getattr(doc, "name", "") or ""
    if name and Path(name).is_file():
        return fitz.open(name)
    return fitz.open("pdf", doc.tobytes())


class ShadowCensus:
    """Installs the three wrappers and accumulates per-row records."""

    def __init__(self, sealed: SealedConstants) -> None:
        self.sealed = sealed
        self.rows: dict[tuple[int, int, int], _RowRecord] = {}
        self.sole_loss: dict[tuple[int, int, int], str] = {}
        self.page_counters: Counter[str] = Counter()
        self.reports: list[dict[str, object]] = []
        self.pages = 0
        self._ordinal = -1
        self._shadow: _DocumentShadow | None = None
        self._evidence_pages_seen: set[tuple[int, int]] = set()

    # ---------------------------------------------------------- wrappers

    @contextmanager
    def installed(self) -> Iterator[None]:
        module = measure_type0_funnel
        original_funnel = module.funnel_document
        original_gate = module.duplicate_source_painter_detail
        original_sole = module._sole_loss_class

        def funnel(doc: fitz.Document, **kwargs: object) -> dict[str, object]:
            self._ordinal += 1
            shadow = _DocumentShadow(doc=_open_shadow_copy(doc), registry=None)  # type: ignore[arg-type]
            shadow.registry = DocumentFontRegistry(shadow.doc)
            self._shadow = shadow
            try:
                report = original_funnel(doc, **kwargs)  # type: ignore[arg-type]
            finally:
                self.pages += doc.page_count
                shadow.close()
                self._shadow = None
            self.reports.append(report)
            return report

        def gate(
            page: fitz.Page,
            target: ShowOp,
            *,
            target_text: str,
            target_capability: FontCapability,
            source_advance: float,
            registry: DocumentFontRegistry,
            shows: tuple[ShowOp, ...],
            capabilities: dict[str, FontCapability] | None = None,
        ) -> str | None:
            kwargs = {
                "target_text": target_text,
                "target_capability": target_capability,
                "source_advance": source_advance,
                "registry": registry,
                "shows": shows,
                "capabilities": capabilities,
            }
            baseline = original_gate(page, target, **kwargs)  # type: ignore[arg-type]
            saved = plan_module._painter_advance
            plan_module._painter_advance = lambda capability, show, text: None  # type: ignore[assignment]
            try:
                reach = original_gate(page, target, **kwargs)  # type: ignore[arg-type]
            finally:
                plan_module._painter_advance = saved
            self._record(
                page,
                target,
                target_capability=target_capability,
                source_advance=source_advance,
                shows=shows,
                capabilities=capabilities,
                baseline=baseline,
                reach=reach,
            )
            return baseline

        def sole(show: object, page: fitz.Page, *args: object, **kwargs: object) -> str:
            result = original_sole(show, page, *args, **kwargs)  # type: ignore[arg-type]
            key = (self._ordinal, page.number, int(getattr(show, "seq", -1)))
            self.sole_loss[key] = result
            return result

        module.funnel_document = funnel  # type: ignore[assignment]
        module.duplicate_source_painter_detail = gate  # type: ignore[assignment]
        module._sole_loss_class = sole  # type: ignore[assignment]
        try:
            yield
        finally:
            module.funnel_document = original_funnel  # type: ignore[assignment]
            module.duplicate_source_painter_detail = original_gate  # type: ignore[assignment]
            module._sole_loss_class = original_sole  # type: ignore[assignment]

    # ----------------------------------------------------------- exact arm

    def _page_evidence(self, page_number: int) -> PagePainterEvidence | None:
        shadow = self._shadow
        assert shadow is not None
        if page_number in shadow.evidence:
            return shadow.evidence[page_number]
        key = (self._ordinal, page_number)
        bundle: PagePainterEvidence | None = None
        try:
            bundle = build_page_painter_evidence(
                shadow.doc,
                shadow.doc[page_number],
                registry=shadow.registry,
                oracles=shadow.oracles,
            )
        except Exception:  # noqa: BLE001 - closed slug, message dropped
            bundle = None
        shadow.evidence[page_number] = bundle
        if key not in self._evidence_pages_seen:
            self._evidence_pages_seen.add(key)
            self.page_counters["evidence_pages"] += 1
            if bundle is not None:
                self.page_counters["evidence_builds"] += bundle.builds
                for counter_key, value in bundle.counters.items():
                    self.page_counters[counter_key] += value
                self.page_counters["unattributed_glyphs_total"] += bundle.unattributed_glyphs
        return bundle

    def _record(
        self,
        page: fitz.Page,
        target: ShowOp,
        *,
        target_capability: FontCapability,
        source_advance: float,
        shows: tuple[ShowOp, ...],
        capabilities: dict[str, FontCapability] | None,
        baseline: str | None,
        reach: str | None,
    ) -> None:
        twins = tuple(
            candidate
            for candidate in shows
            if candidate.seq != target.seq
            and candidate.decoded_bytes == target.decoded_bytes
        )
        key = (self._ordinal, page.number, target.seq)
        th = target.hscale / 100.0
        halo_quad = (0.0, -0.35 * target.font_size, source_advance * th, target.font_size)
        tier0_reject = False
        try:
            visual = map_text_quad_to_visual(page, target.tm, target.ctm, halo_quad)
            tier0_reject = _renderable_bbox(visual) is None
        except Exception:  # noqa: BLE001
            tier0_reject = True
        record = _RowRecord(
            has_twins=bool(twins),
            baseline_admits=baseline is None,
            reach_admits=reach is None,
            exact_kind="exact_safe",
            exact_reason=None,
            target_unproven=False,
            twin_ink_in_target_bbox=False,
            twin_kinds=(),
            twin_reasons=(),
            tj_twin=any(twin.operator == "TJ" for twin in twins),
            unattributed_overlap=0,
            identity_refuted=0,
            tier0_bbox_would_reject=tier0_reject,
        )
        if twins:
            try:
                evidence = self._page_evidence(page.number)
                if evidence is None:
                    raise RuntimeError("evidence unavailable")
                halo = place_text_rect(
                    halo_quad, 0.0, 0.0, target.tm, target.ctm, evidence.base_matrix
                )
                verdict = exact_duplicate_painter_verdict(
                    evidence, target, twins, target_bbox_page=halo
                )
                record.exact_kind = verdict.kind
                record.exact_reason = verdict.reason
                record.target_unproven = verdict.target_unproven
                record.twin_ink_in_target_bbox = verdict.twin_ink_in_target_bbox
                record.twin_kinds = verdict.twin_kinds
                record.twin_reasons = tuple(
                    (event.reason if event is not None else "no_event")
                    for event in (evidence.event_for(twin) for twin in twins)
                )
                target_event = evidence.event_for(target)
                union = target_event.glyph_union() if target_event is not None else None
                if union is not None:
                    record.unattributed_overlap = sum(
                        1 for rect in evidence.unattributed_rects if rects_overlap(rect, union)
                    )
                record.identity_refuted = self._identity_refutations(
                    evidence, target, target_capability, twins, capabilities
                )
            except Exception:  # noqa: BLE001 - every failure is one closed cell
                record.exact_kind = "error"
                record.exact_reason = None
        self.rows[key] = record

    def _identity_refutations(
        self,
        evidence: PagePainterEvidence,
        target: ShowOp,
        target_capability: FontCapability,
        twins: tuple[ShowOp, ...],
        capabilities: dict[str, FontCapability] | None,
    ) -> int:
        """Twins whose font the production identity rule calls the SAME
        font while their outlines differ from the target font's (diagnostic
        only; identity never admits in production)."""
        shadow = self._shadow
        assert shadow is not None
        target_oracle = shadow.oracles.get(target_capability.font_xref)
        if target_oracle is None:
            return 0
        refuted = 0
        for twin in twins:
            capability = (capabilities or {}).get(twin.font_resource or "")
            if capability is None or capability.font_xref == target_capability.font_xref:
                continue
            if _same_font_object(capability, target_capability) is not True:
                continue
            twin_oracle = shadow.oracles.get(capability.font_xref)
            event = evidence.event_for(twin)
            if twin_oracle is None or event is None or not event.glyphs:
                continue
            try:
                for glyph in event.glyphs:
                    if twin_oracle.bounds(glyph.gid) != target_oracle.bounds(glyph.gid):
                        refuted += 1
                        break
            except GeometryUnavailable:
                continue
        return refuted

    # ------------------------------------------------------------ report

    def observed_sealed(self) -> dict[str, int]:
        totals = dict.fromkeys(SEALED_KEYS, 0)
        for report in self.reports:
            funnel = report.get("funnel_shows", {})
            totals["source_bindable"] += int(funnel.get("source_bindable", 0))  # type: ignore[union-attr]
            sole = report.get("glyph_overlap_census", {}).get("sole_loss", {})  # type: ignore[union-attr]
            for key in SEALED_KEYS[1:]:
                totals[key] += int(sole.get(key, 0))
        return totals

    def assert_sealed(self) -> None:
        observed = self.observed_sealed()
        for key, expected in self.sealed.as_dict().items():
            if observed[key] != expected:
                raise SealedMismatch(key, expected, observed[key])

    def counters(self) -> tuple[Counter[str], dict[str, bool]]:
        c: Counter[str] = Counter({key: 0 for key in SHADOW_COUNTER_KEYS})
        for key, value in self.page_counters.items():
            if key in c:
                c[key] += value
        for key, sole in self.sole_loss.items():
            c["rows_type0_shows"] += 1
            bucket = {
                "all_gates_pass": "rows_all_gates_pass",
                "duplicate_painter_only": "rows_duplicate_painter_only",
                "tj_array_only": "rows_tj_array_only",
                "hscale_only": "rows_hscale_only",
            }.get(sole, "rows_other")
            c[bucket] += 1
            record = self.rows.get(key)
            if record is not None:
                record.sole_loss = sole
        c["rows_source_bindable"] = self.observed_sealed()["source_bindable"]
        for record in self.rows.values():
            c["gate_calls"] += 1
            if not record.has_twins:
                c["no_twins"] += 1
                if record.sole_loss == "all_gates_pass":
                    c["reach_all_gates_pass"] += 1
                continue
            c["twin_rows"] += 1
            cell = record.exact_kind
            if record.sole_loss == "all_gates_pass":
                if record.reach_admits:
                    c["reach_safe_twin_rows"] += 1
                    c["reach_all_gates_pass"] += 1
                    c[f"r_{cell}"] += 1
                else:
                    c["delta_rows"] += 1
                    c[f"d_{cell}"] += 1
            elif record.sole_loss == "duplicate_painter_only":
                c[f"p_{cell}"] += 1
                if record.target_unproven:
                    c["p_target_placement_unproven"] += 1
            if record.sole_loss == "tj_array_only":
                if record.target_unproven or cell in ("ambiguous", "unavailable", "error"):
                    c["t_join_ambiguous"] += 1
                else:
                    c["t_join_available"] += 1
            if record.tj_twin:
                c["tj_twin_rows"] += 1
                if cell in ("exact_safe", "exact_overlap_same_baseline", "exact_overlap_cross_baseline"):
                    c["tj_twin_decided"] += 1
            if record.target_unproven:
                c["target_join_ambiguous"] += 1
            elif cell == "ambiguous":
                c["twin_join_ambiguous"] += 1
            if cell == "error":
                c["exact_error"] += 1
            if record.twin_ink_in_target_bbox:
                c["twin_ink_in_target_bbox"] += 1
            c["twin_oc_hidden"] += sum(1 for reason in record.twin_reasons if reason == "ocg_or_absent")
            c["unattributed_glyphs_overlap_target"] += record.unattributed_overlap
            c["identity_refuted_by_outline"] += record.identity_refuted
            if record.tier0_bbox_would_reject:
                c["tier0_bbox_would_reject"] += 1
            reasons = set(record.twin_reasons) | {record.exact_reason}
            trace_hit = bool(reasons & _TRACE_LOAD_BEARING_REASONS) or bool(
                record.unattributed_overlap
            )
            device_hit = bool(reasons & _DEVICE_LOAD_BEARING_REASONS)
            if trace_hit:
                c["trace_load_bearing"] += 1
            if device_hit:
                c["device_load_bearing"] += 1
            if trace_hit or device_hit:
                c["trace_or_device_load_bearing"] += 1
            for slug in EVENT_REASONS:
                if slug in reasons:
                    c[f"row_reason.{slug}"] += 1
        c["composed_all_gates_pass"] = (
            c["reach_all_gates_pass"]
            + c["d_exact_safe"]
            - c["r_exact_overlap_same_baseline"]
            - c["r_exact_overlap_cross_baseline"]
        )
        c["composed_all_gates_pass_hazard_model"] = (
            c["reach_all_gates_pass"]
            + c["d_exact_safe"]
            + c["d_exact_overlap_cross_baseline"]
            - c["r_exact_overlap_same_baseline"]
        )
        c["composed_with_p_exact_safe"] = c["composed_all_gates_pass"] + c["p_exact_safe"]
        identities = {
            "d_partition": sum(c[f"d_{cell}"] for cell in EXACT_CELLS) == c["delta_rows"],
            "r_partition": sum(c[f"r_{cell}"] for cell in EXACT_CELLS) == c["reach_safe_twin_rows"],
            "p_partition": sum(c[f"p_{cell}"] for cell in EXACT_CELLS)
            == c["rows_duplicate_painter_only"],
            "delta_identity": c["delta_rows"] == c["rows_all_gates_pass"] - c["reach_all_gates_pass"],
            "composed_identity": c["composed_all_gates_pass"]
            == c["reach_all_gates_pass"]
            + c["d_exact_safe"]
            - c["r_exact_overlap_same_baseline"]
            - c["r_exact_overlap_cross_baseline"],
        }
        return c, identities

    def report(self) -> dict[str, object]:
        self.assert_sealed()
        counters, identities = self.counters()
        return {
            "status": "ok",
            "documents": len(self.reports),
            "pages": self.pages,
            "sealed": self.observed_sealed(),
            "counters": {key: int(counters[key]) for key in SHADOW_COUNTER_KEYS},
            "identities": {key: bool(identities[key]) for key in IDENTITY_KEYS},
        }


def run_shadow_census(
    documents: list[fitz.Document],
    *,
    sealed: SealedConstants,
    candidate_has_glyph: Callable[[str], bool] | None = None,
) -> dict[str, object]:
    """Run the census over already-open documents under the shadow wrappers
    and return the closed-key report (raises :class:`SealedMismatch`)."""
    census = ShadowCensus(sealed)
    with census.installed():
        for doc in documents:
            measure_type0_funnel.funnel_document(
                doc, run_e2e=False, candidate_has_glyph=candidate_has_glyph
            )
    return census.report()


def _parse_expectations(pairs: list[str], defaults: SealedConstants) -> SealedConstants:
    values = defaults.as_dict()
    for pair in pairs:
        key, _, raw = pair.partition("=")
        if key not in values:
            raise argparse.ArgumentTypeError(f"unknown sealed key: {key}")
        values[key] = int(raw)
    return SealedConstants(**values)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="PDF files (never echoed)")
    parser.add_argument("--json", action="store_true", help="compact JSON")
    parser.add_argument(
        "--no-candidate-fonts",
        action="store_true",
        help="skip loading the system candidate faces (headroom counts only)",
    )
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="override a sealed constant (default: the sealed corpus values)",
    )
    args = parser.parse_args(argv)
    fitz.TOOLS.mupdf_display_errors(False)
    try:
        sealed = _parse_expectations(args.expect, SealedConstants())
    except (argparse.ArgumentTypeError, ValueError):
        print("bad_expectation", file=sys.stderr)
        return 2
    candidate_has_glyph = (
        None
        if args.no_candidate_fonts
        else measure_type0_funnel.system_candidate_supplier()
    )
    documents: list[fitz.Document] = []
    try:
        for path in args.paths:
            documents.append(fitz.open(path))
        report = run_shadow_census(
            documents, sealed=sealed, candidate_has_glyph=candidate_has_glyph
        )
    except SealedMismatch as exc:
        print(str(exc), file=sys.stderr)
        return 3
    finally:
        for doc in documents:
            doc.close()
    print(json.dumps(report, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
