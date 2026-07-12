# M2 review handoff — 2026-07-10

Milestone 2 is **implemented, committed, and gated**. It is **not reviewed**. This doc
exists so the review can be resumed cold, without re-deriving scope.

## State

Branch `milestone-2-bugs-security`, base `4a8e171` on `main`. Not pushed, no PR, not merged.

| Commit | PR | Item | Scope |
|---|---|---|---|
| `9c57934` | PR-13 | B4 | deployment-env closeout (1 file) |
| `388be1a` | PR-14 | B5 | gate_anchor follow-up + TODOS hygiene (1 file) |
| `a68068d` | PR-15 | B1 | design doc, **zero code** (1 file) |
| `747daa8` | PR-16 | B1 | delete app-image via invocation removal (8 files) |
| `2cc52fd` | PR-17 | B2 | R5-01 fileless print path (20 files) |
| `e6fb304` | PR-18 | B3 | worker decrypted-bytes lifetime, Codex F6 (7 files) |

Diff under review: `git diff 4a8e171..HEAD` — 29 files, +3004 / -333.

Gates on the committed tree: **1632 passed / 21 skipped / 1 deselected** (baseline before
M2 was 1585); `ruff check .` clean; `mypy model/ utils/` clean; all four import contracts clean.

Deliberately **out of scope** (uncommitted, unrelated to M2): `.codegraph/graph.db`,
`docs/to_Update.md`, `plans/2026-07-10-m3-feasibility-recon.json`, a stray deleted `.txt`,
and `.claude/agents/plan-code-reviewer.md`.

## Review coverage — what ran, what did not

**Read this before assuming anything is reviewed.** The one adversarial review that happened
covered **B1 only**. Everything in PR-13, PR-14, PR-17, and PR-18 has had *zero* review beyond
the author's own testing and the CI gates. The `/code-review` skill has never been run on any
part of M2.

### Reviewers

| Reviewer | Target | Status | Where its output lives |
|---|---|---|---|
| Adversarial lens 1 — PDF/content-stream semantics (had shell; measured its claims) | B1 (`747daa8`) | **ran, actioned** | `plans/b1-...md` §10.1–§10.3 |
| Adversarial lens 2 — contract regression (source-only, no shell; **none of its findings were executed**) | B1 | **ran; output truncated in notification, recovered late from `journal.jsonl`** | `plans/b1-...md` §10.5, fixes §10.6 |
| Adversarial lens 3 | B1 | **DIED** — session agent limit | nothing |
| Codex peer pass (mandated by the milestone plan for B1) | B1 | **DIED** — session agent limit | nothing |
| `plan-code-reviewer` (`/code-review high` + plan-conformance judgment) | whole M2 diff | **NEVER DISPATCHED** — attempted twice, interrupted both times near the session limit | nothing |
| `/code-review` skill, any level | anything in M2 | **NEVER RUN** | nothing |

Six findings came out of lenses 1+2; all six are reproduced and fixed (`plans/b1-...md`
§10.1–§10.6). §10.3 (inline-image `BI … ID … EI` tokenizer gap) was consciously **not acted on** —
it is pre-existing and filed in TODOS.

### Angles never covered, by PR

| PR | Item | Adversarial review? | Notes |
|---|---|---|---|
| PR-13 `9c57934` | B4 deployment env | none | docs-only closeout; low risk |
| PR-14 `388be1a` | B5 gate_anchor | none | docs-only; low risk |
| PR-15 `a68068d` | B1 design | n/a | design doc, zero code |
| PR-16 `747daa8` | B1 impl | **partial** — 2 of 4 planned lenses | codex pass still owed |
| PR-17 `2cc52fd` | B2 / R5-01 fileless print | **none** | 20 files, the largest and most concurrency-heavy change in M2 |
| PR-18 `e6fb304` | B3 / Codex F6 | **none** | worker lifetime; the test's assertion method is itself unvalidated |

PR-17 is the one that should worry you most: it rewrites the print transport to stream PDF bytes
over `QProcess` stdin, and nothing independent has looked at it.

### Also outstanding (not a code-review gap)

**Manual real-hardware printer validation** of the fileless print path: unprotected +
password-protected PDF, `%TEMP%` watch during the job, cancel mid-job. The automated smoke passed
(no PDF appeared in `%TEMP%` while a real helper subprocess printed; pixel-level neighbour
survival) but **no physical printer was ever exercised**. `test_win_print_fixes.py::
test_set_page_layout_applies_size_on_real_printer` is marked `local_only` and does not run in CI.

## Resume: dispatch this, synchronously, one agent at a time

