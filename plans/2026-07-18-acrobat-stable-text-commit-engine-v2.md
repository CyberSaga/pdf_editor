# Acrobat-Stable Text Commit Engine V2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Keep each production milestone behind a feature flag and show a failing test before implementation.

**Goal:** Make text edits exact and Acrobat-like for explicitly supported PDF text runs, while rejecting or visibly degrading unsupported cases instead of silently changing fonts, moving neighbors, or damaging page content.

**Architecture:** Preserve the existing five-layer inline-editor opening system, but replace the legacy commit path with a capability-driven, model-only engine. The engine losslessly maps visible text to source operators, prepares and verifies a candidate on scratch data, previews that exact candidate, then applies one stale-checked `PatchSet` to the live document. Legacy redact/reinsert remains an explicit bottom tier only.

**Tech Stack:** Python 3.9+, PyMuPDF 1.27.x, PySide6 Qt signals/QThread, pytest, ruff, mypy.

---

## Context

The May 2026 five-layer glyph-jump system has not broken down. It stabilizes editor opening, DPI geometry, the frozen first frame, MuPDF-backed preview, and repeated reopen sizing. It does not preserve PDF content during commit.

The current commit path still:

- converts unknown/subset fonts to generic PDF aliases, commonly Helvetica;
- redacts and reinserts text rather than editing source text operators;
- uses `insert_htmlbox` wrapping rules that can alter line breaks and leading;
- can widen or scale the target box and push/replay neighboring text;
- permits Controller Track A/B displacement reflow after the edit;
- verifies mostly extracted text, not font/resource identity or geometry.

The comparison branch `investigate/text-editing-jump` at `98799eef802ff84a18df5443c1b1c9b8df2eb8a2` is useful as a diagnosis oracle. Implementation should start from current `main`, which contains the PyMuPDF pin, device-data guard, updated architecture notes, and current M3 behavior. Do not build the new engine on the historical branch.

This plan supersedes the unsafe parts of `plans/2026-07-14-acrobat-parity-text-commit-engine.md` while retaining its capability-tier direction and corpus-driven rollout.

## Architectural Verdict

A universally lossless PDF text editor is not possible for every PDF text representation. The product-level definition of “perfect” is therefore:

1. **Exact for classified supported cases.** Preserve source operators, font resources, downstream text state, annotations, and non-target rendering.
2. **No guessing.** Ambiguous source mapping or unsupported text state cannot enter a high-fidelity tier.
3. **Honest fallback.** Unsupported cases are either rejected in strict mode or explicitly labeled as legacy/degraded before mutation.
4. **Preview equals commit.** The pixels shown for a supported edit come from the same immutable candidate that commit applies.
5. **No silent collateral changes.** High-fidelity tiers never redact, replay protected spans, move neighbors, or invoke external reflow.

## Corrections to the July 14 Design

- Do not use `model/pdf_content_ops.py` token serialization for Tier 0. It discards comments/whitespace and rewrites the whole stream. Add a lossless byte-range lexer and raw splice writer.
- Do not initially patch arbitrary substrings or `TJ` items. Changing a string’s advance moves suffix glyphs unless an exact text-space compensation is emitted and verified.
- Do not remove `Tj`/`TJ` operators in Tier 1 without preserving their consumed advance. Later text in the same `BT`/`ET` would move.
- Do not claim that `TextWriter` reuses the original font xref. Report whether the source resource was reused, a validated face was newly embedded, or a system substitute was used.
- Do not derive source identity from `EditableSpan`. It is a geometric selection hint, not a stable stream/operator identity.
- Do not use page snapshot replacement as the normal candidate downgrade loop. Evaluate candidates on scratch data and apply one verified patch to the live document.
- Do not claim current preview and commit share a classifier. The immutable prepared-plan token replaces that false contract.
- Do not allow `clean_contents`, protected-span replay, annotation recreation, `_push_down_overlapping_text`, or Track A/B reflow in high-fidelity tiers.

## Non-Negotiable Invariants

### Source and patch identity

Each replacement range stores:

```python
@dataclass(frozen=True)
class StreamReplacement:
    stream_xref: int
    start: int
    end: int
    expected_bytes: bytes
    replacement_bytes: bytes
    expected_stream_digest: str
```

- Bytes outside declared ranges remain unchanged in decoded content streams.
- Every commit validates page/content/resource/annotation fingerprints immediately before mutation.
- A plan prepared before undo, redo, save/reopen, or another edit returns `STALE_PLAN` without mutation.

### Text-state continuity

- Replay `q/Q/cm`, `BT/ET`, `Tf`, `Tm`, `Td`, `TD`, `T*`, `TL`, `Tc`, `Tw`, `Tz`, `Ts`, and `Tr` for supported page streams.
- `get_texttrace()` sequence numbers are corroborating evidence only, never byte offsets.
- A Tier 0 replacement must preserve the original consumed advance, or carry an independently verified compensation operation.
- A Tier 1 erase must preserve the consumed advance before re-setting text.

### Font identity

- Resolve fonts by resource owner, resource name, and font xref.
- Never match by subset-stripped basename.
- Record source xref, written xref, face fingerprint, coverage, metric error, and one of:
  - `SOURCE_RESOURCE_REUSED`
  - `VALIDATED_FACE_EMBEDDED`
  - `SYSTEM_FACE_SUBSTITUTED`
  - `LEGACY_BASE14_SUBSTITUTED`
- No substitution is silent.

### Mutation isolation

Tier 0 and Tier 1 must not call:

- `Page.add_redact_annot()` or `Page.apply_redactions()`;
- `_push_down_overlapping_text()`;
- protected-span or neighbor replay;
- annotation save/recreate helpers;
- `Page.clean_contents()`;
- Controller Track A/B reflow callbacks.

### Preview/commit identity

- `prepare()` returns an immutable `PreparedEdit` with a source fingerprint and opaque token.
- `preview()` renders that prepared candidate on a target-page scratch document.
- `commit()` applies the same patch after validating the token/fingerprint.
- When a preview is stale, pending, unsupported, or degraded, the UI says so; it never substitutes an unrelated HTML approximation while claiming fidelity.

## Package and API Design

Create:

```text
model/text_commit/
    __init__.py
    dto.py          immutable public/internal DTOs
    pdf_lexer.py    lossless byte ranges and raw splicing
    replay.py       PDF graphics/text-state interpreter
    inspect.py      target/resource/annotation/signature inspection
    fonts.py        per-xref registry, encoding, coverage, metrics
    layout.py       pure paragraph layout for future Tier 1
    plan.py         capability classification and rejection reasons
    patch.py        reversible low-level PatchSet application
    preview.py      scratch candidate rendering
    verify.py       structural/semantic/geometry/raster verification
    engine.py       prepare / preview / commit orchestration
```

### Boundary DTOs

Keep View imports limited to pure request/report types allowed by the import-linter allowlist. Extend `model/edit_requests.py` rather than exposing low-level engine classes to View.

Representative DTO shape:

```python
@dataclass(frozen=True)
class StyleOverrides:
    font_family: str | None = None
    font_size: float | None = None
    color: tuple[float, float, float] | None = None

    @property
    def changed(self) -> bool:
        return any(value is not None for value in (self.font_family, self.font_size, self.color))


@dataclass(frozen=True)
class EditIntent:
    page_num: int
    target_span_id: str | None
    target_mode: str | None
    source_rect: fitz.Rect
    replacement_text: str
    original_text: str | None
    new_rect: fitz.Rect | None
    style_overrides: StyleOverrides


@dataclass(frozen=True)
class CommitOutcome:
    status: CommitStatus
    tier: CommitTier | None
    fallback_chain: tuple[str, ...]
    warnings: tuple[str, ...]
    font_outcomes: tuple[FontOutcome, ...]
    verified_properties: tuple[str, ...]
    degraded_reason: str | None
    allows_external_reflow: bool
```

The editor must populate `StyleOverrides` only when the user actually touches a formatting control. Merely opening an embedded-font span must not convert its font to a UI alias and send that alias back as style truth.

### Engine API

```python
class TieredCommitEngine:
    def prepare(self, source: PageSource, intent: EditIntent) -> PreparedEdit: ...
    def preview(self, prepared: PreparedEdit, clip: fitz.Rect, scale: float) -> PreviewImage: ...
    def commit(self, prepared: PreparedEdit, doc: fitz.Document) -> CommitOutcome: ...
```

