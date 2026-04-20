from __future__ import annotations

from pathlib import Path

from test_scripts.core_interaction_audit import (
    AuditPlan,
    AuditScenario,
    AuditScenarioResult,
    default_core_interaction_plan,
    render_manual_checklist,
    render_markdown_report,
    run_audit_plan,
)


def test_default_core_interaction_plan_uses_three_existing_fixtures() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    plan = default_core_interaction_plan(repo_root)

    assert isinstance(plan, AuditPlan)
    assert len(plan.fixtures) == 3
    assert [fixture.role for fixture in plan.fixtures] == ["small_clean", "long_real_world", "edge_case"]
    assert all(fixture.path.exists() for fixture in plan.fixtures)


def test_default_core_interaction_plan_includes_automated_manual_and_acrobat_scenarios() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    plan = default_core_interaction_plan(repo_root)
    execution_modes = {scenario.execution for scenario in plan.scenarios}

    assert execution_modes == {"automated", "manual", "acrobat"}
    assert any(scenario.phase == "phase1" and scenario.execution == "automated" for scenario in plan.scenarios)
    assert any(scenario.phase == "phase1" and scenario.execution == "manual" for scenario in plan.scenarios)
    assert any(scenario.phase == "phase2" and scenario.execution == "acrobat" for scenario in plan.scenarios)


def test_run_audit_plan_marks_non_automated_scenarios_blocked() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    plan = default_core_interaction_plan(repo_root)

    seen_ids: list[str] = []

    def fake_executor(scenario: AuditScenario) -> AuditScenarioResult:
        seen_ids.append(scenario.id)
        return AuditScenarioResult(scenario_id=scenario.id, status="PASS", details="ok")

    report = run_audit_plan(plan, automated_executor=fake_executor)

    automated_ids = {scenario.id for scenario in plan.scenarios if scenario.execution == "automated"}
    assert set(seen_ids) == automated_ids

    by_id = {result.scenario_id: result for result in report.results}
    for scenario in plan.scenarios:
        result = by_id[scenario.id]
        if scenario.execution == "automated":
            assert result.status == "PASS"
        else:
            assert result.status == "BLOCKED"
            assert result.details


def test_render_markdown_report_includes_summary_and_blockers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    plan = default_core_interaction_plan(repo_root)

    report = run_audit_plan(
        plan,
        automated_executor=lambda scenario: AuditScenarioResult(
            scenario_id=scenario.id,
            status="PASS",
            details=f"executed {scenario.id}",
        ),
    )

    markdown = render_markdown_report(report)

    assert "# Core Interaction UX Audit Report" in markdown
    assert "## Fixture Matrix" in markdown
    assert "## Scenario Results" in markdown
    assert "BLOCKED" in markdown
    assert "Acrobat" in markdown
    assert "C:/Users/" not in markdown
    assert "test_files/1.pdf" in markdown


def test_render_manual_checklist_includes_manual_steps_and_relative_fixture_paths() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    plan = default_core_interaction_plan(repo_root)

    checklist = render_manual_checklist(plan)

    assert "# Core Interaction Manual Operator Checklist" in checklist
    assert "manual.open_and_navigation" in checklist
    assert "manual.selection_save_close" in checklist
    assert "acrobat.core_parity" not in checklist
    assert "C:/Users/" not in checklist
    assert "test_files/1.pdf" in checklist
    assert "Mouse/Keyboard Steps" in checklist
    assert "Expected Visible Result" in checklist
