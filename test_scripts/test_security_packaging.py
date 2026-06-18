"""R5.4 — packaging guard: dev/test/CUA trees must never ship in a built artifact.

`scripts/` is a real package (`scripts/__init__.py` exists) and holds the CUA sign-off
harness that drives the real keyboard/mouse via pyautogui — it must never be distributed.
`test_scripts/` is not a package (no leak into the wheel) but would ride along in an sdist
without the MANIFEST prunes.

Two governing mechanisms, guarded here:
  * wheel  -> `[tool.setuptools.packages.find].include` allow-list in pyproject.toml
  * sdist  -> `prune` directives in MANIFEST.in

The teeth of the real-build guard were verified out-of-band: adding `scripts*` to the
discovery allow-list leaks 10 `scripts/` members into the wheel, which `_offending_members`
flags. See refactor-state.md (R5.4) for the experiment.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Prefixes that must never appear in a distributable artifact's member list.
_DEV_TREES = ("scripts/", "test_scripts/")


def _offending_members(names: list[str]) -> list[str]:
    return sorted(n for n in names if n.startswith(_DEV_TREES))


def _load_pyproject() -> dict:
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError:
            pytest.skip("no TOML parser (tomllib/tomli) available")
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


# ── the predicate has teeth (the negative case the guards rely on) ───────────


def test_offending_predicate_flags_dev_trees() -> None:
    names = [
        "model/pdf_model.py",
        "scripts/__init__.py",
        "controller/pdf_controller.py",
        "test_scripts/test_x.py",
        "src/printing/helper_main.py",
    ]
    assert _offending_members(names) == ["scripts/__init__.py", "test_scripts/test_x.py"]


# ── wheel discovery is an allow-list (omission excludes scripts/test_scripts) ─


def test_pyproject_wheel_discovery_is_allowlist() -> None:
    data = _load_pyproject()
    include = data["tool"]["setuptools"]["packages"]["find"]["include"]
    assert isinstance(include, list) and include, "packages.find.include must be a non-empty allow-list"
    # No discovery pattern may match a dev/test tree.
    for pattern in include:
        head = pattern.rstrip("*").rstrip(".")
        assert not head.startswith(("scripts", "test_scripts", "docs")), (
            f"discovery pattern {pattern!r} would ship a dev/test tree"
        )
    # The production packages must still be discoverable (guards an over-prune regression).
    assert any(p.startswith("controller") for p in include)
    assert any(p.startswith("model") for p in include)


# ── sdist prunes the dev/test/doc trees ──────────────────────────────────────


def test_manifest_prunes_dev_trees() -> None:
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
    pruned = {line.split(None, 1)[1].strip().rstrip("/") for line in manifest if line.strip().startswith("prune ")}
    assert "scripts" in pruned, "MANIFEST.in must `prune scripts` (the CUA harness)"
    assert "test_scripts" in pruned, "MANIFEST.in must `prune test_scripts`"


# ── real artifact: build the wheel and assert no dev tree shipped ────────────


def test_built_wheel_excludes_dev_trees(tmp_path: Path) -> None:
    """Best-effort real build. Skips (does not fail) if the build backend/network
    is unavailable, so an offline runner degrades to the hermetic config guards above."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(tmp_path)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - env dependent
        pytest.skip(f"wheel build could not run: {exc}")

    # setuptools writes build/ into the project root (gitignored); keep the tree tidy.
    shutil.rmtree(REPO_ROOT / "build", ignore_errors=True)

    if result.returncode != 0:
        pytest.skip(f"wheel build unavailable (rc={result.returncode}): {result.stderr.strip()[-300:]}")

    wheels = list(tmp_path.glob("*.whl"))
    assert wheels, "pip wheel reported success but produced no .whl"
    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()

    offending = _offending_members(names)
    assert not offending, f"dev/test trees leaked into the built wheel: {offending}"
    # Sanity: the production packages are actually present.
    assert any(n.startswith("model/") for n in names), "wheel is missing the model package"
