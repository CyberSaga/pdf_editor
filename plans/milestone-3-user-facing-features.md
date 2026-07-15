# Milestone 3 — User-Facing Features

**Status:** In progress (tranche 3.0 started 2026-07-15)

## Goal

Implement all 24 requirements in `docs/to_Update.md` plus the four carried M3 features, using the acceptance criteria in `plans/archive/2026-07-02-to-update-test-plan-acceptance-criteria.md` and the evidence in `plans/2026-07-10-m3-feasibility-recon.json`.

The detailed authoritative roadmap is maintained outside this repository. This repo plan tracks execution and decisions. The Acrobat-parity text commit engine (`plans/2026-07-14-acrobat-parity-text-commit-engine.md`) is explicitly **out of M3**.

## Affected areas

- Shell, tabs, thumbnails, interaction modes, annotations: `view/`, chiefly `view/pdf_view.py`
- Mutation coordination, rendering, print and session state: `controller/`
- Page structure, metadata, TOC and annotation persistence: `model/`
- Preferences, platform single-instance behavior and render limits: `utils/`
- Printing: `src/printing/`
- Acceptance/regression coverage: `test_scripts/`

## Execution order

- [x] **3.0 Pre-flight (2026-07-15):** mode-contract guard; perf baseline; AC-FIX-05 / AC-NEW-10 addenda
- [ ] **3.1 Quick wins:** thumbnail centering/invalidation, Enter search navigation, Ctrl+W, decimal font size
- [ ] **3.2 platform/print:** paper centering, existing-window raise, fresh-boot print diagnosis, icon scope
- [ ] **3.3 Page structure:** delete-all placeholder, custom ranges, thumbnail page reorder
- [ ] **3.4 Shell/tab UX:** 720×520 shell, tab X/context menu, nav keys, MRU
- [ ] **3.5 Editing tools:** edge resize, rectangle style, underline/strikeout, metadata (existing edit path only)
- [ ] **3.6 Render/geometry:** render offload, complex vector performance, document centering, numeric double-click
- [ ] **3.7 Notes/bookmarks:** floating notes and TOC panel
- [ ] **3.8 Tab detach:** full drag-out to an in-process second window (last, XL)

Only 3.5 and 3.6 may swap. All other tranches land serially. L/XL features receive their own plan before implementation.

## Binding decisions

1. Tab detach is the full drag-out gesture, not an “Open in new window” substitute.
2. Delete-all prompts, then retains one model-side blank placeholder; inserting real pages removes it in the same undo unit.
3. Packaged-EXE embedded icon remains deferred to the distribution track.
4. The text-commit engine is not part of M3 and must not expand tranche 3.5.

## Guardrails

- View emits signals; Controller coordinates mutations; Model owns document correctness.
- View-local modes are explicitly documented and all controller modes must be valid View modes.
- No scene x-position changes outside tranche 3.6.
- Page insert/delete/move use SnapshotCommand and stale-index maintenance.
- Background work uses QThread + Signals; never `threading.Thread` in View/Controller.
- Red-light tests precede behavior changes.

## Open questions

- AC-FIX-03 may be an intentional touched-precedence product decision; decide only after live platform reproduction.
- AC-NEW-03 undo-history transfer limitation is decided in `plans/tab-detach.md` before implementation.
- Complex-vector optimization beyond worker offload requires profiler evidence.

## Completion

After each tranche: update PITFALLS.md (+ index), ARCHITECTURE.md when responsibilities/APIs change, TODOS.md and FEATURES.md; run the repository test suite, `ruff check .`, and the repository type checks. Archive this plan only after tranche completion and milestone acceptance are complete.
