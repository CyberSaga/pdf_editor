# Milestone 2 — Known Bugs & Security Backlog: PR-level Execution Plan

Expanded 2026-07-05 from the roadmap section in `this-is-my-own-parallel-donut.md`, after
Milestone 1 acceptance (closeout: `docs/history/# Milestone 1 Closeout — CI & Quality De.md`,
HEAD `dc4146d`). PR numbering continues M1's plan-side sequence (M1 = PR-0…PR-12).

**Status: PLANNING APPROVED PENDING — no implementation until the user signs off on this plan.**

---

## 0. Entry criteria check (from M1 closeout §7)

| Criterion | Status |
|---|---|
| Main green on 2–3 consecutive runs | Confirm on the morning PR-13 starts (pip-audit is the only gate that can turn red without a commit) |
| B4 first, before any content-stream code | Honored — PR-13 is B4 only |
| Fixture strategy decided for B1 | **Decided: synthesized in-test** (constraint from the maintainer). No gitignored `test_files/` dependency; CI gates the regression |
| Red-light discipline for B1 | Mandatory — failing output shown before the fix (§ PR-16) |
| Fresh windows functional baseline (1553 passed) | Rerun the windows leg once before PR-16 lands |

## 0.1 Recon corrections vs. the roadmap text (verified 2026-07-05)

1. **B4 is mostly already done.** TODOS' "Deployment env remediation" cites Pillow 12.1.1 /
   pip 21.2.3 / setuptools 57.4.0, but the live `.venv` measures **Pillow 12.2.0, pip 26.1.2,
   setuptools 82.0.1, wheel 0.47.0** (upgraded as a side effect of M1 PR-1's constraints
   capture — `constraints-ci.txt` already pins Pillow==12.2.0 / setuptools==82.0.1).
   PyInstaller 6.19.0 + hooks 2026.1 are installed. Remaining B4 substance: PyInstaller
   **rebuild** with the patched env, artifact smoke test, TODOS checkoff.
2. **B1 code moved.** TODOS cites `model/pdf_model.py:2204-2213` / `:2196`; the code now lives
   in `model/pdf_object_ops.py`: the buggy delete branch is `_delete_object_impl` (image branch,
   ~lines 885–893: `add_redact_annot` + `apply_redactions(images=PDF_REDACT_IMAGE_REMOVE)`);
   `_remove_native_image_invocation` is at ~line 281; `_find_app_image_invocation` ~line 200;
   `_resolve_marker_image_invocation` ~line 256 (already does xref-drift-tolerant resolution
   with digest backfill — the natural entry point for the fix).
3. **Fixture precedent exists.** `test_scripts/test_image_objects_model.py` already synthesizes
   everything in-test (`_png_bytes()` via `fitz.Pixmap`, `_make_pdf()` blank page) — including
   `test_move_overlapping_app_images_both_survive` (line 178) and
   `test_rotate_overlapping_app_image_neighbour_survives`. B1's red-light test mirrors these;
   no fixture question remains open.
4. **R5.1 partial mitigation is in place.** `controller/print_coordinator.py` already re-encrypts
   the temp (`work_dir/input.pdf`) with the source password so no *unprotected-source-derived*
   plaintext lands at rest. R5-01's remaining gap: the temp file exists at all (and unprotected
   sources are written as-is); the fix is eliminating the file-at-rest via streamed submission.

---

## 1. PR sequence (land strictly in order; one PR in review at a time)

| PR | Task | Title | Model | Stop point after? |
|---|---|---|---|---|
| PR-13 | B4 | `chore: close deployment-env remediation (Pillow/pip/setuptools) + PyInstaller rebuild` | fast-worker (Sonnet 5 verifies) | No |
| PR-14 | B5 | `docs: gate_anchor follow-up + close resolved TODOS sections` | fast-worker | No |
| PR-15 | B1 | `design: delete app-image via invocation removal (design-only, no code)` | **Fable 5** | **YES — user approval required before PR-16** |
| PR-16 | B1 | `fix: delete app-image strips only the targeted invocation (red-light first)` | **Fable 5** + codex adversarial review | Yes — review CI + manual visual check |
| PR-17 | B2 | `security: R5-01 fileless print path` | Fable 5 design, Sonnet 5 implement | Yes — manual printer validation sign-off |
| PR-18 | B3 | `security: bound worker decrypted-bytes lifetime (or documented closure)` | Fable 5 | Milestone close |

Rationale for order: B4 first (maintainer constraint; environment attribution before content-stream
work). B5 is zero-risk hygiene that keeps main warm. B1 design→approval→impl is the milestone's
riskiest change and lands under the freshest baseline. B2 next (Windows-flavored, needs manual
validation window). B3 last — it may legitimately conclude as a documented no-fix.

