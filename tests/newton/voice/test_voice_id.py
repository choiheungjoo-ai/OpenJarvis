"""Tests for newton.voice.voice_id — backends + VoiceIdService + CLI.

These tests run on the default install (no torch / no resemblyzer).
The real-encoder code paths are exercised only by the ``voice_id``
marker, which is skipped when the optional extra is absent.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from newton.cli import cli
from newton.db import get_session, init_db
from newton.models.user import User
from newton.voice.config import VoiceIdConfig
from newton.voice.voice_id import (
    EMBEDDING_DIM,
    FakeVoiceEncoderBackend,
    ResemblyzerBackend,
    VoiceEncoderBackend,
    VoiceIdError,
    VoiceIdService,
    build_backend,
    bytes_to_embedding,
    cosine_similarity,
    embedding_to_bytes,
)

# ── helpers ──────────────────────────────────────────────────────────────


def _seed_user(user_id: str, display_name: str | None = None) -> None:
    with get_session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, display_name=display_name or user_id.title()))


def _write_wav(tmp_path: Path, name: str, payload: bytes) -> Path:
    """Write deterministic bytes — Fake backend keys off file bytes only."""
    p = tmp_path / name
    p.write_bytes(payload)
    return p


@pytest.fixture
def fake_cfg() -> VoiceIdConfig:
    return VoiceIdConfig(backend="fake", device="cpu", threshold=0.75)


# ── ABC + backend factory ────────────────────────────────────────────────


def test_voice_encoder_backend_is_abstract():
    with pytest.raises(TypeError):
        VoiceEncoderBackend()  # type: ignore[abstract]


def test_build_backend_fake(fake_cfg):
    be = build_backend(fake_cfg)
    assert isinstance(be, FakeVoiceEncoderBackend)
    assert be.name == "fake"


def test_build_backend_resemblyzer_does_not_import_torch():
    cfg = VoiceIdConfig(backend="resemblyzer", device="cpu")
    be = build_backend(cfg)
    assert isinstance(be, ResemblyzerBackend)
    # Construction must NOT have loaded the encoder.
    assert be._encoder is None  # noqa: SLF001


def test_build_backend_unknown():
    cfg = VoiceIdConfig(backend="bogus")
    with pytest.raises(VoiceIdError, match="unknown voice-id backend"):
        build_backend(cfg)


# ── FakeVoiceEncoderBackend ──────────────────────────────────────────────


def test_fake_backend_embedding_shape_and_unit_norm(tmp_path):
    be = FakeVoiceEncoderBackend()
    p = _write_wav(tmp_path, "a.wav", b"\x01\x02\x03\x04" * 32)
    vec = be.embed(p)
    assert vec.dtype == np.float32
    assert vec.shape == (EMBEDDING_DIM,)
    assert float(np.linalg.norm(vec)) == pytest.approx(1.0, abs=1e-5)


def test_fake_backend_deterministic_same_bytes(tmp_path):
    be = FakeVoiceEncoderBackend()
    p1 = _write_wav(tmp_path, "x.wav", b"hello-voice")
    p2 = _write_wav(tmp_path, "y.wav", b"hello-voice")
    np.testing.assert_array_equal(be.embed(p1), be.embed(p2))


def test_fake_backend_different_bytes_different_vector(tmp_path):
    be = FakeVoiceEncoderBackend()
    p1 = _write_wav(tmp_path, "a.wav", b"alex")
    p2 = _write_wav(tmp_path, "b.wav", b"stella")
    sim = cosine_similarity(be.embed(p1), be.embed(p2))
    # Independent hashes ⇒ near-orthogonal, definitely < 0.9.
    assert sim < 0.9


def test_fake_backend_missing_file(tmp_path):
    be = FakeVoiceEncoderBackend()
    with pytest.raises(FileNotFoundError):
        be.embed(tmp_path / "nope.wav")


# ── ResemblyzerBackend (lazy) ────────────────────────────────────────────


def test_resemblyzer_backend_lazy_loader_called_on_first_embed(tmp_path):
    calls = {"n": 0}

    class _StubEncoder:
        def embed_utterance(self, _wav):
            return np.ones(EMBEDDING_DIM, dtype=np.float32) / np.sqrt(EMBEDDING_DIM)

    def fake_loader(_device):
        calls["n"] += 1
        return _StubEncoder()

    be = ResemblyzerBackend(device="cpu", loader=fake_loader)
    assert calls["n"] == 0

    # Patch ``preprocess_wav`` in the resemblyzer module so we don't
    # need the real library installed. The lazy import inside ``embed``
    # picks the stubbed module up via sys.modules.
    import types

    stub_module = types.ModuleType("resemblyzer")
    stub_module.preprocess_wav = lambda _p: np.zeros(16000, dtype=np.float32)
    sys.modules["resemblyzer"] = stub_module
    try:
        wav = _write_wav(tmp_path, "a.wav", b"\x00\x01")
        vec = be.embed(wav)
        assert calls["n"] == 1
        assert vec.shape == (EMBEDDING_DIM,)
        # Cached on subsequent calls.
        be.embed(wav)
        assert calls["n"] == 1
    finally:
        sys.modules.pop("resemblyzer", None)


def test_resemblyzer_backend_missing_file(tmp_path):
    be = ResemblyzerBackend(device="cpu", loader=lambda _d: object())
    with pytest.raises(FileNotFoundError):
        be.embed(tmp_path / "missing.wav")


# ── Strategy D: importing voice_id must not pull in torch ────────────────


def test_voice_id_module_does_not_import_torch_or_resemblyzer():
    """A fresh subprocess imports newton.voice.voice_id and asserts no torch."""
    code = textwrap.dedent(
        """
        import sys
        import newton.voice.voice_id  # noqa: F401
        assert "torch" not in sys.modules, sorted(sys.modules)
        assert "resemblyzer" not in sys.modules, sorted(sys.modules)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# ── bytes ↔ embedding round-trip ─────────────────────────────────────────


