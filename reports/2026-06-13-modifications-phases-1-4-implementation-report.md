# Modifications Implementation Report: Phases 1-5

Date: 2026-06-13

Scope: implementation progress for `modifications.md` through:

- `plans/2026-06-13-modifications-phase-1-f1-rectangle-preview.md`
- `plans/2026-06-13-modifications-phase-2-page-controls.md`
- `plans/2026-06-13-modifications-phase-3-object-rotation.md`
- `plans/2026-06-13-modifications-phase-4-insert-password.md`
- `plans/2026-06-13-modifications-phase-5-deskew-build.md`

## Phase 1: F1 Browse Mode and Rectangle Preview

Commits:

- `2e9a899 feat(ui): add F1 browse and rect preview`
- `f2ad2e1 fix(ui): harden rectangle preview cancellation`

Implemented:

- Added F1 shortcut routed through `PDFView.set_mode("browse")`.
- Added live rectangle preview during drag.
- Kept rectangle drawing pinned to the page where the drag started.
- Converted final rectangle geometry through `_scene_rect_to_doc_rect()` instead of stale `self.scale`.
- Cleared rectangle preview state on release and mode changes.
- Hardened cancellation so `drawing_start` is cleared and non-left mouse buttons do not start or finalize rectangle drawing.

Verification:

- `pytest -q test_scripts/test_interaction_modes.py test_scripts/test_browse_selection_gui_regressions.py`
- Result after review fix: `12 passed`.

Review status:

- Subagent review found stale rectangle state after cancel/mode switch and non-left-button drawing.
- Both findings were fixed and covered by regression tests.

## Phase 2: Page Controls

Commits:

- `a38abe5 feat(ui): add scoped page controls`
- `5850da0 fix(model): skip no-op page rotations`
- `b53b7c1 fix(ui): align page scope labels`

Implemented:

- Added shared page-scope resolver for current, all, odd, even, and custom page ranges.
- Replaced delete-pages text entry with a scope menu.
- Replaced rotate-pages text/int dialogs with angle and scope menus.
- Added `360°` page rotation as a no-op in `PDFModel.rotate_pages()`.
- Replaced the page counter with a jumpable page number input that emits zero-based `sig_page_changed(page - 1)`.
- Kept thumbnail context menu single-page actions unchanged.

Verification:

- `pytest -q test_scripts/test_page_controls.py test_scripts/test_thumbnail_context_menu.py test_scripts/test_structural_indexing.py test_scripts/test_multi_tab_plan.py`
- Result after label follow-up: `86 passed, 1 skipped`.

Review status:

- Subagent review found only a low-risk UI label mismatch with the plan.
- Labels were aligned to `全部` and `自訂範圍`, then verified and committed.

## Phase 3: Exact Object Rotation

Commits:

- `a2dda6c feat(model): support exact textbox rotation`
- `4009688 feat(ui): use exact object rotation menus`
- `eaf50d5 test(ui): cover exact rotation menu action`

Implemented:

- Textbox rotation now honors `RotateObjectRequest.absolute_rotation`.
- Object rotation context menu now exposes exact choices: `90°`, `180°`, `270°`, `360°`.
- Menu-based object rotation emits `rotation_delta=0` with `absolute_rotation`.
- `360°` exact object rotation normalizes to `0.0`.
- No-drag rotate-handle clicks open the exact-angle menu instead of applying an additive 90-degree step.
- Drag/free rotation behavior remains unchanged and still emits drag-computed absolute rotation.

Verification:

- `pytest -q test_scripts/test_object_free_rotation_gui.py test_scripts/test_object_free_rotation.py test_scripts/test_object_manipulation_gui.py test_scripts/test_object_manipulation_model.py test_scripts/test_object_controller_flow.py`
- Result after coverage follow-up: `39 passed`.

Review status:

- Subagent review found no blocking issues and one coverage gap.
- Added a test proving the exact rotation menu action emits `absolute_rotation=270.0`.

## Phase 4: Insert Pages Password Support

Commits:

- `d5bbee0 feat(model): authenticate insert-page sources`
- `560c821 feat(ui): prompt for insert-source passwords`

Implemented:

