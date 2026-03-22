"""
unified_command.py — UnifiedObjectCommand 類別

統一封裝 reflow + 物件操作的 EditCommand 子類，
供 pdf_controller.py 使用。

支援的操作類型：
  1. text_reflow     — 文字編輯 + 後續塊自動位移
  2. object_color    — 矩形/形狀 顏色變更
  3. object_opacity  — 矩形/形狀 透明度變更
  4. object_fill     — 矩形/形狀 填滿切換
  5. textbox_rotate  — 文字框旋轉
  6. object_move     — 物件拖曳移動（含 reflow）

整合點：
  - 繼承 model.edit_commands.EditCommand
  - 使用 page-level snapshot 做 undo/redo
  - 使用 TrackAEngine / TrackBEngine 做 reflow
  - 使用 capture_viewport_anchor / restore_viewport_anchor 做視窗鎖定
"""

import io
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

import fitz

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

# 延遲 import 以避免循環依賴
from model.edit_commands import EditCommand

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 模組級便利函數
# ──────────────────────────────────────────────────────────────────────────────

def apply_object_edit(
    page: fitz.Page,
    object_info: dict,
    changes,
    track: str = "auto",
) -> dict:
    """
    模組級便利函數：直接對 fitz.Page 套用物件編輯，不需建立 command。

    適合在 pdf_controller 或 tool 中快速呼叫，無 undo/redo 支援。
    若需要 undo/redo，請使用 UnifiedObjectCommand。

    參數：
      page        fitz.Page        目標頁面（就地修改）
      object_info dict             {original_rect, font, size, color,
                                    original_text, page_rotation}
      changes     ObjectChanges | dict  {new_text, color, opacity, fill,
                                         rotation_angle, reflow_enabled, ...}
      track       "A" | "B" | "auto"  引擎選擇（auto: 先試 B，失敗回退 A）

    回傳：
      dict: {"success": bool, "track": str, "warnings": list,
             "interference_count": int, "elapsed_ms": float}
    """
    t0 = time.perf_counter()

    from reflow.track_A_core import TrackAEngine
    from reflow.track_B_core import TrackBEngine

    result: dict = {"success": False, "track": track, "warnings": [],
                    "interference_count": 0, "elapsed_ms": 0.0}

    if track == "B":
        engine_b = TrackBEngine()
        result = engine_b.apply_object_edit(page, object_info, changes)

    elif track == "A":
        engine_a = TrackAEngine()
        result = engine_a.apply_object_edit(page, object_info, changes)

    else:  # auto：先試 Track B，失敗則回退 Track A
        engine_b = TrackBEngine()
        result = engine_b.apply_object_edit(page, object_info, changes)
        if not result.get("success", False):
            logger.info("apply_object_edit: Track B 失敗，回退到 Track A")
            engine_a = TrackAEngine()
            result_a = engine_a.apply_object_edit(page, object_info, changes)
            result_a["warnings"] = (
                [f"[Track B fallback] {w}" for w in result.get("warnings", [])]
                + result_a.get("warnings", [])
            )
            result = result_a

    result["elapsed_ms"] = (time.perf_counter() - t0) * 1000
    return result


# ──────────────────────────────────────────────────────────────────────────────
# 操作參數資料結構
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ObjectChanges:
    """
    統一的物件操作參數。

    使用方式：只填需要變更的欄位，其餘留 None。
    """
    # 文字 reflow 參數
    new_text: Optional[str] = None
    original_text: Optional[str] = None
    font: Optional[str] = None
    size: Optional[float] = None
    color: Optional[tuple] = None           # (r, g, b)，0.0~1.0
    reflow_enabled: bool = True             # 是否啟用後續塊 reflow

    # 物件屬性參數
    new_color: Optional[tuple] = None       # 形狀新顏色 (r, g, b)
    new_opacity: Optional[float] = None     # 透明度 0.0~1.0
    new_fill: Optional[bool] = None         # 是否填滿
    new_fill_color: Optional[tuple] = None  # 填滿顏色 (r, g, b)

    # 旋轉參數
    rotation_angle: Optional[float] = None  # 旋轉角度（度）

    # 移動參數
    new_rect: Optional[Any] = None          # 新位置 fitz.Rect

    # 進階參數
    target_span_id: Optional[str] = None    # 精準 span 定位
    target_mode: Optional[str] = None       # "run" | "paragraph"
    vertical_shift_left: bool = True        # 垂直文字左移
    track_preference: str = "auto"          # "A" | "B" | "auto"


