# Next Profile Location Prediction — scientific research and design

**Feature:** predict where an Argo float will surface for its next profile (cycle N → N+1) in the
INCOIS ARPY Decoder Workstation (`decoder-ui`).

**Status: RESEARCH / DESIGN ONLY.** No code was written or changed for this feature; nothing in
`src/argo_decoder/` was touched. Implementation waits for your approval and for the decisions in
Appendix B. Every number quoted below is either (a) measured by me from public GDAC files and
listed with file hashes in Appendix A, or (b) cited from a named source in Section K. No accuracy
figure is invented, and no data source is assumed to be available without saying so.

**Headline measured results (fleet hindcast, one cycle ≈ 10 d, Appendix C).** On the workstation's own
30-float trajectory corpus, with leakage-safe predictors and paired statistics:

| Predictor | median err | p90 err | Paired 95 % CI vs persistence (median / p90) |
| --- | --- | --- | --- |
| Persistence (stay put) | 28.1 km | 82.7 km | reference |
| Constant velocity (last displacement) | 21.5 km | 111.4 km | **−6.7 km [−7.8, −5.5]** / **+28.7 km [+19.5, +38.6]** |
| Regional-seasonal prior alone | 27.7 km | 83.9 km | not tested |
| **0.2 × last displacement + 0.8 × prior** (LOFO-selected) | **20.1 km** | 98.1 km | LOFO, n = 3,199 (Table C6) |
| 0.7 × last displacement + 0.3 × prior (tail-minimising) | 23.6 km | 82.4 km | in-sample sweep (Table C6) |
| 0.5/0.5 blend | 21.5 km | 90.2 km | −6.6 km [−7.4, −5.6] / +7.5 km [+1.7, +13.4] |

Empirical radii transferred to floats *not* used to derive them cover the nominal 50 % / 90 % levels to
within ~2 percentage points (51.5 % / 89.4 %, Appendix C Table C7). Skill decays fast beyond one cycle:
median error 21.5 km → 43.6 km → 66.6 km at 1 → 2 → 3 cycles (Table C8).

---

## 1. Problem statement and operational framing

A float surfaces, transmits, and then descends to a parking depth for most of its cycle, rising once
per cycle to profile. Consequence for this feature:

* the **only position observations** are at (or near) the surface, once per cycle — between two
  consecutive fixes the float's path is *unobserved*;
* `Expected Next Profile = Last profile JULD + 10 d` already exists in the workstation, so the
  feature answers a *place*, not a *time* question: "where should we look, and how sure are we?";
* the prediction must never be presented as a communication signal, and must not alter the approved
  profile-recency status semantics (ACTIVE / RECENT PROFILE, PROFILE OVERDUE, NO RECENT PROFILE
  DATA 60+ DAYS, NO DATA) or the banned-wording rules.

Scientific question: estimate **position of the next surfacing** given only information available at
the time of the last received cycle, with a *calibrated* uncertainty.

---

## 2. Evidence base

### 2.1 Measured on real INCOIS floats (Appendix A, hashes recorded)

| WMO | platform / telemetry | cycles | median cycle | median 1-cycle displacement | p10–p90 displacement | median drift |
| --- | --- | --- | --- | --- | --- | --- |
| 2902223 | APEX / Argos | 344 | 10.00 d | 99.1 km | 35.6 – 198.9 km | 9.9 km/d |
| 2902203 | APEX / Argos | 362 | 9.99 d | 24.9 km | 9.3 – 49.1 km | 2.5 km/d |
| 2902086 | PROVOR_III / Iridium | 246 | 5.00 d | 17.5 km | 5.6 – 150.8 km | 4.1 km/d |
| 1902844 | ARVOR / Iridium | 78 | 10.00 d | 56.2 km | 21.9 – 150.2 km | 5.7 km/d |

Two operational findings from the same files that directly shape the design:

1. **Schedule must come from observations, not only configuration.**
   `<WMO>_meta.nc` carries `CONFIG_ParkPressure_dbar`, `CONFIG_CycleTime_hours`,
   `CONFIG_ParkTime_hours`, `CONFIG_AscentTime_hours`, `CONFIG_SurfaceTime_HH`. For 2902086 the last
   mission's `CONFIG_CycleTime_hours` is 24 h while the *observed* cycle is 5.00 d — programme
   changes over a float's life, so the Rtraj-observed schedule wins and config is a fallback only.
2. **Park depth reporting is inconsistent across platforms.** `REPRESENTATIVE_PARK_PRESSURE` is
   filled (99999) for both APEX floats but valid (~996 dbar) for the PROVOR_III — so the parking
   depth chain is: per-cycle Rtraj value → meta config → documented nominal (1000 dbar) → refuse.
3. **Telemetry changes the surface-drift exposure.** Measured transmission window (TST→TET): median
   **0.02 h** for Iridium but **7.9–8.1 h** for Argos; programmed surface time is 6.6 h. A float that
   spends ~8 h at the surface before its last fix drifts with near-surface currents that are *not*
   representative of parking-depth flow. This matches the published observation that Argos floats
   show larger surface displacement than Iridium floats (transition-matrix paper, Section K).

### 2.2 Argo data products available

* `dac/incois/<WMO>/<WMO>_Rtraj.nc` — cycle-level trajectory: `JULD`, `LATITUDE`, `LONGITUDE`,
  `POSITION_QC`, `POSITION_ACCURACY`, `CYCLE_NUMBER`, `MEASUREMENT_CODE` (703 = satellite fix),
  phase timings (`JULD_DESCENT_START/END`, `JULD_PARK_START/END`, `JULD_ASCENT_START/END`,
  `JULD_TRANSMISSION_START/END`, `JULD_FIRST/LAST_LOCATION`, `JULD_FIRST/LAST_MESSAGE`) and
  `REPRESENTATIVE_PARK_PRESSURE` (verified on a real file: 102 variables, N_CYCLE=343 for 2902223).
* `<WMO>_meta.nc` — platform type, telemetry, positioning system, and the `CONFIG_*` programme
  parameters listed above.
* `<WMO>_prof.nc` — already the authority for the profile-recency monitor (do not disturb).
* `<WMO>_tech.nc`, BGC/Sprof — optional, not required for a first version.

The workstation already fetches `<WMO>_prof.nc` over the same GDAC/FTP/HTTPS paths, so adding
`_Rtraj.nc`/`_meta.nc` uses an existing, proven access pattern (no new credential).

### 2.3 Current-field sources that realistically exist for the Indian Ocean

