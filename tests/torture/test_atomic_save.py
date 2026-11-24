"""Torture tests for atomic profile persistence under mid-write I/O faults (TC-045)."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

import pytest

from casper.profile import compute_body_sha256, load_profile, save_profile


def _minimal_profile(display_name: str) -> dict[str, Any]:
    prof: dict[str, Any] = {
        "schema_version": 1,
        "author": {"id": "bill", "display_name": display_name, "aliases": []},
        "generated": {
            "tool": "casper",
            "tool_version": "0.1.0",
            "date": "2026-11-20T00:00:00Z",
            "spacy_model": "en_core_web_sm",
            "corpus_sha256": "0" * 64,
            "body_sha256": "",
        },
        "corpus": {"document_count": 1, "total_words": 150, "avg_doc_words": 150.0},
    }
    prof["generated"]["body_sha256"] = compute_body_sha256(prof)
    return prof


def test_tc045_mid_write_fsync_oserror_preserves_original_and_cleans_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-045: OSError during fsync leaves existing profile byte-identical and cleans temp file."""
    target = tmp_path / "bill.yaml"
    original_profile = _minimal_profile("Original Bill")
    save_profile(target, original_profile)
    original_bytes = target.read_bytes()

    def _boom_fsync(fd: int) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "fsync", _boom_fsync)

    updated_profile = _minimal_profile("Updated Bill")
    with pytest.raises(OSError, match="No space left on device"):
        save_profile(target, updated_profile)

    assert target.read_bytes() == original_bytes
    assert load_profile(target)["author"]["display_name"] == "Original Bill"
    assert [p for p in tmp_path.iterdir() if ".tmp." in p.name] == []


def test_tc045_mid_write_replace_oserror_preserves_original_and_cleans_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-045: OSError during os.replace leaves existing profile intact and cleans temp file."""
    target = tmp_path / "bill.yaml"
    original_profile = _minimal_profile("Original Bill")
    save_profile(target, original_profile)
    original_bytes = target.read_bytes()

    def _boom_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(os, "replace", _boom_replace)

    with pytest.raises(PermissionError, match="Permission denied"):
        save_profile(target, _minimal_profile("Updated Bill"))

    assert target.read_bytes() == original_bytes
    assert [p for p in tmp_path.iterdir() if ".tmp." in p.name] == []


def test_tc045_failed_initial_write_leaves_no_partial_or_tmp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-045: OSError on fresh profile write leaves neither target nor temp file behind."""
    target = tmp_path / "fresh.yaml"

    def _boom_fsync(fd: int) -> None:
        raise OSError(errno.EIO, "Simulated I/O error")

    monkeypatch.setattr(os, "fsync", _boom_fsync)

    with pytest.raises(OSError, match="Simulated I/O error"):
        save_profile(target, _minimal_profile("Fresh Bill"))

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
