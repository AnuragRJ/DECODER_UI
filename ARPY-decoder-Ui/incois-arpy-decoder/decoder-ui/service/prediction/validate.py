"""Historical validation + calibration artefact generator.

    python -m prediction.validate --corpus /path/to/rtraj --out data/fleet_status/prediction_calibration.json
    python -m prediction.validate --corpus /path/to/rtraj --report /tmp/prediction_validation.csv

The corpus is a directory of Ifremer ``<WMO>_Rtraj.nc`` files (the same public
product the workstation already downloads). Files are read transiently: nothing
is copied into the repository and no per-cycle history is persisted. The only
output is aggregate statistics.

Protocol (PART 5 — time-aware and float-aware):

* one case per float and cycle N, target = the REAL cycle N+1 fix, which is used
  only as the label;
* predictors see only fixes at or before t(N);
* the prior pool excludes the target float (float-aware) and only accepts
  transitions that started before t(N) minus the delivery lag (time-aware);
* no random train/test mixing: evaluation is chronological per float and the
  calibration for each method is therefore out-of-sample with respect to that
  float.

Metrics per method and stratum: median / mean / p90 / RMSE great-circle error,
hit rates within 25 / 50 / 100 km, sample count, plus empirical 50 % / 90 %
radii used for the uncertainty estimate.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import netCDF4
import numpy as np

from prediction.calibrate import (
    CALIBRATION_FILENAME,
    DEFAULT_BLEND_WEIGHT_ON_PRIOR,
    METHOD_HISTORY_PRIOR,
    METHOD_PERSISTENCE,
    METHOD_REGIONAL_PRIOR,
    METHOD_TRAJECTORY,
)
from prediction.features import (
    CYCLE_CLASS_DECADAL,
    CYCLE_CLASS_SHORT,
    MAX_TRANSITION_DAYS,
    Transition,
    cycle_class,
    region_of,
)
from prediction.geometry import destination, displacement_km, haversine_km
from prediction.prior import (
    GRID_CELL_DEG,
    GRID_MIN_COUNT,
    PRIOR_LAG_DAYS,
    grid_cell_keys,
    neighbourhood_prior,
)

JULD_EPOCH = datetime(1950, 1, 1, tzinfo=UTC)
#: Leave-one-float-out calibration: methods are scored on floats excluded from
#: the neighbourhood statistics they use.
SATELLITE_FIX_MC = 703.0


def load_fixes(path: Path) -> list[dict[str, Any]]:
    """QC 1/2 satellite fixes, first fix per cycle, chronological.

    Ordering correction (Stage-1 pass): the returned list is now sorted by JULD.
    A few INCOIS trajectory files in the audit corpus contain measurement rows that
    are not in time order around a long silence (the affected floats are listed in
    the Stage-1 report, not here), and the unsorted list made one-cycle labels and
    hop spans land on stale duplicate rows. Sorting only reorders rows that were
    already present; it does not add, drop or interpolate any observation. Effect on
    the aggregate Stage-0 replay is small (measured in audit/stage1_order_effect.py:
    median +0.2 km, p90 +2.5 km, RMSE -11.4 km); per-case labels near an
    out-of-order block change materially, which is why the correction matters.
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
            if "MEASUREMENT_CODE" in ds.variables
            else None
        )
    finally:
        ds.close()

    def _text(value: Any) -> str:
        return value.decode(errors="replace").strip() if isinstance(value, (bytes, bytearray)) else str(value).strip()

    keep = np.isfinite(cyc) & np.isfinite(juld) & np.isfinite(lat) & np.isfinite(lon)
    if mc is not None:
        keep &= mc == SATELLITE_FIX_MC
    if qc is not None:
        keep &= np.isin(np.array([_text(v) for v in qc]), ("1", "2"))
    keep &= (lat >= -90) & (lat <= 90) & (lon >= -180) & (lon <= 180) & (juld < 90000)

    by_cycle: dict[int, dict[str, Any]] = {}
    for i in np.where(keep)[0]:
        cycle = int(cyc[i])
        if cycle not in by_cycle:
            by_cycle[cycle] = {
                "juld": float(juld[i]),
                "lat": float(lat[i]),
                "lon": float(lon[i]),
                "cycle": cycle,
                "mc": SATELLITE_FIX_MC,
                "pos_qc": "1",
            }
    ordered = [by_cycle[c] for c in sorted(by_cycle)]
    # Cycle numbers are normally chronological, but a stale duplicate row can carry
    # a higher cycle number with an earlier timestamp; sort by JULD so downstream
    # spans and labels are physical. Ties keep the earlier cycle number first.
    ordered.sort(key=lambda fix: (fix["juld"], fix.get("cycle", 0)))
    return ordered


