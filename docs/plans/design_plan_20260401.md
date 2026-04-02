{\rtf1\ansi\ansicpg950\cocoartf2868
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fnil\fcharset0 Menlo-Regular;\f1\fnil\fcharset0 Menlo-Bold;\f2\fnil\fcharset0 Menlo-BoldItalic;
\f3\fnil\fcharset0 Menlo-Italic;}
{\colortbl;\red255\green255\blue255;\red0\green0\blue0;\red255\green255\blue255;\red237\green237\blue237;
}
{\*\expandedcolortbl;;\cssrgb\c0\c0\c0;\cssrgb\c100000\c100000\c100000;\csgenericrgb\c92857\c92857\c92857;
}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx560\tx1120\tx1680\tx2240\tx2800\tx3360\tx3920\tx4480\tx5040\tx5600\tx6160\tx6720\pardirnatural\partightenfactor0

\f0\fs36 \cf2 \cb3 \CocoaLigature0 \uc0\u9210  Design review complete \'97 
\f1\b 4 findings
\f0\b0  added to the plan:                 \
                                                                         \
  1. 
\f1\b Fix 1 storage \uc0\u8594  dict[(page_idx, block_idx)]
\f0\b0 : Enables O(1) lookup for\
   hover hide/show and active-edit hiding. Plain list couldn't target\
  individual blocks.                                                     \
  2. 
\f1\b Fix 1 hover: hide dim + show solid
\f0\b0  (your choice): On hover, the dim\
  dashed outline for that block hides; only the solid hover highlight    \
  shows. On mouse-out, the dim outline restores. Steps 6\'967 in            \
  _draw_all_block_outlines implement this.                               \
  3. 
\f1\b Fix 1 zoom via sig_scale_changed
\f0\b0 : sig_viewport_changed only fires on\
   scroll (line 2531). Zoom calls _rebuild_continuous_scene_scaled with  \
  emit_viewport_changed=False. Added sig_scale_changed connection\
  alongside sig_viewport_changed so outlines redraw correctly after zoom.\
  4. 
\f1\b Fix 5 toast is required
\f0\b0 : Changed from "optionally show toast" to\
  required \'97 1.5s "Text edit saved." when MODE_SWITCH commits. Silent    \
  commit is just as confusing as silent discard.\
                                                                         \
  Also added: Fix 2 drag guard \'97 IBeam must check _text_edit_drag_state  \
  == IDLE to avoid overriding ClosedHandCursor during block drag.\
                                                                         \
\uc0\u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \
 
\f1\b Ready to code?
\f0\b0                                                       \
                          \
 Here is Claude's plan:\
\uc0\u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \u9548 \
 
\f2\i\b \ul \ulc4 Week 1 Acrobat-Parity Fixes \'97 Implementation Plan
\f0\i0\b0 \ulnone \
                                                                         \
 
\f1\b Context
\f0\b0                                                 \
\
 Cross-comparison GUI testing (2026-03-31) against Adobe Acrobat\
 identified 9 UX gaps that explain why the PDF editor feels less\
 polished than Acrobat. This plan implements the 5 highest-leverage\
 fixes from Week 1 of\
 docs/plans/acrobat_parity_improvement_plan_2026_03_31.md. The goal is\
 to close the most visible discoverability and data-safety gaps within\
 one sprint.\
\
 
\f1\b Reference
\f0\b0  
\f1\b reports:
\f0\b0 \
 - docs/reports/cross_comparison_ux_2026_03_31.md \'97 observed differences\
 - docs/plans/acrobat_parity_improvement_plan_2026_03_31.md \'97 full plan\
 - docs/reports/commit_5784849_audit_report_2026_03_31.md \'97 remaining\
 bugs\
\
 
\f1\b Branch:
\f0\b0  codex/text-editing-function-by-iterating-repeatedly\
\
 ---\
 
\f1\b What
\f0\b0  
\f1\b We're
\f0\b0  
\f1\b Building
\f0\b0  
\f1\b (5
\f0\b0  
\f1\b fixes)
\f0\b0 \
\
 \uc0\u9484 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9516 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9516 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9516 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9488 \
 \uc0\u9474           Fix          \u9474  Priority \u9474        File(s)        \u9474  Effort  \u9474 \
 \uc0\u9500 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9508 \
 \uc0\u9474  1. Persistent block   \u9474  CRITICAL \u9474  view/pdf_view.py     \u9474  Medium  \u9474 \
 \uc0\u9474  outlines in edit mode \u9474           \u9474                       \u9474          \u9474 \
 \uc0\u9500 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9508 \
 \uc0\u9474  2. IBeam cursor over  \u9474  MODERATE \u9474  view/pdf_view.py     \u9474  Trivial \u9474 \
 \uc0\u9474  editable text         \u9474           \u9474                       \u9474          \u9474 \
 \uc0\u9500 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9508 \
 \uc0\u9474  3. Cmd+Shift+Z redo   \u9474  LOW      \u9474  view/pdf_view.py     \u9474  Trivial \u9474 \
 \uc0\u9474  alias                 \u9474           \u9474                       \u9474          \u9474 \
 \uc0\u9500 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9508 \
 \uc0\u9474  4. Remove +4.0pt      \u9474           \u9474                       \u9474          \u9474 \
 \uc0\u9474  padding (position     \u9474  LOW      \u9474  model/pdf_model.py   \u9474  Trivial \u9474 \
 \uc0\u9474  drift)                \u9474           \u9474                       \u9474          \u9474 \
 \uc0\u9500 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9508 \
 \uc0\u9474  5. Mode switch        \u9474           \u9474                       \u9474          \u9474 \
 \uc0\u9474  auto-commit (not      \u9474  HIGH     \u9474  view/text_editing.py \u9474  Small   \u9474 \
 \uc0\u9474  discard)              \u9474           \u9474                       \u9474          \u9474 \
 \uc0\u9492 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9524 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9524 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9524 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9496 \
