from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Any

import fitz

from model.text_commit.dto import (
    HIGH_FIDELITY_TIERS,
    CommitOutcome,
    CommitStatus,
    RejectReason,
)
from model.text_commit.inspect import page_fingerprint, read_page_streams
from model.text_commit.patch import (
    PatchSet,
    SpliceError,
    StalePlanError,
    apply_patchset,
    build_reversal_patchset,
)

if TYPE_CHECKING:
    # 避免循環 import：只在型別檢查期間引入 PDFModel
    pass

logger = logging.getLogger(__name__)


class EditTextResult(str, Enum):
    SUCCESS = "success"
    NO_CHANGE = "no_change"
    TARGET_BLOCK_NOT_FOUND = "target_block_not_found"
    TARGET_SPAN_NOT_FOUND = "target_span_not_found"
    # V2 strict mode: the edit failed every enabled high-fidelity tier and
    # the degraded legacy engine is not permitted to run. No mutation happened.
    REJECTED_STRICT = "rejected_strict"
    # V2 hard-reject boundary: signed documents / widget-bearing pages are
    # categorically refused for the tiered engine, in strict *or*
    # non-strict mode. No mutation happened.
    REJECTED_UNSUPPORTED = "rejected_unsupported"
    # V2 redo safety: a Tier 0 commit's retained forward patch no longer
    # matches the current page fingerprint (the document changed since the
    # commit it is replaying). Redo refused; zero mutation happened.
    STALE_PLAN = "stale_plan"


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

    def _byte_size(self) -> int:
        """回傳此指令持有的快照位元組數（byte-budget 修剪用）。預設 0。"""
        return 0

    def _snapshot_chunks(self) -> tuple[bytes, ...]:
        """Return all snapshot byte objects held by this command (for unique-byte accounting)."""
        return ()


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
        size: float,
        color: tuple,
        original_text: str | None,
        vertical_shift_left: bool,
        page_snapshot_bytes: bytes,         # execute() 前擷取的頁面 bytes 快照
        old_block_id: str | None,        # 目標 block 的 ID（供 undo 後索引驗證用）
        old_block_text: str | None,      # 目標 block 修改前的文字（Log / debug 用）
        new_rect: Any | None = None,     # 拖曳移動後的目標位置（None = 不移動）
        target_span_id: str | None = None,
        target_mode: str | None = None,
        reflow_fn: Any | None = None,    # callable()，在 model.edit_text() 後呼叫做 displacement reflow
        style_overrides: Any | None = None,  # StyleOverrides；使用者實際碰過的樣式欄位
        plan_token: str | None = None,   # V2 prepared-plan token（stale 檢查用）
    ):
        self._model = model
        self._page_num = page_num
        self._rect = fitz.Rect(rect)        # 存副本，避免被外部改動
        self._new_text = new_text
        self._font = font
        self._size = float(size)
        self._color = color
        self.result: EditTextResult = EditTextResult.SUCCESS
        self._original_text = original_text
        self._vertical_shift_left = vertical_shift_left
        self._page_snapshot_bytes = page_snapshot_bytes
        self._old_block_id = old_block_id
        self._old_block_text = old_block_text
        self._new_rect = fitz.Rect(new_rect) if new_rect is not None else None
        self._target_span_id = target_span_id
        self._target_mode = target_mode
        self._reflow_fn = reflow_fn         # displacement reflow callback（Track A/B）
        self.style_overrides = style_overrides  # redo 需保留原始 intent
        self.plan_token = plan_token
        self.outcome: Any | None = None     # CommitOutcome，execute() 後由 model 提供
        self._executed = False              # 防止在未 execute 前呼叫 undo

        # V2 tier-aware reversal (Task 9; Task 11 Slice 1 widened this to
        # every high-fidelity tier): when the first execute() commits via a
        # high-fidelity tier (dto.HIGH_FIDELITY_TIERS -- Tier 0 or Tier 1),
        # these hold a validated forward/inverse PatchSet pair built from the
        # observed before/after stream diff (see model.text_commit.patch.
        # build_reversal_patchset). Populated once, replayed by every later
        # undo()/redo() instead of re-running the full model.edit_text()
        # pipeline (which would re-prepare from scratch on a different page
        # state and cannot reproduce the exact same committed bytes). Stay
        # ``None`` for every non-high-fidelity-tier command (Tier 2/legacy),
        # which keeps the original page-snapshot undo/full-redo behavior.
        self._tier0_forward_patchset: PatchSet | None = None
        self._tier0_inverse_patchset: PatchSet | None = None
        # Whether the forward patch is CURRENTLY applied to the live
        # document (True right after commit/redo, False right after undo).
        self._tier0_active = False
        # fidelity_protected_pages membership for this page *before* the
        # very first execute() -- restored verbatim by every undo(),
        # whichever restore path (patch replay or snapshot fallback) runs.
        self._pre_protected = False

    @property
    def description(self) -> str:
        preview = (
            (self._new_text[:20] + "…")
            if len(self._new_text) > 20
            else self._new_text
        )
        return f"編輯文字「{preview}」（頁面 {self._page_num}）"

    def _byte_size(self) -> int:
        return len(self._page_snapshot_bytes)

    def _snapshot_chunks(self) -> tuple[bytes, ...]:
        return (self._page_snapshot_bytes,)

    def execute(self) -> bool:  # type: ignore[override]
        """
        執行文字編輯：直接委派給 model.edit_text()。
        快照已在 CommandManager.execute() 建構本物件時事先擷取，此處不重複。

        Intentional LSP widening: EditCommand.execute() is annotated -> None
        (test_edit_command_execute_contract_stays_optional_for_non_edit_text_commands
        pins that), but this override returns bool so CommandManager can detect
        a no-op edit (False) and skip the undo-stack record — see
        test_edit_text_command_execute_annotation_is_bool. The `is False` check
        in CommandManager.execute()/redo() treats every other subclass's None
        return as "recordable", so the wider return type is safe at every call
        site; only mypy's strict override variance objects.

        V2 tier-aware redo: if a *previous* execute() on this command
        committed via Tier 0 and it is currently undone (``_tier0_active``
        False), CommandManager.redo() calling this same method must NOT
        re-run the whole model.edit_text() pipeline from scratch — that
        would re-classify/re-prepare against whatever the page looks like
        now and cannot guarantee reproducing the exact same committed
        bytes. Instead it replays the retained forward PatchSet directly
        (see ``_redo_tier0``): success or a stale-safe, zero-mutation
        refusal, never a silent fall-through to the legacy engine.
        """
        if self._tier0_forward_patchset is not None and self._executed and not self._tier0_active:
            return self._redo_tier0()

        page_idx = self._page_num - 1
        # Best-effort: minimal/mocked models (unit tests exercising only
        # style-intent/reflow plumbing) may not expose fidelity_protected_pages
        # or a real fitz doc at all -- degrade to "no reversal tracking" for
        # those exactly like before this command grew tier0 awareness,
        # rather than requiring every caller to be a full PDFModel.
        pre_protected = False
        pre_streams: tuple[tuple[int, bytes], ...] = ()
        pre_fingerprint: str | None = None
        pre_page: fitz.Page | None = None
        try:
            pre_protected = page_idx in self._model.fidelity_protected_pages
            pre_page = self._model.doc[page_idx]
            pre_streams = tuple(read_page_streams(self._model.doc, pre_page))
            pre_fingerprint = page_fingerprint(self._model.doc, pre_page)
        except (AttributeError, IndexError, ValueError, TypeError) as exc:
            logger.debug(
                "EditTextCommand.execute(): pre-edit stream capture skipped page=%s %s",
                self._page_num,
                type(exc).__name__,
            )

        self.result = self._model.edit_text(
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
            target_mode=self._target_mode,
            style_overrides=self.style_overrides,
        )
        if self.result is not EditTextResult.SUCCESS:
            self._executed = False
            logger.debug(
                "EditTextCommand.execute(): skipped record for result=%s",
                self.result.value,
            )
            return False
        # V2 plumbing: history keeps the full CommitOutcome of this commit.
        self.outcome = getattr(self._model, "last_commit_outcome", None)
        self._pre_protected = pre_protected
        if (
            self.outcome is not None
            and self.outcome.tier in HIGH_FIDELITY_TIERS
            and pre_fingerprint is not None
            and pre_page is not None
        ):
            self._capture_tier0_reversal(page_idx, pre_streams, pre_fingerprint)
        # Displacement reflow：將後續塊向上/下推移（Track A/B 引擎）。
        # 高保真 tier 的 outcome 會禁止外部 reflow（不得移動鄰居）。
        allows_reflow = (
            self.outcome.allows_external_reflow if self.outcome is not None else True
        )
        if self._reflow_fn is not None and allows_reflow:
            try:
                self._reflow_fn()
            except Exception as _rf_e:
                logger.warning(f"EditTextCommand reflow_fn 失敗（不影響主編輯）: {_rf_e}")
        self._executed = True
        logger.debug(f"EditTextCommand.execute(): {self.description}")
        return True

    def _capture_tier0_reversal(
        self,
        page_idx: int,
        pre_streams: tuple[tuple[int, bytes], ...],
        pre_fingerprint: str,
    ) -> None:
        """After a successful high-fidelity tier commit (Tier 0 or Tier 1),
        retain a forward/inverse PatchSet pair so future undo()/redo() replay
        the exact validated intent instead of re-running model.edit_text().
        Best-effort: if the observed diff doesn't look like exactly one
        high-fidelity stream patch, this command silently keeps using the
        page-snapshot fallback for undo/redo instead (never guesses).
        """
        try:
            page = self._model.doc[page_idx]
        except (IndexError, ValueError):
            return
        reversal = build_reversal_patchset(self._model.doc, page, pre_streams, pre_fingerprint)
        if reversal is None:
            logger.debug(
                "EditTextCommand: tier0 reversal not captured (page=%s), "
                "falling back to page-snapshot undo/redo",
                self._page_num,
            )
            return
        self._tier0_forward_patchset, self._tier0_inverse_patchset = reversal
        self._tier0_active = True

    def _redo_tier0(self) -> bool:
        """Replay the retained forward PatchSet — the same validated intent
        as the original high-fidelity tier commit — or fail STALE with zero
        mutation.

        Never falls through to the legacy engine: a stale forward patch
        means the document changed since the commit it is replaying, so the
        only safe outcomes are "identical replay" or "refuse, untouched".
        """
        forward = self._tier0_forward_patchset
        if forward is None:
            # execute() only routes here when the forward patch exists;
            # defensive refusal keeps mypy honest and mutates nothing.
            return False
        page_idx = self._page_num - 1
        try:
            page = self._model.doc[page_idx]
            apply_patchset(self._model.doc, page, forward)
        except (StalePlanError, SpliceError, IndexError, ValueError) as exc:
            logger.warning(
                "EditTextCommand.redo(): tier0 forward patch stale (%s); "
                "redo refused, zero mutation",
                type(exc).__name__,
            )
            self._model.last_commit_outcome = CommitOutcome(
                status=CommitStatus.STALE_PLAN,
                tier=None,
                fallback_chain=(f"tier0:{RejectReason.STALE_PLAN}",),
                warnings=(),
                font_outcomes=(),
                verified_properties=(),
                degraded_reason=str(exc),
                allows_external_reflow=False,
            )
            self.result = EditTextResult.STALE_PLAN
            return False

        self._model.fidelity_protected_pages.add(page_idx)
        self._model.block_manager.rebuild_page(page_idx, self._model.doc)
        self._tier0_active = True
        self.result = EditTextResult.SUCCESS
        # Same validated intent as the original commit -- outcome is left
        # untouched (it already describes the committed state this replay
        # reproduces byte-for-byte); only refresh the model's transient
        # "last operation" field for callers that read it directly.
        self._model.last_commit_outcome = self.outcome
        logger.debug(
            "EditTextCommand.redo(): tier0 forward patch replayed for page %s",
            self._page_num,
        )
        return True

    def _restore_protection_membership(self, page_idx: int) -> None:
        if self._pre_protected:
            self._model.fidelity_protected_pages.add(page_idx)
        else:
            self._model.fidelity_protected_pages.discard(page_idx)

    def undo(self) -> None:
        """
        還原頁面至 execute() 前的狀態。

        V2 tier-aware path: if this command committed via Tier 0 and the
        retained inverse PatchSet is still fingerprint-valid, replay it
        directly -- byte-identical source stream, annotation xrefs
        untouched (patch.py only ever calls ``doc.update_stream``, never
        redaction/annotation recreate). Falls back to the original
        page-snapshot restore when there is no tier0 reversal to replay, or
        when it has gone stale (the document changed since the commit it
        would be reversing) -- StalePlanError there is expected, not a bug.
        Either path restores fidelity_protected_pages membership to its
        pre-edit value.
        """
        if not self._executed:
            logger.warning("EditTextCommand.undo(): 尚未執行過，跳過還原")
            return

        page_num_0based = self._page_num - 1

        if self._tier0_inverse_patchset is not None and self._tier0_active:
            try:
                page = self._model.doc[page_num_0based]
                apply_patchset(self._model.doc, page, self._tier0_inverse_patchset)
            except (StalePlanError, SpliceError, IndexError, ValueError) as exc:
                logger.warning(
                    "EditTextCommand.undo(): tier0 inverse patch stale (%s); "
                    "falling back to page-snapshot restore",
                    type(exc).__name__,
                )
            else:
                self._restore_protection_membership(page_num_0based)
                self._tier0_active = False
                self._model.block_manager.rebuild_page(page_num_0based, self._model.doc)
                logger.debug(
                    f"EditTextCommand.undo(): tier0 inverse patch restored 頁面 {self._page_num}，"
                    f"原文字='{self._old_block_text}'"
                )
                return

        # Phase 3: _restore_page_from_snapshot() 將在 pdf_model.py 中實作
        self._model._restore_page_from_snapshot(
            page_num_0based, self._page_snapshot_bytes
        )
        self._restore_protection_membership(page_num_0based)
        self._tier0_active = False

        # Phase 3: 重建該頁索引，確保後續 find_by_rect 等查詢正確
        self._model.block_manager.rebuild_page(page_num_0based, self._model.doc)

        logger.debug(
            f"EditTextCommand.undo(): 已還原頁面 {self._page_num}，"
            f"原文字='{self._old_block_text}'"
        )


