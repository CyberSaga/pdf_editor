"""P3-D Stage-B red-light tests: bounded preview pre-state baseline."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.text_commit.patch as patch_module  # noqa: E402
import model.text_commit.preview as preview_module  # noqa: E402
import model.text_commit.verify as verify_module  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.plan import PreparedEdit, prepare_plan  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)
from model.text_commit.verify import (  # noqa: E402
    PreStateBaseline,
    PreStateBaselineCache,
    capture_page_state,
)
from scripts.benchmark_p3c_postprepare_latency import _build_doc  # noqa: E402
from scripts.benchmark_p3d_interpretation_reuse import (  # noqa: E402
    LegacyPostInterpretation,
)

TARGET = "Price 2024"


def _stream_doc(*, tier1: bool = False) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    target = b"iii" if tier1 else TARGET.encode()
    tail = b" /F1 9 Tf (            tail) Tj" if tier1 else b""
    stream = b"BT /F1 12 Tf 72 700 Td (" + target + b") Tj" + tail + b" ET"
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def _prepare(
    doc: fitz.Document,
    *,
    target: str = TARGET,
    replacement: str = "Price 2025",
    max_tier: int = 0,
) -> PreparedEdit:
    plan = prepare_plan(
        doc,
        doc[0],
        target_text=target,
        replacement_text=replacement,
        expected_origin=None,
        target_bbox=None,
        registry=DocumentFontRegistry(doc),
        max_tier=max_tier,
    )
    assert isinstance(plan, PreparedEdit), plan
    return plan


def _request(doc: fitz.Document, generation: int) -> PlanPreviewRequest:
    return PlanPreviewRequest(
        session_key="p3d-stage-b",
        generation=generation,
        target_text=TARGET,
        replacement_text=f"Price 2{generation % 10}25",
        expected_origin=None,
        target_bbox=None,
        clip_rect=tuple(float(value) for value in doc[0].rect),
        render_scale=1.5,
    )


def _renderer(doc: fitz.Document) -> PlanPreviewRenderer:
    session = open_preview_session(doc, 0, "p3d-stage-b")
    assert session is not None
    return PlanPreviewRenderer(session)


def test_renderer_one_cold_plus_30_warm_is_one_miss_30_hits() -> None:
    doc = _stream_doc()
    renderer = _renderer(doc)
    for generation in range(1, 32):
        result = renderer.render(_request(doc, generation))
        assert result.plan_token is not None, result.reject_reason
    cache = renderer._pre_state_baseline
    assert (cache.misses, cache.stores, cache.hits) == (1, 1, 30)
    assert cache.entry_count == 1
    renderer.close()
    doc.close()


def test_warm_cache_capture_builds_no_page_interpretation(monkeypatch) -> None:
    doc = _stream_doc()
    page = doc[0]
    plan = _prepare(doc)
    cache = PreStateBaselineCache()
    first = cache.capture(doc, page, plan)
    counts: Counter[str] = Counter()
    for name in ("get_displaylist", "get_textpage", "get_pixmap"):
        original = getattr(fitz.Page, name)

        def counting(*args, _original=original, _name=name, **kwargs):
            counts[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(fitz.Page, name, counting)
    second = cache.capture(doc, page, plan)
    assert second == first
    assert counts == Counter()
    assert (cache.misses, cache.stores, cache.hits) == (1, 1, 1)
    doc.close()


@pytest.mark.parametrize("tier1", (False, True))
def test_hit_derived_page_state_matches_fresh_default(tier1: bool) -> None:
    doc = _stream_doc(tier1=tier1)
    plan = _prepare(
        doc,
        target="iii" if tier1 else TARGET,
        replacement="MMM" if tier1 else "Price 2025",
        max_tier=1 if tier1 else 0,
    )
    cache = PreStateBaselineCache()
    cache.capture(doc, doc[0], plan)
    assert cache.capture(doc, doc[0], plan) == capture_page_state(doc, doc[0], plan)
    doc.close()


def _fresh_cache(doc: fitz.Document) -> tuple[PreStateBaselineCache, PreparedEdit]:
    plan = _prepare(doc)
    cache = PreStateBaselineCache()
    cache.capture(doc, doc[0], plan)
    assert cache.misses == 1
    return cache, plan


def test_font_evidence_change_invalidates() -> None:
    doc = _stream_doc()
    cache, plan = _fresh_cache(doc)
    font_xref = doc[0].get_fonts(full=True)[0][0]
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Courier "
        "/Encoding /WinAnsiEncoding >>",
    )
    page = doc.reload_page(doc[0])
    assert cache.capture(doc, page, plan) == capture_page_state(doc, page, plan)
    assert (cache.misses, cache.stores, cache.hits) == (2, 2, 0)
    doc.close()


def test_annotation_geometry_change_invalidates() -> None:
    doc = _stream_doc()
    cache, plan = _fresh_cache(doc)
    annot = doc[0].add_rect_annot(fitz.Rect(300, 300, 340, 340))
    annot.update()
    page = doc.reload_page(doc[0])
    assert cache.capture(doc, page, plan) == capture_page_state(doc, page, plan)
    assert cache.misses == 2
    doc.close()


def test_unreverted_content_change_invalidates() -> None:
    doc = _stream_doc()
    cache, plan = _fresh_cache(doc)
    content_xref = doc[0].get_contents()[0]
    doc.update_stream(content_xref, doc.xref_stream(content_xref) + b"\n% changed")
    page = doc.reload_page(doc[0])
    assert cache.capture(doc, page, plan) == capture_page_state(doc, page, plan)
    assert cache.misses == 2
    doc.close()


@pytest.mark.parametrize("setting", ("small", "quad", "aa"))
def test_process_global_tool_state_invalidates(setting: str) -> None:
    old_small = bool(fitz.TOOLS.set_small_glyph_heights())
    old_quad = bool(fitz.TOOLS.unset_quad_corrections())
    old_aa = fitz.TOOLS.show_aa_level()
    doc = _stream_doc()
    try:
        cache, plan = _fresh_cache(doc)
        if setting == "small":
            fitz.TOOLS.set_small_glyph_heights(not old_small)
        elif setting == "quad":
            fitz.TOOLS.unset_quad_corrections(not old_quad)
        else:
            level = 4 if old_aa["text"] != 4 else 8
            fitz.TOOLS.set_aa_level(level)
        cache.capture(doc, doc[0], plan)
        assert cache.misses == 2
    finally:
        fitz.TOOLS.set_small_glyph_heights(old_small)
        fitz.TOOLS.unset_quad_corrections(old_quad)
        fitz.TOOLS.set_aa_level(old_aa["text"])
        fitz.TOOLS.set_graphics_min_line_width(old_aa["graphics_min_line_width"])
        doc.close()


def _deep_size(value: Any, seen: set[int] | None = None) -> int:
    if seen is None:
        seen = set()
    object_id = id(value)
    if object_id in seen:
        return 0
    seen.add(object_id)
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        size += sum(
            _deep_size(key, seen) + _deep_size(item, seen)
            for key, item in value.items()
        )
    elif isinstance(value, (tuple, list, set, frozenset)):
        size += sum(_deep_size(item, seen) for item in value)
    elif hasattr(value, "__dict__"):
        size += _deep_size(vars(value), seen)
    return size


def test_dense_entry_is_immutable_wrapper_free_and_within_bound() -> None:
    doc = _build_doc(dense=True)
    plan = _prepare(doc)
    cache = PreStateBaselineCache()
    cache.capture(doc, doc[0], plan)
    entry = cache.lookup_any()
    assert isinstance(entry, PreStateBaseline)
    assert isinstance(entry.pixmap_samples, bytes)
    assert isinstance(entry.pixmap_meta, tuple)
    assert isinstance(entry.span_origins, tuple)
    assert isinstance(entry.chars, tuple)
    forbidden = (
        fitz.Document,
        fitz.Page,
        fitz.DisplayList,
        fitz.TextPage,
        fitz.Pixmap,
        dict,
    )
    assert not any(isinstance(value, forbidden) for value in vars(entry).values())
    bound = (
        len(entry.pixmap_samples)
        + 160 * len(entry.span_origins)
        + 448 * len(entry.chars)
        + 1024 * 1024
    )
    assert _deep_size(entry) <= bound
    assert cache.entry_count == 1
    doc.close()


def test_miss_releases_temporary_interpretation(monkeypatch) -> None:
    doc = _stream_doc()
    plan = _prepare(doc)
    releases = 0
    original = verify_module.interpret_page

    def wrapped(page):
        nonlocal releases
        interpretation = original(page)
        real_release = interpretation.release

        def release():
            nonlocal releases
            releases += 1
            real_release()

        interpretation.release = release
        return interpretation

    monkeypatch.setattr(verify_module, "interpret_page", wrapped)
    PreStateBaselineCache().capture(doc, doc[0], plan)
    assert releases == 1
    doc.close()


def test_close_clears_baseline_and_is_idempotent() -> None:
    doc = _stream_doc()
    renderer = _renderer(doc)
    assert renderer.render(_request(doc, 1)).plan_token is not None
    cache = renderer._pre_state_baseline
    assert cache.entry_count == 1
    renderer.close()
    renderer.close()
    assert cache.entry_count == 0
    doc.close()


def test_verifier_exception_successful_revert_retains_baseline(monkeypatch) -> None:
    doc = _stream_doc()
    renderer = _renderer(doc)

    def fail_verify(*_args, **_kwargs):
        raise RuntimeError("verify failed")

    monkeypatch.setattr(preview_module, "verify_tier0_commit", fail_verify)
    with pytest.raises(RuntimeError, match="verify failed"):
        renderer.render(_request(doc, 1))
    assert renderer._pre_state_baseline.entry_count == 1
    renderer.close()
    doc.close()


def test_post_interpretation_exception_successful_revert_retains_baseline(
    monkeypatch,
) -> None:
    doc = _stream_doc()
    renderer = _renderer(doc)

    def fail_interpret(*_args, **_kwargs):
        raise RuntimeError("interpret failed")

    monkeypatch.setattr(preview_module, "interpret_page", fail_interpret)
    with pytest.raises(RuntimeError, match="interpret failed"):
        renderer.render(_request(doc, 1))
    assert renderer._pre_state_baseline.entry_count == 1
    renderer.close()
    doc.close()


def test_revert_exception_clears_baseline(monkeypatch) -> None:
    doc = _stream_doc()
    renderer = _renderer(doc)

    def fail_revert(*_args, **_kwargs):
        raise RuntimeError("revert failed")

    monkeypatch.setattr(patch_module.AppliedPatch, "revert", fail_revert)
    with pytest.raises(RuntimeError, match="revert failed"):
        renderer.render(_request(doc, 1))
    assert renderer._pre_state_baseline.entry_count == 0
    renderer.close()
    doc.close()


class DisabledBaseline:
    def __init__(self) -> None:
        self.engagement = 0

    def capture(self, doc, page, prepared):
        self.engagement += 1
        return capture_page_state(doc, page, prepared, reuse_rawdict=True)

    def clear(self) -> None:
        return None


def test_legacy_control_disables_both_reuse_layers(monkeypatch) -> None:
    shipped_doc = _stream_doc()
    shipped_renderer = _renderer(shipped_doc)
    shipped = shipped_renderer.render(_request(shipped_doc, 1))
    shipped_renderer.close()

    control_doc = _stream_doc()
    control_renderer = _renderer(control_doc)
    disabled = DisabledBaseline()
    control_renderer._pre_state_baseline = disabled
    engagement: Counter[str] = Counter()
    monkeypatch.setattr(
        preview_module,
        "interpret_page",
        lambda page: LegacyPostInterpretation(page, engagement),
    )
    control = control_renderer.render(_request(control_doc, 1))
    control_renderer.close()
    assert disabled.engagement == 1
    assert engagement["factory"] == 1
    assert (
        shipped.png_bytes,
        shipped.plan_token,
        shipped.reject_reason,
        shipped.clip_rect,
        shipped.prepared,
    ) == (
        control.png_bytes,
        control.plan_token,
        control.reject_reason,
        control.clip_rect,
        control.prepared,
    )
    shipped_doc.close()
    control_doc.close()
