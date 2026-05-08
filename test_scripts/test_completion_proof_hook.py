"""Tests for scripts/check_completion_proof_hook.py.

Covers:
  - Hook is inactive when goal file is absent (not in goal mode).
  - Hook blocks on proof absent, corrupt, wrong status, stale commit, bad
    exit codes, missing invocation_id / tracked_scripts.
  - Anti-forgery layer 1: hook independently re-hashes .gate_passed and
    signoff.json; a forged proof with fabricated digest fields is rejected.
  - Anti-forgery layer 2: even hash-consistent artifacts are rejected when
    _run_check_gate_passed() returns non-zero (i.e. check_gate_passed.py
    finds no real gate evidence).  This is the decisive enforcement layer.
  - Real-path integration: hook uses the correct GOAL_FILE path (the actual
    gate plan file), with no monkeypatching of GOAL_FILE.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_completion_proof_hook as hook_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_artifacts(
    marker_path: Path, signoff_path: Path, head: str
) -> tuple[str, str]:
    """Write fake .gate_passed and signoff.json; return (gate_digest, signoff_digest)."""
    marker_bytes = json.dumps(
        {"git_commit": head, "status": "passed", "signoff_digest": "x"}
    ).encode()
    signoff_bytes = json.dumps({"verdict": "PASS"}).encode()
    marker_path.write_bytes(marker_bytes)
    signoff_path.write_bytes(signoff_bytes)
    return _sha256_bytes(marker_bytes), _sha256_bytes(signoff_bytes)


def _valid_proof(
    git_commit: str, gate_digest: str, signoff_digest: str
) -> dict:
    return {
        "status": "PASSED",
        "invocation_id": "test-uuid-1234",
        "git_commit": git_commit,
        "tracked_scripts": ["scripts/completion_gate.py"],
        "verify_no_jump_exit_code": 0,
        "check_gate_passed_exit_code": 0,
        "gate_passed_digest": gate_digest,
        "signoff_digest": signoff_digest,
    }


@pytest.fixture()
def tmp_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect GOAL_FILE, PROOF_PATH, MARKER_PATH, SIGNOFF_PATH into tmp dir."""
    goal_file    = tmp_path / "2026-05-05-no-jump-editor-geometry-gate.md"
    proof_path   = tmp_path / ".completion_proof.json"
    marker_path  = tmp_path / ".gate_passed"
    signoff_path = tmp_path / "signoff.json"
    monkeypatch.setattr(hook_mod, "GOAL_FILE",    goal_file)
    monkeypatch.setattr(hook_mod, "PROOF_PATH",   proof_path)
    monkeypatch.setattr(hook_mod, "MARKER_PATH",  marker_path)
    monkeypatch.setattr(hook_mod, "SIGNOFF_PATH", signoff_path)
    return goal_file, proof_path, marker_path, signoff_path


# ---------------------------------------------------------------------------
# Case 1 — no goal file AND not git-tracked → exit 0 (genuinely not in goal mode)
# ---------------------------------------------------------------------------

def test_hook_exits_0_when_no_goal_file(tmp_gate, monkeypatch):
    goal_file, *_ = tmp_gate
    assert not goal_file.exists()
    # Explicitly simulate "never committed to git" so the hook stays inactive.
    monkeypatch.setattr(hook_mod, "_goal_file_tracked_in_git", lambda: False)
    assert hook_mod.main() == 0


# ---------------------------------------------------------------------------
# Case 2 — goal present, proof absent → BLOCKED
# ---------------------------------------------------------------------------

def test_hook_blocks_when_proof_absent(tmp_gate, capsys):
    goal_file, proof_path, *_ = tmp_gate
    goal_file.write_text("# goal")
    assert not proof_path.exists()
    assert hook_mod.main() == 1
    assert "BLOCKED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Case 3 — proof is corrupt JSON → BLOCKED
# ---------------------------------------------------------------------------

