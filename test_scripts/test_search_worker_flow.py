"""Phase 4.2 — search on a worker thread (mirrors test_ocr_controller_flow.py).

``PDFController.search_text`` must run ``SearchTool.search_page`` page-by-page on
a background ``QThread``, forward per-page hits through ``_SearchBridge`` onto the
GUI thread, accumulate them incrementally into ``view.display_search_results``,
and persist the session ``search_state`` when the worker finishes.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import fitz
from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer

from controller.pdf_controller import PDFController, _SearchBridge, _SearchWorker


class _FakeSearchTool:
    """Per-page fake with the exact (page_num, context, rect) hit shape."""

    def __init__(self, per_page: dict[int, list], delay: float = 0.0) -> None:
        self._per_page = per_page
        self._delay = delay
        self.calls: list[tuple[int, str]] = []
        self.thread_ids: list[int] = []

    def search_page(self, page_num: int, query: str) -> list:
        self.calls.append((page_num, query))
        self.thread_ids.append(threading.get_ident())
        if self._delay:
            time.sleep(self._delay)
        return list(self._per_page.get(page_num, []))


def _hit(page_num: int, text: str) -> tuple[int, str, fitz.Rect]:
    return (page_num, text, fitz.Rect(0, 0, 10, 10))


def _drive_worker(worker: _SearchWorker, qapp) -> None:
    """Run the worker on a real QThread and pump events until `finished` fires."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    thread.start()

    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    safety = QTimer()
    safety.setSingleShot(True)
    safety.timeout.connect(loop.quit)
    safety.start(5000)
    loop.exec()
    thread.wait(2000)


def test_search_worker_emits_hits_found_per_page(qapp):
    hits_p1 = [_hit(1, "alpha one")]
    hits_p3 = [_hit(3, "alpha three"), _hit(3, "alpha three b")]
    tool = _FakeSearchTool({1: hits_p1, 3: hits_p3})

    worker = _SearchWorker(tool, "alpha", total_pages=3, gen=7)
    events: list[tuple[int, int, list]] = []
    worker.hits_found.connect(lambda g, p, h: events.append((g, p, list(h))))

    _drive_worker(worker, qapp)

    assert [(g, p) for g, p, _ in events] == [(7, 1), (7, 3)]
    assert events[0][2] == hits_p1
    assert events[1][2] == hits_p3
    # All pages were searched even when only two produced hits.
    assert [c[0] for c in tool.calls] == [1, 2, 3]


def test_search_worker_runs_on_non_gui_thread(qapp):
    tool = _FakeSearchTool({1: [_hit(1, "x")]})
    worker = _SearchWorker(tool, "x", total_pages=1, gen=1)
    _drive_worker(worker, qapp)

    gui_thread_id = threading.get_ident()
    assert tool.thread_ids, "tool was never invoked"
    assert all(tid != gui_thread_id for tid in tool.thread_ids)


def test_search_worker_respects_cancel(qapp):
    tool = _FakeSearchTool({p: [_hit(p, f"p{p}")] for p in range(1, 6)}, delay=0.05)
    worker = _SearchWorker(tool, "p", total_pages=5, gen=1)

    pages_seen: list[int] = []

    def _on_hits(_gen, page_num, _hits):
        pages_seen.append(page_num)
        if page_num == 1:
            worker.request_cancel()

    worker.hits_found.connect(_on_hits)
    _drive_worker(worker, qapp)

    assert 1 in pages_seen
    assert len(tool.calls) < 5


def test_search_worker_emits_failed_on_tool_exception(qapp):
    class _BoomTool:
        def search_page(self, *args, **kwargs):
            raise RuntimeError("boom")

    worker = _SearchWorker(_BoomTool(), "q", total_pages=2, gen=3)
    failures: list[tuple[int, object]] = []
    worker.failed.connect(lambda g, exc: failures.append((g, exc)))
    _drive_worker(worker, qapp)

    assert len(failures) == 1
    assert failures[0][0] == 3
    assert isinstance(failures[0][1], RuntimeError)


