#!/usr/bin/env python3
"""Git pre-commit hook: block commits that leak local-machine identity.

Not installed automatically — git hooks live outside version control, so
`scripts/hooks/install_git_hooks.py` copies this into `.git/hooks/pre-commit`.
CI runs this same script with `--base <ref>` (diffing against the PR base
instead of the git index) as a second, un-bypassable layer, since a
missing/uninstalled local hook must not be the only defense.

Background: on 2026-07-15 a commit picked up this machine's local Windows
username / hardware fingerprint and had to be scrubbed with a git history
rewrite. This hook exists so that class of leak is caught before it ever
reaches a commit, not after.

Scope: only lines ADDED by the change under review (diff `+` lines), so
already-committed, intentionally-documented machine paths (e.g. the mypy
pitfall path in CLAUDE.md) do not retroactively trip the guard — only new
occurrences do. ALLOWLIST covers docs that legitimately document this
machine's paths as part of a recorded pitfall/history, plus this guard's own
source (whose patterns necessarily contain the strings they detect).
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ALLOWLIST = {
    "CLAUDE.md",
    "docs/PITFALLS.md",
    "docs/ARCHITECTURE.md",
    "docs/PDF-shell-operation-manual.md",
    "scripts/hooks/pre_commit_device_guard.py",
    "test_scripts/test_pre_commit_device_guard.py",
}
ALLOWLISTED_DIRS = (
    "docs/history/",
    "plans/",
)

# (label, compiled pattern) — patterns target added-line content only.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("windows user-profile path", re.compile(r"C:\\Users\\[^\\\s\"']+\\")),
    ("posix home-directory path", re.compile(r"/home/[^/\s\"']+/")),
    (
        "device/hostname fingerprint call",
        re.compile(
            r"\b(platform\.node|platform\.uname|socket\.gethostname|"
            r"os\.getlogin|uuid\.getnode)\s*\("
        ),
    ),
    ("MAC address literal", re.compile(r"\b[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}\b")),
    (
        "COMPUTERNAME env leak",
        re.compile(r"%COMPUTERNAME%|\$env:COMPUTERNAME|\bCOMPUTERNAME\b\s*[='\"\]]"),
    ),
]


@dataclass(frozen=True)
class Finding:
    file: str
    label: str
    line: str


def _is_allowlisted(file_path: str) -> bool:
    if file_path in ALLOWLIST:
        return True
    return any(file_path.startswith(prefix) for prefix in ALLOWLISTED_DIRS)


def scan_diff(diff_text: str) -> list[Finding]:
    """Scan unified-diff text (added lines only) for device-identity leaks."""
    findings: list[Finding] = []
    current_file: str | None = None
    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ "):
            path = raw_line[4:].strip()
            if path == "/dev/null":
                current_file = None
            else:
                current_file = path[2:] if path.startswith(("a/", "b/")) else path
            continue
        if not raw_line.startswith("+") or raw_line.startswith("+++"):
            continue
        if current_file is None or _is_allowlisted(current_file):
            continue
        content = raw_line[1:]
        for label, pattern in PATTERNS:
            if pattern.search(content):
                findings.append(Finding(file=current_file, label=label, line=content.strip()))
    return findings


def _diff(base_ref: str | None) -> str:
    args = (
        ["git", "diff", f"{base_ref}...HEAD", "--no-color", "-U0"]
        if base_ref
        else ["git", "diff", "--cached", "--no-color", "-U0"]
    )
    # git diff output is UTF-8 regardless of the console codepage (observed:
    # a cp950 locale made subprocess.run's default text-mode decoding crash
    # on any non-ASCII byte anywhere in the diff, not just device info).
    result = subprocess.run(
        args, cwd=REPO_ROOT, capture_output=True, encoding="utf-8", errors="replace", check=False
    )
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    base_ref = None
    if args and args[0] == "--base":
        base_ref = args[1] if len(args) > 1 else None
    diff_text = _diff(base_ref)
    findings = scan_diff(diff_text)
    if not findings:
        return 0
    scope = f"changes since {base_ref}" if base_ref else "staged changes"
    print(f"blocked: possible device-identity leak in {scope}:", file=sys.stderr)
    for f in findings:
        print(f"  {f.file}: {f.label}\n    {f.line}", file=sys.stderr)
    print(
        "\nIf this is a legitimate, intentional reference (e.g. a documented "
        "pitfall path), add the file to ALLOWLIST in "
        "scripts/hooks/pre_commit_device_guard.py.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
