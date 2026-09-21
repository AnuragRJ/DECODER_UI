"""Unit tests: Phase-3 scientific rules ported from the Coriolis MATLAB.

Synthetic-data tests for the JAMSTEC GPS QC chain, the clock-offset
selection/interpolation (get_clock_offset_value_prv_ir) and the mail
pre-launch filtering.  Dataset-level validation lives in
``tests/integration/test_arvor_i_science_reconstruction.py``.
"""

from __future__ import annotations

from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import (
    ClockOffsetEvent,
    CycleTimeData,
    GpsRecord,
    clock_offset_for_cycle,
    jamstec_qc,
)


def _gps(cycle: int, date: float, lat: float, lon: float) -> GpsRecord:
    return GpsRecord(cycle=cycle, date=date, lon=lon, lat=lat, mail_date=0.0)


class TestJamstecQc:
    """compute_jamstec_qc.m rules (validated against raw evidence)."""

    def test_first_fix_without_anchor_stays_good(self):
        # regression: the i == 0 / no-anchor branch used to fall through to
        # the intra-cycle branch and compare the record with ITSELF -> qc 4
        recs = [_gps(1, 27456.25, -64.5, 70.0)]
        jamstec_qc(recs)
        assert recs[0].qc == 1

    def test_cross_cycle_byte_identical_reuse_accepted(self):
        # observed on 6990711 c5/c6: identical fix retransmitted at a LATER
        # date.  Only (lat AND lon AND date) equal counts as a duplicate, so
        # the reuse itself is fine when the speed test passes.
        recs = [
            _gps(1, 27456.0, -64.5, 70.0),
            _gps(2, 27466.0, -64.5, 70.0),  # same fix, +10 days, 0 m/s
        ]
        jamstec_qc(recs)
        assert [r.qc for r in recs] == [1, 1]

    def test_same_cycle_exact_duplicate_flagged(self):
        recs = [
            _gps(1, 27456.0, -64.5, 70.0),
            _gps(1, 27456.0, -64.5, 70.0),  # lat+lon+date identical
            _gps(2, 27466.0, -64.6, 70.1),
        ]
        jamstec_qc(recs)
        assert recs[1].qc == 4

    def test_same_cycle_gap_over_one_day_flagged(self):
        recs = [
            _gps(1, 27456.0, -64.5, 70.0),
            _gps(1, 27458.5, -64.55, 70.05),  # 2.5 days later in same cycle
        ]
        jamstec_qc(recs)
        assert recs[1].qc == 4

    def test_anchor_speed_over_limit_flagged(self):
        # ~52 km in 1 hour -> ~14 m/s > 3 m/s
        recs = [
            _gps(1, 27456.0, -64.0, 70.0),
            _gps(2, 27456.0417, -64.4, 70.35),
        ]
        jamstec_qc(recs)
        assert recs[1].qc == 4

    def test_slow_drift_between_cycles_all_good(self):
        # ~30 km / 10 days ~ 0.035 m/s (real 6990711 magnitudes)
        recs = [
            _gps(1, 27456.25, -64.54, 70.08),
            _gps(2, 27466.05, -64.76, 70.22),
            _gps(3, 27475.84, -64.79, 70.54),
        ]
        jamstec_qc(recs)
        assert [r.qc for r in recs] == [1, 1, 1]

    def test_previous_cycle_anchor_is_last_good_fix(self):
        # c1 has a bad last fix (>1 day gap inside c1): the anchor used for
        # c2 must be the last qc == 1 fix of c1, and a flagged fix cannot
        # poison the following cycle.
        recs = [
            _gps(1, 27456.0, -64.5, 70.0),
            _gps(1, 27459.0, -64.5, 70.0),  # gap > 1 day -> qc 4
            _gps(2, 27466.0, -64.6, 70.1),  # anchored on the qc 1 fix
        ]
        jamstec_qc(recs)
        assert recs[1].qc == 4
        assert recs[2].qc == 1


class TestClockOffsetForCycle:
    """get_clock_offset_value_prv_ir.m parity."""

    def test_no_events(self):
        t = CycleTimeData(cycle_num=3, trans_start=27500.0)
        assert clock_offset_for_cycle([], t) is None

    def test_exact_cycle_match_is_mean(self):
        evs = [
            ClockOffsetEvent(cycle=2, float_time=27466.0, offset_s=-10.0),
            ClockOffsetEvent(cycle=2, float_time=27466.01, offset_s=-20.0),
        ]
        t = CycleTimeData(cycle_num=2, trans_start=27466.0)
        assert clock_offset_for_cycle(evs, t) == -15.0

    def test_interpolation_between_events(self):
        # events at c2 (-30 s) and c5 (-60 s); cycle 4 trans at 40% of the
        # [c2, c5] span -> -30 + 0.4 * (-30) = -42
        evs = [
            ClockOffsetEvent(cycle=2, float_time=27466.0, offset_s=-30.0),
            ClockOffsetEvent(cycle=5, float_time=27496.0, offset_s=-60.0),
        ]
        t = CycleTimeData(cycle_num=4, trans_start=27478.0)
        assert clock_offset_for_cycle(evs, t) == -42.0

    def test_interpolation_rounds_to_one_second(self):
        evs = [
            ClockOffsetEvent(cycle=1, float_time=27456.0, offset_s=-5.0),
            ClockOffsetEvent(cycle=3, float_time=27476.0, offset_s=-23.0),
        ]
        t = CycleTimeData(cycle_num=2, trans_start=27457.25)
        # raw: -5 + (1.25/20)*(-18) = -6.125 -> round -> -6
        assert clock_offset_for_cycle(evs, t) == -6.0

    def test_no_bracketing_event_returns_none(self):
        evs = [ClockOffsetEvent(cycle=5, float_time=27496.0, offset_s=-60.0)]
        t = CycleTimeData(cycle_num=3, trans_start=27476.0)
        assert clock_offset_for_cycle(evs, t) is None

    def test_no_reference_time_returns_none(self):
        evs = [
            ClockOffsetEvent(cycle=1, float_time=27456.0, offset_s=-5.0),
            ClockOffsetEvent(cycle=5, float_time=27496.0, offset_s=-60.0),
        ]
        t = CycleTimeData(cycle_num=3)  # no trans/ascent date
        assert clock_offset_for_cycle(evs, t) is None

    def test_cycle_zero_uses_last_event(self):
        # in-air measurements arrive with the last transmitted cycle #0
        evs = [
            ClockOffsetEvent(cycle=0, float_time=27456.0, offset_s=-5.0),
            ClockOffsetEvent(cycle=0, float_time=27460.0, offset_s=-9.0),
        ]
        t = CycleTimeData(cycle_num=0)
        assert clock_offset_for_cycle(evs, t) == -9.0
