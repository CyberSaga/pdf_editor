"""Security patch P8 + Task 2 (finding F2): Pillow dependency floor & OCR split.

`Pillow>=9.0` resolves to releases carrying multiple image-parser CVEs. The floor
must be high enough that a fresh install cannot land on a known-vulnerable Pillow
reachable from untrusted image input. pip-audit's latest run fixes the current
Pillow advisories (CVE-2026-40192/42309/42310/42311, PYSEC-2026-165) in 12.2.0, so
the floor is 12.2.0.

Pillow backs core image features (deskew/straighten/optimize), so its floor lives
in requirements.txt. surya-ocr transitively caps `pillow<11`, which is unsatisfiable
with the secured floor, so OCR is isolated in ocr-requirements.txt. These tests lock
the floor location and the separation so the conflicting pins can never be
reintroduced into one resolvable file.
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO_ROOT / "requirements.txt"
OPTIONAL_REQS = REPO_ROOT / "optional-requirements.txt"


def _pillow_floor() -> Version:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        match = re.match(r"(?i)^pillow\s*>=\s*([0-9][0-9A-Za-z.\-]*)", stripped)
        if match:
            return Version(match.group(1))
    raise AssertionError("No 'Pillow>=' constraint found in requirements.txt")


def _has_surya(path: Path) -> bool:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.split("#", 1)[0].strip().lower().startswith("surya-ocr"):
            return True
    return False


def test_pillow_floor_is_at_least_12_2_0() -> None:
    assert _pillow_floor() >= Version("12.2.0")


def test_surya_ocr_not_in_core_requirements() -> None:
    """surya-ocr caps pillow<11, so it must never sit in the same resolvable file
    as the secured Pillow floor (requirements.txt)."""
    assert not _has_surya(REQUIREMENTS), (
        "surya-ocr must live in ocr-requirements.txt, not requirements.txt"
    )


def test_surya_ocr_not_in_optional_requirements() -> None:
    assert not _has_surya(OPTIONAL_REQS), (
        "surya-ocr must live in ocr-requirements.txt, not optional-requirements.txt"
    )
