"""Unit tests: ARVOR-I ``_Rtraj.nc`` product model (Phase 4B).

Emitter semantics pinned against ``process_trajectory_data_222_223_225_
231_232.m`` / ``finalize_trajectory_data_ir_sbd.m`` /
``set_n_cycle_vs_n_meas_consistency.m`` (vendored 076a sources; see the
Phase 4B mapping report).  Synthetic CycleTimeData / GPS / mail inputs,
MATLAB-equivalent day arithmetic.
"""

from __future__ import annotations

import pytest

from argo_decoder.platforms.provor_ir_sbd.arvor_i_rtraj import (
    DDET,
    DET,
    EXPECTED_MC_DEEP,
    MC,
    MC_ORDER,
    MC_RANK,
    NCYCLE_FIELD_BY_MC,
    RtrajCycleRecord,
    RtrajRow,
    _bin_row,
    _consistency,
    _finalize,
    _row_float_time_missing,
    _row_float_time_ter,
    _row_surface,
    build_arvor_rtraj_dataset,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import (
    ArvorMeasurement,
    ArvorScienceResult,
    CycleTimeData,
)


def _timing(cycle: int = 1, **kw) -> CycleTimeData:
    t = CycleTimeData(
        cycle_num=cycle,
        cycle_start=27454.25,
        descent_to_park_start=27454.5,
        first_stab=27454.6,
        first_stab_pres=121.0,
        descent_to_park_end=27455.0,
        descent_to_prof_start=27456.0,
        descent_to_prof_end=27457.0,
        ascent_start=27457.5,
        ascent_end=27458.0,
        trans_start=27458.1,
    )
    for k, v in kw.items():
        setattr(t, k, v)
    return t


class TestRowFactories:
    def test_float_time_ter_dated_no_offset(self):
        row, ncycle = _row_float_time_ter(1, MC.DST, 27454.5, "2", None)
        assert row.juld == 27454.5
        assert row.juld_status == "2"
        assert row.juld_adj is None
        assert ncycle == 27454.5

    def test_float_time_ter_dated_with_offset(self):
        # MATLAB: adj = juld - round(s/60)/1440 (whole minutes), status '3'
        row, ncycle = _row_float_time_ter(1, MC.DST, 27454.5, "2", round(-5.0 / 60) / 1440)
        assert row.juld_adj == pytest.approx(27454.5 + 1.0 / 1440)
        assert row.juld_adj_status == "3"
        assert ncycle == row.juld_adj

    def test_float_time_ter_undated_is_code_only(self):
        row, ncycle = _row_float_time_ter(1, MC.FST, None, "2", None)
        assert row.juld is None and row.juld_status == ""
        assert ncycle is None

    def test_surface_row_with_position(self):
        row = _row_surface(2, MC.SURFACE, 27456.25, 70.5, -64.5, "G", "", "1", True)
        assert row.juld_status == "4"
        assert (row.longitude, row.latitude) == (70.5, -64.5)
        assert row.pos_accuracy == "G" and row.pos_qc == "1"
        assert row.juld_adj == 27456.25 and row.juld_adj_status == "4"

    def test_surface_row_without_position(self):
        row = _row_surface(2, MC.FMT, 27456.25, None, None, "", "", "", False)
        assert row.latitude is None and row.pos_qc == ""
        assert row.juld_adj is None


class TestRowQcSemantics:
    """QC strings per init_default_values.m / the 076a row creators.

    ``g_decArgo_qcStrNoQc = '0'`` is set by every creator on DATED rows
    (``juld_qc`` and ``juld_adj_qc`` when the adjusted twin exists);
    ``create_one_meas_float_time`` with time ``-1`` sets the missing-value
    QC ``'9'`` on both; untouched fields keep the MATLAB ``''`` (fill).
    """

    def test_float_time_ter_dated_qc_is_no_qc_zero(self):
        row, _ = _row_float_time_ter(1, MC.DST, 27454.5, "2", None)
        assert row.juld_qc == "0"
        assert row.juld_adj_qc == ""

    def test_float_time_ter_dated_with_offset_adj_qc_zero(self):
        row, _ = _row_float_time_ter(1, MC.DST, 27454.5, "2", 0.0)
        assert row.juld_qc == "0" and row.juld_adj_qc == "0"

    def test_float_time_ter_undated_qc_stays_fill(self):
        row, _ = _row_float_time_ter(1, MC.FST, None, "2", None)
        assert row.juld_qc == "" and row.juld_adj_qc == ""

    def test_surface_row_qc_zero(self):
        row = _row_surface(2, MC.SURFACE, 27456.25, 70.5, -64.5, "G", "", "1", True)
        assert row.juld_qc == "0" and row.juld_adj_qc == "0"

    def test_surface_row_no_clock_no_adj_qc(self):
        row = _row_surface(2, MC.FMT, 27456.25, None, None, "", "", "", False)
        assert row.juld_qc == "0" and row.juld_adj_qc == ""

    def test_missing_time_row_qc_is_nine(self):
        row = _row_float_time_missing(3, MC.TET, "9", True)
        assert row.juld is None and row.juld_adj is None
        assert row.juld_status == "9" and row.juld_qc == "9"
        assert row.juld_adj_status == "9" and row.juld_adj_qc == "9"

    def test_missing_time_row_without_drift_adj_stays_fill(self):
        row = _row_float_time_missing(3, MC.TET, "9", False)
        assert row.juld_qc == "9"
        assert row.juld_adj_status == "" and row.juld_adj_qc == ""


class TestBinRows:
    def _meas(self, trans: bool, date: float | None) -> ArvorMeasurement:
        return ArvorMeasurement(pres=1000.0, temp=2.0, psal=34.9, slot=0, date=date, trans=trans)

    def test_drift_status_rule(self):
        # drift/near-surface bins: status '1' when transmitted, else '2'
        dated = _bin_row(1, MC.DRIFT_AT_PARK, self._meas(True, 27455.0), None, True)
        spaced = _bin_row(1, MC.DRIFT_AT_PARK, self._meas(False, 27455.5), None, True)
        assert dated.juld_status == "1" and spaced.juld_status == "2"

    def test_profile_bins_always_status_2(self):
        row = _bin_row(1, MC.ASC_PROF, self._meas(True, 27457.6), None, False)
        assert row.juld_status == "2"

    def test_undated_bin_keeps_params(self):
        row = _bin_row(1, MC.DRIFT_AT_PARK, self._meas(False, None), None, True)
        assert row.juld is None
        assert (row.pres, row.temp, row.psal) == (1000.0, 2.0, 34.9)


class TestFinalize:
    def test_tet_from_next_cycle_start_prefers_adj(self):
        rows = {
            1: [RtrajRow(1, MC.TET, juld_status="9")],
            2: [
                RtrajRow(
                    2,
                    MC.CYCLE_START,
                    juld=27466.0,
                    juld_status="2",
                    juld_adj=27466.001,
                    juld_adj_status="3",
                )
            ],
        }
        recs = {
            1: RtrajCycleRecord(1, output_cycle_number=1, clock_offset=-5.0 / 86400.0),
            2: RtrajCycleRecord(2, output_cycle_number=2),
        }
        _finalize(rows, recs, {}, [])
        tet = rows[1][0]
        # create_one_meas_float_time: juld = transEndDate + prev offset(days),
        # juldAdj = transEndDate
        assert tet.juld == pytest.approx(27466.001 - 5.0 / 86400.0)
        assert tet.juld_adj == 27466.001
        assert tet.juld_adj_status == "3"
        # dated create_one_meas_float_time branch: QC '0' on both twins
        assert tet.juld_qc == "0" and tet.juld_adj_qc == "0"
        assert recs[1].trans_end == 27466.001
        assert recs[1].trans_end_status == "2"

    def test_expected_mc_fill_only_for_missing_codes(self):
        rows = {
            1: [
                RtrajRow(1, code)
                for code in (
                    MC.DST,
                    MC.FST,
                    MC.PST,
                    MC.PET,
                    MC.DPST,
                    MC.AST,
                    MC.AET,
                    MC.TST,
                    MC.TET,
                )
            ],
        }
        rec = RtrajCycleRecord(1, output_cycle_number=1)
        recs = {1: rec}
        _finalize(rows, recs, {}, [])
        codes = [r.measurement_code for r in rows[1]]
        assert sorted(codes) == sorted(EXPECTED_MC_DEEP)

        # now remove one skeleton row -> a status-9 fill row is added and
        # the N_CYCLE status follows
        rows[1] = [r for r in rows[1] if r.measurement_code != MC.AST]
        rec.ascent_start, rec.ascent_start_status = 27457.5, "2"
        _finalize(rows, recs, {}, [])
        fill = [r for r in rows[1] if r.measurement_code == MC.AST]
        assert len(fill) == 1 and fill[0].juld is None and fill[0].juld_status == "9"
        # missing-date branch of create_one_meas_float_time (drift arg 0 is
        # non-empty): QC '9' on both twins, adjusted status carries '9'
        assert fill[0].juld_qc == "9"
        assert fill[0].juld_adj is None and fill[0].juld_adj_status == "9"
        assert fill[0].juld_adj_qc == "9"
        assert rec.ascent_start is None and rec.ascent_start_status == "9"

    def test_mail_only_cycle_gets_fmt_lmt_record(self):
        rows = {1: [RtrajRow(1, MC.TET)]}
        recs = {1: RtrajCycleRecord(1, output_cycle_number=1)}
        _finalize(rows, recs, {2: (27500.0, 27500.1)}, [])
        assert 2 in rows and recs[2].grounded == "U"
        codes = [r.measurement_code for r in rows[2]]
        assert codes == [MC.FMT, MC.LMT]
        assert recs[2].first_message == 27500.0 and recs[2].last_message == 27500.1


class TestConsistency:
    def test_ncycle_rederived_preferring_adj(self):
        rows = {
            1: [
                RtrajRow(
                    1,
                    MC.DST,
                    juld=27454.5,
                    juld_status="2",
                    juld_adj=27454.501,
                    juld_adj_status="3",
                )
            ],
        }
        rec = RtrajCycleRecord(1, output_cycle_number=1)
        rec.descent_start, rec.descent_start_status = 27454.5, "2"
        _consistency(rows, {1: rec})
        assert rec.descent_start == 27454.501
        assert rec.descent_start_status == "3"

    def test_first_last_location_from_positioned_surface_rows(self):
        rows = {
            1: [
                RtrajRow(
                    1, MC.SURFACE, juld=27458.2, juld_status="4", longitude=70.1, latitude=-64.5
                ),
                RtrajRow(
                    1, MC.SURFACE, juld=27458.1, juld_status="4", longitude=70.0, latitude=-64.4
                ),
                RtrajRow(1, MC.SURFACE, juld=27458.15, juld_status="4"),
            ],
        }
        rec = RtrajCycleRecord(1, output_cycle_number=1)
        _consistency(rows, {1: rec})
        assert rec.first_location == 27458.1 and rec.last_location == 27458.2

    def test_grounded_consistency(self):
        rows = {1: [RtrajRow(1, MC.GROUNDED, juld=27455.0, pres=1500.0)]}
        rec = RtrajCycleRecord(1, output_cycle_number=1)
        _consistency(rows, {1: rec})
        assert rec.grounded == "Y"

    def test_fmt_min_lmt_max_across_duplicates(self):
        rows = {
            1: [
                RtrajRow(1, MC.FMT, juld=27458.30, juld_status="4"),
                RtrajRow(1, MC.FMT, juld=27458.25, juld_status="4"),
                RtrajRow(1, MC.LMT, juld=27458.40, juld_status="4"),
                RtrajRow(1, MC.LMT, juld=27458.45, juld_status="4"),
            ],
        }
        rec = RtrajCycleRecord(1, output_cycle_number=1)
        _consistency(rows, {1: rec})
        assert rec.first_message == 27458.25 and rec.last_message == 27458.45


class TestTables:
    def test_mc_order_is_permutation_rank(self):
        assert len(MC_ORDER) == len(set(MC_ORDER))
        assert sorted(MC_RANK) == sorted(set(MC_RANK))

    def test_ncycle_map_matches_set_status_of_n_cycle_juld(self):
        # every skeleton code maps to the struct field set_status writes
        for _code, (field, _) in NCYCLE_FIELD_BY_MC.items():
            assert isinstance(field, str) and hasattr(RtrajCycleRecord(0), field)

    def test_det_ddet_are_consistency_keys_not_emitted(self):
        assert DET == 200 and DDET == 400
        assert DET not in MC_ORDER and DDET not in MC_ORDER


class TestEmptyDataset:
    def test_no_tech1_raises(self):
        with pytest.raises(ValueError, match="decoder id"):
            build_arvor_rtraj_dataset(ArvorScienceResult(), wmo=6990711)

    def test_launch_row_optional(self):
        result = ArvorScienceResult()
        dataset = build_arvor_rtraj_dataset(result, wmo=6990711, dec_id=222)
        assert dataset.rows == []
        assert any("DATA-COVERAGE" in n for n in dataset.notes)

        with_launch = build_arvor_rtraj_dataset(
            ArvorScienceResult(),
            wmo=6990711,
            dec_id=222,
            launch_position=(27457.2194, 70.01, -64.49),
        )
        (row,) = with_launch.rows
        assert row.measurement_code == MC.LAUNCH
        assert row.cycle_number == -1
        assert row.juld_status == "4"
        assert (row.longitude, row.latitude) == (70.01, -64.49)
        # Trajectory Cookbook (DOI 10.13155/29824) §2.1.1: the launch row
        # carries POSITION_ACCURACY = _FillValue -- the deployment
        # position is META-file metadata, not a positioning-system fix,
        # so it must not claim GPS ('G') accuracy. POSITION_QC starts at
        # the un-tested '0'; trajectory RTQC raises it to '1'.
        assert row.pos_accuracy == "" and row.pos_qc == "0"
