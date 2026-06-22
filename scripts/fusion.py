"""
DIY Fusion — multi-model synthesis tool.

Default mode (agy, no API key needed):
    Calls Antigravity CLI (agy) twice with contrasting analytical lenses,
    then synthesizes via a third agy call.

OpenAI mode (requires OPENAI_API_KEY env var):
    Calls OpenAI + agy in parallel, then synthesizes with agy as judge.

Usage:
    python scripts/fusion.py "your prompt"
    python scripts/fusion.py "your prompt" --file path/to/file.py
    python scripts/fusion.py "your prompt" --file a.py --file b.py
    python scripts/fusion.py "your prompt" --stdin
    python scripts/fusion.py "your prompt" --openai          # enable OpenAI mode
    python scripts/fusion.py "your prompt" --openai --model-a o3-mini
    python scripts/fusion.py "your prompt" --no-synthesize   # raw outputs only
"""
from __future__ import annotations

import argparse
import os
import sys
import textwrap
import threading
from pathlib import Path

# Ensure the repo root is on sys.path so `scripts.fusion_providers` is importable
# whether this script is invoked as `python scripts/fusion.py` or `-m scripts.fusion`.
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.fusion_providers import AntigravityAdapter


AGY_TIMEOUT = 180  # seconds
OPENAI_MODEL_DEFAULT = "gpt-4o"

# Contrasting lenses for agy dual-lens mode — each biases toward a different
# type of finding so the two passes surface different issues.
_LENS_A = (
    "You are a strict code reviewer focused on CORRECTNESS and ARCHITECTURE. "
    "Look for: bugs, incorrect assumptions, violated contracts, layer boundary "
    "crossings, missing edge-case handling, and wrong data types. "
    "Be specific — name the exact function/line. Ignore style."
)

_LENS_B = (
    "You are a pragmatic code reviewer focused on SIMPLIFICATION and EFFICIENCY. "
    "Look for: duplicated logic, dead code, unnecessary abstraction, slow "
    "algorithms, missed standard-library calls, and overly complex control flow. "
    "Be specific — name the exact function/line. Ignore correctness."
)

_agy = AntigravityAdapter("agy")


# ── agy runner ────────────────────────────────────────────────────────────────

def run_agy(prompt: str, system: str | None = None) -> str:
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    result = _agy.call(full_prompt, timeout=AGY_TIMEOUT)
    if result.status == "ok":
        return result.stdout
    if result.status == "timeout":
        return f"[ERROR] agy timed out after {AGY_TIMEOUT}s"
    if result.status == "auth":
        return "[ERROR] agy auth failed — run `agy` and complete Google OAuth login"
    return f"[ERROR] agy failed (rc={result.returncode}): {result.stderr or '(no stderr)'}"


# ── openai runner ─────────────────────────────────────────────────────────────

def run_openai(prompt: str, model: str) -> str:
    try:
        import openai  # type: ignore[import]
    except ImportError:
        return "[ERROR] openai package not installed. Run: pip install openai"
    try:
        client = openai.OpenAI()  # reads OPENAI_API_KEY from env
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        return f"[ERROR] OpenAI call failed: {e}"


# ── parallel runners ──────────────────────────────────────────────────────────

def run_agy_dual(prompt: str) -> tuple[str, str]:
    """Two agy calls in parallel with contrasting lenses."""
    results: dict[str, str] = {}

    def task_a() -> None:
        results["a"] = run_agy(prompt, system=_LENS_A)

    def task_b() -> None:
        results["b"] = run_agy(prompt, system=_LENS_B)

    t_a = threading.Thread(target=task_a)
    t_b = threading.Thread(target=task_b)
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()
    return results["a"], results["b"]


def run_openai_agy(prompt: str, model: str) -> tuple[str, str]:
    """OpenAI + agy in parallel."""
    results: dict[str, str] = {}

    def task_a() -> None:
        results["a"] = run_openai(prompt, model)

    def task_b() -> None:
        results["b"] = run_agy(prompt)

    t_a = threading.Thread(target=task_a)
    t_b = threading.Thread(target=task_b)
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()
    return results["a"], results["b"]


# ── synthesis ─────────────────────────────────────────────────────────────────

