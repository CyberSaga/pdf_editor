#!/usr/bin/env python3
"""Codex /goal session guard — runtime-agnostic post-completion enforcement.

Codex `/goal` does NOT fire the Claude Code Stop hook (the hook only fires for
Claude Code response Stop events).  An agent running inside Codex can declare
its goal complete by emitting a final message; nothing in the Codex runtime
checks .completion_proof.json against the user's repo HEAD.

This script closes that gap from outside the agent runtime.  Usage:

    # 1. Before invoking /goal:
    python scripts/codex_session_guard.py begin

    # 2. Run the Codex goal session normally (e.g. via /goal in a Codex client).

    # 3. After Codex declares the goal complete, run:
    python scripts/codex_session_guard.py verify

    # Exit 0 = the goal session produced a fresh, valid completion proof bound
    #         to a HEAD at-or-after the recorded baseline AND
    #         scripts/check_gate_passed.py independently re-verified the evidence.
    # Exit 1 = no proof, stale proof, mismatched HEAD, or re-verification failed.

The `begin` step records the current HEAD into test_artifacts/.codex_session_baseline
so the `verify` step can reject any proof that predates the session.  Without
the baseline, an agent could satisfy `verify` by reusing a proof file from a
previous run at the same HEAD without the Codex session having actually done
anything.

This is the only mechanically enforceable post-completion check available for
pure Codex /goal sessions in the current toolchain.  Run it from a wrapper
script, a CI step, or a manual workflow — outside of any Codex agent context.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT     = Path(__file__).parent.parent
BASELINE_PATH = REPO_ROOT / "test_artifacts" / ".codex_session_baseline"
PROOF_PATH    = REPO_ROOT / "test_artifacts" / ".completion_proof.json"


def _git_head() -> str:
    """Return the current git HEAD SHA; raise if git is unavailable."""
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(
            f"git rev-parse HEAD failed: {r.stderr.strip() or 'no output'}"
        )
    return r.stdout.strip()


def _is_ancestor(ancestor_sha: str, descendant_sha: str) -> bool:
    """Return True if ancestor_sha is an ancestor of descendant_sha (or equal).

    Uses `git merge-base --is-ancestor` which exits 0 for ancestor/equal,
    1 for not-ancestor, other for error.  We treat error as not-ancestor.
    """
    if ancestor_sha == descendant_sha:
        return True
    r = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
        cwd=str(REPO_ROOT), capture_output=True,
    )
    return r.returncode == 0


def _cmd_begin() -> int:
    head = _git_head()
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    baseline = {
        "baseline_git_commit": head,
        "recorded_at":         time.time(),
        "purpose":             "codex_goal_session_guard",
    }
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print(f"[codex-guard] Baseline recorded: HEAD={head[:12]}…")
    print(f"[codex-guard] File: {BASELINE_PATH}")
    print("[codex-guard] Run the Codex /goal session now.")
    print("[codex-guard] After it completes, run:")
    print("[codex-guard]   python scripts/codex_session_guard.py verify")
    return 0


def _cmd_verify() -> int:
    print("=" * 60)
    print("[codex-guard] Codex Session Post-Completion Verification")
    print("=" * 60)

    # 1. Baseline must exist — proves `begin` was run before the session.
    if not BASELINE_PATH.exists():
        print(
            f"[codex-guard] FAIL — baseline missing: {BASELINE_PATH}\n"
            "  Run `python scripts/codex_session_guard.py begin` BEFORE the\n"
            "  Codex /goal session, then re-run verify after it completes."
        )
        return 1
    try:
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[codex-guard] FAIL — baseline file is not valid JSON: {exc}")
        return 1
    baseline_head = baseline.get("baseline_git_commit", "")
    _raw_baseline_ts = baseline.get("recorded_at")
    try:
        baseline_ts = float(_raw_baseline_ts)  # type: ignore[arg-type]
        if not math.isfinite(baseline_ts):
            raise ValueError("non-finite")
    except (TypeError, ValueError):
        print(
            f"[codex-guard] FAIL — baseline recorded_at is not a finite number: "
            f"{_raw_baseline_ts!r}"
        )
        return 1
    if not baseline_head:
        print("[codex-guard] FAIL — baseline missing baseline_git_commit field")
        return 1

    # 2. .completion_proof.json must exist and parse.
    if not PROOF_PATH.exists():
        print(
            f"[codex-guard] FAIL — completion proof missing: {PROOF_PATH}\n"
            "  The Codex session never invoked completion_gate.py, or it was\n"
            "  invoked from a different working tree.\n"
            "  Re-run the goal session from this repository and ensure it\n"
            "  finishes with `python scripts/completion_gate.py` exit 0."
        )
        return 1
    try:
        proof = json.loads(PROOF_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[codex-guard] FAIL — completion proof is not valid JSON: {exc}")
        return 1

    # 3. Proof status must be PASSED — not IN_PROGRESS or anything else.
    if proof.get("status") != "PASSED":
        print(
            f"[codex-guard] FAIL — proof status={proof.get('status')!r}, "
            f"expected 'PASSED'.  completion_gate.py did not finish cleanly."
        )
        return 1

    # 4. Proof must be fresher than the baseline timestamp — proves it was
    #    written AFTER `begin`, not reused from a prior session.
    _raw_finished_at = proof.get("finished_at")
    try:
        proof_finished_at = float(_raw_finished_at)  # type: ignore[arg-type]
        if not math.isfinite(proof_finished_at):
            raise ValueError("non-finite")
    except (TypeError, ValueError):
        print(
            f"[codex-guard] FAIL — proof finished_at is not a finite number: "
            f"{_raw_finished_at!r}\n"
            "  A forged proof may have set this to NaN or Infinity to bypass "
            "the freshness check."
        )
        return 1
    if proof_finished_at <= baseline_ts:
        print(
            f"[codex-guard] FAIL — proof finished_at={proof_finished_at} "
            f"is not after baseline recorded_at={baseline_ts}.\n"
            f"  Proof predates the recorded baseline; this session reused a "
            f"prior run's evidence.\n"
            f"  Delete the stale proof and re-run completion_gate.py from "
            f"within the goal session."
        )
        return 1

    # 5. Proof's git_commit must descend from (or equal) baseline_head.
    #    A proof at an unrelated commit (e.g. an older HEAD) is not valid.
    proof_head = proof.get("git_commit", "")
    if not proof_head:
        print("[codex-guard] FAIL — proof missing git_commit")
        return 1
    if not _is_ancestor(baseline_head, proof_head):
        print(
            f"[codex-guard] FAIL — proof git_commit ({proof_head[:12]}…) is "
            f"not at or after baseline ({baseline_head[:12]}…).\n"
            f"  The session committed to a divergent branch or rolled HEAD "
            f"backwards; proof cannot be honored."
        )
        return 1

    # 6. Proof's git_commit must equal current HEAD — no commits may follow it.
    current_head = _git_head()
    if proof_head != current_head:
        print(
            f"[codex-guard] FAIL — proof git_commit ({proof_head[:12]}…) does "
            f"not match current HEAD ({current_head[:12]}…).\n"
            f"  A commit was made after the gate finished — proof is invalid.\n"
            f"  Re-run completion_gate.py as the absolute final action."
        )
        return 1

    # 7. Independent re-verification: invoke check_gate_passed.py.  This
    #    re-runs the full test suite and validates real artifact content;
    #    a forged or stale proof cannot satisfy this layer.
    print("[codex-guard] Invoking check_gate_passed.py for independent re-verification…")
    rc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_gate_passed.py")],
        cwd=str(REPO_ROOT),
    ).returncode
    if rc != 0:
        print(
            f"[codex-guard] FAIL — check_gate_passed.py exited {rc}.\n"
            f"  The on-disk evidence does not pass independent re-verification.\n"
            f"  The Codex session's proof file is forged or stale."
        )
        return 1

    print("\n[codex-guard] PASS — Codex session produced a valid no-jump proof.")
    print(f"[codex-guard] baseline_HEAD={baseline_head[:12]}…  "
          f"proof_HEAD={proof_head[:12]}…  current_HEAD={current_head[:12]}…")
    print(f"[codex-guard] invocation_id={proof.get('invocation_id', '')}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("begin", "verify"):
        print(__doc__)
        print("\nUsage:")
        print("  python scripts/codex_session_guard.py begin")
        print("  python scripts/codex_session_guard.py verify")
        return 2
    if argv[1] == "begin":
        return _cmd_begin()
    return _cmd_verify()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
