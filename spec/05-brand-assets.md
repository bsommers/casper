# 05 — Casper Super-Cute Ghost Brand & Visual Asset Kit Contract

This document defines the complete visual identity contract for **Casper, the friendly ghostwriter**. All assets are generated deterministically by `scripts/build_brand.py` into `docs/brand/`, with the web-facing subset byte-synced into `src/casper/web/static/img/` and verified by `tests/smoke/test_brand.py` (`TC-050`) and `tests/smoke/test_hygiene.py` (`TC-004`).

## 1. Mascot Design Specification ("Super-Cute Casper Ghostwriter")

Every asset in the kit shares one unified, charming, mathematically crisp vector mascot — never generic clip-art and never inconsistent styles across sizes:

- **Silhouette & Expression:** Plump, rounded friendly ghost with a soft scalloped 3-wave bottom hem, gentle floating tilt (`-3°`), large expressive dark-navy eyes (`#0F172A`) with dual specular sparkle highlights (`#FFFFFF`), soft pastel rosy blush cheeks (`#FDA4AF`), and a warm curved smile.
- **Ghostwriter Prop:** Tiny tucked hand holding a glowing sky-cyan fountain pen / quill (`#38BDF8` / `#0284C7`) with a golden nib (`#FBBF24`) trailing 2–3 tiny floating sparkle stars and ink-drop accents — immediately communicating *friendly ghostwriter* without relying on unreadable tiny text.
- **Signature Palette:**
  - **Ghost Body:** Soft cloud white (`#F8FAFC` → `#E0F2FE` radial sheen), crisp outline (`#0F172A` on light surfaces; luminous `#38BDF8` glow rim on dark/obsidian surfaces).
  - **Primary Accent (Spectral Cyan):** `#38BDF8` / `#0EA5E9`
  - **Secondary Accent (Blush Pink):** `#FDA4AF`
  - **Nib / Sparkle Gold:** `#FBBF24`
  - **Dark Canvas (Obsidian Twilight):** `#0B0F1A` → `#131B2E` with subtle light-blue grid/starfield accents (`#1E293B` / `#38BDF8` at low opacity).
  - **Light Canvas (Paper Ivory):** `#F8FAFC` → `#EFF6FF` with crisp near-black ink (`#0F172A`).
- **Multi-Scale Legibility Invariants:**
  - All SVGs are 100% self-contained: **zero** external `<image>` URLs and **zero** webfont `@import` directives.
  - Icon viewBox `64x64` uses stroke widths `>= 2.0px` (`>= 12px` in `512x512` viewBox) so facial features, pen nib, and scalloped contour remain unmistakable down to `16x16` and `32x32`.
  - Square icons omit tiny tagline text; wordmarks appear only in wide horizontal lockups, hero banners, and wordmark stickers.

## 2. Deliverable Asset Manifest

All paths below are generated deterministically by `scripts/build_brand.py` (which supports `--check` for zero-drift verification).

### 2.1 Logos & Hero Banners (`docs/brand/`)

| File | Format | Exact Dimensions | Usage & Sync |
|---|---|---|---|
| `docs/brand/casper-mark.svg` | SVG | `512x512` viewBox | Primary square cute ghost mascot (no text); synced to `web/static/img/` |
| `docs/brand/casper-mark-512.png` | PNG (RGBA) | `512x512` | High-res square emblem; transparent background |
| `docs/brand/casper-mark-1024.png` | PNG (RGBA) | `1024x1024` | High-DPI master square emblem; transparent background |
| `docs/brand/casper-logo-light.svg` | SVG | `640x180` viewBox | Horizontal mascot + `CASPER` wordmark for light headers; synced to `web/static/img/` |
| `docs/brand/casper-logo-dark.svg` | SVG | `640x180` viewBox | Horizontal mascot + `CASPER` wordmark for dark footers/headers; synced to `web/static/img/` |
| `docs/brand/casper-hero.svg` | SVG | `1200x360` viewBox | Wide README & docs hero banner (obsidian twilight grid + cute ghost + title + subtitle) |
| `docs/brand/casper-hero.png` | PNG (RGBA) | `1200x360` | Rasterized hero banner for GitHub README & OpenGraph (`og:image`) |

