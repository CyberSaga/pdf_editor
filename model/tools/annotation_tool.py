from __future__ import annotations

import json
import logging
import math
import uuid
from typing import TYPE_CHECKING

import fitz

from .base import ToolExtension

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)


class AnnotationTool(ToolExtension):
    _ANNOT_FREE_TEXT = 2
    _ANNOT_HIGHLIGHT = 8
    _ANNOT_SQUARE = 4
    _ANNOT_CIRCLE = 5
    _ANNOT_UNDERLINE = 9
    _ANNOT_STRIKEOUT = 10
    _ANNOT_REDACT = 12

    def __init__(self, model: PDFModel) -> None:
        self._model = model

    def _require_page(self, page_num: int) -> fitz.Page:
        """Return the fitz.Page for *page_num* (1-based) or raise ValueError.

        Guards both the no-doc case and out-of-range page numbers, preventing
        page 0 from silently resolving to doc[-1] (last page).
        """
        if not self._model.doc:
            raise ValueError("沒有開啟的 PDF 文件")
        if page_num < 1 or page_num > len(self._model.doc):
            raise ValueError(f"無效的頁碼: {page_num}")
        return self._model.doc[page_num - 1]

    def add_highlight(self, page_num: int, rect: fitz.Rect, color: tuple[float, float, float, float]) -> None:
        page = self._require_page(page_num)
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=color[:3], fill=color[:3])
        annot.set_opacity(color[3])
        annot.update()
        logger.debug("新增螢光筆: 頁面 %s, 矩形 %s, 顏色 %s", page_num, rect, color)

    def _add_text_markup(
        self,
        kind: str,
        page_num: int,
        rect: fitz.Rect,
        color: tuple[float, float, float, float],
    ) -> None:
        normalized = self._normalize_color(color, name="color")
        page = self._require_page(page_num)
        if kind == "underline":
            annot = page.add_underline_annot(rect)
        elif kind == "strikeout":
            annot = page.add_strikeout_annot(rect)
        else:  # pragma: no cover - private callers use fixed literals
            raise ValueError(f"unsupported markup kind: {kind}")
        annot.set_colors(stroke=normalized[:3])
        annot.set_opacity(normalized[3])
        annot.update()
        logger.debug("新增%s: 頁面 %s, 矩形 %s, 顏色 %s", kind, page_num, rect, normalized)

    def add_underline(
        self,
        page_num: int,
        rect: fitz.Rect,
        color: tuple[float, float, float, float],
    ) -> None:
        self._add_text_markup("underline", page_num, rect, color)

    def add_strikeout(
        self,
        page_num: int,
        rect: fitz.Rect,
        color: tuple[float, float, float, float],
    ) -> None:
        self._add_text_markup("strikeout", page_num, rect, color)

    def get_text_bounds(self, page_num: int, rough_rect: fitz.Rect) -> fitz.Rect:
        precise_rect = self._model.get_text_selection_bounds(page_num, rough_rect)
        if precise_rect is None:
            logger.debug("頁面 %s 在 %s 無文字，返回原矩形", page_num, rough_rect)
            return rough_rect
        logger.debug("頁面 %s 在 %s 精準矩形 %s", page_num, rough_rect, precise_rect)
        return precise_rect

    @staticmethod
    def _normalize_color(value: object, *, name: str) -> tuple[float, float, float, float]:
        if not isinstance(value, (tuple, list)) or len(value) not in (3, 4):
            raise TypeError(f"{name} must contain three or four numeric channels")
        try:
            channels = tuple(float(channel) for channel in value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"{name} channels must be numeric") from exc
        if any(not math.isfinite(channel) or channel < 0.0 or channel > 1.0 for channel in channels):
            raise ValueError(f"{name} channels must be within 0..1")
        if len(channels) == 3:
            return channels[0], channels[1], channels[2], 1.0
        return channels[0], channels[1], channels[2], channels[3]

    def add_rect(
        self,
        page_num: int,
        rect: fitz.Rect,
        color: tuple[float, float, float, float] | None = None,
        fill: bool | None = None,
        *,
        stroke_color: tuple[float, float, float, float] | None = None,
        fill_color: tuple[float, float, float, float] | None = None,
        border_width: float | None = None,
    ) -> None:
        """Add a rectangle with independent stroke/fill appearance.

        ``color``/``fill`` remain accepted for older callers; new callers pass
        ``stroke_color``/``fill_color`` and an explicit border width.
        """
        stroke = self._normalize_color(
            stroke_color if stroke_color is not None else color,
            name="stroke_color",
        )
        if fill_color is not None:
            normalized_fill = self._normalize_color(fill_color, name="fill_color")
        elif fill:
            normalized_fill = stroke
        else:
            normalized_fill = None
        explicit_border_width = border_width is not None
        if border_width is None:
            width = 0.0 if fill is True and stroke_color is None else 5.0 if fill is False else 1.0
        else:
            if isinstance(border_width, bool):
                raise TypeError("border_width must be numeric")
            try:
                width = float(border_width)
            except (TypeError, ValueError) as exc:
                raise TypeError("border_width must be numeric") from exc
        if (
            not math.isfinite(width)
            or width > 20.0
            or (explicit_border_width and width <= 0.0)
            or (not explicit_border_width and width < 0.0)
        ):
            raise ValueError("border_width must be within 0..20")

        page = self._require_page(page_num)
        annot = page.add_rect_annot(rect)
        annot.set_colors(
            stroke=stroke[:3],
            fill=normalized_fill[:3] if normalized_fill is not None else None,
        )
        annot.set_border(width=width)
        annot.set_opacity(stroke[3])
        payload = {
            "version": 1,
            "kind": "rect",
            "object_id": str(uuid.uuid4()),
            "page_num": int(page_num),
            "rect": [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
            "fill": normalized_fill is not None,
            "stroke_color": list(stroke),
            "fill_color": list(normalized_fill) if normalized_fill is not None else None,
            "border_width": width,
        }
        annot.set_info(
            content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            subject="pdf_editor_rect_object",
        )
        annot.update()
        logger.debug(
            "新增矩形: 頁面 %s, 矩形 %s, 線色=%s, 填色=%s, 線寬=%s",
            page_num,
            rect,
            stroke,
            normalized_fill,
            width,
        )

    def add_annotation(self, page_num: int, point: fitz.Point, text: str) -> int:
        page = self._require_page(page_num)
        annot = page.add_text_annot(point, str(text), icon="Note")
        annot.update()
        logger.debug("新增文字註解: 頁面 %s, 矩形 %s, xref: %s", page_num, annot.rect, annot.xref)
        return annot.xref

    def _find_annotation(self, xref: int) -> tuple[fitz.Page, fitz.Annot] | None:
        if not self._model.doc or not isinstance(xref, int) or xref <= 0:
            return None
        for page in self._model.doc:
            annot = page.first_annot
            while annot is not None:
                if annot.xref == xref:
                    return page, annot
                annot = annot.next
        return None

    def update_annotation(self, xref: int, text: str) -> bool:
        found = self._find_annotation(xref)
        if found is None:
            return False
        _page, annot = found
        if annot.type[1] != "Text":
            return False
        annot.set_info(content=str(text))
        annot.update()
        return True

    def move_annotation(self, xref: int, rect: fitz.Rect) -> bool:
        found = self._find_annotation(xref)
        if found is None:
            return False
        _page, annot = found
        if annot.type[1] != "Text":
            return False
        target = fitz.Rect(rect)
        if target.is_empty or any(
            not math.isfinite(value)
            for value in (target.x0, target.y0, target.x1, target.y1)
        ):
            raise ValueError("annotation rect must be finite and non-empty")
        annot.set_rect(target)
        annot.update()
        return True

    def delete_annotation(self, xref: int) -> bool:
        found = self._find_annotation(xref)
        if found is None:
            return False
        page, annot = found
        if annot.type[1] != "Text":
            return False
        page.delete_annot(annot)
        return True

    def get_all_annotations(self) -> list[dict]:
        results: list[dict] = []
        if not self._model.doc:
            return results

        for page in self._model.doc:
            for annot in page.annots():
                type_name = annot.type[1]
                if type_name not in {"Text", "FreeText"}:
                    continue
                results.append(
                    {
                        "xref": annot.xref,
                        "page_num": page.number,
                        "rect": fitz.Rect(annot.rect),
                        "text": annot.info.get("content", ""),
                        "kind": "note" if type_name == "Text" else "freetext",
                        "read_only": type_name != "Text",
                    }
                )

        logger.debug("找到 %s 個文字註解", len(results))
        return results

    def toggle_annotations_visibility(self, visible: bool) -> None:
        if not self._model.doc:
            return

        for page in self._model.doc:
            for annot in page.annots():
                if annot.type[1] in {"Text", "FreeText"}:
                    current_flags = annot.flags
                    if visible:
                        new_flags = current_flags & ~fitz.ANNOT_FLAG_HIDDEN
                    else:
                        new_flags = current_flags | fitz.ANNOT_FLAG_HIDDEN
                    annot.set_flags(new_flags)
                    annot.update()

        logger.debug("註解可見性設定為: %s", visible)

    def _save_overlapping_annots(self, page: fitz.Page, redact_rect: fitz.Rect) -> list:
        saved: list[dict] = []
        try:
            annot_iter = list(page.annots())
        except Exception as exc:
            logger.warning("_save_overlapping_annots: page.annots() 失敗（壞損 annot xref？）: %s", exc)
            return saved

        for annot in annot_iter:
            try:
                if annot is None:
                    continue
                if annot.type[0] == self._ANNOT_REDACT:
                    continue
                if not fitz.Rect(annot.rect).intersects(redact_rect):
                    continue
                entry = {
                    "type_code": annot.type[0],
                    "type_name": annot.type[1],
                    "rect": fitz.Rect(annot.rect),
                    "info": dict(annot.info),
                    "colors": annot.colors,
                    "opacity": annot.opacity,
                    "border": annot.border,
                    "vertices": annot.vertices,
                }
                saved.append(entry)
                logger.debug("_save_overlapping_annots: 儲存 %s @ %s", annot.type[1], annot.rect)
            except Exception as exc:
                logger.warning("_save_overlapping_annots: 跳過損壞 annot: %s", exc)
                continue
        return saved

    def _restore_annots(self, page: fitz.Page, saved: list) -> None:
        for a in saved:
            tc = a["type_code"]
            rect = a["rect"]
            info = a["info"]
            colors = a["colors"] or {}
            stroke = colors.get("stroke") or (0, 0, 0)
            fill = colors.get("fill")

            try:
                if tc == self._ANNOT_FREE_TEXT:
                    new_a = page.add_freetext_annot(
                        rect,
                        info.get("content", ""),
                        fontname="helv",
                        fontsize=10.5,
                        text_color=stroke if stroke else (0, 0, 0),
                        fill_color=fill if fill else (1, 1, 0.8),
                        rotate=page.rotation,
                    )
                    new_a.update()

                elif tc == self._ANNOT_HIGHLIGHT:
                    verts = a.get("vertices")
                    if verts:
                        new_a = page.add_highlight_annot(quads=verts)
                    else:
                        new_a = page.add_highlight_annot(rect)
                    if stroke:
                        new_a.set_colors(stroke=stroke)
                    if a["opacity"] is not None:
                        new_a.set_opacity(a["opacity"])
                    new_a.update()

                elif tc == self._ANNOT_SQUARE:
                    new_a = page.add_rect_annot(rect)
                    new_a.set_colors(stroke=stroke, fill=fill)
                    if a["opacity"] is not None:
                        new_a.set_opacity(a["opacity"])
                    new_a.update()

                elif tc == self._ANNOT_CIRCLE:
                    new_a = page.add_circle_annot(rect)
                    new_a.set_colors(stroke=stroke, fill=fill)
                    if a["opacity"] is not None:
                        new_a.set_opacity(a["opacity"])
                    new_a.update()

                elif tc in (self._ANNOT_UNDERLINE, self._ANNOT_STRIKEOUT):
                    verts = a.get("vertices")
                    if tc == self._ANNOT_UNDERLINE:
                        new_a = page.add_underline_annot(quads=verts) if verts else page.add_underline_annot(rect)
                    else:
                        new_a = page.add_strikeout_annot(quads=verts) if verts else page.add_strikeout_annot(rect)
                    if stroke:
                        new_a.set_colors(stroke=stroke)
                    if a["opacity"] is not None:
                        new_a.set_opacity(a["opacity"])
                    new_a.update()

                else:
                    logger.warning("_restore_annots: 不支援的 annot 類型 %s (%s)，跳過還原", a["type_name"], tc)
                    continue

                logger.debug("_restore_annots: 已還原 %s @ %s", a["type_name"], rect)

            except Exception as exc:
                logger.warning("_restore_annots: 還原 %s 失敗: %s", a["type_name"], exc)
