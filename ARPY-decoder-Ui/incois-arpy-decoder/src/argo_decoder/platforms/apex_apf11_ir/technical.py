"""Legacy APF11 scalar/display audit model, not the VITALS publication model.

VITALS are timestamped records; use technical_measurements and the numeric
writer. Vacuum is source dbar without conversion (vendor manual Rev11 §4.5).
Legacy piston groupings below are historical display summaries, NOT approved
piston-position identities. The scalar writer rejects these unresolved inputs.
"""

from __future__ import annotations

import gzip
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Historical display order, with the vacuum unit assertion corrected to dbar.
TECH_PARAMETER_ORDER: tuple[str, ...] = (
    "VOLTAGE_BatteryInitialAtProfileDepth_volts",
    "PRESSURE_InternalVacuum_dbar",
    "FLAG_ProfileTermination_hex",
    "PRES_SurfaceOffsetNotTruncated_dbar",
    "POSITION_PistonSurface_COUNT",
    "TIME_PumpMotor_seconds",
    "CURRENT_BatteryInitialAtProfileDepth_mA",
    "POSITION_PistonProfile_COUNT",
    "POSITION_PistonPark_COUNT",
    "VOLTAGE_BatteryParkNoLoad_volts",
    "CURRENT_BatteryPark_mA",
    "VOLTAGE_BatterySBEAscent_volts",
    "PRESSURE_AirBladder_COUNT",
    "CURRENT_BatterySBEPump_mA",
    "FLAG_CTDStatus_NUMBER",
    "VOLTAGE_BatterySurfaceAirPumpOn_volts",
    "NUMBER_RepositionsDuringPark_COUNT",
    "NUMBER_ParkSamples_COUNT",
    "POSITION_PistonMax_COUNT",
    "CLOCK_RealTimeDrift_seconds",
)


@dataclass(frozen=True)
class VitalsRow:
    """One ``VITALS_CORE`` record (aggregate-normed columns)."""

    timestamp: str
    air_bladder_dbar: float | None
    air_bladder_cnts: float | None
    battery_voltage_v: float | None
    battery_voltage_cnts: float | None
    humidity: float | None
    leak_detect_v: float | None
    vacuum_dbar: float | None
    vacuum_cnts: float | None
    coulomb_ahrs: float | None
    battery_current_ma: float | None
    battery_current_raw: float | None


@dataclass(frozen=True)
class SyslogEvent:
    """One ``timestamp|level|component|text`` line from a system log."""

    timestamp: str
    component: str
    text: str


@dataclass
class CycleTechnical:
    """Legacy audit display cells for one cycle; not a publication contract."""

    cycle: int
    battery_voltage: list[float] = field(default_factory=list)
    internal_vacuum: list[float] = field(default_factory=list)
    battery_current: list[float] = field(default_factory=list)
    surface_offset: float | None = None
    piston_surface: int | None = None
    piston_profile: list[int] = field(default_factory=list)
    piston_park: list[int] = field(default_factory=list)
    air_bladder: float | None = None
    park_samples: int | None = None

    def rows(self) -> list[tuple[str, str]]:
        """Return historical audit display cells, not timestamped measurements.

        Multi-value series follow the publisher's own printf form (``%g``
        cells left-justified to width 13 for the VITALS series, ``%.4f``
        cells to width 10 for the profile-piston list), then right-trimmed.
        """

        def series(vals: list[float]) -> str:
            if not vals:
                return ""
            return "".join(f"{v:g}".ljust(13) for v in vals).rstrip()

        def piston_series(vals: list[int]) -> str:
            if not vals:
                return ""
            return "".join(f"{v:.4f}".ljust(10) for v in vals).rstrip()

        cells: dict[str, str] = {
            "VOLTAGE_BatteryInitialAtProfileDepth_volts": series(self.battery_voltage),
            "PRESSURE_InternalVacuum_dbar": series(self.internal_vacuum),
            "CURRENT_BatteryInitialAtProfileDepth_mA": series(self.battery_current),
            "PRESSURE_AirBladder_COUNT": (
                f"{self.air_bladder:g}" if self.air_bladder is not None else ""
            ),
            "PRES_SurfaceOffsetNotTruncated_dbar": (
                f"{self.surface_offset:g}" if self.surface_offset is not None else ""
            ),
            "POSITION_PistonSurface_COUNT": (
                str(self.piston_surface) if self.piston_surface is not None else ""
            ),
            "POSITION_PistonProfile_COUNT": piston_series(self.piston_profile),
            "POSITION_PistonPark_COUNT": (
                "  ".join(str(v) for v in self.piston_park) if self.piston_park else ""
            ),
            "NUMBER_ParkSamples_COUNT": (
                str(self.park_samples) if self.park_samples is not None else ""
            ),
        }
        return [(name, cells.get(name, "")) for name in TECH_PARAMETER_ORDER]


