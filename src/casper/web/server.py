"""Hardened localhost-only stdlib HTTP server and pure `App.handle` core (Rank 8, ADR 0011)."""

from __future__ import annotations

import base64
import binascii
import json
import threading
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from casper import commands
from casper.errors import (
    BusyError,
    CasperError,
    InputError,
    PayloadTooLargeError,
    SecurityError,
)
from casper.llm import CommandRunner
from casper.loaders import SUPPORTED_UPLOAD_EXTENSIONS, load_bytes
from casper.modalities import EXPORT_FORMATS, export_document
from casper.models import BlockKind, Brief, Document, FactKind

MAX_BODY_BYTES = 262_144
MAX_UPLOAD_BODY_BYTES = 2_097_152
MAX_UPLOAD_RAW_BYTES = 1_572_864
MAX_NOTES_CHARS = 40_000
MAX_SCORE_TEXT_CHARS = 60_000
LOCK_TIMEOUT_SECONDS = 30.0
SOCKET_TIMEOUT_SECONDS = 15.0

STATIC_ROOT = Path(__file__).resolve().parent / "static"

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": "default-src 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

_STATIC_MIME: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
}

_EXTRACT_ALLOWED_KEYS: frozenset[str] = frozenset({"notes", "fact_overrides"})
_GENERATE_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "structure",
        "modality",
        "source",
        "target",
        "notes",
        "author",
        "topic",
        "seed",
        "candidates",
        "min_voice",
        "banned",
        "fact_overrides",
        "backend",
        "fallback",
        "timeout",
        "model",
    }
)
_SCORE_ALLOWED_KEYS: frozenset[str] = frozenset({"author", "text", "raw", "overlay"})
_UPLOAD_ALLOWED_KEYS: frozenset[str] = frozenset({"filename", "content_base64"})
_EXPORT_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"format", "text", "title", "facts", "fact_trace", "validation", "record"}
)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def _build_response(
    status: int,
    body: bytes,
    content_type: str,
    *,
    extra_headers: Mapping[str, str] | None = None,
) -> HttpResponse:
    headers = dict(SECURITY_HEADERS)
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(body))
    if extra_headers:
        headers.update(extra_headers)
    return HttpResponse(status=status, headers=headers, body=body)


def _json_response(
    status: int,
    payload: Mapping[str, Any],
    *,
    extra_headers: Mapping[str, str] | None = None,
) -> HttpResponse:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return _build_response(
        status,
        body,
        "application/json; charset=utf-8",
        extra_headers=extra_headers,
    )


def _error_response(
    status: int,
    message: str,
    code: str,
    *,
    extra_headers: Mapping[str, str] | None = None,
) -> HttpResponse:
    return _json_response(
        status,
        {"error": message, "code": code},
        extra_headers=extra_headers,
    )


def _coerce_fact_overrides(raw: Any) -> dict[str, FactKind]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise InputError("'fact_overrides' must be a JSON object mapping fact_id -> kind")
    out: dict[str, FactKind] = {}
    for key, val in raw.items():
        if not isinstance(key, str) or not isinstance(val, str):
            raise InputError("'fact_overrides' keys and values must be strings")
        try:
            out[key] = FactKind(val.strip().lower())
        except ValueError as exc:
            valid = ", ".join(str(k) for k in FactKind)
            raise InputError(
                f"Unknown fact kind {val!r} for {key!r}; valid choices: {valid}"
            ) from exc
    return out


def _require_str(payload: Mapping[str, Any], key: str) -> str:
    if key not in payload:
        raise InputError(f"Missing required field: '{key}'")
    val = payload[key]
    if not isinstance(val, str):
        raise InputError(f"Field '{key}' must be a string")
    return val


def _optional_str(payload: Mapping[str, Any], key: str) -> str | None:
    if key not in payload or payload[key] is None:
        return None
    val = payload[key]
    if not isinstance(val, str):
        raise InputError(f"Field '{key}' must be a string or null")
    return val


