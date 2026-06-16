"""Edit-text / redaction engine (R3.5 god-module decomposition seam — LAST model seam).

The edit-text resolution, redaction insertion, protected-span replay, overflow
push-down and post-edit verification extracted out of PDFModel as free functions
(``def fn(model: PDFModel, ...)``), mirroring ``model/pdf_optimizer.py`` and
``model/pdf_object_ops.py``. PDFModel keeps 1-line delegating wrappers (``edit_text``
plus the private helpers the test net pokes directly). Bodies are moved verbatim
(only ``self`` -> ``model``); the undo-snapshot boundary stays with ``edit_text``'s
caller contract (snapshot captured once, restored on failure). ``_classify_insert_path``
and ``_EditTextResolveResult`` move here too and are re-exported from ``pdf_model`` so
existing ``from model.pdf_model import ...`` test imports keep working.

Cross-cutting helpers reached via ``model.`` (they STAY on PDFModel because callers
outside this cluster use them): ``_needs_cjk_font`` (object-ops), ``_resolve_font_for_push``
(add-text), ``_convert_text_to_html`` / ``_build_insert_css`` / ``_build_multi_style_html``
(controller + view preview), ``_maybe_garbage_collect`` (encryption-preserving roundtrip).
"""

from __future__ import annotations

import difflib
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import fitz

from model.edit_commands import EditTextResult
from model.geometry import clamp_rect_to_page, rect_union
from model.text_block import EditableSpan, TextBlock
from model.text_normalization import normalize_text, token_coverage_ratio

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EditTextResolveResult:
    target_span: EditableSpan
    resolved_target_span_id: str
    effective_target_mode: str
    target_member_span_ids: set[str]
    overlap_cluster: list[EditableSpan]
    protected_spans: list[EditableSpan]
    target: TextBlock
    resolved_font: str
    rotation: int
    is_vertical: bool
    insert_rotate: int
    redact_rect: fitz.Rect
    reopen_anchor_rect: fitz.Rect | None = None


def _classify_insert_path(
    *,
    new_text: str,
    member_spans: list,
    rotation: int,
    is_vertical: bool,
    preserve_multi_style: bool,
    has_new_rect: bool,
    needs_cjk: bool,
    text_width: float,
    available_width: float,
    size: float,
) -> Literal["htmlbox", "fast"]:
    """Shared insert-path classifier: ``"fast"`` (single-line ``insert_text``)
    vs ``"htmlbox"`` (``insert_htmlbox``).

    The preview renderer (view) and the commit path (model) MUST both route
    through this function so an opened editor and the committed PDF never
    diverge in which renderer drew the glyphs.

    ``"fast"`` is chosen only for the strict single-line, single-style,
    unrotated, no-wrap case that ``page.insert_text`` can reproduce exactly.
    Empty ``member_spans`` always falls back to ``"htmlbox"``: there is no
    anchor span to derive the ``insert_text`` origin from, and a downstream
    ``min(member_spans, ...)`` would raise.
    """
    if not member_spans:
        return "htmlbox"
    if is_vertical:
        return "htmlbox"
    if rotation in (90, 270):
        return "htmlbox"
    if has_new_rect:
        return "htmlbox"
    if "\n" in (new_text or ""):
        return "htmlbox"
    if needs_cjk:
        return "htmlbox"
    if preserve_multi_style:
        return "htmlbox"
    try:
        span_top = min(float(s.bbox.y0) for s in member_spans)
        span_bot = max(float(s.bbox.y1) for s in member_spans)
    except (AttributeError, TypeError, ValueError):
        return "htmlbox"
    if (span_bot - span_top) > max(2.0, float(size) * 1.5):
        return "htmlbox"
    if not (0.0 < float(text_width) <= float(available_width)):
        return "htmlbox"
    return "fast"


def _has_complex_script(model: PDFModel, text: str) -> bool:
    """
    判斷文字是否包含常見複雜腳本（RTL/CJK）。
    用於在文字擷取不穩定時放寬驗證閾值（僅限特定流程）。
    """
    if not text:
        return False
    return bool(
        re.search(
            r"[\u0590-\u05ff\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]",
            text,
        )
    )

