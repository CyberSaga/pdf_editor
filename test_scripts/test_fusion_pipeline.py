from __future__ import annotations

import time
import typing

import pytest

from scripts.fusion_providers import ProviderResult
from scripts.fusion_runtime import (
    FusionPipeline,
    InsufficientCandidatesError,
    PanelCall,
    blinded_candidate_payload,
    run_panel,
    run_panel_detailed,
)


class CandidateAdapter:
    def __init__(self, provider: str, text: str, *, delay: float = 0, status: str = "ok"):
        self.provider = provider
        self.text = text
        self.delay = delay
        self.status = status
        self.calls = []

    def call(self, prompt: str, *, timeout: float) -> ProviderResult:
        self.calls.append((prompt, timeout))
        time.sleep(self.delay)
        return ProviderResult(
            provider=self.provider,
            status=self.status,
            command=(self.provider,),
            returncode=0 if self.status == "ok" else 1,
            stdout=self.text if self.status == "ok" else "",
            stderr="" if self.status == "ok" else self.status,
            duration_seconds=self.delay,
        )


def test_panel_runs_four_independent_candidates_concurrently():
    adapters = [
        CandidateAdapter("claude", "claude-a", delay=0.08),
        CandidateAdapter("claude", "claude-b", delay=0.08),
        CandidateAdapter("antigravity", "agy-a", delay=0.08),
        CandidateAdapter("antigravity", "agy-b", delay=0.08),
    ]
    calls = [PanelCall(adapter.provider, index, adapter) for index, adapter in enumerate(adapters)]

    started = time.monotonic()
    candidates = run_panel(calls, "shared prompt", timeout=2, seed=4)
    elapsed = time.monotonic() - started

    assert elapsed < 0.22
    assert len(candidates) == 4
    assert all(adapter.calls == [("shared prompt", 2)] for adapter in adapters)
    assert len({candidate.label for candidate in candidates}) == 4


def test_pipeline_type_hints_resolve_at_runtime():
    assert typing.get_type_hints(FusionPipeline.__init__)["schema_dir"] is not None


def test_blinded_payload_excludes_provider_identity():
    adapters = [CandidateAdapter("claude", "one"), CandidateAdapter("antigravity", "two")]
    calls = [PanelCall(adapter.provider, index, adapter) for index, adapter in enumerate(adapters)]

    payload = blinded_candidate_payload(run_panel(calls, "prompt", timeout=1, seed=1))

    assert payload == [
        {"candidate_id": "candidate-1", "response": "two"},
        {"candidate_id": "candidate-2", "response": "one"},
    ]
    assert "provider" not in str(payload).lower()


def test_panel_requires_two_usable_candidates():
    calls = [
        PanelCall("claude", 0, CandidateAdapter("claude", "only useful")),
        PanelCall("antigravity", 0, CandidateAdapter("antigravity", "", status="error")),
    ]

    with pytest.raises(InsufficientCandidatesError, match="at least two"):
        run_panel(calls, "prompt", timeout=1)


def test_panel_detailed_preserves_failed_attempt_metadata():
    calls = [
        PanelCall("claude", 0, CandidateAdapter("claude", "useful")),
        PanelCall("antigravity", 0, CandidateAdapter("antigravity", "", status="error")),
    ]

    panel = run_panel_detailed(calls, "prompt", timeout=1, seed=1)

    assert [(item.provider, item.sample, item.result.status) for item in panel.attempts] == [
        ("claude", 0, "ok"),
        ("antigravity", 0, "error"),
    ]
    assert len(panel.candidates) == 1


ROUTE_DIRECT = {
    "route": "direct",
    "risk_level": "low",
    "task_kind": "simple",
    "reasons": ["simple request"],
    "direct_answer": "Direct Codex answer",
    "panel_brief": None,
}
ROUTE_FUSION = {
    "route": "fusion",
    "risk_level": "high",
    "task_kind": "architecture",
    "reasons": ["architecture decision"],
    "direct_answer": None,
    "panel_brief": "Compare the architecture",
}
JUDGE = {
    "consensus": ["shared finding"],
    "contradictions": [],
    "unique_insights": ["candidate-1 adds detail"],
    "unsupported_claims": [],
    "missing_coverage": [],
    "recommended_outline": ["Decision", "Risks"],
}


class FakeCodex:
    def __init__(self, route=ROUTE_FUSION, judge=JUDGE, synthesis="Fused answer"):
        self.route = route
        self.judge = judge
        self.synthesis = synthesis
        self.calls = []

    def call_json(self, prompt, *, timeout, output_schema):
        self.calls.append(("json", output_schema.name, prompt, timeout))
        if output_schema.name == "router.schema.json":
            if isinstance(self.route, Exception):
                raise self.route
            return self.route
        if isinstance(self.judge, Exception):
            raise self.judge
        return self.judge

    def call(self, prompt, *, timeout, output_schema=None):
        self.calls.append(("text", None, prompt, timeout))
        if isinstance(self.synthesis, ProviderResult):
            return self.synthesis
        return ProviderResult("codex", "ok", ("codex",), 0, self.synthesis, "", 0.1)


