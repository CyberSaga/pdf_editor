"""R3.6: the object-selection subsystem must live in view/object_selection.py.

First view seam. The 20 object-selection / drag / resize / free-rotation methods move out
of the PDFView god-class into ObjectSelectionManager(view), mirroring TextEditManager.
PDFView keeps 1-line delegating wrappers (so the mouse handlers, context menu, keyPress and
tests are untouched) and a lazy `_ensure_object_selection_manager()` accessor. The pure
`absolute_rotation_from_drag` helper moves with the cluster and is re-exported from pdf_view.

Scope (approach X): METHODS move; the ~26 interaction-state attrs and the three mouse handlers
stay on PDFView for now (manager reaches them via self._view). State migration lands with the
R3.8 handler refactor.
"""

from __future__ import annotations

import inspect

# RED before extraction: this module did not exist (hard ImportError on collect).
import view.object_selection as object_selection
from view.object_selection import ObjectSelectionManager

_VERBS = (
    "_resolve_object_info_for_context_menu_pos", "_clear_object_selection", "_select_object",
    "_rebase_object_selection_to_bboxes", "_apply_object_selection_rotation", "_object_center_scene",
    "_supports_free_rotate", "_update_object_selection_visuals", "_point_hits_object_resize_handle",
    "_hit_object_resize_handle_index", "_point_hits_object_rotate_handle", "_delete_selected_object",
    "_commit_free_rotation", "_rotate_selected_object", "_normalize_object_rotation_angle",
    "_rotate_selected_object_absolute", "_next_right_angle_rotation",
    "_rotate_selected_object_to_next_right_angle", "_add_object_rotation_actions",
    "_show_object_rotation_menu",
)


def test_manager_owns_the_object_selection_verbs() -> None:
    for name in _VERBS:
        assert callable(getattr(ObjectSelectionManager, name, None)), name


def test_manager_holds_view_backref() -> None:
    params = list(inspect.signature(ObjectSelectionManager.__init__).parameters)
    assert params[:2] == ["self", "view"], params[:2]


def test_pdfview_keeps_delegating_wrappers_and_lazy_accessor() -> None:
    # Imported lazily so the module-level `import view.pdf_view` cost is only paid in this test.
    from view.pdf_view import PDFView

    assert callable(getattr(PDFView, "_ensure_object_selection_manager"))
    for name in _VERBS:
        assert callable(getattr(PDFView, name, None)), name


def test_absolute_rotation_from_drag_moved_and_reexported() -> None:
    import view.pdf_view as pdf_view

    assert callable(object_selection.absolute_rotation_from_drag)
    # Re-exported so existing pdf_view.absolute_rotation_from_drag test refs keep working.
    assert pdf_view.absolute_rotation_from_drag is object_selection.absolute_rotation_from_drag
