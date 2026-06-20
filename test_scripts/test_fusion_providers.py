from __future__ import annotations

from pathlib import Path

import pytest

from scripts.fusion_providers import (
    API_KEY_VARIABLES,
    AntigravityAdapter,
    ClaudeAdapter,
    CodexAdapter,
    ExecResult,
    SubprocessExecutor,
    validate_subscription_environment,
)


class FakeExecutor:
    def __init__(self, result: ExecResult):
        self.result = result
        self.calls = []

    def run(self, command, input_text, timeout, environment):
        self.calls.append((command, input_text, timeout, environment))
        return self.result


@pytest.mark.parametrize("name", sorted(API_KEY_VARIABLES))
def test_subscription_environment_rejects_every_provider_api_key(name: str):
    with pytest.raises(ValueError, match=name):
        validate_subscription_environment({name: "secret"})


def test_codex_adapter_uses_ephemeral_read_only_exec_and_stdin(tmp_path: Path):
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    executor = FakeExecutor(ExecResult(0, '{"route":"direct"}', "", 0.2))
    adapter = CodexAdapter("C:/bin/codex.exe", executor, base_environment={"PATH": "bin"})

    result = adapter.call("classify this", timeout=12, output_schema=schema)

    command, input_text, timeout, environment = executor.calls[0]
    assert command == [
        "C:/bin/codex.exe",
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--output-schema",
        str(schema),
        "-",
    ]
    assert input_text == "classify this"
    assert timeout == 12
    assert environment == {"PATH": "bin"}
    assert result.usable


def test_codex_adapter_removes_api_keys_from_child_environment():
    executor = FakeExecutor(ExecResult(0, "answer", "", 0.1))
    environment = {"PATH": "bin", **{name: "secret" for name in API_KEY_VARIABLES}}
    adapter = CodexAdapter("codex", executor, base_environment=environment)

    adapter.call("prompt", timeout=1)

    child_environment = executor.calls[0][3]
    assert not API_KEY_VARIABLES.intersection(child_environment)


def test_codex_adapter_rejects_empty_success_output():
    adapter = CodexAdapter(
        "codex",
        FakeExecutor(ExecResult(0, "  ", "progress only", 0.1)),
        base_environment={},
    )

    result = adapter.call("prompt", timeout=1)

    assert result.status == "error"
    assert not result.usable


def test_codex_adapter_classifies_auth_failure():
    adapter = CodexAdapter(
        "codex",
        FakeExecutor(ExecResult(1, "", "Please login to Codex", 0.1)),
        base_environment={},
    )

    assert adapter.call("prompt", timeout=1).status == "auth"


def test_codex_adapter_parses_structured_json(tmp_path: Path):
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    adapter = CodexAdapter(
        "codex",
        FakeExecutor(ExecResult(0, '{"answer": 42}', "", 0.1)),
        base_environment={},
    )

    assert adapter.call_json("prompt", timeout=1, output_schema=schema) == {"answer": 42}


def test_codex_adapter_rejects_invalid_structured_json(tmp_path: Path):
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    adapter = CodexAdapter(
        "codex",
        FakeExecutor(ExecResult(0, "not json", "", 0.1)),
        base_environment={},
    )

    with pytest.raises(ValueError, match="valid JSON"):
        adapter.call_json("prompt", timeout=1, output_schema=schema)


def test_antigravity_adapter_recovers_empty_stdout_from_matching_transcript(tmp_path: Path):
    brain = tmp_path / "brain"

    class TranscriptWritingExecutor:
        def run(self, command, input_text, timeout, environment):
            transcript = brain / "conversation" / ".system_generated" / "logs" / "transcript_full.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(
                '\n'.join(
                    [
                        '{"step_index":0,"source":"USER_EXPLICIT","type":"USER_INPUT","status":"DONE","content":"[FUSION_CALL_ID:fixed-call]"}',
                        '{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","status":"DONE","content":"Recovered answer"}',
                    ]
                ),
                encoding="utf-8",
            )
            self.call = (command, input_text, timeout, environment)
            return ExecResult(0, "", "", 0.2)

    executor = TranscriptWritingExecutor()
    adapter = AntigravityAdapter(
        "C:/bin/agy.exe",
        executor,
        brain_root=brain,
        base_environment={"PATH": "bin"},
        call_id_factory=lambda: "fixed-call",
    )

    result = adapter.call("Review this", timeout=12)

    command, input_text, timeout, environment = executor.call
    assert command[:5] == [
        "C:/bin/agy.exe",
        "--sandbox",
        "--print-timeout",
        "12s",
        "--print",
    ]
    assert "[FUSION_CALL_ID:fixed-call]" in command[-1]
    assert "Do not use tools" in command[-1]
    assert input_text == ""
    assert timeout == 12
    assert environment == {"PATH": "bin"}
    assert result.stdout == "Recovered answer"
    assert result.source_path.endswith("transcript_full.jsonl")


def test_antigravity_adapter_prefers_future_nonempty_stdout(tmp_path: Path):
    adapter = AntigravityAdapter(
        "agy",
        FakeExecutor(ExecResult(0, "Native stdout", "", 0.1)),
        brain_root=tmp_path,
        base_environment={},
        call_id_factory=lambda: "call",
    )

    result = adapter.call("prompt", timeout=1)

    assert result.usable
    assert result.stdout == "Native stdout"
    assert result.source_path is None


def test_antigravity_default_executor_uses_neutral_temp_workspace(tmp_path: Path):
    adapter = AntigravityAdapter(
        "agy",
        brain_root=tmp_path / "brain",
        base_environment={"TEMP": str(tmp_path)},
    )

    assert isinstance(adapter.executor, SubprocessExecutor)
    assert adapter.executor.working_directory == tmp_path / "fusion-antigravity-workspace"
    assert adapter.executor.working_directory.is_dir()


def test_antigravity_adapter_fails_when_stdout_and_transcript_are_missing(tmp_path: Path):
    adapter = AntigravityAdapter(
        "agy",
        FakeExecutor(ExecResult(0, "", "", 0.1)),
        brain_root=tmp_path,
        base_environment={},
        call_id_factory=lambda: "missing",
    )

    result = adapter.call("prompt", timeout=1)

    assert result.status == "error"
    assert "transcript" in result.stderr.lower()


def test_claude_adapter_uses_subscription_read_only_print_mode_and_stdin():
    executor = FakeExecutor(ExecResult(0, "Claude answer", "", 0.2))
    adapter = ClaudeAdapter("C:/bin/claude.exe", executor, base_environment={"PATH": "bin"})

    result = adapter.call("Review this", timeout=9)

    command, input_text, timeout, environment = executor.calls[0]
    assert command == [
        "C:/bin/claude.exe",
        "-p",
        "--tools",
        "",
        "--permission-mode",
        "plan",
        "--no-session-persistence",
        "--output-format",
        "text",
    ]
    assert input_text == "Review this"
    assert timeout == 9
    assert environment == {"PATH": "bin"}
    assert result.usable


def test_claude_adapter_rejects_empty_output():
    adapter = ClaudeAdapter(
        "claude",
        FakeExecutor(ExecResult(0, "", "", 0.1)),
        base_environment={},
    )

    assert adapter.call("prompt", timeout=1).status == "error"
