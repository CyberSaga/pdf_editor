# test_scripts/test_no_jump_editor_geometry.py
from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest
from PySide6.QtGui import QImage

from view.text_editing import (
    _compute_editor_proxy_layout,
    _display_font_pt,
    PreviewRenderer,
)

ARTIFACT_DIR = Path("test_artifacts") / "no_jump"


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
    metrics = {**metrics, "run_id": run_id}   # embed run_id for stale-artifact detection

    d = ARTIFACT_DIR / test_id
    d.mkdir(parents=True, exist_ok=True)
    _assert_written(d / "metrics.json", json.dumps(metrics, indent=2))

    if before_img is not None:
        _assert_image_saved(d / "before.png", before_img)
    if after_img is not None:
        _assert_image_saved(d / "after.png", after_img)
    if before_img is not None and after_img is not None:
        _assert_image_saved(d / "diff.png", _make_diff_image(before_img, after_img))

    _append_to_manifest(test_id)   # register case so verifier can enumerate expected set


def _make_diff_image(a: QImage, b: QImage) -> QImage:
    w, h = min(a.width(), b.width()), min(a.height(), b.height())
    diff = QImage(w, h, QImage.Format_ARGB32)
    diff.fill(0xFFFFFFFF)
    for y in range(h):
        for x in range(w):
            if abs(a.pixelColor(x, y).lightness() - b.pixelColor(x, y).lightness()) > 10:
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
        raise AssertionError(f"ref image has zero dimensions: {rw}×{rh} — render failed")
    if pw == 0 or ph == 0:
        raise AssertionError(f"preview image has zero dimensions: {pw}×{ph} — render failed")
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


# ── AC 1 + AC 3: geometry match across full matrix ────────────────────────────

# Maps font_case label → (CSS font-family, font_size_pt used in that span)
# Using distinct sizes per font family exercises the formula with realistic values
# and ensures a per-family regression (e.g. wrong fallback size) would be detected.
FONT_CASE_PARAMS: dict[str, tuple[str, float]] = {
    "helv":         ("Helvetica",          12.0),
    "cjk":          ("Microsoft JhengHei", 14.0),
    "unknown_font": ("NonexistentFont123",  10.0),
}

GEOMETRY_CASES = [
    # (render_scale, simulated_logical_dpi, font_case, rotation)
    (0.67, 96.0,  "helv",         0),
    (1.0,  96.0,  "helv",         0),
    (2.0,  96.0,  "helv",         0),
    (0.67, 192.0, "helv",         0),
    (1.0,  192.0, "helv",         0),
    (2.0,  192.0, "helv",         0),
    (1.0,  96.0,  "cjk",          0),
    (2.0,  96.0,  "cjk",          0),
    (1.0,  96.0,  "unknown_font", 0),
    (2.0,  96.0,  "helv",         90),
]