\
 ---\
 
\f1\b Fix
\f0\b0  
\f1\b 1
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b Persistent
\f0\b0  
\f1\b Block
\f0\b0  
\f1\b Outlines
\f0\b0  
\f1\b in
\f0\b0  
\f1\b Edit
\f0\b0  
\f1\b Mode
\f0\b0 \
\
 
\f1\b Problem:
\f0\b0  Entering edit_text mode reveals nothing. Users must hover to\
 discover editable blocks. Acrobat outlines all text blocks immediately\
 on entering "Edit PDF" mode.\
\
 
\f1\b Approach:
\f0\b0  When edit_text mode is entered, draw a QGraphicsRectItem\
 outline around every text block on all currently-rendered pages. Update\
  when page renders change. Remove on mode exit.\
\
 
\f1\b Implementation
\f0\b0 \
\
 
\f1\b File:
\f0\b0  view/pdf_view.py\
\
 
\f1\b Step
\f0\b0  
\f1\b 1
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b Add
\f0\b0  
\f1\b storage
\f0\b0  
\f1\b in
\f0\b0  
\f1\b __init__ (near
\f0\b0  
\f1\b _hover_highlight_item init):
\f0\b0 \
\
 \uc0\u9614  
\f2\i\b Design
\f0\i0\b0  
\f2\i\b review:
\f3\b0  Use
\f0\i0  
\f3\i dict keyed
\f0\i0  
\f3\i by
\f0\i0  
\f3\i (page_idx,
\f0\i0  
\f3\i block_idx) instead
\f0\i0  
\f3\i of
\f0\i0  
\f3\i a
\f0\i0 \
 
\f3\i plain
\f0\i0  
\f3\i list.
\f0\i0  
\f3\i This
\f0\i0  
\f3\i enables
\f0\i0  
\f3\i O(1)
\f0\i0  
\f3\i lookup
\f0\i0  
\f3\i to
\f0\i0  
\f3\i hide/show
\f0\i0  
\f3\i a
\f0\i0  
\f3\i specific
\f0\i0  
\f3\i block's
\f0\i0 \
 
\f3\i outline
\f0\i0  
\f3\i on
\f0\i0  
\f3\i hover
\f0\i0  
\f3\i and
\f0\i0  
\f3\i on
\f0\i0  
\f3\i active-edit
\f0\i0  
\f3\i open,
\f0\i0  
\f3\i without
\f0\i0  
\f3\i iterating
\f0\i0  
\f3\i all
\f0\i0  
\f3\i items.
\f0\i0 \
\
 # Maps (page_idx, block_idx) \uc0\u8594  QGraphicsRectItem for O(1) hover\
 hide/show\
 self._block_outline_items: dict[tuple[int, int], QGraphicsRectItem] =\
 \{\}\
 # Track which block is currently hidden by hover so we can restore it\
 self._hover_hidden_outline_key: tuple[int, int] | None = None\
\
 
\f1\b Step
\f0\b0  
\f1\b 2
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b Add
\f0\b0  
\f1\b _draw_all_block_outlines() and
\f0\b0  
\f1\b _clear_all_block_outlines()
\f0\b0 \
 
\f1\b  methods
\f0\b0  
\f1\b (near
\f0\b0  
\f1\b _update_hover_highlight,
\f0\b0  
\f1\b ~line
\f0\b0  
\f1\b 3416):
\f0\b0 \
\
 
\f1\b Performance:
\f0\b0  Only draw outlines for currently-visible pages. Use\
 existing visible_page_range() (line 2725) which already computes\
 viewport-visible page indices efficiently. This avoids creating\
 thousands of graphics items for large documents.\
\
 def _draw_all_block_outlines(self) -> None:\
     """Draw persistent dim outlines around text blocks on visible pages\
  only (performance-safe)."""\
     self._clear_all_block_outlines()\
     if not hasattr(self, 'controller') or not\
 self.controller.model.doc:\
         return\
     rs = self._render_scale if self._render_scale > 0 else 1.0\
     start_page, end_page = self.visible_page_range(prefetch=1)  # +1\
 page buffer\
     pen = QPen(QColor(100, 149, 237, 120), 1.0, Qt.DashLine)   #\
 cornflower blue, dashed\
     brush = QBrush(Qt.NoBrush)\
     for page_idx in range(start_page, end_page + 1):\
         page_num = page_idx + 1   # model uses 1-based\
         try:\
             self.controller.model.ensure_page_index_built(page_num)\
             blocks =\
 self.controller.model.block_manager.get_blocks(page_num)\
         except Exception:\
             continue\
         y0 = (self.page_y_positions[page_idx]\
               if (self.continuous_pages and page_idx <\
 len(self.page_y_positions))\
               else 0.0)\
         for block_idx, block in enumerate(blocks):\
             try:\
                 br = block.rect   # fitz.Rect: x0, y0, x1, y1\
                 scene_rect = QRectF(br.x0 * rs, y0 + br.y0 * rs,\
                                     br.width * rs, br.height * rs)\
                 item = self.scene.addRect(scene_rect, pen, brush)\
                 item.setZValue(8)   # below hover highlight (z=10),\
 above page image\
                 self._block_outline_items[(page_idx, block_idx)] = item\
             except Exception:\
                 continue\
\
 def _clear_all_block_outlines(self) -> None:\
     for item in self._block_outline_items.values():\
         try:\
             self.scene.removeItem(item)\
         except Exception:\
             pass\
     self._block_outline_items.clear()\
     self._hover_hidden_outline_key = None\
\
 
