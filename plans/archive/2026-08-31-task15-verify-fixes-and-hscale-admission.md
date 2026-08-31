# Task 15 — verifier fixes and positive-hscale admission

## Goal

Land the three changes specified by `plans/p4-b-deep-dahl.md` as stacked
branches: target-local V0c operator proof, a metric growth-background box,
and positive finite horizontal-scale admission.

## Item 1 — V0c target-local operator proof

- [x] Add red tests for Tier 0/Tier 1 neighboring-source text and malformed or
  refused target-operator replay.
- [x] Replace the halo-wide source-substring rejection with a stream-local,
  exact-splice operator proof.
- [x] Run focused and full verification, then update persistent docs.

## Item 2 — growth-background metric box

- [x] Add the flag-on/off, ink, rotation, and compatibility red matrix.
- [x] Derive the flag-immune metric sampling quad in the planner and thread it
  only to the background-majority sampler.
- [x] Run focused and full verification, then update persistent docs.

## Item 3 — positive-hscale admission

- [x] Add the positive/non-positive hscale red matrix and census-mirror pins.
- [x] Apply the raw/effective advance contract to every documented consumer.
- [x] Update all live census gate mirrors and rerun the private census when the
  corpus is available.
- [x] Run focused and full verification, update persistent docs, and archive
  this plan.

## Decisions log

- 2026-08-31: The supplied `p4-b-deep-dahl.md` is the controlling design;
  this file is the CLAUDE.md §8 execution record.
- 2026-08-31: Work starts from `03b08db` on three stacked branches; the dated
  `bench_gui_tier1.py` report remains frozen.
- 2026-08-31: V0c keeps the extraction/ToUnicode gate first, then replays only
  the patched stream and proves one exact-splice target show. The halo-wide
  source-substring test is removed because neighboring shows may contain the
  same text legitimately.
- 2026-08-31: Tier 1 stores a quad-only, flag-immune font-metric sampling box.
  It is not token input because it derives only from fingerprint- and
  advance-bound evidence; `None` retains legacy target-box sampling for
  hand-built candidates.
- 2026-08-31: Raw advances remain token and kern inputs; fallback, growth, and
  metric-background geometry multiply by `th = hscale / 100.0` first. The TJ
  kern is hscale-free because the shared positive Th cancels.
- 2026-08-31: Corpus re-attribution was exact: 877 hscale-only shows became
  source-bindable; 88 TJ+hscale shows became TJ-only; unrelated/page-eligibility
  counters did not drift. Aggregate-only privacy scan passed.
- 2026-08-31: Final verification passed: the focused compatibility set was
  107/107 and the repository suite was 2,933 passed, 21 skipped, 5 expected
  failures. Ruff, mypy, and whitespace checks also passed before commit.
