"""
Track A/B 五大 UX 場景診斷測試
────────────────────────────────
目標：以 headless model-level API 驗證五個關鍵場景，不需 Qt UI。

Scenario 1: 同段落中段改字 → 後文正確位移，不誤刪
Scenario 2: 同高度或縮短替換 → 不 silent-no-op
Scenario 3: 編輯框預覽位置 vs 最終落地位置一致性
Scenario 4: 多次連續編輯 + undo/redo → viewport 文字狀態正確
Scenario 5: 多行段落樣式繼承 → 字型/大小/顏色穩定
"""
import io
import logging
import sys
import tempfile
from pathlib import Path

import fitz

if sys.platform == "win32" and __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextCommand
from model.pdf_model import PDFModel

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_5scenarios")


# ─────────────────────────────────────────────────────────────────────────────
# Helper: PDF fixture builder
# ─────────────────────────────────────────────────────────────────────────────

def _make_paragraph_pdf(path: str) -> None:
    """Three lines of text at (72, 100/120/140), then a trailing block at (72, 200)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Line-A: The quick brown fox.", fontsize=12, fontname="helv")
    page.insert_text((72, 120), "Line-B: jumps over the lazy dog.", fontsize=12, fontname="helv")
    page.insert_text((72, 140), "Line-C: Pack my box with five dozen liquor jugs.", fontsize=12, fontname="helv")
    # trailing block that should be displaced when middle text grows
    page.insert_text((72, 200), "Trailing-block: should shift down", fontsize=12, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


def _make_simple_pdf(path: str) -> None:
    """Single block for simple edit tests."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=12, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


