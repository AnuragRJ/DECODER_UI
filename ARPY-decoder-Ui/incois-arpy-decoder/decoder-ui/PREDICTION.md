# Next Profile Location — experimental prediction

This document describes the shipped prediction subsystem: the ladder, the
refusal rules, the validated-uncertainty contract, the API surface and the
operator-facing UI. It is **not a communication claim and not a fleet-status
authority**; published-profile monitoring stays exactly as documented in
[FLEET_STATUS.md](FLEET_STATUS.md).

Every prediction is labelled in the UI and in the API:

> Experimental prediction — not a communication signal

The research basis (hindcast measurements, error scales, source options,
rejected alternatives) is `/home/user/profile-location-prediction/RESEARCH.md`;
this file is the product contract that implements its Stage-0 recommendation.

## Scope

* **Server-side only.** Predictions are computed in the existing service from
  the already-cached Ifremer `<WMO>_prof.nc` / `<WMO>_Rtraj.nc` data. The
  browser never requests current-model data or any third-party service.
* **No new data store.** Nothing is persisted except one aggregate statistics
  artefact (below). No per-cycle history table, no duplicate trajectory store.
* **No fabricated values.** A float with no verified upstream position, or no
  validated radius for the method actually used, receives an explicit
  unavailable status instead of a position.
* **No float-specific constants.** Every float is treated by the same code
  path; new floats appear automatically with whatever rung their data allows.

## Fallback ladder (evaluated in order, always reported)

| Rung | Condition | Method id | Label |
|---|---|---|---|
| 1 | ≥ 2 recent trajectory hops **and** an available current provider | `current_assisted` | Current-Assisted |
| 2 | — | `ml_residual` | ML Residual Correction (**not implemented in this build**) |
| 3 | any recent hop **and** an available current provider | `physics_lagrangian` | Physics / Lagrangian |
| 4 | validated history/prior baseline (what this deployment ships) | `history_prior`, `trajectory_extrapolation`, `regional_prior`, `persistence` | History + Prior · Trajectory Extrapolation · Regional / Seasonal Prior · Persistence |
| 5 | insufficient data | — | "Prediction unavailable — insufficient data" |

Rung 4 resolves in decreasing data availability:

1. `history_prior` — target float's last displacement blended with the regional
   neighbourhood prior at `blend_weight_on_prior` (default **0.2**, selected
   leave-one-float-out in the research corpus);
2. `trajectory_extrapolation` — the target float's own last displacement;
3. `regional_prior` — the 2° × calendar-month drift grid from the calibration
   artefact;
4. `persistence` — the last verified position (the honest last resort).

`fallback_rung` is included in every payload, so a physics-free prediction can
never be mistaken for a physics-based one. The rung actually used is also what
the uncertainty is conditioned on.

## Refusal rules (enforced in code, covered by tests)

* **No position, no prediction.** Without a verified QC 1/2 upstream position
  the row carries `status = "insufficient_data"` and null coordinates.
* **No validated radius, no prediction.** If the calibration artefact is missing,
  stale or lacks a stratum for (method, region, cycle class, rung), the row
  carries `status = "insufficient_validation"` and the message
  "Prediction unavailable — insufficient validation data". No default circle is
  invented.
* **No current provider, no physics rung.** With no provider configured the
  current-assisted and physics rungs are skipped and the fact is recorded in
  `issues` (and in the fleet-wide `prediction.currents` string); the validated
  baseline is used and labelled as such.
* **Cycle-scale input advisory.** When a float's most recent observed hop is far
  from its own observed cycle interval (< 0.5x or > 2x), the row keeps its method,
  rung and calibrated radius and adds an `issues` entry stating the ratio, because
  `trajectory_extrapolation` and the 0.8/0.2 blend apply that hop as one cycle.
  Three of the thirty monitored floats trigger this today (0.74 d and 0.50 d hops
  on 5 d/10 d cycles, one 10.03 d hop on a 1.0 d cycle); the *documented algorithm*
  is unchanged and the advisory never refuses a prediction.
* **No future information.** Every feature is timestamped at or before the last
  observed fix; the prior pool additionally excludes the target float and any
  transition starting at or after the prediction time (leave-one-float-out and
  a 2-day delivery lag).
* **No ML claim.** `ml_residual` exists as a reserved label only; it is never
  emitted. The research verdict is that ML must beat this baseline
  out-of-sample, on broad Argo data, before it may ship.

## Uncertainties

Radii come only from the calibration artefact, never from a UI constant:

* `r50_km` / `r90_km` are the empirical 50 % / 90 % containment radii measured
  on the historical corpus, stratified by region × cycle class and conditioned
  on the fallback rung;
* `validation_samples` and `validation_source` state the sample actually behind
  the circle (e.g. "Persistence · South Indian Ocean · decadal cycle"), because
  a radius without its sample size is not a defensible number;
