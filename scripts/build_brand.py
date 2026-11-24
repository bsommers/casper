#!/usr/bin/env python3
"""Deterministically generate the Casper Super-Cute Ghost Brand & Visual Asset Kit.

Contract: spec/05-brand-assets.md (TC-050).
Usage:
    python3 scripts/build_brand.py          # Generate docs/brand/ and sync web/static/img/
    python3 scripts/build_brand.py --check  # Verify byte-identical zero-drift against fresh build
"""

from __future__ import annotations

import argparse
import hashlib
import html
import math
import shutil
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = ROOT / "docs" / "brand"
WEB_STATIC_IMG_DIR = ROOT / "src" / "casper" / "web" / "static" / "img"

# Signature palette (spec/05-brand-assets.md §1)
INK = "#0F172A"
GHOST_LIGHT = "#F8FAFC"
GHOST_MID = "#EFF6FF"
GHOST_SHEEN = "#E0F2FE"
GHOST_SHADOW = "#BAE6FD"
CYAN = "#38BDF8"
CYAN_DEEP = "#0284C7"
CYAN_MID = "#0EA5E9"
BLUSH = "#FDA4AF"
GOLD = "#FBBF24"
GOLD_LIGHT = "#FDE68A"
GOLD_DEEP = "#D97706"
DARK_BG_TOP = "#0B0F1A"
DARK_BG_BOT = "#131B2E"
DARK_GRID = "#1E293B"
LIGHT_BG_TOP = "#F8FAFC"
LIGHT_BG_BOT = "#EFF6FF"
SLATE_MUTED = "#94A3B8"
SLATE_SUB = "#475569"
CUTLINE_MAGENTA = "#EC4899"

WALLPAPER_RESOLUTIONS: tuple[tuple[int, int], ...] = (
    # Desktop & Ultrawide Monitor Wallpapers
    (1920, 1080),
    (2560, 1080),
    (2560, 1440),
    (3440, 1440),
    (3480, 1440),
    # Mobile Phone Wallpapers (iPhone / Android portrait)
    (1170, 2532),
    (1290, 2796),
    (1440, 3120),
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

SUBSYSTEM_ICONS: tuple[str, ...] = (
    "icon-voice.svg",
    "icon-facts.svg",
    "icon-plan.svg",
    "icon-validate.svg",
    "icon-format.svg",
    "icon-cli-writer.svg",
)

# ---------------------------------------------------------------------------
# Color & math helpers
# ---------------------------------------------------------------------------


def _hex_rgba(code: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = code.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_color(
    c1: tuple[int, int, int, int], c2: tuple[int, int, int, int], t: float
) -> tuple[int, int, int, int]:
    return (
        int(round(_lerp(c1[0], c2[0], t))),
        int(round(_lerp(c1[1], c2[1], t))),
        int(round(_lerp(c1[2], c2[2], t))),
        int(round(_lerp(c1[3], c2[3], t))),
    )


def _cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int = 24,
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        x = (
            (u**3) * p0[0]
            + 3.0 * (u**2) * t * p1[0]
            + 3.0 * u * (t**2) * p2[0]
            + (t**3) * p3[0]
        )
        y = (
            (u**3) * p0[1]
            + 3.0 * (u**2) * t * p1[1]
            + 3.0 * u * (t**2) * p2[1]
            + (t**3) * p3[1]
        )
        pts.append((x, y))
    return pts


def _rotate_pt(
    pt: tuple[float, float], deg: float, cx: float = 256.0, cy: float = 256.0
) -> tuple[float, float]:
    rad = math.radians(deg)
    ca, sa = math.cos(rad), math.sin(rad)
    dx, dy = pt[0] - cx, pt[1] - cy
    return (cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)


def _scale_pts(
    pts: Iterable[tuple[float, float]], scale: float, ox: float = 0.0, oy: float = 0.0
) -> list[tuple[float, float]]:
    return [(ox + x * scale, oy + y * scale) for x, y in pts]


def _star4_points(cx: float, cy: float, r_outer: float, r_inner: float | None = None) -> list[tuple[float, float]]:
    ri = r_inner if r_inner is not None else r_outer * 0.34
    pts: list[tuple[float, float]] = []
    for i in range(8):
        ang = math.radians(-90 + i * 45)
        r = r_outer if i % 2 == 0 else ri
        pts.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r))
    return pts


def _svg_poly_path(pts: list[tuple[float, float]]) -> str:
    head = f"M {pts[0][0]:.2f},{pts[0][1]:.2f}"
    tail = " ".join(f"L {x:.2f},{y:.2f}" for x, y in pts[1:])
    return f"{head} {tail} Z"


# ---------------------------------------------------------------------------
# Shared Ghost Mascot Vector Geometry (512x512 canonical space, -3° tilt)
# ---------------------------------------------------------------------------

# Plump friendly ghost silhouette with 3 smooth bottom scallops (cubic segments)
GHOST_BODY_SEGMENTS: tuple[
    tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]], ...
] = (
    # Top dome -> left upper cheek
    ((256.0, 78.0), (176.0, 78.0), (124.0, 134.0), (124.0, 220.0)),
    # Left cheek -> left lower flare
    ((124.0, 220.0), (124.0, 286.0), (116.0, 336.0), (118.0, 368.0)),
    # Scallop 1 (left wave)
    ((118.0, 368.0), (120.0, 412.0), (176.0, 420.0), (206.0, 384.0)),
    # Scallop 2 (center wave)
    ((206.0, 384.0), (226.0, 424.0), (286.0, 424.0), (306.0, 384.0)),
    # Scallop 3 (right wave)
    ((306.0, 384.0), (336.0, 420.0), (392.0, 412.0), (394.0, 368.0)),
    # Right lower flare -> right upper cheek
    ((394.0, 368.0), (396.0, 336.0), (388.0, 286.0), (388.0, 220.0)),
    # Right upper cheek -> top dome
    ((388.0, 220.0), (388.0, 134.0), (336.0, 78.0), (256.0, 78.0)),
)


def _ghost_body_svg_path() -> str:
    parts = [f"M {GHOST_BODY_SEGMENTS[0][0][0]:.1f},{GHOST_BODY_SEGMENTS[0][0][1]:.1f}"]
    for _, c1, c2, end in GHOST_BODY_SEGMENTS:
        parts.append(f"C {c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {end[0]:.1f},{end[1]:.1f}")
    parts.append("Z")
    return " ".join(parts)


def _ghost_body_polygon(steps: int = 24) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for p0, p1, p2, p3 in GHOST_BODY_SEGMENTS:
        pts.extend(_cubic_bezier(p0, p1, p2, p3, steps=steps)[:-1])
    return pts


def _smile_points(steps: int = 20) -> list[tuple[float, float]]:
    return _cubic_bezier((230.0, 260.0), (242.0, 282.0), (266.0, 282.0), (278.0, 260.0), steps=steps)


def _highlight_crescent_polygon(steps: int = 16) -> list[tuple[float, float]]:
    outer = _cubic_bezier((162.0, 174.0), (168.0, 128.0), (206.0, 102.0), (244.0, 100.0), steps=steps)
    inner = _cubic_bezier((244.0, 100.0), (214.0, 118.0), (186.0, 144.0), (178.0, 182.0), steps=steps)
    return outer + inner


