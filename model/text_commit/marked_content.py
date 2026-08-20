"""Marked-content wrapper taxonomy, admission, and fingerprint closure.

Task 13 Priority 1: promotes the census taxonomy (plan §2, measured
2026-08-14 — 64.2% of the mc-gated corpus shows sit under a single
default-visible pure ``/OC`` layer) into the production admission gate.

Three responsibilities, one module, fail-closed throughout:

- **Classification** — map one :class:`~model.text_commit.replay.McWrapper`
  to a stable class slug.  The slugs are the census contract verbatim
  (``scripts/wrapper_taxonomy.py`` now delegates here); anything
  unprovable classifies as not admissible.
- **Admission** — :func:`admit_show_wrappers` folds a show's whole
  wrapper stack into one verdict: admitted only when EVERY enclosing
  wrapper is a default-visible pure ``/OC`` layer, the page's BDC/EMC
  pairing is clean, and the splice range lies strictly inside every
  wrapper's span (proof obligation 4).  Rejections carry one of the four
  ``RejectReason.MC_*`` codes with class-slug details only — never
  property names, labels, or values (plan §10).
- **Fingerprint closure** — :func:`update_marked_content_dependencies`
  folds everything admission reads into the page fingerprint (proof
  obligation 5): the resolved ``/Resources /Properties`` mapping (the
  name→target binding itself), each target's canonical object, and each
  OCG's RESOLVED default-config visibility bit (Task 12 lesson: fold by
  resolved shape, so a flip via /ON//OFF arrays or /BaseState goes stale
  no matter which serialized form produced it).

Qt-free by construction (model layer).  No imports from ``inspect.py``
(which imports this module for the fingerprint fold).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import fitz

if TYPE_CHECKING:
    import hashlib

from model.text_commit.cid_fonts import (
    PdfParseError,
    PdfRef,
    canonical_pdf_text,
    parse_pdf_value,
)
from model.text_commit.dto import RejectReason
from model.text_commit.replay import McWrapper, PageReplay, ShowOp

logger = logging.getLogger(__name__)

# Census class slugs — telemetry-facing contract, rename only with a
# migration (they appear in funnel mc_census aggregates and in MC_*
# rejection details).
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

# Classes that ARE a pure /OC layer but whose default-config visibility
# (or membership stability, for OCMDs) is not provably "visible".
_NOT_DEFAULT_VISIBLE_CLASSES = frozenset({CLASS_OC_LAYER_HIDDEN, CLASS_OC_OCMD})

_READ_ERRORS = (RuntimeError, ValueError, PdfParseError, fitz.mupdf.FzErrorBase)


@dataclass(frozen=True)
class McRejection:
    """One admission refusal: a stable ``RejectReason.MC_*`` code plus a
    class-slug-only detail (never a name, label, or property value)."""

    reason: str
    detail: str


# ------------------------------------------------------------------ lookup


def _deref(doc: fitz.Document, value: object, *, hops: int = 4) -> object:
    """Follow indirect-reference chains to a parsed object, bounded."""
    while isinstance(value, PdfRef) and hops > 0:
        try:
            value = parse_pdf_value(doc.xref_object(value.xref))
        except _READ_ERRORS:
            return None
        hops -= 1
    return value


def resolve_properties_mapping(
    doc: fitz.Document, page: fitz.Page
) -> dict[str, object] | None:
    """The page's resolved ``/Resources /Properties`` mapping, or ``None``.

    Values are parsed but deliberately NOT dereferenced: a named entry's
    binding identity is the :class:`PdfRef` itself (re-pointing the name
    at a different object must both reclassify and go stale).

    ``None`` covers "no /Properties", "inherited /Resources" (the page
    object carries none of its own), and "unreadable" alike — admission
    treats every named lookup against ``None`` as unprovable
    (fail-closed), and the fingerprint folds a distinct sentinel.
    """
    try:
        page_obj = parse_pdf_value(doc.xref_object(page.xref))
    except _READ_ERRORS:
        return None
    if not isinstance(page_obj, dict):
        return None
    resources = _deref(doc, page_obj.get("Resources"))
    if not isinstance(resources, dict):
        return None
    properties = _deref(doc, resources.get("Properties"))
    if not isinstance(properties, dict):
        return None
    return properties


def resolve_default_visibility(doc: fitz.Document) -> dict[int, bool]:
    """OCG xref → default-configuration visibility, from the SERIALIZED
    ``/OCProperties``.

    Deliberately NOT ``Document.get_ocgs()``: PyMuPDF's OC descriptor
    (which also drives rendering) is a load-time snapshot that neither
    ``set_layer`` nor raw ``/OCProperties`` writes refresh, while the
    serialized bytes are what every future opener of the committed
    artifact resolves.  Admission and the fingerprint fold must both read
    the serialized truth or a live flip between prepare and commit stays
    invisible.

    Only OCGs listed in ``/OCProperties /OCGs`` appear; an OCG in BOTH
    ``/ON`` and ``/OFF`` resolves hidden (fail-closed on ambiguity), and
    an unreadable or absent config yields ``{}`` (nothing provable).
    Further fail-closed rules (Codex review round, 2026-08-14):
    ``/BaseState`` admits exactly ``/ON``, ``/OFF``, or absence; an
    ``/ON``/``/OFF``/``/AS`` entry PRESENT but not resolvable to its
    expected shape poisons the whole config; and any OCG selected by a
    ``/D /AS`` auto-state entry is dropped from the map entirely — usage
    application can override its base state in a conforming viewer, so
    its default visibility is not provable.
    """
    try:
        cat_obj = parse_pdf_value(doc.xref_object(doc.pdf_catalog()))
    except _READ_ERRORS:
        return {}
    if not isinstance(cat_obj, dict):
        return {}
    ocprops = _deref(doc, cat_obj.get("OCProperties"))
    if not isinstance(ocprops, dict):
        return {}
    registered = _deref(doc, ocprops.get("OCGs"))
    if not isinstance(registered, list):
        return {}
    config = _deref(doc, ocprops.get("D"))
    if not isinstance(config, dict):
        return {}

    def _ref_set(key: str) -> set[int] | None:
        """Ref xrefs under ``key``; ``set()`` when absent; ``None``
        (poison) when present but not provably a list of refs."""
        value = config.get(key)
        if value is None:
            return set()
        array = _deref(doc, value)
        if not isinstance(array, list):
            return None
        refs: set[int] = set()
        for item in array:
            if not isinstance(item, PdfRef):
                return None
            refs.add(item.xref)
        return refs

    raw_base = config.get("BaseState")
    if raw_base is None:
        base_on = True  # spec default
    else:
        # Spec-legal as an indirect name — resolve it; anything that does
        # not resolve to exactly /ON or /OFF (garbage names, /Unchanged,
        # unreadable targets, wrong types) poisons the whole config.
        base_state = _deref(doc, raw_base)
        if base_state == "/ON":
            base_on = True
        elif base_state == "/OFF":
            base_on = False
        else:
            return {}
    on_set = _ref_set("ON")
    off_set = _ref_set("OFF")
    if on_set is None or off_set is None:
        return {}

    as_selected: set[int] = set()
    as_value = config.get("AS")
    if as_value is not None:
        as_array = _deref(doc, as_value)
        if not isinstance(as_array, list):
            return {}
        for entry in as_array:
            entry = _deref(doc, entry)
            if not isinstance(entry, dict):
                return {}
            members = _deref(doc, entry.get("OCGs"))
            if not isinstance(members, list):
                # /OCGs is required in a usage-application dictionary; an
                # absent or unresolvable one leaves the affected set
                # unknowable.
                return {}
            for member in members:
                if not isinstance(member, PdfRef):
                    return {}
                as_selected.add(member.xref)

    visibility: dict[int, bool] = {}
    for item in registered:
        if not isinstance(item, PdfRef):
            continue
        if item.xref in as_selected:
            continue  # usage-application may override: unprovable
        if item.xref in off_set:
            visibility[item.xref] = False
        elif item.xref in on_set:
            visibility[item.xref] = True
        else:
            visibility[item.xref] = base_on
    return visibility


# -------------------------------------------------------- classification


def _semantic_dict_class(keys: set[str]) -> str:
    """Class of a property list by its content-bearing keys, fail-closed."""
    if "ActualText" in keys:
        return CLASS_ACTUAL_TEXT
    if "Alt" in keys:
        return CLASS_ALT
    if "MCID" in keys:
        return CLASS_STRUCT_CONTENT
    return CLASS_BDC_OTHER


def _classify_named_target(
    doc: fitz.Document,
    wrapper: McWrapper,
    target: object,
    visibility: dict[int, bool],
) -> str:
    if isinstance(target, PdfRef):
        xref = target.xref
        try:
            type_kind, type_value = doc.xref_get_key(xref, "Type")
        except _READ_ERRORS:
            return CLASS_PROPS_UNRESOLVED
        type_name = type_value.lstrip("/") if type_kind == "name" else ""
        if type_name == "OCG":
            if wrapper.tag != "OC":
                return CLASS_BDC_OTHER  # OC semantics need the /OC tag
            state = visibility.get(xref)
            if state is None:
                # an OCG absent from /OCProperties has no provable
                # default-config visibility
                return CLASS_PROPS_UNRESOLVED
            if state:
                return CLASS_OC_LAYER_VISIBLE
            return CLASS_OC_LAYER_HIDDEN
        if type_name == "OCMD":
            return CLASS_OC_OCMD if wrapper.tag == "OC" else CLASS_BDC_OTHER
        try:
            keys = set(doc.xref_get_keys(xref) or ())
        except _READ_ERRORS:
            return CLASS_PROPS_UNRESOLVED
        return _semantic_dict_class(keys)
    if isinstance(target, dict):
        keys = {key for key in ("ActualText", "Alt", "MCID") if key in target}
        return _semantic_dict_class(keys)
    return CLASS_PROPS_UNRESOLVED


def classify_wrapper(
    doc: fitz.Document,
    page: fitz.Page,
    wrapper: McWrapper,
    visibility: dict[int, bool],
    mapping: dict[str, object] | None = None,
) -> str:
    """One wrapper's class slug.  Structural defects trump semantics.

    ``visibility`` comes from :func:`resolve_default_visibility`;
    ``mapping`` is the pre-resolved :func:`resolve_properties_mapping`
    result; pass it when classifying many wrappers on one page.  When
    omitted it is resolved here, so single-wrapper callers stay simple.
    """
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
    if mapping is None:
        mapping = resolve_properties_mapping(doc, page)
    target = None if mapping is None else mapping.get(wrapper.props_name or "")
    return _classify_named_target(doc, wrapper, target, visibility)


def classify_wrappers(
    doc: fitz.Document, page: fitz.Page, replay: PageReplay
) -> dict[int, str]:
    """Class slug for every wrapper the page replay observed."""
    if not replay.mc_wrappers:
        return {}
    visibility = resolve_default_visibility(doc)
    mapping = resolve_properties_mapping(doc, page)
    return {
        wrapper.wrapper_id: classify_wrapper(
            doc, page, wrapper, visibility, mapping=mapping
        )
        for wrapper in replay.mc_wrappers
    }


# -------------------------------------------------------------- admission


def splice_range_within_wrapper(
    wrapper: McWrapper, *, stream_xref: int, start: int, end: int
) -> bool:
    """``[start, end)`` lies strictly inside the wrapper's BDC..EMC span,
    in the wrapper's own (single) content stream."""
    if not wrapper.closed or wrapper.close_op_start is None:
        return False
    if wrapper.stream_xref != stream_xref:
        return False
    if wrapper.close_stream_xref != stream_xref:
        return False
    return wrapper.open_op_end <= start and end <= wrapper.close_op_start


