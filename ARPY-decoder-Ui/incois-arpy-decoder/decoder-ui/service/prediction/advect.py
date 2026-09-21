"""Lagrangian advection of a float through one cycle (physics rung).

Used only when a current provider is actually available. The integration splits
the cycle into the phases the float itself reports:

    last fix -> descent -> parking drift -> ascent -> surface/transmission window

Phase durations come from the float's own ``_Rtraj.nc`` phase times when
available, otherwise from its observed interval minus documented defaults. Depth
comes from the observed/representative parking pressure.

The result is an *ensemble*, not a single track: start position, parking depth,
phase durations and the current field itself are perturbed, and a sub-grid
random walk sized by ``sigma_km_per_day`` represents unresolved motion. With no
ensemble members the function refuses rather than returning a confident point.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from prediction.currents import CurrentProvider
from prediction.features import FloatFeatures
from prediction.geometry import destination, haversine_km, mean_vector

MS_TO_KM_DAY = 86.4  # 1 m/s = 86.4 km/day
DEFAULT_DESCENT_H = 5.0
DEFAULT_ASCENT_H = 5.0
DEFAULT_SURFACE_H = 6.0


@dataclass
class AdvectionResult:
    lat: float
    lon: float
    spread_km: list[float]
    members: int
    basis: str


def phase_plan(features: FloatFeatures) -> dict[str, float]:
    """Phase durations (hours) from the float's own cycle, else documented defaults."""
    phase = dict(features.phase_hours or {})
    descent = phase.get("descent_h") or DEFAULT_DESCENT_H
    ascent = phase.get("ascent_h") or DEFAULT_ASCENT_H
    surface = phase.get("surface_h") or DEFAULT_SURFACE_H
    interval_h = max(1.0, float(features.interval_days) * 24.0)
    park = interval_h - descent - ascent - surface
    if "park_h" in phase and phase["park_h"] > 0:
        park = phase["park_h"]
    if park < 0:
        park = max(1.0, interval_h * 0.6)
    return {"descent_h": descent, "park_h": park, "ascent_h": ascent, "surface_h": surface}


def _depth_at(offsets: dict[str, float], park_depth: float, elapsed_h: float) -> float:
    if elapsed_h < offsets["descent_end"]:
        fraction = elapsed_h / max(1e-6, offsets["descent_end"])
        return park_depth * fraction
    if elapsed_h < offsets["park_end"]:
        return park_depth
    if elapsed_h < offsets["ascent_end"]:
        fraction = (elapsed_h - offsets["park_end"]) / max(1e-6, offsets["ascent_end"] - offsets["park_end"])
        return park_depth * (1.0 - fraction)
    return 0.0


def advect_ensemble(
    features: FloatFeatures,
    provider: CurrentProvider,
    *,
    members: int = 100,
    step_hours: float = 6.0,
    park_depth_dbar: float | None = None,
    position_jitter_km: float = 3.0,
    depth_jitter_dbar: float = 50.0,
    duration_jitter: float = 0.05,
    sigma_km_per_day: float = 5.0,
    start_lat: float | None = None,
    start_lon: float | None = None,
    start_juld: float | None = None,
    seed: int = 20260921,
) -> AdvectionResult | None:
    """Ensemble forecast of the next surfacing position, or None if impossible."""
    if not provider.available():
        return None
    if not features.has_position or members <= 0:
        return None
    fix = features.last_fix or {}
    lat0 = float(fix["lat"] if start_lat is None else start_lat)
    lon0 = float(fix["lon"] if start_lon is None else start_lon)
    juld0 = float(fix["juld"] if start_juld is None else start_juld)
    park = float(park_depth_dbar if park_depth_dbar is not None else (features.park_pressure_dbar or 1000.0))
    plan = phase_plan(features)
    rng = random.Random(seed)

    ends: list[tuple[float, float]] = []
    for _ in range(members):
        jitter_lat, jitter_lon = destination(lat0, lon0, rng.uniform(-position_jitter_km, position_jitter_km),
                                             rng.uniform(-position_jitter_km, position_jitter_km))
        member_park = max(50.0, park + rng.uniform(-depth_jitter_dbar, depth_jitter_dbar))
        total_h = (plan["descent_h"] + plan["park_h"] + plan["ascent_h"] + plan["surface_h"])
        total_h *= 1.0 + rng.uniform(-duration_jitter, duration_jitter)
        offsets = {
            "descent_end": plan["descent_h"] * (1.0 + rng.uniform(-duration_jitter, duration_jitter)),
            "park_end": 0.0,
            "ascent_end": 0.0,
        }
        offsets["park_end"] = offsets["descent_end"] + plan["park_h"] * (1.0 + rng.uniform(-duration_jitter, duration_jitter))
        offsets["ascent_end"] = min(total_h, offsets["park_end"] + plan["ascent_h"] * (1.0 + rng.uniform(-duration_jitter, duration_jitter)))
        lat, lon = jitter_lat, jitter_lon
        elapsed = 0.0
        while elapsed < total_h - 1e-9:
            depth = _depth_at(offsets, member_park, elapsed)
            try:
                u, v = provider.velocity(lat, lon, depth, juld0 + elapsed / 24.0)
            except Exception:
                return None
            dlat = v * MS_TO_KM_DAY * (step_hours / 24.0)
            dlon = u * MS_TO_KM_DAY * (step_hours / 24.0)
            random_walk = sigma_km_per_day * (step_hours / 24.0) ** 0.5
            dlat += rng.gauss(0.0, random_walk)
            dlon += rng.gauss(0.0, random_walk)
            lat, lon = destination(lat, lon, dlat, dlon)
            elapsed += step_hours
        ends.append((lat, lon))

    centre = mean_vector(ends)
    if centre is None:
        return None
    spread = [haversine_km(lat, lon, centre[0], centre[1]) for lat, lon in ends]
    return AdvectionResult(
        lat=centre[0],
        lon=centre[1],
        spread_km=spread,
        members=members,
        basis=f"Lagrangian ensemble ({members} members, {provider.name}, park {park:.0f} dbar)",
    )
