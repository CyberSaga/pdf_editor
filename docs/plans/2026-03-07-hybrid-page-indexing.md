# Hybrid Page Indexing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace full-document index rebuilds after structural page operations with a hybrid remap-plus-lazy-rebuild flow that keeps inserted and visible pages immediately editable without reintroducing large-PDF UI stalls.

**Architecture:** The change stays inside the current `TextBlockManager`/`PDFModel`/`PDFController` design. `TextBlockManager` learns how to track per-page cache state and remap cached entries after insert/delete; `PDFModel` uses those helpers for structural operations and on-demand rebuilds; `PDFController` drains stale pages later in small batches, following the same timer-driven yielding pattern already used for open-file indexing.

**Tech Stack:** Python 3.10, PyMuPDF (`fitz`), PySide6 timers/signals, pytest-style test scripts in `test_scripts/`

---

### Task 1: Add structural indexing regression tests

**Files:**
- Create: `test_scripts/test_structural_indexing.py`
- Modify: `model/pdf_model.py:483-489`
- Modify: `model/text_block.py:137-300`
- Test: `test_scripts/test_structural_indexing.py`

**Step 1: Write the failing tests**

```python
import fitz

from model.pdf_model import PDFModel


def _make_three_page_doc(tmp_path):
    path = tmp_path / "three-pages.pdf"
    doc = fitz.open()
    for label in ("alpha", "beta", "gamma"):
        page = doc.new_page()
        page.insert_text((72, 72), label)
    doc.save(path)
    doc.close()
    return path


def test_insert_blank_page_rebuilds_inserted_page_and_marks_shifted_pages_stale(tmp_path):
    model = PDFModel()
    model.open_pdf(str(_make_three_page_doc(tmp_path)))
    model.ensure_page_index_built(1)
    model.ensure_page_index_built(2)

    model.insert_blank_page(2)

    assert model.block_manager.page_state(0) == "clean"
    assert model.block_manager.page_state(1) == "clean"
    assert model.block_manager.page_state(2) == "stale"


def test_shifted_page_is_rebuilt_on_demand_after_delete(tmp_path):
    model = PDFModel()
    model.open_pdf(str(_make_three_page_doc(tmp_path)))
    for page_num in (1, 2, 3):
        model.ensure_page_index_built(page_num)

    model.delete_pages([1])
    assert model.block_manager.page_state(0) == "stale"

    model.ensure_page_index_built(1)
    runs = model.block_manager.get_runs(0)
    assert any("beta" in run.text for run in runs)
    assert model.block_manager.page_state(0) == "clean"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_structural_indexing.py -v`
Expected: FAIL because `TextBlockManager` has no page-state API and structural operations still rebuild the whole document.

**Step 3: Write minimal implementation scaffolding**

```python
class TextBlockManager:
    def page_state(self, page_idx: int) -> str:
        return self._page_state.get(page_idx, "missing")
```

**Step 4: Run test to verify the failure moved**

Run: `python -m pytest test_scripts/test_structural_indexing.py -v`
Expected: FAIL on stale/clean assertions until remap logic is implemented.

**Step 5: Commit**

```bash
git add test_scripts/test_structural_indexing.py model/text_block.py
git commit -m "Add structural indexing regressions"
```

### Task 2: Teach `TextBlockManager` to remap and track stale pages

**Files:**
- Modify: `model/text_block.py:137-300`
- Test: `test_scripts/test_structural_indexing.py`

**Step 1: Write the next failing tests for remap correctness**

```python
def test_shift_after_insert_relabels_cached_ids(tmp_path):
    model = PDFModel()
    model.open_pdf(str(_make_three_page_doc(tmp_path)))
    for page_num in (1, 2, 3):
        model.ensure_page_index_built(page_num)

    model.insert_blank_page(1)

    model.ensure_page_index_built(3)
    runs = model.block_manager.get_runs(2)
    assert all(run.span_id.startswith("p2_") for run in runs)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_structural_indexing.py::test_shift_after_insert_relabels_cached_ids -v`
Expected: FAIL because cached IDs still reference their old page numbers.

**Step 3: Write minimal implementation**

