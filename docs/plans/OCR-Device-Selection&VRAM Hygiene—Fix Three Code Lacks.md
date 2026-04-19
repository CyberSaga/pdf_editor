# OCR Device-Selection & VRAM Hygiene — Fix Three Code Lacks

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the OCR feature behave correctly when the user explicitly picks an unavailable GPU device, surface device availability in the dialog, and release VRAM after each OCR run.

**Architecture:** All three fixes are isolated to two files — `model/tools/ocr_tool.py` (device probing + VRAM cleanup) and `view/dialogs/ocr.py` (dialog gating). One small new helper `_is_device_available(device)` is added beside `_resolve_torch_device` and reused by the dialog.

**Tech Stack:** Python 3.10, PySide6 (QComboBox.model is `QStandardItemModel` by default), torch, surya-ocr.

---

## Context

A live end-to-end OCR run on the user's RTX 4060 surfaced three real issues that the unit-test suite did not catch:

1. **`_resolve_torch_device` only validates the `"auto"` path.** If the user explicitly picks **GPU (CUDA)** or **GPU (Apple Silicon / MPS)** in the dialog, the function returns the string verbatim without calling `torch.cuda.is_available()` / `torch.backends.mps.is_available()`. Surya then crashes mid-OCR with the unhelpful `RuntimeError: Torch not compiled with CUDA enabled`. The error reaches the user via `_on_ocr_failed` but is opaque.

2. **The OCR dialog lists all four device options unconditionally** (`view/dialogs/ocr.py:107-113`). A user with CPU-only torch can pick CUDA and only learns it won't work after starting OCR. Worse, the bad choice is *persisted* via `UserPreferences.set_ocr_device` on `accept()`, so the next session also fails until they re-open the dialog.

3. **`_create_surya_adapter(device)` is a local in `ocr_pages` (line 182).** The adapter holds detector + foundation + recognizer (~2–4 GB VRAM on CUDA). When `ocr_pages` returns, Python releases the reference but torch does not eagerly free CUDA memory — repeated OCR jobs on a single 8 GB card can OOM.

The fixes are small, defensive, and observable.

---

## Critical Files

- **Modify** `model/tools/ocr_tool.py` — add `_is_device_available`, harden `_resolve_torch_device`, add VRAM cleanup at end of `ocr_pages`.
- **Modify** `view/dialogs/ocr.py` — disable unavailable items in `device_combo`, ensure default selection is available.
- **Test** `test_scripts/test_ocr_tool_surya.py` — extend with explicit-device + cleanup tests (mocked torch).
- **Test** `test_scripts/test_ocr_dialog.py` — extend with availability-gating tests.
- **Reuse:** `_resolve_torch_device` (existing), `OcrDevice` enum (`model/tools/ocr_types.py`), `UserPreferences` (`utils/preferences.py`).

---

## Task 1: Add `_is_device_available` helper + harden explicit device selection

**Files:**
- Modify: `model/tools/ocr_tool.py:33-50` (`_resolve_torch_device`)
- Test: `test_scripts/test_ocr_tool_surya.py`

**Step 1: Write the failing tests** (append to `test_ocr_tool_surya.py`)

