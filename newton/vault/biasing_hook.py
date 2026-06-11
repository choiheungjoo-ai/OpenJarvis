"""Vault → STT biasing hook.

Every vault save extracts named entities from the note body and merges them
into the writing user's STT contextual-biasing dictionary
(``users.stt_bias_dict_json``). Block 5 reads that dictionary at every STT
call so Whisper recognises personal vocabulary (project names, products,
people) it would otherwise mangle.

Extraction is two-pass:

  1. spaCy NER (``ko_core_news_sm`` for Korean, ``en_core_web_sm`` for
     English; both run on mixed text). Models load lazily and are cached.
  2. A regex pass for technical patterns spaCy misses — model names like
     "BGE-M3", hardware like "RTX 5090", and all-caps acronyms.

Degradation: spaCy and its models are optional at runtime. If unavailable,
the regex pass still runs and a warning is recorded; a biasing failure must
never break the vault write that triggered it.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Entity labels worth biasing on. GPE = countries/cities, LOC = other
# locations; ko_core_news_sm uses LC for locations and OG for orgs.
_KEEP_LABELS = {
    "PERSON",
    "PS",  # people (en, ko)
    "ORG",
    "OG",  # organisations
    "PRODUCT",
    "GPE",
    "LC",
    "LOC",  # places
    "WORK_OF_ART",
    "EVENT",
    "FAC",
}

# Technical patterns spaCy tends to miss (doc 3.9 mitigation):
#   - model/product codes:  BGE-M3, GPT-4o, Qwen2.5, sm_120
#   - hardware:             RTX 5090, H100
#   - all-caps acronyms:    JARVIS, ACL, STT (3+ letters)
_TECH_PATTERNS = [
    re.compile(r"\b[A-Za-z]+[-_][A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*\b"),
    re.compile(r"\b[A-Z]{2,}[ -]?\d{2,}[A-Za-z0-9]*\b"),
    re.compile(r"\b[A-Z]{3,}\b"),
]

_MIN_LEN = 2
_MAX_LEN = 60
_MAX_DICT = 500  # cap per user so the dict can't grow unbounded

_HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# Lazy spaCy pipelines, keyed by model name. None = tried and unavailable.
_PIPELINES: dict[str, Any] = {}


def _load_pipeline(model: str) -> Any | None:
    if model in _PIPELINES:
        return _PIPELINES[model]
    try:
        import spacy

        nlp = spacy.load(model)
    except Exception:  # noqa: BLE001 — missing lib or model: degrade
        nlp = None
    _PIPELINES[model] = nlp
    return nlp


def _spacy_entities(text: str) -> tuple[list[str], list[str]]:
    """Run NER with every applicable model. Returns (entities, warnings)."""
    entities: list[str] = []
    warnings: list[str] = []

    models: list[str] = []
    if _HANGUL_RE.search(text):
        models.append("ko_core_news_sm")
    if _LATIN_RE.search(text):
        models.append("en_core_web_sm")

    for model in models:
        nlp = _load_pipeline(model)
        if nlp is None:
            warnings.append(f"spaCy model {model} unavailable; regex pass only")
            continue
        doc = nlp(text)
        for ent in doc.ents:
            if ent.label_ in _KEEP_LABELS:
                entities.append(ent.text.strip())
    return entities, warnings


def _regex_entities(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _TECH_PATTERNS:
        found.extend(m.group(0) for m in pattern.finditer(text))
    return found


def _clean(entities: list[str]) -> list[str]:
    """Normalise, length-filter, and dedupe (case-preserving, order-stable)."""
    seen: set[str] = set()
    out: list[str] = []
    for e in entities:
        e = e.strip().strip(".,;:!?\"'()[]{}")
        if not (_MIN_LEN <= len(e) <= _MAX_LEN):
            continue
        key = e.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def extract_entities(text: str, lang: str = "auto") -> list[str]:
    """Extract biasing-worthy entities from text.

    ``lang`` is accepted for the documented signature but detection is
    automatic ("auto"): Korean and/or English models run based on the
    scripts present, and the regex pass always runs.
    """
    ents, _warnings = _spacy_entities(text)
    ents.extend(_regex_entities(text))
    return _clean(ents)


def update_user_biasing(session: Any, user_id: str, entities: list[str]) -> list[str]:
    """Merge ``entities`` into the user's biasing dict. Returns added items."""
    from newton.models import User

    user = session.get(User, user_id)
    if user is None:
        return []

    current: list[str] = json.loads(user.stt_bias_dict_json or "[]")
    existing_keys = {e.lower() for e in current}

    added = [e for e in _clean(entities) if e.lower() not in existing_keys]
    if not added:
        return []

    merged = (current + added)[:_MAX_DICT]
    user.stt_bias_dict_json = json.dumps(merged, ensure_ascii=False)
    session.flush()
    return added


def on_vault_save(session: Any, body: str, user_id: str) -> dict[str, Any]:
    """Hook entry point called after a vault note is saved.

    Never raises: biasing is best-effort and must not break the save.
    Returns a small report for the caller's metadata.
    """
    try:
        ents, warnings = _spacy_entities(body)
        ents.extend(_regex_entities(body))
        added = update_user_biasing(session, user_id, ents)
        return {"entities_added": added, "warnings": warnings}
    except Exception as e:  # noqa: BLE001
        return {"entities_added": [], "warnings": [f"biasing failed: {e}"]}


__all__ = [
    "extract_entities",
    "on_vault_save",
    "update_user_biasing",
]
