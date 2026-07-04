from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# pip-audit (pip_requirements_parser) and pip itself decode requirement files
# with a locale fallback on Windows (cp1252 on the GitHub runners); a
# non-ASCII byte can crash the parse outright (0x81 is undefined in cp1252),
# which broke the windows-latest dependency-audit CI leg for three weeks.
# Keep every requirement/constraint file pure ASCII.
_REQUIREMENT_FILES = sorted(
    path
    for pattern in ("*requirements*.txt", "constraints*.txt")
    for path in REPO_ROOT.glob(pattern)
)


def test_requirement_files_found() -> None:
    assert _REQUIREMENT_FILES, "expected requirement files at the repo root"


@pytest.mark.parametrize("path", _REQUIREMENT_FILES, ids=lambda p: p.name)
def test_requirement_file_is_ascii(path: Path) -> None:
    raw = path.read_bytes()
    try:
        raw.decode("ascii")
    except UnicodeDecodeError as exc:
        line = raw[: exc.start].count(b"\n") + 1
        pytest.fail(
            f"{path.name} has a non-ASCII byte at offset {exc.start} (line {line}): "
            f"{raw[exc.start : exc.start + 8]!r}. Windows pip/pip-audit decode "
            "requirement files with cp1252 and can crash on it."
        )
