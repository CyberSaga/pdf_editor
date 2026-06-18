# Phase R5 — Security & Supply-Chain Hardening

**Status:** Ready (after R3 print-coordinator; share its regression pass). **Fusion:** 3-model for
the disk-leak + OCR bundle; 2-model for the guard strengthening. **Why:** most of the prior
security campaign holds; this phase closes the **two genuinely open** residuals and tightens the
guard. (Census: security lens; critique HAZARD 6.)

> **Already fixed / accepted — DO NOT re-propose:** page-level plaintext undo snapshots (deferred
> in-memory defense-in-depth, not a save-back bug); Pillow `.venv`=12.2.0 == declared floor;
> transformers CVE-2026-1839 / PYSEC-2025-217 (upstream-blocked — no surya release validated
> against transformers 5.x; a blind bump is intentionally not done).
>
> **Moved to R2 (quick-wins):** `pdf_renderer.py:84` `safe_render_scale` clamp;
> `compose_merged_document`/`open_merge_source` `_guard_foreign_doc` routing.
>
> **Implicit risks:** the disk-leak fix must guarantee temp-dir cleanup on **all** exit paths
> incl. subprocess crash/terminate; switching the print input to `encryption=KEEP` means the helper
> subprocess must now authenticate (can break printing encrypted docs if the password isn't
> plumbed). The OCR bundle item is a packaging/vetting task, not a code change.

---

## R5.1 — Print worker writes a FULLY DECRYPTED copy to disk (HIGH, 3-model)

- `capture_worker_snapshot_bytes` (`pdf_model.py:3200-3204`) returns
  `self.doc.tobytes(..., encryption=fitz.PDF_ENCRYPT_NONE)` — explicitly **decrypts**. The
  controller `mkdtemp(prefix='pdf_editor_print_')` (`:1650`), captures bytes (`:1657`), and
  `_PrintSubmissionWorker.run()` writes them to `work_dir/input.pdf` (`:134-135`). For an
  encrypted source this writes the **fully decrypted PDF to disk**. The existing "snapshot bytes
  never reach disk" note covers undo snapshots, **not** this print path. (search/OCR receive the
  same decrypted bytes but keep them in-memory — same class, only print persists.)
- **Fix — pick one, decide via the 3-model design pass:**
  - **(A) keep encryption:** write `encryption=KEEP` to `input.pdf` and have the helper
    authenticate with the session password plumbed through `job.json` (base64, JSON-safe). Closes
    the at-rest exposure entirely.
  - **(B) restrict + guarantee cleanup:** create `work_dir` with `0700` perms and guarantee
    `shutil.rmtree` on **every** exit path including subprocess crash/terminate/stall — reduces but
    does not eliminate the window.
  - Prefer (A); fall back to (B) if password plumbing to the helper is infeasible.
- **Shared regression pass with R3.2 print_coordinator** — same handoff surface.

## R5.2 — OCR weights: ship a vetted bundle + populate digests (3-model, packaging)

