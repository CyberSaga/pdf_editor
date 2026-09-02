"""Fixture mutators and raster oracles for the P4-B2 painter-geometry spike.

Everything here builds on :mod:`test_scripts.type0_fixture_builder` and the
two-painter page of ``test_text_commit_duplicate_painter_gate``.  Nothing
derives from a real document; nothing is written to disk.

The raster oracle (O4 in the spike plan) is the one ground truth every
other geometry oracle is measured against: two single-painter renders of
the same page, each with the OTHER painter switched to ``3 Tr`` (invisible,
still advancing), intersected pixel-wise at 8x (576 dpi).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.inspect import read_page_streams  # noqa: E402
from model.text_commit.replay import ShowOp, replay_page_streams  # noqa: E402
from test_scripts.type0_fixture_builder import (  # noqa: E402
    Type0Fixture,
    _descendant_xref_of,
    _set_page_xobject,
    cid_for,
    encode_cids,
    install_oc_layer,
    write_minimal_tounicode,
)

RASTER_SCALE = 8  # 576 dpi: one device pixel is 1/8 pt
INK_THRESHOLD = 128  # grey level below which a pixel counts as ink


@dataclass(frozen=True)
class InkMask:
    """One rendered clip as a packed ink bitmap (1 = ink)."""

    clip: tuple[float, float, float, float]
    width: int
    height: int
    bits: int

    @property
    def ink_pixels(self) -> int:
        return bin(self.bits).count("1")

    def overlap_pixels(self, other: InkMask) -> int:
        assert (self.width, self.height, self.clip) == (
            other.width,
            other.height,
            other.clip,
        ), "ink masks must share a clip"
        return bin(self.bits & other.bits).count("1")

    def bbox_pt(self) -> tuple[float, float, float, float] | None:
        """Axis-aligned bounds of the ink in page points, or ``None``."""
        if not self.bits:
            return None
        width = self.width
        total = width * self.height
        packed = self.bits.to_bytes(total, "big")
        xs: list[int] = []
        ys: list[int] = []
        for y in range(self.height):
            row = packed[y * width : (y + 1) * width]
            if not any(row):
                continue
            ys.append(y)
            xs.append(row.index(1))
            xs.append(width - 1 - row[::-1].index(1))
        x0, y0 = self.clip[0], self.clip[1]
        return (
            x0 + min(xs) / RASTER_SCALE,
            y0 + min(ys) / RASTER_SCALE,
            x0 + (max(xs) + 1) / RASTER_SCALE,
            y0 + (max(ys) + 1) / RASTER_SCALE,
        )


def render_ink_mask(
    page: fitz.Page, clip: tuple[float, float, float, float]
) -> InkMask:
    """Render ``clip`` of ``page`` at :data:`RASTER_SCALE` into an ink mask.

    Anti-aliasing stays at PyMuPDF's default (8 bits); the plan records
    the level so containment tolerances stay honest.
    """
    rect = fitz.Rect(*clip)
    pix = page.get_pixmap(
        matrix=fitz.Matrix(RASTER_SCALE, RASTER_SCALE),
        clip=rect,
        colorspace=fitz.csGRAY,
        alpha=False,
    )
    samples = pix.samples
    table = bytes(1 if value < INK_THRESHOLD else 0 for value in range(256))
    packed = samples.translate(table)
    return InkMask(
        clip=clip,
        width=pix.width,
        height=pix.height,
        bits=int.from_bytes(packed, "big"),
    )


def _with_stream(
    fixture: Type0Fixture, stream: bytes, clip: tuple[float, float, float, float]
) -> InkMask:
    original = fixture.content_bytes()
    fixture.doc.update_stream(fixture.content_xref, stream)
    try:
        return render_ink_mask(fixture.page, clip)
    finally:
        fixture.doc.update_stream(fixture.content_xref, original)


def two_painter_clip(
    fixture: Type0Fixture, *, pad: float = 80.0
) -> tuple[float, float, float, float]:
    """A page-space clip around the first painter wide enough for a twin
    placed within ``pad`` points of it on either side."""
    height = fixture.page.rect.height
    ox, oy = fixture.origin
    x0 = max(0.0, ox - pad)
    x1 = min(fixture.page.rect.width, ox + pad + len(fixture.text) * fixture.fontsize)
    y_page = height - oy
    return (x0, max(0.0, y_page - 3 * fixture.fontsize), x1, min(height, y_page + 2 * fixture.fontsize))


def single_painter_masks(
    fixture: Type0Fixture,
    *,
    clip: tuple[float, float, float, float] | None = None,
) -> tuple[InkMask, InkMask]:
    """Ink of painter 1 alone and painter 2 alone on a two-painter page.

    The page must have the ``_build_second_show_doc`` shape: one ``BT``,
    the first ``Tj`` followed by ``/<resource>`` for the second painter.
    The hidden painter is wrapped in ``3 Tr`` so its text state (and any
    cursor advance) still executes exactly as in the two-painter page.
    """
    stream = fixture.content_bytes()
    marker = b"> Tj /"
    assert stream.count(marker) == 1, "not a two-painter page"
    assert stream.count(b"BT ") == 1, "expected a single BT"
    clip = clip or two_painter_clip(fixture)
    first_only = stream.replace(marker, b"> Tj 3 Tr /", 1)
    second_only = stream.replace(b"BT ", b"BT 3 Tr ", 1).replace(
        marker, b"> Tj 0 Tr /", 1
    )
    return _with_stream(fixture, first_only, clip), _with_stream(
        fixture, second_only, clip
    )


def painters_overlap_pixels(fixture: Type0Fixture) -> int:
    """Pixels where painter 1's ink and painter 2's ink coincide."""
    first, second = single_painter_masks(fixture)
    return first.overlap_pixels(second)


def glyph_ink_clip(
    fixture: Type0Fixture, *, pad: float = 0.5
) -> tuple[float, float, float, float]:
    """A page-space clip around a single-show page's authored origin,
    ``pad`` em on every side of the em box."""
    height = fixture.page.rect.height
    ox, oy = fixture.origin
    size = fixture.fontsize
    span = (len(fixture.encoded) // 2 + 1) * size
    return (
        max(0.0, ox - pad * size),
        max(0.0, height - oy - (1.0 + pad) * size),
        min(fixture.page.rect.width, ox + span + pad * size),
        min(height, height - oy + (0.5 + pad) * size),
    )


# ---------------------------------------------------------------- mutators
#
# Every helper below edits the fixture's own content stream or page object
# in place (xref surgery, like ``type0_fixture_builder``'s mutators) so the
# resulting page is a real, parser-normalized shape the devices replay.


def replay_shows(fixture: Type0Fixture) -> tuple[ShowOp, ...]:
    """Every ShowOp of the fixture page, under the diagnostic (unbounded)
    replay budget the census uses."""
    streams = read_page_streams(fixture.doc, fixture.page)
    return replay_page_streams(streams, max_decoded_bytes=None).shows


def first_show(fixture: Type0Fixture) -> ShowOp:
    shows = replay_shows(fixture)
    assert shows, "fixture page replays no show"
    return shows[0]


def set_page_boxes(
    fixture: Type0Fixture,
    *,
    mediabox: tuple[float, float, float, float] | None = None,
    cropbox: tuple[float, float, float, float] | None = None,
) -> None:
    """Rewrite ``/MediaBox`` and/or ``/CropBox`` on the page object."""
    for key, box in (("MediaBox", mediabox), ("CropBox", cropbox)):
        if box is not None:
            literal = "[" + " ".join(f"{v:g}" for v in box) + "]"
            fixture.doc.xref_set_key(fixture.page.xref, key, literal)


def set_user_unit(fixture: Type0Fixture, value: float) -> None:
    fixture.doc.xref_set_key(fixture.page.xref, "UserUnit", f"{value:g}")


def _authored_prefix(fixture: Type0Fixture) -> bytes:
    return f"BT /{fixture.resource_name} {fixture.fontsize:g} Tf ".encode("ascii")


def set_text_state(
    fixture: Type0Fixture,
    *,
    hscale: float | None = None,
    char_spacing: float | None = None,
    word_spacing: float | None = None,
    rise: float | None = None,
    render_mode: int | None = None,
) -> None:
    """Insert text-state operators right after the authored ``Tf``.

    They precede the authored ``Tm`` and apply to the FIRST show only when
    the page is a two-painter page (the second painter sets its own state).
    """
    stream = fixture.content_bytes()
    prefix = _authored_prefix(fixture)
    assert stream.count(prefix) == 1, "fixture stream lost its authored Tf"
    ops = []
    if hscale is not None:
        ops.append(f"{hscale:g} Tz")
    if char_spacing is not None:
        ops.append(f"{char_spacing:g} Tc")
    if word_spacing is not None:
        ops.append(f"{word_spacing:g} Tw")
    if rise is not None:
        ops.append(f"{rise:g} Ts")
    if render_mode is not None:
        ops.append(f"{render_mode:d} Tr")
    inserted = prefix + (" ".join(ops) + " ").encode("ascii")
    fixture.doc.update_stream(
        fixture.content_xref, stream.replace(prefix, inserted, 1)
    )


def set_show_cids(fixture: Type0Fixture, cids: tuple[int, ...]) -> None:
    """Replace the authored hex operand with arbitrary CIDs (no ToUnicode
    requirement: the devices never consult the CMap)."""
    stream = fixture.content_bytes()
    old = f"<{fixture.encoded.hex().upper()}>".encode("ascii")
    assert stream.count(old) >= 1, "authored operand missing"
    new = ("<" + "".join(f"{cid:04X}" for cid in cids) + ">").encode("ascii")
    fixture.doc.update_stream(fixture.content_xref, stream.replace(old, new, 1))
    fixture.encoded = b"".join(cid.to_bytes(2, "big") for cid in cids)


def replace_show_with_tj(
    fixture: Type0Fixture, items: list[float | str]
) -> None:
    """Rewrite the authored ``<hex> Tj`` as ``[ ... ] TJ``.

    ``str`` items are encoded with the builder's CIDs; numbers are kerns in
    thousandths of text space (positive moves the cursor LEFT).
    """
    stream = fixture.content_bytes()
    old = f"<{fixture.encoded.hex().upper()}> Tj".encode("ascii")
    assert stream.count(old) == 1, "authored show missing"
    parts = []
    for item in items:
        if isinstance(item, str):
            parts.append(f"<{encode_cids(item).hex().upper()}>")
        else:
            parts.append(f"{item:g}")
    new = ("[" + " ".join(parts) + "] TJ").encode("ascii")
    fixture.doc.update_stream(fixture.content_xref, stream.replace(old, new, 1))


def map_cid_to_two_codepoints(
    fixture: Type0Fixture, cid: int, text: str = "ab"
) -> None:
    """ToUnicode: ``cid`` maps to a two-codepoint string (the continuation
    item shape in MuPDF's text spans); every other fixture char is kept."""
    mappings = [
        (cid_for(char), char) for char in fixture.text if cid_for(char) != cid
    ]
    mappings.append((cid, text))
    write_minimal_tounicode(fixture, mappings)


def install_text_form_xobject(
    fixture: Type0Fixture,
    *,
    name: str,
    text: str,
    fontsize: float,
    origin: tuple[float, float],
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 595.0, 842.0),
) -> int:
    """Register a Form XObject showing ``text`` with the fixture font at
    ``origin`` (PDF user space) as ``/<name>``.  Caller invokes it with
    ``/<name> Do`` via ``type0_fixture_builder.append_page_content``.
    Replay never descends into it, so its glyphs reach the devices with no
    ShowOp: the V0d blind spot the join must survive."""
    doc = fixture.doc
    form_xref = doc.get_new_xref()
    x0, y0, x1, y1 = bbox
    doc.update_object(
        form_xref,
        "<< /Type /XObject /Subtype /Form "
        f"/BBox [{x0:g} {y0:g} {x1:g} {y1:g}] "
        f"/Resources << /Font << /{fixture.resource_name} "
        f"{fixture.font_xref} 0 R >> >> >>",
    )
    doc.update_stream(
        form_xref,
        (
            f"BT /{fixture.resource_name} {fontsize:g} Tf "
            f"1 0 0 1 {origin[0]:g} {origin[1]:g} Tm "
            f"<{encode_cids(text).hex().upper()}> Tj ET"
        ).encode("ascii"),
    )
    _set_page_xobject(fixture, name, f"{form_xref} 0 R")
    return form_xref