\f1\b Step
\f0\b0  
\f1\b 3
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b Call
\f0\b0  
\f1\b in
\f0\b0  
\f1\b set_mode() at
\f0\b0  
\f1\b line
\f0\b0  
\f1\b 2136\'962137
\f0\b0  
\f1\b (edit_text
\f0\b0  
\f1\b branch):
\f0\b0 \
 elif mode == 'edit_text':\
     self.right_stacked_widget.setCurrentWidget(self.text_card)\
     self._draw_all_block_outlines()   # \uc0\u8592  ADD THIS\
\
 
\f1\b Step
\f0\b0  
\f1\b 4
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b Clear
\f0\b0  
\f1\b on
\f0\b0  
\f1\b mode
\f0\b0  
\f1\b exit
\f0\b0  
\f1\b in
\f0\b0  
\f1\b set_mode() at
\f0\b0  
\f1\b existing
\f0\b0  
\f1\b line
\f0\b0  
\f1\b 2111\'962112:
\f0\b0 \
 if mode != 'edit_text':\
     self._clear_hover_highlight()\
     self._clear_all_block_outlines()   # \uc0\u8592  ADD THIS\
\
 
\f1\b Step
\f0\b0  
\f1\b 5
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b Refresh
\f0\b0  
\f1\b on
\f0\b0  
\f1\b scroll
\f0\b0  
\f1\b AND
\f0\b0  
\f1\b zoom.
\f0\b0 \
\
 \uc0\u9614  
\f2\i\b Design
\f0\i0\b0  
\f2\i\b review
\f0\i0\b0  
\f2\i\b finding:
\f3\b0  sig_viewport_changed is
\f0\i0  
\f3\i emitted
\f0\i0  
\f3\i only
\f0\i0  
\f3\i by
\f0\i0 \
 
\f3\i _on_scroll_changed (scroll,
\f0\i0  
\f3\i line
\f0\i0  
\f3\i 2531).
\f0\i0  
\f3\i Zoom
\f0\i0  
\f3\i triggers
\f0\i0 \
 
\f3\i _rebuild_continuous_scene_scaled which
\f0\i0  
\f3\i calls
\f0\i0  
\f3\i scroll_to_page(...,
\f0\i0 \
 
\f3\i emit_viewport_changed=False) \'97
\f0\i0  
\f3\i zoom
\f0\i0  
\f3\i does
\f0\i0  
\f3\i NOT
\f0\i0  
\f3\i fire
\f0\i0  
\f3\i sig_viewport_changed.
\f0\i0 \
 
\f3\i  Also
\f0\i0  
\f3\i connect
\f0\i0  
\f3\i sig_scale_changed (line
\f0\i0  
\f3\i 831)
\f0\i0  
\f3\i to
\f0\i0  
\f3\i catch
\f0\i0  
\f3\i zoom
\f0\i0  
\f3\i events.
\f0\i0 \
\
 # In set_mode(), edit_text branch:\
 elif mode == 'edit_text':\
     self.right_stacked_widget.setCurrentWidget(self.text_card)\
     self._draw_all_block_outlines()\
     try:\
\
 self.sig_viewport_changed.connect(self._draw_all_block_outlines)\
     except Exception:\
         pass\
     try:\
         self.sig_scale_changed.connect(self._draw_all_block_outlines)\
     except Exception:\
         pass\
\
 # In set_mode(), mode-exit branch (line 2111):\
 if mode != 'edit_text':\
     self._clear_hover_highlight()\
     self._clear_all_block_outlines()\
     try:\
\
 self.sig_viewport_changed.disconnect(self._draw_all_block_outlines)\
     except Exception:\
         pass\
     try:\
\
 self.sig_scale_changed.disconnect(self._draw_all_block_outlines)\
     except Exception:\
         pass\
\
 
\f1\b Step
\f0\b0  
\f1\b 6
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b Hover
\f0\b0  
\f1\b hide/show
\f0\b0  
\f1\b (design
\f0\b0  
\f1\b review
\f0\b0  
\f1\b addition):
\f0\b0 \
\
 On hover, hide the dim outline for the hovered block and show only the\
 solid hover highlight. On hover exit, restore the dim outline. This\
 matches Acrobat's single-outline-at-a-time behavior and avoids\
 double-border artifacts.\
\
 In _update_hover_highlight(), after the existing block detection logic,\
  add:\
 # Restore previously hidden outline (if any)\
 if self._hover_hidden_outline_key is not None:\
     prev =\
 self._block_outline_items.get(self._hover_hidden_outline_key)\
     if prev is not None:\
         prev.setVisible(True)\
     self._hover_hidden_outline_key = None\
\
 # Hide the outline for the currently hovered block\
 if hit_block_key is not None:   # (page_idx, block_idx) of the hovered\
 block\
     outline = self._block_outline_items.get(hit_block_key)\
     if outline is not None:\
         outline.setVisible(False)\
         self._hover_hidden_outline_key = hit_block_key\
\
 \uc0\u9614  
\f2\i\b Implementation
\f0\i0\b0  
\f2\i\b note:
\f3\b0  The
\f0\i0  
\f3\i hover
\f0\i0  
\f3\i handler
\f0\i0  
\f3\i must
\f0\i0  
\f3\i resolve
\f0\i0  
\f3\i the
\f0\i0  
\f3\i hovered
\f0\i0  
\f3\i block
\f0\i0 \
 
\f3\i  to
\f0\i0  
\f3\i its
\f0\i0  
\f3\i (page_idx,
\f0\i0  
\f3\i block_idx) key.
\f0\i0  
\f3\i The
\f0\i0  
\f3\i existing
\f0\i0  
\f3\i get_text_info_at_point 
\f0\i0 \
 
