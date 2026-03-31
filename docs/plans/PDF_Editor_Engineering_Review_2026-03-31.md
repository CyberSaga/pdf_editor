

**PDF Editor — Engineering Review**

Deep Code-Level Assessment & Architectural Analysis

2026-03-31

Prepared for: CEO / Engineering Review

# **Executive Summary**

This engineering review examines the PDF editor codebase (PyMuPDF \+ PySide6) across five core modules totaling 10,851 lines of Python. The review follows the UX audit conducted on 2026-03-30 that identified three P0 bugs and two P1 issues. This document traces each bug to root-cause code, assesses overall architecture health, and provides actionable refactoring recommendations.

Overall Grade: C+ (Functional but Concerning). The application works and handles core PDF editing, but suffers from god-class anti-patterns (two classes exceed 2,800 lines each), scattered state management, inconsistent error handling, and a memory leak in the text editor widget. The undo/redo system has an unbounded memory growth risk, and the test suite (43 files) lacks framework consistency and coverage of the known bug areas.

## **Codebase at a Glance**

| Module | File | Lines | Classes | Key Concern |
| :---- | :---- | :---- | :---- | :---- |
| **View** | pdf\_view.py | 4,152 | 10 (1 god) | Monolithic PDFView: 3,242 lines, 170+ methods |
| **Model** | pdf\_model.py | 2,977 | 3 (1 god) | PDFModel: 2,857 lines, edit\_text() alone is 636 lines |
| **Block Mgr** | text\_block.py | 864 | 3 | Newline bug in paragraph builder; O(n) lookups |
| **Commands** | edit\_commands.py | 546 | 4 | Undo stack unbounded; command loss on exception |
| **Controller** | pdf\_controller.py | 2,312 | 1 | 144 methods mixing 9+ concerns |

# **1\. Architecture Assessment**

## **1.1 MVC Structure**

The project follows a classic MVC pattern: View (Qt widgets with signals) communicates through Controller (mutation coordinator) to Model (document correctness, persistence). A ToolManager provides static registration of Annotation, Watermark, Search, and OCR extensions. The design principle that "View must not directly mutate Model" is well-documented in ARCHITECTURE.md and largely upheld.

## **1.2 God Class Anti-Pattern**

The two largest classes — PDFView (3,242 lines, 170+ methods) and PDFModel (2,857 lines, 100+ methods) — each carry 6-10 distinct responsibilities. PDFView mixes UI rendering, mode management, text editing, annotation handling, search, and fullscreen logic. PDFModel combines document management, text extraction, HTML conversion, geometry calculation, snapshot management, and the 636-line edit\_text() transaction. PDFController (144 methods) similarly bundles signal wiring, rendering pipeline, printing subsystem, optimization, text editing, fullscreen mode, page operations, and session management.

**\[HIGH\] PDFView is a 3,242-line god class**

The main view class handles UI rendering, mode management, text editing widget lifecycle, annotation overlays, text selection, fullscreen logic, context menus, and drag state tracking. Over 10 boolean state flags with no state machine create risk of inconsistent combinations.

**Location:** view/pdf\_view.py:910-4152

**Recommendation:** Extract into TextEditManager (\~1,500 lines), InteractionStateManager, UILayoutController, and ModeController.

**\[HIGH\] PDFModel.edit\_text() is a 636-line monolithic method**

Five nested phases (snapshot, resolve, redact, insert, verify) with 3 exception handlers and 3 insertion strategy fallbacks. The method is too long to review, test, or maintain effectively.

**Location:** model/pdf\_model.py:2231-2861

**Recommendation:** Decompose into \_resolve\_edit\_target() (150 lines), \_execute\_redaction\_and\_insert() (250 lines), \_verify\_and\_recover() (100 lines), with edit\_text() as a 30-line orchestrator.

**\[MEDIUM\] PDFController bundles 9+ concerns in 144 methods**

Printing subsystem, optimization workers, rendering cache, session management, fullscreen state, and text editing all live in one class with 23 instance variables.

**Location:** controller/pdf\_controller.py:191-2312

**Recommendation:** Extract PrintSubsystem, RenderCacheManager, SessionStateManager as separate classes.

# **2\. Bug Root Cause Analysis**

## **2.1 BUG-001: Fullscreen Escape Trap (P0)**

When fullscreen mode is entered accidentally (e.g., by mis-clicking the "全螢幕" button adjacent to "適應畫面"), the user becomes trapped. ESC key, F11, right-click menu, and the exit button all fail to restore normal mode.

