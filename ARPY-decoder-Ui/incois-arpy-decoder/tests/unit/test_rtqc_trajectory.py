"""Trajectory RTQC (Argo QC Manual v3.9 §4 / Coriolis traj test set).

The trajectory set is tests 2/3/4/20 only -- the four that Coriolis runs
"to fill JULD_QC, JULD_ADJUSTED_QC and POSITION_QC"
(``nc_add_rtqc_flags_prof_and_traj.m:775-786``).  These tests pin the flag
algebra, the truthful skipped/executed provenance, and the fact that a
skipped test never masquerades as a pass.
"""

from __future__ import annotations

from datetime import UTC, datetime

from argo_decoder.platforms.provor_ir_sbd.arvor_i_rtraj import MC, RtrajRow
from argo_decoder.rtqc.trajectory import (
    TRAJECTORY_RTQC_TESTS,
    apply_trajectory_rtqc,
)

NOW = datetime(2026, 9, 7, tzinfo=UTC)
GOOD_JULD = 27773.5625  # 2026-01-30, inside the Test 2 window
GOOD_LAT, GOOD_LON = 11.0, 66.87


def _row(**kw) -> RtrajRow:
    base = {"cycle_number": 1, "measurement_code": MC.SURFACE}
    base.update(kw)
    return RtrajRow(**base)


class TestTestSet:
    def test_set_is_the_coriolis_trajectory_four(self):
        assert TRAJECTORY_RTQC_TESTS == (2, 3, 4, 20)


class TestFlagAlgebra:
    def test_defined_values_are_raised_to_good(self):
        rows = [_row(juld=GOOD_JULD, latitude=GOOD_LAT, longitude=GOOD_LON)]
        out = apply_trajectory_rtqc(rows, now=NOW)
        assert rows[0].juld_qc == "1"
        assert rows[0].pos_qc == "1"
        assert {2, 3} <= out.executed
        assert not out.failed

    def test_fill_values_keep_the_blank_default(self):
        """QC is never asserted for a value that does not exist."""
        rows = [_row(juld=None, latitude=None, longitude=None)]
        apply_trajectory_rtqc(rows, now=NOW)
        assert rows[0].juld_qc == ""
        assert rows[0].pos_qc == ""

    def test_impossible_date_is_flagged_bad(self):
        rows = [_row(juld=100.0)]  # 1950 -- before the 1997 floor
        out = apply_trajectory_rtqc(rows, now=NOW)
        assert rows[0].juld_qc == "4"
        assert 2 in out.failed

    def test_future_date_is_flagged_bad(self):
        rows = [_row(juld=99000.0)]
        out = apply_trajectory_rtqc(rows, now=NOW)
        assert rows[0].juld_qc == "4"
        assert 2 in out.failed

    def test_impossible_location_is_flagged_bad(self):
        rows = [_row(latitude=91.0, longitude=0.0)]
        out = apply_trajectory_rtqc(rows, now=NOW)
        assert rows[0].pos_qc == "4"
        assert 3 in out.failed

    def test_set_qc_only_worsens(self):
        """A value condemned by one test is not rehabilitated by another."""
        rows = [_row(juld=GOOD_JULD, latitude=91.0, longitude=0.0)]
        apply_trajectory_rtqc(rows, now=NOW)
        assert rows[0].pos_qc == "4"  # test 3 wins over test 3's own '1'

    def test_juld_adjusted_qc_is_filled(self):
        rows = [_row(juld=GOOD_JULD, juld_adj=GOOD_JULD)]
        apply_trajectory_rtqc(rows, now=NOW)
        assert rows[0].juld_adj_qc == "1"


class TestSkippedIsNotPassed:
    def test_test004_skipped_without_bathymetry(self):
        rows = [_row(juld=GOOD_JULD, latitude=GOOD_LAT, longitude=GOOD_LON)]
        out = apply_trajectory_rtqc(rows, bathymetry=None, now=NOW)
        assert 4 not in out.executed
        assert 4 not in out.passed
        assert "bathymetry" in out.skipped[4]

    def test_test004_runs_with_bathymetry(self):
        class _Grid:
            def elevation_at(self, lat, lon):
                return 250.0  # dry land

        rows = [_row(juld=GOOD_JULD, latitude=GOOD_LAT, longitude=GOOD_LON)]
        out = apply_trajectory_rtqc(rows, bathymetry=_Grid(), now=NOW)
        assert 4 in out.executed and 4 in out.failed
        assert rows[0].pos_qc == "4"

    def test_test020_skipped_for_iridium_accuracy(self):
        """Test 20's error radii are defined only for ARGOS classes."""
        rows = [_row(latitude=GOOD_LAT, longitude=GOOD_LON, pos_accuracy="I")]
        out = apply_trajectory_rtqc(rows, now=NOW)
        assert 20 not in out.executed
        assert "ARGOS" in out.skipped[20]

    def test_no_rows_skips_everything(self):
        out = apply_trajectory_rtqc([], now=NOW)
        assert not out.executed
        assert set(out.skipped) == {2, 3, 4, 20}


