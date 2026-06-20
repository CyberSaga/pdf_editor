from __future__ import annotations

from pathlib import Path

import pytest

from scripts.fusion_transcripts import (
    TranscriptError,
    changed_transcripts,
    extract_response,
    snapshot_transcripts,
)


FIXTURES = Path(__file__).parent / "fixtures" / "antigravity"


def _transcript(root: Path, conversation: str) -> Path:
    return root / conversation / ".system_generated" / "logs" / "transcript_full.jsonl"


def test_extract_response_selects_completed_model_answer_after_matching_input(tmp_path: Path):
    path = _transcript(tmp_path, "conversation-a")
    path.parent.mkdir(parents=True)
    path.write_text((FIXTURES / "transcript-success.jsonl").read_text(encoding="utf-8"), encoding="utf-8")

    extracted = extract_response([path], "call-success")

    assert extracted.text == "Evidence-grounded Antigravity answer"
    assert extracted.path == path


def test_extract_response_uses_last_completed_model_answer(tmp_path: Path):
    path = _transcript(tmp_path, "conversation-a")
    path.parent.mkdir(parents=True)
    path.write_text(
        '\n'.join(
            [
                '{"step_index":0,"source":"USER_EXPLICIT","type":"USER_INPUT","status":"DONE","content":"[FUSION_CALL_ID:call-last]"}',
                '{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","status":"DONE","content":"draft"}',
                '{"step_index":2,"source":"MODEL","type":"PLANNER_RESPONSE","status":"DONE","content":"final"}',
            ]
        ),
        encoding="utf-8",
    )

    assert extract_response([path], "call-last").text == "final"


def test_extract_response_rejects_matching_multiple_conversations(tmp_path: Path):
    paths = []
    for name in ("a", "b"):
        path = _transcript(tmp_path, name)
        path.parent.mkdir(parents=True)
        path.write_text(
            (FIXTURES / "transcript-ambiguous.jsonl").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        paths.append(path)

    with pytest.raises(TranscriptError, match="exactly one"):
        extract_response(paths, "call-duplicate")


def test_extract_response_rejects_incomplete_answer(tmp_path: Path):
    path = _transcript(tmp_path, "conversation-a")
    path.parent.mkdir(parents=True)
    path.write_text(
        (FIXTURES / "transcript-incomplete.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(TranscriptError, match="completed model response"):
        extract_response([path], "call-incomplete")


def test_extract_response_rejects_malformed_jsonl(tmp_path: Path):
    path = _transcript(tmp_path, "conversation-a")
    path.parent.mkdir(parents=True)
    path.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(TranscriptError, match="Malformed JSONL"):
        extract_response([path], "call")


def test_changed_transcripts_returns_only_new_or_modified_files(tmp_path: Path):
    unchanged = _transcript(tmp_path, "unchanged")
    changed = _transcript(tmp_path, "changed")
    for path in (unchanged, changed):
        path.parent.mkdir(parents=True)
        path.write_text("{}\n", encoding="utf-8")
    before = snapshot_transcripts(tmp_path)

    changed.write_text("{}\n{}\n", encoding="utf-8")
    added = _transcript(tmp_path, "added")
    added.parent.mkdir(parents=True)
    added.write_text("{}\n", encoding="utf-8")

    assert changed_transcripts(before, tmp_path) == sorted([changed, added])