def _pen_geometry() -> dict[str, list[tuple[float, float]]]:
    """Return angled fountain pen geometry in 512x512 mascot space (pre-tilt)."""
    # Local pen coordinates centered around grip (0, 0), pointing left-down along (-1, 0)
    # Then rotated by -38° and translated to (368, 284).
    ang = -38.0
    tx, ty = 374.0, 276.0

    def xform(local_pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
        rad = math.radians(ang)
        ca, sa = math.cos(rad), math.sin(rad)
        return [(tx + x * ca - y * sa, ty + x * sa + y * ca) for x, y in local_pts]

    barrel_upper = xform([(-22.0, -14.0), (84.0, -12.0), (96.0, -6.0), (96.0, 0.0), (-22.0, 0.0)])
    barrel_lower = xform([(-22.0, 0.0), (96.0, 0.0), (96.0, 6.0), (84.0, 12.0), (-22.0, 14.0)])
    barrel_full = xform(
        [
            (-22.0, -14.0),
            (84.0, -12.0),
            (96.0, -6.0),
            (96.0, 6.0),
            (84.0, 12.0),
            (-22.0, 14.0),
        ]
    )
    barrel_shine = xform([(-12.0, -9.0), (74.0, -7.5), (74.0, -3.5), (-12.0, -4.5)])
    collar = xform([(-32.0, -13.0), (-20.0, -14.0), (-20.0, 14.0), (-32.0, 13.0)])
    nib = xform([(-32.0, -11.5), (-52.0, -9.0), (-78.0, 0.0), (-52.0, 9.0), (-32.0, 11.5)])
    nib_slit = xform([(-74.0, 0.0), (-49.0, 0.0)])
    nib_hole = xform([(-46.0, 0.0)])
    return {
        "barrel_upper": barrel_upper,
        "barrel_lower": barrel_lower,
        "barrel_full": barrel_full,
        "barrel_shine": barrel_shine,
        "collar": collar,
        "nib": nib,
        "nib_slit": nib_slit,
        "nib_hole": nib_hole,
    }


# ---------------------------------------------------------------------------
# SVG Mascot & Reusable SVG Fragment Builders (100% self-contained XML)
# ---------------------------------------------------------------------------


def _svg_mascot_defs(prefix: str, dark: bool) -> str:
    glow_filter = (
        f'    <filter id="{prefix}-glow" x="-25%" y="-25%" width="150%" height="150%">\n'
        f'      <feGaussianBlur stdDeviation="8" result="blur"/>\n'
        f'      <feMerge>\n'
        f'        <feMergeNode in="blur"/>\n'
        f'        <feMergeNode in="SourceGraphic"/>\n'
        f'      </feMerge>\n'
        f'    </filter>\n'
        if dark
        else ""
    )
    return (
        f'    <radialGradient id="{prefix}-body-grad" cx="38%" cy="30%" r="70%">\n'
        f'      <stop offset="0%" stop-color="#FFFFFF"/>\n'
        f'      <stop offset="52%" stop-color="{GHOST_LIGHT}"/>\n'
        f'      <stop offset="86%" stop-color="{GHOST_SHEEN}"/>\n'
        f'      <stop offset="100%" stop-color="{GHOST_SHADOW}"/>\n'
        f'    </radialGradient>\n'
        f'    <linearGradient id="{prefix}-pen-grad" x1="0%" y1="0%" x2="0%" y2="100%">\n'
        f'      <stop offset="0%" stop-color="{CYAN}"/>\n'
        f'      <stop offset="55%" stop-color="{CYAN_MID}"/>\n'
        f'      <stop offset="100%" stop-color="{CYAN_DEEP}"/>\n'
        f'    </linearGradient>\n'
        f'    <linearGradient id="{prefix}-nib-grad" x1="0%" y1="0%" x2="100%" y2="100%">\n'
        f'      <stop offset="0%" stop-color="{GOLD_LIGHT}"/>\n'
        f'      <stop offset="55%" stop-color="{GOLD}"/>\n'
        f'      <stop offset="100%" stop-color="{GOLD_DEEP}"/>\n'
        f'    </linearGradient>\n'
        f"{glow_filter}"
    )


def _svg_mascot_group(prefix: str, dark: bool = False, include_shadow: bool = True) -> str:
    body_path = _ghost_body_svg_path()
    crescent = _svg_poly_path(_highlight_crescent_polygon())
    pen = _pen_geometry()
    barrel_d = _svg_poly_path(pen["barrel_full"])
    shine_d = _svg_poly_path(pen["barrel_shine"])
    collar_d = _svg_poly_path(pen["collar"])
    nib_d = _svg_poly_path(pen["nib"])
    slit_p0, slit_p1 = pen["nib_slit"]
    hole_pt = pen["nib_hole"][0]

    star1 = _svg_poly_path(_star4_points(426.0, 128.0, 24.0))
    star2 = _svg_poly_path(_star4_points(456.0, 184.0, 15.0))
    star3 = _svg_poly_path(_star4_points(94.0, 146.0, 14.0))

    shadow_svg = ""
    if include_shadow:
        sh_fill = CYAN if dark else INK
        sh_op = "0.24" if dark else "0.12"
        shadow_svg = f'    <ellipse cx="256" cy="454" rx="84" ry="13" fill="{sh_fill}" opacity="{sh_op}"/>\n'

    dark_rim = (
        f'      <path d="{body_path}" fill="none" stroke="{CYAN}" stroke-width="24" '
        f'stroke-linejoin="round" opacity="0.55" filter="url(#{prefix}-glow)"/>\n'
        f'      <path d="{body_path}" fill="none" stroke="{CYAN}" stroke-width="17" '
        f'stroke-linejoin="round" opacity="0.9"/>\n'
        if dark
        else ""
    )

    return (
        f"{shadow_svg}"
        f'    <g transform="rotate(-3 256 256)">\n'
        f"{dark_rim}"
        # Ghost body
        f'      <path d="{body_path}" fill="url(#{prefix}-body-grad)" stroke="{INK}" '
        f'stroke-width="13" stroke-linejoin="round"/>\n'
        # Soft glossy dome highlight
        f'      <path d="{crescent}" fill="#FFFFFF" opacity="0.82"/>\n'
        # Subtle left tucked stub arm
        f'      <path d="M 122,262 C 98,270 98,308 128,308" fill="{GHOST_LIGHT}" '
        f'stroke="{INK}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>\n'
        # Rosy blush cheeks
        f'      <ellipse cx="170" cy="256" rx="22" ry="12.5" fill="{BLUSH}" opacity="0.78"/>\n'
        f'      <ellipse cx="338" cy="256" rx="22" ry="12.5" fill="{BLUSH}" opacity="0.78"/>\n'
        # Large expressive dark-navy eyes with dual specular highlights
        f'      <ellipse cx="204" cy="222" rx="22" ry="27" fill="{INK}"/>\n'
        f'      <circle cx="195" cy="210" r="8.5" fill="#FFFFFF"/>\n'
        f'      <circle cx="212" cy="231" r="3.8" fill="#FFFFFF"/>\n'
        f'      <ellipse cx="302" cy="222" rx="22" ry="27" fill="{INK}"/>\n'
        f'      <circle cx="293" cy="210" r="8.5" fill="#FFFFFF"/>\n'
        f'      <circle cx="310" cy="231" r="3.8" fill="#FFFFFF"/>\n'
        # Warm curved smile
        f'      <path d="M 230,260 C 242,282 266,282 278,260" fill="none" stroke="{INK}" '
        f'stroke-width="10" stroke-linecap="round"/>\n'
        # Glowing sky-cyan fountain pen + golden nib
        f'      <path d="{nib_d}" fill="url(#{prefix}-nib-grad)" stroke="{INK}" '
        f'stroke-width="8" stroke-linejoin="round"/>\n'
        f'      <line x1="{slit_p0[0]:.1f}" y1="{slit_p0[1]:.1f}" x2="{slit_p1[0]:.1f}" y2="{slit_p1[1]:.1f}" '
        f'stroke="{INK}" stroke-width="4" stroke-linecap="round"/>\n'
        f'      <circle cx="{hole_pt[0]:.1f}" cy="{hole_pt[1]:.1f}" r="3.6" fill="{INK}"/>\n'
        f'      <path d="{barrel_d}" fill="url(#{prefix}-pen-grad)" stroke="{INK}" '
        f'stroke-width="9" stroke-linejoin="round"/>\n'
        f'      <path d="{shine_d}" fill="{GHOST_SHEEN}" opacity="0.78"/>\n'
        f'      <path d="{collar_d}" fill="{GOLD}" stroke="{INK}" stroke-width="7" stroke-linejoin="round"/>\n'
        # Cute tucked right hand gripping the pen
        f'      <ellipse cx="366" cy="284" rx="26" ry="20" transform="rotate(-14 366 284)" '
        f'fill="{GHOST_LIGHT}" stroke="{INK}" stroke-width="11"/>\n'
        # Floating sparkle stars & glowing ink accents
        f'      <path d="{star1}" fill="{GOLD}" stroke="{INK}" stroke-width="4.5" stroke-linejoin="round"/>\n'
        f'      <path d="{star2}" fill="{CYAN}" stroke="{INK}" stroke-width="3.5" stroke-linejoin="round"/>\n'
        f'      <path d="{star3}" fill="{GOLD}" stroke="{INK}" stroke-width="3.5" stroke-linejoin="round"/>\n'
        f'      <circle cx="299" cy="340" r="6" fill="{CYAN}" stroke="{INK}" stroke-width="3"/>\n'
        f'      <circle cx="283" cy="350" r="4" fill="{GOLD}"/>\n'
        f'    </g>\n'
    )


def _svg_wrap(width: int, height: int, body: str, defs: str = "", title: str = "Casper") -> str:
    defs_block = f"  <defs>\n{defs}  </defs>\n" if defs else ""
    safe_title = html.escape(title, quote=True)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="{safe_title}">\n'
        f"  <title>{safe_title}</title>\n"
        f"{defs_block}"
        f"{body}"
        "</svg>\n"
    )


# ---------------------------------------------------------------------------
# SVG Asset Generators (§2.1, §2.2, §2.3, §2.4)
# ---------------------------------------------------------------------------


def build_mark_svg() -> str:
    return _svg_wrap(
        512,
        512,
        _svg_mascot_group("m", dark=False, include_shadow=True),
        defs=_svg_mascot_defs("m", dark=False),
        title="Casper Ghostwriter Mascot",
    )


def build_logo_svg(dark: bool) -> str:
    prefix = "ld" if dark else "ll"
    word_fill = GHOST_LIGHT if dark else INK
    sub_fill = SLATE_MUTED if dark else SLATE_SUB
    accent = CYAN if dark else CYAN_MID
    body = (
        f'  <g transform="translate(12, 8) scale(0.32)">\n'
        f"{_svg_mascot_group(prefix, dark=dark, include_shadow=True)}"
        f"  </g>\n"
        f'  <text x="192" y="102" fill="{word_fill}" '
        f'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" '
        f'font-size="76" font-weight="800" letter-spacing="6">CASPER</text>\n'
        f'  <rect x="194" y="114" width="64" height="5" rx="2.5" fill="{accent}"/>\n'
        f'  <text x="270" y="124" fill="{sub_fill}" '
        f'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" '
        f'font-size="22" font-weight="600" letter-spacing="1.5">friendly ghostwriter</text>\n'
    )
    return _svg_wrap(
        640,
        180,
        body,
        defs=_svg_mascot_defs(prefix, dark=dark),
        title=f"Casper Logo ({'Dark' if dark else 'Light'})",
    )


def build_hero_svg() -> str:
    defs = (
        f'    <linearGradient id="hero-bg" x1="0%" y1="0%" x2="100%" y2="100%">\n'
        f'      <stop offset="0%" stop-color="{DARK_BG_TOP}"/>\n'
        f'      <stop offset="100%" stop-color="{DARK_BG_BOT}"/>\n'
        f'    </linearGradient>\n'
        f'    <radialGradient id="hero-aura" cx="22%" cy="52%" r="34%">\n'
        f'      <stop offset="0%" stop-color="{CYAN}" stop-opacity="0.28"/>\n'
        f'      <stop offset="55%" stop-color="{CYAN}" stop-opacity="0.08"/>\n'
        f'      <stop offset="100%" stop-color="{CYAN}" stop-opacity="0"/>\n'
        f'    </radialGradient>\n'
        f'    <pattern id="hero-grid" width="40" height="40" patternUnits="userSpaceOnUse">\n'
        f'      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="{CYAN}" stroke-width="0.8" opacity="0.11"/>\n'
        f'    </pattern>\n'
        + _svg_mascot_defs("hero", dark=True)
    )
    stars = [
        (88, 56, 3.0, GOLD, 0.8),
        (146, 302, 2.2, CYAN, 0.7),
        (430, 52, 2.6, CYAN, 0.75),
        (1096, 62, 3.2, GOLD, 0.85),
        (1134, 118, 2.2, CYAN, 0.7),
        (1042, 294, 2.6, BLUSH, 0.75),
        (960, 48, 2.0, GHOST_LIGHT, 0.6),
    ]
    star_svg = "".join(
        f'  <circle cx="{x}" cy="{y}" r="{r}" fill="{c}" opacity="{op}"/>\n' for x, y, r, c, op in stars
    )
    body = (
        '  <rect width="1200" height="360" rx="20" fill="url(#hero-bg)"/>\n'
        '  <rect width="1200" height="360" rx="20" fill="url(#hero-grid)"/>\n'
        '  <rect width="1200" height="360" rx="20" fill="url(#hero-aura)"/>\n'
        f"{star_svg}"
        '  <g transform="translate(92, 36) scale(0.56)">\n'
        f"{_svg_mascot_group('hero', dark=True, include_shadow=True)}"
        "  </g>\n"
        f'  <text x="430" y="166" fill="{GHOST_LIGHT}" '
        'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" '
        'font-size="94" font-weight="800" letter-spacing="8">CASPER</text>\n'
        f'  <rect x="434" y="186" width="124" height="6" rx="3" fill="{CYAN}"/>\n'
        f'  <text x="434" y="232" fill="{GHOST_SHEEN}" '
        'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" '
        'font-size="28" font-weight="500" letter-spacing="0.8">'
        "the friendly ghostwriter — local-first, deterministic</text>\n"
        # Pill badges
        f'  <rect x="434" y="258" width="166" height="34" rx="17" fill="{DARK_GRID}" stroke="{CYAN}" stroke-width="1.5"/>\n'
        f'  <text x="517" y="280" text-anchor="middle" fill="{CYAN}" '
        'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" font-size="15" font-weight="600">deterministic</text>\n'
        f'  <rect x="614" y="258" width="174" height="34" rx="17" fill="{DARK_GRID}" stroke="{GOLD}" stroke-width="1.5"/>\n'
        f'  <text x="701" y="280" text-anchor="middle" fill="{GOLD}" '
        'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" font-size="15" font-weight="600">zero-invention</text>\n'
        f'  <rect x="802" y="258" width="148" height="34" rx="17" fill="{DARK_GRID}" stroke="{BLUSH}" stroke-width="1.5"/>\n'
        f'  <text x="876" y="280" text-anchor="middle" fill="{BLUSH}" '
        'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" font-size="15" font-weight="600">local-first</text>\n'
    )
    return _svg_wrap(1200, 360, body, defs=defs, title="Casper — the friendly ghostwriter")


