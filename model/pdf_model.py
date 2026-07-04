from __future__ import annotations

import difflib  # 相似度比對
import html as _html_mod
import io  # 用於 BytesIO 記憶體 stream（文件推薦 in-memory PDF）
import json
import logging
import math
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import fitz

# Optimizer internals live in `model/pdf_optimizer.py`.
# `PDFModel` keeps the public facade stable and delegates to the internal module.
from model import pdf_object_ops, pdf_optimizer, pdf_text_edit
from model.edit_commands import CommandManager, EditTextResult
from model.object_requests import DeleteObjectRequest, MoveObjectRequest, ObjectHitInfo, RotateObjectRequest
from model.object_requests import ResizeObjectRequest
from model.text_block import (
    EditableParagraph,
    EditableSpan,
    TextBlockManager,
    rotation_degrees_from_dir,
)
from model.geometry import clamp_rect_to_page, rect_from_points, rect_overlap_ratio
from model.text_normalization import normalize_text, normalized_similarity
from model.tools import ToolManager

# [優化 1] 模組級正則預編譯：避免每次呼叫 _convert_text_to_html 時重新編譯，提升效能
_RE_HTML_TEXT_PARTS = re.compile(r'([\u4e00-\u9fff\u3040-\u30ff]+|[^\u4e00-\u9fff\u3040-\u30ff\n ]+| +|\n)')
_RE_CJK = re.compile(r'[\u4e00-\u9fff\u3040-\u30ff]+')
_BULLET_PREFIXES = ("- ", "* ", "\u2022 ", "\u25aa ", "\u25cf ")
_RE_NUMBERED_BULLET = re.compile(r"^\d+[.)]\s+")

# Optional Windows CJK font files for visible family differences in insert_htmlbox.
_WINDOWS_CJK_FONT_FILES = {
    "microsoft jhenghei": Path(r"C:\Windows\Fonts\msjh.ttc"),
    "pmingliu": Path(r"C:\Windows\Fonts\mingliu.ttc"),
    "dfkai-sb": Path(r"C:\Windows\Fonts\kaiu.ttf"),
}

_CUSTOM_CJK_ALIASES = {
    "microsoft jhenghei": "PdfEditorMicrosoftJhengHei",
    "pmingliu": "PdfEditorPMingLiU",
    "dfkai-sb": "PdfEditorDFKaiSB",
}


# 設置日誌
logger = logging.getLogger(__name__)
# Re-export optimizer schema types for backwards compatibility (tests/UI import from `model.pdf_model`).
PdfOptimizeOptions = pdf_optimizer.PdfOptimizeOptions
PdfAuditItem = pdf_optimizer.PdfAuditItem
PdfAuditReport = pdf_optimizer.PdfAuditReport
PdfOptimizationResult = pdf_optimizer.PdfOptimizationResult
OptimizeSourceSnapshot = pdf_optimizer.OptimizeSourceSnapshot
OptimizeOutputCredentials = pdf_optimizer.OptimizeOutputCredentials

# Resource guards for untrusted PDFs (CWE-400 uncontrolled resource consumption,
# CWE-409 decompression bomb). A crafted document with an enormous file size,
# page count, or page dimensions can otherwise OOM/hang the process during parse
# or render. These cap the worst case; they do not affect any realistic document.
_MAX_PDF_BYTES = 512 * 1024 * 1024  # 512 MB
_MAX_PAGES = 5_000
# _MAX_PIXMAP_PX is re-exported here for backward compatibility: external callers
# and tests reference ``model.pdf_model._MAX_PIXMAP_PX`` (see docs/PITFALLS.md).
# It is unused *within* this module, so F401 is suppressed deliberately — do NOT
# let ``ruff --fix`` strip it (that breaks test_security_pdf_resource_guards).
from utils.render_limits import _MAX_PIXMAP_PX, safe_render_scale as _safe_render_scale  # noqa: E402, F401


def _guard_before_open(path: Path) -> None:
    """Reject an over-large file before handing its bytes to the native parser."""
    if path.stat().st_size > _MAX_PDF_BYTES:
        raise ValueError(f"PDF exceeds size limit ({_MAX_PDF_BYTES // 1_048_576} MB)")


def _guard_foreign_doc(path: Path, password: str | None = None) -> fitz.Document:
    """Open a foreign PDF with all resource guards applied.

    Size limit (_MAX_PDF_BYTES), open, optional authentication, page limit (_MAX_PAGES).
    Returns the opened document; caller closes it.
    """
    _guard_before_open(path)
    doc = fitz.open(str(path))
    try:
        if doc.needs_pass:
            if password is None:
                raise RuntimeError(f"document closed or encrypted — 需要密碼: {path}")
            if doc.authenticate(password) == 0:
                raise RuntimeError(f"PDF 密碼驗證失敗（authenticate 回傳 0）: {path}")
        if doc.page_count > _MAX_PAGES:
            raise ValueError(f"Foreign PDF exceeds page limit ({_MAX_PAGES} pages): {path}")
    except Exception:
        doc.close()
        raise
    return doc


def _install_rawdict_text_compat() -> None:
    """Backfill ``span['text']`` for fitz rawdict payloads that only expose chars.

    Some PyMuPDF builds (notably once a QApplication is live) omit the
    ``text`` key in rawdict spans and return only ``chars``. The no-jump E2E
    gate and several callers inspect span text straight from rawdict, so wrap
    ``fitz.Page.get_text`` once at import to reconstruct the missing key.
    """
    sentinel = "_pdf_editor_rawdict_text_compat"
    if getattr(fitz.Page, sentinel, False):
        return
    original_get_text = fitz.Page.get_text

    def _compat_get_text(page, option="text", *args, **kwargs):
        keyword_option = kwargs.get("option")
        if option == "text" and keyword_option is not None:
            effective_option = keyword_option
            result = original_get_text(page, *args, **kwargs)
        else:
            effective_option = option
            call_kwargs = dict(kwargs)
            call_kwargs.pop("option", None)
            result = original_get_text(page, option, *args, **call_kwargs)
        if effective_option != "rawdict" or not isinstance(result, dict):
            return result
        for block in result.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text") is None and isinstance(span.get("chars"), list):
                        span["text"] = "".join(ch.get("c", "") for ch in span["chars"])
        return result

    fitz.Page.get_text = _compat_get_text
    setattr(fitz.Page, sentinel, True)


_install_rawdict_text_compat()


@dataclass
class TextHit:
    target_span_id: str
    target_bbox: fitz.Rect
    target_text: str
    font: str
    size: float
    color: tuple
    rotation: int
    cluster_span_ids: list[str]
    target_mode: str = "run"
    target_paragraph_id: str | None = None

    # Keep tuple compatibility for existing callers/tests.
    def _legacy(self) -> tuple:
        return (
            self.target_bbox,
            self.target_text,
            self.font,
            self.size,
            self.color,
            self.rotation,
        )

    def __getitem__(self, idx: int):
        return self._legacy()[idx]

    def __iter__(self):
        return iter(self._legacy())

    def __len__(self):
        return len(self._legacy())


# R3.5: ``_EditTextResolveResult`` and ``_classify_insert_path`` moved to
# model/pdf_text_edit.py (LAST model seam). Re-exported so existing
# ``from model.pdf_model import ...`` test/UI imports keep working.
from model.pdf_text_edit import _EditTextResolveResult, _classify_insert_path  # noqa: E402, F401

@dataclass
class DocumentSession:
    session_id: str
    canonical_path: str
    display_name: str
    original_path: str
    doc: fitz.Document
    saved_path: str | None = None
    # Password captured at open (in-memory only), used to re-authenticate the
    # reopen-after-save handle when a full save preserves encryption. Never
    # logged or persisted to disk; the decrypted content already lives in RAM.
    password: str | None = None
    # Authentication class returned by ``doc.authenticate()`` at open: 2=user,
    # 4=owner, 6=both, None=unencrypted / no password barrier. Lets the optimize
    # pipeline preserve the source's auth role instead of promoting user->owner (R5-02).
    auth_level: int | None = None
    # Destructive edits may leave recoverable orphan xrefs in the live in-memory
    # document.  Once latched, every persistent / external serialization must do
    # a full garbage=4 rewrite.  Deliberately conservative: undo does not clear it.
    secure_save_required: bool = False
    block_manager: TextBlockManager = field(default_factory=TextBlockManager)
    command_manager: CommandManager = field(default_factory=CommandManager)
    pending_edits: list = field(default_factory=list)
    edit_count: int = 0
    run_reopen_anchors: dict[str, fitz.Rect] = field(default_factory=dict)
    run_reopen_anchor_sizes: dict[str, float] = field(default_factory=dict)

