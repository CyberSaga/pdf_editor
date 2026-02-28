from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

import fitz

from .annotation_tool import AnnotationTool
from .ocr_tool import OcrTool
from .search_tool import SearchTool
from .watermark_tool import WatermarkTool

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)


class ToolManager:
    def __init__(self, model: "PDFModel") -> None:
        self._model = model

        self.annotation = AnnotationTool(model)
        self.watermark = WatermarkTool(model)
        self.search = SearchTool(model)
        self.ocr = OcrTool(model)

        self._extensions = [
            self.annotation,
            self.watermark,
            self.search,
            self.ocr,
        ]

    def on_session_open(self, session_id: str, doc: fitz.Document) -> None:
        for ext in self._extensions:
            ext.on_session_open(session_id, doc)

    def on_session_close(self, session_id: str) -> None:
        for ext in self._extensions:
            ext.on_session_close(session_id)

    def on_session_saved(self, session_id: str) -> None:
        for ext in self._extensions:
            ext.on_session_saved(session_id)

    def has_unsaved_changes(self, session_id: str) -> bool:
        return any(ext.has_unsaved_changes(session_id) for ext in self._extensions)

    def _active_session_id(self) -> str:
        sid = self._model.get_active_session_id()
        if not sid:
            raise RuntimeError("沒有作用中的 session")
        return sid

    def render_page_pixmap(self, page_num: int, scale: float = 1.0, annots: bool = False, purpose: str = "view") -> fitz.Pixmap:
        if not self._model.doc:
            raise RuntimeError("沒有開啟的 PDF 文件")

        session_id = self._active_session_id()
        page = self._model.doc[page_num - 1]
        needs_overlay = any(ext.needs_page_overlay(session_id, page_num, purpose) for ext in self._extensions)
        matrix = fitz.Matrix(scale, scale)

        if not needs_overlay:
            return page.get_pixmap(matrix=matrix, annots=annots)

        tmp_doc = fitz.open()
        try:
            tmp_doc.insert_pdf(self._model.doc, from_page=page_num - 1, to_page=page_num - 1)
            tmp_page = tmp_doc[0]
            for ext in self._extensions:
                if ext.needs_page_overlay(session_id, page_num, purpose):
                    ext.apply_page_overlay(session_id, page_num, tmp_page, purpose)
            return tmp_page.get_pixmap(matrix=matrix, annots=annots)
        finally:
            tmp_doc.close()

    def build_print_snapshot(self) -> bytes:
        if not self._model.doc:
            raise RuntimeError("沒有開啟的 PDF 文件")

        session_id = self._active_session_id()
        page_count = len(self._model.doc)
        has_overlay = any(
            ext.needs_page_overlay(session_id, page_num + 1, "print")
            for ext in self._extensions
            for page_num in range(page_count)
        )
        if not has_overlay:
            return self._model._capture_doc_snapshot()

        tmp_doc = fitz.open()
        try:
            tmp_doc.insert_pdf(self._model.doc)
            for page_idx in range(page_count):
                page_num = page_idx + 1
                for ext in self._extensions:
                    if ext.needs_page_overlay(session_id, page_num, "print"):
                        ext.apply_page_overlay(session_id, page_num, tmp_doc[page_idx], "print")
            stream = io.BytesIO()
            tmp_doc.save(stream, garbage=0)
            return stream.getvalue()
        finally:
            tmp_doc.close()

    def prepare_doc_for_save(self, session_id: str) -> fitz.Document | None:
        doc = self._model.doc
        if doc is None:
            return None

        current = doc
        produced: fitz.Document | None = None
        for ext in self._extensions:
            next_doc = ext.prepare_doc_for_save(session_id, current)
            if next_doc is None:
                continue
            if produced is not None and produced is not next_doc:
                try:
                    produced.close()
                except Exception:
                    pass
            produced = next_doc
            current = next_doc
        return produced
