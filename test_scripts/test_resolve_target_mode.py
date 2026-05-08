# test_scripts/test_resolve_target_mode.py
from __future__ import annotations
import logging
from unittest.mock import MagicMock
import fitz
from model.pdf_model import PDFModel


def _model():
    m = PDFModel.__new__(PDFModel)
    m.text_target_mode = "run"
    m.block_manager = MagicMock(); m.block_manager.find_by_rect.return_value = None
    m.doc = MagicMock()
    return m


def test_run_without_span_id_logs_warning(caplog):
    m = _model()
    with caplog.at_level(logging.WARNING, logger="model.pdf_model"):
        m._resolve_effective_target_mode(
            target_mode="run", target_span_id=None, new_rect=None,
            page_idx=0, rect=fitz.Rect(0, 0, 100, 20),
            original_text="some long paragraph text that goes on and on",
        )
    assert any(
        ("auto-promoted" in r.message or "paragraph" in r.message)
        for r in caplog.records if r.levelno >= logging.WARNING
    ), "run→paragraph promotion must log at WARNING, not DEBUG"


def test_run_with_span_id_does_not_promote():
    result = _model()._resolve_effective_target_mode(
        target_mode="run", target_span_id="span-42", new_rect=None,
        page_idx=0, rect=fitz.Rect(0, 0, 100, 20), original_text="hello",
    )
    assert result == "run", f"Expected 'run' with span_id, got {result!r}"
