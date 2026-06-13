# Insert Pages Password Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow `從檔案插入頁` to import pages from password-protected PDFs using the same password prompt and retry behavior already available in merge flows.

**Architecture:** Keep password prompting in the controller, not the model or view. The view selects a source file and asks the controller to resolve page count/password; the final insert signal carries the password through controller to the model. The model's foreign-PDF guard opens/authenticates source documents while preserving existing size and page-count protections.

**Tech Stack:** PySide6 file/input dialogs, PyMuPDF encrypted document authentication, pytest.

---

## Current Touchpoints

- `view/pdf_view.py`: `sig_insert_pages_from_file`, `_insert_pages_from_file()`, `_insert_pages_from_file_at()`, `ask_pdf_password()`.
- `controller/pdf_controller.py`: signal connection, `_resolve_merge_file()`, `insert_pages_from_file()`.
- `model/pdf_model.py`: `_guard_foreign_doc()`, `insert_pages_from_file()`, `open_merge_source()`.
- Tests: `test_scripts/test_thumbnail_context_menu.py`, `test_scripts/test_security_pdf_resource_guards.py`, `test_scripts/test_structural_indexing.py`, `test_scripts/test_multi_tab_plan.py`; add focused encrypted insert tests where needed.

## Required Behavior

- Inserting from an encrypted source prompts for a password before source page-range input.
- Wrong password shows existing wrong-password error and retries.
- Cancel from password prompt cancels the insert flow and emits nothing.
- Correct password is passed into model insertion.
- Unencrypted source behavior remains unchanged except signal/API now includes `password=None`.
- Resource guards still reject oversize PDFs and post-merge page-count overflow.

## Task 1: Extend Insert Signal And Controller/Model Signatures

**Files:**
- Modify: `view/pdf_view.py`
- Modify: `controller/pdf_controller.py`
- Modify: `model/pdf_model.py`
- Tests: `test_scripts/test_thumbnail_context_menu.py`, `test_scripts/test_multi_tab_plan.py`, `test_scripts/test_structural_indexing.py`

**Step 1: Write/update failing tests**

Update existing expectations from:

```python
assert view.sig_insert_pages_from_file.calls == [(str(source_path), [1, 3, 4], 6)]
```

to:

```python
assert view.sig_insert_pages_from_file.calls == [(str(source_path), [1, 3, 4], 6, None)]
```

Add a controller test that calls:

```python
controller.insert_pages_from_file(str(source), [1], 2, password="pw")
```

and asserts the fake model received the password.

**Step 2: Run failing tests**

```powershell
pytest -q test_scripts/test_thumbnail_context_menu.py test_scripts/test_multi_tab_plan.py -k insert_pages_from_file
```

Expected: fails due current 3-argument signal/signatures.

**Step 3: Implement signature changes**

In `PDFView`:

```python
sig_insert_pages_from_file = Signal(str, list, int, object)
```

In `PDFController`:

```python
def insert_pages_from_file(
    self,
    source_file: str,
    source_pages: list[int],
    position: int,
    password: str | None = None,
):
    actual_inserted_pages = self.model.insert_pages_from_file(
        source_file,
        source_pages,
        position,
        password=password,
    )
```

In `PDFModel`:

```python
def insert_pages_from_file(
    self,
    source_file: str,
    source_pages: list[int],
    position: int,
    password: str | None = None,
) -> list[int]:
```

Do not change command descriptions or snapshot behavior.

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_thumbnail_context_menu.py test_scripts/test_multi_tab_plan.py -k insert_pages_from_file
```

Expected: pass after all call sites include the new fourth argument.

**Step 5: Atomic commit**

```powershell
git add -- view/pdf_view.py controller/pdf_controller.py model/pdf_model.py test_scripts/test_thumbnail_context_menu.py test_scripts/test_multi_tab_plan.py test_scripts/test_structural_indexing.py
git commit -m "feat(api): pass insert-source passwords"
```

## Task 2: Authenticate Foreign PDF Guard

**Files:**
- Modify: `model/pdf_model.py`
- Test: `test_scripts/test_security_pdf_resource_guards.py`

**Step 1: Write failing tests**

Add encrypted source fixtures:

```python
def _encrypted_pdf(path: Path, user_pw: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 60), "secret")
    doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=user_pw, owner_pw="owner")
    doc.close()
```

Tests:

- `_guard_foreign_doc(path, password=None)` raises a needs-password message.
- `_guard_foreign_doc(path, password="wrong")` raises password validation failure.
- `_guard_foreign_doc(path, password="secret")` returns an authenticated doc whose `page_count` can be read.
- `insert_pages_from_file(..., password="secret")` imports the page.

**Step 2: Run failing tests**

```powershell
pytest -q test_scripts/test_security_pdf_resource_guards.py -k encrypted
```

Expected: fails because `_guard_foreign_doc()` rejects encrypted sources unconditionally.

**Step 3: Implement**

Change:

```python
def _guard_foreign_doc(path: Path) -> fitz.Document:
```

to:

```python
def _guard_foreign_doc(path: Path, password: str | None = None) -> fitz.Document:
```

Inside:

```python
_guard_before_open(path)
doc = fitz.open(str(path))
try:
    if doc.needs_pass:
        if password is None:
            raise RuntimeError(f"document closed or encrypted - 需要密碼: {path}")
        if doc.authenticate(password) == 0:
            raise RuntimeError(f"PDF 密碼驗證失敗（authenticate 回傳 0）: {path}")
    if doc.page_count > _MAX_PAGES:
        raise ValueError(f"Foreign PDF exceeds page limit ({_MAX_PAGES} pages): {path}")