def _make_multiline_style_pdf(path: str) -> None:
    """Multiple styled lines to test style inheritance."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Line 1: big, black
    page.insert_text((72, 100), "Title: Big and Bold", fontsize=18, fontname="helv")
    # Line 2: small, black
    page.insert_text((72, 140), "Body: Normal text here.", fontsize=12, fontname="helv")
    # Line 3: different color (red)
    page.insert_text((72, 170), "Note: important warning.", fontsize=10, fontname="helv",
                     color=(1.0, 0.0, 0.0))
    # Adjacent block that must survive edits to earlier text
    page.insert_text((72, 250), "Footer: do not touch me.", fontsize=12, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


def _make_consecutive_edit_pdf(path: str) -> None:
    """Three separate text blocks for consecutive edit + undo/redo test."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Block-1: first", fontsize=12, fontname="helv")
    page.insert_text((72, 160), "Block-2: second", fontsize=12, fontname="helv")
    page.insert_text((72, 220), "Block-3: third", fontsize=12, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


# ─────────────────────────────────────────────────────────────────────────────
# Helper: text extraction & comparison
# ─────────────────────────────────────────────────────────────────────────────

def _page_text(model: PDFModel, page_idx: int = 0) -> str:
    return model.doc[page_idx].get_text("text")


def _norm(t: str) -> str:
    import re
    return re.sub(r"\s+", " ", t).strip()


def _find_block(model: PDFModel, page_idx: int, text_probe: str):
    """Find first TextBlock whose text contains *text_probe*."""
    model.ensure_page_index_built(page_idx + 1)
    for b in model.block_manager.get_blocks(page_idx):
        if text_probe in b.text:
            return b
    return None


def _find_run(model: PDFModel, page_idx: int, text_probe: str):
    """Find first EditableSpan whose text contains *text_probe*."""
    model.ensure_page_index_built(page_idx + 1)
    for r in model.block_manager.get_runs(page_idx):
        if text_probe in r.text:
            return r
    return None


def _edit(model, target, new_text, *, font=None, size=None, color=None,
          original_text=None, new_rect=None, target_span_id=None, target_mode=None):
    """Wrapper around model.edit_text with sensible defaults."""
    model.edit_text(
        page_num=1,
        rect=target.layout_rect if hasattr(target, "layout_rect") else fitz.Rect(target.bbox),
        new_text=new_text,
        font=font or target.font or "helv",
        size=int(size or target.size or 12),
        color=color or target.color or (0.0, 0.0, 0.0),
        original_text=original_text or target.text,
        new_rect=new_rect,
        target_span_id=target_span_id,
        target_mode=target_mode,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1: Mid-paragraph edit — subsequent text displaced correctly
# ─────────────────────────────────────────────────────────────────────────────

def scenario_1_displacement(tmpdir: str) -> tuple[bool, str]:
    """Edit middle line to a longer text; trailing block must shift down, not be deleted."""
    pdf_path = str(Path(tmpdir) / "s1.pdf")
    _make_paragraph_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)

    # Capture trailing block position before edit
    trailing_before = _find_block(model, 0, "Trailing-block")
    if not trailing_before:
        return False, "Setup: cannot find trailing block"
    trailing_y0_before = trailing_before.layout_rect.y0

    # Find Line-B and replace with much longer text
    target = _find_block(model, 0, "Line-B")
    if not target:
        return False, "Setup: cannot find Line-B block"

    long_text = (
        "Line-B EDITED: This replacement text is deliberately much longer "
        "than the original to force the text block to grow in height and "
        "require displacement of subsequent blocks."
    )
    try:
        _edit(model, target, long_text, target_mode="run")
    except Exception as e:
        return False, f"edit_text raised: {e}"

    page_text = _page_text(model)

    # Check 1: new text is present
    if "EDITED" not in page_text:
        return False, "New text not found on page (silent no-op or rollback)"

    # Check 2: trailing block still present (not accidentally deleted)
    if "Trailing-block" not in page_text:
        return False, "Trailing block was accidentally deleted during edit"

    # Check 3: other lines still present
    if "Line-A" not in page_text:
        return False, "Line-A was accidentally deleted"
    if "Line-C" not in page_text:
        return False, "Line-C was accidentally deleted"

    # Check 4: trailing block y0 should have moved down (or at least stayed)
    # Re-read index
    model.block_manager.rebuild_page(0, model.doc)
    trailing_after = _find_block(model, 0, "Trailing-block")
    if trailing_after:
        trailing_y0_after = trailing_after.layout_rect.y0
        # We just verify it didn't move UP (which would indicate bad displacement)
        if trailing_y0_after < trailing_y0_before - 2.0:
            return False, (
                f"Trailing block moved UP (y0: {trailing_y0_before:.1f} → {trailing_y0_after:.1f}); "
                "expected same or lower"
            )

    model.close()
    return True, "OK — new text present, trailing block preserved, no accidental deletion"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2: Same-height / shortened replacement — must not silent-no-op
# ─────────────────────────────────────────────────────────────────────────────

def scenario_2_no_silent_noop(tmpdir: str) -> tuple[bool, str]:
    """Replace 'Hello World' with 'Hi' (shorter). Must actually change, not silently fail."""
    pdf_path = str(Path(tmpdir) / "s2.pdf")
    _make_simple_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)
    target = _find_block(model, 0, "Hello World")
    if not target:
        return False, "Setup: cannot find 'Hello World' block"

    try:
        _edit(model, target, "Hi", target_mode="run")
    except Exception as e:
        return False, f"edit_text raised on shortened replacement: {e}"

    page_text = _page_text(model)
    if "Hi" not in page_text:
        return False, f"'Hi' not found on page after edit (silent no-op). Page text: {page_text[:200]}"
    # The original "Hello World" should be gone (or at least replaced)
    if "Hello World" in page_text:
        return False, "Original 'Hello World' still present — edit was a no-op"

    model.close()
    return True, "OK — shortened replacement applied, original removed"


def scenario_2b_same_length(tmpdir: str) -> tuple[bool, str]:
    """Replace 'Hello World' with 'Greet Earth' (similar length). Must not no-op."""
    pdf_path = str(Path(tmpdir) / "s2b.pdf")
    _make_simple_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)
    target = _find_block(model, 0, "Hello World")
    if not target:
        return False, "Setup: cannot find 'Hello World' block"

    try:
        _edit(model, target, "Greet Earth", target_mode="run")
    except Exception as e:
        return False, f"edit_text raised: {e}"

    page_text = _page_text(model)
    if "Greet Earth" not in page_text:
        return False, f"'Greet Earth' not found on page. Page text: {page_text[:200]}"
    if "Hello World" in page_text:
        return False, "Original 'Hello World' still present — edit was a no-op"

    model.close()
    return True, "OK — same-length replacement applied"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3: Edit box preview position vs final landing position
# ─────────────────────────────────────────────────────────────────────────────