# --- raw input parsing ------------------------------------------------------

_VITALS_WIDTH = 11


def parse_vitals_row(timestamp: str, fields: list[str]) -> VitalsRow | None:
    """Build a :class:`VitalsRow` from one consolidated VITALS_CORE record.

    The consolidated table stores the 11 payload values after the
    ``(src_cycle, record_type, timestamp)`` key. Columns follow the vendor
    table order (air bladder, battery, humidity, leak, vacuum, coulombs,
    currents). The vacuum physical column is dbar, unconverted. Rounded
    consolidated fields are not substitutes for native binary precision.
    """

    if len(fields) < _VITALS_WIDTH:
        return None

    def num(text: str) -> float | None:
        try:
            return float(str(text).strip())
        except (TypeError, ValueError):
            return None

    vals = [num(x) for x in fields[: _VITALS_WIDTH]]
    return VitalsRow(
        timestamp=timestamp,
        air_bladder_dbar=vals[0],
        air_bladder_cnts=vals[1],
        battery_voltage_v=vals[2],
        battery_voltage_cnts=vals[3],
        humidity=vals[4],
        leak_detect_v=vals[5],
        vacuum_dbar=vals[6],
        vacuum_cnts=vals[7],
        coulomb_ahrs=vals[8],
        battery_current_ma=vals[9],
        battery_current_raw=vals[10],
    )


_SYSLOG_RE = re.compile(r"^(?P<ts>\d{8}T\d{6})\|(?P<level>\d+)\|(?P<comp>[^|]*)\|(?P<text>.*)$")


def parse_system_log_lines(text: str) -> list[SyslogEvent]:
    """Parse one system-log stream into structured events.

    Lines that do not match the ``ts|level|component|text`` shape (banner
    continuations, sample-cfg payloads) are skipped: they are never a source
    for the technical parameters implemented here.
    """

    out: list[SyslogEvent] = []
    for line in text.splitlines():
        m = _SYSLOG_RE.match(line.rstrip("\r"))
        if m:
            out.append(
                SyslogEvent(
                    timestamp=m.group("ts"),
                    component=m.group("comp").strip(),
                    text=m.group("text").strip(),
                )
            )
    return out


_SYSTEM_LOG_NAME = re.compile(r"\.(?P<cycle>\d{3})\.\d{8}T\d{6}\.system_log\.txt(?:\.gz)?$")


def float_system_logs(raw_dir: Path) -> dict[int, list[Path]]:
    """Map cycle number -> its system-log file(s) under a float's raw dir.

    Cycle attribution comes from the protocol digit of the file name
    (``<id>.<cycle>.<stamp>.system_log.txt.gz``) — the same convention the
    consolidated tables use for their own ``src_cycle`` column. Multiple
    uploads of one cycle (Iridium retries) are kept together, newest files
    simply duplicating rows, which downstream dedupes.
    """

    out: dict[int, list[Path]] = {}
    if not raw_dir.exists():
        return out
    for path in sorted(raw_dir.iterdir()):
        m = _SYSTEM_LOG_NAME.search(path.name)
        if m:
            out.setdefault(int(m.group("cycle")), []).append(path)
    return out


def read_system_log(path: Path) -> str:
    """Read a (possibly gzipped) system log as text."""

    if path.suffix == ".gz":
        with gzip.open(path, "rt", errors="replace") as fh:
            return fh.read()
    return path.read_text(errors="replace")


# --- technical derivation ---------------------------------------------------

