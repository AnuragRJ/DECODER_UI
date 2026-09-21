# FINAL APF9 PARITY BASELINE

**Date:** 2026-08-21 · **Type:** baseline/validation run only — **no source,
test, config, YAML or decoder logic modified.**
**Method:** completely fresh decode of all 11 APF9 floats from raw
telemetry (operator bundle + `ref2902224/`) with the current source (all
approved fixes in place), compared against current GDAC fetched the same
day (326 files: 44 main products + 282 mono profiles), keyed on
`(cycle, direction)` and `(cycle, MC)` — never positional.

---

## 1. Fresh decode status — all 11 OK

| WMO | status | raw files | nc files |
|---|---|---|---|
| 2901304 | ok | 25 | 24 |
| 2901305 | ok | 81 | 31 |
| 2901328 | ok | 127 | 97 |
| 2901339 | ok | 73 | 76 |
| 2901350 | ok | 70 | 72 |
| 2902201 | ok | 3 | 7 |
| 2902203 | ok | 3 | 7 |
| 2902206 | ok | 3 | 7 |
| 2902222 | ok | 3 | 7 |
| 2902223 | ok | 3 | 7 |
| 2902224 | ok | 6 | 7 |

## 2. Files / NC3

**342 outputs · 342/342 `NETCDF3_CLASSIC`** (verified programmatically).

## 3. Mono profile science — PERFECT

| measure | value |
|---|---|
| cells compared | **49 008** |
| mismatches | **0** |
| recovered (ours valid, GDAC fill) | **119** (2902222 cyc329 ×30; 2902223 cyc328/329 ×89) |
| lost (GDAC valid, ours fill) | **0** |

Per float: 2901304 3510/0, 2901305 4734/0, 2901328 14928/0, 2901339
12459/0, 2901350 11745/0, 2902203 350/0, 2902222 495/0 (+30 rec),
2902223 436/0 (+89 rec), 2902224 351/0. (2902201/2902206: no GDAC mono
overlap — GDAC stops at 350/352, our archive starts 358/359.)

## 4. `_meta.nc` parity

- **65/65 variables, identical sequence, on 11/11 floats** (no
  only-ours/only-GDAC variables).
- Differing fields (all previously classified, none new):
  `SENSOR_MAKER` (11/11, approved divergence), `START_DATE` (6, sheet
  gap), `END_MISSION_DATE` (1, sheet gap), `END_MISSION_STATUS` (4,
  GDAC `0.0` oddity, approved), `FIRMWARE_VERSION`/`MANUAL_VERSION`
  (2/1, zero-padding, expected), `PREDEPLOYMENT_CALIB_COEFFICIENT` (3,
  sheet precision).

## 5. `_tech.nc` — 14/14 names everywhere; value differences

- **14/14 distinct names on every float; name set identical to GDAC.**
- 2901304: **322/322 value-exact**. 2901339: 994/994 exact.
  2901350: 938/938 exact. 2902201: no shared keys (coverage).
- Remaining value mismatches (30 cells, all previously classified):

| parameter | cells | classification |
|---|---|---|
| `PRESSURE_InternalVacuum_inHg` (1010) | 14 (2203×3, 2206×3, 2222×3, 2223×3, 2224×2) | **NOT FIXABLE** — GDAC `-28.009` = count 6 never transmitted (approved divergence) |
| `PRESSURE_InternalVacuum_inHg` (1005) | 7 (2901328×5, 2901305×2) | **NOT FIXABLE** — GDAC-implied counts (14×5, 251×1) absent from telemetry; 1 copy-selection cell, no reproducible rule |
| `PRESSURE_AirBladder_COUNT` (1010) | 6 (2206/361, 2222/328+329, 2223/329, 2224/325+326) | **NOT FIXABLE** — ±1 copy-set; exact-Coriolis round-mean 6/12 < ours 8/12 |
| `FLAG_ProfileTermination_hex` | 2 (1305/27 `601`vs`01`; 1328/85 `1D`vs`01D`) | **NOT FIXABLE** — genuine copy split (swap, net-zero); GDAC width one-off |

## 6. `_Rtraj.nc` parity (per (cycle,MC))

- **PRES: 0 mismatches on every comparable float.**
- **2901304 (full v3.1 overlap): 323 shared keys · 0 JULD diffs.**
- JULD differences, all previously classified:
  - **MC 0 (8 floats: 1339/1350/2201/2203/2206/2222/2223/2224):**
    GDAC +2 433 282.5 d (1950-epoch as astronomical JD) — **NOT
    FIXABLE / approved GDAC error** (ours = LAUNCH_DATE).
  - **MC 702/703 (2902203×1, 2902206×4, 2902222×4, 2902223×6):**
    reception-set differences (GDAC times present-or-absent in our raw;
    convention identical — proven by 2901304 323/323) — **NOT FIXABLE**.
  - 2901305/2901328: GDAC legacy v2.2 (no MC) — **EXPECTED/not
    comparable**. 2901339/2901350/2902201: GDAC Rtraj cycle-coverage
    gaps (starts 114/110, ends 350) — **DATA/COVERAGE LIMITATION**.