def transitions_of(wmo: int, fixes: list[dict[str, Any]]) -> list[Transition]:
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


def interval_days_for(transitions: list[Transition], upto_juld: float | None = None) -> tuple[float, int]:
    """Median observed cycle spacing from transitions strictly before a time."""
    days = [t.days for t in transitions if upto_juld is None or t.start_juld < upto_juld]
    days = [d for d in days if 0.5 <= d <= 60.0]
    if len(days) < 3:
        return 10.0, len(days)
    return float(statistics.median(days)), len(days)


def summarize(errors: Iterable[float]) -> dict[str, Any]:
    values = np.array([e for e in errors if e is not None and math.isfinite(e)], dtype=float)
    if values.size == 0:
        return {}
    return {
        "n": int(values.size),
        "median_km": round(float(np.median(values)), 1),
        "mean_km": round(float(values.mean()), 1),
        "p90_km": round(float(np.percentile(values, 90)), 1),
        "rmse_km": round(float(math.sqrt(float((values ** 2).mean()))), 1),
        "hit25_pct": round(float(100.0 * (values <= 25).mean()), 1),
        "hit50_pct": round(float(100.0 * (values <= 50).mean()), 1),
        "hit100_pct": round(float(100.0 * (values <= 100).mean()), 1),
        "r50_km": round(float(np.percentile(values, 50)), 1),
        "r90_km": round(float(np.percentile(values, 90)), 1),
        "max_km": round(float(values.max()), 1),
    }


