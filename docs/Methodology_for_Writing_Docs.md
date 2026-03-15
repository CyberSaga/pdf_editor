# Methodology for Writing Docs

This repo keeps documentation intentionally small but high-signal. This file defines:

- which doc files are "canonical"
- what each one is responsible for
- how to update docs so they stay consistent with the codebase

Canonical docs (keep these accurate):

- `docs/README.md`
- `docs/README.zh-TW.md`
- `docs/FEATURES.md`
- `docs/ARCHITECTURE.md`
- `docs/架構.txt`
- `docs/solutions.md`
- `test_scripts/TEST_SCRIPTS.md`

This file is the English version. For Traditional Chinese, see:

- `docs/Methodology_for_Writing_Docs.zh-TW.md`

---

## 1. Principles

1. Single Source of Truth
   - Architecture and data-flow details live in `docs/ARCHITECTURE.md`.
   - User-visible behavior lives in `docs/FEATURES.md`.
   - READMEs are entry points (what it is, how to run, where to look next).

2. Prefer "How It Works" over "What We Intended"
   - Docs must reflect current behavior, especially around save/optimize workflows, threading, and failure modes.
   - If you changed behavior, update docs in the same change-set.

3. Keep the Quick Path Quick
   - READMEs should not become design documents. Link to `docs/FEATURES.md` / `docs/ARCHITECTURE.md` instead.

4. Encode as UTF-8
   - All docs are UTF-8.
   - If you see mojibake in a terminal, treat it as a display/encoding issue first, not file corruption.

5. Diagrams Are Allowed (When They Reduce Words)
   - Use Mermaid diagrams in `docs/ARCHITECTURE.md` for workflows / pipelines.
   - Keep node labels short. Use quotes in Mermaid labels if the text contains punctuation or parentheses.

---

## 2. Per-File Responsibilities

### 2.1 `docs/README.md`

Include:

- what the app is, who it is for
- minimal run/dev instructions
- pointers to `docs/FEATURES.md` and `docs/ARCHITECTURE.md`

Avoid:

- deep implementation details (put those in `docs/ARCHITECTURE.md`)
- long troubleshooting lists (use `docs/solutions.md`)

### 2.2 `docs/README.zh-TW.md`

Keep it aligned with `docs/README.md` but translated/adapted for zh-TW readers.

### 2.3 `docs/FEATURES.md`

Purpose: user-visible behaviors and constraints (what users can do, what will happen).

Include:

- workflow-level behavior (e.g., "always saves an optimized copy, never overwrites")
- defaults and presets (names, meanings)
- UX expectations (e.g., "runs in background", "opens output as a new tab")

Avoid:

- class/method names unless needed for clarity
- deep dataflow details (those belong in `docs/ARCHITECTURE.md`)

### 2.4 `docs/ARCHITECTURE.md`

Purpose: how the system is structured and how data flows through it.

Include:

- module boundaries (Model/Controller/View/Tools/Printing)
- critical pipelines (open/edit/render/save/close; optimize-copy; audit scan)
- performance guardrails (what must not run on UI thread, what must be cached, what is paused)
- diagrams:
  - ASCII is acceptable
  - Mermaid is preferred for non-trivial workflows

When adding a workflow graph:

- keep it close to the relevant section (don't centralize all diagrams at the top)
- call out key invariants near the graph (e.g., "never mutate the live document")

### 2.5 `docs/架構.txt`

Purpose: a terse, human-scannable map for contributors (especially when they prefer plain text).

Include:

- file/folder inventory and "what lives where"
- pointers to the authoritative sections of `docs/ARCHITECTURE.md`

Avoid:

- duplicating full architecture explanations
- duplicating feature semantics (link instead)

### 2.6 `docs/solutions.md`

Purpose: operational knowledge and "what to do when X breaks".

Include:

- failure symptoms, root causes, and the actual fix steps
- known tricky environment/setup issues

Avoid:

- design rationales without an operational action

### 2.7 `test_scripts/TEST_SCRIPTS.md`

Purpose: index of test/benchmark scripts and how to run them.

Include:

- what each script validates (workflow, integrity, benchmark)
- how to run headless (Qt env vars), expected runtime, and where outputs go

---

## 3. Feature-Specific Docs Placement

Use this routing so readers can find information quickly:

1. New UI entrypoints (menus, dialogs, new flows)
   - Document in `docs/FEATURES.md` (what users see)
   - Document in `docs/ARCHITECTURE.md` (controller/model pipeline + threading)

2. Performance-sensitive or large-file workflows (e.g., PDF optimize)
   - `docs/ARCHITECTURE.md` must include:
     - the pipeline diagram
     - what runs off the UI thread
     - caching semantics (what is cached, lifetime, invalidation)
     - any "pause background work" rules

3. Unsupported controls / partial parity with other tools
   - Put the list and rationale in a focused file (e.g., `docs/unsupported-optimizer.md`)
   - Link to it from `docs/FEATURES.md` (do not duplicate the list in README)

4. New scripts (benchmarks, validators)
   - Add them to `test_scripts/TEST_SCRIPTS.md`
   - If the script is a "contract" for a feature, link to it from `docs/ARCHITECTURE.md`

---

## 4. Update Loop (PDCA)

1. Plan
   - decide what code behavior will change and list the impacted docs
   - decide which file is the source of truth (usually `docs/FEATURES.md` or `docs/ARCHITECTURE.md`)
2. Do
   - implement the code change first
   - update docs in the same change-set so they match the actual behavior (docs must not lead the code)
3. Check
   - run the minimal verification for the area touched
   - sanity-check that docs do not contradict the UI behavior
4. Act
   - if users still get confused, move details to the right doc (README -> FEATURES/ARCHITECTURE -> solutions)

---

## 5. Quick Checklist

- [ ] updated `docs/FEATURES.md` for user-visible behavior changes
- [ ] updated `docs/ARCHITECTURE.md` for pipeline / threading / caching changes (with a graph if non-trivial)
- [ ] updated `docs/架構.txt` if folders/entrypoints moved or a new major workflow was added
- [ ] updated `test_scripts/TEST_SCRIPTS.md` if a new script was added or run steps changed
- [ ] docs remain UTF-8 and render correctly on GitHub
