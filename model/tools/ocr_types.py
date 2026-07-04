"""Re-export shim: canonical module moved to utils/ocr_types.py (PR-8).

model -> utils is a legal layer direction; existing imports of
model.tools.ocr_types keep working unchanged.
"""
from __future__ import annotations

from utils.ocr_types import (  # noqa: F401
    OcrAvailability,
    OcrDevice,
    OcrLanguage,
    OcrRequest,
    OcrSpan,
    parse_page_range,
)