except Exception:
    doc.close()
    raise
return doc
```

Then update `insert_pages_from_file()`:

```python
source_doc = _guard_foreign_doc(source_path, password=password)
```

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_security_pdf_resource_guards.py -k "insert_pages_from_file or encrypted"
```

Expected: pass.

**Step 5: Atomic commit**

```powershell
git add -- model/pdf_model.py test_scripts/test_security_pdf_resource_guards.py
git commit -m "feat(model): authenticate insert-page sources"
```

## Task 3: Add Controller Source Resolver For Insert

**Files:**
- Modify: `controller/pdf_controller.py`
- Test: `test_scripts/test_multi_tab_plan.py` or new `test_scripts/test_insert_pages_password.py`

**Step 1: Write failing tests**

Use fake model/view objects:

- Model resolver raises `RuntimeError("document closed or encrypted - 需要密碼")` first, then returns `{"page_count": 3, "password": "pw"}`.
- View `ask_pdf_password()` returns `"pw"`.
- Assert resolver returns page count and password.
- Wrong password path raises `密碼驗證失敗`, calls `show_error`, and prompts again.
- Cancel returns `None`.

**Step 2: Run failing tests**

```powershell
pytest -q test_scripts/test_insert_pages_password.py
```

Expected: resolver missing.

**Step 3: Add model source info helper**

Add to `PDFModel`:

```python
def open_insert_source(self, path: str, password: str | None = None) -> dict:
    src_path = Path(path).resolve()
    if not src_path.exists():
        raise FileNotFoundError(f"來源檔案不存在: {path}")
    doc = _guard_foreign_doc(src_path, password=password)
    try:
        if len(doc) == 0:
            raise RuntimeError(f"無法讀取來源檔案: {path}")
        return {
            "path": str(src_path),
            "display_name": src_path.name,
            "page_count": len(doc),
            "password": password,
        }
    finally:
        doc.close()
```

**Step 4: Add controller resolver**

Add to `PDFController`:

```python
def resolve_insert_source_file(self, path: str) -> dict | None:
    password = None
    while True:
        try:
            return self.model.open_insert_source(path, password=password)
        except RuntimeError as e:
            err_msg = str(e)
            if "需要密碼" in err_msg or "encrypted" in err_msg.lower():
                pw = self.view.ask_pdf_password(path)
                if pw is None:
                    return None
                password = pw
                continue
            if "密碼驗證失敗" in err_msg:
                show_error(self.view, "密碼錯誤，請重試。")
                pw = self.view.ask_pdf_password(path)
                if pw is None:
                    return None
                password = pw
                continue
            show_error(self.view, f"無法讀取來源檔案: {e}")
            return None
        except Exception as e:
            show_error(self.view, f"無法讀取來源檔案: {e}")
            return None
```

**Step 5: Verify**

```powershell
pytest -q test_scripts/test_insert_pages_password.py
```

Expected: pass.

## Task 4: Update View Insert Flows To Use Resolver

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_thumbnail_context_menu.py`, `test_scripts/test_insert_pages_password.py`

**Step 1: Write failing tests**

Update `_insert_pages_from_file_at()` tests so `view.controller.resolve_insert_source_file(path)` returns:

```python
{"path": str(source_path), "page_count": 4, "password": "pw"}
```

Assert emitted signal:

```python
(str(source_path), [1, 3, 4], 6, "pw")
```

Add cancel test where resolver returns `None`; assert no signal emitted and no page-range prompt.

**Step 2: Run failing tests**

```powershell
pytest -q test_scripts/test_thumbnail_context_menu.py -k insert_pages_from_file
pytest -q test_scripts/test_insert_pages_password.py
```

Expected: fails because view opens `fitz.open()` directly.

**Step 3: Implement helper**

Add to `PDFView`:

```python
def _resolve_insert_source_file(self, source_file: str) -> dict | None:
    controller = getattr(self, "controller", None)
    if controller is not None and hasattr(controller, "resolve_insert_source_file"):
        return controller.resolve_insert_source_file(source_file)
    try:
        source_doc = fitz.open(source_file)
        try:
            return {"path": source_file, "page_count": len(source_doc), "password": None}
        finally:
            source_doc.close()
    except Exception as e:
        show_error(self, f"無法讀取來源檔案: {e}")
        return None
```

Update both `_insert_pages_from_file()` and `_insert_pages_from_file_at()`:

```python
resolved = self._resolve_insert_source_file(source_file)
if resolved is None:
    return
source_total_pages = int(resolved["page_count"])
password = resolved.get("password")
...
self.sig_insert_pages_from_file.emit(source_file, source_pages, position, password)
```

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_thumbnail_context_menu.py -k insert_pages_from_file
pytest -q test_scripts/test_insert_pages_password.py
```

Expected: pass.

**Step 5: Atomic commit**

```powershell
git add -- view/pdf_view.py controller/pdf_controller.py model/pdf_model.py test_scripts/test_thumbnail_context_menu.py test_scripts/test_insert_pages_password.py
git commit -m "feat(ui): prompt for insert-source passwords"
```

## Phase Verification

Run:

```powershell
pytest -q test_scripts/test_thumbnail_context_menu.py test_scripts/test_security_pdf_resource_guards.py test_scripts/test_structural_indexing.py test_scripts/test_multi_tab_plan.py test_scripts/test_insert_pages_password.py
```

Expected: all pass.

## Notes For Implementer

- Keep merge password behavior unchanged.
- Do not prompt for password in the model.
- Ensure all opened foreign docs close on every exception path.
- Keep resource guards active before and after authentication.
