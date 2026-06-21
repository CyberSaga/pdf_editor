# Codex-Routed Transcript Fusion Design

## Goal

Build a subscription-only Fusion system in which Codex handles ordinary tasks directly,
routes only high-risk, research-heavy, or architectural tasks to a Claude Code plus
Antigravity panel, and synthesizes the panel into one final answer. The system must not
use provider APIs, OpenRouter credits, or API keys.

## Decisions

- Codex is the front door, complexity router, structured judge, and final synthesizer.
- Claude Code and Antigravity are panel participants, invoked through existing subscription
  logins.
- Antigravity uses a transcript adapter because `agy` 1.0.10 completes requests but emits
  empty stdout on this Windows machine.
- Simple tasks stop after one Codex call.
- Fusion is selective, auditable, and allowed to degrade instead of fabricating consensus.

## Architecture

The command first invokes an ephemeral, read-only `codex exec` turn with a JSON Schema.
That turn returns either a direct answer or a Fusion decision with reasons and a task
profile. Deterministic rules force Fusion for explicitly high-risk domains and can veto a
misclassified direct route.

For a Fusion route, the orchestrator launches independent Claude and Antigravity samples
in parallel. A fresh Codex judge receives blinded candidate IDs and returns structured
consensus, contradictions, unique insights, unsupported claims, missing coverage, and a
recommended evidence-grounded outline. A separate fresh Codex session synthesizes the
original task, raw candidates, and judge dossier into the final answer.

```text
task + context
    -> Codex router/direct-answer turn
       -> direct: final answer
       -> fusion: parallel Claude and Antigravity candidates
                  -> fresh Codex structured judge
                  -> fresh Codex synthesizer
                  -> deterministic verification and report
```

The judge and synthesizer are separate sessions so the final writer does not silently
replace the comparison step with its first impression.

## Routing Contract

The router returns structured data with:

- `route`: `direct` or `fusion`.
- `risk_level`: `low`, `medium`, or `high`.
- `task_kind`: `simple`, `code_review`, `research`, `architecture`, `medical`, `legal`,
  `financial`, `security`, or `other`.
- `reasons`: short routing evidence.
- `direct_answer`: required only for the direct route.
- `panel_brief`: required only for the Fusion route.

Fusion is mandatory for medical, legal, financial, security, irreversible migration,
architecture, or explicit deep-research requests. Large context, conflicting evidence, or
requests for multiple independent opinions also trigger Fusion. Formatting, summarization,
small explanations, and low-risk local transformations remain direct.

Routing defaults are conservative but configurable. A CLI `--force-direct` option exists
for diagnostics only; `--force-fusion` is available for evaluation and user choice.

## Provider Adapters

### Codex

Codex runs with saved ChatGPT authentication using `codex exec --ephemeral --sandbox
read-only`. Prompts are supplied through stdin. Structured router and judge results use
`--output-schema`; final responses use captured stdout or `--output-last-message`.

No `OPENAI_API_KEY` or `CODEX_API_KEY` may be present. The adapter records command metadata,
duration, exit status, and stderr without persisting authentication material.

### Claude Code

Claude runs through its subscription login in non-interactive mode. Candidate runs are
independent and receive identical trusted task text and untrusted context delimiters.
Provider tools are disabled for local review mode. Research mode may enable an explicitly
documented read-only web tool profile.

### Antigravity Transcript Adapter

Every Antigravity prompt includes a unique `FUSION_CALL_ID`. Before launch, the adapter
snapshots existing `transcript_full.jsonl` paths and metadata. It runs `agy --sandbox
--print-timeout ... --print ...`, then searches new or changed transcripts for the exact
call ID.

The extractor requires exactly one matching conversation and selects the final non-empty
record where:

- `source` is `MODEL`;
- `type` is `PLANNER_RESPONSE`;
- `status` is `DONE`;
- its step follows the matching `USER_INPUT`.

If stdout becomes usable in a later `agy` release, stdout is preferred and the transcript
becomes a fallback. Ambiguous matches, malformed JSONL, missing completion, or an empty
answer are failures, never guessed results. The adapter reads Antigravity state but never
modifies it.

## Panel and Fusion Semantics

The default high-assurance panel is two independent Claude samples and two independent
Antigravity samples. A lower-cost profile uses one of each. Candidate labels are randomized
before judging so provider identity cannot influence the comparison.

The judge must distinguish:

- claims supported by multiple candidates;
- compatible claims with complementary coverage;
- direct contradictions;
- unique but checkable insights;
- unsupported or unsafe claims;
- missing questions the final answer must address.

The synthesizer receives the original task, evidence context, blinded candidates, and the
judge dossier. It must resolve disagreements explicitly, preserve uncertainty, cite candidate
provenance internally, and never claim consensus merely because the judge preferred one
answer.

## Verification

Deterministic checks run after synthesis:

- The final answer is non-empty and contains no internal call IDs.
- Required sections from the judge dossier are covered.
- File citations refer to supplied files and valid line numbers where applicable.
- Research links have valid URL syntax and are de-duplicated.
- Code tasks may run explicitly configured tests and linters outside model calls.

The system does not claim beyond-frontier quality without a local evaluation. Evaluation
compares direct Codex against Fusion on a fixed task suite using blinded scoring, deterministic
checks, latency, and subscription-call counts.

## Failures and Degradation

- Router failure: return a clear failure unless the user forced a route.
- One panel call fails: continue when at least two independent candidates remain.
- Antigravity extraction fails: use Claude self-fusion and mark the run degraded.
- Judge fails: preserve candidates and stop before synthesis.
- Synthesizer fails: preserve the judge dossier and candidates; do not substitute raw output
  as a final answer.
- Verification fails: write the answer as provisional and return a degraded exit code.

All stages have independent timeouts and process-tree cleanup.

## Artifacts

Each Fusion run stores:

- `request.md` and `route.json`;
- one JSON metadata record and Markdown output per candidate;
- `judge.json`;
- `synthesis.md`;
- `verification.json`;
- `report.md` with route, degradation state, timings, and provenance.

The artifacts copy extracted model text, not entire Antigravity transcripts, which may contain
unrelated local session data.

## Security and Privacy

Candidate and transcript content is untrusted data when passed to judge and synthesizer.
Provider commands use argument arrays with `shell=False`. API-key environments are rejected.
Codex judge and synthesis sessions are ephemeral and read-only; Antigravity runs sandboxed.
Secrets, OAuth tokens, account files, and complete transcript stores are never copied into run
artifacts.

## Source Basis

The architecture mirrors the useful separation in OpenRouter Fusion: parallel candidates,
structured comparison, and a distinct final writer. Unlike OpenRouter, every model is invoked
locally through existing CLI subscriptions. Codex non-interactive mode is suitable because it
supports saved ChatGPT authentication, stdin prompts, final stdout, JSONL events, JSON Schema
outputs, ephemeral sessions, and read-only sandboxing.

