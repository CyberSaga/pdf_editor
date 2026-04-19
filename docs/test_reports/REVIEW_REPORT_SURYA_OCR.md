# Surya OCR Review Report

**Date:** 2026-04-19
**Reviewer:** Claude (Opus 4.7 / Sonnet 4.6)
**Scope:** Verify [`docs/IMPLEMENTATION_REPORT_SURYA_OCR.md`](IMPLEMENTATION_REPORT_SURYA_OCR.md) claims; live-test on real PDFs; identify gaps; fix.
**Status:** Implementation verified, three real bugs found and fixed, end-to-end OCR confirmed working on GPU.

---

## 1. Verification of Implementation Report

| Claim | Status | Evidence |
|-------|--------|----------|
| All listed files exist (§3) | ✅ | 4 new + 4 modified files present |
| MVC layer boundaries respected | ✅ | View signals → Controller → Model; no cross-layer calls |
| Toolbar action accessible | ✅ | `view/pdf_view.py:958` — "OCR（文字辨識）" under 轉換 tab |
| Tests claimed: 71 green | ✅ (better) | **80 unit tests pass** (report undercounts: omitted `test_user_preferences.py`) |
| Zero new ruff violations | ✅ | `ruff check` on new files: clean |
| Per-page commit + cancel safety | ✅ | `_OcrWorker.run` checks `_cancel_requested` between pages |
| QThread + bridge pattern | ✅ | `_OcrBridge` correctly forwards signals to GUI thread |
| Availability gating | ✅ | `_refresh_ocr_availability` runs on `activate()`; toolbar disables when unavailable |
| Invisible text (`render_mode=3`) | ✅ | `model/pdf_model.py:2009` |
| CJK font fallback | ✅ | `_pick_ocr_font` selects via Unicode ranges (japan / korea / china-t / helv) |

**Verdict on report claims:** Wiring, MVC compliance, test coverage, and GUI accessibility all match the report.

---

## 2. Live Test on Real PDFs

### Test Corpus (`test_files/testOCR/`)
- `Engineering_Handover_Blueprint.pdf` — bilingual (English/Chinese) cover page
- `機電O_M竣工資料要求_可重複使用規範_詳細教案.pdf` — dense CJK content

### Discovered Blocker — Surya 0.17 API Break

The "tested with Surya ≥ 0.6" claim does **not** hold on the current release (0.17.1):

1. `RecognitionPredictor` now requires a `FoundationPredictor` argument. Both adapter init paths (`device=` kwarg, no-arg fallback) raised `TypeError`.
2. The `languages` parameter was removed; replaced by `task_names=[TaskNames.ocr_without_boxes]`.

**Adapter rewrite** (`model/tools/ocr_tool.py`):
```python
FoundationPredictor = getattr(recognition_mod, "FoundationPredictor", None)
if FoundationPredictor is not None:                 # Surya ≥ 0.7 path
    fp = FoundationPredictor(device=torch_device)
    self._recognizer = recognition_mod.RecognitionPredictor(fp)
    self._detector = detection_mod.DetectionPredictor(device=torch_device)
else:                                                # Surya ≤ 0.6 path
    self._detector = detection_mod.DetectionPredictor(device=torch_device)
    self._recognizer = recognition_mod.RecognitionPredictor(device=torch_device)
```
Call site likewise switched to `task_names=` when `TaskNames` is exported.

### Environment Pinning
- `surya-ocr 0.17.1` requires `transformers < 5` (the auto-installed `5.5.4` raises `AttributeError: 'SuryaDecoderConfig' object has no attribute 'pad_token_id'`). Downgrade with `pip install "transformers>=4.47,<5"`.

### Results

End-to-end test suite added at `test_scripts/test_ocr_e2e.py` — 8 tests, all pass:

| Test | Result |
|------|--------|
| Availability reports `available=True` | ✅ |
| English page 1 returns spans | ✅ 4 spans |
| English bbox coordinates valid | ✅ |
| English text non-empty | ✅ |
| English confidence ∈ [0, 1] | ✅ avg ~0.95 |
| Chinese page 1 returns spans | ✅ **46 spans**, top conf 1.00 / 0.91 / 0.98 / 0.93 |
| `apply_ocr_spans` inserts text → page becomes searchable | ✅ |
| `apply_ocr_spans` increments `edit_count`, queues `pending_edits` | ✅ |

### Sample CJK Recognition Quality
```
conf=1.00  '《機電 O&M 竣工資料要求可重複使用規範》— 詳細教案'
conf=0.98  '<b>範例來源: O&M_TEST/01-ECS Pumps CH (Final O&M).pdf (D295-OM-1300CH</b> 水泵'
conf=0.93  '浦,左營機廠)'
```

### CPU vs GPU Performance (RTX 4060 Laptop, 8 GB)

