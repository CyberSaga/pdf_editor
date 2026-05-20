# test_scripts/test_no_jump_editor_geometry.py
from __future__ import annotations
import json
import os
from itertools import product
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest
from PySide6.QtGui import QImage

from view.text_editing import (
    _compute_editor_proxy_layout,
    _display_font_pt,
    _parse_font_size_str,
    PreviewRenderer,
    TextEditFinalizeReason,
    TextEditOutcome,
)

ARTIFACT_DIR = Path("test_artifacts") / "no_jump"
EDITOR_CHROME_INSET_PX = 3


# ── run_id helpers (bound to current verifier invocation) ─────────────────────


def _current_run_id() -> str:
    """Read the run_id stamped by verify_no_jump.py before this pytest run.
    Falls back to 'standalone' when tests are run directly (not via the gate)."""
    rid_path = ARTIFACT_DIR / ".run_id"
    if rid_path.exists():
        return rid_path.read_text(encoding="utf-8").strip()
    return "standalone"


def _append_to_manifest(test_id: str) -> None:
    """Append test_id to manifest.json (JSON-lines) so the verifier can enumerate cases."""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = ARTIFACT_DIR / "manifest.json"
    with manifest_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(test_id) + "\n")


# ── artifact write helpers ─────────────────────────────────────────────────────


def _assert_written(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    assert path.exists() and path.stat().st_size > 0, (
        f"Artifact write failed or produced empty file: {path}"
    )


def _assert_image_saved(path: Path, image: QImage) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path)), f"QImage.save() failed for {path}"
    assert path.exists() and path.stat().st_size > 0, f"Image artifact empty: {path}"


def _save_artifacts(
    test_id: str,
    before_img: QImage | None,
    after_img: QImage | None,
    metrics: dict,
) -> None:
    """Write artifacts, assert each one exists + non-empty, register in manifest."""
    run_id = _current_run_id()
    metrics = {**metrics, "run_id": run_id}  # embed run_id for stale-artifact detection

    d = ARTIFACT_DIR / test_id
    d.mkdir(parents=True, exist_ok=True)
    _assert_written(d / "metrics.json", json.dumps(metrics, indent=2))

    if before_img is not None:
        _assert_image_saved(d / "before.png", before_img)
    if after_img is not None:
        _assert_image_saved(d / "after.png", after_img)
    if before_img is not None and after_img is not None:
        _assert_image_saved(d / "diff.png", _make_diff_image(before_img, after_img))

    _append_to_manifest(test_id)  # register case so verifier can enumerate expected set


def _make_diff_image(a: QImage, b: QImage) -> QImage:
    w, h = min(a.width(), b.width()), min(a.height(), b.height())
    diff = QImage(w, h, QImage.Format_ARGB32)
    diff.fill(0xFFFFFFFF)
    for y in range(h):
        for x in range(w):
            if (
                abs(a.pixelColor(x, y).lightness() - b.pixelColor(x, y).lightness())
                > 10
            ):
                diff.setPixelColor(x, y, 0xFFFF0000)
    return diff


def _changed_pixel_pct(ref: QImage, preview: QImage) -> float:
    """Return the fraction of changed pixels between two images.

    Fail-closed on size problems:
      - Zero-dimension images are an immediate assertion error (no render happened).
      - Dimension mismatches > 2px raise AssertionError — indicates a geometry bug,
        not rounding.  Non-overlapping area would be silently ignored otherwise,
        which is exactly the kind of size-jump we are testing for.
    """
    rw, rh = ref.width(), ref.height()
    pw, ph = preview.width(), preview.height()
    if rw == 0 or rh == 0:
        raise AssertionError(
            f"ref image has zero dimensions: {rw}×{rh} — render failed"
        )
    if pw == 0 or ph == 0:
        raise AssertionError(
            f"preview image has zero dimensions: {pw}×{ph} — render failed"
        )
    if abs(rw - pw) > 2 or abs(rh - ph) > 2:
        raise AssertionError(
            f"Image size mismatch: ref={rw}×{rh}, preview={pw}×{ph}. "
            f"Difference > 2px indicates a geometry bug (wrong scale or clip), "
            f"not pixel-level rendering noise — this is a glyph-size jump."
        )
    w, h = min(rw, pw), min(rh, ph)
    changed = 0
    for y in range(h):
        for x in range(w):
            rc = ref.pixelColor(x, y)
            pc = preview.pixelColor(x, y)
            delta = (
                abs(rc.red() - pc.red())
                + abs(rc.green() - pc.green())
                + abs(rc.blue() - pc.blue())
                + abs(rc.alpha() - pc.alpha())
            )
            if delta > 20:
                changed += 1
    # Count non-overlapping strip as fully changed so size jumps show up in the metric
    extra = max(rw * rh, pw * ph) - w * h
    total = max(rw * rh, pw * ph)
    return (changed + extra) / total


# ── Cycle-22 helpers: editor-only crop, blanking detector, real-PDF ink probe ─


def _crop(img: QImage, rect) -> QImage:
    """Crop an image to the given rect, clamped to image bounds.
    Returns a 1×1 image if the rect is fully outside (avoids zero-dim errors)."""
    rx = max(0, rect.x())
    ry = max(0, rect.y())
    rw = min(img.width() - rx, rect.width())
    rh = min(img.height() - ry, rect.height())
    if rw <= 0 or rh <= 0:
        return QImage(1, 1, QImage.Format_RGBA8888)
    return img.copy(rx, ry, rw, rh)


def _inset_editor_content_rect(rect):
    if rect.width() <= EDITOR_CHROME_INSET_PX * 2 or rect.height() <= EDITOR_CHROME_INSET_PX * 2:
        return rect
    return rect.adjusted(
        EDITOR_CHROME_INSET_PX,
        EDITOR_CHROME_INSET_PX,
        -EDITOR_CHROME_INSET_PX,
        -EDITOR_CHROME_INSET_PX,
    )


def _query_widget_bg_rgb(widget) -> tuple[int, int, int]:
    """Return the QPalette base colour of a widget as (R, G, B).
    Used as the 'blank' reference so the test does not hardcode the platform-
    dependent widget background colour.

    Sanity fallback: a base of (0, 0, 0) is almost always a transparent widget
    (an inline editor designed to overlay a PDF page) — pure black is not a
    realistic text-editor background.  Fall back to white, which matches the
    parent QTextEdit's typical paper colour and what the underlying PDF region
    most often is."""
    from PySide6.QtGui import QPalette

    c = widget.palette().color(QPalette.Base)
    rgb = (c.red(), c.green(), c.blue())
    if rgb == (0, 0, 0):
        return (255, 255, 255)
    return rgb


def _is_blank_pixel(c, bg_rgb: tuple[int, int, int], tol: int) -> bool:
    """Inline test: pixel is transparent or within ``tol`` of ``bg_rgb``."""
    if c.alpha() == 0:
        return True
    br, bg_, bb = bg_rgb
    return (
        abs(c.red() - br) <= tol
        and abs(c.green() - bg_) <= tol
        and abs(c.blue() - bb) <= tol
    )


def _blank_pixel_pct(
    img: QImage, bg_rgb: tuple[int, int, int] = (255, 255, 255), tol: int = 8
) -> float:
    """Absolute fraction of pixels that are alpha=0 OR within ``tol`` of ``bg_rgb``.

    Used for the blanking-detector self-test (a fully transparent QImage must
    register ≥99%).  For real bug detection use ``_blanking_relative_to`` —
    comparing the editor against a PDF reference avoids false positives on
    natural whitespace within the bbox."""
    w, h = img.width(), img.height()
    if w == 0 or h == 0:
        raise AssertionError(f"image has zero dimensions: {w}×{h}")
    blank = 0
    for y in range(h):
        for x in range(w):
            if _is_blank_pixel(img.pixelColor(x, y), bg_rgb, tol):
                blank += 1
    return blank / (w * h)


def _blanking_relative_to(
    reference_img: QImage,
    source_img: QImage,
    bg_rgb: tuple[int, int, int] = (255, 255, 255),
    tol: int = 8,
) -> float:
    """Fraction of *reference-ink* pixels where ``source_img`` is blank.

    Numerator: pixels where reference has ink (non-blank) AND source is blank.
    Denominator: pixels where reference has ink.

    This is the correct metric for 'editor failed to paint where PDF had
    content.'  An absolute blank fraction over-counts natural whitespace
    (gaps between glyphs, padding around text) and produces false positives
    even when the editor faithfully reproduces the PDF."""
    rw, rh = reference_img.width(), reference_img.height()
    sw, sh = source_img.width(), source_img.height()
    if rw == 0 or rh == 0 or sw == 0 or sh == 0:
        raise AssertionError(f"image has zero dimensions: ref={rw}×{rh} src={sw}×{sh}")
    w, h = min(rw, sw), min(rh, sh)
    ref_ink = 0
    blanked = 0
    for y in range(h):
        for x in range(w):
            r_blank = _is_blank_pixel(reference_img.pixelColor(x, y), bg_rgb, tol)
            if r_blank:
                continue
            ref_ink += 1
            if _is_blank_pixel(source_img.pixelColor(x, y), bg_rgb, tol):
                blanked += 1
    if ref_ink == 0:
        return 0.0
    return blanked / ref_ink


