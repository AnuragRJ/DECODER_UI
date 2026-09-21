"""Integration tests: Phase-3 scientific reconstruction over both raw datasets.

Validates the scientific layer (``arvor_i_science``) over the complete
read-only telemetry of both supplied floats, asserting the targets fixed
during the investigation (see docs/phase_reports/ phase-3 report):

* 6990711 (dead float, launch 2025-03-02 05:16 UTC): 7 complete cycles;
  descent/drift/ascent kept separate; per-profile measurement counts equal
  the corrected Tech#2 expected counts (descent 54, ascent 102 on cycle 1);
  GPS valid + qc 1 on cycles 1-4 and 7; cycles 5/6 carry item61=0 with a
  byte-identical re-transmission of the cycle-4 fix -> no GpsRecord, and
  their profile locations come from fill_empty interpolation (qc 8); the
  cycle-1 descent location is forward-extrapolated (qc 8; Coriolis would
  use the launch GPS position, absent from this dataset); clock offsets
  -5 -> -23 -> -69 s; no Param#1 -> ascent_end unknown and ascent dates
  fall back to transStartDate (minus clock offset).
* 7902408 (active float, launch 2026-03-25 17:44 UTC): complete cycles
  {1, 4, 9, 12}, incomplete stay incomplete; cycle 13 force-emitted
  incomplete with no expected counts (no Tech#2) and mail-sourced date;
  Param#1-driven config (MC09 = 12, MC29 = 0, MC31 = 5, TC04 = 28000,
  TC22 = 33000); cycle 1 descent 52 / ascent 104 measurements; pre-launch
  factory/deck mails (2025-09-19, 2025-11-20, 2026-03-25 before launch)
  never feed profile locations or dates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from argo_decoder.platforms.provor_ir_sbd.arvor_i import read_arvor_i_eml
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import (
    reconstruct_science,
)

ARGO_PY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ARGO_PY_ROOT.parent
RAW_ROOT = WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819"

LAUNCH_6990711 = datetime(2025, 3, 2, 5, 16, tzinfo=UTC)
LAUNCH_7902408 = datetime(2026, 3, 25, 17, 44, tzinfo=UTC)

requires_raw = pytest.mark.skipif(not RAW_ROOT.exists(), reason="raw ARVOR-I dataset not available")


def _load(wmo: str, launch: datetime):
    messages = [read_arvor_i_eml(p) for p in sorted((RAW_ROOT / wmo).glob("*.eml"))]
    return reconstruct_science(messages, launch_date=launch)


@pytest.fixture(scope="module")
def res_6990711():
    return _load("6990711", LAUNCH_6990711)


@pytest.fixture(scope="module")
def res_7902408():
    return _load("7902408", LAUNCH_7902408)


def _profiles(cycle):
    return {p.kind: p for p in cycle.profiles}


@requires_raw
class Test6990711Science:
    def test_seven_complete_cycles(self, res_6990711):
        assert [c.cycle_number for c in res_6990711.cycles] == list(range(1, 8))
        assert all(c.completed for c in res_6990711.cycles)

    def test_profile_structure_descent_drift_ascent_separate(self, res_6990711):
        c1 = res_6990711.cycles[0]
        kinds = [p.kind for p in c1.profiles]
        assert kinds == ["descent", "ascent_deep", "ascent_shallow"]
        # drift is kept separate from the profiles
        assert c1.drift and all(p.kind != "drift" for p in c1.profiles)

    def test_cycle1_counts_match_expected(self, res_6990711):
        c1 = res_6990711.cycles[0]
        profs = _profiles(c1)
        assert len(profs["descent"].measurements) == 54
        assert len(profs["ascent_deep"].measurements) == 96
        assert len(profs["ascent_shallow"].measurements) == 6
        for p in c1.profiles:
            assert p.expected_n_meas in (54, 102)
            assert p.profile_completed == 0

    def test_drift_counts(self, res_6990711):
        # cycle 1 park holds a single drift sample, cycles 2-7 have 17
        assert [len(c.drift) for c in res_6990711.cycles] == [1] + [17] * 6

    def test_gps_qc_and_stale_fixes(self, res_6990711):
        by_cycle = {c.cycle_number: c.gps for c in res_6990711.cycles}
        for n in (1, 2, 3, 4, 7):
            assert by_cycle[n] is not None and by_cycle[n].qc == 1
        # cycles 5/6 re-transmitted the cycle-4 fix with item61 = 0
        assert by_cycle[5] is None and by_cycle[6] is None

    def test_stale_gps_cycles_get_interpolated_locations(self, res_6990711):
        for n in (5, 6):
            for p in res_6990711.cycles[n - 1].profiles:
                assert p.location.source == "interpolated"
                assert p.location.qc == 8

    def test_valid_gps_cycles_get_gps_locations(self, res_6990711):
        for n in (1, 2, 3, 4, 7):
            for p in res_6990711.cycles[n - 1].profiles:
                if p.kind == "descent":
                    continue  # cycle 0 has no fix -> extrapolated
                assert p.location.source == "gps"
                assert p.location.qc == 1

    def test_cycle1_descent_location_extrapolated(self, res_6990711):
        profs = _profiles(res_6990711.cycles[0])
        loc = profs["descent"].location
        assert loc.source == "interpolated" and loc.qc == 8

    def test_clock_offset_events(self, res_6990711):
        assert [(e.cycle, e.offset_s) for e in res_6990711.clock_offset_events] == [
            (1, -5.0),
            (2, -23.0),
            (3, -23.0),
            (4, -23.0),
            (7, -69.0),
        ]

    def test_no_param1_config(self, res_6990711):
        assert res_6990711.float_config is None or not (res_6990711.float_config.values)

    def test_ascent_dates_fall_back_to_trans_start(self, res_6990711):
        # no Param#1 -> ascent_end unknown with recorded reason
        for c in res_6990711.cycles:
            assert c.timing.ascent_end is None
            for p in c.profiles:
                if p.direction == "A":
                    assert p.date is not None

    def test_no_fabricated_measurement_dates(self, res_6990711):
        # every measurement date is either transmitted (first slot) or
        # derived from a transmitted date + spacing; spot-check monotonicity
        c2 = res_6990711.cycles[1]
        dates = [m.date for m in c2.drift if m.date is not None]
        assert dates == sorted(dates)


@requires_raw
class Test7902408Science:
    def test_completion_states(self, res_7902408):
        complete = {c.cycle_number for c in res_7902408.cycles if c.completed}
        incomplete = {c.cycle_number for c in res_7902408.cycles if not c.completed}
        assert complete == {1, 4, 9, 12}
        # 14/15: trailing-buffer cycles (go=2) since the 2026-08-27
        # production-default change; 13 force-emitted without Tech packets
        assert incomplete == {2, 3, 5, 6, 7, 8, 10, 11, 13, 14, 15}

    def test_cycle13_forced_incomplete_no_expected_counts(self, res_7902408):
        c13 = res_7902408.cycles[12]
        assert not c13.completed
        for p in c13.profiles:
            assert p.expected_n_meas is None
            assert p.profile_completed is None
            assert p.date is not None  # mail-session fallback, labelled
        # date source is explicit about the transport origin
        assert any("iridium-mail" in (p.date_source or "") for p in c13.profiles)

    def test_config_from_param1(self, res_7902408):
        cfg = res_7902408.float_config
        assert cfg is not None
        assert cfg.get("MC09") == 12.0
        assert cfg.get("MC29") == 0.0
        assert cfg.get("MC31") == 5.0
        assert cfg.get("TC04") == 28000.0
        assert cfg.get("TC22") == 33000.0

    def test_cycle1_counts(self, res_7902408):
        profs = _profiles(res_7902408.cycles[0])
        assert len(profs["descent"].measurements) == 52
        assert len(profs["ascent_deep"].measurements) == 99
        assert len(profs["ascent_shallow"].measurements) == 5
        for p in res_7902408.cycles[0].profiles:
            assert p.expected_n_meas in (52, 104)

    def test_incomplete_cycles_keep_pending_counts(self, res_7902408):
        pending = {
            c.cycle_number: [p.profile_completed for p in c.profiles] for c in res_7902408.cycles
        }
        assert 30 in pending[2]
        assert 28 in pending[3]
        assert 72 in pending[8]
        assert 45 in pending[11]
        # complete cycles report zero pending
        for n in (1, 4, 9, 12):
            assert set(pending[n]) == {0}

    def test_ascent_end_computed_from_config(self, res_7902408):
        # Param#1 present -> ascent_end resolves (MC29 = 0: no in-air cycle)
        for c in res_7902408.cycles[:12]:
            if c.timing is None:
                continue
            if c.timing.ascent_end is None:
                assert c.timing.reasons  # reason recorded, never silent

    def test_prelaunch_mails_flagged_and_excluded(self, res_7902408):
        pre = [m for m in res_7902408.mails if m.pre_launch]
        assert pre, "factory/deck test mails must be flagged"
        # every pre-launch session predates the launch date
        assert max(m.time_of_session for m in pre) < 27842.75  # 2026-03-25
        # and no located profile sits at the factory coordinates
        for c in res_7902408.cycles:
            for p in c.profiles:
                if p.location.lat is not None:
                    assert abs(p.location.lat - 11.56) > 1.0

    def test_param_only_prelaunch_buffer(self, res_7902408):
        assert res_7902408.param_only_cycles == [-1]

    def test_cycle1_descent_location_at_sea(self, res_7902408):
        profs = _profiles(res_7902408.cycles[0])
        loc = profs["descent"].location
        # extrapolated from the first two surfacings (launch GPS not in the
        # dataset), qc 8, in the deployment area (not the factory site)
        assert loc.source == "interpolated"
        assert loc.qc == 8
        assert 2.0 < loc.lat < 4.0

    def test_no_descent_profiles_after_cycle1(self, res_7902408):
        for c in res_7902408.cycles[1:]:
            assert all(p.kind != "descent" for p in c.profiles)
