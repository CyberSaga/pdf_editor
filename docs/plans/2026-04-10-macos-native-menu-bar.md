# UX7 Child Plan -- macOS Native Menu Bar

## Goal

Make the app feel native on macOS by adopting the expected menu-bar conventions and platform behaviors.

## Success Criteria

- The app uses the global macOS menu bar correctly.
- Standard app/file/edit/window/help menus map to existing actions.
- Common shortcuts follow macOS expectations where they differ from Windows/Linux.
- The implementation is isolated so non-macOS behavior does not regress.

## Scope

1. Audit current QAction structure against macOS menu-bar expectations.
2. Add a macOS-specific menu-bar assembly path.
3. Normalize menu ownership for:
   - app/about/preferences/quit
   - file/open/save/print
   - edit/undo/redo/copy/paste when available
   - view/window/help
4. Verify shortcut aliases and full-screen/window behavior on macOS.

## Out of Scope

- A full platform-wide visual redesign.
- Native Touch Bar or Finder integration in the first tranche.
- Cross-platform menu refactors unrelated to macOS correctness.

## Workstreams

- QAction inventory and reusable menu assembly helpers.
- macOS platform detection and menu-bar wiring.
- Shortcut parity review.
- Manual macOS validation pass.

## Risks

- Qt behavior on macOS can differ subtly for menu ownership and shortcuts.
- Existing Windows/Linux assumptions may leak into the menu structure.
- This work is hard to validate without real macOS access.

## Exit Evidence

- Menu assembly tests where practical.
- Documented manual macOS verification checklist.
- No regressions to Windows/Linux action wiring.
