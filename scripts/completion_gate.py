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
import argparse
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


def main(skip_signoff: bool = False) -> int:
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
        "scripts/gate_anchor.py",
        "scripts/verify_no_jump.py",
        "scripts/check_gate_passed.py",
        "scripts/ux_signoff_agent.py",
        "scripts/check_completion_proof_hook.py",
        "scripts/codex_session_guard.py",
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

    # Step 0a: Hash-pin the test files and gate scripts that encode the
    # acceptance thresholds (0.5px geometry, 1% pixel diff, 1px floor) and
    # enforcement logic.  An agent that loosens an assertion in any pinned
    # file MUST also update the matching SHA-256 below; that update is a
    # visible diff in this script that a human reviewer will catch.
    #
    # When a legitimate edit changes one of these files:
    #   1. Re-run: python scripts/_print_pinned_hashes.py   (or the inline
    #      one-liner from the no-jump plan body's hash-pinning section)
    #   2. Replace the affected entry below with the new SHA-256.
    #   3. Document the change in the plan so the human review chain has a
    #      paper trail explaining why the threshold/scoring code moved.
    #
    # If only some pinned files have legitimately changed, ONLY those entries
    # should be updated — leave the rest alone so unrelated tampering still
    # registers as a mismatch.
    # Trust chain: this gate pins gate_anchor.py (below), and gate_anchor.py
    # records the expected SHA-256 of check_completion_proof_hook.py.  Step 0c
    # reads gate_anchor and verifies the hook's on-disk content.  This is
    # intentionally one-directional (gate → gate_anchor → hook) to avoid an
    # unsolvable SHA-256 fixed-point cycle that mutual pinning would create.
    _PINNED_HASHES: dict[str, str] = {
        "test_scripts/test_no_jump_editor_geometry.py":   "407a95fc7a395111ad24321a08736903d9f8f3cc1b4904af235a7e1284df843c",
        "test_scripts/test_text_editing_fidelity_suite.py": "e78f07bba51757444acefa5cec12bd9734fda5227465f3dfb2345762be8942fb",
        "test_scripts/test_completion_proof_hook.py":     "7f40c39fbf9033a57db048bf544957df3a5cb8ef97d2aa1ea7c9e984a318bd96",
        "scripts/verify_no_jump.py":                      "9f591f9e81a1b30196360a31885a44650a3dc9ab81361a1fae6518709fc5bb32",
        "scripts/check_gate_passed.py":                   "6c9304abf17891de4dd3c30301472443f08d5c724f953b19799bb173e5ca6544",
        "scripts/codex_session_guard.py":                 "7b50b60331ee1fb5b9849a79fee5966fcfd584980ae7a37d78b1acb305b4cfb2",
        "scripts/ux_signoff_agent.py":                    "bf4d1034857c5700a67c4d246d9b1c3fb06df606b543e49a4f388909f36a3705",
        "scripts/gate_anchor.py":                         "32cf4ba5fbef37b6f41decfc9224347134e25537f940954d5b6ce2ab5c40eae8",
    }
    hash_mismatches: list[str] = []
    for rel, expected in _PINNED_HASHES.items():
        path = REPO_ROOT / rel
        if not path.exists():
            hash_mismatches.append(f"  {rel}: file missing on disk")
            continue
        actual = _sha256(path)
        if actual != expected:
            hash_mismatches.append(
                f"  {rel}:\n"
                f"    expected: {expected}\n"
                f"    actual:   {actual}"
            )
    if hash_mismatches:
        print(
            "\n[completion-gate] FAIL — pinned file hashes do not match.\n"
            "  An agent edited one of the threshold-encoding files without "
            "updating its pinned hash here.\n"
            "  This is the trip-wire for silent threshold loosening.\n"
            "  Mismatches:"
        )
        for m in hash_mismatches:
            print(m)
        print(
            "\n  If this change is legitimate: update _PINNED_HASHES in "
            "scripts/completion_gate.py with the new SHA-256 and document the "
            "reason in docs/plans/2026-05-05-no-jump-editor-geometry-gate.md "
            "(hash-pinning section).  Then re-run this command."
        )
        return 1
    print(f"[completion-gate] Confirmed {len(_PINNED_HASHES)} pinned-hash files match expected SHA-256")

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

    # Step 0c: Verify Stop hook content via gate_anchor.py.
    # gate_anchor.py is already hash-pinned (Step 0a), so its _HOOK_HASH value
    # is trustworthy.  Reading the hook's expected hash from there — rather than
    # hardcoding it here — breaks the circular dependency (gate ↔ hook) that
    # makes mutual SHA-256 pinning mathematically unsolvable.
    try:
        import importlib.util as _ilu
        _anchor_spec = _ilu.spec_from_file_location(
            "gate_anchor", REPO_ROOT / "scripts" / "gate_anchor.py"
        )
        _anchor_mod = _ilu.module_from_spec(_anchor_spec)  # type: ignore[arg-type]
        _anchor_spec.loader.exec_module(_anchor_mod)        # type: ignore[union-attr]
        _expected_hook_hash: str = _anchor_mod._HOOK_HASH
    except Exception as exc:
        print(f"\n[completion-gate] FAIL — cannot load gate_anchor.py: {exc}")
        return 1
    _hook_path = REPO_ROOT / "scripts" / "check_completion_proof_hook.py"
    if not _hook_path.exists():
        print("\n[completion-gate] FAIL — check_completion_proof_hook.py is missing on disk")
        return 1
    _actual_hook_hash = _sha256(_hook_path)
    if _actual_hook_hash != _expected_hook_hash:
        print(
            "\n[completion-gate] FAIL — Stop hook content has been modified.\n"
            f"  gate_anchor.py expected: {_expected_hook_hash}\n"
            f"  actual on disk:          {_actual_hook_hash}\n"
            "  If this change is legitimate: update gate_anchor.py _HOOK_HASH "
            "with the new SHA-256, then update gate_anchor.py's own hash in "
            "scripts/completion_gate.py _PINNED_HASHES."
        )
        return 1
    print("[completion-gate] Stop hook content verified via gate_anchor.py")

    verify_cmd = [sys.executable, "scripts/verify_no_jump.py"]
    if skip_signoff:
        verify_cmd.append("--skip-signoff")
    gate_rc = _run(verify_cmd)
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

    # .gate_passed MUST exist.  signoff.json only required when signoff was not skipped.
    if not MARKER_PATH.exists():
        print(f"\n[completion-gate] FAIL — .gate_passed missing when writing proof — "
              f"filesystem was mutated after gate run"); return 1
    if not skip_signoff and not SIGNOFF_PATH.exists():
        print(f"\n[completion-gate] FAIL — signoff.json missing when writing proof — "
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
        "signoff_digest":              "SKIPPED" if skip_signoff else _sha256(SIGNOFF_PATH),
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
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--skip-signoff", action="store_true",
                     help="Skip the UX signoff step (for environments without OPENAI_API_KEY)")
    _args = _ap.parse_args()
    sys.exit(main(skip_signoff=_args.skip_signoff))
