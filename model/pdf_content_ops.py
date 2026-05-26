from __future__ import annotations

from dataclasses import dataclass

import fitz

from model.geometry import rect_from_points


_DELIM_BYTES = b"()<>[]{}/%"
_WHITESPACE_BYTES = b" \t\r\n\x0c\x00"
_CONTENT_OPERATORS = {
    "b", "B", "b*", "B*", "BDC", "BI", "BMC", "BT", "BX", "c", "cm", "CS", "cs", "d", "d0", "d1",
    "Do", "DP", "EI", "EMC", "ET", "EX", "f", "F", "f*", "G", "g", "gs", "h", "i", "ID", "j", "J",
    "K", "k", "l", "m", "M", "MP", "n", "q", "Q", "re", "RG", "rg", "ri", "s", "S", "sc", "SC",
    "scn", "SCN", "sh", "T*", "Tc", "Td", "TD", "Tf", "Tj", "TJ", "TL", "Tm", "Tr", "Ts", "Tw",
    "Tz", "v", "w", "W", "W*", "y", "'", "\"",
}


@dataclass(frozen=True)
class ContentToken:
    raw: bytes


@dataclass(frozen=True)
class ParsedOperator:
    name: str
    operands: tuple[ContentToken, ...]
    operand_start: int
    operator_index: int


@dataclass(frozen=True)
class NativeImageInvocation:
    page_num: int
    occurrence_index: int
    stream_xref: int
    xobject_name: str
    xref: int
    bbox: fitz.Rect
    rotation: int
    cm_operator_index: int | None
    do_operator_index: int
    q_operator_index: int | None
    q_end_operator_index: int | None
    q_image_invocation_count: int
    # xref whose /Resources/XObject holds ``xobject_name`` — the page for direct
    # invocations, the Form XObject for form-nested ones. Used for resource pruning.
    resource_owner_xref: int = 0
    # True when the image is drawn inside a Form XObject rather than directly on
    # the page; the rewrite path then works in the form's coordinate space.
    is_form_nested: bool = False


def _is_whitespace(byte: int) -> bool:
    return byte in _WHITESPACE_BYTES


def _is_delimiter(byte: int) -> bool:
    return byte in _DELIM_BYTES


def tokenize_content_stream(stream: bytes) -> list[ContentToken]:
    tokens: list[ContentToken] = []
    i = 0
    n = len(stream)
    while i < n:
        current = stream[i]
        if _is_whitespace(current):
            i += 1
            continue
        if current == ord("%"):
            i += 1
            while i < n and stream[i] not in (ord("\r"), ord("\n")):
                i += 1
            continue
        if current == ord("/"):
            start = i
            i += 1
            while i < n and not _is_whitespace(stream[i]) and not _is_delimiter(stream[i]):
                i += 1
            tokens.append(ContentToken(stream[start:i]))
            continue
        if current == ord("("):
            start = i
            i += 1
            depth = 1
            while i < n and depth > 0:
                byte = stream[i]
                if byte == ord("\\"):
                    i += 2
                    continue
                if byte == ord("("):
                    depth += 1
                elif byte == ord(")"):
                    depth -= 1
                i += 1
            tokens.append(ContentToken(stream[start:i]))
            continue
        if current == ord("<"):
            start = i
            if i + 1 < n and stream[i + 1] == ord("<"):
                tokens.append(ContentToken(b"<<"))
                i += 2
                continue
            i += 1
            while i < n and stream[i] != ord(">"):
                i += 1
            if i < n:
                i += 1
            tokens.append(ContentToken(stream[start:i]))
            continue
        if current == ord(">") and i + 1 < n and stream[i + 1] == ord(">"):
            tokens.append(ContentToken(b">>"))
            i += 2
            continue
        if current in (ord("["), ord("]"), ord("{"), ord("}")):
            tokens.append(ContentToken(stream[i : i + 1]))
            i += 1
            continue
        start = i
        i += 1
        while i < n and not _is_whitespace(stream[i]) and not _is_delimiter(stream[i]):
            i += 1
        tokens.append(ContentToken(stream[start:i]))
    return tokens


