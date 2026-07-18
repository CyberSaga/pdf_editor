# TODOS

## Acrobat-parity text commit engine — harness prep (plans/2026-07-14-acrobat-parity-text-commit-engine.md)

Before any engine code (Phase A onward), the environment/CI gaps that would let
the fidelity checks (byte-identical stream patching, render-diff) pass/fail
inconsistently by machine needed closing first. Scoped and landed one slice at
a time (not batched) per the milestone-1 lesson on PR size.

- [x] **PyMuPDF pinned to a single minor (`>=1.27,<1.28`), not a floor.** Was
  `>=1.23`, which let `.venv` (1.27.1) and a bare system-Python run (observed
  1.25.5) silently diverge in stream serialization / `extract_font` behavior —
  exactly the signal a byte-identical fidelity check needs to trust.
  `test_scripts/test_environment_pins.py` fails loudly on skew. `docs/PITFALLS.md`
  "PyMuPDF version skew masks runtime-only bugs".
- [x] **Device-identity pre-commit guard.** `scripts/hooks/pre_commit_device_guard.py`
  scans added diff lines for local machine paths/hostnames/MAC addresses (the
  class of leak from the 2026-07-15 history-rewrite incident); installed via
  `scripts/hooks/install_git_hooks.py` (opt-in per clone) and enforced
  unconditionally by the new `device-guard` CI job. Relevant because
  Phase A's telemetry (§4.7) will start dumping stream hashes / font metadata /
  local paths on failure — this closes the leak path before that lands.
- [x] **Synthetic fidelity corpus generator** (`scripts/build_fidelity_corpus.py`) —
  generates 10 synthetic PDFs on the fly (no checked-in binaries; `*.pdf` stays
  gitignored) covering each decision-gate case: base-14 unembedded Type1,
  embedded CIDFont/Type0 (extractable + reloadable), CJK Identity-H, TJ
  kerning arrays, rotated text (G4), Form XObject (G2), `/Differences`
  encoding (F3), Type3 font (F1), multi-style runs (T0a), neighbor proximity.
  Test: `test_scripts/test_build_fidelity_corpus.py` (19 structural assertions).
  No longer blocks Phase A.
- [ ] **ε calibration for V1d render-diff** (open question 4 in the plan) —
  measure repeated-render pixel noise on both the maintainer's machine and the
  CI runner before hard-coding a tolerance.
- [ ] **Rebind the Stop-hook completion gate** (`scripts/check_completion_proof_hook.py`)
  from its dormant `GOAL_FILE` (`plans/2026-05-05-no-jump-editor-geometry-gate.md`,
  never committed → gate is a permanent no-op) to a new gate plan for this
  engine, so Phase A-D PRs get the independent re-verification the hook was
  built for instead of relying on manual review alone.
- [ ] **`commit-fidelity` CI job** running `verify_commit_fidelity.py` against
  the synthetic corpus (Windows leg blocking, matching the existing
  `test-functional` split) — lands with Phase B.
- [ ] **Perf-budget tests** for `engine.apply` / `render_edit_preview` (the
  300ms slow-edit budget and per-keystroke scratch-doc cost from open question
  6) — target the M3.6 failure class ("So slow" / "Freeze on each operation" /
  500-700MB resident) with an automated gate instead of relying on manual QA
  to catch it a second time.
- [ ] Spikes S2 (TextWriter transplant vs append — 1b is the theoretically
  correct default for z-order but is unproven on resource-dict-collision /
  graphics-state-bleed risk; decide from the render-diff spike, not from
  argument), S3 (Identity-H stream patch), S4 (mapping-ambiguity audit) — each
  its own PR, per plan §4.10.

## Deferred from prior campaigns

### R5-01 / Codex F6 (from post-campaign repair, 2026-06-21) — Resolved in Milestone 2

- [x] **R5-01 fileless print path — Resolved (PR-17, 2026-07-10).** Both plaintext temps are gone.
  `capture_print_snapshot_bytes` always returns `PDF_ENCRYPT_NONE` bytes, so *both* temps held a fully
  decrypted copy of the document at rest.
  - `work_dir/input.pdf` (coordinator): the document now rides the helper subprocess's **stdin**, written
    in 1 MiB chunks with `bytesWritten` flow control. `job.json` carries options + watermarks only.
  - the dispatcher's `NamedTemporaryFile`: `PrintDispatcher.print_pdf_bytes` now calls the new
    `PrinterDriver.print_pdf_from_bytes`. `WindowsPrinterDriver` overrides it, so on Windows **no document
    bytes touch disk at any point**. `PDFRenderer`/`raster_print_pdf` accept `str | bytes`.
  - Bonus: because the piped bytes are already plaintext, the helper has nothing to authenticate, so the
    R5.1 re-encryption and the `PDF_EDITOR_PRINT_PASSWORD` **environment variable are gone from the
    production path** (a process env block is readable by same-user processes; an anonymous pipe is not).
  - Duplicate copies: 5 stops (bytes → input.pdf → helper read → temp → renderer read) reduced to 2.
  - **Residual, accepted:** the Linux/macOS CUPS/lp *direct-PDF* route still materialises one temp, because
    `conn.printFile` / `lp` hand the path to a filter chain that must parse and rasterise it. It cannot be
    encrypted (the consumer needs plaintext), so it is instead driver-scoped, `0600`, and unlinked in a
    `finally`. Windows never reaches that code. Documented in `docs/PITFALLS.md`.
  - Design: `plans/r5-01-fileless-print.md` §11. Tests: `test_scripts/test_print_fileless.py` (+ rewritten
    `test_print_encrypted_input.py`, `test_print_dispatcher_real_sink.py`,
    `test_security_dispatcher_temp_cleanup.py`).
