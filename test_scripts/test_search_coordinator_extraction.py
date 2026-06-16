"""R3.2 red-light: the async search subsystem must live in controller/search_coordinator.py.

The worker/bridge QObjects and the search orchestration (thread/worker/bridge/gen/
session state + slots) move off PDFController into a SearchCoordinator behind a stable
facade. PDFController keeps thin `search_text`/`_cancel_search` delegates and re-exports
`_SearchWorker`/`_SearchBridge` so existing imports stay valid.
"""

from __future__ import annotations

# RED before extraction: this module does not exist yet (hard ImportError on collect).
from controller.search_coordinator import (
    SearchCoordinator,
    _SearchBridge,
    _SearchWorker,
)

# Re-export contract: the worker/bridge must remain importable from pdf_controller too,
# because test_search_worker_flow.py and any external caller import them from there.
from controller.pdf_controller import _SearchBridge as ReexportBridge
from controller.pdf_controller import _SearchWorker as ReexportWorker


def test_worker_bridge_reexported_from_controller() -> None:
    assert ReexportWorker is _SearchWorker
    assert ReexportBridge is _SearchBridge


def test_coordinator_owns_search_runtime_state() -> None:
    class _FakeController:
        pass

    sc = SearchCoordinator(_FakeController())
    # The 8 runtime attrs live on the coordinator, not the controller.
    for attr in (
        "_search_thread",
        "_search_worker",
        "_search_worker_bridge",
        "_search_accumulated_hits",
        "_search_gen",
        "_search_query",
        "_search_session_id",
        "_search_finished",
    ):
        assert hasattr(sc, attr), attr
    assert sc._search_gen == 0
    assert sc._search_finished is True
    assert sc._search_accumulated_hits == []


def test_coordinator_exposes_facade_methods() -> None:
    class _FakeController:
        pass

    sc = SearchCoordinator(_FakeController())
    for name in (
        "search_text",
        "cancel",
        "connect_bridge",
        "_release_search_thread",
        "_on_search_hits_found",
        "_on_search_failed",
        "_on_search_finished",
    ):
        assert callable(getattr(sc, name)), name


def test_controller_holds_a_coordinator_and_delegates() -> None:
    from controller.pdf_controller import PDFController

    controller = PDFController.__new__(PDFController)
    controller._search_coordinator = SearchCoordinator(controller)
    # The public facades exist on the controller (sig_search + 13 mutation callers need them).
    assert callable(PDFController.search_text)
    assert callable(PDFController._cancel_search)
