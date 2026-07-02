# Setup Optimization — Phase 0 Baseline (2026-07-02)

Recorded before Phase 1 config changes (tag: `pre-optimization-2026-07-02`).

| Metric | Value | How measured |
|---|---|---|
| `ruff check .` violations | **91** | `ruff check . --output-format concise` (ruff default rules per pyproject) |
| pytest collected tests | **1590** | `.venv\Scripts\python.exe -m pytest --collect-only -q` |
| CLAUDE.md size | **8,068 bytes ≈ 2.0k tokens** | chars/4 estimate |
| Session-start doc reads (§4/§10 protocol) | ~75–115k tokens when followed | from audit plan |

Source plan: `~/.claude/plans/role-you-are-a-flickering-kettle.md`
Phases 0–1 executed 2026-07-02; Phases 2–5 pending.
