#!/usr/bin/env python3
"""Read-only measurement: edit-level funnel survival + three corpus checks.

Extends ``scripts/audit_tier_coverage.py`` (which classifies *shows*) with
four counts that classify *edits* and structural corpus properties instead
(TODOS.md "Pre-Task-11" measurement pass):

(a) **Edit-level funnel survival** -- resolve -> bind -> plan, driven with an
    IDENTITY replacement (replacement text == target text) over a
    deterministic, systematic sample: every text line and every single
    whole-word run on every page (capped per page; see ``--line-cap`` /
    ``--run-cap``). Identity isolates *structural* survival from the advance
    gate: a replacement identical to its source has identical advance by
    construction, so ``ADVANCE_MISMATCH`` can never fire and is skipped
    rather than counted. The *resolve* stage reuses ``_tier0_target_from_resolve``
    exactly as ``pdf_text_edit.py`` does, over a real ``TextBlockManager``
    index (the ``_StubModel`` shape ``test_tier0_target_resolution.py``
    established for exactly this purpose) -- so this is a genuine resolve
    pass, not the bind-then-plan fallback the task spec allowed for. The
    *plan* stage cannot call ``prepare_tier0_plan`` directly: its first gate
    is ``replacement_text == target_text -> NO_CHANGE``, which an identity
    replacement always trips, making every sample fail identically and
    measuring nothing. ``_identity_plan_survival`` below runs the same
    structural/font/encoding gates ``prepare_tier0_plan`` runs, in the same
    order, minus the six live-edit-request gates identity makes either
    inapplicable (no style/geometry override, no pending maintenance, not
    empty, not multiline) or self-defeating (NO_CHANGE, ADVANCE_MISMATCH) to
    ask under identity.

(b) **Forward advance-dependency** -- per show, does the *next* show in the
    page's stream sequence depend on this op's (never-computed) advance
    because no ``Td``/``TD``/``Tm``/``T*``/``BT`` (or the implicit line move
    inside ``'``/``"``) repositioned the pen first? ``replay.py`` already
    computes exactly this per show (``ShowOp.origin_reliable``: "False if a
    prior show's advance was not tracked", set via ``advance_pending`` and
    cleared by every one of those operators, including inside ``'``/``"``
    before they record their own show) -- so "does a successor consume show
    N's advance" is just "is show N+1's ``origin_reliable`` False", with no
    operator re-walk needed. Verified sufficient by reading ``replay.py``
    end to end rather than assumed; see the module for the exact mechanism.

(c) **Tabular digits** -- for every unique ``FontCapability`` with a
    ``/Widths`` table (deduped by (owner_xref, resource_name, font_xref)
    across the whole document), do codes 0x30-0x39 all carry an equal,
    positive declared width?

(d) **TJ binding-survival** -- among ``TJ`` shows, does the array contain any
    numeric (kerning) operand? ``replay.py`` builds ``decoded_bytes`` as a
    plain join of the array's string operands, silently dropping any
    numbers; ``inspect.bind_source_text`` then requires exact byte equality
    against a target string, so an array with a numeric adjustment can never
    byte-match a target that (correctly) represents that gap as a space.
    Re-lexes each TJ array's own byte range (``pdf_lexer.lex_content_stream``)
    for a ``NUMBER`` token, since ``replay.py`` does not expose this boolean
    on ``ShowOp``. Never mutates ``replay.py``.

(e) **``target_in_form_xobject`` deconfliction** -- ``inspect.bind_source_text``
    reclassifies *any* unmatched target as ``TARGET_IN_FORM_XOBJECT`` whenever
    ``PageReplay.has_xobject_invocation`` is true anywhere on the page (one
    small invoked XObject -- a bullet glyph, a logo -- poisons every direct-
    stream miss on that page with the same label). On this corpus that flag
    is true on effectively every page of the dominant file, so the bind-stage
    tally's ``target_in_form_xobject`` count is not trustworthy at face value
    -- it is measured here for comparability with production, but never
    reported alone. Each such failure is independently re-checked by
    replaying every Form XObject the page's own ``/Resources`` invokes
    (one level; nested ``Do`` inside a Form XObject's own stream is not
    followed) and looking for a byte-identical show -- no origin
    corroboration, since an XObject's text lives in its own coordinate space
    composed with the invoking ``cm`` and the XObject's own ``/Matrix``,
    which ``replay.py`` does not track. A confirmed byte match means the
    production label is at least plausible; no match anywhere means it is a
    reclassification artifact, and the *true* candidate reason (``NO_MATCH``
    or, via the same D5 relabeling as (a), ``TARGET_RECONSTRUCTION_UNVERIFIED``)
    is recovered and reported separately.

Never mutates the document (no scratch commit, no ``prepare_tier0_plan``
call, no ``clean_contents``) and never emits document text, extracted
strings, or file paths: only counts, booleans, and stable
:class:`~model.text_commit.dto.RejectReason` codes. ``BindingFailure``/
``PlanRejection`` ``.detail`` strings are never read for this reason (they
are safe boilerplate, not source text, but the reason code alone is the
documented contract this script commits to). Documents are identified only
by a 0-based positional index (the order they were passed on the command
line), never by name or derived identifiers like filename hashes.

Every metric is reported per document, then aggregated two ways: show-
weighted (raw counts summed across documents -- a large document dominates
in proportion to its own show count) and document-weighted (each document's
own rate averaged with equal weight, regardless of size). One PDF in this
corpus carries the large majority of all shows, so a single weighting would
let it define the headline; report both.

Usage::

    python scripts/measure_tier_funnel.py <pdf> [<pdf> ...] [--password PW]
        [--json] [--line-cap N] [--run-cap N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_text_edit import (  # noqa: E402
    _EditTextResolveResult,
    _reconstruction_aware_reason,
    _tier0_target_from_resolve,
)
from model.text_block import EditableSpan, TextBlockManager  # noqa: E402
from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry, FontCapability  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    BindingFailure,
    SourceSpanBinding,
    _origin_in_page_space,
    page_has_widgets_or_signatures,
    read_page_streams,
)
from model.text_commit.pdf_lexer import TokenKind, lex_content_stream  # noqa: E402
from model.text_commit.replay import PageReplay, ShowOp, replay_page_streams  # noqa: E402

# --------------------------------------------------------------------------
# Deterministic per-page sample caps (systematic: first N in a stable order,
# never random). Runtime is dominated by TextBlockManager.build_index (one
# full-document rawdict parse, unavoidable for any resolve-stage measurement
# and independent of these caps); they bound the incremental per-sample cost
# on pages with unusually many lines/runs.
# --------------------------------------------------------------------------
DEFAULT_LINE_CAP_PER_PAGE = 30
DEFAULT_RUN_CAP_PER_PAGE = 60

_TABULAR_TOL = 1e-6  # float-noise tolerance; /Widths units are exact integers


class _StubModel:
    """The two attributes ``_tier0_target_from_resolve`` touches.

    Mirrors ``test_tier0_target_resolution.py``'s ``_StubModel``: a real
    document and a real block index, nothing PDFModel-shaped (session/undo/
    controller wiring this measurement never needs).
    """

    def __init__(self, doc: fitz.Document) -> None:
        self.doc = doc
        self.block_manager = TextBlockManager()
        self.block_manager.build_index(doc)


def _build_resolve_result(
    runs: list[EditableSpan], member_ids: set[str]
) -> _EditTextResolveResult:
    members = [r for r in runs if r.span_id in member_ids]
    return _EditTextResolveResult(
        target_span=members[0] if members else (runs[0] if runs else None),  # type: ignore[arg-type]
        resolved_target_span_id=next(iter(member_ids), ""),
        effective_target_mode="run",
        target_member_span_ids=set(member_ids),
        overlap_cluster=runs,
        protected_spans=[],
        target=None,  # type: ignore[arg-type]  # unread by _tier0_target_from_resolve
        resolved_font="helv",
        rotation=0,
        is_vertical=False,
        insert_rotate=0,
        redact_rect=fitz.Rect(0, 0, 1, 1),
    )


def _line_and_run_samples(
    runs: list[EditableSpan], line_cap: int, run_cap: int
) -> tuple[list[set[str]], int, int]:
    """Deterministic (text line, single word run) member-id sets for a page.

    Lines are grouped by ``(block_idx, line_idx)`` in that key's sort order;
    runs are taken in ``get_runs`` order. Both truncate at their cap -- a
    systematic, not random, sample. Returns ``(samples, line_count,
    run_count)`` so a caller's reported sample count can never drift from
    what was actually produced here (the two were previously derived twice,
    independently, which agreed today but had no structural guarantee of
    staying in sync).
    """
    line_groups: dict[tuple[int, int], list[str]] = {}
    for run in runs:
        line_groups.setdefault((run.block_idx, run.line_idx), []).append(run.span_id)
    samples: list[set[str]] = []
    line_keys = sorted(line_groups.keys())[:line_cap]
    for key in line_keys:
        samples.append(set(line_groups[key]))
    run_slice = runs[:run_cap]
    for run in run_slice:
        samples.append({run.span_id})
    return samples, len(line_keys), len(run_slice)


def _bind_against_replay(
    page: fitz.Page,
    streams: list[tuple[int, bytes]],
    replay: PageReplay,
    *,
    target_text: str,
    expected_origin: tuple[float, float] | None,
    tol: float = 0.5,
) -> SourceSpanBinding | BindingFailure:
    """``inspect.bind_source_text``'s exact matching rules, replay reused.

    A systematic per-page sample draws dozens of targets from the same page;
    ``bind_source_text`` re-reads and re-lexes the page's content streams on
    every call (``inspect.py:213-217``), which is quadratic in the sample
    count. Replaying once per page and matching against the shared result is
    read-only and pure, so it cannot change the answer -- spot-checked
    against ``bind_source_text`` directly across this corpus before use.
    Kept in lockstep with ``inspect.py:199-291``; a divergence there needs
    the same fix here.
    """
    if not streams:
        return BindingFailure(RejectReason.NO_MATCH, "page has no content streams")
    if replay.malformed:
        return BindingFailure(
            RejectReason.MALFORMED_STREAM,
            "content stream contains constructs the replay cannot account for",
        )
    try:
        target_bytes = target_text.encode("latin-1")
    except UnicodeEncodeError:
        return BindingFailure(
            RejectReason.UNDECODABLE_TARGET,
            "target text is outside byte-level (latin-1) matching",
        )
    candidates = [s for s in replay.shows if s.decoded_bytes == target_bytes]
    if not candidates:
        if replay.has_xobject_invocation:
            return BindingFailure(
                RejectReason.TARGET_IN_FORM_XOBJECT,
                "target not in the direct page stream",
            )
        return BindingFailure(
            RejectReason.NO_MATCH, "no show operator decodes to the target text"
        )
    if expected_origin is not None:
        near = [
            s
            for s in candidates
            if abs(_origin_in_page_space(page, s)[0] - expected_origin[0]) <= tol
            and abs(_origin_in_page_space(page, s)[1] - expected_origin[1]) <= tol
        ]
        if not near:
            return BindingFailure(
                RejectReason.EVIDENCE_MISMATCH,
                f"text matched {len(candidates)} operator(s) but none within "
                f"{tol}pt of the expected origin",
            )
        candidates = near
    if len(candidates) != 1:
        return BindingFailure(
            RejectReason.AMBIGUOUS_MATCH,
            f"{len(candidates)} indistinguishable source candidates",
        )
    show = candidates[0]
    if not show.origin_reliable:
        return BindingFailure(
            RejectReason.UNTRACKED_ADVANCE,
            "origin depends on a preceding show operator's advance",
        )
    if not show.in_bt:
        return BindingFailure(
            RejectReason.UNSUPPORTED_TEXT_STATE, "show operator outside BT/ET"
        )
    if not show.trm_uniform_scaled:
        return BindingFailure(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            "combined text/transform matrix is rotated, sheared, reflected, "
            "or non-uniformly scaled",
        )
    stream_bytes = dict(streams)[show.stream_xref]
    return SourceSpanBinding(
        page_xref=page.xref,
        stream_xref=show.stream_xref,
        stream_digest=hashlib.sha256(stream_bytes).hexdigest(),
        show=show,
        origin_page=_origin_in_page_space(page, show),
    )


def _identity_plan_survival(
    page_capabilities: dict[str, FontCapability],
    page_widgets_or_signed: bool,
    binding: SourceSpanBinding,
    target_text: str,
) -> tuple[bool, str | None]:
    """``prepare_tier0_plan``'s structural/font/encoding gates, identity-mode.

    Runs ``plan.py:130-226``'s checks in the same order, omitting six gates
    that test a *live edit request* rather than the source text/font:
    ``STYLE_OVERRIDE_PRESENT``, ``GEOMETRY_OVERRIDE_PRESENT``,
    ``PENDING_MAINTENANCE``, ``EMPTY_REPLACEMENT``, ``MULTILINE_REPLACEMENT``
    (none apply -- there is no live request, and a resolved line/run target
    is never empty or multiline), and ``NO_CHANGE`` (an identity replacement
    always trips this first, which would fail every sample identically and
    measure nothing -- the entire point of driving identity here).
    ``ADVANCE_MISMATCH`` is skipped from the other side: replacement text
    identical to target text has identical advance by construction (same
    codes, same size/Tc/Tw), so the comparison in ``plan.py:217-226`` can
    never fail and adds no information. This is the "isolates structural
    survival from the advance gate" the measurement spec asks for.
    """
    if page_widgets_or_signed:
        return False, RejectReason.SIGNED_OR_WIDGET_TARGET
    show = binding.show
    if show.operator != "Tj" or show.string_kind not in ("literal", "hex"):
        return False, RejectReason.NOT_SINGLE_LITERAL_TJ
    if show.render_mode != 0 or show.rise != 0.0 or show.hscale != 100.0:
        return False, RejectReason.UNSUPPORTED_TEXT_STATE
    if show.mc_depth != 0:
        return False, RejectReason.UNSUPPORTED_TEXT_STATE
    if show.font_resource is None:
        return False, RejectReason.FONT_FACE_UNAVAILABLE
    capability = page_capabilities.get(show.font_resource)
    if capability is None:
        return False, RejectReason.FONT_FACE_UNAVAILABLE
    if capability.tier0_reject_reason is not None:
        return False, capability.tier0_reject_reason
    source_encoded = capability.encode_simple(target_text)
    if source_encoded is None or source_encoded != show.decoded_bytes:
        return False, RejectReason.ENCODING_FAILED
    if capability.uncovered_codes(target_text):
        return False, RejectReason.FONT_WIDTHS_INCOMPLETE
    return True, None


def _font_has_tabular_digits(capability: FontCapability) -> bool:
    """Codes 0x30-0x39 all carry an equal, positive declared width."""
    if capability.advance_source != "widths":
        return False
    widths = [capability.width_of_code(code) for code in range(0x30, 0x3A)]
    if any(w is None for w in widths):
        return False
    lo, hi = min(widths), max(widths)  # type: ignore[type-var]
    return (hi - lo) <= _TABULAR_TOL


def _tj_has_kern_number(stream_bytes: bytes, show: ShowOp) -> bool:
    """True if a ``TJ`` array's own byte range contains a numeric operand."""
    chunk = stream_bytes[show.string_start : show.string_end]
    return any(t.kind == TokenKind.NUMBER for t in lex_content_stream(chunk))


