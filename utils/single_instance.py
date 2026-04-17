from __future__ import annotations

import getpass
import json
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_ACTIVE_SERVERS: dict[str, QLocalServer] = {}


def _build_server_name() -> str:
    user = getpass.getuser().strip() or "default"
    safe_user = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in user)
    return f"pdf_editor_singleinstance_{safe_user}"


def _remove_server(name: str) -> None:
    QLocalServer.removeServer(name)


def _listen_server(name: str) -> QLocalServer | None:
    server = QLocalServer()
    if server.listen(name):
        return server
    server.deleteLater()
    return None


def _probe_live_server(name: str, timeout_ms: int = 500) -> bool:
    socket = QLocalSocket()
    try:
        socket.connectToServer(name)
        return socket.waitForConnected(timeout_ms)
    finally:
        socket.abort()
        socket.deleteLater()


def _make_lock(name: str) -> QLockFile:
    lock = QLockFile(str(Path(tempfile.gettempdir()) / f"{name}.lock"))
    lock.setStaleLockTime(5000)
    return lock


def _try_acquire_lock(lock: QLockFile) -> bool:
    return lock.tryLock(0)


def _process_events() -> None:
    app = QCoreApplication.instance()
    if app is not None:
        app.processEvents()


def _wait_for_ready_read(socket: QLocalSocket, timeout_ms: int) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if socket.bytesAvailable() > 0:
            return True
        _process_events()
        if socket.waitForReadyRead(25):
            return True
    return socket.bytesAvailable() > 0


def _service_local_server(name: str) -> None:
    server = _ACTIVE_SERVERS.get(name)
    if server is None:
        return
    server.waitForNewConnection(0)
    accept_pending = getattr(server, "_single_instance_accept_pending", None)
    if callable(accept_pending):
        accept_pending()
    on_message = getattr(server, "_single_instance_on_message", None)
    sockets = list(getattr(server, "_single_instance_sockets", []))
    if callable(on_message):
        for socket in sockets:
            socket.waitForReadyRead(100)
            if socket.bytesAvailable() > 0:
                _handle_socket_message(socket, on_message)
    _process_events()


def _normalize_forwarded_argv(argv: list[str]) -> list[str]:
    return [str(Path(item).resolve()) for item in argv]


def _handle_socket_message(
    socket: QLocalSocket,
    on_message: Callable[[list[str]], None],
) -> None:
    raw_buffer = socket.property("payload_buffer")
    if isinstance(raw_buffer, bytes):
        buffer = raw_buffer
    else:
        buffer = b""
    buffer += bytes(socket.readAll())
    if b"\n" not in buffer:
        socket.setProperty("payload_buffer", buffer)
        return

    line, remainder = buffer.split(b"\n", 1)
    socket.setProperty("payload_buffer", remainder)
    ok = False
    try:
        payload = json.loads(line.decode("utf-8"))
        argv = payload.get("argv")
        if isinstance(argv, list) and all(isinstance(item, str) for item in argv):
            on_message(list(argv))
            ok = True
    except Exception:
        ok = False

    socket.write(b"1\n" if ok else b"0\n")
    socket.flush()
    socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()


def try_become_server(
    on_message: Callable[[list[str]], None],
    *,
    server_name: str | None = None,
) -> QLocalServer | None:
    name = server_name or _build_server_name()
    lock = _make_lock(name)
    if not _try_acquire_lock(lock):
        if hasattr(lock, "removeStaleLockFile") and not _probe_live_server(name):
            lock.removeStaleLockFile()
            if not _try_acquire_lock(lock):
                return None
        else:
            return None

    server = _listen_server(name)
    if server is None and not _probe_live_server(name):
        _remove_server(name)
        server = _listen_server(name)
    if server is None:
        lock.unlock()
        return None

    setattr(server, "_single_instance_on_message", on_message)
    setattr(server, "_single_instance_sockets", [])

    def _accept_pending() -> None:
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            if socket is None:
                continue
            socket.setParent(server)
            getattr(server, "_single_instance_sockets").append(socket)
            socket.readyRead.connect(lambda socket=socket: _handle_socket_message(socket, on_message))
            socket.disconnected.connect(
                lambda socket=socket: getattr(server, "_single_instance_sockets").remove(socket)
                if socket in getattr(server, "_single_instance_sockets")
                else None
            )
            socket.disconnected.connect(socket.deleteLater)

    server.newConnection.connect(_accept_pending)
    setattr(server, "_single_instance_accept_pending", _accept_pending)
    _ACTIVE_SERVERS[name] = server
    server.destroyed.connect(lambda *_args, server_name=name: _ACTIVE_SERVERS.pop(server_name, None))
    server.destroyed.connect(lambda *_args: lock.unlock())
    setattr(server, "_single_instance_lock", lock)
    return server


def send_to_running_instance(
    argv: list[str],
    *,
    server_name: str | None = None,
    timeout_ms: int = 2000,
) -> bool:
    name = server_name or _build_server_name()
    normalized_argv = _normalize_forwarded_argv(argv)
    local_server = _ACTIVE_SERVERS.get(name)
    if local_server is not None:
        on_message = getattr(local_server, "_single_instance_on_message", None)
        if callable(on_message):
            on_message(normalized_argv)
            return True

    socket = QLocalSocket()
    try:
        socket.connectToServer(name)
        if not socket.waitForConnected(timeout_ms):
            return False
        _service_local_server(name)
        payload = json.dumps({"argv": normalized_argv}, ensure_ascii=False).encode("utf-8") + b"\n"
        socket.write(payload)
        socket.flush()
        if not socket.waitForBytesWritten(timeout_ms):
            return False
        _service_local_server(name)
        if not _wait_for_ready_read(socket, timeout_ms):
            return False
        ack = bytes(socket.readAll()).strip()
        return ack.startswith(b"1")
    finally:
        socket.abort()
        socket.deleteLater()