`PDFModel` owns the engine and source revision. The Controller coordinates async preview work but remains the sole mutation coordinator. The View emits requests and paints returned raster DTOs only.

## Capability Ladder

### Tier 0 — `LOSSLESS_STREAM_PATCH`

Initial production scope is deliberately narrow:

- direct page content stream, not a Form XObject or widget appearance;
- exactly one unambiguous run mapped to one complete literal-string `Tj` operator;
- simple horizontal text, page rotation 0, supported CTM/text matrix;
- fill render mode, no rise, clipping, opacity dependency, or marked-content dependency;
- simple Latin source encoding with a verified reverse encoder;
- no `TJ`, substring target, newline, deletion, drag move, style override, or paragraph reflow;
- replacement glyphs exist in the source font encoding;
- replacement advance equals source advance within a measured tolerance;
- no pending legacy maintenance that can call `clean_contents` on the page;
- no signature and no AcroForm/widget target.
- **Amended 2026-08-01 (D1):** the `Tj` operand may be literal **or** hex, and the text matrix may carry a uniform positive scale (`a == d > 0`, `b == c == 0`) as well as pure translation; rotation, shear, and reflection stay deferred.

Any failed gate rejects Tier 0. It does not guess.

### Tier 1 — `REBUILD_WITH_VALIDATED_FACE`

Flag-off until spikes prove:

- advance-preserving erase;
- source-position transplant that preserves z-order and resource scope;
- explicit resource mutations;
- non-target geometry/raster stability;
- reliable extracted-font encoding and ToUnicode behavior.

Tier 1 may reflow only inside the chosen paragraph box. It pins the first baseline, preserves measured leading, never pushes neighbors, and reports overflow through the outcome/UI.

### Tier 2 — `LEGACY_REDACT_REINSERT`

The current engine remains for compatibility:

- always marked degraded;
- carries exact fallback reasons and substitution warnings;
- alone may use current protected replay, push-down, and Track A/B behavior;
- strict mode rejects instead of entering Tier 2;
- stale plans, signed documents, malformed streams, or failed high-fidelity verification reject rather than silently mutate through Tier 2.

Deferred until separately proven: Identity-H/CID, Type3, arbitrary `/Differences`, Arabic/Indic shaping, ligatures requiring shaping, vertical writing, arbitrary rotation/shear, Form XObjects, marked content, complex clipping/opacity, tagged content, and AcroForm appearance editing.

---

## Task 1: Deterministic Fidelity Corpus and Characterization

**Files:**
- Create: `scripts/build_fidelity_corpus.py`
- Create: `test_scripts/test_fidelity_corpus_generator.py`
- Create: `test_scripts/test_text_commit_characterization.py`
- Update: `TODOS.md`

**Step 1: Write the corpus manifest test**

Assert deterministic generation for: simple `Tj`, subset TrueType, same-basename/different-xref subsets, `TJ`, escaped/hex strings, Identity-H, Type3, `/Differences`, Form XObject, annotations, marked content, rotated text, Arabic/ligature rejection, encrypted input, and signed/widget boundaries.

**Step 2: Run the test and confirm Red**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_fidelity_corpus_generator.py -q
```

Expected: failure because the generator/manifest does not exist.

**Step 3: Implement the deterministic generator**

Use only redistributable/OFL fixture fonts. Do not commit private PDFs, local paths, machine font files, or runtime telemetry.

**Step 4: Add characterization tests**

Prove current failures rather than asserting intended future behavior:

- unchanged style still becomes a Base-14 alias;
- preview (`insert_htmlbox`) and fast commit (`insert_text`) differ;
- legacy verification accepts font/geometry changes;
- neighboring content can be replayed or moved;
- `break-all` differs from word-boundary wrapping.

**Step 5: Run Green for corpus tests while keeping characterization marked expected-failure**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_fidelity_corpus_generator.py test_scripts/test_text_commit_characterization.py -q
```

**Step 6: Commit**

```bash
git add scripts/build_fidelity_corpus.py test_scripts/test_fidelity_corpus_generator.py test_scripts/test_text_commit_characterization.py TODOS.md
git commit -m "test: add deterministic text fidelity corpus"
```

## Task 2: Lossless Lexer and Raw Splice Primitive

**Files:**
- Create: `model/text_commit/__init__.py`
- Create: `model/text_commit/dto.py`
- Create: `model/text_commit/pdf_lexer.py`
- Create: `test_scripts/test_text_commit_lexer.py`

**Step 1: Write lexer Red tests**

Cover whitespace/comments, nested and escaped literal strings, hex strings, arrays, dictionaries, inline-image payloads, malformed strings, operator boundaries, and exact source offsets.

**Step 2: Write raw-splice Red tests**

Assert:

```python
assert after[:start] == before[:start]
assert after[start:start + len(replacement)] == replacement
assert after[start + len(replacement):] == before[end:]
```

Also assert digest mismatch, overlap, and out-of-range replacements fail before mutation.

**Step 3: Confirm Red**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_lexer.py -q
```

**Step 4: Implement minimal lexer/splicer**

Store raw start/end byte offsets and trivia. Do not add a normalized serializer. Do not modify `model/pdf_content_ops.py`; native-image operations keep their current API.

**Step 5: Run Green, ruff, and mypy for the new package**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_lexer.py -q
.venv/Scripts/python.exe -m ruff check model/text_commit test_scripts/test_text_commit_lexer.py
.venv/Scripts/python.exe -m mypy model/text_commit/
```

**Step 6: Commit**

```bash
git add model/text_commit test_scripts/test_text_commit_lexer.py
git commit -m "feat: add lossless PDF text stream lexer"
```

## Task 3: Text-State Replay and Source Binding Audit

**Files:**
- Create: `model/text_commit/replay.py`
- Create: `model/text_commit/inspect.py`
- Create: `test_scripts/test_text_commit_replay.py`
- Create: `scripts/audit_text_source_mapping.py`

**Step 1: Write Red tests for supported replay**

Cover `q/Q/cm`, `BT/ET`, `Tf`, `Tm`, `Td`, `TD`, `T*`, `TL`, `Tc`, `Tw`, `Tz`, `Ts`, `Tr`, `Tj`, and `TJ` parsing/state transitions.

**Step 2: Write Red tests for mapping refusal**

Duplicate text, ambiguous geometry, Form XObject targets, unsupported text state, malformed streams, and mismatched rawdict/texttrace evidence must return reason codes—not best-score guesses.

**Step 3: Confirm Red**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_replay.py -q
```

**Step 4: Implement horizontal direct-page replay only**

Build `SourceSpanBinding` after replay. Treat existing `EditableSpan.span_id` as a target hint; do not add low-level stream state to View-facing dataclasses.

**Step 5: Add read-only mapping audit**

Report supported/rejected/ambiguous counts by document class. Do not emit text, paths, raw streams, or device-specific metadata.

**Step 6: Run Green and audit synthetic corpus**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_replay.py -q
.venv/Scripts/python.exe scripts/audit_text_source_mapping.py --corpus test_files/fidelity
```

**Step 7: Commit**

```bash
git add model/text_commit/replay.py model/text_commit/inspect.py test_scripts/test_text_commit_replay.py scripts/audit_text_source_mapping.py
git commit -m "feat: replay PDF text state and bind source runs"
```

## Task 4: Per-Xref Font Registry

**Files:**
- Create: `model/text_commit/fonts.py`
- Create: `test_scripts/test_text_commit_fonts.py`

**Step 1: Write Red tests**

Assert:

- same basename at different xrefs remains distinct;
- embedded TrueType/Type0 extracts and loads;
- source text metric agreement is checked;
- missing replacement glyphs reject Tier 0;
- Type3 and unsupported encodings reject;
- system-font matching is an explicit substitution outcome;
- no default Helvetica path is entered silently.

**Step 2: Confirm Red**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_fonts.py -q
```

**Step 3: Implement registry and encoding capability**

Cache by `(document_generation, resource_owner_xref, font_resource_name, font_xref)`. Use `Document.extract_font(xref)` and `fitz.Font(fontbuffer=...)` where supported.

**Step 4: Run Green**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_fonts.py -q
```

**Step 5: Commit**

```bash
git add model/text_commit/fonts.py test_scripts/test_text_commit_fonts.py
git commit -m "feat: resolve PDF fonts by resource xref"
```

## Task 5: Intent, Outcome, Settings, and History Plumbing

