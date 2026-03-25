# PDF Merge Feature Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a modal PDF merge workflow on the `頁面` tab that always includes the current document in a reorderable list and supports both save-as-new and merge-into-current outcomes.

**Architecture:** The view owns a modal `MergePdfDialog` and a small dialog session model that manages rows, reorder state, and button enablement. The controller orchestrates validation, password retries, rejection messages, progress UI, and outcome branching. The model composes merged documents from ordered sources and applies the result either to a new file or the active session.

**Tech Stack:** Python, PySide6, PyMuPDF (`fitz`), pytest

---

### Task 1: Add merge-session state primitives

**Files:**
- Create: `model/merge_session.py`
- Test: `test_scripts/test_pdf_merge_workflow.py`

**Step 1: Write the failing test**

```python
def test_merge_session_keeps_current_entry_locked_and_appends_new_files():
    session = MergeSessionModel(current_label="Current.pdf", current_source_id="active")

    session.add_files(["B.pdf", "C.pdf"])

    assert [entry.display_name for entry in session.entries] == ["Current.pdf", "B.pdf", "C.pdf"]
    assert session.entries[0].locked is True
    assert session.remove_selected([0]) == []
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_pdf_merge_workflow.py::test_merge_session_keeps_current_entry_locked_and_appends_new_files -q`
Expected: FAIL because `MergeSessionModel` does not exist yet.

**Step 3: Write minimal implementation**

```python
@dataclass
class MergeEntry:
    display_name: str
    source_kind: str
    path: str | None = None
    locked: bool = False


class MergeSessionModel:
    def __init__(self, current_label: str, current_source_id: str):
        self.entries = [MergeEntry(display_name=current_label, source_kind="current", path=current_source_id, locked=True)]

    def add_files(self, paths: list[str]) -> None:
        for path in paths:
            self.entries.append(MergeEntry(display_name=Path(path).name, source_kind="file", path=path))

    def remove_selected(self, indexes: list[int]) -> list[MergeEntry]:
        ...
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_scripts/test_pdf_merge_workflow.py::test_merge_session_keeps_current_entry_locked_and_appends_new_files -q`
Expected: PASS

**Step 5: Commit**

```bash
git add model/merge_session.py test_scripts/test_pdf_merge_workflow.py
git commit -m "feat: add merge session model"
```

### Task 2: Add the modal merge dialog and page-tab entry point

**Files:**
- Modify: `view/pdf_view.py`
- Modify: `controller/pdf_controller.py`
- Test: `test_scripts/test_pdf_merge_workflow.py`

**Step 1: Write the failing test**

```python
def test_page_toolbar_opens_merge_dialog_with_current_file_seeded(mvc, monkeypatch, tmp_path):
    model, view, controller = mvc
    path = _make_pdf(tmp_path / "Current.pdf", ["alpha"])
    controller.open_pdf(str(path))

    observed = {}

    def fake_exec(self):
        observed["entries"] = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        return QDialog.Rejected

    monkeypatch.setattr("view.pdf_view.MergePdfDialog.exec", fake_exec)

    view._open_merge_dialog()

    assert observed["entries"] == ["Current.pdf"]
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_pdf_merge_workflow.py::test_page_toolbar_opens_merge_dialog_with_current_file_seeded -q`
Expected: FAIL because merge dialog entry point does not exist.

**Step 3: Write minimal implementation**

```python
class MergePdfDialog(QDialog):
    def __init__(self, parent=None, session: MergeSessionModel | None = None):
        ...
        self.list_widget = QListWidget()
        self.select_button = QPushButton("選擇檔案")
        self.delete_button = QPushButton("刪除檔案")
        self.confirm_button = QPushButton("確認合併")
```

```python
self._action_merge_pdf = tb_page.addAction("合併PDF", self._open_merge_dialog)
```

```python
self.view.sig_merge_pdfs_requested.connect(self.start_merge_pdfs)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_scripts/test_pdf_merge_workflow.py::test_page_toolbar_opens_merge_dialog_with_current_file_seeded -q`
Expected: PASS

**Step 5: Commit**

```bash
git add view/pdf_view.py controller/pdf_controller.py test_scripts/test_pdf_merge_workflow.py
git commit -m "feat: add merge dialog entry point"
```

### Task 3: Implement dialog behavior and validation state

**Files:**
- Modify: `model/merge_session.py`
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_pdf_merge_workflow.py`

**Step 1: Write the failing test**

```python
def test_confirm_disabled_when_only_invalid_removable_entries_remain():
    session = MergeSessionModel(current_label="Current.pdf", current_source_id="active")
    session.mode = "new_file"
    session.add_files(["bad.pdf"])
    session.mark_rejected("bad.pdf", "not a pdf")

    assert session.can_confirm is False
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_pdf_merge_workflow.py::test_confirm_disabled_when_only_invalid_removable_entries_remain -q`
Expected: FAIL because rejection state and confirm rules are incomplete.

**Step 3: Write minimal implementation**

```python
class MergeEntry:
    ...
    status: str = "pending"
    message: str = ""


