# to_Update.md Backlog — Implementation Order

**Goal:** Sequence the 17 open items in `docs/to_Update.md` into phased waves, grouped by shared root cause and dependency, so fixes compound rather than collide.

## Context

`docs/to_Update.md` lists a mix of regressions (text-box editing, print behavior), missing features (image object selection, shell integration), and quality issues (render clarity, perf). Several items have been "fixed" multiple times without sticking — signaling that patch-level attempts are not reaching the root cause. This plan orders the work so related defects are diagnosed together, and high-risk interaction/UX redesigns are gated behind the `brainstorming` skill rather than coded speculatively.

**Scope of this document:** ordering and rationale only. Each phase will get its own `docs/plans/YYYY-MM-DD-<feature>.md` written with `writing-plans` before implementation.

---

## Phase 1 — Print regressions (isolated, low-risk, fast wins)

| # | Item | Entry point |
|---|---|---|
| 1 | Printer preferences must not be mutated after print | `src/printing/print_dialog.py`, `src/printing/dispatcher.py` |
| 2 | Auto-rotate to page orientation | `src/printing/layout.py` |
| 3 | Paper size derived from source page | `src/printing/layout.py` |

**Rationale:** Printing subsystem is self-contained; all three share one module cluster. Bundling them amortizes the test harness cost.
**Acceptance:** after printing, `QPrinter` prefs equal pre-print snapshot; mixed-orientation doc prints each page correctly; A4/Letter source pages print to matching paper.

---

## Phase 2 — Text editing fidelity (shared root cause suspected)

| # | Item | Entry point |
|---|---|---|
| 4 | Edit-complete position shift / layout push | `view/text_editing.py`, `model/edit_requests.py` |
| 5 | Font size changes after edit (grows during, shrinks after) | `model/edit_requests.py` (float vs int — see `CLAUDE.md §9`) |
| 6 | Text collapses to black single font after edit | `model/edit_requests.py` (span style preservation) |
| 7 | Edit box shows averaged background instead of transparent with save-color text | `view/text_editing.py` |
| 8 | Rotated-text edit: content scales up and gets clipped | `view/text_editing.py` + `view/pdf_view.py` rotation transform |

**Rationale:** Items 4–8 all route through the same edit-commit path. The repeated failed patches on #4 are evidence that we need a **systematic diagnosis** of the span reconstruction + geometry recomputation pipeline (`systematic-debugging` skill) before touching code. Fix the pipeline once, validate all five symptoms simultaneously.

**Gate:** write a reproduction test for each symptom *before* implementation (Red-Light first, per `CLAUDE.md §5.1`).

---

## Phase 3 — Selection & object interaction

| # | Item | Entry point |
|---|---|---|
| 9 | Text selection by whole line instead of char-run | `view/pdf_view.py` `_text_selection_*` |
| 10 | Image aspect-ratio corruption on first drag + on rotation | `view/pdf_view.py` handle logic, `model/object_requests.py` |
| 11 | Rotation handle: drag-to-free-rotate, not click-90° | `model/object_requests.py` `ObjectHitInfo.rotation` |

**Rationale:** All three are interaction-model changes in the view layer. #11 is a UX redesign — run through `brainstorming` first to pick between free-rotate, snap-on-modifier, or dual-mode.

---

## Phase 4 — Performance & diagnostics (measure before fixing)

| # | Item | Action |
|---|---|---|
| 12 | OCR progress-bar idle delay before work starts | Instrument `model/tools/ocr_tool.py` startup; identify the blocking call |
| 13 | Text + image rendering looks blurry | Audit `view/pdf_view.py._render_scale` vs device pixel ratio |
| 14 | Slow file open / page switch / print-send freeze | Profile with `cProfile`; document hotspots in `docs/PITFALLS.md` before coding |

**Rationale:** No fix without profiling data. Each of these needs a short investigation report committed under `docs/reports/` before a plan is written.

---

## Phase 5 — New features & platform integration

| # | Item | Entry point |
|---|---|---|
| 15 | macOS menubar moved to top system bar (plan already exists) | Main window wiring in `main.py` / view |
| 16 | Select & manipulate images already embedded in source PDF | `model/object_requests.py` + `view/pdf_view.py` hit-testing |
| 17 | Windows right-click "Merge PDF with PDF Editor" | `model/headless_merge.py` (already has CLI); Registry install step |
| 18 | Conformance to PDF Standards (ongoing) | Cross-cutting — backlog epic, not a single task |

**Rationale:** Additive work. None are blocked by Phases 1–4, but doing them first would paint over unresolved regressions. #18 is the largest and open-ended — treat as continuous, not a sprint item.

---

## Critical files reused across phases

- `view/pdf_view.py` — touched in Phases 2, 3, 4, 5 → coordinate merges carefully; prefer separate feature branches and sequential merges over parallel edits.
- `model/edit_requests.py` — Phase 2 epicenter.
- `src/printing/*` — Phase 1 only; safe to parallelize with Phase 2 if staffed.
- `docs/PITFALLS.md` — update after each phase per `CLAUDE.md §6`.

## Verification approach

Per phase:
1. Write red-light tests first (`CLAUDE.md §5.1`).
2. `ruff check .` zero new violations; `pytest` green; manual GUI smoke test of the touched flow.
3. Update `docs/ARCHITECTURE.md` if module responsibilities shift (Phases 2, 3, 5 likely).
4. Append PITFALLS entries for each non-obvious failure mode uncovered.

## Suggested next step

Start **Phase 1 Item 1** (printer prefs leak) — smallest blast radius, validates the workflow end-to-end, then move into Phase 2's diagnosis task which is the real unlock.
