#!/usr/bin/env python3
"""Deterministically pre-render docs/**/*.md into standalone HTML under docs/rendered/."""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
RENDERED_DIR = DOCS_DIR / "rendered"

ESCAPABLE_PUNCT = frozenset(r"""!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~""")
ATX_HEADING_RE = re.compile(r"^[ ]{0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*?[ \t]*$")
SETEXT_UNDERLINE_RE = re.compile(r"^[ ]{0,3}(=+|-+)[ \t]*$")
FENCE_OPEN_RE = re.compile(r"^([ ]{0,3})(`{3,}|~{3,})([^\n]*)$")
HR_RE = re.compile(r"^[ ]{0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
BLOCKQUOTE_RE = re.compile(r"^[ ]{0,3}> ?(.*)$")
ALERT_RE = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*$", re.IGNORECASE)
UL_ITEM_RE = re.compile(r"^([ ]*)([-*+])([ \t]+|$)(.*)$")
OL_ITEM_RE = re.compile(r"^([ ]*)(\d{1,9})([.)])([ \t]+|$)(.*)$")
TASK_PREFIX_RE = re.compile(r"^\[([ xX])\][ \t]+(.*)$", re.DOTALL)
TABLE_DELIM_CELL_RE = re.compile(r"^[ \t]*(:?)-+(:?)[ \t]*$")
AUTOLINK_URL_RE = re.compile(r"<(https?://[^\s<>]+)>")
AUTOLINK_EMAIL_RE = re.compile(
    r"<([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)>"
)
AUTOLINK_MAILTO_RE = re.compile(r"<(mailto:[^\s<>]+)>")
SLUG_STRIP_RE = re.compile(r"[^a-z0-9\s-]")
SLUG_DASH_RE = re.compile(r"[-\s]+")

ALERT_LABELS: dict[str, str] = {
    "note": "Note",
    "tip": "Tip",
    "important": "Important",
    "warning": "Warning",
    "caution": "Caution",
}


@dataclass(frozen=True)
class Heading:
    """Extracted document heading metadata."""

    level: int
    text: str
    slug: str


LinkRewriter = Callable[[str], str]


def _is_safe_url(url: str) -> bool:
    stripped = url.strip().lower()
    if not stripped:
        return False
    if stripped.startswith(("#", "/", "./", "../")):
        return True
    if stripped.startswith(("http://", "https://", "mailto:")):
        return True
    # Relative path without scheme
    scheme_sep = stripped.find(":")
    slash_sep = stripped.find("/")
    if scheme_sep != -1 and (slash_sep == -1 or scheme_sep < slash_sep):
        return False
    return True


def _strip_inline_markup(text: str) -> str:
    """Extract plain text from inline Markdown for heading slugs and image alt text."""
    # Remove code span backticks while preserving inner text
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in ESCAPABLE_PUNCT:
            out.append(text[i + 1])
            i += 2
            continue
        if ch == "`":
            end_run = i
            while end_run < n and text[end_run] == "`":
                end_run += 1
            ticks = end_run - i
            close = _find_closing_backticks(text, end_run, ticks)
            if close != -1:
                inner = text[end_run:close].replace("\n", " ")
                if len(inner) >= 2 and inner[0] == " " and inner[-1] == " " and inner.strip():
                    inner = inner[1:-1]
                out.append(inner)
                i = close + ticks
                continue
            out.append(text[i:end_run])
            i = end_run
            continue
        if ch == "!" and i + 1 < n and text[i + 1] == "[":
            parsed = _parse_bracket_link(text, i + 1)
            if parsed is not None:
                label, _url, _title, end_pos = parsed
                out.append(_strip_inline_markup(label))
                i = end_pos
                continue
        if ch == "[":
            parsed = _parse_bracket_link(text, i)
            if parsed is not None:
                label, _url, _title, end_pos = parsed
                out.append(_strip_inline_markup(label))
                i = end_pos
                continue
        if ch in ("*", "_", "~"):
            # Skip emphasis markers that aren't intraword underscores
            if ch == "_" and i > 0 and i + 1 < n and text[i - 1].isalnum() and text[i + 1].isalnum():
                out.append(ch)
                i += 1
                continue
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out).strip()


def slugify(text: str, seen: dict[str, int]) -> str:
    """Create a unique GitHub-style heading slug."""
    base = SLUG_STRIP_RE.sub("", text.lower())
    base = SLUG_DASH_RE.sub("-", base).strip("-") or "section"
    count = seen.get(base, 0)
    seen[base] = count + 1
    return base if count == 0 else f"{base}-{count + 1}"


def _find_closing_backticks(text: str, start: int, count: int) -> int:
    """Find the index of an exact `count`-length run of backticks starting from `start`."""
    i = start
    n = len(text)
    while i < n:
        if text[i] == "`":
            j = i
            while j < n and text[j] == "`":
                j += 1
            if j - i == count:
                return i
            i = j
        else:
            i += 1
    return -1


