# Next Profile Location prediction — implementation and verification report

Companion to the research deliverable (`/home/user/profile-location-prediction/RESEARCH.md`).
This report states what is now implemented in `decoder-ui`, how it was verified
against the live system, and what is honestly not claimed.

Scope note: nothing outside `incois-arpy-decoder/decoder-ui` was modified;
`src/argo_decoder/` is untouched; no private operational data was introduced.

---

## 1. Behaviour delivered

### 1.1 Observed cycle interval (replaces the fixed 10-day assumption)

* `service/profile_cycle.py` (new, pure) measures each float's own cycle from the
  accepted consecutive `JULD` spacings of the same published `_prof.nc` history
  used for monitoring: 0.5–60 d window, median, ≥ 3 usable spacings, clamped
  1–45 d, fallback ladder `profile history` → `trajectory history` → documented
  10-day default.
* Float Status now uses that interval for **Expected Next Profile** (`t + i`),
  **Approx. Profiles Missed** (`floor(days / i)`) and the **first status
  boundary** (`days <= i` = ACTIVE / RECENT PROFILE). Status *wordings* and the
  60-day boundary are unchanged; for a float whose measured interval is exactly
  10 days the result is byte-identical to the previous rule.
* The interval and its provenance are visible: drawer row
  `Observed cycle interval` (`9.79 d (profile history, 24 intervals)`) and the
  estimate tooltip ("…observed 9.8-day profile cycle (median of 24 published
  profile dates)"), with the documented fallback wording when history is thin.

### 1.2 Experimental next-profile prediction

* `service/prediction/` (new package): `geometry`, `features` (leakage-safe
  feature capture with a no-future guard), `prior` (regional/seasonal
  neighbourhood + calibrated grid), `currents` (provider hook; default is the
  explicit "no provider" state, CMEMS adapter is credential-gated and never
  fabricates velocities), `advect` (deterministic 100-member Lagrangian
  ensemble), `calibrate` (artefact loading, radii lookup chain), `predict`
  (facade + fallback ladder + refusal statuses), `validate` (offline
  calibrator), plus tests.
* Fallback ladder reported on every payload: rung 1 Current-Assisted →
  rung 2 ML Residual Correction (**reserved, never emitted**) → rung 3
  Physics / Lagrangian → rung 4 validated history/prior baseline
  (`history_prior` blend → `trajectory_extrapolation` → `regional_prior` →
  `persistence`) → rung 5 refusal.
* Refusals are explicit: no verified QC 1/2 position ⇒
  "Prediction unavailable — insufficient data"; no calibrated radius for the
  stratum actually used ⇒ "Prediction unavailable — insufficient validation
  data". The current-dependent rungs are skipped and *reported* when no provider
  is configured; the physics integration point exists but ships no untested path.
* Uncertainty comes only from the artefact (region × cycle class, conditioned on
  the method/rung actually used) together with the sample count and basis string.
* API: every Float Status row carries a `prediction` object; the payload carries
  a fleet-wide summary (`available/unavailable/methods/calibration/currents/forward_test`);
  `GET /api/floats/{wmo}/next-location` serves one float and returns 404 for an
  unmonitored WMO. A prediction failure degrades to `prediction.error` and never
  affects the monitoring fields.
* **Forward test (new this pass):** every available prediction is recorded once
  (keyed by float + issuing fix) and later scored against the float's next
  *strictly newer* verified fix — great-circle error, target-time error and
  whether the error fell inside the r50 / r90 circle that was quoted. Refusals are
  not logged; the audit is append-only JSONL, rotated at 4 MB, and contains no
  profile/measurement data (it is not a profile store). It is reported as
  `prediction.forward_test` on the payload, per row when a float has scored
  predictions, and in the drawer as `Forward test (scored)`. A failure is reported
  and can never affect the monitoring fields.
