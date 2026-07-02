#!/usr/bin/env python3
"""Generate docs/PITFALLS_INDEX.md from docs/PITFALLS.md.

Each PITFALLS.md entry has a uniform shape (`## <title>` followed by
`**Area:** <subsystem>`). The index lists title, area, and the line number
of each entry so a session can grep the index (~2k tokens) and read only
the matched entries by offset, instead of bulk-reading the full file.

Run after every PITFALLS.md update (CLAUDE.md §6).
"""
from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).parent.parent / "docs"
SOURCE = DOCS / "PITFALLS.md"
INDEX = DOCS / "PITFALLS_INDEX.md"


def main() -> None:
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    entries: list[tuple[int, str, str]] = []  # (line_no, title, area)
    for i, line in enumerate(lines, start=1):
        if line.startswith("## "):
            entries.append((i, line[3:].strip(), ""))
        elif entries and not entries[-1][2]:
            m = re.match(r"\*\*Area:\*\*\s*(.+)", line.strip())
            if m:
                entries[-1] = (entries[-1][0], entries[-1][1], m.group(1).strip())

    out = [
        "# PITFALLS index (generated — do not edit)",
        "",
        f"Regenerate: `python scripts/build_pitfalls_index.py` · {len(entries)} entries.",
        "Read matched entries from `docs/PITFALLS.md` with `Read(offset=<line>, limit=~15)`.",
        "",
        "| Line | Title | Area |",
        "|---|---|---|",
    ]
    out += [f"| {n} | {title} | {area} |" for n, title, area in entries]
    INDEX.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Wrote {INDEX} ({len(entries)} entries)")


if __name__ == "__main__":
    main()