def test_hook_blocks_corrupt_proof(tmp_gate, capsys):
    goal_file, proof_path, *_ = tmp_gate
    goal_file.write_text("# goal")
    proof_path.write_text("{not valid json", encoding="utf-8")
    assert hook_mod.main() == 1
    assert "BLOCKED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Case 4 — wrong status → BLOCKED
# ---------------------------------------------------------------------------

def test_hook_blocks_wrong_status(tmp_gate, monkeypatch, capsys):
    goal_file, proof_path, marker_path, signoff_path = tmp_gate
    head = "a" * 40
    goal_file.write_text("# goal")
    gate_d, sig_d = _write_artifacts(marker_path, signoff_path, head)
    proof = _valid_proof(head, gate_d, sig_d)
    proof["status"] = "IN_PROGRESS"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: head)
    assert hook_mod.main() == 1
    assert "status" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Case 5 — stale git_commit → BLOCKED
# ---------------------------------------------------------------------------

def test_hook_blocks_stale_commit(tmp_gate, monkeypatch, capsys):
    goal_file, proof_path, marker_path, signoff_path = tmp_gate
    old_head = "old" + "0" * 37
    new_head = "new" + "1" * 37
    goal_file.write_text("# goal")
    gate_d, sig_d = _write_artifacts(marker_path, signoff_path, old_head)
    proof = _valid_proof(old_head, gate_d, sig_d)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: new_head)
    assert hook_mod.main() == 1
    err = capsys.readouterr().err
    assert "git_commit" in err or "HEAD" in err


# ---------------------------------------------------------------------------
# Case 6 — non-zero verify_no_jump exit code → BLOCKED
# ---------------------------------------------------------------------------

def test_hook_blocks_nonzero_exit_code(tmp_gate, monkeypatch, capsys):
    goal_file, proof_path, marker_path, signoff_path = tmp_gate
    head = "b" * 40
    goal_file.write_text("# goal")
    gate_d, sig_d = _write_artifacts(marker_path, signoff_path, head)
    proof = _valid_proof(head, gate_d, sig_d)
    proof["verify_no_jump_exit_code"] = 1
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: head)
    assert hook_mod.main() == 1
    assert "verify_no_jump_exit_code" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Case 7 — all fields valid + correct artifact digests + check_gate_passed ok
#           → EXIT 0
# ---------------------------------------------------------------------------

def test_hook_allows_valid_proof(tmp_gate, monkeypatch):
    goal_file, proof_path, marker_path, signoff_path = tmp_gate
    head = "c" * 40
    goal_file.write_text("# goal")
    gate_d, sig_d = _write_artifacts(marker_path, signoff_path, head)
    proof = _valid_proof(head, gate_d, sig_d)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: head)
    # Simulate check_gate_passed.py passing without running the real test suite.
    monkeypatch.setattr(hook_mod, "_run_check_gate_passed", lambda: 0)
    assert hook_mod.main() == 0


# ---------------------------------------------------------------------------
# Case 8 — invocation_id absent → BLOCKED
# ---------------------------------------------------------------------------

def test_hook_blocks_missing_invocation_id(tmp_gate, monkeypatch, capsys):
    goal_file, proof_path, marker_path, signoff_path = tmp_gate
    head = "d" * 40
    goal_file.write_text("# goal")
    gate_d, sig_d = _write_artifacts(marker_path, signoff_path, head)
    proof = _valid_proof(head, gate_d, sig_d)
    del proof["invocation_id"]
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: head)
    assert hook_mod.main() == 1
    assert "invocation_id" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Case 9 — tracked_scripts absent → BLOCKED
# ---------------------------------------------------------------------------