**\[CRITICAL\] ESC key may not reach the view in fullscreen**

The \_handle\_escape() method (line 2287\) checks \_fullscreen\_active first and emits sig\_toggle\_fullscreen. However, keyPressEvent (line 2344\) may not fire if a child widget holds focus in fullscreen mode. The QTextEdit editor, if open, consumes ESC before it reaches PDFView. When no editor is open, focus may land on the QGraphicsView, which has its own key handling.

**Location:** view/pdf\_view.py:2287-2347

**Recommendation:** Install a global QShortcut(Qt.Key\_Escape) on the QMainWindow that bypasses focus routing. Also add eventFilter on QApplication for fullscreen ESC as fallback.

**\[CRITICAL\] Fullscreen exit button relies on fragile hover detection**

The exit button (QToolButton) starts hidden and only appears when the mouse enters a 24px top band. Hover detection uses hardcoded geometry with adjusted(-8, \-8, 8, 8\) hit area. On macOS, the menu bar may intercept mouse events in the top band, preventing hover from triggering.

**Location:** view/pdf\_view.py:1297-1337

**Recommendation:** Make the exit button always visible in fullscreen (opacity 0.6, full opacity on hover). Remove the hover-dependent visibility logic.

**\[HIGH\] No spacing between 適應畫面 and 全螢幕 buttons**

In the right toolbar layout, fit\_view\_btn and fullscreen\_quick\_btn are placed adjacent with no spacing. A spacer is implemented as QLabel(" ") which is fragile. Users easily mis-click fullscreen.

**Location:** view/pdf\_view.py:1713-1727

**Recommendation:** Add 12px spacing or a visual separator between the two buttons. Replace QLabel(" ") with addSpacing(8).

**\[HIGH\] Context menu has no "Exit Fullscreen" option**

The right-click menu only shows "Copy Selected Text" (conditional) and "旋轉頁面". No fullscreen exit option is available as a last-resort escape mechanism.

**Location:** view/pdf\_view.py:3767-3773

**Recommendation:** Add "Exit Fullscreen" action to context menu when \_fullscreen\_active is True. Also fix menu.exec\_() call which currently invokes self.exec\_() (wrong object).

## **2.2 BUG-002: Spurious Newlines in Edited Text (P0)**

When text is edited and committed, newline characters appear between visual lines that were originally continuous. The text "The data center shall..." becomes "The data\\ncenter shall..." causing layout corruption and rendering artifacts.

**\[CRITICAL\] Fallback extraction inserts \\n after every visual line**

In the fallback text extraction path (Path 2), the code appends "\\n" unconditionally after each line in a PDF block. Since PDF "lines" are visual layout constructs (not logical paragraphs), this converts soft-wrapped text into hard line breaks. The trailing rstrip("\\n") only removes the final newline.

**Location:** model/pdf\_model.py:1265-1268

**Recommendation:** Replace unconditional newline with intelligent line-joining: check if the line ends mid-word or if the next line starts with a lowercase letter, and join with space instead of newline.

**\[CRITICAL\] Paragraph builder also inserts \\n between visual lines**

The \_build\_paragraphs() method joins line\_texts with "\\n".join(), again treating PDF visual lines as logical line breaks. This is the span-based extraction path (Path 1), so both extraction paths have the same bug independently.

**Location:** model/text\_block.py:701-749 (line 731\)

**Recommendation:** Apply the same smart line-joining heuristic: detect continuation based on vertical spacing, font size, line ending punctuation, and next-line capitalization.

## **2.3 BUG-003: Text Box Grows and Pushes Content Down (P0)**

After editing text that does not change length, the text box grows vertically by several points, pushing all subsequent content down the page. This accumulates with each edit, eventually corrupting the entire page layout.

**\[CRITICAL\] Geometry re-estimation adds unconditional \+4.0pt padding**

After insert\_htmlbox() returns, the code calculates "shrunk\_rect" by adding 4.0pt to the measured text height. This padding is always applied regardless of whether the text actually needs it. Combined with spare\_height variance from the binary search, each edit grows the box slightly.

**Location:** model/pdf\_model.py:2670-2679

**Recommendation:** Skip geometry re-estimation entirely when text content has not changed length. When it has changed, anchor the result to the original rect y1 if the new height is within 2pt of the original.

**\[HIGH\] Push-down cascade amplifies small geometry errors**

