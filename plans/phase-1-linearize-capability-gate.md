# Phase 1 — Linearize Capability Gate + Error Wrapping

**Status:** Ready to implement (Sonnet 4.6 deep-plan pass, 2026-06-10)
**Target:** single atomic commit

---

## 1. Confirmed Root Cause

### 1.1 The dead fallback (`model/pdf_optimizer.py`, lines 769–781)

`save_optimized_working_doc` has a branch:

```python
if model._requires_post_save_packaging(options) and _pikepdf() is None:
    working_doc.save(
        str(temp_save),
        ...
        linear=int(bool(options.linearize)),
        use_objstms=int(bool(options.use_object_streams)),
        ...
    )
    return
```

PyMuPDF 1.24+ removed linearization: passing `linear=1` raises
`code=4: Linearisation is no longer supported`.

- The `.venv` (app runtime) has PyMuPDF **1.27.1** — fallback is confirmed dead there.
- System Python (test runner) has PyMuPDF **1.25.5** which still accepts `linear=1`
  silently — which is why the current test suite does not surface the bug. New tests
  must monkeypatch `_pikepdf` rather than rely on the engine raising.

### 1.2 The double prefix

`save_optimized_copy` (pdf_optimizer.py:838–844) wraps any failure as
`RuntimeError(f"最佳化 PDF 失敗: {model._safe_exc_message(exc)}")`; then
`_on_optimize_copy_failed` (pdf_controller.py:1323–1326) formats
`f"最佳化 PDF 失敗: {exc}"` again → doubled message.

### 1.3 pikepdf availability

| Runtime | pikepdf |
|---|---|
| `.venv` (app, PyMuPDF 1.27.1) | **absent** |
| System Python 3.10 (tests, PyMuPDF 1.25.5) | present |

The 「極致壓縮」 preset (`preset_optimize_options`, pdf_optimizer.py:234) sets
`linearize=True`, so it always crashes the deployed app today.

### 1.4 No existing domain exception

No `PdfOptimizeError`/`PdfError` exists anywhere in `model/`. Introduce
`PdfOptimizeError(RuntimeError)` in `pdf_optimizer.py` (IS-A RuntimeError for
backward compatibility).

---

## 2. Changes

### 2.1 `model/pdf_optimizer.py`

a) After `PdfOptimizeExecutionProfile` (~line 117) add:

```python
class PdfOptimizeError(RuntimeError):
    """User-facing domain error from the PDF optimize pipeline.

    Raised when a requested optimization capability is unavailable (e.g. linearize
    without pikepdf) or when a fatal pipeline failure occurs. The message string is
    already user-readable Chinese text; callers should not re-wrap it.
    """
```

b) After `is_large_optimize_job` (~line 247) add:

```python
def optimize_capabilities() -> dict[str, bool]:
    """Return a capability dict reflecting the current runtime environment."""
    has_pikepdf = _pikepdf() is not None
    return {
        "linearize": has_pikepdf,
        "object_streams": has_pikepdf,
    }
```

c) `save_optimized_working_doc` (763–784): delete the dead fallback branch; replace with:

```python
if model._requires_post_save_packaging(options) and _pikepdf() is None:
    raise PdfOptimizeError(
        "目前環境缺少 pikepdf，無法套用 linearize / object streams 後處理。"
        "請執行 pip install pikepdf 後重試，或取消勾選「最佳化快速網頁檢視」和「使用物件串流」。"
    )
working_doc.save(str(temp_save), **model._fast_save_kwargs(options))
if model._requires_post_save_packaging(options):
    model._postprocess_optimized_pdf_with_pikepdf(temp_save, options)
```

d) `postprocess_optimized_pdf_with_pikepdf` (~line 739): its existing
`RuntimeError("目前環境缺少 pikepdf…")` becomes `PdfOptimizeError`.

e) `save_optimized_copy` except block (838–844): re-raise `PdfOptimizeError` bare
(after temp cleanup); wrap only unexpected exceptions once:

```python
except PdfOptimizeError:
    <temp cleanup>
    raise
except Exception as exc:
    <temp cleanup>
    raise PdfOptimizeError(f"最佳化 PDF 失敗: {model._safe_exc_message(exc)}") from exc
```

f) Add `"PdfOptimizeError"` and `"optimize_capabilities"` to `__all__` if present.

g) Verify NO remaining `linear=` kwarg in any fitz save in the file
(`fast_save_kwargs` at 719–729 already hardcodes `"linear": 0` — keep).

### 2.2 `model/pdf_model.py`

Static delegation next to `_can_use_parallel_image_rewrite` (~line 3200):

```python
@staticmethod
def optimize_capabilities() -> dict[str, bool]:
    return pdf_optimizer.optimize_capabilities()
```

### 2.3 `view/dialogs/optimize.py`

