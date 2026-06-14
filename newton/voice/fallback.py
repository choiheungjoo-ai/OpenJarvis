"""PIN / passphrase auth fallback (block 5 step 5.11).

When Voice ID fails the user's retry profile (block 1's `retry_profile`
column), Newton drops to PIN, then to passphrase. Block 1's schema
already has ``users.pin_hash`` / ``users.passphrase_hash``; this module
is the first consumer.

The shape:

    AuthHasher (ABC)
        .hash(secret: str) -> str
        .verify(secret: str, hashed: str) -> bool

    BcryptAuthHasher
        Lazy ``import bcrypt`` on first call. Tests inject
        :class:`StubAuthHasher` to skip the dep.

    set_pin / set_passphrase / verify_pin / verify_passphrase
        Thin wrappers over the User columns. The hasher is injectable
        so tests can run without bcrypt installed.

No state machine here for the "voice → PIN → passphrase" cascade —
the runtime in a later step orchestrates the order. Step 5.11 just
ships verify primitives + enrollment so the cascade has working
parts to call.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.orm import Session

from newton.models.user import User

log = logging.getLogger(__name__)


class AuthHasher(ABC):
    """How a PIN / passphrase gets hashed and verified."""

    name: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "__abstractmethods__", None):
            return
        if not getattr(cls, "name", None):
            raise TypeError(f"{cls.__name__}: AuthHasher subclass needs a name")

    @abstractmethod
    def hash(self, secret: str) -> str:
        """Return a storage string suitable for ``users.pin_hash`` etc."""

    @abstractmethod
    def verify(self, secret: str, hashed: str) -> bool:
        """True if ``secret`` matches the previously hashed string."""


class BcryptAuthHasher(AuthHasher):
    """``bcrypt`` adapter. Imports the C extension lazily.

    A failed import raises at ``hash`` / ``verify`` time, not at
    module load, so the core stays importable on a fresh checkout
    without the package.
    """

    name = "bcrypt"

    def __init__(self, rounds: int = 12) -> None:
        if rounds < 4 or rounds > 31:
            raise ValueError("bcrypt rounds must be in [4, 31]")
        self.rounds = rounds
        self._bcrypt: Any = None

    def _ensure_loaded(self) -> None:
        if self._bcrypt is not None:
            return
        import bcrypt  # noqa: PLC0415 — lazy

        self._bcrypt = bcrypt

    def hash(self, secret: str) -> str:
        self._ensure_loaded()
        salt = self._bcrypt.gensalt(rounds=self.rounds)
        return self._bcrypt.hashpw(secret.encode("utf-8"), salt).decode("utf-8")

    def verify(self, secret: str, hashed: str) -> bool:
        if not hashed:
            return False
        self._ensure_loaded()
        try:
            return bool(
                self._bcrypt.checkpw(secret.encode("utf-8"), hashed.encode("utf-8"))
            )
        except (ValueError, TypeError) as e:
            log.warning("bcrypt verify failed: %s", e)
            return False


class StubAuthHasher(AuthHasher):
    """Deterministic, *insecure* hasher for tests.

    Prefixes the storage string with ``stub:``; verification is a
    plain equality check after stripping the prefix. Production code
    must never instantiate this; the constructor doesn't guard, but
    every usage in tests is obvious.
    """

    name = "stub"
    _PREFIX = "stub:"

    def hash(self, secret: str) -> str:
        return f"{self._PREFIX}{secret}"

    def verify(self, secret: str, hashed: str) -> bool:
        return hashed == f"{self._PREFIX}{secret}"


# ─────────────────────────────────────────────────────────────────────────────
# enrollment + verification (User column wrappers)
# ─────────────────────────────────────────────────────────────────────────────


def set_pin(
    db_session: Session,
    user_id: str,
    pin: str,
    hasher: AuthHasher,
) -> None:
    """Enroll or replace a user's PIN. Empty PIN raises."""
    pin = pin.strip()
    if not pin:
        raise ValueError("PIN must be non-empty")
    user = db_session.get(User, user_id)
    if user is None:
        raise ValueError(f"unknown user {user_id!r}")
    user.pin_hash = hasher.hash(pin)


def set_passphrase(
    db_session: Session,
    user_id: str,
    passphrase: str,
    hasher: AuthHasher,
) -> None:
    """Enroll or replace a user's passphrase."""
    passphrase = passphrase.strip()
    if not passphrase:
        raise ValueError("passphrase must be non-empty")
    user = db_session.get(User, user_id)
    if user is None:
        raise ValueError(f"unknown user {user_id!r}")
    user.passphrase_hash = hasher.hash(passphrase)


def verify_pin(
    db_session: Session,
    user_id: str,
    pin: str,
    hasher: AuthHasher,
) -> bool:
    """True if ``pin`` matches ``users.pin_hash``. False on any failure."""
    user = db_session.get(User, user_id)
    if user is None or not user.pin_hash:
        return False
    return hasher.verify(pin, user.pin_hash)


def verify_passphrase(
    db_session: Session,
    user_id: str,
    passphrase: str,
    hasher: AuthHasher,
) -> bool:
    """True if ``passphrase`` matches the user's stored hash."""
    user = db_session.get(User, user_id)
    if user is None or not user.passphrase_hash:
        return False
    return hasher.verify(passphrase, user.passphrase_hash)


__all__ = [
    "AuthHasher",
    "BcryptAuthHasher",
    "StubAuthHasher",
    "set_passphrase",
    "set_pin",
    "verify_passphrase",
    "verify_pin",
]
