from __future__ import annotations

from typing import TYPE_CHECKING

from .base import ToolExtension

if TYPE_CHECKING:
    from model.pdf_model import PDFModel


class OcrTool(ToolExtension):
    def __init__(self, model: "PDFModel") -> None:
        self._model = model

    def ocr_pages(self, pages: list[int]) -> dict:
        if not self._model.doc:
            return {}
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("OCR dependencies are missing. Install pytesseract and Pillow.") from exc

        results = {}
        for page_num in pages:
            pix = self._model.doc[page_num - 1].get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text = pytesseract.image_to_string(img)
            results[page_num] = text
        return results
