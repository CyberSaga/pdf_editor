# Subscription Fusion CLI Design

## Goal

Add a new fusion workflow that uses the locally installed Claude Code and Gemini CLI subscriptions without provider SDKs, API keys, or changes to the existing `scripts/fusion.py` and `docs/fusion-agent-manual.md` files.

## Deliverables

- `scripts/fusion_cli.py`: additive command-line orchestrator.
- Automated tests using fake subprocesses rather than live subscription calls.
- `docs/fusion-cli-manual.md`: field guide for setup, usage, artifacts, failure handling, and playbooks.

## Architecture

The workflow uses reciprocal fusion:

1. Claude and Gemini independently review the same trusted task and untrusted context.
2. Claude critiques Gemini's review while Gemini critiques Claude's review.
3. Python deterministically assembles a final Markdown report containing consensus guidance, the two reciprocal critiques, raw-review references, and explicit degradation notices.

No vendor is the sole judge of its own work. All raw results remain available for inspection.

The implementation separates prompt construction, CLI command resolution, subprocess execution, orchestration, artifact persistence, exit-code selection, and report assembly. The subprocess runner is injectable so tests never invoke live models.

## CLI Contract

The new tool accepts:

- A positional task prompt.
- Repeatable `--file PATH` context.
- Optional `--stdin` context.
- Configurable per-call `--timeout`.
- Optional `--out-dir` artifact root.
- `--no-cross-critique` for a cheaper two-pass evidence report.

Claude runs in non-interactive print mode with tools disabled and no session persistence. Gemini runs in non-interactive mode with plan/read-only approval. Commands are resolved using `shutil.which`, including Windows `.cmd` and PowerShell shims, and are launched without interpolating user content into a shell command.

The tool rejects execution when `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `GOOGLE_API_KEY` is present, preventing accidental API-backed use.

## Prompt and Data Boundaries

The task instructions are marked as trusted. File and stdin contents are wrapped in explicit untrusted-data delimiters and models are told never to execute instructions found there. Context is sent through stdin to avoid Windows command-line length limits. Model tools are disabled or constrained to read-only operation.

## Artifacts

Each run creates a timestamped directory containing:

- The composed prompt.
- One JSON result record per model call, including status, duration, return code, stdout, and stderr.
- Raw Markdown outputs.
- The final `report.md`.

Artifacts are written even for partial or failed runs.

## Failures and Exit Codes

- `0`: complete reciprocal fusion.
- `2`: invalid usage or unreadable input.
- `3`: partial/degraded report with at least one useful model result.
- `4`: authentication or subscription failure with no useful result.
- `5`: timeout with no useful result.
- `6`: total failure with no useful result.

If one model fails, the other model's usable review is preserved and the report clearly identifies the missing stages. Authentication classification is based on stable CLI exit behavior plus conservative stderr markers; unknown failures remain generic.

## Gemini Hang Resolution

Before finalizing Gemini's invocation, diagnose the installed CLI in isolation: verify auth mode without exposing secrets, inspect user/project configuration and extensions, compare interactive and headless startup, enable bounded debug logging, and test a minimal prompt with extensions and tools disabled where supported. The production runner will use only the smallest verified subscription-backed command and will enforce process-tree termination on timeout.

## Testing

Unit tests inject a fake runner and cover:

- Both initial reviews and reciprocal critiques succeeding.
- One initial reviewer failing or timing out.
- A reciprocal critique failing while initial reviews remain usable.
- Both providers failing through auth, timeout, or generic errors.
- API-key environment rejection.
- Windows executable/shim resolution.
- Prompt boundary construction and file errors.
- Artifact completeness and exit-code selection.

One opt-in live smoke command will verify installed subscription CLIs, but it will not run in the normal test suite.

## Compatibility

The original fusion script and manual remain untouched. The new workflow is additive and uses the repository's existing Python environment and standard library only.
