#!/usr/bin/env python3
"""PostToolUse hook (Edit|Write): ruff-check the edited Python file.

Registered in .claude/settings.json. Reads the hook payload from stdin,
extracts the edited file path, and runs `ruff check` on it.

Exit codes (Claude Code hook contract):
  0 — clean file, non-Python file, or nothing to check
  2 — ruff findings; stderr is fed back to the agent to fix at edit time
  1 — hook could not run ruff (missing toolchain, timeout); stderr warns the
      user so a broken lint gate is visible instead of silently fail-open

Toolchain pinning: prefers the repo venv's ruff (.venv/Scripts/ruff.exe or
.venv/bin/ruff) so results match `ruff check .` in CI regardless of PATH;
falls back to PATH ruff only if the venv copy is absent.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_ruff() -> str | None:
    for candidate in (
        REPO_ROOT / ".venv" / "Scripts" / "ruff.exe",  # Windows venv
        REPO_ROOT / ".venv" / "bin" / "ruff",  # POSIX venv
    ):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ruff")


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

    ruff = _resolve_ruff()
    if ruff is None:
        print(
            "ruff_on_edit hook: ruff not found (.venv missing and not on PATH) — "
            "lint-on-edit is NOT running. Install dev deps: pip install -e .[dev]",
            file=sys.stderr,
        )
        return 1

    try:
        result = subprocess.run(
            [ruff, "check", "--quiet", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(
            f"ruff_on_edit hook: failed to run {ruff} ({exc.__class__.__name__}) — "
            f"this edit was NOT lint-checked.",
            file=sys.stderr,
        )
        return 1

    if result.returncode == 0:
        return 0
    # ruff check contract: 1 = violations found (findings on stdout),
    # 2+ = tool/config error. Anything but a clean lint-findings case is a
    # broken lint check and must be surfaced, not swallowed.
    if result.returncode == 1 and result.stdout.strip():
        print(f"ruff findings in {path.name}:\n{result.stdout.strip()}", file=sys.stderr)
        return 2
    detail = result.stderr.strip() or result.stdout.strip() or "(no output)"
    print(
        f"ruff_on_edit hook: ruff exited {result.returncode} without findings — "
        f"this edit was NOT lint-checked.\n{detail}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