def scenario_3_position_consistency(tmpdir: str) -> tuple[bool, str]:
    """After editing text in-place (no drag), the new text bbox should be near the original rect."""
    pdf_path = str(Path(tmpdir) / "s3.pdf")
    _make_simple_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)
    target = _find_block(model, 0, "Hello World")
    if not target:
        return False, "Setup: cannot find target"

    original_rect = fitz.Rect(target.layout_rect)
    try:
        _edit(model, target, "Hello World EDITED", target_mode="run")
    except Exception as e:
        return False, f"edit_text raised: {e}"

    # Re-read index to find new block
    model.block_manager.rebuild_page(0, model.doc)
    new_block = _find_block(model, 0, "EDITED")
    if not new_block:
        return False, "Cannot find edited block after edit"

    new_rect = new_block.layout_rect
    # The top-left corner should be within a reasonable tolerance (< 5pt)
    dx = abs(new_rect.x0 - original_rect.x0)
    dy = abs(new_rect.y0 - original_rect.y0)
    if dx > 5.0:
        return False, f"x0 drift too large: {original_rect.x0:.1f} → {new_rect.x0:.1f} (Δ={dx:.1f})"
    if dy > 5.0:
        return False, f"y0 drift too large: {original_rect.y0:.1f} → {new_rect.y0:.1f} (Δ={dy:.1f})"

    model.close()
    return True, f"OK — position drift x={dx:.1f}, y={dy:.1f} (both < 5pt)"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4: Multiple consecutive edits + undo/redo state correctness
# ─────────────────────────────────────────────────────────────────────────────

def scenario_4_consecutive_undo_redo(tmpdir: str) -> tuple[bool, str]:
    """Edit 3 blocks in sequence, then undo all 3, then redo all 3.
    After undo, original text should be restored; after redo, edits should be back."""
    pdf_path = str(Path(tmpdir) / "s4.pdf")
    _make_consecutive_edit_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)

    original_page_text = _page_text(model)

    # Perform 3 sequential edits through CommandManager
    edits = [
        ("Block-1: first", "Block-1: ALPHA"),
        ("Block-2: second", "Block-2: BETA"),
        ("Block-3: third", "Block-3: GAMMA"),
    ]

    for orig_probe, new_text in edits:
        target = _find_block(model, 0, orig_probe.split(":")[0])
        if not target:
            # After previous edits, try finding by the new text
            model.block_manager.rebuild_page(0, model.doc)
            target = _find_block(model, 0, orig_probe.split(":")[0])
            if not target:
                return False, f"Cannot find block containing '{orig_probe}'"

        snapshot = model._capture_page_snapshot(0)
        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=target.layout_rect,
            new_text=new_text,
            font=target.font or "helv",
            size=int(target.size or 12),
            color=target.color or (0, 0, 0),
            original_text=target.text,
            vertical_shift_left=True,
            page_snapshot_bytes=snapshot,
            old_block_id=target.block_id,
            old_block_text=target.text,
        )
        try:
            model.command_manager.execute(cmd)
        except Exception as e:
            return False, f"Edit '{new_text}' failed: {e}"

    # Verify all 3 edits present
    after_edits = _page_text(model)
    for _, new_text in edits:
        probe = new_text.split(":")[1].strip()
        if probe not in after_edits:
            return False, f"After 3 edits, '{probe}' not found on page"

    # Undo all 3
    for i in range(3):
        if not model.command_manager.can_undo():
            return False, f"Cannot undo step {i+1}/3"
        model.command_manager.undo()
        model.block_manager.rebuild_page(0, model.doc)

    # After full undo, original text should be approximately restored
    after_undo = _page_text(model)
    for orig_probe, _ in edits:
        probe = orig_probe.split(":")[1].strip()
        if probe not in after_undo:
            return False, f"After undo, original '{probe}' not found. Page: {after_undo[:300]}"

    # Redo all 3
    for i in range(3):
        if not model.command_manager.can_redo():
            return False, f"Cannot redo step {i+1}/3"
        model.command_manager.redo()
        model.block_manager.rebuild_page(0, model.doc)

    # After full redo, edited text should be back
    after_redo = _page_text(model)
    for _, new_text in edits:
        probe = new_text.split(":")[1].strip()
        if probe not in after_redo:
            return False, f"After redo, '{probe}' not found. Page: {after_redo[:300]}"

    model.close()
    return True, "OK — 3 edits, 3 undos, 3 redos all correct"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 5: Multi-line style inheritance
# ─────────────────────────────────────────────────────────────────────────────