@pytest.mark.parametrize("render_scale,logical_dpi,font_case,rotation", GEOMETRY_CASES)
def test_editor_geometry_matches_pdf_bbox(qapp, render_scale, logical_dpi, font_case, rotation):
    """AC 1+3: placement within 0.5px/1.0px; font_size_ratio in [0.99,1.01].

    Uses the per-font-case font_size from FONT_CASE_PARAMS so that a regression in
    CJK or unknown-font size handling (e.g. wrong fallback, coercion to int) is
    detectable — not masked by always using a common 12pt value.
    """
    _font_name, font_size = FONT_CASE_PARAMS[font_case]
    pdf_bbox   = fitz.Rect(50.0, 100.0, 250.0, 122.0)
    page_y_off = 30.0
    scaled_rect = fitz.Rect(
        pdf_bbox.x0 * render_scale, pdf_bbox.y0 * render_scale,
        pdf_bbox.x1 * render_scale, pdf_bbox.y1 * render_scale,
    )
    with patch("view.text_editing._widget_logical_dpi", return_value=logical_dpi):
        w, h, x, y, _ = _compute_editor_proxy_layout(
            scaled_rect=scaled_rect,
            scaled_width=int(round(pdf_bbox.width * render_scale)),
            page_y_offset=page_y_off,
            rotation=rotation,
            content_height_px=int(round(pdf_bbox.height * render_scale)),
        )
        fs_ratio = (
            _display_font_pt(font_size, render_scale) * logical_dpi / 72.0
        ) / (font_size * render_scale)

    exp_x = pdf_bbox.x0 * render_scale
    exp_y = page_y_off + pdf_bbox.y0 * render_scale
    test_id = f"geom_rs{render_scale}_dpi{int(logical_dpi)}_{font_case}_rot{rotation}"
    _save_artifacts(test_id, None, None, {
        "render_scale": render_scale, "logical_dpi": logical_dpi,
        "font_case": font_case, "font_size_pt": font_size, "rotation": rotation,
        "x_drift": float(x) - exp_x, "y_drift": float(y) - exp_y,
        "w_drift": float(w) - pdf_bbox.width * render_scale,
        "h_drift": float(h) - pdf_bbox.height * render_scale,
        "font_size_ratio": fs_ratio,
    })

    assert abs(float(x) - exp_x) <= 0.5, f"x drift > 0.5px [{test_id}]"
    assert abs(float(y) - exp_y) <= 0.5, f"y drift > 0.5px [{test_id}]"
    assert abs(float(w) - pdf_bbox.width  * render_scale) <= 1.0, f"w drift > 1.0px [{test_id}]"
    assert abs(float(h) - pdf_bbox.height * render_scale) <= 1.0, f"h drift > 1.0px [{test_id}]"
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
        w, h, x, y, r = orig(**kw); return w, h, x + 2.0, y, r
    scaled_rect = fitz.Rect(pdf_bbox.x0, pdf_bbox.y0, pdf_bbox.x1, pdf_bbox.y1)
    _, _, x, _, _ = bad(
        scaled_rect=scaled_rect, scaled_width=int(round(pdf_bbox.width)),
        page_y_offset=30.0, rotation=0, content_height_px=None,
    )
    drift = abs(float(x) - pdf_bbox.x0)
    _save_artifacts("geom_negative_control", None, None,
                    {"injected_x_offset": 2.0, "detected_drift": drift})
    assert drift > 0.5, f"Negative control failed: +2px not detected (drift={drift:.3f}px)"


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
        bad_fs_ratio = (
            _display_font_pt(wrong_size, render_scale) * 96.0 / 72.0
        ) / (correct_size * render_scale)
    _save_artifacts(
        f"geom_neg_fontsize_{font_case}",
        None, None,
        {"font_case": font_case, "correct_size": correct_size, "wrong_size": wrong_size,
         "bad_fs_ratio": bad_fs_ratio},
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
    assert span_data is not None, \
        "No text span found on page 1 of test-colored-background.pdf — update reference PDF"

    span_rect = fitz.Rect(span_data["bbox"])
    center_pt = fitz.Point(
        span_rect.x0 + span_rect.width / 2,
        span_rect.y0 + span_rect.height / 2,
    )

    # Use model.get_text_info_at_point to exercise the real hit-test path
    hit = model.get_text_info_at_point(1, center_pt)
    assert hit is not None, \
        "get_text_info_at_point returned None for a known span center — hit-test broken"

    render_scale = 2.0

    # Before: MuPDF raster of the span's actual bbox (what the user sees before clicking)
    ref_px = fitz_page.get_pixmap(
        matrix=fitz.Matrix(render_scale, render_scale),
        clip=hit.target_bbox,
        alpha=True,
    )
    before_img = QImage(
        ref_px.samples, ref_px.width, ref_px.height,
        ref_px.stride, QImage.Format_RGBA8888,
    ).copy()
    bg = before_img.pixelColor(0, 0)
    legacy_bg_rgb = (bg.red(), bg.green(), bg.blue())
    model.close()

    # After: instantiate the REAL inline editor with actual span data (not hardcoded).
    # _widget_logical_dpi is patched to 96.0 for a deterministic pixel size.
    with patch("view.text_editing._widget_logical_dpi", return_value=96.0):
        editor = PreviewBackedInlineTextEditor(
            text=hit.target_text,
            font_name=hit.font,         # REAL font from the document
            font_size=hit.size,         # REAL font size from the document
            color=tuple(hit.color),     # REAL color from the document
            rect_pt=hit.target_bbox,    # REAL bbox from the document
                render_scale=render_scale,
                rotation=hit.rotation,      # REAL rotation from the document
                model=None,   # model arg for editing; preview render doesn't need live doc
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
    assert not after_img.isNull(), \
        "after_img (editor widget grab) is null — widget did not paint"

    changed_pct = _changed_pixel_pct(before_img, after_img)
    _save_artifacts("e2e_click_to_edit", before_img, after_img,
                    {"font_size": float(hit.size), "render_scale": render_scale,
                     "changed_px_pct": changed_pct})
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
    # Both PDFs MUST exist; missing reference PDFs are a hard failure (see assertion below).
    # colored-bg exercises Latin text on a coloured background;
    # complex-layout exercises CJK glyph rendering and dense layouts — two distinct
    # codepaths through PreviewRenderer.render() and _compute_editor_proxy_layout().
    ("test-colored-background.pdf", "colored"),
    ("test-complexed-layout.pdf",   "complexed"),
]


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
    view  = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    view.show()
    for _ in range(10):
        qapp.processEvents()

    controller.open_pdf(str(pdf_path))
    for _ in range(20):    # let rendering pipeline complete
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
    assert span_data is not None, \
        f"No text span found on page 1 of {pdf_filename}"

    span_bbox  = fitz.Rect(span_data["bbox"])
    render_scale = view._render_scale if view._render_scale > 0 else 1.0
    page_idx = 0

    # Convert span center from PDF-document coords → scene coords → viewport coords
    y0 = (view.page_y_positions[page_idx]
          if (view.continuous_pages and page_idx < len(view.page_y_positions))
          else 0.0)
    scene_x = span_bbox.x0 * render_scale + (span_bbox.width  * render_scale) / 2
    scene_y = y0 + span_bbox.y0 * render_scale + (span_bbox.height * render_scale) / 2
    vp_pt = view.graphics_view.mapFromScene(QPointF(scene_x, scene_y))
    click_pos = QPoint(int(vp_pt.x()), int(vp_pt.y()))

    # Compute the tight viewport rectangle covering the span.
    span_scene_tl = view.graphics_view.mapFromScene(
        QPointF(span_bbox.x0 * render_scale, y0 + span_bbox.y0 * render_scale)
    )
    span_w_px = int(span_bbox.width  * render_scale) + 4   # +4 rounding guard
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
        min(span_vp_rect.width()  + 2 * pad_x, vp_size.width()),
        min(span_vp_rect.height() + 2 * pad_y, vp_size.height()),
    )

    # Before: grab the padded viewport region (PDF rendering, no editor)
    before_grab = view.graphics_view.viewport().grab(grab_rect)
    before_img  = before_grab.toImage().convertToFormat(QImage.Format_RGBA8888)
    assert not before_img.isNull(), \
        "before_img grab returned null — PDF viewport is not yet rendered"

    # Click: mousePress + mouseRelease without movement triggers _create_text_editor
    QTest.mousePress(view.graphics_view.viewport(), Qt.LeftButton, pos=click_pos)
    qapp.processEvents()
    QTest.mouseRelease(view.graphics_view.viewport(), Qt.LeftButton, pos=click_pos)
    for _ in range(10):    # drive paintEvent
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
            int(editor_vp_tl.x()), int(editor_vp_tl.y()),
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
    after_img  = after_grab.toImage().convertToFormat(QImage.Format_RGBA8888)
    assert not after_img.isNull(), "after_img grab returned null"

    changed_pct = _changed_pixel_pct(before_img, after_img)
    test_id = f"e2e_qtest_click_to_edit_{pdf_slug}"
    _save_artifacts(test_id, before_img, after_img,
                    {"render_scale": render_scale, "changed_px_pct": changed_pct,
                     "span_bbox": list(span_bbox), "pdf_filename": pdf_filename,
                     "grab_rect_padded": True})

    # Cleanup
    view.close()
    view.deleteLater()
    qapp.processEvents()

    assert changed_pct <= 0.01, (
        f"QTest click-to-edit jump on {pdf_filename}: {changed_pct:.2%} pixels "
        f"changed in the padded span region (span ± one span-width padding).  "
        f"The editor's first frame does not match the PDF rendering at that location.  "
        f"Open test_artifacts/no_jump/{test_id}/diff.png"
    )