def _xobject_replays_for_page(
    doc: fitz.Document, page: fitz.Page, cache: dict[int, PageReplay]
) -> list[PageReplay]:
    """Replay every Form XObject the page's own ``/Resources`` invokes.

    Cached by xref at the document level: the same header/footer/logo
    XObject is typically invoked by every page, so each unique one is
    replayed once regardless of how many pages or samples ask about it.
    One level only -- a Form XObject's own stream invoking a further Form
    XObject is not followed (out of scope for this diagnostic).
    """
    try:
        xobjects = page.get_xobjects()
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return []
    replays: list[PageReplay] = []
    for entry in xobjects:
        xref = entry[0]
        if xref not in cache:
            try:
                data = doc.xref_stream(xref) or b""
            except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
                data = b""
            cache[xref] = replay_page_streams([(xref, data)])
        replays.append(cache[xref])
    return replays


def _target_confirmed_in_xobjects(
    target_text: str, xobject_replays: list[PageReplay]
) -> bool:
    """Byte-level presence only -- see module docstring (e) for why no
    origin check is possible here. A ``True`` result means production's
    ``TARGET_IN_FORM_XOBJECT`` label is at least plausible for this target.
    """
    try:
        target_bytes = target_text.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return any(
        any(s.decoded_bytes == target_bytes for s in xobj_replay.shows)
        for xobj_replay in xobject_replays
    )