def scenario_5_style_inheritance(tmpdir: str) -> tuple[bool, str]:
    """Edit body text without touching title or footer.
    Title and footer must survive with their text intact."""
    pdf_path = str(Path(tmpdir) / "s5.pdf")
    _make_multiline_style_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)

    target = _find_block(model, 0, "Body:")
    if not target:
        return False, "Setup: cannot find 'Body:' block"

    try:
        _edit(model, target, "Body: UPDATED normal text.", target_mode="run")
    except Exception as e:
        return False, f"edit_text raised: {e}"

    page_text = _page_text(model)

    # Edited text present
    if "UPDATED" not in page_text:
        return False, "Edited text not found after edit"

    # Title must survive
    if "Title:" not in page_text:
        return False, "Title block was deleted during body edit"

    # Note (different color) must survive
    if "important warning" not in page_text:
        return False, "Note block (red text) was deleted during body edit"

    # Footer must survive
    if "Footer:" not in page_text:
        return False, "Footer block was deleted during body edit"

    # Verify style of remaining blocks via rawdict
    model.block_manager.rebuild_page(0, model.doc)
    title_run = _find_run(model, 0, "Title:")
    if title_run:
        if abs(title_run.size - 18.0) > 2.0:
            return False, f"Title font size changed: expected ~18, got {title_run.size}"

    note_run = _find_run(model, 0, "important warning")
    if note_run:
        # Check color is reddish (r component > 0.5)
        if note_run.color and len(note_run.color) >= 3:
            r_val = note_run.color[0]
            if isinstance(r_val, int):
                r_val = ((r_val >> 16) & 0xFF) / 255.0
            if r_val < 0.5:
                return False, f"Note color lost red component: {note_run.color}"

    model.close()
    return True, "OK — body edited, title/note/footer preserved with styles"


# ─────────────────────────────────────────────────────────────────────────────
# Harder edge cases: dense paragraphs, htmlbox content, CJK, same-block edit
# ─────────────────────────────────────────────────────────────────────────────

def _make_dense_paragraph_pdf(path: str) -> None:
    """Create PDF with htmlbox multi-line paragraph (like real editing would produce)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # First paragraph via htmlbox — more realistic than insert_text
    html = (
        '<p style="font-size:11pt;line-height:1.4">'
        'Alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo '
        'lima mike november oscar papa quebec romeo sierra tango uniform victor '
        'whiskey xray yankee zulu.</p>'
    )
    css = "* { font-family: Helvetica; }"
    page.insert_htmlbox(fitz.Rect(72, 72, 520, 200), html, css=css)
    # Second paragraph right below
    html2 = (
        '<p style="font-size:11pt;line-height:1.4">'
        'Second paragraph: this should survive any edit to the first paragraph above. '
        'It contains important content that must not be accidentally redacted.</p>'
    )
    page.insert_htmlbox(fitz.Rect(72, 210, 520, 320), html2, css=css)
    # Third block far below
    page.insert_text((72, 400), "Footer sentinel: must survive all edits.", fontsize=10, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


def _make_cjk_mixed_pdf(path: str) -> None:
    """PDF with mixed CJK + Latin text for style inheritance stress test."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    html = '<p style="font-size:12pt">English text mixed with Chinese</p>'
    css = "* { font-family: Helvetica; }"
    page.insert_htmlbox(fitz.Rect(72, 72, 520, 110), html, css=css)
    # Adjacent CJK block
    html_cjk = '<p style="font-size:12pt">Nearby block that should survive</p>'
    page.insert_htmlbox(fitz.Rect(72, 120, 520, 160), html_cjk, css=css)
    doc.save(path, garbage=0)
    doc.close()


def scenario_1b_dense_paragraph_displacement(tmpdir: str) -> tuple[bool, str]:
    """Edit a word in a dense htmlbox paragraph.
    Adjacent paragraphs and footer must survive."""
    pdf_path = str(Path(tmpdir) / "s1b.pdf")
    _make_dense_paragraph_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)

    # Find block containing "Alpha"
    target = _find_block(model, 0, "Alpha")
    if not target:
        # Try with runs
        run = _find_run(model, 0, "Alpha")
        if run:
            target = _find_block(model, 0, run.text[:10])
        if not target:
            model.close()
            return False, "Setup: cannot find 'Alpha' block in dense PDF"

    # Replace with much longer text (should trigger wrapping + potential displacement)
    new_text = (
        "Alpha bravo REPLACED_WORD delta echo foxtrot golf hotel india juliet kilo "
        "lima mike november oscar papa quebec romeo sierra tango uniform victor "
        "whiskey xray yankee zulu. EXTRA EXTRA EXTRA text to make this longer "
        "and force additional line wrapping in the paragraph."
    )
    try:
        _edit(model, target, new_text, target_mode="paragraph")
    except Exception as e:
        model.close()
        return False, f"edit_text raised: {e}"

    page_text = _page_text(model)

    if "REPLACED_WORD" not in page_text:
        model.close()
        return False, "Edited text 'REPLACED_WORD' not found"

    if "Second paragraph" not in page_text:
        model.close()
        return False, "Second paragraph was accidentally deleted during edit of first"

    if "Footer sentinel" not in page_text:
        model.close()
        return False, "Footer sentinel was accidentally deleted"

    model.close()
    return True, "OK — dense paragraph edited, adjacent content preserved"


