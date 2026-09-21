"""ARVOR-I scientific reconstruction (Phase 3).

Port of the Coriolis downstream scientific layer that consumes the Phase-2
cycle buffers (``create_decoding_buffers_222_223_225_232.m`` output) and
produces per-cycle scientific intermediate objects:

    cycle buffers -> packet roles -> CTD measurements -> drift /
    descent / ascent reconstruction -> cycle timing -> GPS / position ->
    ArvorCycle / ArvorProfile objects

MATLAB sources (all vendored under ``tests/data/arvor_i/coriolis_src/``;
behaviour is PROVEN from these files unless noted):

* ``process_decoded_data.m`` (case {222}/{223,225}/{232}) — orchestration:
  get_decoded_data -> store_gps_data_ir_sbd -> sensor_2_value_* ->
  create_prv_drift_212_222_231 -> create_prv_profile_212_222_231 ->
  store_ice_information_arvor -> compute_prv_dates_222_to_227_231_232 ->
  adjust_clock_offset_prv_ir -> process_profiles_222_223_225_231_232.
* ``get_decoded_data.m`` — buffer packet assembly order +
  ``clean_duplicates_in_received_data`` (byte-identical rows collapse,
  keep first).
* ``decode_prv_data_ir_sbd_222_223_225.m`` — Tech#1 matrix layout
  ``[packType, items 1-73, floatTime, gpsLon, gpsLat, sbdFileDate]``,
  ``julD2FloatDayOffset = cycleStartDateDay - item8``, clock-offset events
  (item 73, only when item 61 GPS-valid), CTD rows
  ``[packType, cycle, dayFrac, -1, pres, temp, psal] x 15``.
* ``create_prv_drift_212_222_231.m`` / ``create_prv_profile_212_222_231.m``
  — measurement expansion, first-measurement timing, MC09 drift spacing,
  sentinel break, sort rules.
* ``compute_prv_dates_222_to_227_231_232.m`` — the cycle date chain.
* ``adjust_clock_offset_prv_ir.m`` + ``get_clock_offset_value_prv_ir.m`` +
  ``store_clock_offset_prv_ir.m`` — clock-offset model.
* ``store_gps_data_ir_sbd.m`` + ``update_gps_position_qc_ir_sbd.m`` +
  ``compute_jamstec_qc.m`` — GPS store + JAMSTEC QC (MAX_VEL = 3 m/s).
* ``process_profiles_222_223_225_231_232.m`` + ``get_pres_cut_off_prof.m``
  + ``get_nb_meas_list_from_tech.m`` — profile split / completion.
* ``add_profile_date_and_location_201_to_230_40x_2001_to_2003.m`` +
  ``compute_profile_location_from_iridium_locations_ir_sbd.m`` +
  ``fill_empty_profile_locations_ir_sbd.m`` — profile date + location.
* ``update_float_config_ir_sbd_222_223_225_232.m`` — Param#1/2 -> mission
  config mapping (MC/TC from Param#1 items 10../42.., IC from Param#2;
  items 44/45 x10 and 46/64 x1000 scaling).

Deliberate representation choices (documented in the Phase-3 report):

* MATLAB sentinels (99999.99 dateDef, 9999.9 presDef, ...) are represented
  as ``None``; raw count sentinels (99999) are preserved on the
  measurement provenance.
* Missing telemetry / missing configuration never fabricates values:
  dependent fields are ``None`` with an explicit reason (``notes``).
* Transport (mail) timestamps never become float timestamps except in the
  two Coriolis-defined fallbacks (profile date from first message time,
  Iridium-mail position fallback), each flagged in
  ``date_source``/``location_source``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from argo_decoder.platforms.provor_ir_sbd.arvor_i import (
    ArvorCtdPacket,
    ArvorHydraulicPacket,
    ArvorIPacket,
    ArvorIridiumMessage,
    ArvorParam1Packet,
    ArvorTech1Packet,
    ArvorTech2Packet,
    counts_to_pres,
    counts_to_psal,
    counts_to_temp,
    decode_arvor_i_sbd,
    read_arvor_i_eml,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_cycles import (
    BufferResult,
    CycleReconstructionResult,
    StreamPacket,
    reconstruct_cycles,
)

# MATLAB days are counted from 1950-01-01 (g_decArgo_janFirst1950InMatlab).
JAN_1950 = datetime(1950, 1, 1, tzinfo=UTC)

# MATLAB sentinels (init_default_values.m)
DATE_DEF = 99999.99999999
PRES_DEF = 9999.9
TEMP_DEF = 99.999
SAL_DEF = 99.999

# compute_jamstec_qc.m
JAMSTEC_MAX_VEL = 3.0  # m/s
GPS_PRECISION_M = 30.0  # accuracy class 'G'


def days_from_1950(dt: datetime) -> float:
    """datetime -> days since 1950-01-01 (MATLAB julian day)."""

    return (dt - JAN_1950).total_seconds() / 86400.0


def datetime_from_days(days: float) -> datetime:
    """Days since 1950-01-01 -> datetime (microsecond exactness)."""

    return JAN_1950 + timedelta(days=days)


def datenum_ddmmyy(dd: int, mm: int, yy: int) -> float:
    """MATLAB ``datenum(sprintf('%02d%02d%02d', dd,mm,yy)) - 1950``.

    Two-digit years use the Phase-1 pivot (yy <= 49 -> 2000s).
    """

    year = 2000 + yy if yy <= 49 else 1900 + yy
    return days_from_1950(datetime(year, mm, dd, tzinfo=UTC))


def datenum_hhmmssddmmyy(items: list[int]) -> float | None:
    """MATLAB ``datenum(..., 'HHMMSSddmmyy')`` from six items."""

    if len(items) < 6 or any(v is None for v in items):
        return None
    hh, mi, ss, dd, mm, yy = items
    year = 2000 + yy if yy <= 49 else 1900 + yy
    try:
        return days_from_1950(datetime(year, mm, dd, hh, mi, ss, tzinfo=UTC))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Float mission configuration (from Param#1 / Param#2 packets)
# ---------------------------------------------------------------------------

# update_float_config_ir_sbd_222_223_225_232.m scalings, applied to items
# (1-based) before storing as config values.
_PARAM1_SCALES = {44: 10, 45: 10, 46: 1000, 64: 1000}


@dataclass
class FloatMissionConfig:
    """Mission configuration values as Coriolis stores them.

    ``MC*``/``TC*`` come from Param#1 (items 10..41 / 42..70[71]),
    ``IC*`` from Param#2 (items 10..25).  Values absent from the telemetry
    (and from float metadata, which this dataset does not include) stay
    missing — nothing is defaulted except where the MATLAB code itself
    defaults (e.g. presCutOffProf 5.5 dbar).
    """

    values: dict[str, float] = field(default_factory=dict)
    source_packets: list[StreamPacket] = field(default_factory=list)

    def get(self, key: str) -> float | None:
        return self.values.get(key)

    @classmethod
    def from_stream(cls, stream: list[StreamPacket]) -> FloatMissionConfig:
        cfg = cls()
        for sp in stream:
            pk = sp.packet
            if isinstance(pk, ArvorParam1Packet):
                f = pk.fields
                cfg.source_packets.append(sp)
                for ident in range(0, 32):  # MC00..MC31 -> items 10..41
                    cfg.values.setdefault(f"MC{ident:02d}", float(f[10 + ident]))
                n_tc = 30 if len(f) > 72 else 29  # 232 has TC00..TC29
                for ident in range(0, n_tc):  # TC00.. -> items 42..
                    item = 42 + ident
                    if item >= len(f):
                        break
                    v = float(f[item])
                    if item in _PARAM1_SCALES:
                        v *= _PARAM1_SCALES[item]
                    cfg.values.setdefault(f"TC{ident:02d}", v)
            elif pk.pack_type == 7:
                f = pk.fields
                cfg.source_packets.append(sp)
                for ident in range(0, 16):  # IC00..IC15 -> items 10..25
                    cfg.values.setdefault(f"IC{ident:02d}", float(f[10 + ident]))
        return cfg


# ---------------------------------------------------------------------------
# Cycle timing (compute_prv_dates_222_to_227_231_232.m)
# ---------------------------------------------------------------------------


@dataclass
class CycleTimeData:
    """Every date field of the Coriolis cycle-time structure.

    Values are days since 1950-01-01 (float, exact MATLAB parity) or
    ``None`` when MATLAB would have the empty/``dateDef`` value, plus the
    clock-offset-adjusted twins (``*_adj``).  ``reasons`` explains every
    missing field (missing Tech packet / missing configuration).
    """

    cycle_num: int
    cycle_start: float | None = None
    descent_to_park_start: float | None = None
    first_stab: float | None = None
    first_stab_pres: float | None = None
    descent_to_park_end: float | None = None
    descent_to_prof_start: float | None = None
    descent_to_prof_end: float | None = None
    ascent_start: float | None = None
    ascent_end: float | None = None
    ascent_end_bis: float | None = None
    trans_start: float | None = None
    trans_start_bis: float | None = None
    float_time: float | None = None  # Tech#1 creation time ("gpsDate" col)
    eol_start: float | None = None
    first_grounding: float | None = None
    first_grounding_pres: float | None = None
    second_grounding: float | None = None
    second_grounding_pres: float | None = None
    first_emergency_ascent: float | None = None
    first_emergency_ascent_pres: float | None = None
    last_reset: float | None = None
    ice_ascent_aborted: int = 0
    # adjusted twins
    cycle_start_adj: float | None = None
    descent_to_park_start_adj: float | None = None
    first_stab_adj: float | None = None
    descent_to_park_end_adj: float | None = None
    descent_to_prof_start_adj: float | None = None
    descent_to_prof_end_adj: float | None = None
    ascent_start_adj: float | None = None
    ascent_end_adj: float | None = None
    trans_start_adj: float | None = None
    cycle_clock_offset_s: float | None = None
    reasons: dict[str, str] = field(default_factory=dict)

    _ADJUSTED = (
        ("cycle_start", "cycle_start_adj"),
        ("descent_to_park_start", "descent_to_park_start_adj"),
        ("first_stab", "first_stab_adj"),
        ("descent_to_park_end", "descent_to_park_end_adj"),
        ("descent_to_prof_start", "descent_to_prof_start_adj"),
        ("descent_to_prof_end", "descent_to_prof_end_adj"),
        ("ascent_start", "ascent_start_adj"),
        ("ascent_end", "ascent_end_adj"),
        ("trans_start", "trans_start_adj"),
    )

    def apply_clock_offset(self, offset_s: float | None) -> None:
        """adjust_clock_offset_prv_ir: meas -s/86400; cycle fields -round(s/60)/1440."""

        if offset_s is None:
            return
        self.cycle_clock_offset_s = offset_s
        minutes = round(offset_s / 60)
        for raw, adj in self._ADJUSTED:
            v = getattr(self, raw)
            if v is not None:
                setattr(self, adj, v - minutes / 1440.0)


def build_cycle_timing(
    tech1: ArvorTech1Packet | None,
    tech2: ArvorTech2Packet | None,
    *,
    deep: bool,
    cycle_num: int,
    config: FloatMissionConfig,
    ref_day_offset: float | None,
    ice_ascent_aborted: int = 0,
) -> CycleTimeData:
    """Port of ``compute_prv_dates_222_to_227_231_232``.

    ``ref_day_offset`` is the buffer's ``julD2FloatDayOffset`` (float-days
    -> days since 1950).  ``ascent_meas_min_pres`` feeds the ICE aborted
    check (min PRES of the ascent/NS/IA measurements + sub-surface point);
    the ICE algorithm itself only runs when ``IC00 > 0``.
    """

    t = CycleTimeData(cycle_num=cycle_num, ice_ascent_aborted=ice_ascent_aborted)
    if tech1 is None and tech2 is None:
        t.reasons["cycle_start"] = "no Tech#1/Tech#2 packet in buffer"
        return t

    if tech1 is not None:
        f1 = tech1.fields  # f1[k] == MATLAB item k
        t.float_time = days_from_1950(tech1.float_time) if tech1.float_time else None
        gps_date = t.float_time

        cycle_start_day: float | None = None
        if any(f1[k] != 0 for k in (5, 6, 7)):
            cycle_start_day = datenum_ddmmyy(f1[5], f1[6], f1[7])
            if deep:
                t.cycle_start = cycle_start_day + f1[9] / 1440.0

        if t.cycle_start is not None and deep:
            d2p_start = cycle_start_day + f1[13] / 1440.0
            if d2p_start < t.cycle_start:
                d2p_start += 1.0
            t.descent_to_park_start = d2p_start
            t.first_stab_pres = float(f1[18])
            t.first_stab = d2p_start
            if t.first_stab_pres != 0:
                fst = cycle_start_day + f1[14] / 1440.0
                if fst < d2p_start:
                    fst += 1.0
                t.first_stab = fst

            cycle1_short = cycle_num == 1 and f1[13] == f1[15] == f1[27]
            if not cycle1_short:
                d2p_end = cycle_start_day + f1[15] / 1440.0
                if d2p_end < t.first_stab:
                    d2p_end += 1.0
                # gregorian-day consistency with item 20 (drift park start day)
                d2p_end_day = datetime_from_days(d2p_end).day
                if (
                    d2p_end_day is not None
                    and d2p_end_day != f1[20]
                    and datetime_from_days(d2p_end - 1.0).day == f1[20]
                ):
                    d2p_end -= 1.0
                t.descent_to_park_end = d2p_end

            if gps_date is not None:
                trans = math.floor(gps_date) + f1[39] / 1440.0
                if trans > gps_date:
                    trans -= 1.0
                t.trans_start = trans

                # ascent end from configuration (minutes/seconds offsets)
                in_air_period = config.get("MC29")
                if in_air_period is not None:
                    mod = cycle_num if in_air_period == 0 else cycle_num % int(in_air_period)
                    if mod == 0:
                        in_air_min = config.get("MC31")
                        tc22 = config.get("TC22")
                        if in_air_min is not None and tc22 is not None:
                            t.ascent_end = (
                                trans
                                - 10.0 / 1440.0
                                - in_air_min * 2.0 / 1440.0
                                - (tc22 / 100.0) / 86400.0
                            )
                        else:
                            t.reasons["ascent_end"] = (
                                "CONFIG_MC31_/TC22_ unavailable (in-air cycle)"
                            )
                    else:
                        tc04 = config.get("TC04")
                        if tc04 is not None:
                            t.ascent_end = trans - 10.0 / 1440.0 - (tc04 / 100.0) / 86400.0
                        else:
                            t.reasons["ascent_end"] = (
                                "CONFIG_TC04_ unavailable (no Param#1 received;"
                                " Coriolis reads it from float metadata JSON)"
                            )
                else:
                    t.reasons["ascent_end"] = "CONFIG_MC29_ unavailable"

                if t.ascent_end is not None:
                    a_start = math.floor(t.ascent_end) + f1[38] / 1440.0
                    if a_start > t.ascent_end:
                        a_start -= 1.0
                    t.ascent_start = a_start
                    d2p_end2 = math.floor(a_start) + f1[28] / 1440.0
                    if d2p_end2 > a_start:
                        d2p_end2 -= 1.0
                    t.descent_to_prof_end = d2p_end2
                    if not cycle1_short:
                        d2p_start2 = math.floor(d2p_end2) + f1[27] / 1440.0
                        if d2p_start2 > d2p_end2:
                            d2p_start2 -= 1.0
                        t.descent_to_prof_start = d2p_start2

                if ice_ascent_aborted == 1:
                    t.trans_start_bis = t.trans_start
                    t.ascent_end_bis = t.ascent_end
                    t.ascent_end = t.trans_start
                    t.trans_start = None

        if f1[66] == 1:
            t.eol_start = datenum_hhmmssddmmyy(f1[67:73])

    if tech2 is not None:
        f2 = tech2.fields
        if deep:
            if t.cycle_start is not None:
                if f2[21] > 0:
                    t.first_grounding_pres = float(f2[22])
                    t.first_grounding = math.floor(t.cycle_start) + f2[23] + f2[24] / 1440.0
                if f2[21] > 1:
                    t.second_grounding_pres = float(f2[27])
                    t.second_grounding = math.floor(t.cycle_start) + f2[28] + f2[29] / 1440.0
            if f2[32] > 0:
                day = f2[36]
                if t.cycle_start is not None and ref_day_offset is not None:
                    while ref_day_offset + day + f2[33] / 1440.0 < t.cycle_start:
                        day += 256
                if ref_day_offset is not None:
                    t.first_emergency_ascent = ref_day_offset + day + f2[33] / 1440.0
                t.first_emergency_ascent_pres = float(f2[34])
        lr = datenum_hhmmssddmmyy(f2[46:52])
        if lr is not None:
            t.last_reset = lr

    return t


def _ice_aborted(
    config: FloatMissionConfig, gps_valid: float | None, min_pres: float | None
) -> int:
    """store_ice_information_arvor aborted-flag core (IC00-gated)."""

    ic0 = config.get("IC00")
    if ic0 is None or ic0 <= 0:
        return 0  # algorithm disabled (PROVEN gate)
    if gps_valid is not None:
        return 1 if gps_valid == 255 else 0
    ic4 = config.get("IC04")
    if min_pres is not None and ic4 is not None and abs(abs(min_pres) - ic4) < min_pres:
        return 1
    if min_pres is None:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Clock offset (store_clock_offset_prv_ir / get_clock_offset_value_prv_ir)
# ---------------------------------------------------------------------------


@dataclass
class ClockOffsetEvent:
    cycle: int
    float_time: float  # days since 1950 (Tech#1 creation time)
    offset_s: float

    @property
    def juld_float(self) -> float:
        return self.float_time


def collect_clock_offset_events(tech1s: list[ArvorTech1Packet]) -> list[ClockOffsetEvent]:
    evs: list[ClockOffsetEvent] = []
    for t1 in tech1s:
        # decode_prv_data: only stored when item 61 (GPS valid) == 1
        if t1.fields[61] == 1 and t1.float_time is not None:
            evs.append(
                ClockOffsetEvent(
                    cycle=t1.fields[1],
                    float_time=days_from_1950(t1.float_time),
                    offset_s=float(t1.clock_offset_s or 0),
                )
            )
    evs.sort(key=lambda e: e.float_time)
    return evs


def clock_offset_for_cycle(events: list[ClockOffsetEvent], timing: CycleTimeData) -> float | None:
    """get_clock_offset_value_prv_ir: exact-cycle mean, else interpolation."""

    if not events:
        return None
    if timing.cycle_num != 0:
        same = [e for e in events if e.cycle == timing.cycle_num]
        if same:
            return sum(e.offset_s for e in same) / len(same)
        before = [e for e in events if e.cycle <= timing.cycle_num - 1]
        after = [e for e in events if e.cycle >= timing.cycle_num]
        if before and after:
            e1, e2 = before[-1], after[0]
            ref = timing.trans_start
            if ref is None:
                ref = timing.ascent_end
            if ref is not None:
                x2 = e2.float_time + e2.offset_s / 86400.0
                if x2 == e1.float_time:
                    return e1.offset_s
                frac = (ref - e1.float_time) / (x2 - e1.float_time)
                off = e1.offset_s + frac * (e2.offset_s - e1.offset_s)
                if not math.isnan(off):
                    return float(round(off))
        return None
    same = [e for e in events if e.cycle == 0]
    return same[-1].offset_s if same else None


# ---------------------------------------------------------------------------
# CTD measurements (create_prv_drift / create_prv_profile)
# ---------------------------------------------------------------------------


@dataclass
class ArvorMeasurement:
    """One CTD measurement with full provenance."""

    pres: float | None
    temp: float | None
    psal: float | None
    slot: int  # 0-based measurement index inside the packet (0..14)
    date: float | None = None  # days since 1950 (float clock)
    date_adj: float | None = None  # after clock-offset adjustment
    trans: bool = False  # time transmitted by the float (first meas)
    date_source: str | None = None  # 'float-first-meas' | 'drift-spacing'
    packet: StreamPacket | None = None
    pres_counts: int | None = None
    temp_counts: int | None = None
    psal_counts: int | None = None

    def apply_clock_offset(self, offset_s: float | None) -> None:
        if offset_s is not None and self.date is not None:
            self.date_adj = self.date - offset_s / 86400.0


def _ctd_rows(pk: ArvorCtdPacket) -> list[tuple[int, int, int]]:
    """Raw count triplets, 15 slots."""

    return [
        (
            pk.fields[3 * i + 5] if 3 * i + 7 < len(pk.fields) else 0,
            pk.fields[3 * i + 6] if 3 * i + 7 < len(pk.fields) else 0,
            pk.fields[3 * i + 7],
        )
        for i in range(15)
    ]


def build_drift_measurements(
    ctd_packets: list[StreamPacket],
    config: FloatMissionConfig,
    ref_day_offset: float | None,
) -> tuple[list[ArvorMeasurement], list[str]]:
    """create_prv_drift_212_222_231: park series, MC09 spacing, date sort."""

    notes: list[str] = []
    mc09 = config.get("MC09")
    out: list[ArvorMeasurement] = []
    drift = [sp for sp in ctd_packets if sp.pack_type == 2]
    if not drift:
        return out, notes
    if mc09 is None:
        notes.append(
            "CONFIG_MC09_ (drift sampling period) unavailable: non-first drift"
            " measurement dates not reconstructed (no Param#1 in telemetry)"
        )
    for sp in drift:
        pk = sp.packet
        assert isinstance(pk, ArvorCtdPacket)
        first_day_frac = pk.first_meas_time_day_fraction
        prev_date: float | None = None
        for slot, (pc, tc, sc) in enumerate(_ctd_rows(pk)):
            if (pc, tc, sc) == (0, 0, 0):
                break  # trailing fill -> MATLAB break
            if slot == 0:
                date = (
                    first_day_frac + ref_day_offset
                    if first_day_frac is not None and ref_day_offset is not None
                    else None
                )
                meas = ArvorMeasurement(
                    pres=counts_to_pres(pc),
                    temp=counts_to_temp(tc),
                    psal=counts_to_psal(sc),
                    slot=slot,
                    date=date,
                    trans=True,
                    date_source="float-first-meas",
                    packet=sp,
                    pres_counts=pc,
                    temp_counts=tc,
                    psal_counts=sc,
                )
            else:
                date = (
                    prev_date + mc09 / 24.0 if prev_date is not None and mc09 is not None else None
                )
                meas = ArvorMeasurement(
                    pres=counts_to_pres(pc),
                    temp=counts_to_temp(tc),
                    psal=counts_to_psal(sc),
                    slot=slot,
                    date=date,
                    trans=False,
                    date_source="drift-spacing" if date is not None else None,
                    packet=sp,
                    pres_counts=pc,
                    temp_counts=tc,
                    psal_counts=sc,
                )
            prev_date = date
            out.append(meas)
    # MATLAB sorts the drift series by date ascending (undated keep order)
    dated = [m for m in out if m.date is not None]
    undated = [m for m in out if m.date is None]
    dated.sort(key=lambda m: m.date)
    return dated + undated, notes


def build_profile_measurements(
    ctd_packets: list[StreamPacket],
    ref_day_offset: float | None,
    in_air_period_s: float | None = None,
) -> dict[int, list[ArvorMeasurement]]:
    """create_prv_profile_212_222_231 per packet type.

    Types 1 (descent) and 3 (ascent): only the first measurement of each
    packet is dated (float first-measurement time); other slots carry no
    timestamp (MATLAB leaves dateDef).  Types 13/14 (unobserved in this
    dataset) would use MC30 spacing — not implemented, flagged by the
    caller.  Both profiles are sorted by pressure DESCENDING (deep first).
    """

    out: dict[int, list[ArvorMeasurement]] = {1: [], 3: []}
    for sp in ctd_packets:
        if sp.pack_type not in (1, 3):
            continue
        pk = sp.packet
        assert isinstance(pk, ArvorCtdPacket)
        first_day_frac = pk.first_meas_time_day_fraction
        for slot, (pc, tc, sc) in enumerate(_ctd_rows(pk)):
            if (pc, tc, sc) == (0, 0, 0):
                break
            if slot == 0:
                date = (
                    first_day_frac + ref_day_offset
                    if first_day_frac is not None and ref_day_offset is not None
                    else None
                )
                meas = ArvorMeasurement(
                    pres=counts_to_pres(pc),
                    temp=counts_to_temp(tc),
                    psal=counts_to_psal(sc),
                    slot=slot,
                    date=date,
                    trans=True,
                    date_source="float-first-meas",
                    packet=sp,
                    pres_counts=pc,
                    temp_counts=tc,
                    psal_counts=sc,
                )
            else:
                meas = ArvorMeasurement(
                    pres=counts_to_pres(pc),
                    temp=counts_to_temp(tc),
                    psal=counts_to_psal(sc),
                    slot=slot,
                    date=None,
                    trans=False,
                    packet=sp,
                    pres_counts=pc,
                    temp_counts=tc,
                    psal_counts=sc,
                )
            out[sp.pack_type].append(meas)
    for k in out:
        out[k].sort(key=lambda m: -(m.pres if m.pres is not None else PRES_DEF))
    return out


# ---------------------------------------------------------------------------
# GPS (store_gps_data_ir_sbd + update_gps_position_qc_ir_sbd + jamstec)
# ---------------------------------------------------------------------------


@dataclass
class GpsRecord:
    cycle: int
    date: float  # Tech#1 float time (days since 1950)
    lon: float
    lat: float
    mail_date: float  # transport (mail session) time
    accuracy: str = "G"
    qc: int = 0  # 0 not assessed, 1 good, 4 bad (jamstec)
    tech1: ArvorTech1Packet | None = None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """distance_lpo equivalent (metres) for the JAMSTEC speed test."""

    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def jamstec_qc(records: list[GpsRecord]) -> None:
    """compute_jamstec_qc port (per cycle group, previous-cycle anchor).

    First pass: speed of the cycle's first fix vs the previous cycle's
    last good fix must be <= 3 m/s.  Later passes flag byte-identical
    consecutive fixes (same position and time) and >1-day gaps within one
    cycle.  The multi-fix disambiguation branches of the MATLAB loop are
    approximated; for these floats every cycle group holds exactly one
    fix (PROVEN from the raw data), for which the port is exact.
    """

    by_cycle: dict[int, list[GpsRecord]] = {}
    for r in records:
        by_cycle.setdefault(r.cycle, []).append(r)
    for cyc in by_cycle:
        group = sorted(by_cycle[cyc], key=lambda r: r.date)
        # reference: last QC==1 fix of the previous cycle (by date)
        prev = sorted(by_cycle.get(cyc - 1, []), key=lambda r: r.date)
        anchor = next((r for r in reversed(prev) if r.qc == 1), None)
        for i, r in enumerate(group):
            r.qc = 1
            if i == 0:
                if anchor is not None:
                    dist = _haversine_m(anchor.lat, anchor.lon, r.lat, r.lon)
                    dt = abs(r.date - anchor.date)
                    if dt > 0:
                        speed = dist / (dt * 86400.0)
                        if speed > JAMSTEC_MAX_VEL:
                            r.qc = 4
            else:
                p = group[i - 1]
                if p.lat == r.lat and p.lon == r.lon and p.date == r.date:
                    r.qc = 4  # duplicated fix
                elif (r.date - p.date) > 1.0:
                    r.qc = 4  # >1 day gap inside one cycle


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@dataclass
class ProfileLocation:
    lat: float | None = None
    lon: float | None = None
    date: float | None = None
    qc: int | str | None = None
    system: str = "GPS"
    source: str = "none"  # gps | launch-gps | iridium-mail | interpolated | none


@dataclass
class ArvorProfile:
    kind: str  # 'descent' | 'ascent_deep' | 'ascent_shallow'
    direction: str  # 'D' | 'A'
    cycle_number: int
    measurements: list[ArvorMeasurement] = field(default_factory=list)
    date: float | None = None  # profile reference date (JULD), days since 1950
    date_adj: float | None = None
    date_source: str | None = None  # descent-to-park start | ascent end | ...
    location: ProfileLocation = field(default_factory=ProfileLocation)
    sub_surface_pres: float | None = None
    pres_cutoff: float | None = None
    expected_n_meas: int | None = None
    profile_completed: int | None = None  # expected - received
    min_meas_date: float | None = None
    max_meas_date: float | None = None


# ---------------------------------------------------------------------------
# Cycle / result objects
# ---------------------------------------------------------------------------


@dataclass
class ArvorCycle:
    cycle_number: int
    buffer: BufferResult | None = None
    completed: bool = False
    delayed: int = 0
    ice_delayed: bool = False
    deep: bool = False
    go: int = 0
    timing: CycleTimeData | None = None
    tech1: ArvorTech1Packet | None = None
    tech2: ArvorTech2Packet | None = None
    gps: GpsRecord | None = None
    drift: list[ArvorMeasurement] = field(default_factory=list)
    profiles: list[ArvorProfile] = field(default_factory=list)
    hydraulic: list[ArvorHydraulicPacket] = field(default_factory=list)
    params: list[ArvorIPacket] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def descent(self) -> list[ArvorMeasurement]:
        for p in self.profiles:
            if p.kind == "descent":
                return p.measurements
        return []

    @property
    def ascent(self) -> list[ArvorMeasurement]:
        out: list[ArvorMeasurement] = []
        for p in self.profiles:
            if p.kind in ("ascent_deep", "ascent_shallow"):
                out.extend(p.measurements)
        return out


@dataclass
class MailInfo:
    """Mail metadata (transport layer), tagged with packet cycles."""

    message: ArvorIridiumMessage
    cycles: list[int]
    time_of_session: float  # days since 1950 (transport)
    lat: float | None
    lon: float | None
    cep_radius_km: float | None
    pre_launch: bool = False  # session before launch date (factory/deck)


@dataclass
class ArvorScienceResult:
    cycles: list[ArvorCycle] = field(default_factory=list)
    gps_records: list[GpsRecord] = field(default_factory=list)
    clock_offset_events: list[ClockOffsetEvent] = field(default_factory=list)
    float_config: FloatMissionConfig | None = None
    mails: list[MailInfo] = field(default_factory=list)
    param_only_cycles: list[int] = field(default_factory=list)  # cycle -1 buffers
    ref_day_offset: float | None = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Profile date + location (add_profile_date_and_location_201_to_230_40x)
# ---------------------------------------------------------------------------


def _profile_date(
    timing: CycleTimeData, direction: str, mails: list[MailInfo], cycle: int
) -> tuple[float | None, str]:
    if direction == "D":
        if timing.descent_to_park_start_adj is not None:
            return timing.descent_to_park_start_adj, "descent-to-park-start"
        if timing.descent_to_park_start is not None:
            return timing.descent_to_park_start, "descent-to-park-start"
        t = _last_msg_time(mails, cycle - 1)
        if t is not None:
            return t, "iridium-mail (last message of cycle N-1)"
        return None, "unavailable"
    if timing.ascent_end_adj is not None:
        return timing.ascent_end_adj, "ascent-end"
    if timing.ascent_end is not None:
        return timing.ascent_end, "ascent-end"
    if timing.trans_start_adj is not None:
        return timing.trans_start_adj, "transmission-start (ascent-end unavailable)"
    if timing.trans_start is not None:
        return timing.trans_start, "transmission-start (ascent-end unavailable)"
    t = _first_msg_time(mails, cycle)
    if t is not None:
        return t, "iridium-mail (first message of cycle N)"
    return None, "unavailable"


def _first_msg_time(mails: list[MailInfo], cycle: int) -> float | None:
    times = [m.time_of_session for m in mails if not m.pre_launch and cycle in m.cycles]
    return min(times) if times else None


def _last_msg_time(mails: list[MailInfo], cycle: int) -> float | None:
    times = [m.time_of_session for m in mails if not m.pre_launch and cycle in m.cycles]
    return max(times) if times else None


def _profile_location_gps(
    gps_records: list[GpsRecord], cycle: int, latest: bool
) -> ProfileLocation | None:
    good = [r for r in gps_records if r.cycle == cycle and r.qc == 1]
    if not good:
        return None
    r = max(good, key=lambda x: x.date) if latest else min(good, key=lambda x: x.date)
    loc = ProfileLocation(lat=r.lat, lon=r.lon, date=r.date, qc=1, system="GPS")
    loc.source = "gps"
    return loc


def _iridium_mail_location(mails: list[MailInfo], cycle: int) -> ProfileLocation | None:
    """compute_profile_location_from_iridium_locations_ir_sbd (CEP<5km, 1/r^2)."""

    use = [
        m
        for m in mails
        if not m.pre_launch
        and cycle in m.cycles
        and m.cep_radius_km not in (None, 0)
        and m.cep_radius_km < 5
    ]
    if not use:
        return None
    weight = [1.0 / (m.cep_radius_km**2) for m in use]  # type: ignore[operator]
    wsum = sum(weight)
    lon = sum(m.lon * w for m, w in zip(use, weight, strict=True)) / wsum  # type: ignore[operator]
    lat = sum(m.lat * w for m, w in zip(use, weight, strict=True)) / wsum  # type: ignore[operator]
    loc = ProfileLocation(
        lat=lat,
        lon=lon,
        date=sum(m.time_of_session for m in use) / len(use),
        qc=1,
        system="IRIDIUM",
    )
    loc.source = "iridium-mail"
    return loc


def _assign_locations(
    cycles: list[ArvorCycle], gps_records: list[GpsRecord], mails: list[MailInfo]
) -> None:
    """add_profile_date_and_location_201_to_230_40x + fill_empty pass."""

    for cyc in cycles:
        for prof in cyc.profiles:
            if prof.direction == "D":
                loc = _profile_location_gps(gps_records, cyc.cycle_number - 1, latest=True)
            else:
                loc = _profile_location_gps(gps_records, cyc.cycle_number, latest=False)
            if loc is None:
                mail_cy = cyc.cycle_number - 1 if prof.direction == "D" else cyc.cycle_number
                loc = _iridium_mail_location(mails, mail_cy)
            prof.location = loc if loc is not None else ProfileLocation(source="none")
            if loc is None:
                cyc.notes.append(
                    f"profile {prof.kind}: no GPS/Iridium location"
                    " (fill_empty interpolation would apply at NetCDF stage)"
                )

    # fill_empty_profile_locations_ir_sbd: linear interpolation between the
    # nearest located profiles, linear extrapolation at the edges (QC 8)
    located = [
        p
        for c in cycles
        for p in c.profiles
        if p.date is not None and p.location.source in ("gps", "iridium-mail")
    ]
    located.sort(key=lambda p: p.date)
    # one anchor per distinct date: deep+shallow of one surfacing share the
    # same fix, and interp/extrap needs distinct bracketing dates
    seen: dict[float, ProfileLocation] = {}
    for p in located:
        seen.setdefault(round(p.date, 9), p)
    located = sorted(seen.values(), key=lambda p: p.date)
    for c in cycles:
        for p in c.profiles:
            if p.date is None or p.location.source != "none":
                continue
            before = [q for q in located if q.date <= p.date]
            after = [q for q in located if q.date > p.date]
            q1 = q2 = None
            if before and after:
                q1, q2 = before[-1], after[0]  # linear interpolation
            elif len(after) >= 2:
                q1, q2 = after[0], after[1]  # extrapolate forwards
            elif len(before) >= 2:
                q1, q2 = before[-2], before[-1]  # extrapolate backwards
            if q1 is not None and q2 is not None and q2.date != q1.date:
                f = (p.date - q1.date) / (q2.date - q1.date)
                lat = q1.location.lat + f * (q2.location.lat - q1.location.lat)
                lon = q1.location.lon + f * (q2.location.lon - q1.location.lon)
                p.location = ProfileLocation(lat=lat, lon=lon, date=p.date, qc=8)
                p.location.source = "interpolated"
                p.location.system = q1.location.system


# ---------------------------------------------------------------------------
# Top-level reconstruction
# ---------------------------------------------------------------------------


def _dedup_buffer(
    packets: list[StreamPacket],
) -> tuple[list[StreamPacket], list[tuple[StreamPacket, str]]]:
    """clean_duplicates_in_received_data: byte-identical rows, keep first."""

    seen: set[bytes] = set()
    kept: list[StreamPacket] = []
    dropped: list[tuple[StreamPacket, str]] = []
    for sp in packets:
        raw = bytes(getattr(sp.packet, "raw", b"") or b"")
        if raw and raw in seen:
            dropped.append((sp, "duplicate raw packet row (byte-identical retransmission)"))
        else:
            if raw:
                seen.add(raw)
            kept.append(sp)
    return kept, dropped


def reconstruct_science(
    messages: list[ArvorIridiumMessage],
    launch_date: datetime | None = None,
    cycles_result: CycleReconstructionResult | None = None,
    extra_config: FloatMissionConfig | None = None,
) -> ArvorScienceResult:
    """Run the full Phase-3 scientific layer over a float's messages."""

    if cycles_result is None:
        cycles_result = reconstruct_cycles(messages, launch_date=launch_date)
    res = ArvorScienceResult()
    res.float_config = FloatMissionConfig.from_stream(
        [sp for b in cycles_result.buffers for sp in b.packets]
        + cycles_result.unranked_packets
        + cycles_result.kept_pre_launch_param_packets
    )
    if extra_config is not None:
        for k, v in extra_config.values.items():
            res.float_config.values.setdefault(k, v)

    # mail metadata tagged with the cycles its packets carry
    cyc_by_msg: dict[int, int] = {}
    for b in cycles_result.buffers:
        for sp in b.packets:
            cyc_by_msg[id(sp.message)] = sp.packet.cycle if sp.packet.cycle is not None else -1
    for m in messages:
        if not m.payload:
            continue
        dec = decode_arvor_i_sbd(m.payload)
        cycles = sorted({pk.cycle for pk in dec.packets if pk.cycle is not None})
        if not cycles and id(m) in cyc_by_msg:
            cycles = [cyc_by_msg[id(m)]]
        ses = m.session
        pre_launch = bool(
            launch_date is not None
            and ses.session_time_utc is not None
            and ses.session_time_utc < launch_date
        )
        res.mails.append(
            MailInfo(
                message=m,
                pre_launch=pre_launch,
                cycles=cycles,
                time_of_session=days_from_1950(ses.session_time_utc)
                if ses.session_time_utc
                else 0.0,
                lat=ses.gps_lat,
                lon=ses.gps_lon,
                cep_radius_km=ses.cep_radius_km,
            )
        )

    # clock offset events from every Tech#1 (GPS-valid only)
    all_t1 = [
        sp.packet
        for b in cycles_result.buffers
        for sp in b.packets
        if isinstance(sp.packet, ArvorTech1Packet)
    ]
    res.clock_offset_events = collect_clock_offset_events(all_t1)

    config = res.float_config
    ref_day_offset: float | None = None

    for buf in cycles_result.buffers:
        cycle = buf.cycle_number
        packets, dropped = _dedup_buffer(buf.packets)
        for sp, reason in dropped:
            res.notes.append(f"cycle {cycle}: dropped {sp.pack_type}-packet ({reason})")

        t1s = [sp.packet for sp in packets if isinstance(sp.packet, ArvorTech1Packet)]
        t2s = [sp.packet for sp in packets if isinstance(sp.packet, ArvorTech2Packet)]
        params = [sp.packet for sp in packets if sp.pack_type in (5, 7)]

        if cycle == -1:
            # process_decoded_data: cycle -1 buffers carry parameters only
            res.param_only_cycles.append(cycle)
            continue

        t1_stream = next((sp for sp in packets if isinstance(sp.packet, ArvorTech1Packet)), None)

        # julD2FloatDayOffset from the (single) Tech#1 of the buffer
        for t1 in t1s:
            if any(t1.fields[k] != 0 for k in (5, 6, 7)):
                cs_day = datenum_ddmmyy(t1.fields[5], t1.fields[6], t1.fields[7])
                ref_day_offset = cs_day - t1.fields[8]
        if ref_day_offset is not None:
            res.ref_day_offset = ref_day_offset

        t1 = t1s[0] if t1s else None
        t2 = t2s[0] if t2s else None

        cyc = ArvorCycle(
            cycle_number=cycle,
            buffer=buf,
            completed=buf.completed,
            delayed=buf.delayed,
            ice_delayed=buf.ice_delayed,
            deep=buf.deep,
            go=buf.go,
            tech1=t1,
            tech2=t2,
            params=params,
        )

        drift, dnotes = build_drift_measurements(packets, config, ref_day_offset)
        cyc.drift = drift
        cyc.notes.extend(dnotes)

        prof_meas = build_profile_measurements(packets, ref_day_offset)
        for pt in (13, 14):
            if any(sp.pack_type == pt for sp in packets):
                cyc.notes.append(
                    f"packet type {pt} present: MC30-spaced dates not implemented"
                    " (unobserved in this dataset)"
                )

        min_asc_pres = None
        asc = prof_meas.get(3, [])
        if asc:
            min_asc_pres = min(m.pres for m in asc if m.pres is not None)
        # sub-surface point from Tech#2 (get_pres_cut_off_prof)
        sub_surf: float | None = None
        if t2 is not None:
            f2 = t2.fields
            if any(f2[k] != 0 for k in (15, 16, 17)):
                sub_surf = counts_to_pres(f2[15])
        if min_asc_pres is not None and sub_surf is not None:
            ice_min_pres = min(min_asc_pres, sub_surf)
        else:
            ice_min_pres = min_asc_pres if min_asc_pres is not None else sub_surf
        ice_abort = _ice_aborted(
            config,
            t1.fields[61] if t1 else None,
            ice_min_pres,
        )
        timing = build_cycle_timing(
            t1,
            t2,
            deep=buf.deep,
            cycle_num=cycle,
            config=config,
            ref_day_offset=ref_day_offset,
            ice_ascent_aborted=ice_abort,
        )
        offset = clock_offset_for_cycle(res.clock_offset_events, timing)
        timing.apply_clock_offset(offset)
        for m in drift + prof_meas.get(1, []) + asc:
            m.apply_clock_offset(offset)
        cyc.timing = timing

        # GPS record for this cycle (valid fixes only, MATLAB item-61 gate)
        if t1 is not None and t1.fields[61] == 1 and t1.float_time is not None:
            rec = GpsRecord(
                cycle=cycle,
                date=days_from_1950(t1.float_time),
                lon=t1.gps_lon if t1.gps_lon is not None else 0.0,
                lat=t1.gps_lat if t1.gps_lat is not None else 0.0,
                mail_date=(
                    days_from_1950(t1_stream.date) if t1_stream else days_from_1950(t1.float_time)
                ),
                tech1=t1,
            )
            res.gps_records.append(rec)
            cyc.gps = rec

        # profiles (process_profiles_222_223_225_231_232)
        strict = True  # 222/223/225 use > cutoff; 232 uses >=
        engine = getattr(t1, "firmware_checksum", None) if t1 else None
        if engine == 13872:
            strict = False
        px02 = config.get("PX02")
        pres_cutoff = sub_surf if sub_surf is not None else (px02 if px02 is not None else 5.5)

        profiles: list[ArvorProfile] = []
        if prof_meas.get(1):
            p = ArvorProfile(
                kind="descent",
                direction="D",
                cycle_number=cycle,
                measurements=prof_meas[1],
                sub_surface_pres=sub_surf,
                pres_cutoff=pres_cutoff,
            )
            if t2 is not None:
                p.expected_n_meas = t2.fields[8] + t2.fields[9]
                p.profile_completed = p.expected_n_meas - len(prof_meas[1])
            profiles.append(p)
        asc_all = prof_meas.get(3, [])
        if asc_all:

            def _qualifies(v: float, cutoff: float = pres_cutoff, eq: bool = strict) -> bool:
                return v > cutoff if eq else v >= cutoff

            deep_idx = [
                i
                for i, m in enumerate(asc_all)
                if m.pres is not None and m.pres != PRES_DEF and _qualifies(m.pres)
            ]
            shallow_idx = [
                i
                for i, m in enumerate(asc_all)
                if m.pres is not None and m.pres != PRES_DEF and not _qualifies(m.pres)
            ]
            if deep_idx:
                p = ArvorProfile(
                    kind="ascent_deep",
                    direction="A",
                    cycle_number=cycle,
                    measurements=asc_all[: deep_idx[-1] + 1],
                    sub_surface_pres=sub_surf,
                    pres_cutoff=pres_cutoff,
                )
                profiles.append(p)
            if shallow_idx:
                p = ArvorProfile(
                    kind="ascent_shallow",
                    direction="A",
                    cycle_number=cycle,
                    measurements=asc_all[shallow_idx[0] :],
                    sub_surface_pres=sub_surf,
                    pres_cutoff=pres_cutoff,
                )
                profiles.append(p)
            if t2 is not None:
                exp_asc = t2.fields[11] + t2.fields[12]
                for p in profiles:
                    if p.kind.startswith("ascent"):
                        p.expected_n_meas = exp_asc
                        p.profile_completed = exp_asc - len(asc_all)
        for p in profiles:
            d, src = _profile_date(timing, p.direction, res.mails, cycle)
            p.date = d
            p.date_source = src
            p.date_adj = None
            dated = [
                m.date_adj if m.date_adj is not None else m.date
                for m in p.measurements
                if m.date is not None
            ]
            if dated:
                p.min_meas_date = min(dated)
                p.max_meas_date = max(dated)
        cyc.profiles = profiles
        res.cycles.append(cyc)

    jamstec_qc(res.gps_records)
    _assign_locations(res.cycles, res.gps_records, res.mails)
    return res


def reconstruct_science_from_directory(
    directory: str | Path, launch_date: datetime | None = None
) -> tuple[list[ArvorIridiumMessage], ArvorScienceResult]:
    d = Path(directory)
    messages = [read_arvor_i_eml(p) for p in sorted(d.glob("*.eml"))]
    return messages, reconstruct_science(messages, launch_date=launch_date)


__all__ = [
    "ArvorCycle",
    "ArvorMeasurement",
    "ArvorProfile",
    "ArvorScienceResult",
    "ClockOffsetEvent",
    "CycleTimeData",
    "FloatMissionConfig",
    "GpsRecord",
    "MailInfo",
    "ProfileLocation",
    "build_cycle_timing",
    "build_drift_measurements",
    "build_profile_measurements",
    "clock_offset_for_cycle",
    "collect_clock_offset_events",
    "datetime_from_days",
    "days_from_1950",
    "jamstec_qc",
    "reconstruct_science",
    "reconstruct_science_from_directory",
]
