"""TC-025 & App.handle unit tests for Casper's localhost web server."""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from casper.errors import CasperError
from casper.profile import build_profile, save_profile
from casper.web.server import (
    MAX_BODY_BYTES,
    MAX_NOTES_CHARS,
    MAX_SCORE_TEXT_CHARS,
    App,
    HttpResponse,
    make_server,
)

_HOST_HEADERS: dict[str, str] = {"Host": "127.0.0.1:8731"}
_JSON_HEADERS: dict[str, str] = {
    "Host": "127.0.0.1:8731",
    "Content-Type": "application/json",
}


def _make_fake_runner() -> Any:
    def runner(
        argv: Sequence[str],
        cwd: Path,
        timeout: float,
        env: Mapping[str, str],
    ) -> tuple[int, str, str]:
        if "--version" in argv:
            return (0, f"{Path(argv[0]).name} 1.0.0-test", "")
        return (0, "", "")

    return runner


def _create_synthetic_author(authors_dir: Path, tmp_path: Path, author_id: str = "alice") -> Path:
    doc_path = tmp_path / f"{author_id}_corpus.md"
    prose = " ".join(
        ["We build deterministic systems with clear tests and measured latency."] * 22
    )
    doc_path.write_text(f"---\ntitle: Notes\nauthor: {author_id}\n---\n\n{prose}\n", encoding="utf-8")
    profile = build_profile(author_id, "Alice Author", [doc_path], min_words=150)
    saved = save_profile(authors_dir / f"{author_id}.yaml", profile)
    curated_path = authors_dir / f"{author_id}.curated.yaml"
    curated_path.write_text(
        yaml.safe_dump(
            {
                "overlays": {
                    "slack": {
                        "pins": {
                            "mean_sentence_length": {"value": 10.0},
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return saved


def _post_json(app: App, path: str, payload: Any) -> HttpResponse:
    body = json.dumps(payload).encode("utf-8")
    return app.handle("POST", path, _JSON_HEADERS, body)


def _decode_json(resp: HttpResponse) -> dict[str, Any]:
    parsed = json.loads(resp.body.decode("utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def test_static_routes_and_404(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")

    root = app.handle("GET", "/", _HOST_HEADERS)
    assert root.status == 200
    assert root.headers["Content-Type"].startswith("text/html")
    assert b"<!doctype html>" in root.body.lower()

    js = app.handle("GET", "/static/app.js", _HOST_HEADERS)
    assert js.status == 200
    assert js.headers["Content-Type"].startswith("application/javascript")
    assert len(js.body) > 0

    css = app.handle("GET", "/static/theme.css", _HOST_HEADERS)
    assert css.status == 200
    assert css.headers["Content-Type"].startswith("text/css")
    assert len(css.body) > 0

    svg = app.handle("GET", "/static/img/casper-mark.svg", _HOST_HEADERS)
    assert svg.status == 200
    assert svg.headers["Content-Type"] == "image/svg+xml"
    assert b"<svg" in svg.body

    missing_static = app.handle("GET", "/static/nonexistent.txt", _HOST_HEADERS)
    assert missing_static.status == 404
    assert _decode_json(missing_static)["code"] == "not-found"

    unknown_route = app.handle("GET", "/unknown", _HOST_HEADERS)
    assert unknown_route.status == 404
    assert _decode_json(unknown_route)["code"] == "not-found"


def test_get_options_and_backend_status_with_fake_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authors_dir = tmp_path / "authors"
    _create_synthetic_author(authors_dir, tmp_path, "alice")
    monkeypatch.setattr("casper.llm.shutil.which", lambda cmd: f"/usr/bin/{cmd}")

    app = App(authors_dir=authors_dir, runner=_make_fake_runner())

    opts_resp = app.handle("GET", "/api/options", _HOST_HEADERS)
    assert opts_resp.status == 200
    opts = _decode_json(opts_resp)
    assert "personas" in opts
    assert "structures" in opts
    assert "modalities" in opts
    assert [a["id"] for a in opts["authors"]] == ["alice"]
    assert opts["backends"] == ["rules", "claude", "agy"]

    status_resp = app.handle("GET", "/api/backend-status", _HOST_HEADERS)
    assert status_resp.status == 200
    status_data = _decode_json(status_resp)
    backends = status_data["backends"]
    assert backends["rules"]["available"] is True
    assert backends["claude"]["available"] is True
    assert "1.0.0-test" in (backends["claude"]["version"] or "")
    assert backends["agy"]["available"] is True


def test_post_extract_with_and_without_fact_overrides(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")
    notes = "Status: API rollout is on track.\nRisk: Cold start latency spiked."

    resp1 = _post_json(app, "/api/extract", {"notes": notes})
    assert resp1.status == 200
    data1 = _decode_json(resp1)
    assert len(data1["facts"]) >= 2
    assert isinstance(data1["warnings"], list)
    first_id = data1["facts"][0]["id"]

    resp2 = _post_json(
        app,
        "/api/extract",
        {"notes": notes, "fact_overrides": {first_id: "metric"}},
    )
    assert resp2.status == 200
    data2 = _decode_json(resp2)
    overridden = next(f for f in data2["facts"] if f["id"] == first_id)
    assert overridden["kind"] == "metric"


def test_post_generate_with_and_without_author(tmp_path: Path) -> None:
    authors_dir = tmp_path / "authors"
    _create_synthetic_author(authors_dir, tmp_path, "alice")
    app = App(authors_dir=authors_dir)

    base_payload: dict[str, Any] = {
        "structure": "status_update",
        "modality": "plain",
        "source": "developer",
        "target": "management",
        "notes": (
            "Status: Core API migration is green.\n"
            "Progress: Completed integration tests.\n"
            "Next: Roll out to canary tomorrow."
        ),
        "topic": "API Migration",
        "seed": 7,
        "banned": ["synergy"],
        "fact_overrides": {"f001": "status"},
    }

    resp_no_author = _post_json(app, "/api/generate", base_payload)
    assert resp_no_author.status == 200
    data_no_author = _decode_json(resp_no_author)
    assert data_no_author["text"].strip()
    assert data_no_author["validation"]["ok"] is True
    assert len(data_no_author["fact_trace"]) >= 1
    assert data_no_author["record"]["seed"] == 7
    assert data_no_author["backend"]["requested"] == "rules"
    assert data_no_author["backend"]["used"] == "rules"
    assert data_no_author["record"]["selectors"]["author"] is None
    assert "synergy" not in data_no_author["text"].lower()
    assert data_no_author["facts"][0]["kind"] == "status"

    with_author = dict(base_payload, author="alice")
    resp_author = _post_json(app, "/api/generate", with_author)
    assert resp_author.status == 200
    data_author = _decode_json(resp_author)
    assert data_author["text"].strip()
    assert data_author["validation"]["ok"] is True
    assert data_author["record"]["selectors"]["author"] == "alice"


def test_post_score_raw_overlay_and_conflict(tmp_path: Path) -> None:
    authors_dir = tmp_path / "authors"
    _create_synthetic_author(authors_dir, tmp_path, "alice")
    app = App(authors_dir=authors_dir)

    sample_text = (
        "We build deterministic systems with clear tests. "
        "Measured latency stayed low across every endpoint."
    )

    resp_default = _post_json(app, "/api/score", {"author": "alice", "text": sample_text})
    assert resp_default.status == 200
    assert "report" in _decode_json(resp_default)

    resp_raw = _post_json(app, "/api/score", {"author": "alice", "text": sample_text, "raw": True})
    assert resp_raw.status == 200
    assert "report" in _decode_json(resp_raw)

    resp_overlay = _post_json(
        app,
        "/api/score",
        {"author": "alice", "text": sample_text, "overlay": "slack"},
    )
    assert resp_overlay.status == 200
    assert "report" in _decode_json(resp_overlay)

    resp_both = _post_json(
        app,
        "/api/score",
        {"author": "alice", "text": sample_text, "raw": True, "overlay": "slack"},
    )
    assert resp_both.status == 400
    assert _decode_json(resp_both)["code"] == "input-error"


def test_post_token_returns_501(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = _post_json(app, "/api/token", {})
    assert resp.status == 501
    assert _decode_json(resp)["code"] == "not-implemented"


def test_tc025_payload_boundaries(tmp_path: Path) -> None:
    authors_dir = tmp_path / "authors"
    _create_synthetic_author(authors_dir, tmp_path, "alice")
    app = App(authors_dir=authors_dir)

    # 1. HTTP JSON body cap: 262_144 passes; 262_145 -> 413.
    base_json = b'{"notes":"Status: ok."}'
    exact_body = base_json + b" " * (MAX_BODY_BYTES - len(base_json))
    assert len(exact_body) == MAX_BODY_BYTES
    resp_body_ok = app.handle("POST", "/api/extract", _JSON_HEADERS, exact_body)
    assert resp_body_ok.status != 413
    assert resp_body_ok.status == 200

    over_body = exact_body + b" "
    assert len(over_body) == MAX_BODY_BYTES + 1
    resp_body_over = app.handle("POST", "/api/extract", _JSON_HEADERS, over_body)
    assert resp_body_over.status == 413
    assert _decode_json(resp_body_over)["code"] == "payload-too-large"

    # 2. Notes length cap on /api/extract and /api/generate: 40_000 passes; 40_001 -> 413.
    prefix = "Status: Service healthy. "
    notes_exact = prefix + ("a" * (MAX_NOTES_CHARS - len(prefix)))
    notes_over = notes_exact + "a"
    assert len(notes_exact) == MAX_NOTES_CHARS
    assert len(notes_over) == MAX_NOTES_CHARS + 1

    ext_ok = _post_json(app, "/api/extract", {"notes": notes_exact})
    assert ext_ok.status == 200
    ext_over = _post_json(app, "/api/extract", {"notes": notes_over})
    assert ext_over.status == 413
    assert _decode_json(ext_over)["code"] == "payload-too-large"

    gen_base = {
        "structure": "status_update",
        "modality": "plain",
        "source": "developer",
        "target": "management",
    }
    gen_ok = _post_json(app, "/api/generate", {**gen_base, "notes": notes_exact})
    assert gen_ok.status == 200
    gen_over = _post_json(app, "/api/generate", {**gen_base, "notes": notes_over})
    assert gen_over.status == 413
    assert _decode_json(gen_over)["code"] == "payload-too-large"

    # 3. Score text length cap: 60_000 passes; 60_001 -> 413.
    score_prefix = "We ship reliable code. "
    text_exact = score_prefix + ("a" * (MAX_SCORE_TEXT_CHARS - len(score_prefix)))
    text_over = text_exact + "a"
    assert len(text_exact) == MAX_SCORE_TEXT_CHARS
    assert len(text_over) == MAX_SCORE_TEXT_CHARS + 1

    score_ok = _post_json(app, "/api/score", {"author": "alice", "text": text_exact})
    assert score_ok.status == 200
    score_over = _post_json(app, "/api/score", {"author": "alice", "text": text_over})
    assert score_over.status == 413
    assert _decode_json(score_over)["code"] == "payload-too-large"


@pytest.mark.parametrize(
    ("path", "raw_body"),
    [
        ("/api/extract", b"{not valid json"),
        ("/api/extract", b"[]"),
        ("/api/extract", b"{}"),
        ("/api/extract", json.dumps({"notes": "ok", "fact_overrides": []}).encode("utf-8")),
        (
            "/api/generate",
            json.dumps(
                {
                    "structure": "status_update",
                    "modality": "plain",
                    "source": "developer",
                    "target": "management",
                }
            ).encode("utf-8"),
        ),
        (
            "/api/generate",
            json.dumps(
                {
                    "structure": "status_update",
                    "modality": "plain",
                    "source": "developer",
                    "target": "management",
                    "notes": "Status: ok.",
                    "seed": True,
                }
            ).encode("utf-8"),
        ),
        (
            "/api/generate",
            json.dumps(
                {
                    "structure": "status_update",
                    "modality": "plain",
                    "source": "developer",
                    "target": "management",
                    "notes": "Status: ok.",
                    "seed": "x",
                }
            ).encode("utf-8"),
        ),
        (
            "/api/generate",
            json.dumps(
                {
                    "structure": "status_update",
                    "modality": "plain",
                    "source": "developer",
                    "target": "management",
                    "notes": "Status: ok.",
                    "banned": "x",
                }
            ).encode("utf-8"),
        ),
        (
            "/api/score",
            json.dumps({"author": "alice"}).encode("utf-8"),
        ),
        (
            "/api/score",
            json.dumps({"author": "alice", "text": "Hello world.", "raw": "yes"}).encode("utf-8"),
        ),
    ],
)
def test_malformed_json_wrong_types_and_missing_fields(
    tmp_path: Path, path: str, raw_body: bytes
) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = app.handle("POST", path, _JSON_HEADERS, raw_body)
    assert resp.status == 400
    assert _decode_json(resp)["code"] == "input-error"


@pytest.mark.parametrize(
    ("method", "path", "expected_allow"),
    [
        ("POST", "/api/options", "GET"),
        ("GET", "/api/generate", "POST"),
        ("DELETE", "/api/options", "GET, POST"),
    ],
)
def test_wrong_http_methods_return_405(
    tmp_path: Path, method: str, path: str, expected_allow: str
) -> None:
    app = App(authors_dir=tmp_path / "authors")
    resp = app.handle(method, path, _HOST_HEADERS)
    assert resp.status == 405
    assert resp.headers.get("Allow") == expected_allow
    assert _decode_json(resp)["code"] == "method-not-allowed"


def test_casper_error_to_dict_with_and_without_details() -> None:
    with_details = CasperError("msg", details={"k": "v"}).to_dict()
    assert with_details == {"error": "msg", "code": "casper-error", "details": {"k": "v"}}

    without_details = CasperError("msg").to_dict()
    assert without_details == {"error": "msg", "code": "casper-error"}
    assert "details" not in without_details


def test_generate_branch_coverage_and_validation(tmp_path: Path) -> None:
    app = App(authors_dir=tmp_path / "authors")
    base: dict[str, Any] = {
        "structure": "status_update",
        "modality": "plain",
        "source": "developer",
        "target": "management",
        "notes": "Status: Core API migration is green.",
    }

    resp_ok = _post_json(app, "/api/generate", {**base, "min_voice": 50, "author": "   "})
    assert resp_ok.status == 200
    assert _decode_json(resp_ok)["record"]["selectors"]["author"] is None

    bad_payloads: list[dict[str, Any]] = [
        {**base, "min_voice": True},
        {**base, "min_voice": "bad"},
        {**base, "fallback": "yes"},
        {**base, "banned": [123]},
        {**base, "fact_overrides": {"f001": 123}},
        {**base, "fact_overrides": {"f001": "bogus"}},
        {**base, "topic": 123},
    ]
    for payload in bad_payloads:
        resp = _post_json(app, "/api/generate", payload)
        assert resp.status == 400
        assert _decode_json(resp)["code"] == "input-error"


def test_score_branch_coverage_and_validation(tmp_path: Path) -> None:
    authors_dir = tmp_path / "authors"
    _create_synthetic_author(authors_dir, tmp_path, "alice")
    app = App(authors_dir=authors_dir)

    resp_ok = _post_json(
        app,
        "/api/score",
        {"author": "alice", "text": "We build deterministic systems.", "overlay": "   "},
    )
    assert resp_ok.status == 200

    for payload in (
        {"author": "alice", "text": "We build deterministic systems.", "raw": "notbool"},
        {"author": 123, "text": "We build deterministic systems."},
    ):
        resp = _post_json(app, "/api/score", payload)
        assert resp.status == 400
        assert _decode_json(resp)["code"] == "input-error"


def _send_raw_http(port: int, raw_request: bytes) -> tuple[str, dict[str, str]]:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(raw_request)
        chunks: list[bytes] = []
        while True:
            part = sock.recv(4096)
            if not part:
                break
            chunks.append(part)
            joined = b"".join(chunks)
            if b"\r\n\r\n" in joined:
                head_raw = joined.split(b"\r\n\r\n", 1)[0]
                lines = head_raw.decode("iso-8859-1").split("\r\n")
                hdrs: dict[str, str] = {}
                for line in lines[1:]:
                    if ":" in line:
                        k, v = line.split(":", 1)
                        hdrs[k.strip().lower()] = v.strip()
                return lines[0], hdrs
    raise AssertionError("Incomplete HTTP response")


@pytest.mark.loopback
def test_live_loopback_content_length_and_methods(tmp_path: Path) -> None:
    server = make_server("127.0.0.1", 0, authors_dir=tmp_path / "authors")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port

    try:
        status_411, _ = _send_raw_http(
            port,
            (
                f"POST /api/extract HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Content-Type: application/json\r\n"
                f"\r\n"
            ).encode("ascii"),
        )
        assert " 411 " in status_411

        for bad_cl in ("-5", "abc"):
            status_400, _ = _send_raw_http(
                port,
                (
                    f"POST /api/extract HTTP/1.1\r\n"
                    f"Host: 127.0.0.1:{port}\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {bad_cl}\r\n"
                    f"\r\n"
                ).encode("ascii"),
            )
            assert " 400 " in status_400

        for method, extra in (
            ("PUT", "Content-Length: 0\r\n"),
            ("DELETE", ""),
            ("PATCH", "Content-Length: 0\r\n"),
            ("HEAD", ""),
            ("OPTIONS", ""),
        ):
            status_405, hdrs = _send_raw_http(
                port,
                (
                    f"{method} /api/options HTTP/1.1\r\n"
                    f"Host: 127.0.0.1:{port}\r\n"
                    f"{extra}"
                    f"\r\n"
                ).encode("ascii"),
            )
            assert " 405 " in status_405
            assert hdrs.get("allow") == "GET, POST"
    finally:
        server.shutdown()
        server.server_close()
