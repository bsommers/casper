"""TC-043 & TC-044: Torture tests for corrupt documents, zip bombs, and URL fetch faults."""

from __future__ import annotations

import io
import shutil
import socket
import zipfile
from typing import Any

import pytest

from casper.errors import InputError, SecurityError
from casper.loaders import load_bytes, load_document


def test_tc043_corrupt_files_and_zip_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    # Corrupt / truncated PDF
    with pytest.raises(InputError):
        load_bytes(b"%PDF-1.7\ntruncated garbage", "broken.pdf")

    # Corrupt DOCX zip
    with pytest.raises(InputError):
        load_bytes(b"PK\x03\x04not a real zip archive", "broken.docx")

    # Zip-bomb DOCX (>50 MiB uncompressed)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"0" * (53 * 1024 * 1024))
    with pytest.raises(SecurityError):
        load_bytes(buf.getvalue(), "bomb.docx")

    # Malformed YAML
    with pytest.raises(InputError):
        load_bytes(b"key: [unclosed\n", "bad.yaml")

    # Malformed CSV (more columns than headers)
    with pytest.raises(InputError):
        load_bytes(b"a,b\n1,2,3,4\n", "bad.csv")

    # Missing .doc system converter
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
    with pytest.raises(InputError):
        load_bytes(ole, "legacy.doc")


def test_tc044_url_timeout_oversized_and_redirect_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    # 1. Timeout
    def timeout_opener(_url: str, _timeout: float) -> Any:
        raise TimeoutError("timed out")

    with pytest.raises(InputError):
        load_document("https://public.example/slow", url_opener=timeout_opener)

    # 2. Oversized stream (> max_bytes)
    class _HugeResp:
        status = 200
        headers = {"Content-Type": "text/plain"}

        def read(self, n: int = 65536) -> bytes:
            return b"x" * (n if n > 0 else 65536)

        def close(self) -> None:
            pass

    with pytest.raises(InputError):
        load_document(
            "https://public.example/huge",
            max_bytes=1024,
            url_opener=lambda _u, _t: _HugeResp(),
        )

    # 3. Redirect loop (> max_redirects)
    class _LoopResp:
        status = 302
        headers = {"Location": "https://public.example/loop"}

        def read(self, _n: int = -1) -> bytes:
            return b""

        def close(self) -> None:
            pass

    with pytest.raises(SecurityError):
        load_document(
            "https://public.example/loop",
            max_redirects=3,
            url_opener=lambda _u, _t: _LoopResp(),
        )
