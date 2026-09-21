"""ARVOR-I ``_Rtraj.nc`` product model — Phase 4B.

Port of the Coriolis trajectory chain for Iridium-SBD ARVOR floats
(decIds 222/232; toolbox 20250516_076a, read end-to-end — see
``docs/phase_reports/ARVOR_I_PHASE4B_RTRAJ_MAPPING_2026-08-27.md``):

* ``process_trajectory_data_222_223_225_231_232.m`` — per-buffer row
  emitter (deep + surface-only branches);
* ``finalize_trajectory_data_ir_sbd.m`` — mail-only cycles, duplicate
  deep records, surface-merge, ``TET(N-1) := CST(N)``;
* ``set_n_cycle_vs_n_meas_consistency.m`` — N_CYCLE re-derived from rows;
* ``sort_trajectory_data.m`` / ``get_mc_order_list.m`` — row order.

Inputs come from the Phase-3 science model (:mod:`.arvor_i_science`):
``CycleTimeData`` (a full port of ``compute_prv_dates_222_to_227_231_232``
including the clock-offset-adjusted twins), ``GpsRecord`` with JAMSTEC QC,
mail first/last message times, the drift series, the
descent/ascent/near-surface profile series and the hydraulic packets kept
in the cycle buffers.

Sentinels follow the MATLAB chain: ``None`` row fields mean the empty
struct field the writer would leave at the NetCDF fill value (JULD
999999.0, char ' ', lat/lon 99999.0).  Nothing is silently discarded:
hydraulic action-duration rows (VALVE/PUMP_ACTION_DURATION) are TECH_AUX
stream material in the MATLAB chain and are bookkept on
``ArvorRtrajDataset.aux_rows``.

The GDAC ``_Rtraj.nc`` files for floats 6990711/7902408 were produced by a
legacy production pipeline (mapping report §7); this module implements the
public 076a chain, not that pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

from argo_decoder.platforms.provor_ir_sbd.arvor_i import (
    ArvorHydraulicPacket,
    counts_to_pres,
    counts_to_temp,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import (
    PRES_DEF,
    SAL_DEF,
    TEMP_DEF,
    ArvorCycle,
    ArvorMeasurement,
    ArvorScienceResult,
    CycleTimeData,
    GpsRecord,
    MailInfo,
)

__all__ = [
    "DDET",
    "DET",
    "EXPECTED_MC_CYCLE0",
    "EXPECTED_MC_DEEP",
    "MC",
    "MC_ORDER",
    "MC_RANK",
    "NCYCLE_FIELD_BY_MC",
    "ArvorRtrajDataset",
    "RtrajAuxRow",
    "RtrajCycleRecord",
    "RtrajRow",
    "build_arvor_rtraj_dataset",
]

NC_DATE_DEF = 999999.0
POS_FILL = 99999.0


class MC:
    """Argo reference table 15 codes used by the 222/232 emitter."""

    LAUNCH = 0
    CYCLE_START = 89
    DST = 100
    FST = 150
    SPY_IN_DESC_TO_PARK = 189
    DESC_PROF = 190
    DESC_PROF_DEEPEST_BIN = 203
    MAX_PRES_IN_DESC_TO_PARK = 198
    DET = 200
    PST = 250
    SPY_AT_PARK = 289
    DRIFT_AT_PARK = 290
    PET = 300
    MIN_PRES_IN_DRIFT_AT_PARK = 297
    MAX_PRES_IN_DRIFT_AT_PARK = 298
    RPP = 301
    SPY_IN_DESC_TO_PROF = 389
    MAX_PRES_IN_DESC_TO_PROF = 398
    DPST = 450
    SPY_AT_PROF = 489
    AST = 500
    MIN_PRES_IN_DRIFT_AT_PROF = 497
    MAX_PRES_IN_DRIFT_AT_PROF = 498
    ASC_PROF_DEEPEST_BIN = 503
    SPY_IN_ASC_PROF = 589
    ASC_PROF = 590
    LAST_ASC_PUMPED_CTD = 599
    AET = 600
    IN_WATER_SERIES_TST = 710
    IN_AIR_SERIES_TST = 711
    TST = 700
    FMT = 702
    SURFACE = 703
    LMT = 704
    TET = 800
    GROUNDED = 901


#: Row order inside one cycle (get_mc_order_list.m, case 222 family).
MC_ORDER: tuple[int, ...] = (
    MC.LAUNCH,
    MC.CYCLE_START,
    MC.DST,
    MC.SPY_IN_DESC_TO_PARK,
    MC.FST,
    MC.DESC_PROF,
    MC.DESC_PROF_DEEPEST_BIN,
    MC.MAX_PRES_IN_DESC_TO_PARK,
    MC.PST,
    MC.SPY_AT_PARK,
    MC.DRIFT_AT_PARK,
    MC.PET,
    MC.MIN_PRES_IN_DRIFT_AT_PARK,
    MC.MAX_PRES_IN_DRIFT_AT_PARK,
    MC.RPP,
    MC.SPY_IN_DESC_TO_PROF,
    MC.MAX_PRES_IN_DESC_TO_PROF,
    MC.DPST,
    MC.SPY_AT_PROF,
    MC.AST,
    MC.MIN_PRES_IN_DRIFT_AT_PROF,
    MC.MAX_PRES_IN_DRIFT_AT_PROF,
    MC.ASC_PROF_DEEPEST_BIN,
    MC.SPY_IN_ASC_PROF,
    MC.ASC_PROF,
    MC.LAST_ASC_PUMPED_CTD,
    593,  # ICE ascent abort
    MC.AET,
    MC.IN_WATER_SERIES_TST,
    MC.IN_AIR_SERIES_TST,
    MC.TST,
    MC.FMT,
    MC.SURFACE,
    MC.LMT,
    MC.TET,
    MC.GROUNDED,
)
MC_RANK = {code: rank for rank, code in enumerate(MC_ORDER)}

DET = 200  #: N_CYCLE-consistency key (juldDescentEnd); never emitted by 076a
DDET = 400  #: N_CYCLE-consistency key (juldDeepDescentEnd); never emitted by 076a

#: QC flag strings (init_default_values.m): '0' = no QC performed is set by
#: every row creator on DATED rows; '9' = missing value (create_one_meas_
#: float_time with time -1); ' ' (empty) stays for never-touched fields.
QC_NO_QC = "0"  # g_decArgo_qcStrNoQc
QC_MISSING = "9"  # g_decArgo_qcStrMissing

#: N_CYCLE JULD field per skeleton measurement code, in the struct/writer
#: order (get_traj_n_cycle_init_struct / set_status_of_n_cycle_juld).
NCYCLE_FIELD_BY_MC: dict[int, tuple[str, str]] = {
    MC.CYCLE_START: ("cycle_start", "cycle_start"),
    MC.DST: ("descent_start", "descent_to_park_start"),
    MC.FST: ("first_stab", "first_stab"),
    DET: ("descent_end", None),
    DDET: ("deep_descent_end", "descent_to_prof_end"),
    MC.PST: ("park_start", "descent_to_park_end"),
    MC.PET: ("park_end", "descent_to_prof_start"),
    MC.DPST: ("deep_park_start", "descent_to_prof_end"),
    MC.AST: ("ascent_start", "ascent_start"),
    MC.AET: ("ascent_end", "ascent_end"),
    MC.TST: ("trans_start", "trans_start"),
    MC.FMT: ("first_message", None),
    MC.LMT: ("last_message", None),
    MC.TET: ("trans_end", None),
}
DET = 200  #: N_CYCLE-consistency key (juldDescentEnd); never emitted by 076a

#: Expected skeleton codes per cycle (finalize_trajectory_data_ir_sbd).
EXPECTED_MC_DEEP = (
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
EXPECTED_MC_CYCLE0 = (MC.TST, MC.TET)


@dataclass
class RtrajRow:
    """One N_MEASUREMENT row (get_traj_one_meas_init_struct port).

    ``None`` means the MATLAB empty struct field (writer leaves the fill
    value).  ``juld_status``/``juld_qc``/``pos_*`` keep the MATLAB '' until
    the writer maps them to fills.
    """

    cycle_number: int
    measurement_code: int
    juld: float | None = None
    juld_status: str = ""
    juld_qc: str = ""
    juld_adj: float | None = None
    juld_adj_status: str = ""
    juld_adj_qc: str = ""
    latitude: float | None = None
    longitude: float | None = None
    pos_accuracy: str = ""
    pos_qc: str = ""
    satellite: str = ""
    axes_major: float | None = None
    axes_minor: float | None = None
    axes_angle: float | None = None
    pres: float | None = None
    temp: float | None = None
    psal: float | None = None
    surf_only: bool = False


@dataclass
class RtrajCycleRecord:
    """One N_CYCLE record (get_traj_n_cycle_init_struct port)."""

    cycle_number: int
    output_cycle_number: int = -1
    cycle_start: float | None = None
    cycle_start_status: str = ""
    descent_start: float | None = None
    descent_start_status: str = ""
    first_stab: float | None = None
    first_stab_status: str = ""
    descent_end: float | None = None
    descent_end_status: str = ""
    park_start: float | None = None
    park_start_status: str = ""
    park_end: float | None = None
    park_end_status: str = ""
    deep_descent_end: float | None = None
    deep_descent_end_status: str = ""
    deep_park_start: float | None = None
    deep_park_start_status: str = ""
    ascent_start: float | None = None
    ascent_start_status: str = ""
    deep_ascent_start: float | None = None
    deep_ascent_start_status: str = ""
    ascent_end: float | None = None
    ascent_end_status: str = ""
    trans_start: float | None = None
    trans_start_status: str = ""
    first_message: float | None = None
    first_message_status: str = ""
    first_location: float | None = None
    first_location_status: str = ""
    last_location: float | None = None
    last_location_status: str = ""
    last_message: float | None = None
    last_message_status: str = ""
    trans_end: float | None = None
    trans_end_status: str = ""
    clock_offset: float | None = None
    grounded: str = "N"
    rep_park_pres: float | None = None
    rep_park_pres_status: str = ""
    config_mission_number: int | None = None
    data_mode: str = "R"
    cycle_number_index: int = -1
    surf_only: bool = False


@dataclass
class RtrajAuxRow:
    """TECH_AUX-destined row bookkept from the emitter (never discarded)."""

    cycle_number: int
    parameter: str  # VALVE_ACTION_DURATION | PUMP_ACTION_DURATION
    value: float
    date: float
    measurement_code: int  # the Spy row it accompanies


@dataclass
class ArvorRtrajDataset:
    """Full trajectory product for one float, in final writer order."""

    dec_id: int
    wmo: int | None = None
    rows: list[RtrajRow] = field(default_factory=list)
    cycles: list[RtrajCycleRecord] = field(default_factory=list)
    aux_rows: list[RtrajAuxRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Provenance of the trajectory RTQC pass, once it has run.
    qc_outcome: object | None = None


# ---------------------------------------------------------------------------
# create_one_meas_* ports
# ---------------------------------------------------------------------------


def _row_float_time_ter(
    cycle: int,
    code: int,
    time: float | None,
    status: str,
    clock_drift_days: float | None,
) -> tuple[RtrajRow, float | None]:
    """create_one_meas_float_time_ter: status ``status``, adj ``status '3'``.

    Returns the row and the N_CYCLE value (adj when the offset is known,
    else the raw time; ``None`` when the time is missing).
    """

    row = RtrajRow(cycle_number=cycle, measurement_code=code)
    if time is None:
        return row, None
    row.juld = time
    row.juld_status = status
    row.juld_qc = QC_NO_QC
    if clock_drift_days is not None:
        row.juld_adj = time - clock_drift_days
        row.juld_adj_status = "3"
        row.juld_adj_qc = QC_NO_QC
        return row, row.juld_adj
    return row, row.juld


def _row_float_time_missing(
    cycle: int,
    code: int,
    status: str,
    drift_known: bool,
) -> RtrajRow:
    """create_one_meas_float_time with time ``-1`` (missing date branch).

    ``juld``/``juld_adj`` stay empty (fill); QC is '9' (missing value) on
    both, and ``juld_adj_status`` carries the row status when the clock
    drift is known (the finalize call sites always pass a non-empty
    drift), else the fill value.
    """

    row = RtrajRow(cycle_number=cycle, measurement_code=code)
    row.juld_status = status
    row.juld_qc = QC_MISSING
    if drift_known:
        row.juld_adj_status = status
        row.juld_adj_qc = QC_MISSING
    return row


def _row_launch(time: float, lon: float, lat: float) -> RtrajRow:
    """The MC 0 launch row (cycle -1), per the Argo standards.

    The launch date/position are *deployment metadata* duplicated from the
    META file, not a fix the float reported, so the surface-fix defaults
    used elsewhere in this module do not apply.  Argo DAC Trajectory
    Cookbook (DOI 10.13155/29824) §2.1.1 "Launch position and time":

        They should be stored as the first LATITUDE, LONGITUDE and JULD
        of the N_MEASUREMENT array with:
          * CYCLE_NUMBER = -1,
          * POSITION_QC = 0,
          * POSITION_ACCURACY = _FILLValue,
          * MEASUREMENT_CODE = 0,
          * JULD_STATUS = 4 - determined by satellite ...

    ``POSITION_ACCURACY`` is therefore left at fill (the deployment
    position has no positioning-system accuracy class -- our previous
    ``'G'`` wrongly claimed a GPS fix), and ``JULD_STATUS`` stays ``'4'``
    as both the cookbook and ``add_launch_data_ir_sbd.m``
    (``g_JULD_STATUS_4``) require.

    ``POSITION_QC``/``JULD_QC`` are deliberately left at the un-tested
    ``'0'`` here: they are RTQC outputs, and
    :func:`argo_decoder.rtqc.trajectory.apply_trajectory_rtqc` raises them
    to ``'1'`` once tests 2 and 3 have actually run on this row.  The
    cookbook's "POSITION_QC = 0 ... once the launch position has been
    checked, its QC should be set to 1" describes exactly that sequence.
    """

    return RtrajRow(
        cycle_number=-1,
        measurement_code=MC.LAUNCH,
        juld=time,
        juld_status="4",
        juld_qc=QC_NO_QC,
        latitude=lat,
        longitude=lon,
        pos_accuracy="",
        pos_qc=QC_NO_QC,
    )


def _row_surface(
    cycle: int,
    code: int,
    time: float,
    lon: float | None,
    lat: float | None,
    acc: str,
    sat: str,
    qc: str,
    clock_known: bool,
) -> RtrajRow:
    """create_one_meas_surface: status '4', position when not default.

    Callers are the satellite-timed events only: MC 702/704 (Iridium mail
    session times) and MC 703 (GPS/Iridium fixes).  Those dates are
    already UTC as received from the positioning/telemetry system, so
    ``JULD_ADJUSTED`` equals ``JULD`` and no clock offset is subtracted --
    the float RTC never entered the value.  This matches Coriolis, whose
    ``adjust_clock_offset_prv_ir.m`` adjusts only RTC-derived cycle
    timings and measurement bins, and Argo reference table 19, under
    which these rows carry status '4' ("value determined by satellite").
    RTC-derived events (MC 100/200/250/300/400/500/600/700/800) go
    through :func:`_row_float_time_ter` instead and *are* adjusted.
    """

    row = RtrajRow(
        cycle_number=cycle,
        measurement_code=code,
        juld=time,
        juld_status="4",
        juld_qc=QC_NO_QC,
    )
    if clock_known:
        row.juld_adj = time
        row.juld_adj_status = "4"
        row.juld_adj_qc = QC_NO_QC
    if lon is not None:
        row.longitude = lon
        row.latitude = lat
        row.pos_accuracy = acc
        row.satellite = sat
        row.pos_qc = qc
    return row


# ---------------------------------------------------------------------------
# Emitter (process_trajectory_data_222_223_225_231_232.m)
# ---------------------------------------------------------------------------


def _cycle_clock_days(timing: CycleTimeData) -> tuple[float | None, float | None]:
    """(floatClockDriftSec, floatClockDriftMin) for the cycle.

    ``cycle_clock_offset_s`` is the float RTC drift in seconds; dividing
    by 86400 expresses it in days, which is exactly what
    ``CLOCK_OFFSET(N_CYCLE)`` publishes.

    Argo User's Manual 3.44.0 (July 2025), §2.3.5 ``CLOCK_OFFSET``:

        "Real time corrections correspond to a data mode of "A".  For
        "A" mode files, JULD_ADJUSTED = JULD - CLOCK_OFFSET"

    That identity is normative and applies to every RTC-derived date in
    the file, so the *same* full-precision day offset is returned for
    both uses.  076a's second value (``round(drift_sec/60)/1440``)
    collapses any realistic second-scale drift to exactly 0, which would
    publish ``JULD_ADJUSTED == JULD`` alongside a non-zero
    ``CLOCK_OFFSET`` -- an internally inconsistent file that contradicts
    the manual.  The Coriolis minute rounding exists because *hydraulic*
    timings have 1-minute resolution (``adjust_clock_offset_prv_ir.m``
    ``adjust_hydrau``); it is not a licence to leave the published
    trajectory identity broken.

    Satellite-derived dates (MC 0/702/703/704 -- launch metadata, mail
    session times and GPS/Iridium fixes) are already UTC and are never
    clock-adjusted; that is handled at the row level, not here.
    """

    s = timing.cycle_clock_offset_s
    if s is None:
        return None, None
    drift_days = s / 86400.0
    return drift_days, drift_days


def _meas_params(row: RtrajRow, m: ArvorMeasurement) -> None:
    pres = None if m.pres in (None, PRES_DEF) else m.pres
    temp = None if m.temp in (None, TEMP_DEF) else m.temp
    psal = None if m.psal in (None, SAL_DEF) else m.psal
    row.pres, row.temp, row.psal = pres, temp, psal


def _bin_row(
    cycle: int,
    code: int,
    m: ArvorMeasurement,
    drift_days: float | None,
    status_by_trans: bool,
) -> RtrajRow:
    """One dated/undated measurement-bin row.

    ``status_by_trans`` selects the drift/near-surface rule (status '1'
    when the float transmitted the time, else '2'); profile bins are
    always status '2' in the emitter.
    """

    if m.date is not None:
        status = ("1" if m.trans else "2") if status_by_trans else "2"
        row, _ = _row_float_time_ter(cycle, code, m.date, status, drift_days)
    else:
        row = RtrajRow(cycle_number=cycle, measurement_code=code)
    _meas_params(row, m)
    return row


def _hydraulic_rows(
    cycle: int,
    cyc: ArvorCycle,
    timing: CycleTimeData,
    ref_day_offset: float | None,
    drift_days_min: float | None,
    aux_out: list[RtrajAuxRow],
) -> list[RtrajRow]:
    """Hydraulic Spy rows (MC 189/289/389/489/589) + aux duration rows."""

    if cyc.buffer is None:
        return []
    actions: list[tuple[float, float, int, int]] = []
    for sp in cyc.buffer.packets:
        if not isinstance(sp.packet, ArvorHydraulicPacket):
            continue
        for act in sp.packet.actions():
            if ref_day_offset is None:
                continue
            day = sp.packet.ref_day
            if day is None:
                continue
            date = day + ref_day_offset + act.ref_time_min / 1440.0
            actions.append((date, act.pressure_db, act.duration_s, 6 if not act.is_pump else 7))
    if not actions:
        return []
    actions.sort(key=lambda a: a[0])

    def raw(name: str) -> float | None:
        return getattr(timing, name) if timing is not None else None

    boundaries = [
        (raw("cycle_start"), raw("descent_to_park_end"), MC.SPY_IN_DESC_TO_PARK),
        (raw("descent_to_park_end"), raw("descent_to_prof_start"), MC.SPY_AT_PARK),
        (raw("descent_to_prof_start"), raw("descent_to_prof_end"), MC.SPY_IN_DESC_TO_PROF),
        (raw("descent_to_prof_end"), raw("ascent_start"), MC.SPY_AT_PROF),
        (raw("ascent_start"), raw("trans_start"), MC.SPY_IN_ASC_PROF),
    ]
    rows: list[RtrajRow] = []
    for lo, hi, code in boundaries:
        if timing is not None and timing.trans_start is None and code == MC.SPY_IN_ASC_PROF:
            # ice-detected cycle: last bucket open-ended
            if lo is None:
                continue
            selected = [a for a in actions if a[0] >= lo]
        else:
            if lo is None or hi is None:
                continue
            selected = [a for a in actions if lo <= a[0] < hi]
        for date, pres, dur, kind in selected:
            row, _ = _row_float_time_ter(cycle, code, date, "2", drift_days_min)
            row.pres = pres
            rows.append(row)
            aux_out.append(
                RtrajAuxRow(
                    cycle_number=cycle,
                    parameter=("VALVE_ACTION_DURATION" if kind == 6 else "PUMP_ACTION_DURATION"),
                    value=float(dur),
                    date=date,
                    measurement_code=code,
                )
            )
    return rows


def _profile_bin_rows(
    cycle: int, code: int, measurements: list[ArvorMeasurement], drift_days_sec: float | None
) -> list[RtrajRow]:
    return [
        _bin_row(cycle, code, m, drift_days_sec, status_by_trans=False)
        for m in measurements
        if m.date is not None
    ]


def _deepest_bin_rows(cycle: int, cyc: ArvorCycle, drift_days_sec: float | None) -> list[RtrajRow]:
    """MC 203 / 503: deepest bin of the descent / ascent profile(s).

    Both profile series are stored deep-first (Phase-3 sort); the MATLAB
    ``idNotDef(end)``/``idNotDef(1)`` picks reduce to the first row of the
    deep-first order in both directions.
    """

    out: list[RtrajRow] = []
    for kind, code in (
        ("descent", MC.DESC_PROF_DEEPEST_BIN),
        ("ascent_deep", MC.ASC_PROF_DEEPEST_BIN),
    ):
        best: tuple[float, ArvorMeasurement] | None = None
        for prof in cyc.profiles:
            if prof.kind != kind:
                continue
            candidates = [m for m in prof.measurements if m.pres is not None and m.pres != PRES_DEF]
            if not candidates:
                continue
            m = candidates[0]
            if best is None or m.pres > best[0]:
                best = (m.pres, m)
        if best is not None:
            out.append(_bin_row(cycle, code, best[1], drift_days_sec, status_by_trans=False))
    return out


def _tech_misc_rows(cycle: int, cyc: ArvorCycle) -> list[RtrajRow]:
    """MC 198/297/298/398/497/498 from the buffer's Tech#1 (LAST row)."""

    t1 = cyc.tech1
    if t1 is None:
        return []
    rows: list[RtrajRow] = []

    def pres_row(code: int, value: int) -> None:
        row = RtrajRow(cycle_number=cycle, measurement_code=code)
        row.pres = float(value)
        rows.append(row)

    pres_row(MC.MAX_PRES_IN_DESC_TO_PARK, t1.fields[19])
    if not (t1.fields[23] == 2100 and t1.fields[24] == 0):
        pres_row(MC.MIN_PRES_IN_DRIFT_AT_PARK, t1.fields[23])
        pres_row(MC.MAX_PRES_IN_DRIFT_AT_PARK, t1.fields[24])
    pres_row(MC.MAX_PRES_IN_DESC_TO_PROF, t1.fields[31])
    if not (t1.fields[36] == 2100 and t1.fields[37] == 0):
        pres_row(MC.MIN_PRES_IN_DRIFT_AT_PROF, t1.fields[36])
        pres_row(MC.MAX_PRES_IN_DRIFT_AT_PROF, t1.fields[37])
    return rows


