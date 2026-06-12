#!/usr/bin/env python3
"""Claude/Codex Stop hook — validates .completion_proof.json before allowing completion.

Registered in .claude/settings.json as a Stop hook.  Claude Code runs this
script automatically when the assistant is about to stop responding.  Exit 0
allows the response; exit 1 blocks it and prints the reason to stderr.

Enforcement logic (layered, each layer catches a distinct attack class):
  1. Goal-mode guard: if the gate plan file does not exist AND was never committed
     to git → exit 0 (not active).  If the file was committed but is now missing
     → exit 1 (tampering detected; deleting the file does not deactivate the gate).
  2. Proof presence: if .completion_proof.json is absent → exit 1.
  3. Basic field validation: status, exit codes, invocation_id, tracked_scripts.
  4. git_commit vs HEAD: rejects stale proofs from earlier commits.
  5. Digest re-hashing: independently reads .gate_passed and signoff.json from
     disk and recomputes SHA256 — a forged proof with fabricated digest strings
     cannot match unless the actual files were written by the real gate.
  6. Semantic artifact validation: reads .gate_passed JSON and checks its
     embedded git_commit matches HEAD.
  7. Full independent re-verification: invokes scripts/check_gate_passed.py as
     a subprocess.  This is the decisive layer — hash-consistent but semantically
     invalid artifacts (e.g. forged .gate_passed with correct git_commit but no
     real test run, or forged signoff.json) are rejected here because
     check_gate_passed.py re-runs the actual tests and verifies real evidence.
     Layer 7 always runs (no cache) — a cache stored in the writable workspace
     can be pre-populated by an agent to skip this decisive check.

This is an OUT-OF-AGENT enforcement point: the agent cannot bypass it by
pasting text or skipping completion_gate.py, because every Stop event fires
this hook regardless of what the agent wrote.

Codex-session note: this hook fires for Claude Code Stop events.  For pure
Codex goal sessions (non-Claude Code), enforcement is provided by:
  (a) the mandatory completion rule in the gate plan file (prompt-level), and
  (b) the goal file explicitly naming completion_gate.py as the only valid
      done signal — Codex must report its stdout to satisfy the AC.
Both layers are documented in plans/2026-05-05-no-jump-editor-geometry-gate.md.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT    = Path(__file__).parent.parent
# Bound to the ACTUAL gate plan file added in this change-set.
GOAL_FILE    = REPO_ROOT / "plans" / "2026-05-05-no-jump-editor-geometry-gate.md"
PROOF_PATH   = REPO_ROOT / "test_artifacts" / ".completion_proof.json"
MARKER_PATH  = REPO_ROOT / "test_artifacts" / ".gate_passed"
SIGNOFF_PATH = REPO_ROOT / "test_artifacts" / "signoff.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _goal_file_tracked_in_git() -> bool:
    """Return True if GOAL_FILE is tracked in git (even if absent from the working tree).

    Isolated as a named function so tests can monkeypatch it without spawning git.
    Using the full path (str(GOAL_FILE)) works for both in-repo and tmp-path cases:
    git ls-files won't find a file outside the repo root and returns non-zero.
    """
    r = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(GOAL_FILE)],
        cwd=str(REPO_ROOT), capture_output=True,
    )
    return r.returncode == 0


def _git_head() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"git rev-parse HEAD failed: {r.stderr.strip()}")
    return r.stdout.strip()


def _run_check_gate_passed() -> int:
    """Invoke check_gate_passed.py and return its exit code.

    Isolated as a named function so tests can monkeypatch it without spawning
    a real subprocess (which would require a full test-suite run).
    """
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_gate_passed.py")],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    # Forward output so the user sees why it failed.
    if r.stdout:
        print(r.stdout, file=sys.stderr, end="")
    if r.stderr:
        print(r.stderr, file=sys.stderr, end="")
    return r.returncode


def main() -> int:
    # Layer 1: goal-mode guard — fail closed on tampering.
    # Deactivates only when the plan file was NEVER committed to git.
    # Deleting the file after it has been committed is treated as tampering.
    if not GOAL_FILE.exists():
        if not _goal_file_tracked_in_git():
            return 0  # Genuinely not in goal mode — file never committed.
        print(
            "[stop-hook] BLOCKED — gate plan file was committed to git but is "
            "missing from the working tree:\n"
            f"  {GOAL_FILE}\n"
            "  Deleting the goal file does not deactivate the gate.\n"
            "  Restore it or run: python scripts/completion_gate.py",
            file=sys.stderr,
        )
        return 1

    if not PROOF_PATH.exists():
        print(
            "[stop-hook] BLOCKED — no-jump gate plan is active but "
            ".completion_proof.json is absent.\n"
            "  Run: python scripts/completion_gate.py\n"
            "  Paste its '[completion-gate] BOTH COMMANDS PASSED' stdout "
            "before completing.",
            file=sys.stderr,
        )
        return 1

    try:
        proof = json.loads(PROOF_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(
            f"[stop-hook] BLOCKED — cannot read .completion_proof.json: {exc}",
            file=sys.stderr,
        )
        return 1

    errors: list[str] = []

    # --- Basic field validation ---
    if proof.get("status") != "PASSED":
        errors.append(f"  status={proof.get('status')!r}  (expected 'PASSED')")

    if not proof.get("invocation_id"):
        errors.append("  invocation_id is absent or empty")

    if not proof.get("tracked_scripts"):
        errors.append("  tracked_scripts is absent or empty")

    if proof.get("verify_no_jump_exit_code") != 0:
        errors.append(
            f"  verify_no_jump_exit_code="
            f"{proof.get('verify_no_jump_exit_code')!r}  (expected 0)"
        )

    if proof.get("check_gate_passed_exit_code") != 0:
        errors.append(
            f"  check_gate_passed_exit_code="
            f"{proof.get('check_gate_passed_exit_code')!r}  (expected 0)"
        )

    # --- git_commit vs HEAD ---
    head: str = ""
    try:
        head = _git_head()
        if proof.get("git_commit") != head:
            errors.append(
                f"  git_commit={str(proof.get('git_commit', ''))[:12]}…"
                f" != HEAD ({head[:12]}…)"
                " — commit changes then re-run completion_gate.py"
            )
    except RuntimeError as exc:
        errors.append(f"  could not verify git_commit: {exc}")

    # --- Independent digest verification (anti-forgery) ---
    # A fabricated proof can set any string for these fields, but this hook
    # reads the actual files on disk and recomputes their SHA256.  The proof
    # passes only when both digests match AND the artifact files are present.

    gate_digest = proof.get("gate_passed_digest", "")
    if not gate_digest:
        errors.append("  gate_passed_digest is absent or empty in proof")
    elif not MARKER_PATH.exists():
        errors.append(f"  .gate_passed artifact is missing ({MARKER_PATH})")
    else:
        actual_gate = _sha256(MARKER_PATH)
        if actual_gate != gate_digest:
            errors.append(
                f"  gate_passed_digest mismatch — "
                f"proof={gate_digest[:12]}… actual={actual_gate[:12]}… "
                f"(.gate_passed was replaced after gate ran)"
            )
        else:
            # Also validate the marker's embedded git_commit matches HEAD.
            try:
                marker = json.loads(MARKER_PATH.read_text(encoding="utf-8"))
                if head and marker.get("git_commit") != head:
                    errors.append(
                        f"  .gate_passed git_commit="
                        f"{str(marker.get('git_commit', ''))[:12]}… "
                        f"!= HEAD ({head[:12]}…)"
                    )
            except (json.JSONDecodeError, OSError) as exc:
                errors.append(f"  .gate_passed is not valid JSON: {exc}")

    signoff_digest = proof.get("signoff_digest", "")
    if not signoff_digest:
        errors.append("  signoff_digest is absent or empty in proof")
    elif not SIGNOFF_PATH.exists():
        errors.append(f"  signoff.json artifact is missing ({SIGNOFF_PATH})")
    else:
        actual_signoff = _sha256(SIGNOFF_PATH)
        if actual_signoff != signoff_digest:
            errors.append(
                f"  signoff_digest mismatch — "
                f"proof={signoff_digest[:12]}… actual={actual_signoff[:12]}… "
                f"(signoff.json was replaced after gate ran)"
            )

    if errors:
        print(
            "[stop-hook] BLOCKED — .completion_proof.json is invalid:\n"
            + "\n".join(errors)
            + "\n  Run: python scripts/completion_gate.py",
            file=sys.stderr,
        )
        return 1

    # --- Layer 7: full independent re-verification ---
    # Hash-consistent artifacts can be forged if .gate_passed and signoff.json
    # are both crafted to match their recorded digests while containing no real
    # gate evidence.  Invoking check_gate_passed.py here closes this because it
    # re-runs the actual test suite and validates real artifact content — not
    # just hashes.
    #
    # No cache: a cache stored in test_artifacts/ lives in the writable workspace
    # and can be pre-populated by an agent to skip this decisive check.  The
    # performance cost of always running check_gate_passed.py is accepted because
    # Layer 7 only fires when a valid .completion_proof.json is present, i.e. only
    # after the agent has already run completion_gate.py.
    print(
        "[stop-hook] Field/digest checks passed; invoking check_gate_passed.py "
        "for full independent re-verification…",
        file=sys.stderr,
    )
    rc = _run_check_gate_passed()
    if rc != 0:
        print(
            "[stop-hook] BLOCKED — check_gate_passed.py failed "
            "(forged or stale gate evidence).\n"
            "  Run: python scripts/completion_gate.py",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
