#!/usr/bin/env python3
"""Install repo-provided git hooks into .git/hooks/.

Git hooks live in .git/ and are never version-controlled, so a fresh clone
has none installed until this is run once:

    python scripts/hooks/install_git_hooks.py

Currently installs: pre-commit -> scripts/hooks/pre_commit_device_guard.py
(CLAUDE.md device-identity guard). If .git/hooks/pre-commit already exists
and was not written by this installer, it is left untouched and a warning is
printed instead of overwriting a hook the user may have set up themselves.
"""
from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MARKER = "# installed-by: scripts/hooks/install_git_hooks.py\n"

HOOK_BODY = """#!/bin/sh
# installed-by: scripts/hooks/install_git_hooks.py
python "{target}" || python3 "{target}" || exit 1
"""


def _git_hooks_dir() -> Path | None:
    # Hooks live in the common git dir, not per-worktree -- `.git` may be a
    # file (linked worktree) rather than a directory, so resolve via git
    # itself instead of assuming `.git/hooks`.
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return None
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = REPO_ROOT / common_dir
    return common_dir / "hooks"


def main() -> int:
    git_hooks_dir = _git_hooks_dir()
    if git_hooks_dir is None or not git_hooks_dir.is_dir():
        print(f"could not resolve .git/hooks (got {git_hooks_dir}) -- is this a git checkout?", file=sys.stderr)
        return 1

    pre_commit = git_hooks_dir / "pre-commit"
    if pre_commit.exists() and MARKER not in pre_commit.read_text(encoding="utf-8", errors="ignore"):
        print(
            f"{pre_commit} already exists and was not installed by this script -- "
            "leaving it untouched. Add a call to "
            "scripts/hooks/pre_commit_device_guard.py to it manually.",
            file=sys.stderr,
        )
        return 1

    target = REPO_ROOT / "scripts" / "hooks" / "pre_commit_device_guard.py"
    pre_commit.write_text(HOOK_BODY.format(target=target), encoding="utf-8")
    pre_commit.chmod(pre_commit.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"installed {pre_commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