```python
def test_resolve_torch_device_explicit_cuda_unavailable_raises(monkeypatch):
    """Explicit cuda selection without CUDA torch must raise a clear error."""
    import importlib
    fake_torch = type(sys)("torch")
    fake_torch.cuda = type(sys)("cuda")
    fake_torch.cuda.is_available = lambda: False
    fake_torch.backends = type(sys)("backends")
    monkeypatch.setattr(importlib, "import_module",
                        lambda name: fake_torch if name == "torch" else importlib.__import__(name))
    from model.tools.ocr_tool import _resolve_torch_device
    with pytest.raises(RuntimeError, match="CUDA"):
        _resolve_torch_device("cuda")


def test_resolve_torch_device_explicit_mps_unavailable_raises(monkeypatch):
    """Explicit mps selection without MPS must raise a clear error."""
    import importlib
    fake_torch = type(sys)("torch")
    fake_torch.cuda = type(sys)("cuda"); fake_torch.cuda.is_available = lambda: False
    fake_torch.backends = type(sys)("backends")
    fake_torch.backends.mps = type(sys)("mps"); fake_torch.backends.mps.is_available = lambda: False
    monkeypatch.setattr(importlib, "import_module",
                        lambda name: fake_torch if name == "torch" else importlib.__import__(name))
    from model.tools.ocr_tool import _resolve_torch_device
    with pytest.raises(RuntimeError, match="MPS"):
        _resolve_torch_device("mps")


def test_resolve_torch_device_explicit_cpu_always_returns_cpu():
    from model.tools.ocr_tool import _resolve_torch_device
    assert _resolve_torch_device("cpu") == "cpu"


def test_is_device_available_cpu_always_true():
    from model.tools.ocr_tool import _is_device_available
    assert _is_device_available("cpu") is True
    assert _is_device_available("auto") is True


def test_is_device_available_cuda_reflects_torch(monkeypatch):
    import importlib
    fake_torch = type(sys)("torch")
    fake_torch.cuda = type(sys)("cuda"); fake_torch.cuda.is_available = lambda: True
    fake_torch.backends = type(sys)("backends")
    monkeypatch.setattr(importlib, "import_module",
                        lambda name: fake_torch if name == "torch" else importlib.__import__(name))
    from model.tools.ocr_tool import _is_device_available
    assert _is_device_available("cuda") is True
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest test_scripts/test_ocr_tool_surya.py::test_resolve_torch_device_explicit_cuda_unavailable_raises test_scripts/test_ocr_tool_surya.py::test_is_device_available_cpu_always_true -v
```
Expected: FAIL — `_is_device_available` does not exist; explicit "cuda" returns "cuda" instead of raising.

**Step 3: Implement**

Replace the body of `_resolve_torch_device` and add the helper:

```python
def _is_device_available(device: str) -> bool:
    """Return True if the requested device can be used by torch right now."""
    normalized = OcrDevice.from_code(device).value
    if normalized in (OcrDevice.AUTO.value, OcrDevice.CPU.value):
        return True
    try:
        torch = importlib.import_module("torch")
    except ImportError:
        return False
    if normalized == OcrDevice.CUDA.value:
        cuda_mod = getattr(torch, "cuda", None)
        return bool(cuda_mod and cuda_mod.is_available())
    if normalized == OcrDevice.MPS.value:
        backends = getattr(torch, "backends", None)
        mps_mod = getattr(backends, "mps", None) if backends else None
        return bool(mps_mod and getattr(mps_mod, "is_available", lambda: False)())
    return False


def _resolve_torch_device(device: str) -> str:
    normalized = OcrDevice.from_code(device).value
    if normalized == OcrDevice.CPU.value:
        return OcrDevice.CPU.value
    if normalized == OcrDevice.AUTO.value:
        # Existing fallback chain unchanged.
        try:
            torch = importlib.import_module("torch")
        except ImportError:
            return OcrDevice.CPU.value
        if getattr(torch, "cuda", None) is not None and torch.cuda.is_available():
            return OcrDevice.CUDA.value
        mps_mod = getattr(getattr(torch, "backends", None), "mps", None)
        if mps_mod is not None and getattr(mps_mod, "is_available", lambda: False)():
            return OcrDevice.MPS.value
        return OcrDevice.CPU.value
    # Explicit cuda / mps — must be available.
    if not _is_device_available(normalized):
        label = "CUDA" if normalized == OcrDevice.CUDA.value else "MPS"
        raise RuntimeError(
            f"已選擇 {label} 但目前 torch 不支援該裝置；請改選自動或 CPU。"
        )
    return normalized
```

**Step 4: Run all OCR-tool tests**

```bash
python -m pytest test_scripts/test_ocr_tool_surya.py -v
```
Expected: PASS (existing 13 + 5 new = 18).

**Step 5: Commit**

```bash
git add model/tools/ocr_tool.py test_scripts/test_ocr_tool_surya.py
git commit -m "fix(ocr): validate explicit GPU device selection before invoking surya"
```

---

## Task 2: Disable unavailable device options in the OCR dialog

**Files:**
- Modify: `view/dialogs/ocr.py:107-113` (device combo construction)
- Test: `test_scripts/test_ocr_dialog.py`

**Step 1: Write the failing tests**

