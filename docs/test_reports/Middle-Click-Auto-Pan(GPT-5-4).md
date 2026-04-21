● Code Review — Middle-Click Auto-Pan

  Verdict: implementation faithfully matches the plan's design intent. All logic works. Tests pass (6/6 autopan, 545/545
  broader suite), no new lint violations. Main gap is process compliance (no commits + missing red-light log). Two minor
  test-quality issues worth addressing before merge.

  ---
  ✅ Plan coverage

| Plan item | Status | Notes |
|-----------|--------|-------|
| State fields + constants | ✅ | All 9 fields + 3 constants match plan exactly (view/pdf_view.py:137–139, 345–357) |
| _enter/_exit/_tick helpers | ✅ | Implement plan logic verbatim, including _finalize_text_edit() guard and Qt.SizeAllCursor (view/pdf_view.py:2433–2489) |
| _mouse_press routing (overlay first, middle→enter, any→exit, right→menu) | ✅ | view/pdf_view.py:2491–2504 |
| _mouse_move cursor tracking | ✅ | view/pdf_view.py:2700–2704 |
| _mouse_release swallow | ✅ | view/pdf_view.py:3717–3720 |
| Context-menu double-pop guard (_autopan_suppress_next_context_menu + _autopan_manual_menu + _show_context_menu_manual) | ✅ | view/pdf_view.py:4035–4047 |
| Docs (ARCHITECTURE.md, PITFALLS.md, TODOS.md) | ✅ | All three updated, pitfall entry follows required format |
| No cross-layer violation | ✅ | View touches only its own scrollbars/viewport |
| Ruff | ✅ | 7 pre-existing errors in worktree = 7 in main; no new violations |

  🟡 Deviations from plan (acceptable)

  - Bonus helper _event_viewport_pos (view/pdf_view.py:2421-2431) — not in plan but a clean DRY extraction. Good.
  - Synchronous context-menu call instead of QTimer.singleShot(0, ...) — works correctly because the suppression flag
  catches the later signal. Simpler than planned; acceptable.
  - Test file at test_scripts/test_autopan.py (not tests/view/...) — correct adaptation: the real project uses
  test_scripts/, not tests/.

  🔴 Process gaps (must address before merge)

  1. No commits. All changes are unstaged. CLAUDE.md §5.1 requires a failing-test log before implementation and §7 requires
  commits per task. Break the work into at least two commits (test-first, then implementation + docs).
  2. No red-light evidence. Since nothing was committed, there's no proof the tests failed before the implementation
  existed. Cannot verify TDD order.

  🟡 Test quality issues

  1. Tests bypass __init__ — use PDFView.__new__(PDFView) with hand-built fakes. Fast, but won't catch wiring regressions
  (e.g., forgetting to connect _autopan_timer.timeout). The plan called for PDFView(defer_heavy_panels=True) + qtbot.
  Mitigation: run the plan's 8-step manual verification before merge.
  2. Missing test_autopan_speed_scales_with_distance (plan's test #6). The existing fractional-accumulation test asserts
  step math at one distance, but does not verify that a far cursor scrolls strictly faster than a near cursor. Worth adding
  — small test, high signal.
  3. Brittle assertion in test_context_menu_manual_bypasses_single_signal_suppression: assert "另存PDF" in labels couples
  the test to the browse-mode menu contents. The test's actual intent is the suppression/bypass logic; recommend assert
  len(labels) > 0 or asserting on menu-was-shown via a flag.

  🟡 Dead-code nit

  _mouse_release's if self._autopan_active: return guard (view/pdf_view.py:3718-3720) is effectively unreachable — by the
  time a release fires, the paired press has already called _exit_autopan(). Harmless defensive coding; consider adding a
  comment or removing.