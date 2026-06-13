# Page Controls Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace page delete/rotate text-entry flows with scope menus, add angle selection for page rotation, prevent no-op page rotation undo entries, and make the page counter jumpable.

**Architecture:** Centralize page-scope resolution in `PDFView`, keep page mutation signals unchanged except for emitted values, and let `PDFModel.rotate_pages()` define no-op behavior. The jumpable page input reuses existing `sig_page_changed` and `PDFController.change_page()`.

**Tech Stack:** PySide6 `QMenu`/`QLineEdit`, PyMuPDF page rotation, pytest, existing GUI test doubles.

---

## Current Touchpoints

- `view/pdf_view.py`: `_delete_pages()`, `_rotate_pages()`, `_rotate_specific_pages()`, `_setup_toolbar()`, `_update_page_counter()`.
- `model/pdf_model.py`: `rotate_pages()`.
- `controller/pdf_controller.py`: `rotate_pages()` already skips undo if model returns `[]`.
- Tests: `test_scripts/test_thumbnail_context_menu.py`, `test_scripts/test_multi_tab_plan.py`, `test_scripts/test_structural_indexing.py`, plus a new or existing page-control test file.

## Required Behavior

- Page delete scope menu options: `目前頁`, `全部`, `奇數頁`, `偶數頁`, `自訂範圍`.
- Page rotate angle options: `90°`, `180°`, `270°`, `360°`.
- Page rotate scope options: `目前頁`, `全部`, `奇數頁`, `偶數頁`, `自訂範圍`.
- Odd/even are based on 1-based page numbers visible to users.
- Page rotation remains relative/additive for `90`, `180`, `270`.
- `360°` must produce no document mutation and no undo entry.
- The page counter must become an input that accepts 1-based page numbers and emits `sig_page_changed(page - 1)` on Enter.

## Task 1: Add Shared Page Scope Resolver

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_thumbnail_context_menu.py` or `test_scripts/test_page_controls.py`

**Step 1: Write failing tests**

Add tests for a helper such as `_pages_for_scope(scope: str) -> list[int] | None`:

```python
view.total_pages = 6
view.current_page = 2
assert view._pages_for_scope("目前頁") == [3]
assert view._pages_for_scope("全部") == [1, 2, 3, 4, 5, 6]
assert view._pages_for_scope("奇數頁") == [1, 3, 5]
assert view._pages_for_scope("偶數頁") == [2, 4, 6]
```

For `自訂範圍`, monkeypatch `QInputDialog.getText()` to return `"1,3-4"` and assert `[1, 3, 4]`.

**Step 2: Run failing tests**

```powershell
pytest -q test_scripts/test_page_controls.py -k scope
```

Expected: helper missing.

**Step 3: Implement**

Add constants and helper to `PDFView`:

```python
_PAGE_SCOPE_LABELS = ("目前頁", "全部", "奇數頁", "偶數頁", "自訂範圍")

def _pages_for_scope(self, scope: str) -> list[int] | None:
    total = int(getattr(self, "total_pages", 0) or 0)
    if total <= 0:
        show_error(self, "沒有開啟的PDF文件")
        return None
    if scope == "目前頁":
        return [min(max(int(self.current_page) + 1, 1), total)]
    if scope == "全部":
        return list(range(1, total + 1))
    if scope == "奇數頁":
        return [p for p in range(1, total + 1) if p % 2 == 1]
    if scope == "偶數頁":
        return [p for p in range(1, total + 1) if p % 2 == 0]
    if scope == "自訂範圍":
        text, ok = QInputDialog.getText(self, "選擇頁面", "輸入頁碼 (如 1,3-5):")
        if not ok or not text:
            return None
        try:
            return parse_pages(text, total)
        except ValueError:
            show_error(self, "頁碼格式錯誤")
            return None
    return None
```

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_page_controls.py -k scope
```

Expected: pass.

## Task 2: Replace Delete Pages Dialog With Scope Menu

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_page_controls.py`

**Step 1: Write failing tests**

Monkeypatch `QMenu` with a fake that records actions and invokes selected callbacks. Assert `_delete_pages()` exposes all scope labels and emits expected pages for odd/even/custom.

**Step 2: Run failing tests**

```powershell
pytest -q test_scripts/test_page_controls.py -k delete
```

Expected: fails because `_delete_pages()` uses `QInputDialog.getText()`.

**Step 3: Implement**

Replace `_delete_pages()` with a `QMenu`:

```python
def _delete_pages(self):
    if self.total_pages == 0:
        show_error(self, "沒有開啟的PDF文件")
        return
    menu = QMenu(self)
    for scope in self._PAGE_SCOPE_LABELS:
        menu.addAction(scope, lambda checked=False, s=scope: self._delete_pages_for_scope(s))
    menu.exec_(QCursor.pos())

def _delete_pages_for_scope(self, scope: str) -> None:
    pages = self._pages_for_scope(scope)
    if pages:
        self.sig_delete_pages.emit(sorted(set(int(page) for page in pages)))
```

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_page_controls.py -k delete
```

Expected: pass.

**Step 5: Atomic commit**

```powershell
git add -- view/pdf_view.py test_scripts/test_page_controls.py
git commit -m "feat(ui): add scoped page delete menu"
```

