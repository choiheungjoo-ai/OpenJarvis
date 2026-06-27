"""Tests for ``newton.voice.sentences.split_sentences``.

The splitter feeds the ``voice tts --stream`` pipeline. It's a
pragmatic regex — these tests pin the happy-path behaviour for EN+KO
and document the known limitations (decimals/abbreviations split) so a
future change can't silently regress streaming UX.
"""

from __future__ import annotations

import sys

from newton.voice.sentences import split_sentences

# ── English ──────────────────────────────────────────────────────────────


def test_english_multi_sentence():
    assert split_sentences("First. Second. Third.", "en") == [
        "First.",
        "Second.",
        "Third.",
    ]


def test_english_mixed_terminators():
    assert split_sentences("Wait! Really? Yes.", "en") == [
        "Wait!",
        "Really?",
        "Yes.",
    ]


def test_english_no_trailing_period():
    assert split_sentences("Hello world. How are you", "en") == [
        "Hello world.",
        "How are you",
    ]


def test_english_single_sentence_returned_as_one():
    assert split_sentences("Hello world", "en") == ["Hello world"]


def test_english_multiple_terminators_glue_together():
    # "..." and "?!" stay glued to their sentence (prosody cue for TTS).
    assert split_sentences("Wait... what?!", "en") == ["Wait...", "what?!"]


# ── Korean ───────────────────────────────────────────────────────────────


def test_korean_with_spaces():
    assert split_sentences("안녕하세요. 잘 지내요? 좋아요!", "ko") == [
        "안녕하세요.",
        "잘 지내요?",
        "좋아요!",
    ]


def test_korean_without_spaces_between_sentences():
    # KO routinely joins sentences with no space — must still split.
    assert split_sentences("안녕하세요.잘지내요?좋아요!", "ko") == [
        "안녕하세요.",
        "잘지내요?",
        "좋아요!",
    ]


def test_korean_horizontal_ellipsis_is_terminator():
    assert split_sentences("안녕…잘 지내요?", "ko") == ["안녕…", "잘 지내요?"]


def test_korean_no_punctuation():
    assert split_sentences("안녕하세요", "ko") == ["안녕하세요"]


# ── whitespace / empties ────────────────────────────────────────────────


def test_empty_string_returns_empty_list():
    assert split_sentences("", "en") == []


def test_whitespace_only_returns_empty_list():
    assert split_sentences("   \n  \t ", "en") == []


def test_collapses_internal_whitespace():
    assert split_sentences("  Hi   there.   Bye.  ", "en") == ["Hi there.", "Bye."]


def test_all_terminator_input_kept_as_single_sentence():
    # "..." has no non-terminator chars but we still want the caller
    # to be able to iterate over something rather than getting [].
    assert split_sentences("...", "en") == ["..."]


# ── mixed-language and edge cases ───────────────────────────────────────


def test_mixed_english_korean():
    assert split_sentences("Hi. 안녕하세요. Bye!", "en") == [
        "Hi.",
        "안녕하세요.",
        "Bye!",
    ]


def test_documented_limitation_decimals_split():
    # Pinned to document the limitation — a future fix may relax this,
    # at which point this assert should be updated, not silently regress.
    assert split_sentences("Pi is 3.14 roughly.", "en") == [
        "Pi is 3.",
        "14 roughly.",
    ]


def test_documented_limitation_abbreviations_split():
    assert split_sentences("Mr. Smith arrived.", "en") == [
        "Mr.",
        "Smith arrived.",
    ]


# ── Strategy D guard ────────────────────────────────────────────────────


def test_sentences_and_streaming_imports_have_no_heavy_deps():
    """Both new modules must stay torch/sounddevice-free."""
    # streaming.py is the heavier of the two — importing it must not
    # drag torch / sounddevice in. (numpy is fine; it's a core dep.)
    import newton.voice.streaming  # noqa: F401 — import-for-side-effect

    assert "torch" not in sys.modules
    assert "sounddevice" not in sys.modules