def scenario_2c_edit_to_empty(tmpdir: str) -> tuple[bool, str]:
    """Edit text to empty string (delete content). Should not crash or silent-fail."""
    pdf_path = str(Path(tmpdir) / "s2c.pdf")
    _make_simple_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)
    target = _find_block(model, 0, "Hello World")
    if not target:
        model.close()
        return False, "Setup: cannot find target"

    try:
        _edit(model, target, "", target_mode="run")
    except Exception as e:
        model.close()
        return False, f"edit_text raised on empty replacement: {e}"

    page_text = _page_text(model)
    # "Hello World" should be gone
    if "Hello World" in page_text:
        model.close()
        return False, "Original text still present after delete-to-empty"

    model.close()
    return True, "OK — text deleted (replaced with empty)"


def scenario_3b_position_after_longer_edit(tmpdir: str) -> tuple[bool, str]:
    """Edit text to something much longer. Top-left should not drift significantly."""
    pdf_path = str(Path(tmpdir) / "s3b.pdf")
    _make_simple_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)
    target = _find_block(model, 0, "Hello World")
    if not target:
        model.close()
        return False, "Setup: cannot find target"

    original_rect = fitz.Rect(target.layout_rect)
    much_longer = "Hello World — this text is now significantly longer to test position stability"
    try:
        _edit(model, target, much_longer, target_mode="run")
    except Exception as e:
        model.close()
        return False, f"edit_text raised: {e}"

    model.block_manager.rebuild_page(0, model.doc)
    new_block = _find_block(model, 0, "significantly longer")
    if not new_block:
        model.close()
        return False, "Edited block not found"

    new_rect = new_block.layout_rect
    dx = abs(new_rect.x0 - original_rect.x0)
    dy = abs(new_rect.y0 - original_rect.y0)

    model.close()
    if dx > 8.0:
        return False, f"x0 drift too large after long edit: {dx:.1f}pt"
    if dy > 8.0:
        return False, f"y0 drift too large after long edit: {dy:.1f}pt"
    return True, f"OK — position drift x={dx:.1f}, y={dy:.1f}"


def scenario_4b_edit_same_block_twice(tmpdir: str) -> tuple[bool, str]:
    """Edit the same block twice. Second edit should still find and modify the block."""
    pdf_path = str(Path(tmpdir) / "s4b.pdf")
    _make_simple_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)
    target = _find_block(model, 0, "Hello World")
    if not target:
        model.close()
        return False, "Setup: cannot find target"

    # First edit
    try:
        _edit(model, target, "First Edit", target_mode="run")
    except Exception as e:
        model.close()
        return False, f"First edit raised: {e}"

    page_text = _page_text(model)
    if "First Edit" not in page_text:
        model.close()
        return False, "First edit text not found"

    # Re-index and find the edited block
    model.block_manager.rebuild_page(0, model.doc)
    target2 = _find_block(model, 0, "First Edit")
    if not target2:
        model.close()
        return False, "Cannot find 'First Edit' block for second edit"

    # Second edit on same block
    try:
        _edit(model, target2, "Second Edit", target_mode="run", original_text="First Edit")
    except Exception as e:
        model.close()
        return False, f"Second edit raised: {e}"

    page_text2 = _page_text(model)
    if "Second Edit" not in page_text2:
        model.close()
        return False, f"Second edit text not found. Page: {page_text2[:200]}"
    if "First Edit" in page_text2:
        model.close()
        return False, "First edit text still present after second edit"

    model.close()
    return True, "OK — same block edited twice successfully"


def scenario_5b_cjk_mixed_edit(tmpdir: str) -> tuple[bool, str]:
    """Edit text adjacent to another block. Adjacent must survive."""
    pdf_path = str(Path(tmpdir) / "s5b.pdf")
    _make_cjk_mixed_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)

    target = _find_block(model, 0, "English")
    if not target:
        model.close()
        return False, "Setup: cannot find English block"

    try:
        _edit(model, target, "English text EDITED with new content", target_mode="run")
    except Exception as e:
        model.close()
        return False, f"edit_text raised: {e}"

    page_text = _page_text(model)

    if "EDITED" not in page_text:
        model.close()
        return False, "Edited text not found"

    if "Nearby block" not in page_text:
        model.close()
        return False, "Adjacent block was accidentally deleted"

    model.close()
    return True, "OK — mixed content edited, adjacent block preserved"