def parse_operators(stream: bytes) -> tuple[list[ContentToken], list[ParsedOperator]]:
    tokens = tokenize_content_stream(stream)
    operators: list[ParsedOperator] = []
    operands: list[ContentToken] = []
    operand_start = 0
    for index, token in enumerate(tokens):
        token_text = token.raw.decode("latin-1")
        if token_text in _CONTENT_OPERATORS:
            operators.append(
                ParsedOperator(
                    name=token_text,
                    operands=tuple(operands),
                    operand_start=operand_start,
                    operator_index=index,
                )
            )
            operands = []
            operand_start = index + 1
        else:
            if not operands:
                operand_start = index
            operands.append(token)
    return tokens, operators


def _rotation_from_cm(a: float, b: float, c: float, d: float) -> int:
    candidates = {
        0: (1.0, 0.0, 0.0, 1.0),
        90: (0.0, 1.0, -1.0, 0.0),
        180: (-1.0, 0.0, 0.0, -1.0),
        270: (0.0, -1.0, 1.0, 0.0),
    }
    scale_x = max(abs(a), abs(b), 1e-9)
    scale_y = max(abs(c), abs(d), 1e-9)
    norm = (a / scale_x, b / scale_x, c / scale_y, d / scale_y)
    best_rotation = 0
    best_score = float("inf")
    for rotation, expected in candidates.items():
        score = sum(abs(norm[idx] - expected[idx]) for idx in range(4))
        if score < best_score:
            best_score = score
            best_rotation = rotation
    return best_rotation


def _cm_values_from_operands(operands: tuple[ContentToken, ...]) -> tuple[float, float, float, float, float, float] | None:
    if len(operands) < 6:
        return None
    raw_values = operands[-6:]
    try:
        return tuple(float(token.raw.decode("latin-1")) for token in raw_values)  # type: ignore[return-value]
    except Exception:
        return None


def _bbox_from_stream_cm(
    cm: tuple[float, float, float, float, float, float],
    *,
    mediabox_height: float,
    crop_x0: float,
    crop_y0: float,
) -> fitz.Rect:
    a, b, c, d, e, f = cm
    corners = (
        (0.0, 0.0),
        (1.0, 0.0),
        (0.0, 1.0),
        (1.0, 1.0),
    )
    # PyMuPDF reports image bboxes in a coordinate space that is affected by CropBox by
    # shifting results by (crop_x0, crop_y0) while still using the original MediaBox height.
    points = [
        fitz.Point(a * x + c * y + e - crop_x0, mediabox_height - (b * x + d * y + f) - crop_y0)
        for x, y in corners
    ]
    return rect_from_points(points)


def _q_bounds_by_operator_index(operators: list[ParsedOperator]) -> tuple[dict[int, int | None], dict[int, int]]:
    q_to_end: dict[int, int | None] = {}
    q_invocation_counts: dict[int, int] = {}
    stack: list[int] = []
    for op_index, operator in enumerate(operators):
        if operator.name == "q":
            stack.append(op_index)
            q_to_end[op_index] = None
            q_invocation_counts[op_index] = 0
        elif operator.name == "Q":
            if stack:
                q_to_end[stack.pop()] = op_index
        elif operator.name == "Do" and stack:
            for q_index in stack:
                q_invocation_counts[q_index] += 1
    return q_to_end, q_invocation_counts