---

## 2. PR-13 — B4: deployment-env remediation closeout

**Scope.** Verify-and-close, not upgrade: the env upgrades already happened (see §0.1.1).
1. Evidence step (in PR description): `.venv\Scripts\python.exe -m pip list` output showing
   Pillow 12.2.0 / pip 26.1.2 / setuptools 82.0.1.
2. Rebuild the PyInstaller artifact from the patched `.venv`; record the build log tail.
3. If, against expectation, any package is below floor: upgrade it in `.venv` **and** update
   `constraints-ci.txt` in this same PR (M1 rule: a `.venv` bump and the constraints file move
   together).
4. Check off the two "Deployment env remediation" boxes in TODOS.md.

**Files.** `TODOS.md`; `constraints-ci.txt` only if a real bump is needed (expected: no).
**Red-light test.** None — mechanical env/docs PR; the existing floor guards
(`test_security_pillow_floor.py`, `test_security_ocr_requirements.py`) already pin the policy.
**Validation commands.**
- `.venv\Scripts\python.exe -m pip list` (evidence)
- `.venv\Scripts\python.exe -m pytest -q test_scripts/test_security_pillow_floor.py test_scripts/test_security_packaging.py`
- `.venv\Scripts\python.exe -m pytest -q` (full local suite, unchanged pass count)
- CI green on the PR branch.

**Manual checklist (CI-blind).**
- [ ] PyInstaller rebuild completes without new warnings about missing hooks.
- [ ] Rebuilt exe launches, opens a PDF, renders page 1, closes cleanly.
- [ ] Rebuilt exe's bundled Pillow is 12.2.0 (check build log or `exe --version`-equivalent evidence).

**Rollback risk. Low.** Docs + build artifact only; no production code. Revert = TODOS text.

---

## 3. PR-14 — B5: gate_anchor doc follow-up + TODOS hygiene