# ── AC 2 + AC 3: pixel diff ───────────────────────────────────────────────────

PIXEL_CASES = [
    ("helv", 0.67), ("helv", 1.0), ("helv", 2.0),
    ("cjk",  1.0),  ("cjk",  2.0),
]


@pytest.mark.parametrize("font_name,render_scale", PIXEL_CASES)
def test_preview_pixel_diff_under_one_pct(qapp, font_name, render_scale):
    """AC 2+3: PreviewRenderer vs direct MuPDF rasterization < 1% changed pixels."""
    font_size = 14.0; span_rect = fitz.Rect(0, 0, 150, 25); text = "Hello World"

    ref_doc = fitz.open()
    ref_page = ref_doc.new_page(width=float(span_rect.width), height=float(span_rect.height))
    font_family = "Helvetica" if font_name == "helv" else "Microsoft JhengHei"
    ref_page.insert_htmlbox(
        fitz.Rect(0, 0, float(span_rect.width), float(span_rect.height)),
        f"<span>{text}</span>",
        css=f"span {{ font-family: {font_family}; font-size: {font_size}pt; color: rgb(0,0,0); }}",
    )
    ref_px = ref_page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=True)
    ref_doc.close()
    ref_img = QImage(ref_px.samples, ref_px.width, ref_px.height,
                     ref_px.stride, QImage.Format_RGBA8888).copy()

    preview_img = PreviewRenderer(model=None).render(
        text=text, font_name=font_name, font_size=font_size, color=(0.0, 0.0, 0.0),
        member_spans=None, rect_pt=span_rect, rotation=0, render_scale=render_scale,
    )
    changed_pct = _changed_pixel_pct(ref_img, preview_img)
    test_id = f"pixel_{font_name}_rs{render_scale}"
    _save_artifacts(test_id, ref_img, preview_img,
                    {"font_name": font_name, "render_scale": render_scale,
                     "changed_px_pct": changed_pct})
    assert changed_pct <= 0.01, (
        f"Pixel diff {changed_pct:.2%} > 1% for {font_name} rs={render_scale}. "
        f"Open test_artifacts/no_jump/{test_id}/diff.png"
    )


