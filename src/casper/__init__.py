"""Casper — the friendly ghostwriter (Rank 8 lazy public API exports)."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__version__ = "0.1.0"

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Uniform core commands (all 10 + generate alias)
    "write_draft": ("casper.commands", "write_draft"),
    "generate": ("casper.commands", "write_draft"),
    "extract_facts": ("casper.commands", "extract_facts"),
    "score_draft": ("casper.commands", "score_draft"),
    "list_options": ("casper.commands", "list_options"),
    "backend_status": ("casper.commands", "backend_status"),
    "author_build": ("casper.commands", "author_build"),
    "author_inspect": ("casper.commands", "author_inspect"),
    "author_show": ("casper.commands", "author_show"),
    "author_list": ("casper.commands", "author_list"),
    "author_diff": ("casper.commands", "author_diff"),
    # Core models
    "AuthorDiff": ("casper.models", "AuthorDiff"),
    "AuthorSummary": ("casper.models", "AuthorSummary"),
    "BackendKind": ("casper.models", "BackendKind"),
    "BackendStatusReport": ("casper.models", "BackendStatusReport"),
    "Brief": ("casper.models", "Brief"),
    "ConformanceReport": ("casper.models", "ConformanceReport"),
    "Fact": ("casper.models", "Fact"),
    "FactKind": ("casper.models", "FactKind"),
    "FactModel": ("casper.models", "FactModel"),
    "FidelityMode": ("casper.models", "FidelityMode"),
    "Result": ("casper.models", "Result"),
    "Validation": ("casper.models", "Validation"),
    # Typed errors
    "BackendError": ("casper.errors", "BackendError"),
    "BusyError": ("casper.errors", "BusyError"),
    "CasperError": ("casper.errors", "CasperError"),
    "InputError": ("casper.errors", "InputError"),
    "LibraryError": ("casper.errors", "LibraryError"),
    "PayloadTooLargeError": ("casper.errors", "PayloadTooLargeError"),
    "ProfileError": ("casper.errors", "ProfileError"),
    "ProfileNotFoundError": ("casper.errors", "ProfileNotFoundError"),
    "ProfileTamperedError": ("casper.errors", "ProfileTamperedError"),
    "SecurityError": ("casper.errors", "SecurityError"),
}

__all__ = ["__version__", *_LAZY_EXPORTS.keys()]


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'casper' has no attribute {name!r}")
    mod_name, attr_name = target
    mod = import_module(mod_name)
    value = getattr(mod, attr_name)
    globals()[name] = value
    return value