**Files:**
- Modify: `model/edit_requests.py`
- Modify: `model/edit_commands.py`
- Modify: `model/pdf_model.py`
- Modify: `view/text_editing.py`
- Modify: `main.py`
- Create: `test_scripts/test_text_commit_intent.py`
- Create: `test_scripts/test_text_commit_settings.py`

**Step 1: Write Red tests for untouched style**

Opening and typing without touching font/size/color controls must produce empty `StyleOverrides`. Explicit user changes must populate only the changed field.

**Step 2: Write Red tests for outcome/history**

`EditTextCommand` must store the full `CommitOutcome`, preserve the original intent for redo, and invoke external reflow only when `outcome.allows_external_reflow` is true.

**Step 3: Confirm Red**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_intent.py test_scripts/test_text_commit_settings.py -q
```

**Step 4: Implement DTO compatibility**

Keep legacy scalar request fields during migration. Add `style_overrides` and `plan_token` with defaults so existing callers remain valid.

**Step 5: Add settings at the composition root**

Pass a Qt-free settings DTO into `PDFModel`:

- `TEXT_COMMIT_ENGINE=legacy|shadow|tiered`
- `TEXT_COMMIT_MAX_TIER=0|1`
- `TEXT_COMMIT_STRICT=0|1`
- `TEXT_COMMIT_PREVIEW=legacy|plan`
- `TEXT_COMMIT_TELEMETRY=off|local`

Defaults stay legacy/off.

**Step 6: Run Green plus layer contracts**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_intent.py test_scripts/test_text_commit_settings.py -q
.venv/Scripts/python.exe -m lint_imports
```

**Step 7: Commit**

```bash
git add model/edit_requests.py model/edit_commands.py model/pdf_model.py view/text_editing.py main.py test_scripts/test_text_commit_intent.py test_scripts/test_text_commit_settings.py
git commit -m "feat: add immutable text edit intent and outcomes"
```

## Task 6: Tier 0 Planner, Patch, and Verifier

**Files:**
- Create: `model/text_commit/plan.py`
- Create: `model/text_commit/patch.py`
- Create: `model/text_commit/verify.py`
- Create: `model/text_commit/engine.py`
- Create: `test_scripts/test_text_commit_tier0.py`

**Step 1: Write Red classifier tests**

Only the deliberately narrow whole-`Tj`, equal-advance, direct-page Latin case selects Tier 0. Every unsupported gate returns a stable reason code.

**Step 2: Write Red mutation-isolation tests**

Candidate failure, digest mismatch, stale source, verification failure, and rejected capability must leave the live document unchanged.

**Step 3: Write Red fidelity tests**

Assert source font/resource xrefs, annotations, downstream text origins/matrices, and decoded bytes outside declared ranges remain unchanged. Assert pixels outside the target halo are identical.

**Step 4: Confirm Red**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_tier0.py -q
```

**Step 5: Implement scratch-first preparation**

Prepare/verify candidates on target-page scratch input. `commit()` revalidates fingerprints and applies exactly one validated `PatchSet` to live stream objects.

**Step 6: Run Green**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_tier0.py -q
```

**Step 7: Commit**

```bash
git add model/text_commit/plan.py model/text_commit/patch.py model/text_commit/verify.py model/text_commit/engine.py test_scripts/test_text_commit_tier0.py
git commit -m "feat: add verified lossless Tier 0 text patch"
```

### Amendment (2026-08-01): advance source is `/Widths`, not the face

Tier 0 shipped inert — 0 accepted shows on all six corpus fixtures. Measurement
(read-only, counts-only) attributed 98.1% of the block to the font gate, of which
76.6% was `FONT_FACE_UNAVAILABLE`: seven unembedded Word-export fonts that all carry
a complete `/Widths` table. Sourcing the advance from the face was the design error.

> **Decision: for simple fonts the advance comes from `/Widths`, and the face is a
> fallback, not the contract.** A conforming viewer advances by
> `Widths[code - FirstChar] / 1000 * size` and never consults the font program.
> Proven empirically, not assumed: an embedded real `arial.ttf` whose `/Widths` are
> all 1000 lays out at 40.0pt in MuPDF while the extracted face reports 23.32pt.
> `FontCapability.advance_source` is now `"widths" | "face" | "none"`. This is also a
> soundness fix independent of coverage — 22 *embedded* capabilities were measuring
> advance from the wrong source. Because `/Widths` is exact rational arithmetic, the
> advance tolerance splits: `1e-9`/pt for widths-sourced, the existing `1e-3`/pt for
> face-derived.

> **Corollary that constrains Task 11: `/Widths` proves an advance, not a glyph.**
> Absent a face, glyph coverage is attested only for non-subset, non-symbolic,
> standard-family fonts (`ascii_repertoire_attested`); everything else refuses. The
> V0a–V0e render checks *cannot* backstop this — raster identity is compared outside
> a 2pt halo, so a committed tofu box passes verification. Any future relaxation of
> the glyph gate must come with a check that actually looks inside the glyph box.

**Dead end, recorded so it is not repeated: regex-parsing PDF dictionaries.** Three
separate review findings (indirect `/Flags`, inline vs. indirect `FontDescriptor`, and
a `/FontFamily (/Flags 0)` string-literal decoy that defeats any regex) had one root
cause. The fix is structural: `doc.xref_get_key(font_xref, "FontDescriptor/Flags")`
resolves inline-or-indirect descriptor *and* inline-or-indirect flags in a single call
and is immune to literal decoys. No regex reads a PDF dictionary in `fonts.py`.

**Second dead end: first-blocker counts.** Gates compose multiplicatively, so ranking
them by "what blocks the most shows first" misleads. The matrix/operator gates measured
0.36% while the font gate masked them and 15.25% (5,879 shows) after it was cleared — a
43× swing from the same measurement script. Size a relaxation only against a corpus with
the upstream gates already relaxed.

**Correction (same day, after decomposing the 5,879):** the sentence below that names
the TJ no-kern check as the carried-forward caveat is *true but misleading*, and the
number it cites was never broken down. `diag_gate_joint.py`'s `+tj_equiv_ops` policy
conflated a lexical relaxation with an unsound semantic one. Measured decomposition of
the 5,879 P3-eligible shows, by the operator form the policy admitted:

| operator form | shows | % of P3 | soundness |
|---|---:|---:|---|
| `Tj` with a **hex** string operand | 5,688 | 96.75% | purely lexical — same string, same advance |
| `Tj` with a literal operand (accepted today) | 165 | 2.81% | already eligible; blocked only by trm |
| `TJ`, one string item, **kerned** | 26 | 0.44% | **unsound** — the leading kern moves the origin |
| `TJ`, one string item, kernless | 0 | 0.00% | sound, and worth nothing on this corpus |

So the sound TJ relaxation is worth **zero shows**, and essentially all the value is in
hex `Tj`, which the earlier note never named. The two surviving relaxations are also
**jointly required**: 5,666 of the 5,688 hex shows are at uniform scale, so neither
uniform-scale nor hex-`Tj` alone delivers more than ~165.

Cost, checked rather than assumed:
- **hex `Tj` is a one-line gate change** at `plan.py:143`. The patch writer needs
  nothing — `plan.py:238` already replaces the *entire* string-operand byte range
  (`string_start`..`string_end`, delimiters included) with a freshly encoded literal, so
  a hex source operand is spliced out wholesale, and `replay.py:158` already normalizes
  hex and literal operands to identical `decoded_bytes`.
- **uniform scale is not just a gate flip.** Advance *equality* is scale-invariant
  (a uniform factor multiplies both sides), but `target_bbox` in `plan.py` adds a
  text-space `old_advance` to a page-space origin, which only coincides under identity.
  Under scale `s` the V0a–V0e halo would be measured over the wrong rectangle. The bbox
  math has to become scale-aware in the same change.

**The largest reachable population is not a gate at all.** With base state and trm
relaxed, `TJ` arrays that are multi-item or kerned account for **17,952 shows (46.6% of
corpus)** — the single biggest prize, and out of reach of any flag. Serving it means
patching *inside* an array and recomputing kerns to hold total advance, which is Tier 0
scope work of the same order as the `/Widths` change.