\f3\i returns
\f0\i0  
\f3\i a
\f0\i0  
\f3\i block
\f0\i0  
\f3\i rect;
\f0\i0  
\f3\i the
\f0\i0  
\f3\i implementer
\f0\i0  
\f3\i should
\f0\i0  
\f3\i match
\f0\i0  
\f3\i it
\f0\i0  
\f3\i against
\f0\i0  
\f3\i the
\f0\i0  
\f3\i block
\f0\i0 \
 
\f3\i  list
\f0\i0  
\f3\i index
\f0\i0  
\f3\i to
\f0\i0  
\f3\i get
\f0\i0  
\f3\i block_idx.
\f0\i0 \
\
 
\f1\b Step
\f0\b0  
\f1\b 7
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b Active-editing
\f0\b0  
\f1\b block
\f0\b0  
\f1\b outline
\f0\b0  
\f1\b hiding
\f0\b0  
\f1\b (design
\f0\b0  
\f1\b review
\f0\b0  
\f1\b addition):
\f0\b0 \
\
 When create_text_editor() is called for a specific block, hide that\
 block's dim outline (the QTextEdit widget IS the visual container\
 during editing). Restore on finalize.\
\
 In the edit-open call site (around line 3484\'963490):\
 # Hide dim outline for the block being edited\
 if self._active_outline_key is not None:\
     outline = self._block_outline_items.get(self._active_outline_key)\
     if outline is not None:\
         outline.setVisible(False)\
\
 In finalize_text_edit_impl() (after the editor is removed):\
 # Restore dim outline for the just-finished block\
 if self._active_outline_key is not None:\
     outline = self._block_outline_items.get(self._active_outline_key)\
     if outline is not None:\
         outline.setVisible(True)\
     self._active_outline_key = None\
\
 Add self._active_outline_key: tuple[int, int] | None = None to\
 __init__.\
\
 \uc0\u9614  
\f2\i\b Existing
\f0\i0\b0  
\f2\i\b APIs
\f0\i0\b0  
\f2\i\b used:
\f0\i0\b0 \
 \uc0\u9614  
\f3\i -
\f0\i0  
\f3\i visible_page_range(prefetch) \'97
\f0\i0  
\f3\i view/pdf_view.py:2725
\f0\i0 \
 \uc0\u9614  
\f3\i -
\f0\i0  
\f3\i controller.model.ensure_page_index_built(page_num) \'97
\f0\i0  
\f3\i per
\f0\i0 \
 
\f3\i docs/ARCHITECTURE.md
\f0\i0 \
 \uc0\u9614  
\f3\i -
\f0\i0  
\f3\i controller.model.block_manager.get_blocks(page_num) \'97
\f0\i0 \
 
\f3\i model/text_block.py:284,
\f0\i0  
\f3\i returns
\f0\i0  
\f3\i list[TextBlock] with
\f0\i0  
\f3\i block.rect:
\f0\i0 \
 
\f3\i fitz.Rect
\f0\i0 \
 \uc0\u9614  
\f3\i -
\f0\i0  
\f3\i sig_viewport_changed \'97
\f0\i0  
\f3\i view/pdf_view.py:832,
\f0\i0  
\f3\i emitted
\f0\i0  
\f3\i on
\f0\i0  
\f3\i scroll
\f0\i0 \
 \uc0\u9614  
\f3\i -
\f0\i0  
\f3\i sig_scale_changed \'97
\f0\i0  
\f3\i view/pdf_view.py:831,
\f0\i0  
\f3\i emitted
\f0\i0  
\f3\i on
\f0\i0  
\f3\i zoom
\f0\i0 \
\
 ---\
 
\f1\b Fix
\f0\b0  
\f1\b 2
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b IBeam
\f0\b0  
\f1\b Cursor
\f0\b0  
\f1\b Over
\f0\b0  
\f1\b Editable
\f0\b0  
\f1\b Text
\f0\b0  
\f1\b in
\f0\b0  
\f1\b Edit
\f0\b0  
\f1\b Mode
\f0\b0 \
\
 
\f1\b Problem:
\f0\b0  edit_text mode uses Arrow cursor everywhere. Acrobat shows\
 IBeam over text blocks. Users don't know they can click to type.\
\
 
\f1\b File:
\f0\b0  view/pdf_view.py \'97 _update_hover_highlight() (~line 3424)\
\
 
\f1\b Change:
\f0\b0  Add cursor update inside the existing hover check:\
 # In _update_hover_highlight(), after line 3423 (info =\
 controller.get_text_info_at_point):\
 if info:\
     # ... existing rect code ...\
     # Only set IBeam if not currently dragging a block (drag uses\
 ClosedHandCursor)\
     if self._text_edit_drag_state == TextEditDragState.IDLE:   # \uc0\u8592 \
 guard\
         self.graphics_view.viewport().setCursor(Qt.IBeamCursor)   # \uc0\u8592 \
 ADD\
 else:\
     self._clear_hover_highlight()\
     self.graphics_view.viewport().setCursor(Qt.ArrowCursor)   # \uc0\u8592  ADD\
\
 \uc0\u9614  
\f2\i\b Design
\f0\i0\b0  
\f2\i\b review:
\f3\b0  Line
\f0\i0  
\f3\i 2957
\f0\i0  
\f3\i sets
\f0\i0  
\f3\i ClosedHandCursor during
\f0\i0  
\f3\i block
\f0\i0  
\f3\i drag.
\f0\i0 \
 
\f3\i Without
\f0\i0  
\f3\i the
\f0\i0  
\f3\i IDLE guard
\f0\i0  
\f3\i above,
\f0\i0  
\f3\i IBeam
\f0\i0  
\f3\i would
\f0\i0  
\f3\i override
\f0\i0  
\f3\i the
\f0\i0  
\f3\i drag
\f0\i0  
\f3\i cursor
\f0\i0 \
 
