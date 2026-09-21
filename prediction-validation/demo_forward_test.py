"""Demonstrate the forward test end to end, offline.

The live INCOIS fleet cannot advance a cycle on demand, so this script drives the
real service code path (`fleet_status` payload + `prediction.forward_test`) twice
against a synthetic runtime:

  round 1  two verified fixes exist          -> a prediction is issued and audited
  round 2  the NEXT cycle's fix has arrived  -> the earlier prediction is scored

Everything happens in a temporary runtime directory; no network, no downloads, no
change to the real cache. It is evidence that the audit scores honestly, not just
that it writes records.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path("/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui")
sys.path[:0] = [str(REPO / "service"), str(REPO / "src")]

RUNTIME = Path(tempfile.mkdtemp(prefix="forward-test-demo-"))
os.environ["ARGO_UI_DATA_DIR"] = str(RUNTIME)
os.environ["PREDICTION_CALIBRATION_PATH"] = str(REPO / "data" / "fleet_status" / "prediction_calibration.json")
os.environ["FLEET_SYNC_ENABLED"] = "0"

import fleet_status as fs  # noqa: E402
from prediction import forward_test  # noqa: E402

NOW = datetime.now(UTC).replace(microsecond=0)
EPOCH = datetime(1950, 1, 1, tzinfo=UTC)
WMO = 2907777


def juld(days_ago: float) -> float:
    return ((NOW - timedelta(days=days_ago)) - EPOCH).total_seconds() / 86400.0


def fix(days_ago: float, lat: float, lon: float, cycle: int) -> dict:
    when = NOW - timedelta(days=days_ago)
    return {
        "juld": juld(days_ago),
        "juld_iso": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lat": lat,
        "lon": lon,
        "cycle": cycle,
        "mc": 703.0,
        "pos_qc": "1",
    }


def row(fixes: list[dict]) -> dict:
    return {
        "in_incois_dac": True,
        "parser_version": fs.PARSER_VERSION,
        "profile_recency_version": fs.PROFILE_RECENCY_VERSION,
        "checked_at": NOW.isoformat(),
        "profile_checked_at": NOW.isoformat(),
        "profile_aggregate_fp": "demo",
        "rtraj": {
            "recent_fixes": fixes,
            "cycle_intervals": {"n": 6, "median_days": 10.0},
            "park_pressure_dbar": 1000.0,
        },
        "profile_aggregate": {
            "file": f"{WMO}_prof.nc",
            "juld": juld(10.0),
            "juld_iso": (NOW - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "juld_intervals": {"n": 6, "median_days": 10.0},
        },
    }


registry = fs.FleetSyncRegistry(
    state_path=RUNTIME / "fleet_status" / "cache.json",
    fleet_fn=lambda: [{"wmo": WMO, "platform_type": "APEX", "transmission_type": "IRIDIUM_SBD"}],
    enabled=False,
)
forward_test.reset_log_for_tests()
log_path = RUNTIME / "fleet_status" / forward_test.LOG_FILENAME

# ---------------------------------------------------------------- round 1
# Two verified fixes, a fast eastward drift; the prediction extrapolates it.
registry._rows = {str(WMO): row([fix(20.0, -7.50, 72.20, 1), fix(10.0, -7.51, 73.20, 2)])}
first = registry.payload()
prediction = first["floats"][0]["prediction"]
print("round 1 — prediction issued")
print(f"  issued from {prediction['issued_from_iso']} at {prediction['issued_from_position']}")
print(f"  predicted   {prediction['predicted_lat']}, {prediction['predicted_lon']}  ({prediction['method_label']}, rung {prediction['fallback_rung']})")
print(f"  radius      r50 {prediction['r50_km']} km / r90 {prediction['r90_km']} km  (n={prediction['validation_samples']})")
print(f"  audit       {json.dumps({k: first['prediction']['forward_test'][k] for k in ('issued', 'scored', 'pending')})}")
print(f"  forward_test on the row: {prediction.get('forward_test')}")

# A polling browser must not inflate the audit.
for _ in range(3):
    registry.payload()
after_polls = registry.payload()["prediction"]["forward_test"]
print(f"  after 4 more polls: issued={after_polls['issued']} scored={after_polls['scored']} pending={after_polls['pending']}")

# ---------------------------------------------------------------- round 2
# The next cycle arrives — deliberately 0.45 deg north of the extrapolation, so
# the miss is real and must be reported rather than hidden.
registry._rows = {
    str(WMO): row([fix(20.0, -7.50, 72.20, 1), fix(10.0, -7.51, 73.20, 2), fix(0.0, -7.06, 74.20, 3)])
}
second = registry.payload()
audit = second["prediction"]["forward_test"]
print("\nround 2 — the next verified fix arrived")
print(f"  observed    {second['floats'][0]['lat']}, {second['floats'][0]['lon']} (cycle 3)")
print(f"  audit       {json.dumps({k: audit[k] for k in ('issued', 'scored', 'pending')})}")
print(f"  overall     {json.dumps(audit['overall'])}")
print(f"  per method  {json.dumps(audit['methods'])}")
row_audit = second["floats"][0]["prediction"].get("forward_test")
print(f"  drawer line {row_audit}")

scored = [json.loads(line) for line in log_path.read_text().splitlines() if '"scored"' in line]
print("\nscored event (audit file, verbatim fields):")
for key in (
    "wmo",
    "issued_from_iso",
    "target_time_iso",
    "predicted_lat",
    "predicted_lon",
    "observed_iso",
    "observed_lat",
    "observed_lon",
    "error_km",
    "time_error_days",
    "within_r50",
    "within_r90",
    "method",
):
    print(f"  {key:>18}: {scored[0].get(key)}")
print(f"\naudit file: {log_path}  ({log_path.stat().st_size} bytes)")
