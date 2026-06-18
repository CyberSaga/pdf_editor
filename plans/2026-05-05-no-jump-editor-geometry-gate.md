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

2026-06-16: Refreshed two stale pins in `scripts/completion_gate.py`:
`scripts/check_gate_passed.py` from
`6c9304abf17891de4dd3c30301472443f08d5c724f953b19799bb173e5ca6544` to
`b539b3ceba8ac51b0cd287ed52387e5a1041e300171ec935a2d22b84f7c1838d`, and
`scripts/ux_signoff_agent.py` from
`bf4d1034857c5700a67c4d246d9b1c3fb06df606b543e49a4f388909f36a3705` to
`40d4cc6ff03246c15e6c86e4787c39ec7a884d7c75c2fa6f577dbdf65d7f9cc6`.

Reason: the R-series refactor campaign legitimately edited both gate scripts but
omitted the matching pin updates, so the completion gate had been aborting at
Step 0a (and the proof stayed stale at pre-campaign commit `1a4a527`). The edits
were pure hygiene with NO threshold/scoring/enforcement change, verified by diff:
`check_gate_passed.py` only dropped an unused `import subprocess` (R1 ruff F401,
commit `4e6f755`); `ux_signoff_agent.py` only replaced an import-time `sys.exit(1)`
on a missing optional `pyautogui` with `pyautogui = None` + a lazy
`_require_pyautogui()` use-site (R0 collection-abort fix, commit `6f16ec2`). The
threshold-encoding files (`test_no_jump_editor_geometry.py`,
`test_text_editing_fidelity_suite.py`, `verify_no_jump.py`) and the trust-chain
anchor still match their pins — nothing security-critical moved.

2026-06-18 (R6.2): Refreshed the `scripts/verify_no_jump.py` entry in
`scripts/completion_gate.py` from
`f852959cdf6c16af6ae3cae5ae1d8ce8fa435a96fb3aeff7685afb0f40fe9323` to
`a037795ff0f9dd7b6a6f86131e21b1c8f1b54706128f5831e55233668834fe42`.

Reason: R6.2 removed three stale `--ignore` lines from `_run_full_suite`
(`test_multi_tab_plan.py`, `test_ocr_e2e.py`, `test_render_colorspace.py`),
which had been excluded as "missing fixtures" but now pass/skip cleanly under
`.venv` (re-audited: 72 passed / 9 skipped). This **widens** the gate's
full-suite coverage — the opposite of threshold loosening — so the pin refresh
is legitimate. The change is confined to the ignore list + its comment; no
no-jump geometry threshold, scoring, artifact schema, signoff, or hook behavior
was touched (verified by diff). The other threshold-encoding files and the
trust-chain anchor still match their pins.
