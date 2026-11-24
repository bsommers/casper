"""HTML document loader with JSON-LD/meta extraction and voice-exclusion tagging (Rank 2)."""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from casper.documents import sha256_bytes
from casper.models import Block, BlockKind, Document

_SUMMARY_RE = re.compile(r"^(summary|tl;?dr|abstract|key takeaways)$", re.IGNORECASE)
_AUDIENCE_RE = re.compile(r"^(audience|who this is for|prerequisites)$", re.IGNORECASE)
_RESOURCES_RE = re.compile(
    r"^(resources|references|further reading|related links)$", re.IGNORECASE
)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _excluded_kind_for_heading(text: str) -> BlockKind | None:
    cleaned = _clean_text(text).rstrip(":")
    if _SUMMARY_RE.match(cleaned):
        return BlockKind.SUMMARY
    if _AUDIENCE_RE.match(cleaned):
        return BlockKind.AUDIENCE
    if _RESOURCES_RE.match(cleaned):
        return BlockKind.RESOURCES
    return None


def _has_emphasis_lead(tag: Tag) -> bool:
    for child in tag.contents:
        if isinstance(child, str):
            if child.strip():
                return False
            continue
        if isinstance(child, Tag):
            return child.name in {"strong", "b", "em", "i"}
    return False


def _extract_json_ld(soup: BeautifulSoup) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.IGNORECASE)}):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if not isinstance(item, dict):
                continue
            if "@graph" in item and isinstance(item["@graph"], list):
                items.extend(g for g in item["@graph"] if isinstance(g, dict))
                continue
            if not meta.get("title"):
                title = item.get("headline") or item.get("name")
                if isinstance(title, str) and title.strip():
                    meta["title"] = title.strip()
            if not meta.get("published"):
                pub = item.get("datePublished")
                if isinstance(pub, str) and pub.strip():
                    meta["published"] = pub.strip()
            if not meta.get("modified"):
                mod = item.get("dateModified")
                if isinstance(mod, str) and mod.strip():
                    meta["modified"] = mod.strip()
            if not meta.get("description"):
                desc = item.get("description")
                if isinstance(desc, str) and desc.strip():
                    meta["description"] = desc.strip()
            author_val = item.get("author")
            if author_val and not meta.get("authors"):
                authors: list[str] = []
                author_list = author_val if isinstance(author_val, list) else [author_val]
                for a in author_list:
                    if isinstance(a, str) and a.strip():
                        authors.append(a.strip())
                    elif isinstance(a, dict):
                        nm = a.get("name")
                        if isinstance(nm, str) and nm.strip():
                            authors.append(nm.strip())
                if authors:
                    meta["authors"] = authors
    return meta


def parse_html(data: bytes, source: str) -> Document:
    text = data.decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "lxml")

    ld = _extract_json_ld(soup)
    title: str | None = ld.get("title")
    authors: list[str] = list(ld.get("authors", ()))
    published: str | None = ld.get("published")
    modified: str | None = ld.get("modified")
    canonical_url: str | None = None
    description: str | None = ld.get("description")

    for meta_tag in soup.find_all("meta"):
        if not isinstance(meta_tag, Tag):
            continue
        name = str(meta_tag.get("name") or meta_tag.get("property") or "").lower()
        content = str(meta_tag.get("content") or "").strip()
        if not content:
            continue
        if name in {"og:title", "twitter:title"} and not title:
            title = content
        elif name == "author" and content not in authors:
            authors.append(content)
        elif name in {"article:published_time", "pubdate", "date"} and not published:
            published = content
        elif name in {"article:modified_time", "last-modified"} and not modified:
            modified = content
        elif name in {"description", "og:description"} and not description:
            description = content

    canon = soup.find("link", rel="canonical")
    if isinstance(canon, Tag) and canon.get("href"):
        canonical_url = str(canon["href"]).strip()

    if not title and soup.title and soup.title.string:
        title = _clean_text(soup.title.string)

    for junk in soup.find_all(["script", "style", "nav", "footer", "noscript"]):
        junk.decompose()

    root: Tag = soup.find("article") or soup.find("main") or soup.body or soup  # type: ignore[assignment]

    blocks: list[Block] = []
    active_excluded: BlockKind | None = None
    active_excluded_level: int = 0

    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre"]):
        if not isinstance(el, Tag):
            continue
        # Skip nested p inside li or blockquote to avoid duplicate extraction
        if el.name == "p" and el.find_parent(["li", "blockquote"]) is not None:
            continue

        in_aside = el.find_parent("aside") is not None
        tag_name = el.name

        if tag_name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag_name[1])
            htext = _clean_text(el.get_text(" ", strip=True))
            if not htext:
                continue
            if level == 1 and not title:
                title = htext
            excl = _excluded_kind_for_heading(htext)
            if excl is not None:
                active_excluded = excl
                active_excluded_level = level
                blocks.append(Block(kind=excl, text=htext, level=level))
                continue
            if active_excluded is not None and level <= active_excluded_level:
                active_excluded = None
                active_excluded_level = 0
            kind = BlockKind.SUMMARY if in_aside else (BlockKind.TITLE if level == 1 else BlockKind.HEADING)
            blocks.append(Block(kind=kind, text=htext, level=level))
            continue

        if tag_name == "pre":
            code_text = el.get_text("\n").strip()
            if code_text:
                blocks.append(Block(kind=BlockKind.CODE, text=code_text))
            continue

        content_text = _clean_text(el.get_text(" ", strip=True))
        if not content_text:
            continue

        link_count = len(el.find_all("a"))
        emph_lead = _has_emphasis_lead(el)

        if in_aside:
            kind = BlockKind.SUMMARY
            lvl = 0
        elif active_excluded is not None:
            kind = active_excluded
            lvl = 0
        elif tag_name == "li":
            kind = BlockKind.LIST_ITEM
            lvl = max(1, len(el.find_parents(["ul", "ol"])))
        elif tag_name == "blockquote":
            kind = BlockKind.QUOTE
            lvl = 0
        else:
            kind = BlockKind.PARAGRAPH
            lvl = 0

        blocks.append(
            Block(
                kind=kind,
                text=content_text,
                level=lvl,
                links=link_count,
                emphasis_lead=emph_lead,
            )
        )

    return Document(
        source=source,
        format="html",
        title=title,
        authors=tuple(authors),
        published=published,
        modified=modified,
        canonical_url=canonical_url,
        description=description,
        blocks=tuple(blocks),
        sha256=sha256_bytes(data),
    )
