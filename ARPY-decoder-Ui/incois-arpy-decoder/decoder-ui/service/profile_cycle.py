"""Observed profile-cycle interval estimation (Float Status + prediction).

PART 2 of the task: "Expected Next Profile = Last Profile Date + observed cycle
interval when sufficient history exists. Use 10 days only as fallback."

This module is pure (no IO, no globals beyond constants) so every rule is
unit-testable. It is shared by:

* ``fleet_status.py`` — the Monitoring authority: max valid ``JULD`` in
  ``<WMO>_prof.nc``. The observed interval is a *spacing* statistic over those
  same published profile dates, so the status formulas remain derived from the
  approved source.
* ``service/prediction/`` — the prediction target time and features.

No float-specific constant exists anywhere: the interval is measured per float
from its own history and falls back to the documented 10 UTC-day Argo nominal
cycle only when the history is insufficient.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Iterable, Sequence

#: Documented fallback: the nominal Argo 10-day cycle (UTC days).
DEFAULT_INTERVAL_DAYS = 10.0
#: Accepted observed spacing window. Below MIN a pair is probably the same
#: cycle (or a repeat/descent pair); above MAX it is a mission gap, not a cycle.
MIN_INTERVAL_DAYS = 0.5
MAX_INTERVAL_DAYS = 60.0
#: Minimum number of observed spacings before the measurement is trusted.
MIN_INTERVAL_SAMPLES = 3
#: Hard bounds for a plausible per-float cycle.
CLAMP_MIN_DAYS = 1.0
CLAMP_MAX_DAYS = 45.0

INTERVAL_SOURCE_PROFILE = "profile history"
INTERVAL_SOURCE_TRAJECTORY = "trajectory history"
INTERVAL_SOURCE_DEFAULT = "default 10-day cycle"


def _intervals(julds: Sequence[float]) -> list[float]:
    """Positive consecutive spacings inside the accepted cycle window."""
    ordered = sorted(float(v) for v in julds if v is not None and math.isfinite(float(v)))
    out: list[float] = []
    for previous, current in zip(ordered, ordered[1:]):
        delta = current - previous
        if MIN_INTERVAL_DAYS <= delta <= MAX_INTERVAL_DAYS:
            out.append(delta)
    return out


def median_interval_days(julds: Iterable[float]) -> tuple[float | None, int]:
    """Robust median cycle interval (days) and the number of spacings used.

    Returns ``(None, n)`` when fewer than ``MIN_INTERVAL_SAMPLES`` usable
    spacings exist, so callers must fall back explicitly instead of silently
    inventing a value from one or two pairs.
    """
    spacings = _intervals(list(julds))
    if len(spacings) < MIN_INTERVAL_SAMPLES:
        return None, len(spacings)
    spacings.sort()
    middle = len(spacings) // 2
    if len(spacings) % 2:
        median = spacings[middle]
    else:
        median = 0.5 * (spacings[middle - 1] + spacings[middle])
    if not math.isfinite(median) or median <= 0:
        return None, len(spacings)
    return min(max(median, CLAMP_MIN_DAYS), CLAMP_MAX_DAYS), len(spacings)


def summarize_intervals(julds: Iterable[float]) -> dict[str, object]:
    """Cache-friendly summary (no raw history retained)."""
    values = list(julds)
    median, count = median_interval_days(values)
    spacings = _intervals(values)
    spacings.sort()
    return {
        "n": count,
        "median_days": median,
        "min_days": spacings[0] if spacings else None,
        "max_days": spacings[-1] if spacings else None,
    }


def resolve_interval(
    profile_summary: dict | None,
    trajectory_summary: dict | None = None,
) -> tuple[float, str, int]:
    """(interval_days, source label, samples) with an explicit fallback ladder.

    1. observed ``<WMO>_prof.nc`` profile-date spacing (the monitoring source),
    2. observed ``<WMO>_Rtraj.nc`` cycle spacing,
    3. the documented 10-day default.
    """
    if profile_summary:
        median = profile_summary.get("median_days")
        count = int(profile_summary.get("n") or 0)
        if median is not None:
            return float(median), INTERVAL_SOURCE_PROFILE, count
    if trajectory_summary:
        median = trajectory_summary.get("median_days")
        count = int(trajectory_summary.get("n") or 0)
        if median is not None:
            return float(median), INTERVAL_SOURCE_TRAJECTORY, count
    return DEFAULT_INTERVAL_DAYS, INTERVAL_SOURCE_DEFAULT, 0


def expected_next_profile(last_profile: datetime, interval_days: float) -> datetime:
    return last_profile + timedelta(days=float(interval_days))


def days_since(last_profile: datetime, now: datetime) -> float:
    return (now - last_profile).total_seconds() / 86400.0


def approx_profiles_missed(days_elapsed: float, interval_days: float) -> int:
    """Approximate elapsed/interval estimate.

    Deliberately NOT the exact missing published-file inventory (that stays a
    separate, exact measure in the profile-inventory block).
    """
    if not math.isfinite(days_elapsed) or days_elapsed < 0:
        return 0
    if not math.isfinite(interval_days) or interval_days <= 0:
        interval_days = DEFAULT_INTERVAL_DAYS
    return int(math.floor(days_elapsed / interval_days))


def status_for(days_elapsed: float | None, interval_days: float) -> str:
    """Approved status bands, now driven by the float's own cycle interval.

    Bands (unchanged wording and the fixed 60-day boundary):
      * ``ACTIVE / RECENT PROFILE`` — elapsed <= the float's observed interval
        (identical to the previous behaviour for every 10-day float),
      * ``PROFILE OVERDUE``         — interval < elapsed < 60 days,
      * ``NO RECENT PROFILE DATA 60+ DAYS`` — elapsed >= 60 days,
      * ``NO DATA``                 — no usable published profile date at all.
    """
    if days_elapsed is None or not math.isfinite(days_elapsed) or days_elapsed < 0:
        return "NO DATA"
    interval = float(interval_days or DEFAULT_INTERVAL_DAYS)
    if not math.isfinite(interval) or interval <= 0:
        interval = DEFAULT_INTERVAL_DAYS
    if days_elapsed <= interval:
        return "ACTIVE / RECENT PROFILE"
    if days_elapsed < 60:
        return "PROFILE OVERDUE"
    return "NO RECENT PROFILE DATA 60+ DAYS"


def interval_note(interval_days: float, source: str, samples: int) -> str:
    """Plain-language provenance used by the UI (never a hardcoded 10 days)."""
    if source == INTERVAL_SOURCE_DEFAULT:
        return (
            "Approximate estimate based on the expected 10-day profile cycle "
            "(no sufficient observed cycle history)."
        )
    where = "published profile dates" if source == INTERVAL_SOURCE_PROFILE else "trajectory cycles"
    return (
        f"Approximate estimate based on the observed {interval_days:.1f}-day profile cycle "
        f"(median of {samples} {where})."
    )
