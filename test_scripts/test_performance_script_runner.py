from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_performance_script_runs_from_repo_root() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "test_scripts" / "test_performance.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--rounds", "1"],
        cwd=repo_root,
        capture_output=True,
        text=False,
        timeout=60,
        check=False,
    )

    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")

    assert completed.returncode == 0, stderr or stdout
    assert "成功編輯：1/1" in stdout
