"""Source binding: map visible text to its content-stream operator.

Binds a target string to exactly one replayed show operation, corroborated
by rawdict geometry.  Anything ambiguous, malformed, out-of-page-stream,
or in unsupported text state returns a :class:`BindingFailure` with a
stable :class:`~model.text_commit.dto.RejectReason` code — never a
best-score guess (plan Task 3).

``EditableSpan``/rawdict data are geometric *hints* only; the binding's
identity is (page xref, stream xref, digest, byte ranges).
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

import fitz

from model.text_commit.cid_fonts import (
    CidCapabilityFailure,
    PdfParseError,
    PdfRef,
    canonical_pdf_text,
    parse_pdf_value,
)
from model.text_commit.dto import RejectReason
from model.text_commit.fonts import DocumentFontRegistry, FontCapability
from model.text_commit.marked_content import update_marked_content_dependencies
from model.text_commit.transforms import admission_verdict
from model.text_commit.replay import (
    McWrapper,
    PageReplay,
    ShowOp,
    replay_page_streams,
)

logger = logging.getLogger(__name__)

# Task 13 P2 (§10 privacy): one fixed, code-only detail per trm_* refusal —
# never a matrix coefficient, which can fingerprint a private document's
# producer pipeline.
_TRM_REJECT_DETAILS = {
    RejectReason.TRM_NON_FINITE: (
        "combined text/transform matrix has non-finite components"
    ),
    RejectReason.TRM_SINGULAR: "combined text/transform matrix is singular",
    RejectReason.TRM_SCALE_BELOW_FLOOR: (
        "combined text/transform matrix baseline scale is below the "
        "absolute floor"
    ),
    RejectReason.TRM_REFLECTED: (
        "combined text/transform matrix has negative orientation "
        "(reflection)"
    ),
    RejectReason.TRM_SHEARED: (
        "combined text/transform matrix has non-orthogonal axes (shear)"
    ),
    RejectReason.TRM_NON_UNIFORM_SCALE: (
        "combined text/transform matrix scales its axes unequally"
    ),
    RejectReason.TRM_ROTATION_NOT_QUARTER_TURN: (
        "combined text/transform matrix rotation is not a visual "
        "quarter turn"
    ),
}


@dataclass(frozen=True)
class SourceSpanBinding:
    """A verified, unambiguous mapping from target text to one show op."""

    page_xref: int
    stream_xref: int
    stream_digest: str  # SHA-256 of the bound stream's decoded bytes
    show: ShowOp
    # Visual (pixmap) page space -- transformation_matrix * rotation_matrix,
    # NOT raw page.get_text('rawdict') convention (that stays unrotated).
    origin_page: tuple[float, float]
    # Task 13 P1: the show's marked-content stack resolved against
    # ``PageReplay.mc_wrappers`` (outermost-first) plus the page's EMC
    # underflow count -- the evidence ``plan.py``'s admission gate folds.
    mc_wrappers: tuple[McWrapper, ...] = ()
    mc_emc_underflows: int = 0


@dataclass(frozen=True)
class BindingFailure:
    reason: str  # a RejectReason constant
    detail: str


def read_page_streams(
    doc: fitz.Document, page: fitz.Page
) -> list[tuple[int, bytes]]:
    """Ordered ``(xref, decoded_bytes)`` list of the page's content streams."""
    return [(xref, doc.xref_stream(xref) or b"") for xref in page.get_contents()]


# Font dictionary keys whose values feed Tier 0 capability classification:
# the width table and the code range that indexes it, the encoding that
# decides simple-ness, and the descriptor carrying the glyph-repertoire
# attestation.  Each may be an indirect object.
_FONT_DEPENDENCY_KEYS = (
    "Widths",
    "FirstChar",
    "LastChar",
    "Encoding",
    "FontDescriptor",
)

def _indirect_target(doc: fitz.Document, xref: int, key: str) -> int | None:
    """The xref ``key`` points at, or ``None`` when it is not indirect."""
    kind, value = doc.xref_get_key(xref, key)
    if kind != "xref":
        return None
    try:
        return int(value.split()[0])
    except (ValueError, IndexError):
        return None


