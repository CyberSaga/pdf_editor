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

from model.text_commit.dto import RejectReason
from model.text_commit.replay import PageReplay, ShowOp, replay_page_streams

logger = logging.getLogger(__name__)

_CONTENTS_ARRAY_REF_RE = re.compile(r"(\d+)\s+0\s+R")


@dataclass(frozen=True)
class SourceSpanBinding:
    """A verified, unambiguous mapping from target text to one show op."""

    page_xref: int
    stream_xref: int
    stream_digest: str  # SHA-256 of the bound stream's decoded bytes
    show: ShowOp
    origin_page: tuple[float, float]  # MuPDF page space (rawdict convention)


@dataclass(frozen=True)
class BindingFailure:
    reason: str  # a RejectReason constant
    detail: str


def read_page_streams(
    doc: fitz.Document, page: fitz.Page
) -> list[tuple[int, bytes]]:
    """Ordered ``(xref, decoded_bytes)`` list of the page's content streams."""
    return [(xref, doc.xref_stream(xref) or b"") for xref in page.get_contents()]


def scan_shared_streams(doc: fitz.Document) -> frozenset[int]:
    """Content-stream xrefs referenced by more than one page's ``/Contents``.

    Xref-level only -- ``doc.page_xref``/``doc.xref_get_key`` are O(1) C-level
    table lookups, no page object is ever constructed, so this stays cheap
    even as a per-``prepare_plan``-call scan (Task 11 Slice 1 D10).
    ``/Contents`` is not inheritable (PDF spec 7.7.3.3, Table 30), so reading
    each page's own dict entry -- never a parent's -- cannot miss a page that
    has no content of its own. An array ``/Contents`` holds only indirect
    stream refs per spec 7.7.3.4 (never nested arrays/dicts/strings), so a
    plain ``N 0 R`` scan over the array value cannot misparse an unrelated
    dictionary value the way a general-purpose ref regex would.
    """
    refcount: dict[int, int] = {}
    for page_number in range(doc.page_count):
        page_xref = doc.page_xref(page_number)
        kind, value = doc.xref_get_key(page_xref, "Contents")
        if kind == "xref":
            try:
                ref = int(value.split()[0])
            except (ValueError, IndexError):
                continue
            refcount[ref] = refcount.get(ref, 0) + 1
        elif kind == "array":
            for match in _CONTENTS_ARRAY_REF_RE.findall(value):
                ref = int(match)
                refcount[ref] = refcount.get(ref, 0) + 1
    return frozenset(xref for xref, count in refcount.items() if count > 1)


def is_stream_shared(doc: fitz.Document, stream_xref: int) -> bool:
    """True when ``stream_xref`` is one page's content among several."""
    return stream_xref in scan_shared_streams(doc)


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


def _update_font_dependencies(
    digest: "hashlib._Hash", doc: fitz.Document, font_xref: int
) -> None:
    """Fold one font's object and every indirect object it depends on.

    Enumerated rather than followed generically so the set is auditable: if
    capability classification starts reading another key, it belongs here in
    the same change, or a plan measured under the old value stays "fresh".
    """
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


def page_fingerprint(doc: fitz.Document, page: fitz.Page) -> str:
    """Digest of everything a Tier 0 commit promises not to disturb.

    Covers decoded content-stream bytes, the font resource table, and
    annotation/widget identity+geometry.  A prepared plan whose fingerprint
    no longer matches is stale and must not mutate anything.
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


def replay_page(doc: fitz.Document, page: fitz.Page) -> PageReplay:
    return replay_page_streams(read_page_streams(doc, page))


def _origin_in_page_space(
    page: fitz.Page, show: ShowOp
) -> tuple[float, float]:
    point = fitz.Point(*show.origin_user) * page.transformation_matrix
    return (point.x, point.y)


def bind_source_text(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    target_text: str,
    expected_origin: tuple[float, float] | None,
    tol: float = 0.5,
) -> SourceSpanBinding | BindingFailure:
    """Bind ``target_text`` at ``expected_origin`` (page space) to one show op.

    Matching is byte-level (latin-1) against decoded string operands, which
    covers simple-encoded fonts; CID/GID-coded strings do not match here
    and surface as ``NO_MATCH`` until font-aware decoding exists (Task 4+).
    """
    streams = read_page_streams(doc, page)
    if not streams:
        return BindingFailure(RejectReason.NO_MATCH, "page has no content streams")

    replay = replay_page_streams(streams)
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
            "target text is outside byte-level (latin-1) matching; "
            "font-aware decoding not yet available",
        )

    candidates = [s for s in replay.shows if s.decoded_bytes == target_bytes]
    if not candidates:
        if replay.has_xobject_invocation:
            return BindingFailure(
                RejectReason.TARGET_IN_FORM_XOBJECT,
                "target not in the direct page stream; page invokes Form "
                "XObjects that may contain it",
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