> **STATUS: BLOCKED — out-of-band human step (2026-06-18).** This is explicitly a *packaging,
> not code* task and cannot be completed by the agent: it requires obtaining a real surya
> 0.17.x checkpoint set (large binary weights from surya's S3), **vetting** it, computing the
> SHA256 digests from those exact files, and **distributing** the bundle out-of-band. The
> enforcement code is already complete and wired (`ocr_tool.py:141 enforce_weights_policy`;
> `ocr_weights.py` SHA256-verifies and **fails closed on an empty manifest**), so populating
> `WEIGHTS_MANIFEST` or defaulting `PDF_EDITOR_OCR_WEIGHTS_DIR` *before* the bundle exists would
> only break OCR (missing dir / empty manifest → fail-closed), not improve security. No safe
> autonomous change remains. **Unblock requires:** a maintainer vets + ships the bundle, then
> populates `WEIGHTS_MANIFEST` with the measured digests and defaults the env var in the packaged
> build (follow `docs/ocr-weights-verification.md`). Until then the runtime stays on the
> revision-pinned online fetch (protection present but inert). **R5 ships at 4/5** (R5.1 ✅, R5.3 ✅
> in R2.2, R5.4 ✅, R5.5 ✅).

- The integrity layer is **complete and wired** (`ocr_tool.py:141 enforce_weights_policy`;
  `ocr_weights.py` SHA256-verifies + fails closed on empty manifest; revision pins) — but
  `WEIGHTS_MANIFEST = {}` is empty and no bundle ships. With no `PDF_EDITOR_OCR_WEIGHTS_DIR`, the
  policy takes the `weights_dir is None` branch (`:189-192`) = revision-pinned **online fetch from
  surya's S3 with no content-hash verification** (CWE-494). Protection exists but is **inert**.
- **Fix (packaging, not code):** vet a surya 0.17.x checkpoint set, compute SHA256 via
  `sha256_file`, populate `WEIGHTS_MANIFEST`, ship the bundle out-of-band, and default
  `PDF_EDITOR_OCR_WEIGHTS_DIR` in the packaged build so OCR loads **offline + verified**. Follow
  `docs/ocr-weights-verification.md`.

## R5.3 — Strengthen the encryption AST guard (2-model) — ✅ DONE in R2.2 (2026-06-15)

- **Landed in R2.2** (`test_xref_repair.py::test_live_doc_roundtrips_preserve_encryption`): the guard
  now walks **all of model/**, catches the `self.doc` / `model.doc` / `self._model.doc` receivers,
  attributes each call to its enclosing function, uses a **function-scoped decrypt-sink allowlist**,
  and **strengthens** so an explicit `encryption=PDF_ENCRYPT_NONE` is allowed only on that allowlist
  (presence of `encryption=` is no longer sufficient). Teeth verified — it flags the optimizer
  `model.doc.tobytes()` sites when they are un-allowlisted.
- Allowlist: `pdf_model.capture_worker_snapshot_bytes` (explicit NONE worker snapshot),
  `pdf_optimizer.current_document_size_bytes` (size measured via `len()` then discarded), and
  `pdf_optimizer.build_working_doc_for_optimized_copy` (flagged — see **R5.5**).

## R5.4 — Packaging guard test (2-model)

- The wheel is safe (allow-list discovery) but there is no automated assertion. Pair with R1.3's
  `MANIFEST.in`: a guard test builds a wheel **and** sdist into a temp dir and asserts no member
  path contains `scripts/` or `test_scripts/`. Wire into CI.

## R5.5 — Optimize-copy decrypts an encrypted source (HIGH, surfaced by R2.2)

- `build_working_doc_for_optimized_copy` (`model/pdf_optimizer.py:347`): for an **encrypted** live
  doc, `_resolve_file_backed_optimize_source` returns `None` (the `needs_pass` gate at `:310`), so
  the working copy is built from `fitz.open("pdf", model.doc.tobytes(...))` — a **decrypted**
  serialization (`tobytes` defaults to `encryption=NONE`). The optimized output (`working_doc.save`
  at `:797`) is then written **without encryption**, so 另存為最佳化的副本 of a password-protected
  PDF silently produces an unprotected copy. Same class as **R5.1** (print decrypts to disk); **not**
  previously tracked. The R2.2 guard allowlists `:347` with a `KNOWN GAP` flag so the net stays
  green — this item is the fix.
- **Fix — product decision (pick one; 3-model, security-invariant-adjacent):**
  - **(A) preserve encryption:** carry the source's encryption (and session password) into the
    optimized copy's final save (`encryption=KEEP`, or re-apply the encryption dict + permissions
    via pikepdf). Keeps the protection the user had.
  - **(B) refuse + inform:** detect `needs_pass`/`is_encrypted` before optimizing and either disable
    the optimize-copy action for encrypted docs or require explicit confirmation that the copy will
    be unprotected.
  - Prefer (A) if PyMuPDF/pikepdf can re-encrypt the optimized output with equivalent parameters;
    fall back to (B). `current_document_size_bytes:332` is **safe** (bytes measured then discarded)
    and stays allowlisted.
- **Red-light:** optimize an encrypted PDF, assert the output `needs_pass` (A) OR the action is
  refused/warns (B). Before the fix, the optimized output opens with no password.

---

## Fusion Protocol Playbook

- **R5.1 / R5.2:** Playbook **4.6 + security-review**, **3-model** (manual §3 mandatory):
  ```powershell
  .venv\Scripts\python.exe scripts/fusion.py `
      "An encrypted PDF is being decrypted to disk at work_dir/input.pdf for printing
       (capture_worker_snapshot_bytes uses PDF_ENCRYPT_NONE). Compare two fixes: (A) write
       encryption=KEEP + helper authenticates via plumbed password; (B) 0700 temp dir + guaranteed
       rmtree on all exit paths incl subprocess terminate. Which is safer and what does each break
       for the encrypted-print path?" `
      --file model/pdf_model.py --file controller/pdf_controller.py --file src/printing/helper_main.py --no-synthesize
  # then /codex:rescue same prompt + files, then synthesize per §3.
  ```
- **R5.3 / R5.4:** Playbook **4.6**, 2-model (mechanical guard/test additions).

## Verification & Gatekeeping

```powershell
# R5.1 — encrypted print must keep working AND leave no decrypted bytes on disk:
.venv\Scripts\python.exe -m pytest test_scripts/test_print_snapshot_path.py test_scripts/test_print_controller_flow.py -v
# Red-light: print an encrypted doc, assert work_dir/input.pdf is encrypted (needs_pass=1) OR work_dir is gone post-job.
.venv\Scripts\python.exe -m pytest test_scripts/test_xref_repair.py -v          # strengthened encryption guard
.venv\Scripts\python.exe -m pytest test_scripts/test_ocr_tool_surya.py -v        # weights policy (if surya present)
.venv\Scripts\python.exe -m pytest test_scripts/test_security_packaging.py -v    # new R5.4 build-artifact guard
.venv\Scripts\python.exe -m pytest test_scripts/ -q --tb=line -p no:cacheprovider
# pip-audit gate (existing CI job):
pip-audit -r requirements.txt -r optional-requirements.txt
```

**Gate:** R5.1 needs a red-light asserting decrypted bytes never persist (encrypted temp OR
guaranteed-removed dir) **before** the fix; the encrypted-print happy path must stay green.

## Risk Triage (2→3 upgrade points)

- **R5.1/R5.2 → 3-model** (trigger #2 security-invariant-adjacent: password/`tobytes`/foreign
  weights). **R5.3/R5.4 → 2-model** (guard/test additions, no live-doc behavior change).
- **Vectors:** leaked `work_dir` on subprocess terminate (decrypted PDF on disk); `encryption=KEEP`
  breaking encrypted-print if password isn't plumbed to the helper; an over-tight merge guard (now
  in R2) rejecting legitimate large docs.

## Docs (same commit)

- `docs/ARCHITECTURE.md §6`: document the secure print-input contract (encrypted temp OR
  ephemeral-dir guarantee); `docs/security/`: update the OCR-weights bundle status.
- `docs/PITFALLS.md`: "print snapshot writes decrypted bytes to disk — keep encryption or guarantee
  rmtree"; "AST encryption guard is presence-only — allowlist intentional decrypt sinks".
- `TODOS.md`: mark "F9 bundle distribution" (when bundle ships) + "scripts/ packaging guard" done;
  keep the transformers CVE item as upstream-blocked (do not close).

## Commit

Per item: `security: R5.<n> <item>`. `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
