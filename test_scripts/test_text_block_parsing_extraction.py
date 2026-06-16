"""R3.1 red-light: the stateless parsing layer must live in model/text_block_parsing.py.

This guards the god-module decomposition seam that lifts the pure fitz-dict ->
dataclass transforms out of TextBlockManager. The functions own no instance state,
so they must be importable and callable as free functions, and the manager's
private methods must keep delegating to them (public API unchanged).
"""

from __future__ import annotations

import fitz

# RED before extraction: this module does not exist yet (hard ImportError on collect).
import model.text_block_parsing as tbp

from model.text_block import (  # noqa: E402
    EditableParagraph as MgrEditableParagraph,
)
from model.text_block import (  # noqa: E402
    EditableSpan as MgrEditableSpan,
)
from model.text_block import (  # noqa: E402
    TextBlock as MgrTextBlock,
)
from model.text_block import (  # noqa: E402
    TextBlockManager,
)


def test_parsing_module_exposes_dataclasses_and_helpers() -> None:
    # The leaf module owns the output dataclasses and the geometry helpers.
    assert hasattr(tbp, "TextBlock")
    assert hasattr(tbp, "EditableSpan")
    assert hasattr(tbp, "EditableParagraph")
    assert callable(tbp.rotation_degrees_from_dir)
    # text_block must keep re-exporting them so existing imports do not break.
    assert tbp.TextBlock is MgrTextBlock
    assert tbp.EditableSpan is MgrEditableSpan
    assert tbp.EditableParagraph is MgrEditableParagraph


def test_parse_functions_are_module_level_free_functions() -> None:
    for name in (
        "_parse_block",
        "_parse_spans",
        "_parse_runs_from_raw_block",
        "_parse_runs_from_raw_line",
        "_build_paragraphs",
        "_merge_vertical_paragraphs",
        "_expand_ligatures",
        "_match_by_text",
        "_closest_to_center",
        "_dynamic_scan",
        "_extract_plain_text_lines",
        "_repair_replacement_chars",
    ):
        assert callable(getattr(tbp, name)), name


def test_parse_block_builds_textblock_from_fitz_dict() -> None:
    block = {
        "type": 0,
        "bbox": (10.0, 10.0, 100.0, 24.0),
        "lines": [
            {
                "dir": (1.0, 0.0),
                "spans": [
                    {"text": "Hello", "font": "Times", "size": 14.0, "color": 0,
                     "bbox": (10, 10, 50, 24), "origin": (10, 22)},
                    {"text": " World", "font": "Times", "size": 14.0, "color": 0,
                     "bbox": (50, 10, 100, 24), "origin": (50, 22)},
                ],
            }
        ],
    }
    tb = tbp._parse_block(0, 0, block)
    assert isinstance(tb, tbp.TextBlock)
    assert tb.text == "Hello World"
    assert tb.font == "Times"
    assert tb.size == 14.0
    assert tb.rotation == 0
    assert tb.block_id == "page_0_block_0"


def test_build_paragraphs_joins_visual_lines_with_space() -> None:
    runs = [
        tbp.EditableSpan("run-1", 0, 0, 0, 0, fitz.Rect(10, 10, 80, 22),
                         fitz.Point(10, 20), "serve the", "helv", 12.0,
                         (0.0, 0.0, 0.0), (1.0, 0.0), 0),
        tbp.EditableSpan("run-2", 0, 0, 1, 0, fitz.Rect(10, 26, 80, 38),
                         fitz.Point(10, 36), "public", "helv", 12.0,
                         (0.0, 0.0, 0.0), (1.0, 0.0), 0),
    ]
    paras = tbp._build_paragraphs(0, runs)
    assert len(paras) == 1
    assert paras[0].text == "serve the public"


def test_manager_delegates_match_module_functions() -> None:
    # Public API unchanged: the manager keeps its private parse methods, and they
    # produce identical output to the free functions.
    runs = [
        MgrEditableSpan("run-1", 0, 0, 0, 0, fitz.Rect(10, 10, 80, 22),
                        fitz.Point(10, 20), "serve the", "helv", 12.0,
                        (0.0, 0.0, 0.0), (1.0, 0.0), 0),
        MgrEditableSpan("run-2", 0, 0, 1, 0, fitz.Rect(10, 26, 80, 38),
                        fitz.Point(10, 36), "public", "helv", 12.0,
                        (0.0, 0.0, 0.0), (1.0, 0.0), 0),
    ]
    mgr = TextBlockManager()
    via_mgr = mgr._build_paragraphs(0, runs)
    via_mod = tbp._build_paragraphs(0, runs)
    assert [p.text for p in via_mgr] == [p.text for p in via_mod] == ["serve the public"]