# ──────────────────────────────────────────────────────────────────────────────
# SnapshotCommand
# ──────────────────────────────────────────────────────────────────────────────

class AddTextboxCommand(EditCommand):
    """Atomic add-textbox command with page-level undo/redo boundaries."""

    def __init__(
        self,
        model: Any,
        page_num: int,
        visual_rect: fitz.Rect,
        text: str,
        font: str,
        size: int,
        color: tuple,
        before_page_snapshot_bytes: bytes,
    ) -> None:
        self._model = model
        self._page_num = int(page_num)
        self._visual_rect = fitz.Rect(visual_rect)
        self._text = text
        self._font = font
        self._size = int(size)
        self._color = color
        self._before_page_snapshot_bytes = before_page_snapshot_bytes
        self._after_page_snapshot_bytes: bytes | None = None
        self._executed = False

    @property
    def description(self) -> str:
        preview = (self._text[:20] + "...") if len(self._text) > 20 else self._text
        return f"新增文字框 '{preview}'（頁 {self._page_num}）"

    def _byte_size(self) -> int:
        after = self._after_page_snapshot_bytes
        return len(self._before_page_snapshot_bytes) + (len(after) if after is not None else 0)

    def _snapshot_chunks(self) -> tuple[bytes, ...]:
        after = self._after_page_snapshot_bytes
        if after is not None:
            return (self._before_page_snapshot_bytes, after)
        return (self._before_page_snapshot_bytes,)

    def execute(self) -> None:
        page_idx = self._page_num - 1
        if not self._executed:
            self._model.add_textbox(
                self._page_num,
                self._visual_rect,
                self._text,
                font=self._font,
                size=self._size,
                color=self._color,
            )
            self._after_page_snapshot_bytes = self._model._capture_page_snapshot_strict(page_idx)
            self._executed = True
            logger.debug("AddTextboxCommand.execute(first): %s", self.description)
            return

        if self._after_page_snapshot_bytes is None:
            raise RuntimeError("AddTextboxCommand redo 缺少 after page snapshot")
        self._model._restore_page_from_snapshot(page_idx, self._after_page_snapshot_bytes)
        self._model.block_manager.rebuild_page(page_idx, self._model.doc)
        logger.debug("AddTextboxCommand.execute(redo): %s", self.description)

    def undo(self) -> None:
        if not self._executed:
            logger.warning("AddTextboxCommand.undo(): 尚未執行，略過")
            return
        page_idx = self._page_num - 1
        self._model._restore_page_from_snapshot(page_idx, self._before_page_snapshot_bytes)
        self._model.block_manager.rebuild_page(page_idx, self._model.doc)
        logger.debug("AddTextboxCommand.undo(): %s", self.description)


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
      - 兩者都會清空舊 cache，並只重建 `affected_pages`（其餘頁面走 lazy rebuild）
        目的：避免大檔在 undo/redo 後做全文件重建而卡住 UI。

    Controller 建立範例：
        before = model._capture_doc_snapshot()
        model.delete_pages([3])
        after  = model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=model,
            command_type="delete_pages",
            affected_pages=[3],  # should be the model-returned "actual affected pages" after validation
            before_bytes=before,
            after_bytes=after,
            description="刪除頁面 3",
        )
        model.command_manager.record(cmd)   # ← 用 record，不用 execute

    is_structural：True 表示操作會影響頁數/頁序（delete/insert/move），
                   Controller 的 undo/redo 需要全量重建縮圖與場景。
    """

    _STRUCTURAL_TYPES = frozenset({
        "delete_pages",
        "insert_blank_page",
        "insert_pages_from_file",
        "move_page",
        "merge_pdfs",
        "move_text_across_pages",
    })

    def __init__(
        self,
        model: Any,
        command_type: str,
        affected_pages: list,
        before_bytes: bytes,
        after_bytes: bytes,
        description: str,
        *,
        before_placeholder_active: bool | None = None,
        after_placeholder_active: bool | None = None,
        index_pages: list[int] | None = None,
    ):
        self._model = model
        self._command_type = command_type
        self._affected_pages = list(affected_pages)
        self._before_bytes = before_bytes
        self._after_bytes = after_bytes
        self._description = description
        self._before_placeholder_active = before_placeholder_active
        self._after_placeholder_active = after_placeholder_active
        self._index_pages = list(index_pages) if index_pages is not None else None

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

    def _byte_size(self) -> int:
        return len(self._before_bytes) + len(self._after_bytes)

    def _snapshot_chunks(self) -> tuple[bytes, ...]:
        return (self._before_bytes, self._after_bytes)

    def execute(self) -> None:
        """redo：從 after_bytes 還原文件，並重建 TextBlock 索引。"""
        self._model._restore_doc_from_snapshot(self._after_bytes)
        if self._after_placeholder_active is not None:
            self._model._set_blank_placeholder_active(self._after_placeholder_active)
        # Structural redo avoids the old eager full rebuild and only restores the hot pages.
        self._model.refresh_structural_indexes(self._index_pages or self._affected_pages)
        logger.debug(f"SnapshotCommand.execute() [redo]: {self._description}")

    def undo(self) -> None:
        """撤銷：從 before_bytes 還原文件，並重建 TextBlock 索引。"""
        self._model._restore_doc_from_snapshot(self._before_bytes)
        if self._before_placeholder_active is not None:
            self._model._set_blank_placeholder_active(self._before_placeholder_active)
        # The remaining pages are rebuilt later through the model/controller lazy path.
        self._model.refresh_structural_indexes(self._index_pages or self._affected_pages)
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

    MAX_UNDO_STACK_SIZE = 100
    MAX_UNDO_STACK_BYTES = 512 * 1024 * 1024  # 512 MiB

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
        executed = cmd.execute()
        if executed is False:
            logger.debug(
                "CommandManager.execute(): command skipped undo record: %s",
                cmd.description,
            )
            return
        self._undo_stack.append(cmd)
        self._dedup_top_snapshot_pair()
        self._trim_undo_stack_if_needed()

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
        self._dedup_top_snapshot_pair()
        self._trim_undo_stack_if_needed()
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

        cmd = self._undo_stack[-1]
        cmd.undo()
        self._undo_stack.pop()
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

        cmd = self._redo_stack[-1]
        executed = cmd.execute()
        if executed is False:
            logger.debug(
                "CommandManager.redo(): command redo skipped: %s",
                cmd.description,
            )
            return False
        self._redo_stack.pop()
        self._undo_stack.append(cmd)
        self._dedup_top_snapshot_pair()
        self._trim_undo_stack_if_needed()

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

    def _dedup_top_snapshot_pair(self) -> None:
        """堆疊頂端相鄰兩筆 SnapshotCommand 邊界快照相同時，共用同一 bytes 物件。

        典型情境：操作 N 的 after_bytes 與操作 N+1 的 before_bytes 內容相同
        （兩次 _capture_doc_snapshot 之間文件未變動）。bytes 不可變、還原端
        （fitz.open("pdf", ...)）內部複製，共用安全；可省下一份整文件快照。
        僅對 SnapshotCommand（整文件快照）做此最佳化。
        """
        if len(self._undo_stack) < 2:
            return
        prev = self._undo_stack[-2]
        curr = self._undo_stack[-1]
        if not isinstance(prev, SnapshotCommand) or not isinstance(curr, SnapshotCommand):
            return
        if prev._after_bytes is curr._before_bytes:
            return
        if prev._after_bytes == curr._before_bytes:
            curr._before_bytes = prev._after_bytes
            logger.debug(
                "CommandManager: deduplicated adjacent snapshot boundary (%s bytes shared)",
                len(prev._after_bytes),
            )

    def _trim_undo_stack_if_needed(self) -> None:
        """Evict oldest undo entries when count or byte budget is exceeded."""
        overflow = len(self._undo_stack) - self.MAX_UNDO_STACK_SIZE
        if overflow > 0:
            del self._undo_stack[:overflow]
            self._saved_stack_size = max(0, self._saved_stack_size - overflow)
            logger.debug(
                "CommandManager: evicted %s oldest undo commands to enforce max=%s",
                overflow,
                self.MAX_UNDO_STACK_SIZE,
            )

        total_bytes = self._unique_byte_total()
        if total_bytes <= self.MAX_UNDO_STACK_BYTES:
            return
        evicted = 0
        while len(self._undo_stack) > 1 and total_bytes > self.MAX_UNDO_STACK_BYTES:
            self._undo_stack.pop(0)
            evicted += 1
            total_bytes = self._unique_byte_total()
        if evicted:
            self._saved_stack_size = max(0, self._saved_stack_size - evicted)
            logger.debug(
                "CommandManager: evicted %s oldest undo commands to enforce byte budget=%s (remaining=%s bytes)",
                evicted,
                self.MAX_UNDO_STACK_BYTES,
                total_bytes,
            )
        if total_bytes > self.MAX_UNDO_STACK_BYTES:
            logger.warning(
                "CommandManager: newest command (%s bytes) exceeds byte budget %s — keeping it",
                total_bytes,
                self.MAX_UNDO_STACK_BYTES,
            )

    def _unique_byte_total(self) -> int:
        # Dedup by CONTENT, not id(): adjacent boundary pairs are aliased to one
        # object by _dedup_top_snapshot_pair, but byte-identical snapshots that are
        # *non-adjacent* (e.g. a fresh capture matching an earlier doc state) remain
        # distinct objects. An id()-keyed sum double-counts those against the budget
        # and evicts prematurely. bytes are hashable (CPython caches the hash on the
        # object), so a content-keyed set is exact and amortized-cheap across the
        # repeated calls in the trim loop.
        seen: set[bytes] = set()
        total = 0
        for cmd in self._undo_stack:
            for chunk in cmd._snapshot_chunks():
                if chunk not in seen:
                    seen.add(chunk)
                    total += len(chunk)
        return total

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
