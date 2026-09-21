"""Next Profile Location prediction: ladder, leakage guards, uncertainty.

Network-free. Uses synthetic cached rows (the same shape fleet_status.py
stores) plus a temporary calibration artefact, so every rule below is pinned
without touching the live cache, the GDAC or the decoder core.

Contract highlights under test:
  * no future information is ever read (fixes are filtered at `now`);
  * the prior pool excludes the target float and any transition that started at
    or after the prediction time (leave-one-float-out + delivery lag);
  * no prediction is produced without a validated radius;
  * insufficient data yields an explicit unavailable status, never a position.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="decoder-ui-prediction-test-")
os.environ["ARGO_UI_DATA_DIR"] = _TMP

import profile_cycle  # noqa: E402
from prediction import predict as pr  # noqa: E402
from prediction.calibrate import (  # noqa: E402
    METHOD_HISTORY_PRIOR,
    METHOD_PERSISTENCE,
    METHOD_REGIONAL_PRIOR,
    METHOD_TRAJECTORY,
    load_calibration,
    radii_for,
)
from prediction.currents import (  # noqa: E402
    CurrentSourceUnavailable,
    NoCurrentProvider,
    UnconfiguredCMEMSProvider,
)
from prediction.features import (  # noqa: E402
    FloatFeatures,
    build_float_features,
    region_of,
    transitions_from_fixes,
)
from prediction.geometry import destination, haversine_km  # noqa: E402
from prediction.prior import grid_prior, neighbourhood_prior  # noqa: E402

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


def row_with(fixes: list[dict], interval: dict | None = None, **extra) -> dict:
    return {
        "rtraj": {
            "recent_fixes": fixes,
            "cycle_intervals": interval or {"n": 4, "median_days": 10.0},
            "park_pressure_dbar": 1000.0,
            "phase_hours": {"descent_h": 5.0, "park_h": 220.0, "ascent_h": 5.0},
        },
        "profile_aggregate": {"juld_intervals": interval or {"n": 4, "median_days": 10.0}},
        **extra,
    }


# --------------------------------------------------------------------- calibration
def calibration_artifact(path: Path, methods: dict | None = None) -> Path:
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
            for key in (METHOD_HISTORY_PRIOR, METHOD_TRAJECTORY, METHOD_REGIONAL_PRIOR, METHOD_PERSISTENCE)
        },
    }
    path.write_text(json.dumps(artifact))
    return path


# --------------------------------------------------------------------- features
def test_fixes_after_now_are_never_used():
    features = build_float_features(
        2900001,
        row_with([fix(20, -10.0, 60.0, 1), fix(10, -10.5, 60.4, 2), fix(-1, -11.0, 61.0, 3)]),
        {"platform_type": "APEX"},
        NOW,
    )
    assert [f["cycle"] for f in features.fixes] == [1, 2]
    assert len(features.transitions) == 1
    assert features.last_fix["cycle"] == 2


def test_legacy_single_fix_row_still_yields_features_and_flags_the_gap():
    features = build_float_features(
        2900002,
        {"rtraj": {"last_fix": fix(3, -12.0, 58.0, 9)}},
        {"platform_type": "ARVOR"},
        NOW,
    )
    assert features.has_position
    assert features.transitions == []
    assert any("single cached trajectory fix" in issue for issue in features.issues)


def test_transitions_skip_mission_gaps():
    fixes = [fix(60, 0.0, 60.0, 1), fix(50, 0.5, 60.2, 2), fix(10, 1.0, 60.6, 3)]
    assert len(transitions_from_fixes(1, fixes)) == 1  # 40-day gap is not a cycle


def test_region_boxes_are_stable():
    assert region_of(15.0, 60.0) == "Arabian Sea"
    assert region_of(15.0, 88.0) == "Bay of Bengal"
    assert region_of(-5.0, 75.0) == "Equatorial Indian"
    assert region_of(-40.0, 60.0) == "South Indian Ocean"


# --------------------------------------------------------------------- prior
def test_neighbourhood_prior_excludes_the_target_float_and_the_future():
    import prediction.features as features_module

    def transition(wmo, days_ago, lat, lon, dlat, dlon):
        return features_module.Transition(
            wmo=wmo,
            start_juld=juld(NOW - timedelta(days=days_ago)),
            lat=lat,
            lon=lon,
            dlat_km=dlat,
            dlon_km=dlon,
            days=10.0,
            cycle_from=1,
            cycle_to=2,
        )

    pool = [
        # target float's OWN past transitions (must never inform its prediction)
        *[transition(2900001, 30 + i, -10.0, 60.0, 1000.0, 1000.0) for i in range(6)],
        # another float's transitions, some of them in the FUTURE of the case
        *[transition(2900002, 5 + i, -10.0, 60.0, 12.0, 30.0) for i in range(6)],
        *[transition(2900003, -5 - i, -10.0, 60.0, 999.0, 999.0) for i in range(6)],
    ]
    result = neighbourhood_prior(
        pool,
        exclude_wmo=2900001,
        lat=-10.0,
        lon=60.0,
        juld=juld(NOW),
    )
    assert result is not None
    assert result.neighbours == 6
    assert result.dlat_km == pytest.approx(12.0)
    assert result.dlon_km == pytest.approx(30.0)


def test_neighbourhood_prior_refuses_below_minimum_neighbours():
    assert (
        neighbourhood_prior([], exclude_wmo=1, lat=0.0, lon=60.0, juld=juld(NOW)) is None
    )


def test_grid_prior_uses_nearest_calibrated_cell():
    cells = {"-5_30_9": [10.0, 20.0, 25]}
    result = grid_prior(cells, lat=-10.0, lon=61.0, juld=juld(NOW))
    assert result is not None and result.neighbours == 25
    assert result.dlat_km == pytest.approx(10.0)
    assert grid_prior({"-5_30_9": [10.0, 20.0, 2]}, lat=-10.0, lon=61.0, juld=juld(NOW)) is None


# --------------------------------------------------------------------- ladder
def test_no_position_is_never_a_prediction():
    features = FloatFeatures(wmo=2900003, interval_days=10.0)
    payload = pr.predict_float(
        features, pool=[], calibration=load_calibration(Path(_TMP) / "missing.json"), now=NOW
    )
    assert payload["status"] == pr.STATUS_INSUFFICIENT_DATA
    assert payload["predicted_lat"] is None and payload["predicted_lon"] is None
    assert payload["available"] is False


def test_missing_calibration_refuses_instead_of_inventing_a_radius(tmp_path):
    features = build_float_features(2900004, row_with([fix(20, -10.0, 60.0, 1), fix(10, -10.5, 60.5, 2)]), None, NOW)
    payload = pr.predict_float(
        features,
        pool=[],
        calibration=load_calibration(tmp_path / "absent.json"),
        now=NOW,
    )
    assert payload["status"] == pr.STATUS_INSUFFICIENT_VALIDATION
    assert payload["predicted_lat"] is None
    assert "validation" in (payload["status_message"] or "")


def test_ladder_selects_history_prior_when_a_prior_exists(tmp_path):
    art = calibration_artifact(tmp_path / "cal.json")
    calibration = load_calibration(art)
    features = build_float_features(
        2900005, row_with([fix(20, -10.0, 60.0, 1), fix(10, -10.4, 60.4, 2)]), None, NOW
    )
    import prediction.features as features_module

    pool = [
        features_module.Transition(
            wmo=2900006,
            start_juld=juld(NOW - timedelta(days=20 + i)),
            lat=-10.0,
            lon=60.0,
            dlat_km=15.0,
            dlon_km=25.0,
            days=10.0,
            cycle_from=i,
            cycle_to=i + 1,
        )
        for i in range(6)
    ]
    payload = pr.predict_float(features, pool=pool, calibration=calibration, now=NOW)
    assert payload["status"] == pr.STATUS_OK
    assert payload["method"] == METHOD_HISTORY_PRIOR
    assert payload["method_label"] == "History + Prior"
    assert payload["fallback_rung"] == 4
    assert payload["validation_samples"] == 120
    assert payload["r50_km"] == 20.0 and payload["r90_km"] == 70.0
    # Deterministic blend: 0.8 * last displacement + 0.2 * prior.
    last = features.last_transition
    expected = destination(
        features.last_fix["lat"],
        features.last_fix["lon"],
        0.8 * last.dlat_km + 0.2 * 15.0,
        0.8 * last.dlon_km + 0.2 * 25.0,
    )
    assert payload["predicted_lat"] == pytest.approx(round(expected[0], 4))
    assert payload["predicted_lon"] == pytest.approx(round(expected[1], 4))
    assert payload["label"] == "Experimental prediction — not a communication signal"


def test_ladder_falls_back_to_trajectory_extrapolation_without_prior(tmp_path):
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = build_float_features(
        2900007, row_with([fix(20, 15.0, 70.0, 1), fix(10, 15.4, 70.6, 2)]), None, NOW
    )
    payload = pr.predict_float(features, pool=[], calibration=calibration, now=NOW)
    assert payload["status"] == pr.STATUS_OK
    assert payload["method"] == METHOD_TRAJECTORY
    last = features.last_transition
    expected = destination(features.last_fix["lat"], features.last_fix["lon"], last.dlat_km, last.dlon_km)
    assert payload["predicted_lat"] == pytest.approx(round(expected[0], 4))


def test_ladder_falls_back_to_regional_prior_without_history(tmp_path):
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = build_float_features(2900008, row_with([fix(3, 16.0, 88.0, 7)]), None, NOW)
    cells = {"8_44_9": [25.0, -10.0, 30]}
    payload = pr.predict_float(features, pool=[], calibration=calibration, now=NOW, grid_cells=cells)
    assert payload["status"] == pr.STATUS_OK
    assert payload["method"] == METHOD_REGIONAL_PRIOR
    assert payload["predicted_lat"] == pytest.approx(round(16.0 + 25.0 / 110.574, 4))


def test_ladder_last_resort_is_persistence(tmp_path):
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = build_float_features(2900009, row_with([fix(3, 16.0, 61.0, 7)]), None, NOW)
    payload = pr.predict_float(features, pool=[], calibration=calibration, now=NOW, grid_cells={})
    assert payload["method"] == METHOD_PERSISTENCE
    assert payload["predicted_lat"] == pytest.approx(16.0)
    assert payload["predicted_lon"] == pytest.approx(61.0)


def test_target_time_and_horizon_follow_the_observed_interval(tmp_path):
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = build_float_features(
        2900010, row_with([fix(20, -5.0, 60.0, 1), fix(10, -5.1, 60.2, 2)]), None, NOW
    )
    payload = pr.predict_float(features, pool=[], calibration=calibration, now=NOW)
    assert payload["expected_interval_days"] == pytest.approx(10.0)
    assert payload["prediction_horizon_days"] == pytest.approx(10.0)
    issued = datetime.fromisoformat(payload["issued_from_iso"].replace("Z", "+00:00"))
    target = datetime.fromisoformat(payload["target_time_iso"].replace("Z", "+00:00"))
    assert (target - issued).total_seconds() == pytest.approx(10 * 86400.0, abs=1.0)


# --------------------------------------------------------------------- currents
def test_default_provider_is_explicitly_absent_and_reported(tmp_path):
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = build_float_features(
        2900011, row_with([fix(20, -5.0, 60.0, 1), fix(10, -5.1, 60.2, 2)]), None, NOW
    )
    payload = pr.predict_float(features, pool=[], calibration=calibration, now=NOW)
    assert any("rungs skipped" in issue for issue in payload["issues"])
    assert payload["ensemble_members"] is None


def test_cmems_provider_is_credential_gated_and_never_fabricates():
    provider = UnconfiguredCMEMSProvider()
    assert provider.available() is False
    with pytest.raises(CurrentSourceUnavailable):
        provider.velocity(0.0, 60.0, 1000.0, juld(NOW))
    assert "not implemented" in provider.describe() or "credentials" in provider.describe()
    noop = NoCurrentProvider()
    assert noop.available() is False
    with pytest.raises(CurrentSourceUnavailable):
        noop.velocity(0.0, 60.0, 1000.0, juld(NOW))


def test_current_assisted_path_runs_when_a_provider_exists(tmp_path):
    class FakeProvider:
        name = "fake-unittest"

        def available(self) -> bool:
            return True

        def describe(self) -> str:
            return "unit-test constant current (not a real product)"

        def velocity(self, lat, lon, depth_dbar, when_juld):
            return (0.5, -0.2)  # eastward 0.5 m/s, southward 0.2 m/s

    calibration = load_calibration(
        calibration_artifact(
            tmp_path / "cal.json",
            methods={
                key: {"default": {"n": 60, "r50_km": 25.0, "r90_km": 80.0, "metrics": {"n": 60}}, "strata": {}}
                for key in ("current_assisted", "physics_lagrangian")
            },
        )
    )
    # Two observed hops -> the "recent trajectory history + currents" rung.
    features = build_float_features(
        2900012,
        row_with([fix(30, -5.0, 60.0, 1), fix(20, -5.05, 60.1, 2), fix(10, -5.1, 60.2, 3)]),
        None,
        NOW,
    )
    payload = pr.predict_float(
        features, pool=[], calibration=calibration, now=NOW, provider=FakeProvider()
    )
    assert payload["status"] == pr.STATUS_OK
    assert payload["method"] == "current_assisted"
    assert payload["fallback_rung"] == 1
    assert payload["ensemble_members"] == 100
    # Eastward drift must move the prediction east of the last fix.
    assert payload["predicted_lon"] > features.last_fix["lon"]


def test_current_assisted_with_short_history_uses_the_physics_rung(tmp_path):
    class FakeProvider:
        name = "fake-unittest"

        def available(self) -> bool:
            return True

        def describe(self) -> str:
            return "unit-test constant current"

        def velocity(self, lat, lon, depth_dbar, when_juld):
            return (0.0, 0.4)  # northward only

    calibration = load_calibration(
        calibration_artifact(
            tmp_path / "cal.json",
            methods={
                key: {"default": {"n": 30, "r50_km": 40.0, "r90_km": 120.0, "metrics": {"n": 30}}, "strata": {}}
                for key in ("current_assisted", "physics_lagrangian")
            },
        )
    )
    # A single hop is enough for rung 3 (available history + currents).
    features = build_float_features(
        2900016, row_with([fix(20, -5.0, 60.0, 1), fix(10, -5.1, 60.2, 2)]), None, NOW
    )
    payload = pr.predict_float(
        features, pool=[], calibration=calibration, now=NOW, provider=FakeProvider()
    )
    assert payload["status"] == pr.STATUS_OK
    assert payload["method"] == "physics_lagrangian"
    assert payload["fallback_rung"] == 3
    assert payload["predicted_lat"] > features.last_fix["lat"]


def test_current_assisted_without_calibration_is_refused(tmp_path):
    class FakeProvider:
        name = "fake-unittest"

        def available(self) -> bool:
            return True

        def describe(self) -> str:
            return "unit-test constant current"

        def velocity(self, lat, lon, depth_dbar, when_juld):
            return (0.1, 0.1)

    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json", methods={}))
    features = build_float_features(
        2900013, row_with([fix(20, -5.0, 60.0, 1), fix(10, -5.1, 60.2, 2)]), None, NOW
    )
    payload = pr.predict_float(
        features, pool=[], calibration=calibration, now=NOW, provider=FakeProvider()
    )
    assert payload["status"] == pr.STATUS_INSUFFICIENT_VALIDATION
    assert payload["predicted_lat"] is None


# --------------------------------------------------------------------- fleet level
def test_predict_fleet_is_per_float_isolated_and_reports_every_float():
    features = {
        2900100: build_float_features(
            2900100, row_with([fix(20, -10.0, 60.0, 1), fix(10, -10.4, 60.4, 2)]), None, NOW
        ),
        2900101: build_float_features(2900101, {"rtraj": {}}, None, NOW),
    }
    payloads = pr.predict_fleet(
        features, calibration=load_calibration(Path(_TMP) / "absent.json"), now=NOW
    )
    assert set(payloads) == {2900100, 2900101}
    assert payloads[2900101]["status"] == pr.STATUS_INSUFFICIENT_DATA
    for payload in payloads.values():
        assert payload["label"] == "Experimental prediction — not a communication signal"


def test_predicted_position_stays_within_a_plausible_distance(tmp_path):
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = build_float_features(
        2900014, row_with([fix(20, 15.0, 70.0, 1), fix(10, 15.2, 70.3, 2)]), None, NOW
    )
    payload = pr.predict_float(features, pool=[], calibration=calibration, now=NOW)
    err = haversine_km(
        features.last_fix["lat"],
        features.last_fix["lon"],
        payload["predicted_lat"],
        payload["predicted_lon"],
    )
    assert err < 400.0  # one 10-day cycle of drift, not a teleport


def test_interval_source_is_carried_into_the_payload(tmp_path):
    calibration = load_calibration(calibration_artifact(tmp_path / "cal.json"))
    features = build_float_features(
        2900015,
        {
            "rtraj": {"recent_fixes": [fix(20, 0.0, 60.0, 1), fix(10, 0.1, 60.1, 2)]},
            "profile_aggregate": {"juld_intervals": {"n": 0, "median_days": None}},
        },
        None,
        NOW,
    )
    payload = pr.predict_float(features, pool=[], calibration=calibration, now=NOW)
    assert payload["interval_source"] == profile_cycle.INTERVAL_SOURCE_DEFAULT
    assert "10-day" in (payload["issues"] + [""])[-1] or any(
        "fallback" in issue for issue in payload["issues"]
    )


def test_radii_lookup_uses_stratum_then_default():
    artifact = {
        "version": 1,
        "blend_weight_on_prior": 0.2,
        "methods": {
            METHODS_KEY: {
            "default": {"n": 500, "r50_km": 30.0, "r90_km": 100.0, "metrics": {"n": 500}},
            "strata": {
                "Arabian Sea|decadal": {"n": 90, "r50_km": 12.0, "r90_km": 40.0, "metrics": {"n": 90}},
                "Arabian Sea|*": {"n": 300, "r50_km": 20.0, "r90_km": 60.0, "metrics": {"n": 300}},
                },
            },
        },
    }
    import json as _json

    path = Path(_TMP) / "strata.json"
    path.write_text(_json.dumps(artifact))
    calibration = load_calibration(path)
    exact = radii_for(calibration, METHODS_KEY, "Arabian Sea", "decadal")
    regional = radii_for(calibration, METHODS_KEY, "Arabian Sea", "short")
    default = radii_for(calibration, METHODS_KEY, "Other", "decadal")
    assert (exact.r50_km, exact.r90_km, exact.samples) == (12.0, 40.0, 90)
    assert (regional.r50_km, regional.r90_km) == (20.0, 60.0)
    assert (default.r50_km, default.r90_km) == (30.0, 100.0)
    assert radii_for(calibration, "unknown_method") is None


METHODS_KEY = METHOD_HISTORY_PRIOR


# --------------------------------------------------------------------- payload
def test_fleet_status_payload_carries_a_prediction_for_every_float(tmp_path, monkeypatch):
    """Integration: the served Float Status payload embeds the prediction and
    the fleet-wide prediction summary, without changing status semantics."""
    import fleet_status as fs

    monkeypatch.setenv("PREDICTION_CALIBRATION_PATH", str(calibration_artifact(tmp_path / "cal.json")))
    registry = fs.FleetSyncRegistry(
        state_path=tmp_path / "cache.json",
        fleet_fn=lambda: [
            {"wmo": 2900200, "platform_type": "APEX", "transmission_type": "ARGOS"},
            {"wmo": 2900201, "platform_type": "ARVOR", "transmission_type": "IRIDIUM_SBD"},
        ],
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
        "2900200": {
            **base,
            **row_with(
                [
                    fix(30, -10.0, 60.0, 1),
                    fix(20, -10.3, 60.3, 2),
                    fix(10, -10.5, 60.6, 3),
                ]
            ),
            "profile_aggregate": {
                "file": "2900200_prof.nc",
                "platform_number": "2900200",
                "juld": juld(NOW - timedelta(days=10)),
                "measurement_index": 3,
                "measurement_cycle": 3,
                "juld_intervals": {"n": 4, "median_days": 10.0},
            },
        },
        "2900201": {**base, "rtraj": {}, "profile_aggregate": {}},
    }
    payload = registry.payload()
    rows = {item["wmo"]: item for item in payload["floats"]}
    assert rows[2900200]["prediction"]["available"] is True
    assert rows[2900200]["prediction"]["predicted_lat"] is not None
    assert rows[2900200]["prediction"]["validation_samples"] == 120
    assert rows[2900201]["prediction"]["available"] is False
    assert rows[2900201]["prediction"]["predicted_lat"] is None
    assert payload["prediction"]["available"] == 1
    assert payload["prediction"]["unavailable"] == 1
    assert payload["prediction"]["methods"]
    assert payload["prediction"]["calibration"]["available"] is True
    # Status semantics are untouched by the prediction feature.
    assert rows[2900200]["data_status"] in {
        "ACTIVE / RECENT PROFILE",
        "PROFILE OVERDUE",
        "NO RECENT PROFILE DATA 60+ DAYS",
        "NO DATA",
    }


def test_prediction_failure_never_breaks_the_status_rows(tmp_path, monkeypatch):
    import fleet_status as fs

    monkeypatch.setenv("PREDICTION_CALIBRATION_PATH", str(tmp_path / "missing.json"))
    registry = fs.FleetSyncRegistry(
        state_path=tmp_path / "cache.json",
        fleet_fn=lambda: [{"wmo": 2900300, "platform_type": "APEX"}],
        enabled=False,
    )
    registry._rows = {
        "2900300": {
            "in_incois_dac": True,
            "parser_version": fs.PARSER_VERSION,
            "profile_recency_version": fs.PROFILE_RECENCY_VERSION,
            "checked_at": NOW.isoformat(),
            "profile_checked_at": NOW.isoformat(),
            "profile_aggregate_fp": "x",
            "rtraj": {"recent_fixes": [fix(5, 0.0, 60.0, 1)]},
            "profile_aggregate": {},
        }
    }
    payload = registry.payload()
    assert payload["floats"][0]["wmo"] == 2900300
    assert payload["floats"][0]["prediction"]["status"] == pr.STATUS_INSUFFICIENT_VALIDATION


# ------------------------------------------------------- input advisories
def test_step_advisory_flags_hops_that_are_not_cycle_scale():
    """Reporting only: the method, rung and radius are never changed by this."""
    import fleet_status as fs

    calibration = load_calibration(
        calibration_artifact(
            Path(_TMP) / "cal-advisory.json",
            methods={
                "trajectory_extrapolation": {
                    "default": {"n": 100, "r50_km": 20.0, "r90_km": 70.0, "metrics": {"n": 100}},
                    "strata": {},
                }
            },
        )
    )
    # 10-day interval, last hop 0.7 d -> flagged
    burst = build_float_features(
        2902070, row_with([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.5, 2), fix(9.3, 2.0, 61.0, 3)]), None, NOW
    )
    burst.interval_days = 10.0
    advisory = fs.FleetSyncRegistry._step_advisory(burst)
    assert advisory is not None and "0.70 d" in advisory and "0.07x" in advisory

    # same shape at cycle scale -> silent
    normal = build_float_features(
        2902071, row_with([fix(20, 0.0, 60.0, 1), fix(10, 0.0, 60.5, 2)]), None, NOW
    )
    normal.interval_days = 10.0
    assert fs.FleetSyncRegistry._step_advisory(normal) is None

    # and the prediction itself is unchanged by the advisory
    payload = pr.predict_float(burst, pool=[], calibration=calibration, now=NOW)
    assert payload["method"] == "trajectory_extrapolation" and payload["fallback_rung"] == 4
    assert payload["r90_km"] == 70.0
