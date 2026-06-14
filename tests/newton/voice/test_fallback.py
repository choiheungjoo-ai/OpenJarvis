"""Tests for newton.voice.fallback — PIN / passphrase enrollment + verify."""

from __future__ import annotations

import sys

import pytest

from newton.db import get_session, init_db
from newton.models.user import User
from newton.voice.fallback import (
    AuthHasher,
    BcryptAuthHasher,
    StubAuthHasher,
    set_passphrase,
    set_pin,
    verify_passphrase,
    verify_pin,
)

# ── AuthHasher ABC ──────────────────────────────────────────────────────


def test_auth_hasher_abc():
    with pytest.raises(TypeError):
        AuthHasher()  # type: ignore[abstract]


def test_auth_hasher_subclass_requires_name():
    with pytest.raises(TypeError, match="needs a name"):

        class Nameless(AuthHasher):
            name = ""

            def hash(self, secret):  # noqa: ARG002
                return ""

            def verify(self, secret, hashed):  # noqa: ARG002
                return False


# ── BcryptAuthHasher lazy contract ──────────────────────────────────────


def test_bcrypt_hasher_does_not_import_at_construction():
    sentinel = sys.modules.pop("bcrypt", None)
    try:
        h = BcryptAuthHasher()
        assert h._bcrypt is None  # noqa: SLF001
        assert "bcrypt" not in sys.modules
    finally:
        if sentinel is not None:
            sys.modules["bcrypt"] = sentinel


def test_bcrypt_hasher_rejects_silly_rounds():
    with pytest.raises(ValueError, match="bcrypt rounds"):
        BcryptAuthHasher(rounds=2)
    with pytest.raises(ValueError, match="bcrypt rounds"):
        BcryptAuthHasher(rounds=99)


# ── StubAuthHasher round-trip ───────────────────────────────────────────


def test_stub_hash_then_verify_succeeds():
    h = StubAuthHasher()
    stored = h.hash("1234")
    assert h.verify("1234", stored) is True


def test_stub_verify_rejects_wrong_secret():
    h = StubAuthHasher()
    stored = h.hash("1234")
    assert h.verify("0000", stored) is False


def test_stub_verify_empty_hashed_is_false():
    h = StubAuthHasher()
    assert h.verify("anything", "") is False


# ── set_pin / verify_pin ───────────────────────────────────────────────


def _seed_user(user_id: str = "sir") -> None:
    with get_session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, display_name=user_id.title()))


def test_set_pin_stores_hash(isolated_db):
    init_db()
    _seed_user()
    h = StubAuthHasher()
    with get_session() as s:
        set_pin(s, "sir", "1234", h)
    with get_session() as s:
        user = s.get(User, "sir")
    assert user.pin_hash == "stub:1234"


def test_set_pin_rejects_empty(isolated_db):
    init_db()
    _seed_user()
    h = StubAuthHasher()
    with pytest.raises(ValueError, match="non-empty"):
        with get_session() as s:
            set_pin(s, "sir", "   ", h)


def test_set_pin_unknown_user_raises(isolated_db):
    init_db()
    h = StubAuthHasher()
    with pytest.raises(ValueError, match="unknown user"):
        with get_session() as s:
            set_pin(s, "ghost", "1234", h)


def test_verify_pin_returns_false_for_unenrolled_user(isolated_db):
    init_db()
    _seed_user()
    h = StubAuthHasher()
    with get_session() as s:
        assert verify_pin(s, "sir", "1234", h) is False


def test_verify_pin_happy_path(isolated_db):
    init_db()
    _seed_user()
    h = StubAuthHasher()
    with get_session() as s:
        set_pin(s, "sir", "1879", h)
    with get_session() as s:
        assert verify_pin(s, "sir", "1879", h) is True
        assert verify_pin(s, "sir", "0000", h) is False


def test_verify_pin_unknown_user_is_false(isolated_db):
    init_db()
    h = StubAuthHasher()
    with get_session() as s:
        assert verify_pin(s, "ghost", "1879", h) is False


# ── passphrase ─────────────────────────────────────────────────────────


def test_passphrase_round_trip(isolated_db):
    init_db()
    _seed_user()
    h = StubAuthHasher()
    with get_session() as s:
        set_passphrase(s, "sir", "open sesame", h)
    with get_session() as s:
        assert verify_passphrase(s, "sir", "open sesame", h) is True
        assert verify_passphrase(s, "sir", "wrong words", h) is False


def test_set_passphrase_rejects_empty(isolated_db):
    init_db()
    _seed_user()
    h = StubAuthHasher()
    with pytest.raises(ValueError, match="non-empty"):
        with get_session() as s:
            set_passphrase(s, "sir", "", h)


def test_pin_and_passphrase_are_independent(isolated_db):
    """Setting a PIN must NOT clobber the passphrase, and vice versa."""

    init_db()
    _seed_user()
    h = StubAuthHasher()
    with get_session() as s:
        set_pin(s, "sir", "1234", h)
        set_passphrase(s, "sir", "open sesame", h)
    with get_session() as s:
        assert verify_pin(s, "sir", "1234", h) is True
        assert verify_passphrase(s, "sir", "open sesame", h) is True


# ── bcrypt verify happy path (only runs if bcrypt is installed) ────────


def test_bcrypt_round_trip_when_installed():
    pytest.importorskip("bcrypt")
    h = BcryptAuthHasher(rounds=4)  # fast for tests
    stored = h.hash("super-secret")
    assert h.verify("super-secret", stored) is True
    assert h.verify("nope", stored) is False


def test_bcrypt_verify_returns_false_on_garbage_hash():
    pytest.importorskip("bcrypt")
    h = BcryptAuthHasher(rounds=4)
    assert h.verify("anything", "not-a-real-bcrypt-string") is False