\f3\i during
\f0\i0  
\f3\i the
\f0\i0  
\f3\i drag
\f0\i0  
\f3\i gesture,
\f0\i0  
\f3\i giving
\f0\i0  
\f3\i the
\f0\i0  
\f3\i user
\f0\i0  
\f3\i incorrect
\f0\i0  
\f3\i visual
\f0\i0  
\f3\i feedback.
\f0\i0  
\f3\i The
\f0\i0 \
 
\f3\i  guard
\f0\i0  
\f3\i is
\f0\i0  
\f3\i essential.
\f0\i0 \
\
 Also restore Arrow cursor in _clear_hover_highlight():\
 def _clear_hover_highlight(self):\
     # ... existing code to remove item ...\
     self.graphics_view.viewport().setCursor(Qt.ArrowCursor)   # \uc0\u8592  ADD\
 if not already there\
\
 ---\
 
\f1\b Fix
\f0\b0  
\f1\b 3
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b Cmd+Shift+Z
\f0\b0  
\f1\b Redo
\f0\b0  
\f1\b Alias
\f0\b0  
\f1\b (macOS
\f0\b0  
\f1\b Standard)
\f0\b0 \
\
 
\f1\b Problem:
\f0\b0  Redo is Cmd+Y (Windows convention). macOS standard is\
 Cmd+Shift+Z.\
\
 
\f1\b File:
\f0\b0  view/pdf_view.py \'97 line 1529\
\
 
\f1\b Current:
\f0\b0 \
 self._action_redo.setShortcut(QKeySequence("Ctrl+Y"))\
\
 
\f1\b Change:
\f0\b0  Keep Ctrl+Y and add second shortcut via QShortcut:\
 self._action_redo.setShortcut(QKeySequence("Ctrl+Y"))\
 # Add macOS-standard alias (Ctrl = Cmd on macOS in Qt)\
 self._redo_mac_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)\
 self._redo_mac_shortcut.activated.connect(self.sig_redo.emit)\
\
 ---\
 
\f1\b Fix
\f0\b0  
\f1\b 4
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b Remove
\f0\b0  
\f1\b +4.0pt
\f0\b0  
\f1\b Padding
\f0\b0  
\f1\b (Position
\f0\b0  
\f1\b Drift)
\f0\b0 \
\
 
\f1\b Problem:
\f0\b0  Every edit commit adds 4pt to the text block's computed\
 height, causing cumulative visual drift after repeated edits of the\
 same block.\
\
 
\f1\b File:
\f0\b0  model/pdf_model.py\
\
 
\f1\b Location
\f0\b0  
\f1\b 1
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b line
\f0\b0  
\f1\b 2649:
\f0\b0 \
 # Before:\
 _probe_y1 = insert_rect.y0 + _probe_used_h + 4.0\
 # After:\
 _probe_y1 = insert_rect.y0 + _probe_used_h\
\
 
\f1\b Location
\f0\b0  
\f1\b 2
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b line
\f0\b0  
\f1\b 2786:
\f0\b0 \
 # Before:\
 computed_y1 = new_layout_rect.y0 + text_used_height + 4.0\
 # After:\
 computed_y1 = new_layout_rect.y0 + text_used_height\
\
 \uc0\u9614  
\f2\i\b Risk
\f0\i0\b0  
\f2\i\b note:
\f3\b0  The
\f0\i0  
\f3\i 4.0pt
\f0\i0  
\f3\i may
\f0\i0  
\f3\i have
\f0\i0  
\f3\i been
\f0\i0  
\f3\i added
\f0\i0  
\f3\i as
\f0\i0  
\f3\i a
\f0\i0  
\f3\i workaround
\f0\i0  
\f3\i for
\f0\i0  
\f3\i text
\f0\i0 \
 
\f3\i clipping
\f0\i0  
\f3\i at
\f0\i0  
\f3\i the
\f0\i0  
\f3\i bottom
\f0\i0  
\f3\i of
\f0\i0  
\f3\i the
\f0\i0  
\f3\i rect.
\f0\i0  
\f3\i After
\f0\i0  
\f3\i removing,
\f0\i0  
\f3\i test
\f0\i0  
\f3\i that
\f0\i0  
\f3\i text
\f0\i0 \
 
\f3\i doesn't
\f0\i0  
\f3\i get
\f0\i0  
\f3\i clipped.
\f0\i0  
\f3\i If
\f0\i0  
\f3\i clipping
\f0\i0  
\f3\i occurs
\f0\i0  
\f3\i in
\f0\i0  
\f3\i practice,
\f0\i0  
\f3\i add
\f0\i0  
\f3\i +
\f0\i0  
\f3\i 1.0 (1pt
\f0\i0 \
 
\f3\i safety
\f0\i0  
\f3\i margin
\f0\i0  
\f3\i instead
\f0\i0  
\f3\i of
\f0\i0  
\f3\i 4pt)
\f0\i0  
\f3\i to
\f0\i0  
\f3\i reduce
\f0\i0  
\f3\i drift
\f0\i0  
\f3\i while
\f0\i0  
\f3\i preventing
\f0\i0 \
 
\f3\i clipping.
\f0\i0 \
\
 ---\
 
\f1\b Fix
\f0\b0  
\f1\b 5
\f0\b0  
\f1\b \'97
\f0\b0  
\f1\b Mode
\f0\b0  
\f1\b Switch
\f0\b0  
\f1\b Auto-Commit
\f0\b0  
\f1\b (Not
\f0\b0  
\f1\b Silent
\f0\b0  
\f1\b Discard)
\f0\b0 \
\
 
\f1\b Problem:
\f0\b0  Switching modes while editing silently discards typed text.\
 TextEditFinalizeReason.MODE_SWITCH maps to TextEditOutcome.DISCARDED.\
\
 
\f1\b File:
\f0\b0  view/text_editing.py \'97 lines 534\'96547\
\
 