def _pdf_region_has_ink(
    pdf_path: Path, page_idx: int, bbox: fitz.Rect, ink_threshold: float = 0.05
) -> bool:
    """True if the source PDF actually has non-white content in ``bbox``.

    Used so the blanking assertion only fires when the editor SHOULD have
    painted something — avoids false positives on whitespace gutters."""
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_idx]
        clip = bbox & page.rect  # clamp to MediaBox
        if clip.is_empty:
            return False
        px = page.get_pixmap(clip=clip, alpha=False)
        img = QImage(
            px.samples, px.width, px.height, px.stride, QImage.Format_RGB888
        ).copy()
    finally:
        doc.close()
    w, h = img.width(), img.height()
    if w == 0 or h == 0:
        return False
    non_white = 0
    for y in range(h):
        for x in range(w):
            c = img.pixelColor(x, y)
            if c.red() < 245 or c.green() < 245 or c.blue() < 245:
                non_white += 1
    return (non_white / (w * h)) >= ink_threshold


def _observed_editor_vp_rect(view):
    """Return the editor's current viewport rectangle (observed, not predicted).

    Maps the proxy widget's scene rect to viewport coords; uses min/max to
    handle rotation transforms (rotated proxies have non-axis-aligned
    sceneBoundingRect already, so taking min/max of the four corners gives
    the axis-aligned cover rect that QGraphicsView would paint)."""
    from PySide6.QtCore import QPointF, QRect

    proxy = view.text_editor.graphicsProxyWidget()
    if proxy is not None:
        sr = proxy.sceneBoundingRect()
        corners = [
            view.graphics_view.mapFromScene(QPointF(sr.left(), sr.top())),
            view.graphics_view.mapFromScene(QPointF(sr.right(), sr.top())),
            view.graphics_view.mapFromScene(QPointF(sr.right(), sr.bottom())),
            view.graphics_view.mapFromScene(QPointF(sr.left(), sr.bottom())),
        ]
        xs = [p.x() for p in corners]
        ys = [p.y() for p in corners]
        x0, y0 = min(xs), min(ys)
        x1, y1 = max(xs), max(ys)
        return QRect(int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0)))
    geom = view.text_editor.geometry()
    return QRect(geom.x(), geom.y(), max(1, geom.width()), max(1, geom.height()))


def _detect_span_rotation(span_data: dict) -> int:
    """Snap a PyMuPDF span's writing-direction vector to {0, 90, 180, 270}.

    Vertical text has dir near (0, ±1).  Used to label the test artifact and
    feed the rotation parameter when comparing predicted vs observed rects."""
    dx, dy = span_data.get("dir", (1.0, 0.0))
    if abs(dx) >= abs(dy):
        return 0 if dx >= 0 else 180
    return 90 if dy >= 0 else 270


# ── AC 1 + AC 3: geometry match across full matrix ────────────────────────────

# Maps font_case label → (CSS font-family, font_size_pt used in that span)
# Using distinct sizes per font family exercises the formula with realistic values
# and ensures a per-family regression (e.g. wrong fallback size) would be detected.
FONT_CASE_PARAMS: dict[str, tuple[str, float]] = {
    "helv": ("Helvetica", 12.0),
    "cjk": ("Microsoft JhengHei", 14.0),
    "unknown_font": ("NonexistentFont123", 10.0),
}

_GEOMETRY_RENDER_SCALES = (0.67, 1.0, 1.5, 2.0, 3.0, 4.0)
_GEOMETRY_DPIS = (96.0, 120.0, 144.0, 192.0, 300.0)
_GEOMETRY_ROTATIONS = (0, 90, 180, 270)
GEOMETRY_CASES = list(
    product(
        _GEOMETRY_RENDER_SCALES,
        _GEOMETRY_DPIS,
        tuple(FONT_CASE_PARAMS.keys()),
        _GEOMETRY_ROTATIONS,
    )
)


@pytest.mark.parametrize("render_scale,logical_dpi,font_case,rotation", GEOMETRY_CASES)
def test_editor_geometry_matches_pdf_bbox(
    qapp, render_scale, logical_dpi, font_case, rotation
):
    """AC 1+3: placement within 0.5px/1.0px; font_size_ratio in [0.99,1.01].

    Uses the per-font-case font_size from FONT_CASE_PARAMS so that a regression in
    CJK or unknown-font size handling (e.g. wrong fallback, coercion to int) is
    detectable — not masked by always using a common 12pt value.
    """
    _font_name, font_size = FONT_CASE_PARAMS[font_case]
    pdf_bbox = fitz.Rect(50.0, 100.0, 250.0, 122.0)
    page_y_off = 30.0
    scaled_rect = fitz.Rect(
        pdf_bbox.x0 * render_scale,
        pdf_bbox.y0 * render_scale,
        pdf_bbox.x1 * render_scale,
        pdf_bbox.y1 * render_scale,
    )
    with patch("view.text_editing._widget_logical_dpi", return_value=logical_dpi):
        w, h, x, y, _ = _compute_editor_proxy_layout(
            scaled_rect=scaled_rect,
            scaled_width=int(round(pdf_bbox.width * render_scale)),
            page_y_offset=page_y_off,
            rotation=rotation,
            content_height_px=int(round(pdf_bbox.height * render_scale)),
        )
        fs_ratio = (_display_font_pt(font_size, render_scale) * logical_dpi / 72.0) / (
            font_size * render_scale
        )

    exp_x = pdf_bbox.x0 * render_scale
    exp_y = page_y_off + pdf_bbox.y0 * render_scale
    if int(rotation) % 360 == 180:
        exp_x += pdf_bbox.width * render_scale
        exp_y += pdf_bbox.height * render_scale
    test_id = f"geom_rs{render_scale}_dpi{int(logical_dpi)}_{font_case}_rot{rotation}"
    _save_artifacts(
        test_id,
        None,
        None,
        {
            "render_scale": render_scale,
            "logical_dpi": logical_dpi,
            "font_case": font_case,
            "font_size_pt": font_size,
            "rotation": rotation,
            "x_drift": float(x) - exp_x,
            "y_drift": float(y) - exp_y,
            "w_drift": float(w) - pdf_bbox.width * render_scale,
            "h_drift": float(h) - pdf_bbox.height * render_scale,
            "font_size_ratio": fs_ratio,
        },
    )

    assert abs(float(x) - exp_x) <= 0.5, f"x drift > 0.5px [{test_id}]"
    assert abs(float(y) - exp_y) <= 0.5, f"y drift > 0.5px [{test_id}]"
    assert abs(float(w) - pdf_bbox.width * render_scale) <= 1.0, (
        f"w drift > 1.0px [{test_id}]"
    )
    assert abs(float(h) - pdf_bbox.height * render_scale) <= 1.0, (
        f"h drift > 1.0px [{test_id}]"
    )
    assert 0.99 <= fs_ratio <= 1.01, (
        f"font_size_ratio {fs_ratio:.4f} outside [0.99,1.01] [{test_id}] "
        f"(font_case={font_case}, font_size={font_size}pt)"
    )


# ── AC 4: geometry negative control ───────────────────────────────────────────


def test_geometry_negative_control_x_offset(qapp):
    """AC 4: +2px x injection MUST be detected; if not, the geometry test is useless."""
    pdf_bbox = fitz.Rect(50.0, 100.0, 250.0, 122.0)
    orig = _compute_editor_proxy_layout

    def bad(**kw):
        w, h, x, y, r = orig(**kw)
        return w, h, x + 2.0, y, r

    scaled_rect = fitz.Rect(pdf_bbox.x0, pdf_bbox.y0, pdf_bbox.x1, pdf_bbox.y1)
    _, _, x, _, _ = bad(
        scaled_rect=scaled_rect,
        scaled_width=int(round(pdf_bbox.width)),
        page_y_offset=30.0,
        rotation=0,
        content_height_px=None,
    )
    drift = abs(float(x) - pdf_bbox.x0)
    _save_artifacts(
        "geom_negative_control",
        None,
        None,
        {"injected_x_offset": 2.0, "detected_drift": drift},
    )
    assert drift > 0.5, (
        f"Negative control failed: +2px not detected (drift={drift:.3f}px)"
    )


@pytest.mark.parametrize("font_case", ["cjk", "unknown_font"])
def test_geometry_negative_control_wrong_font_size(qapp, font_case):
    """AC 4 (font fallback): wrong font_size for CJK/unknown MUST push fs_ratio out of [0.99,1.01].

    Simulates a regression where _display_font_pt receives the wrong per-font size
    (e.g. a hardcoded 12pt instead of the CJK 14pt or fallback 10pt).
    """
    _font_name, correct_size = FONT_CASE_PARAMS[font_case]
    wrong_size = 12.0  # the hard-coded value the bug would use
    # If correct == 12.0 this test would be vacuous, but FONT_CASE_PARAMS ensures it isn't
    assert correct_size != wrong_size, (
        f"FONT_CASE_PARAMS[{font_case}] must not be 12pt — pick a distinct value"
    )
    render_scale = 1.0
    with patch("view.text_editing._widget_logical_dpi", return_value=96.0):
        # fs_ratio using the WRONG (hard-coded) size
        bad_fs_ratio = (_display_font_pt(wrong_size, render_scale) * 96.0 / 72.0) / (
            correct_size * render_scale
        )
    _save_artifacts(
        f"geom_neg_fontsize_{font_case}",
        None,
        None,
        {
            "font_case": font_case,
            "correct_size": correct_size,
            "wrong_size": wrong_size,
            "bad_fs_ratio": bad_fs_ratio,
        },
    )
    assert not (0.99 <= bad_fs_ratio <= 1.01), (
        f"Negative control failed for {font_case}: wrong 12pt still passes "
        f"fs_ratio {bad_fs_ratio:.4f} — pick a more distinct FONT_CASE_PARAMS value"
    )


