"""Security patch P8 (finding F2): Pillow dependency floor.

`Pillow>=9.0` resolves to releases carrying multiple image-parser CVEs (pip-audit
confirmed: 5 Pillow advisories fixed in 12.1.1). The declared floor in
optional-requirements.txt must be at least 12.1.1 so a fresh install cannot land
on a known-vulnerable Pillow that is reachable from untrusted image/OCR input.
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[1]
OPTIONAL_REQS = REPO_ROOT / "optional-requirements.txt"


def _pillow_floor() -> Version:
    text = OPTIONAL_REQS.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        match = re.match(r"(?i)^pillow\s*>=\s*([0-9][0-9A-Za-z.\-]*)", stripped)
        if match:
            return Version(match.group(1))
    raise AssertionError("No 'Pillow>=' constraint found in optional-requirements.txt")


def test_pillow_floor_is_at_least_12_1_1() -> None:
    assert _pillow_floor() >= Version("12.1.1")