* when no stratum matches, the lookup walks the documented fallback chain
  (region × class × rung → region × rung → region pooled → default) and the
  basis used is reported.

## Forward test (deployment-local)

The radii above are measured on a retrospective corpus. To keep them honest in
production, every prediction the service issues is audited (`service/prediction/forward_test.py`):

* each **available** prediction is recorded once, keyed by (WMO, the fix it was
  issued from) — re-serving the same cache cannot inflate the audit;
* when the float later publishes a **strictly newer verified fix**, the earlier
  prediction is scored against it: great-circle error, target-time error, and
  whether the error fell inside the r50 / r90 circle that was quoted at issue time;
* "later" means a *later cycle*, not merely a later timestamp. A float can publish
  several cycles within a day (telemetry bursts / numbering jumps — e.g. a float
  whose cached hops are 0.5 d long on a 5 d cycle), and scoring against such a fix
  measures a sub-cycle hop instead of the next profile. The scorer therefore
  requires a strictly greater cycle number when both cycles are known, and in all
  cases at least half the float's observed cycle interval after the issuing fix.
  Before this rule the audit scored 0.86 d and 1.87 d hops as ~2,078 km and
  ~2,196 km "errors"; the correct next cycles for those two floats sit ~10 d after
  issue (replay in `prediction-validation/audit/stage0_forward_audit.json`);
* refused predictions are not logged (there is no position to test);
* the audit is reported as `prediction.forward_test` on the payload and, once a
  float has scored predictions, per row as `prediction.forward_test`, which the
  drawer shows as `Forward test (scored)`.

Storage and honesty:

* append-only JSON Lines at `$ARGO_UI_DATA_DIR/fleet_status/prediction_forward_log.jsonl`
  (override with `PREDICTION_FORWARD_LOG_PATH`, disable with
  `PREDICTION_FORWARD_LOG=0`), rotated at 4 MB keeping the most recent events;
* it is **not a profile store**: a line holds only the prediction the service
  already made plus the later measured error — no measurements, no profile values,
  no extra download;
* `pending` counts issued predictions whose next cycle has not arrived yet, so an
  empty score table is visibly "accumulating", never "verified";
* any IO/parse failure is reported in `forward_test.error` and never affects the
  monitoring fields or the prediction block itself.

A deployment-wide summary is always available, so an operator can see how many
predictions have actually been checked and how they scored:

```json
"forward_test": {"enabled": true, "issued": 30, "scored": 0, "pending": 30,
                 "overall": null, "note": "deployment-local forward test ..."}
```

## Stage-1 cycle-scale step (implemented, opt-in, NOT the default)

Stage 1 moves the step model — the *size and span of the displacement* used at
rung 4 — from "the newest fix-to-fix hop" to "about one expected cycle", so a
telemetry burst is never read as a full cycle and a multi-cycle gap is never used
as one cycle. It does not change the ladder, the anchor, the target-time
calculation, the API contract or any Float Status semantics.

* module `service/prediction/cycle_step.py`; modes via `PREDICTION_CYCLE_STEP`:
  `off` (**shipped default**), `window`, `median`; `off` is bit-for-bit Stage 0;
* rule: scanning back from the newest fix, the freshest pair whose span lies in
  `[0.75, 1.25] × interval` gives the step; shorter spans are skipped (never
  rescaled — a burst is not a cycle); a span of up to 3 cycles is divided by
  `round(span / interval)` to a mean per-cycle displacement, and the normalisation
  is reported on the payload and in `issues`;
* calibration: Stage 1 has its **own** artefact
  `data/fleet_status/prediction_calibration_stage1.json` (methods
  `cycle_window`, `cycle_window_prior`, `cycle_median`, `cycle_median_prior`),
  generated from Stage-1's own errors by
  `prediction/validate_cycle.py`. Stage-0's R50/R90 are never reused; if the
  Stage-1 artefact is missing, Stage-1 refuses (`insufficient_validation`) rather
  than borrowing them;
* fallback: when no cycle-scale window exists the Stage-0 branch serves the case
  and `stage1_fallback_reason` records why (burst-only history, no span within
  3 cycles, or no eligible transition at all);
* **ship decision — not shipped.** On the 30-float corpus (5,071 paired cases,
  leave-one-float-out, target-matched labels) Stage 1 improved mean error by
  6.2 % and RMSE by 28.5 % but made the median 2.7 % and p90 0.7 % *worse*,
  against a pre-registered gate of ≥5 % / ≥5 % / ≥0 %; a scoped variant (the
  cycle-scale step only on sub-cycle and gap hops) removed every regression
  (+0.3 % median, +0.9 % p90, +8.9 % RMSE) and still missed the gate. So
  `DEFAULT_CYCLE_STEP = off` and Stage 0 remains the Predictor; the measurements,
  the per-case tail (`best improvement −7,681 km`, `worst regression +454 km`) and
  the recommended next step are in
  `/home/user/prediction-validation/STAGE1_REPORT.md`.

