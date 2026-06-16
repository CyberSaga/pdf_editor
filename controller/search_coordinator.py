"""Asynchronous text-search coordinator (R3.2 god-module decomposition seam).

Owns the background-search runtime: the `_SearchWorker`/`_SearchBridge` QObjects and
all of the search thread/worker/bridge/generation/session state that previously lived
on `PDFController`. The controller keeps thin `search_text`/`_cancel_search` delegates
and re-exports `_SearchWorker`/`_SearchBridge` for backward compatibility.

Extracted verbatim from `pdf_controller.py` (only controller-owned reads rewritten to
`self._c.<attr>`) so the behavior — signal wiring, QThread lifecycle, cancellation
generation token, empty-query and worker-snapshot paths — is byte-identical.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import fitz
from PySide6.QtCore import QObject, QThread, Signal, Slot

from utils.helpers import show_error

if TYPE_CHECKING:
    from controller.pdf_controller import PDFController

logger = logging.getLogger(__name__)


class _SearchWorker(QObject):
    """Runs SearchTool.search_page page-by-page on a background thread.

    Every signal carries the search generation token so the controller can
    drop late queued emissions from a cancelled search (queued events posted
    before a disconnect would otherwise still be delivered).
    """

    hits_found = Signal(int, int, list)  # gen, page_num, page hits
    failed = Signal(int, object)  # gen, exception
    finished = Signal(int)  # gen

    def __init__(self, tool, query: str, total_pages: int, gen: int, doc_bytes: bytes) -> None:
        super().__init__()
        self._tool = tool
        self._query = query
        self._total_pages = int(total_pages)
        self._gen = gen
        self._doc_bytes = doc_bytes
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    @Slot()
    def run(self) -> None:
        try:
            doc = fitz.open("pdf", self._doc_bytes) if self._doc_bytes else None
            try:
                search_fn = getattr(self._tool, "search_page_in_doc", None)
                for page_num in range(1, self._total_pages + 1):
                    if self._cancel_requested:
                        break
                    if search_fn is not None and doc is not None:
                        hits = search_fn(doc, page_num, self._query)
                    else:
                        hits = self._tool.search_page(page_num, self._query)
                    if hits:
                        self.hits_found.emit(self._gen, page_num, list(hits))
            finally:
                doc.close()
        except Exception as exc:
            logger.exception("Search worker failed")
            self.failed.emit(self._gen, exc)
        finally:
            self.finished.emit(self._gen)


class _SearchBridge(QObject):
    hits_found = Signal(int, int, list)
    failed = Signal(int, object)
    finished = Signal(int)

    @Slot(int, int, list)
    def forward_hits_found(self, gen: int, page_num: int, hits) -> None:
        self.hits_found.emit(gen, page_num, hits)

    @Slot(int, object)
    def forward_failed(self, gen: int, exc) -> None:
        self.failed.emit(gen, exc)

    @Slot(int)
    def forward_finished(self, gen: int) -> None:
        self.finished.emit(gen)


class SearchCoordinator:
    """Owns the async-search runtime for one PDFController.

    The controller holds exactly one of these (`self._search_coordinator`) and
    delegates `search_text`/`_cancel_search` to it. The coordinator reaches back
    through `self._c` for the controller-owned model/view/session helpers, which
    stay on PDFController.
    """

    def __init__(self, controller: PDFController) -> None:
        self._c = controller
        self._search_thread: QThread | None = None
        self._search_worker: _SearchWorker | None = None
        self._search_worker_bridge: _SearchBridge | None = None
        self._search_accumulated_hits: list[tuple[int, str, object]] = []
        self._search_gen = 0
        self._search_query = ""
        self._search_session_id: str | None = None
        self._search_finished = True

    def connect_bridge(self) -> None:
        """Lazy-init the GUI-thread bridge and wire it to the handlers (from activate())."""
        if self._search_worker_bridge is None:
            self._search_worker_bridge = _SearchBridge(self._c.view)
            self._search_worker_bridge.hits_found.connect(self._on_search_hits_found)
            self._search_worker_bridge.failed.connect(self._on_search_failed)
            self._search_worker_bridge.finished.connect(self._on_search_finished)

    def search_text(self, query: str):
        """非同步搜尋：工作執行緒逐頁搜尋，GUI 執行緒增量累積並顯示結果。

        每次呼叫先取消前一次搜尋（generation token 會丟棄遲到的佇列訊號），
        worker 結束時把完整結果寫回 session 的 search_state。
        """
        self.cancel()
        query = query or ""
        sid = self._c.model.get_active_session_id()
        self._search_accumulated_hits = []
        self._search_query = query
        self._search_session_id = sid
        self._search_finished = False
        if not query or not self._c.model.doc or not sid:
            self._c.view.display_search_results([])
            if sid:
                self._c._get_ui_state(sid).search_state = {"query": query, "results": [], "index": -1}
            return

        gen = self._search_gen  # already bumped by cancel()
        thread = QThread()
        worker = _SearchWorker(
            self._c.model.tools.search,
            query,
            len(self._c.model.doc),
            gen,
            self._c.model.capture_worker_snapshot_bytes(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        if self._search_worker_bridge is not None:
            worker.hits_found.connect(self._search_worker_bridge.forward_hits_found)
            worker.failed.connect(self._search_worker_bridge.forward_failed)
            worker.finished.connect(self._search_worker_bridge.forward_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Drop controller refs only once the THREAD has finished (not the worker):
        # releasing the Python QThread wrapper while the thread still runs lets GC
        # destroy the C++ object and hard-crash the process.
        thread.finished.connect(lambda t=thread: self._release_search_thread(t))

        self._search_thread = thread
        self._search_worker = worker
        thread.start()

    def _release_search_thread(self, thread) -> None:
        if self._search_thread is thread:
            self._search_thread = None
            self._search_worker = None

    def cancel(self) -> None:
        """Cancel any in-flight search and wait for its worker to stop.

        Must be called before any document mutation: the worker reads the live
        fitz document, which is not safe for concurrent read-during-mutation.
        Bumping ``_search_gen`` makes the handlers drop late queued signals.
        """
        self._search_gen += 1
        worker = self._search_worker
        thread = self._search_thread
        self._search_worker = None
        self._search_thread = None
        had_active_worker = (worker is not None or (thread is not None and thread.isRunning())) and not self._search_finished
        if had_active_worker:
            sid = self._search_session_id
            self._search_accumulated_hits = []
            self._c.view.display_search_results([])
            if sid:
                self._c._get_ui_state(sid).search_state = {"query": "", "results": [], "index": -1}
        if worker is not None:
            worker.request_cancel()
        if thread is not None and thread.isRunning():
            # quit() is thread-safe; the per-page cancel check makes run()
            # return quickly, after which the thread's event loop exits.
            thread.quit()

    @Slot(int, int, list)
    def _on_search_hits_found(self, gen: int, page_num: int, hits) -> None:
        if gen != self._search_gen:
            return
        self._search_accumulated_hits.extend(hits)
        append_results = getattr(type(self._c.view), "append_search_results", None)
        if callable(append_results):
            self._c.view.append_search_results(list(hits))
        else:
            self._c.view.display_search_results(list(self._search_accumulated_hits))

    @Slot(int, object)
    def _on_search_failed(self, gen: int, exc) -> None:
        if gen != self._search_gen:
            return
        logger.error("搜尋失敗: %s", exc)
        show_error(self._c.view, f"搜尋失敗: {exc}")

    @Slot(int)
    def _on_search_finished(self, gen: int) -> None:
        if gen != self._search_gen:
            return
        self._search_finished = True
        self._c.view.display_search_results(list(self._search_accumulated_hits))
        sid = self._search_session_id
        if sid:
            state = self._c._get_ui_state(sid)
            state.search_state = {
                "query": self._search_query,
                "results": list(self._search_accumulated_hits),
                "index": -1,
            }
