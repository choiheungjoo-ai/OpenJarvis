"""Tests for the quiet-hours predicate."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from newton.proactive.quiet_hours import QuietHoursWindow, parse_hhmm


def _kst_utc(dt_local: datetime) -> datetime:
    return (
        dt_local.replace(tzinfo=ZoneInfo("Asia/Seoul"))
        .astimezone(ZoneInfo("UTC"))
        .replace(tzinfo=None)
    )


def test_parse_hhmm_ok():
    assert parse_hhmm("07:00") == time(7, 0)
    assert parse_hhmm("23:30") == time(23, 30)


def test_parse_hhmm_bad():
    with pytest.raises(ValueError):
        parse_hhmm("seven")


# ── wrap-around window ────────────────────────────────────────────────────


def test_wraparound_quiet_at_late_night():
    """23:00-07:00 should treat 02:00 as quiet."""
    w = QuietHoursWindow(start=time(23, 0), end=time(7, 0), tz_name="Asia/Seoul")
    assert w.is_quiet(_kst_utc(datetime(2026, 6, 14, 2, 0))) is True


def test_wraparound_quiet_just_after_start():
    w = QuietHoursWindow(start=time(23, 0), end=time(7, 0), tz_name="Asia/Seoul")
    assert w.is_quiet(_kst_utc(datetime(2026, 6, 14, 23, 30))) is True


def test_wraparound_not_quiet_at_noon():
    w = QuietHoursWindow(start=time(23, 0), end=time(7, 0), tz_name="Asia/Seoul")
    assert w.is_quiet(_kst_utc(datetime(2026, 6, 14, 12, 0))) is False


def test_wraparound_boundary_inclusive_start_exclusive_end():
    """23:00 is quiet; 07:00 is not."""
    w = QuietHoursWindow(start=time(23, 0), end=time(7, 0), tz_name="Asia/Seoul")
    assert w.is_quiet(_kst_utc(datetime(2026, 6, 14, 23, 0))) is True
    assert w.is_quiet(_kst_utc(datetime(2026, 6, 14, 7, 0))) is False


# ── same-day window ───────────────────────────────────────────────────────


def test_sameday_quiet_inside():
    w = QuietHoursWindow(start=time(12, 0), end=time(14, 0), tz_name="Asia/Seoul")
    assert w.is_quiet(_kst_utc(datetime(2026, 6, 14, 13, 0))) is True


def test_sameday_not_quiet_outside():
    w = QuietHoursWindow(start=time(12, 0), end=time(14, 0), tz_name="Asia/Seoul")
    assert w.is_quiet(_kst_utc(datetime(2026, 6, 14, 11, 0))) is False
    assert w.is_quiet(_kst_utc(datetime(2026, 6, 14, 15, 0))) is False


# ── zero-length window ────────────────────────────────────────────────────


def test_zero_length_window_never_quiet():
    w = QuietHoursWindow(start=time(0, 0), end=time(0, 0), tz_name="Asia/Seoul")
    assert w.is_quiet(_kst_utc(datetime(2026, 6, 14, 0, 0))) is False
    assert w.is_quiet(_kst_utc(datetime(2026, 6, 14, 12, 0))) is False
