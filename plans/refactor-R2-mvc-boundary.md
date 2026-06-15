# Phase R2 — MVC Boundary Reconvergence (guard-first)

**Status:** Ready (after R1). **Fusion:** 2-model (rules are explicit — Playbook 4.3).
**Why before R3:** model/ is provably Qt-clean and cross-import-clean (0 imports both ways)
*today*. This phase **locks that invariant with a CI guard FIRST**, then fixes the live View→Model
reach-through. The guard is the structural safety net that makes R3 decomposition safe — without
it, an accidental `from controller import` during seam extraction regresses silently.
(Census: MVC lens; critique HAZARD 3+4.)

> **Implicit risks:** an over-broad import guard red-lights the *sanctioned* exceptions
> (`text_editing.py:680` scratch `fitz.open`, geometry value-types, `model/edit_requests.py:5` +
> `object_requests.py:5`). The `controller.get_page_rect` replacement must return a byte-identical
> `fitz.Rect` *including rotation* or object-drag geometry breaks. The PreviewRenderer fix is
> pixel-parity-critical (no-jump gate).

---

## R2.1 — Ship the AST import-boundary guard FIRST (the structural net)

- No layer-boundary CI guard exists; the encryption invariant's AST scan
  (`test_xref_repair.py:324-368`, `REPO_ROOT` helper L18) is the exact precedent.
- **New `test_scripts/test_layer_boundaries.py`** (`ast.parse`/`ast.walk`, utf-8-sig):
  - For every `.py` under `model/`: assert **no** `PySide6`/`PyQt` import and **no**
    `from view`/`from controller` import (currently 0 — locks it in).
  - For every `.py` under `view/`: flag `fitz.open(` `ast.Call` nodes, with an **allowlist** of
    exactly `{view/text_editing.py:680}` (empty scratch doc for no-jump preview) + a comment
    pointing at the rationale. Geometry value-types (`fitz.Rect/Point/Quad/Matrix`) and the typed
    request channel (`model/edit_requests.py:5`, `model/object_requests.py:5`) are explicitly
    allowed.
  - (Optional, advisory) flag new `controller.model.doc[...]` `Subscript` chains in `view/`.
- **This test lands first in the phase**, green against current code, so every subsequent R2/R3
  edit runs against a live guard.

## R2.2 — Generalize the encryption AST guard to all of model/

- The `self.doc.{save,tobytes}`-missing-`encryption=` guard walks only `pdf_model.py`. When
  `edit_text`/object-ops leave that file in R3, the guard goes blind.
- **Fix (here, ahead of R3):** widen the AST walk to **every `.py` under `model/`**; keep the
  documented decrypt-sink allowlist (`capture_worker_snapshot_bytes` `PDF_ENCRYPT_NONE`, page-
  snapshot `tmp_doc.save`, export `new_doc.save`). Strengthen to also assert any
  `encryption=PDF_ENCRYPT_NONE` is on the vetted allowlist (presence-only check is too weak).

## R2.3 — Close the real view `fitz.open` leak (merge/insert dialog)

- `view/pdf_view.py:5314-5326` `_resolve_insert_source_file()` delegates to
  `controller.resolve_insert_source_file()` (exists at `pdf_controller.py:3258`) but **falls back
  to `fitz.open(source_file)` at :5319** to read `len(source_doc)`.
- **Fix:** drop the fitz fallback; make the controller path the only one (raise/show-error if
  controller is absent). The page-count probe lives entirely in controller/model. (TODOS.md:22.)

## R2.4 — Replace the 8 `controller.model.doc[...]` reach-through reads

- Sites: `pdf_view.py:3239,3354,3411,3428,3460,3730,4191,5388` — all read
  `controller.model.doc[page_idx].rect` (and `:3460` reads `.rotation`).
- **Fix:** add `controller.get_page_rect(page_idx) -> fitz.Rect` (read-only geometry accessor,
  rotation-faithful) and replace all 8. View loses its live-document handle for reads; behavioral
  risk is low *iff* the returned rect is identical including rotation.

## R2.5 — Promote the remaining View→Model method reach-through to a controller query API

- `text_editing.py:1227` `get_render_width_for_edit`; `pdf_view.py:2469,4247,4251,4253`
  `block_manager.get_paragraphs/get_runs/get_blocks`; `:4242` `ensure_page_index_built`;
  `:5084` `tools.watermark.get_watermarks()` (4-hop — deepest violation); `:1879`
  `has_unsaved_changes()`.
- **Fix:** thin read-only controller facade — `controller.get_render_width_for_edit`,
  `controller.iter_text_targets(page_idx, mode)`, `controller.get_watermarks()`,
  `controller.has_unsaved_changes()`. Forwards only; owns no new state.