class TestLaunchRow:
    def test_launch_row_qc_comes_from_rtqc_not_a_constant(self):
        """Cookbook §2.1.1: QC starts '0', becomes '1' once checked."""
        launch = RtrajRow(
            cycle_number=-1,
            measurement_code=MC.LAUNCH,
            juld=GOOD_JULD,
            juld_status="4",
            juld_qc="0",
            latitude=GOOD_LAT,
            longitude=GOOD_LON,
            pos_accuracy="",
            pos_qc="0",
        )
        apply_trajectory_rtqc([launch], now=NOW)
        assert launch.juld_qc == "1"
        assert launch.pos_qc == "1"
        assert launch.juld_status == "4"  # untouched by RTQC
        assert launch.pos_accuracy == ""  # stays fill, never 'G'


class TestGenericity:
    def test_no_wmo_or_cycle_dependence(self):
        """Identical content must yield identical flags on any float."""
        a = [_row(cycle_number=1, juld=GOOD_JULD, latitude=GOOD_LAT, longitude=GOOD_LON)]
        b = [_row(cycle_number=987, juld=GOOD_JULD, latitude=GOOD_LAT, longitude=GOOD_LON)]
        apply_trajectory_rtqc(a, now=NOW)
        apply_trajectory_rtqc(b, now=NOW)
        assert (a[0].juld_qc, a[0].pos_qc) == (b[0].juld_qc, b[0].pos_qc)


class TestClockOffsetIdentity:
    """Argo User's Manual 3.44.0 §2.3.5 (CLOCK_OFFSET).

        "Real time corrections correspond to a data mode of "A".  For
        "A" mode files, JULD_ADJUSTED = JULD - CLOCK_OFFSET"

    RTC-derived events must satisfy the identity; satellite-derived
    events (launch metadata, mail session times, GPS/Iridium fixes) are
    already UTC and must NOT be shifted.
    """

    RTC_CODES = (100, 200, 250, 300, 400, 500, 600, 700, 800)
    SATELLITE_CODES = (0, 702, 703, 704)

    def test_rtc_rows_apply_the_offset(self):
        from argo_decoder.platforms.provor_ir_sbd.arvor_i_rtraj import _row_float_time_ter

        offset = -38.0 / 86400.0
        row, _ = _row_float_time_ter(1, 100, GOOD_JULD, "2", offset)
        assert row.juld_adj == GOOD_JULD - offset
        assert row.juld_adj_status == "3"

    def test_satellite_rows_do_not_apply_the_offset(self):
        from argo_decoder.platforms.provor_ir_sbd.arvor_i_rtraj import _row_surface

        row = _row_surface(1, 703, GOOD_JULD, GOOD_LON, GOOD_LAT, "I", "", "0", True)
        assert row.juld_adj == GOOD_JULD
        assert row.juld_adj_status == "4"


class TestNCycleFillPairing:
    """N_CYCLE JULD_<EVENT> must be fill when its MC row is unpublished.

    The GDAC FileChecker pairs the N_CYCLE summary with the
    N_MEASUREMENT row carrying the matching measurement code and warns
    "<VAR> (MC nnn): Not FillValue where there is no associated JULD"
    otherwise. The publication projection narrows the file to the GDAC
    event set, so the diagnostic families (MC 150 FST, MC 450 DPST) are
    internal-only and their summaries must not be advertised.
    """

    UNPUBLISHED = ("JULD_FIRST_STABILIZATION", "JULD_DEEP_PARK_START")

    def _built(self, wmo: int):
        import sys

        sys.path.insert(0, "scripts")
        from validate_arvor_i_rtraj import _launch_position, science

        from argo_decoder.nc.rtraj_arvor import build_arvor_rtraj_nc_dataset
        from argo_decoder.platforms.provor_ir_sbd.arvor_i_rtraj import (
            build_arvor_rtraj_dataset,
        )

        ds = build_arvor_rtraj_dataset(science(wmo), wmo=wmo, launch_position=_launch_position(wmo))
        return ds, build_arvor_rtraj_nc_dataset(ds)

    def test_unpublished_families_are_fill_in_ncycle(self):
        import numpy as np

        _internal, nc = self._built(7902408)
        published = {int(c) for c in np.asarray(nc["MEASUREMENT_CODE"].values)}
        assert 150 not in published and 450 not in published
        for var in self.UNPUBLISHED:
            values = np.asarray(nc[var].values)
            assert (values >= 99998.0).all(), f"{var} advertises an unpublished event"

    def test_decoded_values_survive_internally(self):
        """The projection must narrow the file, not destroy the decode."""
        internal, _ = self._built(7902408)
        assert any(r.measurement_code == 450 and r.juld is not None for r in internal.rows), (
            "internal DPST rows were lost"
        )

    def test_published_families_keep_their_ncycle_dates(self):
        import numpy as np

        _, nc = self._built(7902408)
        juld = np.asarray(nc["JULD_TRANSMISSION_START"].values)
        assert (juld < 99998.0).any(), "published MC 700 summary was wrongly blanked"