def _optional_int(payload: Mapping[str, Any], key: str, default: int) -> int:
    if key not in payload or payload[key] is None:
        return default
    val = payload[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise InputError(f"Field '{key}' must be an integer")
    return val


def _optional_bool(payload: Mapping[str, Any], key: str, default: bool) -> bool:
    if key not in payload or payload[key] is None:
        return default
    val = payload[key]
    if not isinstance(val, bool):
        raise InputError(f"Field '{key}' must be a boolean")
    return val


def _optional_float(payload: Mapping[str, Any], key: str) -> float | None:
    if key not in payload or payload[key] is None:
        return None
    val = payload[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise InputError(f"Field '{key}' must be a number or null")
    return float(val)


def _check_allowed_keys(payload: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(payload.keys()) - allowed)
    if unknown:
        raise InputError(f"Unknown request field(s): {', '.join(unknown)}")


def _sanitize_upload_filename(raw_name: str) -> str:
    if (
        not raw_name
        or not raw_name.strip()
        or "\x00" in raw_name
        or "/" in raw_name
        or "\\" in raw_name
    ):
        raise InputError("Invalid upload filename")
    safe_name = Path(raw_name).name
    if (
        not safe_name
        or safe_name in {".", ".."}
        or "\x00" in safe_name
        or "/" in safe_name
        or "\\" in safe_name
    ):
        raise InputError("Invalid upload filename")
    return safe_name


def _document_to_editable_text(doc: Document) -> str:
    parts: list[str] = []
    for block in doc.blocks:
        text = block.text.strip()
        if not text:
            continue
        if block.kind == BlockKind.HEADING:
            parts.append(f"## {text}")
        elif block.kind == BlockKind.LIST_ITEM:
            parts.append(f"- {text}")
        else:
            parts.append(text)
    if parts:
        return "\n\n".join(parts)
    return (doc.title or "").strip()


class App:
    """Pure, frameworkless HTTP request router enforcing Casper's security boundary."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8731,
        authors_dir: Path = Path("authors"),
        project_dir: Path | None = None,
        static_root: Path | None = None,
        lock_timeout: float = LOCK_TIMEOUT_SECONDS,
        runner: CommandRunner | None = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.authors_dir = Path(authors_dir)
        self.project_dir = Path(project_dir) if project_dir is not None else None
        self.static_root = (static_root if static_root is not None else STATIC_ROOT).resolve()
        self.lock_timeout = float(lock_timeout)
        self._runner = runner
        self._lock = threading.Lock()

    def _allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def _allowed_origins(self) -> set[str]:
        return {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}

    def _check_security_headers(self, hdrs: Mapping[str, str]) -> HttpResponse | None:
        # 1. Host header required and exact loopback+port match (zero whitespace/userinfo).
        host_val = hdrs.get("host")
        if host_val is None or not host_val or any(ch.isspace() for ch in host_val) or "@" in host_val:
            return _error_response(403, "Invalid or missing Host header", "security-error")
        if host_val.lower() not in self._allowed_hosts():
            return _error_response(403, "Forbidden Host header", "security-error")

        # 2. Origin (if present) must exact-match loopback HTTP origin.
        if "origin" in hdrs:
            origin_val = hdrs["origin"]
            if origin_val.lower() not in self._allowed_origins():
                return _error_response(403, "Forbidden Origin header", "security-error")

        # 3. Sec-Fetch-Site (if present) must be same-origin or none.
        if "sec-fetch-site" in hdrs:
            sfs = hdrs["sec-fetch-site"].strip().lower()
            if sfs not in {"same-origin", "none"}:
                return _error_response(403, "Forbidden Sec-Fetch-Site header", "security-error")

        return None

    def _serve_static(self, relpath: str) -> HttpResponse:
        # Strip query/fragment if any remained, reject NUL/backslash/traversal before & after unquoting.
        clean = relpath.split("?", 1)[0].split("#", 1)[0]
        if "\x00" in clean or "\\" in clean or clean.startswith("/"):
            return _error_response(404, "Not found", "not-found")

        # Decode iteratively (handles double-encoded %252e%252e)
        decoded = clean
        for _ in range(3):
            nxt = urllib.parse.unquote(decoded)
            if nxt == decoded:
                break
            decoded = nxt

        if "\x00" in decoded or "\\" in decoded or decoded.startswith("/") or not decoded:
            return _error_response(404, "Not found", "not-found")

        segments = decoded.split("/")
        if any(seg in {"", ".", ".."} for seg in segments):
            return _error_response(404, "Not found", "not-found")

        candidate = (self.static_root / decoded).resolve()
        if not candidate.is_relative_to(self.static_root) or not candidate.is_file():
            return _error_response(404, "Not found", "not-found")

        mime = _STATIC_MIME.get(candidate.suffix.lower(), "application/octet-stream")
        return _build_response(200, candidate.read_bytes(), mime)

    def _parse_json_post(
        self,
        hdrs: Mapping[str, str],
        body: bytes,
        *,
        max_bytes: int = MAX_BODY_BYTES,
    ) -> dict[str, Any] | HttpResponse:
        ctype = hdrs.get("content-type", "")
        media_type = ctype.split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            return _error_response(
                415,
                "Content-Type must be application/json",
                "unsupported-media-type",
            )
        if len(body) > max_bytes:
            return _error_response(
                413,
                f"Request body exceeds {max_bytes} bytes",
                "payload-too-large",
            )
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _error_response(400, "Invalid JSON request body", "input-error")
        if not isinstance(parsed, dict):
            return _error_response(400, "Request body must be a JSON object", "input-error")
        return parsed

    def _run_serialized(self, fn: Any) -> HttpResponse:
        if not self._lock.acquire(timeout=self.lock_timeout):
            busy = BusyError("Server busy; try again shortly")
            return _error_response(busy.http_status, busy.message, busy.code)
        try:
            return fn()
        finally:
            self._lock.release()

    def _handle_extract(self, payload: dict[str, Any]) -> HttpResponse:
        _check_allowed_keys(payload, _EXTRACT_ALLOWED_KEYS)
        notes = _require_str(payload, "notes")
        if len(notes) > MAX_NOTES_CHARS:
            raise PayloadTooLargeError(f"Notes exceed maximum length of {MAX_NOTES_CHARS} characters")
        overrides = _coerce_fact_overrides(payload.get("fact_overrides"))
        fm = commands.extract_facts(notes=notes, fact_overrides=overrides or None)
        return _json_response(
            200,
            {
                "facts": [f.to_dict() for f in fm.facts],
                "warnings": list(fm.warnings),
            },
        )

    def _handle_generate(self, payload: dict[str, Any]) -> HttpResponse:
        _check_allowed_keys(payload, _GENERATE_ALLOWED_KEYS)
        structure = _require_str(payload, "structure")
        modality = _require_str(payload, "modality")
        source = _require_str(payload, "source")
        target = _require_str(payload, "target")
        notes = _require_str(payload, "notes")
        if len(notes) > MAX_NOTES_CHARS:
            raise PayloadTooLargeError(f"Notes exceed maximum length of {MAX_NOTES_CHARS} characters")

        author = _optional_str(payload, "author")
        if author is not None and not author.strip():
            author = None
        topic = _optional_str(payload, "topic")
        seed = _optional_int(payload, "seed", 0)
        candidates = _optional_int(payload, "candidates", 8)
        min_voice = _optional_float(payload, "min_voice")
        raw_banned = payload.get("banned")
        banned_list: list[str] = []
        if raw_banned is not None:
            if not isinstance(raw_banned, list) or not all(isinstance(x, str) for x in raw_banned):
                raise InputError("Field 'banned' must be a list of strings")
            banned_list = list(raw_banned)
        overrides = _coerce_fact_overrides(payload.get("fact_overrides"))
        backend = _optional_str(payload, "backend") or "rules"
        fallback = _optional_bool(payload, "fallback", True)
        timeout = _optional_int(payload, "timeout", 120)
        model = _optional_str(payload, "model")

        brief = Brief(
            structure=structure,
            modality=modality,
            source=source,
            target=target,
            author=author,
            inputs=(),
            notes=notes,
            topic=topic,
            seed=seed,
            candidates=candidates,
            min_voice=min_voice,
            banned=tuple(banned_list),
            fact_overrides=overrides,
            project_dir=str(self.project_dir) if self.project_dir is not None else None,
            authors_dir=str(self.authors_dir),
            backend=backend,
            fallback=fallback,
            timeout=timeout,
            model=model,
        )
        result = commands.write_draft(brief, allow_author_path=False, runner=self._runner)
        return _json_response(
            200,
            {
                "text": result.text,
                "validation": result.validation.to_dict(),
                "fact_trace": [e.to_dict() for e in result.fact_trace],
                "record": result.record.to_dict(),
                "facts": [f.to_dict() for f in result.facts],
                "backend": result.record.backend.to_dict(),
            },
        )

    def _handle_score(self, payload: dict[str, Any]) -> HttpResponse:
        _check_allowed_keys(payload, _SCORE_ALLOWED_KEYS)
        author = _require_str(payload, "author")
        text = _require_str(payload, "text")
        if len(text) > MAX_SCORE_TEXT_CHARS:
            raise PayloadTooLargeError(
                f"Text exceeds maximum length of {MAX_SCORE_TEXT_CHARS} characters"
            )
        raw = _optional_bool(payload, "raw", False)
        overlay = _optional_str(payload, "overlay")
        if overlay is not None and not overlay.strip():
            overlay = None

        report = commands.score_draft(
            author,
            text,
            authors_dir=self.authors_dir,
            is_text=True,
            raw=raw,
            overlay=overlay,
            allow_author_path=False,
        )
        return _json_response(200, {"report": report.to_dict()})

    def _handle_upload(self, payload: dict[str, Any]) -> HttpResponse:
        _check_allowed_keys(payload, _UPLOAD_ALLOWED_KEYS)
        safe_name = _sanitize_upload_filename(_require_str(payload, "filename"))
        raw_b64 = _require_str(payload, "content_base64")
        try:
            raw_bytes = base64.b64decode(raw_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InputError("Invalid base64 payload in 'content_base64'") from exc

        if len(raw_bytes) > MAX_UPLOAD_RAW_BYTES:
            raise PayloadTooLargeError(
                f"Decoded upload exceeds maximum size of {MAX_UPLOAD_RAW_BYTES} bytes"
            )

        doc = load_bytes(raw_bytes, safe_name, max_bytes=MAX_UPLOAD_RAW_BYTES)
        extracted_text = _document_to_editable_text(doc)
        if not extracted_text:
            raise InputError("Uploaded file contained no readable text")
        if len(extracted_text) > MAX_SCORE_TEXT_CHARS:
            raise PayloadTooLargeError(
                f"Extracted text exceeds maximum length of {MAX_SCORE_TEXT_CHARS} characters"
            )

        return _json_response(
            200,
            {
                "filename": safe_name,
                "format": doc.format,
                "title": doc.title,
                "text": extracted_text,
                "word_count": len(extracted_text.split()),
                "notes": list(doc.notes),
            },
        )

    def _handle_export(self, payload: dict[str, Any]) -> HttpResponse:
        _check_allowed_keys(payload, _EXPORT_ALLOWED_KEYS)
        fmt = _require_str(payload, "format")
        text = _require_str(payload, "text")
        if len(text) > MAX_SCORE_TEXT_CHARS:
            raise PayloadTooLargeError(
                f"Text exceeds maximum length of {MAX_SCORE_TEXT_CHARS} characters"
            )
        title = _optional_str(payload, "title")
        metadata: dict[str, Any] = {}
        for meta_key in ("facts", "fact_trace", "validation", "record"):
            if meta_key in payload and payload[meta_key] is not None:
                metadata[meta_key] = payload[meta_key]

        payload_bytes, mime_type, filename = export_document(
            text,
            fmt,
            title=title,
            metadata=metadata or None,
        )
        safe_disp_name = filename.replace("\r", "").replace("\n", "").replace('"', "")
        return _build_response(
            200,
            payload_bytes,
            mime_type,
            extra_headers={"Content-Disposition": f'attachment; filename="{safe_disp_name}"'},
        )

    def handle(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes = b"",
    ) -> HttpResponse:
        """Route and validate an HTTP request purely in-memory."""
        hdrs = {k.lower(): v for k, v in headers.items()}

        # Gates 1-3: Host, Origin, Sec-Fetch-Site.
        sec_err = self._check_security_headers(hdrs)
        if sec_err is not None:
            return sec_err

        method_u = method.upper()
        clean_path = path.split("?", 1)[0]

        # Gate 4: Method check (OPTIONS and unsupported methods -> 405 with Allow).
        if method_u == "OPTIONS" or method_u not in {"GET", "POST"}:
            return _error_response(
                405,
                f"Method {method_u} not allowed",
                "method-not-allowed",
                extra_headers={"Allow": "GET, POST"},
            )

        is_get_route = (
            clean_path in {"/", "/api/options", "/api/backend-status", "/api/formats"}
            or clean_path.startswith("/static/")
        )
        is_post_route = clean_path in {
            "/api/extract",
            "/api/generate",
            "/api/score",
            "/api/token",
            "/api/upload",
            "/api/export",
        }

        if is_get_route and method_u != "GET":
            return _error_response(
                405,
                f"Method {method_u} not allowed for {clean_path}",
                "method-not-allowed",
                extra_headers={"Allow": "GET"},
            )
        if is_post_route and method_u != "POST":
            return _error_response(
                405,
                f"Method {method_u} not allowed for {clean_path}",
                "method-not-allowed",
                extra_headers={"Allow": "POST"},
            )
        if not is_get_route and not is_post_route:
            return _error_response(404, "Not found", "not-found")

        try:
            if method_u == "GET":
                if clean_path == "/":
                    return self._serve_static("index.html")
                if clean_path.startswith("/static/"):
                    return self._serve_static(clean_path[len("/static/") :])
                if clean_path == "/api/options":
                    opts = commands.list_options(
                        project_dir=self.project_dir,
                        authors_dir=self.authors_dir,
                    )
                    return _json_response(200, opts)
                if clean_path == "/api/backend-status":
                    rep = commands.backend_status(runner=self._runner)
                    return _json_response(200, rep.to_dict())
                if clean_path == "/api/formats":
                    return _json_response(
                        200,
                        {
                            "upload_extensions": list(SUPPORTED_UPLOAD_EXTENSIONS),
                            "export_formats": [
                                {
                                    "id": fmt_id,
                                    "label": label,
                                    "extension": ext,
                                    "mime": mime,
                                }
                                for fmt_id, (label, ext, mime) in EXPORT_FORMATS.items()
                            ],
                        },
                    )

            # Gate 5: POST JSON checks.
            max_post_bytes = (
                MAX_UPLOAD_BODY_BYTES if clean_path == "/api/upload" else MAX_BODY_BYTES
            )
            parsed_or_err = self._parse_json_post(hdrs, body, max_bytes=max_post_bytes)
            if isinstance(parsed_or_err, HttpResponse):
                return parsed_or_err
            payload = parsed_or_err

            if clean_path == "/api/token":
                return _error_response(
                    501,
                    "API tokens are not supported; Casper runs locally.",
                    "not-implemented",
                )
            if clean_path == "/api/extract":
                return self._run_serialized(lambda: self._handle_extract(payload))
            if clean_path == "/api/generate":
                return self._run_serialized(lambda: self._handle_generate(payload))
            if clean_path == "/api/score":
                return self._run_serialized(lambda: self._handle_score(payload))
            if clean_path == "/api/upload":
                return self._run_serialized(lambda: self._handle_upload(payload))
            if clean_path == "/api/export":
                return self._handle_export(payload)

            return _error_response(404, "Not found", "not-found")
        except CasperError as exc:
            return _error_response(exc.http_status, exc.message, exc.code)
        except Exception:
            return _error_response(500, "Internal server error", "internal-error")


class CasperHTTPServer(ThreadingHTTPServer):
    """Localhost-only threaded HTTP server carrying a Casper App instance."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        app: App,
    ) -> None:
        self.app = app
        super().__init__(server_address, handler_cls)
        self.app.port = self.server_port


class CasperRequestHandler(BaseHTTPRequestHandler):
    """HTTP/1.1 handler enforcing pre-read Transfer-Encoding & Content-Length bounds."""

    server: CasperHTTPServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(SOCKET_TIMEOUT_SECONDS)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Suppress noisy default stderr logging during CLI/test execution.
        return

    def _write_http_response(self, resp: HttpResponse) -> None:
        self.send_response(resp.status)
        for key, value in resp.headers.items():
            self.send_header(key, value)
        self.end_headers()
        if resp.body:
            self.wfile.write(resp.body)

    def _dispatch(self, method: str) -> None:
        raw_headers = {k: v for k, v in self.headers.items()}
        body = b""

        if method in {"POST", "PUT", "PATCH"}:
            te = self.headers.get("Transfer-Encoding", "")
            if "chunked" in te.lower():
                self._write_http_response(
                    _error_response(
                        411,
                        "Chunked Transfer-Encoding is not supported",
                        "length-required",
                    )
                )
                return

            cl_header = self.headers.get("Content-Length")
            if cl_header is None:
                self._write_http_response(
                    _error_response(411, "Content-Length header required", "length-required")
                )
                return
            try:
                content_length = int(cl_header.strip())
                if content_length < 0:
                    raise ValueError("negative")
            except ValueError:
                self._write_http_response(
                    _error_response(400, "Invalid Content-Length header", "input-error")
                )
                return

            # Pre-read body cap enforcement (TC-046): reject BEFORE reading rfile!
            clean_path = self.path.split("?", 1)[0]
            max_body = MAX_UPLOAD_BODY_BYTES if clean_path == "/api/upload" else MAX_BODY_BYTES
            if content_length > max_body:
                self._write_http_response(
                    _error_response(
                        413,
                        f"Request body exceeds {max_body} bytes",
                        "payload-too-large",
                    )
                )
                return

            if content_length > 0:
                body = self.rfile.read(content_length)

        resp = self.server.app.handle(method, self.path, raw_headers, body)
        self._write_http_response(resp)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_OPTIONS(self) -> None:
        self._dispatch("OPTIONS")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_HEAD(self) -> None:
        self._dispatch("HEAD")


def make_server(
    host: str = "127.0.0.1",
    port: int = 8731,
    *,
    authors_dir: Path = Path("authors"),
    project_dir: Path | None = None,
    app: App | None = None,
) -> CasperHTTPServer:
    """Create a localhost-only ThreadingHTTPServer bound strictly to `127.0.0.1` (GC-06)."""
    if host != "127.0.0.1":
        raise SecurityError(
            f"Casper web server binds exclusively to 127.0.0.1; refusing host {host!r}"
        )
    active_app = (
        app
        if app is not None
        else App(
            host=host,
            port=port,
            authors_dir=authors_dir,
            project_dir=project_dir,
        )
    )
    return CasperHTTPServer((host, port), CasperRequestHandler, active_app)
