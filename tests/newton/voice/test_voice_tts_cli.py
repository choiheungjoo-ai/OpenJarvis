"""Tests for `newton voice tts` — zero-shot cloning CLI scaffold.

The CLI invokes the TTSRouter + a real engine instance via
``default_engine_factory``. We don't want to actually load qwen-tts /
chatterbox here, so the tests monkeypatch ``default_engine_factory``
to return a stubbed engine. That covers the routing seam end-to-end
without any model dep.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np
from click.testing import CliRunner

from newton.cli import cli
from newton.voice.tts.base import TTS, TTSResult

# ── helpers ──────────────────────────────────────────────────────────────


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


def _isolated_voice_dir(tmp_path: Path) -> tuple[Path, Path]:
    """Build a config dir + voice dir with one jarvis/ko sample."""
    voices = tmp_path / "voices"
    _write_wav(voices / "jarvis/samples/ko/ko-001.wav", duration=1.5)
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "voice.yaml").write_text(
        "tts:\n"
        f"  voice_root: {voices}\n"
        "  routes:\n"
        "    - persona: jarvis\n"
        "      language: ko\n"
        "      engine: qwen3_tts_1.7b\n"
        "      voice_reference: jarvis/samples/ko/ko-001.wav\n"
    )
    return cfg_dir, voices


class _StubEngine(TTS):
    """A TTS engine that records calls and emits a short tone."""

    name = "qwen3_tts_1.7b"
    last_call: dict | None = None

    def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice_reference=None,
    ) -> TTSResult:
        _StubEngine.last_call = {
            "text": text,
            "language": language,
            "voice_reference": (
                str(voice_reference) if voice_reference is not None else None
            ),
        }
        # 0.5 s at 22050 Hz — passes save_wav round-trip.
        n = 11025
        wave_arr = 0.3 * np.sin(
            2 * np.pi * 220 * np.linspace(0, 0.5, n, dtype=np.float32)
        )
        return TTSResult(audio=wave_arr, sample_rate=22050)


def _stub_factory(name: str) -> TTS:  # noqa: ARG001
    return _StubEngine()


# ── happy path ──────────────────────────────────────────────────────────


def test_voice_tts_happy_path(tmp_path, monkeypatch):
    cfg_dir, voices = _isolated_voice_dir(tmp_path)
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr("newton.voice.tts.router.default_engine_factory", _stub_factory)
    monkeypatch.setattr("newton.cli._voice_root_path", lambda: voices)

    out = tmp_path / "out.wav"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "voice",
            "tts",
            "--persona",
            "jarvis",
            "--lang",
            "ko",
            "--text",
            "안녕하십니까, sir.",
            "--out",
            str(out),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["engine"] == "qwen3_tts_1.7b"
    assert payload["voice_reference"].endswith("ko-001.wav")
    assert payload["out"] == str(out)
    assert payload["sample_rate"] == 22050
    assert out.exists()

    # Engine got the right text + sample.
    last = _StubEngine.last_call
    assert last is not None
    assert last["text"] == "안녕하십니까, sir."
    assert last["language"] == "ko"
    assert last["voice_reference"].endswith("ko-001.wav")


# ── routing failures ────────────────────────────────────────────────────


def test_voice_tts_no_route_errors_clearly(tmp_path, monkeypatch):
    cfg_dir, voices = _isolated_voice_dir(tmp_path)
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr("newton.voice.tts.router.default_engine_factory", _stub_factory)
    monkeypatch.setattr("newton.cli._voice_root_path", lambda: voices)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "voice",
            "tts",
            "--persona",
            "ghost",
            "--lang",
            "en",
            "--text",
            "hello",
        ],
    )
    assert result.exit_code == 1
    assert "no TTS route" in result.output


# ── missing sample short-circuits before model load ────────────────────


def test_voice_tts_missing_sample_fails_before_loader_runs(tmp_path, monkeypatch):
    voices = tmp_path / "voices"
    voices.mkdir()
    # voice.yaml points at a non-existent file.
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "voice.yaml").write_text(
        "tts:\n"
        f"  voice_root: {voices}\n"
        "  routes:\n"
        "    - persona: jarvis\n"
        "      language: ko\n"
        "      engine: qwen3_tts_1.7b\n"
        "      voice_reference: jarvis/samples/ko/ko-001.wav\n"
    )
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr("newton.cli._voice_root_path", lambda: voices)

    boom = {"called": False}

    def explosive_factory(_name):
        boom["called"] = True
        raise AssertionError("loader must not run when the sample is missing")

    monkeypatch.setattr(
        "newton.voice.tts.router.default_engine_factory", explosive_factory
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["voice", "tts", "--persona", "jarvis", "--lang", "ko", "--text", "hi"],
    )
    assert result.exit_code == 1
    assert "voice sample" in result.output and "not found" in result.output
    # CRITICAL: the engine factory was never invoked.
    assert boom["called"] is False


# ── helpful errors when deps / weights are missing ─────────────────────


def test_voice_tts_module_not_found_message(tmp_path, monkeypatch):
    cfg_dir, voices = _isolated_voice_dir(tmp_path)
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr("newton.cli._voice_root_path", lambda: voices)

    class _ModuleMissing(TTS):
        name = "qwen3_tts_1.7b"

        def synthesize(self, *_args, **_kwargs):
            raise ModuleNotFoundError("No module named 'qwen_tts'", name="qwen_tts")

    monkeypatch.setattr(
        "newton.voice.tts.router.default_engine_factory",
        lambda _name: _ModuleMissing(),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["voice", "tts", "--persona", "jarvis", "--lang", "ko", "--text", "hi"]
    )
    assert result.exit_code == 1
    assert "qwen_tts not installed" in result.output
    assert "voice-cloning-verification.md" in result.output


def test_voice_tts_file_not_found_message(tmp_path, monkeypatch):
    cfg_dir, voices = _isolated_voice_dir(tmp_path)
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr("newton.cli._voice_root_path", lambda: voices)

    class _WeightsMissing(TTS):
        name = "qwen3_tts_1.7b"

        def synthesize(self, *_args, **_kwargs):
            raise FileNotFoundError(
                "Qwen3-TTS 1.7B weights not found at /tmp/foo. "
                "Run scripts/newton/download-models.sh first."
            )

    monkeypatch.setattr(
        "newton.voice.tts.router.default_engine_factory",
        lambda _name: _WeightsMissing(),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["voice", "tts", "--persona", "jarvis", "--lang", "ko", "--text", "hi"]
    )
    assert result.exit_code == 1
    assert "weights not found" in result.output
    assert "voice-cloning-verification.md" in result.output


# ── default output path when --out omitted ─────────────────────────────


def test_voice_tts_default_out_path_is_temp(tmp_path, monkeypatch):
    cfg_dir, voices = _isolated_voice_dir(tmp_path)
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr("newton.voice.tts.router.default_engine_factory", _stub_factory)
    monkeypatch.setattr("newton.cli._voice_root_path", lambda: voices)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "voice",
            "tts",
            "--persona",
            "jarvis",
            "--lang",
            "ko",
            "--text",
            "안녕",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    out = Path(payload["out"])
    assert out.parent == Path("/tmp")
    assert out.name.startswith("newton-voice-")
    assert out.exists()
    out.unlink()
