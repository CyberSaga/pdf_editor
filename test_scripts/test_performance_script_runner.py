from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_performance_script_runs_from_repo_root() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "test_scripts" / "test_performance.py"

    # test_performance.py prints zh-TW status text (Phase 6 ...). On GitHub's
    # windows-latest runner the child's stdout is a captured pipe (not a
    # console), so CPython falls back to the process locale codepage (cp1252)
    # to encode it, and the zh-TW characters aren't representable there ->
    # UnicodeEncodeError inside the child, nonzero exit. Force UTF-8 I/O on
    # the child so its own print() calls succeed regardless of host locale
    # (docs/PITFALLS.md: "Windows runner locale codepage vs UTF-8 subprocess
    # text").
    child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

    completed = subprocess.run(
        [sys.executable, str(script), "--rounds", "1"],
        cwd=repo_root,
        capture_output=True,
        text=False,
        timeout=60,
        check=False,
        env=child_env,
    )

    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")

    assert completed.returncode == 0, stderr or stdout
    assert "成功編輯：1/1" in stdout
