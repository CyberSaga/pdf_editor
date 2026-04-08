# CLAUDE.md — PDF Editor Agent Harness

## 1. Project Identity

A desktop PDF editor targeting Acrobat-level UX parity.

- **Language:** Python 3.9+
- **GUI:** PySide6 ≥ 6.4 (Qt signals, QThread, QGraphicsScene)
- **PDF engine:** PyMuPDF ≥ 1.23 (`fitz`)
- **Architecture:** MVC + ToolManager extensions
- **Entry point:** `main.py`

## 2. Layer Dependency Rules (hard constraints)

```
View  →(signals)→  Controller  →  Model  →  ToolManager
```

- View **never** calls Model directly; it only emits signals.
- Controller is the sole mutation coordinator between View and Model.
- Model owns document correctness; it never imports Qt widgets.
- ToolManager handles annotation/watermark/search/OCR extensions only; it does not own sessions.
- `main.py` is the only file that instantiates all three layers together.

**Violation = CI failure.** Do not propose architecture that crosses these boundaries.

## 3. Coding Standards

- Variables and functions: `snake_case`. Classes: `PascalCase`.
- Background work: `QThread` + Qt Signals only. No `threading.Thread` on the Qt main thread.
- Logging: call `logging.getLogger(__name__)` in each module. Never call `logging.basicConfig(...)` outside `main.py`.
- No bare `except:` — catch the most specific exception you can.
- Font sizes: always `float` (PyMuPDF returns floats; coercing to `int` silently truncates).
- Type annotations: use modern syntax (`list`, `dict`, `X | None`) — not `typing.List`, `typing.Optional`, etc. All modules must start with `from __future__ import annotations`.
- Every top-level package directory must have an `__init__.py`.

### 3.1 Tooling (enforced via `pyproject.toml`)

```bash
pip install -e ".[dev]"       # install ruff, mypy, pytest
ruff check .                  # lint — must pass before commit
ruff check --fix .            # auto-fix safe issues
ruff format .                 # format (import ordering, whitespace)
mypy model/ utils/            # type-check (gradual — strict on new modules)
pytest                        # test suite
```

New code must pass `ruff check` with zero violations. Existing violations (113 remaining) are tracked for gradual cleanup.

## 4. Context Loading Protocol

At the start of any session involving structural changes or new features:

1. Read `docs/ARCHITECTURE.md` — understand current module responsibilities and API contracts.
2. Read `docs/PITFALLS.md` — check for known failure modes in the area you are about to touch.
3. Read `TODOS.md` — check priority/dependency before starting new work.

Do not make assumptions about module APIs without reading the relevant source file first.

## 5. Development Workflow (Middleware rules)

### 5.1 Red-Light First (mandatory)

Before writing any implementation code:

1. Write the unit test(s) that the feature must satisfy.
2. **Run the tests and show the failing output (Red).** Do not proceed until failure is confirmed.
3. Implement the feature until tests pass (Green).
4. If a test passes before any implementation exists, the test is invalid — rewrite it.

### 5.2 Assertion Density

Tests must check **state changes and side effects**, not only return values.

- Include edge cases: empty input, page boundary, invalid type.
- Mock external I/O (file system, network) but not the PyMuPDF document object unless unavoidable.
- Prefer integration-style tests for Model methods over pure mocks.

### 5.3 Architecture Validation

Before committing a structural change (new module, refactor, dependency change):

- Confirm the change does not introduce a cross-layer call.
- If a new module is added or a responsibility moves, update `docs/ARCHITECTURE.md` in the same commit.

## 6. Post-Task Protocol (Persistent Memory)

After completing any non-trivial task:

1. **Update `docs/PITFALLS.md`** with any non-obvious failure modes discovered (e.g. Qt threading gotchas, PyMuPDF quirks, PySide6 signal issues).
2. **Update `docs/ARCHITECTURE.md`** if module structure, public APIs, or responsibilities changed.
3. **Update `TODOS.md`** — mark completed items, add new items discovered during implementation.

Format for PITFALLS.md entries:
```
## <short title>
**Area:** <module or subsystem>
**Symptom:** what went wrong
**Cause:** why it happened
**Fix:** what resolves it
**File:** where the fix lives
```

## 7. Definition of Done

A task is complete when:

- [ ] `ruff check .` passes with zero new violations.
- [ ] All existing tests pass (`pytest` with no regressions).
- [ ] A failing test log was shown before implementation began.
- [ ] New tests cover the added/changed behavior.
- [ ] `docs/ARCHITECTURE.md` is current (update if structure changed).
- [ ] `docs/PITFALLS.md` is updated with any new gotchas.
- [ ] `TODOS.md` reflects current task status.

## 8. Plan as First-Class Artifact

For tasks larger than a single function change:

1. Write `docs/plans/<feature-name>.md` with: goal, affected modules, step list, open questions.
2. Update the plan as you go — record decisions made and dead ends hit.
3. On completion, move the plan to `docs/plans/archive/` and summarize the key architectural decision in `docs/ARCHITECTURE.md`.

## 9. Known Pitfall Areas

> Quick index — details in `docs/PITFALLS.md`

- **PySide6 threading:** UI mutations from non-main threads crash silently; always use Signals.
- **PyMuPDF font sizes:** `span["size"]` is `float`; coercing to `int` corrupts fractional sizes.
- **Continuous mode rendering:** `change_scale` must rebuild the full scene, not a single page.
- **Text index lifecycle:** call `model.ensure_page_index_built(page_num)` before any edit/search; structural ops mark pages `"stale"` rather than eagerly rebuilding.
- **Controller activation:** `PDFController.__init__()` must stay cheap; all signal wiring goes in `PDFController.activate()`.
