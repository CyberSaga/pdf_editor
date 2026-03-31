**PDF EDITOR — CODE-LEVEL IMPROVEMENT PLAN**

*Derived from 2026-03-30 UX Audit  ·  Five bugs traced to source code*

# **1\. Source File Map**

All bugs trace to three core files. The table below provides a quick reference for the rest of this document.

| Shorthand | Full Path | Lines of Interest |
| :---- | :---- | :---- |
| **pdf\_view.py** | view/pdf\_view.py | 1297-1376, 1697-1717, 2287-2290, 2344-2347, 3440-3766, 3767-3773 |
| **pdf\_model.py** | model/pdf\_model.py | 1197-1283, 1479-1510, 2231-2861 |
| **text\_block.py** | model/text\_block.py | 701-749 (\_build\_paragraphs) |
| **edit\_commands.py** | model/edit\_commands.py | 52-199 (EditTextCommand), 357-546 (CommandManager) |
| **pdf\_controller.py** | controller/pdf\_controller.py | 274, 635-639, 1442-1573 |

# **2\. BUG-001 \[P0\] — Unescapable 全螢幕 Clean-View Trap**

## **Root Cause Analysis**

The code DOES have three exit paths for fullscreen mode: (1) an Escape key handler at pdf\_view.py:2287-2290 via \_handle\_escape(), (2) an 'X' QToolButton built at pdf\_view.py:1297-1309, and (3) the 全螢幕 button itself acting as a toggle. During live testing, NONE of these worked. The likely reason is a focus-routing issue: when fullscreen activates via showFullScreen() at pdf\_view.py:1375, the keyboard focus shifts to the graphics\_view viewport, and the QShortcut context (Qt.WidgetWithChildrenShortcut at pdf\_view.py:1509) may not propagate Escape events from the viewport back to the main window's keyPressEvent handler at line 2344\.

The 'X' exit button (pdf\_view.py:1297-1309) is hidden by default and relies on a hover-detection mechanism: it only becomes visible when the mouse enters the top 24px band of the window. The call \_set\_fullscreen\_exit\_button\_visible(False) at line 1373 starts it hidden. If the hover event filter doesn't fire correctly in fullscreen (common in Qt 6 on macOS), the button never appears.

## **Fix Plan**

**Fix 2.1 — Guarantee Escape works in fullscreen**

File: pdf\_view.py, around line 1375 (inside enter\_fullscreen\_ui)

After showFullScreen(), explicitly call self.setFocus(Qt.ActiveWindowFocusReason) to ensure the main window holds keyboard focus. Then verify QShortcut fires by adding an installEventFilter on the graphics\_view that forwards Escape to \_handle\_escape().

\# After line 1375: self.showFullScreen()  
self.setFocus(Qt.ActiveWindowFocusReason)  
self.activateWindow()  \# ensure macOS brings us to front

**Fix 2.2 — Always-visible exit button (not hover-dependent)**

File: pdf\_view.py, line 1373 (inside enter\_fullscreen\_ui)

Change \_set\_fullscreen\_exit\_button\_visible(False) to \_set\_fullscreen\_exit\_button\_visible(True). The button should always be visible in fullscreen, not require hover discovery.

\# Line 1373: change False \-\> True  
self.\_set\_fullscreen\_exit\_button\_visible(True)  \# always visible in fullscreen

**Fix 2.3 — Add padding between page counter and 全螢幕 button**

File: pdf\_view.py, between lines 1716-1717

Insert a fixed-width spacer (QWidget with setFixedWidth(16)) between fit\_view\_btn and fullscreen\_quick\_btn in the right\_layout to prevent accidental clicks.

\# Between lines 1716-1717:  
spacer \= QWidget()  
spacer.setFixedWidth(16)  
right\_layout.addWidget(spacer)  
right\_layout.addWidget(self.fullscreen\_quick\_btn)

**Fix 2.4 — Add 'Exit Fullscreen' to context menu**

File: pdf\_view.py, line 3772 (inside \_show\_context\_menu)

\# Add before '旋轉頁面' action:  
if self.\_fullscreen\_active:  
    menu.addAction('退出全螢幕', self.sig\_toggle\_fullscreen.emit)  
    menu.addSeparator()

# **3\. BUG-002 \[P0\] — Mid-Word Line Breaks in Edit Box**

## **Root Cause Analysis**

Two code paths inject hard newlines between PDF visual lines, treating each line as a paragraph:

**Path A — Fallback extraction in pdf\_model.py:1265-1268**

for line in block.get('lines', \[\]):  
    for span in line.get('spans', \[\]):  
        full\_text.append(span.get('text', ''))  
    full\_text.append('\\n')   \# \<-- Hard break after every visual line

This iterates over PyMuPDF's dict-mode text blocks. Each 'line' is a visual line in the PDF (one row of glyphs), NOT a semantic paragraph. Appending '\\n' after every visual line means words split across lines (like 'serve th\\ne public') get a hard newline mid-word.

