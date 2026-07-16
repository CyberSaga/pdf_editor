from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def reveal_in_file_manager(path: str) -> bool:
    """Reveal an existing file without constructing a shell command string."""
    candidate = str(path or "").strip()
    if not candidate or not os.path.isfile(candidate):
        return False
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer.exe", "/select,", candidate])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", candidate])
        else:
            subprocess.Popen(["xdg-open", str(Path(candidate).parent)])
    except OSError as exc:
        logger.warning("Unable to reveal file %s: %s", candidate, exc)
        return False
    return True