### 2.2 Icons, Favicons & Subsystem Badges (`docs/brand/` & `docs/brand/icons/`)

| File | Format | Exact Dimensions | Notes |
|---|---|---|---|
| `docs/brand/favicon.svg` | SVG | `64x64` viewBox | Simplified crisp cute-ghost face (stroke `>=2px`); synced to `web/static/img/` |
| `docs/brand/favicon.ico` | ICO | `16x16, 32x32, 48x48` | Multi-resolution ICO; synced to `web/static/img/` |
| `docs/brand/favicon-16x16.png` | PNG (RGBA) | `16x16` | Browser tab icon; synced to `web/static/img/` |
| `docs/brand/favicon-32x32.png` | PNG (RGBA) | `32x32` | Standard favicon; synced to `web/static/img/` |
| `docs/brand/apple-touch-icon.png` | PNG (RGBA) | `180x180` | iOS/macOS touch icon with rounded tile background; synced to `web/static/img/` |
| `docs/brand/icon-192x192.png` | PNG (RGBA) | `192x192` | Web manifest / PWA icon; synced to `web/static/img/` |
| `docs/brand/icon-512x512.png` | PNG (RGBA) | `512x512` | App / plugin store icon; synced to `web/static/img/` |
| `docs/brand/icon-1024x1024.png` | PNG (RGBA) | `1024x1024` | High-DPI master app icon |
| `docs/brand/icons/icon-voice.svg` | SVG | `64x64` viewBox | Subsystem badge: Author Voice Fingerprint |
| `docs/brand/icons/icon-facts.svg` | SVG | `64x64` viewBox | Subsystem badge: Fact Extraction & Graph |
| `docs/brand/icons/icon-plan.svg` | SVG | `64x64` viewBox | Subsystem badge: Audience & Structure Planner |
| `docs/brand/icons/icon-validate.svg` | SVG | `64x64` viewBox | Subsystem badge: Fidelity Validator |
| `docs/brand/icons/icon-format.svg` | SVG | `64x64` viewBox | Subsystem badge: Multi-Modality Formatter |
| `docs/brand/icons/icon-cli-writer.svg` | SVG | `64x64` viewBox | Subsystem badge: Claude / Antigravity CLI Writer |

### 2.3 Die-Cut Stickers with Border Cutouts (`docs/brand/stickers/`)

All die-cut stickers feature a uniform, smooth contoured **white vinyl offset border** (`~8%` contour padding around the mascot, quill, sparkles, and optional wordmark) plus an explicit vector cutline group (`<g id="cutline">` in SVG, crisp magenta/dashed print-guide optional layer or clean kiss-cut stroke) and **strictly transparent background outside the border cutout** (`alpha == 0` on all 4 corners and outer margins of every PNG).

| File | Format | Exact Dimensions | Specification |
|---|---|---|---|
| `docs/brand/stickers/casper-sticker-diecut.svg` | SVG | `1500x1500` viewBox | Cute ghost + fountain pen die-cut sticker with white vinyl offset contour and `<g id="cutline">` vector path (Cricut/Silhouette/Sticker Mule ready) |
| `docs/brand/stickers/casper-sticker-diecut.png` | PNG (RGBA) | `1500x1500` (300 DPI @ 5×5 in) | Transparent-background print-ready die-cut sticker with crisp white border cutout and subtle outer edge definition |
| `docs/brand/stickers/casper-sticker-diecut-1024.png` | PNG (RGBA) | `1024x1024` | Digital chat/Slack/Discord sticker with white die-cut border cutout |
| `docs/brand/stickers/casper-sticker-wordmark-diecut.svg` | SVG | `1800x1200` viewBox | Cute ghost + `"CASPER"` + `"friendly ghostwriter"` contoured die-cut sticker with `<g id="cutline">` |
| `docs/brand/stickers/casper-sticker-wordmark-diecut.png` | PNG (RGBA) | `1800x1200` (300 DPI @ 6×4 in) | Print-ready transparent-background wordmark die-cut sticker |
| `docs/brand/stickers/casper-sticker-sheet.svg` | SVG | `2550x3300` viewBox (8.5×11 in @ 300 DPI) | Print-ready multi-sticker kiss-cut sheet (mascot stickers in 3 sizes + wordmark stickers + mini ghost icons) with `<g id="cutline">` |
| `docs/brand/stickers/casper-sticker-sheet.png` | PNG (RGBA) | `2550x3300` | Rasterized transparent-background sticker sheet |

