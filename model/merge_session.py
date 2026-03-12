from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import uuid


@dataclass
class MergeEntry:
    display_name: str
    source_kind: str
    path: str | None = None
    password: str | None = None
    locked: bool = False
    status: str = "ready"
    message: str = ""
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class MergeSessionModel:
    def __init__(self, current_label: str, current_source_id: str) -> None:
        self.entries: list[MergeEntry] = [
            MergeEntry(
                display_name=current_label,
                source_kind="current",
                path=current_source_id,
                locked=True,
            )
        ]

    def add_files(self, paths: list[str]) -> None:
        for path in paths:
            self.entries.append(
                MergeEntry(
                    display_name=Path(path).name,
                    source_kind="file",
                    path=path,
                )
            )

    def add_resolved_files(self, resolved_entries: list[dict]) -> None:
        for resolved in resolved_entries:
            path = resolved.get("path")
            self.entries.append(
                MergeEntry(
                    display_name=resolved.get("display_name") or (Path(path).name if path else "未命名"),
                    source_kind=resolved.get("source_kind", "file"),
                    path=path,
                    password=resolved.get("password"),
                )
            )

    def remove_selected(self, indexes: list[int]) -> list[MergeEntry]:
        removed: list[MergeEntry] = []
        for index in sorted(set(indexes), reverse=True):
            if not 0 <= index < len(self.entries):
                continue
            entry = self.entries[index]
            if entry.locked:
                continue
            removed.append(self.entries.pop(index))
        removed.reverse()
        return removed

    def remove_entries(self, entry_ids: list[str]) -> list[MergeEntry]:
        removed: list[MergeEntry] = []
        wanted = set(entry_ids)
        kept: list[MergeEntry] = []
        for entry in self.entries:
            if entry.entry_id in wanted and not entry.locked:
                removed.append(entry)
                continue
            kept.append(entry)
        self.entries = kept
        return removed

    @property
    def can_confirm(self) -> bool:
        return any(entry.status != "rejected" for entry in self.entries)