def test_embedding_to_bytes_roundtrip():
    vec = np.linspace(-1.0, 1.0, EMBEDDING_DIM, dtype=np.float32)
    blob = embedding_to_bytes(vec)
    assert isinstance(blob, bytes)
    assert len(blob) == EMBEDDING_DIM * 4  # float32
    recovered = bytes_to_embedding(blob)
    np.testing.assert_array_equal(recovered, vec)


def test_embedding_to_bytes_rejects_non_1d():
    with pytest.raises(ValueError, match="1-D"):
        embedding_to_bytes(np.zeros((2, 4), dtype=np.float32))


# ── cosine_similarity ────────────────────────────────────────────────────


def test_cosine_similarity_identity_and_orthogonal():
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    assert cosine_similarity(a, a) == pytest.approx(1.0)
    assert cosine_similarity(a, b) == pytest.approx(0.0)


# ── VoiceIdService.register ──────────────────────────────────────────────


def test_register_stores_bytes(isolated_db, fake_cfg, tmp_path):
    init_db()
    _seed_user("sir")
    wav = _write_wav(tmp_path, "sir.wav", b"sir-voice-1")

    with get_session() as s:
        svc = VoiceIdService(s, FakeVoiceEncoderBackend(), fake_cfg)
        svc.register("sir", wav)

    with get_session() as s:
        user = s.get(User, "sir")
        assert user.voice_embedding is not None
        vec = bytes_to_embedding(user.voice_embedding)
        assert vec.shape == (EMBEDDING_DIM,)
        assert vec.dtype == np.float32


def test_register_is_idempotent_overwrite(isolated_db, fake_cfg, tmp_path):
    init_db()
    _seed_user("sir")
    wav1 = _write_wav(tmp_path, "v1.wav", b"version-one")
    wav2 = _write_wav(tmp_path, "v2.wav", b"version-two")

    with get_session() as s:
        svc = VoiceIdService(s, FakeVoiceEncoderBackend(), fake_cfg)
        svc.register("sir", wav1)

    with get_session() as s:
        first = bytes(s.get(User, "sir").voice_embedding)

    with get_session() as s:
        svc = VoiceIdService(s, FakeVoiceEncoderBackend(), fake_cfg)
        svc.register("sir", wav2)

    with get_session() as s:
        second = bytes(s.get(User, "sir").voice_embedding)
        assert second != first  # overwritten, not appended


def test_register_unknown_user(isolated_db, fake_cfg, tmp_path):
    init_db()
    wav = _write_wav(tmp_path, "ghost.wav", b"no-such-user")
    with get_session() as s:
        svc = VoiceIdService(s, FakeVoiceEncoderBackend(), fake_cfg)
        with pytest.raises(VoiceIdError, match="unknown user"):
            svc.register("ghost", wav)


# ── VoiceIdService.identify ──────────────────────────────────────────────


def test_identify_returns_registered_user(isolated_db, fake_cfg, tmp_path):
    init_db()
    _seed_user("sir")
    wav = _write_wav(tmp_path, "sir.wav", b"sir-voice")

    with get_session() as s:
        svc = VoiceIdService(s, FakeVoiceEncoderBackend(), fake_cfg)
        svc.register("sir", wav)

    with get_session() as s:
        svc = VoiceIdService(s, FakeVoiceEncoderBackend(), fake_cfg)
        user_id, score = svc.identify(wav)

    assert user_id == "sir"
    assert score == pytest.approx(1.0, abs=1e-5)


def test_identify_below_threshold_returns_none(isolated_db, tmp_path):
    # Push threshold to 0.99 so the fake-encoder's natural cross-clip
    # similarity (≈ 0) never qualifies.
    cfg = VoiceIdConfig(backend="fake", threshold=0.99)
    init_db()
    _seed_user("sir")
    enrolled = _write_wav(tmp_path, "enroll.wav", b"sir-voice")
    probe = _write_wav(tmp_path, "probe.wav", b"someone-else-entirely")

    with get_session() as s:
        VoiceIdService(s, FakeVoiceEncoderBackend(), cfg).register("sir", enrolled)
    with get_session() as s:
        user_id, score = VoiceIdService(s, FakeVoiceEncoderBackend(), cfg).identify(
            probe
        )

    assert user_id is None
    assert score < cfg.threshold


