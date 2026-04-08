# TODOS

## Acrobat Baseline For UX Audit

- What: Set up at least one test environment with Adobe Acrobat available for side-by-side UX benchmarking against this PDF editor.
- Why: The planned "Acrobat-level" audit depends on direct baseline comparison for task time, shortcut parity, focus behavior, and recovery UX. This device does not currently have Acrobat installed, so local parity testing is blocked.
- Pros: Enables real benchmark runs instead of internal-only scoring; prevents false claims of Acrobat-level smoothness; gives us a control app for ambiguous UX judgments.
- Cons: Requires access to a licensed/installable Acrobat environment; adds setup overhead before the full audit can be completed.
- Context: Existing GUI audits in this repo already cover many text-editing and focus/undo regressions, but they only validate this app in isolation. The missing Acrobat baseline means we can measure "good" or "bad" internally, but not "Acrobat-like" with confidence.
- Depends on / blocked by: Acrobat installation or access to another Windows machine/VM with Acrobat; final parity audit should stay blocked until that baseline environment exists.

## Done (2026-04-08) — PDFModel.edit_text() Phase Extraction

- What: Extracted `_resolve_effective_target_mode()` from `edit_text()`. Added 15 unit tests covering all three phase helpers (`_resolve_edit_target`, `_apply_redact_insert`, `_verify_rebuild_edit`) plus the new target-mode resolver.
- Why: Per-phase tests enable faster root-cause isolation; each helper is now independently testable.
- Outcome: `test_scripts/test_edit_text_helpers.py` covers happy paths, edge cases (missing block, no-change, empty text, rollback), and target-mode resolution heuristics.

## Done (2026-04-07) — Route Controller Through Typed Edit Requests

- What: Moved `EditTextRequest` and `MoveTextRequest` into `model/edit_requests.py`, re-exported from `view/text_editing.py`, routed `PDFController.edit_text()` through `EditTextCommand.from_request()`.
- Why: Keeps the typed payload intact from view to controller to command, removes repeated field unpacking, preserves the intended dependency direction.
- Outcome: Foundation tests cover request importability, controller routing, command construction, and same-page move reroute through typed payloads.

## Done (2026-04-07) — Fix size field type in EditTextRequest and MoveTextRequest

- What: Changed `size` to `float` in both request dataclasses.
- Why: PyMuPDF returns font sizes as floats; coercing to `int` silently truncates fractional sizes.
- Outcome: Request payloads match PyMuPDF's data model; canonical types now live in `model/edit_requests.py`.
