"""Tests for newton.persona.engine."""

from __future__ import annotations

import pytest

from newton.persona import (
    ActivationReason,
    FaceBindingSignal,
    PersonaEngine,
    PersonaEngineError,
    VoiceNamingSignal,
)


def _engine(session):
    return PersonaEngine(session)


# -- voice naming -------------------------------------------------------------


def test_voice_naming_own_persona(seeded_db):
    from newton.db import get_session

    with get_session() as session:
        act = _engine(session).route("sir", VoiceNamingSignal("JARVIS"))
    assert act.persona_id == "jarvis"
    assert act.reason is ActivationReason.VOICE_NAMING


def test_voice_naming_case_insensitive(seeded_db):
    from newton.db import get_session

    with get_session() as session:
        act = _engine(session).route("sir", VoiceNamingSignal("jarvis"))
    assert act.persona_id == "jarvis"


def test_voice_naming_public_persona_allowed_for_anyone(seeded_db):
    from newton.db import get_session

    # butler is public (owner=None) -> gf may activate it.
    with get_session() as session:
        act = _engine(session).route("gf", VoiceNamingSignal("Butler"))
    assert act.persona_id == "butler"
    assert act.reason is ActivationReason.VOICE_NAMING


def test_voice_naming_others_persona_falls_back(seeded_db):
    from newton.db import get_session

    # gf names JARVIS (owned by sir) -> fall back to gf's default (friday).
    with get_session() as session:
        act = _engine(session).route("gf", VoiceNamingSignal("JARVIS"))
    assert act.persona_id == "friday"
    assert act.reason is ActivationReason.FALLBACK_NOT_OWNED


def test_voice_naming_unknown_persona_falls_back(seeded_db):
    from newton.db import get_session

    with get_session() as session:
        act = _engine(session).route("sir", VoiceNamingSignal("Ultron"))
    assert act.persona_id == "jarvis"  # sir's default
    assert act.reason is ActivationReason.FALLBACK_UNKNOWN


# -- face binding -------------------------------------------------------------


def test_face_binding_uses_default(seeded_db):
    from newton.db import get_session

    with get_session() as session:
        act = _engine(session).route("gf", FaceBindingSignal())
    assert act.persona_id == "friday"
    assert act.reason is ActivationReason.FACE_DEFAULT


# -- errors -------------------------------------------------------------------


def test_unknown_user_raises(seeded_db):
    from newton.db import get_session

    with get_session() as session:
        with pytest.raises(PersonaEngineError, match="unknown user"):
            _engine(session).route("nobody", FaceBindingSignal())


# -- system prompt rendering --------------------------------------------------


def test_render_substitutes_owner_display_name(seeded_db):
    from newton.db import get_session

    with get_session() as session:
        prompt = _engine(session).render_system_prompt("jarvis", "sir")
    # JARVIS is owned by sir (display "Alex"); placeholder must be gone.
    assert "${OWNER_DISPLAY_NAME}" not in prompt
    assert "Alex" in prompt


def test_render_public_persona_keeps_template(seeded_db):
    from newton.db import get_session

    with get_session() as session:
        prompt = _engine(session).render_system_prompt("butler", "sir")
    # butler has no owner -> template returned; if it has no placeholder this
    # is just the raw personality. Either way it must not raise.
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_render_unknown_persona_raises(seeded_db):
    from newton.db import get_session

    with get_session() as session:
        with pytest.raises(PersonaEngineError, match="unknown persona"):
            _engine(session).render_system_prompt("ghost", "sir")
