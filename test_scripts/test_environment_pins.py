"""Fails loudly on PyMuPDF version skew instead of silently masking bugs.

requirements.txt / pyproject.toml pin PyMuPDF to >=1.27,<1.28 (not just a
floor): the text-commit engine's Tier 0/1 fidelity checks assert
byte-identical content-stream bytes, and PyMuPDF's stream serialization /
extract_font behavior can shift between minors. A stray interpreter (e.g.
system Python resolving an older PyMuPDF instead of the repo's `.venv`) must
not be allowed to pass this suite while quietly exercising different stream
behavior — see docs/PITFALLS.md "PyMuPDF version skew masks runtime-only
bugs" and CLAUDE.md's `.venv\\Scripts\\python.exe -m pytest` requirement.
"""
from __future__ import annotations

import fitz


def test_pymupdf_version_within_pinned_range() -> None:
    major, minor, *_ = (int(part) for part in fitz.__version__.split(".")[:2] + [0])
    assert (major, minor) == (1, 27), (
        f"fitz.__version__ == {fitz.__version__!r} is outside the pinned "
        "range (>=1.27,<1.28 per requirements.txt). This interpreter is not "
        "the repo .venv — re-run via `.venv\\Scripts\\python.exe -m pytest`, "
        "or the .venv install is stale (`pip install -e .[dev]`)."
    )
