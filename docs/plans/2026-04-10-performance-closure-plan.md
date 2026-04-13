# B4 Child Plan -- Performance Closure

## Goal

Close `B4` with measured speed improvements in the three backlog-critical workflows:

1. document open
2. page-change / page render
3. optimize-copy

The exit bar is not "we profiled it." The exit bar is before/after evidence showing that real changes shipped and improved the measured hotspots.

## Baseline Snapshot (captured 2026-04-12)

Environment: current Windows development machine, repo root execution, local sample files.

- Startup:
  - `python test_scripts/measure_startup_time.py`
  - `PDFModel` import: about `0.441s`
  - `PDFModel` instantiate: about `0.003s`
  - combined import + instantiate: about `0.444s`
- Synthetic large-file open:
  - `python test_scripts/test_open_large_pdf.py --pages 300 --first-page`
  - open 300-page generated PDF: about `0.02s`
  - first page `get_page_pixmap(1, 1.0)`: about `8ms`
- Page-change / render spot check on the same 300-page file:
  - page 1 render: about `7.93ms`
  - page 150 render: about `1.43ms`
  - page 300 render: about `1.13ms`
- Repeated-edit latency:
  - `python test_scripts/test_performance.py --rounds 10`
  - average: about `0.034s`
  - max: about `0.112s`
  - over `300ms`: `0`
- Optimize-copy:
  - ad-hoc probe on `test_files/1.pdf` with the balanced preset
  - elapsed: about `0.087s`
  - bytes saved: `5183`
  - percent saved: about `21.8%`
- Large optimize-copy hotspot:
  - ad-hoc probe on `test_files/2024_ASHRAE_content.pdf` with the balanced preset
  - exceeded the initial `124s` timeout window
  - treat this as the highest-risk `B4` hotspot until we gather a full timed run or materially reduce it

## Slice 1 Results (2026-04-12)

Preset-aware optimize-copy routing is now landed.

- `快速`
  - about `15.6s` on `test_files/2024_ASHRAE_content.pdf`
  - speed-first result; size stayed effectively unchanged on this sample
- `平衡`
  - about `20.4s` on `test_files/2024_ASHRAE_content.pdf`
  - about `37.9%` saved on that sample
- `極致壓縮`
  - about `23.2s` on `test_files/2024_ASHRAE_content.pdf`
  - about `57.8%` saved on that sample

This closes the optimize-copy portion of the first `B4` slice and shifts the next priority to open/page-change improvements.

## Success Criteria

- We ship at least one measured improvement for each target workflow:
  - open
  - page-change / render
  - optimize-copy
- We keep a stable baseline command set so later reruns are comparable.
- We do not regress correctness, undo safety, print behavior, or optimize-copy output validity while chasing speed.
- The final tracker update includes before/after numbers, not only qualitative claims.

## Scope

1. Make the baseline tooling reliable and repeatable.
2. Identify the highest-cost stages in the three target workflows.
3. Land small, measurable optimizations in separate commits where possible.
4. Re-run the same baselines and compare against the captured 2026-04-12 numbers.

## Out of Scope

- Broad speculative micro-optimization with no measurement path.
- Cross-machine benchmarking infrastructure.
- Full UI startup animation or splash-screen tuning unless it materially affects measured startup.

## Workstreams

### 1. Baseline tooling stabilization

- Keep `test_scripts/test_performance.py` runnable directly from repo root.
- Decide whether the optimize-copy baseline should use:
  - `test_scripts/benchmark_optimize_ab.py` for baseline-vs-worktree comparisons, or
  - a dedicated current-tree-only benchmark script for large-file timing
- Standardize the baseline fixture set:
  - synthetic large PDF for open/page render
  - `test_files/1.pdf` for fast optimize-copy sanity
  - `test_files/2024_ASHRAE_content.pdf` for large optimize-copy hotspot measurement

### 2. Open / page-change profiling

- Inspect the open path in:
  - `model/pdf_model.py`
  - any indexing/build-cache steps triggered during open
- Inspect page-render/page-change path:
  - `get_page_pixmap`
  - thumbnail/visible-page invalidation
  - page cache behavior
- Look for:
  - redundant indexing
  - repeated page object creation
  - overly eager full-document refreshes during page change

### 3. Optimize-copy profiling

- Focus first on the large-file case because that is the only currently demonstrated hotspot.
- Inspect:
  - `PDFModel.save_optimized_copy(...)`
  - `model/pdf_optimizer.py`
  - image rewrite selection and parallel path gating
  - unnecessary `doc.tobytes()` or duplicate temp-output work
- Use `test_scripts/benchmark_optimize_ab.py` when comparing against a baseline revision becomes useful.

## Proposed First Optimization Targets

1. Optimize-copy on large PDFs
   - highest evidence-backed hotspot today
   - likely best return on time
2. Page-change/render cache behavior
   - measured already, but still worth checking for avoidable churn
3. Open-path indexing and session setup
   - currently fast on the synthetic fixture, so optimize only if real files show a bottleneck

## Measurement Plan

Before each optimization batch:

- `python test_scripts/measure_startup_time.py`
- `python test_scripts/test_open_large_pdf.py --pages 300 --first-page`
- `python test_scripts/test_performance.py --rounds 10`
- ad-hoc page-render probe on pages `1`, `150`, `300`
- optimize-copy probe on:
  - `test_files/1.pdf`
  - `test_files/2024_ASHRAE_content.pdf`

After each optimization batch:

- Re-run the same commands
- Record deltas directly in the tracker/checklist/TODOs
- If optimize-copy changes touch file structure or image rewriting, also run:
  - `python -m pytest -q test_scripts/test_pdf_optimize_workflow.py`

## Risks

- Performance wins can accidentally trade correctness for speed, especially in optimize-copy.
- Synthetic fixtures may hide real bottlenecks, so at least one real-file probe must stay in the loop.
- Large optimize-copy changes may create memory regressions even if elapsed time improves.

## Exit Evidence

- Before/after timing table for:
  - startup
  - open
  - page-change / render
  - optimize-copy small sample
  - optimize-copy large sample
- Green targeted regression slices for any changed subsystems.
- Tracker updated so `B4` can move from `in_progress` to `done` only after the measured wins are shipped.
