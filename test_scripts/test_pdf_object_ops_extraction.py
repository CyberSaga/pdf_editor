"""R3.4: the object-ops engine must live in model/pdf_object_ops.py.

The native-image/app-object helpers, markers, and the object verbs move out of PDFModel
into a free-function module (def fn(model: PDFModel, ...)), mirroring model/pdf_optimizer.py.
PDFModel keeps 1-line delegating wrappers for the 7 public verbs the tests call. The OCR
methods (apply_ocr_spans/_pick_ocr_font) and _convert_text_to_html stay on PDFModel.
"""

from __future__ import annotations

import inspect

# RED before extraction: this module does not exist yet (hard ImportError on collect).
import model.pdf_object_ops as obj_ops
from model.pdf_model import PDFModel


def test_module_exposes_object_ops_free_functions() -> None:
    for name in (
        "add_image_object",
        "add_textbox",
        "get_object_info_at_point",
        "move_object",
        "rotate_object",
        "delete_object",
        "resize_object",
        "_find_native_image_invocation",
        "_rewrite_native_image_matrix",
        "_remove_native_image_invocation",
        "_create_textbox_object_marker",
        "_create_image_object_marker",
        "_insert_textbox_visual_content",
    ):
        fn = getattr(obj_ops, name, None)
        assert callable(fn), name
        # Free functions take `model` as the first parameter.
        params = list(inspect.signature(fn).parameters)
        assert params and params[0] == "model", f"{name} first param: {params[:1]}"


def test_pdfmodel_keeps_public_verb_wrappers() -> None:
    for name in (
        "add_image_object",
        "add_textbox",
        "get_object_info_at_point",
        "move_object",
        "rotate_object",
        "delete_object",
        "resize_object",
    ):
        assert callable(getattr(PDFModel, name)), name


def test_ocr_and_html_methods_stay_on_pdfmodel() -> None:
    # apply_ocr_spans is what the OcrCoordinator calls; it + _convert_text_to_html are NOT object-ops.
    assert callable(PDFModel.apply_ocr_spans)
    assert callable(PDFModel._convert_text_to_html)
    assert not hasattr(obj_ops, "apply_ocr_spans")
    assert not hasattr(obj_ops, "_convert_text_to_html")
