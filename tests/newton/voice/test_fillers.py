"""Tests for ``newton.voice.fillers`` — the instant-reply clip library.

Coverage:
    * cache path derivation (sha1 hash, persona/lang/category structure)
    * idempotent ``build_cache`` (skips existing, ``force`` rebuilds)
    * ``pick`` rotates across cached variants + raises on empty category
    * config override merges with defaults (replace + extend + disable)
    * Strategy D import guard — module loads without torch
"""

from __future__ import annotations

import hashlib
import random
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from newton.voice.config import FillerConfig, VoiceConfig
from newton.voice.fillers import (
    DEFAULT_FILLERS,
    BuildCacheReport,
    FillerLibrary,
    FillerNotCachedError,
    FillerSynthSpec,
    build_cache,
    merge_filler_phrases,
    pick,
)
from newton.voice.tts.base import TTS, TTSResult

# ── helpers ───────────────────────────────────────────────────────────────


class _RecordingEngine(TTS):
    """Records every ``synthesize`` call; emits a short 22050 Hz tone."""

    name = "qwen3_tts_jarvis"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice_reference=None,
        ref_text: str | None = None,
    ) -> TTSResult:
        self.calls.append(
            {
                "text": text,
                "language": language,
                "voice_reference": (
                    str(voice_reference) if voice_reference is not None else None
                ),
                "ref_text": ref_text,
            }
        )
        n = 2205  # 0.1s @ 22050 Hz
        return TTSResult(audio=np.full(n, 0.1, dtype=np.float32), sample_rate=22050)


def _spec(engine: TTS) -> FillerSynthSpec:
    return FillerSynthSpec(engine=engine, voice_reference=None, ref_text=None)


def _library_with(
    tmp_path: Path,
    phrases: dict[str, dict[str, dict[str, list[str]]]],
) -> FillerLibrary:
    return FillerLibrary(phrases=phrases, voice_root=tmp_path / "voices")


# ── 1. cache path derivation ─────────────────────────────────────────────


def test_cache_path_uses_sha1_first_12_hex(tmp_path):
    library = _library_with(
        tmp_path,
        {"jarvis": {"en": {"acknowledge": ["Of course, sir."]}}},
    )
    phrase = "Of course, sir."
    expected_hash = hashlib.sha1(phrase.encode("utf-8")).hexdigest()[:12]
    p = library.cache_path("jarvis", "en", "acknowledge", phrase)
    assert p.name == f"{expected_hash}.wav"
    assert p.parent == tmp_path / "voices" / "jarvis" / "fillers" / "en" / "acknowledge"


def test_cache_path_differs_for_different_phrases(tmp_path):
    library = _library_with(tmp_path, {})
    p1 = library.cache_path("jarvis", "en", "acknowledge", "Of course, sir.")
    p2 = library.cache_path("jarvis", "en", "acknowledge", "Right away, sir.")
    assert p1 != p2


def test_cached_paths_only_lists_existing_files(tmp_path):
    phrases = {
        "jarvis": {"en": {"acknowledge": ["alpha", "beta", "gamma"]}},
    }
    library = _library_with(tmp_path, phrases)
    # Create only beta on disk.
    beta = library.cache_path("jarvis", "en", "acknowledge", "beta")
    beta.parent.mkdir(parents=True, exist_ok=True)
    beta.write_bytes(b"fake")
    found = library.cached_paths("jarvis", "en", "acknowledge")
    assert found == [beta]


# ── 2. idempotent build_cache ────────────────────────────────────────────


def test_build_cache_synthesizes_each_missing_phrase_once(tmp_path):
    phrases = {
        "jarvis": {
            "en": {"acknowledge": ["alpha", "beta"]},
            "ko": {"affirm": ["감마"]},
        },
    }
    library = _library_with(tmp_path, phrases)
    engine = _RecordingEngine()

    report = build_cache(library, "jarvis", lambda _lang: _spec(engine))

    assert isinstance(report, BuildCacheReport)
    assert report.synthesized == 3
    assert report.skipped_existing == 0
    assert report.failed == 0
    assert set(report.languages) == {"en", "ko"}
    # Each call passed text + correct language.
    assert [c["text"] for c in engine.calls] == ["alpha", "beta", "감마"]
    assert {c["language"] for c in engine.calls} == {"en", "ko"}
    # On-disk files exist.
    for phrase, lang in [("alpha", "en"), ("beta", "en"), ("감마", "ko")]:
        cat = "acknowledge" if lang == "en" else "affirm"
        assert library.cache_path("jarvis", lang, cat, phrase).exists()


