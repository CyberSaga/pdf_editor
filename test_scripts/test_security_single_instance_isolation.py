"""Security patch P2 (finding F6): single-instance IPC user-isolation.

Two hardening measures:
  1. The QLocalServer is created with ``UserAccessOption`` so the named pipe /
     unix socket is restricted to the current user (CWE-306/CWE-668).
  2. ``_handle_socket_message`` validates forwarded argv: an absolute path that
     does not exist or is not a ``.pdf`` causes the whole message to be rejected
     (ack ``0``), so a local peer cannot drive the running instance to open
     arbitrary files.
"""

from __future__ import annotations

import json

from PySide6.QtNetwork import QLocalServer

from utils import single_instance as si


def test_listen_server_enables_user_access_option(qapp) -> None:
    server = si._listen_server("pdf_editor_test_useraccess")
    try:
        assert server is not None
        options = server.socketOptions()
        assert bool(options & QLocalServer.SocketOption.UserAccessOption)
    finally:
        if server is not None:
            server.close()
            server.deleteLater()
        QLocalServer.removeServer("pdf_editor_test_useraccess")


class _FakeSocket:
    """Minimal stand-in for QLocalSocket used by _handle_socket_message."""

    def __init__(self, payload: bytes) -> None:
        self._props: dict[str, object] = {}
        self._read = payload
        self.written = b""

    def property(self, key: str) -> object:
        return self._props.get(key)

    def setProperty(self, key: str, value: object) -> None:
        self._props[key] = value

    def readAll(self) -> bytes:
        data = self._read
        self._read = b""
        return data

    def write(self, data: bytes) -> None:
        self.written += bytes(data)

    def flush(self) -> None:
        return None

    def waitForBytesWritten(self, _ms: int) -> bool:
        return True

    def disconnectFromServer(self) -> None:
        return None


def _run_message(argv: list[str]) -> tuple[list[list[str]], bytes]:
    received: list[list[str]] = []
    payload = json.dumps({"argv": argv}, ensure_ascii=False).encode("utf-8") + b"\n"
    socket = _FakeSocket(payload)
    si._handle_socket_message(socket, received.append)
    return received, socket.written


def test_handle_socket_message_rejects_nonexistent_path(tmp_path) -> None:
    missing = str(tmp_path / "missing.pdf")  # absolute, does not exist
    received, ack = _run_message([missing])
    assert received == []
    assert ack == b"0\n"


def test_handle_socket_message_rejects_non_pdf_path(tmp_path) -> None:
    txt = tmp_path / "real.txt"
    txt.write_text("hello")
    received, ack = _run_message([str(txt)])  # absolute, exists, wrong suffix
    assert received == []
    assert ack == b"0\n"


def test_handle_socket_message_accepts_existing_pdf(tmp_path) -> None:
    pdf = tmp_path / "real.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    received, ack = _run_message([str(pdf)])
    assert received == [[str(pdf)]]
    assert ack == b"1\n"