**Path B — Paragraph builder in text\_block.py:726-731**

line\_texts: list\[str\] \= \[\]  
for line\_idx in sorted(line\_map.keys()):  
    parts \= \[seg.text.strip() for seg in ...\]  
    if parts:  
        line\_texts.append(' '.join(parts))  
para\_text \= '\\n'.join(line\_texts).strip()  \# \<-- Hard break between visual lines

Same problem: visual lines are joined with '\\n' instead of spaces.

## **Fix Plan**

**Fix 3.1 — Smart line joining in fallback extraction**

File: pdf\_model.py, lines 1265-1270

Replace the per-line '\\n' with a space, and only insert '\\n' when there is a genuine paragraph break (detected by a vertical gap exceeding the line height).

prev\_y1 \= None  
for line in block.get('lines', \[\]):  
    if prev\_y1 is not None:  
        line\_y0 \= line\['bbox'\]\[1\]  
        line\_height \= line\['bbox'\]\[3\] \- line\['bbox'\]\[1\]  
        gap \= line\_y0 \- prev\_y1  
        if gap \> line\_height \* 0.5:  \# paragraph break  
            full\_text.append('\\n')  
        else:  
            \# Same paragraph — join with space  
            if full\_text and not full\_text\[-1\].endswith(' '):  
                full\_text.append(' ')  
    for span in line.get('spans', \[\]):  
        full\_text.append(span.get('text', ''))  
    prev\_y1 \= line\['bbox'\]\[3\]

**Fix 3.2 — Smart line joining in paragraph builder**

File: text\_block.py, line 731

Replace '\\n'.join(line\_texts) with ' '.join(line\_texts). The paragraph builder already groups lines by block\_idx, so all lines within a block are one paragraph.

\# Line 731: change \\n to space  
para\_text \= ' '.join(line\_texts).strip()  \# space-join, not newline-join

**Fix 3.3 — Preserve original line breaks in commit path**

File: pdf\_model.py, \_convert\_text\_to\_html() around lines 1479-1510

When the user's edited text is committed back to the PDF via insert\_htmlbox(), the text must be re-wrapped to match the original bounding-box width. This is already handled by insert\_htmlbox() which reflows text within the specified Rect. No change needed here if Fixes 3.1 and 3.2 are applied.

# **4\. BUG-003 \[P0\] — Position Drift / Layout Corruption on Click-Outside**

## **Root Cause Analysis**

The text commit flow (triggered by focusOutEvent at pdf\_view.py:3501-3504) calls \_finalize\_text\_edit\_impl() which emits sig\_edit\_text. The controller then calls model.edit\_text() which performs a five-step transaction:

1. Step 0 (line 2316): Capture page snapshot for rollback.  
2. Step 1 (lines 2319-2429): Resolve target text block via BlockManager.  
3. Step 2 (lines 2436-2457): REDACT the entire old text block with page.add\_redact\_annot() \+ page.apply\_redactions().  
4. Step 3 (lines 2459-2679): INSERT new text via page.insert\_htmlbox() with three fallback strategies.  
5. Step 4 (lines 2682-2789): Verify insertion via text comparison.

**The critical drift sources are:**

**Source A — Geometry re-estimation in Step 3 (pdf\_model.py:2670-2679)**

After insert\_htmlbox(), spare\_height is used to compute the new y1. The formula 'computed\_y1 \= y0 \+ (rect.height \- spare\_height) \+ 4.0' introduces a \+4.0pt padding that may not match the original block height. Additionally, 'max(computed\_y1, base\_y1)' ensures the block never shrinks, but can cause it to GROW if spare\_height is less than expected.

**Source B — Push-down cascade (pdf\_model.py:1928-2116)**

\_push\_down\_overlapping\_text() detects blocks that overlap the newly inserted text and moves them downward. If the new block is even slightly taller than the original (due to Source A), this cascade shifts ALL subsequent blocks on the page. Each pushed block is itself re-inserted via insert\_htmlbox(), compounding geometry errors.

**Source C — Font rendering variance**

The pre-push probe (line 2521-2560) runs on a temporary page. Font metrics on a temp page can differ from the main page if fonts are subset-embedded differently. This causes height estimates to be wrong.

## **Fix Plan**

**Fix 4.1 — Preserve original geometry for no-op edits**

File: pdf\_view.py, \_finalize\_text\_edit\_impl() around line 3639

If new\_text \== original\_text, emit a 'no change' signal and skip the entire model.edit\_text() call. This prevents geometry re-estimation when no actual text change occurred.

\# After line 3639-3640:  
new\_text \= editor.toPlainText()  
if new\_text \== self.\_editing\_original\_text and not position\_changed:  
    self.\_cleanup\_editor()  \# just remove the widget  
    return  \# no change, skip model.edit\_text() entirely

**Fix 4.2 — Use original block rect as anchor, not re-estimated rect**

File: pdf\_model.py, around line 2674

