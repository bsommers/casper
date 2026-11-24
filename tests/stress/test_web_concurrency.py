"""Web server concurrency and busy-lock 503 stress tests (TC-039)."""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from casper.web.server import App, make_server

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_NOTES = REPO_ROOT / "tests" / "fixtures" / "status_notes.md"


@pytest.mark.loopback
def test_tc039_eight_concurrent_generate_requests_byte_identical(tmp_path: Path) -> None:
    notes = STATUS_NOTES.read_text(encoding="utf-8")
    payload = json.dumps(
        {
            "structure": "status_update",
            "modality": "slack",
            "source": "developer",
            "target": "management",
            "notes": notes,
            "seed": 0,
        }
    ).encode("utf-8")

    server = make_server("127.0.0.1", 0, authors_dir=tmp_path / "authors")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port

    n_workers = 8
    barrier = threading.Barrier(n_workers)
    results: list[tuple[int, dict[str, object]]] = [(-1, {})] * n_workers
    errors: list[BaseException] = []

    def _worker(idx: int) -> None:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            try:
                barrier.wait(timeout=10)
                conn.request(
                    "POST",
                    "/api/generate",
                    body=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp = conn.getresponse()
                data = json.loads(resp.read().decode("utf-8"))
                results[idx] = (resp.status, data)
            finally:
                conn.close()
        except BaseException as exc:  # pragma: no cover - captured for assertion
            errors.append(exc)

    try:
        workers = [threading.Thread(target=_worker, args=(i,)) for i in range(n_workers)]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=30)

        assert not errors
        assert all(status == 200 for status, _ in results)
        texts = {data["text"] for _, data in results}
        shas = {data["record"]["record_sha256"] for _, data in results}  # type: ignore[index]
        assert len(texts) == 1
        assert len(shas) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_tc039_busy_lock_returns_503_and_recovers(tmp_path: Path) -> None:
    app = App(port=8731, authors_dir=tmp_path / "authors", lock_timeout=0.05)
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

    assert app._lock.acquire(blocking=False)
    try:
        busy_resp = app.handle("POST", "/api/generate", headers, body)
        assert busy_resp.status == 503
        busy_json = json.loads(busy_resp.body.decode("utf-8"))
        assert busy_json["code"] == "server-busy"
    finally:
        app._lock.release()

    ok_resp = app.handle("POST", "/api/generate", headers, body)
    assert ok_resp.status == 200