**Ceiling, and why Task 11 outranks all of the above.** Relaxing every structural gate
(trm shape and operator form) leaves 28,055 shows (72.79%) reachable; the residue is
`FONT_UNSUPPORTED_ENCODING` (14.74%), `mc_depth` (6.51%), and `render_mode` (5.55%).
But *reachable* is not *acceptable*: Tier 0 still requires the replacement's advance to
equal the source's. On the reachable population, P(advance preserved) for a uniformly
random same-length **single-character** swap averages 0.39, and no font in the corpus is
monospaced. That is the ceiling for the most permissive edit shape that exists — a
length-changing edit (typo fix, word swap, insertion) is accepted only by numeric
coincidence. **No number of structural relaxations changes this.** Tier 1
(transplant + erase-compensation) is the only direction that escapes the equal-advance
rule, and therefore the only one that changes what a user can actually do.

**Outcome:** `FONT_FACE_UNAVAILABLE` 29,526 → 0 with zero fonts newly refused. Corpus
acceptance is *unchanged* (174 accepted / 771 `FONT_UNSUPPORTED_ENCODING` / 174
`FONT_TYPE3`) because no show fails only the font gate — Tier 0 remains inert pending the
matrix/operator gates below. Carried forward to Task 11: the TJ relaxation needs a
**no-kern check**, not an item count; relaxing the trm gate inverts
`test_planner_rejects_uniformly_scaled_text_matrix`, which must be revised in the same
change rather than deleted.

## Task 7: Shadow Integration and Maintenance Policy

**Files:**
- Modify: `model/pdf_text_edit.py`
- Modify: `model/pdf_model.py`
- Modify: `model/edit_commands.py`
- Modify: `controller/pdf_controller.py`
- Create: `test_scripts/test_text_commit_shadow_mode.py`
- Create: `test_scripts/test_text_commit_maintenance.py`

**Step 1: Write Red shadow tests**

Shadow preparation/classification must not mutate the live document, alter history, schedule cleanup, or affect the legacy result.

**Step 2: Write Red high-fidelity isolation tests**

For Tier 0 outcomes assert:

- no `_push_down_overlapping_text`;
- no protected replay;
- no redaction;
- no Track A/B callback;
- no `pending_edits` entry that later triggers `clean_contents`.

**Step 3: Confirm Red**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_shadow_mode.py test_scripts/test_text_commit_maintenance.py -q
```

**Step 4: Integrate behind `legacy|shadow|tiered`**

Legacy remains default. Shadow logs sanitized reason codes and timing only. Tiered mode enters the new engine only for supported plans.

**Step 5: Replace page-level pending cleanup with explicit maintenance policy**

A fidelity-protected stream/page cannot be passed through `clean_contents` during interactive maintenance or save preparation. Define and test how legacy-edited and Tier-0-edited pages coexist.

**Step 6: Run Green and existing edit suite**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_shadow_mode.py test_scripts/test_text_commit_maintenance.py test_scripts/test_edit_text_helpers.py -q
```

**Step 7: Commit**

```bash
git add model/pdf_text_edit.py model/pdf_model.py model/edit_commands.py controller/pdf_controller.py test_scripts/test_text_commit_shadow_mode.py test_scripts/test_text_commit_maintenance.py
git commit -m "feat: integrate text commit shadow mode"
```

## Task 8: Exact Plan-Backed Preview

**Files:**
- Create: `model/text_commit/preview.py`
- Create: `controller/text_commit_coordinator.py`
- Modify: `controller/pdf_controller.py`
- Modify: `view/pdf_view.py`
- Modify: `view/text_editing.py`
- Create: `test_scripts/test_text_commit_preview_contract.py`
- Extend: `scripts/verify_no_jump.py`

**Step 1: Write Red contract tests**

Assert View only emits a preview request; Controller/worker returns raster DTOs; View never opens a PDF or calls Model. Assert stale responses are ignored by session/generation/token.

**Step 2: Write Red identity tests**

The preview candidate digest/token must equal the plan later committed. Mutating the document between preview and commit must return `STALE_PLAN` with no mutation.

**Step 3: Write Red performance tests**

No full-document snapshot is opened per keystroke. Cache one target-page scratch input per edit session and retain the current argument/image cache.

**Step 4: Confirm Red**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_preview_contract.py -q
```

**Step 5: Implement QThread coordinator**

Follow `controller/page_render_coordinator.py`: immutable work request, one worker, signals, session/generation guard, no QWidget access off the main thread.

**Step 6: Keep legacy preview explicit**

`PreviewRenderer` remains only for legacy Tier 2. Plan-backed Tier 0/1 preview never falls back to HTML while claiming exactness.

**Step 7: Run Green and no-jump gate**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_preview_contract.py -q
.venv/Scripts/python.exe scripts/verify_no_jump.py
```

**Step 8: Commit**

```bash
git add model/text_commit/preview.py controller/text_commit_coordinator.py controller/pdf_controller.py view/pdf_view.py view/text_editing.py test_scripts/test_text_commit_preview_contract.py scripts/verify_no_jump.py
git commit -m "feat: preview exact prepared text edits"
```

## Task 9: Persistence, Undo/Redo, and Unsupported Boundaries

**Files:**
- Create: `test_scripts/test_text_commit_persistence.py`
- Create: `test_scripts/test_text_commit_boundaries.py`
- Modify: `model/pdf_model.py`
- Modify: `model/edit_commands.py`
- Modify: `model/text_commit/inspect.py`
- Modify: `model/text_commit/patch.py`

**Step 1: Write Red persistence tests**

Cover normal save, save-as, incremental save, full save, reopen, encrypted authentication, and a legacy edit followed by Tier 0.

**Step 2: Write Red identity tests**

Annotations preserve xref/dictionary/appearance. Signed documents and widget appearances reject. Undo restores source semantics and annotations; redo applies the same validated intent or fails stale without partial mutation.

**Step 3: Confirm Red**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_persistence.py test_scripts/test_text_commit_boundaries.py -q
```

**Step 4: Implement explicit boundaries**

Do not promise whole-file byte or xref identity after full save/garbage collection. Promise supported live-commit semantics and tested save/reopen behavior. Preserve encryption through existing save chokepoints.

**Step 5: Run Green**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_persistence.py test_scripts/test_text_commit_boundaries.py -q
```

**Step 6: Commit**

```bash
git add model/pdf_model.py model/edit_commands.py model/text_commit/inspect.py model/text_commit/patch.py test_scripts/test_text_commit_persistence.py test_scripts/test_text_commit_boundaries.py
git commit -m "test: enforce text commit persistence boundaries"
```

## Task 10: Tier 1 Spikes — No Production Enablement

**Files:**
- Create: `test_scripts/test_text_commit_textwriter_zorder.py`
- Create: `test_scripts/test_text_commit_identity_h_spike.py`
- Create: `scripts/audit_tier_coverage.py`
- Extend: `model/text_commit/patch.py`
- Extend: `model/text_commit/verify.py`

**Step 1: Red-test advance-preserving erase**

Show that deleting `Tj`/`TJ` moves later text, then require exact compensation.

**Step 2: Red-test TextWriter append vs transplant**

Cover text under/over filled rectangles, clipping, transparency, OCG, resource collisions, graphics-state bleed, extraction, and z-order.

**Step 3: Red-test font outcome honesty**

Extracted-face TextWriter output is `VALIDATED_FACE_EMBEDDED` unless source-resource reuse is separately proven.

**Step 4: Red-test Identity-H separately**

Do not infer source encoding from Unicode coverage. Require source CMap/CID/GID evidence.