def build_favicon_svg() -> str:
    """Simplified crisp 64x64 cute-ghost face with every stroke >= 2.0px."""
    defs = (
        f'    <radialGradient id="fav-body" cx="38%" cy="30%" r="72%">\n'
        f'      <stop offset="0%" stop-color="#FFFFFF"/>\n'
        f'      <stop offset="65%" stop-color="{GHOST_LIGHT}"/>\n'
        f'      <stop offset="100%" stop-color="{GHOST_SHEEN}"/>\n'
        f'    </radialGradient>\n'
    )
    body = (
        f'  <rect x="2" y="2" width="60" height="60" rx="15" fill="{DARK_BG_TOP}" '
        f'stroke="{CYAN}" stroke-width="2.4"/>\n'
        # Simplified plump ghost silhouette (stroke 2.6px >= 2.0px)
        f'  <path d="M 32,11 C 20,11 13,19 13,31 L 13,47 C 13,53 20,54 24,49 '
        f'C 27,54 37,54 40,49 C 44,54 51,53 51,47 L 51,31 C 51,19 44,11 32,11 Z" '
        f'fill="url(#fav-body)" stroke="{INK}" stroke-width="2.6" stroke-linejoin="round"/>\n'
        # Blush cheeks
        f'  <ellipse cx="20" cy="35" rx="3.4" ry="2.1" fill="{BLUSH}"/>\n'
        f'  <ellipse cx="44" cy="35" rx="3.4" ry="2.1" fill="{BLUSH}"/>\n'
        # Expressive eyes + sparkle dots
        f'  <ellipse cx="25" cy="29.5" rx="3.4" ry="4.2" fill="{INK}"/>\n'
        f'  <circle cx="23.8" cy="27.8" r="1.4" fill="#FFFFFF"/>\n'
        f'  <ellipse cx="39" cy="29.5" rx="3.4" ry="4.2" fill="{INK}"/>\n'
        f'  <circle cx="37.8" cy="27.8" r="1.4" fill="#FFFFFF"/>\n'
        # Sweet smile (stroke 2.4px >= 2.0px)
        f'  <path d="M 28.5,35.5 C 30,39 34,39 35.5,35.5" fill="none" stroke="{INK}" '
        f'stroke-width="2.4" stroke-linecap="round"/>\n'
        # Crisp cyan pen nib & gold sparkle accent at top-right
        f'  <path d="M 46,18 L 54,10" stroke="{CYAN}" stroke-width="3.2" stroke-linecap="round"/>\n'
        f'  <circle cx="53" cy="21" r="2.6" fill="{GOLD}"/>\n'
    )
    return _svg_wrap(64, 64, body, defs=defs, title="Casper Favicon")


def build_subsystem_icon_svg(name: str) -> str:
    """Build each 64x64 subsystem badge with crisp strokes >= 2.2px."""
    frame = (
        f'  <rect x="3" y="3" width="58" height="58" rx="14" fill="{DARK_BG_BOT}" '
        f'stroke="{CYAN}" stroke-width="2.2"/>\n'
    )
    if name == "icon-voice.svg":
        # Author Voice Fingerprint: concentric fingerprint wave arcs + gold sparkle
        inner = (
            f'  <path d="M 20,42 C 20,24 44,24 44,42" fill="none" stroke="{GHOST_LIGHT}" stroke-width="2.6" stroke-linecap="round"/>\n'
            f'  <path d="M 14,38 C 14,15 50,15 50,38" fill="none" stroke="{CYAN}" stroke-width="2.6" stroke-linecap="round"/>\n'
            f'  <path d="M 26,45 C 26,32 38,32 38,45" fill="none" stroke="{BLUSH}" stroke-width="2.6" stroke-linecap="round"/>\n'
            f'  <line x1="32" y1="39" x2="32" y2="49" stroke="{GOLD}" stroke-width="2.8" stroke-linecap="round"/>\n'
            f'  <circle cx="49" cy="16" r="3" fill="{GOLD}"/>\n'
        )
        title = "Casper Voice Fingerprint"
    elif name == "icon-facts.svg":
        # Fact Extraction & Graph: 4-node directed graph with verified gold hub
        inner = (
            f'  <line x1="20" y1="22" x2="34" y2="32" stroke="{CYAN}" stroke-width="2.6" stroke-linecap="round"/>\n'
            f'  <line x1="46" y1="19" x2="34" y2="32" stroke="{CYAN}" stroke-width="2.6" stroke-linecap="round"/>\n'
            f'  <line x1="34" y1="32" x2="22" y2="47" stroke="{GHOST_LIGHT}" stroke-width="2.6" stroke-linecap="round"/>\n'
            f'  <line x1="34" y1="32" x2="47" y2="45" stroke="{BLUSH}" stroke-width="2.6" stroke-linecap="round"/>\n'
            f'  <circle cx="20" cy="22" r="5" fill="{GHOST_LIGHT}" stroke="{INK}" stroke-width="2.2"/>\n'
            f'  <circle cx="46" cy="19" r="5" fill="{CYAN}" stroke="{INK}" stroke-width="2.2"/>\n'
            f'  <circle cx="22" cy="47" r="4.5" fill="{BLUSH}" stroke="{INK}" stroke-width="2.2"/>\n'
            f'  <circle cx="47" cy="45" r="4.5" fill="{GHOST_LIGHT}" stroke="{INK}" stroke-width="2.2"/>\n'
            f'  <circle cx="34" cy="32" r="6.5" fill="{GOLD}" stroke="{INK}" stroke-width="2.2"/>\n'
        )
        title = "Casper Fact Extraction & Graph"
    elif name == "icon-plan.svg":
        # Audience & Structure Planner: ordered blueprint blocks + priority target dot
        inner = (
            f'  <rect x="14" y="15" width="36" height="9" rx="3" fill="{CYAN}" stroke="{INK}" stroke-width="2.2"/>\n'
            f'  <rect x="14" y="28" width="26" height="8" rx="3" fill="{GHOST_LIGHT}" stroke="{INK}" stroke-width="2.2"/>\n'
            f'  <rect x="14" y="40" width="20" height="8" rx="3" fill="{GHOST_SHEEN}" stroke="{INK}" stroke-width="2.2"/>\n'
            f'  <circle cx="46" cy="40" r="7" fill="{GOLD}" stroke="{INK}" stroke-width="2.2"/>\n'
            f'  <circle cx="46" cy="40" r="2.5" fill="{INK}"/>\n'
        )
        title = "Casper Audience & Structure Planner"
    elif name == "icon-validate.svg":
        # Fidelity Validator: crisp shield + bold checkmark + gold sparkle
        inner = (
            f'  <path d="M 32,12 L 49,18 L 49,33 C 49,44 41,50 32,53 C 23,50 15,44 15,33 L 15,18 Z" '
            f'fill="{GHOST_LIGHT}" stroke="{INK}" stroke-width="2.6" stroke-linejoin="round"/>\n'
            f'  <path d="M 24,33 L 30,39 L 41,25" fill="none" stroke="{CYAN_DEEP}" '
            f'stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/>\n'
            f'  <circle cx="49" cy="14" r="3.2" fill="{GOLD}"/>\n'
        )
        title = "Casper Fidelity Validator"
    elif name == "icon-format.svg":
        # Multi-Modality Formatter: layered cards + code brackets & prose bars
        inner = (
            f'  <rect x="20" y="13" width="30" height="32" rx="5" fill="{DARK_GRID}" stroke="{CYAN}" stroke-width="2.2"/>\n'
            f'  <rect x="14" y="19" width="30" height="32" rx="5" fill="{GHOST_LIGHT}" stroke="{INK}" stroke-width="2.4"/>\n'
            f'  <path d="M 24,29 L 20,34 L 24,39" fill="none" stroke="{CYAN_DEEP}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>\n'
            f'  <path d="M 34,29 L 38,34 L 34,39" fill="none" stroke="{CYAN_DEEP}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>\n'
            f'  <line x1="21" y1="45" x2="37" y2="45" stroke="{BLUSH}" stroke-width="2.8" stroke-linecap="round"/>\n'
            f'  <circle cx="46" cy="16" r="2.8" fill="{GOLD}"/>\n'
        )
        title = "Casper Multi-Modality Formatter"
    elif name == "icon-cli-writer.svg":
        # Claude / Antigravity CLI Writer: terminal prompt + glowing cyan quill nib
        inner = (
            f'  <rect x="12" y="15" width="40" height="34" rx="6" fill="{DARK_BG_TOP}" stroke="{GHOST_LIGHT}" stroke-width="2.4"/>\n'
            f'  <path d="M 19,27 L 26,32 L 19,37" fill="none" stroke="{CYAN}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>\n'
            f'  <line x1="29" y1="37" x2="37" y2="37" stroke="{GHOST_LIGHT}" stroke-width="2.8" stroke-linecap="round"/>\n'
            f'  <path d="M 39,29 L 51,17" stroke="{CYAN}" stroke-width="3.6" stroke-linecap="round"/>\n'
            f'  <circle cx="38" cy="30" r="3" fill="{GOLD}"/>\n'
        )
        title = "Casper CLI Writer"
    else:
        raise ValueError(f"Unknown subsystem icon: {name}")

    return _svg_wrap(64, 64, frame + inner, title=title)


def _sticker_contour_svg_shapes(scale: float, ox: float, oy: float) -> str:
    """Contoured smooth rounded union envelope around mascot + pen + sparkles in SVG."""
    body_path = _ghost_body_svg_path()
    pen = _pen_geometry()
    barrel_d = _svg_poly_path(pen["barrel_full"])
    nib_d = _svg_poly_path(pen["nib"])
    star1 = _svg_poly_path(_star4_points(426.0, 128.0, 24.0))
    star2 = _svg_poly_path(_star4_points(456.0, 184.0, 15.0))
    star3 = _svg_poly_path(_star4_points(94.0, 146.0, 14.0))
    return (
        f'    <g transform="translate({ox:.1f}, {oy:.1f}) scale({scale:.4f}) rotate(-3 256 256)">\n'
        f'      <path d="{body_path}" fill="#FFFFFF" stroke="#FFFFFF" stroke-width="82" stroke-linejoin="round" stroke-linecap="round"/>\n'
        f'      <path d="{barrel_d}" fill="#FFFFFF" stroke="#FFFFFF" stroke-width="76" stroke-linejoin="round" stroke-linecap="round"/>\n'
        f'      <path d="{nib_d}" fill="#FFFFFF" stroke="#FFFFFF" stroke-width="76" stroke-linejoin="round" stroke-linecap="round"/>\n'
        f'      <path d="{star1}" fill="#FFFFFF" stroke="#FFFFFF" stroke-width="64" stroke-linejoin="round"/>\n'
        f'      <path d="{star2}" fill="#FFFFFF" stroke="#FFFFFF" stroke-width="58" stroke-linejoin="round"/>\n'
        f'      <path d="{star3}" fill="#FFFFFF" stroke="#FFFFFF" stroke-width="58" stroke-linejoin="round"/>\n'
        f'      <circle cx="299" cy="340" r="38" fill="#FFFFFF"/>\n'
        f"    </g>\n"
    )