def test_hook_blocks_missing_tracked_scripts(tmp_gate, monkeypatch, capsys):
    goal_file, proof_path, marker_path, signoff_path = tmp_gate
    head = "e" * 40
    goal_file.write_text("# goal")
    gate_d, sig_d = _write_artifacts(marker_path, signoff_path, head)
    proof = _valid_proof(head, gate_d, sig_d)
    del proof["tracked_scripts"]
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: head)
    assert hook_mod.main() == 1
    assert "tracked_scripts" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Case 10 — forged minimal proof (no digest fields) → BLOCKED
#   An agent writing {"status":"PASSED","git_commit":HEAD,...} without running
#   completion_gate.py must be rejected.
# ---------------------------------------------------------------------------

def test_hook_blocks_forged_minimal_proof(tmp_gate, monkeypatch, capsys):
    goal_file, proof_path, *_ = tmp_gate
    head = "f" * 40
    goal_file.write_text("# goal")
    forged = {
        "status": "PASSED",
        "invocation_id": "fake-uuid",
        "git_commit": head,
        "tracked_scripts": ["scripts/completion_gate.py"],
        "verify_no_jump_exit_code": 0,
        "check_gate_passed_exit_code": 0,
        # gate_passed_digest and signoff_digest intentionally absent
    }
    proof_path.write_text(json.dumps(forged), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: head)
    rc = hook_mod.main()
    assert rc == 1
    err = capsys.readouterr().err
    assert "gate_passed_digest" in err or "signoff_digest" in err


# ---------------------------------------------------------------------------
# Case 11 — gate_passed_digest present in proof but .gate_passed file absent → BLOCKED
# ---------------------------------------------------------------------------

def test_hook_blocks_gate_passed_file_absent(tmp_gate, monkeypatch, capsys):
    goal_file, proof_path, marker_path, signoff_path = tmp_gate
    head = "g" * 40
    goal_file.write_text("# goal")
    _, sig_d = _write_artifacts(marker_path, signoff_path, head)
    marker_path.unlink()  # remove the file after computing digest
    proof = _valid_proof(head, "deadbeef" * 8, sig_d)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: head)
    assert hook_mod.main() == 1
    assert ".gate_passed" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Case 12 — gate_passed_digest in proof does not match actual file hash → BLOCKED
# ---------------------------------------------------------------------------

def test_hook_blocks_gate_passed_digest_mismatch(tmp_gate, monkeypatch, capsys):
    goal_file, proof_path, marker_path, signoff_path = tmp_gate
    head = "h" * 40
    goal_file.write_text("# goal")
    gate_d, sig_d = _write_artifacts(marker_path, signoff_path, head)
    proof = _valid_proof(head, gate_d, sig_d)
    # Tamper the file after writing the proof
    marker_path.write_bytes(b'{"git_commit":"' + head.encode() + b'","tampered":true}')
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: head)
    assert hook_mod.main() == 1
    err = capsys.readouterr().err
    assert "gate_passed_digest" in err and "mismatch" in err


# ---------------------------------------------------------------------------
# Case 13 — signoff.json absent despite proof claiming digest → BLOCKED
# ---------------------------------------------------------------------------

def test_hook_blocks_signoff_file_absent(tmp_gate, monkeypatch, capsys):
    goal_file, proof_path, marker_path, signoff_path = tmp_gate
    head = "i" * 40
    goal_file.write_text("# goal")
    gate_d, sig_d = _write_artifacts(marker_path, signoff_path, head)
    signoff_path.unlink()
    proof = _valid_proof(head, gate_d, sig_d)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: head)
    assert hook_mod.main() == 1
    assert "signoff.json" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Case 14 — signoff_digest in proof does not match actual signoff.json hash → BLOCKED
# ---------------------------------------------------------------------------

def test_hook_blocks_signoff_digest_mismatch(tmp_gate, monkeypatch, capsys):
    goal_file, proof_path, marker_path, signoff_path = tmp_gate
    head = "j" * 40
    goal_file.write_text("# goal")
    gate_d, sig_d = _write_artifacts(marker_path, signoff_path, head)
    proof = _valid_proof(head, gate_d, sig_d)
    # Tamper signoff.json after building proof
    signoff_path.write_bytes(b'{"verdict":"TAMPERED"}')
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: head)
    assert hook_mod.main() == 1
    err = capsys.readouterr().err
    assert "signoff_digest" in err and "mismatch" in err


