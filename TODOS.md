# TODOS

## Acrobat Baseline For UX Audit

- What: Set up at least one test environment with Adobe Acrobat available for side-by-side UX benchmarking against this PDF editor.
- Why: The planned "Acrobat-level" audit depends on direct baseline comparison for task time, shortcut parity, focus behavior, and recovery UX. This device does not currently have Acrobat installed, so local parity testing is blocked.
- Pros: Enables real benchmark runs instead of internal-only scoring; prevents false claims of Acrobat-level smoothness; gives us a control app for ambiguous UX judgments.
- Cons: Requires access to a licensed/installable Acrobat environment; adds setup overhead before the full audit can be completed.
- Context: Existing GUI audits in this repo already cover many text-editing and focus/undo regressions, but they only validate this app in isolation. The missing Acrobat baseline means we can measure "good" or "bad" internally, but not "Acrobat-like" with confidence.
- Depends on / blocked by: Acrobat installation or access to another Windows machine/VM with Acrobat; final parity audit should stay blocked until that baseline environment exists.

## Month 3 — PDFModel.edit_text() Phase Extraction

- What: Decompose `PDFModel.edit_text()` (~400 LOC) into three helper methods: `_resolve_target()`, `_apply_redact_insert()`, `_verify_rebuild()`.
- Why: Right now if edit_text() breaks, you trace through 400 lines to isolate which phase failed. Phase helpers make each step independently testable and reduce debugging time from minutes to seconds.
- Pros: True unit tests per phase; faster root-cause isolation on failures; cleaner model layer — each phase has a clear input/output contract.
- Cons: edit_text() is the most battle-tested code in the codebase. Refactoring it carries real regression risk. Must have comprehensive test coverage *before* the refactor touches any logic.
- Context: The 7 phases are already documented in edit_text()'s docstring (model/pdf_model.py:2323-2341). The extraction is structural only — no behavioral changes. The MoveTextRequest + foundation tests (current plan) must land first to ensure the foundation is locked before the model is touched.
- Effort: M (human: 3-5 days / CC: ~30 min)
- Priority: P2
- Depends on / blocked by: Current MoveTextRequest + foundation tests plan must land first.

## Fix size field type in EditTextRequest and MoveTextRequest

- What: Change `size: int` to `size: float` in both `EditTextRequest` and `MoveTextRequest` dataclasses in `view/text_editing.py`.
- Why: PyMuPDF returns font sizes as floats (`span["size"]` is float). Coercing to `int` silently truncates 9.5pt → 9pt, corrupting style fidelity on every text edit that uses fractional font sizes.
- Pros: Correct type; no silent data loss; matches PyMuPDF's actual data model.
- Cons: May require updating callers that pass int literals for size (trivial in Python since int is assignment-compatible with float); may need test fixture updates.
- Context: Both dataclasses currently use `int`. This is a pre-existing issue in `EditTextRequest` that should be fixed at the same time as `MoveTextRequest` to avoid two separate migrations. Discovered during eng review cross-model analysis (2026-04-01).
- Effort: S (human: 30 min / CC: ~5 min)
- Priority: P2
- Depends on / blocked by: None (independent fix, but do both dataclasses together).
