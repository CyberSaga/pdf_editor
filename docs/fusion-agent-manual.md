# Fusion Agent Manual — Approaching Fable 5 Quality with Local Tools

> **Purpose:** Field guide for agent sessions working on this codebase.
> Three-model fusion (Gemini dual-lens + Codex) reaches near-frontier
> review quality without requiring a frontier model API key.
>
> **Tools:** `scripts/fusion.py` + `/codex:rescue` (Claude Code skill)
> **Theory source:** OpenRouter Fusion / DRACO benchmark findings (2025)

---

## 1. Why This Works

The DRACO benchmark showed that **synthesizing independent model outputs
consistently beats any single model**, and that a budget panel can score
within 5 points of Fable 5 (64.7% vs 69.0%). The key mechanism is not
model capability — it is **independent analytical angles**.

A single model call has one implicit frame. Two calls with **forced
contrasting lenses** surface complementary issues. Adding a **third
model from a different vendor** (different training data, different
biases) pushes coverage further — three independent passes approach
the combinatorial finding rate of frontier models.

The available panel on this machine:

| Pass | Model | Lens | How invoked |
|------|-------|------|-------------|
| A | Gemini | Correctness / architecture | `scripts/fusion.py` (automatic) |
| B | Gemini | Simplification / efficiency | `scripts/fusion.py` (automatic) |
| C | Codex (OpenAI o3) | Implementation / second opinion | `/codex:rescue` in Claude Code |
| Judge | Gemini | Synthesis | `scripts/fusion.py` (automatic) |

**Two-model fusion** (Gemini dual-lens only) yields a measured +6.7
point jump. **Three-model fusion** (adding Codex) adds a third
vendor's training perspective — different blind spots, different
strengths — pushing closer to Fable 5's 69.0%.

---

## 2. The Tools

### 2.1 `scripts/fusion.py` — Gemini Dual-Lens (automated)

Runs two Gemini CLI calls in parallel with contrasting system prompts,
then synthesizes both outputs via a third Gemini call. Fully automated,
no API key needed.

```
--file PATH       Include a source file as context (repeatable)
--stdin           Read context from stdin (pipe output of another command)
--no-synthesize   Print raw pass A + B outputs, skip synthesis
--openai          Use OpenAI API as pass A (requires OPENAI_API_KEY)
--model-a MODEL   OpenAI model override (default: gpt-4o)
```

### 2.2 `/codex:rescue` — Codex Pass (agent-driven)

Codex is a Claude Code skill invoked via `/codex:rescue` inside a
Claude Code session. It uses OAuth login (subscription-based, no API
key). It cannot be piped into fusion.py — the agent must invoke it
separately and manually incorporate its output into the synthesis.

**How Codex fits the panel:** Codex runs OpenAI o3 under the hood.
Its training data and reasoning patterns differ from Gemini's, so it
reliably surfaces findings that both Gemini passes miss. This is the
vendor-diversity advantage that makes three-model fusion stronger
than same-model self-fusion.

### 2.3 Invocation Patterns

```powershell
# Two-model fusion (Gemini dual-lens, everyday use)
.venv\Scripts\python.exe scripts/fusion.py "Find the top 5 issues" `
    --file model/pdf_model.py

# Review multiple files together
.venv\Scripts\python.exe scripts/fusion.py "Find coupling violations" `
    --file controller/pdf_controller.py `
    --file model/pdf_model.py

# Feed code graph output as context
.venv\Scripts\python.exe .codegraph/query.py explore PDFModel 2 | `
    .venv\Scripts\python.exe scripts/fusion.py "Architectural weak points?" --stdin

# Feed ruff output as context
.venv\Scripts\python.exe -m ruff check model/pdf_model.py --output-format=json | `
    .venv\Scripts\python.exe scripts/fusion.py "Prioritize by fix risk" --stdin

# Raw outputs only (useful for comparing before synthesis)
.venv\Scripts\python.exe scripts/fusion.py "Prompt" --file path.py --no-synthesize
```

---

## 3. Three-Model Fusion Protocol

This is the full workflow for approaching Fable 5 quality. Use it for
high-stakes reviews (pre-commit on core modules, design decisions,
security-sensitive changes).

### Step 1 — Run Gemini dual-lens

```powershell
.venv\Scripts\python.exe scripts/fusion.py "<PROMPT>" --file <FILE> --no-synthesize
```

Use `--no-synthesize` so you keep both raw outputs visible. Save or
copy the output for Step 3.

### Step 2 — Run Codex

In your Claude Code session, invoke:

```
/codex:rescue
```

Then give Codex the **same prompt and file context** you gave fusion.py.
Codex will produce an independent analysis using OpenAI o3. Copy or
save its output.

### Step 3 — Synthesize all three

Feed all three outputs into the Gemini synthesis judge:

```powershell
.venv\Scripts\python.exe scripts/fusion.py `
    "You have three independent code reviews below. Synthesize into one
     actionable report. Where all three agree: state confidently. Where
     two agree and one disagrees: explain the trade-off, pick the stronger.
     Where one found something unique: include it, mark as medium confidence.
     Drop hedging phrases.

     === Pass A (Gemini correctness) ===
     <PASTE PASS A>

     === Pass B (Gemini simplification) ===
     <PASTE PASS B>

     === Pass C (Codex / OpenAI o3) ===
     <PASTE CODEX OUTPUT>"
```

