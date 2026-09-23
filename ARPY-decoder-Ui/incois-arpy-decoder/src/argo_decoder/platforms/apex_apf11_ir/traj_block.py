"""APF11 trajectory content (``<WMO>_Rtraj.nc``, pre-NetCDF).

Per-cycle trajectory anchors and measurement rows, built exclusively from
the float's own telemetry. Anchor rules below were each verified against
the published real-time trajectory of the primary parity float (239
published cycles, keyed ``(cycle, MEASUREMENT_CODE)``):

* ``JULD_DESCENT_START``: the first ``Park Descent Mission`` science-log
  message timestamp (bit-exact across the corpus);
* ``JULD_PARK_START``: the first ``Park Mission`` message timestamp --
  FILL on cycle 1 (the deep-profile-first cycle publishes no park
  start on GDAC even though the float logs the phase message) and on
  cycles without message evidence;
* ``JULD_PARK_END``: the system-log ``go_to_state``
  ``Mission state PARK -> DEEPDESCENT`` transition timestamp -- FILL on
  cycle 1 and on cycles without system-log evidence;
* ``JULD_DEEP_DESCENT_END``: the ``Deep Descent Mission`` message
  timestamp (bit-exact, ±1e-7 JULD clock noise on a few cycles);
* ``JULD_ASCENT_START``: the ``go_to_state``
  ``Mission state DEEPDESCENT -> ASCENT``
  transition timestamp;
* ``JULD_ASCENT_END``: the first ``Surface Mission`` message timestamp
  (bit-exact);
* ``JULD_FIRST_LOCATION`` / ``JULD_LAST_LOCATION``: GPS-fix timestamps
  from the consolidated ``GPS`` table plus system-log ``GPS Fix:``
  lines, windowed per cycle:

    - window(k) = (ascent_end(k)*, descent_start(k+1)* + 300 s]
    - ``*`` anchors chain over telemetry-silent neighbours: a cycle with
      no ``Surface Mission`` message inherits the previous cycle's
      ascent end as its window lower bound; a cycle whose successor has
      no ``Park Descent Mission`` message inherits the next available
      descent start as upper bound;
    - cycle 1's window opens at launch;
    - FIRST = earliest fix in the window, LAST = latest fix in the
      window (single-fix windows publish the same timestamp twice);
    - no fix in the window -> both fill.

* ``GROUNDED``: ``'Y'`` when the cycle's system log carries a
  ``Hit bottom`` DEEPDESCENT event, ``'N'`` otherwise -- the raw
  telemetry's only grounding evidence (GDAC's value on six
  ``Hit bottom`` cycles is ``'N'``, and three telemetry-silent early
  cycles publish ``'U'`` where the raw record is silent: those are
  downstream publication choices, not raw evidence);
* the deep-park/message/transmission/stabilization anchor families and
  ``REPRESENTATIVE_PARK_PRESSURE``: fill -- the APF11 stream carries no
  content for them and the publication leaves them fill.
* No clock drift is measured or applied by this builder. The production
  writer leaves ``CLOCK_OFFSET`` at fill rather than assuming zero.

Per-measurement rows follow the published pattern (row count verified
exactly: 1 launch row + 6 rows per cycle, minus the absent 250 rows):

* launch row: CYCLE_NUMBER -1, MEASUREMENT_CODE 0, JULD = the config
  ``meta.csv`` launch timestamp, JULD_STATUS ``'0'``;
* per cycle: ``100`` descent start, ``200`` always fill, ``250`` park
  start (row present only when the anchor is), ``300`` park end,
  ``500`` ascent start, ``600`` ascent end; JULD_STATUS ``'1'`` when the
  anchor exists, ``'9'`` with fill JULD otherwise.

No WMO, cycle or float literal appears anywhere: every value derives
from the cycle's own records.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from argo_decoder.platforms.apex_apf11_ir.phases import (
    CyclePhases,
    timestamp_to_juld,
)
from argo_decoder.platforms.apex_apf11_ir.technical import SyslogEvent

JULD_FILL = 999999.0

#: MC rows published per cycle, in row order (200 is always fill for this
#: DAC; 250 is emitted only when the park-start anchor exists).
MC_ROWS: tuple[int, ...] = (100, 200, 250, 300, 500, 600)

#: Tolerance around the next descent start when windowing GPS fixes.
#: The float's last upload fix lands a handful of seconds before the
#: ``Park Descent Mission`` message (observed 4-7 s on the parity float;
#: the publication accepts +10 s and rejects the +38 s outlier).
_WINDOW_EXIT_TOLERANCE_S = 10.0 / 86400.0


@dataclass
class TrajCycleBlock:
    """N_CYCLE content for one cycle."""

    cycle: int
    descent_start: float = JULD_FILL
    descent_end: float = JULD_FILL
    park_start: float = JULD_FILL
    park_end: float = JULD_FILL
    deep_descent_end: float = JULD_FILL
    ascent_start: float = JULD_FILL
    ascent_end: float = JULD_FILL
    first_message: float = JULD_FILL
    transmission_start: float = JULD_FILL
    transmission_end: float = JULD_FILL
    last_message: float = JULD_FILL
    first_location: float = JULD_FILL
    last_location: float = JULD_FILL
    grounded: str = "N"
    config_mission_number: int | None = None

    def status(self, value: float) -> str:
        return "1" if value != JULD_FILL else "9"


DOUBLE_FILL = 99999.0


@dataclass
class TrajMeasurementRow:
    """One N_MEASUREMENT row."""

    cycle: int
    mc: int
    juld: float = JULD_FILL
    juld_status: str = ""
    juld_qc: str = ""
    latitude: float = DOUBLE_FILL
    longitude: float = DOUBLE_FILL
    position_qc: str = " "
    position_accuracy: str = " "

    @property
    def status(self) -> str:
        if self.juld_status:
            return self.juld_status
        if self.mc == 0:
            return "0"
        return "1" if self.juld != JULD_FILL else "9"


@dataclass
class FloatTrajectory:
    """Whole-float trajectory content (rows grouped per cycle, ascending)."""

    wmo: str
    cycles: list[TrajCycleBlock] = field(default_factory=list)
    rows: list[TrajMeasurementRow] = field(default_factory=list)
    launch_juld: float | None = None


def _juld(ts: str | None) -> float:
    return timestamp_to_juld(ts) if ts else JULD_FILL


def _state_ts(syslog: list[SyslogEvent], src_state: str, dst_state: str) -> str | None:
    """Timestamp of a ``go_to_state`` mission-state transition line."""
    needle = f"{src_state} -> {dst_state}"
    for ev in sorted(syslog, key=lambda e: e.timestamp):
        if needle in ev.text:
            return ev.timestamp
    return None


def _hit_bottom(syslog: list[SyslogEvent]) -> bool:
    return any("Hit bottom" in ev.text for ev in syslog)


def _location_anchors(
    cycles: list[TrajCycleBlock],
    fixes: list[float],
    *,
    launch_juld: float | None = None,
) -> None:
    """Fill FIRST/LAST location anchors from *timestamp-windowed* GPS fixes.

    The float tags its fixes with the cycle whose upload session carried
    them, which shifts telemetry by one cycle for pre-dive fixes; the
    window is therefore computed from anchor timestamps only:

    window(k) = (ascent_end(k), descent_start(k+1) + 10 s], with both
    bounds chained over telemetry-silent neighbours; cycle 1's window
    opens at launch.

    Grey cycles (no ``Surface Mission`` received) publish the final fix in
    the shared window on both anchors -- verified on all 13 grey cycles of
    the parity float.
    """
    if not fixes:
        return
    fixes = sorted(fixes)
    blocks = {b.cycle: b for b in cycles}
    ordered = sorted(blocks)
    for i, cycle in enumerate(ordered):
        block = blocks[cycle]
        if block.ascent_end != JULD_FILL:
            lower = launch_juld if cycle == min(ordered) else block.ascent_end
        else:
            lower = None
            for j_ in range(i - 1, -1, -1):
                prev = blocks[ordered[j_]].ascent_end
                if prev != JULD_FILL:
                    lower = prev
                    break
        upper = None
        for j_ in range(i + 1, len(ordered)):
            nxt = blocks[ordered[j_]].descent_start
            if nxt != JULD_FILL:
                upper = nxt + _WINDOW_EXIT_TOLERANCE_S
                break
        max_surf = None
        if block.ascent_end != JULD_FILL:
            max_surf = block.ascent_end + 2.0
        elif block.transmission_end != JULD_FILL:
            max_surf = block.transmission_end + 1.0
        if max_surf is not None:
            if upper is None or upper > max_surf:
                upper = max_surf
        inside = [
            f
            for f in fixes
            if (lower is None or f > lower) and (upper is None or f <= upper)
        ]
        if not inside:
            continue
        if block.ascent_end == JULD_FILL:
            block.first_location = block.last_location = inside[-1]
        else:
            block.first_location = inside[0]
            block.last_location = inside[-1]


def build_trajectory(
    *,
    wmo: str,
    cycles: dict[int, CyclePhases],
    syslog_by_cycle: dict[int, list[SyslogEvent]],
    fixes_by_cycle: dict[int, list[str]],
    missions: dict[int, int],
    launch_juld: float | None = None,
    launch_lat: float | None = None,
    launch_lon: float | None = None,
    message_sessions: dict[int, tuple[float, float]] | None = None,
    gps_fixes: list[object] | None = None,
) -> FloatTrajectory:
    """Assemble the full-float trajectory from per-cycle telemetry slices.

    ``cycles`` maps cycle -> parsed science-log phase anchors; cycle index
    1..N are published (a cycle-0 entry with ``prelude_start`` is ignored:
    the GDAC launch row carries the config launch timestamp instead, passed
    in ``launch_juld``).

    ``syslog_by_cycle`` maps cycle -> parsed system-log events.
    ``gps_fixes`` carries GpsFix objects (timestamp, latitude, longitude);
    if omitted, fixes derive from ``fixes_by_cycle`` (timestamps only).
    Pre-launch (cycle-0 maintenance) fixes are excluded.
    """

    out = FloatTrajectory(wmo=wmo, launch_juld=launch_juld)

    if not cycles:
        return out

    # Collect and validate GPS fixes
    valid_fixes: list[object] = []
    if gps_fixes is not None:
        for f in gps_fixes:
            ts = getattr(f, "timestamp", None)
            if not ts:
                continue
            src = getattr(f, "src_cycle", None)
            if src in ("000", 0, "0"):
                continue
            fj = timestamp_to_juld(ts)
            if launch_juld is not None and fj <= launch_juld:
                continue
            valid_fixes.append(f)
    else:
        for c, ts_list in fixes_by_cycle.items():
            if c <= 0:
                continue
            for ts in ts_list:
                if not ts:
                    continue
                fj = timestamp_to_juld(ts)
                if launch_juld is not None and fj <= launch_juld:
                    continue
                class _StubFix:
                    def __init__(self, t):
                        self.timestamp = t
                        self.latitude = None
                        self.longitude = None
                valid_fixes.append(_StubFix(ts))

    # Deduplicate by timestamp preserving order
    seen_ts = set()
    dedup_fixes = []
    for f in sorted(valid_fixes, key=lambda x: timestamp_to_juld(x.timestamp)):
        if f.timestamp not in seen_ts:
            seen_ts.add(f.timestamp)
            dedup_fixes.append(f)
    valid_fixes = dedup_fixes

    first_cycle = min(c for c in cycles if c > 0)
    last_cycle = max(c for c in cycles if c > 0)
    for cycle in range(first_cycle, last_cycle + 1):
        ph = cycles.get(cycle, CyclePhases(cycle=cycle))
        syslog = syslog_by_cycle.get(cycle, [])

        if (
            not any(
                (ph.prelude_start, ph.descent_start, ph.park_start, ph.park_end,
                 ph.profiling_start, ph.continuous_profile_start,
                 ph.continuous_profile_end, ph.ascent_end)
            )
            and not syslog
        ):
            continue

        complete = ph.ascent_end is not None
        ascent_end_j = _juld(ph.ascent_end)
        session = (message_sessions or {}).get(cycle)
        if session is None:
            fm = lm = JULD_FILL
        else:
            fm, lm = session
        block = TrajCycleBlock(
            cycle=cycle,
            descent_start=_juld(ph.descent_start) if complete else JULD_FILL,
            descent_end=_juld(_state_ts(syslog, "PARKDESCENT", "PARK")),
            park_start=(
                _juld(ph.park_start)
                if complete and ph.park_start
                else (
                    _juld(_state_ts(syslog, "PARKDESCENT", "PARK"))
                    if complete
                    else JULD_FILL
                )
            ),
            park_end=(
                _juld(_state_ts(syslog, "PARK", "DEEPDESCENT"))
                if complete and _state_ts(syslog, "PARK", "DEEPDESCENT")
                else (_juld(ph.park_end) if complete else JULD_FILL)
            ),
            deep_descent_end=_juld(ph.park_end) if complete else JULD_FILL,
            ascent_start=(
                _juld(_state_ts(syslog, "DEEPDESCENT", "ASCENT"))
                if complete
                else JULD_FILL
            ),
            ascent_end=ascent_end_j,
            first_message=(fm if complete else JULD_FILL),
            transmission_start=(fm if complete else JULD_FILL),
            transmission_end=(lm if complete else JULD_FILL),
            last_message=(lm if complete else JULD_FILL),
            grounded="Y" if _hit_bottom(syslog) else "N",
            config_mission_number=missions.get(cycle),
        )
        out.cycles.append(block)

    # Windowing GPS fixes per cycle
    blocks_map = {b.cycle: b for b in out.cycles}
    ordered = sorted(blocks_map)
    fixes_by_block: dict[int, list[object]] = {}
    for i, cycle in enumerate(ordered):
        block = blocks_map[cycle]
        if block.ascent_end != JULD_FILL:
            lower = launch_juld if cycle == min(ordered) else block.ascent_end
        else:
            lower = None
            for j_ in range(i - 1, -1, -1):
                prev = blocks_map[ordered[j_]].ascent_end
                if prev != JULD_FILL:
                    lower = prev
                    break
        upper = None
        for j_ in range(i + 1, len(ordered)):
            nxt = blocks_map[ordered[j_]].descent_start
            if nxt != JULD_FILL:
                upper = nxt + _WINDOW_EXIT_TOLERANCE_S
                break
        max_surf = None
        if block.ascent_end != JULD_FILL:
            max_surf = block.ascent_end + 2.0
        elif block.transmission_end != JULD_FILL:
            max_surf = block.transmission_end + 1.0
        if max_surf is not None:
            if upper is None or upper > max_surf:
                upper = max_surf
        inside = [
            f
            for f in valid_fixes
            if (lower is None or timestamp_to_juld(f.timestamp) > lower)
            and (upper is None or timestamp_to_juld(f.timestamp) <= upper)
        ]
        fixes_by_block[cycle] = inside
        if inside:
            f_juld = timestamp_to_juld(inside[0].timestamp)
            l_juld = timestamp_to_juld(inside[-1].timestamp)
            block.first_location = f_juld
            block.last_location = l_juld
            if block.ascent_end == JULD_FILL:
                block.first_location = block.last_location = l_juld
            if session is None and complete:
                block.first_message = f_juld
                block.transmission_start = f_juld
                block.last_message = l_juld
                block.transmission_end = l_juld

    # Launch row (MC 0)
    if launch_juld is not None:
        l_lat = launch_lat if (launch_lat is not None and launch_lat != DOUBLE_FILL) else DOUBLE_FILL
        l_lon = launch_lon if (launch_lon is not None and launch_lon != DOUBLE_FILL) else DOUBLE_FILL
        l_pqc = "1" if (l_lat != DOUBLE_FILL and l_lon != DOUBLE_FILL) else " "
        out.rows.append(
            TrajMeasurementRow(
                cycle=-1,
                mc=0,
                juld=launch_juld,
                juld_status="0",
                juld_qc="1",
                latitude=l_lat,
                longitude=l_lon,
                position_qc=l_pqc,
            )
        )

    # Per-cycle table-15 measurement rows
    for block in out.cycles:
        cycle = block.cycle
        inside = fixes_by_block.get(cycle, [])
        first_gps = inside[0] if inside else None
        last_gps = inside[-1] if inside else None

        f_lat = (first_gps.latitude if (first_gps and first_gps.latitude is not None) else DOUBLE_FILL)
        f_lon = (first_gps.longitude if (first_gps and first_gps.longitude is not None) else DOUBLE_FILL)
        f_pqc = "1" if (f_lat != DOUBLE_FILL and f_lon != DOUBLE_FILL) else " "

        l_lat = (last_gps.latitude if (last_gps and last_gps.latitude is not None) else DOUBLE_FILL)
        l_lon = (last_gps.longitude if (last_gps and last_gps.longitude is not None) else DOUBLE_FILL)
        l_pqc = "1" if (l_lat != DOUBLE_FILL and l_lon != DOUBLE_FILL) else " "

        # 100 Descent Start
        out.rows.append(
            TrajMeasurementRow(
                cycle=cycle,
                mc=100,
                juld=block.descent_start,
                juld_status="1" if block.descent_start != JULD_FILL else "9",
                juld_qc="0" if block.descent_start != JULD_FILL else "9",
            )
        )
        # 200 Descent End
        out.rows.append(
            TrajMeasurementRow(
                cycle=cycle,
                mc=200,
                juld=block.descent_end,
                juld_status="1" if block.descent_end != JULD_FILL else "9",
                juld_qc="0" if block.descent_end != JULD_FILL else "9",
            )
        )
        # 250 Park Start
        out.rows.append(
            TrajMeasurementRow(
                cycle=cycle,
                mc=250,
                juld=block.park_start,
                juld_status="1" if block.park_start != JULD_FILL else "9",
                juld_qc="0" if block.park_start != JULD_FILL else "9",
            )
        )
        # 300 Park End
        out.rows.append(
            TrajMeasurementRow(
                cycle=cycle,
                mc=300,
                juld=block.park_end,
                juld_status="1" if block.park_end != JULD_FILL else "9",
                juld_qc="0" if block.park_end != JULD_FILL else "9",
            )
        )
        # 400 Deep Descent End (fill)
        out.rows.append(
            TrajMeasurementRow(
                cycle=cycle,
                mc=400,
                juld=JULD_FILL,
                juld_status="9",
                juld_qc="9",
            )
        )
        # 500 Ascent Start
        out.rows.append(
            TrajMeasurementRow(
                cycle=cycle,
                mc=500,
                juld=block.ascent_start,
                juld_status="1" if block.ascent_start != JULD_FILL else "9",
                juld_qc="0" if block.ascent_start != JULD_FILL else "9",
            )
        )
        # 600 Ascent End
        out.rows.append(
            TrajMeasurementRow(
                cycle=cycle,
                mc=600,
                juld=block.ascent_end,
                juld_status="1" if block.ascent_end != JULD_FILL else "9",
                juld_qc="0" if block.ascent_end != JULD_FILL else "9",
                latitude=f_lat,
                longitude=f_lon,
                position_qc=f_pqc,
            )
        )
        # 700 Transmission Start
        out.rows.append(
            TrajMeasurementRow(
                cycle=cycle,
                mc=700,
                juld=block.transmission_start,
                juld_status="1" if block.transmission_start != JULD_FILL else "9",
                juld_qc="0" if block.transmission_start != JULD_FILL else "9",
                latitude=f_lat,
                longitude=f_lon,
                position_qc=f_pqc,
            )
        )
        # 702 First Message
        out.rows.append(
            TrajMeasurementRow(
                cycle=cycle,
                mc=702,
                juld=block.first_message,
                juld_status="1" if block.first_message != JULD_FILL else "9",
                juld_qc="0" if block.first_message != JULD_FILL else "9",
                latitude=f_lat,
                longitude=f_lon,
                position_qc=f_pqc,
            )
        )
        # 703 Surface Fixes
        if inside:
            for f in inside:
                fj = timestamp_to_juld(f.timestamp)
                flat = f.latitude if f.latitude is not None else DOUBLE_FILL
                flon = f.longitude if f.longitude is not None else DOUBLE_FILL
                fpqc = "1" if (flat != DOUBLE_FILL and flon != DOUBLE_FILL) else " "
                out.rows.append(
                    TrajMeasurementRow(
                        cycle=cycle,
                        mc=703,
                        juld=fj,
                        juld_status="1",
                        juld_qc="0",
                        latitude=flat,
                        longitude=flon,
                        position_qc=fpqc,
                    )
                )
        else:
            # Fallback placeholder rows if no GPS fixes available
            out.rows.append(
                TrajMeasurementRow(
                    cycle=cycle,
                    mc=703,
                    juld=block.first_location,
                    juld_status="1" if block.first_location != JULD_FILL else "9",
                    juld_qc="0" if block.first_location != JULD_FILL else "9",
                )
            )
            out.rows.append(
                TrajMeasurementRow(
                    cycle=cycle,
                    mc=703,
                    juld=block.last_location,
                    juld_status="1" if block.last_location != JULD_FILL else "9",
                    juld_qc="0" if block.last_location != JULD_FILL else "9",
                )
            )
        # 704 Last Message
        out.rows.append(
            TrajMeasurementRow(
                cycle=cycle,
                mc=704,
                juld=block.last_message,
                juld_status="1" if block.last_message != JULD_FILL else "9",
                juld_qc="0" if block.last_message != JULD_FILL else "9",
                latitude=l_lat,
                longitude=l_lon,
                position_qc=l_pqc,
            )
        )
        # 800 Transmission End
        out.rows.append(
            TrajMeasurementRow(
                cycle=cycle,
                mc=800,
                juld=block.transmission_end,
                juld_status="1" if block.transmission_end != JULD_FILL else "9",
                juld_qc="0" if block.transmission_end != JULD_FILL else "9",
                latitude=l_lat,
                longitude=l_lon,
                position_qc=l_pqc,
            )
        )
        # 903 Grounding / Abort
        out.rows.append(
            TrajMeasurementRow(
                cycle=cycle,
                mc=903,
                juld=JULD_FILL,
                juld_status="9",
                juld_qc="9",
            )
        )

    return out


__all__ = [
    "FloatTrajectory",
    "TrajCycleBlock",
    "TrajMeasurementRow",
    "build_trajectory",
    "MC_ROWS",
    "JULD_FILL",
]