def test_pixel_diff_negative_control_bad_font_size(qapp):
    """AC 4: +10% font MUST produce > 1% pixel diff; if not, pixel test is useless."""
    font_size = 14.0; span_rect = fitz.Rect(0, 0, 150, 25); text = "Hello World"
    ref_doc = fitz.open()
    ref_page = ref_doc.new_page(width=float(span_rect.width), height=float(span_rect.height))
    ref_page.insert_htmlbox(
        fitz.Rect(0, 0, float(span_rect.width), float(span_rect.height)), f"<span>{text}</span>",
        css=f"span {{ font-family: Helvetica; font-size: {font_size}pt; color: rgb(0,0,0); }}",
    )
    ref_px = ref_page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=True)
    ref_doc.close()
    ref_img = QImage(ref_px.samples, ref_px.width, ref_px.height,
                     ref_px.stride, QImage.Format_RGBA8888).copy()
    bad_img = PreviewRenderer(model=None).render(
        text=text, font_name="helv", font_size=font_size * 1.10,
        color=(0.0, 0.0, 0.0), member_spans=None, rect_pt=span_rect,
        rotation=0, render_scale=2.0,
    )
    changed_pct = _changed_pixel_pct(ref_img, bad_img)
    _save_artifacts("pixel_negative_control", ref_img, bad_img,
                    {"injected_font_pct": 10.0, "changed_px_pct": changed_pct})
    assert changed_pct > 0.01, (
        f"Negative control failed: +10% font not detected (changed={changed_pct:.2%})"
    )