Alternatively, save the three outputs to a temp file and pipe via `--stdin`.

### When to use three-model vs two-model

| Situation | Use |
|-----------|-----|
| Quick pre-edit scan | Two-model (fusion.py default) |
| Core module refactor | Three-model |
| MVC boundary audit | Two-model (rules are explicit enough) |
| New feature design | Three-model (competing designs benefit from vendor diversity) |
| Security / encryption review | Three-model |
| Ruff violation triage | Two-model (mechanical task) |
| Test gap analysis | Three-model (different models catch different untested paths) |

---

## 4. Codebase-Specific Playbooks

Run these before touching a module.

### 4.1 Pre-edit module review

```powershell
.venv\Scripts\python.exe scripts/fusion.py `
    "This is the target module I am about to modify. Identify: (1) any existing
     correctness bugs or violated invariants I must not worsen; (2) any
     simplification opportunities I should apply while I'm here; (3) any
     architectural boundary violations I need to be aware of per the MVC rules
     (View never calls Model; Controller is the only mutation coordinator;
     Model never imports Qt). Be specific about function names and line ranges." `
    --file <TARGET_FILE>
```

**Three-model upgrade:** Run the same prompt through `/codex:rescue`
with the file content pasted, then synthesize per Section 3.

### 4.2 Ruff violation triage

```powershell
.venv\Scripts\python.exe scripts/fusion.py `
    "Here are the ruff violations for this file. Group them by: (1) auto-fixable
     with ruff --fix; (2) safe to fix manually with no behavior change; (3) risky
     to fix (could change behavior). List specific line numbers." `
    --file <TARGET_FILE> --stdin < /tmp/violations.json
```

### 4.3 Cross-layer boundary audit

```powershell
.venv\Scripts\python.exe scripts/fusion.py `
    "Audit this file for MVC boundary violations. The rules are strict:
     (1) View (view/) must never import from model/ or call fitz directly.
     (2) Model (model/) must never import Qt (PySide6/PyQt).
     (3) Controller is the only coordinator — it can call both.
     (4) ToolManager is a Model extension, not a separate layer.
     List every violation with the exact import or call site." `
    --file <TARGET_FILE>
```

### 4.4 New feature design (three-model recommended)

```powershell
# Step 1: Gemini dual-lens
.venv\Scripts\python.exe scripts/fusion.py `
    "I need to implement: <FEATURE DESCRIPTION>.
     The affected modules are: <LIST>.
     Constraints: MVC architecture (View->signals->Controller->Model->ToolManager),
     QThread for background work, no bare except, float font sizes.
     Produce two competing design sketches. Focus on: what data flows where,
     which layer owns the new state, how undo/redo would work if relevant." `
    --file <AFFECTED_FILE_1> --file <AFFECTED_FILE_2> --no-synthesize

# Step 2: Give /codex:rescue the same prompt and files
# Step 3: Synthesize all three per Section 3
```

### 4.5 Test coverage gap analysis (three-model recommended)

```powershell
.venv\Scripts\python.exe scripts/fusion.py `
    "Review this implementation file and the corresponding test file.
     Identify: (1) public methods or branches with no test; (2) edge cases
     (empty input, boundary values, error paths) not covered; (3) any test
     that passes on a no-op because it only checks return value, not side effects.
     Be specific — name the untested method and describe the missing test." `
    --file <IMPL_FILE> --file <TEST_FILE>
```

### 4.6 PyMuPDF / PySide6 pitfall scan (three-model recommended)

```powershell
.venv\Scripts\python.exe scripts/fusion.py `
    "Scan this code for PyMuPDF and PySide6 known pitfalls:
     - font sizes must stay float (never coerce span['size'] to int)
     - fitz.Document.save() default encryption=NONE actively decrypts
     - tobytes() also defaults to NONE — use encryption=KEEP
     - scene.clear() leaves dangling Python wrappers to deleted C++ items
     - QThread workers must never touch Qt UI objects directly
     - fitz.open() must never appear in view/ layer files
     List every instance with file and line number." `
    --file <TARGET_FILE>
```

---

## 5. Prompt Engineering for This Codebase

### 5.1 Always name the constraints

```
# Good
"Find violations of the MVC rule that View must never call Model directly.
 The layer boundary is enforced by CLAUDE.md and CI."