def _canonical_object_digest(doc: fitz.Document, xref: int) -> bytes:
    # doc.xref_object()'s key order is not stable across a
    # tobytes(encryption=KEEP) round trip on a disk-loaded *dictionary*
    # object (MuPDF re-serializes with a different dict key order, same
    # keys/values), so hash the structured key/value API instead, sorted
    # for order-independence. Arrays/scalars/strings have no keys to
    # reorder (xref_get_keys is [] for them too, indistinguishable from an
    # empty dict) and are not observed to reformat across the round trip,
    # so fall back to the raw object string rather than silently hashing
    # nothing -- e.g. an indirect /Widths array must still be covered.
    keys = sorted(doc.xref_get_keys(xref))
    if not keys:
        return " ".join(doc.xref_object(xref).split()).encode("utf-8")
    parts = []
    for key in keys:
        kind, value = doc.xref_get_key(xref, key)
        parts.append(f"{key}\x1f{kind}\x1f{value}")
    return "\x1e".join(parts).encode("utf-8")


def _fold_stream(digest: "hashlib._Hash", doc: fitz.Document, xref: int) -> None:
    """Fold one stream's DECODED bytes (raw bytes are not stable across a
    ``tobytes()`` scratch round trip that recompresses)."""
    try:
        digest.update(doc.xref_stream(xref) or b"")
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        digest.update(b"<unreadable-stream>")
    digest.update(b"\x1f")


def _fold_canonical_value(
    digest: "hashlib._Hash", doc: fitz.Document, kind: str, value: str
) -> None:
    """Fold one key's value in a serialization-independent form.

    Container values (dicts/arrays — most importantly the INLINE
    descendant form of ``/DescendantFonts``) are parsed and canonicalized:
    MuPDF may re-order a dictionary's keys across a ``tobytes()`` round
    trip, and hashing the raw value text would then make every live→
    scratch comparison falsely stale.  Scalars fold as-is.
    """
    if kind in ("dict", "array"):
        try:
            canonical = canonical_pdf_text(parse_pdf_value(value))
        except PdfParseError:
            canonical = "raw:" + " ".join(value.split())
        digest.update(canonical.encode("utf-8"))
    else:
        digest.update(f"{kind}:{value}".encode("utf-8", "replace"))
    digest.update(b"\x1f")