- [x] **Codex F6 — in-flight worker decrypted-bytes lifetime — Resolved (PR-18, 2026-07-10), Exit A.**
  The old note said "revisit only if a worker can be made to clear its payload race-free on cancel." It can,
  and the mechanism needs no synchronisation at all: **the worker clears its own `_doc_bytes` on its own
  thread.** `request_cancel()` (GUI thread) only flips a bool; nothing but the worker thread ever writes the
  payload, so there is no window to lose and the non-blocking cancel is preserved.
  - `_SearchWorker` drops the reference immediately after `fitz.open("pdf", ...)` — PyMuPDF holds its own
    reference to the buffer, so the `Document` stays usable (verified: refcount 3 after open).
  - `_OcrWorker` needs the bytes on every iteration (`ocr_pages(doc=...)`), so it clears in `run()`'s
    `finally`. That still bounds the lifetime to `run()` instead of to the QObject's lifetime, which
    extends past the loop until Qt processes the pending `deleteLater()` — the actual F6 exposure.
  - Fixed en route: `_SearchWorker.run()` called `doc.close()` unconditionally in a `finally`, crashing with
    `AttributeError` on the empty-`doc_bytes` fallback path.
  - **Residual, accepted:** between `request_cancel()` and the worker's next checkpoint, the in-flight page
    still holds the bytes, and the live document is decrypted in RAM regardless. Removing that needs a
    blocking join, which would regress the intentional non-blocking cancel.
  - Tests: `test_scripts/test_worker_doc_bytes_lifetime.py`.

### Audit remediation deferrals (2026-06-10)

- [~] **R4.1 — Overlay render cache: EVALUATED → DEFERRED.** Disproportionate risk for a watermark-only conditional gain. Full rationale: `plans/refactor-R4-performance-deferrals.md`. Revisit only if watermarked scroll-after-edit latency becomes a measured bottleneck.
- [x] **MVC routing of merge-dialog page counting.** The view-layer `fitz.open()` calls in `pdf_view.py` (merge dialog page-count probe) should route through a controller/model utility to respect layer boundaries. **Resolved (R2.3, predates PR-9):** `PDFController.resolve_insert_source_file()` is the routed path; `view/pdf_view.py` has zero `fitz.open(...)` calls (confirmed by `test_scripts/test_layer_boundaries.py`'s exact-count allowlist, which only permits `view/text_editing.py`'s scratch doc).

## Resolved -- Completion-gate trust chain (2026-07-03, Codex adversarial-review finding)

Phase 1 of the setup-optimization campaign (2026-07-02) unregistered the `Stop` hook and, separately, edited
`check_completion_proof_hook.py`'s header comment without cascading the SHA-256 update through
`gate_anchor.py` → `completion_gate.py`'s `_PINNED_HASHES`. Net effect: `scripts/completion_gate.py` could no
longer pass its own Step 0b (missing Stop-hook registration) or Step 0c (stale pinned hash) invariant checks —
a permanently broken trust chain, caught by `codex:adversarial-review --base pre-optimization-2026-07-02`.

Fixed by re-registering the Stop hook in `.claude/settings.json` (alongside the Phase-1 `PostToolUse` ruff
hook) and re-cascading the hash chain (`check_completion_proof_hook.py` → `gate_anchor.py._HOOK_HASH` →
`completion_gate.py._PINNED_HASHES['scripts/gate_anchor.py']`). Verified: the hook still exits 0 in ~90ms
(its `GOAL_FILE`, `plans/2026-05-05-no-jump-editor-geometry-gate.md`, has never been committed to git, so
Layer 1's goal-mode guard short-circuits), Steps 0/0a/0b/0c of `completion_gate.py` now pass, and
`test_scripts/test_completion_proof_hook.py` is green (18 passed, 1 skipped).

- [x] **Open follow-up — Resolved (PR-14, 2026-07-10) as documented-here-instead.** `gate_anchor.py`'s
  maintenance doc (step 5, `scripts/gate_anchor.py:26`) says "document the change in
  `plans/2026-05-05-no-jump-editor-geometry-gate.md`" — that file has never existed in git (a pre-existing
  gap predating this campaign, not introduced by it).

  **This TODOS section is that file's stand-in.** Hash-cascade changes are recorded here.

  Two fixes were considered and rejected:
  - *Edit `gate_anchor.py:26` to point at this file.* Rejected: any content change to `gate_anchor.py`
    changes its SHA-256, which is pinned in `completion_gate.py._PINNED_HASHES`, forcing a hash re-cascade
    for a comment edit. Cost/benefit is upside-down.
  - *Create the missing `plans/2026-05-05-no-jump-editor-geometry-gate.md`.* **Rejected — actively unsafe.**
    `check_completion_proof_hook.py:120-122` deactivates the Stop-hook gate only while `GOAL_FILE` neither
    exists on disk nor is tracked in git. Committing that plan file would flip Layer 1's goal-mode guard on
    and start enforcing Layer 2 (proof/marker/signoff artifacts in `test_artifacts/`) on every Stop event.
    The dangling pointer is inert; the file it points at is a live tripwire.

  If a future no-jump-style campaign revives that plan file, it must (a) reconcile this history into it and
  (b) expect the Stop gate to arm itself the moment the file is committed.

