# TODOS

## Acrobat Baseline For UX Audit

- What: Set up at least one test environment with Adobe Acrobat available for side-by-side UX benchmarking against this PDF editor.
- Why: The planned "Acrobat-level" audit depends on direct baseline comparison for task time, shortcut parity, focus behavior, and recovery UX. This device does not currently have Acrobat installed, so local parity testing is blocked.
- Pros: Enables real benchmark runs instead of internal-only scoring; prevents false claims of Acrobat-level smoothness; gives us a control app for ambiguous UX judgments.
- Cons: Requires access to a licensed/installable Acrobat environment; adds setup overhead before the full audit can be completed.
- Context: Existing GUI audits in this repo already cover many text-editing and focus/undo regressions, but they only validate this app in isolation. The missing Acrobat baseline means we can measure "good" or "bad" internally, but not "Acrobat-like" with confidence.
- Depends on / blocked by: Acrobat installation or access to another Windows machine/VM with Acrobat; final parity audit should stay blocked until that baseline environment exists.

## Month 3 - PDFModel.edit_text() Phase Extraction

- What: Decompose `PDFModel.edit_text()` (~400 LOC) into three helper methods: `_resolve_target()`, `_apply_redact_insert()`, `_verify_rebuild()`.
- Why: Right now if `edit_text()` breaks, you trace through 400 lines to isolate which phase failed. Phase helpers make each step independently testable and reduce debugging time from minutes to seconds.
- Pros: True unit tests per phase; faster root-cause isolation on failures; cleaner model layer where each phase has a clear input/output contract.
- Cons: `edit_text()` is the most battle-tested code in the codebase. Refactoring it carries real regression risk. It still needs comprehensive test coverage before the refactor touches any logic.
- Context: The 7 phases are already documented in `edit_text()`'s docstring (`model/pdf_model.py`). The extraction is structural only, with no behavioral changes. The typed request-routing foundation landed on 2026-04-07, so this task is now unblocked.
- Effort: M (human: 3-5 days / CC: ~30 min)
- Priority: P2
- Depends on / blocked by: None.

## Done (2026-04-07) - Route Controller Through Typed Edit Requests

- What: Moved `EditTextRequest` and `MoveTextRequest` into `model/edit_requests.py`, re-exported them from `view/text_editing.py`, and routed `PDFController.edit_text()` through `EditTextCommand.from_request()`.
- Why: Keeps the typed payload intact from view to controller to command, removes repeated field unpacking, and preserves the intended dependency direction.
- Outcome: Foundation tests now cover request importability, controller routing, command construction, and same-page move reroute through typed payloads.

## Done (2026-04-07) - Fix size field type in EditTextRequest and MoveTextRequest

- What: Changed `size` to `float` in both request dataclasses.
- Why: PyMuPDF returns font sizes as floats (`span["size"]` is float). Coercing to `int` silently truncates fractional sizes and corrupts style fidelity.
- Pros: Correct type; no silent data loss; matches PyMuPDF's actual data model.
- Cons: Callers that assume `int` may need trivial fixture updates.
- Context: The canonical request types now live in `model/edit_requests.py` and both use `float`.
- Outcome: Request payloads match PyMuPDF's data model and no longer risk silent truncation.
