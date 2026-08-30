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
- [x] Add the fontTools same-face proof census.
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
- Relaxing the 4 MiB replay budget exposes a stage-loss upper bound of 16,549
  rejected single-hex-`Tj` shows (27,250 − 10,701). Those shows can still fail
  marked-content, TRM, state, decode, or glyph gates, so this bound belongs to
  neither Unit A nor Unit B. It remains tracked separately; the latency half
  of budget relaxation is open.

The e2e-enabled second pass was attempted because the baseline completed
within 30 minutes, but it did not complete within its 30-minute ceiling and
was stopped without producing a valid artifact. E2E results therefore did not
run to completion in this record.

### Replacement-vocabulary counterfactual (2026-08-30, `--no-e2e`)

Population: the same positional two-document corpus. `doc_0` evaluates 261
Type0 fonts across 263 page references and 5,934 bindable shows; all 261 fonts
also occur in replayed page shows. `doc_1` evaluates one Type0 font across 18
page references, that font occurs in replay, and it has zero bindable shows.
Both documents report zero name-resolution mismatches, zero replayed fonts
outside the population, zero population fonts without replayed shows, zero
truncated corpus-union fonts, and zero `page_replay_malformed` diagnostics.
The latter is recorded on both sides because any nonzero value would make the
corresponding counts upper bounds.
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
  `candidate_supply|encodable_now` is structurally zero because already
  encodable characters are never candidate-supply opportunities.
- `doc_0` corpus-union show weighting has 554,528 encodable-now opportunities,
  3,023,672 augmentable candidate-supplied opportunities, and 3,578,200
  after-augmentation opportunities out of 3,584,136. The provisional
  augmentation headroom is `3,023,672 / 604 = 5,006.08` show-equivalents
  before the same-face A-family restriction.
- The three BMP-oriented candidates do not cover the SIP sample. The CAD list
  remains a seed pending domain-owner sign-off; `corpus_union` is the
  decision-grade vocabulary for Priority GO.
- Both documents' sole `type0_tounicode_unparseable` font records
  `array-destination bfrange is outside the v1 grammar`; these values come
  from the closed, code-authored reject-detail key space.
- All 543 `doc_1` Type0 shows are `TJ` on one font whose ToUnicode verdict is
  `type0_tounicode_unparseable`. Whole-`TJ` admission therefore has zero
  `doc_1` headroom unless the v1 ToUnicode grammar is extended. P4-B (b) is a
  TJ-and-grammar item and must be re-costed with this blocker named.
  Candidate face coverage is diagnostic only and no longer turns any row into
  false 100% headroom. Its runtime corpus union is empty and its show-weighted
  rates are undefined, not zero.

Priority is recorded in two like-for-like units (show-equivalents):

| Unit A — self-proxy / rearrange existing text | augmentation | whole `TJ` | hscale |
| --- | ---: | ---: | ---: |
| doc_0 | 0 | 42 | 877 |
| doc_1 | 0 | 0 | 0 |

| Unit B — corpus union / type a document character | baseline | augmentation | whole `TJ` | hscale |
| --- | ---: | ---: | ---: | ---: |
| doc_0 | 918.09 | 5,006.08 | 12.29 | 127.00 |
| doc_1 | n/a (empty union) | 0 | 0 | 0 |

The provisional Unit-B arithmetic exceeds twice the best non-mutating
candidate (`5,006.08 > 2 × 127.00`) before the A-family restriction. It is
therefore a pre-Commit-3 upper bound, not a Priority verdict; the same-face
record below supersedes it. Unit A keeps the cheap candidates' standalone
value visible without mixing units.

Headline: the 100% replacement-encodable funnel value is a self-proxy
artefact. Show-weighted, only 15.5% of corpus-union characters are encodable
in a bindable `doc_0` show's font today (CAD seed 10.3%; fullwidth digits and
punctuation 4.1%). A character copied from elsewhere in the drawing therefore
fails encoding about 85% of the time even after source binding succeeds; that
is the gap augmentation addresses.

The Commit 2c `--no-e2e` rerun left every recorded funnel and counterfactual
number unchanged. In particular, sole-loss rows still sum to 27,820 / 543,
`all_gates_pass == source_bindable == 5,934`, and Unit B remains
554,528 / 3,023,672 / 7,424 / 76,711 over vocabulary size 604, or
918.09 / 5,006.08 / 12.29 / 127.00 show-equivalents.

### Same-face proof census (2026-08-30, fontTools; Commit 3b rerun)