def _update_type0_dependencies(
    digest: "hashlib._Hash", doc: fitz.Document, font_xref: int
) -> None:
    """Fold the FULL Type0 evidence closure (Task 12 P0-D).

    Mirrors exactly what ``cid_fonts.build_identity_h_cid_capability``
    reads — the auditable-enumeration rule below applies here too: the
    font dictionary itself (canonical per key), the /ToUnicode stream, the
    descendant (inline or indirect, canonical), its indirect /W and
    /FontDescriptor targets, the /CIDToGIDMap stream, and the /FontFile2
    program bytes.  Without this closure, mutating any of those between
    prepare and commit leaves the fingerprint byte-identical and a stale
    plan commits against dead width/glyph evidence.
    """
    for key in sorted(doc.xref_get_keys(font_xref)):
        kind, value = doc.xref_get_key(font_xref, key)
        digest.update(key.encode("utf-8", "replace"))
        digest.update(b"\x1d")
        _fold_canonical_value(digest, doc, kind, value)
    tounicode_target = _indirect_target(doc, font_xref, "ToUnicode")
    if tounicode_target is not None:
        _fold_stream(digest, doc, tounicode_target)

    try:
        kind, value = doc.xref_get_key(font_xref, "DescendantFonts")
        if kind == "xref":
            value = doc.xref_object(int(value.split()[0]))
        parsed = parse_pdf_value(value)
    except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase, PdfParseError):
        digest.update(b"<unreadable-descendants>")
        return
    descendant: object = parsed[0] if isinstance(parsed, list) and parsed else None
    if isinstance(descendant, PdfRef):
        try:
            descendant = parse_pdf_value(doc.xref_object(descendant.xref))
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase, PdfParseError):
            digest.update(b"<unreadable-descendant>")
            return
    if not isinstance(descendant, dict):
        return
    # Fold the descendant canonically on EVERY arrival path, not only the
    # PdfRef one: an inline dict reached through an INDIRECT /DescendantFonts
    # array object otherwise leaves its direct /W, /DW, /CIDToGIDMap-name and
    # /Subtype values outside the fingerprint while the capability builder
    # accepts the form (post-review pin, wf_1757a5fb-8e9).  The direct-inline
    # form gets folded twice (font-dict key loop + here) — harmless, both
    # sides of a staleness comparison fold identically.
    digest.update(canonical_pdf_text(descendant).encode("utf-8"))
    digest.update(b"\x1f")
    for key in ("W", "DW", "FontDescriptor"):
        target = descendant.get(key)
        if isinstance(target, PdfRef):
            try:
                digest.update(
                    canonical_pdf_text(
                        parse_pdf_value(doc.xref_object(target.xref))
                    ).encode("utf-8")
                )
            except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase, PdfParseError):
                digest.update(b"<unreadable-target>")
            digest.update(b"\x1f")
    cidtogid = descendant.get("CIDToGIDMap")
    if isinstance(cidtogid, PdfRef):
        _fold_stream(digest, doc, cidtogid.xref)
    descriptor = descendant.get("FontDescriptor")
    if isinstance(descriptor, PdfRef):
        try:
            descriptor = parse_pdf_value(doc.xref_object(descriptor.xref))
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase, PdfParseError):
            descriptor = None
    if isinstance(descriptor, dict):
        font_file = descriptor.get("FontFile2")
        if isinstance(font_file, PdfRef):
            _fold_stream(digest, doc, font_file.xref)


def _update_font_dependencies(
    digest: "hashlib._Hash", doc: fitz.Document, font_xref: int
) -> None:
    """Fold one font's object and every indirect object it depends on.

    Enumerated rather than followed generically so the set is auditable: if
    capability classification starts reading another key, it belongs here in
    the same change, or a plan measured under the old value stays "fresh".
    """
    kind, subtype_value = doc.xref_get_key(font_xref, "Subtype")
    if kind == "name" and subtype_value == "/Type0":
        # The Type0 closure REPLACES the generic path: the generic
        # _canonical_object_digest folds the raw /DescendantFonts value
        # text, which is not serialization-stable for the inline form.
        _update_type0_dependencies(digest, doc, font_xref)
        digest.update(b"\x06")
        return
    digest.update(_canonical_object_digest(doc, font_xref))
    for key in _FONT_DEPENDENCY_KEYS:
        target = _indirect_target(doc, font_xref, key)
        if target is None:
            continue
        try:
            digest.update(_canonical_object_digest(doc, target))
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            digest.update(b"<unreadable>")
            continue
    # /Flags carries the glyph-repertoire attestation and may be indirect
    # whether its descriptor is inline or an indirect object; the path form
    # resolves both shapes in one lookup.
    flags_target = _indirect_target(doc, font_xref, "FontDescriptor/Flags")
    if flags_target is not None:
        try:
            digest.update(_canonical_object_digest(doc, flags_target))
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            digest.update(b"<unreadable>")
    digest.update(b"\x06")


