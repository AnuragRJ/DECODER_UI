# Stage-1 — cycle-scale next-surface prediction: evidence report

**Status: implemented, evaluated, and NOT shipped.** Stage 0 remains the shipped
Predictor (`PREDICTION_CYCLE_STEP=off`). Stage 1 lives behind that switch with its
own calibration artefact, its own provenance on every payload, and a pre-registered
ship gate that it failed. This report is the complete record: audit, method,
comparison, calibration, fallbacks, leakage evidence, ship decision, files and tests.

* Repo: `/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui` (uncommitted change set)
* Corpus: 30 public Ifremer/Argo `_Rtraj.nc` files (`dac/incois/<WMO>_Rtraj.nc`), 111.1 MB, refetched this session
* Baseline artefact: `data/fleet_status/prediction_calibration.json` — **unchanged** (42,481 B, Stage-0)
* Stage-1 artefact: `data/fleet_status/prediction_calibration_stage1.json` (45,798 B, candidate, not loaded unless Stage-1 is switched on)
* No `src/argo_decoder/` file was touched. No ML. No current provider. No Float Status semantics changed.

---

## 0. Read-only audit of the Stage-0 predictor (required first step)

`prediction-validation/audit/stage1_audit.py` →
`audit/stage1_audit.json` + `audit/stage1_audit_summary.json`. 5,265 issuing fixes
across 30 floats; no file was modified.

**(1) Last-transition duration / expected-cycle interval.** Median 1.000 × the
interval (p10 0.992, p90 1.007) — the corpus is regular at the median, so any
correction can only act on the tails. Histogram of the ratio: 207 hops in
(0, 0.25], 3 in (0.25, 0.5], 2 in (0.5, 0.75], 2,433 in (0.75, 1], 2,596 in
(1, 1.25], 0 in (1.25, 1.5], 7 in (1.5, 2], 8 in (2, 3], 4 in (3, 5], 5 above 5
(max 36.03 ×). 4.0 % of hops are shorter than 0.25 × the expected interval: bursts
are real but rare, and they are clustered by float.

**(2) Floats whose newest transition is sub-cycle (< 0.5 × interval).** 2 of 30:
`2902089` (0.737 d = 0.147 × its 4.998 d interval) and `2902113` (0.5 d = 0.05 ×
its 10.0 d interval). These are the floats where Stage 0 would apply a fraction of
a cycle as a whole cycle.

**(3) Floats whose newest transition spans multiple cycles (> 1.5 × interval).**
1 of 30: `2902091` (10.03 d = 10.03 × its 1.0 d interval). 27 floats are
cycle-scale at the newest hop.

**(4) Effect of using the current last-transition displacement (Stage-0 replay).**
Chronological replay, n = 5,265: median 30.2 km, mean 84.6, p90 182.8, RMSE 273.3,
hit ≤25 km 43.5 %, ≤50 km 64.8 %, ≤100 km 79.3 %. Split by the class of the hop
that produced the step:

| hop class | n | median | mean | p90 | RMSE | hit ≤25 km |
|---|---|---|---|---|---|---|
| sub_cycle | 210 | 13.0 | 241.8 | 445.3 | **892.0** | 68.6 % |
| cycle_scale | 5,031 | 30.8 | 77.0 | 178.3 | 206.7 | 42.6 % |
| multi_cycle | 24 | 59.9 | 302.2 | 1,119.8 | **683.0** | 12.5 % |

The tail — not the bulk — is where the last-hop step misbehaves: 234 of 5,265 cases
carry the class-level RMSE blow-ups. Worst floats by median error: `2902113` 372.9 km,
`2902223` 101.5, `2902115` 94.9, `2902090` 86.7, `2902130` 84.4.

**(5) Available recent trajectory windows.** A cycle-scale window (span within
`[0.75, 1.25] ×` interval) exists at prediction time for **97.8 %** of cases
(5,150/5,265); a further 20 are normalisable multi-cycle spans (> 1.25 ≤ 3 cycles),
86 have only shorter-than-band history, and 9 have no window at all. 29 of 30
floats have at least one in-band window; the exception is `2902113`, whose cached
history is a single burst.

---

## A. Stage-0 vs Stage-1 accuracy (same cases, same protocol)

Methodology that matters for reading these numbers (each point is a fix in the
comparison):

* **Paired, deployment-faithful replay.** Stage 0 is replayed exactly as shipped:
  the newest *eligible* transition (hops > 30 d are mission gaps and are excluded by
  `features.build_transitions`) is the rung-4 step, blended with the regional/seasonal
  prior at the calibrated weight 0.2 when a prior exists; with no eligible transition
  it falls to the regional prior, then persistence. Stage 1 is replayed through the
  same ladder, substituting only the step, and **inherits the Stage-0 branch** when it
  has no window — so both columns are "what the service would have served".
* **Target-matched labels.** The label is the first fix with a later cycle number
  **and** ΔJULD ≥ 0.5 × the observed interval, within 2 intervals — the deployed
  forward-test rule. 151 of 5,222 candidate fixes have no such observation and are
  counted as unscoreable rather than scored against an interior burst.