* UI: `NEXT PROFILE LOCATION (PREDICTED)` drawer section (predicted lat/lon,
  target time, horizon, r50/r90 with the validated 50 %/90 % note, method, rung,
  validation sample count, calibration basis, status, interval used, region/class,
  prior basis, currents, issues) and an **opt-in, OFF-by-default** map layer
  (hollow diamond, dashed connector, dashed 90 % / solid 50 % rings). Real
  markers, trajectories, cycle dots, EEZ layers, filters, sorting, pagination,
  navigation and every existing control are unchanged. Banned wording is absent
  ("Last Communication", "No Transmission", "Dead").

### 1.3 Files

| Path | Role |
|---|---|
| `service/profile_cycle.py` | observed-interval rules (new) |
| `service/prediction/*` (10 modules) | prediction pipeline, calibration, forward test, CLI (new) |
| `service/fleet_status.py` | interval-based monitor + per-row prediction + payload summary |
| `service/api.py` | `GET /api/floats/{wmo}/next-location` |
| `frontend/src/{types,utils/fleetStatus.ts}` | prediction types + display helpers |
| `frontend/src/components/fleetMapModel.ts` | layer order, prediction palette, ring geometry, descriptors |
| `frontend/src/components/esriFleetView.ts` | prediction GraphicsLayer + draw block + hit-test |
| `frontend/src/components/FleetOceanMap.tsx` | `predictions` prop, opt-in toggle |
| `frontend/src/components/FloatStatusPage.tsx` | drawer block, map predictions, section test-ids |
| `data/fleet_status/prediction_calibration.json` | calibration artefact (aggregate statistics only) |
| `PREDICTION.md`, `FLEET_STATUS.md` | product documentation (new / updated) |
| `tests/test_profile_cycle.py`, `tests/test_prediction.py`, `tests/test_forward_test.py`, `tests/test_profile_recency.py`, `tests/test_fleet_status.py` | service verification |
| `frontend/src/**/*.test.ts(x)`, `frontend/e2e/fleetStatus.e2e.mjs` | frontend + browser verification |
| `data/fleet_status/prediction_forward_log.jsonl` | forward-test audit (runtime; created on first serve) |

---

## 2. Verification matrix

| # | Check | Command | Result |
|---|---|---|---|
| 1 | Service/interval/prediction/audit tests | `cd decoder-ui && env -u FLEET_SYNC_ENABLED PYTHONPATH=src:service /home/user/.venv/bin/python -m pytest tests -q` | **298 passed** (incl. `test_profile_cycle` 8, `test_prediction` 25, `test_forward_test` 14, `test_fleet_status`, `test_profile_recency`) |
| 2 | Frontend unit/SSR tests | `cd frontend && npx vitest run` | **164 passed / 15 files** |
| 3 | Types | `cd frontend && npx tsc --noEmit -p tsconfig.json` | **clean** |
| 4 | Live browser audit — Float Status + prediction + audit | `FLEET_E2E_BASE=http://127.0.0.1:3000 npm run test:fleet` | **988 / 988 checks, 30 floats field-checked**, exit 0 |
| 5 | Live browser audit — fleet map | `MAP_E2E_BASE=http://127.0.0.1:3000 npm run test:e2e` | **15 / 15 checks, page errors: none** |
| 6 | Forward test, live | `curl /api/fleet-status` twice + file inspection | 30 issued / 0 scored / 30 pending on first serve; repeated polls do not inflate it |
| 7 | Forward test, scoring path | `python /home/user/prediction-validation/demo_forward_test.py` (synthetic cycle advance, offline) | prediction issued → next cycle scored: error 51.15 km, outside r50 (47.3 km), inside r90 (206.7 km), time error 0.0 d |
| 8 | Calibration artefact regeneration | `PYTHONPATH=service /home/user/.venv/bin/python -m prediction.validate --corpus /tmp/argotraj --out data/fleet_status/prediction_calibration.json --report /home/user/prediction-validation/prediction_validation.csv` | regenerated 2026-09-21T12:38:49Z, 29 floats / 5,257 transitions / 269 grid cells |
| 9 | Live API contract | `curl /api/fleet-status`, `/api/floats/<wmo>/next-location`, `/api/floats/9999999/next-location` | 30/30 rows with predictions, endpoint agrees with the row, unmonitored WMO → 404 |

