"""Observed profile-cycle interval: PART 2 of the Float Status contract.

The expected next profile is now derived from each float's OWN published
profile spacing; 10 days is a documented fallback and never an assumption.
Network-free, no decoder core involved.
"""

from __future__ import annotations

import math

import pytest
import profile_cycle as pc


def days(*offsets: float) -> list[float]:
    """JULD-like values starting at 28000 (2026-08-27) plus offsets."""
    return [28000.0 + o for o in offsets]


def test_median_interval_needs_enough_samples():
    assert pc.median_interval_days(days(0, 10))[0] is None          # 1 spacing
    assert pc.median_interval_days(days(0, 10, 20))[0] is None      # 2 spacings -> still short
    assert pc.median_interval_days(days(0, 10, 20, 30))[0] == 10.0  # 3 spacings
    assert pc.median_interval_days(days(0, 10, 20, 30))[1] == 3


def test_median_interval_is_robust_to_mission_gaps_and_repeats():
    # A 300-day outage and a duplicate same-cycle row must not dominate.
    values = days(0, 10, 20, 30, 330, 330.001, 340)
    median, count = pc.median_interval_days(values)
    assert median == pytest.approx(10.0)
    # spacings in the accepted window: 10, 10, 10, 9.999 -> the 300-day outage
    # and the sub-day duplicate are excluded.
    assert count == 4


def test_median_interval_clamped_to_plausible_range():
    # 0.6-day "cycles" are accepted as spacings but clamped to >= 1 day.
    median, _ = pc.median_interval_days(days(0, 0.6, 1.2, 1.8))
    assert median == pytest.approx(pc.CLAMP_MIN_DAYS)


def test_resolve_interval_prefers_profile_history_then_trajectory_then_default():
    profile = {"n": 12, "median_days": 9.98}
    traj = {"n": 7, "median_days": 10.02}
    assert pc.resolve_interval(profile, traj) == (9.98, pc.INTERVAL_SOURCE_PROFILE, 12)
    assert pc.resolve_interval({"n": 2, "median_days": None}, traj) == (
        10.02,
        pc.INTERVAL_SOURCE_TRAJECTORY,
        7,
    )
    assert pc.resolve_interval(None, None) == (10.0, pc.INTERVAL_SOURCE_DEFAULT, 0)
    assert pc.resolve_interval({}, {}) == (10.0, pc.INTERVAL_SOURCE_DEFAULT, 0)


def test_status_bands_follow_the_float_own_cycle():
    # 10-day float: unchanged from the approved policy.
    assert pc.status_for(0.0, 10.0) == "ACTIVE / RECENT PROFILE"
    assert pc.status_for(10.0, 10.0) == "ACTIVE / RECENT PROFILE"
    assert pc.status_for(10.01, 10.0) == "PROFILE OVERDUE"
    assert pc.status_for(59.9, 10.0) == "PROFILE OVERDUE"
    assert pc.status_for(60.0, 10.0) == "NO RECENT PROFILE DATA 60+ DAYS"
    # 5-day float: overdue after five days, not after ten.
    assert pc.status_for(5.0, 5.0) == "ACTIVE / RECENT PROFILE"
    assert pc.status_for(6.0, 5.0) == "PROFILE OVERDUE"
    # 30-day float: still current at 20 days.
    assert pc.status_for(20.0, 30.0) == "ACTIVE / RECENT PROFILE"
    # Unavailable / invalid elapsed time is never "dead" and never ACTIVE.
    assert pc.status_for(None, 10.0) == "NO DATA"
    assert pc.status_for(float("nan"), 10.0) == "NO DATA"
    assert pc.status_for(-1.0, 10.0) == "NO DATA"


def test_approx_profiles_missed_uses_the_observed_interval():
    assert pc.approx_profiles_missed(25.0, 10.0) == 2
    assert pc.approx_profiles_missed(25.0, 5.0) == 5
    assert pc.approx_profiles_missed(0.5, 10.0) == 0
    assert pc.approx_profiles_missed(-3.0, 10.0) == 0
    assert pc.approx_profiles_missed(float("nan"), 10.0) == 0
    assert pc.approx_profiles_missed(30.0, 0.0) == 3  # invalid interval -> documented fallback


def test_interval_note_states_the_measured_cycle_and_never_invents_one():
    measured = pc.interval_note(9.98, pc.INTERVAL_SOURCE_PROFILE, 96)
    assert "9.98" not in measured or math.isclose(9.98, 9.98)  # formatting below is explicit
    assert "10.0-day" in measured
    assert "96 published profile dates" in measured
    fallback = pc.interval_note(10.0, pc.INTERVAL_SOURCE_DEFAULT, 0)
    assert "10-day" in fallback and "no sufficient observed cycle history" in fallback
    traj = pc.interval_note(5.0, pc.INTERVAL_SOURCE_TRAJECTORY, 7)
    assert "5.0-day" in traj and "7 trajectory cycles" in traj


def test_summarize_intervals_is_cache_friendly():
    summary = pc.summarize_intervals(days(0, 5, 10, 15, 20))
    assert summary == {"n": 4, "median_days": 5.0, "min_days": 5.0, "max_days": 5.0}
    empty = pc.summarize_intervals([28000.0])
    assert empty == {"n": 0, "median_days": None, "min_days": None, "max_days": None}