def _last_pumped_row(cycle: int, cyc: ArvorCycle, timing: CycleTimeData) -> list[RtrajRow]:
    """MC 599 from the buffer's Tech#2 (LAST row); ice gate."""

    t2 = cyc.tech2
    if t2 is None or (timing is not None and timing.ice_ascent_aborted != 0):
        return []
    pres = counts_to_pres(t2.fields[15])
    temp = counts_to_temp(t2.fields[16])
    psal = t2.fields[17] / 1000.0
    if pres == 0.0 and temp == 0.0 and psal == 0.0:
        return []
    row = RtrajRow(cycle_number=cycle, measurement_code=MC.LAST_ASC_PUMPED_CTD)
    row.pres, row.temp, row.psal = pres, temp, psal
    return [row]


def _gps_rows(
    cycle: int,
    gps: list[GpsRecord],
    clock_known: bool,
) -> list[RtrajRow]:
    return [
        _row_surface(
            cycle,
            MC.SURFACE,
            g.date,
            g.lon,
            g.lat,
            "G",
            "",
            str(g.qc),
            clock_known,
        )
        for g in gps
    ]


def _iridium_rows(
    cycle: int,
    mails: list[MailInfo],
    clock_known: bool,
) -> list[RtrajRow]:
    """Iridium unit locations (cepRadius != 0) as MC 703 rows.

    The MATLAB mail store carries ONE cycleNumber per mail; a mail whose
    payload spans two cycles is attributed to its first tagged cycle
    (INFERRED: the store is built from the mail's first packet).
    """

    rows: list[RtrajRow] = []
    for mail in mails:
        if not mail.cycles or mail.cycles[0] != cycle or mail.pre_launch:
            continue
        if mail.cep_radius_km in (None, 0):
            continue
        radius_m = mail.cep_radius_km * 1000.0
        row = _row_surface(
            cycle,
            MC.SURFACE,
            mail.time_of_session,
            mail.lon,
            mail.lat,
            "I",
            "",
            "0",  # QC set during RTQC only
            clock_known,
        )
        row.axes_major = radius_m
        row.axes_minor = radius_m
        row.axes_angle = 0.0
        rows.append(row)
    return rows