| Source | What it gives | Resolution / horizon | Notes |
| --- | --- | --- | --- |
| CMEMS `GLOBAL_ANALYSISFORECAST_PHY_001_024` (GLO12) | 3-D currents top-to-bottom + hourly surface fields; includes a merged surface-current dataset (SMOC) that adds wave and tidal drift | 1/12° (~8 km), 50 levels, **10-day forecast**, daily update | Covers the full 10-day cycle; requires a free CMEMS account/credentials |
| CMEMS `GLOBAL_MULTIYEAR_PHY_001_030` (GLORYS12V1) | eddy-resolving reanalysis currents | 1/12°, daily, 1993 → present | The back-testing workhorse: lets us evaluate predictors on historical cycles without forecasts |
| CMEMS DUACS `SEALEVEL_GLO_PHY_L4_NRT_008_046` / `MY_008_047` | gridded SLA/ADT → absolute geostrophic currents (`ugos`,`vgos`) | 0.125°, daily | Geostrophy only (no Ekman/wave); gridded effective resolution is much coarser than the grid (~180 km / 33 d per the QUID) — a genuine limitation at parking depth |
| NASA **OSCAR** | surface total current (geostrophic + wind + thermal-wind), averaged over top ~30 m | ~0.25°, 5-day | Independent (non-CMEMS) surface-current cross-check |
| **Scripps Argo trajectory-based velocity product** / YoMaHa'07 / ANDRO | *measured* parking-depth velocities from ~200 000 Argo cycles (mostly 800–1200 dbar) | point data, global | Ideal for priors, for validating the modelled parking-depth current, and for a "climatological drift" baseline; older products are discontinued/less QC'd |
| INCOIS **HOOFS / OSF** (ROMS, 1/4° basin, 1/48° coastal; 3–7 day forecasts) and **SARAT/SARAT 2** (operational drift prediction for search and rescue) | Indian Ocean currents + established drift-prediction capability in-house | forecast horizon **shorter than one 10-day cycle** | Excellent partner source and precedent, but the horizon does not cover a full cycle on its own — a reason to keep a global 10-day forecast or a statistical fallback |

---

## A. Recommended overall approach

**Hybrid, staged, and calibrated — with the physics step carrying the prediction and ML only as a
validated residual correction.**

1. **Stage 0 (MVP, ships first): schedule + shrunk-displacement predictor with empirical uncertainty.**
   * target time: expected next surfacing ≈ last fix time + last observed cycle interval
     (measured median error 0.01–0.10 d — timing is the easy part, Appendix C Table C2);
   * position: **blend of the last observed displacement with a leakage-safe regional-seasonal
     drift prior**, `w_prior = 0.2` for the point estimate (chosen leave-one-float-out in Table C6,
     median 20.1 km, −29 % versus persistence) and `w_prior ≈ 0.5–0.7` where a smaller tail matters
     more than the median (p90 82–90 km). Report the blend weight in the provenance so the two modes
     are never confused;
   * uncertainty: radii from the LOFO calibration store (region × cycle class × blend weight);
     measured transfer to unseen floats is within ~2 points of nominal (Table C7);
   * horizon policy: one cycle = the supported product; two cycles = indicative, radius must come
     from Table C8; three or more = refuse (`insufficient_data`);
   * Why first: it needs **no new credentials**, works offline, is fully reproducible, and sets a
     stiff bar — median ≈ 20 km at one full cycle — that physics and ML must beat.
2. **Stage 1 (physics / Lagrangian advection).** Advect the float through the cycle using modelled
   3-D currents at the float's parking depth for the parked phase, plus ascent/descent and a
   surface-drift term over the transmission window, driven by CMEMS GLO12 (analysis for t ≤ last
   fix; forecast for the remainder, up to 10 days) with GLORYS12V1 for hindcasts. Integrate as an
   **ensemble** (see G) rather than a single trajectory.
3. **Stage 2 (ML, conditional).** Only if it beats Stage 1 out-of-sample by a pre-registered margin:
   a residual model that predicts the *error vector* of the Stage-1 displacement from
   leakage-safe features (Section D/E). Candidates: gradient-boosted trees or a small recurrent net;
   published Argo-buoy deep-learning work (SRU + spatio-temporal attention) exists but reports its
   own splits, so it cannot be treated as evidence for our fleet.

**Minimum viable, scientifically defensible deliverable:** Stage 0 + Stage 1 with the uncertainty
calibration of Section G, presented as *experimental prediction*, with provenance and refusal states.
Stage 0 alone is the fallback whenever currents are unavailable — never a silently fabricated point.

---

## B. Alternatives considered

| Option | Strengths | Weaknesses for this task | Verdict |
| --- | --- | --- | --- |
| **B0** Persistence (last known position) | trivial, no data | error equals the full inter-cycle displacement (median 25–99 km on our floats); useless as a prediction | baseline floor only |
| **B1** Displacement persistence / constant velocity from previous cycles | no external data; captures local drift; cheap; works offline | fails when the float turns with a mesoscale eddy; degrades after data gaps | **adopt as Stage 0** |
| **B2** Climatological / regional-mean drift (Scripps/YoMaHa-type products; local multi-year Rtraj means) | independent of any model; physically meaningful; good prior | too smooth in the tropics/BoB where variability is high; seasonality matters | adopt as a *shrinkage prior* inside Stage 0 |
| **B3** Single deterministic Lagrangian advection by model currents | direct physical reasoning; uses the best available 3-D fields | one trajectory says nothing about uncertainty; chaotic advection amplifies small velocity errors | reject as-is; keep the integrator and make it an ensemble |
| **B4** Physics/Lagrangian **ensemble** with calibrated radii (Stage 1) | physically defensible; produces honest uncertainty; testable at 10-day leads | needs a credentialed provider; parking-depth current skill is genuinely limited; model error must be injected explicitly | **recommended core** |
| **B5** Statistical transition matrices (Chamberlain et al. 2023 / ARGONE) | model-free, uses 24 years of Argo positions | designed for 2°×2° / 90-day array-scale probabilities, not one-float/one-cycle geodesic accuracy | reject for this feature; keep as a possible uncertainty prior for large leads |
| **B6** ML regressor/sequence model trained directly on positions | can exploit non-linear structure, platform quirks, seasonal patterns | small local sample (~10³ cycles for the workstation fleet), high leakage risk, opacity, and published accuracy is not transferable evidence | **defer to Stage 2, gated on beating Stage 1** |
| **B7** Trajectory data assimilation into the ocean model (MFS/OceanVar style) | best-possible velocity correction; demonstrated ~15 % trajectory improvement in the Mediterranean system | requires an ocean-model assimilation cycle — far beyond a decoder workstation's remit | out of scope; note as INCOIS modelling-centre collaboration |
| **B8** Auxiliary: surface-drift-only prediction (assume the float surfaces near the same longitude/latitude) | trivial | ignores the dominant parked-phase drift | reject |

---

## C. Required data sources

**Mandatory (already-reachable patterns):**

| Data | Endpoint | Use | Constraint |
| --- | --- | --- | --- |
| `_Rtraj.nc` per float | `https://data-argo.ifremer.fr/dac/incois/<WMO>/<WMO>_Rtraj.nc` (FTP mirror already used by the monitor) | observed schedule, surface fixes, park pressure, QC | one small file per float (2902223 ≈ 1.4 MB; 2902086 ≈ 7.9 MB) |
| `_meta.nc` per float | same DAC path | park depth/cycle config fallback, platform + telemetry class | per-mission config may be stale (measured, §2.1) |
| `_prof.nc` | same DAC path | authoritative profile times/positions already used by the monitor | do not change existing consumption |

**Required for Stage 1 (physics):**