_SURFACE_OFFSET_RE = re.compile(r"Surface Offset Pressure:\s*(-?\d+(?:\.\d+)?)")
_DEST_REACHED_RE = re.compile(r"Buoyancy engine destination\s+(\d+)\s+reached")
_GOTO_STATE_RE = re.compile(r"Mission state\s+(\w+)\s*->\s*(\w+)")
_OFFSET_ACCEPTANCE_S = 90.0


def _sec(ts: str) -> float:
    from argo_decoder.platforms.apex_apf11_ir.phases import timestamp_to_juld

    return timestamp_to_juld(ts) * 86400.0


def build_cycle_technical(
    cycle: int,
    *,
    vitals: list[VitalsRow],
    syslog: list[SyslogEvent],
    ascent_end: str | None,
    park_start: str | None,
    park_end: str | None,
    park_sample_records: list[tuple[str, int | None]],
) -> CycleTechnical:
    """Assemble the 20-row technical block for one cycle.

    All inputs are per-cycle slices of the float's own telemetry; the
    phase anchors come from the science-log ``Message`` records (the same
    :class:`CyclePhases` the profile products use).
    """

    out = CycleTechnical(cycle=cycle)

    # --- VITALS window: rows up to ~1 s after the Surface Mission anchor ---
    if ascent_end is not None and vitals:
        aet = _sec(ascent_end)
        window = [v for v in vitals if _sec(v.timestamp) - aet <= _OFFSET_ACCEPTANCE_S]
        for row in window:
            if row.battery_voltage_v is not None:
                out.battery_voltage.append(row.battery_voltage_v)
            if row.vacuum_dbar is not None:
                out.internal_vacuum.append(row.vacuum_dbar)
            if row.battery_current_ma is not None:
                out.battery_current.append(row.battery_current_ma)
        if window and window[-1].air_bladder_dbar is not None:
            out.air_bladder = window[-1].air_bladder_dbar

    # --- system-log scalar events ------------------------------------------
    state = ""
    surface_offset_seen = False
    for ev in sorted(syslog, key=lambda e: e.timestamp):
        goto = _GOTO_STATE_RE.search(ev.text)
        if goto:
            state = goto.group(2).upper()
            continue
        if ev.component == "SURFACE" and not surface_offset_seen:
            m = _SURFACE_OFFSET_RE.search(ev.text)
            if m:
                out.surface_offset = float(m.group(1))
                surface_offset_seen = True
            continue
        reached = _DEST_REACHED_RE.search(ev.text)
        if reached:
            dest = int(reached.group(1))
            if state == "PARKDESCENT":
                if not out.piston_park:
                    out.piston_park.append(dest)
            elif state == "PARK":
                # every repositioning destination during the park drift is
                # published (verified on the parity float: all 29 cycles
                # with drift corrections carry the full destination series)
                out.piston_park.append(dest)
            elif state in ("DEEPDESCENT", "ASCENT", "DEEPPARK"):
                out.piston_profile.append(dest)
            elif state == "SURFACE":
                out.piston_surface = dest
            continue

    # --- park CTD sample count ----------------------------------------------
    # Sum the record-reported sample counts in the park window (a PTS burst
    # packs 3 samples: 225 records -> 675 samples on the parity float,
    # verified against every published tech cycle).  Records without a
    # sample count contribute 1 (record == sample).
    if park_start is not None and park_end is not None:
        win = [
            (t, n) for (t, n) in park_sample_records if park_start <= t < park_end
        ]
        uniq: dict[str, int] = {}
        for t, n in win:
            uniq.setdefault(t, n if n is not None else 1)
        out.park_samples = sum(uniq.values())
    else:
        out.park_samples = None

    return out


# --- NetCDF text cell encoding ----------------------------------------------


def fmt_g(value: float) -> str:
    """``%g`` cell content used for the 13-wide VITALS series."""

    return f"{value:g}"


__all__ = [
    "TECH_PARAMETER_ORDER",
    "CycleTechnical",
    "SyslogEvent",
    "VitalsRow",
    "build_cycle_technical",
    "float_system_logs",
    "parse_system_log_lines",
    "parse_vitals_row",
    "read_system_log",
]