_SYNTHESIS_PROMPT = """\
You are a synthesis judge. Two independent AI passes analyzed the same code/question.
Produce ONE best-answer synthesis following these rules:
- Where both agree: state the conclusion confidently without attribution.
- Where they conflict: explain the trade-off, pick the stronger option with a reason.
- Where one found something the other missed: include it.
- Drop all hedging phrases like "both models said" or "Model A noted".
- Be concrete and actionable. Use bullet points if listing issues.

=== Pass A ({label_a}) ===
{output_a}

=== Pass B ({label_b}) ===
{output_b}

=== Original question ===
{original_prompt}

Synthesized answer:"""


def synthesize(
    output_a: str,
    output_b: str,
    original_prompt: str,
    label_a: str,
    label_b: str,
) -> str:
    judge_prompt = _SYNTHESIS_PROMPT.format(
        label_a=label_a,
        label_b=label_b,
        output_a=output_a,
        output_b=output_b,
        original_prompt=original_prompt,
    )
    print("\n[judge] Synthesizing...", flush=True)
    return run_agy(judge_prompt)


# ── helpers ───────────────────────────────────────────────────────────────────

def build_prompt(user_prompt: str, files: list[Path], use_stdin: bool) -> str:
    parts = [user_prompt]
    if use_stdin and not sys.stdin.isatty():
        ctx = sys.stdin.read().strip()
        if ctx:
            parts.append(f"\n--- context (stdin) ---\n{ctx}")
    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            parts.append(f"\n--- {path} ---\n{content}")
        except OSError as e:
            print(f"[warn] Could not read {path}: {e}", file=sys.stderr)
    return "\n".join(parts)


def _divider(label: str) -> str:
    line = "─" * 60
    return f"\n{line}\n  {label}\n{line}"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DIY Fusion: two-model synthesis via Antigravity CLI (agy)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              # agy dual-lens mode (default, no API key needed):
              python scripts/fusion.py "Find refactoring opportunities" --file model/pdf_model.py

              # OpenAI + agy mode (requires OPENAI_API_KEY):
              python scripts/fusion.py "Review for ruff violations" --file view/pdf_view.py --openai

              # Pipe file content via stdin:
              type model\\pdf_model.py | python scripts/fusion.py "Find coupling issues" --stdin
        """),
    )
    parser.add_argument("prompt", help="The question or task")
    parser.add_argument("--file", "-f", action="append", type=Path, default=[], metavar="PATH",
                        help="File(s) to include as context (repeatable)")
    parser.add_argument("--stdin", action="store_true",
                        help="Read additional context from stdin")
    parser.add_argument("--openai", action="store_true",
                        help="Use OpenAI as model A instead of a second agy pass "
                             "(requires OPENAI_API_KEY environment variable)")
    parser.add_argument("--model-a", default=OPENAI_MODEL_DEFAULT, metavar="MODEL",
                        help=f"OpenAI model for --openai mode (default: {OPENAI_MODEL_DEFAULT})")
    parser.add_argument("--no-synthesize", "--raw", action="store_true",
                        help="Print both raw outputs without the synthesis step")
    args = parser.parse_args()

    if args.openai and not os.environ.get("OPENAI_API_KEY"):
        print("[error] --openai requires OPENAI_API_KEY to be set in your environment.", file=sys.stderr)
        print("        Set it with:  $env:OPENAI_API_KEY = 'sk-...'", file=sys.stderr)
        sys.exit(1)

    full_prompt = build_prompt(args.prompt, args.file, args.stdin)

    if args.openai:
        label_a = f"OpenAI {args.model_a}"
        label_b = "agy (Antigravity / Gemini)"
        print(f"[fusion] Running {label_a} + {label_b} in parallel...", flush=True)
        output_a, output_b = run_openai_agy(full_prompt, args.model_a)
    else:
        label_a = "agy — correctness/architecture lens"
        label_b = "agy — simplification/efficiency lens"
        print("[fusion] Running two agy passes in parallel...", flush=True)
        output_a, output_b = run_agy_dual(full_prompt)

    print(_divider(f"Pass A — {label_a}"))
    print(output_a)

    print(_divider(f"Pass B — {label_b}"))
    print(output_b)

    if args.no_synthesize:
        return

    synthesis = synthesize(output_a, output_b, args.prompt, label_a, label_b)
    print(_divider("Synthesis"))
    print(synthesis)
    print()


if __name__ == "__main__":
    main()
