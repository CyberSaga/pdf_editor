from __future__ import annotations

from abc import ABC

import fitz


class ToolExtension(ABC):
    """Base extension contract for PDFModel tools."""

    def on_session_open(self, session_id: str, doc: fitz.Document) -> None:
        return None

    def on_session_close(self, session_id: str) -> None:
        return None

    def on_session_saved(self, session_id: str) -> None:
        return None

    def has_unsaved_changes(self, session_id: str) -> bool:
        return False

    def needs_page_overlay(self, session_id: str, page_num: int, purpose: str) -> bool:
        return False

    def apply_page_overlay(self, session_id: str, page_num: int, page: fitz.Page, purpose: str) -> None:
        return None

    def prepare_doc_for_save(self, session_id: str, doc: fitz.Document) -> fitz.Document | None:
        return None