### 2.4 Screen Backgrounds / Wallpapers (`docs/brand/wallpapers/`)

Generated in standard desktop and ultrawide resolutions **up to and including `3480x1440`**, in both **Dark Twilight Obsidian (`dark`)** and **Clean Paper Sky (`light`)** themes. Composition scales cleanly to each aspect ratio (16:9 and ~21:9/ultrawide) without stretching the mascot — placing the super-cute ghostwriter mascot with subtle glowing constellation/notebook-grid geometry and balanced desktop-icon negative space on the left/right margins.

| Resolution | Aspect Class | Dark Variant | Light Variant |
|---|---|---|---|
| **`1920x1080`** | FHD 16:9 | `casper-wallpaper-dark-1920x1080.{svg,png}` | `casper-wallpaper-light-1920x1080.{svg,png}` |
| **`2560x1080`** | Ultrawide 21:9 | `casper-wallpaper-dark-2560x1080.{svg,png}` | `casper-wallpaper-light-2560x1080.{svg,png}` |
| **`2560x1440`** | QHD 16:9 | `casper-wallpaper-dark-2560x1440.{svg,png}` | `casper-wallpaper-light-2560x1440.{svg,png}` |
| **`3440x1440`** | UWQHD 21:9 | `casper-wallpaper-dark-3440x1440.{svg,png}` | `casper-wallpaper-light-3440x1440.{svg,png}` |
| **`3480x1440`** | Super-Wide (exact requested max) | `casper-wallpaper-dark-3480x1440.{svg,png}` | `casper-wallpaper-light-3480x1440.{svg,png}` |

## 3. Generator Contract (`scripts/build_brand.py`)

```text
Usage: python3 scripts/build_brand.py [--check]
```

- **Pure deterministic generation:** Uses pure Python SVG generation + local rasterization (e.g., `cairosvg` / `rsvg-convert` / `resvg` / `Pillow` fallback renderer with zero network calls) to produce identical bytes across runs (no embedded timestamps in PNG `tEXt` chunks or SVG metadata).
- **Web static sync:** Copies `casper-mark.svg`, `casper-logo-light.svg`, `casper-logo-dark.svg`, `favicon.svg`, `favicon.ico`, `favicon-16x16.png`, `favicon-32x32.png`, `apple-touch-icon.png`, `icon-192x192.png`, `icon-512x512.png` into `src/casper/web/static/img/` byte-for-byte.
- **`--check` mode:** Regenerates into a temporary directory and compares SHA-256 hashes of every asset in `docs/brand/` and `src/casper/web/static/img/`, exiting `0` only if every file matches byte-for-byte.
- **Automated verification (`TC-050`):**
  1. Verifies every required file in §§2.1–2.4 exists and passes `build_brand.py --check`.
  2. Parses every SVG via XML parser: confirms valid XML, zero external `<image href="http...">` or `@import`, and `<g id="cutline">` present in all die-cut sticker SVGs.
  3. Opens every PNG/ICO via `Pillow`: confirms exact `(width, height)` pixel dimensions (including exact `3480x1440` wallpapers and `1500x1500`/`1800x1200`/`2550x3300` stickers) and confirms die-cut sticker PNGs are `RGBA` with transparent corner pixels (`alpha == 0`) outside the white vinyl border cutout.
  4. Confirms byte-identity between `docs/brand/` and `src/casper/web/static/img/`.
