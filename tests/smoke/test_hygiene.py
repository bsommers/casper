"""TC-004: Repository hygiene, .gitignore rules, relative links, zero external brands, brand sync."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# External third-party brand names that must never leak into Casper (GC-08).
FORBIDDEN_BRANDS = (
    "fastly",
    "cloudflare",
    "akamai",
    "netlify",
    "vercel",
)

WEB_SYNCED_BRAND_FILES = (
    "casper-mark.svg",
    "casper-logo-light.svg",
    "casper-logo-dark.svg",
    "favicon.svg",
    "favicon.ico",
    "favicon-16x16.png",
    "favicon-32x32.png",
    "apple-touch-icon.png",
    "icon-192x192.png",
    "icon-512x512.png",
)


def _iter_text_files() -> list[Path]:
    skip_dirs = {
        ".git",
        ".venv",
        "target",
        "raw_inputs",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".hypothesis",
    }
    text_exts = {".py", ".md", ".yaml", ".yml", ".toml", ".sh", ".html", ".css", ".js", ".txt"}
    out: list[Path] = []
    for path in ROOT.rglob("*"):
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() in text_exts:
            if path.name.endswith(".local.yaml"):
                continue
            out.append(path)
    return out


def test_gitignore_required_rules() -> None:
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("target/", "input/*", "!input/README.md", "output/*", "!output/README.md", "authors/*.local.yaml"):
        assert pattern in gi, f"Missing .gitignore rule: {pattern}"
    assert (ROOT / "input" / "README.md").is_file()
    assert (ROOT / "output" / "README.md").is_file()


def test_zero_external_brand_leakage() -> None:
    this_file = Path(__file__).resolve()
    pattern = re.compile(r"\b(" + "|".join(re.escape(b) for b in FORBIDDEN_BRANDS) + r")\b", re.IGNORECASE)
    hits: list[str] = []
    for path in _iter_text_files():
        if path.resolve() == this_file:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in pattern.finditer(text):
            hits.append(f"{path.relative_to(ROOT)}: {m.group(0)}")
    assert not hits, f"Forbidden third-party brand strings found: {hits}"


def test_markdown_relative_links_exist() -> None:
    link_re = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    broken: list[str] = []
    for md in [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]:
        if not md.is_file():
            continue
        text = md.read_text(encoding="utf-8")
        # Strip fenced code blocks
        cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        for target in link_re.findall(cleaned):
            target = target.strip().split()[0]
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            rel = target.split("#", 1)[0]
            if not rel:
                continue
            resolved = (md.parent / rel).resolve()
            if not resolved.exists():
                broken.append(f"{md.relative_to(ROOT)} -> {target}")
    assert not broken, f"Broken relative markdown links: {broken}"


def test_brand_static_sync_when_brand_exists() -> None:
    brand_dir = ROOT / "docs" / "brand"
    static_img = ROOT / "src" / "casper" / "web" / "static" / "img"
    if not brand_dir.exists():
        # Phased check per 04-implementation-plan.md Task 1: activates once Task 14 creates docs/brand/
        return
    for name in WEB_SYNCED_BRAND_FILES:
        src = brand_dir / name
        dst = static_img / name
        assert src.is_file(), f"Missing brand asset: {src}"
        assert dst.is_file(), f"Missing synced static asset: {dst}"
        assert hashlib.sha256(src.read_bytes()).digest() == hashlib.sha256(dst.read_bytes()).digest(), (
            f"Brand asset out of sync: {name}"
        )
