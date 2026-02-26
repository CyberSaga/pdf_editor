import difflib
import logging
import math
import re
import statistics
import unicodedata
from collections import Counter
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


def _norm_dir_vec(dir_tuple) -> tuple[float, float]:
    if not dir_tuple or len(dir_tuple) < 2:
        return (1.0, 0.0)
    dx, dy = float(dir_tuple[0]), float(dir_tuple[1])
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return (1.0, 0.0)
    return (dx / length, dy / length)


def _rect_axis_projection(rect: fitz.Rect, ux: float, uy: float, vx: float, vy: float) -> tuple[float, float, float, float]:
    pts = (
        (rect.x0, rect.y0),
        (rect.x1, rect.y0),
        (rect.x0, rect.y1),
        (rect.x1, rect.y1),
    )
    uvals = [x * ux + y * uy for x, y in pts]
    vvals = [x * vx + y * vy for x, y in pts]
    return (min(uvals), max(uvals), min(vvals), max(vvals))


def _char_kind(ch: str) -> str:
    if not ch:
        return "other"
    if ch.isspace():
        return "space"
    code = ord(ch)
    if (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    ):
        return "cjk"
    cat = unicodedata.category(ch)
    if cat.startswith("P"):
        return "punct"
    if cat.startswith("N"):
        return "latin"
    if cat.startswith("L"):
        return "latin"
    return "other"


def _kind_compatible(prev_kind: str, curr_kind: str) -> bool:
    if prev_kind == curr_kind:
        return True
    if "punct" in (prev_kind, curr_kind):
        return True
    if "other" in (prev_kind, curr_kind):
        return True
    if prev_kind == "latin" and curr_kind == "latin":
        return True
    return False


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


@dataclass
class EditableParagraph:
    paragraph_id: str
    page_idx: int
    block_idx: int
    bbox: fitz.Rect
    text: str
    font: str
    size: float
    color: tuple
    dir_vec: tuple
    rotation: int
    run_ids: list[str]
    line_start: int
    line_end: int