@dataclass
class _FunnelCounts:
    samples_line: int = 0
    samples_run: int = 0
    resolve_survivors: int = 0
    resolve_fail: Counter = None  # type: ignore[assignment]
    bind_survivors: int = 0
    bind_fail: Counter = None  # type: ignore[assignment]
    plan_survivors: int = 0
    plan_fail: Counter = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.resolve_fail = Counter()
        self.bind_fail = Counter()
        self.plan_fail = Counter()

    @property
    def samples_total(self) -> int:
        return self.samples_line + self.samples_run

    def to_dict(self) -> dict[str, object]:
        return {
            "samples_total": self.samples_total,
            "samples_line": self.samples_line,
            "samples_run": self.samples_run,
            "resolve_survivors": self.resolve_survivors,
            "resolve_fail_reasons": dict(sorted(self.resolve_fail.items())),
            "bind_survivors": self.bind_survivors,
            "bind_fail_reasons": dict(sorted(self.bind_fail.items())),
            "plan_survivors": self.plan_survivors,
            "plan_fail_reasons": dict(sorted(self.plan_fail.items())),
        }


def measure_document(
    doc: fitz.Document, line_cap: int, run_cap: int
) -> dict[str, object]:
    model = _StubModel(doc)
    registry = DocumentFontRegistry(doc)

    funnel = _FunnelCounts()
    fwd_shows_total = 0
    fwd_with_successor = 0
    fwd_dependent = 0
    tj_total = 0
    tj_has_kern = 0
    tj_no_kern_single = 0
    tj_no_kern_multi = 0
    fonts_seen: dict[tuple[int, str, int], FontCapability] = {}
    show_font_total = 0
    show_font_tabular = 0
    pages_with_xobject_invocation = 0
    shows_on_xobject_invoking_pages = 0
    xobject_cache: dict[int, PageReplay] = {}
    xobject_confirmed = 0
    xobject_reclassified_no_match = 0
    xobject_reclassified_reconstruction_unverified = 0

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        streams = read_page_streams(doc, page)
        replay = replay_page_streams(streams)
        stream_map = dict(streams)
        page_widgets_or_signed = page_has_widgets_or_signatures(doc, page)

        # -- (b) forward advance-dependency --
        shows = replay.shows
        fwd_shows_total += len(shows)
        for i in range(len(shows) - 1):
            fwd_with_successor += 1
            if not shows[i + 1].origin_reliable:
                fwd_dependent += 1

        if replay.has_xobject_invocation:
            pages_with_xobject_invocation += 1
            shows_on_xobject_invoking_pages += len(shows)

        # -- (c) tabular digits + (d) TJ binding-survival, per show --
        page_capabilities = registry.page_capabilities(page)
        for show in shows:
            if show.font_resource is not None:
                capability = page_capabilities.get(show.font_resource)
                if capability is not None:
                    show_font_total += 1
                    key = (
                        capability.owner_xref,
                        capability.resource_name,
                        capability.font_xref,
                    )
                    fonts_seen.setdefault(key, capability)
                    if _font_has_tabular_digits(capability):
                        show_font_tabular += 1
            if show.operator == "TJ":
                tj_total += 1
                has_kern = _tj_has_kern_number(stream_map[show.stream_xref], show)
                if has_kern:
                    tj_has_kern += 1
                elif show.array_item_count == 1:
                    tj_no_kern_single += 1
                else:
                    tj_no_kern_multi += 1

        # -- (a) edit-level funnel: resolve -> bind -> plan, identity mode --
        runs = model.block_manager.get_runs(page_idx)
        if not runs:
            continue
        samples, line_count, run_count = _line_and_run_samples(runs, line_cap, run_cap)
        funnel.samples_line += line_count
        funnel.samples_run += run_count
        for member_ids in samples:
            resolve_result = _build_resolve_result(runs, member_ids)
            target = _tier0_target_from_resolve(model, page_idx, resolve_result)
            if target is None:
                funnel.resolve_fail[RejectReason.MULTI_SPAN_TARGET] += 1
                continue
            funnel.resolve_survivors += 1

            binding = _bind_against_replay(
                page, streams, replay, target_text=target.text, expected_origin=target.origin
            )
            if isinstance(binding, BindingFailure):
                # (e): TARGET_IN_FORM_XOBJECT is reported as production would
                # (comparability), but is independently re-checked rather
                # than trusted -- see module docstring (e).
                if binding.reason == RejectReason.TARGET_IN_FORM_XOBJECT:
                    xobj_replays = _xobject_replays_for_page(doc, page, xobject_cache)
                    if _target_confirmed_in_xobjects(target.text, xobj_replays):
                        xobject_confirmed += 1
                    else:
                        deconflated = _reconstruction_aware_reason(
                            RejectReason.NO_MATCH, target
                        )
                        if deconflated == RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED:
                            xobject_reclassified_reconstruction_unverified += 1
                        else:
                            xobject_reclassified_no_match += 1
                    funnel.bind_fail[binding.reason] += 1
                else:
                    reason = _reconstruction_aware_reason(binding.reason, target)
                    funnel.bind_fail[reason] += 1
                continue
            funnel.bind_survivors += 1

            ok, reason = _identity_plan_survival(
                page_capabilities, page_widgets_or_signed, binding, target.text
            )
            if ok:
                funnel.plan_survivors += 1
            else:
                funnel.plan_fail[reason] += 1  # type: ignore[index]

    tabular_fonts = sum(
        1 for cap in fonts_seen.values() if _font_has_tabular_digits(cap)
    )
    widths_fonts = sum(
        1 for cap in fonts_seen.values() if cap.advance_source == "widths"
    )

    return {
        "pages": doc.page_count,
        "funnel": {
            "line_cap_per_page": line_cap,
            "run_cap_per_page": run_cap,
            **funnel.to_dict(),
        },
        "forward_advance": {
            "shows_total": fwd_shows_total,
            "shows_with_successor": fwd_with_successor,
            "forward_dependent": fwd_dependent,
        },
        "tabular_digits": {
            "fonts_with_widths": widths_fonts,
            "fonts_with_tabular_digits": tabular_fonts,
            "shows_with_font_capability": show_font_total,
            "shows_with_tabular_digit_font": show_font_tabular,
        },
        "tj_binding": {
            "tj_total": tj_total,
            "tj_has_kern": tj_has_kern,
            "tj_no_kern_single_string": tj_no_kern_single,
            "tj_no_kern_multi_string": tj_no_kern_multi,
        },
        "xobject_deconfliction": {
            "pages_total": doc.page_count,
            "pages_with_xobject_invocation": pages_with_xobject_invocation,
            "shows_total": fwd_shows_total,
            "shows_on_xobject_invoking_pages": shows_on_xobject_invoking_pages,
            "target_in_form_xobject_bind_failures": funnel.bind_fail.get(
                RejectReason.TARGET_IN_FORM_XOBJECT, 0
            ),
            "confirmed_in_xobject": xobject_confirmed,
            "reclassified_no_match": xobject_reclassified_no_match,
            "reclassified_reconstruction_unverified": (
                xobject_reclassified_reconstruction_unverified
            ),
        },
    }


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return (numerator / denominator) if denominator else None


