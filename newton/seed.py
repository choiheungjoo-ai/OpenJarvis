"""Initial-data seeding for Newton.

What gets seeded
----------------
* Two users: ``sir`` (display_name 'Alex') and ``gf`` (display_name 'Stella').
* The three personas from ``config/personas.yaml`` (Butler, JARVIS, Friday).
* For each non-public persona, a ``user_persona_link`` to its owner with
  ``is_default=1``.  Public personas (Butler) need no link.

Order matters because of foreign keys:
    1. users     — no FK dependencies
    2. personas  — owner_user_id → users
    3. links     — user_id → users, persona_id → personas

All functions are idempotent — calling them twice on the same database is
a no-op.  We achieve this by reading the row first and inserting only when
absent.  This is more verbose than ``INSERT OR IGNORE`` but transparent
to SQLAlchemy and easy to follow when debugging.

Why the names live here
-----------------------
``personas.yaml`` is committed to git and must not contain personal names.
The Pydantic config carries ``${OWNER_DISPLAY_NAME}`` placeholders; the
real names ('Alex', 'Stella') live in ``users.display_name`` and are
written by this seeder.  ``newton.config.render_personality()`` does the
substitution at LLM-call time.

Public API
----------
    SeedReport               — dataclass with counts of what was created
    seed_users(session)      — write the two initial users
    seed_personas(session)   — write personas from config (users first!)
    seed_links(session)      — write user_persona_link rows
    seed_all(session)        — full sequence in dependency order
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select

from newton.config import load_config
from newton.models import Persona, User, UserPersonaLink

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ─────────────────────────────────────────────────────────────────────────────
# Seed definitions
# ─────────────────────────────────────────────────────────────────────────────


# (user_id, display_name, default_persona_id)
_INITIAL_USERS: list[tuple[str, str, str]] = [
    ("sir", "Alex", "jarvis"),
    ("gf", "Stella", "friday"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SeedReport:
    """What the seeder actually inserted (skipped rows aren't counted)."""

    personas_added: list[str] = field(default_factory=list)
    users_added: list[str] = field(default_factory=list)
    links_added: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.personas_added) + len(self.users_added) + len(self.links_added)

    @property
    def is_empty(self) -> bool:
        return self.total == 0


# ─────────────────────────────────────────────────────────────────────────────
# seed_users
# ─────────────────────────────────────────────────────────────────────────────


def seed_users(session: Session, report: SeedReport | None = None) -> SeedReport:
    """Insert the two initial users.  No FK dependencies — safe first step.

    Note: ``default_persona_id`` is a soft pointer (no FK on the column),
    so we can set it here even before the personas exist.
    """
    report = report or SeedReport()

    with session.no_autoflush:
        for user_id, display_name, default_persona_id in _INITIAL_USERS:
            if session.get(User, user_id) is None:
                session.add(
                    User(
                        user_id=user_id,
                        display_name=display_name,
                        default_persona_id=default_persona_id,
                    )
                )
                report.users_added.append(user_id)

    session.flush()
    return report


# ─────────────────────────────────────────────────────────────────────────────
# seed_personas
# ─────────────────────────────────────────────────────────────────────────────


def seed_personas(session: Session, report: SeedReport | None = None) -> SeedReport:
    """Insert the three personas from ``personas.yaml``.

    Users referenced by ``owner`` must be seeded first; the FK on
    ``personas.owner_user_id`` enforces this.
    """
    report = report or SeedReport()
    cfg = load_config()

    # Disable autoflush so half-added personas don't flush mid-iteration
    # and trip a FK before their dependency is in place.  We flush
    # explicitly at the end of the loop.
    with session.no_autoflush:
        for persona_id, persona_def in cfg.personas.items():
            existing = session.get(Persona, persona_id)
            if existing is not None:
                continue

            # ``voice`` may be a single VoiceConfig or a {ko, en} dict.
            voice = persona_def.voice
            if isinstance(voice, dict):
                voice_json = json.dumps(
                    {lang: vc.model_dump() for lang, vc in voice.items()},
                    ensure_ascii=False,
                )
            else:
                voice_json = json.dumps(voice.model_dump(), ensure_ascii=False)

            session.add(
                Persona(
                    persona_id=persona_id,
                    display_name=persona_def.display_name,
                    is_public=int(persona_def.is_public),
                    is_default=int(persona_def.is_default),
                    owner_user_id=persona_def.owner,
                    # Raw template; ``render_personality`` substitutes at runtime.
                    system_prompt=persona_def.personality,
                    voice_config_json=voice_json,
                    color=persona_def.color,
                )
            )
            report.personas_added.append(persona_id)

    session.flush()  # surface FK / CHECK errors now
    return report


# ─────────────────────────────────────────────────────────────────────────────
# seed_links
# ─────────────────────────────────────────────────────────────────────────────


def seed_links(session: Session, report: SeedReport | None = None) -> SeedReport:
    """Insert each user's default-persona link.  Users + personas required."""
    report = report or SeedReport()

    with session.no_autoflush:
        for user_id, _, default_persona_id in _INITIAL_USERS:
            existing = session.execute(
                select(UserPersonaLink).where(
                    UserPersonaLink.user_id == user_id,
                    UserPersonaLink.persona_id == default_persona_id,
                )
            ).scalar_one_or_none()

            if existing is None:
                session.add(
                    UserPersonaLink(
                        user_id=user_id,
                        persona_id=default_persona_id,
                        is_default=1,
                    )
                )
                report.links_added.append((user_id, default_persona_id))

    session.flush()
    return report


# ─────────────────────────────────────────────────────────────────────────────
# seed_all
# ─────────────────────────────────────────────────────────────────────────────


def seed_all(session: Session) -> SeedReport:
    """Run the full seed sequence in dependency order.  Idempotent."""
    report = SeedReport()
    seed_users(session, report)
    seed_personas(session, report)
    seed_links(session, report)
    return report


__all__ = [
    "SeedReport",
    "seed_all",
    "seed_links",
    "seed_personas",
    "seed_users",
]
