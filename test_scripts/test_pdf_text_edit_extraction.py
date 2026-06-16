"""R3.5: the edit_text / redaction engine must live in model/pdf_text_edit.py.

This is the LAST and highest-risk model seam. The edit-text resolution, redaction
insertion, protected-span replay, overflow push-down, and post-edit verification move
out of PDFModel into a free-function module (def fn(model: PDFModel, ...)), mirroring
model/pdf_optimizer.py and model/pdf_object_ops.py. PDFModel keeps a 1-line delegating
wrapper for the public ``edit_text`` verb the controller/tests call.

Source-verified STAY set (called from outside the moving cluster, so they remain on
PDFModel and the moved free functions reach them via ``model.``):
  - _needs_cjk_font          (also used by model/pdf_object_ops.py)
  - _resolve_font_for_push   (also used by _resolve_add_text_font, which stays)
  - _convert_text_to_html    (used by controller + view preview path)
  - _build_insert_css        (used by controller + view preview path)
  - _build_multi_style_html  (HTML composition helper, stays with the converters)
  - _maybe_garbage_collect   (encryption-preserving live-doc roundtrip maintenance)
"""

from __future__ import annotations

import inspect

# RED before extraction: this module does not exist yet (hard ImportError on collect).
import model.pdf_text_edit as text_edit
from model.pdf_model import PDFModel


def test_module_exposes_edit_text_free_functions() -> None:
    for name in (
        "edit_text",
        "_resolve_effective_target_mode",
        "_resolve_edit_target",
        "_apply_redact_insert",
        "_verify_rebuild_edit",
        "_push_down_overlapping_text",
        "_replay_protected_spans",
        "_validate_protected_spans",
        "_has_complex_script",
    ):
        fn = getattr(text_edit, name, None)
        assert callable(fn), name
        # Free functions take `model` as the first parameter.
        params = list(inspect.signature(fn).parameters)
        assert params and params[0] == "model", f"{name} first param: {params[:1]}"


def test_pdfmodel_keeps_edit_text_wrapper() -> None:
    assert callable(getattr(PDFModel, "edit_text"))


def test_cross_cutting_helpers_stay_on_pdfmodel() -> None:
    # These are reached from OUTSIDE the moving cluster (object-ops, add-text, preview,
    # encryption maintenance) so they must remain on PDFModel and NOT be in the new module.
    for name in (
        "_needs_cjk_font",
        "_resolve_font_for_push",
        "_convert_text_to_html",
        "_build_insert_css",
        "_build_multi_style_html",
        "_maybe_garbage_collect",
    ):
        assert callable(getattr(PDFModel, name)), name
        assert not hasattr(text_edit, name), f"{name} must stay on PDFModel"
