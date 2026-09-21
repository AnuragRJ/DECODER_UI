"""Phase-4 CTS4 float-level products — unit tests (synthetic, fast).

Covers: mission-clock derivation + guards, adjudicated Rtraj row rules,
tech-row builder contract, FloatTime byte-order regression, and the Rtraj
writer structure. Real-corpus validation lives in
``test_provor_cts4_phase4_products_integration.py`` and
``scripts/validate_cts4_phase4_gdac.py``.
"""

from __future__ import annotations

import numpy as np
import pytest

from argo_decoder.platforms.provor_cts4_ir_sbd.mission_clock import (
    AnchorInconsistentError,
    MissionClock,
    derive_mission_clock,
    floattime_juld,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.packets import dispatch_row
from argo_decoder.platforms.provor_cts4_ir_sbd.rtraj_build import (
    JULD_FILL,
    build_cycle_rows,
    build_cycle_summaries,
    build_rows,
    build_transmission_rows,
    launch_row,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.tech import decode_253
from argo_decoder.platforms.provor_cts4_ir_sbd.tech_build import (
    TECH_ROW_NAMES,
    build_cycle_tech_rows,
)


def _row_253(
    *,
    date=(21, 2, 14, 3, 57, 9),   # wire DD MM YY HH MM SS
    cycle=98,
    phase=12,
    cycle_start=(414, 220),
    buoy=(414, 237),
    stab=(414, 287),
    park_desc=(414, 267),
    park_end=(414, 796),
    prof_desc=(418, 754),
    prof_end=(418, 1192),
    ascent=(418, 1312),
    ascent_end=(419, 222),
    gps=(13, 53, 5283, 0, 86, 5, 7315, 0, 1),
) -> bytes:
    row = bytearray(140)
    row[0] = 0xFD
    row[1:7] = bytes(date)

    def u16(off, val):
        row[off:off + 2] = int(val).to_bytes(2, "big")

    u16(7, 1206)     # serial
    u16(9, 99)       # total profiles
    u16(11, cycle)
    row[13] = 0      # profile
    u16(14, cycle_start[0]); u16(16, cycle_start[1])
    row[18] = phase
    u16(19, 0); u16(21, 1)
    row[23] = 148    # vacuum
    row[24] = 55     # battery
    row[25] = 0      # rtc
    u16(26, buoy[0]); u16(28, buoy[1])
    row[30] = 8      # ev timing
    row[31] = 15     # valve surface
    u16(32, park_desc[0]); u16(34, park_desc[1])
    u16(36, stab[0]); u16(38, stab[1])
    u16(40, park_end[0]); u16(42, park_end[1])
    row[44] = 12; row[45] = 0
    row[46] = 7      # stab pres bar
    row[47] = 98     # max pres desc park
    row[48] = 1; row[49] = 0; row[50] = 0; row[51] = 0
    row[50] = 98; row[51] = 100     # drift park min/max
    row[52] = 0; row[53] = 0
    u16(54, prof_desc[0]); u16(56, prof_desc[1])
    u16(58, prof_end[0]); u16(60, prof_end[1])
    row[62] = 7; row[63] = 0; row[64] = 198  # max pres desc prof
    row[65] = 1; row[66] = 0; row[67] = 0; row[68] = 0
    row[69] = 198; row[70] = 198
    u16(71, ascent[0]); u16(73, ascent[1])
    u16(75, ascent_end[0]); u16(77, ascent_end[1])
    row[79] = 15     # pump ascent
    row[80] = 0; row[81] = 0; u16(82, 0); u16(84, 0)   # grounding
    row[86] = 0; u16(87, 0); row[89] = 0; row[90] = 0; row[91] = 0
    row[92] = 0; row[93] = 0        # remote rx/rej
    row[94] = gps[0]; row[95] = gps[1]
    u16(96, gps[2]); row[98] = gps[3]
    row[99] = gps[4]; row[100] = gps[5]
    u16(101, gps[6]); row[103] = gps[7]
    row[104] = gps[8]
    return bytes(row)


def _vt(**kw):
    return decode_253(dispatch_row(_row_253(**kw), index=0))


CLOCK = MissionClock(anchor_juld=23008.0, n_estimates=3, spread_days=0.0005,
                     rounded_to_midnight=True)


# --------------------------------------------------------------------------
# FloatTime byte-order regression (GDAC-verified 20140221035709)
# --------------------------------------------------------------------------

def test_floattime_wire_order_is_dd_mm_yy() -> None:
    vt = _vt()
    assert (vt.time.yy, vt.time.mm, vt.time.dd) == (14, 2, 21)
    assert (vt.time.hh, vt.time.mi, vt.time.ss) == (3, 57, 9)
    # 2014-02-21 03:57:09 UTC
    assert floattime_juld(vt.time) == pytest.approx(23427.16468750, abs=1e-8)


# --------------------------------------------------------------------------
# mission clock
# --------------------------------------------------------------------------

def test_derive_mission_clock_midnight_rounding() -> None:
    vt98 = _vt(cycle=98)
    vt99 = _vt(cycle=99, date=(26, 2, 14, 4, 11, 9), cycle_start=(419, 238))
    clock = derive_mission_clock({98: [vt98], 99: [vt99]})
    # FloatTime(98 s2)=23427.1646875 - (419 + 238/1440) = 23007.99941 -> 23008
    assert clock.anchor_juld == 23008.0
    assert clock.rounded_to_midnight is True


def test_derive_mission_clock_inconsistent_raises() -> None:
    vt98 = _vt(cycle=98)
    vt99 = _vt(cycle=99, date=(26, 2, 14, 4, 11, 9), cycle_start=(419, 238))
    vt100 = _vt(cycle=100, date=(3, 3, 14, 3, 51, 22), cycle_start=(500, 0))
    with pytest.raises(AnchorInconsistentError):
        derive_mission_clock({98: [vt98], 99: [vt99], 100: [vt100]})


def test_derive_mission_clock_needs_consecutive_cycles() -> None:
    with pytest.raises(AnchorInconsistentError):
        derive_mission_clock({98: [_vt(cycle=98)]})


def test_clock_event_conversions_adjudicated() -> None:
    vt = _vt()
    assert CLOCK.buoyancy_reduction_start(vt) == pytest.approx(
        23008.0 + 414 + 237 / 1440)
    assert CLOCK.surfacing(vt) == pytest.approx(
        CLOCK.ascent_end(vt) - 10.0 / 1440.0)


# --------------------------------------------------------------------------
# Rtraj rows
# --------------------------------------------------------------------------

def test_launch_row_is_cycle_zero_mc0_status4() -> None:
    # Cycle 0 is the launch cycle ("0 : launch cycle, 1 : first complete
    # cycle"). It must agree with CYCLE_NUMBER_INDEX[0] and the N_CYCLE launch
    # row, or OneArgo FileChecker skips all remaining trajectory checks.
    r = launch_row(23008.5, 12.0, 86.0)
    assert (r.cycle_number, r.measurement_code) == (0, 0)
    assert r.juld_status == "4" and r.juld_qc == "1"
    assert (r.latitude, r.longitude) == (12.0, 86.0)
    assert r.position_qc == "1"


def test_cycle_rows_event_set_and_status() -> None:
    vt = _vt()
    rows = build_cycle_rows(98, vt, [], CLOCK)
    by_mc = {r.measurement_code: r for r in rows
             if r.measurement_code in (89, 100, 150, 250, 300, 450, 500, 600)}
    assert set(by_mc) == {89, 100, 150, 250, 300, 450, 500, 600}
    assert all(r.juld_status == "2" and r.juld_qc == "1" for r in by_mc.values())
    undated = {r.measurement_code: r for r in rows
               if r.measurement_code in (198, 297, 298, 398, 497, 498)}
    assert all(r.juld_status == " " and r.juld == JULD_FILL
               for r in undated.values())
    assert undated[198].pres == pytest.approx(980.0)
    assert undated[498].pres == pytest.approx(1980.0)
    # closing MC589 surface pump action at ascent_end, PRES 0
    tail = [r for r in rows if r.measurement_code == 589]
    assert len(tail) == 1 and tail[0].pres == 0.0
    assert tail[0].juld == pytest.approx(CLOCK.ascent_end(vt))


def test_transmission_rows_from_floattime() -> None:
    # vt1 is the PREVIOUS cycle's session-1 (surfacing) packet still sitting in
    # this cycle's buffer: its FloatTime predates this cycle's own session-2
    # packet, so it must NOT be counted as this cycle's first message. Only
    # vt2 (phase 12, this cycle's own end-of-cycle packet) is in the window,
    # giving a single MC 703 row.
    vt1 = _vt(phase=1, date=(21, 2, 14, 3, 47, 9))
    vt2 = _vt(phase=12, date=(21, 2, 14, 3, 57, 9))
    rows = build_transmission_rows(98, [vt1, vt2])
    mcs = [r.measurement_code for r in rows]
    assert mcs == [700, 702, 703, 704, 800]
    assert rows[0].juld_status == "3"           # first message: telemetry
    assert rows[1].juld_status == "4"           # first location: satellite
    fix = rows[2]
    assert fix.latitude == pytest.approx(13.892138, abs=1e-5)
    assert rows[-1].juld == JULD_FILL and rows[-1].juld_status == "9"


def test_transmission_window_includes_next_cycle_session1() -> None:
    """A cycle's transmission spans its own phase-12 and the next cycle's phase-1.

    Verified against INCOIS 2902093 cycles 45-53: GDAC's MC 703 window for
    each cycle contains both of our packets' GPS fixes (8/8 cycles). MC 704
    (last location) is therefore the following cycle's session-1 fix.
    """
    own = _vt(phase=12, date=(21, 2, 14, 3, 57, 9))
    nxt1 = _vt(phase=1, date=(21, 2, 24, 3, 59, 9))
    nxt12 = _vt(phase=12, date=(21, 2, 24, 4, 9, 9))
    rows = build_transmission_rows(98, [own], [nxt1, nxt12])
    mcs = [r.measurement_code for r in rows]
    assert mcs == [700, 702, 703, 703, 704, 800]
    fixes = [r for r in rows if r.measurement_code == 703]
    assert len(fixes) == 2
    assert fixes[0].juld < fixes[1].juld
    # MC 704 is the later (next cycle's session-1) fix, not our own.
    last_loc = [r for r in rows if r.measurement_code == 704][0]
    assert last_loc.juld == pytest.approx(fixes[1].juld)
    # The next cycle's session-2 packet is NOT part of this window: only its
    # session-1 (phase-1) packet is. Exactly two MC 703 rows proves it.
    assert len([r for r in rows if r.measurement_code == 703]) == 2
    first_msg = [r for r in rows if r.measurement_code == 700][0]
    assert first_msg.juld == pytest.approx(floattime_juld(own.time))


def test_build_rows_sorted_and_launch_first() -> None:
    vt98 = _vt(cycle=98)
    vt99 = _vt(cycle=99, date=(26, 2, 14, 4, 11, 9), cycle_start=(419, 238))
    rows = build_rows({98: [vt98], 99: [vt99]}, {}, CLOCK,
                      23008.5, 12.0, 86.0)
    # Launch measurement belongs to cycle 0 (the launch cycle), matching the
    # N_CYCLE launch row and CYCLE_NUMBER_INDEX[0].
    assert rows[0].measurement_code == 0 and rows[0].cycle_number == 0
    keys = [(r.cycle_number, r.measurement_code, r.juld) for r in rows]
    assert keys == sorted(keys)


def test_cycle_summaries_shape() -> None:
    vt98 = _vt(cycle=98)
    sums = build_cycle_summaries({98: [vt98]}, CLOCK,
                                 park_pres_by_cycle={98: 998.7})
    assert len(sums) == 2
    # CYCLE_NUMBER_INDEX carries the cycle NUMBER of the row, not a positional
    # ordinal (Argo trajectory spec: "Cycle number that corresponds to the
    # current index"). FileChecker cross-checks CYCLE_NUMBER against it in both
    # directions and skips all remaining checks on a mismatch.
    assert sums[0].cycle_number == 0 and sums[0].cycle_number_index == 0
    assert sums[1].cycle_number == 98 and sums[1].cycle_number_index == 98
    assert sums[1].data_mode == "R"
    assert sums[1].representative_park_pressure == pytest.approx(998.7)
    assert sums[1].juld_descent_start_status == "2"


# --------------------------------------------------------------------------
# tech rows
# --------------------------------------------------------------------------

def test_tech_rows_contract_and_gdac_verified_values() -> None:
    vt = _vt()

    class _Half:
        present = True
        tx_descent, tx_drift, tx_ascent = 0, 1, 7
        acq_descent = (0, 0, 0, 0, 0)
        acq_drift = 8
        acq_ascent = (8, 38, 30, 25, 40)
        status = 1
        free = None

    rows = build_cycle_tech_rows(98, vt, {0: _Half(), 1: _Half(), 4: _Half()},
                                 CLOCK, last_ascent_ctd_pres=0.2)
    assert len(rows) == 95
    assert [r.name for r in rows] == list(TECH_ROW_NAMES)
    val = {r.name: r.value for r in rows}
    # GDAC-verified values (2902086 cycle 99 == telemetry cycle 98)
    assert val["CLOCK_FloatTime_YYYYMMDDHHMMSS"] == "20140221035709"
    assert val["NUMBER_InternalCycle_NUMBER"] == "98"
    assert val["CLOCK_StartInternalCycle_FloatDay"] == "414"
    assert val["CLOCK_StartInternalCycle_HHMM"] == "0340"
    assert val["CLOCK_StartInternalCycle_YYYYMMDDHHMMSS"] == "20140216034000"
    assert val["PRESSURE_InternalVacuumAtSurface_mbar"] == "740"
    assert val["VOLTAGE_BatteryPumpStartProfile_volts"] == "9.5"
    assert val["TIME_ValveActionsAtSurface_minutes"] == "8"
    assert val["NUMBER_ValveActionsAtSurfaceDuringDescent_COUNT"] == "15"
    assert val["CLOCK_InitialStabilizationDuringDescentToPark_HHMM"] == "0447"
    assert val["CLOCK_PumpActionsAtSurface_YYYYMMDDHHMMSS"] == "20140221034200"
    assert val["NUMBER_CTDAscentSamplesDepthZone2_COUNT"] == "38"
    # no fabrication: this row is decoded from telemetry byte 106
    # (`show_sensor`), which is 0 on this fixture -- matching the GDAC value.
    assert val["FLAG_SensorBoardStatus_NUMBER"] == "0"
    assert all(r.cycle_number == 98 for r in rows)


def test_tech_rows_missing_half_is_none_filled() -> None:
    vt = _vt()
    rows = build_cycle_tech_rows(98, vt, {}, CLOCK)
    val = {r.name: r.value for r in rows}
    assert val["NUMBER_CTDDescentIridiumMessages_COUNT"] == "none"
    assert val["FLAG_FlbbStatus_LOGICAL"] == "none"
    assert val["PRES_LastAscentPumpedRawSample_dbar"] == "none"


# --------------------------------------------------------------------------
# Rtraj writer structure (synthetic minimal)
# --------------------------------------------------------------------------

def test_rtraj_writer_structure(tmp_path) -> None:
    import netCDF4

    from argo_decoder.nc.rtraj_cts4 import write_cts4_rtraj
    from argo_decoder.writer.nc import ExternalMeta

    em = ExternalMeta(
        float_serial_no="SYN-1", wmo_inst_type="836",
        launch_date="20121229131742", launch_latitude=12.0,
        launch_longitude=86.0, project_name="TEST", pi_name="TEST PI",
        config_parameter_names=("A", "B"),
        config_mission_values=((1.0, 2.0),),
    )
    vt98 = _vt(cycle=98)
    vt99 = _vt(cycle=99, date=(26, 2, 14, 4, 11, 9), cycle_start=(419, 238))
    rows = build_rows({98: [vt98], 99: [vt99]}, {}, CLOCK,
                      23008.5, 12.0, 86.0)
    sums = build_cycle_summaries({98: [vt98], 99: [vt99]}, CLOCK)
    path = write_cts4_rtraj(tmp_path / "2909999_Rtraj.nc", rows, sums, em,
                            "2909999")
    ds = netCDF4.Dataset(str(path))
    try:
        assert len(ds.dimensions["N_MEASUREMENT"]) == len(rows)
        assert len(ds.dimensions["N_CYCLE"]) == 3
        assert len(ds.dimensions["N_PARAM"]) == 12
        # trajectory files are written to the 3.2 spec (N_CALIB_* / STRING256
        # are 3.2 additions; adjudicated against FileChecker -internal-specs)
        assert ds.getncattr("Conventions") == "Argo-3.2 CF-1.6"
        assert (ds.variables["FORMAT_VERSION"][:].tobytes().decode().strip()
                == "3.2")
        assert ds.getncattr("featureType") == "trajectory"
        dm = ds.variables["DATA_MODE"][:].tobytes().decode()
        assert set(dm.strip()) <= {"R"}
        for name in ("JULD", "JULD_STATUS", "MEASUREMENT_CODE",
                     "TRAJECTORY_PARAMETERS", "SCIENTIFIC_CALIB_EQUATION",
                     "HISTORY_SOFTWARE", "REPRESENTATIVE_PARK_PRESSURE"):
            assert name in ds.variables, name
    finally:
        ds.close()


def test_rtraj_writer_rejects_bad_wmo(tmp_path) -> None:
    from argo_decoder.nc.rtraj_cts4 import write_cts4_rtraj
    from argo_decoder.writer.nc import ExternalMeta

    em = ExternalMeta(
        float_serial_no="SYN-1", wmo_inst_type="836",
        launch_date="20121229131742", launch_latitude=12.0,
        launch_longitude=86.0, project_name="TEST", pi_name="TEST PI",
        config_parameter_names=("A",),
        config_parameter_values=(1.0,),
    )
    rows = [launch_row(23008.5, 12.0, 86.0)]
    sums = build_cycle_summaries({98: [_vt(cycle=98)]}, CLOCK)
    with pytest.raises(ValueError):
        write_cts4_rtraj(tmp_path / "x.nc", rows, sums, em, "290209")
