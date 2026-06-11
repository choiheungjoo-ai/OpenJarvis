"""Tests for newton.seed.

Covers:
    * personas / users actually get inserted
    * a second call is a no-op (idempotent)
    * user_persona_link rows are created (sir→jarvis, gf→friday)
    * a partial seed (personas only, then users) still ends consistent
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from newton.models import Persona, User, UserPersonaLink
from newton.seed import seed_all, seed_personas, seed_users

MIGRATION_001 = (
    Path(__file__).resolve().parent.parent.parent / "migrations" / "001_initial.sql"
)


@pytest.fixture
def engine():
    """In-memory SQLite with FK enforcement and migration 001 applied."""
    eng = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _fk(c, _r):
        cur = c.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.close()

    with eng.connect() as conn:
        raw = conn.connection.driver_connection
        # Apply ALL production migrations in order, exactly like init_db,
        # so later ALTERs (e.g. 008 users.stt_bias_dict_json) are included.
        for mig in sorted(MIGRATION_001.parent.glob("0*.sql")):
            raw.executescript(mig.read_text(encoding="utf-8"))
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


# ─────────────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────────────


def test_seed_all_inserts_expected_rows(session):
    report = seed_all(session)
    session.commit()

    assert sorted(report.personas_added) == ["butler", "friday", "jarvis"]
    assert sorted(report.users_added) == ["gf", "sir"]
    assert sorted(report.links_added) == [("gf", "friday"), ("sir", "jarvis")]

    # Verify DB state
    persona_ids = {p.persona_id for p in session.scalars(select(Persona))}
    assert persona_ids == {"butler", "jarvis", "friday"}

    users = {u.user_id: u for u in session.scalars(select(User))}
    assert users["sir"].display_name == "Alex"
    assert users["sir"].default_persona_id == "jarvis"
    assert users["gf"].display_name == "Stella"
    assert users["gf"].default_persona_id == "friday"


def test_seed_creates_user_persona_links(session):
    seed_all(session)
    session.commit()

    links = {
        (link.user_id, link.persona_id, bool(link.is_default))
        for link in session.scalars(select(UserPersonaLink))
    }
    assert links == {
        ("sir", "jarvis", True),
        ("gf", "friday", True),
    }


def test_personas_keep_placeholder_in_system_prompt(session):
    """seed must NOT substitute names — that's a runtime concern."""
    # personas have FK on owner_user_id → users; seed users first.
    seed_users(session)
    seed_personas(session)
    session.commit()

    jarvis = session.get(Persona, "jarvis")
    friday = session.get(Persona, "friday")
    butler = session.get(Persona, "butler")

    assert "${OWNER_DISPLAY_NAME}" in jarvis.system_prompt
    assert "${OWNER_DISPLAY_NAME}" in friday.system_prompt
    # Butler is public — no placeholder needed.
    assert "${OWNER_DISPLAY_NAME}" not in butler.system_prompt


def test_voice_config_serialized_as_json(session):
    """JARVIS has dict voice (ko/en); Friday has single VoiceConfig."""
    import json

    seed_users(session)
    seed_personas(session)
    session.commit()

    jarvis = session.get(Persona, "jarvis")
    friday = session.get(Persona, "friday")

    j_voice = json.loads(jarvis.voice_config_json)
    assert set(j_voice.keys()) == {"ko", "en"}
    assert j_voice["ko"]["engine"] == "qwen3-tts-1.7b"
    assert j_voice["en"]["engine"] == "chatterbox"

    f_voice = json.loads(friday.voice_config_json)
    assert f_voice["engine"] == "qwen3-tts-1.7b"


# ─────────────────────────────────────────────────────────────────────────────
# Idempotency
# ─────────────────────────────────────────────────────────────────────────────


def test_seed_all_is_idempotent(session):
    seed_all(session)
    session.commit()

    # Second run must add nothing.
    report = seed_all(session)
    session.commit()
    assert report.is_empty

    # Row counts unchanged.
    assert len(list(session.scalars(select(Persona)))) == 3
    assert len(list(session.scalars(select(User)))) == 2
    assert len(list(session.scalars(select(UserPersonaLink)))) == 2


def test_seed_users_then_personas_then_links_split_call(session):
    """Running each stage separately is equivalent to seed_all."""
    from newton.seed import seed_links

    seed_users(session)
    session.commit()
    seed_personas(session)
    session.commit()
    seed_links(session)
    session.commit()

    assert {p.persona_id for p in session.scalars(select(Persona))} == {
        "butler",
        "jarvis",
        "friday",
    }
    assert {u.user_id for u in session.scalars(select(User))} == {"sir", "gf"}
    assert len(list(session.scalars(select(UserPersonaLink)))) == 2
