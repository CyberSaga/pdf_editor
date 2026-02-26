import fitz
import io
import logging
from abc import ABC, abstractmethod
from typing import Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    # 避免循環 import：只在型別檢查期間引入 PDFModel
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 抽象基類
# ──────────────────────────────────────────────────────────────────────────────

class EditCommand(ABC):
    """
    所有可撤銷編輯操作的抽象基類（Command Pattern）。

    子類必須實作 execute() 與 undo()。
    - execute()：首次執行，或 redo 時呼叫。
    - undo()   ：撤銷，還原至 execute() 前的狀態。

    CommandManager 使用此介面管理 undo/redo 堆疊，
    不需要知道具體操作的實作細節。
    """

    @abstractmethod
    def execute(self) -> None:
        """執行操作（首次或 redo）。"""
        ...

    @abstractmethod
    def undo(self) -> None:
        """撤銷操作，還原至 execute() 前的狀態。"""
        ...

    @property
    def description(self) -> str:
        """操作的人類可讀描述，供 UI 顯示（如「復原: 編輯文字『…』」）。預設回傳類別名。"""
        return self.__class__.__name__


# ──────────────────────────────────────────────────────────────────────────────
# EditTextCommand
# ──────────────────────────────────────────────────────────────────────────────

class EditTextCommand(EditCommand):
    """
    文字編輯指令：封裝單次 edit_text 操作的前後狀態，支援 undo/redo。

    undo 策略（page-level 快照）：
      - 以 page-level 快照（bytes）還原頁面，避免每次操作都儲存整份 PDF，
        顯著降低記憶體消耗與 I/O 開銷。
      - 快照應在 CommandManager.execute() 呼叫 cmd.execute() 之前由外部擷取，
        並在建構本物件時傳入 page_snapshot_bytes。
      - undo() 後需重建該頁 TextBlock 索引，確保後續查詢正確。

    Phase 3 整合說明：
      model 需實作以下兩個 helper 方法（Phase 3 加入 pdf_model.py）：
        def _capture_page_snapshot(self, page_num_0based: int) -> bytes:
            \"\"\"擷取指定頁面的 bytes 快照（供 EditTextCommand 建構時傳入）。\"\"\"
            tmp_doc = fitz.open()
            tmp_doc.insert_pdf(self.doc, from_page=page_num_0based, to_page=page_num_0based)
            stream = io.BytesIO()
            tmp_doc.save(stream, garbage=0)
            data = stream.getvalue()
            tmp_doc.close()
            return data

        def _restore_page_from_snapshot(self, page_num_0based: int, snapshot_bytes: bytes) -> None:
            \"\"\"用 bytes 快照替換 doc 中指定頁面（undo 時呼叫）。\"\"\"
            snapshot_doc = fitz.open("pdf", snapshot_bytes)
            self.doc.delete_page(page_num_0based)
            self.doc.insert_pdf(snapshot_doc, from_page=0, to_page=0, start_at=page_num_0based)
            snapshot_doc.close()

    Controller 建立指令的範例（Phase 4）：
        snapshot = model._capture_page_snapshot(page - 1)
        cmd = EditTextCommand(
            model=model,
            page_num=page,
            rect=rect,
            new_text=new_text,
            font=font,
            size=size,
            color=color,
            original_text=original_text,
            vertical_shift_left=vertical_shift_left,
            page_snapshot_bytes=snapshot,
            old_block_id=target_block.block_id if target_block else None,
            old_block_text=original_text,
        )
        command_manager.execute(cmd)
    """

    def __init__(
        self,
        model: Any,                         # PDFModel；用 Any 避免循環 import
        page_num: int,                      # 1-based（與 edit_text 介面一致）
        rect: fitz.Rect,
        new_text: str,
        font: str,
        size: int,
        color: tuple,
        original_text: Optional[str],
        vertical_shift_left: bool,
        page_snapshot_bytes: bytes,         # execute() 前擷取的頁面 bytes 快照
        old_block_id: Optional[str],        # 目標 block 的 ID（供 undo 後索引驗證用）
        old_block_text: Optional[str],      # 目標 block 修改前的文字（Log / debug 用）
        new_rect: Optional[Any] = None,     # 拖曳移動後的目標位置（None = 不移動）
        target_span_id: Optional[str] = None,
    ):
        self._model = model
        self._page_num = page_num
        self._rect = fitz.Rect(rect)        # 存副本，避免被外部改動
        self._new_text = new_text
        self._font = font
        self._size = size
        self._color = color
        self._original_text = original_text
        self._vertical_shift_left = vertical_shift_left
        self._page_snapshot_bytes = page_snapshot_bytes
        self._old_block_id = old_block_id
        self._old_block_text = old_block_text
        self._new_rect = fitz.Rect(new_rect) if new_rect is not None else None
        self._target_span_id = target_span_id
        self._executed = False              # 防止在未 execute 前呼叫 undo

    @property
    def description(self) -> str:
        preview = (
            (self._new_text[:20] + "…")
            if len(self._new_text) > 20
            else self._new_text
        )
        return f"編輯文字「{preview}」（頁面 {self._page_num}）"

    def execute(self) -> None:
        """
        執行文字編輯：直接委派給 model.edit_text()。
        快照已在 CommandManager.execute() 建構本物件時事先擷取，此處不重複。
        """
        self._model.edit_text(
            self._page_num,
            self._rect,
            self._new_text,
            self._font,
            self._size,
            self._color,
            self._original_text,
            self._vertical_shift_left,
            new_rect=self._new_rect,
            target_span_id=self._target_span_id,
        )
        self._executed = True
        logger.debug(f"EditTextCommand.execute(): {self.description}")

    def undo(self) -> None:
        """
        還原頁面至 execute() 前的狀態：
          1. 呼叫 model._restore_page_from_snapshot() 用 bytes 快照替換該頁。
          2. 呼叫 model.block_manager.rebuild_page() 重建該頁 TextBlock 索引。

        依賴 Phase 3 加入 pdf_model.py 的兩個 helper 方法。
        """
        if not self._executed:
            logger.warning(f"EditTextCommand.undo(): 尚未執行過，跳過還原")
            return

        page_num_0based = self._page_num - 1

        # Phase 3: _restore_page_from_snapshot() 將在 pdf_model.py 中實作
        self._model._restore_page_from_snapshot(
            page_num_0based, self._page_snapshot_bytes
        )

        # Phase 3: 重建該頁索引，確保後續 find_by_rect 等查詢正確
        self._model.block_manager.rebuild_page(page_num_0based, self._model.doc)

        logger.debug(
            f"EditTextCommand.undo(): 已還原頁面 {self._page_num}，"
            f"原文字='{self._old_block_text}'"
        )


