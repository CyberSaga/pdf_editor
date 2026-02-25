"""macOS print driver implementation (CUPS stack)."""

from __future__ import annotations

from .linux_driver import LinuxPrinterDriver


class MacPrinterDriver(LinuxPrinterDriver):
    """macOS shares CUPS behavior with Linux in this project."""

    @property
    def name(self) -> str:
        return "macos_cups"