def admit_show_wrappers(
    doc: fitz.Document,
    page: fitz.Page,
    show: ShowOp,
    *,
    wrappers: tuple[McWrapper, ...],
    emc_underflows: int,
) -> McRejection | None:
    """Admit or refuse one show's marked-content stack, fail-closed.

    ``None`` means admissible: the show is either outside every wrapper,
    or every enclosing wrapper (outermost-first) is a default-visible
    pure ``/OC`` layer AND the show's whole-operator byte range lies
    strictly inside every wrapper's BDC..EMC span in the show's own
    stream.  ``wrappers`` is the show's ``mc_stack`` resolved against
    ``PageReplay.mc_wrappers``; ``emc_underflows`` is the page total.
    """
    if not wrappers and show.mc_depth == 0:
        return None
    if len(wrappers) != show.mc_depth:
        # Evidence inconsistency (a dropped wrapper id, a clamp artifact):
        # unprovable, never admit.
        return McRejection(
            RejectReason.MC_MALFORMED_PAIRING,
            "wrapper evidence does not account for the show's "
            "marked-content depth",
        )
    if emc_underflows:
        return McRejection(
            RejectReason.MC_MALFORMED_PAIRING,
            "page has EMC underflows; its BDC/EMC pairing evidence is "
            "untrustworthy",
        )
    visibility = resolve_default_visibility(doc)
    mapping = resolve_properties_mapping(doc, page)
    for wrapper in wrappers:
        wrapper_class = classify_wrapper(
            doc, page, wrapper, visibility, mapping=mapping
        )
        if wrapper_class == CLASS_MALFORMED_PAIRING:
            return McRejection(
                RejectReason.MC_MALFORMED_PAIRING,
                "wrapper is unclosed or crosses a q/Q boundary",
            )
        if wrapper_class in _NOT_DEFAULT_VISIBLE_CLASSES:
            return McRejection(
                RejectReason.MC_LAYER_NOT_DEFAULT_VISIBLE,
                f"wrapper class: {wrapper_class}",
            )
        if wrapper_class != CLASS_OC_LAYER_VISIBLE:
            return McRejection(
                RejectReason.MC_WRAPPER_NOT_PURE_LAYER,
                f"wrapper class: {wrapper_class}",
            )
    for wrapper in wrappers:
        if not splice_range_within_wrapper(
            wrapper,
            stream_xref=show.stream_xref,
            start=show.op_start,
            end=show.op_end,
        ):
            return McRejection(
                RejectReason.MC_SPLICE_CROSSES_WRAPPER_BOUNDARY,
                "replacement range does not lie strictly inside every "
                "enclosing wrapper's BDC..EMC span in the show's own stream",
            )
    return None


