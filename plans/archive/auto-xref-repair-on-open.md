# Plan: Auto-repair damaged XREF on open (replace manual toolbar action)

## Goal

Remove the manual **"修復 XREF 表"** file-tab toolbar action and replace it with an
automatic check-and-repair that runs when a PDF is opened: if PyMuPDF had to
rebuild a damaged cross-reference table on open (`doc.is_repaired`), transparently
round-trip the document in memory so the active document carries a clean,
internally-consistent xref. Healthy files are untouched.

## Why in-memory (not save-a-copy)

The old feature prompted a *Save As* dialog and wrote a clean copy to a new path.
On-open we cannot prompt the user for a path on every file, and silently
overwriting the source would be surprising/destructive. The in-memory round-trip
(`doc.tobytes(garbage=1, deflate=True)` → reopen) gives the user a working,
consistent document immediately; a later full save writes the clean structure to
disk. A repaired doc cannot be saved incrementally anyway, so losing the
incremental-save path for previously-damaged files is correct, not a regression.

## Affected modules

- `model/pdf_model.py` — add the check + in-memory repair inside `open_pdf`;
  remove the now-unused on-disk `repair_document_xref(output_path)` method.
- `view/pdf_view.py` — remove the toolbar action, the `_repair_document_xref`
  handler, and the `sig_repair_xref_requested` signal.
- `controller/pdf_controller.py` — remove the `repair_document_xref` handler and
  its signal wiring.
- `test_scripts/test_xref_repair.py` — repurpose to cover auto-repair-on-open.
- `docs/ARCHITECTURE.md`, `docs/pdf_compliance.md`, `docs/PITFALLS.md`,
  `TODOS.md` — update references.

## Steps

1. (Red) Rewrite `test_xref_repair.py`: opening a damaged PDF leaves
   `model.doc.is_repaired == False` (repaired in memory) with content intact;
   opening a healthy PDF stays file-backed (no needless round-trip).
2. (Green) Implement repair in `model.open_pdf` before the session is created.
3. Strip the view/controller UI surface and the dead model method.
4. Update docs + benchmark startup impact.

## Startup-speed evaluation (measured 2026-06-06)

Benchmark: text-heavy PDFs, median of 7 opens via `PDFModel.open_pdf`.

| pages | size     | healthy open | damaged open | added by auto-repair |
|-------|----------|--------------|--------------|----------------------|
| 10    | 86 KB    | 0.77 ms      | 10.6 ms      | +9.9 ms              |
| 50    | 432 KB   | 0.92 ms      | 50.6 ms      | +49.7 ms             |
| 200   | 1.74 MB  | 1.03 ms      | 205.3 ms     | +204.2 ms            |

- **Healthy files (the common case): no measurable impact.** The check is a single
  boolean read (`doc.is_repaired`) on a flag MuPDF already sets during the
  `fitz.open()` that runs regardless. Median open held ~1 ms across 10–200 pages,
  identical to before — healthy files never enter the repair branch.
- **Damaged files only: a one-time in-memory rebuild.** Paid once, on open, only
  for files MuPDF had to repair — which previously could not be saved incrementally
  at all.

### Large-file follow-up (the "200 MB → 20 s?" question)

The first cut used `tobytes(garbage=1, deflate=True)`, whose cost is ~20 ms/MB on
image-heavy content → ~10 s at the 512 MB open cap. `deflate=True` re-compresses
every stream, which is wasted on the already-compressed/incompressible data that
dominates large PDFs. Measured on random-noise (incompressible) image PDFs:

| size    | `garbage=1, deflate=True` | `garbage=1` (no deflate) | output size |
|---------|---------------------------|--------------------------|-------------|
| 117.6 MB| 2386 ms (20.3 ms/MB)      | 261 ms (2.2 ms/MB)       | unchanged   |
| 235.2 MB| 4910 ms (20.9 ms/MB)      | 592 ms (2.5 ms/MB)       | unchanged   |

`is_repaired` still clears either way. `deflate=False` copies existing streams
as-is (does not decompress), so output size and memory are unchanged.

**Real-file validation.** Damaged copy of `test_files/test-large-file.pdf`
(47 MB, 402 pages — corrupt the *last* `startxref` offset so MuPDF must rebuild):

| file              | open    | is_repaired | pages | backed-by |
|-------------------|---------|-------------|-------|-----------|
| healthy (orig)    | 2.8 ms  | False       | 402   | file      |
| damaged (repaired)| 240.6 ms| False       | 402   | memory    |

→ +238 ms (5.1 ms/MB, mixed content), `is_repaired` cleared, page count and
mid-page text **byte-identical** to the healthy file (no data loss).

**Decision:** use `tobytes(garbage=1)` (no deflate). At ~2.5 ms/MB (image) to
~5 ms/MB (mixed), a 200 MB damaged file repairs in ~0.5–1.0 s, ~1.3–2.6 s worst
case at the 512 MB cap — acceptable for a one-time, damaged-file-only op.
`garbage=1` (vs `garbage=0`) is ~free here and gives object compaction; full
duplicate-pruning + stream compression happen on an explicit save. Text-heavy PDFs
are object-count-bound rather than stream-bound (deflate ~neutral), but real
200 MB+ files are image-heavy — exactly where the win lands.

## Follow-up: encrypted documents must skip the round-trip (code-review finding)

A post-merge review found a silent regression: `doc.tobytes()` on an
authenticated encrypted doc emits a **decrypted** PDF, so round-tripping a file
that is *both encrypted and damaged* dropped its password/permissions on the next
save (and could emit broken streams — `MuPDF error: aes padding out of range`).

