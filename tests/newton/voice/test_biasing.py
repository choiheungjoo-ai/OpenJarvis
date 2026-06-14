"""Tests for newton.voice.stt.biasing — 3-tier Whisper prompt."""

from __future__ import annotations

import json
from datetime import datetime

from newton.db import get_session, init_db
from newton.models.chat_session import ChatSession
from newton.models.message import Message
from newton.models.persona import Persona
from newton.models.user import User
from newton.voice.stt.biasing import (
    BiasingDict,
    BiasingTiers,
    _dedupe_preserve,
    build_default_biasing,
    load_system_terms,
)


def _seed_user(user_id: str = "sir", bias_dict: list[str] | None = None) -> None:
    with get_session() as s:
        if s.get(User, user_id) is None:
            s.add(
                User(
                    user_id=user_id,
                    display_name=user_id.title(),
                    stt_bias_dict_json=json.dumps(bias_dict or []),
                )
            )
        else:
            s.get(User, user_id).stt_bias_dict_json = json.dumps(bias_dict or [])


def _seed_persona(persona_id: str = "jarvis") -> None:
    with get_session() as s:
        if s.get(Persona, persona_id) is None:
            s.add(Persona(persona_id=persona_id, display_name="JARVIS"))


def _seed_session_with_messages(
    *, session_id: str, user_id: str, persona_id: str, message_contents: list[str]
) -> None:
    with get_session() as s:
        s.add(
            ChatSession(
                session_id=session_id,
                user_id=user_id,
                persona_id=persona_id,
                started_at=datetime(2026, 6, 14, 12, 0, 0),
            )
        )
        for content in message_contents:
            s.add(Message(session_id=session_id, role="user", content=content))


# ── load_system_terms ────────────────────────────────────────────────────


def test_load_system_terms_returns_builtins_when_file_missing(tmp_path):
    terms = load_system_terms(config_dir=tmp_path)  # no biasing_system.txt
    assert "Newton" in terms
    assert "BGE-M3" in terms


def test_load_system_terms_reads_file(tmp_path):
    (tmp_path / "biasing_system.txt").write_text("Alpha\nBeta\n# comment\n\nGamma\n")
    assert load_system_terms(config_dir=tmp_path) == ["Alpha", "Beta", "Gamma"]


def test_load_system_terms_empty_file_falls_back(tmp_path):
    (tmp_path / "biasing_system.txt").write_text("# only comments\n\n")
    terms = load_system_terms(config_dir=tmp_path)
    assert "Newton" in terms  # built-in fallback


def test_shipped_system_terms_file_is_valid():
    """The repo's config/biasing_system.txt must parse and be non-empty."""
    terms = load_system_terms(config_dir=None)
    assert len(terms) >= 5
    assert "Newton" in terms
    assert "BGE-M3" in terms


# ── _dedupe_preserve ────────────────────────────────────────────────────


def test_dedupe_preserves_first_occurrence_casing():
    assert _dedupe_preserve(["BGE-M3", "bge-m3", "Newton"]) == ["BGE-M3", "Newton"]


def test_dedupe_strips_and_skips_empty():
    assert _dedupe_preserve(["  Alpha  ", "", "   "]) == ["Alpha"]


# ── tier composition ────────────────────────────────────────────────────


def _no_op_extractor(_text: str) -> list[str]:
    return []


def test_system_tier_alone_when_no_user_no_session(isolated_db):
    init_db()
    _seed_user(user_id="sir", bias_dict=[])
    bd = BiasingDict(
        system_terms=["Newton", "BGE-M3"], extract_entities=_no_op_extractor
    )
    with get_session() as s:
        prompt = bd.build_prompt(s, "sir", session_id=None)
    assert prompt == "Domain context: Newton, BGE-M3."


def test_user_tier_appends_personal_vocab(isolated_db):
    init_db()
    _seed_user(user_id="sir", bias_dict=["Stella", "Alex"])
    bd = BiasingDict(system_terms=["Newton"], extract_entities=_no_op_extractor)
    with get_session() as s:
        tiers = bd.tiers(s, "sir")
    assert tiers.system == ["Newton"]
    assert tiers.user == ["Stella", "Alex"]


def test_context_tier_extracts_from_session_messages(isolated_db):
    init_db()
    _seed_persona()
    _seed_user(user_id="sir", bias_dict=[])
    _seed_session_with_messages(
        session_id="T1",
        user_id="sir",
        persona_id="jarvis",
        message_contents=["talking about Newton", "RTX 5090 again"],
    )

    seen: list[str] = []

    def extractor(text: str) -> list[str]:
        # Naive extractor — just split on whitespace and capitalize.
        words = [w.strip(",.").title() for w in text.split() if w.strip(",.")]
        seen.extend(words)
        return [w for w in words if w.istitle() and len(w) > 1]

    bd = BiasingDict(
        system_terms=["Foo"], extract_entities=extractor, context_messages=5
    )
    with get_session() as s:
        tiers = bd.tiers(s, "sir", session_id="T1")
    # Extractor ran on both messages
    assert "Newton" in tiers.context or "RTX" in [t.title() for t in tiers.context]


