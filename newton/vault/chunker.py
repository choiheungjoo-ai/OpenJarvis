"""Markdown-aware chunker.

Splits a note body into chunks suited for embedding:

  1. Primary split at ``##`` (and deeper) headings — each section is a unit.
  2. Secondary split if a section exceeds ``max_tokens`` (default ~800),
     breaking on sentence/paragraph boundaries.
  3. ``overlap_tokens`` (default ~50) of trailing context is prepended to the
     next chunk so meaning isn't lost across a boundary.

Token counts are *approximate* (whitespace-based, see ``estimate_tokens``).
Precision isn't needed here: counts only decide where to cut, and TEI's
auto_truncate guards the real model limit. This keeps the chunker dependency
-free (no tokenizer, no PyTorch).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Rough token estimate. BGE-M3 averages well under one token per "word" for
# English and a bit more for CJK; a word-ish split is close enough for sizing.
# We bias slightly high (count CJK chars individually) so chunks stay under
# the real limit rather than over.
_WORD_RE = re.compile(r"\S+")
_CJK_RE = re.compile(r"[\u3000-\u9fff\uac00-\ud7a3]")
_HEADING_RE = re.compile(r"^(#{2,6})\s+.*$", re.MULTILINE)
_SENTENCE_RE = re.compile(r"(?<=[.!?。!?])\s+|\n{2,}")

_DEFAULT_MAX_TOKENS = 800
_DEFAULT_OVERLAP_TOKENS = 50


def estimate_tokens(text: str) -> int:
    """Approximate token count: whitespace words + extra weight for CJK chars."""
    words = len(_WORD_RE.findall(text))
    cjk = len(_CJK_RE.findall(text))
    # CJK characters are roughly one token each and often glued without
    # spaces, so add them on top of the word count.
    return words + cjk


@dataclass
class Chunk:
    """One chunk ready to embed."""

    index: int
    text: str
    heading: str | None = None  # nearest preceding heading, if any


def _split_by_heading(body: str) -> list[tuple[str | None, str]]:
    """Split into (heading, section_text) keeping the heading line with body."""
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return [(None, body.strip())] if body.strip() else []

    sections: list[tuple[str | None, str]] = []
    # Preamble before the first heading.
    if matches[0].start() > 0:
        pre = body[: matches[0].start()].strip()
        if pre:
            sections.append((None, pre))

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        heading_line = m.group(0).strip()
        section = body[start:end].strip()
        sections.append((heading_line, section))
    return sections


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _subsplit_large(
    heading: str | None, section: str, max_tokens: int, overlap_tokens: int
) -> list[tuple[str | None, str]]:
    """Break a too-large section into pieces on sentence boundaries with overlap."""
    if estimate_tokens(section) <= max_tokens:
        return [(heading, section)]

    sentences = _split_sentences(section)
    pieces: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sent in sentences:
        st = estimate_tokens(sent)
        if current and current_tokens + st > max_tokens:
            pieces.append(" ".join(current))
            # Start next piece with trailing overlap from the previous one.
            overlap: list[str] = []
            otok = 0
            for s in reversed(current):
                otok += estimate_tokens(s)
                overlap.insert(0, s)
                if otok >= overlap_tokens:
                    break
            current = overlap + [sent]
            current_tokens = sum(estimate_tokens(s) for s in current)
        else:
            current.append(sent)
            current_tokens += st

    if current:
        pieces.append(" ".join(current))

    return [(heading, p) for p in pieces]


def chunk_text(
    body: str,
    *,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    overlap_tokens: int = _DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Chunk a note body. Returns chunks in document order."""
    body = body.strip()
    if not body:
        return []

    chunks: list[Chunk] = []
    idx = 0
    for heading, section in _split_by_heading(body):
        if not section:
            continue
        for h, piece in _subsplit_large(heading, section, max_tokens, overlap_tokens):
            chunks.append(Chunk(index=idx, text=piece, heading=h))
            idx += 1
    return chunks


__all__ = ["Chunk", "chunk_text", "estimate_tokens"]
