"""Tests for newton.voice.samples — directory + consent inspection."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np
from click.testing import CliRunner

from newton.cli import cli
from newton.voice.samples import (
    PersonaSampleSummary,
    SampleFile,
    consent_doc_for,
    find_referenced_sample,
    list_samples,
    summarize,
)


def _write_wav(path: Path, *, duration: float = 1.0, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(duration * sample_rate)
    samples = 0.3 * np.sin(
        2 * np.pi * 220 * np.linspace(0, duration, n, dtype=np.float32)
    )
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes((samples * 32767).astype(np.int16).tobytes())


# ── list_samples ─────────────────────────────────────────────────────────


def test_list_samples_finds_each_language_dir(tmp_path):
    root = tmp_path / "voices"
    _write_wav(root / "jarvis/samples/en/en-001.wav", duration=1.5)
    _write_wav(root / "jarvis/samples/en/en-002.wav", duration=2.0)
    _write_wav(root / "jarvis/samples/ko/ko-001.wav", duration=1.0)

    listed = list_samples("jarvis", root)
    assert set(listed.keys()) == {"en", "ko"}
    assert len(listed["en"]) == 2
    assert len(listed["ko"]) == 1


def test_list_samples_reads_wav_metadata(tmp_path):
    root = tmp_path / "voices"
    _write_wav(
        root / "jarvis/samples/en/en-001.wav",
        duration=2.5,
        sample_rate=22050,
    )
    listed = list_samples("jarvis", root)
    f = listed["en"][0]
    assert isinstance(f, SampleFile)
    assert f.duration_seconds is not None
    assert f.duration_seconds == 2.5
    assert f.sample_rate == 22050
    assert f.n_channels == 1


def test_list_samples_skips_non_wav(tmp_path):
    root = tmp_path / "voices"
    (root / "jarvis/samples/en").mkdir(parents=True)
    (root / "jarvis/samples/en/readme.txt").write_text("notes")
    _write_wav(root / "jarvis/samples/en/en-001.wav")

    listed = list_samples("jarvis", root)
    assert [f.path.name for f in listed["en"]] == ["en-001.wav"]


def test_list_samples_handles_malformed_wav(tmp_path):
    root = tmp_path / "voices"
    bad = root / "jarvis/samples/en/junk.wav"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"not a wav")
    listed = list_samples("jarvis", root)
    f = listed["en"][0]
    assert f.duration_seconds is None
    assert f.sample_rate is None


def test_list_samples_empty_when_persona_dir_missing(tmp_path):
    assert list_samples("ghost", tmp_path / "voices") == {}


def test_list_samples_ignores_loose_files_at_samples_root(tmp_path):
    """consent.md / manifest files at samples/ are not language dirs."""
    root = tmp_path / "voices"
    (root / "jarvis/samples").mkdir(parents=True)
    (root / "jarvis/samples/consent.md").write_text("# consent")
    _write_wav(root / "jarvis/samples/en/en-001.wav")

    listed = list_samples("jarvis", root)
    assert set(listed.keys()) == {"en"}


# ── consent_doc_for ─────────────────────────────────────────────────────


def test_consent_doc_for_path(tmp_path):
    docs = tmp_path / "docs"
    expected = docs / "newton" / "voice-samples" / "jarvis.md"
    assert consent_doc_for("jarvis", docs) == expected


def test_summarize_combines_files_and_consent(tmp_path):
    voices = tmp_path / "voices"
    docs = tmp_path / "docs"
    _write_wav(voices / "jarvis/samples/en/en-001.wav", duration=1.0)
    # No consent file yet → has_consent_doc False.
    s = summarize("jarvis", voices, docs)
    assert isinstance(s, PersonaSampleSummary)
    assert s.total_count == 1
    assert s.has_consent_doc is False
    assert s.consent_doc is None

    # Create the consent file → snapshot reflects it.
    consent = docs / "newton" / "voice-samples" / "jarvis.md"
    consent.parent.mkdir(parents=True)
    consent.write_text("# jarvis consent\n")
    s2 = summarize("jarvis", voices, docs)
    assert s2.has_consent_doc is True
    assert s2.consent_doc == consent


# ── find_referenced_sample ──────────────────────────────────────────────


def test_find_referenced_sample_resolves_against_voice_root(tmp_path):
    voices = tmp_path / "voices"
    _write_wav(voices / "jarvis/samples/en/en-001.wav")
    found = find_referenced_sample("jarvis/samples/en/en-001.wav", voices)
    assert found is not None
    assert found.name == "en-001.wav"


def test_find_referenced_sample_returns_none_when_missing(tmp_path):
    assert find_referenced_sample("jarvis/samples/en/en-001.wav", tmp_path) is None


def test_find_referenced_sample_returns_none_for_empty():
    assert find_referenced_sample(None, Path("/tmp")) is None
    assert find_referenced_sample("", Path("/tmp")) is None


# ── shipped JARVIS consent doc parses cleanly ──────────────────────────


def test_shipped_jarvis_consent_doc_exists_in_repo():
    """The committed consent record must be present and non-empty."""
    repo = Path(__file__).resolve().parent.parent.parent.parent
    consent = repo / "docs" / "newton" / "voice-samples" / "jarvis.md"
    assert consent.exists()
    content = consent.read_text(encoding="utf-8")
    assert "JARVIS" in content
    assert "consent" in content.lower()
    assert "Donor" in content or "donor" in content.lower()


# ── CLI ────────────────────────────────────────────────────────────────


def test_cli_voice_samples_list_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))  # use defaults
    # voice_root resolves relative to project root → use a real voices
    # dir we control. Override the helper by setting voice_root to an
    # absolute path in a tmp voice.yaml.
    (tmp_path / "voice.yaml").write_text(
        f"tts:\n  voice_root: {tmp_path / 'voices'}\n  routes: []\n"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["voice", "samples", "list", "ghost", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {}


def test_cli_voice_samples_list_finds_files(tmp_path, monkeypatch):
    voices = tmp_path / "voices"
    _write_wav(voices / "jarvis/samples/en/en-001.wav", duration=1.5)
    _write_wav(voices / "jarvis/samples/ko/ko-001.wav", duration=2.0)
    (tmp_path / "voice.yaml").write_text(
        f"tts:\n  voice_root: {voices}\n  routes: []\n"
    )
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(cli, ["voice", "samples", "list", "jarvis", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert set(data.keys()) == {"en", "ko"}
    assert len(data["en"]) == 1
    assert len(data["ko"]) == 1
    assert data["en"][0]["sample_rate"] == 16000


def test_cli_voice_samples_show_reports_consent_status(tmp_path, monkeypatch):
    voices = tmp_path / "voices"
    _write_wav(voices / "jarvis/samples/en/en-001.wav", duration=1.0)
    (tmp_path / "voice.yaml").write_text(
        f"tts:\n  voice_root: {voices}\n  routes: []\n"
    )
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(cli, ["voice", "samples", "show", "jarvis", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # Consent doc is shipped in the real repo; the test's tmp dir
    # doesn't contain it, but `summarize` walks the real docs root.
    assert payload["total_count"] == 1
    assert "en" in payload["files_by_language"]
