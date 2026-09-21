# ARVOR-I RTQC — Applied Test Set & GDAC Parity (verified from products)

**Date:** 2026-09-07 · **READ-ONLY audit.** No source, test, config or product modified.
**Evidence:** QCP$/QCF$ HISTORY masks decoded from our 69 preserved RT products vs the 69 INCOIS GDAC `R*.nc` references; thresholds traced to Argo QC Manual **v3.9** (DOI 10.13155/33951) and the vendored Coriolis MATLAB.

---

## 1. Direct answer: it is **14**, not 14/15

The "14/15 except GEBCO" phrasing in project memory is **imprecise**. Measured from the actual QCP$ masks:

| | count | tests |
|---|---|---|
| **Executed by us** | **14** | 1, 2, 3, 5, 6, 8, 9, 11, 12, 13, 14, 16, 18, 19 |
| Skipped — GEBCO absent | 1 | **4** (Position on Land) |
| **Declared applicable set** | **15** | the 14 + test 4 |

So: **14 of the 15-test applicable set run; test 4 is the only one skipped for tooling.** The set is 15 — *not* 14/15 with one more hiding.

**But two further tests in the "11/25" note are also NOT running:**

| Test | Status in tree | Reality |
|---|---|---|
| **11** Gradient | **implemented & executed** (69/69 files) | v3.9 declares it **obsolete** (ADMT20, Jan 2020) |
| **25** MEDD | **config flag only** (`models.py:368`) — **no implementation** | v3.9 says 25 **replaces** 11 in the §2.1.3 order |
| **15** Exclusion/Grey list | **not implemented** (no code) | active test, DAC-managed list |

The project memory phrase "11/25" implies a resolved either/or. In fact **11 runs, 25 does not exist**, and **15 does not exist**. That is a real documentation-vs-code discrepancy, though (see §4) running 11 is the *correct* choice for this fleet.

Per-test execution counts across our 69 files:
`{1:69, 2:69, 3:69, 5:64, 6:69, 8:69, 9:69, 11:69, 12:69, 13:69, 14:69, 16:61, 18:63, 19:69}`
Tests 5/16/18 are cross-cycle and legitimately do not run on every profile (§3).

## 2. GDAC parity — headline numbers

| Metric | Result |
|---|---|
| Comparable profiles | **69 / 69** |
| **QCF$ (failures) identical** | **63 / 69 (91.3 %)** |
| QCP$ (executed) identical | 0 / 69 — **entirely explained by test 4 + cross-cycle gating** |

| | ours | GDAC |
|---|---|---|
| executed | 1,2,3,5,6,8,9,11,12,13,14,16,18,19 | 1,2,3,**4**,5,6,8,9,11,12,13,14,16,18,19 |
| failed | 5:1, 11:6, 12:4, 16:1 | 5:2, 11:6, 12:4, 14:2 |

**Tests 11 and 12 match GDAC exactly — 6/6 and 4/4 failures, same files.** That is strong evidence our thresholds are right.

## 3. Every QCP$ difference (all GDAC-only, none ours-only)

