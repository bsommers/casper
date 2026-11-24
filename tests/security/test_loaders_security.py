"""TC-034: SSRF & URL scheme guard tests for loaders."""

from __future__ import annotations

import socket
from typing import Any

import pytest

from casper.errors import SecurityError
from casper.loaders import load_document


class _FakeResp:
    def __init__(self, status: int, headers: dict[str, str], body: bytes = b"") -> None:
        self.status = status
        self.headers = headers
        self._body = body
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            chunk = self._body[self._pos :]
            self._pos = len(self._body)
            return chunk
        chunk = self._body[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        pass


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///etc/passwd",
        "ftp://example.com/resource",
        "gopher://example.com/1",
        "http://127.0.0.1:8731/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/internal",
        "http://[::1]:8080/",
    ],
)
def test_ssrf_and_scheme_rejected_before_connect(bad_url: str) -> None:
    called = False

    def opener(_url: str, _timeout: float) -> Any:
        nonlocal called
        called = True
        return _FakeResp(200, {}, b"should never run")

    with pytest.raises(SecurityError):
        load_document(bad_url, url_opener=opener)
    assert not called


def test_ssrf_redirect_to_loopback_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        if host == "public.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    visited: list[str] = []

    def opener(url: str, _timeout: float) -> Any:
        visited.append(url)
        return _FakeResp(302, {"Location": "http://127.0.0.1:8731/secret"})

    with pytest.raises(SecurityError):
        load_document("https://public.example/start", url_opener=opener)
    assert visited == ["https://public.example/start"]