The \_push\_down\_overlapping\_text() method (189 lines) detects blocks that overlap the edited rect and shifts them down. With the \+4.0pt padding making every edit slightly taller, the cascade progressively pushes more content down the page. Tolerances (X\_TOL=5.0, Y\_GAP varying) compound the drift.

**Location:** model/pdf\_model.py:1928-2116

**Recommendation:** Gate the push-down cascade: only trigger when the height increase exceeds a meaningful threshold (e.g., \> 2 full line heights). For edits that don't change text length, skip entirely.

## **2.4 P1 Issues: Text Property Panel & Context Menu**

**\[MEDIUM\] Text property panel (text\_card) not wired to selection events**

The text\_card widget with font/size dropdowns exists in the right sidebar but only activates when entering edit\_text mode. In browse mode, selecting text does not update the panel. Apply/Cancel buttons remain enabled even when no editor is open, creating dead UI.

**Location:** view/pdf\_view.py:1997-2036, 2137-2145

**Recommendation:** Wire text\_card to a new sig\_text\_selected signal. Disable Apply/Cancel when no editor is active.

**\[MEDIUM\] Context menu has only 2 actions**

Right-click shows only "Copy Selected Text" and "旋轉頁面". Missing: Edit Text, Delete, Paste, Select All, Zoom, and mode-specific actions that users expect in a document editor.

**Location:** view/pdf\_view.py:3767-3773

**Recommendation:** Expand context menu with mode-appropriate actions. Add "Edit Text Here" in browse mode on text blocks.

# **3\. Critical Code Quality Issues**

## **3.1 Memory Leak via Instance Method Replacement**

**\[CRITICAL\] focusOutEvent monkey-patched on QTextEdit instance**

The text editor creation replaces editor.focusOutEvent with a closure that captures self and the editor. Even after self.text\_editor is set to None during finalization, the closure prevents garbage collection of both the editor widget and the PDFView reference. Each new edit session creates another leak.

**Location:** view/pdf\_view.py:3501-3504

**Recommendation:** Subclass QTextEdit with a proper signal: class TextEditSubclass(QTextEdit) with focus\_out\_requested \= Signal(). Connect/disconnect via Qt signal mechanism instead of monkey-patching.

## **3.2 Undo/Redo Command Loss on Exception**

**\[CRITICAL\] CommandManager.undo() pops before executing**

The undo stack pops the command first, then calls cmd.undo(). If undo() raises an exception, the command is already removed from the undo stack but never reaches the redo stack. The command is permanently lost — the user can neither undo nor redo it.

**Location:** model/edit\_commands.py:438-480

**Recommendation:** Peek before popping: cmd \= self.\_undo\_stack\[-1\]; cmd.undo(); self.\_undo\_stack.pop(); self.\_redo\_stack.append(cmd). This preserves the command in the undo stack if undo() fails.

## **3.3 Unbounded Undo Stack Memory Growth**

**\[HIGH\] No maximum size limit on undo/redo stacks**

Each EditTextCommand stores full page snapshot bytes (100KB-1MB per page). Each SnapshotCommand for structural operations stores entire PDF bytes twice (before \+ after). A user performing 1,000 edits on a 50-page PDF could accumulate 1GB+ of undo history. No eviction policy exists.

**Location:** model/edit\_commands.py:380-381

**Recommendation:** Implement MAX\_UNDO\_STACK\_SIZE \= 100 with LRU eviction. Consider gzip compression of snapshot bytes. For SnapshotCommand, explore delta-based storage instead of full PDF copies.

## **3.4 Silent Rollback Failure**

**\[HIGH\] edit\_text() swallows rollback exceptions with bare except:pass**

When the main edit\_text() transaction fails and attempts rollback, a generic except Exception: pass silently swallows any failure in \_restore\_page\_from\_snapshot(). If the snapshot is corrupt, the page remains in a partially edited state with no error visibility.

**Location:** model/pdf\_model.py:2846-2849

**Recommendation:** Log the rollback failure at ERROR level and raise a compound exception: "Edit failed \+ rollback failed: {original}; rollback: {rollback\_err}"

## **3.5 Non-Atomic Page Snapshot Restoration**

**\[HIGH\] \_restore\_page\_from\_snapshot() deletes then inserts**

The restore operation calls doc.delete\_page() then doc.insert\_pdf(). If delete succeeds but insert fails (e.g., corrupt snapshot bytes), the page is permanently lost. There is no transactional wrapper.

**Location:** model/pdf\_model.py:1763-1768

**Recommendation:** Implement a two-phase restore: first validate the snapshot can be opened, then delete+insert. Or keep the deleted page reference until insert is confirmed.