def _panel_calls(*adapters):
    return [PanelCall(adapter.provider, index, adapter) for index, adapter in enumerate(adapters)]


def test_pipeline_returns_direct_codex_answer_without_panel(tmp_path):
    codex = FakeCodex(route=ROUTE_DIRECT)
    panel = CandidateAdapter("claude", "must not run")
    pipeline = FusionPipeline(codex, _panel_calls(panel), schema_dir=tmp_path)
    (tmp_path / "router.schema.json").write_text("{}", encoding="utf-8")
    (tmp_path / "judge.schema.json").write_text("{}", encoding="utf-8")

    outcome = pipeline.run("Format this", context="", timeout=1)

    assert outcome.status == "complete"
    assert outcome.route == "direct"
    assert outcome.final_answer == "Direct Codex answer"
    assert panel.calls == []


def test_pipeline_runs_panel_judge_and_separate_synthesizer(tmp_path):
    codex = FakeCodex()
    calls = _panel_calls(
        CandidateAdapter("claude", "Claude evidence"),
        CandidateAdapter("antigravity", "Antigravity evidence"),
    )
    pipeline = FusionPipeline(codex, calls, schema_dir=tmp_path)
    (tmp_path / "router.schema.json").write_text("{}", encoding="utf-8")
    (tmp_path / "judge.schema.json").write_text("{}", encoding="utf-8")

    outcome = pipeline.run("Choose architecture", context="facts", timeout=1)

    assert outcome.status == "complete"
    assert outcome.route == "fusion"
    assert outcome.final_answer == "Fused answer"
    assert [call[:2] for call in codex.calls] == [
        ("json", "router.schema.json"),
        ("json", "judge.schema.json"),
        ("text", None),
    ]
    synthesis_prompt = codex.calls[-1][2]
    assert "Claude evidence" in synthesis_prompt
    assert "Antigravity evidence" in synthesis_prompt
    assert "shared finding" in synthesis_prompt


def test_pipeline_degrades_to_claude_self_fusion_when_antigravity_fails(tmp_path):
    codex = FakeCodex()
    calls = _panel_calls(
        CandidateAdapter("claude", "Claude A"),
        CandidateAdapter("claude", "Claude B"),
        CandidateAdapter("antigravity", "", status="error"),
    )
    pipeline = FusionPipeline(codex, calls, schema_dir=tmp_path)
    (tmp_path / "router.schema.json").write_text("{}", encoding="utf-8")
    (tmp_path / "judge.schema.json").write_text("{}", encoding="utf-8")

    outcome = pipeline.run("Architecture", context="", timeout=1)

    assert outcome.status == "degraded"
    assert outcome.final_answer == "Fused answer"
    assert "antigravity" in " ".join(outcome.warnings).lower()


@pytest.mark.parametrize(
    ("codex", "expected_stage"),
    [
        (FakeCodex(judge=ValueError("judge broke")), "judge"),
        (
            FakeCodex(
                synthesis=ProviderResult("codex", "error", ("codex",), 1, "", "failed", 0.1)
            ),
            "synthesis",
        ),
    ],
)
def test_pipeline_stops_on_judge_or_synthesis_failure(tmp_path, codex, expected_stage):
    calls = _panel_calls(
        CandidateAdapter("claude", "one"),
        CandidateAdapter("antigravity", "two"),
    )
    pipeline = FusionPipeline(codex, calls, schema_dir=tmp_path)
    (tmp_path / "router.schema.json").write_text("{}", encoding="utf-8")
    (tmp_path / "judge.schema.json").write_text("{}", encoding="utf-8")

    outcome = pipeline.run("Architecture", context="", timeout=1)

    assert outcome.status == "failed"
    assert outcome.final_answer is None
    assert expected_stage in outcome.errors[0]


def test_pipeline_marks_call_id_leak_as_degraded_verification(tmp_path):
    codex = FakeCodex(synthesis="Leaked [FUSION_CALL_ID:secret]")
    calls = _panel_calls(
        CandidateAdapter("claude", "one"),
        CandidateAdapter("antigravity", "two"),
    )
    pipeline = FusionPipeline(codex, calls, schema_dir=tmp_path)
    (tmp_path / "router.schema.json").write_text("{}", encoding="utf-8")
    (tmp_path / "judge.schema.json").write_text("{}", encoding="utf-8")

    outcome = pipeline.run("Architecture", context="", timeout=1)

    assert outcome.status == "degraded"
    assert "call ID" in outcome.verification_errors[0]