* **Leakage-safe.** Case *i* sees only fixes at or before its own timestamp
  (`fixes[:i+1]`); the prior pool excludes the target float and lags its inputs by
  2.0 d.
* Chronological per float, leave-one-float-out prior pool, same corpus for both.

**Headline, paired on 5,071 cases / 29 floats:**

| method | n | median | mean | p90 | RMSE | hit ≤25 | ≤50 | ≤100 | R50 | R90 |
|---|---|---|---|---|---|---|---|---|---|---|
| **Stage-0 as served** | 5,071 | **30.1** | 86.6 | **180.1** | 421.6 | **43.6 %** | **64.3 %** | 79.4 % | 30.1 | 180.1 |
| Stage-1 as served | 5,071 | 30.9 | **81.2** | 181.4 | **301.5** | 42.3 % | 64.2 % | **79.5 %** | 30.9 | 181.4 |
| Stage-1 scoped variant (post-hoc) | 5,071 | 30.0 | 82.1 | 178.5 | 384.3 | 43.7 % | 64.8 % | 79.5 % | 30.0 | 178.5 |

*Stage-1 minus Stage-0:* median **−2.66 %** (worse), mean **+6.24 %**, p90
**−0.72 %** (worse), RMSE **+28.49 %**, hit ≤25 km **−1.3 pp**, ≤50 km −0.1 pp,
≤100 km +0.1 pp. Leave-one-float-out (29 folds) keeps the sign: median −3.05 %…−0.91 %,
p90 −2.05 %…−0.33 %, RMSE +25.35 %…+28.94 %.

**Where the two differ.** Both stages produce the same position (within 1 km) in
3,194 of 5,071 cases. Where the step actually changes they usually change *because*
an irregularity was present: 1,165 cases worse by > 1 km, 712 better by > 1 km,
median per-case change 0.0 km, best improvement **−7,681 km**, worst regression
**+454 km**. Read together with the case counts, Stage 1 trades a small systematic
loss in the bulk for a large reduction in catastrophic error: the RMSE gain comes
from ≤ 2 % of cases, and the loss comes from burst-influenced histories where the
small last hop is, empirically, the better estimator for these particular floats.

**Error by region (both methods, ALL cycle classes):**

| region | n | Stage-0 median / p90 / RMSE | Stage-1 median / p90 / RMSE |
|---|---|---|---|
| Arabian Sea | 2,174 | 20.8 / 73.2 / 270.6 | 21.9 / 76.4 / **246.9** |
| Bay of Bengal | 858 | 16.7 / 209.5 / **143.4** | 17.0 / 218.1 / 152.1 |
| Equatorial Indian | 315 | 49.8 / 222.3 / 1,475.0 | 49.8 / 220.1 / **924.9** |
| South Indian Ocean | 1,724 | 71.4 / 226.6 / 150.7 | **70.5** / 226.6 / 150.7 |

**Error by class of the hop that produced the step** (paired served series — this is
where the effect actually lives):

| hop class of the served case | n | Stage-0 median / p90 / RMSE | Stage-1 median / p90 / RMSE |
|---|---|---|---|
| cycle_scale (regular) | 4,964 | **29.6** / **176.9** / 355.8 | 30.6 / 180.4 / **261.8** |
| multi_cycle (gap) | 29 | 54.9 / 155.2 / 141.5 | **34.3** / **96.7** / **93.0** |
| sub_cycle (burst) | 78 | 61.5 / 2,655.6 / 1,868.4 | **45.2** / **717.4** / **1,242.2** |

Stage 1 is better on every irregular class (burst p90 2,655.6 → 717.4 km; gap median
54.9 → 34.3 km) and is *worse on the median and p90 of the regular class* while still
better on its RMSE — which is exactly why the pooled gate fails even though the step
model does what it was designed to do.

**Error by cycle class and region:** both served methods are broken out per
region × class (`ALL`, `short`, `decadal`) in
`prediction-validation/stage1_vs_stage0.csv` (201 rows: the two `served_*` blocks
plus the per-method diagnostic tables). Example, Arabian Sea · decadal:
Stage-0 n = 2,150 median 20.9 / p90 70.5 / RMSE 271.1 vs Stage-1 n = 2,150
median 21.9 / p90 75.4 / RMSE 247.1. In three of the four regions the decadal class
carries the cases, so the pooled table is not driven by a thin stratum.

**Variants and secondary protocol.** `cycle_window` (freshest in-band pair, using
the newest fix) beat the `median`-of-3-anchors variant on median error
(30.9 vs 37.5 km pooled, and in every region), which is why the window rule is the
configured Stage-1 mode. The normalisation-cap sweep (3 vs 10 cycles) changes 5 cases
and no conclusion. The legacy `i → i+1` protocol — scoring against the very next
published fix — is kept as a descriptive table in the JSON/CSV, but its rows are not
case-matched across stages (Stage-1 `cycle_window` n = 5,049: median 31.1 / mean 87.2
/ p90 181.9 / RMSE 357.7; Stage-0's no-prior `trajectory_extrapolation` subset
n = 2,932: 51.1 / 128.6 / 224.1 / 595.6), so the paired target-matched protocol above
is the comparison that decides the gate.

