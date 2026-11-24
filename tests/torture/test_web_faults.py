"""Web server fault-injection, exception safety, and pre-read header bounds tests (TC-046)."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from typing import Any

import pytest

from casper import commands
from casper.web.server import App, make_server

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_NOTES = REPO_ROOT / "tests" / "fixtures" / "status_notes.md"


def _read_http_head_and_body(sock: socket.socket) -> tuple[str, dict[str, str], bytes]:
    chunks: list[bytes] = []
    while True:
        part = sock.recv(4096)
        if not part:
            break
        chunks.append(part)
        joined = b"".join(chunks)
        if b"\r\n\r\n" in joined:
            head_raw, rest = joined.split(b"\r\n\r\n", 1)
            lines = head_raw.decode("iso-8859-1").split("\r\n")
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            cl = int(headers.get("content-length", "0"))
            while len(rest) < cl:
                more = sock.recv(4096)
                if not more:
                    break
                rest += more
            return lines[0], headers, rest[:cl]
    raise AssertionError("Did not receive a complete HTTP response")


def test_tc046_unhandled_exception_returns_500_without_traceback_and_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = App(port=8731, authors_dir=tmp_path / "authors")
    orig_write_draft = commands.write_draft
    calls = 0

    def _fault_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom-secret-traceback-detail")
        return orig_write_draft(*args, **kwargs)

    monkeypatch.setattr(commands, "write_draft", _fault_once)

    notes = STATUS_NOTES.read_text(encoding="utf-8")
    headers = {"Host": "127.0.0.1:8731", "Content-Type": "application/json"}
    body = json.dumps(
        {
            "structure": "status_update",
            "modality": "slack",
            "source": "developer",
            "target": "management",
            "notes": notes,
        }
    ).encode("utf-8")

    err_resp = app.handle("POST", "/api/generate", headers, body)
    assert err_resp.status == 500
    err_text = err_resp.body.decode("utf-8")
    assert json.loads(err_text) == {"error": "Internal server error", "code": "internal-error"}
    assert "boom-secret-traceback-detail" not in err_text
    assert "Traceback" not in err_text
    assert not app._lock.locked()

    ok_resp = app.handle("POST", "/api/generate", headers, body)
    assert ok_resp.status == 200


@pytest.mark.loopback
def test_tc046_preread_content_length_and_chunked_rejection(tmp_path: Path) -> None:
    server = make_server("127.0.0.1", 0, authors_dir=tmp_path / "authors")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port

    try:
        # 1. Oversized Content-Length (300000 > 262144) rejected BEFORE reading body
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            raw_req = (
                f"POST /api/generate HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: 300000\r\n"
                f"\r\n"
            ).encode("ascii")
            sock.sendall(raw_req)
            status_line, _, resp_body = _read_http_head_and_body(sock)
            assert " 413 " in status_line
            payload = json.loads(resp_body.decode("utf-8"))
            assert payload["code"] == "payload-too-large"

        # 2. Transfer-Encoding: chunked rejected immediately with 411 length-required
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            raw_req = (
                f"POST /api/generate HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Transfer-Encoding: chunked\r\n"
                f"\r\n"
            ).encode("ascii")
            sock.sendall(raw_req)
            status_line, _, resp_body = _read_http_head_and_body(sock)
            assert " 411 " in status_line
            payload = json.loads(resp_body.decode("utf-8"))
            assert payload["code"] == "length-required"
    finally:
        server.shutdown()
        server.server_close()
