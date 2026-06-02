"""Security patch P4 (finding F8): watermark JSON coercion on load.

Embedded watermark metadata comes from untrusted PDF bytes. ``_coerce_wm`` must
validate types and clamp numeric ranges / cap text length on load (CWE-20), and
``_load_watermarks_from_doc`` must drop structurally-invalid entries rather than
let them reach rendering. (It is JSON, not pickle — no code execution — so this
is robustness hardening.)
"""

from __future__ import annotations

import json

import fitz

from model.tools.watermark_tool import WatermarkTool, _coerce_wm


def test_coerce_clamps_oversized_font_size() -> None:
    out = _coerce_wm({"id": "a", "pages": [1], "font_size": 1e9})
    assert out is not None
    assert out["font_size"] == 1000.0


def test_coerce_floors_tiny_font_size() -> None:
    out = _coerce_wm({"id": "a", "pages": [1], "font_size": 0})
    assert out is not None
    assert out["font_size"] == 1.0


def test_coerce_truncates_long_text() -> None:
    out = _coerce_wm({"id": "a", "pages": [1], "text": "x" * 10_000})
    assert out is not None
    assert len(out["text"]) == 5_000


def test_coerce_caps_page_count() -> None:
    out = _coerce_wm({"id": "a", "pages": list(range(20_000))})
    assert out is not None
    assert len(out["pages"]) == 10_000


def test_coerce_clamps_opacity_and_wraps_angle() -> None:
    out = _coerce_wm({"id": "a", "pages": [1], "opacity": 5.0, "angle": 405})
    assert out is not None
    assert out["opacity"] == 1.0
    assert out["angle"] == 45.0


def test_coerce_drops_wrong_type_pages() -> None:
    assert _coerce_wm({"id": "a", "pages": "all"}) is None


def test_coerce_drops_missing_required_keys() -> None:
    assert _coerce_wm({"pages": [1]}) is None
    assert _coerce_wm({"id": "a"}) is None


def test_coerce_preserves_valid_watermark_fields() -> None:
    wm = {
        "id": "wm-1",
        "pages": [1, 2],
        "text": "DRAFT",
        "angle": 45,
        "opacity": 0.3,
        "font_size": 24,
        "color": [0.8, 0.8, 0.8],  # JSON round-trips tuples as lists
        "font": "helv",
        "offset_x": 5,
        "offset_y": -3,
        "line_spacing": 1.3,
    }
    out = _coerce_wm(wm)
    assert out is not None
    assert out["id"] == "wm-1"
    assert out["pages"] == [1, 2]
    assert out["text"] == "DRAFT"
    assert out["angle"] == 45.0
    assert out["opacity"] == 0.3
    assert out["font_size"] == 24.0
    assert out["color"] == (0.8, 0.8, 0.8)
    assert out["font"] == "helv"
    assert out["offset_x"] == 5.0
    assert out["offset_y"] == -3.0
    assert out["line_spacing"] == 1.3


def test_load_watermarks_drops_bad_entries_and_clamps_good(tmp_path) -> None:
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    blob = json.dumps(
        [
            {"id": "good", "pages": [1], "text": "hi", "font_size": 1e9, "opacity": 5.0},
            {"id": "bad-pages", "pages": "all"},  # dropped
            {"no_id": True, "pages": [1]},  # dropped (missing id)
            ["not", "a", "dict"],  # dropped (not a dict)
        ]
    ).encode("utf-8")
    doc.embfile_add(WatermarkTool.WATERMARK_EMBED_NAME, blob)

    tool = WatermarkTool.__new__(WatermarkTool)
    loaded = tool._load_watermarks_from_doc(doc)
    doc.close()

    assert len(loaded) == 1
    assert loaded[0]["id"] == "good"
    assert loaded[0]["font_size"] == 1000.0
    assert loaded[0]["opacity"] == 1.0
