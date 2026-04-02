# MoveTextRequest Implementation Report

*Date: 2026-04-02 | Branch: `codex/text-editing-function-by-iterating-repeatedly` | Commit: `683a103`*

---

## What Was Done

Typed the last untyped signal in the text-editing pipeline. `sig_move_text_across_pages` previously emitted 11 positional arguments (fragile, untyped). It now emits a single frozen `MoveTextRequest` dataclass, matching the `EditTextRequest` pattern already used by `sig_edit_text`.

## Why

Positional-arg signals are an implicit contract that breaks silently when argument order changes. Named dataclass fields break loudly with `AttributeError`. This change eliminates the last positional-arg signal in the edit pipeline, making the View-to-Controller contract fully typed and self-documenting.

## Files Modified

| File | Change | Lines |
|------|--------|-------|
| `view/text_editing.py` | Added `MoveTextRequest` frozen dataclass (11 fields); changed emission from 11 positional args to single `MoveTextRequest` object | +25/-12 |
| `view/pdf_view.py` | Added `MoveTextRequest` to import block; changed signal declaration from `Signal(int, object, int, object, str, str, int, tuple, str, object, str)` to `Signal(object)` | +3/-1 |
| `controller/pdf_controller.py` | Added `MoveTextRequest` import; simplified `move_text_across_pages()` from 11 parameters to single typed request | +13/-17 |
| `test_scripts/test_text_edit_manager_foundation.py` | Added 3 new tests: `test_sig_move_text_emits_move_text_request`, `test_move_text_request_fields_match_session`, `test_controller_accepts_move_text_request` | +101 |
| `test_scripts/test_text_editing_gui_regressions.py` | Fixed mandatory regression: changed tuple indexing (`call[0]==1`) to attribute access (`request.source_page==1`); hoisted `MoveTextRequest` import to module level | +9/-5 |
| `TODOS.md` | Added 2 future items: Month 3 model phase extraction (P2); `size: int` to `float` fix (P2) | +22 |

**Total: 6 files, +174 insertions, -35 deletions**

## MoveTextRequest Shape

```python
@dataclass(frozen=True)
class MoveTextRequest:
    source_page: int
    source_rect: fitz.Rect
    destination_page: int
    destination_rect: fitz.Rect
    new_text: str
    font: str
    size: int
    color: tuple
    original_text: str | None = None
    target_span_id: str | None = None
    target_mode: str | None = None
```

## Signal Flow (Before/After)

```
BEFORE:
  TextEditManager.finalize_text_edit_impl()
    -> sig_move_text_across_pages.emit(int, obj, int, obj, str, str, int, tuple, str, obj, str)
    -> controller.move_text_across_pages(source_page, source_rect, ...)

AFTER:
  TextEditManager.finalize_text_edit_impl()
    -> MoveTextRequest(source_page, source_rect, dest_page, dest_rect, ...)
    -> sig_move_text_across_pages.emit(request)
    -> controller.move_text_across_pages(request: MoveTextRequest)
```

## Review Summary

- **Pre-landing review:** 0 critical, 1 informational (auto-fixed: import hoisted to module level)
- **Adversarial review (Claude subagent):** 6 findings, all pre-existing patterns not introduced by this diff
- **Plan completion:** 10/10 items DONE
- **Test results:** 73 passed, 0 failures across all 8 test suites

## Known Limitations (Pre-existing, Not Introduced)

- `fitz.Rect` is mutable in a frozen dataclass (same as `EditTextRequest`)
- `size: int` should be `float` — tracked in TODOS.md as P2
- `Signal(object)` accepts any Python object — same pattern as `sig_edit_text`

## What's Next

- **Month 3:** `PDFModel.edit_text()` phase extraction (depends on this landing)
- **P2:** `size: int` -> `size: float` in both `EditTextRequest` and `MoveTextRequest`
- **Blocked:** Acrobat baseline environment for UX audit
