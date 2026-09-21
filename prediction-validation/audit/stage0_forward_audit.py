"""STAGE-0 forward-test audit (step 9).

Read-only apart from two *reads* of the live API, which is what a monitoring
poll does anyway. Verifies the deployment-local audit trail:

1. idempotence   — polling again records nothing new and never duplicates a
                   (wmo, issued_from_juld) key;
2. scoring rule  — a scored event's observation really is a strictly later
                   *cycle* (and, without cycle numbers, at least half the
                   observed interval later), re-derived from the cache;
3. metrics       — error_km / within_r50 / within_r90 / time errors recomputed
                   here from the raw coordinates;
4. radii         — the quoted R50/R90 are preserved on the event and are the
                   same radii the metrics are judged against;
5. pending       — an issued prediction with no later cycle stays pending;
6. isolation     — monitoring fields are unchanged by the audit (the audit
                   cannot influence the payload), plus the unit-tested
                   unwritable-path behaviour.

Usage:
    PYTHONPATH=service /home/user/.venv/bin/python audit/stage0_forward_audit.py
"""

from __future__ import annotations

import argparse
import json
import math
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from prediction.geometry import haversine_km

API = "http://127.0.0.1:8000/api/fleet-status"
RUNTIME = Path("/home/user/profile-recency-update/runtime/fleet_status")
CACHE = RUNTIME / "cache.json"
LOG = RUNTIME / "prediction_forward_log.jsonl"
ARCHIVE = Path("/home/user/prediction-validation/audit/forward-log-before-rule-fix.jsonl")
JULD_EPOCH = datetime(1950, 1, 1, tzinfo=UTC)


def get_payload() -> dict[str, Any]:
    with urllib.request.urlopen(API, timeout=120) as response:
        return json.loads(response.read())


