#!/usr/bin/env python3
"""Single-command completion enforcer for the no-jump gate.

Run this as THE ONLY completion action.  It mechanically chains:
  1. python scripts/verify_no_jump.py  (full acceptance gate)
  2. python scripts/check_gate_passed.py  (independent re-verification)
and propagates exit 1 if EITHER exits non-zero.

On success it writes test_artifacts/.completion_proof.json — a machine-readable
artifact capturing this specific run's evidence (subprocess exit codes, git HEAD,
timestamps, artifact digests).  Presence and validity of this file is the
durable completion proof; pasted stdout alone is supplemental.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT    = Path(__file__).parent.parent
MARKER_PATH  = REPO_ROOT / "test_artifacts" / ".gate_passed"
SIGNOFF_PATH = REPO_ROOT / "test_artifacts" / "signoff.json"
PROOF_PATH   = REPO_ROOT / "test_artifacts" / ".completion_proof.json"

# Reuse the strict _git_head() from verify_no_jump — raises RuntimeError,
# NEVER returns "unknown" or a stale value.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from verify_no_jump import _git_head   # noqa: E402


def _sha256(path: Path) -> str:
    h = hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()


def _run(cmd: list[str]) -> int:
    print(f"\n{'='*60}")
    print(f"[completion-gate] Running: {' '.join(cmd)}")
    print(f"{'='*60}")
    return subprocess.run(cmd, cwd=REPO_ROOT).returncode


def main() -> int:
    started_at = time.time()

    # Generate a fresh invocation ID and immediately overwrite any existing proof
    # with an IN_PROGRESS record.  This invalidates any stale proof from a prior
    # run at the same HEAD — a matching proof file alone is not enough if this
    # run fails or aborts before writing the completed proof.
    invocation_id = str(uuid.uuid4())
    PROOF_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROOF_PATH.write_text(
        json.dumps({"status": "IN_PROGRESS", "invocation_id": invocation_id}),
        encoding="utf-8",
    )
    print(f"[completion-gate] invocation_id={invocation_id}")
    print(f"[completion-gate] Prior proof (if any) replaced with IN_PROGRESS marker")

    # Step 0: Verify all gate scripts are committed to git — not just present on disk.
    # This closes the bypass where an agent creates the scripts as untracked files,
    # runs the gate (which succeeds because Python only needs the file to exist),
    # then declares done.  With this check, running from untracked scripts causes an
    # immediate exit 1 before verify_no_jump.py is even invoked.
    _REQUIRED_TRACKED = [
        "scripts/completion_gate.py",
        "scripts/verify_no_jump.py",
        "scripts/check_gate_passed.py",
        "scripts/ux_signoff_agent.py",
        "scripts/check_completion_proof_hook.py",
        "test_scripts/test_no_jump_editor_geometry.py",
        "test_scripts/test_text_editing_fidelity_suite.py",
        "test_scripts/test_completion_proof_hook.py",
        ".claude/settings.json",
    ]
    not_tracked: list[str] = []
    for script in _REQUIRED_TRACKED:
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", script],
            cwd=REPO_ROOT, capture_output=True,
        )
        if r.returncode != 0:
            not_tracked.append(script)
    if not_tracked:
        print("\n[completion-gate] FAIL — required gate files are NOT committed to git:")
        for s in not_tracked:
            print(f"  {s}")
        print("  Commit all scripts before re-running this command.")
        return 1
    print(f"[completion-gate] Confirmed {len(_REQUIRED_TRACKED)} gate files tracked in git")

    # Step 0b: Parse .claude/settings.json and confirm the stop hook is still wired.
    # Tracking the settings file is necessary but not sufficient — the hook command
    # could be removed from the JSON while the file remains tracked in git.
    _settings_path = REPO_ROOT / ".claude" / "settings.json"
    try:
        _settings = json.loads(_settings_path.read_text(encoding="utf-8"))
        _stop_entries = _settings.get("hooks", {}).get("Stop", [])
        _hook_registered = any(
            "check_completion_proof_hook.py" in hook.get("command", "")
            for entry in _stop_entries
            for hook in entry.get("hooks", [])
        )
        if not _hook_registered:
            print(
                "\n[completion-gate] FAIL — Stop hook not registered in .claude/settings.json\n"
                "  'scripts/check_completion_proof_hook.py' was removed from the Stop hooks.\n"
                "  Restore the hook entry before re-running."
            )
            return 1
        print("[completion-gate] Stop hook registration verified in .claude/settings.json")
    except (json.JSONDecodeError, OSError) as exc:
        print(f"\n[completion-gate] FAIL — cannot read .claude/settings.json: {exc}")
        return 1

    gate_rc = _run([sys.executable, "scripts/verify_no_jump.py"])
    if gate_rc != 0:
        print("\n[completion-gate] FAIL — verify_no_jump.py exited non-zero")
        print("[completion-gate] Fix the failing gates then re-run this script.")
        return 1

    check_rc = _run([sys.executable, "scripts/check_gate_passed.py"])
    if check_rc != 0:
        print("\n[completion-gate] FAIL — check_gate_passed.py exited non-zero")
        print("[completion-gate] Re-run verify_no_jump.py and this script together.")
        return 1

    # Write the completed proof — fail-closed so the success message is NEVER
    # emitted if the proof cannot be bound to HEAD and the current invocation.
    try:
        head = _git_head()  # raises RuntimeError if git unavailable — never "unknown"
    except RuntimeError as exc:
        print(f"\n[completion-gate] FAIL — cannot resolve git HEAD for proof: {exc}")
        return 1

    # Both evidence files MUST exist; if they disappeared between sub-runs and
    # proof-write, something mutated the filesystem and the proof is invalid.
    for path, name in [(MARKER_PATH, ".gate_passed"), (SIGNOFF_PATH, "signoff.json")]:
        if not path.exists():
            print(f"\n[completion-gate] FAIL — {name} missing when writing proof — "
                  f"filesystem was mutated after gate run"); return 1

    # Verify .gate_passed's recorded commit matches HEAD (final sanity check)
    try:
        marker = json.loads(MARKER_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"\n[completion-gate] FAIL — .gate_passed is not valid JSON: {exc}"); return 1
    if marker.get("git_commit") != head:
        print(f"\n[completion-gate] FAIL — .gate_passed git_commit "
              f"({str(marker.get('git_commit',''))[:12]}…) != HEAD ({head[:12]}…)"); return 1

    proof = {
        "status":                      "PASSED",
        "completion_gate_version":     "1.0",
        "invocation_id":               invocation_id,  # must match stdout
        "git_commit":                  head,
        "started_at":                  started_at,
        "finished_at":                 time.time(),
        "verify_no_jump_exit_code":    gate_rc,   # 0 — verified above
        "check_gate_passed_exit_code": check_rc,  # 0 — verified above
        "gate_passed_digest":          _sha256(MARKER_PATH),
        "signoff_digest":              _sha256(SIGNOFF_PATH),
        "tracked_scripts":             _REQUIRED_TRACKED,  # auditable: all were git-tracked at proof time
    }
    PROOF_PATH.write_text(json.dumps(proof, indent=2), encoding="utf-8")

    # Read back and validate before printing success
    try:
        written = json.loads(PROOF_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"\n[completion-gate] FAIL — proof write/read back failed: {exc}"); return 1
    if written.get("invocation_id") != invocation_id:
        print(f"\n[completion-gate] FAIL — proof invocation_id mismatch after write"); return 1
    if written.get("git_commit") != head:
        print(f"\n[completion-gate] FAIL — proof git_commit mismatch after write"); return 1
    if written.get("verify_no_jump_exit_code") != 0 or written.get("check_gate_passed_exit_code") != 0:
        print(f"\n[completion-gate] FAIL — proof exit codes invalid after write"); return 1

    print("\n[completion-gate] BOTH COMMANDS PASSED — no-jump goal is resolved")
    print(f"[completion-gate] Proof written and validated: {PROOF_PATH}")
    print(f"[completion-gate] invocation_id={invocation_id}  git_commit={head[:12]}…")
    print("[completion-gate] Paste this full output in your completion message.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