The active stage is always visible: every payload carries `predictor_stage`,
`predictor_stage_label` and (for Stage 1) `step_basis` / `step_span_days` /
`step_ratio` / `step_cycles`, the drawer shows a **Predictor stage** row plus a
note that Stage 0 remains the baseline, and the forward-test log records the stage
per issued prediction so Stage-0 and Stage-1 issues are never pooled. The audit
reports the **pending** mix as `issued_by_stage` (records written before the
Stage-1 pass have no stage field and count as Stage-0) and the **scored** mix as
`stages`; records are keyed by `(float, issuing fix)`, so switching
`PREDICTION_CYCLE_STEP` on an unchanged cache does **not** create new records — the
audit keeps the stage that was actually issued first for that fix and never
relabels history. A stage change therefore needs a fresh cycle (or a fresh log) to
appear in the forward test; the retrospective harness
(`prediction/validate_cycle.py` + `prediction-validation/STAGE1_REPORT.md`) is the
first-line evidence. `stage0_science_audit.py` verifies each served row against the
artefact of the stage that served it and asserts the Stage-0 artefact is intact.

## Calibration artefact

Generated from the public corpus by the research validator; it holds aggregate
statistics and file hashes only:

```bash
cd decoder-ui
PYTHONPATH=service /home/user/.venv/bin/python -m prediction.validate \
  --corpus /tmp/argotraj \
  --out data/fleet_status/prediction_calibration.json \
  --report /home/user/prediction-validation/prediction_validation.csv
```

* default path `data/fleet_status/prediction_calibration.json`, overridable with
  `PREDICTION_CALIBRATION_PATH`;
* contents: version, `generated_at`, corpus provenance (float count, transitions,
  per-file SHA-256, method `"leave-one-float-out, chronological per float"`),
  per-method metrics (median / p90 / RMSE / hit rates, radii), strata table and
  the 2° × month `prior_grid` (cell → mean drift + count);
* `configure_calibration.py`-style runtime override is *not* needed: the service
  reads the artefact on each payload build, so a re-run is picked up without a
  restart.

## API

* `GET /api/fleet-status` — every row carries a `prediction` object (same shape
  as below), plus a fleet-wide `prediction` summary:
  `{available, unavailable, methods{method:count}, calibration{available, version,
  generated_at, path}, currents, label, error}`, plus `diagnostics` — the Stage-0
  answer to "what did the ladder actually use?": `{floats, methods{}, rungs{},
  statuses{}, persistence_only, history_prior, trajectory_extrapolation,
  regional_prior, unavailable, insufficient_validation, insufficient_data,
  trajectory_history_available, trajectory_transitions{mean, median, min, max},
  note}`. `persistence_only` counts floats whose documented prior was unavailable
  (a *report*, never a rule change). A prediction failure degrades to
  `prediction.error` and never breaks the monitoring fields.
* `GET /api/floats/{wmo}/next-location` — one float:
  `{wmo, generated_at, label, prediction, prediction_summary}`;
  `404` with `WMO <wmo> is not in the monitored fleet` for unmonitored WMOs.

Row-level `prediction` fields: `available`, `status`, `status_message`,
`predicted_lat`, `predicted_lon`, `prediction_horizon_days`, `target_time_iso`,
`r50_km`, `r90_km`, `method`, `method_label`, `fallback_rung`,
`validation_samples`, `validation_source`, `ensemble_members`,
`ensemble_spread_km`, `issued_from_iso`, `issued_from_position`,
`expected_interval_days`, `interval_source`, `interval_samples`, `region`,
`cycle_class`, `trajectory_transitions`, `prior_neighbours`, `prior_basis`,
`currents`, `issues[]`, `generated_at`, `label`.

## UI

* **Detail drawer** — `NEXT PROFILE LOCATION (PREDICTED)` section, always
  present: predicted latitude/longitude, expected next profile (target time),
  horizon, uncertainty/radius (with the validated 50 %/90 % containment note),
  method, fallback rung, validation sample count, calibration basis, prediction
  status, cycle interval used, region/cycle class, prior basis, current-provider
  state, the **Predictor stage** that produced it (with its cycle-scale step
  basis when Stage 1 is active), and the issue list. When a value is unavailable the section states the
  refusal instead of showing placeholders.
