# Unsupported Optimizer Options

This file tracks Acrobat-style optimizer controls that are intentionally not exposed in v1 of `另存為最佳化的副本`.

## Deferred Controls

- Separate image codec choices per family (`JPEG2000`, `ZIP`, `JBIG2`, `CCITT Group 3/4`, `MRC`)
  - Current v1 exposes DPI and JPEG-quality style controls only.
  - Reason: the current PyMuPDF + Pillow stack does not provide a clean, low-risk mapping for all PDF-native codecs.

- Full font unembedding policy matrix
  - Deferred options include "unembed recommended fonts", "unembed all fonts", and manual font pickers.
  - Reason: these options are high-risk for rendering fidelity and need explicit font-availability handling.

- Full object-removal matrix
  - Deferred options include JavaScript removal, bookmark removal, alternate-image removal, print-setting removal, and image-fragment merging.
  - Reason: v1 keeps the UI honest and only exposes removals with direct implementation support.

- Full user-data removal matrix
  - Deferred options include attachments, annotations/forms/media removal, external cross-references, link stripping, and hidden-layer flattening.
  - Reason: these need more document-structure analysis and higher regression coverage.

- Automatic / live audit refresh
  - v1 audit is on-demand only.
  - Reason: repeated xref scans on large PDFs would regress dialog responsiveness.
