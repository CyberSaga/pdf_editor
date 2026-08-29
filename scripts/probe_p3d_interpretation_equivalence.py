"""Reproduce the PyMuPDF 1.27.1 premises for P3-D interpretation reuse.

The probe is deliberately independent of production P3-D symbols. It exercises
rotation-faithful raster display lists, derotated text display lists, and the
low-level clipped stext replay needed by :mod:`model.text_commit.interpretation`.
Only aggregate counts are printed and persisted.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

SEED = 0xA93D
RANDOM_CLIPS = 400


@dataclass(frozen=True)
class Fixture:
    name: str
    pdf: bytes


def _assert_runtime() -> None:
    assert fitz.__version__ == "1.27.1", fitz.__version__
    required = (
        "FzCookie",
        "FzRect",
        "FzStextOptions",
        "FzStextPage",
        "fz_close_device",
        "fz_new_stext_device",
        "fz_run_display_list",
    )
    missing = [name for name in required if not hasattr(fitz.mupdf, name)]
    assert not missing, f"missing fitz.mupdf symbols: {missing}"


def _minimal_type3(page: fitz.Page) -> None:
    doc = page.parent
    charproc = doc.get_new_xref()
    doc.update_object(charproc, "<<>>")
    doc.update_stream(charproc, b"0 0 500 700 re f\n")
    font = doc.get_new_xref()
    doc.update_object(
        font,
        "<< /Type /Font /Subtype /Type3 /FontBBox [0 0 500 700] "
        "/FontMatrix [0.001 0 0 0.001 0 0] /CharProcs "
        f"<< /A {charproc} 0 R >> /Encoding << /Type /Encoding "
        "/Differences [65 /A] >> /FirstChar 65 /LastChar 65 /Widths [500] "
        "/Resources << >> >>",
    )
    content = doc.get_new_xref()
    doc.update_object(content, "<<>>")
    doc.update_stream(content, b"BT /T3 28 Tf 72 110 Td (A) Tj ET\n")
    doc.xref_set_key(page.xref, "Contents", f"{content} 0 R")
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /T3 {font} 0 R >> >>")


def _fixture(
    name: str,
    *,
    width: float = 595,
    height: float = 842,
    rotate: int = 0,
    user_unit: float | None = None,
    cropbox: tuple[float, float, float, float] | None = None,
    inherited_rotation: bool = False,
    type0: bool = False,
    type3: bool = False,
    visible_oc: bool = False,
    hidden_oc: bool = False,
    rotated_tm: bool = False,
    off_page_text: bool = False,
    free_text: bool = False,
    apless_annot: bool = False,
    big_glyph: bool = False,
) -> Fixture:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    if type3:
        _minimal_type3(page)
    else:
        fontname = "china-s" if type0 else "helv"
        text = "\u4e2d\u6587 Identity H" if type0 else "P3D Digits ABC 0123456789"
        oc = 0
        if visible_oc or hidden_oc:
            oc = doc.add_ocg("p3d-oc", on=visible_oc)
        if rotated_tm:
            page.insert_text((80, 140), text, fontname=fontname, fontsize=16, rotate=90, oc=oc)
        else:
            page.insert_text((72, 110), text, fontname=fontname, fontsize=16, oc=oc)
        page.insert_text((70, 190), "Boundary AZ09", fontsize=52 if big_glyph else 13)
        if off_page_text:
            page.insert_text((-40, -20), "off-media", fontsize=12)
            page.insert_text((width + 20, height + 20), "off-crop", fontsize=12)
    if free_text:
        page.add_freetext_annot(fitz.Rect(100, 210, 260, 260), "FreeText P3D")
    if apless_annot:
        annot = page.add_rect_annot(fitz.Rect(280, 80, 340, 140))
        doc.xref_set_key(annot.xref, "AP", "null")
    if user_unit is not None:
        doc.xref_set_key(page.xref, "UserUnit", str(user_unit))
    if cropbox is not None:
        doc.xref_set_key(page.xref, "CropBox", "[" + " ".join(map(str, cropbox)) + "]")
    if inherited_rotation:
        kind, parent_ref = doc.xref_get_key(page.xref, "Parent")
        assert kind == "xref"
        parent_xref = int(parent_ref.split()[0])
        doc.xref_set_key(parent_xref, "Rotate", str(rotate))
        doc.xref_set_key(page.xref, "Rotate", "null")
    elif rotate:
        page.set_rotation(rotate)
    data = doc.tobytes(garbage=0, deflate=False)
    doc.close()
    return Fixture(name, data)


def _fixtures() -> list[Fixture]:
    return [
        _fixture("plain-a4"),
        _fixture("plain-letter", width=612, height=792),
        _fixture("rotate-90", rotate=90),
        _fixture("rotate-180", rotate=180),
        _fixture("rotate-270", rotate=270),
        _fixture("crop-fraction-rotate-90", rotate=90, cropbox=(10.25, 20.5, 560.75, 800.25)),
        _fixture("userunit-2.5-rotate-90", rotate=90, user_unit=2.5),
        _fixture("userunit-2.5-rotate-270", rotate=270, user_unit=2.5),
        _fixture("userunit-0.4-rotate-180", rotate=180, user_unit=0.4),
        _fixture("userunit-crop-rotate-270", rotate=270, user_unit=2.5, cropbox=(11.25, 9.5, 560.5, 800.75)),
        _fixture("big-glyph-straddle", big_glyph=True),
        _fixture("type0-visible-oc", type0=True, visible_oc=True),
        _fixture("type0-hidden-oc", type0=True, hidden_oc=True),
        _fixture("rotated-tm", rotated_tm=True),
        _fixture("type0-rotate-270", type0=True, rotate=270),
        _fixture("off-media-crop", cropbox=(20.5, 30.25, 570.5, 810.75), off_page_text=True),
        _fixture("inherited-rotate-90", rotate=90, inherited_rotation=True),
        _fixture("type3", type3=True),
        _fixture("apless-annot-rotate-90", rotate=90, apless_annot=True),
        _fixture("freetext-annot", free_text=True),
    ]


def _text_displaylist(page: fitz.Page) -> fitz.DisplayList:
    old_rotation = page.rotation
    try:
        if old_rotation:
            page.set_rotation(0)
        return page.get_displaylist(annots=True)
    finally:
        if old_rotation:
            page.set_rotation(old_rotation)


def _rawdict_from_displaylist(page: fitz.Page, displaylist: fitz.DisplayList) -> dict[str, Any]:
    raw_page = displaylist.get_textpage(fitz.TEXTFLAGS_RAWDICT)
    textpage = fitz.TextPage(raw_page)
    textpage.parent = weakref.proxy(page)
    return page.get_text("rawdict", textpage=textpage)


def _clipped_text_from_displaylist(
    displaylist: fitz.DisplayList,
    clip: fitz.Rect,
    *,
    matrix: fitz.Matrix = fitz.Identity,
) -> str:
    options = fitz.mupdf.FzStextOptions()
    options.flags = fitz.TEXTFLAGS_TEXT
    raw_page = fitz.mupdf.FzStextPage(fitz.JM_rect_from_py(clip))
    device = fitz.mupdf.fz_new_stext_device(raw_page, options)
    try:
        fitz.mupdf.fz_run_display_list(
            displaylist.this,
            device,
            fitz.JM_matrix_from_py(matrix),
            fitz.mupdf.FzRect(fitz.mupdf.FzRect.Fixed_INFINITE),
            fitz.mupdf.FzCookie(),
        )
    finally:
        fitz.mupdf.fz_close_device(device)
    return fitz.TextPage(raw_page).extractText()


def _pixmap_signature(pixmap: fitz.Pixmap) -> tuple[Any, ...]:
    return (
        tuple(pixmap.irect),
        pixmap.width,
        pixmap.height,
        pixmap.stride,
        pixmap.n,
        pixmap.alpha,
        pixmap.xres,
        pixmap.yres,
        bytes(pixmap.samples),
        pixmap.tobytes("png"),
    )


def _clip_cases(page: fitz.Page, rng: random.Random) -> list[fitz.Rect]:
    rect = page.rect
    clips = [fitz.Rect(rect), fitz.Rect(rect.x0, rect.y0, rect.x0 + rect.width / 2, rect.y0 + rect.height / 2)]
    for _ in range(20):
        x0 = rng.uniform(rect.x0 - 5, rect.x1 + 5)
        y0 = rng.uniform(rect.y0 - 5, rect.y1 + 5)
        x1 = x0 + rng.uniform(0.1, max(0.2, rect.width / 2))
        y1 = y0 + rng.uniform(0.1, max(0.2, rect.height / 2))
        clips.append((fitz.Rect(x0, y0, x1, y1) & rect).normalize())
    return [clip for clip in clips if not clip.is_empty]


def run_probe() -> dict[str, Any]:
    _assert_runtime()
    rng = random.Random(SEED)
    fixtures = _fixtures()
    counts = {
        "fixtures": len(fixtures),
        "raster_equal": 0,
        "rawdict_equal": 0,
        "clipped_text_equal": 0,
        "random_clips": 0,
        "boundary_clips": 0,
        "apless_independent_first_render_equal": 0,
        "negative_raster_mismatches": 0,
        "negative_clip_rotate90_mismatches": 0,
        "negative_clip_rotate270_mismatches": 0,
    }
    raster_negative_legs = 0
    for fixture in fixtures:
        doc = fitz.open("pdf", fixture.pdf)
        page = doc[0]
        raster_list = page.get_displaylist(annots=True)
        direct = page.get_pixmap(dpi=96, annots=True)
        replay = raster_list.get_pixmap(matrix=fitz.Matrix(96 / 72, 96 / 72), colorspace=fitz.csRGB, alpha=False)
        replay.set_dpi(96, 96)
        assert _pixmap_signature(direct) == _pixmap_signature(replay), fixture.name
        counts["raster_equal"] += 1

        text_list = _text_displaylist(page)
        assert page.get_text("rawdict") == _rawdict_from_displaylist(page, text_list), fixture.name
        counts["rawdict_equal"] += 1

        for clip in _clip_cases(page, rng):
            dict_clip = (clip * page.derotation_matrix).normalize()
            direct_text = page.get_text("text", clip=dict_clip)
            replay_text = _clipped_text_from_displaylist(text_list, dict_clip)
            assert direct_text == replay_text, (fixture.name, tuple(clip))
            counts["clipped_text_equal"] += 1

        if page.rotation in (90, 180, 270) and (
            "crop" in fixture.name or "userunit" in fixture.name
        ):
            raster_negative_legs += 1
            wrong = text_list.get_pixmap(
                matrix=page.rotation_matrix * fitz.Matrix(96 / 72, 96 / 72),
                colorspace=fitz.csRGB,
                alpha=False,
            )
            if _pixmap_signature(direct) != _pixmap_signature(wrong):
                counts["negative_raster_mismatches"] += 1

        if page.rotation in (90, 270):
            # Replaying a rotation-baked list through another quarter-turn
            # transform makes stext mediabox clipping transformation-sensitive.
            # This is the rejected construction: the accepted helper instead
            # uses the derotated text list with an identity CTM.
            dict_clip = fitz.Rect(40, 40, 300, 180) & page.cropbox
            wrong_text = _clipped_text_from_displaylist(
                raster_list, dict_clip, matrix=page.rotation_matrix
            )
            direct_text = page.get_text("text", clip=dict_clip)
            if wrong_text != direct_text:
                key = f"negative_clip_rotate{page.rotation}_mismatches"
                counts[key] += 1
        doc.close()

    # The acceptance contract requires at least 380 seeded random clips.
    fuzz = fitz.open("pdf", fixtures[0].pdf)
    page = fuzz[0]
    text_list = _text_displaylist(page)
    for _ in range(RANDOM_CLIPS):
        rect = page.rect
        x0 = rng.uniform(rect.x0, rect.x1 - 0.1)
        y0 = rng.uniform(rect.y0, rect.y1 - 0.1)
        clip = fitz.Rect(
            x0,
            y0,
            rng.uniform(x0 + 0.1, rect.x1),
            rng.uniform(y0 + 0.1, rect.y1),
        )
        assert page.get_text("text", clip=clip) == _clipped_text_from_displaylist(text_list, clip)
        counts["random_clips"] += 1

    # 0.1-point digits/capitals boundary sweep around known text geometry.
    chars = [
        ch
        for block in page.get_text("rawdict")["blocks"]
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        for ch in span.get("chars", [])
        if ch["c"].isdigit() or ch["c"].isupper()
    ]
    for ch in chars:
        bbox = fitz.Rect(ch["bbox"])
        for delta in (-0.2, -0.1, 0.0, 0.1, 0.2):
            clip = fitz.Rect(bbox.x0 + delta, bbox.y0, bbox.x1 + delta, bbox.y1)
            assert page.get_text("text", clip=clip) == _clipped_text_from_displaylist(text_list, clip)
            counts["boundary_clips"] += 1
    fuzz.close()

    apless = next(item for item in fixtures if item.name == "apless-annot-rotate-90")
    doc_a = fitz.open("pdf", apless.pdf)
    doc_b = fitz.open("pdf", apless.pdf)
    assert _pixmap_signature(doc_a[0].get_pixmap()) == _pixmap_signature(doc_b[0].get_pixmap())
    counts["apless_independent_first_render_equal"] = 1
    doc_a.close()
    doc_b.close()

    assert counts["random_clips"] >= 380
    assert counts["negative_raster_mismatches"] >= 1, (
        counts["negative_raster_mismatches"], raster_negative_legs
    )
    assert counts["negative_clip_rotate90_mismatches"] >= 1
    assert counts["negative_clip_rotate270_mismatches"] >= 1
    return {
        "probe": "p3d-interpretation-equivalence",
        "pymupdf": fitz.__version__,
        "seed": SEED,
        "acceptance": "PASS",
        "counts": counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ROOT / "benchmarks" / "p3d-interpretation-equivalence.json",
    )
    args = parser.parse_args()
    report = run_probe()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"report: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
