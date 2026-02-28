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


class WatermarkTool(ToolExtension):
    WATERMARK_EMBED_NAME = "__pdf_editor_watermarks"

    def __init__(self, model: "PDFModel") -> None:
        self._model = model
        self._watermarks_by_session: dict[str, list[dict]] = {}
        self._modified_sessions: set[str] = set()

    def on_session_open(self, session_id: str, doc: fitz.Document) -> None:
        self._watermarks_by_session[session_id] = self._load_watermarks_from_doc(doc)
        self._modified_sessions.discard(session_id)

    def on_session_close(self, session_id: str) -> None:
        self._watermarks_by_session.pop(session_id, None)
        self._modified_sessions.discard(session_id)

    def on_session_saved(self, session_id: str) -> None:
        self._modified_sessions.discard(session_id)

    def has_unsaved_changes(self, session_id: str) -> bool:
        return session_id in self._modified_sessions

    def needs_page_overlay(self, session_id: str, page_num: int, purpose: str) -> bool:
        _ = purpose
        return bool(self._get_watermarks_for_page(session_id, page_num))

    def apply_page_overlay(self, session_id: str, page_num: int, page: fitz.Page, purpose: str) -> None:
        _ = purpose
        watermarks = self._get_watermarks_for_page(session_id, page_num)
        self._apply_watermarks_to_page(page, watermarks)

    def prepare_doc_for_save(self, session_id: str, doc: fitz.Document) -> fitz.Document | None:
        watermarks = self._watermarks_by_session.get(session_id, [])
        if not watermarks:
            self._write_watermarks_embed(doc, [])
            return None

        tmp_doc = fitz.open()
        tmp_doc.insert_pdf(doc)
        for wm in watermarks:
            for page_num in wm.get("pages", []):
                if 1 <= page_num <= len(tmp_doc):
                    self._apply_watermarks_to_page(tmp_doc[page_num - 1], [wm])
        self._write_watermarks_embed(tmp_doc, watermarks)
        return tmp_doc

    def _active_session_id(self) -> str:
        sid = self._model.get_active_session_id()
        if not sid:
            raise RuntimeError("沒有作用中的 session")
        return sid

    def _active_watermark_list(self) -> list[dict]:
        sid = self._active_session_id()
        return self._watermarks_by_session.setdefault(sid, [])

    def _mark_modified(self, session_id: str) -> None:
        self._modified_sessions.add(session_id)

    def add_watermark(
        self,
        pages: list[int],
        text: str,
        angle: float = 45,
        opacity: float = 0.4,
        font_size: int = 48,
        color: tuple[float, float, float] = (0.7, 0.7, 0.7),
        font: str = "helv",
        offset_x: float = 0,
        offset_y: float = 0,
        line_spacing: float = 1.3,
    ) -> str:
        if not self._model.doc or not text.strip():
            raise ValueError("無效的文件或浮水印文字")

        sid = self._active_session_id()
        wm_id = str(uuid.uuid4())
        wm = {
            "id": wm_id,
            "pages": [p for p in pages if 1 <= p <= len(self._model.doc)],
            "text": text.strip(),
            "angle": angle,
            "opacity": opacity,
            "font_size": font_size,
            "color": color,
            "font": font,
            "offset_x": offset_x,
            "offset_y": offset_y,
            "line_spacing": max(0.8, min(3.0, line_spacing)),
        }
        self._active_watermark_list().append(wm)
        self._mark_modified(sid)
        logger.debug("新增浮水印: %s, 頁面 %s", wm_id, wm["pages"])
        return wm_id

    def get_watermarks(self) -> list[dict]:
        sid = self._model.get_active_session_id()
        if not sid:
            return []
        return list(self._watermarks_by_session.get(sid, []))

    def remove_watermark(self, watermark_id: str) -> bool:
        sid = self._active_session_id()
        watermarks = self._active_watermark_list()
        for i, wm in enumerate(watermarks):
            if wm.get("id") == watermark_id:
                watermarks.pop(i)
                self._mark_modified(sid)
                logger.debug("已移除浮水印: %s", watermark_id)
                return True
        return False

    def update_watermark(
        self,
        watermark_id: str,
        text: str | None = None,
        pages: list[int] | None = None,
        angle: float | None = None,
        opacity: float | None = None,
        font_size: int | None = None,
        color: tuple[float, float, float] | None = None,
        font: str | None = None,
        offset_x: float | None = None,
        offset_y: float | None = None,
        line_spacing: float | None = None,
    ) -> bool:
        sid = self._active_session_id()
        watermarks = self._active_watermark_list()
        for wm in watermarks:
            if wm.get("id") != watermark_id:
                continue
            if text is not None:
                wm["text"] = text.strip()
            if pages is not None:
                wm["pages"] = [p for p in pages if 1 <= p <= len(self._model.doc)]
            if angle is not None:
                wm["angle"] = angle
            if opacity is not None:
                wm["opacity"] = max(0.0, min(1.0, opacity))
            if font_size is not None:
                wm["font_size"] = font_size
            if color is not None:
                wm["color"] = color
            if font is not None:
                wm["font"] = font
            if offset_x is not None:
                wm["offset_x"] = offset_x
            if offset_y is not None:
                wm["offset_y"] = offset_y
            if line_spacing is not None:
                wm["line_spacing"] = max(0.8, min(3.0, line_spacing))
            self._mark_modified(sid)
            logger.debug("已更新浮水印: %s", watermark_id)
            return True
        return False

    def _load_watermarks_from_doc(self, doc: fitz.Document) -> list[dict]:
        loaded: list[dict] = []
        try:
            names = doc.embfile_names()
            if not names or self.WATERMARK_EMBED_NAME not in names:
                return loaded
            raw = doc.embfile_get(self.WATERMARK_EMBED_NAME)
            if not raw:
                return loaded
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, list):
                return loaded
            for wm in data:
                if not isinstance(wm, dict) or "id" not in wm or "pages" not in wm:
                    continue
                if "color" in wm and isinstance(wm["color"], list):
                    wm["color"] = tuple(wm["color"])
                loaded.append(wm)
            logger.debug("已從 PDF 還原 %s 個浮水印", len(loaded))
        except Exception as exc:
            logger.warning("還原浮水印元數據失敗: %s", exc)
        return loaded

    def _write_watermarks_embed(self, doc: fitz.Document, watermarks: list[dict]) -> None:
        payload = json.dumps(watermarks, ensure_ascii=False).encode("utf-8")
        try:
            names = doc.embfile_names()
            if names and self.WATERMARK_EMBED_NAME in names:
                doc.embfile_del(self.WATERMARK_EMBED_NAME)
        except Exception as exc:
            logger.debug("刪除舊浮水印附件時忽略: %s", exc)

        try:
            doc.embfile_add(self.WATERMARK_EMBED_NAME, payload)
            logger.debug("已寫入浮水印元數據（%s 筆）", len(watermarks))
        except Exception as exc:
            logger.warning("寫入浮水印元數據失敗: %s", exc)

    def _get_watermarks_for_page(self, session_id: str, page_num: int) -> list[dict]:
        watermarks = self._watermarks_by_session.get(session_id, [])
        return [wm for wm in watermarks if page_num in wm.get("pages", [])]

    def _needs_cjk_font(self, text: str) -> bool:
        import re

        return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))

    def _get_watermark_font(self, font_name: str, text: str) -> str:
        non_cjk_fonts = ("helv", "cour", "Helvetica", "Courier")
        if self._needs_cjk_font(text) and font_name in non_cjk_fonts:
            return "china-ts"
        return font_name

    def _apply_watermarks_to_page(self, page: fitz.Page, watermarks: list[dict]) -> None:
        if not watermarks:
            return
        page_rect = page.rect
        cx = page_rect.width / 2
        cy = page_rect.height / 2

        for wm in watermarks:
            text = wm.get("text", "")
            angle = wm.get("angle", 0)
            opacity = max(0.0, min(1.0, wm.get("opacity", 0.5)))
            font_size = wm.get("font_size", 48)
            color = wm.get("color", (0.7, 0.7, 0.7))
            font_name = wm.get("font", "helv")
            offset_x = wm.get("offset_x", 0)
            offset_y = wm.get("offset_y", 0)
            line_spacing = wm.get("line_spacing", 1.3)

            font_name = self._get_watermark_font(font_name, text)
            center_x = cx + offset_x
            center_y = cy + offset_y
            center = fitz.Point(center_x, center_y)

            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if not lines:
                continue

            try:
                font = fitz.Font(font_name)
            except Exception:
                font = fitz.Font("china-ts" if self._needs_cjk_font(text) else "helv")

            line_height = font_size * line_spacing
            total_height = line_height * len(lines)
            rad = math.radians(-angle)
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)

            for i, line in enumerate(lines):
                if not line:
                    continue
                line_len = font.text_length(line, fontsize=font_size)
                dx = -line_len / 2
                dy = -total_height / 2 + i * line_height + font_size * 0.35
                px = center_x + dx * cos_a - dy * sin_a
                py = center_y + dx * sin_a + dy * cos_a
                pt = fitz.Point(px, py)
                mat = fitz.Matrix(cos_a, -sin_a, sin_a, cos_a, 0, 0)
                page.insert_text(
                    pt,
                    line,
                    fontsize=font_size,
                    fontname=font_name,
                    color=color[:3] if len(color) >= 3 else (0.7, 0.7, 0.7),
                    morph=(center, mat),
                    fill_opacity=opacity,
                    stroke_opacity=opacity,
                )
