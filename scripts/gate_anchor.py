#!/usr/bin/env python3
"""Anchor file: records the expected SHA-256 of check_completion_proof_hook.py.

completion_gate.py reads this file's _HOOK_HASH and verifies the Stop hook's
on-disk content before running its checks.  This closes the enforcement gap
where an agent edits the Stop hook to remove its verification layers.

Trust chain (one-directional — no SHA-256 fixed-point cycle):
  completion_gate.py  →  gate_anchor.py  →  check_completion_proof_hook.py
  (pins gate_anchor       (pins the hook       (runs on every Stop event,
   via _PINNED_HASHES)     via _HOOK_HASH)      no further back-reference)

Attack surfaces closed:
  • Agent edits the Stop hook → completion_gate.py reads gate_anchor and
    recomputes the hook's SHA-256 → mismatch → gate exits 1 before the hook
    ever runs.
  • Agent edits gate_anchor to update the expected hook hash → completion_gate.py
    has gate_anchor in _PINNED_HASHES → mismatch → gate exits 1.
  • Both require editing completion_gate.py too, which is visible in git diff.

Maintenance — when check_completion_proof_hook.py changes legitimately:
  1. python -c "import hashlib,pathlib; p=pathlib.Path('scripts/check_completion_proof_hook.py'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
  2. Replace _HOOK_HASH below with the new SHA-256.
  3. python -c "import hashlib,pathlib; p=pathlib.Path('scripts/gate_anchor.py'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
  4. Replace the 'scripts/gate_anchor.py' entry in completion_gate.py _PINNED_HASHES.
  5. Document the change in docs/plans/2026-05-05-no-jump-editor-geometry-gate.md.
"""
from __future__ import annotations

_HOOK_HASH: str = "dba7d52a8c3cf5a7bf86f4ea3f9f3a29ce7840aee99572de29e5ba1093e2e8b6"