- Constructor (~line 26): add `capabilities: dict | None = None` param; store
  `self._capabilities = capabilities or {}`.
- Call order in `__init__`: `self._build_ui()` → `self._apply_capabilities(self._capabilities)`
  → `self._apply_preset("平衡")` (capability gate BEFORE preset).
- New `_apply_capabilities(caps)`: for each of `linearize` / `object_streams` keys
  (default True when missing): if False → `setEnabled(False)`, `setChecked(False)`,
  tooltip 「目前環境未安裝 pikepdf，無法使用此功能。\n請執行 pip install pikepdf 以啟用。」
  **Wrap the checkbox writes in `self._applying_preset = True/finally False`** so the
  `toggled → _mark_custom` connection doesn't flip the preset to 自訂 (Pitfall B).
- `_apply_preset` (~line 220): guard preset writes on disabled checkboxes:
  `if self.linearize_checkbox.isEnabled(): self.linearize_checkbox.setChecked(options.linearize)`
  and same for `object_streams_checkbox` — `setChecked` works on disabled widgets
  otherwise (Pitfall A).
- `get_options()` (~line 258) needs no change — disabled+unchecked naturally yields False.

### 2.4 `controller/pdf_controller.py`

- Dialog construction (~1216): pass `capabilities=self.model.optimize_capabilities()`.
- `_on_optimize_copy_failed` (1323–1326):

```python
def _on_optimize_copy_failed(self, exc) -> None:
    self._hide_optimize_progress_dialog()
    logger.error("最佳化 PDF 失敗: %s", exc)
    show_error(self.view, str(exc))
```

(Model's `PdfOptimizeError` message is already complete; lazy `%s` logging.)

### 2.5 Dependencies / environment

- Add to `optional-requirements.txt` (NOT requirements.txt):

```
# Post-save PDF packaging (linearize / object-stream repack for optimize-copy).
pikepdf>=8.0
```

- Env action: `.venv\Scripts\pip install pikepdf` so the deployed runtime gains the
  capability.

---

## 3. Red-Light Tests (write FIRST, in `test_scripts/test_pdf_optimize_workflow.py`, append after ~line 840)

- **T1** `test_save_optimized_working_doc_raises_domain_error_when_no_pikepdf_and_linearize`:
  monkeypatch `pdf_optimizer._pikepdf → lambda: None`; expect `PdfOptimizeError` from
  `save_optimized_working_doc` with `PdfOptimizeOptions(linearize=True)`.
  Red: currently the fallback save *succeeds* on PyMuPDF 1.25.5 → `pytest.raises` fails.
- **T2** capability probes: `optimize_capabilities()` False/False when `_pikepdf()` is None;
  True/True with a fake module; `PDFModel.optimize_capabilities` delegates.
  Red: AttributeError (functions don't exist yet).
- **T3** `test_optimize_copy_error_is_not_double_prefixed`: monkeypatch `_pikepdf → None`,
  call `model.save_optimized_copy(..., PdfOptimizeOptions(linearize=True))`, assert message
  does NOT start with `"最佳化 PDF 失敗: 最佳化 PDF 失敗:"` and exception IS PdfOptimizeError.
- **T4** dialog tests (need qapp fixture): `OptimizePdfDialog(capabilities={...})` disables +
  unchecks linearize / object_streams; 極致壓縮 preset switch cannot re-check a gated box
  (`get_options().linearize is False`). Red: TypeError unknown kwarg `capabilities`.
- **T5** `test_save_optimized_copy_with_linearize_succeeds_when_pikepdf_present`:
  skip if `_pikepdf() is None`; full pipeline with linearize=True produces output.

## 4. Verification

```powershell
python -m pytest test_scripts/test_pdf_optimize_workflow.py -v --tb=short
python -m pytest test_scripts/test_dialogs_package.py -v --tb=short
python -m ruff check model/pdf_optimizer.py model/pdf_model.py view/dialogs/optimize.py controller/pdf_controller.py
```

Existing test to watch: `test_save_optimized_copy_accepts_all_presets[極致壓縮]` — passes
under system Python (pikepdf present → real post-process path).

## 5. Docs (same commit)

- PITFALLS.md entry: "PyMuPDF `linear=1` removed in 1.24+; pikepdf-absent fallback is dead"
  (Area/Symptom/Cause/Fix/File format; see plan body).
- ARCHITECTURE.md: bullet documenting `optimize_capabilities()` static probe + dialog wiring.
- TODOS.md: mark Phase 1 done in the audit-remediation section.

## 6. Pitfalls recap

- A: `_apply_preset` setChecked works on disabled widgets — guard with `isEnabled()`.
- B: capability-gate setChecked fires `_mark_custom` — wrap in `_applying_preset`.
- D: test env has pikepdf — always monkeypatch `_pikepdf` to simulate absence.
- F: convert touched `logger.error(f"...")` to lazy `%s` (ruff G004).
