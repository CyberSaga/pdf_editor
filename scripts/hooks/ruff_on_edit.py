#!/usr/bin/env python3
"""PostToolUse hook (Edit|Write): ruff-check the edited Python file.

Registered in .claude/settings.json. Reads the hook payload from stdin,
extracts the edited file path, and runs `ruff check` on it. Exit 2 feeds
the findings back to the agent so lint is fixed at edit time instead of
at Definition-of-Done. Non-Python files and missing files exit 0 silently.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        # utf-8-sig: tolerate a BOM (PowerShell pipes prepend one)
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return 0

    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    if not file_path or not file_path.endswith(".py"):
        return 0
    path = Path(file_path)
    if not path.is_file():
        return 0

    try:
        result = subprocess.run(
            ["ruff", "check", "--quiet", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0  # ruff unavailable/slow — never block edits on tooling

    if result.returncode != 0 and result.stdout.strip():
        print(f"ruff findings in {path.name}:\n{result.stdout.strip()}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
