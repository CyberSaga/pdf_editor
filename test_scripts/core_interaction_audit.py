from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Status = str


@dataclass(frozen=True)
class AuditFixture:
    role: str
    path: Path
    description: str


@dataclass(frozen=True)
class AuditScenario:
    id: str
    title: str
    category: str
    execution: str
    phase: str
    fixture_roles: tuple[str, ...]
    details: str
    automation_target: str | None = None
    blocked_reason: str | None = None
    mouse_keyboard_steps: tuple[str, ...] = ()
    expected_visible_result: str | None = None
    expected_persisted_result: str | None = None


@dataclass(frozen=True)
class AuditPlan:
    fixtures: tuple[AuditFixture, ...]
    scenarios: tuple[AuditScenario, ...]


@dataclass(frozen=True)
class AuditScenarioResult:
    scenario_id: str
    status: Status
    details: str


@dataclass(frozen=True)
class AuditReport:
    plan: AuditPlan
    results: tuple[AuditScenarioResult, ...]


def _relative_path(path: Path) -> str:
    try:
        repo_root = Path(__file__).resolve().parents[1]
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def default_core_interaction_plan(repo_root: Path) -> AuditPlan:
    fixtures = (
        AuditFixture(
            role="small_clean",
            path=repo_root / "test_files" / "1.pdf",
            description="Small clean fixture for deterministic reruns.",
        ),
        AuditFixture(
            role="long_real_world",
            path=repo_root / "test_files" / "TIA-942-B-2017 Rev Full.pdf",
            description="Long real-world fixture for navigation and sustained interaction checks.",
        ),
        AuditFixture(
            role="edge_case",
            path=repo_root / "test_files" / "excel_table.pdf",
            description="Mixed-layout fixture for table-like text/layout behavior.",
        ),
    )

    scenarios = (
        AuditScenario(
            id="internal.noop_finalize",
            title="No-op finalize should not emit a ghost edit",
            category="edit_recovery",
            execution="automated",
            phase="phase1",
            fixture_roles=("small_clean",),
            details="Reuse GUI regression coverage for normalized no-op finalize behavior.",
            automation_target="test_scripts/test_text_editing_gui_regressions.py::test_finalize_skips_emit_for_normalized_noop_edit",
        ),
        AuditScenario(
            id="internal.escape_discard",
            title="Escape path marks the active editor as discard-before-finalize",
            category="keyboard_recovery",
            execution="automated",
            phase="phase1",
            fixture_roles=("small_clean",),
            details="Reuse GUI regression coverage for the internal Escape delivery path.",
            automation_target="test_scripts/test_text_editing_gui_regressions.py::test_escape_marks_current_editor_as_discard_before_finalize",
        ),
        AuditScenario(
            id="internal.local_undo_redo",
            title="Local editor undo/redo stays local while the editor is open",
            category="keyboard_recovery",
            execution="automated",
            phase="phase1",
            fixture_roles=("small_clean",),
            details="Reuse GUI regression coverage for editor shortcut forwarding.",
            automation_target="test_scripts/test_text_editing_gui_regressions.py::test_editor_shortcut_forwarder_uses_local_undo_redo_history",
        ),
        AuditScenario(
            id="internal.cross_page_move",
            title="Cross-page move writes once and remains undoable",
            category="edit_recovery",
            execution="automated",
            phase="phase1",
            fixture_roles=("edge_case",),
            details="Reuse controller regression coverage for cross-page move persistence and undo/redo.",
            automation_target="test_scripts/test_cross_page_text_move.py::test_move_text_across_pages_records_single_snapshot_command_and_undoes",
        ),
        AuditScenario(
            id="manual.open_and_navigation",
            title="Open, tab-switch, scroll, jump, and zoom remain smooth",
            category="navigation",
            execution="manual",
            phase="phase1",
            fixture_roles=("small_clean", "long_real_world"),
            details="Human-run protocol for interaction spine behavior that is hard to capture honestly with a thin harness.",
            blocked_reason="Requires manual screen operation and timing notes.",
            mouse_keyboard_steps=(
                "Launch the app and open `test_files/1.pdf`.",
                "Use mouse navigation to switch tabs, scroll, and jump between pages.",
                "Use zoom in, zoom out, and fit-to-view, then continue scrolling immediately.",
                "Repeat the same flow on `test_files/TIA-942-B-2017 Rev Full.pdf` and note hesitation, focus loss, or visible jank.",
            ),
            expected_visible_result="Navigation remains stable with no surprise focus jumps, stale page counter, or obvious scroll/zoom hitching.",
        ),
        AuditScenario(
            id="manual.selection_save_close",
            title="Selection, copy, save, close-with-dirty-prompt, and reopen confidence",
            category="persistence",
            execution="manual",
            phase="phase1",
            fixture_roles=("small_clean", "edge_case"),
            details="Human-run protocol for confidence and recovery flows around persistence.",
            blocked_reason="Requires manual keyboard/mouse validation and post-save inspection.",
            mouse_keyboard_steps=(
                "Open `test_files/1.pdf` and select visible text with the mouse.",
                "Use keyboard copy, start a text edit, then trigger save and close flows with the keyboard.",
                "Confirm the dirty prompt appears with the expected options, save the document, reopen it, and verify the edited result.",
                "Repeat a shorter version on `test_files/excel_table.pdf` to confirm the same persistence behavior on the edge-case fixture.",
            ),
            expected_visible_result="Selection, save, dirty prompt, reopen, and recovery flows feel predictable and do not trap focus.",
            expected_persisted_result="Saved output reopens with the intended text change and without ghost edits or reverted state.",
        ),
        AuditScenario(
            id="acrobat.core_parity",
            title="Run the same core interaction protocol against Acrobat",
            category="acrobat_baseline",
            execution="acrobat",
            phase="phase2",
            fixture_roles=("small_clean", "long_real_world", "edge_case"),
            details="Reserved parity phase for the same scenarios on Acrobat.",
            blocked_reason="Blocked until a machine with Adobe Acrobat is available.",
        ),
    )
    return AuditPlan(fixtures=fixtures, scenarios=scenarios)


