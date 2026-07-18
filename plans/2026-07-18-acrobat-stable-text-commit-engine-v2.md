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

**Step 7: Commit spike evidence**

```bash
git add model/text_commit/patch.py model/text_commit/verify.py test_scripts/test_text_commit_textwriter_zorder.py test_scripts/test_text_commit_identity_h_spike.py scripts/audit_tier_coverage.py plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md
git commit -m "test: evaluate Tier 1 text transplant strategies"
```

## Task 11: Tier 1 Horizontal Layout — Conditional on Task 10

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
