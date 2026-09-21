# CTS4 RTQC — Complete Test Inventory and Implementation Matrix

**Date:** 2026-09-15
**Scope:** exhaustive enumeration of the Argo real-time QC test universe
applicable to PROVOR CTS4 / decoder-301, with every test classified. This
supersedes the partial matrix in `RTQC_MATRIX.md`.

---

## 1. Sources used, with exact versions

| Ref | Document | Version / date | Location |
|---|---|---|---|
| **S1** | Argo Quality Control Manual for CTD and Trajectory Data (Wong, Keeley, Carval) | **v3.9, 20 Feb 2025** | DOI 10.13155/33951 (cited via `docs/phase_reports/ARVOR_I_RTQC_SPEC_AUDIT_2026-09-04.md` §1, D1) |
| **S2** | `add_rtqc_to_profile_file.m` | Coriolis MATLAB, **7912 lines**, `lastTestNum = 63` | `tests/data/arvor_i/coriolis_src/add_rtqc_to_profile_file.m` |
| **S3** | Production test-enable list | `testToPerformList`, CORIOLIS block | `Coriolis-…/decArgo_soft/soft/util/nc_add_rtqc_flags_prof_and_traj.m:76-105` |
| **S4** | Decoder-ID gate lists | `g_decArgo_decoderIdList*` | `Coriolis-…/decArgo_soft/soft/util/ge_generate_traj_from_csv_estimate_profile_position_SA.m:1692-1709` |
| **S5** | MEDD reference implementation | D. Dobler, IFREMER, v1.2 (2019-11-20) / v1.1 (2019-11-06 / 2019-11-05) | `Coriolis-…/decArgo_soft/soft/sub_foreign/QTRT_spike_check_MEDD{,_main}.m`, `relative_2D_distance.m` |
| **S6** | Processing Argo OXYGEN data at the DAC level | **v2.3.4, 22 Apr 2025** | `provor_bio_irsbd/ref/cook_oxy.pdf` |
| **S7** | Processing Argo BACKSCATTERING data | `provor_bio_irsbd/ref/cook_bbp.pdf` | same |
| **S8** | INCOIS GDAC per-profile QCP$/QCF$ masks | live, 2902093 cycles 45–53 | `HISTORY_ACTION` + `HISTORY_QCTEST`, 18 files |

**Decoder ID:** 301. `g_decArgo_decoderIdListNkeMisc = [301, 302, 303]` (S4:1709).
301 is **not** in `NkeIridiumDeep` `[201,202,203,215,216,218,221,228,229,230]`
and **not** in `NkeIridiumRbr` `[224,226,227,228,229]`. Therefore
`deepFloatFlag = 0`, `rbrFloatFlag = 0`, `apexFloatFlag = 0`, and
`floatDecoderId < 1000` is true (the NKE branch).

**Sensors (from `incois_2902093_meta.nc`):** `CTD_PRES`/`CTD_TEMP`/`CTD_CNDC`
= SBE **SBE41CP**; `OPTODE_DOXY` = **AANDERAA_OPTODE_4330**;
`FLUOROMETER_CHLA` and `BACKSCATTERINGMETER_BBP700` = WETLABS **ECO_FLBB**.

**Document limitation (declared):** the two PDFs that would corroborate S1
firsthand — `implementation_of_RTQC_at_coriolis_V1.6_20250303.pdf` and
`argo_coriolis_matlab_decoder_V1.10_20251112.pdf` — are **132-byte Git LFS
pointers** in this workspace, not readable PDFs. S1's test list is therefore
taken from the prior audited extract plus the executable MATLAB source (S2),
which is the stronger authority in any case.

---

## 2. The enumerated universe

S2 contains **30 test blocks**. S3 enables **29** of them for production and
disables **2** (`TEST016` and `TEST018` are `{0}`). S1 additionally lists
tests 10, 17 and 20, which have no block in S2 or are non-mandatory. The full
universe is therefore **33 distinct test numbers**.

---

## 3. CTD matrix — `PRES`, `TEMP`, `PSAL`

