# F3 Child Plan -- Shell / File Explorer Integration

## Goal

Add OS-level file-explorer integration so users can invoke PDF Editor from the shell context menu for supported file operations.

## Success Criteria

- Windows shell integration can register and unregister cleanly.
- Explorer right-click can open selected PDFs in this app.
- Integration changes are optional, explicit, and reversible.
- The app handles multi-file invocation safely.

## Scope

1. Define the supported OS integrations:
   - Windows Explorer context menu first
   - macOS Finder follow-up if the platform support story is acceptable
2. Add registration/unregistration scripts or commands.
3. Add app entry handling for shell-invoked file lists.
4. Document permissions, rollback, and troubleshooting.

## Out of Scope

- Deep OS-specific preview extensions.
- File-type conversion context actions in the first tranche.
- Linux desktop-environment-specific shell integrations.

## Workstreams

- OS integration scripts and packaging hooks.
- Main-entry argument handling and validation.
- UX copy and settings surface for enabling/disabling integration.
- Tests for registration logic and argument parsing.

## Risks

- Registry/Finder integration can be brittle across installation layouts.
- Per-user vs machine-wide registration needs clear ownership.
- Rollback must be reliable to avoid leaving stale shell entries behind.

## Exit Evidence

- Registration tests or dry-run verifiers for shell changes.
- Entry-point tests for single/multi-file invocation.
- Manual verification on a clean Windows profile.