class PDFModel:
    def __init__(self):
        self._sessions_by_id: dict[str, DocumentSession] = {}
        self._session_ids: list[str] = []
        self._active_session_id: str | None = None
        self._path_to_session_id: dict[str, str] = {}
        self._legacy_doc: fitz.Document | None = None
        self._legacy_original_path: str | None = None
        self._legacy_saved_path: str | None = None
        self._legacy_password: str | None = None
        self._legacy_block_manager: TextBlockManager = TextBlockManager()
        self._legacy_command_manager: CommandManager = CommandManager()
        self._legacy_edit_count: int = 0
        self._legacy_secure_save_required: bool = False
        self._legacy_pending_edits: list = []
        self._legacy_run_reopen_anchors: dict[str, fitz.Rect] = {}
        self._legacy_run_reopen_anchor_sizes: dict[str, float] = {}
        self.temp_dir = None
        # 是否在「存回原檔」時使用增量更新（Incremental Update），以減少對數位簽章與大檔的影響
        self.use_incremental_save: bool = True
        # Text target granularity: "run" or "paragraph" (UI can override on startup).
        self.text_target_mode: str = "run"
        self.tools = ToolManager(self)
        self._audit_report_cache_key: tuple | None = None
        self._audit_report_cache_value: PdfAuditReport | None = None
        self._initialize_temp_dir()
        # 全局 glyph 高度調整（文件推薦，import 後設定一次）
        try:
            fitz.TOOLS.set_small_glyph_heights(True)
            logger.debug("已設定 PyMuPDF TOOLS.set_small_glyph_heights(True)")
        except AttributeError:
            logger.warning("PyMuPDF 版本無 TOOLS 支援，跳過 glyph 調整")

    def _canonicalize_path(self, path: str) -> str:
        """Normalize path for dedupe across tabs (case-insensitive on Windows)."""
        return str(Path(path).resolve()).casefold()

    @staticmethod
    def _safe_exc_message(exc: Exception) -> str:
        try:
            return str(exc)
        except Exception:
            return repr(exc)

    def _active_session(self) -> DocumentSession | None:
        # getattr-guarded so PDFModel.__new__(...) instances (used by some
        # unit tests that bypass __init__) don't AttributeError here.
        active_session_id = getattr(self, "_active_session_id", None)
        if not active_session_id:
            return None
        sessions_by_id = getattr(self, "_sessions_by_id", {})
        return sessions_by_id.get(active_session_id)

    @contextmanager
    def _activate_temporarily(self, session_id: str) -> Iterator[None]:
        previous = self._active_session_id
        if session_id != previous:
            self.activate_session(session_id)
        try:
            yield
        finally:
            if previous and previous in self._sessions_by_id:
                self._active_session_id = previous
            elif self._active_session_id not in self._sessions_by_id:
                self._active_session_id = self._session_ids[0] if self._session_ids else None

    @property
    def session_ids(self) -> list[str]:
        return list(self._session_ids)

    def list_sessions(self) -> list[dict]:
        out = []
        for sid in self._session_ids:
            s = self._sessions_by_id[sid]
            out.append({
                "id": sid,
                "display_name": s.display_name,
                "path": s.original_path,
                "saved_path": s.saved_path,
                "dirty": self.session_has_unsaved_changes(sid),
            })
        return out

    def get_session_id_by_index(self, index: int) -> str | None:
        if index < 0 or index >= len(self._session_ids):
            return None
        return self._session_ids[index]

    def get_active_session_id(self) -> str | None:
        return self._active_session_id

    def get_active_session_index(self) -> int:
        if not self._active_session_id:
            return -1
        try:
            return self._session_ids.index(self._active_session_id)
        except ValueError:
            return -1

    def find_session_by_path(self, path: str) -> str | None:
        canonical = self._canonicalize_path(path)
        return self._path_to_session_id.get(canonical)

    def activate_session(self, session_id: str) -> bool:
        if session_id not in self._sessions_by_id:
            return False
        self._active_session_id = session_id
        return True

    def activate_session_by_index(self, index: int) -> bool:
        sid = self.get_session_id_by_index(index)
        if not sid:
            return False
        return self.activate_session(sid)

    def session_has_unsaved_changes(self, session_id: str) -> bool:
        session = self._sessions_by_id.get(session_id)
        if not session:
            return False
        return session.command_manager.has_pending_changes() or self.tools.has_unsaved_changes(session_id)

    def has_any_unsaved_changes(self) -> bool:
        return any(self.session_has_unsaved_changes(sid) for sid in self._session_ids)

    def get_dirty_session_ids(self) -> list[str]:
        return [sid for sid in self._session_ids if self.session_has_unsaved_changes(sid)]

    def get_session_meta(self, session_id: str) -> dict | None:
        session = self._sessions_by_id.get(session_id)
        if not session:
            return None
        return {
            "id": session_id,
            "display_name": session.display_name,
            "path": session.original_path,
            "saved_path": session.saved_path,
            "dirty": self.session_has_unsaved_changes(session_id),
        }

    def close_session(self, session_id: str) -> bool:
        session = self._sessions_by_id.get(session_id)
        if not session:
            return False
        self.tools.on_session_close(session_id)
        try:
            if session.doc:
                session.doc.close()
        except Exception as e:
            # Some paths (stress/script runners) may already close the document handle.
            # Treat "document closed" as benign cleanup noise.
            msg = str(e).lower()
            if "document closed" in msg:
                logger.debug(f"session 文件已關閉 ({session_id})，略過重複 close")
            else:
                logger.warning(f"關閉 session 文件失敗 ({session_id}): {e}")
        self._sessions_by_id.pop(session_id, None)
        self._session_ids = [sid for sid in self._session_ids if sid != session_id]
        self._path_to_session_id.pop(session.canonical_path, None)
        if self._active_session_id == session_id:
            self._active_session_id = self._session_ids[0] if self._session_ids else None
        return True

    def close_all_sessions(self) -> None:
        for sid in list(getattr(self, "_session_ids", [])):
            self.close_session(sid)

    def save_session_as(self, session_id: str, new_path: str) -> None:
        if session_id not in self._sessions_by_id:
            raise RuntimeError(f"Session 不存在: {session_id}")
        canonical = self._canonicalize_path(new_path)
        existing = self._path_to_session_id.get(canonical)
        if existing and existing != session_id:
            raise RuntimeError("目標路徑已在其他分頁開啟，請改用不同檔名。")
        with self._activate_temporarily(session_id):
            self.save_as(new_path)

    @property
    def doc(self) -> fitz.Document | None:
        session = self._active_session()
        return session.doc if session else self._legacy_doc

    @doc.setter
    def doc(self, value: fitz.Document | None) -> None:
        session = self._active_session()
        if session:
            session.doc = value
        else:
            self._legacy_doc = value

    @property
    def original_path(self) -> str | None:
        session = self._active_session()
        return session.original_path if session else self._legacy_original_path

    @original_path.setter
    def original_path(self, value: str) -> None:
        session = self._active_session()
        if session:
            session.original_path = value
        else:
            self._legacy_original_path = value

    @property
    def saved_path(self) -> str | None:
        session = self._active_session()
        return session.saved_path if session else self._legacy_saved_path

    @saved_path.setter
    def saved_path(self, value: str | None) -> None:
        session = self._active_session()
        if session:
            session.saved_path = value
        else:
            self._legacy_saved_path = value

    @property
    def secure_save_required(self) -> bool:
        session = self._active_session()
        return session.secure_save_required if session else self._legacy_secure_save_required

    @secure_save_required.setter
    def secure_save_required(self, value: bool) -> None:
        session = self._active_session()
        if session:
            session.secure_save_required = bool(value)
        else:
            self._legacy_secure_save_required = bool(value)

    @property
    def password(self) -> str | None:
        session = self._active_session()
        return session.password if session else self._legacy_password

    @password.setter
    def password(self, value: str | None) -> None:
        session = self._active_session()
        if session:
            session.password = value
        else:
            self._legacy_password = value

    @property
    def block_manager(self) -> TextBlockManager:
        session = self._active_session()
        return session.block_manager if session else self._legacy_block_manager

    @block_manager.setter
    def block_manager(self, value: TextBlockManager) -> None:
        session = self._active_session()
        if session:
            session.block_manager = value
        else:
            self._legacy_block_manager = value

    @property
    def command_manager(self) -> CommandManager:
        session = self._active_session()
        return session.command_manager if session else self._legacy_command_manager

    @command_manager.setter
    def command_manager(self, value: CommandManager) -> None:
        session = self._active_session()
        if session:
            session.command_manager = value
        else:
            self._legacy_command_manager = value

    @property
    def edit_count(self) -> int:
        session = self._active_session()
        return session.edit_count if session else self._legacy_edit_count

    @edit_count.setter
    def edit_count(self, value: int) -> None:
        session = self._active_session()
        if session:
            session.edit_count = value
        else:
            self._legacy_edit_count = value

    @property
    def pending_edits(self) -> list:
        session = self._active_session()
        return session.pending_edits if session else self._legacy_pending_edits

    @pending_edits.setter
    def pending_edits(self, value: list) -> None:
        session = self._active_session()
        if session:
            session.pending_edits = value
        else:
            self._legacy_pending_edits = value

    # ── Run reopen anchors ────────────────────────────────────────────────
    # A run-mode edit shrinks/repositions the committed box every commit. To
    # stop that drift cumulating across open→edit→reopen cycles, the FIRST
    # run-mode edit records the original span bbox+size as an anchor, keyed by
    # "{page_idx}::{span_id}". Subsequent edits and the next click resolve
    # against the anchor instead of the freshly-shrunk geometry.

    @property
    def run_reopen_anchors(self) -> dict[str, fitz.Rect]:
        session = self._active_session()
        return session.run_reopen_anchors if session else self._legacy_run_reopen_anchors

    @run_reopen_anchors.setter
    def run_reopen_anchors(self, value: dict[str, fitz.Rect]) -> None:
        session = self._active_session()
        if session:
            session.run_reopen_anchors = value
        else:
            self._legacy_run_reopen_anchors = value

    @property
    def run_reopen_anchor_sizes(self) -> dict[str, float]:
        session = self._active_session()
        return session.run_reopen_anchor_sizes if session else self._legacy_run_reopen_anchor_sizes

    @run_reopen_anchor_sizes.setter
    def run_reopen_anchor_sizes(self, value: dict[str, float]) -> None:
        session = self._active_session()
        if session:
            session.run_reopen_anchor_sizes = value
        else:
            self._legacy_run_reopen_anchor_sizes = value

    @staticmethod
    def _run_reopen_anchor_key(page_idx: int, span_id: str) -> str:
        return f"{int(page_idx)}::{span_id}"

    def _get_run_reopen_anchor_rect(self, page_idx: int, span_id: str | None) -> fitz.Rect | None:
        if not span_id:
            return None
        rect = self.run_reopen_anchors.get(self._run_reopen_anchor_key(page_idx, span_id))
        return fitz.Rect(rect) if rect is not None else None

    def _set_run_reopen_anchor_rect(self, page_idx: int, span_id: str | None, rect: fitz.Rect | None) -> None:
        if not span_id or rect is None:
            return
        self.run_reopen_anchors[self._run_reopen_anchor_key(page_idx, span_id)] = fitz.Rect(rect)

    def _get_run_reopen_anchor_size(self, page_idx: int, span_id: str | None) -> float | None:
        if not span_id:
            return None
        value = self.run_reopen_anchor_sizes.get(self._run_reopen_anchor_key(page_idx, span_id))
        return float(value) if value is not None else None

    def _set_run_reopen_anchor_size(self, page_idx: int, span_id: str | None, size: float | None) -> None:
        if not span_id or size is None:
            return
        self.run_reopen_anchor_sizes[self._run_reopen_anchor_key(page_idx, span_id)] = float(size)

    def _delete_run_reopen_anchor(self, page_idx: int, span_id: str | None) -> None:
        if not span_id:
            return
        key = self._run_reopen_anchor_key(page_idx, span_id)
        self.run_reopen_anchors.pop(key, None)
        self.run_reopen_anchor_sizes.pop(key, None)

    def _iter_run_reopen_anchors_for_page(self, page_idx: int) -> Iterator[tuple[str, fitz.Rect]]:
        prefix = f"{int(page_idx)}::"
        for key, rect in list(self.run_reopen_anchors.items()):
            if not key.startswith(prefix):
                continue
            span_id = key[len(prefix):]
            if not span_id:
                continue
            yield span_id, fitz.Rect(rect)

    def set_text_target_mode(self, mode: str) -> None:
        normalized = (mode or "").strip().lower()
        if normalized not in {"run", "paragraph"}:
            logger.warning("invalid text target mode: %s (keep %s)", mode, self.text_target_mode)
            return
        self.text_target_mode = normalized
        logger.debug("text_target_mode set to %s", self.text_target_mode)

    def _initialize_temp_dir(self):
        """初始化臨時目錄，確保可寫入"""
        try:
            self.temp_dir = tempfile.TemporaryDirectory()
            logger.debug(f"成功創建臨時目錄: {self.temp_dir.name}")
            # 檢查目錄是否可寫入
            test_file = Path(self.temp_dir.name) / "test.txt"
            test_file.touch()
            test_file.unlink()
        except (PermissionError, OSError) as e:
            logger.error(f"無法創建臨時目錄: {e!s}")
            # 後備：使用當前工作目錄下的自訂臨時目錄
            fallback_dir = Path.cwd() / "pdf_temp"
            try:
                fallback_dir.mkdir(exist_ok=True)
                self.temp_dir = tempfile.TemporaryDirectory(dir=str(fallback_dir))
                logger.debug(f"使用後備臨時目錄: {self.temp_dir.name}")
            except Exception as e:
                raise RuntimeError(f"無法創建後備臨時目錄: {e!s}")

    def __del__(self):
        try:
            self.close()
        except AttributeError:
            pass

    @staticmethod
    def _doc_needs_xref_repair(doc: fitz.Document) -> bool:
        """True when MuPDF had to rebuild a damaged cross-reference table on open.

        ``is_repaired`` is set during ``fitz.open()`` itself, so reading it is a
        free flag check — no extra parsing for healthy files.
        """
        return bool(getattr(doc, "is_repaired", False))

    @staticmethod
    def _doc_is_encrypted(doc: fitz.Document) -> bool:
        """True when the *source* document is encrypted (any scheme).

        The ``needs_pass`` / ``is_encrypted`` flags both flip to False once the
        document is authenticated (and an owner-password-only PDF opens with both
        already False), so neither survives to the repair branch. The trailer's
        encryption string in ``doc.metadata`` does survive — it stays populated
        after authentication and is set even for owner-only encryption — so it is
        the reliable signal for "this file was encrypted on disk".

        Reading ``metadata`` is cheap, and this is only consulted on the damaged
        path (gated behind ``is_repaired``), so healthy files never touch it.
        """
        return bool((doc.metadata or {}).get("encryption"))

    def _repair_doc_xref_in_memory(self, doc: fitz.Document) -> fitz.Document:
        """Return a clean in-memory copy of a doc whose xref MuPDF rebuilt on open.

        The in-memory document MuPDF hands back is already usable, but its xref is
        not yet persisted cleanly (and a repaired doc cannot be saved
        incrementally). Round-tripping the bytes with garbage collection produces
        a fresh, internally-consistent xref so later saves don't inherit the
        damage. ``garbage=1`` rebuilds the xref and compacts objects without the
        heavier duplicate-pruning of ``garbage=4`` — full pruning still happens on
        an explicit full save.

        Deliberately **not** ``deflate=True``: re-compressing every stream is the
        dominant cost on large files (≈20 ms/MB) yet adds nothing to a clean-xref
        repair — on already-compressed/image-heavy PDFs it shrinks nothing. Skipping
        it keeps the repair at ≈2.5–5 ms/MB (~1.3–2.6 s worst case at the 512 MB open
        cap vs ~10 s with deflate; a real damaged 47 MB / 402-page file repairs in
        ~240 ms). Stream compression belongs on an explicit save.

        On failure the original (already MuPDF-repaired) doc is returned unchanged
        so opening still succeeds.
        """
        try:
            repaired_bytes = doc.tobytes(garbage=1)
            repaired = fitz.open("pdf", repaired_bytes)
        except Exception as exc:  # noqa: BLE001 - never let auto-repair break open
            logger.warning(
                "開檔自動修復 XREF 失敗，沿用 MuPDF 載入的文件: %s",
                self._safe_exc_message(exc),
            )
            return doc
        try:
            doc.close()
        except Exception:
            pass
        logger.info("開檔偵測到損毀的 XREF 表，已自動於記憶體中重建乾淨的 xref")
        return repaired

    def open_pdf(self, path: str, password: str | None = None, append: bool = False) -> str:
        """
        開啟 PDF 檔案並建立文字塊索引。

        Args:
            path: PDF 檔案路徑
            password: 可選密碼（支援 user password 與 owner/permission password）。
                      PyMuPDF authenticate() 會自動嘗試兩種類型：
                        回傳 2 = user password 認證成功（可讀取內容）
                        回傳 4 = owner password 認證成功（可讀取並修改權限）
                        回傳 6 = 兩者皆成功
        """
        logger.debug(f"嘗試開啟PDF: {path} (append={append})")
        try:
            # 規範化路徑
            src_path = Path(path).resolve()
            canonical_path = self._canonicalize_path(str(src_path))
            if not src_path.exists():
                logger.error(f"原始檔案不存在: {path}")
                raise FileNotFoundError(f"原始檔案不存在: {path}")
            if not src_path.is_file():
                logger.error(f"路徑不是有效檔案: {path}")
                raise ValueError(f"路徑不是有效檔案: {path}")
            # Reject an over-large file before parsing or touching existing sessions.
            _guard_before_open(src_path)
            existing_id = self._path_to_session_id.get(canonical_path)
            if append and existing_id:
                self.activate_session(existing_id)
                return existing_id
            if not append:
                self.close_all_sessions()

            # 直接從原始路徑開啟（以便存檔時可選用增量更新）
            doc = fitz.open(str(src_path))

            # 若 PDF 需要密碼，嘗試認證（支援 user 與 owner password）
            auth_level: int | None = None
            if doc.needs_pass:
                if password is None:
                    raise RuntimeError("document closed or encrypted — 需要密碼")
                auth_result = doc.authenticate(password)
                if auth_result == 0:
                    raise RuntimeError(
                        f"PDF 密碼驗證失敗（authenticate 回傳 0）: {path}"
                    )
                # Retain the auth class (2=user/4=owner/6=both) so the optimize pipeline
                # preserves the source role rather than promoting a user to owner (R5-02).
                auth_level = int(auth_result)
                # auth_result: 2=user, 4=owner, 6=both — 均允許繼續
                logger.debug(
                    f"PDF 密碼驗證成功 (auth_level={auth_result}，"
                    f"2=user/4=owner/6=both): {src_path}"
                )

            # Cap page count once the document is readable (after any auth).
            if doc.page_count > _MAX_PAGES:
                doc.close()
                raise ValueError(f"PDF exceeds page limit ({_MAX_PAGES} pages)")

            # 部分壞損 PDF 可能被 MuPDF 接受但頁數為 0（無法進一步操作）。
            # 這裡以空白文件替代，避免後續流程崩潰。
            if len(doc) == 0:
                logger.warning("PDF 頁數為 0，使用空白頁 fallback: %s", src_path)
                fallback = fitz.open()
                fallback.new_page(width=595.0, height=842.0)
                try:
                    doc.close()
                except Exception:
                    pass
                doc = fallback

            # 自動修復：MuPDF 開檔時會重建損毀的 XREF 表並標記 is_repaired。
            # 此處於記憶體中以 garbage collection round-trip 重建乾淨的 xref，
            # 讓後續儲存不會沿用損毀結構。健康檔案僅讀取一個旗標、不受影響。
            #
            # 但加密檔案除外：tobytes() 會輸出「已解密」的內容，round-trip 會默默
            # 移除密碼/權限保護。加密又損毀的檔案維持 MuPDF 修復後的（仍加密的）
            # 文件即可——之後的完整儲存（encryption=KEEP）會寫出乾淨的 xref 並保留
            # 加密。偵測訊號用 metadata 的加密字串（驗證後仍存在，且涵蓋 owner-only）。
            if self._doc_needs_xref_repair(doc) and not self._doc_is_encrypted(doc):
                doc = self._repair_doc_xref_in_memory(doc)

            logger.debug(f"成功開啟PDF: {src_path}")
            session_id = str(uuid.uuid4())
            session = DocumentSession(
                session_id=session_id,
                canonical_path=canonical_path,
                display_name=src_path.name,
                original_path=str(src_path),
                doc=doc,
                # Kept in-memory so a save that preserves encryption can
                # re-authenticate the reopened handle (see _reopen_doc_after_save).
                password=password,
                auth_level=auth_level,
            )
            self._sessions_by_id[session_id] = session
            self._session_ids.append(session_id)
            self._path_to_session_id[canonical_path] = session_id
            self._active_session_id = session_id
            self.tools.on_session_open(session_id, doc)

            # 文字方塊索引改由 Controller 分批建立（方向 B），開檔不阻塞
            # self.block_manager.build_index(self.doc)
            return session_id
        except PermissionError as e:
            logger.error(f"無權限存取檔案: {e!s}")
            raise PermissionError(f"無權限存取檔案: {e!s}")
        except Exception as e:
            logger.error(f"開啟PDF失敗: {e!s}")
            raise RuntimeError(f"開啟PDF失敗: {e!s}")

    def ensure_page_index_built(self, page_num: int) -> None:
        """
        Ensure the requested page is immediately edit/search-ready.

        Contract:
        - Controller and tools may call this before hit-testing / search / edit flows.
        - We rebuild if the cache is missing OR marked stale (stale is produced by structural ops that shift
          page numbers without eagerly rebuilding the entire document).

        Notes:
        - `page_num` is 1-based to match public UI-facing APIs.
        """
        page_idx = page_num - 1
        if page_idx < 0 or not self.doc or page_idx >= len(self.doc):
            return
        if self.block_manager.page_state(page_idx) in {"missing", "stale"}:
            self.block_manager.rebuild_page(page_idx, self.doc)

    def refresh_structural_indexes(self, affected_pages: list[int]) -> None:
        """
        Refresh page text indices after a document snapshot restore (undo/redo) that may have changed content.

        Why it clears everything:
        - Snapshot restore replaces the whole document bytes, so any cached page indices could be wrong even
          if page counts match.

        Why it doesn't rebuild everything:
        - Full-document rebuild is CPU-heavy and can stall the UI for large PDFs. We rebuild only the pages
          that the controller knows are immediately relevant (`affected_pages`). Other pages are rebuilt
          lazily through `ensure_page_index_built(...)` or background draining.

        `affected_pages` is expected to be 1-based (same as public APIs).
        """
        if not self.doc:
            return
        # Snapshot restore invalidates the old cache wholesale, so rebuild only the hot pages now.
        self.block_manager.clear()
        for page_num in sorted({page for page in affected_pages if 1 <= page <= len(self.doc)}):
            self.block_manager.rebuild_page(page_num - 1, self.doc)

    def _insert_rotate_for_htmlbox(self, rotation: int) -> int:
        """
        insert_htmlbox(rotate=...) 的旋轉方向與 PDF 文字 dir 相反（順時針 vs 逆時針），
        垂直文字若直接傳 90 會變成 180° 反轉。改傳 (360 - rotation) % 360 以對齊原檔方向。
        """
        return (360 - rotation) % 360

    def _vertical_html_rect(self, base_rect: fitz.Rect, text: str, size: float, font_name: str, page_rect: fitz.Rect, anchor_right: bool = True) -> fitz.Rect:
        """
        垂直文字：估算「需要的 x 方向寬度（列數 × 行高）」。
        anchor_right=True（預設）：固定右緣 x1，向左擴展（x0 往左）→ 左側文字需左移。
        anchor_right=False：固定左緣 x0，向右擴展（x1 往右）→ 右側文字需右移。
        不超出頁面邊界。
        """
        line_gap = 1.1
        try:
            font_obj = fitz.Font(font_name)
            line_height = max(1.0, (font_obj.ascender - font_obj.descender) * size * line_gap)
        except Exception:
            line_height = max(1.0, size * line_gap)
        rect_height = max(base_rect.height, line_height)
        chars_per_col = max(1, int(rect_height / line_height))
        logical_cols = 1 + text.count('\n')
        chars_no_nl = len(text.replace('\n', ''))
        wrap_cols = math.ceil(max(1, chars_no_nl) / chars_per_col) if chars_no_nl else 0
        cols = max(logical_cols, wrap_cols)
        needed_width = max(base_rect.width, cols * line_height)
        max_width = max(1.0, page_rect.width * 0.98)
        needed_width = min(needed_width, max_width)

        if anchor_right:
            # 固定 x1，向左擴展
            new_x1 = base_rect.x1
            new_x0 = new_x1 - needed_width
            if new_x0 < page_rect.x0:
                new_x0 = page_rect.x0
                new_x1 = min(new_x0 + needed_width, page_rect.x1)
        else:
            # 固定 x0，向右擴展
            new_x0 = base_rect.x0
            new_x1 = new_x0 + needed_width
            if new_x1 > page_rect.x1:
                new_x1 = page_rect.x1
                new_x0 = max(new_x1 - needed_width, page_rect.x0)
        # 夾緊 y 於頁面內，避免超出頁面
        y0 = max(base_rect.y0, page_rect.y0)
        y1 = min(base_rect.y1, page_rect.y1)
        if y0 >= y1:
            y1 = y0 + max(1.0, base_rect.height)
        return fitz.Rect(new_x0, y0, new_x1, min(y1, page_rect.y1))

    def _visual_rect_to_unrotated_rect(self, page: fitz.Page, visual_rect: fitz.Rect) -> fitz.Rect:
        """Convert a visual-space page rect to unrotated page coordinates."""
        corners = [
            fitz.Point(visual_rect.x0, visual_rect.y0),
            fitz.Point(visual_rect.x1, visual_rect.y0),
            fitz.Point(visual_rect.x1, visual_rect.y1),
            fitz.Point(visual_rect.x0, visual_rect.y1),
        ]
        mapped = [pt * page.derotation_matrix for pt in corners]
        return rect_from_points(mapped)

    def _unrotated_page_rect(self, page: fitz.Page) -> fitz.Rect:
        """
        Return page bounds in unrotated coordinates.
        For rotated pages, page.rect is visual-space (w/h swapped on 90/270), so
        insertion geometry derived via derotation_matrix must clamp against cropbox.
        """
        try:
            crop = fitz.Rect(page.cropbox)
            if crop.width > 0 and crop.height > 0:
                return crop
        except Exception:
            pass
        try:
            media = fitz.Rect(page.mediabox)
            if media.width > 0 and media.height > 0:
                return media
        except Exception:
            pass
        return fitz.Rect(page.rect)

    def _y_overlaps(self, rect_a: fitz.Rect, rect_b: fitz.Rect) -> bool:
        return not (rect_a.y1 <= rect_b.y0 or rect_b.y1 <= rect_a.y0)

    def _shift_rect_left(self, rect: fitz.Rect, target_right_x0: float, min_gap: float, page_rect: fitz.Rect) -> fitz.Rect:
        """將矩形左移，使右緣不超過 target_right_x0 - min_gap。若會移出頁面則不移動。"""
        width = rect.width
        new_x1 = min(rect.x1, target_right_x0 - min_gap)
        shift = rect.x1 - new_x1
        if shift <= 0:
            return rect
        new_x0 = rect.x0 - shift
        new_x1 = new_x0 + width
        if new_x0 < page_rect.x0 or new_x1 > page_rect.x1:
            return rect
        return fitz.Rect(new_x0, rect.y0, new_x1, rect.y1)

    def _shift_rect_right(self, rect: fitz.Rect, target_left_x1: float, min_gap: float, page_rect: fitz.Rect) -> fitz.Rect:
        """將矩形右移，使左緣至少為 target_left_x1 + min_gap。若會移出頁面則不移動。"""
        width = rect.width
        new_x0 = max(rect.x0, target_left_x1 + min_gap)
        if new_x0 <= rect.x0:
            return rect
        new_x1 = new_x0 + width
        if new_x0 < page_rect.x0 or new_x1 > page_rect.x1:
            return rect
        return fitz.Rect(new_x0, rect.y0, new_x1, rect.y1)

    @staticmethod
    def _starts_bullet_item(text: str) -> bool:
        stripped = (text or "").strip()
        if not stripped:
            return False
        if stripped.startswith(_BULLET_PREFIXES):
            return True
        return bool(_RE_NUMBERED_BULLET.match(stripped))

    def _compose_block_text_for_hit(self, block: dict) -> str:
        """
        Build editable text for fallback point-hit extraction.
        Wrapped lines are joined with spaces, while bullets / large visual gaps keep line breaks.
        """
        lines = block.get("lines", []) or []
        if not lines:
            return ""

        line_texts: list[str] = []
        line_boxes: list[fitz.Rect] = []
        for line in lines:
            parts = [
                (span.get("text", "") or "").strip()
                for span in (line.get("spans", []) or [])
                if (span.get("text", "") or "").strip()
            ]
            if not parts:
                continue
            line_texts.append(" ".join(parts))
            bbox = line.get("bbox")
            if bbox is not None:
                line_boxes.append(fitz.Rect(bbox))
                continue
            spans = line.get("spans", []) or []
            if spans:
                line_box = fitz.Rect(spans[0].get("bbox", (0, 0, 0, 0)))
                for span in spans[1:]:
                    line_box.include_rect(fitz.Rect(span.get("bbox", (0, 0, 0, 0))))
                line_boxes.append(line_box)
            else:
                line_boxes.append(fitz.Rect(0, 0, 0, 0))

        if not line_texts:
            return ""

        composed: list[str] = []
        for idx, line_text in enumerate(line_texts):
            if idx == 0:
                composed.append(line_text)
                continue
            prev_box = line_boxes[idx - 1]
            curr_box = line_boxes[idx]
            prev_height = max(prev_box.height, 0.0)
            gap = curr_box.y0 - prev_box.y1
            if self._starts_bullet_item(line_text) or (prev_height > 0 and gap > prev_height * 0.5):
                composed.append("\n")
            elif composed and not composed[-1].endswith((" ", "\n", "-")):
                composed.append(" ")
            composed.append(line_text)
        return "".join(composed).strip()

    def _resolve_paragraph_candidate(
        self,
        page_idx: int,
        probe_rect: fitz.Rect,
        original_text: str | None,
        preferred_run_id: str | None = None,
    ) -> EditableParagraph | None:
        """Resolve the best paragraph target by geometry + text similarity.

        This is used to recover from stale run IDs after page rebuilds.
        """
        paragraphs = self.block_manager.get_paragraphs(page_idx)
        if not paragraphs:
            return None

        expanded = fitz.Rect(
            probe_rect.x0 - 1.0,
            probe_rect.y0 - 1.0,
            probe_rect.x1 + 1.0,
            probe_rect.y1 + 1.0,
        )
        candidates = [
            para
            for para in paragraphs
            if fitz.Rect(para.bbox).intersects(expanded)
        ]
        if not candidates:
            candidates = paragraphs

        has_probe_text = bool(normalize_text(original_text or ""))
        best_para: EditableParagraph | None = None
        best_key: tuple[float, ...] | None = None
        key: tuple[float, ...]

        for para in candidates:
            para_rect = fitz.Rect(para.bbox)
            overlap_score = rect_overlap_ratio(para_rect, probe_rect)
            text_score = (
                normalized_similarity(original_text or "", para.text)
                if has_probe_text
                else 0.0
            )
            preferred_score = 1.0 if preferred_run_id and preferred_run_id in para.run_ids else 0.0

            if has_probe_text:
                key = (
                    round(text_score, 6),
                    round(overlap_score, 6),
                    preferred_score,
                    -abs(para_rect.y0 - probe_rect.y0),
                )
            else:
                key = (
                    round(overlap_score, 6),
                    preferred_score,
                    -abs(para_rect.y0 - probe_rect.y0),
                )

            if best_key is None or key > best_key:
                best_key = key
                best_para = para

        return best_para

    def _text_fits_in_rect(self, page: fitz.Page, rect: fitz.Rect, expected_text: str) -> bool:
        extracted = page.get_text("text", clip=rect)
        return normalize_text(expected_text) in normalize_text(extracted)

    def _binary_shrink_height(self, page: fitz.Page, rect: fitz.Rect, expected_text: str, iterations: int = 7, padding: float = 4.0, min_y1: float | None = None) -> fitz.Rect:
        """
        先用全頁高度 rect 渲染，再二分縮減 y1 找到最小可用高度。
        y0 固定，最後加 padding。
        [優化 11] 早期結束：若範圍已足夠小則提前返回，減少不必要的 get_text 呼叫
        """
        page_rect = page.rect
        low = rect.y1 if min_y1 is None else max(rect.y0, min_y1)
        high = page_rect.y1
        if low > high:
            low = high
        best_y1 = high

        for _ in range(iterations):
            if high - low < 2.0:  # [優化 11] 範圍小於 2pt 時提前結束
                break
            mid = (low + high) / 2.0
            test_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, mid)
            if self._text_fits_in_rect(page, test_rect, expected_text):
                best_y1 = mid
                high = mid
            else:
                low = mid

        best_y1 = min(page_rect.y1, best_y1 + padding)
        return fitz.Rect(rect.x0, rect.y0, rect.x1, best_y1)

    def _calc_vertical_padding(self, size: float) -> float:
        return max(4.0, float(size) * 0.8) # 0.2 還是會被裁切到，我先試 0.8 是可行的，待有需要再測試能否進一步減少

    def close(self):
        logger.debug("關閉PDF並清理臨時目錄")
        self.close_all_sessions()
        self._legacy_doc = None
        self._legacy_original_path = None
        self._legacy_saved_path = None
        legacy_block_manager = getattr(self, "_legacy_block_manager", None)
        if legacy_block_manager is not None:
            legacy_block_manager.clear()
        legacy_command_manager = getattr(self, "_legacy_command_manager", None)
        if legacy_command_manager is not None:
            legacy_command_manager.clear()
        legacy_pending_edits = getattr(self, "_legacy_pending_edits", None)
        if isinstance(legacy_pending_edits, list):
            legacy_pending_edits.clear()
        self._legacy_edit_count = 0
        if getattr(self, "temp_dir", None):
            self.temp_dir.cleanup()
            logger.debug("臨時目錄已清理")
            self.temp_dir = None

    def delete_pages(
        self,
        pages: list[int],
        *,
        transaction_snapshot: bytes | None = None,
    ) -> list[int]:
        """
        Delete pages (1-based) and return the actual deleted pages (1-based, sorted).

        Source of truth rule:
        - Controller must use this return value for UI messaging and SnapshotCommand metadata. The input can
          be dirty (out-of-range, duplicates, non-int), and the model decides the actual effect.

        Indexing rule:
        - Do not rebuild all pages. Keep unaffected cache entries, mark shifted survivors as stale, and make
          a nearby anchor page immediately usable for compatibility with existing callers.
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")

        max_page = len(self.doc)
        normalized: list[int] = []
        for value in pages or []:
            if isinstance(value, bool):
                continue
            try:
                page_num = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= page_num <= max_page:
                normalized.append(page_num)

        actual_deleted_pages = sorted(set(normalized))
        if not actual_deleted_pages:
            return []
        deleted_page_idxs = [page_num - 1 for page_num in actual_deleted_pages]
        before = transaction_snapshot if transaction_snapshot is not None else self._capture_doc_snapshot()
        pending_before = list(self.pending_edits)
        edit_count_before = self.edit_count
        secure_before = self.secure_save_required
        try:
            for page_num in sorted(actual_deleted_pages, reverse=True):
                self.doc.delete_page(page_num - 1)
            # Preserve unaffected cache entries; shifted survivors become stale until demanded.
            self.block_manager.shift_after_delete(deleted_page_idxs)
            if self.doc and deleted_page_idxs:
                # Keep the page nearest the deletion immediately usable for existing callers.
                anchor_idx = min(deleted_page_idxs[0], len(self.doc) - 1)
                if anchor_idx >= 0:
                    self.block_manager.rebuild_page(anchor_idx, self.doc)
        except Exception:
            self._restore_doc_from_snapshot(before)
            self.pending_edits = pending_before
            self.edit_count = edit_count_before
            self.secure_save_required = secure_before
            self.block_manager.build_index(self.doc)
            raise
        self.secure_save_required = True
        return actual_deleted_pages

    def rotate_pages(self, pages: list[int], degrees: int) -> list[int]:
        """
        Rotate pages and return the actual rotated pages (1-based, sorted).

        Controller input can be dirty; model validates and becomes the source of truth for undo metadata.
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")
        try:
            normalized_degrees = int(degrees) % 360
        except (TypeError, ValueError):
            normalized_degrees = 0
        if normalized_degrees == 0:
            return []

        max_page = len(self.doc)
        normalized: list[int] = []
        for value in pages or []:
            if isinstance(value, bool):
                continue
            try:
                page_num = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= page_num <= max_page:
                normalized.append(page_num)

        actual_pages = sorted(set(normalized))
        for page_num in actual_pages:
            page = self.doc[page_num - 1]
            page.set_rotation((page.rotation + normalized_degrees) % 360)
        for page_num in actual_pages:
            self.block_manager.rebuild_page(page_num - 1, self.doc)
        return actual_pages

    @staticmethod
    def _normalize_image_format(fmt: str) -> str:
        value = (fmt or "").lower().lstrip(".")
        if value in ("jpg", "jpeg"):
            return "jpg"
        if value == "png":
            return "png"
        if value in ("tif", "tiff"):
            return "tiff"
        return ""

    def export_pages(
        self,
        pages: list[int],
        output_path: str,
        as_image: bool = False,
        dpi: int = 300,
        image_format: str = "png",
    ):
        # typed bind; callers guarantee an open doc here (export path) - runtime behavior identical if None
        doc: fitz.Document = self.doc
        output_target = Path(output_path)
        base_path = output_target.with_suffix('')
        logger.debug(
            f"匯出頁面: 路徑={output_path}, as_image={as_image}, dpi={dpi}, image_format={image_format}"
        )

        if as_image:
            normalized_format = self._normalize_image_format(image_format)
            if not normalized_format:
                normalized_format = self._normalize_image_format(output_target.suffix)
            if not normalized_format:
                normalized_format = "png"
            raw_suffix = output_target.suffix.lower().lstrip(".")
            # Keep user-typed suffix style for output names (e.g. .tif vs .tiff).
            write_ext = raw_suffix if self._normalize_image_format(raw_suffix) else normalized_format
            dpi_value = max(int(round(float(dpi))), 1)
            scale = dpi_value / 72.0

            for page_num in pages:
                if not (1 <= page_num <= len(doc)):
                    logger.warning(f"匯出影像時略過無效頁碼: {page_num}")
                    continue
                safe_scale = _safe_render_scale(doc[page_num - 1], scale)
                pix = self.get_page_pixmap(page_num, scale=safe_scale)
                # Persist resolution metadata so image "DPI" matches user selection.
                pix.set_dpi(dpi_value, dpi_value)
                if len(pages) == 1:
                    target_path = output_target if output_target.suffix else output_target.with_suffix(f".{write_ext}")
                else:
                    # Multi-page export uses page-number suffix to avoid collisions.
                    target_path = Path(f"{base_path}_p{page_num}.{write_ext}")
                if normalized_format == "tiff":
                    # PyMuPDF Pixmap.save does not support TIFF; use Pillow-backed path.
                    try:
                        pix.pil_save(str(target_path), format="TIFF")
                    except Exception as exc:
                        raise RuntimeError(
                            "匯出 TIFF 失敗，請確認已安裝 Pillow (pip install Pillow)"
                        ) from exc
                else:
                    pix.save(str(target_path))
                logger.debug(f"匯出影像: 頁面 {page_num} 至 {target_path}")
            return

        new_doc = fitz.open()
        try:
            for page_num in pages:
                if 1 <= page_num <= len(doc):
                    new_doc.insert_pdf(doc, from_page=page_num - 1, to_page=page_num - 1)
                    logger.debug(f"匯出PDF頁面: {page_num}")
                else:
                    logger.warning(f"匯出PDF時略過無效頁碼: {page_num}")
            self.save_external_document(new_doc, output_path)
        finally:
            new_doc.close()

    def insert_blank_page(self, position: int) -> list[int]:
        """
        Insert one blank page and return the actual inserted page number (1-based).

        Source of truth rule:
        - Controller must use the returned page number (position can be dirty/out-of-range).

        Indexing rule:
        - The inserted page must be immediately editable/search-ready, but the shifted suffix can be marked
          stale and rebuilt lazily.
        
        Args:
            position: 插入位置（1-based），例如 1 表示在第一頁之前，2 表示在第一頁之後
                     如果 position > 總頁數，則插入到最後
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")

        try:
            pos_value = int(position)
        except (TypeError, ValueError):
            pos_value = 1

        # 獲取當前第一頁的尺寸作為新頁面的尺寸
        if len(self.doc) > 0:
            first_page = self.doc[0]
            page_rect = first_page.rect
            width = page_rect.width
            height = page_rect.height
        else:
            # 如果文件為空，使用標準 A4 尺寸
            width = 595  # A4 width in points
            height = 842  # A4 height in points

        # 轉換為 0-based 索引，並確保不超出範圍
        insert_at = min(pos_value - 1, len(self.doc))
        if insert_at < 0:
            insert_at = 0

        # 插入空白頁面
        self.doc.new_page(insert_at, width=width, height=height)
        logger.debug(f"在位置 {insert_at + 1} 插入空白頁面，尺寸: {width}x{height}")
        # New pages must be editable right away, but later pages can be rebuilt lazily.
        self.block_manager.shift_after_insert(insert_at, 1)
        self.block_manager.rebuild_page(insert_at, self.doc)
        return [insert_at + 1]

    def insert_pages_from_file(
        self,
        source_file: str,
        source_pages: list[int],
        position: int,
        password: str | None = None,
    ) -> list[int]:
        """
        Insert pages from another PDF and return the actual inserted page numbers (1-based, ascending).

        Source of truth rule:
        - Controller must use the returned positions for SnapshotCommand metadata and UI. `source_pages` and
          `position` can be dirty; the model validates and applies the real operation.

        Indexing rule:
        - Imported pages are rebuilt immediately for edit hit-testing; shifted suffix pages are marked stale
          and rebuilt lazily/background.
        
        Args:
            source_file: 來源PDF檔案路徑
            source_pages: 要插入的來源頁碼列表（1-based）
            position: 插入位置（1-based），例如 1 表示在第一頁之前
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")

        source_path = Path(source_file)
        if not source_path.exists():
            raise FileNotFoundError(f"來源檔案不存在: {source_file}")

        try:
            try:
                pos_value = int(position)
            except (TypeError, ValueError):
                pos_value = 1

            # 開啟來源PDF（套用 foreign-doc 資源防護：大小/頁數/加密）
            source_doc = _guard_foreign_doc(source_path, password=password)

            # 轉換為 0-based 索引
            insert_at = min(pos_value - 1, len(self.doc))
            if insert_at < 0:
                insert_at = 0

            max_source = len(source_doc)
            normalized_source: list[int] = []
            for value in source_pages or []:
                if isinstance(value, bool):
                    continue
                try:
                    page_num = int(value)
                except (TypeError, ValueError):
                    continue
                if 1 <= page_num <= max_source:
                    normalized_source.append(page_num)
                else:
                    logger.warning(f"來源檔案頁碼 {value} 超出範圍（總頁數: {max_source}）")

            # Sort and de-dup BEFORE insertion so invalid pages do not distort positional offsets.
            actual_source_pages = sorted(set(normalized_source))

            # Post-merge invariant: the combined document must stay under _MAX_PAGES.
            if len(self.doc) + len(actual_source_pages) > _MAX_PAGES:
                source_doc.close()
                raise ValueError(f"Merged document would exceed page limit ({_MAX_PAGES} pages)")

            # Group the sorted/deduped pages into contiguous runs so each run is
            # one insert_pdf call instead of one call per page.
            runs: list[list[int]] = []
            for page_num in actual_source_pages:
                if runs and page_num == runs[-1][1] + 1:
                    runs[-1][1] = page_num
                else:
                    runs.append([page_num, page_num])

            inserted_positions: list[int] = []
            try:
                offset = 0
                for from_pg, to_pg in runs:
                    self.doc.insert_pdf(
                        source_doc,
                        from_page=from_pg - 1,
                        to_page=to_pg - 1,
                        start_at=insert_at + offset,
                    )
                    logger.debug(
                        f"從 {source_file} 插入頁面 {from_pg}-{to_pg} 到位置 {insert_at + offset + 1}"
                    )
                    offset += to_pg - from_pg + 1
                inserted_positions = list(range(insert_at + 1, insert_at + len(actual_source_pages) + 1))
            finally:
                source_doc.close()

            if inserted_positions:
                # Imported pages are rebuilt immediately; the shifted suffix drains in the background.
                self.block_manager.shift_after_insert(insert_at, len(inserted_positions))
                for page_idx in range(insert_at, insert_at + len(inserted_positions)):
                    self.block_manager.rebuild_page(page_idx, self.doc)
            return inserted_positions

        except Exception as e:
            logger.error(f"從檔案插入頁面失敗: {e}")
            raise RuntimeError(f"從檔案插入頁面失敗: {e}")

    def open_insert_source(self, path: str, password: str | None = None) -> dict:
        src_path = Path(path).resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"來源檔案不存在: {path}")
        if not src_path.is_file():
            raise ValueError(f"路徑不是有效檔案: {path}")

        doc = _guard_foreign_doc(src_path, password=password)
        try:
            if len(doc) == 0:
                raise RuntimeError(f"無法讀取來源檔案: {path}")
            return {
                "path": str(src_path),
                "display_name": src_path.name,
                "page_count": len(doc),
                "password": password,
            }
        finally:
            doc.close()

    def compose_merged_document(self, ordered_sources: list[dict]) -> fitz.Document:
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")

        merged = fitz.open()
        current_snapshot = self._capture_doc_snapshot()

        for source in ordered_sources or []:
            source_kind = (source or {}).get("source_kind")
            if source_kind == "current":
                current_doc = fitz.open("pdf", current_snapshot)
                try:
                    merged.insert_pdf(current_doc)
                finally:
                    current_doc.close()
                continue

            if source_kind != "file":
                continue

            path = (source or {}).get("path")
            if not path:
                continue

            password = (source or {}).get("password")
            # Route foreign opens through the resource guard (size/page caps +
            # auth) instead of a bare fitz.open — same auth errors, plus the
            # _MAX_PDF_BYTES/_MAX_PAGES limits a merge previously bypassed.
            file_doc = _guard_foreign_doc(Path(str(path)), password=password)
            try:
                merged.insert_pdf(file_doc)
            finally:
                file_doc.close()

        return merged

    def open_merge_source(self, path: str, password: str | None = None) -> dict:
        src_path = Path(path).resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"來源檔案不存在: {path}")
        if not src_path.is_file():
            raise ValueError(f"路徑不是有效檔案: {path}")

        # Mirror open_insert_source: the resource guard applies the size/page
        # caps + auth (replacing the bare fitz.open + inline auth here).
        doc = _guard_foreign_doc(src_path, password=password)
        try:
            if len(doc) == 0:
                raise RuntimeError(f"無法讀取來源檔案: {path}")

            return {
                "path": str(src_path),
                "display_name": src_path.name,
                "password": password,
            }
        finally:
            doc.close()

    def get_page_pixmap(
        self,
        page_num: int,
        scale: float = 1.0,
        colorspace: fitz.Colorspace | None = None,
    ) -> fitz.Pixmap:
        return self.tools.render_page_pixmap(
            page_num,
            scale=scale,
            annots=True,
            purpose="view",
            colorspace=colorspace,
        )

    def get_page_snapshot(
        self,
        page_num: int,
        scale: float = 1.0,
        colorspace: fitz.Colorspace | None = None,
    ) -> fitz.Pixmap:
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"無效頁碼: {page_num}")
        return self.tools.render_page_pixmap(
            page_num,
            scale=scale,
            annots=True,
            purpose="snapshot",
            colorspace=colorspace,
        )

    def get_thumbnail(self, page_num: int, colorspace: fitz.Colorspace | None = None) -> fitz.Pixmap:
        return self.get_page_pixmap(page_num, scale=0.2, colorspace=colorspace)

    def build_print_snapshot(self, dest: Path) -> None:
        """Write the print-input PDF directly to ``dest`` (avoids a full in-memory copy)."""
        self.tools.build_print_snapshot(dest)

    def get_print_watermarks(self) -> list[dict]:
        return json.loads(json.dumps(self.tools.watermark.get_watermarks(), ensure_ascii=False))

    def get_text_info_at_point(
        self,
        page_num: int,
        point: fitz.Point,
        allow_fallback: bool = True,
    ) -> TextHit | None:
        """Return topmost editable run info at point using stable run/span identity."""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return None

        page_idx = page_num - 1
        self.ensure_page_index_built(page_num)
        mode = (self.text_target_mode or "run").lower()

        spans = self.block_manager.get_runs(page_idx)

        # Anchor-first resolution: if the click lands inside a remembered
        # run-reopen anchor region, hit-test against the anchor (not the
        # shrunk live bbox) so reopening the same textbox stays stable. The
        # span_id can change across rebuilds, so re-bind a stale anchor to the
        # nearest live run by center distance.
        anchored_hit: EditableSpan | None = None
        anchored_rect: fitz.Rect | None = None
        anchored_size: float | None = None
        anchored_distance_sq: float | None = None
        for anchor_span_id, anchor_rect in self._iter_run_reopen_anchors_for_page(page_idx):
            if point not in anchor_rect:
                continue
            anchor_run = self.block_manager.find_run_by_id(page_idx, anchor_span_id)
            if anchor_run is None and spans:
                anchor_cx = float(anchor_rect.x0 + (anchor_rect.width / 2.0))
                anchor_cy = float(anchor_rect.y0 + (anchor_rect.height / 2.0))
                anchor_run = min(
                    spans,
                    key=lambda span: (
                        (float(span.bbox.x0 + (span.bbox.width / 2.0)) - anchor_cx) ** 2
                        + (float(span.bbox.y0 + (span.bbox.height / 2.0)) - anchor_cy) ** 2
                    ),
                )
                self._set_run_reopen_anchor_rect(page_idx, anchor_run.span_id, anchor_rect)
                old_size = self._get_run_reopen_anchor_size(page_idx, anchor_span_id)
                self._set_run_reopen_anchor_size(
                    page_idx,
                    anchor_run.span_id,
                    old_size if old_size is not None else float(anchor_run.size),
                )
            if anchor_run is None:
                continue
            center_x = float(anchor_rect.x0 + (anchor_rect.width / 2.0))
            center_y = float(anchor_rect.y0 + (anchor_rect.height / 2.0))
            distance_sq = ((float(point.x) - center_x) ** 2) + ((float(point.y) - center_y) ** 2)
            if anchored_hit is None or anchored_distance_sq is None or distance_sq < anchored_distance_sq:
                anchored_hit = anchor_run
                anchored_rect = fitz.Rect(anchor_rect)
                anchored_size = self._get_run_reopen_anchor_size(page_idx, anchor_span_id)
                if anchored_size is None:
                    anchored_size = float(anchor_run.size)
                anchored_distance_sq = distance_sq

        hit_spans = [anchored_hit] if anchored_hit is not None else [s for s in spans if point in fitz.Rect(s.bbox)]
        if hit_spans:
            target = hit_spans[-1]  # Topmost = last extracted/drawn.
            reopen_anchor_rect = (
                fitz.Rect(anchored_rect)
                if anchored_rect is not None
                else self._get_run_reopen_anchor_rect(page_idx, target.span_id)
            )
            if mode == "paragraph":
                para = self.block_manager.find_paragraph_for_run(page_idx, target.span_id)
                if para is not None:
                    para_run_ids = set(para.run_ids)
                    cluster = [span for span in spans if span.span_id in para_run_ids]
                    if not cluster:
                        cluster = self.block_manager.find_overlapping_runs(page_idx, para.bbox, tol=0.5)
                    return TextHit(
                        target_span_id=target.span_id,
                        target_bbox=fitz.Rect(para.bbox),
                        target_text=para.text,
                        font=para.font,
                        size=float(para.size),
                        color=tuple(para.color),
                        rotation=int(para.rotation),
                        cluster_span_ids=[s.span_id for s in cluster],
                        target_mode="paragraph",
                        target_paragraph_id=para.paragraph_id,
                    )
            cluster = self.block_manager.find_overlapping_runs(page_idx, target.bbox, tol=0.5)
            return TextHit(
                target_span_id=target.span_id,
                target_bbox=fitz.Rect(reopen_anchor_rect if reopen_anchor_rect is not None else target.bbox),
                target_text=target.text,
                font=target.font,
                size=float(anchored_size if anchored_size is not None else target.size),
                color=tuple(target.color),
                rotation=int(target.rotation),
                cluster_span_ids=[s.span_id for s in cluster],
                target_mode="run",
            )

        if not allow_fallback:
            return None

        # Backward-compatible fallback if span extraction misses the point.
        page = self.doc[page_idx]
        blocks = page.get_text("dict", flags=0)["blocks"]
        for block_idx, block in enumerate(blocks):
            if block.get("type") != 0:
                continue
            rect = fitz.Rect(block["bbox"])
            if point not in rect:
                continue

            font_name = "helv"
            font_size = 12.0
            color_int = 0
            rotation = 0

            if block.get("lines") and block["lines"][0].get("spans"):
                first_span = block["lines"][0]["spans"][0]
                font_name = first_span.get("font", "helv")
                font_size = float(first_span.get("size", 12.0))
                color_int = int(first_span.get("color", 0))
            if block.get("lines") and block["lines"][0].get("dir") is not None:
                rotation = rotation_degrees_from_dir(block["lines"][0]["dir"])

            rgb_int = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
            color = tuple(c / 255.0 for c in rgb_int)
            text_content = self._compose_block_text_for_hit(block)
            fallback_span_id = f"p{page_idx}_b{block_idx}_l0_s0"
            return TextHit(
                target_span_id=fallback_span_id,
                target_bbox=rect,
                target_text=text_content,
                font=font_name,
                size=font_size,
                color=color,
                rotation=rotation,
                cluster_span_ids=[fallback_span_id],
                target_mode=mode if mode in {"run", "paragraph"} else "run",
            )
        return None

    def get_text_in_rect(self, page_num: int, rect: fitz.Rect) -> str:
        """Extract plain text in a rectangle for browse-mode copy."""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return ""
        text, _ = self.get_text_selection_snapshot(page_num, rect)
        return text

    def get_text_selection_bounds(self, page_num: int, rect: fitz.Rect) -> fitz.Rect | None:
        """Return browse-mode selection bounds snapped to whole visual lines."""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return None
        _, bounds = self.get_text_selection_snapshot(page_num, rect)
        return fitz.Rect(bounds) if bounds is not None else None

    def get_text_selection_snapshot(self, page_num: int, rect: fitz.Rect) -> tuple[str, fitz.Rect | None]:
        """Resolve browse-mode text selection by snapping intersected clips to full line units."""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return "", None

        def _extract_line_text(line_dict: dict) -> str:
            spans_data = line_dict.get("spans") or []
            chunks: list[str] = []
            for span_dict in spans_data:
                span_text = span_dict.get("text")
                if span_text is None:
                    span_text = "".join((char.get("c") or "") for char in (span_dict.get("chars") or []))
                chunks.append(span_text)
            return "".join(chunks).strip()

        page_idx = page_num - 1
        page = self.doc[page_idx]
        clipped = clamp_rect_to_page(fitz.Rect(rect), page.rect)
        self.ensure_page_index_built(page_num)

        spans = self.block_manager.get_runs(page_idx)
        if not spans:
            text = (page.get_text("text", clip=clipped, sort=True) or "").strip()
            return text, (fitz.Rect(clipped) if text else None)

        selected_keys: set[tuple[int, int]] = set()
        grouped_spans: dict[tuple[int, int], list] = {}
        for span in spans:
            key = (int(span.block_idx), int(span.line_idx))
            grouped_spans.setdefault(key, []).append(span)
            if fitz.Rect(span.bbox).intersects(clipped):
                selected_keys.add(key)

        if not selected_keys:
            return "", None

        raw_blocks = page.get_text("dict", flags=0).get("blocks", [])
        line_texts: list[str] = []
        line_rects: list[fitz.Rect] = []
        for key in sorted(selected_keys):
            line_spans = sorted(
                grouped_spans.get(key, []),
                key=lambda item: (int(item.span_idx), float(item.bbox.x0), float(item.bbox.y0)),
            )
            block_idx, line_idx = key
            raw_line = None
            if 0 <= block_idx < len(raw_blocks):
                block_lines = raw_blocks[block_idx].get("lines") or []
                if 0 <= line_idx < len(block_lines):
                    raw_line = block_lines[line_idx]

            if raw_line is not None:
                line_text = _extract_line_text(raw_line)
                line_bbox = fitz.Rect(raw_line.get("bbox") or line_spans[0].bbox)
            else:
                line_text = " ".join((span.text or "").strip() for span in line_spans if (span.text or "").strip()).strip()
                x0 = min(float(span.bbox.x0) for span in line_spans)
                y0 = min(float(span.bbox.y0) for span in line_spans)
                x1 = max(float(span.bbox.x1) for span in line_spans)
                y1 = max(float(span.bbox.y1) for span in line_spans)
                line_bbox = fitz.Rect(x0, y0, x1, y1)

            if not line_text:
                continue
            line_texts.append(line_text)
            line_rects.append(line_bbox)

        if not line_texts or not line_rects:
            return "", None

        bounds = fitz.Rect(line_rects[0])
        for line_rect in line_rects[1:]:
            bounds.include_rect(line_rect)
        return "\n".join(line_texts).strip(), bounds

    def get_text_selection_snapshot_from_run(
        self,
        page_num: int,
        start_span_id: str,
        end_point: fitz.Point,
    ) -> tuple[str, fitz.Rect | None]:
        """Resolve browse-mode selection from a start run to an end point on the same page."""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return "", None

        page_idx = page_num - 1
        self.ensure_page_index_built(page_num)
        runs = self.block_manager.get_runs(page_idx)
        if not runs:
            return "", None

        start_run = self.block_manager.find_run_by_id(page_idx, start_span_id)
        if start_run is None:
            return "", None

        def _distance_sq_to_rect(point: fitz.Point, rect: fitz.Rect) -> float:
            dx = 0.0
            if point.x < rect.x0:
                dx = rect.x0 - point.x
            elif point.x > rect.x1:
                dx = point.x - rect.x1
            dy = 0.0
            if point.y < rect.y0:
                dy = rect.y0 - point.y
            elif point.y > rect.y1:
                dy = point.y - rect.y1
            return dx * dx + dy * dy

        end_run = self.get_text_info_at_point(page_num, end_point, allow_fallback=False)
        resolved_end_run = None
        if end_run is not None and getattr(end_run, "target_span_id", None):
            resolved_end_run = self.block_manager.find_run_by_id(page_idx, end_run.target_span_id)
        if resolved_end_run is None:
            resolved_end_run = min(
                runs,
                key=lambda run: _distance_sq_to_rect(end_point, fitz.Rect(run.bbox)),
            )

        run_ids = [run.span_id for run in runs]
        try:
            start_idx = run_ids.index(start_run.span_id)
            end_idx = run_ids.index(resolved_end_run.span_id)
        except ValueError:
            return "", None

        range_start = min(start_idx, end_idx)
        range_end = max(start_idx, end_idx)
        selected_runs = runs[range_start:range_end + 1]
        if not selected_runs:
            return "", None

        def _same_visual_line(left, right) -> bool:
            left_rect = fitz.Rect(left.bbox)
            right_rect = fitz.Rect(right.bbox)
            left_rotation = int(getattr(left, "rotation", 0)) % 360
            right_rotation = int(getattr(right, "rotation", 0)) % 360
            if left_rotation != right_rotation:
                return False
            tol = 2.0
            if left_rotation in (90, 270):
                return not (left_rect.x1 < right_rect.x0 - tol or right_rect.x1 < left_rect.x0 - tol)
            return not (left_rect.y1 < right_rect.y0 - tol or right_rect.y1 < left_rect.y0 - tol)

        line_groups: list[list] = []
        run_to_line_idx: dict[str, int] = {}
        for run in runs:
            if line_groups and _same_visual_line(line_groups[-1][-1], run):
                line_groups[-1].append(run)
            else:
                line_groups.append([run])
            run_to_line_idx[run.span_id] = len(line_groups) - 1

        start_line_idx = run_to_line_idx.get(start_run.span_id)
        end_line_idx = run_to_line_idx.get(resolved_end_run.span_id)
        if start_line_idx is None or end_line_idx is None:
            return "", None

        def _slice_for_group(group_idx: int) -> list:
            group_runs = line_groups[group_idx]
            group_ids = [run.span_id for run in group_runs]
            if start_line_idx == end_line_idx == group_idx:
                left = min(group_ids.index(start_run.span_id), group_ids.index(resolved_end_run.span_id))
                right = max(group_ids.index(start_run.span_id), group_ids.index(resolved_end_run.span_id))
                return group_runs[left:right + 1]
            if group_idx == start_line_idx:
                start_pos = group_ids.index(start_run.span_id)
                return group_runs[start_pos:]
            if group_idx == end_line_idx:
                end_pos = group_ids.index(resolved_end_run.span_id)
                return group_runs[:end_pos + 1]
            return group_runs

        line_texts: list[str] = []
        line_rects: list[fitz.Rect] = []
        for group_idx in range(min(start_line_idx, end_line_idx), max(start_line_idx, end_line_idx) + 1):
            line_runs = _slice_for_group(group_idx)
            line_text = " ".join((run.text or "").strip() for run in line_runs if (run.text or "").strip()).strip()
            if not line_text:
                continue
            line_texts.append(line_text)
            line_rect = fitz.Rect(line_runs[0].bbox)
            for run in line_runs[1:]:
                line_rect.include_rect(fitz.Rect(run.bbox))
            line_rects.append(line_rect)

        if not line_texts or not line_rects:
            return "", None

        bounds = fitz.Rect(line_rects[0])
        for line_rect in line_rects[1:]:
            bounds.include_rect(line_rect)
        return "\n".join(line_texts).strip(), bounds

    def get_chars_in_run(
        self,
        page_num: int,
        span_id: str,
        rawdict: dict | None = None,
    ) -> list[tuple[str, fitz.Rect]]:
        """Per-character (glyph, bbox) pairs for a run, in reading order.

        Glyph boxes come from PyMuPDF ``rawdict``; a char belongs to the run when
        its centre lies inside the run's bbox. Used for character-level selection.
        Pass ``rawdict`` to reuse one page extraction across multiple runs.
        """
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return []
        page_idx = page_num - 1
        self.ensure_page_index_built(page_num)
        run = self.block_manager.find_run_by_id(page_idx, span_id)
        if run is None:
            return []
        run_rect = fitz.Rect(run.bbox)
        # Tolerance is applied only along the run's *reading* axis (so the first
        # and last glyphs aren't clipped); the cross axis stays tight to avoid
        # picking up glyphs from an overlapping neighbouring line.
        tol = 0.5
        rotation = int(getattr(run, "rotation", 0)) % 360
        is_vertical = rotation in (90, 270)
        if rawdict is None:
            page = self.doc[page_idx]
            try:
                raw = page.get_text("rawdict")
            except Exception:
                return []
        else:
            raw = rawdict
        collected: list[tuple[str, fitz.Rect]] = []
        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    for ch in span.get("chars", []):
                        glyph = ch.get("c", "")
                        cb = fitz.Rect(ch.get("bbox"))
                        cx = (cb.x0 + cb.x1) / 2.0
                        cy = (cb.y0 + cb.y1) / 2.0
                        if is_vertical:
                            inside = (
                                run_rect.x0 <= cx <= run_rect.x1
                                and run_rect.y0 - tol <= cy <= run_rect.y1 + tol
                            )
                        else:
                            inside = (
                                run_rect.x0 - tol <= cx <= run_rect.x1 + tol
                                and run_rect.y0 <= cy <= run_rect.y1
                            )
                        if inside:
                            collected.append((glyph, cb))
        if is_vertical:
            # 90° reads top→bottom (ascending y); 270° reads bottom→top.
            collected.sort(key=lambda item: item[1].y0, reverse=(rotation == 270))
        else:
            # Order by line then x so a span wrapped onto two rows stays in order.
            collected.sort(key=lambda item: (round(item[1].y0), item[1].x0))
        return collected

    def get_text_selection_lines(
        self,
        page_num: int,
        start_span_id: str,
        end_point: fitz.Point,
        start_point: fitz.Point | None = None,
    ) -> tuple[str, list[fitz.Rect]]:
        """Character-level browse selection from a start run/point to an end point.

        Returns the exact selected text and one clipped rect per visual line
        (partial first line → full middle lines → partial last line). The text
        matches the highlighted glyphs exactly so copy stays in sync (AC-1).
        """
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return "", []
        page_idx = page_num - 1
        self.ensure_page_index_built(page_num)
        runs = self.block_manager.get_runs(page_idx)
        if not runs:
            return "", []
        start_run = self.block_manager.find_run_by_id(page_idx, start_span_id)
        if start_run is None:
            return "", []

        def _distance_sq_to_rect(point: fitz.Point, rect: fitz.Rect) -> float:
            dx = max(rect.x0 - point.x, 0.0, point.x - rect.x1)
            dy = max(rect.y0 - point.y, 0.0, point.y - rect.y1)
            return dx * dx + dy * dy

        end_run_info = self.get_text_info_at_point(page_num, end_point, allow_fallback=False)
        resolved_end_run = None
        if end_run_info is not None and getattr(end_run_info, "target_span_id", None):
            resolved_end_run = self.block_manager.find_run_by_id(page_idx, end_run_info.target_span_id)
        if resolved_end_run is None:
            resolved_end_run = min(runs, key=lambda r: _distance_sq_to_rect(end_point, fitz.Rect(r.bbox)))

        run_ids = [r.span_id for r in runs]
        try:
            start_idx = run_ids.index(start_run.span_id)
            end_idx = run_ids.index(resolved_end_run.span_id)
        except ValueError:
            return "", []

        # Order anchor/focus by reading order so clipping is direction-independent.
        if start_idx <= end_idx:
            first_run, first_point = start_run, start_point
            last_run, last_point = resolved_end_run, end_point
        else:
            first_run, first_point = resolved_end_run, end_point
            last_run, last_point = start_run, start_point

        def _same_visual_line(left, right) -> bool:
            left_rect = fitz.Rect(left.bbox)
            right_rect = fitz.Rect(right.bbox)
            lr = int(getattr(left, "rotation", 0)) % 360
            rr = int(getattr(right, "rotation", 0)) % 360
            if lr != rr:
                return False
            tol = 2.0
            if lr in (90, 270):
                return not (left_rect.x1 < right_rect.x0 - tol or right_rect.x1 < left_rect.x0 - tol)
            return not (left_rect.y1 < right_rect.y0 - tol or right_rect.y1 < left_rect.y0 - tol)

        line_groups: list[list] = []
        run_to_line_idx: dict[str, int] = {}
        for run in runs:
            if line_groups and _same_visual_line(line_groups[-1][-1], run):
                line_groups[-1].append(run)
            else:
                line_groups.append([run])
            run_to_line_idx[run.span_id] = len(line_groups) - 1

        first_line = run_to_line_idx.get(first_run.span_id)
        last_line = run_to_line_idx.get(last_run.span_id)
        if first_line is None or last_line is None:
            return "", []
        lo_line, hi_line = min(first_line, last_line), max(first_line, last_line)

        def _slice_for_group(group_idx: int) -> list:
            group_runs = line_groups[group_idx]
            ids = [r.span_id for r in group_runs]
            if first_line == last_line == group_idx:
                a = ids.index(first_run.span_id)
                b = ids.index(last_run.span_id)
                return group_runs[min(a, b):max(a, b) + 1]
            if group_idx == first_line:
                return group_runs[ids.index(first_run.span_id):]
            if group_idx == last_line:
                return group_runs[:ids.index(last_run.span_id) + 1]
            return group_runs

        def _axis(point: fitz.Point, vertical: bool) -> float:
            return point.y if vertical else point.x

        line_texts: list[str] = []
        line_rects: list[fitz.Rect] = []
        same_run = first_run.span_id == last_run.span_id
        try:
            rawdict = self.doc[page_idx].get_text("rawdict")
        except Exception:
            rawdict = None
        for group_idx in range(lo_line, hi_line + 1):
            glyphs: list[str] = []
            rects: list[fitz.Rect] = []
            for run in _slice_for_group(group_idx):
                vertical = int(getattr(run, "rotation", 0)) % 360 in (90, 270)
                chars = self.get_chars_in_run(page_num, run.span_id, rawdict=rawdict)
                for glyph, cb in chars:
                    coord = (cb.y0 + cb.y1) / 2.0 if vertical else (cb.x0 + cb.x1) / 2.0
                    keep = True
                    if same_run and run.span_id == first_run.span_id and first_point is not None and last_point is not None:
                        lo = min(_axis(first_point, vertical), _axis(last_point, vertical))
                        hi = max(_axis(first_point, vertical), _axis(last_point, vertical))
                        keep = lo <= coord <= hi
                    else:
                        if run.span_id == first_run.span_id and first_point is not None:
                            keep = keep and coord >= _axis(first_point, vertical)
                        if run.span_id == last_run.span_id and last_point is not None:
                            keep = keep and coord <= _axis(last_point, vertical)
                    if keep:
                        glyphs.append(glyph)
                        rects.append(cb)
            if not rects:
                continue
            line_rect = fitz.Rect(rects[0])
            for r in rects[1:]:
                line_rect.include_rect(r)
            line_texts.append("".join(glyphs))
            line_rects.append(line_rect)

        return "\n".join(line_texts), line_rects

    def get_render_width_for_edit(self, page_num: int, rect: fitz.Rect) -> float:
        """編輯換行寬度 == 原文字框寬度（point），不再加任何 Qt margin。

        編輯框比原 rect 寬時，Qt 字型渲染（與 PyMuPDF glyph metrics 略有
        差異）會在不同位置斷行，導致「開啟編輯框後斷行跳動」。換行寬度
        鎖定為來源 rect 寬度可讓預覽與最終 PDF 斷行一致。
        """
        return float(rect.width)

    def _resolve_add_text_font(self, font_hint: str) -> str:
        """Resolve add-text font name with CJK-safe default."""
        low = (font_hint or "").strip().lower()
        if not low:
            return "cjk"
        if low in {"microsoft jhenghei", "microsoftjhenghei", "microsoftjhengheiregular", "msjh"}:
            return "microsoft jhenghei"
        if low in {"pmingliu", "mingliu"}:
            return "pmingliu"
        if low in {"dfkai-sb", "dfkai", "dfkaishu-sb-estd-bf", "kaiu"}:
            return "dfkai-sb"
        if low in {"cjk", "china-ts", "china-ss"}:
            return low
        if any(k in low for k in ("cjk", "jhenghei", "yahei", "simsun", "pingfang", "source han", "noto")):
            return "cjk"
        resolved = self._resolve_font_for_push(font_hint)
        return resolved or "cjk"

    def _resolve_cjk_companion_font(self, latin_font_name: str) -> str:
        token = self._resolve_add_text_font(latin_font_name)
        if token in {"cjk", "china-ts", "china-ss", "microsoft jhenghei", "pmingliu", "dfkai-sb"}:
            return token
        if token == "tiro":
            return "china-ts"
        return "china-ss"

    def _font_token_to_css_family(self, font_token: str) -> str:
        token = self._resolve_add_text_font(font_token)
        return _CUSTOM_CJK_ALIASES.get(token, token)

    def _font_face_css_for_token(self, font_token: str) -> str:
        token = self._resolve_add_text_font(font_token)
        font_path = _WINDOWS_CJK_FONT_FILES.get(token)
        if font_path is None or not font_path.exists():
            return ""
        css_family = self._font_token_to_css_family(token)
        # Use absolute local path so MuPDF can resolve the face during htmlbox rendering.
        src = font_path.as_posix()
        return f'@font-face {{ font-family: "{css_family}"; src: url("{src}"); }}'

    def _insert_tiny_plain_text(
        self,
        page: fitz.Page,
        text: str,
        color_rgb: tuple[float, float, float],
        font_size_hint: float,
    ) -> None:
        """
        Tiny canvas fallback: force a minimal plain-text insertion.
        This prioritizes recoverable text extraction on extremely small pages.
        """
        tiny_size = 0.1
        x = float(page.rect.x0) + 0.05
        y = float(page.rect.y0) + max(0.2, min(float(page.rect.height) * 0.8, max(0.2, float(page.rect.height) - 0.05)))
        page.insert_text(
            fitz.Point(x, y),
            text,
            fontsize=tiny_size,
            fontname="helv",
            color=color_rgb,
            rotate=int(page.rotation) % 360,
        )

    def add_image_object(
        self,
        page_num: int,
        visual_rect: fitz.Rect,
        image_bytes: bytes,
        *,
        rotation: int = 0,
    ) -> str:
        return pdf_object_ops.add_image_object(self, page_num, visual_rect, image_bytes, rotation=rotation)

    def _pick_ocr_font(self, text: str) -> str:
        """Pick a PyMuPDF built-in font that covers the OCR text's scripts."""
        if re.search(r"[\u3040-\u30ff]", text):
            return "japan"
        if re.search(r"[\uac00-\ud7af]", text):
            return "korea"
        if re.search(r"[\u4e00-\u9fff]", text):
            return "china-t"
        return "helv"

    def apply_ocr_spans(
        self,
        page_num: int,
        spans: list,
    ) -> int:
        """Insert OCR-detected strings as invisible text (render_mode=3).

        ``spans`` is a sequence of ``OcrSpan``-like objects with ``bbox``,
        ``text``, and ``confidence`` attributes. Bboxes are in visual page
        coordinates. Returns the number of spans actually written.
        """
        if not self.doc:
            return 0
        if page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"無效 OCR 頁碼: {page_num}")
        if not spans:
            return 0

        page_idx = page_num - 1
        page = self.doc[page_idx]
        unrot_bounds = self._unrotated_page_rect(page)
        page_rotation = int(page.rotation) % 360

        inserted = 0
        for span in spans:
            text = (getattr(span, "text", "") or "").strip()
            if not text:
                continue
            bbox = getattr(span, "bbox", None)
            if bbox is None or len(bbox) != 4:
                continue

            visual_rect = fitz.Rect(*bbox)
            unrot_rect = self._visual_rect_to_unrotated_rect(page, visual_rect)
            unrot_rect = clamp_rect_to_page(unrot_rect, unrot_bounds)
            height = float(unrot_rect.height)
            width = float(unrot_rect.width)
            if height < 1.0 or width < 1.0:
                continue

            font_name = self._pick_ocr_font(text)
            font_size = max(1.0, height * 0.9)
            baseline_x = float(unrot_rect.x0)
            baseline_y = float(unrot_rect.y1 - height * 0.12)

            try:
                page.insert_text(
                    fitz.Point(baseline_x, baseline_y),
                    text,
                    fontname=font_name,
                    fontsize=font_size,
                    render_mode=3,
                    rotate=page_rotation,
                )
                inserted += 1
            except Exception:
                logger.exception(
                    "apply_ocr_spans: insert_text failed (page=%s font=%s text=%r)",
                    page_num,
                    font_name,
                    text,
                )
                continue

        if inserted:
            self.block_manager.rebuild_page(page_idx, self.doc)
            self.pending_edits.append({"page_idx": page_idx, "rect": fitz.Rect(page.rect)})
            self.edit_count += 1
            logger.info("apply_ocr_spans page=%s inserted=%s", page_num, inserted)
        return inserted

    def add_textbox(
        self,
        page_num: int,
        visual_rect: fitz.Rect,
        text: str,
        font: str = "cjk",
        size: int = 12,
        color: tuple = (0.0, 0.0, 0.0),
    ) -> None:
        return pdf_object_ops.add_textbox(self, page_num, visual_rect, text, font=font, size=size, color=color)

    def get_object_info_at_point(self, page_num: int, point: fitz.Point) -> ObjectHitInfo | None:
        return pdf_object_ops.get_object_info_at_point(self, page_num, point)

    def move_object(self, request: MoveObjectRequest) -> bool:
        return pdf_object_ops.move_object(self, request)

    def rotate_object(self, request: RotateObjectRequest) -> bool:
        return pdf_object_ops.rotate_object(self, request)

    def delete_object(self, request: DeleteObjectRequest) -> bool:
        return pdf_object_ops.delete_object(self, request)

    def delete_objects_atomic(self, requests: list[DeleteObjectRequest]) -> bool:
        return pdf_object_ops.delete_objects_atomic(self, requests)

    def resize_object(self, request: ResizeObjectRequest) -> bool:
        return pdf_object_ops.resize_object(self, request)

    def _convert_text_to_html(
        self,
        text: str,
        font_size: float,
        color: tuple,
        latin_font: str = "helv",
    ) -> str:
        """
        將混合文本轉換為帶有字體樣式的簡單 HTML，並正確處理空格。
        [優化 3] 使用模組級預編譯正則 _RE_HTML_TEXT_PARTS、_RE_CJK，避免重複編譯
        """
        html_parts = []
        if not text:
            return ""

        parts = _RE_HTML_TEXT_PARTS.findall(text)
        latin_font_name = self._resolve_add_text_font(latin_font)
        cjk_font_name = self._resolve_cjk_companion_font(latin_font_name)
        latin_css_family = self._font_token_to_css_family(latin_font_name)
        cjk_css_family = self._font_token_to_css_family(cjk_font_name)

        for part in parts:
            if part == '\n':
                html_parts.append('<br>')
            elif part.isspace():
                html_parts.append(f'<span style="font-family: {latin_css_family};">{part}</span>')
            elif _RE_CJK.match(part):
                html_parts.append(f'<span style="font-family: {cjk_css_family};">{_html_mod.escape(part)}</span>')
            else:
                html_parts.append(f'<span style="font-family: {latin_css_family};">{_html_mod.escape(part)}</span>')

        return "".join(html_parts)

    def _build_multi_style_html(
        self,
        new_text: str,
        member_spans: list,
        default_color: tuple,
        latin_font: str = "helv",
    ) -> str:
        """Build HTML that preserves per-run colors from ``member_spans``.

        Used when a paragraph-mode edit should not collapse multi-style runs
        onto the dominant color: characters in ``new_text`` that diff-match a
        source span inherit that span's color; inserted/replaced chunks inherit
        the nearest preceding span's color (or the first span's color at the
        start).
        """
        if not new_text:
            return ""
        ordered = sorted(
            member_spans,
            key=lambda s: (float(s.bbox.y0), float(s.bbox.x0)),
        )
        source_chars: list[str] = []
        source_colors: list[tuple[float, ...]] = []
        for span in ordered:
            span_text = span.text or ""
            span_color = tuple(float(c) for c in (span.color or default_color))
            for ch in span_text:
                source_chars.append(ch)
                source_colors.append(span_color)
        source_text = "".join(source_chars)
        if not source_text or not source_colors:
            return self._convert_text_to_html(
                new_text, 12, default_color, latin_font=latin_font
            )

        new_colors: list[tuple | None] = [None] * len(new_text)
        matcher = difflib.SequenceMatcher(a=source_text, b=new_text, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for k in range(j2 - j1):
                    new_colors[j1 + k] = source_colors[i1 + k]
            else:
                inherit = source_colors[i1 - 1] if i1 > 0 else source_colors[0]
                for k in range(j2 - j1):
                    new_colors[j1 + k] = inherit
        for idx in range(len(new_colors)):
            if new_colors[idx] is None:
                new_colors[idx] = tuple(float(c) for c in default_color)

        latin_font_name = self._resolve_add_text_font(latin_font)
        cjk_font_name = self._resolve_cjk_companion_font(latin_font_name)
        latin_css_family = self._font_token_to_css_family(latin_font_name)
        cjk_css_family = self._font_token_to_css_family(cjk_font_name)

        html_parts: list[str] = []
        idx = 0
        while idx < len(new_text):
            run_color = cast(tuple, new_colors[idx])
            start = idx
            idx += 1
            while idx < len(new_text) and new_colors[idx] == run_color:
                idx += 1
            chunk = new_text[start:idx]
            r = int(round(run_color[0] * 255))
            g = int(round(run_color[1] * 255))
            b = int(round(run_color[2] * 255))
            color_css = f"color: rgb({r}, {g}, {b});"
            for part in _RE_HTML_TEXT_PARTS.findall(chunk):
                if part == "\n":
                    html_parts.append("<br>")
                elif part.isspace():
                    html_parts.append(
                        f'<span style="font-family: {latin_css_family}; {color_css}">{part}</span>'
                    )
                elif _RE_CJK.match(part):
                    html_parts.append(
                        f'<span style="font-family: {cjk_css_family}; {color_css}">{_html_mod.escape(part)}</span>'
                    )
                else:
                    html_parts.append(
                        f'<span style="font-family: {latin_css_family}; {color_css}">{_html_mod.escape(part)}</span>'
                    )
        return "".join(html_parts)


    # ──────────────────────────────────────────────────────────────────────────
    # Phase 6: 文件整體快照（供 SnapshotCommand undo/redo 使用）
    # ──────────────────────────────────────────────────────────────────────────

    def _capture_doc_snapshot(self) -> bytes:
        """擷取整份文件的 bytes 快照（SnapshotCommand before/after 用）。

        encryption=KEEP：save() 的 encryption 預設為 NONE(1) 會解密。doc-level 快照
        在還原時會「整份取代」live doc（_restore_doc_from_snapshot 重新 fitz.open），
        若快照已解密，undo 後 live doc 即失去加密，下次存檔便遺失密碼。保留來源加密，
        還原端再以 session 密碼重新驗證即可。（page-level 快照為原地插頁、不取代
        live handle，加密狀態不受影響，另案追蹤。）
        """
        stream = io.BytesIO()
        self._save_doc(self.doc, stream)
        return stream.getvalue()

    def capture_worker_snapshot_bytes(self) -> bytes:
        """Capture snapshot bytes for background worker readers."""
        if not self.doc:
            raise RuntimeError("沒有開啟的 PDF 文件")
        return self.doc.tobytes(garbage=0, no_new_id=1, encryption=fitz.PDF_ENCRYPT_NONE)

    def capture_print_snapshot_bytes(self) -> bytes:
        """Capture print input, pruning destructive-edit orphans when required."""
        if not self.doc:
            raise RuntimeError("沒有開啟的 PDF 文件")
        if not self.secure_save_required:
            return self.capture_worker_snapshot_bytes()
        return self.doc.tobytes(
            garbage=4,
            no_new_id=1,
            encryption=fitz.PDF_ENCRYPT_NONE,
        )

    @staticmethod
    def preset_optimize_options(preset: str) -> PdfOptimizeOptions:
        return pdf_optimizer.preset_optimize_options(preset)

    @staticmethod
    def _normalize_optimize_options(options: PdfOptimizeOptions) -> PdfOptimizeOptions:
        return pdf_optimizer.normalize_optimize_options(options)

    def _resolve_file_backed_optimize_source(self, session_id: str | None) -> Path | None:
        return pdf_optimizer.resolve_file_backed_optimize_source(self, session_id)

    def _current_document_size_bytes(self, session_id: str | None) -> int:
        return pdf_optimizer.current_document_size_bytes(self, session_id)

    def _build_working_doc_for_optimized_copy(self, session_id: str | None) -> fitz.Document:
        return pdf_optimizer.build_working_doc_for_optimized_copy(self, session_id)

    def _make_active_audit_cache_key(self) -> tuple | None:
        return pdf_optimizer.make_active_audit_cache_key(self)

    @staticmethod
    def _blank_metadata_dict(doc: fitz.Document) -> dict[str, str]:
        return pdf_optimizer.blank_metadata_dict(doc)

    @staticmethod
    def _xref_size_bytes(doc: fitz.Document, xref: int) -> int:
        return pdf_optimizer.xref_size_bytes(doc, xref)

    def build_pdf_audit_report(self, doc: fitz.Document | None = None) -> PdfAuditReport:
        return pdf_optimizer.build_pdf_audit_report(self, doc)

    def _apply_optimize_options(
        self,
        working_doc: fitz.Document,
        options: PdfOptimizeOptions,
        source_path: Path | None = None,
        *,
        original_bytes: int | None = None,
        image_usage: dict[int, dict[str, float | int]] | None = None,
    ) -> None:
        pdf_optimizer.apply_optimize_options(
            self,
            working_doc,
            options,
            source_path=source_path,
            original_bytes=original_bytes,
            image_usage=image_usage,
        )

    @staticmethod
    def _image_rewrite_settings(options: PdfOptimizeOptions) -> dict[str, int | bool]:
        return pdf_optimizer.image_rewrite_settings(options)

    @staticmethod
    def _parallel_image_worker_count(image_count: int) -> int:
        return pdf_optimizer.parallel_image_worker_count(image_count)

    @staticmethod
    def _can_use_parallel_image_rewrite() -> bool:
        return pdf_optimizer.can_use_parallel_image_rewrite()

    @staticmethod
    def optimize_capabilities() -> dict[str, bool]:
        # Runtime probe for optional post-save packaging (pikepdf-backed
        # linearize / object streams); the controller feeds this to the dialog.
        return pdf_optimizer.optimize_capabilities()

    def _rewrite_images_serially(
        self,
        working_doc: fitz.Document,
        image_usage: dict[int, dict[str, float | int]],
        options: PdfOptimizeOptions,
    ) -> None:
        pdf_optimizer.rewrite_images_serially(self, working_doc, image_usage, options)

    def _collect_extracted_images(
        self,
        working_doc: fitz.Document,
        image_usage: dict[int, dict[str, float | int]],
    ) -> list[tuple[int, int, float, bytes]]:
        return pdf_optimizer.collect_extracted_images(self, working_doc, image_usage)

    def _rewrite_images_from_source_in_parallel(
        self,
        working_doc: fitz.Document,
        image_usage: dict[int, dict[str, float | int]],
        options: PdfOptimizeOptions,
        source_path: Path,
    ) -> None:
        pdf_optimizer.rewrite_images_from_source_in_parallel(self, working_doc, image_usage, options, source_path)

    def _rewrite_extracted_images_in_parallel(
        self,
        working_doc: fitz.Document,
        extracted_images: list[tuple[int, int, float, bytes]],
        options: PdfOptimizeOptions,
    ) -> None:
        pdf_optimizer.rewrite_extracted_images_in_parallel(self, working_doc, extracted_images, options)

    def _rewrite_images_with_pillow(
        self,
        working_doc: fitz.Document,
        options: PdfOptimizeOptions,
        source_path: Path | None = None,
        *,
        image_usage: dict[int, dict[str, float | int]] | None = None,
        allow_extracted_parallel_fallback: bool = True,
    ) -> None:
        pdf_optimizer.rewrite_images_with_pillow(
            self,
            working_doc,
            options,
            source_path=source_path,
            image_usage=image_usage,
            allow_extracted_parallel_fallback=allow_extracted_parallel_fallback,
        )

    @staticmethod
    def _requires_post_save_packaging(options: PdfOptimizeOptions) -> bool:
        return pdf_optimizer.requires_post_save_packaging(options)

    @staticmethod
    def _fast_save_kwargs(options: PdfOptimizeOptions) -> dict[str, int]:
        return pdf_optimizer.fast_save_kwargs(options)

    def _postprocess_optimized_pdf_with_pikepdf(self, source_path: Path, options: PdfOptimizeOptions) -> None:
        pdf_optimizer.postprocess_optimized_pdf_with_pikepdf(self, source_path, options)

    def _save_optimized_working_doc(self, working_doc: fitz.Document, temp_save: Path, options: PdfOptimizeOptions) -> None:
        pdf_optimizer.save_optimized_working_doc(self, working_doc, temp_save, options)

    def save_optimized_copy(
        self,
        new_path: str,
        options: PdfOptimizeOptions | None = None,
        session_id: str | None = None,
        credentials: OptimizeOutputCredentials | None = None,
    ) -> PdfOptimizationResult:
        # Optimize-copy is a strict "write a new file" workflow.
        # Implementation is delegated so `PDFModel` does not become an optimizer grab-bag.
        # session_id binds the job to its source tab (R5-03); None = active session.
        return pdf_optimizer.save_optimized_copy(
            self,
            new_path,
            options,
            session_id,
            credentials=credentials,
        )

    def capture_optimize_source(self, session_id: str) -> OptimizeSourceSnapshot:
        return pdf_optimizer.capture_optimize_source(self, session_id)

    def save_optimized_copy_from_snapshot(
        self,
        snapshot: OptimizeSourceSnapshot,
        new_path: str,
        options: PdfOptimizeOptions | None = None,
        credentials: OptimizeOutputCredentials | None = None,
    ) -> PdfOptimizationResult:
        return pdf_optimizer.save_optimized_copy_from_snapshot(
            self,
            snapshot,
            new_path,
            options,
            credentials=credentials,
        )

    def _restore_doc_from_snapshot(self, snapshot_bytes: bytes) -> None:
        """用 bytes 快照替換整份文件（SnapshotCommand undo/redo 時呼叫）。

        快照以 encryption=KEEP 擷取，故為加密檔案時重新開啟的 handle 會是鎖定狀態；
        以 session 保存的密碼重新驗證後 live session 才能繼續算繪/編輯。未加密文件
        為 no-op。
        """
        # typed bind; callers guarantee an open doc here (see replace_active_document_from_snapshot) - runtime behavior identical if None
        doc: fitz.Document = self.doc
        doc.close()
        self.doc = self._reauthenticate_if_needed(fitz.open("pdf", snapshot_bytes))
        logger.debug(f"_restore_doc_from_snapshot: 已還原文件（{len(snapshot_bytes)} bytes）")

    def replace_active_document_from_snapshot(self, snapshot_bytes: bytes, affected_pages: list[int] | None = None) -> None:
        if not snapshot_bytes:
            raise ValueError("缺少文件快照")
        self._restore_doc_from_snapshot(snapshot_bytes)
        self.refresh_structural_indexes(affected_pages or [1])

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 3: 頁面快照（取代 clone_page）
    # ──────────────────────────────────────────────────────────────────────────

    def _capture_single_page_snapshot_bytes(
        self,
        source_doc: fitz.Document,
        page_num_0based: int,
        annots: bool = True,
    ) -> bytes:
        tmp_doc = fitz.open()
        try:
            tmp_doc.insert_pdf(
                source_doc,
                from_page=page_num_0based,
                to_page=page_num_0based,
                annots=annots,
            )
            stream = io.BytesIO()
            tmp_doc.save(stream, garbage=0)
            return stream.getvalue()
        finally:
            tmp_doc.close()

    def _roundtrip_live_doc(self, *, garbage: int, deflate: bool) -> None:
        """Round-trip the live document through its own bytes, then make the fresh
        handle the active doc — preserving encryption and re-authenticating it.

        Single chokepoint for the invariant *a live-doc round-trip must not
        decrypt*: ``tobytes``/``save`` default to ``encryption=NONE``, which
        silently strips the password in memory and drops it on the next save. Every
        ``self.doc = fitz.open(self.doc.tobytes(...))`` (in-memory GC, in-memory
        repair, …) must go through here. Undo/redo *snapshots* deliberately do NOT
        — they are reopened without a password and stay decrypted by design.

        Opens the new handle *before* closing the old one, so if serialization or
        reopen fails the live doc is left intact for the caller to keep using.
        """
        # typed bind; callers guarantee an open doc here (see _repair_active_doc_in_memory guard) - runtime behavior identical if None
        doc: fitz.Document = self.doc
        data = doc.tobytes(
            garbage=garbage, deflate=deflate, encryption=fitz.PDF_ENCRYPT_KEEP
        )
        old = doc
        self.doc = self._reauthenticate_if_needed(fitz.open("pdf", data))
        try:
            old.close()
        except Exception:
            pass

    @staticmethod
    def _save_doc(
        doc: fitz.Document,
        target: str | io.BytesIO,
        *,
        garbage: int = 0,
        incremental: bool = False,
    ) -> None:
        """Single chokepoint for writing a document out to a path/stream.

        Always passes ``encryption=fitz.PDF_ENCRYPT_KEEP``. ``save()`` defaults to
        ``encryption=NONE(1)``, which actively *decrypts*: a full rewrite drops the
        password/permissions, and an incremental save even *raises* ("Can't do
        incremental writes when changing encryption"). KEEP is a no-op for
        unencrypted docs and preserves the source encryption otherwise. Sibling to
        ``_roundtrip_live_doc`` (the funnel for the serialize-and-replace variant).
        """
        doc.save(
            target, garbage=garbage, incremental=incremental, encryption=fitz.PDF_ENCRYPT_KEEP
        )

    def _atomic_full_save(
        self,
        doc: fitz.Document,
        path: str | Path,
        *,
        garbage: int = 4,
        replace_live_handle: bool = False,
    ) -> None:
        """Validate a same-directory full rewrite before atomically installing it.

        Keeping the staging file beside the destination preserves the atomicity
        guarantee of ``os.replace``.  The live handle is closed only after the
        staged file has been serialized and reopened successfully; if replacement
        then fails, the original file is reopened and the editing session survives.
        """
        target = Path(path).resolve()
        stage = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp.pdf")
        live_was_closed = False
        try:
            self._save_doc(doc, str(stage), garbage=max(4, int(garbage)), incremental=False)
            probe = fitz.open(str(stage))
            try:
                if probe.needs_pass:
                    password = self.password
                    if password is None or probe.authenticate(password) == 0:
                        raise RuntimeError("staged PDF could not be re-authenticated")
                # Force the xref/page tree to be read before the original is touched.
                len(probe)
            finally:
                probe.close()

            if replace_live_handle:
                # typed bind; replace_live_handle path guarantees an open live doc - runtime behavior identical if None (name live_doc avoids the `doc` param)
                live_doc: fitz.Document = self.doc
                live_doc.close()
                live_was_closed = True
            try:
                os.replace(str(stage), str(target))
            except Exception:
                if live_was_closed:
                    self.doc = self._reopen_doc_after_save(str(target))
                    live_was_closed = False
                raise
            if live_was_closed:
                self.doc = self._reopen_doc_after_save(str(target))
        finally:
            try:
                stage.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("unable to remove staged save %s: %s", stage, exc)

    def save_external_document(
        self,
        doc: fitz.Document,
        path: str | Path,
        *,
        sanitize: bool | None = None,
    ) -> None:
        """Persist an exported/merged document under the active security policy."""
        must_sanitize = self.secure_save_required if sanitize is None else bool(sanitize)
        if must_sanitize:
            self._atomic_full_save(doc, path, garbage=4)
        else:
            self._save_doc(doc, str(path))

    def _repair_active_doc_in_memory(self, garbage: int = 1) -> bool:
        """Try to repair current doc by round-tripping bytes and reopen in memory."""
        if not self.doc:
            return False
        try:
            self._roundtrip_live_doc(garbage=max(1, int(garbage)), deflate=True)
            self.block_manager.build_index(self.doc)
            logger.warning("已以 in-memory roundtrip 修復目前文件（garbage=%s）", max(1, int(garbage)))
            return True
        except Exception as e:
            logger.warning("修復目前文件失敗: %s", self._safe_exc_message(e))
            return False

    def _capture_page_snapshot_strict(self, page_num_0based: int) -> bytes:
        """Capture one-page snapshot without any whole-document fallback."""
        if not self.doc or page_num_0based < 0 or page_num_0based >= len(self.doc):
            raise ValueError(f"無效頁碼: {page_num_0based + 1}")
        last_err: Exception | None = None

        # 1) direct page copy with annotations
        try:
            return self._capture_single_page_snapshot_bytes(self.doc, page_num_0based, annots=True)
        except Exception as e:
            last_err = e

        # 2) fallback: page copy without annotations (still page-level strict)
        try:
            return self._capture_single_page_snapshot_bytes(self.doc, page_num_0based, annots=False)
        except Exception as e:
            last_err = e

        # 3) repair current document in memory, then retry page-level extraction
        repaired = self._repair_active_doc_in_memory(garbage=1)
        if repaired and self.doc and page_num_0based < len(self.doc):
            try:
                return self._capture_single_page_snapshot_bytes(self.doc, page_num_0based, annots=True)
            except Exception as e:
                last_err = e
            try:
                return self._capture_single_page_snapshot_bytes(self.doc, page_num_0based, annots=False)
            except Exception as e:
                last_err = e

        msg = self._safe_exc_message(last_err) if last_err else "unknown error"
        raise RuntimeError(
            f"無法擷取頁面快照（strict, page={page_num_0based + 1}）: {msg}"
        )

    def _capture_page_snapshot(self, page_num_0based: int) -> bytes:
        """
        擷取指定頁面的 bytes 快照，供 undo / rollback 使用。
        Fallback 策略（依序）：
          1. 正常 insert_pdf（含 annotations）
          2. insert_pdf annots=False（含跨頁 annotation 引用的 PDF）
          3. 整份文件快照（最保守）
        """
        # 嘗試 1：完整頁面（含 annotations）
        try:
            tmp_doc = fitz.open()
            tmp_doc.insert_pdf(self.doc, from_page=page_num_0based, to_page=page_num_0based)
            stream = io.BytesIO()
            tmp_doc.save(stream, garbage=0)
            data = stream.getvalue()
            tmp_doc.close()
            return data
        except Exception as e1:
            logger.debug(f"_capture_page_snapshot 完整複製失敗 (p{page_num_0based+1}): {e1}，嘗試 annots=False")

        # 嘗試 2：不含 annotations（避免跨頁 xref 無效引用）
        try:
            tmp_doc = fitz.open()
            tmp_doc.insert_pdf(
                self.doc, from_page=page_num_0based, to_page=page_num_0based,
                annots=False
            )
            stream = io.BytesIO()
            tmp_doc.save(stream, garbage=0)
            data = stream.getvalue()
            tmp_doc.close()
            logger.debug(f"_capture_page_snapshot: 使用 annots=False 快照 (p{page_num_0based+1})")
            return data
        except Exception as e2:
            logger.debug(f"_capture_page_snapshot annots=False 亦失敗: {e2}，改用文件級快照")

        # 嘗試 3：整份文件快照（最保守，undo 效果較差但不崩潰）
        return self._capture_doc_snapshot()

    def _restore_page_from_snapshot(self, page_num_0based: int, snapshot_bytes: bytes) -> None:
        """用 bytes 快照替換 doc 中指定頁面（undo / rollback 時呼叫）"""
        snapshot_doc = fitz.open("pdf", snapshot_bytes)
        try:
            if snapshot_doc.page_count < 1:
                raise ValueError("snapshot restore requires at least one page")

            # typed bind; callers guarantee an open doc here (undo/rollback path) - runtime behavior identical if None
            doc: fitz.Document = self.doc
            insert_at = page_num_0based
            doc.insert_pdf(snapshot_doc, from_page=0, to_page=0, start_at=insert_at)
            try:
                doc.delete_page(insert_at + 1)
            except Exception as delete_err:
                cleanup_err: Exception | None = None
                try:
                    doc.delete_page(insert_at)
                except Exception as err:
                    cleanup_err = err
                if cleanup_err is not None:
                    logger.error(
                        "snapshot restore cleanup failed: page=%s delete_error=%s cleanup_error=%s",
                        page_num_0based + 1,
                        delete_err,
                        cleanup_err,
                    )
                    raise RuntimeError(
                        f"snapshot restore inserted replacement page but could not restore original state: "
                        f"delete_error={delete_err}; cleanup_error={cleanup_err}"
                    ) from cleanup_err
                raise RuntimeError(
                    f"snapshot restore inserted replacement page but could not remove original page: {delete_err}"
                ) from delete_err
        finally:
            snapshot_doc.close()

    def _build_insert_css(
        self,
        size: float,
        color: tuple,
        font_hint: str = "helv",
        line_height: float = 0.0,
    ) -> str:
        """建構 insert_htmlbox 所需的 CSS 樣式字串。

        line_height: 實際行高（pt）。0 表示自動計算（size × 1.2，或從字體 metrics 取得）。
        正確的行高能讓 re-insert 後的文字行距與原 PDF 一致。
        """
        resolved_font = self._resolve_add_text_font(font_hint)
        cjk_companion = self._resolve_cjk_companion_font(resolved_font)
        font_face_rules = []
        for token in {resolved_font, cjk_companion}:
            css_rule = self._font_face_css_for_token(token)
            if css_rule:
                font_face_rules.append(css_rule)
        font_face_block = "\n".join(font_face_rules)

        # 行高：優先使用傳入值，否則從字體 metrics 計算。
        # max(size, ...) 夾擠只在「自動計算」分支生效；呼叫端傳入的
        # 明確行高（含緊湊 leading，如 8pt < 10pt 字級）必須原樣保留，
        # 否則 re-insert 後文字會比原 PDF 高、推擠下方文字。
        if line_height <= 0:
            try:
                font_obj = fitz.Font(resolved_font)
                line_height = max(size * 1.1, (font_obj.ascender - font_obj.descender) * size)
            except Exception:
                line_height = size * 1.2
            line_height = round(max(size, line_height), 2)
        else:
            line_height = round(line_height, 2)

        return f"""
            {font_face_block}
            span {{
                font-size: {size}pt;
                line-height: {line_height}pt;
                white-space: pre-wrap;
                word-break: break-all;
                overflow-wrap: anywhere;
                color: rgb({int(color[0]*255)}, {int(color[1]*255)}, {int(color[2]*255)});
            }}
            .helv {{ font-family: helv; }}
            .cjk {{ font-family: cjk; }}
        """

    def apply_pending_redactions(self) -> None:
        """
        批次清理所有已修改頁面的 content stream（Phase 6 效能優化）。
        對每個 pending_edit 中記錄的頁面呼叫 page.clean_contents()，
        壓縮 content stream、移除孤立資源，可降低 PDF 大小 10-30%。
        應在 save() 前或每 5 次編輯時呼叫。
        """
        if not self.pending_edits or not self.doc:
            return
        unique_pages = {e["page_idx"] for e in self.pending_edits}
        cleaned = 0
        for page_idx in sorted(unique_pages):
            if 0 <= page_idx < len(self.doc):
                try:
                    self.doc[page_idx].clean_contents()
                    cleaned += 1
                except Exception as e:
                    logger.warning(f"clean_contents 失敗（頁面 {page_idx + 1}）: {e}")
        logger.debug(
            f"apply_pending_redactions: 已清理 {cleaned}/{len(unique_pages)} 頁的 content stream"
        )
        self.pending_edits.clear()

    def _maybe_garbage_collect(self) -> None:
        """
        Interactive maintenance performs page-local ``clean_contents`` only.

        Whole-document garbage=4 rewrites are deliberately deferred to the
        persistence boundary: doing them here blocks the GUI, rebuilds the full
        text index, and renumbers xrefs while object markers are live.
        """
        if self.edit_count <= 0:
            return
        # 輕量層：每 5 次清理 content stream
        if self.edit_count % 5 == 0:
            self.apply_pending_redactions()

    # ──────────────────────────────────────────────────────────────────────────
    # Push-Down 輔助方法：換行溢出時保留並推移下方文字塊
    # ──────────────────────────────────────────────────────────────────────────

    def _resolve_font_for_push(self, raw_font_name: str) -> str:
        """
        將 get_text("dict") 返回的字體名稱（如 'ABCDEF+ArialMT'）轉為
        page.insert_text() 可接受的名稱。若原字體不可用則回退至最接近的
        PyMuPDF 內建字體（helv / tiro / cour 系列）。
        """
        # 去除嵌入子集前綴（如 "ABCDEF+Arial" → "Arial"）
        base = raw_font_name.split("+", 1)[-1] if "+" in raw_font_name else raw_font_name

        # 嘗試直接使用原名稱
        try:
            fitz.Font(base)
            return base
        except Exception:
            pass

        # 依字體名稱特徵回退至 PyMuPDF 內建字體
        low = base.lower()
        is_bold   = "bold"   in low
        is_italic = "italic" in low or "oblique" in low
        is_mono   = "courier" in low or "mono" in low or "typewriter" in low
        is_serif  = "times" in low or "roman" in low or "georgia" in low

        if is_mono:
            if is_bold and is_italic:
                return "cour-bi"
            if is_bold:
                return "cour-b"
            if is_italic:
                return "cour-i"
            return "cour"
        if is_serif:
            if is_bold and is_italic:
                return "tibo"
            if is_bold:
                return "tib"
            if is_italic:
                return "tiit"
            return "tiro"
        # sans-serif (Helvetica / Arial / 其他)
        if is_bold and is_italic:
            return "heit"
        if is_bold:
            return "hebo"
        if is_italic:
            return "heit"
        return "helv"

    def _needs_cjk_font(self, text: str) -> bool:
        """
        判斷文字是否包含 CJK（中日韓）字符。
        供文字重播/插入時挑選可用 fallback 字體，避免缺字。
        """
        if not text:
            return False
        return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))

    # R3.5: edit-text / redaction engine extracted to model/pdf_text_edit.py.
    # These stay as 1-line delegating wrappers so the test net (which pokes the
    # private helpers directly and monkeypatches _push_down_overlapping_text) and
    # the public edit_text API are preserved byte-for-byte in behaviour.
    def _has_complex_script(self, *args, **kwargs):
        return pdf_text_edit._has_complex_script(self, *args, **kwargs)

    def _push_down_overlapping_text(self, *args, **kwargs):
        return pdf_text_edit._push_down_overlapping_text(self, *args, **kwargs)

    def _replay_protected_spans(self, *args, **kwargs):
        return pdf_text_edit._replay_protected_spans(self, *args, **kwargs)

    def _validate_protected_spans(self, *args, **kwargs):
        return pdf_text_edit._validate_protected_spans(self, *args, **kwargs)

    def _resolve_edit_target(self, *args, **kwargs):
        return pdf_text_edit._resolve_edit_target(self, *args, **kwargs)

    def _apply_redact_insert(self, *args, **kwargs):
        return pdf_text_edit._apply_redact_insert(self, *args, **kwargs)

    def _verify_rebuild_edit(self, *args, **kwargs):
        return pdf_text_edit._verify_rebuild_edit(self, *args, **kwargs)

    def _resolve_effective_target_mode(self, *args, **kwargs):
        return pdf_text_edit._resolve_effective_target_mode(self, *args, **kwargs)

    def edit_text(self, page_num: int, rect: fitz.Rect, new_text: str,
                  font: str = "helv", size: float = 12.0,
                  color: tuple = (0.0, 0.0, 0.0),
                  original_text: str | None = None,
                  vertical_shift_left: bool = True,
                  new_rect: fitz.Rect = None,
                  target_span_id: str | None = None,
                  target_mode: str | None = None) -> EditTextResult:
        return pdf_text_edit.edit_text(
            self, page_num, rect, new_text,
            font=font, size=size, color=color,
            original_text=original_text,
            vertical_shift_left=vertical_shift_left,
            new_rect=new_rect,
            target_span_id=target_span_id,
            target_mode=target_mode,
        )

    def _reauthenticate_if_needed(self, doc: fitz.Document) -> fitz.Document:
        """Re-authenticate a freshly (re)opened encrypted handle in place.

        Any time an encrypted doc is round-tripped (``tobytes``/save+reopen) the
        new handle comes back locked (``needs_pass``); until it is re-authenticated
        with the password captured at open, the live session can't render, extract
        text, or edit. No-op for unencrypted docs (``needs_pass`` is 0), so it is
        safe to call on every reopen/round-trip path.
        """
        if doc.needs_pass:
            pw = self.password
            if pw is None:
                logger.warning("重新開啟文件仍加密但未保存密碼，無法自動解鎖")
            elif doc.authenticate(pw) == 0:
                logger.warning("文件密碼重新驗證失敗，維持鎖定")
        return doc

    def _reopen_doc_after_save(self, path: str) -> fitz.Document:
        """Reopen a just-saved file, re-authenticating if it kept encryption.

        Saving with ``encryption=KEEP`` produces an encrypted file, so the
        reopened handle is locked until re-authenticated. Without this, the live
        editing session would go dead (no render / text extraction / edits) after
        an encrypted save-back — the save paths close the in-memory authenticated
        doc to release the Windows file lock, then reopen from disk.
        """
        return self._reauthenticate_if_needed(fitz.open(path))

    def _full_save_to_path(self, path: str):
        """
        完整儲存到指定路徑。若目標路徑與目前開啟的檔案相同（doc.name），
        先寫入暫存檔再覆蓋，避免 Windows 上「覆寫已開啟檔案」導致 Permission denied。
        """
        # typed bind; callers guarantee an open doc here (save path) - runtime behavior identical if None; self.doc not reassigned until the reopen below
        doc: fitz.Document = self.doc
        path_resolved = Path(path).resolve()
        doc_name_resolved = Path(doc.name).resolve() if doc.name else None
        saving_over_open_file = doc_name_resolved is not None and path_resolved == doc_name_resolved

        if self.secure_save_required:
            self._atomic_full_save(
                doc,
                path,
                garbage=4,
                replace_live_handle=saving_over_open_file,
            )
            return

        if saving_over_open_file:
            # 先寫入暫存檔，關閉 doc 後再覆蓋原檔，最後重新開啟
            temp_save = Path(self.temp_dir.name) / f"save_{uuid.uuid4()}.pdf"
            self._save_doc(doc, str(temp_save))
            doc.close()
            try:
                shutil.copy2(str(temp_save), path)
            finally:
                try:
                    os.unlink(temp_save)
                except OSError as e:
                    logger.warning(f"無法刪除暫存檔 {temp_save}: {e}")
            self.doc = self._reopen_doc_after_save(path)
            logger.debug(f"已透過暫存檔覆寫原檔: {path}")
        else:
            self._save_doc(self.doc, path)

    def _render_page_gray_array(self, page_num: int, max_dim: int = 1000):
        """Render a page to a downscaled grayscale numpy array for skew analysis."""
        import numpy as np

        # typed bind; callers guarantee an open doc here (deskew path) - runtime behavior identical if None
        doc: fitz.Document = self.doc
        page = doc[page_num - 1]
        rect = fitz.Rect(page.rect)
        longest = max(1.0, float(rect.width), float(rect.height))
        scale = max(0.1, min(float(max_dim) / longest, 4.0))
        scale = _safe_render_scale(page, scale)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)

    def detect_page_skew(self, page_num: int, max_angle: float = 10.0, step: float = 0.5) -> float:
        """Detect a page's skew via projection-profile variance.

        Returns the corrective angle (degrees, CCW-positive) that, applied to the
        page, best aligns text rows horizontally. The bars/text rows of a level
        page produce a row-sum projection with sharp peaks (high variance); the
        candidate angle maximizing that variance is the deskew angle.
        """
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"無效頁碼: {page_num}")
        import numpy as np
        from PIL import Image

        arr = self._render_page_gray_array(page_num)
        ink = ((arr < 128).astype(np.uint8) * 255)
        img = Image.fromarray(ink, mode="L")
        best_angle = 0.0
        best_score = -1.0
        steps = int(round((2.0 * max_angle) / max(1e-6, step))) + 1
        for i in range(steps):
            angle = -max_angle + i * step
            rotated = img.rotate(angle, resample=Image.Resampling.NEAREST, expand=False, fillcolor=0)
            row_sums = np.asarray(rotated, dtype=np.float64).sum(axis=1)
            score = float(np.var(row_sums))
            if score > best_score:
                best_score = score
                best_angle = angle
        return float(best_angle)

    def straighten_page(self, page_num: int, angle_degrees: float | None = None) -> bool:
        """Rotate a page to level it (deskew). Rasterizes the page.

        When ``angle_degrees`` is None the skew is auto-detected. The corrected
        page keeps the original size; rotated-out corners are filled white.
        """
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"無效頁碼: {page_num}")
        if angle_degrees is None:
            angle_degrees = self.detect_page_skew(page_num)
        angle = float(angle_degrees)
        idx = page_num - 1
        rect = fitz.Rect(self.doc[idx].rect)
        if abs(angle) < 0.05:
            return True  # already level; nothing to correct

        import io

        from PIL import Image

        scale = _safe_render_scale(self.doc[idx], 2.0)
        pix = self.doc[idx].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        mode = "RGBA" if pix.alpha else "RGB"
        img = Image.frombytes(mode, (pix.width, pix.height), pix.samples).convert("RGB")
        # Release the MuPDF pixmap's C buffer eagerly; PIL.frombytes already copied
        # the pixel data, so holding pix through the rotation+save is dead weight.
        del pix
        straightened = img.rotate(
            angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(255, 255, 255)
        )
        buf = io.BytesIO()
        straightened.save(buf, format="PNG")
        png = buf.getvalue()

        # Replace the page: insert a same-size blank page at idx (old shifts to
        # idx+1), paint the straightened raster, then drop the old page.
        new_page = self.doc.new_page(pno=idx, width=float(rect.width), height=float(rect.height))
        new_page.insert_image(fitz.Rect(0.0, 0.0, float(rect.width), float(rect.height)), stream=png)
        self.doc.delete_page(idx + 1)
        try:
            self.block_manager.rebuild_page(idx, self.doc)
        except Exception:
            logger.debug("block index rebuild after straighten skipped")
        self.pending_edits.append({"page_idx": idx, "rect": fitz.Rect(rect)})
        self.edit_count += 1
        return True

    def save_as(self, new_path: str):
        """另存 PDF。若存回原檔且支援增量更新，則使用 incremental=True。"""
        if not self.doc:
            return
        canonical_new = self._canonicalize_path(new_path)
        active_sid = self.get_active_session_id()
        existing_sid = self._path_to_session_id.get(canonical_new)
        if existing_sid and active_sid and existing_sid != active_sid:
            raise RuntimeError("目標路徑已在其他分頁開啟，請改用不同檔名。")
        # Phase 6: 儲存前批次清理已修改頁面的 content stream，壓縮 PDF 大小
        self.apply_pending_redactions()
        new_path_resolved = Path(new_path).resolve()
        original_resolved = Path(self.original_path).resolve() if self.original_path else None
        doc_name_resolved = Path(self.doc.name).resolve() if self.doc.name else None
        # 是否為「存回原檔」：新路徑與開啟時路徑相同，且目前 doc 仍是從原檔開啟（未經 undo 載入 temp）
        is_save_back_to_original = (
            original_resolved is not None
            and doc_name_resolved is not None
            and new_path_resolved == original_resolved
            and doc_name_resolved == original_resolved
        )
        can_incr = getattr(self.doc, "can_save_incrementally", None)
        use_incremental = (
            self.use_incremental_save
            and not self.secure_save_required
            and is_save_back_to_original
            and can_incr
            and self.doc.can_save_incrementally()
        )

        prepared_doc = self.tools.prepare_doc_for_save(active_sid) if active_sid else None
        doc_to_save = prepared_doc if prepared_doc is not None else self.doc
        try:
            if doc_to_save is self.doc and use_incremental:
                # 增量更新時使用與 doc.name 一致的路徑格式，避免 PyMuPDF 判定為非原檔
                try:
                    save_target = self.doc.name if self.doc.name else new_path
                    self._save_doc(self.doc, save_target, incremental=True)
                    logger.debug(f"已使用增量更新儲存: {new_path}")
                except Exception as e:
                    logger.warning(f"增量更新儲存失敗，改為完整儲存: {e}")
                    self._full_save_to_path(new_path)
            elif doc_to_save is self.doc:
                self._full_save_to_path(new_path)
            else:
                # 若目標路徑為目前開啟的檔案，先寫暫存再覆蓋，避免 Windows Permission denied
                if self.secure_save_required:
                    self._atomic_full_save(
                        doc_to_save,
                        new_path,
                        garbage=4,
                        replace_live_handle=(
                            doc_name_resolved is not None and new_path_resolved == doc_name_resolved
                        ),
                    )
                elif doc_name_resolved is not None and new_path_resolved == doc_name_resolved:
                    temp_save = Path(self.temp_dir.name) / f"save_{uuid.uuid4()}.pdf"
                    self._save_doc(doc_to_save, str(temp_save))
                    self.doc.close()
                    try:
                        shutil.copy2(str(temp_save), new_path)
                    finally:
                        try:
                            os.unlink(temp_save)
                        except OSError:
                            pass
                    self.doc = self._reopen_doc_after_save(new_path)
                else:
                    self._save_doc(doc_to_save, new_path)
        finally:
            if prepared_doc is not None:
                prepared_doc.close()

        self.saved_path = new_path
        if active_sid and active_sid in self._sessions_by_id:
            session = self._sessions_by_id[active_sid]
            self._path_to_session_id.pop(session.canonical_path, None)
            session.canonical_path = canonical_new
            session.original_path = str(Path(new_path).resolve())
            session.display_name = Path(new_path).name
            self._path_to_session_id[canonical_new] = active_sid
        self.command_manager.mark_saved()
        self.edit_count = 0
        if active_sid:
            self.tools.on_session_saved(active_sid)

    def has_unsaved_changes(self) -> bool:
        """檢查是否有未儲存的變更（Phase 6：統一由 command_manager 管理）。"""
        sid = self.get_active_session_id()
        if not sid:
            return False
        return self.session_has_unsaved_changes(sid)

    # undo() / redo() 已於 Phase 6 移除，改由 Controller 呼叫 model.command_manager.undo/redo()。
