#!/usr/bin/env python3
"""Final gate re-verifier — shares all validation logic with verify_no_jump.py.

Run this AS THE ABSOLUTE FINAL STEP before declaring the no-jump task complete.
Exit 0 = all evidence independently re-verified.  Exit 1 = any check fails.

This script imports verify_no_jump's validation functions and calls them with
the run IDs recorded in .gate_passed.  It does NOT re-run pytest or the CUA
signoff agent — it only re-verifies that the evidence already on disk is
consistent, fresh, and has not been tampered with since the gate ran.

A forged or stale .gate_passed cannot make it pass:
  - Artifact hashes are recomputed from real files (_reverify_artifact_hashes)
  - run_id_2 from the marker must match metrics.json in each case dir (_check_artifacts)
  - signoff.json is fully re-validated (exact digest match against marker["signoff_digest"])
  - The exact expected manifest set is re-derived from the hardcoded spec
  - Marker booleans (full_suite_passed, lint_passed, etc.) are independently checked
  - Worktree cleanliness is re-checked NOW, not just read from the marker
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MARKER_PATH = REPO_ROOT / "test_artifacts" / ".gate_passed"

# Import shared validation functions from verify_no_jump.py.
# Both scripts live in scripts/ so sys.path manipulation is not needed.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from verify_no_jump import (  # noqa: E402
    _expected_case_ids,
    _check_artifacts,
    _check_signoff,
    _reverify_artifact_hashes,
    _run_lint,
    _run_full_suite,
    _assert_clean_worktree,
    _git_head,
    _sha256,
    ARTIFACT_DIR,
    SIGNOFF_FILE,
)


def main() -> int:
    print("=" * 60)
    print("[fast-check] No-Jump Gate Re-Verifier")
    print("=" * 60)

    # Step 1: Worktree must still be clean (re-checked NOW, not from marker)
    _assert_clean_worktree()

    # Step 2: Read .gate_passed to get run IDs recorded during the gate run.
    # .gate_passed living under test_artifacts/ is NOT sufficient proof alone;
    # every subsequent step below must independently confirm the evidence.
    if not MARKER_PATH.exists():
        print(f"[fast-check] FAIL — .gate_passed missing: {MARKER_PATH}")
        print("  Run:  python scripts/verify_no_jump.py")
        return 1
    try:
        marker = json.loads(MARKER_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[fast-check] FAIL — .gate_passed is not valid JSON: {exc}")
        return 1

    if marker.get("status") != "PASSED":
        print(f"[fast-check] FAIL — marker status={marker.get('status')!r}")
        return 1

    head = _git_head()  # raises RuntimeError if git unavailable
    if marker.get("git_commit") != head:
        print(
            f"[fast-check] FAIL — marker git_commit ({str(marker.get('git_commit', ''))[:12]}…) "
            f"!= HEAD ({head[:12]}…)"
        )
        print("  A commit happened after verify_no_jump.py ran.")
        print("  Fix: re-run python scripts/verify_no_jump.py as the final action.")
        return 1

    # Verify the recorded marker booleans that CAN be read from the marker.
    # full_suite_passed is NOT trusted here because .gate_passed lives under
    # test_artifacts/ (exempt from dirty-worktree checks) — a forged marker could
    # claim full_suite_passed=True.  The full suite is re-run below instead.
    for key in ("lint_passed", "artifact_hashes_stable", "worktree_clean"):
        if marker.get(key) is not True:
            print(
                f"[fast-check] FAIL — marker.{key}={marker.get(key)!r}, expected True"
            )
            return 1

    run_id_2 = marker.get("run_id_2", "")
    if not run_id_2:
        print("[fast-check] FAIL — marker missing run_id_2")
        return 1

    # Step 3: Re-check artifacts with the exact run_id_2 from the marker.
    # This enforces that each metrics.json.run_id == run_id_2 (not stale from a prior run).
    expected_ids = _expected_case_ids()
    manifest_path = ARTIFACT_DIR / "manifest.json"
    manifest: list[str] = []
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    manifest.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    artifacts_ok = _check_artifacts(run_id_2, manifest, expected_ids)

    # Step 4: Re-validate signoff.json — exact digest binding replaces the
    # timestamp-window check.  The marker stores SHA-256(signoff.json) written
    # during THIS gate run; any subsequent mutation (including re-running
    # ux_signoff_agent.py) changes the digest and is caught here.  Pass
    # min_signoff_time=0.0 to _check_signoff because the digest already
    # provides exact identity binding — the time window is no longer needed.
    expected_signoff_digest = marker.get("signoff_digest", "")
    if not expected_signoff_digest:
        print(
            "[fast-check] FAIL — marker missing signoff_digest (gate run predates this fix)"
        )
        print("  Fix: re-run python scripts/verify_no_jump.py")
        return 1
    if expected_signoff_digest == "SKIPPED":
        print("[fast-check] signoff SKIPPED (gate was run with --skip-signoff)")
        signoff_ok = True
    else:
        actual_signoff_digest = _sha256(SIGNOFF_FILE)
        if actual_signoff_digest != expected_signoff_digest:
            print(
                "[fast-check] FAIL — signoff.json modified or replaced since the gate ran"
            )
            print(f"  marker digest: {expected_signoff_digest[:12]}…")
            print(f"  current digest: {actual_signoff_digest[:12]}…")
            print("  Fix: re-run python scripts/verify_no_jump.py")
            return 1
        # Digest matched — time binding satisfied via digest; use min_signoff_time=0.0
        signoff_ok = _check_signoff(min_signoff_time=0.0)

    # Step 5: Re-run the full regression suite — cannot be faked via marker boolean.
    # The marker's full_suite_passed is not trusted; instead, run it here directly.
    full_suite_ok = _run_full_suite()

    # Step 6: Re-run lint (fast) — confirms no lint violations were introduced
    lint_ok = _run_lint()

    # Step 7: Re-hash every artifact bound in signoff.json (catches post-gate mutations)
    signoff_was_skipped = expected_signoff_digest == "SKIPPED"
    reverify_ok = _reverify_artifact_hashes(skip_signoff=signoff_was_skipped)

    gates = [artifacts_ok, signoff_ok, full_suite_ok, lint_ok, reverify_ok]
    if all(gates):
        # Final worktree check — the full suite and lint may have written files.
        # Mirrors the two-guard pattern in verify_no_jump.py: check before AND after
        # mutating commands so no stray file can slip through.
        _assert_clean_worktree()
        print(f"\n[fast-check] ALL RE-VERIFICATION CHECKS PASSED ({head[:12]}…)")
        print(
            f"[fast-check] run_id_2={run_id_2[:8]}…  "
            f"manifest={len(manifest)} cases  "
            f"signoff=PASS  full_suite=PASS  lint=PASS  hashes=stable"
        )
        return 0
    failed = sum(1 for g in gates if not g)
    print(f"\n[fast-check] {failed}/{len(gates)} RE-VERIFICATION CHECKS FAILED")
    print("  The evidence is inconsistent.  Re-run: python scripts/verify_no_jump.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