```python
def test_dialog_disables_cuda_when_unavailable(qtbot, monkeypatch):
    from view.dialogs import ocr as ocr_mod
    monkeypatch.setattr(ocr_mod, "_is_device_available",
                        lambda d: d in ("auto", "cpu"))
    dialog = ocr_mod.OcrDialog(total_pages=3, current_page=1)
    qtbot.addWidget(dialog)
    model = dialog.device_combo.model()
    cuda_idx = dialog.device_combo.findData("cuda")
    mps_idx = dialog.device_combo.findData("mps")
    assert not model.item(cuda_idx).isEnabled()
    assert not model.item(mps_idx).isEnabled()
    assert model.item(dialog.device_combo.findData("cpu")).isEnabled()
    assert model.item(dialog.device_combo.findData("auto")).isEnabled()


def test_dialog_default_falls_back_when_stored_pref_unavailable(qtbot, monkeypatch):
    """If saved preference is CUDA but CUDA is unavailable, dialog selects auto."""
    from view.dialogs import ocr as ocr_mod
    monkeypatch.setattr(ocr_mod, "_is_device_available",
                        lambda d: d in ("auto", "cpu"))
    prefs = _make_in_memory_prefs(device="cuda")  # existing helper in this file
    dialog = ocr_mod.OcrDialog(total_pages=3, current_page=1, preferences=prefs)
    qtbot.addWidget(dialog)
    assert dialog.device_combo.currentData() == "auto"
```

**Step 2: Run to verify they fail**

```bash
python -m pytest test_scripts/test_ocr_dialog.py::test_dialog_disables_cuda_when_unavailable test_scripts/test_ocr_dialog.py::test_dialog_default_falls_back_when_stored_pref_unavailable -v
```
Expected: FAIL — items aren't disabled; selection stays on cuda even when unavailable.

**Step 3: Implement** — modify the device combo block in `_build_ui`:

```python
from model.tools.ocr_tool import _is_device_available  # add to imports

# ... inside _build_ui(), replace lines 107-113:
self.device_combo = QComboBox()
combo_model = self.device_combo.model()
for value, label in _DEVICE_LABELS:
    self.device_combo.addItem(label, value)
    idx = self.device_combo.count() - 1
    available = _is_device_available(value)
    item = combo_model.item(idx)
    if item is not None and not available:
        item.setEnabled(False)
        item.setToolTip("此裝置目前不可用 (torch 未支援)")

stored = self._preferences.get_ocr_device()
if not _is_device_available(stored):
    stored = OcrDevice.AUTO.value
device_idx = self.device_combo.findData(stored)
if device_idx >= 0:
    self.device_combo.setCurrentIndex(device_idx)
```

**Step 4: Run dialog tests**

```bash
python -m pytest test_scripts/test_ocr_dialog.py -v
```
Expected: PASS (existing 13 + 2 new = 15).

**Step 5: Commit**

```bash
git add view/dialogs/ocr.py test_scripts/test_ocr_dialog.py
git commit -m "fix(ocr): disable unavailable device options in dialog and clamp default"
```

---

## Task 3: Release CUDA memory after OCR completes

**Files:**
- Modify: `model/tools/ocr_tool.py:152-219` (`OcrTool.ocr_pages`)
- Test: `test_scripts/test_ocr_tool_surya.py`

**Step 1: Write the failing test**

```python
def test_ocr_pages_calls_cuda_empty_cache(monkeypatch, mock_model_with_doc):
    """After successful OCR on a CUDA device, torch.cuda.empty_cache must be called."""
    import importlib
    calls = {"empty": 0}
    fake_torch = type(sys)("torch")
    fake_torch.cuda = type(sys)("cuda")
    fake_torch.cuda.is_available = lambda: True
    fake_torch.cuda.empty_cache = lambda: calls.__setitem__("empty", calls["empty"] + 1)
    fake_torch.backends = type(sys)("backends")
    real_import = importlib.import_module
    monkeypatch.setattr(importlib, "import_module",
                        lambda name: fake_torch if name == "torch" else real_import(name))

    # Use existing fully-mocked surya fixture that returns one span on one page.
    tool = _build_tool_with_mocked_surya(mock_model_with_doc, device="cuda")
    tool.ocr_pages([1], languages=["en"], device="cuda")
    assert calls["empty"] == 1


def test_ocr_pages_skips_empty_cache_on_cpu(monkeypatch, mock_model_with_doc):
    """No CUDA cleanup attempted when running on CPU."""
    import importlib
    calls = {"empty": 0}
    fake_torch = type(sys)("torch")
    fake_torch.cuda = type(sys)("cuda")
    fake_torch.cuda.is_available = lambda: False
    fake_torch.cuda.empty_cache = lambda: calls.__setitem__("empty", calls["empty"] + 1)
    fake_torch.backends = type(sys)("backends")
    real_import = importlib.import_module
    monkeypatch.setattr(importlib, "import_module",
                        lambda name: fake_torch if name == "torch" else real_import(name))

    tool = _build_tool_with_mocked_surya(mock_model_with_doc, device="cpu")
    tool.ocr_pages([1], languages=["en"], device="cpu")
    assert calls["empty"] == 0
```

