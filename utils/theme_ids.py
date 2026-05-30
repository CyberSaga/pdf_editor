"""Canonical theme identifiers — the single source of truth for valid themes.

This is a dependency-free leaf module so both the view layer (`view/theme.py`,
which owns the palettes/QSS) and the utils layer (`utils/preferences.py`, which
persists the choice) can import the same set without `utils` importing `view`
(a layer violation per CLAUDE.md §2). Keeping the authority here means the
valid-id set can never drift between the registry and the preference validator.
"""

from __future__ import annotations

# Display order of the themes (also the on-screen order of the switcher chips).
THEME_IDS: tuple[str, ...] = (
    "alpine-snow",
    "meadow-lupine",
    "ink-porcelain",
    "glimmering-glacier",
)

DEFAULT_THEME_ID: str = "alpine-snow"

VALID_THEME_IDS: frozenset[str] = frozenset(THEME_IDS)
