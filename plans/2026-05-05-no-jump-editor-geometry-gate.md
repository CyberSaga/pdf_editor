# No-Jump Editor Geometry Gate

## Hash-Pinning Section

2026-06-13: Refreshed the `scripts/gate_anchor.py` entry in
`scripts/completion_gate.py` from
`32cf4ba5fbef37b6f41decfc9224347134e25537f940954d5b6ce2ab5c40eae8` to
`94fbced9543e90a5883d9a91701f7082fd3623dfe07c4f247874eb320d4dce71`, then
to `792b98925af76420ee921e9746cf1b9fcb4319ad225fd99a332bc5c6e737f949`
after refreshing the hook hash below.

Reason: the committed `scripts/gate_anchor.py` content already hashes to
`94fbced9543e90a5883d9a91701f7082fd3623dfe07c4f247874eb320d4dce71`, while
`scripts/completion_gate.py` still carried the prior stale pin. No no-jump
threshold, scoring, signoff, or hook behavior was changed; this updates the
pin so the completion gate validates the current tracked trust-chain anchor.

The same completion-gate run then exposed a stale `_HOOK_HASH` in
`scripts/gate_anchor.py`. The committed `scripts/check_completion_proof_hook.py`
content hashes to
`26965582400cff5054ae3b1d6a75b13d101904abfd17503ef799bb153c43a794`, while
the anchor still carried
`dba7d52a8c3cf5a7bf86f4ea3f9f3a29ce7840aee99572de29e5ba1093e2e8b6`.
The anchor was updated to the current tracked hook hash, which changed
`scripts/gate_anchor.py`'s own hash to
`792b98925af76420ee921e9746cf1b9fcb4319ad225fd99a332bc5c6e737f949`.

2026-06-13: Refreshed the `scripts/verify_no_jump.py` entry in
`scripts/completion_gate.py` from
`9f591f9e81a1b30196360a31885a44650a3dc9ab81361a1fae6518709fc5bb32` to
`f852959cdf6c16af6ae3cae5ae1d8ce8fa435a96fb3aeff7685afb0f40fe9323`.

Reason: the completion gate proved the pytest no-jump cases passed, but
artifact validation rejected the three negative-control artifacts because the
validator applied the full `geom_*` matrix schema to every `geom_*` ID.
`geom_negative_control` and `geom_neg_fontsize_*` are fixed negative controls
with their own evidence fields, so `verify_no_jump.py` now validates those
explicit schemas before the generic geometry matrix branch. This preserves the
gate's artifact completeness check while making the validator match the
negative-control artifact contract.