## Resolved -- Layer boundary violations (S4 import-linter, added 2026-07-02)

`lint-imports` (`.github/workflows/ci.yml` → `layer-boundaries`) now runs all four contracts as a single
**blocking** step: `model-no-controller-view`, `model-no-qt`, `utils-no-controller-view-model` (PR-8), and
`view-no-model` (PR-9). No known violations remain.

- [x] **`utils/preferences.py` imports `model.tools.ocr_types`.** Utils importing Model inverts the intended
  bottom-of-stack position of `utils/`. Either move `ocr_types` to `utils/` (if it's really a shared type) or move
  the OCR preference logic that needs it into `controller/`/`model/`. **Resolved (PR-8):** moved to
  `utils/ocr_types.py` with a re-export shim left at `model/tools/ocr_types.py`.
- [x] **`utils/helpers.py` imports `PySide6.QtWidgets.QMessageBox`.** Utils showing a message box directly bypasses
  the View layer; callers should raise/return and let View show the dialog. **Resolved (PR-8):** moved
  `show_error` to `view/message_boxes.py`; all callers updated.
- [x] **View importing Model directly** (`view/dialogs/audit.py`, `view/dialogs/ocr.py`, `view/dialogs/optimize.py`,
  `view/object_selection.py`, `view/pdf_view.py`, `view/text_editing.py`). **Resolved (PR-9, 2026-07-04):** the two
  real boundary crossings were routed through controller injection — `view/dialogs/ocr.py::OcrDialog` takes a
  required `device_available` callable (view forwards to `PDFController.is_device_available`, new facade over
  `model.tools.ocr_tool.is_device_available`), and `view/dialogs/optimize.py::OptimizePdfDialog` takes a required
  `preset_options` callable (`PDFController.start_optimize_pdf_copy()` passes `PDFModel.preset_optimize_options`).
  The remaining DTO/type imports (`model.object_requests`, `model.edit_requests`, `model.pdf_optimizer`) have no
  mutation surface and are permitted via `ignore_imports` on the `view-no-model` contract in `pyproject.toml`,
  each with a comment justifying the permit. `view-no-model` is now blocking.

## Open -- Security dependency hygiene (from F2/F9 patch work; updated 2026-06-05)

See `docs/history/reports/0607-implementation-notes.md` for the full F1-F9 patch log.

### BLOCKED — transformers CVE (investigated 2026-06-05)

`surya-ocr` transitively pulls `transformers 4.57.6` (two CVEs: CVE-2026-1839 fixed only in 5.x, PYSEC-2025-217 no fix). No surya release requires or is validated against transformers 5.x. Do NOT bump. See TODOS-archive for full investigation table.

### Pillow floor vs. surya-ocr

Reconciled via file split: `surya-ocr` + `torch` in `ocr-requirements.txt`; core image features floor at `Pillow>=12.2.0` in `optional-requirements.txt`. Locked by `test_security_pillow_floor.py` and `test_security_ocr_requirements.py`.

### Deployment env remediation — Resolved (PR-13, 2026-07-10)

- [x] **Upgrade the build-env (`.venv`) Pillow to >=12.2.0.** Done. `.venv` measures **Pillow 12.2.0**
  (the 5 image-parser CVEs are remediated); `constraints-ci.txt` pins the same version, so CI and the
  build env agree by policy. The upgrade landed as a side effect of M1 PR-1's constraints capture.
- [x] **Refresh build tooling** in the `.venv`. Done: **pip 26.1.2**, **setuptools 82.0.1**, **wheel 0.47.0**
  (were pip 21.2.3 / setuptools 57.4.0). `constraints-ci.txt` pins setuptools/wheel.
- [~] **PyInstaller rebuild: DEFERRED to the distribution track.** There is no `.spec` file anywhere in
  the repo and no build recipe to rebuild from (`build/` is an untracked distutils artifact, not a
  PyInstaller output). PyInstaller 6.19.0 + `pyinstaller-hooks-contrib` are installed in `.venv`, but
  authoring the spec is distribution work the roadmap already parks under "Later candidates"
  (packaged-EXE embedded icon + PyInstaller spec). The CVE remediation above does not depend on it:
  a future build picks up the patched `.venv` automatically.

### Remaining open items

- [ ] **Revisit the OCR stack when surya-ocr relaxes its pins.** When a surya release ships `pillow>=12.2` support and a transformers floor in the 5.x line, merge `ocr-requirements.txt` back and drop the residual-risk note.
- [ ] **F9 bundle distribution** — ship a vetted weights bundle and populate `WEIGHTS_MANIFEST` with its published SHA256 digests so `PDF_EDITOR_OCR_WEIGHTS_DIR` works out of the box. See `docs/ocr-weights-verification.md`.

## CI coverage baseline (PR-11, 2026-07-05) -- gate enforced in PR-12

- [x] **Evidence-based coverage gate (PR-12).** CI coverage baseline (PR-11, 2026-07-05): 78%
  windows-latest functional leg, stable across 3 consecutive runs (local: 79%).
  CI detail: 15385 stmts / 3354 missed, 1553 passed / 33 skipped / 15 deselected / 0 failed
  (run 28712396725). Local detail: 15385 stmts / 3292 missed.
  Measured by the now-blocking windows `test-functional` leg via
  `--cov --cov-report=term --cov-report=xml --cov-fail-under=0` (the explicit 0 kept the
  number advisory pending this PR). The CI figure is lower than local because fixture-dependent
  (`needs_fixtures`) tests don't run there.
  PR-12 removes the `--cov-fail-under=0` override from the windows leg's cov args, so
  `pyproject.toml`'s existing `[tool.coverage.report] fail_under = 75` now governs on CI —
  one number, one source of truth, three points of headroom against the CI-measured 78%
  baseline. (Deviation from the original plan note below this line, which proposed
  CI-measured-minus-2: 75 was already the configured threshold and already has real
  headroom, so it was left as-is rather than raised, per PR-12 design decision.)

## CI advisory findings (PR-10, 2026-07-04)

- [ ] **ubuntu-latest `test-functional` leg segfaults (Bus error, intermittent).** Crashes inside
  `test_scripts/test_page_deskew_scope.py::test_controller_straightens_batch_as_single_undo` at a
  `qapp.processEvents()` call (~49-58% through the suite), native Qt/PyMuPDF/PIL interaction under
  offscreen rendering; doesn't reproduce on every run (2 of 4 sampled runs completed cleanly). Stays
  advisory (`continue-on-error: true`) until root-caused. See GitHub issue
  https://github.com/CyberSaga/pdf_editor/issues/19 for full evidence and next steps (bisect via
  `--deselect`, junit artifact comparison across runs, core dump analysis).

