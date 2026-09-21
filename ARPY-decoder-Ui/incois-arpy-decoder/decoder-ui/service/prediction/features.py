"""Prediction features built ONLY from information available at prediction time.

Inputs are the already-cached fleet-status rows (themselves derived from
``<WMO>_prof.nc`` and ``<WMO>_Rtraj.nc``). Every feature carries the timestamp
it was observed at; nothing here reads a future cycle, and a fix observed after
``now`` is dropped.

Only a bounded ring of recent fixes per float is cached by the sync
(``fleet_status.PREDICTION_FIX_HISTORY``), which is all the baseline needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import profile_cycle
from prediction.geometry import displacement_km, haversine_km, speed_km_per_day

#: A cycle-to-cycle hop longer than this is a mission gap, not one cycle, and is
#: excluded from displacement features (same rule as the validation harness).
MAX_TRANSITION_DAYS = 30.0

#: Argo JULD epoch (days since 1950-01-01T00:00:00Z).
JULD_EPOCH = datetime(1950, 1, 1, tzinfo=UTC)

REGION_ARABIAN = "Arabian Sea"
REGION_BENGAL = "Bay of Bengal"
REGION_EQUATORIAL = "Equatorial Indian"
REGION_SOUTH = "South Indian Ocean"
REGION_OTHER = "Other"

CYCLE_CLASS_SHORT = "short"
CYCLE_CLASS_DECADAL = "decadal"


def region_of(lat: float | None, lon: float | None) -> str:
    """Coarse basin boxes, identical to the calibration harness."""
    if lat is None or lon is None:
        return REGION_OTHER
    if lat > 0 and lon < 80:
        return REGION_ARABIAN
    if lat > 0 and lon >= 80:
        return REGION_BENGAL
    if -10 < lat <= 0:
        return REGION_EQUATORIAL
    if lat <= -10:
        return REGION_SOUTH
    return REGION_OTHER


def cycle_class(interval_days: float | None) -> str:
    if interval_days is None:
        return CYCLE_CLASS_DECADAL
    return CYCLE_CLASS_SHORT if interval_days <= 7.0 else CYCLE_CLASS_DECADAL


@dataclass(frozen=True)
class Transition:
    """One observed cycle-to-cycle displacement of one float."""

    wmo: int
    start_juld: float
    lat: float
    lon: float
    dlat_km: float
    dlon_km: float
    days: float
    cycle_from: int | None
    cycle_to: int | None

    @property
    def speed_km_d(self) -> float:
        return speed_km_per_day(self.dlat_km, self.dlon_km, self.days)


@dataclass
class FloatFeatures:
    """Everything the engine may use for one float, with provenance."""

    wmo: int
    platform_type: str | None = None
    transmission_type: str | None = None
    interval_days: float = profile_cycle.DEFAULT_INTERVAL_DAYS
    interval_source: str = profile_cycle.INTERVAL_SOURCE_DEFAULT
    interval_samples: int = 0
    park_pressure_dbar: float | None = None
    phase_hours: dict[str, float] = field(default_factory=dict)
    fixes: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def last_fix(self) -> dict[str, Any] | None:
        return self.fixes[-1] if self.fixes else None

    @property
    def last_transition(self) -> Transition | None:
        return self.transitions[-1] if self.transitions else None

    @property
    def region(self) -> str:
        fix = self.last_fix
        if not fix:
            return REGION_OTHER
        return region_of(fix.get("lat"), fix.get("lon"))

    @property
    def cycle_class(self) -> str:
        return cycle_class(self.interval_days)

    @property
    def has_position(self) -> bool:
        fix = self.last_fix
        if not fix:
            return False
        lat, lon = fix.get("lat"), fix.get("lon")
        return (
            lat is not None
            and lon is not None
            and math.isfinite(lat)
            and math.isfinite(lon)
            and abs(lat) <= 90
            and abs(lon) <= 180
        )


def _fixes_from_row(row: dict[str, Any] | None, now: datetime) -> tuple[list[dict], list[str]]:
    issues: list[str] = []
    if not row:
        return [], ["no cached row"]
    rtraj = row.get("rtraj") or {}
    raw_fixes = rtraj.get("recent_fixes")
    if not isinstance(raw_fixes, list) or not raw_fixes:
        # A legacy row (older parser) still has exactly one verified fix.
        single = rtraj.get("last_fix")
        raw_fixes = [single] if isinstance(single, dict) else []
        if raw_fixes:
            issues.append("single cached trajectory fix (parser predates fix history)")
    clean: list[dict[str, Any]] = []
    for fix in raw_fixes:
        if not isinstance(fix, dict):
            continue
        juld, lat, lon = fix.get("juld"), fix.get("lat"), fix.get("lon")
        if juld is None or lat is None or lon is None:
            continue
        if not (math.isfinite(float(juld)) and math.isfinite(float(lat)) and math.isfinite(float(lon))):
            continue
        # Hard no-future rule: a fix observed after `now` is not usable.
        observed = JULD_EPOCH + timedelta(days=float(juld))
        if observed > now:
            continue
        clean.append(
            {
                "juld": float(juld),
                "juld_iso": fix.get("juld_iso"),
                "lat": float(lat),
                "lon": float(lon),
                "cycle": fix.get("cycle"),
                "mc": fix.get("mc"),
                "pos_qc": fix.get("pos_qc"),
            }
        )
    clean.sort(key=lambda f: f["juld"])
    return clean, issues


def transitions_from_fixes(wmo: int, fixes: list[dict[str, Any]]) -> list[Transition]:
    """Consecutive QC'd cycle fixes -> displacement vectors (no future data)."""
    out: list[Transition] = []
    for previous, current in zip(fixes, fixes[1:]):
        days = current["juld"] - previous["juld"]
        if not (0 < days <= MAX_TRANSITION_DAYS):
            continue
        dlat, dlon = displacement_km(previous["lat"], previous["lon"], current["lat"], current["lon"])
        out.append(
            Transition(
                wmo=wmo,
                start_juld=previous["juld"],
                lat=previous["lat"],
                lon=previous["lon"],
                dlat_km=dlat,
                dlon_km=dlon,
                days=days,
                cycle_from=previous.get("cycle"),
                cycle_to=current.get("cycle"),
            )
        )
    return out


