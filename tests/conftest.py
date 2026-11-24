"""Shared pytest fixtures and offline network guard (GC-07)."""

from __future__ import annotations

import socket
from typing import Any

import pytest

_ORIG_CONNECT = socket.socket.connect
_ORIG_CONNECT_EX = socket.socket.connect_ex
_ORIG_CREATE_CONNECTION = socket.create_connection

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_loopback_address(address: Any) -> bool:
    if isinstance(address, (str, bytes)):
        return True  # AF_UNIX path
    if isinstance(address, tuple) and len(address) >= 1:
        host = str(address[0]).lower()
        return host in _LOOPBACK_HOSTS
    return False


@pytest.fixture(autouse=True)
def _offline_socket_guard(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Block all outbound network connections in tests; allow loopback only when marked."""
    allow_loopback = request.node.get_closest_marker("loopback") is not None

    def _guarded_connect(self: socket.socket, address: Any) -> Any:
        if self.family == getattr(socket, "AF_UNIX", -1):
            return _ORIG_CONNECT(self, address)
        if allow_loopback and _is_loopback_address(address):
            return _ORIG_CONNECT(self, address)
        raise RuntimeError(f"Outbound network connection blocked in offline test suite: {address!r}")

    def _guarded_connect_ex(self: socket.socket, address: Any) -> int:
        if self.family == getattr(socket, "AF_UNIX", -1):
            return _ORIG_CONNECT_EX(self, address)
        if allow_loopback and _is_loopback_address(address):
            return _ORIG_CONNECT_EX(self, address)
        raise RuntimeError(f"Outbound network connection blocked in offline test suite: {address!r}")

    def _guarded_create_connection(address: tuple[str, int], *args: Any, **kwargs: Any) -> socket.socket:
        if allow_loopback and _is_loopback_address(address):
            return _ORIG_CREATE_CONNECTION(address, *args, **kwargs)
        raise RuntimeError(f"Outbound network connection blocked in offline test suite: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    monkeypatch.setattr(socket, "create_connection", _guarded_create_connection)
