# Task 15 P4-B2 — Exact painter geometry, read-only value spike

**Base:** `task15/p4-b1-hscale-admission@49c98ee` (frozen; see
`plans/2026-09-01-p4b1-final-review-verdict.md`)
**Working branch:** `task15/p4-b2-exact-painter-geometry-spike`
**Status:** commit 0 — design, gates, counters and tolerances pre-registered;
no measurement code exists yet.

## 1. Goal

Decide, by measurement, whether exact painter-event geometry (per-glyph outline
bounds placed by the painter's own text state) can safely replace the
declared-advance "exact extent" quad in the duplicate-painter gate
(`model/text_commit/plan.py:283-496`), whose proof the P4-B1 review showed
unsound. Two verdicts:

- **Safety GO / NO-GO:** the spike gate rejects every known false admit
  (`/W 0`, `/W 1`, core-band, negative `Tc`/`Tw`, width clones) and never
  reports `exact_safe` when single-painter rasters overlap.
- **Value GO / NO-GO:** how many of the 2,146 exact-quad-dependent admissions
  are re-proved, how many of the 187 `duplicate_painter_only` rows become
  decidable, and at what per-page cost.

The spike is read-only: it never changes production admission.

## 2. Non-goals / hard constraints

- No change to `model/`, `PreparedEdit`, production admission, PDF content, or
  `main`. New code lives in `scripts/`, `test_scripts/`, `plans/` only.
- No merge, no PR, no push unless the user asks. Sealed corpus paths are
  CLI-only and never committed; sealed documents are never saved.
- Aggregate-only output (closed slug tuples + `Counter` + closed projection at
  emit): no document text, basefont or resource names, filenames, OCG labels,
  glyph names, exception text, or non-ASCII. Identity stays in memory.
- No font mutation, no `store_shrink(100)`; augmentation stays Safety NO-GO.
- Declared advance (`/W`, `/DW`, `/Widths`, `Tc`, `Tw`, TJ kerns) moves the
  cursor only. It is never an ink bound in the exact arm.
- Red-first per CLAUDE.md §5.1 (`.venv\Scripts\python.exe -m pytest`),
  `ruff check .` clean, subagents serial.

## 3. Verified facts the design rests on (PyMuPDF 1.27.1)

| # | Fact | Consequence |
| --- | --- | --- |
| R1 | The texttrace and bbox devices run over a derotated `DisplayList` via `fz_run_display_list` with output identical to `get_texttrace()` / `get_bboxlog()`; only the convenience wrappers call `fz_run_page`. | One interpretation per page; no per-call `set_rotation` writes. |
| R2 | Texttrace char bboxes are metrics boxes (advance × ascender/descender), never ink. `get_bboxlog()` entries are `fz_bound_text` = union of per-glyph outline bounds **+1.0 pt in page (device) space**, applied after the CTM (commit 2: still exactly 1.0 pt under `2 0 0 2 cm`). | bboxlog is an ink oracle; texttrace supplies only `gid`, `origin`, `type`, `seqno`, `wmode`. |
| R3 | One `fz_text` = one bboxlog entry = one seqno; MuPDF merges every show inside a BT until a flush (colour change, new BT). `Tr 2` emits the same `fz_text` twice. | Per-show extents exist at neither level; join per char via origin+gid. |
| R4 | `fitz.Font(fontbuffer=…)` uses `use_glyph_bbox=0` and returns the head bbox for every gid. `fz_bound_glyph(span.font(), gid, trm)` inside a device hook, or `fz_new_font_from_buffer(None, buf, 0, 1)`, returns per-gid outline bounds equal to fontTools. | Dual per-glyph oracle: MuPDF (production-viable) vs fontTools. |
| R5 | `_painter_reach` keeps a 0.6-em core band on both sides; `second_dy=±7.3` at 12 pt is disjoint in bands but overlaps in ink. | Reach is fail-closed in x only; pinned in commit 1. |
| R7 | The 112 `tj_array_only` rows already pass the duplicate gate; TJ matters on the candidate side (a TJ twin never gets an exact extent). | 112 → readiness counter; TJ twins are the recoverable population. |
| R8 | Trace space = `[Tfs·Th,0,0,Tfs,0,Ts] × Tm × CTM × page transform` (cropbox-anchored, UserUnit-aware). `Page.transformation_matrix` drops the cropbox origin on rotated pages. | Base matrix captured inside the rotation-0 window; production TODO. |
| R9 | Trace `type` distinguishes only fill/stroke/ignore; no clip hooks; trace `linewidth` is unreliable. | Mode ladder keyed on `ShowOp.render_mode`. |
| R12 | Trace carries `gid = -1` continuation items (multi-codepoint ToUnicode); XObject and annotation text has no marker; OCG-hidden text is absent. | Window-search join, not count consumption. |

## 4. Design (fixed before measurement)

### 4.1 Canonical space

Derotated page space = trace space. Base matrix `B = page.transformation_matrix`
captured inside the rotation-0 window in which the spike builds its own
derotated DisplayList (`get_displaylist(annots=False)`; recipe
`model/text_commit/interpretation.py:104-112`). Per-glyph placement: glyph
bounds (font units / `head.unitsPerEm`) → `[Tfs·Th, 0, 0, Tfs, 0, 0]` → translate
to the glyph's cursor origin (rise already inside `origin_user` / trace origin)
→ linear part of `Tm × CTM` → `B`. Visual space (production) = derotated ×
`page.rotation_matrix`.

### 4.2 Oracles

| Oracle | Granularity | Source | Role |
| --- | --- | --- | --- |
| O1 MuPDF per-glyph | glyph | custom `FzDevice2` hook calling `fz_bound_glyph(span.font(), gid, trm)` over the derotated list (fallback: `fz_new_font_from_buffer(None, buf, 0, 1)` on FontFile2 bytes) | primary ink bound; production-viable |
| O2 fontTools per-glyph | glyph | `BoundsPen` (lower) / `ControlBoundsPen` (upper) over `getGlyphSet()` from FontFile2 bytes | independent implementation |
| O3 bboxlog | fz_text | `fitz.JM_new_bbox_device(rc, False)` over the same list | end-to-end union check incl. stroke adjust |
| O4 raster | pixels | 8× (576 dpi) render of single-painter variants, AA level recorded | ground truth in tests only |
| Texttrace | char | `fitz.extra.JM_new_texttrace_device` over the same list | `gid`, `origin`, `type`, `seqno`, `wmode` only |

Pre-registered relations: O2-lower ⊆ O1 ⊆ O2-upper ⊕ 0.02 pt per glyph
(quarter-turn TRMs; rect-transform semantics for others); ∪O1 over an fz_text ⊆
O3 ⊆ ∪O1 ⊕ (1.0 ± 0.02) pt at identity ctm; O4 ⊆ O1 ⊕ 0.25 pt (2 device px)
for cells ≥ 4 pt em. Any relation violation on a glyph ⇒ that glyph `ambiguous`
+ `oracle_disagreement`; never a verdict.

### 4.3 Join (per page)

Own `replay_page_streams(streams, max_decoded_bytes=None)`; for each ShowOp
predict the `(origin, gid)` sequence by Identity-H cursor replay
(`x += (w/1000·Tfs + Tc)·Th`, no `Tw`; TJ kerns from the per-item re-lex
`x −= n/1000·Tfs·Th`; `gid_for` for gids). Drop trace items with `gid < 0`;
pair `Tr 2` double emissions by seqno adjacency. Search each show's predicted
sequence as a contiguous window in the trace char stream forward from the
previous match (origin within `1e-3·Tfs`, gids equal). Not found ⇒ that show
`ambiguous` (`missing_window_reason ∈ {tr_clip, ocg_or_absent,
decode_unsupported, unknown}`); more than one candidate window ⇒ `ambiguous`
(+ `verdict_invariant_ambiguity` when all candidates give the same verdict —
still ambiguous). Trace glyphs attributable to no show ⇒
`unattributed_glyphs_total` / `unattributed_glyphs_overlap_target` (diagnostic
only). Never text equality alone.

### 4.4 Render-mode ladder (keyed on `ShowOp.render_mode`)

0 ⇒ exact-eligible. 1/2 ⇒ never exact; `conservative` from the bboxlog
stroke-text rect only when that fz_text maps to exactly one show, else
ambiguous. 3 ⇒ no-ink only when replay says 3 AND trace type 3 AND bboxlog
`ignore-text` agree. 4–7 ⇒ ambiguous. `wmode = 1`, non-Identity-H CMaps, Type3,
OTTO/bare CFF, non-embedded ⇒ `unavailable`.

### 4.5 Target region (census)

The target's own per-glyph old-ink quads (always available: the cid capability
guarantees FontFile2 + parseable glyf). Diagnostic counter
`twin_ink_in_target_bbox` against the V0c halo `target_bbox_page`
(`plan.py:914-924`). A production slice must additionally union
replacement-ink quads; stated, not measured.

