from __future__ import annotations

import sys
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.object_requests import DeleteObjectRequest, MoveObjectRequest, ObjectHitInfo, RotateObjectRequest


def test_object_request_shapes() -> None:
    hit = ObjectHitInfo(
        object_kind="textbox",
        object_id="obj-1",
        page_num=1,
        bbox=fitz.Rect(10, 20, 30, 40),
        rotation=90,
        supports_rotate=True,
    )
    move = MoveObjectRequest(
        object_id="obj-1",
        object_kind="textbox",
        source_page=1,
        destination_page=1,
        destination_rect=fitz.Rect(15, 25, 35, 45),
    )
    rotate = RotateObjectRequest(
        object_id="obj-1",
        object_kind="textbox",
        page_num=1,
        rotation_delta=90,
    )
    delete = DeleteObjectRequest(
        object_id="obj-1",
        object_kind="textbox",
        page_num=1,
    )

    assert hit.object_kind == "textbox"
    assert hit.rotation == 90
    assert move.destination_rect == fitz.Rect(15, 25, 35, 45)
    assert rotate.rotation_delta == 90
    assert delete.page_num == 1