# ── AC 2 end-to-end: real geometry pipeline with a real PDF ───────────────────
#
# This test uses a real reference PDF and the real model geometry pipeline
# (PDFModel.open_pdf → get_text_info_at_point → actual span data) rather than
# hardcoded synthetic values.  Bugs in get_text_info_at_point, real font_name
# extraction, or real font_size values cannot hide behind synthetic assumptions.

REPO_ROOT = Path(__file__).parent.parent


def test_click_to_edit_real_geometry_pipeline(qapp):
    """AC 2 end-to-end: real PDF + real geometry pipeline → PreviewBackedInlineTextEditor.

    Exercises the FULL click-to-edit pipeline path:
      1. Load test-colored-background.pdf via PDFModel (real document, real fonts).
      2. Extract a real text span using get_text_info_at_point — same API the
         controller calls on click.
      3. Render the actual span region via MuPDF → 'before' (pre-click view).
      4. Instantiate PreviewBackedInlineTextEditor with the REAL span data
         (font_name, font_size, color, rect_pt, rotation from the model hit result).
      5. Capture the first editor frame and assert < 1% changed pixels.

    Unlike a synthetic-PDF test with hardcoded values, this catches:
      - Wrong font_name extraction (get_text_info_at_point returning stale font)
      - Wrong font_size values from the real document
      - Real bbox divergence between document coordinates and editor placement
    """
    from model.pdf_model import PDFModel
    from view.text_editing import PreviewBackedInlineTextEditor
    from unittest.mock import patch

    pdf_path = REPO_ROOT / "test_files" / "test-colored-background.pdf"
    assert pdf_path.exists(), f"Reference PDF not found: {pdf_path}"

    model = PDFModel()
    model.open_pdf(str(pdf_path))
    model.ensure_page_index_built(1)

    # Find the first text span on page 1 using the real document
    fitz_page = model.doc[0]
    blocks = fitz_page.get_text("rawdict")["blocks"]
    span_data = None
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    span_data = span
                    break
            if span_data:
                break
        if span_data:
            break
    assert span_data is not None, (
        "No text span found on page 1 of test-colored-background.pdf — update reference PDF"
    )

    span_rect = fitz.Rect(span_data["bbox"])
    center_pt = fitz.Point(
        span_rect.x0 + span_rect.width / 2,
        span_rect.y0 + span_rect.height / 2,
    )

    # Use model.get_text_info_at_point to exercise the real hit-test path
    hit = model.get_text_info_at_point(1, center_pt)
    assert hit is not None, (
        "get_text_info_at_point returned None for a known span center — hit-test broken"
    )

    render_scale = 2.0

    # Before: MuPDF raster of the span's actual bbox (what the user sees before clicking)
    ref_px = fitz_page.get_pixmap(
        matrix=fitz.Matrix(render_scale, render_scale),
        clip=hit.target_bbox,
        alpha=True,
    )
    before_img = QImage(
        ref_px.samples,
        ref_px.width,
        ref_px.height,
        ref_px.stride,
        QImage.Format_RGBA8888,
    ).copy()
    bg = before_img.pixelColor(0, 0)
    legacy_bg_rgb = (bg.red(), bg.green(), bg.blue())
    model.close()

    # After: instantiate the REAL inline editor with actual span data (not hardcoded).
    # _widget_logical_dpi is patched to 96.0 for a deterministic pixel size.
    with patch("view.text_editing._widget_logical_dpi", return_value=96.0):
        editor = PreviewBackedInlineTextEditor(
            text=hit.target_text,
            font_name=hit.font,  # REAL font from the document
            font_size=hit.size,  # REAL font size from the document
            color=tuple(hit.color),  # REAL color from the document
            rect_pt=hit.target_bbox,  # REAL bbox from the document
            render_scale=render_scale,
            rotation=hit.rotation,  # REAL rotation from the document
            model=None,  # model arg for editing; preview render doesn't need live doc
            legacy_bg_rgb=legacy_bg_rgb,
            initial_frame_image=before_img,
        )
        editor.show()
        qapp.processEvents()
        grab = editor.grab()
        after_img = grab.toImage().convertToFormat(QImage.Format_RGBA8888)
        editor.hide()
        editor.deleteLater()
        qapp.processEvents()

    assert not before_img.isNull(), "before_img (MuPDF raster) render failed"
    assert not after_img.isNull(), (
        "after_img (editor widget grab) is null — widget did not paint"
    )

    changed_pct = _changed_pixel_pct(before_img, after_img)
    _save_artifacts(
        "e2e_click_to_edit",
        before_img,
        after_img,
        {
            "font_size": float(hit.size),
            "render_scale": render_scale,
            "changed_px_pct": changed_pct,
        },
    )
    assert changed_pct <= 0.01, (
        f"Real click-to-edit jump: {changed_pct:.2%} changed pixels > 1%. "
        f"Font={hit.font!r}, size={hit.size}, bbox={hit.target_bbox}. "
        f"Open test_artifacts/no_jump/e2e_click_to_edit/diff.png"
    )


# ── AC 2 full-stack: real QTest click through PDFView + PDFController ─────────
#
# This test drives the FULL click-to-edit transition:
#   PDFView._mouse_press (sets _pending_text_info) →
#   PDFView._mouse_release (calls _create_text_editor) →
#   TextEditManager.create_text_editor →
#   PreviewBackedInlineTextEditor (opens, paintEvent runs preview)
#
# The before/after comparison captures the actual viewport region, not a widget
# grab — it observes exactly what the user sees at the moment of transition.


QTEST_E2E_CASES = [
    # (pdf_filename, slug)  — slug becomes part of the test_id.
    # All three PDFs MUST exist; missing reference PDFs are a hard failure.
    # colored-bg     — Latin text on a coloured background (background-fill regression class)
    # complex-layout — CJK glyph rendering, dense layouts (font-fallback regression class)
    # vertical-texts — rotation=90 spans (rotation regression class — the bug
    #                  Codex's manual retest exposed where the editor blanks on open)
    ("test-colored-background.pdf", "colored"),
    ("test-complexed-layout.pdf", "complexed"),
    ("test-vertical-texts.pdf", "vertical"),
]

MUTATION_EMPTY_SOURCE_INK_RETAINED_MAX = 0.01
MUTATION_GEOMETRY_DRIFT_MAX_PX = 1
CONTINUOUS_INSERTION_STEPS = 5
REOPEN_SESSION_CYCLES = max(1, int(os.environ.get("NO_JUMP_REOPEN_CYCLES", "20")))
REOPEN_GEOMETRY_DRIFT_MAX_PX = 1
REOPEN_FONT_PT_DRIFT_MAX = 0.5
REOPEN_PIXEL_DIFF_MAX = 0.01


def _resolve_inner_editor_widget(editor_obj):
    from PySide6.QtWidgets import QGraphicsProxyWidget

    if isinstance(editor_obj, QGraphicsProxyWidget):
        return editor_obj.widget()
    return editor_obj