def discover_native_image_invocations(doc: fitz.Document, page_num: int) -> list[NativeImageInvocation]:
    page = doc[page_num - 1]
    mediabox = fitz.Rect(page.mediabox)
    cropbox = fitz.Rect(page.cropbox)
    mediabox_height = float(mediabox.height)
    crop_x0 = float(cropbox.x0)
    crop_y0 = float(cropbox.y0)
    image_name_to_xref = {str(image[7]): int(image[0]) for image in page.get_images(full=True)}
    placements_by_xref: dict[int, list[tuple[fitz.Rect, fitz.Matrix]]] = {}
    placement_offsets: dict[int, int] = {}
    for xref in set(image_name_to_xref.values()):
        placements = list(page.get_image_rects(xref, transform=True))
        placements_by_xref[xref] = [(fitz.Rect(rect), matrix) for rect, matrix in placements]
        placement_offsets[xref] = 0
    invocations: list[NativeImageInvocation] = []
    occurrence_index = 0
    for stream_xref in [int(xref) for xref in page.get_contents() if int(xref) > 0]:
        stream = doc.xref_stream(stream_xref)
        _, operators = parse_operators(stream)
        q_to_end, q_invocation_counts = _q_bounds_by_operator_index(operators)
        last_cm_by_depth: list[int | None] = [None]
        q_stack: list[int] = []
        for op_index, operator in enumerate(operators):
            if operator.name == "q":
                q_stack.append(op_index)
                last_cm_by_depth.append(None)
                continue
            if operator.name == "Q":
                if q_stack:
                    q_stack.pop()
                if len(last_cm_by_depth) > 1:
                    last_cm_by_depth.pop()
                continue
            if operator.name == "cm":
                last_cm_by_depth[-1] = op_index
                continue
            if operator.name != "Do" or not operator.operands:
                continue
            image_name = operator.operands[-1].raw.decode("latin-1").lstrip("/")
            if image_name not in image_name_to_xref:
                continue
            xref = image_name_to_xref[image_name]
            placements = placements_by_xref.get(xref, [])
            placement_index = placement_offsets.get(xref, 0)
            cm_index = last_cm_by_depth[-1]
            cm_values = _cm_values_from_operands(operators[cm_index].operands) if cm_index is not None else None
            bbox: fitz.Rect | None = None
            rotation = 0
            if cm_values is not None:
                bbox = _bbox_from_stream_cm(
                    cm_values,
                    mediabox_height=mediabox_height,
                    crop_x0=crop_x0,
                    crop_y0=crop_y0,
                )
                rotation = _rotation_from_cm(cm_values[0], cm_values[1], cm_values[2], cm_values[3])
                if placement_index < len(placements):
                    placement_offsets[xref] = placement_index + 1
            elif placement_index < len(placements):
                bbox, transform = placements[placement_index]
                placement_offsets[xref] = placement_index + 1
                rotation = _rotation_from_cm(transform.a, transform.b, transform.c, transform.d)
            else:
                continue
            q_index = q_stack[-1] if q_stack else None
            invocations.append(
                NativeImageInvocation(
                    page_num=page_num,
                    occurrence_index=occurrence_index,
                    stream_xref=stream_xref,
                    xobject_name=image_name,
                    xref=xref,
                    bbox=fitz.Rect(bbox),
                    rotation=rotation,
                    cm_operator_index=cm_index,
                    do_operator_index=op_index,
                    q_operator_index=q_index,
                    q_end_operator_index=q_to_end.get(q_index) if q_index is not None else None,
                    q_image_invocation_count=q_invocation_counts.get(q_index, 0) if q_index is not None else 0,
                    resource_owner_xref=int(page.xref),
                    is_form_nested=False,
                )
            )
            occurrence_index += 1

    occurrence_index = _discover_form_nested_invocations(
        doc,
        page,
        page_num,
        placements_by_xref,
        placement_offsets,
        invocations,
        occurrence_index,
    )
    return invocations


