# Phase R3 — God-Module Decomposition

**Status:** Ready (after R2 guard lands). **Fusion:** 3-model (Playbook 4.4 design + 4.1 pre-edit).
**Why:** `pdf_view` 5497 / `pdf_model` 5166 / `pdf_controller` 3383 / `text_editing` 1809 /
`text_block` 1043 LOC are genuine god-modules. This is the **highest-risk** phase — state
migration + signal rewiring. It is gated on R2's import guard + generalized encryption guard.
(Census: god-module lens.)

> **Implicit risks:** state migration is the dominant vector (ObjectSelectionManager must move ~25
> attrs); the mouse-handler dispatcher must preserve `current_mode` early-return ordering;
> coordinator extraction must preserve exact `QThread` signal wiring (a missed `connect` = a
> worker that runs but never reports back — silent hang). Encryption/snapshot-adjacent model seams
> must keep `save`/`tobytes` visible to the generalized AST guard.

## Pattern (proven in-repo)

Every extraction follows an existing precedent and **stays inside its own MVC layer behind a
stable facade**: free-function modules taking `model: PDFModel` (like `pdf_optimizer.py`
`def fn(model, ...)` with 1-line delegating wrappers at `pdf_model.py:3207-3340`); view managers
holding `self._view` and emitting via `self._view.sig_*` (like `TextEditManager`,
`text_editing.py:964`); PEP-562 lazy packages (`view/dialogs/__init__.py:17`). **No extraction
crosses a layer.** One cohesive seam per commit; full suite green before/after each.

## HARD internal ordering (non-negotiable — critique-enforced)

### R3.1 — `model/text_block_parsing.py` (FIRST — verified pure leaf) ✅ DONE 2026-06-16
> Landed: `text_block.py` 1043→338 LOC; new pure leaf `model/text_block_parsing.py` (helpers + 3
> dataclasses + 14 transforms), moved verbatim. `TextBlockManager` keeps all index state and delegates
> (signatures preserved); `text_block` re-exports dataclasses + `rotation_degrees_from_dir`. Red-Light via
> `test_text_block_parsing_extraction.py`. Suite 1366p/20s, AST guards green, ruff 0, codegraph re-indexed.

- `text_block.py:392-1043` (~652 LOC): `_parse_block/_parse_spans/_parse_runs_from_raw_*/
  _build_paragraphs/_merge_vertical_paragraphs/_expand_ligatures/...`. **10 `self.` refs total, 5
  `@staticmethod`**; none touch the instance indices (`_index/_span_index/_paragraph_index/
  _run_to_paragraph/_page_plain_lines/_page_state`, L152-169). Stateless transforms: fitz page
  dict → `TextBlock/EditableSpan/EditableParagraph` dataclasses (L99/117/134).
- **Extract** a free-function module owning **no** state. `TextBlockManager._build_page_index`
  (L244) keeps ownership of all indices and calls into it. Public API unchanged. Own red-light
  test (feed a fitz page dict, assert dataclass output) before the move. **Lowest blast radius of
  all five modules — do it first.**

### R3.2 — Controller async-job coordinators (search → OCR → print)
- The 8 worker/bridge QObjects are **already module-level** (`_PrintSubmissionWorker:121`,
  `_OcrWorker:216`, `_SearchWorker:308`, + bridges); only orchestration methods/state live on
  PDFController.
- **Extract** `controller/search_coordinator.py` (smallest, ~7 methods, already async-isolated by
  Phase4) → then `ocr_coordinator.py` → then `print_coordinator.py` (largest; subprocess runner +
  stall/terminate edges). Each holds `self._controller`, owns its `thread/worker/bridge/gen/
  dialog/session_id` state. Facade = `PDFController` keeps thin `search_text/start_ocr/
  print_document/start_optimize_pdf_copy` delegates. Bridges keep emitting to `QObject(view)`.
- **Coordinate with R5:** `print_coordinator` relocates the decrypted-snapshot handoff R5.1 fixes
  — share one regression pass (see refactor-state §3 hazard 5).

### R3.3 — Generalize the encryption AST guard to all of model/ (if not already done in R2.2)
- **Before** any model engine leaves `pdf_model.py`. Confirm the guard walks all of model/ and the
  decrypt-sink allowlist is in place. (Belt-and-suspenders with R2.2.)

### R3.4 — `model/pdf_object_ops.py` (object markers + native-image invocation + verbs)
- `pdf_model.py:2211-3065` (~850 LOC): markers, `_find/_rewrite/_remove_native_image_invocation`,
  `add_image_object/add_textbox/move_object/rotate_object/delete_object/resize_object`. self-refs
  dominated by `doc×50`, shares `pending_edits/edit_count` + snapshot machinery with edit_text.
- **Extract** a free-function module (`model: PDFModel` first arg); imports (does not move)
  `pdf_content_ops.py` stream parsing. PDFModel keeps the verbs as delegates. **HIGH risk** (undo-
  snapshot + encryption roundtrip). Sequence adjacent to R3.5; share a single regression pass.

### R3.5 — `model/pdf_text_edit.py` (edit_text/redaction engine — LAST model seam)
- `pdf_model.py:4012-4940` (~930 LOC) + push-down helpers `:3650-4011`: `_resolve_edit_target/
  _apply_redact_insert/_verify_rebuild_edit/_resolve_effective_target_mode/edit_text` +
  `_push_down_overlapping_text/_replay_protected_spans/...`.
- **Extract** a free-function module (`model: PDFModel`) reading `block_manager/doc/pending_edits/
  edit_count` + run-reopen-anchor helpers (which stay PDFModel methods the module calls). PDFModel
  keeps `edit_text()` as a 1-line delegate. **DO NOT split `_apply_redact_insert` (~360 LOC, L4191)
  across commits — move it whole.** Highest model risk; require full edit_text integration suite +
  no-jump gate green before/after.

