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
- [x] Follow-up from Task 10b: `_ocg_membership_lost` → tri-state `_ocg_membership_status` (`preserved` / `lost` / `unknown`) across locked-probe and every exception path (WS-D, 2026-08-03). Unknown is never recorded as `ocg_membership_preserved`. Bool wrapper retained for callers that only need confirmed loss.
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
- [x] **DECIDED 2026-08-04 — keep as deliberate defence-in-depth.** The guard stays, with a comment at `model/pdf_text_edit.py:1478-1484` recording the decision, why mutation testing marks it insensitive, and an explicit instruction not to fabricate a fixture for it. Rationale: its protection must not hinge on `span_id`'s format staying byte-identical across two independent parsers — that is an incidental property of today's code, not a contract. Cost is one `any()` over a member list already in hand. Original item:
  **The `any(...)` line-identity guard in `_tier0_target_from_resolve` is subsumed, not pinned** (found by D5 mutation testing). Deleting it leaves the whole suite green: `span_id` is `f"p{page}_b{block}_l{line}_s{idx}"` in both parsers, so a member on another line always carries an id absent from `first`'s `line_run_ids`, and the full-line set-equality check below refuses the same input first; with one member `any(...)` compares `first` to itself. Kept as cheap defence-in-depth and the test docstring no longer claims to pin it. Decide deliberately: delete it, or give it a reachable role. Do **not** fabricate a fixture that makes it look SENSITIVE
- [x] **CLOSED 2026-08-04 (Red-light first).** Note the description below is stale in one detail: by the time this was picked up, `derive_tier0_preview_target` already returned a full `_Tier0Target` (the whitespace-recovery work above changed it) — the residual gap was the *DTO chain* discarding the provenance, not the derivation dropping it. Closed by threading `whitespace_reconstructed` through `controller/pdf_controller.py:3595` → `text_commit_coordinator.request(whitespace_reconstructed=)` → `PlanPreviewRequest.whitespace_reconstructed`, where the renderer relabels a bare `NO_MATCH` to `TARGET_RECONSTRUCTION_UNVERIFIED` exactly as the commit path does. Shadow-mode reason counts collected through the two paths are now comparable. Original item:
  **Preview path still reports the undifferentiated `NO_MATCH` (asymmetry knowingly left by D5).** `derive_tier0_preview_target` (`pdf_text_edit.py:1280`) drops `joined_runs` to keep its 3-tuple contract, so a multi-space line reports `target_reconstruction_unverified` on commit but plain `no_source_match` in the per-keystroke preview — two answers for one condition. No user-visible or correctness difference (both degrade the preview, neither mutates); it is a telemetry/diagnosis inconsistency, and the shadow-mode reason counts the measurement pass will collect come through *both* paths, so fix it before trusting those counts. Closing it means threading the field through `controller/pdf_controller.py:3565` → `text_commit_coordinator.request` → `preview.py:191`, i.e. the QThread worker boundary the plan already lists as needing its own contract work — deliberately not done inside a test task
- [x] **CLOSED 2026-08-04 (opus design → sonnet implement, Red-light first).** Both blockers answered rather than assumed away. `_Tier0Target` gained `source_kind` (`"run_join"` | `"dict_line"`) + `replacement_for(edited)`, and `_dict_line_for_runs` resolves the dict line for a run set behind a **runtime** content-and-geometry alignment proof (gates P1–P5 / A1–A2 / G1–G4) instead of relying on the rawdict↔dict index-alignment assumption blocker (a) named below — the alignment is verified per call, so the shapes where it breaks (multi-span lines, `_parse_block`-skipped blocks, multi-line blocks) refuse instead of mis-binding. Blocker (b), single-run padding, is covered because the dict line carries the leading/trailing padding verbatim. **Funnel re-measured after landing** — and the honest result is that the class *rose*, 19.8% → 29.1% `TARGET_RECONSTRUCTION_UNVERIFIED`, while bind survivors went 51 → 93. That is not a regression: MuPDF materializes wide `TJ` kerns as synthesized spaces (see PITFALLS), so on the dominant document the dict line is *also* a reconstruction, and cases previously mislabeled `NO_MATCH` are now correctly named. **Provenance caveat:** these two figures come from the delegated 2026-08-04 measurement pass; the orchestrator did not independently re-run it and the exact invocation (fixture set + per-page caps) was not captured, so Task 12's ceiling decomposition must **re-measure, not cite**. Original item:
  **Recover the whitespace-collapsed edits (owed; D5 only made them honest, not working).** The verbatim source text *is* available — the dict parse preserves `"Price is  100"` and `"  Hello World  "` exactly (probed 2026-08-01), whereas the rawdict word runs do not. Two blockers before using it: (a) mapping a run's `(block_idx, line_idx)` onto the dict line crosses the rawdict↔dict index-alignment assumption baked into `_build_page_index`, untested at the shapes where it breaks (multi-span lines, blocks `_parse_block` skips, multi-line blocks); (b) it does not help the single-run shape — `"  Total  "` parses to one run `"Total"` that also fails to bind, so leading/trailing padding needs its own answer. **Do this before the measurement pass**, or the pass will read the `TARGET_RECONSTRUCTION_UNVERIFIED` count as a ceiling rather than as a known-fixable gap. *(Update 2026-08-01: the measurement pass ran first anyway, but explicitly deconflated and reported the class as known-fixable — 7,251/36,518 samples (19.8%) after XObject deconfliction — so the feared misreading did not occur. The recovery work is still owed; re-run `scripts/measure_tier_funnel.py` after it lands to watch that 19.8% convert.)*
