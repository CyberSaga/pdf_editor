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
- [x] Add replacement-vocabulary counterfactual aggregates.
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
| default hscale × glyph OK | 23,385 | 0 |
| default hscale × source undecodable | 15 | 0 |
| default hscale × capability unavailable | 90 | 543 |
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
- Capability rejection is now decidable: the one unavailable Type0 font in
  each document is `type0_tounicode_unparseable` (one font, not one show).

The independent full-gate vector removes pre-gate double counting:

| sole-loss class | doc_0 | doc_1 |
| --- | ---: | ---: |
| all gates pass | 5,934 | 0 |
| `TJ` array only | 42 | 0 |
| non-default hscale only | 877 | 0 |
| `TJ` + non-default hscale only | 88 | 0 |
| other / multiple losses | 20,879 | 543 |

Arithmetic reconciliation:

- `doc_0` operator fold: 27,233 glyph-OK single-hex + 15 undecodable
  single-hex + 2 GID-beyond single-hex + 480 glyph-OK `TJ` + 90
  capability-unavailable `TJ` = 27,820 Type0 shows.
- `doc_1` operator fold: 543 capability-unavailable `TJ` = 543 Type0 shows.
- The sole-loss rows sum to 27,820 and 543 Type0 shows respectively, and
  `all_gates_pass == source_bindable == 5,934` for `doc_0` (both zero for
  `doc_1`). The 88-show intersection is separate, so it cannot inflate either
  cheap candidate. The unchanged funnel stages exactly match the sealed Task
  13 record, so no drift attribution is required.
- The 16,549 shows lost to the 4 MiB replay budget are 59.5% of all `doc_0`
  Type0 shows. That is the larger, separately tracked lever; the three P4
  candidates below compare only within the budget-eligible population.

The e2e-enabled second pass was attempted because the baseline completed
within 30 minutes, but it did not complete within its 30-minute ceiling and
was stopped without producing a valid artifact. E2E results therefore did not
run to completion in this record.

### Replacement-vocabulary counterfactual (2026-08-30, `--no-e2e`)

Population: the same positional two-document corpus. `doc_0` evaluates 261
Type0 fonts across 263 page references and 5,934 bindable shows; all 261 fonts
also occur in replayed page shows. `doc_1` evaluates one Type0 font across 18
page references, that font occurs in replay, and it has zero bindable shows.
Both documents report zero name-resolution mismatches and zero truncated
corpus-union fonts.
The raw aggregate-only JSON is gitignored at
`benchmarks/p4a-vocabulary-2026-08-30.json`. Candidate coverage uses the three
configured system font files through PyMuPDF face 0 only; it is a heuristic
upper bound, not the same-face proof performed by Commit 3.

Each cell is `encodable now % → after augmentation %`. Show weighting stores
integer show-character opportunities; dividing by vocabulary size gives
`Σ bindable_shows(font) × rate` without placing floats in the raw report.

| vocabulary / weighting | doc_0 | doc_1 |
| --- | ---: | ---: |
| fullwidth/punctuation — font | 2.61 → 99.62 | not augmentable: `type0_tounicode_unparseable` |
| fullwidth/punctuation — page | 2.59 → 98.86 | not augmentable: `type0_tounicode_unparseable` |
| fullwidth/punctuation — show | 4.07 → 100.00 | n/a (0 bindable shows) |
| CAD seed — font | 7.53 → 99.62 | not augmentable: `type0_tounicode_unparseable` |
| CAD seed — page | 7.48 → 98.86 | not augmentable: `type0_tounicode_unparseable` |
| CAD seed — show | 10.33 → 100.00 | n/a (0 bindable shows) |
| Japanese common — font | 2.62 → 99.62 | not augmentable: `type0_tounicode_unparseable` |
| Japanese common — page | 2.60 → 98.86 | not augmentable: `type0_tounicode_unparseable` |
| Japanese common — show | 3.55 → 100.00 | n/a (0 bindable shows) |
| SIP sample — font | 0.00 → 0.00 | not augmentable: `type0_tounicode_unparseable` |
| SIP sample — page | 0.00 → 0.00 | not augmentable: `type0_tounicode_unparseable` |
| SIP sample — show | 0.00 → 0.00 | n/a (0 bindable shows) |
| corpus union — font | 10.04 → 99.45 | n/a (empty union) |
| corpus union — page | 9.97 → 98.70 | n/a (empty union) |
| corpus union — show | 15.47 → 99.83 | n/a (0 bindable shows) |

