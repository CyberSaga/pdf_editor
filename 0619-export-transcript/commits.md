## Commit Hash Reference

Full `git log` for the campaign branch, oldest to newest. This is the authoritative commit history (supersedes the partial hash list inferred from transcript prose alone).

| Hash | Date | Author | Message | Source Message(s) |
|---|---|---|---|---|
| `c3b6899` | 2026-06-14 | CyberSaga | Add Fusion Agent Manual and implement fusion.py for multi-model synthesis. Also downloaded "CL4R1T4S/ANTHROPIC/CLAUDE-FABLE-5.md" | Pre-dates this session (no direct mention; fusion.py groundwork referenced contextually in Msg 17) |
| `7b6fe6c` | 2026-06-14 | CyberSaga | feat(ui): Fable-5 UI/UX polish — interactive states, elevation, meadow bg | Pre-dates this session (not mentioned) |
| `582978f` | 2026-06-15 | CyberSaga | feat(ui): add "適應畫面" button and icon to PDF view, update documentation | Pre-dates this session (not mentioned) |
| `d78ad44` | 2026-06-15 | CyberSaga | Fable 5 (Level) Refactor plans | Msg 4 — the competing refactoring-master-plan.md / R-Series plan-collision flagged here |
| `6f16ec2` | 2026-06-15 | CyberSaga | test: R0 regression-net repair — green the shipped .venv stack (icon count, ux_signoff lazy import, heartbeat de-flake, coverage baseline) | Msg 8 (R0 implementation), Msg 12 (cited in campaign chain) |
| `4e6f755` | 2026-06-15 | CyberSaga | chore: R1 mechanical hygiene — ruff production-layer clean, app_identity leaf, MANIFEST prune | Msg 12 (cited in campaign chain) |
| `2a2aa96` | 2026-06-15 | CyberSaga | test: R2.1 layer-boundary AST import guard (model Qt/cross-import ban + view fitz.open allowlist) | Msg 12 (cited in campaign chain) |
| `cbe0284` | 2026-06-15 | CyberSaga | test: R2.2 generalize the encryption AST guard to all of model/ (+ R5.5 finding) | Msg 10 (guard goes green, R5.5 finding flagged), Msg 12 ("HEAD is green at R2.2 (cbe0284)") |
| `6e3dea1` | 2026-06-15 | CyberSaga | refactor: R2.3+R2.4 — view stops opening fitz and indexing model.doc (controller page-rect facade) | Msg 12 (committed and green; "view is now fully decoupled from the model's document handle") |
| `44abebe` | 2026-06-15 | CyberSaga | docs(refactor-state): record user directive to /compact after R2, before R3 | Msg 14 ("Recorded and committed (44abebe); tree clean") |
| `870728c` | 2026-06-15 | CyberSaga | refactor: R2.5 — controller read-only query facade (view stops calling model methods) | Msg 16 (R2.5 work — "promotes the remaining View→Model method reach-throughs... to a thin read-only controller query facade") |
| `dc1bb2c` | 2026-06-15 | CyberSaga | refactor: R2.6 — PreviewRenderer uses a public preview-HTML builder, not model dunders | Msg 14 (planned as part of R2.5→R2.7 sequence); not separately narrated |
| `0dd1fac` | 2026-06-16 | CyberSaga | refactor: R2.7 — print-renderer clamp + merge-source _guard_foreign_doc (R2 complete) | Msg 14 (planned as "render clamp + merge guard" — final R2 item); not separately narrated |
| `89770be` | 2026-06-16 | CyberSaga | refactor: R3.1 extract model/text_block_parsing.py behind facade (no behavior change) | Msg 25 ("R3.1–R3.7 are done" — referenced retrospectively) |
| `cbd2cbb` | 2026-06-16 | CyberSaga | docs(refactor-R3): record R3.2a search-coordinator extraction map + fusion-review decision | Msg 16 ("Committed the design map as a doc-only prep commit (cbd2cbb)"), Msg 17 (cited as actual HEAD in stop-hook gate mismatch) |
| `c66877c` | 2026-06-16 | CyberSaga | refactor: R3.2 extract controller/search_coordinator.py behind facade (no behavior change) | Msg 18 (R3.2 proceeds via fusion protocol after blocker resolved) |
| `2fc3461` | 2026-06-16 | CyberSaga | fix(fusion): resolve gemini.cmd on Windows so subprocess can launch the CLI | Msg 17 ("Gemini / fusion.py — fixed a one-line Windows path issue... adds a _gemini_cmd() helper") |
| `2634359` | 2026-06-16 | CyberSaga | chore(gate): refresh two stale completion-gate pins from R0/R1 script edits | Msg 18 (stop-hook gate/proof mismatch investigation) |
| `cc1e0f9` | 2026-06-16 | CyberSaga | refactor: R3.2 extract controller/ocr_coordinator.py behind facade (no behavior change) | Msg 20 (OCR coordinator extraction — Gemini dual-lens design agreed, "move worker/bridge... to OcrCoordinator") |
| `fbed226` | 2026-06-16 | CyberSaga | docs(refactor-R3): record R3.2c print-coordinator extraction map (3-model fusion synthesis) | Msg 22 (print-coordinator constants/imports mapping work) |
| `a597f42` | 2026-06-16 | CyberSaga | refactor: R3.2 extract controller/print_coordinator.py behind facade (no behavior change) | Msg 22 (print-coordinator extraction execution) |
| `87f2aa6` | 2026-06-16 | CyberSaga | docs(refactor-R3): record R3.4a object-ops extraction map (3-model + source-verified) | Msg 22–24 (R3.4 design/mapping work before the no-jump baseline) |
| `04b0a4c` | 2026-06-16 | CyberSaga | refactor: R3.4 extract model/pdf_object_ops.py behind facade (no behavior change) | Msg 24 ("No-jump proof PASSED at 04b0a4c — R3.4 held the geometry invariant") |
| `7e001c8` | 2026-06-16 | CyberSaga | refactor: R3.5 extract model/pdf_text_edit.py behind facade (no behavior change) | Msg 25 ("R3.1–R3.7 are done" — referenced retrospectively) |
| `5179b4f` | 2026-06-16 | CyberSaga | docs(refactor-R3): record R3.6 object-selection extraction map (3-model + source-verified) | Msg 25 (retrospective reference; not separately narrated) |
| `e953fb2` | 2026-06-16 | CyberSaga | refactor: R3.6 extract view/object_selection.py behind facade (no behavior change) | Msg 25 (retrospective reference; not separately narrated) |
| `f3f3b6d` | 2026-06-17 | CyberSaga | refactor: R3.7 extract view/text_selection.py behind facade (no behavior change) | Msg 25 (retrospective reference; later hardened — see `97406ce`) |
| `a7e7734` | 2026-06-17 | CyberSaga | refactor: R3.8a migrate interaction state into managers behind PDFView forwarders | Msg 26 (R3.8a execution — "migrate the ~43 interaction attrs into the two managers"), Msg 28 ("Git tree is still clean (a7e7734)" after re-index) |
| `2a8cf8c` | 2026-06-17 | CyberSaga | perf: R4.5 快速 preset enables object streams (output-identical structural shrink) | Msg 30 (R4 plan loaded; not separately narrated) |
| `62e0b81` | 2026-06-17 | CyberSaga | perf: R4.4 undo byte-budget dedups by content, not id() (no premature eviction) | Msg 30 (R4 plan loaded; not separately narrated) |
| `883fc6e` | 2026-06-17 | CyberSaga | perf: R4.2 revision-keyed worker snapshot-bytes cache (output-identical) | Msg 32 ("Tree is clean at 883fc6e with the full suite green (1398p)") |
| `60c36fc` | 2026-06-17 | CyberSaga | perf: R4.3 hybrid async thumbnail rasterization (output-identical) | Msg 33–34 (R4.3 hybrid-async design and landing; "Pausing here at a clean, fully-gated checkpoint (HEAD 60c36fc, proof PASSED)") |
| `8cabd01` | 2026-06-17 | CyberSaga | docs: R4.1 overlay raster cache evaluated → deferred; R4 closed at 4/5 | Msg 38–40 (R4.1 risk evaluation; cache-only subset recommended, full overlay-cache deferred) |
| `5165b0f` | 2026-06-18 | CyberSaga | security: R5.5 optimize-copy preserves source encryption | Msg 44 ("starting with R5.5 (model-contained, lower risk)") |
| `05963b4` | 2026-06-18 | CyberSaga | docs: append user feature-wishlist notes | Not directly narrated in retained messages |
| `94a62ad` | 2026-06-18 | CyberSaga | security: R5.1 print path no longer writes a decrypted PDF to disk | Msg 43 (Option A — preserve encryption — confirmed for R5.1 and R5.5) |
| `7b413ae` | 2026-06-18 | CyberSaga | security: R5.4 packaging guard — no dev/test trees in shipped artifacts | Not directly narrated in retained messages |
| `6c1298d` | 2026-06-18 | CyberSaga | docs: close R5 at 4/5 — R5.2 OCR bundle BLOCKED (out-of-band human step) | Msg 44 ("Where things stand... gate PASSED on HEAD... R5.2 weights bundle" handoff) |
| `15b50d6` | 2026-06-18 | CyberSaga | chore: re-index codegraph after R5 (237 files, 3827 nodes, 24316 edges) | Msg 46 ("Re-run codegraph indexer... Indexer re-run complete") |
| `42aa51b` | 2026-06-18 | CyberSaga | test: R6.1 characterize merge-compose/print-watermark/bridge-slot/text-selection seams | Msg 50 (R6 Coverage Hardening kickoff) |
| `7442b09` | 2026-06-18 | CyberSaga | test: R6.2 retire stale verify_no_jump full-suite ignores | Msg 50 (R6 Coverage Hardening, continued) |
| `cbfba8e` | 2026-06-18 | CyberSaga | chore: refresh verify_no_jump.py pin after R6.2 ignore removal | Msg 50 (R6 Coverage Hardening, continued) |
| `189c94d` | 2026-06-18 | CyberSaga | test: R6.3 coverage floor — fail_under=75 at-or-below measured baseline | Msg 50 (R6 Coverage Hardening, continued) |
| `4f075ed` | 2026-06-18 | CyberSaga | docs: close R3.4 deferred finding — pending_edits asymmetry is optimization-only | Msg 51–52 ("Document & close" decision; "record the resolution in the R3 plan") |
| `97406ce` | 2026-06-18 | CyberSaga | fix: R3.7 harden TextSelectionManager cleanup to shiboken6.isValid | Msg 52 ("R3.7 — hardened + tested, closed") |

Notes:
- `02c608aa6da6…` and `875442b163ea…` (seen in Message 17) are gate/proof digests, not commit hashes — not included above.
- The transcript prose sometimes referenced commits by a different short hash than git's canonical short form for the same commit (e.g. `cbd2cbb7a834…` and `1a4a527687dc…` are longer renderings of `cbd2cbb` and a stale pre-`cbd2cbb` proof reference, respectively); this table uses git's actual log output as the source of truth.
- R3.2 in the transcript prose covers three separate extraction commits in the real log (search_coordinator `c66877c`, ocr_coordinator `cc1e0f9`, print_coordinator `a597f42`), each with its own doc-map commit.
- Several commits (`dc1bb2c`, `0dd1fac`, `2a8cf8c`, `62e0b81`, `05963b4`, `7b413ae`, and the R3.5/R3.6 pair) were not individually narrated in the condensed transcript — they landed silently within a batch of work described only at a higher level (e.g. "R2.5 → R2.7 on the ticks" or "the R4 plan"), so the Source Message column marks them as planned-but-not-separately-narrated rather than inventing detail not present in the transcript.