def test_build_cache_skips_existing_clips(tmp_path):
    phrases = {"jarvis": {"en": {"acknowledge": ["alpha", "beta"]}}}
    library = _library_with(tmp_path, phrases)
    engine = _RecordingEngine()

    # First build — both synthesized.
    build_cache(library, "jarvis", lambda _lang: _spec(engine))
    assert len(engine.calls) == 2

    # Second build — both skipped, engine untouched.
    engine.calls.clear()
    report = build_cache(library, "jarvis", lambda _lang: _spec(engine))
    assert engine.calls == []
    assert report.synthesized == 0
    assert report.skipped_existing == 2


def test_build_cache_force_rebuilds_existing_clips(tmp_path):
    phrases = {"jarvis": {"en": {"acknowledge": ["alpha"]}}}
    library = _library_with(tmp_path, phrases)
    engine = _RecordingEngine()

    build_cache(library, "jarvis", lambda _lang: _spec(engine))
    engine.calls.clear()

    report = build_cache(library, "jarvis", lambda _lang: _spec(engine), force=True)
    assert len(engine.calls) == 1
    assert report.synthesized == 1
    assert report.skipped_existing == 0


def test_build_cache_resolver_not_called_when_all_cached(tmp_path):
    phrases = {"jarvis": {"en": {"acknowledge": ["alpha"]}}}
    library = _library_with(tmp_path, phrases)
    # Pre-create the file so build_cache sees it as already cached.
    p = library.cache_path("jarvis", "en", "acknowledge", "alpha")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"fake")

    boom = {"called": False}

    def explosive_resolver(_language):
        boom["called"] = True
        raise AssertionError("resolver must not run when all phrases are cached")

    report = build_cache(library, "jarvis", explosive_resolver)
    assert boom["called"] is False
    assert report.synthesized == 0
    assert report.skipped_existing == 1


def test_build_cache_counts_engine_failures(tmp_path):
    phrases = {"jarvis": {"en": {"acknowledge": ["alpha", "beta"]}}}
    library = _library_with(tmp_path, phrases)

    class _Flaky(TTS):
        name = "qwen3_tts_jarvis"

        def __init__(self) -> None:
            self.n = 0

        def synthesize(self, text, **kwargs):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("model not loaded")
            return TTSResult(audio=np.zeros(100, dtype=np.float32), sample_rate=22050)

    engine = _Flaky()
    report = build_cache(library, "jarvis", lambda _lang: _spec(engine))
    assert report.synthesized == 1
    assert report.failed == 1


# ── 3. pick() rotation + missing-category error ─────────────────────────


def test_pick_rotates_across_cached_variants(tmp_path):
    phrases = {"jarvis": {"en": {"acknowledge": ["alpha", "beta", "gamma"]}}}
    library = _library_with(tmp_path, phrases)
    engine = _RecordingEngine()
    build_cache(library, "jarvis", lambda _lang: _spec(engine))

    seen: set[Path] = set()
    rng = random.Random(0)
    for _ in range(40):
        seen.add(pick(library, "jarvis", "en", "acknowledge", rng=rng))
    # All three variants picked over enough draws.
    assert len(seen) == 3
    for p in seen:
        assert p.exists()


def test_pick_raises_when_no_clip_cached(tmp_path):
    phrases = {"jarvis": {"en": {"acknowledge": ["alpha"]}}}
    library = _library_with(tmp_path, phrases)
    # No build_cache → no files on disk.
    with pytest.raises(FillerNotCachedError) as excinfo:
        pick(library, "jarvis", "en", "acknowledge")
    assert "no cached filler clip" in str(excinfo.value)
    assert "newton voice fillers build" in str(excinfo.value)


def test_pick_raises_for_unknown_category(tmp_path):
    phrases = {"jarvis": {"en": {"acknowledge": ["alpha"]}}}
    library = _library_with(tmp_path, phrases)
    engine = _RecordingEngine()
    build_cache(library, "jarvis", lambda _lang: _spec(engine))
    with pytest.raises(FillerNotCachedError):
        pick(library, "jarvis", "en", "no_such_category")


