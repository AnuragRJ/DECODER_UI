# CTS4 Real-Time QC — Implementation Matrix and Evidence

**Date:** 2026-09-15
**Scope:** final real-time QC pass before the CTS4 freeze. No decoder
architecture work; no change made to match the GDAC without a manual or
Coriolis source behind it.

---

## 1. What was added

| File | Change |
|---|---|
| `src/argo_decoder/rtqc/cts4.py` | New module: `run_cts4_rtqc()` and the CTS4 test battery |
| `src/argo_decoder/writer/nc.py` | `_build_rtqc_levels()` feeds RTQC into `<PARAM>_QC`; `_write_qc_vars()` accepts per-level arrays; new `compute_profile_quality_flag()` derives `PROFILE_<PARAM>_QC` |
| `tests/unit/test_rtqc_cts4.py` | 55 unit tests |
| `tests/test_provor_cts4_rtqc_integration.py` | 4 end-to-end tests on a real fleet decode |

Before this pass the writer published a **flat** `1` (or `0` for the four raw
channels) on every QC array and a hard-coded `A` on every profile flag. No
real-time QC ran at all.

## 2. Test matrix

Every threshold below is taken from a manual or from Coriolis source. None is
fitted to GDAC data.

### CTD — TEMP / PSAL (`non_density.py`, reused)

| # | Test | Source | Action |
|---|---|---|---|
| 6 | Global range | QC Manual v3.9; TEMP −2.5…40.0 °C, PSAL 2…41 psu | `4` |
| 9 | Spike | QC Manual v3.9, 500 dbar split | `4` |
| 11 | Gradient | v3.9 (obsolete, retained for INCOIS parity) | `4` |
| 12 | Digit rollover | v3.9 | `4` |
| 13 | Stuck value | v3.9, whole-profile rule | `4` |
| 21 | **Near-surface unpumped CTD** | `add_rtqc_to_profile_file.m:2402` | `3` on all defined PSAL |
| 22 | **Near-surface air/water** | `add_rtqc_to_profile_file.m:2483`, NKE branch | `3` where `PRES ≤ 1 dbar` (0.5 if `discrete` VSS) |

### BGC

| Param | Tests | Manual | Action |
|---|---|---|---|
| `DOXY` | 6, 9, 11, 12, 13, **57** | DOXY v2.2 §2.2.1/§2.2.2 | `3` always (optode predeployment drift, median sensitivity loss 7.6%); `PRES_QC=4` or `TEMP_QC=4` → `4`; `PSAL_QC=4` leaves it at `3` |
| `TEMP_DOXY` | 6, 9, 11, 12, 13 | DOXY v2.2 | may reach `1` |
| `CHLA` | 6, 13, **63** | CHLA v3.0 §2.2.2 | `3` always; range −0.2…100 mg/m³ |
| `CHLA_FLUORESCENCE` | 6, 13 | CHLA v3.0 | may reach `1` |
| `BBP700` | 13, **62** (5 sub-tests) | BBP v1.0 §2.2.2 | `1` if all pass — the only derived BGC parameter allowed to earn `1` in real time |
| `C1PHASE_DOXY`, `C2PHASE_DOXY`, `FLUORESCENCE_CHLA`, `BETA_BACKSCATTERING700` | 13 only | DOXY/CHLA v-common §2.2.1 | stay `0`; never promoted to `1` |

BBP 62 sub-tests: 62.1 missing data (1 bin → `4`, 2–9 bins → `3`);
62.2 high deep value (median medfilt below 700 dbar > 5e-4 → `3`);
62.3 negatives (`<5 dbar` and `<0` → `4`; deep 0<pct<10 → `3`, ≥10% → `4`);
62.4 noisy (≥10% of sub-100 dbar residuals > 5e-4 → `3`);
62.5 parking hook (deepest 50 dbar above baseline+2e-4 → `4`), aborted
without `PARK_PRES` or when `|max PRES − PARK_PRES| ≥ 100 dbar`.