## Future Object Follow-Ups

- Any remaining object-manipulation polish that needs its own child plan.
- [x] **Delete app-image: drop `PDF_REDACT_IMAGE_REMOVE`** — **Resolved (PR-16, 2026-07-10).**
  The image branch of `_delete_object_impl` (`model/pdf_object_ops.py`, not `pdf_model.py` — the code
  moved) now resolves the marker to its `NativeImageInvocation` via `_resolve_marker_image_invocation`
  and strips only that placement via `_remove_native_image_invocation`, matching the move/rotate
  conversion from `c099b28`. An unresolvable placement fails safe (delete returns `False`, a no-op)
  rather than falling back to redaction.

  The defect was **larger than this item described**. `apply_redactions` is geometric, so deleting an
  app-image also destroyed *text* and *line art* under its rect, not only overlapping images (measured:
  `"UNDER THE IMAGE"` → `"AGE"`). Design + measurements:
  `plans/b1-delete-app-image-invocation-removal.md`; generalized gotcha in `docs/PITFALLS.md`.

  Regressions added to `test_scripts/test_image_objects_model.py` (all synthesized in-test, so the
  blocking Windows CI leg runs them): overlapping-neighbour survival, underlying-text preservation,
  underlying-vector-art preservation, shared-xref neighbour survival, fail-safe on ambiguous
  resolution, undo restores both, save/reopen persistence. `test_pdf_object_ops_transactional.py`'s
  two redaction-injection tests were retargeted at the new mutation call and strengthened to assert
  `apply_redactions` is never invoked on this path.

