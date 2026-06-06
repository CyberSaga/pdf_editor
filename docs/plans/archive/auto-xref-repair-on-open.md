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

## Open questions (resolved)

- `garbage=1` vs `garbage=4`? → `garbage=1` on open for speed; full pruning on save.
- `deflate=True`? → No. It was the dominant large-file cost and added nothing to a
  clean-xref repair. Dropped (~9× faster on large files).
- Async/background repair? → Not needed: bounded at ~1.3 s worst case by the 512 MB
  open cap, and a background doc-swap would fight PyMuPDF thread-safety + the
  batched-index design for marginal benefit.
