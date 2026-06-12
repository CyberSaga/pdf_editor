# TODOS

## Audit remediation (2026-06-10 two-round audit)

- [x] **Phase 1 (2026-06-12) — Search snapshot restore / print snapshot funnel:** search workers now read private snapshot bytes captured on the GUI thread, completed tab-search results are preserved per tab across switches, and only in-flight partial searches are cleared on cancel; print submission captures snapshot bytes before the helper thread starts. Tests: `test_scripts/test_search_worker_flow.py`, `test_scripts/test_multi_tab_plan.py::test_05_search_state_restored_per_tab`, `test_scripts/test_print_controller_flow.py`.
- [x] **Phase 2 (2026-06-12) — Watermark double-stamp fix:** `WatermarkTool.needs_page_overlay(...)` now returns `False` for `purpose == "print"`, leaving the helper subprocess as the only print stamping path; helper heartbeat output now refreshes runner activity so heartbeat lines do not trip the stall watchdog. Tests: `test_scripts/test_print_snapshot_path.py`, `test_scripts/test_print_subprocess_runner.py`.
- [x] **Phase 3 (2026-06-12) — OCR worker parity:** `_OcrWorker` now receives GUI-thread snapshot bytes, `OcrTool.ocr_pages(..., doc=...)` can render from an override document/bytes, every OCR signal carries a generation token (`cancel_ocr` bumps it, handlers drop stale gens) and `page_done` is additionally dropped when the active session no longer matches the captured `_ocr_session_id`; OCR cancellation is non-blocking from session-switch/close chokepoints. Tests: `test_scripts/test_ocr_controller_flow.py`.
- [ ] **Flaky test under load:** `test_scripts/test_print_subprocess_runner.py::test_runner_heartbeat_events_prevent_false_stall` intermittently fails in full-suite runs (timing-sensitive stall watchdog vs CPU contention) but passes in isolation — widen its timing margins or fake the clock.

- [x] **Phase 0 — Restore the Gate:** polluter = stylesheet leak in `test_main_startup_behavior.py`; fixed via cleanup + widget QSS override + conftest fixture (7 order-dependent failures in `test_no_jump_editor_geometry.py` eliminated).
- [x] **Phase 1 — Linearize Capability Gate + Error Wrapping:** dead PyMuPDF `linear=1` fallback deleted (fail-fast `PdfOptimizeError`); `optimize_capabilities()` runtime probe gates the dialog's linearize/object-streams checkboxes; double 「最佳化 PDF 失敗:」 prefix fixed; `pikepdf>=8.0` in optional-requirements.txt and installed into `.venv`.
- [x] **Phase 2 — Chokepoint Guards (OOM / Logic-Bypass):** all six items landed (2026-06-10): central `_safe_render_scale` clamp in `ToolManager.render_page_pixmap` (strict-xfail red-light flipped green, marker removed); shared `_MIN/_MAX_VIEW_ZOOM` constants across wheel/pinch/combo; `_guard_foreign_doc` chokepoint (size/pages/encryption) routing `insert_pages_from_file` + `headless_merge`, with post-merge `_MAX_PAGES` invariant and contiguous-run insert batching; `AnnotationTool._require_page` (page 0 no longer silently annotates `doc[-1]`); NaN/inf-safe watermark `_coerce_wm` chokepoint funneling `add_watermark`/`update_watermark`; single-instance argv filter now resolves every non-flag token. Plan: `plans/phase-2-chokepoint-guards.md`.
- [x] **Phase 3 — Memory Budgets** (landed 2026-06-10): `CommandManager` now enforces `MAX_UNDO_STACK_BYTES = 512 MiB` over per-command `_byte_size()` (oldest-first eviction, `_saved_stack_size` decremented per eviction) and dedups adjacent `SnapshotCommand` boundary snapshots (`prev._after_bytes` shared into `curr._before_bytes` when equal) at all three push sites; `build_print_snapshot` writes the print-input PDF directly to a dest `Path` (fast path `doc.save(..., encryption=KEEP)`, overlay path `tmp_doc.save`), `PrintJobRequest.capture_pdf_bytes` → `write_pdf_to`, and dead `PDFModel.capture_print_input_pdf_bytes` removed. Plan: `plans/phase-3-memory-budgets.md`. Tests: `test_scripts/test_undo_memory_budget.py`, `test_scripts/test_print_snapshot_path.py`.
- [x] **Phase 4 — UI-Thread Responsiveness** (landed 2026-06-10): 4.1 async thumbnails — structural call sites (delete/rotate/straighten/insert ×2/merge, structural undo/redo) now use `_invalidate_thumbnails(affected)` (synchronous `set_thumbnail_placeholders` first, then load-gen bump + `_schedule_thumbnail_batch` next tick); cross-page text moves no longer touch thumbnails; `_update_thumbnails` kept only as a deprecated test shim. 4.2 search worker — `SearchTool.search_page(page_num, query)` + `_SearchWorker`/`_SearchBridge` (gen-tokened signals), incremental accumulate into `display_search_results`, search_state persisted on worker finish; `_cancel_search()` guards all doc-mutating methods + tab switch/close/open. Plan: `plans/phase-4-ui-responsiveness.md`. Tests: `test_scripts/test_thumbnail_async.py`, `test_scripts/test_search_worker_flow.py`.
- [x] **Phase 4 (2026-06-12) — Thumbnail invalidation fixes:** `_invalidate_thumbnails` now skips `set_thumbnail_placeholders` when page count is unchanged (rotate/straighten/text-move), rendering only affected rows via `end_limit`; uses dedicated `_thumb_gen_by_session` counter instead of bumping `_load_gen` (no longer cancels viewport-anchor restore or open-background fallback); cross-page text moves now invalidate thumbnails for both source and destination pages on success and rollback; dead `_update_thumbnails` deleted. Tests: `test_scripts/test_thumbnail_async.py`, `test_scripts/test_cross_page_text_move.py`.
- [x] **Phase 5 (2026-06-12) — Undo byte budget fixes:** Trim floor keeps at least 1 command (the newest) even if it exceeds the budget — prevents `can_undo()` silently becoming False; `_unique_byte_total()` counts shared dedup'd bytes objects once (via `id()`), not double, restoring the full effective 512 MiB budget for dedup'd stacks. Tests: `test_scripts/test_undo_memory_budget.py`.
- [x] **Phase 6 (2026-06-12) — QSS padding fix + preview render clamp:** `_build_text_editor_stylesheet` now includes `padding: 0px; margin: 0px;` so the theme's `QTextEdit { padding: 4px 8px; }` rule cannot cascade back and shift glyphs; new `utils/render_limits.py` with `safe_render_scale` and `_MAX_PIXMAP_PX` (moved from `pdf_model.py`, re-exported for backwards compat); `view/text_editing.py` clamps the preview `get_pixmap` via `_safe_render_scale`. Tests: `test_scripts/test_text_editor_theme_padding.py`.
- [x] **Phase 7 (2026-06-12) — Guards + optimizer + hygiene:** `render_page_pixmap` now rejects page_num < 1 or > len(doc); wheel zoom uses effective clamped factor instead of raw factor (no overshoot/snap-back at boundaries); IPC dash-token skip deleted (every non-blank token must resolve to an existing .pdf); `optimize_capabilities` reports `object_streams: True` unconditionally (native PyMuPDF `use_objstms=1`), `fast_save_kwargs` passes objstms from options, `requires_post_save_packaging` only gates on linearize. Tests: `test_scripts/test_phase7_guard_hygiene.py`.
- [ ] **Phase 4.3 (deferred) — Overlay render cache.** Deferred from Phase 4: caching the overlay raster (watermark/annotation overlays composited during page render) requires revision counters on BOTH `WatermarkTool` and `AnnotationTool` plus cache state on the currently stateless `ToolManager`; the overlay path is only active when overlays exist, so the win is conditional. Non-blocking per the audit master plan — design the revision-counter invalidation before implementing.
- [ ] **Deferred — Snapshot-bytes caching.** Cache worker snapshot bytes keyed by `_render_revision` so overlapping search/OCR/print requests reuse the same serialization instead of re-calling `tobytes()`.
- [ ] **Deferred — Undo dedup digest optimization.** The `memcmp`-on-record optimization (C-speed `bytes.__eq__`, one adjacent pair) is accepted but deferred — the current `id()`-based dedup covers the common case.
- [ ] **Deferred — MVC routing of merge-dialog page counting.** The view-layer `fitz.open()` calls in `pdf_view.py` (merge dialog page-count probe) should route through a controller/model utility to respect layer boundaries.
- [ ] **Deferred — Preset objstms re-enable.** The optimizer presets currently leave `use_object_streams=False`; now that native `use_objstms=1` works, consider enabling it by default in balanced/compression presets.
- [x] **Phase 5 — Hygiene / Documentation** (landed 2026-06-11): `pyproject.toml` added (name=`cybersaga-pdf`, setuptools backend with explicit flat-layout package discovery incl. the `src.printing` namespace package; deps mirror requirements.txt; `dev` extra = ruff/mypy/pytest; `[tool.ruff]` encodes the default rule set so the 240-violation baseline is stable; `[tool.mypy]` gradual + `explicit_package_bases` for the parent-dir `__init__.py` gotcha; `[tool.pytest.ini_options] testpaths=["test_scripts"]`). `pip install -e ".[dev]"` now works (`.venv` pip upgraded 21.2.3 → 26.1.2 for PEP 660). PITFALLS: cooperative OCR cancellation entry. CLAUDE.md §3.1 violation count reconciled (113 → 240). Plan: `plans/phase-5-hygiene.md`.

