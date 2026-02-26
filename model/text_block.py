import difflib
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Optional

import fitz

_RE_WS_STRIP = re.compile(r"\s+")
logger = logging.getLogger(__name__)


def rotation_degrees_from_dir(dir_tuple) -> int:
    """Convert line direction vector to nearest 0/90/180/270 rotation."""
    if not dir_tuple or len(dir_tuple) < 2:
        return 0
    dx, dy = float(dir_tuple[0]), float(dir_tuple[1])
    rad = math.atan2(dy, dx)
    deg = (math.degrees(rad) + 360) % 360
    nearest = round(deg / 90) * 90
    return int(nearest % 360)


@dataclass
class TextBlock:
    block_id: str
    page_num: int
    rect: fitz.Rect
    layout_rect: fitz.Rect
    text: str
    font: str
    size: float
    color: tuple
    rotation: int
    original_span_count: int = 0
    is_vertical: bool = field(init=False, default=False)

    def __post_init__(self):
        self.is_vertical = self.rotation in (90, 270)


@dataclass
class EditableSpan:
    span_id: str
    page_idx: int
    block_idx: int
    line_idx: int
    span_idx: int
    bbox: fitz.Rect
    origin: fitz.Point
    text: str
    font: str
    size: float
    color: tuple
    dir_vec: tuple
    rotation: int


