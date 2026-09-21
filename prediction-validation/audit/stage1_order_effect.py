"""Read-only audit: effect of enforcing chronological fix order in the harness.

`prediction.validate.load_fixes` documents "chronological" but returned rows in
file order. Two INCOIS trajectory files (1902844, 2904082) contain a long silence
followed by measurement rows that are not in time order, which made one-cycle
labels land on stale duplicate rows. This script measures how much that bug moved
the Stage-0 replay numbers before the harness was corrected.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path[:0] = ["service", "src"]

import netCDF4  # noqa: E402
import numpy as np  # noqa: E402

from prediction.validate import SATELLITE_FIX_MC  # noqa: E402
from prediction.validate import (  # noqa: E402
    load_fixes, transitions_of, interval_days_for, displacement_km, destination,
    haversine_km, summarize,
)


def load_fixes_file_order(path: Path) -> list[dict]:
    """The pre-correction loader: first row per cycle number, in file order.

    Reproduces exactly what `load_fixes` returned before the Stage-1 ordering fix,
    so the before/after evidence stays reproducible without reverting the fix.
    """
    ds = netCDF4.Dataset(path)
    try:
        cyc = np.ma.filled(np.asarray(ds.variables["CYCLE_NUMBER"][:], dtype=float), np.nan)
        juld = np.ma.filled(np.asarray(ds.variables["JULD"][:], dtype=float), np.nan)
        lat = np.ma.filled(np.asarray(ds.variables["LATITUDE"][:], dtype=float), np.nan)
        lon = np.ma.filled(np.asarray(ds.variables["LONGITUDE"][:], dtype=float), np.nan)
        qc = ds.variables["POSITION_QC"][:] if "POSITION_QC" in ds.variables else None
        mc = (
            np.ma.filled(np.asarray(ds.variables["MEASUREMENT_CODE"][:], dtype=float), np.nan)
            if "MEASUREMENT_CODE" in ds.variables else None
        )
    finally:
        ds.close()

    def text(value) -> str:
        return value.decode(errors="replace").strip() if isinstance(value, (bytes, bytearray)) else str(value).strip()

    keep = np.isfinite(cyc) & np.isfinite(juld) & np.isfinite(lat) & np.isfinite(lon)
    if mc is not None:
        keep &= mc == SATELLITE_FIX_MC
    if qc is not None:
        keep &= np.isin(np.array([text(v) for v in qc]), ("1", "2"))
    keep &= (lat >= -90) & (lat <= 90) & (lon >= -180) & (lon <= 180) & (juld < 90000)

    by_cycle: dict[int, dict] = {}
    for i in np.where(keep)[0]:
        cycle = int(cyc[i])
        if cycle not in by_cycle:
            by_cycle[cycle] = {"juld": float(juld[i]), "lat": float(lat[i]),
                               "lon": float(lon[i]), "cycle": cycle}
    return [by_cycle[c] for c in sorted(by_cycle)]

CORPUS = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/argotraj2")


def replay(fixes_by_float, sorted_order: bool):
    errors = []
    out_of_order_floats = []
    for wmo, fixes in sorted(fixes_by_float.items()):
        juld = [f["juld"] for f in fixes]
        if juld != sorted(juld):
            out_of_order_floats.append(wmo)
        if sorted_order:
            fixes = sorted(fixes, key=lambda f: f["juld"])
        own = transitions_of(wmo, fixes)
        for i in range(2, len(fixes) - 1):
            interval, _ = interval_days_for(own, fixes[i]["juld"])
            nxt = fixes[i + 1]
            d = displacement_km(fixes[i - 1]["lat"], fixes[i - 1]["lon"], fixes[i]["lat"], fixes[i]["lon"])
            lat, lon = destination(fixes[i]["lat"], fixes[i]["lon"], *d)
            errors.append(haversine_km(nxt["lat"], nxt["lon"], lat, lon))
    return summarize(errors), out_of_order_floats


def main() -> int:
    fixes_by_float = {}
    for path in sorted(CORPUS.glob("*_Rtraj.nc")):
        wmo = int(path.name.split("_")[0])
        try:
            fixes = load_fixes_file_order(path)
        except Exception:
            continue
        if len(fixes) >= 4:
            fixes_by_float[wmo] = fixes

    unsorted_metrics, flagged = replay(fixes_by_float, sorted_order=False)
    sorted_metrics = replay(
        {wmo: load_fixes(CORPUS / f"{wmo}_Rtraj.nc") for wmo in fixes_by_float},
        sorted_order=True,
    )[0]
    payload = {
        "corpus": str(CORPUS),
        "floats": len(fixes_by_float),
        "floats_with_out_of_order_rows": flagged,
        "stage0_replay_file_order": unsorted_metrics,
        "stage0_replay_chronological": sorted_metrics,
        "delta_median_km": round(sorted_metrics["median_km"] - unsorted_metrics["median_km"], 3),
        "delta_p90_km": round(sorted_metrics["p90_km"] - unsorted_metrics["p90_km"], 3),
        "delta_rmse_km": round(sorted_metrics["rmse_km"] - unsorted_metrics["rmse_km"], 3),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