```python
class TextBlockManager:
    def __init__(self):
        self._page_state = {}

    def mark_stale_range(self, start_idx: int) -> None:
        for page_idx in range(start_idx, max(self._index.keys(), default=-1) + 1):
            if page_idx in self._index:
                self._page_state[page_idx] = "stale"

    def shift_after_insert(self, insert_at: int, count: int) -> None:
        new_index = {}
        for old_idx in sorted(self._index.keys(), reverse=True):
            if old_idx >= insert_at:
                new_index[old_idx + count] = self._clone_page_entry_with_new_page(old_idx, old_idx + count)
            else:
                new_index[old_idx] = self._clone_page_entry_with_new_page(old_idx, old_idx)
        self._index = {idx: entry["blocks"] for idx, entry in new_index.items()}
```

**Step 4: Expand implementation to all per-page stores**

```python
def _clone_page_entry_with_new_page(self, old_idx: int, new_idx: int) -> dict:
    blocks = [replace(block, block_id=f"page_{new_idx}_block_{block.block_id.rsplit('_', 1)[-1]}", page_num=new_idx) for block in self._index.get(old_idx, [])]
    spans = [replace(span, span_id=f"p{new_idx}_b{span.block_idx}_l{span.line_idx}_s{span.span_idx}", page_idx=new_idx) for span in self._span_index.get(old_idx, [])]
    paragraphs = self._rebuild_paragraphs(new_idx, spans)
    return {"blocks": blocks, "spans": spans, "paragraphs": paragraphs}
```

**Step 5: Run tests to verify remap behavior**

Run: `python -m pytest test_scripts/test_structural_indexing.py -v`
Expected: PASS for remap/state tests, FAIL for model/controller integration tests not implemented yet.

**Step 6: Commit**

```bash
git add model/text_block.py test_scripts/test_structural_indexing.py
git commit -m "Add page cache remap support"
```

### Task 3: Route structural page operations through remap plus immediate rebuild

**Files:**
- Modify: `model/pdf_model.py:483-489`
- Modify: `model/pdf_model.py:796-952`
- Test: `test_scripts/test_structural_indexing.py`

**Step 1: Write failing model-level tests for immediate editability**

```python
def test_inserted_page_is_immediately_editable(tmp_path):
    model = PDFModel()
    model.open_pdf(str(_make_three_page_doc(tmp_path)))

    model.insert_blank_page(2)
    model.doc[1].insert_text((72, 72), "new page text")
    model.ensure_page_index_built(2)

    runs = model.block_manager.get_runs(1)
    assert any("new page text" in run.text for run in runs)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_structural_indexing.py::test_inserted_page_is_immediately_editable -v`
Expected: FAIL until `insert_blank_page()` rebuilds the inserted page immediately.

**Step 3: Write minimal implementation**

```python
def ensure_page_index_built(self, page_num: int) -> None:
    page_idx = page_num - 1
    if page_idx < 0 or not self.doc or page_idx >= len(self.doc):
        return
    if self.block_manager.page_state(page_idx) in {"missing", "stale"}:
        self.block_manager.rebuild_page(page_idx, self.doc)


def _refresh_after_structural_change(self, immediate_pages: set[int], stale_start: int) -> None:
    for page_idx in sorted(immediate_pages):
        if 0 <= page_idx < len(self.doc):
            self.block_manager.rebuild_page(page_idx, self.doc)
    self.block_manager.mark_stale_range(stale_start)
    for page_idx in immediate_pages:
        self.block_manager.mark_clean(page_idx)
```

**Step 4: Integrate delete/insert operations**

```python
def insert_blank_page(self, position: int):
    insert_at = min(max(position - 1, 0), len(self.doc))
    self.doc.new_page(insert_at, width=width, height=height)
    self.block_manager.shift_after_insert(insert_at, 1)
    self._refresh_after_structural_change({insert_at}, insert_at + 1)
```

**Step 5: Run the focused regression suite**

Run: `python -m pytest test_scripts/test_structural_indexing.py -v`
Expected: PASS for direct structural-operation tests.

**Step 6: Commit**

```bash
git add model/pdf_model.py test_scripts/test_structural_indexing.py
git commit -m "Avoid full rebuild after page operations"
```

### Task 4: Update structural undo/redo and controller batch scheduling