| Data | Where | Notes |
| --- | --- | --- |
| 3-D + surface currents, analysis + 10-day forecast | CMEMS GLO12 (`GLOBAL_ANALYSISFORECAST_PHY_001_024`) | free but **credentials required** (`copernicusmarine` client or subsetting service). The sandbox has none today — this is a deployment decision, not a technical blocker |
| historical currents for back-testing | CMEMS GLORYS12V1 (`GLOBAL_MULTIYEAR_PHY_001_030`) | same credential; gives the full validation corpus over the fleet's lifetime |

**Optional / cross-check:** DUACS L4 geostrophic currents (0.125°, daily), OSCAR surface currents,
Scripps/YoMaHa/ANDRO parking-depth velocity products, INCOIS HOOFS/OSF fields and SARAT as an
in-house comparison, and bathemetry/coastline (INCOIS EEZ + GEBCO-class data) to flag grounding risk.

**Explicitly not assumed:** any INCOIS-internal, non-public current product; any float list beyond the
30 floats the workstation actually discovers; any network access from the *browser* (all fetching
stays server-side, consistent with the existing monitor).

---

## D. Features (for Stage 1 calibration and Stage 2 modelling)

| Feature | Source | Availability | Leakage risk if mishandled |
| --- | --- | --- | --- |
| last surface fix (lat/lon, `POSITION_QC`, `POSITION_ACCURACY`) | Rtraj | always (QC 1/2 preferred) | low |
| time of last fix / last message; expected next surfacing time | Rtraj + existing +10 d convention | always | low |
| last k cycle displacements & headings (k = 1…5) | Rtraj | for floats with ≥2 cycles | must truncate at cycle N |
| observed cycle length / park duration statistics (per float, per region) | Rtraj | good coverage | low |
| parking depth (per-cycle → config → nominal) | Rtraj / meta | inconsistent (§2.1) | low |
| platform type, telemetry class (Argos/Iridium), positioning system | meta | always | low |
| phase durations (descent/ascent/surface/transmission) | Rtraj timings, meta `CONFIG_*` | partial (fill values common on APEX) | low |
| modelled current at parking depth along the predicted path | CMEMS analysis (t ≤ t_N) | needs credentials | using forecast fields initialised *after* t_N is leakage in back-tests; use GLORYS12V1 for history and the real-time analysis only in production |
| modelled surface current + wind/wave drift over the surface window | SMOC / OSCAR | needs credentials | same rule |
| bathymetry / distance to coast (grounding risk) | INCOIS EEZ / GEBCO-class | already partly in repo for EEZ | low |
| basin/seasonality indicators (Arabian Sea, Bay of Bengal, equatorial band, monsoon phase) | derived | always | low |
| historical residual statistics of the same predictor (per float, per region) | our own hindcast archive | builds up over time | must be built from *past* cycles only |

---

## E. Training / validation strategy (and leakage rules)

**Leakage rules — non-negotiable:**

1. Only information with timestamp ≤ the cycle-N transmission time may be used, including model
   fields (analysis, not a forecast initialised later) and file versions (freeze by fingerprint:
   mdtm/size or checksum). Reject any file whose `DATE_UPDATE` is after t_N when back-testing.
2. Never read cycle N+1 (position, timing, or `CYCLE_NUMBER` existence) — including "the file
   happens to end at N+1" effects when slicing arrays.
3. Split by **time** (rolling origin / forward chaining) *and* by **float** (leave-floats-out). Random
   row splits are invalid here: neighbouring cycles of one float are strongly autocorrelated.
4. Calibration (uncertainty radii) must be fitted on a period disjoint from the evaluation period.
5. Feature windows, regional means and residual statistics must be computed from data strictly
   before the prediction time (no full-history climatology that includes the test cycle).
6. Keep delayed-mode/updated products out of real-time features; the real-time monitor must be able
   to reproduce the exact prediction from stored inputs.

**Protocol:**

* **Stage 0:** fit nothing except regional/seasonal shrinkage weights; evaluate directly.
* **Stage 1:** tune only a small number of knobs (sub-grid diffusivity, surface-drift coefficient,
  ensemble spread scaling) on a training window; freeze them for evaluation.
* **Stage 2 (if attempted):** leave-floats-out group CV + rolling-origin; report both pooled and
  per-float metrics; require the improvement to survive a bootstrap confidence interval.
* **Sample size reality check:** the workstation fleet is 30 floats with ~5.6 × 10³ profile cycles
  in the local inventory (fleet cache, 2026-09-21). That is thin for a deep model but ample for
  Stage 0/1 calibration per region *if* the Indian Ocean GDAC archive (thousands of floats) is used
  for physics validation only — with explicit platform/config domain-shift caveats.
* **Pre-registration:** fix the target time definition, QC filter, metric list and the pass/fail
  margin *before* looking at results (Section I).

---

## F. Expected limitations (honest error scales)

1. **Positions exist only at the surface.** The dominant term — parking-depth drift over ~9 days —
   is inferred, not observed for the cycle being predicted.
2. **Chaotic advection bounds any method.** Published Lagrangian-predictability work reports a
   horizon of roughly 3–10 days for ocean velocity fields (FTLE-based estimate in the 2025 review),
   and drifter-based separation growth of about 4–25 km/day, with ~15 km separation after 24 h in one
   regional assessment. A 10-day Argo cycle therefore sits *at or beyond* the practical horizon in
   energetic regions.
