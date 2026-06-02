"""Security patch P5 (finding F5 / bandit B110): temp-unlink error visibility.

``PrintDispatcher.print_pdf_bytes`` writes the document to a temp file and removes
it in a ``finally`` block. A bare ``except Exception: pass`` there masked cleanup
failures (a leftover temp PDF holding document content). The failure must now be
logged at debug, while still not propagating (cleanup must not mask the result).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from src.printing.base_driver import PrintJobOptions, PrintJobResult
from src.printing.dispatcher import PrintDispatcher


def test_print_pdf_bytes_logs_unlink_failure_at_debug(monkeypatch, caplog) -> None:
    dispatcher = PrintDispatcher(driver=object(), renderer=object())

    sentinel = PrintJobResult(success=True, route="test", message="ok")
    monkeypatch.setattr(dispatcher, "print_pdf_file", lambda path, opts: sentinel)

    leaked: list[Path] = []

    def _boom(self, *args, **kwargs):
        leaked.append(Path(self))
        raise PermissionError("temp file is locked")

    monkeypatch.setattr("src.printing.dispatcher.Path.unlink", _boom)

    try:
        with caplog.at_level(logging.DEBUG, logger="src.printing.dispatcher"):
            result = dispatcher.print_pdf_bytes(b"%PDF-1.4\n%%EOF\n", PrintJobOptions())

        # The cleanup failure must NOT propagate; the real result is returned.
        assert result is sentinel
        # And it must be observable at debug level rather than silently swallowed.
        debug_msgs = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.DEBUG and rec.name == "src.printing.dispatcher"
        ]
        assert any("temp" in m.lower() for m in debug_msgs), debug_msgs
    finally:
        # Remove the temp file the patched unlink refused to delete.
        for path in leaked:
            try:
                os.unlink(path)
            except OSError:
                pass