def _update_page_geometry(
    digest: hashlib._Hash, doc: fitz.Document, page: fitz.Page
) -> None:
    """Fold the resolved page geometry into a fingerprint digest.

    RESOLVED values only (never raw dict shape): ``page.rotation`` /
    ``page.mediabox`` / ``page.cropbox`` resolve page-tree inheritance, so
    a direct ``/Rotate 270`` and the same value inherited from ``/Pages``
    fold identically while an ancestor mutation still changes the fold.
    ``/UserUnit`` is not inheritable; it is read off the page dict with
    one indirect hop resolved and folded as a canonical NUMBER (review
    F4): MuPDF re-serializes an integer-valued real spelling (``2.0``)
    minimally as the int ``2`` on save, so a raw ``kind:value`` fold
    would flip ``float:2`` → ``int:2`` across the live→scratch round
    trip and fail every prepare on such a document.  The live visual
    matrices are folded too:
    they are what plan/verify geometry actually consumes, so any
    divergence between serialized state and a computed view goes stale
    instead of slipping through.
    """
    try:
        kind, value = doc.xref_get_key(page.xref, "UserUnit")
        if kind == "xref":
            value = doc.xref_object(int(value.split()[0]))
        try:
            user_unit = f"num:{float(value)!r}"
        except ValueError:
            # Non-numeric (including the "null:null" absent case): the
            # raw pair is the only stable identity available.
            user_unit = f"{kind}:{value}"
    except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase):
        user_unit = "<unreadable-user-unit>"
    tm = page.transformation_matrix
    rm = page.rotation_matrix
    parts = (
        str(page.rotation),
        repr(tuple(page.mediabox)),
        repr(tuple(page.cropbox)),
        user_unit,
        repr((tm.a, tm.b, tm.c, tm.d, tm.e, tm.f)),
        repr((rm.a, rm.b, rm.c, rm.d, rm.e, rm.f)),
    )
    digest.update("|".join(parts).encode("utf-8"))
    digest.update(b"\x06")


def page_fingerprint(doc: fitz.Document, page: fitz.Page) -> str:
    """Digest of everything a Tier 0 commit promises not to disturb.

    Covers decoded content-stream bytes, the font resource table, the
    marked-content wrapper evidence closure (/Properties mapping, OCG
    objects and their resolved default visibility), and annotation/widget
    identity+geometry.  A prepared plan whose fingerprint no longer
    matches is stale and must not mutate anything.
    """
    digest = hashlib.sha256()
    for xref, data in read_page_streams(doc, page):
        digest.update(str(xref).encode("ascii"))
        digest.update(b"\x00")
        digest.update(data)
        digest.update(b"\x01")
    for entry in page.get_fonts(full=True):
        digest.update(repr(entry).encode("utf-8"))
        digest.update(b"\x02")
        # The metadata tuple is identical whether or not the font's advance
        # or glyph contract changed, so hash the defining objects themselves —
        # including every indirect one, whose *content* can change while the
        # reference in the font dictionary stays byte-identical.
        try:
            _update_font_dependencies(digest, doc, int(entry[0]))
        except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase):
            digest.update(b"<unreadable-font-object>")
        digest.update(b"\x05")
    # Task 13 P1 (proof obligation 5): fold the marked-content wrapper
    # evidence closure -- the resolved /Properties mapping, its targets,
    # and each OCG's default-config visibility bit (RESOLVED shape).
    update_marked_content_dependencies(digest, doc, page)
    # Task 13 P2: fold the RESOLVED page geometry every P2 geometric proof
    # rides -- /Rotate, /MediaBox, /CropBox via PyMuPDF's inheritance-
    # resolving accessors (a page-tree ancestor mutation must go stale,
    # and a direct-vs-inherited value must fingerprint identically), the
    # page-local /UserUnit (not inheritable; one indirect hop resolved),
    # AND the live computed visual matrices (transformation x rotation),
    # so a cached-view/serialized-state divergence can never slip through.
    _update_page_geometry(digest, doc, page)
    for annot in page.annots():
        digest.update(f"{annot.xref}:{tuple(annot.rect)}".encode("utf-8"))
        digest.update(b"\x03")
    for widget in page.widgets():
        digest.update(f"{widget.xref}:{tuple(widget.rect)}".encode("utf-8"))
        digest.update(b"\x04")
    return digest.hexdigest()