**Step 5: Run spikes**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_textwriter_zorder.py test_scripts/test_text_commit_identity_h_spike.py -q
```

**Step 6: Record go/no-go decisions in this plan**

Do not enable Tier 1 from argument alone. Promote only the strategy that passes structural and raster verification on deterministic plus representative corpora.

> **Go/no-go record (2026-07-30, spike evidence from Steps 1–5; deterministic synthetic fixtures only — representative-corpus confirmation still owed before any production enablement):**
>
> - **(a) Advance-preserving erase — GO.** `patch.build_advance_preserving_erase` replaces a show op's full byte range with a kern-only `[N] TJ`, `N = -100000 * consumed_advance / (font_size * hscale)`. TJ adjustment numbers apply in unscaled text space and never re-trigger Tc/Tw, so one arithmetic correction covers ops that had Tc/Tw folded in. Spike proves the raw-delete hazard (later same-line show shifts >1pt), then exact compensation within 0.1pt on both Tj and kerned-TJ fixtures, raster identity outside halo, full `revert()` reversibility.
> - **(b) TextWriter/append (new ops at end of `/Contents`) — NO-GO, terminal.** Fails all 6 fixtures. Resource rebinding is fixable by real `TextWriter`, but z-order resurrection over occluding paint, escape from `q..Q` clip scope, loss of `/OC BDC..EMC` membership, and inherited dirty graphics state (dangling `rg`/`w` bleeding across stream concatenation) are **structural to append as a strategy**, not prototype artifacts. Do not revisit.
> - **(c) Source-position transplant — GO (Tier 1's write primitive).** `patch.build_transplant_replacement` splices the replacement at the source op's exact byte position; z-order, clip scope, ExtGState, and OCG membership are inherited **by construction** because nothing outside the declared byte range changes. Zero failures on all 6 fixtures. Caveat carried into Task 11: transplant alone is not advance-neutral — layer in (a)'s compensation math whenever the replacement advance differs from the source.
> - **(d) Font-outcome honesty — GO.** `patch.build_tier1_font_outcome` gated by `verify.prove_source_resource_reuse` (affirmative xref-identity proof; defaults to False on ambiguity). `SOURCE_RESOURCE_REUSED` only when the resource name still resolves to the exact source font xref; extracted faces report `VALIDATED_FACE_EMBEDDED`, system faces `SYSTEM_FACE_SUBSTITUTED`. Never inferred from face similarity or Unicode coverage.
> - **(e) Identity-H — PARTIAL: evidence collection GO, Tier 1 enablement NO-GO (stays on the deferred list).** `verify.collect_cid_encoding_evidence` reads `/Encoding`, descendant `/CIDToGIDMap` (absent key = PDF-spec-implicit Identity, never inferred), and a parsed `/ToUnicode` CMap; `CidEncodingEvidence.decode()` round-trips CIDs from source CMap evidence alone. Missing `/ToUnicode` is a hard `FONT_UNSUPPORTED_ENCODING` failure even when the face provably covers every target glyph. `bind_source_text` continues to refuse CID text (`UNDECODABLE_TARGET`). Characterization only; no tier accepts CID text.
>
> **Decision: Task 11 proceeds on transplant (c) + erase-compensation (a) + honest font outcomes (d). Append (b) is dead. Identity-H (e) remains deferred.** Tier 1 stays flag-off; nothing here enables it. `scripts/audit_tier_coverage.py` (read-only, counts-only) exists to size tier coverage on representative corpora before rollout.

**Step 7: Commit spike evidence**

```bash
git add model/text_commit/patch.py model/text_commit/verify.py test_scripts/test_text_commit_textwriter_zorder.py test_scripts/test_text_commit_identity_h_spike.py scripts/audit_tier_coverage.py plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md
git commit -m "test: evaluate Tier 1 text transplant strategies"
```

## Task 11: Tier 1 Horizontal Layout — Conditional on Task 10

### Amendment (2026-08-01): panel review — equal-advance is a policy, not a ceiling; Slice 1 first

A three-model independent review (Opus/Sonnet/Haiku, serial, each instructed to
*refute* the "structural relaxations are capped by the equal-advance rule"
verdict) returned unanimous **partially refuted**: the recommended order stands,
the reasoning behind it did not.

**Correction 1 — real edit classes pass the advance gate deterministically.**
`plan.py:_advance` is a pure multiset function of the text (Σ per-code `/Widths`
+ Tc·len + Tw·spaces), so any permutation of the same characters — the
transposition typo class (`teh`→`the`, `adn`→`and`) — has advance delta exactly
0.0 (~1e-13 float noise against a ≥1e-9 tolerance). Digit-for-digit edits
(dates, prices, versions) are advance-preserving wherever the font declares
tabular figures — verified for Helvetica in `test_text_commit_font_widths.py`;
unverified for the corpus's unembedded Word-export fonts (a one-line audit
addition settles it). The P=0.39 uniform-random-swap statistic measures neither
class; "accepted only by numeric coincidence" is withdrawn.

**Correction 2 — the cap is liftable with primitives that already passed their
spikes.** This plan's invariant already reads "…or carry an independently
verified compensation operation". Composing `build_advance_preserving_erase`'s
kern math with `build_transplant_replacement` yields `[(newtext) K] TJ` spliced
at the source op's byte range: arbitrary-length edits, same font resource and
encoding, every following show provably unmoved, no layout engine. **That is
Slice 1 of this task, and it ships and verifies before any Step-1 layout work**
(wrapping, alignment, overflow UI). The `LOSSLESS_STREAM_PATCH` label does not
fit growth (replacement ink exceeds the source bbox), so Slice 1 lands as
Tier 1 with an honest outcome, flag-off.

**Slice 1 hard gates (new, from the review; first two code-verified):**
- `patch.py:156-213` has no operator guard, and the spliced range differs by
  operator: for `"` the range starts at `operands[-3].start` (`replay.py:437`)
  and includes the aw/ac operands whose `Tw`/`Tc` assignments persist beyond
  the op (`replay.py:426-427`); `'` folds in an implicit `T*`
  (`replay.py:399-402`). A naive whole-op rewrite silently deletes persistent
  state — refuse `'` and `"` explicitly, with tests.
- Halo semantics under growth are undesigned: V0d's
  raster-identity-outside-halo stops proving the neighbour region unpainted
  once the halo widens. Decide and document: widen honestly, or admit
  compensated growth only when `verify.py:_region_is_uniform` proves the
  growth zone blank pre-edit.
- `_ocg_membership_lost` must become tri-state across **all** failure paths
  (`verify.py:341-379` — locked probe plus every raised-exception branch
  return `False`, recorded as `ocg_membership_preserved`) before
  V0d/`verify_tier1_strategy` runs on live handles. Not a blocker for starting
  Slice 1: transplant inherits OCG by construction.

**Prerequisites promoted ahead of this task** (phased checklist in TODOS.md):
1. Direct tests for `_tier0_target_from_resolve` — zero exist; its `" ".join`
   reconstruction must byte-match `bind_source_text`'s exact-equality demand
   (`inspect.py:233`), else eligible edits die as silent `NO_MATCH` above the
   planner where no corpus measurement can see them.
2. `scripts/audit_tier_coverage.py:70-76` still gates `tier1_candidate` on
   `capability.face is not None` — stale against the Task 10d `/Widths`
   finding; fix before running the owed representative-corpus audit.
3. Measurement pass (counts-only): edit-level funnel survival; forward
   advance-dependency rate (how often a successor consumes an op's advance
   before the next `Td`/`Tm`/`T*`/`BT` — decides how much of Slice 1 needs
   kern math at all); tabular-digit check; TJ binding-survival rate
   (`decoded_bytes` drops kern numbers, so kern-as-word-gap arrays can never
   bind — the 17,952/46.6% TJ figure is not achievable coverage).
4. D1 (hex-Tj + uniform-scale) with `a>0` in the relaxed matrix gate (else the
   48 reflected shows slip in) and the scale-corrected *fallback* bbox
   (`plan.py:243-250`; under scale<1 the halo inflates → false accepts —
   production already passes a page-space bbox via `pdf_text_edit.py:1225`).

**TJ arrays (decision):** whole-array targets only, via transplant — an
accepted target always covers the entire operator, so no unedited glyph sits
inside the replaced range; preserve leading/trailing kerns; never the unsound
`array_item_count==1` rule. In-array splicing with kern rebalancing is
rejected: it serves only substring targets every tier refuses.

### Amendment addendum (2026-08-01): GPT-5.6-sol independent evaluation

A fourth reviewer (GPT-5.6-sol, dual-lens) evaluated the same question and
returned **conditional GO — for functional coverage and edit capability, not
runtime performance**. It confirmed the direction above and added four
corrections that change this task's shape:

**1. The performance baseline moves BEFORE this task, not into Task 12.** There
is no basis for claiming post-Task-10 work improves runtime, and per-preview
cost is *increasing*: prepare + full page-stream replay + patch + raster +
revert per keystroke generation. On dense pages the plausible outcomes include
stale generations arriving faster than the worker can finish them. Baseline
p50/p95/p99 for prepare (cold/warm), key-to-preview, raster, stale-drop rate,
commit, live verification, undo/redo, and peak/resident memory (including after
repeated preview-session teardown) **before** D1, then re-measure each phase.
Derive budgets from the measured legacy baseline — do not adopt invented
thresholds; Task 12's own gate already says budgets come from measurement.