- Extended insert-from-file signal and controller/model signatures to carry `password`.
- `_guard_foreign_doc()` now accepts an optional password and authenticates encrypted source PDFs.
- `PDFModel.insert_pages_from_file()` passes the password through to the guarded source open.
- Added `PDFModel.open_insert_source()` for page-count/password source resolution.
- Added `PDFController.resolve_insert_source_file()` using the existing password prompt/retry/cancel pattern from merge flows.
- Updated view insert flows to resolve the source before page-range input and emit the resolved password with the insert request.
- Kept unencrypted behavior unchanged with `password=None`.
- Preserved source size/page-count guards and post-merge page-count invariant checks.

Verification:

- `pytest -q test_scripts/test_thumbnail_context_menu.py test_scripts/test_security_pdf_resource_guards.py test_scripts/test_structural_indexing.py test_scripts/test_multi_tab_plan.py test_scripts/test_insert_pages_password.py`
- Result: `103 passed, 1 skipped`.

Review status:

- Subagent review was attempted after verification, but the subagent service returned a usage-limit error.
- A local review pass checked the same Phase 4 diff range and reran the full Phase 4 verification command above.
- No local Phase 4 defect was found.

## Phase 5: Deskew Size Warning and Build Readiness

Commits:

- `30572f2 feat(ui): warn about deskew size growth`
- `2e447fa docs: explain deskew size growth`

Implemented:

- Added a non-blocking `拉正頁面` tooltip warning that deskew can materially increase output file size.
- Recommended `另存為最佳化的副本` with `極致壓縮` when file size matters.
- Documented the root cause in `docs/PITFALLS.md`: `PDFModel.straighten_page()` rasterizes the page to a full-page RGB image, reinserts a bitmap, and replaces compact vector/text content with pixels.
- Added a concise user-facing deskew size note in `docs/FEATURES.md`.
- Added build-readiness notes in `docs/README.md` and `docs/README.zh-TW.md` instructing maintainers to refresh `.venv` dependencies before the next PyInstaller build with:
  `.venv\Scripts\python -m pip install -U "Pillow>=12.2.0" numpy`

Verification:

- `pytest -q test_scripts/test_theme_and_icons.py test_scripts/test_page_deskew.py test_scripts/test_page_deskew_scope.py test_scripts/test_security_pillow_floor.py test_scripts/test_startup_heavy_imports.py`
- Result: `67 passed`.

Review status:

- Subagent review found no blocking issues.
- Review confirmed the tooltip/docs/build-note changes and a clean `git diff --check` over the Phase 5 range.

## Completion Audit

Commits:

- `a4a8502 chore(gate): refresh gate anchor hash pin`
- `14d2757 fix(gate): validate no-jump negative artifacts`

Implemented:

- Refreshed stale no-jump completion-gate trust-chain hashes in `scripts/completion_gate.py` and `scripts/gate_anchor.py`.
- Documented the hash refresh rationale in `plans/2026-05-05-no-jump-editor-geometry-gate.md`.
- Fixed a verifier/schema mismatch in `scripts/verify_no_jump.py` so the three negative-control no-jump artifacts are validated against their actual evidence schema instead of the full geometry-matrix schema.
- Added focused regression coverage for that verifier behavior in `test_scripts/test_verify_no_jump_artifacts.py`.

Verification:

- Main workspace full suite: `pytest -q`
- Result: `1322 passed, 21 skipped, 5 warnings`.
- Clean worktree completion proof: `python scripts/completion_gate.py --skip-signoff`
- Result: exit code `0` in `.worktrees/completion-gate-14d2757`.

Notes:

- The non-skip completion gate path failed only on UX signoff because `OPENAI_API_KEY` / OpenAI signoff capability was unavailable in the environment.
- The same clean-worktree gate run passed the two no-jump pytest/artifact verification runs before signoff handling.

## Current State

Branch status after Phase 5 and completion audit: `main` contains the Phase 1-5 commits listed above plus the two completion-gate maintenance commits.

Final implementation head:

- `14d2757 fix(gate): validate no-jump negative artifacts`

Additional artifacts:

- Completion proof artifacts were generated in the clean completion worktree and then copied into ignored `test_artifacts/`.
- Stashed non-phase planning/reference files were preserved separately and can be restored or committed independently.
