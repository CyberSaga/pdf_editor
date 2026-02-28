from __future__ import annotations

from typing import TYPE_CHECKING

import fitz

from .base import ToolExtension

if TYPE_CHECKING:
    from model.pdf_model import PDFModel


class SearchTool(ToolExtension):
    def __init__(self, model: "PDFModel") -> None:
        self._model = model

    def search_text(self, query: str):
        results = []
        if not self._model.doc:
            return results
        for i in range(len(self._model.doc)):
            page = self._model.doc[i]
            found_rects = page.search_for(query)
            for inst in found_rects:
                context_rect = inst + (-10, -5, 10, 5)
                context = page.get_text("text", clip=context_rect, sort=True).strip().replace("\n", " ")
                results.append((i + 1, context, inst))
        return results