## 7. 2902224 cycles 325/326/345 — VALIDATED

| cycle | MC702 | MC703 | MC704 |
|---|---|---|---|
| 325 | 2026-01-01T19:24:55 = **GDAC exact** | **7/7 fixes exact** | 2026-01-02T03:11:46 = **GDAC exact** |
| 326 | 2026-01-11T17:33:00 = **GDAC exact** | **8/8 fixes exact** | 2026-01-12T02:09:44 = **GDAC exact** |
| 345 | 2026-07-20T21:04:32 (not in GDAC Rtraj) | 7 fixes (GDAC Rtraj lacks 345) | 2026-07-21T02:40:20 (not in GDAC Rtraj) |

Multi-burst mono JULD and Rtraj union both working: 325/326 fully
GDAC-exact on MC702/703/704. 345 is a coverage limitation (GDAC Rtraj
ends before cycle 345).

## 8. FileChecker (v3.0.5, `-internal-specs`)

- **33/44 FILE-ACCEPTED** — `_meta.nc`, `_tech.nc`, `_Rtraj.nc` accepted
  on **all 11 floats**.
- 11/11 `_prof.nc` rejected on the **pre-existing fleet-wide
  `VERTICAL_SAMPLING_SCHEME` warning** (documented; GDAC's own prof files
  fail differently; unrelated to this run).

## 9. Every remaining difference — consolidated classification

| # | item | scope | class |
|---|---|---|---|
| 1 | 1010 vacuum `-28.009` | 14 cells | **NOT FIXABLE** (approved GDAC divergence) |
| 2 | 1005 vacuum | 7 cells | **NOT FIXABLE** (GDAC-implied counts absent) |
| 3 | 1010 ABP ±1 | 6 cells | **NOT FIXABLE** (copy-set) |
| 4 | FLAG (cyc27, cyc85) | 2 cells | **NOT FIXABLE** (copy swap / GDAC width) |
| 5 | MC0 JULD | 8 floats | **NOT FIXABLE** (approved GDAC epoch error) |
| 6 | MC702/703 JULD | 15 cells (4 floats) | **NOT FIXABLE** (reception-set) |
| 7 | `SENSOR_MAKER` | 11 floats | **NOT FIXABLE** (approved divergence) |
| 8 | `START_DATE`/`END_MISSION_DATE`/calib precision | 6/1/3 | **DATA/COVERAGE LIMITATION** (sheet gaps) |
| 9 | `END_MISSION_STATUS` | 4 floats | **NOT FIXABLE** (approved GDAC oddity) |
| 10 | zero-padded versions | 3 | **EXPECTED** (representation) |
| 11 | `_prof.nc` FileChecker warning | 11 floats | **EXPECTED/NOT FIXABLE** (fleet-wide; needs spec decision) |
| 12 | 1005 Rtraj coverage / legacy v2.2 | 5 floats | **DATA/COVERAGE LIMITATION** (GDAC-side) |
| 13 | 2902201/2902206 mono overlap | 2 floats | **DATA/COVERAGE LIMITATION** |

**FIXABLE: none remaining** (the one former FIXABLE item — prof.nc
variable order — remains unimplemented by prior decision, not a new
finding).

## 10. Comparison with the previous baseline — no regressions

| measure | previous baseline | this run |
|---|---|---|
| mono science cells | 48 508 · 0 mismatches | **49 008 · 0 mismatches** (more GDAC mono fetched) |
| 2902224 MC703/704 | 7/8 + MC704 exact (after fix) | **unchanged, exact** |
| 2901304 Rtraj | 323/323 exact | **323/323 exact** |
| 1010/1005 vacuum, ABP, FLAG | 30 cells | **identical 30 cells** (same classification) |
| NC3 | 342/342 | **342/342** |
| FileChecker | 33/44 | **33/44** |

**No new decoder problem surfaced by this fresh run.** Every remaining
difference matches the established evidence-based classification.

## 11. Verdict

- **APF9 (core CTD, 1005 + 1010) is ready to be FROZEN** for parity
  purposes: science is 100 % (49 008 cells, 0 mismatches, 119 recovered),
  structure is exact (meta 65/65, tech 14/14, Rtraj 102 vars), NC3
  everywhere, FileChecker clean on all products except the documented
  pre-existing `_prof.nc` warning, and 2902224's previously-broken
  multi-burst cycles are now fully GDAC-exact.
- Remaining differences are **all** evidence-classified NOT FIXABLE /
  EXPECTED / DATA-LIMITATION items (GDAC-side values, reception sets,
  sheet gaps, approved divergences) — none is a decoder defect.
- **Recommended: proceed to the next float family** (e.g. APEX Iridium /
  APF11, PROVOR/ARVOR, or BGC APEX), per the project roadmap. The APF9
  open items that remain are data/operator requests (START_DATE column,
  INCOIS reception sets, `_prof.nc` VERTICAL_SAMPLING_SCHEME decision),
  not decoder work.

---

*Baseline/validation only. Source tree unchanged: no src/test/config/
YAML file was modified during this run (verified). Raw telemetry and GDAC
references retained; all regenerable run artifacts removed.*
