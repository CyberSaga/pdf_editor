# Codex-Routed Transcript Fusion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace reciprocal reporting with a subscription-only, Codex-routed Fusion pipeline using Claude candidates, Antigravity transcript extraction, a structured Codex judge, and a fresh Codex synthesizer.

**Architecture:** `scripts/fusion_cli.py` remains the user-facing entry point while focused modules own provider execution, transcript extraction, routing schemas, and pipeline orchestration. All model adapters are injectable; normal tests use fixtures and fake processes, while opt-in smoke tests consume subscriptions.

**Tech Stack:** Python 3, standard-library `argparse`, `subprocess`, `concurrent.futures`, `json`, `pathlib`, pytest, Ruff, Codex CLI, Claude Code CLI, Antigravity CLI.

---

### Task 1: Characterize the Existing Contract

**Files:**
- Modify: `test_scripts/test_fusion_cli.py`
- Create: `test_scripts/fixtures/antigravity/transcript-success.jsonl`
- Create: `test_scripts/fixtures/antigravity/transcript-ambiguous.jsonl`
- Create: `test_scripts/fixtures/antigravity/transcript-incomplete.jsonl`

**Step 1: Preserve current exit-code, timeout, prompt-boundary, and artifact tests**

Keep tests that describe reusable behavior and rename provider-specific reciprocal tests so the
old implementation can be replaced intentionally.

**Step 2: Add sanitized Antigravity transcript fixtures**

Include one matching `USER_INPUT` record followed by a completed model response, plus ambiguous
and incomplete cases. Do not copy account data or unrelated transcript content.

**Step 3: Run the baseline**

Run: `.venv\Scripts\python.exe -m pytest test_scripts\test_fusion_cli.py -q`

Expected: existing tests PASS before behavior-changing tests are added.

### Task 2: Add Routing Schemas and Pure Decisions

**Files:**
- Create: `scripts/fusion_schemas/router.schema.json`
- Create: `scripts/fusion_schemas/judge.schema.json`
- Create: `scripts/fusion_runtime.py`
- Create: `test_scripts/test_fusion_routing.py`

**Step 1: Write failing schema and routing tests**

Test valid direct/fusion router results, missing conditional fields, mandatory high-risk Fusion,
`--force-fusion`, and diagnostic `--force-direct` behavior.

**Step 2: Run the focused tests**

Run: `.venv\Scripts\python.exe -m pytest test_scripts\test_fusion_routing.py -q`

Expected: FAIL because routing helpers do not exist.

**Step 3: Implement minimal pure routing helpers**

Add enums/dataclasses for route, risk, task kind, candidate, judge dossier, and pipeline outcome.
Implement deterministic high-risk overrides separately from the model classifier.

**Step 4: Re-run focused tests**

Expected: PASS.

### Task 3: Implement the Codex Subscription Adapter

**Files:**
- Create: `scripts/fusion_providers.py`
- Create: `test_scripts/test_fusion_providers.py`

**Step 1: Write failing Codex command tests**

Require `codex exec --ephemeral --sandbox read-only`, stdin prompt transport, optional
`--output-schema`, no shell, timeout cleanup, and empty-output rejection.

**Step 2: Test subscription-only enforcement**

Reject `OPENAI_API_KEY`, `CODEX_API_KEY`, `ANTHROPIC_API_KEY`, and Google provider API-key
variables before any subprocess starts. Verify child environments also remove them.

**Step 3: Run focused tests**

Run: `.venv\Scripts\python.exe -m pytest test_scripts\test_fusion_providers.py -q -k codex`

Expected: FAIL.

**Step 4: Implement `CodexAdapter`**

Support three methods: structured router, structured judge, and text synthesis. Parse structured
JSON strictly and preserve stderr only as diagnostic metadata.

**Step 5: Re-run focused tests**

Expected: PASS.

### Task 4: Implement Antigravity Transcript Extraction

**Files:**
- Create: `scripts/fusion_transcripts.py`
- Create: `test_scripts/test_fusion_transcripts.py`
- Modify: `scripts/fusion_providers.py`

**Step 1: Write failing pure extractor tests**

Cover exact call-ID matching, last completed response selection, unrelated steps, malformed JSONL,
ambiguous conversations, incomplete responses, and empty model content.

**Step 2: Run extractor tests**

Run: `.venv\Scripts\python.exe -m pytest test_scripts\test_fusion_transcripts.py -q`

Expected: FAIL.

**Step 3: Implement read-only discovery and extraction**

Snapshot `~/.gemini/antigravity-cli/brain/*/.system_generated/logs/transcript_full.jsonl`, compare
post-run path/mtime/size metadata, parse only changed candidates, and require one matching call ID.

**Step 4: Write failing adapter lifecycle tests**

Mock `agy` returning exit 0 with empty stdout while a matching transcript appears. Also test
future usable stdout, process failure, timeout, and transcript polling timeout.

**Step 5: Implement `AntigravityAdapter`**

