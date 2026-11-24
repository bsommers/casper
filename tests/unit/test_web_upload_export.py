"""Unit tests for /api/formats, /api/upload, and /api/export web endpoints."""

from __future__ import annotations

import base64
import json
import socket
import threading
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from casper.loaders import SUPPORTED_UPLOAD_EXTENSIONS
from casper.modalities import EXPORT_FORMATS, export_document
from casper.web.server import (
    MAX_BODY_BYTES,
    MAX_SCORE_TEXT_CHARS,
    MAX_UPLOAD_BODY_BYTES,
    MAX_UPLOAD_RAW_BYTES,
    SECURITY_HEADERS,
    App,
    HttpResponse,
    make_server,
)

_HOST_HEADERS: dict[str, str] = {"Host": "127.0.0.1:8731"}
_JSON_HEADERS: dict[str, str] = {
    "Host": "127.0.0.1:8731",
    "Content-Type": "application/json",
}

_ALL_EXPORT_FORMATS: tuple[str, ...] = (
    "txt",
    "md",
    "adoc",
    "html",
    "pdf",
    "docx",
    "odt",
    "rtf",
    "tex",
    "rst",
    "org",
    "json",
)

_SAMPLE_TEXT = (
    "## Status Summary\n\n"
    "API migration completed on schedule with zero downtime.\n\n"
    "- Integration suite passed across all environments.\n"
    "- Canary rollout begins tomorrow morning."
)


def _assert_security_headers(resp: HttpResponse) -> None:
    for header, expected in SECURITY_HEADERS.items():
        assert resp.headers.get(header) == expected


def _post_json(
    app: App,
    path: str,
    payload: Any,
    headers: dict[str, str] | None = None,
) -> HttpResponse:
    hdrs = headers if headers is not None else _JSON_HEADERS
    body = json.dumps(payload).encode("utf-8")
    return app.handle("POST", path, hdrs, body)