# **4\. State Management Analysis**

## **4.1 Boolean Flag Explosion**

PDFView maintains 10+ boolean flags for drag state, focus guards, text selection, and editing context. These flags can reach inconsistent combinations (e.g., \_drag\_pending=True and \_drag\_active=True simultaneously) because there is no state machine enforcing valid transitions. Similarly, 10+ editing-related attributes (editing\_rect, \_editing\_original\_rect, editing\_font\_name, etc.) are scattered as individual instance variables instead of being grouped in a dataclass.

**\[MEDIUM\] No state machine for drag/edit/selection modes**

Multiple boolean flags track overlapping concerns without transition validation. DragState could be NONE/PENDING/ACTIVE enum. TextEditState could be CLOSED/OPENING/OPEN/CLOSING.

**Location:** view/pdf\_view.py:1062-1113

**Recommendation:** Define state enums (DragState, TextEditState) and a TextSelectionState dataclass. Centralize state transitions with validation in setter methods.

## **4.2 Signal Parameter Complexity**

**\[MEDIUM\] sig\_edit\_text has 11 positional parameters**

The edit text signal passes 11 ordered arguments (page\_num, original\_rect, text, font, size, color, original\_text, vsl, new\_rect, span\_id, mode). Adding or reordering a parameter breaks all receivers. This is fragile and hard to maintain.

**Location:** view/pdf\_view.py:924

**Recommendation:** Replace with a dataclass: EditTextEvent with named fields. Emit Signal(EditTextEvent) instead of 11 positional args.

# **5\. Error Handling Assessment**

Error handling varies significantly across the codebase. The controller has structured patterns for some operations (encrypted PDF retry loop, print-specific PrintingError) but uses broad except Exception catches elsewhere. The view silently ignores signal disconnect failures. The model has critical gaps in rollback handling.

| Pattern | Location | Issue |
| :---- | :---- | :---- |
| **Broad except Exception** | controller:1570, model:2842 | Masks real bugs; no recovery differentiation |
| **Silent except pass** | view:2238, view:3680, model:2849 | Hides signal disconnect \+ rollback failures |
| **No try/except** | view:1764 (zoom parse) | ValueError crash on invalid user input |
| **Good: specific catch** | controller:717 (RuntimeError for encrypted PDF) | Proper retry logic |
| **Good: typed exception** | controller:1347 (PrintingError) | Clear error hierarchy for printing |

**\[MEDIUM\] No logger.warning() or logger.info() usage in view**

PDFView has 5 logger.error() calls, 2 logger.debug() calls, and zero warning or info calls. Normal operation flow is invisible. Combined with 15+ silent except:pass blocks, debugging issues in production requires stepping through code.

**Location:** view/pdf\_view.py (entire file)

**Recommendation:** Add info-level logging for key state transitions (mode changes, editor open/close, fullscreen enter/exit). Replace all except:pass with except as e: logger.warning(f"...: {e}").

# **6\. Test Coverage Assessment**

The project has 43 test files in test\_scripts/. Seven use pytest; the remaining 36 are standalone scripts with custom assertion helpers. No mocking libraries are used — all test doubles are hand-written fakes. Tests cover the happy path of the edit pipeline but have significant gaps in the known bug areas.

| Category | Files | Coverage Quality |
| :---- | :---- | :---- |
| **Text editing pipeline** | 8 | Good: covers edit\_text, empty edit, overlap, drag-move |
| **Undo/redo commands** | 2 | Moderate: tests basic stack ops but not exception paths |
| **Printing subsystem** | 6 | Good: subprocess isolation, dialog logic, controller flow |
| **PDF operations (merge, optimize)** | 3 | Moderate: workflow tests, no edge cases |
| **GUI regressions** | 2 | Limited: text editing focus, no fullscreen tests |
| **Performance & stress** | 3 | Good: render speed, large PDF handling, optimization benchmarks |

## **6.1 Critical Coverage Gaps**

**\[HIGH\] No tests for fullscreen mode transitions**

BUG-001 (fullscreen escape trap) has zero test coverage. No tests verify that ESC exits fullscreen, that the exit button appears on hover, or that mode normalization works during fullscreen entry.

**Location:** test\_scripts/ (none)

**Recommendation:** Add test\_fullscreen\_transitions.py testing: enter/exit via button, ESC key, toggle\_fullscreen(), mode normalization on entry, and state restoration on exit.

**\[HIGH\] No tests for line-joining logic**

