"""Iteration 1 — Print auto paper-size detection + orientation (AC-2, AC-3).

Root cause being fixed: `_to_q_page_size()` fell through to a custom
`QPageSize(QSizeF(...))` for every "auto" case — even when the source page was a
standard size (A4/A3). Windows printer drivers silently snap custom page sizes to
their default (usually A4 portrait), so A3 landscape jobs printed cropped on A4.

The fix matches source dimensions against a standard-size table and returns a
*named* QPageSize constant the driver recognises, falling back to custom only for
genuinely non-standard sizes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPageSize
from PySide6.QtWidgets import QApplication

from src.printing import qt_bridge as qtb
from src.printing.base_driver import PrinterDevice
from src.printing.layout import match_standard_paper_size
from src.printing.print_dialog import UnifiedPrintDialog

# Standard portrait dimensions in points (ISO 216 / ANSI), for fixtures.
A3_PORTRAIT = (841.89, 1190.55)
A4_PORTRAIT = (595.28, 841.89)
LETTER_PORTRAIT = (612.0, 792.0)
TABLOID_PORTRAIT = (792.0, 1224.0)


# ---------------------------------------------------------------------------
# layout.match_standard_paper_size — pure dimension matcher
# ---------------------------------------------------------------------------


def test_match_standard_paper_size_a3_portrait() -> None:
    assert match_standard_paper_size(*A3_PORTRAIT) == "a3"


def test_match_standard_paper_size_a3_landscape() -> None:
    # Orientation-independent: a landscape A3 still resolves to A3.
    assert match_standard_paper_size(A3_PORTRAIT[1], A3_PORTRAIT[0]) == "a3"


def test_match_standard_paper_size_a4() -> None:
    assert match_standard_paper_size(*A4_PORTRAIT) == "a4"


def test_match_standard_paper_size_letter() -> None:
    assert match_standard_paper_size(*LETTER_PORTRAIT) == "letter"


def test_match_standard_paper_size_tabloid() -> None:
    assert match_standard_paper_size(*TABLOID_PORTRAIT) == "tabloid"


def test_match_standard_paper_size_non_standard_returns_none() -> None:
    assert match_standard_paper_size(700.0, 900.0) is None


def test_match_standard_paper_size_tolerates_small_rounding() -> None:
    # PyMuPDF may report A4 as 595.0 × 842.0 rather than 595.28 × 841.89.
    assert match_standard_paper_size(595.0, 842.0) == "a4"


# ---------------------------------------------------------------------------
# qt_bridge._to_q_page_size — returns NAMED QPageSize for standard sizes
# ---------------------------------------------------------------------------


def test_to_q_page_size_auto_a3_source_returns_named_a3() -> None:
    """AC-3a: an A3 source page must map to the named A3 size, not A4/custom."""
    size = qtb._to_q_page_size("auto", QRectF(0.0, 0.0, *A3_PORTRAIT))
    assert size.id() == QPageSize.A3


def test_to_q_page_size_auto_a3_landscape_source_returns_named_a3() -> None:
    size = qtb._to_q_page_size("auto", QRectF(0.0, 0.0, A3_PORTRAIT[1], A3_PORTRAIT[0]))
    assert size.id() == QPageSize.A3


def test_to_q_page_size_auto_a4_source_returns_named_a4_not_custom() -> None:
    """AC-3b: A4 source uses driver-recognised named A4, never a custom size."""
    size = qtb._to_q_page_size("auto", QRectF(0.0, 0.0, *A4_PORTRAIT))
    assert size.id() == QPageSize.A4


def test_to_q_page_size_auto_non_standard_falls_back_to_custom() -> None:
    """AC-3c: a genuinely non-standard size falls back to a custom QPageSize."""
    size = qtb._to_q_page_size("auto", QRectF(0.0, 0.0, 700.0, 900.0))
    assert size.id() == QPageSize.Custom
    # Custom must carry the source dimensions (portrait-normalised).
    pts = size.sizePoints()
    assert {pts.width(), pts.height()} == {700, 900}


def test_to_q_page_size_explicit_a4_overrides_source() -> None:
    """AC-3d: explicit A4 wins regardless of an A3-sized source page."""
    size = qtb._to_q_page_size("a4", QRectF(0.0, 0.0, *A3_PORTRAIT))
    assert size.id() == QPageSize.A4


def test_to_q_page_size_explicit_a3_returns_named_a3() -> None:
    size = qtb._to_q_page_size("a3", QRectF(0.0, 0.0, *A4_PORTRAIT))
    assert size.id() == QPageSize.A3


def test_to_q_page_size_explicit_tabloid_returns_named_tabloid() -> None:
    size = qtb._to_q_page_size("tabloid", QRectF(0.0, 0.0, *A4_PORTRAIT))
    assert size.id() == QPageSize.Tabloid


# ---------------------------------------------------------------------------
# AC-3e: A3 is offered in the print dialog paper combo
# ---------------------------------------------------------------------------


def test_print_dialog_paper_combo_offers_a3() -> None:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    class _FakeDispatcher:
        def get_default_printer(self):
            return "Printer A"

        def resolve_page_indices_for_count(self, total_pages, options):
            _ = options
            return [0] if total_pages > 0 else []

        def supports_printer_properties_dialog(self):
            return False

    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "sample.pdf"
        doc = fitz.open()
        doc.new_page(width=200, height=200)
        doc.save(pdf_path)
        doc.close()

        dialog = UnifiedPrintDialog(
            parent=None,
            dispatcher=_FakeDispatcher(),
            printers=[PrinterDevice(name="Printer A", is_default=True, status="ready")],
            pdf_path=str(pdf_path),
            total_pages=1,
            current_page=1,
            job_name="test_job",
        )
        try:
            assert dialog.paper_combo.findData("a3") >= 0
        finally:
            dialog.close()