**Scope.** Resolve TODOS line ~35 ("gate_anchor.py maintenance doc points at a plan file that
never existed in git"): record the documented-here-instead decision in the gate_anchor follow-up
item and close it, or add the missing pointer where gate_anchor's doc expects it. Close any other
"Resolved" TODOS sections that only await checkoff. No code, no hash-chain changes — if any edit
would touch `check_completion_proof_hook.py`/`gate_anchor.py`/`completion_gate.py` **content**,
stop and escalate (hash-cascade risk documented in TODOS "Completion-gate trust chain").

**Files.** `TODOS.md`; possibly a comment-only touch in `scripts/gate_anchor.py` docs — avoid if
it triggers the pinned-hash cascade; prefer TODOS-only.
**Red-light test.** None (docs-only).
**Validation commands.** `.venv\Scripts\python.exe -m pytest -q test_scripts/test_completion_proof_hook.py`
(guards the trust chain stayed intact); `ruff check .`; full suite; CI green.
**Manual checklist.** None needed.
**Rollback risk. None.** Docs only.

---

## 4. PR-15 — B1 design-only PR (no implementation code)

**Scope.** A design document, `plans/b1-delete-app-image-invocation-removal.md`, PR-reviewed on
its own. **Zero production/test code in this PR.** The design must answer, with evidence from
`model/pdf_object_ops.py`:

1. **Resolution path.** How the image branch of `_delete_object_impl` resolves the marker payload
   to a `NativeImageInvocation` — expected: reuse `_resolve_marker_image_invocation` (xref-drift
   tolerant, digest-verified) exactly as move/rotate do, then call
   `_remove_native_image_invocation` instead of redacting.
2. **Ambiguity fallback.** `_find_app_image_invocation` returns `None` on ambiguous geometry
   (>1 candidate, digest tie). Decide the fallback: fail the delete (return `False`, surface via
   the existing failure path) vs. degrade to the old redaction. Recommendation to be argued in
   the doc — leaning **fail-safe (no redaction fallback)**, since redaction is the data-loss
   vector being removed.
3. **Marker + mutation bookkeeping.** The current branch deletes the marker annot and calls
   `_register_mutation`; the new path must keep both, and preserve the R6-01 forced `garbage=4`
   round-trip so a fully-orphaned image xref does not survive as recoverable (existing pin:
   `test_delete_image_object_removes_marker_and_page_image_ref` asserts image-count shrink).
4. **Shared-xref semantics.** Two app-images can share one image xref (identical bytes → PyMuPDF
   dedupe). Deleting one must remove only its invocation; the xref must survive while the
   neighbor still references it, and be GC'd when the last invocation goes. The design names the
   exact test matrix (§ PR-16).
5. **Undo interplay.** How `_restore_delete_transaction` (snapshot-based) behaves with the new
   path — expected unchanged, but state it explicitly.
6. **Form-nested images.** `_remove_native_image_invocation` already handles form-nested
   resources; confirm the app-image path can never be form-nested (app inserts at page level),
   or handle it.

**Files.** `plans/b1-delete-app-image-invocation-removal.md` (new). Optionally a TODOS note
pointing at it.
**Model.** Fable 5 (content-stream surgery design). Feed it: this plan, the §0.1.2 code
locations, `git show c099b28` (the move/rotate conversion), and codegraph context for
`_delete_object_impl` / `_remove_native_image_invocation`.
**Red-light test.** N/A (design-only) — but the design doc must **specify** every red-light test
PR-16 will write, including expected failing assertion messages.
**Validation commands.** `ruff check .` (no code should have changed); CI green (trivially).
**Manual checklist.** None.
**Rollback risk. None.** A markdown file.

**STOP POINT (hard).** After PR-15 merges: present the design to the user and **wait for explicit
approval**. Do not open PR-16 without it. If the design review finds the invocation-removal
approach unsound, return here — do not improvise an alternative inside PR-16.

---

## 5. PR-16 — B1 implementation: delete via invocation removal

**Scope.** Implement exactly what the approved PR-15 design specifies, red-light first:

1. Write the regression tests (below), run them, **show the failing output** in the PR
   description before any production edit.
2. Replace the image branch of `_delete_object_impl` (`model/pdf_object_ops.py` ~885–893):
   resolve via `_resolve_marker_image_invocation`, remove via
   `_remove_native_image_invocation`, keep marker-annot deletion + `_register_mutation` +
   the R6-01 GC round-trip. Drop `add_redact_annot`/`apply_redactions(PDF_REDACT_IMAGE_REMOVE)`
   from this path.
3. Codex adversarial review before merge (roadmap requirement for B1).
4. Same-commit docs: TODOS.md checkoff of "Delete app-image: drop PDF_REDACT_IMAGE_REMOVE";
   `docs/PITFALLS.md` entry if new content-stream gotchas surfaced; ARCHITECTURE.md only if a
   new helper became public API.

**Red-light tests** (all in `test_scripts/test_image_objects_model.py`, all synthesized in-test
via the existing `_png_bytes()`/`_make_pdf()` pattern — **no `test_files/` dependency, CI gates
every one of them**):

- `test_delete_overlapping_app_images_neighbor_survives` — mirror of
  `test_move_overlapping_app_images_both_survive`: A at (10,10,80,80), B overlapping at
  (40,40,110,110) with **distinct** pixel content (different colors → different digests);
  delete B; assert `discover_native_image_invocations` count 2→1, A still hit-detectable at
  its point, B's point empty. **This must fail on current main** (redaction erases A).
- `test_delete_one_of_two_shared_xref_images_neighbor_survives` — A and B from **identical**
  bytes (shared xref); delete B; neighbor invocation + xref survive.
- `test_delete_last_app_image_releases_xref` — behavior pin: existing
  `test_delete_image_object_removes_marker_and_page_image_ref` must stay green (sole image
  deleted → image gone from `page.get_images`); extend if the design says the GC guarantee
  needs a tighter assert.
- `test_delete_app_image_ambiguous_resolution_fails_safely` — construct the ambiguity the
  design's fallback decision covers (e.g. two same-digest images at near-identical rects);
  assert the decided behavior (expected: delete returns `False`, document unchanged, no
  redaction fired).
- `test_delete_app_image_then_undo_restores_both` — delete under overlap, undo, both images
  hit-detectable again (pins `_restore_delete_transaction` interplay).
- Save/reopen edge: delete one of the overlapping pair, `save_as`, reopen, neighbor still
  present (persistence of the rewritten stream).

**Files.** `model/pdf_object_ops.py`, `test_scripts/test_image_objects_model.py`, `TODOS.md`,
`docs/PITFALLS.md` (likely), `plans/b1-delete-app-image-invocation-removal.md` (decision log
updates).
**Model.** Fable 5 implements (content-stream surgery); codex plugin adversarial review before
merge.
**Validation commands.**
- Red phase: `.venv\Scripts\python.exe -m pytest test_scripts/test_image_objects_model.py -q -k delete` → new tests FAIL (output pasted in PR).
- Green phase: same command → all pass; then `.venv\Scripts\python.exe -m pytest -q` (full suite, no regressions vs. the fresh 1553 baseline).
- `ruff check .` ; `.venv\Scripts\python.exe -m mypy model/ utils/` ; `lint-imports`.
- CI: blocking windows functional leg green **including the new tests** (they're synthesized, so CI runs them — this is the point of the fixture constraint).

**Manual checklist (CI-blind residue — visual fidelity).**
- [ ] Launch the app, insert two overlapping images (different pictures), delete the top one:
      the bottom image's **pixels** are visually intact (CI asserts invocations, not rendering).
- [ ] Same check after save → reopen.
- [ ] Delete → undo → both images render correctly.
- [ ] Sanity: delete a native (non-app) image still works (that path is untouched but adjacent).

**Rollback risk. Medium-high** (highest of the milestone — content-stream rewriting). Mitigations:
single-file production diff (revertable in one `git revert`); the old redaction path remains in
git history; CI now gates the exact regression; codex review; the analogous move/rotate
conversion (`c099b28`) has been stable in production since it landed. If post-merge fallout
appears, revert PR-16 — the bug reverts to its known, documented state (data loss on overlap
delete) rather than something new.

**Stop point (soft).** After merge: run the manual visual checklist, report results, confirm one
subsequent CI run stays green before starting PR-17.

---

## 6. PR-17 — B2: R5-01 fileless print path

**Scope.** Eliminate the transient at-rest temp (`work_dir/input.pdf`) in
`controller/print_coordinator.py`. Current state (verified): worker writes the (possibly
re-encrypted) document to `tempfile.mkdtemp(prefix="pdf_editor_print_")/input.pdf` and hands the
path to the driver boundary. Target per TODOS: page-streamed raster submission (or a
password-aware driver boundary) so no document copy lands on disk, and the duplicate
full-document copies in memory are also reduced.

Two-phase inside one PR stream:
- **17-design (in-plan checkpoint, not a separate PR):** Fable 5 produces a design section in
  this plan file: chosen submission mechanism (raster page stream vs. driver-boundary change),
  worker-thread memory profile (page-at-a-time raster bounds peak RSS), failure/cancel paths,
  and what the automated test can assert. Reviewed at the stop point below **before**
  implementation starts.
- **17-impl:** red-light first, Sonnet 5 implements to the approved design.

If the design reveals the work exceeds one reviewable PR (TODOS flags it "large redesign"),
split: PR-17a raster-pipeline extraction, PR-17b temp elimination — decided at the checkpoint.

**Red-light tests** (mock the driver boundary; never require a real printer in CI):
- `test_print_job_writes_no_plaintext_temp` — run a print job against a mocked driver
  boundary while watching the temp directory: assert **no** `input.pdf` (or any document-bytes
  file) is created at any point (poll/patch `tempfile` + filesystem assertion). Must fail on
  current main (the file demonstrably appears).
- Password-protected source variant: same assertion + the driver receives decrypted page
  rasters while nothing decrypted lands on disk.
- Cancel mid-job: no orphaned temp dir, no partial file.
- Existing print flow tests (`test_print_controller_flow`, `test_print_speed`, marked flaky
  locally per closeout §5) must keep passing on CI.

**Files.** `controller/print_coordinator.py` (main), possibly a small raster helper in
`model/` (must respect layer rules: controller→model is legal), `test_scripts/test_print_*`
(existing + new), `TODOS.md`, `docs/ARCHITECTURE.md` (print-path responsibility change),
`docs/PITFALLS.md` (Windows driver quirks discovered).
**Model.** Fable 5 design; Sonnet 5 implement; codex review recommended (security-flavored).
**Validation commands.** Red output first for the new tests; then full suite +
`ruff check .` + mypy + `lint-imports`; CI green (windows blocking leg runs the mocked print
tests).

**Manual checklist (CI-blind — real hardware; the `local_only` real-printer test covers part).**
- [ ] Print a test page on the real printer from an unprotected PDF — output correct
      (orientation, scaling, margins vs. pre-change print of the same page).
- [ ] Print from a **password-protected** PDF — prompts as before, output correct.
- [ ] While printing, watch `%TEMP%` (`pdf_editor_print_*`): no document file appears.
- [ ] Cancel a multi-page job mid-print: spooler recovers, no stuck job, no temp residue.
- [ ] `test_win_print_fixes.py::test_set_page_layout_applies_size_on_real_printer`
      (`local_only`) passes locally.
- [ ] Kill stray `python.exe` before local print-test runs (closeout §5 orphaned-helper pitfall).

**Rollback risk. Medium.** Print is Windows-hardware-flavored and CI can't see the driver.
Mitigations: mocked-boundary tests pin the contract; the old path is one revert away; manual
checklist gates the merge, not post-merge hope. Known hazard: local print tests are the suite's
flakiest area (orphaned print-helper processes) — expect noise, follow the closeout §5 first
response (kill strays, rerun) before suspecting the diff.

**Stop points.** (a) After 17-design: user reviews the design section + the single-vs-split PR
decision. (b) After merge: manual printer checklist results reported before PR-18 starts.

---

## 7. PR-18 — B3: worker decrypted-bytes lifetime (bounded investigation)

**Scope.** TODOS frames this as conditional: "revisit only if a worker can be made to clear its
payload race-free on cancel." So PR-18 is a **bounded investigation with two legitimate exits**:

- **Exit A (fix):** a race-free mechanism exists (e.g. worker checks a generation/cancel flag at
  its next safe point and drops `self._doc_bytes = None`; or the coordinator swaps the reference
  for a weakly-held container the worker re-validates). Implement red-light-first in
  `controller/ocr_coordinator.py` (`_OcrWorker._doc_bytes`, line ~60) and
  `controller/search_coordinator.py` (line ~47).
- **Exit B (documented closure):** if every mechanism either blocks the UI thread (regresses the
  intentional non-blocking cancel) or leaves a race, write the finding into TODOS + PITFALLS and
  close the item as accepted residual risk (the live doc is decrypted in RAM regardless — the
  marginal exposure is a bounded-time worker snapshot).

Fable 5 makes the call with evidence; the exit decision is recorded in this plan file.

**Red-light test (Exit A only).**
- `test_cancelled_ocr_worker_releases_doc_bytes` — start OCR on an in-memory doc, cancel,
  drive the worker to its next cancellation checkpoint (deterministic via the existing
  generation counter), assert the worker's `_doc_bytes` reference is `None` /
  garbage-collectable (weakref goes dead) without joining the thread from the UI side.
  Analogous test for `search_coordinator`. Must fail before the fix.

**Files (Exit A).** `controller/ocr_coordinator.py`, `controller/search_coordinator.py`,
`test_scripts/test_ocr_controller_flow.py` / search-flow tests, `TODOS.md`.
**Files (Exit B).** `TODOS.md`, `docs/PITFALLS.md` only.
**Model.** Fable 5 (concurrency reasoning). Codex second opinion if Exit A's race argument is
subtle (high-stakes-decision convention).
**Validation commands.** Full suite + ruff + mypy + lint-imports; CI green; for Exit A the new
tests must be in the CI-gated selection (no fixtures needed — synthesized docs).
**Manual checklist.**
- [ ] Open a password-protected PDF, start OCR, cancel immediately, close the tab: no crash,
      no hang, UI stays responsive (the property Exit A must not regress).
- [ ] Same for search.
**Rollback risk. Low-medium (Exit A), None (Exit B).** Cancel-path changes can deadlock or drop
legitimate results if the generation check is misplaced; the red-light tests + the existing
cancel-flow tests pin behavior. Single-coordinator diffs, independently revertable.

---

## 8. Milestone-level stop/review points (summary)

1. **Before PR-13:** confirm main green (2–3 consecutive runs, per entry criteria).
2. **After PR-15 (B1 design): HARD STOP — user approval required before PR-16.** (Maintainer
   constraint; recorded at the top of this plan.)
3. **Before PR-16 red-light phase:** rerun the windows functional leg once for a fresh 1553
   baseline.
4. **After PR-16:** manual visual checklist + one subsequent green CI run before PR-17.
5. **After PR-17 design checkpoint:** user reviews the print-path design + single/split PR call.
6. **After PR-17:** manual printer checklist reported.
7. **After PR-18:** exit decision (fix vs. documented closure) recorded here; then milestone
   close: archive this plan to `plans/archive/`, PITFALLS/ARCHITECTURE/TODOS updated, end-of-M2
   smoke from the roadmap (app-level overlap-delete visual check + print temp-dir watch).

## 9. Milestone-level risks

- **B1 is the codebase's highest-regression-risk area** (content-stream rewriting). The whole
  design→approval→red-light→codex chain exists for it; do not shortcut any link.
- **Print-test flakiness pollutes signals** (orphaned helpers, COM `0x80040155`,
  `0xC0000142`) — triage against closeout §5 before attributing failures to PR-17's diff.
- **pip-audit can redden main without a commit** — check the job name first (closeout §6).
- **Coverage gate (75%)**: PR-16/17 add tested code, so coverage should rise; if a PR somehow
  trips the gate, that's a signal the new path is under-tested, not a reason to lower the gate.
- **Serial dispatch discipline** (CLAUDE.md §11): one subagent, one PR in flight at a time.
