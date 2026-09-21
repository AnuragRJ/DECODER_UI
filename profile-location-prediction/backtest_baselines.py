"""Leakage-safe hindcast of candidate Stage-0 "next profile location" predictors.

Research tooling only — this file lives outside decoder-ui and changes nothing in the
product. It reads public GDAC <WMO>_Rtraj.nc files (already downloaded to a scratch dir)
and scores, for every cycle N, the prediction of the surface position at cycle N+1 made
ONLY from information available at cycle N or earlier.

Predictors
  B0  persistence                     : x(N+1) = x(N)
  B1  last displacement (constant vel): x(N+1) = x(N) + [x(N) - x(N-1)]
  B2  mean of last 3 displacements    : x(N+1) = x(N) + mean(dx(N-2..N))
  B3  regional-seasonal drift prior   : x(N+1) = x(N) + mean displacement of all
                                        OTHER cycles within +-2 deg / +-1 month whose
                                        START time is strictly before t(N)   (no leakage)

Metrics: great-circle error (km) -> median / mean / RMSE / p90, hit rates at
25 / 50 / 100 km, skill vs B0, and empirical 50 % / 90 % containment radii.
Also scores the *time* prediction (next cycle time = t(N) + last observed interval).

Usage:  python backtest_baselines.py <traj_dir> <out_dir> [presets.json]
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import netCDF4
import numpy as np

R_EARTH_KM = 6371.0088
MAX_GAP_DAYS = 30.0


# ----------------------------------------------------------------------------- IO
def load_fixes(path: Path) -> list[tuple[int, float, float, float]]:
    """QC'd surface fixes: (cycle, juld, lat, lon), first fix per cycle, sorted."""
    ds = netCDF4.Dataset(path)
    try:
        cyc = np.ma.filled(np.asarray(ds.variables["CYCLE_NUMBER"][:], dtype=float), np.nan)
        juld = np.ma.filled(np.asarray(ds.variables["JULD"][:], dtype=float), np.nan)
        lat = np.ma.filled(np.asarray(ds.variables["LATITUDE"][:], dtype=float), np.nan)
        lon = np.ma.filled(np.asarray(ds.variables["LONGITUDE"][:], dtype=float), np.nan)
        qc = ds.variables["POSITION_QC"][:] if "POSITION_QC" in ds.variables else None
        mc = (np.ma.filled(np.asarray(ds.variables["MEASUREMENT_CODE"][:], dtype=float), np.nan)
              if "MEASUREMENT_CODE" in ds.variables else None)
    finally:
        ds.close()

    keep = np.isfinite(cyc) & np.isfinite(juld) & np.isfinite(lat) & np.isfinite(lon)
    if mc is not None:
        keep &= (mc == 703)  # satellite fix
    if qc is not None:
        def _qc(x):
            return x.decode(errors="replace").strip() if isinstance(x, (bytes, bytearray)) else str(x).strip()
        qc_str = np.array([_qc(x) for x in qc])
        keep &= np.isin(qc_str, ("1", "2"))
    keep &= (lat >= -90) & (lat <= 90) & (lon >= -180) & (lon <= 180)

    by_cycle: dict[int, tuple[float, float, float]] = {}
    for i in np.where(keep)[0]:
        c = int(cyc[i])
        if c not in by_cycle:  # first (earliest) fix of that cycle
            by_cycle[c] = (float(juld[i]), float(lat[i]), float(lon[i]))
    return [(c, *by_cycle[c]) for c in sorted(by_cycle)]