(Reuse the existing `_build_tool_with_mocked_surya` / fixture pattern already in `test_ocr_tool_surya.py`. If a public helper isn't there, factor one out from existing tests in the same step.)

**Step 2: Run to verify they fail**

```bash
python -m pytest test_scripts/test_ocr_tool_surya.py::test_ocr_pages_calls_cuda_empty_cache -v
```
Expected: FAIL — `empty_cache` is never called.

**Step 3: Implement** — at the end of `ocr_pages`, after the page loop:

```python
        # Release VRAM. Adapter goes out of scope at function return; this
        # makes torch eagerly free its allocator cache so successive OCR
        # runs don't OOM on small GPUs.
        adapter = None  # drop strong ref before empty_cache
        try:
            torch = importlib.import_module("torch")
            cuda_mod = getattr(torch, "cuda", None)
            if cuda_mod is not None and cuda_mod.is_available():
                cuda_mod.empty_cache()
        except ImportError:
            pass

        return results
```

(Move the existing `return results` so the cleanup runs whether or not any spans were found. Wrap the loop in `try/finally` if cleanup should also run on exceptions — recommended.)

**Step 4: Run full OCR-tool test file**

```bash
python -m pytest test_scripts/test_ocr_tool_surya.py -v
```
Expected: PASS — all existing + 2 new.

**Step 5: Commit**

```bash
git add model/tools/ocr_tool.py test_scripts/test_ocr_tool_surya.py
git commit -m "fix(ocr): release CUDA cache after each ocr_pages run"
```

---

## Task 4: End-to-end smoke verification

**Step 1: Run the full OCR test suite (unit + e2e)**

```bash
python -m pytest test_scripts/test_ocr_*.py -v 2>&1 | tail -40
```
Expected: 81 unit + 8 e2e = **89 passing**, zero failures.

**Step 2: Manual GUI sanity check**

1. Launch `python main.py`.
2. Open a PDF.
3. Click 轉換 → OCR（文字辨識）.
4. In the dialog confirm:
   - On CUDA-built torch (current state) the CUDA option is **enabled**, MPS is **disabled** with tooltip "此裝置目前不可用".
   - Picking CPU and clicking 確定 runs OCR successfully.
   - Picking GPU (CUDA) and clicking 確定 runs OCR successfully and `nvidia-smi` shows VRAM usage rising then dropping after completion.
5. To simulate the unavailable case, temporarily uninstall CUDA torch (`pip install torch --index-url https://download.pytorch.org/whl/cpu --force-reinstall`) and re-launch — confirm CUDA item is greyed out and stored preference falls back to 自動.

**Step 3: Lint**

```bash
ruff check model/tools/ocr_tool.py view/dialogs/ocr.py
```
Expected: All checks passed.

**Step 4: Update docs**

- Add a one-liner to `docs/PITFALLS.md`: "Surya passes the device string straight to torch; explicit `cuda`/`mps` selections must be probed via `_is_device_available` before resolution to avoid `Torch not compiled with CUDA enabled` mid-OCR."
- Note in `docs/ARCHITECTURE.md` § 5.1 (OCR Tool): adapter releases `torch.cuda.empty_cache()` after each `ocr_pages` run.

**Step 5: Final commit**

```bash
git add docs/PITFALLS.md docs/ARCHITECTURE.md
git commit -m "docs: document OCR device probing and VRAM cleanup"
```

---

## Verification Summary

| Check | Command | Expected |
|-------|---------|----------|
| Unit tests | `pytest test_scripts/test_ocr_*.py -v` | All green (≥ 89) |
| E2E live OCR (GPU) | `pytest test_scripts/test_ocr_e2e.py -v -s` | 8 pass, GPU utilization visible in `nvidia-smi` |
| Lint | `ruff check model/tools/ocr_tool.py view/dialogs/ocr.py` | Zero violations |
| Manual: CUDA available | Launch app, open dialog | CUDA enabled, MPS disabled |
| Manual: explicit CUDA on CPU torch | Force CPU torch, pick CUDA | Dialog blocks selection; if bypassed, OCR raises clear "已選擇 CUDA 但目前 torch 不支援" message |
| Manual: VRAM | Run OCR on 5+ pages, watch `nvidia-smi` | VRAM drops after dialog closes |
