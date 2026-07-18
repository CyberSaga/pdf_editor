# M2 review handoff v2 — 2026-07-12 (supersedes `plans/2026-07-10-m2-review-handoff.md`)

Session ended before dispatching any reviewer (session-limit precaution). **No review ran in this
session.** This doc captures the re-oriented state and the exact, ready-to-send reviewer prompts so
the next session can dispatch cold with zero re-derivation.

## State (verified 2026-07-12, this session)

M2 is **merged into `main`** — the 2026-07-10 handoff's "branch not pushed, no PR" state is obsolete.

```
98799ee  merge: integrate M2 bugs and security fixes   (merges milestone-2-bugs-security into main)
62521f8  fix: close M2 review regressions              (post-review defect fixes, see below)
e6fb304  PR-18 / B3  worker decrypted-bytes lifetime
2cc52fd  PR-17 / B2  R5-01 fileless print path
747daa8  PR-16 / B1  delete app-image via invocation removal
a68068d  PR-15 / B1  design doc, zero code
388be1a  PR-14 / B5  gate_anchor follow-up
9c57934  PR-13 / B4  deployment-env closeout
4a8e171  (base)
```

Diff under review: `git diff 4a8e171..98799ee`. Working tree clean.

Gates on the current tree (per `docs/plans/2026-07-12-m2-defect-fixes.md` Outcome): **1636 passed /
21 skipped**; ruff clean; `mypy model/ utils/` clean; all four import-linter contracts clean;
`git diff --check` clean.

### What `62521f8` is (new since the old handoff)

A defect-fix session ran 2026-07-12 (plan: `docs/plans/2026-07-12-m2-defect-fixes.md`). Three
independently reproduced M2 defects were fixed red-light-first:

1. **Shared-xref stale-marker resolution** — the recorded-xref/digest fast path in
   `model/pdf_object_ops.py` now validates candidates against marker geometry/rotation; returns no
   resolution when none match (was: deleting a stale marker could delete the surviving placement).
2. **Inherited-resource pruning** — scans only content streams whose effective
   `Resources/XObject/<name>` binding resolves to the target owner+xref (was: an unrelated same-name
   token on another page blocked pruning).
3. **Print helper `FailedToStart` cleanup** — `src/printing/subprocess_runner.py` routes terminal
   process errors through one idempotent finalization helper shared with `_on_finished` (was: runner
   stayed active and retained the PDF payload).

