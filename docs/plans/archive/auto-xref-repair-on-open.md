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
- **Damaged files only: a one-time in-memory rebuild** that scales with content
  (~0.1 ms per KB here; a large scanned PDF could be a second or two). It is paid
  once, on open, and only for files MuPDF had to repair — which previously could
  not be saved incrementally at all.

Decision: `garbage=1` chosen (fast xref rebuild + compaction); full
duplicate-pruning still happens on an explicit full save.

## Open questions

- Keep `garbage=1` (fast, compacts + rebuilds xref) vs `garbage=4` (heavier,
  prunes duplicates)? Decision: `garbage=1` on open for speed; full pruning still
  happens on an explicit full save.
