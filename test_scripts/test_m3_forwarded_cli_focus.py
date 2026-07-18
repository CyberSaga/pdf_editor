"""Tests: handle_forwarded_cli sets focus on graphics_view after activation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt


class TestForwardedCliFocus:
    """When a PDF is forwarded via CLI to an existing instance, the graphics_view
    must receive keyboard focus so PgUp/PgDn navigation works immediately."""

    def test_handle_forwarded_cli_focuses_graphics_view(self):
        from controller.pdf_controller import PDFController

        mock_model = MagicMock()
        mock_model.doc = None
        mock_view = MagicMock()
        mock_view.isMinimized.return_value = False

        with patch.object(PDFController, "__init__", lambda self, *a, **kw: None):
            ctrl = PDFController.__new__(PDFController)

        ctrl.model = mock_model
        ctrl.view = mock_view
        ctrl.activate = MagicMock()
        ctrl.open_pdf = MagicMock()

        ctrl.handle_forwarded_cli(["/tmp/test.pdf"])

        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        app.processEvents()

        mock_view.raise_.assert_called()
        mock_view.activateWindow.assert_called()
        mock_view.graphics_view.setFocus.assert_called_with(
            Qt.FocusReason.ActiveWindowFocusReason
        )

    def test_focus_is_set_after_open_pdf_so_document_loading_cannot_steal_it(self):
        """setFocus must run after the forwarded-files open_pdf loop, otherwise
        opening a document (which can rebuild focus-stealing widgets) could
        clobber the focus we just set."""
        from controller.pdf_controller import PDFController

        mock_model = MagicMock()
        mock_model.doc = None
        mock_view = MagicMock()
        mock_view.isMinimized.return_value = False

        manager = MagicMock()
        manager.attach_mock(mock_view.graphics_view.setFocus, "setFocus")

        with patch.object(PDFController, "__init__", lambda self, *a, **kw: None):
            ctrl = PDFController.__new__(PDFController)

        ctrl.model = mock_model
        ctrl.view = mock_view
        ctrl.activate = MagicMock()

        def _fake_open_pdf(path):
            return None

        ctrl.open_pdf = MagicMock(side_effect=_fake_open_pdf)
        manager.attach_mock(ctrl.open_pdf, "open_pdf")

        ctrl.handle_forwarded_cli(["/tmp/test.pdf", "/tmp/test2.pdf"])

        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        app.processEvents()

        call_names = [call[0] for call in manager.mock_calls]
        assert call_names.count("open_pdf") == 2
        last_open_pdf_index = max(
            idx for idx, name in enumerate(call_names) if name == "open_pdf"
        )
        set_focus_index = call_names.index("setFocus")
        assert set_focus_index > last_open_pdf_index