def _emit_cycle(
    cyc: ArvorCycle,
    gps_by_cycle: dict[int, list[GpsRecord]],
    mails: list[MailInfo],
    aux_out: list[RtrajAuxRow],
    ref_day_offset: float | None,
) -> tuple[list[RtrajRow], RtrajCycleRecord]:
    """The deep + surface-only branches of the 222 emitter for one cycle."""

    cycle = cyc.cycle_number
    timing = cyc.timing
    rows: list[RtrajRow] = []
    rec = RtrajCycleRecord(
        cycle_number=cycle,
        output_cycle_number=cycle,
        # Launch mission (Argo convention "1 : first complete mission"):
        # same evidence as the mono products -- no config change in the
        # telemetry or the sheets. The GDAC Rtraj generator's raw 0
        # contradicts GDAC's own meta/mono values (1).
        config_mission_number=1,
    )
    rec.cycle_number_index = cycle

    clock_days_sec, clock_days_min = (
        _cycle_clock_days(timing) if timing is not None else (None, None)
    )
    clock_known = clock_days_sec is not None

    cycle_mails = [m for m in mails if m.cycles and m.cycles[0] == cycle and not m.pre_launch]
    first_msg = min((m.time_of_session for m in cycle_mails), default=None)
    last_msg = max((m.time_of_session for m in cycle_mails), default=None)
    gps = [g for g in gps_by_cycle.get(cycle, []) if not _is_pre_launch(g)]

    # FMT 702 (status 4) — always when the mail time exists
    if first_msg is not None:
        rows.append(_row_surface(cycle, MC.FMT, first_msg, None, None, "", "", "", clock_known))
        rec.first_message = first_msg
        rec.first_message_status = "4"

    # Surface locations: GPS + Iridium fixes, sorted by date
    surf = _gps_rows(cycle, gps, clock_known) + _iridium_rows(cycle, mails, clock_known)
    surf.sort(key=lambda r: r.juld if r.juld is not None else NC_DATE_DEF)
    rows.extend(surf)
    loc_dates = [r.juld for r in surf if r.juld is not None]
    if loc_dates:
        rec.first_location = min(loc_dates)
        rec.first_location_status = "4"
        rec.last_location = max(loc_dates)
        rec.last_location_status = "4"

    if last_msg is not None:
        rows.append(_row_surface(cycle, MC.LMT, last_msg, None, None, "", "", "", clock_known))
        rec.last_message = last_msg
        rec.last_message_status = "4"

    # clock offset / data mode (clockOffset field = floatClockDriftSec,
    # i.e. the seconds offset expressed in days)
    if clock_known and timing is not None:
        rec.clock_offset = timing.cycle_clock_offset_s / 86400.0
        rec.data_mode = "A"

    if cyc.deep:

        def skeleton(code: int, time: float | None, ncycle_field: str) -> None:
            row, ncycle_time = _row_float_time_ter(cycle, code, time, "2", clock_days_min)
            if code == MC.FST and time is not None and timing is not None:
                row.pres = timing.first_stab_pres
            rows.append(row)
            # the emitter sets the N_CYCLE status unconditionally, even
            # when the time is missing (value stays empty -> fill)
            setattr(rec, ncycle_field, ncycle_time)
            setattr(rec, f"{ncycle_field}_status", "2")

        skeleton(MC.CYCLE_START, timing.cycle_start if timing else None, "cycle_start")
        skeleton(MC.DST, timing.descent_to_park_start if timing else None, "descent_start")
        skeleton(MC.FST, timing.first_stab if timing else None, "first_stab")
        skeleton(MC.PST, timing.descent_to_park_end if timing else None, "park_start")
        skeleton(MC.PET, timing.descent_to_prof_start if timing else None, "park_end")
        skeleton(MC.DPST, timing.descent_to_prof_end if timing else None, "deep_park_start")
        skeleton(MC.AST, timing.ascent_start if timing else None, "ascent_start")
        skeleton(MC.AET, timing.ascent_end if timing else None, "ascent_end")
        skeleton(MC.TST, timing.trans_start if timing else None, "trans_start")
        # TET placeholder — filled from the next cycle's CST by finalize
        # (emitter line 513: create_one_meas_float_time(TET, -1, '9',
        # floatClockDriftMin) -> missing-date branch, QC '9')
        rows.append(_row_float_time_missing(cycle, MC.TET, "9", clock_known))
        rec.trans_end_status = "9"

        # profile dated bins
        for prof in cyc.profiles:
            if prof.kind == "descent":
                rows.extend(
                    _profile_bin_rows(cycle, MC.DESC_PROF, prof.measurements, clock_days_sec)
                )
            elif prof.kind == "ascent_deep":
                rows.extend(
                    _profile_bin_rows(cycle, MC.ASC_PROF, prof.measurements, clock_days_sec)
                )
            elif prof.kind == "ascent_shallow":
                # near-surface series: trans-flag status rule (status '1'
                # when the float transmitted the bin time, else '2')
                rows.extend(
                    _bin_row(cycle, MC.IN_WATER_SERIES_TST, m, clock_days_sec, True)
                    for m in prof.measurements
                    if m.date is not None
                )

        # park drift bins + RPP
        for m in cyc.drift:
            rows.append(_bin_row(cycle, MC.DRIFT_AT_PARK, m, clock_days_sec, status_by_trans=True))
        valid = [
            m
            for m in cyc.drift
            if m.pres not in (None, PRES_DEF)
            and m.temp not in (None, TEMP_DEF)
            and m.psal not in (None, SAL_DEF)
        ]
        if valid:
            means = (
                sum(m.pres for m in valid) / len(valid),
                sum(m.temp for m in valid) / len(valid),
                sum(m.psal for m in valid) / len(valid),
            )
            row = RtrajRow(cycle_number=cycle, measurement_code=MC.RPP)
            row.pres, row.temp, row.psal = means
            rows.append(row)
            rec.rep_park_pres = means[0]
            rec.rep_park_pres_status = "1"

        # hydraulic Spy rows (+ aux duration bookkeeping)
        rows.extend(
            _hydraulic_rows(
                cycle,
                cyc,
                timing or CycleTimeData(cycle_num=cycle),
                ref_day_offset,
                clock_days_min,
                aux_out,
            )
        )

        # deepest profile bins, tech misc, last pumped CTD
        rows.extend(_deepest_bin_rows(cycle, cyc, clock_days_sec))
        rows.extend(_tech_misc_rows(cycle, cyc))
        rows.extend(_last_pumped_row(cycle, cyc, timing or CycleTimeData(cycle_num=cycle)))

        # grounding
        grounded = "N"
        for date, pres in (
            (timing.first_grounding, timing.first_grounding_pres) if timing else (None, None),
            (timing.second_grounding, timing.second_grounding_pres) if timing else (None, None),
        ):
            if pres is None:
                continue
            row, _ = _row_float_time_ter(cycle, MC.GROUNDED, date, "2", clock_days_min)
            row.pres = pres
            rows.append(row)
            grounded = "Y"
        if cyc.tech1 is not None and cyc.tech1.fields[12] == 1:
            grounded = "Y"
        rec.grounded = grounded
    else:
        # surface-only branch: no deep rows, no cycle skeleton
        for row in rows:
            row.surf_only = True
        rec.surf_only = True

    return rows, rec