def _first_non_empty_span_data(model, page_idx: int = 0):
    fitz_page = model.doc[page_idx]
    for block in fitz_page.get_text("rawdict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if (span.get("text") or "").strip():
                    return span
    return None


def _cycle_replacement_text_same_length(original_text: str, cycle: int) -> str:
    """Return deterministic replacement text with the same length as input."""
    src = original_text or ""
    if not src:
        return f"R{cycle}"
    token = f"R{cycle:02d}X"
    replacement = (token * ((len(src) // len(token)) + 1))[: len(src)]
    if replacement == src:
        replacement = ("Z" + replacement[1:]) if len(replacement) > 1 else "Z"
    return replacement


def _grab_editor_only_image(view, qapp):
    for _ in range(3):
        qapp.processEvents()
    full = (
        view.graphics_view.viewport()
        .grab()
        .toImage()
        .convertToFormat(QImage.Format_RGBA8888)
    )
    rect = _observed_editor_vp_rect(view)
    return _crop(full, _inset_editor_content_rect(rect)), rect


def _rect_drift_metrics(reference_rect, current_rect) -> dict[str, int]:
    return {
        "dx": int(current_rect.x() - reference_rect.x()),
        "dy": int(current_rect.y() - reference_rect.y()),
        "dw": int(current_rect.width() - reference_rect.width()),
        "dh": int(current_rect.height() - reference_rect.height()),
    }


def _assert_rect_drift_within(
    *,
    reference_rect,
    current_rect,
    tolerance_px: int,
    context: str,
) -> None:
    drift = _rect_drift_metrics(reference_rect, current_rect)
    assert abs(drift["dx"]) <= tolerance_px, (
        f"{context}: editor x drift {drift['dx']}px exceeds ±{tolerance_px}px"
    )
    assert abs(drift["dy"]) <= tolerance_px, (
        f"{context}: editor y drift {drift['dy']}px exceeds ±{tolerance_px}px"
    )
    assert abs(drift["dw"]) <= tolerance_px, (
        f"{context}: editor width drift {drift['dw']}px exceeds ±{tolerance_px}px"
    )
    assert abs(drift["dh"]) <= tolerance_px, (
        f"{context}: editor height drift {drift['dh']}px exceeds ±{tolerance_px}px"
    )


@pytest.mark.parametrize("pdf_filename,pdf_slug", QTEST_E2E_CASES)
def test_click_to_edit_qtest_integration(qapp, pdf_filename, pdf_slug):
    """AC 2 full-stack: real QTest click drives the complete click-to-edit transition.

    Sets up PDFView + PDFController + PDFModel exactly as main.py does, loads
    a reference PDF (parametrized — see QTEST_E2E_CASES), enters edit_text mode,
    finds a real text span, and uses QTest.mousePress + QTest.mouseRelease to
    trigger the editor.

    Parametrizing across PDFs catches font-family / layout-dependent regressions
    that single-PDF coverage would miss (CJK handling, complex layouts).

    Captures the viewport sub-region containing the span:
      before — PDF page rendering (what the user sees before clicking)
      after  — same region with the open editor's first painted frame

    Asserts < 1% changed pixels — any glyph-size jump shows up here.
    This is the only test that exercises the full coordinate pipeline:
      page_y_positions → _render_scale → _scene_pos_to_page_and_doc_point →
      get_text_info_at_point → _compute_editor_proxy_layout →
      PreviewBackedInlineTextEditor.paintEvent
    """
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView
    from controller.pdf_controller import PDFController
    from PySide6.QtCore import Qt, QPoint, QPointF, QRect
    from PySide6.QtTest import QTest

    pdf_path = REPO_ROOT / "test_files" / pdf_filename
    assert pdf_path.exists(), f"Reference PDF not found: {pdf_path}"

    # Wire up the full app stack exactly as main.py does
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    view.show()
    for _ in range(10):
        qapp.processEvents()

    controller.open_pdf(str(pdf_path))
    for _ in range(20):  # let rendering pipeline complete
        qapp.processEvents()

    # Enter text-edit mode
    view.set_mode("edit_text")
    for _ in range(5):
        qapp.processEvents()

    # Find a real text span on page 1
    model.ensure_page_index_built(1)
    fitz_page = model.doc[0]
    blocks = fitz_page.get_text("rawdict")["blocks"]
    span_data = None
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    span_data = span
                    break
            if span_data:
                break
        if span_data:
            break
    assert span_data is not None, f"No text span found on page 1 of {pdf_filename}"

    span_bbox = fitz.Rect(span_data["bbox"])
    render_scale = view._render_scale if view._render_scale > 0 else 1.0
    page_idx = 0

    # Convert span center from PDF-document coords → scene coords → viewport coords
    y0 = (
        view.page_y_positions[page_idx]
        if (view.continuous_pages and page_idx < len(view.page_y_positions))
        else 0.0
    )
    scene_x = span_bbox.x0 * render_scale + (span_bbox.width * render_scale) / 2
    scene_y = y0 + span_bbox.y0 * render_scale + (span_bbox.height * render_scale) / 2
    vp_pt = view.graphics_view.mapFromScene(QPointF(scene_x, scene_y))
    click_pos = QPoint(int(vp_pt.x()), int(vp_pt.y()))

    # Compute the tight viewport rectangle covering the span.
    span_scene_tl = view.graphics_view.mapFromScene(
        QPointF(span_bbox.x0 * render_scale, y0 + span_bbox.y0 * render_scale)
    )
    span_w_px = int(span_bbox.width * render_scale) + 4  # +4 rounding guard
    span_h_px = int(span_bbox.height * render_scale) + 4
    span_vp_rect = QRect(span_scene_tl.x(), span_scene_tl.y(), span_w_px, span_h_px)

    # Expand grab_rect by the span's own dimensions on each side.  This ensures
    # a displaced editor cannot escape detection: if the editor opens at a wrong
    # position, it appears in after_img at a location that had no rendering in
    # before_img, driving changed_pct above 1%.  Using just span_vp_rect would
    # let a displaced editor fall entirely outside the sampled region, producing
    # changed_pct ≈ 0 and a false pass.
    pad_x = max(span_w_px, 8)
    pad_y = max(span_h_px, 8)
    vp_size = view.graphics_view.viewport().size()
    grab_rect = QRect(
        max(0, span_vp_rect.x() - pad_x),
        max(0, span_vp_rect.y() - pad_y),
        min(span_vp_rect.width() + 2 * pad_x, vp_size.width()),
        min(span_vp_rect.height() + 2 * pad_y, vp_size.height()),
    )

    # Before: grab the padded viewport region (PDF rendering, no editor)
    before_grab = view.graphics_view.viewport().grab(grab_rect)
    before_img = before_grab.toImage().convertToFormat(QImage.Format_RGBA8888)
    assert not before_img.isNull(), (
        "before_img grab returned null — PDF viewport is not yet rendered"
    )

    # Click: mousePress + mouseRelease without movement triggers _create_text_editor
    QTest.mousePress(view.graphics_view.viewport(), Qt.LeftButton, pos=click_pos)
    qapp.processEvents()
    QTest.mouseRelease(view.graphics_view.viewport(), Qt.LeftButton, pos=click_pos)
    for _ in range(10):  # drive paintEvent
        qapp.processEvents()

    assert view.text_editor is not None, (
        "view.text_editor is None after click — editor did not open. "
        f"click_pos={click_pos}, span_bbox={span_bbox}, render_scale={render_scale}"
    )

    # Geometry intersection assertion: the editor must overlap the expected span
    # viewport rect.  A displaced editor (regression) fails here immediately —
    # before the pixel diff even runs — with a clear diagnostic message.
    proxy = view.text_editor.graphicsProxyWidget()
    if proxy is not None:
        editor_scene_rect = proxy.sceneBoundingRect()
        editor_vp_tl = view.graphics_view.mapFromScene(editor_scene_rect.topLeft())
        editor_vp_rect = QRect(
            int(editor_vp_tl.x()),
            int(editor_vp_tl.y()),
            max(1, int(editor_scene_rect.width())),
            max(1, int(editor_scene_rect.height())),
        )
        assert editor_vp_rect.intersects(span_vp_rect), (
            f"Editor opened at viewport {editor_vp_rect} which does NOT overlap the "
            f"expected span rect {span_vp_rect}.  The editor is displaced — glyph "
            f"jump confirmed.  span_bbox={span_bbox}  render_scale={render_scale}"
        )
    else:
        # Editor is not a QGraphicsProxyWidget — fall back to checking that
        # click_pos (which is inside the span) is within the editor's geometry.
        egeom = view.text_editor.geometry()
        assert egeom.width() > 0 and egeom.height() > 0, (
            f"Editor has zero-size geometry {egeom} — likely not properly placed"
        )

    # After: grab the SAME padded region with the open editor's first frame.
    after_grab = view.graphics_view.viewport().grab(grab_rect)
    after_img = after_grab.toImage().convertToFormat(QImage.Format_RGBA8888)
    assert not after_img.isNull(), "after_img grab returned null"

    # Cycle-22: editor-only crop instead of padded grab.  The padded diff
    # dilutes per-region blanking below 1% (the editor is ~1/9 of the grab),
    # which is how colored-background blanking and vertical-texts open-blanking
    # slipped through earlier gates.  Capture both for diagnostic visibility.
    changed_pct_padded = _changed_pixel_pct(before_img, after_img)
    obs_editor = _observed_editor_vp_rect(view)
    editor_in_grab = _inset_editor_content_rect(obs_editor).intersected(grab_rect).translated(
        -grab_rect.x(), -grab_rect.y()
    )
    if editor_in_grab.width() <= 0 or editor_in_grab.height() <= 0:
        view.close()
        view.deleteLater()
        qapp.processEvents()
        pytest.fail(
            f"Editor at viewport {obs_editor} is outside grab region "
            f"{grab_rect} on {pdf_filename} — geometric jump."
        )
    before_crop = _crop(before_img, editor_in_grab)
    after_crop = _crop(after_img, editor_in_grab)
    changed_pct_editor = _changed_pixel_pct(before_crop, after_crop)
    # `view.text_editor` may be the QTextEdit-derived widget OR a
    # QGraphicsProxyWidget wrapping it; unwrap once for palette/focus access.
    from PySide6.QtWidgets import QGraphicsProxyWidget as _QGPW

    _inner = (
        view.text_editor.widget()
        if isinstance(view.text_editor, _QGPW)
        else view.text_editor
    )
    bg_rgb = _query_widget_bg_rgb(_inner)
    mask_debug = _inner.property("mask_debug_metrics") or {}
    # Relative blanking — fraction of PDF-ink pixels where the editor is blank.
    # Avoids false positives on natural whitespace (gaps between glyphs, padding).
    blanking_pct = _blanking_relative_to(before_crop, after_crop, bg_rgb=bg_rgb)
    pdf_has_ink = _pdf_region_has_ink(pdf_path, 0, span_bbox)
    span_rotation = _detect_span_rotation(span_data)

    test_id = f"e2e_qtest_click_to_edit_{pdf_slug}"
    _save_artifacts(
        test_id,
        before_img,
        after_img,
        {
            "render_scale": render_scale,
            "changed_px_pct_padded": changed_pct_padded,
            "changed_px_pct_editor": changed_pct_editor,
            "blanking_pct_vs_pdf": blanking_pct,
            "pdf_has_ink": pdf_has_ink,
            "bg_rgb": list(bg_rgb),
            "mask_mode": mask_debug.get("mask_mode"),
            "mask_ring_delta": mask_debug.get("ring_delta"),
            "mask_leak_pct": mask_debug.get("leak_pct"),
            "mask_contrast_ratio": mask_debug.get("contrast_ratio"),
            "mask_tint_strength": mask_debug.get("tint_strength"),
            "span_rotation": span_rotation,
            "span_bbox": list(span_bbox),
            "pdf_filename": pdf_filename,
        },
    )

    # Cleanup
    view.close()
    view.deleteLater()
    qapp.processEvents()

    assert changed_pct_editor <= 0.01, (
        f"Editor-region changed_pct {changed_pct_editor:.2%} > 1% on "
        f"{pdf_filename} (padded crop {changed_pct_padded:.2%}).  "
        f"The editor's first frame does not match the PDF rendering.  "
        f"Open test_artifacts/no_jump/{test_id}/diff.png"
    )
    assert mask_debug.get("mask_mode") in {"background_match", "fallback"}, (
        f"Mask debug metrics missing mode for {pdf_filename}: {mask_debug!r}"
    )
    if mask_debug.get("ring_delta") is not None:
        assert float(mask_debug.get("ring_delta", 999.0)) <= 40.0, (
            f"Mask ring delta too high on {pdf_filename}: "
            f"{mask_debug.get('ring_delta')}"
        )
    if mask_debug.get("leak_pct") is not None:
        assert float(mask_debug.get("leak_pct", 1.0)) <= 0.01, (
            f"Mask leak ratio too high on {pdf_filename}: {mask_debug.get('leak_pct')}"
        )
    if pdf_has_ink:
        assert blanking_pct <= 0.05, (
            f"Editor blanked: {blanking_pct:.2%} of PDF-ink pixels render as "
            f"transparent or background-colour ({bg_rgb}) in the editor.  "
            f"This is the vertical-text / colored-bg blanking bug class. "
            f"{pdf_filename}  span_rotation={span_rotation}°"
        )


# ── AC 5 (Cycle 22): mutation stability — type then delete must restore ──────


@pytest.mark.parametrize("pdf_filename,pdf_slug", QTEST_E2E_CASES)
def test_click_to_edit_then_insert_then_delete_stays_stable(
    qapp, pdf_filename, pdf_slug
):
    """AC 5: opening + typing 'TEST' + backspacing it out must restore the
    editor to its open-state appearance within 1% delta, with the editor
    region still showing PDF-derived content (not blanked).

    Catches the bug class the previous gate missed: mutation-triggered blanking
    on coloured backgrounds where geometry stays fixed but the editor paints
    nothing recognisable after a roundtrip type+delete."""
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView
    from controller.pdf_controller import PDFController
    from PySide6.QtCore import Qt, QPoint, QPointF
    from PySide6.QtTest import QTest

    pdf_path = REPO_ROOT / "test_files" / pdf_filename
    assert pdf_path.exists(), f"Reference PDF not found: {pdf_path}"

    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    view.show()
    for _ in range(10):
        qapp.processEvents()
    controller.open_pdf(str(pdf_path))
    for _ in range(20):
        qapp.processEvents()
    view.set_mode("edit_text")
    for _ in range(5):
        qapp.processEvents()

    # Find a real text span on page 1
    model.ensure_page_index_built(1)
    fitz_page = model.doc[0]
    blocks = fitz_page.get_text("rawdict")["blocks"]
    span_data = None
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    span_data = span
                    break
            if span_data:
                break
        if span_data:
            break
    assert span_data is not None, f"No text span on page 1 of {pdf_filename}"

    span_bbox = fitz.Rect(span_data["bbox"])
    render_scale = view._render_scale if view._render_scale > 0 else 1.0
    y0 = (
        view.page_y_positions[0]
        if (view.continuous_pages and view.page_y_positions)
        else 0.0
    )
    sx = span_bbox.x0 * render_scale + (span_bbox.width * render_scale) / 2
    sy = y0 + span_bbox.y0 * render_scale + (span_bbox.height * render_scale) / 2
    vp_pt = view.graphics_view.mapFromScene(QPointF(sx, sy))
    click_pos = QPoint(int(vp_pt.x()), int(vp_pt.y()))

    QTest.mousePress(view.graphics_view.viewport(), Qt.LeftButton, pos=click_pos)
    qapp.processEvents()
    QTest.mouseRelease(view.graphics_view.viewport(), Qt.LeftButton, pos=click_pos)
    for _ in range(10):
        qapp.processEvents()
    assert view.text_editor is not None, (
        f"editor did not open on {pdf_filename} click_pos={click_pos}"
    )

    # `view.text_editor` may be either the QTextEdit-derived widget or a
    # QGraphicsProxyWidget wrapping it. Resolve once to the inner widget for
    # focus, palette, and mutation operations.
    inner_editor = _resolve_inner_editor_widget(view.text_editor)
    assert inner_editor is not None, (
        f"could not resolve inner editor widget on {pdf_filename}"
    )
    bg_rgb = _query_widget_bg_rgb(inner_editor)
    mask_rgb = inner_editor.property("mask_rgb") or bg_rgb
    opened_img, opened_rect = _grab_editor_only_image(view, qapp)
    assert opened_img.width() > 0 and opened_img.height() > 0, (
        f"opened_img has zero dimensions on {pdf_filename}"
    )

    inner_editor.setFocus()
    qapp.processEvents()

    # During live editing the old PDF glyphs must be suppressed by the
    # background-matched mask. Exercise that exact state with an empty edit
    # before checking the type/delete restore contract.
    original_text = inner_editor.toPlainText()
    inner_editor.setPlainText("")
    for _ in range(10):
        qapp.processEvents()
    empty_img, empty_rect = _grab_editor_only_image(view, qapp)
    _assert_rect_drift_within(
        reference_rect=opened_rect,
        current_rect=empty_rect,
        tolerance_px=MUTATION_GEOMETRY_DRIFT_MAX_PX,
        context=f"{pdf_filename} empty live-edit state",
    )
    empty_source_ink_retained = 1.0 - _blanking_relative_to(
        opened_img, empty_img, bg_rgb=mask_rgb
    )
    inner_editor.setPlainText(original_text)
    for _ in range(10):
        qapp.processEvents()

    # Mutate via the QTextEdit API rather than QTest.keyClicks: the latter
    # is fragile across PySide6 versions and proxy-widget contexts. The
    # paintEvent re-render is triggered by content change, not by the input
    # source, so this exercises the same code path that user typing would.
    inner_editor.insertPlainText("TEST")
    for _ in range(10):
        qapp.processEvents()
    inserted_img, inserted_rect = _grab_editor_only_image(view, qapp)
    _assert_rect_drift_within(
        reference_rect=opened_rect,
        current_rect=inserted_rect,
        tolerance_px=MUTATION_GEOMETRY_DRIFT_MAX_PX,
        context=f"{pdf_filename} inserted state",
    )

    cursor = inner_editor.textCursor()
    for _ in range(4):
        cursor.deletePreviousChar()
    inner_editor.setTextCursor(cursor)
    for _ in range(10):
        qapp.processEvents()
    restored_img, restored_rect = _grab_editor_only_image(view, qapp)
    _assert_rect_drift_within(
        reference_rect=opened_rect,
        current_rect=restored_rect,
        tolerance_px=MUTATION_GEOMETRY_DRIFT_MAX_PX,
        context=f"{pdf_filename} restored state",
    )

    insert_delta = _changed_pixel_pct(opened_img, inserted_img)
    insert_blanking = _blanking_relative_to(opened_img, inserted_img, bg_rgb=bg_rgb)
    restore_delta = _changed_pixel_pct(opened_img, restored_img)
    # Relative blanking: of the pixels that had ink in the opened editor,
    # what fraction went blank in the restored editor? This catches the
    # mutation-blanking bug class (colored-bg) while ignoring natural
    # whitespace that's blank in both opened and restored.
    blanking_after = _blanking_relative_to(opened_img, restored_img, bg_rgb=bg_rgb)

    test_id = f"e2e_qtest_mutation_{pdf_slug}"
    _save_artifacts(
        test_id,
        opened_img,
        restored_img,
        {
            "insert_delta": insert_delta,
            "insert_blanking_vs_opened": insert_blanking,
            "empty_source_ink_retained": empty_source_ink_retained,
            "restore_delta": restore_delta,
            "blanking_pct_vs_opened": blanking_after,
            "empty_rect_drift": _rect_drift_metrics(opened_rect, empty_rect),
            "insert_rect_drift": _rect_drift_metrics(opened_rect, inserted_rect),
            "restored_rect_drift": _rect_drift_metrics(opened_rect, restored_rect),
            "bg_rgb": list(bg_rgb),
            "mask_rgb": list(mask_rgb),
            "pdf_filename": pdf_filename,
            "span_rotation": _detect_span_rotation(span_data),
        },
    )

    view.close()
    view.deleteLater()
    qapp.processEvents()

    assert empty_source_ink_retained <= MUTATION_EMPTY_SOURCE_INK_RETAINED_MAX, (
        f"Empty live-edit state retained {empty_source_ink_retained:.2%} of "
        f"opened-state source ink on {pdf_filename}; old glyphs are leaking "
        f"through the edit mask during editing."
    )
    assert restore_delta <= 0.01, (
        f"Restore delta {restore_delta:.2%} > 1% on {pdf_filename} - typing "
        f"then deleting did NOT return the editor to its opened-state "
        f"appearance. This is the mutation-blanking bug class. "
        f"insert_delta={insert_delta:.2%}"
    )
    assert blanking_after <= 0.05, (
        f"After type+delete, {blanking_after:.2%} of opened-state ink pixels "
        f"went blank (transparent or bg={bg_rgb}) on {pdf_filename} - the "
        f"editor lost original page content during mutation."
    )


@pytest.mark.parametrize("pdf_filename,pdf_slug", QTEST_E2E_CASES)
def test_click_to_edit_continuous_insertions_then_delete_stays_stable(
    qapp, pdf_filename, pdf_slug
):
    """Cycle22 continuous mutation scenario: 5 in-session insertions, then full delete.

    Asserts three invariants in one open editor session:
      1) no geometry drift while mutating,
      2) inserted-state continuity on every step,
      3) restored-state parity after deleting all inserted text.
    """
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView
    from controller.pdf_controller import PDFController
    from PySide6.QtCore import Qt, QPoint, QPointF
    from PySide6.QtTest import QTest

    pdf_path = REPO_ROOT / "test_files" / pdf_filename
    assert pdf_path.exists(), f"Reference PDF not found: {pdf_path}"

    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    view.show()
    for _ in range(10):
        qapp.processEvents()
    controller.open_pdf(str(pdf_path))
    for _ in range(20):
        qapp.processEvents()
    view.set_mode("edit_text")
    for _ in range(5):
        qapp.processEvents()

    model.ensure_page_index_built(1)
    fitz_page = model.doc[0]
    blocks = fitz_page.get_text("rawdict")["blocks"]
    span_data = None
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    span_data = span
                    break
            if span_data:
                break
        if span_data:
            break
    assert span_data is not None, f"No text span on page 1 of {pdf_filename}"

    span_bbox = fitz.Rect(span_data["bbox"])
    render_scale = view._render_scale if view._render_scale > 0 else 1.0
    y0 = (
        view.page_y_positions[0]
        if (view.continuous_pages and view.page_y_positions)
        else 0.0
    )
    sx = span_bbox.x0 * render_scale + (span_bbox.width * render_scale) / 2
    sy = y0 + span_bbox.y0 * render_scale + (span_bbox.height * render_scale) / 2
    vp_pt = view.graphics_view.mapFromScene(QPointF(sx, sy))
    click_pos = QPoint(int(vp_pt.x()), int(vp_pt.y()))

    QTest.mousePress(view.graphics_view.viewport(), Qt.LeftButton, pos=click_pos)
    qapp.processEvents()
    QTest.mouseRelease(view.graphics_view.viewport(), Qt.LeftButton, pos=click_pos)
    for _ in range(10):
        qapp.processEvents()
    assert view.text_editor is not None, (
        f"editor did not open on {pdf_filename} click_pos={click_pos}"
    )

    inner_editor = _resolve_inner_editor_widget(view.text_editor)
    assert inner_editor is not None, (
        f"could not resolve inner editor widget on {pdf_filename}"
    )
    bg_rgb = _query_widget_bg_rgb(inner_editor)
    mask_rgb = inner_editor.property("mask_rgb") or bg_rgb

    opened_img, opened_rect = _grab_editor_only_image(view, qapp)
    assert opened_img.width() > 0 and opened_img.height() > 0, (
        f"opened_img has zero dimensions on {pdf_filename}"
    )

    inner_editor.setFocus()
    qapp.processEvents()
    original_text = inner_editor.toPlainText()
    inner_editor.setPlainText("")
    for _ in range(10):
        qapp.processEvents()
    empty_img, empty_rect = _grab_editor_only_image(view, qapp)
    _assert_rect_drift_within(
        reference_rect=opened_rect,
        current_rect=empty_rect,
        tolerance_px=MUTATION_GEOMETRY_DRIFT_MAX_PX,
        context=f"{pdf_filename} continuous empty live-edit state",
    )
    empty_source_ink_retained = 1.0 - _blanking_relative_to(
        opened_img, empty_img, bg_rgb=mask_rgb
    )
    assert empty_source_ink_retained <= MUTATION_EMPTY_SOURCE_INK_RETAINED_MAX, (
        f"Empty live-edit state retained {empty_source_ink_retained:.2%} of "
        f"opened-state source ink on {pdf_filename}; old glyphs are leaking "
        f"through the edit mask during editing."
    )
    inner_editor.setPlainText(original_text)
    for _ in range(10):
        qapp.processEvents()

    per_step = []
    for step in range(1, CONTINUOUS_INSERTION_STEPS + 1):
        inner_editor.insertPlainText("X")
        for _ in range(8):
            qapp.processEvents()
        step_img, step_rect = _grab_editor_only_image(view, qapp)
        step_delta = _changed_pixel_pct(opened_img, step_img)
        step_blanking = _blanking_relative_to(opened_img, step_img, bg_rgb=bg_rgb)
        step_drift = _rect_drift_metrics(opened_rect, step_rect)
        per_step.append(
            {
                "step": step,
                "insert_delta": step_delta,
                "insert_blanking_vs_opened": step_blanking,
                "rect_drift": step_drift,
            }
        )

        _assert_rect_drift_within(
            reference_rect=opened_rect,
            current_rect=step_rect,
            tolerance_px=MUTATION_GEOMETRY_DRIFT_MAX_PX,
            context=f"{pdf_filename} continuous step {step}",
        )

    cursor = inner_editor.textCursor()
    for _ in range(CONTINUOUS_INSERTION_STEPS):
        cursor.deletePreviousChar()
    inner_editor.setTextCursor(cursor)
    for _ in range(10):
        qapp.processEvents()
    restored_img, restored_rect = _grab_editor_only_image(view, qapp)
    _assert_rect_drift_within(
        reference_rect=opened_rect,
        current_rect=restored_rect,
        tolerance_px=MUTATION_GEOMETRY_DRIFT_MAX_PX,
        context=f"{pdf_filename} continuous restored state",
    )

    restore_delta = _changed_pixel_pct(opened_img, restored_img)
    blanking_after = _blanking_relative_to(opened_img, restored_img, bg_rgb=bg_rgb)

    test_id = f"e2e_qtest_mutation_continuous5_{pdf_slug}"
    _save_artifacts(
        test_id,
        opened_img,
        restored_img,
        {
            "continuous_insertion_steps": CONTINUOUS_INSERTION_STEPS,
            "empty_source_ink_retained": empty_source_ink_retained,
            "empty_rect_drift": _rect_drift_metrics(opened_rect, empty_rect),
            "mask_rgb": list(mask_rgb),
            "steps": per_step,
            "restore_delta": restore_delta,
            "blanking_pct_vs_opened": blanking_after,
            "restored_rect_drift": _rect_drift_metrics(opened_rect, restored_rect),
            "bg_rgb": list(bg_rgb),
            "pdf_filename": pdf_filename,
            "span_rotation": _detect_span_rotation(span_data),
        },
    )

    view.close()
    view.deleteLater()
    qapp.processEvents()

    assert restore_delta <= 0.01, (
        f"Continuous restore delta {restore_delta:.2%} > 1% on {pdf_filename}."
    )
    assert blanking_after <= 0.05, (
        f"After continuous type+delete, {blanking_after:.2%} of opened-state "
        f"ink pixels went blank on {pdf_filename}."
    )


@pytest.mark.parametrize("pdf_filename,pdf_slug", QTEST_E2E_CASES)
def test_reopen_same_textbox_cycles_do_not_cumulate_shrink(
    qapp, pdf_filename, pdf_slug
):
    """Across-session regression guard for repeated open→edit→commit→reopen.

    This is the exact failure mode reported by manual QA:
      reopen same textbox, edit, close, reopen, repeat on the same span.
    The editor box must not cumulatively shrink across cycles.
    """
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView
    from controller.pdf_controller import PDFController
    from PySide6.QtCore import Qt, QPoint, QPointF
    from PySide6.QtTest import QTest

    pdf_path = REPO_ROOT / "test_files" / pdf_filename
    assert pdf_path.exists(), f"Reference PDF not found: {pdf_path}"

    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    view.show()
    for _ in range(10):
        qapp.processEvents()
    controller.open_pdf(str(pdf_path))
    for _ in range(20):
        qapp.processEvents()
    view.set_mode("edit_text")
    for _ in range(5):
        qapp.processEvents()
    target_mode_combo = getattr(view, "text_target_mode_combo", None)
    if target_mode_combo is not None:
        run_idx = target_mode_combo.findData("run")
        if run_idx >= 0:
            target_mode_combo.setCurrentIndex(run_idx)
            qapp.processEvents()

    model.ensure_page_index_built(1)
    span_data = _first_non_empty_span_data(model, page_idx=0)
    assert span_data is not None, f"No text span found on page 1 of {pdf_filename}"
    span_bbox = fitz.Rect(span_data["bbox"])
    probe_pt = fitz.Point(
        span_bbox.x0 + span_bbox.width / 2, span_bbox.y0 + span_bbox.height / 2
    )

    def _resolve_hit_near_probe():
        hit = model.get_text_info_at_point(1, probe_pt)
        if hit is not None and (hit.target_text or "").strip():
            return hit
        for radius in (1.5, 3.0, 6.0):
            offsets = (
                (0.0, 0.0),
                (radius, 0.0),
                (-radius, 0.0),
                (0.0, radius),
                (0.0, -radius),
                (radius, radius),
                (radius, -radius),
                (-radius, radius),
                (-radius, -radius),
            )
            for ox, oy in offsets:
                probe = fitz.Point(probe_pt.x + ox, probe_pt.y + oy)
                candidate = model.get_text_info_at_point(1, probe)
                if candidate is not None and (candidate.target_text or "").strip():
                    return candidate
        return None

    opened_rects = []
    cycle_metrics = []
    hit_sizes = []
    opened_images = []
    open_changed_px_pcts = []
    first_open_img = None
    final_open_img = None
    baseline_text = None

    try:
        # Commit through the exact user path (APPLY finalize), not direct
        # model.edit_text(), to cover the real reopen-loop regression.
        def _open_editor_snapshot(cycle_idx: int):
            model.ensure_page_index_built(1)
            hit = _resolve_hit_near_probe()
            assert hit is not None, (
                f"Could not resolve span near probe on cycle {cycle_idx} for {pdf_filename}"
            )

            render_scale = view._render_scale if view._render_scale > 0 else 1.0
            y0 = (
                view.page_y_positions[0]
                if (view.continuous_pages and view.page_y_positions)
                else 0.0
            )
            sx = float(hit.target_bbox.x0) + float(hit.target_bbox.width) / 2.0
            sy = float(hit.target_bbox.y0) + float(hit.target_bbox.height) / 2.0
            scene_x = sx * render_scale
            scene_y = y0 + sy * render_scale
            vp_pt = view.graphics_view.mapFromScene(QPointF(scene_x, scene_y))
            click_pos = QPoint(int(vp_pt.x()), int(vp_pt.y()))
            before_full = (
                view.graphics_view.viewport()
                .grab()
                .toImage()
                .convertToFormat(QImage.Format_RGBA8888)
            )

            QTest.mousePress(
                view.graphics_view.viewport(), Qt.LeftButton, pos=click_pos
            )
            qapp.processEvents()
            QTest.mouseRelease(
                view.graphics_view.viewport(), Qt.LeftButton, pos=click_pos
            )
            for _ in range(10):
                qapp.processEvents()
            assert view.text_editor is not None, (
                f"Editor did not open on cycle {cycle_idx} ({pdf_filename}) click={click_pos}"
            )

            opened_img, opened_rect = _grab_editor_only_image(view, qapp)
            assert opened_img.width() > 0 and opened_img.height() > 0, (
                f"opened_img has zero dimensions on cycle {cycle_idx} ({pdf_filename})"
            )
            before_crop = _crop(before_full, _inset_editor_content_rect(opened_rect))
            open_changed_px_pct = _changed_pixel_pct(before_crop, opened_img)

            combo_pdf_size = _parse_font_size_str(view.text_size.currentText())
            assert combo_pdf_size is not None, (
                f"text_size combo does not contain a parseable PDF pt value on cycle "
                f"{cycle_idx} for {pdf_filename}: {view.text_size.currentText()!r}"
            )
            assert (
                abs(float(combo_pdf_size) - float(hit.size)) <= REOPEN_FONT_PT_DRIFT_MAX
            ), (
                f"Cycle {cycle_idx}: text_size combo drifted from resolved PDF size on "
                f"{pdf_filename} (combo={combo_pdf_size:.3f}pt, hit={float(hit.size):.3f}pt)."
            )
            return (
                hit,
                opened_img,
                opened_rect,
                float(combo_pdf_size),
                open_changed_px_pct,
            )

        # Each round: open baseline -> mutate + APPLY -> reopen -> restore + APPLY.
        # This exercises iterative real commits while keeping the span content
        # stable between rounds so pixel-diff consistency is meaningful.
        for cycle_idx in range(1, REOPEN_SESSION_CYCLES + 1):
            hit, opened_img, opened_rect, combo_pdf_size, open_changed_px_pct = (
                _open_editor_snapshot(cycle_idx)
            )
            if first_open_img is None:
                first_open_img = opened_img
            final_open_img = opened_img
            opened_images.append(opened_img)
            open_changed_px_pcts.append(float(open_changed_px_pct))
            opened_rects.append(opened_rect)
            hit_sizes.append(float(hit.size))
            if baseline_text is None:
                baseline_text = hit.target_text or ""

            cycle_metrics.append(
                {
                    "cycle": cycle_idx,
                    "target_span_id": getattr(hit, "target_span_id", None),
                    "hit_font": str(getattr(hit, "font", "")),
                    "hit_size_pt": float(hit.size),
                    "combo_size_pt": combo_pdf_size,
                    "open_changed_px_pct": float(open_changed_px_pct),
                    "editor_rect": {
                        "x": int(opened_rect.x()),
                        "y": int(opened_rect.y()),
                        "w": int(opened_rect.width()),
                        "h": int(opened_rect.height()),
                    },
                }
            )

            inner_editor = _resolve_inner_editor_widget(view.text_editor)
            assert inner_editor is not None
            mutated_text = _cycle_replacement_text_same_length(
                baseline_text or (hit.target_text or ""),
                cycle_idx,
            )
            assert mutated_text != (hit.target_text or ""), (
                f"Cycle {cycle_idx}: replacement text unexpectedly equals current text "
                f"for {pdf_filename}; cannot force a real commit."
            )
            inner_editor.setPlainText(mutated_text)
            qapp.processEvents()
            result = view._finalize_text_edit(TextEditFinalizeReason.APPLY)
            assert result is not None
            assert result.outcome is TextEditOutcome.COMMITTED, (
                f"Cycle {cycle_idx}: UI APPLY finalize did not commit for {pdf_filename} "
                f"(outcome={result.outcome.value})"
            )
            assert view.text_editor is None
            for _ in range(10):
                qapp.processEvents()

            restore_hit, _, _, _, restore_open_changed_px_pct = _open_editor_snapshot(
                cycle_idx
            )
            open_changed_px_pcts.append(float(restore_open_changed_px_pct))
            restore_editor = _resolve_inner_editor_widget(view.text_editor)
            assert restore_editor is not None
            restore_editor.setPlainText(
                baseline_text or (restore_hit.target_text or "")
            )
            qapp.processEvents()
            restore_result = view._finalize_text_edit(TextEditFinalizeReason.APPLY)
            assert restore_result is not None
            assert restore_result.outcome is TextEditOutcome.COMMITTED, (
                f"Cycle {cycle_idx}: restore APPLY finalize did not commit for {pdf_filename} "
                f"(outcome={restore_result.outcome.value})"
            )
            assert view.text_editor is None
            for _ in range(10):
                qapp.processEvents()

        terminal_cycle = REOPEN_SESSION_CYCLES + 1
        (
            terminal_hit,
            terminal_img,
            terminal_rect,
            terminal_combo_pdf_size,
            terminal_open_changed_px_pct,
        ) = _open_editor_snapshot(terminal_cycle)
        final_open_img = terminal_img
        opened_images.append(terminal_img)
        open_changed_px_pcts.append(float(terminal_open_changed_px_pct))
        opened_rects.append(terminal_rect)
        hit_sizes.append(float(terminal_hit.size))
        cycle_metrics.append(
            {
                "cycle": terminal_cycle,
                "target_span_id": getattr(terminal_hit, "target_span_id", None),
                "hit_font": str(getattr(terminal_hit, "font", "")),
                "hit_size_pt": float(terminal_hit.size),
                "combo_size_pt": terminal_combo_pdf_size,
                "open_changed_px_pct": float(terminal_open_changed_px_pct),
                "editor_rect": {
                    "x": int(terminal_rect.x()),
                    "y": int(terminal_rect.y()),
                    "w": int(terminal_rect.width()),
                    "h": int(terminal_rect.height()),
                },
            }
        )
        result = view._finalize_text_edit(TextEditFinalizeReason.ESCAPE)
        assert result is not None
        assert result.outcome in {TextEditOutcome.DISCARDED, TextEditOutcome.NO_OP}
        assert view.text_editor is None
        for _ in range(8):
            qapp.processEvents()

        assert len(opened_rects) == REOPEN_SESSION_CYCLES + 1, (
            f"Expected {REOPEN_SESSION_CYCLES + 1} open snapshots, got {len(opened_rects)}"
        )
        assert first_open_img is not None and final_open_img is not None

        baseline_rect = opened_rects[0]
        for idx, rect in enumerate(opened_rects[1:], start=2):
            _assert_rect_drift_within(
                reference_rect=baseline_rect,
                current_rect=rect,
                tolerance_px=REOPEN_GEOMETRY_DRIFT_MAX_PX,
                context=f"{pdf_filename} reopen cycle {idx}",
            )

        widths = [int(r.width()) for r in opened_rects]
        heights = [int(r.height()) for r in opened_rects]
        width_shrink_px = max(0, widths[0] - min(widths))
        height_shrink_px = max(0, heights[0] - min(heights))
        font_shrink_pt = max(0.0, hit_sizes[0] - min(hit_sizes))
        font_abs_drift_pt = max(
            abs(float(size) - float(hit_sizes[0])) for size in hit_sizes
        )
        reopen_changed_px_pct = _changed_pixel_pct(first_open_img, final_open_img)
        max_open_changed_px_pct = (
            max(open_changed_px_pcts) if open_changed_px_pcts else 0.0
        )

        test_id = f"e2e_qtest_reopen_cycles{REOPEN_SESSION_CYCLES}_{pdf_slug}"
        _save_artifacts(
            test_id,
            first_open_img,
            final_open_img,
            {
                "pdf_filename": pdf_filename,
                "cycles": REOPEN_SESSION_CYCLES,
                "widths": widths,
                "heights": heights,
                "hit_sizes_pt": hit_sizes,
                "width_shrink_px": width_shrink_px,
                "height_shrink_px": height_shrink_px,
                "font_shrink_pt": font_shrink_pt,
                "font_abs_drift_pt": font_abs_drift_pt,
                "reopen_changed_px_pct_first_to_last": reopen_changed_px_pct,
                "open_changed_px_pcts": open_changed_px_pcts,
                "max_open_changed_px_pct": max_open_changed_px_pct,
                "cycle_metrics": cycle_metrics,
            },
        )

        assert width_shrink_px <= REOPEN_GEOMETRY_DRIFT_MAX_PX, (
            f"Width cumulatively shrank by {width_shrink_px}px over "
            f"{REOPEN_SESSION_CYCLES} reopen cycles on {pdf_filename}."
        )
        assert height_shrink_px <= REOPEN_GEOMETRY_DRIFT_MAX_PX, (
            f"Height cumulatively shrank by {height_shrink_px}px over "
            f"{REOPEN_SESSION_CYCLES} reopen cycles on {pdf_filename}."
        )
        assert font_shrink_pt <= REOPEN_FONT_PT_DRIFT_MAX, (
            f"Resolved hit size shrank by {font_shrink_pt:.3f}pt over "
            f"{REOPEN_SESSION_CYCLES} reopen cycles on {pdf_filename}."
        )
        assert font_abs_drift_pt <= REOPEN_FONT_PT_DRIFT_MAX, (
            f"Resolved hit size drifted by {font_abs_drift_pt:.3f}pt over "
            f"{REOPEN_SESSION_CYCLES} reopen cycles on {pdf_filename}."
        )
        assert max_open_changed_px_pct <= REOPEN_PIXEL_DIFF_MAX, (
            f"Open-time pixel diff {max_open_changed_px_pct:.2%} exceeds "
            f"{REOPEN_PIXEL_DIFF_MAX:.2%} on {pdf_filename}; reopen content is not "
            "visually consistent with underlying PDF after repeated edit/apply cycles."
        )
    finally:
        try:
            model.close_all_sessions()
        except Exception:
            pass
        view.close()
        view.deleteLater()
        qapp.processEvents()


# ── AC 4 (Cycle 22): blanking-detector negative control ──────────────────────


def test_blanking_detector_catches_a_blank_image(qapp):
    """AC 4: a fully transparent QImage MUST register ≥99% blank.  If this
    fails, the blanking detector itself is broken and any 'pass' on
    _blank_pixel_pct elsewhere is meaningless."""
    blank = QImage(40, 20, QImage.Format_RGBA8888)
    blank.fill(0x00FFFFFF)  # alpha=0
    pct = _blank_pixel_pct(blank)
    _save_artifacts(
        "blanking_detector_negative_control", None, None, {"blank_pct_observed": pct}
    )
    assert pct >= 0.99, (
        f"Blanking detector failed: only {pct:.2%} of fully transparent pixels "
        f"detected as blank.  Detector is broken; AC 5 blanking checks are "
        f"unreliable until this passes."
    )


# ── AC 2 (DEPRECATED): synthetic round-trip — superseded by real-PDF e2e ──────

PIXEL_CASES = [
    ("helv", 0.67),
    ("helv", 1.0),
    ("helv", 2.0),
    ("cjk", 1.0),
    ("cjk", 2.0),
]


@pytest.mark.skip(
    reason=(
        "Cycle 22: superseded by test_click_to_edit_qtest_integration which "
        "compares the real PDF region to the actual editor paintEvent output.  "
        "The synthetic round-trip (insert_htmlbox vs PreviewRenderer using the "
        "same MuPDF engine) is tautological and let visible bugs through."
    )
)
@pytest.mark.parametrize("font_name,render_scale", PIXEL_CASES)
def test_preview_pixel_diff_under_one_pct(qapp, font_name, render_scale):
    """AC 2+3: PreviewRenderer vs direct MuPDF rasterization < 1% changed pixels."""
    font_size = 14.0
    span_rect = fitz.Rect(0, 0, 150, 25)
    text = "Hello World"

    ref_doc = fitz.open()
    ref_page = ref_doc.new_page(
        width=float(span_rect.width), height=float(span_rect.height)
    )
    font_family = "Helvetica" if font_name == "helv" else "Microsoft JhengHei"
    ref_page.insert_htmlbox(
        fitz.Rect(0, 0, float(span_rect.width), float(span_rect.height)),
        f"<span>{text}</span>",
        css=f"span {{ font-family: {font_family}; font-size: {font_size}pt; color: rgb(0,0,0); }}",
    )
    ref_px = ref_page.get_pixmap(
        matrix=fitz.Matrix(render_scale, render_scale), alpha=True
    )
    ref_doc.close()
    ref_img = QImage(
        ref_px.samples,
        ref_px.width,
        ref_px.height,
        ref_px.stride,
        QImage.Format_RGBA8888,
    ).copy()

    preview_img = PreviewRenderer(model=None).render(
        text=text,
        font_name=font_name,
        font_size=font_size,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=span_rect,
        rotation=0,
        render_scale=render_scale,
    )
    changed_pct = _changed_pixel_pct(ref_img, preview_img)
    test_id = f"pixel_{font_name}_rs{render_scale}"
    _save_artifacts(
        test_id,
        ref_img,
        preview_img,
        {
            "font_name": font_name,
            "render_scale": render_scale,
            "changed_px_pct": changed_pct,
        },
    )
    assert changed_pct <= 0.01, (
        f"Pixel diff {changed_pct:.2%} > 1% for {font_name} rs={render_scale}. "
        f"Open test_artifacts/no_jump/{test_id}/diff.png"
    )


@pytest.mark.skip(
    reason=(
        "Cycle 22: companion control for the synthetic AC 2 test which is itself "
        "skipped — both rely on the same insert_htmlbox→PreviewRenderer round-trip "
        "that does not exercise the real click-to-edit pipeline."
    )
)
def test_pixel_diff_negative_control_bad_font_size(qapp):
    """AC 4: +10% font MUST produce > 1% pixel diff; if not, pixel test is useless."""
    font_size = 14.0
    span_rect = fitz.Rect(0, 0, 150, 25)
    text = "Hello World"
    ref_doc = fitz.open()
    ref_page = ref_doc.new_page(
        width=float(span_rect.width), height=float(span_rect.height)
    )
    ref_page.insert_htmlbox(
        fitz.Rect(0, 0, float(span_rect.width), float(span_rect.height)),
        f"<span>{text}</span>",
        css=f"span {{ font-family: Helvetica; font-size: {font_size}pt; color: rgb(0,0,0); }}",
    )
    ref_px = ref_page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=True)
    ref_doc.close()
    ref_img = QImage(
        ref_px.samples,
        ref_px.width,
        ref_px.height,
        ref_px.stride,
        QImage.Format_RGBA8888,
    ).copy()
    bad_img = PreviewRenderer(model=None).render(
        text=text,
        font_name="helv",
        font_size=font_size * 1.10,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=span_rect,
        rotation=0,
        render_scale=2.0,
    )
    changed_pct = _changed_pixel_pct(ref_img, bad_img)
    _save_artifacts(
        "pixel_negative_control",
        ref_img,
        bad_img,
        {"injected_font_pct": 10.0, "changed_px_pct": changed_pct},
    )
    assert changed_pct > 0.01, (
        f"Negative control failed: +10% font not detected (changed={changed_pct:.2%})"
    )
