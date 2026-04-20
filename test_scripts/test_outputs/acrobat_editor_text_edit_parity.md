# Acrobat vs PDF Editor Text-Edit Parity Report (Page 5)

## Scope
- File: `TIA-942-B-2017 Rev Full.pdf`
- Page: 5
- Actions attempted: enter edit mode, type prefix, commit, undo/redo, escape/discard

## Evidence (Screenshots)

### Baselines
- Acrobat: `C:\Users\jiang\Documents\python programs\pdf_editor\tmp\tia_acrobat_before.png`
- Editor: `C:\Users\jiang\Documents\python programs\pdf_editor\tmp\tia_editor_before.png`

### Edit-mode probe and escape
- Acrobat (edit tool active, post-escape): `C:\Users\jiang\Documents\python programs\pdf_editor\tmp\tia_acrobat_after_real_escape.png`
- Editor (post-escape): `C:\Users\jiang\Documents\python programs\pdf_editor\tmp\tia_editor_after_real_escape.png`

### Commit / Undo / Redo sequence captures
- Acrobat commit: `C:\Users\jiang\Documents\python programs\pdf_editor\tmp\tia_acrobat_step1_commit.png`
- Acrobat undo: `C:\Users\jiang\Documents\python programs\pdf_editor\tmp\tia_acrobat_step2_undo.png`
- Acrobat redo: `C:\Users\jiang\Documents\python programs\pdf_editor\tmp\tia_acrobat_step3_redo.png`
- Acrobat restore/exit: `C:\Users\jiang\Documents\python programs\pdf_editor\tmp\tia_acrobat_step4_restore.png`
- Editor commit: `C:\Users\jiang\Documents\python programs\pdf_editor\tmp\tia_editor_step1_commit.png`
- Editor undo: `C:\Users\jiang\Documents\python programs\pdf_editor\tmp\tia_editor_step2_undo.png`
- Editor redo: `C:\Users\jiang\Documents\python programs\pdf_editor\tmp\tia_editor_step3_redo.png`
- Editor restore/exit: `C:\Users\jiang\Documents\python programs\pdf_editor\tmp\tia_editor_step4_restore.png`

## Notes
- Typed input was previously misdirected into the Codex input box, so only the final captured sequence is considered.
- The commit/undo/redo captures did not show visible text deltas in either app from these screenshots alone.
- Acrobat’s edit state is visually clearer (explicit text box overlays) than the editor’s.