class MergeSessionModel:
    ...
    @property
    def can_confirm(self) -> bool:
        if self.mode == "merge_current":
            return any(entry.status != "rejected" for entry in self.entries)
        return any(entry.source_kind == "file" and entry.status != "rejected" for entry in self.entries)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_scripts/test_pdf_merge_workflow.py::test_confirm_disabled_when_only_invalid_removable_entries_remain -q`
Expected: PASS

**Step 5: Commit**

```bash
git add model/merge_session.py view/pdf_view.py test_scripts/test_pdf_merge_workflow.py
git commit -m "feat: add merge dialog validation rules"
```

### Task 4: Implement merge orchestration in controller and model

**Files:**
- Modify: `controller/pdf_controller.py`
- Modify: `model/pdf_model.py`
- Test: `test_scripts/test_pdf_merge_workflow.py`

**Step 1: Write the failing test**

```python
def test_merge_into_current_replaces_active_document_in_list_order(mvc, tmp_path, monkeypatch):
    model, view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["current"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["extra"])
    controller.open_pdf(str(current))

    controller.merge_ordered_sources_into_current([
        {"source_kind": "file", "path": str(extra)},
        {"source_kind": "current"},
    ])

    text = "".join(model.doc[i].get_text("text") for i in range(len(model.doc)))
    assert "extra" in text
    assert "current" in text
    assert model.has_unsaved_changes()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_pdf_merge_workflow.py::test_merge_into_current_replaces_active_document_in_list_order -q`
Expected: FAIL because merge orchestration is missing.

**Step 3: Write minimal implementation**

```python
def compose_merged_document(self, ordered_sources: list[dict]) -> fitz.Document:
    merged = fitz.open()
    for source in ordered_sources:
        if source["source_kind"] == "current":
            merged.insert_pdf(self.doc)
        else:
            with fitz.open(source["path"]) as src:
                merged.insert_pdf(src)
    return merged
```

```python
def replace_active_document(self, new_doc: fitz.Document) -> None:
    ...
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_scripts/test_pdf_merge_workflow.py::test_merge_into_current_replaces_active_document_in_list_order -q`
Expected: PASS

**Step 5: Commit**

```bash
git add controller/pdf_controller.py model/pdf_model.py test_scripts/test_pdf_merge_workflow.py
git commit -m "feat: add ordered pdf merge orchestration"
```

### Task 5: Add password retry, rejection reporting, and brand-new save flow

**Files:**
- Modify: `controller/pdf_controller.py`
- Modify: `view/pdf_view.py`
- Modify: `model/pdf_model.py`
- Test: `test_scripts/test_pdf_merge_workflow.py`

**Step 1: Write the failing test**

```python
def test_password_protected_file_retries_then_skips_on_cancel(mvc, tmp_path, monkeypatch):
    model, view, controller = mvc
    prompts = iter(["wrong", None])
    monkeypatch.setattr(view, "ask_pdf_password", lambda path: next(prompts))

    messages = []
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *_args: messages.append(_args[-1]))

    result = controller._resolve_merge_source({"source_kind": "file", "path": "locked.pdf"})

    assert result is None
    assert any("密碼錯誤" in msg for msg in messages)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test_scripts/test_pdf_merge_workflow.py::test_password_protected_file_retries_then_skips_on_cancel -q`
Expected: FAIL because retry/skip logic is not extracted for merge.

**Step 3: Write minimal implementation**

```python
def _resolve_merge_source(self, entry: dict):
    password = None
    while True:
        try:
            return self.model.open_merge_source(entry["path"], password=password)
        except RuntimeError as exc:
            ...
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest test_scripts/test_pdf_merge_workflow.py::test_password_protected_file_retries_then_skips_on_cancel -q`
Expected: PASS

**Step 5: Commit**

```bash
git add controller/pdf_controller.py view/pdf_view.py model/pdf_model.py test_scripts/test_pdf_merge_workflow.py
git commit -m "feat: handle merge source validation errors"
```

### Task 6: Run focused verification

**Files:**
- Test: `test_scripts/test_pdf_merge_workflow.py`
- Test: `test_scripts/test_main_startup_behavior.py`

**Step 1: Run merge workflow tests**

Run: `python -m pytest test_scripts/test_pdf_merge_workflow.py -q`
Expected: PASS

**Step 2: Run startup regression smoke**

Run: `python -m pytest test_scripts/test_main_startup_behavior.py -q`
Expected: PASS

**Step 3: Commit**

```bash
git add view/pdf_view.py controller/pdf_controller.py model/pdf_model.py model/merge_session.py test_scripts/test_pdf_merge_workflow.py docs/plans/2026-03-11-pdf-merge-feature-design.md docs/plans/2026-03-11-pdf-merge-feature.md
git commit -m "feat: add pdf merge workflow"
```
