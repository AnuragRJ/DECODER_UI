"""Stage-1 cycle-scale step: geometry, irregular sampling, fallbacks, stage labels.

Network-free. Two layers are pinned here:

  * the step model itself (``prediction/cycle_step.py``) — which pair of historical
    fixes may define "about one cycle" of displacement, and what happens when the
    float's sampling is bursty or has a multi-cycle gap;
  * the service wiring (``prediction/predict.py``) — Stage-1 is opt-in, uses its
    own calibration, never borrows Stage-0's radii, keeps the Stage-0 target-time
    calculation, and falls back to the Stage-0 branch when it has no window.

Nothing here reads the network, the live cache or the decoder core.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="decoder-ui-cycle-step-test-")
os.environ["ARGO_UI_DATA_DIR"] = _TMP

import profile_cycle  # noqa: E402
from prediction import predict as pr  # noqa: E402
from prediction.calibrate import (  # noqa: E402
    METHOD_CYCLE_MEDIAN,
    METHOD_CYCLE_MEDIAN_PRIOR,
    METHOD_CYCLE_WINDOW,
    METHOD_CYCLE_WINDOW_PRIOR,
    METHOD_HISTORY_PRIOR,
    METHOD_PERSISTENCE,
    METHOD_REGIONAL_PRIOR,
    METHOD_TRAJECTORY,
    load_calibration,
    load_stage1_calibration,
)
from prediction.cycle_step import (  # noqa: E402
    CYCLE_STEP_ENV,
    DEFAULT_CYCLE_STEP,
    STEP_MEDIAN,
    STEP_OFF,
    STEP_WINDOW,
    cycle_scale_step,
    fallback_reason,
    resolve_cycle_step_mode,
)
from prediction.features import build_float_features  # noqa: E402
from prediction.geometry import haversine_km  # noqa: E402

EPOCH = datetime(1950, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
REPO = Path(__file__).resolve().parents[1]


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


def row_with(fixes: list[dict], interval: dict | None = None) -> dict:
    return {
        "rtraj": {
            "recent_fixes": fixes,
            "cycle_intervals": interval or {"n": 4, "median_days": 10.0},
            "park_pressure_dbar": 1000.0,
            "phase_hours": {"descent_h": 5.0, "park_h": 220.0, "ascent_h": 5.0},
        },
        "profile_aggregate": {"juld_intervals": interval or {"n": 4, "median_days": 10.0}},
    }


def calibration_artifact(path: Path, methods: dict | None = None, *, stage: str | None = None) -> Path:
    artifact = {
        "version": 1,
        "generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "blend_weight_on_prior": 0.2,
        "default_interval_days": 10.0,
        "corpus": {"rtraj_floats": 2, "cases": {"history_prior": 40}},
        "prior_grid": {"cell_deg": 2.0, "min_count": 5, "cells": {}},
        "methods": methods
        if methods is not None
        else {
            key: {
                "default": {"n": 120, "r50_km": 20.0, "r90_km": 70.0, "metrics": {"n": 120}},
                "strata": {},
            }
            for key in (METHOD_HISTORY_PRIOR, METHOD_TRAJECTORY,
                        METHOD_REGIONAL_PRIOR, METHOD_PERSISTENCE)
        },
    }
    if stage:
        artifact["stage"] = stage
    path.write_text(json.dumps(artifact))
    return path


def stage1_artifact(path: Path) -> Path:
    """Stage-1 candidate artefact with radii deliberately different from Stage-0."""
    return calibration_artifact(
        path,
        methods={
            key: {
                "default": {"n": 900, "r50_km": 61.4, "r90_km": 208.9, "metrics": {"n": 900}},
                "strata": {},
            }
            for key in (METHOD_CYCLE_WINDOW, METHOD_CYCLE_WINDOW_PRIOR,
                        METHOD_CYCLE_MEDIAN, METHOD_CYCLE_MEDIAN_PRIOR)
        },
        stage="stage1",
    )


# ------------------------------------------------------------------ step model
def test_window_uses_the_freshest_in_band_pair():
    """Recency wins: the newest pair inside [0.75, 1.25] x interval defines the step."""
    fixes = [
        fix(60, 0.0, 60.0, 1),
        fix(50, 0.2, 60.2, 2),
        fix(40, 0.4, 60.4, 3),   # 10 d before the newest and 20 d before it: both in band
        fix(20, 1.0, 60.6, 4),
        fix(10, 1.2, 60.9, 5),
    ]
    step = cycle_scale_step(fixes, 10.0, mode=STEP_WINDOW)
    assert step is not None
    assert step.cycles == 1
    assert step.span_days == pytest.approx(10.0, abs=0.01)
    assert step.windows_used == 1
    assert abs(step.ratio - 1.0) < 0.01
    # the step is the 10 d displacement (1.0, 60.6) -> (1.2, 60.9), not the 20 d one
    assert step.dlat_km < 30.0 and step.dlon_km < 40.0
    assert "0.75" not in step.basis


def test_burst_hop_is_never_treated_as_a_cycle():
    """A 0.7 d telemetry hop must not be rescaled into a full-cycle displacement."""
    fixes = [
        fix(30.0, 0.0, 60.0, 1),
        fix(20.0, 0.5, 60.5, 2),
        fix(10.0, 1.0, 61.0, 3),
        fix(9.3, 1.1, 61.05, 4),  # burst: 0.7 d after the previous fix
    ]
    step = cycle_scale_step(fixes, 10.0, mode=STEP_WINDOW)
    assert step is not None
    # the freshest in-band window is the 10.7 d pair, never the 0.7 d hop
    assert step.span_days == pytest.approx(10.7, abs=0.05)
    assert step.cycles == 1
    burst = haversine_km(1.0, 61.0, 1.1, 61.05)
    assert math.hypot(step.dlat_km, step.dlon_km) > burst  # not a burst-sized step either


def test_multi_cycle_gap_is_normalised_by_whole_cycles():
    """A 30 d silence over a 10 d interval is divided by three, not used as one cycle."""
    fixes = [
        fix(60, 0.0, 60.0, 1),
        fix(50, 0.2, 60.2, 2),
        fix(30, 5.0, 66.0, 3),  # 20 d gap (a mission gap, still > 1 cycle)
        fix(0, 14.0, 78.0, 4),  # 30 d gap: the newest span
    ]
    step = cycle_scale_step(fixes, 10.0, mode=STEP_WINDOW)
    assert step is not None
    assert step.cycles == 3
    assert step.span_days == pytest.approx(30.0, abs=0.05)
    raw = haversine_km(5.0, 66.0, 14.0, 78.0)
    applied = math.hypot(step.dlat_km, step.dlon_km)
    assert applied == pytest.approx(raw / 3.0, rel=0.02)


def test_shorter_than_band_spans_are_skipped_not_rescaled():
    fixes = [fix(21, 0.0, 60.0, 1), fix(20.7, 0.0, 60.05, 2), fix(20.4, 0.0, 60.1, 3)]
    step = cycle_scale_step(fixes, 10.0, mode=STEP_WINDOW)
    assert step is None  # every span is 0.3 d: no cycle-scale window exists
    reason = fallback_reason(fixes, 10.0)
    assert "telemetry burst, not a cycle" in reason and "0.60 d" in reason


def test_fallback_reason_never_contradicts_an_available_step():
    """A truthful reason string is what gets attached to a payload."""
    fixes = [fix(30, 0.0, 60.0, 1), fix(20, 0.5, 60.5, 2), fix(13, 1.0, 61.0, 3)]
    step = cycle_scale_step(fixes, 10.0)
    if step is not None:
        reason = fallback_reason(fixes, 10.0)
        assert reason.startswith("cycle-scale window available")
    else:
        assert "window" in fallback_reason(fixes, 10.0)


def test_no_window_when_history_is_too_short_or_too_stale():
    assert cycle_scale_step([fix(1, 0.0, 60.0, 1)], 10.0) is None
    assert cycle_scale_step([], 10.0) is None
    stale = [fix(120, 0.0, 60.0, 1), fix(0, 4.0, 70.0, 2)]  # 120 d apart, cap is 3 cycles
    assert cycle_scale_step(stale, 10.0) is None
    reason = fallback_reason(stale, 10.0)
    assert isinstance(reason, str) and reason


def test_median_mode_combines_the_last_windows_and_stays_dynamic():
    long_drift = [
        fix(40, 0.0, 60.0, 1),
        fix(20, 2.0, 63.0, 3),
        fix(10, 3.2, 64.5, 4),
    ]
    single = cycle_scale_step(long_drift, 10.0, mode=STEP_WINDOW, max_cycles=3.0)
    median = cycle_scale_step(long_drift, 10.0, mode=STEP_MEDIAN, max_cycles=3.0)
    assert median is not None and median.windows_used >= 1
    assert median.cycles >= 1
    if single is not None and median.windows_used > 1:
        applied_median = math.hypot(median.dlat_km, median.dlon_km)
        applied_single = math.hypot(single.dlat_km, single.dlon_km)
        assert applied_median != applied_single  # combining windows changes the step
    # dynamic for any float: no state, so the same input always gives the same step
    again = cycle_scale_step(long_drift, 10.0, mode=STEP_MEDIAN, max_cycles=3.0)
    assert (again.dlat_km, again.dlon_km) == (median.dlat_km, median.dlon_km)


def test_step_provenance_fields_are_always_populated():
    fixes = [fix(30, 0.0, 60.0, 1), fix(20, 0.5, 60.5, 2), fix(10, 1.0, 61.0, 3)]
    step = cycle_scale_step(fixes, 10.0)
    assert step is not None
    assert step.span_days > 0
    assert step.ratio == pytest.approx(step.span_days / 10.0, rel=1e-6)
    assert step.cycles >= 1
    assert step.windows_used >= 1
    assert isinstance(step.basis, str) and step.basis


def test_mode_resolution_defaults_to_stage0_and_ignores_unknown_values(monkeypatch):
    monkeypatch.delenv(CYCLE_STEP_ENV, raising=False)
    assert DEFAULT_CYCLE_STEP == STEP_OFF  # ship gate not met: Stage-0 stays the default
    assert resolve_cycle_step_mode(None) == STEP_OFF
    assert resolve_cycle_step_mode("nonsense") == STEP_OFF
    monkeypatch.setenv(CYCLE_STEP_ENV, STEP_MEDIAN)
    assert resolve_cycle_step_mode(None) == STEP_MEDIAN
    assert resolve_cycle_step_mode(STEP_WINDOW) == STEP_WINDOW


# ------------------------------------------------------------------ service wiring
def test_stage0_payload_is_identical_when_stage1_is_off(tmp_path):
    calibration = load_calibration(calibration_artifact(tmp_path / "stage0.json"))
    features = build_float_features(
        2900001, row_with([fix(30, 0.0, 60.0, 1), fix(20, 0.4, 60.4, 2), fix(10, 0.8, 60.8, 3)]),
        None, NOW,
    )
    default = pr.predict_float(features, pool=[], calibration=calibration, now=NOW)
    explicit_off = pr.predict_float(
        features, pool=[], calibration=calibration, now=NOW, cycle_step_mode=STEP_OFF
    )
    assert default["method"] == explicit_off["method"] == METHOD_TRAJECTORY
    assert default["predicted_lat"] == explicit_off["predicted_lat"]
    assert default["predicted_lon"] == explicit_off["predicted_lon"]
    assert default["r50_km"] == explicit_off["r50_km"] == 20.0
    assert default["predictor_stage"] == "stage0"
    assert default["predictor_stage_label"] == "Stage-0 baseline (last-hop step)"
    assert default["step_basis"] is None


def test_stage1_uses_the_cycle_scale_step_and_its_own_radii(tmp_path):
    stage0 = load_calibration(calibration_artifact(tmp_path / "stage0.json"))
    stage1 = load_stage1_calibration(stage1_artifact(tmp_path / "prediction_calibration_stage1.json"))
    assert stage1 is not None and stage1.stage == "stage1"
    features = build_float_features(
        2900002, row_with([fix(30, 0.0, 60.0, 1), fix(20, 0.4, 60.4, 2), fix(10, 0.8, 60.8, 3)]),
        None, NOW,
    )
    stage0_payload = pr.predict_float(features, pool=[], calibration=stage0, now=NOW)
    payload = pr.predict_float(
        features, pool=[], calibration=stage0, now=NOW,
        cycle_step_mode=STEP_WINDOW, calibration_stage1=stage1,
    )
    assert payload["method"] == METHOD_CYCLE_WINDOW
    assert payload["method_label"] == "Cycle-Scale Window (Stage-1)"
    assert payload["predictor_stage"] == "stage1"
    assert payload["predictor_stage_label"] == "Stage-1 cycle-scale step"
    assert payload["r50_km"] == 61.4 and payload["r90_km"] == 208.9  # its own, not Stage-0's
    assert payload["validation_samples"] == 900
    assert isinstance(payload["step_basis"], str) and payload["step_basis"]
    assert payload["step_span_days"] == pytest.approx(10.0, abs=0.05)
    assert payload["step_cycles"] == 1
    # the target-time calculation is unchanged by the stage
    assert payload["target_time_iso"] == stage0_payload["target_time_iso"]
    assert payload["prediction_horizon_days"] == stage0_payload["prediction_horizon_days"]
    assert payload["issued_from_iso"] == stage0_payload["issued_from_iso"]


def test_stage1_median_mode_is_reported_as_its_own_method(tmp_path):
    stage0 = load_calibration(calibration_artifact(tmp_path / "stage0.json"))
    stage1 = load_stage1_calibration(stage1_artifact(tmp_path / "prediction_calibration_stage1.json"))
    features = build_float_features(
        2900003, row_with([fix(30, 0.0, 60.0, 1), fix(20, 0.4, 60.4, 2), fix(10, 0.8, 60.8, 3)]),
        None, NOW,
    )
    payload = pr.predict_float(
        features, pool=[], calibration=stage0, now=NOW,
        cycle_step_mode=STEP_MEDIAN, calibration_stage1=stage1,
    )
    assert payload["method"] == METHOD_CYCLE_MEDIAN
    assert payload["predictor_stage"] == "stage1"
    assert payload["r90_km"] == 208.9


def test_stage1_without_its_own_calibration_refuses_and_never_borrows_stage0(tmp_path):
    stage0 = load_calibration(calibration_artifact(tmp_path / "stage0.json"))
    features = build_float_features(
        2900004, row_with([fix(30, 0.0, 60.0, 1), fix(20, 0.4, 60.4, 2), fix(10, 0.8, 60.8, 3)]),
        None, NOW,
    )
    payload = pr.predict_float(
        features, pool=[], calibration=stage0, now=NOW,
        cycle_step_mode=STEP_WINDOW, calibration_stage1=None,
    )
    assert payload["available"] is False
    assert payload["status"] == pr.STATUS_INSUFFICIENT_VALIDATION
    assert payload["predicted_lat"] is None and payload["predicted_lon"] is None
    assert payload["r50_km"] != 20.0  # Stage-0 radius never reused
    assert payload["r50_km"] is None
    assert payload["stage1_fallback_reason"] == "Stage-1 calibration artefact not available"


def test_stage1_falls_back_to_the_stage0_branch_with_a_documented_reason(tmp_path):
    stage0 = load_calibration(calibration_artifact(tmp_path / "stage0.json"))
    stage1 = load_stage1_calibration(stage1_artifact(tmp_path / "prediction_calibration_stage1.json"))
    # telemetry-burst history only: three fixes one day apart over a 10 d interval.
    # Rung 4 does fire (the hops are short, not gappy), so Stage-1 is consulted and
    # then has to say "no cycle-scale window" — it must not stretch a burst into a cycle.
    features = build_float_features(
        2900005, row_with([fix(3, 0.0, 60.0, 1), fix(2, 0.2, 60.2, 2), fix(1, 0.4, 60.4, 3)]),
        None, NOW,
    )
    payload = pr.predict_float(
        features, pool=[], calibration=stage0, now=NOW,
        cycle_step_mode=STEP_WINDOW, calibration_stage1=stage1,
    )
    assert payload["available"] is True
    assert payload["predictor_stage"] == "stage0"  # the Stage-0 branch served this case
    # 120 d apart is a mission gap, so no eligible transition and no prior exist:
    # Stage-0 itself is down to persistence here, and Stage-1 changed nothing
    assert payload["method"] in (METHOD_TRAJECTORY, METHOD_HISTORY_PRIOR, METHOD_PERSISTENCE)
    assert payload["r50_km"] == 20.0  # Stage-0 radii, because Stage-0 produced it
    assert "telemetry burst, not a cycle" in payload["stage1_fallback_reason"]
    assert any("Stage-1 cycle-scale step unavailable" in issue for issue in payload["issues"])
    # and the burst hop really is what Stage-0 applied (the baseline is untouched)
    applied = haversine_km(0.4, 60.4, payload["predicted_lat"], payload["predicted_lon"])
    assert applied < 40.0  # a one-day hop, never a stretched full-cycle displacement


def test_stage1_reports_the_reason_when_rung4_never_fires(tmp_path):
    """Two fixes 120 d apart: no eligible hop, so Stage-0 serves and the reason is explicit."""
    stage0 = load_calibration(calibration_artifact(tmp_path / "stage0.json"))
    stage1 = load_stage1_calibration(stage1_artifact(tmp_path / "prediction_calibration_stage1.json"))
    features = build_float_features(2900008, row_with([fix(120, 0.0, 60.0, 1), fix(0, 4.0, 70.0, 2)]), None, NOW)
    payload = pr.predict_float(
        features, pool=[], calibration=stage0, now=NOW,
        cycle_step_mode=STEP_WINDOW, calibration_stage1=stage1,
    )
    assert payload["predictor_stage"] == "stage0"
    assert "no eligible trajectory transition" in payload["stage1_fallback_reason"]
    # Stage-0 mode never carries the Stage-1 field at all
    plain = pr.predict_float(features, pool=[], calibration=stage0, now=NOW)
    assert not plain.get("stage1_fallback_reason")


def test_stage1_gap_normalisation_is_reported_on_the_payload(tmp_path):
    stage0 = load_calibration(calibration_artifact(tmp_path / "stage0.json"))
    stage1 = load_stage1_calibration(stage1_artifact(tmp_path / "prediction_calibration_stage1.json"))
    features = build_float_features(
        2900006,
        row_with([fix(60, 0.0, 60.0, 1), fix(50, 0.2, 60.2, 2), fix(20, 5.0, 66.0, 3), fix(0, 12.0, 76.0, 4)]),
        None, NOW,
    )
    payload = pr.predict_float(
        features, pool=[], calibration=stage0, now=NOW,
        cycle_step_mode=STEP_WINDOW, calibration_stage1=stage1,
    )
    assert payload["predictor_stage"] == "stage1"
    assert payload["step_cycles"] == 2  # the 20 d gap over a 10 d interval
    assert any("gap normalised" in issue for issue in payload["issues"])
    # a multi-cycle span is divided, so the applied step is a one-cycle displacement
    assert payload["step_ratio"] > 1.9 and payload["step_span_days"] > 19


def test_future_fixes_never_change_a_stage1_prediction(tmp_path):
    """A fix dated after the prediction time is filtered before any step is built."""
    stage0 = load_calibration(calibration_artifact(tmp_path / "stage0.json"))
    stage1 = load_stage1_calibration(stage1_artifact(tmp_path / "prediction_calibration_stage1.json"))
    past = [fix(30, 0.0, 60.0, 1), fix(20, 0.4, 60.4, 2), fix(10, 0.8, 60.8, 3)]
    features = build_float_features(2900007, row_with(past), None, NOW)
    future = fix(-2.0, 40.0, 120.0, 99)  # dated two days after NOW
    with_future = build_float_features(2900007, row_with(past + [future]), None, NOW)
    payload = pr.predict_float(
        features, pool=[], calibration=stage0, now=NOW,
        cycle_step_mode=STEP_WINDOW, calibration_stage1=stage1,
    )
    other = pr.predict_float(
        with_future, pool=[], calibration=stage0, now=NOW,
        cycle_step_mode=STEP_WINDOW, calibration_stage1=stage1,
    )
    assert [f["juld"] for f in with_future.fixes] == [f["juld"] for f in features.fixes]
    assert payload["predicted_lat"] == other["predicted_lat"]
    assert payload["predicted_lon"] == other["predicted_lon"]
    assert payload["step_basis"] == other["step_basis"]


def test_predict_fleet_plumbs_the_stage_and_keeps_every_float(tmp_path):
    stage0 = load_calibration(calibration_artifact(tmp_path / "stage0.json"))
    stage1 = load_stage1_calibration(stage1_artifact(tmp_path / "prediction_calibration_stage1.json"))
    features_by_wmo = {
        2900011: build_float_features(
            2900011, row_with([fix(30, 0.0, 60.0, 1), fix(20, 0.4, 60.4, 2), fix(10, 0.8, 60.8, 3)]), None, NOW),
        2900012: build_float_features(
            2900012, row_with([fix(120, 0.0, 55.0, 1), fix(0, 9.0, 74.0, 2)]), None, NOW),
    }
    payloads = pr.predict_fleet(
        features_by_wmo, calibration=stage0, now=NOW,
        cycle_step_mode=STEP_WINDOW, calibration_stage1=stage1,
    )
    assert set(payloads) == set(features_by_wmo)
    assert payloads[2900011]["predictor_stage"] == "stage1"
    assert payloads[2900011]["method"] == METHOD_CYCLE_WINDOW
    assert payloads[2900012]["predictor_stage"] == "stage0"  # no window: Stage-0 branch


# ------------------------------------------------- shipped artefacts stay separate
def test_stage0_artefact_is_not_overwritten_by_the_stage1_candidate():
    """The baseline artefact must stay a Stage-0 artefact on disk."""
    stage0 = json.loads((REPO / "data/fleet_status/prediction_calibration.json").read_text())
    assert "stage" not in stage0  # unchanged since it was generated for Stage-0
    assert stage0["blend_weight_on_prior"] == 0.2
    assert set(stage0["methods"]) == {
        "history_prior", "trajectory_extrapolation", "regional_prior", "persistence"
    }
    stage1 = json.loads((REPO / "data/fleet_status/prediction_calibration_stage1.json").read_text())
    assert stage1["stage"] == "stage1"
    assert set(stage1["methods"]) == {
        "cycle_window", "cycle_window_prior", "cycle_median", "cycle_median_prior"
    }
    assert stage1["ship_gate"]["passed"] is False  # the candidate did not meet the gate
    assert stage1["ship_gate"]["default_mode"] == "off"
    assert stage1["baseline"]["stage0_calibration"].endswith("prediction_calibration.json (unchanged)")
    assert "no Stage-0 R50/R90 is reused" in stage1["baseline"]["note"]

# ------------------------------------------------- forward-test stage distinction
def _forward_artifacts(tmp_path):
    """A Stage-0 artefact (small radii) plus a Stage-1 candidate (larger radii)."""
    stage0 = load_calibration(calibration_artifact(
        tmp_path / "stage0.json",
        methods={
            METHOD_TRAJECTORY: {"default": {"n": 100, "r50_km": 5.0, "r90_km": 9.0,
                                            "metrics": {"n": 100}}, "strata": {}},
            METHOD_HISTORY_PRIOR: {"default": {"n": 100, "r50_km": 5.0, "r90_km": 9.0,
                                               "metrics": {"n": 100}}, "strata": {}},
            METHOD_REGIONAL_PRIOR: {"default": {"n": 100, "r50_km": 5.0, "r90_km": 9.0,
                                                "metrics": {"n": 100}}, "strata": {}},
            METHOD_PERSISTENCE: {"default": {"n": 100, "r50_km": 5.0, "r90_km": 9.0,
                                             "metrics": {"n": 100}}, "strata": {}},
        },
    ))
    stage1 = load_stage1_calibration(stage1_artifact(tmp_path / "prediction_calibration_stage1.json"))
    return stage0, stage1


def test_forward_log_keeps_stage0_and_stage1_issues_distinguishable(tmp_path):
    """The audit must never pool the two stages into one set of numbers."""
    from prediction.forward_test import ForwardTestLog

    stage0, stage1 = _forward_artifacts(tmp_path)
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=True)

    # one float, one cycle: issued while Stage-0 was the active Predictor
    fixes_two = [fix(20, -10.0, 60.0, 1), fix(10, -10.2, 60.2, 2)]
    features_two = {2903001: build_float_features(2903001, row_with(fixes_two), None, NOW)}
    stage0_payload = pr.predict_float(features_two[2903001], pool=[], calibration=stage0, now=NOW)
    assert stage0_payload["predictor_stage"] == "stage0"
    log.observe(features_two, {2903001: stage0_payload}, now=NOW)

    # the next cycle: the operator turns Stage-1 on, so the new issue carries stage1
    fixes_three = fixes_two + [fix(0, -10.4, 60.4, 3)]
    features_three = {2903001: build_float_features(2903001, row_with(fixes_three), None, NOW)}
    stage1_payload = pr.predict_float(
        features_three[2903001], pool=[], calibration=stage0, now=NOW,
        cycle_step_mode=STEP_WINDOW, calibration_stage1=stage1,
    )
    assert stage1_payload["predictor_stage"] == "stage1"
    summary = log.observe(features_three, {2903001: stage1_payload}, now=NOW)

    events = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    issued = [e for e in events if e["kind"] == "issued"]
    assert [e["predictor_stage"] for e in issued] == ["stage0", "stage1"]
    assert issued[1]["step_basis"] and issued[1]["step_cycles"] == 1
    assert issued[0]["step_basis"] is None  # Stage-0 issues never claim a step basis

    # scored events inherit the stage of the issue they came from
    scored = [e for e in events if e["kind"] == "scored"]
    assert scored and all(e["predictor_stage"] == "stage0" for e in scored)
    # pending issues are attributed to their stage before anything is scored
    assert summary["issued_by_stage"] == {"stage0": 1, "stage1": 1}
    # ... and the report groups by stage rather than merging them
    assert set(summary["stages"]) == {"stage0"}
    assert summary["stages"]["stage0"]["n"] == len(scored)
    assert summary["overall"]["n"] == len(scored)
    # radii are quoted from the issue, never re-derived at scoring time
    assert all(e["r50_km"] == 5.0 for e in scored)


def test_forward_report_groups_scored_rows_by_stage(tmp_path):
    from prediction.forward_test import ForwardTestLog, _summarize  # noqa: F401

    stage0, stage1 = _forward_artifacts(tmp_path)
    log = ForwardTestLog(tmp_path / "audit.jsonl", enabled=True)
    fixes = [fix(20, -10.0, 60.0, 1), fix(10, -10.2, 60.2, 2)]
    features_two = {2903002: build_float_features(2903002, row_with(fixes), None, NOW)}
    stage0_payload = pr.predict_float(features_two[2903002], pool=[], calibration=stage0, now=NOW)
    stage1_payload = pr.predict_float(
        features_two[2903002], pool=[], calibration=stage0, now=NOW,
        cycle_step_mode=STEP_WINDOW, calibration_stage1=stage1,
    )
    # both stages issued from the same fix (a validation deployment does exactly this),
    # then scored against the same later verified cycle
    log.observe(features_two, {2903002: stage0_payload}, now=NOW)
    # the second issue comes from the same fix, so use a distinct float for it
    features_two_b = {2903003: build_float_features(2903003, row_with(fixes), None, NOW)}
    stage1_payload_b = pr.predict_float(
        features_two_b[2903003], pool=[], calibration=stage0, now=NOW,
        cycle_step_mode=STEP_WINDOW, calibration_stage1=stage1,
    )
    log.observe(features_two_b, {2903003: stage1_payload_b}, now=NOW)

    later = [fix(20, -10.0, 60.0, 1), fix(10, -10.2, 60.2, 2), fix(0, -14.0, 65.0, 3)]
    arrived = {
        2903002: build_float_features(2903002, row_with(later), None, NOW),
        2903003: build_float_features(2903003, row_with(later), None, NOW),
    }
    summary = log.observe(
        arrived,
        {
            2903002: pr.predict_float(arrived[2903002], pool=[], calibration=stage0, now=NOW),
            2903003: pr.predict_float(
                arrived[2903003], pool=[], calibration=stage0, now=NOW,
                cycle_step_mode=STEP_WINDOW, calibration_stage1=stage1,
            ),
        },
        now=NOW,
    )
    assert summary["scored"] == 2
    assert set(summary["stages"]) == {"stage0", "stage1"}
    assert summary["stages"]["stage0"]["n"] == 1 and summary["stages"]["stage1"]["n"] == 1
    # both stages are separately summarised, and the pooled figure keeps both rows
    assert summary["overall"]["n"] == 2
    assert summary["methods"]  # struck method keys stay as served (cycle_window vs trajectory)
    assert any(key.startswith("cycle_") for key in summary["methods"])