BUG-002 (spurious newlines) has no tests that verify text extraction preserves continuous text. The newline-vs-space decision in both extraction paths is untested.

**Location:** model/pdf\_model.py:1265-1268, model/text\_block.py:731

**Recommendation:** Add test\_text\_extraction\_line\_joining.py with PDFs containing: single-line text, wrapped paragraphs, multi-column layouts, and bullet lists to verify correct newline/space decisions.

**\[HIGH\] No tests for geometry stability across edits**

BUG-003 (text box growth \+ push-down cascade) has no regression tests. No test verifies that editing text without changing content preserves the original bounding box geometry.

**Location:** model/pdf\_model.py:2670-2679, 1928-2116

**Recommendation:** Add test\_edit\_geometry\_stability.py that performs N identical edits and asserts rect.y1 drift \< 0.5pt.

**\[MEDIUM\] Undo stack exception paths untested**

CommandManager.undo() command-loss bug (pop before execute) has no test. No test verifies behavior when undo() or redo() raises an exception mid-operation.

**Location:** model/edit\_commands.py:438-480

**Recommendation:** Add test\_command\_manager\_exception\_safety.py with a mock command that raises on undo().

# **7\. Magic Numbers & Hardcoded Constants**

The codebase contains 15+ hardcoded numeric constants scattered across methods with no centralized configuration. Different methods use inconsistent values for similar purposes (e.g., 5.0pt vs 2.0pt for Y-tolerance). None are documented or tunable at runtime.

| Value | Location(s) | Purpose | Risk |
| :---- | :---- | :---- | :---- |
| **\+4.0 pt** | model:2542, 2671 | Geometry shrink padding | Direct cause of BUG-003 |
| **0.5 pt** | model:1213, 1226, 2352 | Overlap tolerance for hit detection | May miss thin spans |
| **5.0 pt** | model:1954, 1975 | X-tolerance, Y-margin in push-down | Inconsistent with 2.0pt elsewhere |
| **2.0 pt** | model:1973, 2144 | Y-tolerance thresholds | Different from 5.0pt in same algorithm |
| **24 px** | view:1329 | Fullscreen top band for hover detection | Too small on HiDPI displays |
| **0.88 / 0.90** | model:2740, 2748 | Verification similarity thresholds | Empirical; not tunable |
| **0.40** | model:2733 | Complex script similarity threshold | Very low; may accept bad edits |
| **100 px** | view:1724 | Toolbar minimum width | Arbitrary; should be calculated |

**\[MEDIUM\] No centralized constants configuration**

All constants are scattered as inline literals. Changing the geometry padding requires finding every occurrence of "4.0" in a 2,977-line file.

**Location:** model/pdf\_model.py, view/pdf\_view.py (throughout)

**Recommendation:** Create a GeometryConstants class with SHRINK\_PADDING\_PT, OVERLAP\_TOLERANCE, Y\_TOLERANCE\_PT, etc. Create a UIConstants class for FULLSCREEN\_BAND\_HEIGHT, TOOLBAR\_MIN\_WIDTH, etc.

# **8\. Prioritized Recommendations**

## **8.1 Immediate (Week 1): Fix the Bugs**

These fixes address the three P0 bugs identified in the UX audit. Each can be done independently.

| \# | Fix | File:Lines | Effort | Impact |
| :---- | :---- | :---- | :---- | :---- |
| **1** | Global ESC shortcut \+ always-visible exit button | view:1297-1337, 2287-2347 | 4h | Fixes BUG-001 |
| **2** | Smart line-joining in both extraction paths | model:1265-1268, text\_block:731 | 6h | Fixes BUG-002 |
| **3** | Skip re-estimation for no-change edits; anchor to original rect | model:2670-2679 | 4h | Fixes BUG-003 |
| **4** | Gate push-down cascade on meaningful height increase | model:1928-2116 | 3h | Prevents BUG-003 cascade |
| **5** | Add 12px spacing between fit\_view\_btn and fullscreen\_quick\_btn | view:1713-1727 | 0.5h | Prevents accidental fullscreen |
| **6** | Add "Exit Fullscreen" to context menu | view:3767-3773 | 1h | Last-resort escape |

## **8.2 Short-Term (Weeks 2-3): Safety & Stability**