**2. Slice 1's key claim is a forecast, not a proven result.** Task 10 proved
advance-preserving erase and source-position transplant **separately**. "Every
following show is provably unmoved" holds for the composite only once one Red
test exercises the whole candidate: replacement renders, arbitrary replacement
advance compensated, later shows retain origins, persistent text state
unchanged, exact source range + stream digest checked, preview and commit use
the *same* prepared candidate, undo restores byte-identical bytes, verification
failure reverts everything.

**3. This task's `Files:` list is incomplete.** It names `layout.py`,
`plan.py`, `patch.py`, `engine.py`, `view/text_editing.py` — but Tier 1 also
needs explicit contracts for prepared-candidate/token DTOs, preview↔commit
candidate identity, live-commit rollback, persistence, undo/redo, resource-
dictionary and font-embedding mutation, clip / allowed-growth-region semantics,
and **shared content streams** (a stream referenced by multiple pages must be
handled or explicitly rejected). Extend the file list before implementing.

**4. Coverage must be published as a funnel, both weightings.** selected edits
→ target resolved → source bound → encoding/glyph accepted → candidate built →
preview verified → commit verified → save/reopen verified, reported per
document class with **document-weighted alongside show-weighted** figures.
Structural eligibility (D1's ~5,853 shows, the 15.25%) is headroom and must
never be quoted as product coverage. Zero-tolerance correctness gates and
per-direction pivot conditions are recorded in TODOS.md.

Where this reviewer proposed absolute latency/success thresholds, they are
**not adopted** — the plan's existing rule (derive p95 budgets from measured
baselines) governs.

**Carried to Task 12:** re-measure runtime against the pre-Task-11 baseline — `preview.py` re-runs
`prepare_tier0_plan` per keystroke generation, a full page re-parse on a
35k-show document — and report the Q3 ceiling decomposed (Identity-H stays
NO-GO so 14.74% never clears; render_mode 5.55% unaddressed): this task's real
ceiling is materially below 72.79% and is currently uncomputed.

**Files:**
- Create: `model/text_commit/layout.py`
- Create: `test_scripts/test_text_commit_tier1_layout.py`
- Modify: `model/text_commit/plan.py`
- Modify: `model/text_commit/patch.py`
- Modify: `model/text_commit/engine.py`
- Modify: `view/text_editing.py`

**Step 1: Write Red layout tests**

Word-boundary wrapping, CJK-per-character policy only when later enabled, first-baseline pinning, original leading, left/center/right alignment, overflow indication, and no neighbor movement.