# ------------------------------------------------- fingerprint dependencies


def _fold_target_structured(
    digest: "hashlib._Hash", doc: fitz.Document, xref: int
) -> None:
    """Fold one property target's structured key/value surface.

    Deliberately the SAME API family classification reads
    (``xref_get_keys``/``xref_get_key``) rather than a whole-object
    parse: an over-parse-budget object still classifies via its ``/Type``
    key, so it must still fold that key (Codex review round — a /Type
    flip on a parse-hostile object previously bypassed STALE_PLAN).
    Sorted keys for order independence; raw ``xref_object`` text is not
    round-trip stable for dictionaries (see
    ``inspect._canonical_object_digest``), the structured surface is.
    """
    try:
        keys = sorted(doc.xref_get_keys(xref) or ())
    except _READ_ERRORS:
        digest.update(b"<unreadable-target>")
        return
    if not keys:
        try:
            digest.update(
                " ".join(doc.xref_object(xref).split()).encode("utf-8", "replace")
            )
        except _READ_ERRORS:
            digest.update(b"<unreadable-target>")
        return
    for key in keys:
        try:
            kind, value = doc.xref_get_key(xref, key)
        except _READ_ERRORS:
            kind, value = "?", "<unreadable>"
        digest.update(f"{key}\x1f{kind}\x1f{value}\x1e".encode("utf-8", "replace"))