def _mascot_cutline_path_512() -> str:
    """Single clean closed outer kiss-cut contour path in 512x512 mascot space (~8% vinyl offset)."""
    # Smooth closed cubic Bezier contour hugging dome, left sparkle, 3-wave hem, pen barrel, and right sparkles
    return (
        "M 256,34 "
        "C 334,34 388,68 424,84 "
        "C 464,100 492,136 488,186 "
        "C 484,232 464,268 446,304 "
        "C 432,334 438,376 426,412 "
        "C 412,452 362,468 312,454 "
        "C 276,472 232,472 198,454 "
        "C 146,466 96,448 84,404 "
        "C 74,366 80,318 76,274 "
        "C 66,232 54,186 64,142 "
        "C 74,102 108,82 146,66 "
        "C 180,46 216,34 256,34 Z"
    )


def build_sticker_diecut_svg() -> str:
    scale = 2.42
    ox, oy = 130.0, 130.0
    cut_d = _mascot_cutline_path_512()
    body = (
        # White vinyl offset border cutout (zero background outside!)
        '  <g id="vinyl-border">\n'
        f'    <g transform="translate({ox:.1f}, {oy:.1f}) scale({scale:.4f})">\n'
        f'      <path d="{cut_d}" fill="#FFFFFF" stroke="#CBD5E1" stroke-width="2.5" stroke-linejoin="round"/>\n'
        "    </g>\n"
        f"{_sticker_contour_svg_shapes(scale, ox, oy)}"
        "  </g>\n"
        # Artwork
        f'  <g id="artwork" transform="translate({ox:.1f}, {oy:.1f}) scale({scale:.4f})">\n'
        f"{_svg_mascot_group('st1', dark=False, include_shadow=False)}"
        "  </g>\n"
        # Explicit die-cut kiss-cut vector cutline group
        '  <g id="cutline">\n'
        f'    <g transform="translate({ox:.1f}, {oy:.1f}) scale({scale:.4f})">\n'
        f'      <path d="{cut_d}" fill="none" stroke="{CUTLINE_MAGENTA}" stroke-width="2.4" '
        'stroke-dasharray="10 7" stroke-linejoin="round"/>\n'
        "    </g>\n"
        "  </g>\n"
    )
    return _svg_wrap(
        1500,
        1500,
        body,
        defs=_svg_mascot_defs("st1", dark=False),
        title="Casper Die-Cut Sticker (1500x1500)",
    )


def _wordmark_cutline_path_1800x1200() -> str:
    """Unified smooth contour wrapping mascot (left) + CASPER wordmark badge (right)."""
    return (
        "M 454,146 "
        "C 586,146 680,210 738,318 "
        "C 850,296 1054,284 1280,284 "
        "C 1548,284 1670,350 1670,582 "
        "C 1670,814 1548,892 1268,892 "
        "C 1046,892 864,878 748,858 "
        "C 696,978 588,1048 456,1048 "
        "C 242,1048 130,906 130,616 "
        "C 130,318 250,146 454,146 Z"
    )


def build_sticker_wordmark_diecut_svg() -> str:
    cut_d = _wordmark_cutline_path_1800x1200()
    body = (
        '  <g id="vinyl-border">\n'
        f'    <path d="{cut_d}" fill="#FFFFFF" stroke="#CBD5E1" stroke-width="5" stroke-linejoin="round"/>\n'
        "  </g>\n"
        '  <g id="artwork">\n'
        '    <g transform="translate(152, 224) scale(1.42)">\n'
        f"{_svg_mascot_group('stw', dark=False, include_shadow=False)}"
        "    </g>\n"
        f'    <text x="846" y="612" fill="{INK}" '
        'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" '
        'font-size="188" font-weight="800" letter-spacing="10">CASPER</text>\n'
        f'    <rect x="854" y="646" width="180" height="14" rx="7" fill="{CYAN}"/>\n'
        f'    <text x="854" y="732" fill="{SLATE_SUB}" '
        'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" '
        'font-size="56" font-weight="700" letter-spacing="2">friendly ghostwriter</text>\n'
        "  </g>\n"
        '  <g id="cutline">\n'
        f'    <path d="{cut_d}" fill="none" stroke="{CUTLINE_MAGENTA}" stroke-width="4" '
        'stroke-dasharray="18 12" stroke-linejoin="round"/>\n'
        "  </g>\n"
    )
    return _svg_wrap(
        1800,
        1200,
        body,
        defs=_svg_mascot_defs("stw", dark=False),
        title="Casper Wordmark Die-Cut Sticker (1800x1200)",
    )


def build_sticker_sheet_svg() -> str:
    """Print-ready 8.5x11in @ 300 DPI (2550x3300) kiss-cut sheet with 3 mascot sizes + wordmarks + mini icons."""
    cut_mascot = _mascot_cutline_path_512()
    cut_wordmark = _wordmark_cutline_path_1800x1200()

    # Placements: (x, y, size) for square mascot stickers in 3 sizes
    large_mascots = [(265, 190, 900), (1385, 190, 900)]
    med_mascots = [(220, 1210, 620), (965, 1210, 620), (1710, 1210, 620)]
    wordmarks = [(215, 1950, 1020, 680), (1315, 1950, 1020, 680)]
    mini_mascots = [(205 + i * 440, 2750, 380) for i in range(5)]

    vinyl_parts: list[str] = []
    art_parts: list[str] = []
    cut_parts: list[str] = []

    def add_mascot_sticker(x: float, y: float, sz: float, idx: int) -> None:
        sc = (sz * 0.82) / 512.0
        ox = x + sz * 0.09
        oy = y + sz * 0.09
        vinyl_parts.append(
            f'    <g transform="translate({ox:.1f}, {oy:.1f}) scale({sc:.4f})">\n'
            f'      <path d="{cut_mascot}" fill="#FFFFFF" stroke="#CBD5E1" stroke-width="3" stroke-linejoin="round"/>\n'
            "    </g>\n"
        )
        art_parts.append(
            f'    <g transform="translate({ox:.1f}, {oy:.1f}) scale({sc:.4f})">\n'
            f"{_svg_mascot_group('sh', dark=False, include_shadow=False)}"
            "    </g>\n"
        )
        cut_parts.append(
            f'    <g id="cut-mascot-{idx}" transform="translate({ox:.1f}, {oy:.1f}) scale({sc:.4f})">\n'
            f'      <path d="{cut_mascot}" fill="none" stroke="{CUTLINE_MAGENTA}" stroke-width="3" '
            'stroke-dasharray="12 8" stroke-linejoin="round"/>\n'
            "    </g>\n"
        )

    idx = 0
    for x, y, sz in large_mascots + med_mascots + mini_mascots:
        idx += 1
        add_mascot_sticker(x, y, sz, idx)

    for widx, (x, y, w, _h) in enumerate(wordmarks, start=1):
        sc = w / 1800.0
        vinyl_parts.append(
            f'    <g transform="translate({x:.1f}, {y:.1f}) scale({sc:.4f})">\n'
            f'      <path d="{cut_wordmark}" fill="#FFFFFF" stroke="#CBD5E1" stroke-width="5" stroke-linejoin="round"/>\n'
            "    </g>\n"
        )
        art_parts.append(
            f'    <g transform="translate({x:.1f}, {y:.1f}) scale({sc:.4f})">\n'
            '      <g transform="translate(152, 224) scale(1.42)">\n'
            f"{_svg_mascot_group('sh', dark=False, include_shadow=False)}"
            "      </g>\n"
            f'      <text x="846" y="612" fill="{INK}" '
            'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" '
            'font-size="188" font-weight="800" letter-spacing="10">CASPER</text>\n'
            f'      <rect x="854" y="646" width="180" height="14" rx="7" fill="{CYAN}"/>\n'
            f'      <text x="854" y="732" fill="{SLATE_SUB}" '
            'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" '
            'font-size="56" font-weight="700" letter-spacing="2">friendly ghostwriter</text>\n'
            "    </g>\n"
        )
        cut_parts.append(
            f'    <g id="cut-wordmark-{widx}" transform="translate({x:.1f}, {y:.1f}) scale({sc:.4f})">\n'
            f'      <path d="{cut_wordmark}" fill="none" stroke="{CUTLINE_MAGENTA}" stroke-width="5" '
            'stroke-dasharray="18 12" stroke-linejoin="round"/>\n'
            "    </g>\n"
        )

    body = (
        '  <g id="vinyl-borders">\n'
        + "".join(vinyl_parts)
        + "  </g>\n"
        + '  <g id="artwork">\n'
        + "".join(art_parts)
        + "  </g>\n"
        + '  <g id="cutline">\n'
        + "".join(cut_parts)
        + "  </g>\n"
    )
    return _svg_wrap(
        2550,
        3300,
        body,
        defs=_svg_mascot_defs("sh", dark=False),
        title="Casper Die-Cut Kiss-Cut Sticker Sheet (2550x3300)",
    )


