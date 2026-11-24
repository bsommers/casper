"""Cross-surface parity tests across Python API, CLI, and Web App.handle (TC-017)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from casper import cli, commands
from casper.models import Brief
from casper.web.server import App

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_NOTES = REPO_ROOT / "tests" / "fixtures" / "status_notes.md"
FAKE_AGENT = REPO_ROOT / "tests" / "fakes" / "fake_agent.py"


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


def _web_headers(port: int = 8731, *, json_body: bool = False) -> dict[str, str]:
    headers = {"Host": f"127.0.0.1:{port}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def test_tc017_surface_parity_all_shared_operations(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authors_dir = _build_synthetic_author(tmp_path)
    notes = STATUS_NOTES.read_text(encoding="utf-8")
    app = App(port=8731, authors_dir=authors_dir)

    # 1. write_draft parity
    brief = Brief(
        structure="status_update",
        modality="slack",
        source="developer",
        target="management",
        author="alice",
        notes=notes,
        seed=0,
        candidates=8,
        authors_dir=str(authors_dir),
        backend="rules",
    )
    py_result = commands.write_draft(brief)

    rc_write = cli.main(
        [
            "write",
            "--structure",
            "status_update",
            "--modality",
            "slack",
            "--source",
            "developer",
            "--target",
            "management",
            "--author",
            "alice",
            "--authors-dir",
            str(authors_dir),
            "--notes",
            notes,
            "--seed",
            "0",
            "--candidates",
            "8",
            "--backend",
            "rules",
            "--json",
        ]
    )
    assert rc_write == 0
    cli_write = json.loads(capsys.readouterr().out)

    web_write_resp = app.handle(
        "POST",
        "/api/generate",
        _web_headers(json_body=True),
        json.dumps(
            {
                "structure": "status_update",
                "modality": "slack",
                "source": "developer",
                "target": "management",
                "author": "alice",
                "notes": notes,
                "seed": 0,
                "candidates": 8,
                "backend": "rules",
            }
        ).encode("utf-8"),
    )
    assert web_write_resp.status == 200
    web_write = json.loads(web_write_resp.body.decode("utf-8"))

    py_facts = [f.to_dict() for f in py_result.facts]
    assert py_result.text == cli_write["text"] == web_write["text"]
    assert (
        py_result.record.record_sha256
        == cli_write["record"]["record_sha256"]
        == web_write["record"]["record_sha256"]
    )
    assert py_facts == cli_write["facts"] == web_write["facts"]
    assert (
        py_result.validation.ok
        is cli_write["validation"]["ok"]
        is web_write["validation"]["ok"]
    )

    # 2. extract_facts parity
    py_extract = commands.extract_facts(notes=notes)

    rc_extract = cli.main(["write", "--notes", notes, "--dry-run", "--json"])
    assert rc_extract == 0
    cli_extract = json.loads(capsys.readouterr().out)

    web_extract_resp = app.handle(
        "POST",
        "/api/extract",
        _web_headers(json_body=True),
        json.dumps({"notes": notes}).encode("utf-8"),
    )
    assert web_extract_resp.status == 200
    web_extract = json.loads(web_extract_resp.body.decode("utf-8"))

    py_fact_tuples = [(f.id, str(f.kind), f.text) for f in py_extract.facts]
    cli_fact_tuples = [(f["id"], f["kind"], f["text"]) for f in cli_extract["facts"]]
    web_fact_tuples = [(f["id"], f["kind"], f["text"]) for f in web_extract["facts"]]
    assert py_fact_tuples == cli_fact_tuples == web_fact_tuples

    # 3. score_draft parity
    draft_path = tmp_path / "draft.txt"
    draft_path.write_text(py_result.text, encoding="utf-8")

    py_score = commands.score_draft(
        "alice", py_result.text, authors_dir=authors_dir, is_text=True
    )

    rc_score = cli.main(
        [
            "author",
            "--authors-dir",
            str(authors_dir),
            "score",
            "alice",
            str(draft_path),
            "--json",
        ]
    )
    assert rc_score == 0
    cli_score = json.loads(capsys.readouterr().out)

    web_score_resp = app.handle(
        "POST",
        "/api/score",
        _web_headers(json_body=True),
        json.dumps({"author": "alice", "text": py_result.text}).encode("utf-8"),
    )
    assert web_score_resp.status == 200
    web_score = json.loads(web_score_resp.body.decode("utf-8"))["report"]

    assert py_score.overall == cli_score["overall"] == web_score["overall"]
    assert str(py_score.band) == cli_score["band"] == web_score["band"]
    assert str(py_score.confidence) == cli_score["confidence"] == web_score["confidence"]
    assert py_score.word_count == cli_score["word_count"] == web_score["word_count"]

    # 4. list_options parity
    py_opts = commands.list_options(authors_dir=authors_dir)

    rc_opts = cli.main(
        ["write", "--list-options", "--authors-dir", str(authors_dir), "--json"]
    )
    assert rc_opts == 0
    cli_opts = json.loads(capsys.readouterr().out)

    web_opts_resp = app.handle("GET", "/api/options", _web_headers())
    assert web_opts_resp.status == 200
    web_opts = json.loads(web_opts_resp.body.decode("utf-8"))

    for key in ("structures", "modalities", "personas", "authors", "backends"):
        assert py_opts[key] == cli_opts[key] == web_opts[key]

    # 5. backend_status parity
    mode = FAKE_AGENT.stat().st_mode
    if not (mode & stat.S_IXUSR):
        FAKE_AGENT.chmod(mode | stat.S_IXUSR)

    monkeypatch.setenv("CASPER_CLAUDE_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_AGY_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_FAKE_MODE", "good")
    monkeypatch.setenv("CASPER_FAKE_VERSION", "fake-agent 1.0.0")

    py_status = commands.backend_status().to_dict()["backends"]

    rc_status = cli.main(["write", "--backend-status", "--json"])
    assert rc_status == 0
    cli_status = json.loads(capsys.readouterr().out)["backends"]

    web_status_resp = app.handle("GET", "/api/backend-status", _web_headers())
    assert web_status_resp.status == 200
    web_status = json.loads(web_status_resp.body.decode("utf-8"))["backends"]

    assert py_status == cli_status == web_status
