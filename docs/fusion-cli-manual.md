# Subscription Fusion CLI Manual

> Selective, API-key-free orchestration using Codex, Claude Code, and Google
> Antigravity CLI subscriptions.

## Behavior

`scripts/fusion_cli.py` sends every task to Codex first. Codex either answers a
simple, low-risk task directly or routes it to Fusion. Medical, legal, financial,
security, architecture, and other high-risk tasks are forced through Fusion even
if the model proposes a direct route.

A Fusion run performs:

1. Two independent Claude Code candidates and two independent Antigravity
   candidates in parallel (`--panel-profile standard`).
2. A fresh Codex structured judge that compares blinded candidates.
3. A separate fresh Codex synthesizer that writes the final answer.
4. Deterministic checks for empty output and leaked internal call IDs.

Use `--panel-profile lean` for one Claude and one Antigravity candidate. If
Antigravity fails but two Claude candidates remain, the run continues as degraded
Claude self-fusion.

## Prerequisites

All three commands must use saved subscription authentication:

```powershell
codex --version
codex login status
claude --version
agy --version
```

The verified local configuration uses Codex CLI `0.137.0` logged in through
ChatGPT, Claude Code subscription login, and Antigravity CLI `1.0.10` Google OAuth.

Install Antigravity from Google's official installer when required:

```powershell
irm https://antigravity.google/cli/install.ps1 | iex
```

Restart PowerShell after installation. For only the current shell:

```powershell
$env:Path += ";$env:LOCALAPPDATA\agy\bin"
```

The runner refuses provider API keys. This check should print nothing:

```powershell
Get-Item Env:ANTHROPIC_API_KEY,Env:CODEX_API_KEY,Env:GEMINI_API_KEY,`
  Env:GOOGLE_API_KEY,Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
```

## Antigravity Transcript Adapter

On this Windows machine, authenticated `agy 1.0.10 --print` requests complete but
return empty stdout. Antigravity nevertheless writes the response to:

```text
~/.gemini/antigravity-cli/brain/<conversation-id>/.system_generated/logs/transcript_full.jsonl
```

The adapter adds a unique `FUSION_CALL_ID` to each prompt, snapshots transcript
metadata before execution, and reads only new or changed transcripts afterward.
It requires exactly one matching conversation and the last non-empty record with:

- `source: MODEL`
- `type: PLANNER_RESPONSE`
- `status: DONE`

Ambiguous, malformed, incomplete, or empty transcripts fail closed. If a future
Antigravity version restores stdout, native stdout is preferred automatically.
Only the extracted answer is copied to Fusion artifacts; full transcripts and
account data are never copied.

This is an internal Antigravity storage format and may change. Transcript failures
are reported as degraded or failed runs rather than silently guessed results.

## Usage

### Automatic routing

```powershell
.venv\Scripts\python.exe scripts\fusion_cli.py `
  "Explain what this function does" --file model\pdf_model.py
```

### Force Fusion for evaluation or an important decision

```powershell
.venv\Scripts\python.exe scripts\fusion_cli.py `
  "Choose a safe architecture and compare failure modes" `
  --file controller\pdf_controller.py --force-fusion
```

### Lean panel

```powershell
.venv\Scripts\python.exe scripts\fusion_cli.py `
  "Review this migration plan" --file plan.md `
  --force-fusion --panel-profile lean
```

### Pipe diagnostics

```powershell
.venv\Scripts\python.exe -m ruff check model\pdf_model.py --output-format=json | `
  .venv\Scripts\python.exe scripts\fusion_cli.py `
    "Prioritize these findings by regression risk" --stdin
```

### Timeout and artifact root

```powershell
.venv\Scripts\python.exe scripts\fusion_cli.py `
  "Review this architecture" --force-fusion `
  --timeout 300 --out-dir C:\tmp\fusion-runs
```

`--force-direct` is a diagnostic override. It bypasses mandatory Fusion routing
and should not be used to evade review for high-risk work.

## Safety Boundaries

- Codex router, judge, and synthesizer use `codex exec --ephemeral --sandbox read-only`.
- Claude candidates run in print mode with tools disabled, plan permission mode,
  and no session persistence.
- Antigravity candidates run with `--sandbox`.
- File and stdin content is explicitly labelled untrusted.
- Provider subprocesses use argument arrays with `shell=False`.
- Each call has a timeout; Windows timeout cleanup terminates the process tree.
- Judge and synthesizer prompts treat all candidate text as untrusted evidence.

The Antigravity prompt must be passed as a process argument because `agy --print`
accepts its prompt as a flag value. It is not interpolated through a shell, but it
may be visible to other processes owned by the same Windows user while running.

## Artifacts

Each invocation creates a timestamped directory:

```text
.fusion-runs/fusion-20260620-120000-a1b2c3/
  request.md
  route.json
  attempt-claude-0.json
  attempt-antigravity-0.json
  candidate-1.json
  candidate-1.md
  candidate-2.json
  candidate-2.md
  judge.json
  synthesis.md
  verification.json
  report.md
```

Direct routes omit attempt, candidate, and judge artifacts. Failed panel attempts
are retained even when there are too few usable candidates to continue. Candidate
and attempt JSON contains status and timing metadata, but not the prompt-bearing
process command.

## Exit Codes

| Code | Meaning |
|---:|---|
| 0 | Direct answer or full Fusion completed and verified. |
| 2 | Invalid input, unreadable file, missing Codex, invalid timeout, or API-key environment. |
| 3 | Useful answer produced with provider degradation or verification warning. |
| 6 | Router, panel, judge, or synthesis failed without a valid final answer. |

## Interpretation

The judge identifies consensus, contradictions, unique insights, unsupported
claims, missing coverage, and a recommended outline. The synthesizer receives the
original task, raw blinded candidates, and that dossier. It is a separate Codex
session and must preserve uncertainty rather than manufacture consensus.

Fusion is not proof of correctness. Verify code changes with tests and linting,
and verify medical, legal, financial, or security conclusions against authoritative
sources and qualified review.

## Offline Verification

Normal tests do not consume subscription quota:

```powershell
.venv\Scripts\python.exe -m pytest test_scripts\test_fusion*.py -q
.venv\Scripts\python.exe -m ruff check `
  scripts\fusion_cli.py scripts\fusion_runtime.py `
  scripts\fusion_providers.py scripts\fusion_transcripts.py `
  test_scripts\test_fusion*.py
```

Live smoke tests are opt-in because one standard forced Fusion run uses seven
subscription calls: one router, four candidates, one judge, and one synthesizer.