\f1\b Current:
\f0\b0 \
 if reason in \{\
     TextEditFinalizeReason.CANCEL_BUTTON,\
     TextEditFinalizeReason.ESCAPE,\
     TextEditFinalizeReason.MODE_SWITCH,    # \uc0\u8592  causes silent discard\
     TextEditFinalizeReason.CLOSE_DOCUMENT,\
 \}:\
     return TextEditFinalizeResult(outcome=TextEditOutcome.DISCARDED,\
 ...)\
\
 
\f1\b Change:
\f0\b0  Remove MODE_SWITCH from the discard set so it falls through to\
 the commit logic (same path as CLICK_AWAY):\
 if reason in \{\
     TextEditFinalizeReason.CANCEL_BUTTON,\
     TextEditFinalizeReason.ESCAPE,\
     # MODE_SWITCH removed \'97 falls through to commit\
     TextEditFinalizeReason.CLOSE_DOCUMENT,\
 \}:\
     return TextEditFinalizeResult(outcome=TextEditOutcome.DISCARDED,\
 ...)\
\
 \uc0\u9614  
\f2\i\b Edge
\f0\i0\b0  
\f2\i\b case:
\f3\b0  CLOSE_DOCUMENT keeps
\f0\i0  
\f3\i discard
\f0\i0  
\f3\i behavior
\f0\i0  
\f3\i intentionally
\f0\i0  
\f3\i \'97
\f0\i0  
\f3\i when
\f0\i0 \
 
\f3\i  closing,
\f0\i0  
\f3\i the
\f0\i0  
\f3\i document
\f0\i0  
\f3\i is
\f0\i0  
\f3\i gone.
\f0\i0  
\f3\i ESCAPE and
\f0\i0  
\f3\i CANCEL_BUTTON remain
\f0\i0  
\f3\i discard
\f0\i0 \
 
\f3\i  since
\f0\i0  
\f3\i they
\f0\i0  
\f3\i are
\f0\i0  
\f3\i explicit
\f0\i0  
\f3\i user
\f0\i0  
\f3\i cancellation
\f0\i0  
\f3\i signals.
\f0\i0 \
\
 \uc0\u9614  
\f2\i\b What
\f0\i0\b0  
\f2\i\b changes:
\f3\b0  Clicking
\f0\i0  
\f3\i Browse/Rect/Highlight
\f0\i0  
\f3\i while
\f0\i0  
\f3\i mid-edit
\f0\i0  
\f3\i will
\f0\i0  
\f3\i now
\f0\i0 \
 
\f3\i commit
\f0\i0  
\f3\i the
\f0\i0  
\f3\i edit
\f0\i0  
\f3\i (same
\f0\i0  
\f3\i as
\f0\i0  
\f3\i clicking
\f0\i0  
\f3\i outside
\f0\i0  
\f3\i the
\f0\i0  
\f3\i text
\f0\i0  
\f3\i block).
\f0\i0  
\f3\i This
\f0\i0  
\f3\i matches
\f0\i0 \
 
\f3\i  Acrobat's
\f0\i0  
\f3\i behavior.
\f0\i0 \
\
 \uc0\u9614  
\f2\i\b Design
\f0\i0\b0  
\f2\i\b review
\f0\i0\b0  
\f2\i\b \'97
\f0\i0\b0  
\f2\i\b toast
\f0\i0\b0  
\f2\i\b is
\f0\i0\b0  
\f2\i\b REQUIRED:
\f3\b0  Replacing
\f0\i0  
\f3\i silent
\f0\i0  
\f3\i discard
\f0\i0  
\f3\i with
\f0\i0 \
 
\f3\i silent
\f0\i0  
\f3\i commit
\f0\i0  
\f3\i swaps
\f0\i0  
\f3\i one
\f0\i0  
\f3\i confusion
\f0\i0  
\f3\i for
\f0\i0  
\f3\i another.
\f0\i0  
\f3\i When
\f0\i0  
\f3\i a
\f0\i0  
\f3\i user
\f0\i0  
\f3\i switches
\f0\i0 \
 
\f3\i modes,
\f0\i0  
\f3\i they
\f0\i0  
\f3\i need
\f0\i0  
\f3\i to
\f0\i0  
\f3\i know
\f0\i0  
\f3\i whether
\f0\i0  
\f3\i their
\f0\i0  
\f3\i edit
\f0\i0  
\f3\i landed.
\f0\i0  
\f3\i Show
\f0\i0  
\f3\i a
\f0\i0  
\f3\i 1.5s
\f0\i0  
\f3\i "Text
\f0\i0 \
 
\f3\i edit
\f0\i0  
\f3\i saved."
\f0\i0  
\f3\i toast
\f0\i0  
\f3\i using
\f0\i0  
\f3\i a
\f0\i0  
\f3\i QLabel overlay
\f0\i0  
\f3\i positioned
\f0\i0  
\f3\i bottom-center
\f0\i0  
\f3\i of
\f0\i0 \
 
\f3\i the
\f0\i0  
\f3\i viewport.
\f0\i0  
\f3\i The
\f0\i0  
\f3\i toast
\f0\i0  
\f3\i must
\f0\i0  
\f3\i appear
\f0\i0  
\f3\i when
\f0\i0  
\f3\i MODE_SWITCH triggers
\f0\i0  
\f3\i commit
\f0\i0 \
 
\f3\i (i.e.,
\f0\i0  
\f3\i when
\f0\i0  
\f3\i result.outcome
\f0\i0  
\f3\i ==
\f0\i0  
\f3\i TextEditOutcome.APPLIED).
\f0\i0  
\f3\i This
\f0\i0  
\f3\i is
\f0\i0  
\f3\i not
\f0\i0 \
 
\f3\i optional.
\f0\i0 \
\
 ---\
 
