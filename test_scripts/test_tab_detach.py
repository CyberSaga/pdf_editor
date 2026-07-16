from __future__ import annotations

from pathlib import Path

import fitz
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from controller.pdf_controller import PDFController
from controller.session_transfer import SessionTransferPayload
from model.pdf_model import PDFModel
from view.detachable_tab_bar import DetachableTabBar
from view.pdf_view import PDFView


def _make_pdf(path: Path, text: str = "DETACH") -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 60), text)
    doc.save(path)
    doc.close()


def test_transfer_payload_repr_hides_bytes_and_password() -> None:
    payload = SessionTransferPayload(
        snapshot_bytes=b"secret-pdf-bytes",
        source_path="source.pdf",
        saved_path=None,
        display_name="source.pdf",
        dirty=True,
        current_page=2,
        scale=1.5,
        color_profile="srgb",
        password="secret-password",
        auth_level=2,
    )
    rendered = repr(payload)
    assert "secret-pdf-bytes" not in rendered
    assert "secret-password" not in rendered


def test_model_import_transfer_uses_independent_document_and_empty_history(tmp_path: Path) -> None:
    path = tmp_path / "source.pdf"
    _make_pdf(path)
    source = PDFModel()
    destination = PDFModel()
    try:
        source.open_pdf(str(path))
        source.doc[0].insert_text((40, 90), "DIRTY")
        source.edit_count += 1
        payload = SessionTransferPayload.from_model(
            source,
            source.get_active_session_id(),
            current_page=0,
            scale=1.25,
            color_profile="gray",
        )

        sid = destination.import_session_transfer(payload)

        assert sid == destination.get_active_session_id()
        assert destination.doc is not source.doc
        assert "DIRTY" in destination.doc[0].get_text()
        assert destination.session_has_unsaved_changes(sid) is True
        assert destination.command_manager.can_undo() is False
        meta = destination.get_session_meta(sid)
        assert meta["path"] == str(path)
        assert meta["dirty"] is True
    finally:
        source.close()
        destination.close()


def test_detachable_tab_bar_emits_only_for_thresholded_release_outside(qapp) -> None:
    bar = DetachableTabBar()
    bar.resize(320, 32)
    bar.addTab("A")
    bar.setTabData(0, "sid-a")
    bar.show()
    emitted: list[tuple[str, QPoint]] = []
    bar.detach_requested.connect(lambda sid, pos: emitted.append((sid, pos)))
    qapp.processEvents()
    try:
        QTest.mousePress(bar, Qt.LeftButton, pos=QPoint(20, 15))
        QTest.mouseRelease(bar, Qt.LeftButton, pos=QPoint(24, 15))
        assert emitted == []

        QTest.mousePress(bar, Qt.LeftButton, pos=QPoint(20, 15))
        QTest.mouseMove(bar, QPoint(120, 15), delay=10)
        QTest.mouseRelease(bar, Qt.LeftButton, pos=QPoint(120, 15))
        assert emitted == []

        QTest.mousePress(bar, Qt.LeftButton, pos=QPoint(20, 15))
        QTest.mouseMove(bar, QPoint(400, 80), delay=10)
        QTest.mouseRelease(bar, Qt.LeftButton, pos=QPoint(400, 80))
        assert len(emitted) == 1
        assert emitted[0][0] == "sid-a"
    finally:
        bar.close()
        qapp.processEvents()


def test_controller_removes_source_only_after_successful_handoff(qapp, tmp_path: Path) -> None:
    path = tmp_path / "atomic.pdf"
    _make_pdf(path)
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(path))
    sid = model.get_active_session_id()
    try:
        controller.set_session_handoff_callback(lambda _payload, _pos: False)
        controller.detach_document_session(sid, QPoint(100, 100))
        assert sid in model.session_ids

        captured: list[SessionTransferPayload] = []
        controller.set_session_handoff_callback(
            lambda payload, _pos: captured.append(payload) or True
        )
        controller.detach_document_session(sid, QPoint(100, 100))
        assert len(captured) == 1
        assert sid not in model.session_ids
    finally:
        view.close()
        model.close()
        qapp.processEvents()
