from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class OcrSpan:
    bbox: tuple[float, float, float, float]
    text: str
    confidence: float


class OcrLanguage(str, Enum):
    ENGLISH = "en"
    TRAD_CHINESE = "zh-Hant"
    SIMP_CHINESE = "zh-Hans"
    JAPANESE = "ja"

    @classmethod
    def from_code(cls, code: str) -> OcrLanguage:
        normalized = (code or "").strip()
        for member in cls:
            if member.value.lower() == normalized.lower():
                return member
        raise ValueError(f"未知的 OCR 語言代碼: {code!r}")


class OcrDevice(str, Enum):
    AUTO = "auto"
    CUDA = "cuda"
    CPU = "cpu"
    MPS = "mps"

    @classmethod
    def from_code(cls, code: str) -> OcrDevice:
        normalized = (code or "auto").strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"未知的 OCR 裝置代碼: {code!r}")


@dataclass(frozen=True)
class OcrAvailability:
    available: bool
    reason: str = ""
    install_hint: str = ""


@dataclass(frozen=True)
class OcrRequest:
    page_indices: tuple[int, ...]
    languages: tuple[str, ...]
    device: str = "auto"
    metadata: dict = field(default_factory=dict)


def parse_page_range(
    text: str,
    total_pages: int,
    default_current: int | None = None,
) -> list[int]:
    """Parse a 1-based page-range string into sorted, deduped 0-based indices.

    Empty input falls back to ``default_current`` (must be a valid 0-based index).
    The literal ``"all"`` (case-insensitive) returns every page.
    """
    if total_pages <= 0:
        raise ValueError("文件總頁數必須大於 0")

    cleaned = (text or "").strip()
    if not cleaned:
        if default_current is None:
            raise ValueError("頁碼不可為空")
        if default_current < 0 or default_current >= total_pages:
            raise ValueError(f"預設頁碼 {default_current} 超出範圍")
        return [default_current]

    if cleaned.lower() == "all":
        return list(range(total_pages))

    pages: set[int] = set()
    for raw_part in cleaned.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start_s, end_s = part.split("-", 1)
                start = int(start_s.strip())
                end = int(end_s.strip())
            except ValueError as exc:
                raise ValueError(f"無效的頁碼範圍: {part!r}") from exc
            if start > end:
                raise ValueError(f"頁碼範圍順序錯誤: {part!r}")
            if start < 1 or end > total_pages:
                raise ValueError(
                    f"頁碼範圍 {part!r} 超出文件範圍 (1..{total_pages})"
                )
            for p in range(start, end + 1):
                pages.add(p - 1)
        else:
            try:
                num = int(part)
            except ValueError as exc:
                raise ValueError(f"無效的頁碼: {part!r}") from exc
            if num < 1 or num > total_pages:
                raise ValueError(
                    f"頁碼 {num} 超出文件範圍 (1..{total_pages})"
                )
            pages.add(num - 1)
    if not pages:
        raise ValueError("未解析到任何有效頁碼")
    return sorted(pages)
