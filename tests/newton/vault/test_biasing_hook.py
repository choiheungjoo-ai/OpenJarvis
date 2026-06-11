"""Tests for newton.vault.biasing_hook."""

from __future__ import annotations

import json

import pytest

from newton.vault.biasing_hook import (
    _regex_entities,
    extract_entities,
    on_vault_save,
    update_user_biasing,
)


def _has_model(name: str) -> bool:
    try:
        import spacy

        spacy.load(name)
        return True
    except Exception:  # noqa: BLE001
        return False


# -- regex pass (no spaCy needed) ----------------------------------------------


def test_regex_catches_model_names():
    found = _regex_entities("Newton uses BGE-M3 embeddings on an RTX 5090.")
    assert "BGE-M3" in found
    assert any("RTX" in f and "5090" in f for f in found)


def test_regex_catches_acronyms():
    found = _regex_entities("The ACL gates what STT hears via JARVIS.")
    assert "ACL" in found
    assert "STT" in found
    assert "JARVIS" in found


def test_extract_dedupes_case_insensitively():
    ents = extract_entities("JARVIS and jarvis and Jarvis-7 met JARVIS.")
    lowered = [e.lower() for e in ents]
    assert lowered.count("jarvis") == 1


def test_extract_length_filter():
    # 1-char junk and >60-char strings are dropped.
    long = "X" * 70
    ents = extract_entities(f"A {long} BGE-M3")
    assert long not in ents
    assert "BGE-M3" in ents


# -- user dict merge ------------------------------------------------------------


def test_update_user_biasing_merges_and_dedupes(seeded_db):
    from newton.db import get_session
    from newton.models import User

    with get_session() as session:
        added1 = update_user_biasing(session, "sir", ["BGE-M3", "RTX 5090"])
        assert sorted(added1) == ["BGE-M3", "RTX 5090"]

        # Second call: one duplicate (case-insensitive), one new.
        added2 = update_user_biasing(session, "sir", ["bge-m3", "Qdrant"])
        assert added2 == ["Qdrant"]

        user = session.get(User, "sir")
        entries = json.loads(user.stt_bias_dict_json)
        assert len(entries) == 3


def test_update_unknown_user_returns_empty(seeded_db):
    from newton.db import get_session

    with get_session() as session:
        assert update_user_biasing(session, "nobody", ["X1-Y2"]) == []


def test_on_vault_save_never_raises(seeded_db):
    from newton.db import get_session

    with get_session() as session:
        report = on_vault_save(session, "Newton uses BGE-M3.", "sir")
    assert "entities_added" in report
    assert "BGE-M3" in report["entities_added"]


# -- spaCy NER (skipped when models absent) -------------------------------------


@pytest.mark.skipif(
    not _has_model("en_core_web_sm"), reason="en_core_web_sm not installed"
)
def test_ner_english_person_org():
    ents = extract_entities("Tony Stark founded Stark Industries in California.")
    joined = " ".join(ents)
    assert "Stark" in joined  # person and/or org surfaced


@pytest.mark.skipif(
    not _has_model("ko_core_news_sm"), reason="ko_core_news_sm not installed"
)
def test_ner_korean_entities():
    ents = extract_entities("뉴턴은 서울에서 김철수가 만든 시스템이다.")
    joined = " ".join(ents)
    assert ("서울" in joined) or ("김철수" in joined)