def _push_down_overlapping_text(
    model: PDFModel,
    page: fitz.Page,
    page_rect: fitz.Rect,
    above_y: float,
    new_bottom: float,
    edit_x0: float,
    edit_x1: float,
) -> None:
    """
    換行溢出修正：將位於 [above_y, new_bottom] Y 區間內（且與
    [edit_x0, edit_x1] X 範圍有重疊）的文字塊向下推移，使它們
    落在 new_bottom 之後，保留原有文字內容，不重疊於新插入的文字。

    支援 cascade：每個 block 推移後，若與下一個 block 仍有重疊，
    自動繼續推移，直到頁面底部。

    Args:
        page       : 當前頁面物件
        page_rect  : 頁面邊界 Rect
        above_y    : 原始 block 的底部 Y（= redact_rect.y1）
        new_bottom : 新插入文字的底部 Y（= shrunk_rect.y1）
        edit_x0    : 編輯區 X 左邊界
        edit_x1    : 編輯區 X 右邊界
    """
    GAP   = 2.0   # 推移後與上方文字的最小間距
    X_TOL = 5.0   # X 方向重疊容差
    page_idx = page.number

    # ── 1. 取得整頁文字結構 ──
    # 不使用 TEXT_PRESERVE_LIGATURES：確保 span 文字中的 ﬁ/ﬀ/ﬂ 等合字
    # 已被展開（ﬁ→fi、ﬀ→ff 等），避免 insert_text(helv) 因字型不支援合字
    # 而靜默丟棄字元，導致 push-down 後文字殘缺。
    raw = page.get_text(
        "dict",
        flags=fitz.TEXT_PRESERVE_WHITESPACE,
    )

    # ── 2. 找出溢出區間內且 X 重疊的文字 block ──
    candidates: list[tuple[fitz.Rect, dict]] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:      # 只處理純文字 block
            continue
        bbox = fitz.Rect(block["bbox"])
        # Y 範圍：必須在 above_y 和 new_bottom + margin 之間開始
        if bbox.y0 < above_y - 1.0:
            continue
        if bbox.y0 > new_bottom + 5.0:
            continue
        # X 重疊：至少有部分與編輯欄重疊
        if bbox.x1 < edit_x0 - X_TOL or bbox.x0 > edit_x1 + X_TOL:
            continue
        candidates.append((fitz.Rect(bbox), block))

    if not candidates:
        logger.debug("_push_down_overlapping_text: 溢出區內無需推移的文字塊")
        return

    # ── 3. 按 y0 排序，cascade 計算各 block 的 delta_y ──
    candidates.sort(key=lambda c: c[0].y0)
    push_floor = new_bottom + GAP   # 目前可用的最低安全邊界

    plan: list[tuple[fitz.Rect, dict, float]] = []   # (bbox, block, delta_y)
    for bbox, block in candidates:
        delta_y = max(0.0, push_floor - bbox.y0)
        new_y1  = bbox.y1 + delta_y
        if new_y1 > page_rect.y1 + 5.0:
            logger.warning(
                f"_push_down: block [y={bbox.y0:.0f}~{bbox.y1:.0f}] "
                f"推移 {delta_y:.1f}pt 後超出頁面，跳過"
            )
            push_floor = max(push_floor, bbox.y1 + GAP)
            continue
        plan.append((fitz.Rect(bbox), block, delta_y))
        push_floor = new_y1 + GAP   # cascade：更新安全邊界

    if not plan:
        return

    # ── 4. 預先收集所有 span 資料（讀），避免 redact 後影響 get_text ──
    insert_tasks: list[dict] = []
    redact_rects: list[fitz.Rect] = []
    shifted_annots: list[dict] = []

    for bbox, block, delta_y in plan:
        redact_rects.append(fitz.Rect(bbox))
        # 儲存此 block 上的 annotation 並計算推移後位置
        for saved_a in model.tools.annotation._save_overlapping_annots(page, bbox):
            r = fitz.Rect(saved_a["rect"])
            shifted_annots.append(dict(
                saved_a,
                rect=fitz.Rect(r.x0, r.y0 + delta_y, r.x1, r.y1 + delta_y),
            ))
        # 收集 span 資訊
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                orig = span.get("origin")
                if not orig:
                    continue
                c_int = span.get("color", 0)
                insert_tasks.append({
                    "origin": fitz.Point(orig[0], orig[1] + delta_y),
                    "text":   span.get("text", ""),
                    "font":   span.get("font", "helv"),
                    "size":   float(span.get("size", 12)),
                    "color":  (
                        ((c_int >> 16) & 0xFF) / 255.0,
                        ((c_int >>  8) & 0xFF) / 255.0,
                        ( c_int        & 0xFF) / 255.0,
                    ),
                })

    # ── 5. 批次 Redact（一次 apply，減少 PDF stream 操作次數）──
    for rect in redact_rects:
        page.add_redact_annot(rect)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    # 在推移後的位置還原 annotation
    if shifted_annots:
        model.tools.annotation._restore_annots(page, shifted_annots)

    # ── 6. 批次 Insert（使用 insert_htmlbox 確保 Unicode 完整保留）──
    # 改用 insert_htmlbox（而非 insert_text）的原因：
    # insert_text(fontname="helv") 會靜默丟棄 helv 不支援的字元（如 €、emoji），
    # 導致 push-down 後文字殘缺。insert_htmlbox 使用 CSS 渲染引擎，
    # 完整支援 Unicode，確保 € 等特殊字元能被正確插入與還原。
    import html as _html_module
    inserted = 0
    for task in insert_tasks:
        if not task["text"].strip():
            continue
        x  = float(task["origin"].x)
        y  = float(task["origin"].y)  # baseline
        sz = float(task["size"])
        r, g, b = task["color"]
        # 估算文字寬度（保守估計）
        est_w  = max(sz * len(task["text"]) * 0.75, sz * 2)
        _pr    = page.rect
        x0     = max(x, _pr.x0)
        x1     = min(x + est_w, _pr.x1)
        y0     = max(y - sz * 1.15, _pr.y0)  # 基線上方（ascender）
        y1     = min(y + sz * 0.40, _pr.y1)  # 基線下方（descender）
        if x1 <= x0 or y1 <= y0:
            continue
        color_hex = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        html_str = (
            f'<span style="color:{color_hex}">'
            f'{_html_module.escape(task["text"])}</span>'
        )
        css_str = (
            f"* {{ font-size: {sz}pt; white-space: pre; "
            f"margin:0; padding:0; }}"
        )
        try:
            page.insert_htmlbox(
                fitz.Rect(x0, y0, x1, y1),
                html_str, css=css_str,
            )
            inserted += 1
        except Exception as e_html:
            # 最後回退：仍嘗試 insert_text（可能丟字元，但不會崩潰）
            logger.debug(
                f"_push_down insert_htmlbox 失敗，回退 insert_text: {e_html}"
            )
            try:
                page.insert_text(
                    task["origin"], task["text"],
                    fontname="helv",
                    fontsize=sz, color=task["color"],
                )
                inserted += 1
            except Exception as e2:
                logger.warning(
                    f"_push_down: span '{task['text'][:20]}' 無法插入: {e2}"
                )

    # ── 7. 更新 TextBlockManager 索引中被推移 block 的 layout_rect ──
    for bbox, _block, delta_y in plan:
        new_rect = fitz.Rect(
            bbox.x0, bbox.y0 + delta_y,
            bbox.x1, bbox.y1 + delta_y,
        )
        tb = model.block_manager.find_by_rect(page_idx, bbox)
        if tb:
            model.block_manager.update_block(tb, layout_rect=new_rect)

    logger.debug(
        f"_push_down_overlapping_text: 推移了 {len(plan)} 個 block，"
        f"插入 {inserted} 個 span"
    )