**Step 2: Confirm Red**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_tier1_layout.py -q
```

**Step 3: Implement the smallest supported horizontal Latin layout**

No justification, complex shaping, Forms, rotation, or Identity-H in the first production slice.

**Step 4: Add UI warnings**

Show font resource action, overflow, tier downgrade, and strict rejection. Default overflow policy is commit-with-indicator for supported Tier 1; strict mode may reject.

**Step 5: Run Green**

```bash
.venv/Scripts/python.exe -m pytest test_scripts/test_text_commit_tier1_layout.py -q
```

**Step 6: Commit**

```bash
git add model/text_commit/layout.py model/text_commit/plan.py model/text_commit/patch.py model/text_commit/engine.py view/text_editing.py test_scripts/test_text_commit_tier1_layout.py
git commit -m "feat: add bounded Tier 1 text layout"
```

## Amendment (2026-08-02): Slice 1 landed

**What landed:** Task 11 Slice 1 (transplant + kern-compensated splice) shipped complete and verified. The mutation shape is `[(newtext) K] TJ` spliced at the source op's exact byte range. Four hard gates control ink growth: (1) operator guard refusing `/` single/double quote at the plan policy level and patch mechanism level; (2) growth-region blank proof via two independent pre-edit checks (character-intersection gate on rawdict, raster-uniformity gate on pixels); (3) shared-content-stream detection across all pages, gated in the common classifier so both tiers are covered; (4) font-resource re-proof before scratch and again before live apply_patchset. Tier 0 is always tried first; only ADVANCE_MISMATCH escalates to Tier 1, and the default engine flag stays max_tier=0 (flag-off). All 12 red tests pass, including the composite verification that replacement renders, arbitrary replacement advance is compensated, later shows retain origins, persistent state is unchanged, and exact source range + stream digest are checked. Six-PDF corpus audit confirms forward advance-dependency is 0.40% show-weighted (99.6% of shows have no successor before the next structural op).

**Halo decision:** Blank-growth-zone proof on the PRE-EDIT rendering. Compared box widens from target_bbox_page to verify_bbox_page (mapping through page.transformation_matrix, extending x1 in user space), proving the growth zone via two complementary gates sharing reason but not detail prefix. Inner guard = source_bbox + 2px (1px truncation + 1px AA bleed). Honesty limits: V0c cannot see same-span successors, 1.5pt unproven band remains, V0c false-rejects (never false accepts) on wider clip.

**Shared-stream decision:** New `inspect.find_pages_sharing_content_stream(doc, *, stream_xref, page_number)` never loads a Page object per page; handles array / indirect-array / single-stream / null shapes with fail-closed on any xref call exception. Detect and reject in `_classify_common` prologue so both tiers are covered (every high-fidelity tier mutates the stream in place). New `RejectReason.SHARED_CONTENT_STREAM` with counts-only detail. Blast radius narrow: six-PDF corpus uses one stream per page.

**Operator guard:** Two placements, both required. Plan-level: new `_classify_common` gate immediately before NOT_SINGLE_LITERAL_TJ returns `PlanRejection(UNSUPPORTED_SHOW_OPERATOR)`. Patch-level: `_SPLICEABLE_SHOW_OPERATORS = {"Tj", "TJ"}`, `_require_spliceable_show(show)` called as the first statement of both `build_advance_preserving_erase` and `build_transplant_replacement`, raising `UnsupportedShowOperatorError(ValueError)`. Why both: plan alone is insufficient because patch builders are public API called by spikes; patch alone is insufficient because exceptions escaping into per-keystroke preview are the failure class Task 10e had to fix.

**Corrected Slice 1 files_list (verbatim from implementation):**
- `model/text_commit/{dto,plan,patch,verify,inspect,engine}.py`
- `model/text_commit/preview.py` (threading coordination only, no layout)
- `model/{pdf_text_edit,edit_commands}.py`
- `controller/pdf_controller.py`
- `test_scripts/test_text_commit_tier1_slice1.py` (one fixture deviation: char-level vs span-level target_bbox in growth-refusal cases)

**Deferred from Slice 1 (stated in task scope to remain unblocked):** Whole-array TJ targets (Slice 1 refuses TJ at planner, one gate after operator guard); D4 _ocg_membership_lost tri-state (transplant inherits OCG, not blocking); rotated-page fallback-bbox shape defect (production safe today because pdf_text_edit.py:1225 passes real page-space bbox); TEXT_COMMIT_TELEMETRY wire-or-remove (untouched, TEXT_COMMIT_MAX_TIER now actually readable); different-face replacement/font re-embedding; Identity-H/CID enablement (evidence collection only); deletion/multiline via Tier 1; running growth gates inside per-keystroke preview (known preview/commit asymmetry documented); shadow-mode staying Tier-0-only classification.

## Amendment (2026-08-03): Slice 1 acceptance closed

**Verdict:** Task 11 Slice 1 end-to-end acceptance is closed on branch `task11/slice1-closure` (`db5ca5db` → `ff435fbe` → `2cf901f9` → `768ab174`, cut from the reviewed `08b15e7f`). All five P0 blockers from the GPT 5.6 Pro review are fixed red-light-first; the during-Task-11 backlog is done. Final gates on the closure HEAD: ruff clean, mypy clean (47 source files), full pytest `2178 passed / 21 skipped / 5 xfailed / 0 failed`. Defaults unchanged — `engine=legacy`, `max_tier=0`, `preview=legacy`, `telemetry=off`: closure is acceptance, not rollout; nothing here reaches a user until Task 12's gates pass.

**P0 → commit map (each with a test that fails on the pre-fix code):**
1. Preview token end-to-end wiring — `ff435fbe`: token read from the saved editor local before `view.text_editor = None`; `EditTextRequest.plan_token` → `EditTextCommand` → `model.edit_text(plan_token=)` → engine candidate cache (`test_text_commit_candidate_identity.py`).
2. Preview verdict parity — `2cf901f9`: preview runs the full Tier 0/1 verifier on the session scratch and refuses with the live reason class; clip widened to `effective_verify_bbox` (`test_text_commit_preview_parity.py`, parametrized over both WS-B growth fixtures; a `fail_prepare` monkeypatch proves commit consumes the cached candidate without re-preparing).
3. Uniform ≠ blank growth proof — `db5ca5db`: background-reference + drawings/images/shading occupancy layered onto uniformity, fail-closed on every uninspectable path (`test_growth_into_filled_vector_region_is_rejected` — uniformly black growth zone passes the old check, refused by occupancy).
4. Growth outside page — `db5ca5db`: `_bbox_within_page` containment gate at `_build_tier1`, reason `growth_outside_page` (`test_growth_verify_bbox_outside_page_is_rejected_during_prepare`, 200pt-page reproduction from the review).
5. Verifier-exception atomic revert — `db5ca5db`: live `verify_fn` wrapped, `applied.revert(doc)` + re-raise (`test_live_commit_reverts_and_reraises_when_verifier_raises` asserts byte-identical stream and fingerprint after the raise).

**Closed from the 08-02 deferred list (WS-D, `768ab174`):** D4 OCG tri-state (`unknown` never recorded as preserved); `TEXT_COMMIT_TELEMETRY` wired (`telemetry == "local"` gates the shadow log line); rotated fallback bbox now maps user space through `transformation_matrix * rotation_matrix` with `/Rotate 90/270` fixtures; `TARGET_IN_FORM_XOBJECT` target-scoped; stale undo mirrors stale redo (`STALE_UNDO`, zero mutation, command retained).

**Still Task 12 (registered, not implemented):** T12-P1-01..06 (TODOS.md registry with fixture names); rollout gates + fidelity/perf CI; ceiling decomposition; runtime re-measure vs the 2026-08-01 baseline; whole-array TJ stays deferred per the pivot condition.

**Residual risks, named** — ~~open~~ **ALL FOUR CLOSED 2026-08-04; (a) and (b) concealed a third, worse defect. See the 2026-08-04 amendment below.** Original text: (a) caller-supplied `target_bbox` (the production `pdf_text_edit.py` path and preview requests) is used untransformed — on `/Rotate 90/270` pages its axis-aligned shape is wrong versus the visual-space raster gates; the WS-D fix covers only the fallback-bbox path. (b) `inspect._origin_in_page_space` maps through `transformation_matrix` only (no `rotation_matrix`), so `binding.origin_page` is unrotated page space; consumers comparing it against visual-space quantities on rotated pages inherit the mismatch. (c) `growth_outside_page` is emitted as a bare string via a `getattr` fallback — the constant was never declared in `RejectReason`, contrary to the registry's own contract (one-line Task 12 cleanup). (d) The View-side finalize read-order fix has no dedicated GUI assertion (the chain is tested piecewise from Controller down; existing finalize tests would catch a read-after-clear regression only as a FAILED outcome).

## Amendment (2026-08-04): the 08-03 closure was re-verified adversarially and partly refuted; now genuinely closed

**Verdict:** Task 11 Slice 1 acceptance is closed — this time on evidence that survived an attempt to break it. The 2026-08-03 amendment above stands as a record of what was *believed*; three of its five P0 claims did not hold. Defaults are still `engine=legacy`, `max_tier=0`, `preview=legacy`, `telemetry=off`. Task 11 is **not** finished: the perf gate and Steps 1–6 layout remain (see the end of this amendment).

**Method.** Rather than accept the closure commits, an independent read-only pass was tasked with *refuting* each P0 fix on the closure HEAD, with the phase set to early-exit if any P0 turned out unfixed. It refuted three. Every subsequent fix landed Red-light first and, where a gate was involved, was pinned with its neighbouring gates neutered so the new gate is proven load-bearing on its own.

**What the refutation found, and why each mistake was the same shape.** All three failures are instances of *accepting evidence that does not prove the property*:

1. **P0-3 (uniform ≠ blank) — NOT fixed.** A growth zone filled solid black by a shading inside a Form XObject was still accepted. Two independent causes. The occupancy gates (`get_drawings`, `get_images`, an `sh` scan) enumerate *mechanisms*, and none of them can see ink one nesting level down — a blocklist over a format that permits nesting cannot be complete. And the background-reference gate meant to backstop them was **inert**: it sampled the reference colour from the target's own tail, inside the band it was certifying, so on a black background the reference *was* the ink. Monkeypatching all occupancy gates to no-ops left all five growth tests green — the proof was carried entirely by checks the review had already called insufficient.
2. **P0-1 (preview↔commit identity) — partial.** The `plan_token` cache made the commit path skip the style/geometry policy gates, so an edit carrying a drag reused the cached candidate and **silently discarded the drag**, UI-reachable. The token's preimage covers the candidate's semantics, not the request's. The accompanying test was vacuous.
3. **P0-2 (preview verdict parity) — partial.** Preview's V0e certificate compared a page count read on the patched document against a page count read on that same patched document — `x == x`, a green certificate for nothing. Tier 1's font-resource proof was absent from preview entirely.

**Fixes.** F1 rebuilds the growth proof as a background-*surface* argument: `background_reference_points` (left/above/below, provably disjoint from the widened halo), `_target_background_rgb` (strict-majority colour inside the target's own bbox; **no majority ⇒ reject, 100% majority ⇒ the target's ink is invisible against its background ⇒ reject** — this, not the reference comparison, is what kills black-on-black, because a large fill also covers every reference point), and `_reference_confirms_background`. `_target_tail_reference_rgb` and its fail-open median are deleted; ambiguity refuses everywhere. Deliberate deviation, recorded: a non-uniform reference neighbourhood skips that candidate rather than aborting the whole proof — a pass still requires an affirmative match. F2 makes the cached branch refuse on `style_overrides.changed` / `new_rect` (falling through to a fresh prepare, which yields an honest refusal reason) and re-run `find_pages_sharing_content_stream` before applying; the controller caches only after the PNG decodes. F3 captures `page_count` pre-patch and gives preview a real per-session KEEP round trip whose single `tobytes` feeds both the probe verdict and the session snapshot (keystroke budget preserved), fail-closed by default, plus `build_tier1_font_outcome`. F4 widens the live-commit catch to `BaseException` and chains a failed revert with an explicit "document may be inconsistent".

**Residuals (a)–(d) closed — and (a)+(b) were symptoms of a defect nobody had named.** `RejectReason.GROWTH_OUTSIDE_PAGE` is declared; `_origin_in_page_space` composes `rotation_matrix` (Defect A); the caller-supplied `target_bbox` was raw dict-space geometry and is now converted at the model boundary by `_dict_space_to_visual` (Defect B). Chasing those exposed **Defect C**: V0c/V0d compared dict-space rawdict geometry against a visual-space `target_bbox_page`, so **no tiered commit had ever succeeded on a `/Rotate 90/270` page.** Pre-existing, invisible to every test because the two spaces coincide when `/Rotate` is 0, and it would have been shipped by any closure that deferred (a) and (b) as cosmetic. Pinned by `test_full_tiered_commit_succeeds_on_rotated_page[90/270]`. (d) is closed by a GUI assertion whose sensitivity was proven by temporarily reintroducing the WS-A bug.

**Owed pre-Task-11 debts, also closed.** Whitespace-collapsed bind recovery: `_Tier0Target.source_kind` + `_dict_line_for_runs` behind a runtime content-and-geometry alignment proof, which answers blocker (a) by *verifying* the rawdict↔dict alignment per call instead of assuming it. Preview's `NO_MATCH` asymmetry: `whitespace_reconstructed` threaded controller → coordinator → `PlanPreviewRequest`. The `any(...)` line-identity guard: **kept**, with the decision and its rationale written into the code — its protection must not depend on `span_id`'s format being identical across two parsers — and an explicit instruction not to fabricate a fixture for it.

**Honest measurement.** After recovery landed, `TARGET_RECONSTRUCTION_UNVERIFIED` **rose**, 19.8% → 29.1%, while bind survivors went 51 → 93. That is the relabelling working, not a regression: MuPDF materializes wide `TJ` kerns as synthesized spaces, so on the dominant document the dict line is a reconstruction too, and cases formerly mislabeled `NO_MATCH` are now correctly named. Provenance is caveated in TODOS — Task 12's ceiling decomposition must re-measure rather than cite these figures.

**Gates.** `ruff check .` clean; `mypy model/ utils/` clean (47 source files); pytest **2,219 passed / 21 skipped / 5 xfailed / 0 failed**, run in four alphabetical chunks (402 + 871 + 323 + 623, every chunk exit 0) because a single whole-suite invocation hangs at PySide6 interpreter teardown in this venv — pre-existing, unrelated, now in PITFALLS. The run is post-Phase-2 on purpose; the earlier 2,178/2,201 figures predate changes to `_Tier0Target`'s shape. One intermittent flake seen and not reproduced: `test_multi_tab_plan.py::test_05_search_state_restored_per_tab`.

**Still Task 11, explicitly outstanding.** The runtime re-measure against the gitignored 2026-08-01 baseline, then Steps 1–6 smallest horizontal Latin layout. These are gated, not skipped: this plan's own constraint is that no layout expansion happens until Slice 1 preview is responsive, and Slice 1 has since added per-keystroke verification work to the preview path. The perf gate runs first and its result decides whether layout starts or preview cost is remediated. Task 12 (rollout gates, fidelity/perf CI, ceiling decomposition, T12-P1-01..06, plan archive) is unchanged.

## Task 12: Fidelity Gate, Rollout, and Documentation

**Files:**
- Create: `scripts/verify_commit_fidelity.py`
- Create: `test_scripts/test_text_commit_perf.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/PITFALLS.md`
- Regenerate: `docs/PITFALLS_INDEX.md`
- Modify: `TODOS.md`
- Archive when complete: `plans/archive/2026-07-18-acrobat-stable-text-commit-engine-v2.md`

**Step 1: Build the deterministic fidelity gate**

Run each supported and rejection case twice. Assert committed content changed when expected; forbid no-op passes.

**Step 2: Add performance gates**

Measure preparation, preview, commit, and resident-memory deltas on representative large fixtures. No full-document clone per keystroke. Use measured p95 budgets; do not guess a tolerance.

**Step 3: Add blocking Windows CI job**

The job uses the project venv/PyMuPDF pin and the synthetic corpus.

**Step 4: Update architecture and pitfalls**

Document the final tier contracts, preview/commit token lifecycle, maintenance policy, unsupported classes, and any PyMuPDF stream/font gotchas discovered.

**Step 5: Run full verification**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy model/ utils/
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe scripts/verify_no_jump.py
.venv/Scripts/python.exe scripts/verify_commit_fidelity.py
```