def update_marked_content_dependencies(
    digest: "hashlib._Hash", doc: fitz.Document, page: fitz.Page
) -> None:
    """Fold the wrapper-evidence closure into a page fingerprint digest.

    Enumerated (auditable) mirror of what :func:`admit_show_wrappers`
    reads — if admission starts reading another key, it belongs here in
    the same change, or a plan measured under the old value stays
    "fresh":

    - the resolved ``/Properties`` mapping: each name plus its binding
      identity (the target xref for indirect entries), so re-pointing a
      name at a different object goes stale even when both objects'
      contents digest identically;
    - each indirect target's structured key/value surface (OCG, OCMD, or
      property-list dict — covers renames and any key mutation, INCLUDING
      on objects too large for the value parser, which classification
      still reads via ``xref_get_key``);
    - each target's RESOLVED default-config visibility bit from the
      SERIALIZED ``/OCProperties`` (on/off/absent, via
      :func:`resolve_default_visibility` — the same source admission
      reads), so a flip via /ON, /OFF or /BaseState goes stale
      regardless of serialized form;
    - inline (direct-dict) entries canonically.

    The BDC/BMC operands themselves live in the content streams, which
    the fingerprint already folds byte-for-byte.
    """
    digest.update(b"\x07mc")
    mapping = resolve_properties_mapping(doc, page)
    if mapping is None:
        digest.update(b"<no-properties>")
        digest.update(b"\x07")
        return
    visibility = resolve_default_visibility(doc)
    for name in sorted(mapping):
        value = mapping[name]
        # Length-prefixed so the frame stays injective even for a name
        # containing the separator bytes (legal PDF name characters).
        encoded_name = name.encode("utf-8", "replace")
        digest.update(str(len(encoded_name)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded_name)
        digest.update(b"\x1d")
        if isinstance(value, PdfRef):
            digest.update(str(value.xref).encode("ascii"))
            digest.update(b"\x1d")
            _fold_target_structured(digest, doc, value.xref)
            state = visibility.get(value.xref)
            if state is None:
                digest.update(b"\x1dabsent")
            elif state:
                digest.update(b"\x1don")
            else:
                digest.update(b"\x1doff")
        else:
            try:
                digest.update(canonical_pdf_text(value).encode("utf-8"))
            except _READ_ERRORS:
                digest.update(b"<uncanonical-value>")
        digest.update(b"\x1f")
    digest.update(b"\x07")
