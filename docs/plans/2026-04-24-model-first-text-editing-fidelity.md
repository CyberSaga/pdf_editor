# Model-First Text Editing Fidelity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve text-editing fidelity at the model/extraction layer so F2 opens coherent, non-overlapping, less-corrupted edit targets.

**Architecture:** Keep the existing TextHit/EditTextRequest flow. Fix extraction and grouping in model text indexing first, then rely on the existing view flow to open improved targets.

**Tech Stack:** Python, PyMuPDF (`fitz`), pytest.

---

### Task 1: Add red-light regression tests for model-first failures

**Files:**
- Modify: `test_scripts/test_char_run_reconstruction.py`

**Step 1: Add failing test for overlap pollution in paragraph target**

Add a test that hits the main paragraph in `test_files/1.pdf` and asserts paragraph-mode target text does not include `run or not run`.

**Step 2: Add failing test for replacement-character fallback**

Add a test that hits text in `test_files/1.pdf` and asserts target text does not contain `\ufffd` when page plain text has non-`\ufffd` alternatives.

**Step 3: Add failing test for rotated column grouping**

Add a test that hits `test_files/when I was young I.pdf` in paragraph mode and expects one coherent target containing `when`, `radio`, and `song`.

**Step 4: Run each new test independently**

Run:
- `python -m pytest test_scripts/test_char_run_reconstruction.py::test_1pdf_paragraph_target_excludes_overlapping_run_or_not_run -q`
- `python -m pytest test_scripts/test_char_run_reconstruction.py::test_1pdf_text_hit_does_not_contain_replacement_character_when_plain_text_has_alternative -q`
- `python -m pytest test_scripts/test_char_run_reconstruction.py::test_vertical_paragraph_groups_adjacent_columns_in_reading_order -q`

Expected: all fail on current code.

### Task 2: Implement conservative replacement-character repair

**Files:**
- Modify: `model/text_block.py`

**Step 1: Cache page plain-text lines during page index build**

Store normalized plain-text lines per page as read-only hints for repair matching.

**Step 2: Add a constrained replacement repair helper**

When a reconstructed run text contains `\ufffd`, attempt replacement only if:
- a matching plain-text line exists for the same block/line sequence,
- lengths align after whitespace normalization,
- candidate char at that position is not `\ufffd`.

**Step 3: Apply repair before finalizing each run text**

Keep fallback behavior unchanged if no safe replacement exists.

**Step 4: Re-run the replacement red-light test**

Run:
- `python -m pytest test_scripts/test_char_run_reconstruction.py::test_1pdf_text_hit_does_not_contain_replacement_character_when_plain_text_has_alternative -q`

Expected: pass.

### Task 3: Implement visual-lane paragraph grouping for overlap/vertical coherence

**Files:**
- Modify: `model/text_block.py`
- Modify: `model/pdf_model.py` (paragraph candidate usage only if needed by tests)

**Step 1: Build paragraph candidates by visual lane, not only block index**

Group runs by rotation + projected cross-axis lane with thresholds that prevent unrelated overlapping lines from merging.

**Step 2: Merge rotated adjacent columns into one paragraph when style/direction compatible**

Allow vertical columns with compatible direction/font/size/color and paragraph-like spacing to compose one paragraph in reading order.

**Step 3: Keep overlap protection intact**

Ensure overlap cluster membership for redaction still protects non-member spans.

**Step 4: Re-run overlap and rotated red-light tests**

Run:
- `python -m pytest test_scripts/test_char_run_reconstruction.py::test_1pdf_paragraph_target_excludes_overlapping_run_or_not_run -q`
- `python -m pytest test_scripts/test_char_run_reconstruction.py::test_vertical_paragraph_groups_adjacent_columns_in_reading_order -q`

Expected: pass.

### Task 4: Verification batch

**Files:**
- No new files

**Step 1: Run focused regression suites**

Run:
- `python -m pytest test_scripts/test_char_run_reconstruction.py -q`
- `python -m pytest test_scripts/test_text_extraction_line_joining.py -q`
- `python -m pytest test_scripts/test_edit_text_helpers.py test_scripts/test_track_ab_model_regressions.py -q`
- `python -m pytest test_scripts/test_text_editing_gui_regressions.py -q`

**Step 2: Run lint on touched files**

Run:
- `python -m ruff check model/text_block.py model/pdf_model.py test_scripts/test_char_run_reconstruction.py`

**Step 3: Stage only the implementation batch**

Run:
- `git add model/text_block.py model/pdf_model.py test_scripts/test_char_run_reconstruction.py docs/plans/2026-04-24-model-first-text-editing-fidelity.md`