| ID | Test name | Threshold / rule | Source | RT applicable to CTS4? | Implemented? | QC action | Coriolis implementation | GDAC evidence |
|---|---|---|---|---|---|---|---|---|
| 1 | Platform identification | WMO in decoder table | S1, S2:1974 | **IMPLEMENTED** | **YES** | mask bit | "nothing implemented; always reported passed" | QCP$ bit 1 set, 9/9 |
| 2 | Impossible date | 17167 ≤ JULD < now | S1, S2:1982 | **IMPLEMENTED** | **YES** | `JULD_QC 4` | implemented | bit 2 set, 9/9 |
| 3 | Impossible location | ±90 / ±180 | S1, S2:2017 | **IMPLEMENTED** | **YES** | `POSITION_QC 4` | implemented | bit 3 set, 9/9 |
| 4 | Position on land | bathymetry lookup | S1, S2:2040 | **IMPLEMENTED** | **YES** (aborts without a GEBCO grid) | `POSITION_QC 4` | `GEBCO_2024.nc` | bit 4 set, 9/9 |
| 5 | Impossible speed | > 3 m/s between fixes | S1, S2:2079 | **IMPLEMENTED** (this pass) | **YES** | `POSITION_QC 4` | implemented | bit 5 set, 9/9; QCF$ never set for 5 |
| 6 | Global range | PRES ≥ −5, [−5,−2.4]→`3`; TEMP −2.5…40; PSAL 2…41 | S1, S2:2694 | **IMPLEMENTED** | **YES** | `4` / `3` | verbatim | bit 6 set, 9/9 |
| 7 | Regional range | Red Sea / Mediterranean only | S1, S2:2946 | **NOT APPLICABLE** | no | — | implemented | bit 7 **clear** on all 18 |
| 8 | Pressure increasing | `PRES_reversal` = 20 dbar | S1 (2024 rev.), S2:3045 | **IMPLEMENTED** | **YES** | `4` | `PRES_REVERSAL = 20` | bit 8 set, 9/9 |
| 9 | Spike | T 6.0/2.0 °C, S 0.9/0.3 psu @500 dbar | S1, S2:3148 | **IMPLEMENTED** | **YES** | `4` | verbatim triplicate | bit 9 set, 9/9 |
| 10 | Top/bottom spike | — | S1 | **OBSOLETE** (ADMT4, Oct 2003) | no | — | absent | — |
| 11 | Gradient | \|V2−(V1+V3)/2\|, T 9 / S 1.5 shallow | S1 (obsolete ADMT20), S2:3378 | **IMPLEMENTED** | **YES** | `4` | retained for INCOIS parity | bit 11 set on **BR prof2 only** |
| 12 | Digit rollover | ΔT > 10 °C, ΔS > 5 psu | S1, S2:3659 | **IMPLEMENTED** | **YES** | `4` | verbatim | bit 12 set, 9/9 |
| 13 | Stuck value | whole profile identical | S1, S2:3747 | **IMPLEMENTED** | **YES** | `4` | verbatim | bit 13 set (prof0/2/3) |
| 14 | Density inversion | σ ≥ 0.03 kg/m³, mid-point ref, both directions | S1, S2:3818 | **IMPLEMENTED** (this pass) | **YES** | `4` on TEMP+PSAL | `potential_density_gsw`, 0.03 verbatim | bit 14 set on **R prof0 only** |
| 15 | Exclusion list | DAC-managed external file | S1, S2:2119 | **NOT POSSIBLE IN REAL TIME HERE** | no | external `qcVal` | reads `exclusionListPathFileName` | bit 15 set, but **no exclusion-list file exists** in the workspace, so it can flag nothing |
| 16 | Gross sensor drift | ΔS > 0.5 psu, ΔT > 1 °C in a common deep band | S1, S2:4078 | **IMPLEMENTED** (this pass) | **YES** | `3` | **disabled `{0}`** in S3, needs multi-profile file | bit 16 **clear** on 2902093 |
| 17 | Visual QC | manual inspection | S1 | **NOT APPLICABLE** ("not mandatory before real-time distribution") | no | — | absent | — |
| 18 | Frozen profile | 50 dbar slabs; T .3/.001/.02, S .3/.001/.004 | S1, S2:4227 | **IMPLEMENTED** (this pass) | **YES** | `4` | **disabled `{0}`** in S3, needs multi-profile file | bit 18 **clear** on 2902093 |
| 19 | Deepest pressure | ramp 150 %@10 dbar → 10 %@1000, **+100 dbar flat above** | S1, S2:2233, `compute_max_pres_for_rtqc_test19:7243` | **IMPLEMENTED** (this pass) | **YES** | `3` | verbatim | bit 19 set, 9/9 |
| 20 | Questionable Argos position | Argos-only | S1, DAC cookbook Annex H | **NOT APPLICABLE** (Iridium SBD) | no | — | **no block in S2 at all** | bit 20 clear |
| 21 | Near-surface unpumped salinity | unpumped CTD → PSAL `3` | S2:2402 | **IMPLEMENTED** | **YES** | `3` on all defined PSAL | `apexFloatFlag == 0` → applies | bits 21+22 set on **prof1**, QCF$ = `{21,22}` 9/9 |
| 22 | Near-surface air/water | `PRES ≤ 1 dbar` (0.5 if `discrete`) → TEMP `3` | S2:2478, NKE branch | **IMPLEMENTED** | **YES** | `3` on TEMP | NKE branch, TEMP only | as above |
| 23 | Deep float > 2000 dbar | deep-float flag scheme | S2:4586 | **NOT APPLICABLE** | no | — | `deepFloatFlag` gate; **301 not in the deep list** (S4:1693) | bit 23 clear |
| 24 | Pre-April-2021 RBR | RBR salinity `3` | S2:4519 | **NOT APPLICABLE** | no | — | `g_decArgo_rbrPreApril2021FloatList`; sensor is SBE, not RBR | bit 24 clear |
| 25 | MEDD | median-with-distance envelope | S1, S2:3484, S5 | **IMPLEMENTED** (this pass) | **YES** | `4` on **TEMP only** | `QTRT_spike_check_MEDD_main`, captures **only `tempSpike`** | bit 25 set on **R prof0+prof1**, QCF$ shows **no** MEDD failure on 9/9 |
| 26 | TEMP_CNDC | RBR-only scheme | S2:4414 | **NOT APPLICABLE** | no | — | `rbrFloatFlag` gate; **301 not in the RBR list** | bit 26 clear |