---

## B. Stage-1 sample counts

| quantity | count |
|---|---|
| candidate issuing fixes (all fixes with ≥ 2 predecessors) | 5,222 |
| scoreable cases (a target-matched observation exists) | **5,071** |
| unscoreable: no fix near the target time | 151 |
| Stage-1 cases scored, `cycle_window` | 5,049 |
| Stage-1 cases scored, `cycle_median` | 5,051 |
| Stage-1 cases scored, cap-10 variants | 5,051–5,054 |
| floats covered | 29 of 30 (all four artefact strata populated) |
| Stage-1 unavailable cases | 22 (0.43 %) |
| cases whose newest eligible hop is a multi-cycle gap (Stage-1 normalises these) | 29 |
| cases whose newest eligible hop is sub-cycle (Stage-1 ignores the burst) | 78 |

Artefact sample sizes (its own errors, its own strata): `cycle_window` 5,049 default
/ 12 strata; `cycle_window_prior` 2,138 / 8; `cycle_median` 5,051 / 12;
`cycle_median_prior` 2,139 / 8. Stage-0's own samples for contrast:
`trajectory_extrapolation` 5,187, `history_prior` 2,153, `regional_prior` 2,153,
`persistence` 5,187.

---

## C. Stage-1 R50/R90 calibration (its own, never Stage-0's)

Generated by `prediction/validate_cycle.py` into
`data/fleet_status/prediction_calibration_stage1.json`; every number below comes
from Stage-1's own historical errors. R50 is the 50th percentile of those errors,
R90 the 90th — the same definition Stage 0 uses, applied to different errors.

| Stage-1 method | n | R50 km | R90 km |
|---|---|---|---|
| cycle_window | 5,049 | 30.9 | 180.7 |
| cycle_window_prior | 2,138 | 18.8 | 68.7 |
| cycle_median | 5,051 | 37.5 | 156.0 |
| cycle_median_prior | 2,139 | 23.3 | 66.8 |

Per-stratum radii (`cycle_window`, region\|class → n / R50 / R90):
Arabian Sea\|* 2,169 / 21.9 / 76.3; Arabian Sea\|decadal 2,145 / 21.9 / 75.4;
Arabian Sea\|short 24 / 13.5 / 287.1; Bay of Bengal\|* 853 / 17.0 / 219.2;
Bay of Bengal\|short 848 / 17.0 / 220.1; Equatorial Indian\|* 314 / 49.5 / 220.6;
South Indian Ocean\|* 1,713 / 70.6 / 225.8; South Indian Ocean\|decadal 1,596 / 74.0 /
225.4; South Indian Ocean\|short 117 / 30.8 / 202.3. Every method carries the same bin
structure — 4 regions × {wildcard, `short`, `decadal`} = 12 bins — with 8 populated for
the prior-blended methods, whose strata for the Equatorial Indian Ocean hold no
prior-neighbour cases (full table in the artefact).

The artefact records the non-reuse explicitly (`baseline.note`: *"Stage-1 radii are
derived from Stage-1's own errors; no Stage-0 R50/R90 is reused"*), the criterion
outcome (`ship_gate.passed = false`), the default mode (`off`), and it keeps
Stage-0's file untouched (`data/fleet_status/prediction_calibration.json`, 42,481 B,
still keyed only by `history_prior` / `trajectory_extrapolation` / `regional_prior` /
`persistence` with no `stage` key). Both facts are asserted by
`tests/test_cycle_step.py::test_stage0_artefact_is_not_overwritten_by_the_stage1_candidate`.

---

## D. Cases where Stage-1 is unavailable

22 of 5,071 evaluable cases (0.43 %), on 17 floats, under the shipped window mode
(cap 3 cycles). Reasons, verbatim from the payload's `stage1_fallback_reason` /
the harness reason table:

* 18 cases: **burst-only history** — e.g. *"cached history spans only 1.58 d = 0.16 ×
  the 10.00 d interval (< 0.75 ×): telemetry burst, not a cycle"*. Stage 1 refuses to
  stretch a burst into a cycle; this is the behaviour the brief asks for, and it is
  visible in the drawer as a Stage-0-served prediction.
* 4 cases: **no span within 3 cycles** — histories whose only admissible spans exceed
  the normalisation cap (cached history spans of 550 d, 1,410 d, 1,850 d, 1,890 d,
  3,470 d with decadal intervals).

Cap sensitivity: with a 10-cycle cap the unavailable count falls to 17 (window) and
20 (median); the 5 cases gained are long-gap spans that the 3-cycle cap deliberately
excludes. No case is ever filled with a fabricated step, and none falls back to a
Stage-0 *radius* while claiming Stage 1.

---

## E. Cases where Stage-1 falls back to Stage-0

Three distinct fallback paths, all documented and all reported on the payload:

1. **No cycle-scale window** (the 22 cases in D): `_stage1_step` returns `None` and
   the unchanged Stage-0 branch serves the case; the Stage-0 method *and* Stage-0's
   own radii are used, `predictor_stage` stays `stage0`, and `issues` records
   *"Stage-1 cycle-scale step unavailable — …; Stage-0 last-hop step retained"*.