3. **Measured skill, not assumption (Appendix C, hindcast on this fleet's own trajectories).**
   A leakage-safe hindcast over 29 floats / 3,276 like-for-like cases gives: plain persistence
   28.1 km median / 82.7 km p90; best blend (last displacement + regional prior) **21.5 km median**,
   mean 41.3 km, RMSE 76.7 km, p90 90.2 km, hit-rate 81.7 % within 50 km. Regionally: Arabian Sea
   p90 ≈ 55 km (Argos), Bay of Bengal p90 ≈ 103–146 km, equatorial Indian p90 ≈ 130 km,
   South Indian Ocean p90 ≈ 139–146 km. These are *one-cycle* (~10 d) numbers and the bar Stage 1
   must clear.
4. **Skill decays steeply beyond one cycle (measured, Table C8).** Median error 21.5 km → 43.6 km →
   66.6 km at 1 → 2 → 3 cycles, and constant-velocity extrapolation degrades *worse than persistence*
   by cycle 2 (68.4 km vs 66.1 km) and much worse by cycle 3 (109.4 km vs 89.9 km). The 10-day lead
   already sits near the practical horizon; a 30-day lead is a different, much weaker product and
   should be labelled as such, not sold as the same number with a bigger circle.
5. **Two practical data caveats discovered in the corpus (Appendix C).** (i) A float can pass the
   "has ≥3 cycles" test and still be unscorable — 2902113 has only three QC'd cycles for 21 satellite
   fixes, so no cycle transition exists; the feature must report that honestly. (ii) One third of
   cases had no usable neighbourhood for the prior, which is why Stage 0 needs an explicit fallback
   ladder (blend → last displacement → persistence) that widens the radius at each rung.
6. **Parking-depth current skill is the binding constraint.** At 1000 dbar, observations are sparse
   and gridded altimetry-derived geostrophy has an effective resolution far coarser than its grid;
   1/12° models do not resolve sub-mesoscale motion that a float actually samples.
7. **Telemetry asymmetry.** Argos floats spend hours at the surface (measured 7.9–8.1 h vs 0.02 h for
   Iridium), so their fixes include surface drift not representative of the parked phase — a
   systematic, platform-dependent bias.
8. **Non-nominal cycles defeat prediction:** grounding/beaching, under-ice excursions, mission
   re-programming (measured: 2902086 config ≠ observed cycle), aborted or skipped cycles, sensor or
   telemetry failure, and floats that never surface again. The feature must return "unknown" for
   these rather than a confident point.
9. **Coastal/shelf and equatorial bands** (much of the INCOIS fleet's operating area) are the
   hardest: strong tidal/wave drift, shallow bathymetry, grounding risk, geostrophic assumption
   breakdown, and sharp gradients.
10. **Small local fleet.** Calibration sample sizes must be stated in the UI; pooling regions is
   necessary and must be disclosed.

---

## G. Recommended uncertainty method

**Ensemble + empirically calibrated radii (hybrid probabilistic output).**

1. **Members (≈ 100–500):** sample starting position (Argos vs GPS error class), parking depth
   (per-cycle value ± its observed spread, else ±50–100 dbar), phase durations (observed per-float
   medians or `CONFIG_*`), current-field error (perturbation/OU noise using model-vs-observed current
   differences — calibrated, not guessed), surface-drift window, and a random-walk sub-grid
   displacement whose diffusivity is fitted to Stage-1 hindcast residuals.
2. **Output uncertainty from residuals, not from ensemble spread alone:** on the hindcast corpus,
   compute great-circle residuals of the final predictor as a function of lead time and region;
   derive **50 % and 90 % containment radii** by quantile regression (or empirical quantiles with a
   minimum sample-size guard). Cross-check that the ensemble spread is consistent with these radii
   (rank histogram / coverage test). **This part is already validated for Stage 0** (Table C7):
   radii computed on a *different* float than the one they are applied to covered 51.5 % / 89.4 %
   of held-out cases (nominal 50 / 90), across 25 float × stratum blocks and 3,199 cases; adding
   cycle class to the region key did not materially change transfer (51.9 % / 89.7 % at the
   tail-optimised weight). So the radii are transferable *within* these regions — but the study also
   shows why a single fleet-wide circle is not: the same nominal 90 % radius ranges from ~51 km
   (Argos, Arabian Sea) to ~146 km (Bay of Bengal / South Indian Ocean).
3. **Expose, per prediction:** predicted lat/lon, target time, 50 % and 90 % radius, method tag
   (`persistence+prior`, `lagrangian-cmems-glo12`), input fingerprints, calibration sample size and
   period, and a plain-language caveat. Isotropic circles are acceptable for the MVP; add
   anisotropy only if residuals show it.
4. **Refuse to invent:** if the source is unavailable, credentials are missing, the float has <2
   QC'd cycles, the last fix is stale beyond the calibration range, or the calibration set is too
   small, return `insufficient_data` / `source_unavailable` and show the reason. "No prediction" is a
   valid, honest output — mirroring the existing rule that missing data is never substituted.

---

## H. Proposed decoder-ui architecture (proposal only — nothing implemented)

**Server side (new, read-only, isolated from the monitor):**

```
decoder-ui/service/prediction/
  trajectory_source.py   # fetch+cache _Rtraj.nc/_meta.nc, QC filter, freeze fingerprints
  schedule.py            # observed cycle schedule; falls back to CONFIG_* then +10 d convention
  currents.py            # provider interface: cmems_glo12 | glorys12_backtest | prior_only | none
  advect.py              # Lagrangian integrator (parked / ascent / surface phases)
  ensemble.py            # member generation, radii, coverage diagnostics
  calibrate.py           # residual store + quantile radii per region x cycle class x fallback rung
  predict.py             # facade → payload {position, time, radii, method, provenance, status}
  residuals.json         # local calibration archive (built from our own hindcasts)
```

* **API:** `GET /api/floats/{wmo}/next-location` (read-only, cached) + optional `POST …/refresh`;
  response carries `status ∈ {ok, insufficient_data, source_unavailable, stale}`, provenance
  (files + checksums + model product ids), and the calibration reference.
* **Response shape is already prototyped and checked** against three real floats —
  `stage0-demo-records.json` (`stage0_demo.py`): `predicted_position`, `target_time_utc`,
  `uncertainty{r50_km, r90_km, calibration_cases, calibration_basis}`, `method`, `fallback_rung`,
  `prior_neighbours_within_2deg_1month`, `provenance{file, sha256, predictor, prior_lag_days}`.
  Used as the design contract: nothing in it requires a product change to evaluate.
* **Reuse:** the existing GDAC access layer, `fleet_status.py`'s QC conventions and cache discipline,
  and the current `Expected Next Profile` computation as the target *time*.
* **UI:** a "NEXT SURFACING (PREDICTED)" block inside the existing Float Status detail drawer, plus an
  optional map layer (default OFF, distinct symbol + uncertainty circle), always labelled
  `Experimental prediction — not a communication signal`, with method, radius and calibration
  provenance one click away. No change to the metrics row, table columns, statuses, statuses'
  thresholds, or banned/approved wording.
* **Configuration:** CMEMS credentials via environment variables (never committed; same rule as the
  existing SMTP handling). No credentials → Stage 0 only, clearly labelled.
* **Cost/limits:** prediction refresh piggybacks on the existing sync cadence; no new browser-side
  network calls; no new background thread beyond the monitor's existing loop.
* **Non-goals:** no change to `src/argo_decoder/`, no substitution of local coordinates, no change to
  profile-recency or fleet-status semantics, no automatic alerting on predictions.

---

## I. Validation against historical floats

**Corpus.** All 30 workstation floats with `_Rtraj.nc` histories; back-test every cycle with ≥2
preceding QC'd cycles (thousands of prediction cases), replaying the real information state at each
cycle. GLORYS12V1 (not forecasts) supplies historical currents for reproducibility.

**Metrics (per float and pooled, with sample counts):**

* great-circle error (km) — median, mean, RMSE, p90 (the metric family already used in this project
  for positions);
* hit-rate: fraction within 25 / 50 / 100 km;
* skill score vs the strongest baseline (B0/B1/B2) at identical cases;
* error vs lead time (1–10+ days), and vs cycle length (5 d vs 10 d classes);
* reliability: empirical coverage of the 50 %/90 % intervals (target within binomial error);
* stratified by telemetry (Argos vs Iridium), platform type, region (Arabian Sea / Bay of Bengal /
  equatorial / southern Indian Ocean), and QC mix;
* *failures honestly reported*: floats that grounded/beached or stopped transmitting — the model is
  expected to fail there, and the product must say "unknown" rather than absorb them into skill.

**Acceptance gates for shipping (to be agreed before implementation):**

| Gate | Requirement |
| --- | --- |
| Stage 0 | shipped only with the Appendix C radii; must reproduce the measured skill on the same corpus |
| Stage 1 | beats the measured Stage-0 blend (median 21.5 km, p90 90.2 km, 3,276 like-for-like cases) — e.g. ≥10 % lower median with a 95 % bootstrap CI excluding zero — in at least two of the four regions, or improves p90 without degrading the median |
| Uncertainty | observed coverage within ±5 percentage points of nominal for both 50 % and 90 % radii |
| Robustness | no systematic lon/lat bias; refusal paths exercised (missing files, credentials absent, single-cycle floats) |
| Reproducibility | every prediction reproducible from stored input fingerprints; the monitor's own tests unchanged |

**This protocol is already running for Stage 0 (Appendix C).** Implemented as
`backtest_baselines.py` (prospective predictors) and `backtest_robustness.py` (delivery-lag
sensitivity, paired bootstrap CIs, leave-one-float-out weight selection and calibration, horizon
decay). Results are stored as CSVs next to this document, so any later Stage-1 claim can be checked
against the same cases. Still to add before Stage 1: a *temporal* split (train on cycles before a
cut-off date, test after) in addition to the leave-one-float-out split, and a live forward test in
which each prediction is logged before the next profile arrives.

**Forward test plan (small, honest, no new services).** For each float, when a new cycle is decoded,
log one row: predicted vs observed position, predicted vs observed time, method tag and weight,
radii, and the fingerprint of every input. After ~3 months (≈9 cycles per decadal float) score it
per float; that gives the first numbers that are *not* retrospective.

**Artefacts:** per-cycle residual table, skill-by-stratum table, reliability diagrams, the frozen
configuration used, and the exact GDAC/product file checksums — all archived like the earlier audits.

---

## J. Verdict: baseline-only vs physics vs ML vs hybrid

* **Baseline-only (the calibrated blend) is a legitimate MVP, and I no longer describe it as
  insufficient by construction** — measured, it beats persistence on the median by ~29 % and is
  already calibrated. What it cannot do is (a) represent the parked-phase current structure
  explicitly, (b) use a forecast that extends beyond the last fix, or (c) stay useful past one cycle
  (Table C8), and its prior abstains in a third of cases. So it is the floor, not the ceiling.
* **Physics/Lagrangian alone** is the best *single* method available today and is defensible, but a
  deterministic trajectory over-states confidence; it must ship as an ensemble with calibrated radii.
* **ML-first is rejected.** With ~10³ local cycles, high spatial autocorrelation, and a strong
  temptation toward leakage, ML cannot currently be justified ahead of a physics baseline; published
  deep-learning results are not transferable evidence for this fleet. ML is worth attempting only as
  a residual corrector, and only if it clears the pre-registered margin.
* **Recommended: staged hybrid.** Stage 0 — concretely the LOFO-validated blend (0.8 × last observed
  displacement + 0.2 × leakage-safe regional-seasonal prior, radii calibrated per region × cycle
  class × fallback rung on other floats) as the always-available MVP → Stage 1 (CMEMS-driven
  Lagrangian ensemble, calibrated radii) as the main method → Stage 2 (ML residual correction)
  conditional on out-of-sample gains. Every stage is validated by the same protocol, and the UI always
  discloses which method produced a prediction.
* **What would change this verdict:** (i) if CMEMS access is impossible *and* INCOIS fields are also
  unavailable, Stage 0 is the ceiling and the feature should be scoped as "expected landing zone",
  not "trajectory prediction"; (ii) if Stage 1 fails to beat median 20.1 km / p90 98.1 km on the same
  corpus with a CI excluding zero, it should be dropped rather than shipped as decoration;
  (iii) if the forward-test log (Section I) shows the 50 % radius under-covering systematically, the
  calibration — not the predictor — is the thing to fix first.

**Suggested decision points for you:** (1) approve the staged hybrid and Stage 0/1 scope; (2) decide
whether the workstation may hold CMEMS credentials (this is the single biggest capability gate);
(3) confirm whether INCOIS HOOFS/OSF or SARAT fields should be a required comparison rather than an
optional one; (4) confirm that "prediction unavailable" is acceptable in the UI (my recommendation:
yes, always).

---

## K. Sources and references

**Argo data model and timing**
1. Argo cycle timing variables (DST/DET/PST/PET/AST/AET/TST/TET and measurement codes) — https://argo.ucsd.edu/how-do-floats-work/argo-cycle-timing-variables/
2. Argo trajectory file access and variable listing (Rtraj, JULD_* phase variables, REPRESENTATIVE_PARK_PRESSURE) — https://euroargodev.github.io/argoonlineschool/Lessons/L03_UsingArgoData/Chapter32d_ArgoDatabyFloat_Traj.html
3. Argo trajectory data description (measurement codes, drift pressure extraction, meta parking depth) — https://www.argo.org.cn/uploadfile/2024/0614/20240614094941254.pdf
4. Verification performed for this report: downloaded `_Rtraj.nc`/`_meta.nc` for 1902844, 2902086, 2902203, 2902223 from `https://data-argo.ifremer.fr/dac/incois/<WMO>/` (SHA-256 in Appendix A).

**Ocean current sources**
5. CMEMS `GLOBAL_ANALYSISFORECAST_PHY_001_024` Product User Manual (1/12°, 50 levels, 10-day forecast updated daily, hourly surface fields, SMOC surface merged current incl. wave and tidal drift) — https://documentation.marine.copernicus.eu/PUM/CMEMS-GLO-PUM-001-024.pdf ; product page — https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_PHY_001_024/description
6. CMEMS `GLOBAL_MULTIYEAR_PHY_001_030` GLORYS12V1 reanalysis (1/12°, 1993→present, daily 3-D currents) — https://sextant.ifremer.fr/geonetwork/srv/api/records/c0635fc4-07d3-4309-9d55-cfd3e6aa788b (PUM: https://www.mercator-ocean.eu/wp-content/uploads/2017/06/CMEMS-GLO-PUM-001-030.pdf)
7. DUACS sea-level products (L4 NRT 008_046 / MY 008_047, 0.125° daily, `ugos`/`vgos`; effective-resolution caveat) — https://documentation.marine.copernicus.eu/QUID/CMEMS-SL-QUID-008-032-068.pdf
8. NASA OSCAR surface currents (top ~30 m; geostrophic + wind + thermal wind; DUACS-based) — https://www.esr.org/data-products/oscar/oscar-surface-currents/
9. Scripps Argo trajectory-based velocity product (parking-depth absolute velocities; comparison with ANDRO/YoMaHa) — Zilberman, Scanderbeg, Gray & Oke (2023) — https://repository.library.noaa.gov/view/noaa/60521/noaa_60521_DS1.pdf
10. YoMaHa'07 velocity dataset (parking level and surface; error estimates) — https://apdrc.soest.hawaii.edu/projects/yomaha/
11. ANDRO: an Argo-based deep displacement dataset (parking-pressure velocity, shear/surface-fix-delay treatment) — https://www.researchgate.net/publication/244484160_ANDRO_An_Argo-based_deep_displacement_dataset

**Prediction methods and literature**
12. Chamberlain et al. (2023), *Using Existing Argo Trajectories to Statistically Predict Future Float Positions with a Transition Matrix*, JTECH 40(9) — https://journals.ametsoc.org/view/journals/atot/40/9/JTECH-D-22-0070.1.xml (ARGONE/Argovis product; 2°×2°, 90-day step; Argos vs Iridium surface displacement)
13. Taillandier & co., *On the assessment of Argo float trajectory assimilation in the Mediterranean Forecasting System* (5-day trajectory forecasts from model velocities; ≈15 % improvement with assimilation) — https://link.springer.com/article/10.1007/s10236-011-0437-0
14. Ning et al. (2024), *Argo Buoy Trajectory Prediction: Multi-Scale Ocean Driving Factors and Time–Space Attention Mechanism*, JMSE 12(2):323 — https://doi.org/10.3390/jmse12020323
15. Özgökmen et al. (2000), *On the Predictability of Lagrangian Trajectories in the Ocean*, JTECH 17(3) — https://journals.ametsoc.org/view/journals/atot/17/3/1520-0426_2000_017_0366_otpolt_2_0_co_2.xml
16. Lagrangian predictability assessments (separation ~15 km after 24 h; 4–25 km/day growth; regional dt dependence) — https://www.sciencedirect.com/science/article/abs/pii/S1463500310001654 and https://www.sciencedirect.com/science/article/abs/pii/S0924796301000082
17. *Dynamical systems theory approach in oceanography* (2025 review; predictability horizon ≈3–10 days for FTLE 0.1–0.3) — https://www.frontiersin.org/journals/marine-science/articles/10.3389/fmars.2025.1621820/full
18. ORCAst (2025), *Operational High-Resolution Current Forecasts* — AI-based current forecasting as a future input upgrade — https://journals.ametsoc.org/view/journals/aies/4/4/AIES-D-25-0002.1.xml

**INCOIS capability and data services**
19. INCOIS ocean-state forecasting systems (HOOFS/INDOFOS: ROMS, 1/4° basin / coastal, currents to +5 days; RAIN/LETKF assimilation of Argo profiles) — https://oceanpredict.org/science/operational-ocean-forecasting-systems/system-descriptions/ and https://www.researchgate.net/publication/359564021_HOOFS_The_Operational_Ocean_Forecast_System_of_India
20. INCOIS search-and-rescue drift tool SARAT / SARAT 2 (drift of objects from currents, winds, waves — the closest existing INCOIS capability to float drift prediction) — https://currentaffairs.adda247.com/incois-upgrades-sarat-for-enhanced-sea-rescue-operations/
21. INCOIS Argo services (Web-GIS with trajectories, ERDDAP `Indian_ARGO_Floats`, Live Access Server, Argo Regional Centre for the Indian Ocean) — India national reports to the Argo Steering Team: https://argo.ucsd.edu/wp-content/uploads/sites/361/2025/04/India_NatRep_AST26.pdf and https://datascience.codata.org/articles/10.5334/dsj-2018-011
    → **No public evidence was found that INCOIS operates a next-profile/surfacing-position prediction service for Argo floats.** The nearest capabilities are SARAT (drifting-object prediction) and HOOFS/OSF (current forecasts). This should be confirmed directly with the INCOIS Argo/OSF teams before any claim is made in documentation.

---

## Appendix A — measured statistics and reproducibility

Full table: `measured-cycle-statistics.csv` (same directory). Source files and SHA-256:
`evidence-file-hashes.tsv`. Method: for each float, take satellite-fix records
(`MEASUREMENT_CODE == 703`), keep the first fix per `CYCLE_NUMBER`, sort by JULD, then compute
great-circle separation and time difference between consecutive fixes (cycles with Δt ≤ 30 d);
phase durations from the `N_CYCLE` timing variables; programme parameters from `CONFIG_*` in
`_meta.nc`. The same Rtraj files supply the schedule/park-depth chain used by the design.

Reproduce with:

```bash
curl -sO https://data-argo.ifremer.fr/dac/incois/2902223/2902223_Rtraj.nc
curl -sO https://data-argo.ifremer.fr/dac/incois/2902223/2902223_meta.nc
# then read with netCDF4 (same library the workstation already depends on)
```

**Caveat:** inter-cycle displacement mixes parked drift, descent/ascent and surface drift — that is
precisely why the predictor must model the phases separately (Section H) and why the error budget in
Section F is stated as an expectation to be tested.

## Appendix B — open questions for INCOIS before implementation

1. May the workstation hold CMEMS credentials (or is a local mirror/cache of GLO12 + GLORYS12V1 to be
   provided)? Without this, only Stage 0 is possible.
2. Is there an in-house preference or requirement to use HOOFS/OSF currents and/or SARAT's drift
   engine for this feature?
3. What float populations should the calibration cover — the 30 workstation floats only, or the full
   Indian Ocean DAC holdings?
4. Which consumers will see the prediction (operations desk vs research), and what action would they
   take on it? This sets how conservative the uncertainty display must be.
5. Should predictions be archived/reported like the daily fleet reports, and with what retention?

---

## Appendix C — measured Stage-0 hindcast on the workstation fleet (completed after the main draft)

**Corpus.** All 30 floats of the current workstation fleet; `_Rtraj.nc` downloaded from
`data-argo.ifremer.fr/dac/incois/<WMO>/` on 2026-09-21 (SHA-256 list:
`evidence-trajectory-hashes.tsv`, 30/30 HTTP 200, 107 MB). 30 floats had ≥3 usable cycles; one float
contributed no scorable cases. 5,187 prediction cases were formed (mean ≈ 179 per float).

**Protocol (leakage-safe by construction).** A case is cycle *N* → *N+1* for a float. Only
information timestamped at or before the cycle-N fix may enter the predictor:

* positions: satellite fixes (`MEASUREMENT_CODE == 703`), first fix per cycle, `POSITION_QC ∈ {1,2}`;
* the drift **prior** for a case is the median displacement of all cycles whose *start* time is
  strictly earlier than t(N) and whose start position lies within ±2° / ±1 month of the case;
  at least 5 such neighbours are required, otherwise the prior predictor abstains;
* no cycle N+1 quantity (position, existence, timing) is ever read. Metrics are computed only
  against the real cycle N+1 fix, and cases with >30 d gaps are dropped.

**Table C1 — like-for-like comparison (3,276 cases in which every predictor produced a value)**

| predictor | median (km) | mean (km) | RMSE (km) | p90 (km) | ≤25 km | ≤50 km | ≤100 km | skill vs B0 (median) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B0 persistence | 28.1 | 42.5 | 67.6 | 82.7 | 43.1 % | 78.6 % | 92.5 % | — |
| B1 last displacement (constant velocity) | 21.5 | 47.8 | 95.9 | 111.4 | 57.0 % | 79.5 % | 88.8 % | +23.7 % |
| B2 mean of last 3 displacements | 24.0 | 43.9 | 78.6 | 96.7 | 51.9 % | 78.3 % | 90.4 % | +14.6 % |
| B3 regional-seasonal prior | 27.7 | 42.2 | 67.7 | 83.9 | 45.1 % | 78.8 % | 92.3 % | +1.5 % |
| B4 half-strength prior | 27.0 | 41.4 | 66.9 | 81.9 | 45.8 % | 79.3 % | 92.5 % | +4.0 % |
| **B5 blend (0.5 × last displacement + 0.5 × prior)** | **21.5** | **41.3** | 76.7 | 90.2 | **57.1 %** | **81.7 %** | 91.0 % | **+23.5 %** |

**Table C2 — all cases (5,187 for B0–B2; the prior predictors abstain when no neighbourhood exists)**

| predictor | n | median | mean | RMSE | p90 | median time error |
| --- | --- | --- | --- | --- | --- | --- |
| B0 persistence | 5,187 | 37.3 | 60.9 | 90.9 | 143.1 | 0.01 d |
| B1 last displacement | 5,187 | 30.5 | 70.6 | 126.4 | 180.7 | 0.01 d |
| B2 mean of last 3 | 5,187 | 34.6 | 74.2 | 270.9 | 162.8 | 0.01 d |
| B3 prior | 3,276 | 27.7 | 42.2 | 67.7 | 83.9 | 0.01 d |
| B4 half prior | 3,276 | 27.0 | 41.4 | 66.9 | 81.9 | 0.01 d |
| B5 blend | 3,276 | 21.5 | 41.3 | 76.7 | 90.2 | 0.01 d |

**Table C3 — by region (median / p90 km, and 50 km hit-rate, B5)**

| region | cases (B0) | B0 median / p90 | B1 median / p90 | B5 median / p90 | B5 ≤50 km |
| --- | --- | --- | --- | --- | --- |
| Arabian Sea (approx) | 2,199 | 29.5 / 63.4 | 21.9 / 75.4 | 21.6 / **55.5** | 87.6 % |
| Bay of Bengal (approx) | 908 | 21.5 / 118.4 | 16.7 / 227.2 | 17.0 / 146.4 | 77.7 % |
| Equatorial Indian (10°S–0°) | 319 | 60.9 / 153.9 | 48.9 / 206.2 | 40.3 / 130.3 | 60.6 % |
| South Indian Ocean (≤10°S) | 1,761 | 72.2 / 187.2 | 70.8 / 231.1 | 35.9 / 146.1 | 63.4 % |

(For the Bay of Bengal the tail-minimising variant is B4: 19.8 km median / 103.2 km p90.)

**Table C4 — by telemetry class (B5)**

| class | cases (B0) | B0 median / p90 | B5 median / p90 | B5 ≤50 km |
| --- | --- | --- | --- | --- |
| ARGOS (APEX) | 2,465 | 38.8 / 133.4 | 20.6 / **51.4** | 89.5 % |
| IRIDIUM_SBD (ARVOR / PROVOR_III) | 2,722 | 35.8 / 155.1 | 22.7 / 135.9 | 75.6 % |

**What this changes in the design**

1. **Constant-velocity extrapolation alone is unsafe.** It wins the median (+23.7 %) but its tail is
   worse than doing nothing (Bay of Bengal p90 227 km vs 118 km) — a textbook signature of chaotic
   advection. Reported as a point estimate without an inflated radius it would over-promise.
2. **Blending with a leakage-safe regional prior is the best Stage-0 predictor**, with one honest
   nuance added by the bootstrap (Table C6): the 0.5/0.5 blend *ties* constant velocity on the median
   (+0.05 km, CI includes zero) and is clearly better on mean error, p90 and the ≤50 km hit-rate;
   at w = 0.2 it is better on every metric (20.1 km median held-out). Unlike constant velocity, the
   blend never has a tail worse than persistence. This is the concrete Stage-0 recipe.
3. **Uncertainty must be regional and telemetry-aware**: 90 % radii of ~51–56 km (Argos, Arabian Sea)
   versus ~130–146 km (equatorial and southern Indian Ocean) are a factor of ~3 apart; one fleet-wide
   circle would be dishonest in both directions.
4. **Prior coverage is a real constraint**: 37 % of cases had no ≥5-cycle neighbourhood, so the
   product needs an explicit fallback ladder (blend → last displacement → persistence) that widens the
   radius at each step, and must say which rung produced the number.
5. **Timing is effectively deterministic** (median error 0.01 d; 0.10 d for Argos) — the existing
   "+10 d Expected Next" convention is sound as the target time; the *position* is the hard part.
6. **The Stage-1 physics target is now explicit**: beat median 21.5 km / p90 90.2 km on this corpus
   (3,276 like-for-like cases) before it can be called an improvement.

**Caveats (must be carried into any product text)**

* These are one-cycle (~5–10 d) leads only; nothing here validates longer horizons.
* Positions are the *published* Rtraj values, i.e. possibly after delayed-mode revision — production
  features must use the version available at prediction time.
* The prior uses older cycles with `t < t(N)` but assumes immediate availability; a production run
  should apply a conservative ≈48 h GDAC delivery lag (`t < t(N) − 2 d`) and re-measure.
* Two of the four APEX floats report fill in `REPRESENTATIVE_PARK_PRESSURE`, and one float's
  `CONFIG_CycleTime_hours` disagrees with its observed cycle — both facts are handled by using
  observations first (Section 2.1).
* The corpus contains 29 score-able floats; per-region sample sizes (Table C3) are small for the
  equatorial basin and should be quoted in the UI.

* **Cycle length matters as much as region.** Decadal cycles (≈10 d): B5 median 23.4 km / p90 73.9 km.
  Short cycles (≤7 d, i.e. the 5-day PROVOR floats): B5 median 16.6 km but p90 158.5 km — shorter
  cycles buy a smaller median, not smaller tails, because those floats operate in the more variable
  equatorial/southern domains. Calibration must therefore be region **and** cycle-class aware.
* **Attribution caveat.** Five long-record APEX floats contribute ≈49 % of the B5 cases and only 11
  floats provide ≥100 cases each, so the pooled numbers are weighted toward the Arabian Sea/equatorial
  APEX fleet. Per-float B5 medians span 15.4 km (2902114, n=280) to 115.8 km (2902223, n=13 — too few
  cases here for a per-float radius). Use per-float calibration where n is adequate and pooled
  region/telemetry radii otherwise, and display the sample size.

**Reproduce:**

```bash
python backtest_baselines.py <traj_dir> <out_dir> <presets.json>
# outputs: baseline-skill-{overall,common-subset,by-region,by-telemetry,by-cycle-class,by-float}.csv
# note: the 'skill' column on baseline-skill-overall.csv is not like-for-like; use
#       baseline-skill-common-subset.csv (3,276 cases) for predictor-vs-predictor claims.
python backtest_robustness.py <traj_dir> <out_dir> <presets.json>
# outputs: robustness-{lag-sensitivity,bootstrap-ci,blend-weight-lofo,calibration-lofo-*,
#          horizon}.csv  (Tables C5–C8)
```

### Appendix C addendum — robustness, calibration transfer and horizon decay

Run after the tables above, on the same corpus and the same leakage rules:
`backtest_robustness.py` (input fingerprints unchanged — `evidence-trajectory-hashes.tsv`).

**Table C5 — delivery-lag sensitivity of the prior pool** (prior neighbourhood restricted to cycles
starting before `t(N) − L`). The product can therefore adopt a conservative 48 h GDAC delivery lag at
no measurable cost.

| prior lag L | prior coverage | blend w=0.5 median | blend w=0.5 p90 | hit ≤50 km |
| --- | --- | --- | --- | --- |
| 0 d (idealised) | 63 % | 21.5 km | 90.2 km | 81.7 % |
| 2 d | 63 % | 21.6 km | 90.1 km | 81.7 % |
| 5 d | 62 % | 21.8 km | 89.6 km | 81.6 % |
| 7 d | 61 % | 21.9 km | 89.1 km | 81.7 % |

**Table C6 — paired bootstrap (10,000 resamples, 3,276 common cases) and blend-weight study.**
Positive = worse than the reference.

| comparison | median difference (95 % CI) | p90 difference (95 % CI) |
| --- | --- | --- |
| blend w=0.5 − persistence | −6.62 km [−7.38, −5.64] | +7.49 km [+1.73, +13.41] |
| blend w=0.5 − constant velocity | +0.05 km [−0.70, +0.87] | −21.20 km [−28.40, −14.06] |
| constant velocity − persistence | −6.68 km [−7.77, −5.48] | +28.69 km [+19.45, +38.56] |

Reading: the 0.5/0.5 blend is **statistically indistinguishable from constant velocity on the median
and decisively better in the tail**, and it beats persistence on the median. Constant velocity's tail
penalty is real and significant — which is why it is not shipped alone.

Blend weight sweep (fraction given to the prior), 3,276 cases: median is flat-to-best around
w = 0.2–0.3 (20.3–20.4 km) while p90 keeps improving with w (106 km at w=0.1 down to ~82 km at
w = 0.8). Leave-one-float-out selection chose **w = 0.2 for all 18 eligible floats**, giving
**20.1 km median / 98.1 km p90 on held-out data** (3,199 cases). The weight is therefore a *risk
preference*, not a fitted constant: w ≈ 0.2 for "most likely landing point", w ≈ 0.7 for the smallest
90 % search area (23.6 km median / 82.4 km p90).

**Table C7 — calibration transfer (leave-one-float-out radii).** Radii are estimated from other
floats in the same stratum and applied to the held-out float, then coverage is measured.

| stratification | weight | nominal 50 % → empirical | nominal 90 % → empirical |
| --- | --- | --- | --- |
| region × cycle class | 0.2 | 51.5 % | 89.4 % |
| region | 0.2 | 50.7 % | 89.6 % |
| region × cycle class | 0.5 | 51.9 % | 89.7 % |
| region | 0.5 | 51.3 % | 90.0 % |

**Table C8 — horizon decay** (the same step vector applied h times; every intermediate hop required
to be a real, ≤30 d interval; leads are the median observed).

| horizon | median lead | persistence | constant velocity ×h | prior ×h | blend w=0.5 ×h |
| --- | --- | --- | --- | --- | --- |
| 1 cycle | 10.0 d | 37.3 / 143.1 | 30.5 / 182.1 | 27.5 / 83.7 | **21.5 / 90.1** |
| 2 cycles | 20.0 d | 66.1 / 209.4 | 68.4 / 316.8 | 51.1 / 132.6 | **43.6 / 151.5** |
| 3 cycles | 30.0 d | 89.9 / 265.2 | 109.4 / 444.7 | 73.6 / 177.5 | **66.6 / 210.4** |

(cells: median km / p90 km). The blend remains the best predictor at every horizon, but its error
roughly doubles from 1 to 2 cycles and triples by 3 — consistent with the published 3–10 day
predictability horizon (Section 2 of F). **Product policy: one cycle supported, two cycles indicative
only, three or more refused.**

**Table C9 — corpus coverage caveat.** 30 floats pass the "≥3 QC'd cycles" test, but 2902113 has only
three QC'd cycles for 21 satellite-fix records (sparse Argos transmission), so no cycle transition can
be scored: the scorable fleet is 29 floats. A further reduction applies per predictor — the prior is
available in only 63 % of the 5,187 cases. Any UI string must quote the sample actually behind the
radius, not the fleet size.

**Robustness summary (what still needs care):**

* weight selection and both calibration studies were run on this same corpus; LOFO removes per-float
  overfitting, not corpus-level selection, so the honest statement is "validated by leave-one-float-out
  on 22–25 float × stratum blocks", not "independently validated";
* only 11 floats contribute ≥100 prior-bearing cases each, and five long-record APEX floats supply
  ≈49 % of them — pooled numbers are weighted toward the Arabian Sea / equatorial APEX fleet;
* retrospective positions are published (possibly delayed-mode-revised) values; production must use
  the version available at prediction time, which the forward-test logging (Section I) will measure;
* the 90 % radii above 100 km are a *warning*, not a product: quoting them honestly is what keeps the
  feature scientifically defensible in the Bay of Bengal and the southern Indian Ocean.

**Table C10 — as-if-live demonstration (`stage0_demo.py`, `stage0-demo-as-if-live.csv`,
`stage0-demo-records.json`).** For each of the 29 scorable floats, the *last* observed cycle was
predicted from the previous one using the recommended recipe (blend w_prior = 0.2, 2-day delivery
lag) with radii calibrated on **all other floats** and conditioned on the fallback rung actually
used. This is a format demonstration and a deliberately unfavourable sample, not the validation
corpus (the last cycle of each float is one case, and half of them need the fallback rung).

| group | n floats | median err | p90 err | ≤50 km |
| --- | --- | --- | --- | --- |
| blend rung (prior available) | 14 | 41.9 km | 157.2 km | 50 % |
| fallback rung (last displacement only) | 15 | 70.5 km | 201.3 km | 47 % |
| all | 29 | 50.6 km | 175.9 km | 48 % |

Containment on this sample: 50 % radius → 31 % of 29 floats; 90 % radius → 86 % of 29. Median
target-time error 0.02 d.

**Two design lessons this demo produced (both folded into the recommendation):**

1. **Radii must be conditioned on the fallback rung, not just the region.** The two rungs have
   materially different residual scales (p90 157 km vs 201 km here; 90 km vs 181 km pooled in
   Table C2). A single per-region radius is simultaneously inflated for blend cases and too small
   for fallback cases. The demo therefore widens the fallback chain explicitly —
   *region × cycle class × rung* → *region × rung* → *region, rungs pooled* — and records which basis
   was used (`calibration_basis` in the JSON), so the UI can state the provenance of the circle.
2. **Small-sample honesty.** On this 29-case sample the 50 % radius covered 31 % of floats. With
   n = 29 the 95 % binomial interval spans roughly 17–50 %, so this is *not* evidence of
   miscalibration — but it is a warning against freezing radii. The forward-test log in Section I is
   what keeps them honest, and every UI string must quote the sample actually behind the radius
   (e.g. "n = 264 calibration cases from 22 other floats").

**Face validity of the output format (three contrasting floats, from the JSON record):**

* **2902086** (PROVOR_III, Iridium, 5-day cycle, Bay of Bengal): predicted +/− 15.6 / 179.1 km
  (n = 264, region × cycle class × rung) — actual error 50.6 km, inside the 90 % circle.
* **2902223** (APEX, Argos, 10-day cycle, southern Indian Ocean): prior unavailable → fallback rung,
  predicted +/− 72.5 / 231.2 km (n = 1,269) — actual error 70.5 km, inside both circles. The wide
  circle is the honest answer for a fast-drifting float with no regional neighbourhood.
* **1902844** (ARVOR, Iridium, equatorial Indian Ocean): predicted +/− 46.8 / 206.7 km
  (n = 273, rungs pooled) — actual error 148.9 km: a genuine large miss, inside the 90 % circle and
  outside the 50 % one, i.e. exactly the behaviour a calibrated uncertainty should show.
