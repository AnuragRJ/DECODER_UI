"""CTS4 tech.nc row builder — Phase-4.

Row set and order: verbatim from GDAC ``2902086_tech.nc`` cycle rows (95 per
cycle; the same ``_tech_param_name_301`` namespace). Values come ONLY from
decoded telemetry (253 VectorTech, 250 SensorTech halves, CTD records) and
the adjudicated mission clock; every mapping was verified value-for-value on
12170 cycle 98 vs GDAC cycle 99 (see adjudication report). Two rows have no
telemetry source and are filled ``'none'`` (explicit, never fabricated):

* ``PRES_SurfaceOffsetBeforeReset_1cBarResolution_dbar`` — filled from the
  250 CTD free-zone ``offset_p`` when present (candidate mapping, verified in
  the Phase-4 validation), otherwise ``'none'``.
* ``FLAG_SensorBoardStatus_NUMBER`` — RESOLVED: the 253 byte-106 field
  "Show mode Sensor Board (0: not active; 1 active)" (NKE §7.2.4.6), decoded
  as ``show_sensor``. It is 0 on all 269 vectors of the corpus, matching INCOIS
  2902093 on 9/9 cycles. Previously filled 'none' while the derivation was
  unknown; it is not a function of the per-sensor status flags.

Accumulation contract: the pipeline rebuilds the full row list from every
attributed cycle on each run, so ``<WMO>_tech.nc`` grows with the corpus and
stays idempotent (no partial-append state).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC

from argo_decoder.platforms.provor_cts4_ir_sbd.mission_clock import (
    MissionClock,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.tech import (
    SensorHalf,
    VectorTech,
)

#: 95 row names in GDAC per-cycle order (evidence: incois_2902086_tech.nc).
TECH_ROW_NAMES: tuple[str, ...] = (
    "NUMBER_CTDDescentIridiumMessages_COUNT",
    "NUMBER_CTDParkIridiumMessages_COUNT",
    "NUMBER_CTDAscentIridiumMessages_COUNT",
    "NUMBER_CTDDescentSamplesDepthZone1_COUNT",
    "NUMBER_CTDDescentSamplesDepthZone2_COUNT",
    "NUMBER_CTDDescentSamplesDepthZone3_COUNT",
    "NUMBER_CTDDescentSamplesDepthZone4_COUNT",
    "NUMBER_CTDDescentSamplesDepthZone5_COUNT",
    "NUMBER_ParkCTDSamplesInternal_COUNT",
    "NUMBER_CTDAscentSamplesDepthZone1_COUNT",
    "NUMBER_CTDAscentSamplesDepthZone2_COUNT",
    "NUMBER_CTDAscentSamplesDepthZone3_COUNT",
    "NUMBER_CTDAscentSamplesDepthZone4_COUNT",
    "NUMBER_CTDAscentSamplesDepthZone5_COUNT",
    "FLAG_CTDStatus_LOGICAL",
    "PRES_SurfaceOffsetBeforeReset_1cBarResolution_dbar",
    "PRES_LastAscentPumpedRawSample_dbar",
    "NUMBER_OptodeDescentIridiumMessages_COUNT",
    "NUMBER_OptodeParkIridiumMessages_COUNT",
    "NUMBER_OptodeAscentIridiumMessages_COUNT",
    "NUMBER_OptodeDescentSamplesDepthZone1_COUNT",
    "NUMBER_OptodeDescentSamplesDepthZone2_COUNT",
    "NUMBER_OptodeDescentSamplesDepthZone3_COUNT",
    "NUMBER_OptodeDescentSamplesDepthZone4_COUNT",
    "NUMBER_OptodeDescentSamplesDepthZone5_COUNT",
    "NUMBER_ParkOptodeSamplesInternal_COUNT",
    "NUMBER_OptodeAscentSamplesDepthZone1_COUNT",
    "NUMBER_OptodeAscentSamplesDepthZone2_COUNT",
    "NUMBER_OptodeAscentSamplesDepthZone3_COUNT",
    "NUMBER_OptodeAscentSamplesDepthZone4_COUNT",
    "NUMBER_OptodeAscentSamplesDepthZone5_COUNT",
    "FLAG_OptodeStatus_LOGICAL",
    "NUMBER_FlbbDescentIridiumMessages_COUNT",
    "NUMBER_FlbbParkIridiumMessages_COUNT",
    "NUMBER_FlbbAscentIridiumMessages_COUNT",
    "NUMBER_FlbbDescentSamplesDepthZone1_COUNT",
    "NUMBER_FlbbDescentSamplesDepthZone2_COUNT",
    "NUMBER_FlbbDescentSamplesDepthZone3_COUNT",
    "NUMBER_FlbbDescentSamplesDepthZone4_COUNT",
    "NUMBER_FlbbDescentSamplesDepthZone5_COUNT",
    "NUMBER_ParkFlbbSamplesInternal_COUNT",
    "NUMBER_FlbbAscentSamplesDepthZone1_COUNT",
    "NUMBER_FlbbAscentSamplesDepthZone2_COUNT",
    "NUMBER_FlbbAscentSamplesDepthZone3_COUNT",
    "NUMBER_FlbbAscentSamplesDepthZone4_COUNT",
    "NUMBER_FlbbAscentSamplesDepthZone5_COUNT",
    "FLAG_FlbbStatus_LOGICAL",
    "CLOCK_FloatTime_YYYYMMDDHHMMSS",
    "NUMBER_SubCyclesDoneSinceDeployment_COUNT",
    "NUMBER_InternalCycle_NUMBER",
    "NUMBER_SubCycle_NUMBER",
    "CLOCK_StartInternalCycle_FloatDay",
    "CLOCK_StartInternalCycle_HHMM",
    "CLOCK_StartInternalCycle_YYYYMMDDHHMMSS",
    "NUMBER_VectorToSensorBoardsDialogErrors_COUNT",
    "NUMBER_SBEFPCommandTimeouts_COUNT",
    "PRESSURE_InternalVacuumAtSurface_mbar",
    "VOLTAGE_BatteryPumpStartProfile_volts",
    "FLAG_RTCStatus_LOGICAL",
    "CLOCK_InitialValveActionDescentToPark_FloatDay",
    "CLOCK_InitialValveActionDescentToPark_HHMM",
    "TIME_ValveActionsAtSurface_minutes",
    "NUMBER_ValveActionsAtSurfaceDuringDescent_COUNT",
    "CLOCK_StartDescentToPark_FloatDay",
    "CLOCK_StartDescentToPark_HHMM",
    "CLOCK_InitialStabilizationDuringDescentToPark_FloatDay",
    "CLOCK_InitialStabilizationDuringDescentToPark_HHMM",
    "CLOCK_EndDescentToPark_FloatDay",
    "CLOCK_EndDescentToPark_HHMM",
    "NUMBER_ValveActionsDuringDescentToPark_COUNT",
    "NUMBER_PumpActionsDuringDescentToPark_COUNT",
    "NUMBER_DescentToParkEntriesInParkMargin_COUNT",
    "NUMBER_RepositionsDuringPark_COUNT",
    "NUMBER_ValveActionsDuringPark_COUNT",
    "NUMBER_PumpActionsDuringPark_COUNT",
    "CLOCK_StartDescentToProfile_FloatDay",
    "CLOCK_StartDescentToProfile_HHMM",
    "CLOCK_EndDescentToProfile_FloatDay",
    "CLOCK_EndDescentToProfile_HHMM",
    "NUMBER_ValveActionsDuringDescentToProfile_COUNT",
    "NUMBER_PumpActionsDuringDescentToProfile_COUNT",
    "NUMBER_DescentToProfileEntriesInProfileMargin_COUNT",
    "NUMBER_RepositionsAtProfileDepth_COUNT",
    "NUMBER_ValveActionsDuringProfileDrift_COUNT",
    "NUMBER_PumpActionsDuringProfileDrift_COUNT",
    "CLOCK_StartAscentToSurface_FloatDay",
    "CLOCK_StartAscentToSurface_HHMM",
    "CLOCK_PumpActionsAtSurface_FloatDay",
    "CLOCK_PumpActionsAtSurface_HHMM",
    "CLOCK_PumpActionsAtSurface_YYYYMMDDHHMMSS",
    "NUMBER_PumpActionsDuringAscentToSurface_COUNT",
    "NUMBER_EmergencyAscents_COUNT",
    "FLAG_RemoteControlMessageOK_COUNT",
    "FLAG_RemoteControlMessageKO_COUNT",
    "FLAG_SensorBoardStatus_NUMBER",
)

#: 250 half sensor ids in row order (NKE §7.2.4.9: 0 CTD, 1 Optode, 4 FLBB).
_SENSOR_ORDER = (0, 1, 4)

NONE = "none"


@dataclass(frozen=True)
class TechRow:
    cycle_number: int
    name: str
    value: str


def _hhmm(minutes_of_day: int) -> str:
    return f"{minutes_of_day // 60:02d}{minutes_of_day % 60:02d}"


def _abs_stamp(clock: MissionClock, day: int, hour_minutes: int) -> str:
    """YYYYMMDDHHMMSS from the mission-anchored day/minutes fields."""
    from datetime import datetime, timedelta

    dt = datetime(1950, 1, 1, tzinfo=UTC) + timedelta(
        days=clock.juld(day, hour_minutes)
    )
    return dt.strftime("%Y%m%d%H%M%S")


def _half_rows(half: SensorHalf | None) -> list[str]:
    """16 values per sensor: 3 tx + 5 acq-descent + 1 park + 5 acq-ascent
    + status + surface-offset + last-raw (last two only for CTD; others get
    the FLAG slot only)."""
    if half is None or not half.present:
        return [NONE] * 15
    vals = [
        str(half.tx_descent),
        str(half.tx_drift),
        str(half.tx_ascent),
        *[str(x) for x in half.acq_descent],
        str(half.acq_drift),
        *[str(x) for x in half.acq_ascent],
        str(half.status),
    ]
    return vals


def build_cycle_tech_rows(
    cycle: int,
    vt: VectorTech,
    halves: dict[int, SensorHalf],
    clock: MissionClock,
    *,
    last_ascent_ctd_pres: float | None = None,
) -> list[TechRow]:
    """95 rows for one cycle, in GDAC order. ``halves`` keyed by sensor id."""
    ctd = _half_rows(halves.get(0))
    opt = _half_rows(halves.get(1))
    flb = _half_rows(halves.get(4))

    ctd_free_offset = NONE
    free = getattr(halves.get(0), "free", None) if halves.get(0) else None
    if free is not None and getattr(free, "offset_p", None) is not None:
        # ``+ 0.0`` normalises a signed zero: the 250 CTD free-zone offset is
        # transmitted as a signed value, and Python renders -0.0 as "-0", which
        # is the same pressure as "0" but a different string. Adding 0.0 is the
        # IEEE-754 identity for every other value, so this only ever changes
        # "-0" into "0" (seen on 2902093 cycle 53).
        ctd_free_offset = f"{float(free.offset_p) + 0.0:g}"

    values: list[str] = []
    values.extend(ctd[:15])                                   # 1-15
    values.append(ctd_free_offset)                            # 16
    values.append(NONE if last_ascent_ctd_pres is None
                  else f"{last_ascent_ctd_pres:.4f}")         # 17
    values.extend(opt[:15])                                   # 18-32
    values.extend(flb[:15])                                   # 33-47
    ft = vt.time
    values.append(f"{2000 + ft.yy:04d}{ft.mm:02d}{ft.dd:02d}"
                  f"{ft.hh:02d}{ft.mi:02d}{ft.ss:02d}")       # 48
    values.append(str(vt.total_profiles))                     # 49
    values.append(str(vt.cycle))                              # 50
    values.append(str(vt.profile))                            # 51
    values.append(str(vt.cycle_start_day))                    # 52
    values.append(_hhmm(vt.cycle_start_hour))                 # 53
    values.append(_abs_stamp(clock, vt.cycle_start_day,
                             vt.cycle_start_hour))            # 54
    values.append(str(vt.dialog_errors))                      # 55
    values.append(str(vt.timeout_fp))                         # 56
    values.append(str(vt.vacuum_raw * 5))                     # 57
    values.append(f"{(150 - vt.battery_raw) / 10:g}")         # 58
    # 59: the 253 field is the RTC *error* indicator, but the published Argo
    # name is FLAG_RTCStatus_LOGICAL and Coriolis documents it as
    # "real time clock status - 1= OK, 0=not OK"
    # (decArgo_soft/config/_techParamNames/_tech_param_name_301.csv, decoder id
    # 109). The polarity is therefore inverted, exactly as the sibling
    # PROVOR IR-SBD decoder already does for the same Argo field
    # (provor_ir_sbd/arvor_i_tech.py:489,537 -> `0 if raw else 1`).
    # On all 10 CTS4 groups the transmitted byte is 0 (no error) on 269/269
    # packets, which publishes as 1 (clock OK) -- consistent with the fact that
    # our decoded timestamps match the GDAC bit-exactly.
    values.append("0" if vt.rtc else "1")                     # 59 (inverted)
    values.append(str(vt.buoy_start_day))                     # 60
    values.append(_hhmm(vt.buoy_start_hour))                  # 61
    values.append(str(vt.ev_timing_min))                      # 62
    values.append(str(vt.n_valve_surface))                    # 63
    values.append(str(vt.park_desc_start_day))                # 64
    values.append(_hhmm(vt.park_desc_start_hour))             # 65
    values.append(str(vt.stab_day))                           # 66
    values.append(_hhmm(vt.stab_hour))                        # 67
    values.append(str(vt.park_desc_end_day))                  # 68
    values.append(_hhmm(vt.park_desc_end_hour))               # 69
    values.append(str(vt.n_valve_desc_park))                  # 70
    values.append(str(vt.n_pump_desc_park))                   # 71
    values.append(str(vt.n_entries_park))                     # 72
    values.append(str(vt.n_repos_park))                       # 73
    values.append(str(vt.n_valve_park))                       # 74
    values.append(str(vt.n_pump_park))                        # 75
    values.append(str(vt.prof_desc_start_day))                # 76
    values.append(_hhmm(vt.prof_desc_start_hour))             # 77
    values.append(str(vt.prof_desc_end_day))                  # 78
    values.append(_hhmm(vt.prof_desc_end_hour))               # 79
    values.append(str(vt.n_valve_desc_prof))                  # 80
    values.append(str(vt.n_pump_desc_prof))                   # 81
    values.append(str(vt.n_entries_prof))                     # 82
    values.append(str(vt.n_repos_prof))                       # 83
    values.append(str(vt.n_valve_drift_prof))                 # 84
    values.append(str(vt.n_pump_drift_prof))                  # 85
    values.append(str(vt.ascent_start_day))                   # 86
    values.append(_hhmm(vt.ascent_start_hour))                # 87
    values.append(str(vt.ascent_end_day))                     # 88
    values.append(_hhmm(vt.ascent_end_hour))                  # 89
    values.append(_abs_stamp(clock, vt.ascent_end_day,
                             vt.ascent_end_hour))             # 90
    values.append(str(vt.n_pump_ascent))                      # 91
    values.append(str(vt.n_emergency))                        # 92
    values.append(str(vt.remote_rx))                          # 93
    values.append(str(vt.remote_rej))                         # 94
    # 95 FLAG_SensorBoardStatus_NUMBER — 253 byte 106 "Show mode Sensor Board
    # (0: not active; 1 active)" (NKE §7.2.4.6). Decoded as ``show_sensor``;
    # offset verified by the packet being exactly 140 bytes with bytes
    # 107-139 all zero, matching the manual's trailing "Free (filled with
    # zeros) 33". Value 0 on all 269 vectors of the 10-group corpus, equal to
    # what INCOIS publishes on 2902093 cycles 45-53.
    values.append(str(vt.show_sensor))                        # 95

    if len(values) != len(TECH_ROW_NAMES):
        raise AssertionError(
            f"tech row drift: {len(values)} values vs "
            f"{len(TECH_ROW_NAMES)} names"
        )
    return [TechRow(cycle, n, v)
            for n, v in zip(TECH_ROW_NAMES, values, strict=True)]