class TextBlockManager:
    def __init__(self):
        self._index: dict[int, list[TextBlock]] = {}
        self._span_index: dict[int, list[EditableSpan]] = {}

    def build_index(self, doc: fitz.Document) -> None:
        self._index.clear()
        self._span_index.clear()
        for page_num in range(len(doc)):
            self._build_page_index(page_num, doc[page_num])
        total = sum(len(blocks) for blocks in self._index.values())
        logger.info(f"TextBlockManager index built: {total} blocks")

    def rebuild_page(self, page_num: int, doc: fitz.Document) -> None:
        if page_num < 0 or page_num >= len(doc):
            logger.warning(f"rebuild_page out of range: {page_num}")
            return
        self._build_page_index(page_num, doc[page_num])

    def _build_page_index(self, page_num: int, page: fitz.Page) -> None:
        blocks_raw = page.get_text("dict", flags=0).get("blocks", [])
        page_blocks: list[TextBlock] = []
        page_spans: list[EditableSpan] = []

        for block_idx, block in enumerate(blocks_raw):
            tb = self._parse_block(page_num, block_idx, block)
            if tb is not None:
                page_blocks.append(tb)
            page_spans.extend(self._parse_spans(page_num, block_idx, block))

        self._index[page_num] = page_blocks
        self._span_index[page_num] = page_spans
        logger.debug(
            f"page {page_num + 1}: {len(page_blocks)} blocks, {len(page_spans)} spans"
        )

    def get_blocks(self, page_num: int) -> list[TextBlock]:
        return self._index.get(page_num, [])

    def get_spans(self, page_num: int) -> list[EditableSpan]:
        return self._span_index.get(page_num, [])

    def find_by_id(self, page_num: int, block_id: str) -> Optional[TextBlock]:
        for block in self._index.get(page_num, []):
            if block.block_id == block_id:
                return block
        return None

    def find_span_by_id(self, page_num: int, span_id: str) -> Optional[EditableSpan]:
        for span in self._span_index.get(page_num, []):
            if span.span_id == span_id:
                return span
        return None

    def find_overlapping_spans(
        self,
        page_num: int,
        rect: fitz.Rect,
        tol: float = 0.5,
    ) -> list[EditableSpan]:
        expanded = fitz.Rect(rect.x0 - tol, rect.y0 - tol, rect.x1 + tol, rect.y1 + tol)
        return [
            span
            for span in self._span_index.get(page_num, [])
            if fitz.Rect(span.bbox).intersects(expanded)
        ]

    def find_by_rect(
        self,
        page_num: int,
        rect: fitz.Rect,
        original_text: Optional[str] = None,
        doc: Optional[fitz.Document] = None,
    ) -> Optional[TextBlock]:
        candidates = [
            b for b in self._index.get(page_num, []) if fitz.Rect(b.layout_rect).intersects(rect)
        ]

        if not candidates:
            if doc is not None:
                return self._dynamic_scan(page_num, rect, original_text, doc)
            return None

        if original_text and original_text.strip():
            matched = self._match_by_text(candidates, original_text)
            if matched is not None:
                return matched
        return self._closest_to_center(candidates, rect)

    def update_block(self, block: TextBlock, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(block, key):
                setattr(block, key, value)
        if "rotation" in kwargs:
            block.is_vertical = block.rotation in (90, 270)

    def clear(self) -> None:
        self._index.clear()
        self._span_index.clear()
        logger.debug("TextBlockManager index cleared")

    def _parse_block(
        self,
        page_num: int,
        raw_index: int,
        block: dict,
    ) -> Optional[TextBlock]:
        if block.get("type") != 0:
            return None

        block_rect = fitz.Rect(block["bbox"])
        text_parts: list[str] = []
        font_name = "helv"
        font_size = 12.0
        color_int = 0
        span_count = 0

        for line in block.get("lines", []) or []:
            for span in line.get("spans", []) or []:
                text_parts.append(span.get("text", ""))
                span_count += 1
                if font_name == "helv" and "font" in span:
                    font_name = span.get("font", "helv")
                    font_size = float(span.get("size", 12.0))
                    color_int = int(span.get("color", 0))

        text = "".join(text_parts)
        rgb_int = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
        color = tuple(c / 255.0 for c in rgb_int)

        rotation = 0
        first_line = (block.get("lines") or [None])[0]
        if first_line and first_line.get("dir") is not None:
            rotation = rotation_degrees_from_dir(first_line.get("dir"))

        return TextBlock(
            block_id=f"page_{page_num}_block_{raw_index}",
            page_num=page_num,
            rect=fitz.Rect(block_rect),
            layout_rect=fitz.Rect(block_rect),
            text=text,
            font=font_name,
            size=font_size,
            color=color,
            rotation=rotation,
            original_span_count=span_count,
        )

    def _parse_spans(
        self,
        page_num: int,
        block_idx: int,
        block: dict,
    ) -> list[EditableSpan]:
        if block.get("type") != 0:
            return []

        out: list[EditableSpan] = []
        for line_idx, line in enumerate(block.get("lines", []) or []):
            dir_vec = line.get("dir") or (1.0, 0.0)
            rotation = rotation_degrees_from_dir(dir_vec)
            for span_idx, span in enumerate(line.get("spans", []) or []):
                bbox_raw = span.get("bbox")
                if not bbox_raw:
                    continue
                text = span.get("text", "")
                if text == "":
                    continue
                color_int = int(span.get("color", 0))
                rgb_int = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
                color = tuple(c / 255.0 for c in rgb_int)
                origin_raw = span.get("origin") or (bbox_raw[0], bbox_raw[3])
                out.append(
                    EditableSpan(
                        span_id=f"p{page_num}_b{block_idx}_l{line_idx}_s{span_idx}",
                        page_idx=page_num,
                        block_idx=block_idx,
                        line_idx=line_idx,
                        span_idx=span_idx,
                        bbox=fitz.Rect(bbox_raw),
                        origin=fitz.Point(float(origin_raw[0]), float(origin_raw[1])),
                        text=text,
                        font=span.get("font", "helv"),
                        size=float(span.get("size", 12.0)),
                        color=color,
                        dir_vec=(float(dir_vec[0]), float(dir_vec[1])),
                        rotation=rotation,
                    )
                )
        return out

    def _match_by_text(
        self,
        candidates: list[TextBlock],
        original_text: str,
    ) -> Optional[TextBlock]:
        original_clean = _RE_WS_STRIP.sub("", original_text.strip()).lower()
        if not original_clean:
            return None

        best_block: Optional[TextBlock] = None
        best_similarity = 0.5

        for block in candidates:
            block_clean = _RE_WS_STRIP.sub("", block.text.strip()).lower()
            if not block_clean:
                continue

            len_ratio = max(len(original_clean), len(block_clean)) / max(
                1, min(len(original_clean), len(block_clean))
            )
            if len_ratio > 3.0:
                continue

            if original_clean in block_clean or block_clean in original_clean:
                return block

            similarity = difflib.SequenceMatcher(None, original_clean, block_clean).ratio()
            if similarity > best_similarity:
                best_similarity = similarity
                best_block = block

        return best_block

    def _closest_to_center(
        self,
        candidates: list[TextBlock],
        rect: fitz.Rect,
    ) -> Optional[TextBlock]:
        rect_cx = rect.x0 + rect.width / 2
        rect_cy = rect.y0 + rect.height / 2
        best_block: Optional[TextBlock] = None
        min_distance = float("inf")

        for block in candidates:
            bcx = block.layout_rect.x0 + block.layout_rect.width / 2
            bcy = block.layout_rect.y0 + block.layout_rect.height / 2
            dist = abs(bcx - rect_cx) + abs(bcy - rect_cy)
            if dist < min_distance:
                min_distance = dist
                best_block = block

        return best_block

    def _dynamic_scan(
        self,
        page_num: int,
        rect: fitz.Rect,
        original_text: Optional[str],
        doc: fitz.Document,
    ) -> Optional[TextBlock]:
        page = doc[page_num]
        blocks_raw = page.get_text("dict", flags=0).get("blocks", [])
        temp_blocks: list[TextBlock] = []

        for i, block in enumerate(blocks_raw):
            if block.get("type") != 0:
                continue
            if not fitz.Rect(block["bbox"]).intersects(rect):
                continue
            tb = self._parse_block(page_num, i, block)
            if tb is not None:
                temp_blocks.append(tb)

        if not temp_blocks:
            return None
        if original_text and original_text.strip():
            matched = self._match_by_text(temp_blocks, original_text)
            if matched is not None:
                return matched
        return self._closest_to_center(temp_blocks, rect)
