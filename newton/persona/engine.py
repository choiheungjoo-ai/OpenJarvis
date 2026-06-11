"""Persona engine — activation routing and system-prompt rendering.

Two responsibilities:

  1. ``route(user_id, signal)`` decides which persona becomes active given a
     Stage-2 signal, enforcing persona ownership:
       - a public persona (owner_user_id is None) may be activated by anyone
       - an owned persona may be activated only by its owner
       - otherwise we fall back to the requesting user's default persona
  2. ``render_system_prompt(persona_id, user_id)`` builds the LLM system
     prompt, substituting the owner's display name via the existing
     ``newton.config.render_personality`` (block 1's canonical implementation
     — reused, not reimplemented).

The actual sensors that produce signals live in later blocks; here we only
expose the routing logic so it can be tested and driven from the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from newton.config import render_personality
from newton.persona.signals import (
    FaceBindingSignal,
    Stage2Signal,
    VoiceNamingSignal,
)


class ActivationReason(str, Enum):
    VOICE_NAMING = "voice_naming"  # named persona, owned-by or public
    FACE_DEFAULT = "face_default"  # face binding -> user's default
    FALLBACK_NOT_OWNED = "fallback_not_owned"  # named persona owned by another
    FALLBACK_UNKNOWN = "fallback_unknown"  # named persona does not exist


@dataclass(frozen=True)
class PersonaActivation:
    """The outcome of routing: which persona is active and why."""

    user_id: str
    persona_id: str
    reason: ActivationReason


class PersonaEngineError(RuntimeError):
    """Raised when routing/rendering cannot proceed (unknown user, etc.)."""


class PersonaEngine:
    """Routes Stage-2 signals to personas and renders system prompts."""

    def __init__(self, session: Any):
        self._session = session

    # -- internal lookups -----------------------------------------------------

    def _get_user(self, user_id: str):
        from newton.models import User

        user = self._session.get(User, user_id)
        if user is None:
            raise PersonaEngineError(f"unknown user: {user_id!r}")
        return user

    def _get_persona(self, persona_id: str):
        from newton.models import Persona

        return self._session.get(Persona, persona_id)

    def _find_persona_by_name(self, name: str):
        """Resolve a spoken persona name to a persona row (case-insensitive).

        Matches on persona_id or display_name so "JARVIS", "jarvis", and the
        display name all resolve.
        """
        from sqlalchemy import func, select

        from newton.models import Persona

        lowered = name.strip().lower()
        stmt = select(Persona).where(
            (func.lower(Persona.persona_id) == lowered)
            | (func.lower(Persona.display_name) == lowered)
        )
        return self._session.execute(stmt).scalars().first()

    def _default_persona_id(self, user) -> str:
        if not user.default_persona_id:
            raise PersonaEngineError(f"user {user.user_id!r} has no default persona")
        return user.default_persona_id

    # -- routing --------------------------------------------------------------

    def route(self, user_id: str, signal: Stage2Signal) -> PersonaActivation:
        user = self._get_user(user_id)

        if isinstance(signal, FaceBindingSignal):
            return PersonaActivation(
                user_id=user_id,
                persona_id=self._default_persona_id(user),
                reason=ActivationReason.FACE_DEFAULT,
            )

        if isinstance(signal, VoiceNamingSignal):
            persona = self._find_persona_by_name(signal.persona_name)
            if persona is None:
                return PersonaActivation(
                    user_id=user_id,
                    persona_id=self._default_persona_id(user),
                    reason=ActivationReason.FALLBACK_UNKNOWN,
                )
            # Ownership check: public (None) or owned-by-this-user is allowed.
            if persona.owner_user_id in (None, user_id):
                return PersonaActivation(
                    user_id=user_id,
                    persona_id=persona.persona_id,
                    reason=ActivationReason.VOICE_NAMING,
                )
            # Owned by someone else -> fall back to the user's default.
            return PersonaActivation(
                user_id=user_id,
                persona_id=self._default_persona_id(user),
                reason=ActivationReason.FALLBACK_NOT_OWNED,
            )

        raise PersonaEngineError(f"unsupported signal type: {type(signal)!r}")

    # -- rendering ------------------------------------------------------------

    def render_system_prompt(self, persona_id: str, user_id: str) -> str:
        """Render the persona's system prompt with the owner's display name.

        The personality template lives in personas.yaml (config.Persona), not
        in the DB row (the ORM Persona carries only metadata). We look the
        template up by persona_id from load_config(), and resolve the owner's
        display name from the DB. Public personas (no owner) render unchanged.
        """
        from newton.config import load_config

        config_personas = load_config().personas
        config_persona = config_personas.get(persona_id)
        if config_persona is None:
            raise PersonaEngineError(f"unknown persona: {persona_id!r}")

        # Resolve owner display name from the DB, as a plain string, while the
        # session is live (avoids DetachedInstanceError later).
        owner_display_name: str | None = None
        orm_persona = self._get_persona(persona_id)
        if orm_persona is not None and orm_persona.owner_user_id is not None:
            from newton.models import User

            owner = self._session.get(User, orm_persona.owner_user_id)
            owner_display_name = owner.display_name if owner else None

        return render_personality(config_persona, owner_display_name)


__all__ = [
    "ActivationReason",
    "PersonaActivation",
    "PersonaEngine",
    "PersonaEngineError",
]
