"""Typed error hierarchy for Casper with CLI exit codes and HTTP status codes."""

from __future__ import annotations

from typing import Any


class CasperError(Exception):
    """Base error for all operational failures in Casper."""

    code: str = "casper-error"
    exit_code: int = 2
    http_status: int = 400

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details) if details else {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.message, "code": self.code}
        if self.details:
            payload["details"] = self.details
        return payload


class InputError(CasperError):
    """Missing notes, unreadable file, bad YAML/flag/backend, or unscorable text."""

    code = "input-error"
    exit_code = 2
    http_status = 400


class LibraryError(CasperError):
    """Invalid persona/structure/modality combo or library schema violation."""

    code = "library-error"
    exit_code = 2
    http_status = 400


class ProfileError(CasperError):
    """Corrupt profile YAML or invalid layer directive."""

    code = "profile-error"
    exit_code = 2
    http_status = 400


class ProfileNotFoundError(ProfileError):
    """Valid author ID does not exist in authors_dir."""

    code = "profile-not-found"
    exit_code = 2
    http_status = 404


class ProfileTamperedError(ProfileError):
    """body_sha256 mismatch on save_profile without --force."""

    code = "profile-tampered"
    exit_code = 3
    http_status = 409


class BackendError(CasperError):
    """CLI writer unavailable, auth error, timeout, or empty output."""

    code = "backend-error"
    exit_code = 2
    http_status = 502


class SecurityError(CasperError):
    """Non-loopback bind, bad Host/Origin/Sec-Fetch-Site, path traversal, SSRF, or zip bomb."""

    code = "security-error"
    exit_code = 2
    http_status = 403


class PayloadTooLargeError(CasperError):
    """HTTP body > 256 KiB or notes > 40,000 / text > 60,000 chars."""

    code = "payload-too-large"
    exit_code = 2
    http_status = 413


class BusyError(CasperError):
    """Single-flight lock acquisition timed out under slow CLI load."""

    code = "server-busy"
    exit_code = 2
    http_status = 503