**CTD: 16 implemented / 16 applicable.**

The applicable set is 1, 2, 3, 4, 5, 6, 8, 9, 11, 12, 13, 14, 19, 21, 22, 25.
Tests 21 and 22 are near-surface-conditional and both are implemented, so all
16 are implemented.

*Note on the "14 applicable" figure in the task statement:* the always-on
subset — excluding the two near-surface-conditional tests 21 and 22 — is 14.
Both figures describe the same battery; this inventory counts 16 because the
near-surface profiles are real and INCOIS runs 21/22 on them (QCP$ bits set on
prof1 of every R and BR file, with QCF$ = `{21,22}` on 9/9 cycles).

Test 8 is recorded on **PRES**, not on TEMP/PSAL: it is a property of the
pressure series. `run_cts4_rtqc` did not score PRES at all before this pass,
so test 8 never ran; see §6 defect 6.

---

## 4. BGC matrix

| ID | Parameter(s) | Test | Rule | Source | Applicable? | Implemented? | QC action | GDAC evidence |
|---|---|---|---|---|---|---|---|---|
| 57 | DOXY | DOXY specific | real-time unadjusted DOXY → `3`; `PRES_QC=4` or `TEMP_QC=4` → `4`; `PSAL_QC=4` leaves `3` | S2:4919 | **IMPLEMENTED** | **YES** | `3` / `4` | bit 57 + QCF$ `{57}` on BR prof2, 9/9 |
| 62 | BBP700 | BBP specific | 5 sub-tests (62.1–62.5); `1` if all pass | S2:5356, S7 | **IMPLEMENTED** | **YES** | `1`/`3`/`4` | bit 62 + QCF$ `{63,62}` on BR prof3 |
| 62.1 | BBP700 | missing data | 1 bin → `4`; 2–9 bins → `3` | S7 | **IMPLEMENTED** | **YES** | `4`/`3` | — |
| 62.2 | BBP700 | high deep value | median medfilt < 700 dbar > 5e-4 → `3` | S7 | **IMPLEMENTED** | **YES** | `3` | — |
| 62.3 | BBP700 | negatives | `<5 dbar` & `<0` → `4`; deep 0<pct<10 → `3`, ≥10% → `4` | S7 | **IMPLEMENTED** | **YES** | `4`/`3` | — |
| 62.4 | BBP700 | noisy | ≥10% of sub-100 dbar residuals > 5e-4 → `3` | S7 | **IMPLEMENTED** | **YES** | `3` | — |
| 62.5 | BBP700 | parking hook | deepest 50 dbar above baseline+2e-4 → `4`; aborts without `PARK_PRES` or when \|maxPRES−PARK_PRES\| ≥ 100 | S7 | **IMPLEMENTED** (this pass — see §6) | **YES** | `4` | — |
| 63 | CHLA | CHLA specific | real-time CHLA → `3` | S2:5514 | **IMPLEMENTED** | **YES** | `3` | bit 63 + QCF$ `{63}`, 9/9 |
| 6/13 | CHLA | global range / stuck | −0.2…100 mg/m³ | S6, S2 | **IMPLEMENTED** | **YES** | `4` | — |
| 6/13 | CHLA_FLUORESCENCE | global range / stuck | −0.2…100 | S6, S2 | **IMPLEMENTED** | **YES** | `1` if clean | — |
| 6/13 | TEMP_DOXY | global range / stuck | −2.5…40 °C | S6 | **IMPLEMENTED** | **YES** | `1` if clean | — |
| 13 | C1PHASE_DOXY | stuck value only | whole profile identical → `4` | S2 common list | **IMPLEMENTED** | **YES** | stays `0` otherwise | QC `0` on all 5148 cells |
| 13 | C2PHASE_DOXY | stuck value only | as above | S2 | **IMPLEMENTED** | **YES** | stays `0` | QC `0` |
| 13 | FLUORESCENCE_CHLA | stuck value only | as above | S2 | **IMPLEMENTED** | **YES** | stays `0` | QC `0` |
| 13 | BETA_BACKSCATTERING700 | stuck value only | as above | S2 | **IMPLEMENTED** | **YES** | stays `0` | QC `0` |
| 56 | PH | PH specific | — | S2:4687 | **NOT APPLICABLE** (no PH sensor) | no | — | bit 56 clear |
| 59 | NITRATE | NITRATE specific | — | S2:5108 | **NOT APPLICABLE** (no sensor) | no | — | bit 59 clear |
| 60 | PAR | PAR specific | — | S2:5270 | **NOT APPLICABLE** (no sensor) | no | — | bit 60 clear |
| 61 | IRRADIANCE | IRRADIANCE specific | — | S2:5306 | **NOT APPLICABLE** (no sensor) | no | — | bit 61 clear |
| — | C1PHASE/C2PHASE/FLUORESCENCE/BETA | global range | — | — | **UNKNOWN / INSUFFICIENT AUTHORITY** | no | — | No manual publishes a range for these raw IB-Argo channels, so none was invented |