### 2b. Regression sweep — the rest of the workstation (this pass)

The interval and prediction work touches Float Status, the map view and the
service payload, so every other browser suite was re-run against the same live
backend to show nothing else moved:

| Suite | Command (dev server `:3000`, API `:8000`) | Result |
|---|---|---|
| EEZ layer | `node e2e/eezLayer.e2e.mjs` | **27 / 27 passed** (alert panel, toggle, fades, no duplicate rows) |
| Decode-all gating | `node e2e/decodeAllGating.e2e.mjs` | **16 / 16 passed** (one batch per click, no duplicates, backend 409 guard) |
| Ingestion arrivals | `MAP_E2E_BASE=…:3000 INGEST_ZONE=<runtime>/incoming node e2e/ingestionArrivals.e2e.mjs` | **17 / 17 passed** (arrival detected, honest normalised fields, NEW DATA badge, no auto-decode, mark-seen persisted) |
| Fleet map | `MAP_E2E_BASE=…:3000 npm run test:e2e` | **15 / 15 passed**, page errors: none |
| Float Status + prediction | `FLEET_E2E_BASE=…:3000 npm run test:fleet` | **988 / 988 passed**, 30 floats field-checked |
| Investigation detail | `node e2e/investigationDetail.e2e.mjs` | **not runnable on a fresh runtime** — the suite pins run ids (`run-6902892-011aef`, `run-7902408-2a2e88`, …) and a batch id (`batch-1789628039-4b81`) from the earlier session; run ids embed a random `uuid4().hex[:6]` and the 6902892 metadata was removed by the approved cleanup, so they cannot be recreated. Its API path was verified instead: `GET /api/runs/run-2902223-fd8bb4/investigation` returns the full investigation record and an unknown run returns **404** |

Two environment notes discovered while doing this (neither is a product defect and
neither was introduced by this work):

* Legacy harness paths: `e2e/ingestionArrivals.e2e.mjs` hardcodes
  `/home/user/incois-arpy-decoder/...` (the repo location in the original
  environment) and `MAP_E2E_BASE` defaults to the *backend* port, expecting the
  built SPA to be served there. A compatibility symlink
  `/home/user/incois-arpy-decoder → /home/user/ARPY-decoder-Ui/incois-arpy-decoder`
  plus `MAP_E2E_BASE=…:3000` makes the suite run unmodified. The symlink is an
  environment shim outside the repository, not part of the deliverable.
* Core test suite (`incois-arpy-decoder/tests`, outside the edit scope):
  `PYTHONPATH=src pytest tests -q` gives **85 failed / 1042 passed / 83 skipped /
  18 errors**, versus the previously recorded baseline **80 failed / 1047 passed /
  83 skipped / 18 errors**. The five extra failures are all registry-content
  assertions in `tests/unit/test_metadata_csv.py` and
  `tests/unit/test_arvor_i_registry_routing.py`, caused by the **earlier approved
  Coriolis cleanup**, which removed rows `6902892` / `6903014` from
  `config/registry.csv` and `registry_apf9.csv` (documented in
  `float-cleanup/REPORT.md` items 3–4) while updating only the in-scope
  `decoder-ui` tests. Nothing in this task touches those files
  (`git status` shows changes outside `decoder-ui` only in the cleanup's
  `config/` and deleted `Coriolis-…/` paths). Fixing it means editing either
  `config/registry.csv` or the core tests — both outside the authorised scope, so
  it is reported, not changed.

Logs and artefacts: `fleet-e2e.log`, `e2e-shots/` (Float Status, drawers for six
floats, the prediction drawer block, the enabled prediction layer), `map-shots/`
(browser audit), `verification.json` (per-check results from the browser run).

