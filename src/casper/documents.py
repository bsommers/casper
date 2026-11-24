"""Document and Block helper utilities (Rank 1)."""

from __future__ import annotations

import hashlib
import re

from casper.models import EXCLUDED_VOICE_BLOCK_KINDS, Block, BlockKind, Document

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)*")

PROSE_BLOCK_KINDS: frozenset[BlockKind] = frozenset(
    {
        BlockKind.PARAGRAPH,
        BlockKind.LIST_ITEM,
        BlockKind.QUOTE,
    }
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prose_blocks(doc: Document) -> tuple[Block, ...]:
    """Return blocks eligible for prose word count and voice feature extraction."""
    return tuple(
        b
        for b in doc.blocks
        if b.kind in PROSE_BLOCK_KINDS and b.kind not in EXCLUDED_VOICE_BLOCK_KINDS
    )


def heading_blocks(doc: Document) -> tuple[Block, ...]:
    return tuple(b for b in doc.blocks if b.kind == BlockKind.HEADING)


def list_blocks(doc: Document) -> tuple[Block, ...]:
    return tuple(b for b in doc.blocks if b.kind == BlockKind.LIST_ITEM)


def prose_text(doc: Document) -> str:
    return "\n\n".join(b.text for b in prose_blocks(doc) if b.text.strip())


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def prose_word_count(doc: Document) -> int:
    return sum(count_words(b.text) for b in prose_blocks(doc))
