"""Voice ID — speaker enrollment + recognition (block 5 step 5.9).

Turns a short WAV recording of a user's voice into a 256-dim embedding
and stores it as bytes in ``users.voice_embedding``. Later, an incoming
clip can be embedded and cosine-compared against every registered user;
the best match above ``threshold`` is returned.

Strategy D
----------
Resemblyzer pulls in torch. The default install must stay torch-free,
so ``ResemblyzerBackend`` lazy-imports resemblyzer inside its loader,
never at module-import time. The fake backend has no heavy deps and
is what the test suite uses.

Backend selection
-----------------
Driven by ``VoiceIdConfig.backend`` — ``resemblyzer`` for the real
encoder (needs the ``voice-id`` extra) or ``fake`` for deterministic
hash-based vectors. A simple factory inside this module dispatches
on the name; no module-level discovery because we only ever ship the
two backends and a registry would obscure the device/sample-rate plumbing.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.models import User
from newton.voice.config import VoiceIdConfig, load_voice_config

log = logging.getLogger(__name__)

# Resemblyzer's encoder produces 256-dim float32 embeddings, normalised
# to unit norm. ``FakeVoiceEncoderBackend`` matches that contract so
# tests can swap freely without dimension drift.
EMBEDDING_DIM = 256


class VoiceIdError(RuntimeError):
    """Raised when voice-ID enrollment / identification fails."""


# ─────────────────────────────────────────────────────────────────────────────
# Backend ABC
# ─────────────────────────────────────────────────────────────────────────────


class VoiceEncoderBackend(ABC):
    """One way to turn a WAV file into a 256-dim float32 speaker embedding."""

    name: str

    @abstractmethod
    def embed(self, wav_path: str | Path) -> np.ndarray:
        """Return the unit-norm 256-dim float32 embedding for ``wav_path``."""
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# Resemblyzer backend (lazy — Strategy D)
# ─────────────────────────────────────────────────────────────────────────────


def _default_resemblyzer_loader(device: str) -> Any:
    """Real loader — imports resemblyzer and constructs ``VoiceEncoder``.

    Kept module-level so tests can monkeypatch a stub loader without
    touching the import side. ``device`` comes from config.
    """
    from resemblyzer import VoiceEncoder  # noqa: PLC0415 — lazy

    return VoiceEncoder(device)


class ResemblyzerBackend(VoiceEncoderBackend):
    """Resemblyzer ``VoiceEncoder`` wrapper.

    Construction is cheap (no model load); the encoder loads on first
    ``embed`` call. Resemblyzer's ``preprocess_wav`` handles resampling
    and pre-emphasis; we don't second-guess it.
    """

    name = "resemblyzer"

    def __init__(
        self,
        device: str = "cpu",
        loader: Callable[[str], Any] = _default_resemblyzer_loader,
    ) -> None:
        self.device = device
        self._encoder: Any = None
        self._loader = loader

    def _ensure_loaded(self) -> None:
        if self._encoder is not None:
            return
        log.info("loading resemblyzer VoiceEncoder (device=%s)", self.device)
        self._encoder = self._loader(self.device)

    def embed(self, wav_path: str | Path) -> np.ndarray:
        path = Path(wav_path)
        if not path.exists():
            raise FileNotFoundError(f"voice sample not found: {path}")
        self._ensure_loaded()
        # ``preprocess_wav`` accepts a path and returns a float32 array
        # at the encoder's expected sample rate; ``embed_utterance``
        # returns a 256-dim unit-norm float32 vector.
        from resemblyzer import preprocess_wav  # noqa: PLC0415 — lazy

        wav = preprocess_wav(str(path))
        vec = self._encoder.embed_utterance(wav)
        return np.asarray(vec, dtype=np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# Fake backend (tests / dev)
# ─────────────────────────────────────────────────────────────────────────────


class FakeVoiceEncoderBackend(VoiceEncoderBackend):
    """Deterministic pseudo-encoder driven by a hash of file bytes.

    Same file → same vector. Different files → different vectors. No
    semantic meaning. Vectors are L2-normalised so cosine similarity
    behaves like the real encoder's (i.e. identity = 1.0, orthogonal ≈ 0).
    """

    name = "fake"

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim

    def embed(self, wav_path: str | Path) -> np.ndarray:
        path = Path(wav_path)
        if not path.exists():
            raise FileNotFoundError(f"voice sample not found: {path}")
        digest_seed = hashlib.sha256(path.read_bytes()).digest()
        raw = bytearray()
        counter = 0
        while len(raw) < self._dim * 4:
            raw.extend(hashlib.sha256(bytes([counter]) + digest_seed).digest())
            counter += 1
        vals = np.frombuffer(bytes(raw[: self._dim * 4]), dtype=np.uint32)
        # Map to (-1, 1) floats.
        floats = (vals.astype(np.float64) / (2**32 - 1)) * 2.0 - 1.0
        vec = floats.astype(np.float32)
        norm = float(np.linalg.norm(vec)) or 1.0
        return vec / norm


# ─────────────────────────────────────────────────────────────────────────────
# Backend factory
# ─────────────────────────────────────────────────────────────────────────────


def build_backend(config: VoiceIdConfig) -> VoiceEncoderBackend:
    """Construct the backend named in ``config.backend``.

    Kept explicit (a small dispatch) over module-discovery because we
    only ship two backends and each takes different ctor args.
    """
    if config.backend == "resemblyzer":
        return ResemblyzerBackend(device=config.device)
    if config.backend == "fake":
        return FakeVoiceEncoderBackend()
    raise VoiceIdError(
        f"unknown voice-id backend {config.backend!r}; expected 'resemblyzer' or 'fake'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Embedding ↔ bytes round-trip
# ─────────────────────────────────────────────────────────────────────────────


def embedding_to_bytes(vec: np.ndarray) -> bytes:
    """Pack a float32 embedding as raw little-endian bytes."""
    arr = np.asarray(vec, dtype=np.float32)
    if arr.ndim != 1:
        raise ValueError(f"embedding must be 1-D, got shape={arr.shape}")
    return arr.tobytes()


def bytes_to_embedding(blob: bytes) -> np.ndarray:
    """Unpack a float32 embedding from raw bytes."""
    return np.frombuffer(blob, dtype=np.float32).copy()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D float32 vectors.

    Both backends emit unit-norm vectors, but normalising again here
    keeps the function honest if a non-normalised vector ever sneaks in.
    """
    na = float(np.linalg.norm(a)) or 1.0
    nb = float(np.linalg.norm(b)) or 1.0
    return float(np.dot(a, b) / (na * nb))


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class VoiceIdService:
    """Enroll users by voice and identify the speaker of a new clip."""

    def __init__(
        self,
        session: Session,
        backend: VoiceEncoderBackend,
        config: VoiceIdConfig,
    ) -> None:
        self._session = session
        self._backend = backend
        self._config = config

    # -- construction ---------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        session: Session,
        config: VoiceIdConfig | None = None,
        backend: VoiceEncoderBackend | None = None,
    ) -> VoiceIdService:
        """Build a service, defaulting backend + config from ``voice.yaml``.

        ``backend`` lets tests inject a fake without round-tripping config.
        """
        cfg = config or load_voice_config().voice_id
        be = backend or build_backend(cfg)
        return cls(session, be, cfg)

    # -- operations -----------------------------------------------------------

    def register(self, user_id: str, audio_path: str | Path) -> None:
        """Compute the user's embedding and store it. Idempotent overwrite.

        Read-before-write: a missing user raises rather than silently
        creating one — registration is an operator action on an
        already-seeded account.
        """
        user = self._session.get(User, user_id)
        if user is None:
            raise VoiceIdError(f"unknown user {user_id!r}")

        vec = self._backend.embed(audio_path)
        user.voice_embedding = embedding_to_bytes(vec)
        self._session.flush()

    def identify(self, audio_path: str | Path) -> tuple[str | None, float]:
        """Return the best-matching user + cosine score for the clip.

        Falls back to ``(None, best_score)`` when the best score is below
        ``threshold``. ``best_score`` is 0.0 when no users have an
        embedding registered yet.
        """
        probe = self._backend.embed(audio_path)

        stmt = select(User).where(User.voice_embedding.is_not(None))
        rows = self._session.execute(stmt).scalars().all()
        if not rows:
            return None, 0.0

        best_user: str | None = None
        best_score = -1.0
        for user in rows:
            blob = user.voice_embedding
            if blob is None:
                # Defensive — the WHERE clause already filters these.
                continue
            stored = bytes_to_embedding(blob)
            score = cosine_similarity(probe, stored)
            if score > best_score:
                best_score = score
                best_user = user.user_id

        if best_score < self._config.threshold:
            return None, max(best_score, 0.0)
        return best_user, best_score


__all__ = [
    "EMBEDDING_DIM",
    "FakeVoiceEncoderBackend",
    "ResemblyzerBackend",
    "VoiceEncoderBackend",
    "VoiceIdError",
    "VoiceIdService",
    "build_backend",
    "bytes_to_embedding",
    "cosine_similarity",
    "embedding_to_bytes",
]