## Open -- App identity single source of truth (from /code-review of claude/simplify, 2026-06-10)

- [ ] **Consolidate app-identity strings into one canonical module.** The CyberSagaPDF
  rename touched 5+ independent hardcoded sites with no shared constant: `main.py:21`
  (`prog="cybersaga_pdf"`), `main.py:37` (`APP_USER_MODEL_ID = "CyberSaga.CyberSagaPDF"`),
  `utils/preferences.py:29-30` (`_ORG`/`_APP` for QSettings), `utils/single_instance.py:22`
  (IPC server name prefix `cybersagapdf_singleinstance_`), and
  `scripts/windows_file_association.ps1:63-69` (`$Launcher`, `$ProgId`, `$AppExe`,
  `$AppName`, `$AppRegName`). A future rename that misses one site produces no error at
  rename time but silently breaks settings migration, single-instance forwarding, or .pdf
  associations for existing users later. **Fix:** add a leaf `utils/app_identity.py`
  (pattern: `utils/theme_ids.py` from the theme work) exporting ORG/APP/prog/server-prefix
  and import it from main.py, preferences.py, single_instance.py; the PowerShell script
  can't import Python, so parameterize its identity values (`param(...)` with current
  defaults) and note in the script header that defaults must track `utils/app_identity.py`.
  Confirmed by the 2026-06-10 review verifier: 5-6 independent definition sites, none
  derived from a shared source.

## Open -- Security dependency hygiene (from F2/F9 patch work; updated 2026-06-05)

See `implementation-notes.md` for the full F1–F9 patch log. Status of the follow-up
investigation (Task 2 of the follow-up series):

### BLOCKED — transformers CVE cannot be fixed via a surya-ocr bump (investigated 2026-06-05)

pip-audit on the global env flags two advisories in `transformers 4.57.6`:

| advisory          | fixed in        | notes                                        |
|-------------------|-----------------|----------------------------------------------|
| CVE-2026-1839     | `5.0.0rc3`      | fix lives only in the transformers 5.x line  |
| PYSEC-2025-217    | *(none)*        | **no fixed version exists upstream**         |

`transformers` is pulled **transitively by `surya-ocr`**. I checked every relevant
surya-ocr release's declared constraints (PyPI `requires_dist`):

| surya-ocr | pillow              | transformers                |
|-----------|---------------------|-----------------------------|
| 0.20.0 (latest) | `<11,>=10.2.0`| `>=4.56.1` (unbounded upper)|
| 0.17.1 (installed) | `<11,>=10.2.0` | `>=4.56.1` (unbounded upper)|
| 0.16.0    | `<11,>=10.2.0`      | `<4.54.0,>=4.51.2`          |
| 0.13.0 … 0.5.0 | `<11,>=10.2.0` | `<5.0.0,>=4.41.0`           |
| 0.4.0     | `<11,>=10.2.0`      | `==4.36.2`                  |

**Conclusion: do NOT bump.** Reasons:
1. **No surya-ocr release requires `transformers>=5.0.0rc3`.** The newest (0.17.1,
   0.20.0) only *allow* it via an unbounded `>=4.56.1`; every release ≤0.16 actively
   *excluded* 5.x (`<5.0.0` / `<4.54.0`). There is no surya release that pins or has
   been validated against transformers 5.x.
2. Forcing `transformers>=5.0.0rc3` onto surya 0.17.1 is an **untested major-version
   combination** (transformers 5.0 is a breaking release; surya predates it). The OCR
   adapter's own surface — `DetectionPredictor` / `RecognitionPredictor` /
   `FoundationPredictor` / `TaskNames.ocr_without_boxes` — is a *surya* API and is
   unaffected by the transformers version, but surya calls transformers internally,
   so a 5.x break would surface as a runtime failure inside recognition.
3. `PYSEC-2025-217` has **no fix at all**, so even a successful bump leaves one CVE open.

### Pillow floor vs. surya-ocr — unsatisfiable; reconciled via file split (2026-06-05)

The P8 patch set `Pillow>=12.1.1` in `optional-requirements.txt` **next to**
`surya-ocr>=0.6`. But every surya-ocr release caps `pillow<11`, so that file was
**unsatisfiable** — `pip install -r optional-requirements.txt` could not resolve.
pip-audit also shows `Pillow 12.1.1` itself now has CVEs fixed in `12.2.0`.

Reconciled: `surya-ocr` (+ `torch`) moved to a new mutually-exclusive
**`ocr-requirements.txt`**; `optional-requirements.txt` now floors the *core* image
features (deskew/straighten/optimize) at `Pillow>=12.2.0` (secured). The OCR extra
is documented as carrying the vulnerable Pillow 10.x line + the transformers CVEs as
an upstream-blocked residual. Locked by `test_security_pillow_floor.py` and
`test_security_ocr_requirements.py`.

### Packaging hygiene (recorded during F3 / Task 5)

- [ ] **Exclude `scripts/` from any future packaged artifact.** There is currently no
  app packaging manifest in the repo (no `setup.py`/`setup.cfg`/`pyproject.toml`/
  `MANIFEST.in`, no PyInstaller `.spec`), so the dev-only CUA harness
  `scripts/ux_signoff_agent.py` is not shipped by anything. When packaging is added,
  exclude `scripts/` (it drives the real keyboard/mouse and must never ride along in a
  release build).

### Deployment env remediation (recorded during Task 6 audit, 2026-06-05)

- [ ] **Upgrade the build-env (`.venv`) Pillow to >=12.2.0 and rebuild.** The PyInstaller
  build env still has Pillow 12.1.1 (5 image-parser CVEs, fixed in 12.2.0). The declared
  floor (optional-requirements.txt) is already 12.2.0 for fresh installs; the existing
  `.venv` needs `python -m pip install -U "Pillow>=12.2.0"` + a PyInstaller rebuild so the
  shipped artifact drops the vulnerable Pillow. (Deployment audit otherwise clean:
  PyMuPDF/PySide6/pytesseract OK; no transformers/surya/torch in the deployment, so the
  OCR-stack CVEs do not apply to the shipped product.)
- [ ] **Refresh build tooling** (`pip 21.2.3`, `setuptools 57.4.0`) in the `.venv` — old
  but not bundled into the exe, so low risk; update for build hygiene.

### F1 follow-up — central render-scale clamp gap (recorded during /simplify code-review, 2026-06-06)

- [x] **DONE (2026-06-10, Phase 2.1).** Clamp landed in `ToolManager.render_page_pixmap` (local import of `_safe_render_scale` to avoid the pdf_model↔tools cycle); the strict-xfail red-light test flipped green and its marker was removed. Original item kept below for history.
- ~~[ ]~~ **Push `_safe_render_scale` into the central raster chokepoint.** The F1 patch applies
  the 40 MP pixmap clamp only at four *leaf* render sites (image export, deskew, straighten,
  OCR). `ToolManager.render_page_pixmap` (`model/tools/manager.py:71`) — which every render
  flows through, including the interactive zoom path (`PDFController.set_scale` →
  `PDFModel.get_page_pixmap` → `render_page_pixmap`) — builds `fitz.Matrix(scale, scale)` from
  the raw scale with no clamp. A page that clears the open-time size/page guards but carries an
  outsized MediaBox can therefore still OOM on zoom (CWE-400). `implementation-notes.md` records
  that the central clamp was skipped to avoid perturbing ~30 render tests — test-churn avoidance,
  not an architectural reason. **Fix:** clamp `scale` via `_safe_render_scale(page, scale)` inside
  `render_page_pixmap` (both the no-overlay and overlay branches) so every raster path is bounded
  by construction. **Red-light already in place:** `test_security_pdf_resource_guards.py::
  test_render_page_pixmap_clamps_oversized_scale` is an `xfail(strict=True)` asserting the
  chokepoint clamps an oversized scale — it flips to XPASS (a hard failure under `strict`) the
  moment the clamp lands, prompting removal of the marker. This is the one genuine residual
  security gap surfaced by the round-5 /simplify review.

