"""Robustness / validation layer on top of backtest_baselines.py (research tooling only).

Adds, for the Stage-0 "next profile location" predictors:
  A. delivery-lag sensitivity  : prior pool truncated to t < t(N) - L days (L = 0, 2, 5, 7)
  B. paired bootstrap CIs      : median / p90 error differences, B5 vs B0 / B1, B0 vs B1
  C. blend-weight validation   : w swept, selected leave-one-float-out (LOFO)
  D. calibration generalization: r50/r90 from OTHER floats, coverage measured on held-out float
  E. horizon decay             : same predictors applied 1, 2, 3 cycles ahead
  F. float diagnosis           : why a given WMO produced no cases

Usage: python backtest_robustness.py <traj_dir> <out_dir> [presets.json]
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from backtest_baselines import R_EARTH_KM, dest, hav, load_fixes, region_of

MAX_GAP_DAYS = 30.0
WEIGHTS = [round(0.1 * k, 1) for k in range(1, 10)]
N_BOOT = 10000
RNG = np.random.default_rng(20260921)


# ------------------------------------------------------------------ case building
def build_cases(tracks: dict[int, list], meta: dict[int, dict], lag_days: float) -> list[dict]:
    """One record per (float, cycle N) holding every predictor's error vector at lead 1.

    lag_days: the prior pool only uses cycles whose start time is < t(N) - lag_days.
    """
    pool = []
    for fixes in tracks.values():
        for a, b in zip(fixes, fixes[1:]):
            dt = b[1] - a[1]
            if not (0 < dt <= MAX_GAP_DAYS):
                continue
            dlat = (b[2] - a[2]) * 110.574
            dlon = (b[3] - a[3]) * 111.320 * np.cos(np.radians(a[2]))
            pool.append((a[1], a[2], a[3], dlat, dlon))
    pool_np = np.array(pool, dtype=float) if pool else np.zeros((0, 5))

    cases: list[dict] = []
    for wmo, fixes in sorted(tracks.items()):
        info = meta.get(wmo, {})
        for i in range(2, len(fixes) - 1):
            _, jN, laN, loN = fixes[i]
            _, jP, laP, loP = fixes[i - 1]
            _, jF, laF, loF = fixes[i + 1]
            lead, gap = jF - jN, jN - jP
            if not (0 < lead <= MAX_GAP_DAYS and 0 < gap <= MAX_GAP_DAYS):
                continue

            dN = ((laN - laP) * 110.574, (loN - loP) * 111.320 * np.cos(np.radians(laP)))
            d_prev = [((fixes[k][2] - fixes[k - 1][2]) * 110.574,
                       (fixes[k][3] - fixes[k - 1][3]) * 111.320 * np.cos(np.radians(fixes[k - 1][2])))
                      for k in (i - 1, i)]
            m_lat = float(np.mean([d[0] for d in d_prev]))
            m_lon = float(np.mean([d[1] for d in d_prev]))

            rec = {
                "wmo": wmo, "cycle": fixes[i][0], "lead_days": lead, "gap_days": gap,
                "region": region_of(laN, loN),
                "telemetry": info.get("transmission_type") or "unknown",
                "platform": info.get("platform_type") or "unknown",
                "cycle_class": "short (<=7 d)" if lead <= 7 else "decadal (~10 d)",
                "err": {},
                "prior_available": False,
            }
            rec["err"]["B0_persistence"] = float(hav(laF, loF, laN, loN))
            rec["err"]["B1_last_displacement"] = float(
                hav(laF, loF, *dest(laN, loN, dN[0], dN[1])))
            rec["err"]["B2_mean3_displacement"] = float(
                hav(laF, loF, *dest(laN, loN, m_lat, m_lon)))

            if pool_np.shape[0]:
                sel = (pool_np[:, 0] < jN - lag_days)
                sel &= np.abs(pool_np[:, 1] - laN) <= 2.0
                sel &= np.abs((pool_np[:, 2] - loN + 180) % 360 - 180) <= 2.0
                month = (jN % 365.25) / 30.44
                pmonth = (pool_np[:, 0] % 365.25) / 30.44
                dm = np.minimum(np.abs(month - pmonth), 12 - np.abs(month - pmonth))
                sel &= (dm <= 1.0) & np.isfinite(pool_np[:, 3]) & np.isfinite(pool_np[:, 4])
                if sel.sum() >= 5:
                    pdlat = float(np.median(pool_np[sel, 3]))
                    pdlon = float(np.median(pool_np[sel, 4]))
                    rec["prior_available"] = True
                    rec["err"]["B3_regional_seasonal_prior"] = float(
                        hav(laF, loF, *dest(laN, loN, pdlat, pdlon)))
                    rec["err"]["B4_half_prior"] = float(
                        hav(laF, loF, *dest(laN, loN, 0.5 * pdlat, 0.5 * pdlon)))
                    for w in WEIGHTS:
                        rec["err"][f"W{w:.1f}"] = float(hav(
                            laF, loF,
                            *dest(laN, loN, (1 - w) * dN[0] + w * pdlat, (1 - w) * dN[1] + w * pdlon)))
            cases.append(rec)
    return cases


def build_horizon_cases(tracks: dict[int, list], meta: dict[int, dict], lag_days: float,
                        horizons=(1, 2, 3)) -> list[dict]:
    """Same idea but the target is cycle N+h; predictors apply their step vector h times."""
    pool = []
    for fixes in tracks.values():
        for a, b in zip(fixes, fixes[1:]):
            dt = b[1] - a[1]
            if not (0 < dt <= MAX_GAP_DAYS):
                continue
            pool.append((a[1], a[2], a[3], (b[2] - a[2]) * 110.574,
                         (b[3] - a[3]) * 111.320 * np.cos(np.radians(a[2]))))
    pool_np = np.array(pool, dtype=float) if pool else np.zeros((0, 5))

    out: list[dict] = []
    for wmo, fixes in sorted(tracks.items()):
        info = meta.get(wmo, {})
        for h in horizons:
            for i in range(2, len(fixes) - h):
                _, jN, laN, loN = fixes[i]
                _, jP, laP, loP = fixes[i - 1]
                _, jF, laF, loF = fixes[i + h]
                # every intermediate hop must be a real, short interval, else the horizon is invalid
                hops = np.diff([fixes[k][1] for k in range(i, i + h + 1)])
                if not np.all((hops > 0) & (hops <= MAX_GAP_DAYS)):
                    continue
                dN = ((laN - laP) * 110.574, (loN - loP) * 111.320 * np.cos(np.radians(laP)))
                rec = {"wmo": wmo, "cycle": fixes[i][0], "horizon": h, "lead_days": float(jF - jN),
                       "region": region_of(laN, loN),
                       "telemetry": info.get("transmission_type") or "unknown",
                       "cycle_class": "short (<=7 d)" if (jF - jN) <= 7 * h else "decadal (~10 d)",
                       "err": {}}
                rec["err"]["B0_persistence"] = float(hav(laF, loF, laN, loN))
                rec["err"][f"B1_last_displacement_x{h}"] = float(
                    hav(laF, loF, *dest(laN, loN, h * dN[0], h * dN[1])))
                if pool_np.shape[0]:
                    sel = (pool_np[:, 0] < jN - lag_days)
                    sel &= np.abs(pool_np[:, 1] - laN) <= 2.0
                    sel &= np.abs((pool_np[:, 2] - loN + 180) % 360 - 180) <= 2.0
                    month = (jN % 365.25) / 30.44
                    pmonth = (pool_np[:, 0] % 365.25) / 30.44
                    dm = np.minimum(np.abs(month - pmonth), 12 - np.abs(month - pmonth))
                    sel &= (dm <= 1.0) & np.isfinite(pool_np[:, 3])
                    if sel.sum() >= 5:
                        pdlat, pdlon = float(np.median(pool_np[sel, 3])), float(np.median(pool_np[sel, 4]))
                        step = (0.5 * dN[0] + 0.5 * pdlat, 0.5 * dN[1] + 0.5 * pdlon)
                        rec["err"][f"B5_blend_x{h}"] = float(
                            hav(laF, loF, *dest(laN, loN, h * step[0], h * step[1])))
                        rec["err"][f"B3_prior_x{h}"] = float(
                            hav(laF, loF, *dest(laN, loN, h * pdlat, h * pdlon)))
                out.append(rec)
    return out


# ------------------------------------------------------------------- statistics
def med(a):
    return float(np.median(a))


def p90(a):
    return float(np.percentile(a, 90))


def boot_diff(a: np.ndarray, b: np.ndarray, fn, n_boot: int = N_BOOT) -> tuple[float, float, float]:
    """Paired bootstrap CI for fn(a) - fn(b) on the same cases (fn(x, axis))."""
    n = len(a)
    d = np.empty(n_boot)
    chunk = 500
    done = 0
    while done < n_boot:
        m = min(chunk, n_boot - done)
        idx = RNG.integers(0, n, size=(m, n))
        d[done:done + m] = fn(a[idx], axis=1) - fn(b[idx], axis=1)
        done += m
    obs = float(fn(a, None) - fn(b, None))
    return obs, float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def main() -> int:
    traj_dir = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    presets_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    out_dir.mkdir(parents=True, exist_ok=True)

    meta: dict[int, dict] = {}
    if presets_path and presets_path.exists():
        for p in json.loads(presets_path.read_text()):
            meta[int(p["wmo"])] = {"platform_type": p.get("platform_type"),
                                   "transmission_type": p.get("transmission_type")}

    tracks: dict[int, list] = {}
    raw_fix_counts: dict[int, int] = {}
    for path in sorted(traj_dir.glob("*_Rtraj.nc")):
        wmo = int(path.name.split("_")[0])
        try:
            fx = load_fixes(path)
        except Exception as exc:
            print(f"  ! {wmo}: unreadable ({type(exc).__name__})")
            continue
        raw_fix_counts[wmo] = len(fx)
        if len(fx) >= 3:
            tracks[wmo] = fx
    print(f"[F] floats parsed: {len(tracks)}")
    unscorable = {w: n for w, n in raw_fix_counts.items() if n < 4}
    print(f"[F] floats with <4 usable QC'd cycles (cannot form a case): {unscorable or 'none'}")

    # ---------------------------------------------------------------- A. lag
    rowsA = []
    for lag in (0.0, 2.0, 5.0, 7.0):
        cases = build_cases(tracks, meta, lag)
        with_prior = [c for c in cases if c["prior_available"]]
        for pred in ("B0_persistence", "B1_last_displacement", "B5_blend_lastdispl_prior", "W0.5"):
            key = "W0.5" if pred == "B5_blend_lastdispl_prior" else pred
            sub = [c["err"][key] for c in with_prior] if key == "W0.5" else \
                  [c["err"][key] for c in cases]
            if not sub:
                continue
            a = np.array(sub)
            rowsA.append({"prior_lag_days": lag, "predictor": pred, "n": len(a),
                          "median_km": med(a), "p90_km": p90(a),
                          "hit50_pct": float(100 * np.mean(a <= 50)),
                          "prior_coverage_pct": float(100 * len(with_prior) / len(cases))})
    with (out_dir / "robustness-lag-sensitivity.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rowsA[0]))
        w.writeheader()
        w.writerows(rowsA)
    print("\n[A] delivery-lag sensitivity")
    for r in rowsA:
        print(f"    lag={r['prior_lag_days']:>4}d {r['predictor']:<28} n={r['n']:>5} "
              f"median={r['median_km']:6.1f} p90={r['p90_km']:6.1f} "
              f"hit50={r['hit50_pct']:5.1f}% prior_cov={r['prior_coverage_pct']:.0f}%")

    cases = build_cases(tracks, meta, 0.0)
    common = [c for c in cases if c["prior_available"]]

    # ---------------------------------------------------------------- B. CIs
    rowsB = []
    pairs = [("B5_blend_lastdispl_prior", "W0.5", "B0_persistence", "B0_persistence"),
             ("B5_blend_lastdispl_prior", "W0.5", "B1_last_displacement", "B1_last_displacement"),
             ("B1_last_displacement", "B1_last_displacement", "B0_persistence", "B0_persistence")]
    for label_a, key_a, label_b, key_b in pairs:
        a = np.array([c["err"][key_a] for c in common])
        b = np.array([c["err"][key_b] for c in common])
        dm, lo, hi = boot_diff(a, b, lambda x, axis=None: np.median(x, axis=axis))
        dp, lo2, hi2 = boot_diff(a, b, lambda x, axis=None: np.percentile(x, 90, axis=axis))
        rowsB.append({"comparison": f"{label_a} minus {label_b}", "n": len(a),
                      "median_diff_km": dm, "median_ci_lo": lo, "median_ci_hi": hi,
                      "p90_diff_km": dp, "p90_ci_lo": lo2, "p90_ci_hi": hi2,
                      "significant": bool(lo > 0 or hi < 0)})
        print(f"\n[B] {label_a} - {label_b}: median diff {dm:+.2f} km "
              f"[{lo:+.2f}, {hi:+.2f}] ; p90 diff {dp:+.2f} km [{lo2:+.2f}, {hi2:+.2f}]")
    with (out_dir / "robustness-bootstrap-ci.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rowsB[0]))
        w.writeheader()
        w.writerows(rowsB)

    # ---------------------------------------------------------------- C. weights
    errs = {wt: np.array([c["err"][f"W{wt:.1f}"] for c in common]) for wt in WEIGHTS}
    rowsC = []
    for wt in WEIGHTS:
        a = errs[wt]
        rowsC.append({"selection": "fixed", "weight_on_prior": wt, "n": len(a),
                      "median_km": med(a), "p90_km": p90(a)})
    floats = sorted({c["wmo"] for c in common})
    lofo_by_w = defaultdict(list)
    chosen = defaultdict(int)
    for f in floats:
        ins = np.array([i for i, c in enumerate(common) if c["wmo"] != f])
        outs = np.array([i for i, c in enumerate(common) if c["wmo"] == f])
        if outs.size < 20:            # too few cases on this float to judge honestly
            continue
        med_in = {wt: float(np.median(errs[wt][ins])) for wt in WEIGHTS}
        best = min(med_in, key=med_in.get)
        chosen[best] += 1
        lofo_by_w[best] = lofo_by_w[best] + list(errs[best][outs])
    if lofo_by_w:
        a = np.array([e for v in lofo_by_w.values() for e in v])
        rowsC.append({"selection": "LOFO-selected (per held-out float)", "weight_on_prior":
                      float(np.mean([w for w, _ in sorted(chosen.items())])) if chosen else 0.0,
                      "n": len(a), "median_km": med(a), "p90_km": p90(a)})
    rowsC.append({"selection": "fixed", "weight_on_prior": 0.5, "n": len(errs[0.5]),
                  "median_km": med(errs[0.5]), "p90_km": p90(errs[0.5])})
    rowsC.append({"selection": "persistence reference", "weight_on_prior": 0.0,
                  "n": len(common), "median_km": med(np.array([c["err"]["B0_persistence"] for c in common])),
                  "p90_km": p90(np.array([c["err"]["B0_persistence"] for c in common]))})
    with (out_dir / "robustness-blend-weight-lofo.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rowsC[0]))
        w.writeheader()
        w.writerows(rowsC)
    print("\n[C] blend weight (fraction on the prior) — in-sample sweep and LOFO choice")
    for r in rowsC:
        print(f"    {r['selection']:<38} w={r['weight_on_prior']:<5} n={r['n']:>5} "
              f"median={r['median_km']:6.1f} p90={r['p90_km']:6.1f}")
    print(f"    LOFO weight choices: {dict(sorted(chosen.items()))}")

    # ---------------------------------------------------------------- D. calibration
    for cal_w in (0.2, 0.5):
        for label, use_cycle_class in ((f"region+cycle_class_w{cal_w}", True), (f"region_w{cal_w}", False)):
            rowsD = []
            cover50, cover90, ncov = [], [], []
            for f in floats:
                out_idx = [i for i, c in enumerate(common) if c["wmo"] == f]
                if len(out_idx) < 20:
                    continue
                k_out = [(common[i]["region"],
                          common[i]["cycle_class"] if use_cycle_class else "ALL") for i in out_idx]
                for key in sorted(set(k_out)):
                    ins = np.array([errs[cal_w][i] for i, c in enumerate(common)
                                    if c["wmo"] != f
                                    and (c["region"], c["cycle_class"] if use_cycle_class else "ALL") == key])
                    outs = np.array([errs[cal_w][i] for i in out_idx
                                     if (common[i]["region"],
                                         common[i]["cycle_class"] if use_cycle_class else "ALL") == key])
                    if outs.size == 0:
                        continue
                    src = ins if ins.size >= 30 else np.array(
                        [errs[cal_w][i] for i, c in enumerate(common) if c["wmo"] != f])
                    r50, r90 = float(np.percentile(src, 50)), float(np.percentile(src, 90))
                    cover50.append(float(np.mean(outs <= r50)))
                    cover90.append(float(np.mean(outs <= r90)))
                    ncov.append(outs.size)
                    rowsD.append({"stratum": str(key), "held_out_float": f, "n": outs.size,
                                  "r50_km": r50, "r90_km": r90,
                                  "cov50": cover50[-1], "cov90": cover90[-1]})
            wsum = np.array(ncov, dtype=float)
            print(f"\n[D] LOFO calibration using {label}: coverage of nominal 50% / 90% radii "
                  f"(case-weighted over {len(ncov)} (float,stratum) blocks, {int(wsum.sum())} cases)")
            print(f"    50% radius -> empirical {100 * np.average(cover50, weights=wsum):.1f}%   "
                  f"90% radius -> empirical {100 * np.average(cover90, weights=wsum):.1f}%")
            with (out_dir / f"robustness-calibration-lofo-{label.replace('+', '_')}.csv").open(
                    "w", newline="") as fh:
                if rowsD:
                    w = csv.DictWriter(fh, fieldnames=list(rowsD[0]))
                    w.writeheader()
                    w.writerows(rowsD)

    # ---------------------------------------------------------------- E. horizon
    hz = build_horizon_cases(tracks, meta, 0.0)
    rowsE = []
    for h in (1, 2, 3):
        sub = [c for c in hz if c["horizon"] == h]
        for key in sorted({k for c in sub for k in c["err"]}):
            a = np.array([c["err"][key] for c in sub if key in c["err"]])
            if a.size == 0:
                continue
            rowsE.append({"horizon_cycles": h, "predictor": key, "n": len(a),
                          "median_lead_days": float(np.median([c["lead_days"] for c in sub
                                                               if key in c["err"]])),
                          "median_km": med(a), "p90_km": p90(a),
                          "hit50_pct": float(100 * np.mean(a <= 50))})
    with (out_dir / "robustness-horizon.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rowsE[0]))
        w.writeheader()
        w.writerows(rowsE)
    print("\n[E] horizon decay (same predictors iterated forward)")
    for r in rowsE:
        print(f"    h={r['horizon_cycles']} lead~{r['median_lead_days']:5.1f}d "
              f"{r['predictor']:<28} n={r['n']:>5} median={r['median_km']:6.1f} "
              f"p90={r['p90_km']:6.1f} hit50={r['hit50_pct']:5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