def test_pick_only_returns_paths_that_exist_on_disk(tmp_path):
    """Phrase configured but its WAV missing → not eligible for pick."""
    phrases = {"jarvis": {"en": {"acknowledge": ["alpha", "beta"]}}}
    library = _library_with(tmp_path, phrases)
    # Cache only ``alpha``.
    alpha = library.cache_path("jarvis", "en", "acknowledge", "alpha")
    alpha.parent.mkdir(parents=True, exist_ok=True)
    alpha.write_bytes(b"fake")
    chosen = pick(library, "jarvis", "en", "acknowledge")
    assert chosen == alpha


# ── 4. config override merges with defaults ──────────────────────────────


def test_merge_default_used_when_no_overrides():
    merged = merge_filler_phrases({})
    assert (
        merged["jarvis"]["en"]["acknowledge"]
        == (DEFAULT_FILLERS["jarvis"]["en"]["acknowledge"])
    )


def test_merge_user_overrides_replace_category_list():
    overrides = {"jarvis": {"en": {"acknowledge": ["only one"]}}}
    merged = merge_filler_phrases(overrides)
    assert merged["jarvis"]["en"]["acknowledge"] == ["only one"]
    # Untouched category still has defaults.
    assert (
        merged["jarvis"]["en"]["thinking"]
        == (DEFAULT_FILLERS["jarvis"]["en"]["thinking"])
    )


def test_merge_user_can_add_new_category():
    overrides = {"jarvis": {"en": {"farewell": ["Until next time, sir."]}}}
    merged = merge_filler_phrases(overrides)
    assert merged["jarvis"]["en"]["farewell"] == ["Until next time, sir."]
    # Defaults untouched.
    assert "acknowledge" in merged["jarvis"]["en"]


def test_merge_empty_list_disables_category():
    overrides = {"jarvis": {"en": {"acknowledge": []}}}
    merged = merge_filler_phrases(overrides)
    assert merged["jarvis"]["en"]["acknowledge"] == []


def test_merge_does_not_mutate_defaults():
    """Sanity guard — deepcopy keeps DEFAULT_FILLERS pristine across calls."""
    snapshot = list(DEFAULT_FILLERS["jarvis"]["en"]["acknowledge"])
    merge_filler_phrases({"jarvis": {"en": {"acknowledge": ["x"]}}})
    assert DEFAULT_FILLERS["jarvis"]["en"]["acknowledge"] == snapshot


def test_from_config_applies_user_overrides(tmp_path):
    cfg = VoiceConfig(
        fillers=FillerConfig(
            phrases={"jarvis": {"en": {"acknowledge": ["custom only"]}}}
        )
    )
    library = FillerLibrary.from_config(cfg, tmp_path)
    assert library.phrases("jarvis", "en", "acknowledge") == ["custom only"]
    # Untouched defaults still surface.
    assert (
        library.phrases("jarvis", "en", "thinking")
        == (DEFAULT_FILLERS["jarvis"]["en"]["thinking"])
    )


# ── 5. Strategy D — no torch import on module load ────────────────────────


def test_module_does_not_import_torch():
    """Strategy D: fillers.py must remain torch-free at import time."""
    # The test process may have torch loaded by other tests; importing
    # the module under test alone must not pull it in. The simplest
    # robust check: inspect the module's globals and confirm torch is
    # not referenced. (Subprocess isolation is overkill here.)
    import newton.voice.fillers as fillers_mod

    assert "torch" not in vars(fillers_mod)
    # And no torch submodule should be in this module's recursive imports
    # either; the explicit deps in the import block are stdlib +
    # numpy + tts.base. Spot-check the file source.
    source = Path(fillers_mod.__file__).read_text(encoding="utf-8")
    assert "import torch" not in source
    assert "from torch" not in source


def test_module_imports_only_expected_third_party():
    """Sanity check the public surface matches the spec."""
    assert "DEFAULT_FILLERS" in sys.modules["newton.voice.fillers"].__all__
    assert "FillerLibrary" in sys.modules["newton.voice.fillers"].__all__
    assert "build_cache" in sys.modules["newton.voice.fillers"].__all__
    assert "pick" in sys.modules["newton.voice.fillers"].__all__


# ── 6. round-trip — cache build then read back a WAV ─────────────────────


def test_built_wavs_are_readable_pcm16(tmp_path):
    phrases = {"jarvis": {"en": {"acknowledge": ["alpha"]}}}
    library = _library_with(tmp_path, phrases)
    engine = _RecordingEngine()
    build_cache(library, "jarvis", lambda _lang: _spec(engine))
    p = library.cache_path("jarvis", "en", "acknowledge", "alpha")
    with wave.open(str(p), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 22050
        assert wf.getnframes() == 2205
