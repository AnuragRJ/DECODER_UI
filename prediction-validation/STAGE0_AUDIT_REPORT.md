# STAGE-0 — prediction hardening + real-data audit (report A–G)

Scope of this stage: make the **shipped** prediction use the historical trajectory
data the workstation already has, instead of needlessly falling back, and make the
UI explain the empirical uncertainty behind R50/R90 honestly. No new ML, no
current-assisted physics, no change to the prediction algorithm, the calibration
mathematics, the R50/R90 definitions, the fallback ladder, the API contract or the
communication/status terminology. `src/argo_decoder/` untouched.

Everything below is measured on the live deployment (30 monitored floats, cache
rebuilt from the public Ifremer `_Rtraj.nc`/`_prof.nc` the workstation already
downloads) and on saved evidence files.

Evidence:
`audit/stage0_audit.py` (ring vs full history, pre-fix),
`audit/stage0_science_audit.py` + `.json` (no leakage / no fabricated radii),
`audit/stage0_forward_audit.py` + `.json` (forward-test honesty),
`audit/forward-log-before-rule-fix.jsonl` (pre-fix audit trail, preserved),
`map-prediction-shots/prediction-map-audit.json` (map audit),
`e2e-shots/drawer-audit.json` + `04-drawer-prediction-1902844.png` (UI evidence),
`prediction-validation.csv` / `data/fleet_status/prediction_calibration.json` (radii).

---

## A. Method counts (what the ladder actually serves)

| | before this stage | after |
|---|---|---|
| `history_prior` (rung 4, prior + own displacement) | 0 | **9** |
| `trajectory_extrapolation` (rung 4, own displacement) | 30 | **21** |
| `regional_prior` (rung 3) | 0 | 0 |
| `persistence` (rung 4, last resort) | 0 | 0 |
| unavailable (`insufficient_data` / `insufficient_validation`) | 0 | 0 |
| fallback rung reported | 4 × 30 | 4 × 30 |

The nine floats now on the prior: 2902087, 2902091, 2902092, 2902093, 2902113,
2902114, 2902118, 2902120, 2902203 (neighbour counts 6–37, all ≥ the documented
minimum of 5). Stratum split: 12 South Indian Ocean, 11 Arabian Sea, 6 Bay of
Bengal, 1 Equatorial Indian; 24 decadal-class, 6 short-class.

Fleet-wide `prediction.diagnostics`: `{"trajectory_extrapolation": 21,
"history_prior": 9}`, rungs `{"4": 30}`, statuses `{"ok": 30}`, trajectory history
available 30/30, transitions mean 176.47 / median 215 / min 3 / max 359.

Root cause of the pre-fix behaviour (measured, not assumed): the cached trajectory
block kept only **8** one-per-cycle fixes per float, so the fleet-wide transition
pool the predictors draw from held **200** transitions and no float could satisfy
the documented prior conditions; the same code over the complete public history
(**5,294** transitions, 4–361 usable fixes per float) resolves nine floats with the
prior. Fix = `PREDICTION_FIX_HISTORY` 8 → 400 and `PARSER_VERSION` 3 → 4 so the
existing cache is re-parsed (no rule, radius or ladder change).

**Reproduced from scratch and archived** (`audit/stage0_audit_output.txt`,
`audit/stage0_audit_summary.json`): the 30 public `_Rtraj.nc` files were re-fetched
over the workstation's own FTP source and the real parser/feature/predictor code was
run at three bounds, giving a three-way result that is stronger than the original
two-way comparison:

| bound | transition pool | median transitions/float | `trajectory_extrapolation` | `history_prior` |
|---|---|---|---|---|
| regression ring (8) | 200 | 7 | **30** | 0 |
| shipped ring (400) | 5,294 | 215 | 21 | **9** |
| full history (unbounded) | 5,294 | 215 | 21 | **9** |

Two properties follow, both now on the record: the shipped bound **withholds
nothing** relative to unlimited history (0 floats change between rows 2 and 3), and
the 9 floats the old ring starved are exactly the 9 the live service now serves with
a prior. The per-float diagnosis in the same file shows why the other 21 genuinely
have no prior inside the documented window (nearest-neighbour counts of 0, or fewer
than the required 5 inside ±1 month), so no float is held back by the cache any
more.

