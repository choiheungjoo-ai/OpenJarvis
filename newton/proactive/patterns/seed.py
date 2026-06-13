"""Deterministic synthetic data for pattern detection tests + the
``newton proactive seed-test-data`` CLI command.

We need data that:

    * spans the full ``observation_window_days`` (default 28),
    * exhibits *known* time and sequence patterns at known counts so
      tests can assert exact numerator / denominator values,
    * is reproducible — same seed in, same data out, no flakey
      time-of-day surprises.

The generator uses ``random.Random(seed)`` exclusively (never the
global ``random`` namespace) so a seeded run is fully deterministic
even when the host's RNG state is dirty.

Known patterns the default scenario produces (with ``seed=42`` and
4 weeks, anchoring at ``end_at_local`` Mon 03:00 KST so each weekday
appears exactly 4 times):

    * weekday=1 (Tue), hour=9: 4 sessions on 4 Tuesdays   → 4/4
    * weekday=4 (Fri), hour=18: 3 sessions on 4 Fridays   → 3/4
    * weekday=2 (Wed), hour=14: 1 session  on 4 Wednesdays→ 1/4 (gated)
    * vault_search → vault_write within 10 min: 6/8 anchors
    * a 3-burst of vault_search inside a 90 s window (dedupes to 1)

Test assertions hard-code those counts; changing the generator
without updating the tests will be loud.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from newton.models.chat_session import ChatSession
from newton.models.tool_approval import ToolApproval


@dataclass
class SeedReport:
    """What the seed generator produced — for the CLI to print."""

    sessions_added: int = 0
    tool_approvals_added: int = 0
    weeks: int = 0
    seed: int = 0
    user_id: str = ""
    expected_patterns: list[str] = field(default_factory=list)


def _utc(dt_local: datetime, tz_name: str) -> datetime:
    """Convert a naive local datetime to naive UTC for SQLite storage."""
    return (
        dt_local.replace(tzinfo=ZoneInfo(tz_name))
        .astimezone(ZoneInfo("UTC"))
        .replace(tzinfo=None)
    )


def seed_test_data(
    session: Session,
    user_id: str = "sir",
    persona_id: str = "jarvis",
    weeks: int = 4,
    seed: int = 42,
    tz_name: str = "Asia/Seoul",
    end_at_local: datetime | None = None,
) -> SeedReport:
    """Insert a known mix of sessions + tool_approvals for pattern testing.

    Returns counts; the rows are inserted via ``session.add`` and the
    caller commits.

    ``end_at_local`` anchors the window's right edge. Default is a
    fixed wall-clock instant (2026-06-15 Mon 03:00 KST) so the same
    seed produces the same data forever — picking ``datetime.now()``
    would make tests flake if run on different weekdays.
    """
    rng = random.Random(seed)
    report = SeedReport(
        weeks=weeks,
        seed=seed,
        user_id=user_id,
        expected_patterns=[
            "weekly tue@9 — 4/4 (full consistency, volume-capped)",
            "weekly fri@18 — 3/4 (partial consistency)",
            "weekly wed@14 — 1/4 (below floor → 0.0)",
            "weekly fri@11 — 1/4 (below floor → 0.0; keeps Fri denom at 4)",
            "sequence vault_search→vault_write — 6/9 "
            "(8 spread + 1 burst anchor; burst dedupes 3→1)",
        ],
    )

    if end_at_local is None:
        # Mon 2026-06-15 03:00 KST — chosen so each weekday in the
        # 4-week window appears the same number of times.
        end_at_local = datetime(2026, 6, 15, 3, 0, 0)

    # The first day of the window: 4 weeks before end_at_local, at 00:00.
    start_local = (end_at_local - timedelta(weeks=weeks)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # ── Time-pattern sessions ──────────────────────────────────────────
    # Tue@9: all 4 weeks
    # Fri@18: weeks 1, 2, 4 (skip week 3)
    # Wed@14: week 2 only (deliberately below floor)
    for week in range(weeks):
        week_start = start_local + timedelta(weeks=week)
        # locate the Tuesday in this week
        tuesday = week_start + timedelta(days=(1 - week_start.weekday()) % 7)
        friday = week_start + timedelta(days=(4 - week_start.weekday()) % 7)
        wednesday = week_start + timedelta(days=(2 - week_start.weekday()) % 7)

        # Tue@9 — 4 weeks, always present
        session.add(
            ChatSession(
                session_id=f"seed-tue-{week}",
                user_id=user_id,
                persona_id=persona_id,
                started_at=_utc(
                    tuesday.replace(hour=9, minute=5 + rng.randint(0, 20)),
                    tz_name,
                ),
            )
        )
        report.sessions_added += 1

        # Fri@18 — skip week index 2 (3rd week)
        if week != 2:
            session.add(
                ChatSession(
                    session_id=f"seed-fri-{week}",
                    user_id=user_id,
                    persona_id=persona_id,
                    started_at=_utc(
                        friday.replace(hour=18, minute=rng.randint(0, 30)),
                        tz_name,
                    ),
                )
            )
            report.sessions_added += 1
        else:
            # Week 2: sir's still around on Friday — just not at 18:00.
            # This keeps the Friday *denominator* at 4 (the count of
            # Fridays with ≥1 session by sir), so Fri@18's consistency
            # is a real 3/4 instead of a gated-out 3/3.
            session.add(
                ChatSession(
                    session_id=f"seed-fri-other-{week}",
                    user_id=user_id,
                    persona_id=persona_id,
                    started_at=_utc(
                        friday.replace(hour=11, minute=0),
                        tz_name,
                    ),
                )
            )
            report.sessions_added += 1

        # Wed@14 — week 1 only
        if week == 1:
            session.add(
                ChatSession(
                    session_id=f"seed-wed-{week}",
                    user_id=user_id,
                    persona_id=persona_id,
                    started_at=_utc(
                        wednesday.replace(hour=14, minute=10),
                        tz_name,
                    ),
                )
            )
            report.sessions_added += 1

    # ── Sequence-pattern tool_approvals ────────────────────────────────
    # 8 vault_search anchors over the window. 6 of them are followed
    # by a vault_write within 10 min; 2 are not.
    base_local = start_local + timedelta(days=1, hours=10)
    for i in range(8):
        anchor_local = base_local + timedelta(days=i * 3)
        session.add(
            ToolApproval(
                tool_name="vault_search",
                risk_level=1,
                user_id=user_id,
                decision="approved",
                decided_at=_utc(anchor_local, tz_name),
            )
        )
        report.tool_approvals_added += 1
        if i < 6:
            # Add the follow-up vault_write within window
            session.add(
                ToolApproval(
                    tool_name="vault_write",
                    risk_level=2,
                    user_id=user_id,
                    decision="approved",
                    decided_at=_utc(
                        anchor_local + timedelta(minutes=2 + i % 5),
                        tz_name,
                    ),
                )
            )
            report.tool_approvals_added += 1

    # Dedupe check: three vault_search in 90 s on a single day.
    # These collapse to 1 anchor in the sequence detector; the unit
    # test for sequence asserts the count is unaffected.
    burst_local = base_local + timedelta(days=20)
    for offset in (0, 30, 60):
        session.add(
            ToolApproval(
                tool_name="vault_search",
                risk_level=1,
                user_id=user_id,
                decision="approved",
                decided_at=_utc(burst_local + timedelta(seconds=offset), tz_name),
            )
        )
        report.tool_approvals_added += 1

    # A denied attempt — must NOT be counted by approved_tool_runs_in_window.
    session.add(
        ToolApproval(
            tool_name="vault_write",
            risk_level=2,
            user_id=user_id,
            decision="denied",
            decided_at=_utc(burst_local + timedelta(minutes=5), tz_name),
        )
    )
    report.tool_approvals_added += 1

    return report


__all__ = ["SeedReport", "seed_test_data"]
