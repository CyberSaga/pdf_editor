# M3.6 Manual Verification Round-2 Defects — Investigation Findings

**Status:** Defect 1 (annotation rotation) FIXED 2026-07-17 — chokepoint helpers in
`model/tools/annotation_tool.py`, both write and read direction, 24 pixel-detection tests
in `test_scripts/test_annotation_rotation.py`; awaiting manual re-verify on the rotated
fixture. Defect 2 (render/GIL/memory) investigation complete, fix plan not yet written.
NEW defect discovered during verification: Python 3.10 `Path.resolve(strict=False)`
raises WinError 53 on unreachable UNC recent-file entries → `activate()` crash — FIXED
2026-07-17 via workflow (audit → TDD implement → adversarial verify): chokepoint guards in
preferences/`_canonicalize_path`/`single_instance` (fail-closed) + controller defense;
`test_recent_files_unc_robustness.py` (6); previously-failing suites 8 → 0. Lower-severity
inline save-time `resolve()` sites tracked as follow-up in TODOS.
**Source:** manual M3.6 checklist results (complex-vector responsiveness ✗×6, annotation placement ✗).
**Repro scripts (evidence):** `C:\Users\jiang\.claude\jobs\b31e9064\tmp\{repro_annot_offset,repro_annot_rotation2,repro_redact_rotation,perf_probe,gil_probe}.py` — re-runnable with `.venv\Scripts\python.exe`.

---

## Defect 1 — Annotation placement offset (rect/highlight/underline/strikeout)

**Symptom (user):** 呈現的位置都會比實際點選的位置往下往右偏移 (rendered annotation lands down-right of the click).

**Root cause (CONFIRMED empirically, PyMuPDF 1.27.1):**
`page.add_rect_annot / add_highlight_annot / add_underline_annot / add_strikeout_annot / add_text_annot`
interpret the given rect/point in **UNROTATED page coordinates**. The app passes
displayed-coordinate rects (from `_scene_rect_to_doc_rect`), which are correct only for
`/Rotate 0` pages. The HVAC fixture's pages have **rotation=270** (page 25:
`rect=(0,0,1191,842), rotation=270`) — measured raw placement error at rot=270 for a rect
drawn at displayed (100,100): dx≈-1pt dy≈+274pt (rect), underline dx≈+50 dy≈+275,
strikeout dx≈+32 dy≈+275 → exactly "down and right". `annot.rect` readback misleadingly
echoes the requested values, so only pixel-level verification catches it.

**Why every other feature looked correct:** text selection, object handles, note-marker
overlays and the inline editor all convert scene→doc and doc→scene through the *same*
helpers — any absolute bias cancels visually. Annotations are the only path where PyMuPDF
bakes the rect at absolute doc coordinates.

**Rotation-safe already:** `add_redact_annot` accepts displayed coords (verified: redact of
a displayed-coords word rect on a rot=270 page removes the word) → the text-commit engine
is NOT affected.

**Fix matrix (verified):**
- rect annot: `rect * page.derotation_matrix` (normalized) → pixel-exact at 90/180/270.
- highlight/underline/strikeout: derotated **rect alone is NOT enough** — the markup ink
  (underline at quad bottom edge, strikeout mid-height) follows quad orientation; at
  90/270 the line lands on a vertical edge. Must pass a corner-mapped `fitz.Quad`
  (map displayed rect corners through `derotation_matrix`, assign ul/ur/ll/lr roles by
  rotation so "bottom edge" stays the displayed bottom).
- note annot (`add_annotation`): derotate the point the same way. Note *move*
  (`move_annotation`) passes displayed points too — same fix.

**Fix protocol (per feedback-fix-bug-class-not-instances):** single chokepoint helper in
`model/tools/annotation_tool.py` (e.g. `_displayed_to_annot_geometry(page, rect|point)`),
applied at every `page.add_*_annot` call site; audit remaining sites passing view-derived
doc coords to PyMuPDF (`insert_htmlbox`/textbox add path, watermark placement, the
FreeText reconstruction at annotation_tool.py:330 which already passes
`rotate=page.rotation`). Red-light tests: pixel-detection on rot 0/90/180/270 pages for
all four types (pattern in repro scripts; `annot.rect` readback must NOT be the oracle).

---

## Defect 2 — Complex-vector fixture: freezes, slow zoom, memory

**Fixture:** `test_files\MIC-VB-HVAC-DWG-0001 ... .pdf` — 34.8 MB, 50 dense vector pages.

**Measured (venv Python 3.10, PyMuPDF 1.27.1):**
| Operation | Cost |
|---|---|
| `doc.tobytes()` (worker snapshot / each undo half) | 520–657 ms, 36.4 MB |
| `get_pixmap` page25 low 1.0x | 220 ms |
| `get_pixmap` page25 high 1.5x (+DPR 1.25) | 257–318 ms (warm re-render no faster: 253 ms) |
| Thumbnail sweep, 50 pages @0.2x | **52 s**, RSS +155 MB (MuPDF store growth) |
| Undo snapshot pair (one annotation op) | ~1.0 s + 73 MB |

**Root cause #1 (CONFIRMED — architectural):** PyMuPDF **holds the GIL** during
rendering. GIL probe: main thread ticking at 10 ms stalls with median 197 ms, max
**4.5 s** gaps while a `threading.Thread` rasters 5 dense pages (8.3 s of 8.5 s starved).
⇒ The M3.6 `PageRenderCoordinator` + `ThumbnailCoordinator` QThread offload does not
actually yield responsiveness on this fixture: every "background" render freezes the GUI
for its full duration. Explains: freeze during high/prefetch render, frozen tab switch,
frozen tab close (plus `wait_for_done(1000)` ×2 on close and `get_pixmap` being
un-interruptible mid-call — cancellation only checks before/after).

**Root cause #2:** every zoom step runs a synchronous "immediate low" render on the GUI
thread (`_schedule_visible_render` → `_render_page_into_scene`, 220 ms+/step on this
fixture) plus a full placeholder scene rebuild; then the offloaded high render freezes the
GUI again via the GIL. Wheel zoom = repeated 300–600 ms stalls.

**Root cause #3 (memory):** MuPDF store retains display-list/path caches for all 50 dense
pages after the thumbnail sweep (+155 MB); plus 96 MB `RENDER_CACHE_BUDGET_BYTES` of
QPixmaps, 36 MB cached worker snapshot, 73 MB per annotation-op undo pair. After close,
`close+gc` frees most doc-owned store entries (291→123 MB in probe) — app residual
460–480 MB is likely Qt/thumbnails of remaining UI + heap retention; needs a targeted
leak pass only if it persists after the main fixes.

**Fix direction (needs its own plan; architecture-level):**
1. Move rasterization out-of-process — the print subsystem already has the pattern
   (`src/printing/subprocess_runner.py`): a render helper process fed by snapshot bytes,
   returning raw RGB. Solves GIL starvation AND makes cancellation real (kill/skip).
2. Zoom: never re-raster synchronously per wheel tick — rescale existing pixmaps via item
   transform immediately, debounce the re-raster.
3. Thumbnails: on-demand for the visible sidebar range only (never a full-document sweep
   on a 50-page dense doc); consider `fitz.TOOLS.store_shrink` after batches and on close.
4. Keep undo snapshots but note 1 s/73 MB per annotation op on this class of file —
   candidates: page-level snapshots for annotation ops instead of doc-level.

**Side observation (user):** PDF-XChange renders more vivid/contrasty colors — likely our
color-profile conversion (`safe_to_fitz_colorspace`) defaulting differently; separate
minor item, not part of this defect.