def _replay_protected_spans(model: PDFModel, page: fitz.Page, spans: list[EditableSpan]) -> None:
    for span in spans:
        text = (span.text or "").rstrip("\n")
        if not text:
            continue
        fontsize = max(1.0, float(span.size))
        color = tuple(span.color) if span.color else (0.0, 0.0, 0.0)
        rotate = int(span.rotation) if span.rotation in (0, 90, 180, 270) else 0
        raw_font = span.font or "helv"
        fontname = model._resolve_font_for_push(raw_font)
        is_cjk_text = model._needs_cjk_font(text)

        # CJK text can be silently dropped by insert_text(helv) without raising.
        # Prefer HTML replay first to preserve Unicode reliably.
        if is_cjk_text:
            try:
                bbox = fitz.Rect(span.bbox)
                if bbox.width < 2:
                    bbox.x1 = bbox.x0 + max(2.0, fontsize * 0.8)
                if bbox.height < 2:
                    bbox.y1 = bbox.y0 + max(2.0, fontsize * 1.2)
                html_content = model._convert_text_to_html(
                    text, int(round(fontsize)), color, latin_font=fontname
                )
                css = model._build_insert_css(fontsize, color, fontname)
                page.insert_htmlbox(
                    clamp_rect_to_page(bbox, page.rect),
                    html_content,
                    css=css,
                    rotate=rotate,
                    scale_low=0,
                )
                continue
            except Exception as e_html:
                logger.debug(
                    "protected replay html fallback failed span=%s err=%s; fallback to insert_text candidates",
                    span.span_id,
                    e_html,
                )

        candidates = [fontname]
        if is_cjk_text:
            candidates.extend(["china-ts", "helv"])
        else:
            candidates.extend(["helv", "tiro", "cour"])

        inserted = False
        tried: list[str] = []
        for cand in candidates:
            if cand in tried:
                continue
            tried.append(cand)
            try:
                page.insert_text(
                    fitz.Point(span.origin.x, span.origin.y),
                    text,
                    fontname=cand,
                    fontsize=fontsize,
                    color=color,
                    rotate=rotate,
                )
                inserted = True
                break
            except Exception as e_font:
                logger.debug(
                    "protected replay fallback failed span=%s font=%s err=%s",
                    span.span_id,
                    cand,
                    e_font,
                )

        if inserted:
            continue

        # Last fallback: htmlbox path is more tolerant for non-base14 fonts.
        bbox = fitz.Rect(span.bbox)
        if bbox.width < 2:
            bbox.x1 = bbox.x0 + max(2.0, fontsize * 0.8)
        if bbox.height < 2:
            bbox.y1 = bbox.y0 + max(2.0, fontsize * 1.2)
        html_content = model._convert_text_to_html(
            text, int(round(fontsize)), color, latin_font=fontname
        )
        css = model._build_insert_css(fontsize, color, fontname)
        page.insert_htmlbox(
            clamp_rect_to_page(bbox, page.rect),
            html_content,
            css=css,
            rotate=rotate,
            scale_low=0,
        )

def _validate_protected_spans(model: PDFModel, page: fitz.Page, protected_spans: list[EditableSpan]) -> bool:
    full_page = normalize_text(page.get_text("text"))
    for span in protected_spans:
        probe = normalize_text(span.text)
        if probe and probe not in full_page:
            logger.warning("protected span missing after replay: %s", span.span_id)
            return False
    return True

def _resolve_edit_target(
    model: PDFModel,
    *,
    page_num: int,
    page_idx: int,
    page: fitz.Page,
    rect: fitz.Rect,
    new_text: str,
    font: str,
    size: float,
    color: tuple,
    original_text: str | None,
    new_rect: fitz.Rect | None,
    resolved_target_span_id: str | None,
    effective_target_mode: str,
) -> tuple[EditTextResult, _EditTextResolveResult | None]:
    target_span = None
    if resolved_target_span_id:
        target_span = model.block_manager.find_run_by_id(page_idx, resolved_target_span_id)
        if target_span is None:
            logger.debug("target_span_id not found in current index: %s", resolved_target_span_id)

    if target_span is None:
        target = model.block_manager.find_by_rect(
            page_idx, rect, original_text=original_text, doc=model.doc
        )
        if not target:
            logger.warning("無法找到目標文字方塊，頁面 %s 矩形 %s", page_num, rect)
            return EditTextResult.TARGET_BLOCK_NOT_FOUND, None

        clip_text = page.get_text("text", clip=target.rect).strip()
        norm_clip = normalize_text(clip_text)
        norm_block = normalize_text(target.text)
        if norm_block and norm_clip:
            match_ratio = difflib.SequenceMatcher(None, norm_block, norm_clip).ratio()
            if match_ratio < 0.5:
                logger.debug("索引文字與頁面文字不匹配 (ratio=%.2f)，重建該頁索引", match_ratio)
                model.block_manager.rebuild_page(page_idx, model.doc)
                target = model.block_manager.find_by_rect(
                    page_idx, rect, original_text=original_text, doc=model.doc
                )
                if not target:
                    logger.warning("重建索引後仍找不到目標文字方塊")
                    return EditTextResult.TARGET_BLOCK_NOT_FOUND, None

        candidate_spans = model.block_manager.find_overlapping_runs(page_idx, target.layout_rect, tol=0.5)
        if candidate_spans:
            text_probe = normalize_text(original_text or target.text or "")
            if text_probe:
                scored = sorted(
                    candidate_spans,
                    key=lambda sp: difflib.SequenceMatcher(
                        None, text_probe, normalize_text(sp.text)
                    ).ratio(),
                )
                target_span = scored[-1]
            else:
                target_span = candidate_spans[-1]
            resolved_target_span_id = target_span.span_id

    if target_span is None:
        logger.warning("unable to resolve target span for edit on page %s", page_num)
        return EditTextResult.TARGET_SPAN_NOT_FOUND, None

    if not resolved_target_span_id:
        resolved_target_span_id = target_span.span_id

    target_member_span_ids: set[str] = {resolved_target_span_id}
    # First run-mode edit of this span records its original bbox+size as
    # the reopen anchor; later edits reuse it so the box doesn't cumulate
    # shrink. Drag edits (new_rect) and paragraph mode never anchor.
    reopen_anchor_rect: fitz.Rect | None = None
    if effective_target_mode == "run" and new_rect is None and resolved_target_span_id:
        reopen_anchor_rect = model._get_run_reopen_anchor_rect(page_idx, resolved_target_span_id)
        if reopen_anchor_rect is None:
            reopen_anchor_rect = fitz.Rect(target_span.bbox)
            model._set_run_reopen_anchor_rect(page_idx, resolved_target_span_id, reopen_anchor_rect)
        if model._get_run_reopen_anchor_size(page_idx, resolved_target_span_id) is None:
            model._set_run_reopen_anchor_size(page_idx, resolved_target_span_id, float(target_span.size))
    target_bbox_for_cluster = fitz.Rect(
        reopen_anchor_rect if reopen_anchor_rect is not None else target_span.bbox
    )
    target_block_idx = target_span.block_idx
    target_rotation = int(target_span.rotation)
    if effective_target_mode == "paragraph":
        para = model._resolve_paragraph_candidate(
            page_idx=page_idx,
            probe_rect=fitz.Rect(rect),
            original_text=original_text,
            preferred_run_id=target_span.span_id,
        )
        if para is not None:
            target_member_span_ids = set(para.run_ids)
            target_bbox_for_cluster = fitz.Rect(para.bbox)
            target_block_idx = para.block_idx
            target_rotation = int(para.rotation)
            if para.run_ids and resolved_target_span_id not in target_member_span_ids:
                resolved_target_span_id = para.run_ids[0]
            reopen_anchor_rect = None
        else:
            logger.debug(
                "paragraph mode requested but paragraph not resolved for run=%s; fallback to run mode",
                target_span.span_id,
            )
            effective_target_mode = "run"

    overlap_cluster = model.block_manager.find_overlapping_runs(
        page_idx,
        target_bbox_for_cluster,
        tol=0.5,
    )
    if not overlap_cluster:
        overlap_cluster = [
            s for s in model.block_manager.get_runs(page_idx)
            if s.span_id in target_member_span_ids
        ]
    if not overlap_cluster:
        overlap_cluster = [target_span]

    protected_spans = [s for s in overlap_cluster if s.span_id not in target_member_span_ids]
    cluster_union = rect_union([fitz.Rect(s.bbox) for s in overlap_cluster])

    target = model.block_manager.find_by_id(
        page_idx,
        f"page_{page_idx}_block_{target_block_idx}",
    )
    if not target:
        target = model.block_manager.find_by_rect(
            page_idx, fitz.Rect(target_bbox_for_cluster), original_text=original_text, doc=model.doc
        )
    if not target:
        logger.warning("unable to resolve target block for span %s", resolved_target_span_id)
        return EditTextResult.TARGET_BLOCK_NOT_FOUND, None

    resolved_font = model._resolve_add_text_font(font)
    current_font = model._resolve_add_text_font(target.font or "helv")
    current_text_norm = normalize_text(target.text or "")
    requested_text_norm = normalize_text(new_text)
    size_unchanged = abs(float(size) - float(target.size)) <= 0.01
    target_color = tuple(float(c) for c in (target.color or (0.0, 0.0, 0.0)))
    request_color = tuple(float(c) for c in (color or (0.0, 0.0, 0.0)))
    color_unchanged = len(target_color) == len(request_color) and all(
        abs(a - b) <= 0.001 for a, b in zip(target_color, request_color)
    )
    if (
        new_rect is None
        and requested_text_norm == current_text_norm
        and resolved_font == current_font
        and size_unchanged
        and color_unchanged
    ):
        logger.debug(
            "edit_text no-op: page=%s span=%s text/style unchanged; skip geometry re-estimation",
            page_num,
            resolved_target_span_id,
        )
        return EditTextResult.NO_CHANGE, None

    rotation = int(target_rotation)
    is_vertical = rotation in (90, 270)
    insert_rotate = model._insert_rotate_for_htmlbox(rotation)
    redact_rect = fitz.Rect(cluster_union if not cluster_union.is_empty else target.layout_rect)

    return EditTextResult.SUCCESS, _EditTextResolveResult(
        target_span=target_span,
        resolved_target_span_id=resolved_target_span_id,
        effective_target_mode=effective_target_mode,
        target_member_span_ids=target_member_span_ids,
        overlap_cluster=overlap_cluster,
        protected_spans=protected_spans,
        target=target,
        resolved_font=resolved_font,
        rotation=rotation,
        is_vertical=is_vertical,
        insert_rotate=insert_rotate,
        redact_rect=redact_rect,
        reopen_anchor_rect=fitz.Rect(reopen_anchor_rect) if reopen_anchor_rect is not None else None,
    )