- [ ] **Content-stream tokenizer has no inline-image (`BI … ID … EI`) mode.**
  `model/pdf_content_ops.py`'s tokenizer lexes inline-image *binary data* as operators: a `0x25` (`%`) byte
  starts comment-skipping to end-of-line, `(`/`<` trigger delimited consumption that can run past `EI`, and
  stray bytes can lex as `q`/`Q`/`Do`, perturbing the q/Q bounds used by `_remove_native_image_invocation`.
  Any whole-stream re-serialize (`serialize_tokens` joins with `\n`) then mangles the image bytes.

  **Pre-existing, not introduced by PR-16:** `_rewrite_native_image_matrix` (move/rotate, `c099b28`) and the
  `native_image` delete branch already re-serialize the same streams. The app-image path cannot reach it
  directly — `insert_image` appends a fresh `q cm /name Do Q` stream per insert. The reachability argument
  runs through `_redact_and_restore_textbox_region` consolidating page contents first, and it is unverified
  whether mupdf's redaction filter re-emits inline images as `BI…EI` at all.

  Fix direction: treat `ID … EI` as one opaque byte token, or fail-safe (`return False` before
  `update_stream`) when a target stream contains `BI`/`ID`. Needs its own red-light suite covering move,
  rotate, and both delete branches. Raised by adversarial review; see
  `plans/b1-delete-app-image-invocation-removal.md` §10.3.

- [x] **B1 codex adversarial review completed (2026-07-12).** The resumed Codex pass reproduced and fixed
  three additional defects: a stale shared-xref marker deleting the surviving placement; an unrelated
  page's same-named XObject preventing inherited-resource pruning and surviving `garbage=4`; and the
  fileless print runner retaining plaintext and never finishing after `QProcess.FailedToStart`.
  Regression coverage lives in `test_image_objects_model.py` and `test_print_subprocess_runner.py`.

- [ ] **Batch delete gives no feedback when it rolls back.** `delete_objects_atomic` is all-or-nothing by
  design, so one unresolvable app-image in a multi-select cancels the whole delete. The view has already
  cleared the selection handles by then, so the user sees the handles vanish and nothing happen — no toast,
  no undo entry. Add a message on the `False` path of `PDFController.delete_object` (both the batch and
  single branches); `_show_edit_result_feedback` is the precedent. UX only; correctness is fine.

- [ ] **A no-op delete used to leave `model.doc` renamed.** Fixed for delete (rollback is now conditional on
  `edit_count` changing), but `_restore_doc_from_snapshot` still yields a doc with an empty `doc.name`,
  which silently degrades the next save from incremental to full (`model/pdf_model.py:3263-3278`). Any
  other caller that rolls back a genuine mutation inherits that. Worth a look when touching the save path.

## Future View Follow-Ups

- [ ] Tune middle-click auto-pan speed/feel after manual validation on long multi-page PDFs.
- [ ] Consider drawing an origin marker for auto-pan so users can see the deadzone anchor more clearly.

## Notes on `objects mode`

- Treat `objects mode` as a separate interaction mode from browse mode and text-edit mode.
- Browse mode keeps its text-selection behavior and should not accidentally start moving objects.
- Objects mode should focus on selecting/manipulating objects:
  - Supported now: rectangles, app-inserted images, and native PDF images.
  - Textboxes stay in text-edit mode.
- Text edit mode focuses on textboxes:
  - Supported: move/rotate/delete/resize/multi-select textboxes, plus editing words.
- The same object identity layer stays shared across the object and text-edit paths.

## M3 — Tranche 3.1 Quick Wins (completed 2026-07-15)

- [x] Scale and center thumbnail rasters across narrow and wide sidebars.
- [x] Re-render every thumbnail after page-count changes; keep bounded invalidation for unchanged counts.
- [x] Make repeated Enter advance completed search results without restarting the search.
- [x] Add Ctrl+W current-tab close while preserving an empty application window after the final tab.
- [x] Make the font-size combo editable with one-decimal commit validation and last-valid restoration.
- Runtime evidence is retained separately from the repository.
- Completion gates: `1673 passed, 21 skipped`; full Ruff clean; mypy clean across 35 model/utils files.

## M3 — Tranche 3.2 Platform and Print (implementation complete 2026-07-15)

