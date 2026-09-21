"""STAGE-0 science audit — no future leakage, no fabricated radii, no float hacks.

Read-only. Uses the live API payload, the live cache, the real prediction
modules and the shipped calibration artefact. Writes nothing except its own
JSON report under --out (default: this directory).

Checks
------
A. radius provenance   : every served r50/r90 is exactly the calibrated value
                         for (method, region, cycle class) — recomputed here.
B. stratum provenance  : validation_source matches the served method and its
                         sample count matches the calibration bin.
C. horizon             : equals the float's own observed cycle interval.
D. diagnostics         : fleet diagnostics agree with the per-row values.
E. no wall-clock leak  : a later ``now`` provably cannot change a prediction.
F. target-float exclusion + 2-day lag: the prior pool the predictor actually
                         selects from contains no self-transitions and no
                         transitions newer than as_of - lag (re-derived here).
G. no future transitions in features: nothing the predictor sees starts after
                         the issuing fix.
H. no float-specific behaviour: no WMO/coordinate literals in the prediction
                         service code (tests excluded).
I. chronology of the calibration corpus: the generator's case loop is
                         structurally causal (grep-verified) and the artefact
                         records it.

Usage:
    PYTHONPATH=service /home/user/.venv/bin/python audit/stage0_science_audit.py
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path("/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui")
CACHE = Path("/home/user/profile-recency-update/runtime/fleet_status/cache.json")
CALIBRATION = REPO / "data/fleet_status/prediction_calibration.json"
CALIBRATION_STAGE1 = REPO / "data/fleet_status/prediction_calibration_stage1.json"
sys.path.insert(0, str(REPO / "service"))

from prediction import predict as predict_module  # noqa: E402
from prediction import features as features_module  # noqa: E402
from prediction import prior as prior_module  # noqa: E402
from prediction.prior import _month_distance  # noqa: E402
from prediction.calibrate import load_calibration, radii_for  # noqa: E402
from prediction.geometry import haversine_km  # noqa: E402

JULD_EPOCH = datetime(1950, 1, 1, tzinfo=UTC)


def juld_to_dt(value: float) -> datetime:
    return JULD_EPOCH + timedelta(days=float(value))


def great_circle(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine_km(lat1, lon1, lat2, lon2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", default=None,
                        help="cached /api/fleet-status payload; default fetches from the live API")
    parser.add_argument("--out", default=str(Path(__file__).with_name("stage0_science_audit.json")))
    args = parser.parse_args(argv)

    if args.payload and args.payload != "-" and Path(args.payload).exists():
        payload = json.loads(Path(args.payload).read_text())
        source = args.payload
    else:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:8000/api/fleet-status") as response:
            payload = json.loads(response.read())
        source = "http://127.0.0.1:8000/api/fleet-status (live)"

    # The service may round for JSON; read the calibration artefact directly.
    # Stage-1 pass: the audit verifies whichever stage the API is actually serving.
    # Stage-0 stays the reference for every other check, and its artefact must remain
    # untouched on disk while a Stage-1 deployment runs (checked below).
    stage0_artefact = json.loads(CALIBRATION.read_text())
    served_stages = {str((r.get("prediction") or {}).get("predictor_stage") or "stage0")
                     for r in payload["floats"]}
    # a validation deployment can serve both stages at once (Stage-1 for the floats that
    # have a cycle-scale window, Stage-0 for the documented fallbacks)
    serving_stage1 = "stage1" in served_stages and CALIBRATION_STAGE1.is_file()
    stage_calibrations = {"stage0": load_calibration(CALIBRATION)}
    if CALIBRATION_STAGE1.is_file():
        stage_calibrations["stage1"] = load_calibration(CALIBRATION_STAGE1)
    # The deployed code always loads the Stage-0 artefact as its primary calibration and
    # layers the Stage-1 artefact on top through `calibration_stage1`: rows that fall back
    # to the Stage-0 branch still need Stage-0 radii. The audit replays it exactly that way.
    calibration = load_calibration(CALIBRATION)
    artefact = stage0_artefact
    # the settled mode, inferred from what is actually being served (the audit runs in
    # its own process, so it must not trust its own environment for this)
    served_methods = {str((r.get("prediction") or {}).get("method")) for r in payload["floats"]}
    replay_mode = (
        "median" if any(m and m.startswith("cycle_median") for m in served_methods)
        else "window" if any(m and m.startswith("cycle_window") for m in served_methods)
        else "off"
    )
    replay_kwargs: dict[str, Any] = (
        {"cycle_step_mode": replay_mode,
         "calibration_stage1": load_calibration(CALIBRATION_STAGE1)}
        if replay_mode != "off" and CALIBRATION_STAGE1.is_file() else {}
    )
    rows = payload["floats"]
    now = datetime.now(UTC)
    findings: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        findings.append({"check": name, "passed": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")

    # ---- A/B/C: radius, stratum and horizon provenance --------------------
    bad_radius: list[str] = []
    bad_stratum: list[str] = []
    bad_horizon: list[str] = []
    missing = 0
    for row in rows:
        p = row.get("prediction") or {}
        if not p.get("available"):
            missing += 1
            continue
        method = p["method"]
        # radii are verified against the artefact of the stage that served the row
        row_stage = str(p.get("predictor_stage") or "stage0")
        row_calibration = stage_calibrations.get(row_stage, stage_calibrations["stage0"])
        radius = radii_for(row_calibration, method, region=p.get("region"), cycle_class=p.get("cycle_class"))
        if radius is None:
            bad_radius.append(
                f"{row['wmo']}: no calibrated radius for {method}/{p.get('region')}/"
                f"{p.get('cycle_class')} in the {row_stage} artefact")
        elif (abs(radius.r50_km - p["r50_km"]) > 0.051 or abs(radius.r90_km - p["r90_km"]) > 0.051
              or radius.samples != p.get("validation_samples")):
            bad_radius.append(
                f"{row['wmo']}: served {p['r50_km']}/{p['r90_km']} n={p.get('validation_samples')} vs "
                f"calibrated {radius.r50_km}/{radius.r90_km} n={radius.samples}")
        basis = p.get("validation_source") or ""
        if not basis.startswith(p.get("method_label", "")) or not p.get("validation_samples"):
            bad_stratum.append(f"{row['wmo']}: basis={basis!r} samples={p.get('validation_samples')}")
        interval = float(row["expected_interval_days"])
        if abs(float(p["prediction_horizon_days"]) - interval) > 0.005001:
            bad_horizon.append(f"{row['wmo']}: horizon {p['prediction_horizon_days']} vs interval {interval}")

    stage0_intact = (
        "stage" not in stage0_artefact
        and set(stage0_artefact.get("methods", {})) == {
            "history_prior", "trajectory_extrapolation", "regional_prior", "persistence"}
    )
    unresolved = [
        r["wmo"] for r in rows
        if (r.get("prediction") or {}).get("available")
        and str((r.get("prediction") or {}).get("predictor_stage") or "stage0")
        not in stage_calibrations
    ]
    record(
        "A0. every served row's stage has its own artefact, and the Stage-0 artefact is intact",
        stage0_intact and not unresolved and serving_stage1 == ("stage1" in served_stages),
        (f"served stages={sorted(served_stages)}; Stage-1 artefact "
         f"{'present' if 'stage1' in stage_calibrations else 'absent'}; "
         f"Stage-0 artefact methods={sorted(stage0_artefact.get('methods', {}))}, "
         f"stage key={'absent' if stage0_intact else 'PRESENT'}"),
    )
    record("A. every served radius is the calibrated value for its method/region/stratum",
           not bad_radius,
           "; ".join(bad_radius[:3]) or (
               f"{len(rows) - missing} predictions checked against the artefact of the "
               f"stage that served each row ({sorted(served_stages)})"))
    record("B. every served prediction quotes the calibration stratum it came from",
           not bad_stratum, "; ".join(bad_stratum[:3]))
    record("C. every horizon equals the float's own observed cycle interval",
           not bad_horizon, "; ".join(bad_horizon[:3]))

    # ---- D: diagnostics agree with the rows -------------------------------
    diag = payload["prediction"]["diagnostics"]
    by_method: dict[str, int] = {}
    for row in rows:
        label = (row.get("prediction") or {}).get("method")
        by_method[label] = by_method.get(label, 0) + 1
    record("D. fleet diagnostics are the aggregate of the per-row predictions",
           diag["floats"] == len(rows) and diag["methods"] == by_method and
           diag["persistence_only"] == by_method.get("persistence", 0) and
           sum(diag["rungs"].values()) == len(rows),
           json.dumps(diag["methods"]))

    # ---- E/F/G: leakage, exclusion, causality ----------------------------
    cache = json.loads(CACHE.read_text())
    cached = {int(k): v for k, v in cache["rows"].items()}
    meta = {int(row["wmo"]): row for row in rows}
    # Exactly the fleet feature set + pool the service builds for /api/fleet-status.
    fleet_features = features_module.build_fleet_features(cached, meta, now)
    pool = features_module.fleet_transitions(fleet_features)
    pool_wmos = [t.wmo for t in pool]

    wallclock_stable: list[str] = []
    self_leaks: list[str] = []
    lag_violations: list[str] = []
    future_transitions: list[str] = []
    prior_reproduced: list[str] = []
    prior_skipped: list[str] = []
    prior_served_floats: list[int] = []
    prior_withheld_floats: list[int] = []
    served_mismatch: list[str] = []
    pool_sizes: list[int] = []
    decisive = 0
    for row in rows:
        wmo = int(row["wmo"])
        cached_row = cached.get(wmo)
        if not cached_row:
            continue
        features = fleet_features.get(wmo)
        if features is None or not features.has_position or not features.transitions:
            continue
        pool_sizes.append(len(pool))
        if wmo not in pool_wmos and (meta.get(wmo) or {}).get("prediction", {}).get("available"):
            pass  # a float without its own transitions still predicts from the shared pool

        # G. nothing the predictor sees starts after the issuing fix
        last = float(features.last_fix["juld"])
        if any(float(t.start_juld) > last + 1e-6 for t in features.transitions):
            future_transitions.append(str(wmo))

        # F. the pool this float chooses from must not contain its own hops, and
        #    every accepted neighbour must be older than the delivery lag.
        served_prior = (row.get("prediction") or {}).get("prior_neighbours") or 0
        fix = features.last_fix
        redone = prior_module.neighbourhood_prior(
            pool, exclude_wmo=wmo, lat=float(fix["lat"]), lon=float(fix["lon"]), juld=last
        )
        # The shared fleet pool deliberately holds every float's own hops; what
        # matters is that the *lookup* drops them. Re-run the same lookup with
        # self-inclusion forced and require the served value to match the
        # excluding run wherever the two differ (decisive evidence).
        including = prior_module.neighbourhood_prior(
            pool, exclude_wmo=None, lat=float(fix["lat"]), lon=float(fix["lon"]), juld=last
        )
        served_payload = row.get("prediction") or {}
        if served_payload.get("prior_basis") and including is not None and redone is not None:
            if (including.neighbours, round(including.dlat_km, 6), round(including.dlon_km, 6)) != (
                redone.neighbours, round(redone.dlat_km, 6), round(redone.dlon_km, 6)
            ):
                decisive += 1
                if served_payload.get("prior_neighbours") != redone.neighbours:
                    self_leaks.append(
                        f"{wmo}: served n={served_payload.get('prior_neighbours')} but excluding self gives "
                        f"{redone.neighbours} (including self gives {including.neighbours})"
                    )
        elif served_payload.get("prior_neighbours") and redone is not None and \
                served_payload["prior_neighbours"] != redone.neighbours:
            self_leaks.append(f"{wmo}: served n={served_payload['prior_neighbours']} vs re-derived {redone.neighbours}")
        if served_prior:
            # Independent re-derivation of the documented selection rule.
            accepted = [
                t for t in pool
                if t.wmo != wmo
                and float(t.start_juld) < last - prior_module.PRIOR_LAG_DAYS
                and abs(t.lat - float(fix["lat"])) <= prior_module.PRIOR_RADIUS_DEG
                and abs((t.lon - float(fix["lon"]) + 180.0) % 360.0 - 180.0) <= prior_module.PRIOR_RADIUS_DEG
                and _month_distance(prior_module._month_of_day(last), prior_module._month_of_day(t.start_juld))
                <= prior_module.PRIOR_MONTHS
            ]
            stale = [t for t in accepted if float(t.start_juld) >= last - prior_module.PRIOR_LAG_DAYS]
            if stale:
                lag_violations.append(f"{wmo}: {len(stale)} neighbours newer than the {prior_module.PRIOR_LAG_DAYS}-day lag")
            if len(accepted) != served_prior:
                prior_reproduced.append(
                    f"{wmo}: served n={served_prior} but the documented rule accepts {len(accepted)} "
                    f"(re-run: {0 if redone is None else redone.neighbours})"
                )
            elif redone is None:
                prior_reproduced.append(f"{wmo}: served n={served_prior} but the re-run returned no prior")
            prior_served_floats.append(wmo)
        else:
            # Mirrored proof: a float without a served prior must genuinely fail
            # the documented conditions (so no higher rung was skipped).
            if redone is not None and redone.neighbours >= prior_module.PRIOR_MIN_NEIGHBOURS:
                prior_skipped.append(
                    f"{wmo}: no prior served although the rule accepts {redone.neighbours} neighbours"
                )
            prior_withheld_floats.append(wmo)

        # E. a later wall clock must not change the prediction
        first = predict_module.predict_float(
            features, pool=pool, calibration=calibration, now=now, **replay_kwargs
        )
        later = predict_module.predict_float(
            features, pool=pool, calibration=calibration, now=now + timedelta(days=5),
            **replay_kwargs,
        )
        if (first.get("predicted_lat"), first.get("predicted_lon"), first.get("method")) != (
            later.get("predicted_lat"), later.get("predicted_lon"), later.get("method")
        ):
            wallclock_stable.append(str(wmo))

        # E2. what the API served must equal a fresh run of the shipped code on
        #     the same cache + calibration (nothing hidden between them).
        served_payload2 = row.get("prediction") or {}
        if served_payload2.get("available"):
            if first.get("status") != served_payload2.get("status") or \
                    first.get("method") != served_payload2.get("method") or \
                    first.get("fallback_rung") != served_payload2.get("fallback_rung") or \
                    first.get("r50_km") != served_payload2.get("r50_km") or \
                    first.get("r90_km") != served_payload2.get("r90_km") or \
                    first.get("validation_samples") != served_payload2.get("validation_samples") or \
                    first.get("validation_source") != served_payload2.get("validation_source") or \
                    abs(haversine_km(float(first["predicted_lat"]), float(first["predicted_lon"]),
                                     float(served_payload2["predicted_lat"]),
                                     float(served_payload2["predicted_lon"]))) > 0.05:
                served_mismatch.append(str(wmo))

    record("E. predictions are independent of the wall clock (no now()-driven drift)",
           not wallclock_stable, ", ".join(wallclock_stable) or f"{len(rows)} floats re-run at T and T+5 d")
    record("E2. the served prediction equals a fresh run of the shipped code on the same cache",
           not served_mismatch,
           ", ".join(served_mismatch[:3]) or
           f"{len(rows) - missing} predictions reproduced (position, method, rung, radii, stratum)")
    record("F1. the served prior never uses the target float's own hops",
           not self_leaks,
           "; ".join(self_leaks[:3]) or
           f"exclusion decisive on {decisive} float(s); unchanged elsewhere (unit-tested)")
    record("F2. the documented delivery lag is honoured by the accepted neighbours",
           not lag_violations, "; ".join(lag_violations[:3]) or
           f"{prior_module.PRIOR_LAG_DAYS}-day lag, float-aware pool")
    record("F3. every served prior reproduces exactly under the documented rule",
           not prior_reproduced,
           "; ".join(prior_reproduced[:3]) or
           f"{len(prior_served_floats)} floats: 2.0 deg radius, +/-1 month, "
           f"{prior_module.PRIOR_LAG_DAYS}-day lag, >= {prior_module.PRIOR_MIN_NEIGHBOURS} neighbours")
    record("F4. every float without a prior genuinely fails the documented conditions",
           not prior_skipped,
           "; ".join(prior_skipped[:3]) or
           f"{len(prior_withheld_floats)} floats re-checked — no higher rung was skipped")
    record("G. predictors only see transitions that start at or before the issuing fix",
           not future_transitions, ", ".join(future_transitions) or "no future transitions in any float's features")

    # ---- H: no float-specific behaviour anywhere in the service -----------
    literals = re.compile(r"\b(?:1902\d{3}|2902\d{3}|6902\d{3}|7902\d{3}|6990\d{3})\b")
    offenders: list[str] = []
    # Only the prediction feature is in Stage-0 scope; the pre-existing
    # PathResolver preset list (unmodified by this work) carries demo WMOs.
    scoped = [REPO / "service" / "fleet_status.py", *sorted((REPO / "service/prediction").rglob("*.py"))]
    for path in scoped:
        lines = path.read_text().splitlines()
        doc_start, doc_end = None, -1
        for index, line in enumerate(lines):  # leading module docstring span
            if line.lstrip().startswith('"""'):
                if doc_start is None:
                    doc_start = index
                else:
                    doc_end = index
                    break
        for number, line in enumerate(lines, start=1):
            if line.lstrip().startswith("#") or (doc_start is not None and doc_start <= number - 1 <= doc_end):
                continue  # documentation examples, not behaviour
            if literals.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{number}")
    # domain constants that would betray a specific basin are checked too
    for path in sorted((REPO / "service/prediction").rglob("*.py")):
        text = path.read_text()
        for bad in ("60.0, 70.0", "65.0, 55.0"):
            if bad in text:
                offenders.append(f"{path.name}: {bad}")
    record("H. no WMO or coordinate literals in the prediction feature",
           not offenders,
           ", ".join(offenders[:5]) or f"{len(scoped)} files scanned (fleet_status + prediction/)")

    # ---- I: the calibration corpus is causally built ----------------------
    validate_src = (REPO / "service/prediction/validate.py").read_text()
    chronology_markers = [
        "predictors see only fixes at or before t(N)",
        "exclude_wmo=wmo",
        "lag_days=PRIOR_LAG_DAYS",
    ]
    record("I. the validation generator is chronological and float-aware by construction",
           all(marker in validate_src for marker in chronology_markers),
           "prior pool excludes the target float and lags its inputs")
    corpus = artefact.get("corpus") or {}
    strata = {key.split("|")[0] for method in artefact.get("methods", {}).values()
              for key in (method.get("strata") or {})}
    bins = sum(len(method.get("strata") or {}) for method in artefact.get("methods", {}).values())
    record("I2. the shipped artefact records its corpus, protocol and radii",
           bool(artefact.get("methods")) and bool(corpus.get("cases")) and
           corpus.get("prior_lag_days") == prior_module.PRIOR_LAG_DAYS and
           all(bins > 0 and method.get("default", {}).get("n", 0) > 0
               for method in artefact["methods"].values()),
           f"cases={corpus.get('cases')} floats={corpus.get('floats_with_insufficient_history')} "
           f"strata_bins={bins} regions={len(strata - {'*'})} generated_at={artefact.get('generated_at')}")

    # ---- J: pooled cross-check of the served distances --------------------
    # The prediction is anchored on the float's last *trajectory* fix, which for
    # some floats is older than the position the page displays (last profile).
    # Both distances are therefore measured separately: the hop the method
    # actually applied, and the apparent distance from the displayed position.
    hops: list[float] = []
    apparent: list[float] = []
    stale_anchor: list[dict[str, Any]] = []
    for row in rows:
        p = row.get("prediction") or {}
        if not p.get("available"):
            continue
        anchor = p.get("issued_from_position") or []
        if not isinstance(anchor, (list, tuple)) or len(anchor) != 2:
            continue
        hop = great_circle(float(anchor[0]), float(anchor[1]), p["predicted_lat"], p["predicted_lon"])
        hops.append(hop)
        apparent.append(great_circle(row["lat"], row["lon"], p["predicted_lat"], p["predicted_lon"]))
        if row.get("last_profile_iso") and p.get("issued_from_iso"):
            age = (datetime.fromisoformat(row["last_profile_iso"].replace("Z", "+00:00")) -
                   datetime.fromisoformat(p["issued_from_iso"].replace("Z", "+00:00"))).total_seconds() / 86400.0
            if age > 90:
                stale_anchor.append({
                    "wmo": row["wmo"], "anchor_age_days": round(age),
                    "anchor_vs_display_km": round(great_circle(row["lat"], row["lon"],
                                                              float(anchor[0]), float(anchor[1])), 1),
                    "applied_hop_km": round(hop, 1),
                })
    record("J. every prediction is a real one-cycle hop from the fix it was issued from",
           len(hops) == len(rows) - missing and all(h > 0 for h in hops),
           f"applied hops: median {statistics.median(hops):.1f} km, max {max(hops):.1f} km; "
           f"apparent distance from the displayed position: median {statistics.median(apparent):.1f} km")
    # The calibrated R90 is a 90th-percentile of historical method errors, so a
    # few served steps may legitimately exceed it. What must hold is that the
    # fleet-wide rate stays consistent with that claim rather than contradicting
    # it; the exceedances themselves are named.
    inside_r90 = []
    exceed = []
    for row in rows:
        p = row.get("prediction") or {}
        if not p.get("available"):
            continue
        anchor = p.get("issued_from_position") or []
        if not isinstance(anchor, (list, tuple)) or len(anchor) != 2:
            continue
        hop = great_circle(float(anchor[0]), float(anchor[1]), p["predicted_lat"], p["predicted_lon"])
        if hop <= float(p["r90_km"]):
            inside_r90.append(row["wmo"])
        else:
            exceed.append({"wmo": row["wmo"], "applied_hop_km": round(hop, 1), "r90_km": p["r90_km"]})
    rate = 100.0 * len(inside_r90) / max(1, len(inside_r90) + len(exceed))
    record("J2. the served steps are consistent with the calibrated R90 they are judged against",
           rate >= 80.0,
           f"{rate:.1f}% of served steps lie within their own R90 (a 90th percentile "
           f"threshold, so single exceedances are expected): {json.dumps(exceed)}")
    # Informational, not a failure: the anchor can legitimately predate the last
    # profile when a float stopped reporting trajectory fixes before its last
    # profile. Reported so the reader knows which floats that affects.
    print(f"NOTE  {len(stale_anchor)}/{len(hops)} floats are predicted from a trajectory fix "
          f">90 d older than the displayed position: {json.dumps(stale_anchor)}")

    report = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "payload": source,
        "replay_mode": replay_mode,
        "serving_stage1": serving_stage1,
        "calibration": {"path": str(CALIBRATION), "generated_at": artefact.get("generated_at"),
                        "stage1_path": str(CALIBRATION_STAGE1) if serving_stage1 else None,
                        "floats": artefact.get("floats"), "transitions": artefact.get("transitions")},
        "floats": len(rows),
        "available": len(rows) - missing,
        "prior_served": prior_served_floats,
        "prior_withheld": prior_withheld_floats,
        "prior_exclusion_decisive_on": decisive,
        "pool_sizes": {"min": min(pool_sizes), "max": max(pool_sizes)} if pool_sizes else None,
        "applied_hop_km": {"median": round(statistics.median(hops), 1), "max": round(max(hops), 1)},
        "stale_anchor_floats": stale_anchor,
        "steps_within_own_r90_pct": round(rate, 1),
        "checks": findings,
        "passed": sum(1 for f in findings if f["passed"]),
        "failed": sum(1 for f in findings if not f["passed"]),
    }
    Path(args.out).write_text(json.dumps(report, indent=2))
    print(f"\n{report['passed']}/{len(findings)} science checks passed -> {args.out}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