def _is_pre_launch(g: GpsRecord) -> bool:
    return g.cycle < 0


# ---------------------------------------------------------------------------
# finalize_trajectory_data_ir_sbd.m port
# ---------------------------------------------------------------------------


def _finalize(
    rows_by_cycle: dict[int, list[RtrajRow]],
    recs: dict[int, RtrajCycleRecord],
    mail_cycles: dict[int, tuple[float | None, float | None]],
    notes: list[str],
) -> None:
    cycles = sorted(rows_by_cycle)

    # mail cycles with no trajectory rows -> FMT/LMT-only records ('U')
    for cycle, (first_msg, last_msg) in sorted(mail_cycles.items()):
        if cycle in rows_by_cycle:
            continue
        rec = RtrajCycleRecord(
            cycle_number=cycle,
            output_cycle_number=cycle,
            grounded="U",
            surf_only=True,
            config_mission_number=1,  # launch mission, as every cycle record
        )
        rec.cycle_number_index = cycle
        rows: list[RtrajRow] = []
        if first_msg is not None:
            rows.append(_row_surface(cycle, MC.FMT, first_msg, None, None, "", "", "", False))
            rec.first_message = first_msg
            rec.first_message_status = "4"
        if last_msg is not None:
            rows.append(_row_surface(cycle, MC.LMT, last_msg, None, None, "", "", "", False))
            rec.last_message = last_msg
            rec.last_message_status = "4"
        recs[cycle] = rec
        rows_by_cycle[cycle] = rows
        notes.append(f"cycle {cycle}: mail data only -> surface-only record (finalize)")

    # TET(N-1) := CST(N) (juldAdj when the previous cycle has an offset)
    for prev, cur in pairwise(cycles):
        if cur != prev + 1:
            continue
        cst = next(
            (r for r in rows_by_cycle[cur] if r.measurement_code == MC.CYCLE_START),
            None,
        )
        tet = next(
            (r for r in rows_by_cycle[prev] if r.measurement_code == MC.TET),
            None,
        )
        if cst is None or tet is None or cst.juld is None:
            continue
        # MATLAB: transEndDate = CST(N).juldAdj when the PREVIOUS cycle's
        # offset is known (which the emitter sets = CST raw, since the
        # minute drift collapses to 0); create_one_meas_float_time then
        # swaps the pair: juld = transEndDate + clockDrift(prev),
        # juldAdj = transEndDate (status '3').
        value = cst.juld_adj if cst.juld_adj is not None else cst.juld
        prev_rec = recs.get(prev)
        clock_days = prev_rec.clock_offset if prev_rec is not None else None
        tet.juld_status = "2"
        tet.juld_qc = QC_NO_QC
        if clock_days is not None:
            tet.juld = value + clock_days
            tet.juld_adj = value
            tet.juld_adj_status = "3"
            tet.juld_adj_qc = QC_NO_QC
        else:
            tet.juld = value
            tet.juld_adj = None
        # finalize's N_CYCLE pass: trans_end(N-1) := juldCycleStart(N)
        recs[prev].trans_end = value
        recs[prev].trans_end_status = "2"

    # expected-MC fill rows for cycles >= 0
    for cycle in cycles:
        if cycle < 0:
            continue
        expected = EXPECTED_MC_CYCLE0 if cycle == 0 else EXPECTED_MC_DEEP
        present = {r.measurement_code for r in rows_by_cycle[cycle]}
        rec = recs.get(cycle)
        for code in expected:
            if code in present:
                continue
            # finalize line 358: create_one_meas_float_time(mc, -1, '9', 0)
            # -> missing-date branch with a NON-empty drift argument, so the
            # adjusted twins also take status '9' / QC '9' (values fill).
            row = _row_float_time_missing(cycle, code, "9", True)
            rows_by_cycle[cycle].append(row)
            if rec is not None and code in NCYCLE_FIELD_BY_MC:
                ncycle_field = NCYCLE_FIELD_BY_MC[code][0]
                setattr(rec, ncycle_field, None)
                setattr(rec, f"{ncycle_field}_status", "9")