### 4.6 Exact predicate

Aggregate prefilter: if target and twin aggregate AABBs have strict overlap
depth ≤ 0.05 pt on either axis ⇒ `exact_safe`. Else evaluate every (target
glyph, twin glyph) pair with `_strict_overlap_depths` semantics; any pair
> 0.05 pt on both axes ⇒ `exact_overlap`, split `same_baseline` /
`cross_baseline` (twin baseline within 0.05 pt of the target's). Row
aggregation over twins: overlap > ambiguous > unavailable > safe.

### 4.7 Composition (pre-registered)

Exact-first: `exact_overlap` is terminal; `exact_safe` admits;
ambiguous/unavailable/error fall to the **existing** reach verdict. The
reach-decided admitted population is reported as residual declared-advance
exposure.

### 4.8 Evidence build

Harness-owned second `Document` per path, lazily one evidence bundle per page
keyed `(doc_ordinal, page.number, stream_xref, op_start)`; the census's own
`page` object is never touched. Per-font `(font_xref, gid)` bound caches for
O1/O2. Every exception inside the builder maps to a closed slug
(`exact_error`), never propagates.

## 5. File layout

| File | Content |
| --- | --- |
| `scripts/painter_geometry.py` | DTOs (`GlyphPaint`, `PainterEvent`, `proof_quality ∈ exact/conservative/ambiguous/unavailable`); O2 extractor with per-font caches; unitsPerEm; transform chain; stroke/mode ladder helpers |
| `scripts/painter_evidence.py` | Derotated list + `B` capture; O1 device; texttrace and bbox device runs; TJ per-item re-lex; cursor replay; window-search join; `build_page_painter_evidence`; `exact_duplicate_painter_verdict` |
| `scripts/measure_p4b2_shadow_census.py` | Stage E harness (multiplexer + recorder + `funnel_document` pass-through wrapper, sealed-constant parameters, closed-slug emit) |
| `scripts/benchmark_p4b2_painter_evidence.py` | Perf |
| `test_scripts/painter_matrix_fixtures.py` | Fixture mutators on top of `type0_fixture_builder` + `_build_second_show_doc` |
| `test_scripts/test_p4b2_production_pins.py`, `test_p4b2_oracles.py`, `test_p4b2_painter_join.py`, `test_p4b2_falsification_matrix.py`, `test_p4b2_shadow_census.py` | commits 1–5 |

Raw measurements → gitignored `benchmarks/p4b2_*.json` (slugs + timings only);
committed aggregates live in this document.

## 6. Commit sequence

| # | Commit | Red-first |
| --- | --- | --- |
| 0 | Branch + this document + verdict status block | docs |
| 1 | Production pins: 8 `/W` cases + core-band, characterization + strict-xfail twins | characterization (exempt) |
| 2 | Oracle characterization (Stage A) | ImportError red |
| 3 | Evidence + join (Stages B/D) | yes |
| 4 | Falsification matrix (Stage C); safety gate evaluated | yes |
| 5 | Shadow-census harness (Stage E) | yes |
| 6 | Sealed run | measurement-only |
| 7 | Perf | measurement-only |
| 8 | Closing docs, GO/NO-GO | docs |

## 7. Pre-registered gates, counters, tolerances

### 7.1 Counters (ints only)

`rows_source_bindable=6811`, `rows_all_gates_pass=6624`,
`rows_duplicate_painter_only=187`, `rows_tj_array_only=112`,
`rows_hscale_only=0`, `no_twins`, `delta_rows=2146`, `reach_safe_twin_rows`;
for the delta D, the reach-safe set R and the 187 P: `{d,r,p}_exact_safe`,
`_overlap_same_baseline`, `_overlap_cross_baseline`, `_ambiguous`,
`_unavailable`, `_error`; `p_target_placement_unproven`; `t_join_available`,
`t_join_ambiguous` (the 112); `tj_twin_decided`, `target_join_ambiguous`,
`twin_join_ambiguous`, `missing_window_reason.*`, `verdict_invariant_ambiguity`,
`oracle_disagreement`, `identity_refuted_by_outline`, `twin_ink_in_target_bbox`,
`twin_oc_hidden`, `unattributed_glyphs_total`,
`unattributed_glyphs_overlap_target`, `trace_load_bearing`,
`tier0_bbox_would_reject`, `font_has_fpgm_prep`, `render_mode.*`,
`form_xobject_pages`.

Identities asserted: D partitions into its six cells; R likewise;
`composed_all_gates_pass = 4478 + d_exact_safe − r_overlap_same_baseline −
r_overlap_cross_baseline`.

### 7.2 Safety gate (all must hold)

- Zero false-safe on the falsification matrix (exact and reach counted
  separately).
- Declared advance never an ink bound in the exact arm.
- Oracle disagreement ⇒ unresolved; ambiguous joins never `exact_safe`.
- Per-glyph quads; aggregate AABBs only for exclusion.
- All 8 `/W` counterexamples + the core-band counterexample rejected by the
  spike gate.
- No `exact_safe` row with any per-glyph oracle disagreement > 0.02 pt.

### 7.3 Value gate

Headline retention `composed_all_gates_pass` reported under both hazard
readings (strict: cross-baseline overlaps terminal; hazard-model: cross-baseline
admitted as designed). User thresholds kept: hard floor 4,478 (consistency check
under exact-first), provisional GO 5,962. Decidability gate:
`(d_exact_safe + d_overlap_*) / 2146 ≥ 0.90` and `d_error = 0`; NO-GO if
`d_ambiguous + d_unavailable > 10%` or any `exact_safe` row carries an oracle
disagreement. `r_overlap_same_baseline` is reported as a safety win, not a loss.

### 7.4 Performance gate

Evidence built once per page (builds == pages); p50/p95/p99 of
`build_page_painter_evidence`; scaling vs show count / TJ items / dense
same-bytes bucket; O1-only vs O1+O2 cost; `trace_load_bearing` share.

### 7.5 Privacy gate

Closed key set, ASCII, test-enforced including the exception-text, OCG-label
and glyph-name channels.

### 7.6 Tolerances

| Quantity | Tolerance |
| --- | --- |
| origin agreement (trace vs cursor replay) | `1e-3·Tfs` |
| per-glyph O1 vs O2 | `0.02 pt` (BoundsPen ⊆ O1 ⊆ ControlBoundsPen ⊕ 0.02) |
| bboxlog margin at identity ctm | `1.0 ± 0.02 pt` |
| raster containment | `0.25 pt` (2 px @ 576 dpi, AA level recorded, cells ≥ 4 pt em) |
| overlap ε | `0.05 pt` (= production) |
| same-baseline threshold | `0.05 pt` |

## 8. Key risks

Control-box vs exact-extrema on curved glyphs (two-sided O2 bound; settled in
commit 2). Tricky CJK fonts with instructed outlines (mingliu cell; O1 is a
census-time oracle on every glyph). DisplayList replay culling empty-outline
texts (count check in commit 2). `Page.transformation_matrix` cropbox-origin
bug on rotated pages (spike captures `B` at rotation 0; production TODO).
seqno↔bboxlog coupling is PyMuPDF-version-fragile (pinned by a test; violation
⇒ disagreement, not STOP). Census `all_gates_pass` over-counts per F6/F7 —
inherited by all arms, bounded by `tier0_bbox_would_reject`.

## 9. Logbook

### Commit 0 (2026-09-02)

Branch created from `49c98ee`. Verdict document stamped
`HEURISTIC_CEILING_REACHED` / `NO_MERGE`; open questions replaced by the two
user rulings. This document written before any measurement code.

### Commit 1 (2026-09-02) — production pins

`test_scripts/test_p4b2_production_pins.py` + raster oracle in
`test_scripts/painter_matrix_fixtures.py` (single-painter masks at 576 dpi,
the other painter switched to `3 Tr`).  All 18 pinned shapes ADMIT at
`49c98ee` while their single-painter rasters overlap; the 18 strict-xfail
twins (must reject with `duplicate_source_painter`) xfail.  Controls: a
28 pt-offset twin has 0 overlap pixels; a coincident twin overlaps fully.

| Case | target ink px | twin ink px | overlap px |
| --- | --- | --- | --- |
| `/W 0`, same CIDToGIDMap, offsets ±1/±2 | 4978 | 4078 | 1065–1310 |
| `/W 0`, distinct CIDToGIDMap, offsets ±1/±2 | 4978 | 4335 | 1152–1267 |
| `/W 1`, same, offsets ±1/±2 | 4978 | 4078 | 1065–1310 |
| `/W 1`, distinct, offsets ±1/±2 | 4978 | 4335 | 1152–1267 |
| core band `second_dy = −7.3` | 4978 | 4978 | 375 |
| core band `second_dy = +7.3` | 4978 | 4978 | 524 |

`/W 0` and `/W 1` are pixel-identical: the declared width moves nothing
the renderer paints, only the cursor after the last glyph.

### Commit 2 (2026-09-02) — oracle characterization (Stage A)

Red log: `ModuleNotFoundError: No module named 'scripts.painter_evidence'`
(57 tests collected against the two new modules before they existed).
Green: 57 passed, including the tricky-font cell (mingliu.ttc present on this
machine; hinted program, `fpgm` + `prep`, upem 1024).

Measured facts (all now pinned by `test_scripts/test_p4b2_oracles.py`):

- **O1 is a control box.** On the curved glyph (gid 1166 of the builder
  face) MuPDF's `fz_bound_glyph` equals fontTools' `ControlBoundsPen`
  (upper), not the exact extrema (lower): O1 x0 = 103.9375 vs exact
  104.0982 at 48 pt. The two-sided relation `lower ⊆ O1 ⊆ upper ⊕ 0.02`
  holds on every glyph tried (plain, curved, composite, hinted MingLiU).
  Consequence: O1 is a superset of ink (safe), at most one control-point
  overshoot loose.
- **bboxlog margin is post-CTM.** Exactly 1.0 pt on every side in page space
  at identity device matrix, unchanged under `2 0 0 2 cm` (R2 corrected: it
  is a device-space pixel, not a text-space quantity). For an empty-outline
  glyph (space, .notdef) `fz_bound_glyph` is the degenerate origin point; it
  is unioned in and the +1.0 is NOT applied to a wholly degenerate union.
- **Raster ⊆ O1 ⊕ 0.25 pt** at 48 pt and 12 pt; O1 ⊆ raster ⊕ 1.0 pt at
  48 pt (tightness).
- **Base matrix.** At rotation 0, `transformation_matrix` carries the CropBox
  origin AND `/UserUnit` (`(2,0,0,-2,-100,1484)` for UserUnit 2 with an
  offset CropBox) and trace origins equal `origin_user × B` to 1e-6 on all
  eight (rotate × boxes × UserUnit) shapes. At rotation 90 the property
  returns `(1,0,0,-1,0,722)`: CropBox origin and UserUnit both dropped
  (production TODO for `transforms.py:203`).
- **Cursor replay == trace origins** (1e-3·Tfs) on Tj under Tz 80/120/−100,
  Tc ±2, Tw 40 (ignored for 2-byte codes), Ts ±3, combined, and on TJ with
  leading, intra and mixed kerns. Negative Tz mirrors glyphs left of the
  origin; the replay follows because `Th` multiplies the advance. STOP rule
  not triggered.
- **Render modes.** 0 fill; 1 stroke; 2 fill+stroke as two adjacent seqnos
  with equal glyph lists; 3 ignore-text; 4/5/6 look exactly like 0/1/2 to
  every device; 7 emits nothing to any device (no clip hooks are counted).
- **Trace shape.** A 2-codepoint `bfchar` yields a `gid = −1` continuation
  item (dropped by the O1 device). Space-only / .notdef / space-then-glyph
  shows keep their item count on every route (no display-list culling).
  Form XObject text reaches the devices as its own fz_text with no ShowOp.
  A hidden OCG painter is absent from every device; a **visible `/OC BDC`
  boundary flushes the fz_text**, so the two painters of one BT become two
  bboxlog entries.

### Commit 3 (2026-09-02) — painter events, join, exact verdict (Stages B/D)

Red log: `ImportError: cannot import name 'EVIDENCE_COUNTER_KEYS' from
'scripts.painter_evidence'` (27 tests). Green: 27 passed.

- **Window search works as pre-registered**: forward from the previous
  match on `(gid, origin)` within `1e-3·Tfs`, same fz_text, unconsumed.
  Two-show pages give two exact events keyed by `(stream_xref, op_start)`;
  a leading-kern TJ twin is placed 72 pt left of its recorded origin; Form
  XObject glyphs between shows stay unattributed and never decide.
- **Hidden shows can steal a later identical show's window** (measured):
  a hidden-OCG twin at x = 73 matched the visible show at x = 73 that came
  later, leaving that show windowless. Fix: shows under a
  `CLASS_OC_LAYER_HIDDEN` / `CLASS_OC_OCMD` wrapper (`classify_wrappers`)
  skip the search and are `ambiguous / ocg_or_absent`. Even before the fix
  no false safe was possible (a stolen window is real ink; the loser
  becomes ambiguous), only mis-attribution.
- **Coincident twins**: the first show sees two candidate windows and is
  `ambiguous / multiple_windows` (+ `verdict_invariant_ambiguity`); the
  second show's remaining candidate is unique. A coincident target is
  therefore `target_unproven` — the same fail-closed outcome production
  reaches through `AMBIGUOUS_MATCH`.
- **Tr 2** pairs the fill and stroke emissions (adjacent seqnos) into one
  `conservative` event bounded by the union of both bboxlog rects; **Tr 3**
  is an exact event that paints nothing; **Tr 4–7** are `ambiguous /
  tr_clip` (4–6 still consume their glyphs so later shows stay aligned).
- Degenerate placements (Tz 0, Tfs 0, singular Tm) are empty on both
  oracles and paint nothing (raster confirms).
