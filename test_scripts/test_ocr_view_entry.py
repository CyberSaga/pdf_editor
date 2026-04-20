from __future__ import annotations

from unittest.mock import patch

from model.tools.ocr_types import OcrRequest
from view.pdf_view import PDFView


def test_view_exposes_ocr_action(qapp):
    view = PDFView()
    assert view.ocr_action is not None
    assert view.ocr_action.isEnabled()
    view.deleteLater()


def test_view_update_ocr_availability_disables_action(qapp):
    view = PDFView()
    view.update_ocr_availability(False, "Surya 未安裝\npip install surya-ocr")
    assert view.ocr_action.isEnabled()
    tooltip = view.ocr_action.toolTip()
    assert "surya" in tooltip.lower()
    view.deleteLater()


def test_view_update_ocr_availability_reenables(qapp):
    view = PDFView()
    view.update_ocr_availability(False, "Surya 未安裝")
    view.update_ocr_availability(True, "")
    assert view.ocr_action.isEnabled()
    assert "surya" not in view.ocr_action.toolTip().lower()
    view.deleteLater()


def test_view_ocr_action_when_unavailable_shows_error_and_does_not_open_dialog(qapp):
    view = PDFView()
    view.total_pages = 5
    view.current_page = 1
    view.update_ocr_availability(False, "Surya 未安裝\npip install surya-ocr")

    with patch("view.pdf_view.show_error") as show_error, patch("view.pdf_view.OcrDialog") as DialogCls:
        view._ocr_pages()

    DialogCls.assert_not_called()
    assert show_error.call_count == 1
    assert "pip install" in str(show_error.call_args[0][1]).lower()
    view.deleteLater()


def test_view_ocr_action_opens_dialog_and_emits_request(qapp):
    view = PDFView()
    view.total_pages = 5
    view.current_page = 2

    captured: list = []
    view.sig_start_ocr.connect(lambda req: captured.append(req))

    # Prepare a dialog stub that returns a canned request instead of showing UI.
    canned = OcrRequest(page_indices=(1,), languages=("en",), device="auto")

    with patch("view.pdf_view.OcrDialog") as DialogCls:
        instance = DialogCls.return_value
        instance.exec.return_value = True
        instance.get_request.return_value = canned
        view._ocr_pages()

    assert captured == [canned]
    view.deleteLater()


def test_view_ocr_action_cancel_does_not_emit(qapp):
    view = PDFView()
    view.total_pages = 5
    view.current_page = 1

    captured: list = []
    view.sig_start_ocr.connect(lambda req: captured.append(req))

    with patch("view.pdf_view.OcrDialog") as DialogCls:
        instance = DialogCls.return_value
        instance.exec.return_value = False
        instance.get_request.return_value = None
        view._ocr_pages()

    assert captured == []
    view.deleteLater()