def capture_annotation_parent_refs(
    doc: fitz.Document, page: fitz.Page
) -> tuple[tuple[int, str], ...]:
    """Snapshot one page's annotations' full object dictionaries.

    ``fitz.Document.insert_pdf()`` mutates the copied SOURCE page's
    annotation objects as an observed side effect (a PyMuPDF quirk,
    reproduced directly with no model code involved): the ``/P``
    (parent-page) key is dropped and silently re-appended at the *end* of
    the dictionary, so a plain ``xref_get_key``/``xref_set_key`` round trip
    restores the right value but in the wrong position -- ``xref_object()``
    (and any byte-level comparison of it) still disagrees with the
    pre-copy state even though every key's value is intact. The xref, rect,
    and ``/AP`` appearance stream are never touched.

    Any call site that copies this page out of a *live* document (page-level
    undo snapshots, most notably) must back the full object string up first
    and restore it immediately after via :func:`restore_annotation_parent_refs`,
    or the live document's own annotation identity is silently disturbed by
    the mere act of copying it.
    """
    return tuple((annot.xref, doc.xref_object(annot.xref)) for annot in page.annots())


def restore_annotation_parent_refs(
    doc: fitz.Document, backup: tuple[tuple[int, str], ...]
) -> None:
    """Restore object dictionaries captured by
    :func:`capture_annotation_parent_refs`, verbatim, including key order.

    Only writes back an object that actually changed -- if the current
    object string already matches, the copy that would have disturbed it
    never ran, and this is a no-op.
    """
    for xref, object_str in backup:
        if doc.xref_object(xref) != object_str:
            doc.update_object(xref, object_str)


def page_has_widgets_or_signatures(doc: fitz.Document, page: fitz.Page) -> bool:
    """True when the page has form widgets or the document is signed."""
    if any(True for _ in page.widgets()):
        return True
    try:
        sig_flags = doc.get_sigflags()
    except (RuntimeError, ValueError):
        return True  # unreadable AcroForm: refuse rather than guess
    return sig_flags > 0


_CONTENTS_REF_RE = re.compile(r"(\d+)\s+\d+\s+R")


def _page_contents_xrefs(doc: fitz.Document, page_xref: int) -> tuple[int, ...] | None:
    """The xref(s) a page's ``/Contents`` refers to, or ``None`` when the
    value could not be parsed (callers must treat that as "possibly shares
    a stream", never as "shares nothing" -- fail-closed, matching
    :func:`page_has_widgets_or_signatures` above).

    Handles the three legal shapes: a direct reference to a single stream
    (``kind == "xref"``), an indirect reference to an array of stream
    references (``kind == "xref"`` pointing at a non-stream object), and an
    inline array of references (``kind == "array"``).  A page with no
    ``/Contents`` at all (``kind == "null"``) cannot share a stream and
    returns an empty tuple, never ``None``.
    """
    try:
        kind, value = doc.xref_get_key(page_xref, "Contents")
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None
    if kind == "null":
        return ()
    if kind == "array":
        matches = _CONTENTS_REF_RE.findall(value)
        if not matches:
            return None
        return tuple(int(m) for m in matches)
    if kind == "xref":
        try:
            target = int(value.split()[0])
        except (ValueError, IndexError):
            return None
        xrefs = [target]
        try:
            is_stream = doc.xref_is_stream(target)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            return None
        if not is_stream:
            # The indirect-/Contents-array shape: `target` is itself an
            # array object, not a stream -- parse the references inside it,
            # never the dictionary that owns them.
            try:
                obj = doc.xref_object(target)
            except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
                return None
            matches = _CONTENTS_REF_RE.findall(obj)
            if not matches:
                return None
            xrefs.extend(int(m) for m in matches)
        return tuple(xrefs)
    return None  # any other kind: fail-closed, never a guess


def find_pages_sharing_content_stream(
    doc: fitz.Document, *, stream_xref: int, page_number: int
) -> tuple[int, ...]:
    """0-based indices of every OTHER page whose ``/Contents`` references
    ``stream_xref`` -- or that could not be proven NOT to (fail-closed).

    Reads ``doc.xref_get_key(doc.page_xref(i), "Contents")`` for every page
    but ``page_number`` -- never ``doc[i]``, which loads a full page object
    and is the dense-page-preview cost this function must not pay per
    keystroke.  ``/Contents`` is not an inheritable page attribute, so no
    ``/Pages``-tree walk is needed.
    """
    hits: list[int] = []
    for i in range(doc.page_count):
        if i == page_number:
            continue
        try:
            page_xref = doc.page_xref(i)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            hits.append(i)
            continue
        xrefs = _page_contents_xrefs(doc, page_xref)
        if xrefs is None or stream_xref in xrefs:
            hits.append(i)
    return tuple(hits)