def _parse_bracket_link(text: str, start: int) -> tuple[str, str, str | None, int] | None:
    """Parse `[label](url "title")` starting at `[`."""
    n = len(text)
    if start >= n or text[start] != "[":
        return None
    depth = 0
    i = start
    label_end = -1
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in ESCAPABLE_PUNCT:
            i += 2
            continue
        if ch == "`":
            j = i
            while j < n and text[j] == "`":
                j += 1
            close = _find_closing_backticks(text, j, j - i)
            i = close + (j - i) if close != -1 else j
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                label_end = i
                break
        i += 1
    if label_end == -1 or label_end + 1 >= n or text[label_end + 1] != "(":
        return None

    label = text[start + 1 : label_end]
    pos = label_end + 2
    while pos < n and text[pos] in " \t\n":
        pos += 1
    if pos >= n:
        return None

    # Parse URL (either <...> or bare with balanced parens)
    if text[pos] == "<":
        end_angle = text.find(">", pos + 1)
        if end_angle == -1:
            return None
        url = text[pos + 1 : end_angle]
        pos = end_angle + 1
    else:
        url_start = pos
        paren_depth = 0
        while pos < n:
            ch = text[pos]
            if ch == "\\" and pos + 1 < n and text[pos + 1] in ESCAPABLE_PUNCT:
                pos += 2
                continue
            if ch in " \t\n":
                break
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                if paren_depth == 0:
                    break
                paren_depth -= 1
            pos += 1
        url = text[url_start:pos]

    # Unescape backslash-escaped punctuation in URL
    url = re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])", r"\1", url)

    while pos < n and text[pos] in " \t\n":
        pos += 1

    title: str | None = None
    if pos < n and text[pos] in ('"', "'"):
        quote = text[pos]
        pos += 1
        t_chars: list[str] = []
        while pos < n and text[pos] != quote:
            if text[pos] == "\\" and pos + 1 < n and text[pos + 1] in ESCAPABLE_PUNCT:
                t_chars.append(text[pos + 1])
                pos += 2
                continue
            t_chars.append(text[pos])
            pos += 1
        if pos >= n or text[pos] != quote:
            return None
        title = "".join(t_chars)
        pos += 1
        while pos < n and text[pos] in " \t\n":
            pos += 1

    if pos >= n or text[pos] != ")":
        return None
    return label, url, title, pos + 1


def _find_closing_delim(text: str, start: int, delim: str, intraword_guard: bool = False) -> int:
    """Find closing emphasis/strike delimiter skipping code spans and escapes."""
    n = len(text)
    dlen = len(delim)
    i = start
    while i <= n - dlen:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in ESCAPABLE_PUNCT:
            i += 2
            continue
        if ch == "`":
            j = i
            while j < n and text[j] == "`":
                j += 1
            close = _find_closing_backticks(text, j, j - i)
            i = close + (j - i) if close != -1 else j
            continue
        if text.startswith(delim, i):
            prev_ch = text[i - 1] if i > 0 else " "
            next_ch = text[i + dlen] if i + dlen < n else " "
            # Closer cannot immediately follow whitespace
            if not prev_ch.isspace():
                # Avoid matching longer run than expected when looking for single * or _
                if dlen == 1 and next_ch == delim:
                    # Skip nested ** inside *...*
                    i += 2
                    continue
                if intraword_guard and next_ch.isalnum():
                    i += 1
                    continue
                return i
        i += 1
    return -1


