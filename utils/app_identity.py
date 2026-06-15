"""Canonical application-identity strings — the single source of truth.

A dependency-free leaf module (mirrors ``utils/theme_ids.py``) so every layer
can import the same identity values without a cycle or a layer violation
(CLAUDE.md §2). Consolidating these here removes a class of *silent-failure*
bugs: a drifted copy of any value breaks something with no exception surfaced —
open-file forwarding to a running instance, the taskbar icon grouping, or the
QSettings store / one-time migration.

WARNING — compatibility values. The IPC prefixes and the legacy QSettings
``(LEGACY_ORG, LEGACY_APP)`` are wire / at-rest identities shared with already
installed or already running builds. Changing them silently breaks forwarding to
a running instance and the one-time preferences migration from older installs.
Keep them byte-identical unless you are deliberately breaking compatibility with
a shipped version. ``scripts/windows_file_association.ps1`` mirrors the exe stem
(``ARGPARSE_PROG``) and the app name (``APP``) and must be updated in lock-step.
"""

from __future__ import annotations

# QSettings store identity — PySide6 ``QSettings(ORG, APP)``.
ORG: str = "CyberSaga"
APP: str = "CyberSagaPDF"

# Legacy QSettings identity written by older builds. The one-time settings
# migration reads ``QSettings(LEGACY_ORG, LEGACY_APP)``; if these drift from what
# those builds wrote, migration silently finds nothing.
LEGACY_ORG: str = "pdf_editor"
LEGACY_APP: str = "pdf_editor"

# argparse program name (usage / --help text only).
ARGPARSE_PROG: str = "cybersaga_pdf"

# Windows AppUserModelID — gives the taskbar the app's own icon/grouping instead
# of inheriting the host python(w).exe identity.
APP_USER_MODEL_ID: str = "CyberSaga.CyberSagaPDF"

# Single-instance IPC. The per-user QLocalServer name is
# ``f"{IPC_SERVER_PREFIX}{username}"``; a drift breaks open-file forwarding to a
# running instance with no error. The legacy prefix detects an instance launched
# by an older build.
IPC_SERVER_PREFIX: str = "cybersagapdf_singleinstance_"
IPC_LEGACY_SERVER_PREFIX: str = "pdf_editor_singleinstance_"