The browser run recomputes every formula from the API payload instead of copying
UI strings: interval-based expected-next date, `floor(days / interval)`,
interval tooltip wording, status boundary, prediction position/method/rung/
samples/status/radius/horizon/calibration basis, opt-in layer counts
(30 diamonds, 60 rings, 30 connectors for 30 floats) and the click-selects-the-
same-float behaviour. A drifted string or a fabricated value fails the run.

---

## 3. Live evidence (2026-09-21, 13:01 UTC)

Monitoring snapshot (unchanged semantics, interval-aware numbers):

| total | recent | overdue | 60+ days | NO DATA | approx. missed | published cycles |
|---|---|---|---|---|---|---|
| 30 | 4 | 2 | 24 | 0 | 13,845 | 5,628 |

Prediction distribution: **30 available / 0 unavailable**, all on the validated
baseline rung (`trajectory_extrapolation`, rung 4); no current provider is
configured, so rungs 1 and 3 are skipped and the reason is reported in `issues`
and in the fleet-wide `currents` string. Examples of the radii actually served
(region × cycle class strata of the artefact):

| WMO | method | r50 | r90 | calibration samples | basis |
|---|---|---|---|---|---|
| 2902086 | Trajectory Extrapolation | 16.8 km | 232.2 km | 900 | Bay of Bengal · short cycle |
| 1902844 | Trajectory Extrapolation | 47.3 km | 206.7 km | 313 | Equatorial Indian · decadal cycle |
| 2902223 | Trajectory Extrapolation | 74.0 km | 226.3 km | 1,605 | South Indian Ocean · decadal cycle |

The wide 90 % circles are the measured, honest error scale for a fast-drifting
float predicted one cycle ahead without a current field — they are quoted with
their sample size rather than hidden.

Forward-test audit on the same live payload
(`/home/user/profile-recency-update/runtime/fleet_status/prediction_forward_log.jsonl`):

| issued | scored | pending | interpretation |
|---|---|---|---|
| 30 | 0 | 30 | every float's current prediction is on record; none can be scored yet because no float has published its next cycle since issue |

Because the real fleet advances at most once per cycle, the *scoring* half of the
audit was exercised offline on the same service code path
(`demo_forward_test.py`, synthetic runtime, no network): a prediction issued from
cycle 2 was scored when cycle 3 appeared — error **51.15 km**, outside the quoted
r50 (47.3 km) and inside r90 (206.7 km), target-time error 0.0 d, and the drawer's
`Forward test (scored)` line then reports `1 scored · median 51.15 km · 0% within
r50 / 100% within r90 · time error 0.0 d`. Four extra polls of the unchanged cache
added **zero** records, i.e. the audit cannot be inflated by the UI.

---

## 4. Research provenance

* Hindcast on 29 public INCOIS trajectory files (5,257 transitions): persistence
  median 28.1 km / p90 82.7 km; last-displacement 21.5 / 111.4; regional-seasonal
  prior 29.6 / 68.7; **0.8 × last displacement + 0.2 × prior (LOFO-selected)
  20.1 km median, 98.1 km p90**; calibration transfer within ~2 points of nominal.
* The shipped default blend weight (`0.2`), delivery-lag guard (2 days), prior
  grid (2° × month, ≥ 5 neighbours) and the refusal rules all come from that
  measurement, not from preference. Full tables C1–C10 and the rejected
  alternatives are in `RESEARCH.md`.

---

## 5. Explicitly not done / limitations

1. **No ML.** Rung 2 is a reserved label only. The research verdict requires an
   out-of-sample improvement on broad Argo data before it may ship.
2. **No ocean-current provider is configured.** The CMEMS/GLORYS adapter is a
   credential-gated placeholder that reports itself unavailable; no untested
   data path and no fabricated velocities were shipped. Rungs 1 and 3 therefore
   cannot run in this deployment and say so.
3. **No production bundle rebuild.** The resource limit recorded in the earlier
   repository verification still prevents the prod build in this sandbox;
   verification used the running dev server, the live API and the real renderers.
   No shipped-bundle claim is made.
4. **Uncertainty is large where the ocean is.** 90 % radii above 100 km are a
   warning, not precision; the UI always shows the sample count behind them.
