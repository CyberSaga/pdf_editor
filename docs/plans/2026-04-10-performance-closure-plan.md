# B4 Child Plan -- Performance Closure

## Goal

Close `B4` with measured speed improvements in the three backlog-critical workflows:

1. document open
2. page-change / page render
3. optimize-copy

## Baseline Snapshot (captured 2026-04-12)

- `measure_startup_time.py`: combined import + instantiate about `0.444s`
- `test_open_large_pdf.py --pages 300 --first-page`: open about `0.02s`, first page render about `8ms`
- `test_performance.py --rounds 10`: average about `0.034s`
- optimize-copy on `test_files/1.pdf` (`平衡`): about `0.087s`, about `21.8%` saved
- optimize-copy on `test_files/2024_ASHRAE_content.pdf` (`平衡`): exceeded the original `124s` timeout window

## Shipped Improvements

### Slice 1 -- preset-aware optimize-copy routing

- `快速`: about `15.6s` on `test_files/2024_ASHRAE_content.pdf`
- `平衡`: about `20.4s`, about `37.9%` saved
- `極致壓縮`: about `23.2s`, about `57.8%` saved

### Slice 2 -- open/page-change responsiveness

- controller now prioritizes the initial visible page before thumbnail/sidebar background work
- visible-render scheduling coalesces repeated page-change and viewport-triggered requests
- `benchmark_ui_open_render.py --path test_files/2024_ASHRAE_content.pdf`:
  - placeholders about `547ms`
  - initial visible page high-quality ready about `73ms`
  - far-page jump high-quality ready about `222ms`

## Closure Evidence (captured 2026-04-13)

- `measure_startup_time.py`: combined import + instantiate about `0.193s`
- `test_open_large_pdf.py --pages 300 --first-page`: open about `17-20ms`, first render about `6ms`
- `test_performance.py --rounds 10`: average about `0.020s`
- `benchmark_ui_open_render.py --path test_files/2024_ASHRAE_content.pdf`: placeholders about `547ms`, first visible page high-quality about `73ms`, far-page jump about `222ms`
- optimize-copy on `test_files/2024_ASHRAE_content.pdf`:
  - `快速`: about `15.6s`
  - `平衡`: about `20.4s`, about `37.9%` saved
  - `極致壓縮`: about `23.2s`, about `57.8%` saved

`measure_startup_time.py` still prints unrelated self-check noise, but it exits successfully and did not block timing capture.

## Final Decision

`B4` is closed.

The backlog requirement was “measured speed improvements ship for open, page-change, and optimize-copy.” That requirement is now met:

- open/page-change improvements are shipped and benchmarked
- optimize-copy improvements are shipped and benchmarked
- baseline and after-state numbers are captured in a stable command set

## Keep

- `test_scripts/measure_startup_time.py`
- `test_scripts/test_open_large_pdf.py`
- `test_scripts/test_performance.py`
- `test_scripts/benchmark_ui_open_render.py`

These remain the comparison set for future regressions.