## B. Needless persistence / needless fallback

* **Floats served by `persistence` although a documented prior existed: 0** — before
  and after. Persistence was never misused in this fleet.
* **Floats denied their documented prior rung by truncated cache history: 9**
  (the nine above) — this is the "unnecessarily falling back" the stage was about;
  they were served by the lower-ranked trajectory rung. After the rebuild: 0.
* **Floats still on the trajectory rung *correctly*: 21** — for these the prior
  genuinely does not exist within the documented window (2.0° radius, ±1 month,
  ≥5 neighbours, 2.0-day delivery lag). Their rows say so explicitly:
  `no regional/seasonal prior available for this position`.

## C. Floats lacking history

* Verified QC 1/2 position: **30/30** (`insufficient_data`: 0).
* Trajectory history: **30/30** have usable cycle hops (min 3, median 215, max 359);
  none falls through to persistence.
* Observed cycle interval: **29/30** observed (median of published profile dates);
  **2902113** has no observable interval and is served with the documented 10-day
  fallback **and** an explicit issue (`observed cycle interval unavailable; 10-day
  fallback used`) — no silent assumption, no fabricated interval.
* Cycle-scale input advisory (new, reporting only): 3 floats have a most recent hop
  far from their own interval — 2902089 0.74 d = 0.15× (5.00 d), 2902091 10.03 d =
  10.03× (1.00 d), 2902113 0.50 d = 0.05× (10.00 d). Method, rung and radius are
  unchanged; the operator is told the step used by the method may not represent a
  full cycle.

## D. Floats lacking validation strata

**0** — every served prediction matched a calibrated stratum with `n > 0`
(`insufficient_validation`: 0; check A of the science audit recomputes each radius
from the artefact and requires an exact match, including the sample count).
Artefact coverage: 4 methods, 40 stratum bins, 4 regions + default, cases
`{history_prior 2,153 · persistence 5,187 · regional_prior 2,153 ·
trajectory_extrapolation 5,187}`, generator protocol recorded in the artefact
(`prior_lag_days 2.0`, `prior_min_neighbours 5`). **Served sample counts range
8–2,148** depending on the stratum; no default/global radius is used as a
substitute for a missing stratum.

One served stratum is thin: **7902408 uses `trajectory_extrapolation · Bay of
Bengal · decadal cycle` with n = 8**, so its r50/r90 (10.7 / 65.6 km) rest on
eight historical cases. The drawer shows that number, and the artefact's own
bin is honest about it, but a reader should treat it as the weakest radius in the
fleet. A documented minimum-sample policy (refuse or widen below n ≈ 30) is a
calibration decision and therefore **out of scope for Stage 0** — noted as a
Stage-1 candidate.

## E. Is the UI's R50/R90 explanation scientifically accurate?

**Verdict: yes, and it is the strongest wording available without a
probabilistic model.** The served numbers are `np.percentile(errors, 50)` and
`np.percentile(errors, 90)` over great-circle validation errors pooled by
*method × region × cycle class* (chronological, per-float, target float excluded,
2-day lag — see the science audit). "50 %/90 % of historical validation prediction
errors were within this distance" is precisely the definition of those sample
quantiles, and the standing sentence —

> These are empirical uncertainty radii calculated from historical validation
> errors, not a probability guarantee for this individual prediction.

— correctly refuses the individual-probability reading. "90 % confidence" and
"90 % probability" do not appear anywhere in the drawer; the three artefacts that
assert this wording — `frontend/src/components/PredictionDetail.test.tsx`,
`frontend/e2e/fleetStatus.e2e.mjs` and `prediction-validation/capture_prediction_ui.mjs`
— also fail on a probability claim.

Honest caveats (documented in `PREDICTION.md`, stated here for the report):

1. The corpus is a retrospective 29-float / 5,257-case sample of published
   (partly delayed-mode revised) Ifremer trajectories. The radii are **estimates**
   with sampling error, not population values; small strata carry fewer cases.
2. The radii are conditional on the *stratum*, not on the float's current eddy
   state: two floats in the same class share a radius.
3. R90 is a containment statement about the past, not a bound: 10 % of historical
   cases were larger, and the tail is unbounded (the corpus maximum exceeds p90 by
   a factor of 2–4 depending on method).