class TextBlockManager:
    def __init__(self):
        self._index: dict[int, list[TextBlock]] = {}
        self._span_index: dict[int, list[EditableSpan]] = {}
        self._paragraph_index: dict[int, list[EditableParagraph]] = {}
        self._run_to_paragraph: dict[int, dict[str, str]] = {}

    def build_index(self, doc: fitz.Document) -> None:
        self._index.clear()
        self._span_index.clear()
        self._paragraph_index.clear()
        self._run_to_paragraph.clear()
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
        raw_blocks = page.get_text("rawdict", flags=0).get("blocks", [])
        page_blocks: list[TextBlock] = []
        page_spans: list[EditableSpan] = []

        for block_idx, block in enumerate(blocks_raw):
            tb = self._parse_block(page_num, block_idx, block)
            if tb is not None:
                page_blocks.append(tb)
            raw_block = raw_blocks[block_idx] if block_idx < len(raw_blocks) else None
            if raw_block and raw_block.get("type") == 0:
                runs = self._parse_runs_from_raw_block(page_num, block_idx, raw_block)
                if runs:
                    page_spans.extend(runs)
                    continue
            page_spans.extend(self._parse_spans(page_num, block_idx, block))

        self._index[page_num] = page_blocks
        self._span_index[page_num] = page_spans
        paragraphs = self._build_paragraphs(page_num, page_spans)
        self._paragraph_index[page_num] = paragraphs
        run_map: dict[str, str] = {}
        for para in paragraphs:
            for run_id in para.run_ids:
                run_map[run_id] = para.paragraph_id
        self._run_to_paragraph[page_num] = run_map
        logger.debug(
            f"page {page_num + 1}: {len(page_blocks)} blocks, {len(page_spans)} spans(runs), "
            f"{len(paragraphs)} paragraphs"
        )

    def get_blocks(self, page_num: int) -> list[TextBlock]:
        return self._index.get(page_num, [])

    def get_spans(self, page_num: int) -> list[EditableSpan]:
        return self._span_index.get(page_num, [])

    # Run-level aliases: reconstructed runs are stored in _span_index for compatibility.
    def get_runs(self, page_num: int) -> list[EditableSpan]:
        return self.get_spans(page_num)

    def get_paragraphs(self, page_num: int) -> list[EditableParagraph]:
        return self._paragraph_index.get(page_num, [])

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

    def find_run_by_id(self, page_num: int, run_id: str) -> Optional[EditableSpan]:
        return self.find_span_by_id(page_num, run_id)

    def find_paragraph_by_id(self, page_num: int, paragraph_id: str) -> Optional[EditableParagraph]:
        for para in self._paragraph_index.get(page_num, []):
            if para.paragraph_id == paragraph_id:
                return para
        return None

    def find_paragraph_for_run(self, page_num: int, run_id: str) -> Optional[EditableParagraph]:
        para_id = self._run_to_paragraph.get(page_num, {}).get(run_id)
        if not para_id:
            return None
        return self.find_paragraph_by_id(page_num, para_id)

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

    def find_overlapping_runs(
        self,
        page_num: int,
        rect: fitz.Rect,
        tol: float = 0.5,
    ) -> list[EditableSpan]:
        return self.find_overlapping_spans(page_num, rect, tol=tol)

    def find_overlapping_paragraphs(
        self,
        page_num: int,
        rect: fitz.Rect,
        tol: float = 0.5,
    ) -> list[EditableParagraph]:
        expanded = fitz.Rect(rect.x0 - tol, rect.y0 - tol, rect.x1 + tol, rect.y1 + tol)
        return [
            para
            for para in self._paragraph_index.get(page_num, [])
            if fitz.Rect(para.bbox).intersects(expanded)
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
        self._paragraph_index.clear()
        self._run_to_paragraph.clear()
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

    def _parse_runs_from_raw_block(
        self,
        page_num: int,
        block_idx: int,
        raw_block: dict,
    ) -> list[EditableSpan]:
        lines = raw_block.get("lines", []) or []
        if not lines:
            return []

        out: list[EditableSpan] = []
        for line_idx, line in enumerate(lines):
            out.extend(self._parse_runs_from_raw_line(page_num, block_idx, line_idx, line))
        return out

    def _parse_runs_from_raw_line(
        self,
        page_num: int,
        block_idx: int,
        line_idx: int,
        line: dict,
    ) -> list[EditableSpan]:
        dir_vec = _norm_dir_vec(line.get("dir") or (1.0, 0.0))
        ux, uy = dir_vec
        vx, vy = (-uy, ux)
        rotation = rotation_degrees_from_dir(dir_vec)

        chars: list[dict] = []
        for span_idx, span in enumerate(line.get("spans", []) or []):
            color_int = int(span.get("color", 0))
            rgb_int = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
            color = tuple(c / 255.0 for c in rgb_int)
            font_name = span.get("font", "helv")
            font_size = float(span.get("size", 12.0))

            span_chars = span.get("chars") or []
            if span_chars:
                for char_idx, ch in enumerate(span_chars):
                    ch_text = ch.get("c", "")
                    bbox_raw = ch.get("bbox")
                    if not bbox_raw:
                        continue
                    bbox = fitz.Rect(bbox_raw)
                    origin_raw = ch.get("origin") or (bbox.x0, bbox.y1)
                    u0, u1, v0, v1 = _rect_axis_projection(bbox, ux, uy, vx, vy)
                    chars.append(
                        {
                            "text": ch_text,
                            "bbox": bbox,
                            "origin": fitz.Point(float(origin_raw[0]), float(origin_raw[1])),
                            "font": font_name,
                            "size": font_size,
                            "color": color,
                            "kind": _char_kind(ch_text),
                            "u0": u0,
                            "u1": u1,
                            "uc": (u0 + u1) / 2.0,
                            "vc": (v0 + v1) / 2.0,
                            "source_span_idx": span_idx,
                            "source_char_idx": char_idx,
                        }
                    )
                continue

            # Fallback for PDFs that expose span text without per-char geometry in rawdict.
            span_text = span.get("text", "")
            bbox_raw = span.get("bbox")
            if not span_text or not bbox_raw:
                continue
            bbox = fitz.Rect(bbox_raw)
            origin_raw = span.get("origin") or (bbox.x0, bbox.y1)
            u0, u1, v0, v1 = _rect_axis_projection(bbox, ux, uy, vx, vy)
            chars.append(
                {
                    "text": span_text,
                    "bbox": bbox,
                    "origin": fitz.Point(float(origin_raw[0]), float(origin_raw[1])),
                    "font": font_name,
                    "size": font_size,
                    "color": color,
                    "kind": "other",
                    "u0": u0,
                    "u1": u1,
                    "uc": (u0 + u1) / 2.0,
                    "vc": (v0 + v1) / 2.0,
                    "source_span_idx": span_idx,
                    "source_char_idx": 0,
                }
            )

        if not chars:
            return []

        chars.sort(key=lambda c: (c["uc"], c["vc"], c["source_span_idx"], c["source_char_idx"]))
        extents = [max(0.1, float(c["u1"] - c["u0"])) for c in chars]
        median_extent = statistics.median(extents) if extents else 1.0
        gap_tol = max(0.8, median_extent * 0.35)
        hard_gap_tol = max(gap_tol * 2.2, median_extent * 1.2)
        cross_tol = max(1.0, median_extent * 0.75)

        def _finalize(run: dict, run_idx: int) -> Optional[EditableSpan]:
            text_value = "".join(run["text_parts"]).strip()
            if not text_value:
                return None
            bbox = fitz.Rect(run["bbox"])
            dominant_font = run["font_counter"].most_common(1)[0][0] if run["font_counter"] else "helv"
            dominant_color = (
                run["color_counter"].most_common(1)[0][0]
                if run["color_counter"]
                else (0.0, 0.0, 0.0)
            )
            avg_size = run["size_sum"] / max(1, run["size_count"])
            return EditableSpan(
                span_id=f"p{page_num}_b{block_idx}_l{line_idx}_s{run_idx}",
                page_idx=page_num,
                block_idx=block_idx,
                line_idx=line_idx,
                span_idx=run_idx,
                bbox=bbox,
                origin=fitz.Point(run["origin"].x, run["origin"].y),
                text=text_value,
                font=dominant_font,
                size=float(avg_size),
                color=tuple(dominant_color),
                dir_vec=(float(dir_vec[0]), float(dir_vec[1])),
                rotation=rotation,
            )

        runs: list[EditableSpan] = []
        run_idx = 0
        current: Optional[dict] = None
        for ch in chars:
            text_value = ch["text"]
            if not text_value:
                continue

            # Space characters define run boundaries for Latin-like text.
            if text_value.isspace():
                if current is not None:
                    built = _finalize(current, run_idx)
                    if built is not None:
                        runs.append(built)
                        run_idx += 1
                    current = None
                continue

            if current is None:
                current = {
                    "text_parts": [text_value],
                    "bbox": fitz.Rect(ch["bbox"]),
                    "origin": fitz.Point(ch["origin"].x, ch["origin"].y),
                    "font_counter": Counter([ch["font"]]),
                    "color_counter": Counter([tuple(ch["color"])]),
                    "size_sum": float(ch["size"]),
                    "size_count": 1,
                    "kind": ch["kind"],
                    "last_u1": float(ch["u1"]),
                    "last_vc": float(ch["vc"]),
                    "last_size": float(ch["size"]),
                    "last_kind": ch["kind"],
                    "last_color": tuple(ch["color"]),
                }
                continue

            gap = float(ch["u0"]) - float(current["last_u1"])
            cross_delta = abs(float(ch["vc"]) - float(current["last_vc"]))
            size_delta = abs(float(ch["size"]) - float(current["last_size"]))
            color_changed = tuple(ch["color"]) != tuple(current["last_color"])
            kind_changed = not _kind_compatible(str(current["last_kind"]), str(ch["kind"]))

            should_break = False
            if cross_delta > cross_tol:
                should_break = True
            elif gap > hard_gap_tol:
                should_break = True
            elif size_delta > max(0.9, float(current["last_size"]) * 0.25):
                should_break = True
            elif color_changed:
                should_break = True
            elif kind_changed:
                should_break = True
            elif gap > gap_tol:
                should_break = True

            if should_break:
                built = _finalize(current, run_idx)
                if built is not None:
                    runs.append(built)
                    run_idx += 1
                current = {
                    "text_parts": [text_value],
                    "bbox": fitz.Rect(ch["bbox"]),
                    "origin": fitz.Point(ch["origin"].x, ch["origin"].y),
                    "font_counter": Counter([ch["font"]]),
                    "color_counter": Counter([tuple(ch["color"])]),
                    "size_sum": float(ch["size"]),
                    "size_count": 1,
                    "kind": ch["kind"],
                    "last_u1": float(ch["u1"]),
                    "last_vc": float(ch["vc"]),
                    "last_size": float(ch["size"]),
                    "last_kind": ch["kind"],
                    "last_color": tuple(ch["color"]),
                }
                continue

            current["text_parts"].append(text_value)
            current["bbox"].include_rect(ch["bbox"])
            current["font_counter"][ch["font"]] += 1
            current["color_counter"][tuple(ch["color"])] += 1
            current["size_sum"] += float(ch["size"])
            current["size_count"] += 1
            current["last_u1"] = float(ch["u1"])
            current["last_vc"] = float(ch["vc"])
            current["last_size"] = float(ch["size"])
            current["last_kind"] = ch["kind"]
            current["last_color"] = tuple(ch["color"])

        if current is not None:
            built = _finalize(current, run_idx)
            if built is not None:
                runs.append(built)

        return runs

    def _build_paragraphs(
        self,
        page_num: int,
        runs: list[EditableSpan],
    ) -> list[EditableParagraph]:
        if not runs:
            return []

        by_block: dict[int, list[EditableSpan]] = {}
        for run in runs:
            by_block.setdefault(run.block_idx, []).append(run)

        paragraphs: list[EditableParagraph] = []
        for block_idx in sorted(by_block.keys()):
            block_runs = sorted(
                by_block[block_idx],
                key=lambda r: (r.line_idx, r.span_idx),
            )
            if not block_runs:
                continue

            line_map: dict[int, list[EditableSpan]] = {}
            for r in block_runs:
                line_map.setdefault(r.line_idx, []).append(r)

            line_texts: list[str] = []
            for line_idx in sorted(line_map.keys()):
                parts = [seg.text.strip() for seg in sorted(line_map[line_idx], key=lambda s: s.span_idx) if seg.text.strip()]
                if parts:
                    line_texts.append(" ".join(parts))
            para_text = "\n".join(line_texts).strip()
            if not para_text:
                continue

            bbox = fitz.Rect(block_runs[0].bbox)
            font_counter = Counter()
            color_counter = Counter()
            size_sum = 0.0
            size_count = 0
            for run in block_runs[1:]:
                bbox.include_rect(run.bbox)
            for run in block_runs:
                font_counter[run.font] += max(1, len((run.text or "").strip()))
                color_counter[tuple(run.color)] += max(1, len((run.text or "").strip()))
                size_sum += float(run.size)
                size_count += 1

            dominant_font = font_counter.most_common(1)[0][0] if font_counter else block_runs[0].font
            dominant_color = color_counter.most_common(1)[0][0] if color_counter else tuple(block_runs[0].color)
            avg_size = size_sum / max(1, size_count)

            first = block_runs[0]
            para_id = f"pg{page_num}_b{block_idx}_p0"
            paragraphs.append(
                EditableParagraph(
                    paragraph_id=para_id,
                    page_idx=page_num,
                    block_idx=block_idx,
                    bbox=bbox,
                    text=para_text,
                    font=dominant_font,
                    size=float(avg_size),
                    color=tuple(dominant_color),
                    dir_vec=(float(first.dir_vec[0]), float(first.dir_vec[1])),
                    rotation=int(first.rotation),
                    run_ids=[r.span_id for r in block_runs],
                    line_start=min(line_map.keys()),
                    line_end=max(line_map.keys()),
                )
            )

        return paragraphs

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