def run_validation(corpus_dir: Path, blend_weight: float) -> tuple[dict[str, list[dict]], dict[str, Any]]:
    tracks: dict[int, list[dict[str, Any]]] = {}
    hashes: list[str] = []
    for path in sorted(corpus_dir.glob("*_Rtraj.nc")):
        wmo = int(path.name.split("_")[0])
        try:
            fixes = load_fixes(path)
        except Exception as exc:
            print(f"  ! {wmo}: unreadable ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        if len(fixes) >= 4:
            tracks[wmo] = fixes
            hashes.append(f"{path.name}:{hashlib.sha256(path.read_bytes()).hexdigest()}")

    full_pool: list[Transition] = []
    for wmo, fixes in tracks.items():
        full_pool.extend(transitions_of(wmo, fixes))

    cases: dict[str, list[dict[str, Any]]] = {}
    for wmo, fixes in sorted(tracks.items()):
        own = transitions_of(wmo, fixes)
        for i in range(2, len(fixes) - 1):
            current, previous, target = fixes[i], fixes[i - 1], fixes[i + 1]
            lead = target["juld"] - current["juld"]
            gap = current["juld"] - previous["juld"]
            if not (0 < lead <= MAX_TRANSITION_DAYS and 0 < gap <= MAX_TRANSITION_DAYS):
                continue
            interval, samples = interval_days_for(own, current["juld"])
            klass = cycle_class(interval)
            dlat, dlon = displacement_km(previous["lat"], previous["lon"], current["lat"], current["lon"])
            last_step = (dlat, dlon)
            prior = neighbourhood_prior(
                full_pool,
                exclude_wmo=wmo,
                lat=current["lat"],
                lon=current["lon"],
                juld=current["juld"],
                lag_days=PRIOR_LAG_DAYS,
            )
            region = region_of(current["lat"], current["lon"])
            predictions: dict[str, tuple[float, float]] = {
                METHOD_PERSISTENCE: (current["lat"], current["lon"]),
                METHOD_TRAJECTORY: destination(current["lat"], current["lon"], *last_step),
            }
            if prior is not None:
                blend = (
                    (1.0 - blend_weight) * last_step[0] + blend_weight * prior.dlat_km,
                    (1.0 - blend_weight) * last_step[1] + blend_weight * prior.dlon_km,
                )
                predictions[METHOD_HISTORY_PRIOR] = destination(current["lat"], current["lon"], *blend)
                predictions[METHOD_REGIONAL_PRIOR] = destination(
                    current["lat"], current["lon"], prior.dlat_km, prior.dlon_km
                )
            for method, (plat, plon) in predictions.items():
                cases.setdefault(method, []).append(
                    {
                        "wmo": wmo,
                        "cycle": current.get("cycle"),
                        "error_km": haversine_km(target["lat"], target["lon"], plat, plon),
                        "region": region,
                        "cycle_class": klass,
                        "interval_days": interval,
                        "interval_samples": samples,
                        "prior_neighbours": prior.neighbours if prior else 0,
                        "target_juld": target["juld"],
                    }
                )

    # Sparse regional/seasonal drift grid from every observed transition.
    cells: dict[str, list[float]] = {}
    for transition in full_pool:
        for rank, key in enumerate(
            grid_cell_keys(transition.lat, transition.lon, transition.start_juld, GRID_CELL_DEG)[:1]
        ):
            _ = rank
            bucket = cells.setdefault(key, [])
            bucket.extend([transition.dlat_km, transition.dlon_km])
    grid: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    for key, values in cells.items():
        lat_values = values[0::2]
        lon_values = values[1::2]
        if len(lat_values) < GRID_MIN_COUNT:
            continue
        grid[key] = [
            round(float(np.median(lat_values)), 2),
            round(float(np.median(lon_values)), 2),
            len(lat_values),
        ]
        counts[key] = len(lat_values)

    corpus = {
        "rtraj_floats": len(tracks),
        "scored_floats": len({c["wmo"] for items in cases.values() for c in items}),
        "transitions": len(full_pool),
        "cases": {method: len(items) for method, items in sorted(cases.items())},
        "floats_with_insufficient_history": [
            wmo for wmo, fixes in sorted(tracks.items()) if len(fixes) < 4
        ],
        "source": "dac/incois/<WMO>_Rtraj.nc (public Ifremer/Argo GDAC)",
        "file_sha256": sorted(hashes),
        "prior_lag_days": PRIOR_LAG_DAYS,
        "prior_radius_deg": 2.0,
        "prior_min_neighbours": 5,
        "method": "leave-one-float-out, chronological per float",
    }
    return cases, {"corpus": corpus, "grid": grid, "grid_counts": counts}


def build_calibration(cases: dict[str, list[dict]], extras: dict[str, Any], blend_weight: float,
                      generated_at: str) -> dict[str, Any]:
    methods: dict[str, Any] = {}
    for method, items in sorted(cases.items()):
        def entry(subset: list[dict]) -> dict[str, Any]:
            metrics = summarize([c["error_km"] for c in subset])
            if not metrics:
                return {}
            return {
                "n": metrics["n"],
                "r50_km": metrics["r50_km"],
                "r90_km": metrics["r90_km"],
                "metrics": metrics,
            }

        if not items:
            # A method with no scored cases must not appear in the artefact: an empty
            # default entry would be served as a radius with no validation behind it.
            continue

        strata: dict[str, Any] = {}
        regions = sorted({c["region"] for c in items})
        for region in regions:
            strata[f"{region}|*"] = entry([c for c in items if c["region"] == region])
            for klass in (CYCLE_CLASS_SHORT, CYCLE_CLASS_DECADAL):
                subset = [c for c in items if c["region"] == region and c["cycle_class"] == klass]
                if subset:
                    strata[f"{region}|{klass}"] = entry(subset)
        methods[method] = {"default": entry(items), "strata": strata}

    return {
        "version": 1,
        "generated_at": generated_at,
        "generator": "decoder-ui service/prediction/validate.py",
        "blend_weight_on_prior": blend_weight,
        "default_interval_days": 10.0,
        "note": (
            "Aggregate validation statistics only (radii, metrics, sparse drift grid). "
            "Contains no per-cycle history and no float positions."
        ),
        "corpus": extras["corpus"],
        "prior_grid": {"cell_deg": GRID_CELL_DEG, "min_count": GRID_MIN_COUNT, "cells": extras["grid"]},
        "methods": methods,
    }


def write_report(cases: dict[str, list[dict]], path: Path) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "method",
                "region",
                "cycle_class",
                "n",
                "median_km",
                "mean_km",
                "p90_km",
                "rmse_km",
                "hit25_pct",
                "hit50_pct",
                "hit100_pct",
                "r50_km",
                "r90_km",
            ]
        )
        for method, items in sorted(cases.items()):
            groups: dict[tuple[str, str], list[dict]] = {}
            for item in items:
                groups.setdefault((item["region"], item["cycle_class"]), []).append(item)
                groups.setdefault((item["region"], "ALL"), []).append(item)
            groups.setdefault(("ALL", "ALL"), []).extend(items)
            for (region, klass), subset in sorted(groups.items()):
                metrics = summarize([c["error_km"] for c in subset])
                if not metrics:
                    continue
                writer.writerow(
                    [
                        method,
                        region,
                        klass,
                        metrics["n"],
                        metrics["median_km"],
                        metrics["mean_km"],
                        metrics["p90_km"],
                        metrics["rmse_km"],
                        metrics["hit25_pct"],
                        metrics["hit50_pct"],
                        metrics["hit100_pct"],
                        metrics["r50_km"],
                        metrics["r90_km"],
                    ]
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate + calibrate the next-location predictor")
    parser.add_argument("--corpus", required=True, help="directory of <WMO>_Rtraj.nc files")
    parser.add_argument("--out", default=None, help=f"calibration JSON path (default {CALIBRATION_FILENAME})")
    parser.add_argument("--report", default=None, help="optional CSV metrics report")
    parser.add_argument("--blend-weight", type=float, default=DEFAULT_BLEND_WEIGHT_ON_PRIOR)
    args = parser.parse_args(argv)

    corpus_dir = Path(args.corpus)
    if not corpus_dir.is_dir():
        print(f"corpus directory not found: {corpus_dir}", file=sys.stderr)
        return 2
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    cases, extras = run_validation(corpus_dir, args.blend_weight)
    if not cases:
        print("no scorable cases in corpus", file=sys.stderr)
        return 1
    calibration = build_calibration(cases, extras, args.blend_weight, generated_at)

    out_path = Path(args.out) if args.out else Path(__file__).resolve().parents[2] / "data" / "fleet_status" / CALIBRATION_FILENAME
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(calibration, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"calibration written: {out_path}")
    if args.report:
        write_report(cases, Path(args.report))
        print(f"metrics report written: {args.report}")

    print(f"corpus: {calibration['corpus']['rtraj_floats']} floats, "
          f"{calibration['corpus']['transitions']} transitions, grid cells {len(extras['grid'])}")
    for method, items in sorted(cases.items()):
        metrics = summarize([c["error_km"] for c in items])
        print(
            f"  {method:<24} n={metrics['n']:>6} median={metrics['median_km']:>6} km "
            f"p90={metrics['p90_km']:>6} km rmse={metrics['rmse_km']:>6} km "
            f"hit50={metrics['hit50_pct']:>5}% r90={metrics['r90_km']:>6} km"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
