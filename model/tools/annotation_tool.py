from __future__ import annotations

import logging
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

    def __init__(self, model: "PDFModel") -> None:
        self._model = model

    def add_highlight(self, page_num: int, rect: fitz.Rect, color: tuple[float, float, float, float]) -> None:
        page = self._model.doc[page_num - 1]
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=color[:3], fill=color[:3])
        annot.set_opacity(color[3])
        annot.update()
        logger.debug("新增螢光筆: 頁面 %s, 矩形 %s, 顏色 %s", page_num, rect, color)

    def get_text_bounds(self, page_num: int, rough_rect: fitz.Rect) -> fitz.Rect:
        page = self._model.doc[page_num - 1]
        words = page.get_text("words", clip=rough_rect)
        if not words:
            logger.debug("頁面 %s 在 %s 無文字，返回原矩形", page_num, rough_rect)
            return rough_rect
        x0 = min(word[0] for word in words)
        y0 = min(word[1] for word in words)
        x1 = max(word[2] for word in words)
        y1 = max(word[3] for word in words)
        precise_rect = fitz.Rect(x0, y0, x1, y1)
        logger.debug("頁面 %s 在 %s 精準矩形 %s", page_num, rough_rect, precise_rect)
        return precise_rect

    def add_rect(self, page_num: int, rect: fitz.Rect, color: tuple[float, float, float, float], fill: bool) -> None:
        page = self._model.doc[page_num - 1]
        annot = page.add_rect_annot(rect)
        annot.set_colors(stroke=color[:3], fill=color[:3] if fill else None)
        annot.set_border(width=5 if not fill else 0)
        annot.set_opacity(color[3])
        annot.update()
        logger.debug("新增矩形: 頁面 %s, 矩形 %s, 顏色 %s, 填滿=%s", page_num, rect, color, fill)

    def add_annotation(self, page_num: int, point: fitz.Point, text: str) -> int:
        if not self._model.doc or page_num < 1 or page_num > len(self._model.doc):
            raise ValueError("無效的頁碼")

        page = self._model.doc[page_num - 1]
        fixed_width = 200
        font_size = 10.5
        rect = fitz.Rect(point.x, point.y, point.x + fixed_width, point.y + 50)

        annot = page.add_freetext_annot(
            rect,
            text,
            fontsize=font_size,
            fontname="helv",
            text_color=(0, 0, 0),
            fill_color=(1, 1, 0.8),
            rotate=page.rotation,
        )
        annot.update()
        logger.debug("新增註解: 頁面 %s, 最終矩形 %s, xref: %s", page_num, annot.rect, annot.xref)
        return annot.xref

    def get_all_annotations(self) -> list[dict]:
        results = []
        if not self._model.doc:
            return results

        for page in self._model.doc:
            for annot in page.annots():
                if annot.type[1] == "FreeText":
                    info = {
                        "xref": annot.xref,
                        "page_num": page.number,
                        "rect": annot.rect,
                        "text": annot.info.get("content", ""),
                    }
                    results.append(info)

        logger.debug("找到 %s 個 FreeText 註解", len(results))
        return results

    def toggle_annotations_visibility(self, visible: bool) -> None:
        if not self._model.doc:
            return

        for page in self._model.doc:
            for annot in page.annots():
                if annot.type[1] == "FreeText":
                    current_flags = annot.flags
                    if visible:
                        new_flags = current_flags & ~fitz.ANNOT_FLAG_HIDDEN
                    else:
                        new_flags = current_flags | fitz.ANNOT_FLAG_HIDDEN
                    annot.set_flags(new_flags)
                    annot.update()

        logger.debug("註解可見性設定為: %s", visible)

    def _save_overlapping_annots(self, page: fitz.Page, redact_rect: fitz.Rect) -> list:
        saved = []
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