No global range is applied to the four raw IB-Argo channels — no manual
publishes one, so none was invented.

### Profile-level flag (Argo reference table 2a)

`compute_profile_quality_flag.m` ported exactly. Levels coded blank / `0` /
`9` are inert; of the rest the fraction coded good (`1`,`2`,`5`,`8`) selects
the letter — 100% `A`, then `B`, `C`, `D`, `E`, 0% `F`. An all-`0` parameter
therefore publishes **no** profile flag, which is why the four raw channels
now leave `PROFILE_*_QC` blank.

## 3. Verification

| Check | Result |
|---|---|
| `pytest tests/ -q` | **2441 passed, 1 skipped** |
| Fleet, all 10 raw groups | **10/10 OK, 274 .nc** |
| OneArgo FileChecker v3.0.5, `incois` specs | **274/274 FILE-ACCEPTED, 0 FORMAT-ERRORS**, 10 warnings (all the known `PI_NAME 'M Ravichandran'`) |
| `prove_cts4_generic_path.py` | **static=PASS dynamic=PASS** |
| QC parity vs live GDAC, 2902093 cycles 45–53, 18 profiles | **61 776 / 61 776 per-level cells exact** on all 12 real-time QC arrays |

Mutation testing: 16 deliberate faults injected (thresholds, flag codes, VSS
matching, guard clauses, the profile-flag port, reverting the writer to a flat
`A`). Every one was caught by at least one test.

## 4. Remaining differences from the GDAC — classification

| Difference | Evidence | Classification |
|---|---|---|
| `PROFILE_CHLA_QC` ours `F`, GDAC `A` (9 cells, BR 45–53) | GDAC per-level `CHLA_QC` is all `3`, identical to `DOXY_QC`, yet GDAC gives DOXY `F` and CHLA `A`. On the delayed-mode BD files of 2902130/2902131 DOXY all-`3` also yields `A`. No single rule reproduces both. | **NOT A DEFECT (ours) / GDAC INCONSISTENT.** We apply the documented rule; the GDAC value is the outlier. FileChecker accepts ours. |
| `CHLA_ADJUSTED_QC`, `CHLA_FLUORESCENCE_ADJUSTED_QC`, `BBP700_ADJUSTED_QC` blank vs GDAC `1`/`5` (3861 cells) | Deliberate: `*_ADJUSTED` stays FillValue in R/BR mode (FileChecker: "DATA_MODE 'R': *_ADJUSTED must be FillValue"). Pre-existing, untouched by this pass. | **EXPECTED (R-mode contract)** |
| `PI_NAME 'M Ravichandran'` warning ×10 | FileChecker warns identically on INCOIS's own file. | **NOT A DEFECT** |

## 5. Two real defects found and fixed

1. **`PROFILE_DOXY_QC` was `A` where the spec requires `F`.** Every DOXY level
   is `3` by test 57, so the good fraction is 0 and the flag must be `F`.
   FileChecker rejected all 274 files on this alone
   (`PROFILE_DOXY_QC[3]: Value = 'A'. Expected = 'F'`). Fixed by deriving the
   flag instead of assuming it.
2. **The four raw channels wrongly carried `PROFILE_*_QC = 'A'`.** Their
   per-level QC is all `0`, i.e. no QC performed, so no profile flag may be
   claimed.

## 6. One crash fixed

`run_cts4_rtqc` raised `ValueError: operands could not be broadcast together
with shapes (143,) (0,)` and rejected **8 of 10 floats**. `R_STATION_PARAMETERS_TEMPLATE`
publishes `["PRES", "", ""]` rows, so a profile can carry pressure with no
measurement; a zero-length parameter array reached the range test, which
broadcasts it against the full-length `PRES`. A zero-length array now means
"not measured", and a length mismatch is skipped rather than crashing.
Guards are mutation-verified.
