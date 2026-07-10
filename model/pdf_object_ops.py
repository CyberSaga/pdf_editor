"""Object-ops engine (R3.4 god-module decomposition seam).

App-object / native-image manipulation extracted out of PDFModel as free functions
(``def fn(model: PDFModel, ...)``), mirroring ``model/pdf_optimizer.py``. PDFModel keeps
1-line delegating wrappers for the public verbs. The controller owns undo snapshots;
destructive operations additionally use a private snapshot for atomic rollback. There are
no direct ``.save``/``.tobytes`` calls on the live doc (the encryption AST guard scans
all of model/).
"""

from __future__ import annotations

import html as _html_mod
import hashlib
import json
import logging
import math
import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import fitz

from model.geometry import clamp_rect_to_page
from model.object_requests import (
    DeleteObjectRequest,
    MoveObjectRequest,
    ObjectHitInfo,
    ResizeObjectRequest,
    RotateObjectRequest,
)
from model.pdf_content_ops import (
    NativeImageInvocation,
    _cm_values_from_operands,
    decompose_image_cm,
    discover_native_image_invocations,
    fitz_rect_to_stream_cm,
    form_rect_to_stream_cm,
    parse_operators,
    remove_operator_range,
    replace_operator_operands,
    rotated_image_stream_cm,
)

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)

_APP_OBJECT_SUBJECT_PREFIX = "pdf_editor_"
_TEXTBOX_OBJECT_SUBJECT = "pdf_editor_textbox_object"
_RECT_OBJECT_SUBJECT = "pdf_editor_rect_object"
_IMAGE_OBJECT_SUBJECT = "pdf_editor_image_object"
_APP_OBJECT_VERSION = 1


