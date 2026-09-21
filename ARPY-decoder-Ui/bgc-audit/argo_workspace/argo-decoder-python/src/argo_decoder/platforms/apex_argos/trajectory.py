"""Assemble ADMT trajectory records from APEX/ARGOS decoder output.

Turns what the ARGOS decoder already knows -- satellite location fixes
and per-message reception times -- into the ``N_MEASUREMENT`` /
``N_CYCLE`` records that :mod:`argo_decoder.nc.trajectory` writes.

Evidence for the mapping (see ``docs/phase_reports/phase6a_traj_plan.md``):
comparing ``parse_argos_fixes()`` output for raw cycle 327 of WMO 2902222
against the reference ``MC=703`` block for the same cycle shows every one
of our fixes present with bit-identical JULD/LATITUDE/LONGITUDE, and
``POSITION_ACCURACY`` equal to the CLS location class we already parse.
``JULD_LAST_MESSAGE`` likewise equals our last transmission time exactly.

Events whose time lives in the APEX engineering/technical message are
emitted as structural rows with fill values and ``JULD_STATUS='9'``
("not determined"), matching the references. No time is invented.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.trajectory import (
    CYCLE_MEASUREMENT_TEMPLATE,
    JULD_QC_BY_MEASUREMENT_CODE,
    JULD_STATUS_BY_MEASUREMENT_CODE,
    JULD_STATUS_DERIVED,
    JULD_STATUS_FLOAT_CLOCK,
    JULD_STATUS_TRANSMITTED,
    JULD_STATUS_UNKNOWN,
    TrajCycle,
    TrajectoryRecords,
    TrajMeasurement,
    TrajMeasurementCode,
)
from argo_decoder.platforms.apex_argos.engineering import ApexEngineeringData
from argo_decoder.platforms.apex_argos.frames import ArgosFix
from argo_decoder.platforms.apex_argos.mission import position_qc_for_location_class
from argo_decoder.platforms.apex_argos.profile import datetime_to_juld


@dataclass
class ArgosCycleTelemetry:
    """What the decoder observed for one output cycle."""

    cycle_number: int
    fixes: list[ArgosFix]
    message_times: list[datetime]
    #: Decoded engineering for this cycle, when the messages allowed it.
    engineering: ApexEngineeringData | None = None

    @property
    def first_message_juld(self) -> float | None:
        times = sorted(self.message_times)
        return datetime_to_juld(times[0]) if times else None

    @property
    def last_message_juld(self) -> float | None:
        times = sorted(self.message_times)
        return datetime_to_juld(times[-1]) if times else None

    @property
    def ordered_fixes(self) -> list[ArgosFix]:
        return sorted(self.fixes, key=lambda f: f.at)


#: The references flag the park samples ``'0'`` -- "no QC performed" --
#: rather than ``'1'``. Verified on all 23/339/337/334 cycles of WMO
#: 2901304, 2902222, 2902223 and 2902224. They are single engineering
#: samples that the real-time chain does not screen, unlike the profile
#: levels.
_PARK_SAMPLE_QC = "0"


#: Mission-schedule offsets from the cycle's descent start, in hours.
#:
#: Read off the three healthy reference floats (WMO 2902222, 2902223 and
#: 2902224), where every populated cycle carries exactly these gaps:
#:
#:     JULD_PARK_START       = DESCENT_START + 4.7081 h
#:     JULD_PARK_END         = DESCENT_START + DownTime + 2 h
#:     JULD_TRANSMISSION_END = DESCENT_START + CycleTime
#:     DESCENT_START(n+1)    = TRANSMISSION_END(n)
#:
#: with ``DownTime`` and ``CycleTime`` taken from the launch
#: configuration. The 4.7081 h park-start gap is a float-independent
#: constant of the APF9 descent profile; the other two are pure mission
#: programming.
_PARK_START_AFTER_DESCENT_HOURS = 4.708098
_PARK_END_AFTER_DOWNTIME_HOURS = 2.0

#: The cycle the launch anchor describes. The schedule is propagated
#: forward from here by absolute cycle number.
_FIRST_SCHEDULED_CYCLE = 1


#: How far short of its programmed profile pressure an APEX/ARGOS float
#: must stop before the cycle is called grounded, in dbar.
#:
#: **This is the empirically verified INCOIS APEX/ARGOS criterion, not an
#: Argo-wide universal constant.** Do not substitute the 150 dbar figure
#: that appears in the DAC trajectory cookbook's ascent-rate annex: that
#: number bounds a velocity study, and measurement shows INCOIS uses 100.
#:
#: The Argo DAC trajectory cookbook (v6.1, Nov 2022, DOI 10.13155/29824)
#: §2.5 sanctions two derivations, "1) based on float performance and
#: technical data or 2) based on checks with bathymetry", and Annex D
#: §5.2 gives the APEX/ARGOS performance form: a cycle whose deepest bin
#: falls short of the programmed profile pressure "can be flagged
#: grounded". Reference table 20 reserves ``B``/``C`` for the bathymetry
#: route; INCOIS publishes ``Y``/``N``, so the performance route is the
#: one they took. The cookbook leaves the margin to the DAC.
#:
#: 100 dbar is INCOIS's choice, measured not assumed. Across 69 INCOIS
#: APEX floats and 12 518 cycles the error count is sharply minimised
#: here and the curve is asymmetric about it -- 87 errors at 75 dbar, 78
#: at 100, 127 at 101, 165 at 150 -- which is the signature of a
#: deterministic threshold rather than a fitted one. On the eight floats
#: with full reference coverage the rule reproduces 2 305 of 2 315
#: published flags, every residual being a cycle whose profile file
#: INCOIS has not published. Full evidence: ``docs/GROUNDED_INVESTIGATION.md``.
GROUNDED_PRESSURE_MARGIN_DBAR = 100.0

#: Argo reference table 20 codes this module can emit.
GROUNDED_YES = "Y"
GROUNDED_NO = "N"
GROUNDED_UNKNOWN = "U"


def grounded_flag(
    max_ascent_pressure_dbar: float | None,
    target_pressure_dbar: float | None,
) -> str:
    """Classify one cycle's grounding from float performance.

    Returns an Argo reference table 20 code:

    * ``'U'`` when the cycle produced no usable ascending-profile
      pressure, or when the programmed profile pressure is unknown. Both
      are missing *inputs*, and a missing input cannot be answered with
      ``'Y'`` or ``'N'`` -- the flag means "did the float touch the
      ground", not "did we manage to check".
    * ``'Y'`` when the deepest ascending sample falls more than
      :data:`GROUNDED_PRESSURE_MARGIN_DBAR` short of the programmed
      profile pressure: the float stopped early, and on these floats the
      only thing that stops an APF9 short of its target is the seabed.
    * ``'N'`` otherwise.

    The comparison is strict (``<``), so a cycle landing exactly on
    ``target - margin`` is ``'N'``. Measured on the reference floats:
    no cycle sits in the ``(target-100, target-90]`` band at all, and the
    shallowest ``Y`` deficit is 100.1 dbar against a deepest ``N``
    deficit of 100.0, so the boundary is real and this is the side of it
    INCOIS uses.
    """
    if target_pressure_dbar is None or not math.isfinite(target_pressure_dbar):
        return GROUNDED_UNKNOWN
    if max_ascent_pressure_dbar is None or not math.isfinite(max_ascent_pressure_dbar):
        return GROUNDED_UNKNOWN
    if max_ascent_pressure_dbar < target_pressure_dbar - GROUNDED_PRESSURE_MARGIN_DBAR:
        return GROUNDED_YES
    return GROUNDED_NO


def config_parameter(meta: FloatMeta | None, name: str) -> float | None:
    """Read one ``LAUNCH_CONFIG_PARAMETER_*`` entry as a float.

    Returns ``None`` when the parameter is absent or unparseable, so
    callers can distinguish "not configured" from a real value.
    """
    if meta is None:
        return None
    names = getattr(meta, "LAUNCH_CONFIG_PARAMETER_NAME", None) or []
    values = getattr(meta, "LAUNCH_CONFIG_PARAMETER_VALUE", None) or []
    flat_names = [v for entry in names for v in entry.values()]
    flat_values = [v for entry in values for v in entry.values()]
    for key, value in zip(flat_names, flat_values, strict=False):
        if str(key).strip() == name:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _offset_pressure(pres: float | None, surface_offset: float | None) -> float | None:
    """Apply the cycle's surface-pressure offset to a park sample.

    ``PRES_ADJUSTED = PRES - PRES_SurfaceOffsetNotTruncated``, the
    standard Argo pressure correction. Verified exact on 2 020 of 2 020
    adjusted park rows across the four reference floats.
    """
    if pres is None or surface_offset is None:
        return None
    return pres - surface_offset


def _launch_measurement(meta: FloatMeta | None) -> TrajMeasurement | None:
    """Build the ``MC=0`` launch row from float metadata.

    The references carry one launch row at ``CYCLE_NUMBER = -1`` holding
    the deployment time and position. Emitted only when the metadata
    actually provides them.
    """
    if meta is None:
        return None
    launch_date = getattr(meta, "launch_date", "")
    lat = getattr(meta, "launch_latitude", None)
    lon = getattr(meta, "launch_longitude", None)
    if not launch_date or lat is None or lon is None:
        return None
    if float(lat) == 0.0 and float(lon) == 0.0:
        return None
    juld = _launch_juld(str(launch_date))
    if juld is None:
        return None
    return TrajMeasurement(
        cycle_number=-1,
        measurement_code=TrajMeasurementCode.LAUNCH,
        juld=juld,
        # The deployment time and position are recorded by the ship, not
        # measured by the float, so the references mark the launch row
        # with a blank JULD_STATUS and 'good' QC on both axes (verified
        # identical on WMO 2901304, 2902222 and 2902224).
        juld_status=" ",
        juld_qc="1",
        latitude=float(lat),
        longitude=float(lon),
        position_qc="1",
    )


def _launch_juld(raw: str) -> float | None:
    """Parse a Coriolis launch-date string into a Julian day."""
    text = raw.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%d%H%M%S",
        # The CSV registry stores launch dates as DD/MM/YYYY HH:MM:SS.
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y%m%d",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        from datetime import UTC

        return datetime_to_juld(parsed.replace(tzinfo=UTC))
    return None


#: ApexTimings.xlsx rows 29/31: the ascent-end time precedes the start
#: of transmission by a fixed ten minutes. Verified exactly against
#: every GDAC reference cycle that publishes both fields.
_AET_BEFORE_TST_MINUTES = 10


def build_argos_trajectory_records(
    telemetry: list[ArgosCycleTelemetry],
    *,
    meta: FloatMeta | None = None,
    config_mission_number: int = 1,
    max_ascent_pressure_dbar: Mapping[int, float] | None = None,
) -> TrajectoryRecords:
    """Build trajectory records for one APEX/ARGOS float.

    Rows are emitted cycle by cycle in ascending cycle order, following
    the per-cycle template observed in the references, with one
    ``MC=703`` row per ARGOS fix inserted between ``MC=702`` and
    ``MC=704``.

    ``max_ascent_pressure_dbar`` maps output cycle number to the deepest
    pressure that cycle's ascending profile reached. It feeds
    :func:`grounded_flag`; cycles absent from the mapping are reported
    ``GROUNDED='U'``.
    """
    records = TrajectoryRecords()
    deepest = dict(max_ascent_pressure_dbar or {})
    # The programmed profile target. Absent on the single-registry
    # metadata backend, in which case every cycle honestly reports 'U'
    # rather than being classified against a guessed target.
    target_pressure = config_parameter(meta, "CONFIG_ProfilePressure_dbar")

    launch = _launch_measurement(meta)
    if launch is not None:
        records.measurements.append(launch)

    for cycle in sorted(telemetry, key=lambda t: t.cycle_number):
        first_msg = cycle.first_message_juld
        last_msg = cycle.last_message_juld
        fixes = cycle.ordered_fixes

        for code in CYCLE_MEASUREMENT_TEMPLATE:
            if code == TrajMeasurementCode.FIRST_MESSAGE:
                records.measurements.append(
                    _timed_row(cycle.cycle_number, code, first_msg),
                )
                for fix in fixes:
                    records.measurements.append(
                        TrajMeasurement(
                            cycle_number=cycle.cycle_number,
                            measurement_code=TrajMeasurementCode.SURFACE_FIX,
                            juld=datetime_to_juld(fix.at),
                            juld_status=JULD_STATUS_TRANSMITTED,
                            latitude=fix.latitude,
                            longitude=fix.longitude,
                            position_accuracy=fix.location_class,
                            position_qc=position_qc_for_location_class(fix.location_class).decode(
                                "ascii"
                            ),
                            # SATELLITE_NAME is left blank. The raw pass
                            # header does name the receiving spacecraft,
                            # but all four references publish the field
                            # empty for every one of their 22 040 ARGOS
                            # fixes, so writing it would be a difference
                            # from the reference rather than a match.
                            satellite_name="",
                        )
                    )
                continue
            if code == TrajMeasurementCode.LAST_MESSAGE:
                records.measurements.append(
                    _timed_row(cycle.cycle_number, code, last_msg),
                )
                continue
            # Park statistics (MC 296) and the park-end sample (MC 290)
            # carry hydrographic values rather than a time. D4 pp.22-23
            # and D3 p.6; verified against the GDAC reference, which
            # reports exactly these triplets.
            eng = cycle.engineering
            if eng is not None and code == TrajMeasurementCode.DEEP_PARK_DESCENT:
                records.measurements.append(
                    TrajMeasurement(
                        cycle_number=cycle.cycle_number,
                        measurement_code=code,
                        juld=None,
                        juld_status=JULD_STATUS_UNKNOWN,
                        temp=eng.park_temperature_mean,
                        pres=eng.park_pressure_mean,
                        pres_adjusted=_offset_pressure(
                            eng.park_pressure_mean, eng.surface_pressure_dbar
                        ),
                        science_qc=_PARK_SAMPLE_QC,
                    )
                )
                continue
            if eng is not None and code == TrajMeasurementCode.PARK_END:
                records.measurements.append(
                    TrajMeasurement(
                        cycle_number=cycle.cycle_number,
                        measurement_code=code,
                        juld=None,
                        juld_status=JULD_STATUS_UNKNOWN,
                        temp=eng.park_end_temperature,
                        psal=eng.park_end_salinity,
                        pres=eng.park_end_pressure,
                        pres_adjusted=_offset_pressure(
                            eng.park_end_pressure, eng.surface_pressure_dbar
                        ),
                        science_qc=_PARK_SAMPLE_QC,
                    )
                )
                continue
            # MC 903 carries the surface-pressure offset, not a time. The
            # reference publishes exactly the value it also reports as
            # ``PRES_SurfaceOffsetNotTruncated_dbar`` in ``_tech.nc`` --
            # verified equal on all 23 cycles of WMO 2901304 -- so the two
            # files are two views of the same decoded byte.
            if eng is not None and code == TrajMeasurementCode.GROUNDING:
                records.measurements.append(
                    TrajMeasurement(
                        cycle_number=cycle.cycle_number,
                        measurement_code=code,
                        juld=None,
                        juld_status=JULD_STATUS_UNKNOWN,
                        pres=eng.surface_pressure_dbar,
                        # The row carries a value but no flag in any
                        # reference: it is a housekeeping offset, not a
                        # measurement, so no QC applies to it.
                        science_qc=" ",
                    )
                )
                continue
            # Every other event needs the engineering message.
            records.measurements.append(
                TrajMeasurement(
                    cycle_number=cycle.cycle_number,
                    measurement_code=code,
                    juld=None,
                    juld_status=JULD_STATUS_UNKNOWN,
                )
            )

        # M6 -- documented cycle-timing model (ApexTimings.xlsx).
        #
        #   row 27  TST_float = EPOCH + TINIT
        #   row 31  AET_float = TST_float - 10 minutes
        #
        # The 10-minute offset was verified against every reference cycle
        # that publishes both fields: JULD_TRANSMISSION_START minus
        # JULD_ASCENT_END is exactly 10.00 min on all of them.
        #
        # These are the *float clock* forms, and their accuracy depends
        # entirely on how far the float is from deployment.
        #
        # On WMO 2901304, whose archive starts at cycle 1, they are
        # exact: the median difference from the reference across all 23
        # cycles is 0.00 min (range -0.83 to +0.62). On WMO 2902222 and
        # 2902223, whose local archive starts at cycle 327, they sit
        # ~+11 min late.
        #
        # That is not a modelling error but accumulated RTC drift. The
        # reference's own JULD_DESCENT_START advances 864004.944 s per
        # cycle against a programmed 864000 s, i.e. the clock gains
        # 4.944 s every cycle -- which over 327 cycles is the offset we
        # see. Removing it needs the per-cycle CLOCK_OFFSET, and the
        # reference publishes that field empty on all 339 cycles, so
        # there is nothing to subtract. Emitting the honest float-clock
        # time and documenting the residual is preferable to fitting a
        # drift rate to three cycles of overlap.
        eng = cycle.engineering
        tst = eng.telemetry_init if eng is not None else None
        transmission_start = datetime_to_juld(tst) if tst is not None else None
        ascent_end = (
            datetime_to_juld(tst - timedelta(minutes=_AET_BEFORE_TST_MINUTES))
            if tst is not None
            else None
        )

        records.cycles.append(
            TrajCycle(
                cycle_number=cycle.cycle_number,
                juld_first_message=first_msg,
                juld_first_location=datetime_to_juld(fixes[0].at) if fixes else None,
                juld_last_message=last_msg,
                juld_last_location=datetime_to_juld(fixes[-1].at) if fixes else None,
                juld_ascent_end=ascent_end,
                juld_transmission_start=transmission_start,
                config_mission_number=config_mission_number,
                data_mode="R",
                grounded=grounded_flag(deepest.get(cycle.cycle_number), target_pressure),
            )
        )
    _apply_mission_schedule(records, meta)
    _apply_reference_flags(records.measurements)
    return records


def _apply_mission_schedule(records: TrajectoryRecords, meta: FloatMeta | None) -> None:
    """Fill the mission-schedule times on both axes.

    The float does not timestamp descent start, park start, park end or
    transmission end; the DAC derives them by propagating the programmed
    cycle timings from a launch anchor. The chain, verified cell-for-cell
    on WMO 2902222, 2902223 and 2902224, is::

        DESCENT_START(first) = LAUNCH_DATE
        PARK_START(n)        = DESCENT_START(n) + 4.7081 h
        PARK_END(n)          = DESCENT_START(n) + DownTime + 2 h
        TRANSMISSION_END(n)  = DESCENT_START(n) + CycleTime
        DESCENT_START(n+1)   = TRANSMISSION_END(n)

    The same four times are also written to ``JULD_ADJUSTED`` on the
    matching ``N_MEASUREMENT`` rows (MC 100/250/300/800), with
    ``JULD_ADJUSTED_STATUS='1'``; MC 500 stays empty with status ``'9'``.

    Applied only when the archive actually contains the deployment
    cycle. The anchor is the launch date, so a run that holds only late
    cycles has no way to place them: extrapolating 326 spans forward
    accumulates the whole unmodelled clock drift, and anchoring on the
    first cycle *present* would date it to the deployment year. Measured
    on WMO 2902222 and 2902223, whose local archive starts at cycle 327,
    the launch-anchored prediction misses the published DESCENT_START by
    about 210 h. Neither ``LAST_MESSAGE(n-1)`` nor ``TRANSMISSION_END``
    recovers it -- both land within 2 min on only about half the cycles.
    So for a partial archive these four times are left unset rather than
    filled with a value that is wrong by days.

    Not applied when the configuration is missing, rather than guessed.

    Note this deliberately *diverges* from the WMO 2901304 reference,
    which advances the same chain by 480 h per cycle instead of its
    programmed 240 h. That is a defect in the published file: it puts
    DESCENT_START after ASCENT_END on 22 of 23 cycles and dates the last
    cycle's transmission end 220 days after its own last message. The
    three floats above, produced by the same DAC, use CycleTime
    correctly. Reproducing the arithmetic error to score a match would
    publish times that cannot be true.
    """
    down_time = config_parameter(meta, "CONFIG_DownTime_hours")
    cycle_time = config_parameter(meta, "CONFIG_CycleTime_hours")
    if down_time is None or cycle_time is None or not records.cycles:
        return
    anchor = _launch_juld(str(getattr(meta, "launch_date", "") or ""))
    if anchor is None:
        return
    if min(c.cycle_number for c in records.cycles) > _FIRST_SCHEDULED_CYCLE:
        return

    park_end_offset = (down_time + _PARK_END_AFTER_DOWNTIME_HOURS) / 24.0
    park_start_offset = _PARK_START_AFTER_DESCENT_HOURS / 24.0
    cycle_span = cycle_time / 24.0

    # Indexed on the *absolute* cycle number, not on position in this
    # run. A partial archive that starts at cycle 327 must place that
    # cycle 326 spans after launch, not one; stepping per record instead
    # would date it to the deployment year.
    schedule: dict[int, tuple[float, float, float, float]] = {}
    for cycle in records.cycles:
        elapsed = cycle.cycle_number - _FIRST_SCHEDULED_CYCLE
        if elapsed < 0:
            continue
        descent_start = anchor + elapsed * cycle_span
        transmission_end = descent_start + cycle_span
        schedule[cycle.cycle_number] = (
            descent_start,
            descent_start + park_start_offset,
            descent_start + park_end_offset,
            transmission_end,
        )
        cycle.juld_descent_start = descent_start
        cycle.juld_park_start = descent_start + park_start_offset
        cycle.juld_park_end = descent_start + park_end_offset
        cycle.juld_transmission_end = transmission_end

    by_code = {
        TrajMeasurementCode.DESCENT_START: 0,
        TrajMeasurementCode.PARK_DRIFT: 1,
        TrajMeasurementCode.DESCENT_TO_PROFILE_START: 2,
        TrajMeasurementCode.TRANSMISSION_END: 3,
    }
    for measurement in records.measurements:
        position = by_code.get(measurement.measurement_code)
        if position is None:
            continue
        times = schedule.get(measurement.cycle_number)
        if times is None:
            continue
        measurement.juld_adjusted = times[position]
        measurement.juld_adjusted_status = "1"
    for measurement in records.measurements:
        if measurement.measurement_code == TrajMeasurementCode.ASCENT_START:
            measurement.juld_adjusted_status = JULD_STATUS_UNKNOWN

    # The park rows carry the park-end time on the N_MEASUREMENT axis
    # too: in every reference the MC 290 and MC 296 JULDs equal that
    # cycle's JULD_PARK_END exactly, just as MC 600 and MC 700 equal
    # JULD_ASCENT_END and JULD_TRANSMISSION_START.
    park_end = {c.cycle_number: c.juld_park_end for c in records.cycles}
    ascent_end = {c.cycle_number: c.juld_ascent_end for c in records.cycles}
    transmission_start = {c.cycle_number: c.juld_transmission_start for c in records.cycles}
    mirrored = {
        TrajMeasurementCode.PARK_END: park_end,
        TrajMeasurementCode.DEEP_PARK_DESCENT: park_end,
        TrajMeasurementCode.ASCENT_END: ascent_end,
        TrajMeasurementCode.TRANSMISSION_START: transmission_start,
    }
    for measurement in records.measurements:
        source = mirrored.get(measurement.measurement_code)
        if source is None or measurement.juld is not None:
            continue
        measurement.juld = source.get(measurement.cycle_number)


def _timed_row(cycle_number: int, code: int, juld: float | None) -> TrajMeasurement:
    return TrajMeasurement(
        cycle_number=cycle_number,
        measurement_code=code,
        juld=juld,
        juld_status=(JULD_STATUS_TRANSMITTED if juld is not None else JULD_STATUS_UNKNOWN),
    )


def _apply_reference_flags(measurements: list[TrajMeasurement]) -> None:
    """Stamp the per-measurement-code ``JULD_STATUS`` / ``JULD_QC``.

    Both are constants of the measurement code in every reference
    examined, independent of whether the row carries a time -- see
    :data:`JULD_STATUS_BY_MEASUREMENT_CODE`. Applied as a final pass so
    the row-building code above stays concerned with values alone.

    A row that was *expected* to carry a time but has none keeps
    ``JULD_STATUS='9'`` ("not determined"), which is what the references
    do for the handful of incomplete cycles on WMO 2902222 and 2902224.
    """
    for measurement in measurements:
        code = measurement.measurement_code
        status = JULD_STATUS_BY_MEASUREMENT_CODE.get(code)
        if status is not None:
            timed = status in {JULD_STATUS_FLOAT_CLOCK, JULD_STATUS_DERIVED, "4"}
            measurement.juld_status = (
                JULD_STATUS_UNKNOWN if timed and measurement.juld is None else status
            )
        qc = JULD_QC_BY_MEASUREMENT_CODE.get(code)
        if qc is not None:
            measurement.juld_qc = qc


__all__ = [
    "GROUNDED_NO",
    "GROUNDED_PRESSURE_MARGIN_DBAR",
    "GROUNDED_UNKNOWN",
    "GROUNDED_YES",
    "ArgosCycleTelemetry",
    "build_argos_trajectory_records",
    "config_parameter",
    "grounded_flag",
]
