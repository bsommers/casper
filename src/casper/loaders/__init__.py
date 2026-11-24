"""Uniform content-first document loader with SSRF-protected URL fetching (Rank 2)."""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from casper.errors import InputError, SecurityError
from casper.loaders.docx import check_zip_bomb, parse_docx
from casper.loaders.html import parse_html
from casper.loaders.latex import parse_latex
from casper.loaders.markdown import parse_markdown
from casper.loaders.markup import parse_asciidoc, parse_org, parse_rst
from casper.loaders.office import parse_doc, parse_odt
from casper.loaders.pdf import parse_pdf
from casper.loaders.rtf import parse_rtf
from casper.loaders.tabular import parse_csv, parse_yaml
from casper.models import Document

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"

SUPPORTED_UPLOAD_EXTENSIONS: tuple[str, ...] = (
    ".txt",
    ".md",
    ".markdown",
    ".adoc",
    ".asciidoc",
    ".pdf",
    ".docx",
    ".odt",
    ".rtf",
    ".tex",
    ".html",
    ".htm",
    ".csv",
    ".yaml",
    ".yml",
    ".rst",
    ".org",
)

_SUPPORTED_EXTENSIONS = frozenset(
    {
        ".html",
        ".htm",
        ".md",
        ".markdown",
        ".adoc",
        ".asciidoc",
        ".rst",
        ".org",
        ".txt",
        ".text",
        ".tex",
        ".docx",
        ".pdf",
        ".rtf",
        ".doc",
        ".odt",
        ".csv",
        ".yaml",
        ".yml",
    }
)


def _is_forbidden_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_url_target(url: str) -> urllib.parse.ParseResult:
    """Validate URL scheme (http/https only) and resolved IPs against SSRF (GC-06)."""
    parsed = urllib.parse.urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise SecurityError(f"Unsupported or forbidden URL scheme: {scheme!r}")
    host = parsed.hostname
    if not host:
        raise SecurityError(f"URL missing hostname: {url!r}")

    # Direct IP literal check first
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if _is_forbidden_ip(host):
            raise SecurityError(f"Refusing to fetch private or non-public IP: {host}")
        return parsed

    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise InputError(f"DNS resolution failed for {host!r}: {exc}") from exc

    if not addr_infos:
        raise InputError(f"DNS returned no addresses for {host!r}")

    for _family, _socktype, _proto, _canonname, sockaddr in addr_infos:
        ip_str = str(sockaddr[0])
        if _is_forbidden_ip(ip_str):
            raise SecurityError(
                f"Refusing to fetch URL resolving to private/non-public IP: {host} -> {ip_str}"
            )
    return parsed


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


def _default_url_opener(url: str, timeout: float) -> Any:
    opener = urllib.request.build_opener(_NoRedirectHandler())
    req = urllib.request.Request(url, headers={"User-Agent": "casper/0.1.0"})
    try:
        return opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code in {301, 302, 303, 307, 308}:
            return exc
        raise InputError(f"HTTP error {exc.code} fetching {url}") from exc
    except TimeoutError as exc:
        raise InputError(f"Timed out fetching {url}") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise InputError(f"Timed out fetching {url}") from exc
        raise InputError(f"Failed fetching {url}: {exc.reason}") from exc


