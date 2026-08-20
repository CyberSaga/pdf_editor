#!/usr/bin/env python3
"""Marked-content wrapper taxonomy for the Task 13 census scripts.

The classification itself was PROMOTED into
``model/text_commit/marked_content.py`` by the Priority-1 admission
slice (Task 13 step 2) behind its own red matrix
(``test_scripts/test_text_commit_mc_admission.py``); this module now
re-exports the production classifier so the census keeps a single
source of truth, and keeps only the census-facing verdict fold.

Aggregate-only (plan §10): classification returns slugs and never emits
tags' property values, layer names, resource names, or document text.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.marked_content import (  # noqa: E402,F401
    CLASS_ACTUAL_TEXT,
    CLASS_ALT,
    CLASS_ARTIFACT,
    CLASS_BDC_OTHER,
    CLASS_BMC_BARE,
    CLASS_MALFORMED_PAIRING,
    CLASS_OC_LAYER_HIDDEN,
    CLASS_OC_LAYER_VISIBLE,
    CLASS_OC_OCMD,
    CLASS_PROPS_UNPARSED,
    CLASS_PROPS_UNRESOLVED,
    CLASS_STRUCT_CONTENT,
    VERDICT_ADMISSIBLE,
    VERDICT_NOT_WRAPPED,
    classify_wrapper,
    classify_wrappers,
)
from model.text_commit.replay import PageReplay, ShowOp  # noqa: E402


def show_verdict(
    show: ShowOp, classes: dict[int, str], replay: PageReplay
) -> str:
    """Fold one show's wrapper stack into a census verdict slug.

    ``admissible_pure_layer`` only when every enclosing wrapper is a
    default-visible pure ``/OC`` layer and the page shows no EMC
    underflow; otherwise ``mc:<first blocking class>``, outermost-first
    (nested admission requires EVERY wrapper to qualify individually).

    Census-only: the production admission
    (``marked_content.admit_show_wrappers``) additionally enforces the
    splice boundary guard, which needs byte ranges this census fold
    deliberately ignores.
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
