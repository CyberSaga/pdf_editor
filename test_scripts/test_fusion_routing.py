from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.fusion_runtime import (
    RiskLevel,
    Route,
    RouteDecision,
    TaskKind,
    apply_route_policy,
    parse_route_decision,
)


SCHEMA_DIR = Path(__file__).parents[1] / "scripts" / "fusion_schemas"


def test_router_schema_is_closed_and_requires_routing_fields():
    schema = json.loads((SCHEMA_DIR / "router.schema.json").read_text(encoding="utf-8"))

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "route",
        "risk_level",
        "task_kind",
        "reasons",
        "direct_answer",
        "panel_brief",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {
            "route": "direct",
            "risk_level": "low",
            "task_kind": "simple",
            "reasons": ["low-risk formatting"],
            "direct_answer": "Formatted result",
            "panel_brief": None,
        },
        {
            "route": "fusion",
            "risk_level": "high",
            "task_kind": "architecture",
            "reasons": ["irreversible design choice"],
            "direct_answer": None,
            "panel_brief": "Compare failure modes and migration risks",
        },
    ],
)
def test_parse_route_decision_accepts_valid_conditional_payloads(payload):
    decision = parse_route_decision(payload)

    assert decision.route.value == payload["route"]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "route": "direct",
            "risk_level": "low",
            "task_kind": "simple",
            "reasons": [],
            "direct_answer": None,
            "panel_brief": None,
        },
        {
            "route": "fusion",
            "risk_level": "high",
            "task_kind": "security",
            "reasons": ["high risk"],
            "direct_answer": "must be absent",
            "panel_brief": None,
        },
    ],
)
def test_parse_route_decision_rejects_invalid_conditional_payloads(payload):
    with pytest.raises(ValueError):
        parse_route_decision(payload)


@pytest.mark.parametrize(
    "kind",
    [
        TaskKind.ARCHITECTURE,
        TaskKind.MEDICAL,
        TaskKind.LEGAL,
        TaskKind.FINANCIAL,
        TaskKind.SECURITY,
    ],
)
def test_high_risk_kinds_force_fusion(kind):
    proposed = RouteDecision(
        route=Route.DIRECT,
        risk_level=RiskLevel.LOW,
        task_kind=kind,
        reasons=("model proposed direct",),
        direct_answer="unsafe shortcut",
    )

    actual = apply_route_policy(proposed, "Assess the decision")

    assert actual.route is Route.FUSION
    assert actual.direct_answer is None
    assert actual.panel_brief == "Assess the decision"


def test_force_fusion_overrides_low_risk_direct_route():
    proposed = RouteDecision(
        route=Route.DIRECT,
        risk_level=RiskLevel.LOW,
        task_kind=TaskKind.SIMPLE,
        reasons=("simple",),
        direct_answer="answer",
    )

    assert apply_route_policy(proposed, "task", force_fusion=True).route is Route.FUSION


def test_force_direct_is_diagnostic_override():
    proposed = RouteDecision(
        route=Route.FUSION,
        risk_level=RiskLevel.HIGH,
        task_kind=TaskKind.SECURITY,
        reasons=("high risk",),
        panel_brief="audit",
    )

    actual = apply_route_policy(proposed, "task", force_direct=True)

    assert actual.route is Route.DIRECT
    assert "diagnostic" in actual.reasons[-1]


def test_force_flags_are_mutually_exclusive():
    proposed = RouteDecision(
        route=Route.DIRECT,
        risk_level=RiskLevel.LOW,
        task_kind=TaskKind.SIMPLE,
        reasons=("simple",),
        direct_answer="answer",
    )

    with pytest.raises(ValueError, match="mutually exclusive"):
        apply_route_policy(proposed, "task", force_fusion=True, force_direct=True)
