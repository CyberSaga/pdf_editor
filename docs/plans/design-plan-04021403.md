 Here is Claude's plan:
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
 Next Steps to Acrobat-Level Smooth UX — Eng + Design Reviewed Plan

 Context

 Week 1 shipped 5 Acrobat-parity fixes (block outlines, cursor, redo alias, padding, mode-switch commit) +
 MoveTextRequest typed signal. 73 tests pass across 8 suites. The question: what's the highest-leverage Week 2 sprint
 to close the remaining Acrobat gap?

 This plan is eng-reviewed: each step has been verified against actual code paths, with specific line numbers and risk
 assessments.

 ---
 Step 1: Fix size: int → size: float in dataclasses

 Risk: LOW | Effort: S (~10 min) | Impact: Correctness

 What

 - view/text_editing.py:91 — EditTextRequest.size: int → size: float
 - view/text_editing.py:123 — MoveTextRequest.size: int → size: float

 Why

 PyMuPDF span["size"] returns float. Current int silently truncates (9.5pt → 9pt), corrupting style fidelity.

 Eng Notes

 - model/pdf_model.py:2316 — edit_text() signature also has size: int = 12. Must update to size: float = 12.0 for
 consistency.
 - model/pdf_model.py:2519 already does abs(float(size) - float(target.size)) — so the comparison logic is safe, but
 the parameter type annotation is wrong.
 - model/pdf_model.py:2569 — _convert_text_to_html(new_text, int(size), ...) explicitly casts to int. This is
 intentional for HTML rendering (CSS px values). Do NOT change this cast — it's the output side, not the data model
 side.
 - EditTextRequest.to_legacy_args() passes self.size directly to edit_text() — type flows through cleanly.
 - Python int is assignment-compatible with float, so no caller breakage.

 Files to modify

 1. view/text_editing.py — both dataclass fields
 2. model/pdf_model.py — edit_text() signature annotation
 3. Test fixtures if any pass explicit size=12 (grep for size= in test files)

 Verification

 - python -m pytest test_scripts/test_text_edit_manager_foundation.py test_scripts/test_text_editing_gui_regressions.py
  -v
 - Grep for size= across codebase to verify no truncation sites remain

 ---
 Step 2: edit_text() Phase Extraction (~400 LOC → 3 helpers)

 Risk: MODERATE | Effort: M (~30 min CC) | Impact: Maintainability + unlocks future UX

 What

 Decompose model/pdf_model.py:2315-2750+ into three helpers:
 1. _resolve_target(page_idx, rect, original_text, target_span_id, target_mode) → returns resolved span, mode, cluster,
  protected spans
 2. _apply_redact_insert(page, target, new_text, font, size, color, ...) → handles Steps 2+3 (redaction + 3-strategy
 insert)
 3. _verify_rebuild(page, page_idx, new_text, new_layout_rect, snapshot_bytes) → handles Step 4+5 (verification +
 rollback + index update)

 Eng Notes — Phase Boundaries (verified from code)

 Phase 1 → _resolve_target() (lines 2343-2537)
 - Input: page_num, rect, new_text, font, size, color, original_text, target_span_id, target_mode
 - Output: A result object containing: target_span, effective_target_mode, resolved_target_span_id,
 target_member_span_ids, overlap_cluster, protected_spans, cluster_union, target (block), resolved_font, rotation,
 is_vertical, redact_rect, insert_rotate
 - Also includes the no-op early return check (lines 2525-2537)
 - Risk: This phase has the most local variables that downstream phases consume. The result object must capture ~15
 values. Recommend a _ResolveResult NamedTuple or dataclass.

 Phase 2 → _apply_redact_insert() (lines 2544-2794)
 - Input: page, page_rect, the resolve result, new_text, size, color, html_content, css, new_rect, vertical_shift_left
 - Output: new_layout_rect
 - Contains: redaction, annotation save/restore, protected span replay, pre-push probe, vertical binary shrink,
 Strategy A/B/C
 - Risk: Deepest nesting and most complex branching. Has page-mutating side effects (redaction, insert_htmlbox). If
 extraction breaks, text corruption is possible. Must have snapshot rollback wrapping the call.

 Phase 3 → _verify_rebuild() (lines 2797-end)
 - Input: page, page_idx, new_text, new_layout_rect, snapshot_bytes, rollback context
 - Output: success/rollback
 - Contains: full-page text verification, clip verification, token coverage check, rollback decision,
 block_manager.update_block()

 Constraints

 - Structural only — no behavioral changes. Each extracted method must produce identical results.
 - edit_text() becomes an orchestrator: snapshot → resolve → redact_insert → verify_rebuild
 - The try/except rollback at line 2402 must wrap all three phases
 - _capture_page_snapshot() call stays in edit_text() (before the orchestration)

 Verification

 - Run full test suite after each extraction: python -m pytest test_scripts/ -v
 - Zero test regressions required at each step
 - Extract one phase at a time, test, commit, then extract next

 ---
 Step 3: Error Toasts for Invalid Operations

 Risk: LOW | Effort: M (~20 min) | Impact: UX — eliminates silent failures

 What

 Surface toast notifications when edit operations fail silently.

 Eng Notes — Where Silent Failures Occur (verified from code)

 1. edit_text() line 2417 — return with only logger.warning when target block not found
 2. edit_text() line 2452 — return when target span unresolvable
 3. edit_text() line 2537 — no-op early return (text/style unchanged) — this is intentional, NOT an error
 4. Strategy C failure, line 2770-2776 — raises RuntimeError but caller may swallow it

 Approach

 - edit_text() currently returns None on both success and failure. Change return type to bool or a result enum
 (EditResult.SUCCESS | NOT_FOUND | NO_CHANGE | ROLLBACK).
 - Controller (pdf_controller.py) already calls edit_text() — add result checking there and emit toast via existing
 toast pattern in pdf_view.py.
 - Reuse the mode-switch toast infrastructure (already in pdf_view.py).

 Design Review — Toast Visual Language

 The existing toast (line 2104-2118) uses a single dark-background style for success ("文字已儲存"). Error toasts need
 visual differentiation:

 ┌───────────────────┬───────────────────────────────┬──────────┬──────────────────────────────────────────────────┐
 │    Toast Type     │          Background           │ Duration │                     Use Case                     │
 ├───────────────────┼───────────────────────────────┼──────────┼──────────────────────────────────────────────────┤
 │ Success           │ rgba(40,40,40,200) dark gray  │ 1500ms   │ Mode-switch auto-save                            │
 │ (existing)        │                               │          │                                                  │
 ├───────────────────┼───────────────────────────────┼──────────┼──────────────────────────────────────────────────┤
 │ Error (new)       │ rgba(180,40,40,220) muted red │ 2500ms   │ Target not found, edit failed                    │
 ├───────────────────┼───────────────────────────────┼──────────┼──────────────────────────────────────────────────┤
 │ Info (new,        │ rgba(40,40,40,200) same as    │ 1200ms   │ No-op (text unchanged) — skip this, silent is    │
 │ optional)         │ success                       │          │ correct for no-ops                               │
 └───────────────────┴───────────────────────────────┴──────────┴──────────────────────────────────────────────────┘

 Design decisions:
 1. Error toasts must be longer (2500ms vs 1500ms) — errors need more reading time, especially for Chinese text.
 2. Error color is muted red, not bright red — matches the app's neutral #F1F5F9 toolbar palette; avoids alarm-bell UX
 for recoverable situations.
 3. Position stays bottom-center — consistent with existing success toast. Do NOT move error toasts to top (would
 conflict with toolbar) or center-screen (would block the editing area).
 4. Copy must be actionable, not technical — e.g., "找不到目標文字" (target text not found) not "target_span_id
 resolution failed".
 5. No toast for no-op — silent is the correct behavior when text is unchanged. Acrobat doesn't toast for no-ops
 either.

 Recommended error messages:
 - Target block not found: "找不到可編輯的文字區塊" (Cannot find editable text block)
 - Target span unresolvable: "無法定位目標文字" (Cannot locate target text)
 - Strategy A/B/C all failed: "文字插入失敗，已復原" (Text insertion failed, reverted)

 Files to modify

 1. model/pdf_model.py — add return values to edit_text() failure paths
 2. controller/pdf_controller.py — check return value, emit toast signal
 3. view/pdf_view.py — extend _show_toast() with optional style parameter ("error" | "success")

 Verification

 - Manual test: click empty area in edit mode → red-tinted toast should appear
 - Add 2 regression tests for error paths

 ---
 Step 4: Undo/Redo State Feedback

 Risk: LOW | Effort: S (~15 min) | Impact: UX polish

 What

 Disable/gray-out undo/redo toolbar buttons when stack is empty.

 Eng Notes

 - Need to verify how CommandManager exposes stack state (likely can_undo() / can_redo() or stack length check)
 - Connect state query to toolbar button enabled/disabled after each edit operation
 - Must update state on: edit commit, undo, redo, document load, document close
 - Existing actions: self._action_undo and self._action_redo (pdf_view.py:1534-1536) — use QAction.setEnabled(bool)

 Design Review — Undo/Redo Visual States

 Acrobat reference behavior:
 - Undo grayed out: no edits in history
 - Redo grayed out: no undone operations (or new edit after undo clears redo stack)
 - Both grayed on fresh document open

 Implementation approach for this app:
 - self._action_undo.setEnabled(False) when undo stack empty — Qt handles graying automatically for QToolBar actions
 - self._action_redo.setEnabled(False) when redo stack empty
 - Keyboard shortcuts (Ctrl+Z, Ctrl+Y, Ctrl+Shift+Z) should also be no-ops when disabled — Qt QAction.setEnabled(False)
  handles this automatically since the shortcuts are bound to the actions
 - During active text editing (QTextEdit has focus): undo/redo buttons should reflect the editor-local undo state
 (QTextEdit.document().isUndoAvailable()), NOT the global command stack. This matches Acrobat: undo inside an active
 text edit undoes typing, not the previous page-level operation.

 Edge case: When text editor is open, the toolbar undo/redo reflect editor-local state. When editor closes, they switch
  back to global CommandManager state. The transition must be seamless.

 Files to modify

 1. controller/pdf_controller.py — emit undo/redo availability signal after each operation
 2. view/pdf_view.py — connect to _action_undo.setEnabled() / _action_redo.setEnabled(); also connect to editor-local
 state during active editing

 Verification

 - Manual: edit text, verify undo enabled; undo, verify redo enabled + undo grayed if stack empty
 - Manual: open text editor, type, verify undo reflects local typing state
 - Add 1 test for state query

 ---
 Deferred (Month 3+)

 ┌───────────────────────────┬─────────────────────────────────────────┬──────────────────────────────────────────┐
 │           Item            │                Why Defer                │            Risk of Deferring             │
 ├───────────────────────────┼─────────────────────────────────────────┼──────────────────────────────────────────┤
 │ Text selection highlight  │ Requires QGraphicsScene overlay work,   │ Low — users click to edit, selection is  │
 │                           │ moderate effort                         │ nice-to-have                             │
 ├───────────────────────────┼─────────────────────────────────────────┼──────────────────────────────────────────┤
 │ Inline formatting         │ Major feature: rich-text pipeline       │ Medium — users editing styled PDFs lose  │
 │ (bold/italic)             │ rewrite                                 │ formatting                               │
 ├───────────────────────────┼─────────────────────────────────────────┼──────────────────────────────────────────┤
 │ Live drag preview         │ Complex cross-page rendering            │ Low — commit-then-move works             │
 ├───────────────────────────┼─────────────────────────────────────────┼──────────────────────────────────────────┤
 │ TextEditSession           │ Architectural refactor, no user-visible │ Low short-term, but increases fragility  │
 │ consolidation             │  change                                 │ risk over time                           │
 ├───────────────────────────┼─────────────────────────────────────────┼──────────────────────────────────────────┤
 │ Acrobat baseline audit    │ Blocked on Acrobat installation         │ Blocks confident "Acrobat-level" claims  │
 ├───────────────────────────┼─────────────────────────────────────────┼──────────────────────────────────────────┤
 │ Viewport 180ms            │ Works reliably; root cause unclear      │ Low — workaround is stable               │
 │ double-restore            │                                         │                                          │
 └───────────────────────────┴─────────────────────────────────────────┴──────────────────────────────────────────┘

 ---
 Execution Order & Dependencies

 Step 1 (size float) ─── independent, do first (quick win)
      │
 Step 2 (phase extraction) ─── depends on Step 1 being landed (size type must be correct before refactor)
      │
 Step 3 (error toasts) ─── depends on Step 2 (edit_text return values easier to add during extraction)
      │
 Step 4 (undo/redo state) ─── independent of Steps 2-3, can parallel with Step 3

 Key Files

 ┌───────────────────────────────────────────────────┬────────────┬──────────────────────────────────────────────┐
 │                       File                        │   Lines    │                     Role                     │
 ├───────────────────────────────────────────────────┼────────────┼──────────────────────────────────────────────┤
 │ view/text_editing.py                              │ 1-128      │ EditTextRequest, MoveTextRequest dataclasses │
 ├───────────────────────────────────────────────────┼────────────┼──────────────────────────────────────────────┤
 │ model/pdf_model.py                                │ 2315-2850+ │ edit_text() — the ~400 LOC method to extract │
 ├───────────────────────────────────────────────────┼────────────┼──────────────────────────────────────────────┤
 │ view/pdf_view.py                                  │ throughout │ Toast overlay, toolbar, block outlines       │
 ├───────────────────────────────────────────────────┼────────────┼──────────────────────────────────────────────┤
 │ controller/pdf_controller.py                      │ 1444-1584  │ Edit coordination, undo/redo                 │
 ├───────────────────────────────────────────────────┼────────────┼──────────────────────────────────────────────┤
 │ test_scripts/test_text_edit_manager_foundation.py │ all        │ Foundation tests                             │
 ├───────────────────────────────────────────────────┼────────────┼──────────────────────────────────────────────┤
 │ test_scripts/test_text_editing_gui_regressions.py │ all        │ GUI regression tests                         │
 └───────────────────────────────────────────────────┴────────────┴──────────────────────────────────────────────┘