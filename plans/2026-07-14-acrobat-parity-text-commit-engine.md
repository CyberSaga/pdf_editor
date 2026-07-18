# Acrobat-Parity Text Commit Engine — Design

**Date:** 2026-07-14
**Status:** DESIGN — synthesis of two independent proposals (deep-reasoner + Codex) plus empirical corpus audit. No implementation yet.
**Trigger:** User report: "After editing, text formatting/layout jumps around and font changes — not as stable as Adobe Acrobat."

---

## 1. Diagnosis (verified 2026-07-14)

The 2026-05-19 "5-layer glyph-jump elimination" system has **not** broken down — no
commit has touched the edit path since it merged (only no-behavior-change refactors,
R3.5 extraction; M2 touched `pdf_object_ops.py` only). That system solved editor-**OPEN**
geometry. The reported symptoms are the fidelity ceiling of the **COMMIT** design
(redact + re-insert), which is structural, not a regression:

| Symptom | Root cause | Where |
|---|---|---|
| Font changes after edit | Embedded font file is never reused; name is stripped of subset prefix, resolved against base-14, else heuristic-mapped to helv/tiro/cour | `model/pdf_model.py:_resolve_font_for_push` (~2992) |
| Font changes even on "best case" single-line edits | The fast `insert_text` path uses the same `_resolve_font_for_push` substitution | `model/pdf_text_edit.py:_apply_redact_insert` (~710, ~745) |
| Line breaks / layout jump | htmlbox re-breaks lines via MuPDF HTML engine with CSS `word-break: break-all; overflow-wrap: anywhere`; hard-coded 2.0pt leading-overhead constant | `model/pdf_model.py:_build_insert_css` (~2902); `pdf_text_edit.py` (~808) |
| *Untouched* text moves/changes | `_push_down_overlapping_text` redacts neighbor blocks and re-inserts them via htmlbox with estimated widths and a final `insert_text(fontname="helv")` fallback | `model/pdf_text_edit.py` (~124, ~259, ~288) |
| Neighbor damage | Rect-based redaction erases overlapping/adjacent glyphs; "protected spans" are replayed by best-effort re-insert (again substituting fonts) | pitfalls on record (vertical double-redact; multi-style collapse) |
| All of the above passes silently | Post-edit verification checks only normalized whole-page **text similarity** — never font identity or geometry | `model/pdf_text_edit.py:_verify_rebuild_edit` (~955) |

Acrobat, by contrast: edits text runs in the content stream, reuses/extends embedded
fonts, reflows only within the paragraph box, and never moves other content.

## 2. Prior art

- **Track C spike** (`feat: add Track C feasibility spike`, `73335db`/`6642bca`; later
  purged from the tree in `eaeae7f`, recoverable via
  `git show 6642bca:reflow/track_C_core.py`): direct content-stream Tj/TJ editing.
  Proved: kerning preservation, in-place byte replace, 4-part verify + rollback,
  2/3 real PDFs. Recorded limits: single-STR-item targets, no CID/Identity-H, no
  reflow, subset glyph coverage required. Verdict at the time: "right long-term
  direction, not main-path ready."
- **`model/pdf_content_ops.py`** (shipped, used by native-image move/resize/rotate/
  delete): content-stream tokenizer + operator rewrite (`tokenize_content_stream`,
  `parse_operators`, `replace_operator_operands`, `remove_operator_range`,
  `serialize_tokens`). The "rewrite operators, don't redact" precedent already exists
  in this codebase — Track C's rebuild sits on this instead of its own parser.

## 3. Empirical corpus audit (spike S1, run 2026-07-14)

`font_roundtrip_audit.py` over 9 corpus PDFs (first 5 pages each), 182 font instances:

- **Every embedded TrueType/Type0 font that extracted also loaded** in
  `fitz.Font(fontbuffer=...)` (63/63) — extraction + reuse is viable as the workhorse.
- **Type3 fonts** (large cluster in one matplotlib/LaTeX-style doc) cannot be
  extracted → permanent fallback tier.