# ---------------------------------------------------------------------------
# set_n_cycle_vs_n_meas_consistency.m port
# ---------------------------------------------------------------------------


def _consistency(
    rows_by_cycle: dict[int, list[RtrajRow]],
    recs: dict[int, RtrajCycleRecord],
) -> None:
    for cycle, rec in recs.items():
        rows = rows_by_cycle.get(cycle, [])
        for code, (ncycle_field, _) in NCYCLE_FIELD_BY_MC.items():
            candidates = [r for r in rows if r.measurement_code == code]
            if not candidates:
                continue
            juld = status = None
            for row in candidates:
                if row.juld_adj is not None:
                    value, st = row.juld_adj, row.juld_adj_status
                elif row.juld is not None:
                    value, st = row.juld, row.juld_status
                else:
                    continue
                take = (
                    juld is None
                    or (code == MC.FMT and value < juld)
                    or (code == MC.LMT and value > juld)
                )
                if take:
                    juld, status = value, st
            if juld is None or rec_juld(rec, ncycle_field) != juld:
                set_rec(rec, ncycle_field, juld)
            if status is not None:
                set_rec_status(rec, ncycle_field, status)

        # FIRST/LAST LOCATION from positioned surface rows
        surf = [r for r in rows if r.measurement_code == MC.SURFACE and r.longitude is not None]
        surf.sort(key=lambda r: r.juld if r.juld is not None else NC_DATE_DEF)
        if surf:
            rec.first_location = surf[0].juld
            rec.first_location_status = surf[0].juld_status or "4"
            rec.last_location = surf[-1].juld
            rec.last_location_status = surf[-1].juld_status or "4"
        # GROUNDED consistency
        if any(r.measurement_code == MC.GROUNDED for r in rows) and rec.grounded != "Y":
            rec.grounded = "Y"