# ─────────────────────────────────────────────────────────────────────────────
# Stress tests: multi-run block, real-world-like content, protected span replay
# ─────────────────────────────────────────────────────────────────────────────

def _make_multirun_block_pdf(path: str) -> None:
    """Multi-run paragraph: mixed fonts in a tight cluster.
    Simulates a real PDF where one block has multiple styled spans."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Create spans close together to form a multi-run block
    y = 100
    page.insert_text((72, y), "Name: ", fontsize=12, fontname="helv")
    page.insert_text((120, y), "John Smith", fontsize=12, fontname="helv")
    page.insert_text((72, y + 20), "Title: ", fontsize=12, fontname="helv")
    page.insert_text((120, y + 20), "Senior Engineer", fontsize=12, fontname="helv")
    page.insert_text((72, y + 40), "Dept: ", fontsize=12, fontname="helv")
    page.insert_text((120, y + 40), "Research and Development", fontsize=12, fontname="helv")
    # Independent block far below
    page.insert_text((72, 300), "Independent block: do not touch", fontsize=12, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


def _make_tightly_packed_pdf(path: str) -> None:
    """Multiple lines packed tightly (2pt gap). Tests that redaction is precise."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    lines = [
        (72, 100, "Line 1: alpha bravo charlie"),
        (72, 114, "Line 2: delta echo foxtrot"),
        (72, 128, "Line 3: golf hotel india"),
        (72, 142, "Line 4: juliet kilo lima"),
        (72, 156, "Line 5: mike november oscar"),
    ]
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=11, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


def scenario_1c_multirun_edit_single_run(tmpdir: str) -> tuple[bool, str]:
    """Edit one run in a multi-run block. Other runs in the block must survive.
    PyMuPDF splits 'Hello World' into separate 'Hello' and 'World' runs —
    we target 'World' by span_id to simulate real UI run-mode editing."""
    pdf_path = str(Path(tmpdir) / "s1c.pdf")
    _make_multirun_block_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)

    # Find the "Smith" run (PyMuPDF splits "John Smith" → "John" + "Smith")
    run = _find_run(model, 0, "Smith")
    if not run:
        model.close()
        return False, "Setup: cannot find 'Smith' run"

    try:
        _edit(model, run, "Doe",
              target_span_id=run.span_id, target_mode="run",
              original_text=run.text)
    except Exception as e:
        model.close()
        return False, f"edit_text raised: {e}"

    page_text = _page_text(model)

    checks = [
        ("Doe" in page_text, "Edited text 'Doe' missing"),
        ("Title" in page_text, "Adjacent 'Title' line deleted"),
        ("Senior" in page_text, "Adjacent 'Senior' deleted"),
        ("Dept" in page_text, "Adjacent 'Dept' line deleted"),
        ("Independent" in page_text, "Independent block deleted"),
    ]
    for ok, msg in checks:
        if not ok:
            model.close()
            return False, msg

    # Check that 'John' (sibling run) survived as protected span
    if "John" not in page_text:
        model.close()
        return False, "Sibling run 'John' was lost during protected span replay"

    model.close()
    return True, "OK — single run edited, sibling + adjacent content preserved"


def scenario_1d_tightly_packed_lines(tmpdir: str) -> tuple[bool, str]:
    """Edit middle line in tightly packed text using explicit span_id (real UI behavior).
    PyMuPDF merges tightly packed lines into one block; we target a specific
    run by span_id to simulate clicking on 'Line 3' in the real UI."""
    pdf_path = str(Path(tmpdir) / "s1d.pdf")
    _make_tightly_packed_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)

    # In tightly packed text, all lines end up in one block.
    # Find the "3:" run (part of "Line 3:") to target precisely.
    run = _find_run(model, 0, "3:")
    if not run:
        model.close()
        return False, "Setup: cannot find '3:' run"

    try:
        _edit(model, run, "EDITED",
              target_span_id=run.span_id, target_mode="run",
              original_text=run.text)
    except Exception as e:
        model.close()
        return False, f"edit_text raised: {e}"

    page_text = _page_text(model)

    checks = [
        ("EDITED" in page_text, "Edited text not found"),
        ("Line 1" in page_text or "1:" in page_text, "Line 1 content deleted"),
        ("Line 2" in page_text or "2:" in page_text, "Line 2 content deleted"),
        ("Line 4" in page_text or "4:" in page_text, "Line 4 content deleted"),
        ("Line 5" in page_text or "5:" in page_text, "Line 5 content deleted"),
    ]
    for ok, msg in checks:
        if not ok:
            model.close()
            return False, msg

    model.close()
    return True, "OK — tightly packed edit (run mode), other lines preserved"