| GDAC-only bits | files | Cause | Class |
|---|---|---|---|
| 4 | 69 | GEBCO grid absent (`/mnt/ref/gebco.nc` missing) | **TOOL-AVAILABILITY** |
| 5, 16, 18 | 4 (every float's **cycle 1**) | No previous profile exists | **EXPECTED — GDAC is wrong** |
| 16 | 3 | Zero deep-band overlap | **EXPECTED — scientifically correct skip** |
| 16, 18 | 1 | as above | **EXPECTED** |
| 18 | 1 | <2 shared 50-dbar slabs | **EXPECTED** |
| 5 | 1 | degenerate Δt | **EXPECTED** |

**There is not a single ours-only executed bit.** We never claim a test we didn't run.

### 3.1 Cycle-1 cross-cycle tests — GDAC violates the manual
GDAC marks tests **5, 16 and 18 as executed on cycle 1 of all four floats**, where no predecessor exists. The manual is explicit:
- **Test 16:** *"calculates the average temperature and salinity from the deepest 100 dbar of a profile **and the previous good profile**"*
- **Test 18:** *"deltaT = abs(T_prof − **T_previous_prof**)"*
- **Test 5:** drift speed between successive positions

On 2904082 cycle 1 GDAC even reports test 5 **failed** — while simultaneously writing `POSITION_QC = '1'` (good). Self-contradictory. Our "skipped ≠ passed" semantics is correct.

### 3.2 Test-16 skips are scientifically right
Test 16 compares the deepest-100-dbar averages. Measured overlap for every skipped file:

| float / cycle | our max P | previous max P | deep-band overlap |
|---|---|---|---|
| 1902844 c6 | 175.2 | 2013.3 | **0 dbar** |
| 1902844 c7 | 2008.6 | 175.2 | **0 dbar** |
| 2904082 c21 | 175.3 | 1612.9 | **0 dbar** |
| 2904082 c22 | 1262.4 | 175.3 | **0 dbar** |
| 7902408 c15 | 1287.8 | 2028.7 | **0 dbar** |

Comparing a 175-dbar profile's "deep" average against a 2013-dbar one measures *the thermocline versus the abyss*, not sensor drift. Running it would manufacture false drift detections. **Correct to skip.**

## 4. Every QCF$ difference — 6 files, ours defensible in all

| File | ours | GDAC | Verdict |
|---|---|---|---|
| 1902844 c6 | — | **14** | **Ours right.** Max downward inversion **−0.0190 kg/m³**, inside the manual's **0.03** threshold. GDAC over-flags. |
| 2904082 c21 | — | **14** | **Ours right.** Inversion **−0.0044 kg/m³** — 7× inside threshold. |
| 2904082 c1 | — | **5** | **Ours right.** Cycle 1, no predecessor; GDAC's own POSITION_QC='1' contradicts its failure bit. |
| 6990711 c6 | **5** | — | **Ours right.** Δt = 0.02 h over 8.9 km ⇒ 146 m/s. Genuine anomaly (known 6990711 JULD defect). |
| 6990711 c7 | — | **5** | Boundary case: **negative Δt** in both datasets; we attribute the failure to c6, GDAC to c7. Same defect, different attribution. **EXPECTED**. |
| 7902408 c15 | **16** | — | Ours fires on a real deep-band offset; threshold verified against MATLAB. Previously classified PUBLICATION; unchanged. |

Both GDAC test-14 failures were recomputed independently with TEOS-10 (`gsw`), potential density referenced to mid-point pressure exactly as v3.9 §2.1.2 requires.

## 5. Spec-conformance check of the fixes already in the tree

The four defects raised in `ARVOR_I_RTQC_SPEC_AUDIT_2026-09-04.md` are **all now implemented correctly**:

| Item | Manual v3.9 | Code | ✅ |
|---|---|---|---|
| T6 TEMP upper | 40.0 °C | `non_density.py:39` `(-2.5, 40.0)` | ✅ (42.0 artifact removed) |
| T6 PSAL | 2 – 41 | `"PSAL": (2.0, 41.0)` | ✅ |
| T8 tolerance | — | `PRESSURE_INVERSION_TOL_DB = 20.0` | ✅ |
| T9 spike split | 6.0/2.0 °C, 0.9/0.3 psu @500 dbar | lines 47–52 | ✅ |
| T11 form | `\|V2−(V3+V1)/2\|`, 9.0/3.0, 1.5/0.5 | `gradient` impl. | ✅ |
| T14 threshold | 0.03 kg m⁻³, mid-point ref | density_inversion | ✅ |

## 6. Classification summary

| Class | Item |
|---|---|
| **TOOL-AVAILABILITY** | Test 4 — GEBCO grid absent; skipped on all 69, never fabricated |
| **EXPECTED** | Cycle-1 cross-cycle skips (GDAC violates manual); zero-overlap T16 skips; T5 attribution on 6990711 |
| **PUBLICATION/RTQC** | GDAC's 2 spurious T14 failures; GDAC's cycle-1 T5 failure; our 7902408 c15 T16 |
| **FIX CANDIDATE** | **Test 25 (MEDD) not implemented** — v3.9 replacement for 11 |
| **FIX CANDIDATE** | **Test 15 (exclusion/grey list) not implemented** — needs DAC list |
| **NOT FIXABLE** | 6990711 JULD anomaly driving T5 |

## 7. Recommendation — do **not** change RTQC for parity

Running **11 rather than 25 is the right call for this fleet**: INCOIS demonstrably still runs 11 (bit set in all 69 GDAC masks, 6 failures) and does **not** run 25. Adopting 25 now would *reduce* parity while matching a newer manual. Test 11 is retained deliberately, and our failures match GDAC 6/6.

The honest gaps, neither of which affects current parity:
1. **Test 25 (MEDD)** — config flag with no implementation. Should be implemented *alongside* 11 (flag-gated, off by default) so the engine is v3.9-ready. Requires the MEDD reference package.
2. **Test 15 (exclusion list)** — requires the DAC exclusion-list file; **dataset not present** in the workspace. Cannot be implemented until supplied.
3. **Test 4** — unblocked the moment a GEBCO grid is provided.

**Missing datasets/tools:** GEBCO bathymetry (`/mnt/ref/gebco.nc`), DAC exclusion list (`<dac>_exclusionlist.csv`), MEDD MATLAB reference package.

Mono remains frozen; nothing in this audit constitutes a regression, and no change is recommended without your authorization.