4. "Validation" here means the leak-free chronological replay on that corpus, not
   an independent operational forecast trial. The deployment-local forward test
   (`prediction.forward_test`) is the honest, still-young complement and is
   labelled as such wherever it appears.

## F. Code / cache issues found

| # | Issue | Status |
|---|---|---|
| 1 | Cached trajectory block (8 fixes/float) starved the predictors: 200-transition fleet pool, prior impossible for every float, 9 floats needlessly on the lower rung | **fixed** — `PREDICTION_FIX_HISTORY` 400 (≈2× the largest usable history, 361) + `PARSER_VERSION` 4; cache re-parsed through the existing sync |
| 2 | Forward test scored sub-cycle fixes: 1902844 scored 2,077.7 km and 2904082 2,196.2 km against fixes only 0.86 d / 1.87 d after issuance (the audit log itself was the evidence) | **fixed** — scoring now requires a strictly later *cycle* (when cycles are known) **and** ≥ half the float's observed interval; the pre-fix log is archived as evidence and the replay shows the correct next cycles ~10 d after issuance |
| 3 | Uncertainty rings were drawn with a local equirectangular approximation: up to 1.2 % radius error (2.79 km on a 226.3 km ring at 45.7°S) | **fixed** — rings are now true geodesic circles (destination-point formula); the map audit measures 0.0000 km worst vertex error across all 60 rings |
| 4 | Rung 4 uses `features.last_transition` as *one cycle's* displacement, which for burst-transmitting floats is a 0.5–0.74 d hop (2902089, 2902113) and for gappy floats a 10 d hop on a 1.0 d cycle (2902091 — served horizon 1.0 d, applied hop 19.5 km, but 2,672 km from the displayed position) | **report-only (by design)** — the algorithm, ladder and calibration are frozen at this stage; each affected row now carries an advisory stating the ratio. Candidate STAGE-1 item: make the step cycle-scale before extrapolating, then recalibrate. Related measurement: **2902092's applied step (69.1 km) exceeds its own quoted R90 (49.6 km)** — one exceedance in 30, i.e. 96.7 % of served steps sit inside their own R90, which is what a 90th-percentile threshold implies (tracked by science-audit check J2, settled honestly by the forward test when that float's next cycle arrives) |
| 5 | Multi-cycle spans (>30 d) are rejected by `MAX_TRANSITION_DAYS = 30`, so gappy floats count fewer transitions | **documented behaviour, unchanged** — rejecting non-cycle gaps is what keeps one-cycle displacements honest; no fabrication |
| 6 | Cached fixes can carry `cycle: null` (arithmetic guard) | **guarded** (pre-existing fix, still covered by tests) |
| 8 | The prediction is anchored on the last **trajectory** fix, which for 5/30 floats is more than 90 days older than the position the page displays (last profile): 1902844, 2902224, 2904082 and 7902408 are 110–137 d apart, and **2901350 is anchored on a 2017-12-08 fix while the displayed position comes from a 2020-04-26 profile — 870 d and 4,545.8 km apart**. The method's own step is sane in every case (2901350: 61.6 km; fleet applied hops median 35.8 km, max 191.3 km), and the drawer's `Issued from` row states the anchor date, but the map's dashed link for 2901350 runs 4,600 km back to the current marker and can read as motion | **report-only, measured and tracked** — science-audit check J + the NOTE in `stage0_science_audit.json`, plus captured evidence `e2e-shots/anchor-2901350-evidence.json`, `anchor-2901350-drawer.png`, `anchor-2901350-map.png` (the map screenshot shows the real marker alone in frame because the drawn connector is 4,604.5 km long; the drawer row `Issued from 2017-12-08 11:01 UTC` is what carries the truth). Stage-1 candidates: anchor on the newest position across the cached products, or refuse/label when the trajectory anchor is much older than the last profile |
| 7 | Tracked fixture `decoder-ui/data/fleet_status/cache.json` differs from HEAD (pretty-printed; 30 rows, i.e. without the two floats deleted in the approved Coriolis cleanup) | **verified as intended, not accidental** — restoring the HEAD version was tried and it *fails* `tests/test_fleet_status_audit.py::test_actual_cache_total_is_available_cycles_not_sum_of_maxima` (that test asserts 30 NO-DATA rows and totals 5,625/5,647/22 for the current 30-float fleet); the working version is the one the green suite requires and was left in place |

## G. Exact files changed

**Service (algorithm, radii, ladder, API contract untouched)**

* `service/fleet_status.py` — `PARSER_VERSION` 3 → 4, `PREDICTION_FIX_HISTORY` 8 → 400
  (rationale comment with the 200 → 5,294 pool evidence), `_prediction_diagnostics()`
  → `prediction.diagnostics`, `_step_advisory()` + per-row `issues` advisory wiring.
* `service/prediction/forward_test.py` — cycle-aware `_next_fix_after(...)`
  (`issued_from_cycle`, later cycle **and** ≥ half observed interval) and
  `issued_from_cycle` recorded on issued events.

**Frontend (UI/design otherwise preserved)**

* `frontend/src/components/FloatStatusPage.tsx` — drawer rows: Prediction Method,
  Fallback rung, **Trajectory history available**, **Trajectory transitions**,
  Validation Sample Count, **R50 (empirical)** and **R90 (empirical)** with the
  exact required texts, plus the empirical-caveat note
  (`data-testid="prediction-radius-note"`).
* `frontend/src/components/fleetMapModel.ts` — `circleRing()` now places ring
  vertices by the spherical destination-point formula (geodesic circle of exactly
  the quoted km), `EARTH_RADIUS_KM = 6371.0088`.
* `frontend/src/components/fleetMapModel.test.ts` — ring test asserts the
  great-circle radius (< 1 m) incl. a pole-adjacent ring.
* `frontend/src/components/PredictionDetail.test.tsx` — exact R50/R90 wording,
  caveat sentence, banned-probability assertions, trajectory rows.
* `frontend/e2e/fleetStatus.e2e.mjs` — drawer checks for the new rows and wording,
  fleet diagnostics (methods/rungs/persistence/history/transitions) checks.
* `frontend/e2e/predictionMap.e2e.mjs` — **new**: map audit (predicted point == API
  lat/lon to < 1 m, ring vertices == API r50/r90, no ring when unavailable, real
  markers untouched, opt-in/clear behaviour).
* `frontend/package.json` — `test:prediction-map` script (`node e2e/predictionMap.e2e.mjs`)
  so the map audit runs from the repo like the other suites.

**Tests (regressions for the two defects)**

* `tests/test_forward_test.py` (+2) — a 0.9-day burst fix never scores a 10-day
  prediction; without cycle numbers the half-interval rule applies.
* `tests/test_prediction.py` (+1) — the step advisory flags non-cycle-scale hops and
  provably leaves method, rung and radius unchanged.

**Docs**

* `PREDICTION.md` — cycle-aware scoring rule and its evidence, input advisory,
  geodesic rings, `diagnostics` fields, the exact drawer wording section.
* `FLEET_STATUS.md` — why the fix ring was 8 → 400 (+`PARSER_VERSION`), and the
  prediction-input advisory.

**Audit artefacts (outside the repo)**

* `prediction-validation/audit/stage0_audit.py`, `stage0_science_audit.py` (+.json),
  `stage0_forward_audit.py` (+.json), `audit/forward-log-before-rule-fix.jsonl`.
* `prediction-validation/capture_prediction_ui.mjs` (drawer/map evidence capture),
  `e2e-shots/drawer-audit.json`, `map-prediction-shots/prediction-map-audit.json`.
* This report: `prediction-validation/STAGE0_AUDIT_REPORT.md`.

---

## Verification runs (all on the live deployment, after the changes)

| Suite | Result |
|---|---|
| Backend `pytest tests -q` (`env -u FLEET_SYNC_ENABLED PYTHONPATH=src:service`) | **301 passed** |
| Frontend `vitest run` | **166 passed** (15 files) |
| `tsc --noEmit` | clean |
| `e2e/fleetStatus.e2e.mjs` (fleet browser contract) | **1083/1083**, 30 floats field-checked |
| `e2e/predictionMap.e2e.mjs` (map audit) | **162/162**, 30 points + 60 rings audited, worst ring vertex error 0.0000 km |
| `e2e/fleetMap.e2e.mjs` | 15/15 |
| `e2e/eezLayer.e2e.mjs` | 27/27 |
| `e2e/decodeAllGating.e2e.mjs` | 16/16 |
| `e2e/ingestionArrivals.e2e.mjs` | 17/17 |
| `audit/stage0_science_audit.py` (leakage/radii/strata/anchor) | **16/16**, 30 predictions re-derived; served == recomputed (E2), priors exact (F3) and withheld priors proven necessary (F4) |
| `audit/stage0_forward_audit.py` (audit honesty) | **11/11**, 30 events, 30 keys, 2 archived replay cases |
| `demo_forward_test.py` (offline scoring path) | scored 51.15 km, r50 47.3 missed / r90 206.7 hit, re-poll adds nothing |

Monitoring is unchanged by all of this: 30 floats / 4 recent profile / 2 overdue /
24 no-recent-profile-60+ / 0 no-data / 13,845 approx. missed / 5,628 profiles, and
the two API polls in the forward audit returned identical monitoring figures and
identical float rows.

**Stage-0 success criterion:** met — the shipped prediction now uses all available
historical trajectory information (9 floats resolved at the documented prior rung,
0 needless fallbacks, 0 unavailable), and the UI states the empirical basis of
R50/R90 with the required wording.

---

## Appendix — Stage-0 steps 1–10 mapped to their evidence

| Step (as specified) | Where it is answered / proven |
|---|---|
| 1. Audit every monitored float (position, history, transitions, interval, method, rung, samples, r50/r90, status, issues, persistence-only) | §A–§C above; raw: `audit/stage0_audit_output.txt` / `stage0_audit_summary.json` (three-bound table) + `prediction.diagnostics` in the live payload |
| 2. Identify misses: Rtraj present but unparsed; enough history yet persistence used; cached rows predating the fix-history parser; unavailable despite valid upstream data | §B above — 9 floats denied the prior by the truncated cache (fixed, named in `stage0_audit_summary.json`); 0 persistence; 0 unavailable; cache rows all now `parser_version 4` |
| 3. Refresh cached trajectory blocks from the already-available Ifremer files via the existing cache/download (no new historical DB) | cache rebuilt through `POST /api/fleet-status/sync` (30/30 ok, ~435 s); `PREDICTION_FIX_HISTORY` 400 + `PARSER_VERSION` 4; no new store created |
| 4. Re-run prediction generation, verify the ladder rungs | §A — 9 `history_prior` / 21 `trajectory_extrapolation`, all rung 4 reported honestly, prior threshold ≥5 neighbours met by every prior case |
| 5. Fleet-wide diagnostics (method/rung distribution, persistence, history_prior, trajectory, unavailable, insufficient validation, transitions) | `prediction.diagnostics` on the live payload; asserted by fleet E2E ("diagnostics report the same methods/rungs as the rows") and §D of the science audit |
| 6. UI drawer contents + the three exact texts, no "90 % confidence/probability" | §E above; `e2e-shots/04-drawer-prediction-1902844.png`, `e2e-shots/drawer-audit.json`, drawer checks in `fleetStatus.e2e.mjs` (1083/1083), `PredictionDetail.test.tsx` |
| 7. Map audit (predicted point == API lat/lon; rings == API r50/r90; no ring when unavailable; real marker unchanged) | `e2e/predictionMap.e2e.mjs` 162/162 + `map-prediction-shots/prediction-map-audit.json`: points 0.000 m from the API, 60 rings at 0.0000 km worst vertex error, no graphics for unavailable floats, 30 real markers byte-identical |
| 8. Science audit (no future leakage, target float excluded, 2-day lag, chronology, stratum match, no hardcoding, no fabrication) | `audit/stage0_science_audit.py` **16/16** + `stage0_science_audit.json` — E2 (served == a fresh run of the shipped code), F3 (every served prior reproduces exactly under the documented rule), F4 (every float without a prior genuinely fails those conditions — no higher rung skipped), J (real one-cycle hop from the anchor: median 35.8 km), J2 (96.7 % of steps inside their own R90, exceedance named) |
| 9. Forward-test audit (idempotent, strictly-newer scoring, quoted radii preserved, pending stays pending, isolation) | `audit/stage0_forward_audit.py` 11/11 + `stage0_forward_audit.json`; offline live-path demo `demo_forward_test.py` |
| 10. Report A–G | This document |

## Post-reset re-verification (2026-09-21 16:15–16:25 UTC)

The working environment was rebuilt (fresh `.venv`, `npm install`, Playwright
chromium-1243) and **every** check was re-run against the unchanged code and cache:

backend `pytest` **301 passed** · vitest **166 passed** (15 files) · `tsc --noEmit`
clean · `fleetStatus.e2e.mjs` **1083/1083** · `predictionMap.e2e.mjs` **162/162** ·
`fleetMap.e2e.mjs` 15/15 · `eezLayer.e2e.mjs` 27/27 · `decodeAllGating.e2e.mjs`
16/16 · `ingestionArrivals.e2e.mjs` 17/17 · science audit **16/16** · forward audit
**11/11**. Live payload unchanged: 9 `history_prior` / 21
`trajectory_extrapolation`, rungs `{"4": 30}`, `persistence_only 0`, forward test
30 issued / 0 scored / 30 pending, monitoring 30 / 4 / 2 / 24 / 0.

## Post-audit verification pass (2026-09-21 16:40–16:55 UTC)

The audit itself was re-tested against the live deployment and **two of its own
claims were corrected**, plus one new finding and two stronger checks were added:

| Change | Why |
|---|---|
| §D sample range corrected to **8–2,148** (was "22–2,148") and the thin stratum named: 7902408 uses `trajectory_extrapolation · Bay of Bengal · decadal cycle` with **n = 8** | the live payload shows 7902408 at 8 samples; the earlier range was wrong, and an 8-case radius deserves to be visible to the reader rather than averaged away |
| §E wording corrected to "the three artefacts that assert this wording" (was "four suites") | grep of every consumer: `PredictionDetail.test.tsx`, `fleetStatus.e2e.mjs`, `capture_prediction_ui.mjs` |
| **New finding #8 — trajectory-anchor age** | 5/30 floats are predicted from a trajectory fix >90 d older than the displayed position (2901350: 870 d / 4,545.8 km); the applied step stays sane (61.6 km) but the map's dashed connector is unreadable as motion. Measured, tracked, evidenced (`e2e-shots/anchor-2901350-*`), not changed |
| **New science-audit checks** | **E2** served prediction == a fresh run of the shipped code on the same cache (position, method, rung, radii, stratum); **F3** every served prior reproduces *exactly* under the documented rule (2.0° radius, ±1 month, 2.0 d lag, ≥5 neighbours) — previously only "≥ minimum"; **F4** every float *without* a prior genuinely fails those conditions, so no higher rung was skipped; **J2** 96.7 % of served steps sit inside their own quoted R90, with the single exceedance named (2902092: 69.1 km vs r90 49.6 km) |
| **An arbitrary threshold removed** | J2's first draft asserted "≤ 20 km/day of drift", a number I invented; it failed (191.3 km over a 5 d horizon is 38 km/day). The replacement states a real statistical property of the quoted radii, and J now measures the applied hop separately from the apparent distance to the displayed position (median 35.8 km vs 39.6 km) |

Science audit is now **16/16**; everything else re-ran unchanged: backend **301**,
vitest **166**, tsc clean, `fleetStatus.e2e.mjs` **1083/1083**,
`predictionMap.e2e.mjs` **162/162**, forward audit **11/11**.

---

## Stage-1 candidates (proposals only — nothing implemented, algorithm frozen in Stage 0)

Each item below is measured, evidenced and **not** actioned, because it changes the
prediction algorithm, the calibration mathematics or a documented definition and
therefore needs explicit direction.

| # | Change | Evidence today | Why it matters | Would need |
|---|---|---|---|---|
| 1 | Anchor the prediction on the **newest verified position across the cached products** (or label/refuse when the trajectory anchor is much older than the last profile) | finding #8 — 5/30 floats anchored >90 d older than the displayed position; 2901350: 870 d / 4,545.8 km, drawn connector 4,604.5 km (`e2e-shots/anchor-2901350-*`) | removes a case where the map can read as 4,600 km of motion in 10 days | algorithm change + recalibration (the anchor change shifts every validation case) + UI wording for the labelled case |
| 2 | Make the rung-4 step **cycle-scale** before extrapolating (use several hops, or the cycle-matched hop, instead of the single last hop) | finding #4 — 3 floats have a last hop of 0.50–0.74 d (bursts) or 10.03 d on a 1.0 d cycle; advisory now flags them | the extrapolated displacement currently assumes the last hop *is* one cycle | algorithm change + full recalibration + new unit tests for burst/gappy floats |
| 3 | A **minimum-sample policy** for calibrated radii (refuse below, or widen with a documented wider stratum) | §D — 7902408 served from `n = 8`; fleet median n is far higher | an 8-case p90 is a weak radius presented next to 1,600-case ones | calibration decision (R50/R90 definition untouched, but the refuse/widen rule is new) + UI copy for the refusal path |
| 4 | Report the **applied hop vs the displayed position** distinction in the drawer (not only in the audit) | §F #8 + check J — median applied hop 35.8 km vs apparent distance 39.6 km; the two diverge sharply only for the stale-anchor floats | gives an operator the number the method actually used | UI-only change, no algorithm or calibration impact — the cheapest of the four, if you want one item taken early |

Also open from the previous stage, unchanged and out of scope here: the 5
pre-existing registry-content test failures in the core tree (they assert the two
floats deleted in the approved Coriolis cleanup), and the ML rung, which stays
reserved until an out-of-sample improvement on broad Argo data is demonstrated.

---

## Stage-1 pass (implemented behind a switch, evaluated, not shipped) — 2026-09-21

Candidate **#2 above was taken up as Stage 1** and is now implemented, evaluated and
deliberately left off by default, so nothing in this Stage-0 report is invalidated:
Stage 0 remains the shipped Predictor (`PREDICTION_CYCLE_STEP=off`).

| item | outcome |
|---|---|
| cycle-scale rung-4 step (#2) | implemented in `service/prediction/cycle_step.py` (freshest window in `[0.75, 1.25] × interval`; ≤ 3-cycle spans divided by whole cycles; burst spans ignored, never rescaled) |
| evaluation | 5,071 paired, deployment-faithful cases / 29 floats, target-matched labels, leave-one-float-out — median −2.66 %, p90 −0.72 % (worse), RMSE +28.49 %, mean +6.24 % against the pre-registered gate (≥5 % / ≥5 % / ≥0 %) |
| ship decision | **failed** → not shipped; measurements, class tables and the scoped-variant result in `/home/user/prediction-validation/STAGE1_REPORT.md` |
| what it does fix (measured) | the irregular classes: burst p90 2,655.6 → 717.4 km, gap median 54.9 → 34.3 km on the served series |
| effects on this report's evidence | Stage-0 artefact byte-unchanged (42,481 B, no `stage` key); live payload 30/30 `predictor_stage = stage0` in the shipped default; science audit now 17/17 (stage-aware: A0 added, A/E2 verify whichever stage is serving) and forward audit 11/11, both re-run green in the shipped default **and** with Stage 1 enabled |
| one protocol correction it surfaced | `prediction/validate.py::load_fixes` documented "chronological" but returned file order; 4 of 30 corpus files contain out-of-order rows around a long silence. Now sorted by JULD (no row added/dropped/interpolated). Measured effect on the aggregate Stage-0 replay: median 30.5 → 30.7 km, p90 183.5 → 186.0, RMSE 483.2 → 471.8, max 18,915 → 16,181 km (`audit/stage1_order_effect.py`) |
| test-suite isolation fix it surfaced | two older modules imported the service before redirecting `ARGO_UI_DATA_DIR`, so a test run appended forward-test records for the synthetic float 2909999 into the repository's own `data/fleet_status/prediction_forward_log.jsonl` — a file a deployment started without the variable serves as its own history. Fixed by `tests/conftest.py` (pins the variable before any module import; `setdefault`) plus import-order fixes and a guard test. Fixture log restored to its 30 records, md5 unchanged by the full suite and by each module run alone. Backend total **331**. Details in `STAGE1_REPORT.md` §I |

Candidates **#1, #3 and #4 remain unimplemented** and unimpaired by this pass.
