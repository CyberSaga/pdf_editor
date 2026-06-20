"""Selective subscription Fusion: Codex direct, or Claude + Antigravity with Codex synthesis."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.fusion_providers import (
    AntigravityAdapter,
    ClaudeAdapter,
    CodexAdapter,
    validate_subscription_environment,
)
from scripts.fusion_runtime import FusionPipeline, PanelCall, PipelineOutcome


SCHEMA_DIR = Path(__file__).with_name("fusion_schemas")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="Task for Codex direct routing or selective Fusion")
    parser.add_argument("--file", "-f", action="append", type=Path, default=[])
    parser.add_argument("--stdin", action="store_true", help="Read additional untrusted context")
    parser.add_argument("--timeout", type=float, default=180.0, help="Seconds per model call")
    parser.add_argument("--out-dir", type=Path, default=Path(".fusion-runs"))
    parser.add_argument(
        "--panel-profile",
        choices=("standard", "lean"),
        default="standard",
        help="standard=2 Claude + 2 Antigravity; lean=1 of each",
    )
    route = parser.add_mutually_exclusive_group()
    route.add_argument("--force-fusion", action="store_true")
    route.add_argument("--force-direct", action="store_true", help="Diagnostic override")
    return parser


def build_context(files: Sequence[Path], stdin_context: str) -> str:
    parts: list[str] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ValueError(f"Could not read {path}: {exc}") from exc
        parts.extend(
            [
                f"--- BEGIN UNTRUSTED FILE: {path} ---",
                content,
                f"--- END UNTRUSTED FILE: {path} ---",
            ]
        )
    if stdin_context.strip():
        parts.extend(
            [
                "--- BEGIN UNTRUSTED STDIN ---",
                stdin_context,
                "--- END UNTRUSTED STDIN ---",
            ]
        )
    return "\n".join(parts)


def panel_calls_for_profile(
    profile: str,
    *,
    claude_adapter,
    antigravity_adapter,
) -> list[PanelCall]:
    samples = 2 if profile == "standard" else 1
    return [
        *[PanelCall("claude", index, claude_adapter) for index in range(samples)],
        *[PanelCall("antigravity", index, antigravity_adapter) for index in range(samples)],
    ]


def resolve_executable(
    name: str, *, environment: Mapping[str, str] | None = None
) -> str | None:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    active = os.environ if environment is None else environment
    if name == "agy" and active.get("LOCALAPPDATA"):
        candidate = Path(active["LOCALAPPDATA"]) / "agy" / "bin" / "agy.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def build_live_pipeline(profile: str) -> FusionPipeline:
    codex = resolve_executable("codex")
    if not codex:
        raise ValueError("`codex` was not found on PATH")
    claude = ClaudeAdapter(resolve_executable("claude") or "claude")
    antigravity = AntigravityAdapter(resolve_executable("agy") or "agy")
    calls = panel_calls_for_profile(
        profile,
        claude_adapter=claude,
        antigravity_adapter=antigravity,
    )
    return FusionPipeline(CodexAdapter(codex), calls, schema_dir=SCHEMA_DIR)


def _jsonable(value):
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_jsonable),
        encoding="utf-8",
    )


def write_artifacts(
    run_dir: Path,
    task: str,
    context: str,
    outcome: PipelineOutcome,
) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "request.md").write_text(
        f"# Trusted Task\n\n{task}\n\n# Untrusted Context\n\n{context}\n",
        encoding="utf-8",
    )
    route_payload = {
        "status": outcome.status,
        "route": outcome.route,
        "decision": asdict(outcome.decision) if outcome.decision else None,
        "warnings": list(outcome.warnings),
        "errors": list(outcome.errors),
    }
    _write_json(run_dir / "route.json", route_payload)
    for attempt in outcome.attempts:
        metadata = {
            "provider": attempt.provider,
            "sample": attempt.sample,
            "status": attempt.result.status,
            "returncode": attempt.result.returncode,
            "duration_seconds": attempt.result.duration_seconds,
            "stderr": attempt.result.stderr,
            "source_path": attempt.result.source_path,
        }
        _write_json(
            run_dir / f"attempt-{attempt.provider}-{attempt.sample}.json",
            metadata,
        )
    for candidate in outcome.candidates:
        metadata = {
            "candidate_id": candidate.label,
            "provider": candidate.provider,
            "sample": candidate.sample,
            "status": candidate.result.status,
            "returncode": candidate.result.returncode,
            "duration_seconds": candidate.result.duration_seconds,
            "stderr": candidate.result.stderr,
            "source_path": candidate.result.source_path,
        }
        _write_json(run_dir / f"{candidate.label}.json", metadata)
        (run_dir / f"{candidate.label}.md").write_text(
            candidate.result.stdout, encoding="utf-8"
        )
    if outcome.judge is not None:
        _write_json(run_dir / "judge.json", outcome.judge)
    if outcome.final_answer is not None:
        (run_dir / "synthesis.md").write_text(outcome.final_answer, encoding="utf-8")
    _write_json(
        run_dir / "verification.json",
        {"errors": list(outcome.verification_errors)},
    )
    report_lines = [
        "# Subscription Fusion Report",
        "",
        f"Status: {outcome.status}",
        f"Route: {outcome.route}",
    ]
    if outcome.warnings:
        report_lines.extend(["", "## Warnings", *[f"- {item}" for item in outcome.warnings]])
    if outcome.errors:
        report_lines.extend(["", "## Errors", *[f"- {item}" for item in outcome.errors]])
    if outcome.verification_errors:
        report_lines.extend(
            ["", "## Verification", *[f"- {item}" for item in outcome.verification_errors]]
        )
    if outcome.final_answer is not None:
        report_lines.extend(["", "## Final Answer", "", outcome.final_answer])
    report = run_dir / "report.md"
    report.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return report


def exit_code_for_status(status: str) -> int:
    return {"complete": 0, "degraded": 3, "failed": 6}.get(status, 6)


def _new_run_dir(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return root / f"fusion-{stamp}-{uuid.uuid4().hex[:6]}"


def main(
    argv: Sequence[str] | None = None,
    *,
    pipeline_factory: Callable[[str], FusionPipeline] = build_live_pipeline,
    environment: Mapping[str, str] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    active_environment = os.environ if environment is None else environment
    try:
        if args.timeout <= 0:
            raise ValueError("--timeout must be greater than zero")
        validate_subscription_environment(active_environment)
        stdin_context = sys.stdin.read() if args.stdin and not sys.stdin.isatty() else ""
        context = build_context(args.file, stdin_context)
        pipeline = pipeline_factory(args.panel_profile)
        outcome = pipeline.run(
            args.prompt,
            context=context,
            timeout=args.timeout,
            force_fusion=args.force_fusion,
            force_direct=args.force_direct,
        )
    except ValueError as exc:
        print(f"[fusion] {exc}", file=sys.stderr)
        return 2
    report = write_artifacts(_new_run_dir(args.out_dir), args.prompt, context, outcome)
    print(report)
    return exit_code_for_status(outcome.status)


if __name__ == "__main__":
    raise SystemExit(main())