Detection is subtle — verified empirically (PyMuPDF 1.25.5):

| case | `needs_pass` | `is_encrypted` | `metadata['encryption']` |
|------|-------------|----------------|--------------------------|
| user-pw (after auth) | 1→0 on roundtrip | True→**False** | None → `'Standard V5 R6 256-bit AES'` |
| owner-only (empty user pw) | 0 | **False** | `'Standard V5 R6 256-bit AES'` |
| plain | 0 | False | None |

Both flags flip to False after `authenticate()`, and owner-only PDFs open with
both already False — only the **trailer encryption string** in `doc.metadata`
survives. The fix is **two parts** (a second review pass caught that the first cut
fixed only the in-memory half):

1. Gate the round-trip on `not _doc_is_encrypted(doc)` where `_doc_is_encrypted`
   reads `(doc.metadata or {}).get("encryption")` — keeps the live doc encrypted.
2. **Pass `encryption=fitz.PDF_ENCRYPT_KEEP` on every full-save-to-disk call.**
   `Document.save()`'s `encryption` default is `PDF_ENCRYPT_NONE` (1), *not* KEEP
   (0) — so `save(path, garbage=0)` with no explicit arg actively decrypts. A
   repaired doc can't save incrementally, so it always takes the full-rewrite path
   (`_full_save_to_path` / `save_as` full-save branch); without KEEP the password
   was still stripped *on disk* even though the live doc stayed encrypted.

Verified end-to-end through the real `model.save_as` (saved-back file:
`needs_pass=1`, `authenticate('usr')→2`, `is_repaired=False`, text intact).

**Part 3 (third review pass): re-authenticate the reopen-after-save handle.**
Preserving encryption surfaced a *new* regression: the save-over-open-file paths
close the live doc (to release the Windows lock) and `fitz.open(path)` again — but
that reopened handle is now locked (`needs_pass`) and nothing re-authenticated it,
so the live editing session went dead (`get_text()` raised "document closed or
encrypted"). `DocumentSession` did not persist the password. Fix: store the
open-time password on `DocumentSession.password` (in-memory only) and route both
reopen points through `_reopen_doc_after_save`, which re-authenticates when the
reopened doc `needs_pass`. Stress-verified: 170/170 encrypted save-backs preserve
content (live + disk) and keep the live doc usable.

Test gotcha learned: `needs_pass` stays 1 on an encrypted file even after a
successful `authenticate()` — assert `not is_encrypted` / that `get_text()` works,
not `needs_pass == 0`. Benign-but-noisy `aes padding out of range` warnings appear
when re-serializing a repaired encrypted doc (content verified byte-correct).

Covered by `test_open_damaged_encrypted_pdf_keeps_encryption` /
`test_open_damaged_owner_only_pdf_keeps_encryption`, which now `save_as` → reopen
→ assert the password survives **and** the live doc stays usable (the in-memory-only
assertions gave false confidence in the first cut; the on-disk-only assertions gave
false confidence in the second).

**Part 4: the same root cause hit every live-doc round-trip — made structural.**
`tobytes`'s encryption default is also NONE(1), so any `self.doc =
fitz.open(self.doc.tobytes(...))` silently decrypts the live doc in memory. Two
instances surfaced one-per-review: `_maybe_garbage_collect()` (every 20 edits) and
`_repair_active_doc_in_memory()` (error-recovery fallback for damaged docs — the
exact domain of this feature), each dropping the password on the next save even
with the save paths fixed (`metadata.encryption` → `None`).

Rather than keep patching call sites, the invariant is now **structural**: a
single chokepoint `_roundtrip_live_doc(garbage=, deflate=)` always serializes with
`encryption=KEEP` and re-authenticates the reopened handle
(`_reauthenticate_if_needed`, in-memory `DocumentSession.password`); it also opens
before closing so a failed round-trip leaves the live doc intact. Both GC and
in-memory repair route through it. A guard test (`test_live_doc_tobytes_calls_
preserve_encryption`) AST-scans the module and fails on any `self.doc.tobytes(...)`
without `encryption=`, so the next instance can't ship. Behavioral coverage:
`test_encrypted_doc_survives_periodic_gc`, `test_encrypted_doc_survives_in_memory_repair`.

Residual: undo/redo still round-trips through a *decrypted* snapshot
(`_restore_doc_from_snapshot`) — intentional (snapshots reopen without a password)
and not re-encryptable without re-authentication; separate, pre-existing.

## Follow-up: peak memory (code-review finding)

Measured on the real 47 MB damaged file (psutil RSS): original file-backed doc
+4.7 MB after open (lazy streaming), `tobytes` buffer ~1× (47.6 MB), reopen from
that same buffer +0. **Peak ≈ +54 MB ≈ 1.15× file size** — one serialization
buffer, not the ~2× the review estimated. No code change: the buffer is inherent
to in-memory round-trip; a temp-file approach would cut it but break the
memory-backed contract. Bounded to ~590 MB above baseline at the 512 MB cap.

## Open questions (resolved)

- `garbage=1` vs `garbage=4`? → `garbage=1` on open for speed; full pruning on save.
- `deflate=True`? → No. It was the dominant large-file cost and added nothing to a
  clean-xref repair. Dropped (~9× faster on large files).
- Async/background repair? → Not needed: bounded at ~1.3 s worst case by the 512 MB
  open cap, and a background doc-swap would fight PyMuPDF thread-safety + the
  batched-index design for marginal benefit.
- Encrypted docs? → Skip the round-trip (would strip encryption); keep MuPDF's
  repaired-but-encrypted doc and let the full save preserve protection.
