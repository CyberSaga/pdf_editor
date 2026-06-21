# PDF Editor — R-Series Code Review Findings

Single review log for the staged refactor campaign (R0 → R6) on branch
`feat/ui-ux-fable5-refactor`. Each round (R2, R3, …) gets its own section;
findings are ranked by severity within a round and carry a stable ID
(`R2-01`, `R3-01`, …) so they can be referenced and tracked to closure.

**Severity scale:** Critical · High · Medium · Low · Info
**Status values:** Open · Fixed · Won't-fix (accepted) · Tracked-elsewhere

**Method.** Each round is reviewed two ways and the results merged:
1. Inline review by Claude — source read of the actual diff + helpers, targeted
   `pytest` runs on the affected modules, and `ruff check` on touched production
   files.
2. The multi-angle "fusion" code-review workflow (`docs/fusion-agent-manual.md`):
   independent finder angles (correctness/architecture, simplification/efficiency,
   second-opinion) with an adversarial verifier per candidate.

A finding is recorded here only after it survives verification; the source
(inline vs fusion, and confidence tier) is noted per finding.

---

## R2 — MVC Boundary Reconvergence

**Range:** `2a2aa96^..0dd1fac` — 7 commits, R2.1 → R2.7
(`2a2aa96` R2.1 layer-boundary AST guard · `cbe0284` R2.2 generalize encryption
AST guard · `6e3dea1` R2.3+R2.4 view stops opening fitz / controller page-rect
facade · `44abebe` R2.4 docs · `870728c` R2.5 controller read-only query facade ·
`dc1bb2c` R2.6 PreviewRenderer public preview-HTML builder · `0dd1fac` R2.7
print-renderer `safe_render_scale` clamp + merge-source `_guard_foreign_doc`).

**Reviewed:** 2026-06-19
**Production files touched:** `controller/pdf_controller.py`, `model/pdf_model.py`,
`view/pdf_view.py`, `view/text_editing.py`, `src/printing/pdf_renderer.py`,
`utils/render_limits.py` (consumed). Tests: `test_layer_boundaries.py` (new),
`test_xref_repair.py`, `test_text_editing_gui_regressions.py`,
`test_thumbnail_context_menu.py`, `test_interaction_modes.py`.

**Verdict:** Clean and behavior-preserving — no correctness or behavior-change
defects; affected tests + ruff green. **18** quality/hardening findings recorded
(R2-01…R2-19; R2-03 refuted/accepted), all Low/Info except **R2-13** (Low–Medium —
`compose_merged_document` lacks an aggregate merge page/size cap). The most
user-facing are **R2-13** and **R2-17** (merge resource-exhaustion + uncaught
compose-path error) and **R2-18** (large-format prints silently downscaled); the
rest are cleanups, test-hygiene, and doc-accuracy. None block; several cluster
into a few small fixes.

> **Fusion-workflow cross-check (two runs + inline; near-complete).**
> - **Parallel run** (10 angles → 38 candidates → 14 verified): corroborated
>   **R2-02** three times (now high confidence), refuted **R2-03** (cosmetic,
>   accepted), added **R2-04…R2-08**, and refuted four non-issues (a
>   controller→model `get_watermarks` call — allowed; facade null-safety
>   "inconsistency" — callers guard first; the shim param rebind — stylistic; and
>   R2-03). Its verify phase was then truncated by the account session limit.
> - **Serial run** (one agent at a time, to dodge the parallel-burst limit;
>   18 candidates, **all now verified** across the initial run + a serial re-run
>   of the verifiers that had died on the limit): added **R2-09…R2-13** initially,
>   then **R2-14…R2-19** when the 9 died verifiers were re-run (6 CONFIRMED, 3
>   REFUTED — `test_rotated_text_editor_preview.py:62`,
>   `test_no_jump_editor_geometry.py:1776`, `test_thumbnail_context_menu.py:152`).
>   **No candidates remain unverified.**
> - **R2-01** was never machine-cross-checked (it was seeded as already-known, so
>   no verifier ran for it); it stays inline-only but is corroborated by the
>   closely-related, confirmed **R2-09**.
> - Synthesis/dedup was done by hand (this section); no automated synthesis pass ran.

### Findings

#### R2-01 — Low — View `fitz.open` guard has evadable escape hatches
**Status:** Open · **Source:** inline review
**Where:** `test_scripts/test_layer_boundaries.py::_count_fitz_open` /
`test_view_layer_has_no_unsanctioned_fitz_open`

The view-layer guard counts only the literal `fitz.open(...)` shape
(`ast.Call` → `Attribute(attr="open")` on `Name(id="fitz")`). It does **not**
catch equivalent document-opening forms a future R3 edit could introduce in
`view/`:
- `fitz.Document(path)` — a direct alias of `fitz.open` that opens a file;
- `import fitz as f; f.open(...)` — aliased module name;
- `from fitz import open` — bare imported name.

The guard's purpose during the god-module decomposition is to be airtight, so
this is worth tightening: match `f.attr in {"open", "Document"}` and resolve the
imported `fitz` alias (track `import fitz as X` / `from fitz import open`). The
model-import guard has the analogous, lower-priority gap for dynamic imports
(`importlib.import_module`, `__import__`). Low probability today — the codebase
uses `fitz.open` uniformly — but cheap to close.

#### R2-02 — Low — `PreviewRenderer._model` became dead (write-only) state
**Status:** Open · **Source:** inline review + fusion (CONFIRMED ×3) — high confidence
**Where:** `view/text_editing.py` — `PreviewRenderer.__init__` / `render`

After R2.6, `render()` no longer reads `self._model`; the borrow path now goes
through `self._build_preview_html`. The only remaining consumer is the
`__init__` back-compat shim, and that closes over the local `model` parameter,
not the attribute. So `self._model` is assigned and never read again. Safe to
drop (and have `PreviewBackedInlineTextEditor.__init__` pass a builder instead of
`model=`), or keep it as the documented back-compat constructor knob. Not a bug —
cleanliness only.

#### R2-03 — Very Low — `_default_image_insert_rect_for_page` now relies on the `except`
**Status:** Won't-fix (accepted) · **Source:** inline review; refuted by fusion verifier as a non-issue (behavior is equivalent)
**Where:** `view/pdf_view.py` — `_default_image_insert_rect_for_page`

The rewrite changed the pre-check from `if model is not None and model.doc:` to
`if model is not None:`. When `model.doc` is `None`, the new code calls
`get_page_rect` → `self.model.doc[page_idx]` → `None[page_idx]` → `TypeError`,
which the surrounding `try/except Exception: pass` swallows, yielding the same
default A4 rect (595×842). The end-state is identical, but it now leans on the
exception path rather than the guard. Cosmetic; optionally restore the
`model.doc` truthiness check for clarity.

#### R2-04 — Low — Test helper hand-copies the `iter_text_targets` dispatch (third copy)
**Status:** Open · **Source:** fusion (CONFIRMED)
**Where:** `test_scripts/test_text_editing_gui_regressions.py:1100` —
`_outline_controller` helper

The test's `_outline_controller` mock re-implements the
paragraph/run/`blocks_fallback` dispatch by hand instead of delegating to the
real `PDFController.iter_text_targets`, making it a third copy of that logic
(production facade + the two call sites it unified). The mock can now drift
silently: if `iter_text_targets` changes its mode handling or fallback rule, the
test keeps passing against the stale copy and stops guarding the view→controller
contract it exists to protect — a regression ships green. Have the mock call the
real facade (or assert against it).

#### R2-05 — Low — PreviewRenderer shim duplicates `build_insert_preview_html` (two sources of truth)
**Status:** Open · **Source:** fusion (CONFIRMED) · relates to R2-02
**Where:** `view/text_editing.py:626-633` (shim) vs
`controller/pdf_controller.py:2695-2701` (`build_insert_preview_html`)

R2.6's whole point was to centralize the preview CSS/HTML in the public
`build_insert_preview_html` builder, but the legacy `model=` shim re-implements
the identical `_build_insert_css` / `_convert_text_to_html` call pair. The
pixel-parity-critical preview↔commit contract now has two copies. If the
css/html arg mapping changes, one site can be updated and the other forgotten,
breaking the byte-identical invariant on whichever construction path tests don't
exercise — and the no-jump gate would not catch it (both derive from the same
model in the test path). Collapse the shim to call the single builder. Fixing
this together with R2-02 (drop `model=`/`self._model`, always inject the
controller builder) removes the duplicate at the source.

