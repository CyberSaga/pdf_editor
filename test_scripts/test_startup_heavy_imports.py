"""Startup heavy-import guard.

Imports view.pdf_view in a clean subprocess and asserts that numpy, PIL,
pikepdf, and lxml are NOT loaded as a side effect.  These 55 MB of native
DLLs must remain deferred until first actual use.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_PROBE = """
import sys, json, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"{root}")
import view.pdf_view  # noqa: F401 — side-effect import under test
heavy = [m for m in sys.modules if m.startswith(("numpy", "PIL", "pikepdf", "lxml"))]
print(json.dumps(sorted(heavy)))
""".format(root=str(ROOT).replace("\\", "\\\\"))


def _run_probe() -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Probe failed:\n{result.stderr}"
    return json.loads(result.stdout.strip())


def test_numpy_not_loaded_at_pdf_view_import():
    """numpy must not appear in sys.modules after importing view.pdf_view."""
    loaded = _run_probe()
    numpy_mods = [m for m in loaded if m.startswith("numpy")]
    assert numpy_mods == [], (
        f"numpy loaded at startup (should be deferred to first text-edit use): {numpy_mods}"
    )


def test_pil_pikepdf_lxml_not_loaded_at_pdf_view_import():
    """PIL, pikepdf, and lxml must not appear in sys.modules after importing view.pdf_view."""
    loaded = _run_probe()
    heavy = [m for m in loaded if m.startswith(("PIL", "pikepdf", "lxml"))]
    assert heavy == [], (
        f"Heavy dialog deps loaded at startup (should be deferred to first dialog open): {heavy}"
    )
