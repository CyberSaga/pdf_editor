# Subscription Fusion CLI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an additive, subscription-only reciprocal fusion CLI using Claude Code and Gemini CLI, with durable artifacts, deterministic reporting, and clear failure behavior.

**Architecture:** A single standard-library Python module exposes pure prompt/report/status functions plus an injectable subprocess runner. Claude and Gemini perform concurrent independent reviews, then reciprocal critiques; every stage is persisted and Python assembles the final report without appointing either vendor as sole judge.

**Tech Stack:** Python 3, `argparse`, `concurrent.futures`, `subprocess`, `dataclasses`, JSON, pytest, Claude Code CLI, Gemini CLI.

---

### Task 1: Diagnose and Stabilize Gemini Headless Subscription Use

**Files:**
- Create: `docs/plans/2026-06-20-gemini-cli-diagnosis.md`

**Step 1: Capture safe environment and configuration evidence**

Record CLI version, resolved executable, Boolean API-key presence, auth configuration names with values redacted, enabled extensions, and processes left by the timed-out invocations.

**Step 2: Run bounded startup experiments**

Compare minimal headless runs with project configuration enabled/disabled, extensions enabled/disabled, explicit model selection, JSON/text output, and debug logging. Use a 45-second process-tree timeout for every experiment.

**Step 3: Identify the first divergent phase**

Use debug output and process state to classify the hang as authentication, extension/MCP startup, workspace trust, model selection, network, or shutdown cleanup.

**Step 4: Verify the smallest working subscription command**

Run a prompt that returns `GEMINI_OK`, confirm no API-key environment is present, and record exact flags plus elapsed time.

**Step 5: Document the diagnosis**

Write symptoms, evidence, root cause, verified command, and any user-level configuration correction to the diagnosis document.

### Task 2: Define Core Contracts with Failing Tests

**Files:**
- Create: `scripts/fusion_cli.py`
- Create: `test_scripts/test_fusion_cli.py`

**Step 1: Write tests for prompt boundaries and API-key rejection**

Test that trusted instructions and untrusted file/stdin blocks are distinct, unreadable files are rejected, and any provider API-key variable blocks live execution.

**Step 2: Run tests to verify failure**

Run: `.venv\Scripts\python.exe -m pytest test_scripts/test_fusion_cli.py -q`

Expected: FAIL because `scripts.fusion_cli` does not exist.

**Step 3: Implement minimal data types and pure helpers**

Add `CallSpec`, `CallResult`, status constants, prompt construction, API-key validation, and executable resolution. Keep subprocess access behind a runner protocol.

**Step 4: Run focused tests**

Expected: prompt and validation tests PASS.

### Task 3: Implement Safe CLI Runners with TDD

**Files:**
- Modify: `scripts/fusion_cli.py`
- Modify: `test_scripts/test_fusion_cli.py`

**Step 1: Write failing runner tests**

Cover Claude/Gemini argv, stdin transport, UTF-8 replacement, missing executables, timeout classification, auth marker classification, nonzero generic failure, and Windows shim resolution.

**Step 2: Run focused runner tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest test_scripts/test_fusion_cli.py -q -k runner`

Expected: FAIL for missing runner implementation.

**Step 3: Implement the subprocess runner**

Use `Popen` with `shell=False`, captured streams, verified CLI flags, and process-tree termination on timeout. Return structured results rather than raising provider failures.

**Step 4: Run focused and full module tests**

Expected: PASS.

### Task 4: Implement Reciprocal Orchestration and Artifacts with TDD

**Files:**
- Modify: `scripts/fusion_cli.py`
- Modify: `test_scripts/test_fusion_cli.py`

**Step 1: Write failing orchestration tests**

Use a fake runner to cover success, partial initial review, failed reciprocal critique, auth-only failure, timeout-only failure, mixed total failure, and `--no-cross-critique`.

**Step 2: Assert concurrency and stage dependencies**

Verify initial calls can overlap and reciprocal critiques run only when both initial reviews are usable.

**Step 3: Implement orchestration**

Run initial reviews with `ThreadPoolExecutor`, persist each result immediately, run reciprocal critiques concurrently, and compute documented exit codes.

**Step 4: Implement deterministic Markdown assembly**

Report run status, degradation notes, both initial reviews, both reciprocal critiques, and artifact filenames without claiming unsupported consensus.

**Step 5: Run module tests**

Expected: PASS.

### Task 5: Implement the User-Facing CLI

**Files:**
- Modify: `scripts/fusion_cli.py`
- Modify: `test_scripts/test_fusion_cli.py`

**Step 1: Write parser and main-function tests**

Cover positional prompt, repeatable `--file`, `--stdin`, `--timeout`, `--out-dir`, `--no-cross-critique`, invalid timeout, and final report path output.

**Step 2: Implement `argparse` and `main()`**

Default to a timestamped `.fusion-runs` directory, return the orchestrator's exit code, and print concise progress to stderr with the final report path on stdout.

**Step 3: Run tests and CLI help**

Run:

```powershell
.venv\Scripts\python.exe -m pytest test_scripts/test_fusion_cli.py -q
.venv\Scripts\python.exe scripts\fusion_cli.py --help
```

Expected: tests PASS and help lists all documented options.

### Task 6: Write the Separate Manual

**Files:**
- Create: `docs/fusion-cli-manual.md`

**Step 1: Document prerequisites and subscription checks**

Include installed versions, OAuth/subscription requirements, API-key rejection, Gemini recovery, and a safe smoke test.

**Step 2: Document everyday and high-stakes workflows**

Provide PowerShell examples for one or several files, stdin, raw two-pass mode, custom timeout/output location, and interpreting reciprocal critiques.

**Step 3: Document artifacts and exit codes**

Explain every generated file, partial-run semantics, timeout behavior, and rerun guidance.

**Step 4: Document repository-specific playbooks**

Cover pre-edit review, MVC audit, tests, PyMuPDF/PySide6 pitfalls, security review, and explicit verification limitations.

### Task 7: Verify Live and Offline Behavior

**Files:**
- Modify if required: `scripts/fusion_cli.py`
- Modify if required: `test_scripts/test_fusion_cli.py`
- Modify if required: `docs/fusion-cli-manual.md`

**Step 1: Run the complete offline test module**

Run: `.venv\Scripts\python.exe -m pytest test_scripts/test_fusion_cli.py -q`

Expected: PASS without invoking either subscription.

**Step 2: Run repository lint on new Python files**

Run: `.venv\Scripts\python.exe -m ruff check scripts/fusion_cli.py test_scripts/test_fusion_cli.py`

Expected: PASS.

**Step 3: Run a bounded live reciprocal smoke test**

Run the new CLI against a small source file with a concise prompt and a practical timeout. Confirm Claude and Gemini calls both complete, reciprocal critiques are present, no API keys are set, and artifacts are valid UTF-8.

**Step 4: Review the diff and untouched originals**

Confirm `scripts/fusion.py` and `docs/fusion-agent-manual.md` have no diff.

**Step 5: Commit implementation and documentation**

Stage only the new tool, tests, manual, diagnosis, and plan. Use a concise repository-style commit message.
