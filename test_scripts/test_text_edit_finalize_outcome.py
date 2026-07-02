# test_scripts/test_text_edit_finalize_outcome.py
from __future__ import annotations
from unittest.mock import MagicMock
from view.text_editing import (
    TextEditOutcome,
    finalize_text_edit_impl,
    TextEditReason,
)


def _make_session():
    s = MagicMock()
    s.intent = "edit"
    s.edit_page = 0
    s.origin_page = 0
    s.original_rect = MagicMock()
    s.current_rect = MagicMock()
    s.original_text = "hello"
    s.current_font = "helv"
    s.current_size = 12.0
    s.original_color = (0.0, 0.0, 0.0)
    s.target_span_id = "span-1"
    s.target_mode = "run"
    return s


def test_failed_outcome_exists():
    assert hasattr(TextEditOutcome, "FAILED"), (
        "TextEditOutcome.FAILED missing — finalize cannot signal commit failure"
    )


def test_finalize_returns_failed_when_emit_raises(qapp):
    session = _make_session()
    delta = MagicMock()
    delta.page_changed = False
    view = MagicMock()
    view.sig_edit_text.emit.side_effect = RuntimeError("bus error")
    result = finalize_text_edit_impl(
        view=view,
        session=session,
        delta=delta,
        reason=TextEditReason.USER_COMMIT,
    )
    assert result.outcome is TextEditOutcome.FAILED, (
        f"Expected FAILED, got {result.outcome!r}; failed emit must not report COMMITTED"
    )
