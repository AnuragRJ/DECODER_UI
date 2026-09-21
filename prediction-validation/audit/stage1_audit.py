"""STAGE-1 step 1 — READ-ONLY audit of the Stage-0 predictor's step choice.

Answers, with the shipped parser, feature builder and geometry (nothing
reimplemented, nothing retrained):

  1. distribution of last-transition duration / expected cycle interval;
  2. floats whose newest transition is sub-cycle (< 0.5 x interval);
  3. floats whose newest transition spans multiple cycles (> 1.5 x interval);
  4. the effect of using the newest transition displacement: chronological,
     leakage-safe replay of Stage-0's rung-4 trajectory step, split by the
     sampling class of the hop that produced it;
  5. availability of recent windows that could form a cycle-scale step (a pair
     of fixes whose span is close to one expected interval), which bounds how
     often a Stage-1 method can even be computed.

Read-only: reads the public ``<WMO>_Rtraj.nc`` corpus and the cached fleet rows,
writes only this directory's own audit outputs.

    PYTHONPATH=service:src /home/user/.venv/bin/python audit/stage1_audit.py --corpus /tmp/argotraj2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path("/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui")
sys.path[:0] = [str(REPO / "service"), str(REPO / "src")]

import fleet_status as fs  # noqa: E402
import profile_cycle  # noqa: E402
from prediction.geometry import destination, displacement_km, haversine_km  # noqa: E402
from prediction.features import MAX_TRANSITION_DAYS, build_fleet_features  # noqa: E402

CACHE = Path("/home/user/profile-recency-update/runtime/fleet_status/cache.json")
NOW = datetime.now(UTC)

#: Sampling classes for one observed hop, by hop_days / expected_interval.
SUB_CYCLE = 0.5
CYCLE_SCALE = 1.5
MULTI_CYCLE = 1.5

#: A cycle-scale window must land inside this band around the expected interval.
WINDOW_LOW = 0.75
WINDOW_HIGH = 1.25
#: Beyond this, a window is treated as spanning k whole cycles and normalised.
WINDOW_MAX = 3.0


def hop_class(days: float, interval: float) -> str:
    ratio = days / interval if interval else float("inf")
    if ratio < SUB_CYCLE:
        return "sub_cycle"
    if ratio <= CYCLE_SCALE:
        return "cycle_scale"
    return "multi_cycle"


@dataclass
class Case:
    wmo: int
    cycle: int | None
    interval: float
    issued_juld: float
    # Stage-0 rung-4 step: the newest observed hop, treated as one cycle
    stage0_step: tuple[float, float]
    stage0_class: str
    stage0_hop_days: float
    # ground truth
    truth_step: tuple[float, float]
    truth_days: float
    error_km: float
    # window availability at prediction time (fixes at or before issued_juld)
    window_span_days: float | None
    window_ratio: float | None
    window_endpoints: tuple[int, int] | None


def build_cases(features: dict[int, Any]) -> list[Case]:
    cases: list[Case] = []
    for wmo, item in features.items():
        fixes = [f for f in item.fixes if f.get("lat") is not None and f.get("juld") is not None]
        interval = float(item.interval_days or profile_cycle.DEFAULT_INTERVAL_DAYS)
        for index in range(1, len(fixes) - 1):
            previous, issued, target = fixes[index - 1], fixes[index], fixes[index + 1]
            days = float(issued["juld"]) - float(previous["juld"])
            truth_days = float(target["juld"]) - float(issued["juld"])
            if days <= 0 or truth_days <= 0 or truth_days > MAX_TRANSITION_DAYS:
                continue
            step = displacement_km(previous["lat"], previous["lon"], issued["lat"], issued["lon"])
            truth = displacement_km(issued["lat"], issued["lon"], target["lat"], target["lon"])
            lat, lon = destination(issued["lat"], issued["lon"], step[0], step[1])
            # best window ending at the issuing fix, spans <= 3 cycles back
            best: tuple[float, int, int] | None = None
            for back in range(index - 1, -1, -1):
                span = float(issued["juld"]) - float(fixes[back]["juld"])
                if span <= 0 or span > WINDOW_MAX * interval:
                    break
                if best is None or abs(span - interval) < abs(best[0] - interval):
                    best = (span, back, index)
            cases.append(
                Case(
                    wmo=wmo,
                    cycle=issued.get("cycle"),
                    interval=interval,
                    issued_juld=float(issued["juld"]),
                    stage0_step=(step[0], step[1]),
                    stage0_class=hop_class(days, interval),
                    stage0_hop_days=days,
                    truth_step=(truth[0], truth[1]),
                    truth_days=truth_days,
                    error_km=haversine_km(target["lat"], target["lon"], lat, lon),
                    window_span_days=best[0] if best else None,
                    window_ratio=(best[0] / interval) if best and interval else None,
                    window_endpoints=(best[1], best[2]) if best else None,
                )
            )
    return cases


def summarize(errors: list[float]) -> dict[str, Any]:
    if not errors:
        return {"n": 0}
    ordered = sorted(errors)
    mean = sum(ordered) / len(ordered)
    return {
        "n": len(ordered),
        "median_km": round(statistics.median(ordered), 1),
        "mean_km": round(mean, 1),
        "p90_km": round(ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))], 1),
        "rmse_km": round((sum(e * e for e in ordered) / len(ordered)) ** 0.5, 1),
        "hit25_pct": round(100.0 * sum(e <= 25 for e in ordered) / len(ordered), 1),
        "hit50_pct": round(100.0 * sum(e <= 50 for e in ordered) / len(ordered), 1),
        "hit100_pct": round(100.0 * sum(e <= 100 for e in ordered) / len(ordered), 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out", default=str(Path(__file__).with_name("stage1_audit.json")))
    args = parser.parse_args()

    cache = json.loads(CACHE.read_text())
    rows = cache["rows"]
    raws: dict[int, bytes] = {}
    parsed: dict[str, dict] = {}
    for path in sorted(Path(args.corpus).glob("*_Rtraj.nc")):
        wmo = int(path.name.split("_")[0])
        raw = path.read_bytes()
        raws[wmo] = raw
        try:
            parsed[str(wmo)] = {
                "rtraj": fs.parse_rtraj(raw, wmo, NOW),
                "profile_aggregate": (rows.get(str(wmo)) or {}).get("profile_aggregate") or {},
                "in_incois_dac": True,
                "parser_version": fs.PARSER_VERSION,
                "profile_recency_version": fs.PROFILE_RECENCY_VERSION,
            }
        except Exception as exc:  # pragma: no cover - audit visibility
            print(f"  ! {wmo}: {type(exc).__name__}: {exc}")
    features = build_fleet_features(parsed, {}, NOW)
    cases = build_cases(features)

    out: dict[str, Any] = {
        "generated_at": NOW.isoformat().replace("+00:00", "Z"),
        "corpus": args.corpus,
        "floats": len(features),
        "cases": len(cases),
        "ring": fs.PREDICTION_FIX_HISTORY,
    }

    # ---- 1. distribution of last-transition duration / expected interval ----
    ratios = [c.stage0_hop_days / c.interval for c in cases if c.interval]
    ordered = sorted(ratios)
    bins = [0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 5.0, float("inf")]
    histogram = {
        f"{bins[i]:g}-{bins[i + 1]:g}": sum(1 for r in ordered if bins[i] <= r < bins[i + 1])
        for i in range(len(bins) - 1)
    }
    out["ratio_distribution"] = {
        "n": len(ordered),
        "min": round(ordered[0], 3) if ordered else None,
        "p10": round(ordered[int(0.1 * len(ordered))], 3) if ordered else None,
        "median": round(statistics.median(ordered), 3) if ordered else None,
        "p90": round(ordered[int(0.9 * len(ordered))], 3) if ordered else None,
        "max": round(ordered[-1], 3) if ordered else None,
        "histogram": histogram,
    }
    print("=== 1. last-transition duration / expected interval, all corpus cycles ===")
    print(f"n={len(ordered)}  min={ordered[0]:.3f}  p10={ordered[int(.1*len(ordered))]:.3f}  "
          f"median={statistics.median(ordered):.3f}  p90={ordered[int(.9*len(ordered))]:.3f}  max={ordered[-1]:.3f}")
    for name, count in histogram.items():
        print(f"   ratio {name:>12} : {count:>6}  ({100.0*count/len(ordered):5.2f}%)")

    # ---- 2/3. newest hop per float: sub-cycle / multi-cycle -----------------
    per_float: dict[int, dict[str, Any]] = {}
    for wmo, item in features.items():
        last = item.last_transition
        interval = float(item.interval_days or profile_cycle.DEFAULT_INTERVAL_DAYS)
        if last is None:
            per_float[wmo] = {"interval": round(interval, 3), "last_hop_days": None, "ratio": None,
                              "class": "no_transition", "fixes": len(item.fixes)}
            continue
        per_float[wmo] = {
            "interval": round(interval, 3),
            "interval_source": item.interval_source,
            "last_hop_days": round(last.days, 3),
            "ratio": round(last.days / interval, 3) if interval else None,
            "class": hop_class(last.days, interval),
            "fixes": len(item.fixes),
            "transitions": len(item.transitions),
        }
    sub = {w: v for w, v in per_float.items() if v["class"] == "sub_cycle"}
    multi = {w: v for w, v in per_float.items() if v["class"] == "multi_cycle"}
    scale = {w: v for w, v in per_float.items() if v["class"] == "cycle_scale"}
    out["per_float"] = per_float
    out["newest_hop_classes"] = {
        "sub_cycle": sorted(sub), "cycle_scale": sorted(scale), "multi_cycle": sorted(multi),
    }
    print("\n=== 2. floats whose NEWEST transition is sub-cycle (< 0.5 x interval) ===")
    for wmo, v in sorted(sub.items()):
        print(f"   {wmo}: last hop {v['last_hop_days']} d = {v['ratio']} x interval ({v['interval']} d), "
              f"{v['transitions']} transitions cached")
    print(f"   -> {len(sub)} float(s)")
    print("\n=== 3. floats whose NEWEST transition spans multiple cycles (> 1.5 x interval) ===")
    for wmo, v in sorted(multi.items()):
        print(f"   {wmo}: last hop {v['last_hop_days']} d = {v['ratio']} x interval ({v['interval']} d), "
              f"{v['transitions']} transitions cached")
    print(f"   -> {len(multi)} float(s)")
    print(f"\n   (cycle-scale newest hop: {len(scale)} float(s))")

    # ---- 4. effect of the newest-transition displacement --------------------
    by_class: dict[str, list[float]] = {"sub_cycle": [], "cycle_scale": [], "multi_cycle": []}
    for case in cases:
        by_class[case.stage0_class].append(case.error_km)
    out["stage0_error_by_hop_class"] = {name: summarize(values) for name, values in by_class.items()}
    out["stage0_error_all"] = summarize([c.error_km for c in cases])
    print("\n=== 4. Stage-0 rung-4 step (newest transition as one cycle), chronological replay ===")
    print(json.dumps(out["stage0_error_all"], indent=2))
    print("   split by the sampling class of the hop that produced the step:")
    for name in ("sub_cycle", "cycle_scale", "multi_cycle"):
        stats = out["stage0_error_by_hop_class"][name]
        if stats.get("n"):
            print(f"   {name:<12} {stats}")

    # per-float medians: is the error concentrated in a few floats?
    per_float_err: dict[str, list[float]] = {}
    for case in cases:
        per_float_err.setdefault(str(case.wmo), []).append(case.error_km)
    medians = {w: round(statistics.median(v), 1) for w, v in per_float_err.items()}
    out["stage0_median_by_float"] = medians
    worst = sorted(medians.items(), key=lambda kv: -kv[1])[:5]
    print(f"   worst floats by median error: {worst}")

    # ---- 5. available recent windows for a cycle-scale step -----------------
    in_band = [c for c in cases if c.window_ratio is not None and WINDOW_LOW <= c.window_ratio <= WINDOW_HIGH]
    normalizable = [c for c in cases if c.window_ratio is not None and WINDOW_HIGH < c.window_ratio <= WINDOW_MAX]
    too_short = [c for c in cases if c.window_ratio is not None and c.window_ratio < WINDOW_LOW]
    none = [c for c in cases if c.window_ratio is None]
    out["window_availability"] = {
        "cases": len(cases),
        "in_band": len(in_band),
        "in_band_pct": round(100.0 * len(in_band) / max(1, len(cases)), 1),
        "normalisable_multi_cycle": len(normalizable),
        "shorter_than_band": len(too_short),
        "no_window_at_all": len(none),
        "band": [WINDOW_LOW, WINDOW_HIGH],
    }
    print("\n=== 5. cycle-scale window availability at prediction time (fixes <= t(N)) ===")
    print(json.dumps(out["window_availability"], indent=2))
    floats_with_band = sorted({c.wmo for c in in_band})
    floats_without = sorted({w for w in features if w not in floats_with_band})
    out["floats_with_in_band_window"] = floats_with_band
    out["floats_without_in_band_window"] = floats_without
    print(f"   floats with at least one in-band window: {len(floats_with_band)}"
          f" | without: {floats_without}")

    Path(args.out).write_text(json.dumps(out, indent=2))
    summary_path = Path(__file__).with_name("stage1_audit_summary.json")
    summary_path.write_text(json.dumps({
        "generated_at": out["generated_at"],
        "cases": len(cases), "floats": len(features),
        "ratio_distribution": out["ratio_distribution"],
        "newest_hop_classes": {k: v for k, v in out["newest_hop_classes"].items()},
        "stage0_error_all": out["stage0_error_all"],
        "stage0_error_by_hop_class": out["stage0_error_by_hop_class"],
        "window_availability": out["window_availability"],
    }, indent=2))
    print(f"\nwrote {args.out} and {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
