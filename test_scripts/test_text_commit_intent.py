"""Red-light tests for immutable style intent and outcome plumbing (Task 5).

The model must be able to distinguish "user typed text" from "user
restyled": StyleOverrides carries only the fields the user actually
touched, and EditTextCommand stores the full CommitOutcome, preserving
intent for redo and gating external reflow on the outcome.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextCommand, EditTextResult  # noqa: E402
from model.edit_requests import EditTextRequest, StyleOverrides  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitOutcome,
    CommitStatus,
    CommitTier,
)
from view.text_editing import build_style_overrides  # noqa: E402


def test_style_overrides_empty_by_default():
    overrides = StyleOverrides()
    assert overrides.font_family is None
    assert overrides.font_size is None
    assert overrides.color is None
    assert not overrides.changed


def test_style_overrides_reports_only_touched_fields():
    overrides = StyleOverrides(font_size=14.5)
    assert overrides.changed
    assert overrides.font_family is None
    assert overrides.font_size == 14.5


def test_edit_text_request_defaults_keep_legacy_callers_valid():
    request = EditTextRequest(
        page=1,
        rect=fitz.Rect(0, 0, 10, 10),
        new_text="x",
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
    )
    assert request.style_overrides is None
    assert request.plan_token is None
    assert len(request.to_legacy_args()) == 11  # unchanged legacy tuple


def test_build_style_overrides_untouched_session_is_empty():
    overrides = build_style_overrides(
        current_font="helv",
        initial_font="Helv",  # case difference is not a user change
        current_size=12.0,
        initial_size=12.0,
    )
    assert not overrides.changed


def test_build_style_overrides_populates_only_changed_fields():
    font_only = build_style_overrides(
        current_font="cour",
        initial_font="helv",
        current_size=12.0,
        initial_size=12.0,
    )
    assert font_only.font_family == "cour"
    assert font_only.font_size is None

    size_only = build_style_overrides(
        current_font="helv",
        initial_font="helv",
        current_size=14.0,
        initial_size=12.0,
    )
    assert size_only.font_family is None
    assert size_only.font_size == 14.0


def _legacy_outcome(*, allows_reflow: bool) -> CommitOutcome:
    return CommitOutcome(
        status=CommitStatus.COMMITTED,
        tier=CommitTier.TIER2_LEGACY,
        fallback_chain=("legacy",),
        warnings=(),
        font_outcomes=(),
        verified_properties=("text_similarity",),
        degraded_reason="legacy_redact_reinsert",
        allows_external_reflow=allows_reflow,
    )


def _make_command(model, **kwargs) -> EditTextCommand:
    return EditTextCommand(
        model=model,
        page_num=1,
        rect=fitz.Rect(0, 0, 10, 10),
        new_text="new",
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text="old",
        vertical_shift_left=True,
        page_snapshot_bytes=b"snap",
        old_block_id=None,
        old_block_text="old",
        **kwargs,
    )


def test_edit_text_command_stores_commit_outcome():
    outcome = _legacy_outcome(allows_reflow=True)
    model = SimpleNamespace(
        edit_text=lambda *a, **k: EditTextResult.SUCCESS,
        last_commit_outcome=outcome,
    )
    command = _make_command(model)
    assert command.execute() is True
    assert command.outcome is outcome


def test_edit_text_command_gates_external_reflow_on_outcome():
    calls: list[str] = []

    def _reflow() -> None:
        calls.append("reflow")

    blocked = _legacy_outcome(allows_reflow=False)
    model = SimpleNamespace(
        edit_text=lambda *a, **k: EditTextResult.SUCCESS,
        last_commit_outcome=blocked,
    )
    command = _make_command(model, reflow_fn=_reflow)
    assert command.execute() is True
    assert calls == []  # outcome forbids Track A/B reflow

    allowed = _legacy_outcome(allows_reflow=True)
    model.last_commit_outcome = allowed
    command2 = _make_command(model, reflow_fn=_reflow)
    assert command2.execute() is True
    assert calls == ["reflow"]


def test_edit_text_command_preserves_intent_for_redo():
    overrides = StyleOverrides(font_family="cour")
    model = SimpleNamespace(
        edit_text=lambda *a, **k: EditTextResult.SUCCESS,
        last_commit_outcome=None,
    )
    command = _make_command(
        model, style_overrides=overrides, plan_token="tok-1"
    )
    assert command.execute() is True
    assert command.style_overrides is overrides
    assert command.plan_token == "tok-1"