def _decode_json(resp: HttpResponse) -> dict[str, Any]:
    parsed = json.loads(resp.body.decode("utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def test_get_formats_returns_extensions_and_12_export_formats(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = app.handle("GET", "/api/formats", _HOST_HEADERS)
    assert resp.status == 200
    _assert_security_headers(resp)

    data = _decode_json(resp)
    assert data["upload_extensions"] == list(SUPPORTED_UPLOAD_EXTENSIONS)
    assert len(data["upload_extensions"]) >= 8

    export_entries = data["export_formats"]
    assert len(export_entries) == 12
    assert len(export_entries) == len(EXPORT_FORMATS)
    ids = [entry["id"] for entry in export_entries]
    assert set(ids) == set(_ALL_EXPORT_FORMATS)
    for entry in export_entries:
        fmt_id = entry["id"]
        label, ext, mime = EXPORT_FORMATS[fmt_id]
        assert entry == {
            "id": fmt_id,
            "label": label,
            "extension": ext,
            "mime": mime,
        }


@pytest.mark.parametrize(
    ("ext", "export_fmt"),
    [
        (".txt", "txt"),
        (".md", "md"),
        (".adoc", "adoc"),
        (".rtf", "rtf"),
        (".tex", "tex"),
        (".docx", "docx"),
        (".odt", "odt"),
        (".pdf", "pdf"),
    ],
)
def test_post_upload_supported_formats(tmp_path: Path, ext: str, export_fmt: str) -> None:
    app = App(authors_dir=tmp_path / "authors")
    payload_bytes, _, _ = export_document(_SAMPLE_TEXT, export_fmt, title="Weekly Status")
    encoded = base64.b64encode(payload_bytes).decode("ascii")

    resp = _post_json(
        app,
        "/api/upload",
        {"filename": f"notes{ext}", "content_base64": encoded},
    )
    assert resp.status == 200
    _assert_security_headers(resp)

    data = _decode_json(resp)
    assert data["filename"] == f"notes{ext}"
    assert isinstance(data["format"], str) and data["format"]
    assert "API migration completed" in data["text"]
    assert data["word_count"] == len(data["text"].split())
    assert data["word_count"] > 5
    assert isinstance(data["notes"], list)


@pytest.mark.parametrize(
    "bad_filename",
    [
        "",
        "   ",
        "../secret.txt",
        "dir/file.txt",
        "dir\\file.txt",
        "bad\x00name.txt",
        ".",
        "..",
    ],
)
def test_post_upload_bad_filename_rejected_400(tmp_path: Path, bad_filename: str) -> None:
    app = App(authors_dir=tmp_path / "authors")
    encoded = base64.b64encode(b"Status: ok.").decode("ascii")
    resp = _post_json(
        app,
        "/api/upload",
        {"filename": bad_filename, "content_base64": encoded},
    )
    assert resp.status == 400
    assert _decode_json(resp)["code"] == "input-error"
    _assert_security_headers(resp)


def test_post_upload_validation_and_bounds(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")

    # Bad base64 -> 400
    bad_b64 = _post_json(
        app,
        "/api/upload",
        {"filename": "notes.txt", "content_base64": "!!!not-base64!!!"},
    )
    assert bad_b64.status == 400
    assert _decode_json(bad_b64)["code"] == "input-error"
    _assert_security_headers(bad_b64)

    # Unknown field -> 400
    unknown_field = _post_json(
        app,
        "/api/upload",
        {
            "filename": "notes.txt",
            "content_base64": base64.b64encode(b"Status: ok.").decode("ascii"),
            "extra": True,
        },
    )
    assert unknown_field.status == 400
    assert _decode_json(unknown_field)["code"] == "input-error"
    _assert_security_headers(unknown_field)

    # Empty / unreadable text -> 400
    empty_txt = _post_json(
        app,
        "/api/upload",
        {"filename": "empty.txt", "content_base64": base64.b64encode(b"   \n\t  ").decode("ascii")},
    )
    assert empty_txt.status == 400
    assert _decode_json(empty_txt)["code"] == "input-error"
    _assert_security_headers(empty_txt)

    # Oversized raw JSON body (> MAX_UPLOAD_BODY_BYTES) -> 413
    oversized_body = b" " * (MAX_UPLOAD_BODY_BYTES + 1)
    resp_over_body = app.handle("POST", "/api/upload", _JSON_HEADERS, oversized_body)
    assert resp_over_body.status == 413
    assert _decode_json(resp_over_body)["code"] == "payload-too-large"
    _assert_security_headers(resp_over_body)

    # Oversized decoded raw bytes (> MAX_UPLOAD_RAW_BYTES) -> 413
    # (note: base64 of 1.5 MiB + 1 byte is slightly over 2 MiB, so test decoded > MAX_SCORE_TEXT_CHARS too)
    over_text = ("word " * ((MAX_SCORE_TEXT_CHARS // 5) + 5)).encode("utf-8")
    assert len(over_text) > MAX_SCORE_TEXT_CHARS
    resp_over_text = _post_json(
        app,
        "/api/upload",
        {
            "filename": "huge.txt",
            "content_base64": base64.b64encode(over_text).decode("ascii"),
        },
    )
    assert resp_over_text.status == 413
    assert _decode_json(resp_over_text)["code"] == "payload-too-large"
    _assert_security_headers(resp_over_text)

    # Non-JSON Content-Type -> 415
    resp_415 = app.handle(
        "POST",
        "/api/upload",
        {**_HOST_HEADERS, "Content-Type": "text/plain"},
        b"{}",
    )
    assert resp_415.status == 415
    _assert_security_headers(resp_415)

    # Security boundary checks on /api/upload (foreign Origin / Sec-Fetch-Site -> 403)
    resp_403 = _post_json(
        app,
        "/api/upload",
        {"filename": "notes.txt", "content_base64": base64.b64encode(b"ok").decode("ascii")},
        headers={**_JSON_HEADERS, "Origin": "http://evil.com"},
    )
    assert resp_403.status == 403
    _assert_security_headers(resp_403)


def test_post_upload_raw_bytes_limit_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import casper.web.server as srv

    assert MAX_UPLOAD_RAW_BYTES == 1_572_864
    app = App(authors_dir=tmp_path / "authors")
    monkeypatch.setattr(srv, "MAX_UPLOAD_RAW_BYTES", 16)
    encoded = base64.b64encode(b"x" * 17).decode("ascii")
    resp = _post_json(
        app,
        "/api/upload",
        {"filename": "over.txt", "content_base64": encoded},
    )
    assert resp.status == 413
    assert _decode_json(resp)["code"] == "payload-too-large"
    _assert_security_headers(resp)


@pytest.mark.parametrize("fmt", _ALL_EXPORT_FORMATS)
def test_post_export_all_12_formats(tmp_path: Path, fmt: str) -> None:
    app = App(authors_dir=tmp_path / "authors")
    payload: dict[str, Any] = {
        "format": fmt,
        "text": _SAMPLE_TEXT,
        "title": "Q4 Launch Update",
        "facts": [{"id": "f001", "kind": "status", "text": "API migration completed."}],
        "fact_trace": [{"sentence": "API migration completed.", "fact_ids": ["f001"]}],
        "validation": {"ok": True},
        "record": {"seed": 0},
    }

    resp = _post_json(app, "/api/export", payload)
    assert resp.status == 200
    _assert_security_headers(resp)

    disp = resp.headers.get("Content-Disposition", "")
    assert disp.startswith('attachment; filename="')
    assert disp.endswith('"')
    _, expected_ext, expected_mime = EXPORT_FORMATS[fmt]
    assert f".{expected_ext}" in disp
    assert resp.headers.get("Content-Type") == expected_mime
    assert len(resp.body) > 0

    if fmt == "pdf":
        assert resp.body.startswith(b"%PDF-")
    elif fmt == "rtf":
        assert resp.body.startswith(b"{\\rtf")
    elif fmt == "docx":
        with zipfile.ZipFile(BytesIO(resp.body)) as zf:
            assert "word/document.xml" in zf.namelist()
    elif fmt == "odt":
        with zipfile.ZipFile(BytesIO(resp.body)) as zf:
            assert "content.xml" in zf.namelist()
    elif fmt == "json":
        parsed = json.loads(resp.body.decode("utf-8"))
        assert parsed["title"] == "Q4 Launch Update"
        assert "API migration completed" in parsed["text"]
    elif fmt == "html":
        decoded = resp.body.decode("utf-8")
        assert "<html" in decoded.lower()
        assert "API migration completed" in decoded
    else:
        decoded = resp.body.decode("utf-8")
        assert "API migration completed" in decoded


def test_post_export_validation_and_security(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")

    # Unknown format -> 400
    bad_fmt = _post_json(app, "/api/export", {"format": "bogus", "text": "Hello."})
    assert bad_fmt.status == 400
    assert _decode_json(bad_fmt)["code"] == "input-error"
    _assert_security_headers(bad_fmt)

    # Unknown field -> 400
    unknown_field = _post_json(
        app,
        "/api/export",
        {"format": "txt", "text": "Hello.", "unexpected": 1},
    )
    assert unknown_field.status == 400
    assert _decode_json(unknown_field)["code"] == "input-error"
    _assert_security_headers(unknown_field)

    # Oversized text (> MAX_SCORE_TEXT_CHARS) -> 413
    over_text = "a" * (MAX_SCORE_TEXT_CHARS + 1)
    resp_over = _post_json(app, "/api/export", {"format": "txt", "text": over_text})
    assert resp_over.status == 413
    assert _decode_json(resp_over)["code"] == "payload-too-large"
    _assert_security_headers(resp_over)

    # Oversized raw body (> MAX_BODY_BYTES) -> 413 (strictly enforced on /api/export)
    resp_over_body = app.handle("POST", "/api/export", _JSON_HEADERS, b" " * (MAX_BODY_BYTES + 1))
    assert resp_over_body.status == 413
    assert _decode_json(resp_over_body)["code"] == "payload-too-large"
    _assert_security_headers(resp_over_body)

    # Sec-Fetch-Site cross-site -> 403
    resp_403 = _post_json(
        app,
        "/api/export",
        {"format": "txt", "text": "Hello."},
        headers={**_JSON_HEADERS, "Sec-Fetch-Site": "cross-site"},
    )
    assert resp_403.status == 403
    _assert_security_headers(resp_403)

    # Wrong method on /api/formats, /api/upload, /api/export -> 405
    assert app.handle("POST", "/api/formats", _HOST_HEADERS).status == 405
    assert app.handle("GET", "/api/upload", _HOST_HEADERS).status == 405
    assert app.handle("GET", "/api/export", _HOST_HEADERS).status == 405


@pytest.mark.loopback
def test_live_loopback_upload_vs_generate_body_caps(tmp_path: Path) -> None:
    server = make_server("127.0.0.1", 0, authors_dir=tmp_path / "authors")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port

    def _send_and_read_status(raw: bytes) -> str:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.sendall(raw)
            buf = b""
            while b"\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            return buf.split(b"\r\n", 1)[0].decode("iso-8859-1")

    try:
        # /api/generate strictly rejects > MAX_BODY_BYTES pre-read
        gen_status = _send_and_read_status(
            (
                f"POST /api/generate HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {MAX_BODY_BYTES + 1}\r\n\r\n"
            ).encode("ascii")
        )
        assert " 413 " in gen_status

        # /api/upload strictly rejects > MAX_UPLOAD_BODY_BYTES pre-read
        up_over_status = _send_and_read_status(
            (
                f"POST /api/upload HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {MAX_UPLOAD_BODY_BYTES + 1}\r\n\r\n"
            ).encode("ascii")
        )
        assert " 413 " in up_over_status
    finally:
        server.shutdown()
        server.server_close()