* **Map** — optional, explicitly opt-in layer (`Predicted next profile (N)`
  checkbox, unchecked at mount). It adds a hollow diamond at the predicted
  position, a dashed connector from the real position, and dashed 90 % / solid
  50 % uncertainty rings, each drawn as a true geodesic circle of exactly the
  quoted r50/r90 distance from the predicted point. Real markers, trajectories,
  cycle dots, EEZ layers and
  all existing controls are untouched, and clicking a predicted position selects
  the same float. Nothing is drawn for a prediction without a validated radius.
* **Terminology** — History + Prior / Current-Assisted / Physics / Lagrangian /
  ML Residual Correction. The words "Last Communication", "No Transmission" and
  "Dead" remain banned, as everywhere else in Float Status.

### What the drawer says about the radii (exact wording)

The drawer never presents an empirical radius as a probability for the float in
front of you. The two rows and the note under them are asserted character-for-
character by `frontend/src/components/PredictionDetail.test.tsx`,
`frontend/e2e/fleetStatus.e2e.mjs` and `prediction-validation/capture_prediction_ui.mjs`:

* `R50: <value> km — 50% of historical validation prediction errors were within this distance.`
* `R90: <value> km — 90% of historical validation prediction errors were within this distance.`
* `These are empirical uncertainty radii calculated from historical validation errors, not a probability guarantee for this individual prediction.`

"90 % confidence", "90 % probability" and "confidence interval" are banned and
fails the suites that grep the rendered drawer. The same section also states the
`Trajectory history available` / `Trajectory transitions` counts, the calibration
basis and its sample size, so the reader can see which history produced the number.

## Verification

```bash
# service + interval + prediction unit/integration tests (network-free)
cd decoder-ui
env -u FLEET_SYNC_ENABLED PYTHONPATH=src:service /home/user/.venv/bin/python -m pytest tests -q

# frontend unit/SSR tests and types
cd frontend
npx vitest run
npx tsc --noEmit -p tsconfig.json

# live browser audit of table, drawer, prediction block, map layer and API
FLEET_E2E_BASE=http://127.0.0.1:3000 npm run test:fleet
```

`tests/test_prediction.py` pins the ladder, the leakage guards (future fixes,
own-float prior, delivery lag), every refusal path, the radii lookup chain, the
blend arithmetic, the horizon/interval coupling, the provider gate and the
fleet-status integration (including the degradation guard). `tests/test_profile_cycle.py`
pins the observed-interval rules that both Float Status and the prediction target
time share. `tests/test_forward_test.py` pins the audit: idempotent recording,
scoring only against a strictly newer fix, containment arithmetic, per-float and
per-method separation, bounded file size, corrupt-line tolerance, the disabled
state, and the guarantee that an audit failure cannot break the payload. The browser audit recomputes each formula independently from the API
payload, so a drifted string or a fabricated value fails the run.

## Current limitations (honest, measured)

* **No current provider in this deployment.** Rungs 1 and 3 are skipped, so the
  shipped method is the validated baseline; the research corpus measured a
  21.5 km median / 90.2 km p90 error for the blend and 28.1 / 82.7 km for
  persistence.
* **No ML in v1** (rung 2 reserved; research verdict requires out-of-sample
  improvement on broad Argo data first).
* **Uncertainty is large where the ocean is.** 90 % radii above 100 km are a
  warning, not a precision claim — the UI quotes the sample size so an operator
  can judge the circle.
* **Cached rows can predate the fix-history parser.** Until a re-sync refreshes
  the trajectory block, most floats fall back to persistence and say so in
  `issues` / the drawer; this is expected, not a silent failure.
* **The anchor is the last *trajectory* fix, not the displayed position.** The
  prediction is issued from the float's newest verified trajectory fix, while the
  page's real marker and coordinates come from the last published profile. For a
  float that stopped reporting trajectory fixes before its last profile these
  disagree: measured on this fleet, 5 of 30 floats are anchored on a fix more than
  90 days older than the displayed position (1902844, 2902224, 2904082, 7902408:
  110–137 d; **2901350: a 2017-12-08 anchor versus a 2020-04-26 profile, 870 d and
  4,545.8 km apart**). The method's own step stays sane in every case (the
  fleet's applied one-cycle hops: median 35.8 km, max 191.3 km; 2901350's is
  61.6 km) and the drawer's `Issued from` row states the anchor date, but the
  optional map layer links the anchor to the predicted point, so for 2901350 the
  dashed connector runs ~4,600 km and can be misread as motion. Anchoring on the
  newest cached position, or labelling/refusing this case in the UI, is a
  **Stage-1 candidate** — Stage 0 changes neither the anchor rule nor the map's
  link semantics.
* **Retrospective corpus + a young forward test.** The calibration corpus is
  published (possibly delayed-mode-revised) trajectory data. The forward test
  above is the mechanism that keeps radii honest in production, but it needs real
  time: on a fresh deployment the audit shows predictions *pending* and no
  containment statistics until floats actually advance a cycle.