def rec_juld(rec: RtrajCycleRecord, ncycle_field: str) -> float | None:
    return getattr(rec, ncycle_field)


def set_rec(rec: RtrajCycleRecord, ncycle_field: str, value: float | None) -> None:
    setattr(rec, ncycle_field, value)


def set_rec_status(rec: RtrajCycleRecord, ncycle_field: str, status: str) -> None:
    setattr(rec, f"{ncycle_field}_status", status)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_arvor_rtraj_dataset(
    result: ArvorScienceResult,
    *,
    wmo: int | None = None,
    dec_id: int | None = None,
    launch_position: tuple[float, float, float] | None = None,
) -> ArvorRtrajDataset:
    """Build the trajectory product from a Phase-3 science result.

    ``launch_position`` is the ``(juld, longitude, latitude)`` triple the
    MATLAB chain seeds from the operational float info (``add_launch_data_
    ir_sbd`` -> MC 0 row, cycle -1).  Our metadata carries no launch
    position; when omitted the launch row is skipped and a note is kept
    (DATA-COVERAGE).
    """

    from argo_decoder.platforms.provor_ir_sbd.arvor_i_tech import resolve_dec_id

    resolved = dec_id if dec_id is not None else resolve_dec_id(result)
    if resolved is None:
        raise ValueError("no Tech#1 packet found: cannot resolve decoder id")

    dataset = ArvorRtrajDataset(dec_id=resolved, wmo=wmo)

    gps_by_cycle: dict[int, list[GpsRecord]] = {}
    for g in result.gps_records:
        gps_by_cycle.setdefault(g.cycle, []).append(g)
    for records in gps_by_cycle.values():
        records.sort(key=lambda g: g.date)

    rows_by_cycle: dict[int, list[RtrajRow]] = {}
    recs: dict[int, RtrajCycleRecord] = {}
    aux: list[RtrajAuxRow] = []

    if launch_position is not None:
        juld, lon, lat = launch_position
        launch_row = _row_launch(juld, lon, lat)
        rows_by_cycle[-1] = [launch_row]
        dataset.notes.append("launch row (MC 0, cycle -1) from launch_position input")

    for cyc in result.cycles:
        if cyc.cycle_number == -1:
            dataset.notes.append(
                "cycle -1: parameter-only buffer, no trajectory rows (process_decoded_data)"
            )
            continue
        rows, rec = _emit_cycle(
            cyc,
            gps_by_cycle,
            result.mails,
            aux,
            result.ref_day_offset,
        )
        if cyc.cycle_number in rows_by_cycle:
            dataset.notes.append(f"cycle {cyc.cycle_number}: duplicate deep record, first kept")
            continue
        rows_by_cycle[cyc.cycle_number] = rows
        recs[cyc.cycle_number] = rec

    mail_cycles: dict[int, tuple[float | None, float | None]] = {}
    for mail in result.mails:
        if mail.pre_launch or not mail.cycles or mail.cycles[0] < 0:
            continue
        cycle = mail.cycles[0]
        first, last = mail_cycles.get(cycle, (None, None))
        first = mail.time_of_session if first is None else min(first, mail.time_of_session)
        last = mail.time_of_session if last is None else max(last, mail.time_of_session)
        mail_cycles[cycle] = (first, last)
    _finalize(rows_by_cycle, recs, mail_cycles, dataset.notes)
    _consistency(rows_by_cycle, recs)

    final_rows: list[RtrajRow] = []
    for cycle in sorted(rows_by_cycle):
        rows = rows_by_cycle[cycle]
        rows.sort(key=lambda r: MC_RANK.get(r.measurement_code, len(MC_ORDER)))
        final_rows.extend(rows)
    dataset.rows = final_rows
    dataset.cycles = [recs[c] for c in sorted(recs)]
    dataset.aux_rows = aux
    if launch_position is None:
        dataset.notes.append("no launch position in metadata: MC 0 row not emitted (DATA-COVERAGE)")
    return dataset
