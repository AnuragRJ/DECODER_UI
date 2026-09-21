"""Regional / seasonal drift prior.

Two interchangeable sources, both leakage-safe by construction:

* **fleet pool** — the displacement vectors of the *other* floats in the live
  cache (bounded ring of recent cycles). A prediction may only use transitions
  that started before the target float's last fix (minus a delivery lag), so a
  prior can never contain the answer it is asked to predict.
* **calibration grid** — a sparse 2 deg x month median-drift table produced by
  ``python -m prediction.validate`` over the historical corpus. Used only when
  the live pool is too thin, and only through the same neighbour rules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from prediction.features import Transition

#: Neighbourhood definition of the validated prior (unchanged from the
#: hindcast study so the calibration radii keep their meaning).
PRIOR_RADIUS_DEG = 2.0
PRIOR_MONTHS = 1.0
PRIOR_MIN_NEIGHBOURS = 5
#: Conservative GDAC delivery lag: a transition is only usable once it is very
#: likely to have been published (measured cost: 21.5 -> 21.6 km median).
PRIOR_LAG_DAYS = 2.0
GRID_CELL_DEG = 2.0
GRID_MIN_COUNT = 5


@dataclass(frozen=True)
class PriorResult:
    dlat_km: float
    dlon_km: float
    neighbours: int
    basis: str


def _month_of_day(juld: float) -> float:
    """Fractional month index (0-12) of a JULD value."""
    return (juld % 365.25) / 30.44


def _month_distance(a: float, b: float) -> float:
    diff = abs(a - b)
    return min(diff, 12.0 - diff)


def neighbourhood_prior(
    pool: list[Transition],
    *,
    exclude_wmo: int | None,
    lat: float,
    lon: float,
    juld: float,
    radius_deg: float = PRIOR_RADIUS_DEG,
    months: float = PRIOR_MONTHS,
    min_neighbours: int = PRIOR_MIN_NEIGHBOURS,
    lag_days: float = PRIOR_LAG_DAYS,
) -> PriorResult | None:
    """Median displacement of recent neighbouring cycles, or ``None``."""
    month = _month_of_day(juld)
    selected: list[Transition] = []
    for item in pool:
        if exclude_wmo is not None and item.wmo == exclude_wmo:
            continue
        if item.start_juld >= juld - lag_days:  # strictly earlier, delivery-lagged
            continue
        if abs(item.lat - lat) > radius_deg:
            continue
        lon_delta = abs((item.lon - lon + 180.0) % 360.0 - 180.0)
        if lon_delta > radius_deg:
            continue
        if _month_distance(month, _month_of_day(item.start_juld)) > months:
            continue
        selected.append(item)
    if len(selected) < min_neighbours:
        return None
    ordered_lat = sorted(item.dlat_km for item in selected)
    ordered_lon = sorted(item.dlon_km for item in selected)
    middle = len(selected) // 2
    if len(selected) % 2:
        dlat, dlon = ordered_lat[middle], ordered_lon[middle]
    else:
        dlat = 0.5 * (ordered_lat[middle - 1] + ordered_lat[middle])
        dlon = 0.5 * (ordered_lon[middle - 1] + ordered_lon[middle])
    return PriorResult(dlat, dlon, len(selected), "fleet pool (neighbouring recent cycles)")


def grid_cell_keys(lat: float, lon: float, juld: float, cell_deg: float = GRID_CELL_DEG) -> list[str]:
    """Sparse grid keys for a position/time, nearest cell first.

    Key format: ``<lat_index>_<lon_index>_<month>`` with integer indices, which
    keeps the calibration artefact small and readable.
    """
    lat_index = int(math.floor(lat / cell_deg))
    lon_index = int(math.floor(lon / cell_deg))
    month = int((_month_of_day(juld)) % 12) + 1
    keys: list[str] = []
    for dlat in (0, -1, 1):
        for dlon in (0, -1, 1):
            keys.append(f"{lat_index + dlat}_{lon_index + dlon}_{month}")
    return keys


def grid_prior(
    cells: dict[str, Any] | None,
    *,
    lat: float,
    lon: float,
    juld: float,
    cell_deg: float = GRID_CELL_DEG,
    min_count: int = GRID_MIN_COUNT,
) -> PriorResult | None:
    """Median drift of the calibration grid cell (nearest neighbours first)."""
    if not cells:
        return None
    for rank, key in enumerate(grid_cell_keys(lat, lon, juld, cell_deg)):
        entry = cells.get(key)
        if not entry:
            continue
        try:
            dlat, dlon, count = float(entry[0]), float(entry[1]), int(entry[2])
        except (TypeError, ValueError, IndexError):
            continue
        if count < min_count:
            continue
        basis = "calibration grid (regional/seasonal prior)" if rank == 0 else (
            "calibration grid (neighbouring cell)"
        )
        return PriorResult(dlat, dlon, count, basis)
    return None