def render_inline(text: str, link_rewriter: LinkRewriter | None = None) -> str:
    """Render inline CommonMark + GFM syntax into safe HTML."""
    out: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # Backslash escape or backslash hard break
        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "\n":
                out.append("<br>\n")
                i += 2
                continue
            if nxt in ESCAPABLE_PUNCT:
                out.append(html.escape(nxt, quote=False))
                i += 2
                continue

        # Hard line break: 2+ spaces before newline
        if ch == " " and i + 2 < n:
            j = i
            while j < n and text[j] == " ":
                j += 1
            if j < n and text[j] == "\n" and (j - i) >= 2:
                out.append("<br>\n")
                i = j + 1
                continue

        # Inline code span (single or multi-backtick)
        if ch == "`":
            j = i
            while j < n and text[j] == "`":
                j += 1
            ticks = j - i
            close = _find_closing_backticks(text, j, ticks)
            if close != -1:
                inner = text[j:close].replace("\n", " ")
                if len(inner) >= 2 and inner[0] == " " and inner[-1] == " " and inner.strip():
                    inner = inner[1:-1]
                out.append(f"<code>{html.escape(inner, quote=False)}</code>")
                i = close + ticks
                continue
            out.append("`" * ticks)
            i = j
            continue

        # Image: ![alt](src "title")
        if ch == "!" and i + 1 < n and text[i + 1] == "[":
            parsed = _parse_bracket_link(text, i + 1)
            if parsed is not None:
                alt_raw, url, title, end_pos = parsed
                rewritten = link_rewriter(url) if link_rewriter else url
                if _is_safe_url(rewritten):
                    alt_text = html.escape(_strip_inline_markup(alt_raw), quote=True)
                    src_attr = html.escape(rewritten, quote=True)
                    title_attr = f' title="{html.escape(title, quote=True)}"' if title else ""
                    out.append(f'<img src="{src_attr}" alt="{alt_text}"{title_attr} loading="lazy">')
                    i = end_pos
                    continue

        # Link: [label](url "title")
        if ch == "[":
            parsed = _parse_bracket_link(text, i)
            if parsed is not None:
                label_raw, url, title, end_pos = parsed
                rewritten = link_rewriter(url) if link_rewriter else url
                if _is_safe_url(rewritten):
                    label_html = render_inline(label_raw, link_rewriter=None)
                    href_attr = html.escape(rewritten, quote=True)
                    title_attr = f' title="{html.escape(title, quote=True)}"' if title else ""
                    ext_attr = (
                        ' target="_blank" rel="noopener"'
                        if rewritten.startswith(("http://", "https://"))
                        else ""
                    )
                    out.append(f'<a href="{href_attr}"{title_attr}{ext_attr}>{label_html}</a>')
                    i = end_pos
                    continue

        # Autolinks: <https://...>, <mailto:...>, <user@host.tld>
        if ch == "<":
            m_url = AUTOLINK_URL_RE.match(text, i)
            if m_url:
                url = m_url.group(1)
                escaped = html.escape(url, quote=True)
                out.append(f'<a href="{escaped}" target="_blank" rel="noopener">{html.escape(url, quote=False)}</a>')
                i = m_url.end()
                continue
            m_mailto = AUTOLINK_MAILTO_RE.match(text, i)
            if m_mailto:
                full = m_mailto.group(1)
                shown = full[len("mailto:") :]
                out.append(
                    f'<a href="{html.escape(full, quote=True)}">{html.escape(shown, quote=False)}</a>'
                )
                i = m_mailto.end()
                continue
            m_email = AUTOLINK_EMAIL_RE.match(text, i)
            if m_email:
                addr = m_email.group(1)
                out.append(
                    f'<a href="mailto:{html.escape(addr, quote=True)}">{html.escape(addr, quote=False)}</a>'
                )
                i = m_email.end()
                continue

        # Strikethrough: ~~text~~
        if ch == "~" and text.startswith("~~", i) and i + 2 < n and not text[i + 2].isspace():
            close = _find_closing_delim(text, i + 2, "~~")
            if close != -1 and close > i + 2:
                inner_html = render_inline(text[i + 2 : close], link_rewriter=link_rewriter)
                out.append(f"<del>{inner_html}</del>")
                i = close + 2
                continue

        # Bold+Italic, Bold, Italic (* or _)
        if ch in ("*", "_"):
            prev_alnum = i > 0 and text[i - 1].isalnum()
            intraword = ch == "_"
            if not (intraword and prev_alnum):
                matched = False
                for run_len, open_tag, close_tag in (
                    (3, "<strong><em>", "</em></strong>"),
                    (2, "<strong>", "</strong>"),
                    (1, "<em>", "</em>"),
                ):
                    delim = ch * run_len
                    if text.startswith(delim, i) and i + run_len < n and not text[i + run_len].isspace():
                        # Avoid splitting a longer delimiter run inconsistently
                        if run_len < 3 and text.startswith(ch * (run_len + 1), i):
                            continue
                        close = _find_closing_delim(text, i + run_len, delim, intraword_guard=intraword)
                        if close != -1 and close > i + run_len:
                            inner_html = render_inline(
                                text[i + run_len : close], link_rewriter=link_rewriter
                            )
                            out.append(f"{open_tag}{inner_html}{close_tag}")
                            i = close + run_len
                            matched = True
                            break
                if matched:
                    continue

        out.append(html.escape(ch, quote=False))
        i += 1

    return "".join(out)