def test_build_prompt_combines_all_tiers(isolated_db):
    init_db()
    _seed_persona()
    _seed_user(user_id="sir", bias_dict=["Stella", "Alex"])
    _seed_session_with_messages(
        session_id="T1",
        user_id="sir",
        persona_id="jarvis",
        message_contents=["talking about Apple Stock"],
    )

    def extractor(text: str) -> list[str]:
        return [w.strip(",.") for w in text.split() if w[0].isupper()]

    bd = BiasingDict(system_terms=["Newton"], extract_entities=extractor)
    with get_session() as s:
        prompt = bd.build_prompt(s, "sir", session_id="T1")
    # Order: system → user → context, deduped.
    assert prompt.startswith("Domain context: Newton, Stella, Alex,")
    assert "Apple" in prompt


# ── deduplication across tiers ──────────────────────────────────────────


def test_dedupe_across_tiers(isolated_db):
    init_db()
    _seed_user(user_id="sir", bias_dict=["Newton", "Stella"])  # Newton dupes system
    bd = BiasingDict(system_terms=["Newton"], extract_entities=_no_op_extractor)
    with get_session() as s:
        prompt = bd.build_prompt(s, "sir")
    # Newton appears once (system); Stella once (user).
    assert prompt.count("Newton") == 1
    assert "Stella" in prompt


# ── user tier robustness ────────────────────────────────────────────────


def test_user_with_malformed_json_yields_empty_user_tier(isolated_db):
    init_db()
    with get_session() as s:
        s.add(User(user_id="sir", display_name="Sir", stt_bias_dict_json="not-json"))
    bd = BiasingDict(system_terms=["Newton"], extract_entities=_no_op_extractor)
    with get_session() as s:
        tiers = bd.tiers(s, "sir")
    assert tiers.user == []


def test_user_with_non_strings_ignored(isolated_db):
    init_db()
    with get_session() as s:
        s.add(
            User(
                user_id="sir",
                display_name="Sir",
                stt_bias_dict_json=json.dumps(["good", 42, None, " "]),
            )
        )
    bd = BiasingDict(system_terms=[], extract_entities=_no_op_extractor)
    with get_session() as s:
        tiers = bd.tiers(s, "sir")
    assert tiers.user == ["good"]


def test_unknown_user_returns_empty_user_tier(isolated_db):
    init_db()
    bd = BiasingDict(system_terms=["Newton"], extract_entities=_no_op_extractor)
    with get_session() as s:
        tiers = bd.tiers(s, "ghost")
    assert tiers.user == []


# ── context-tier sizing ────────────────────────────────────────────────


def test_context_respects_message_limit(isolated_db):
    init_db()
    _seed_persona()
    _seed_user(user_id="sir", bias_dict=[])
    _seed_session_with_messages(
        session_id="T1",
        user_id="sir",
        persona_id="jarvis",
        message_contents=[f"msg{i}" for i in range(20)],
    )

    seen_count = {"n": 0}

    def extractor(_text: str) -> list[str]:
        seen_count["n"] += 1
        return []

    bd = BiasingDict(system_terms=[], extract_entities=extractor, context_messages=3)
    with get_session() as s:
        bd.tiers(s, "sir", session_id="T1")
    assert seen_count["n"] == 3


def test_extractor_exception_does_not_kill_pipeline(isolated_db):
    init_db()
    _seed_persona()
    _seed_user(user_id="sir", bias_dict=["safe"])
    _seed_session_with_messages(
        session_id="T1",
        user_id="sir",
        persona_id="jarvis",
        message_contents=["oh no"],
    )

    def bad_extractor(_text: str) -> list[str]:
        raise RuntimeError("kaboom")

    bd = BiasingDict(
        system_terms=["Newton"],
        extract_entities=bad_extractor,
        context_messages=5,
    )
    with get_session() as s:
        # Should not raise; context tier just stays empty.
        tiers = bd.tiers(s, "sir", session_id="T1")
    assert tiers.system == ["Newton"]
    assert tiers.user == ["safe"]
    assert tiers.context == []


# ── empty prompt ────────────────────────────────────────────────────────


def test_empty_prompt_when_all_tiers_empty(isolated_db):
    init_db()
    _seed_user(user_id="sir", bias_dict=[])
    bd = BiasingDict(system_terms=[], extract_entities=_no_op_extractor)
    with get_session() as s:
        prompt = bd.build_prompt(s, "sir")
    assert prompt == ""


# ── build_default_biasing ──────────────────────────────────────────────


def test_build_default_biasing_loads_system_terms(monkeypatch, tmp_path):
    (tmp_path / "biasing_system.txt").write_text("Alpha\nBeta\n")
    bd = build_default_biasing(config_dir=tmp_path, extract_entities=_no_op_extractor)
    assert isinstance(bd, BiasingDict)
    assert bd.system_terms == ["Alpha", "Beta"]


# ── Tiers dataclass shape ──────────────────────────────────────────────


def test_biasing_tiers_dataclass():
    t = BiasingTiers(system=["a"], user=["b"], context=["c"])
    assert t.system == ["a"]
    assert t.user == ["b"]
    assert t.context == ["c"]