def _read_bounded_stream(resp: Any, max_bytes: int, url: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = resp.read(65_536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise InputError(f"Response from {url} exceeded {max_bytes} byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _fetch_url(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    max_redirects: int,
    url_opener: Callable[..., Any] | None,
) -> tuple[bytes, str | None, str]:
    opener = url_opener or _default_url_opener
    current_url = url

    for hops in range(max_redirects + 1):
        validate_url_target(current_url)
        try:
            resp = opener(current_url, timeout)
        except (InputError, SecurityError):
            raise
        except TimeoutError as exc:
            raise InputError(f"Timed out fetching {current_url}") from exc
        except Exception as exc:
            raise InputError(f"Failed fetching {current_url}: {exc}") from exc

        status = getattr(resp, "status", getattr(resp, "code", 200))
        headers = getattr(resp, "headers", {}) or {}
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("Location") or headers.get("location")
            close_fn = getattr(resp, "close", None)
            if callable(close_fn):
                close_fn()
            if not location:
                raise InputError(f"Redirect ({status}) missing Location header at {current_url}")
            if hops >= max_redirects:
                raise SecurityError(f"Exceeded max redirects ({max_redirects}) for {url}")
            current_url = urllib.parse.urljoin(current_url, str(location))
            continue

        try:
            data = _read_bounded_stream(resp, max_bytes, current_url)
            content_type = headers.get("Content-Type") or headers.get("content-type")
            return data, (str(content_type) if content_type else None), current_url
        finally:
            close_fn = getattr(resp, "close", None)
            if callable(close_fn):
                close_fn()

    raise SecurityError(f"Exceeded max redirects ({max_redirects}) for {url}")


def _looks_like_url(value: str) -> bool:
    return "://" in value


def load_bytes(
    data: bytes,
    name: str,
    *,
    content_type: str | None = None,
    max_bytes: int = 10_485_760,
) -> Document:
    """Parse raw bytes into a Document using content-first magic detection."""
    if len(data) > max_bytes:
        raise InputError(f"Input {name} exceeds {max_bytes} byte limit")

    # 1. Magic-byte dispatch
    if data.startswith(b"%PDF-"):
        return parse_pdf(data, name)
    if data.startswith(b"{\\rtf"):
        return parse_rtf(data, name)
    if data.startswith(_OLE_MAGIC):
        return parse_doc(data, name)
    if data.startswith(_ZIP_MAGIC):
        zf = check_zip_bomb(data, max_bytes=max_bytes)
        try:
            names = set(zf.namelist())
            mimetype_bytes = zf.read("mimetype") if "mimetype" in names else b""
        except zipfile.BadZipFile as exc:
            raise InputError(f"Corrupt ZIP archive {name}: {exc}") from exc
        finally:
            zf.close()
        if "word/document.xml" in names:
            return parse_docx(data, name, max_bytes=max_bytes)
        if "content.xml" in names and b"opendocument.text" in mimetype_bytes:
            return parse_odt(data, name, max_bytes=max_bytes)
        raise InputError(f"Unsupported ZIP archive format: {name}")

    # 2. Content-Type header dispatch
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct in {"text/html", "application/xhtml+xml"}:
        return parse_html(data, name)
    if ct == "application/pdf":
        return parse_pdf(data, name)
    if ct in {"application/rtf", "text/rtf"}:
        return parse_rtf(data, name)
    if ct == "text/csv":
        return parse_csv(data, name)
    if ct in {"application/x-yaml", "text/yaml", "application/yaml"}:
        return parse_yaml(data, name)
    if ct == "text/asciidoc":
        return parse_asciidoc(data, name)
    if ct in {"text/x-rst", "text/prs.fallenstein.rst"}:
        return parse_rst(data, name)
    if ct == "text/org":
        return parse_org(data, name)

    # 3. Extension dispatch
    ext = Path(urllib.parse.urlparse(name).path if _looks_like_url(name) else name).suffix.lower()
    if ext in {".html", ".htm"}:
        return parse_html(data, name)
    if ext == ".tex":
        return parse_latex(data, name)
    if ext == ".docx":
        return parse_docx(data, name, max_bytes=max_bytes)
    if ext == ".odt":
        return parse_odt(data, name, max_bytes=max_bytes)
    if ext == ".doc":
        return parse_doc(data, name)
    if ext == ".pdf":
        return parse_pdf(data, name)
    if ext == ".rtf":
        return parse_rtf(data, name)
    if ext == ".csv":
        return parse_csv(data, name)
    if ext in {".yaml", ".yml"}:
        return parse_yaml(data, name)
    if ext in {".adoc", ".asciidoc"}:
        return parse_asciidoc(data, name)
    if ext == ".rst":
        return parse_rst(data, name)
    if ext == ".org":
        return parse_org(data, name)
    if ext in {".md", ".markdown"}:
        return parse_markdown(data, name, fmt="markdown")
    if ext in {".txt", ".text"}:
        return parse_markdown(data, name, fmt="text")

    # 4. Heuristic HTML sniff vs plain markdown/text
    head = data[:512].lstrip().lower()
    if head.startswith((b"<!doctype html", b"<html")):
        return parse_html(data, name)

    return parse_markdown(data, name, fmt="markdown" if name == "<inline>" else "text")


def load_document(
    path_or_url: str | Path,
    *,
    max_bytes: int = 10_485_760,
    timeout: float = 30.0,
    max_redirects: int = 5,
    url_opener: Callable[..., Any] | None = None,
) -> Document:
    """Load a local file or SSRF-checked HTTP(S) URL into a Document."""
    raw_ref = str(path_or_url)
    if _looks_like_url(raw_ref):
        data, content_type, final_url = _fetch_url(
            raw_ref,
            max_bytes=max_bytes,
            timeout=timeout,
            max_redirects=max_redirects,
            url_opener=url_opener,
        )
        return load_bytes(data, final_url, content_type=content_type, max_bytes=max_bytes)

    path = Path(path_or_url)
    if not path.is_file():
        raise InputError(f"Input file not found: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise InputError(f"Input file {path} exceeds {max_bytes} byte limit")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InputError(f"Could not read file {path}: {exc}") from exc
    return load_bytes(data, str(path), max_bytes=max_bytes)


def collect_input_paths(inputs: Sequence[str | Path]) -> list[str]:
    """Expand directories in deterministic sorted order, skipping *_files and hidden dot-dirs."""
    out: list[str] = []
    for item in inputs:
        raw = str(item)
        if _looks_like_url(raw):
            out.append(raw)
            continue
        path = Path(item)
        if not path.exists():
            raise InputError(f"Input path does not exist: {path}")
        if path.is_file():
            out.append(str(path))
            continue
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                rel_parts = child.relative_to(path).parts
                if any(p.startswith(".") or p.endswith("_files") for p in rel_parts):
                    continue
                if child.is_file() and child.suffix.lower() in _SUPPORTED_EXTENSIONS:
                    out.append(str(child))
    return out