def _split_table_row(line: str) -> list[str]:
    """Split a GFM table row respecting backslash-escaped pipes and inline code spans."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    # Strip trailing unescaped pipe
    if s.endswith("|"):
        bs_count = 0
        k = len(s) - 2
        while k >= 0 and s[k] == "\\":
            bs_count += 1
            k -= 1
        if bs_count % 2 == 0:
            s = s[:-1]

    cells: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n and s[i + 1] == "|":
            # GFM: \| inside table cells represents a literal pipe character
            buf.append("|")
            i += 2
            continue
        if ch == "`":
            j = i
            while j < n and s[j] == "`":
                j += 1
            ticks = j - i
            close = _find_closing_backticks(s, j, ticks)
            if close != -1:
                # Inside code spans in GFM tables, \| still becomes |
                segment = s[i : close + ticks].replace(r"\|", "|")
                buf.append(segment)
                i = close + ticks
                continue
            buf.append(s[i:j])
            i = j
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def _parse_table_delimiter(line: str) -> list[str] | None:
    """Parse a GFM table alignment delimiter row, returning column alignments or None."""
    if "|" not in line and "-" not in line:
        return None
    if not line.strip():
        return None
    cells = _split_table_row(line)
    if not cells:
        return None
    aligns: list[str] = []
    for cell in cells:
        m = TABLE_DELIM_CELL_RE.match(cell)
        if not m:
            return None
        left_colon, right_colon = bool(m.group(1)), bool(m.group(2))
        if left_colon and right_colon:
            aligns.append("center")
        elif right_colon:
            aligns.append("right")
        elif left_colon:
            aligns.append("left")
        else:
            aligns.append("")
    return aligns


def _is_table_start(lines: list[str], idx: int) -> list[str] | None:
    """Return column alignments if `lines[idx:idx+2]` begins a valid GFM table."""
    if idx + 1 >= len(lines):
        return None
    header_line = lines[idx]
    delim_line = lines[idx + 1]
    if "|" not in header_line:
        return None
    aligns = _parse_table_delimiter(delim_line)
    if aligns is None:
        return None
    header_cells = _split_table_row(header_line)
    if len(header_cells) != len(aligns):
        return None
    return aligns


def _strip_indent(line: str, amount: int) -> str:
    """Strip up to `amount` leading spaces (treating a tab as 4 spaces)."""
    removed = 0
    idx = 0
    while idx < len(line) and removed < amount:
        if line[idx] == " ":
            removed += 1
            idx += 1
        elif line[idx] == "\t":
            removed += 4
            idx += 1
        else:
            break
    return line[idx:]


def _leading_spaces(line: str) -> int:
    count = 0
    for ch in line:
        if ch == " ":
            count += 1
        elif ch == "\t":
            count += 4
        else:
            break
    return count


def _is_block_start(lines: list[str], idx: int) -> bool:
    """Check whether `lines[idx]` starts a new block that interrupts a paragraph."""
    line = lines[idx]
    if not line.strip():
        return True
    if FENCE_OPEN_RE.match(line):
        return True
    if ATX_HEADING_RE.match(line):
        return True
    if HR_RE.match(line):
        return True
    if BLOCKQUOTE_RE.match(line):
        return True
    if UL_ITEM_RE.match(line) or OL_ITEM_RE.match(line):
        return True
    if _is_table_start(lines, idx) is not None:
        return True
    return False


def _render_blocks(
    lines: list[str],
    headings: list[Heading],
    slug_seen: dict[str, int],
    link_rewriter: LinkRewriter | None,
) -> str:
    """Render a sequence of Markdown lines into block-level HTML."""
    out: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # Blank line
        if not line.strip():
            i += 1
            continue

        # 1. Fenced code block (``` or ~~~)
        m_fence = FENCE_OPEN_RE.match(line)
        if m_fence:
            indent_len = len(m_fence.group(1))
            fence_seq = m_fence.group(2)
            fence_char = fence_seq[0]
            fence_len = len(fence_seq)
            info = m_fence.group(3).strip()
            # CommonMark: backtick fence info string cannot contain backticks
            if not (fence_char == "`" and "`" in info):
                lang_raw = info.split()[0] if info else ""
                lang_clean = re.sub(r"[^A-Za-z0-9_+#.-]", "", lang_raw).lower()
                code_lines: list[str] = []
                i += 1
                close_re = re.compile(rf"^[ ]{{0,3}}{re.escape(fence_char)}{{{fence_len},}}[ \t]*$")
                while i < n:
                    if close_re.match(lines[i]):
                        i += 1
                        break
                    code_lines.append(_strip_indent(lines[i], indent_len))
                    i += 1
                escaped_code = html.escape("\n".join(code_lines), quote=False)
                badge = html.escape(lang_clean or "text", quote=False)
                cls_attr = f' class="language-{html.escape(lang_clean, quote=True)}"' if lang_clean else ""
                out.append(
                    '<div class="code-block">'
                    f'<div class="code-block-head"><span class="code-lang">{badge}</span></div>'
                    f"<pre><code{cls_attr}>{escaped_code}</code></pre>"
                    "</div>"
                )
                continue

        # 2. ATX Heading (# .. ######)
        m_atx = ATX_HEADING_RE.match(line)
        if m_atx:
            level = len(m_atx.group(1))
            raw_content = (m_atx.group(2) or "").strip()
            # Strip trailing closing hashes preceded by whitespace
            raw_content = re.sub(r"[ \t]+#+[ \t]*$", "", raw_content).strip()
            plain = _strip_inline_markup(raw_content)
            slug = slugify(plain, slug_seen)
            headings.append(Heading(level=level, text=plain, slug=slug))
            inner = render_inline(raw_content, link_rewriter=link_rewriter)
            out.append(f'<h{level} id="{slug}">{inner}</h{level}>')
            i += 1
            continue

        # 3. Horizontal rule (---, ***, ___)
        if HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue

        # 4. Blockquote & GitHub Alerts (> [!NOTE], etc.)
        m_bq = BLOCKQUOTE_RE.match(line)
        if m_bq:
            bq_lines: list[str] = []
            while i < n:
                m_b = BLOCKQUOTE_RE.match(lines[i])
                if m_b:
                    bq_lines.append(m_b.group(1))
                    i += 1
                else:
                    break
            m_alert = ALERT_RE.match(bq_lines[0].strip()) if bq_lines else None
            if m_alert:
                kind = m_alert.group(1).lower()
                label = ALERT_LABELS[kind]
                body_html = _render_blocks(bq_lines[1:], headings, slug_seen, link_rewriter)
                out.append(
                    f'<div class="md-alert md-alert-{kind}" role="note">'
                    f'<div class="md-alert-title">{label}</div>'
                    f'<div class="md-alert-body">{body_html}</div>'
                    "</div>"
                )
            else:
                inner_html = _render_blocks(bq_lines, headings, slug_seen, link_rewriter)
                out.append(f"<blockquote>\n{inner_html}\n</blockquote>")
            continue

        # 5. GFM Table
        aligns = _is_table_start(lines, i)
        if aligns is not None:
            headers = _split_table_row(lines[i])
            i += 2
            rows: list[list[str]] = []
            while i < n and lines[i].strip():
                if (
                    FENCE_OPEN_RE.match(lines[i])
                    or ATX_HEADING_RE.match(lines[i])
                    or HR_RE.match(lines[i])
                    or BLOCKQUOTE_RE.match(lines[i])
                    or "|" not in lines[i]
                ):
                    break
                row_cells = _split_table_row(lines[i])
                if len(row_cells) < len(aligns):
                    row_cells.extend([""] * (len(aligns) - len(row_cells)))
                elif len(row_cells) > len(aligns):
                    row_cells = row_cells[: len(aligns)]
                rows.append(row_cells)
                i += 1
            ths: list[str] = []
            for cell, align in zip(headers, aligns, strict=True):
                style = f' style="text-align:{align}"' if align else ""
                ths.append(f"<th{style}>{render_inline(cell, link_rewriter=link_rewriter)}</th>")
            body_rows: list[str] = []
            for row in rows:
                tds: list[str] = []
                for cell, align in zip(row, aligns, strict=True):
                    style = f' style="text-align:{align}"' if align else ""
                    tds.append(f"<td{style}>{render_inline(cell, link_rewriter=link_rewriter)}</td>")
                body_rows.append(f"<tr>{''.join(tds)}</tr>")
            tbody = f"<tbody>{''.join(body_rows)}</tbody>" if body_rows else ""
            out.append(
                '<div class="table-wrap"><table>'
                f"<thead><tr>{''.join(ths)}</tr></thead>"
                f"{tbody}"
                "</table></div>"
            )
            continue

        # 6. Unordered or Ordered List (nested + task lists + indented code blocks)
        m_ul = UL_ITEM_RE.match(line)
        m_ol = OL_ITEM_RE.match(line) if not m_ul else None
        if m_ul or m_ol:
            is_ordered = m_ol is not None
            base_indent = len(m_ol.group(1)) if m_ol else len(m_ul.group(1))  # type: ignore[union-attr]
            marker_delim = m_ol.group(3) if m_ol else m_ul.group(2)  # type: ignore[union-attr]
            start_num = int(m_ol.group(2)) if m_ol else 1

            items_html: list[str] = []
            loose = False

            while i < n:
                cur = lines[i]
                if not cur.strip():
                    # Look ahead to see if list continues after blank line
                    look = i + 1
                    while look < n and not lines[look].strip():
                        look += 1
                    if look >= n:
                        i = look
                        break
                    nxt_m = OL_ITEM_RE.match(lines[look]) if is_ordered else UL_ITEM_RE.match(lines[look])
                    if nxt_m and len(nxt_m.group(1)) == base_indent:
                        nxt_delim = nxt_m.group(3) if is_ordered else nxt_m.group(2)
                        if nxt_delim == marker_delim:
                            loose = True
                            i = look
                            continue
                    break

                if HR_RE.match(cur) and _leading_spaces(cur) <= base_indent + 3:
                    break

                cur_m = OL_ITEM_RE.match(cur) if is_ordered else UL_ITEM_RE.match(cur)
                if not cur_m or len(cur_m.group(1)) != base_indent:
                    break
                cur_delim = cur_m.group(3) if is_ordered else cur_m.group(2)
                if cur_delim != marker_delim:
                    break

                marker_text = (cur_m.group(2) + cur_m.group(3)) if is_ordered else cur_m.group(2)
                after_space = cur_m.group(4) if is_ordered else cur_m.group(3)
                content_indent = base_indent + len(marker_text) + max(len(after_space), 1)
                first_text = cur_m.group(5) if is_ordered else cur_m.group(4)
                item_lines: list[str] = [first_text]
                i += 1

                # Collect indented continuation lines (including nested lists & fenced code blocks)
                in_item_fence = False
                item_fence_char = ""
                item_fence_len = 0
                while i < n:
                    sub = lines[i]
                    if not sub.strip():
                        if in_item_fence:
                            item_lines.append("")
                            i += 1
                            continue
                        # Check if blank line is followed by an indented continuation of this item
                        look = i + 1
                        while look < n and not lines[look].strip():
                            look += 1
                        if look < n and _leading_spaces(lines[look]) >= content_indent:
                            loose = True
                            item_lines.append("")
                            i += 1
                            continue
                        break

                    sub_indent = _leading_spaces(sub)
                    if sub_indent >= content_indent or (
                        sub_indent > base_indent and (UL_ITEM_RE.match(sub) or OL_ITEM_RE.match(sub))
                    ):
                        stripped = _strip_indent(sub, min(content_indent, sub_indent))
                        if not in_item_fence:
                            mf = FENCE_OPEN_RE.match(stripped)
                            if mf and not (mf.group(2)[0] == "`" and "`" in mf.group(3)):
                                in_item_fence = True
                                item_fence_char = mf.group(2)[0]
                                item_fence_len = len(mf.group(2))
                        else:
                            if re.match(
                                rf"^[ ]{{0,3}}{re.escape(item_fence_char)}{{{item_fence_len},}}[ \t]*$",
                                stripped,
                            ):
                                in_item_fence = False
                        item_lines.append(stripped)
                        i += 1
                        continue

                    if in_item_fence:
                        item_lines.append(_strip_indent(sub, content_indent))
                        i += 1
                        continue

                    # Stop at sibling/outer list item or other block starter
                    if _is_block_start(lines, i):
                        break
                    # Lazy continuation line
                    item_lines.append(sub.strip())
                    i += 1

                # Task list item detection: [x] or [ ]
                task_prefix = ""
                li_cls = ""
                m_task = TASK_PREFIX_RE.match(item_lines[0])
                if m_task:
                    checked = m_task.group(1).lower() == "x"
                    item_lines[0] = m_task.group(2)
                    chk_attr = " checked" if checked else ""
                    task_prefix = f'<input type="checkbox" class="task-checkbox" disabled{chk_attr}> '
                    li_cls = ' class="task-list-item"'

                rendered_item = _render_blocks(item_lines, headings, slug_seen, link_rewriter)
                # Unwrap single tight paragraph for clean list output
                if (
                    not loose
                    and rendered_item.startswith("<p>")
                    and rendered_item.endswith("</p>")
                    and rendered_item.count("<p>") == 1
                ):
                    rendered_item = rendered_item[3:-4]
                    items_html.append(f"<li{li_cls}>{task_prefix}{rendered_item}</li>")
                elif task_prefix and rendered_item.startswith("<p>"):
                    rendered_item = "<p>" + task_prefix + rendered_item[3:]
                    items_html.append(f"<li{li_cls}>{rendered_item}</li>")
                else:
                    items_html.append(f"<li{li_cls}>{task_prefix}{rendered_item}</li>")

            if is_ordered:
                start_attr = f' start="{start_num}"' if start_num != 1 else ""
                out.append(f"<ol{start_attr}>\n" + "\n".join(items_html) + "\n</ol>")
            else:
                out.append("<ul>\n" + "\n".join(items_html) + "\n</ul>")
            continue

        # 7. Paragraph or Setext Heading
        para_lines: list[str] = [line]
        i += 1
        setext_level: int | None = None
        while i < n:
            cur = lines[i]
            if not cur.strip():
                break
            m_setext = SETEXT_UNDERLINE_RE.match(cur)
            if m_setext:
                setext_level = 1 if m_setext.group(1).startswith("=") else 2
                i += 1
                break
            if _is_block_start(lines, i):
                break
            para_lines.append(cur)
            i += 1

        if setext_level is not None:
            raw_heading = " ".join(p.strip() for p in para_lines)
            plain = _strip_inline_markup(raw_heading)
            slug = slugify(plain, slug_seen)
            headings.append(Heading(level=setext_level, text=plain, slug=slug))
            inner = render_inline(raw_heading, link_rewriter=link_rewriter)
            out.append(f'<h{setext_level} id="{slug}">{inner}</h{setext_level}>')
        else:
            joined = "\n".join(p.lstrip() for p in para_lines)
            out.append(f"<p>{render_inline(joined, link_rewriter=link_rewriter)}</p>")

    return "\n".join(out)


def render_markdown(
    md_text: str,
    link_rewriter: LinkRewriter | None = None,
) -> tuple[str, list[Heading], str]:
    """Render full CommonMark + GFM Markdown document to `(body_html, headings, title)`."""
    normalized = md_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    headings: list[Heading] = []
    slug_seen: dict[str, int] = {}
    body_html = _render_blocks(lines, headings, slug_seen, link_rewriter)
    title = headings[0].text if headings else "Casper Documentation"
    return body_html, headings, title


def build_toc_html(headings: list[Heading]) -> str:
    """Build a Table of Contents block when >= 2 headings exist."""
    if len(headings) < 2:
        return ""
    sub_headings = [h for h in headings if h.level >= 2]
    entries = sub_headings if len(sub_headings) >= 2 else headings
    items = [
        f'<li class="toc-l{h.level}"><a href="#{h.slug}">{html.escape(h.text, quote=False)}</a></li>'
        for h in entries
    ]
    return (
        '<nav class="doc-toc" aria-label="Table of contents">\n'
        '  <div class="doc-toc-title">On This Page</div>\n'
        '  <ul class="doc-toc-list">\n'
        "    " + "\n    ".join(items) + "\n"
        "  </ul>\n"
        "</nav>"
    )


def make_link_rewriter(
    src_md: Path,
    rendered_html: Path,
    rendered_map: dict[Path, Path],
    root_dir: Path = ROOT,
) -> LinkRewriter:
    """Create a deterministic relative link rewriter for a pre-rendered doc page."""

    def rewrite(raw_url: str) -> str:
        url = raw_url.strip()
        if not url or url.startswith(("http://", "https://", "mailto:", "#")):
            return url

        # Preserve query and fragment
        frag = ""
        path_part = url
        if "#" in path_part:
            path_part, frag = path_part.split("#", 1)
            frag = f"#{frag}"
        query = ""
        if "?" in path_part:
            path_part, query = path_part.split("?", 1)
            query = f"?{query}"
        if not path_part:
            return url

        # Resolve target relative to source markdown file, with repo-root fallback (e.g. docs/using.md)
        candidate = (src_md.parent / path_part).resolve()
        if not candidate.exists():
            root_candidate = (root_dir / path_part).resolve()
            if root_candidate.exists():
                candidate = root_candidate

        # Rewrite links targeting another pre-rendered doc to its sibling .html page
        if candidate in rendered_map:
            target_html = rendered_map[candidate]
            rel = os.path.relpath(target_html, rendered_html.parent).replace(os.sep, "/")
            return f"{rel}{query}{frag}"

        # Rewrite non-rendered existing repo paths (e.g. ../src/casper/models.py) relative to HTML location
        if candidate.exists():
            rel = os.path.relpath(candidate, rendered_html.parent).replace(os.sep, "/")
            return f"{rel}{query}{frag}"

        return url

    return rewrite


def render_page_html(
    src_md: Path,
    rendered_html: Path,
    rendered_map: dict[Path, Path],
    docs_dir: Path = DOCS_DIR,
    root_dir: Path = ROOT,
) -> str:
    """Render a single Markdown document into a complete standalone HTML page."""
    rel_md = src_md.relative_to(docs_dir).as_posix()
    to_docs = os.path.relpath(docs_dir, rendered_html.parent).replace(os.sep, "/")
    to_rendered = os.path.relpath(docs_dir / "rendered", rendered_html.parent).replace(os.sep, "/")
    nav_prefix = "" if to_rendered == "." else f"{to_rendered}/"

    rewriter = make_link_rewriter(src_md, rendered_html, rendered_map, root_dir=root_dir)
    md_text = src_md.read_text(encoding="utf-8")
    body_html, headings, title = render_markdown(md_text, link_rewriter=rewriter)
    toc_html = build_toc_html(headings)
    toc_block = f"\n      {toc_html}\n" if toc_html else ""

    dl_name = rel_md.replace("/", "-")
    escaped_title = html.escape(title, quote=False)
    escaped_rel = html.escape(rel_md, quote=False)
    escaped_rel_attr = html.escape(rel_md, quote=True)
    escaped_dl = html.escape(dl_name, quote=True)

    return f"""<!-- DO NOT EDIT DIRECTLY. Generated deterministically by scripts/build_docs_html.py -->
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title} — Casper Documentation</title>
  <link rel="icon" type="image/svg+xml" href="{to_docs}/brand/favicon.svg">
  <link rel="icon" href="{to_docs}/brand/favicon.ico" sizes="any">
  <link rel="apple-touch-icon" href="{to_docs}/brand/apple-touch-icon.png">
  <link rel="stylesheet" href="{to_docs}/site.css">
