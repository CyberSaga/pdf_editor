# Plan: Task 3 — Route Controller Through Typed Edit Requests

## Context

The Month 2 foundation plan extracts text-edit lifecycle into typed dataclasses. Tasks 1–2 landed `EditTextRequest` and `MoveTextRequest` in `view/text_editing.py`, and the view already emits them via signals. But the controller immediately unpacks them back into 10+ local variables, and `EditTextCommand` takes 14 individual args that duplicate request fields. Task 3 cleans this up so the typed request flows through controller → command without unnecessary unpacking.

**Critical constraint:** `EditTextRequest` lives in `view/text_editing.py`. Model layer has zero imports from `view/` (confirmed). For `EditTextCommand` (in `model/edit_commands.py`) to accept the dataclass, it must move to the model layer.

## Engineering Review Summary

### Architecture (Step 1)
- Moving dataclasses to `model/edit_requests.py` improves dependency direction (Controller → Model, View → Model — both already established patterns)
- View re-exports for backward compat — all existing import paths preserved
- **Key finding:** `_reflow_fn` closure has subtle `None`-coercion risk when switching from `original_text or ""` local to `request.original_text`. All `or ""` guards must be preserved at point of use.

### Code Quality (Step 2)
- DRY improvement: field-list repetitions reduced from 5 → 3
- Frozen dataclass means `None`-coercions need a local var for the mutated value (can't assign to `request.new_text`)
- `to_legacy_args()` is likely dead code — defer removal to follow-up

### Test Coverage (Step 3)
- 5 new tests + 1 updated test cover 100% of new codepaths
- `_reflow_fn` closure tested indirectly through integration (acceptable)
- Legacy positional-arg path covered by existing test (line 271)

### Risk Assessment (Step 4)
| Risk | Severity | Mitigation |
|------|----------|------------|
| Missed `request.field` ref after removing local unpacking | Medium | Write tests first; grep-verify all bare refs |
| `fitz.Rect` mutability in frozen dataclass | Low (pre-existing) | Defensive copies already in `EditTextCommand.__init__` |
| Circular import | Very low | `model.edit_requests` imports only `fitz` + stdlib |

---

## Implementation Steps

### Pre-step: Update TODOS.md
Mark `size: float` fix as done (both dataclasses already use `size: float`).

### Step 1 — Write failing tests (Red)

**File:** `test_scripts/test_text_edit_manager_foundation.py`

Add 5 new tests:
1. `test_edit_text_request_importable_from_model` — `from model.edit_requests import EditTextRequest, MoveTextRequest` succeeds
2. `test_edit_text_command_from_request_fields` — factory creates command with all fields matching the request
3. `test_edit_text_command_from_request_execute` — `execute()` calls `model.edit_text()` with correct positional/keyword args
4. `test_controller_edit_text_accepts_request_object` — pass `EditTextRequest` to `controller.edit_text()`, verify it works
5. `test_edit_text_request_none_coercion` — `None` new_text/original_text handled correctly at controller level

Update 1 existing test:
6. `test_controller_accepts_move_text_request` (line 197) — change assertions from positional args to `isinstance(args[0], EditTextRequest)`

Run `pytest test_scripts/test_text_edit_manager_foundation.py -q` → confirm failures.

### Step 2 — Create `model/edit_requests.py`

**New file:** `model/edit_requests.py`
- Move `EditTextRequest` (lines 86-113) and `MoveTextRequest` (lines 116-128) from `view/text_editing.py`
- Include `from __future__ import annotations`, `dataclasses`, `fitz` only — no Qt

**Edit:** `view/text_editing.py`
- Replace class definitions with `from model.edit_requests import EditTextRequest, MoveTextRequest`

**Edit:** `controller/pdf_controller.py:21`
- Change import to `from model.edit_requests import EditTextRequest, MoveTextRequest`
- Remove them from the `view.pdf_view` import line

**Edit:** test files that import directly:
- `test_text_edit_manager_foundation.py:19`
- `test_text_editing_gui_regressions.py:22`

### Step 3 — Add `EditTextCommand.from_request()` classmethod

**File:** `model/edit_commands.py`

```python
@classmethod
def from_request(cls, model, request: EditTextRequest, page_snapshot_bytes: bytes,
                 old_block_id=None, old_block_text=None, reflow_fn=None):
    inst = cls(
        model=model, page_num=request.page, rect=request.rect,
        new_text=request.new_text, font=request.font, size=request.size,
        color=request.color, original_text=request.original_text,
        vertical_shift_left=request.vertical_shift_left,
        page_snapshot_bytes=page_snapshot_bytes,
        old_block_id=old_block_id, old_block_text=old_block_text,
        new_rect=request.new_rect, target_span_id=request.target_span_id,
        target_mode=request.target_mode, reflow_fn=reflow_fn,
    )
    inst._request = request
    return inst
```

Import `from model.edit_requests import EditTextRequest` at module top.

### Step 4 — Fix same-page reroute in `move_text_across_pages`

**File:** `controller/pdf_controller.py:1654-1667`

Replace positional-arg call:
```python
if source_page == destination_page:
    self.edit_text(EditTextRequest(
        page=source_page, rect=request.source_rect,
        new_text=new_text, font=font, size=size, color=color,
        original_text=original_text, vertical_shift_left=True,
        new_rect=request.destination_rect,
        target_span_id=target_span_id, target_mode=target_mode,
    ))
    return
```

### Step 5 — Refactor controller `edit_text()` to use request object

**File:** `controller/pdf_controller.py:1488-1605`

- Keep polymorphic signature (accepts `EditTextRequest` OR positional args)
- Keep normalizing to `request` variable (lines 1488-1502)
- **Remove** 11-line local unpacking block (lines 1504-1514)
- Keep derived locals:
  - `new_text = request.new_text if request.new_text is not None else ""`
  - `page_idx = request.page - 1`
- Update `_reflow_fn` closure: capture `request` instead of 6+ individual locals
  - `_request.original_text or ""` (preserve coercion!)
  - `_request.font`, `_request.size`, `_request.color`
  - Keep `_edit_rect` and `_page_idx` as computed locals
- Command construction → `EditTextCommand.from_request(model, request, snapshot, ...)`
- Update all remaining bare references: `font` → `request.font`, `color` → `request.color`, etc.

### Step 6 — Update imports across codebase

Ensure all files import from canonical `model.edit_requests` or via backward-compat `view.text_editing` re-export.

### Step 7 — Run full suite (Green)

```bash
pytest test_scripts/test_text_edit_manager_foundation.py -q
pytest test_scripts/test_text_editing_gui_regressions.py -q
pytest -q
ruff check .
mypy model/ utils/
```

### Step 8 — Update docs

- `docs/ARCHITECTURE.md` — document `model/edit_requests.py` as shared typed edit payloads
- `docs/PITFALLS.md` — note: `EditTextRequest` must stay Qt-free for model-layer importability
- `TODOS.md` — mark Task 3 done, mark size fix done

---

## Files Touched

| File | Action |
|------|--------|
| `model/edit_requests.py` | **Create** — canonical home for `EditTextRequest`, `MoveTextRequest` |
| `view/text_editing.py` | Edit — replace definitions with re-import |
| `model/edit_commands.py` | Edit — add `from_request()` classmethod + import |
| `controller/pdf_controller.py` | Edit — use request object, fix reroute, clean closure |
| `test_scripts/test_text_edit_manager_foundation.py` | Edit — 5 new + 1 updated test |
| `test_scripts/test_text_editing_gui_regressions.py` | Edit — update import |
| `docs/ARCHITECTURE.md` | Edit — document new module |
| `docs/PITFALLS.md` | Edit — add Qt-free constraint note |
| `TODOS.md` | Edit — mark items done |