Expected: zero new ruff violations, mypy clean, full suite green, no-jump green twice, commit-fidelity green twice.

**Step 6: Rollout gates**

Do not change the default from `legacy` until all are true:

1. deterministic corpus and blocking fidelity CI exist;
2. zero unexpected stream/resource/raster change outside declared ranges;
3. annotation, encryption, save/reopen, and undo/redo matrices are green;
4. shadow telemetry shows supported coverage by document class;
5. p95 preview/commit and memory budgets are green;
6. degraded/rejected UX is manually verified;
7. feature-flag rollback to legacy changes no document schema.

Enable Tier 0 for internal/opt-in use first. Enable Tier 1 only after Task 10 go/no-go evidence. Report coverage separately for simple Latin, embedded subsets, CJK, Forms, annotations, and rejection-only classes; never hide unsupported classes behind one blended percentage.

**Step 7: Archive the completed plan and commit**

```bash
git mv plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md plans/archive/2026-07-18-acrobat-stable-text-commit-engine-v2.md
git add .github/workflows/ci.yml scripts/verify_commit_fidelity.py test_scripts/test_text_commit_perf.py docs/ARCHITECTURE.md docs/PITFALLS.md docs/PITFALLS_INDEX.md TODOS.md plans/archive/2026-07-18-acrobat-stable-text-commit-engine-v2.md
git commit -m "feat: complete verified text commit engine rollout"
```

## Verification Matrix

| Area | Required proof |
|---|---|
| Stream identity | Tier 0 decoded stream bytes are unchanged outside declared ranges; no normalized serialization. |
| Font outcome | Source/written xrefs, face fingerprint, glyph coverage, metrics, and resource action are explicit; no silent Base-14 fallback. |
| Text-state continuity | Later show operations retain origin/matrix/advance/state; compensation is verified where used. |
| Geometry | Non-target rawdict spans retain count, origins, sizes, and font identity within calibrated tolerances. |
| Raster | Pixels outside the target/paragraph halo are exact or within empirically calibrated epsilon. |
| Annotations | Xrefs, dictionaries, appearance streams, order, flags, and rectangles remain unchanged. |
| Save/reopen | Unencrypted/encrypted, save/save-as, incremental/full save, authentication, and reopen are covered. |
| Undo/redo | Undo restores source semantics; redo re-prepares or deterministically rejects stale input without partial mutation. |
| Stale plans | Any fingerprint mismatch returns `STALE_PLAN` and leaves the live document unchanged. |
| Performance | Target-page scratch preparation is cached per edit session; no full-document clone per keystroke; p95 and memory gates pass. |
| Unsupported classes | Each unsupported font/encoding/state/Form/widget/signature/rotation/shaping class returns a stable reason code and clear UX. |

## Telemetry and Privacy

Local telemetry may contain only tier/reason codes, font class/resource action, operator and byte-length counts, page-size bucket, timings, verification result, rollback result, and raster-diff counts.

Never record text, PDF bytes, stream snippets, document paths, passwords, font buffers, raw annotation data, hostnames, MAC addresses, usernames, or device identifiers. Raw stream digests are allowed only in local debug verification and must not be committed or uploaded.

## Reusable Existing Mechanisms

- `model/pdf_model.py:_capture_page_snapshot` — immutable source/undo input, not candidate rollback.
- `model/pdf_model.py:_restore_page_from_snapshot` — command undo/redo or emergency recovery only.
- `model/pdf_model.py` save, reauthentication, and round-trip chokepoints — persistence behavior.
- `model/edit_commands.py` — history boundary.
- `model/text_block_parsing.py` — geometric selection/index hint, not source identity.
- `model/pdf_content_ops.py` — precedent for operator-aware PDF mutations; do not reuse its normalized serializer for Tier 0 text.
- `controller/page_render_coordinator.py` — QThread, signals, session/generation guards.
- `view/text_editing.py` — frozen frame and legacy preview compatibility.
- `scripts/verify_no_jump.py` — deterministic gate structure.

## Definition of Done

The project can claim Acrobat-like text-edit stability only when:

- supported Tier 0/1 edits preserve declared structural and visual invariants;
- preview and commit use one stale-checked prepared candidate;
- unsupported cases are explicit, not silently substituted;
- legacy fallback is visibly degraded or rejected under strict mode;
- all project verification commands pass;
- architecture, pitfalls, TODOs, and the archived plan match the shipped behavior.

### Prereq D5 landed (2026-08-01): target derivation is a reconstruction

Direct tests for `_tier0_target_from_resolve` now exist
(`test_scripts/test_tier0_target_resolution.py`, 11 tests). The prerequisite
asked whether the `" ".join` at `pdf_text_edit.py:1223` byte-matches
`bind_source_text`'s exact-equality demand (`inspect.py:233`). Measured
answer: **not in general.** `text_block_parsing.py:_finalize` strips every
word run, so run text carries no whitespace and word boundaries come from
geometric gap analysis. `"Price is  100"` rebuilds as `"Price is 100"` and
fails to bind.

**Decision — make it honest, not clever.** The recovery path (read the
verbatim dict line text, which *does* preserve the source exactly) was
considered and deferred: it crosses the rawdict↔dict index-alignment
assumption in `_build_page_index` and does not address the single-run
padding case (`"  Total  "` → `"Total"`, which also fails to bind). Shipping
a reconstruction *derived* differently but still unverified would repeat the
Task 10f root cause — inferring a property from evidence that does not prove
it. Instead the boundary now distinguishes the two claims:
`RejectReason.NO_MATCH` continues to mean "the document lacks this text",
while `TARGET_RECONSTRUCTION_UNVERIFIED` means "our target string was
assembled from N stripped runs and may itself be wrong".

**Consequence for Task 12's coverage reporting:** the
`TARGET_RECONSTRUCTION_UNVERIFIED` count is a *known-fixable gap*, not part
of the structural ceiling. It must not be folded into the refusal total as if it
were a document property.

**Also found (mutation testing):** the `any(...)` line-identity guard is
subsumed by the full-line set-equality check that follows it and cannot be
made SENSITIVE — `span_id` encodes page/block/line, so cross-line members can
never satisfy the set equality. Recorded rather than papered over; see
TODOS.md and PITFALLS.md.