#### R2-06 — Low — Dead `getattr` defensiveness in the facade masks future renames as silent empty results
**Status:** Open · **Source:** fusion (CONFIRMED)
**Where:** `controller/pdf_controller.py:2668` (`iter_text_targets`), `:3316` /
`:2676` (`get_text_blocks`)

The facade guards `block_manager` access with
`getattr(bm, "get_runs", lambda _i: [])(page_idx)` etc., but `BlockManager`
unconditionally defines `get_paragraphs`/`get_runs`/`get_blocks`
(`model/text_block.py:151,158,161`), so the fallback branch is unreachable. Two
costs: it adds per-call `getattr` + lambda churn for an impossible case, and —
worse — it converts a genuine future bug (someone renames `get_runs`) from a loud
`AttributeError` into a silent empty list, so the outline/selection target list
comes back empty and text-selection silently finds nothing with no traceback.
Call `bm.get_runs(page_idx)` directly so it fails loudly. (Pre-R2.5 the view did
call these methods directly without the guard.)

#### R2-07 — Info — Per-page `fitz.Matrix` rebuilt even when the clamp is a no-op (efficiency)
**Status:** Open · **Source:** fusion (CONFIRMED)
**Where:** `src/printing/pdf_renderer.py:83`

R2.7 correctly moved the clamp into the per-page loop (the clamp must be
per-page), but it also moved `fitz.Matrix(...)` construction inside, so for a
print job of uniformly-sized normal pages — where `safe_render_scale` returns
`zoom` unchanged every time — an identical `Matrix` is rebuilt N times. The
per-page *clamp* is required; the *Matrix* can be memoized: build the unclamped
`fitz.Matrix(zoom, zoom)` once and reuse it unless a page trips the clamp. Minor;
optional micro-optimization, no correctness impact.

#### R2-08 — Info — `get_text_blocks` duplicates the blocks-fallback branch of `iter_text_targets`
**Status:** Open · **Source:** fusion (PLAUSIBLE — lower confidence)
**Where:** `controller/pdf_controller.py:2676`

`get_text_blocks` repeats the same `list(getattr(bm, "get_blocks", …)(…) or [])`
boilerplate that `iter_text_targets`' `blocks_fallback` branch already contains,
so the `get_blocks` reach-through lives in two places that must change in
lockstep. Largely subsumed by the R2-06 cleanup. Lower confidence (the two call
patterns are arguably distinct enough to keep separate).

#### R2-13 — Low–Medium — `compose_merged_document` has no aggregate page/size cap (merge resource-exhaustion gap)
**Status:** Open · **Source:** fusion-serial (CONFIRMED) — *most actionable new finding*
**Where:** `model/pdf_model.py:1411` (`compose_merged_document`)

R2.7 routed each merge source through `_guard_foreign_doc` (per-source caps:
`_MAX_PAGES` = 5,000, `_MAX_PDF_BYTES` = 512 MB) and its own comment claims it
closed "the `_MAX_PDF_BYTES`/`_MAX_PAGES` limits a merge previously bypassed."
But `compose_merged_document` loops `merged.insert_pdf(file_doc)` over N sources
with **no aggregate cap**, so e.g. 50 files × 5,000 pages compose into a
~250,000-page in-memory document that OOMs/hangs inside the insert loop — the
exact CWE-400/409 resource-exhaustion class R2.7 set out to close on the merge
path. This is an **asymmetry, not a deliberate omission**: the sibling insert
path applies a post-merge invariant
(`len(self.doc) + len(actual_source_pages) > _MAX_PAGES`, `model/pdf_model.py:1349`)
*and* has a regression test (`test_security_pdf_resource_guards.py`); the compose
path has neither. The per-source 512 MB cap is also a *compressed*-file cap, not
a decompressed-content cap. Local DoS only (single-user desktop, requires
deliberately assembling many large PDFs in the merge dialog), no corruption/RCE —
hence Low–Medium. **Fix:** apply the same aggregate `_MAX_PAGES` invariant in
`compose_merged_document` (and `save_ordered_sources_as_new`), with a test
mirroring the insert-path one.

#### R2-09 — Low — Model-import guard skips ALL relative imports (level ≥ 2 escapes)
**Status:** Open · **Source:** fusion-serial (CONFIRMED) · companion to R2-01
**Where:** `test_scripts/test_layer_boundaries.py:42` —
`test_model_layer_imports_no_qt_and_no_view_or_controller`

The model-import check only inspects `node.level == 0` ImportFrom nodes (absolute
imports), skipping every relative import with the comment "node.level > 0 stays
within model/." That's false for `level >= 2`: a `from ..view import X` in a
`model/` module — or `from ...view import X` under `model/tools/` — resolves to
the repo-root `view`/`controller` packages, escaping `model/`, yet the guard
never flags it. No such import exists today (no `from ..` in `model/`), so it's a
coverage gap, not a live violation — but `model/tools/` already uses relative
imports as a convention, so a future contributor could naturally trip it. Fix:
also inspect `node.level` and forbid a `level >= 2` ImportFrom that resolves to
`view`/`controller`. (Same R-series structural net as R2-01 — two holes in it.)

#### R2-10 — Low — Dead `model=` test-mock keys left beside the live facade key (×4)
**Status:** Open · **Source:** fusion-serial (CONFIRMED)
**Where:** `test_scripts/test_text_editing_gui_regressions.py:1285, 1332, 1393, 1527`

R2.5 moved the production call from `controller.model.get_render_width_for_edit`
to the `controller.get_render_width_for_edit` facade (`view/text_editing.py:1239`,
now with zero `controller.model.*` reach-throughs). The test update added the new
top-level facade key to the four `create_text_editor` controller mocks but left
the now-dead nested `model=SimpleNamespace(get_render_width_for_edit=...)` key in
place. Write-only mock state, no functional impact (the tests pass), but it
misleads a reader into thinking the view still reaches through `controller.model`
— and the AST guard polices imports/`fitz.open`, not `controller.model.<method>`
reach-throughs, so CI wouldn't catch a re-introduced one. Remove the four stale
`model=` keys.

#### R2-11 — Info — Incomplete `.doc` decoupling: scattered `controller.model.doc` existence checks remain
**Status:** Open · **Source:** fusion-serial (CONFIRMED)
**Where:** `view/pdf_view.py` — document-existence reach-throughs at ~lines 2409,
3264, 3362, 3384, 3896, 3964 (anchors drift between commit `0dd1fac` and the
working tree)