def test_search_bridge_forwards_signals(qapp):
    bridge = _SearchBridge()
    hits_seen: list = []
    failed_seen: list = []
    finished_seen: list = []
    bridge.hits_found.connect(lambda g, p, h: hits_seen.append((g, p, list(h))))
    bridge.failed.connect(lambda g, exc: failed_seen.append((g, exc)))
    bridge.finished.connect(lambda g: finished_seen.append(g))

    bridge.forward_hits_found(2, 1, [_hit(1, "x")])
    bridge.forward_failed(2, RuntimeError("nope"))
    bridge.forward_finished(2)
    QCoreApplication.processEvents()

    assert hits_seen and hits_seen[0][:2] == (2, 1)
    assert failed_seen and isinstance(failed_seen[0][1], RuntimeError)
    assert finished_seen == [2]


# -----------------------------------------------------------------------------
# Controller-level flow
# -----------------------------------------------------------------------------


def _build_minimal_controller(per_page: dict[int, list], *, page_count: int = 3, delay: float = 0.0):
    controller = PDFController.__new__(PDFController)

    model = MagicMock()
    model.doc = MagicMock()
    model.doc.__len__ = lambda self=None: page_count
    model.get_active_session_id = MagicMock(return_value="sid-1")
    tool = _FakeSearchTool(per_page, delay=delay)
    model.tools = MagicMock()
    model.tools.search = tool

    view = MagicMock()
    view.thread = lambda: QCoreApplication.instance().thread()

    controller.model = model
    controller.view = view
    controller._session_ui_state = {}
    controller._search_thread = None
    controller._search_worker = None
    controller._search_gen = 0
    controller._search_query = ""
    controller._search_session_id = None
    controller._search_accumulated_hits = []
    controller._search_worker_bridge = _SearchBridge(None)
    # Wire bridge to controller handlers (mirrors activate()).
    controller._search_worker_bridge.hits_found.connect(controller._on_search_hits_found)
    controller._search_worker_bridge.failed.connect(controller._on_search_failed)
    controller._search_worker_bridge.finished.connect(controller._on_search_finished)
    return controller, tool


def _wait_for_search_finish(controller, qapp, timeout_ms: int = 4000) -> None:
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)

    def _check():
        if controller._search_thread is None:
            loop.quit()
        else:
            QTimer.singleShot(20, _check)

    QTimer.singleShot(0, _check)
    loop.exec()


def test_controller_search_text_is_async(qapp):
    per_page = {1: [_hit(1, "alpha")]}
    controller, tool = _build_minimal_controller(per_page, page_count=3, delay=0.05)

    controller.search_text("alpha")

    # search_text returns immediately: the worker thread is still running and no
    # hits have been displayed yet.
    assert controller._search_thread is not None
    assert controller._search_accumulated_hits == []

    _wait_for_search_finish(controller, qapp)

    assert controller._search_accumulated_hits == per_page[1]
    displayed = [c.args[0] for c in controller.view.display_search_results.call_args_list]
    assert displayed, "no incremental display happened"
    assert displayed[-1] == per_page[1]
    # Session search_state persisted on finish.
    state = controller._session_ui_state["sid-1"].search_state
    assert state["query"] == "alpha"
    assert state["results"] == per_page[1]
    assert state["index"] == -1


def test_controller_search_text_accumulates_hits(qapp):
    per_page = {1: [_hit(1, "k one")], 3: [_hit(3, "k three")]}
    controller, tool = _build_minimal_controller(per_page, page_count=3)

    controller.search_text("k")
    _wait_for_search_finish(controller, qapp)

    displayed = [c.args[0] for c in controller.view.display_search_results.call_args_list]
    assert per_page[1] in displayed  # first incremental batch
    assert displayed[-1] == per_page[1] + per_page[3]  # accumulated, in page order


def test_controller_search_text_cancel_previous(qapp):
    per_page = {p: [_hit(p, f"slow {p}")] for p in range(1, 6)}
    controller, tool = _build_minimal_controller(per_page, page_count=5, delay=0.05)

    controller.search_text("slow")
    first_worker = controller._search_worker
    assert first_worker is not None

    controller.search_text("slow-again")

    assert first_worker._cancel_requested, "previous worker was not cancelled"
    _wait_for_search_finish(controller, qapp)

    # Only the second query's results survive.
    state = controller._session_ui_state["sid-1"].search_state
    assert state["query"] == "slow-again"
    queries = {q for _, q in tool.calls}
    assert "slow-again" in queries
