"""Great-circle geometry shared by the prediction engine and its validation.

The displacement convention is the one used by the validation harness, so a
radius calibrated on the historical corpus means the same thing at serve time:
``dlat_km`` is a northward distance and ``dlon_km`` an eastward distance at the
reference latitude.
"""

from __future__ import annotations

import math

R_EARTH_KM = 6371.0088
KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON_EQ = 111.320


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin((p2 - p1) / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * R_EARTH_KM * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def displacement_km(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    """(dlat_km, dlon_km) from point 1 to point 2."""
    return (
        (lat2 - lat1) * KM_PER_DEG_LAT,
        (lon2 - lon1) * KM_PER_DEG_LON_EQ * math.cos(math.radians(lat1)),
    )


def destination(lat: float, lon: float, dlat_km: float, dlon_km: float) -> tuple[float, float]:
    """Inverse of :func:`displacement_km`; wraps longitude and clamps latitude."""
    new_lat = lat + dlat_km / KM_PER_DEG_LAT
    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-9:
        new_lon = lon
    else:
        new_lon = lon + dlon_km / (KM_PER_DEG_LON_EQ * cos_lat)
    new_lat = max(-90.0, min(90.0, new_lat))
    new_lon = (new_lon + 180.0) % 360.0 - 180.0
    return new_lat, new_lon


def speed_km_per_day(dlat_km: float, dlon_km: float, days: float) -> float:
    if not math.isfinite(days) or days <= 0:
        return 0.0
    return math.hypot(dlat_km, dlon_km) / days


def add_vectors(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] + b[0], a[1] + b[1])


def scale_vector(a: tuple[float, float], factor: float) -> tuple[float, float]:
    return (a[0] * factor, a[1] * factor)


def mean_vector(vectors: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not vectors:
        return None
    return (
        sum(v[0] for v in vectors) / len(vectors),
        sum(v[1] for v in vectors) / len(vectors),
    )


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return 0.5 * (ordered[middle - 1] + ordered[middle])
