from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import ToolExtension

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)


class OcrTool(ToolExtension):
    def __init__(self, model: "PDFModel") -> None:
        self._model = model

    def ocr_pages(self, pages: list[int]) -> dict:
        if not self._model.doc:
            return {}
        try:
            import pytesseract
            from PIL import Image
            from pytesseract import TesseractNotFoundError
        except ImportError as exc:
            raise RuntimeError(
                "OCR dependencies are missing. Install pytesseract and Pillow."
            ) from exc

        results = {}
        for page_num in pages:
            if page_num < 1 or page_num > len(self._model.doc):
                raise ValueError(f"Invalid OCR page number: {page_num}")

            pix = self._model.doc[page_num - 1].get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            try:
                text = pytesseract.image_to_string(img)
            except TesseractNotFoundError as exc:
                raise RuntimeError(
                    "OCR engine is missing. Install Tesseract and add it to PATH."
                ) from exc
            except Exception as exc:
                logger.exception("OCR failed on page %s", page_num)
                raise RuntimeError(f"OCR failed on page {page_num}: {exc}") from exc
            results[page_num] = text
        return results
