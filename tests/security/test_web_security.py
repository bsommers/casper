"""TC-032 & TC-033: Web server security boundary, XSS escaping, and static JS safety tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from casper.errors import SecurityError
from casper.web.server import (
    MAX_BODY_BYTES,
    SECURITY_HEADERS,
    STATIC_ROOT,
    App,
    HttpResponse,
    make_server,
)

_HOST_HEADERS: dict[str, str] = {"Host": "127.0.0.1:8731"}
_JSON_HEADERS: dict[str, str] = {
    "Host": "127.0.0.1:8731",
    "Content-Type": "application/json",
}


def _assert_security_headers(resp: HttpResponse) -> None:
    for header, expected in SECURITY_HEADERS.items():
        assert resp.headers.get(header) == expected


def _post_json(app: App, path: str, payload: Any, headers: dict[str, str] | None = None) -> HttpResponse:
    hdrs = headers if headers is not None else _JSON_HEADERS
    return app.handle("POST", path, hdrs, json.dumps(payload).encode("utf-8"))


def test_tc032_make_server_refuses_non_loopback_bind() -> None:
    with pytest.raises(SecurityError):
        make_server("0.0.0.0", 0)


def test_tc032_missing_host_http10_rejected_403(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = app.handle("GET", "/", {})
    assert resp.status == 403
    _assert_security_headers(resp)


@pytest.mark.parametrize(
    "bad_host",
    [
        "evil.com:8731",
        "localhost:8731@evil.com",
        "127.0.0.1:9999",
        "localhost:8731 ",
    ],
)
def test_tc032_bad_host_rejected_403(tmp_path: Path, bad_host: str) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = app.handle("GET", "/", {"Host": bad_host})
    assert resp.status == 403
    _assert_security_headers(resp)


@pytest.mark.parametrize(
    "bad_origin",
    [
        "http://evil.com",
        "https://127.0.0.1:8731",
        "http://localhost:9999",
    ],
)
def test_tc032_foreign_origin_rejected_403(tmp_path: Path, bad_origin: str) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = app.handle("GET", "/api/options", {**_HOST_HEADERS, "Origin": bad_origin})
    assert resp.status == 403
    _assert_security_headers(resp)


@pytest.mark.parametrize(
    "good_origin",
    [
        "http://localhost:8731",
        "http://127.0.0.1:8731",
    ],
)
def test_tc032_loopback_origin_allowed_200(tmp_path: Path, good_origin: str) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = app.handle("GET", "/api/options", {**_HOST_HEADERS, "Origin": good_origin})
    assert resp.status == 200
    _assert_security_headers(resp)


@pytest.mark.parametrize("bad_sfs", ["cross-site", "same-site"])
def test_tc032_sec_fetch_site_rejected_403(tmp_path: Path, bad_sfs: str) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = app.handle("GET", "/api/options", {**_HOST_HEADERS, "Sec-Fetch-Site": bad_sfs})
    assert resp.status == 403
    _assert_security_headers(resp)


@pytest.mark.parametrize("good_sfs", ["same-origin", "none"])
def test_tc032_sec_fetch_site_allowed_200(tmp_path: Path, good_sfs: str) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = app.handle("GET", "/api/options", {**_HOST_HEADERS, "Sec-Fetch-Site": good_sfs})
    assert resp.status == 200
    _assert_security_headers(resp)


def test_tc032_options_returns_405_with_allow(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = app.handle("OPTIONS", "/api/generate", _HOST_HEADERS)
    assert resp.status == 405
    assert "Allow" in resp.headers
    assert "GET" in resp.headers["Allow"]
    _assert_security_headers(resp)


def test_tc032_non_json_content_type_returns_415(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = app.handle(
        "POST",
        "/api/extract",
        {**_HOST_HEADERS, "Content-Type": "text/plain"},
        b'{"notes": "Status: ok."}',
    )
    assert resp.status == 415
    _assert_security_headers(resp)


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/extract", {"notes": "Status: ok.", "unexpected": 1}),
        (
            "/api/generate",
            {
                "structure": "status_update",
                "modality": "plain",
                "source": "developer",
                "target": "management",
                "notes": "Status: ok.",
                "unexpected": 1,
            },
        ),
        ("/api/score", {"author": "alice", "text": "Hello.", "unexpected": 1}),
    ],
)
def test_tc032_unknown_json_fields_rejected_400(
    tmp_path: Path, path: str, payload: dict[str, Any]
) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = _post_json(app, path, payload)
    assert resp.status == 400
    _assert_security_headers(resp)


def test_tc032_author_path_traversal_403_and_missing_author_404(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")

    gen_traversal = _post_json(
        app,
        "/api/generate",
        {
            "structure": "status_update",
            "modality": "plain",
            "source": "developer",
            "target": "management",
            "notes": "Status: ok.",
            "author": "../etc/passwd",
        },
    )
    assert gen_traversal.status == 403
    assert json.loads(gen_traversal.body.decode("utf-8"))["code"] == "security-error"
    _assert_security_headers(gen_traversal)

    score_traversal = _post_json(
        app,
        "/api/score",
        {"author": "../etc/passwd", "text": "Hello world."},
    )
    assert score_traversal.status == 403
    assert json.loads(score_traversal.body.decode("utf-8"))["code"] == "security-error"
    _assert_security_headers(score_traversal)

    gen_missing = _post_json(
        app,
        "/api/generate",
        {
            "structure": "status_update",
            "modality": "plain",
            "source": "developer",
            "target": "management",
            "notes": "Status: ok.",
            "author": "nonexistent_author",
        },
    )
    assert gen_missing.status == 404
    assert json.loads(gen_missing.body.decode("utf-8"))["code"] == "profile-not-found"
    _assert_security_headers(gen_missing)

    score_missing = _post_json(
        app,
        "/api/score",
        {"author": "nonexistent_author", "text": "Hello world."},
    )
    assert score_missing.status == 404
    assert json.loads(score_missing.body.decode("utf-8"))["code"] == "profile-not-found"
    _assert_security_headers(score_missing)


@pytest.mark.parametrize(
    "traversal_path",
    [
        "/static/..%2f..%2fpyproject.toml",
        "/static/..%252f..%252fpyproject.toml",
        "/static/app.js%00.png",
        "/static/..\\pyproject.toml",
        "/static/../server.py",
    ],
)
def test_tc032_static_path_traversal_rejected_404(tmp_path: Path, traversal_path: str) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = app.handle("GET", traversal_path, _HOST_HEADERS)
    assert resp.status == 404
    _assert_security_headers(resp)


def test_tc032_mandatory_security_headers_across_status_codes(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")

    responses: dict[int, HttpResponse] = {
        200: app.handle("GET", "/api/options", _HOST_HEADERS),
        400: app.handle("POST", "/api/extract", _JSON_HEADERS, b"[]"),
        403: app.handle("GET", "/", {"Host": "evil.com:8731"}),
        404: app.handle("GET", "/unknown", _HOST_HEADERS),
        405: app.handle("OPTIONS", "/api/generate", _HOST_HEADERS),
        413: app.handle("POST", "/api/extract", _JSON_HEADERS, b" " * (MAX_BODY_BYTES + 1)),
        415: app.handle(
            "POST",
            "/api/extract",
            {**_HOST_HEADERS, "Content-Type": "text/plain"},
            b"{}",
        ),
        501: _post_json(app, "/api/token", {}),
    }

    for expected_status, resp in responses.items():
        assert resp.status == expected_status
        _assert_security_headers(resp)


def test_tc033_html_article_escapes_script_payload(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = _post_json(
        app,
        "/api/generate",
        {
            "structure": "technical_article",
            "modality": "article",
            "source": "developer",
            "target": "engineering",
            "notes": (
                "Background: Input contained <script>alert(1)</script> during testing.\n"
                "Detail: Output encoding neutralized <script>alert(1)</script> cleanly."
            ),
        },
    )
    assert resp.status == 200
    text = json.loads(resp.body.decode("utf-8"))["text"]
    assert "<script>" not in text.lower()
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text


def test_tc033_static_app_js_has_no_unsafe_dom_sinks() -> None:
    app_js = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "document.write", "insertAdjacentHTML", "eval("):
        assert sink not in app_js