**Files:**
- Modify: `model/edit_commands.py:290-333`
- Modify: `controller/pdf_controller.py:734-752`
- Modify: `controller/pdf_controller.py:571-577`
- Modify: `controller/pdf_controller.py:897-940`
- Test: `test_scripts/test_structural_indexing.py`
- Test: `test_scripts/test_multi_tab_plan.py`

**Step 1: Write failing regression tests for structural undo/redo**

```python
def test_structural_undo_marks_shifted_pages_stale_instead_of_full_rebuild(tmp_path):
    model = PDFModel()
    path = _make_three_page_doc(tmp_path)
    model.open_pdf(str(path))
    for page_num in (1, 2, 3):
        model.ensure_page_index_built(page_num)

    before = model._capture_doc_snapshot()
    model.delete_pages([1])
    after = model._capture_doc_snapshot()
    cmd = SnapshotCommand(model, "delete_pages", [1], before, after, "delete first page")

    cmd.undo()
    assert model.block_manager.page_state(0) in {"clean", "stale"}
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest test_scripts/test_structural_indexing.py::test_structural_undo_marks_shifted_pages_stale_instead_of_full_rebuild -v`
Expected: FAIL until `SnapshotCommand` stops calling `build_index()`.

**Step 3: Write minimal implementation**

```python
class SnapshotCommand:
    def execute(self) -> None:
        self._model._restore_doc_from_snapshot(self._after_bytes)
        self._model.refresh_structural_indexes(self._command_type, self._affected_pages)

    def undo(self) -> None:
        self._model._restore_doc_from_snapshot(self._before_bytes)
        self._model.refresh_structural_indexes(self._command_type, self._affected_pages)
```

**Step 4: Add controller-side stale-page draining**

```python
def _schedule_structural_index_batch(self, start: int, session_id: str, gen: int):
    stale_pages = self.model.block_manager.list_stale_pages()
    batch = stale_pages[start:start + INDEX_BATCH_SIZE]
    for page_idx in batch:
        self.model.ensure_page_index_built(page_idx + 1)
    if start + len(batch) < len(stale_pages):
        QTimer.singleShot(INDEX_BATCH_INTERVAL_MS, lambda: self._schedule_structural_index_batch(start + len(batch), session_id, gen))
```

**Step 5: Guard search correctness while stale pages remain**

```python
def search_text(self, query: str):
    self._drain_structural_stale_pages_for_search()
    results = self.model.tools.search.search_text(query)
    self.view.display_search_results(results)
```

**Step 6: Run integration tests**

Run: `python -m pytest test_scripts/test_structural_indexing.py test_scripts/test_multi_tab_plan.py -v`
Expected: PASS for structural undo/redo and controller integration coverage.

**Step 7: Commit**

```bash
git add model/edit_commands.py controller/pdf_controller.py test_scripts/test_structural_indexing.py test_scripts/test_multi_tab_plan.py
git commit -m "Batch stale index rebuild after undo"
```

### Task 5: Verify full regression coverage and document behavior

**Files:**
- Modify: `docs/solutions.md`
- Modify: `docs/FEATURES.md`
- Test: `test_scripts/test_structural_indexing.py`
- Test: `test_scripts/test_feature_conflict.py`
- Test: `test_scripts/test_deep.py`

**Step 1: Add a short docs note after implementation**

```markdown
## Structural page indexing

Page insert/delete operations now remap cached per-page text indexes, rebuild only the working set immediately, and finish the remaining pages in background batches.
```

**Step 2: Run focused regressions**

Run: `python -m pytest test_scripts/test_structural_indexing.py test_scripts/test_feature_conflict.py -v`
Expected: PASS

**Step 3: Run the broader regression sweep**

Run: `python -m pytest test_scripts/test_deep.py -v`
Expected: PASS, including structural operation and undo/redo flows.

**Step 4: Run a manual large-PDF smoke check**

Run: `python main.py`
Expected: open a large PDF, insert/delete a page, confirm the current page remains editable immediately and the UI stays responsive while background indexing completes.

**Step 5: Commit**

```bash
git add docs/solutions.md docs/FEATURES.md
git commit -m "Document hybrid page indexing"
```