\f1\b Critical
\f0\b0  
\f1\b Files
\f0\b0 \
\
 \uc0\u9484 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9516 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9516 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9488 \
 \uc0\u9474          File         \u9474         Purpose         \u9474     Key Lines     \u9474 \
 \uc0\u9500 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9508 \
 \uc0\u9474  view/pdf_view.py     \u9474  Hover highlight, mode  \u9474  1529, 2111\'962142, \u9474 \
 \uc0\u9474                       \u9474  entry, cursor, redo    \u9474   3416\'963449       \u9474 \
 \uc0\u9500 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9508 \
 \uc0\u9474  view/text_editing.py \u9474  Finalization reason \u8594   \u9474  534\'96547          \u9474 \
 \uc0\u9474                       \u9474  outcome mapping        \u9474                   \u9474 \
 \uc0\u9500 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9532 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9508 \
 \uc0\u9474  model/pdf_model.py   \u9474  +4.0pt padding removal \u9474  2649, 2786       \u9474 \
 \uc0\u9492 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9524 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9524 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9496 \
\
 ---\
 
\f1\b Implementation
\f0\b0  
\f1\b Order
\f0\b0  
\f1\b (minimize
\f0\b0  
\f1\b re-runs)
\f0\b0 \
\
 1. model/pdf_model.py \'97 remove +4.0pt (2 lines, no risk to other fixes)\
 2. view/text_editing.py \'97 remove MODE_SWITCH from discard set (1 line\
 change)\
 3. view/pdf_view.py line 1529 \'97 add Cmd+Shift+Z alias (2 lines)\
 4. view/pdf_view.py _update_hover_highlight \'97 add IBeam cursor logic (2\
  lines)\
 5. view/pdf_view.py \'97 add block outlines (new method + 2 call sites)\
\
 ---\
 
\f1\b Tests
\f0\b0  
\f1\b Required
\f0\b0 \
\
 Add to test_scripts/test_text_editing_gui_regressions.py:\
\
 
\f1\b Test:
\f0\b0  
\f1\b MODE_SWITCH
\f0\b0  
\f1\b now
\f0\b0  
\f1\b commits
\f0\b0  
\f1\b instead
\f0\b0  
\f1\b of
\f0\b0  
\f1\b discarding
\f0\b0 \
\
 def test_mode_switch_commits_edit_not_discards(monkeypatch:\
 pytest.MonkeyPatch) -> None:\
     """Switching modes while editing must auto-commit, not silently\
 discard."""\
     from view.text_editing import TextEditFinalizeReason,\
 TextEditOutcome\
     view = _make_minimal_view()  # use existing helper\
     # Set up a fake editor with changed text\
     _setup_fake_editor(view, original_text="Hello", new_text="Hello\
 World")\
     result = view.text_edit_manager.finalize_text_edit(TextEditFinalize\
 Reason.MODE_SWITCH)\
     assert result is not None\
     assert result.outcome != TextEditOutcome.DISCARDED, \\\
         "MODE_SWITCH must not discard \'97 text edits are lost silently"\
     # Outcome should be APPLIED or SKIPPED (no change), never DISCARDED\
     assert result.outcome in (TextEditOutcome.APPLIED,\
 TextEditOutcome.SKIPPED)\
\
 
\f1\b Test:
\f0\b0  
\f1\b ESCAPE
\f0\b0  
\f1\b and
\f0\b0  
\f1\b CANCEL_BUTTON
\f0\b0  
\f1\b still
\f0\b0  
\f1\b discard
\f0\b0 \
\
 def test_escape_still_discards(monkeypatch: pytest.MonkeyPatch) ->\
 None:\
     """ESCAPE must still discard \'97 it is an explicit cancel signal."""\
     from view.text_editing import TextEditFinalizeReason,\
 TextEditOutcome\
     view = _make_minimal_view()\
     _setup_fake_editor(view, original_text="Hello", new_text="Hello\
 World")\
     result = view.text_edit_manager.finalize_text_edit(TextEditFinalize\
 Reason.ESCAPE)\
     assert result is not None\
     assert result.outcome == TextEditOutcome.DISCARDED\
\
 
\f1\b Test:
\f0\b0  
\f1\b Block
\f0\b0  
\f1\b outlines
\f0\b0  
\f1\b respect
\f0\b0  
\f1\b visible_page_range
\f0\b0 \
\
 def test_block_outlines_only_drawn_for_visible_pages(monkeypatch:\
 pytest.MonkeyPatch) -> None:\
     """_draw_all_block_outlines must only draw for visible_page_range,\
 not all pages."""\
     view = _make_minimal_view()\
     visited_pages = []\
     monkeypatch.setattr(\
         view, 'visible_page_range', lambda prefetch=0: (3, 5)  # pages\
 3-5 visible\
     )\
     # Ensure get_blocks is only called for pages 3-5\
     orig_get_blocks = view.controller.model.block_manager.get_blocks\
     def tracking_get_blocks(page_num):\
         visited_pages.append(page_num)\
         return orig_get_blocks(page_num)\
     monkeypatch.setattr(view.controller.model.block_manager,\
 'get_blocks', tracking_get_blocks)\
     view._draw_all_block_outlines()\
     assert all(p in (4, 5, 6) for p in visited_pages), \\\
         f"Expected pages 4-6 (1-based), got \{visited_pages\}"\
\
 
\f1\b Test:
\f0\b0  
\f1\b Cmd+Shift+Z
\f0\b0  
\f1\b fires
\f0\b0  
\f1\b redo
\f0\b0 \
\
 def test_cmd_shift_z_fires_redo(qapp) -> None:\
     """Cmd+Shift+Z (macOS standard) must trigger redo signal."""\
     view = _make_minimal_view()\
     redo_count = [0]\
     view.sig_redo.connect(lambda: redo_count.__setitem__(0,\
 redo_count[0] + 1))\
     # Simulate Ctrl+Shift+Z key press\
     from PySide6.QtGui import QKeySequence\
     from PySide6.QtWidgets import QApplication\
     QApplication.processEvents()\
     view._redo_mac_shortcut.activated.emit()\
     assert redo_count[0] == 1\
