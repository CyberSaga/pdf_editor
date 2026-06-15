"""R2.1 — Layer-boundary AST guard: the structural net for the R-series.

Locks the MVC import invariants that CLAUDE.md §2 makes load-bearing, so an
accidental cross-layer import or a stray document handle introduced during the
R3 god-module decomposition fails CI instead of regressing silently:

  - ``model/`` never imports Qt (PySide6/PyQt) and never imports ``view``/``controller``.
  - ``view/`` never calls ``fitz.open(...)`` outside a small sanctioned allowlist.

Geometry value-types (``fitz.Rect``/``Point``/``Quad``/``Matrix``) and the typed
request channels (``model/edit_requests.py``, ``model/object_requests.py``) are
deliberately allowed — they are data, not live document handles, so a view may
import them. Only ``fitz.open`` (a document handle) is forbidden in the view.

This guard lands green against current code and stays live for every subsequent
R2/R3 edit.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _py_files(rel_dir: str) -> list[Path]:
    return sorted(p for p in (REPO_ROOT / rel_dir).rglob("*.py") if "__pycache__" not in p.parts)


def test_model_layer_imports_no_qt_and_no_view_or_controller() -> None:
    forbidden_tops = {"PySide6", "PyQt5", "PyQt6", "view", "controller"}
    offenders: list[str] = []
    for path in _py_files("model"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden_tops:
                        offenders.append(f"{rel}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                # Ignore relative imports (node.level > 0 stays within model/).
                if node.level == 0 and (node.module or "").split(".")[0] in forbidden_tops:
                    offenders.append(f"{rel}:{node.lineno} from {node.module}")
    assert not offenders, (
        "model/ must never import Qt or the view/controller layers (CLAUDE.md §2). "
        f"Offending imports: {offenders}"
    )


# view/ fitz.open allowlist: file -> the EXACT number of sanctioned fitz.open
# calls in it. An exact count catches a *new* fitz.open sneaking into an
# allowlisted file while staying robust to line-number drift.
_VIEW_FITZ_OPEN_ALLOWLIST: dict[str, int] = {
    # Empty scratch doc for the no-jump inline-editor preview — sanctioned,
    # permanent (it never touches a real/user document). This is the ONLY
    # fitz.open permitted anywhere in view/; R2.3 removed the merge-dialog leak.
    "view/text_editing.py": 1,
}


def _count_fitz_open(tree: ast.AST) -> int:
    count = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "open"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "fitz"
        ):
            count += 1
    return count


def test_view_layer_has_no_unsanctioned_fitz_open() -> None:
    offenders: list[str] = []
    for path in _py_files("view"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        found = _count_fitz_open(ast.parse(path.read_text(encoding="utf-8-sig")))
        allowed = _VIEW_FITZ_OPEN_ALLOWLIST.get(rel, 0)
        if found != allowed:
            offenders.append(f"{rel}: {found} fitz.open( call(s), allowlist expects {allowed}")
    assert not offenders, (
        "view/ must not call fitz.open(...) outside the sanctioned allowlist "
        "(geometry value-types are fine; document handles are not). Update R2.3 "
        f"and the allowlist together if intentional. Mismatches: {offenders}"
    )
