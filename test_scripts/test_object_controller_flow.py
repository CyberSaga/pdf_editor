from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from controller.pdf_controller import PDFController
from model.object_requests import BatchDeleteObjectsRequest, BatchMoveObjectsRequest, DeleteObjectRequest, MoveObjectRequest, ObjectRef, RotateObjectRequest


class _FakeCommandManager:
    def __init__(self) -> None:
        self.recorded = []

    def record(self, cmd) -> None:
        self.recorded.append(cmd)


class _FakeModel:
    def __init__(self) -> None:
        self.doc = [object()]
        self.command_manager = _FakeCommandManager()
        self.calls = []

    def _capture_doc_snapshot(self) -> bytes:
        return b"snapshot"

    def move_object(self, request):
        self.calls.append(("move", request))
        return True

    def rotate_object(self, request):
        self.calls.append(("rotate", request))
        return True

    def delete_object(self, request):
        self.calls.append(("delete", request))
        return True

    def get_object_info_at_point(self, page_num: int, point: fitz.Point):
        self.calls.append(("hit", page_num, point))
        return "hit-info"


def _make_controller() -> PDFController:
    controller = PDFController.__new__(PDFController)
    controller.model = _FakeModel()
    controller.view = SimpleNamespace(current_page=0)
    controller._invalidate_active_render_state = lambda *args, **kwargs: None
    controller._update_undo_redo_tooltips = lambda: None
    controller.show_page = lambda page_idx: None
    return controller


def test_controller_delegates_object_hit_info() -> None:
    controller = _make_controller()
    point = fitz.Point(10, 20)
    result = PDFController.get_object_info_at_point(controller, 1, point)
    assert result == "hit-info"
    assert controller.model.calls[-1] == ("hit", 1, point)


def test_controller_records_snapshot_for_move_object() -> None:
    controller = _make_controller()
    request = MoveObjectRequest("obj-1", "textbox", 1, 1, fitz.Rect(10, 20, 30, 40))

    PDFController.move_object(controller, request)

    assert controller.model.calls[-1] == ("move", request)
    assert len(controller.model.command_manager.recorded) == 1


def test_controller_records_snapshot_for_batch_move_object() -> None:
    controller = _make_controller()
    batch = BatchMoveObjectsRequest(
        moves=[
            MoveObjectRequest("obj-1", "rect", 1, 1, fitz.Rect(10, 20, 30, 40)),
            MoveObjectRequest("obj-2", "rect", 1, 1, fitz.Rect(50, 60, 70, 80)),
        ]
    )

    PDFController.move_object(controller, batch)

    assert ("move", batch.moves[0]) in controller.model.calls
    assert ("move", batch.moves[1]) in controller.model.calls
    assert len(controller.model.command_manager.recorded) == 1


def test_controller_records_snapshot_for_rotate_and_delete_object() -> None:
    controller = _make_controller()
    rotate = RotateObjectRequest("obj-1", "textbox", 1, 90)
    delete = DeleteObjectRequest("obj-2", "rect", 1)

    PDFController.rotate_object(controller, rotate)
    PDFController.delete_object(controller, delete)

    assert ("rotate", rotate) in controller.model.calls
    assert ("delete", delete) in controller.model.calls
    assert len(controller.model.command_manager.recorded) == 2


def test_controller_records_snapshot_for_batch_delete_object() -> None:
    controller = _make_controller()
    batch = BatchDeleteObjectsRequest(
        objects=[
            ObjectRef(object_id="obj-1", object_kind="rect", page_num=1),
            ObjectRef(object_id="obj-2", object_kind="textbox", page_num=1),
        ]
    )

    PDFController.delete_object(controller, batch)

    # Must apply deletes and record exactly one snapshot command for the whole batch.
    assert ("delete", DeleteObjectRequest("obj-1", "rect", 1)) in controller.model.calls
    assert ("delete", DeleteObjectRequest("obj-2", "textbox", 1)) in controller.model.calls
    assert len(controller.model.command_manager.recorded) == 1
