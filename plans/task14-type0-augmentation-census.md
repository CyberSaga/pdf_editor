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

- [x] Add this execution record and the dev-only fontTools dependency.
- [x] Rerun the post-P2 funnel and add the independent glyph-overlap census.
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

### Post-P2 funnel and glyph-overlap record (2026-08-30, `--no-e2e`)

Population: the sealed two-document private corpus at `c276018`, reported only
as positional aggregates. `doc_0` has 50 pages; `doc_1` has 23 pages. The raw
aggregate-only JSON is gitignored at
`benchmarks/p4a-funnel-2026-08-30.json`.

| aggregate | doc_0 | doc_1 |
| --- | ---: | ---: |
| shows total | 28,043 | 2,237 |
| Type0 shows | 27,820 | 543 |
| single-hex `Tj` | 27,250 | 0 |
| source bindable | 5,934 | 0 |
| replacement-encodable self proxy | 5,934 | 0 |
| `TJ` array × glyph OK | 480 | 0 |
| `TJ` array × capability unavailable | 90 | 543 |
| non-default hscale × glyph OK | 4,328 | 0 |
| non-default hscale × GID beyond glyph count | 2 | 0 |
| mapped CID with glyph | 15,607 | 0 |
| mapped CID without glyph | 225 | 0 |
| glyph-present CID without ToUnicode | 7,722 | 0 |

Readings:

- The sealed post-P2 funnel is unchanged from the 2026-08-20 record:
  `doc_0` has 28,043 total shows, 27,820 Type0 shows, 27,250 single-hex
  `Tj`, 10,701 within budget, 6,872 outside marked content, 6,413 rotated
  admitted, and 5,934 replacement-encodable proxies. `doc_1` again has
  543 Type0 shows and zero survival past the single-hex gate.
- The independent operator fold exposes 480 glyph-usable `TJ` shows in
  `doc_0`; the other 90 `TJ` shows lack a CID capability. All 543 `doc_1`
  `TJ` shows lack a CID capability, so they are not counted as glyph-usable.
- The independent hscale fold exposes 4,328 glyph-usable non-default-hscale
  shows plus two whose GID exceeds the embedded glyph count. This is larger
  than the main fold's 892 `state:hscale` losses because the independent fold
  runs before operator, replay-budget, marked-content, and TRM early exits.
- The array census measures glyph availability after replay drops kern
  numbers; it does not claim byte-bindability for whole-`TJ` mutation.

Arithmetic reconciliation:

- `doc_0` operator fold: 27,233 glyph-OK single-hex + 15 undecodable
  single-hex + 2 GID-beyond single-hex + 480 glyph-OK `TJ` + 90
  capability-unavailable `TJ` = 27,820 Type0 shows.
- `doc_1` operator fold: 543 capability-unavailable `TJ` = 543 Type0 shows.
- Both hscale folds independently sum to the same Type0-show populations.
  The unchanged funnel stages exactly match the sealed Task 13 record, so no
  drift attribution is required.

The e2e-enabled second pass was attempted because the baseline completed
within 30 minutes, but it did not complete within its 30-minute ceiling and
was stopped without producing a valid artifact. E2E results therefore did not
run to completion in this record.

## 8. Open questions

- TTC candidates currently need all-face enumeration; `fitz.Font(fontfile=...)`
  observes face 0 only.
- Simple-font program bytes are not folded into the current page fingerprint.
- Text edits do not currently invalidate file-backed thumbnails.
- `fitz.TOOLS.store_shrink(100)` is process-global and cannot be considered a
  safe live-session mechanism without coordinator-level exclusion.
