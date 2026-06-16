"""R3.7: the text-selection subsystem must live in view/text_selection.py.

Second view seam. The 12 browse-mode text-selection / highlight / copy methods move out of
the PDFView god-class into TextSelectionManager(view), mirroring ObjectSelectionManager (R3.6).
PDFView keeps 1-line delegating wrappers (so mouse handlers, context menu, keyPress/menu
QActions, the controller, and tests are untouched) + a lazy `_ensure_text_selection_manager()`.

Scope (approach X): METHODS move; the ~17 selection-state attrs and the three mouse handlers
stay on PDFView for now (manager reaches them via self._view). State migration lands with R3.8.
"""

from __future__ import annotations

import inspect

# RED before extraction: this module did not exist (hard ImportError on collect).
from view.text_selection import TextSelectionManager

_VERBS = (
    "_selected_text_has_context", "_start_text_selection", "_update_text_selection",
    "_finalize_text_selection", "_selection_doc_rect_to_scene", "_clear_text_selection_extra_rects",
    "_render_text_selection_line_rects", "_clear_text_selection", "_resolve_text_info_for_doc_rect",
    "_resolve_text_info_for_context_menu_pos", "_select_all_text_on_current_page",
    "_copy_selected_text_to_clipboard",
)


def test_manager_owns_the_text_selection_verbs() -> None:
    for name in _VERBS:
        assert callable(getattr(TextSelectionManager, name, None)), name


def test_manager_holds_view_backref() -> None:
    params = list(inspect.signature(TextSelectionManager.__init__).parameters)
    assert params[:2] == ["self", "view"], params[:2]


def test_pdfview_keeps_delegating_wrappers_and_lazy_accessor() -> None:
    from view.pdf_view import PDFView

    assert callable(getattr(PDFView, "_ensure_text_selection_manager"))
    for name in _VERBS:
        assert callable(getattr(PDFView, name, None)), name
