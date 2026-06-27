"""Sentence splitting for sentence-streamed TTS.

A pragmatic, dependency-free regex splitter for the voice stack. The
Qwen3-TTS package doesn't expose token-level streaming, so the
``newton voice tts --stream`` path simulates streaming at sentence
granularity — split, synthesize one, start playing while the next
synthesizes.

The splitter handles English (``. ! ?``) and Korean (``. ! ? …`` — KO
uses the horizontal ellipsis often). KO clauses are routinely joined
without a space, so the splitter does NOT require whitespace after a
terminator; trailing punctuation stays glued to its sentence so the
synthesizer can use it as a prosody cue.

Known limitations
-----------------
This is a streaming-time splitter, not a corpus tokenizer:

* Decimals (``3.14``) split — there is no number rule.
* English abbreviations (``Mr.``, ``e.g.``) split — same reason.
* No multi-paragraph handling beyond whitespace collapse.

Streamed speech keeps moving, so a too-eager split is a smaller
problem than the heavy deps it would take to avoid it (nltk / spaCy).
Offline batch synthesis can stay on ``--no-stream``.
"""

from __future__ import annotations

import re

# Sentence-final punctuation. KO additionally uses the horizontal
# ellipsis (… → "…"). Centralised so per-locale extension stays
# a one-line change.
_TERMINATORS = ".!?…"

# A sentence is either:
#  * one-or-more non-terminator chars followed by one-or-more terminator
#    chars (the terminator stays glued to the sentence), or
#  * a trailing run of non-terminator chars at end-of-string (no period).
_SENTENCE_RE = re.compile(
    rf"[^{re.escape(_TERMINATORS)}]+[{re.escape(_TERMINATORS)}]+"
    rf"|[^{re.escape(_TERMINATORS)}]+$"
)
_WHITESPACE_RE = re.compile(r"\s+")


def split_sentences(text: str, lang: str) -> list[str]:
    """Split ``text`` into sentences for streamed synthesis.

    Returns ``[]`` for empty / whitespace-only input. Inputs with no
    sentence-final punctuation collapse to a single element so callers
    can always iterate.

    The ``lang`` argument is accepted so the signature can grow
    per-locale rules later (e.g. JA's ``。``) without touching every
    caller; EN and KO currently share one regex.
    """
    _ = lang  # reserved for per-locale rules
    if not text or not text.strip():
        return []
    pieces = _SENTENCE_RE.findall(text)
    out: list[str] = []
    for piece in pieces:
        normalised = _WHITESPACE_RE.sub(" ", piece).strip()
        if normalised:
            out.append(normalised)
    if out:
        return out
    # All-terminator input (e.g. "...") — preserve as a single sentence
    # rather than dropping it, so the caller still has something to say.
    return [text.strip()]


__all__ = ["split_sentences"]