2. **Rung 4 never fires** (no eligible transition in the cached history, so Stage 1
   is never consulted): the Stage-0 ladder serves regional-prior/persistence and, in
   Stage-1 mode only, the payload records
   *"no eligible trajectory transition in the cached history — Stage-0 ladder used"*.
   This is an additive metadata field; Stage-0 mode never carries it.
3. **Stage-1 calibration missing**: Stage 1 refuses
   (`insufficient_validation`, no position) rather than borrowing Stage-0's radii.
   Covered by
   `test_stage1_without_its_own_calibration_refuses_and_never_borrows_stage0`.

Because `PREDICTION_CYCLE_STEP` defaults to `off`, path 2 and 3 are the only ones a
default deployment can ever reach today: the live payload shows all 30 predictions at
`predictor_stage = "stage0"` with no Stage-1 field set, which is the invariant that
proves Stage 0 was not silently changed. The Stage-1 artefact is present, so an
operator who sets `PREDICTION_CYCLE_STEP=window` gets path 1 behaviour instead of a
blanket refusal (the failure mode the artefact-less build would have had).

---

## F. Evidence that no future information was used

1. **Visibility rule in code.** Every Stage-1 step is built from
   `features.fixes`, which `build_float_features` filters to fixes at or before
   `now`; the harness builds each case from `fixes[:i+1]`. The step module then
   re-sorts by JULD and only ever pairs fixes inside that window.
2. **Target rule.** Labels require a strictly later cycle number *and*
   ΔJULD ≥ 0.5 × interval, and any candidate beyond 2 intervals is dropped as
   unscoreable — so a case is never scored against a fix that could not exist at
   prediction time, and never against an interior burst.
3. **Test.** `test_future_fixes_never_change_a_stage1_prediction` injects a fix dated
   two days *after* the prediction timestamp into the cached row and asserts the
   filtered feature list, the predicted position and the `step_basis` are byte-identical.