\
 ---\
 
\f1\b Verification
\f0\b0 \
\
 
\f1\b Fix
\f0\b0  
\f1\b 1
\f0\b0  
\f1\b (block
\f0\b0  
\f1\b outlines)
\f0\b0 \
\
 1. Launch editor, open TIA-942 PDF, navigate to page 5\
 2. Click "\uc0\u32232 \u36655 \u25991 \u23383 " toolbar button\
 3. 
\f1\b Expected:
\f0\b0  Dashed cornflower-blue outlines appear around all visible\
 text blocks immediately, without hovering\
 4. Hover over a block \'97 
\f1\b Expected:
\f0\b0  dim dashed outline DISAPPEARS,\
 replaced by solid blue hover highlight only (no double-border)\
 5. Move mouse off the block \'97 
\f1\b Expected:
\f0\b0  dim dashed outline RESTORES,\
 solid hover clears\
 6. Click a block to open editor \'97 
\f1\b Expected:
\f0\b0  that block's dim outline\
 hides (editor widget is the visual boundary)\
 7. Finish editing \'97 
\f1\b Expected:
\f0\b0  dim outline restores for that block\
 8. Change zoom level while in edit_text mode \'97 
\f1\b Expected:
\f0\b0  outlines\
 redraw at correct positions\
 9. Switch to Browse mode \'97 all outlines disappear\
\
 
\f1\b Fix
\f0\b0  
\f1\b 2
\f0\b0  
\f1\b (IBeam
\f0\b0  
\f1\b cursor)
\f0\b0 \
\
 1. In edit_text mode, hover over a text block\
 2. 
\f1\b Expected:
\f0\b0  Cursor changes to IBeam (only when not dragging)\
 3. Move mouse to empty page area \'97 
\f1\b Expected:
\f0\b0  cursor returns to Arrow\
 4. Click-drag a block \'97 
\f1\b Expected:
\f0\b0  cursor stays ClosedHand (IBeam does\
 NOT override drag cursor)\
\
 
\f1\b Fix
\f0\b0  
\f1\b 3
\f0\b0  
\f1\b (Cmd+Shift+Z)
\f0\b0 \
\
 1. Make a text edit, commit\
 2. Press Cmd+Shift+Z \'97 
\f1\b Expected:
\f0\b0  redo fires (same as Cmd+Y)\
\
 
\f1\b Fix
\f0\b0  
\f1\b 4
\f0\b0  
\f1\b (+4.0pt
\f0\b0  
\f1\b removal)
\f0\b0 \
\
 1. Edit a text block 5 times (type a character, commit, repeat)\
 2. 
\f1\b Expected:
\f0\b0  Block does not grow visually after each commit\
 3. Check text is not clipped at bottom\
\
 
\f1\b Fix
\f0\b0  
\f1\b 5
\f0\b0  
\f1\b (mode
\f0\b0  
\f1\b switch
\f0\b0  
\f1\b commit)
\f0\b0 \
\
 1. Enter edit_text mode, click a text block, type "HELLO"\
 2. Click the Browse mode button\
 3. 
\f1\b Expected:
\f0\b0  Edit is committed (text appears in PDF) \'97 NOT discarded\
 silently\
 4. 
\f1\b Expected:
\f0\b0  "Text edit saved." toast appears for 1.5s at bottom-center\
  of viewport\
 5. Press Cmd+Z \'97 
\f1\b Expected:
\f0\b0  text reverts (proves it went through commit\
 path)\
\
 ---\
 
\f1\b GSTACK
\f0\b0  
\f1\b REVIEW
\f0\b0  
\f1\b REPORT
\f0\b0 \
\
 
\f1\b Review:
\f0\b0  CEO Review\
 
\f1\b Trigger:
\f0\b0  /plan-ceo-review\
 
\f1\b Why:
\f0\b0  Scope & strategy\
 
\f1\b Runs:
\f0\b0  1\
 
\f1\b Status:
\f0\b0  DONE\
 
\f1\b Findings:
\f0\b0  Visible-pages-only for Fix 1 (perf)\
 \uc0\u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \
 
\f1\b Review:
\f0\b0  Codex Review\
 
\f1\b Trigger:
\f0\b0  /codex review\
 
\f1\b Why:
\f0\b0  Independent 2nd opinion\
 
\f1\b Runs:
\f0\b0  0\
 
\f1\b Status:
\f0\b0  \'97\
 
\f1\b Findings:
\f0\b0  \'97\
 \uc0\u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \
 
\f1\b Review:
\f0\b0  Eng Review\
 
\f1\b Trigger:
\f0\b0  /plan-eng-review\
 
\f1\b Why:
\f0\b0  Architecture & tests (required)\
 
\f1\b Runs:
\f0\b0  1\
 
\f1\b Status:
\f0\b0  DONE\
 
\f1\b Findings:
\f0\b0  +4 tests added; sig_viewport_changed scroll hook added\
 \uc0\u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \u9472 \
 
\f1\b Review:
\f0\b0  Design Review\
 
\f1\b Trigger:
\f0\b0  /plan-design-review\
 
\f1\b Why:
\f0\b0  UI/UX gaps\
 
\f1\b Runs:
\f0\b0  1\
 
\f1\b Status:
\f0\b0  DONE\
 
\f1\b Findings:
\f0\b0  4 findings: dict storage for outlines, hover hide/show, zoom\
   via sig_scale_changed, toast required\
\
 
\f1\b VERDICT:
\f0\b0  READY \'97 3 reviews complete (CEO + Eng + Design). Codex review\
 optional.\
}