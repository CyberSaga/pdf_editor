"""Task 2 (finding F2): lock the OCR-extra dependency file's documented decisions.

surya-ocr transitively constrains pillow<11 and an unbounded transformers>=4.56.1.
No surya-ocr release requires/validates transformers 5.x, and one transformers CVE
(PYSEC-2025-217) has no fix at all, so the transformers floor is intentionally NOT
bumped to 5.0.0rc3. These tests lock that decision so a later well-meaning edit
cannot silently introduce the untested/unsatisfiable bump.
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[1]
OCR_REQS = REPO_ROOT / "ocr-requirements.txt"


def _requirements() -> list[Requirement]:
    reqs: list[Requirement] = []
    for line in OCR_REQS.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        reqs.append(Requirement(stripped))
    return reqs


def test_ocr_requirements_file_exists() -> None:
    assert OCR_REQS.is_file(), "ocr-requirements.txt must exist as the separate OCR extra"


def test_surya_ocr_is_declared_in_ocr_file() -> None:
    names = {r.name.lower() for r in _requirements()}
    assert "surya-ocr" in names


def test_transformers_not_pinned_to_unvalidated_5x() -> None:
    """No surya-ocr release requires transformers>=5; the bump is untested and one
    of the two CVEs is unfixable. Guard against re-introducing a >=5 floor here."""
    text = OCR_REQS.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        if re.match(r"(?i)^transformers\b", stripped):
            req = Requirement(stripped)
            for spec in req.specifier:
                if spec.operator in (">=", "==", ">"):
                    assert Version(spec.version) < Version("5.0.0"), (
                        f"transformers floor {spec} re-introduces the untested 5.x bump"
                    )
