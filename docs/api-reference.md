# API Reference

Casper routes its Python public API, CLI, and localhost HTTP server uniformly through the 10 typed functions in [`src/casper/commands.py`](../src/casper/commands.py).

## Python Public API (`casper.*`)

[`src/casper/__init__.py`](../src/casper/__init__.py) lazily exports all 10 commands, the `generate` alias, core model types, and the typed error hierarchy:

- **Commands:** `write_draft`, `generate` (alias for `write_draft`), `extract_facts`, `score_draft`, `list_options`, `backend_status`, `author_build`, `author_inspect`, `author_show`, `author_list`, `author_diff`
- **Models:** `AuthorDiff`, `AuthorSummary`, `BackendKind`, `BackendStatusReport`, `Brief`, `ConformanceReport`, `Fact`, `FactKind`, `FactModel`, `FidelityMode`, `Result`, `Validation`
- **Errors:** `CasperError`, `InputError`, `LibraryError`, `ProfileError`, `ProfileNotFoundError`, `ProfileTamperedError`, `BackendError`, `SecurityError`, `PayloadTooLargeError`, `BusyError`

```python
import casper

brief = casper.Brief(
    structure="status_update",
    modality="slack",
    source="developer",
    target="management",
    inputs=("examples/edge-migration-status.md",),
    seed=1,
)
result = casper.write_draft(brief)
print(result.text)
```

### Error Hierarchy (`CasperError`)

Defined in [`src/casper/errors.py`](../src/casper/errors.py). Every error serializes via `.to_dict()` to `{"error": ..., "code": ...}` (plus optional `"details"`).

| Exception | `code` | CLI Exit | HTTP Status | Purpose |
|---|---|---|---|---|
| `CasperError` | `casper-error` | `2` | `400` | Base operational error |
| `InputError` | `input-error` | `2` | `400` | Invalid inputs, flags, YAML, or unscorable text |
| `LibraryError` | `library-error` | `2` | `400` | Unknown persona/structure/modality or incompatible combo |
| `ProfileError` | `profile-error` | `2` | `400` | Corrupt profile YAML or invalid layer directive |
| `ProfileNotFoundError` | `profile-not-found` | `2` | `404` | Author ID does not exist in `authors_dir` |
| `ProfileTamperedError` | `profile-tampered` | `3` | `409` | `body_sha256` mismatch without `--force` |
| `BackendError` | `backend-error` | `2` | `502` | External CLI unavailable, auth failure, timeout, or empty output |
| `SecurityError` | `security-error` | `2` | `403` | Non-loopback bind, bad headers, traversal, SSRF, or zip bomb |
| `PayloadTooLargeError` | `payload-too-large` | `2` | `413` | HTTP body `> 262,144` bytes, notes `> 40,000` chars, or text `> 60,000` chars |
| `BusyError` | `server-busy` | `2` | `503` | Single-flight lock acquisition timeout |

## Surface Parity Matrix

| Operation | Python API (`casper.*`) | CLI (`casper ...`) | Web HTTP API (`casper serve`) |
|---|---|---|---|
| Generate draft | `write_draft(brief)` / `generate(brief)` | `casper write ...` | `POST /api/generate` |
| Extract facts | `extract_facts(inputs, notes, ...)` | `casper write --dry-run` | `POST /api/extract` |
| Score voice | `score_draft(author_ref, text_or_path, ...)` | `casper author score <author> <file>` | `POST /api/score` |
| List options | `list_options(project_dir, authors_dir)` | `casper write --list-options` | `GET /api/options` |
| Backend status | `backend_status(timeout, runner)` | `casper write --backend-status` | `GET /api/backend-status` |
| Build author | `author_build(...)` | `casper author build ...` | CLI / Python only |
| Inspect author | `author_inspect(author_ref, ...)` | `casper author inspect <author>` | CLI / Python only |
| Show author | `author_show(author_ref, ...)` | `casper author show <author>` | CLI / Python only |
| List authors | `author_list(authors_dir)` | `casper author list` | Included in `GET /api/options` |
| Diff authors | `author_diff(author_a, author_b, ...)` | `casper author diff <a> <b>` | CLI / Python only |

## Localhost Web HTTP API

Implemented in [`src/casper/web/server.py`](../src/casper/web/server.py) using Python's stdlib `ThreadingHTTPServer`.

### Endpoints

- `GET /` — Serves static UI entrypoint (`index.html`).
- `GET /static/<rel>` — Serves static assets under `src/casper/web/static/` with path-traversal and iterative percent-decoding guards (`404` on invalid paths).
- `GET /api/options` — Returns `{personas, structures, modalities, authors, backends}`.
- `GET /api/backend-status` — Returns `{backends: {rules, claude, agy}}` availability report.
- `POST /api/extract` — Accepts `{"notes": str, "fact_overrides": {...}}`; returns `{"facts": [...], "warnings": [...]}`.
- `POST /api/generate` — Accepts `structure`, `modality`, `source`, `target`, `notes`, and optional `author`, `topic`, `seed`, `candidates`, `min_voice`, `banned`, `fact_overrides`, `backend`, `fallback`, `timeout`, `model`; returns `{"text", "validation", "fact_trace", "record", "facts", "backend"}`.
- `POST /api/score` — Accepts `{"author": str, "text": str, "raw": bool?, "overlay": str?}`; returns `{"report": ...}`.
- `POST /api/token` — Always returns HTTP `501` (`"not-implemented"`); Casper runs locally with no API tokens.

### Security Headers, Bounds, and Isolation

- **Loopback-only binding:** `make_server()` and `casper serve` reject any host other than `127.0.0.1` (`SecurityError`).
- **Request header validation:** Every request requires an exact `Host` match (`127.0.0.1:<port>` or `localhost:<port>` without whitespace or `@`), rejects non-loopback `Origin` headers, and requires `Sec-Fetch-Site` (when present) to be `same-origin` or `none` (`403` otherwise).
- **Method & media-type enforcement:** Unsupported methods and `OPTIONS` return `405` with `Allow`. `POST` endpoints require `Content-Type: application/json` (`415` otherwise) and valid `Content-Length` (rejects chunked `Transfer-Encoding` with `411`).
- **Payload bounds (pre-read & post-parse):**
  - Maximum HTTP request body: `262,144` bytes (256 KiB; checked against `Content-Length` before reading the socket, returning `413`).
  - Maximum `notes` length (`/api/extract`, `/api/generate`): `40,000` characters (`413`).
  - Maximum `text` length (`/api/score`): `60,000` characters (`413`).
  - Socket timeout: `15.0`s; single-flight execution lock timeout: `30.0`s (`503` `server-busy`).
- **Author path containment:** HTTP endpoints invoke `commands.write_draft(..., allow_author_path=False)` and `commands.score_draft(..., allow_author_path=False)`, restricting author references to valid slugs inside `authors_dir`.
- **Response security headers:** Every response sets `Content-Security-Policy: default-src 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `Cache-Control: no-store`.
