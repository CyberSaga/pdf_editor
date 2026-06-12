from __future__ import annotations

from typing import TYPE_CHECKING

import fitz

from .base import ToolExtension

if TYPE_CHECKING:
    from model.pdf_model import PDFModel


class SearchTool(ToolExtension):
    def __init__(self, model: PDFModel) -> None:
        self._model = model

    @staticmethod
    def search_page_in_doc(doc: fitz.Document, page_num: int, query: str) -> list[tuple[int, str, object]]:
        """Search a single 1-based page; returns (page_num, context, rect) hits.

        Bounds-checked: out-of-range pages (or no open document) return an
        empty list instead of raising, so a background worker can iterate
        pages without re-validating against a document that may have changed.
        """
        results: list[tuple[int, str, object]] = []
        if not doc or page_num < 1 or page_num > len(doc):
            return results
        page = doc[page_num - 1]
        for inst in page.search_for(query):
            context_rect = inst + (-10, -5, 10, 5)
            context = page.get_text("text", clip=context_rect, sort=True).strip().replace("\n", " ")
            results.append((page_num, context, inst))
        return results

    def search_page(self, page_num: int, query: str) -> list[tuple[int, str, object]]:
        return self.search_page_in_doc(self._model.doc, page_num, query)

    def search_text(self, query: str):
        results = []
        if not self._model.doc:
            return results
        for i in range(len(self._model.doc)):
            results.extend(self.search_page(i + 1, query))
        return results
