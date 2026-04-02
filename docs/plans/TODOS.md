# TODOS

## Acrobat Baseline For UX Audit

- What: Set up at least one test environment with Adobe Acrobat available for side-by-side UX benchmarking against this PDF editor.
- Why: The planned "Acrobat-level" audit depends on direct baseline comparison for task time, shortcut parity, focus behavior, and recovery UX. This device does not currently have Acrobat installed, so local parity testing is blocked.
- Pros: Enables real benchmark runs instead of internal-only scoring; prevents false claims of Acrobat-level smoothness; gives us a control app for ambiguous UX judgments.
- Cons: Requires access to a licensed/installable Acrobat environment; adds setup overhead before the full audit can be completed.
- Context: Existing GUI audits in this repo already cover many text-editing and focus/undo regressions, but they only validate this app in isolation. The missing Acrobat baseline means we can measure "good" or "bad" internally, but not "Acrobat-like" with confidence.
- Depends on / blocked by: Acrobat installation or access to another Windows machine/VM with Acrobat; final parity audit should stay blocked until that baseline environment exists.