## R2.6 — De-couple PreviewRenderer from private model methods

- `text_editing.py:618-619` stores `self._model`; `:687,693` call the **private**
  `_build_insert_css` / `_convert_text_to_html`; the model is pulled via
  `getattr(getattr(view,'controller',None),'model',None)` (`:1328,1362`).
- **Fix:** expose a public `controller.build_insert_preview_html(text,size,color,font,line_height)
  -> (css, html)` and have PreviewRenderer depend on that callable, not `self._model` + dunders.
- **Pixel-parity gate:** the no-jump tests assert byte-identical preview↔commit rasterization —
  any CSS/HTML drift fails the gate. Verify with `scripts/verify_no_jump.py --skip-signoff`.

## R2.7 — Pulled-forward security quick-wins (mechanical, independent of R3)

- **`pdf_renderer.py:84`** is the one unclamped raster path: `zoom = dpi/72; matrix =
  fitz.Matrix(zoom, zoom); get_pixmap(...)` with no `safe_render_scale`. Add
  `utils.render_limits.safe_render_scale(page, zoom)` at the single site (utils import is legal
  from src/printing).
- **`compose_merged_document` (`pdf_model.py:1516`) + `open_merge_source` (`:1536`)** open foreign
  files without `_guard_foreign_doc` (bypassing `_MAX_PDF_BYTES`/`_MAX_PAGES`). Route both through
  `_guard_foreign_doc(path, password=...)`, removing the duplicated inline `fitz.open`+auth blocks.

---

## Fusion Protocol Playbook

- **Playbook 4.3** (cross-layer boundary audit, 2-model) on `view/pdf_view.py` and
  `view/text_editing.py` before editing:
  ```powershell
  .venv\Scripts\python.exe scripts/fusion.py `
      "Audit for MVC violations. Rules: View never imports model/ or calls fitz directly
       (geometry value-types + the empty scratch fitz.open at text_editing.py:680 are sanctioned);
       Model never imports Qt; Controller is the only coordinator. List every violation with exact
       call site, and for each propose the controller facade method to replace it." `
      --file view/pdf_view.py --file view/text_editing.py
  ```
- R2.6 (PreviewRenderer) is pixel-parity-critical → run it through 4.3 **and** confirm against the
  no-jump gate; if the synthesis flags drift risk, escalate that single step to 3-model.

## Verification & Gatekeeping

```powershell
.venv\Scripts\python.exe -m pytest test_scripts/test_layer_boundaries.py -v          # the new guard, green
.venv\Scripts\python.exe -m pytest test_scripts/test_xref_repair.py -v                # generalized encryption guard
.venv\Scripts\python.exe scripts/verify_no_jump.py --skip-signoff                     # pixel-parity (R2.6)
.venv\Scripts\python.exe -m pytest test_scripts/test_pdf_merge_workflow.py test_scripts/test_headless_merge.py -v
.venv\Scripts\python.exe -m pytest test_scripts/ -q --tb=line -p no:cacheprovider     # full green
.venv\Scripts\python.exe -m ruff check view/ controller/ model/ src/printing/
```

**Gate:** `test_layer_boundaries.py` green and committed **before** any R3 work begins. No-jump
gate must hold across R2.6.

## Risk Triage (2→3 upgrade points)

- **R2.6 PreviewRenderer → 3-model if** the 4.3 synthesis flags any CSS/HTML divergence risk
  (security/correctness-adjacent via the no-jump pixel contract).
- All other steps **2-model**: explicit, well-bounded boundary fixes; no state migration; the
  pulled-forward security clamps are single-site mechanical additions.
- **Vectors:** over-broad guard blocks valid code (allowlist the 4 sanctioned cases); a non-
  identical `get_page_rect` (rotation!) breaks object-drag; merge `_guard_foreign_doc` could reject
  a previously-working large legitimate merge (confirm 512MB/5000pp limits are acceptable for real
  user docs).

## Docs (same commit)

- `docs/ARCHITECTURE.md §7`: add the import-boundary guard contract + the controller read-only
  query API; note the generalized encryption guard now walks all of model/.
- `docs/PITFALLS.md`: "view must not index `controller.model.doc[...]` — use `get_page_rect`";
  "PreviewRenderer must depend on a public preview-HTML builder, not private model dunders".
- `TODOS.md`: mark "MVC routing of merge-dialog page counting" done.

## Commit

Two commits (guard first, fixes second): `test: R2.1 layer-boundary AST guard + generalized
encryption guard`; then `refactor: R2 MVC reconvergence — kill view fitz/model reach-through,
public preview-HTML + page-rect facade, pulled-forward render clamp + merge guard`.
`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
