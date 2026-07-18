"""Tests for scripts/hooks/pre_commit_device_guard.py.

Covers: each pattern fires on an added line, unchanged/removed lines are
never scanned, the allowlist suppresses known-legitimate docs, and main()
exits nonzero (blocking the commit) exactly when scan_diff() finds something.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))

import pre_commit_device_guard as guard  # noqa: E402


def _diff(file_path: str, *added_lines: str, removed: tuple[str, ...] = ()) -> str:
    body = "\n".join(f"-{line}" for line in removed)
    body += ("\n" if body and added_lines else "") + "\n".join(f"+{line}" for line in added_lines)
    return (
        f"diff --git a/{file_path} b/{file_path}\n"
        f"--- a/{file_path}\n"
        f"+++ b/{file_path}\n"
        f"@@ -1,0 +1,{len(added_lines)} @@\n"
        f"{body}\n"
    )


@pytest.mark.parametrize(
    "line",
    [
        r'FIXTURE_DIR = "C:\Users\alice\Documents\stuff"',
        "path = '/home/alice/.config/app.json'",
        "hostname = platform.node()",
        "name = socket.gethostname()",
        "user = os.getlogin()",
        "mac = '00:1A:2B:3C:4D:5E'",
        "print(os.environ['COMPUTERNAME'])",
    ],
)
def test_each_pattern_fires_on_added_line(line: str) -> None:
    findings = guard.scan_diff(_diff("model/pdf_model.py", line))
    assert findings, f"expected a finding for: {line!r}"
    assert findings[0].file == "model/pdf_model.py"


def test_removed_lines_are_never_scanned() -> None:
    diff_text = _diff("model/pdf_model.py", removed=(r'C:\Users\alice\old_path',))
    assert guard.scan_diff(diff_text) == []


def test_unrelated_added_line_is_clean() -> None:
    diff_text = _diff("model/pdf_model.py", "def edit_text(self, page_num: int) -> None:")
    assert guard.scan_diff(diff_text) == []


@pytest.mark.parametrize(
    "file_path",
    ["CLAUDE.md", "docs/PITFALLS.md", "docs/history/harness-creation.md", "plans/2026-07-14-x.md"],
)
def test_allowlisted_docs_are_not_scanned(file_path: str) -> None:
    diff_text = _diff(file_path, r'C:\Users\jiang\Documents\python programs\pdf_editor')
    assert guard.scan_diff(diff_text) == []


def test_non_allowlisted_file_with_same_path_still_blocks() -> None:
    diff_text = _diff("controller/pdf_controller.py", r'C:\Users\jiang\Documents\python programs\pdf_editor')
    findings = guard.scan_diff(diff_text)
    assert len(findings) == 1
    assert findings[0].file == "controller/pdf_controller.py"


def test_diff_decodes_non_ascii_bytes_in_the_real_repo_regardless_of_locale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: subprocess.run(text=True) decodes with the console's
    locale codepage, not UTF-8. A cp950 session crashed _diff() on an
    em-dash anywhere in the staged diff -- not just in device-info lines --
    because git diff output is always UTF-8. Exercises the real subprocess
    call (not mocked) against a scratch git repo so the fix is verified at
    the actual boundary that broke.
    """
    import subprocess

    def run(*cmd: str) -> None:
        subprocess.run(["git", *cmd], cwd=tmp_path, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "test")
    target = tmp_path / "note.py"
    target.write_text("# baseline\n", encoding="utf-8")
    run("add", "note.py")
    run("commit", "-q", "-m", "baseline")

    target.write_text("# drift only bit local runs — which is worse\n", encoding="utf-8")
    run("add", "note.py")

    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    diff_text = guard._diff(None)  # noqa: SLF001
    assert "which is worse" in diff_text


def test_main_returns_nonzero_when_findings_and_prints_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(guard, "_diff", lambda base_ref: _diff("model/x.py", "socket.gethostname()"))
    assert guard.main([]) == 1
    assert "device-identity leak" in capsys.readouterr().err


def test_main_returns_zero_when_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "_diff", lambda base_ref: _diff("model/x.py", "x = 1"))
    assert guard.main([]) == 0


def test_main_uses_base_ref_diff_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake_diff(base_ref: str | None) -> str:
        seen["base_ref"] = base_ref
        return ""

    monkeypatch.setattr(guard, "_diff", fake_diff)
    assert guard.main(["--base", "origin/main"]) == 0
    assert seen["base_ref"] == "origin/main"