def _apply_redact_insert(
    model: PDFModel,
    *,
    page: fitz.Page,
    page_num: int,
    page_idx: int,
    page_rect: fitz.Rect,
    new_text: str,
    size: float,
    color: tuple,
    vertical_shift_left: bool,
    new_rect: fitz.Rect | None,
    snapshot_bytes: bytes,
    resolve_result: _EditTextResolveResult,
) -> fitz.Rect:
    _saved_annots = model.tools.annotation._save_overlapping_annots(page, resolve_result.redact_rect)
    page.add_redact_annot(resolve_result.redact_rect)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    if _saved_annots:
        model.tools.annotation._restore_annots(page, _saved_annots)
    if resolve_result.protected_spans:
        model._replay_protected_spans(page, resolve_result.protected_spans)
    model.pending_edits.append({"page_idx": page_idx, "rect": fitz.Rect(resolve_result.redact_rect)})
    logger.debug(
        "overlap_redaction page=%s target_span_id=%s target_mode=%s cluster_size=%s protected_count=%s redact_rect=%s",
        page_num,
        resolve_result.resolved_target_span_id,
        resolve_result.effective_target_mode,
        len(resolve_result.overlap_cluster),
        len(resolve_result.protected_spans),
        resolve_result.redact_rect,
    )

    member_spans = [
        span for span in resolve_result.overlap_cluster
        if span.span_id in resolve_result.target_member_span_ids
    ]
    member_colors_distinct = {
        tuple(round(float(c), 3) for c in (s.color or (0.0, 0.0, 0.0)))
        for s in member_spans
    }
    request_color_rounded = tuple(
        round(float(c), 3) for c in (color or (0.0, 0.0, 0.0))
    )
    preserve_multi_style = (
        resolve_result.effective_target_mode == "paragraph"
        and len(member_colors_distinct) > 1
        and request_color_rounded in member_colors_distinct
    )

    if preserve_multi_style:
        html_content = model._build_multi_style_html(
            new_text,
            member_spans,
            default_color=color,
            latin_font=resolve_result.resolved_font,
        )
        logger.debug(
            "multi-style paragraph preserve: page=%s members=%s distinct_colors=%s",
            page_num,
            len(member_spans),
            len(member_colors_distinct),
        )
    else:
        html_content = model._convert_text_to_html(
            new_text, size, color, latin_font=resolve_result.resolved_font
        )
    # 行高保真：從 member_spans 推導原 PDF 的真實 leading。多行時取
    # 相鄰 baseline (origin.y) 推進的中位數；單行時取最大 bbox 高度。
    # 明確傳入 _build_insert_css，繞過自動 line-height 夾擠，避免
    # committed box 比原文字高/矮而推擠相鄰文字。
    _line_ht = 0.0
    if member_spans:
        origins_y = sorted({round(float(s.origin.y), 2) for s in member_spans})
        if len(origins_y) >= 2:
            advances = sorted(
                b - a for a, b in zip(origins_y, origins_y[1:]) if (b - a) > 0.5
            )
            if advances:
                _line_ht = advances[len(advances) // 2]
        if _line_ht <= 0.0:
            _line_ht = max(
                float(s.bbox.y1) - float(s.bbox.y0) for s in member_spans
            )
    css = model._build_insert_css(
        size, color, resolve_result.resolved_font, line_height=_line_ht
    )

    if new_rect is not None:
        clamped_new = fitz.Rect(
            max(float(new_rect.x0), page_rect.x0),
            max(float(new_rect.y0), page_rect.y0),
            min(float(new_rect.x1), page_rect.x1 - 5),
            min(float(new_rect.y1), page_rect.y1 - 5),
        )
        if clamped_new.is_empty or clamped_new.is_infinite or clamped_new.width < 5:
            logger.warning("new_rect %s clamped 後為空，退回原位插入", new_rect)
            clamped_new = fitz.Rect(resolve_result.target.layout_rect)
        base_layout = clamped_new
    else:
        base_layout = fitz.Rect(
            resolve_result.reopen_anchor_rect
            if resolve_result.reopen_anchor_rect is not None
            else resolve_result.target.layout_rect
        )

    # 快/慢路徑分類，預覽（view.PreviewRenderer）與 commit（此處）共用
    # 同一 _classify_insert_path，確保開啟編輯框與最終 PDF 用同一渲染器。
    needs_cjk = model._needs_cjk_font(new_text)
    fast_margin = 15
    fast_right_margin_pt = max(60.0, min(120.0, float(size) * 2.0))
    fast_right_safe = page_rect.x1 - fast_right_margin_pt
    fast_available_w = max(
        0.0,
        fast_right_safe - max(float(base_layout.x0), page_rect.x0) - fast_margin,
    )
    fast_insert_font = model._resolve_font_for_push(resolve_result.resolved_font)
    try:
        _fast_font_obj = fitz.Font(fast_insert_font)
        fast_text_width = _fast_font_obj.text_length(new_text, fontsize=size)
    except Exception:
        fast_insert_font = "helv"
        fast_text_width = fitz.Font(fast_insert_font).text_length(
            new_text, fontsize=size
        )

    insert_path = _classify_insert_path(
        new_text=new_text,
        member_spans=member_spans,
        rotation=int(resolve_result.rotation),
        is_vertical=bool(resolve_result.is_vertical),
        preserve_multi_style=preserve_multi_style,
        has_new_rect=new_rect is not None,
        needs_cjk=needs_cjk,
        text_width=fast_text_width,
        available_width=fast_available_w,
        size=size,
    )

    if insert_path == "fast":
        origin_span = min(
            member_spans,
            key=lambda span: (float(span.origin.x), float(span.origin.y)),
        )
        origin = fitz.Point(
            float(origin_span.origin.x),
            float(origin_span.origin.y),
        )
        page.insert_text(
            origin,
            new_text,
            fontname=fast_insert_font,
            fontsize=float(size),
            color=tuple(float(c) for c in color),
            rotate=0,
        )
        original_bbox = rect_union([fitz.Rect(span.bbox) for span in member_spans])
        return fitz.Rect(
            original_bbox.x0,
            original_bbox.y0,
            min(original_bbox.x0 + fast_text_width, page_rect.x1 - 10),
            original_bbox.y1,
        )

    if resolve_result.is_vertical:
        if new_rect is not None:
            base_y1 = float(base_layout.y1)
            insert_rect = fitz.Rect(
                base_layout.x0, base_layout.y0, base_layout.x1, page_rect.y1
            )
        else:
            base_rect = model._vertical_html_rect(
                resolve_result.target.layout_rect, new_text, size, resolve_result.resolved_font,
                page_rect, anchor_right=vertical_shift_left
            )
            base_y1 = base_rect.y1
            insert_rect = fitz.Rect(
                base_rect.x0, base_rect.y0, base_rect.x1, page_rect.y1
            )
    else:
        margin = 15
        right_margin_pt = max(60.0, min(120.0, float(size) * 2.0))
        right_safe = page_rect.x1 - right_margin_pt
        x0 = max(float(base_layout.x0), page_rect.x0)
        if new_rect is not None:
            x1 = min(float(base_layout.x1), page_rect.x1 - 10)
        else:
            max_w = max(0, min(
                page_rect.width - margin,
                right_safe - x0 - margin
            ))
            x1 = min(x0 + max(resolve_result.target.layout_rect.width, max_w), right_safe)
        y0 = max(float(base_layout.y0), page_rect.y0)
        # 不再用 line_count×size×2 + size×2 的過度保守地板，改信任實際
        # 文字框高度，避免單行編輯被誤判為溢出而推擠下方未編輯文字。
        base_y1 = y0 + float(base_layout.height)
        insert_rect = fitz.Rect(x0, y0, x1, page_rect.y1)

    insert_rect = clamp_rect_to_page(insert_rect, page_rect)

    skip_prepush = resolve_result.effective_target_mode == "paragraph" and new_rect is not None
    if not resolve_result.is_vertical and not skip_prepush:
        try:
            _probe_doc = fitz.open()
            _probe_page = _probe_doc.new_page(
                width=page_rect.width, height=page_rect.height
            )
            _probe_spare, _ = _probe_page.insert_htmlbox(
                insert_rect, html_content, css=css,
                rotate=0, scale_low=1,
            )
            _probe_doc.close()
            # insert_htmlbox 固定多吃約 2pt leading；扣除後 probe 才能
            # 反映真實文字高度，否則單行編輯會被誤判為溢出觸發 push-down。
            _MUPDF_HTMLBOX_LEADING_OVERHEAD = 2.0
            _probe_used_h = max(
                0.0, insert_rect.height - _probe_spare - _MUPDF_HTMLBOX_LEADING_OVERHEAD
            )
            _probe_y1 = insert_rect.y0 + _probe_used_h
            _probe_y1 = float(min(max(_probe_y1, base_y1), page_rect.y1))
            height_growth = _probe_y1 - resolve_result.redact_rect.y1
            meaningful_growth = max(0.5, float(size) * 0.2)
            if height_growth > meaningful_growth:
                logger.debug(
                    "換行預估溢出 %.1fpt，預先推移下方文字塊（pre-push）",
                    height_growth,
                )
                model._push_down_overlapping_text(
                    page, page_rect,
                    above_y=resolve_result.redact_rect.y1,
                    new_bottom=_probe_y1,
                    edit_x0=x0,
                    edit_x1=x1,
                )
            else:
                logger.debug(
                    "Pre-push probe skipped: growth %.2fpt <= threshold %.2fpt",
                    height_growth,
                    meaningful_growth,
                )
        except Exception as _probe_err:
            logger.debug("Pre-push probe 失敗（忽略）: %s", _probe_err)
    elif skip_prepush:
        logger.debug("Pre-push probe skipped (paragraph mode with dragged new_rect)")

    if resolve_result.is_vertical:
        try:
            _shrink_doc = fitz.open()
            _shrink_page = _shrink_doc.new_page(
                width=page_rect.width, height=page_rect.height
            )
            _shrink_page.insert_htmlbox(
                insert_rect, html_content, css=css,
                rotate=resolve_result.insert_rotate, scale_low=1
            )
            padding = model._calc_vertical_padding(size)
            shrunk_rect = model._binary_shrink_height(
                _shrink_page, insert_rect, new_text,
                iterations=7, padding=padding, min_y1=base_y1
            )
            _shrink_doc.close()
        except Exception as _shrink_err:
            logger.debug("垂直 binary_shrink 失敗，回退 insert_rect: %s", _shrink_err)
            shrunk_rect = fitz.Rect(insert_rect)
        shrunk_rect = clamp_rect_to_page(shrunk_rect, page_rect)
        spare_height, scale_used = page.insert_htmlbox(
            shrunk_rect, html_content, css=css,
            rotate=resolve_result.insert_rotate, scale_low=1
        )
        if spare_height < 0:
            page.insert_htmlbox(
                shrunk_rect, html_content, css=css,
                rotate=resolve_result.insert_rotate, scale_low=0
            )
        new_layout_rect = fitz.Rect(shrunk_rect)
        logger.debug(
            "垂直策略（臨時頁量測）: spare_height=%s, shrunk_rect=%s",
            spare_height,
            shrunk_rect,
        )
        return new_layout_rect

    spare_height, scale_used = page.insert_htmlbox(
        insert_rect, html_content, css=css,
        rotate=resolve_result.insert_rotate, scale_low=1
    )
    new_layout_rect = fitz.Rect(insert_rect)
    logger.debug("策略 A: spare_height=%s, scale=%s", spare_height, scale_used)

    if spare_height < 0:
        logger.debug("策略 A 失敗，嘗試策略 B（自動擴寬）")
        try:
            font_for_measure = (
                "china-ts" if model._needs_cjk_font(new_text) else resolve_result.resolved_font
            )
            try:
                font_obj = fitz.Font(font_for_measure)
            except Exception:
                font_for_measure = "helv"
                font_obj = fitz.Font(font_for_measure)
            text_width = font_obj.text_length(
                new_text.replace('\n', ''), fontsize=size
            )
            expanded_width = max(
                insert_rect.width, text_width * 1.15 + size
            )
            expanded_rect = fitz.Rect(
                insert_rect.x0, insert_rect.y0,
                min(insert_rect.x0 + expanded_width,
                    page_rect.x1 - 10),
                insert_rect.y1
            )
            expanded_rect = clamp_rect_to_page(
                expanded_rect, page_rect
            )
            spare_height, scale_used = page.insert_htmlbox(
                expanded_rect, html_content, css=css,
                rotate=resolve_result.insert_rotate, scale_low=1
            )
            new_layout_rect = fitz.Rect(expanded_rect)
            logger.debug(
                "策略 B: spare_height=%s, scale=%s",
                spare_height,
                scale_used,
            )
        except Exception as ex_b:
            logger.debug("策略 B 失敗: %s", ex_b)

    if spare_height < 0:
        spare_height, scale_used = page.insert_htmlbox(
            new_layout_rect, html_content, css=css,
            rotate=resolve_result.insert_rotate, scale_low=0.5
        )
        if spare_height < 0:
            model._restore_page_from_snapshot(page_idx, snapshot_bytes)
            model.block_manager.rebuild_page(page_idx, model.doc)
            raise RuntimeError(
                f"文字框內容在字級 {size}pt 下無法完整塞入 "
                f"(spare_height={spare_height})，"
                "策略 A/B/C 均失敗，已回滾。"
            )
        logger.debug(
            "策略 C（水平, scale_low=0.5）: spare_height=%s, scale=%s",
            spare_height,
            scale_used,
        )

    text_used_height = new_layout_rect.height - spare_height
    computed_y1 = new_layout_rect.y0 + text_used_height
    computed_y1 = max(computed_y1, base_y1)
    shrunk_rect = fitz.Rect(
        new_layout_rect.x0, new_layout_rect.y0,
        new_layout_rect.x1, computed_y1
    )
    shrunk_rect = clamp_rect_to_page(shrunk_rect, page_rect)
    if resolve_result.reopen_anchor_rect is not None:
        # Pin the committed layout back to the anchor so the box geometry
        # is identical to the previous open — no per-commit shrink.
        return clamp_rect_to_page(fitz.Rect(resolve_result.reopen_anchor_rect), page_rect)
    return fitz.Rect(shrunk_rect)

def _verify_rebuild_edit(
    model: PDFModel,
    *,
    page: fitz.Page,
    page_num: int,
    page_idx: int,
    page_rect: fitz.Rect,
    new_text: str,
    size: float,
    color: tuple,
    snapshot_bytes: bytes,
    resolve_result: _EditTextResolveResult,
    new_layout_rect: fitz.Rect,
) -> None:
    full_page_text = page.get_text("text")
    norm_new = normalize_text(new_text)
    norm_page = normalize_text(full_page_text)

    if norm_new and norm_new in norm_page:
        sim_ratio = 1.0
    elif norm_new and norm_page:
        sim_ratio = difflib.SequenceMatcher(
            None, norm_new, norm_page
        ).ratio()
    else:
        sim_ratio = 1.0 if not norm_new else 0.0

    logger.debug(
        "Step4 驗證: ratio=%.2f, layout_rect=%s, norm_new[:%s]=%r",
        sim_ratio,
        new_layout_rect,
        min(40, len(norm_new)),
        norm_new[:40],
    )

    norm_clip = ""
    clip_ratio = 0.0
    clip_token_coverage = 0.0
    if not new_layout_rect.is_empty:
        try:
            clipped = page.get_text("text", clip=clamp_rect_to_page(new_layout_rect, page_rect))
            norm_clip = normalize_text(clipped)
            if norm_new and norm_clip:
                if norm_new in norm_clip:
                    clip_ratio = 1.0
                else:
                    clip_ratio = difflib.SequenceMatcher(None, norm_new, norm_clip).ratio()
                clip_token_coverage = token_coverage_ratio(new_text, norm_clip)
        except Exception as e_clip:
            logger.debug("Step4 clip probe failed: %s", e_clip)

    page_token_coverage = token_coverage_ratio(new_text, norm_page)
    exact_present = (norm_new in norm_page) or (bool(norm_clip) and norm_new in norm_clip)
    has_complex_script = model._has_complex_script(new_text)
    if not norm_new or exact_present:
        target_present = True
    elif resolve_result.effective_target_mode == "paragraph":
        if has_complex_script:
            target_present = (
                sim_ratio >= 0.40
                or clip_ratio >= 0.38
                or page_token_coverage >= 0.35
                or clip_token_coverage >= 0.35
            )
        else:
            target_present = (
                sim_ratio >= 0.88
                or clip_ratio >= 0.84
                or page_token_coverage >= 0.78
                or clip_token_coverage >= 0.72
            )
    elif len(norm_new) >= 48:
        target_present = (
            sim_ratio >= 0.90
            or clip_ratio >= 0.86
            or page_token_coverage >= 0.85
        )
    else:
        target_present = False

    logger.debug(
        "target_presence page=%s mode=%s exact=%s sim_ratio=%.2f clip_ratio=%.2f token_page=%.2f token_clip=%.2f",
        page_num,
        resolve_result.effective_target_mode,
        exact_present,
        sim_ratio,
        clip_ratio,
        page_token_coverage,
        clip_token_coverage,
    )
    protected_ok = model._validate_protected_spans(page, resolve_result.protected_spans)
    if not target_present or not protected_ok:
        model._restore_page_from_snapshot(page_idx, snapshot_bytes)
        model.block_manager.rebuild_page(page_idx, model.doc)
        raise RuntimeError(
            "overlap edit verification failed: "
            f"target_present={target_present}, protected_ok={protected_ok}"
        )

    strict_ratio = max(sim_ratio, clip_ratio)
    if resolve_result.effective_target_mode != "paragraph" and strict_ratio < 0.80 and not resolve_result.is_vertical:
        logger.warning(
            "插入後驗證失敗 (ratio=%.2f)，正在回滾頁面 %s",
            strict_ratio,
            page_num,
        )
        model._restore_page_from_snapshot(page_idx, snapshot_bytes)
        model.block_manager.rebuild_page(page_idx, model.doc)
        raise RuntimeError(
            f"文字編輯驗證失敗：difflib.ratio="
            f"{strict_ratio:.2f} < 0.80，已回滾。"
        )

    update_kwargs = dict(
        text=new_text,
        font=resolve_result.resolved_font,
        size=float(size),
        color=color,
    )
    if not resolve_result.is_vertical:
        update_kwargs["layout_rect"] = new_layout_rect
    model.block_manager.update_block(resolve_result.target, **update_kwargs)
    model.block_manager.rebuild_page(page_idx, model.doc)
    if resolve_result.reopen_anchor_rect is not None:
        # rebuild_page reassigns span_ids; migrate the anchor onto the
        # rebuilt run that best matches by (text-match, distance-to-anchor
        # -center) so the next reopen still resolves to it, and drop the
        # stale key so the anchor dict can't grow unboundedly.
        anchor_rect = fitz.Rect(resolve_result.reopen_anchor_rect)
        anchor_size = model._get_run_reopen_anchor_size(
            page_idx, resolve_result.resolved_target_span_id
        )
        if anchor_size is None:
            anchor_size = float(size)
        model._set_run_reopen_anchor_rect(
            page_idx, resolve_result.resolved_target_span_id, anchor_rect
        )
        model._set_run_reopen_anchor_size(
            page_idx, resolve_result.resolved_target_span_id, anchor_size
        )
        try:
            rebuilt_runs = model.block_manager.get_runs(page_idx)
            if rebuilt_runs:
                norm_new = normalize_text(new_text or "")
                anchor_cx = float(anchor_rect.x0 + (anchor_rect.width / 2.0))
                anchor_cy = float(anchor_rect.y0 + (anchor_rect.height / 2.0))

                def _run_anchor_score(span: EditableSpan) -> tuple[int, float]:
                    span_rect = fitz.Rect(span.bbox)
                    span_cx = float(span_rect.x0 + (span_rect.width / 2.0))
                    span_cy = float(span_rect.y0 + (span_rect.height / 2.0))
                    distance_sq = ((span_cx - anchor_cx) ** 2) + ((span_cy - anchor_cy) ** 2)
                    text_match_penalty = 0
                    if norm_new:
                        text_match_penalty = 0 if normalize_text(span.text) == norm_new else 1
                    return (text_match_penalty, distance_sq)

                best_run = min(rebuilt_runs, key=_run_anchor_score)
                if best_run.span_id != resolve_result.resolved_target_span_id:
                    model._delete_run_reopen_anchor(
                        page_idx, resolve_result.resolved_target_span_id
                    )
                model._set_run_reopen_anchor_rect(page_idx, best_run.span_id, anchor_rect)
                model._set_run_reopen_anchor_size(page_idx, best_run.span_id, anchor_size)
        except Exception as anchor_exc:
            logger.debug("run anchor refresh skipped after rebuild: %s", anchor_exc)
    logger.debug(
        "編輯文字成功: 頁面 %s, block_id=%s, text='%s...'",
        page_num,
        resolve_result.target.block_id,
        new_text[:30],
    )

# ──────────────────────────────────────────────────────────────────────────
# Phase 3: 五步流程 + 三策略 edit_text
# ──────────────────────────────────────────────────────────────────────────

def _resolve_effective_target_mode(
    model: PDFModel,
    *,
    target_mode: str | None,
    target_span_id: str | None,
    new_rect: fitz.Rect | None,
    page_idx: int,
    rect: fitz.Rect,
    original_text: str | None,
) -> str:
    """Determine effective target mode from caller hints and heuristics."""
    if target_mode is None:
        if new_rect is not None and not target_span_id:
            effective = "paragraph"
        elif target_span_id:
            effective = "run"
        else:
            effective = "paragraph"
    else:
        effective = (target_mode or model.text_target_mode or "run").strip().lower()
    if effective not in {"run", "paragraph"}:
        effective = "run"
    if effective == "run" and not target_span_id:
        should_promote = True
        if original_text:
            probe_block = model.block_manager.find_by_rect(
                page_idx, rect, original_text=original_text, doc=model.doc
            )
            if probe_block and probe_block.text:
                norm_orig = normalize_text(original_text)
                norm_block = normalize_text(probe_block.text)
                if norm_block and len(norm_orig) < len(norm_block) * 0.6:
                    should_promote = False
                    logger.debug(
                        "keeping run mode: original_text (%d chars) < 60%% of block text (%d chars)",
                        len(norm_orig), len(norm_block),
                    )
        if should_promote:
            effective = "paragraph"
            logger.warning("auto-promoted target_mode run->paragraph (no explicit span_id)")
    return effective

def edit_text(model: PDFModel, page_num: int, rect: fitz.Rect, new_text: str,
              font: str = "helv", size: float = 12.0,
              color: tuple = (0.0, 0.0, 0.0),
              original_text: str = None,
              vertical_shift_left: bool = True,
              new_rect: fitz.Rect = None,
              target_span_id: str | None = None,
              target_mode: str | None = None) -> EditTextResult:
    """
    編輯文字：五步流程 + 三策略智能插入。

    流程：
      1. 驗證：從 TextBlockManager 取出 TextBlock，比對原文字
      2. 安全 Redaction：只清除目標 block 的 layout_rect
      3. 智能插入：策略 A (htmlbox) → B (auto-expand) → C (fallback)
      4. 驗證與回滾：difflib.ratio > 0.92，否則 page-level snapshot 回滾
      5. 更新索引：block_manager.update_block()

    Args:
        page_num: 頁碼（1-based）
        rect: 使用者選取的粗略矩形
        new_text: 新文字內容
        font: 字體名稱
        size: 字體大小
        color: 文字顏色 (0-1 float tuple)
        original_text: 原始文字內容（可選，用於精確定位）
        vertical_shift_left: 垂直文字擴展方向（True=左移，False=右移）
    """
    # Keep empty text as a valid edit: redact target text and reinsert nothing.
    if new_text is None:
        new_text = ""

    _t0 = time.perf_counter()  # Phase 6: 效能計時
    page_idx = page_num - 1
    model.ensure_page_index_built(page_num)
    page = model.doc[page_idx]
    page_rect = page.rect
    rollback_flag = False
    resolved_target_span_id = target_span_id
    effective_target_mode = model._resolve_effective_target_mode(
        target_mode=target_mode,
        target_span_id=target_span_id,
        new_rect=new_rect,
        page_idx=page_idx,
        rect=rect,
        original_text=original_text,
    )
    resolve_result: _EditTextResolveResult | None = None

    # ── Step 0: 擷取 page-level 快照，供回滾使用 ──
    snapshot_bytes = model._capture_page_snapshot(page_idx)

    try:
        resolve_status, resolve_result = model._resolve_edit_target(
            page_num=page_num,
            page_idx=page_idx,
            page=page,
            rect=rect,
            new_text=new_text,
            font=font,
            size=size,
            color=color,
            original_text=original_text,
            new_rect=new_rect,
            resolved_target_span_id=resolved_target_span_id,
            effective_target_mode=effective_target_mode,
        )
        if resolve_status is not EditTextResult.SUCCESS:
            return resolve_status

        resolved_target_span_id = resolve_result.resolved_target_span_id
        effective_target_mode = resolve_result.effective_target_mode

        new_layout_rect = model._apply_redact_insert(
            page=page,
            page_num=page_num,
            page_idx=page_idx,
            page_rect=page_rect,
            new_text=new_text,
            size=size,
            color=color,
            vertical_shift_left=vertical_shift_left,
            new_rect=new_rect,
            snapshot_bytes=snapshot_bytes,
            resolve_result=resolve_result,
        )

        model._verify_rebuild_edit(
            page=page,
            page_num=page_num,
            page_idx=page_idx,
            page_rect=page_rect,
            new_text=new_text,
            size=size,
            color=color,
            snapshot_bytes=snapshot_bytes,
            resolve_result=resolve_result,
            new_layout_rect=new_layout_rect,
        )

        # ── Phase 6: GC + 效能計時 ──
        model.edit_count += 1
        model._maybe_garbage_collect()

        _duration = time.perf_counter() - _t0
        logger.debug(
            "edit_transaction page=%s target_span_id=%s target_mode=%s cluster_size=%s protected_count=%s rollback_flag=%s duration_ms=%s",
            page_num,
            resolved_target_span_id,
            effective_target_mode,
            len(resolve_result.overlap_cluster),
            len(resolve_result.protected_spans),
            rollback_flag,
            round(_duration * 1000, 2),
        )
        if _duration > 0.3:
            logger.warning("單次編輯過慢：%.3fs，頁面 %s", _duration, page_num)
        return EditTextResult.SUCCESS

    except RuntimeError:
        rollback_flag = True
        _duration = time.perf_counter() - _t0
        logger.debug(
            "edit_transaction page=%s target_span_id=%s target_mode=%s cluster_size=%s protected_count=%s rollback_flag=%s duration_ms=%s",
            page_num,
            resolved_target_span_id,
            effective_target_mode,
            len(resolve_result.overlap_cluster) if resolve_result else 0,
            len(resolve_result.protected_spans) if resolve_result else 0,
            rollback_flag,
            round(_duration * 1000, 2),
        )
        raise
    except Exception as e:
        logger.error(f"編輯文字時發生非預期錯誤: {e}")
        rollback_error: Exception | None = None
        try:
            rollback_flag = True
            model._restore_page_from_snapshot(page_idx, snapshot_bytes)
            model.block_manager.rebuild_page(page_idx, model.doc)
        except Exception as rollback_err:
            rollback_error = rollback_err
            logger.error(
                "編輯文字回滾失敗: page=%s original_error=%s rollback_error=%s",
                page_num,
                e,
                rollback_err,
            )
        _duration = time.perf_counter() - _t0
        logger.debug(
            "edit_transaction page=%s target_span_id=%s target_mode=%s cluster_size=%s protected_count=%s rollback_flag=%s duration_ms=%s",
            page_num,
            resolved_target_span_id,
            effective_target_mode,
            len(resolve_result.overlap_cluster) if resolve_result else 0,
            len(resolve_result.protected_spans) if resolve_result else 0,
            rollback_flag,
            round(_duration * 1000, 2),
        )
        if rollback_error is not None:
            raise RuntimeError(
                f"編輯文字失敗且回滾失敗: {e}; rollback: {rollback_error}"
            ) from rollback_error
        raise RuntimeError(f"編輯文字失敗: {e}") from e

    # Phase 4: undo/redo 已由 CommandManager (EditTextCommand) 全權負責，
    #          此處不再呼叫 _save_state()，避免雙重儲存浪費 I/O。

# _save_state() 已於 Phase 6 移除，所有 undo/redo 由 CommandManager 統一管理。

