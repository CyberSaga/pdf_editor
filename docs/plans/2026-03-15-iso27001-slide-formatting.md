# ISO27001 Slide Formatting Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Update the generated ISO27001 SOP deck so slides 60 onward use 標楷體 36pt for the middle description box, while leaving titles and the 作業提醒 box unchanged, and switch macOS attachment encryption guidance to Keka.

**Architecture:** Keep the existing deck-generation script as the single source of truth for appendix slides. Add a regression test that inspects the generated deck for the Keka content and the target placeholder font formatting, then minimally adjust the generator to set only the middle description placeholder formatting on slides 60+.

**Tech Stack:** Python, `python-pptx`, `pytest`

---

### Task 1: Add regression coverage

**Files:**
- Modify: `test_scripts/test_iso27001_sop_update.py`
- Modify: `build/iso27001_sop_update/update_iso27001_sop.py`

**Step 1: Write the failing test**

Add assertions that:
- slides 60+ middle description placeholders use `BiauKai` / `標楷體` at `36pt`
- the macOS attachment-encryption slides reference `Keka`
- the 作業提醒 textbox does not get the same font override

**Step 2: Run test to verify it fails**

Run: `pytest test_scripts/test_iso27001_sop_update.py -q`
Expected: FAIL because the current generator still writes Disk Utility content and smaller default formatting.

**Step 3: Write minimal implementation**

Update the generator to:
- set only the content placeholder font to 標楷體 36pt on appended step slides
- preserve title and reminder box formatting
- replace macOS attachment-encryption steps with Keka-based instructions

**Step 4: Run test to verify it passes**

Run: `pytest test_scripts/test_iso27001_sop_update.py -q`
Expected: PASS

**Step 5: Regenerate the deliverable**

Run: `python build/iso27001_sop_update/update_iso27001_sop.py --source "ISO27001審查項目SOP.pptx" --output "ISO27001審查項目SOP_附件加密與隨身碟加密.pptx"`

### Task 2: Verify the deliverable artifact

**Files:**
- Modify: `ISO27001審查項目SOP_附件加密與隨身碟加密.pptx`

**Step 1: Inspect generated deck structure**

Run a Python inspection snippet to confirm:
- output deck has 80 slides
- slide 60+ content placeholders use the requested font and size
- macOS attachment section mentions `Keka`

**Step 2: Record verification evidence**

Keep the command output for the final handoff.