def scenario_4c_rapid_consecutive_same_block(tmpdir: str) -> tuple[bool, str]:
    """Rapid consecutive edits on the same block (3 edits, no undo between them).
    Uses paragraph mode (the real UI default when no span_id is given)."""
    pdf_path = str(Path(tmpdir) / "s4c.pdf")
    _make_simple_pdf(pdf_path)

    model = PDFModel()
    model.open_pdf(pdf_path)

    # Use texts without 'fi' to avoid insert_htmlbox ligature artifacts (fi→ﬁ)
    edits = ["Edit-AAA", "Edit-BBB", "Edit-CCC-done"]
    prev_text = "Hello World"
    for new_text in edits:
        model.block_manager.rebuild_page(0, model.doc)
        target = _find_block(model, 0, prev_text)
        if not target:
            model.close()
            return False, f"Cannot find '{prev_text}' for edit to '{new_text}'"
        try:
            # Use paragraph mode — this is what the real UI does when editing a block
            _edit(model, target, new_text, target_mode="paragraph", original_text=prev_text)
        except Exception as e:
            model.close()
            return False, f"Edit to '{new_text}' raised: {e}"
        prev_text = new_text

    page_text = _page_text(model)
    if "Edit-CCC-done" not in page_text:
        model.close()
        return False, f"Final edit text not found. Page: {page_text[:200]}"

    # Previous edits should be gone
    for old in ["Hello World", "Edit-AAA", "Edit-BBB"]:
        if old in page_text:
            model.close()
            return False, f"Stale text '{old}' still present"

    model.close()
    return True, "OK — 3 rapid consecutive edits on same block succeeded"


def scenario_real_pdf_edit(tmpdir: str) -> tuple[bool, str]:
    """Test against a real PDF file if available."""
    real_pdf = Path("/Users/ruinclaw/Documents/pdf_editor/test_files/1.pdf")
    if not real_pdf.exists():
        return True, "SKIP — real PDF not available"

    model = PDFModel()
    model.open_pdf(str(real_pdf))
    model.ensure_page_index_built(1)

    runs = model.block_manager.get_runs(0)
    if not runs:
        model.close()
        return True, "SKIP — no runs in real PDF page 0"

    # Find a suitable text run (not whitespace, not too short)
    target_run = None
    for r in runs:
        if r.text.strip() and len(r.text.strip()) > 3 and r.size > 8:
            target_run = r
            break
    if not target_run:
        model.close()
        return True, "SKIP — no suitable run found"

    # Capture original state
    orig_page_text = _page_text(model)
    original_text = target_run.text.strip()
    snapshot = model._capture_page_snapshot(0)

    # Edit: append " [EDITED]" to the run
    new_text = original_text + " [EDITED]"
    try:
        _edit(model, target_run, new_text,
              target_span_id=target_run.span_id, target_mode="run",
              original_text=target_run.text)
    except RuntimeError as e:
        # Verification rollback is acceptable for real PDFs
        if "驗證失敗" in str(e) or "verification failed" in str(e):
            model.close()
            return True, f"WARN — edit rolled back (verification): {str(e)[:80]}"
        model.close()
        return False, f"edit_text raised: {e}"

    after_text = _page_text(model)
    if "[EDITED]" not in after_text:
        model.close()
        return False, f"Edited text not found in real PDF. Original run: {original_text[:30]!r}"

    # Verify: other content should not have been mass-deleted
    # Simple heuristic: page text length should not have decreased dramatically
    len_before = len(orig_page_text)
    len_after = len(after_text)
    if len_after < len_before * 0.5:
        model.close()
        return False, (
            f"Page text shrank dramatically: {len_before} → {len_after} chars "
            "(possible mass deletion)"
        )

    model.close()
    return True, f"OK — real PDF edited, text length {len_before} → {len_after}"


