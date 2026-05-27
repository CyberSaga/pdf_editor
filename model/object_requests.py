from __future__ import annotations

from dataclasses import dataclass

import fitz


@dataclass(frozen=True)
class ObjectRef:
    object_id: str
    object_kind: str
    page_num: int


@dataclass(frozen=True)
class ObjectHitInfo:
    object_kind: str
    object_id: str
    page_num: int
    bbox: fitz.Rect
    rotation: float = 0.0
    supports_move: bool = True
    supports_delete: bool = True
    supports_rotate: bool = False


@dataclass(frozen=True)
class MoveObjectRequest:
    object_id: str
    object_kind: str
    source_page: int
    destination_page: int
    destination_rect: fitz.Rect


@dataclass(frozen=True)
class BatchMoveObjectsRequest:
    moves: list[MoveObjectRequest]


@dataclass(frozen=True)
class RotateObjectRequest:
    object_id: str
    object_kind: str
    page_num: int
    rotation_delta: int
    # When set, the object is rotated to this absolute angle (degrees, screen
    # clockwise) about its centre — used by free drag-rotation. When None, the
    # legacy 90°-step ``rotation_delta`` "fit to rect" path is used.
    absolute_rotation: float | None = None


@dataclass(frozen=True)
class DeleteObjectRequest:
    object_id: str
    object_kind: str
    page_num: int


@dataclass(frozen=True)
class BatchDeleteObjectsRequest:
    objects: list[ObjectRef]


@dataclass(frozen=True)
class ResizeObjectRequest:
    object_id: str
    object_kind: str
    page_num: int
    destination_rect: fitz.Rect


@dataclass(frozen=True)
class InsertImageObjectRequest:
    page_num: int
    visual_rect: fitz.Rect
    image_bytes: bytes
    rotation: int = 0
