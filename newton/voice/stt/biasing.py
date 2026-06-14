"""Three-tier contextual biasing for Whisper.

Whisper's ``initial_prompt`` is a short hint that biases recognition
toward terms in the prompt. We assemble that prompt from three
sources, in order of "always-on → user-specific → just-now":

    1. **system**  — always-on technical vocab (model names, Newton
       itself). Loaded from ``config/biasing_system.txt`` plus a
       small hard-coded fallback so a fresh checkout still has a
       working prompt.
    2. **user**    — sir's personal dictionary from
       ``users.stt_bias_dict_json`` (populated by the block-3 vault
       hook).
    3. **context** — entities extracted from the last few messages
       in the current session. Uses the block-3 NER helper
       (``newton.vault.biasing_hook.extract_entities``) so we don't
       grow a second NER pipeline.

Joined into one string Whisper accepts:

    "Domain context: Newton, RTX 5090, BGE-M3, JARVIS, Stella, ..."

Deduplication is case-insensitive and order-preserving — the system
tier appears first, then user, then context.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.models.message import Message
from newton.models.user import User

log = logging.getLogger(__name__)


#: Built-in fallback used when ``config/biasing_system.txt`` is missing.
#: Hard-coded but minimal — the YAML is the user-tunable source. Tests
#: pass their own ``system_terms`` so this list is never load-bearing.
_BUILTIN_SYSTEM_TERMS: tuple[str, ...] = (
    "Newton",
    "JARVIS",
    "Friday",
    "Butler",
    "RTX 5090",
    "BGE-M3",
    "Qdrant",
    "Whisper",
    "Chatterbox",
    "Qwen3-TTS",
    "Silero",
)

#: Header prefix Whisper sees. The library docs note "Domain context:"
#: as one of the well-tested biasing-prompt shapes.
_PROMPT_HEADER = "Domain context: "


@dataclass(frozen=True, slots=True)
class BiasingTiers:
    """The raw per-tier vocab, for ``patterns show``-style debugging."""

    system: list[str]
    user: list[str]
    context: list[str]


@dataclass
class BiasingDict:
    """Assembles the three-tier prompt for one ``(user, session)`` pair.

    ``extract_entities`` is injectable so tests don't need to load
    spaCy. The default points at block-3's helper, which lazy-loads
    the model on first call.
    """

    system_terms: list[str]
    context_messages: int = 5
    # Step 5.8: terms extracted live from recent messages.
    extract_entities: Callable[[str], list[str]] | None = None

    def tiers(
        self, db_session: Session, user_id: str, session_id: str | None = None
    ) -> BiasingTiers:
        user_terms = self._user_terms(db_session, user_id)
        context_terms = (
            self._context_terms(db_session, session_id) if session_id else []
        )
        return BiasingTiers(
            system=list(self.system_terms),
            user=user_terms,
            context=context_terms,
        )

    def build_prompt(
        self, db_session: Session, user_id: str, session_id: str | None = None
    ) -> str:
        """Return the Whisper ``initial_prompt`` string."""
        tiers = self.tiers(db_session, user_id, session_id)
        ordered = _dedupe_preserve(tiers.system + tiers.user + tiers.context)
        if not ordered:
            return ""
        return _PROMPT_HEADER + ", ".join(ordered) + "."

    # ── tier helpers ─────────────────────────────────────────────────

    @staticmethod
    def _user_terms(db_session: Session, user_id: str) -> list[str]:
        user = db_session.get(User, user_id)
        if user is None or not user.stt_bias_dict_json:
            return []
        try:
            parsed = json.loads(user.stt_bias_dict_json)
        except json.JSONDecodeError as e:
            log.warning("user %s has malformed stt_bias_dict_json: %s", user_id, e)
            return []
        return [str(s) for s in parsed if isinstance(s, str) and s.strip()]

    def _context_terms(self, db_session: Session, session_id: str) -> list[str]:
        # Most recent N user / assistant messages, oldest first so the
        # prompt reads chronologically.
        rows = list(
            db_session.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.message_id.desc())
                .limit(self.context_messages)
            )
            .scalars()
            .all()
        )
        rows.reverse()

        extractor = self.extract_entities or _default_extractor()
        out: list[str] = []
        for m in rows:
            if not m.content:
                continue
            try:
                out.extend(extractor(m.content))
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "biasing extractor failed on message %s: %s", m.message_id, e
                )
        return out


def _default_extractor() -> Callable[[str], list[str]]:
    """Return the block-3 NER extractor (lazy-loaded on first call)."""

    def _extract(text: str) -> list[str]:
        # Imported lazily — extracts_entities pulls spaCy.
        from newton.vault.biasing_hook import extract_entities  # noqa: PLC0415

        return extract_entities(text)

    return _extract


def _dedupe_preserve(items: list[str]) -> list[str]:
    """Case-insensitive de-dup; preserve first-seen order and casing."""
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        x = x.strip()
        if not x:
            continue
        key = x.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out


def load_system_terms(config_dir: Path | None = None) -> list[str]:
    """Load ``config/biasing_system.txt`` or fall back to the built-in list."""
    import os

    root = (
        config_dir
        or Path(os.environ.get("NEWTON_CONFIG_DIR", "")).expanduser()
        or Path(__file__).resolve().parent.parent.parent.parent / "config"
    )
    path = root / "biasing_system.txt"
    if not path.exists():
        return list(_BUILTIN_SYSTEM_TERMS)
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return lines or list(_BUILTIN_SYSTEM_TERMS)


def build_default_biasing(
    config_dir: Path | None = None,
    extract_entities: Callable[[str], list[str]] | None = None,
    context_messages: int = 5,
) -> BiasingDict:
    """Convenience constructor — system terms from file + default extractor."""
    return BiasingDict(
        system_terms=load_system_terms(config_dir),
        context_messages=context_messages,
        extract_entities=extract_entities,
    )


def _coerce_any_session(session: Any) -> Session:
    """Tests sometimes pass a SQLAlchemy AsyncSession or similar."""
    return session


__all__ = [
    "BiasingDict",
    "BiasingTiers",
    "build_default_biasing",
    "load_system_terms",
]
