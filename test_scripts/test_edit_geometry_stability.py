from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_model import PDFModel


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(72, 96, 220, 132), "Stable target", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(72, 150, 260, 186), "Neighbor block", fontsize=12, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


def _find_block(model: PDFModel, page_idx: int, probe: str):
    model.ensure_page_index_built(page_idx + 1)
    for block in model.block_manager.get_blocks(page_idx):
        if probe in (block.text or ""):
            return block
    return None


def test_repeated_identical_edits_keep_y1_drift_under_half_point() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "geometry.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            original = _find_block(model, 0, "Stable target")
            assert original is not None
            baseline_y1 = float(original.layout_rect.y1)

            for _ in range(5):
                current = _find_block(model, 0, "Stable target")
                assert current is not None
                model.edit_text(
                    page_num=1,
                    rect=fitz.Rect(current.layout_rect),
                    new_text="Stable target",
                    font=current.font,
                    size=max(8, int(round(current.size))),
                    color=current.color,
                    original_text=current.text,
                )
                model.block_manager.rebuild_page(0, model.doc)

            final_block = _find_block(model, 0, "Stable target")
            assert final_block is not None
            assert abs(float(final_block.layout_rect.y1) - baseline_y1) < 0.5
        finally:
            model.close()
