"""Read-only extraction of Antigravity answers from local JSONL transcripts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


class TranscriptError(ValueError):
    pass


@dataclass(frozen=True)
class TranscriptStamp:
    mtime_ns: int
    size: int


@dataclass(frozen=True)
class ExtractedResponse:
    text: str
    path: Path


TranscriptSnapshot = dict[Path, TranscriptStamp]


def _paths(root: Path) -> list[Path]:
    return sorted(root.glob("*/.system_generated/logs/transcript_full.jsonl"))


def snapshot_transcripts(root: Path) -> TranscriptSnapshot:
    snapshot: TranscriptSnapshot = {}
    for path in _paths(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[path] = TranscriptStamp(stat.st_mtime_ns, stat.st_size)
    return snapshot


def changed_transcripts(before: Mapping[Path, TranscriptStamp], root: Path) -> list[Path]:
    changed: list[Path] = []
    for path in _paths(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        current = TranscriptStamp(stat.st_mtime_ns, stat.st_size)
        if before.get(path) != current:
            changed.append(path)
    return sorted(changed)


def _records(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise TranscriptError(f"Could not read transcript {path}: {exc}") from exc
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TranscriptError(f"Malformed JSONL in {path} at line {number}") from exc
        if not isinstance(record, dict):
            raise TranscriptError(f"Malformed JSONL record in {path} at line {number}")
        records.append(record)
    return records


def extract_response(paths: Iterable[Path], call_id: str) -> ExtractedResponse:
    marker = f"[FUSION_CALL_ID:{call_id}]"
    matches: list[tuple[Path, list[dict], int]] = []
    for path in paths:
        records = _records(path)
        input_indexes = [
            int(record.get("step_index", -1))
            for record in records
            if record.get("type") == "USER_INPUT" and marker in str(record.get("content", ""))
        ]
        if input_indexes:
            matches.append((path, records, max(input_indexes)))
    if len(matches) != 1:
        raise TranscriptError(
            f"Expected exactly one Antigravity transcript for call {call_id}; found {len(matches)}"
        )
    path, records, input_index = matches[0]
    answers = [
        record
        for record in records
        if int(record.get("step_index", -1)) > input_index
        and record.get("source") == "MODEL"
        and record.get("type") == "PLANNER_RESPONSE"
        and record.get("status") == "DONE"
        and isinstance(record.get("content"), str)
        and record["content"].strip()
    ]
    if not answers:
        raise TranscriptError(f"No completed model response found for call {call_id}")
    final = max(answers, key=lambda record: int(record.get("step_index", -1)))
    return ExtractedResponse(final["content"].strip(), path)