def build_wallpaper_svg(width: int, height: int, dark: bool) -> str:
    prefix = f"wp{'d' if dark else 'l'}{width}x{height}"
    bg_top = DARK_BG_TOP if dark else LIGHT_BG_TOP
    bg_bot = DARK_BG_BOT if dark else LIGHT_BG_BOT
    grid_color = CYAN if dark else CYAN_DEEP
    grid_op = "0.09" if dark else "0.08"
    aura_color = CYAN if dark else CYAN_MID
    aura_op = "0.24" if dark else "0.14"
    ring_color = CYAN if dark else CYAN_DEEP
    ring_op = "0.18" if dark else "0.14"
    word_color = GHOST_LIGHT if dark else INK
    sub_color = SLATE_MUTED if dark else SLATE_SUB

    # Mascot never stretches: scales strictly to the shorter canvas edge
    short_edge = min(width, height)
    is_portrait = height > width
    mascot_px = short_edge * (0.52 if is_portrait else 0.44)
    sc = mascot_px / 512.0
    mx = (width - mascot_px) / 2.0
    my = height * (0.49 if is_portrait else 0.45) - mascot_px / 2.0
    cx = width / 2.0
    cy = height * (0.50 if is_portrait else 0.46)

    defs = (
        f'    <linearGradient id="{prefix}-bg" x1="0%" y1="0%" x2="100%" y2="100%">\n'
        f'      <stop offset="0%" stop-color="{bg_top}"/>\n'
        f'      <stop offset="100%" stop-color="{bg_bot}"/>\n'
        f'    </linearGradient>\n'
        f'    <radialGradient id="{prefix}-aura" cx="50%" cy="46%" r="36%">\n'
        f'      <stop offset="0%" stop-color="{aura_color}" stop-opacity="{aura_op}"/>\n'
        f'      <stop offset="60%" stop-color="{aura_color}" stop-opacity="0.04"/>\n'
        f'      <stop offset="100%" stop-color="{aura_color}" stop-opacity="0"/>\n'
        f'    </radialGradient>\n'
        f'    <pattern id="{prefix}-grid" width="64" height="64" patternUnits="userSpaceOnUse">\n'
        f'      <path d="M 64 0 L 0 0 0 64" fill="none" stroke="{grid_color}" stroke-width="1" opacity="{grid_op}"/>\n'
        f'    </pattern>\n'
        + _svg_mascot_defs(prefix, dark=dark)
    )

    # Subtle balanced constellation nodes in inner band (keeps desktop icon margins clean)
    constellation_rel = [
        (0.28, 0.24, 3.2, GOLD),
        (0.33, 0.34, 2.4, CYAN),
        (0.25, 0.66, 2.8, BLUSH),
        (0.32, 0.72, 2.2, CYAN),
        (0.72, 0.26, 3.2, GOLD),
        (0.67, 0.35, 2.4, CYAN),
        (0.75, 0.64, 2.8, BLUSH),
        (0.68, 0.73, 2.4, GOLD),
    ]
    c_nodes = "".join(
        f'  <circle cx="{width * rx:.1f}" cy="{height * ry:.1f}" r="{r}" fill="{col}" opacity="0.72"/>\n'
        for rx, ry, r, col in constellation_rel
    )
    c_lines = (
        f'  <line x1="{width * 0.28:.1f}" y1="{height * 0.24:.1f}" x2="{width * 0.33:.1f}" y2="{height * 0.34:.1f}" '
        f'stroke="{ring_color}" stroke-width="1.2" opacity="{ring_op}"/>\n'
        f'  <line x1="{width * 0.72:.1f}" y1="{height * 0.26:.1f}" x2="{width * 0.67:.1f}" y2="{height * 0.35:.1f}" '
        f'stroke="{ring_color}" stroke-width="1.2" opacity="{ring_op}"/>\n'
    )

    ring_r1 = short_edge * (0.31 if is_portrait else 0.26)
    ring_r2 = short_edge * (0.41 if is_portrait else 0.34)
    title_y = height * (0.72 if is_portrait else 0.76)
    sub_y = height * (0.752 if is_portrait else 0.805)
    title_fs = max(36, int(round(short_edge * 0.044)))
    sub_fs = max(16, int(round(short_edge * 0.017)))

    body = (
        f'  <rect width="{width}" height="{height}" fill="url(#{prefix}-bg)"/>\n'
        f'  <rect width="{width}" height="{height}" fill="url(#{prefix}-grid)"/>\n'
        f'  <rect width="{width}" height="{height}" fill="url(#{prefix}-aura)"/>\n'
        f'  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{ring_r1:.1f}" fill="none" '
        f'stroke="{ring_color}" stroke-width="1.5" stroke-dasharray="8 12" opacity="{ring_op}"/>\n'
        f'  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{ring_r2:.1f}" fill="none" '
        f'stroke="{ring_color}" stroke-width="1" opacity="{ring_op}"/>\n'
        f"{c_lines}"
        f"{c_nodes}"
        f'  <g transform="translate({mx:.1f}, {my:.1f}) scale({sc:.4f})">\n'
        f"{_svg_mascot_group(prefix, dark=dark, include_shadow=True)}"
        "  </g>\n"
        f'  <text x="{cx:.1f}" y="{title_y:.1f}" text-anchor="middle" fill="{word_color}" '
        'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" '
        f'font-size="{title_fs}" font-weight="800" letter-spacing="10">CASPER</text>\n'
        f'  <text x="{cx:.1f}" y="{sub_y:.1f}" text-anchor="middle" fill="{sub_color}" '
        'font-family="\'Segoe UI\', \'Helvetica Neue\', Arial, sans-serif" '
        f'font-size="{sub_fs}" font-weight="600" letter-spacing="3">FRIENDLY GHOSTWRITER</text>\n'
    )
    return _svg_wrap(
        width,
        height,
        body,
        defs=defs,
        title=f"Casper Wallpaper {'Dark' if dark else 'Light'} {width}x{height}",
    )


# ---------------------------------------------------------------------------
# Fast Deterministic Pillow Rasterizer (Supersampled Anti-Aliased Geometry)
# ---------------------------------------------------------------------------


def _save_png_deterministic(img: Image.Image, path: Path) -> None:
    """Save RGBA PNG with zero timestamps / tEXt chunks for 100% byte-determinism."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba = img if img.mode == "RGBA" else img.convert("RGBA")
    rgba.save(path, format="PNG", pnginfo=None, compress_level=6, optimize=False)


def _linear_gradient_bg(
    width: int, height: int, top_hex: str, bot_hex: str
) -> Image.Image:
    """Fast C-accelerated diagonal/vertical gradient background (RGBA)."""
    c1 = _hex_rgba(top_hex)
    c2 = _hex_rgba(bot_hex)
    # Build tiny 256x256 diagonal ramp and resize smoothly in C (<15ms even for 3480x1440)
    ramp = Image.new("RGBA", (128, 128))
    px = ramp.load()
    assert px is not None
    for y in range(128):
        for x in range(128):
            t = (x + y) / 254.0
            px[x, y] = _lerp_color(c1, c2, t)
    return ramp.resize((width, height), Image.Resampling.BILINEAR)


def _radial_glow_layer(
    width: int,
    height: int,
    cx_frac: float,
    cy_frac: float,
    radius_frac: float,
    color_hex: str,
    max_alpha: int,
) -> Image.Image:
    """Fast C-accelerated radial glow overlay."""
    rgb = _hex_rgba(color_hex)[:3]
    sw, sh = 160, max(64, int(round(160 * height / width)))
    glow = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    px = glow.load()
    assert px is not None
    cx, cy = sw * cx_frac, sh * cy_frac
    rad = max(sw, sh) * radius_frac
    for y in range(sh):
        dy = y - cy
        for x in range(sw):
            dx = x - cx
            d = math.hypot(dx, dy) / rad
            if d < 1.0:
                a = int(round(max_alpha * ((1.0 - d) ** 2.2)))
                if a > 0:
                    px[x, y] = (rgb[0], rgb[1], rgb[2], a)
    return glow.resize((width, height), Image.Resampling.BILINEAR)


def _draw_thick_polyline(
    draw: ImageDraw.ImageDraw,
    pts: list[tuple[float, float]],
    fill: tuple[int, int, int, int],
    width: float,
    closed: bool = False,
) -> None:
    """Anti-aliased rounded-join, rounded-cap polyline."""
    r = width / 2.0
    seq = pts + [pts[0]] if closed else pts
    w_int = max(1, int(round(width)))
    draw.line(seq, fill=fill, width=w_int, joint="curve")
    for x, y in seq:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def _draw_rotated_ellipse(
    canvas: Image.Image,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    angle_deg: float,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    outline_width: float = 0.0,
) -> None:
    """Draw a smooth rotated ellipse as a 48-point polygon onto canvas."""
    draw = ImageDraw.Draw(canvas)
    rad = math.radians(angle_deg)
    ca, sa = math.cos(rad), math.sin(rad)
    pts: list[tuple[float, float]] = []
    for i in range(48):
        th = 2.0 * math.pi * i / 48.0
        lx, ly = rx * math.cos(th), ry * math.sin(th)
        pts.append((cx + lx * ca - ly * sa, cy + lx * sa + ly * ca))
    draw.polygon(pts, fill=fill)
    if outline is not None and outline_width > 0:
        _draw_thick_polyline(draw, pts, fill=outline, width=outline_width, closed=True)


def _render_mascot_master(
    size: int = 1536, dark: bool = False, include_shadow: bool = True
) -> Image.Image:
    """Render the super-cute Casper ghostwriter at high resolution (RGBA, transparent bg)."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sc = size / 512.0
    draw = ImageDraw.Draw(canvas)

    def to_px(pt: tuple[float, float], tilt: bool = True) -> tuple[float, float]:
        p = _rotate_pt(pt, -3.0) if tilt else pt
        return (p[0] * sc, p[1] * sc)

    def poly_px(pts: list[tuple[float, float]], tilt: bool = True) -> list[tuple[float, float]]:
        return [to_px(p, tilt=tilt) for p in pts]

    # Floating aura shadow underneath
    if include_shadow:
        sh_col = _hex_rgba(CYAN, 62) if dark else _hex_rgba(INK, 30)
        sx, sy = 256.0 * sc, 454.0 * sc
        rx, ry = 84.0 * sc, 13.0 * sc
        sh_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(sh_layer).ellipse((sx - rx, sy - ry, sx + rx, sy + ry), fill=sh_col)
        sh_layer = sh_layer.filter(ImageFilter.GaussianBlur(radius=6.0 * sc))
        canvas = Image.alpha_composite(canvas, sh_layer)
        draw = ImageDraw.Draw(canvas)

    body_poly = poly_px(_ghost_body_polygon(steps=28))

    # Dark-mode luminous cyan outer rim glow
    if dark:
        glow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow_layer)
        _draw_thick_polyline(gdraw, body_poly, fill=_hex_rgba(CYAN, 175), width=26.0 * sc, closed=True)
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=11.0 * sc))
        canvas = Image.alpha_composite(canvas, glow_layer)
        draw = ImageDraw.Draw(canvas)
        _draw_thick_polyline(draw, body_poly, fill=_hex_rgba(CYAN, 230), width=18.5 * sc, closed=True)

    # Cloud-white radial sheen body fill masked to exact ghost silhouette
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(body_poly, fill=255)

    # Radial gradient sheet (128x128 -> size x size)
    sheen_small = Image.new("RGBA", (128, 128))
    spx = sheen_small.load()
    assert spx is not None
    c_hi = _hex_rgba("#FFFFFF")
    c_mid = _hex_rgba(GHOST_LIGHT)
    c_lo = _hex_rgba(GHOST_SHEEN)
    c_rim = _hex_rgba(GHOST_SHADOW)
    for y in range(128):
        for x in range(128):
            d = min(1.0, math.hypot((x - 50) / 76.0, (y - 38) / 84.0))
            if d < 0.45:
                spx[x, y] = _lerp_color(c_hi, c_mid, d / 0.45)
            elif d < 0.82:
                spx[x, y] = _lerp_color(c_mid, c_lo, (d - 0.45) / 0.37)
            else:
                spx[x, y] = _lerp_color(c_lo, c_rim, (d - 0.82) / 0.18)
    sheen_full = sheen_small.resize((size, size), Image.Resampling.BILINEAR)
    body_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    body_layer.paste(sheen_full, (0, 0), mask)
    canvas = Image.alpha_composite(canvas, body_layer)
    draw = ImageDraw.Draw(canvas)

    # Glossy top-left dome highlight crescent (opaque white so dark canvases never bleed through)
    cresc_poly = poly_px(_highlight_crescent_polygon(steps=20))
    draw.polygon(cresc_poly, fill=(255, 255, 255, 255))

    # Crisp dark-navy silhouette outline
    _draw_thick_polyline(draw, body_poly, fill=_hex_rgba(INK), width=13.0 * sc, closed=True)

    # Cute tucked left stub arm
    left_arm = poly_px(_cubic_bezier((122.0, 262.0), (98.0, 270.0), (98.0, 308.0), (128.0, 308.0), steps=18))
    draw.polygon(left_arm + [to_px((128.0, 262.0))], fill=_hex_rgba(GHOST_LIGHT))
    _draw_thick_polyline(draw, left_arm, fill=_hex_rgba(INK), width=11.0 * sc, closed=False)

    # Soft pastel rosy blush cheeks (pre-blended opaque pastel pink over ghost white)
    blush_opaque = _lerp_color(_hex_rgba(GHOST_LIGHT), _hex_rgba(BLUSH), 0.78)
    for bx, by in ((170.0, 256.0), (338.0, 256.0)):
        px_b, py_b = to_px((bx, by))
        _draw_rotated_ellipse(canvas, px_b, py_b, 22.0 * sc, 12.5 * sc, -3.0, blush_opaque)

    # Large expressive dark-navy eyes with dual white sparkle highlights
    for ex, ey in ((204.0, 222.0), (302.0, 222.0)):
        px_e, py_e = to_px((ex, ey))
        _draw_rotated_ellipse(canvas, px_e, py_e, 22.0 * sc, 27.0 * sc, -3.0, _hex_rgba(INK))
        hx1, hy1 = to_px((ex - 9.0, ey - 12.0))
        r1 = 8.5 * sc
        ImageDraw.Draw(canvas).ellipse((hx1 - r1, hy1 - r1, hx1 + r1, hy1 + r1), fill=(255, 255, 255, 255))
        hx2, hy2 = to_px((ex + 8.0, ey + 9.0))
        r2 = 3.8 * sc
        ImageDraw.Draw(canvas).ellipse((hx2 - r2, hy2 - r2, hx2 + r2, hy2 + r2), fill=(255, 255, 255, 255))

    # Warm curved smile
    draw = ImageDraw.Draw(canvas)
    _draw_thick_polyline(draw, poly_px(_smile_points(steps=24)), fill=_hex_rgba(INK), width=10.0 * sc)

    # Glowing sky-cyan fountain pen + golden nib
    pen = _pen_geometry()
    nib_pts = poly_px(pen["nib"])
    draw.polygon(nib_pts, fill=_hex_rgba(GOLD))
    _draw_thick_polyline(draw, nib_pts, fill=_hex_rgba(INK), width=8.0 * sc, closed=True)
    slit_pts = poly_px(pen["nib_slit"])
    _draw_thick_polyline(draw, slit_pts, fill=_hex_rgba(INK), width=4.0 * sc)
    hx, hy = to_px(pen["nib_hole"][0])
    hr = 3.6 * sc
    draw.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=_hex_rgba(INK))

    draw.polygon(poly_px(pen["barrel_upper"]), fill=_hex_rgba(CYAN))
    draw.polygon(poly_px(pen["barrel_lower"]), fill=_hex_rgba(CYAN_DEEP))
    draw.polygon(poly_px(pen["barrel_shine"]), fill=_hex_rgba(GHOST_SHEEN))
    _draw_thick_polyline(draw, poly_px(pen["barrel_full"]), fill=_hex_rgba(INK), width=9.0 * sc, closed=True)

    collar_pts = poly_px(pen["collar"])
    draw.polygon(collar_pts, fill=_hex_rgba(GOLD))
    _draw_thick_polyline(draw, collar_pts, fill=_hex_rgba(INK), width=7.0 * sc, closed=True)

    # Cute tucked right ghost hand gripping the pen
    rx_h, ry_h = to_px((366.0, 284.0))
    _draw_rotated_ellipse(
        canvas,
        rx_h,
        ry_h,
        26.0 * sc,
        20.0 * sc,
        -17.0,
        _hex_rgba(GHOST_LIGHT),
        outline=_hex_rgba(INK),
        outline_width=11.0 * sc,
    )

    # Floating sparkle stars & glowing ink-drop accents
    draw = ImageDraw.Draw(canvas)
    for cx_s, cy_s, rad_s, col_s, sw_s in (
        (426.0, 128.0, 24.0, GOLD, 4.5),
        (456.0, 184.0, 15.0, CYAN, 3.5),
        (94.0, 146.0, 14.0, GOLD, 3.5),
    ):
        s_pts = poly_px(_star4_points(cx_s, cy_s, rad_s))
        draw.polygon(s_pts, fill=_hex_rgba(col_s))
        _draw_thick_polyline(draw, s_pts, fill=_hex_rgba(INK), width=sw_s * sc, closed=True)

    for dx, dy, dr, dcol, dstroke in (
        (299.0, 340.0, 6.0, CYAN, 3.0),
        (283.0, 350.0, 4.0, GOLD, 0.0),
    ):
        px_d, py_d = to_px((dx, dy))
        r_d = dr * sc
        if dstroke > 0:
            ro = r_d + dstroke * sc * 0.6
            draw.ellipse((px_d - ro, py_d - ro, px_d + ro, py_d + ro), fill=_hex_rgba(INK))
        draw.ellipse((px_d - r_d, py_d - r_d, px_d + r_d, py_d + r_d), fill=_hex_rgba(dcol))

    return canvas