# ──────────────────────────────────────────────────────────────────────────────
# SnapshotCommand
# ──────────────────────────────────────────────────────────────────────────────

class SnapshotCommand(EditCommand):
    """
    文件整體快照指令：以 before/after bytes 快照實作完整的 undo/redo。

    適用於 delete_pages、rotate_pages、insert_blank_page、
    add_highlight、add_rect、add_annotation 等操作。

    設計原則：
      - before_bytes：操作前整份文件的 bytes（undo 用）
      - after_bytes ：操作後整份文件的 bytes（redo 用）
      - execute() 是 redo 的入口，還原至 after_bytes
      - undo()    是撤銷的入口，還原至 before_bytes
      - 兩者都會呼叫 block_manager.build_index() 以更新 TextBlock 索引

    Controller 建立範例：
        before = model._capture_doc_snapshot()
        model.delete_pages([3])
        after  = model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=model,
            command_type="delete_pages",
            affected_pages=[3],
            before_bytes=before,
            after_bytes=after,
            description="刪除頁面 3",
        )
        model.command_manager.record(cmd)   # ← 用 record，不用 execute

    is_structural：True 表示操作會影響頁數/頁序（delete/insert），
                   Controller 的 undo/redo 需要全量重建縮圖與場景。
    """

    _STRUCTURAL_TYPES = frozenset({
        "delete_pages", "insert_blank_page", "insert_pages_from_file"
    })

    def __init__(
        self,
        model: Any,
        command_type: str,
        affected_pages: list,
        before_bytes: bytes,
        after_bytes: bytes,
        description: str,
    ):
        self._model = model
        self._command_type = command_type
        self._affected_pages = list(affected_pages)
        self._before_bytes = before_bytes
        self._after_bytes = after_bytes
        self._description = description

    @property
    def description(self) -> str:
        return self._description

    @property
    def is_structural(self) -> bool:
        """True 時 Controller 的 undo/redo 需要全量重建縮圖與場景。"""
        return self._command_type in self._STRUCTURAL_TYPES

    @property
    def affected_pages(self) -> list:
        return self._affected_pages

    def execute(self) -> None:
        """redo：從 after_bytes 還原文件，並重建 TextBlock 索引。"""
        self._model._restore_doc_from_snapshot(self._after_bytes)
        self._model.block_manager.build_index(self._model.doc)
        logger.debug(f"SnapshotCommand.execute() [redo]: {self._description}")

    def undo(self) -> None:
        """撤銷：從 before_bytes 還原文件，並重建 TextBlock 索引。"""
        self._model._restore_doc_from_snapshot(self._before_bytes)
        self._model.block_manager.build_index(self._model.doc)
        logger.debug(f"SnapshotCommand.undo(): {self._description}")


