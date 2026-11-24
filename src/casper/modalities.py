"""Modality-specific draft formatting and rendered word/char counting (Rank 4)."""

from __future__ import annotations

import html
import re

from casper.models import Draft, DraftSection, MarkupKind, Modality

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _format_title(title: str, markup: MarkupKind) -> str:
    if markup == MarkupKind.HTML:
        return f"<h1>{html.escape(title)}</h1>"
    if markup == MarkupKind.MARKDOWN:
        return f"# {title}"
    if markup == MarkupKind.SLACK:
        return f"*{title}*"
    return title


def _format_heading(heading: str, modality: Modality) -> str | None:
    if not heading or modality.headings == "none":
        return None
    if modality.markup == MarkupKind.HTML:
        escaped = html.escape(heading)
        if modality.headings == "h2":
            return f"<h2>{escaped}</h2>"
        return f"<strong>{escaped}</strong>"
    if modality.headings == "h2":
        return f"## {heading}"
    if modality.headings == "slack_bold":
        return f"*{heading}*"
    # modality.headings == "bold"
    if modality.markup == MarkupKind.MARKDOWN:
        return f"**{heading}**"
    if modality.markup == MarkupKind.SLACK:
        return f"*{heading}*"
    return heading


def _format_html_section(section: DraftSection, modality: Modality) -> list[str]:
    parts: list[str] = []
    heading_html = _format_heading(section.heading, modality)
    if heading_html is not None:
        parts.append(heading_html)

    body_sents = [s for s in section.sentences if not s.frame]
    frame_sents = [s for s in section.sentences if s.frame]

    if body_sents:
        if modality.bullets and len(body_sents) >= 2:
            items = "\n".join(f"<li>{html.escape(s.text)}</li>" for s in body_sents)
            parts.append(f"<ul>\n{items}\n</ul>")
        else:
            joined = " ".join(html.escape(s.text) for s in body_sents)
            parts.append(f"<p>{joined}</p>")

    for frame_sent in frame_sents:
        parts.append(f"<p>{html.escape(frame_sent.text)}</p>")

    return parts


def _format_text_section(section: DraftSection, modality: Modality) -> list[str]:
    blocks: list[str] = []
    heading_line = _format_heading(section.heading, modality)

    body_sents = [s for s in section.sentences if not s.frame]
    frame_sents = [s for s in section.sentences if s.frame]

    body_str = ""
    if body_sents:
        if modality.bullets and len(body_sents) >= 2:
            body_str = "\n".join(f"- {s.text}" for s in body_sents)
        else:
            body_str = " ".join(s.text for s in body_sents)

    if heading_line is not None and body_str:
        blocks.append(f"{heading_line}\n{body_str}")
    elif heading_line is not None and frame_sents:
        blocks.append(f"{heading_line}\n{frame_sents[0].text}")
        frame_sents = frame_sents[1:]
    elif body_str:
        blocks.append(body_str)

    for frame_sent in frame_sents:
        blocks.append(frame_sent.text)

    return blocks


def format_draft(draft: Draft, modality: Modality) -> str:
    """Format a realized Draft into the target Modality without altering sentence wording."""
    if modality.markup == MarkupKind.HTML:
        elements: list[str] = []
        if modality.title and draft.title:
            elements.append(_format_title(draft.title, MarkupKind.HTML))
        for section in draft.sections:
            if not section.sentences:
                continue
            elements.extend(_format_html_section(section, modality))
        if not elements:
            return ""
        return "<article>\n" + "\n".join(elements) + "\n</article>"

    blocks: list[str] = []
    if modality.title and draft.title:
        blocks.append(_format_title(draft.title, modality.markup))
    for section in draft.sections:
        if not section.sentences:
            continue
        blocks.extend(_format_text_section(section, modality))
    return "\n\n".join(blocks)


def count_rendered(draft: Draft, modality: Modality) -> tuple[int, int]:
    """Return (word_count, char_count) for the formatted draft under the given modality."""
    text = format_draft(draft, modality)
    char_count = len(text)
    if modality.markup == MarkupKind.HTML:
        plain = html.unescape(_HTML_TAG_RE.sub(" ", text))
        word_count = len(plain.split())
        return word_count, char_count

    tokens = [tok for raw in text.split() if (tok := raw.strip("#*-"))]
    return len(tokens), char_count