def _discover_form_nested_invocations(
    doc: fitz.Document,
    page: fitz.Page,
    page_num: int,
    placements_by_xref: dict[int, list[tuple[fitz.Rect, fitz.Matrix]]],
    placement_offsets: dict[int, int],
    invocations: list[NativeImageInvocation],
    occurrence_index: int,
) -> int:
    """Discover image ``Do`` invocations that live inside Form XObjects.

    Many PDFs (e.g. exported from layout tools) wrap page content — including
    images — in a Form XObject, so the page content stream only contains
    ``/Fm0 Do`` and the image is invoked one level down. We walk each page-level
    form's stream, resolve image names against that form's own resources, and
    reuse the page-space placement from ``get_image_rects`` for the bbox.
    Depth-1 only (forms referenced directly by the page), which covers the
    common case. A PDF with no image-bearing forms is unaffected (no-op).
    """
    try:
        form_xobjects = page.get_xobjects()
    except Exception:
        return occurrence_index

    # Per-form image-name → xref maps, keyed by the referencing (form) xref.
    images_by_referencer: dict[int, dict[str, int]] = {}
    try:
        for row in page.get_images(full=True):
            referencer = int(row[9])
            images_by_referencer.setdefault(referencer, {})[str(row[7])] = int(row[0])
    except Exception:
        return occurrence_index

    processed_forms: set[int] = set()
    for xobj in form_xobjects:
        form_xref = int(xobj[0])
        if form_xref in processed_forms:
            continue
        processed_forms.add(form_xref)
        try:
            subtype = doc.xref_get_key(form_xref, "Subtype")
        except Exception:
            continue
        if not (isinstance(subtype, tuple) and subtype[1] == "/Form"):
            continue
        form_images = images_by_referencer.get(form_xref)
        if not form_images:
            continue
        try:
            stream = doc.xref_stream(form_xref)
        except Exception:
            continue
        _, operators = parse_operators(stream)
        q_to_end, q_invocation_counts = _q_bounds_by_operator_index(operators)
        last_cm_by_depth: list[int | None] = [None]
        q_stack: list[int] = []
        for op_index, operator in enumerate(operators):
            if operator.name == "q":
                q_stack.append(op_index)
                last_cm_by_depth.append(None)
                continue
            if operator.name == "Q":
                if q_stack:
                    q_stack.pop()
                if len(last_cm_by_depth) > 1:
                    last_cm_by_depth.pop()
                continue
            if operator.name == "cm":
                last_cm_by_depth[-1] = op_index
                continue
            if operator.name != "Do" or not operator.operands:
                continue
            image_name = operator.operands[-1].raw.decode("latin-1").lstrip("/")
            if image_name not in form_images:
                continue
            xref = form_images[image_name]
            placements = placements_by_xref.get(xref, [])
            placement_index = placement_offsets.get(xref, 0)
            if placement_index >= len(placements):
                continue
            bbox, transform = placements[placement_index]
            placement_offsets[xref] = placement_index + 1
            rotation = _rotation_from_cm(transform.a, transform.b, transform.c, transform.d)
            cm_index = last_cm_by_depth[-1]
            q_index = q_stack[-1] if q_stack else None
            invocations.append(
                NativeImageInvocation(
                    page_num=page_num,
                    occurrence_index=occurrence_index,
                    stream_xref=form_xref,
                    xobject_name=image_name,
                    xref=xref,
                    bbox=fitz.Rect(bbox),
                    rotation=rotation,
                    cm_operator_index=cm_index,
                    do_operator_index=op_index,
                    q_operator_index=q_index,
                    q_end_operator_index=q_to_end.get(q_index) if q_index is not None else None,
                    q_image_invocation_count=q_invocation_counts.get(q_index, 0) if q_index is not None else 0,
                    resource_owner_xref=form_xref,
                    is_form_nested=True,
                )
            )
            occurrence_index += 1
    return occurrence_index


def replace_operator_operands(tokens: list[ContentToken], operator: ParsedOperator, new_operands: list[bytes]) -> bytes:
    start = operator.operand_start
    end = operator.operator_index
    replacement = [ContentToken(raw=value) for value in new_operands]
    rewritten = tokens[:start] + replacement + tokens[end:]
    return serialize_tokens(rewritten)


