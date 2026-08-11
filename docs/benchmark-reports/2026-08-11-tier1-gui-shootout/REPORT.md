# Tier 1 Text-Commit Engine GUI Shootout — 2026-08-11

Comparison of the two independent Task 11 Slice 1 builds, driven through the
**real GUI stack** (offscreen `QApplication` + real `PDFView` +
`PDFController.activate()`, edits via `controller.edit_text` with
`target_mode='run'` — the exact slot the GUI signal path invokes).

- **Engine A** — worktree `task11-remaining-closure`, commit `46623c5`
  (Build A lineage, `text-editing-design-v2` descendant)
- **Engine B** — worktree `by-fable`, commit `95851aa`
  (independent build)
- Env: `TEXT_COMMIT_ENGINE=tiered`, `TEXT_COMMIT_MAX_TIER=1`,
  `TEXT_COMMIT_TELEMETRY=local`, `QT_QPA_PLATFORM=offscreen`
- Workload: 5 fixtures × up to 3 deterministic targets × 3 scenarios
  (same-length / +40% growth / −40% shorten) = 45 measured edits per side
  (+3 symmetric skips), identical record-for-record on both sides.
- Harness: `bench_gui_tier1.py` (this directory) — single shared script,
  zero per-worktree compat branches.
- Orchestration: ultracode workflow `wf_0e9e1334-0df`
  (serial bench A → bench B → visual fidelity judge → adversarial verify).

## Verdict

**Winner: `task11-remaining-closure` — on speed only.** Fidelity, stability,
and memory are effective ties.

Headline finding: **every one of the 45 result renders is byte-identical
(md5) between the two engines** — including the 3 Tier 1 commits. The two
implementations produce pixel-for-pixel the same output on this corpus.

| Dimension | task11-remaining-closure | by-fable | Confidence |
|---|---|---|---|
| Fidelity | 8 (tie) | 8 (tie) | LOW as a Tier-1 discriminator (see caveat) |
| Stability | 9 — 0 errors, 45/45 committed | 9 — same | MEDIUM |
| Speed | **8** — p50 256 ms / p95 1331 ms | 4 — p50 417 ms / p95 3756 ms | HIGH |
| Performance | **8** — total 22.5 s | 4 — total 50.8 s | HIGH |
| Memory | 7 — peak WS 792 MB, leak loop +2.07 MB | **7.5** — 760 MB, +0.68 MB | MEDIUM |
| **Overall (weighted)** | **8.1** | 7.18 | MEDIUM |

Weights: fidelity 35%, stability 25%, speed 15%, performance 10%, memory 15%.

The speed gap is systematic (1.6–3× on every fixture, corroborated by
in-model `duration_ms` timers, so not harness noise). Part of by-fable's
extra cost is that it does more checking: it emits a strictly better reject
taxonomy (`target_in_form_xobject`, explicit `tier0:advance_mismatch`
escalation chain, `compensated_transplant_kern` warning) where
task11-closure lumps the same cases into generic `no_source_match`.

## Critical caveat (adversarial-verify finding, stated bluntly)

**Only 3 of 45 edits per side (6.7%) actually engaged Tier 1** — the
discovered `'Standard'` target on `test-large-file.pdf` p15. The other 42
fell through the tier 0 gates to the shared legacy redact+reinsert path
(`degraded_committed`) on BOTH sides, because the fixtures' first text pages
contain only TJ arrays, CID-coded text, or Tw/Tc-tainted ops. This benchmark
is therefore ~93% a measurement of the whole commit pipeline (legacy path +
tiered pre-flight), **not** of Tier 1 substitution quality. A decision about
which Tier 1 engine *edits text better* requires a fixture set that actually
passes the tier gates (see the `fidelity-corpus-generator` worktree).

The 3 Tier 1 commits themselves were the best-quality results in the corpus
on both sides (outside-rect drift ≤ 1.3e-4, correct Arial-ItalicMT, correct
baseline). by-fable's kern compensation cost ~3× latency there
(~3.9 s vs ~1.35 s per commit) and bought zero pixel difference on this font.

Visual judging also reconfirmed known **legacy-path** corruptions (shared
product concern, not a differentiator): advance-width breakage on
same-length swaps (`1/t0`), glyph overprint on growth (`1/t2`), sans→serif
substitution (`test-horizontal-texts/t1`), and a ~180 px CJK title shift on
`test-colored-background/t0` — the outside-rect pixel metric undersensitively
scores these because the damage is inside the edited rect.

## Contents

- `bench_gui_tier1.py` — shared harness (parameterized `--worktree`/`--out`)
- `task11-closure/result.json`, `by-fable/result.json` — full per-edit
  records + aggregates (latency, tier funnel, memory, pixel diffs)
- `*/renders/<fixture>/<target>_<scenario>_{before,after}.png` — 144 dpi
  page renders around every edit
- Note: `task11-closure/renders/test-large-file/t101_*.png` are stale files
  from an earlier smoke run (~3.5 min before its result.json); t101 was
  skipped (`discovered_span_not_found`) on both sides — do not read them as
  a t101 success.

Machine context: single Windows 11 machine, sequential runs, project
`.venv` (PyMuPDF 1.27.1, PySide6 offscreen). Fixture `1.pdf` differed in
bytes across the three checkouts (behavior and picks identical); the other
four fixtures were byte-identical (sourced from the main checkout's
`test_files/`).