## Task 3: Replace Rotate Pages Dialog With Angle And Scope Menus

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_page_controls.py`

**Step 1: Write failing tests**

Assert `_rotate_pages()` exposes angle options `90°`, `180°`, `270°`, `360°`. Assert selecting `180°` then `奇數頁` emits `([1, 3, 5], 180)` for a 5-page document.

**Step 2: Run failing tests**

```powershell
pytest -q test_scripts/test_page_controls.py -k rotate
```

Expected: fails because `_rotate_pages()` uses text/int dialogs.

**Step 3: Implement**

Use an angle menu that opens a scope menu:

```python
def _rotate_pages(self):
    if self.total_pages == 0:
        show_error(self, "沒有開啟的PDF文件")
        return
    menu = QMenu(self)
    for degrees in (90, 180, 270, 360):
        menu.addAction(f"{degrees}°", lambda checked=False, d=degrees: self._rotate_pages_with_scope_menu(d))
    menu.exec_(QCursor.pos())

def _rotate_pages_with_scope_menu(self, degrees: int) -> None:
    menu = QMenu(self)
    for scope in self._PAGE_SCOPE_LABELS:
        menu.addAction(scope, lambda checked=False, s=scope, d=degrees: self._rotate_pages_for_scope(s, d))
    menu.exec_(QCursor.pos())

def _rotate_pages_for_scope(self, scope: str, degrees: int) -> None:
    pages = self._pages_for_scope(scope)
    if pages:
        self.sig_rotate_pages.emit(sorted(set(int(page) for page in pages)), int(degrees))
```

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_page_controls.py -k rotate
```

Expected: pass.

**Step 5: Atomic commit**

```powershell
git add -- view/pdf_view.py test_scripts/test_page_controls.py
git commit -m "feat(ui): add scoped page rotate menu"
```

## Task 4: Skip No-Op Page Rotation

**Files:**
- Modify: `model/pdf_model.py`
- Test: `test_scripts/test_structural_indexing.py` or `test_scripts/test_page_controls.py`

**Step 1: Write failing tests**

Add a model test:

```python
before_rotation = model.doc[0].rotation
rotated = model.rotate_pages([1], 360)
assert rotated == []
assert model.doc[0].rotation == before_rotation
```

Add a controller test if practical: patch `model.rotate_pages` to return `[]` and assert no snapshot command is recorded. Existing controller behavior likely already covers this.

**Step 2: Run failing test**

```powershell
pytest -q test_scripts/test_structural_indexing.py -k rotate
```

Expected: fails because `rotate_pages()` returns `[1]` for 360.

**Step 3: Implement**

At the top of `PDFModel.rotate_pages()` after validating document presence:

```python
try:
    normalized_degrees = int(degrees) % 360
except (TypeError, ValueError):
    normalized_degrees = 0
if normalized_degrees == 0:
    return []
```

Use `normalized_degrees` in `page.set_rotation((page.rotation + normalized_degrees) % 360)`.

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_structural_indexing.py -k rotate
```

Expected: pass.

**Step 5: Atomic commit**

```powershell
git add -- model/pdf_model.py test_scripts/test_structural_indexing.py
git commit -m "fix(model): skip no-op page rotations"
```

## Task 5: Replace Page Counter Label With Jump Input

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_page_controls.py` or `test_scripts/test_multi_tab_plan.py`

**Step 1: Write failing tests**

Assert the right toolbar contains a page input widget and that setting it to `"4"` then pressing Enter emits `sig_page_changed(3)`. Assert invalid input `"0"`, `"abc"`, and `total + 1` reset to the current page and do not emit.

**Step 2: Run failing tests**

```powershell
pytest -q test_scripts/test_page_controls.py -k page_input
```

Expected: fails because only `page_counter_label` exists.

**Step 3: Implement**

In `_setup_toolbar()`, replace:

```python
self.page_counter_label = QLabel("頁 1 / 1")
```

with:

```python
self.page_number_input = QLineEdit("1")
self.page_number_input.setAlignment(Qt.AlignRight)
self.page_number_input.setFixedWidth(52)
self.page_number_input.returnPressed.connect(self._on_page_number_input_return_pressed)
self.page_total_label = QLabel("/ 1")
```

Add:

```python
def _on_page_number_input_return_pressed(self) -> None:
    total = int(getattr(self, "total_pages", 0) or 0)
    try:
        page_num = int(self.page_number_input.text().strip())
    except (TypeError, ValueError):
        self._update_page_counter()
        return
    if total <= 0 or page_num < 1 or page_num > total:
        self._update_page_counter()
        return
    self.sig_page_changed.emit(page_num - 1)
```

Update `_update_page_counter()`:

```python
n = max(1, self.total_pages)
cur = min(self.current_page + 1, n)
if hasattr(self, "page_number_input"):
    if self.page_number_input.text() != str(cur):
        self.page_number_input.blockSignals(True)
        self.page_number_input.setText(str(cur))
        self.page_number_input.blockSignals(False)
if hasattr(self, "page_total_label"):
    self.page_total_label.setText(f"/ {n}")
```

Keep `page_counter_label` only if existing tests require it; if retained, hide it or update it in parallel for compatibility.

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_page_controls.py -k page_input
pytest -q test_scripts/test_multi_tab_plan.py -k page
```

Expected: pass.

**Step 5: Atomic commit**

```powershell
git add -- view/pdf_view.py test_scripts/test_page_controls.py test_scripts/test_multi_tab_plan.py
git commit -m "feat(ui): add jumpable page number input"
```

## Phase Verification

Run:

```powershell
pytest -q test_scripts/test_page_controls.py test_scripts/test_thumbnail_context_menu.py test_scripts/test_structural_indexing.py test_scripts/test_multi_tab_plan.py
```

Expected: all pass.

## Notes For Implementer

- Keep thumbnail context menu single-page rotate/delete actions unchanged.
- Use 1-based page numbers in UI and emitted page lists.
- Use 0-based page index only when emitting `sig_page_changed`.
- Avoid adding new controller APIs for page jump; the signal already exists.