- [x] Centre raster output on the physical paper rectangle rather than a potentially asymmetric printable rectangle.
- [x] Retain the touched-precedence print contract through dialog/options/helper/Qt bridge tests; no code defect reproduced in the cold-start diagnostic path.
- [x] Grant the already-running Windows instance foreground rights before forwarding a double-click file-open request.
- [x] Log a nonfatal warning when the configured runtime application icon is unavailable.
- [x] Manual verification round 1 (2026-07-17) found two defects; both fixed same day:
  - Print dialog forgot in-app settings between prints in the same process. `PrintCoordinator` now captures accepted-dialog settings (`capture_user_settings()`) and replays them via `previous_settings=`; restore runs **after** `_wire_signals()` so restored hardware fields are touch-marked and beat driver preferences in `_build_effective_options()` (see PITFALLS: "programmatic combo restore must run AFTER signal wiring"). Cancel persists nothing.
  - PgUp/PgDn dead after foreground handoff into a new/detached window (F2/F3 worked — they're window-level QActions; paging needs `graphics_view` focus). `handle_forwarded_cli` and `create_detached_window` now set `graphics_view.setFocus(ActiveWindowFocusReason)` after raising, *after* the `open_pdf` loop so loading can't steal it.
  - Tests: `test_m3_print_settings_persistence.py` (10), `test_m3_forwarded_cli_focus.py` (2).
- [ ] Manual re-verify (blocked items now unblocked): second-print settings retention, cancel-does-not-persist, PgUp/PgDn in a fresh detached window.
- [ ] Capture manual Windows evidence for cold-first-job print overrides and the current source-vs-packaged icon scope.

## M3 — Tranche 3.3 Page Structure (complete)

- [x] Add strict, 1-based custom range validation to delete and rotate dialogs; invalid, reversed, blank, and out-of-range values do not emit mutations.
- [x] Delete all pages transactionally into a single model-side blank placeholder, replacing it when real imported pages arrive and preserving the state over undo/redo.
- [x] Implement thumbnail drag/drop page reordering with snapshot undo/redo, interval-limited thumbnail refresh, stale-index maintenance, and a compact portrait row cap that keeps three drop targets visible.
- [x] Make native thumbnail drags reach the viewport, reorder rows without Qt post-drag deletion, and auto-scroll while hovering within 48 px of the top/bottom edge. Real-GUI acceptance used `test_files/test-colored-background.pdf`.

## M3 — Tranche 3.4 Shell and Tab UX (complete)

- [x] Support a real 720×520 outer shell; below 900 px, collapse both sidebars while preserving at least a 360×300 central viewport, then restore prior sidebar visibility at normal widths.
- [x] Replace style-dependent native tab close glyphs with explicit themed 20×20 `×` controls that delegate to the existing unsaved-tab close pipeline.
- [x] Add saved-tab `開啟檔案所在位置` context action through a session-id View signal, controller metadata resolution, and argument-list platform launcher.
- [x] Route PgUp/PgDn/Home/End from the browse canvas to bounded page targets without stealing keys from text inputs or inline editors.
- [x] Persist a canonical, deduplicated ten-entry recent-file list after successful opens from every existing entry path; show missing entries disabled in the Open menu.

## M3 — Tranche 3.5 Editing Tools (complete)

- [x] Add top/right/bottom/left midpoint resize handles; edge drags change one dimension only, preserve the opposite edge, enforce minimum size, and leave Shift aspect locking corner-only.
- [x] Replace the rectangle fill confirmation with inspector-owned stroke color, optional independent fill color, validated 0.1–20 pt border width, matching preview, persisted object payload, and snapshot undo/redo.
- [x] Add underline and strikeout modes through View signals, controller snapshots, and ToolManager-owned PyMuPDF annotation creation.
- [x] Combine underline/strikeout into a single "標記線" (`markup_line`) mode with a style toggle, replacing the two separate toolbar buttons; each style remembers its own color/opacity independently.
- [ ] `markup_line` line width control (deferred): PyMuPDF's Underline/StrikeOut annotation subtypes reject `set_border()` outright — there is no width to adjust. A real width control needs a design decision on switching to a generic Line annotation positioned at the underline/strikeout Y-offset (gains width control, loses semantic Underline/StrikeOut recognition in other PDF readers).
- [x] Add a title/author/subject/keywords metadata editor with Qt-free model wrappers, preservation of unedited metadata, dirty-tab refresh, save/reopen persistence, and snapshot undo/redo.

## M3 — Performance Baseline (captured 2026-07-15, pre-tranche-3.0)

Full commands, method, and values: `plans/archive/2026-07-16-m3-render-offload.md`.

| Metric | Run 1 | Run 2 |
|---|---:|---:|
| PDFModel import | 0.245 s | — |
| PDFModel instantiation | 0.001 s | — |
| reference fixture| 861.3 ms | 923.7 ms |
| reference fixture| 18.7 ms | 18.4 ms |
| complex fixture| 1252.6 ms | 1044.1 ms |
| complex fixture| 56.8 ms | 52.4 ms |
| complex fixture| 81991.4 ms | 107464.7 ms |

- [x] Fix `benchmark_ui_open_render.py` for the profile-scoped quality map.
- [x] Capture the pre-M3 baseline and seed `plans/archive/2026-07-16-m3-render-offload.md`.
- [x] Re-run immediately before tranche 3.6 and publish before/after evidence.

## M3 — Tranche 3.6 Render Offload (render slice implemented 2026-07-16)

- [x] Profile the complex fixture: XREF repair was absent; snapshot capture was ~1.1 s; page-25 display-list plus raster was ~0.45 s.
- [x] Identify the actual 78–80 s defect as GUI-callback prefetch blocking plus full-document thumbnail contention, not the requested high-quality page raster.
- [x] Add a one-worker/latest-pending `PageRenderCoordinator` with immutable snapshot bytes, QImage-only results, complete token/session/generation/revision/page/scale/profile/DPR rejection, and bounded cancellation.
- [x] Keep the immediate low first paint synchronous; offload high and non-immediate low/prefetch rendering; pause and resume thumbnails around foreground candidates.
- [x] Reduce complex midpoint jump readiness from 78.1/80.1 s to 180.5/167.5 ms; full commands and raw values are in `plans/archive/2026-07-16-m3-render-offload.md`.
- [x] Center mixed-width continuous pages through shared per-page x/y coordinate helpers and add browse-mode run-local numeric-token double-click selection.
- [x] M3.6 completion gates: `1788 passed, 21 skipped`; full Ruff clean; mypy clean across 36 model/utils files.
- Manual verification round 2 (2026-07-17) found two defect clusters; investigation in `plans/2026-07-17-m3-manual-round2-defects.md`:
  - [x] Annotation placement offset on rotated pages (下右偏移) — PyMuPDF interprets `add_*_annot` geometry (and stores `/Rect`) in **unrotated** page space while the app deals in displayed coords; HVAC fixture pages are rotation=270. Fixed at the model-boundary chokepoint in `annotation_tool.py`: derotation on write (corner-mapped quads for highlight/underline/strikeout, anchor-point for note `set_rect`), `rotation_matrix` on read in `get_all_annotations`. `add_redact_annot` verified rotation-safe (text editing unaffected). Tests: `test_annotation_rotation.py` (24, pixel-detection oracle — `annot.rect` readback lies).
  - [ ] Manual re-verify: rectangle/highlight/underline/strikeout placement, note-marker position, and jump-to-note on the rotated HVAC fixture pages.
  - [ ] Render responsiveness/memory cluster (zoom slow, freeze on high/prefetch/tab switch/close, 500–700 MB): root-caused — PyMuPDF holds the GIL during rendering (measured 4.5 s main-thread stalls while a "background" QThread rastered), so the M3.6 QThread offload cannot free the UI on dense fixtures; plus 220 ms+ synchronous low render per zoom step and 52 s/+155 MB full-document thumbnail sweeps. Fix needs its own plan: out-of-process rasterization (pattern: `src/printing/subprocess_runner.py`), rescale-don't-re-raster on wheel zoom, on-demand thumbnails.
- [x] UNC recent-files crash (found and fixed 2026-07-17): Python 3.10 `Path.resolve(strict=False)` raises WinError 53 on unreachable UNC paths; a stale network-share entry crashed `activate()` → `_refresh_recent_files()` and a second path via `open_pdf()` → `find_session_by_path()`. Fixed at chokepoints catching only `OSError` with a string-canonical fallback: `_safe_resolve_path` (preferences), `PDFModel._canonicalize_path`, per-entry `available=False` defense in `_refresh_recent_files`; `single_instance` sender/receiver made explicitly FAIL-CLOSED (unresolvable token rejects the whole hand-off/message — never skipped). Tests: `test_recent_files_unc_robustness.py` (6, red-on-revert verified); previously-failing suites went 8 → 0. See PITFALLS entry.
- [ ] Follow-up (audited 2026-07-17, lower severity, no failing test yet): inline `Path(...).resolve()` sites without OSError guards — `pdf_model.py` `open_insert_source` (~1700), `open_merge_source` (~1756), `_atomic_full_save` (~3078), `_full_save_to_path` (~3479, resolves `doc.name` — raises mid-save if the source share died), `save_as`/`save_session_as` (~3603/~409), `pdf_controller.py` optimize dedupe (~1485), `src/printing/dispatcher.py` output path (~101). Route through a shared safe-resolve helper when touched.
- [ ] Test-isolation gap: suites construct controllers that read the REAL user preference store (`UserPreferences()` default QSettings), so machine-local state can poison unrelated tests — point tests at an isolated store fixture.

## M3 — Tranche 3.7 Notes and Bookmarks (implementation complete 2026-07-16)

- [x] Create compact standard PDF Text notes; list legacy FreeText read-only; snapshot-back content update, marker move, and delete.
- [x] Add a main-window-owned frameless `FloatingNote`; popup drag remains UI-only while marker drag persists through a View signal and controller snapshot.
- [x] Add validated Qt-free TOC get/set APIs and remap bookmark targets across insert, delete/delete-all placeholder, and final-index page moves.
- [x] Add nested bookmark tree navigation plus add/rename/delete/sibling-reorder requests through the controller-owned TOC snapshot path.
- [x] M3.7 completion gates: `1800 passed, 21 skipped`; full Ruff clean; mypy clean across 36 model/utils files.
- Manual verification (`docs/M3-Manual-Verification-Checklist-0716.md`) found bookmark rename/page-edit undiscoverable and the note drag bar not visibly grabbable — both fixed 2026-07-17:
  - [x] Rename a bookmark — was implemented (`Qt.ItemIsEditable` + `_on_toc_item_changed`) but only reachable via F2 (`EditKeyPressed`), with double-click already claimed by navigation; added a right-click context menu on `bookmark_tree` ("重新命名" → `editItem(item, 0)`). Tests: `test_scripts/test_bookmark_rename_ux.py`.
  - [x] Change its page number — same undiscoverability; added "設定頁碼" → `editItem(item, 1)` to the same context menu, reusing existing validation/clamping in `_on_toc_item_changed` unchanged. Tests: `test_scripts/test_bookmark_rename_ux.py`.
  - [x] Note popup drag handle polish (希望可以抓到註解的那個可點擊區域是可見的) — `_NoteDragBar` (`view/floating_note.py`) now has a visible background/border and an open-hand cursor. Tests: `test_scripts/test_floating_notes.py::test_note_drag_bar_is_visually_identifiable_as_a_grab_handle`.
- Manual verification (round 2) found the note popup was not session-scoped — fixed 2026-07-18:
  - [x] Note popup survives its own delete — `FloatingNote` delete button only emitted `delete_requested`, never `.close()`d, leaving it editing a deleted xref; now `_emit_delete` closes it (relies on `WA_DeleteOnClose`). Tests: `test_scripts/test_floating_notes.py::test_delete_button_closes_the_popup`.
  - [x] Note popup survives tab-close / tab-switch and mutates the wrong session — `_floating_note` was an un-scoped singleton, so its Save/Delete/drag (routed via the controller to `_record_annotation_mutation`) hit whatever `get_active_session_id()` currently pointed at, not the popup's origin session — a silent cross-document corruption path. Now the view records `_floating_note_sid` on open and `_dismiss_floating_note_if_orphaned()` (called from `set_document_tabs`, the funnel for every switch/close/reset) closes it the instant its owning session stops being active. Tests: `test_closing_the_popups_owning_tab_dismisses_the_popup`, `test_switching_away_from_owning_tab_severs_the_cross_session_mutation_path`.
  - [x] Bookmark panel doesn't clear when the last tab closes (有保留。但關閉分頁後書籤不會消失，要關閉視窗才會) — `_reset_empty_ui()` cleared the annotation and watermark lists but had no `populate_toc([])`, so stale bookmark rows from the last-closed document lingered until the whole window closed. Added the missing `self.view.populate_toc([])` call alongside the existing list-clearing pattern. Tests: `test_scripts/test_bookmarks_toc.py::test_reset_empty_ui_clears_bookmark_panel`.
  - [x] Bookmark deselected on every up/down move (每按一次上移或下移就會取消聚焦該書籤，還要重新點一次太麻煩) — `_move_selected_bookmark` set the current item then emitted `sig_toc_changed`, whose synchronous round-trip (`update_toc` → `load_toc` → `populate_toc`) does a full `tree.clear()`+rebuild, destroying the just-set selection before the event loop ran. The view now stashes the moved entry's flat DFS index (`_pending_toc_selection`) and re-selects/focuses the matching rebuilt item at the end of `populate_toc` (`_restore_pending_toc_selection`); scoped to the move path only. Tests: `test_scripts/test_bookmarks_toc.py::test_move_bookmark_up_preserves_selection_after_rebuild`, `test_move_bookmark_down_preserves_selection_after_rebuild`, `test_move_child_bookmark_preserves_selection_after_rebuild`, `test_move_bookmark_boundary_noop_leaves_selection_intact`.

## M3 — Tranche 3.8 Tab Detachment (implementation complete 2026-07-16)

- [x] Add true thresholded tab drag-out through `DetachableTabBar`; clicks/short/in-bar drags do not detach.
- [x] Transfer repr-safe in-memory snapshot/path/dirty/page/zoom/profile DTOs into an independent MVC triple composed only by `main.py`.
- [x] Remove the source session only after destination readiness; failed handoff leaves the source intact.
- [x] Preserve dirty state through a session-local flag and normal save; intentionally start the detached undo stack empty.
- [x] Final automated gates: `1804 passed, 21 skipped`; full Ruff clean; mypy clean across 36 model/utils files.
- [ ] Manual acceptance remains: drag saved and dirty tabs into secondary windows, save/reopen, and close both windows independently.

## M3 candidate — Acrobat-parity text commit engine (design complete 2026-07-14)

Design: `plans/2026-07-14-acrobat-parity-text-commit-engine.md` (synthesis of two
independent proposals + corpus font audit). Addresses "font changes / layout jumps
after edit" — structural ceiling of redact+reinsert, not a regression.

- [x] Diagnosis + root cause (font substitution in `_resolve_font_for_push`; htmlbox
      re-layout with break-all CSS; push-down moving neighbors; verify checks text only)
- [x] Spike S1 — font round-trip audit over corpus (embedded TT/Type0: 100% extract+load)
- [ ] Spike S2 — TextWriter transplant vs append (z-order); decides Tier 1 write strategy
- [ ] Spike S3 — Identity-H GID stream patch on a representative CJK fixture; decides Tier 0 CID scope
- [ ] Spike S4 — span→operator mapping ambiguity audit (~20 corpus PDFs, ≥95% bar)
- [ ] Phase A — font_registry + verify + EditTextResult extension + TEXT_COMMIT_ENGINE flag
- [ ] Phase A.5 — shadow-classify telemetry (no behavior change)
- [ ] Phase B — Tier 0 (STREAM_PATCH, Latin) + preview DTO contract + verify_commit_fidelity gate
- [ ] Phase C — Tier 1 (RESET_ORIGINAL_FONT via TextWriter + LayoutEngine)
- [ ] Phase D — Identity-H / CJK