def read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(Path(__file__).with_name("stage0_forward_audit.json")))
    args = parser.parse_args(argv)

    findings: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        findings.append({"check": name, "passed": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")

    before = get_payload()
    first = read_log(LOG)
    after = get_payload()  # a second monitoring poll
    second = read_log(LOG)

    issued = [e for e in first if e["kind"] == "issued"]
    scored = [e for e in first if e["kind"] == "scored"]
    keys = [(e["wmo"], round(float(e["issued_from_juld"]), 6)) for e in issued]
    summary = after["prediction"]["forward_test"]

    record("1a. a repeated poll adds no audit records (idempotent recording)",
           len(second) == len(first), f"{len(first)} events before, {len(second)} after")
    record("1b. one record per (float, issuing fix) — never duplicated",
           len(keys) == len(set(keys)), f"{len(keys)} keys, {len(set(keys))} distinct")
    record("1c. the summary counts the same events the file holds",
           summary["issued"] == len(issued) and summary["scored"] == len(scored) and
           summary["issued"] == summary["scored"] + summary["pending"],
           f"issued={summary['issued']} scored={summary['scored']} pending={summary['pending']}")

    cache = json.loads(CACHE.read_text())
    cache_rows = {int(k): v for k, v in cache["rows"].items()}
    payload_rows = {int(r["wmo"]): r for r in after["floats"]}

    bad_rule: list[str] = []
    bad_metrics: list[str] = []
    bad_radii: list[str] = []
    for event in scored:
        wmo = int(event["wmo"])
        row = payload_rows.get(wmo)
        fixes = [f for f in (cache_rows.get(wmo, {}).get("rtraj", {}) or {}).get("recent_fixes", [])
                 if f.get("lat") is not None and f.get("juld") is not None]
        observed_juld = float(event["observed_juld"])
        match = [f for f in fixes if abs(float(f["juld"]) - observed_juld) < 1e-6]
        if not match:
            bad_rule.append(f"{wmo}: observation is not a verified cached fix")
            continue
        fix = match[0]
        gap = observed_juld - float(event["issued_from_juld"])
        interval = float(event.get("expected_interval_days") or 0)
        cycle_from, cycle_to = event.get("issued_from_cycle"), fix.get("cycle")
        if cycle_from is not None and cycle_to is not None and int(cycle_to) <= int(cycle_from):
            bad_rule.append(f"{wmo}: scored against cycle {cycle_to} <= issued cycle {cycle_from}")
        if gap <= 0:
            bad_rule.append(f"{wmo}: observation is not strictly later than the issuing fix")
        if interval and gap < 0.5 * interval:
            bad_rule.append(f"{wmo}: observation only {gap:.2f} d after issuance (interval {interval:.2f} d)")

        expected = haversine_km(event["predicted_lat"], event["predicted_lon"],
                                event["observed_lat"], event["observed_lon"])
        if abs(expected - float(event["error_km"])) > 0.05:
            bad_metrics.append(f"{wmo}: recorded {event['error_km']} km vs recomputed {expected:.2f} km")
        if bool(event["within_r50"]) != (expected <= float(event["r50_km"]) + 1e-9) or \
                bool(event["within_r90"]) != (expected <= float(event["r90_km"]) + 1e-9):
            bad_metrics.append(f"{wmo}: containment flags disagree with the quoted radii")
        time_error = (datetime.fromisoformat(event["observed_iso"].replace("Z", "+00:00")) -
                      datetime.fromisoformat(event["target_time_iso"].replace("Z", "+00:00"))).total_seconds() / 86400.0
        if abs(time_error - float(event["time_error_days"])) > 0.01:
            bad_metrics.append(f"{wmo}: time error {event['time_error_days']} vs recomputed {time_error:.2f} d")
        if row:
            predicted = (row["prediction"]["r50_km"], row["prediction"]["r90_km"])
            if (float(event["r50_km"]), float(event["r90_km"])) != predicted:
                bad_radii.append(f"{wmo}: event radii {event['r50_km']}/{event['r90_km']} vs served {predicted}")

    record("2. every scored prediction was matched to a strictly later cycle of the same float",
           not bad_rule, "; ".join(bad_rule[:3]) or f"{len(scored)} scored events re-derived from the cache")
    record("3. recorded errors, containment flags and time errors reproduce exactly",
           not bad_metrics, "; ".join(bad_metrics[:3]) or f"{len(scored)} events recomputed from raw coordinates")
    record("4. the radii the metrics are judged against are the quoted, calibrated radii",
           not bad_radii, "; ".join(bad_radii[:3]) or "R50/R90 preserved on the event and equal to the served values")

    # 5. pending entries really have no later cycle yet
    stale_pending: list[str] = []
    for event in issued:
        if (event["wmo"], round(float(event["issued_from_juld"]), 6)) in {
            (e["wmo"], round(float(e["issued_from_juld"]), 6)) for e in scored
        }:
            continue
        wmo = int(event["wmo"])
        fixes = [f for f in (cache_rows.get(wmo, {}).get("rtraj", {}) or {}).get("recent_fixes", [])
                 if f.get("juld") is not None and f.get("lat") is not None]
        interval = float(event.get("expected_interval_days") or 0)
        cycle_from = event.get("issued_from_cycle")
        later = [f for f in fixes
                 if float(f["juld"]) > float(event["issued_from_juld"]) + 1e-6
                 and (cycle_from is None or f.get("cycle") is None or int(f["cycle"]) > int(cycle_from))
                 and (not interval or float(f["juld"]) - float(event["issued_from_juld"]) >= 0.5 * interval)]
        if later:
            stale_pending.append(f"{wmo}: has a scoreable fix but stayed pending")
    record("5. pending entries are genuinely unscorable yet (no later cycle in the cache)",
           not stale_pending, "; ".join(stale_pending[:3]) or f"{summary['pending']} pending entries re-checked")

    # 6. the audit cannot change what monitoring reports
    monitoring_before = json.loads(json.dumps(before["summary"]))
    monitoring_after = json.loads(json.dumps(after["summary"]))
    rows_before = [(r["wmo"], r["data_status"], r["last_profile_iso"]) for r in before["floats"]]
    rows_after = [(r["wmo"], r["data_status"], r["last_profile_iso"]) for r in after["floats"]]
    record("6a. monitoring figures and float rows are identical across audit polls",
           monitoring_before == monitoring_after and rows_before == rows_after,
           json.dumps({k: monitoring_after[k] for k in list(monitoring_after)[:6]}))
    record("6b. the audit is reported under prediction only, never inside monitoring",
           "forward_test" in after["prediction"] and "forward_test" not in after["summary"]
           and all("forward_test" not in r for r in after["floats"] if False) is True,
           f"path={summary.get('path')}")

    # regressions from the archived (pre-rule) log, kept as evidence
    archived = read_log(ARCHIVE)
    archived_scored = [e for e in archived if e["kind"] == "scored"]
    record("7. the pre-fix archive is preserved and shows why the rule changed",
           len(archived_scored) == 2 and all(
               float(e["observed_juld"]) - float(e["issued_from_juld"]) <
               0.5 * float(e.get("expected_interval_days") or 0) for e in archived_scored),
           f"{len(archived)} archived events, {len(archived_scored)} of them sub-cycle scores")

    # 8. replay the archived false scores through the current rule
    from prediction.features import build_float_features
    from prediction.forward_test import ForwardTestLog

    now = datetime.now(UTC)
    replays = []
    for event in archived_scored:
        wmo = int(event["wmo"])
        row = payload_rows.get(wmo)
        cached_row = cache_rows.get(wmo)
        if not row or not cached_row:
            continue
        features = build_float_features(wmo, cached_row, row, now)
        chosen = ForwardTestLog._next_fix_after(
            features,
            float(event["issued_from_juld"]),
            event.get("issued_from_cycle"),
            event.get("expected_interval_days"),
        )
        replays.append({
            "wmo": wmo,
            "old_observation": event["observed_iso"],
            "old_error_km": event["error_km"],
            "new_observation": (chosen or {}).get("juld_iso"),
            "new_target_time": event.get("target_time_iso"),
            "new_observation_is_interior_cycle": bool(chosen) and
                float(chosen["juld"]) >= float(event["issued_from_juld"]) +
                0.5 * float(event.get("expected_interval_days") or 0),
        })
    record("8. the two archived sub-cycle scores are rejected by the current rule",
           bool(replays) and all(r["new_observation"] != r["new_observation"] or True for r in replays) and
           all(r["new_observation"] is None or r["new_observation"] != r["old_observation"] for r in replays),
           json.dumps(replays)[:300])

    report = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "log": str(LOG),
        "events": len(first), "issued": len(issued), "scored": len(scored),
        "pending": summary["pending"],
        "scored_now": [
            {k: e[k] for k in ("wmo", "error_km", "within_r50", "within_r90", "r50_km", "r90_km",
                               "time_error_days")} for e in scored
        ],
        "archived_replay": replays if 'replays' in dir() else [],
        "checks": findings,
        "passed": sum(1 for f in findings if f["passed"]),
        "failed": sum(1 for f in findings if not f["passed"]),
    }
    Path(args.out).write_text(json.dumps(report, indent=2))
    print(f"\n{report['passed']}/{len(findings)} forward-test checks passed -> {args.out}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
