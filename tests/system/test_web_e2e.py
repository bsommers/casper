"""Live loopback HTTP E2E tests for the Casper web UI and JSON API (TC-019)."""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from casper import commands
from casper.web.server import SECURITY_HEADERS, make_server

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_NOTES = REPO_ROOT / "tests" / "fixtures" / "status_notes.md"


def _build_synthetic_author(tmp_path: Path) -> Path:
    authors_dir = tmp_path / "authors"
    samples: list[Path] = []
    for idx in (1, 2):
        doc = tmp_path / f"alice_{idx}.md"
        body = " ".join(
            [
                f"We ship fast code (batch {idx}).",
                "Short sentences work!",
                "Can we measure latency?",
                "Yes, we track SLOs daily.",
                "It isn't luck; it's discipline!",
            ]
            * 12
        )
        doc.write_text(
            f'---\ntitle: "Alice Note {idx}"\nauthor: "Alice Tester"\n---\n\n{body}\n',
            encoding="utf-8",
        )
        samples.append(doc)
    commands.author_build("alice", "Alice Tester", samples, authors_dir=authors_dir)
    return authors_dir


def _assert_security_headers(resp: http.client.HTTPResponse) -> None:
    for header, expected in SECURITY_HEADERS.items():
        assert resp.getheader(header) == expected


@pytest.mark.loopback
def test_tc019_web_e2e_all_routes_and_security_headers(tmp_path: Path) -> None:
    authors_dir = _build_synthetic_author(tmp_path)
    notes = STATUS_NOTES.read_text(encoding="utf-8")

    server = make_server("127.0.0.1", 0, authors_dir=authors_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port

    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            # 1. Static routes: /, /static/app.js, /static/img/casper-mark.svg
            for path, expected_ct in (
                ("/", "text/html"),
                ("/static/app.js", "application/javascript"),
                ("/static/img/casper-mark.svg", "image/svg+xml"),
            ):
                conn.request("GET", path)
                resp = conn.getresponse()
                body = resp.read()
                assert resp.status == 200, f"GET {path} returned {resp.status}"
                assert expected_ct in (resp.getheader("Content-Type") or "")
                assert len(body) > 0
                _assert_security_headers(resp)

            # 2. GET /api/options
            conn.request("GET", "/api/options")
            resp = conn.getresponse()
            opts = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 200
            _assert_security_headers(resp)
            assert {"personas", "structures", "modalities", "authors", "backends"} <= set(opts)
            assert any(a["id"] == "alice" for a in opts["authors"])

            # 3. GET /api/backend-status
            conn.request("GET", "/api/backend-status")
            resp = conn.getresponse()
            status_data = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 200
            _assert_security_headers(resp)
            assert {"rules", "claude", "agy"} <= set(status_data["backends"])
            assert status_data["backends"]["rules"]["available"] is True

            json_headers = {"Content-Type": "application/json"}

            # 4. POST /api/extract
            conn.request(
                "POST",
                "/api/extract",
                body=json.dumps({"notes": notes}).encode("utf-8"),
                headers=json_headers,
            )
            resp = conn.getresponse()
            extracted = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 200
            _assert_security_headers(resp)
            assert isinstance(extracted["facts"], list) and len(extracted["facts"]) > 0

            # 5. POST /api/generate
            gen_payload = {
                "structure": "status_update",
                "modality": "slack",
                "source": "developer",
                "target": "management",
                "author": "alice",
                "notes": notes,
                "seed": 0,
            }
            conn.request(
                "POST",
                "/api/generate",
                body=json.dumps(gen_payload).encode("utf-8"),
                headers=json_headers,
            )
            resp = conn.getresponse()
            generated = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 200
            _assert_security_headers(resp)
            assert {"text", "validation", "fact_trace", "record", "facts", "backend"} <= set(
                generated
            )
            assert generated["validation"]["ok"] is True
            assert generated["backend"]["used"] == "rules"

            # 6. POST /api/score
            conn.request(
                "POST",
                "/api/score",
                body=json.dumps({"author": "alice", "text": generated["text"]}).encode("utf-8"),
                headers=json_headers,
            )
            resp = conn.getresponse()
            scored = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 200
            _assert_security_headers(resp)
            assert "report" in scored
            assert isinstance(scored["report"]["overall"], float)

            # 7. POST /api/token -> 501 error JSON
            conn.request(
                "POST",
                "/api/token",
                body=b"{}",
                headers=json_headers,
            )
            resp = conn.getresponse()
            token_err = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 501
            _assert_security_headers(resp)
            assert token_err["code"] == "not-implemented"
            assert "error" in token_err
        finally:
            conn.close()
    finally:
        server.shutdown()
        server.server_close()