Population: the same positional two-document corpus, with all faces of all
three configured candidate files enumerated. Seven candidate faces loaded,
all with allowed `fsType` 0x0008. The audit evaluated 261 `doc_0` Type0 fonts
and one `doc_1` Type0 font, skipped zero documents, and emitted integer counts
and closed slugs only. Its raw aggregate report is gitignored at
`benchmarks/p4a-same-face-2026-08-30.json`.

| proof class | doc_0 | doc_1 | combined |
| --- | ---: | ---: | ---: |
| `A_same_gid_exact` | 48 | 1 | 49 |
| `A_same_gid_exact_shared_program` | 95 | 0 | 95 |
| `face_unproven` | 118 | 0 | 118 |

The shared-program class requires every allowed match to be exact at the
embedded GIDs, byte-identical `glyf`/`loca`/`hmtx` tables with equal UPEM and
glyph count, and unanimous cmap-to-GID agreement for each supplied character.
Multiple names for one TTC glyph program are therefore no longer treated as
proof ambiguity. Composite components are compared transitively even when an
embedded component is empty, corrupt embedded glyph programs are reported as
`program_unreadable`, and an empty candidate set makes `--same-face` exit 2.

The labelled heuristics remain non-proof diagnostics. `/W` supplied max CID
for all 262 fonts. `numGlyphs` was greater than `maxCID + 1` for 261 fonts and
less than or equal to `maxCID` for one; subset tags were present for 6 and
absent for 256.

The proof-class × sole-loss cross-tab for `doc_0` reconciles to 27,820 Type0
shows, 5,934 bindable shows, and 877 hscale-only shows:

| proof class | fonts | Type0 shows | bindable | `TJ` only | hscale only | `TJ`+hscale | over budget | downstream |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| exact | 48 | 137 | 0 | 0 | 36 | 0 | 11 | 90 |
| shared program | 95 | 14,476 | 4,292 | 42 | 195 | 0 | 8,827 | 1,120 |
| unproven | 118 | 13,207 | 1,642 | 0 | 646 | 88 | 7,947 | 2,884 |

The 48 strict exact fonts have no bindable shows because their 137 shows are
36 hscale-only losses, 11 over-budget losses, and 90 downstream losses. The
1,642 bindable shows on unproven fonts are a candidate-list question for P4-B,
not evidence that the shared-program proof failed.

The production-equivalent `--same-face --no-e2e` run admits both exact proof
classes and applies per-character agreement in memory. It reports 143 eligible
`doc_0` fonts and 4,292 eligible bindable shows. The three Unit-B views are:

| Unit B rule (`doc_0`, corpus union) | baseline | augmentation | whole `TJ` | hscale |
| --- | ---: | ---: | ---: | ---: |
| unrestricted candidate upper bound | 918.09 | 5,006.08 | 12.29 | 127.00 |
| strict unique-face only | 918.09 | 0 | 12.29 | 127.00 |
| exact + shared-program agreement | 918.09 | 3,326.47 | 12.29 | 127.00 |

The shared-program row is `554,528 / 2,009,190 / 7,424 / 76,711` over 604.
Its augmentation headroom is 26.2× hscale and satisfies the 2× rule. Unit A
is separate: hscale leads at 877 newly bindable shows versus whole-`TJ` 42,
while augmentation is zero because it changes character encodability rather
than source-show bindability.

Priority pick is deferred to the §7 verdict step after Commit 4. If the
mutation premises produce Safety GO, shared-program augmentation leads Unit B
by 26×; if Safety is NO-GO, hscale is the fallback. Whole-`TJ` remains a
TJ-and-ToUnicode-grammar item on `doc_1`, not hidden headroom in this comparison.

Commit 2d overwrote all four aggregate artifacts. Both unrestricted and
`--same-face --no-e2e` reports persist zero malformed-replay pages/shows, zero
shared-stream pages/shows, and zero unreadable-content pages for both corpus
documents. `all_gates_pass == source_bindable == 5,934`; the unrestricted and
shared-program numerators above are unchanged. The inverse stream-owner index
matches production's fail-closed membership while avoiding a per-stream
whole-document rescan. The allowed-match set excludes restricted faces: one
allowed exact face plus a restricted match remains a unique usable face, while
two restricted matches remain `embedding_restricted`.

## 8. Open questions

- The proof path enumerates all TTC faces; the diagnostic
  `system_candidate_supplier` still observes face 0 only through `fitz.Font`.
- Simple-font program bytes are not folded into the current page fingerprint.
- Text edits do not currently invalidate file-backed thumbnails.
- `fitz.TOOLS.store_shrink(100)` is process-global and cannot be considered a
  safe live-session mechanism without coordinator-level exclusion.