R2.4/R2.5 routed the view's page-*geometry* reads through
`get_page_rect`/`get_page_rotation` and added the query facade, but left several
direct `controller.model.doc` *document-existence* checks in the same file, and
added no `has_document()`/`is_document_open()` accessor — so the view still
depends on the model's `.doc` attribute shape there. Behavior-preserving today
and not a CI failure (the AST guard doesn't police attribute reach-throughs); the
risk is a future `.doc` shape change (e.g. it becomes a property or
session-scoped handle) breaking the un-converted sites while the facade-routed
ones stay correct. Optional: add a `controller.has_document()` accessor and route
these through it. (The verifier noted one originally-cited site, ~5054, was in
fact converted by this diff; content of the rest confirmed, line anchors drift.)

#### R2-12 — Low — `iter_text_targets`/`get_text_blocks` make an O(N) `list(...)` copy on every call
**Status:** Open · **Source:** fusion-serial (CONFIRMED, downgraded Medium→Low) · folds into R2-06
**Where:** `controller/pdf_controller.py:2671` (both `list(...)` wraps in those two methods)

The facade wraps the `BlockManager` accessor results in an unconditional
`list(...)`. Those accessors return the underlying index list *reference*
(`model/text_block.py:152-162`), and pre-R2.5 the view enumerated them in place
(zero copy). Callers only `enumerate(...)`, so the copy is unnecessary. On a
text-dense page, the debounced outline redraw (`_draw_all_block_outlines`) and
hit-test (`_iter_outline_targets`) now copy the whole per-page run/block list per
visible page per redraw. The verifier downgraded to Low: it's a *shallow*
pointer-array copy, the redraw is debounced (~80 ms), and per-item
`fitz.Rect`/`scene.addRect` work dominates — a minor cleanup, not a hot path.
Naturally folded into the R2-06 fix (drop the dead `getattr`; return the
reference directly, copying only if a caller actually mutates).

#### R2-17 — Low — Uncaught `ValueError` from the new compose-path guard (TOCTOU) reaches the Qt event loop
**Status:** Open · **Source:** fusion-serial (CONFIRMED) · distinct from R2-13
**Where:** `controller/pdf_controller.py:1046` (`merge_ordered_sources_into_current`) and `:1070` (`save_ordered_sources_as_new`)

R2.7 routed `compose_merged_document`'s per-source opens through
`_guard_foreign_doc`, which can now raise `ValueError` (over `_MAX_PAGES`, or over
`_MAX_PDF_BYTES` via `path.stat()`) — an exception type the old bare `fitz.open`
path didn't produce here. The compose-time consumers (`:1046`, `:1070`) and the
`start_merge_pdfs` Qt slot above them have no `try/except`, so if a source is
grown past 512 MB / 5,000 pages between dialog-add and final compose (TOCTOU), the
`ValueError` propagates as an unhandled traceback into the Qt event loop instead
of the friendly `show_error` the *add*-time path (`_resolve_merge_file`) gives.
(Verifier correction: `FileNotFoundError` is **not** new — `fitz.open` already
raised it — only the caps `ValueError` is the genuine regression.) Fix: wrap the
compose call in the merge flow with the same user-facing error handling as the add
path.

#### R2-18 — Low — `safe_render_scale` silently downscales legitimate large-format prints (not just bombs)
**Status:** Open · **Source:** fusion-serial (CONFIRMED) · refines the R2.7 "verified clean" note
**Where:** `src/printing/pdf_renderer.py:86`

The R2.7 clamp is correct as a decompression-bomb defense, but it also fires on
*legitimate* large pages at normal print DPI with no warning/log/user signal: an
A0 page (2384×3370 pt) at 300 DPI (zoom ≈ 4.17) computes to ~140 MP > the 40 MP
`_MAX_PIXMAP_PX`, so it is silently capped to ~161 effective DPI (A1 at 300 DPI
also clamps; A2 and smaller do not). The user gets a visibly soft poster/CAD print
with nothing signalling the reduction. This refines the earlier "clamp leaves
normal pages untouched" note — true for normal pages, but "oversized" includes
real large-format documents. Fix: log/surface a warning when the clamp fires,
and/or raise `_MAX_PIXMAP_PX` for the print path.

#### R2-15 — Low — R2.4/R2.5 facade methods have no direct test coverage
**Status:** Open · **Source:** fusion-serial (CONFIRMED, downgraded Medium→Low)
**Where:** `controller/pdf_controller.py:2628` (the facade block)

The new facade (`get_page_rect`, `get_page_rotation`, `iter_text_targets`,
`get_text_blocks`, `get_render_width_for_edit`, `get_watermarks`, controller-level
`has_unsaved_changes`/`ensure_page_index_built`, `build_insert_preview_html`) is
never called on the *real* controller in any test — tests only mock these (the
`_outline_controller` helper, inline `SimpleNamespace` stubs, `MagicMock`). So the
load-bearing contracts the docstrings promise — `get_page_rect` returns a
`fitz.Rect` **copy** (view-side mutation can't corrupt the live page) and is
rotation-faithful — are asserted nowhere. No live bug today (current callers build
new `fitz.Rect`s rather than mutating the return), but a refactor dropping the copy
would reach users with no failing test. Add a direct contract test (copy-identity
+ rotation faithfulness).

#### R2-16 — Low — ARCHITECTURE.md overstates the decoupling (false at HEAD) + `text_target_mode` read
**Status:** Open · **Source:** fusion-serial (CONFIRMED, downgraded Medium→Low) · relates to R2-11
**Where:** `docs/ARCHITECTURE.md:413`

R2's new §7.2 states "The view no longer reaches through `controller.model.<…>`,"
but the view still does: `model.doc` presence checks (`pdf_view.py` ~2409/3361/3964)
**and** `model.text_target_mode` read straight off the model (~2412). R2 facaded
away the *geometry* reach-throughs but left these doc-presence/mode reads, so the
documented invariant is already false at HEAD and is unenforced (the AST guard
doesn't police attribute reach-throughs). Read-only, no correctness/security impact
today; the risk is a future R3 view-decomposition trusting a false contract. Fix:
soften the doc to "geometry/method reach-throughs removed; doc-presence/mode reads
remain," or add `has_document()`/`text_target_mode` accessors (folds into R2-11).

#### R2-14 — Low — Stale allowlist comment in the encryption guard (says "R5 gap open"; R5.5 already fixed it)
**Status:** Open · **Source:** fusion-serial (CONFIRMED, downgraded Medium→Low)
**Where:** `test_scripts/test_xref_repair.py:356`

The R2.2 allowlist entry for `pdf_optimizer.build_working_doc_for_optimized_copy`
is commented "**KNOWN GAP (tracked for R5)** … the fix is a product decision
(refuse vs preserve-encryption)." R5.5 (`5165b0f`) already shipped that decision —
preserve-encryption via `reapply_source_encryption` on a reopened output handle,
deliberately keeping the live-doc `model.doc.tobytes()` decrypt allowlisted so the
guard stays green. The comment now misrepresents settled work as pending and gives
no cross-reference to the compensating R5.5 step, so a maintainer could redo R5.5
— or, worse, delete `reapply_source_encryption` trusting the allowlist as the
tracker, after which the still-allowlisted decrypt sink would never re-flag. Fix:
update the comment to point at R5.5. (Test-comment-accuracy companion to the
Context note below, which records that the underlying *security* gap was fixed in
R5.5.)

#### R2-19 — Low — Encryption-guard allowlist keyed by bare function name (no class qualification)
**Status:** Open · **Source:** fusion-serial (CONFIRMED)
**Where:** `test_scripts/test_xref_repair.py:386` (`_LiveDocVisitor`)

The R2.2 decrypt-sink allowlist is keyed by `(relative_filename, bare_function_name)`;
`_LiveDocVisitor` tracks only `FunctionDef`/`AsyncFunctionDef` (no `visit_ClassDef`),
so the key carries no class qualification. A future live-doc serialization added
inside any function/method whose bare name collides with an allowlisted name in the
same module (e.g. a second `current_document_size_bytes`) would be silently allowed
to bypass `encryption=KEEP`. Latent precision gap (no current name collisions among
the three allowlist entries), test/CI-only. Fix: class-qualify the allowlist key.

### Context note (not a finding against R2)

R2.2's generalized encryption guard allowlists
`pdf_optimizer.build_working_doc_for_optimized_copy` with a documented
"optimize-copy decrypts an encrypted source" gap. That is a real security gap,
but it is **pre-existing** — R2.2 only made it *visible* by widening the AST scan
— and per `0619-export-transcript/commit-contexts.md` it was fixed later in R5.5
(`5165b0f`, "optimize-copy preserves source encryption"). Not chargeable to this
range; recorded here for traceability.

### Verified clean (high confidence)

- **Controller read-only query facade.** Every rerouted view call site
  (`get_page_rect`, `get_page_rotation`, `iter_text_targets`, `get_text_blocks`,
  `get_watermarks`, `has_unsaved_changes`, `get_render_width_for_edit`,
  `ensure_page_index_built`) preserves prior behavior. `get_page_rect` returns a
  `fitz.Rect` *copy* (no aliasing of the model-owned rect) and is
  rotation-faithful (`page.rect` reflects rotation, matching the old direct
  reads). `iter_text_targets`' `blocks_fallback` flag faithfully reproduces the
  two original call sites' run→block fallback semantics.
- **PreviewRenderer byte-identical contract.** Both the controller builder
  (`build_insert_preview_html`) and the legacy `model=` shim forward identical
  `float`/`tuple`/`str` arguments to the same `_build_insert_css` /
  `_convert_text_to_html`, with the same `font_hint`/`latin_font` mapping and
  `line_height`→CSS-only routing as the pre-R2.6 code. Pixel parity holds (the
  no-jump gate's invariant is preserved).
- **`safe_render_scale` clamp (R2.7).** Clamps an oversized page's pixmap to
  exactly `_MAX_PIXMAP_PX` and returns the scale unchanged for normal pages at
  any real print DPI (the 0.1 floor only bites below ~7 DPI, a documented
  tradeoff). Moving the matrix into the per-page loop is correct since the clamp
  is per-page.
- **`_guard_foreign_doc` merge routing (R2.7).** Identical auth logic and error
  strings to the old inline block; both merge sites
  (`compose_merged_document` file branch, `open_merge_source`) mirror
  `open_insert_source`. No unguarded foreign `fitz.open` remains in the changed
  code (the other model `fitz.open` calls open empty/in-memory/own-snapshot docs
  or reopen our own saved output). The caps now also apply to merge sources —
  intended hardening.
- **Layer-boundary AST guards (R2.1/R2.2).** Correctly enforce
  `model/` → no Qt / no view / no controller imports, and `view/` → no
  unsanctioned `fitz.open` (single allowlisted preview-scratch open in
  `view/text_editing.py`). (Completeness gap: see R2-01.)
- **Test integrity.** Changed tests were strengthened or MVC-adapted, not
  weakened: `test_thumbnail_context_menu` swaps the removed-fallback `fitz.open`
  monkeypatch for a controller `resolve_insert_source_file` mock;
  `test_interaction_modes` adds the `has_unsaved_changes` stub the R2.5 facade
  requires; `test_xref_repair` generalizes the encryption guard across all of
  `model/` and three live-doc receivers and adds a "explicit `PDF_ENCRYPT_NONE`
  is also an offender" strengthening. The `open_merge_source` error-string shift
  (now suffixed `: {path}`) is safe — no test pins the old exact string.

### Verification evidence

- `pytest` — 112 passed across the affected modules
  (`test_pdf_merge_workflow`, `test_insert_pages_password`,
  `test_security_pdf_resource_guards`, `test_xref_repair`,
  `test_text_editing_gui_regressions`, `test_thumbnail_context_menu`,
  `test_interaction_modes`) + 2 passed for the new `test_layer_boundaries`.
- `ruff check` — clean on all six touched production files.
- Foreign-open audit — every `fitz.open`/`fitz.Document` site in
  `model/pdf_model.py` inspected; only the two intended merge sites changed, both
  now routed through `_guard_foreign_doc`.

---

## R3 — God-Module Decomposition

**Range:** `89770be^..a7e7734` — 15 commits, R3.1 through R3.8a
(`89770be` text-block parsing extraction → `a7e7734` interaction-state
migration). The range also contains the Windows Fusion launcher fix and the two
documented completion-gate pin refreshes.

**Reviewed:** 2026-06-20–21
**Production files touched:** `model/text_block.py`,
`model/text_block_parsing.py`, `model/pdf_model.py`,
`model/pdf_object_ops.py`, `model/pdf_text_edit.py`,
`controller/pdf_controller.py`, `controller/search_coordinator.py`,
`controller/ocr_coordinator.py`, `controller/print_coordinator.py`,
`view/pdf_view.py`, `view/object_selection.py`, and
`view/text_selection.py` (plus `scripts/fusion.py` and the hash-only
`scripts/completion_gate.py` edit).

**Verdict:** Behavior-preserving in production. No correctness, security,
performance/resource, or architecture defect survived verification. One
reportable **Low** test/regression gap survived the code-review plugin's
changed-line-only, confidence-≥80 filter: **R3-01**, covering the newly
introduced OCR activation-to-coordinator bridge handoff (confidence 97).

> **Fusion CLI cross-check (degraded but completed).** The initial forced
> standard-panel run over the 468 KB Python diff failed closed because the
> request exceeded provider/Windows process-argument limits. A compact,
> source-backed adversarial verification run then completed with both independent
> Antigravity candidates plus the separate Codex judge and synthesizer; both
> Claude candidates failed at the provider boundary, so the run is explicitly
> degraded rather than a full four-candidate panel. The candidates proposed two
> extraction-shaped concerns (lazy manager creation and coordinator state
> ownership); the judge rejected both because they contradicted the actual
> forwarder bodies and the verified read/write mapping. Final Fusion synthesis
> found **no introduced production bug ≥80 confidence**. A subsequent
> five-hunter, two-reproducer pass retained **R3-01** as a Low test-coverage
> finding—not a production defect—because a no-op `connect_bridge()` mutation
> left the focused suites and exact-commit full suite green. Artifact:
> `.fusion-runs/fusion-20260620-220445-0e5766/report.md`.

> **Layered multi-agent cross-check.** Five specialized hunters ran the requested
> lenses: correctness, security, performance/resource, architecture/topology,
> and test/regression. Only the test hunter produced a candidate. Two fresh
> independent reproducers confirmed the test blind spot while refuting a present
> production bug; a separate nit/noise filter kept it at Low severity (97
> confidence), and an independent synthesizer/ranker deduplicated and formatted
> the finding below.

### Findings

#### R3-01 — Low — New OCR activation-to-coordinator handoff has no regression coverage
**Status:** Open · **Source:** Test & Regression Hunter → Independent Reproducer ×2;
Nit-Filter KEEP (confidence 97)
**Where:** `controller/pdf_controller.py:222` →
`controller/ocr_coordinator.py:141-149`; bypassed by
`test_scripts/test_ocr_controller_flow.py:295-314` (all at `a7e7734`)

R3.2 replaced the inline OCR bridge setup in `PDFController.activate()` with a
new delegation to `OcrCoordinator.connect_bridge()`, but the OCR flow tests never
exercise that handoff. Their helper constructs `PDFController` via `__new__`,
creates `_OcrBridge` itself, and manually connects four coordinator handlers.
Consequently, deleting the new `activate()` call—or making `connect_bridge()` a
no-op or miswiring it—can leave the application without OCR progress, status,
page-result, failure, and completion delivery while the existing tests remain
green. Page results would never reach `_on_ocr_page_done()` and therefore would
not be applied to the document.

Mutation evidence confirms the blind spot: replacing
`OcrCoordinator.connect_bridge()` with a no-op left two focused verifier runs
green (**16/16** and **28/28**) and an isolated exact-`a7e7734` full suite green
(**1384 passed, 27 skipped**). Production wiring is correct today; this is a
test-gap finding only. The older pre-R3 tests also manually wired the bridge, so
the broad activation blind spot is pre-existing—the R3-chargeable gap is the new
`activate()` → coordinator handoff, which received no red-light or
changed-behavior test despite `CLAUDE.md` §§5.1–5.2 and its Definition of Done.

**Fix:** Add an activation contract test using a real `OcrCoordinator` while
stubbing unrelated coordinators. Call `PDFController.activate()`, assert the
bridge is created, emit the five bridge signals (`progress`, `status`,
`page_done`, `failed`, `thread_finished`), and assert their observable handler
and state side effects. Call `activate()` again to verify idempotency/no duplicate
delivery. The test must fail when `connect_bridge()` is replaced with a no-op;
retain the existing focused OCR-flow tests for worker behavior.

### Rejected candidates / context notes (not findings against R3)

- **`PDFView.__new__()` doubles remain supported.** All 43 state properties call
  `_ensure_object_selection_manager()` or `_ensure_text_selection_manager()` in
  both getter and setter; normal construction also creates both managers eagerly.
  The Fusion candidates' claimed direct-manager `AttributeError` path does not
  exist in the source.
- **Coordinator state is not split between facade and coordinator.** A
  normalized AST comparison of every moved search/OCR/print method found no body
  drift after accounting for the intentional `self._c` controller reads and the
  two facade renames. Repository-wide reference search found no stale production
  read of the relocated runtime attributes on `PDFController`.
- **Private-helper dispatch changes do not establish a regression.** The
  edit-text seam preserves the existing instance dispatch points used for
  monkeypatch/failure injection (`model._resolve_edit_target`,
  `model._apply_redact_insert`, and `model._push_down_overlapping_text`). The
  object-ops and text-block parsing clusters directly call their new private pure
  functions, but no repository subclass, monkeypatch, or externalized contract
  relies on overriding those private helper-to-helper calls.
- **R3.4 `pending_edits` asymmetry is pre-existing and optimization-only.** It
  was moved verbatim, then independently traced and closed in `4f075ed`:
  `pending_edits` only triggers optional `clean_contents()` compaction, so the
  affected saves remain byte-correct and pixel-identical (potentially larger).
- **R3.7 text-selection cleanup was already crash-safe.** Calling `item.scene()`
  on a wrapper deleted by `scene.clear()` can raise `RuntimeError`, but the moved
  code catches it and then clears the reference/list. `97406ce` later replaced
  that exception-as-control-flow path with `shiboken6.isValid()` and tests; it is
  a hardening/clarity follow-up, not evidence of a crash introduced by this range.
- **R3.8b remains intentionally deferred.** The range stops at state migration;
  it does not contain the event-dispatch rewrite whose Qt accept/fallthrough and
  auto-pan behavior require dedicated interaction tests or manual QA.

### Verified clean (high confidence)

- **R3.1 parsing seam.** All 14 manager parsing methods retain their facade and
  the extracted pure functions preserve the original bodies and Unicode
  constants; dataclasses and `rotation_degrees_from_dir` remain re-exported.
- **R3.2 coordinators.** Worker/bridge/request compatibility re-exports remain;
  bridge creation stays in `activate()` via `connect_bridge()`; generation,
  session, thread-finished release, print stall/terminate, and app-close paths
  retain their original ordering.
- **R3.4/R3.5 model seams.** Public `PDFModel` entry points remain one-line
  facades, model-owned snapshot/undo/index state is still reached through the
  model object, and the extraction does not move Qt into `model/` or hide a new
  live-document serialization from the encryption guard.
- **R3.6–R3.8a view seams.** All moved method names remain available on
  `PDFView`; all 34 previously initialized state defaults match exactly; the nine
  newly centralized first-set object fields use their existing reset defaults;
  and every one of the 43 property getter/setter pairs targets the identically
  named manager attribute.

### Verification evidence

- Fresh targeted pytest on 2026-06-20: **143 passed, 1 skipped** across all eight
  extraction contracts plus search/OCR/print runtime flow, text-block and
  text-edit behavior, text selection/bounds, interaction modes, browse selection,
  and object manipulation/free-rotation GUI suites.
- Fresh mutation reproduction on 2026-06-21: replacing
  `OcrCoordinator.connect_bridge()` in memory with a no-op still yielded
  **16 passed** across `test_ocr_controller_flow.py` and
  `test_ocr_coordinator_extraction.py`, independently confirming R3-01.
- Fresh Ruff check: **all checks passed** for the 12 touched production modules
  and `scripts/fusion.py`. A full-file check of `scripts/completion_gate.py`
  reports ten pre-existing `E702` script-layer violations; this range changes
  only two pinned hash literals there, so they are not chargeable to R3.
- Structural audit: normalized AST body comparison for every coordinator and
  extraction seam; repository-wide stale-attribute/import search; one-to-one
  manager default and property-target validation.
- Multi-agent audit: five specialized hunters, two fresh independent
  reproducers, one nit/noise filter, and one independent synthesizer/ranker. Four
  hunter lenses returned no candidates; the sole test/regression candidate was
  reproduced twice and retained as R3-01.
- Historical exact-commit evidence from `0619-export-transcript/commit-contexts.md`:
  `a7e7734` completed with **1391 passed** and the no-jump pixel-parity gate bound
  to that commit.

---

## R4 — Performance (output-identical optimizations)

**Range:** `2a8cf8c^..8cabd01` — 5 commits, R4.5, R4.4, R4.2, R4.3, and
the R4.1 deferral/closure documentation.

**Reviewed:** 2026-06-21

**Production files touched:** `controller/ocr_coordinator.py`,
`controller/pdf_controller.py`, `controller/print_coordinator.py`,
`controller/search_coordinator.py`, `controller/thumbnail_coordinator.py`,
`model/edit_commands.py`, and `model/pdf_optimizer.py`.

**Verdict:** Four introduced defects survived independent reproduction and the
code-review plugin's changed-line, practical-trigger, and confidence filters:
three Major and one Minor. All four remain open at current HEAD; none of the
relevant production files changed after R4.

> **Fusion CLI cross-check (degraded but completed).** The first forced standard
> panel failed closed because the 139 KB full-diff request exceeded provider /
> Windows process-argument limits; artifact:
> `.fusion-runs/fusion-20260621-105924-43c099/report.md`. A compact, production-only
> retry completed with two independent Antigravity candidates plus the separate
> Codex judge and synthesizer. Both Claude provider calls failed, so the result is
> explicitly degraded. Fusion confirmed the cross-session thumbnail defect and
> identified the undo-accounting concern; the latter was subsequently rejected by
> a real-PDF reproducer. Artifact:
> `.fusion-runs/fusion-20260621-110622-49bf48/report.md`.

> **Layered multi-agent cross-check.** Correctness, security, performance/resource,
> architecture/topology, and test/regression lenses reviewed the range. Fresh
> reproducers then exercised real QThreads, real PyMuPDF documents, close-session
> flow, and resource behavior. A separate nit/noise filter removed speculative Qt
> lifetime claims; final synthesis retained only the four findings below.

### Findings

#### R4-01 — Major — A cancelled tab's thumbnails can paint into the new tab
**Status:** Open | **Source:** Correctness + Performance Hunters; Independent
Reproducer CONFIRMED (confidence 95)
**Where:** `controller/thumbnail_coordinator.py:56`, `:143-148`, `:185-208`,
`:227-237`; `controller/pdf_controller.py:327-335` (all at `8cabd01`)

`_ThumbnailWorker.batch_ready` carries only `(gen, start_index, images)`, while
thumbnail generations are counters scoped independently to each session. When a
new job starts, `ThumbnailCoordinator.try_start()` overwrites the coordinator's
single mutable `_session_id`. A batch already queued by the old worker is therefore
interpreted using the new session id. Fresh sessions commonly both have `gen == 1`,
so the old batch passes both guards and is painted into the active tab.

The independent real-QThread reproduction queued three red batches for session A,
started blue session B with the same generation, then pumped the GUI event loop.
All three red A batches were accepted after B became active, followed by B's blue
batches. This can transiently show another document's pages in the active sidebar,
and the wrong images can persist if the replacement job fails or is cancelled.

**Fix:** Carry an immutable `session_id` or globally unique job token through every
worker/bridge signal and validate the emitted token directly. Add a regression test
that delivers a queued A payload after B starts with the same numeric generation.

#### R4-02 — Major — The async thumbnail path serializes the whole PDF on the GUI thread
**Status:** Open | **Source:** Security + Performance Hunters; Independent
Reproducer CONFIRMED (confidence 96)
**Where:** `controller/thumbnail_coordinator.py:157-188`;
`controller/pdf_controller.py:592-615` (all at `8cabd01`)

Async eligibility considers only bridge state, active session, page count (at least
24), and watermarks. On a cache miss, `try_start()` calls
`capture_worker_snapshot_bytes()` before constructing and starting the QThread.
That call performs a full `doc.tobytes()` and caches the resulting document-sized
buffer synchronously on the Qt GUI thread. Opening a large scan-heavy or
embedded-content PDF therefore blocks the interface and creates a large transient
copy before any work is offloaded.

The verifier measured the exact 24-page path: a 64 MiB PDF took 0.147 s with a
128 MiB traced peak, while a 128 MiB PDF took 0.273 s with a 256 MiB traced peak.
The repository accepts inputs up to 512 MiB, so the automatic path can cause a
multi-second stall or memory exhaustion on otherwise accepted documents. Before
R4.3, initial thumbnails were bounded page batches; full serialization followed an
explicit search/OCR/print action rather than ordinary document opening.

**Fix:** Do not automatically serialize an uncached full document on the GUI thread.
Use a safe file-backed source for clean sessions or a bounded snapshot strategy;
otherwise gate the async path by snapshot availability and document size and fall
back to the existing bounded synchronous batches.

#### R4-03 — Major — Closing a session retains its full decrypted snapshot
**Status:** Open | **Source:** Security + Performance Hunters; Independent
Reproducer CONFIRMED (confidence 100)
**Where:** `controller/pdf_controller.py:592-620`, `:1313-1341`;
`model/pdf_model.py:2377-2381` (all at `8cabd01`)

The R4.2 cache stores `(session_id, render_revision, bytes)`, but the session-close
path removes the other per-session state without invalidating the matching cache or
cancelling the thumbnail worker. Closing the last tab, or switching to a document
that never requests worker bytes, leaves the entire old PDF allocation reachable
for the controller's lifetime.

This is also a security-lifetime issue for password-protected input:
`capture_worker_snapshot_bytes()` deliberately serializes with
`PDF_ENCRYPT_NONE`. The verifier opened an encrypted PDF, confirmed the source
needed authentication, closed the session, and then reopened the still-cached bytes
without a password and extracted the secret text. R5.1 later re-encrypts print
temporary files on disk, but it does not clear this in-memory cache.

**Fix:** On close, switch, and shutdown, cancel the thumbnail job and clear the cache
when its stored session id matches the departing session. Immutable Python bytes
cannot be guaranteed zeroized, but prompt reference release bounds both memory and
plaintext lifetime.

#### R4-04 — Minor — Sync fallback leaves the superseded thumbnail worker running
**Status:** Open | **Source:** Performance Hunter; Independent Reproducer
CONFIRMED (confidence 99)
**Where:** `controller/thumbnail_coordinator.py:176-185` (at `8cabd01`)

`try_start()` checks `_should_async()` before calling `cancel()`. If a large async
job is followed by a small range, a watermarked document, or another ineligible
session, the method returns `False` and the caller renders synchronously while the
old worker continues rasterizing stale pages. Generation/session checks usually
discard its output, but they do not stop its CPU use or release its snapshot and
image resources.

The exact coordinator reproduction started a large job, submitted a one-page
replacement, and observed `try_start() == False` while the old worker remained
uncancelled and completed all simulated work intervals.

**Fix:** Cancel superseded work before evaluating whether the replacement will use
the async or synchronous path, and cancel explicitly on tab close/switch and app
shutdown.

### Rejected candidates / context notes (not findings against R4)

- **Content-keyed undo accounting is theoretically wrong for equal-but-distinct
  buffers, but the trigger is not produced by the application.** A synthetic
  `set[bytes]` probe undercounts separate equal allocations, and the committed R4.4
  tests manufacture that state with `bytes(bytearray(...))`. The fresh production
  reproducer found that every full-document and page snapshot save changes the PDF
  trailer id: unchanged captures, capture-after-restore, and a reversible
  +90/-90-degree rotation all produced unequal byte strings. Worker snapshots use
  `no_new_id=1`, but they never enter `CommandManager`. With no production path to
  equal-but-distinct command snapshots, the plugin confidence score is 25, below
  the required 80 threshold.
- **`cancel()` does not destroy a running QThread wrapper.** Although it clears the
  coordinator fields early, the `thread.finished` lambda's default argument holds a
  strong reference to the wrapper. A weak-reference/GC reproduction kept it alive
  through completion and collected it safely afterward (confidence 5 for the
  proposed crash).
- **R4.2's OCR cache invalidation is correct.** Render-visible mutations invalidate
  through `_bump_render_revision`, while invisible OCR text explicitly clears the
  cache after each applied page. No stale searchable snapshot survived this trace.
- **R4.5's object-stream preset change is correctly normalized.** `快速` reaches
  `use_objstms=1`; `極致壓縮` remains protected by its linearization normalization.
- **R4.1 was deliberately deferred.** The range contains documentation only for the
  rejected overlay-cache design, so no deferred implementation is charged as a bug.

### Verified clean (high confidence)

- Worker rendering uses a private `fitz.Document` opened from immutable bytes,
  closes it in `finally`, converts to detached `QImage` objects off-thread, and
  creates `QPixmap` objects only on the GUI thread.
- Watermarked sessions correctly stay on the synchronous overlay-aware renderer;
  annotations remain present through `annots=True` in the snapshot document.
- The worker snapshot cache is single-entry and correctly keyed for reuse across
  search, OCR, print, and thumbnails; the defect is its preparation/lifecycle, not
  stale reuse across a different session.
- No hardcoded credentials, new dependencies, shell/eval/pickle surface, circular
  import, or MVC layer inversion was introduced by the range.

### Verification evidence

- Fresh focused suite: **78 passed, 4 skipped** across thumbnail coordination,
  worker-snapshot caching, undo budgeting, optimize workflow, OCR flow, and search
  worker flow.
- Real-QThread cross-session reproduction: three queued A batches were painted after
  B became active with the same generation, confirming R4-01 despite the green suite.
- Resource probes measured GUI-thread serialization/peak allocation, uncancelled
  fallback work, cache survival after close, and password-free reopening of cached
  encrypted input.
- `git diff --check 2a8cf8c^..8cabd01` completed cleanly.
- Multi-agent audit: five hunter lenses, two fresh independent reproducers, one
  independent nit/noise filter, and final deduplication/severity ranking.

## R5 — Security (encryption / packaging)

**Range:** `5165b0f^..15b50d6` — 6 commits covering optimize-copy encryption,
encrypted printing, the packaging guard, R5 closure documentation, and the
post-R5 codegraph re-index.

**Reviewed:** 2026-06-21

**Production files touched:** `controller/print_coordinator.py`,
`model/pdf_optimizer.py`, `src/printing/helper_main.py`, and
`src/printing/subprocess_runner.py`.

**Verdict:** Six introduced defects survived independent reproduction and the
code-review plugin's changed-line, practical-trigger, and confidence filters:
four Major and two Minor. No candidate met the Critical threshold.

> **Fusion CLI cross-check (failed closed; not treated as consensus).** The first
> forced standard panel exceeded Windows/provider argument limits and produced no
> usable candidate (`.fusion-runs/fusion-20260621-144251-f1628b/report.md`). A
> compact changed-lines retry produced two Antigravity candidates, while both
> Claude calls failed; the separate Codex judge then timed out, so no synthesis
> was emitted (`.fusion-runs/fusion-20260621-145107-4ef8d2/report.md`). The raw
> candidates contained several false positives (missing imports, unsupported
> `BytesIO`, and encrypted helper output) that direct execution disproved. Their
> one valid access-control concern was reproduced independently below.

> **Layered multi-agent cross-check.** Correctness, security,
> performance/resource, architecture/topology, test/regression, history, and
> code-comment lenses reviewed the range. Two fresh reproducers then exercised
> real PyMuPDF documents, PDFModel session switching, failure injection, the real
> helper-to-dispatcher handoff, and Qt parent ownership. A separate nit/noise
> filter rejected the environment-inheritance item and folded the resource concern
> into its shared print-path root cause.

### Findings

#### R5-01 — Major — Encrypted printing still writes a decrypted PDF to disk
**Status:** Open | **Source:** Test/Regression + Security + Performance Hunters;
Independent Reproducer CONFIRMED (confidence 100)
**Where:** `src/printing/helper_main.py:33-46`, `:94-100`;
`src/printing/dispatcher.py:106-117` (at `15b50d6`)

R5.1 encrypts `work_dir/input.pdf`, but the helper immediately authenticates that
file and serializes decrypted bytes. `PrintDispatcher.print_pdf_bytes()` then
writes those bytes to a second `NamedTemporaryFile(delete=False)` for the entire
driver/spool call. The fix therefore relocates the plaintext-at-rest exposure from
the job work directory to the system temp directory instead of eliminating it; a
hard process kill or the already-tolerated unlink failure can strand the file.

The real helper/dispatcher reproduction inspected the actual driver path while it
was live: the encrypted source had `needs_pass=1`, while the dispatcher temp
existed with `needs_pass=0`, no encryption metadata, and readable `TOP SECRET`
text. It was deleted only after the fake driver returned. The six new R5.1 tests
stop after asserting that helper output is decrypted and use fake dispatchers, so
they never inspect this real sink.

The same design also adds material resource amplification for encrypted,
no-watermark jobs. A 32 MiB incompressible PDF added about 64 MiB peak RSS in the
worker re-encryption pass and about 96 MiB in the helper decrypt/resave pass, on
top of the controller's retained full snapshot. This is an OOM risk near the
project's several-hundred-MiB input ceiling.

**Fix:** Keep protected jobs encrypted through dispatch and make the
renderer/driver boundary password-aware, or use a genuinely fileless/page-streamed
raster path. Avoid the duplicate full-document `BytesIO`/`read_bytes` copies. Add
an end-to-end test that inspects every intermediate path during an encrypted print
and a large encrypted/no-watermark resource-budget test.

#### R5-02 — Major — Optimize-copy promotes a restricted user password to owner access
**Status:** Open | **Source:** Correctness + Security + Test/History Hunters;
Independent Reproducer CONFIRMED (confidence 100)
**Where:** `model/pdf_optimizer.py:834-855`;
`test_scripts/test_pdf_optimize_workflow.py:73-83`, `:223-251` (at `15b50d6`)

`reapply_source_encryption()` writes the one session credential as both
`owner_pw` and `user_pw`. For a source opened with a restricted user password,
that same credential therefore authenticates as owner in the optimized copy and
the supplied permission mask becomes ineffective. The committed test fixture
already uses distinct owner/user passwords and restricted permissions, but it
asserts only that the output rejects a wrong password and accepts the original
one.

The real pipeline reproduced `authenticate(user-secret) == 2` and
`permissions == -3900` on the source, versus `authenticate(user-secret) == 6`
and `permissions == -4` on the output; copy/modify restrictions were lost. The
original owner password also stopped working. A second reproduction used an
owner-only/blank-user encrypted source: because the helper gates on `needs_pass`,
it skipped re-encryption and changed AES-256 metadata with restricted permissions
to `encryption=None` and unrestricted output.

**Fix:** Preserve the authentication role and never reuse a user credential as
the owner credential. A user-authenticated source can use an unguessable owner
secret while retaining the session credential as `user_pw`; other roles need an
explicit product decision because one captured password cannot reconstruct both
original credentials. Detect encrypted-but-blank-user sources from encryption
metadata, and test authentication class plus effective permissions—not merely the
password barrier.

#### R5-03 — Major — Active-session changes can encrypt document A with document B's state
**Status:** Open | **Source:** Correctness/Security Hunter; Independent Reproducer
CONFIRMED (confidence 97)
**Where:** `model/pdf_optimizer.py:834-845`, `:862-897`;
`controller/pdf_controller.py:115-135`, `:976-988`, `:1177-1205` (at `15b50d6`)

`save_optimized_copy()` captures `active_sid` when it starts, but the new final
`reapply_source_encryption(model, new_path)` reads mutable `model.doc`,
`model.password`, metadata, and permissions after the long background optimize
has completed. If the active session changes in that interval, encryption is
decided from the wrong tab.

The modal progress dialog blocks ordinary tab clicks, but it does not make the
model immutable: the single-instance server can accept a second invocation and
schedule `open_pdf` through `QTimer` while the optimizer QThread is running. In a
controlled reproduction, switching from encrypted A to plain B before the reapply
step left A's output unencrypted. Switching to encrypted B kept A's content but
made A's password fail and B's password authenticate as owner.

**Fix:** Bind the optimize request to its source session and capture an immutable
encryption descriptor (session id, password, method, permissions, and auth level)
before dispatch. Every worker-stage read must resolve that explicit source rather
than active-session properties; define safe behavior if that session closes.

#### R5-04 — Major — Re-encryption failure leaves the requested output plaintext
**Status:** Open | **Source:** Correctness + Performance/Resource Hunters;
Independent Reproducer CONFIRMED (confidence 100)
**Where:** `model/pdf_optimizer.py:846-859`, `:892-930` (at `15b50d6`)

The pipeline first moves the complete plaintext optimized file to `new_path`, then
creates an encrypted sibling and replaces the destination. If the encrypted save
or `os.replace()` fails because of disk pressure, permissions, antivirus locking,
or I/O failure, the outer cleanup checks only `temp_save`, which has already been
moved. The user sees `PdfOptimizeError`, but the protected document remains at the
requested path without a password; the `_enc_` sibling can also remain.

Fault injection on only the final `os.replace` reproduced a plaintext final file
with readable optimized content plus one orphan encrypted sibling. The design also
requires roughly twice the output disk space and a second full-file write for every
encrypted optimize, making the failure more likely on large documents.

**Fix:** Never publish the plaintext intermediate. Build and validate the encrypted
artifact in a destination-directory staging file, atomically install it only after
success, and clean every plaintext/encrypted staging path in `finally`. Add failure
tests for both encrypted save and final replace.

#### R5-05 — Minor — Completed print runners retain passwords until the view is destroyed
**Status:** Open | **Source:** Security + Performance/Resource Hunters; Independent
Reproducer CONFIRMED (confidence 100)
**Where:** `src/printing/subprocess_runner.py:43-52`, `:231-237`;
`controller/print_coordinator.py:303-310`, `:375-384` (at `15b50d6`)

Each runner stores `_helper_password` and is constructed with the long-lived view
as its QObject parent. Completion drops the coordinator's references, but
`_cleanup()` neither clears the password nor schedules the runner for deletion, so
Qt parent ownership keeps one runner, its child timer, and its credential alive per
encrypted print.

After three synthetic completed jobs, deleting every Python local and processing
GC/events still left all three runners under `view.children()` with
`['secret-0', 'secret-1', 'secret-2']` readable.

**Fix:** Clear `_helper_password` as soon as QProcess has copied its environment
and again in terminal cleanup, then `deleteLater()` the completed runner. A repeated
encrypted-print regression test should keep the view child count flat and make old
secrets unreachable. Consuming the helper variable with `os.environ.pop` is useful
defense-in-depth but not a separate finding.

#### R5-06 — Minor — The packaging guard accepts a find-all discovery pattern
**Status:** Open | **Source:** Test/Regression + History Hunter; Independent Noise
Filter CONFIRMED (confidence 100)
**Where:** `test_scripts/test_security_packaging.py:65-74`, `:93-121` (at `15b50d6`)

The hermetic fallback strips trailing `*` characters and checks only the remaining
prefix. A discovery list such as `['controller*', 'model*', '*']` therefore passes
because the find-all pattern becomes an empty string, even though setuptools
discovers `scripts` and `scripts.fusion_schemas`. If the live wheel build returns
any nonzero code, the test skips it, so a packaging regression can make its own
security check disappear. The R5 plan also required inspecting both wheel and
sdist, while the implementation builds only a wheel and checks two manifest lines
for the sdist.

The current allow-list is safe; this finding is about the new guard's false-negative
contract, not a claim that the current artifact already contains the dev tree.

**Fix:** Evaluate setuptools discovery semantics against concrete forbidden
package names, fail build errors in the authoritative CI environment, and build
and inspect both wheel and sdist member lists.

### Rejected candidates / context notes (not findings against R5)

- **Helper environment inheritance is real but not a separate vulnerability.** A
  downstream `lp` child inherits `PDF_EDITOR_PRINT_PASSWORD`, but it is a trusted
  absolute system executable in the same helper trust boundary. Pop/sanitize the
  variable as part of R5-05 hardening; no independent exfiltration path survived
  the 80-confidence practical-impact filter.
- **Fusion raw-candidate false positives were removed.** `model/pdf_optimizer.py`
  already imports `os`, `uuid`, and `Path`; PyMuPDF 1.27 accepts the exercised
  `BytesIO` save; and the helper's authenticated serialization is demonstrably
  decrypted. These claims did not survive direct execution.
- **R5.2 remains the documented out-of-band packaging block.** The review does not
  re-propose populating an empty weights manifest without a vetted bundle.
- **The docs-only wishlist/closure commits and codegraph re-index introduced no
  separate runtime defect.** No hardcoded credential, new third-party dependency,
  command injection, circular dependency, or new MVC import cycle was found.

### Verified clean (high confidence)

- For a password-gated source, `work_dir/input.pdf` itself is AES-256 encrypted,
  rejects a wrong password, and the password is absent from `job.json`.
- The helper rejects missing/invalid passwords, and the unencrypted/no-watermark
  path remains byte-identical.
- With a stable active session and successful I/O, the optimized copy retains a
  password barrier; the defects are credential semantics, session binding, and
  failure atomicity.
- The current wheel discovery allow-list excludes `scripts`/`test_scripts`; R5-06
  concerns the guard's ability to catch a future broad-pattern regression.

### Verification evidence

- Fresh focused suite: **45 passed, 4 skipped** across optimize workflow,
  encrypted print, and packaging-security tests.
- Real-PDF reproductions: helper-to-dispatcher plaintext-path inspection;
  restricted-user and owner-only encryption semantics; cross-session reapply; and
  injected encrypted-save/replace failures.
- Qt lifetime reproduction: three cleaned runner objects and all three passwords
  remained owned by the long-lived view after local references and GC were gone.
- Setuptools discovery reproduction: adding `'*'` changed `contains_scripts` from
  false to true while the static guard logic still accepted the pattern.
- `git diff --check 5165b0f^..15b50d6` completed cleanly.
- Multi-agent audit: five hunter lenses, two fresh independent reproducers, one
  independent nit/noise filter, and final deduplication/severity ranking.

---

## R6 — Coverage Hardening + deferred-finding closures

**Range:** `42aa51b^..97406ce` — 6 commits covering R6 characterization
tests, no-jump ignore retirement, the coverage floor, and the post-campaign
R3.4/R3.7 finishing work.

**Reviewed:** 2026-06-21

**Runtime/configuration files touched:** `pyproject.toml`,
`scripts/completion_gate.py`, `scripts/verify_no_jump.py`, and
`view/text_selection.py`. The range also adds five test files and changes the
R3 plan/state/TODO documents.

**Verdict:** Three changed-line issues survived independent reproduction and
the code-review plugin's practical-trigger/confidence filter: one Major and two
Minor. No candidate met the Critical threshold. The production
`shiboken6.isValid` hardening itself is correct; the Major finding is that the
companion finishing commit incorrectly closed a practical pre-existing defect.

> **Fusion CLI cross-check (failed closed; not treated as evidence).** A forced
> standard panel exceeded the outer execution window before producing a usable
> report and was terminated with its process tree. A compact lean retry failed
> in the Codex router before any candidates were created
> (`.fusion-runs/fusion-20260621-154442-2e6fd9/report.md`). No Fusion claim was
> used to confirm or reject a finding.

> **Layered multi-agent cross-check.** Three parallel read-only hunter passes
> covered correctness/architecture, security/resources, and test/history/second
> opinion. Candidate findings were then cross-assigned to agents that had not
> originated them. The final nit filter retained only practical changed-line
> issues scoring at least 80 confidence.

### Findings

#### R6-01 — Major — R3.4 was closed as a slight size issue, but object rewrites bypass full GC and retain deleted data
**Status:** Open | **Source:** Security/Resource Hunter; independent
Correctness Reproducer CONFIRMED (confidence 99)
**Where:** `plans/refactor-R3-god-module-decomposition.md:209-224`,
`refactor-state.md:690-704`, and `TODOS.md:31` (at `97406ce`)

Commit `4f075ed` changes the deferred R3.4 finding to “NOT a correctness bug”
and closes it on the premise that `pending_edits` only drives
`clean_contents()`, so the omission merely makes saves “slightly larger.” The
trace stops one step too early. Textbox move/rotate/delete rewrites page content
through redact-and-reinsert without registering the page, incrementing
`edit_count`, or invoking `_maybe_garbage_collect()`
(`model/pdf_object_ops.py:653-676`, `:759-786`, `:801-816`). That collector is
the path that performs the material `garbage=4` live-document round-trip every
20 edits (`model/pdf_model.py:2798-2821`); its sole caller is the text-edit path.

The independent real-API reproduction saved and reopened an app textbox, then
used ordinary public move/rotate requests. Twenty move+rotate pairs grew the
document from about 73 KB to 3.32 MB / 2,341 xrefs; 40 pairs reached 7.22 MB /
7,861 xrefs; 100 moves reached 9.27 MB versus a 76 KB garbage-collected
equivalent. `edit_count` and `pending_edits` stayed zero. Manually adding the
page to `pending_edits` and running `clean_contents()` did not reclaim the
orphan xrefs, while the existing `garbage=4` collector reduced the 3.32 MB case
to about 57 KB. Pixel hashes remained equal, so the defect is resource/file
amplification rather than visual corruption; controller before/after snapshots
amplify the same growth in memory and undo-budget pressure.

Deletion also has a confidentiality consequence. After adding a uniquely
identified textbox, deleting it, and saving to a different path (the
non-incremental full-save path), visible text extraction was empty but the
pre-delete form content stream, ToUnicode map, and embedded-font streams all
survived byte-for-byte as orphan xrefs. A low-level PDF scanner can recover the
deleted text; a `garbage=4` rewrite removed those streams. This directly
contradicts the changed claim that there is no data consequence. The runtime
omission predates R6, but the reviewed finishing commit newly removes the only
tracked finding and records a false resolution, so the changed-line issue is
the closure itself.

**Fix:** Reopen R3.4 in the plan/state/TODO. Funnel every content-rewriting
app-object mutation through shared post-mutation bookkeeping that registers the
page, advances the mutation/GC count, and actually invokes the bounded full-GC
policy; `pending_edits`/`clean_contents()` alone is insufficient. For destructive
deletes, use a non-incremental `garbage=4` sanitized-save path when secure removal
is promised, or explicitly document orphan-data recoverability. Add real-PDF
regressions for repeated textbox transforms (bounded xrefs/serialized bytes),
deleted-payload absence from all saved xref streams, render equivalence,
encryption retention, marker survival, and undo integrity.

#### R6-02 — Minor — The “session-routed” anchor test passes with a global anchor map
**Status:** Open | **Source:** Test/History Hunter; independent Security/Resource
Verifier CONFIRMED (confidence 98)
**Where:** `test_scripts/test_text_selection_bounds.py:81-89` (at `97406ce`)

The new test claims to exercise `run_reopen_anchors` “through session,” but its
fixture opens one document and only sets/gets the property in that same active
session. Replacing the property with a legacy-global dictionary made all five
new tests pass; the pre-existing multi-tab suite also remained green. A direct
two-document probe then showed document B immediately reading document A's
anchor key. Run/span IDs are deterministic per page structure, so collisions
can redirect reopen hit-testing and geometry across tabs if this routing ever
regresses.

**Fix:** Open two sessions, store distinct anchor maps in A and B, switch in
both directions, and assert isolation plus persistence. Also assert the legacy
store remains unused while an active session exists.

#### R6-03 — Minor — Cleanup tests never prove that live extra-line highlights leave the scene
**Status:** Open | **Source:** Test/History Hunter; independent Security/Resource
Verifier CONFIRMED (confidence 99)
**Where:** `test_scripts/test_text_selection_cleanup_guard.py:85-106` (at
`97406ce`)

The dangling-extra test clears the scene before invoking cleanup and checks only
that the Python list becomes empty. The sole live-item test covers the primary
selection rectangle, not `_text_selection_extra_rect_items`. Replacing
`_clear_text_selection_extra_rects()` with a one-line list reset therefore left
all four new tests—and 22 broader text-selection tests—green. A real Qt probe
kept two live z=20 rectangles attached to `view.scene` after that mutant dropped
their references. Repeated multiline selections would accumulate visible ghost
highlights and scene items. This misses the state/side-effect assertion required
by `CLAUDE.md` section 5.2 for the exact production branch changed in `97406ce`.

**Fix:** Populate live extra items, retain external references, invoke cleanup,
and assert each item is invalid or has `scene() is None`, is absent from
`scene.items()`, and the manager list is empty. Add a mixed live/dangling case.

### Rejected candidates / context notes (not findings against R6)

- **The line-bounds assertion is loose but not a suite-level hole.** An
  unsnapped-rough-rectangle mutant passed the five new R6 tests, but the older
  exact regression in `test_text_extraction_line_joining.py` failed it. The new
  assertion is redundant, not an independently actionable defect.
- **The 75% coverage floor is deliberately opt-in.** CI and the completion gate
  do not invoke `--cov`; this contradicts the older plan wording “set a CI
  floor,” but the changed implementation/state/TODO explicitly choose the local
  full-suite `.venv` as authority. Treating that disclosed policy as a hidden
  runtime regression would be noise. A focused `--cov` run does fail the global
  floor, but the documented canonical command is the full suite.
- **Direct bridge-slot tests intentionally cover forwarding, not transport.**
  Existing coordinator-flow tests cover the missing OCR terminal slots; no
  changed runtime wiring defect survived reproduction.
- **Merge aggregate-cap/leak concerns are pre-existing.** The aggregate page-cap
  item is already recorded as R2-13. The new compose tests do not create a new
  guard bypass, and `_guard_foreign_doc` already has independent size/page/auth
  coverage.
- **No Qt cleanup crash was found.** `shiboken6.isValid` correctly handles live,
  detached, and `scene.clear()`-invalidated production items on the GUI thread;
  no credible race, ownership leak, MVC inversion, or import cycle was added.

### Verified clean (high confidence)

- The R6 merge, print-watermark, bridge, selection-bounds, and cleanup files are
  green together; real PyMuPDF documents are closed on their normal test paths.
- Removing the three stale no-jump ignores widens the full-suite step without
  changing its subprocess/environment behavior. The refreshed hash exactly
  matches the target `verify_no_jump.py` bytes.
- The print-watermark test has real nested-mutation teeth, and merge file sources
  still route through `_guard_foreign_doc` with the source password.
- No hardcoded credential, dependency addition, command-injection surface,
  production MVC crossing, or circular dependency was introduced by the range.

### Verification evidence

- Fresh focused suite: **27 passed** across all five added R6/finishing test
  files.
- Re-enabled gate files: **72 passed, 9 skipped** across multi-tab, OCR E2E, and
  render-colorspace tests.
- Mutation reproductions: the global-anchor mutant passed **5/5** new bounds
  tests; the list-only cleanup mutant passed **4/4** new cleanup tests while two
  live items remained in the scene.
- Real-PDF reproductions: repeated app-textbox operations, forced collector
  comparison, full-save orphan-stream inspection, and render-hash comparison.
- `git diff --check 42aa51b^..97406ce` completed cleanly.
- Multi-agent audit: all six requested hunter lenses, two independent
  reproducer passes, one independent nit/noise filter, and final
  deduplication/severity ranking.