| Stage | CPU (`torch+cpu`) | GPU (`torch+cu128`) | Speedup |
|-------|-------------------|---------------------|---------|
| Detection (per page) | ~3 s | ~0.4 s | ~7.5× |
| Recognition (English, 4 lines) | ~10 s | ~1.2 s | ~8× |
| Recognition (CJK, 49 lines) | ~35 s | ~3.3 s | ~10× |
| Full e2e suite (8 tests) | 136 s | **68 s** | ~2× wall |

(End-to-end speedup dampened by model load + Python overhead; pure inference is the 7–10× figure.)

---

## 3. Code Lacks Identified

Live testing surfaced three issues the unit-test suite did not catch:

### Lack 1 — `_resolve_torch_device` does not validate explicit GPU selections
`model/tools/ocr_tool.py` (pre-fix lines 33–50). Only the `"auto"` path probed availability; explicit `"cuda"` / `"mps"` returned the string verbatim, so a CPU-only torch install would crash mid-OCR with the opaque `RuntimeError: Torch not compiled with CUDA enabled`.

### Lack 2 — Dialog lists all device options unconditionally
`view/dialogs/ocr.py` (pre-fix lines 107–113). Users with CPU-only torch could pick CUDA; the bad choice was even persisted via `UserPreferences.set_ocr_device`, so the next session also failed until they re-opened the dialog.

### Lack 3 — No VRAM cleanup after OCR
`OcrTool.ocr_pages` instantiated the adapter as a local; on return, Python released the reference but torch did not eagerly free its allocator cache. Repeated OCR runs on a small (8 GB) GPU could OOM.

---

## 4. Implemented Fixes

Plan saved at `~/.claude/plans/dazzling-sleeping-journal.md`. Summary:

### Fix 1 — `_is_device_available` helper + harden `_resolve_torch_device`
`model/tools/ocr_tool.py:33-77`. New helper returns `True` for cpu/auto, probes `torch.cuda.is_available()` / `torch.backends.mps.is_available()` for cuda/mps. `_resolve_torch_device` now raises a clear bilingual `RuntimeError` when an explicit GPU selection is unavailable.

### Fix 2 — Disable unavailable items in dialog
`view/dialogs/ocr.py:108-124`, `:202-204`. Combo items for unavailable devices are `setEnabled(False)` with tooltip "此裝置目前不可用 (torch 不支援)". Stored preference is clamped to `auto` if no longer available. `accept()` re-clamps defensively.

### Fix 3 — Release VRAM after each OCR run
`model/tools/ocr_tool.py:229-286`. Page loop wrapped in `try/finally`; on exit (success or exception) the adapter ref is dropped and `torch.cuda.empty_cache()` (or `torch.mps.empty_cache()`) is called when the resolved device matches.

### Fix 4 — Bug in finally block (post-review)
`return` inside the finally block was swallowing the success return value (`results` → `None`) when torch happened to be unimportable at cleanup time. Changed `return` → `pass`.

### Test additions
- `test_scripts/test_ocr_tool_surya.py`: +5 tests (explicit-device validation, `_is_device_available`, VRAM cleanup)
- `test_scripts/test_ocr_dialog.py`: +2 tests (combo gating, default fallback)
- `test_scripts/test_ocr_e2e.py`: 8 new live OCR tests against the real PDFs

---

## 5. Final State

| Check | Result |
|-------|--------|
| Unit tests (`test_ocr_*.py` minus e2e) | ✅ 81 pass |
| E2E tests (real PDFs on GPU) | ✅ 8 pass |
| **Total OCR tests** | **89 pass** |
| `ruff check model/tools/ocr_tool.py view/dialogs/ocr.py` | ✅ clean |
| MVC layer boundaries | ✅ preserved |
| GUI accessibility | ✅ confirmed via toolbar action + dialog |
| Real OCR accuracy | ✅ avg conf ≥ 0.93 on CJK; multilingual |
| GPU acceleration | ✅ ~10× speedup on RTX 4060 |
| VRAM hygiene | ✅ `empty_cache()` on every run, even on exception |

---

## 6. Outstanding (Out of Scope)

- The `_pixmap_to_image` PIL fallback path (returns raw ndarray) is untested — Surya may not accept it.
- `OCR_RENDER_SCALE = 2.0` (~144 DPI) is below Surya's recommended 300 DPI; a higher scale would likely improve recall on small fonts.
- The legacy `sig_ocr` path (`controller/pdf_controller.py:2256`) bypasses the dialog; currently unreachable from toolbar but should be marked deprecated or removed.
- No automated test for the GUI toolbar action's enabled/disabled state under live availability changes.

---

**Files touched in this review:**
- `model/tools/ocr_tool.py` — adapter rewritten for Surya 0.17 API; device validation; VRAM cleanup
- `view/dialogs/ocr.py` — combo item gating; default clamp; defensive `accept()`
- `test_scripts/test_ocr_tool_surya.py` — +5 tests
- `test_scripts/test_ocr_dialog.py` — +2 tests
- `test_scripts/test_ocr_e2e.py` — new file, 8 live OCR tests

**Plan archive:** `~/.claude/plans/dazzling-sleeping-journal.md`
