"""Smoke + round-trip tests for every Newton ORM model.

Strategy
--------
* In-memory SQLite per test (no shared state, no temp files).
* The real ``migrations/001_initial.sql`` is applied — we verify that
  ORM models and the SQL schema agree.  If a column type, FK, or CHECK
  drifts, these tests catch it.
* Tests are grouped by table-group: identity / auth / guest / proactive.

These are intentionally narrow tests — one happy-path round trip per
model plus a handful of FK / CHECK / relationship checks.  Broader
behaviour belongs to later blocks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newton.models import (
    AuthAttempt,
    Base,  # noqa: F401  (kept for explicit "models imported" assertion)
    CalendarEvent,
    ChatSession,
    GuestActivity,
    Message,
    Persona,
    ProactiveNotification,
    RegistrationRequest,
    ScreenCapture,
    SystemMetric,
    User,
    UserPattern,
    UserPersonaLink,
)

MIGRATION_001 = (
    Path(__file__).resolve().parent.parent.parent / "migrations" / "001_initial.sql"
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    """In-memory SQLite with FK enforcement and migration 001 applied."""
    eng = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.close()

    # Apply the actual production migration so we test what we ship.
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
# Identity group
# ─────────────────────────────────────────────────────────────────────────────


def test_user_round_trip(session):
    session.add(User(user_id="sir", display_name="Alex"))
    session.commit()

    got = session.get(User, "sir")
    assert got is not None
    assert got.display_name == "Alex"
    assert got.retry_profile == "normal"  # server_default
    assert got.created_at is not None


def test_user_retry_profile_check_constraint(session):
    session.add(User(user_id="x", display_name="X", retry_profile="paranoid"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_persona_round_trip_with_owner(session):
    session.add(User(user_id="sir", display_name="Alex"))
    session.add(
        Persona(
            persona_id="jarvis",
            display_name="JARVIS",
            owner_user_id="sir",
            color="#185FA5",
        )
    )
    session.commit()

    p = session.get(Persona, "jarvis")
    assert p.owner_user_id == "sir"
    assert p.owner.display_name == "Alex"
    # Reverse relationship populates.
    assert any(op.persona_id == "jarvis" for op in p.owner.owned_personas)


def test_persona_owner_set_null_on_user_delete(session):
    session.add(User(user_id="sir", display_name="Alex"))
    session.add(Persona(persona_id="jarvis", display_name="J", owner_user_id="sir"))
    session.commit()

    session.delete(session.get(User, "sir"))
    session.commit()

    p = session.get(Persona, "jarvis")
    assert p is not None  # persona survives
    assert p.owner_user_id is None  # owner cleared (SET NULL)


def test_user_persona_link_cascade(session):
    session.add(User(user_id="sir", display_name="Alex"))
    session.add(Persona(persona_id="jarvis", display_name="J", owner_user_id="sir"))
    session.add(UserPersonaLink(user_id="sir", persona_id="jarvis", is_default=1))
    session.commit()

    # Deleting the user cascades through user_persona_link.
    session.delete(session.get(User, "sir"))
    session.commit()
    assert session.query(UserPersonaLink).count() == 0


def test_chat_session_with_messages(session):
    session.add(User(user_id="sir", display_name="Alex"))
    session.add(Persona(persona_id="jarvis", display_name="J", owner_user_id="sir"))
    session.add(ChatSession(session_id="s1", user_id="sir", persona_id="jarvis"))
    session.add(Message(session_id="s1", role="user", content="Hello"))
    session.add(Message(session_id="s1", role="assistant", content="Good day, sir."))
    session.commit()

    s = session.get(ChatSession, "s1")
    assert len(s.messages) == 2
    assert s.messages[0].role == "user"
    assert s.messages[1].content.startswith("Good day")


def test_message_role_check_constraint(session):
    session.add(User(user_id="sir", display_name="Alex"))
    session.add(Persona(persona_id="jarvis", display_name="J", owner_user_id="sir"))
    session.add(ChatSession(session_id="s1", user_id="sir", persona_id="jarvis"))
    session.add(Message(session_id="s1", role="spammer", content="x"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_persona_delete_restricted_by_active_session(session):
    session.add(User(user_id="sir", display_name="Alex"))
    session.add(Persona(persona_id="jarvis", display_name="J", owner_user_id="sir"))
    session.add(ChatSession(session_id="s1", user_id="sir", persona_id="jarvis"))
    session.commit()

    session.delete(session.get(Persona, "jarvis"))
    with pytest.raises(IntegrityError):
        session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Auth + Guest group
# ─────────────────────────────────────────────────────────────────────────────


def test_registration_request_round_trip(session):
    req = RegistrationRequest(requested_name="visitor", requested_persona="friday")
    session.add(req)
    session.commit()

    assert req.request_id is not None
    assert req.status == "pending"
    assert req.requested_at is not None


def test_auth_attempt_survives_user_delete(session):
    session.add(User(user_id="sir", display_name="Alex"))
    session.commit()

    a = AuthAttempt(attempted_user_id="sir", method="voice", success=1, confidence=0.92)
    session.add(a)
    session.commit()
    attempt_id = a.attempt_id

    session.delete(session.get(User, "sir"))
    session.commit()

    # AuthAttempt row survives; FK points to NULL.
    rec = session.get(AuthAttempt, attempt_id)
    assert rec is not None
    assert rec.attempted_user_id is None


def test_guest_activity_default_status(session):
    g = GuestActivity(activity_type="chat", summary="asked about the time")
    session.add(g)
    session.commit()
    assert g.status == "pending_review"


# ─────────────────────────────────────────────────────────────────────────────
# Proactive group
# ─────────────────────────────────────────────────────────────────────────────


def test_system_metric_round_trip(session):
    m = SystemMetric(metric_type="cpu", value=87.5)
    session.add(m)
    session.commit()
    assert m.metric_id is not None
    assert m.captured_at is not None


def test_user_pattern_cascade(session):
    session.add(User(user_id="sir", display_name="Alex"))
    session.add(UserPattern(user_id="sir", pattern_type="time", confidence=0.8))
    session.commit()

    session.delete(session.get(User, "sir"))
    session.commit()
    assert session.query(UserPattern).count() == 0


def test_proactive_notification_with_pattern_set_null(session):
    session.add(User(user_id="sir", display_name="Alex"))
    p = UserPattern(user_id="sir", pattern_type="time", confidence=0.9)
    session.add(p)
    session.commit()

    n = ProactiveNotification(
        user_id="sir",
        trigger_pattern_id=p.pattern_id,
        notification_text="It's 11pm; want to wind down?",
    )
    session.add(n)
    session.commit()

    # Deleting the pattern keeps the notification but nulls the trigger.
    session.delete(p)
    session.commit()

    session.refresh(n)
    assert n.notification_text.startswith("It's 11pm")
    assert n.trigger_pattern_id is None


def test_screen_capture_round_trip(session):
    session.add(User(user_id="sir", display_name="Alex"))
    session.commit()
    c = ScreenCapture(user_id="sir", analysis_summary="VS Code, Python file open")
    session.add(c)
    session.commit()
    assert c.capture_id is not None
    assert c.is_sensitive == 0


def test_calendar_event_round_trip(session):
    from datetime import datetime, timezone

    session.add(User(user_id="sir", display_name="Alex"))
    session.commit()
    e = CalendarEvent(
        source="google",
        external_id="abc123",
        user_id="sir",
        title="Stand-up",
        start_time=datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc),
    )
    session.add(e)
    session.commit()
    assert e.event_id is not None
    assert e.user.user_id == "sir"


def test_models_module_exports_everything():
    """Every Base subclass defined under newton/models/ is exported in __all__.

    Compares two sources of truth: the model classes actually defined on
    disk versus the names declared in ``__all__``. Adding a model file but
    forgetting it in ``__all__`` fails here. No hardcoded list to maintain.
    """
    import newton.models as m
    from tests.newton._schema_helpers import expected_model_names

    exported = set(m.__all__) - {"Base"}
    on_disk = expected_model_names()
    assert exported == on_disk, f"diff: {exported ^ on_disk}"