</head>
<body>
  <div class="grid-bg" aria-hidden="true"></div>

  <header class="topbar">
    <a class="brand-link" href="{to_docs}/index.html">
      <img src="{to_docs}/brand/casper-logo-dark.svg" alt="Casper — The Friendly Ghostwriter" class="brand-logo">
    </a>
    <nav class="nav-links" aria-label="Documentation navigation">
      <a href="{to_docs}/index.html#docs">All Docs</a>
      <a href="{nav_prefix}using.html">Using</a>
      <a href="{nav_prefix}data-model.html">Data Model</a>
      <a href="{nav_prefix}api-reference.html">API</a>
      <a href="{nav_prefix}testing.html">Testing</a>
      <a href="{nav_prefix}adr/README.html">ADRs</a>
      <a class="btn-outline" href="https://github.com/bsommers/casper" target="_blank" rel="noopener">GitHub</a>
    </nav>
  </header>

  <main class="container doc-container">
    <div class="hud-card doc-toolbar">
      <div class="doc-toolbar-left">
        <a class="dl-link" href="{to_docs}/index.html#docs">&larr; Back to Hub</a>
        <span class="tag">{escaped_rel}</span>
      </div>
      <div class="doc-toolbar-right">
        <div class="pill-group" role="group" aria-label="Document view mode">
          <span class="pill active" aria-current="page">Pre-Rendered HTML</span>
          <a class="pill" href="{to_docs}/doc.html?file={escaped_rel_attr}">Dynamic JS Viewer</a>
        </div>
        <a class="dl-link" href="{to_docs}/{escaped_rel_attr}" target="_blank" rel="noopener">View Raw .md</a>
        <a class="dl-link" href="{to_docs}/{escaped_rel_attr}" download="{escaped_dl}">Download .md</a>
      </div>
    </div>

    <article class="hud-card markdown-body">{toc_block}
{body_html}
    </article>
  </main>

  <footer class="footer">
    <div class="footer-inner">
      <img src="{to_docs}/brand/casper-mark.svg" alt="Casper Ghost Mark" class="footer-mark">
      <span>Casper Documentation · Pre-Rendered Static HTML · Local-First · MIT License</span>
    </div>
  </footer>
