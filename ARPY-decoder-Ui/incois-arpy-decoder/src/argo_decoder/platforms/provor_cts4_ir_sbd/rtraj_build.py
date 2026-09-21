"""Adjudicated CTS4 Rtraj row builder — Phase-4 (evidence: PROVOR_CTS4_RTRAJ_
ADJUDICATION_2026-09-10.md; GDAC 2902086 Rtraj/tech + NKE 5.8 §7.2.4.6/7/9).

MEASUREMENT_CODE set emitted per cycle, with the exact semantics verified on
12170 cycles 98-114 against GDAC 2902086 (zero residual unless noted):

  89  buoyancy-reduction start (float 253 field; GDAC "cycle start"), st 2
  100 descent start = Parking Descent Start, st 2
  150 first stabilisation, st 2 (exact vs GDAC)
  189 buoyancy actions during descent-to-park (252 phase-5 samples anchored
      at Parking Descent Start; reltime = min/phase-start, NKE §7.2.4.7), st 2
  198 max pressure during descent to park (253; no date, st ' ')
  250 park descent end, st 2 (exact)
  297/298 min/max drift pressure at park (253; no date)
  300 profile descent start, st 2 (exact)
  301 representative park measurement (phase-6 telemetry; PRES + BGC via the
      production equations; no date; representative rule = per-stream median,
      documented choice — GDAC's internal rule unknown)
  389 buoyancy actions during descent-to-profile (252 phase-7), st 2
  398 max pressure during descent to profile (253; no date)
  450 profile descent end, st 2 (exact)
  497/498 min/max drift pressure at profile depth (253; no date)
  500 ascent start, st 2 (exact)
  503 ascending-profile deepest level (252 phase-9 max-pressure sample), st 2
  589 buoyancy actions during ascent (252 phase-9), st 2
  599 last pumped ascent CTD sample (PRES/TEMP/PSAL from the 253 pump block; no date)
  600 surfacing = ascent end - 10 min (NKE-documented wait; GDAC +0.1 min)
  700 first message (FloatTime, st 3 = telemetry)
  702 first location time (st 4; no coordinates, per GDAC)
  703 one row per valid GPS fix (FloatTime + lat/lon, st 4, PQc 1)
  704 last location time (st 4)
  800 transmission end — unknown, fill + st 9 (GDAC identical)

  290 park/drift sensor series — 3 rows per park sample (optode DOXY at +0 s,
      fluorometer CHLA/BBP700 at +1 s, CTD TEMP/PSAL at +9 s), triplets 12 h
      apart from the park descent end. Structure verified on 2902093 cycles
      45-53; row count = 3 x decoded park CTD count on 9/9.

  590 ascending-profile series — one row per ASCENT PHASE (phase-9) PACKET,
      not per level. Each row takes that packet's own type-0 header timestamp
      as JULD and that packet's own first record pressure as PRES. Row order
      per packet slot is CTD, DOXY, FL (MC590_ROW_ORDER). Structure verified
      against 2902093 cycles 45-53: 261/261 rows matched, JULD exact to
      0.000000 s, PRES exact to 0.000 dbar, no extra rows. Per cycle on this
      family: 7 CTD, 7 FLBB, 14-15 optode packets.

  289 buoyancy actions during drift/park — built from the concatenated
      eV+pump action table partitioned by [descentToParkEnd,
      descentToProfStart), per Coriolis process_trajectory_data
      g_MC_SpyAtPark. Window rule verified 12/12 on 2902093. Emits nothing on
      the supplied real-time corpus because a phase-6 census of all 10 groups
      finds zero phase-6 park samples (252-packet phases are {0,5,7,8,9,10}
      only), so no rows are fabricated. The mechanism is exercised by the
      generic fixture test instead.

Deferred (documented, not fabricated): MC 190/203.

FLAG_RTCStatus_LOGICAL is the INVERSE of telemetry byte 25. Byte 25 is the RTC
error flag; Coriolis documents the published Argo field as "real time clock
status - 1= OK, 0=not OK" (_tech_param_name_301.csv, decoder id 109 of message
253), and the sibling PROVOR IR-SBD decoder inverts it the same way. Byte 25 is
0 (no error) on 269/269 packets across all 10 groups, so the published value is
'1' (clock OK) -- matching INCOIS on every cycle. An earlier
NOT-REPRODUCIBLE-FROM-TELEMETRY classification of this row was wrong and is
withdrawn.

Launch row: MC 0 at cycle -1 (GDAC 2902086 structure), JULD from externally
supplied launch metadata, status 4.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field

from argo_decoder.platforms.provor_cts4_ir_sbd.mission_clock import (
    MissionClock,
    floattime_juld,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.tech import (
    PressurePacket,
    VectorTech,
)

JULD_FILL = 999999.0
POS_FILL = 99999.0

#: MC codes with per-phase 252 anchors (phase -> MC).
#:
#: Phase 6 is the park/drift window: Coriolis ``g_MC_SpyAtPark`` builds MC 289
#: from the same concatenated valve/pump action table as 189/389/589,
#: partitioned by date window (``process_trajectory_data_222_223_225_231_232.m``
#: L718-830). Every action inside ``[park_descent_end, profile_descent_start)``
#: emits one PRES-only trajectory row. Phase 6 is therefore a first-class
#: member of the same mechanism, not a special case — it simply has no samples
#: in the supplied corpus (0 of 5240 samples across all 10 groups), so it
#: contributes nothing rather than fabricating rows.
PHASE_SERIES_MC = {5: 189, 6: 289, 7: 389, 9: 589}


@dataclass
class RtrajRow:
    """One N_MEASUREMENT row (all fills explicit; no hidden defaults)."""

    cycle_number: int
    measurement_code: int
    juld: float = JULD_FILL
    juld_status: str = "9"
    juld_qc: str = "9"
    latitude: float = POS_FILL
    longitude: float = POS_FILL
    position_qc: str = "9"
    position_accuracy: str = " "
    pres: float = POS_FILL
    params: dict[str, float] = field(default_factory=dict)


def _dated(cycle: int, mc: int, juld: float) -> RtrajRow:
    return RtrajRow(cycle, mc, juld=juld, juld_status="2", juld_qc="1")


def _undated_pres(cycle: int, mc: int, pres_dbar: float) -> RtrajRow:
    return RtrajRow(cycle, mc, juld_status=" ", juld_qc=" ", pres=float(pres_dbar))


@dataclass
class ParkSample:
    """One park-phase sensor sample, already reduced to trajectory content.

    Filled by the caller from the decoded CTD / optode / fluorometer park
    records and the production science chain. Each field is ``None`` when that
    sensor produced no park sample at this index, in which case the
    corresponding row is not emitted (no fabricated value).

    The ``*_juld`` fields carry that sensor's OWN sample time, read from the
    type-0 packet timestamp of the packet the record arrived in. A sensor with
    no park sample at this index also has no JULD, and no row is emitted for it.
    """

    ctd_pres: float | None = None
    temp: float | None = None
    psal: float | None = None
    o2_pres: float | None = None
    doxy: float | None = None
    fl_pres: float | None = None
    chla: float | None = None
    bbp700: float | None = None
    ctd_juld: float | None = None
    o2_juld: float | None = None
    fl_juld: float | None = None
    # Raw sensor channels, carried for the MC 301 representative park mean.
    # MC 290 does not publish them, but Coriolis averages them into RPP, so
    # they must survive to that reduction rather than being recomputed.
    c1_phase: float | None = None
    c2_phase: float | None = None
    temp_doxy: float | None = None
    fluorescence_chla: float | None = None
    beta_700: float | None = None


@dataclass
class AscentSample:
    """One ascent-phase packet, reduced to trajectory content (MC 590).

    Each field is ``None`` when that sensor transmitted no ascent packet at
    this index, in which case no row is emitted for it. The JULD is that
    packet's OWN type-0 header timestamp and the pressure that packet's OWN
    first record pressure — never interpolated between packets.
    """

    ctd_juld: float | None = None
    ctd_pres: float | None = None
    temp: float | None = None
    psal: float | None = None
    o2_juld: float | None = None
    o2_pres: float | None = None
    doxy: float | None = None
    fl_juld: float | None = None
    fl_pres: float | None = None
    chla: float | None = None
    bbp700: float | None = None


#: MC 590 row order within one ascent sample. Presentation order only; every
#: row carries its own packet timestamp, so no time offset is applied.
MC590_ROW_ORDER: tuple[str, ...] = ("CTD", "DOXY", "FL")


def build_ascent_sample_rows(
    cycle: int,
    ascent_samples: list[AscentSample],
) -> list[RtrajRow]:
    """MC 590 ascent-profile series, one row per transmitted packet per sensor.

    Coriolis builds MC 590 (``g_MC_AscProf``) from ``profile.dates``, an
    unpublished intermediate. Those dates are NOT missing from the telemetry —
    they are exactly the type-0 header timestamp of each ascent-phase packet.
    Each sensor transmits its ascent profile as a sequence of packets (7 CTD,
    7 FLBB, 14-15 optode per cycle on this family), and MC 590 carries one row
    per packet, not one per decimated level.

    Verified against INCOIS 2902093 cycles 45-53, keyed by (cycle, MC):

    * JULD exact (residual 0.000000 s) on **261/261** rows — 9 cycles x
      (7 CTD + 15 O2 + 7 FL);
    * PRES exact (0.000 dbar) on the CTD rows, 9/9 cycles;
    * ``JULD_STATUS='2'``, no coordinates.

    The row count therefore follows the transmitted packet count, which varies
    by float and cycle (the optode sends 14 or 15). No stride, no decimation
    and no interpolation is involved.
    """
    rows: list[RtrajRow] = []
    for a in ascent_samples:
        for kind in MC590_ROW_ORDER:
            if kind == "CTD" and a.temp is not None and a.ctd_juld is not None:
                row = RtrajRow(cycle, 590, juld=a.ctd_juld, juld_status="2",
                               juld_qc="1",
                               pres=(a.ctd_pres if a.ctd_pres is not None
                                     else POS_FILL))
                row.params["TEMP"] = a.temp
                if a.psal is not None:
                    row.params["PSAL"] = a.psal
            elif (kind == "DOXY" and a.doxy is not None
                  and a.o2_juld is not None):
                row = RtrajRow(cycle, 590, juld=a.o2_juld, juld_status="2",
                               juld_qc="1",
                               pres=(a.o2_pres if a.o2_pres is not None
                                     else POS_FILL))
                row.params["DOXY"] = a.doxy
            elif kind == "FL" and a.chla is not None and a.fl_juld is not None:
                row = RtrajRow(cycle, 590, juld=a.fl_juld, juld_status="2",
                               juld_qc="1",
                               pres=(a.fl_pres if a.fl_pres is not None
                                     else POS_FILL))
                row.params["CHLA"] = a.chla
                if a.bbp700 is not None:
                    row.params["BBP700"] = a.bbp700
            else:
                continue
            rows.append(row)
    return rows


#: MC 290 row order within one park sample. Row order is a presentation
#: convention only — every row now carries its sensor's own packet timestamp,
#: so no per-kind time offset is applied.
MC290_ROW_ORDER: tuple[str, ...] = ("O2", "FL", "CTD")


def build_park_sample_rows(
    cycle: int,
    park_samples: list[ParkSample],
) -> list[RtrajRow]:
    """MC 290 drift/park sensor series, generic and telemetry-derived.

    Every row's JULD is that sensor's own sample time, decoded from the type-0
    packet header of the packet the record arrived in (NKE §7.2.4.1 "1st-sample
    date", bytes6-9 = seconds since 2000-01-01 UTC; see
    :func:`argo_decoder.platforms.provor_cts4_ir_sbd.packets.meas_record_julds`).
    No timestamp is synthesized from a fixed interval or an event anchor.

    Structure verified against INCOIS 2902093 cycles 45-53 (keyed by
    ``(cycle, MC)``, never array position):

    * row count is ``3 x n_park_samples`` — 54 for 18 park samples, 57 for 19,
      matching the decoded park-phase CTD count on 9/9 cycles;
    * reconstructed JULD matches the published JULD EXACTLY (residual
      0.000000 s) on 495/495 rows — 9 cycles x 3 sensors;
    * within one park sample the optode row carries DOXY only, the fluorometer
      row carries CHLA and BBP700 only, the CTD row carries TEMP and PSAL only;
    * every row carries that sensor's OWN park pressure (verified exact 18/18
      per stream on cycle 45), ``JULD_STATUS='2'``, and no coordinates;
    * a sensor that produced no park sample contributes no row.

    The optode transmits its park series in two packets per cycle (the second
    starting 5 days later), so its own timestamps — not one anchor — are what
    reproduce the published series; a single anchor drifts 1 s on 6 of 9
    cycles.
    """
    rows: list[RtrajRow] = []
    for ps in park_samples:
        for kind in MC290_ROW_ORDER:
            if kind == "O2" and ps.doxy is not None and ps.o2_juld is not None:
                row = RtrajRow(cycle, 290, juld=ps.o2_juld, juld_status="2",
                               juld_qc="1",
                               pres=(ps.o2_pres if ps.o2_pres is not None
                                     else POS_FILL))
                row.params["DOXY"] = ps.doxy
            elif (kind == "FL" and ps.chla is not None
                  and ps.fl_juld is not None):
                row = RtrajRow(cycle, 290, juld=ps.fl_juld, juld_status="2",
                               juld_qc="1",
                               pres=(ps.fl_pres if ps.fl_pres is not None
                                     else POS_FILL))
                row.params["CHLA"] = ps.chla
                if ps.bbp700 is not None:
                    row.params["BBP700"] = ps.bbp700
            elif (kind == "CTD" and ps.temp is not None
                  and ps.ctd_juld is not None):
                row = RtrajRow(cycle, 290, juld=ps.ctd_juld, juld_status="2",
                               juld_qc="1",
                               pres=(ps.ctd_pres if ps.ctd_pres is not None
                                     else POS_FILL))
                row.params["TEMP"] = ps.temp
                if ps.psal is not None:
                    row.params["PSAL"] = ps.psal
            else:
                continue
            rows.append(row)
    return rows


def launch_row(
    launch_juld: float, launch_lat: float, launch_lon: float
) -> RtrajRow:
    """MC 0 at cycle 0 (GDAC 2902086: status 4, position from metadata).

    The launch measurement belongs to cycle 0, the launch cycle, and the N_CYCLE
    launch row carries cycle number 0 as well. A negative cycle number is only
    tolerated by OneArgo FileChecker at measurement index 0 *and* only when the
    file passes its two-way CYCLE_NUMBER <-> CYCLE_NUMBER_INDEX cross-check;
    otherwise the checker emits "CYCLE_NUMBER errors exist. Remaining checks
    skipped" and validates nothing else in the trajectory.
    """
    return RtrajRow(
        cycle_number=0,
        measurement_code=0,
        juld=float(launch_juld),
        juld_status="4",
        juld_qc="1",
        latitude=float(launch_lat),
        longitude=float(launch_lon),
        position_qc="1",
        position_accuracy=" ",
    )


def _phase_anchor(mc: int, vt: VectorTech, clock: MissionClock) -> float:
    if mc == 189:
        return clock.park_descent_start(vt)
    if mc == 289:
        # Park/drift window opens at the park descent end (MC 250).
        return clock.park_descent_end(vt)
    if mc == 389:
        return clock.profile_descent_start(vt)
    return clock.ascent_start(vt)


def build_cycle_rows(
    cycle: int,
    vt: VectorTech,
    pressure_packets: list[PressurePacket],
    clock: MissionClock,
    park_repr_params: dict[str, float] | None = None,
    park_repr_pres: float | None = None,
    last_ascent_ctd_pres: float | None = None,
    park_samples: list[ParkSample] | None = None,
    ascent_samples: list[AscentSample] | None = None,
    prof_deepest_pres_dbar: float | None = None,
    last_ascent_ctd_sample: tuple[float, float] | None = None,
) -> list[RtrajRow]:
    """All adjudicated rows for one cycle, sorted by (MC, JULD)."""
    rows: list[RtrajRow] = []

    # -- dated single events ------------------------------------------------
    rows.append(_dated(cycle, 89, clock.buoyancy_reduction_start(vt)))
    rows.append(_dated(cycle, 100, clock.park_descent_start(vt)))
    rows.append(_dated(cycle, 150, clock.first_stabilization(vt)))
    rows.append(_dated(cycle, 250, clock.park_descent_end(vt)))
    rows.append(_dated(cycle, 300, clock.profile_descent_start(vt)))
    rows.append(_dated(cycle, 450, clock.profile_descent_end(vt)))
    rows.append(_dated(cycle, 500, clock.ascent_start(vt)))
    rows.append(_dated(cycle, 600, clock.surfacing(vt)))

    # -- undated pressure extremes (253 fields; bar -> dbar) ----------------
    rows.append(_undated_pres(cycle, 198, vt.max_pres_desc_park_bar * 10.0))
    rows.append(_undated_pres(cycle, 297, vt.min_pres_drift_park_bar * 10.0))
    rows.append(_undated_pres(cycle, 298, vt.max_pres_drift_park_bar * 10.0))
    rows.append(_undated_pres(cycle, 398, vt.max_pres_desc_prof_bar * 10.0))
    rows.append(_undated_pres(cycle, 497, vt.min_pres_drift_prof_bar * 10.0))
    rows.append(_undated_pres(cycle, 498, vt.max_pres_drift_prof_bar * 10.0))

    # -- MC 301 representative park measurement ------------------------------
    if park_repr_pres is not None:
        row = RtrajRow(cycle, 301, juld_status=" ", juld_qc=" ",
                       pres=float(park_repr_pres))
        row.params.update(park_repr_params or {})
        rows.append(row)

    # -- 252 hydraulic series (189/389/589) + 503 deepest ascent level -------
    anchors = {mc: _phase_anchor(mc, vt, clock) for mc in PHASE_SERIES_MC.values()}
    deepest = None  # (reltime_min, pressure_dbar)
    phase9: list = []
    for pkt in pressure_packets:
        for s in pkt.samples:
            mc = PHASE_SERIES_MC.get(s.phase)
            if mc is None:
                continue
            juld = clock.sample_juld(anchors[mc], s.reltime_min)
            rows.append(RtrajRow(cycle, mc, juld=juld, juld_status="2",
                                 juld_qc="1", pres=s.pressure_bar * 10.0))
            if s.phase == 9:
                phase9.append(s)
                if deepest is None or s.pressure_bar > deepest[1]:
                    deepest = (s.reltime_min, s.pressure_bar)
    # MC 503 is the DEEPEST BIN OF THE AVERAGED ASCENDING PROFILE, not the
    # deepest raw 252 sample. Coriolis process_trajectory_data takes
    # `idDeepest = idNotDef(1)` of the direction=='A' profile's own PRES
    # column, i.e. the first defined level of the binned profile -- which for
    # the shallow-first R prof1 grid is its deepest bin. On 2902093 cycles
    # 45-53 that bin is 1977.0/2007.3/... dbar (fractional), whereas the
    # deepest raw phase-9 sample is the round 1980/2010 dbar. Using the raw
    # maximum left MC 503 PRES wrong on 9/9 cycles and its JULD off by
    # 9-57 s. `prof_deepest_pres_dbar` is supplied by the caller from the same
    # binned grid the R writer publishes, so the two products agree by
    # construction. The JULD is interpolated to that bin inside the bracketing
    # phase-9 samples.
    if prof_deepest_pres_dbar is not None:
        target = float(prof_deepest_pres_dbar)
        # MC 503's date is the timestamp of the LAST MC 590 ascent row sitting
        # at that pressure, whichever sensor produced it (CTD, optode or
        # fluorometer) -- it is NOT an interpolation of the 252 phase-9
        # hydraulic series. Verified against INCOIS 2902093 cycles 45-53: the
        # rule matches GDAC exactly on 9/9 (0.000 s), while interpolating the
        # phase-9 samples left it 10-96 s off. On the 6 cycles where several
        # sensors transmit at the same deepest pressure the CTD row is the
        # latest; on the other 3 the optode row is the only one there.
        hit = None
        for a in (ascent_samples or []):
            for pres, juld in ((a.ctd_pres, a.ctd_juld),
                               (a.o2_pres, a.o2_juld),
                               (a.fl_pres, a.fl_juld)):
                if pres is None or juld is None:
                    continue
                if (abs(float(pres) - target) < 0.05
                        and (hit is None or float(juld) > hit)):
                    hit = float(juld)
        if hit is not None:
            rows.append(RtrajRow(
                cycle, 503, juld=hit,
                juld_status="2", juld_qc="1", pres=target,
            ))
        elif phase9:
            # No ascent row at that pressure: fall back to interpolating the
            # bracketing phase-9 hydraulic samples rather than dropping the row.
            ordered = sorted(phase9, key=lambda s: s.reltime_min)
            reltime = float(ordered[0].reltime_min)
            for lo, hi in itertools.pairwise(ordered):
                p_lo, p_hi = lo.pressure_bar * 10.0, hi.pressure_bar * 10.0
                if min(p_lo, p_hi) - 1e-9 <= target <= max(p_lo, p_hi) + 1e-9:
                    span = p_lo - p_hi
                    frac = 0.0 if abs(span) < 1e-12 else (p_lo - target) / span
                    reltime = float(lo.reltime_min) + frac * float(
                        hi.reltime_min - lo.reltime_min)
                    break
            else:
                reltime = float(
                    max(ordered, key=lambda s: s.pressure_bar).reltime_min)
            rows.append(RtrajRow(
                cycle, 503,
                juld=clock.sample_juld(anchors[589], reltime),
                juld_status="2", juld_qc="1", pres=target,
            ))
    elif deepest is not None:
        # No binned profile available (e.g. BGC-only cycle): fall back to the
        # deepest raw phase-9 sample rather than fabricating a bin.
        rows.append(RtrajRow(
            cycle, 503,
            juld=clock.sample_juld(anchors[589], deepest[0]),
            juld_status="2", juld_qc="1", pres=deepest[1] * 10.0,
        ))
    # Closing surface pump action of the ascent series: GDAC appends one
    # MC 589 row at (ascent_end, 0 dbar) beyond the 252 phase-9 window —
    # reproduced here from the first-party 253 ascent_end field (verified
    # 16/16 cycles on 2902086).
    rows.append(RtrajRow(cycle, 589, juld=clock.ascent_end(vt),
                         juld_status="2", juld_qc="1", pres=0.0))

    # -- MC 290 park/drift sensor series (telemetry-derived; see above) ------
    if park_samples:
        rows.extend(build_park_sample_rows(cycle, park_samples))

    # -- MC 590 ascent profile series (one row per transmitted packet) -------
    if ascent_samples:
        rows.extend(build_ascent_sample_rows(cycle, ascent_samples))

    # -- MC 599 last pumped ascent CTD sample (no date) ----------------------
    # Coriolis process_trajectory_data_222_223_225_231_232.m:974-980 reads the
    # last pumped CTD measurement straight out of the 253 vector's own tech
    # block: pres = tabTech2(15), temp = tabTech2(16), psal = tabTech2(17)/1000,
    # and emits the row only when not all three are zero. The pressure is the
    # `p_sub` pump-cutoff field, which is also tech row 17
    # (PRES_LastAscentPumpedRawSample_dbar) -- verified 5.1431 dbar on 2902093
    # cycle 46, matching GDAC's MC 599 PRES exactly. TEMP and PSAL are the CTD
    # sample taken at that pump pressure; the raw ascent CTD record nearest to
    # it reproduces GDAC to 1e-4 (2902093 cycles 45-49). The previously emitted
    # row carried pressure only, and the binned-profile pressure (~0.1-0.4 dbar)
    # rather than `p_sub`, so it was wrong on 9/9 cycles.
    if last_ascent_ctd_pres is not None:
        row = RtrajRow(cycle, 599, juld_status=" ", juld_qc=" ",
                       pres=float(last_ascent_ctd_pres))
        if last_ascent_ctd_sample is not None:
            t_c, psal = last_ascent_ctd_sample
            row.params["TEMP"] = float(t_c)
            row.params["PSAL"] = float(psal)
        rows.append(row)

    # -- transmission/position events (absolute FloatTime) -------------------
    # NOTE: caller passes the FULL per-cycle VectorTech list via `vt_all`;
    # this builder receives them through `pressure_packets`-independent args.
    return rows


def build_transmission_rows(
    cycle: int,
    vt_all: list[VectorTech],
    next_vt_all: list[VectorTech] | None = None,
) -> list[RtrajRow]:
    """700/702/703*/704/800 from the cycle's own transmission session.

    A cycle's transmission window is bounded by its own surfacing and the
    start of the NEXT cycle's descent. In the SBD telemetry that window
    contains two 253 packets: this cycle's phase-12 (session-2, end-of-cycle)
    packet and the following cycle's phase-1 (session-1, surfacing) packet.
    Both carry a GPS fix and both belong to this cycle's transmission, which
    is why INCOIS publishes 8 MC 703 rows per cycle spanning roughly
    surfacing+950 s to surfacing+2030 s (verified on 2902093 cycles 45-53:
    both our packets' fixes fall inside GDAC's MC 703 window on 8/8).

    Passing only this cycle's buffer made MC 700/702 report the PREVIOUS
    cycle's session-1 packet time (~10 days early) and MC 704 miss the last
    fix. `next_vt_all` supplies the following cycle's session-1 packet.
    """
    rows: list[RtrajRow] = []
    # This cycle's own session-2 (phase-12) packet carries the completed-cycle
    # counters; its FloatTime is the anchor for the transmission window. Any
    # phase-1 packet in this cycle's own buffer predates that anchor: it is the
    # PREVIOUS cycle's surfacing packet, still in the buffer, and must not be
    # counted as this cycle's first message.
    _own12 = next((v for v in vt_all if v.phase == 12), None)
    _anchor = floattime_juld(_own12.time) if _own12 is not None else None
    session: list[VectorTech] = [
        v for v in vt_all
        if _anchor is None or floattime_juld(v.time) >= _anchor
    ]
    if next_vt_all:
        session.extend(v for v in next_vt_all if v.phase == 1)
    fts = sorted(floattime_juld(v.time) for v in session)
    if fts:
        rows.append(RtrajRow(cycle, 700, juld=fts[0], juld_status="3",
                             juld_qc="1"))
    _fix_list: list[tuple[float, tuple[float, float]]] = []
    for _v in session:
        if _v.gps_valid != 1:
            continue
        _pos = _v.gps_position()
        if _pos is not None:
            _fix_list.append((floattime_juld(_v.time), _pos))
    fixes = sorted(_fix_list)
    if fixes:
        rows.append(RtrajRow(cycle, 702, juld=fixes[0][0], juld_status="4",
                             juld_qc="1"))
        for juld, (lat, lon) in fixes:
            # POSITION_ACCURACY follows Argo reference table 5. Every fix this
            # decoder can emit comes from the 253 packet's own `gps_valid`/
            # `gps_position` fields, i.e. a real GPS fix, so the truthful code
            # is "G". GDAC's INCOIS files additionally carry "I" (Argos
            # interpolated) rows for the same cycles; those fixes are not
            # present in the SBD telemetry we decode, so they are not
            # fabricated here. Writing "1" (a table-2 QC code) was wrong for a
            # table-5 field.
            rows.append(RtrajRow(cycle, 703, juld=juld, juld_status="4",
                                 juld_qc="1", latitude=lat, longitude=lon,
                                 position_qc="1", position_accuracy="G"))
        rows.append(RtrajRow(cycle, 704, juld=fixes[-1][0], juld_status="4",
                             juld_qc="1"))
    else:
        rows.append(RtrajRow(cycle, 702))
        rows.append(RtrajRow(cycle, 704))
    # MC 800: transmission end unknown to the float — fill, status 9 (GDAC same)
    rows.append(RtrajRow(cycle, 800))
    return rows


def build_rows(
    vectors_by_cycle: dict[int, list[VectorTech]],
    pressure_by_cycle: dict[int, list[PressurePacket]],
    clock: MissionClock,
    launch_juld: float,
    launch_lat: float,
    launch_lon: float,
    park_by_cycle: dict[int, tuple[float, dict[str, float]]] | None = None,
    last_ctd_pres_by_cycle: dict[int, float] | None = None,
    park_samples_by_cycle: dict[int, list[ParkSample]] | None = None,
    ascent_samples_by_cycle: dict[int, list[AscentSample]] | None = None,
    prof_deepest_pres_by_cycle: dict[int, float] | None = None,
    last_ascent_ctd_sample_by_cycle: dict[int, tuple[float, float]] | None = None,
) -> list[RtrajRow]:
    """Full-float row list: launch + per-cycle rows, sorted for stability."""
    rows = [launch_row(launch_juld, launch_lat, launch_lon)]
    park_by_cycle = park_by_cycle or {}
    last_ctd_pres_by_cycle = last_ctd_pres_by_cycle or {}
    park_samples_by_cycle = park_samples_by_cycle or {}
    ascent_samples_by_cycle = ascent_samples_by_cycle or {}
    prof_deepest_pres_by_cycle = prof_deepest_pres_by_cycle or {}
    last_ascent_ctd_sample_by_cycle = last_ascent_ctd_sample_by_cycle or {}
    _ordered_cycles = sorted(vectors_by_cycle)
    for _ci, cycle in enumerate(_ordered_cycles):
        vt_all = vectors_by_cycle[cycle]
        # The following cycle's session-1 packet completes this cycle's
        # transmission window (see build_transmission_rows).
        _next_vt_all = (vectors_by_cycle[_ordered_cycles[_ci + 1]]
                        if _ci + 1 < len(_ordered_cycles) else None)
        # Representative VT for event fields: the phase-12 (session-2) packet
        # carries the completed-cycle counters; fall back to any packet.
        vt = next((v for v in vt_all if v.phase == 12), vt_all[0])
        park = park_by_cycle.get(cycle)
        rows.extend(build_cycle_rows(
            cycle, vt, pressure_by_cycle.get(cycle, []), clock,
            park_repr_params=park[1] if park else None,
            park_repr_pres=park[0] if park else None,
            last_ascent_ctd_pres=last_ctd_pres_by_cycle.get(cycle),
            park_samples=park_samples_by_cycle.get(cycle),
            ascent_samples=ascent_samples_by_cycle.get(cycle),
            prof_deepest_pres_dbar=prof_deepest_pres_by_cycle.get(cycle),
            last_ascent_ctd_sample=last_ascent_ctd_sample_by_cycle.get(cycle),
        ))
        rows.extend(build_transmission_rows(cycle, vt_all, _next_vt_all))
    rows.sort(key=lambda r: (r.cycle_number, r.measurement_code, r.juld))
    return rows


@dataclass
class Cts4RtrajCycleSummary:
    """One N_CYCLE summary row (field names mirror the writer columns)."""

    cycle_number: int
    cycle_number_index: int
    data_mode: str = "R"
    juld_descent_start: float = JULD_FILL
    juld_descent_start_status: str = " "
    juld_first_stabilization: float = JULD_FILL
    juld_first_stabilization_status: str = " "
    juld_descent_end: float = JULD_FILL
    juld_descent_end_status: str = " "
    juld_park_start: float = JULD_FILL
    juld_park_start_status: str = " "
    juld_park_end: float = JULD_FILL
    juld_park_end_status: str = " "
    juld_deep_descent_end: float = JULD_FILL
    juld_deep_descent_end_status: str = " "
    juld_deep_park_start: float = JULD_FILL
    juld_deep_park_start_status: str = " "
    juld_ascent_start: float = JULD_FILL
    juld_ascent_start_status: str = " "
    juld_deep_ascent_start: float = JULD_FILL
    juld_deep_ascent_start_status: str = " "
    juld_ascent_end: float = JULD_FILL
    juld_ascent_end_status: str = " "
    juld_transmission_start: float = JULD_FILL
    juld_transmission_start_status: str = " "
    juld_first_message: float = JULD_FILL
    juld_first_message_status: str = " "
    juld_first_location: float = JULD_FILL
    juld_first_location_status: str = " "
    juld_last_location: float = JULD_FILL
    juld_last_location_status: str = " "
    juld_last_message: float = JULD_FILL
    juld_last_message_status: str = " "
    juld_transmission_end: float = JULD_FILL
    juld_transmission_end_status: str = "9"
    grounded: str = " "
    representative_park_pressure: float = POS_FILL
    representative_park_pressure_status: str = " "
    config_mission_number: int = 99999


#: CONFIG_MISSION_NUMBER (N_CYCLE) is published as FillValue, and this is the
#: documented reason. Investigated at the freeze gate; the negative result is
#: recorded here so it is not re-litigated or "fixed" by defaulting to 1.
#:
#: Argo UM §2.4.6.1 (p57) defines CONFIG_MISSION_NUMBER as the "unique number of
#: the mission to which this profile belongs", counting successive float
#: configurations. The authoritative per-mission table IS available (meta.nc
#: CONFIG_PARAMETER_NAME / _VALUE / CONFIG_MISSION_NUMBER, reproduced exactly);
#: what is missing is which cycles belong to which mission.
#:
#: A spacing-based derivation was built and tested. Each mission states its own
#: CONFIG_CycleTime_hours and the 253 packet's cycle_start_day counter is
#: mission-start relative, so observed inter-cycle spacing does identify *some*
#: boundaries. It is not sufficient in general:
#:
#:   * 2902093 -- table 24/120/240 h, GDAC boundaries at cycles 9 and 11. Our
#:     corpus (cycles 44-53) shows uniform 10-day spacing, i.e. mission 3
#:     throughout, and the spacing rule reproduced all 11 cycles exactly.
#:   * 2902131 -- table 24/240 h, GDAC boundary at cycle 11. The rule got 13/15,
#:     mis-assigning the two cycles either side of the boundary.
#:   * 2902130 -- table 24/24/240 h. Missions 1 and 2 have IDENTICAL cycle
#:     times, so no spacing change marks the boundary; the only differing
#:     parameter is CONFIG_FloatReferenceDay_FloatDay (0 vs 1), a
#:     launch-configuration reference-day offset that is not observable in the
#:     cycle spacing. The rule got 3/16 and assigned mission 1 to cycles the
#:     GDAC places in mission 2.
#:
#: Publishing a derived value would therefore assert a specific mission for
#: cycles where the assignment is wrong or unknowable. Publishing 1 (the
#: previous mono_profile.py default) asserts the FIRST configuration for every
#: cycle, which is wrong for any float that has changed configuration -- all
#: three floats above have. FillValue is the honest representation, and the
#: OneArgo FileChecker accepts it (274/274 FILE-ACCEPTED, 0 FORMAT-ERRORS).
#:
#: This is a real-time telemetry limitation, not a decoder defect: the mission
#: index is a deployment-log fact, like START_DATE, and neither is carried in
#: the SBD telemetry.


def build_cycle_summaries(
    vectors_by_cycle: dict[int, list[VectorTech]],
    clock: MissionClock,
    park_pres_by_cycle: dict[int, float] | None = None,
) -> list[Cts4RtrajCycleSummary]:
    """N_CYCLE rows: launch row (cycle -1) + one row per cycle.

    ``cycle_number_index`` carries the cycle *number* of the row, not a
    positional ordinal — that is what the Argo trajectory spec means by
    "Cycle number that corresponds to the current index" and what the ARVOR
    builder does (``rec.cycle_number_index = cycle``). OneArgo FileChecker
    cross-checks the two arrays in both directions and, on mismatch, emits
    "CYCLE_NUMBER errors exist. Remaining checks skipped", which suppresses
    every later trajectory check for the file.

    The launch row uses cycle number 0: the launch *is* cycle 0 of the float
    ("0 : launch cycle, 1 : first complete cycle"). Cycle -1 is not a defined
    cycle number, and a -1 here can never appear in CYCLE_NUMBER.
    """
    park_pres_by_cycle = park_pres_by_cycle or {}
    # Launch row. Cycle number 0 is the launch cycle ("0 : launch cycle"), and
    # it must equal CYCLE_NUMBER_INDEX[0] and the CYCLE_NUMBER carried by the
    # MC 0 launch measurement, or the checker's two-way cycle cross-check
    # fails and every remaining trajectory check is skipped for the file.
    out = [Cts4RtrajCycleSummary(cycle_number=0, cycle_number_index=0)]
    _cycles = sorted(vectors_by_cycle)
    for _ci, cycle in enumerate(_cycles):
        vt_all = vectors_by_cycle[cycle]
        vt = next((v for v in vt_all if v.phase == 12), vt_all[0])
        # JULD_FIRST/LAST_LOCATION and JULD_FIRST/LAST_MESSAGE must describe the
        # SAME transmission window as the MC 700/702/703/704 rows built by
        # _session_rows: this cycle's own phase-12 packet onward, plus the next
        # cycle's phase-1 surfacing packet. A phase-1 packet still sitting in
        # this cycle's buffer is the PREVIOUS cycle's surfacing packet, whose
        # fix is already published under that cycle's MC 703.
        #
        # Deriving `fts`/`fixes` from the unanchored buffer instead made
        # JULD_FIRST_LOCATION count a fix from the previous session on cycles
        # whose own session carried no valid GPS at all (2902092 cycles 47 and
        # 52), publishing a location time with no MC 703 row to match it.
        # OneArgo FileChecker reports exactly that:
        # "JULD_FIRST_LOCATION (MC 703): Not FillValue where there is no
        # associated JULD at 2 cycles". INCOIS never does this on a real cycle
        # -- its single orphan is the cycle-0 launch row, which carries MC 0
        # rather than a GPS measurement (2902093 Rtraj, 1 of 236 cycles).
        _own12 = next((v for v in vt_all if v.phase == 12), None)
        _anchor = floattime_juld(_own12.time) if _own12 is not None else None
        _session = [
            v for v in vt_all
            if _anchor is None or floattime_juld(v.time) >= _anchor
        ]
        _nxt = vectors_by_cycle[_cycles[_ci + 1]] if _ci + 1 < len(_cycles) else None
        if _nxt:
            _session.extend(v for v in _nxt if v.phase == 1)
        fts = sorted(floattime_juld(v.time) for v in _session)
        fixes = sorted(floattime_juld(v.time) for v in _session
                       if v.gps_valid == 1 and v.gps_position() is not None)
        s = Cts4RtrajCycleSummary(
            cycle_number=cycle,
            cycle_number_index=cycle,
            juld_descent_start=clock.buoyancy_reduction_start(vt),
            juld_descent_start_status="2",
            juld_first_stabilization=clock.first_stabilization(vt),
            juld_first_stabilization_status="2",
            # JULD_DESCENT_END (MC 200), JULD_DEEP_DESCENT_END (MC 400) and
            # JULD_DEEP_ASCENT_START (MC 550) stay FILL unless this cycle
            # actually emits the matching measurement row. OneArgo FileChecker
            # reports "Not FillValue where there is no associated JULD" when an
            # N_CYCLE event time is populated but no MC row carries it; INCOIS
            # 2902093 emits no MC 200/400/550 and leaves all three FILL on all
            # 235 cycles. The remaining N_CYCLE times have matching rows.
            juld_descent_end=JULD_FILL,
            juld_descent_end_status=" ",
            juld_park_start=clock.park_descent_end(vt),
            juld_park_start_status="2",
            juld_park_end=clock.profile_descent_start(vt),
            juld_park_end_status="2",
            juld_deep_descent_end=JULD_FILL,
            juld_deep_descent_end_status=" ",
            juld_deep_park_start=clock.profile_descent_end(vt),
            juld_deep_park_start_status="2",
            juld_ascent_start=clock.ascent_start(vt),
            juld_ascent_start_status="2",
            juld_deep_ascent_start=JULD_FILL,
            juld_deep_ascent_start_status=" ",
            juld_ascent_end=clock.ascent_end(vt),
            juld_ascent_end_status="2",
            juld_first_message=fts[0] if fts else JULD_FILL,
            juld_first_message_status="3" if fts else "9",
            juld_last_message=fts[-1] if fts else JULD_FILL,
            juld_last_message_status="3" if fts else "9",
            # A cycle whose 253 packets carry no valid GPS fix has no location
            # time to publish. The paired _STATUS must then be Fill too, not
            # '9': the INCOIS GDAC never writes a status code for a Fill time
            # (verified on 2902093, where every Fill JULD_* has a blank
            # JULD_*_STATUS). Writing '9' here made FileChecker warn
            # "Not FillValue where there is no associated JULD_STATUS".
            juld_first_location=fixes[0] if fixes else JULD_FILL,
            juld_first_location_status="4" if fixes else " ",
            juld_last_location=fixes[-1] if fixes else JULD_FILL,
            juld_last_location_status="4" if fixes else " ",
            grounded=str(vt.grounding_detected),
            # CONFIG_MISSION_NUMBER stays FillValue (99999). See
            # mission_number_by_cycle for why the per-cycle assignment cannot
            # be pinned from telemetry in general.
        )
        if cycle in park_pres_by_cycle:
            s.representative_park_pressure = float(park_pres_by_cycle[cycle])
            s.representative_park_pressure_status = "1"
        out.append(s)
    return out