def hide_second_painter_in_ocg(fixture: Type0Fixture, *, on: bool = False) -> int:
    """Wrap the second painter of a two-painter page in ``/OC /P0 BDC ...
    EMC`` bound to an OCG whose default visibility is ``on``.  Returns the
    OCG xref.  The label never reaches any report."""
    ocg_xref = install_oc_layer(fixture, name="P0", label="layer", on=on)
    stream = fixture.content_bytes()
    marker = b"> Tj /"
    assert stream.count(marker) == 1, "not a two-painter page"
    assert stream.endswith(b" ET"), stream[-10:]
    edited = stream.replace(marker, b"> Tj /OC /P0 BDC /", 1)
    edited = edited[: -len(b" ET")] + b" EMC ET"
    fixture.doc.update_stream(fixture.content_xref, edited)
    return ocg_xref


# ----------------------------------------------------- alternative faces

_FACE_CACHE: dict[tuple, bytes] = {}


def build_face_fixture(
    fontfile: str,
    text: str,
    *,
    fontsize: float = 48.0,
    origin: tuple[float, float] = (100.0, 400.0),
) -> Type0Fixture:
    """Author a single-hex-``Tj`` Identity-H page with an arbitrary TrueType
    face (``fitz.TextWriter`` embedding + ``subset_fonts``), mirroring
    ``type0_fixture_builder._author_base`` for a face the builder does not
    ship.  Used for the tricky-font cell; the face bytes are never written
    to the repository."""
    key = (fontfile, text, fontsize, origin)
    face = fitz.Font(fontfile=fontfile)
    cids = tuple(face.has_glyph(ord(char)) for char in text)
    assert all(cids), "face lacks a glyph for the fixture text"
    data = _FACE_CACHE.get(key)
    if data is None:
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        writer = fitz.TextWriter(page.rect)
        writer.append(origin, text, font=face, fontsize=fontsize)
        writer.write_text(page)
        doc.subset_fonts()
        resource_name = page.get_fonts(full=True)[0][4]
        operand = "".join(f"{cid:04X}" for cid in cids)
        stream = (
            f"BT /{resource_name} {fontsize:g} Tf "
            f"1 0 0 1 {origin[0]:g} {origin[1]:g} Tm <{operand}> Tj ET"
        )
        doc.update_stream(page.get_contents()[0], stream.encode("ascii"))
        data = doc.tobytes()
        doc.close()
        _FACE_CACHE[key] = data
    reopened = fitz.open(stream=data, filetype="pdf")
    page = reopened[0]
    font_xref = page.get_fonts(full=True)[0][0]
    _, tounicode_value = reopened.xref_get_key(font_xref, "ToUnicode")
    return Type0Fixture(
        doc=reopened,
        page_number=0,
        resource_name=page.get_fonts(full=True)[0][4],
        font_xref=font_xref,
        descendant_xref=_descendant_xref_of(reopened, font_xref),
        tounicode_xref=int(tounicode_value.split()[0]),
        content_xref=page.get_contents()[0],
        text=text,
        fontsize=fontsize,
        origin=origin,
        encoded=b"".join(cid.to_bytes(2, "big") for cid in cids),
    )


TRICKY_FONT_PATH = r"C:\Windows\Fonts\mingliu.ttc"


def tricky_font_available() -> bool:
    return Path(TRICKY_FONT_PATH).is_file()
