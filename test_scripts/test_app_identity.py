"""R1.2 — utils/app_identity.py is the single source of truth for the app's
identity strings.

Drift in any of these breaks something *silently* (no exception):
  - IPC_SERVER_PREFIX  -> open-file forwarding to a running instance stops working
  - IPC_LEGACY_SERVER_PREFIX -> a still-running old instance is no longer detected
  - ORG / APP          -> QSettings reads a different store (preferences "reset")
  - LEGACY_ORG / APP   -> the one-time settings migration silently finds nothing
  - APP_USER_MODEL_ID  -> the taskbar regroups under python(w).exe
  - ARGPARSE_PROG      -> usage/--help text only (cosmetic)

This test pins the byte-identical values and asserts the leaf stays a
dependency-free root (mirrors utils/theme_ids.py) that the consumers import from
rather than re-defining the literals.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_identity_constants_are_byte_identical() -> None:
    from utils import app_identity

    # The IPC prefixes are the highest-stakes: a single-character drift breaks
    # open-file forwarding to a running instance with NO error surfaced.
    assert app_identity.IPC_SERVER_PREFIX == "cybersagapdf_singleinstance_"
    assert app_identity.IPC_LEGACY_SERVER_PREFIX == "pdf_editor_singleinstance_"
    assert app_identity.ORG == "CyberSaga"
    assert app_identity.APP == "CyberSagaPDF"
    assert app_identity.LEGACY_ORG == "pdf_editor"
    assert app_identity.LEGACY_APP == "pdf_editor"
    assert app_identity.ARGPARSE_PROG == "cybersaga_pdf"
    assert app_identity.APP_USER_MODEL_ID == "CyberSaga.CyberSagaPDF"


def test_leaf_is_dependency_free() -> None:
    # Mirrors utils/theme_ids.py: no first-party imports, so it is the root other
    # identity-aware modules can depend on without creating a cycle or a layer
    # violation (CLAUDE.md §2).
    src = (REPO_ROOT / "utils" / "app_identity.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    first_party = ("utils", "model", "view", "controller", "src", "main")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in first_party:
            raise AssertionError(f"app_identity must stay dependency-free; imports {node.module!r}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in first_party, (
                    f"app_identity must stay dependency-free; imports {alias.name!r}"
                )


def _imports_from(rel_path: str, module_tail: str) -> bool:
    src = (REPO_ROOT / rel_path).read_text(encoding="utf-8-sig")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(module_tail):
            return True
    return False


def test_consumers_source_identity_from_leaf() -> None:
    # Every consumer must pull identity from the leaf instead of re-declaring the
    # literals (the drift bug this consolidation removes).
    assert _imports_from("main.py", "app_identity"), "main.py must import from utils.app_identity"
    assert _imports_from("utils/single_instance.py", "app_identity"), (
        "single_instance.py must import the IPC prefixes from utils.app_identity"
    )
    assert _imports_from("utils/preferences.py", "app_identity"), (
        "preferences.py must import ORG/APP from utils.app_identity"
    )


def test_consumers_do_not_redefine_unique_identity_literals() -> None:
    # AST-level guard: no consumer may contain a string literal equal to one of
    # the unique identity values (catches a re-hardcoded prefix/AUMID). Restricted
    # to the unambiguous values so a doc/comment mention cannot false-positive.
    unique = {
        "cybersagapdf_singleinstance_",
        "pdf_editor_singleinstance_",
        "CyberSaga.CyberSagaPDF",
        "cybersaga_pdf",
    }
    for rel in ("main.py", "utils/single_instance.py", "utils/preferences.py"):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8-sig")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in unique, (
                    f"{rel} re-hardcodes identity literal {node.value!r}; import it "
                    "from utils.app_identity instead"
                )