| \# | Fix | File:Lines | Effort | Impact |
| :---- | :---- | :---- | :---- | :---- |
| **7** | Fix memory leak: subclass QTextEdit instead of monkey-patching | view:3501-3504 | 4h | Prevents OOM over time |
| **8** | Fix undo: peek before pop in CommandManager | edit\_commands:438-480 | 2h | Prevents command loss |
| **9** | Add undo stack size limit (MAX=100) with LRU eviction | edit\_commands:380 | 3h | Prevents memory bloat |
| **10** | Log rollback failures instead of except:pass | model:2846-2849 | 1h | Error visibility |
| **11** | Add regression tests for all 3 P0 bugs | test\_scripts/ (new) | 8h | Prevent regressions |

## **8.3 Medium-Term (Month 2): Architecture Refactoring**

| \# | Refactoring | Scope | Effort | Impact |
| :---- | :---- | :---- | :---- | :---- |
| **12** | Extract TextEditManager from PDFView | view:3440-3766 \+ related | 3 days | SRP; testability |
| **13** | Decompose edit\_text() into 4 phase methods | model:2231-2861 | 2 days | Readability; maintainability |
| **14** | Introduce state enums and dataclasses | view:1062-1113 | 2 days | Eliminate boolean flag explosion |
| **15** | Centralize constants in config classes | model \+ view | 1 day | Tunable; documented |
| **16** | Standardize error handling patterns | All files | 2 days | Consistent; debuggable |
| **17** | Migrate test suite to pytest with fixtures | test\_scripts/ | 3 days | Maintainable; CI-ready |

# **9\. Quantitative Metrics**

| Metric | Value | Target | Status |
| :---- | :---- | :---- | :---- |
| **Total source lines** | 10,851 | \< 15,000 | OK |
| **Largest class (PDFView)** | 3,242 lines | \< 500 lines | FAIL |
| **Largest method (edit\_text)** | 636 lines | \< 50 lines | FAIL |
| **Methods in largest class** | 170+ | \< 30 | FAIL |
| **Boolean state flags** | 10+ | 0 (use enums) | FAIL |
| **Magic number constants** | 15+ | 0 (use config) | FAIL |
| **Test files** | 43 | 50+ | NEAR |
| **Tests using pytest** | 7 / 43 | 43 / 43 | FAIL |
| **Fullscreen test coverage** | 0 tests | 5+ tests | FAIL |
| **Line-joining test coverage** | 0 tests | 3+ tests | FAIL |
| **Geometry stability tests** | 0 tests | 3+ tests | FAIL |
| **logger.error() calls** | 30 | \< 20 (more info/warning) | WARN |
| **Silent except:pass blocks** | 8+ | 0 | FAIL |

# **Appendix: File Reference**

| File | Key Lines | Content |
| :---- | :---- | :---- |
| **view/pdf\_view.py** | 1297-1337 | Fullscreen exit button \+ hover logic |
| **view/pdf\_view.py** | 1697-1727 | Right toolbar layout (button spacing) |
| **view/pdf\_view.py** | 1997-2036 | Text property panel (text\_card) |
| **view/pdf\_view.py** | 2287-2347 | ESC handling \+ keyPressEvent |
| **view/pdf\_view.py** | 3440-3507 | Text editor widget creation |
| **view/pdf\_view.py** | 3501-3504 | focusOutEvent monkey-patch (LEAK) |
| **view/pdf\_view.py** | 3617-3766 | Text edit finalization |
| **view/pdf\_view.py** | 3767-3773 | Context menu (2 actions only) |
| **model/pdf\_model.py** | 1197-1283 | get\_text\_info\_at\_point() dual paths |
| **model/pdf\_model.py** | 1265-1268 | Newline bug (fallback extraction) |
| **model/pdf\_model.py** | 1479-1510 | \_convert\_text\_to\_html() |
| **model/pdf\_model.py** | 1928-2116 | \_push\_down\_overlapping\_text() |
| **model/pdf\_model.py** | 2231-2861 | edit\_text() transaction (636 lines) |
| **model/pdf\_model.py** | 2670-2679 | Geometry re-estimation (+4.0pt) |
| **model/pdf\_model.py** | 2846-2849 | Silent rollback failure |
| **model/text\_block.py** | 701-749 | \_build\_paragraphs() newline join |
| **model/edit\_commands.py** | 52-199 | EditTextCommand (snapshot undo) |
| **model/edit\_commands.py** | 357-546 | CommandManager (undo/redo stacks) |
| **model/edit\_commands.py** | 438-480 | undo() pop-before-execute bug |
| **controller/pdf\_controller.py** | 635-639 | toggle\_fullscreen() |
| **controller/pdf\_controller.py** | 1442-1573 | edit\_text() controller entry |

