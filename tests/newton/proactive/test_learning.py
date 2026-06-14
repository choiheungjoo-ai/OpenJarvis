"""Tests for newton.proactive.learning — reactions + penalty + auto-ignore."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner

from newton.cli import cli
from newton.db import get_session, init_db
from newton.models.proactive_notification import ProactiveNotification
from newton.models.user import User
from newton.models.user_pattern import UserPattern
from newton.proactive.config import ReactionLearningConfig
from newton.proactive.learning import (
    compute_pattern_penalty,
    mark_stale_as_ignored,
    record_reaction,
)

CFG = ReactionLearningConfig(
    rejected_weight=0.2,
    rejected_ttl_days=7,
    ignored_weight=0.05,
    ignored_ttl_days=2,
    auto_ignore_minutes=5,
)


def _seed_user(user_id: str = "sir") -> None:
    with get_session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, display_name="Sir"))


def _add_pattern(user_id: str = "sir") -> int:
    with get_session() as s:
        row = UserPattern(
            user_id=user_id,
            pattern_type="time",
            pattern_data_json='{"hour": 9, "kind": "weekly", "weekday": 1}',
            confidence=0.8,
            occurrences=5,
            last_seen=datetime(2026, 6, 14),
        )
        s.add(row)
        s.flush()
        return row.pattern_id


def _add_notif(
    *,
    user_id: str = "sir",
    pattern_id: int | None = None,
    sent_at: datetime | None = None,
    user_response: str | None = None,
    response_at: datetime | None = None,
) -> int:
    with get_session() as s:
        row = ProactiveNotification(
            user_id=user_id,
            trigger_pattern_id=pattern_id,
            notification_text="Sir, predicted action.",
            sent_at=sent_at or datetime(2026, 6, 14, 12, 0, 0),
            user_response=user_response,
            response_at=response_at,
        )
        s.add(row)
        s.flush()
        return row.notification_id


# ── record_reaction ────────────────────────────────────────────────────────


def test_record_reaction_sets_response_fields(isolated_db):
    init_db()
    _seed_user()
    nid = _add_notif()
    now = datetime(2026, 6, 14, 12, 30, 0)

    with get_session() as s:
        result = record_reaction(s, nid, "accepted", now=now)

    assert result.reaction == "accepted"
    assert result.response_at == now
    with get_session() as s:
        row = s.get(ProactiveNotification, nid)
    assert row.user_response == "accepted"
    assert row.response_at == now


def test_record_reaction_rejects_bad_value(isolated_db):
    init_db()
    _seed_user()
    nid = _add_notif()
    with pytest.raises(ValueError, match="reaction must be"):
        with get_session() as s:
            record_reaction(s, nid, "maybe")


def test_record_reaction_unknown_id(isolated_db):
    init_db()
    _seed_user()
    with pytest.raises(ValueError, match="no notification"):
        with get_session() as s:
            record_reaction(s, 9999, "accepted")


def test_record_reaction_can_be_overwritten(isolated_db):
    """A second reaction replaces the first; useful if sir misclicked."""

    init_db()
    _seed_user()
    nid = _add_notif()
    with get_session() as s:
        record_reaction(s, nid, "accepted", now=datetime(2026, 6, 14, 12, 0, 0))
    with get_session() as s:
        result = record_reaction(
            s, nid, "rejected", now=datetime(2026, 6, 14, 13, 0, 0)
        )
    assert result.reaction == "rejected"


# ── compute_pattern_penalty ────────────────────────────────────────────────


def test_no_reactions_means_zero_penalty(isolated_db):
    init_db()
    _seed_user()
    pid = _add_pattern()
    with get_session() as s:
        p = compute_pattern_penalty(s, "sir", pid, CFG)
    assert p == 0.0


def test_rejected_within_ttl_contributes(isolated_db):
    init_db()
    _seed_user()
    pid = _add_pattern()
    now = datetime(2026, 6, 14, 12, 0, 0)
    _add_notif(
        pattern_id=pid,
        user_response="rejected",
        response_at=now - timedelta(days=3),
    )
    with get_session() as s:
        p = compute_pattern_penalty(s, "sir", pid, CFG, now=now)
    assert p == pytest.approx(0.2)


def test_two_rejections_accumulate(isolated_db):
    init_db()
    _seed_user()
    pid = _add_pattern()
    now = datetime(2026, 6, 14, 12, 0, 0)
    for d in (1, 4):
        _add_notif(
            pattern_id=pid,
            user_response="rejected",
            response_at=now - timedelta(days=d),
        )
    with get_session() as s:
        p = compute_pattern_penalty(s, "sir", pid, CFG, now=now)
    assert p == pytest.approx(0.4)


def test_rejected_past_ttl_does_not_count(isolated_db):
    init_db()
    _seed_user()
    pid = _add_pattern()
    now = datetime(2026, 6, 14, 12, 0, 0)
    _add_notif(
        pattern_id=pid,
        user_response="rejected",
        response_at=now - timedelta(days=10),  # > 7 day TTL
    )
    with get_session() as s:
        p = compute_pattern_penalty(s, "sir", pid, CFG, now=now)
    assert p == 0.0


def test_ignored_uses_lighter_weight(isolated_db):
    init_db()
    _seed_user()
    pid = _add_pattern()
    now = datetime(2026, 6, 14, 12, 0, 0)
    _add_notif(
        pattern_id=pid,
        user_response="ignored",
        response_at=now - timedelta(hours=12),
    )
    with get_session() as s:
        p = compute_pattern_penalty(s, "sir", pid, CFG, now=now)
    assert p == pytest.approx(0.05)


def test_penalty_clipped_to_one(isolated_db):
    init_db()
    _seed_user()
    pid = _add_pattern()
    now = datetime(2026, 6, 14, 12, 0, 0)
    # 10 rejections × 0.2 = 2.0 — should clip to 1.0
    for i in range(10):
        _add_notif(
            pattern_id=pid,
            user_response="rejected",
            response_at=now - timedelta(days=i),
        )
    with get_session() as s:
        p = compute_pattern_penalty(s, "sir", pid, CFG, now=now)
    assert p == 1.0


def test_penalty_is_per_pattern(isolated_db):
    init_db()
    _seed_user()
    p_a = _add_pattern()
    p_b = _add_pattern()
    now = datetime(2026, 6, 14, 12, 0, 0)
    _add_notif(
        pattern_id=p_a,
        user_response="rejected",
        response_at=now - timedelta(days=1),
    )
    with get_session() as s:
        pa = compute_pattern_penalty(s, "sir", p_a, CFG, now=now)
        pb = compute_pattern_penalty(s, "sir", p_b, CFG, now=now)
    assert pa == pytest.approx(0.2)
    assert pb == 0.0


# ── mark_stale_as_ignored ─────────────────────────────────────────────────


def test_mark_stale_flips_old_unresponded_rows(isolated_db):
    init_db()
    _seed_user()
    now = datetime(2026, 6, 14, 12, 0, 0)
    stale_id = _add_notif(sent_at=now - timedelta(minutes=10))
    fresh_id = _add_notif(sent_at=now - timedelta(minutes=2))
    responded_id = _add_notif(
        sent_at=now - timedelta(minutes=20),
        user_response="accepted",
        response_at=now - timedelta(minutes=18),
    )

    with get_session() as s:
        count = mark_stale_as_ignored(s, CFG, now=now)
    assert count == 1

    with get_session() as s:
        stale = s.get(ProactiveNotification, stale_id)
        fresh = s.get(ProactiveNotification, fresh_id)
        responded = s.get(ProactiveNotification, responded_id)
    assert stale.user_response == "ignored"
    assert stale.response_at == now
    assert fresh.user_response is None  # too young
    assert responded.user_response == "accepted"  # already responded


# ── anticipation engine respects penalty ──────────────────────────────────


def test_anticipation_score_is_reduced_by_penalty(isolated_db):
    """A pattern with a recent rejection sees its final shrink."""

    from newton.models.tool_approval import ToolApproval
    from newton.proactive.anticipation import AnticipationEngine
    from newton.proactive.config import AnticipationConfig, ModeThresholds
    from newton.proactive.context import Context

    init_db()
    _seed_user()

    with get_session() as s:
        # Sequence pattern at confidence 0.9.
        pat = UserPattern(
            user_id="sir",
            pattern_type="sequence",
            pattern_data_json=json.dumps(
                {
                    "kind": "sequence",
                    "after_tool": "vault_search",
                    "then_tool": "vault_write",
                    "within_seconds": 600,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            confidence=0.9,
            occurrences=10,
            last_seen=datetime(2026, 6, 14),
        )
        s.add(pat)
        s.flush()
        pid = pat.pattern_id

    now = datetime(2026, 6, 14, 12, 0, 0)
    cfg = AnticipationConfig(
        default_mode="smart",
        relevance_sigma_minutes=30,
        sequence_relevance_seconds=600,
        max_results=5,
        thresholds=ModeThresholds(),
    )
    engine = AnticipationEngine(config=cfg, reactions=CFG)

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
    with get_session() as s:
        baseline = engine.predict(s, ctx, mode="smart")
    assert len(baseline) == 1
    assert baseline[0].rationale.penalty == 0.0
    base_final = baseline[0].final

    # Record a rejection on the same pattern.
    _add_notif(
        pattern_id=pid,
        user_response="rejected",
        response_at=now - timedelta(days=1),
    )

    with get_session() as s:
        after = engine.predict(s, ctx, mode="smart")
    if after:
        p = after[0]
        # final = 0.9 × (1 - 0.2) × 1.0 = 0.72 — still passes smart 0.7
        assert p.rationale.penalty == pytest.approx(0.2)
        assert p.final == pytest.approx(base_final * 0.8, rel=1e-6)
        assert "penalty" in p.rationale.explain()


def test_repeated_rejection_drives_below_threshold(isolated_db):
    """Three rejections in 7 days × 0.2 = 0.6 penalty → final 0.36 < smart 0.7."""

    from newton.models.tool_approval import ToolApproval
    from newton.proactive.anticipation import AnticipationEngine
    from newton.proactive.config import AnticipationConfig, ModeThresholds
    from newton.proactive.context import Context

    init_db()
    _seed_user()

    with get_session() as s:
        pat = UserPattern(
            user_id="sir",
            pattern_type="sequence",
            pattern_data_json=json.dumps(
                {
                    "kind": "sequence",
                    "after_tool": "vault_search",
                    "then_tool": "vault_write",
                    "within_seconds": 600,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            confidence=0.9,
            occurrences=10,
            last_seen=datetime(2026, 6, 14),
        )
        s.add(pat)
        s.flush()
        pid = pat.pattern_id

    now = datetime(2026, 6, 14, 12, 0, 0)
    for d in (1, 2, 3):
        _add_notif(
            pattern_id=pid,
            user_response="rejected",
            response_at=now - timedelta(days=d),
        )

    engine = AnticipationEngine(
        config=AnticipationConfig(
            default_mode="smart",
            relevance_sigma_minutes=30,
            sequence_relevance_seconds=600,
            max_results=5,
            thresholds=ModeThresholds(),
        ),
        reactions=CFG,
    )
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
    with get_session() as s:
        preds = engine.predict(s, ctx, mode="smart")
    # 0.9 × (1-0.6) × 1.0 = 0.36 — below 0.7
    assert preds == []


# ── CLI ──────────────────────────────────────────────────────────────────


def test_cli_react_records_and_lists(seeded_db):
    runner = CliRunner()
    nid = _add_notif()

    result = runner.invoke(cli, ["proactive", "react", str(nid), "--reject", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["reaction"] == "rejected"

    listed = runner.invoke(cli, ["proactive", "notifications", "--last", "5", "--json"])
    assert listed.exit_code == 0
    rows = json.loads(listed.output)
    target = next(r for r in rows if r["notification_id"] == nid)
    assert target["user_response"] == "rejected"


def test_cli_react_missing_flag_errors(seeded_db):
    nid = _add_notif()
    runner = CliRunner()
    result = runner.invoke(cli, ["proactive", "react", str(nid)])
    assert result.exit_code == 1
    assert "--accept" in result.output


def test_cli_notifications_pending_only(seeded_db):
    nid_pending = _add_notif()
    nid_accepted = _add_notif(
        user_response="accepted", response_at=datetime(2026, 6, 14)
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["proactive", "notifications", "--pending-only", "--json", "--last", "20"],
    )
    assert result.exit_code == 0
    rows = json.loads(result.output)
    ids = {r["notification_id"] for r in rows}
    assert nid_pending in ids
    assert nid_accepted not in ids