4. **Independent Stage-0 audit.** `stage0_science_audit.py` check **G** passes after
   the Stage-1 change (*"predictors only see transitions that start at or before the
   issuing fix — no future transitions in any float's features"*), and its check **H**
   (*no WMO or coordinate literals in the prediction feature*) passes after the one
   literal I had put in a docstring was moved into this report.
5. **No hindsight in the calibration.** Stage-1's radii are computed from its own
   historical errors with the same chronological, leave-one-float-out protocol as
   Stage 0; the prior pool lags its inputs by 2.0 d and excludes the target float.
6. **One protocol correction, disclosed.** `load_fixes` claimed "chronological" but
   returned file order; four corpus files contain measurement rows that are out of
   time order around a long silence. That made one-cycle labels and hop spans land on
   stale duplicate rows. `load_fixes` now sorts by JULD (no row added, dropped or
   interpolated) and `audit/stage1_order_effect.py` measures the effect both ways:
   Stage-0 replay median 30.5 → 30.7 km, p90 183.5 → 186.0, RMSE 483.2 → 471.8,
   max 18,915 → 16,181 km. Aggregate radii are materially unaffected; per-case labels
   near an out-of-order block change decisively, which is why the correction is part
   of this change set rather than a silent fix. It uses no future data — sorting
   reorders rows that were already present.

---

## G. Is Stage 1 scientifically justified to ship?

**No — not as a default, on this evidence.** The pre-registered gate (median ≥ 5 %
better **and** p90 ≥ 5 % better **and** RMSE ≥ 0 % better, with leave-one-float-out
keeping the sign) is **failed**: median −2.66 %, p90 −0.72 %; RMSE passes at
+28.49 % and the LOFO sign is stable, but two of three accuracy terms move the wrong
way. The post-hoc scoped variant — cycle-scale step only where the newest hop is
sub-cycle or a normalised gap — removes every regression (+0.33 % median, +0.89 %
p90, +8.85 % RMSE, +0.1/+0.5/+0.1 pp hit rates, applied on 90 cases) and *still*
misses the ≥ 5 % bar, so it is not shippable either.

What the evidence does establish, and what I would put in front of an operator:

* **The scientific premise holds and the fix works on the cases it targets.** Bursts
  and multi-cycle gaps exist in the real data (audit items 1–3), the last-hop step is
  measurably wrong on them (audit item 4: sub-cycle RMSE 892 km, multi-cycle RMSE
  683 km against 207 km for the regular class), and in the paired comparison Stage 1
  improves every irregular class: burst p90 2,655.6 → 717.4 km (RMSE 1,868.4 →
  1,242.2), gap median 54.9 → 34.3 km (RMSE 141.5 → 93.0). Pooled, that reduces
  catastrophic error: mean −6.2 %, RMSE −28.5 %, best case −7,681 km.
* **Why it still loses the bulk.** For regular floats both stages choose the same
  pair of fixes (3,194/5,071 identical positions), and where a bursty float's newest
  hop *is* short, that short hop is a better estimator of the next surfacing for
  these particular floats than a full cycle of older drift (1,165 cases worse vs 712
  better, median change 0.0 km). Two of the three floats most affected
  (`2902092`, `2902093`) have per-float medians that move by ≤ 4 km; the largest per-float
  median regression is +10.6 km (2902131: 59.9 → 70.5 km) while the two flats that
  improve move by −17.8 km (2902089: 54.3 → 36.5) and −3.1 km (2904082), and the
  single worst case regression is +454 km against a 30 km baseline — tail events, not drift.
* **The defensible next step** is the scoped rule (or an explicit per-float
  irregularity gate), evaluated under the same protocol, with a target-matched
  scoring rule that can distinguish "next surfacing" from "next telemetry fix" —
  the harness's target rule already mirrors the deployed forward test, so the
  production forward log will confirm or refute this measurement as the fleet
  advances cycles. Stage 1 stays implemented, documented and one env var away, so
  that decision can be made on live evidence instead of a re-write.

---

## G2. Live validation: the Stage-1 path actually serving (not only unit-tested)

Every earlier Stage-1 test was synthetic. To close that gap the service was run in
`PREDICTION_CYCLE_STEP=window` against the real 30-float cache, exercised through the
browser, and then returned to the shipped default. Evidence:
`audit/capture_stage1_case.mjs` → `e2e-shots/stage1-1902844-{drawer.png,map.png,evidence.json}`.

**What the deployment served (Stage-1 mode):** 26 of 30 floats at
`predictor_stage = stage1` (20 `cycle_window`, 6 `cycle_window_prior`), 4 at
`stage0` via the documented fallbacks — 3 "no window within 3 cycles" (histories
spanning 30 d / 3,470 d / 3,710 d against 1.00–10.00 d intervals) and 1 "cached
history spans only 1.46 d = 0.15 × the 10.00 d interval (< 0.75 ×): telemetry burst,
not a cycle". All 30 kept rung 4 and none was unavailable. The drawer for a Stage-1
float (1902844, Arabian Sea · decadal) reported:

| row | value |
|---|---|
| Prediction Method | Cycle-Scale Window (Stage-1) |
| Predictor stage | Stage-1 cycle-scale step |
| Cycle-scale step basis | `cycle-scale window 9.79 d = 1.00 x the 9.79 d expected interval (1 fix(es) back)` |
| Stage note | *"Stage-1 cycle-scale step in use for this prediction. It is under evaluation: Stage-0 (last-hop step) remains the shipped baseline and its R50/R90 are not reused here."* |
| R50 / R90 | 21.9 km / 75.4 km, both quoted with the unchanged required wording |
| Validation Sample Count | 2,145 |
| Calibration basis | Cycle-Scale Window (Stage-1) · Arabian Sea · decadal cycle |

All eight automated drawer checks in the capture passed
(`stage_row_names_stage1`, `step_basis_row_present`, `step_basis_matches_payload`,
`note_keeps_stage0_as_baseline`, `note_denies_radius_reuse`, `r50_row_is_stage1_radius`,
`r90_row_is_stage1_radius`, `samples_row_matches_payload`), and the served radii
reproduced the Stage-1 artefact **exactly on all 26 Stage-1 floats** (stratum-first
lookup, zero mismatches) while the Stage-0 artefact on disk stayed byte-identical.

**Suites re-run in Stage-1 mode:** fleetStatus 1113/1113 · predictionMap 162/162 ·
forward audit 11/11 · science audit 17/17 (after the hardening below). **Then back in
the shipped default:** fleetStatus 1113/1113, science 17/17, forward 11/11, payload
30/30 `stage0` with 21 `trajectory_extrapolation` / 9 `history_prior`.

**Two audit defects this exposed (both fixed, both were audit-side, not product-side):**

1. `stage0_science_audit.py` assumed the Stage-0 artefact was always the served one:
   check A reported "no calibrated radius for cycle_window" and check E2 replayed
   without the stage layer, so a Stage-1 deployment failed three checks that were
   really the audit's own blind spots. It is now stage-aware: it verifies each row
   against the artefact of the stage that served it, replays with the served mode and
   the Stage-1 artefact layered on the Stage-0 primary calibration exactly as the
   service does, and carries a new check **A0** asserting that every served row's
   stage has its own artefact *and* that the Stage-0 artefact is still intact
   (no `stage` key, exactly the four Stage-0 methods). 16/16 became **17/17 in both
   modes**.
2. `ForwardTestLog.metrics()` grouped only *scored* rows by stage, so a validation
   deployment could not see its pending Stage-0/Stage-1 mix. It now reports
   `issued_by_stage`, attributing records with no stage field to Stage-0 (they were
   issued by Stage-0 code) — the live payload shows `{"stage0": 30}`.

**One operational finding worth stating plainly:** the forward log is keyed by
`(wmo, issuing fix)`, so flipping `PREDICTION_CYCLE_STEP` on an unchanged cache does
**not** create new records — the audit keeps the stage that was actually issued first
for that fix. To validate Stage-1 in the forward test, the cache must advance a cycle
(or a validation deployment must start from a fresh log). This is the correct
behaviour — the audit never relabels history — but it means the forward test cannot
be the *first* evidence for a stage change; the retrospective harness in section A is.

## H. Exact files changed

**Service (shipped code, `decoder-ui/service/`)**

| file | change |
|---|---|
| `prediction/cycle_step.py` | **new** — cycle-scale step model (window / median modes, band 0.75–1.25 × interval, ≤ 3-cycle normalisation by whole cycles, `bounded` provenance, truthful `fallback_reason`, `PREDICTION_CYCLE_STEP` resolution, `DEFAULT_CYCLE_STEP = off`) |
| `prediction/validate_cycle.py` | **new** — Stage-0 vs Stage-1 evaluation harness: deployment-faithful replay, target-matched labels, cap and weight sweeps, leave-one-float-out, per-region/per-class tables, ship-gate arithmetic, artefact + CSV/JSON writers |
| `prediction/validate_cycle.py` (2nd change) | per-case step provenance (`step_cycles`, `gap_normalised`) is now written as **real case fields**; previously it was passed as `extra={…}`, which landed the values under a literal `"extra"` key and made them unreadable per case (found by the new harness regression test) |
| `prediction/validate.py` | ordering correction in `load_fixes` (sort by JULD; documented) + de-literalised docstring; `build_calibration` now **skips methods with no scored cases**, so a degenerate (empty) method entry can never enter an artefact as a radius |
| `prediction/calibrate.py` | Stage-1 method keys and labels, `STAGE_STAGE0/1` + `STAGE_LABELS`, `Calibration.stage`, `load_stage1_calibration()`, Stage-1 artefact filename/env |
| `prediction/predict.py` | `_stage1_step()` (mode-gated, before the rung-4 Stage-0 branch), provenance fields (`predictor_stage`, `predictor_stage_label`, `step_basis`, `step_span_days`, `step_ratio`, `step_cycles`, `step_windows_used`, `stage1_fallback_reason`), no-history fallback reason, `predict_fleet` plumbing, **bug fix**: `step_dlat/step_dlon` were only bound in the prior-blend branch (`UnboundLocalError` for a Stage-1 step without a prior) |
| `prediction/forward_test.py` | issued records now carry `predictor_stage`, `predictor_stage_label`, `step_basis`, `step_cycles`, `stage1_fallback_reason`; `metrics()` groups scored rows by stage (`stages`), treating pre-Stage-1 records as Stage 0 |

**Data**

| file | change |
|---|---|
| `data/fleet_status/prediction_calibration_stage1.json` | **new** candidate artefact (45,798 B): 4 Stage-1 methods, 12-bin strata per method (8 for the prior-blended pair), sparse `prior_grid`, ship-gate block with `default_mode: off` |
| `data/fleet_status/prediction_calibration.json` | **unchanged** (42,481 B) — asserted by test |

**Frontend (`decoder-ui/frontend/src`, `frontend/e2e`)**

| file | change |
|---|---|
| `components/FloatStatusPage.tsx` | **Predictor stage** row (baseline named when no stage is reported), **Cycle-scale step basis** row for Stage 1 (with gap-normalisation note), amber Stage-1 note stating Stage 0 remains the shipped baseline and its radii are not reused |
| `types/index.ts` | `predictor_stage`/`predictor_stage_label`/`step_*`/`stage1_fallback_reason` on `FleetPrediction`; `cycle_window`, `cycle_window_prior`, `cycle_median`, `cycle_median_prior` added to `PredictionMethod` |
| `components/PredictionDetail.test.tsx` | +4 tests (baseline naming, Stage-1 naming + step + note + unchanged R50/R90 wording, gap-normalised step, payload without a stage) |
| `e2e/fleetStatus.e2e.mjs` | +1 check per field-checked float (30): the drawer names the predictor stage and never implies a stage swap |

**Tests & docs**

| file | change |
|---|---|
| `tests/conftest.py` | **new** — suite-wide isolation: ``ARGO_UI_DATA_DIR`` is pinned to a temporary directory before any test module imports the service, because ``event_bus.DATA_DIR`` is resolved once at import time (`setdefault`, so a deliberate override still wins) |
| `tests/test_fleet_status_audit.py` | imports the service **after** redirecting ``ARGO_UI_DATA_DIR``, plus a guard test asserting runtime state is not the repository data directory (source of a real leak, see section I) |
| `tests/test_profile_recency.py` | same import-order fix |
| `tests/test_validate_cycle.py` | **new** — 8 regression tests for the evaluation harness itself (synthetic `_Rtraj.nc` corpus in a temp `ARGO_UI_DATA_DIR`): hop classification and labels, paired stage series, Stage-1 prior-inheritance, multi-cycle-gap normalisation reported per case, no-future-fix leakage, determinism, and the written artefact's stage/schema/gate |
step geometry, burst/gap handling, provenance fields, mode resolution/defaults, Stage-0 equivalence when off, Stage-1 own radii, refusal without Stage-1 calibration, documented fallback paths, gap normalisation reporting, no-future-fix invariance, fleet plumbing, both artefacts on disk at once |
| `PREDICTION.md` | new *Stage-1 cycle-scale step* section (switch, rule, artefact, fallback, ship decision, payload fields); UI section notes the stage rows |
| `service/prediction/forward_test.py` (2nd change) | `metrics()` now reports `issued_by_stage`, so a validation deployment can see the pending stage mix before anything is scored |
| `service/prediction/predict.py` (2nd change) | Stage-1 mode with no eligible transition records `stage1_fallback_reason` (additive metadata only; Stage-0 mode never carries the field) |

**Evidence (outside the repo, `/home/user/prediction-validation/`)**

`audit/stage1_audit.py` + `stage1_audit.json` + `stage1_audit_summary.json` (read-only
audit, items 1–5); `audit/stage1_order_effect.py` + `stage1_order_effect.json`;
`audit/capture_stage1_case.mjs` + `e2e-shots/stage1-1902844-{drawer.png,map.png,evidence.json}`
(live Stage-1 serving evidence); `stage1_vs_stage0.csv` (201 rows) +
`stage1_vs_stage0.json` (full comparison incl. per-case class tables, LOFO folds,
availability reasons); this report.

Also touched (audit tooling outside this feature's earlier list):
`audit/stage0_science_audit.py` — made stage-aware, new check A0, now 17 checks.

---

## I. All tests and results

| suite | command | result |
|---|---|---|
| backend (service + prediction + fleet status) | `env -u FLEET_SYNC_ENABLED PYTHONPATH=src:service /home/user/.venv/bin/python -m pytest tests -q` | **331 passed** (301 before + 21 Stage-1 tests + 8 harness regression tests + 1 runtime-isolation guard) |
| Stage-1 module only | `pytest tests/test_cycle_step.py -q` | 21 passed |
| Stage-1 evaluation harness (new) | `env -u FLEET_SYNC_ENABLED PYTHONPATH=service:src … -m pytest tests/test_validate_cycle.py -q` | **8 passed** — the harness that produced every number in this report is now itself regression-tested; writing it surfaced two real harness defects (see below) |
| frontend unit / SSR | `cd frontend && npx vitest run` | **15 files, 170 passed** (166 before + 4 new) |
| frontend environment rebuilt after a sandbox reset | `npm install` (301 packages) + `npx playwright install chromium` + `install-deps chromium` | rebuilt clean; chromium launch smoke-tested before any audit ran |
| TypeScript | `cd frontend && npx tsc --noEmit` | clean (exit 0) |
| browser audit — Float Status, drawer, prediction, map | `FLEET_E2E_BASE=http://127.0.0.1:3000 node e2e/fleetStatus.e2e.mjs` | **1113/1113** (1083 Stage-0 checks + 30 stage-label checks), 30 floats field-checked — run in **both** Stage-1 mode and the shipped default |
| browser audit — prediction map layer | `PREDICTION_MAP_BASE=http://127.0.0.1:3000 npm run test:prediction-map` | **162/162** (30 predicted points, 60 rings) |
| science audit (live API, both deployment modes) | `PYTHONPATH=src:service …/audit/stage0_science_audit.py` | **17/17 with Stage 1 serving**, **17/17 in the shipped default** (was 16 checks; A0 added and A/E2 made stage-aware — see G2) |
| forward-test audit | `PYTHONPATH=service …/audit/stage0_forward_audit.py` | **11/11** (archived pre-fix log still replays correctly) |
| Stage-1 evaluation harness | `PYTHONPATH=service:src … -m prediction.validate_cycle --corpus /tmp/argotraj2 …` | ran clean; artefact + CSV + JSON written |
| Stage-1 live serving capture | `FLEET_E2E_BASE=http://127.0.0.1:3000 node audit/capture_stage1_case.mjs` | **8/8 drawer checks**, evidence in `e2e-shots/stage1-1902844-*` |
| prediction-map audit in Stage-1 mode | `PREDICTION_MAP_BASE=http://127.0.0.1:3000 npm run test:prediction-map` | **162/162** with Stage-1 radii drawn (30 points, 60 rings) |
| read-only Stage-1 audit | `PYTHONPATH=src:service …/audit/stage1_audit.py --corpus /tmp/argotraj2` | ran clean; JSON + summary archived |
| live payload invariant | `GET /api/fleet-status` | 30 floats, **all `predictor_stage = stage0`**, methods 21 `trajectory_extrapolation` / 9 `history_prior`, rungs `{"4": 30}`, persistence 0, unavailable 0, forward test 30 issued / 0 scored / 30 pending, `stages` grouping present and empty |

**Reproduced from scratch (sandbox resets between turns).** The results table above
is the authoritative, current record; this paragraph documents that the report's
numbers were rebuilt from an empty environment rather than carried forward: fresh
virtualenv from `service/requirements.txt` + `pytest`/`httpx`, fresh `npm install` +
Playwright browser, corpus re-fetched from the public GDAC over FTP (30/30 files,
111.1 MB), API and frontend restarted, symlink recreated. Each such rebuild
reproduced the earlier run (the Stage-1 audit: 5,265 cases; ratio median 1.000 / max
36.028; 2 sub-cycle, 27 cycle-scale, 1 multi-cycle newest hop; 97.8 % in-band windows;
Stage-0 replay 30.2 / 182.8 / 273.3 km), and the totals in the table were then
extended by the work described below (backend 320 → 322 with the forward-test
stage tests → 330 with the harness regression tests → **331** with the runtime-
isolation guard; science 16 → **17** once check A0 was added).

After the final reset the harness was re-run against the freshly re-fetched corpus
once more, on the current tree: the Stage-1 artefact regenerates **1,610 of 1,611
scalar fields identical** (only its own `generated_at`), the full comparison JSON
**645 of 646** (same single difference), and `stage1_vs_stage0.csv` is
**byte-identical**. The Stage-0 artefact is unchanged throughout
(`prediction_calibration.json`, sha256 prefix `532d1d831f2888a1`, Stage-0 methods
only).

**Runtime-state leak in the test suite (found while re-running the battery, fixed
here).** Rebuilding the frontend environment after a sandbox reset exposed something
the green battery had hidden: two older test modules imported the service **before**
redirecting ``ARGO_UI_DATA_DIR``, and because ``service/event_bus.py`` resolves
``DATA_DIR`` once at import time, a test run then wrote into the repository's own
``data/fleet_status/prediction_forward_log.jsonl`` — appending forward-test records
for the synthetic audit float 2909999 (three of them, still present on disk from a
pre-reset run). That file is *not* test-only data: a deployment started without
``ARGO_UI_DATA_DIR`` serves it as its own forward-test history, so the suite was
quietly editing a fixture a deployment could read. Fixed three ways, each verified:

1. ``tests/conftest.py`` pins ``ARGO_UI_DATA_DIR`` to a temporary directory before any
   test module is imported, so isolation no longer depends on pytest's collection
   order (the old per-module pattern only worked while the first-imported module
   happened to be one that set it).
2. ``tests/test_fleet_status_audit.py`` and ``tests/test_profile_recency.py`` now
   redirect before importing the service.
3. A guard test in ``test_fleet_status_audit.py`` asserts ``event_bus.DATA_DIR`` is not
   the repository data directory and that the forward-log path is not inside it.

Verification: the fixture log was restored to its 30 pre-existing records and its md5
is **unchanged by the full suite and by each previously-polluting module run
individually**; the three test-written lines that had accumulated are archived at
``audit/removed_fixture_forward_log_tail.jsonl``. No service code was touched, and the
runtime deployment log was never affected (30 records, 30 unique ``(wmo, issuing fix)``
keys, all pending). Backend total is therefore **331**, not 330.

**Harness regression closure (last engineering gap).** `tests/test_validate_cycle.py`
builds a 3-float synthetic `_Rtraj.nc` corpus in a temporary `ARGO_UI_DATA_DIR` and
drives the real harness end to end. Writing it found two defects in the harness
itself, both now fixed and re-verified against the real corpus:

1. **Per-case step provenance was unreadable** — `record()` passed
   `extra={"step_cycles": …, "gap_normalised": …}` as a keyword argument, so every
   case carried a nested `extra` dict instead of the fields themselves. The
   aggregates in this report are unaffected (the harness's tables read the step
   objects, not the per-case keys), but per-case provenance was not inspectable.
2. **An empty method could enter an artefact** — `build_calibration` emitted a
   default entry even for a method with no scored cases, which would be served as a
   radius backed by zero validation samples. Empty methods are now skipped.

Re-measured after both fixes, from the re-fetched corpus (30/30 files, 111.1 MB):
`prediction_calibration_stage1.json` regenerates **1,610 of 1,611 scalar fields
identical** (only its own `generated_at` differs), the comparison CSV is
**byte-identical**, and the full comparison JSON is identical in 645 of 646 fields.
Every figure quoted in sections A–G therefore stands unchanged. Live checks in the
shipped default: 30/30 `predictor_stage = stage0`, forward test 30 issued / 0 scored /
30 pending, science audit 17/17, forward audit 11/11.

**Audit-host requirement (learned the hard way, recorded so it is not repeated).**
The live service only sees trajectory history when it is started with
`ARGO_UI_DATA_DIR=/home/user/profile-recency-update/runtime`. Without it,
`event_bus.DATA_DIR` falls back to the repo-local `decoder-ui/data`, whose
`fleet_status/cache.json` is a fixture carrying **no** `recent_fixes` — the service
then reports 0 priors, 0 trajectory transitions and zero-hop steps for every float,
and the science audit correctly fails (14/17). Started with the runtime data dir and
sync disabled, the same audit is 17/17 and the forward audit 11/11. Separately, that
mis-started server appended 8 records to the repo-local *fixture* forward log; the
fixture was restored to its 30 pre-existing records (removed tail preserved as
`audit/removed_fixture_forward_log_tail.jsonl`). The runtime forward log was never
touched (30 records, 30 unique `(wmo, issuing fix)` keys, all pending).

**Acceptance criteria mapping.** The brief's requirements — one-cycle-representative
step, only pre-timestamp fixes, unchanged target time, explicit burst and
multi-cycle-gap handling, dynamic for all floats, documented fallback, own
calibration, UI stage label without overwriting the baseline, stage-distinguishable
forward test, all suites plus new tests, sections A–I, and ship-only-on-evidence —
are each either satisfied or explicitly measured as failing in this report. The
single requirement that is *not* met is the ship gate itself, which the brief
deliberately made binding: **Stage 1 is not shipped.**
