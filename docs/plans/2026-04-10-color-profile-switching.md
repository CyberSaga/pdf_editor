# F4 Child Plan -- Color Profile Switching

## Goal

Add explicit color-profile conversion and switching workflows without regressing existing rendering, export, or print behavior.

## Success Criteria

- Users can inspect the document/profile state and choose a conversion target.
- Converted output is deterministic and reversible via undo/save-as flow.
- Printing/exporting preserve the chosen color intent.
- The feature fails clearly when profile data is missing or unsupported.

## Scope

1. Inventory current color handling in render/export/print paths.
2. Define supported profile conversions and where they apply.
3. Add a non-destructive workflow:
   - inspect current profile
   - preview/confirm target profile
   - save/export converted result
4. Add test fixtures for RGB/CMYK edge cases.

## Out of Scope

- Full professional prepress soft-proofing in the first tranche.
- Per-object color conversions.
- Automatic monitor calibration support.

## Workstreams

- Model/service layer for profile inspection and conversion.
- Controller orchestration for preview/commit flows.
- View UI for profile selection and confirmation.
- Tests for conversion correctness and print/export propagation.

## Risks

- Color conversion fidelity may depend on external libraries/tooling.
- Large-file conversion may be expensive.
- Mixed-profile documents may need a more complex workflow than a single toggle.

## Exit Evidence

- Fixture-based tests covering RGB/CMYK conversions and round-trips.
- Export/print tests showing converted profile intent is preserved.
- Manual verification with known-profile sample PDFs.
