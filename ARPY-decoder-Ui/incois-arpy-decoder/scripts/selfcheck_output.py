#!/usr/bin/env python3
"""Reference-free plausibility checks on decoder output.

The point of this script is that it needs **no GDAC file**. Every check is
an internal-consistency or physical-plausibility invariant, so it works on
the first cycle of a brand-new float that nobody has ever published.

Motivation: the defects found on 2901328/2901350 (a spurious +256 cycle
offset, a mis-selected profile layout, and an RTQC test comparing
non-overlapping depth bands) were all *visible in our own output*. They were
only caught because a reference happened to exist. These checks catch that
class without one.

Each check returns findings with a severity:

``error``    physically impossible or self-contradictory - certainly wrong
``warn``     implausible - probably wrong, worth a human look

Exit code is non-zero when any ``error`` is present, so this can gate a
pipeline run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import netCDF4  # type: ignore[import-untyped]
import numpy as np

_JULD_REF = dt.datetime(1950, 1, 1, tzinfo=dt.UTC)
_CYCLE_RE = re.compile(r"_(\d+)\.nc$")

# Physical envelopes. Deliberately wide: these detect gross field
# mis-assignment (a layout error), not oceanographic subtleties.
_PRES_RANGE = (-10.0, 6500.0)
_TEMP_RANGE = (-2.5, 40.0)
_PSAL_RANGE = (2.0, 41.0)

#: A profile whose pressures are entirely fill is never legitimate.
#: A layout misread typically produces exactly this.
_MIN_FINITE_FRACTION = 0.5

#: Extrapolating cycle numbers back to cycle 0 must land near deployment.
_DEPLOY_TOLERANCE_DAYS = 45.0


@dataclass
class Finding:
    severity: str
    check: str
    detail: str


@dataclass
class FloatOutput:
    wmo: int
    cycles: dict[int, Path] = field(default_factory=dict)
    juld: dict[int, float] = field(default_factory=dict)


def _load(nc_dir: Path, wmo: int) -> FloatOutput:
    out = FloatOutput(wmo=wmo)
    for path in sorted((nc_dir / "profiles").glob("*.nc")):
        m = _CYCLE_RE.search(path.name)
        if m is None:
            continue
        cycle = int(m.group(1))
        out.cycles[cycle] = path
        with netCDF4.Dataset(path) as ds:
            if "JULD" in ds.variables:
                value = float(np.ma.filled(ds.variables["JULD"][0], np.nan))
                if np.isfinite(value):
                    out.juld[cycle] = value
    return out


def _values(ds: netCDF4.Dataset, name: str) -> np.ndarray:
    if name not in ds.variables:
        return np.array([])
    return np.ma.filled(ds.variables[name][0].astype("f8"), np.nan)


def check_parameter_envelopes(out: FloatOutput) -> list[Finding]:
    """Catch a mis-selected profile layout.

    When the wrong byte layout is used the fields shift, so pressure lands
    in the temperature slot and so on. Range checks on all three
    parameters catch that immediately, without any reference.
    """
    findings: list[Finding] = []
    ranges = {"PRES": _PRES_RANGE, "TEMP": _TEMP_RANGE, "PSAL": _PSAL_RANGE}
    offenders: dict[str, int] = defaultdict(int)
    empty_pres = 0
    for cycle, path in out.cycles.items():
        with netCDF4.Dataset(path) as ds:
            pres = _values(ds, "PRES")
            if pres.size and not np.isfinite(pres).any():
                empty_pres += 1
            for name, (lo, hi) in ranges.items():
                arr = _values(ds, name)
                if not arr.size:
                    continue
                finite = arr[np.isfinite(arr)]
                if finite.size and ((finite < lo) | (finite > hi)).any():
                    offenders[name] += 1
                    del cycle  # reported in aggregate below
    for name, count in offenders.items():
        findings.append(
            Finding(
                "error",
                "parameter_envelope",
                f"{name} outside {ranges[name]} on {count} cycle(s) - "
                "typically a wrong profile layout for this firmware",
            )
        )
    if empty_pres:
        findings.append(
            Finding(
                "error",
                "pressure_all_fill",
                f"PRES entirely fill on {empty_pres} cycle(s) - layout misread",
            )
        )
    return findings


def check_cycle_epoch(out: FloatOutput, launch: dt.datetime | None) -> list[Finding]:
    """Catch a bogus constant cycle offset (e.g. an unwarranted 8-bit wrap).

    Cycle numbers and times are redundant: extrapolating the observed
    cycle/time line back to cycle 0 must land near deployment. A spurious
    +256 puts the implied deployment years before the float existed. This
    needs no reference file, only the launch date already in the registry.
    """
    if launch is None or len(out.juld) < 3:
        return []
    cycles = sorted(out.juld)
    periods = [(out.juld[b] - out.juld[a]) / (b - a) for a, b in pairwise(cycles) if b != a]
    if not periods:
        return []
    period = float(np.median(periods))
    if period <= 0:
        return [Finding("error", "cycle_epoch", "non-increasing JULD across cycles")]
    first = cycles[0]
    implied = _JULD_REF + dt.timedelta(days=out.juld[first] - first * period)
    error_days = (implied - launch).total_seconds() / 86400.0
    if abs(error_days) > _DEPLOY_TOLERANCE_DAYS:
        return [
            Finding(
                "error",
                "cycle_epoch",
                f"cycle numbering implies deployment {implied.date()} but launch is "
                f"{launch.date()} ({error_days:+.0f} d). Median period {period * 24:.1f} h. "
                "A constant cycle offset (e.g. an unwarranted 8-bit wrap) is the usual cause",
            )
        ]
    return []


def check_monotonic_time(out: FloatOutput) -> list[Finding]:
    """Cycle number and time must increase together."""
    cycles = sorted(out.juld)
    bad = [b for a, b in pairwise(cycles) if out.juld[b] <= out.juld[a]]
    if bad:
        return [
            Finding(
                "error",
                "time_ordering",
                f"JULD not increasing with cycle number at cycle(s) {bad[:8]}",
            )
        ]
    return []


def check_qc_mass_condemnation(out: FloatOutput) -> list[Finding]:
    """Flag whole-profile condemnations - the signature of an RTQC misfire.

    A cross-cycle test that compares non-overlapping depth bands condemns
    every level of a profile at once. Real sensor failures do happen, so
    this is a warning, but a cluster of them on an otherwise healthy float
    is the fingerprint of a false positive.
    """
    findings: list[Finding] = []
    for param in ("TEMP", "PSAL"):
        whole: list[int] = []
        for cycle, path in sorted(out.cycles.items()):
            with netCDF4.Dataset(path) as ds:
                key = f"{param}_QC"
                if key not in ds.variables:
                    continue
                flags = [c.decode() for c in np.ma.filled(ds.variables[key][0], b" ").tolist()]
                flags = [f for f in flags if f.strip()]
                if flags and all(f in {"3", "4"} for f in flags):
                    whole.append(cycle)
        if whole:
            findings.append(
                Finding(
                    "warn",
                    "qc_whole_profile",
                    f"{param}: every level flagged bad/probably-bad on {len(whole)} cycle(s) "
                    f"{whole[:10]} - verify this is a real failure, not a cross-cycle "
                    "test comparing mismatched depth ranges",
                )
            )
    return findings


def check_depth_vs_qc_correlation(out: FloatOutput) -> list[Finding]:
    """Directly detect the TEST016 depth-band defect.

    If whole-profile condemnations coincide with cycles whose maximum
    pressure is far shallower than the previous cycle's, the flag is an
    artefact of comparing different water, not a sensor drift.
    """
    cycles = sorted(out.cycles)
    maxp: dict[int, float] = {}
    condemned: set[int] = set()
    for cycle in cycles:
        with netCDF4.Dataset(out.cycles[cycle]) as ds:
            pres = _values(ds, "PRES")
            if pres.size and np.isfinite(pres).any():
                maxp[cycle] = float(np.nanmax(pres))
            flags = [c.decode() for c in np.ma.filled(ds.variables["TEMP_QC"][0], b" ").tolist()]
            flags = [f for f in flags if f.strip()]
            if flags and all(f in {"3", "4"} for f in flags):
                condemned.add(cycle)
    suspicious = []
    for prev, cur in pairwise(cycles):
        if cur in condemned and prev in maxp and cur in maxp:
            shortfall = maxp[prev] - maxp[cur]
            if shortfall > 200.0:
                suspicious.append((cur, round(shortfall)))
    if suspicious:
        return [
            Finding(
                "error",
                "qc_depth_artefact",
                f"whole-profile flags coincide with a large dive-depth shortfall on "
                f"{len(suspicious)} cycle(s) {suspicious[:6]} - cross-cycle comparison is "
                "using non-overlapping depth bands",
            )
        ]
    return []


def check_level_counts(out: FloatOutput) -> list[Finding]:
    """A profile with almost no levels next to full ones is suspicious."""
    counts = {}
    for cycle, path in out.cycles.items():
        with netCDF4.Dataset(path) as ds:
            pres = _values(ds, "PRES")
            counts[cycle] = int(np.isfinite(pres).sum())
    if not counts:
        return []
    median = float(np.median(list(counts.values())))
    if median <= 0:
        return []
    thin = [c for c, n in sorted(counts.items()) if n < median * _MIN_FINITE_FRACTION]
    if thin:
        return [
            Finding(
                "warn",
                "thin_profiles",
                f"{len(thin)} cycle(s) have under half the median level count "
                f"({median:.0f}): {thin[:10]}",
            )
        ]
    return []


def audit(nc_dir: Path, wmo: int, launch: dt.datetime | None) -> list[Finding]:
    out = _load(nc_dir, wmo)
    if not out.cycles:
        return [Finding("error", "no_output", f"no profiles found under {nc_dir}")]
    findings: list[Finding] = []
    findings += check_parameter_envelopes(out)
    findings += check_cycle_epoch(out, launch)
    findings += check_monotonic_time(out)
    findings += check_depth_vs_qc_correlation(out)
    findings += check_qc_mass_condemnation(out)
    findings += check_level_counts(out)
    return findings


def _launch_from_registry(registry: Path | None, wmo: int) -> dt.datetime | None:
    if registry is None or not registry.exists():
        return None
    import csv

    for row in csv.DictReader(registry.open(newline="")):
        if row.get("wmo") == str(wmo) and row.get("launch_date_utc"):
            return dt.datetime.fromisoformat(row["launch_date_utc"].replace("Z", "+00:00"))
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nc-dir", type=Path, required=True, help="output nc/<wmo> directory")
    ap.add_argument("--wmo", type=int, required=True)
    ap.add_argument("--registry", type=Path, default=None, help="registry.csv for launch date")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    launch = _launch_from_registry(args.registry, args.wmo)
    findings = audit(args.nc_dir, args.wmo, launch)

    errors = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warn"]
    print(f"=== WMO {args.wmo}: {len(errors)} error(s), {len(warns)} warning(s) ===")
    for f in findings:
        print(f"  [{f.severity:5}] {f.check}: {f.detail}")
    if not findings:
        print("  all reference-free checks passed")

    if args.json:
        args.json.write_text(
            json.dumps(
                [{"severity": f.severity, "check": f.check, "detail": f.detail} for f in findings],
                indent=2,
            )
        )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
