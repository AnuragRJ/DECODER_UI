"""Next Profile Location prediction facade + fallback ladder.

Fallback ladder (PART 3), evaluated in order and always reported explicitly:

1. recent trajectory history + ocean currents + cycle information
   -> method ``current_assisted`` ("Current-Assisted")
2. available trajectory history + ocean currents
   -> method ``current_assisted`` with the reduced-history note
3. ocean currents + regional/seasonal prior
   -> method ``physics_lagrangian`` ("Physics / Lagrangian")
4. validated history/prior baseline (what this deployment ships)
   -> ``history_prior`` (blend), ``trajectory_extrapolation``,
      ``regional_prior``, ``persistence`` in decreasing data availability
5. prediction unavailable -> ``insufficient_data`` / ``insufficient_validation``

Rules that are enforced in code, not conventions:

* every input is timestamped at or before the last observed fix;
* a prediction without a validated radius is refused, not embellished;
* a float with no verified upstream position gets no position prediction;
* the ensemble/physics rungs are skipped (and reported) whenever no current
  provider is available.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from prediction import calibrate as calibration_module
from prediction.advect import advect_ensemble
from prediction.calibrate import (
    METHOD_CURRENT_ASSISTED,
    METHOD_CYCLE_MEDIAN,
    METHOD_CYCLE_MEDIAN_PRIOR,
    METHOD_CYCLE_WINDOW,
    METHOD_CYCLE_WINDOW_PRIOR,
    METHOD_HISTORY_PRIOR,
    METHOD_LABELS,
    METHOD_PERSISTENCE,
    METHOD_PHYSICS,
    METHOD_REGIONAL_PRIOR,
    METHOD_TRAJECTORY,
    STAGE_LABELS,
    STAGE_STAGE0,
    STAGE_STAGE1,
    Calibration,
    radii_for,
)
from prediction.cycle_step import (
    STEP_MEDIAN,
    CYCLE_STEP_MODES,
    STEP_OFF,
    CycleStep,
    cycle_scale_step,
    fallback_reason,
    resolve_cycle_step_mode,
)
from prediction.currents import CurrentProvider, NoCurrentProvider, provider_from_env
from prediction.features import FloatFeatures, Transition, fleet_transitions
from prediction.geometry import destination
from prediction.prior import neighbourhood_prior, grid_prior

STATUS_OK = "ok"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_INSUFFICIENT_VALIDATION = "insufficient_validation"
STATUS_SOURCE_UNAVAILABLE = "source_unavailable"

UNAVAILABLE_MESSAGE = "Prediction unavailable — insufficient data"
UNVALIDATED_MESSAGE = "Prediction unavailable — insufficient validation data"
#: Minimum observed transitions for the current-assisted rung.
MIN_HISTORY_TRANSITIONS = 2


def _iso(juld: float) -> str:
    return (datetime(1950, 1, 1, tzinfo=UTC) + timedelta(days=float(juld))).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _base_payload(features: FloatFeatures, now: datetime) -> dict[str, Any]:
    return {
        "wmo": features.wmo,
        "available": False,
        "status": STATUS_INSUFFICIENT_DATA,
        "status_message": UNAVAILABLE_MESSAGE,
        "predicted_lat": None,
        "predicted_lon": None,
        "prediction_horizon_days": None,
        "target_time_iso": None,
        "r50_km": None,
        "r90_km": None,
        "method": None,
        "method_label": None,
        "fallback_rung": None,
        "validation_samples": 0,
        "validation_source": None,
        "ensemble_members": None,
        "ensemble_spread_km": None,
        "issued_from_iso": None,
        "issued_from_position": None,
        "expected_interval_days": round(float(features.interval_days), 2),
        "interval_source": features.interval_source,
        "interval_samples": features.interval_samples,
        "region": features.region,
        "cycle_class": features.cycle_class,
        "trajectory_transitions": len(features.transitions),
        "prior_neighbours": None,
        "prior_basis": None,
        "currents": provider_from_env().describe(),
        "predictor_stage": STAGE_STAGE0,
        "predictor_stage_label": STAGE_LABELS[STAGE_STAGE0],
        "step_basis": None,
        "step_span_days": None,
        "step_ratio": None,
        "step_cycles": None,
        "step_windows_used": None,
        "stage1_fallback_reason": None,
        "issues": list(features.issues),
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "label": "Experimental prediction — not a communication signal",
    }


def _refuse(payload: dict[str, Any], status: str, message: str, issue: str | None = None) -> dict:
    payload["status"] = status
    payload["status_message"] = message
    payload["available"] = False
    if issue:
        payload["issues"] = payload["issues"] + [issue]
    return payload


def _finish(
    payload: dict[str, Any],
    *,
    features: FloatFeatures,
    lat: float,
    lon: float,
    method_key: str,
    rung: int,
    radii: calibration_module.Radii | None,
    now: datetime,
    validation_source: str | None,
    ensemble: dict[str, Any] | None = None,
    stage: str = STAGE_STAGE0,
    step: CycleStep | None = None,
) -> dict[str, Any]:
    if radii is None:
        return _refuse(
            payload,
            STATUS_INSUFFICIENT_VALIDATION,
            UNVALIDATED_MESSAGE,
            "no validated uncertainty radius for this method/region/cycle class",
        )
    fix = features.last_fix or {}
    issued_juld = float(fix.get("juld") or 0.0)
    target_juld = issued_juld + float(features.interval_days)
    payload.update(
        available=True,
        status=STATUS_OK,
        status_message=None,
        predicted_lat=round(float(lat), 4),
        predicted_lon=round(float(lon), 4),
        prediction_horizon_days=round(float(features.interval_days), 2),
        target_time_iso=_iso(target_juld),
        r50_km=round(radii.r50_km, 1),
        r90_km=round(radii.r90_km, 1),
        method=method_key,
        method_label=METHOD_LABELS.get(method_key, method_key),
        fallback_rung=rung,
        validation_samples=radii.samples,
        validation_source=validation_source or radii.basis,
        issued_from_iso=_iso(issued_juld),
        issued_from_position=[round(float(fix.get("lat", lat)), 4), round(float(fix.get("lon", lon)), 4)],
        generated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        predictor_stage=stage,
        predictor_stage_label=STAGE_LABELS[stage],
    )
    if step is not None:
        payload["step_basis"] = step.basis
        payload["step_span_days"] = round(step.span_days, 2)
        payload["step_ratio"] = round(step.ratio, 3)
        payload["step_cycles"] = step.cycles
        payload["step_windows_used"] = step.windows_used
    if ensemble:
        payload["ensemble_members"] = ensemble.get("members")
        spread = ensemble.get("p90_spread_km")
        payload["ensemble_spread_km"] = None if spread is None else round(float(spread), 1)
    return payload


def _stage1_step(
    features: FloatFeatures,
    *,
    mode: str,
    calibration_stage1: Calibration | None,
    prior_source: Any,
    weight: float,
    lat0: float,
    lon0: float,
    payload: dict[str, Any],
    now: datetime,
) -> dict[str, Any] | None:
    """Apply the Stage-1 cycle-scale step, or return None to keep Stage-0.

    Returning ``None`` is the documented fallback: the caller continues into the
    unchanged Stage-0 branch, and the reason is recorded on the payload. Stage-1
    never substitutes a fabricated step, and it never borrows Stage-0 radii.
    """
    if mode == STEP_OFF:
        return None
    step: CycleStep | None = cycle_scale_step(features.fixes, features.interval_days, mode=mode)
    if step is None:
        payload["stage1_fallback_reason"] = fallback_reason(features.fixes, features.interval_days)
        payload["issues"] = list(payload.get("issues") or []) + [
            f"Stage-1 cycle-scale step unavailable — {payload['stage1_fallback_reason']}; "
            "Stage-0 last-hop step retained"
        ]
        return None
    if calibration_stage1 is None or not calibration_stage1.available:
        # Stage-1 radii are its own; without them the documented refusal applies.
        payload["stage1_fallback_reason"] = "Stage-1 calibration artefact not available"
        return _refuse(
            payload,
            STATUS_INSUFFICIENT_VALIDATION,
            UNVALIDATED_MESSAGE,
            "Stage-1 cycle-scale step has no calibrated uncertainty radius loaded",
        )
    method_key = (
        METHOD_CYCLE_MEDIAN if mode == STEP_MEDIAN else METHOD_CYCLE_WINDOW
    )
    issues = [f"step basis: {step.basis}"]
    if step.cycles > 1:
        issues.append(
            f"gap normalised: {step.span_days:.2f} d span divided by {step.cycles} cycles"
        )
    step_dlat, step_dlon = step.dlat_km, step.dlon_km
    if prior_source is not None:
        step_dlat = (1.0 - weight) * step.dlat_km + weight * prior_source.dlat_km
        step_dlon = (1.0 - weight) * step.dlon_km + weight * prior_source.dlon_km
        method_key = (
            METHOD_CYCLE_MEDIAN_PRIOR if mode == STEP_MEDIAN else METHOD_CYCLE_WINDOW_PRIOR
        )
        issues.extend(
            [
                f"blend weight on prior {weight:g} (LOFO-calibrated)",
                f"prior basis: {prior_source.basis} (n={prior_source.neighbours})",
            ]
        )
    else:
        issues.append("no regional/seasonal prior available for this position")
    lat, lon = destination(lat0, lon0, step_dlat, step_dlon)
    payload["issues"] = list(payload.get("issues") or []) + issues
    return _finish(
        payload,
        features=features,
        lat=lat,
        lon=lon,
        method_key=method_key,
        rung=4,
        radii=radii_for(
            calibration_stage1, method_key, features.region, features.cycle_class
        ),
        now=now,
        validation_source=None,
        stage=STAGE_STAGE1,
        step=step,
    )


def predict_float(
    features: FloatFeatures,
    *,
    pool: list[Transition],
    calibration: Calibration,
    provider: CurrentProvider | None = None,
    now: datetime | None = None,
    grid_cells: dict[str, Any] | None = None,
    blend_weight: float | None = None,
    cycle_step_mode: str | None = None,
    calibration_stage1: Calibration | None = None,
) -> dict[str, Any]:
    """Predict the next surfacing position of one float.

    ``cycle_step_mode`` selects the step model: ``off`` reproduces the Stage-0
    baseline exactly, ``window``/``median`` use the Stage-1 cycle-scale step with
    ``calibration_stage1`` supplying that stage's own radii.
    """
    now = now or datetime.now(UTC)
    provider = provider or NoCurrentProvider()
    mode = resolve_cycle_step_mode(cycle_step_mode)
    payload = _base_payload(features, now)
    payload["currents"] = provider.describe()
    payload["predictor_stage"] = STAGE_STAGE0
    payload["predictor_stage_label"] = STAGE_LABELS[STAGE_STAGE0]
    payload["step_basis"] = None

    if not features.has_position:
        return _refuse(
            payload,
            STATUS_INSUFFICIENT_DATA,
            UNAVAILABLE_MESSAGE,
            "no verified QC 1/2 upstream position available for this float",
        )
    fix = features.last_fix or {}
    lat0, lon0 = float(fix["lat"]), float(fix["lon"])
    weight = (
        float(blend_weight)
        if blend_weight is not None
        else float(calibration.blend_weight_on_prior)
    )

    prior = neighbourhood_prior(pool, exclude_wmo=features.wmo, lat=lat0, lon=lon0, juld=float(fix["juld"]))
    grid = None if prior else grid_prior(grid_cells if grid_cells is not None else calibration.prior_grid,
                                         lat=lat0, lon=lon0, juld=float(fix["juld"]))
    payload["prior_neighbours"] = (prior or grid).neighbours if (prior or grid) else 0
    payload["prior_basis"] = (prior or grid).basis if (prior or grid) else None

    # ---- rungs 1-3: current-assisted / physics (requires a provider) ----------
    if provider.available():
        ensemble = advect_ensemble(features, provider)
        if ensemble is not None:
            spread = sorted(ensemble.spread_km)
            p90 = spread[int(0.9 * (len(spread) - 1))] if spread else None
            method = (
                METHOD_CURRENT_ASSISTED
                if len(features.transitions) >= MIN_HISTORY_TRANSITIONS
                else METHOD_PHYSICS
            )
            payload["issues"] = payload["issues"] + [
                f"currents from {provider.name}"
                + ("" if len(features.transitions) >= MIN_HISTORY_TRANSITIONS else " (short history)")
            ]
            return _finish(
                payload,
                features=features,
                lat=ensemble.lat,
                lon=ensemble.lon,
                method_key=method,
                rung=1 if method == METHOD_CURRENT_ASSISTED else 3,
                radii=radii_for(calibration, method, features.region, features.cycle_class),
                now=now,
                validation_source=ensemble.basis,
                ensemble={"members": ensemble.members, "p90_spread_km": p90},
            )
        payload["issues"] = payload["issues"] + [
            f"current-assisted prediction unavailable ({provider.describe()})"
        ]
    else:
        payload["issues"] = payload["issues"] + [
            f"current-assisted / physics rungs skipped — {provider.describe()}"
        ]

    # ---- rung 4: validated history / prior baseline --------------------------
    if mode != STEP_OFF and not features.transitions:
        # Stage-1 was requested but rung 4 never fires for this float: record why, so a
        # Stage-1-mode payload that is served by the Stage-0 ladder is still auditable.
        payload["stage1_fallback_reason"] = (
            "no eligible trajectory transition in the cached history — Stage-0 ladder used"
        )
    if features.transitions:
        last = features.last_transition
        stage1 = _stage1_step(
            features,
            mode=mode,
            calibration_stage1=calibration_stage1,
            prior_source=(prior or grid or None),
            weight=weight,
            lat0=lat0,
            lon0=lon0,
            payload=payload,
            now=now,
        )
        if stage1 is not None:
            return stage1
        if prior_source := (prior or grid or None):
            step = (
                (1.0 - weight) * last.dlat_km + weight * prior_source.dlat_km,
                (1.0 - weight) * last.dlon_km + weight * prior_source.dlon_km,
            )
            lat, lon = destination(lat0, lon0, step[0], step[1])
            payload["issues"] = payload["issues"] + [
                f"blend weight on prior {weight:g} (LOFO-calibrated)",
                f"prior basis: {prior_source.basis} (n={prior_source.neighbours})",
            ]
            return _finish(
                payload,
                features=features,
                lat=lat,
                lon=lon,
                method_key=METHOD_HISTORY_PRIOR,
                rung=4,
                radii=radii_for(calibration, METHOD_HISTORY_PRIOR, features.region, features.cycle_class),
                now=now,
                validation_source=None,
            )
        lat, lon = destination(lat0, lon0, last.dlat_km, last.dlon_km)
        payload["issues"] = payload["issues"] + ["no regional/seasonal prior available for this position"]
        return _finish(
            payload,
            features=features,
            lat=lat,
            lon=lon,
            method_key=METHOD_TRAJECTORY,
            rung=4,
            radii=radii_for(calibration, METHOD_TRAJECTORY, features.region, features.cycle_class),
            now=now,
            validation_source=None,
        )

    if prior_source := (prior or grid or None):
        lat, lon = destination(lat0, lon0, prior_source.dlat_km, prior_source.dlon_km)
        payload["issues"] = payload["issues"] + [
            f"no usable trajectory transition; prior basis: {prior_source.basis}"
        ]
        return _finish(
            payload,
            features=features,
            lat=lat,
            lon=lon,
            method_key=METHOD_REGIONAL_PRIOR,
            rung=4,
            radii=radii_for(calibration, METHOD_REGIONAL_PRIOR, features.region, features.cycle_class),
            now=now,
            validation_source=None,
        )

    # ---- rung 4 (last resort): persistence ----------------------------------
    payload["issues"] = payload["issues"] + ["no trajectory history or prior: persistence used"]
    return _finish(
        payload,
        features=features,
        lat=lat0,
        lon=lon0,
        method_key=METHOD_PERSISTENCE,
        rung=4,
        radii=radii_for(calibration, METHOD_PERSISTENCE, features.region, features.cycle_class),
        now=now,
        validation_source=None,
    )


def predict_fleet(
    features_by_wmo: dict[int, FloatFeatures],
    *,
    calibration: Calibration | None = None,
    provider: CurrentProvider | None = None,
    now: datetime | None = None,
    cycle_step_mode: str | None = None,
    calibration_stage1: Calibration | None = None,
) -> dict[int, dict[str, Any]]:
    """Predictions for the whole live cache with one shared, leakage-safe pool."""
    now = now or datetime.now(UTC)
    calibration = calibration or calibration_module.load_calibration()
    provider = provider or provider_from_env()
    mode = resolve_cycle_step_mode(cycle_step_mode)
    if mode != STEP_OFF and calibration_stage1 is None:
        calibration_stage1 = calibration_module.load_stage1_calibration()
    pool = fleet_transitions(features_by_wmo)
    grid_cells = calibration.prior_grid if isinstance(calibration.prior_grid, dict) else None
    out: dict[int, dict[str, Any]] = {}
    for wmo, features in features_by_wmo.items():
        try:
            out[wmo] = predict_float(
                features,
                pool=pool,
                calibration=calibration,
                provider=provider,
                now=now,
                grid_cells=grid_cells,
                cycle_step_mode=mode,
                calibration_stage1=calibration_stage1,
            )
        except Exception as exc:  # never let one float break the fleet payload
            payload = _base_payload(features, now)
            out[wmo] = _refuse(
                payload,
                STATUS_INSUFFICIENT_DATA,
                UNAVAILABLE_MESSAGE,
                f"prediction error: {type(exc).__name__}",
            )
    return out


def calibration_summary(calibration: Calibration) -> dict[str, Any]:
    """Non-secret provenance for the UI/API (never contains credentials)."""
    methods: dict[str, Any] = {}
    for key, method in (calibration.methods or {}).items():
        if not isinstance(method, dict):
            continue
        default = method.get("default") or {}
        methods[key] = {
            "label": METHOD_LABELS.get(key, key),
            "r50_km": default.get("r50_km"),
            "r90_km": default.get("r90_km"),
            "samples": default.get("n"),
            "metrics": default.get("metrics"),
        }
    return {
        "available": calibration.available,
        "version": calibration.version,
        "generated_at": calibration.generated_at,
        "path": calibration.path,
        "load_error": calibration.load_error,
        "blend_weight_on_prior": calibration.blend_weight_on_prior,
        "corpus": calibration.corpus,
        "prior_grid_cells": len(calibration.prior_grid or {}),
        "methods": methods,
    }


__all__ = [
    "CYCLE_STEP_MODES",
    "STEP_MEDIAN",
    "STEP_OFF",
    "cycle_scale_step",
    "resolve_cycle_step_mode",
    "STATUS_OK",
    "STATUS_INSUFFICIENT_DATA",
    "STATUS_INSUFFICIENT_VALIDATION",
    "STATUS_SOURCE_UNAVAILABLE",
    "UNAVAILABLE_MESSAGE",
    "UNVALIDATED_MESSAGE",
    "predict_float",
    "predict_fleet",
    "calibration_summary",
]