### R3.6 — `view/object_selection.py` `ObjectSelectionManager(view)`
- `pdf_view.py:3828-4187` (~20 methods) + ~25 attrs (`_selected_object_info×46`,
  `_object_rotate_handle_item`, `_object_resize_handle_items`, `_object_drag_*`, `_object_rotate_*`,
  `_object_resize_*`). Emits `sig_delete/rotate/resize/move_object`. Template = `TextEditManager`.
- **Extract** the manager holding `self._view`; **migrate the ~25 attrs into it** (the main risk —
  any attr left on PDFView or double-owned causes selection desync). Signals **stay class attrs on
  PDFView** (a plain helper cannot own Qt Signals); the manager emits via `self._view.sig_*`.
- **Blocker:** `_mouse_press/move/release` read+write this state inline (45+ refs). Expose
  `handle_press/move/release(scene_pos, event)` the handlers call — do **not** inline-split the
  handlers yet.

### R3.7 — `view/text_selection.py` `TextSelectionManager(view)`
- `pdf_view.py:3477-3669` + ~17 attrs (`_text_selection_*`, `_selected_text_*`). Emits nothing
  (local selection; copy uses clipboard). Browse-mode-owned, so separable by the mode gate at
  `:2924`. Extract **after** R3.6 (lower coupling once objects are out).

### R3.8 — Mouse-handler dispatcher (LAST view artifact)
- Only after R3.6+R3.7: refactor `_mouse_press/move/release` (L2899-4558, ~830 LOC, the
  convergence of autopan + object-drag + text-selection + add-text) into a thin **per-mode
  dispatcher** that delegates to the two managers. **Preserve the `current_mode` early-return
  ordering exactly** (gate at L2924) — reordering changes which mode wins on overlapping hits.

### DO-NOT-TOUCH in R3
- The model **session/legacy-shadow accessor layer** (`pdf_model.py:267-668`) — every core
  property branches on `_active_session()` vs `_legacy_*`; it is the dependency root every other
  model seam reads through. Consolidating the `_legacy_*` shadow into a default `DocumentSession`
  is a **separate post-R3 phase** with its own migration.
- Internal splitting of `_apply_redact_insert`.

---

## Fusion Protocol Playbook

- **Per seam, BEFORE the move:** Playbook **4.1** (pre-edit review, 3-model) on the target file to
  surface invariants not to worsen.
- **For each extraction design:** Playbook **4.4** (3-model design) — fusion.py `--no-synthesize`
  for two competing facade sketches, `/codex:rescue` same prompt, synthesize per manual §3:
  ```powershell
  .venv\Scripts\python.exe scripts/fusion.py `
      "I am extracting <SEAM> into <new module> behind a stable facade, mirroring the
       pdf_optimizer free-function precedent (def fn(model: PDFModel, ...)). What state must stay
       owned by the original class, what must move, and what is the single safest commit boundary?
       Flag any encryption/snapshot/signal-wiring invariant I could break." `
      --file <TARGET_FILE> --no-synthesize
  # then /codex:rescue with the same prompt + file, then synthesize.
  ```
- **After each move:** Playbook **4.5** (3-model test-gap) to confirm no behavior/branch was lost.

## Verification & Gatekeeping

```powershell
# Per seam: targeted suite green, then full suite, then the boundary guards from R2:
.venv\Scripts\python.exe -m pytest test_scripts/test_edit_text_helpers.py test_scripts/test_char_run_reconstruction.py -v   # R3.1/R3.5
.venv\Scripts\python.exe -m pytest test_scripts/test_object_manipulation_gui.py test_scripts/test_native_pdf_images_model.py -v  # R3.4/R3.6
.venv\Scripts\python.exe -m pytest test_scripts/test_search_worker_flow.py test_scripts/test_ocr_controller_flow.py test_scripts/test_print_controller_flow.py -v  # R3.2
.venv\Scripts\python.exe scripts/verify_no_jump.py --skip-signoff                  # after R3.5
.venv\Scripts\python.exe -m pytest test_scripts/test_layer_boundaries.py test_scripts/test_xref_repair.py -v  # invariants intact
.venv\Scripts\python.exe -m pytest test_scripts/ -q --tb=line -p no:cacheprovider  # full green per seam
```

**Gate:** every seam is its own commit; full suite + both AST guards + no-jump gate green before
the next seam starts. A seam that cannot stay green is reverted, not patched forward.

## Risk Triage (2→3 upgrade points)

- **Entire phase is 3-model** — every seam trips triggers #1 (state migration), #4 (new facade),
  or #5 (entangled control flow). R3.5/R3.4 additionally trip #2 (security-invariant-adjacent).
- **Vectors:** attr left on/double-owned (selection desync); reordered mode early-returns; lost
  `connect` (silent worker hang); `save/tobytes` leaving the AST guard's view; `_apply_redact_insert`
  split across commits.

## Docs (per seam commit)

- `docs/ARCHITECTURE.md`: record each new module's responsibility + facade contract (§2.1/2.3/2.4).
- `docs/PITFALLS.md`: any state-migration or signal-wiring gotcha discovered.
- `plans/refactor-R3-*.md`: tick the seam; `refactor-state.md`: update R3 sub-status.
- `CODEINDEX.md` / `.codegraph`: re-run `python .codegraph/indexer.py` after each structural move.

## Commit

One commit **per seam** (8 commits), each: `refactor: R3.<n> extract <seam> behind facade (no
behavior change)`. `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