def _aggregate(rows: list[dict[str, object]]) -> dict[str, object]:
    """Show-weighted (raw sums) and document-weighted (mean of per-doc rates)."""
    show_weighted: dict[str, object] = {
        "funnel": {
            "samples_total": 0,
            "resolve_survivors": 0,
            "resolve_fail_reasons": Counter(),
            "bind_survivors": 0,
            "bind_fail_reasons": Counter(),
            "plan_survivors": 0,
            "plan_fail_reasons": Counter(),
        },
        "forward_advance": {
            "shows_with_successor": 0,
            "forward_dependent": 0,
        },
        "tabular_digits": {
            "fonts_with_widths": 0,
            "fonts_with_tabular_digits": 0,
            "shows_with_font_capability": 0,
            "shows_with_tabular_digit_font": 0,
        },
        "tj_binding": {
            "tj_total": 0,
            "tj_has_kern": 0,
            "tj_no_kern_single_string": 0,
            "tj_no_kern_multi_string": 0,
        },
        "xobject_deconfliction": {
            "pages_total": 0,
            "pages_with_xobject_invocation": 0,
            "shows_total": 0,
            "shows_on_xobject_invoking_pages": 0,
            "target_in_form_xobject_bind_failures": 0,
            "confirmed_in_xobject": 0,
            "reclassified_no_match": 0,
            "reclassified_reconstruction_unverified": 0,
        },
    }
    doc_rates: dict[str, list[float]] = {
        "resolve_rate": [],
        "bind_rate": [],
        "plan_rate": [],
        "forward_dependent_rate": [],
        "tabular_font_rate": [],
        "tabular_show_rate": [],
        "tj_no_kern_rate": [],
        "xobject_pages_flagged_rate": [],
        "xobject_label_confirmed_rate": [],
    }

    for row in rows:
        f = row["funnel"]  # type: ignore[index]
        sw_f = show_weighted["funnel"]  # type: ignore[index]
        sw_f["samples_total"] += f["samples_total"]
        sw_f["resolve_survivors"] += f["resolve_survivors"]
        sw_f["resolve_fail_reasons"].update(f["resolve_fail_reasons"])
        sw_f["bind_survivors"] += f["bind_survivors"]
        sw_f["bind_fail_reasons"].update(f["bind_fail_reasons"])
        sw_f["plan_survivors"] += f["plan_survivors"]
        sw_f["plan_fail_reasons"].update(f["plan_fail_reasons"])

        fa = row["forward_advance"]  # type: ignore[index]
        sw_fa = show_weighted["forward_advance"]  # type: ignore[index]
        sw_fa["shows_with_successor"] += fa["shows_with_successor"]
        sw_fa["forward_dependent"] += fa["forward_dependent"]

        td = row["tabular_digits"]  # type: ignore[index]
        sw_td = show_weighted["tabular_digits"]  # type: ignore[index]
        sw_td["fonts_with_widths"] += td["fonts_with_widths"]
        sw_td["fonts_with_tabular_digits"] += td["fonts_with_tabular_digits"]
        sw_td["shows_with_font_capability"] += td["shows_with_font_capability"]
        sw_td["shows_with_tabular_digit_font"] += td["shows_with_tabular_digit_font"]

        tj = row["tj_binding"]  # type: ignore[index]
        sw_tj = show_weighted["tj_binding"]  # type: ignore[index]
        sw_tj["tj_total"] += tj["tj_total"]
        sw_tj["tj_has_kern"] += tj["tj_has_kern"]
        sw_tj["tj_no_kern_single_string"] += tj["tj_no_kern_single_string"]
        sw_tj["tj_no_kern_multi_string"] += tj["tj_no_kern_multi_string"]

        xo = row["xobject_deconfliction"]  # type: ignore[index]
        sw_xo = show_weighted["xobject_deconfliction"]  # type: ignore[index]
        sw_xo["pages_total"] += xo["pages_total"]
        sw_xo["pages_with_xobject_invocation"] += xo["pages_with_xobject_invocation"]
        sw_xo["shows_total"] += xo["shows_total"]
        sw_xo["shows_on_xobject_invoking_pages"] += xo["shows_on_xobject_invoking_pages"]
        sw_xo["target_in_form_xobject_bind_failures"] += xo[
            "target_in_form_xobject_bind_failures"
        ]
        sw_xo["confirmed_in_xobject"] += xo["confirmed_in_xobject"]
        sw_xo["reclassified_no_match"] += xo["reclassified_no_match"]
        sw_xo["reclassified_reconstruction_unverified"] += xo[
            "reclassified_reconstruction_unverified"
        ]

        if f["samples_total"]:
            doc_rates["resolve_rate"].append(f["resolve_survivors"] / f["samples_total"])
        if f["resolve_survivors"]:
            doc_rates["bind_rate"].append(f["bind_survivors"] / f["resolve_survivors"])
        if f["bind_survivors"]:
            doc_rates["plan_rate"].append(f["plan_survivors"] / f["bind_survivors"])
        if fa["shows_with_successor"]:
            doc_rates["forward_dependent_rate"].append(
                fa["forward_dependent"] / fa["shows_with_successor"]
            )
        if td["fonts_with_widths"]:
            doc_rates["tabular_font_rate"].append(
                td["fonts_with_tabular_digits"] / td["fonts_with_widths"]
            )
        if td["shows_with_font_capability"]:
            doc_rates["tabular_show_rate"].append(
                td["shows_with_tabular_digit_font"] / td["shows_with_font_capability"]
            )
        if tj["tj_total"]:
            no_kern = tj["tj_no_kern_single_string"] + tj["tj_no_kern_multi_string"]
            doc_rates["tj_no_kern_rate"].append(no_kern / tj["tj_total"])
        if xo["pages_total"]:
            doc_rates["xobject_pages_flagged_rate"].append(
                xo["pages_with_xobject_invocation"] / xo["pages_total"]
            )
        if xo["target_in_form_xobject_bind_failures"]:
            doc_rates["xobject_label_confirmed_rate"].append(
                xo["confirmed_in_xobject"] / xo["target_in_form_xobject_bind_failures"]
            )

    sw_f = show_weighted["funnel"]  # type: ignore[index]
    sw_f["resolve_fail_reasons"] = dict(sorted(sw_f["resolve_fail_reasons"].items()))
    sw_f["bind_fail_reasons"] = dict(sorted(sw_f["bind_fail_reasons"].items()))
    sw_f["plan_fail_reasons"] = dict(sorted(sw_f["plan_fail_reasons"].items()))
    sw_f["resolve_rate"] = _safe_ratio(sw_f["resolve_survivors"], sw_f["samples_total"])
    sw_f["bind_rate"] = _safe_ratio(sw_f["bind_survivors"], sw_f["resolve_survivors"])
    sw_f["plan_rate"] = _safe_ratio(sw_f["plan_survivors"], sw_f["bind_survivors"])

    sw_fa = show_weighted["forward_advance"]  # type: ignore[index]
    sw_fa["forward_dependent_rate"] = _safe_ratio(
        sw_fa["forward_dependent"], sw_fa["shows_with_successor"]
    )

    sw_td = show_weighted["tabular_digits"]  # type: ignore[index]
    sw_td["tabular_font_rate"] = _safe_ratio(
        sw_td["fonts_with_tabular_digits"], sw_td["fonts_with_widths"]
    )
    sw_td["tabular_show_rate"] = _safe_ratio(
        sw_td["shows_with_tabular_digit_font"], sw_td["shows_with_font_capability"]
    )

    sw_tj = show_weighted["tj_binding"]  # type: ignore[index]
    no_kern_total = sw_tj["tj_no_kern_single_string"] + sw_tj["tj_no_kern_multi_string"]
    sw_tj["tj_no_kern_total"] = no_kern_total
    sw_tj["tj_no_kern_rate"] = _safe_ratio(no_kern_total, sw_tj["tj_total"])

    sw_xo = show_weighted["xobject_deconfliction"]  # type: ignore[index]
    sw_xo["pages_flagged_rate"] = _safe_ratio(
        sw_xo["pages_with_xobject_invocation"], sw_xo["pages_total"]
    )
    sw_xo["label_confirmed_rate"] = _safe_ratio(
        sw_xo["confirmed_in_xobject"], sw_xo["target_in_form_xobject_bind_failures"]
    )

    def _mean(values: list[float]) -> float | None:
        return (sum(values) / len(values)) if values else None

    document_weighted = {
        "documents_counted": {key: len(vals) for key, vals in doc_rates.items()},
        "resolve_rate_mean": _mean(doc_rates["resolve_rate"]),
        "bind_rate_mean": _mean(doc_rates["bind_rate"]),
        "plan_rate_mean": _mean(doc_rates["plan_rate"]),
        "forward_dependent_rate_mean": _mean(doc_rates["forward_dependent_rate"]),
        "tabular_font_rate_mean": _mean(doc_rates["tabular_font_rate"]),
        "tabular_show_rate_mean": _mean(doc_rates["tabular_show_rate"]),
        "tj_no_kern_rate_mean": _mean(doc_rates["tj_no_kern_rate"]),
        "xobject_pages_flagged_rate_mean": _mean(doc_rates["xobject_pages_flagged_rate"]),
        "xobject_label_confirmed_rate_mean": _mean(
            doc_rates["xobject_label_confirmed_rate"]
        ),
    }

    return {"show_weighted": show_weighted, "document_weighted": document_weighted}


