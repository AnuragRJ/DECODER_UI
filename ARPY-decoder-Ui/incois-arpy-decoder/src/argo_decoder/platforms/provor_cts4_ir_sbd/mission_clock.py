"""Mission clock for PROVOR CTS4 (decoder 301) — Phase-4, adjudicated 2026-09-10.

All day/hour fields in packet 253 are *relative to mission start* (NKE 5.8
§7.2.4.6 wording: "relative to mission start Day"; hour fields carry minutes
0..1439 at 1-minute resolution).  The mission-start epoch is NOT transmitted,
so it is derived from the telemetry itself:

    anchor = median over cycles N of [ FloatTime(session-2 of cycle N)
                                       - (cycle_start_day(N+1)
                                          + cycle_start_hour(N+1)/1440) ]

The identity used is "the next cycle starts when the previous transmission
window closes" — the float restarts its cycle immediately after surfacing.
The estimator is self-checking: all per-cycle estimates must agree within
``CONSISTENCY_TOL_DAYS`` (observed spread on 12170: 66 s over 16 cycles).
When the estimates cluster within ``MIDNIGHT_TOL_DAYS`` of an integer JULD,
the anchor is rounded to that midnight — validated on 12170 where the derived
anchor 23008.0 equals midnight UTC of the GDAC LAUNCH_DATE day and reproduces
GDAC tech ``CLOCK_StartInternalCycle_YYYYMMDDHHMMSS = 20140216034000``
exactly for FloatDay 414 / 0340.

Event-time semantics adjudicated against GDAC 2902086 Rtraj/tech (2026-09-10,
see PROVOR_CTS4_RTRAJ_ADJUDICATION_2026-09-10.md); all mappings were verified
with ZERO residual on 12170 cycles 98-114:

* ``cycle_start``       → float's internal cycle start (GDAC tech
  ``CLOCK_StartInternalCycle_*``; NOT GDAC Rtraj MC 89).
* ``buoy_start``        → Buoyancy Reduction Start == GDAC Rtraj MC 89.
* ``stab``              → first stabilisation == MC 150 (exact, 16/16).
* ``park_desc_start``   → anchors 252 phase-5 reltimes (MC 189 series).
* ``park_desc_end``     → MC 250 (exact).
* ``prof_desc_start``   → anchors 252 phase-7 reltimes (MC 389 series).
* ``prof_desc_end``     → MC 450 (exact).
* ``ascent_start``      → MC 500 (exact); anchors 252 phase-9 (MC 589 series).
* ``ascent_end``        -> pump actions at surface; MC 600 = ascent_end - 10 min
  (NKE: float waits 10 minutes after pressure < 1 bar before surfacing ops).

No GDAC value is copied; GDAC is comparison evidence only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median

from argo_decoder.platforms.provor_cts4_ir_sbd.tech import FloatTime, VectorTech

#: Max spread across per-cycle anchor estimates (days). 12170: 0.00076 d.
CONSISTENCY_TOL_DAYS = 0.02
#: Max distance from an integer JULD to round the anchor to midnight (days).
MIDNIGHT_TOL_DAYS = 0.02
#: NKE-documented wait between ascent completion and surface ops (days).
SURFACE_WAIT_DAYS = 10.0 / 1440.0

_EPOCH = datetime(1950, 1, 1, tzinfo=UTC)


def floattime_juld(ft: FloatTime) -> float:
    """Absolute JULD of a 253 FloatTime (wire DD MM YY; names now true)."""
    dt = datetime(2000 + ft.yy, ft.mm, ft.dd, ft.hh, ft.mi, ft.ss,
                  tzinfo=UTC)
    return (dt - _EPOCH).total_seconds() / 86400.0


def rel_juld(day: int, hour_minutes: int) -> float:
    """Mission-relative day + minutes-of-day as a fractional day offset."""
    return float(day) + float(hour_minutes) / 1440.0


class AnchorInconsistentError(ValueError):
    """Per-cycle mission-start estimates disagree beyond tolerance."""


@dataclass(frozen=True)
class MissionClock:
    """Absolute-time converter for one float group.

    ``anchor_juld`` is the mission-start epoch (JULD). ``rounded_to_midnight``
    records whether the midnight rule fired (evidence: 12170/2902086).
    """

    anchor_juld: float
    n_estimates: int
    spread_days: float
    rounded_to_midnight: bool

    def juld(self, day: int, hour_minutes: int) -> float:
        return self.anchor_juld + rel_juld(day, hour_minutes)

    # -- adjudicated event conversions (VectorTech -> absolute JULD) -------
    def cycle_start(self, vt: VectorTech) -> float:
        return self.juld(vt.cycle_start_day, vt.cycle_start_hour)

    def buoyancy_reduction_start(self, vt: VectorTech) -> float:
        return self.juld(vt.buoy_start_day, vt.buoy_start_hour)

    def first_stabilization(self, vt: VectorTech) -> float:
        return self.juld(vt.stab_day, vt.stab_hour)

    def park_descent_start(self, vt: VectorTech) -> float:
        return self.juld(vt.park_desc_start_day, vt.park_desc_start_hour)

    def park_descent_end(self, vt: VectorTech) -> float:
        return self.juld(vt.park_desc_end_day, vt.park_desc_end_hour)

    def profile_descent_start(self, vt: VectorTech) -> float:
        return self.juld(vt.prof_desc_start_day, vt.prof_desc_start_hour)

    def profile_descent_end(self, vt: VectorTech) -> float:
        return self.juld(vt.prof_desc_end_day, vt.prof_desc_end_hour)

    def ascent_start(self, vt: VectorTech) -> float:
        return self.juld(vt.ascent_start_day, vt.ascent_start_hour)

    def ascent_end(self, vt: VectorTech) -> float:
        return self.juld(vt.ascent_end_day, vt.ascent_end_hour)

    def surfacing(self, vt: VectorTech) -> float:
        """MC 600: ascent end minus the NKE-documented 10-minute wait."""
        return self.ascent_end(vt) - SURFACE_WAIT_DAYS

    def sample_juld(self, phase_anchor_juld: float, reltime_min: int) -> float:
        """252 sample time: minutes since its phase start (NKE §7.2.4.7)."""
        return phase_anchor_juld + float(reltime_min) / 1440.0


def derive_mission_clock(
    vectors_by_cycle: dict[int, list[VectorTech]],
) -> MissionClock:
    """Derive the mission-start epoch from absolute FloatTimes + rel counters.

    For every consecutive cycle pair (N, N+1) present in the mapping, the
    latest session FloatTime of cycle N minus the mission-relative start of
    cycle N+1 estimates the anchor. Requires at least one pair; raises
    :class:`AnchorInconsistentError` when estimates disagree.
    """
    estimates: list[float] = []
    for cyc in sorted(vectors_by_cycle):
        nxt = cyc + 1
        if nxt not in vectors_by_cycle or not vectors_by_cycle[cyc]:
            continue
        # The estimator pairs the latest absolute FloatTime of cycle N with the
        # mission-relative start of cycle N+1, so both operands must come from
        # the SAME end-of-cycle epoch. That epoch is the phase-12 packet, which
        # is the one carrying the completed cycle's counters.
        #
        # Taking `max(...)` over every packet in the buffer instead silently
        # used a phase-1 (surfacing) time whenever cycle N had no phase-12
        # packet. A phase-1 packet belongs to a DIFFERENT mission-day, so the
        # resulting estimate was off by ~0.5 d. That happened for exactly one
        # float in the corpus -- group 03530 / WMO 2902130, whose launch cycle
        # transmits only phases 0 and 1 -- and it alone broke the consistency
        # check (spread 0.536 d) while the other 13 pairs agreed to 2.7e-4 d.
        #
        # Cycles without a phase-12 packet contribute no estimate rather than a
        # wrong one; they cannot pin the anchor, but the remaining pairs can.
        _p12 = [v for v in vectors_by_cycle[cyc] if v.phase == 12]
        if not _p12:
            continue
        latest_ft = max(floattime_juld(v.time) for v in _p12)
        v_next = vectors_by_cycle[nxt][0]
        estimates.append(
            latest_ft - rel_juld(v_next.cycle_start_day, v_next.cycle_start_hour)
        )
    if not estimates:
        raise AnchorInconsistentError(
            "need at least two consecutive cycles with 253 packets to derive "
            "the mission clock"
        )
    med = median(estimates)
    spread = max(estimates) - min(estimates)
    if spread > CONSISTENCY_TOL_DAYS:
        raise AnchorInconsistentError(
            f"mission-start estimates disagree by {spread:.5f} d "
            f"(> {CONSISTENCY_TOL_DAYS} d) — anchor semantics not pinned"
        )
    midnight = round(med)
    if abs(med - midnight) <= MIDNIGHT_TOL_DAYS:
        return MissionClock(float(midnight), len(estimates), spread, True)
    return MissionClock(med, len(estimates), spread, False)
