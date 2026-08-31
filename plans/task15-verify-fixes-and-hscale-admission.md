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
- [ ] Run focused and full verification, then update persistent docs.

## Item 2 — growth-background metric box

- [ ] Add the flag-on/off, ink, rotation, and compatibility red matrix.
- [ ] Derive the flag-immune metric sampling quad in the planner and thread it
  only to the background-majority sampler.
- [ ] Run focused and full verification, then update persistent docs.

## Item 3 — positive-hscale admission

- [ ] Add the positive/non-positive hscale red matrix and census-mirror pins.
- [ ] Apply the raw/effective advance contract to every documented consumer.
- [ ] Update all live census gate mirrors and rerun the private census when the
  corpus is available.
- [ ] Run focused and full verification, update persistent docs, and archive
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
