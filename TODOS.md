# TODOS

## Deferred from prior campaigns

### R5-01 / Codex F6 (from post-campaign repair, 2026-06-21)

- [ ] **R5-01 fileless print path.** Eliminate the transient plaintext temp during the driver call (page-streamed
  raster or password-aware driver boundary) + avoid the duplicate full-document copies. Large redesign.
- [ ] **Codex F6 — in-flight worker decrypted-bytes lifetime.** `cancel_ocr`/`_cancel_search` are non-blocking by
  design, so a search/OCR worker can hold its snapshot `_doc_bytes` briefly after a tab closes. A blocking join
  would regress responsiveness (intentional non-blocking cancel); the live doc is decrypted in RAM regardless, and
  the controller's long-lived cache is already cleared on close (R4-03). Revisit only if a worker can be made to
  clear its payload race-free on cancel.

### Audit remediation deferrals (2026-06-10)

- [~] **R4.1 — Overlay render cache: EVALUATED → DEFERRED.** Disproportionate risk for a watermark-only conditional gain. Full rationale: `plans/refactor-R4-performance-deferrals.md`. Revisit only if watermarked scroll-after-edit latency becomes a measured bottleneck.
- [ ] **MVC routing of merge-dialog page counting.** The view-layer `fitz.open()` calls in `pdf_view.py` (merge dialog page-count probe) should route through a controller/model utility to respect layer boundaries.

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

- [ ] **Open follow-up:** `gate_anchor.py`'s own maintenance doc says "document the change in
  `plans/2026-05-05-no-jump-editor-geometry-gate.md`" — that file has never existed in git (a pre-existing gap
  predating this campaign, not introduced by it). Documented here instead. If a future no-jump-style campaign
  revives that plan file, reconcile this history into it.

## Open -- Layer boundary violations (S4 import-linter, added 2026-07-02)

`lint-imports` (`.github/workflows/ci.yml` → `layer-boundaries`) is now split: `model-no-controller-view` and
`model-no-qt` are **blocking** (no violations). The `utils-no-controller-view-model` and `view-no-model` contracts
below run advisory-only until these clear, then flip to blocking too:

- [ ] **`utils/preferences.py` imports `model.tools.ocr_types`.** Utils importing Model inverts the intended
  bottom-of-stack position of `utils/`. Either move `ocr_types` to `utils/` (if it's really a shared type) or move
  the OCR preference logic that needs it into `controller/`/`model/`.
- [ ] **`utils/helpers.py` imports `PySide6.QtWidgets.QMessageBox`.** Utils showing a message box directly bypasses
  the View layer; callers should raise/return and let View show the dialog.
- [ ] **View importing Model directly** (`view/dialogs/audit.py`, `view/dialogs/ocr.py`, `view/dialogs/optimize.py`,
  `view/object_selection.py`, `view/pdf_view.py`, `view/text_editing.py`). Most are DTO/type imports (arguably
  acceptable — request/response dataclasses aren't mutation calls), but `view/dialogs/optimize.py` calling
  `PDFModel.preset_optimize_options()` and `view/dialogs/ocr.py` calling `is_device_available()` are real boundary
  crossings that should route through `controller/`. Triage: split the DTO imports (allow) from the direct calls
  (route through controller) before flipping the CI contract to blocking.

## Open -- Security dependency hygiene (from F2/F9 patch work; updated 2026-06-05)

See `docs/history/reports/0607-implementation-notes.md` for the full F1-F9 patch log.

### BLOCKED — transformers CVE (investigated 2026-06-05)

`surya-ocr` transitively pulls `transformers 4.57.6` (two CVEs: CVE-2026-1839 fixed only in 5.x, PYSEC-2025-217 no fix). No surya release requires or is validated against transformers 5.x. Do NOT bump. See TODOS-archive for full investigation table.

### Pillow floor vs. surya-ocr

Reconciled via file split: `surya-ocr` + `torch` in `ocr-requirements.txt`; core image features floor at `Pillow>=12.2.0` in `optional-requirements.txt`. Locked by `test_security_pillow_floor.py` and `test_security_ocr_requirements.py`.

### Deployment env remediation

- [ ] **Upgrade the build-env (`.venv`) Pillow to >=12.2.0 and rebuild.** The PyInstaller build env still has Pillow 12.1.1 (5 image-parser CVEs). The declared floor is already 12.2.0 for fresh installs; the existing `.venv` needs a pip upgrade + PyInstaller rebuild.
- [ ] **Refresh build tooling** (`pip 21.2.3`, `setuptools 57.4.0`) in the `.venv` — old but not bundled, low risk; update for build hygiene.

### Remaining open items

- [ ] **Revisit the OCR stack when surya-ocr relaxes its pins.** When a surya release ships `pillow>=12.2` support and a transformers floor in the 5.x line, merge `ocr-requirements.txt` back and drop the residual-risk note.
- [ ] **F9 bundle distribution** — ship a vetted weights bundle and populate `WEIGHTS_MANIFEST` with its published SHA256 digests so `PDF_EDITOR_OCR_WEIGHTS_DIR` works out of the box. See `docs/ocr-weights-verification.md`.

## Future Object Follow-Ups

- Any remaining object-manipulation polish that needs its own child plan.
- [ ] **Delete app-image: drop `PDF_REDACT_IMAGE_REMOVE`** (`model/pdf_model.py:2204-2213`)
  - Move/rotate were converted in commit `c099b28` to rewrite placements via
    `_rewrite_native_image_matrix`, preserving overlapping neighbors.
  - Delete still calls `page.add_redact_annot(old_rect); page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)`,
    which can remove overlapping neighbor images and is inconsistent with the new behavior.
  - Approach: reuse `_find_app_image_invocation` + a native-image "remove invocation" helper
    (parallel to `_remove_native_image_invocation` at `model/pdf_model.py:2196`) so only the
    targeted placement is stripped.
  - Add regression: two overlapping app-images, delete one, assert the other survives
    (mirror `test_move_overlapping_app_images_both_survive` in `test_scripts/test_image_objects_model.py:180`).

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