- **Unembedded fonts** (`ext=n/a`: base-14 Type1 + named TrueType like Arial-BoldMT)
  need a **system-font resolution** path, not extraction; substitution there matches
  what every viewer (incl. MuPDF rendering) already does, so it is not a fidelity loss.
- **Font identity must be keyed per-xref, never per-basefont**: one doc carried four
  distinct `LAAAAA+Consolas` subset instances with disjoint glyph sets; name-keyed
  matching produced false "missing glyph" results in the audit itself.
- Metric agreement (`Font.text_length` vs rawdict advances) was ~0.92–1.0 for
  correctly-matched instances — good enough for layout planning with a per-run
  validation check at plan time.

## 4. Design synthesis

Two independent proposals (deep-reasoner, Codex GPT-5.4) were produced from the same
evidence pack without seeing each other. They converged on the same architecture; the
synthesis below merges them, keeping each side's unique contributions (attributed
inline where it matters for future archaeology).

### 4.0 Verdict

Build a **capability-driven tiered commit engine** in a new model-side package
`model/text_commit/`. Surgical content-stream patching is the preferred operation;
original-font TextWriter re-set is the controlled middle path; today's
redact+htmlbox pipeline survives only as the explicitly-degraded bottom tier.
Redaction, `_push_down_overlapping_text`, and protected-span replay are
**unreachable** from the new tiers.