- [x] **Fix `scripts/audit_tier_coverage.py` predicates (2026-08-01).** `tier1_candidate` no longer requires `capability.face is not None` (contradicted Task 10d — `/Widths` is the contract); both it and `tier0_eligible` now require `tier0_reject_reason is None` **and** the Task 10e glyph proxy `(face is not None or ascii_repertoire_attested)` — a structural audit cannot evaluate text-dependent `missing_glyphs`, and without the proxy the 55 always-refusing capabilities count as headroom. Before/after on the six-PDF corpus: identical (0 / 26 / 38,516) — the proxy costs zero here, verified again post-D1 (`fails_only_glyph_proxy = 0`)
- [x] **Measurement pass (2026-08-01, `scripts/measure_tier_funnel.py`** — counts-only, deterministic, rerun-identical; drives the real resolve stage per the D5 harness, binds against a per-page cached replay cross-checked 0 mismatches vs the real `bind_source_text` over 618 targets, then identity-replacement plan survival). Results (six PDFs + ten synthetic fixtures, 36,518 sampled targets, caps 30 lines/60 runs per page recorded in output; **taken under pre-D1 gates, so funnel rates are now stale relative to production — re-run after any gate change**): (a) bind 0.14% show-weighted vs 18.7% document-weighted (130× divergence — the skew warning was justified); plan 0% everywhere, re-confirming the audit independently. (b) Forward advance-dependency **0.40%** show-weighted, 100% concentrated in `test-complexed-layout.pdf` (6.1% of its own shows; every other file 0%) — Slice 1's kern math is load-bearing for a thin slice of this corpus. (c) Tabular digits: 44.9% of font capabilities but only **5.5% of shows** use such a font — the digit edit class exists but is thin by usage. (d) TJ binding-survival: **0.59%** (146/24,665 kernless) — 99.4% of TJ shows carry kerning and can never byte-bind; feeds the whole-array-TJ pivot condition below. (e) NEW, advisor-driven: `TARGET_IN_FORM_XOBJECT` deconfliction — the production label is page-scoped and only 5.3% of its firings are confirmed target-in-XObject; deconflated `target_reconstruction_unverified` is **19.8% of all samples** (vs 11 raw), squarely the known-fixable gap the item below warned about (see PITFALLS). Shadow telemetry verified, not enabled: collection requires **both** `TEXT_COMMIT_ENGINE=shadow` and `PDF_EDITOR_DEBUG=1` (the INFO log line is dropped at the default WARNING level); `TEXT_COMMIT_TELEMETRY` is parsed but read nowhere (dead flag — wire or remove)
- [x] **Runtime + memory baseline (2026-08-01, `scripts/benchmark_text_commit_baseline.py`** — headless, no Qt; measured numbers live in the **gitignored, machine-local** `benchmarks/baseline-2026-08-01.json` with full p50/p95/p99 — absolute figures deliberately stay out of shared commits). Structure of the result: the real corpus had zero eligible shows pre-D1, so accept-path metrics (commit/verify/undo-redo) come from clearly-labeled synthetic injected fixtures; the reject path — the true per-keystroke driver — was measured on the real dense file. Qualitative shape: accept-path prepare is ~30× the dense reject-path prepare, dominated by the whole-doc scratch copy + `tobytes` reopen; preview pays one whole-doc snapshot at session open, then per-generation work is cheap relative to it; undo/redo via the reversal patchset is ~1000× cheaper than commit (no whole-doc snapshot); teardown leak over 25 cycles is ~20KB tracemalloc (psutil unavailable in the venv — recorded, not faked; stale-generation drop rate is Qt-side and recorded not-measurable-headless). Budgets remain underived per the rollout gate — numbers only. **Repeat after each phase** and after any D1/Slice 1 perf-relevant change
- [x] **D1 — hex-Tj + uniform-scale Tier 0 relaxation (2026-08-01, Red-light first, mutation-verified).** `replay.py`: `_is_translation_only` → `_uniform_scale(m) -> float | None` (factor when `b==c==0, a==d>0`; `None` for rotation/shear/reflection/mirror/degenerate); `ShowOp.trm_translation_only` → `trm_uniform_scale` + derived `trm_uniform_scaled` property. `inspect.py`: bind gates on the property; detail re-worded ("non-uniformly scaled"). `plan.py`: operand gate accepts `string_kind in ("literal","hex")` for `Tj` (`TJ`/`'`/`"` still refused; verified the patch writer already splices the whole operand range incl. `<`/`>` — no writer change); fallback `target_bbox` scale-corrected (Red pinned the exact 2× inflation at `a=d=0.5` — the false-ACCEPT direction, see PITFALLS). The SENSITIVE test was revised into `test_planner_accepts_uniformly_scaled_text_matrix` (same fixture, docstring records the former name); gate coverage moved to two new parametrized rejection tests, mutation-run-verified: `b==c==0` pinned only by `a==d>0`+off-diagonals, `a>0` pinned only by point reflection (see PITFALLS on fixture subsumption). Mirror predicates updated in `audit_tier_coverage.py` + `measure_tier_funnel.py`; one dated plan line. Full suite 2135 passed / 28 skipped / 5 xfailed; ruff + mypy clean. **Audit: tier0_eligible 0 → 5,853 (15.19%) — the prediction held exactly** (`fails_only_glyph_proxy=0`); composition 5,688 hex + 165 literal, **100% at non-unit scale**, so hex-only is worth 0 and the joint-requirement count is 5,688 (the plan's ~5,666 was wrong — corrected, not agreed with). All gain is in `test-large-file.pdf`; the other five files stay at 0 (mc_depth/font gates dominate), which is exactly the D1 pivot-condition scenario below — verified edit-level acceptance outside the dominant PDF is still ~0, so D1 stays opt-in and 15% is headroom, not coverage
- [x] **RESOLVED (2026-08-01/02): scratch-first fingerprint self-check failed on disk-loaded documents — blocked every real Tier 0 accept on the dominant file.** `tobytes(encryption=KEEP)` reorders a disk-loaded object's dictionary keys on first serialization (idempotent after one round trip); `_update_font_dependencies` hashed `xref_object()` strings verbatim, so `TieredCommitEngine.prepare()`'s pre-scratch fingerprint never matched the scratch's — measured on `test_files/test-large-file.pdf`, the exact file where D1 made 5,853 shows eligible. Unit tests never saw it (synthetic fixtures are never disk-loaded). Fixed Red-light-first (`test_scripts/test_text_commit_fingerprint_roundtrip.py`): `_update_font_dependencies` now folds `_canonical_object_digest` — `sorted(xref_get_keys)` + `xref_get_key` per key — instead of the raw `xref_object()` string; order-independent, so the MuPDF reorder no longer moves the digest while a real dependency mutation still does. All 5 genuinely-eligible Tier-0 targets found on this file (pages 13/14/15/18×2) now return `PreparedEdit` from `TieredCommitEngine.prepare()` on the real document. Full suite green, no regressions; see PITFALLS
- [x] **NEW (measurement stage, 2026-08-01 → fixed WS-D 2026-08-03): `TARGET_IN_FORM_XOBJECT` is target-scoped in production `bind_source_text`.** Confirmed via per-target Form XObject replay (one level); a page that merely invokes a logo/bullet XObject no longer rebrands every miss as `TARGET_IN_FORM_XOBJECT`.
- [x] **Codex P2 review fixes (2026-08-01, ultracode workflow, serial opus→haiku→sonnet, each independently re-verified).** Three findings from `/codex:review` on the pre-Task-11 diff: (1) **CONFIRMED, fixed** — the fallback `target_bbox` (D1's scale fix covered only the Tm term) ignores `/UserUnit`: MuPDF folds it into `page.rect`/`page.transformation_matrix` (mediabox stays unscaled), so `binding.origin_page` is page-scaled while `_advance`/`font_size` stay text-space. At `/UserUnit 2` a valid edit was refused (`verification_failed`, halo half-size); at `/UserUnit 0.5` the halo doubled — the dangerous direction, since V0d only proves raster identity *outside* the halo. Fix: `scale = trm_uniform_scale * math.hypot(page_matrix.a, page_matrix.b)` (hypot, not `abs(a)`, which reads 0 at `/Rotate 90`). Red pinned first (2 new tests, both directions), mutation-verified, 4 fallback-bbox tests total incl. an independent MuPDF-rawdict oracle. My own pre-dispatch hypothesis that this was a PyMuPDF false positive was wrong — stated here so the record doesn't quietly bury a wrong guess. (2) **Fixed** — `scripts/measure_tier_funnel.py` printed real PDF basenames in both JSON and text output; replaced with positional `doc_index`, matching the same privacy contract `audit_tier_coverage.py` already documents. (3) **Fixed** — `scripts/benchmark_text_commit_baseline.py`'s `corpus_findings` was a hardcoded pre-D1 string (claimed 0 eligible everywhere); now computed at run time via `audit_tier_coverage.audit_document()`, with the old claim kept inline labeled "Superseded 2026-08-01" for provenance. Scoping check done, not assumed: the real-corpus reject-path benchmark's picked target (densest page of `test-large-file.pdf`) is itself a `TJ`-array element, so its reject reason was already `NOT_SINGLE_LITERAL_TJ` pre-D1 too (a structural gate checked before the text-state gate) — the docstring's old `UNSUPPORTED_TEXT_STATE` claim described `audit_tier_coverage.py`'s *aggregate* classification, not this one `prepare()` call. Full suite re-verified independently: 19/19 structural-gates tests, ruff clean, mypy clean

### During Task 11
- [x] **Slice 1 ships first (2026-08-02)** — transplant + kern compensation (`[(newtext) K] TJ` at the source op's byte range, same font resource/encoding, K absorbs the advance delta, every following show provably unmoved). Landed with all 12 red tests green, full verification suite passing, and six-PDF corpus audit confirming measurable forward-advance dependency is 0.40% show-weighted (99.6% of shows have no consuming successor before the next structural op, so kern compensation is sound and rarely load-bearing). Files completed: `model/text_commit/{dto,plan,patch,verify,inspect,engine}.py`, `model/{pdf_text_edit,edit_commands}.py`, `controller/pdf_controller.py`, `preview.py` threading, undo gate widening, and one test-fixture deviation (char-level vs span-level target_bbox in growth-refusal cases).
- [x] **Tier 1 contracts coverage (2026-08-02)** — extended `Files:` list now includes prepared-candidate token lifecycle in `dto.py:PreparedEdit`, preview↔commit identity in `preview.py`, live-commit rollback gating in `engine.py`, persistence/undo/redo in `edit_commands.py`, resource-dictionary/font-embedding via `patch.build_tier1_font_outcome` + engine pre-scratch/pre-apply honesty re-verification, and shared-content-stream detection via `inspect.find_pages_sharing_content_stream` (both tiers covered, gated in the `_classify_common` prologue). **Deferred:** layout.py, wrapping/alignment/overflow UI, different-face replacement, Identity-H/CID enablement, deletion/multiline, running growth gates inside per-keystroke preview, shadow mode staying Tier-0-only.
- [x] **Operator guard on `patch.py:156-213` (2026-08-02)** — `_SPLICEABLE_SHOW_OPERATORS = {"Tj", "TJ"}`, `_require_spliceable_show(show)` raises `UnsupportedShowOperatorError` at the top of both `build_advance_preserving_erase` and `build_transplant_replacement` (patch.py mechanism), plus policy refusal in `plan.py`'s `_classify_common` before `NOT_SINGLE_LITERAL_TJ` gate (plan.py policy). New `RejectReason.UNSUPPORTED_SHOW_OPERATOR` emitted by both sites, tests confirm ' and " are refused without entering the builders.
- [x] **Halo semantics under growth (2026-08-02)** — decided: blank-growth-zone proof on the PRE-EDIT rendering via two independent gates sharing reason `GROWTH_REGION_NOT_BLANK` but not detail prefix: rawdict character-intersection gate (exact, text-only, size-independent) and raster uniformity gate (covers non-text ink). Widened clip only: `verify_bbox_page = union(target_bbox_page, target box extended along the advance direction by (replacement_advance - source_advance) * trm_uniform_scale)`, with V0c span-origin comparison staying pinned to `target_bbox_page` on both sides (proven pre-edit, never widened). HONESTY LIMITS documented: V0c cannot see merged same-span successors, residual 1.5pt unproven band at the advance edge exists, and V0c's wider clip sees more neighbours (false rejects only, never false accepts).
- [x] **Fallback `target_bbox` uses user-space→visual matrix (WS-D, 2026-08-03)** — build rect in user space, map through `transformation_matrix * rotation_matrix`. PyMuPDF's `transformation_matrix` alone omits `/Rotate`; without `rotation_matrix` a `/Rotate 90/270` halo stays horizontal while pixmap ink runs vertically. `/Rotate 90/270` fixtures + scale/`/UserUnit` controls in `test_text_commit_structural_gates.py`. See PITFALLS.
- [x] **`TEXT_COMMIT_TELEMETRY` wired (WS-D, 2026-08-03)** — shadow measurement `logger.info` emits only when `telemetry == "local"`; default `off` suppresses the line. Classification still runs under `engine=shadow`.
- [x] **D4 — `_ocg_membership_status` tri-state (WS-D, 2026-08-03)** — locked probe + every exception path return `unknown`; `verify_tier1_strategy` records `ocg_membership_unknown`, never `preserved`, on unknown.
- [x] **Stale undo mirrors stale redo (WS-D, 2026-08-03)** — high-fidelity inverse-patch stale → `EditTextResult.STALE_UNDO`, zero mutation, command retained on undo stack; no page-snapshot fallback.
- [ ] **TJ arrays — deferred per pivot condition** — binding survival is 0.59% show-weighted (146 of 24,665 TJ shows are kernless; 99.4% can never byte-bind). Whole-array targets via transplant are sound by construction; in-array splicing with kern rebalancing is rejected. Gate measured 2026-08-01; pivot condition met: "defer if binding survival is negligible" — revisit only if a representative corpus disagrees or binding stops demanding byte equality
- [x] **Same-line successor merges into the target's own rawdict span** (deviation 2026-08-02; PITFALLS cross-ref WS-D 2026-08-03) — char-level `_target_bbox(page, probe)` in Slice 1 growth-refusal fixtures; see `docs/PITFALLS.md` "Same-line successor merges…".
- [x] **WS-B — Tier 1 growth proof + rollback atomicity (2026-08-03, Red-light first, `db5ca5db`):** `growth_outside_page` containment gate at `_build_tier1` (widened verify bbox must sit inside `page.rect`, 1e-3pt tolerance — clamping never substitutes for proof); `prove_growth_region_blank` upgraded from uniformity to background-reference + drawings/images/shading occupancy, fail-closed on every uninspectable path (a uniformly BLACK growth zone is now refused); live-commit `verify_fn` wrapped in try/except → `applied.revert(doc)` + re-raise, so a *raising* verifier can no longer strand a half-applied patch. Tests in `test_scripts/test_text_commit_tier1_slice1.py` (+3, incl. fault injection asserting byte-identical stream + fingerprint after the raise).
- [x] **WS-A — preview↔commit candidate identity (2026-08-03, Red-light first, `ff435fbe`):** token read from the saved `editor` local *before* `view.text_editor = None` (was always `None` at emit); threaded `EditTextRequest.plan_token` → `EditTextCommand` → `model.edit_text(plan_token=)` → `_attempt_tiered_commit`; `TieredCommitEngine` gained the `VerifiedPreparedEdit` cache (`prepare()` auto-caches, FIFO 8, `get_verified_candidate`/`clear_verified_candidates`); `_content_token` preimage widened to full candidate semantics (target/verify bbox, advance pair, kern, font identity, style/geometry intent). Stale cached candidates are refused at apply time by the PatchSet fingerprint gate. New `test_scripts/test_text_commit_candidate_identity.py`.
- [x] **WS-C — preview verdict parity and session candidate identity (2026-08-03, Red-light first):** preview now captures pre-patch state and runs the Tier 0/Tier 1 verifier before rasterizing, refuses growth/blank/outside-page candidates with the live reason class, widens raster clips to `effective_verify_bbox`, forwards style/geometry intent, and returns the verified `PreparedEdit`. `PDFModel` owns one `TieredCommitEngine` per document session; the controller caches that DTO on the GUI thread so commit reuses the preview candidate by `plan_token`. Preview V0e reuses the open session-scratch certificate to preserve the one-scratch-per-session keystroke budget; live commit retains the real KEEP-encrypted reopen probe. New coverage: `test_scripts/test_text_commit_preview_parity.py`.
- [x] ~~**Slice 1 acceptance CLOSED (2026-08-03)**~~ — **SUPERSEDED 2026-08-04 by the entry below.** An adversarial re-verification pass refuted part of this verdict: **P0-3 was not fixed** and P0-1/P0-2 were only partially fixed. The four named residuals listed here are now closed, and one of them turned out to conceal a pre-existing correctness defect. Kept verbatim for provenance; read the 2026-08-04 entry instead. Original text:
  **Slice 1 acceptance CLOSED (2026-08-03, Fable 5 verdict on `task11/slice1-closure`):** all five GPT 5.6 Pro P0s map to commits + red→green tests; during-Task-11 backlog done; gates on the closure HEAD: ruff clean, mypy clean, pytest `2178 passed / 21 skipped / 5 xfailed`. Defaults untouched (`engine=legacy`, `max_tier=0`) — Tier 1 remains flag-off; rollout is Task 12. Named residuals: caller-supplied `target_bbox` shape on `/Rotate 90/270` pages (WS-D fixed only the fallback path); `binding.origin_page` maps through `transformation_matrix` without `rotation_matrix`; `growth_outside_page` reason string not declared as a `RejectReason` constant; View finalize token read has no dedicated GUI assertion. Full amendment in `plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md`.
- [x] **Slice 1 acceptance GENUINELY CLOSED (2026-08-04, `task11/slice1-closure`, Opus-5-orchestrated serial workflows; supersedes the 08-03 entry above).** The 08-03 closure was re-verified adversarially instead of trusted — an independent read-only pass was tasked with *refuting* each of the five P0 fixes on the closure HEAD, and it refuted three of them.
  - **What the re-verification found.** P0-4 (growth outside page) and P0-5 (verifier-exception revert) confirmed fixed and non-vacuous. **P0-3 NOT fixed**: a growth zone painted solid black by a shading inside a Form XObject was still accepted — the occupancy checks are a mechanism blocklist that cannot see into an XObject, and the background-reference gate added alongside them was *inert*, sampling inside the very band it was proving (monkeypatching every occupancy gate to a no-op left all five growth tests green). **P0-1 partial**: the cached-candidate commit path bypassed the style/geometry policy gates, so a drag accompanying an edit was silently discarded (UI-reachable), and the token test was vacuous. **P0-2 partial**: preview's V0e certificate was a tautology (`page_count` compared against itself on the post-patch document) and the Tier 1 font-resource proof was absent from preview.
  - **Fixes (F1–F4, each Red-light first, in the working tree of this commit).** F1 — growth proof rebuilt as a background-*surface* proof (`background_reference_points` disjoint from the widened halo, `_target_background_rgb`'s strict-majority + ink-visibility rule, `_reference_confirms_background`); `_target_tail_reference_rgb` and its fail-open median deleted; occupancy gates demoted to early-outs and the raster proof pinned standing alone with them neutered; `count_growth_zone_glyphs` foreign-overhang blind spot fixed. F2 — cached-candidate branch refuses on `style_overrides.changed` / `new_rect` and falls through to a fresh prepare, re-runs `find_pages_sharing_content_stream` pre-commit, and the controller caches only after the PNG decodes. F3 — `PageState.page_count` captured pre-patch, real per-session KEEP round trip (`_live_keep_round_trip`, one `tobytes` shared by probe and snapshot), `reopen_probe_ok` fail-closed, preview runs `build_tier1_font_outcome`. F4 — live `verify_fn` wrapped in `except BaseException` with revert + re-raise, and a failing revert chains both errors.
  - **The four named residuals are closed, and one hid a real defect.** `RejectReason.GROWTH_OUTSIDE_PAGE` declared (`dto.py:62`), `getattr` fallbacks removed. Rotation parity: `inspect._origin_in_page_space` now composes `rotation_matrix` (Defect A); the caller-supplied `target_bbox` was unconverted dict-space geometry, fixed by `_dict_space_to_visual` at the model boundary (Defect B); **and Defect C, pre-existing and not previously suspected — V0c/V0d compared dict-space rawdict geometry against a visual-space `target_bbox_page`, meaning no tiered commit had *ever* succeeded on a `/Rotate 90/270` page.** Found only because the residual was chased rather than deferred; pinned by `test_full_tiered_commit_succeeds_on_rotated_page[90/270]`. The GUI finalize-token assertion is added and sensitivity-proven by temporarily reintroducing the WS-A bug.
  - **Gates on this tree:** `ruff check .` clean; `mypy model/ utils/` clean (47 files); pytest **2,219 passed / 21 skipped / 5 xfailed / 0 failed**, run **chunked** in four alphabetical parts (402 + 871 + 323 + 623, every chunk exit 0) — a single whole-suite invocation hangs at PySide6 interpreter teardown in this venv, pre-existing and unrelated (see PITFALLS). This is a post-Phase-2 run, deliberately not the Phase 1c number: Phase 2 reshaped `_Tier0Target` and added 365 lines to `pdf_text_edit.py`, and this repo has a recorded pitfall where that class of change breaks `__new__`-built test doubles in a way targeted runs miss. One intermittent flake observed and not reproduced: `test_multi_tab_plan.py::test_05_search_state_restored_per_tab` (green in isolation and on re-run; unrelated tab/search state).
  - **Defaults untouched** — `engine=legacy`, `max_tier=0`, `preview=legacy`, `telemetry=off`. This is acceptance, not rollout.
  - **Still outstanding in Task 11 (not skipped for time — gated by the plan's own rule):** the runtime re-measure against the 2026-08-01 baseline, and Steps 1–6 horizontal Latin layout. The plan's constraint governs: *no layout expansion until Slice 1 preview is responsive*, so the perf gate must run first and layout cannot start ahead of it.

### After Task 11 (Task 12 scope additions)
> **Plan:** `plans/2026-08-12-task12-engine-hardening.md` — evidence-driven P0 reordering (2026-08-12 verification campaign): P0-A replay-chokepoint size guard, P0-B streaming lexer, P0-C staged degrade visibility/consent (promotes T12-P1-06), P0-D CID hex-`Tj` existing-glyph slice. Whole-`TJ` simple demoted to P2 (pivot condition below **triggered**: measured <1% coverage).
- [ ] **Re-measure runtime against the pre-Task-11 baseline** (done 2026-08-01: `scripts/benchmark_text_commit_baseline.py`, numbers in the gitignored local `benchmarks/baseline-2026-08-01.json`). Known risk: `preview.py` re-runs `prepare_tier0_plan` per keystroke generation, replaying every content stream on the page and then re-reading them (`inspect.py:213-217`, `plan.py:228-229`) — a full page re-parse per keystroke on the 35,844-show file. If dense-page preview p95 regresses: cache replay/index state, eliminate the duplicate stream read, debounce or tile raster work — and do **not** expand into paragraph layout until Slice 1 is responsive
  - 2026-08-12 (Task 12 P0-A/P0-B landed): the OOM half is closed — peak RSS on a dense-page prepare is now flat (~45–75 MB; was ~133× the stream size), and pages over the 4 MiB summed budget refuse in ~15 ms with `content_stream_too_large_for_safe_replay` (legacy fallback, which never lexes). The **latency half stays open**: prepare still costs ~1.05 s per MiB of decoded stream per keystroke (measured 0.5/2/3.8 MiB → 0.53/2.1/4.1 s), so replay/index caching + duplicate-read elimination remain the fix for dense-page preview responsiveness
- [ ] **Publish coverage as a funnel, both weightings** (GPT-5.6-sol): selected edits → target resolved → source bound → encoding/glyph accepted → candidate built → preview verified → commit verified → save/reopen verified. Report per document class, and give **document-weighted alongside show-weighted** numbers so the 35,844-show file cannot define the headline. Structural eligibility is headroom, never product coverage
- [ ] **Zero-tolerance correctness gates — any one blocks rollout:** mutation after a stale/rejected prepare; changed non-target stream bytes; moved following text; changed font/resource binding without a declared outcome; raster difference outside the declared affected region; preview candidate ≠ committed candidate; a "preserved" result where verification was not evaluable; failed undo/redo/encryption/save-reopen matrix
- [ ] **Pivot conditions, agreed in advance:** D1 — if verified edit-level acceptance stays near zero outside the dominant PDF, keep it opt-in and stop quoting 15% as coverage. Slice 1 — if the composite cannot preserve following origins and outside-region pixels, stop Tier 1 transplant rather than weakening verification. Whole-array `TJ` — defer if binding survival is negligible. Paragraph layout — narrow scope rather than silently degrading fidelity if it needs ambiguous multi-show reconstruction or uncontrolled resource mutation
- [ ] **Report the Q3 ceiling decomposed, not blended:** Task 11's real ceiling is materially below the 72.79% structural figure — Identity-H stays NO-GO so `font_unsupported_encoding` (14.74%) never clears; `render_mode` (5.55%) is unaddressed by Task 11 scope; `mc_depth` (6.51%) plausibly clears via transplant inheritance. Nothing currently computes the actual ceiling; the rollout decision needs it
- [x] Task 12 as planned — **sealed 2026-08-14** (plan archived to `plans/archive/2026-08-12-task12-engine-hardening.md`; P0-A/B via PR #28, P0-C Phase 1/2 via PRs #29/#30, P0-D via PR #31, Step 7–8 cleanup via PR #32). Rollout gates remain OPEN by design: defaults are still `legacy`/`max_tier=0`, and the three corpus blockers (marked-content tolerance, rotated-Tm, replay-budget latency) move to `plans/task13-cad-binding-unlock.md` — nothing reaches a user until those gates pass

#### Task 12 named P1 defects (GPT 5.6 Pro review — register only; do not implement in Task 11)
Registered 2026-08-03 (WS-D). Each needs a red fixture before work starts:

| ID | Defect | Suggested fixture name |
|----|--------|------------------------|
| T12-P1-01 | `gs`/ExtGState font-state ignored by replay | `test_replay_tracks_extgstate_font_ops` |
| T12-P1-02 | Font registry owner identity collapses to resource-name-only | `test_font_registry_distinguishes_owner_xref` |
| T12-P1-03 | Target tofu / wrong-glyph not proven (extraction ≠ glyph outline) | `test_verify_rejects_tofu_replacement_glyph` |
| T12-P1-04 | Fingerprint dependency graph incomplete (FontFile/ExtGState/OCG/geometry/AP) | `test_page_fingerprint_covers_fontfile_extgstate_ocg_ap` |
| T12-P1-05 | Non-page stream aliasing (Form/Pattern/annot AP sharing target stream) | `test_bind_refuses_shared_form_or_ap_stream` |
| T12-P1-06 | Non-strict silent legacy fallback consent UX | ~~`test_non_strict_legacy_fallback_requires_consent`~~ **RESOLVED 2026-08-12** (P0-C phase 1 visibility + phase 2 consent, see below) |

- 2026-08-12 (Task 12 P0-C phase 1): T12-P1-06's **visibility half landed** — a
  `degraded_committed` edit now surfaces exactly one warning notice carrying the
  `fallback_chain` reason codes (incl. the P0-A guard reason verbatim), with the
  plain success toast suppressed for that edit (`test_text_commit_degrade_visibility.py`,
  13 tests after same-day adversarial verification: default-engine
  over-notification, commit-stage detail leak, cross-page-move silent gap, and
  stale-flag leak into add-textbox were all found and fixed red-first). The
  semantic fidelity gate landed as an acceptance-only harness
  (`test_scripts/semantic_fidelity_gate.py` + 7 tests) pinning the
  `outside_diff == 0` false negative; runtime enforcement is still an open plan
  §9 question. **Known, accepted gate scope limits** (low severity, documented
  in the module docstring — widen before judging real mixed-style or
  graphical-occlusion commits): the gate is extraction-based and blind to
  non-text occlusion (an opaque fill/image over a neighbor survives
  undetected); a mixed-style target region (two fonts in one edit's bbox) is
  judged only against its first character's style.
- 2026-08-12 (Task 12 P0-C phase 2): **T12-P1-06's consent half landed —
  item CLOSED.** A real tiered→legacy fallback now pauses before the legacy
  mutation via a Qt-free callback injected into `model.edit_text()`
  (`confirm_fallback`); a decline is zero-mutation
  (`EditTextResult.FALLBACK_DECLINED`), a confirm proceeds exactly as before
  Phase 2 existed (`test_text_commit_consent_flow.py`, 13 tests after
  same-day adversarial verification: a redo-reprompt-bypass bug where a
  command that won cleanly at Tier 0 could silently arm a future redo to
  skip asking, found and fixed red-first). Session-level "always allow" is
  explicitly deferred, not started. **Known, deterministic UX consequence**
  (not a bug, explicitly reviewed and endorsed): under the tiered engine,
  cross-page move's source deletion always uses an empty replacement,
  which always rejects at the Tier 0 prepare stage — so every cross-page
  move prompts for consent once the tiered engine is enabled, every time.
- 2026-08-12 (Task 12 P0-C phase 2, post-review fix — **RESOLVED**, was
  registered below as out-of-scope, promoted to a PR #30 merge blocker):
  the mode-switch success toast gated only on `TextEditFinalizeResult.
  outcome == COMMITTED` (signal emitted without raising), never the
  Controller's actual `EditTextResult` — so a user who explicitly declined
  the new consent prompt (zero mutation, no undo entry) could still see
  "文字已儲存" on the next mode switch. Fixed with
  `PDFController.consume_last_edit_result()` (pull-and-clear, mirrors
  `consume_last_edit_degraded()`); `set_mode()` now requires a pulled
  `EditTextResult.SUCCESS` before the toast can fire at all. Also closes
  the same pre-existing gap for `REJECTED_STRICT`/`TARGET_BLOCK_NOT_FOUND`.
  5 new tests (4 requested + 1 production-View-method red mirroring Phase
  1's F6 discipline) + 1 existing pin updated to assert a genuine second
  edit instead of stale mock state. Adversarial verification (workflow
  `wf_1f9461b8-4cd`) then caught 2 more (high + medium): the new
  `_last_edit_result` reset in `move_text_across_pages`/`add_textbox` was
  placed after, not before, each method's own early-return validation
  guards, so a stale `SUCCESS` from an earlier unconsumed edit could
  survive a later, unrelated interaction's guard failure. Fixed by moving
  both resets to each method's true first line; 2 more regression tests
  added.
- 2026-08-13 (Task 12 P0-D steps 1–4 — census, scope lock, fixtures, RED):
  Type0 encoding census landed (`scripts/audit_type0_census.py`, read-only,
  aggregate-only): private corpus is **100% Identity-H + CIDFontType2 +
  Identity CIDToGIDMap + readable /W + embedded** (262/262 fonts; ToUnicode
  260/262 structurally parseable — 2 use array-destination bfranges and
  fail closed under `type0_tounicode_unparseable` in v1) — v1 scope locked
  unchanged in plan §8; the §9 CMap-scope open question is RESOLVED.
  Census also surfaced the corpus-dominant INLINE `/DescendantFonts
  [<<...>>]` form (256/262, AutoCAD) that `collect_cid_encoding_evidence`
  currently rejects — implementation must handle it (see PITFALLS).
  Synthetic fixture builder (`test_scripts/type0_fixture_builder.py`) +
  red matrix (`test_scripts/test_text_commit_cid_hex_tj.py`) landed, then
  were adversarially hardened (workflow `wf_a084d864-566`, 7/7 findings
  confirmed and fixed red-first — incl. the census correction above, which
  the round's structural-validation finding forced): final state **38
  tests — 35 red / 2 fixture-sanity / 1 replay-budget pin**, every red
  failing on the pre-P0-D `undecodable_target` binding refusal. The
  `type0_*` per-gate reason codes in the test module ARE the P0-D
  contract. This partially
  addresses the Q3-ceiling item below (Identity-H NO-GO is exactly what
  P0-D lifts).
- 2026-08-13 (Task 12 P0-D steps 5–7 — implementation GREEN): after the
  user's go-ahead + 5 more red pins (explicit /Identity name, scalar
  bfrange positive, 3 more STALE_PLAN staleness pins), the CID codec
  landed: new leaf `model/text_commit/cid_fonts.py`, Type0 capabilities in
  `fonts.py` (no face; per-lookup evidence-digest revalidation),
  registry-driven Type0 binding leg + full Type0 fingerprint closure in
  `inspect.py`, per-capability planner branch with hex operand
  serialization in `plan.py`/`patch.py`/`pdf_lexer.py`, legacy
  `_parse_tounicode` fabrication fixed + inline-descendant support in
  `verify.py`. **All 43 P0-D tests green on the first run**; full suite
  2319 passed / 0 failed; ruff/mypy/import-linter clean; 3 obsolete
  Type0 pins updated (helv TextWriter → CIDFontType0 descendant, see
  PITFALLS). Acceptance funnel (`scripts/measure_type0_funnel.py`,
  aggregate-only) reported HONESTLY: 0 source-bindable shows on the
  reference corpus today — 59% of Type0 shows behind the P0-A budget
  (intact by design), 100% of the budget-eligible remainder inside
  BDC/EMC layer wrappers (`mc_depth`), 95% on rotated text matrices —
  all outside P0-D's locked scope; registered as the mc_depth/rotated-Tm
  P1 follow-ups + the §9 budget-relaxation item. The Q3-ceiling item
  below now has REAL per-condition decomposition data from the funnel.
  Rollout defaults unchanged (legacy, max_tier=0).
- 2026-08-13 (Task 12 P0-D pre-PR review round — `wf_1757a5fb-8e9`,
  plan-code-reviewer + skeptical verifier, verdict ship-with-fixes): 2
  confirmed findings fixed red-first — (1) BLOCKING: the hybrid
  indirect-array-holding-inline-descendant form was accepted by the
  capability builder but invisible to the fingerprint's canonical
  descendant fold → prepare→mutate→commit COMMITTED instead of
  STALE_PLAN; fold now keys on the resolved dict, not the arrival path.
  (2) MINOR: literal-string Identity-H `Tj` silently widened the locked
  hex-only scope; the CID plan branch now refuses non-hex operands
  (`not_single_literal_tj`) and the funnel stage is `single_hex_tj`.
  Matrix 52/52; full suite 2328/21/5/0; review follow-ups registered in
  plan §8 (perf indexes, XObject name-shadowing [pre-existing],
  cached-rejection revalidation, literal-escape canonicalization,
  odd-length code attribution, composite-component walk, ttcf offsets).
- 2026-08-14 (Task 12 sealed — Step 7–8 closure): PR #31 merged into
  `task11/slice1-closure` as a true merge commit (`d961342`, red-first
  history preserved). Step 7: `CommitOutcome.decision_chain` records the
  tier decision trail on successful tiered commits (`fallback_chain`
  stays `()` — reserved for true degrades; no by-fable port, no
  `strategy` field until a second Tier 1 strategy exists); the dead
  Track A/B reflow hook was removed after the red pin CAPTURED its
  per-edit warning + spurious status-bar override from the production
  wiring (evidence grade upgraded from agent-reported). Step 8: final
  anonymized staged funnel recorded in the archived plan §8 (the seven
  user-specified survival stages — structural family, ToUnicode-
  acceptable, replay-budget, marked-content, rotated-Tm, source-
  bindable, replacement-encodable — plus the base show counts;
  marked-content and uniform-Tm survival are now explicit funnel
  stages); PITFALLS +1 (dead-hook entry, index 264); plan `git mv`-ed
  to `plans/archive/`. Corpus-unlock follow-ups live in
  `plans/task13-cad-binding-unlock.md`.
- 2026-08-14 (Task 13 step 1 — wrapper-taxonomy census, read-only,
  aggregate-only): replay now captures marked-content wrapper EVIDENCE
  (`McWrapper` table + `ShowOp.mc_stack`, `mc_depth` semantics frozen,
  BDC/BMC oddities never set malformed); taxonomy classifier lives in
  `scripts/wrapper_taxonomy.py` (census-before-code — no admission logic
  in model); funnel gained the `mc_census` aggregate block with a
  data-policy pin test (no document strings in the report). 31-test
  red-first matrix; Codex review round fixed 2 findings red-first
  (exact-shape BDC/BMC operand parsing fail-closed; bare
  `true`/`false`/`null` retained as operands). Corpus result: of the
  10,701 mc-gated shows, **64.2% sit under pure default-visible `/OC`
  layers (admissible)**, 35.8% in the v1 `malformed_pairing` bucket; no
  nesting (depth 1 everywhere), zero semantic wrappers; only 376
  admissible shows also have uniform `Tm` + default state — Priority 2
  (rotated `Tm`) stays the bulk unlock. Recorded in the Task 13 plan §7;
  base funnel stages re-verified byte-identical to the sealed record.
- 2026-08-14 (Task 13 steps 2+3 — Priority 1 marked-content admission):
  the blanket mc gate became a fail-closed taxonomy admission
  (`model/text_commit/marked_content.py`, promoted from the census
  classifier): only default-visible pure `/OC` layer stacks admit, four
  new stable `MC_*` reject codes, splice boundary guard on new
  `McWrapper` byte spans, and the page fingerprint folds the wrapper
  evidence closure (visibility flip / properties re-point / OCG mutation
  between prepare and commit all go STALE_PLAN). 28-test red-first
  matrix (5 proof obligations pinned). Key discovery: PyMuPDF
  `get_ocgs`/rendering are a LOAD-TIME snapshot — `/OCProperties` writes
  don't refresh them; admission + fingerprint parse the SERIALIZED
  catalog instead (PITFALLS, index 266). Step-3 funnel:
  `outside_marked_content` 0 → **6,872** (census-exact), **376 shows now
  clear every plan gate** (was 0), corpus e2e sample 8/8 committed with
  reopen-extraction OK; bottleneck moves to Priority 2 rotated-Tm
  (6,444 `state:trm_not_uniform_scaled`). Adversarial round (Codex +
  serial deep-reasoner workflow) fixed 4 admits-unprovable findings
  red-first: `/D /AS` auto-states (AS-selected OCG → unprovable),
  fail-open `/BaseState` (now deref'd, exactly `/ON`/`/OFF`),
  parse-budget fold asymmetry (structured-surface fold), duplicate
  dict keys (shared parser refuses). 9 more red pins; corpus numbers
  re-verified identical after all fixes.
- 2026-08-19 (Task 13 step 4 census-before-code — rotated-TRM census,
  read-only, aggregate-only): matrix taxonomy of the 6,444 post-P1
  TRM-gate deaths (`scripts/trm_taxonomy.py` classifier — user-space
  shape of `Tm × CTM` + visual baseline direction through
  `transformation_matrix × rotation_matrix`; funnel `trm_census` block;
  70-test red-first matrix). Corpus: **6,417/6,444 uniform rotations;
  6,413/6,417 of those (99.94%) are visual quarter-turn (`right` 6,212;
  6,413/6,444 = 99.52% of all TRM-gate deaths), all on `/Rotate 270` pages, all
  P1-admitted wrapped shows; zero near-miss rounded matrices; predicted
  newly bindable 5,558 (quarter-turn) vs 5,561 (any-uniform — +3
  only)**. v1 scope LOCKED to the quarter-turn family; acceptance for
  the P2 implementation = census prediction exactly (6,413 gate /
  5,558 downstream). Adversarial round (serial 2-agent Attack→Verify)
  fixed 3 findings red-first: `near_miss` diagnostic (rounded quarter
  turns), `ABS_SCALE_FLOOR` in front of the predicted chain (mirrors
  replay's absolute `_EPS` floor), dual-scope predicted counters;
  `/Rotate` folded to a closed 0/90/180/270/`other` vocabulary. Fixture
  pitfall: PDF numbers have no exponent notation — `%g` writing
  `6.12e-17` silently voids the whole `Tm` under a real lexer. Next:
  P2-B red matrix (stable `trm_*` codes, rotated kern axis, directional
  growth proof, page-geometry staleness pins) — plan §7 step-4 record.
- 2026-08-20 (Task 13 step 4 P2-B — rotated-TRM admission red matrix,
  tests only): four new files (`test_text_commit_trm_admission` 44 red /
  1 control, `_trm_tier1_kern` 12 red / 1 control,
  `_trm_growth_directions` 32 red, `_trm_page_geometry` 7 red /
  3 controls — **95 red confirmed before any implementation**) pin SEVEN
  literal `trm_*` codes with fixed gate precedence (absolute
  `trm_scale_below_floor` promoted to its own code), relative-tolerance
  boundaries at three scales, the full /Rotate × quarter-turn-Tm visual
  direction truth table, the new `model/text_commit/transforms.py`
  contract (census `scripts/trm_taxonomy.py` must delegate; no-drift
  probe grid), rotation-invariant text-space kern with successor-origin
  preservation in both visual coordinates (kern-gap `[-2000] TJ`
  fixture), four-direction growth gates through one shared
  `growth_direction`, and prepare→mutate /Rotate //UserUnit/CropBox/
  MediaBox (incl. raw-xref and page-tree-inherited) → `STALE_PLAN` pins.
  Contract details in plan §7. Next: quarter-turn admission
  implementation; acceptance = census prediction exactly (6,413 gate /
  5,558 downstream, SET identity not just counts).
- 2026-08-20 (Task 13 step 4 P2 — quarter-turn admission
  IMPLEMENTATION): red matrix 95→green (104/104 incl. 4 new F3
  invariant pins); NEW `model/text_commit/transforms.py` single source
  (census `scripts/trm_taxonomy.py` delegates); binding gate =
  `admission_verdict` with seven `trm_*` codes; plan geometry rides
  `map_text_quad_to_visual` + directional `_grown_verify_bbox` +
  `PreparedEdit.growth_direction`; verify growth gates direction-aware
  with dict-space conversion (PITFALLS 269: `get_drawings`/
  `get_image_rects` speak UNROTATED page space); fingerprint folds
  resolved page geometry + live visual matrices; funnel gate mirrors
  production with per-code `state:trm_*` slugs + SET-identity
  acceptance block. Replaced-contract pins updated (structural gates,
  replay, audit, census funnel test). Full per-file sweep green.
  Registered follow-up: `scripts/measure_tier_funnel.py` (legacy
  simple-font tier funnel) still models the OLD blanket TRM gate —
  update when that funnel is next used.
- 2026-08-20 (Task 13 step 4 P2 — implementation review round,
  wf_3cb287ec Attack + hand verification after the Verify agent hit the
  session limit): 5 findings — F2 CONFIRMED fixed red-first (admission
  gate now skips replay-uniform shows except `trm_non_finite`, keeping
  the pre-P2 admitted boundary sliver admitted and re-aligning
  funnel↔production); F4 CONFIRMED fixed red-first (fingerprint folds
  numeric `/UserUnit` canonically — MuPDF re-prints integer-valued
  reals as ints, PITFALLS 270); F1 documented (funnel acceptance sets
  are one-directional predicted ⊆ production — fail-loud only); F3
  accepted as documented (~1 ulp axis-path drift, fail-closed); F5
  docstrings corrected (verify re-derives the growth edge; slug is
  token-bound, not threaded). Details in plan §7.
- 2026-08-20 (Task 13 step 5 — funnel acceptance, corpus, --no-e2e):
  SET-identity acceptance PASS at the sealed tip — gate 6,413
  predicted == 6,413 production, downstream 5,558 == 5,558, both
  symmetric differences 0, membership exact; census counters identical
  to the pre-implementation baseline; blanket slug decomposes exactly
  (6,444 = 6,413 admitted + 27 reflected + 4 not-quarter-turn).
  Corpus e2e pass deferred (optional per step-4 advisory — ride the
  rollout-gate work). P2 slice ready for its PR (base
  task11/slice1-closure) — do not push/open until instructed.
  **P2 MERGED 2026-08-20**: PR #34 → `task11/slice1-closure` @ 137a50b,
  all 9 CI checks green, 6 commits preserved unsquashed.
- 2026-08-21 (Task 13 step 6 first half — P3-A replay-index spike,
  branch `task13/p3-replay-indexing`, read-only, zero `model/` change):
  serial analysis round (invalidation census: pull-validation is the
  contract — four mutation classes have NO push signal; checkpoint
  contract: Shape B is necessarily a hybrid), 41-test red matrix +
  two spike prototypes + latency harness (`scripts/replay_index_spike
  .py`, `scripts/benchmark_replay_index_spike.py`), serial
  Attack→Verify review (8 findings, 4 important, all fixed — three
  were measurement-integrity defects gating the census run), corpus
  measurement DONE: **replay is ~90% of the 2.7–4.8 s per-keystroke
  cost on dense pages; honest validated warm lookups are 8–14 ms
  (page-paired prototype-lookup comparison ~310×–430×, standalone spike
  path with pull-validation included, excludes plan/verify/apply/
  render, not a production speedup — see plan §7 post-PR audit
  correction); Shape A (materialized ShowOp table) wins — Shape B
  (sparse checkpoints) REJECTED for v1 on measured memory (3.3×–6.1×
  Shape A's total retained, page-paired).**  4 MiB budget untouched; no
  persistent cache.  Scope verdict + P3-B follow-up order in
  `plans/task13-p3a-replay-index-spike.md` §7.  **PR #35 opened
  2026-08-22** against `task11/slice1-closure`; a 2026-08-22
  post-PR-audit docs-only reconciliation commit corrected the numbers
  above — see plan §7's "Post-PR claim audit correction" record for
  the full derivation. This partially
  addresses the "latency half stays open" item above: the fix is now
  measured and shaped (reuse one replay across bind→plan, then the
  per-generation Shape A table), but nothing lands in production until
  the P3-B slice.

- 2026-08-22 (Task 13 step 6 second half — **P3-B production replay
  reuse, COMPLETE**, branch `task13/p3b-replay-evidence-plumbing` cut
  from the post-PR-#35 closure merge `e71b13e`): one complete bounded
  slice — evidence seam (`model/text_commit/evidence.py`; one coherent
  stream read per prepare feeding bind + stream selection + the
  fingerprint's stream portion), retained Shape A (`ReplayEvidence`
  wraps the production `PageReplay` verbatim), lookup-time
  pull-validation (fresh read + sha256 digest compare before any reuse;
  refused/malformed/unbounded replays can never become evidence),
  renderer-owned single-slot `ReplayEvidenceCache` (engine.prepare stays
  ephemeral), 40-test red-first matrix, serial Attack->Verify review
  (4 findings R1-R4, top 3 independently CONFIRMED, all fixed), and a
  replay-count acceptance harness (`scripts/benchmark_p3b_preview_reuse
  .py`): cold = 1 replay, 30 warm keystrokes = 0 replays (30/30
  validated hits), unsignalled mutations rebuild every time, false
  hits = 0, memory bounded (entry_count pinned at 1, close releases).
  Measured on the synthetic dense page: cold prepare 11.9 s vs warm
  validated prepare p50 31 ms; warm end-to-end render p50 ~3.3 s with
  zero replays — the residual splice/verify/raster share is the next
  P3 lever, explicitly NOT claimed solved. Fences held: 4 MiB budget
  untouched, no admission widening, no persistent/document-wide cache,
  rollout defaults unchanged. Record: `plans/task13-p3b-replay-reuse.md`.
  **Follow-up (from review R1, pre-existing, NOT a P3-B regression):**
  `DocumentFontRegistry` serves cached simple-font capabilities without
  per-lookup revalidation until `bump_generation` (Type0 already
  digest-revalidates) — extend the Type0-style evidence-digest check to
  simple-font cache hits on the engine path; see PITFALLS "Simple-font
  capabilities are served stale within a registry generation".
  **→ CLOSED 2026-08-27** by the Task 13 revalidation slice (entry below).

- [x] 2026-08-27 (Task 13 — **simple-font capability pull-revalidation,
  COMPLETE**, branch `task13/simple-font-capability-revalidation` cut from
  `task11/slice1-closure@0578866`; sequenced BEFORE P3-D so the known
  correctness hole is sealed before the interpretation pipeline moves):
  every `FontCapability` now carries a same-document `evidence_digest`
  (`compare=False`); `compute_font_evidence_digest` dispatches on the
  `get_fonts` entry's subtype (Type0 → `compute_cid_evidence_digest`, else
  the new `compute_simple_font_evidence_digest`: font-dict keys, indirect
  `/Encoding`/`/Widths`/`/FirstChar`/`/LastChar`/`/FontDescriptor`
  targets, `FontDescriptor/Flags`, raw `FontFile*` bytes; inline xref-0
  dict → constant); `page_capabilities` re-derives it on EVERY lookup
  before the cache probe and rebuilds on mismatch, digest taken BEFORE the
  build. Subtype dispatch also closes the same-class hole for a REJECTED
  Type0 (`cid is None`). Red-light first: 19/21 Red in
  `test_scripts/test_text_commit_font_revalidation.py`, then Green.
  Ultracode refute-first review (3 lenses, 2 important findings both
  CONFIRMED by independent probes and fixed pre-commit, each Red-first):
  F1 — the digest must also fold the MuPDF-RESOLVED `get_fonts` entry
  fields (ext/subtype/basefont/encoding), or an indirect `/BaseFont`,
  `/Subtype` or `/BaseEncoding` target rewrite serves stale (Helvetica face
  served for a font renamed to Wingdings); F2 — `capability(page, name)`
  routed through the whole-page map, O(K·N) digests per prepare (98-font
  page 1.45 s → 10.3 s); now resolves the single matching entry (98-font
  page 340 ms, small pages within noise). Minor closed: `FontFile*` stream
  dict folded alongside raw bytes (`/Filter` rewrite). Final: 27 tests in
  the new file, 147 Green across fonts/widths/cid/replay suites, full
  suite green. Fenced OUT: P3-D DL/TP reuse, `fitz.TOOLS` flag governance,
  dense-CJK growth admission, rollout. Record:
  `plans/task13-simple-font-capability-revalidation.md`.
  **Follow-up correction (2026-08-27, characterization guard-pins):** the
  originally recorded `inspect._update_font_dependencies` analogous gap is
  REFUTED. `page_fingerprint()` has folded the complete MuPDF-resolved
  `get_fonts(full=True)` entry since its initial implementation, before its
  separate object-dependency closure. Three Green-from-first-run pins cover
  indirect `/BaseFont`, `/Subtype`, and inline `/BaseEncoding` target
  rewrites: the live fingerprint is KEEP-round-trip stable before mutation,
  then changes and forces `commit == STALE_PLAN` with zero stream mutation.
  These are characterization guards, not a red-first production fix.
  **→ CLOSED 2026-08-27** by
  `task13/cid-stream-evidence-attestation`: `compute_cid_evidence_digest`
  now folds the builder-visible decoded bytes returned by the same
  `_stream_bytes()` helper the CID builder uses for `FontFile2`,
  `CIDToGIDMap`, and `ToUnicode`. Six red pins cover direct and indirect
  `/Filter` target rewrites with byte-identical raw storage; unreadable
  post-mutation evidence rebuilds to a stable fail-closed rejection. An
  unchanged control reuses the identical capability, and a structural
  performance guard permits exactly one decoded read per evidence stream
  on a warm single-resource hit. Probe p50: 0.011 ms ToUnicode, 0.135 ms
  CIDToGIDMap, 3.617 ms FontFile2; no raw+decoded double hashing.

- 2026-08-23 (Task 13 step 6 third pass — **P3-C preview post-prepare
  latency, COMPLETE**, branch `task13/p3c-preview-postprepare-latency`
  cut from the post-PR-#36 closure merge `f57f590`): the P3-B-named
  residual lever, one complete census->implementation->acceptance
  slice. Census phase-attributed warm `PlanPreviewRenderer.render()`
  on the dense synthetic page: `apply_patchset` (38.7%) +
  `AppliedPatch.revert` (36.8%) = 75.5% of render time, each exactly
  one `Document.update_stream()` call on the ~2.5 MiB content stream;
  root-caused to FlateDecode compression (`compress=1` default, ~540x
  cost vs `compress=0` on an isolated 2.6 MiB stream). Fix: both
  gained a `compress: bool = True` keyword (default preserves every
  existing caller); `PlanPreviewRenderer` alone passes `False` at both
  call sites, since its scratch is never saved or `tobytes()`'d — the
  live commit path (`TieredCommitEngine.commit`) is untouched. 16-test
  red-first matrix, deep-reasoner adversarial review (6 findings
  F1-F6, all independently re-verified, all fixed), and a
  compress-count acceptance harness
  (`scripts/benchmark_p3c_postprepare_latency.py`): every preview
  keystroke = 0 compressed / 2 uncompressed `update_stream` calls,
  live commit keeps its existing >=1 compressed / 0 uncompressed calls
  unchanged (regression guard), memory bounded structurally (stored
  representation size identical across 100 keystrokes — NOT
  `tracemalloc`, which is blind to PyMuPDF's C-side storage, see
  PITFALLS). Measured: warm render p50 874 ms -> 267 ms (~3.3x) on the
  same dense corpus; cold render (replay-dominated) 5.2 s. Fences
  held: no admission/budget/plan-semantics/rollout-default change,
  live document write path untouched. Record:
  `plans/task13-p3c-preview-postprepare-latency.md`. **Named next
  lever (not solved here):** three `page.get_pixmap()` calls + six
  `page.get_fonts(full=True)` scans per keystroke (`capture_page_state`
  + `verify` + the final preview raster), ~92% of the post-fix total.

- 2026-08-23 (**P3-C bridge round, COMPLETE** — same branch, 4 more
  commits `4012114`..`docs`): closed the gaps between the shipped slice
  and the fuller P3-C spec. (1) Extended matrix 16->29 tests: the
  compress flag proven observationally invisible through the REAL
  `render()` for Tier 1 kern+growth, Type0/CID Tier 0/1, visible /OC,
  rotated quarter-turn Tm; plus the suite's FIRST forced V0a-V0d
  verification failures (previously only positively pinned) and
  preview-path injected-failure/raising-verifier revert pins — all
  under `compress=False`, each control leg proving its monkeypatch
  engaged. (2) Committed dual-mode stage census
  (`scripts/benchmark_p3c_stage_census.py`): same-process old-vs-new
  per-stage p50/p95, full primitive counter table, small-page control
  (no reproducible regression), replay contract re-asserted
  (cold=1/warm=0), token identity between modes, working-set snapshots;
  dense warm p50 2,715.8->538.4 ms same-process (5.04x vs predicted
  4.75x — ratio reproduced, absolutes drift with machine state,
  vindicating counts-not-milliseconds). (3) Complete per-file pytest
  sweep at `3c502b4`: 227 files, 0 FAIL. (4) Second adversarial round
  (workflow attack -> skeptical verify, serial): 6 findings B-F1..B-F6
  all CONFIRMED and fixed (control-leg engagement asserts + mutation-red
  proof; plan-record overclaims corrected; nearest-rank p95; machine-
  neutral wording). **Next-lever REFINED by the census:** six
  independent content-stream interpretations per keystroke (3
  DisplayList + 3 TextPage builds inside PyMuPDF's own
  `get_pixmap`/`get_text`, ~99 ms each, none reused — `get_fonts` is
  latency-trivial at ~1.5 ms total, correcting the earlier framing);
  the one-post-patch-DisplayList+TextPage reuse design is the P3-D
  candidate (plan §6c/§8). **Still OPEN from the spec:** the private
  real-PDF corpus census leg (requires a locally provided corpus,
  absent by default) and repo-wide `ruff format --check` (fails on 302
  pre-existing files incl. pre-P3-C ones; the enforced gate is `ruff
  check`, which is clean). `lint-imports` verified 4/4 KEPT locally.

- 2026-08-25 (**P3-C PR #37 CI follow-up, fixed** — same branch, one
  more commit): the single-process CI suite failed
  `test_preview_render_type0_cid_tier1_identical_and_uncompressed`
  (`growth_region_not_blank`) on both platforms (Windows blocking,
  Ubuntu advisory) while every isolated and per-file run was green.
  Proven root cause, not a compress regression: `PDFModel.__init__`
  sets the process-global `fitz.TOOLS.set_small_glyph_heights(True)` in
  the first collected test
  (`test_1pdf_horizontal.py::test_horizontal_edit_and_verify`), the
  caller-supplied text-extraction bbox (the app's own path) becomes a
  fontsize-tall 0.8/-0.2 em box in which the dense-CJK target has no
  strict-majority background colour, and the Tier 1 growth proof
  rejects the `+1 em` candidate identically under `compress=False` and
  forced `compress=True` (a gate on the PageState captured before
  apply, so no compressed byte can influence it). Fix: the Type0/CID Tier 1 pin now uses `REPLACEMENT_SHORTER`
  (Tier 1, `has_ink_growth is False` asserted); growth parity stays on
  the simple-font Tier 1 pin. Production growth proof untouched;
  PITFALLS entry added. **New follow-ups (neither P3-C nor P3-D):**
  (a) suite hygiene — decide whether a `conftest.py` autouse guard
  should snapshot/restore PyMuPDF `TOOLS` globals per test, or whether
  tests should pin the flag explicitly (either changes the process
  state hundreds of later tests currently run under — needs its own
  red matrix first); (b) admission gap — under the app's own
  `set_small_glyph_heights(True)`, Tier 1 growth candidates whose
  non-background pixels (ink plus anti-aliased fringe) reach ≥ 50 % of
  the fontsize-tall 0.8/-0.2 em extraction bbox (dense CJK) are
  fail-closed rejected by `_target_background_rgb` on BOTH app paths
  (preview `pdf_controller.py` and commit `pdf_text_edit.py` pass
  `target_bbox=target.bbox`), while `target_bbox=None` callers are
  admitted through plan.py's flag-immune 1.35 em metric quad (why the
  `test_text_commit_trm_*` growth tests stayed green in the same run);
  smallest candidate remedy: sample the majority colour over the
  planner's metric-quad height (or the halo ring) instead of the
  extraction bbox, behind a corpus-backed red matrix.

- 2026-08-28 (Task 13 step 6 fourth pass — **P3-D interpretation reuse,
  COMPLETE**, branch `task13/p3d-interpretation-reuse`): introduced a
  mutation-window-scoped `PageInterpretation` and a renderer-owned one-slot
  `PreStateBaselineCache`. Final hard counts reduced the legacy six page
  interpretations to Stage-A 3/4, Stage-B cold 2/4, and Stage-B warm 1/2
  (unrotated/rotated); each corpus recorded one miss, one store, and 30 hits.
  PNG bytes, plan token, rejection/verifier result, clip, scale, new rect, and
  prepared-plan identity matched the legacy control. The final gate rerun's
  dense-unrotated Stage-A capture share was 0.503762 (GO threshold 0.20);
  retained Python memory stayed
  within the structural bounds. Live commit behavior and rollout defaults are
  unchanged. Record: `plans/archive/task13-p3d-interpretation-reuse.md`.
  **Registered follow-ups — not implemented in P3-D:** (a) prove whether
  `_span_origins` can derive its tuple from the already materialized rawdict;
  (b) prove node rect/quad coverage before replacing full-page interpretation
  with a halo scissor; (c) investigate reuse around `get_drawings()` tracing;
  (d) reduce rawdict extraction-shape/Python-dict construction cost; (e)
  investigate once-per-accept interpretation reuse in the live engine; (f)
  define complete snapshot/reset governance for the process-global
  `fitz.TOOLS` small-glyph, quad-correction, and anti-alias settings.
- 2026-08-29 (Task 13 — **P3-D manual smoke FAIL → rotated-page text-edit
  geometry fix**, same branch): the rotated GUI smoke
  (`docs/history/reports/2026-08-29-p3d-manual-smoke-attempt.md`) exposed
  three pre-existing defects, none introduced by P3-D: the model's public
  text-geometry surface was unrotated dict space while the View is displayed
  space (outlines/hover/click/editor all landed at the unrotated location on
  every `/Rotate 90/270` page — GUI text editing there had never worked);
  an untouched session reported a font override (`"Helvetica"` vs the UI alias
  `"helv"`) and lost the Tier 0 plan; and the plan-preview hook refused rotated
  editors. Fixed at the model boundary (`model/geometry.py` chokepoints,
  `PDFModel` displayed-space wrappers, `edit_text`/`derive_tier0_preview_target`
  entry derotation, legacy insert bounds = `unrotated_page_rect`) plus view
  changes (style-override comparison through `_font_alias`, rotated
  plan-raster + frozen-first-frame counter-rotation through one shared
  `PROXY_COUNTER_ROTATION` table incl. 180°). An adversarial review round
  found and fixed three more red-first (180° frozen frame, font
  pick-and-revert override, legacy clamps vs displayed `page.rect`). Record:
  `plans/archive/task13-rotated-page-text-edit-geometry.md`. **Manual retest
  still owed** (interactive only): the smoke procedure in the report.
  **Registered follow-ups (pre-existing, rotated-*text* proxies too):** (a)
  drag-end rect derivation (`pdf_view.py` mouseRelease ~4979-4991) uses the
  proxy's top-left for 90/180/270 proxies whose anchor is
  `(x1,y0)`/`(x1,y1)`/`(x0,y1)`, so a dragged rotated editor reports an offset
  `new_rect` (derive it from `proxy.sceneBoundingRect()` instead; plain
  click-then-Apply is unaffected, `new_rect` stays None); (b)
  `_clamp_editor_pos_to_page` clamps with unrotated widget dims for rotated
  proxies; (c) the add-text editor on a `/Rotate` page is drawn at
  `page_rotation` while `add_textbox` inserts with `rotate=page.rotation` in
  unrotated space, so the committed glyphs' on-screen orientation differs from
  the editor's — determine the real orientation with the pixmap-ink oracle and
  pass that rotation from `_create_add_text_editor_at_scene`; (d) the plan
  preview coordinator rasterises `clip | effective_verify_bbox` but the view
  paints the decoded PNG at local (0, 0) and discards `result.clip_rect`, so
  baseline-direction growth shifts the preview (rotation-independent; crop /
  offset by `result.clip_rect` in the controller); (e) the three older
  rotation helpers (`_dict_space_to_visual`, annotation derotate/rotate,
  `add_textbox`) should route through `model/geometry` thin wrappers; (f) the
  model geometry surface now round-trips through MuPDF float32 rects/points at
  `/Rotate 0` too (no exact-equality test exists; short-circuit at rotation 0
  if one ever needs byte identity); (g) `PDFModel._normalize_text_for_compare`
  is still missing (below).

### Task 14 P4 — Type0 hit-rate (census-gated)

- 2026-08-30 (Task 14 P4 candidate census, review-corrected): the
  replacement-encodable funnel's 100% value is only a self-proxy. Among
  already-bindable `doc_0` shows, just **15.5%** of the document's
  corpus-union characters are encodable in that show's font today (CAD seed
  10.3%; fullwidth digits/punctuation 4.1%), so a character copied from
  elsewhere in the drawing fails the encoding gate about 85% of the time.
  Commit 3b's all-face proof found 48 strict exact and 95 shared-program
  `doc_0` fonts. The shared-program rule admits byte-identical TTC
  `glyf`/`loca`/`hmtx` programs only when every face agrees on the requested
  character's GID. Those 143 eligible fonts contain 4,292 bindable shows.
  The Commit 3c Codex finding is closed: shared-program admission now also
  pins `head`/`hhea` interpretation fields, fails closed over every unexcluded
  table's presence and bytes, and requires per-GID glyph/metric agreement;
  the 2026-08-31 census numbers were unchanged.
  Unit B is 3,326.47 augmentation vs 127.00 hscale vs 12.29 whole-`TJ`
  show-equivalents, so augmentation leads hscale by 26× on value.
  The strict unique-face row remains 0 and the unrestricted upper bound
  remains 5,006.08. The mutation-premise matrix passed serializer, descendant
  rewrite, KEEP reopen, raster identity, multi-object revert, cross-page
  staleness, and AES-256 gates. Cache visibility is the blocker: in-place and
  descriptor-repoint/new-xref rewrites stay invisible; reopen works; only the
  process-global `fitz.TOOLS.store_shrink(100)` refreshes the same handle, and
  the single-threaded probe cannot prove worker exclusion during that flush.
  **Safety is NO-GO, so Priority GO is hscale.** If coordinator-level
  exclusion or a non-global same-handle refresh later flips Safety, the same
  corpus numbers make augmentation the pick. The 1,642 bindable shows on
  unproven fonts remain a candidate-list item for P4-B.
  Separately, hscale leads Unit A at 877 newly bindable shows versus whole-`TJ`
  42. Relaxing the unchanged 4 MiB replay budget exposes a **16,549**-show
  stage-loss upper bound, but those shows can still fail downstream gates, so
  the bound belongs to neither Unit A nor Unit B. Budget relaxation stays the
  §9 item (`TODOS.md:473`): its latency half remains open. Record:
  `plans/task14-type0-augmentation-census.md` §7.
  Fresh artifacts persist zero malformed-replay pages/shows, zero shared-
  content-stream pages/shows, and zero unreadable-content pages in both corpus
  documents. The census rejects all three conditions structurally, uses a
  one-pass fail-closed stream-owner index, and closes ToUnicode reject details
  over the 15 code-authored literals plus `missing_detail`.
  P2 confirms `xref_set_key(..., "DescendantFonts/0/DW", ...)` destroys the
  array, so descendant mutation must use parse → modify → serialize. P9
  confirms an earlier Tier 0 command's undo refuses stale after font mutation
  and leaves the document unchanged.

#### Pre-existing defects discovered incidentally during P0-C (register only; not in P0-C's scope)

- `PDFModel` has no `_normalize_text_for_compare` method. Referenced by
  `controller/pdf_controller.py`'s `_resolve_cross_page_move_source_span_id`
  (its ambiguous-multi-candidate ranking path, reached when
  `find_overlapping_runs` returns more than one span for a cross-page
  move's source rect) and by `test_scripts/test_track_ab_model_regressions.py:28`.
  Found 2026-08-12 while writing P0-C phase 1's cross-page-move test;
  worked around there with a single-token target text (word-boundary
  tokenization guarantees exactly one candidate span, avoiding the buggy
  path) rather than fixed, per the standing scope-freeze discipline. Still
  open — unrelated to the toast-gating fix above.
