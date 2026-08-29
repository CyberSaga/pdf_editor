# Task 14 P4-A — Type0 augmentation census and mutation premises

**Base:** `task13/p3d-interpretation-reuse@c276018`  
**Working branch:** `task14/type0-augmentation-census`  
**Status:** in progress

## 1. Goal

Measure whether same-face Type0 glyph augmentation is safe and valuable before
adding any production mutation path. The work produces two independent
verdicts:

- **Safety GO / NO-GO:** based on serializer, font mutation, cache, revert,
  cross-page staleness, encryption, and raster-identity premises.
- **Priority GO:** compare augmentation, whole-`TJ`, and non-default horizontal
  scaling headroom in the common unit of bindable shows.

The corpus reports contain positional document/font/face identifiers and closed
count/status vocabularies only. They never contain paths, document text, font
names, resource names, or system-font stems.

## 2. Non-goals

- Do not add Tier 1b augmentation or change planner, engine, tier, or rollout
  behavior.
- Do not mutate a live user document; mutation probes use synthetic scratch
  documents only.
- Do not commit private PDFs, generated benchmark JSON, or system fonts.
- Do not use `canonical_pdf_text` as a PDF writer.
- Keep Fix A (V0c target-local proof) and Fix B (growth-background metric box)
  on independent branches based on `c276018`.

## 3. Affected modules

- `scripts/measure_type0_funnel.py`: glyph-overlap and vocabulary censuses.
- `scripts/type0_vocabulary.py`: closed replacement vocabularies and candidate
  font supplier.
- `scripts/audit_same_face.py`: dev-only fontTools proof census.
- `model/text_commit/cid_fonts.py`: legal PDF-value serializer.
- `scripts/probe_type0_mutation_premises.py`: synthetic premise matrix.
- Focused tests under `test_scripts/`, plus required architecture, pitfalls,
  TODO, and test-index documentation.

## 4. Data policy

Reports use `doc_i`, `font_i`, and `face_i`; closed slug vocabularies; and
integer/boolean leaves. Raw reports are written only beneath the gitignored
`benchmarks/` directory. This plan records aggregate counts and verdicts.

## 5. Locked decisions

1. Augmentation, if later approved, runs before `prepare_plan` and requires a
   multi-object mutation/revert surface.
2. `serialize_pdf_value` is the only production-package addition in P4-A.
3. fontTools remains dev-only and absence is reported as `fonttools_absent`.
4. Cache refresh mechanisms are measured; process-global `store_shrink(100)` is
   not assumed safe.
5. Augmentation must receive Safety GO and exceed twice the best non-mutating
   candidate before it can win Priority GO.

## 6. Step list

- [ ] Add this execution record and the dev-only fontTools dependency.
- [ ] Rerun the post-P2 funnel and add the independent glyph-overlap census.
- [ ] Add replacement-vocabulary counterfactual aggregates.
- [ ] Add the fontTools same-face proof census.
- [ ] Add `serialize_pdf_value` and the nine synthetic mutation premises.
- [ ] Record Safety and Priority verdicts, documentation, and verification.
- [ ] Implement Fix A and Fix B on their independent branches.

## 7. Decisions record

Corpus and premise records will be appended here after their artifacts exist.
Each corpus entry includes the date and mode, a population paragraph, a
positional aggregate table, readings, arithmetic reconciliation, and an
explicit note for any run that was not performed.

## 8. Open questions

- TTC candidates currently need all-face enumeration; `fitz.Font(fontfile=...)`
  observes face 0 only.
- Simple-font program bytes are not folded into the current page fingerprint.
- Text edits do not currently invalidate file-backed thumbnails.
- `fitz.TOOLS.store_shrink(100)` is process-global and cannot be considered a
  safe live-session mechanism without coordinator-level exclusion.
