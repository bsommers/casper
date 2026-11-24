"""TC-050: Casper Super-Cute Ghost Brand & Visual Asset Kit verification (spec/05-brand-assets.md)."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BRAND_DIR = ROOT / "docs" / "brand"
WEB_STATIC_IMG = ROOT / "src" / "casper" / "web" / "static" / "img"
BUILD_SCRIPT = ROOT / "scripts" / "build_brand.py"

EXPECTED_SVGS: dict[str, tuple[int, int]] = {
    "casper-mark.svg": (512, 512),
    "casper-logo-light.svg": (640, 180),
    "casper-logo-dark.svg": (640, 180),
    "casper-hero.svg": (1200, 360),
    "favicon.svg": (64, 64),
    "icons/icon-voice.svg": (64, 64),
    "icons/icon-facts.svg": (64, 64),
    "icons/icon-plan.svg": (64, 64),
    "icons/icon-validate.svg": (64, 64),
    "icons/icon-format.svg": (64, 64),
    "icons/icon-cli-writer.svg": (64, 64),
    "stickers/casper-sticker-diecut.svg": (1500, 1500),
    "stickers/casper-sticker-wordmark-diecut.svg": (1800, 1200),
    "stickers/casper-sticker-sheet.svg": (2550, 3300),
    "wallpapers/casper-wallpaper-dark-1920x1080.svg": (1920, 1080),
    "wallpapers/casper-wallpaper-dark-2560x1080.svg": (2560, 1080),
    "wallpapers/casper-wallpaper-dark-2560x1440.svg": (2560, 1440),
    "wallpapers/casper-wallpaper-dark-3440x1440.svg": (3440, 1440),
    "wallpapers/casper-wallpaper-dark-3480x1440.svg": (3480, 1440),
    "wallpapers/casper-wallpaper-dark-1170x2532.svg": (1170, 2532),
    "wallpapers/casper-wallpaper-dark-1290x2796.svg": (1290, 2796),
    "wallpapers/casper-wallpaper-dark-1440x3120.svg": (1440, 3120),
    "wallpapers/casper-wallpaper-light-1920x1080.svg": (1920, 1080),
    "wallpapers/casper-wallpaper-light-2560x1080.svg": (2560, 1080),
    "wallpapers/casper-wallpaper-light-2560x1440.svg": (2560, 1440),
    "wallpapers/casper-wallpaper-light-3440x1440.svg": (3440, 1440),
    "wallpapers/casper-wallpaper-light-3480x1440.svg": (3480, 1440),
    "wallpapers/casper-wallpaper-light-1170x2532.svg": (1170, 2532),
    "wallpapers/casper-wallpaper-light-1290x2796.svg": (1290, 2796),
    "wallpapers/casper-wallpaper-light-1440x3120.svg": (1440, 3120),
}

EXPECTED_PNGS: dict[str, tuple[int, int]] = {
    "casper-mark-512.png": (512, 512),
    "casper-mark-1024.png": (1024, 1024),
    "casper-hero.png": (1200, 360),
    "favicon-16x16.png": (16, 16),
    "favicon-32x32.png": (32, 32),
    "apple-touch-icon.png": (180, 180),
    "icon-192x192.png": (192, 192),
    "icon-512x512.png": (512, 512),
    "icon-1024x1024.png": (1024, 1024),
    "stickers/casper-sticker-diecut.png": (1500, 1500),
    "stickers/casper-sticker-diecut-1024.png": (1024, 1024),
    "stickers/casper-sticker-wordmark-diecut.png": (1800, 1200),
    "stickers/casper-sticker-sheet.png": (2550, 3300),
    "wallpapers/casper-wallpaper-dark-1920x1080.png": (1920, 1080),
    "wallpapers/casper-wallpaper-dark-2560x1080.png": (2560, 1080),
    "wallpapers/casper-wallpaper-dark-2560x1440.png": (2560, 1440),
    "wallpapers/casper-wallpaper-dark-3440x1440.png": (3440, 1440),
    "wallpapers/casper-wallpaper-dark-3480x1440.png": (3480, 1440),
    "wallpapers/casper-wallpaper-dark-1170x2532.png": (1170, 2532),
    "wallpapers/casper-wallpaper-dark-1290x2796.png": (1290, 2796),
    "wallpapers/casper-wallpaper-dark-1440x3120.png": (1440, 3120),
    "wallpapers/casper-wallpaper-light-1920x1080.png": (1920, 1080),
    "wallpapers/casper-wallpaper-light-2560x1080.png": (2560, 1080),
    "wallpapers/casper-wallpaper-light-2560x1440.png": (2560, 1440),
    "wallpapers/casper-wallpaper-light-3440x1440.png": (3440, 1440),
    "wallpapers/casper-wallpaper-light-3480x1440.png": (3480, 1440),
    "wallpapers/casper-wallpaper-light-1170x2532.png": (1170, 2532),
    "wallpapers/casper-wallpaper-light-1290x2796.png": (1290, 2796),
    "wallpapers/casper-wallpaper-light-1440x3120.png": (1440, 3120),
}

STICKER_SVGS: tuple[str, ...] = (
    "stickers/casper-sticker-diecut.svg",
    "stickers/casper-sticker-wordmark-diecut.svg",
    "stickers/casper-sticker-sheet.svg",
)

STICKER_PNGS: tuple[str, ...] = (
    "stickers/casper-sticker-diecut.png",
    "stickers/casper-sticker-diecut-1024.png",
    "stickers/casper-sticker-wordmark-diecut.png",
    "stickers/casper-sticker-sheet.png",
)

WEB_SYNCED_FILES: tuple[str, ...] = (
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


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def test_all_brand_deliverables_exist() -> None:
    missing: list[str] = []
    for rel in (*EXPECTED_SVGS, *EXPECTED_PNGS, "favicon.ico"):
        if not (BRAND_DIR / rel).is_file():
            missing.append(rel)
    assert not missing, f"Missing brand assets in docs/brand/: {missing}"


def test_build_brand_check_zero_drift() -> None:
    proc = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"build_brand.py --check failed:\n{proc.stderr}\n{proc.stdout}"


def test_svgs_valid_xml_self_contained_and_exact_viewbox() -> None:
    for rel, (w, h) in EXPECTED_SVGS.items():
        path = BRAND_DIR / rel
        raw = path.read_text(encoding="utf-8")
        assert "@import" not in raw, f"@import directive found in {rel}"
        assert not re.search(r"<image\b", raw, re.IGNORECASE), f"External <image> tag found in {rel}"
        assert not re.search(r'href\s*=\s*["\']https?://', raw, re.IGNORECASE), (
            f"External URL href found in {rel}"
        )
        root = ET.fromstring(raw)
        assert _strip_ns(root.tag) == "svg", f"Root tag is not <svg> in {rel}"
        assert root.attrib.get("viewBox") == f"0 0 {w} {h}", (
            f"Unexpected viewBox in {rel}: {root.attrib.get('viewBox')}"
        )


def test_favicon_svg_stroke_legibility() -> None:
    root = ET.fromstring((BRAND_DIR / "favicon.svg").read_text(encoding="utf-8"))
    strokes = [
        float(el.attrib["stroke-width"])
        for el in root.iter()
        if "stroke-width" in el.attrib
    ]
    assert strokes, "favicon.svg must define visible strokes"
    assert min(strokes) >= 2.0, f"favicon.svg has thin stroke < 2.0px: {min(strokes)}"


def test_sticker_svgs_contain_cutline_group() -> None:
    for rel in STICKER_SVGS:
        root = ET.fromstring((BRAND_DIR / rel).read_text(encoding="utf-8"))
        cutlines = [
            el for el in root.iter() if _strip_ns(el.tag) == "g" and el.attrib.get("id") == "cutline"
        ]
        assert len(cutlines) == 1, f"{rel} must contain exactly one <g id='cutline'>"
        paths = [el for el in cutlines[0].iter() if _strip_ns(el.tag) == "path"]
        assert paths, f"{rel} <g id='cutline'> must contain at least one <path>"


def test_png_dimensions_and_mode() -> None:
    for rel, expected_size in EXPECTED_PNGS.items():
        with Image.open(BRAND_DIR / rel) as img:
            assert img.size == expected_size, f"{rel}: expected {expected_size}, got {img.size}"
            assert img.mode == "RGBA", f"{rel}: expected RGBA, got {img.mode}"


def test_favicon_ico_multi_resolution() -> None:
    with Image.open(BRAND_DIR / "favicon.ico") as ico:
        sizes = set(ico.info.get("sizes", set()))
        for req in ((16, 16), (32, 32), (48, 48)):
            assert req in sizes, f"favicon.ico missing resolution {req}; found {sorted(sizes)}"


def test_sticker_pngs_transparent_corners_and_vinyl_cutout() -> None:
    for rel in STICKER_PNGS:
        with Image.open(BRAND_DIR / rel) as img:
            assert img.mode == "RGBA", f"{rel} must be RGBA"
            w, h = img.size
            corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (4, 4), (w - 5, h - 5)]
            for x, y in corners:
                pixel = img.getpixel((x, y))
                assert isinstance(pixel, tuple) and pixel[3] == 0, (
                    f"{rel}: corner ({x}, {y}) is not transparent (rgba={pixel})"
                )
            # Confirm image has non-transparent opaque vinyl/artwork inside
            bbox = img.getchannel("A").getbbox()
            assert bbox is not None, f"{rel}: sticker is completely blank"
            assert bbox[0] > 0 and bbox[1] > 0 and bbox[2] < w and bbox[3] < h, (
                f"{rel}: sticker cutout touches outer image edge ({bbox} vs {w}x{h})"
            )


def test_web_static_img_byte_sync() -> None:
    for name in WEB_SYNCED_FILES:
        src = BRAND_DIR / name
        dst = WEB_STATIC_IMG / name
        assert src.is_file(), f"Missing docs/brand/{name}"
        assert dst.is_file(), f"Missing src/casper/web/static/img/{name}"
        assert hashlib.sha256(src.read_bytes()).digest() == hashlib.sha256(dst.read_bytes()).digest(), (
            f"Byte mismatch for synced web brand asset: {name}"
        )