Serial dispatch is a hard constraint (CLAUDE.md §11, and the maintainer restated it): parallel
bursts trip the session agent limit and kill **every** in-flight agent at once.

> Review Milestone 2 on branch `milestone-2-bugs-security`. The work is **committed** — the diff
> is `git diff 4a8e171..HEAD` (six commits, 29 files, +3004/-333). Do not review the uncommitted
> working-tree paths; they are deliberately out of scope.
>
> Governing plans, in this order:
> - `plans/milestone-2-bugs-security.md` (the milestone; defines PR-13..PR-18)
> - `plans/b1-delete-app-image-invocation-removal.md` (child design doc for PR-15/PR-16; §10
>   records six adversarial-review findings and their fixes, §10.6 lists still-open items)
> - `plans/r5-01-fileless-print.md` (child design doc for PR-17; §11 is the binding resolved
>   design, §11.4 rejects re-encrypting the CUPS/lp temp as unsound)
>
> Commit → PR mapping: as in the table above. Verify `a68068d` really is docs-only.
>
> Two maintainer decisions override the written plan; treat them as authorized, not as findings —
> but check the record says so:
> - The plan's HARD STOP for user approval after the B1 design PR was waived ("run straight through").
> - B4's PyInstaller rebuild was deferred and B4 closed as env-verified, because no `.spec` exists
>   anywhere in the repo, so there is no recipe to rebuild from.
>
> Direct particular scrutiny at these, which earlier passes flagged but never settled:
> 1. `src/printing/subprocess_runner.py` — chunked stdin streaming (`_begin_stdin_stream`,
>    `_write_next_stdin_chunk`, `_on_stdin_bytes_written`, `_finish_stdin_stream`). Races on crash,
>    `terminate()`, and empty payload. Does `closeWriteChannel()` always run exactly once? Can a
>    `bytesWritten` signal arrive after `_cleanup`?
> 2. Whether removing the `password` plumbing from `controller/print_coordinator.py` broke printing
>    of encrypted/password-protected source PDFs. The justifying claim is that
>    `capture_print_snapshot_bytes` uses `PDF_ENCRYPT_NONE` on **both** branches, so print bytes are
>    always plaintext. Verify that claim in the source.
> 3. `model/pdf_object_ops.py::_resolve_xobject_resource_owner` — the `/Parent` ancestor walk, for
>    the form-nested case and for cyclic/malformed `/Parent` chains.
> 4. `test_scripts/test_print_fileless.py` — does the module-level `_FakeProcess` make the chunking
>    test pass **vacuously**? Verify it actually exercises the `bytesWritten` re-entry path rather
>    than short-circuiting it. Same question for `test_scripts/test_worker_doc_bytes_lifetime.py`'s
>    `_worker_attrs_holding` assertion.
> 5. The conditional rollback in `delete_objects_atomic` (roll back only if `edit_count` moved) and
>    the orphan-vs-ambiguous split in the `_delete_object_impl` image branch. Can a delete still
>    leave an undeletable "zombie" marker?
>
> Known-outstanding obligations — confirm they are still open and list them in your Outstanding
> section; do not re-litigate them as new findings: the codex B1 review never ran; manual printer
> validation never happened; `plans/b1-...md` §10.6 open items (batch-delete gives no user feedback
> on rollback; `_restore_doc_from_snapshot` yields an empty `doc.name`, degrading incremental save).
>
> Verification environment: `.venv\Scripts\python.exe -m pytest` — never bare `pytest`. Baseline on
> the committed tree is 1632 passed / 21 skipped / 1 deselected; ruff, mypy, and all four import
> contracts are clean. If you contradict that, re-run and show the output.
>
> If you delegate, spawn subagents strictly one at a time and wait for each to return.

After `plan-code-reviewer` returns, run the **codex** pass independently (`/codex:rescue --background`,
per CLAUDE.md §11) and synthesize both without showing either reviewer the other's output. Codex owes
two things, not one: the **B1 pass the milestone plan mandates** (never ran), and a first look at
**PR-17**, which no reviewer has ever seen.

Priority if the session budget only allows one: **PR-17**. It is the largest change, it is the only
concurrency-heavy one, and its reviewer count is zero. B1 at least has two lenses and six fixes behind it.

## Process lesson that cost real findings

The B1 review workflow ran four agents; two died on the session limit, and the surviving second
lens's findings were **truncated in the task notification** and silently missed. They were only
recovered by reading `<transcriptDir>/journal.jsonl` directly. Four of the six B1 fixes came from
that recovered output, including a major one.

**Read the workflow journal. Never trust the notification summary to be complete.**
