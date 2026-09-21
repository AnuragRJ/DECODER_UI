"""Stage-0 demonstration: what the recommended prediction output would look like.

Research / design artefact only — nothing here touches decoder-ui or src/argo_decoder.

It answers two questions the approval decision needs:
  1. For every fleet float, "as-if-live" prediction of its LAST observed cycle, made with the
     recommended Stage-0 recipe: blend w_prior = 0.2 for the point estimate, radii calibrated on
     OTHER floats and conditioned on the fallback rung actually used, then checked against what the
     float actually did.
  2. What the per-prediction output record looks like (point, target time, radii, method tag,
     fallback rung, calibration sample, provenance fingerprints) for three contrasting floats.

Design point this demo exists to test: radii must be conditioned on the rung (blend vs
last-displacement fallback), otherwise the 90 % circle is inflated for blend cases and too small for
fallback cases — see Table C10 in RESEARCH.md.

Usage: python stage0_demo.py <traj_dir> <out_dir> <presets.json>
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from backtest_baselines import dest, hav, load_fixes, region_of

MAX_GAP_DAYS = 30.0
PRIOR_LAG_DAYS = 2.0          # conservative GDAC delivery lag (Table C5)
W_PRIOR = 0.2                 # LOFO-selected point-estimate weight (Table C6)
RADII_MIN_N = 30              # minimum calibration sample before widening the fallback
DEMO_WMOS = (2902223, 2902086, 1902844)
JULD_EPOCH = datetime(1950, 1, 1)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def juld_to_iso(j: float) -> str:
    return (JULD_EPOCH + timedelta(days=float(j))).strftime("%Y-%m-%dT%H:%M:%SZ")


def step_km(a, b) -> tuple[float, float]:
    return ((b[2] - a[2]) * 110.574,
            (b[3] - a[3]) * 111.320 * np.cos(np.radians(a[2])))


def build_pool(tracks) -> np.ndarray:
    """Global displacement pool: rows = (wmo, t_start, lat, lon, dlat_km, dlon_km)."""
    rows = []
    for wmo, fixes in tracks.items():
        for a, b in zip(fixes, fixes[1:]):
            if 0 < b[1] - a[1] <= MAX_GAP_DAYS:
                rows.append((wmo, a[1], a[2], a[3], *step_km(a, b)))
    return np.array(rows, float)


def stage0_step(pool: np.ndarray, wmo: int, laN, loN, jN, dN, exclude_wmo: int | None):
    """(dlat_km, dlon_km, rung, n_neighbours) for one prediction."""
    sel = (pool[:, 0] != (exclude_wmo if exclude_wmo is not None else -1))
    sel &= (pool[:, 0] != wmo) | (exclude_wmo is None)
    sel &= (pool[:, 1] < jN - PRIOR_LAG_DAYS)
    sel &= np.abs(pool[:, 2] - laN) <= 2.0
    sel &= np.abs((pool[:, 3] - loN + 180) % 360 - 180) <= 2.0
    month = (jN % 365.25) / 30.44
    pmonth = (pool[:, 1] % 365.25) / 30.44
    dm = np.minimum(np.abs(month - pmonth), 12 - np.abs(month - pmonth))
    sel &= (dm <= 1.0) & np.isfinite(pool[:, 4])
    n = int(sel.sum())
    if n >= 5:
        pdlat, pdlon = float(np.median(pool[sel, 4])), float(np.median(pool[sel, 5]))
        return ((1 - W_PRIOR) * dN[0] + W_PRIOR * pdlat,
                (1 - W_PRIOR) * dN[1] + W_PRIOR * pdlon, "blend", n)
    return dN[0], dN[1], "last_displacement_fallback", n


def calibration_store(tracks, pool: np.ndarray, exclude_wmo: int):
    """Residuals of the Stage-0 predictor computed WITHOUT the target float, keyed by rung."""
    store = defaultdict(list)
    for wmo, fixes in tracks.items():
        if wmo == exclude_wmo:
            continue
        for i in range(2, len(fixes) - 1):
            _, jN, laN, loN = fixes[i]
            _, jP, laP, loP = fixes[i - 1]
            _, jP2, laP2, loP2 = fixes[i - 2]
            lead, gap = fixes[i + 1][1] - jN, jN - jP
            if not (0 < lead <= MAX_GAP_DAYS and 0 < gap <= MAX_GAP_DAYS):
                continue
            dN = ((laN - laP) * 110.574, (loN - loP) * 111.320 * np.cos(np.radians(laP)))
            dl, dn, rung, _ = stage0_step(pool, wmo, laN, loN, jN, dN, exclude_wmo)
            err = float(hav(fixes[i + 1][2], fixes[i + 1][3], *dest(laN, loN, dl, dn)))
            cls = "short (<=7 d)" if lead <= 7 else "decadal (~10 d)"
            reg = region_of(laN, loN)
            store[(reg, cls, rung)].append(err)
            store[(reg, "ALL", rung)].append(err)
            store[(reg, "ALL", "any")].append(err)
    return store


def radii_for(store, region: str, cls: str, rung: str):
    """Rung-conditioned radii with honest widening, returning (r50, r90, n, provenance)."""
    for key, how in (((region, cls, rung), "region+cycle_class+rung"),
                     ((region, "ALL", rung), "region+rung (cycle class pooled)"),
                     ((region, "ALL", "any"), "region, all rungs pooled")):
        vals = store.get(key) or []
        if len(vals) >= RADII_MIN_N:
            return (float(np.percentile(vals, 50)), float(np.percentile(vals, 90)),
                    len(vals), how)
    vals = [v for k, vs in store.items() if k[2] == "any" for v in vs]
    if not vals:
        return None, None, 0, "no calibration data"
    return float(np.percentile(vals, 50)), float(np.percentile(vals, 90)), len(vals), "all data pooled"


def main() -> int:
    traj_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    presets_path = Path(sys.argv[3])
    meta = {int(p["wmo"]): p for p in json.loads(presets_path.read_text())}

    tracks, hashes = {}, {}
    for path in sorted(traj_dir.glob("*_Rtraj.nc")):
        wmo = int(path.name.split("_")[0])
        fx = load_fixes(path)
        if len(fx) >= 4:
            tracks[wmo] = fx
            hashes[wmo] = sha256(path)
    pool = build_pool(tracks)
    print(f"floats with a scorable transition: {len(tracks)} | displacement pool rows: {len(pool)}")

    rows, records = [], {}
    for wmo in sorted(tracks):
        fixes = tracks[wmo]
        last, prev, prev2 = fixes[-1], fixes[-2], fixes[-3]
        jN, laN, loN = prev[1], prev[2], prev[3]
        gap = jN - prev2[1]
        dN = step_km(prev2, prev)
        dl, dn, rung, n_neigh = stage0_step(pool, wmo, laN, loN, jN, dN, exclude_wmo=None)
        plat, plon = (float(v) for v in dest(laN, loN, dl, dn))

        store = calibration_store(tracks, pool, exclude_wmo=wmo)
        cls = "short (<=7 d)" if gap <= 7 else "decadal (~10 d)"
        region = region_of(laN, loN)
        r50, r90, n_cal, how = radii_for(store, region, cls, rung)

        rec = {
            "wmo": wmo,
            "platform": meta.get(wmo, {}).get("platform_type"),
            "telemetry": meta.get(wmo, {}).get("transmission_type"),
            "issued_from_cycle": prev[0],
            "issued_from_fix_utc": juld_to_iso(jN),
            "last_fix_position": [round(laN, 4), round(loN, 4)],
            "last_cycle_step_km": [round(dN[0], 1), round(dN[1], 1)],
            "predicted_cycle": last[0],
            "target_time_utc": juld_to_iso(jN + gap),
            "target_time_basis": f"last observed interval {gap:.2f} d",
            "predicted_position": [round(plat, 4), round(plon, 4)],
            "region": region,
            "method": ("blend(last displacement, regional-seasonal prior), w_prior=0.2"
                       if rung == "blend" else "last displacement (prior unavailable)"),
            "fallback_rung": rung,
            "prior_neighbours_within_2deg_1month": n_neigh,
            "uncertainty": {"r50_km": None if r50 is None else round(r50, 1),
                            "r90_km": None if r90 is None else round(r90, 1),
                            "calibration_cases": n_cal,
                            "calibration_basis": how,
                            "calibrated_on": "all other floats (target float excluded)"},
            "provenance": {"trajectory_file": f"{wmo}_Rtraj.nc", "sha256": hashes[wmo],
                           "predictor": "stage0_blend_w0.2", "prior_lag_days": PRIOR_LAG_DAYS},
            "retrospective_check": {
                "actual_position": [round(last[2], 4), round(last[3], 4)],
                "actual_time_utc": juld_to_iso(last[1]),
                "error_km": round(float(hav(last[2], last[3], plat, plon)), 1),
                "time_error_days": round(abs(last[1] - (jN + gap)), 2),
                "inside_r50": None if r50 is None else bool(hav(last[2], last[3], plat, plon) <= r50),
                "inside_r90": None if r90 is None else bool(hav(last[2], last[3], plat, plon) <= r90),
            },
        }
        rows.append({"wmo": wmo, "region": region, "fallback_rung": rung,
                     "predicted_lat": rec["predicted_position"][0],
                     "predicted_lon": rec["predicted_position"][1],
                     "actual_lat": rec["retrospective_check"]["actual_position"][0],
                     "actual_lon": rec["retrospective_check"]["actual_position"][1],
                     "err_km": rec["retrospective_check"]["error_km"],
                     "r50_km": rec["uncertainty"]["r50_km"], "r90_km": rec["uncertainty"]["r90_km"],
                     "calibration_cases": n_cal, "calibration_basis": how,
                     "inside_r50": rec["retrospective_check"]["inside_r50"],
                     "inside_r90": rec["retrospective_check"]["inside_r90"],
                     "target_time_utc": rec["target_time_utc"],
                     "time_err_days": rec["retrospective_check"]["time_error_days"]})
        if wmo in DEMO_WMOS:
            records[wmo] = rec

    with (out_dir / "stage0-demo-as-if-live.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (out_dir / "stage0-demo-records.json").write_text(json.dumps(
        {"generated_utc": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
         "weight_on_prior": W_PRIOR, "prior_lag_days": PRIOR_LAG_DAYS,
         "note": ("research demonstration of the proposed output format; the predictor is NOT "
                  "implemented in the product"), "records": records}, indent=2))

    errs = np.array([r["err_km"] for r in rows])
    print(f"\nas-if-live demo: {len(rows)} floats (final observed cycle each)")
    print(f"  all      : median {np.median(errs):6.1f} km | mean {errs.mean():6.1f} | "
          f"p90 {np.percentile(errs, 90):6.1f} | <=50 km {100 * np.mean(errs <= 50):.0f}%")
    for rung in ("blend", "last_displacement_fallback"):
        sub = np.array([r["err_km"] for r in rows if r["fallback_rung"] == rung])
        if sub.size:
            print(f"  {rung:<24}: n={sub.size:>2} median {np.median(sub):6.1f} km | "
                  f"p90 {np.percentile(sub, 90):6.1f} | <=50 km {100 * np.mean(sub <= 50):.0f}%")
    for label in ("inside_r50", "inside_r90"):
        vals = [r[label] for r in rows if r[label] is not None]
        print(f"  containment {label.split('_')[1]:>3}: {100 * np.mean(vals):.1f}% of {len(vals)} floats")
    print(f"  median target-time error {np.median([r['time_err_days'] for r in rows]):.2f} d")
    for wmo, rec in records.items():
        u, rc = rec["uncertainty"], rec["retrospective_check"]
        print(f"\n  [{wmo}] {rec['method']}  ({rec['region']})")
        print(f"    from cycle {rec['issued_from_cycle']} at {rec['issued_from_fix_utc']}"
              f" -> predict cycle {rec['predicted_cycle']} at {rec['target_time_utc']}")
        print(f"    predicted {rec['predicted_position']}  +- {u['r50_km']}/{u['r90_km']} km (50/90)"
              f"  [n={u['calibration_cases']}, {u['calibration_basis']}]")
        print(f"    actual    {rc['actual_position']}  -> error {rc['error_km']} km, "
              f"inside r50={rc['inside_r50']} r90={rc['inside_r90']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
