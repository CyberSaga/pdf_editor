"""Path bootstrap for hybrid test scripts executed as ``python test_scripts/<name>.py``.

Under pytest, ``conftest.py`` already inserts the repo root on ``sys.path`` (and
sets the offscreen Qt platform) before any test module is imported. Script-mode
execution gets neither, so hybrid files make this their FIRST import:

    import _bootstrap  # noqa: F401

Deliberately does NOT set ``QT_QPA_PLATFORM``: some hybrid scripts have real-GUI
modes (e.g. ``test_1pdf_horizontal.py --gui``) that a forced offscreen default
would silently break. The underscore prefix keeps pytest from collecting this
module; with no ``test_scripts/__init__.py``, the bare import resolves under both
pytest (test-dir prepend) and script mode (script dir is ``sys.path[0]``).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
