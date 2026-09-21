import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { FleetPrediction, FleetStatusRow } from "../types";
import { PredictionDetail } from "./FloatStatusPage";

/** Presentation contract for the experimental prediction block.
 *  Fixture values come from the payload shape the backend actually serves
 *  (see decoder-ui/PREDICTION.md); no network is involved. */
const PREDICTION: FleetPrediction = {
  wmo: 2902223,
  available: true,
  status: "ok",
  status_message: null,
  predicted_lat: -45.71,
  predicted_lon: 7.97,
  prediction_horizon_days: 10.0,
  target_time_iso: "2026-09-11T20:29:34Z",
  r50_km: 72.5,
  r90_km: 231.2,
  method: "trajectory_extrapolation",
  method_label: "Trajectory Extrapolation",
  fallback_rung: 4,
  validation_samples: 5187,
  validation_source: "Trajectory Extrapolation · South Indian Ocean · decadal cycle",
  ensemble_members: null,
  ensemble_spread_km: null,
  issued_from_iso: "2026-09-01T23:28:26Z",
  issued_from_position: [-45.518, 7.1129],
  expected_interval_days: 10.0,
  interval_source: "profile history",
  interval_samples: 300,
  region: "South Indian Ocean",
  cycle_class: "decadal",
  trajectory_transitions: 5,
  prior_neighbours: 0,
  prior_basis: null,
  currents: "no ocean-current provider configured for this deployment",
  issues: ["current-assisted / physics rungs skipped — no provider configured"],
  generated_at: "2026-09-21T12:00:00Z",
  label: "Experimental prediction — not a communication signal",
};

function row(prediction: FleetPrediction | null): FleetStatusRow {
  return {
    wmo: prediction?.wmo ?? 2902223,
    internal_id: null, ptt: null, imei: null, float_type: "APEX", transmission_type: "ARGOS",
    in_incois_dac: true, prof_num: 353, profile_count: 352, lat: -45.72, lon: 7.97,
    pos_source: "traj", pos_qc: "1", last_profile_iso: "2026-09-01T23:30:00Z",
    last_profile_juld: 27990.0, last_profile_index: 0, last_profile_cycle: 353,
    last_profile_file: "2902223_prof.nc", last_profile_field: "JULD",
    profile_date_error: null, profile_checked_at: null, expected_next_profile_iso: "2026-09-11T23:30:00Z",
    expected_interval_days: 10, expected_interval_source: "profile history",
    expected_interval_samples: 300, interval_note: "note", days_since_last_profile: 19.5,
    approx_profiles_missed: 1, data_status: "PROFILE OVERDUE", traj_max_cycle: 353,
    latest_profile: null, traj_last_fix: null, rtraj_mdtm: null, error: null, updated_at: null,
    prediction,
  };
}

describe("NEXT PROFILE LOCATION (PREDICTED) block", () => {
  it("shows every required field and the experimental label", () => {
    const html = renderToStaticMarkup(<PredictionDetail row={row(PREDICTION)} />);
    expect(html).toContain("Experimental prediction — not a communication signal");
    expect(html).toContain("Predicted Latitude");
    expect(html).toContain("Predicted Longitude");
    expect(html).toContain("Expected Next Profile");
    expect(html).toContain("Prediction Horizon");
    expect(html).toContain("Fallback rung");
    expect(html).toContain("Trajectory history available");
    expect(html).toContain("Trajectory transitions");
    expect(html).toContain("Trajectory Extrapolation");
    expect(html).toContain("Validation Sample Count");
    expect(html).toContain("5187");
    expect(html).toContain("Prediction Status");
    expect(html).toContain("AVAILABLE");
    expect(html).toContain("+10.00 d");
    expect(html).not.toMatch(/Last Communication|Last Transmission|No Transmission|Dead/i);
  });

  it("explains R50/R90 as empirical radii with the exact required wording", () => {
    const html = renderToStaticMarkup(<PredictionDetail row={row(PREDICTION)} />);
    expect(html).toContain("R50: 72.5 km — 50% of historical validation prediction errors were within this distance.");
    expect(html).toContain("R90: 231.2 km — 90% of historical validation prediction errors were within this distance.");
    expect(html).toContain(
      "These are empirical uncertainty radii calculated from historical validation errors, " +
        "not a probability guarantee for this individual prediction.",
    );
    expect(html).toContain("Calibration basis");
    // never a probability claim about this individual prediction
    expect(html).not.toMatch(/90\s?%\s?(confidence|probability|probable|chance)/i);
    expect(html).not.toMatch(/confidence interval/i);
  });

  it("reports the trajectory history and transitions that back the prediction", () => {
    const html = renderToStaticMarkup(<PredictionDetail row={row(PREDICTION)} />);
    expect(html).toContain("yes — 5 cycle hop(s) in the cached trajectory");
    expect(html).not.toContain("Uncertainty / Radius");
    const none = renderToStaticMarkup(
      <PredictionDetail row={row({ ...PREDICTION, trajectory_transitions: 0, validation_samples: 0 })} />,
    );
    expect(none).toContain("no — no usable cycle hops in the cached trajectory");
  });

  it("states the fallback method and rung instead of implying physics", () => {
    const html = renderToStaticMarkup(<PredictionDetail row={row(PREDICTION)} />);
    expect(html).toContain("validated history/prior baseline");
    expect(html).toContain("no ocean-current provider configured");
    expect(html).toContain("current-assisted / physics rungs skipped");
  });

  it("never fabricates a position when the prediction is unavailable", () => {
    const html = renderToStaticMarkup(
      <PredictionDetail
        row={row({
          ...PREDICTION,
          available: false,
          status: "insufficient_data",
          status_message: "Prediction unavailable — insufficient data",
          predicted_lat: null,
          predicted_lon: null,
          r50_km: null,
          r90_km: null,
        })}
      />
    );
    expect(html).toContain("Prediction unavailable — insufficient data");
    expect(html).not.toContain("Predicted Latitude");
    expect(html).not.toContain("Uncertainty / Radius");
  });

  it("degrades honestly when a payload has no prediction at all", () => {
    const html = renderToStaticMarkup(<PredictionDetail row={row(null)} />);
    expect(html).toContain("Prediction unavailable — insufficient data");
    expect(html).toContain('data-testid="prediction-absent"');
  });
});