These are FIXED. Reviewers should verify the fixes are sound but must not re-report the underlying
defects as new findings. (Where those three findings originally came from is not recorded in-repo;
the 2026-07-10 handoff's coverage table predates them.)

## Review coverage — unchanged gaps

Everything in the old handoff's coverage table still holds, plus `62521f8` itself has had no
independent review:

| Target | Reviewed? |
|---|---|
| PR-13, PR-14 (docs-only) | never (low risk) |
| PR-16 / B1 impl | partial — 2 of 4 planned lenses; **codex pass still owed** (milestone-plan mandate) |
| PR-17 / B2 fileless print | **zero review** — largest, most concurrency-heavy change |
| PR-18 / B3 worker lifetime | zero review; its test's assertion method itself unvalidated |
| `62521f8` defect fixes | zero independent review |
| `/code-review` skill on any of M2 | never run |

Also outstanding (not a code-review gap): **manual real-printer validation** — unprotected +
password-protected PDF, temporary print-artifact monitoring during the job, cancel mid-job,
`test_win_print_fixes.py::test_set_page_layout_applies_size_on_real_printer` (`local_only`).
And `plans/b1-delete-app-image-invocation-removal.md` §10.6 open items: batch-delete gives no user
feedback on rollback; `_restore_doc_from_snapshot` yields empty `doc.name`, degrading incremental save.

## Maintainer constraints for the next session

- **At most 2 agents total** (stated 2026-07-12), dispatched **serially, synchronously** — parallel
  bursts trip the session agent limit and kill every in-flight agent (CLAUDE.md §11).
- The two agents are: (1) `plan-code-reviewer` over the whole M2 diff, then (2) a codex pass
  (B1 + PR-17). Synthesize both without showing either the other's output.
- If budget allows only ONE: **codex on PR-17** — it's the only concurrency-heavy change and its
  reviewer count is zero. B1 already has two lenses and six fixes behind it.
- Read the workflow journal / full agent output; never trust a truncated notification (this lost
  findings once already — old handoff, "Process lesson").

## Agent 1 prompt — `plan-code-reviewer` (dispatch verbatim, run_in_background: false)

> Review Milestone 2, now merged into `main`. The diff under review is `git diff 4a8e171..98799ee`
> (merge commit `98799ee` integrated branch `milestone-2-bugs-security`). Seven commits:
>
> - `9c57934` PR-13 / B4 — deployment-env closeout (docs-only; verify it really is docs-only)
> - `388be1a` PR-14 / B5 — gate_anchor follow-up + TODOS hygiene (docs-only; verify)
> - `a68068d` PR-15 / B1 — design doc, zero code (verify zero code)
> - `747daa8` PR-16 / B1 — delete app-image via invocation removal (8 files)
> - `2cc52fd` PR-17 / B2 — R5-01 fileless print path (20 files, largest and most concurrency-heavy)
> - `e6fb304` PR-18 / B3 — worker decrypted-bytes lifetime, Codex F6 (7 files)
> - `62521f8` — post-review defect fixes (see below)
>
> Governing plans, in this order:
> - `plans/milestone-2-bugs-security.md` (the milestone; defines PR-13..PR-18)
> - `plans/b1-delete-app-image-invocation-removal.md` (child design for PR-15/16; §10 records six
>   adversarial findings and fixes, §10.6 lists still-open items)
> - `plans/r5-01-fileless-print.md` (child design for PR-17; §11 is the binding resolved design;
>   §11.4 rejects re-encrypting the CUPS/lp temp as unsound)
> - `docs/plans/2026-07-12-m2-defect-fixes.md` (governs `62521f8`)
>
> Two maintainer decisions override the written plan; treat as authorized, not findings — but check
> the record says so: (a) the plan's HARD STOP for user approval after the B1 design PR was waived
> ("run straight through"); (b) B4's PyInstaller rebuild was deferred and B4 closed as env-verified
> because no `.spec` exists in-repo.
>
> Three defects were ALREADY found, reproduced, and fixed in `62521f8` — verify the fixes are sound
> but do NOT re-report the underlying defects as new findings:
> 1. Shared-xref stale-marker resolution: recorded-xref/digest fast path now validates candidates
>    against marker geometry/rotation (`model/pdf_object_ops.py`).
> 2. Inherited-resource pruning: scans only content streams whose effective
>    `Resources/XObject/<name>` binding resolves to the target owner+xref.
> 3. Print helper `FailedToStart` cleanup: terminal process errors route through one idempotent
>    finalization helper shared with `_on_finished` (`src/printing/subprocess_runner.py`).
>
> Direct particular scrutiny at these, flagged earlier but never independently settled:
> 1. `src/printing/subprocess_runner.py` — chunked stdin streaming (`_begin_stdin_stream`,
>    `_write_next_stdin_chunk`, `_on_stdin_bytes_written`, `_finish_stdin_stream`). Races on crash,
>    `terminate()`, empty payload. Does `closeWriteChannel()` always run exactly once? Can
>    `bytesWritten` arrive after `_cleanup`?
> 2. Whether removing the `password` plumbing from `controller/print_coordinator.py` broke printing
>    of encrypted source PDFs. The justifying claim: `capture_print_snapshot_bytes` uses
>    `PDF_ENCRYPT_NONE` on BOTH branches, so print bytes are always plaintext. Verify in source.
> 3. `model/pdf_object_ops.py::_resolve_xobject_resource_owner` — the `/Parent` ancestor walk, for
>    form-nested and cyclic/malformed `/Parent` chains.
> 4. `test_scripts/test_print_fileless.py` — does the module-level `_FakeProcess` make the chunking
>    test pass vacuously? Does it actually exercise the `bytesWritten` re-entry path? Same question
>    for `test_scripts/test_worker_doc_bytes_lifetime.py`'s `_worker_attrs_holding` assertion.
> 5. The conditional rollback in `delete_objects_atomic` (roll back only if `edit_count` moved) and
>    the orphan-vs-ambiguous split in the `_delete_object_impl` image branch. Can a delete still
>    leave an undeletable "zombie" marker?
>
> Known-outstanding obligations — confirm still open and list in your Outstanding section; do not
> re-litigate as new findings: manual real-printer validation never happened; a codex B1 pass runs
> separately; `plans/b1-...md` §10.6 open items (batch-delete gives no user feedback on rollback;
> `_restore_doc_from_snapshot` yields empty `doc.name`, degrading incremental save).
>
> Verification: use the repository-managed test runner instead of an unrelated system interpreter; dependency skew can mask runtime bugs. Baseline on the current tree: 1636 passed
> / 21 skipped; ruff, mypy (`model/ utils/`), and all four import-linter contracts clean. If you
> contradict that, re-run and show the output.
>
> Hard constraint: if you delegate, spawn subagents strictly ONE at a time and wait for each to
> return — parallel bursts trip the session agent limit and kill every in-flight agent.

## Agent 2 prompt — codex (`codex:codex-rescue` or `/codex:rescue --background`), AFTER agent 1 returns

Do not show it agent 1's output. Codex owes two things:

> You are the independent adversarial reviewer for two changes in a PySide6/PyMuPDF PDF editor,
> merged into `main` as `git diff 4a8e171..98799ee`.
>
> TARGET 1 (mandated by the milestone plan, never ran): B1 — delete app-image via invocation
> removal. Commits `747daa8` plus the `model/pdf_object_ops.py` portions of `62521f8`. Design doc:
> `plans/b1-delete-app-image-invocation-removal.md` (§10 lists six already-fixed findings — do not
> re-report; §10.6 lists known-open items — do not re-report). Focus: content-stream rewriting
> correctness (`_remove_native_image_invocation`), `_resolve_marker_image_invocation` geometry
> validation, `_resolve_xobject_resource_owner` `/Parent` walk (cycles, malformed chains),
> orphan-vs-ambiguous split in `_delete_object_impl`, conditional rollback in
> `delete_objects_atomic` (zombie markers?), inherited-resource pruning scope.
>
> TARGET 2 (zero prior review): PR-17 — R5-01 fileless print path, commit `2cc52fd` plus the
> `src/printing/subprocess_runner.py` portion of `62521f8`. Design doc:
> `plans/r5-01-fileless-print.md` §11. Focus: `QProcess` chunked-stdin streaming races (crash,
> terminate, empty payload, `bytesWritten` after cleanup, double `closeWriteChannel()`), the
> removed password plumbing in `controller/print_coordinator.py` (claim: `capture_print_snapshot_bytes`
> always emits plaintext via `PDF_ENCRYPT_NONE` on both branches — verify), cancel paths, temp-file
> guarantees, and whether `test_scripts/test_print_fileless.py`'s `_FakeProcess` makes the chunking
> tests vacuous.
>
> Priority if constrained: TARGET 2. Run through the repository-managed test runner (never a bare system command).
> pytest). Baseline 1636 passed / 21 skipped. Reproduce any claimed bug with a minimal script or
> failing test before reporting it.

## After both return

1. Synthesize independently (neither sees the other's findings).
2. Reproduce each finding before acting (red-light-first per CLAUDE.md §5.1).
3. Fix confirmed findings; update `docs/PITFALLS.md` (+ regen index), TODOS.md.
4. Then the only remaining M2 obligation is **manual printer validation** (checklist in
   `plans/milestone-2-bugs-security.md` §6) → archive both handoffs and the milestone plan to
   `plans/archive/` on close.
