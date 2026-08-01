# TODOS

## Acrobat-parity text commit engine — harness prep (plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md)

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
- [x] **ε calibration for V1d render-diff** (open question 4 in the plan) —
  DONE 2026-07-18.  Script: `scripts/calibrate_render_epsilon.py`; test:
  `test_scripts/test_calibrate_render_epsilon.py` (17 tests).
  Result on maintainer machine (Win11, PyMuPDF 1.27.1, 50 iterations, 96 dpi):
  **zero pixel noise** across all 10 corpus cases.  Recommended ε = 1
  (floor margin).  CI runner measurement deferred to the `commit-fidelity`
  CI job (Phase B) — if CI shows non-zero noise, bump ε there.
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

## M3 candidate — Acrobat-stable text commit engine V2 (design corrected 2026-07-18)

Implementation plan: `plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md`.
The earlier `plans/2026-07-14-acrobat-parity-text-commit-engine.md` is retained as
superseded design archaeology. The diagnosis remains: font/layout changes are the
structural ceiling of redact+reinsert, not a collapse of the May five-layer editor-open work.

- [x] Diagnosis + base-vs-main regression audit (commit engine unchanged; one continuous-mode placement change is unrelated to general post-commit font/reflow changes)
- [x] Adversarial design review — corrected lossless stream, text-advance, TextWriter resource identity, scratch-first verification, save/cleanup, and unsupported-PDF assumptions
- [x] Spike S1 — font round-trip audit over corpus (embedded TT/Type0: 100% extract+load)
- [x] Task 1 — deterministic synthetic fidelity corpus (merged via PR #26) + 5 strict-xfail characterization tests (`test_scripts/test_text_commit_characterization.py`, 2026-07-18): Base-14 substitution, scalar-font style truth, fast/htmlbox pixel divergence, neighbor push-down, line-break rewriting
- [x] Task 2 — lossless byte-range lexer/raw splice (`model/text_commit/pdf_lexer.py`; tiles source exactly incl. trivia/inline images; splice gated on digest+expected-bytes+overlap+range; no serializer by design)
- [x] Task 3 — horizontal page-stream text-state replay + source binding (`replay.py`/`inspect.py`; multi-stream state carry, per-stream byte ranges, stable RejectReason refusals) + read-only audit `scripts/audit_text_source_mapping.py` (synthetic corpus: 14/18 spans bound; CID/GID and rotation reject honestly)
- [x] Task 4 — per-xref font registry (`fonts.py`; keyed by generation/owner/name/xref; explicit face provenance; Type3//Differences/Identity-H tier0 reject codes; strict-ASCII verified reverse encoder; no silent Helvetica anywhere)
- [x] Task 5 — StyleOverrides (view populates only user-touched fields) + CommitStatus/Tier/FontOutcome/CommitOutcome + EditTextCommand stores outcome & gates Track A/B reflow on `allows_external_reflow` + TextCommitSettings (TEXT_COMMIT_* env) injected in main.py; defaults legacy/off
- [x] Task 6 — Tier 0 LOSSLESS_STREAM_PATCH (`plan.py`/`patch.py`/`verify.py`/`engine.py`): whole-Tj equal-advance Latin gate, scratch-first prepare, fingerprint-checked single PatchSet, V0a–V0e verification incl. exact raster identity outside 2pt halo, revert-on-failure, STALE_PLAN without mutation
- [x] Task 7 — shadow/tiered integration + maintenance policy (2026-07-19): `edit_text` hook behind `legacy|shadow|tiered` (shadow logs sanitized reason codes only; tiered commits Tier 0 with zero legacy machinery, falls back with `tier0:<reason>` chain, strict mode returns `REJECTED_STRICT` without mutation); `mark_page_content_dirty` chokepoint replaces all 9 direct `pending_edits.append` sites and revokes fidelity protection; `apply_pending_redactions` skips fidelity-protected pages. Note: block-manager runs are word-level — Tier 0 target = whole line (space-joined runs) or single whole-word run
- [x] Task 8 — exact plan-backed preview: `model/text_commit/preview.py` (one snapshot per edit session, session-scoped scratch renderer, content-derived plan token) + `controller/text_commit_coordinator.py` (session-long QThread worker, latest-wins, session/generation/identity staleness guards) + emit-only View hook (`sig_text_edit_plan_preview`) + `plan_token` carried into EditTextRequest; gated by TEXT_COMMIT_PREVIEW=plan; new gate file in verify_no_jump PYTEST_TARGETS
- [x] Task 9 — persistence + undo/redo + unsupported boundaries (2026-07-29): `test_text_commit_persistence.py` (7) + `test_text_commit_boundaries.py` (7). Tiered mode hard-rejects widget/signed pages up front (`REJECTED_UNSUPPORTED`, zero mutation) instead of silently degrading to legacy; Tier 0 undo/redo replay a validated forward/inverse PatchSet pair (`patch.py:build_reversal_patchset`) — undo restores byte-identical streams + annotations + `fidelity_protected_pages` membership, redo reproduces the exact committed bytes or fails `STALE_PLAN` with zero mutation; encryption preserved: `engine.py:_build_scratch_copy` + V0e probe now serialize with `PDF_ENCRYPT_KEEP` (the default-`tobytes()` calls were corrupting the live crypt state — see PITFALLS); `_capture_page_snapshot` restores annotation `/P` keys stripped by `insert_pdf` (pre-existing, engine-agnostic defect). Follow-up: `preview.py` still has one default-`tobytes()` call site (same encrypted-doc risk, untested)
- [x] Task 10 — Tier 1 spikes, no production enablement (2026-07-30): go/no-go recorded in plan Step 6 — advance-preserving erase GO (`patch.py:build_advance_preserving_erase`, kern-only `[N] TJ` compensation exact to 0.1pt), append NO-GO terminal (z-order/clip/OCG/gs-bleed failures structural to appending at end of `/Contents`), source-position transplant GO (`patch.py:build_transplant_replacement` inherits z-order/clip/ExtGState/OCG by construction; not advance-neutral alone — layer in erase math), font honesty GO (`patch.py:build_tier1_font_outcome` gated by `verify.py:prove_source_resource_reuse` xref-identity proof), Identity-H PARTIAL (evidence reader `verify.py:collect_cid_encoding_evidence` GO; enablement stays deferred; missing `/ToUnicode` = hard `FONT_UNSUPPORTED_ENCODING`, never Unicode-coverage inference). New: `test_text_commit_textwriter_zorder.py` (3), `test_text_commit_identity_h_spike.py` (2), `scripts/audit_tier_coverage.py` (read-only counts-only tier audit). Tier 1 remains flag-off
- [x] Task 10a — structural-gate test hardening (2026-07-31, from a test-validity audit): mutation testing proved `plan.py`'s `mc_depth` and `render_mode`/`rise`/`hscale` gates could both be **deleted with the whole suite still green** — the existing tests asserted only that the *replay recorded* the state, never that the *planner rejected* it, and every case in `test_text_commit_tier0.py`'s rejection test varies only the request, never the document. New `test_scripts/test_text_commit_structural_gates.py` (9 tests) covers all nine structural gates at planner level: mc_depth, render_mode, rise, hscale (plan.py), in_bt, origin_reliable→`UNTRACKED_ADVANCE`, trm_translation_only via **uniform scale** (the TeX/dvips `1 Tf` + `10 0 0 10 … Tm` idiom, previously only rotation was covered and only at bind level), and both `FONT_FACE_UNAVAILABLE` routes. Each test pins reason **and** a detail substring (four gates share `UNSUPPORTED_TEXT_STATE`, two share `FONT_FACE_UNAVAILABLE` — reason alone lets a test survive its own gate's deletion), asserts the fixture is off-nominal in exactly one field, and replays a positive control. All nine mutation-verified SENSITIVE. First assertions anywhere for `UNTRACKED_ADVANCE` and `FONT_FACE_UNAVAILABLE`
- [x] Task 10b — encrypted-document safety in the preview/verify paths (2026-07-31, Red-light first): `preview.py:open_preview_session` and `verify.py:_ocg_membership_lost` both called `tobytes()` with the default (decrypting) encryption on the *live* handle, silently poisoning its crypt state so the user's next `PDF_ENCRYPT_KEEP` save wrote streams that no longer decrypt. Both measured, not theoretical — 4 of 5 new tests failed before the fix with `needs_pass` 1→0 on reopen. Fix follows the proven `PDFModel._decrypted_snapshot_bytes` shape: KEEP snapshot → throwaway clone → authenticate → decrypt the clone, whose crypt state nobody depends on. `open_preview_session` now takes `password` and returns `PreviewSessionInput | None`; the controller threads `model.password` and degrades to the legacy preview with a new `snapshot_unavailable` reason rather than claiming exactness. New `test_scripts/test_text_commit_encrypted_safety.py` (5) also pins the property a lazy fix would break — the snapshot stays plan-valid, i.e. a `PreparedEdit` prepared on it still addresses the same bytes in the live encrypted document
- [ ] Follow-up from Task 10b: `_ocg_membership_lost` returns `False` ("no evidence of loss") when handed a locked probe, which the caller records as `ocg_membership_preserved` — evidence it does not actually have. Harmless today (callers pass an already-decrypted scratch, so it never fires), but promoting V0d onto live-handle documents in Task 11 requires a tri-state: "not lost" and "could not evaluate" must stop sharing an answer
- [x] Task 10c — `TextBlock.text` no longer fuses soft-wrapped lines (2026-07-31, Red-light first): `_parse_block` flattened every span of every line into one `"".join`, deleting the word boundary at each line break — a three-line paragraph read back as `"fox jumpsover the lazy dog whilecarrying"`, with `"jumps over"` absent entirely. Concatenating *spans* is correct (contiguous style runs within a line); concatenating *lines* is not. New `_join_visual_lines` inserts a single space between lines, suppressed after a trailing space/newline/hyphen (hyphen = split word) and skipping empty lines, which brings `_parse_block` in line with `_build_paragraphs` (`:560-567`) and `pdf_text_edit.py:1223`. Worth noting the value is `SequenceMatcher`-compared against `page.get_text("text", clip=...)` at `pdf_text_edit.py:456-459`, which *does* separate lines, so the fused form was depressing that ratio and could trigger spurious page-index rebuilds. 4 new tests in `test_text_block_parsing_extraction.py` (1 Red before the fix; 3 constrain it against over-correction: no span-level splitting, hyphen continuation, no double-spacing)
- [x] Task 10d — Tier 0 measures advance from `/Widths`, not from a font face (2026-08-01, Red-light first): the corpus audit found 29,526 of 38,540 shows (76.6%) refused `font_face_unavailable`, all one profile — unembedded TrueType Arial/Times New Roman/Courier New, WinAnsi, Word's default export. None is base-14, so no face resolved. But for a simple font `/Widths` **is** the layout contract, and every one of those fonts carried a complete table. New `_read_width_table` + `FontCapability.advance_source`/`first_char`/`widths`; `plan.py:_advance` sources width from the table. Proof `/Widths` outranks the font program: embed a real `arial.ttf` but write `/Widths` all-1000 — MuPDF lays out 40.0pt while the extracted face says 23.32pt. So this is also a soundness fix for the 22 embedded corpus capabilities that were being measured from the wrong source. New reason `FONT_WIDTHS_INCOMPLETE`; malformed tables never downgrade to "absent". `font_face_unavailable` 29,526 → 0, with zero fonts newly refused
- [x] Task 10e — hardening from independent review of Task 10d (2026-08-01, Red-light first, 3 tests in `test_text_commit_widths_hardening.py`): (i) **glyph coverage was bypassed** — with `/Widths` and no face, `missing_glyphs` returned "" for any text, so Tier 0 would commit replacements whose glyphs do not exist, rendering tofu; V0a–V0e cannot catch it because raster identity is asserted *outside* a 2pt halo around the target. A width proves an advance, not an outline. Now only non-subset unembedded fonts (drawn via a substituted complete face) are trusted without a face; 55 of 174 accepted corpus capabilities correctly refuse. (ii) **dangling `/Widths` ref crashed** — unguarded `xref_object` raised `RuntimeError` out through `engine.prepare` and the per-keystroke preview worker, where the pre-change code returned a clean rejection; same latent bug fixed in `_has_custom_differences`. (iii) **the advance tolerance equalled one `/Widths` unit** (`1e-3*size` vs `size/1000`), so float representation decided accept/reject — measured non-monotonic, committing a 0.600pt shift at size 600. `/Widths` arithmetic is exact, so it now gets a float-noise tolerance
- [x] Task 10f — five rounds of independent Codex review over Task 10d/10e, each finding a further layer of the *same* mistake: inferring a property from evidence that does not prove it (2026-08-01, 13 tests in `test_text_commit_widths_hardening.py`, each Red first). R1 `/Widths` attests glyphs → it proves an advance, not an outline. R2 non-subset+unembedded ⇒ substituted complete face → if the named font *is* installed the viewer uses it, and it may be symbolic; replaced with a closed full-ASCII family allowlist plus the descriptor's own `/Flags`. R3 the symbolic flag lives in an indirect descriptor → `/FontDescriptor` may be an inline dict. R4 `/Flags` is a literal → it may itself be `N 0 R`, and the regex was reading the *xref number* (my own test passed only because the allocated number happened to have bit 3 set — made deterministic); plus StandardEncoding disagrees with ASCII at 0x27/0x60 (`quoteright`/`quoteleft`), indirect `/FirstChar`//`LastChar` were misread as malformed, and `/Widths` tokenisation was unbounded in the per-keystroke path. R5 the staleness fingerprint did not cover `/Widths` at all, so a plan measured against old widths passed the freshness check; plus the token bound still materialised the full list. R6 the fingerprint followed `/Widths` but not `/FirstChar`//`LastChar`//`Encoding`//`FontDescriptor`, each of which may also be indirect — replaced ad-hoc enumeration with an auditable dependency-key list. R7 the descriptor `/Flags` were read by regex over the serialised object, which a string value like `/FontFamily (/Flags 0)` defeats; **the recurring root cause across R3/R4/R7 was parsing PDF dictionaries with a regex**, so the regex was removed entirely in favour of PyMuPDF's structured path lookup `xref_get_key(font_xref, "FontDescriptor/Flags")`, which resolves inline-or-indirect descriptor *and* inline-or-indirect flags in one call. R8 a font dictionary stored inline in `/Resources` reports xref 0, and every xref call against it raises out through the per-keystroke path — guarded in all three readers. Corpus outcome identical through all eight rounds (174 accepted / 119 encode / 55 glyph-refused), so none of the safety work cost real coverage. Review stopped at R8 by request; R8's fix went in without a further review pass
- [ ] ~~**Scoping correction — the matrix/operator gates are NOT dead.**~~ **SUPERSEDED 2026-08-01** — the 5,879 figure and the "single-item `TJ` takes `1.pdf` 0/26 → 26/26" claim below both rest on the unsound `array_item_count == 1` rule; the sound decomposition (5,688 hex `Tj` + 165 literal + 0 sound kernless `TJ`) and the phased plan replace them. Kept for provenance; read the phased blocks below instead. Original text:
  **Scoping correction — the matrix/operator gates are NOT dead.** The earlier "trm+op relaxation buys only 137 shows (0.36%)" was measured while the font gate was masking it; the gates were co-blocking. With Task 10d landed, P3 (+uniform_scale +tj_equiv_ops) is worth **5,879 shows (15.25%)**, a 43x change. Two caveats before acting: that figure uses an `array_item_count == 1` TJ rule that is **unsound** as specified (`[-100 (A)]` has one string item but its leading kern shifts the origin — needs a no-kern check, not an item count), and relaxing the trm gate would invert `test_planner_rejects_uniformly_scaled_text_matrix`, which is a deliberate design decision, not an implementation detail. P0 under the *current* policy is still 0: no show fails only the font gate
- [ ] Open defects from the same audit, not yet fixed: (a) Tier 0 is inert on all 6 `test_files/` PDFs (0 eligible of ~38,500 shows) — dominant blocker is the exact-identity text-matrix gate rejecting *uniform scale*, stricter than the plan, which only defers rotation/shear; accepting single-item `TJ` would take `1.pdf` from 0/26 to 26/26. (b) `MULTI_SPAN_TARGET` (`pdf_text_edit.py:1296,1364`) still has no assertion anywhere — it is above the planner, so it needs a different harness than the gate tests. *(Both folded into the phased panel-review block below: (a) → pre-Task-11 D1, (b) → pre-Task-11 D5.)*
- [x] **Panel review 2026-08-01** — three independent models (Opus/Sonnet/Haiku, serial, each told to refute the "structural relaxations are capped by equal-advance" verdict) returned unanimous *partially refuted*: the recommended order stands, the reasoning did not. Two corrections: (i) real edit classes pass the advance gate **deterministically**, not by coincidence — `plan.py:_advance` is a pure multiset function of the text (Σ per-code `/Widths` + Tc·len + Tw·spaces), so transpositions (`teh`→`the`) have delta exactly 0.0; digit-for-digit edits are advance-preserving wherever the font declares tabular figures (verified for Helvetica in `test_text_commit_font_widths.py`; corpus Word-export fonts unverified). The P=0.39 uniform-random-swap statistic measures neither class. (ii) The equal-advance rule is a v1 *policy*, not a ceiling — the plan invariant already licenses "an independently verified compensation operation", and `build_advance_preserving_erase` + `build_transplant_replacement` compose to `[(newtext) K] TJ` with no layout engine (= Task 11 Slice 1). Remaining work reorganized into the three phased blocks below; details in the plan's Task 11 amendment (2026-08-01)

### Pre-Task-11 (do in this order, before any layout work)
- [x] **D5 — direct tests for `_tier0_target_from_resolve` (2026-08-01, Red-light first): 11 tests in `test_scripts/test_tier0_target_resolution.py`, the first direct coverage this stage has ever had.** The defect is real and now measured: word runs are `.strip()`-ed in `text_block_parsing.py:_finalize`, so the `" ".join` at `:1223` reproduces the source only when every gap was exactly one space. `"Price is  100"` rebuilt as `"Price is 100"` fails `bind_source_text`'s byte equality (`inspect.py:233`) and surfaced as `no_source_match` — byte-identical to the refusal for text that is genuinely absent, which is why the class was invisible to every corpus number (the audits classify *shows*, not *edits*). Fix: `_tier0_target_from_resolve` returns `_Tier0Target` carrying `joined_runs`, and a run-joined target failing only `NO_MATCH` is re-labelled `TARGET_RECONSTRUCTION_UNVERIFIED` (new `RejectReason`) at both call sites — the reconstruction is named as the suspect instead of the document. Also the first assertions anywhere for `MULTI_SPAN_TARGET`, at both `:1296` and `:1364`, the latter proving zero mutation on the live-document path. **Mutation-verified (7 mutants):** empty-members guard SENSITIVE, full-line set-equality SENSITIVE, the re-label in both directions SENSITIVE (keep-original *and* relabel-every-miss), `joined_runs` source SENSITIVE, and the `_attempt_tiered_commit` call site SENSITIVE. Two mutants initially SURVIVED and both were real: the `any(...)` line-identity guard (subsumed — see next item), and the commit-path call site, which the classify-path tests were covering *for* it, since mutating a shared helper does not prove each caller invokes it. The latter is now pinned by a dedicated test; the former cannot be
- [ ] **The `any(...)` line-identity guard in `_tier0_target_from_resolve` is subsumed, not pinned** (found by D5 mutation testing). Deleting it leaves the whole suite green: `span_id` is `f"p{page}_b{block}_l{line}_s{idx}"` in both parsers, so a member on another line always carries an id absent from `first`'s `line_run_ids`, and the full-line set-equality check below refuses the same input first; with one member `any(...)` compares `first` to itself. Kept as cheap defence-in-depth and the test docstring no longer claims to pin it. Decide deliberately: delete it, or give it a reachable role. Do **not** fabricate a fixture that makes it look SENSITIVE
- [ ] **Preview path still reports the undifferentiated `NO_MATCH` (asymmetry knowingly left by D5).** `derive_tier0_preview_target` (`pdf_text_edit.py:1280`) drops `joined_runs` to keep its 3-tuple contract, so a multi-space line reports `target_reconstruction_unverified` on commit but plain `no_source_match` in the per-keystroke preview — two answers for one condition. No user-visible or correctness difference (both degrade the preview, neither mutates); it is a telemetry/diagnosis inconsistency, and the shadow-mode reason counts the measurement pass will collect come through *both* paths, so fix it before trusting those counts. Closing it means threading the field through `controller/pdf_controller.py:3565` → `text_commit_coordinator.request` → `preview.py:191`, i.e. the QThread worker boundary the plan already lists as needing its own contract work — deliberately not done inside a test task
- [ ] **Recover the whitespace-collapsed edits (owed; D5 only made them honest, not working).** The verbatim source text *is* available — the dict parse preserves `"Price is  100"` and `"  Hello World  "` exactly (probed 2026-08-01), whereas the rawdict word runs do not. Two blockers before using it: (a) mapping a run's `(block_idx, line_idx)` onto the dict line crosses the rawdict↔dict index-alignment assumption baked into `_build_page_index`, untested at the shapes where it breaks (multi-span lines, blocks `_parse_block` skips, multi-line blocks); (b) it does not help the single-run shape — `"  Total  "` parses to one run `"Total"` that also fails to bind, so leading/trailing padding needs its own answer. **Do this before the measurement pass**, or the pass will read the `TARGET_RECONSTRUCTION_UNVERIFIED` count as a ceiling rather than as a known-fixable gap
- [ ] **Fix `scripts/audit_tier_coverage.py:70-76`** — `tier1_candidate` still requires `capability.face is not None`, contradicting Task 10d (`/Widths` is the contract); the owed audit would understate Tier 1 candidacy on the dominant unembedded-Word profile. Mechanical, blocks any trustworthy Task 11 sizing
- [ ] **Measurement pass (counts-only, extends the audit; run on a representative corpus — current one is 93% one file):** (a) edit-level funnel survival (resolve→bind→plan), not just show-level classification; (b) forward advance-dependency rate — how often a successor consumes an op's advance before the next `Td`/`Tm`/`T*`/`BT` (decides how much of Slice 1 needs kern math at all); (c) tabular-digit check over corpus `/Widths` tables; (d) TJ binding-survival rate — `decoded_bytes` drops kern numbers (`replay.py:460`) vs exact byte equality at `inspect.py:233`, so kern-as-word-gap arrays can never bind and the 17,952 (46.6%) TJ figure is NOT achievable coverage. Also start collecting Task 7 shadow-mode `tier0:<reason>` telemetry — already built, privacy-safe, unused
- [ ] **Runtime + memory baseline BEFORE any implementation** (moved up from Task 12 on the GPT-5.6-sol review — you cannot detect a regression you never baselined, and D1/Slice 1 both add per-preview work). Measure p50/p95/p99 for: cold and warm prepare, key-to-preview, raster time, stale-generation drop rate, commit, live verification, undo/redo, peak + resident memory, and memory after repeated preview-session teardown. Derive budgets from the measured legacy baseline — do **not** adopt invented thresholds (150ms, 1s); the plan's own rollout gate says budgets come from measurement. Repeat after each phase
- [ ] **D1 — hex-Tj + uniform-scale Tier 0 relaxation, complete scope:** hex gate at `plan.py:143` (patch writer already replaces the whole operand range with a fresh literal); relax `_is_translation_only` to `a==d, b==c==0, a>0` (without `a>0` the 48 reflected/mirrored shows slip in); fix the *fallback* `target_bbox` (`plan.py:243-250`) for scale — under scale<1 the halo inflates and can mask out-of-halo corruption (false accept; production path already passes a page-space bbox via `pdf_text_edit.py:1225`); revise, never delete, the mutation-SENSITIVE `test_planner_rejects_uniformly_scaled_text_matrix`; one-line plan wording amendment. ~5,853 sound shows on the current corpus (5,688 hex + 165 literal; 5,666 overlap needs both), plus it unblocks the deterministic transposition/digit classes on real docs

### During Task 11
- [ ] **Slice 1 ships first** — transplant + kern compensation (`[(newtext) K] TJ` at the source op's byte range, same font resource/encoding, K absorbs the advance delta, every following show provably unmoved). No `layout.py`, no wrapping/alignment/embedding until Slice 1 is verified. Both primitives exist and passed spikes (`patch.py:156-213`) — **but separately.** The spikes prove erase-compensation and transplant in isolation; "every following show is provably unmoved" is a *forecast* for the composite until one Red test proves the whole candidate at once: replacement text renders, arbitrary replacement advance is compensated, every later show retains its origin, persistent text state is unchanged, exact source range + stream digest are checked, preview and commit use the *same* prepared candidate, undo restores byte-identical bytes, and verification failure reverts everything
- [ ] **Tier 1 contracts that Task 11's file list does not yet cover** (GPT-5.6-sol): Tier 1 prepared-candidate/token DTOs, preview↔commit candidate identity, live-commit rollback, persistence, undo/redo, resource-dictionary/font-embedding mutation, and clipping / allowed-growth-region semantics. Also **shared content streams** — a stream referenced by multiple pages must be handled or explicitly rejected. Task 11's `Files:` list names `layout.py`/`plan.py`/`patch.py`/`engine.py`/`view/text_editing.py` only; the preview, controller, DTO, and persistence surfaces are missing and need adding before implementation starts
- [ ] **Operator guard on `patch.py:156-213` (latent defect, code-verified):** neither builder checks `show.operator`. For `"`, `op_start` is `operands[-3].start` (`replay.py:437`) — the spliced range includes the aw/ac operands whose `Tw`/`Tc` assignments persist beyond the op (`replay.py:426-427`); `'` folds in an implicit `T*` (`replay.py:399-402`). A naive whole-op rewrite silently deletes persistent state. Refuse `'` and `"` explicitly, with tests
- [ ] **Halo semantics under growth (design decision, document it):** replacement ink extends past `target_bbox_page`, so V0d's raster-identity-outside-halo stops proving the neighbour region unpainted. Either widen the halo and report it honestly, or admit compensated growth only when `verify.py:_region_is_uniform` proves the growth zone blank pre-edit
- [ ] **D4 — `_ocg_membership_lost` tri-state, ALL failure paths** (`verify.py:341-379`: locked probe plus every raised-exception branch currently return `False`, which the caller records as `ocg_membership_preserved`). Required before V0d/`verify_tier1_strategy` runs on live handles; not a blocker for starting Slice 1 (transplant inherits OCG by construction)
- [ ] **TJ arrays — cheap half only, gated on the binding-survival measurement:** admit whole-array targets via `build_transplant_replacement` (sound by construction — an accepted target always covers the entire operator, so no unedited glyph sits inside the replaced range), preserving leading/trailing kerns; never the unsound `array_item_count==1` rule. Do NOT build in-array splicing with kern rebalancing — it serves only substring targets every tier refuses

### After Task 11 (Task 12 scope additions)
- [ ] **Re-measure runtime against the pre-Task-11 baseline** (the baseline itself moved above). Known risk: `preview.py` re-runs `prepare_tier0_plan` per keystroke generation, replaying every content stream on the page and then re-reading them (`inspect.py:213-217`, `plan.py:228-229`) — a full page re-parse per keystroke on the 35,844-show file. If dense-page preview p95 regresses: cache replay/index state, eliminate the duplicate stream read, debounce or tile raster work — and do **not** expand into paragraph layout until Slice 1 is responsive
- [ ] **Publish coverage as a funnel, both weightings** (GPT-5.6-sol): selected edits → target resolved → source bound → encoding/glyph accepted → candidate built → preview verified → commit verified → save/reopen verified. Report per document class, and give **document-weighted alongside show-weighted** numbers so the 35,844-show file cannot define the headline. Structural eligibility is headroom, never product coverage
- [ ] **Zero-tolerance correctness gates — any one blocks rollout:** mutation after a stale/rejected prepare; changed non-target stream bytes; moved following text; changed font/resource binding without a declared outcome; raster difference outside the declared affected region; preview candidate ≠ committed candidate; a "preserved" result where verification was not evaluable; failed undo/redo/encryption/save-reopen matrix
- [ ] **Pivot conditions, agreed in advance:** D1 — if verified edit-level acceptance stays near zero outside the dominant PDF, keep it opt-in and stop quoting 15% as coverage. Slice 1 — if the composite cannot preserve following origins and outside-region pixels, stop Tier 1 transplant rather than weakening verification. Whole-array `TJ` — defer if binding survival is negligible. Paragraph layout — narrow scope rather than silently degrading fidelity if it needs ambiguous multi-show reconstruction or uncontrolled resource mutation
- [ ] **Report the Q3 ceiling decomposed, not blended:** Task 11's real ceiling is materially below the 72.79% structural figure — Identity-H stays NO-GO so `font_unsupported_encoding` (14.74%) never clears; `render_mode` (5.55%) is unaddressed by Task 11 scope; `mc_depth` (6.51%) plausibly clears via transplant inheritance. Nothing currently computes the actual ceiling; the rollout decision needs it
- [ ] Task 12 as planned — blocking fidelity/performance CI, rollout gates (default is still legacy: nothing from D1/Slice 1 reaches a user until these pass), docs, `git mv` plan archive