describe("forward-test row in the prediction block", () => {
  it("shows the scored audit with its scope, when one exists", () => {
    const html = renderToStaticMarkup(
      <PredictionDetail
        row={row({
          ...PREDICTION,
          forward_test: {
            n: 4,
            median_km: 27.5,
            p90_km: 91.2,
            within_r50_pct: 75,
            within_r90_pct: 100,
            median_time_error_days: 0.01,
          },
        })}
      />
    );
    expect(html).toContain("Forward test (scored)");
    expect(html).toContain("4 scored · median 27.5 km · p90 91.2 km · 75% within r50 / 100% within r90");
    expect(html).toContain("not the historical corpus");
  });

  it("stays silent when nothing has been scored yet", () => {
    expect(renderToStaticMarkup(<PredictionDetail row={row(PREDICTION)} />)).not.toContain(
      "Forward test (scored)"
    );
    expect(
      renderToStaticMarkup(<PredictionDetail row={row({ ...PREDICTION, forward_test: { n: 0 } })} />)
    ).not.toContain("Forward test (scored)");
  });
});

const STAGE1: FleetPrediction = {
  ...PREDICTION,
  method: "cycle_window",
  method_label: "Cycle-Scale Window (Stage-1)",
  predictor_stage: "stage1",
  predictor_stage_label: "Stage-1 cycle-scale step",
  step_basis: "cycle-scale window 9.80 d = 0.98 x the 10.00 d expected interval",
  step_span_days: 9.8,
  step_ratio: 0.98,
  step_cycles: 1,
  step_windows_used: 1,
  r50_km: 61.4,
  r90_km: 208.9,
  validation_samples: 5049,
  validation_source: "Cycle-Scale Window · South Indian Ocean · decadal cycle",
};

describe("predictor-stage labelling (Stage-0 vs Stage-1)", () => {
  it("names the Stage-0 baseline on a normal payload", () => {
    const html = renderToStaticMarkup(
      <PredictionDetail row={row({ ...PREDICTION, predictor_stage_label: "Stage-0 baseline (last-hop step)" })} />,
    );
    expect(html).toContain("Predictor stage");
    expect(html).toContain("Stage-0 baseline (last-hop step)");
    expect(html).not.toContain('data-testid="prediction-stage-note"');
    expect(html).not.toContain("Cycle-scale step basis");
  });

  it("names Stage-1, shows the step that was used, and keeps Stage-0 as the baseline", () => {
    const html = renderToStaticMarkup(<PredictionDetail row={row(STAGE1)} />);
    expect(html).toContain("Stage-1 cycle-scale step");
    expect(html).toContain("Cycle-scale step basis");
    expect(html).toContain("0.98 x the 10.00 d expected interval");
    expect(html).toContain('data-testid="prediction-stage-note"');
    expect(html).toContain("Stage-0 (last-hop step) remains the shipped baseline");
    expect(html).toContain("its R50/R90 are not reused here");
    // the R50/R90 wording contract is stage-independent
    expect(html).toContain("R50: 61.4 km — 50% of historical validation prediction errors were within this distance.");
    expect(html).toContain("R90: 208.9 km — 90% of historical validation prediction errors were within this distance.");
    expect(html).toContain(
      "These are empirical uncertainty radii calculated from historical validation errors, " +
        "not a probability guarantee for this individual prediction.",
    );
    expect(html).not.toMatch(/90\s?%\s?(confidence|probability|probable|chance)/i);
  });

  it("marks a gap-normalised Stage-1 step", () => {
    const html = renderToStaticMarkup(
      <PredictionDetail
        row={row({ ...STAGE1, step_basis: "cycle-scale window 20.0 d", step_cycles: 2, step_span_days: 20 })}
      />,
    );
    expect(html).toContain("gap normalised over 2 cycles");
  });

  it("falls back to the Stage-0 wording when a payload omits the stage", () => {
    const html = renderToStaticMarkup(<PredictionDetail row={row({ ...PREDICTION })} />);
    expect(html).toContain("Stage-0 baseline (last-hop step) — no stage reported by this payload");
  });
});