def replay_page(doc: fitz.Document, page: fitz.Page) -> PageReplay:
    return replay_page_streams(read_page_streams(doc, page))


def _origin_in_page_space(
    page: fitz.Page, show: ShowOp
) -> tuple[float, float]:
    """Map a show op's user-space origin into VISUAL (pixmap) page space.

    ``page.transformation_matrix`` covers the cropbox y-flip and /UserUnit
    but deliberately omits /Rotate in PyMuPDF; ``page.rotation_matrix``
    supplies the /Rotate term. This mirrors
    ``model.text_commit.plan._page_visual_matrix`` -- the same composition
    ``plan.py``'s fallback halo uses to match ``page.get_pixmap`` output --
    so ``origin_page`` stays in the same space as ``expected_origin`` values
    that callers derive from displayed geometry. NOT the same space as raw
    ``page.get_text('rawdict')`` output, which PyMuPDF keeps unrotated on
    both read and write (docs/PITFALLS.md).
    """
    point = fitz.Point(*show.origin_user) * page.transformation_matrix * page.rotation_matrix
    return (point.x, point.y)


def _target_in_invoked_form_xobjects(
    doc: fitz.Document, page: fitz.Page, target_bytes: bytes
) -> bool | None:
    """True when ``target_bytes`` decode from a show op inside a Form
    XObject the page's ``/Resources`` invokes (one level; nested ``Do``
    inside a Form is not followed — matches the funnel diagnostic).

    ``None`` (Task 12 P0-A) when at least one invoked XObject's stream was
    refused by the replay resource guard and the target was not confirmed
    in another: neither presence nor absence is provable, so the caller
    must surface the refusal rather than claim NO_MATCH — an unscanned
    stream proves nothing, and a False here would let
    ``_reconstruction_aware_reason`` rewrite the collapsed NO_MATCH into a
    fabricated reconstruction diagnosis.
    """
    try:
        xobjects = page.get_xobjects()
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return False
    scan_refused = False
    for entry in xobjects:
        xref = int(entry[0])
        try:
            data = doc.xref_stream(xref) or b""
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            continue
        replay = replay_page_streams([(xref, data)])
        if replay.refusal_reason is not None:
            scan_refused = True
            continue
        if any(s.decoded_bytes == target_bytes for s in replay.shows):
            return True
    return None if scan_refused else False


def _cid_show_candidates(
    page: fitz.Page,
    replay: PageReplay,
    target_text: str,
    registry: DocumentFontRegistry,
) -> tuple[list[ShowOp], BindingFailure | None]:
    """Type0 leg of binding: decode each CID show and match the target.

    Target-scoped by construction: a failing capability or an undecodable
    show is only REMEMBERED (first one wins) and surfaces solely when no
    show matches at all — a broken, unrelated Type0 font never blocks a
    target that another show satisfies.
    """
    matches: list[ShowOp] = []
    remembered: BindingFailure | None = None
    # One capability resolution per distinct resource, not per show: a
    # Type0 lookup re-verifies the evidence digest (a full font-program
    # hash), and corpus pages carry hundreds of shows sharing one font.
    resolved: dict[str, FontCapability | None] = {}
    for show in replay.shows:
        if show.font_resource is None:
            continue
        if show.font_resource not in resolved:
            resolved[show.font_resource] = registry.capability(
                page, show.font_resource
            )
        capability = resolved[show.font_resource]
        if capability is None or capability.subtype != "Type0":
            continue
        if capability.cid is None:
            if remembered is None and capability.tier0_reject_reason:
                remembered = BindingFailure(
                    capability.tier0_reject_reason,
                    capability.tier0_reject_detail
                    or "type0 evidence gate refused this font resource",
                )
            continue
        decoded = capability.cid.decode_show_bytes(show.decoded_bytes)
        if isinstance(decoded, CidCapabilityFailure):
            if remembered is None:
                remembered = BindingFailure(decoded.reason, decoded.detail)
            continue
        if decoded == target_text:
            matches.append(show)
    return matches, remembered