Readings and arithmetic reconciliation:

- Vocabulary sizes are 25 fullwidth/punctuation, 220 CAD seed, 440 Japanese
  common, 12 SIP, and a runtime-only 604-character `doc_0` corpus union.
- For `doc_0`, corpus-union base buckets are: font-weighted 15,831
  encodable-now + 141,208 Unicode-unmapped + 1 GID-beyond + 604
  CID-unavailable = 157,644; page-weighted the same first three + 1,812
  CID-unavailable = 158,852; show-weighted 554,528 encodable-now + 3,029,606
  Unicode-unmapped + 2 GID-beyond = 3,584,136. Only
  `type0_unicode_unmapped` and `type0_glyph_missing` are augmentable in v1.
  Candidate coverage of unavailable / ambiguous / GID-range buckets remains
  visible under `candidate_supply|<verdict>` but is not credited.
- `doc_0` corpus-union show weighting has 554,528 encodable-now opportunities,
  3,023,672 augmentable candidate-supplied opportunities, and 3,578,200
  after-augmentation opportunities out of 3,584,136. The provisional
  augmentation headroom is `3,023,672 / 604 = 5,006.08` show-equivalents
  before the same-face A-family restriction.
- The three BMP-oriented candidates do not cover the SIP sample. The CAD list
  remains a seed pending domain-owner sign-off; `corpus_union` is the
  decision-grade vocabulary for Priority GO.
- `doc_1`'s only Type0 font is not augmentable because its ToUnicode is
  unparseable. Candidate face coverage is diagnostic only and no longer turns
  any row into false 100% headroom. Its runtime corpus union is empty and its
  show-weighted rates are undefined, not zero.

Priority is recorded in two like-for-like units (show-equivalents):

| Unit A — self-proxy / rearrange existing text | augmentation | whole `TJ` | hscale |
| --- | ---: | ---: | ---: |
| doc_0 | 0 | 42 | 877 |
| doc_1 | 0 | 0 | 0 |

| Unit B — corpus union / type a document character | baseline | augmentation | whole `TJ` | hscale |
| --- | ---: | ---: | ---: | ---: |
| doc_0 | 918.09 | 5,006.08 | 12.29 | 127.00 |
| doc_1 | n/a (empty union) | 0 | 0 | 0 |

The Unit-B arithmetic exceeds twice the best non-mutating candidate
(`5,006.08 > 2 × 127.00`) before the A-family restriction. This is not yet a
Priority GO: augmentation remains ineligible until Commit 3 supplies Safety
GO and restricts the numerator to proven A-family fonts. Unit A keeps the
cheap candidates' standalone value visible without mixing units.

Headline: the 100% replacement-encodable funnel value is a self-proxy
artefact. Show-weighted, only 15.5% of corpus-union characters are encodable
in a bindable `doc_0` show's font today (CAD seed 10.3%; fullwidth digits and
punctuation 4.1%). A character copied from elsewhere in the drawing therefore
fails encoding about 85% of the time even after source binding succeeds; that
is the gap augmentation addresses.

## 8. Open questions

- TTC candidates currently need all-face enumeration; `fitz.Font(fontfile=...)`
  observes face 0 only.
- Simple-font program bytes are not folded into the current page fingerprint.
- Text edits do not currently invalidate file-backed thumbnails.
- `fitz.TOOLS.store_shrink(100)` is process-global and cannot be considered a
  safe live-session mechanism without coordinator-level exclusion.
