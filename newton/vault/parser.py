"""Vault note parser.

Reads an Obsidian-style markdown file: YAML frontmatter (ACL + tags) plus a
markdown body. Produces a ``VaultNote``. Parsing is a *pure* operation — it
validates structure and types only, never touching the database. Referential
validation (does ``owner`` name a real user?) is a separate step,
``validate_against_db``, so the parser stays fast, deterministic, and easy to
test, and so the same note can be parsed without a DB at all.

ACL design (per block-3 spec):

    acl:
      owner: sir                 # required, single user_id
      read_users: [sir, gf]      # default: [owner]
      read_personas: [jarvis]    # default: []  (resolved later)
      write_users: [sir]         # default: [owner]
      write_personas: []         # default: []
      status: canonical          # canonical | shared | pending_review
    tags: [project, newton]

Unknown keys inside ``acl`` are preserved and surfaced as warnings rather
than rejected, for forward compatibility.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path
from typing import Any

import frontmatter
from pydantic import BaseModel, Field, model_validator

_KNOWN_ACL_KEYS = {
    "owner",
    "read_users",
    "read_personas",
    "write_users",
    "write_personas",
    "status",
}


class ACLStatus(str, Enum):
    CANONICAL = "canonical"
    SHARED = "shared"
    PENDING_REVIEW = "pending_review"


class ACL(BaseModel):
    """Access-control metadata for one note.

    ``owner`` may be None only when it could not be determined (e.g. a note
    with no acl block and no inferable owner); such notes are treated as
    pending and excluded from RAG until promoted.
    """

    owner: str | None = None
    read_users: list[str] = Field(default_factory=list)
    read_personas: list[str] = Field(default_factory=list)
    write_users: list[str] = Field(default_factory=list)
    write_personas: list[str] = Field(default_factory=list)
    status: ACLStatus = ACLStatus.PENDING_REVIEW
    unknown_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _apply_defaults(self) -> ACL:
        # read/write_users default to [owner] when owner is known and the
        # list was left empty.
        if self.owner:
            if not self.read_users:
                self.read_users = [self.owner]
            if not self.write_users:
                self.write_users = [self.owner]
            # owner is always allowed to read/write its own note.
            if self.owner not in self.read_users:
                self.read_users.append(self.owner)
            if self.owner not in self.write_users:
                self.write_users.append(self.owner)
        return self

    @classmethod
    def from_frontmatter(cls, acl_raw: dict[str, Any] | None) -> ACL:
        """Build an ACL from the raw ``acl`` mapping in frontmatter.

        Tolerates a missing block (returns an owner-less pending ACL) and
        records unknown keys instead of failing.
        """
        if not acl_raw:
            return cls()
        unknown = sorted(k for k in acl_raw if k not in _KNOWN_ACL_KEYS)
        data = {k: v for k, v in acl_raw.items() if k in _KNOWN_ACL_KEYS}
        data["unknown_keys"] = unknown
        return cls(**data)


class VaultNote(BaseModel):
    """A parsed vault note: location, ACL, tags, body, and a content hash."""

    path: Path
    acl: ACL
    tags: list[str] = Field(default_factory=list)
    body: str = ""
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""

    model_config = {"arbitrary_types_allowed": True}


class VaultParseError(RuntimeError):
    """Raised when a note cannot be parsed (bad YAML, unreadable file)."""


def _content_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def parse(path: str | Path) -> VaultNote:
    """Parse a markdown note into a VaultNote. Pure: no DB access.

    Raises VaultParseError on unreadable files or malformed frontmatter.
    """
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        raise VaultParseError(f"cannot read {p}: {e}") from e

    try:
        post = frontmatter.loads(raw)
    except Exception as e:  # YAML / frontmatter parse errors
        raise VaultParseError(f"malformed frontmatter in {p}: {e}") from e

    meta = post.metadata or {}
    acl_raw = meta.get("acl")
    if acl_raw is not None and not isinstance(acl_raw, dict):
        raise VaultParseError(f"'acl' must be a mapping in {p}, got {type(acl_raw)}")

    try:
        acl = ACL.from_frontmatter(acl_raw)
    except Exception as e:
        raise VaultParseError(f"invalid acl in {p}: {e}") from e

    tags_raw = meta.get("tags", [])
    if isinstance(tags_raw, str):
        tags = [tags_raw]
    elif isinstance(tags_raw, list):
        tags = [str(t) for t in tags_raw]
    else:
        tags = []

    return VaultNote(
        path=p,
        acl=acl,
        tags=tags,
        body=post.content,
        frontmatter=meta,
        content_hash=_content_hash(raw),
    )


class ACLValidationIssue(BaseModel):
    """One referential problem found by validate_against_db."""

    field: str
    value: str
    problem: str  # e.g. "unknown user", "unknown persona"


def validate_against_db(note: VaultNote, session: Any) -> list[ACLValidationIssue]:
    """Check that ACL references point to existing users / personas.

    Returns a list of issues (empty == valid). Does not raise on referential
    problems — the caller decides how strict to be (a scanner may warn and
    quarantine rather than abort).
    """
    from sqlalchemy import select

    from newton.models import Persona, User

    known_users = set(session.execute(select(User.user_id)).scalars().all())
    known_personas = set(session.execute(select(Persona.persona_id)).scalars().all())

    issues: list[ACLValidationIssue] = []

    def check_users(field: str, values: list[str]) -> None:
        for v in values:
            if v not in known_users:
                issues.append(
                    ACLValidationIssue(field=field, value=v, problem="unknown user")
                )

    def check_personas(field: str, values: list[str]) -> None:
        for v in values:
            if v not in known_personas:
                issues.append(
                    ACLValidationIssue(field=field, value=v, problem="unknown persona")
                )

    if note.acl.owner is not None and note.acl.owner not in known_users:
        issues.append(
            ACLValidationIssue(
                field="owner", value=note.acl.owner, problem="unknown user"
            )
        )
    check_users("read_users", note.acl.read_users)
    check_users("write_users", note.acl.write_users)
    check_personas("read_personas", note.acl.read_personas)
    check_personas("write_personas", note.acl.write_personas)
    return issues


__all__ = [
    "ACL",
    "ACLStatus",
    "ACLValidationIssue",
    "VaultNote",
    "VaultParseError",
    "parse",
    "validate_against_db",
]