**BGC: 15 implemented / 15 applicable** (counting the five BBP sub-tests as one
test 62 with five parts: 57, 62, 63, plus the range/stuck battery on
TEMP_DOXY / CHLA / CHLA_FLUORESCENCE and test 13 on the four raw channels).

---

## 5. Overall

**Overall: 31 implemented / 31 applicable** (16 CTD + 15 BGC), out of a
33-number universe. Nothing applicable to CTS4 is left unimplemented.

Classified as not implementable here:

| ID | Classification | Reason |
|---|---|---|
| 7 | NOT APPLICABLE TO CTS4 | Red Sea / Mediterranean only; INCOIS floats are Indian Ocean. QCP$ bit clear on all 18 files. |
| 10 | NOT APPLICABLE | Obsolete, ADMT4 Oct 2003. |
| 15 | NOT POSSIBLE IN REAL TIME | Requires a DAC-managed exclusion-list file that does not exist in this workspace; without it the test can flag nothing. |
| 17 | NOT APPLICABLE | Visual QC, "not mandatory before real-time distribution". |
| 20 | NOT APPLICABLE | Argos-only; CTS4 is Iridium SBD. No block in S2. |
| 23 | NOT APPLICABLE | Deep-float gate closed: decoder 301 ∉ `NkeIridiumDeep`. |
| 24 | NOT APPLICABLE | RBR-only; sensors are SBE41CP / Aanderaa / ECO_FLBB. |
| 26 | NOT APPLICABLE | RBR-only; `rbrFloatFlag = 0` for decoder 301. |
| 56, 59, 60, 61 | NOT APPLICABLE | No PH / NITRATE / PAR / IRRADIANCE sensor on this float family. |