Invoke `agy --sandbox --print-timeout <duration> --print <prompt-with-call-id>`. Prefer non-empty
stdout; otherwise use the extractor. Persist only extracted answer text and source transcript path
metadata.

**Step 6: Re-run transcript and provider tests**

Expected: PASS.

### Task 5: Implement Claude Candidates and Parallel Panel Execution

**Files:**
- Modify: `scripts/fusion_providers.py`
- Modify: `scripts/fusion_runtime.py`
- Modify: `test_scripts/test_fusion_providers.py`
- Create: `test_scripts/test_fusion_pipeline.py`

**Step 1: Write failing Claude adapter tests**

Require subscription print mode, read-only/no-tool local review profile, stdin transport, timeout
cleanup, auth classification, and empty-output rejection.

**Step 2: Implement `ClaudeAdapter`**

Keep provider execution injectable and return the same normalized `CandidateResult` contract as
Antigravity.

**Step 3: Write failing panel concurrency tests**

Verify two Claude and two Antigravity calls run independently, labels are blinded and randomized,
and at least two usable candidates are required.

**Step 4: Implement the panel executor**

Use bounded `ThreadPoolExecutor` concurrency and persist each result immediately.

**Step 5: Run focused tests**

Run: `.venv\Scripts\python.exe -m pytest test_scripts\test_fusion_providers.py test_scripts\test_fusion_pipeline.py -q`

Expected: PASS.

### Task 6: Implement Judge, Synthesis, Verification, and Degradation

**Files:**
- Modify: `scripts/fusion_runtime.py`
- Modify: `test_scripts/test_fusion_pipeline.py`

**Step 1: Write failing end-to-end fake-runner tests**

Cover direct Codex answer, full Fusion, one provider failure, Antigravity-to-Claude-self-fusion
fallback, insufficient candidates, judge failure, synthesis failure, and verification failure.

**Step 2: Assert stage separation**

Verify router, judge, and synthesizer are separate Codex calls and the synthesizer receives the
original task, blinded raw candidates, and judge dossier.

**Step 3: Implement orchestration**

Run route -> panel -> judge -> synthesis -> deterministic verification. Never synthesize after a
judge failure and never promote a raw candidate to final output silently.

**Step 4: Implement deterministic verifiers**

Check non-empty output, internal call-ID leakage, required dossier coverage, local file citation
validity, URL syntax, and configured command results.

**Step 5: Run pipeline tests**

Expected: PASS.

### Task 7: Replace the CLI and Artifact Contract

**Files:**
- Modify: `scripts/fusion_cli.py`
- Modify: `test_scripts/test_fusion_cli.py`
- Modify: `docs/fusion-cli-manual.md`

**Step 1: Write failing CLI tests**

Cover automatic routing, `--force-fusion`, `--force-direct`, panel profile, timeouts, files, stdin,
artifact root, final answer path, and degraded exit codes.

**Step 2: Implement the thin CLI facade**

Move orchestration details out of the entry point. Print the user-facing final answer/report path
to stdout and progress diagnostics to stderr.

**Step 3: Update artifact assertions**

Require `request.md`, `route.json`, candidate records, `judge.json`, `synthesis.md`,
`verification.json`, and `report.md` for applicable stages.

**Step 4: Rewrite the manual around the new pipeline**

Document Codex direct routing, selective Fusion, transcript fallback, subscription checks,
degraded behavior, privacy boundaries, and the fact that the adapter depends on an internal
Antigravity JSONL format.

**Step 5: Run CLI tests and help**

Run:

```powershell
.venv\Scripts\python.exe -m pytest test_scripts\test_fusion_cli.py -q
.venv\Scripts\python.exe scripts\fusion_cli.py --help
```

Expected: PASS and help reflects the new routing controls.

### Task 8: Evaluate and Verify

**Files:**
- Create: `test_scripts/test_fusion_eval.py`
- Create: `docs/fusion-evaluation.md`
- Modify if required: implementation and tests above

**Step 1: Add a deterministic offline evaluation harness**

Compare stored direct and fused fixtures without live calls. Score required facts, unsafe claims,
coverage, citation validity, and latency metadata.

**Step 2: Run the complete offline suite**

Run: `.venv\Scripts\python.exe -m pytest test_scripts\test_fusion*.py -q`

Expected: all tests PASS without consuming subscriptions.

**Step 3: Run lint**

Run:

```powershell
.venv\Scripts\python.exe -m ruff check `
  scripts\fusion_cli.py scripts\fusion_runtime.py `
  scripts\fusion_providers.py scripts\fusion_transcripts.py `
  test_scripts\test_fusion*.py
```

Expected: PASS.

**Step 4: Run opt-in subscription smoke tests**

Verify one direct Codex task and one forced Fusion task. Confirm no API-key variables are present,
Antigravity output is recovered from the matching JSONL transcript, Codex produces judge and
synthesis outputs, and all artifacts exclude OAuth/account data.

**Step 5: Record measured results**

Document direct-versus-Fusion quality, latency, provider failures, and subscription call count.
Do not claim performance improvement unless the fixed evaluation suite supports it.