5. **Approx. Profiles Missed is an estimate, not an inventory.** With the observed
   interval as denominator, fast-cycling floats produce large estimates (e.g.
   2902091, a ~1-day cycler, shows ~4,938 days' worth of cycles); the exact
   file-gap inventory remains a separate, exact measure, as documented.
6. **Cached rows can lag the parser.** Until a re-sync refreshes the trajectory
   block, some rows fall back to `persistence` and record the reason in
   `issues`; that is visible, not silent.
7. **Two suites and the core test tree carry environment debt** (outside the
   authorised scope, reported in §2b): `investigationDetail.e2e.mjs` is pinned to
   the earlier session's run/batch ids, the ingestion harness assumes the original
   repository path (a compatibility symlink is documented), and five core tests
   still assert the registry rows that the approved Coriolis cleanup removed. None
   of these is caused by, or fixable inside, this task's scope.
8. **The production forward test is young.** The audit is implemented, wired and
   scoring correctly (proven offline), but on this deployment it currently shows
   30 predictions *pending* and no containment statistics: those can only appear
   after real floats publish their next cycle. Nothing is claimed about
   production skill before that happens, and the audit file is a deployment-local
   artefact — not committed to the repository and not a substitute for the
   corpus calibration.

---

## 5b. Where each requested part is answered

| Part (research document letter) | Deliverable |
|---|---|
| A. Recommended overall approach | `RESEARCH.md` §A → implemented as the rung-4 blend (`calibrate.DEFAULT_BLEND_WEIGHT_ON_PRIOR = 0.2`) |
| B. Alternatives considered | `RESEARCH.md` §B (rejected: pure persistence, pure physics, ML-first) |
| C. Required data sources | `RESEARCH.md` §C → only the already-cached `_prof.nc` / `_Rtraj.nc`; `currents.py` provider hook |
| D. Features | `RESEARCH.md` §D → `prediction/features.py` (leakage-guarded) |
| E. Training / validation strategy | `RESEARCH.md` §E → `prediction/validate.py` (leave-one-float-out, per-float chronological) |
| F. Limitations | `RESEARCH.md` §F, §5 of this report (large 90 % radii, corpus limits) |
| G. Uncertainty method | `RESEARCH.md` §G → `calibrate.radii_for` lookup chain + `validation_samples` / `validation_source` in the UI |
| H. Architecture | `RESEARCH.md` §H → now implemented (service package, row `prediction`, endpoint, drawer, opt-in layer) |
| I. Validation against historical floats | `RESEARCH.md` §I + Appendix C (Tables C1–C10), reproducible via `backtest_baselines.py` / `backtest_robustness.py` |
| J. Verdict | `RESEARCH.md` §J → staged hybrid; Stage 0 shipped, ML rung reserved |
| K. Sources and references | `RESEARCH.md` §K (CMEMS/GLORYS, INCOIS OSF, Argo traj docs, literature) |
| L. Shipped implementation + verification | This report §1–§6, `PREDICTION.md`, and the test/E2E evidence above |

---

## STAGE-0 — prediction hardening + real-data audit (2026-09-21)

Reported in `STAGE0_AUDIT_REPORT.md` (sections A–G). Headlines:

* **Root cause of "needlessly falling back", found with real data:** the cached
  trajectory block kept 8 one-per-cycle fixes per float, so the fleet transition
  pool held 200 transitions and the documented prior was impossible for *every*
  float. The same code over the full public history (5,294 transitions, 4–361
  usable fixes per float) resolves **9** floats with the prior. Fix (no rule,
  radius or ladder change): `PREDICTION_FIX_HISTORY` 8 → 400 and `PARSER_VERSION`
  3 → 4, then the existing sync re-parsed the cache.
* **Live result:** 9 `history_prior` / 21 `trajectory_extrapolation` / 0
  persistence / 0 unavailable; `prediction.diagnostics` published fleet-wide;
  monitoring figures unchanged.
* **Two defects found and fixed while auditing:**
  1. the forward test scored *sub-cycle* fixes (burst transmissions) — 2,077.7 km
     and 2,196.2 km "errors" 0.86 d / 1.87 d after issuance; scoring now demands a
     later *cycle* and ≥ half the observed interval (pre-fix log archived, replay
     shows the correct ~10 d later cycles);
  2. uncertainty rings were drawn with an equirectangular approximation (2.79 km
     error on a 226.3 km ring); rings are now geodesic — 0.0000 km worst vertex
     error over 60 audited rings.
* **Report-only finding:** rung 4 treats the last observed hop as one cycle, which
  is not cycle-scale for three floats (0.50–0.74 d hops; one 10.03 d span on a
  1.0 d cycle). The algorithm is frozen at this stage, so each row now carries an
  explicit input advisory instead.
* **Verification:** backend 301, vitest 166, tsc clean, fleet browser 1083/1083,
  new `e2e/predictionMap.e2e.mjs` 162/162 (map audit), fleetMap 15/15, EEZ 27/27,
  decodeAllGating 16/16, ingestionArrivals 17/17, science audit 16/16, forward
  audit 11/11. Re-run end to end after a full environment rebuild (fresh venv +
  npm install + Playwright) with identical results; the Stage-0 report also maps
  the requested steps 1–10 to their evidence.
* **Anchor finding (reported, not changed):** the prediction is anchored on the last
  *trajectory* fix; for 5 of 30 floats that anchor is >90 d older than the position
  the page displays (2901350: 2017-12-08 fix vs a 2020-04-26 profile, 870 d and
  4,545.8 km apart), while the method's own applied step stays sane (61.6 km; fleet
  median 35.8 km, max 191.3 km). Tracked by science-audit check J and captured in
  `e2e-shots/anchor-2901350-{evidence.json,drawer.png,map.png}` (drawn connector measured
  at 4,604.5 km); Stage-1 candidates are anchoring on the newest cached position or
  labelling the case.