</body>
</html>
"""


def discover_docs(docs_dir: Path = DOCS_DIR, rendered_dir: Path = RENDERED_DIR) -> list[Path]:
    """Return sorted list of all Markdown source documents under `docs/`."""
    rendered_resolved = rendered_dir.resolve()
    docs: list[Path] = []
    for path in sorted(docs_dir.rglob("*.md")):
        if not path.is_file():
            continue
        if rendered_resolved in path.resolve().parents:
            continue
        docs.append(path)
    return docs


def build_all(
    docs_dir: Path = DOCS_DIR,
    rendered_dir: Path = RENDERED_DIR,
    root_dir: Path = ROOT,
    check: bool = False,
) -> tuple[int, list[str]]:
    """Build or verify all pre-rendered documentation HTML files."""
    sources = discover_docs(docs_dir=docs_dir, rendered_dir=rendered_dir)
    rendered_map: dict[Path, Path] = {}
    for src in sources:
        rel = src.relative_to(docs_dir)
        dst = (rendered_dir / rel).with_suffix(".html")
        rendered_map[src.resolve()] = dst.resolve()

    expected_outputs: dict[Path, str] = {}
    for src in sources:
        dst = rendered_map[src.resolve()]
        expected_outputs[dst] = render_page_html(
            src_md=src,
            rendered_html=dst,
            rendered_map=rendered_map,
            docs_dir=docs_dir,
            root_dir=root_dir,
        )

    existing_html: set[Path] = (
        {p.resolve() for p in rendered_dir.rglob("*.html") if p.is_file()}
        if rendered_dir.exists()
        else set()
    )
    stale = sorted(existing_html - set(expected_outputs.keys()))

    if check:
        drifts: list[str] = []
        for dst, expected in sorted(expected_outputs.items()):
            rel_dst = dst.relative_to(root_dir).as_posix() if dst.is_relative_to(root_dir) else str(dst)
            if not dst.is_file():
                drifts.append(f"MISSING: {rel_dst}")
            elif dst.read_text(encoding="utf-8") != expected:
                drifts.append(f"DRIFT: {rel_dst}")
        for extra in stale:
            rel_extra = (
                extra.relative_to(root_dir).as_posix() if extra.is_relative_to(root_dir) else str(extra)
            )
            drifts.append(f"STALE: {rel_extra}")
        return (1 if drifts else 0), drifts

    for extra in stale:
        extra.unlink()

    written: list[str] = []
    for dst, content in sorted(expected_outputs.items()):
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")
        rel_dst = dst.relative_to(root_dir).as_posix() if dst.is_relative_to(root_dir) else str(dst)
        written.append(rel_dst)
    return 0, written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-render docs/**/*.md into standalone HTML under docs/rendered/."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify docs/rendered/**/*.html is byte-identical to generated output without writing.",
    )
    args = parser.parse_args(argv)

    rc, items = build_all(check=args.check)
    if args.check:
        if rc != 0:
            for item in items:
                sys.stderr.write(f"{item}\n")
            sys.stderr.write("Run: .venv/bin/python scripts/build_docs_html.py\n")
        return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