def build_float_features(
    wmo: int,
    row: dict[str, Any] | None,
    preset: dict[str, Any] | None,
    now: datetime,
) -> FloatFeatures:
    fixes, issues = _fixes_from_row(row, now)
    rtraj = (row or {}).get("rtraj") or {}
    aggregate = (row or {}).get("profile_aggregate") or {}
    interval, source, samples = profile_cycle.resolve_interval(
        aggregate.get("juld_intervals"), rtraj.get("cycle_intervals")
    )
    if source == profile_cycle.INTERVAL_SOURCE_DEFAULT and fixes:
        issues.append("observed cycle interval unavailable; 10-day fallback used")
    park = rtraj.get("park_pressure_dbar")
    phases = rtraj.get("phase_hours") or {}
    return FloatFeatures(
        wmo=wmo,
        platform_type=(preset or {}).get("platform_type"),
        transmission_type=(preset or {}).get("transmission_type"),
        interval_days=interval,
        interval_source=source,
        interval_samples=samples,
        park_pressure_dbar=float(park) if isinstance(park, (int, float)) else None,
        phase_hours={k: float(v) for k, v in phases.items() if isinstance(v, (int, float))},
        fixes=fixes,
        transitions=transitions_from_fixes(wmo, fixes),
        issues=issues,
    )


def build_fleet_features(
    rows: dict[str, dict[str, Any]],
    meta: dict[int, dict[str, Any]],
    now: datetime,
) -> dict[int, FloatFeatures]:
    out: dict[int, FloatFeatures] = {}
    for key, row in rows.items():
        if not str(key).isdigit():
            continue
        wmo = int(key)
        out[wmo] = build_float_features(wmo, row, meta.get(wmo), now)
    for wmo, preset in meta.items():
        out.setdefault(wmo, build_float_features(wmo, None, preset, now))
    return out


def fleet_transitions(features: dict[int, FloatFeatures]) -> list[Transition]:
    out: list[Transition] = []
    for item in features.values():
        out.extend(item.transitions)
    return out


def distance_to_last_fix(features: FloatFeatures, lat: float, lon: float) -> float | None:
    fix = features.last_fix
    if not fix or not features.has_position:
        return None
    return haversine_km(fix["lat"], fix["lon"], lat, lon)
