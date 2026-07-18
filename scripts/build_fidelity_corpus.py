#!/usr/bin/env python3
"""Generate synthetic PDF fixtures for the text-commit-engine fidelity suite.

Each PDF exercises a specific decision gate from the tiered commit engine
(plans/2026-07-14-acrobat-parity-text-commit-engine.md §4.2).  The corpus is
generated on the fly — not checked into git (``*.pdf`` is gitignored) — so the
script itself is the canonical corpus definition.

Usage::

    python scripts/build_fidelity_corpus.py [OUTPUT_DIR]

Default output: ``test_corpus/fidelity/``
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

CASES: dict[str, str] = {
    "base14_simple": "base-14 unembedded Type1 fonts (helv, tiro, cour)",
    "embedded_subset": "embedded font via TextWriter (extractable, reloadable)",
    "cjk_identity_h": "CJK text with Identity-H CIDFont/Type0",
    "tj_kerning": "content stream with TJ kerning arrays",
    "rotation": "rotated text (90deg, 180deg) — G4 rejection case",
    "form_xobject": "text inside a Form XObject — G2 rejection case",
    "differences_encoding": "font with /Differences encoding — F3 rejection",
    "type3_font": "Type3 font — F1 rejection case",
    "multi_style": "paragraph with multiple style runs (size + color)",
    "neighbor_proximity": "adjacent text blocks for neighbor-damage testing",
}

_PAGE_W, _PAGE_H = 595, 842  # A4


def _strip_metadata(doc: fitz.Document) -> None:
    doc.set_metadata({})


def _save(doc: fitz.Document, out: Path, name: str) -> Path:
    _strip_metadata(doc)
    path = out / f"{name}.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _build_base14_simple() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    page.insert_text((72, 100), "Helvetica sample text", fontsize=12, fontname="helv")
    page.insert_text((72, 130), "Times Roman sample text", fontsize=12, fontname="tiro")
    page.insert_text((72, 160), "Courier sample text", fontsize=12, fontname="cour")
    return doc


def _build_embedded_subset() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    tw = fitz.TextWriter(page.rect)
    font = fitz.Font("helv")
    tw.append((72, 100), "Hello World embedded font", font=font, fontsize=12)
    tw.write_text(page)
    return doc


def _build_cjk_identity_h() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    tw = fitz.TextWriter(page.rect)
    font = fitz.Font("china-s")
    tw.append((72, 100), "中文測試 CJK Identity-H 一二三", font=font, fontsize=14)
    tw.write_text(page)
    return doc


def _build_tj_kerning() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    page.insert_text((72, 100), "AV kern test", fontsize=14, fontname="helv")
    stream = doc.xref_stream(page.get_contents()[0])
    font_name = "Helv"
    for f in page.get_fonts():
        font_name = f[3]
        break
    tj_block = (
        b"\nBT\n"
        b"/" + font_name.encode() + b" 14 Tf\n"
        b"72 700 Td\n"
        b"[(T) -80 (o) 20 (kern) -60 (ed)] TJ\n"
        b"ET\n"
    )
    new_stream = stream + tj_block
    doc.update_stream(page.get_contents()[0], new_stream)
    return doc


def _build_rotation() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    page.insert_text((72, 200), "Normal text", fontsize=12, fontname="helv")
    page.insert_text((200, 400), "Rotated 90", fontsize=12, fontname="helv", rotate=90)
    page.insert_text(
        (400, 600), "Rotated 180", fontsize=12, fontname="helv", rotate=180
    )
    return doc


def _build_form_xobject() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    page.insert_text((72, 100), "Page-level text", fontsize=12, fontname="helv")

    xobj_rect = fitz.Rect(0, 0, 200, 50)
    font_xref = page.insert_font(fontname="Helv", fontfile=None)

    res_str = f"<< /Font << /F-xobj {font_xref} 0 R >> >>"
    xobj_stream = b"BT /F-xobj 12 Tf 10 30 Td (XObject text inside) Tj ET"
    xobj_xref = doc.get_new_xref()
    doc.update_object(
        xobj_xref,
        f"<< /Type /XObject /Subtype /Form /BBox [{xobj_rect}] "
        f"/Resources {res_str} >>",
    )
    doc.update_stream(xobj_xref, xobj_stream)

    page_contents = page.get_contents()[0]
    old_stream = doc.xref_stream(page_contents)
    invoke = f"\nq 72 650 cm /{_register_xobject(doc, page, xobj_xref)} Do Q\n"
    doc.update_stream(page_contents, old_stream + invoke.encode())

    return doc


def _register_xobject(doc: fitz.Document, page: fitz.Page, xobj_xref: int) -> str:
    name = "FXObj0"
    page_obj = doc.xref_object(page.xref)
    if "/XObject" not in page_obj:
        res_xref_str = doc.xref_get_key(page.xref, "Resources")
        if res_xref_str[0] == "xref":
            res_xref = int(res_xref_str[1].split()[0])
        else:
            res_xref = page.xref
        doc.xref_set_key(
            res_xref, "XObject", f"<< /{name} {xobj_xref} 0 R >>"
        )
    else:
        doc.xref_set_key(
            page.xref, f"Resources/XObject/{name}", f"{xobj_xref} 0 R"
        )
    return name


def _build_differences_encoding() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    page.insert_text((72, 100), "Normal text", fontsize=12, fontname="helv")

    fonts = page.get_fonts(full=True)
    font_xref = fonts[0][0]

    encoding_xref = doc.get_new_xref()
    doc.update_object(
        encoding_xref,
        "<< /Type /Encoding /BaseEncoding /WinAnsiEncoding "
        "/Differences [32 /space 65 /Acustom 66 /Bcustom 67 /Ccustom] >>",
    )
    doc.xref_set_key(font_xref, "Encoding", f"{encoding_xref} 0 R")

    return doc


def _build_type3_font() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)

    char_proc_a_xref = doc.get_new_xref()
    doc.update_object(char_proc_a_xref, "<< >>")
    doc.update_stream(
        char_proc_a_xref,
        b"600 0 0 0 600 800 d1 100 0 500 800 re f",
    )

    char_proc_space_xref = doc.get_new_xref()
    doc.update_object(char_proc_space_xref, "<< >>")
    doc.update_stream(char_proc_space_xref, b"300 0 d0")

    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type3 "
        "/FontBBox [0 0 600 800] "
        "/FontMatrix [0.001 0 0 0.001 0 0] "
        "/FirstChar 32 /LastChar 65 "
        f"/Widths [300 {'0 ' * 32}600] "
        "/Encoding << /Type /Encoding "
        "  /Differences [32 /space 65 /A] >> "
        f"/CharProcs << /A {char_proc_a_xref} 0 R "
        f"  /space {char_proc_space_xref} 0 R >> >>",
    )

    res_xref_str = doc.xref_get_key(page.xref, "Resources")
    if res_xref_str[0] == "xref":
        res_xref = int(res_xref_str[1].split()[0])
    else:
        res_xref = page.xref
    doc.xref_set_key(res_xref, "Font", f"<< /T3F {font_xref} 0 R >>")

    contents_xref = doc.get_new_xref()
    doc.update_object(contents_xref, "<< >>")
    doc.update_stream(contents_xref, b"BT /T3F 24 Tf 72 750 Td (A A) Tj ET")
    doc.xref_set_key(page.xref, "Contents", f"{contents_xref} 0 R")

    return doc


def _build_multi_style() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    page.insert_text(
        (72, 100), "Large bold", fontsize=18, fontname="hebo", color=(1, 0, 0)
    )
    page.insert_text(
        (72, 130), "Small normal", fontsize=10, fontname="helv", color=(0, 0, 1)
    )
    page.insert_text(
        (72, 155), "Medium italic", fontsize=14, fontname="heit", color=(0, 0.5, 0)
    )
    return doc


def _build_neighbor_proximity() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    page.insert_text((72, 100), "BLOCK_A: first text block", fontsize=12, fontname="helv")
    page.insert_text(
        (72, 135), "BLOCK_B: adjacent block", fontsize=12, fontname="helv"
    )
    return doc


_BUILDERS: dict[str, callable] = {
    "base14_simple": _build_base14_simple,
    "embedded_subset": _build_embedded_subset,
    "cjk_identity_h": _build_cjk_identity_h,
    "tj_kerning": _build_tj_kerning,
    "rotation": _build_rotation,
    "form_xobject": _build_form_xobject,
    "differences_encoding": _build_differences_encoding,
    "type3_font": _build_type3_font,
    "multi_style": _build_multi_style,
    "neighbor_proximity": _build_neighbor_proximity,
}


def build_corpus(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, builder in _BUILDERS.items():
        doc = builder()
        paths[name] = _save(doc, output_dir, name)
    return paths


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    out = Path(args[0]) if args else Path("test_corpus/fidelity")
    paths = build_corpus(out)
    for name, path in paths.items():
        print(f"  {name}: {path}")
    print(f"\n{len(paths)} corpus PDFs generated in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
