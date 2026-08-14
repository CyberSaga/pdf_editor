#!/usr/bin/env python3
"""Marked-content wrapper taxonomy for the Task 13 Priority-1 census.

Read-only, script-layer classification of the BDC/BMC..EMC wrapper
evidence that ``model.text_commit.replay`` captures per show.  Maps each
wrapper to one stable class slug from the plan §2 taxonomy, and folds a
show's whole wrapper stack into a single census verdict: admissible only
when EVERY enclosing wrapper is a pure, default-visible ``/OC`` layer and
the page's BDC/EMC pairing is clean.

This module deliberately lives OUTSIDE ``model/`` (census-before-code):
no admission gate consumes it.  The Priority-1 implementation slice will
promote the accepted classes into ``model/text_commit/plan.py`` behind its
own red matrix.

Aggregate-only (plan §10): classification returns slugs and never emits
tags' property values, layer names, resource names, or document text.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.replay import (  # noqa: E402
    McWrapper,
    PageReplay,
    ShowOp,
)
from scripts.audit_type0_census import (  # noqa: E402
    _dict_key_raw,
    _first_ref,
)

CLASS_OC_LAYER_VISIBLE = "oc_layer_visible_default"
CLASS_OC_LAYER_HIDDEN = "oc_layer_hidden_default"
CLASS_OC_OCMD = "oc_ocmd"
CLASS_ACTUAL_TEXT = "actual_text"
CLASS_ALT = "alt_text"
CLASS_ARTIFACT = "artifact"
CLASS_STRUCT_CONTENT = "struct_content"
CLASS_BMC_BARE = "bmc_bare"
CLASS_BDC_OTHER = "bdc_other"
CLASS_PROPS_UNRESOLVED = "props_unresolved"
CLASS_PROPS_UNPARSED = "props_unparsed"
CLASS_MALFORMED_PAIRING = "malformed_pairing"

VERDICT_ADMISSIBLE = "admissible_pure_layer"
VERDICT_NOT_WRAPPED = "not_wrapped"


def _semantic_dict_class(keys: set[str]) -> str:
    """Class of a property list by its content-bearing keys, fail-closed."""
    if "ActualText" in keys:
        return CLASS_ACTUAL_TEXT
    if "Alt" in keys:
        return CLASS_ALT
    if "MCID" in keys:
        return CLASS_STRUCT_CONTENT
    return CLASS_BDC_OTHER


def _props_lookup(
    doc: fitz.Document, page: fitz.Page, name: str
) -> tuple[str, str]:
    """``(kind, value)`` of the page's ``/Resources /Properties /<name>``.

    The composite-path lookup resolves intermediate indirection; the
    manual two-hop fallback covers producers where it does not.
    """
    kind, value = doc.xref_get_key(page.xref, f"Resources/Properties/{name}")
    if kind != "null":
        return kind, value
    xref = page.xref
    for part in ("Resources", "Properties"):
        part_kind, part_value = doc.xref_get_key(xref, part)
        if part_kind != "xref":
            return "null", "null"
        target = _first_ref(part_value)
        if target is None:
            return "null", "null"
        xref = target
    return doc.xref_get_key(xref, name)


def _classify_named_target(
    doc: fitz.Document,
    wrapper: McWrapper,
    kind: str,
    value: str,
    ocgs: dict[int, dict],
) -> str:
    if kind == "xref":
        xref = _first_ref(value)
        if xref is None:
            return CLASS_PROPS_UNRESOLVED
        type_kind, type_value = doc.xref_get_key(xref, "Type")
        type_name = type_value.lstrip("/") if type_kind == "name" else ""
        if type_name == "OCG":
            if wrapper.tag != "OC":
                return CLASS_BDC_OTHER  # OC semantics need the /OC tag
            info = ocgs.get(xref)
            if info is None:
                # an OCG absent from /OCProperties has no provable
                # default-config visibility
                return CLASS_PROPS_UNRESOLVED
            if info.get("on"):
                return CLASS_OC_LAYER_VISIBLE
            return CLASS_OC_LAYER_HIDDEN
        if type_name == "OCMD":
            return CLASS_OC_OCMD if wrapper.tag == "OC" else CLASS_BDC_OTHER
        try:
            keys = set(doc.xref_get_keys(xref) or ())
        except (RuntimeError, ValueError):
            return CLASS_PROPS_UNRESOLVED
        return _semantic_dict_class(keys)
    if kind == "dict":
        keys = {
            key
            for key in ("ActualText", "Alt", "MCID")
            if _dict_key_raw(value, key) is not None
        }
        return _semantic_dict_class(keys)
    return CLASS_PROPS_UNRESOLVED


def classify_wrapper(
    doc: fitz.Document,
    page: fitz.Page,
    wrapper: McWrapper,
    ocgs: dict[int, dict],
) -> str:
    """One wrapper's class slug.  Structural defects trump semantics."""
    if not wrapper.closed or wrapper.crossed_q:
        return CLASS_MALFORMED_PAIRING
    if wrapper.props_kind == "unparsed":
        return CLASS_PROPS_UNPARSED
    if wrapper.tag == "Artifact":
        return CLASS_ARTIFACT
    if wrapper.operator == "BMC":
        return CLASS_BMC_BARE
    if wrapper.props_kind == "dict":
        return _semantic_dict_class(set(wrapper.props_dict_keys))
    kind, value = _props_lookup(doc, page, wrapper.props_name or "")
    return _classify_named_target(doc, wrapper, kind, value, ocgs)


def classify_wrappers(
    doc: fitz.Document, page: fitz.Page, replay: PageReplay
) -> dict[int, str]:
    """Class slug for every wrapper the page replay observed."""
    if not replay.mc_wrappers:
        return {}
    try:
        ocgs = doc.get_ocgs()
    except (RuntimeError, ValueError):
        ocgs = {}
    return {
        wrapper.wrapper_id: classify_wrapper(doc, page, wrapper, ocgs)
        for wrapper in replay.mc_wrappers
    }


def show_verdict(
    show: ShowOp, classes: dict[int, str], replay: PageReplay
) -> str:
    """Fold one show's wrapper stack into a census verdict slug.

    ``admissible_pure_layer`` only when every enclosing wrapper is a
    default-visible pure ``/OC`` layer and the page shows no EMC
    underflow; otherwise ``mc:<first blocking class>``, outermost-first
    (nested admission requires EVERY wrapper to qualify individually).
    """
    if not show.mc_stack:
        return VERDICT_NOT_WRAPPED
    if replay.mc_emc_underflows:
        return f"mc:{CLASS_MALFORMED_PAIRING}"
    for wrapper_id in show.mc_stack:
        wrapper_class = classes.get(wrapper_id, CLASS_PROPS_UNPARSED)
        if wrapper_class != CLASS_OC_LAYER_VISIBLE:
            return f"mc:{wrapper_class}"
    return VERDICT_ADMISSIBLE
