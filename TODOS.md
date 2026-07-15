# TODOS

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

## M3 — Performance Baseline (captured 2026-07-15, pre-tranche-3.0)

Full commands, method, and values: `plans/render-offload.md`.

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
- [x] Capture the pre-M3 baseline and seed `plans/render-offload.md`.
- [ ] Re-run immediately before tranche 3.6 and publish before/after evidence.
