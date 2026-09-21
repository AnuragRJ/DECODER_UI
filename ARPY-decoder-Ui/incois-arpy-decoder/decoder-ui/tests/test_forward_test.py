"""Forward test: the audit that scores shipped predictions against later fixes.

Network-free. Uses synthetic cached rows (the same shape fleet_status stores)
so every rule is pinned without touching the live cache or the GDAL/GDAC path:

  * recording is idempotent per (float, issued-from fix) — re-serving the same
    cache cannot inflate the audit;
  * scoring requires a strictly newer verified fix, never the fix the prediction
    came from;
  * refused predictions are not logged at all;
  * the audit is not a profile store: only the prediction and its measured error;
  * a corrupt line, a disabled log or an IO failure degrades to a report and
    never breaks the payload.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="decoder-ui-forward-test-")
os.environ["ARGO_UI_DATA_DIR"] = _TMP

from prediction import predict as pr  # noqa: E402
from prediction.calibrate import load_calibration  # noqa: E402
from prediction.features import build_float_features  # noqa: E402
from prediction.forward_test import (  # noqa: E402
    ENABLED_ENV,
    ForwardTestLog,
    log_enabled,
)

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
EPOCH = datetime(1950, 1, 1, tzinfo=UTC)


def juld(dt: datetime) -> float:
    return (dt - EPOCH).total_seconds() / 86400.0


def fix(days_ago: float, lat: float, lon: float, cycle: int) -> dict:
    when = NOW - timedelta(days=days_ago)
    return {
        "juld": juld(when),
        "juld_iso": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lat": lat,
        "lon": lon,
        "cycle": cycle,
        "mc": 703,
        "pos_qc": "1",
    }


def row_with(fixes: list[dict]) -> dict:
    return {
        "rtraj": {"recent_fixes": fixes, "cycle_intervals": {"n": 4, "median_days": 10.0}},
        "profile_aggregate": {"juld_intervals": {"n": 4, "median_days": 10.0}},
    }


def calibration_artifact(path: Path) -> Path:
    """Radii small enough that a scored prediction must miss the 50 % circle."""
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "blend_weight_on_prior": 0.2,
                "default_interval_days": 10.0,
                "corpus": {"rtraj_floats": 2},
                "prior_grid": {},
                "methods": {
                    "trajectory_extrapolation": {
                        "default": {"n": 60, "r50_km": 5.0, "r90_km": 200.0, "metrics": {"n": 60}},
                        "strata": {},
                    }
                },
            }
        )
    )
    return path


def features_for(fixes: list[dict], wmo: int = 2902001):
    return build_float_features(wmo, row_with(fixes), {"platform_type": "APEX"}, NOW)


def predicts(features, calibration):
    return pr.predict_float(features, pool=[], calibration=calibration, now=NOW)


# ------------------------------------------------------------------ recording
def test_each_prediction_is_recorded_once_even_if_served_repeatedly(tmp_path):
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=True)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = {2902001: features_for([fix(20, -10.0, 60.0, 1), fix(10, -10.2, 60.2, 2)])}
    predictions = {2902001: predicts(features[2902001], calibration)}

    first = log.observe(features, predictions, now=NOW)
    second = log.observe(features, predictions, now=NOW)
    third = log.observe(features, predictions, now=NOW)

    assert (first["issued"], first["scored"]) == (1, 0)
    assert (second["issued_this_call"], second["scored_this_call"]) == (0, 0)
    assert (third["issued_this_call"], third["scored_this_call"]) == (0, 0)
    lines = (tmp_path / "audit.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1  # one event, regardless of how often the API is polled
    assert json.loads(lines[0])["kind"] == "issued"


def test_a_new_cycle_produces_a_new_record(tmp_path):
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=True)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    two = {2902002: features_for([fix(20, -10.0, 60.0, 1), fix(10, -10.2, 60.2, 2)], 2902002)}
    three = {
        2902002: features_for(
            [fix(20, -10.0, 60.0, 1), fix(10, -10.2, 60.2, 2), fix(0, -10.4, 60.4, 3)], 2902002
        )
    }
    log.observe(two, {2902002: predicts(two[2902002], calibration)}, now=NOW)
    summary = log.observe(three, {2902002: predicts(three[2902002], calibration)}, now=NOW)
    assert summary["issued"] == 2
    assert summary["scored"] == 1  # the first prediction's next fix has arrived
    assert summary["pending"] == 1
    assert summary["overall"]["n"] == 1


def test_predictions_that_were_refused_are_not_logged(tmp_path):
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=True)
    features = {2902003: build_float_features(2902003, {"rtraj": {}}, None, NOW)}
    payload = predicts(features[2902003], load_calibration(tmp_path / "absent.json"))
    assert payload["available"] is False
    summary = log.observe(features, {2902003: payload}, now=NOW)
    assert summary["issued"] == 0 and summary["scored"] == 0
    assert not (tmp_path / "audit.jsonl").exists()


# ------------------------------------------------------------------- scoring
def test_scoring_measures_the_error_against_the_later_verified_fix(tmp_path):
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=True)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    before = {2902004: features_for([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.5, 2)], 2902004)}
    issued = predicts(before[2902004], calibration)
    log.observe(before, {2902004: issued}, now=NOW)

    # The next cycle arrives 3 degrees north of the predicted position.
    after = {
        2902004: features_for(
            [fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.5, 2), fix(0, 3.0, 61.0, 3)], 2902004
        )
    }
    summary = log.observe(after, {2902004: predicts(after[2902004], calibration)}, now=NOW)

    scored = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text().splitlines()
        if json.loads(line)["kind"] == "scored"
    ]
    assert len(scored) == 1
    event = scored[0]
    assert event["predicted_lat"] == issued["predicted_lat"]
    assert event["observed_lat"] == 3.0 and event["observed_lon"] == 61.0
    # The extrapolation tracks the longitude, so the miss is the ~3 deg latitude
    # difference (~332 km): outside both the 5 km r50 and the 200 km r90 circles.
    assert 325 < event["error_km"] < 340
    assert event["within_r50"] is False and event["within_r90"] is False
    assert event["time_error_days"] is not None
    assert summary["overall"]["n"] == 1
    assert summary["overall"]["within_r90_pct"] == 0.0
    assert summary["methods"]["trajectory_extrapolation"]["n"] == 1


def test_containment_is_measured_when_the_error_is_inside_the_circle(tmp_path):
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=True)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    # Equal 0.5 deg steps: the constant-displacement prediction lands on the
    # observed next fix, so containment must register.
    before = {2902005: features_for([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.5, 2)], 2902005)}
    log.observe(before, {2902005: predicts(before[2902005], calibration)}, now=NOW)
    after = {
        2902005: features_for(
            [fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.5, 2), fix(0, 0.0, 61.0, 3)], 2902005
        )
    }
    summary = log.observe(after, {2902005: predicts(after[2902005], calibration)}, now=NOW)
    assert summary["overall"]["within_r50_pct"] == 100.0
    assert summary["overall"]["within_r90_pct"] == 100.0
    assert summary["overall"]["median_km"] < 1.0


def test_a_record_is_never_scored_against_the_fix_it_came_from(tmp_path):
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=True)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = {2902006: features_for([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.5, 2)], 2902006)}
    log.observe(features, {2902006: predicts(features[2902006], calibration)}, now=NOW)
    # Same fix set, re-served many times (a polling browser).
    for _ in range(3):
        summary = log.observe(features, {2902006: predicts(features[2902006], calibration)}, now=NOW)
    assert summary["scored"] == 0 and summary["pending"] == 1
    assert summary["overall"] is None


def test_per_float_and_per_method_metrics_are_kept_separate(tmp_path):
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=True)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    for wmo, lat_after in ((2902011, 1.0), (2902012, 2.0)):
        before = {wmo: features_for([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.2, 2)], wmo)}
        log.observe(before, {wmo: predicts(before[wmo], calibration)}, now=NOW)
        after = {
            wmo: features_for(
                [fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.2, 2), fix(0, lat_after, 60.4, 3)], wmo
            )
        }
        log.observe(after, {wmo: predicts(after[wmo], calibration)}, now=NOW)
    summary = log.metrics()
    assert summary["scored"] == 2
    assert set(summary["floats"]) == {"2902011", "2902012"}
    assert summary["floats"]["2902012"]["median_km"] > summary["floats"]["2902011"]["median_km"]
    assert summary["methods"]["trajectory_extrapolation"]["n"] == 2


# ---------------------------------------------------------------- robustness
def test_the_audit_is_not_a_profile_store(tmp_path):
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=True)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = {2902013: features_for([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.2, 2)], 2902013)}
    log.observe(features, {2902013: predicts(features[2902013], calibration)}, now=NOW)
    text = (tmp_path / "audit.jsonl").read_text()
    assert "prof.nc" not in text and "Rtraj" not in text
    assert "temperature" not in text.lower() and "pressure" not in text.lower()
    for line in text.splitlines():
        event = json.loads(line)
        assert set(event).isdisjoint({"samples", "measurements", "psal", "temp", "pres"})


def test_a_corrupt_line_does_not_break_the_audit(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text("{not json at all\n")
    log = ForwardTestLog(path, enabled=True)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = {2902014: features_for([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.2, 2)], 2902014)}
    summary = log.observe(features, {2902014: predicts(features[2902014], calibration)}, now=NOW)
    assert summary["issued"] == 1
    assert len(path.read_text().strip().splitlines()) == 2  # corrupt line kept, event appended


def test_a_disabled_log_reports_itself_instead_of_looking_empty(tmp_path, monkeypatch):
    monkeypatch.setenv(ENABLED_ENV, "0")
    assert log_enabled() is False
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=False)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = {2902015: features_for([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.2, 2)], 2902015)}
    summary = log.observe(features, {2902015: predicts(features[2902015], calibration)}, now=NOW)
    assert summary["enabled"] is False
    assert "disabled" in summary["note"]
    assert not (tmp_path / "audit.jsonl").exists()


def test_the_audit_file_stays_bounded(tmp_path):
    import prediction.forward_test as ft

    path = tmp_path / "audit.jsonl"
    log = ForwardTestLog(path, enabled=True)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    original = ft.MAX_BYTES
    ft.MAX_BYTES = 2048
    try:
        for cycle in range(30):
            wmo = 2902020 + cycle
            features = {
                wmo: features_for([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.2, 2)], wmo)
            }
            log.observe(features, {wmo: predicts(features[wmo], calibration)}, now=NOW)
    finally:
        ft.MAX_BYTES = original
    assert path.stat().st_size < 4096
    assert log.metrics()["issued"] >= 1  # still readable after a rotation


def test_an_unwritable_path_is_reported_and_never_raised(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    log = ForwardTestLog(blocker / "audit.jsonl", enabled=True)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = {2902040: features_for([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.2, 2)], 2902040)}
    summary = log.observe(features, {2902040: predicts(features[2902040], calibration)}, now=NOW)
    assert summary["error"] and summary["issued_this_call"] == 0


# ------------------------------------------------------------------ payload
def test_fleet_status_payload_exposes_the_forward_test(tmp_path, monkeypatch):
    import fleet_status as fs

    log_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("PREDICTION_FORWARD_LOG_PATH", str(log_path))
    monkeypatch.setenv("PREDICTION_CALIBRATION_PATH", str(calibration_artifact(tmp_path / "cal.json")))
    fs.prediction_forward_reset = None  # documentation: the module-level log is reset below
    from prediction import forward_test

    forward_test.reset_log_for_tests()

    registry = fs.FleetSyncRegistry(
        state_path=tmp_path / "cache.json",
        fleet_fn=lambda: [{"wmo": 2902050, "platform_type": "APEX"}],
        enabled=False,
    )
    base = {
        "in_incois_dac": True,
        "parser_version": fs.PARSER_VERSION,
        "profile_recency_version": fs.PROFILE_RECENCY_VERSION,
        "checked_at": NOW.isoformat(),
        "profile_checked_at": NOW.isoformat(),
        "profile_aggregate_fp": "test",
    }
    registry._rows = {
        "2902050": {
            **base,
            **row_with([fix(20, -10.0, 60.0, 1), fix(10, -10.3, 60.3, 2)]),
            "profile_aggregate": {
                "file": "2902050_prof.nc",
                "juld": juld(NOW - timedelta(days=10)),
                "juld_intervals": {"n": 4, "median_days": 10.0},
            },
        }
    }
    payload = registry.payload()
    forward = payload["prediction"]["forward_test"]
    assert forward["enabled"] is True
    assert forward["issued"] == 1 and forward["pending"] == 1
    assert forward["scored"] == 0
    assert forward["path"] == str(log_path)
    # The audit is additive: monitoring fields are untouched by it.
    assert payload["floats"][0]["data_status"] in {
        "ACTIVE / RECENT PROFILE",
        "PROFILE OVERDUE",
        "NO RECENT PROFILE DATA 60+ DAYS",
        "NO DATA",
    }
    forward_test.reset_log_for_tests()


def test_a_broken_forward_log_cannot_break_the_status_payload(tmp_path, monkeypatch):
    import fleet_status as fs
    from prediction import forward_test

    monkeypatch.setenv("PREDICTION_FORWARD_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("PREDICTION_CALIBRATION_PATH", str(calibration_artifact(tmp_path / "cal.json")))
    forward_test.reset_log_for_tests()

    class Exploding(forward_test.ForwardTestLog):
        def observe(self, features_by_wmo, predictions, now=None):  # type: ignore[override]
            raise RuntimeError("audit exploded")

    monkeypatch.setattr(forward_test, "get_log", lambda: Exploding(tmp_path / "audit.jsonl"))
    registry = fs.FleetSyncRegistry(
        state_path=tmp_path / "cache.json",
        fleet_fn=lambda: [{"wmo": 2902051, "platform_type": "APEX"}],
        enabled=False,
    )
    registry._rows = {
        "2902051": {
            "in_incois_dac": True,
            "parser_version": fs.PARSER_VERSION,
            "profile_recency_version": fs.PROFILE_RECENCY_VERSION,
            "checked_at": NOW.isoformat(),
            "profile_checked_at": NOW.isoformat(),
            "profile_aggregate_fp": "test",
            **row_with([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.2, 2)]),
        }
    }
    payload = registry.payload()
    assert payload["floats"][0]["wmo"] == 2902051
    # The whole prediction block degrades together, and the error is reported.
    assert payload["prediction"]["error"]
    assert payload["floats"][0]["data_status"] in {
        "ACTIVE / RECENT PROFILE",
        "PROFILE OVERDUE",
        "NO RECENT PROFILE DATA 60+ DAYS",
        "NO DATA",
    }
    forward_test.reset_log_for_tests()


# ------------------------------------------------- sub-cycle burst guard
def test_a_sub_cycle_fix_never_scores_a_prediction(tmp_path):
    """Floats can publish several cycles within a day (telemetry bursts).

    Scoring against such a fix measures a sub-cycle hop, not the next-profile
    prediction. The audit must wait for a later *cycle* (or, when cycles are
    unknown, at least half the expected interval).
    """
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=True)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    before = {2902060: features_for([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.5, 2)], 2902060)}
    issued = predicts(before[2902060], calibration)
    log.observe(before, {2902060: issued}, now=NOW)

    # 0.9 days later the same float publishes cycle 3 (a burst, not the next profile)
    burst = {
        2902060: features_for(
            [fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.5, 2), fix(10 - 0.9, 3.0, 61.0, 3)], 2902060
        )
    }
    summary = log.observe(burst, {2902060: predicts(burst[2902060], calibration)}, now=NOW)
    assert summary["scored"] == 0, "a 0.9-day hop must not score a 10-day prediction"
    assert summary["pending"] == 2  # the burst record itself is now pending too

    # the genuine next cycle (cycle 4, ~10 days after cycle 2's fix) does score
    real = {
        2902060: features_for(
            [
                fix(20, 0.0, 60.0, 1),
                fix(10, 0.0, 60.5, 2),
                fix(10 - 0.9, 3.0, 61.0, 3),
                fix(0.2, 0.05, 61.05, 4),
            ],
            2902060,
        )
    }
    log.observe(real, {2902060: predicts(real[2902060], calibration)}, now=NOW)
    scored = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text().splitlines()
        if json.loads(line)["kind"] == "scored"
    ]
    assert any(event["observed_lat"] == 0.05 and event["error_km"] < 10 for event in scored), \
        "the cycle-3 prediction must be scored against the cycle-4 fix"


def test_without_cycle_numbers_the_half_interval_rule_applies(tmp_path):
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=True)
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    no_cycle = lambda d, lat, lon: {**fix(d, lat, lon, 0), "cycle": None}
    before = {2902061: features_for([no_cycle(20, 0.0, 60.0), no_cycle(10, 0.0, 60.5)], 2902061)}
    log.observe(before, {2902061: predicts(before[2902061], calibration)}, now=NOW)
    # 1 day later: too early for a 10-day float without cycle numbers
    early = {2902061: features_for([no_cycle(20, 0.0, 60.0), no_cycle(10, 0.0, 60.5), no_cycle(9, 1.0, 61.0)], 2902061)}
    assert log.observe(early, {2902061: predicts(early[2902061], calibration)}, now=NOW)["scored"] == 0
    # 6 days later: half the interval has passed, so it scores
    later = {2902061: features_for([no_cycle(20, 0.0, 60.0), no_cycle(10, 0.0, 60.5), no_cycle(4, 1.0, 61.0)], 2902061)}
    summary = log.observe(later, {2902061: predicts(later[2902061], calibration)}, now=NOW)
    assert summary["scored"] >= 1
