"""Tests for the anticipation engine."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from click.testing import CliRunner

from newton.cli import cli
from newton.db import get_session, init_db
from newton.models.tool_approval import ToolApproval
from newton.models.user import User
from newton.models.user_pattern import UserPattern
from newton.proactive.anticipation import (
    AnticipationEngine,
    RelevanceResult,
    RelevanceStrategy,
    TimeProximityRelevance,
)
from newton.proactive.config import (
    AnticipationConfig,
    ModeThresholds,
)
from newton.proactive.context import Context, assemble


def _utc(dt_local: datetime, tz: str = "Asia/Seoul") -> datetime:
    return (
        dt_local.replace(tzinfo=ZoneInfo(tz))
        .astimezone(ZoneInfo("UTC"))
        .replace(tzinfo=None)
    )


def _seed_user(user_id: str = "sir") -> None:
    with get_session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, display_name="Sir"))


def _add_pattern(
    *,
    user_id: str,
    pattern_type: str,
    signature: dict,
    confidence: float,
    occurrences: int = 5,
    last_seen: datetime | None = None,
) -> int:
    with get_session() as s:
        row = UserPattern(
            user_id=user_id,
            pattern_type=pattern_type,
            pattern_data_json=json.dumps(
                signature, sort_keys=True, separators=(",", ":")
            ),
            confidence=confidence,
            occurrences=occurrences,
            last_seen=last_seen or datetime(2026, 6, 14, 0, 0, 0),
        )
        s.add(row)
        s.flush()
        return row.pattern_id


CFG = AnticipationConfig(
    default_mode="smart",
    relevance_sigma_minutes=30.0,
    sequence_relevance_seconds=600,
    max_results=5,
    thresholds=ModeThresholds(off=1.01, minimal=0.9, smart=0.7, aggressive=0.5),
)


# ── time-pattern relevance ─────────────────────────────────────────────────


def test_weekly_relevance_peaks_at_local_eta(isolated_db):
    init_db()
    _seed_user()
    # Tue 09:00 KST pattern
    pid = _add_pattern(
        user_id="sir",
        pattern_type="time",
        signature={"kind": "weekly", "weekday": 1, "hour": 9},
        confidence=0.8,
    )
    # now = exactly Tue 09:00 KST = Mon 24:00 = Tue 00:00 UTC
    now_utc = _utc(datetime(2026, 6, 16, 9, 0, 0))

    engine = AnticipationEngine(config=CFG)
    with get_session() as s:
        ctx = Context(user_id="sir", now=now_utc)
        preds = engine.predict(s, ctx, mode="smart")

    matching = [p for p in preds if p.pattern_id == pid]
    assert len(matching) == 1
    p = matching[0]
    assert p.rationale.relevance == pytest.approx(1.0, abs=1e-6)
    # final = 0.8 × 1.0 = 0.8 ≥ smart threshold 0.7 → pass
    assert p.rationale.threshold_passed is True
    assert p.final == pytest.approx(0.8, abs=1e-6)


def test_weekly_relevance_decays_with_distance(isolated_db):
    init_db()
    _seed_user()
    pid = _add_pattern(
        user_id="sir",
        pattern_type="time",
        signature={"kind": "weekly", "weekday": 1, "hour": 9},
        confidence=0.9,
    )
    # now = Tue 10:00 KST = 60 min past eta
    now_utc = _utc(datetime(2026, 6, 16, 10, 0, 0))

    engine = AnticipationEngine(config=CFG)
    with get_session() as s:
        preds = engine.predict(s, Context(user_id="sir", now=now_utc), mode="smart")

    # Gaussian σ=30 ⇒ at 60min: exp(-((60/30)^2)/2) = exp(-2) ≈ 0.135
    matching = [p for p in preds if p.pattern_id == pid]
    # final = 0.9 × 0.135 ≈ 0.12 — below smart threshold 0.7
    assert matching == [], "should be filtered out by mode threshold"


def test_weekly_eta_is_next_future_occurrence(isolated_db):
    """ETA is the next future occurrence, not the closer past one."""

    init_db()
    _seed_user()
    _add_pattern(
        user_id="sir",
        pattern_type="time",
        signature={"kind": "weekly", "weekday": 1, "hour": 9},
        confidence=0.95,
    )
    # now = Tue 08:55 KST — past occurrence is 7 days ago, next is in 5 minutes
    now_utc = _utc(datetime(2026, 6, 16, 8, 55, 0))

    engine = AnticipationEngine(config=CFG)
    with get_session() as s:
        preds = engine.predict(s, Context(user_id="sir", now=now_utc), mode="smart")
    assert len(preds) >= 1
    p = preds[0]
    assert p.eta is not None
    # ETA should be Tue 09:00 KST = Tue 00:00 UTC = same day
    expected_eta = _utc(datetime(2026, 6, 16, 9, 0, 0))
    assert p.eta == expected_eta


# ── sequence relevance ────────────────────────────────────────────────────


def test_sequence_relevant_when_a_just_ran(isolated_db):
    init_db()
    _seed_user()
    pid = _add_pattern(
        user_id="sir",
        pattern_type="sequence",
        signature={
            "kind": "sequence",
            "after_tool": "vault_search",
            "then_tool": "vault_write",
            "within_seconds": 600,
        },
        confidence=0.8,
    )

    now = datetime(2026, 6, 14, 12, 0, 0)
    ctx = Context(
        user_id="sir",
        now=now,
        recent_runs=[
            ToolApproval(
                tool_name="vault_search",
                risk_level=1,
                user_id="sir",
                decision="approved",
                decided_at=now - timedelta(minutes=2),
            )
        ],
    )

    engine = AnticipationEngine(config=CFG)
    with get_session() as s:
        preds = engine.predict(s, ctx, mode="smart")

    matching = [p for p in preds if p.pattern_id == pid]
    assert len(matching) == 1
    p = matching[0]
    assert p.rationale.relevance == 1.0
    assert p.final == pytest.approx(0.8)
    # eta = last_a + within_seconds → 8 minutes after now
    assert p.eta is not None
    expected = (now - timedelta(minutes=2)) + timedelta(seconds=600)
    assert p.eta == expected


def test_sequence_irrelevant_when_a_did_not_run(isolated_db):
    init_db()
    _seed_user()
    _add_pattern(
        user_id="sir",
        pattern_type="sequence",
        signature={
            "kind": "sequence",
            "after_tool": "vault_search",
            "then_tool": "vault_write",
            "within_seconds": 600,
        },
        confidence=0.9,
    )

    engine = AnticipationEngine(config=CFG)
    with get_session() as s:
        preds = engine.predict(
            s,
            Context(user_id="sir", now=datetime(2026, 6, 14, 12, 0, 0)),
            mode="smart",
        )
    assert preds == []


# ── mode gating ──────────────────────────────────────────────────────────


def test_off_mode_never_fires(isolated_db):
    init_db()
    _seed_user()
    _add_pattern(
        user_id="sir",
        pattern_type="time",
        signature={"kind": "weekly", "weekday": 1, "hour": 9},
        confidence=1.0,
    )
    now_utc = _utc(datetime(2026, 6, 16, 9, 0, 0))

    engine = AnticipationEngine(config=CFG)
    with get_session() as s:
        preds = engine.predict(s, Context(user_id="sir", now=now_utc), mode="off")
    assert preds == []


def test_minimal_requires_higher_confidence_than_smart(isolated_db):
    init_db()
    _seed_user()
    _add_pattern(
        user_id="sir",
        pattern_type="time",
        signature={"kind": "weekly", "weekday": 1, "hour": 9},
        confidence=0.75,
    )
    now_utc = _utc(datetime(2026, 6, 16, 9, 0, 0))

    engine = AnticipationEngine(config=CFG)
    with get_session() as s:
        smart = engine.predict(s, Context(user_id="sir", now=now_utc), mode="smart")
        minimal = engine.predict(s, Context(user_id="sir", now=now_utc), mode="minimal")

    # final = 0.75 × 1.0 = 0.75
    # smart threshold 0.7 → pass; minimal threshold 0.9 → fail
    assert len(smart) == 1
    assert minimal == []


# ── sort + cap ───────────────────────────────────────────────────────────


def test_predictions_sorted_by_final_desc_and_capped(isolated_db):
    init_db()
    _seed_user()
    # Three sequence patterns. They all become fully relevant when their
    # respective A-tools have run recently — guarantees three crossings.
    for tool, conf in [("ta", 0.6), ("tb", 0.95), ("tc", 0.75)]:
        _add_pattern(
            user_id="sir",
            pattern_type="sequence",
            signature={
                "kind": "sequence",
                "after_tool": tool,
                "then_tool": "tx",
                "within_seconds": 600,
            },
            confidence=conf,
        )

    cfg = AnticipationConfig(
        default_mode="aggressive",
        relevance_sigma_minutes=30.0,
        sequence_relevance_seconds=600,
        max_results=2,
        thresholds=ModeThresholds(),
    )
    engine = AnticipationEngine(config=cfg)
    now = datetime(2026, 6, 14, 12, 0, 0)
    ctx = Context(
        user_id="sir",
        now=now,
        recent_runs=[
            ToolApproval(
                tool_name=t,
                risk_level=1,
                user_id="sir",
                decision="approved",
                decided_at=now - timedelta(minutes=1),
            )
            for t in ("ta", "tb", "tc")
        ],
    )
    with get_session() as s:
        preds = engine.predict(s, ctx, mode="aggressive")

    assert len(preds) == 2, f"expected max_results=2 cap, got {len(preds)}"
    assert preds[0].final >= preds[1].final
    # Top one must be the 0.95-confidence pattern (tb).
    assert preds[0].rationale.factors["after_tool"] == "tb"


# ── swappable strategy ───────────────────────────────────────────────────


def test_custom_relevance_strategy_used(isolated_db):
    """A user-supplied strategy replaces TimeProximityRelevance entirely."""

    init_db()
    _seed_user()
    pid = _add_pattern(
        user_id="sir",
        pattern_type="time",
        signature={"kind": "weekly", "weekday": 1, "hour": 9},
        confidence=0.5,
    )

    class AlwaysOne(RelevanceStrategy):
        def evaluate(self, **kwargs) -> RelevanceResult:  # noqa: ARG002
            return RelevanceResult(
                relevance=1.0, eta=None, factors={"src": "AlwaysOne"}
            )

    engine = AnticipationEngine(config=CFG, relevance=AlwaysOne())
    with get_session() as s:
        preds = engine.predict(
            s,
            Context(user_id="sir", now=datetime(2026, 6, 14, 12, 0, 0)),
            mode="smart",
        )

    # AlwaysOne → relevance 1.0, final = 0.5 — below smart 0.7
    assert preds == []

    with get_session() as s:
        preds_agg = engine.predict(
            s,
            Context(user_id="sir", now=datetime(2026, 6, 14, 12, 0, 0)),
            mode="aggressive",
        )
    assert len(preds_agg) == 1
    assert preds_agg[0].pattern_id == pid
    assert preds_agg[0].rationale.factors.get("src") == "AlwaysOne"


# ── zero-confidence short-circuit ────────────────────────────────────────


def test_zero_confidence_patterns_skipped(isolated_db):
    init_db()
    _seed_user()
    _add_pattern(
        user_id="sir",
        pattern_type="time",
        signature={"kind": "weekly", "weekday": 1, "hour": 9},
        confidence=0.0,
    )
    now_utc = _utc(datetime(2026, 6, 16, 9, 0, 0))

    engine = AnticipationEngine(config=CFG)
    with get_session() as s:
        preds = engine.predict(
            s, Context(user_id="sir", now=now_utc), mode="aggressive"
        )
    assert preds == []


# ── rationale explainability ─────────────────────────────────────────────


def test_rationale_includes_factors_and_explain(isolated_db):
    init_db()
    _seed_user()
    _add_pattern(
        user_id="sir",
        pattern_type="time",
        signature={"kind": "weekly", "weekday": 1, "hour": 9},
        confidence=0.85,
    )
    now_utc = _utc(datetime(2026, 6, 16, 9, 0, 0))

    engine = AnticipationEngine(config=CFG)
    with get_session() as s:
        preds = engine.predict(s, Context(user_id="sir", now=now_utc), mode="smart")
    p = preds[0]
    text = p.rationale.explain()
    assert "confidence" in text and "relevance" in text and "threshold" in text
    assert "sigma_minutes" in p.rationale.factors


# ── CLI ──────────────────────────────────────────────────────────────────


def test_cli_predict_no_patterns(seeded_db):
    runner = CliRunner()
    result = runner.invoke(cli, ["proactive", "predict", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_cli_predict_returns_payload(seeded_db):
    _add_pattern(
        user_id="sir",
        pattern_type="time",
        signature={"kind": "weekly", "weekday": 1, "hour": 9},
        confidence=0.95,
        last_seen=datetime(2026, 6, 14),
    )
    runner = CliRunner()
    # Force a moment that lines up with the pattern's local 09:00 KST
    # eta by indirectly relying on the engine's choice of mode; here
    # we just check the CLI returns *something* parseable.
    result = runner.invoke(
        cli, ["proactive", "predict", "--mode", "aggressive", "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    # May or may not have results depending on real wall clock; the
    # important thing is the payload shape is well-formed.
    assert isinstance(payload, list)


# ── context.assemble ─────────────────────────────────────────────────────


def test_context_assemble_includes_recent_approved_runs(isolated_db):
    init_db()
    _seed_user()
    now = datetime(2026, 6, 14, 12, 0, 0)
    with get_session() as s:
        s.add(
            ToolApproval(
                tool_name="vault_search",
                risk_level=1,
                user_id="sir",
                decision="approved",
                decided_at=now - timedelta(minutes=2),
            )
        )
        s.add(
            ToolApproval(
                tool_name="vault_write",
                risk_level=2,
                user_id="sir",
                decision="denied",
                decided_at=now - timedelta(minutes=1),
            )
        )

    with get_session() as s:
        ctx = assemble(s, "sir", now=now, lookback_seconds=600)

    # Approved only.
    tools = {r.tool_name for r in ctx.recent_runs}
    assert tools == {"vault_search"}


def test_context_lookback_excludes_old_runs(isolated_db):
    init_db()
    _seed_user()
    now = datetime(2026, 6, 14, 12, 0, 0)
    with get_session() as s:
        s.add(
            ToolApproval(
                tool_name="vault_search",
                risk_level=1,
                user_id="sir",
                decision="approved",
                decided_at=now - timedelta(hours=2),
            )
        )

    with get_session() as s:
        ctx = assemble(s, "sir", now=now, lookback_seconds=600)
    assert ctx.recent_runs == []


def test_default_relevance_strategy_is_time_proximity():
    eng = AnticipationEngine(config=CFG)
    # Internal default access — assert via the public type
    assert isinstance(eng._relevance, TimeProximityRelevance)  # noqa: SLF001
