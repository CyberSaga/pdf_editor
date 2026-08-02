"""Characterization tests for the legacy text-commit path.

Each test asserts the *intended* Acrobat-stable behavior defined in
plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md and is marked
``xfail(strict=True)``: today's redact+reinsert engine demonstrably fails
it.  If one of these starts passing (XPASS -> suite failure), the legacy
engine's behavior changed and the marker must be consciously removed —
that is the point: silent behavior drift in the commit path is never OK.

These are the permanent regression net for the V2 engine rollout; they run
the legacy engine (default flag) and must keep failing until the tiered
engine is enabled for the covered case.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.pdf_text_edit as pdf_text_edit_module  # noqa: E402
from model.edit_commands import EditTextResult  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402


def _open_model(pdf_path: Path) -> PDFModel:
    model = PDFModel()
    model.open_pdf(str(pdf_path))
    model.ensure_page_index_built(1)
    return model


def _find_block(model: PDFModel, probe: str):
    for block in model.block_manager.get_blocks(0):
        if probe in (block.text or ""):
            return block
    raise AssertionError(f"no block containing {probe!r}")


def _edit(model: PDFModel, probe: str, new_text: str, **kwargs) -> EditTextResult:
    block = _find_block(model, probe)
    return model.edit_text(
        1,
        fitz.Rect(block.layout_rect),
        new_text,
        original_text=block.text,
        **kwargs,
    )


def _page_font_types(page: fitz.Page) -> set[str]:
    return {entry[2] for entry in page.get_fonts(full=True)}


def _span_fonts_containing(page: fitz.Page, probe: str) -> set[str]:
    fonts: set[str] = set()
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if probe in span["text"]:
                    fonts.add(span["font"])
    return fonts


@pytest.fixture()
def embedded_font_pdf(tmp_path: Path) -> Path:
    """A page whose only font is an embedded Type0 face (via TextWriter)."""
    pdf_path = tmp_path / "embedded.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    writer = fitz.TextWriter(page.rect)
    writer.append((72, 100), "Alpha embedded line", font=fitz.Font("helv"), fontsize=12)
    writer.write_text(page)
    doc.save(str(pdf_path), garbage=0)
    doc.close()
    return pdf_path


@pytest.fixture()
def base14_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "base14.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=12.0, fontname="helv")
    doc.save(str(pdf_path), garbage=0)
    doc.close()
    return pdf_path


@pytest.mark.xfail(
    strict=True,
    reason="legacy commit reinserts via a Base-14 alias instead of reusing the "
    "embedded font resource (plan V2: no silent substitution)",
)
def test_unchanged_style_preserves_embedded_font_resource(embedded_font_pdf: Path):
    """Editing text without touching style must not add substitute font resources.

    Intended (V2): the edited run keeps being served by the original embedded
    Type0 resource; the page's font-resource type set is unchanged.
    """
    model = _open_model(embedded_font_pdf)
    try:
        types_before = _page_font_types(model.doc[0])
        assert types_before == {"Type0"}

        result = _edit(model, "Alpha embedded", "Alpha embedded lines")
        assert result is EditTextResult.SUCCESS

        types_after = _page_font_types(model.doc[0])
        assert types_after == types_before, (
            f"font resources changed: {types_before} -> {types_after}"
        )
    finally:
        model.close()


@pytest.mark.xfail(
    strict=True,
    reason="edit_text takes scalar font/size/color as style truth, so an alias "
    "the user never chose replaces the original family and the verifier "
    "accepts it (plan V2: StyleOverrides + font-outcome honesty)",
)
def test_untouched_font_control_keeps_original_family(base14_pdf: Path):
    """A font value the user never touched must not replace the original family.

    The legacy API cannot distinguish "user typed text" from "user restyled":
    whatever alias the view sends becomes the committed font, and
    _verify_rebuild_edit still reports SUCCESS (it only checks text
    similarity).  Intended (V2): with no explicit style override the committed
    family stays Helvetica, and any substitution is a reported outcome.
    """
    model = _open_model(base14_pdf)
    try:
        result = _edit(model, "Hello World", "Hello Worlds", font="cour")
        assert result is EditTextResult.SUCCESS

        fonts = _span_fonts_containing(model.doc[0], "Hello Worlds")
        assert fonts, "edited text not found after commit"
        assert all("helvetica" in f.lower() for f in fonts), (
            f"family replaced without an explicit user override: {fonts}"
        )
    finally:
        model.close()


@pytest.mark.xfail(
    strict=True,
    reason="fast insert_text commits and htmlbox commits draw different pixels "
    "for the same edit; the preview always uses htmlbox, so preview and a "
    "fast-path commit diverge (plan V2: preview renders the committed plan)",
)
def test_fast_and_htmlbox_commits_render_identically(tmp_path: Path, monkeypatch):
    """The two legacy insert engines must produce identical pixels for one edit.

    The editor preview is always rendered with the htmlbox engine while the
    commit may take the fast insert_text path, so any pixel difference between
    the two engines is exactly the preview/commit divergence users see.
    """

    def _render_after_forced_path(path_choice: str) -> bytes:
        pdf_path = tmp_path / f"render_{path_choice}.pdf"
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Hello World", fontsize=12.0, fontname="helv")
        doc.save(str(pdf_path), garbage=0)
        doc.close()

        model = _open_model(pdf_path)
        try:
            monkeypatch.setattr(
                pdf_text_edit_module,
                "_classify_insert_path",
                lambda **kwargs: path_choice,
            )
            result = _edit(model, "Hello World", "Hello Worlds")
            assert result is EditTextResult.SUCCESS
            return model.doc[0].get_pixmap(dpi=96).samples
        finally:
            model.close()

    fast_pixels = _render_after_forced_path("fast")
    htmlbox_pixels = _render_after_forced_path("htmlbox")
    assert fast_pixels == htmlbox_pixels


@pytest.mark.xfail(
    strict=True,
    reason="overflow growth triggers _push_down_overlapping_text, which redacts "
    "and re-inserts neighbor blocks (plan V2: neighbors never move)",
)
def test_commit_never_moves_neighbor_blocks(tmp_path: Path):
    """Committing a growing edit must leave untouched neighbor text in place."""
    pdf_path = tmp_path / "neighbors.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Short target line.", fontsize=12.0, fontname="helv")
    page.insert_text((72, 140), "NEIGHBOR anchor text", fontsize=12.0, fontname="helv")
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    def _neighbor_origin(page: fitz.Page) -> fitz.Point:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    if "NEIGHBOR" in span["text"]:
                        return fitz.Point(span["origin"])
        raise AssertionError("neighbor span not found")

    model = _open_model(pdf_path)
    try:
        origin_before = _neighbor_origin(model.doc[0])
        long_text = (
            "This replacement text is deliberately long enough to wrap onto "
            "several committed lines inside the paragraph box so that the "
            "legacy engine estimates vertical growth beyond the redacted "
            "rectangle and activates its pre-push displacement of every text "
            "block that sits below the edited paragraph on this page."
        )
        result = _edit(model, "Short target", long_text)
        assert result is EditTextResult.SUCCESS

        origin_after = _neighbor_origin(model.doc[0])
        assert abs(origin_after.x - origin_before.x) <= 0.1
        assert abs(origin_after.y - origin_before.y) <= 0.1, (
            f"neighbor moved {origin_after.y - origin_before.y:+.2f}pt vertically"
        )
    finally:
        model.close()


@pytest.mark.xfail(
    strict=True,
    reason="insert_htmlbox re-breaks the paragraph inside a widened box, so a "
    "one-word edit rewrites every line break (plan V2: reflow only within "
    "the original paragraph box at its original width)",
)
def test_paragraph_edit_preserves_original_line_breaks(tmp_path: Path):
    """Editing one word of a multi-line paragraph must keep its line structure.

    Today the legacy engine widens the insert box up to the page's safe right
    margin and lets MuPDF's HTML engine re-break the text, so a 3-line
    paragraph commits as a single long line — the "layout jumps around"
    symptom.  Intended (V2): same line count, same first word on each line.
    """
    original_lines = [
        "The quick brown fox jumps",
        "over the lazy dog while",
        "carrying a heavy basket",
    ]
    pdf_path = tmp_path / "para.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for i, line in enumerate(original_lines):
        page.insert_text((72, 100 + 14 * i), line, fontsize=12.0, fontname="helv")
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = _open_model(pdf_path)
    try:
        block = _find_block(model, "quick brown")
        replacement = (block.text or "").replace("heavy", "light")
        result = _edit(model, "quick brown", replacement)
        assert result is EditTextResult.SUCCESS

        committed_lines: list[str] = []
        for blk in model.doc[0].get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                text = "".join(span["text"] for span in line["spans"]).strip()
                if text:
                    committed_lines.append(text)
        assert len(committed_lines) == len(original_lines), (
            f"line structure changed: {len(original_lines)} lines -> "
            f"{len(committed_lines)}: {committed_lines}"
        )
        for committed, original in zip(committed_lines, original_lines):
            assert committed.split()[0] == original.split()[0]
    finally:
        model.close()