# Weak
"Find architecture problems."
```

### 5.2 Ask for specificity

```
# Good
"List each issue with: module name, function name, line range, and one-sentence fix."

# Weak
"What could be improved?"
```

### 5.3 For design questions, ask for competing options

```
"Give two competing approaches to implementing X. Approach A should prioritize
 simplicity and fewest moving parts. Approach B should prioritize robustness
 and explicit error handling. Then recommend one."
```

### 5.4 For bug hunting, use the correctness lens explicitly

```
"This function is producing wrong output in the following scenario: <SCENARIO>.
 Read the code carefully and identify the exact line where the logic error is.
 Check: off-by-one errors, incorrect condition polarity, mutation of shared
 state, and any PyMuPDF or Qt API misuse."
```

### 5.5 Give Codex the same prompt as Gemini

When running three-model fusion, use the **exact same prompt** for both
fusion.py and `/codex:rescue`. Different prompts produce different scopes,
which weakens the synthesis — the judge cannot meaningfully compare
findings that answered different questions.

---

## 6. Reading Synthesis Output

The synthesis pass uses these rules:
- Where all passes agree -> stated confidently, no hedging
- Where majority agrees -> included with brief note on the dissent
- Where they conflict -> trade-off explained, stronger option picked
- Where one found something unique -> included, marked medium confidence

**Confidence tiers (three-model):**
- All three agree -> high confidence, act on it
- Two agree, one disagrees -> medium-high, verify the disagreement
- One unique finding -> medium, verify manually before acting
- All three disagree -> low, investigate before choosing

**When to use `--no-synthesize` and read raw outputs:**
- When you want to see the full reasoning from each pass
- When the synthesis dropped an important finding from one pass
- When designing and you want competing options visible

---

## 7. Integration with the Cleanup Plan

| Phase | Fusion mode | Playbook |
|-------|------------|----------|
| Phase 0 — Audit | Three-model | 4.1 on the 10 largest modules |
| Phase 1 — Mechanical | Two-model | 4.2 on each file before `ruff --fix` |
| Phase 2 — MVC fix | Two-model | 4.3 on all view/ files |
| Phase 3 — Manual ruff | Two-model | 4.1 + 4.2 per module |
| Phase 4 — Deferred features | Three-model | 4.4 before, 4.5 after |
| Phase 5 — Security | Three-model | 4.6 on model/ and view/ |

---

## 8. Limitations

Fusion does **not** replace:
- **Running the actual tests.** `pytest` catches regressions; fusion does not.
- **Reading PITFALLS.md.** Known failure modes are documented there; fusion
  may rediscover them but will not cite them by name.
- **The ruff linter.** `ruff check .` is authoritative; fusion is advisory.
- **Reading the source file before editing.** Fusion reviews a snapshot;
  the actual file may have changed. Always read before editing.

Fusion is **not reliable for:**
- Tasks requiring full repository context (it only sees the files you pass)
- Precise line-count or token-level diffs
- Verifying that a proposed fix actually passes the test suite

**Codex-specific limitations:**
- `/codex:rescue` is a Claude Code skill, not a shell command — it cannot
  be piped into fusion.py or automated in a script
- Codex output must be manually copied into the synthesis step
- Codex uses subscription auth (OAuth login), not an API key — it cannot
  run headlessly or in CI

Use fusion for **analysis and design decisions**. Use the actual tools
(`pytest`, `ruff`, `mypy`) for **verification**.

---

## 9. Quick Reference

```powershell
# === Two-model (everyday) ===

# Pre-edit review
.venv\Scripts\python.exe scripts/fusion.py "Review before I modify this" --file <FILE>

# Ruff triage
.venv\Scripts\python.exe scripts/fusion.py "Prioritize these violations" --file <FILE> --stdin < violations.json

# MVC audit
.venv\Scripts\python.exe scripts/fusion.py "Find layer boundary violations" --file <FILE>

# PyMuPDF/Qt pitfall scan
.venv\Scripts\python.exe scripts/fusion.py "Scan for fitz/Qt known pitfalls" --file <FILE>

# Raw passes without synthesis
.venv\Scripts\python.exe scripts/fusion.py "..." --file <FILE> --no-synthesize

# === Three-model (high-stakes) ===

# Step 1: Gemini dual-lens (save raw output)
.venv\Scripts\python.exe scripts/fusion.py "<PROMPT>" --file <FILE> --no-synthesize

# Step 2: Run /codex:rescue with same prompt and file content

# Step 3: Synthesize all three passes
.venv\Scripts\python.exe scripts/fusion.py `
    "Synthesize these three independent reviews into one report:
     === Pass A === <GEMINI_A> === Pass B === <GEMINI_B> === Pass C === <CODEX>"

# === Design decisions ===
# Step 1: fusion.py with --no-synthesize
# Step 2: /codex:rescue with same prompt
# Step 3: Synthesize competing designs from all three
```
