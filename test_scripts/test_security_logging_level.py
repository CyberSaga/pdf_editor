"""Security patch P6 (finding F7): release logging level.

`main._configure_logging` must default the root logger to WARNING in a shipped
build and only emit DEBUG when the operator opts in via the ``PDF_EDITOR_DEBUG``
environment variable. Verbose DEBUG logging leaks absolute file paths and full
tracebacks to the console.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import pytest

# ``test_scripts/conftest.py`` inserts the repo root onto sys.path before
# collection, so a plain top-level import resolves cleanly.
import main as main_module


@contextmanager
def _isolated_root_logging() -> Iterator[logging.Logger]:
    """Detach the root logger's handlers/level so basicConfig actually applies,
    then restore the prior state so pytest's own log capture is untouched."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    for handler in saved_handlers:
        root.removeHandler(handler)
    try:
        yield root
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)


def test_configure_logging_defaults_to_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PDF_EDITOR_DEBUG", raising=False)
    with _isolated_root_logging() as root:
        main_module._configure_logging()
        assert root.level == logging.WARNING


def test_configure_logging_debug_env_enables_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDF_EDITOR_DEBUG", "1")
    with _isolated_root_logging() as root:
        main_module._configure_logging()
        assert root.level == logging.DEBUG


def test_configure_logging_empty_env_value_is_not_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    # An empty string is falsy and must not flip on DEBUG.
    monkeypatch.setenv("PDF_EDITOR_DEBUG", "")
    with _isolated_root_logging() as root:
        main_module._configure_logging()
        assert root.level == logging.WARNING
