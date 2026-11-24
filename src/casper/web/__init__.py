"""Localhost-only Casper web server and frameworkless static UI (Rank 8, ADR 0011)."""

from __future__ import annotations

from casper.web.server import App, HttpResponse, make_server

__all__ = ["App", "HttpResponse", "make_server"]
