"""Printing subsystem exceptions."""


class PrintingError(RuntimeError):
    """Base error for printing subsystem."""


class PrinterUnavailableError(PrintingError):
    """Raised when no printer is available or selected printer is missing."""


class PrinterOfflineError(PrintingError):
    """Raised when the selected printer is offline/stopped."""


class PrintJobSubmissionError(PrintingError):
    """Raised when submitting a print job fails."""


class RenderingError(PrintingError):
    """Raised when page rasterization fails."""


class PrintHelperStalledError(PrintingError):
    """Raised when the helper subprocess stops reporting progress."""


class PrintHelperTerminatedError(PrintingError):
    """Raised when the user terminates the helper subprocess."""

