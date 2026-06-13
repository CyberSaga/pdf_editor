# Deskew Size Explanation and Build Readiness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Explain why deskew can greatly increase PDF size, surface that warning in the UI, and document the build-environment dependency refresh needed before the next PyInstaller build.

**Architecture:** Treat deskew size growth as expected behavior for the current rasterizing implementation, not as a model rewrite. Add a non-blocking toolbar tooltip and documentation updates; keep existing dependency floors because `requirements.txt` and `pyproject.toml` already declare `Pillow>=12.2.0` and `numpy>=1.21`.

**Tech Stack:** PySide6 toolbar actions/tooltips, Markdown docs, pytest.

---

## Current Touchpoints

- `view/pdf_view.py`: page toolbar action for `拉正頁面`.
- `docs/PITFALLS.md`: operational pitfalls and known behavior explanations.
- `docs/FEATURES.md` or `docs/README.md`: user-facing feature docs.
- `requirements.txt`, `pyproject.toml`: dependency floors already present.
- Tests: `test_scripts/test_theme_and_icons.py`, `test_scripts/test_security_pillow_floor.py`, `test_scripts/test_startup_heavy_imports.py`.

## Required Behavior

- The `拉正頁面` action must explain that deskew rasterizes the page into an image and can increase file size.
- The explanation should recommend `另存為最佳化的副本` with `平衡` when file size matters.
- Documentation must explain the root cause: `straighten_page()` renders the page to an RGB image, inserts a full-page bitmap, and replaces the original vector/text page content.
- Release/build notes must instruct maintainers to refresh `.venv` with `Pillow>=12.2.0` and `numpy` before the next PyInstaller build.
- Do not change deskew algorithm or optimizer behavior in this phase.

## Task 1: Add Deskew Tooltip

**Files:**
- Modify: `view/pdf_view.py`
- Test: `test_scripts/test_theme_and_icons.py`

**Step 1: Write failing test**

Extend or add a test near `test_straighten_action_has_icon`:

```python
def test_straighten_action_warns_about_size_growth(qapp):
    view = PDFView()
    try:
        actions = [
            a
            for tb in view._collect_toolbars()
            for a in tb.actions()
            if a.text() == "拉正頁面"
        ]
        assert actions
        tooltip = actions[0].toolTip()
        assert "檔案大小" in tooltip
        assert "最佳化" in tooltip
        assert "平衡" in tooltip
    finally:
        view.deleteLater()
```

**Step 2: Run failing test**

```powershell
pytest -q test_scripts/test_theme_and_icons.py -k straighten
```

Expected: fails because the action has no deskew size tooltip.

**Step 3: Implement**

In `_setup_toolbar()`, keep a handle to the straighten action:

```python
self._action_straighten_page = tb_page.addAction("拉正頁面", self._straighten_current_page)
self._action_straighten_page.setToolTip(
    "拉正會將頁面轉成影像，檔案大小可能增加；若在意大小，請使用「另存為最佳化的副本」的「平衡」設定。"
)
```

Do not change the action text, because icon mapping and tests depend on it.

**Step 4: Verify**

```powershell
pytest -q test_scripts/test_theme_and_icons.py -k straighten
```

Expected: pass.

**Step 5: Atomic commit**

```powershell
git add -- view/pdf_view.py test_scripts/test_theme_and_icons.py
git commit -m "feat(ui): warn about deskew size growth"
```

## Task 2: Document Deskew Size Growth

**Files:**
- Modify: `docs/PITFALLS.md`
- Modify: `docs/FEATURES.md`
- Optional Modify: `docs/README.md`

**Step 1: Add docs section**

In `docs/PITFALLS.md`, add a section named:

```markdown
## Deskew Can Increase File Size
```

Include these facts:

- `PDFModel.straighten_page()` is designed for scanned/photographed pages.
- It rasterizes the current page into a full-page RGB image.
- It inserts that bitmap back into the document and removes/replaces the original page content.
- Vector text and compact PDF drawing operations become pixels.
- A larger output file is therefore expected.
- Use `另存為最佳化的副本` with `平衡` after deskew when size matters.

**Step 2: Update user-facing feature docs**

In `docs/FEATURES.md`, under page straightening/deskew or page operations, add one sentence:

```markdown
Deskew/拉正 is image-based and can increase file size; save an optimized copy with the 平衡 preset afterward when size matters.
```

If `docs/README.md` has a page editing feature list, add the same short note there. Do not duplicate long implementation detail in README.

**Step 3: Verify docs mention the key terms**

Run:

```powershell
rg -n "Deskew Can Increase File Size|拉正.*檔案大小|平衡" docs/PITFALLS.md docs/FEATURES.md docs/README.md
```

Expected: shows new entries.

**Step 4: Atomic commit**

```powershell
git add -- docs/PITFALLS.md docs/FEATURES.md docs/README.md
git commit -m "docs: explain deskew size growth"
```

## Task 3: Add Build Readiness Checklist

**Files:**
- Modify: `docs/README.md`
- Optional Modify: `docs/README.zh-TW.md`
- Test: `test_scripts/test_security_pillow_floor.py`, `test_scripts/test_startup_heavy_imports.py`

**Step 1: Update build docs**

Near the PyInstaller command in `docs/README.md`, add:

```markdown
Before rebuilding the packaged app, refresh the build environment dependencies:

`.venv\Scripts\python -m pip install -U "Pillow>=12.2.0" numpy`

Then rebuild with PyInstaller so the shipped artifact matches `requirements.txt`.
```

Add the same note to `docs/README.zh-TW.md` if the build section exists there.

**Step 2: Verify dependency files already satisfy floor**

Run:

```powershell
pytest -q test_scripts/test_security_pillow_floor.py
```

Expected: pass.

**Step 3: Verify startup lazy imports still hold**

Run:

```powershell
pytest -q test_scripts/test_startup_heavy_imports.py
```

Expected: pass. This guards that documenting/build-bundling Pillow/numpy does not reintroduce eager imports.

**Step 4: Atomic commit**

```powershell
git add -- docs/README.md docs/README.zh-TW.md
git commit -m "docs: document build dependency refresh"
```

## Phase Verification

Run:

```powershell
pytest -q test_scripts/test_theme_and_icons.py test_scripts/test_page_deskew.py test_scripts/test_page_deskew_scope.py test_scripts/test_security_pillow_floor.py test_scripts/test_startup_heavy_imports.py
```

Expected: all pass.

## Notes For Implementer

- Do not add a modal warning to every deskew operation unless the user asks; it would slow a normal page operation.
- Do not alter `straighten_page()` rasterization in this phase.
- Do not downgrade or move Pillow/numpy requirements.
- The `.venv` refresh command is documentation/release checklist work; do not run it unless the user explicitly asks for a build.
