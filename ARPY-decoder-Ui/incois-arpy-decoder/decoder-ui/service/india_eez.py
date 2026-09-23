"""Indian EEZ geometry and point-in-polygon classification for float monitoring.

Consumes the canonical reference geometry (Marine Regions World EEZ v12,
2023-10-25 -- Indian features MRGID 8480 + MRGID 8333, EPSG:4326) located at
decoder-ui/data/geography/india_eez.geojson, matching the frontend Float Status map.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("india_eez")

EEZ_SOURCE = "Marine Regions World EEZ v12 (2023-10-25) via https://doi.org/10.5281/zenodo.16314546 (MRGID 8480, 8333)"
POSITION_BASIS = "Latest verified float position"

_CACHED_POLYGONS: list[list[list[list[float]]]] | None = None


def _find_eez_geojson() -> Path:
    """Locate the india_eez.geojson file dynamically."""
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "data" / "geography" / "india_eez.geojson",
        here.parent.parent / "decoder-ui" / "data" / "geography" / "india_eez.geojson",
        Path.cwd() / "decoder-ui" / "data" / "geography" / "india_eez.geojson",
        Path.cwd() / "ARPY-decoder-Ui" / "incois-arpy-decoder" / "decoder-ui" / "data" / "geography" / "india_eez.geojson",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError("Canonical india_eez.geojson not found in known locations")


def load_eez_polygons() -> list[list[list[list[float]]]]:
    """Load and parse polygon rings from india_eez.geojson."""
    global _CACHED_POLYGONS
    if _CACHED_POLYGONS is not None:
        return _CACHED_POLYGONS

    geojson_path = _find_eez_geojson()
    with open(geojson_path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    polygons: list[list[list[list[float]]]] = []
    features = doc.get("features", [])
    for feat in features:
        geom = feat.get("geometry", {})
        gtype = geom.get("type")
        coords = geom.get("coordinates", [])
        if gtype == "Polygon":
            polygons.append(coords)
        elif gtype == "MultiPolygon":
            for poly in coords:
                polygons.append(poly)

    _CACHED_POLYGONS = polygons
    return _CACHED_POLYGONS


def _ring_contains(ring: list[list[float]], lon: float, lat: float) -> bool:
    """Ray-casting point-in-ring algorithm using the even-odd rule."""
    inside = False
    n = len(ring)
    if n < 4:
        return False
    j = n - 2
    for i in range(n - 1):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (yj != yi):
            intersect_x = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < intersect_x:
                inside = not inside
        j = i
    return inside


def point_in_india_eez(lon: float | None, lat: float | None) -> bool:
    """Check if (lon, lat) is strictly inside the Indian EEZ (exterior ring minus holes)."""
    if lon is None or lat is None:
        return False
    try:
        lon_f = float(lon)
        lat_f = float(lat)
    except (ValueError, TypeError):
        return False

    if not math.isfinite(lon_f) or not math.isfinite(lat_f):
        return False
    if abs(lon_f) > 180 or abs(lat_f) > 90:
        return False

    polygons = load_eez_polygons()
    for poly in polygons:
        if not poly:
            continue
        exterior = poly[0]
        if _ring_contains(exterior, lon_f, lat_f):
            in_hole = False
            for hole in poly[1:]:
                if _ring_contains(hole, lon_f, lat_f):
                    in_hole = True
                    break
            if not in_hole:
                return True
    return False


def get_monitored_floats_inside_eez(
    monitored_floats: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int, str]:
    """Identify floats from the monitored fleet whose latest verified position is inside Indian EEZ.

    Strictly uses verified/QC-valid positions (never predicted positions).
    """
    snapshot_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if monitored_floats is None:
        try:
            from fleet_status import fleet_sync
            payload = fleet_sync.payload()
            monitored_floats = payload.get("floats", [])
        except Exception as e:
            logger.warning("Could not load fleet_sync payload: %s", e)
            monitored_floats = []

    total_monitored = len(monitored_floats)
    inside_floats: list[dict[str, Any]] = []

    for f in monitored_floats:
        wmo = f.get("wmo")
        lat = f.get("lat")
        lon = f.get("lon")

        # Fallback to latest_profile verified coordinates if top-level is absent
        if lat is None or lon is None:
            lp = f.get("latest_profile") or {}
            lat = lp.get("lat")
            lon = lp.get("lon")

        # STRICTLY ignore predicted coordinates: only verified/QC-valid float positions
        if lat is not None and lon is not None and point_in_india_eez(lon, lat):
            last_date = f.get("last_profile_iso") or "N/A"
            if "T" in str(last_date):
                last_date = str(last_date).replace("T", " ").replace("+00:00", " UTC")

            inside_floats.append(
                {
                    "wmo": wmo,
                    "float_type": f.get("float_type") or f.get("platform_type") or "APEX",
                    "lat": round(float(lat), 4),
                    "lon": round(float(lon), 4),
                    "last_profile_date": last_date,
                    "data_status": f.get("data_status") or "ACTIVE",
                }
            )

    return inside_floats, total_monitored, snapshot_ts


def get_batch_floats_inside_eez(
    batch: Any,
    monitored_floats: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int, str]:
    """Identify floats from the current batch whose decoded position is inside Indian EEZ.

    Strictly uses real decoded cycle positions from the batch runs, never predictions.
    If monitored_floats is provided (e.g. in unit tests), evaluates those directly.

    Returns:
        (floats_inside, total_monitored, snapshot_timestamp_utc_iso)
    """
    snapshot_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # If explicit floats list is provided (e.g. testing), evaluate directly
    if monitored_floats is not None:
        return get_monitored_floats_inside_eez(monitored_floats)

    items = getattr(batch, "items", []) or []
    total_monitored = getattr(batch, "total_floats", None) or len(items) or 34

    # Lookup float metadata from fleet_sync
    floats_map: dict[int, dict[str, Any]] = {}
    try:
        from fleet_status import fleet_sync
        payload = fleet_sync.payload()
        for f in payload.get("floats", []):
            if "wmo" in f:
                floats_map[f["wmo"]] = f
    except Exception as e:
        logger.warning("Could not load fleet_sync payload: %s", e)

    from event_bus import bus

    inside_floats: list[dict[str, Any]] = []

    for item in items:
        wmo = getattr(item, "wmo", None)
        if wmo is None and isinstance(item, dict):
            wmo = item.get("wmo")
        run_id = getattr(item, "run_id", None)
        if run_id is None and isinstance(item, dict):
            run_id = item.get("run_id")

        lat, lon, date_str = None, None, None
        run = bus.get_run(run_id) if run_id else None
        if run and getattr(run, "cycles", None):
            valid_cycles = [
                c for c in run.cycles
                if getattr(c, "latitude", None) is not None
                and getattr(c, "longitude", None) is not None
                and abs(c.latitude) <= 90
                and abs(c.longitude) <= 180
            ]
            if valid_cycles:
                latest = sorted(valid_cycles, key=lambda c: getattr(c, "cycle_number", 0))[-1]
                lat = latest.latitude
                lon = latest.longitude
                if getattr(latest, "date", None):
                    date_str = latest.date.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Fallback to fleet_sync position ONLY if the float was completed in the batch
        item_status = getattr(item, "status", None)
        if hasattr(item_status, "value"):
            item_status = item_status.value
        if (lat is None or lon is None) and str(item_status).lower() in ("completed", "active"):
            f_info = floats_map.get(wmo, {})
            lat = f_info.get("lat")
            lon = f_info.get("lon")
            date_str = f_info.get("last_profile_iso")

        if lat is not None and lon is not None and point_in_india_eez(lon, lat):
            f_info = floats_map.get(wmo, {})
            last_date = date_str or f_info.get("last_profile_iso") or "N/A"
            if "T" in str(last_date):
                last_date = str(last_date).replace("T", " ").replace("+00:00", " UTC")

            platform = (
                getattr(item, "platform_type", None)
                or (item.get("platform_type") if isinstance(item, dict) else None)
                or f_info.get("float_type")
                or "APEX"
            )

            inside_floats.append(
                {
                    "wmo": wmo,
                    "float_type": platform,
                    "lat": round(float(lat), 4),
                    "lon": round(float(lon), 4),
                    "last_profile_date": last_date,
                    "data_status": f_info.get("data_status") or "COMPLETED",
                }
            )

    return inside_floats, total_monitored, snapshot_ts
