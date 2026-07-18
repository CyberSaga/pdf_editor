from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import fitz  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtNetwork import QLocalServer  # noqa: E402

import main as main_module  # noqa: E402
from utils import single_instance as single_instance_module  # noqa: E402


def _pump_until(qapp, predicate, timeout_ms: int = 1000) -> bool:
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


def _make_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((36, 72), text)
    doc.save(path)
    doc.close()


def _cleanup_server(server: QLocalServer | None, server_name: str) -> None:
    if server is not None:
        lock = getattr(server, "_single_instance_lock", None)
        server.close()
        server.deleteLater()
        if lock is not None:
            lock.unlock()
    QLocalServer.removeServer(server_name)


def _cleanup_startup(startup: dict) -> None:
    server = startup.get("single_instance_server")
    if server is not None:
        lock = getattr(server, "_single_instance_lock", None)
        server.close()
        server.deleteLater()
        if lock is not None:
            lock.unlock()
    startup["view"].close()
    model = startup.get("model")
    if model is not None:
        model.close()
    startup["app"].quit()


def test_single_instance_server_receives_forwarded_argv(qapp) -> None:
    received: list[list[str]] = []
    server_name = f"pdf_editor_test_{uuid.uuid4().hex}"
    server = single_instance_module.try_become_server(received.append, server_name=server_name)
    try:
        assert server is not None
        assert single_instance_module.send_to_running_instance(["x.pdf"], server_name=server_name)
        expected = [[str(Path("x.pdf").resolve())]]
        assert _pump_until(qapp, lambda: received == expected)
    finally:
        _cleanup_server(server, server_name)


def test_try_become_server_returns_none_when_server_alive() -> None:
    server_name = f"pdf_editor_test_{uuid.uuid4().hex}"
    server = single_instance_module.try_become_server(lambda _argv: None, server_name=server_name)
    second = None
    try:
        assert server is not None
        second = single_instance_module.try_become_server(lambda _argv: None, server_name=server_name)
        assert second is None
    finally:
        _cleanup_server(second, server_name)
        _cleanup_server(server, server_name)


def test_try_become_server_cleans_stale_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    server_name = f"pdf_editor_test_{uuid.uuid4().hex}"
    removed: list[str] = []
    listen_attempts = {"count": 0}
    acquire_attempts = {"count": 0}

    class _FakeLock:
        def removeStaleLockFile(self) -> None:
            removed.append(f"{server_name}:lock")

        def unlock(self) -> None:
            return None

    def fake_probe(_name: str, timeout_ms: int = 500) -> bool:
        return False

    def fake_remove(name: str) -> None:
        removed.append(name)

    def fake_listen(name: str):
        listen_attempts["count"] += 1
        if listen_attempts["count"] == 1:
            return None
        server = QLocalServer()
        assert server.listen(name)
        return server

    def fake_make_lock(_name: str):
        return _FakeLock()

    def fake_try_acquire_lock(_lock) -> bool:
        acquire_attempts["count"] += 1
        return acquire_attempts["count"] > 1

    monkeypatch.setattr(single_instance_module, "_probe_live_server", fake_probe)
    monkeypatch.setattr(single_instance_module, "_remove_server", fake_remove)
    monkeypatch.setattr(single_instance_module, "_listen_server", fake_listen)
    monkeypatch.setattr(single_instance_module, "_make_lock", fake_make_lock)
    monkeypatch.setattr(single_instance_module, "_try_acquire_lock", fake_try_acquire_lock)

    server = single_instance_module.try_become_server(lambda _argv: None, server_name=server_name)
    try:
        assert server is not None
        assert removed == [f"{server_name}:lock", server_name]
        assert listen_attempts["count"] == 2
    finally:
        _cleanup_server(server, server_name)


def test_controller_handle_forwarded_cli_opens_forwarded_files(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
    tmp_path: Path,
) -> None:
    opened: list[str] = []
    initial = tmp_path / "initial.pdf"
    first = tmp_path / "forward-a.pdf"
    second = tmp_path / "forward-b.pdf"
    _make_pdf(initial, "initial")
    _make_pdf(first, "first")
    _make_pdf(second, "second")

    from controller.pdf_controller import PDFController

    def fake_open_pdf(self, path: str) -> None:
        opened.append(path)

    monkeypatch.setattr(PDFController, "open_pdf", fake_open_pdf)

    startup = main_module.run(argv=[str(initial)], start_event_loop=False)
    server_name = f"pdf_editor_test_{uuid.uuid4().hex}"
    server = None
    try:
        controller = startup["controller"]
        assert controller is not None
        server = single_instance_module.try_become_server(controller.handle_forwarded_cli, server_name=server_name)
        assert server is not None
        assert single_instance_module.send_to_running_instance([str(first), str(second)], server_name=server_name)
        expected = [str(first.resolve()), str(second.resolve())]
        assert _pump_until(qapp, lambda: opened[-2:] == expected)
    finally:
        _cleanup_server(server, server_name)
        _cleanup_startup(startup)


def test_primary_close_promotes_secondary_for_forwarding(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
    tmp_path: Path,
) -> None:
    """After the primary window closes, forwarded paths must reach a
    promoted secondary window instead of the dead primary."""
    initial = tmp_path / "primary.pdf"
    forward = tmp_path / "forward.pdf"
    _make_pdf(initial, "primary")
    _make_pdf(forward, "forward")

    from controller.pdf_controller import PDFController

    opened_by: list[tuple[int, str]] = []

    def tracking_open(self, path: str) -> None:
        opened_by.append((id(self), path))

    monkeypatch.setattr(PDFController, "open_pdf", tracking_open)

    startup = main_module.run(argv=[str(initial)], start_event_loop=False)
    primary_controller = startup["controller"]
    primary_view = startup["view"]
    assert primary_controller is not None

    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    sec_view = PDFView()
    sec_view.apply_initial_theme()
    sec_model = PDFModel()
    sec_controller = PDFController(sec_model, sec_view)
    sec_view.controller = sec_controller
    sec_controller.activate()
    sec_context = {
        "model": sec_model,
        "view": sec_view,
        "controller": sec_controller,
    }
    startup["secondary_windows"].append(sec_context)
    sec_view.show()
    qapp.processEvents()

    primary_view.close()
    qapp.processEvents()

    assert startup["controller"] is sec_controller
    assert startup["view"] is sec_view
    assert startup["model"] is sec_model
    assert sec_context not in startup["secondary_windows"]

    sec_view.close()
    sec_model.close()
    startup.get("model") and startup["model"].close()
    qapp.processEvents()


def test_allow_running_instance_foreground_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    class _User32:
        def AllowSetForegroundWindow(self, process_id: int) -> int:
            calls.append(process_id)
            return 1

    fake_ctypes = type("FakeCtypes", (), {"windll": type("Windll", (), {"user32": _User32()})()})()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    single_instance_module._allow_running_instance_foreground()

    assert calls == [-1]