def hav(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R_EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def dest(lat, lon, dlat, dlon):
    """Great-circle destination given a displacement in km (deg-comp) — exact enough here."""
    return lat + dlat / 110.574, lon + dlon / (111.320 * np.cos(np.radians(lat)) + 1e-9)


def region_of(lat: float, lon: float) -> str:
    if lat > 0 and lon < 80:
        return "Arabian Sea (approx)"
    if lat > 0 and lon >= 80:
        return "Bay of Bengal (approx)"
    if -10 < lat <= 0:
        return "Equatorial Indian (10S-0)"
    if lat <= -10:
        return "South Indian Ocean"
    return "Other"


# ------------------------------------------------------------------- statistics
def summarize(err: np.ndarray) -> dict:
    err = err[np.isfinite(err)]
    if err.size == 0:
        return {}
    return {
        "n": int(err.size),
        "median_km": float(np.median(err)),
        "mean_km": float(np.mean(err)),
        "rmse_km": float(np.sqrt(np.mean(err ** 2))),
        "p90_km": float(np.percentile(err, 90)),
        "hit25_pct": float(100 * np.mean(err <= 25)),
        "hit50_pct": float(100 * np.mean(err <= 50)),
        "hit100_pct": float(100 * np.mean(err <= 100)),
        "r50_km": float(np.percentile(err, 50)),
        "r90_km": float(np.percentile(err, 90)),
    }


def main() -> int:
    traj_dir = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    presets_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    out_dir.mkdir(parents=True, exist_ok=True)

    meta: dict[int, dict] = {}
    if presets_path and presets_path.exists():
        for p in json.loads(presets_path.read_text()):
            meta[int(p["wmo"])] = {
                "platform_type": p.get("platform_type"),
                "transmission_type": p.get("transmission_type"),
            }

    tracks: dict[int, list] = {}
    for path in sorted(traj_dir.glob("*_Rtraj.nc")):
        wmo = int(path.name.split("_")[0])
        try:
            fixes = load_fixes(path)
        except Exception as exc:  # keep the corpus honest: report, never guess
            print(f"  ! {wmo}: unreadable ({type(exc).__name__}: {exc})")
            continue
        if len(fixes) >= 3:
            tracks[wmo] = fixes
    print(f"floats with ≥3 QC'd cycles: {len(tracks)}")

    # prior pool for B3: displacement vectors from cycle i -> i+1, keyed by start time
    pool = []  # (t_start, lat, lon, dlat_km, dlon_km)
    for fixes in tracks.values():
        for a, b in zip(fixes, fixes[1:]):
            (_, j0, la0, lo0), (_, j1, la1, lo1) = a, b
            dt = j1 - j0
            if not (0 < dt <= MAX_GAP_DAYS):
                continue
            if not (np.isfinite(la0) and np.isfinite(lo0) and np.isfinite(la1) and np.isfinite(lo1)):
                continue
            dlat = (la1 - la0) * 110.574
            dlon = (lo1 - lo0) * 111.320 * np.cos(np.radians(la0))
            pool.append((j0, la0, lo0, dlat, dlon))
    pool_np = np.array(pool, dtype=float) if pool else np.zeros((0, 5))
    print(f"prior-cycle displacement pool: {len(pool)}")

    rows: list[dict] = []
    for wmo, fixes in sorted(tracks.items()):
        info = meta.get(wmo, {})
        for i in range(2, len(fixes) - 1):
            (_, jN, laN, loN) = fixes[i]
            (_, jP, laP, loP) = fixes[i - 1]     # cycle N-1
            (_, jF, laF, loF) = fixes[i + 1]     # actual next cycle (label only)
            (_, jPrev, _, _) = fixes[i - 2]

            lead = jF - jN
            gap = jN - jP
            if not (0 < lead <= MAX_GAP_DAYS and 0 < gap <= MAX_GAP_DAYS):
                continue

            preds: dict[str, tuple[float, float]] = {}
            d_lat_N = (laN - laP) * 110.574
            d_lon_N = (loN - loP) * 111.320 * np.cos(np.radians(laP))
            preds["B0_persistence"] = (laN, loN)
            preds["B1_last_displacement"] = dest(laN, loN, d_lat_N, d_lon_N)

            d3 = []
            for a, b in ((fixes[i - 2], fixes[i - 1]), (fixes[i - 1], fixes[i])):
                d3.append(((b[2] - a[2]) * 110.574,
                           (b[3] - a[3]) * 111.320 * np.cos(np.radians(a[2]))))
            m_lat, m_lon = np.mean([d[0] for d in d3]), np.mean([d[1] for d in d3])
            preds["B2_mean3_displacement"] = dest(laN, loN, m_lat, m_lon)

            prior_dlat = prior_dlon = None
            if pool_np.shape[0]:
                sel = (pool_np[:, 0] < jN)                       # strictly before t(N)
                sel &= np.abs(pool_np[:, 1] - laN) <= 2.0
                dlon_box = np.abs((pool_np[:, 2] - loN + 180) % 360 - 180) <= 2.0
                month = (jN % 365.25) / 30.44
                pmonth = (pool_np[:, 0] % 365.25) / 30.44
                dmonth = np.minimum(np.abs(month - pmonth), 12 - np.abs(month - pmonth))
                sel &= dlon_box & (dmonth <= 1.0) & ~np.isnan(pool_np[:, 3])
                if sel.sum() >= 5:
                    prior_dlat = float(np.median(pool_np[sel, 3]))
                    prior_dlon = float(np.median(pool_np[sel, 4]))
                    preds["B3_regional_seasonal_prior"] = dest(laN, loN, prior_dlat, prior_dlon)
                    preds["B4_half_prior"] = dest(laN, loN, 0.5 * prior_dlat, 0.5 * prior_dlon)
                    preds["B5_blend_lastdispl_prior"] = dest(
                        laN, loN, 0.5 * d_lat_N + 0.5 * prior_dlat, 0.5 * d_lon_N + 0.5 * prior_dlon
                    )

            strata = {
                "telemetry": info.get("transmission_type") or "unknown",
                "platform": info.get("platform_type") or "unknown",
                "region": region_of(laN, loN),
                "cycle_class": "short (≤7 d)" if lead <= 7 else "decadal (≈10 d)",
            }
            for name, (pla, plo) in preds.items():
                rows.append({
                    "wmo": wmo, "cycle": fixes[i][0], "predictor": name,
                    "err_km": float(hav(laF, loF, pla, plo)),
                    "time_err_days": float(abs(jF - (jN + gap))),
                    **strata,
                })

    if not rows:
        print("no prediction cases produced")
        return 1

    def write_grouped(group_keys: list[str], fname: str) -> None:
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in rows:
            key = ("ALL",) if not group_keys else tuple(r[k] for k in group_keys)
            groups[key].append(r)
        base_med: dict[tuple, float] = {}
        for g, rs in groups.items():
            b0 = [r["err_km"] for r in rs if r["predictor"] == "B0_persistence"]
            if b0:
                base_med[g] = float(np.median(b0))
        with (out_dir / fname).open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(group_keys + ["predictor", "n", "median_km", "mean_km", "rmse_km", "p90_km",
                                     "hit25_pct", "hit50_pct", "hit100_pct",
                                     "r50_km", "r90_km", "skill_vs_B0_median_pct",
                                     "median_time_err_days"])
            for g in sorted(groups, key=lambda x: tuple(str(v) for v in x)):
                rs = groups[g]
                for pred in sorted({r["predictor"] for r in rs}):
                    _ = g
                    sub = [r for r in rs if r["predictor"] == pred]
                    _ = pred
                    s = summarize(np.array([r["err_km"] for r in sub]))
                    if not s:
                        continue
                    bm = base_med.get(g)
                    skill = "" if (bm in (None, 0)) else f"{100 * (1 - s['median_km'] / bm):.1f}"
                    terr = float(np.median([r["time_err_days"] for r in sub]))
                    w.writerow(([] if not group_keys else list(g)) + [pred, s["n"], f"{s['median_km']:.1f}", f"{s['mean_km']:.1f}",
                                          f"{s['rmse_km']:.1f}", f"{s['p90_km']:.1f}",
                                          f"{s['hit25_pct']:.1f}", f"{s['hit50_pct']:.1f}",
                                          f"{s['hit100_pct']:.1f}", f"{s['r50_km']:.1f}",
                                          f"{s['r90_km']:.1f}", skill, f"{terr:.2f}"])

    write_grouped([], "baseline-skill-overall.csv")

    # like-for-like: keep only cases where all predictors produced a value
    by_case: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by_case[(r["wmo"], r["cycle"])].append(r)
    all_preds = sorted({r["predictor"] for r in rows})
    common = [r for k, rs in by_case.items()
              if {x["predictor"] for x in rs} == set(all_preds) for r in rs]
    keep_rows = rows
    rows = common
    write_grouped([], "baseline-skill-common-subset.csv")
    rows = keep_rows
    write_grouped(["region"], "baseline-skill-by-region.csv")
    write_grouped(["telemetry"], "baseline-skill-by-telemetry.csv")
    write_grouped(["cycle_class"], "baseline-skill-by-cycle-class.csv")
    write_grouped(["wmo"], "baseline-skill-by-float.csv")

    print(f"cases: {len(rows)}   floats: {len({r['wmo'] for r in rows})}")
    with (out_dir / "baseline-skill-overall.csv").open() as fh:
        print(fh.read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