def _render_favicon_master(size: int = 256) -> Image.Image:
    """High-contrast simplified cute-ghost favicon matching favicon.svg (crisp down to 16x16)."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sc = size / 64.0
    draw = ImageDraw.Draw(canvas)

    # Rounded dark obsidian tile with luminous cyan border
    draw.rounded_rectangle(
        (2 * sc, 2 * sc, 62 * sc, 62 * sc),
        radius=15 * sc,
        fill=_hex_rgba(DARK_BG_TOP),
        outline=_hex_rgba(CYAN),
        width=max(2, int(round(2.8 * sc))),
    )

    # Bold simplified ghost dome + 3-wave bottom
    segs = (
        ((32.0, 11.0), (20.0, 11.0), (13.0, 19.0), (13.0, 31.0)),
        ((13.0, 31.0), (13.0, 39.0), (13.0, 44.0), (13.0, 47.0)),
        ((13.0, 47.0), (13.0, 53.0), (20.0, 54.0), (24.0, 49.0)),
        ((24.0, 49.0), (27.0, 54.0), (37.0, 54.0), (40.0, 49.0)),
        ((40.0, 49.0), (44.0, 54.0), (51.0, 53.0), (51.0, 47.0)),
        ((51.0, 47.0), (51.0, 44.0), (51.0, 39.0), (51.0, 31.0)),
        ((51.0, 31.0), (51.0, 19.0), (44.0, 11.0), (32.0, 11.0)),
    )
    pts: list[tuple[float, float]] = []
    for p0, p1, p2, p3 in segs:
        pts.extend([(x * sc, y * sc) for x, y in _cubic_bezier(p0, p1, p2, p3, steps=16)[:-1]])
    draw.polygon(pts, fill=_hex_rgba(GHOST_LIGHT))
    _draw_thick_polyline(draw, pts, fill=_hex_rgba(INK), width=2.8 * sc, closed=True)

    # Blush cheeks
    for bx in (20.0, 44.0):
        draw.ellipse(
            ((bx - 3.4) * sc, 32.9 * sc, (bx + 3.4) * sc, 37.1 * sc),
            fill=_hex_rgba(BLUSH),
        )
    # Eyes + sparkles
    for ex in (25.0, 39.0):
        draw.ellipse(
            ((ex - 3.4) * sc, 25.3 * sc, (ex + 3.4) * sc, 33.7 * sc),
            fill=_hex_rgba(INK),
        )
        draw.ellipse(
            ((ex - 2.6) * sc, 26.4 * sc, (ex + 0.2) * sc, 29.2 * sc),
            fill=(255, 255, 255, 255),
        )
    # Smile
    smile = [(x * sc, y * sc) for x, y in _cubic_bezier((28.5, 35.5), (30.0, 39.0), (34.0, 39.0), (35.5, 35.5), 14)]
    _draw_thick_polyline(draw, smile, fill=_hex_rgba(INK), width=2.4 * sc)
    # Pen stroke + gold sparkle
    _draw_thick_polyline(draw, [(46.0 * sc, 18.0 * sc), (54.0 * sc, 10.0 * sc)], fill=_hex_rgba(CYAN), width=3.4 * sc)
    draw.ellipse((50.4 * sc, 18.4 * sc, 55.6 * sc, 23.6 * sc), fill=_hex_rgba(GOLD))
    return canvas


def _render_app_icon(mascot_dark: Image.Image, size: int) -> Image.Image:
    """Rounded obsidian twilight app tile with centered luminous Casper mascot (no text)."""
    bg = _linear_gradient_bg(size, size, DARK_BG_TOP, DARK_BG_BOT)
    glow = _radial_glow_layer(size, size, 0.5, 0.48, 0.45, CYAN, 76)
    bg = Image.alpha_composite(bg, glow)

    # Rounded square mask (iOS/macOS/PWA style)
    mask = Image.new("L", (size, size), 0)
    rad = int(round(size * 0.22))
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=rad, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(bg, (0, 0), mask)

    # Subtle luminous inner border
    rim = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bw = max(2, int(round(size * 0.018)))
    inset = bw // 2 + 1
    ImageDraw.Draw(rim).rounded_rectangle(
        (inset, inset, size - 1 - inset, size - 1 - inset),
        radius=max(4, rad - inset),
        outline=_hex_rgba(CYAN, 140),
        width=bw,
    )
    out = Image.alpha_composite(out, rim)

    # Centered mascot
    msz = int(round(size * 0.82))
    m_resized = mascot_dark.resize((msz, msz), Image.Resampling.LANCZOS)
    off = (size - msz) // 2
    out.alpha_composite(m_resized, (off, off))
    return out


# ---------------------------------------------------------------------------
# Crisp Portable Geometric Vector Wordmark "CASPER" (for PNGs)
# ---------------------------------------------------------------------------


def _draw_casper_wordmark(
    canvas: Image.Image,
    x: float,
    y: float,
    height: float,
    color_hex: str,
    tracking_ratio: float = 0.26,
) -> float:
    """Draw bold rounded geometric 'CASPER' wordmark in Pillow (100% font-independent & portable)."""
    draw = ImageDraw.Draw(canvas)
    col = _hex_rgba(color_hex)
    sw = height * 0.19
    lw = height * 0.66
    step = lw + height * tracking_ratio

    def arc_pts(
        cx: float, cy: float, rx: float, ry: float, deg0: float, deg1: float, n: int = 24
    ) -> list[tuple[float, float]]:
        return [
            (
                cx + rx * math.cos(math.radians(_lerp(deg0, deg1, i / n))),
                cy + ry * math.sin(math.radians(_lerp(deg0, deg1, i / n))),
            )
            for i in range(n + 1)
        ]

    # C
    cx0 = x + lw * 0.54
    cy0 = y + height * 0.50
    _draw_thick_polyline(draw, arc_pts(cx0, cy0, lw * 0.48, height * 0.42, 42, 318, 28), col, sw)

    # A
    ax = x + step
    a_pts = [(ax + lw * 0.06, y + height * 0.90), (ax + lw * 0.50, y + height * 0.10), (ax + lw * 0.94, y + height * 0.90)]
    _draw_thick_polyline(draw, a_pts, col, sw)
    _draw_thick_polyline(
        draw,
        [(ax + lw * 0.24, y + height * 0.63), (ax + lw * 0.76, y + height * 0.63)],
        col,
        sw * 0.92,
    )

    # S
    sx = x + step * 2
    s_top = arc_pts(sx + lw * 0.50, y + height * 0.30, lw * 0.42, height * 0.21, -24, -260, 20)
    s_bot = arc_pts(sx + lw * 0.50, y + height * 0.70, lw * 0.44, height * 0.22, -90, 155, 20)
    _draw_thick_polyline(draw, s_top + s_bot, col, sw)

    # P
    px = x + step * 3
    _draw_thick_polyline(draw, [(px + lw * 0.14, y + height * 0.90), (px + lw * 0.14, y + height * 0.10)], col, sw)
    p_bowl = (
        [(px + lw * 0.14, y + height * 0.10), (px + lw * 0.54, y + height * 0.10)]
        + arc_pts(px + lw * 0.54, y + height * 0.32, lw * 0.36, height * 0.22, -90, 90, 18)
        + [(px + lw * 0.14, y + height * 0.54)]
    )
    _draw_thick_polyline(draw, p_bowl, col, sw)

    # E
    ex = x + step * 4
    _draw_thick_polyline(
        draw,
        [
            (ex + lw * 0.86, y + height * 0.10),
            (ex + lw * 0.14, y + height * 0.10),
            (ex + lw * 0.14, y + height * 0.90),
            (ex + lw * 0.88, y + height * 0.90),
        ],
        col,
        sw,
    )
    _draw_thick_polyline(
        draw,
        [(ex + lw * 0.14, y + height * 0.49), (ex + lw * 0.76, y + height * 0.49)],
        col,
        sw * 0.94,
    )

    # R
    rx = x + step * 5
    _draw_thick_polyline(draw, [(rx + lw * 0.14, y + height * 0.90), (rx + lw * 0.14, y + height * 0.10)], col, sw)
    r_bowl = (
        [(rx + lw * 0.14, y + height * 0.10), (rx + lw * 0.54, y + height * 0.10)]
        + arc_pts(rx + lw * 0.54, y + height * 0.31, lw * 0.36, height * 0.21, -90, 90, 18)
        + [(rx + lw * 0.14, y + height * 0.52)]
    )
    _draw_thick_polyline(draw, r_bowl, col, sw)
    _draw_thick_polyline(draw, [(rx + lw * 0.52, y + height * 0.54), (rx + lw * 0.90, y + height * 0.90)], col, sw)

    return step * 5 + lw


def _load_portable_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------------------
# Die-Cut Sticker PNG Renderer (Smooth Contoured White Vinyl Border + Alpha=0)
# ---------------------------------------------------------------------------


def _apply_vinyl_diecut_border(
    artwork: Image.Image,
    pad_px: int,
    rim_px: int = 3,
) -> Image.Image:
    """Create a smooth contoured white vinyl border around RGBA artwork with transparent outside."""
    w, h = artwork.size
    alpha = artwork.getchannel("A")

    # Fast smooth circular Euclidean dilation at 1/2 resolution -> smooth upsample -> threshold
    ds = 2 if max(w, h) >= 1000 else 1
    sw, sh = w // ds, h // ds
    a_small = alpha.resize((sw, sh), Image.Resampling.BILINEAR) if ds > 1 else alpha

    # Multi-pass Gaussian dilation gives a clean circular offset contour (~pad_px radius)
    r = max(2.0, (pad_px / ds) * 0.58)
    dilated = a_small.point(lambda p: 255 if p > 24 else 0)
    for _ in range(3):
        dilated = dilated.filter(ImageFilter.GaussianBlur(radius=r))
        dilated = dilated.point(lambda p: 255 if p > 46 else 0)

    # Anti-aliased smooth outer edge (strictly 0 outside contour!)
    soft = dilated.filter(ImageFilter.GaussianBlur(radius=1.4))
    outer_mask = soft.point(lambda p: 0 if p < 24 else (255 if p > 215 else int((p - 24) * 255 / 191)))
    if ds > 1:
        outer_mask = outer_mask.resize((w, h), Image.Resampling.BICUBIC)
        outer_mask = outer_mask.point(lambda p: 0 if p < 16 else (255 if p > 235 else p))

    # Inner white mask slightly eroded by rim_px for subtle kiss-cut outer edge definition
    rim_blur = max(1.0, rim_px * 0.75)
    inner_white_mask = outer_mask.filter(ImageFilter.MinFilter(size=max(3, (rim_px * 2) | 1)))
    inner_white_mask = inner_white_mask.filter(ImageFilter.GaussianBlur(radius=rim_blur * 0.5))

    # Composite: subtle cool-gray outer rim (#CBD5E1) + crisp white vinyl (#FFFFFF) + artwork
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rim_layer = Image.new("RGBA", (w, h), _hex_rgba("#CBD5E1", 255))
    rim_layer.putalpha(outer_mask)
    out = Image.alpha_composite(out, rim_layer)

    white_layer = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    white_layer.putalpha(ImageChops.darker(outer_mask, inner_white_mask))
    out = Image.alpha_composite(out, white_layer)
    out = Image.alpha_composite(out, artwork)
    return out


def _render_sticker_diecut_png(mascot_light_no_shadow: Image.Image) -> Image.Image:
    size = 1500
    art = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    msz = 1140
    m = mascot_light_no_shadow.resize((msz, msz), Image.Resampling.LANCZOS)
    off = (size - msz) // 2
    art.alpha_composite(m, (off, off))
    return _apply_vinyl_diecut_border(art, pad_px=64, rim_px=3)


def _render_sticker_wordmark_png(mascot_light_no_shadow: Image.Image) -> Image.Image:
    w, h = 1800, 1200
    art = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    msz = 700
    m = mascot_light_no_shadow.resize((msz, msz), Image.Resampling.LANCZOS)
    art.alpha_composite(m, (132, 246))

    # Crisp geometric CASPER wordmark + cyan bar + subtitle (generous transparent margins on all 4 sides)
    _draw_casper_wordmark(art, x=812, y=456, height=144, color_hex=INK, tracking_ratio=0.18)
    draw = ImageDraw.Draw(art)
    draw.rounded_rectangle((816, 626, 996, 640), radius=7, fill=_hex_rgba(CYAN))
    sub_font = _load_portable_font(50)
    draw.text((816, 662), "friendly ghostwriter", fill=_hex_rgba(SLATE_SUB), font=sub_font)
    return _apply_vinyl_diecut_border(art, pad_px=64, rim_px=3)


def _render_sticker_sheet_png(
    sticker_mascot: Image.Image, sticker_wordmark: Image.Image
) -> Image.Image:
    """Composite print-ready 2550x3300 RGBA sticker sheet (transparent corners & margins)."""
    sheet = Image.new("RGBA", (2550, 3300), (0, 0, 0, 0))
    large = sticker_mascot.resize((900, 900), Image.Resampling.LANCZOS)
    medium = sticker_mascot.resize((620, 620), Image.Resampling.LANCZOS)
    word = sticker_wordmark.resize((1020, 680), Image.Resampling.LANCZOS)
    mini = sticker_mascot.resize((380, 380), Image.Resampling.LANCZOS)

    for x, y in ((265, 190), (1385, 190)):
        sheet.alpha_composite(large, (x, y))
    for x, y in ((220, 1210), (965, 1210), (1710, 1210)):
        sheet.alpha_composite(medium, (x, y))
    for x, y in ((215, 1950), (1315, 1950)):
        sheet.alpha_composite(word, (x, y))
    for i in range(5):
        sheet.alpha_composite(mini, (205 + i * 440, 2750))
    return sheet


# ---------------------------------------------------------------------------
# Hero Banner & Wallpaper PNG Renderers
# ---------------------------------------------------------------------------


def _render_hero_png(mascot_dark: Image.Image) -> Image.Image:
    w, h = 1200, 360
    bg = _linear_gradient_bg(w, h, DARK_BG_TOP, DARK_BG_BOT)

    # Subtle obsidian light-blue grid
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grid)
    gcol = _hex_rgba(CYAN, 26)
    for gx in range(0, w, 40):
        gdraw.line([(gx, 0), (gx, h)], fill=gcol, width=1)
    for gy in range(0, h, 40):
        gdraw.line([(0, gy), (w, gy)], fill=gcol, width=1)
    bg = Image.alpha_composite(bg, grid)

    # Spectral cyan aura behind mascot
    aura = _radial_glow_layer(w, h, 0.22, 0.52, 0.34, CYAN, 76)
    bg = Image.alpha_composite(bg, aura)

    # Starfield accents
    draw = ImageDraw.Draw(bg)
    for sx, sy, sr, scol, sa in (
        (88, 56, 3, GOLD, 210),
        (146, 302, 2, CYAN, 180),
        (430, 52, 3, CYAN, 190),
        (1096, 62, 3, GOLD, 220),
        (1134, 118, 2, CYAN, 180),
        (1042, 294, 3, BLUSH, 190),
        (960, 48, 2, GHOST_LIGHT, 155),
    ):
        draw.ellipse((sx - sr, sy - sr, sx + sr, sy + sr), fill=_hex_rgba(scol, sa))

    # Cute mascot on left
    msz = 290
    m = mascot_dark.resize((msz, msz), Image.Resampling.LANCZOS)
    bg.alpha_composite(m, (92, 35))

    # Crisp geometric CASPER wordmark + cyan bar + subtitle + pills
    _draw_casper_wordmark(bg, x=436, y=88, height=78, color_hex=GHOST_LIGHT, tracking_ratio=0.28)
    draw = ImageDraw.Draw(bg)
    draw.rounded_rectangle((436, 186, 564, 192), radius=3, fill=_hex_rgba(CYAN))
    sub_font = _load_portable_font(26)
    draw.text(
        (436, 206),
        "the friendly ghostwriter  -  local-first, deterministic",
        fill=_hex_rgba(GHOST_SHEEN),
        font=sub_font,
    )
    pill_font = _load_portable_font(16)
    for px, pw, label, pcol in (
        (436, 162, "deterministic", CYAN),
        (612, 170, "zero-invention", GOLD),
        (796, 144, "local-first", BLUSH),
    ):
        draw.rounded_rectangle(
            (px, 258, px + pw, 292),
            radius=17,
            fill=_hex_rgba(DARK_GRID),
            outline=_hex_rgba(pcol),
            width=2,
        )
        bbox = pill_font.getbbox(label)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            (px + (pw - tw) / 2, 258 + (34 - th) / 2 - 2),
            label,
            fill=_hex_rgba(pcol),
            font=pill_font,
        )

    # Rounded corner clip matching hero SVG
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=20, fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(bg, (0, 0), mask)
    return out


def _render_wallpaper_png(
    width: int, height: int, dark: bool, mascot_img: Image.Image
) -> Image.Image:
    bg_top = DARK_BG_TOP if dark else LIGHT_BG_TOP
    bg_bot = DARK_BG_BOT if dark else LIGHT_BG_BOT
    bg = _linear_gradient_bg(width, height, bg_top, bg_bot)

    # Subtle blueprint / notebook grid
    grid = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grid)
    gcol = _hex_rgba(CYAN, 22) if dark else _hex_rgba(CYAN_DEEP, 20)
    for gx in range(0, width, 64):
        gdraw.line([(gx, 0), (gx, height)], fill=gcol, width=1)
    for gy in range(0, height, 64):
        gdraw.line([(0, gy), (width, gy)], fill=gcol, width=1)
    bg = Image.alpha_composite(bg, grid)

    # Centered spectral radial aura
    aura = _radial_glow_layer(
        width,
        height,
        0.5,
        0.46,
        0.34,
        CYAN if dark else CYAN_MID,
        64 if dark else 38,
    )
    bg = Image.alpha_composite(bg, aura)

    # Subtle geometric rings + balanced inner constellation accents
    short_edge = min(width, height)
    is_portrait = height > width
    deco = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ddraw = ImageDraw.Draw(deco)
    cx, cy = width / 2.0, height * (0.50 if is_portrait else 0.46)
    ring_col = _hex_rgba(CYAN, 44) if dark else _hex_rgba(CYAN_DEEP, 34)
    for r_frac in ((0.31, 0.41) if is_portrait else (0.26, 0.34)):
        rr = short_edge * r_frac
        ddraw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=ring_col, width=2)

    ddraw.line(
        [(width * 0.28, height * 0.24), (width * 0.33, height * 0.34)],
        fill=ring_col,
        width=2,
    )
    ddraw.line(
        [(width * 0.72, height * 0.26), (width * 0.67, height * 0.35)],
        fill=ring_col,
        width=2,
    )
    for rx, ry, r_dot, col in (
        (0.28, 0.24, 4, GOLD),
        (0.33, 0.34, 3, CYAN),
        (0.25, 0.66, 3, BLUSH),
        (0.32, 0.72, 3, CYAN),
        (0.72, 0.26, 4, GOLD),
        (0.67, 0.35, 3, CYAN),
        (0.75, 0.64, 3, BLUSH),
        (0.68, 0.73, 3, GOLD),
    ):
        px_c, py_c = width * rx, height * ry
        ddraw.ellipse(
            (px_c - r_dot, py_c - r_dot, px_c + r_dot, py_c + r_dot),
            fill=_hex_rgba(col, 185),
        )
    bg = Image.alpha_composite(bg, deco)

    # Unstretched cute mascot centered cleanly
    mascot_px = int(round(short_edge * (0.52 if is_portrait else 0.44)))
    m_resized = mascot_img.resize((mascot_px, mascot_px), Image.Resampling.LANCZOS)
    mx = (width - mascot_px) // 2
    my = int(round(height * (0.49 if is_portrait else 0.45))) - mascot_px // 2
    bg.alpha_composite(m_resized, (mx, my))

    # Minimal geometric CASPER caption underneath
    wm_h = max(32.0, short_edge * 0.042)
    wm_w = wm_h * (0.66 * 6 + 0.28 * 5)
    _draw_casper_wordmark(
        bg,
        x=(width - wm_w) / 2.0,
        y=height * (0.70 if is_portrait else 0.73),
        height=wm_h,
        color_hex=GHOST_LIGHT if dark else INK,
        tracking_ratio=0.28,
    )
    sub_font = _load_portable_font(max(16, int(round(short_edge * 0.017))))
    sub_text = "FRIENDLY GHOSTWRITER"
    bbox = sub_font.getbbox(sub_text)
    tw = bbox[2] - bbox[0]
    ImageDraw.Draw(bg).text(
        ((width - tw) / 2.0, height * (0.742 if is_portrait else 0.792)),
        sub_text,
        fill=_hex_rgba(SLATE_MUTED if dark else SLATE_SUB),
        font=sub_font,
    )
    return bg


# ---------------------------------------------------------------------------
# Full Kit Generation & Verification
# ---------------------------------------------------------------------------


def generate_all(brand_dir: Path, static_img_dir: Path | None = None) -> list[Path]:
    """Generate every brand deliverable into brand_dir and optionally sync web subset."""
    icons_dir = brand_dir / "icons"
    stickers_dir = brand_dir / "stickers"
    wallpapers_dir = brand_dir / "wallpapers"
    for d in (brand_dir, icons_dir, stickers_dir, wallpapers_dir):
        d.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    def write_text(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(path)

    def write_png(path: Path, img: Image.Image) -> None:
        _save_png_deterministic(img, path)
        written.append(path)

    # Render supersampled masters once (major speedup + uniform crisp anti-aliasing)
    mascot_light = _render_mascot_master(size=1536, dark=False, include_shadow=True)
    mascot_light_no_shadow = _render_mascot_master(size=1536, dark=False, include_shadow=False)
    mascot_dark = _render_mascot_master(size=1536, dark=True, include_shadow=True)
    favicon_master = _render_favicon_master(size=256)

    # §2.1 Logos & Hero Banners (7 files)
    write_text(brand_dir / "casper-mark.svg", build_mark_svg())
    write_png(brand_dir / "casper-mark-512.png", mascot_light.resize((512, 512), Image.Resampling.LANCZOS))
    write_png(brand_dir / "casper-mark-1024.png", mascot_light.resize((1024, 1024), Image.Resampling.LANCZOS))
    write_text(brand_dir / "casper-logo-light.svg", build_logo_svg(dark=False))
    write_text(brand_dir / "casper-logo-dark.svg", build_logo_svg(dark=True))
    write_text(brand_dir / "casper-hero.svg", build_hero_svg())
    write_png(brand_dir / "casper-hero.png", _render_hero_png(mascot_dark))

    # §2.2 Icons, Favicons & Subsystem Badges (14 files)
    write_text(brand_dir / "favicon.svg", build_favicon_svg())
    fav16 = favicon_master.resize((16, 16), Image.Resampling.LANCZOS)
    fav32 = favicon_master.resize((32, 32), Image.Resampling.LANCZOS)
    fav48 = favicon_master.resize((48, 48), Image.Resampling.LANCZOS)
    write_png(brand_dir / "favicon-16x16.png", fav16)
    write_png(brand_dir / "favicon-32x32.png", fav32)

    ico_path = brand_dir / "favicon.ico"
    fav48.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=[fav32, fav16],
    )
    written.append(ico_path)

    app_icon_1024 = _render_app_icon(mascot_dark, 1024)
    write_png(brand_dir / "apple-touch-icon.png", app_icon_1024.resize((180, 180), Image.Resampling.LANCZOS))
    write_png(brand_dir / "icon-192x192.png", app_icon_1024.resize((192, 192), Image.Resampling.LANCZOS))
    write_png(brand_dir / "icon-512x512.png", app_icon_1024.resize((512, 512), Image.Resampling.LANCZOS))
    write_png(brand_dir / "icon-1024x1024.png", app_icon_1024)

    for icon_name in SUBSYSTEM_ICONS:
        write_text(icons_dir / icon_name, build_subsystem_icon_svg(icon_name))

    # §2.3 Die-Cut Stickers with Border Cutouts (7 files)
    write_text(stickers_dir / "casper-sticker-diecut.svg", build_sticker_diecut_svg())
    sticker_1500 = _render_sticker_diecut_png(mascot_light_no_shadow)
    write_png(stickers_dir / "casper-sticker-diecut.png", sticker_1500)
    write_png(
        stickers_dir / "casper-sticker-diecut-1024.png",
        sticker_1500.resize((1024, 1024), Image.Resampling.LANCZOS),
    )

    write_text(stickers_dir / "casper-sticker-wordmark-diecut.svg", build_sticker_wordmark_diecut_svg())
    sticker_wordmark = _render_sticker_wordmark_png(mascot_light_no_shadow)
    write_png(stickers_dir / "casper-sticker-wordmark-diecut.png", sticker_wordmark)

    write_text(stickers_dir / "casper-sticker-sheet.svg", build_sticker_sheet_svg())
    write_png(
        stickers_dir / "casper-sticker-sheet.png",
        _render_sticker_sheet_png(sticker_1500, sticker_wordmark),
    )

    # §2.4 Wallpapers: 5 resolutions × 2 themes × 2 formats (20 files)
    for w, h in WALLPAPER_RESOLUTIONS:
        for dark in (True, False):
            theme = "dark" if dark else "light"
            stem = f"casper-wallpaper-{theme}-{w}x{h}"
            write_text(wallpapers_dir / f"{stem}.svg", build_wallpaper_svg(w, h, dark=dark))
            write_png(
                wallpapers_dir / f"{stem}.png",
                _render_wallpaper_png(w, h, dark=dark, mascot_img=mascot_dark if dark else mascot_light),
            )

    # §3 Web Static Sync (10 byte-identical files)
    if static_img_dir is not None:
        static_img_dir.mkdir(parents=True, exist_ok=True)
        for name in WEB_SYNCED_FILES:
            shutil.copyfile(brand_dir / name, static_img_dir / name)

    return written


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_brand(brand_dir: Path = BRAND_DIR, static_img_dir: Path = WEB_STATIC_IMG_DIR) -> list[str]:
    """Regenerate into a temp directory and verify SHA-256 byte-identity of every asset."""
    mismatches: list[str] = []
    with tempfile.TemporaryDirectory(prefix="casper-brand-check-") as tmp:
        tmp_root = Path(tmp)
        tmp_brand = tmp_root / "brand"
        tmp_static = tmp_root / "static_img"
        generated = generate_all(tmp_brand, tmp_static)

        for gen_path in sorted(generated):
            rel = gen_path.relative_to(tmp_brand)
            live = brand_dir / rel
            if not live.is_file():
                mismatches.append(f"MISSING docs/brand/{rel}")
            elif _sha256(live) != _sha256(gen_path):
                mismatches.append(f"DRIFT docs/brand/{rel}")

        for name in WEB_SYNCED_FILES:
            gen_static = tmp_static / name
            live_static = static_img_dir / name
            if not live_static.is_file():
                mismatches.append(f"MISSING src/casper/web/static/img/{name}")
            elif _sha256(live_static) != _sha256(gen_static):
                mismatches.append(f"DRIFT src/casper/web/static/img/{name}")

    return mismatches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or verify Casper Brand Kit assets.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Regenerate into temp dir and verify byte-identical SHA-256 hashes without modifying repo.",
    )
    args = parser.parse_args(argv)

    if args.check:
        mismatches = check_brand(BRAND_DIR, WEB_STATIC_IMG_DIR)
        if mismatches:
            for item in mismatches:
                sys.stderr.write(f"{item}\n")
            sys.stderr.write("Brand assets out of sync. Run: python3 scripts/build_brand.py\n")
            return 1
        return 0

    generate_all(BRAND_DIR, WEB_STATIC_IMG_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