def _format_summary(index: int, row: dict[str, object]) -> str:
    f = row["funnel"]  # type: ignore[index]
    fa = row["forward_advance"]  # type: ignore[index]
    td = row["tabular_digits"]  # type: ignore[index]
    tj = row["tj_binding"]  # type: ignore[index]
    xo = row["xobject_deconfliction"]  # type: ignore[index]
    return (
        f"doc[{index}] pages={row['pages']} "
        f"funnel[samples={f['samples_total']} resolve={f['resolve_survivors']} "
        f"bind={f['bind_survivors']} plan={f['plan_survivors']}] "
        f"fwd_advance[shows={fa['shows_total']} dependent={fa['forward_dependent']}"
        f"/{fa['shows_with_successor']}] "
        f"tabular[fonts={td['fonts_with_tabular_digits']}/{td['fonts_with_widths']} "
        f"shows={td['shows_with_tabular_digit_font']}/{td['shows_with_font_capability']}] "
        f"tj[total={tj['tj_total']} kern={tj['tj_has_kern']} "
        f"no_kern={tj['tj_no_kern_single_string'] + tj['tj_no_kern_multi_string']}] "
        f"xobj[pages_flagged={xo['pages_with_xobject_invocation']}/{xo['pages_total']} "
        f"label_confirmed={xo['confirmed_in_xobject']}/"
        f"{xo['target_in_form_xobject_bind_failures']}]"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", help="paths to the PDFs to measure")
    parser.add_argument("--password", default=None, help="owner/user password")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--line-cap", type=int, default=DEFAULT_LINE_CAP_PER_PAGE,
        help="max text-line samples per page (deterministic first-N)",
    )
    parser.add_argument(
        "--run-cap", type=int, default=DEFAULT_RUN_CAP_PER_PAGE,
        help="max single-word-run samples per page (deterministic first-N)",
    )
    args = parser.parse_args(argv)

    rows: list[dict[str, object]] = []
    for doc_index, pdf_path in enumerate(args.pdfs):
        doc = fitz.open(pdf_path)
        try:
            if doc.needs_pass:
                if not args.password or doc.authenticate(args.password) == 0:
                    print(f"error: password required or incorrect for document at index {doc_index}", file=sys.stderr)
                    return 2
            row = measure_document(doc, args.line_cap, args.run_cap)
        finally:
            doc.close()
        rows.append(row)

    aggregate = _aggregate(rows)
    output = {
        "per_document": [{"doc_index": i, **r} for i, r in enumerate(rows)],
        "aggregate": aggregate,
        "methodology": {
            "resolve_bind_plan_driven": True,
            "bind_then_plan_fallback_used": False,
            "identity_replacement": True,
        },
    }

    if args.json:
        print(json.dumps(output))
    else:
        for i, row in enumerate(rows):
            print(_format_summary(i, row))
        agg = aggregate["show_weighted"]
        print(
            "AGGREGATE(show-weighted) "
            f"resolve_rate={agg['funnel']['resolve_rate']} "
            f"bind_rate={agg['funnel']['bind_rate']} "
            f"plan_rate={agg['funnel']['plan_rate']} "
            f"fwd_dependent_rate={agg['forward_advance']['forward_dependent_rate']} "
            f"tabular_font_rate={agg['tabular_digits']['tabular_font_rate']} "
            f"tj_no_kern_rate={agg['tj_binding']['tj_no_kern_rate']} "
            f"xobj_label_confirmed_rate={agg['xobject_deconfliction']['label_confirmed_rate']}"
        )
        dw = aggregate["document_weighted"]
        print(
            "AGGREGATE(document-weighted) "
            f"resolve_rate_mean={dw['resolve_rate_mean']} "
            f"bind_rate_mean={dw['bind_rate_mean']} "
            f"plan_rate_mean={dw['plan_rate_mean']} "
            f"fwd_dependent_rate_mean={dw['forward_dependent_rate_mean']} "
            f"tabular_font_rate_mean={dw['tabular_font_rate_mean']} "
            f"tj_no_kern_rate_mean={dw['tj_no_kern_rate_mean']} "
            f"xobj_label_confirmed_rate_mean={dw['xobject_label_confirmed_rate_mean']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
