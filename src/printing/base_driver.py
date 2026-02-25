"""Abstract printing driver contracts and shared models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .layout import (
    normalize_orientation,
    normalize_scale_mode,
    normalize_scale_percent,
)
from .page_selection import normalize_page_subset


@dataclass(slots=True)
class PrinterDevice:
    """System printer metadata."""

    name: str
    is_default: bool = False
    status: str = "unknown"
    raw: Optional[Dict[str, object]] = None


@dataclass(slots=True)
class PrintJobOptions:
    """User-selected print options."""

    printer_name: Optional[str] = None
    page_ranges: Optional[str] = None
    copies: int = 1
    collate: bool = True
    dpi: int = 300
    fit_to_page: bool = True
    color_mode: str = "color"  # color | grayscale
    duplex: str = "none"  # none | long | short
    job_name: str = "pdf_editor_job"
    output_pdf_path: Optional[str] = None  # virtual printer target
    transport: str = "auto"  # auto | direct_pdf | raster
    paper_size: str = "auto"  # auto | a4 | letter | legal
    orientation: str = "auto"  # auto | portrait | landscape
    scale_mode: str = "fit"  # fit | actual | custom
    scale_percent: int = 100  # 25~400
    page_subset: str = "all"  # all | odd | even
    reverse_order: bool = False
    extra_options: Dict[str, str] = field(default_factory=dict)

    def normalized(self) -> "PrintJobOptions":
        """Return a normalized copy used by drivers."""
        copies = max(1, int(self.copies))
        dpi = max(72, int(self.dpi))
        color_mode = self.color_mode.lower().strip() or "color"
        duplex = self.duplex.lower().strip() or "none"
        transport = self.transport.lower().strip() or "auto"
        scale_mode = normalize_scale_mode(self.scale_mode, fit_to_page=bool(self.fit_to_page))
        scale_percent = normalize_scale_percent(self.scale_percent)
        fit_to_page = scale_mode == "fit"
        return PrintJobOptions(
            printer_name=(self.printer_name or "").strip() or None,
            page_ranges=(self.page_ranges or "").strip() or None,
            copies=copies,
            collate=bool(self.collate),
            dpi=dpi,
            fit_to_page=fit_to_page,
            color_mode=color_mode,
            duplex=duplex,
            job_name=(self.job_name or "pdf_editor_job").strip(),
            output_pdf_path=(self.output_pdf_path or "").strip() or None,
            transport=transport,
            paper_size=(self.paper_size or "auto").strip().lower() or "auto",
            orientation=normalize_orientation(self.orientation),
            scale_mode=scale_mode,
            scale_percent=scale_percent,
            page_subset=normalize_page_subset(self.page_subset),
            reverse_order=bool(self.reverse_order),
            extra_options=dict(self.extra_options or {}),
        )


@dataclass(slots=True)
class PrintJobResult:
    """Submission result for a print job."""

    success: bool
    route: str
    message: str
    job_id: Optional[str] = None


class PrinterDriver(ABC):
    """Abstract base class for platform-specific print drivers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Driver display name."""

    @property
    def supports_direct_pdf(self) -> bool:
        """Whether this driver can submit raw PDF to platform spooler."""
        return False

    @abstractmethod
    def list_printers(self) -> List[PrinterDevice]:
        """Enumerate available system printers."""

    @abstractmethod
    def get_default_printer(self) -> Optional[str]:
        """Return default printer name if available."""

    @abstractmethod
    def get_printer_status(self, printer_name: str) -> str:
        """Return printer status string."""

    @abstractmethod
    def print_pdf(
        self,
        pdf_path: str,
        page_indices: List[int],
        options: PrintJobOptions,
    ) -> PrintJobResult:
        """Submit print job for the given PDF."""