# ---------------------------------------------------------------------------
# Case 15 — real goal path integration test (no GOAL_FILE monkeypatching)
#   Verifies the hook is bound to the actual plan file added in this change-set,
#   not a hypothetical future filename.
# ---------------------------------------------------------------------------

def test_hook_real_goal_path_blocks_without_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    if not hook_mod.GOAL_FILE.exists():
        pytest.skip("Real gate plan file not present in working tree")
    monkeypatch.setattr(hook_mod, "PROOF_PATH", tmp_path / ".no_proof_here.json")
    rc = hook_mod.main()
    assert rc == 1, (
        f"Expected hook to block (proof absent) but got exit 0.\n"
        f"GOAL_FILE={hook_mod.GOAL_FILE}  PROOF_PATH={tmp_path / '.no_proof_here.json'}"
    )


# ---------------------------------------------------------------------------
# Case 16 — self-consistent forged artifacts: proof + .gate_passed + signoff.json
#   are all mutually hash-consistent but check_gate_passed.py rejects them
#   (because no real test suite was run).  This is the decisive anti-forgery test.
# ---------------------------------------------------------------------------

def test_hook_blocks_self_consistent_forged_artifacts(tmp_gate, monkeypatch, capsys):
    """All hashes match but check_gate_passed.py returns 1 — must block."""
    goal_file, proof_path, marker_path, signoff_path = tmp_gate
    head = "k" * 40
    goal_file.write_text("# goal")
    # Craft mutually consistent artifacts (correct hashes, correct git_commit).
    gate_d, sig_d = _write_artifacts(marker_path, signoff_path, head)
    proof = _valid_proof(head, gate_d, sig_d)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: head)
    # Simulate check_gate_passed.py finding no real gate evidence.
    monkeypatch.setattr(hook_mod, "_run_check_gate_passed", lambda: 1)
    rc = hook_mod.main()
    assert rc == 1
    err = capsys.readouterr().err
    assert "check_gate_passed" in err


# ---------------------------------------------------------------------------
# Case 17 — check_gate_passed.py passes → hook exits 0 (positive control for case 16)
# ---------------------------------------------------------------------------

def test_hook_allows_when_check_gate_passed_succeeds(tmp_gate, monkeypatch):
    """Counterpart to case 16: when check_gate_passed.py exits 0, hook allows."""
    goal_file, proof_path, marker_path, signoff_path = tmp_gate
    head = "m" * 40
    goal_file.write_text("# goal")
    gate_d, sig_d = _write_artifacts(marker_path, signoff_path, head)
    proof = _valid_proof(head, gate_d, sig_d)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(hook_mod, "_git_head", lambda: head)
    monkeypatch.setattr(hook_mod, "_run_check_gate_passed", lambda: 0)
    assert hook_mod.main() == 0


# ---------------------------------------------------------------------------
# Case 18 — goal file deleted but still tracked in git → BLOCKED
#   Removing the plan file must NOT deactivate the gate.  The hook checks
#   git-tracked status before allowing exit 0 on a missing file.
# ---------------------------------------------------------------------------

def test_hook_blocks_when_goal_file_deleted_but_tracked(tmp_gate, monkeypatch, capsys):
    """Deleting the goal file does not bypass the hook if it is git-tracked."""
    goal_file, *_ = tmp_gate
    assert not goal_file.exists()
    # Simulate "was committed to git" even though the file is absent on disk.
    monkeypatch.setattr(hook_mod, "_goal_file_tracked_in_git", lambda: True)
    rc = hook_mod.main()
    assert rc == 1
    err = capsys.readouterr().err
    assert "BLOCKED" in err