def _default_blocked_details(scenario: AuditScenario) -> str:
    if scenario.blocked_reason:
        return scenario.blocked_reason
    if scenario.execution == "manual":
        return "Requires manual operator execution."
    if scenario.execution == "acrobat":
        return "Blocked until Acrobat baseline is available."
    return "Blocked."


def run_audit_plan(
    plan: AuditPlan,
    *,
    automated_executor: Callable[[AuditScenario], AuditScenarioResult],
) -> AuditReport:
    results: list[AuditScenarioResult] = []
    for scenario in plan.scenarios:
        if scenario.execution == "automated":
            results.append(automated_executor(scenario))
            continue
        results.append(
            AuditScenarioResult(
                scenario_id=scenario.id,
                status="BLOCKED",
                details=_default_blocked_details(scenario),
            )
        )
    return AuditReport(plan=plan, results=tuple(results))


def render_markdown_report(report: AuditReport) -> str:
    fixture_lines = []
    for fixture in report.plan.fixtures:
        fixture_lines.append(
            f"- `{fixture.role}`: `{_relative_path(fixture.path)}` - {fixture.description}"
        )

    result_map = {result.scenario_id: result for result in report.results}
    scenario_lines = []
    for scenario in report.plan.scenarios:
        result = result_map[scenario.id]
        scenario_lines.append(
            f"- `{scenario.id}` | {result.status} | {scenario.title} | {result.details}"
        )

    pass_count = sum(1 for result in report.results if result.status == "PASS")
    fail_count = sum(1 for result in report.results if result.status == "FAIL")
    blocked_count = sum(1 for result in report.results if result.status == "BLOCKED")

    return "\n".join(
        [
            "# Core Interaction UX Audit Report",
            "",
            "## Summary",
            f"- PASS: {pass_count}",
            f"- FAIL: {fail_count}",
            f"- BLOCKED: {blocked_count}",
            "",
            "## Fixture Matrix",
            *fixture_lines,
            "",
            "## Scenario Results",
            *scenario_lines,
            "",
            "## Notes",
            "- `BLOCKED` is expected for manual and Acrobat-only scenarios in the thin-harness phase.",
            "- Acrobat parity remains blocked until a machine with Acrobat is available.",
        ]
    )


def render_manual_checklist(plan: AuditPlan) -> str:
    fixture_map = {fixture.role: _relative_path(fixture.path) for fixture in plan.fixtures}
    sections: list[str] = [
        "# Core Interaction Manual Operator Checklist",
        "",
        "Use this checklist for the Phase 1 manual screen-operation pass.",
        "Record timings, hesitation points, visible glitches, and whether the persisted PDF matches the visible result.",
        "",
    ]

    manual_scenarios = [scenario for scenario in plan.scenarios if scenario.execution == "manual"]
    for scenario in manual_scenarios:
        sections.extend(
            [
                f"## {scenario.id} - {scenario.title}",
                "",
                f"- Fixtures: {', '.join(f'`{fixture_map[role]}`' for role in scenario.fixture_roles)}",
                f"- Mouse/Keyboard Steps: {' '.join(scenario.mouse_keyboard_steps)}",
                f"- Expected Visible Result: {scenario.expected_visible_result or scenario.details}",
                f"- Expected Persisted Result: {scenario.expected_persisted_result or 'N/A for this scenario.'}",
                "",
            ]
        )
    return "\n".join(sections)


def _run_pytest_target(scenario: AuditScenario) -> AuditScenarioResult:
    if not scenario.automation_target:
        return AuditScenarioResult(
            scenario_id=scenario.id,
            status="FAIL",
            details="No automation target configured.",
        )

    env = dict(**__import__("os").environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("PYTHONPATH", ".")
    command = [sys.executable, "-m", "pytest", "-q", scenario.automation_target]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode == 0:
        return AuditScenarioResult(
            scenario_id=scenario.id,
            status="PASS",
            details=f"Automated check passed via `{scenario.automation_target}`.",
        )
    return AuditScenarioResult(
        scenario_id=scenario.id,
        status="FAIL",
        details=f"Automated check failed via `{scenario.automation_target}`: {output}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the core interaction UX audit harness.")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("test_scripts") / "test_outputs" / "core_interaction_audit.md",
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--manual-checklist",
        type=Path,
        default=Path("test_scripts") / "test_outputs" / "core_interaction_manual_checklist.md",
        help="Manual operator checklist output path.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    plan = default_core_interaction_plan(repo_root)
    report = run_audit_plan(plan, automated_executor=_run_pytest_target)
    markdown = render_markdown_report(report)
    checklist = render_manual_checklist(plan)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(markdown, encoding="utf-8")
    args.manual_checklist.parent.mkdir(parents=True, exist_ok=True)
    args.manual_checklist.write_text(checklist, encoding="utf-8")
    print(markdown)
    return 0 if all(result.status != "FAIL" for result in report.results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