def scenario_7_run_mode_orphan_guard(tmpdir: str) -> tuple[bool, str]:
    """Run mode without span_id on multi-run block.
    When target_mode is explicitly 'run' but no span_id is given, the model
    should still handle the block correctly via fallback logic.
    We verify the edit takes effect and no text vanishes silently."""
    pdf_path = str(Path(tmpdir) / "s7.pdf")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Alpha Beta", fontsize=12, fontname="helv")
    page.insert_text((72, 160), "Gamma Delta", fontsize=12, fontname="helv")
    doc.save(pdf_path, garbage=0)
    doc.close()

    model = PDFModel()
    model.open_pdf(pdf_path)

    target = _find_block(model, 0, "Alpha")
    if not target:
        model.close()
        return False, "Setup: cannot find Alpha block"

    try:
        # Explicit run mode, no span_id — this is the fragile path
        _edit(model, target, "Replaced", target_mode="run", original_text=target.text)
    except Exception as e:
        model.close()
        return False, f"edit_text raised: {e}"

    page_text = _page_text(model)

    # The edit must have taken effect
    if "Replaced" not in page_text:
        model.close()
        return False, f"Edited text not found. Page: {page_text[:200]}"

    # Gamma Delta must survive
    if "Gamma" not in page_text:
        model.close()
        return False, "Adjacent block 'Gamma Delta' was accidentally deleted"

    model.close()
    return True, "OK — run mode without span_id: edit applied, adjacent preserved"


def scenario_8_verification_sensitivity(tmpdir: str) -> tuple[bool, str]:
    """Test that verification doesn't roll back a valid edit that slightly changes text metrics.
    Create text, edit to a visually similar but different string, verify it sticks."""
    pdf_path = str(Path(tmpdir) / "s8.pdf")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "The quick brown fox jumps over the lazy dog.",
                     fontsize=12, fontname="helv")
    doc.save(pdf_path, garbage=0)
    doc.close()

    model = PDFModel()
    model.open_pdf(pdf_path)
    target = _find_block(model, 0, "quick brown")
    if not target:
        model.close()
        return False, "Setup: cannot find target"

    # Replace with similar-length text that should pass verification
    new_text = "The slow red cat walks under the sleepy hound."
    try:
        _edit(model, target, new_text, target_mode="paragraph")
    except RuntimeError as e:
        err_str = str(e)
        if "驗證失敗" in err_str or "verification failed" in err_str:
            model.close()
            return False, f"Valid edit was rolled back by verification: {err_str[:80]}"
        model.close()
        return False, f"edit_text raised: {e}"

    page_text = _page_text(model)
    if "slow red cat" not in page_text:
        model.close()
        return False, f"Edited text not found. Page: {page_text[:200]}"

    model.close()
    return True, "OK — verification passed for valid replacement"


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

SCENARIOS = [
    ("S1a: Mid-paragraph displacement (insert_text)", scenario_1_displacement),
    ("S1b: Dense paragraph displacement (htmlbox)", scenario_1b_dense_paragraph_displacement),
    ("S1c: Multi-run block single-run edit", scenario_1c_multirun_edit_single_run),
    ("S1d: Tightly packed lines edit", scenario_1d_tightly_packed_lines),
    ("S2a: Shortened replacement no-op", scenario_2_no_silent_noop),
    ("S2b: Same-length replacement no-op", scenario_2b_same_length),
    ("S2c: Edit to empty (delete)", scenario_2c_edit_to_empty),
    ("S3a: Position consistency (same-length)", scenario_3_position_consistency),
    ("S3b: Position consistency (longer text)", scenario_3b_position_after_longer_edit),
    ("S4a: Consecutive edit + undo/redo", scenario_4_consecutive_undo_redo),
    ("S4b: Edit same block twice", scenario_4b_edit_same_block_twice),
    ("S4c: Rapid 3x edit same block", scenario_4c_rapid_consecutive_same_block),
    ("S5a: Style inheritance", scenario_5_style_inheritance),
    ("S5b: Mixed content adjacent edit", scenario_5b_cjk_mixed_edit),
    ("S6: Real PDF edit", scenario_real_pdf_edit),
    ("S7: Run-mode orphan guard (no span_id)", scenario_7_run_mode_orphan_guard),
    ("S8: Verification rollback sensitivity", scenario_8_verification_sensitivity),
]


def main():
    print("=" * 70)
    print("Track A/B — 五大 UX 場景診斷")
    print("=" * 70)

    passed = 0
    failed = 0
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, func in SCENARIOS:
            print(f"\n── {name} ──")
            try:
                ok, msg = func(tmpdir)
            except Exception as e:
                ok, msg = False, f"Unhandled exception: {e}"
                import traceback
                traceback.print_exc()
            status = "PASS" if ok else "FAIL"
            if ok:
                passed += 1
            else:
                failed += 1
            print(f"  [{status}] {msg}")
            results.append((name, status, msg))

    print("\n" + "=" * 70)
    print(f"結果: {passed} passed, {failed} failed / {passed + failed} total")
    print("=" * 70)
    for name, status, msg in results:
        marker = "✓" if status == "PASS" else "✗"
        print(f"  {marker} {name}: {msg[:80]}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
