# PDF Standards Compliance

This document records which PDF standard(s) the editor's output targets and how
that is verified. References for the standards themselves are in
[`docs/pdf_standards.txt`](pdf_standards.txt) (pdfa.org, pdf-tools.com, Wikipedia).

## Target standard

- **ISO 32000-1 (PDF 1.7)** structural conformance. The editor reads and writes
  documents through PyMuPDF (MuPDF), which produces ISO 32000-1 structured
  output (objects, cross-reference table/streams, page tree, content streams).
- Files saved at version **PDF 1.4+** are supported; the version header from the
  source document is preserved on save.
- We target **structural well-formedness**, not full **PDF/A** archival
  conformance. PDF/A additionally requires embedded fonts, no encryption, colour
  profiles, and XMP metadata that this editor does not guarantee. PDF/A is out of
  scope; the standards links above describe it for reference.

## What "conformant" means here

A document is considered structurally conformant when all of the following hold
(checked by `model/pdf_validator.py::check_pdf_conformance`):

1. The file opens with a recognisable **PDF version header**.
2. The **cross-reference table** is intact — PyMuPDF did not have to rebuild it
   on open (`Document.is_repaired` is false).
3. The **page tree** is parseable and contains at least one page; every page
   object resolves and its content is dereferenceable (so a reference reachable
   from a page — content stream, font, XObject — that dangles is caught).
4. Every in-use **object reference** resolves to an object definition (the xref
   scan flags entries that fail to parse).

Encrypted/password-protected documents that are not authenticated cannot be
structurally validated and are reported as such rather than passing silently.

`check_pdf_conformance(path)` returns a list of human-readable issues; an empty
list means no structural problems were detected. `is_pdf_conformant(path)` is a
boolean convenience wrapper.

## The XREF-repair feature as a conformance safeguard

The most common way a PDF becomes non-conformant in practice is a damaged
**cross-reference table** (truncated downloads, broken `startxref` offsets,
incremental-update corruption). The editor's **automatic XREF repair** addresses
exactly this, transparently on open (there is no manual action):

- PyMuPDF rebuilds a damaged xref when it opens the file and flags it via
  `doc.is_repaired`. `PDFModel.open_pdf` detects that flag and round-trips the
  document in memory (`doc.tobytes(garbage=1)` → reopen) so the active document
  carries a fresh, internally-consistent xref before any edit. It skips
  `deflate=True` on purpose — stream re-compression is the dominant cost on large
  files (≈20 ms/MB) and buys nothing for a clean-xref repair, so the round-trip
  stays at ≈2.5–5 ms/MB (~1.3–2.6 s worst case at the 512 MB open cap; a real
  damaged 47 MB / 402-page file repaired on open in ~240 ms).
- Reading `doc.is_repaired` is free (the flag is set during the `fitz.open()`
  that runs regardless), so healthy files pay nothing; the round-trip cost is
  incurred only for files that were actually damaged.
- After the in-memory repair, `check_pdf_conformance` reports a clean result
  (the "cross-reference table is damaged" issue clears), which is the verifiable
  evidence that the repair restored structural conformance. A subsequent full
  save writes the clean structure to disk (a previously-damaged document cannot
  be saved incrementally, so it falls back to a full rewrite automatically).

## How to verify

```
pytest test_scripts/test_pdf_compliance.py
```

The suite proves:

- a well-formed PDF (and the repository sample `test_files/01_報告書.pdf`)
  reports **no** issues;
- a PDF with a deliberately corrupted `startxref` offset is **flagged** with a
  cross-reference issue;
- an unopenable file is reported rather than silently passing.

## Known limitations

- This is a structural check, not a semantic/visual one, and not a PDF/A
  validator. For formal PDF/A verification, use an external tool such as
  veraPDF (a corpus is vendored under `test_files/veraPDF-corpus-staging`).
- The object-reference scan flags references that fail to resolve; it does not
  validate the semantic correctness of every object's contents.