def bind_source_text(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    target_text: str,
    expected_origin: tuple[float, float] | None,
    tol: float = 0.5,
    registry: DocumentFontRegistry | None = None,
) -> SourceSpanBinding | BindingFailure:
    """Bind ``target_text`` at ``expected_origin`` (page space) to one show op.

    Matching is byte-level (latin-1) against decoded string operands for
    simple-encoded fonts. When ``registry`` is provided (Task 12 P0-D) and
    the simple leg finds nothing, Type0/Identity-H shows are decoded
    through their capability's ToUnicode evidence and matched by text; a
    unique CID match must additionally survive the source-reproduction
    proof (deterministic reverse encoding byte-equals the show operand).
    Without a registry, CID text keeps the historical refusal.
    """
    streams = read_page_streams(doc, page)
    if not streams:
        return BindingFailure(RejectReason.NO_MATCH, "page has no content streams")

    replay = replay_page_streams(streams)
    if replay.refusal_reason is not None:
        # Verbatim propagation is a frozen contract (Task 12 P0-A): the
        # refusal is about resources, not stream shape or match failure.
        return BindingFailure(
            replay.refusal_reason,
            f"decoded content streams total "
            f"{sum(len(data) for _, data in streams)} bytes, over the safe "
            "replay budget; refused before tokenization",
        )
    if replay.malformed:
        return BindingFailure(
            RejectReason.MALFORMED_STREAM,
            "content stream contains constructs the replay cannot account for",
        )

    target_bytes: bytes | None
    try:
        target_bytes = target_text.encode("latin-1")
    except UnicodeEncodeError:
        target_bytes = None
    if target_bytes is None and registry is None:
        return BindingFailure(
            RejectReason.UNDECODABLE_TARGET,
            "target text is outside byte-level (latin-1) matching; "
            "font-aware decoding not yet available",
        )

    candidates = (
        [s for s in replay.shows if s.decoded_bytes == target_bytes]
        if target_bytes is not None
        else []
    )
    cid_candidate_ids: frozenset[int] = frozenset()
    cid_failure: BindingFailure | None = None
    if registry is not None:
        # The CID leg ALWAYS runs alongside the simple leg (adversarial
        # round wf_a93b4e6c-e0f, F5): a target present as both simple
        # bytes and CID text must be bindable at either occurrence's
        # origin, and duplicates across the two legs must trip the same
        # ambiguity contract as duplicates within one leg.
        cid_candidates, cid_failure = _cid_show_candidates(
            page, replay, target_text, registry
        )
        seen = {id(s) for s in candidates}
        candidates = candidates + [
            s for s in cid_candidates if id(s) not in seen
        ]
        cid_candidate_ids = frozenset(id(s) for s in cid_candidates)
    if not candidates:
        if target_bytes is None:
            # Only an undecodable (non-latin-1) target is something the
            # Type0 leg alone could have explained — surface its remembered
            # failure there and ONLY there. A latin-1 miss must never be
            # rebranded with a type0_* code by an unrelated broken font
            # (F1), and must keep the Form-XObject / P0-A refusals below.
            if cid_failure is not None:
                return cid_failure
            return BindingFailure(
                RejectReason.NO_MATCH,
                "no Type0 show operator decodes to the target text",
            )
        # Target-scoped: only fire TARGET_IN_FORM_XOBJECT when the target
        # bytes are confirmed inside an invoked Form XObject. A page that
        # merely invokes a logo/bullet XObject must not rebrand every miss.
        if replay.has_xobject_invocation:
            in_xobjects = _target_in_invoked_form_xobjects(
                doc, page, target_bytes
            )
            if in_xobjects:
                return BindingFailure(
                    RejectReason.TARGET_IN_FORM_XOBJECT,
                    "target not in the direct page stream; confirmed inside "
                    "an invoked Form XObject",
                )
            if in_xobjects is None:
                # An invoked XObject was refused by the replay resource
                # guard: NO_MATCH would be an unprovable claim, and the
                # refusal must stay verbatim (Task 12 P0-A).
                return BindingFailure(
                    RejectReason.CONTENT_STREAM_TOO_LARGE,
                    "an invoked Form XObject's stream is over the safe "
                    "replay budget; the target's presence there can be "
                    "neither confirmed nor ruled out",
                )
        return BindingFailure(
            RejectReason.NO_MATCH,
            "no show operator decodes to the target text",
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
            RejectReason.UNSUPPORTED_TEXT_STATE,
            "show operator outside BT/ET",
        )
    # Task 13 P2: the blanket "rotated, sheared, reflected, or
    # non-uniformly scaled" refusal is replaced by the fail-closed
    # quarter-turn admission — the combined Tm×CTM must be a
    # positive-orientation uniform rotation+scale whose VISUAL baseline
    # is cardinal; every defect keeps its own stable trm_* code.  Details
    # are code-only (§10 privacy): matrix coefficients can fingerprint a
    # private document's producer and never appear here.
    #
    # Replay-uniform shows NEVER enter the new gate (review F2): replay's
    # absolute tolerances admit residuals (|b| == 1e-6) that the relative
    # shape checks would refuse, and the pre-P2 admitted set must stay
    # admitted byte-identically.  The one exception is a non-finite
    # combined matrix, which replay's comparison-based idiom test cannot
    # flag (NaN compares False everywhere) — that defect stays refused
    # regardless of the replay flag.
    trm_verdict = admission_verdict(page, show.tm, show.ctm)
    if trm_verdict.reject_reason is not None and (
        not show.trm_uniform_scaled
        or trm_verdict.reject_reason == RejectReason.TRM_NON_FINITE
    ):
        return BindingFailure(
            trm_verdict.reject_reason,
            _TRM_REJECT_DETAILS[trm_verdict.reject_reason],
        )

    if id(show) in cid_candidate_ids and registry is not None:
        # Source-reproduction proof (its own gate, never skipped): the
        # ToUnicode forward decode matching the target is NOT enough — the
        # deterministic reverse encoding must reproduce the show operand
        # byte-for-byte, or the encoding contract used for the replacement
        # is unproven for this very string.
        assert show.font_resource is not None
        capability = registry.capability(page, show.font_resource)
        cid = capability.cid if capability is not None else None
        if cid is None:
            return BindingFailure(
                RejectReason.FONT_FACE_UNAVAILABLE,
                "type0 capability vanished between decode and reproduction",
            )
        reproduced = cid.encode_first_wins(target_text)
        if isinstance(reproduced, CidCapabilityFailure):
            return BindingFailure(reproduced.reason, reproduced.detail)
        if reproduced != show.decoded_bytes:
            return BindingFailure(
                RejectReason.TYPE0_SOURCE_BYTES_NOT_REPRODUCED,
                "deterministic reverse encoding does not reproduce the "
                "source show operand bytes",
            )

    stream_bytes = dict(streams)[show.stream_xref]
    return SourceSpanBinding(
        page_xref=page.xref,
        stream_xref=show.stream_xref,
        stream_digest=hashlib.sha256(stream_bytes).hexdigest(),
        show=show,
        origin_page=_origin_in_page_space(page, show),
        # An out-of-range wrapper id is silently dropped HERE, but never
        # admitted: the admission gate re-checks stack length against
        # ``mc_depth`` and refuses the inconsistency (fail-closed net).
        mc_wrappers=tuple(
            replay.mc_wrappers[i]
            for i in show.mc_stack
            if 0 <= i < len(replay.mc_wrappers)
        ),
        mc_emc_underflows=replay.mc_emc_underflows,
    )