---

## 6. Defects found and fixed in this pass

1. **Five applicable CTD tests existed in the engine but were never called for
   CTS4.** `deepest_pressure_test` (19), `density_inversion_test` (14),
   `impossible_speed_test` (5), `gross_sensor_drift_test` (16) and
   `frozen_profile_test` (18) were all present and spec-exact, but `cts4.py`
   invoked none of them. All five are now wired.

2. **MEDD (25) was absent entirely.** Ported from S5 as
   `rtqc/medd.py`. A first version applied MEDD's salinity output and flagged
   **22 halocline levels on 6 of 9 cycles** that INCOIS leaves good. The
   Coriolis caller (S2:3636-3645) captures **only `tempSpike`** and discards
   `SPIKE_S`; correcting this gives **exact agreement** — MEDD runs on all 9 R
   cycles and fails on none, matching INCOIS's QCF$ masks.

3. **BBP test 62.5 (parking hook) had never once run.** `_build_rtqc_levels`
   never passed `park_pres`, so the sub-test aborted on every profile of every
   float since it was written. Now fed from `CONFIG_ParkPressure_dbar`.

4. **Test 19 had no configuration input.** `CONFIG_ProfilePressure_dbar` is
   present in the metadata (2000 dbar for 2902093) but was never threaded to
   RTQC. Now read from `ExternalMeta`.

5. **Tests 5/16/18 had no predecessor.** The writer is called per cycle and
   never carried the previous cycle's profile forward. `prev_primary_profile`
   tracking is now maintained across the cycle loop.

6. **Test 8 never ran at all.** `pressure_increasing_test` is called inside
   `_run_ctd_param` behind a `name == "PRES"` guard, but the parameter loop in
   `run_cts4_rtqc` covered only TEMP and PSAL — so the guard was never
   reached. PRES is now scored as a parameter in its own right, and tests 6,
   8, 13 and 19 all record against it. Per-level parity against INCOIS is
   unchanged at 61 776/61 776.

---

## 7. Verification

| Check | Result |
|---|---|
| `pytest tests/ -q` | **2464 passed, 1 skipped** |
| Fleet, all 10 raw groups | **10/10 OK, 274 .nc** |
| FileChecker v3.0.5, `incois` | **274/274 FILE-ACCEPTED, 0 FORMAT-ERRORS**, 10 warnings (all the known `PI_NAME`) |
| `prove_cts4_generic_path.py` | **static=PASS dynamic=PASS** |
| Per-level QC parity vs INCOIS R/BR, 2902093 cy45–53 | **61 776 / 61 776 exact** on all 12 real-time QC arrays |
| D/BD production | **none** — `DATA_MODE` is `R` throughout, 0 `D`/`BD` files |
| Four legacy CSVs | **unchanged** (`calib`, `config_params`, `meta`, `sensor-info` hashes recorded) |
| Mutation testing | **26 injected faults**, every one caught by ≥1 test |

### GDAC validation was used as evidence, not as the definition

Every threshold above is transcribed from S1/S2/S5/S6/S7. The GDAC masks in
S8 were used for three things only: (a) to confirm which tests INCOIS actually
executes per profile, (b) to catch the MEDD salinity error, and (c) to confirm
no regression. No threshold was derived from a GDAC value.

### The one remaining difference

`PROFILE_CHLA_QC` is ours `F`, GDAC `A`, on 9 cells. GDAC's own per-level
`CHLA_QC` is all `3` — identical to `DOXY_QC`, for which GDAC publishes `F`.
On the delayed-mode BD files of 2902130/2902131, DOXY all-`3` also yields `A`.
No single rule reproduces both, so the documented rule is applied and the GDAC
value is classified as inconsistent. **NOT A DEFECT (ours).**
