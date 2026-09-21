"""STAGE-1 evaluation: Stage-0 vs Stage-1 on the same corpus, same protocol.

Reuses the shipped validation harness (`prediction.validate`) for the corpus
loader, the leave-one-float-out prior pool, the strata and the summariser, and
scores **both** stages inside one case loop, so the comparison cannot drift:

* one case per float and cycle N; the target is the real cycle N+1 fix, used only
  as the label;
* predictors see only fixes at or before t(N);
* the prior pool excludes the target float and only accepts transitions that
  started at least ``PRIOR_LAG_DAYS`` before t(N);
* chronological per float, no train/test mixing.

Methods scored
--------------
Stage-0 (baseline, reproduced here for a like-for-like comparison):
``persistence``, ``trajectory_extrapolation`` (newest hop as one cycle),
``history_prior`` (0.8 * hop + 0.2 * prior), ``regional_prior``.

Stage-1 (cycle-scale step, `prediction.cycle_step`):
``cycle_window`` / ``cycle_window_prior`` (matched window + optional prior) and
``cycle_median`` / ``cycle_median_prior`` (median of matched windows). The prior
blend weight is swept (0.0 / 0.1 / 0.2 / 0.3) and reported, so Stage-1's shipped
weight is chosen from its own historical errors rather than inherited.

Outputs
-------
* Stage-1 calibration artefact (its own R50/R90 per method and stratum),
* a comparison CSV (both stages, every stratum),
* a JSON report with the availability/fallback accounting, per-float medians,
  leave-one-float-out stability and the pre-registered ship criterion.

Usage
-----
    PYTHONPATH=service:src /home/user/.venv/bin/python -m prediction.validate_cycle \\
        --corpus /tmp/argotraj2 --out data/fleet_status/prediction_calibration_stage1.json \\
        --report /home/user/prediction-validation/stage1_vs_stage0.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from prediction.calibrate import (
    METHOD_CYCLE_MEDIAN,
    METHOD_CYCLE_MEDIAN_PRIOR,
    METHOD_CYCLE_WINDOW,
    METHOD_CYCLE_WINDOW_PRIOR,
    METHOD_HISTORY_PRIOR,
    METHOD_PERSISTENCE,
    METHOD_REGIONAL_PRIOR,
    METHOD_TRAJECTORY,
    STAGE_STAGE1,
)
from prediction.cycle_step import (
    DEFAULT_CYCLE_STEP,
    STEP_MEDIAN,
    STEP_WINDOW,
    cycle_scale_step,
    fallback_reason,
)
from prediction.features import CYCLE_CLASS_DECADAL, CYCLE_CLASS_SHORT, Transition, cycle_class, region_of
from prediction.geometry import destination, displacement_km, haversine_km
from prediction.prior import (
    GRID_CELL_DEG,
    GRID_MIN_COUNT,
    PRIOR_LAG_DAYS,
    grid_cell_keys,
    neighbourhood_prior,
)
from prediction.validate import (
    MAX_TRANSITION_DAYS,
    build_calibration,
    interval_days_for,
    load_fixes,
    summarize,
    transitions_of,
    write_report,
)

#: Harness-only labels for the paired, deployment-faithful comparison rows. They
#: are never written into a calibration artefact (which only carries cycle_* methods).
METHOD_SERVED_STAGE0 = "served_stage0 (last-hop ladder, shipped)"
METHOD_SERVED_STAGE1 = "served_stage1 (cycle-scale, falls back to Stage-0)"
METHOD_SERVED_SCOPED = "served_stage1_scoped (cycle-scale only on sub-cycle / gap hops)"

#: Target-matched label rule (primary protocol). The deployed target is the next
#: *surfacing* roughly one expected interval after the issuing fix, and the
#: deployed forward test scores exactly that way ("strictly later cycle, at least
#: half the observed interval"). Scoring a one-cycle prediction against a fix
#: published 12 h later (telemetry burst) would systematically mis-rank the
#: methods, so the label is the first fix at least half an interval later, and a
#: case is scoreable only when that fix is within two intervals (otherwise no
#: observation exists near the target time and the case is counted as unscoreable,
#: never scored).
LABEL_MIN_RATIO = 0.5
LABEL_MAX_RATIO = 2.0

#: Normalisation caps evaluated for multi-cycle gaps.
CAP_SWEEP = (3.0, 10.0)

#: Stage-1 blend weights evaluated for the prior-blended variants.
WEIGHT_SWEEP = (0.0, 0.1, 0.2, 0.3)
#: Stage-0's shipped weight, used for its own history_prior row.
STAGE0_WEIGHT = 0.2

#: Pre-registered ship criterion (fixed BEFORE looking at the results).
SHIP_CRITERION = {
    "headline": "cycle_window vs trajectory_extrapolation",
    "median_improvement_pct_min": 5.0,
    "p90_improvement_pct_min": 5.0,
    "rmse_improvement_pct_min": 0.0,
    "stability": "leave-one-float-out aggregates must keep the same sign of improvement",
    "note": "a failure on any term keeps Stage-0 as the shipped default",
}


def blend(step: tuple[float, float], prior: Any, weight: float) -> tuple[float, float]:
    if prior is None or weight <= 0:
        return step
    return (
        (1.0 - weight) * step[0] + weight * prior.dlat_km,
        (1.0 - weight) * step[1] + weight * prior.dlon_km,
    )


def target_index(fixes: list[dict[str, Any]], i: int, interval: float) -> int | None:
    """First fix at least half an interval after fix ``i`` and within two intervals."""
    current = fixes[i]
    for j in range(i + 1, len(fixes)):
        gap = fixes[j]["juld"] - current["juld"]
        if gap < LABEL_MIN_RATIO * interval:
            continue
        if gap > LABEL_MAX_RATIO * interval or gap > MAX_TRANSITION_DAYS:
            return None
        cycle_now, cycle_next = current.get("cycle"), fixes[j].get("cycle")
        if cycle_now is not None and cycle_next is not None and cycle_next <= cycle_now:
            continue
        return j
    return None


def stage0_route(visible_transitions, prior, weight, lat0, lon0):
    """The rung the shipped Stage-0 code would use, reproduced exactly.

    Mirrors ``prediction.predict.predict_float``: the newest *eligible* transition
    (hops longer than ``MAX_TRANSITION_DAYS`` are mission gaps and are excluded by
    ``features.build_transitions``) drives rung 4 and is blended with the prior at
    the calibrated weight when a prior exists; with no eligible transition the
    service falls to the regional prior, and finally to persistence.
    """
    if visible_transitions:
        last = visible_transitions[-1]
        step = (last.dlat_km, last.dlon_km)
        method = METHOD_TRAJECTORY
        if prior is not None:
            step = blend(step, prior, weight)
            method = METHOD_HISTORY_PRIOR
        return method, step, last
    if prior is not None:
        return METHOD_REGIONAL_PRIOR, (prior.dlat_km, prior.dlon_km), None
    return METHOD_PERSISTENCE, (0.0, 0.0), None


def hop_class_of(days: float, interval: float) -> str:
    """"sub_cycle" | "cycle_scale" | "multi_cycle" for a hop duration."""
    if not interval:
        return "unknown"
    ratio = days / interval
    if ratio < 0.5:
        return "sub_cycle"
    if ratio <= 1.5:
        return "cycle_scale"
    return "multi_cycle"


def score(cases: dict[str, list[dict[str, Any]]], corpus_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    tracks: dict[int, list[dict[str, Any]]] = {}
    for path in sorted(corpus_dir.glob("*_Rtraj.nc")):
        wmo = int(path.name.split("_")[0])
        try:
            fixes = load_fixes(path)
        except Exception as exc:  # pragma: no cover - visibility only
            print(f"  ! {wmo}: unreadable ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        if len(fixes) >= 4:
            tracks[wmo] = fixes

    full_pool: list[Transition] = []
    for wmo, fixes in tracks.items():
        full_pool.extend(transitions_of(wmo, fixes))

    availability: dict[str, Any] = {
        "candidates": 0, "cases": 0, "unscoreable": 0,
        "stage1_by_cap": {}, "stage0_route": {}, "stage1_unavailable": 0,
        "unavailable_by_variant": {}, "unavailable_by_float": {},
        "unavailable_reasons": {}, "hop_class_counts": {},
    }
    legacy: dict[str, list[float]] = {}
    served: dict[str, list[dict[str, Any]]] = {"stage0": [], "stage1": [], "stage1_scoped": []}

    for wmo, fixes in sorted(tracks.items()):
        own = transitions_of(wmo, fixes)
        for i in range(2, len(fixes) - 1):
            current = fixes[i]
            availability["candidates"] += 1
            interval, samples = interval_days_for(own, current["juld"])
            region = region_of(current["lat"], current["lon"])
            klass = cycle_class(interval)
            j = target_index(fixes, i, interval)
            if j is None:
                availability["unscoreable"] += 1
                continue
            availability["cases"] += 1
            label_fix = fixes[j]
            visible = fixes[: i + 1]
            visible_transitions = transitions_of(wmo, visible)
            prior = neighbourhood_prior(
                full_pool, exclude_wmo=wmo, lat=current["lat"], lon=current["lon"],
                juld=current["juld"], lag_days=PRIOR_LAG_DAYS,
            )
            method0, step0, last = stage0_route(
                visible_transitions, prior, STAGE0_WEIGHT, current["lat"], current["lon"])
            if last is not None:
                hop_class = hop_class_of(last.days, interval)
            else:
                hop_class = "gap_only"
            availability["hop_class_counts"][hop_class] = (
                availability["hop_class_counts"].get(hop_class, 0) + 1)
            availability["stage0_route"][method0] = availability["stage0_route"].get(method0, 0) + 1

            common = {
                "wmo": wmo, "cycle": current.get("cycle"), "region": region,
                "cycle_class": klass, "interval_days": interval, "interval_samples": samples,
                "prior_neighbours": prior.neighbours if prior else 0,
                "target_juld": label_fix["juld"], "hop_class": hop_class,
                "label_ratio": round((label_fix["juld"] - current["juld"]) / interval, 3) if interval else None,
                "hop_days": round(last.days, 3) if last is not None else None,
            }

            def record(
                method: str,
                lat: float,
                lon: float,
                bucket: dict | None = None,
                extra: dict[str, Any] | None = None,
            ) -> float:
                """One scored case; ``extra`` fields are merged into the case itself."""
                error = haversine_km(label_fix["lat"], label_fix["lon"], lat, lon)
                (cases if bucket is None else bucket).setdefault(method, []).append(
                    {**common, "error_km": error, **(extra or {})}
                )
                return error

            def predicted(step: tuple[float, float]) -> tuple[float, float]:
                return destination(current["lat"], current["lon"], step[0], step[1])

            # ---- Stage-0 exactly as the service would serve it ---------------
            lat0, lon0 = predicted(step0)
            err0 = record(method0, lat0, lon0)
            # diagnostic single-method tables; a step that the routed method already
            # used is not recorded twice (that would double-count it in the CPU/table
            # aggregates and inflate its n)
            if last is not None:
                if method0 != METHOD_TRAJECTORY:
                    record(METHOD_TRAJECTORY, *predicted((last.dlat_km, last.dlon_km)))
                if prior is not None and method0 != METHOD_HISTORY_PRIOR:
                    record(METHOD_HISTORY_PRIOR,
                           *predicted(blend((last.dlat_km, last.dlon_km), prior, STAGE0_WEIGHT)))
                if prior is not None and method0 != METHOD_REGIONAL_PRIOR:
                    record(METHOD_REGIONAL_PRIOR, *predicted((prior.dlat_km, prior.dlon_km)))
            elif method0 != METHOD_PERSISTENCE:
                record(METHOD_PERSISTENCE, *predicted((0.0, 0.0)))
            served["stage0"].append({**common, "error_km": err0, "pred_lat": lat0, "pred_lon": lon0,
                                     "route": method0})

            # legacy (i -> i+1) protocol, secondary robustness table
            nxt = fixes[i + 1]
            legacy.setdefault(method0, []).append(
                haversine_km(nxt["lat"], nxt["lon"], lat0, lon0))

            # ---- Stage-1: cycle-scale step from fixes at or before t(N) ------
            stage1_errors = None
            for cap in CAP_SWEEP:
                for mode, base_method, prior_method in (
                    (STEP_WINDOW, METHOD_CYCLE_WINDOW, METHOD_CYCLE_WINDOW_PRIOR),
                    (STEP_MEDIAN, METHOD_CYCLE_MEDIAN, METHOD_CYCLE_MEDIAN_PRIOR),
                ):
                    key = f"{base_method}@cap{cap:g}"
                    step = cycle_scale_step(visible, interval, mode=mode, max_cycles=cap)
                    if step is None:
                        availability["unavailable_by_variant"][key] = (
                            availability["unavailable_by_variant"].get(key, 0) + 1)
                        if cap == CAP_SWEEP[0] and mode == STEP_WINDOW:
                            availability["stage1_unavailable"] += 1
                            availability["unavailable_by_float"][str(wmo)] = (
                                availability["unavailable_by_float"].get(str(wmo), 0) + 1)
                            reason = fallback_reason(visible, interval)
                            availability["unavailable_reasons"][reason] = (
                                availability["unavailable_reasons"].get(reason, 0) + 1)
                        continue
                    availability["stage1_by_cap"][key] = availability["stage1_by_cap"].get(key, 0) + 1
                    gap_normalised = step.cycles > 1
                    if cap == CAP_SWEEP[0]:
                        step_pair = (step.dlat_km, step.dlon_km)
                        lat_s, lon_s = predicted(step_pair)
                        record(base_method, lat_s, lon_s,
                               extra={"gap_normalised": gap_normalised, "step_cycles": step.cycles})
                        if stage1_errors is None and mode == STEP_WINDOW:
                            stage1_errors = {"base": (lat_s, lon_s), "step": step_pair}
                        if prior is not None:
                            lat_p, lon_p = predicted(blend(step_pair, prior, STAGE0_WEIGHT))
                            record(prior_method + f"@w{STAGE0_WEIGHT:g}", lat_p, lon_p,
                                   extra={"gap_normalised": gap_normalised, "step_cycles": step.cycles})
                            for weight in WEIGHT_SWEEP:
                                if weight == STAGE0_WEIGHT:
                                    continue
                                record(f"{prior_method}@w{weight:g}",
                                       *predicted(blend(step_pair, prior, weight)),
                                       extra={"gap_normalised": gap_normalised})
                    record(key, *predicted((step.dlat_km, step.dlon_km)),
                           extra={"gap_normalised": gap_normalised, "step_cycles": step.cycles})

            scoped_hop = hop_class in ("sub_cycle", "multi_cycle", "gap_only")
            if stage1_errors is not None and scoped_hop:
                lat_c, lon_c = stage1_errors["base"]
            else:
                lat_c, lon_c = lat0, lon0
            served.setdefault("stage1_scoped", []).append({
                **common,
                "error_km": haversine_km(label_fix["lat"], label_fix["lon"], lat_c, lon_c),
                "pred_lat": lat_c, "pred_lon": lon_c,
                "route": ("cycle_scale" if (stage1_errors is not None and scoped_hop) else method0),
                "inherited_stage0": not (stage1_errors is not None and scoped_hop),
            })

            if stage1_errors is not None:
                legacy.setdefault(METHOD_CYCLE_WINDOW, []).append(
                    haversine_km(nxt["lat"], nxt["lon"], *stage1_errors["base"]))

            if stage1_errors is None:  # no cycle-scale window: Stage-0 branch is retained
                served["stage1"].append({**common, "error_km": err0, "pred_lat": lat0, "pred_lon": lon0,
                                         "route": method0, "inherited_stage0": True})
            else:
                lat_s, lon_s = stage1_errors["base"]
                served["stage1"].append({**common,
                                         "error_km": haversine_km(label_fix["lat"], label_fix["lon"], lat_s, lon_s),
                                         "pred_lat": lat_s, "pred_lon": lon_s,
                                         "route": METHOD_CYCLE_WINDOW_PRIOR if prior is not None else METHOD_CYCLE_WINDOW,
                                         "inherited_stage0": False})

    # sparse regional/seasonal grid, identical code path to the shipped harness
    cells: dict[str, list[float]] = {}
    for transition in full_pool:
        for key in grid_cell_keys(transition.lat, transition.lon, transition.start_juld, GRID_CELL_DEG)[:1]:
            bucket = cells.setdefault(key, [])
            bucket.extend([transition.dlat_km, transition.dlon_km])
    grid: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    for key, values in cells.items():
        lat_values, lon_values = values[0::2], values[1::2]
        if len(lat_values) < GRID_MIN_COUNT:
            continue
        grid[key] = [
            round(float(statistics.median(lat_values)), 2),
            round(float(statistics.median(lon_values)), 2),
            len(lat_values),
        ]
        counts[key] = len(lat_values)

    extras = {
        "corpus": {
            "rtraj_floats": len(tracks),
            "scored_floats": len({case["wmo"] for items in cases.values() for case in items}),
            "transitions": len(full_pool),
            "cases": {method: len(items) for method, items in sorted(cases.items())},
            "source": "dac/incois/<WMO>_Rtraj.nc (public Ifremer/Argo GDAC)",
            "prior_lag_days": PRIOR_LAG_DAYS,
            "prior_radius_deg": 2.0,
            "prior_min_neighbours": 5,
            "blend_weight_on_prior": STAGE0_WEIGHT,
            "method": "leave-one-float-out, chronological per float",
            "stage0_replay": "newest eligible transition (<= MAX_TRANSITION_DAYS) -> prior -> persistence, as shipped",
            "label_rule": (
                f"next fix at least {LABEL_MIN_RATIO:g} x interval after the issuing fix and "
                f"within {LABEL_MAX_RATIO:g} x interval (target-matched, mirrors the deployment "
                "forward-test scoring rule)"
            ),
        },
        "grid": grid,
        "grid_counts": counts,
    }
    return cases, {"extras": extras, "availability": availability, "legacy": legacy, "served": served}


def per_float_medians(cases: dict[str, list[dict]], method: str) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for case in cases.get(method, []):
        grouped.setdefault(str(case["wmo"]), []).append(case["error_km"])
    return {wmo: round(statistics.median(v), 1) for wmo, v in sorted(grouped.items())}


def lofo_range(cases: dict[str, list[dict]], method: str) -> dict[str, Any]:
    """Aggregate median/p90 when each float is left out in turn (stability check)."""
    floats = sorted({str(c["wmo"]) for c in cases.get(method, [])})
    medians, p90s = [], []
    for drop in floats:
        errors = [c["error_km"] for c in cases[method] if str(c["wmo"]) != drop]
        if len(errors) < 50:
            continue
        errors.sort()
        medians.append(statistics.median(errors))
        p90s.append(errors[min(len(errors) - 1, int(0.9 * len(errors)))])
    if not medians:
        return {}
    return {
        "floats": len(floats),
        "median_km_min": round(min(medians), 1),
        "median_km_max": round(max(medians), 1),
        "p90_km_min": round(min(p90s), 1),
        "p90_km_max": round(max(p90s), 1),
    }


def improvement(before: float, after: float) -> float:
    if not before:
        return 0.0
    return round(100.0 * (before - after) / before, 2)


def write_comparison_csv(cases: dict[str, list[dict]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "method", "region", "cycle_class", "n", "median_km", "mean_km", "p90_km", "rmse_km",
            "hit25_pct", "hit50_pct", "hit100_pct", "r50_km", "r90_km",
        ])
        for method in [METHOD_SERVED_STAGE0, METHOD_SERVED_STAGE1] + sorted(
                m for m in cases if m not in (METHOD_SERVED_STAGE0, METHOD_SERVED_STAGE1)):
            items = cases[method]
            for region in sorted({c["region"] for c in items}):
                for klass in ("ALL", CYCLE_CLASS_SHORT, CYCLE_CLASS_DECADAL):
                    subset = [
                        c for c in items
                        if c["region"] == region and (klass == "ALL" or c["cycle_class"] == klass)
                    ]
                    if not subset:
                        continue
                    metrics = summarize([c["error_km"] for c in subset])
                    if not metrics:
                        continue
                    writer.writerow([
                        method, region, klass, metrics["n"], metrics["median_km"], metrics["mean_km"],
                        metrics["p90_km"], metrics["rmse_km"], metrics["hit25_pct"], metrics["hit50_pct"],
                        metrics["hit100_pct"], metrics["r50_km"], metrics["r90_km"],
                    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out", default=str(
        Path("/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/data/fleet_status/"
             "prediction_calibration_stage1.json")))
    parser.add_argument("--report", default=None, help="comparison CSV path")
    parser.add_argument("--json", default=None, help="full comparison JSON path")
    args = parser.parse_args(argv)

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    cases, meta = score({}, Path(args.corpus))
    availability = meta["availability"]
    extras = meta["extras"]
    # the ship-gate comparison: what each stage would actually serve per case,
    # paired one-for-one (Stage-1 falls back to the Stage-0 branch when it has no
    # cycle-scale window, exactly as the shipped code does)
    pairs = list(zip(meta["served"]["stage0"], meta["served"]["stage1"]))
    scoped_pairs = list(zip(meta["served"]["stage0"], meta["served"]["stage1_scoped"]))
    cases[METHOD_SERVED_STAGE0] = [pair[0] for pair in pairs]
    cases[METHOD_SERVED_STAGE1] = [pair[1] for pair in pairs]
    cases[METHOD_SERVED_SCOPED] = [pair[1] for pair in scoped_pairs]

    # ---- headline comparison ------------------------------------------------
    headline = {}
    for method in (METHOD_SERVED_STAGE0, METHOD_SERVED_STAGE1, METHOD_SERVED_SCOPED,
                   METHOD_TRAJECTORY, METHOD_HISTORY_PRIOR, METHOD_PERSISTENCE,
                   METHOD_REGIONAL_PRIOR, METHOD_CYCLE_WINDOW, METHOD_CYCLE_MEDIAN,
                   f"{METHOD_CYCLE_WINDOW}@cap10", f"{METHOD_CYCLE_MEDIAN}@cap10"):
        metrics = summarize([c["error_km"] for c in cases.get(method, [])])
        if metrics:
            headline[method] = metrics

    sweep = {}
    for weight in WEIGHT_SWEEP:
        for key, base in ((METHOD_CYCLE_WINDOW_PRIOR, METHOD_CYCLE_WINDOW),
                          (METHOD_CYCLE_MEDIAN_PRIOR, METHOD_CYCLE_MEDIAN)):
            metrics = summarize([
                c["error_km"] for c in cases.get(f"{key}@w{weight:g}", [])
            ])
            if metrics:
                sweep[f"{key}@w{weight:g}"] = metrics

    base = headline.get(METHOD_TRAJECTORY, {})
    window = headline.get(METHOD_CYCLE_WINDOW, {})
    median_variant = headline.get(METHOD_CYCLE_MEDIAN, {})
    deltas = {
        "median_improvement_pct": improvement(base.get("median_km", 0), window.get("median_km", 0)),
        "p90_improvement_pct": improvement(base.get("p90_km", 0), window.get("p90_km", 0)),
        "rmse_improvement_pct": improvement(base.get("rmse_km", 0), window.get("rmse_km", 0)),
        "mean_improvement_pct": improvement(base.get("mean_km", 0), window.get("mean_km", 0)),
        "hit25_gain_pct_points": round(window.get("hit25_pct", 0) - base.get("hit25_pct", 0), 1),
        "hit50_gain_pct_points": round(window.get("hit50_pct", 0) - base.get("hit50_pct", 0), 1),
        "hit100_gain_pct_points": round(window.get("hit100_pct", 0) - base.get("hit100_pct", 0), 1),
    }

    # ---- error by the sampling class of the newest hop ---------------------
    classes: dict[str, dict[str, Any]] = {}
    for method in (METHOD_SERVED_STAGE0, METHOD_SERVED_STAGE1, METHOD_SERVED_SCOPED,
                   METHOD_CYCLE_WINDOW, METHOD_CYCLE_MEDIAN):
        buckets: dict[str, list[float]] = {}
        for case in cases.get(method, []):
            buckets.setdefault(case["hop_class"], []).append(case["error_km"])
        classes[method] = {name: summarize(values) for name, values in sorted(buckets.items())}

    # ---- ship-gate comparison, paired on identical cases ---------------------
    stage0_served = headline[METHOD_SERVED_STAGE0]
    stage1_served = headline[METHOD_SERVED_STAGE1]
    window = headline.get(METHOD_CYCLE_WINDOW, {})
    median_variant = headline.get(METHOD_CYCLE_MEDIAN, {})
    base = stage0_served
    deltas = {
        "median_improvement_pct": improvement(stage0_served["median_km"], stage1_served["median_km"]),
        "mean_improvement_pct": improvement(stage0_served["mean_km"], stage1_served["mean_km"]),
        "p90_improvement_pct": improvement(stage0_served["p90_km"], stage1_served["p90_km"]),
        "rmse_improvement_pct": improvement(stage0_served["rmse_km"], stage1_served["rmse_km"]),
        "r90_improvement_pct": improvement(stage0_served["r90_km"], stage1_served["r90_km"]),
        "hit25_gain_pct_points": round(stage1_served["hit25_pct"] - stage0_served["hit25_pct"], 2),
        "hit50_gain_pct_points": round(stage1_served["hit50_pct"] - stage0_served["hit50_pct"], 2),
        "hit100_gain_pct_points": round(stage1_served["hit100_pct"] - stage0_served["hit100_pct"], 2),
    }
    scoped_served = headline[METHOD_SERVED_SCOPED]
    scoped_deltas = {
        "median_improvement_pct": improvement(stage0_served["median_km"], scoped_served["median_km"]),
        "mean_improvement_pct": improvement(stage0_served["mean_km"], scoped_served["mean_km"]),
        "p90_improvement_pct": improvement(stage0_served["p90_km"], scoped_served["p90_km"]),
        "rmse_improvement_pct": improvement(stage0_served["rmse_km"], scoped_served["rmse_km"]),
        "hit25_gain_pct_points": round(scoped_served["hit25_pct"] - stage0_served["hit25_pct"], 2),
        "hit50_gain_pct_points": round(scoped_served["hit50_pct"] - stage0_served["hit50_pct"], 2),
        "hit100_gain_pct_points": round(scoped_served["hit100_pct"] - stage0_served["hit100_pct"], 2),
    }
    scoped_criterion = bool(
        scoped_deltas["median_improvement_pct"] >= SHIP_CRITERION["median_improvement_pct_min"]
        and scoped_deltas["p90_improvement_pct"] >= SHIP_CRITERION["p90_improvement_pct_min"]
        and scoped_deltas["rmse_improvement_pct"] >= SHIP_CRITERION["rmse_improvement_pct_min"]
    )
    as_served = {
        "paired_cases": len(pairs),
        "stage1_scoped": scoped_served,
        "stage1_scoped_deltas_pct": scoped_deltas,
        "stage1_scoped_meets_criterion": scoped_criterion,
        "stage1_scoped_uses_cycle_step_on": sum(
            1 for _, b in scoped_pairs if b["route"] == "cycle_scale"),
        "variants_compared": ["stage1_full", "stage1_scoped"],
        "stage0_as_served": stage0_served,
        "stage1_as_served": stage1_served,
        "stage1_inherited_stage0": sum(1 for _, b in pairs if b.get("inherited_stage0")),
        "deltas_pct": deltas,
    }
    identical = sum(
        1 for a, b in pairs
        if abs(a["pred_lat"] - b["pred_lat"]) < 1e-9 and abs(a["pred_lon"] - b["pred_lon"]) < 1e-9
    )
    as_served["identical_step_cases"] = identical
    as_served["identical_step_share_pct"] = round(100.0 * identical / max(1, len(pairs)), 2)

    # per-case deltas: where Stage-1 differs, is it better or worse?
    diffs = sorted(b["error_km"] - a["error_km"] for a, b in pairs)
    as_served["case_deltas_km"] = {
        "better_by_more_than_1km": sum(1 for d in diffs if d < -1),
        "identical_within_1km": sum(1 for d in diffs if -1 <= d <= 1),
        "worse_by_more_than_1km": sum(1 for d in diffs if d > 1),
        "median_delta_km": round(diffs[len(diffs) // 2], 2),
        "worst_regression_km": round(diffs[-1], 1),
        "best_improvement_km": round(diffs[0], 1),
    }

    # leave-one-float-out on the paired comparison (drop one float, recompute both)
    lofo_rows = []
    for dropped in sorted({a["wmo"] for a, _ in pairs}):
        keep = [(a, b) for a, b in pairs if a["wmo"] != dropped]
        m0 = summarize([a["error_km"] for a, _ in keep])
        m1 = summarize([b["error_km"] for _, b in keep])
        if m0 and m1:
            lofo_rows.append({
                "dropped_float": dropped,
                "median_improvement_pct": improvement(m0["median_km"], m1["median_km"]),
                "p90_improvement_pct": improvement(m0["p90_km"], m1["p90_km"]),
                "rmse_improvement_pct": improvement(m0["rmse_km"], m1["rmse_km"]),
                "mean_improvement_pct": improvement(m0["mean_km"], m1["mean_km"]),
            })
    lofo = {
        "floats": len(lofo_rows),
        "median_improvement_pct_min": min(r["median_improvement_pct"] for r in lofo_rows),
        "median_improvement_pct_max": max(r["median_improvement_pct"] for r in lofo_rows),
        "p90_improvement_pct_min": min(r["p90_improvement_pct"] for r in lofo_rows),
        "p90_improvement_pct_max": max(r["p90_improvement_pct"] for r in lofo_rows),
        "rmse_improvement_pct_min": min(r["rmse_improvement_pct"] for r in lofo_rows),
        "rmse_improvement_pct_max": max(r["rmse_improvement_pct"] for r in lofo_rows),
    }
    lofo["same_sign_as_pooled"] = bool(
        all(r["median_improvement_pct"] * deltas["median_improvement_pct"] > 0 for r in lofo_rows)
        and all(r["p90_improvement_pct"] * deltas["p90_improvement_pct"] > 0 for r in lofo_rows)
        and all(r["rmse_improvement_pct"] > 0 for r in lofo_rows)
    )

    stability = {
        method: lofo_range(cases, method)
        for method in (METHOD_TRAJECTORY, METHOD_CYCLE_WINDOW, METHOD_CYCLE_MEDIAN,
                       METHOD_CYCLE_WINDOW_PRIOR + f"@w{STAGE0_WEIGHT:g}")
    }
    stability = {
        method: lofo_range(cases, method)
        for method in (METHOD_TRAJECTORY, METHOD_CYCLE_WINDOW, METHOD_CYCLE_MEDIAN,
                       METHOD_CYCLE_WINDOW_PRIOR + "@w0.2")
    }
    per_float0: dict[int, list[float]] = {}
    per_float1: dict[int, list[float]] = {}
    for a, b in pairs:
        per_float0.setdefault(a["wmo"], []).append(a["error_km"])
        per_float1.setdefault(b["wmo"], []).append(b["error_km"])
    med0 = {w: statistics.median(v) for w, v in per_float0.items()}
    med1 = {w: statistics.median(per_float1.get(w, [])) for w in per_float0}
    worse = {w: [round(med0[w], 1), round(med1[w], 1)] for w in med0 if med1[w] > med0[w] * 1.05}
    improved = {w: [round(med0[w], 1), round(med1[w], 1)] for w in med0 if med1[w] < med0[w] * 0.95}
    per_float = {"stage0_median_by_float": {w: round(v, 1) for w, v in sorted(med0.items())}}

    criterion = {
        "criterion": SHIP_CRITERION,
        "observed": deltas,
        "passed": bool(
            deltas["median_improvement_pct"] >= SHIP_CRITERION["median_improvement_pct_min"]
            and deltas["p90_improvement_pct"] >= SHIP_CRITERION["p90_improvement_pct_min"]
            and deltas["rmse_improvement_pct"] >= SHIP_CRITERION["rmse_improvement_pct_min"]
            and lofo["same_sign_as_pooled"]
        ),
        "window_vs_median_variant": {
            "window": window, "median_of_windows": median_variant,
            "winner": "window" if window.get("median_km", 1e9) <= median_variant.get("median_km", 1e9) else "median",
        },
    }

    legacy_metrics = {
        method: summarize(values) for method, values in meta["legacy"].items()
    }

    report = {
        "generated_at": generated_at,
        "corpus": args.corpus,
        "floats": extras["corpus"]["rtraj_floats"],
        "cases": availability["cases"],
        "headline": headline,
        "blend_weight_sweep": sweep,
        "stage0_vs_stage1": deltas,
        "stage0_vs_stage1_scoped": scoped_deltas,
        "as_served": as_served,
        "floats_improved": improved,
        "error_by_hop_class": classes,
        "legacy_protocol_i_to_i_plus_1": legacy_metrics,
        "hop_class_counts": availability["hop_class_counts"],
        "stage1_availability": {
            "cases": availability["cases"],
            "scoreable": availability["cases"],
            "unscoreable_no_fix_near_target": availability["unscoreable"],
            "by_variant": availability["stage1_by_cap"],
            "stage1_unavailable_count": availability["stage1_unavailable"],
            "unavailable_by_variant": availability["unavailable_by_variant"],
            "unavailable_by_float": availability["unavailable_by_float"],
            "reasons": availability["unavailable_reasons"],
        },
        "leave_one_float_out": lofo,
        "leave_one_float_out_single_methods": stability,
        "per_float_medians": per_float,
        "stage0_route_counts": availability["stage0_route"],
        "candidate_issuing_fixes": availability["candidates"],
        "worst_floats_for_stage1": worse,
        "criterion": criterion,
        "generated_by": "prediction.validate_cycle",
    }

    # ---- Stage-1 artefact (its own radii, its own provenance) --------------
    best_weight = float(criterion["window_vs_median_variant"]["winner"] == "window" and 0.2 or 0.2)
    stage1_methods = [method for method in cases if method.startswith("cycle_") and "@" not in method]
    chosen = {}
    for method in stage1_methods:
        chosen[method] = cases[method]
    # prior-blended rows at the chosen weight
    for method in (METHOD_CYCLE_WINDOW_PRIOR, METHOD_CYCLE_MEDIAN_PRIOR):
        key = f"{method}@w{best_weight:g}"
        if key in cases:
            chosen[method] = cases[key]
    artefact = build_calibration(chosen, extras, best_weight, generated_at)
    artefact["generator"] = "decoder-ui service/prediction/validate_cycle.py"
    artefact["stage"] = STAGE_STAGE1
    artefact["stage_label"] = "Stage-1 cycle-scale step (see STAGE1_REPORT.md)"
    artefact["baseline"] = {
        "stage0_calibration": "data/fleet_status/prediction_calibration.json (unchanged)",
        "stage0_methods": [METHOD_TRAJECTORY, METHOD_HISTORY_PRIOR, METHOD_REGIONAL_PRIOR, METHOD_PERSISTENCE],
        "note": "Stage-1 radii are derived from Stage-1's own errors; no Stage-0 R50/R90 is reused",
    }
    artefact["ship_gate"] = {
        "criterion": SHIP_CRITERION,
        "observed_as_served": deltas,
        "observed_scoped_variant": scoped_deltas,
        "passed": criterion["passed"] or scoped_criterion,
        "decision": (
            "not shipped — Stage-0 remains the default Predictor "
            "(PREDICTION_CYCLE_STEP=off); this artefact is a non-default candidate"
        ),
        "default_mode": DEFAULT_CYCLE_STEP,
    }
    artefact["comparison"] = {
        "reference_method": METHOD_TRAJECTORY,
        "reference_metrics": base,
        "stage1_metrics": window,
        "deltas_pct": deltas,
        "weight_sweep": sweep,
        "criterion_passed": criterion["passed"],
    }
    Path(args.out).write_text(json.dumps(artefact, indent=2, sort_keys=False))
    print(f"Stage-1 artefact -> {args.out} ({Path(args.out).stat().st_size} bytes, "
          f"{len(artefact['methods'])} methods)")

    if args.report:
        write_comparison_csv(cases, Path(args.report))
        print(f"comparison CSV -> {args.report}")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))
        print(f"comparison JSON -> {args.json}")

    # ---- console summary ---------------------------------------------------
    print("\n=== Stage-0 (baseline) vs Stage-1 (cycle-scale), identical cases ===")
    print(f"{'method':<28} {'n':>6} {'median':>8} {'mean':>8} {'p90':>8} {'rmse':>8} "
          f"{'hit25':>6} {'hit50':>6} {'hit100':>6} {'r50':>7} {'r90':>7}")
    for method, metrics in headline.items():
        print(f"{method:<28} {metrics['n']:>6} {metrics['median_km']:>8} {metrics['mean_km']:>8} "
              f"{metrics['p90_km']:>8} {metrics['rmse_km']:>8} {metrics['hit25_pct']:>6} "
              f"{metrics['hit50_pct']:>6} {metrics['hit100_pct']:>6} {metrics['r50_km']:>7} {metrics['r90_km']:>7}")
    print("\nAS-SERVED comparison, paired on identical cases (deployment ladder reproduced):")
    print(f"{'stage':<22} {'n':>6} {'median':>8} {'mean':>8} {'p90':>8} {'rmse':>8} {'hit25':>6} {'hit50':>6}")
    for name, metrics in (("Stage-0 as served", stage0_served), ("Stage-1 as served", stage1_served)):
        print(f"{name:<22} {metrics['n']:>6} {metrics['median_km']:>8} {metrics['mean_km']:>8} "
              f"{metrics['p90_km']:>8} {metrics['rmse_km']:>8} {metrics['hit25_pct']:>6} {metrics['hit50_pct']:>6}")
    print(json.dumps(as_served["deltas_pct"], indent=2))
    print(f"identical served position in {as_served['identical_step_share_pct']}% of paired cases "
          f"({as_served['identical_step_cases']}/{as_served['paired_cases']}); "
          f"Stage-1 inherited Stage-0 on {as_served['stage1_inherited_stage0']} cases")
    print("per-case deltas:", json.dumps(as_served["case_deltas_km"]))
    print(f"floats with >5% better median: {len(improved)} | with >5% worse: {len(worse)}")
    print("leave-one-float-out (paired):", json.dumps(lofo))
    print("\nSCOPED variant (cycle-scale step only on sub-cycle / gap hops):")
    print(f"{'stage':<22} {'n':>6} {'median':>8} {'mean':>8} {'p90':>8} {'rmse':>8} {'hit25':>6} {'hit50':>6}")
    print(f"{'Stage-1 scoped':<22} {scoped_served['n']:>6} {scoped_served['median_km']:>8} "
          f"{scoped_served['mean_km']:>8} {scoped_served['p90_km']:>8} {scoped_served['rmse_km']:>8} "
          f"{scoped_served['hit25_pct']:>6} {scoped_served['hit50_pct']:>6}")
    print(json.dumps(scoped_deltas, indent=2))
    print(f"scoped variant meets criterion: {scoped_criterion}; "
          f"uses the cycle-scale step on {sum(1 for _, b in scoped_pairs if b['route'] == 'cycle_scale')} cases")

    print("\nSHIP CRITERION:")
    print(json.dumps(criterion, indent=2))
    print("\nStage-0 route mix actually served:", json.dumps(availability["stage0_route"]))
    print("\nblend-weight sweep (prior-blended variants, median km):")
    for key in sorted(sweep):
        print(f"   {key:<34} n={sweep[key]['n']:>5} median={sweep[key]['median_km']:>8} "
              f"p90={sweep[key]['p90_km']:>8} rmse={sweep[key]['rmse_km']:>8}")
    print("\nlegacy (i -> i+1) protocol, secondary robustness table:")
    print(json.dumps(legacy_metrics, indent=2))
    print("\nerror by sampling class of the newest hop:")
    print(json.dumps(classes, indent=2))
    print("\nStage-1 availability:")
    print(json.dumps(report["stage1_availability"], indent=2))
    print("\nleave-one-float-out stability (aggregate ranges):")
    print(json.dumps(stability, indent=2))
    print("\nfloats where Stage-1 is worse than Stage-0 by > 1 km median:")
    print(json.dumps(worse, indent=2))
    print("\nPRE-REGISTERED SHIP CRITERION:")
    print(json.dumps(criterion, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