* **Fixture note:** `decoder-ui/data/fleet_status/cache.json` is required in its
  current form — restoring the HEAD version fails
  `tests/test_fleet_status_audit.py` (it asserts the current 30-float fleet).

---

## 6. Reproduction

The sandbox toolchain (`.venv`, `frontend/node_modules`, Playwright browsers) is
not part of the workspace snapshot, so after a restart it must be rebuilt once:

```bash
python3 -m venv /home/user/.venv && /home/user/.venv/bin/python -m pip install \
  -r /home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/service/requirements.txt pytest httpx
cd /home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/frontend
npm install && npx playwright install --with-deps chromium
```

then:

```bash
# 1. service + frontend tests, types
cd /home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui
env -u FLEET_SYNC_ENABLED PYTHONPATH=src:service /home/user/.venv/bin/python -m pytest tests -q
cd frontend && npx vitest run && npx tsc --noEmit -p tsconfig.json

# 2. live browser audits (backend on :8000, dev server on :3000)
FLEET_E2E_BASE=http://127.0.0.1:3000 FLEET_E2E_SHOTS=/home/user/prediction-validation/e2e-shots npm run test:fleet
MAP_E2E_BASE=http://127.0.0.1:3000 MAP_E2E_SHOTS=/home/user/prediction-validation/map-shots npm run test:e2e
PREDICTION_MAP_BASE=http://127.0.0.1:3000 node e2e/predictionMap.e2e.mjs   # map audit (point + ring radii)

# 2b. STAGE-0 data audits (read-only)
PYTHONPATH=src:service /home/user/.venv/bin/python /home/user/prediction-validation/audit/stage0_science_audit.py
PYTHONPATH=service     /home/user/.venv/bin/python /home/user/prediction-validation/audit/stage0_forward_audit.py

# 3. recalibrate (public corpus, network required once)
PYTHONPATH=service /home/user/.venv/bin/python -m prediction.validate \
  --corpus /tmp/argotraj --out data/fleet_status/prediction_calibration.json \
  --report /home/user/prediction-validation/prediction_validation.csv
```
