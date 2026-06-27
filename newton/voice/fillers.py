"""Pre-synthesized "filler" clips for zero-latency persona replies.

A filler is a short, generic phrase ("Of course, sir. Allow me a moment
to gather precisely what you need.") that plays *instantly* from disk
while the real answer is still synthesizing. Synthesis on a warm GPU is
~1.5-2 s per sentence; a ~3-4 s filler fully masks that gap, so the
user perceives no wait.

This module is the persistent half of the system: it knows every
phrase the persona ships with (config + ``DEFAULT_FILLERS``), where its
cached WAV lives on disk, and how to build / pick those WAVs. The
live wiring into ``voice tts --filler`` is in :mod:`newton.cli` /
:mod:`newton.voice.streaming`.

Strategy D
----------
The module imports only the stdlib, numpy, and
:mod:`newton.voice.tts.base` (an ABC). No torch, no sounddevice. The
TTS engine used during ``build_cache`` is *injected* by the caller —
the production CLI hands in a function backed by the HTTP TTS service.

Disk layout
-----------
Cache files live under ``<voice_root>/<persona>/fillers/<lang>/<category>/``,
one WAV per phrase, named by ``sha1(phrase)[:12]``. The hash keeps file
names short and stable across config edits — change a phrase and the
new hash means the new WAV (not the stale one) lives next to it.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from newton.voice.tts.base import TTS, save_wav

# ─────────────────────────────────────────────────────────────────────────────
# Default phrase library — JARVIS, EN + KO
# ─────────────────────────────────────────────────────────────────────────────
#
# Shape: ``{persona: {language: {category: [phrases]}}}``. The defaults
# ship in code so a fresh checkout works without a ``voice.yaml``;
# overrides at the same path REPLACE the category's list (per
# :func:`merge_filler_phrases`) so the cache builder sees exactly what
# the user wrote.
#
# Sourced from docs/newton/jarvis-fillers.md. Keep them in sync —
# treat that doc as the editor-friendly view, this dict as the
# machine-readable view.

DEFAULT_FILLERS: dict[str, dict[str, dict[str, list[str]]]] = {
    "jarvis": {
        "en": {
            "acknowledge": [
                "Of course, sir. Allow me a moment to gather precisely what you need.",
                "Right away, sir. I'm pulling the relevant pieces together "
                "as we speak.",
                "Certainly, sir. Give me just a moment to look into this "
                "properly for you.",
                "Consider it done, sir. I'm assembling the details for you now.",
                "At once, sir. Let me retrieve the relevant information and "
                "present it clearly.",
                "Very good, sir. I shall have that ready for you in just a moment.",
                "Understood, sir. I'm working through the particulars as we speak.",
                "Naturally, sir. Allow me a brief moment to put this in order for you.",
                "With pleasure, sir. I'm attending to it this very instant.",
                "Straight away, sir. Let me ensure I have every detail correct first.",
            ],
            "thinking": [
                "Let me see what I can find for you, sir. This will take "
                "only a moment.",
                "I'm looking into that now, sir. Bear with me for just a "
                "second or two.",
                "Allow me to check on that, sir. I'd like to give you a "
                "precise answer.",
                "One moment while I look that up, sir. I want to be thorough about it.",
                "I'm cross-referencing the details now, sir. It won't be a moment.",
                "Give me a heartbeat to consult the records, sir, and I'll "
                "have your answer.",
                "Let me run the numbers properly, sir. I'd rather be right than quick.",
            ],
            "greeting_morning": [
                "Good morning, sir. I trust you slept well. Allow me a "
                "moment to begin.",
                "Good morning, sir. The day holds promise. Let me gather "
                "what you'll need.",
                "A very good morning to you, sir. I'll have everything ready shortly.",
                "Good morning, sir. Rested, I hope. One moment while I "
                "bring things up.",
            ],
            "greeting_evening": [
                "Good evening, sir. I hope the day treated you kindly. "
                "Allow me a moment.",
                "Good evening, sir. Let me attend to that for you straight away.",
                "Good evening, sir. Winding down, are we? One moment, if "
                "you'd be so kind.",
            ],
            "welcome_back": [
                "Welcome back, sir. I've kept things in order in your "
                "absence. One moment.",
                "Ah, there you are, sir. I was just keeping the systems "
                "warm. Allow me a moment.",
                "At your service, sir, as always. Let me see to that right away.",
            ],
            "affirm": [
                "Absolutely, sir. I'm on it.",
                "Indeed, sir. Allow me.",
                "As you wish, sir. Proceeding now.",
                "Quite so, sir. One moment.",
                "Without question, sir.",
            ],
            "acknowledge_problem": [
                "I'm afraid there's a small complication, sir. Allow me to "
                "explain in a moment.",
                "A moment, sir — I want to be certain I have this exactly "
                "right before I answer.",
                "There's a wrinkle worth mentioning, sir. Let me lay it "
                "out for you clearly.",
                "I should flag something, sir. Give me a moment to put it plainly.",
            ],
            "wit": [
                "An excellent question, sir. Let me do it justice with a "
                "proper answer.",
                "You're keeping me busy today, sir. With pleasure. One moment.",
                "As ever, sir, you ask the interesting ones. Allow me a moment.",
                "I anticipated you might ask, sir. Let me bring it up.",
            ],
            "working_long": [
                "This one will take a touch longer, sir. I'll keep you posted as I go.",
                "Bear with me, sir — this deserves a careful look. I won't "
                "keep you waiting long.",
                "Give me a proper moment for this, sir. I'd rather get it "
                "right the first time.",
            ],
        },
        "ko": {
            "acknowledge": [
                "물론입니다, sir. 필요하신 내용을 정확히 준비하겠습니다. 잠시만요.",
                "알겠습니다, sir. 지금 바로 관련 자료를 모으고 있습니다.",
                "네, sir. 말씀하신 내용을 정리하는 중입니다. 잠깐이면 됩니다.",
                "분부대로 하겠습니다, sir. 지금 세부 사항을 살펴보고 있습니다.",
                "곧바로 처리하겠습니다, sir. 정확한지 먼저 확인하겠습니다.",
                "기꺼이 하겠습니다, sir. 지금 이 순간 처리하고 있습니다.",
            ],
            "thinking": [
                "지금 찾아보고 있습니다, sir. 잠깐이면 됩니다.",
                "확인하는 중입니다, sir. 정확하게 답변드리고 싶습니다.",
                "기록을 대조하고 있습니다, sir. 곧 답을 드리겠습니다.",
                "제대로 계산해 보겠습니다, sir. 서두르기보다 정확한 편이 낫겠지요.",
            ],
            "greeting_morning": [
                "좋은 아침입니다, sir. 잘 주무셨길 바랍니다. 잠시만 준비하겠습니다.",
                "안녕히 주무셨습니까, sir. 오늘 일정을 정리해 두었습니다. 잠시만요.",
                "상쾌한 아침입니다, sir. 필요하신 것을 바로 가져오겠습니다.",
            ],
            "greeting_evening": [
                "좋은 저녁입니다, sir. 오늘 하루 수고 많으셨습니다. 잠시만요.",
                "편안한 저녁입니다, sir. 바로 처리해 드리겠습니다.",
            ],
            "welcome_back": [
                "돌아오셨군요, sir. 자리를 비우신 동안 잘 관리해 두었습니다. 잠시만요.",
                "기다리고 있었습니다, sir. 시스템을 따뜻하게 유지해 두었습니다.",
            ],
            "affirm": [
                "물론입니다, sir. 바로 처리하겠습니다.",
                "네, sir. 그렇게 하겠습니다.",
                "당연하지요, sir. 잠시만요.",
            ],
            "acknowledge_problem": [
                "한 가지 짚을 점이 있습니다, sir. 잠시 후에 분명히 설명드리겠습니다.",
                "잠깐만요, sir — 정확히 확인한 뒤에 말씀드리는 게 좋겠습니다.",
            ],
            "wit": [
                "좋은 질문이십니다, sir. 제대로 답해 드리겠습니다. 잠시만요.",
                "오늘 저를 바쁘게 하시는군요, sir. 기꺼이 하겠습니다.",
                "그러실 줄 알았습니다, sir. 바로 가져오겠습니다.",
            ],
            "working_long": [
                "이건 조금 더 걸리겠습니다, sir. 진행 상황을 알려드리겠습니다.",
                "잠시만 기다려 주십시오, sir. 한 번에 제대로 하고 싶습니다.",
            ],
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Config merge
# ─────────────────────────────────────────────────────────────────────────────


def merge_filler_phrases(
    overrides: dict[str, dict[str, dict[str, list[str]]]],
) -> dict[str, dict[str, dict[str, list[str]]]]:
    """Combine :data:`DEFAULT_FILLERS` with user ``overrides``.

    Merge semantics — per category, the user's list REPLACES the
    default. Unspecified categories keep defaults. New persona /
    language / category keys add to the result. An empty list disables
    a category for that (persona, language).

    The defaults are deep-copied first so callers can mutate the result
    without poisoning :data:`DEFAULT_FILLERS` for the rest of the
    process.
    """
    merged = deepcopy(DEFAULT_FILLERS)
    for persona, languages in (overrides or {}).items():
        persona_block = merged.setdefault(persona, {})
        for language, categories in (languages or {}).items():
            lang_block = persona_block.setdefault(language, {})
            for category, phrases in (categories or {}).items():
                lang_block[category] = list(phrases)
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# Library — cache-path derivation and on-disk inspection
# ─────────────────────────────────────────────────────────────────────────────


class FillerNotCachedError(LookupError):
    """Raised by :func:`pick` when a (persona, lang, category) has no clip on disk."""


class FillerSynthSpec(NamedTuple):
    """What ``build_cache`` needs per (persona, language) to synthesize.

    The caller builds these from the TTS router so this module never
    talks to the router directly — keeps the dependency graph one-way.
    """

    engine: TTS
    voice_reference: Path | None
    ref_text: str | None


@dataclass(frozen=True, slots=True)
class FillerEntry:
    """One configured phrase + the path its WAV would live at."""

    persona: str
    language: str
    category: str
    phrase: str
    path: Path

    @property
    def cached(self) -> bool:
        return self.path.exists()


@dataclass(frozen=True, slots=True)
class BuildCacheReport:
    """Counts returned from :func:`build_cache`."""

    persona: str
    synthesized: int = 0
    skipped_existing: int = 0
    failed: int = 0
    languages: list[str] = field(default_factory=list)


class FillerLibrary:
    """Stateless view of "what phrases exist, where do their WAVs live".

    The library does not synthesize anything; that's :func:`build_cache`.
    It does not pick anything; that's :func:`pick`. It just answers:

    * which phrases does (persona, language, category) have?
    * where is each phrase's cache file?
    * which of those files exist on disk right now?
    """

    def __init__(
        self,
        *,
        phrases: dict[str, dict[str, dict[str, list[str]]]],
        voice_root: Path | str,
    ) -> None:
        self._phrases = phrases
        self._voice_root = Path(voice_root)

    # ── construction ────────────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        config: object,
        voice_root: Path | str,
    ) -> FillerLibrary:
        """Build a library from a :class:`~newton.voice.config.VoiceConfig`.

        ``config`` is typed as :class:`object` so this module need not
        import the top-level config class at module load — keeps the
        Strategy-D import graph minimal and helps tests that mock the
        config out.
        """
        overrides = getattr(config, "fillers", None)
        overrides_dict = (
            overrides.phrases
            if overrides is not None and hasattr(overrides, "phrases")
            else {}
        )
        merged = merge_filler_phrases(overrides_dict)
        return cls(phrases=merged, voice_root=voice_root)

    # ── enumeration ─────────────────────────────────────────────────────

    def personas(self) -> list[str]:
        return sorted(self._phrases.keys())

    def languages(self, persona: str) -> list[str]:
        return sorted(self._phrases.get(persona, {}).keys())

    def categories(self, persona: str, language: str) -> list[str]:
        return sorted(self._phrases.get(persona, {}).get(language, {}).keys())

    def phrases(self, persona: str, language: str, category: str) -> list[str]:
        return list(self._phrases.get(persona, {}).get(language, {}).get(category, []))

    # ── on-disk path derivation ─────────────────────────────────────────

    @property
    def voice_root(self) -> Path:
        return self._voice_root

    def cache_dir(self, persona: str, language: str, category: str) -> Path:
        return self._voice_root / persona / "fillers" / language / category

    def cache_path(
        self, persona: str, language: str, category: str, phrase: str
    ) -> Path:
        digest = hashlib.sha1(phrase.encode("utf-8")).hexdigest()[:12]
        return self.cache_dir(persona, language, category) / f"{digest}.wav"

    def entries(
        self,
        *,
        persona: str | None = None,
        language: str | None = None,
        category: str | None = None,
    ) -> list[FillerEntry]:
        """Flat list of every configured (persona, lang, category, phrase)."""
        out: list[FillerEntry] = []
        for p in self.personas():
            if persona is not None and p != persona:
                continue
            for ll in self.languages(p):
                if language is not None and ll != language:
                    continue
                for cat in self.categories(p, ll):
                    if category is not None and cat != category:
                        continue
                    for phrase in self.phrases(p, ll, cat):
                        out.append(
                            FillerEntry(
                                persona=p,
                                language=ll,
                                category=cat,
                                phrase=phrase,
                                path=self.cache_path(p, ll, cat, phrase),
                            )
                        )
        return out

    def cached_paths(self, persona: str, language: str, category: str) -> list[Path]:
        """Cache files that currently exist on disk for the given category.

        Order follows :meth:`phrases` (config order) so callers can
        rotate deterministically when they want round-robin.
        """
        paths: list[Path] = []
        for phrase in self.phrases(persona, language, category):
            p = self.cache_path(persona, language, category, phrase)
            if p.exists():
                paths.append(p)
        return paths


# ─────────────────────────────────────────────────────────────────────────────
# Cache build + pick
# ─────────────────────────────────────────────────────────────────────────────


def build_cache(
    library: FillerLibrary,
    persona: str,
    resolver: Callable[[str], FillerSynthSpec],
    *,
    force: bool = False,
) -> BuildCacheReport:
    """Synthesize every missing filler for ``persona`` into the cache.

    ``resolver(language)`` returns the engine + sample to use for that
    language's phrases — built by the caller from the TTS router so
    this module never imports the router itself.

    Idempotent: existing files are skipped unless ``force=True``. The
    returned report counts ``synthesized`` (new), ``skipped_existing``
    (no-op), and ``failed`` (synthesis raised).

    Engine failures are caught per-phrase so one bad language doesn't
    abort the whole rebuild; the count surfaces in the report.
    """
    synthesized = 0
    skipped = 0
    failed = 0
    languages_done: list[str] = []

    for language in library.languages(persona):
        spec: FillerSynthSpec | None = None
        for category in library.categories(persona, language):
            for phrase in library.phrases(persona, language, category):
                out = library.cache_path(persona, language, category, phrase)
                if out.exists() and not force:
                    skipped += 1
                    continue
                if spec is None:
                    # Lazy-resolve so a language with all phrases already
                    # cached never touches the engine factory.
                    spec = resolver(language)
                try:
                    result = spec.engine.synthesize(
                        phrase,
                        language=language,
                        voice_reference=spec.voice_reference,
                        ref_text=spec.ref_text,
                    )
                except BaseException:  # noqa: BLE001 — count + continue
                    failed += 1
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                save_wav(result, out)
                synthesized += 1
        if spec is not None:
            languages_done.append(language)

    return BuildCacheReport(
        persona=persona,
        synthesized=synthesized,
        skipped_existing=skipped,
        failed=failed,
        languages=languages_done,
    )


def pick(
    library: FillerLibrary,
    persona: str,
    language: str,
    category: str,
    *,
    rng: random.Random | None = None,
) -> Path:
    """Return a cached filler WAV for ``(persona, language, category)``.

    Picks uniformly at random from the cached variants — so repeats
    don't sound canned. Raises :class:`FillerNotCachedError` if the
    category has no cached clip yet; the caller is expected to fall
    back to "no filler" rather than blow up.
    """
    paths = library.cached_paths(persona, language, category)
    if not paths:
        raise FillerNotCachedError(
            f"no cached filler clip for persona={persona!r} "
            f"language={language!r} category={category!r}. "
            f"Run `newton voice fillers build --persona {persona}` first."
        )
    chooser = rng if rng is not None else random
    return chooser.choice(paths)


__all__ = [
    "DEFAULT_FILLERS",
    "BuildCacheReport",
    "FillerEntry",
    "FillerLibrary",
    "FillerNotCachedError",
    "FillerSynthSpec",
    "build_cache",
    "merge_filler_phrases",
    "pick",
]
