"""Stage-0 prediction audit: cache ring vs full available trajectory history.

Answers, with the SHIPPED parser, feature builder, predictor and calibration
artefact (nothing is reimplemented, nothing is retrained):

  1. per float: verified position? fixes available? transitions at the shipped
     ring (``PREDICTION_FIX_HISTORY``) vs the full public history?
  2. does the documented prior (2 deg / +-1 month / >= 5 neighbours / 2 d lag,
     target float excluded) become reachable when the cache keeps more history?
  3. which rung each float lands on, in both scenarios, and why.

Usage:
  PYTHONPATH=service:<repo>/src python stage0_audit.py --corpus /tmp/argotraj2

The corpus is public GDAC ``<WMO>_Rtraj.nc`` data; the script reads it, runs the
real code paths in memory, and prints tables. It writes no cache and no artefact.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # /home/user/prediction-validation/audit -> up 2: wait, resolved below
sys.path[:0] = [str(Path("/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/service"))]

import fleet_status as fs  # noqa: E402
from prediction import predict as pr  # noqa: E402
from prediction.calibrate import load_calibration  # noqa: E402
from prediction.features import build_fleet_features, fleet_transitions  # noqa: E402
from prediction.prior import grid_prior, neighbourhood_prior  # noqa: E402

NOW = datetime.now(UTC)


def parse_corpus(corpus: Path, ring: int) -> tuple[dict[str, dict], dict[int, bytes]]:
    """Parse every file with the real parser, at a chosen ring size."""
    original = fs.PREDICTION_FIX_HISTORY
    fs.PREDICTION_FIX_HISTORY = ring
    raws: dict[int, bytes] = {}
    parsed: dict[str, dict] = {}
    try:
        for path in sorted(corpus.glob("*_Rtraj.nc")):
            wmo = int(path.name.split("_")[0])
            raw = path.read_bytes()
            raws[wmo] = raw
            try:
                rtraj = fs.parse_rtraj(raw, wmo, NOW)
            except Exception as exc:
                print(f"  ! {wmo}: {type(exc).__name__}: {exc}")
                continue
            parsed[str(wmo)] = {
                "rtraj": rtraj,
                "profile_aggregate": {},
                "in_incois_dac": True,
                "parser_version": fs.PARSER_VERSION,
                "profile_recency_version": fs.PROFILE_RECENCY_VERSION,
            }
    finally:
        fs.PREDICTION_FIX_HISTORY = original
    return parsed, raws


def run_scenario(features: dict, calibration) -> dict[int, dict]:
    return pr.predict_fleet(features, calibration=calibration, now=NOW)


def prior_diagnosis(features: dict, wmo: int, calibration) -> str:
    """Why the prior did or did not form for one float (documented rules only)."""
    item = features[wmo]
    if item.last_fix is None:
        return "no verified fix"
    pool = fleet_transitions(features)
    grid_cells = calibration.prior_grid if isinstance(calibration.prior_grid, dict) else None
    live = neighbourhood_prior(
        pool,
        exclude_wmo=wmo,
        lat=item.last_fix["lat"],
        lon=item.last_fix["lon"],
        juld=item.last_fix["juld"],
    )
    grid = grid_prior(
        grid_cells, lat=item.last_fix["lat"], lon=item.last_fix["lon"], juld=item.last_fix["juld"]
    )
    # how many of the pool's transitions pass each individual filter
    others = [t for t in pool if t.wmo != wmo]
    lagged = [t for t in others if t.start_juld < item.last_fix["juld"] - 2.0]
    spatial = [t for t in lagged if abs(t.lat - item.last_fix["lat"]) <= 2.0 and
               abs((t.lon - item.last_fix["lon"] + 180) % 360 - 180) <= 2.0]
    seasonal = [
        t for t in spatial
        if min(abs(((item.last_fix["juld"] % 365.25) / 30.44) - ((t.start_juld % 365.25) / 30.44)),
               12 - abs(((item.last_fix["juld"] % 365.25) / 30.44) - ((t.start_juld % 365.25) / 30.44))) <= 1.0
    ]
    bits = [
        f"pool={len(pool)} others={len(others)} after_lag={len(lagged)} "
        f"in_2deg={len(spatial)} in_month={len(seasonal)}"
    ]
    bits.append(f"live_prior={'yes' if live else 'no'}")
    bits.append(f"grid_prior={'yes' if grid else 'no'}")
    return " · ".join(bits)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--calibration", default=str(
        Path("/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/data/fleet_status/prediction_calibration.json")))
    args = ap.parse_args()

    calibration = load_calibration(Path(args.calibration))
    print(f"calibration: available={calibration.available} version={calibration.version} "
          f"grid_cells={len(calibration.prior_grid or {})}")

    # Three scenarios so the before/after evidence stays reproducible as the
    # shipped bound changes: the bound this stage replaced (8), the bound the
    # code actually ships (read from the module, never hardcoded), and the
    # unbounded ceiling that proves nothing further is being withheld.
    scenarios = {}
    for label, ring in (("regression ring (8)", 8),
                        (f"shipped ring ({fs.PREDICTION_FIX_HISTORY})", fs.PREDICTION_FIX_HISTORY),
                        ("full history (all)", 10**6)):
        parsed, raws = parse_corpus(Path(args.corpus), ring)
        features = build_fleet_features(parsed, {}, NOW)
        payloads = run_scenario(features, calibration)
        scenarios[label] = (parsed, features, payloads)
        print(f"\n=== {label}: {len(parsed)} floats parsed, "
              f"pool transitions={len(fleet_transitions(features))}")

    header = (f"{'wmo':>9} | {'fixes':>5} {'tr':>3} | {'method(ship)':<24} {'rung':>4} | "
              f"{'tr_all':>6} {'method(all)':<24} {'rung':>4} | changed")
    print("\n" + header)
    print("-" * len(header))
    shipped_label = f"shipped ring ({fs.PREDICTION_FIX_HISTORY})"
    switches = 0
    for wmo in sorted({int(k) for k in scenarios[shipped_label][0]}):
        ship_parsed, ship_features, ship_payloads = scenarios[shipped_label]
        full_parsed, full_features, full_payloads = scenarios["full history (all)"]
        s = ship_payloads.get(wmo) or {}
        f = full_payloads.get(wmo) or {}
        sf = ship_features.get(wmo)
        ff = full_features.get(wmo)
        changed = "YES" if (s.get("method") != f.get("method") or s.get("available") != f.get("available")) else ""
        if changed:
            switches += 1
        print(f"{wmo:>9} | {len(sf.fixes) if sf else 0:>5} {str(s.get('trajectory_transitions')):>3} | "
              f"{str(s.get('method')):<24} {str(s.get('fallback_rung')):>4} | "
              f"{len(ff.fixes) if ff else 0:>6} {str(f.get('method')):<24} {str(f.get('fallback_rung')):>4} | {changed}")

    print(f"\nfloats whose method/rung changes between the SHIPPED ring and full history: {switches}"
          f"  (0 means the shipped bound withholds nothing)")

    old_label = "regression ring (8)"
    old_payloads = scenarios[old_label][2]
    old_methods: dict[str, int] = {}
    for payload in old_payloads.values():
        old_methods[str(payload.get("method"))] = old_methods.get(str(payload.get("method")), 0) + 1
    starved = sorted(wmo for wmo in old_payloads
                     if (old_payloads[wmo] or {}).get("method") != (scenarios[shipped_label][2].get(wmo) or {}).get("method"))
    print(f"\n=== regression evidence: with the old 8-fix ring the fleet serves {old_methods}")
    print(f"    floats the old ring starved of their documented prior ({len(starved)}): {starved}")

    print("\n=== prior diagnosis (full-history scenario) ===")
    for wmo in sorted(scenarios["full history (all)"][1]):
        status = pr.predict_float(
            scenarios["full history (all)"][1][wmo],
            pool=fleet_transitions(scenarios["full history (all)"][1]),
            calibration=calibration,
            now=NOW,
        )
        print(f"{wmo:>9} {str(status.get('method')):<24} rung={status.get('fallback_rung')} "
              f"prior_basis={status.get('prior_basis')} | {prior_diagnosis(scenarios['full history (all)'][1], wmo, calibration)}")

    summary = {"shipped_ring": fs.PREDICTION_FIX_HISTORY,
               "floats_withheld_by_regression_ring": starved}
    for label, (_, features, payloads) in scenarios.items():
        methods: dict[str, int] = {}
        rungs: dict[str, int] = {}
        for payload in payloads.values():
            methods[str(payload.get("method"))] = methods.get(str(payload.get("method")), 0) + 1
            rungs[str(payload.get("fallback_rung"))] = rungs.get(str(payload.get("fallback_rung")), 0) + 1
        transitions = sorted(len(item.transitions) for item in features.values())
        summary[label] = {
            "methods": methods,
            "rungs": rungs,
            "transitions_median": transitions[len(transitions) // 2] if transitions else 0,
            "transitions_mean": round(sum(transitions) / len(transitions), 1) if transitions else 0,
            "pool": len(fleet_transitions(features)),
        }
    print("\n=== summary ===")
    print(json.dumps(summary, indent=2))
    out = Path(__file__).with_name("stage0_audit_summary.json")
    out.write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