### Repo governance / hygiene (recorded during code-review follow-up, 2026-06-05)

- [x] **Refresh completion-gate pins + commit settings.json — DONE (2026-06-06).**
  Committed `.claude/settings.json` (activates the Stop hook repo-wide) and refreshed the
  three stale `_PINNED_HASHES` to their LF-blob hashes: ux_signoff_agent.py `bf4d1034`,
  test_no_jump_editor_geometry.py `407a95fc` (accepts 066261c's chrome-inset edit; core
  thresholds unchanged), verify_no_jump.py `9f591f9e` (LF blob; the stale CRLF working
  copy was re-checked-out so the gate's raw read matches a fresh clone). The gate's
  static checks now all pass (`11 tracked`, `8 pins match`, hook registered + content
  verified). **Still NOT fully green:** `verify_no_jump.py` reports `6/9 gates failed`
  (artifact gaps + the 7 pre-existing geometry test failures). Making the acceptance
  suite itself pass is the separate, pre-existing no-jump work, not gate maintenance.
  Note: committing settings.json means the Stop hook now runs for anyone working in the
  repo with Claude Code.
- [x] **Consolidate authored security docs under `docs/`.** Moved all six tracked
  reports (investigation-review.md, security-investigate.md, weakness_patch.md,
  weakness_patch_organized.md, patch-weaknesses-found-in-immutable-knuth.md, and the
  CJK scan report 資安掃瞄.md) to `docs/security/` via `git mv` (history preserved).
- [x] **(Optional) Reconcile CLAUDE.md s3.1 with reality — DONE (2026-06-11, Phase 5).**
  `pyproject.toml` added; `pip install -e ".[dev]"` works; s3.1's stale 113-violation
  count updated to the measured 240 (ruff 0.15.9 default rules).

### Remaining open items

- [ ] **Revisit the OCR stack when surya-ocr relaxes its pins.** When a surya release
  ships `pillow>=12.2` support and a transformers floor in the 5.x line, merge
  `ocr-requirements.txt` back and drop the residual-risk note. Track upstream surya.
- [x] **`pip-audit` CI gate** — DONE (Task 4): `.github/workflows/ci.yml` runs
  `pip-audit -r requirements.txt -r optional-requirements.txt` as a BLOCKING matrix job
  (ubuntu + windows, so both platform-gated print backends resolve) and fails on any
  advisory. Verified locally: the core+optional set is clean. The OCR extra is audited
  as an advisory (non-blocking) step. ruff + a security-regression pytest subset are
  wired in too (ruff advisory due to the 113-violation backlog).
- [x] **F9 — pin/verify OCR model weights** — DONE (Task 3): `model/tools/ocr_weights.py`
  pins the surya checkpoint revisions, supports offline loading from a local bundle
  (`PDF_EDITOR_OCR_WEIGHTS_DIR`), and SHA256-verifies bundle files before load (refuses
  on mismatch, fails closed on an empty manifest). Wired into `_SuryaAdapter._ensure_loaded`.
  Process documented in `docs/ocr-weights-verification.md`.
- [ ] **F9 bundle distribution** — ship a vetted weights bundle and populate
  `WEIGHTS_MANIFEST` with its published SHA256 digests so `PDF_EDITOR_OCR_WEIGHTS_DIR`
  works out of the box (the verification layer is ready; only the bundled artifact +
  digests are missing). See `docs/ocr-weights-verification.md` for the update process.

## Done (2026-06-06) -- Auto XREF repair on open (replaces manual toolbar action)

- What: Removed the file-tab **"修復 XREF 表"** toolbar action and its view/controller
  plumbing (`sig_repair_xref_requested`, `PDFView._repair_document_xref`,
  `PDFController.repair_document_xref`) plus the now-dead on-disk
  `PDFModel.repair_document_xref(output_path)`. Replaced with an automatic
  check-and-repair in `PDFModel.open_pdf`: when MuPDF flags `doc.is_repaired`, the
  document is round-tripped in memory (`_repair_doc_xref_in_memory`) so the active
  doc carries a clean, consistent xref.
- Startup impact: healthy files pay only one boolean flag read (median open held at
  ~1 ms for 10–200 page docs); the round-trip runs once and only for files MuPDF
  actually had to repair — files that previously could not be saved incrementally
  anyway.
- Large-file cost: the round-trip uses `tobytes(garbage=1)` **without** `deflate=True`.
  deflate re-compresses every stream (~20 ms/MB) but shrinks nothing on the
  image-heavy content of real large PDFs, so it was the whole reason a 235 MB file
  took ~4.9 s. Dropped → ≈2.5–5 ms/MB (~1.3–2.6 s worst case at the 512 MB open cap).
  Validated on a real damaged copy of `test_files/test-large-file.pdf` (47 MB,
  402 pages): repaired on open in 240 ms, content byte-identical to the healthy file.
  Same output size/memory; compression deferred to explicit save.
- Tests: `test_scripts/test_xref_repair.py` rewritten to cover auto-repair-on-open
  (damaged → repaired/memory-backed, content intact; healthy → untouched/file-backed).
- Code-review follow-up (2026-06-07): auto-repair was silently **stripping
  encryption** from a damaged+encrypted PDF. Two-part fix (a second review pass
  caught that the first cut fixed only the in-memory half):
  (1) skip the round-trip when `_doc_is_encrypted(doc)` (trailer encryption string
  in `doc.metadata` — survives auth, covers owner-only); and
  (2) pass `encryption=fitz.PDF_ENCRYPT_KEEP` on every full-save-to-disk call
  (`_full_save_to_path`, `save_as` full-save branch) — `Document.save()`'s
  `encryption` default is NONE(1) and **actively decrypts**, so a repaired doc's
  forced full-rewrite still stripped the password *on disk* without it.
  Verified end-to-end via real `save_as` → reopen (`needs_pass=1`, `auth=2`,
  `is_repaired=False`). Also measured peak memory = ~1.15× file size (one
  serialization buffer, not ~2×) — no change needed.
- Third review pass (2026-06-07): preserving encryption surfaced a **new** regression
  — the reopen-after-save handle was locked and never re-authenticated, so the live
  editing session went dead (`get_text` raised "document closed or encrypted") after
  an encrypted save-back. Fix: persist the open-time password on
  `DocumentSession.password` (in-memory only) and re-authenticate via
  `_reopen_doc_after_save` at both reopen points. Stress-verified 170/170 encrypted
  save-backs keep content (live+disk) and the live doc usable. Test gotcha:
  `needs_pass` stays 1 after a successful `authenticate()` — assert `not is_encrypted`
  / `get_text()` works, not `needs_pass == 0`. Tests now assert in-memory + on-disk +
  live-session survival (each prior cut's narrower asserts gave false confidence).
- Same-root-cause sweep, made structural (2026-06-07): `tobytes()` also defaults
  `encryption=NONE`, so any live-doc round-trip (`self.doc = fitz.open(self.doc.tobytes(...))`)
  silently decrypts in-memory. Two instances surfaced one-per-review —
  `_maybe_garbage_collect` (every 20 edits) and `_repair_active_doc_in_memory`
  (damaged-doc recovery fallback). Instead of patching each, added a single chokepoint
  `_roundtrip_live_doc(garbage=, deflate=)` (always `encryption=KEEP` + re-auth, opens
  before closing) and routed both through it; plus an AST guard test
  (`test_live_doc_roundtrips_preserve_encryption`) that fails on any
  `self.doc.tobytes(...)` **or** `self.doc.save(...)` lacking `encryption=`. Behavioral tests:
  `test_encrypted_doc_survives_periodic_gc`, `test_encrypted_doc_survives_in_memory_repair`.
- Doc-level snapshot decrypt closed (2026-06-07): the last instance of the invariant.
  `_restore_doc_from_snapshot` *replaces* the live handle (`self.doc = fitz.open(snapshot_bytes)`),
  so a structural-edit undo on an encrypted doc decrypted the live doc and the next save
  lost the password. Fix: `_capture_doc_snapshot` serializes with `encryption=KEEP`;
  `_restore_doc_from_snapshot` re-authenticates via `_reauthenticate_if_needed`. Test:
  `test_encrypted_doc_survives_doc_level_snapshot_restore` (red→green, save-back `needs_pass=1`).
  Verified the symmetric page-level path (`_restore_page_from_snapshot`) does **not** lose the
  password — it mutates the still-encrypted live doc in place, so the saved file stays encrypted
  (correcting the earlier "page-level needs re-encryption logic" framing).
  Residual (deferred, NOT a password bug): page-level snapshot *bytes* in the undo history are
  plaintext in memory — same exposure as the already-decrypted live doc, never on disk. Encrypting
  them at rest needs real re-encryption (method+permissions+keys, session holds only one password);
  spin up as a separate task.
- Incremental-save gap closed (2026-06-07): the `encryption=KEEP` sweep missed the one
  *incremental* save (`save_as`'s `self.doc.save(save_target, incremental=True)`). With the
  default `encryption=NONE` PyMuPDF **raises** ("Can't do incremental writes when changing
  encryption"), so every healthy-encrypted save-back logged a WARNING and silently fell back
  to a full rewrite — password survived (fallback uses KEEP) but incremental was defeated for
  all encrypted files. Fix: pass `encryption=KEEP` on the incremental call (no-op for
  unencrypted; true incremental append for encrypted). AST guard widened to `self.doc.save(...)`.
  Behavioral test `test_healthy_encrypted_save_back_uses_incremental_and_keeps_password` spies
  on `_full_save_to_path` and asserts no fallback (a "password survives" assert alone passed
  even with the bug). Lesson logged: audit all call sites of a library-default footgun + build
  the chokepoint/guard FIRST, then fix once — this gap was the one site the per-commit sweep skipped.
- Plan: `plans/archive/auto-xref-repair-on-open.md`. Pitfalls recorded in
  `docs/PITFALLS.md` (memory-backed-after-repair; no-deflate-on-open;
  no-roundtrip-when-encrypted; save()+tobytes()-default-to-decrypt [structural:
  _roundtrip_live_doc + AST guard]; incremental-save-needs-KEEP-or-raises;
  reopen-must-reauthenticate; peak-memory-~1.15×).

## Done (2026-06-01) -- Four Windows printing defects + review-finding follow-ups

- What: Fixed the four print bugs the earlier commits `2408f65`/`9fd7d76` only appeared to fix (their tests exercised fake/PDF-output paths, never the GDI spooler). Plan: `plans/2026-06-01-plan-surgical-fixes-for-eager-biscuit.md`; investigation: `4-problems-investigation.txt`.
- Shipped (commits `676002b`, `4833e84`, + findings follow-up):
  - P1 — settings no longer permanently mutated: removed `SetPrinter(level=9)` persistence on opening `屬性`; the captured DEVMODE is carried base64 in `extra_options`, injected only at submission, and applied job-scoped (set → print → restore) in `win_driver._print_with_scoped_devmode`.
  - P2/P3 — per-page media: `_split_by_layout`/`_print_layout_groups` split a mixed-size/orientation job into one spooler job per uniform-layout group (GDI ignores mid-job `setPageLayout`).
  - P4 — slow spool: cap effective raster DPI at `_WIN_MAX_RASTER_DPI = 150` for the real printer path (PDF output keeps full DPI).
  - Review findings #1–#14: explicit paper preserved across split (#1); document-order multi-copy split (#2, chosen behavior); page-range validated before DEVMODE consumed (#3); apply-only-on-confirmed-write + surfaced restore failure (#4); pywin32-fallback degrades to public fields with a log (#5); partial-output reporting on mid-split failure (#6); buffer-only props no longer revert dialog fields (#7); clarifying comments for #8/#9/#10; shared base64 encode/decode helpers (#11); dropped dead `override_fields` write (#12); single-normalize contract in `qt_bridge._apply_printer_options` (#13); DPI-ceiling comment ties to the `normalized()` floor (#14).
  - Tests: `test_scripts/test_win_print_fixes.py` (real driver/dialog paths) + updated `test_win_driver_properties.py`. 45 print-suite tests pass; no new ruff violations. Docs updated: `FEATURES.md`, `PITFALLS.md`.
- Follow-up (future work): Windows has no vector/direct-PDF submission path — a true vector path (send PDF to an interpreting driver, or render vector via PDFium) would beat the raster-DPI cap. Mixed-media multi-copy jobs are inherently non-atomic on GDI (one spool job per layout group).

## Done (2026-05-30) -- Clean re-implementation of the four-theme UI system

  - What: Restarted the theme switcher from clean base `24c9dba` (old work preserved on branch `backup/theme-switcher-b774a72`) and rebuilt it per `plans/learn-from-ui-update-report-txt-ethereal-micali.md`, folding in every lesson from `ui-update-report.txt`.
- Shipped:
  - `view/theme.py` — four token dicts (added **glimmering-glacier**), `THEME_REGISTRY`, `build_qss` (app-level QSS, scoped ribbon/sidebar/doc-tab rules, dialog+menu+combo-popup themed), and `ThemeSwitcherWidget`/`_ThemeChip` (one square per mode).
  - `view/icons.py` — 32-label→PNG map (incl. `拉正頁面` → `33_拉正PDF頁面.png`, wired to the existing straighten-page toolbar button) + `load_icon(label)`; Qt imports guarded for headless tests.
  - `appearance_design/colors.css` — appended block 03 Glimmering Glacier.
  - `utils/preferences.py` — `ui/theme` get/set with validation (`_VALID_THEME_IDS`), default `alpine-snow`.
  - `view/pdf_view.py` — removed all inline color stylesheets; object names for panels/tabs; toolbar container 92px + text-beside-icon + 24px icons; status-bar switcher; `sig_theme_selected`.
  - `controller/pdf_controller.py` — `set_theme` slot applies app-level QSS + persists + syncs switcher.
  - Tests: `test_scripts/test_theme_and_icons.py` (rebuilt, 4 themes) + theme cases in `test_user_preferences.py`. 66 pass; RED confirmed before implementation.
- Outcome: themed QSS applied once at `QApplication` level so context menus and dialogs re-theme too. No new ruff violations.
- Post-review fixes (3 findings from `/code-review`):
  1. Switcher was inert on the empty shell (no controller yet). Theming is now **view-owned** (`PDFView.apply_theme`) since it never touches the model; works without a controller. Removed `PDFController.set_theme`.
  2. Dual source of truth for valid ids → new leaf `utils/theme_ids.py` imported by both `utils/preferences.py` and `view/theme.py`; the registry raises at import on drift.
  3. View constructor no longer mutates the global app stylesheet; `main.py` calls `view.apply_initial_theme()` at the composition root. Side benefit: this removed the global-QSS pollution that made `test_no_jump_editor_geometry` flake in the full suite — that file is deterministic again (377 passed alone).
- Follow-up: delete `backup/theme-switcher-b774a72` once the new branch is merged.

## Done (2026-05-19) -- Clean re-implementation of glyph-jump elimination

- What: Re-derived the 5-layer no-jump text-editing fix from clean baseline `c091661f` on branch `rewrite/glyph-jump-v2` instead of carrying the 50-commit organic history.
- Layers: A commit-side fidelity + shared `_classify_insert_path` (model); B `PreviewRenderer` real MuPDF rasterization; C `_display_font_pt` DPI-correct sizing; D `PreviewBackedInlineTextEditor` frozen-first-frame paint; E `run_reopen_anchors` cross-edit anchor.
- Prereqs ported (outside the 5-layer plan, gate-required): rawdict `span['text']` backfill shim; `QGraphicsProxyWidget.graphicsProxyWidget` shim; `view/pdf_view.py` click-pipeline (adopted from validated `308ae15`); 3 gate test files + finalize-failure API + resilient audit fixtures.
- Outcome: 142 passed / 6 skipped across ported suites. No-jump gate's 5 core behavioral gates pass deterministically x2 (27 cases, manifest match). Remaining gate steps need `ux_signoff_agent.py` (absent) / are render-scale-DPI environment-sensitive (fail identically on validated code in offscreen sandbox) -- see `implementation-notes.html` Q3.
- Follow-ups: Q4 (finalize FAILED behavior change); run gate full-suite in a real-DPI desktop env. Q1 (`get_render_width_for_edit` dead params removed — done).

## Done (2026-04-22) -- Phase 2 text-editing fidelity

- What: Closed the Phase 2 gap between current text-edit behavior and Acrobat-level stability across five tasks.
- Changes shipped:
  - Red-light matrix: 6 regression tests across float font-size round-trip, multi-style paragraph collapse, inline editor geometry/transparency, and stale-fixture autopan attribute.
  - Float font-size: `TextEditSession`, `EditTextRequest`, and all call sites now use `float` throughout. `_parse_font_size_str` / `_format_font_size` helpers normalize the font-size combo widget.
  - Multi-style preservation: `_build_multi_style_html` uses difflib char-level mapping to rebuild per-run color fidelity. `preserve_multi_style` flag gates the path and skips the single-line fast path.
  - Request deduplication: `EditTextRequest` and `MoveTextRequest` moved to `model/edit_requests.py` as single source of truth; re-exported via `view/text_editing.py`.
  - Fixture fix: `_make_view()` in `test_text_editing_gui_regressions.py` now injects `_autopan_active = False` to match post-autopan-merge `__init__`.
- Outcome: 91 tests pass (2 pre-existing context-menu failures unrelated to Phase 2). All 6 red-light tests green.

## Done (2026-04-20) -- F4 view-only color profile switching (simplify + bug fix pass)

- What: Completed F4 with a three-agent code review pass (reuse, quality, efficiency) plus a P0 object-selection-overlay bug fix.
- Simplify fixes applied:
  - Centralized duplicate `pixmap_to_qimage` bridge logic (pdf_renderer.py → utils/helpers.py).
  - Added `safe_to_fitz_colorspace()` helper for reusable fallible colorspace conversion.
  - Replaced itemData loop with `combo.findData()` in view's color profile setter.
  - Extracted `_on_color_profile_combo_changed()` method from inline lambda.
  - Used `dataclasses.replace()` for immutable mutation in print options pipeline.
  - Extracted `_resolve_session_profile()` helper to consolidate 3× normalize-and-warn boilerplate.
  - Dropped tautological "Defensive" comment in color_profile.py.
- Bug fix: Dead C++ object references in selection overlay. When `scene.clear()` runs (profile switch, render rebuild), Python refs to deleted C++ items cause `RuntimeError` on next click. Added `shiboken6.isValid()` guards in `_update_object_selection_visuals()` to drop dangling wrappers and re-create.
- Outcome: 543 tests pass (no regressions). Code is cleaner, more maintainable, object selection works reliably. See `plans/archive/2026-04-20-simplify-and-fix-report.md` for detailed breakdown.

## Done (2026-04-19) -- F2 Surya OCR implementation

- What: Replaced the Tesseract-era OCR stub with Surya as the recognition backend, added a structured `OcrRequest` dialog (page scope + languages + device), a `QThread`-backed worker with per-page commit and cancel, and availability-gated UI entry points. GPU is user-configurable via `utils.preferences.UserPreferences` (`ocr/device`: `auto` prefers CUDA → MPS → CPU; also `cuda`/`cpu`/`mps`).
- Why: The existing OCR slot never shipped real text insertion and left language, GPU, and cancel handling undefined. Surya delivers modern multilingual OCR (including zh-Hant/Hans, ja) and fits the existing `model/tools/*` + QThread worker patterns without breaking layer boundaries.
- Outcome: `pip install surya-ocr torch` enables the OCR action under 轉換. Results are written into the PDF via `PDFModel.apply_ocr_spans(page_num, spans)` using `page.insert_text(..., render_mode=3, rotate=page_rotation)` with built-in CJK-aware font fallback ("japan"/"korea"/"china-t"/"helv"), so the text is invisible but searchable/selectable. Focused suites `test_scripts/test_ocr_*.py` (71 tests) cover types, preferences parsing, the Surya adapter behind mocks, model span insertion, the dialog, controller worker/bridge flow, and the view entry point; all green.

## Done (2026-04-17) -- F3 shell-integration API slice

- What: Added an `argparse` CLI surface, a Qt-free headless merge path, and a per-user single-instance forwarding layer so later shell verbs can call into the running app without touching registry or file-association settings.
- Why: The backlog F3 scope was reduced to "open the APIs, don't change my computer settings", so the missing work was the in-app command surface rather than OS registration.
- Outcome: `python main.py a.pdf b.pdf` now routes through the CLI parser, `python main.py --merge out.pdf a.pdf b.pdf` merges headlessly without launching the UI, and later invocations can forward file-open requests into the already-running window. OS-level registration and shell-verbs remain explicitly deferred.

## Done (2026-04-16) -- Close F1 native PDF image manipulation

- What: Extended `objects mode` so existing PDF image XObjects are selectable and can be moved, resized, rotated, and deleted through the same object workflow as app-owned objects.
- Why: F1 was still open because object manipulation stopped at app-owned images. The backlog required native PDF images to become real manipulable objects before the phase could close.
- Outcome: Native image hits now come from parsed page content/image invocations, edits rewrite the image invocation operators instead of redacting page regions, focused native-image regressions are green, and a real-file round-trip on `test_files/2.pdf` verifies move/rotate/delete plus save/reopen.

## Done (2026-04-14) -- F1 object manipulation v2

- What: Expanded the F1 object layer from v1 textboxes/rectangles into a first-class `objects mode` with visible entry points, same-page multi-select, resize handles, and app-inserted image objects.
- Why: The backlog needs a clean separation between browse text selection, object manipulation, and text edit mode, and the app-owned image path is the safest place to grow next.
- Outcome: Focused request/model/controller/view tests are green, the GUI slices are green, and the mixed-sample GUI verification still passes.

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
- [ ] Flaky: `test_scripts/test_print_subprocess_runner.py::test_runner_heartbeat_events_prevent_false_stall` can fail during long `pytest -x` runs in the worktree but passes when run alone (timing-sensitive).

## Notes on `objects mode`

- Treat `objects mode` as a separate interaction mode from browse mode and text-edit mode.
- Browse mode keeps its text-selection behavior and should not accidentally start moving objects.
- Objects mode should focus on selecting/manipulating objects:
  - Supported now: rectangles, app-inserted images, and native PDF images.
  - Textboxes stay in text-edit mode.
- Text edit mode focuses on textboxes:
  - Supported: move/rotate/delete/resize/multi-select textboxes, plus editing words.
- The same object identity layer stays shared across the object and text-edit paths.

## Done (2026-04-13) -- Close B4 performance campaign

- What: Closed `B4` after the optimize-copy and open/page-change slices shipped and the final before/after evidence was captured in the tracker and performance plan.
- Why: The backlog explicitly required measured wins, not just profiling, before `B4` could close.
- Outcome: Startup/import+instantiate is down to about `0.193s` from the `0.444s` baseline, UI-path open on `2024_ASHRAE_content.pdf` now reaches initial high-quality visible page at about `73ms` and far-page jump at about `222ms`, and large optimize-copy now completes in the tens of seconds instead of timing out past the original probe window.

## Done (2026-04-13) -- B4 Slice 2 open/page-change responsiveness

- What: Changed the controller open path so full-page placeholders still appear immediately, but thumbnail raster batches and sidebar scans wait until the initial visible page reaches high quality or a short fallback timer expires. Also coalesced repeated visible-render scheduling so page changes and viewport updates stop restarting the render queue on every tick.
- Why: After the optimize-copy slice, the next best B4 move was making the document feel ready sooner in the real UI path. The existing controller already had batched rendering and caching, but it still spent early open time on background work and allowed redundant render scheduling churn during navigation.
- Outcome: `test_scripts/benchmark_ui_open_render.py` now measures `test_files/2024_ASHRAE_content.pdf` at startup-to-placeholders ~534.9ms, initial high-quality page ready ~78.1ms, and far-page jump to page 483 high-quality ready ~268.7ms. The startup controller regression suite now locks in visible page first, background work later plus visible-render coalescing.

## Done (2026-04-12) -- B4 Slice 1 preset-aware optimize-copy performance

- What: Added explicit execution profiles for the three optimize-copy presets so speed-first skips content cleanup/font subsetting and avoids the slower extracted-image parallel fallback, balanced keeps the heavier pipeline for small jobs but downgrades cleanup on large jobs, and compression-first preserves the full path.
- Why: The first measured `B4` hotspot was large-file optimize-copy, not open or page-change. The old implementation used nearly the same expensive pipeline for all presets, which left too much latency on the table for the speed-first and balanced modes.
- Outcome: Large-file optimize-copy on `test_files/2024_ASHRAE_content.pdf` now measures about `15.6s` for speed-first, `20.4s` for balanced with about `37.9%` saved, and `23.2s` for compression-first with about `57.8%` saved. `B4` remains open for open/page-change work, but the optimize-copy slice is now a shipped measured win.

## Done (2026-04-12) -- B4 baseline capture and performance-plan handoff

- What: Captured fresh baseline numbers for startup, synthetic large-file open, page render, repeated-edit latency, and a first optimize-copy sample, then wrote the dedicated `B4` child plan for closing performance with measured wins.
- Why: The backlog requires `B4` to stay open until we have both baseline evidence and shipped before/after improvements. We had planning placeholders, but not a concrete performance handoff with real numbers and hotspots.
- Outcome: `B4` is now `in_progress` instead of vague-open. The plan identifies large-file optimize-copy as the highest-risk hotspot on this machine, and the next step is shipping measured wins for open, page-change, and optimize-copy flows.

## Done (2026-04-30) -- Text editing fidelity render-preview + 15-test suite

- What: Added a preview-backed inline text editing surface and a 15-test fidelity suite for text edit rendering and commit parity.
- Changes shipped:
  - Shared insert path classifier `_classify_insert_path(...)` in `model/pdf_model.py`, with `_apply_redact_insert(...)` routed through the shared decision.
  - `PreviewRenderer` and `PreviewBackedInlineTextEditor` in `view/text_editing.py`.
  - `TextEditManager.create_text_editor(...)` now uses preview-backed editor and configures render context.
  - New regression suite: `test_scripts/test_text_editing_fidelity_suite.py` (15 tests).
- Outcome: New fidelity suite passes in full (15/15 green).

## Done (2026-05-01) -- Real MuPDF rasterization + three blocker fixes (Phase 2 complete)

- What: Completed Phase 2 stretch goal — replaced blank QImage scaffolding in `PreviewRenderer.render` with real `insert_htmlbox` rasterization. Fixed three runtime blockers identified in adversarial review.
- Changes shipped:
  - **Blocker 1 (critical):** `editor.font = qt_font_obj` shadow removed from `create_text_editor` — `editor.font()` now works correctly in font/size-change handlers. (`view/text_editing.py`)
  - **Blocker 2 (high):** `PreviewRenderer.render()` now rasterizes via temp document + `insert_htmlbox` + `get_pixmap` + `QImage.copy()`. Uses `model._build_insert_css`/`_convert_text_to_html` for bit-exact preview/commit parity. (`view/text_editing.py`)
  - **Blocker 3 (high):** `_classify_insert_path` now returns `"htmlbox"` on empty `member_spans` instead of `"fast"`, preventing downstream `min()` crash. (`model/pdf_model.py`)
  - **line_height threading:** `cluster_span_ids` threaded from `_start_text_edit_from_hit` → `_create_text_editor` → `create_text_editor`; `_line_ht` computed from block manager and passed to `configure_render_context(line_height=...)`. (`view/pdf_view.py`, `view/text_editing.py`)
  - **10 new tests** across `test_edit_text_helpers.py`, `test_text_editing_gui_regressions.py`, `test_text_editing_fidelity_suite.py`.
- Outcome: 103 text-editing tests pass. No regressions. PITFALLS + ARCHITECTURE updated.
- Follow-ups (deferred):
  - Editor proxy height re-measurement on font-size change — `view/text_editing.py:~688–705` (review issue #6).
  - Promote `MUPDF_HTMLBOX_OVERHEAD_PT` to module-level named constant with citation comment (review issue #3).
  - Decompose `_apply_redact_insert` into per-strategy helpers (review issue #1).