def test_identify_no_users_registered(isolated_db, fake_cfg, tmp_path):
    init_db()
    _seed_user("sir")  # exists but no embedding
    wav = _write_wav(tmp_path, "probe.wav", b"anyone")

    with get_session() as s:
        user_id, score = VoiceIdService(
            s, FakeVoiceEncoderBackend(), fake_cfg
        ).identify(wav)
    assert user_id is None
    assert score == 0.0


def test_identify_picks_best_across_multiple_users(isolated_db, fake_cfg, tmp_path):
    init_db()
    _seed_user("sir")
    _seed_user("gf")
    sir_wav = _write_wav(tmp_path, "sir.wav", b"sir-sample")
    gf_wav = _write_wav(tmp_path, "gf.wav", b"gf-sample")

    with get_session() as s:
        be = FakeVoiceEncoderBackend()
        VoiceIdService(s, be, fake_cfg).register("sir", sir_wav)
        VoiceIdService(s, be, fake_cfg).register("gf", gf_wav)

    # Probing with sir's sample picks sir.
    with get_session() as s:
        user_id, score = VoiceIdService(
            s, FakeVoiceEncoderBackend(), fake_cfg
        ).identify(sir_wav)
    assert user_id == "sir"
    assert score == pytest.approx(1.0, abs=1e-5)

    # Probing with gf's sample picks gf.
    with get_session() as s:
        user_id, score = VoiceIdService(
            s, FakeVoiceEncoderBackend(), fake_cfg
        ).identify(gf_wav)
    assert user_id == "gf"
    assert score == pytest.approx(1.0, abs=1e-5)


# ── CLI ─────────────────────────────────────────────────────────────────


def _force_fake_backend(monkeypatch) -> None:
    """Make ``VoiceIdService.from_config`` build the fake backend.

    Patch the YAML loader so the CLI's default service uses fake — no
    torch import, deterministic vectors.
    """
    from newton.voice import voice_id as voice_id_module

    def fake_loader():
        from newton.voice.config import VoiceConfig

        cfg = VoiceConfig()
        cfg = cfg.model_copy(
            update={"voice_id": VoiceIdConfig(backend="fake", threshold=0.75)}
        )
        return cfg

    monkeypatch.setattr(voice_id_module, "load_voice_config", fake_loader)


def test_cli_register_json(isolated_db, runner, monkeypatch, tmp_path):
    init_db()
    _seed_user("sir")
    _force_fake_backend(monkeypatch)
    wav = _write_wav(tmp_path, "sir.wav", b"sir-cli")

    result = runner.invoke(cli, ["voice", "id", "register", "sir", str(wav), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"user_id": "sir", "registered": True}

    with get_session() as s:
        assert s.get(User, "sir").voice_embedding is not None


def test_cli_register_unknown_user_exits_nonzero(
    isolated_db, runner, monkeypatch, tmp_path
):
    init_db()
    _force_fake_backend(monkeypatch)
    wav = _write_wav(tmp_path, "ghost.wav", b"ghost")

    result = runner.invoke(
        cli, ["voice", "id", "register", "ghost", str(wav), "--json"]
    )
    assert result.exit_code == 1
    assert "unknown user" in result.output


def test_cli_verify_json_match(isolated_db, runner, monkeypatch, tmp_path):
    init_db()
    _seed_user("sir")
    _force_fake_backend(monkeypatch)
    wav = _write_wav(tmp_path, "sir.wav", b"sir-verify")

    reg = runner.invoke(cli, ["voice", "id", "register", "sir", str(wav), "--json"])
    assert reg.exit_code == 0, reg.output

    result = runner.invoke(cli, ["voice", "id", "verify", str(wav), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["user_id"] == "sir"
    assert payload["confidence"] == pytest.approx(1.0, abs=1e-5)


def test_cli_verify_json_no_match(isolated_db, runner, monkeypatch, tmp_path):
    """Threshold rejects an unenrolled probe."""
    from newton.voice import voice_id as voice_id_module

    def loader_high_threshold():
        from newton.voice.config import VoiceConfig

        cfg = VoiceConfig()
        return cfg.model_copy(
            update={"voice_id": VoiceIdConfig(backend="fake", threshold=0.99)}
        )

    monkeypatch.setattr(voice_id_module, "load_voice_config", loader_high_threshold)

    init_db()
    _seed_user("sir")
    enrolled = _write_wav(tmp_path, "sir.wav", b"sir-enrolled")
    other = _write_wav(tmp_path, "other.wav", b"unrelated-noise")

    reg = runner.invoke(
        cli, ["voice", "id", "register", "sir", str(enrolled), "--json"]
    )
    assert reg.exit_code == 0, reg.output

    result = runner.invoke(cli, ["voice", "id", "verify", str(other), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["user_id"] is None
    assert 0.0 <= payload["confidence"] < 0.99