def _dump_app_object_payload(model: PDFModel, payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

def _load_app_object_payload(model: PDFModel, annot: fitz.Annot) -> dict | None:
    try:
        info = annot.info or {}
        subject = info.get("subject") or ""
        if not subject.startswith(_APP_OBJECT_SUBJECT_PREFIX):
            return None
        content = info.get("content") or ""
        payload = json.loads(content)
        if not isinstance(payload, dict):
            return None
        if payload.get("version") != _APP_OBJECT_VERSION:
            return None
        if payload.get("kind") not in {"textbox", "rect", "image"}:
            return None
        return payload
    except Exception:
        return None

def _iter_page_annots(model: PDFModel, page_num: int) -> Iterator[fitz.Annot]:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        return iter(())
    page = model.doc[page_num - 1]
    try:
        return iter(list(page.annots() or []))
    except Exception:
        return iter(())

def _find_app_object_annot(model: PDFModel, page_num: int, object_id: str, expected_kind: str | None = None) -> tuple[fitz.Page, fitz.Annot, dict] | None:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        return None
    page = model.doc[page_num - 1]
    try:
        annots = list(page.annots() or [])
    except Exception:
        return None
    for annot in annots:
        payload = _load_app_object_payload(model, annot)
        if payload is None:
            continue
        if payload.get("object_id") != object_id:
            continue
        if expected_kind is not None and payload.get("kind") != expected_kind:
            continue
        return page, annot, payload
    return None

def _find_native_image_invocation(model: PDFModel, page_num: int, object_id: str) -> NativeImageInvocation | None:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        return None
    prefix = f"native_image:{page_num}:"
    if not str(object_id).startswith(prefix):
        return None
    try:
        occurrence_index = int(str(object_id).split(":")[-1])
    except Exception:
        return None
    invocations = discover_native_image_invocations(model.doc, page_num)
    for invocation in invocations:
        if invocation.occurrence_index == occurrence_index:
            return invocation
    return None

def _rewrite_native_image_matrix(
    model: PDFModel,
    invocation: NativeImageInvocation,
    destination_rect: fitz.Rect,
    rotation: float,
) -> bool:
    # typed bind; callers guarantee an open doc here (native image rewrite path) - runtime behavior identical if None
    doc: fitz.Document = model.doc
    page = doc[invocation.page_num - 1]
    if invocation.cm_operator_index is None:
        return False
    stream = doc.xref_stream(invocation.stream_xref)
    tokens, operators = parse_operators(stream)
    if invocation.cm_operator_index >= len(operators):
        return False
    cm_operator = operators[invocation.cm_operator_index]
    if cm_operator.name != "cm":
        return False
    rot = float(rotation) % 360.0
    if invocation.is_form_nested:
        current_cm = _cm_values_from_operands(cm_operator.operands)
        if current_cm is None:
            return False
        new_operands = form_rect_to_stream_cm(
            fitz.Rect(destination_rect),
            current_cm,
            fitz.Rect(invocation.bbox),
            rot,
        )
        if new_operands is None:
            return False
    elif abs(rot - round(rot / 90.0) * 90.0) > 0.5:
        # Free (non-cardinal) rotation: place the image rotated about its
        # centre. On a pure move the destination AABB has the same size as
        # the current one, so preserve the un-rotated size (and thus the
        # angle) rather than squashing the image into the new AABB.
        current_cm = _cm_values_from_operands(cm_operator.operands)
        if current_cm is None:
            return False
        cur_w, cur_h, _ang, _cx, _cy = decompose_image_cm(current_cm)
        dest = fitz.Rect(destination_rect)
        cur_bbox = fitz.Rect(invocation.bbox)
        if abs(dest.width - cur_bbox.width) < 0.5 and abs(dest.height - cur_bbox.height) < 0.5:
            # Pure move: preserve the un-rotated size (and thus the angle).
            unrotated_w, unrotated_h = cur_w, cur_h
        else:
            # Resize: the destination is the new axis-aligned bounding box of
            # the rotated image. Recover the un-rotated size so the rendered
            # AABB matches the request, instead of treating the AABB as the
            # image size (which would inflate it by |cos|+|sin|).
            cos_t = abs(math.cos(math.radians(rot)))
            sin_t = abs(math.sin(math.radians(rot)))
            det = cos_t * cos_t - sin_t * sin_t
            if abs(det) > 1e-3:
                unrotated_w = max(1.0, (dest.width * cos_t - dest.height * sin_t) / det)
                unrotated_h = max(1.0, (dest.height * cos_t - dest.width * sin_t) / det)
            else:
                # Near 45°/135° the inversion is singular; keep current size.
                unrotated_w, unrotated_h = cur_w, cur_h
        page_height = float(fitz.Rect(page.mediabox).height)
        new_operands = rotated_image_stream_cm(
            (dest.x0 + dest.x1) / 2.0,
            (dest.y0 + dest.y1) / 2.0,
            unrotated_w,
            unrotated_h,
            rot,
            page_height,
        )
    else:
        new_operands = fitz_rect_to_stream_cm(
            fitz.Rect(destination_rect), page, rot
        )
    new_stream = replace_operator_operands(tokens, cm_operator, new_operands)
    doc.update_stream(invocation.stream_xref, new_stream)
    model.pending_edits.append({"page_idx": invocation.page_num - 1, "rect": fitz.Rect(destination_rect)})
    model.edit_count += 1
    return True

def _find_app_image_invocation(
    model: PDFModel,
    page_num: int,
    xref: int,
    expected_rect: fitz.Rect,
    *,
    image_digest: str | None = None,
    expected_rotation: float = 0.0,
) -> NativeImageInvocation | None:
    """Resolve an app image without treating its garbage-collectable xref as identity."""
    invocations = discover_native_image_invocations(model.doc, page_num)
    usable = [inv for inv in invocations if inv.cm_operator_index is not None]
    er = fitz.Rect(expected_rect)

    def _rect_dist(inv: NativeImageInvocation) -> float:
        b = inv.bbox
        return sum(abs(a - b_) for a, b_ in zip([b.x0, b.y0, b.x1, b.y1], [er.x0, er.y0, er.x1, er.y1]))

    def _rotation_matches(inv: NativeImageInvocation) -> bool:
        delta = (float(inv.rotation) - float(expected_rotation) + 180.0) % 360.0 - 180.0
        return abs(delta) <= 1.0

    xref_candidates = [inv for inv in usable if inv.xref == xref]
    if xref_candidates:
        if image_digest:
            verified = [
                inv for inv in xref_candidates
                if _image_xref_digest(model, inv.xref) == image_digest
            ]
            if verified:
                return min(verified, key=_rect_dist)
        else:
            positioned = [
                inv for inv in xref_candidates
                if _rect_dist(inv) <= 2.0 and _rotation_matches(inv)
            ]
            if positioned:
                return min(positioned, key=_rect_dist)

    geometric = [inv for inv in usable if _rect_dist(inv) <= 2.0 and _rotation_matches(inv)]
    if image_digest:
        matches = [inv for inv in geometric if _image_xref_digest(model, inv.xref) == image_digest]
        return matches[0] if len(matches) == 1 else None
    return geometric[0] if len(geometric) == 1 else None


def _image_xref_digest(model: PDFModel, xref: int) -> str | None:
    try:
        # typed bind inside the try; the except still swallows AttributeError if doc is None - reachable-shape identical
        doc: fitz.Document = model.doc
        stream = doc.xref_stream(int(xref))
    except Exception:
        return None
    return hashlib.sha256(stream).hexdigest() if stream else None


def _marker_xref(payload: dict) -> int:
    """The marker payload's recorded image xref, or 0 when absent/unusable.

    Single parse chokepoint: a corrupt or third-party payload (`"xref": "abc"`) used to
    raise `ValueError` straight through `delete_objects_atomic`'s re-raise and into an
    uncaught Qt slot. 0 is the right degraded value — `_find_app_image_invocation` treats it
    as "no recorded xref" and falls back to geometry + digest.
    """
    try:
        return int(payload.get("xref", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _app_image_invocation_candidates(
    model: PDFModel,
    page_num: int,
    payload: dict,
    expected_rect: fitz.Rect,
) -> list[NativeImageInvocation]:
    """Invocations that could plausibly be this marker's image.

    A deliberate *superset* of what `_find_app_image_invocation` will accept, used only to
    tell two failures apart when resolution returns None:

      * **zero** candidates — nothing on the page renders this image any more (an external
        editor stripped the XObject and left our hidden marker behind). The marker is
        orphaned and must be cleaned up, or it becomes an undeletable zombie.
      * **more than one** — the pixels exist but we cannot say which placement is ours.
        Fail safe; deleting the marker alone would orphan visible content.
    """
    recorded_xref = _marker_xref(payload)
    digest = payload.get("image_digest")
    er = fitz.Rect(expected_rect)
    candidates: list[NativeImageInvocation] = []
    for inv in discover_native_image_invocations(model.doc, page_num):
        if inv.cm_operator_index is None:
            continue
        if recorded_xref and inv.xref == recorded_xref:
            candidates.append(inv)
            continue
        if digest and _image_xref_digest(model, inv.xref) == digest:
            candidates.append(inv)
            continue
        b = inv.bbox
        if sum(abs(a - c) for a, c in zip([b.x0, b.y0, b.x1, b.y1], [er.x0, er.y0, er.x1, er.y1])) <= 2.0:
            candidates.append(inv)
    return candidates


def _resolve_marker_image_invocation(
    model: PDFModel,
    page_num: int,
    payload: dict,
    expected_rect: fitz.Rect,
) -> NativeImageInvocation | None:
    recorded_xref = _marker_xref(payload)
    invocation = _find_app_image_invocation(
        model,
        page_num,
        recorded_xref,
        expected_rect,
        image_digest=payload.get("image_digest"),
        expected_rotation=float(payload.get("rotation", 0)) % 360,
    )
    if invocation is None:
        return None
    if invocation.xref != recorded_xref or not payload.get("image_digest"):
        digest = _image_xref_digest(model, invocation.xref)
        if digest is None:
            return None
        payload["xref"] = int(invocation.xref)
        payload["image_digest"] = digest
    return invocation

# PDF name tokens end at whitespace or a delimiter (PDF 1.7 §7.2.2, Tables 1-2).
_PDF_NAME_TERMINATORS = frozenset(b"\x00\t\n\x0c\r ()<>[]{}/%")


def _stream_references_xobject(stream: bytes, xobject_name: str) -> bool:
    """True when ``stream`` invokes ``/<xobject_name>`` as a whole name token.

    A raw substring test is wrong: ``b"/fzImg1" in stream`` is satisfied by the token
    ``/fzImg10``, so deleting the 2nd of 11+ images would leave its resource entry behind.
    Match only where the name is followed by a delimiter or the end of the stream.
    """
    token = f"/{xobject_name}".encode("latin-1")
    start = 0
    while True:
        index = stream.find(token, start)
        if index < 0:
            return False
        end = index + len(token)
        if end == len(stream) or stream[end] in _PDF_NAME_TERMINATORS:
            return True
        start = end


def _resolve_xobject_resource_owner(
    doc: fitz.Document, page: fitz.Page, invocation: NativeImageInvocation
) -> int | None:
    """The xref of the dict that actually holds ``Resources/XObject/<name>``.

    ``/Resources`` is inheritable: a page may have none of its own and resolve it through
    its ``/Parent`` chain, in which case PyMuPDF's ``insert_image`` registers the XObject
    in that *ancestor* dict. Nulling the key on the page would not remove it — worse,
    ``xref_set_key`` creates every missing link in the path, fabricating a direct
    ``/Resources`` on the page that SHADOWS the inherited one, so the page's fonts and
    other XObjects stop resolving. Returns ``None`` when the owner cannot be located.
    """
    if invocation.is_form_nested:
        return invocation.resource_owner_xref or invocation.stream_xref

    key = f"Resources/XObject/{invocation.xobject_name}"
    if doc.xref_get_key(page.xref, "Resources")[0] != "null":
        return page.xref if doc.xref_get_key(page.xref, key)[0] != "null" else None

    node = page.xref
    seen: set[int] = {node}
    while True:
        kind, value = doc.xref_get_key(node, "Parent")
        if kind != "xref":
            return None
        try:
            parent = int(str(value).split()[0])
        except (ValueError, IndexError):
            return None
        if parent in seen:
            return None
        seen.add(parent)
        if doc.xref_get_key(parent, key)[0] != "null":
            return parent
        node = parent


def _remove_native_image_invocation(model: PDFModel, invocation: NativeImageInvocation) -> bool:
    # typed bind; callers guarantee an open doc here (native image removal path) - runtime behavior identical if None
    doc: fitz.Document = model.doc
    page = doc[invocation.page_num - 1]
    stream = doc.xref_stream(invocation.stream_xref)
    tokens, operators = parse_operators(stream)
    if invocation.do_operator_index >= len(operators):
        return False
    start_token = operators[invocation.do_operator_index].operand_start
    end_token = operators[invocation.do_operator_index].operator_index
    if (
        invocation.q_operator_index is not None
        and invocation.q_end_operator_index is not None
        and invocation.q_operator_index < len(operators)
        and invocation.q_end_operator_index < len(operators)
        and invocation.q_image_invocation_count == 1
    ):
        start_token = operators[invocation.q_operator_index].operand_start
        end_token = operators[invocation.q_end_operator_index].operator_index
    elif invocation.cm_operator_index is not None and invocation.cm_operator_index < len(operators):
        start_token = operators[invocation.cm_operator_index].operand_start
    new_stream = remove_operator_range(tokens, start_token, end_token)
    doc.update_stream(invocation.stream_xref, new_stream)

    owner_xref = _resolve_xobject_resource_owner(doc, page, invocation)
    if owner_xref is not None:
        # A form-nested image is named in the form's own resources and drawn from the
        # form's single stream. A page-level image may be drawn from several of the
        # page's content streams; and when the owner is an *inherited* resources dict,
        # sibling pages share it, so every page must be cleared before pruning.
        if invocation.is_form_nested:
            scan_streams = [invocation.stream_xref]
        elif owner_xref == page.xref:
            scan_streams = [int(xref) for xref in page.get_contents() if int(xref) > 0]
        else:
            scan_streams = [
                int(xref)
                for other in doc
                for xref in other.get_contents()
                if int(xref) > 0
            ]
        still_referenced = any(
            _stream_references_xobject(doc.xref_stream(int(xref)), invocation.xobject_name)
            for xref in scan_streams
        )
        if not still_referenced:
            try:
                doc.xref_set_key(owner_xref, f"Resources/XObject/{invocation.xobject_name}", "null")
            except Exception:
                logger.debug(
                    "Could not prune XObject resource %s from xref %s",
                    invocation.xobject_name,
                    owner_xref,
                )
    model.pending_edits.append({"page_idx": invocation.page_num - 1, "rect": fitz.Rect(invocation.bbox)})
    model.edit_count += 1
    return True

def _delete_app_object_annots(
    model: PDFModel,
    page_num: int,
    object_id: str,
    expected_kind: str | None = None,
) -> int:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        return 0
    page = model.doc[page_num - 1]
    deleted = 0
    try:
        annots = list(page.annots() or [])
    except Exception:
        return 0
    for annot in annots:
        payload = _load_app_object_payload(model, annot)
        if payload is None:
            continue
        if payload.get("object_id") != object_id:
            continue
        if expected_kind is not None and payload.get("kind") != expected_kind:
            continue
        try:
            page.delete_annot(annot)
            deleted += 1
        except Exception:
            continue
    return deleted

def _create_textbox_object_marker(
    model: PDFModel,
    page_num: int,
    visual_rect: fitz.Rect,
    *,
    text: str,
    font: str,
    size: float,
    color: tuple[float, float, float],
    rotation: int,
    object_id: str | None = None,
) -> str:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        raise ValueError(f"無效頁碼: {page_num}")
    page = model.doc[page_num - 1]
    marker = page.add_rect_annot(fitz.Rect(visual_rect))
    payload: dict[str, Any] = {
        "version": _APP_OBJECT_VERSION,
        "kind": "textbox",
        "object_id": object_id or str(uuid.uuid4()),
        "page_num": int(page_num),
        "rect": [float(visual_rect.x0), float(visual_rect.y0), float(visual_rect.x1), float(visual_rect.y1)],
        "text": text,
        "font": font,
        "size": float(size),
        "color": [float(c) for c in color[:3]],
        "rotation": int(rotation) % 360,
    }
    marker.set_border(width=0)
    marker.set_colors(stroke=None, fill=None)
    marker.set_opacity(0.0)
    marker.set_flags(marker.flags | fitz.PDF_ANNOT_IS_HIDDEN)
    marker.set_info(
        content=_dump_app_object_payload(model, payload),
        subject=_TEXTBOX_OBJECT_SUBJECT,
    )
    marker.update()
    return payload["object_id"]

def _create_image_object_marker(
    model: PDFModel,
    page_num: int,
    visual_rect: fitz.Rect,
    *,
    xref: int,
    image_digest: str,
    rotation: int,
    object_id: str | None = None,
) -> str:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        raise ValueError(f"無效頁碼: {page_num}")
    page = model.doc[page_num - 1]
    marker = page.add_rect_annot(fitz.Rect(visual_rect))
    payload: dict[str, Any] = {
        "version": _APP_OBJECT_VERSION,
        "kind": "image",
        "object_id": object_id or str(uuid.uuid4()),
        "page_num": int(page_num),
        "rect": [float(visual_rect.x0), float(visual_rect.y0), float(visual_rect.x1), float(visual_rect.y1)],
        "rotation": int(rotation) % 360,
        "xref": int(xref),
        "image_digest": image_digest,
    }
    marker.set_border(width=0)
    marker.set_colors(stroke=None, fill=None)
    marker.set_opacity(0.0)
    marker.set_flags(marker.flags | fitz.PDF_ANNOT_IS_HIDDEN)
    marker.set_info(
        content=_dump_app_object_payload(model, payload),
        subject=_IMAGE_OBJECT_SUBJECT,
    )
    marker.update()
    return payload["object_id"]

def add_image_object(
    model: PDFModel,
    page_num: int,
    visual_rect: fitz.Rect,
    image_bytes: bytes,
    *,
    rotation: int = 0,
) -> str:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        raise ValueError(f"無效頁碼: {page_num}")
    page = model.doc[page_num - 1]
    rect = fitz.Rect(visual_rect)
    xref = int(page.insert_image(rect, stream=image_bytes, rotate=int(rotation) % 360, overlay=True))
    image_digest = _image_xref_digest(model, xref)
    if image_digest is None:
        raise RuntimeError("Inserted image stream could not be fingerprinted")
    object_id = _create_image_object_marker(model, 
        page_num,
        rect,
        xref=xref,
        image_digest=image_digest,
        rotation=int(rotation) % 360,
    )
    model.pending_edits.append({"page_idx": page_num - 1, "rect": fitz.Rect(rect)})
    model.edit_count += 1
    return object_id

def _insert_textbox_visual_content(
    model: PDFModel,
    page_num: int,
    visual_rect: fitz.Rect,
    text: str,
    *,
    font: str = "cjk",
    size: int | float = 12,
    color: tuple = (0.0, 0.0, 0.0),
    rotation: int | None = None,
) -> dict:
    if not text.strip():
        logger.warning("新增文字框內容為空，略過")
        raise ValueError("新增文字框內容為空")
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        raise ValueError(f"無效頁碼: {page_num}")

    page_idx = page_num - 1
    font_name = model._resolve_add_text_font(font)
    font_size = max(0.1, float(size))
    if len(color) >= 3:
        color_rgb = (
            max(0.0, min(1.0, float(color[0]))),
            max(0.0, min(1.0, float(color[1]))),
            max(0.0, min(1.0, float(color[2]))),
        )
    else:
        color_rgb = (0.0, 0.0, 0.0)

    last_err: Exception | None = None
    bounded_visual = fitz.Rect(visual_rect)
    insert_rect = fitz.Rect(visual_rect)
    repaired_once = False
    effective_rotation = int(rotation) % 360 if rotation is not None else 0

    for _ in range(2):
        page = model.doc[page_idx]
        page_visual_rect = fitz.Rect(page.rect)
        bounded_visual = clamp_rect_to_page(fitz.Rect(visual_rect), page_visual_rect)

        if bounded_visual.width < 4:
            bounded_visual.x1 = min(page_visual_rect.x1, bounded_visual.x0 + 4)
        if bounded_visual.height < 4:
            bounded_visual.y1 = min(page_visual_rect.y1, bounded_visual.y0 + 4)

        unrot_rect = model._visual_rect_to_unrotated_rect(page, bounded_visual)
        insert_rect = clamp_rect_to_page(unrot_rect, model._unrotated_page_rect(page))
        if rotation is None:
            effective_rotation = int(page.rotation) % 360

        try:
            tiny_canvas = (
                min(float(page.rect.width), float(page.rect.height)) < 12.0
                or min(float(insert_rect.width), float(insert_rect.height)) < 12.0
            )
            if tiny_canvas and not model._needs_cjk_font(text):
                model._insert_tiny_plain_text(page, text, color_rgb, font_size)
            else:
                escaped_text = _html_mod.escape(text).replace("\n", "<br>")
                html_content = f'<span style="font-family: {font_name};">{escaped_text}</span>'
                css = f"""
                    span {{
                        font-size: {font_size}pt;
                        white-space: pre-wrap;
                        word-break: break-all;
                        overflow-wrap: anywhere;
                        color: rgb({int(color_rgb[0]*255)}, {int(color_rgb[1]*255)}, {int(color_rgb[2]*255)});
                    }}
                """
                page.insert_htmlbox(
                    insert_rect,
                    html_content,
                    css=css,
                    rotate=effective_rotation,
                    scale_low=0,
                )
            last_err = None
            break
        except Exception as e:
            last_err = e
            if repaired_once:
                break
            repaired_once = model._repair_active_doc_in_memory(garbage=1)
            if not repaired_once:
                break
            if not model.doc or page_idx >= len(model.doc):
                break
            continue

    if last_err is not None:
        raise RuntimeError(f"新增文字框失敗: {model._safe_exc_message(last_err)}") from last_err

    return {
        "page_idx": page_idx,
        "bounded_visual": fitz.Rect(bounded_visual),
        "insert_rect": fitz.Rect(insert_rect),
        "rotation": effective_rotation,
        "font_name": font_name,
        "font_size": font_size,
        "color_rgb": color_rgb,
    }


def add_textbox(
    model: PDFModel,
    page_num: int,
    visual_rect: fitz.Rect,
    text: str,
    font: str = "cjk",
    size: int = 12,
    color: tuple = (0.0, 0.0, 0.0),
) -> None:
    """
    Add new page text anchored in visual page coordinates.

    visual_rect uses current viewer orientation coordinates. The method maps
    it to unrotated page space and inserts with rotate=page.rotation so text
    appears at the clicked visual location for rotation 0/90/180/270.
    """
    insert_state = _insert_textbox_visual_content(model, 
        page_num,
        visual_rect,
        text,
        font=font,
        size=size,
        color=color,
    )
    page_idx = insert_state["page_idx"]
    _create_textbox_object_marker(model, 
        page_num,
        insert_state["bounded_visual"],
        text=text,
        font=insert_state["font_name"],
        size=insert_state["font_size"],
        color=insert_state["color_rgb"],
        rotation=insert_state["rotation"],
    )
    model.block_manager.rebuild_page(page_idx, model.doc)
    model.pending_edits.append({"page_idx": page_idx, "rect": fitz.Rect(insert_state["insert_rect"])})
    model.edit_count += 1
    logger.debug(
        "add_textbox page=%s visual_rect=%s insert_rect=%s rotate=%s font=%s",
        page_num,
        insert_state["bounded_visual"],
        insert_state["insert_rect"],
        insert_state["rotation"],
        insert_state["font_name"],
    )

def get_object_info_at_point(model: PDFModel, page_num: int, point: fitz.Point) -> ObjectHitInfo | None:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        return None
    try:
        page = model.doc[page_num - 1]
        annots = list(page.annots() or [])
    except Exception:
        annots = []
    candidates: list[tuple[fitz.Annot, dict]] = []
    for annot in annots:
        payload = _load_app_object_payload(model, annot)
        if payload is None:
            continue
        rect = fitz.Rect(annot.rect)
        if point in rect:
            candidates.append((annot, payload))
    if candidates:
        annot, payload = candidates[-1]
        kind = payload["kind"]
        return ObjectHitInfo(
            object_kind=kind,
            object_id=str(payload["object_id"]),
            page_num=page_num,
            bbox=fitz.Rect(annot.rect),
            rotation=float(payload.get("rotation", 0)) % 360,
            supports_move=True,
            supports_delete=True,
            supports_rotate=kind in ("textbox", "image"),
        )
    native_hits = [
        invocation
        for invocation in discover_native_image_invocations(model.doc, page_num)
        if point in fitz.Rect(invocation.bbox)
    ]
    if not native_hits:
        return None
    native_hit = native_hits[-1]
    return ObjectHitInfo(
        object_kind="native_image",
        object_id=f"native_image:{page_num}:{native_hit.occurrence_index}",
        page_num=page_num,
        bbox=fitz.Rect(native_hit.bbox),
        rotation=float(native_hit.rotation) % 360,
        supports_move=True,
        supports_delete=True,
        # Form-nested images are repositioned in the form's coordinate space,
        # which only supports axis-aligned move/resize — not rotation.
        supports_rotate=not native_hit.is_form_nested,
    )

def _redact_and_restore_textbox_region(model: PDFModel, page: fitz.Page, rect: fitz.Rect, object_id: str) -> None:
    saved_annots = model.tools.annotation._save_overlapping_annots(page, rect)
    filtered_annots: list[dict] = []
    for saved in saved_annots:
        info = dict(saved.get("info") or {})
        subject = info.get("subject") or ""
        if subject == _TEXTBOX_OBJECT_SUBJECT:
            try:
                payload = json.loads(info.get("content") or "{}")
            except Exception:
                payload = {}
            if payload.get("object_id") == object_id:
                continue
        filtered_annots.append(saved)
    page.add_redact_annot(rect)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    if filtered_annots:
        model.tools.annotation._restore_annots(page, filtered_annots)

def _register_mutation(model: PDFModel, page_idx: int, rect: fitz.Rect) -> None:
    """Track a rewrite without performing a live full-document GC."""
    model.pending_edits.append({"page_idx": page_idx, "rect": fitz.Rect(rect)})
    model.edit_count += 1


def move_object(model: PDFModel, request: MoveObjectRequest) -> bool:
    if request.destination_page != request.source_page:
        return False
    if request.object_kind == "native_image":
        invocation = _find_native_image_invocation(model, request.source_page, request.object_id)
        if invocation is None:
            return False
        return _rewrite_native_image_matrix(model, 
            invocation,
            fitz.Rect(request.destination_rect),
            invocation.rotation,
        )
    found = _find_app_object_annot(model, request.source_page, request.object_id, request.object_kind)
    if found is None:
        return False
    page, annot, payload = found
    if payload["kind"] == "rect":
        annot.set_rect(fitz.Rect(request.destination_rect))
        payload["rect"] = [
            float(request.destination_rect.x0),
            float(request.destination_rect.y0),
            float(request.destination_rect.x1),
            float(request.destination_rect.y1),
        ]
        annot.set_info(content=_dump_app_object_payload(model, payload), subject=_RECT_OBJECT_SUBJECT)
        annot.update()
        return True
    if payload["kind"] == "image":
        old_rect = fitz.Rect(payload.get("rect") or annot.rect)
        dest_rect = fitz.Rect(request.destination_rect)
        xref = _marker_xref(payload)
        rotation = float(payload.get("rotation", 0)) % 360
        if not xref:
            return False
        invocation = _resolve_marker_image_invocation(model, request.source_page, payload, old_rect)
        if invocation is None:
            return False
        if not _rewrite_native_image_matrix(model, invocation, dest_rect, rotation):
            return False
        annot.set_rect(dest_rect)
        payload["rect"] = [float(dest_rect.x0), float(dest_rect.y0), float(dest_rect.x1), float(dest_rect.y1)]
        annot.set_info(content=_dump_app_object_payload(model, payload), subject=_IMAGE_OBJECT_SUBJECT)
        annot.update()
        return True
    if payload["kind"] != "textbox":
        return False
    old_rect = fitz.Rect(payload["rect"])
    _redact_and_restore_textbox_region(model, page, old_rect, request.object_id)
    _delete_app_object_annots(model, request.source_page, request.object_id, expected_kind="textbox")
    insert_state = _insert_textbox_visual_content(model, 
        request.destination_page,
        fitz.Rect(request.destination_rect),
        payload["text"],
        font=payload["font"],
        size=payload["size"],
        color=tuple(payload["color"]),
        rotation=int(payload.get("rotation", 0)),
    )
    _create_textbox_object_marker(model, 
        request.destination_page,
        insert_state["bounded_visual"],
        text=payload["text"],
        font=payload["font"],
        size=payload["size"],
        color=tuple(payload["color"]),
        rotation=int(payload.get("rotation", 0)),
        object_id=request.object_id,
    )
    model.block_manager.rebuild_page(request.destination_page - 1, model.doc)
    # R6-01: redact+reinsert orphaned the prior content stream; register the mutation so
    # the batched garbage=4 round-trip reclaims it (bounds file growth over repeats).
    _register_mutation(model, request.destination_page - 1, old_rect | fitz.Rect(request.destination_rect))
    return True

def _rotate_native_image_absolute(
    model: PDFModel,
    invocation: NativeImageInvocation,
    angle: float,
) -> bool:
    """Rotate a (non-form) native image to an absolute angle about its centre."""
    if invocation.is_form_nested or invocation.cm_operator_index is None:
        return False
    # typed bind; callers guarantee an open doc here (native image rotate path) - runtime behavior identical if None
    doc: fitz.Document = model.doc
    page = doc[invocation.page_num - 1]
    stream = doc.xref_stream(invocation.stream_xref)
    tokens, operators = parse_operators(stream)
    if invocation.cm_operator_index >= len(operators):
        return False
    cm_operator = operators[invocation.cm_operator_index]
    if cm_operator.name != "cm":
        return False
    current_cm = _cm_values_from_operands(cm_operator.operands)
    if current_cm is None:
        return False
    width, height, _ang, centre_x, centre_y_user = decompose_image_cm(current_cm)
    page_height = float(fitz.Rect(page.mediabox).height)
    new_operands = rotated_image_stream_cm(
        centre_x,
        page_height - centre_y_user,
        width,
        height,
        float(angle) % 360.0,
        page_height,
    )
    new_stream = replace_operator_operands(tokens, cm_operator, new_operands)
    doc.update_stream(invocation.stream_xref, new_stream)
    model.pending_edits.append({"page_idx": invocation.page_num - 1, "rect": fitz.Rect(invocation.bbox)})
    model.edit_count += 1
    return True

def rotate_object(model: PDFModel, request: RotateObjectRequest) -> bool:
    if request.object_kind == "native_image":
        invocation = _find_native_image_invocation(model, request.page_num, request.object_id)
        if invocation is None:
            return False
        if request.absolute_rotation is not None:
            return _rotate_native_image_absolute(model, invocation, request.absolute_rotation)
        new_rotation = (float(invocation.rotation) + float(request.rotation_delta)) % 360
        return _rewrite_native_image_matrix(model, 
            invocation,
            fitz.Rect(invocation.bbox),
            new_rotation,
        )
    found = _find_app_object_annot(model, request.page_num, request.object_id, request.object_kind)
    if found is None:
        return False
    page, annot, payload = found
    if payload["kind"] != "textbox":
        if payload.get("kind") != "image":
            return False
        rect = fitz.Rect(payload.get("rect") or annot.rect)
        xref = _marker_xref(payload)
        if not xref:
            return False
        invocation = _resolve_marker_image_invocation(model, request.page_num, payload, rect)
        if invocation is None:
            return False
        if request.absolute_rotation is not None:
            if not _rotate_native_image_absolute(model, invocation, request.absolute_rotation):
                return False
            updated = _resolve_marker_image_invocation(model, request.page_num, payload, rect)
            new_bbox = fitz.Rect(updated.bbox) if updated is not None else rect
            payload["rotation"] = float(request.absolute_rotation) % 360
            payload["rect"] = [float(new_bbox.x0), float(new_bbox.y0), float(new_bbox.x1), float(new_bbox.y1)]
            annot.set_rect(new_bbox)
            annot.set_info(content=_dump_app_object_payload(model, payload), subject=_IMAGE_OBJECT_SUBJECT)
            annot.update()
            return True
        old_rotation = float(payload.get("rotation", 0)) % 360
        new_rotation = (old_rotation + float(request.rotation_delta)) % 360
        if not _rewrite_native_image_matrix(model, invocation, rect, new_rotation):
            return False
        payload["rotation"] = new_rotation
        annot.set_info(content=_dump_app_object_payload(model, payload), subject=_IMAGE_OBJECT_SUBJECT)
        annot.update()
        return True
    old_rect = fitz.Rect(payload["rect"])
    if request.absolute_rotation is not None:
        new_rotation = int(round(float(request.absolute_rotation))) % 360
    else:
        new_rotation = (int(payload.get("rotation", 0)) + int(request.rotation_delta)) % 360
    _redact_and_restore_textbox_region(model, page, old_rect, request.object_id)
    _delete_app_object_annots(model, request.page_num, request.object_id, expected_kind="textbox")
    insert_state = _insert_textbox_visual_content(model, 
        request.page_num,
        old_rect,
        payload["text"],
        font=payload["font"],
        size=payload["size"],
        color=tuple(payload["color"]),
        rotation=new_rotation,
    )
    _create_textbox_object_marker(model, 
        request.page_num,
        insert_state["bounded_visual"],
        text=payload["text"],
        font=payload["font"],
        size=payload["size"],
        color=tuple(payload["color"]),
        rotation=new_rotation,
        object_id=request.object_id,
    )
    model.block_manager.rebuild_page(request.page_num - 1, model.doc)
    # R6-01: redact+reinsert orphaned the prior content stream; register for batched GC.
    _register_mutation(model, request.page_num - 1, old_rect)
    return True

def _delete_object_impl(model: PDFModel, request: DeleteObjectRequest) -> bool:
    if request.object_kind == "native_image":
        invocation = _find_native_image_invocation(model, request.page_num, request.object_id)
        if invocation is None:
            return False
        if not _remove_native_image_invocation(model, invocation):
            return False
        return True
    found = _find_app_object_annot(model, request.page_num, request.object_id, request.object_kind)
    if found is None:
        return False
    page, annot, payload = found
    if payload["kind"] == "rect":
        marker_rect = fitz.Rect(annot.rect)
        page.delete_annot(annot)
        _register_mutation(model, request.page_num - 1, marker_rect)
        return True
    if payload["kind"] == "image":
        # Strip only this image's own content-stream invocation. The old path redacted
        # the image's rectangle, and apply_redactions is *geometric*: it destroys every
        # image, glyph and stroke the rectangle touches, not the one object the user
        # selected. Resolution mirrors move/rotate exactly.
        old_rect = fitz.Rect(payload.get("rect") or annot.rect)
        invocation = _resolve_marker_image_invocation(model, request.page_num, payload, old_rect)
        if invocation is None:
            # Two very different failures land here, and they want opposite handling.
            if _app_image_invocation_candidates(model, request.page_num, payload, old_rect):
                # Ambiguous: the pixels exist but we cannot say which placement is ours.
                # Fail safe — deleting the marker alone would orphan visible content, and
                # redacting is the data-loss vector this whole path exists to remove.
                return False
            # Orphaned: nothing renders this image any more (e.g. an external editor
            # stripped the XObject and left our hidden marker). Clean the marker up rather
            # than leaving a hit-detectable object that no verb can touch.
            if not _delete_app_object_annots(model, request.page_num, request.object_id, expected_kind="image"):
                return False
            _register_mutation(model, request.page_num - 1, old_rect)
            return True
        # _remove_native_image_invocation registers the pending edit + edit_count itself,
        # so no _register_mutation here (that would double-count).
        if not _remove_native_image_invocation(model, invocation):
            return False
        if not _delete_app_object_annots(model, request.page_num, request.object_id, expected_kind="image"):
            # The stream was already rewritten; a surviving marker would be a phantom
            # selectable object. Fail the transaction so the snapshot rollback restores it.
            return False
        return True
    if payload["kind"] != "textbox":
        return False
    old_rect = fitz.Rect(payload["rect"])
    _redact_and_restore_textbox_region(model, page, old_rect, request.object_id)
    restored = _find_app_object_annot(model, request.page_num, request.object_id, "textbox")
    if restored is not None:
        restored[0].delete_annot(restored[1])
    model.block_manager.rebuild_page(request.page_num - 1, model.doc)
    _register_mutation(model, request.page_num - 1, old_rect)
    return True


def _restore_delete_transaction(
    model: PDFModel,
    snapshot: bytes,
    pending_edits: list,
    edit_count: int,
    secure_save_required: bool,
) -> None:
    model._restore_doc_from_snapshot(snapshot)
    model.pending_edits = pending_edits
    model.edit_count = edit_count
    model.secure_save_required = secure_save_required
    try:
        model.block_manager.build_index(model.doc)
    except Exception:
        logger.exception("Failed to refresh text index after delete transaction rollback")


def _ordered_delete_requests(requests: list[DeleteObjectRequest]) -> list[DeleteObjectRequest]:
    """Keep native-image occurrence IDs stable by deleting highest occurrences first."""
    native: list[DeleteObjectRequest] = []
    others: list[DeleteObjectRequest] = []
    for request in requests:
        (native if request.object_kind == "native_image" else others).append(request)

    def _native_key(request: DeleteObjectRequest) -> tuple[int, int]:
        try:
            occurrence = int(str(request.object_id).rsplit(":", 1)[-1])
        except ValueError:
            occurrence = -1
        return (int(request.page_num), occurrence)

    native.sort(key=_native_key, reverse=True)
    return [*native, *others]


def delete_objects_atomic(model: PDFModel, requests: list[DeleteObjectRequest]) -> bool:
    """Delete all requested objects as one document-and-bookkeeping transaction."""
    if not requests:
        return False
    snapshot = model._capture_doc_snapshot()
    pending_edits = list(model.pending_edits)
    edit_count = int(model.edit_count)
    secure_save_required = bool(model.secure_save_required)
    try:
        for request in _ordered_delete_requests(list(requests)):
            if not _delete_object_impl(model, request):
                # Only roll back if the document was actually touched. `_restore_doc_from_snapshot`
                # closes and reopens `model.doc`, so running it on a pure no-op (resolution failed
                # before any stream was rewritten) would swap the live handle for nothing: cached
                # `fitz.Page` objects would point at a closed document, and the restored doc's empty
                # `doc.name` silently degrades the next save from incremental to full. Every mutating
                # path bumps `edit_count`, so comparing against the transaction's opening value
                # witnesses a mutation by this request *or* by any earlier one in the batch.
                if int(model.edit_count) != edit_count:
                    _restore_delete_transaction(
                        model, snapshot, pending_edits, edit_count, secure_save_required
                    )
                return False
    except Exception:
        _restore_delete_transaction(model, snapshot, pending_edits, edit_count, secure_save_required)
        raise
    model.secure_save_required = True
    return True


def delete_object(model: PDFModel, request: DeleteObjectRequest) -> bool:
    return delete_objects_atomic(model, [request])


def resize_object(model: PDFModel, request: ResizeObjectRequest) -> bool:
    # Resize is modeled as a move with a new destination rect on the same page.
    return move_object(model, 
        MoveObjectRequest(
            object_id=request.object_id,
            object_kind=request.object_kind,
            source_page=request.page_num,
            destination_page=request.page_num,
            destination_rect=fitz.Rect(request.destination_rect),
        )
    )