Core invariant (Codex's formulation): *for every committed edit, all non-target
operators, resources, fonts, graphics, annotations, and geometry remain unchanged
unless the selected capability explicitly requires otherwise.* "Pixel-identical"
means pixel-identical **outside the edited region** — the target itself necessarily
changes.

### 4.1 Package layout

```
model/text_commit/
    __init__.py
    intent.py          EditIntent / EditContext / EditPlan / CommitOutcome DTOs (Qt-free)
    capability.py      classify_edit(ctx) -> EditPlan   — tier decision, single source of truth
    font_registry.py   DocumentFontRegistry — per-xref FontCapability cache (never per-basefont)
    stream_edit.py     content-stream text ops: parse / match / patch / erase
                       (built ON model/pdf_content_ops.py tokenizer, like native-image ops)
    layout.py          LayoutEngine — pure metric line-breaking, no fitz.Page needed
    engine.py          TieredCommitEngine — apply(plan) / preview(plan), downgrade loop
    verify.py          per-tier post-conditions + render-diff + rollback triggers
```

Integration: `pdf_text_edit.edit_text` keeps its transactional phase structure.
New Phase 1.5 builds `EditContext` from `resolve_result` + `EditIntent` and calls
`capability.classify_edit`. Phase 2 becomes `engine.apply(plan)` with verified
downgrade (Tier 0 → 1 → 2, snapshot-restore between attempts, ≤3 attempts, every
downgrade logged with a structured reason). Tier 2 **is** today's
`_apply_redact_insert`, untouched. Tier 0/1 edits do not append to
`model.pending_edits` (no redactions to clean; `clean_contents` must never run on
freshly patched streams — Tier-0 byte identity would be destroyed).

`EditContext` (Codex's fuller enumeration): member spans + rawdict chars/quads,
texttrace spans with seqnos + matrices + render mode + font refs, content-stream
xrefs and original bytes, decoded target operators with byte ranges, text state
(`Tf Tm Td TL Tc Tw Tz Ts Tr`), writing mode/rotation, original + replacement text
and length delta, font descriptor + extracted buffer + coverage result, paragraph
box, capability decision with rejection reasons.

### 4.2 The tier ladder

| Tier | Name | Mechanism | Neighbor guarantee | Edited-text guarantee |
|---|---|---|---|---|
| 0 | STREAM_PATCH | In-place byte patch of show-op strings (Track C rebuilt on `pdf_content_ops`) | **Byte-identical** outside patched operand ranges; font xrefs unchanged | Original font xref, original kerning for untouched glyphs, original baseline |
| 1 | RESET_ORIGINAL_FONT | Surgical erase of target show ops + re-set via `fitz.TextWriter` with the **extracted embedded font**, own layout | Byte-identical outside erased ranges + one new block; render-identical outside paragraph bbox | Original face (or *declared* same-family substitute), pinned first baseline + leading, real-metrics line breaks |
| 2 | LEGACY_HTMLBOX | Today's `_apply_redact_insert`, incl. fast path / push-down / strategies A-B-C | Today's (weak) | Today's (substituted) — UI marks the edit as degraded fidelity |

#### Decision gates (first failure drops the tier)

**G — target resolvability (needed for Tier 0 and 1):**
- G1: every member span maps to concrete show-op byte ranges via text-state replay
  of the stream. **Seqno caveat (Codex):** `get_texttrace()` seqnos are display-list
  ordering, not byte offsets — use them only as corroborating evidence; ambiguous
  mappings (multiple indistinguishable candidates) are rejected, never guessed.
- G2: target ops in the page stream, not inside a Form XObject (v1) — reject only
  when the *target* is inside one, not when the page merely contains any XObject
  (the old spike's page-level rejection fired constantly on MuPDF's own wrappers).
- G3: enclosing CTM at the target is identity-or-page-rotation (tracked via q/Q/cm).
- G4: horizontal line direction; vertical/rotated stays Tier 2 in v1 (TextWriter
  `morph` is a later extension).
- G5: no `BDC/EMC` pair orphaned by the planned removal.
- G6 (Codex): no reliance on text render modes/state the engine can't reproduce
  (`Tr` ≠ fill, `Ts` rise, opacity/clipping effects) — reject to Tier 2.

**F — font class (per style run, keyed by font XREF — never basefont; see §3):**
- F1: font xref resolvable from `page.get_fonts(full=True)`; Type3 → Tier 2.
- F2: `doc.extract_font(xref)` non-empty and `fitz.Font(fontbuffer=...)` loads →
  else registry tries `system_family_font()` (name-table match); else Tier 2.
  Unembedded fonts skip F2 and resolve via the system path (matches what every
  viewer already renders — not a fidelity loss; audit §3).
- F3 **cmap sanity** (deep-reasoner; the make-or-break signal): every *original*
  char has a glyph in the loaded face AND `font.text_length(original)` matches the
  observed rawdict advance within 2% after folding `Tc/Tw/Tz`. Filters symbolic
  fonts, custom `/Differences`, broken subset cmaps — the cases where re-set would
  render tofu or shift widths.
- F4 glyph coverage of NEW text: missing chars → whole-run substitution with the
  declared system family face (never per-glyph mixing in v1), reported in the
  outcome and the editor UI; else Tier 2.

**T0 — Tier 0 eligibility (on top of G+F):**
- T0a: single style run; no line-count change; no paragraph re-break needed.
- T0b: new width at original metrics fits the line's actual right boundary
  (measured against real neighbors, not page-margin heuristics).
- T0c: edit maps to a contiguous STR sub-range in one show op, or cleanly
  splittable across adjacent STR items — kern numbers outside the edited char
  range are preserved, those inside are dropped (evolves the spike's
  single-STR-item limit).
- T0d: chars encodable in the run's encoding class. WinAnsi/MacRoman: latin-1 +
  `/Differences`. **Identity-H: 2-byte GIDs from the extracted font's cmap for any
  char whose glyph exists in the subset** — this unlocks Tier 0 for modern CID
  PDFs incl. the CJK corpus (deep-reasoner; Codex scopes it "only after explicit
  implementation" — phased, see spikes).
- T0e: no style overrides except (v1.1) pure color, which can patch `rg/g` state.

Anything passing G+F but failing T0x lands in Tier 1. A user-dragged `new_rect` is
Tier 1 with `box = new_rect` (today it force-routes to htmlbox for no reason once
layout is owned).

### 4.3 Old-text removal (no redaction in Tiers 0/1)

- Tier 0: nothing removed — bytes replaced in place via
  `replace_operator_operands`.
- Tier 1 erase: show ops wholly owned by the target → `remove_operator_range`;
  a shared op spanning the target boundary → operand truncation. Positioning ops
  (`Td/TD/T*/Tm`) and state ops are never removed, so subsequent lines are
  untouched. Erasing glyphs correctly *reveals* whatever was painted beneath them
  (Acrobat behavior) — unlike redaction's white box.
- Tier 1 write, two strategies (deep-reasoner), decided by spike S2:
  - **1a append+verify:** `TextWriter.write_text(page)` appends a stream. Simple;
    PyMuPDF owns glyph encoding + ToUnicode. Risk: z-order (re-set text now paints
    above content that originally covered it) — caught by render-diff V1d.
  - **1b transplant:** splice the generated `BT/ET` block into the original stream
    at the erased offset (valid under G3; resource names are page-scoped), blank
    the appended stream. Z-order preserved by construction.
  - Ship 1a first, spike 1b immediately, promote 1b to default if clean.
- Protected/overlapping spans: **not erased, therefore not replayed** — the entire
  `_replay_protected_spans` machinery and the vertical double-redact pitfall are
  structurally impossible in the new tiers.

### 4.4 Layout & reflow policy (Acrobat parity)

1. Reflow **only within the paragraph box** (union of member line boxes, or the
   user-resized `new_rect`); width fixed; alignment detected from span origins vs
   box edges and reproduced (justified lines emit per-word placements).
2. **First baseline pinned** to the original; subsequent baselines at original
   leading (median baseline-delta — logic already proven in
   `pdf_text_edit.py:665-677`, moves into `layout.py`).
3. Line breaks at Unicode word boundaries, per-character for CJK, mid-word only
   when a single word exceeds the box — never `break-all`/`anywhere`.
4. Metrics from the actual `fitz.Font` (`text_length` + `Tc/Tw/Tz` folded in).
5. **Overflow: never move neighbors.** The box grows downward only; the engine
   reports `overflow_overlap` in the outcome; the view shows an Acrobat-style
   overflow indicator on the box. No auto-shrink, no auto-widen, no push-down.
   (Codex would also allow "reject the edit" as a strict mode — kept as an open
   question, §5.)

### 4.5 Preview contract (replaces "shared classifier")

Finding recorded 2026-07-14: `_classify_insert_path` is called **only** by the
commit path and tests — `view/` and `controller/` never consult it, so today's
preview (always htmlbox on a temp page) can already diverge from a fast-path
commit. ARCHITECTURE.md §10's "they cannot diverge" is stale. The redesign fixes
this **by construction**:

- Model: `render_edit_preview(...) -> PreviewImage(samples, w, h, stride, alpha)` —
  open the session snapshot bytes as a scratch doc, run `engine.apply(plan)` on the
  scratch page, rasterize the clip. The plan the preview renders **is** the plan
  commit executes. Qt-free DTO.
- Controller: expose it beside `build_insert_preview_html` (same R2.6 injection
  seam, `controller/pdf_controller.py:2812`).
- View: `PreviewRenderer` renders the returned samples for Tier 0/1 plans; Tier 2
  keeps today's htmlbox preview path byte-for-byte. Arg-tuple caching stays.
- Honest UX: if a keystroke degrades the plan (new char misses the subset), the
  preview visibly changes and the editor shows a "font substituted" indicator
  (hook exists: `TextEditManager.on_edit_font_family_changed`).
- `scripts/verify_no_jump.py` gains tiered-plan preview cases; the gate fails if
  `PreviewRenderer` bypasses the model-selected capability.

### 4.6 API change — EditIntent (small but load-bearing)

`edit_text(...)` today receives scalar `font="helv", size=12.0, color=...`
(`pdf_text_edit.py:1174`), so the model **cannot distinguish "user typed text" from
"user restyled"** — a prerequisite failure for keeping original fonts. Add
`style_overrides: dict | None` (keys present only if the user touched that control
during the session; view already tracks the interactions, controller forwards).
When absent, style truth comes from the member spans. Legacy callers behave as
today under Tier 2. Font substitution stops being a silent default and becomes a
reported event owned by `DocumentFontRegistry` (`CommitOutcome.warnings` + UI);
`_resolve_font_for_push` is retired from every new-tier path.

### 4.7 Verification & rollback (per tier, inside `engine.apply`)

Any failure → snapshot restore → downgrade one tier (existing snapshot machinery
is the rollback foundation).

**Tier 0:** V0a non-patched content-stream bytes identical (re-diffed, not assumed);
V0b font resources + resource dict unchanged, no new font xref; V0c clip text
(new present, old gone) + stable-span whole-page check (port of spike's verify);
V0d render-diff — pixels outside the edited line bbox (+2pt) **exactly equal**;
V0e doc reopens from `tobytes()`; no annotations removed/recreated.

**Tier 1:** V1a tokens outside (erased ∪ new block) identical; V1b non-target
rawdict spans: same count, origins within 0.1pt, same font names/sizes; V1c target
spans: basename equals original (subset prefix may differ) or the *declared*
substitute — substitution verified as intentional, never incidental; first-baseline
and leading deltas ≤0.5pt; V1d render-diff outside paragraph bbox ≤ ε (z-order
guard for 1a) — ε calibrated from repeated PyMuPDF renders, not guessed (Codex);
V1e new text extractable via `get_text` (ToUnicode correctness).

**Tier 2:** unchanged `_verify_rebuild_edit`. Do not retrofit geometry checks onto
the legacy path — it cannot pass them; that is why it is the bottom tier.

**Telemetry (Codex):** on failure or debug, record capability decision + rejection
reasons, font metadata, stream hashes, operator ranges, geometry deltas,
render-diff bboxes, rollback result. Cost: two ~96dpi pixmaps per edit — inside
the existing 300ms slow-edit budget.

### 4.8 Rollout & testing (red-light-first, corpus-driven)

- **Phase A — infrastructure (no behavior change):** `font_registry` + `verify` +
  `EditTextResult` extension (`tier_used`, `fallback_chain`, `warnings`) + flag
  `TEXT_COMMIT_ENGINE = legacy | shadow | tiered` (default `legacy`).
  Red suite first: characterization tests that *demonstrate current failures*
  (font substitution on subset fonts, neighbor damage, break-all wrapping,
  preview/fast-path divergence, verifier accepting font mismatch) — these are the
  permanent regression net.
- **Phase A.5 — shadow mode (Codex):** classify every real edit, log the would-be
  tier, change nothing. Produces the tier-coverage telemetry before any risk.
- **Phase B — Tier 0 Latin + preview plumbing:** port spike tests into
  `test_scripts/`; rebuild `stream_edit` on `pdf_content_ops`; ship the preview
  DTO path in the same phase (the invariant demands preview lands *with* the first
  tier). Parser-only byte-range tests precede any mutation (escaped parens, hex
  strings, nested TJ, comments, BT/ET transitions, malformed streams).
- **Phase C — Tier 1** (TextWriter re-set, erase, LayoutEngine, alignment).
 - **Phase D — Identity-H** (Tier 0 CID patching + Tier 1 CJK; corpus: representative CJK fixture, representative drawing fixture, and representative Arabic-script fixture for rejection tests).
- **New CI gate** `scripts/verify_commit_fidelity.py` (deterministic cases ×2,
  mirroring verify_no_jump): corpus × scripted edits × per-tier post-conditions
  incl. neighbor byte-identity and render-diff. Every case asserts on committed
  content, never no-op edits.
- **`scripts/audit_tier_coverage.py`:** % of corpus spans commit-able at each tier
  — the progress metric and empirical definition of done. Suggested flag-flip bar:
  ≥70% of corpus spans at Tier ≤1 with the fidelity gate green.
- All runs via the repository-managed test runner; an unrelated system environment can mask stream behavior.

### 4.9 Risks

- **Mapping ambiguity** (top risk, both proposals): span→operator matching must
  replay text state; reject ambiguity rather than guess. Success bar from spike:
  ≥95% of simple/subset single-run cases map unambiguously.
- **Subset coverage of new chars** — hard capability boundary; handled by F4
  substitution-with-report, never silently.
- **Complex scripts/shaping** (Arabic, Indic, ligatures): reject to Tier 2 until
  explicitly supported; corpus has `015-arabic` for rejection tests.
- **Appearance is more than font** (Codex): `Tr/Ts/Tz`, opacity, clip paths —
  gate G6 rejects what the engine can't reproduce.
- **Z-order** for Tier 1a — V1d guards; 1b transplant resolves properly.
- **Font re-embedding growth** — subsets are small; `doc.subset_fonts()` at the
  persistence boundary where whole-doc GC already lives.
- **Custom `/Differences`** — F3 rejects to Tier 2; a Differences-aware encoder is
  a v2 extension.
- **Encrypted docs** — the encryption-preserving round-trip chokepoints must be in
  the fidelity corpus.
- **Parity honesty:** some PDFs are positioned glyph soup, not paragraphs. The
  product promises Acrobat-like fidelity *for classified editable cases* and says
  so when it can't (degraded-tier marking), rather than pretending universality.

### 4.10 De-risking spikes (in order; S1 already done)

- **S1 — font round-trip audit: DONE 2026-07-14** (§3). Embedded TT/Type0
  extract+load = 100%; Type3 never; identity must be per-xref.
- **S2 — TextWriter transplant vs append:** append via `write_text`, splice the
  `BT/ET` block into the original stream position, blank the appended stream;
  render-diff both ways incl. a text-under-filled-rect case to prove z-order.
  Decides 1a vs 1b as the Tier 1 default.
- **S3 — Identity-H stream patch:** on a representative CJK fixture, swap one CJK char for
  another already-in-subset char by GID hex patch; verify render + extraction.
  Decides whether Tier 0 covers modern CID PDFs (reconciles the deep-reasoner/
  Codex scoping difference with data).
- **S4 — mapping-ambiguity audit:** read-only parser prototype over ~20 corpus
  PDFs (simple fonts, subsets, TJ arrays, rotations, Form XObjects): map
  span→byte-range, replace one string, assert zero non-target byte changes.
  Gates Phase B go/no-go at the ≥95% bar.

## 5. Open questions

1. **Overflow UX:** commit-with-indicator (Acrobat-style "+", deep-reasoner) vs
   strict reject-on-overflow mode (Codex). Recommend indicator as default; revisit
   after first real-corpus dogfooding.
2. **Identity-H in Tier 0 v1 scope** — resolved by spike S3's outcome.
3. **`style_overrides` plumbing** — exact view-side tracking of "user touched font
   control" needs a small design note when Phase A starts.
4. **ε calibration** for V1d render-diff — measure across repeated renders on this
   machine + CI runner before hard-coding.
5. **ARCHITECTURE.md §10 stale claim** ("preview and commit cannot diverge") —
   correct it when the new preview contract lands, or earlier as a docs fix.
6. **Preview scratch-doc cost on large PDFs** (adversarial-verify finding):
   `render_edit_preview` must not `fitz.open` the full session snapshot per
   keystroke — on a large representative fixture that is way past frame budget. Mitigation
   to design in Phase B: extract the single target page into a small scratch doc
   once per edit session, run `engine.apply` on copies of that; keep the existing
   arg-tuple render cache in front.

## 5.1 Adversarial verification record (2026-07-14)

Steel-manned the "not a regression" diagnosis against the user's word "again":
- mypy commit `c9b14c4` (touched `model/pdf_model.py` post-merge) — documented and
  diff-verified zero-runtime-change (typed-local-bind only; no size/font coercions).
  the recent symptom reports.
Conclusion stands: symptoms are the structural fidelity ceiling of redact+reinsert
surfacing on real-world (embedded-font) documents.

## 6. Verified API surface (probed 2026-07-14)

- `TextWriter.append(pos, text, font, fontsize, ...) -> (Rect, Point)`;
  `write_text(page, color, opacity, overlay, morph, matrix, render_mode, oc)`;
  `fill_textbox(..., align, lineheight, warn)`; `text_rect` / `last_point` props.
- `Document.extract_font(xref) -> (name, ext, type, buffer)`;
  `fitz.Font(fontbuffer=...)` with `has_glyph` / `text_length`;
  `Document.subset_fonts` exists.
- `model/pdf_content_ops.py` provides `tokenize_content_stream` (:65),
  `parse_operators` (:131), `replace_operator_operands` (:488),
  `remove_operator_range` (:496), `serialize_tokens` (:501) — shipped and already
  battle-tested by native-image operator rewriting.