# ──────────────────────────────────────────────────────────────────────────────
# CommandManager
# ──────────────────────────────────────────────────────────────────────────────

class CommandManager:
    """
    管理可撤銷指令的 undo/redo 堆疊（Command Pattern 的 Invoker）。

    Phase 6：統一 undo 堆疊，取代舊的檔案式 _save_state / undo / redo 機制。
    所有操作（文字編輯用 execute()，其他操作用 record()）統一由此管理器管理。

    使用流程：
        # 建構指令（包含事先擷取的頁面快照）
        snapshot = model._capture_page_snapshot(page - 1)
        cmd = EditTextCommand(model, page, rect, new_text, ...,
                              page_snapshot_bytes=snapshot, ...)
        # 執行並記錄
        command_manager.execute(cmd)
        ...
        # 撤銷 / 重做
        command_manager.undo()
        command_manager.redo()
        # 儲存後標記（重要：避免 has_pending_changes 誤報）
        command_manager.mark_saved()
    """

    def __init__(self):
        self._undo_stack: list[EditCommand] = []
        self._redo_stack: list[EditCommand] = []
        # [修正] 追蹤「已儲存時的 undo 堆疊大小」，供 has_pending_changes() 正確判斷；
        #        概念與 pdf_model.py 的 self.saved_undo_stack_size 一致
        self._saved_stack_size: int = 0

    # ──────────────────────────────────────────────────────────────────────────
    # 公開介面
    # ──────────────────────────────────────────────────────────────────────────

    def execute(self, cmd: EditCommand) -> None:
        """
        執行指令並推入 undo 堆疊；同時清空 redo 堆疊（新操作使歷史失效）。

        Args:
            cmd: 已建構（含快照）且尚未 execute() 的 EditCommand 物件。
        注意：若指令已在外部執行完（如 SnapshotCommand），請改用 record()。
        """
        cmd.execute()
        self._undo_stack.append(cmd)

        # 新操作使原 redo 歷史失效
        if self._redo_stack:
            logger.debug(
                f"CommandManager.execute(): 清空 redo 堆疊（{len(self._redo_stack)} 筆）"
            )
            self._redo_stack.clear()

        logger.debug(
            f"CommandManager.execute(): {cmd.description}，"
            f"undo 堆疊大小={len(self._undo_stack)}"
        )

    def record(self, cmd: EditCommand) -> None:
        """
        記錄「已在外部執行完畢」的指令到 undo 堆疊（不重複呼叫 execute()）。

        適用情境：Controller 已先執行操作、後補建 SnapshotCommand 的流程：
            before = model._capture_doc_snapshot()
            model.delete_pages(pages)          # 操作已完成
            after  = model._capture_doc_snapshot()
            cmd = SnapshotCommand(...)
            model.command_manager.record(cmd)  # 補記，不重複執行

        Args:
            cmd: 已執行完的 EditCommand 物件（SnapshotCommand 等）。
        """
        self._undo_stack.append(cmd)
        if self._redo_stack:
            logger.debug(
                f"CommandManager.record(): 清空 redo 堆疊（{len(self._redo_stack)} 筆）"
            )
            self._redo_stack.clear()
        logger.debug(
            f"CommandManager.record(): {cmd.description}，"
            f"undo 堆疊大小={len(self._undo_stack)}"
        )

    def undo(self) -> bool:
        """
        撤銷最近一次操作。

        Returns:
            True 若成功撤銷，False 若 undo 堆疊為空。
        """
        if not self._undo_stack:
            logger.debug("CommandManager.undo(): undo 堆疊為空，無可撤銷")
            return False

        cmd = self._undo_stack.pop()
        cmd.undo()
        self._redo_stack.append(cmd)

        logger.debug(
            f"CommandManager.undo(): {cmd.description}，"
            f"undo 堆疊大小={len(self._undo_stack)}，"
            f"redo 堆疊大小={len(self._redo_stack)}"
        )
        return True

    def redo(self) -> bool:
        """
        重做最近一次被撤銷的操作。

        Returns:
            True 若成功重做，False 若 redo 堆疊為空。
        """
        if not self._redo_stack:
            logger.debug("CommandManager.redo(): redo 堆疊為空，無可重做")
            return False

        cmd = self._redo_stack.pop()
        cmd.execute()
        self._undo_stack.append(cmd)

        logger.debug(
            f"CommandManager.redo(): {cmd.description}，"
            f"undo 堆疊大小={len(self._undo_stack)}，"
            f"redo 堆疊大小={len(self._redo_stack)}"
        )
        return True

    def mark_saved(self) -> None:
        """
        標記當前 undo 堆疊大小為「已儲存狀態」。
        應在 PDFModel.save_as()（或 save()）成功後呼叫。

        [修正] 對應 pdf_model.py 的 self.saved_undo_stack_size = len(self.undo_stack) 邏輯；
               修正了 has_pending_changes() 儲存後仍誤報 True 的 bug。

        Phase 3 整合範例（pdf_model.py 的 save_as 末尾）：
            self.command_manager.mark_saved()
        """
        self._saved_stack_size = len(self._undo_stack)
        logger.debug(
            f"CommandManager.mark_saved(): 已儲存標記，"
            f"saved_size={self._saved_stack_size}"
        )

    def clear(self) -> None:
        """清空所有堆疊（開啟新 PDF 或關閉 PDF 時呼叫）。"""
        undo_count = len(self._undo_stack)
        redo_count = len(self._redo_stack)
        self._undo_stack.clear()
        self._redo_stack.clear()
        # [修正] 同步重置已儲存標記，確保 has_pending_changes() 在 clear 後正確回傳 False
        self._saved_stack_size = 0
        logger.debug(
            f"CommandManager.clear(): 已清空 undo({undo_count}) + redo({redo_count}) 堆疊"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 狀態查詢
    # ──────────────────────────────────────────────────────────────────────────

    def can_undo(self) -> bool:
        """是否有可撤銷的操作（供 UI 啟用/停用 Undo 按鈕）。"""
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        """是否有可重做的操作（供 UI 啟用/停用 Redo 按鈕）。"""
        return bool(self._redo_stack)

    @property
    def undo_count(self) -> int:
        """undo 堆疊中的操作數量。"""
        return len(self._undo_stack)

    @property
    def redo_count(self) -> int:
        """redo 堆疊中的操作數量。"""
        return len(self._redo_stack)

    def has_pending_changes(self) -> bool:
        """
        是否有尚未存檔的文字編輯變更。

        [修正] 改用 _saved_stack_size 比對，正確處理以下兩種情境：
          - 執行了編輯但尚未存檔 → True
          - 存檔後再 undo（檔案內容已與磁碟不同）→ True
          - 剛存檔後 / clear() 後 → False

        設計說明：此方法僅追蹤文字編輯（EditTextCommand）的變更狀態，
        檔案整體是否已儲存仍由 pdf_model.py 的 has_unsaved_changes() 主控。
        Phase 4 可考慮將兩者整合。
        """
        return len(self._undo_stack) != self._saved_stack_size