When text changes, still use the original block's x0/y0 as the anchor. Only adjust y1 if the new text is actually longer. Remove the \+4.0pt padding and instead use the original block's y1 as the default, only growing if spare\_height proves the text overflows.

\# Replace lines 2670-2679 with:  
text\_used\_height \= new\_layout\_rect.height \- spare\_height  
if text\_used\_height \> (base\_y1 \- new\_layout\_rect.y0):  
    \# Text grew: extend y1 to fit  
    computed\_y1 \= new\_layout\_rect.y0 \+ text\_used\_height \+ 1.0  
else:  
    \# Text fits in original height: keep original y1  
    computed\_y1 \= base\_y1

**Fix 4.3 — Gate the push-down cascade**

File: pdf\_model.py, \_push\_down\_overlapping\_text() around line 1928

Only trigger push-down if the new block rect is actually TALLER than the old block rect by more than a threshold (e.g. 2pt). Currently, even sub-pixel height differences trigger a full cascade.

\# At the start of \_push\_down\_overlapping\_text():  
height\_delta \= new\_rect.height \- old\_rect.height  
if height\_delta \< 2.0:  \# less than 2pt growth  
    return  \# no push-down needed

**Fix 4.4 — Undo must restore block geometry, not just page content**

File: edit\_commands.py, EditTextCommand.undo() around line 174

The current undo restores the entire page from a snapshot and rebuilds the BlockManager. This should work for content restoration. If it's failing during testing (10x Cmd+Z had no effect), the issue may be that the CommandManager's undo stack is empty because \_finalize\_text\_edit() is being called multiple times (re-entrancy). Verify the \_finalizing guard at line 3617 is robust.

# **5\. P1 Issues — Font Panel & Context Menu**

## **Fix 5.1 — Wire text\_card to selection events**

File: pdf\_view.py, \_on\_text\_selection\_released() around lines 3209-3239

After storing the selection, update the text\_card controls with the selected span's font metadata:

\# After selection is stored:  
if info and hasattr(info, 'font'):  
    self.\_set\_text\_font\_by\_pdf(info.font)  
    self.text\_size.setCurrentText(str(round(info.size, 1)))  
    self.right\_stacked\_widget.setCurrentWidget(self.text\_card)

## **Fix 5.2 — Show text\_card in fullscreen edit mode**

File: pdf\_view.py, enter\_fullscreen\_ui() around line 1370

When editing text in fullscreen, show a floating mini-panel with font info instead of the full right sidebar. This can reuse the text\_card widget but re-parent it as a floating overlay.

## **Fix 5.3 — Enrich context menu**

File: pdf\_view.py, \_show\_context\_menu() at line 3767-3773

def \_show\_context\_menu(self, pos):  
    menu \= QMenu(self)  
    if self.current\_mode \== 'browse' and self.\_selected\_text\_cached:  
        menu.addAction('Copy Selected Text', self.\_copy\_selected\_text\_to\_clipboard)  
        menu.addSeparator()  
    \# NEW: editing entry point  
    if self.current\_mode \== 'browse':  
        menu.addAction('Edit Text', lambda: self.set\_mode('edit\_text'))  
    \# NEW: fullscreen exit  
    if self.\_fullscreen\_active:  
        menu.addAction('Exit Full Screen', self.sig\_toggle\_fullscreen.emit)  
        menu.addSeparator()  
    menu.addAction('Rotate Page', self.\_rotate\_pages)  
    menu.exec\_(self.graphics\_view.mapToGlobal(pos))

# **6\. Recommended Implementation Order**

| When | What | Why / Risk |
| :---- | :---- | :---- |
| Week 1 | BUG-003 Fix 4.1 (no-op skip) | Highest ROI — eliminates the most common drift scenario (user clicks to edit, changes nothing, clicks away). Zero risk of regression. |
| Week 1 | BUG-003 Fix 4.2 (anchor to original rect) | Fixes drift for actual edits. Must be paired with integration test. |
| Week 1 | BUG-001 Fix 2.1 \+ 2.2 (ESC focus \+ visible X button) | Quick fix, unblocks all other testing. Two lines of code change. |
| Week 2 | BUG-002 Fix 3.1 \+ 3.2 (smart line joining) | Requires careful testing with multi-column PDFs and RTL text. Add regression tests for 10 sample PDFs. |
| Week 2 | BUG-003 Fix 4.3 (gate push-down cascade) | Depends on Fix 4.2. Needs testing with PDFs that have dense text near page bottom. |
| Week 2 | BUG-001 Fix 2.3 \+ 2.4 (spacing \+ context menu) | Low risk, improves discoverability. |
| Week 3 | P1 Fix 5.1 \+ 5.3 (font panel \+ context menu) | Polish pass. Test with 5+ font families. |
| Week 3 | Integration test suite | Automated before/after geometry comparison for all 10 test PDFs. |

*Plan produced 2026-03-31  ·  Claude (Cowork mode)  ·  Codebase: /Users/ruinclaw/Documents/pdf\_editor*