# ──────────────────────────────────────────────────────────────────────────────
# UnifiedObjectCommand
# ──────────────────────────────────────────────────────────────────────────────

class UnifiedObjectCommand(EditCommand):
    """
    統一物件操作指令：封裝 reflow + 物件屬性變更，支援 undo/redo。

    undo 策略：
      - page-level snapshot（與 EditTextCommand 一致）
      - 在 execute 前擷取快照，undo 時還原

    整合至 pdf_controller.py：
      snapshot = model._capture_page_snapshot(page_idx)
      cmd = UnifiedObjectCommand(
          model=model,
          page_num=page,                # 1-based
          target_rect=edited_rect,
          changes=ObjectChanges(new_text="...", reflow_enabled=True),
          page_snapshot_bytes=snapshot,
      )
      model.command_manager.execute(cmd)
    """

    def __init__(
        self,
        model: Any,                      # PDFModel
        page_num: int,                   # 1-based（與 pdf_model API 一致）
        target_rect: fitz.Rect,          # 目標物件的 visual rect
        changes: ObjectChanges,          # 要套用的變更
        page_snapshot_bytes: bytes,      # execute 前的頁面快照
        operation_type: str = "auto",    # 操作類型（auto = 自動推斷）
        captured_anchor: Any = None,     # ViewportAnchor：execute 前由 view 擷取
    ):
        self._model = model
        self._page_num = page_num
        self._target_rect = fitz.Rect(target_rect)
        self._changes = changes
        self._page_snapshot_bytes = page_snapshot_bytes
        self._operation_type = self._infer_operation_type(operation_type, changes)
        self._executed = False
        # viewport anchor：controller 在 _refresh_after_command 後呼叫
        # view.restore_viewport_anchor(cmd.captured_anchor) 恢復捲軸位置
        self.captured_anchor = captured_anchor

    @property
    def description(self) -> str:
        op_desc = {
            "text_reflow":    "文字 Reflow 編輯",
            "object_color":   "物件顏色變更",
            "object_opacity": "物件透明度變更",
            "object_fill":    "物件填滿切換",
            "textbox_rotate": "文字框旋轉",
            "object_move":    "物件移動",
        }
        desc = op_desc.get(self._operation_type, "統一物件操作")
        return f"{desc}（頁面 {self._page_num}）"

    # ── execute ──────────────────────────────────────────────────────────

    def execute(self) -> None:
        """
        執行統一物件操作。

        根據 operation_type 分派到對應的處理邏輯。
        """
        page_idx = self._page_num - 1

        try:
            if self._operation_type == "text_reflow":
                self._execute_text_reflow(page_idx)

            elif self._operation_type == "object_color":
                self._execute_object_color(page_idx)

            elif self._operation_type == "object_opacity":
                self._execute_object_opacity(page_idx)

            elif self._operation_type == "object_fill":
                self._execute_object_fill(page_idx)

            elif self._operation_type == "textbox_rotate":
                self._execute_textbox_rotate(page_idx)

            elif self._operation_type == "object_move":
                self._execute_object_move(page_idx)

            else:
                logger.warning(
                    f"UnifiedObjectCommand: 未知操作類型 {self._operation_type}"
                )

            self._executed = True
            logger.debug(f"UnifiedObjectCommand.execute(): {self.description}")

        except Exception as e:
            logger.error(
                f"UnifiedObjectCommand.execute() 失敗: {e}", exc_info=True
            )
            raise

    # ── undo ─────────────────────────────────────────────────────────────

    def undo(self) -> None:
        """
        還原頁面至 execute() 前的狀態。
        使用 page-level snapshot 還原。

        整合至 pdf_controller._refresh_after_command() 的 viewport 恢復：
        ─────────────────────────────────────────────────────────────────
        # 在 _refresh_after_command 末尾加入：
        if hasattr(cmd, 'captured_anchor') and cmd.captured_anchor is not None:
            QTimer.singleShot(0, lambda a=cmd.captured_anchor:
                self.view.restore_viewport_anchor(a))
            QTimer.singleShot(180, lambda a=cmd.captured_anchor:
                self.view.restore_viewport_anchor(a))

        整合至 pdf_view._finalize_text_edit_impl() 的 anchor 擷取：
        ─────────────────────────────────────────────────────────────────
        # 在 sig_edit_text.emit() 之前加入：
        viewport_anchor = self.capture_viewport_anchor()
        # 並將 viewport_anchor 傳遞給 controller，由 controller 建立
        # UnifiedObjectCommand(... captured_anchor=viewport_anchor) 時使用。
        ─────────────────────────────────────────────────────────────────
        """
        if not self._executed:
            logger.warning("UnifiedObjectCommand.undo(): 尚未執行過，跳過")
            return

        page_idx = self._page_num - 1

        try:
            self._model._restore_page_from_snapshot(
                page_idx, self._page_snapshot_bytes
            )
            self._model.block_manager.rebuild_page(page_idx, self._model.doc)
            logger.debug(f"UnifiedObjectCommand.undo(): {self.description}")
        except Exception as e:
            logger.error(
                f"UnifiedObjectCommand.undo() 失敗: {e}", exc_info=True
            )
            raise

    # ── 操作分派：text_reflow ────────────────────────────────────────────

    def _execute_text_reflow(self, page_idx: int):
        """
        文字 reflow 操作（第 2 階段版本）：
          1. 用 model.edit_text() 處理基本文字替換（含 span 定位）
          2. 用 apply_object_edit 介面呼叫 Track A/B 引擎做後續塊 reflow
          3. 記錄 quad 干擾數量供 controller 判斷
        """
        changes = self._changes
        doc  = self._model.doc
        page = doc[page_idx]

        # Step 1: 基本文字替換（利用現有 model.edit_text，處理 span 定位）
        if changes.new_text is not None:
            self._model.edit_text(
                page_num=self._page_num,
                rect=self._target_rect,
                new_text=changes.new_text,
                font=changes.font or "helv",
                size=int(changes.size or 12),
                color=changes.color or (0, 0, 0),
                original_text=changes.original_text,
                vertical_shift_left=changes.vertical_shift_left,
                new_rect=fitz.Rect(changes.new_rect) if changes.new_rect else None,
                target_span_id=changes.target_span_id,
                target_mode=changes.target_mode,
            )

        # Step 2: Reflow（若啟用）—— 使用 apply_object_edit 統一介面
        if changes.reflow_enabled and changes.new_text is not None:
            object_info = {
                "original_rect":  self._target_rect,
                "font":           changes.font or "helv",
                "size":           changes.size or 12.0,
                "color":          changes.color or (0, 0, 0),
                "original_text":  changes.original_text or "",
                "page_rotation":  page.rotation,
            }
            ch_dict = {
                "new_text":       changes.new_text,
                "font":           changes.font,
                "size":           changes.size,
                "color":          changes.color,
                "reflow_enabled": changes.reflow_enabled,
            }
            result = apply_object_edit(
                page=page,
                object_info=object_info,
                changes=ch_dict,
                track=changes.track_preference,
            )

            if result.get("warnings"):
                for w in result["warnings"]:
                    logger.warning(f"[{result.get('track','?')}] Reflow warning: {w}")

            # 記錄干擾計數，供外部查詢
            self._last_reflow_interference = result.get("interference_count", 0)
            self._last_reflow_elapsed_ms   = result.get("elapsed_ms", 0.0)

            if not result.get("success", False):
                logger.error("UnifiedObjectCommand: reflow 失敗")

    @property
    def last_reflow_interference(self) -> int:
        """最後一次 reflow 的 quad 干擾數（0 = 無干擾）。"""
        return getattr(self, "_last_reflow_interference", 0)

    @property
    def last_reflow_elapsed_ms(self) -> float:
        """最後一次 reflow 的執行時間（ms）。"""
        return getattr(self, "_last_reflow_elapsed_ms", 0.0)

    # ── 操作分派：object_color ───────────────────────────────────────────

    def _execute_object_color(self, page_idx: int):
        """
        變更矩形/形狀的顏色。
        透過 annotation API 或 content stream 操作。
        """
        page = self._model.doc[page_idx]
        new_color = self._changes.new_color
        if new_color is None:
            return

        # 嘗試透過 annotation 找到目標
        target_annot = self._find_target_annotation(page, self._target_rect)
        if target_annot is not None:
            # 設定 stroke color
            target_annot.set_colors(stroke=new_color)
            if self._changes.new_fill_color is not None:
                target_annot.set_colors(fill=self._changes.new_fill_color)
            target_annot.update()
            logger.debug(f"物件顏色已更新: stroke={new_color}")
        else:
            logger.warning(
                f"找不到目標 annotation at {self._target_rect}，"
                f"嘗試 drawing-level 操作"
            )
            self._recolor_drawing(page, page_idx, new_color)

    # ── 操作分派：object_opacity ─────────────────────────────────────────

    def _execute_object_opacity(self, page_idx: int):
        """變更物件透明度。"""
        page = self._model.doc[page_idx]
        new_opacity = self._changes.new_opacity
        if new_opacity is None:
            return

        target_annot = self._find_target_annotation(page, self._target_rect)
        if target_annot is not None:
            target_annot.set_opacity(new_opacity)
            target_annot.update()
            logger.debug(f"物件透明度已更新: opacity={new_opacity}")
        else:
            logger.warning(f"找不到目標 annotation，無法變更透明度")

    # ── 操作分派：object_fill ────────────────────────────────────────────

    def _execute_object_fill(self, page_idx: int):
        """切換物件的填滿狀態。"""
        page = self._model.doc[page_idx]
        new_fill = self._changes.new_fill
        if new_fill is None:
            return

        target_annot = self._find_target_annotation(page, self._target_rect)
        if target_annot is not None:
            if new_fill:
                fill_color = self._changes.new_fill_color or (1, 1, 1)
                target_annot.set_colors(fill=fill_color)
            else:
                target_annot.set_colors(fill=None)
            target_annot.update()
            logger.debug(f"物件填滿已更新: fill={new_fill}")
        else:
            logger.warning(f"找不到目標 annotation，無法切換填滿")

    # ── 操作分派：textbox_rotate ─────────────────────────────────────────

    def _execute_textbox_rotate(self, page_idx: int):
        """
        旋轉文字框。

        策略：
          1. 提取原文字內容
          2. Redact 原文字
          3. 以旋轉角度 re-insert（透過 insert_htmlbox 的 rotate 參數）
        """
        page = self._model.doc[page_idx]
        angle = self._changes.rotation_angle
        if angle is None:
            return

        # 提取原文字
        target_rect = self._target_rect
        text_in_rect = page.get_text("text", clip=target_rect).strip()

        if not text_in_rect:
            logger.warning(f"旋轉區域內無文字: {target_rect}")
            return

        # 取得字體資訊
        font = self._changes.font or "helv"
        size = self._changes.size or 12.0
        color = self._changes.color or (0, 0, 0)

        # Redact 原文字
        page.add_redact_annot(target_rect)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        # 計算旋轉後的插入角度
        current_rotation = page.rotation
        insert_rotation = (current_rotation + int(angle)) % 360

        # Re-insert with rotation
        font_name = self._resolve_font(font)
        css = (
            f"* {{ font-family: {font_name}; font-size: {size}pt; "
            f"color: rgb({int(color[0]*255)},{int(color[1]*255)},{int(color[2]*255)}); }}"
        )
        page.insert_htmlbox(
            target_rect,
            text_in_rect,
            css=css,
            rotate=insert_rotation,
        )

        logger.debug(f"文字框已旋轉 {angle}° (insert_rotation={insert_rotation})")

    # ── 操作分派：object_move ────────────────────────────────────────────

    def _execute_object_move(self, page_idx: int):
        """
        移動物件到新位置（含 reflow）。
        結合文字移動 + 後續塊 reflow。
        """
        changes = self._changes
        if changes.new_rect is None:
            return

        new_rect = fitz.Rect(changes.new_rect)

        # 如果是文字物件，走 edit_text 路徑（帶 new_rect）
        if changes.new_text is not None or changes.original_text is not None:
            text = changes.new_text or changes.original_text or ""
            self._model.edit_text(
                page_num=self._page_num,
                rect=self._target_rect,
                new_text=text,
                font=changes.font or "helv",
                size=int(changes.size or 12),
                color=changes.color or (0, 0, 0),
                original_text=changes.original_text,
                vertical_shift_left=changes.vertical_shift_left,
                new_rect=new_rect,
                target_span_id=changes.target_span_id,
                target_mode=changes.target_mode,
            )
        else:
            # 非文字物件：嘗試透過 annotation 移動
            page = self._model.doc[page_idx]
            target_annot = self._find_target_annotation(page, self._target_rect)
            if target_annot is not None:
                target_annot.set_rect(new_rect)
                target_annot.update()
                logger.debug(f"物件已移動: {self._target_rect} → {new_rect}")
            else:
                logger.warning(f"找不到可移動的物件 at {self._target_rect}")

    # ── 輔助方法 ─────────────────────────────────────────────────────────

    def _infer_operation_type(self, op_type: str, changes: ObjectChanges) -> str:
        """根據 changes 內容自動推斷操作類型。"""
        if op_type != "auto":
            return op_type

        if changes.new_text is not None:
            if changes.new_rect is not None:
                return "object_move"
            return "text_reflow"

        if changes.rotation_angle is not None:
            return "textbox_rotate"

        if changes.new_color is not None:
            return "object_color"

        if changes.new_opacity is not None:
            return "object_opacity"

        if changes.new_fill is not None:
            return "object_fill"

        if changes.new_rect is not None:
            return "object_move"

        return "text_reflow"  # 預設

    def _find_target_annotation(
        self, page: fitz.Page, target_rect: fitz.Rect,
    ) -> Optional[fitz.Annot]:
        """找出頁面中與 target_rect 重疊最大的 annotation。"""
        best_annot = None
        best_overlap = 0.0

        for annot in page.annots():
            annot_rect = annot.rect
            intersection = annot_rect & target_rect
            if intersection.is_empty:
                continue
            area = intersection.width * intersection.height
            if area > best_overlap:
                best_overlap = area
                best_annot = annot

        return best_annot

    def _recolor_drawing(
        self, page: fitz.Page, page_idx: int, new_color: tuple,
    ):
        """
        變更 drawing-level 的顏色（非 annotation 的形狀）。
        使用 page.get_drawings() 找到目標形狀。
        """
        drawings = page.get_drawings()
        target = self._target_rect

        for d in drawings:
            d_rect = fitz.Rect(d["rect"])
            if d_rect.intersects(target):
                # 找到匹配的 drawing
                # PyMuPDF 的 drawings 是唯讀的，需要 redact + 重繪
                logger.info(
                    f"找到 drawing at {d_rect}，但 drawing-level recolor "
                    f"需要 redact+重繪，暫不實作"
                )
                break

    def _resolve_font(self, font: str) -> str:
        """字體名稱映射。"""
        font_map = {
            "helv": "helv",
            "helvetica": "helv",
            "times": "tiro",
            "courier": "cour",
            "cjk": "china-s",
        }
        return font_map.get(font.lower(), font)

    def _get_track_a(self):
        """延遲載入 Track A 引擎。"""
        from reflow.track_A_core import TrackAEngine
        return TrackAEngine()

    def _get_track_b(self):
        """延遲載入 Track B 引擎。"""
        from reflow.track_B_core import TrackBEngine
        return TrackBEngine()
