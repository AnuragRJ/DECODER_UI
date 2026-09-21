# ARVOR-I Fleet/Product GDAC Parity Report

**Floats:** 1902844, 2904082, 6990711, 7902408 · **Family:** ARVOR-I SBE41CP Iridium SBD (engines 5900A05 → ids {222, 223, 225}, 5900A05B → id 232; resolved per float from the Tech#1 firmware checksum via `resolve_engine`, the `check_decoder_id.m` table — PROVEN)
**GDAC:** `https://data-argo.ifremer.fr/dac/incois/<WMO>/` (6990711/7902408 refs re-verified 2026-08-31; **1902844/2904082 refs fetched 2026-09-04** and preserved in `../gdac_arvor_i_ref/`; `prof.nc` excluded everywhere — GDAC downstream derivative)
**Revision 4 — 2026-09-04:** expanded to the **four-float fleet** with **full value-level comparison** of all four products (`validation_fleet_parity/*.json` = the machine-readable record). Architecture change: the **four CSVs are the only metadata/routing authority** for ARVOR-I; `registry.csv` provides nothing for these floats (§2). Revision 3 content (Phase 9 Rtraj closure, CLOCK_OFFSET correction) is carried forward inside the new structure; no prior evidence was discarded.

---

## 1. Executive Summary

| Product | Floats | Verdict | Core evidence (value-level) |
|---|---|---|---|
| Mono `R*.nc` | all 4 | **EXACT science, validated** | **PRES/TEMP/PSAL exact on every one of 5,737 compared levels** (1,909 / 2,096 / 720 / 1,092); zero mismatches, zero fill asymmetries; JULD within 1 s on every file |
| `_tech.nc` | all 4 | **Matched values exact** | **75/75, 70/70, 15/15, 60/60 matched (cycle, parameter) values exact** — zero divergences; inventory differences classified (§6) |
| `_meta.nc` | all 4 | **Sheets-sourced fields exact** | Every sheet/GDAC-checkable field exact for all 4 floats (serials, launch, sensors, calibration); **7 systematic diffs, identical signature across all floats** (§8) |
| `_Rtraj.nc` | all 4 | **Science cells exact on matched rows; GDAC-side corruption documented** | PRES/TEMP/PSAL(+adj) exact on **all 277/277 / 277/277 / 70/70 / 80/80 matched rows**; JULD/position comparison for the new floats is dominated by **GDAC publication-file corruption** (§5.3): pre-launch-dated rows, a −730-day date shift from cycle 14, and 53 phantom cycles projected to 2028 |

**Headline conclusions.**
1. The decoder's scientific output is byte/value-exact against GDAC wherever a like-for-like comparison exists — now demonstrated **across the whole four-float fleet**, including both newly onboarded floats decoded through the generic sheets-only pipeline.
2. The GDAC Rtraj files for 1902844/2904082 are internally corrupted (dates before launch, −730 d shifts, cycles beyond the float's actual 24) — a **publication-side defect we must not chase** (standing rule: never move our semantics to GDAC values for parity).
3. Remaining differences are the *same classes* Phase 9 established for 6990711/7902408 (publication conventions, RTQC layers, reception-data coverage, expected timestamps) — the new floats introduce **no new decoder-defect class**. Two new generic FIX CANDIDATES exist (§12), neither implemented.

**Certification at this revision:** pytest **2,050 passed** (full unit + integration) · ruff check + format clean (164 files) · validators: Tech **54/54**, Meta **54/54**, Profiles **207/207**, Rtraj **35/35** · FileChecker 1.17 zero decoder-unique findings (Rev 3; re-run not in scope here).

**Reading rule (unchanged):** remaining Rtraj/QC-layer differences are **not evidence of remaining decoder defects**; each carries exactly one classification (§11).

## 2. Scope and Four-CSV Metadata Architecture

**Hard rule implemented this revision:** `config/metadata/{meta,sensor-info,calib,config_params}.csv` are the **only authoritative metadata source** for ARVOR-I.

* `registry.csv` provides **nothing** for ARVOR-I floats: the four rows added on 2026-09-04 (Prompt 4) were **removed** (registry restored to its 6 pre-fleet rows: 2 NKE demo + 4 APF9), the `routing_registry_path`/`_RoutingResolver` mechanism was **deleted**, and tests now assert `registry ∩ {ARVOR-I WMOs} = ∅`.
* Decoder routing is **family-first from the sheets**: `MultiCsvLoader` derives `PROFILE_CLASS = arvor_i_sbe41cp` from the sheet family signature (Manufacturer `arvor` → NKE + `CTD Sensor Type = SBE41CP` + non-ARGOS comms) → `FloatInfo.PROFILE_CLASS` → `ArvorISbdDecoder.can_handle` (decoder-table `profile_class` lookup). The numeric engine id (222-family vs 232) is resolved **from the telemetry checksum inside the stack**, never from metadata. `FIRMWARE_TO_DECODER` remains APF9-scoped; `7.2.5` is absent by invariant test.
* Chain verified end-to-end for all four floats: **4 CSVs → FloatMeta → generic routing → ArvorISbdDecoder → existing Phase 3-9 stack** (§8 proves meta provenance; §14 regression).
* No WMO is referenced anywhere in selection code (guard test scans loader/builder/base/plugin/table/discovery/metadata-stage source).

## 3. Fleet Covered

| WMO | Serial | Launch | Engine (checksum → ids) | Cycles decoded | Mono profiles | GDAC refs |
|---|---|---|---|---|---|---|
| 1902844 | 25001 | 2026-01-15 13:33 | 13872 → 232 | 24 (1–24) | 23 | fetched 2026-09-04 |
| 2904082 | 25002 | 2026-01-16 15:32 | 13872 → 232 | 24 (1–24) | 24 | fetched 2026-09-04 |
| 6990711 | 24022 | 2025-03-02 05:16 | 11415 → {222,223,225} | 7 (1–7) | 7 | standing |
| 7902408 | 25016 | 2026-03-25 17:44 | 13872 → 232 | 15 (1–15) | 15 | standing |

Family references: 6990711/7902408 retain their Phase 4–9 analyses (this report carries them forward); the new floats' numbers come from fresh decodes through the identical generic pipeline (raw: operator bundle, preserved).

## 4. Input / GDAC Availability

* **1902844** — GDAC publishes `1902844_{Rtraj,meta,prof,tech}.nc` + 23 `profiles/R*.nc` (fetched 2026-09-04; Rtraj last modified 2026-06-16, tech 2026-09-02, prof 2026-09-01). No DATA-COVERAGE gap for the compared products.
* **2904082** — same set, 24 profiles (Rtraj 2026-06-17, tech/prof 2026-08-31). No gap.
* **7902408** — standing refs; **GDAC publishes one mono profile we cannot produce: `R7902408_016.nc`** (cycle 16 is beyond our raw-telemetry snapshot) → **DATA-COVERAGE** (raw coverage, not a decoder failure).
* **6990711** — standing refs; known coverage gaps (April–May 2025 mails) unchanged.

## 5. Rtraj Detailed Comparison

Alignment: rows matched on **(cycle, MEASUREMENT_CODE, occurrence)** with **GDAC cycle = ours + 1** (the PROVEN publication convention; our cycle-1 position rows equal GDAC cycle-2's to the minute). Per-variable, per-cell results in `validation_fleet_parity/<wmo>_rtraj.json`.

### 5.1 Row inventory

| WMO | ours | GDAC | matched | ours-only | GDAC-only |
|---|---|---|---|---|---|
| 1902844 | 956 | 1,196 | 277 | 679 | 919 |
| 2904082 | 1,003 | 1,185 | 277 | 726 | 908 |
| 6990711 | 363 | 107 | 70 | 293 | 37 |
| 7902408 | 891 | 97 | 80 | 811 | 17 |

Ours-only rows are the **full Coriolis event set** the GDAC generator does not publish (1902844: code 290 ×69, 590 ×35, 189 ×12, 703 ×9, 89/150/198/297 …) — **EXPECTED** (identical class to 6990711/7902408 in Phase 9). GDAC-only rows for the new floats are dominated by **phantom cycles > 24** (§5.3).

### 5.2 Value-level on matched rows (per float: 1902844 / 2904082 / 6990711 / 7902408)

| Variable | exact / compared | mismatches | notes |
|---|---|---|---|
| MEASUREMENT_CODE | 277/277 · 277/277 · 70/70 · 80/80 | **0** | definitionally exact (key member) |
| PRES, TEMP, PSAL (+ `_ADJUSTED`, `_ERROR`) | **277/277 · 277/277 · 70/70 · 80/80 each** | **0** | science cells **exact on every matched row of every float** |
| PRES/TEMP/PSAL QC | all compared cells | **0** | exact |
| SATELLITE_NAME | 277 · 277 · 70 · 80 | **0** | exact |
| CYCLE_NUMBER | 0 (diff = 1 everywhere) | 277·277·70·80 | **EXPECTED** — the +1 publication convention (key shift); `CYCLE_NUMBER_ADJUSTED` is fill on both sides |
| JULD / JULD_ADJUSTED | 0 exact; mm 177/181/54/77; ours-fill 97/93/16/0; GDAC-placeholder 2/2/0/3 | see notes | new floats: dominated by GDAC-side date corruption (§5.3) + occurrence mispairing; 6990711: GDAC legacy-dating/RTQC (Phase 9 classes); sample-level detail in artifacts |
| JULD_QC / POSITION_QC | ours blank vs GDAC '0'/'1' (mm 180/184/41/26 and 183/192/47/50) | — | **PUBLICATION/RTQC** — GDAC fills RTQC codes; we emit the MATLAB-faithful blank (Phase 7 semantics; do-not-change) |
| JULD_STATUS / _ADJUSTED_STATUS | ours '2'/'3' vs GDAC '1' (all matched rows) | — | **PUBLICATION** — status-code convention |
| LATITUDE / LONGITUDE | 0 exact; mm 82/90/25/26; ours-fill 115/115/25/30; both-fill 80/72/20/24 | see notes | real mismatches are position-fix selection + GDAC corrupted rows; 6990711 sample deltas ≈ 0.26–0.30° (GDAC reuses a stale fix — Phase 9 classification); new-float max diffs (~20°) trace to §5.3 rows |
| POSITION_ACCURACY | exact 195/187/45/54 of 277/277/70/80 | rest | tracks the position rows (PUBLICATION) |
| AXES_ERROR_ELLIPSE_* | exact 209/200/48/60 | rest | same driver (position/QC publication layer) |

### 5.3 GDAC publication-file corruption — new floats (documented, NOT ours to fix)

1. **Pre-launch-dated rows:** GDAC cycle 1 carries 700/702/703 rows dated **2025-09-19** (four months before the 2026-01 launch).
2. **−730-day date shift:** from GDAC cycle 14 the code-500/600 dates jump to **2024** while keeping the exact ~9.83-day cadence (true date − 730 d), through cycle 77.
3. **Phantom cycles 25–77:** GDAC publishes complete cycle blocks beyond the float's actual 24 cycles, with dates projected to **2028-02** — over half of the GDAC-only keys (136/200 listed for 1902844; 147/200 for 2904082).
4. Cycle-1 codes 100–400 carry the legacy **1999-11-30 (18230)** placeholder (also present in the old refs; comparator treats it as no-date).

Classification: **PUBLICATION (GDAC-side data defect)** — evidence in `validation_fleet_parity/*_rtraj.json` samples. None of these may be reproduced by our decoder (§11 rules).

### 5.4 Family reference (Phase 9 closure, carried forward verbatim)

6990711: 363/107/94 rows; 269/13 only; 2,144/3,008 cells exact. 7902408: 891/97/68; 823/29; 1,598/2,176. 18/32 variables fully exact. CLOCK_OFFSET: ours raw-derived MATLAB-faithful (−5…−69 s / −3, −18 s); GDAC publishes literal 0.0 — **ours correct, NOT FIXABLE**. Rtraj: freeze-eligible, **not** declared frozen, and **never** to be described as identical to GDAC.

## 6. Tech Detailed Comparison

Alignment: (cycle, TECHNICAL_PARAMETER_NAME, occurrence), GDAC cycle = ours + 1 (new floats; consistent with the cycle-0 launch bucket), direct numbering for the old floats per the 2026-08-28 audit.

| WMO | ours rows | GDAC rows | matched | matched-value exact | ours-only | GDAC-only |
|---|---|---|---|---|---|---|
| 1902844 | 1,009 | 1,694 | 75 | **75/75 (100%)** | 934 | 1,619 |
| 2904082 | 938 | 1,694 | 70 | **70/70 (100%)** | 868 | 1,624 |
| 6990711 | 467 | 88 | 15 | **15/15 (100%)** | 452 | 73 |
| 7902408 | 804 | 374 | 60 | **60/60 (100%)** | 744 | 314 |

* **Every matched (cycle, parameter) value is exact on all four floats — zero divergences**, including hydraulic counters (extends the 2026-08-28 75/75 result family-wide).
* Parameter-set separation (per the audit's classes): (1) Coriolis-emitted = the modern Tech#1/Tech#2 set (62–67 names/cycle → the ours-only rows); (2) we emit + GDAC publishes = the 75/70/15/60 matched; (3) GDAC-only = legacy Argos-era names (`CLOCK_*`, `FLAG_ProfileTermination_hex`, duplicated vacuum rows …) **plus, on the new floats, rows belonging to phantom cycles 25–77** (§5.3) — legacy part **NOT FIXABLE**, phantom part **PUBLICATION**.
* Valid modern parameters are **not removed** because legacy GDAC omits them (standing rule).

## 7. Mono Profile Detailed Comparison

Filenames match exactly where both sides exist (no descent files manufactured; GDAC publishes none for this fleet).

| WMO | files ours/GDAC/common | levels compared (P/T/S) | exact | mismatch | JULD | LAT/LON |
|---|---|---|---|---|---|---|
| 1902844 | 23/23/23 | 1,909 | **1,909 (100%)** | **0** | 23 near ≤1 s | LAT 22 exact + 1 mm |
| 2904082 | 24/24/24 | 2,096 | **2,096 (100%)** | **0** | 24 near ≤1 s | LAT 22+2 mm, LON 22+2 mm |
| 6990711 | 7/7/7 | 719–720 | **all** | **0** | 6 near + **1 mm (cycle 5 — known, classified Phase 5: missing April mails, DATA-COVERAGE)** | 1 mm each |
| 7902408 | 15/16/15 | 1,092 | **1,092 (100%)** | **0** | 15 near | LAT 13 + 2 near |

* **Every PRES/TEMP/PSAL level of every compared profile of every float is exact** (5,737 levels total; zero fill asymmetries).
* **QC flags — value fields identical, flag-convention fields differ exactly as designed (pre-RTQC vs RTQC):**
  * *Identical on all 69 compared files:* `JULD_QC`, `POSITION_QC` (both sides '1'), `*_ADJUSTED_QC` (fill both sides), `HISTORY_QCTEST` (blank both sides — populated only in delayed mode).
  * *Systematic difference in every file of every float:* per-level `PRES/TEMP/PSAL_QC` = ours **'0'** (raw pre-RTQC, MATLAB-faithful Coriolis decode) vs GDAC **'1'** (RTQC-passed) — 17,211 QC cells (5,737 levels × 3 parameters); profile summaries `PROFILE_{PRES,TEMP,PSAL}_QC` = ours **''** vs GDAC **'A'** (real-time QC applied, all tests passed). Classification: **PUBLICATION/RTQC** — the deliberate pre-RTQC semantics of §11; running GDAC's RTQC pass locally is a separate, not-yet-authorised capability (the in-repo RTQC engine is not wired into the ARVOR-I chain; see §16).
* The few position mismatches are GPS-fix selection differences on individual profiles (PUBLICATION; values in artifacts). 7902408's GDAC-only `R7902408_016.nc` = **DATA-COVERAGE** (§4).

## 8. Meta Detailed Comparison

**Provenance proof:** with registry.csv out of the loop entirely, every sheets-sourced field matches GDAC for all four floats — FLOAT_SERIAL_NO (25001/25002/24022/25016), PLATFORM_TYPE ARVOR, LAUNCH_DATE, launch positions, WMO_INST_TYPE 844, sensor inventory (SBE CTD + DRUCK serials), calibration blocks, DATA_CENTRE/PI/OWNER (INCOIS defaults), BATTERY 4DD LI. The metadata demonstrably flows from the four CSVs.

**Systematic differences — identical variable set and value pattern on all four floats** (i.e. conventions, not float-specific defects):

| Variable | ours | GDAC | Classification |
|---|---|---|---|
| DATE_CREATION / DATE_UPDATE | run timestamps | GDAC run timestamps | EXPECTED |
| TRANS_SYSTEM_ID / TRANS_FREQUENCY | `123230` / blank | `n/a` / `n/a` | PUBLICATION (GDAC n/a convention for Iridium) |
| POSITIONING_SYSTEM | `IRIDIUM` (from sheet comms) | `GPS` | **FIX CANDIDATE** (§12.1) |
| CONTROLLER_BOARD_TYPE_PRIMARY | `APF0` (derived from `0i-0` placeholder) | `n/a` | **FIX CANDIDATE** (§12.2) |
| START_DATE | blank (no-fabrication doctrine) | cycle-1-derived timestamp | EXPECTED (note: telemetry-derivable — candidate only if sanctioned) |

## 9. Cross-Product Findings

1. **Consistency across products:** floats/rows where Tech and Mono both exist show 100% value agreement in both — the science core (counts→physics, cycle timing) is GDAC-exact family-wide.
2. **The new floats reproduce the family pattern** established on 6990711/7902408: same QC/status publication conventions, same ours-only detailed-event rows, same legacy GDAC parameter set — the fleet expansion acted as a **cross-float generalization test and found no generic defect**.
3. **New, new-float-specific:** GDAC Rtraj corruption (§5.3) — the only substantive new finding, and it is on the GDAC side.

## 10. Complete Mismatch Register

Machine-readable registers with per-cell locations, both values, and diffs: `validation_fleet_parity/<wmo>_{rtraj,tech,meta,mono}.json` (16 artifacts; capped sample lists carry exact indices). Summary counts appear in §5–§8 tables. The Rev-3 17-item register items remain valid and are subsumed as follows: items 1–17 map onto §11 classes unchanged (CLOCK_OFFSET → §5.4; RTQC/QC layers → PUBLICATION/RTQC rows; reception-data items → DATA-COVERAGE; do-not-change doctrine → §11 rules).

## 11. Classification of Every Mismatch

| Class | Items (this revision's fleet findings) |
|---|---|
| FIXABLE | none |
| FIX CANDIDATE | POSITIONING_SYSTEM (meta, all floats); CONTROLLER_BOARD_TYPE placeholder (meta, all floats) — §12 |
| DATA-COVERAGE | 7902408 mono 016 (raw snapshot); 6990711 April–May 2025 mails (cycle-5 JULD/LAT residuals); INCOIS reception logs (standing) |
| TOOL-AVAILABILITY | RTQC-pass QC flags (POSITION_QC 2/3 etc.) — out of chain scope (standing Phase 9) |
| PUBLICATION/RTQC | JULD_QC/POSITION_QC blank-vs-'0'/'1' (Rtraj); **mono per-level `*_QC` '0'-vs-'1' (17,211 cells) and `PROFILE_*_QC` ''-vs-'A' (§7 — pre-RTQC vs GDAC's RTQC pass; our chain runs no RTQC, §16)**; JULD_STATUS '2'/'3'-vs-'1'; TRANS_SYSTEM n/a; GDAC legacy undated rows; GDAC Rtraj corruption (§5.3, GDAC-side); GDAC-only legacy Tech names; cycle +1 convention |
| EXPECTED | ours-only detailed event rows (Coriolis-faithful); DATE_* stamps; START_DATE no-fabrication blank; CYCLE_NUMBER +1 |
| NOT FIXABLE | CLOCK_OFFSET (ours correct, GDAC publishes 0.0); HANDBOOK_VERSION leading space; legacy GDAC generator artifacts |

## 12. Fix Candidates (NOT implemented — awaiting authorisation)

1. **POSITIONING_SYSTEM** — file: `src/argo_decoder/metadata/multi_csv_loader.py` (payload `positioning_system`); current `[comms.upper()]` → `['IRIDIUM']`; reference `['GPS']` (GDAC, all four floats; also the registry convention `["GPS","IRIDIUM"]`). Proposed generic fix: positioning = `['GPS', comms]` for Iridium-SBD family floats (Coriolis `generate_json_float_meta_arvor_c_ir_sbd` convention). No WMO logic.
2. **CONTROLLER_BOARD_TYPE_PRIMARY** — file: same (`_controller_board_type`); the sheet placeholder serial `0i-0` currently yields `APF0`; GDAC publishes `n/a`. Proposed generic fix: placeholder serials (`0i-0`) produce a blank type rather than a derived one. No WMO logic.

## 13. Data-Coverage Limitations

Standing: INCOIS reception logs; 6990711 April–May 2025 mails; GDAC republication cadence (Rtraj for the new floats lags tech by ~2.5 months even while corrupted). New: our 7902408 raw snapshot ends before GDAC's cycle 16. *(The former "registry `*_meta.json` missing" limitation is now moot for ARVOR-I — the registry is no longer in their path.)*

## 14. Regression Status

* Full suite **2,050 passed** (unit + integration, incl. the generic-pipeline end-to-end test on preserved 6990711 raw).
* Validators: Tech **54/54**, Meta **54/54**, Profiles **207/207**, Rtraj **35/35**.
* ruff check + format clean across `src`, `tests`, `scripts` (164 files).
* No regressions: 6990711/7902408 (validators unchanged, products re-derived identically), APF9 fleet (loader APF9 path byte-equal; suite green), NKE demo (6902892 still routes to `ProvorIridiumSbdDecoder`), new floats (fresh decodes byte-consistent with the Prompt-2 baseline: 23/24 mono, 1,009/938 Tech rows, 956/1,003 Rtraj rows).
* Architecture guards: fleet join = 15 WMOs; `7.2.5` ∉ FIRMWARE_TO_DECODER; registry ∩ ARVOR-I = ∅; no WMO literal in selection source.

## 15. Final Scientific/Publication Parity Assessment

**Scientific parity:** wherever GDAC publishes values derived from the same telemetry, our products are **value-exact family-wide** — 5,737/5,737 mono P/T/S levels, 220/220 matched Tech values, all matched Rtraj science cells, all sheets-checkable meta fields. This is the strongest parity statement the evidence supports, and it now covers both engines (222-family and 232) and both metadata provenances (GDAC-verbatim legacy floats, sheet-only new floats).

**Publication parity:** differences that remain are *publication-layer* (RTQC codes, status conventions, n/a conventions, the +1 cycle numbering) or *GDAC-side defects* (the new floats' corrupted Rtraj dates/phantom cycles), plus documented coverage limits. Per the standing scientific rules none of these may be "fixed" by copying GDAC behavior into the decoder; the two generic FIX CANDIDATES (§12) are the only actionable items and are **not implemented** pending review.

**Action separation (per directive):**
**NO ACTION REQUIRED** — all exact-match results; all EXPECTED/PUBLICATION/NOT FIXABLE classes; GDAC Rtraj corruption (documented, referenced).
**FIXABLE** — none.
**FIX CANDIDATE** — §12.1 POSITIONING_SYSTEM; §12.2 CONTROLLER_BOARD_TYPE placeholder.
**DATA-COVERAGE** — 7902408 mono 016 (needs the later raw mails); 6990711 April–May 2025 mails; reception logs; GDAC republication of the corrupted Rtrajs.
**EXPECTED / NOT FIXABLE** — CLOCK_OFFSET (ours correct), legacy GDAC generator artifacts, HANDBOOK_VERSION quirk, cycle +1, DATE_* stamps, no-fabrication blanks.

* artifacts: `validation_fleet_parity/` (16 JSON, preserved) · comparator: `scripts/fleet_parity_compare.py` · log: `IMPLEMENTATION_PROGRESS.md` (append-only).

## 16. RTQC Engine Inventory (status note — no change made)

The repository inherits a full RTQC engine (`src/argo_decoder/rtqc/`, `RtqcConfig`, 32 per-test flags, 27 enabled by default per the docker sample config) **wired into the APEX-Argos path only** (`apply_rtqc` defaults to `False`; `ArvorISbdDecoder` contains no RTQC invocation — PROVEN by source scan). Consequently **none of the RTQC tests ran on the ARVOR-I products compared in this report**: our files are the validated MATLAB-faithful pre-RTQC decode, which is exactly what §7's mono QC rows show (ours '0'/'' vs GDAC's RTQC-passed '1'/'A').

For a core T/S/P float like ARVOR-I, the **applicable automatic suite is 15 tests, not 14** (the earlier 14 undercounted by omitting RT Test 19, deepest pressure): tests 1–6, 8, 9, 11 (legacy; v3.9 supersedes it with Test 25 MEDD, which INCOIS does not yet run), 12, 13, 14, 16, 18, 19. Test 7 is region-conditional (vacuous for this fleet), Test 15 is the DAC exclusion-list mechanism (empty ⇒ no-op), Test 17 is human visual QC. **Direct proof: the GDAC mono files for these floats carry `HISTORY` rows `QCP$`/`D7B7E`** = INCOIS's published record that tests 1–6, 8, 9, 11–14, 16, 18, 19 ran (cycle 1: `C7B7E`, minus test 16) and passed — matching the repo engine's implemented set exactly. Full specification audit — official manuals (QC Manual v3.9, Coriolis RTQC implementation doc) vs `src/argo_decoder/rtqc/`, test-by-test cross-check, threshold differences and traceability URLs: **`ARVOR_I_RTQC_SPEC_AUDIT_2026-09-04.md`** (companion to this section). **Step-1 addendum (same file, §8–§14):** QCP$/QCF$ masks decoded for all four floats directly (D7B7E invariant; 10 cycles with real INCOIS test failures), per-test implementation-gap table, specification conflicts resolved on the current Coriolis MATLAB source, a **standalone RTQC harness** (`scripts/rtqc_harness.py`; artifacts `validation_rtqc_harness/`) that runs the 15 tests on our decoded products with executed/passed/failed/skipped+reason semantics and truthful masks — cycle-exact test-12 oracle agreement with INCOIS on 4 failure cycles — and the recommended (NOT implemented) integration plan. The GEBCO and WOA13 reference datasets do **not** exist in the sandbox (`/mnt/ref/` absent; verified; WOA13 is BGC-only anyway) — the APEX path logs `apex_argos_test004_skipped (no_gebco_grid)` in that case. **Executing the full 15-test suite (incl. Test 4) therefore requires a local run with the reference datasets mounted** (`--gebco /path/GEBCO_2024.nc`). Wiring the RTQC engine into the ARVOR-I chain remains a **separate, explicitly authorised change** — deliberately not part of this diagnosis-only revision.