def remove_operator_range(tokens: list[ContentToken], start_token: int, end_token: int) -> bytes:
    rewritten = tokens[:start_token] + tokens[end_token + 1 :]
    return serialize_tokens(rewritten)


def serialize_tokens(tokens: list[ContentToken]) -> bytes:
    if not tokens:
        return b"\n"
    return b"\n".join(token.raw for token in tokens) + b"\n"


def fitz_rect_to_stream_cm(rect: fitz.Rect, page: fitz.Page, rotation: int) -> list[bytes]:
    bbox = fitz.Rect(rect)
    width = float(bbox.width)
    height = float(bbox.height)
    cropbox = fitz.Rect(page.cropbox)
    mediabox = fitz.Rect(page.mediabox)
    crop_x0 = float(cropbox.x0)
    crop_y0 = float(cropbox.y0)
    page_height = float(mediabox.height)
    x0 = float(bbox.x0) + crop_x0
    x1 = float(bbox.x1) + crop_x0
    y0 = float(bbox.y0)
    y1 = float(bbox.y1)
    if rotation % 360 == 0:
        values = (width, 0.0, 0.0, height, x0, page_height - (y1 + crop_y0))
    elif rotation % 360 == 90:
        values = (0.0, height, -width, 0.0, x1, page_height - (y1 + crop_y0))
    elif rotation % 360 == 180:
        values = (-width, 0.0, 0.0, -height, x1, page_height - (y0 + crop_y0))
    else:
        values = (0.0, -height, width, 0.0, x0, page_height - (y0 + crop_y0))
    return [f"{value:g}".encode("ascii") for value in values]


def form_rect_to_stream_cm(
    destination_rect: fitz.Rect,
    current_cm_values: tuple[float, float, float, float, float, float],
    current_page_bbox: fitz.Rect,
    rotation: int,
) -> list[bytes] | None:
    """Build a new ``cm`` for an image drawn inside a Form XObject.

    The image's cm lives in the *form's* coordinate space, which reaches page
    space through an outer placement transform (the page ``cm`` before
    ``/Fm Do`` composed with the form ``Matrix``). Rather than reconstruct that
    transform from document internals, we recover the affine placement
    empirically from the correspondence between the *current* form-space cm and
    the *current* page-space bbox, then invert it for the destination rect.

    Only axis-aligned, non-rotated placements/images are supported (the common
    Form-wrapper case). Returns None for rotated/sheared images so the caller can
    refuse the edit rather than corrupt the page.
    """
    a, b, c, d, e, f = current_cm_values
    eps = 1e-6
    # Reject shear/rotation in the image cm, and rotation of the placement
    # itself (handled by demanding the current invocation be un-rotated).
    if abs(b) > eps or abs(c) > eps or rotation % 360 != 0:
        return None
    if abs(a) < eps or abs(d) < eps:
        return None

    old = fitz.Rect(current_page_bbox)
    if old.width <= eps or old.height <= eps:
        return None

    # Placement scale/translate with the page y-flip folded in:
    #   page.x = sx * form.x + tx ,  page.y_top = -sy * form.y_top + ty
    # derived from the current correspondence (image occupies [e, e+a]×[f, f+d]
    # in form space and ``old`` in page space, page coords being y-down).
    sx = old.width / a
    sy = old.height / d
    tx = old.x0 - sx * e
    ty = old.y1 + sy * f

    dest = fitz.Rect(destination_rect)
    new_a = dest.width / sx
    new_d = dest.height / sy
    new_e = (dest.x0 - tx) / sx
    new_f = (ty - dest.y1) / sy
    values = (new_a, 0.0, 0.0, new_d, new_e, new_f)
    return [f"{value:g}".encode("ascii") for value in values]
