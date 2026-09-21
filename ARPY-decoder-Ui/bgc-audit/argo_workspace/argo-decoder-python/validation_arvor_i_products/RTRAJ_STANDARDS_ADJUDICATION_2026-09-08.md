# ARVOR-I Rtraj — Standards-First Adjudication (pre-freeze audit)

**Date:** 2026-09-08 · Tech FROZEN, Mono FROZEN, Meta untouched, GEBCO/Test-4 untouched.

## Documents used (current official versions, fetched this session)

| # | Document | Version / date | DOI / URL |
|---|---|---|---|
| D1 | Argo User's Manual | **3.44.0, 10 July 2025** | [10.13155/29825](https://dx.doi.org/10.13155/29825) |
| D2 | Argo DAC Trajectory Cookbook | **6.1, November 2022** | [10.13155/29824](https://dx.doi.org/10.13155/29824) |
| D3 | Argo QC Manual for CTD & Trajectory Data | **3.9** | [10.13155/33951](https://dx.doi.org/10.13155/33951) |
| D4 | NERC reference tables R05, R19, R20, RR2 | current (live) | vocab.nerc.ac.uk |
| D5 | Vendored Coriolis MATLAB | in-workspace | `tests/data/arvor_i/coriolis_src/` |
| D6 | Raw ARVOR-I telemetry | in-workspace | `arvor_raw/` |

All obtained from https://www.argodatamgt.org/Documentation. **D1 is newer than the manual relied on in earlier phases** — the CLOCK_OFFSET fix below comes directly from it.

---

## 3 GENUINE FIXES MADE (standard says GDAC/standard is right, ours was wrong)

### FIX 1 — `JULD_ADJUSTED` did not honour the CLOCK_OFFSET identity
**Rule (D1 §2.3.5, `CLOCK_OFFSET`, verbatim):** *"Real time corrections correspond to a data mode of "A". For "A" mode files, **JULD_ADJUSTED = JULD - CLOCK_OFFSET**"*

- **Ours (before):** published a real non-zero `CLOCK_OFFSET` but wrote `JULD_ADJUSTED == JULD`. **240 of 580** RTC-derived rows violated the identity — an internally inconsistent file.
- **Cause:** `_cycle_clock_days` returned a second value `round(drift_sec/60)/1440`, which collapses any second-scale drift to exactly **0**. That mirrors Coriolis's *hydraulic* minute-rounding (`adjust_hydrau`, 1-minute resolution), wrongly applied to the cycle skeleton.
- **GDAC:** satisfies the identity trivially — it publishes `CLOCK_OFFSET = 0.0` everywhere, discarding a measured quantity.
- **Decision: FIXED** — full-precision offset applied to all RTC-derived events. **580/580 now compliant, 0 violations.** We keep the *real* offset (D1 requires it be the actual drift), so we satisfy the identity with real data where GDAC satisfies it with zeros.
- Satellite-derived events (MC 0/702/703/704) are correctly **not** shifted: their dates never passed through the float RTC. Confirmed against D5 `adjust_clock_offset_prv_ir.m`, which adjusts only RTC timings, and D4 R19 status '4'.

### FIX 2 — DDET (MC 400) published the wrong quantity
**Rule (D2 Annex 9.3 + p.103):** DDET 400 and AST 500 are **separate ARVOR events**. DDET = arrival at profile depth (start of deep-park drift); AST = end of that drift.

- **Ours (before):** DDET was synthesised as a **copy of AST 500** (`replace(r, measurement_code=400)`).
- **Evidence it was wrong:** GDAC has `400 != 500` in **100 %** of cycles. Our own internal DPST 450 row (`descent_to_prof_end` — the same instant DDET denotes, per the module's own `_NCYCLE_FIELDS` map) reproduces **GDAC's MC 400 exactly** (27843.947917, 27853.777778, 27863.552083 …), fractional parts identical on every clean cycle.
- **Decision: FIXED** — DDET is now published from the decoded DPST instant. Parity moved from *wrong quantity* to **exact modulo GDAC's known integer-day bug** (exact = 1, integer-day-only = 4, other = **0**).
- Where the mission config never arrived the 450 skeleton is still emitted as fill, so the published family inventory is unchanged (DATA-COVERAGE, not a dropped event).
- DET 200 ≡ PST 250 **is** correct (same instant; GDAC has 200 == 250 in every cycle) and is retained.

### FIX 3 — validator/test assertions encoded the two bugs
`test_det_ddet_are_pst_ast_twins` asserted `DDET == AST`, and the GDAC validator asserted the same. Both corrected to the cookbook semantics (`DDET <= AST`; equality only for a zero-length deep-park drift, genuinely observed on 7902408 cycles 11–12). A unit test now pins the CLOCK_OFFSET identity for RTC rows and its non-application to satellite rows.

---

## 1. GDAC == ours (no action)

| Item | Evidence |
|---|---|
| Variable inventory | 102 = 102, **zero** ours-only / GDAC-only / dtype / dimension / **attribute** diffs, ×4 floats |
| Published MC family set | identical 13 families `{0,100,200,250,300,400,500,600,700,702,703,704,800}` |
| Block order, launch row first | identical |
| MC 702 FMT / 704 LMT | JULD **36/36 exact**, positions **36/36 exact** |
| MC 703 surface fixes | JULD **158/158 exact**, positions **158/158 exact** |
| MC 700/800 positions | **36/36 exact** |
| MC 600 positions | **26/26 exact** where a fix exists |
| Launch row JULD/lat/lon | **exact ×4** |
| Launch `POSITION_QC`/`JULD_QC`/`POSITION_ACCURACY` | **exact ×4** — and RTQC-derived, not hardcoded |
| `DATA_STATE_INDICATOR` | `'2B  '` both sides |
| Cycle numbering (launch = −1) | D1 §2.3.4: *"Cycle number is -1 for the float's launch"* |

## 2. GDAC != ours, and the Argo standard says OURS is correct (keep + documented)

| # | Field | Ours | GDAC | Rule & section | Verdict |
|---|---|---|---|---|---|
| 2.1 | MC 100/200/250 JULD | fractional part identical, no day drift | +1…+99 whole days | D2 §1.2.4 cycle definition; D3 §4 Test 2 | GDAC puts descent start **after** transmission in 7/9 cycles — physically impossible. **Manual requires ours.** NOT FIXABLE (GDAC legacy double-anchor). |
| 2.2 | MC 600 AET | TST − 880 s | TST − 0 s | D2 p.103 (`AET = TST − 14 min` for Arvor); D5 `compute_prv_dates_222_...m:180` (`TST − 10 min − TC04/100`) | GDAC applies **no** correction, contradicting both. Ours uses the float's own decoded TC04 (=280 s from D6 raw). **Manual requires a correction; GDAC has none.** Ours kept. *See §4.1 — the 840 vs 880 s nuance is the one UNKNOWN.* |
| 2.3 | MC 703 `POSITION_ACCURACY` | `'I'` | `'0'/'1'/'2'/'3'` | D1 §2.3.4 + **D4 R05**: `'I'` = Iridium (≤5 km); 0–3 = **ARGOS** classes | These are Iridium-only floats with no ARGOS transmitter. **Manual requires ours.** NOT FIXABLE. |
| 2.4 | `JULD_STATUS` / `JULD_ADJUSTED_STATUS` | `2`/`3`/`4` per event provenance | flattened to `'1'` | **D4 R19**: 1 = "estimated, *not* transmitted by the float"; 2 = "transmitted by the float"; 4 = "determined by satellite" | GDAC labels float-transmitted dates as not-transmitted. **Manual requires ours.** PUBLICATION. |
| 2.5 | `JULD_QC` on float-clock rows | `'1'` (test 2 ran, passed) | `'0'` | D3 §4 Test 2 + D4 RR2 (`'1'` = good, all RT tests passed) | GDAC runs test 2 but never raises the flag. Ours applies the algebra uniformly. PUBLICATION. |
| 2.6 | `CLOCK_OFFSET` | real decoded drift (−2.3e-05 … −6.3e-04 d) | `0.0` everywhere | D1 §2.3.5: *"Decimal part of day that float clock **has drifted**"* | A measured quantity; publishing 0 asserts a driftless clock the telemetry contradicts. **Manual requires ours.** NOT FIXABLE. |
| 2.7 | `DATA_MODE` | `'R'` on cycles with no offset, `'A'` where applied | `'A'` everywhere | D1 §2.3.5: `'A'` ⇔ a real-time correction **was applied** | With `CLOCK_OFFSET = 0` GDAC's `'A'` claims a correction it did not make. Ours kept. |
| 2.8 | `CONFIG_MISSION_NUMBER` | `1` | fill | **D2 §1.2.3**: *"For **cycle 0**, CONFIG_MISSION_NUMBER should be fill value"* | Our N_CYCLE contains **no cycle 0** (cycles start at 1) — the fill rule does not apply. GDAC blanks CMN on cycles 1+, unsupported. **Manual requires ours.** |
| 2.9 | Cycle numbering | launch −1, first cycle 1 | shifted +1 | D1 §2.3.4: *"-1 for the float's launch"*, *"must match the profile cycle number"* | Our numbering matches our profiles; GDAC's +1 is a legacy artifact. **Manual requires ours.** EXPECTED. |
| 2.10 | `GROUNDED` | from float tech data | 5 cycles differ | D2 §2.5 + **D4 R20** | Traced to D6 raw: 1902844 cyc 2 has a real grounding pressure (963 dbar) → `'Y'`; the other disputed cycles have `tech1[12]=0` and no grounding pressure → `'N'`. **Raw telemetry supports ours.** (Most GDAC `'Y'`s fall in the contaminated block.) |
| 2.11 | Launch `JULD_STATUS` | `'4'` | `'0'` | **D2 §2.1.1**: *"JULD_STATUS = 4 - determined by satellite"* | **Manual explicitly requires ours; GDAC contradicts it.** |
| 2.12 | Foreign contaminated block | not reproduced | 64 cycles byte-identical across two different WMOs, positions in the wrong hemisphere, dates to **2028** | D1 §2.3.4 (cycle must match profile) | Corrupt. NOT FIXABLE, never reproduced. |
| 2.13 | MC 702/704 presence | published | published | **D2 §2.2.1**: 702/704 omitted only for Iridium **RUDICS**; *"Iridium floats that send timing of messages… **This includes SBD Iridium floats**"* (D2 p.166) | ARVOR-I is Iridium **SBD** → 702/704 **required**. Both agree. |

## 3. GDAC != ours and the standard says GDAC is correct → **FIXED**
See FIX 1, FIX 2 above (and the earlier launch `POSITION_ACCURACY` `'G'`→fill, D2 §2.1.1). **No remaining item in this category.**

## 4. Standard ambiguous → UNKNOWN

### 4.1 AET constant: cookbook 840 s vs Coriolis 880 s
D2 p.103 gives a **fixed** `AET = TST − 14 min (840 s)` for Arvor. D5 computes `TST − 10 min − TC04/100`, which for these floats is **880 s** (TC04 = 28000 csec, decoded from D6 raw). The cookbook value is a documented *typical* constant; the Coriolis form is parameterised by the float's own transmitted configuration and therefore adapts to any mission. The two differ by 40 s.

**Decision: keep the Coriolis/telemetry-derived 880 s** (uses the float's actual TC04 rather than a hard-coded constant, and is generic across missions), and record this as **UNKNOWN** pending ADMT clarification. Either way GDAC's 0 s is wrong. *Not changed — changing it would replace measured configuration with a literal.*

### 4.2 MC 703 `JULD_ADJUSTED_QC` blank vs `'1'` on 26 rows
Where `JULD_ADJUSTED` is fill we leave QC blank per the `_FillValue = " "` contract; GDAC has no fill dates so the case never arises there. Ours is self-consistent; the standard does not address QC for a fill adjusted-date. UNKNOWN, low impact.

## 5. DATA-COVERAGE / TOOL-AVAILABILITY

| Item | Detail |
|---|---|
| MC 300/400/500 fill on 1902844/2904082/6990711 | Depend on `CONFIG_TC04_`/`MC29`, carried **only** in pack_type-5 (Param#1) packets. Decoding every raw `.eml`: **0** such packets on those three floats, **7** on 7902408 — the one float with them yields AST matching GDAC 5/5 exactly. Nothing fabricated. |
| MC 600 positions, 10 rows | No GPS fix in the cycle; position left fill rather than invented. |
| RTQC Test 4 (position on land) | **SKIPPED** — no GEBCO grid. Never fabricated. |
| RTQC Test 20 (questionable ARGOS position) | **SKIPPED** — its critical-error-length is defined (D3 §4 Test 20) only for ARGOS classes 1/2/3 (radii 1000/350/150 m). Iridium `'I'` has no ARGOS error radius. |
| 7902408 cycles 6–15 | Absent from GDAC reference (stale window). |

## 6. RTQC separation verified

**Trajectory RTQC ≠ profile RTQC.** D3 gives trajectories their own section (**§4**), distinct from the profile order table (§2.1.3). D5 `nc_add_rtqc_flags_prof_and_traj.m:775-786` applies exactly:

```matlab
testToPerformList2 = [ {'TEST002_IMPOSSIBLE_DATE'} {1} ...
   {'TEST003_IMPOSSIBLE_LOCATION'} {1} {'TEST004_POSITION_ON_LAND'} {1} ...
   {'TEST020_QUESTIONABLE_ARGOS_POSITION'} {1} ];
% perform RTQC on trajectory data (to fill JULD_QC, JULD_ADJUSTED_QC and POSITION_QC)
```

- **Fields these tests may modify:** `JULD_QC`, `JULD_ADJUSTED_QC`, `POSITION_QC` — and our implementation writes **only** those three. `JULD_STATUS`/`JULD_ADJUSTED_STATUS`/`POSITION_ACCURACY` are decoder provenance (D4 R19/R05) and are never touched by RTQC.
- **Results:** test 2 executed/passed (0 failures / 700 dated rows); test 3 executed/passed (0 / 602 positioned rows); tests 4 and 20 **skipped with recorded reasons**.
- **No QC value is hardcoded to match GDAC.** Launch QC `'1'/'1'` is produced by tests 2/3 running; remove the launch position and no flag is set, corrupt the date and it becomes `'4'` (unit-tested).
- Profile RTQC (the 15-test set) remains on Mono only — **frozen and verified unchanged**.

## 7. Validation

| Gate | Result |
|---|---|
| pytest | **2098 passed**, 1 skipped (golden tree, pre-existing) |
| Rtraj GDAC validator | **84/84** (was 80/80; +4 DDET/order checks) |
| Rtraj 4B validator | **64/64** |
| Tech GDAC / Tech | **32/32** · **56/56** |
| Meta | **108/108** |
| ruff check + format | clean, 172 files |
| APEX A/B | **IDENTICAL** (4/4 fingerprints) |
| **Tech frozen** | content identical ex-timestamps, ×4 |
| **Mono frozen** | 69 files; RTQC inventory identical to baseline (`executed {1,2,3,5,6,8,9,11,12,13,14,16,18,19}`, `failed {5:1,11:6,12:4,16:1}`) |
| CLOCK_OFFSET identity | **580/580 compliant, 0 violations** |
| JULD_ADJUSTED deltas vs GDAC | **0 unexplained** (92 exact, 88 fully explained by our real offset) |

## 8. Genericity

No WMO or cycle literal anywhere in the changes. DDET sourcing keys on MC 450 presence; clock adjustment keys on whether a cycle has a decoded offset; RTQC keys on decoded row content only. Tests 4/20 self-activate when their inputs appear. Four-CSV-only architecture intact; `registry.csv` unused for ARVOR-I. Valid for current and future ARVOR-I floats.

## 9. Freeze recommendation

Every remaining divergence now has an explicit standards-based justification (§2), is a proven coverage/tooling limit (§5), or is one of two documented UNKNOWNs (§4) where our choice is the more defensible and GDAC is wrong either way. **Rtraj is ready to freeze**, with §4.1 (AET 840 vs 880 s) flagged for ADMT clarification.
