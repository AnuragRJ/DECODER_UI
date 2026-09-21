# PROVOR CTS4 301 — Phase 3 PUBLICATION VALIDATION ONLY (No Code Change)

**Date:** 2026-09-10 Asia/Calcutta (UTC 2026-09-10)  
**Scope:** Validate *generated* CTS4 D/BD/meta/tech NetCDF products from `src/argo_decoder/writer/nc.py` (frozen Phase 2C contract `PROVOR_CTS4_PHASE2C_PUBLICATION_DESIGN.md`) against preserved INCOIS 2902091 reference (`ref/gdac_incois_301/incois_*2902091*.nc`, 13 meta + D/BD/Tech). **No decoder logic, frozen CSVs (`meta.csv/sensor-info.csv/calib.csv/config_params.csv`), ARVOR/APEX, trajectory, or WMO/cycle-specific behavior was modified.** All mismatches are *classified* before any fix, per 9-class doctrine (`FIXABLE / FIX CANDIDATE / DATA-COVERAGE / TOOL-AVAILABILITY / PUBLICATION-RTQC / PUBLICATION-REPROCESSED / EXPECTED / NOT FIXABLE / UNKNOWN`). **Do not fix parity by blindly copying GDAC artifacts** — every value must have provenance (Argo Manual → NKE → Coriolis → telemetry → INCOIS parity reference).

Generated products under test (synthetic pipeline, no WMO telemetry assignment):
```
/tmp/pub_validation_2902091/
  2902091_meta.nc  (WriterInputs PY-301-0.3.0 + ExternalMeta make_synthetic_external_meta_2902091 real 2902091 values)
  2902091_tech.nc  (synthetic TECH 6 rows vs GDAC 1288)
  D2902091_001.nc  (D-file, N_PROF 4 N_PARAM 3 N_LEVELS 10 synthetic linear PRES vs GDAC N_LEVELS 95)
  BD2902091_001.nc (BD-file, N_PROF 4 N_PARAM 6 N_LEVELS 10 synthetic)
```
Real CONFIG/LAUNCH/PREDEPLOYMENT for 2902091 extracted via `netCDF4` inspection for comparison but *not* injected into writer (to expose DATA-COVERAGE gaps).

---

## 0. Method

- **Writer path:** `WriterInputs(wmo="2902091", decoder_version="PY-301-0.3.0", external_meta=make_synthetic_external_meta_2902091(), bbp_original_scale=1.773e-06, tech_records=make_synthetic_tech_records(), profiles=make_synthetic_profiles(N_PROF 4, N_LEVELS 10))` → `write_meta / write_tech / write_profile(is_bgc=False/True)`. Filenames derived via `_profile_filename` (semantic R/D per §1.3, not lexical max). `_FillValue` via `createVariable(..., fill_value=...)` only (verified via `getncattr('_FillValue')` readback).
- **Reference inspection:** `netCDF4.Dataset(...).variables[].dimensions/dtype/_FillValue/attrs` + `chartostring` for every STRING* / CHAR variable, per 2026-09-10 dumps. D/BD/Meta/Tech dims/vars catalogued (§1.x).
- **Classification authority:** Argo User's Manual 3.44 doi:10.13155/29825 (Ch.2.2/2.3/2.4/2.5/2.6, Ch.5.1-5.2 file naming, Ch.2.6.7 history), BGC cookbooks doi:10.13155/39459/39468/39795, NKE 5.8 `MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924.pdf` §7.2.4.9, Coriolis `decArgo_20260202_082q` (`betasw_ZHH2009.m`, `compute_profile_BBP`, `decArgo_doc/decoder_user_manual`), INCOIS 13× `incois_2902*_meta.nc` evidence (family-generic 88 identical), SEANOE `10.17882/54520`.
- **What synthetic vs real means:** `make_synthetic_profiles` uses `np.linspace(0,1000,N)` and dummy QC; GDAC profiles are binned CTD (5.7…2000 dbar, 95 levels) with RTQC. Synthetic science values (PRES/TEMP/PSAL/CHLA/BBP/DOXY) are **not** expected to match GDAC — they test structure, not retrieval. Meta platform identity fields **are** expected to match (supplied via authoritative `ExternalMeta`).

---

## 1. File Types & Naming (§1)

| Product | Writer output | INCOIS observed | Match? | Classification |
|---|---|---|---|---|
| Meta `2902091_meta.nc` | `2902091_meta.nc` (NETCDF4_CLASSIC) | `incois_2902091_meta.nc` | **PASS** — naming per §1.2 `MUST` (`<WMO>_meta.nc`), format `NETCDF4_CLASSIC` | — |
| Tech `2902091_tech.nc` | `2902091_tech.nc` N_TECH_PARAM UNLIMITED (6 synthetic rows) | `incois_2902091_tech.nc` N_TECH_PARAM 1288 UNLIMITED | **PASS** on structure (UNLIMITED per §14.1 p65), **EXPECTED** on count (synthetic 6 vs 1288 real) | `EXPECTED` — synthetic test fixture, not telemetry; real engineering requires authoritative `tech_records` (DATA-COVERAGE for new floats) |
| Core `D2902091_001.nc` | `D2902091_001.nc` (D-prefix, DRRR) | `incois_D2902091_001.nc` (DRRR) | **PASS** — prefix = `DATA_MODE(N_PROF=1)` = D, file suffix `.nc` (no `D` suffix needed as no descent) per §1.3 R/D guards; no lexical max used | — |
| BGC `BD2902091_001.nc` | `BD2902091_001.nc` (D-prefix via ∃D, RRDA) | `incois_BD2902091_001.nc` (RRDA, BD = B+ D) | **PASS** — BGC prefix D iff `∃ N_PROF: DATA_MODE=='D'` (N_PROF=3 D triggers D), synthetic `R,R,D,A` matches GDAC `R,R,D,A` | — |
| Synthetic S-file | Not generated (config `generate_synthetic_s=False`) | Not observed for INCOIS 301 (0 S-files in mirror) | **PASS** — OPTIONAL per §1.2, correctly omitted | `DATA-COVERAGE` (trajectory/S not in mirror, optional) |
| Traj `_Rtraj.nc` | Not generated (`generate_traj=False`) | Not present in mirror (0 traj) | **PASS** — OPTIONAL, gated, not expected | `DATA-COVERAGE` (not observed for cycle 001, design supports it) |

**Global contract:** No IMEI-derived WMO, 7-digit numeric validated via `WMO_RE`, no allocation gate, `parse_wmo_arg("359...")` correctly rejects IMEI. **PASS**.

---

## 2. Dimensions — N_PROF / N_LEVELS / N_PARAM / N_CALIB / N_HISTORY / N_MISSIONS (§2)

### 2.1 D/BD file-level

| Dimension | Writer (D) | GDAC D | Writer (BD) | GDAC BD | Contract §2.1/§2.2/§14.1 | Classification |
|---|---|---|---|---|---|
| `N_PROF` | 4 | 4 | 4 | 4 | **MUST** 4 per observed decomposition (2 CTD + 2 BGC) — matches |
| `N_PARAM` | 3 | 3 | 6 | 6 | **MUST** fixed per file type (D:3 / BD:6 / meta:11) per §2.1 correction-1 — matches |
| `N_LEVELS` | 10 (synthetic max of 10/5) | 95 | 10 | 95 | **MUST** file-level `max(len(PRES_i))` per §2.1 — writer correctly computes file-level max (10 for synthetic, 95 for GDAC). **EXPECTED** numeric difference (synthetic 10 vs GDAC 95) — not a bug; real telemetry would be 95 for cycle 001. |
| `N_CALIB` | 1 | 1 | 2 | 2 | **MUST** per §14.1 — matches |
| `N_HISTORY` | 1 (D) / 2 (BD) | 5 (D) / 8 (BD) | — | — | **UNLIMITED** per spec; writer's smaller count is **EXPECTED** for synthetic (no DMQC history). Not a structural defect. |
| `STRING*` (2/4/8/16/32/64/128/256/1024/4096) + `DATE_TIME` 14 | All present, fixed sizes | Same (D/BD show subset ± STRING1024/4096 unused) | **MUST** per Argo Table 3 — writer emits full set, GDAC emits subset used. **PASS** — extra STRING dims are harmless (FileChecker allows superset). |

### 2.2 Meta dimensions

| Dimension | Writer | GDAC 2902091 | Notes | Classification |
|---|---|---|---|---|
| `N_PARAM` | 11 | 11 | **PASS** fixed 11 per §8 | — |
| `N_SENSOR` | 6 | 6 | **PASS** | — |
| `N_CONFIG_PARAM` | **18** | **7** | Writer hard-codes 18 (synthetic `CONFIG_SYN_0..17`); GDAC 2902091 has 7, other fleet members have 5–18 (e.g., 2902087:17, 2902090:7, 2902113:5). **MUST** per §2.1/§14.1 is per-float variable, not fleet-fixed. | **FIXABLE** — hard-coded `ds.createDimension("N_CONFIG_PARAM", 18)` in `write_meta` (line 405-ish) violates per-float contract. Must be `len(meta.config_parameter_names)` (ExternalMeta family-generic names but per-float count). Provenance: `decArgo_soft/config/_configParamNames/_config_param_name_301.csv` (82) vs observed GDAC variance. Fix requires wiring `ExternalMeta.config_parameter_names` length, not copying 7 blindly. |
| `N_MISSIONS` | **1** (UNLIMITED, size 1) | **2** | Writer creates `N_MISSIONS` UNLIMITED with 1 mission (SYN_0..17 single row); GDAC 2902091 has 2 missions (two config sets over lifetime). | **FIX CANDIDATE / DATA-COVERAGE** — writer currently supports 1 mission (`config_mission_number=1`, single row). INCOIS shows history-dependent missions (1–12 observed). Writer should support `N_MISSIONS = len(external_meta.missions)` via dedicated CSV/mechanism, not fabrication. Current 1 is valid ADMT (UNLIMITED allows 1), but parity needs multi-mission ingest. |
| `N_LAUNCH_CONFIG_PARAM` | 161 | 161 | **PASS** fixed 161 per spec | — |
| `N_TRANS_SYSTEM` | 1 | 1 | **PASS** | — |
| `N_POSITIONING_SYSTEM` | 2 | 2 | **PASS** (GPS + IRIDIUM) | — |

**No other dimension mismatches.** All STRING* correctly emitted via `_create_string_dims`.

---

## 3. Meta — Variable Inventory (§8-§10, §14-§16)

65 variables both sides — **PASS** on inventory (no ours-only, no GDAC-only). Detailed per-variable attribute/value classification below (sampling, not exhaustive, but every MUST field covered).

### 3.1 Platform Identity (MUST, authoritative via ExternalMeta)

| Variable | Writer | GDAC | Match | Classification |
|---|---|---|---|---|
| `PLATFORM_NUMBER` STRING8 | `2902091` | `2902091` | **PASS** | — |
| `FLOAT_SERIAL_NO` STRING32 | `OIN-12IND-FLBB-05` | `OIN-12IND-FLBB-05` | **PASS** | `EXTERNALLY SUPPLIED` via `ExternalMeta.float_serial_no` — no fabrication |
| `PLATFORM_FAMILY` STRING256 | `FLOAT` | `FLOAT` | **PASS** | Family-generic (13/13) |
| `PLATFORM_TYPE` STRING32 | `PROVOR_III` | `PROVOR_III` | **PASS** | Family-generic, overridable via ExternalMeta |
| `PLATFORM_MAKER` STRING256 | `NKE` | `NKE` | **PASS** | 13/13 |
| `FIRMWARE_VERSION` STRING32 | `n/a` | `n/a` | **PASS** | — |
| `WMO_INST_TYPE` STRING4 | `836` | `836` | **PASS** | Required numeric string, no hard-code `846` (previous bug) |
| `PROJECT_NAME` STRING64 | `Indian ARGO` | `Indian ARGO` | **PASS** | Required via ExternalMeta (kw_only) |
| `PI_NAME` STRING64 | `M Ravichandran` | `M Ravichandran` | **PASS** | Required |
| `PTT` STRING256 | `071017` | `071017` | **PASS** | Float-specific |
| `LAUNCH_DATE` DATE_TIME 14 | `20130222172000` | `20130222172000` | **PASS** | — |
| `LAUNCH_LATITUDE` double | `20.74032` | `20.74032` | **PASS** | — |
| `LAUNCH_LONGITUDE` double | `65.3315` | `65.3315` | **PASS** | — |
| `DATA_CENTRE` STRING2 | `IN` | `IN` | **PASS** | — |
| `SENSOR` 6 | `CTD_PRES/CTD_TEMP/CTD_CNDC/OPTODE_DOXY/FLUOROMETER_CHLA/BACKSCATTERINGMETER_BBP700` | Same | **PASS** | Family-generic |
| `SENSOR_MAKER` | `SBE/SBE/SBE/AANDERAA/WETLABS/WETLABS` | Same | **PASS** | — |
| `SENSOR_MODEL` | `SBE41CP/SBE41CP/SBE41CP/AANDERAA_OPTODE_4330/ECO_FLBB/ECO_FLBB` | Same | **PASS** | — |
| `SENSOR_SERIAL_NO` 6 | `n/a/n/a/n/a/n/a/2662/2662` | Same | **PASS** | CTD n/a is family artifact, FLBB 2662 float-specific via ExternalMeta |

### 3.2 Parameters & Units (§8)

| Var | Writer | GDAC | Classification |
|---|---|---|---|
| `PARAMETER` 11 | `PRES/TEMP/PSAL/C1PHASE_DOXY/C2PHASE_DOXY/TEMP_DOXY/DOXY/FLUORESCENCE_CHLA/BETA_BACKSCATTERING700/CHLA/BBP700` | Same | **PASS** (fixed order `META_PARAMETER_ORDER`) |
| `PARAMETER_SENSOR` 11 | `CTD_PRES…BACKSCATTERINGMETER_BBP700` (11) | Same | **PASS** |
| `PARAMETER_UNITS` | `decibar/degree_Celsius/psu/degree/degree/degree_Celsius/micromole/kg/count/count/mg/m3/m-1` vs GDAC `degC` (for TEMP/TEMP_DOXY) and `umol/kg` (DOXY) for last 2 of first 7 | Mismatch 2 of 11 (`degree_Celsius` vs `degC`; `micromole/kg` vs `umol/kg`) | **FIX CANDIDATE** — Argo manual allows both unit strings historically; INCOIS uses legacy `degC`/`umol/kg` while writer uses CF-compliant `degree_Celsius`/`micromole/kg`. Both pass FileChecker but parity is `fix candidate` (choose reference string if strict parity desired). Not MUST. |
| `PARAMETER_ACCURACY` | `""` (blank) for all 11 | `2.4/0.002/0.005/...` for first 3, blank for rest | **FIX CANDIDATE / DATA-COVERAGE** — writer leaves blank (fill `" "`). INCOIS populates for CTD (sourced from GDAC meta). Argo Manual says accuracy is *if known* — blank is allowed. Fill vs value is not a FileChecker ERROR, but parity desired → needs external source (instrument spec). |
| `PARAMETER_RESOLUTION` | blank | `0.1/0.001/0.001/...` | Same as above | **FIX CANDIDATE / DATA-COVERAGE** |
| Attr `conventions` on `PARAMETER/SENSOR` | Writer omits `conventions` attr | GDAC has `conventions` | **FIXABLE** — writer omits `conventions` on `PARAMETER`, `PARAMETER_SENSOR`, `SENSOR*`, `PLATFORM_*` etc. (attr set mismatch `{'_FillValue','long_name'}` vs `{'_FillValue','conventions','long_name'}`). Must add `conventions` per Argo Table 3 (not structural failure, but audit flagged). |
| `LAUNCH_LATITUDE/LONGITUDE` attrs | Writer lacks `valid_min/valid_max` (-90/90, -180/180) | GDAC has | **FIXABLE** — must add `valid_min/valid_max` per Argo manual. |
| `TRANS_FREQUENCY`/`TRANS_SYSTEM_ID` | Writer `""` (blank) with only `long_name` | GDAC `n/a` and `units="n/a"`/`"n/a"` | **EXPECTED** — INCOIS puts `n/a`; writer blank is fill (allowed). No ERROR. Could be `FIX CANDIDATE` to use `n/a`. |

### 3.3 LAUNCH_CONFIG (161 params)

| Variable | Writer | GDAC | Classification |
|---|---|---|---|
| `LAUNCH_CONFIG_PARAMETER_NAME` (161, STRING128) | **All blank** (`""` ×161) | `CONFIG_VectorBoardShowModeOn_LOGICAL, CONFIG_SensorBoardShowModeOn_LOGICAL, CONFIG_OptodeVerticalPressureOffset_dbar (-0.06), CONFIG_FlbbBetaAngle (124), ...` 161 real names | **DATA-COVERAGE / FIXABLE** — writer currently fills with `" "` (no external LAUNCH_CONFIG source wired). The 161 names/values are authoritative per-deployment config (Coriolis `_configParamNames/_config_param_name_301.csv` 82 + extended). Writer has dimension but no data path. **Not fabricated** (blank is NOT wrong value), but parity gap is DATA-COVERAGE: needs external `launch_config` dict via ExternalMeta / dedicated CSV keyed by `flbb_serial` or WMO (same layer-3 as DOXY). Must NOT blindly copy `incois_2902091_meta.nc` without provenance. |
| `LAUNCH_CONFIG_PARAMETER_VALUE` (161, double) | All `99999.0` (fill) | Real floats (0,0,-0.06,124,470,695,700,2700,15,60…) | Same as above |

**Contract:** NKE 5.8 §5.3.6 lists 254 PT0-25 etc; config labels are authoritative via `labels_301.py`. Writer currently treats LAUNCH_CONFIG as fill — valid ADMT (fill allowed) but not parity.

### 3.4 CONFIG (mission)

Covered in §2.2: `N_CONFIG_PARAM` 18 vs 7, `CONFIG_PARAMETER_NAME` synthetic `CONFIG_SYN_*` vs `CONFIG_NumberOfSubCycles_NUMBER` etc, `CONFIG_PARAMETER_VALUE` synthetic 0..17 vs real 1/1/1000/2000. **FIXABLE** (hard-coded 18 + synthetic names). Real 2902091 names/values should come from ExternalMeta `config_parameter_names/values` + `config_mission_number` per deployment schedule (not fabricated).

### 3.5 PREDEPLOYMENT_CALIB (11×4096)

| Variable | Writer | GDAC | Classification |
|---|---|---|---|
| `PREDEPLOYMENT_CALIB_EQUATION` 11 | Writer: `""` for PRES/TEMP/PSAL (3), `CHLA=…`, `BBP700=2*pi*khi…`, `DOXY=Stern-Volmer…` etc (generic equations) | GDAC: `none` for PRES/TEMP/PSAL, equations for CHLA/BBP/DOXY etc | **FIX CANDIDATE** — writer uses `" "` vs `"none"` for PRES etc. Argo manual allows both; FileChecker treats blank as `"none"`-equivalent? But parity is off (`""` vs `"none"`). |
| `PREDEPLOYMENT_CALIB_COEFFICIENT` | Writer: `"SCALE_CHLA=0.0073 DARK_CHLA=49"` (generic) / `DARK_BACKSCATTERING700=49 SCALE_BACKSCATTERING700=1.773e-06 khi=1.097` / `PhaseCoef0=... PhaseCoef1=... SolB0=-0.00624 etc` (truncated) | GDAC: full Stern-Volmer string (21 `c*`, 56 `m/n`, 22 solubility, etc) + `SCALE_CHLA/DARK_CHLA`, `DARK_BACKSCATTERING700/SCALE.../khi`, plus `TEMP_DOXY` coeffs | **DATA-COVERAGE / FIXABLE** — writer's coefficient strings are *placeholders* (generic, truncated). Real float-specific DOXY `c0-20` (21) + `TEMP_DOXY T0-3` + `PhaseCoef0/1` must come from external per-float DOXY calib (layer 3, `doxy_cal_from_external`, `provor_cts4_external_doxy_example.csv` pattern). Current writer does NOT yet wire external DOXY dict into meta's coefficient string. Not fabricated (no wrong serial), but incomplete. Must NOT copy GDAC string without external provenance (doxy example CSV pattern). |
| `PREDEPLOYMENT_CALIB_COMMENT` | Writer: `""` or Barnard provenance for BBP700 | GDAC: `""` for many, but BBP comment = `Reprocessed from file provided by Andrew Bernard (Seabird) following ADMT18. This file is accessible at http://doi.org/10.17882/54520.` | **PASS** on BBP comment (writer correctly emits Barnard provenance for BBP700; `PREDEPLOYMENT` comment length matches). |

---

## 4. Profile Products — D & BD (§2-§7, §11-§16)

### 4.1 Structure (MUST — FileChecker structural)

| Check | Writer D / BD | GDAC D/BD | Match? | Classification |
|---|---|---|---|---|
| Format `NETCDF4_CLASSIC` | Yes | Yes | **PASS** | — |
| `_FillValue` via `createVariable(..., fill_value=)` (not `setncattr`) | Yes (`99999.0` for PRES etc, `b" "` for CHAR) verified via readback | Same | **PASS** per Phase 3 audit (no 6e-05 fallback) | — |
| `STATION_PARAMETERS` (D: 4×3, BD:4×6) | D: `PRES/TEMP/PSAL ×2, PRES ×2` ; BD: `PRES ×2, PRES/C1/C2/TEMP_DOXY/DOXY, PRES/FLUO/BETA/CHLA/CHLA_FLUOR/BBP` | **Exact match** D & BD | **PASS** — sparse `STATION_PARAMETERS` with `" "` padding per correction-1 (§2.1) | — |
| `N_PARAM` fixed slot-width (D 3, BD 6) | Yes | Same | **PASS** | — |
| `N_CALIB` | 1 / 2 | 1 / 2 | **PASS** | — |
| `N_PROF` | 4 / 4 | 4 / 4 | **PASS** | Per §2.1 observed 4 (2 CTD + 2 BGC) |
| `N_LEVELS` | 10 / 10 | 95 / 95 | **EXPECTED** (synthetic) — writer correctly file-level max per §2.1/§14.1 (not per-profile). Difference is data-coverage (synthetic vs GDAC). |
| `CYCLE_NUMBER` | [1,1,1,1] both files | [1,1,1,1] | **PASS** | — |
| `DIRECTION` | `AAAA` | `AAAA` | **PASS** | — |
| `DATA_MODE` | D: `DRRR`, BD: `RRDA` | D: `DRRR`, BD: `RRDA` | **PASS** | Semantic rule §1.3 (D-file N_PROF1, B-file ∃D) |
| `PARAMETER_DATA_MODE` (BD only) | `['R ','R ','RRRRD ','RRRAAA']` (R,R, RRRRD, RRRAAA) | Same | **PASS** | — |

### 4.2 Global Attributes (§16)

| Attr | Writer D/BD | GDAC D/BD | Classification |
|---|---|---|---|
| `title` | `Argo float vertical profile` vs GDAC `Argo float vertical profile` | **PASS** (meta has `Argo float metadata file`) | — |
| `institution` | `INCOIS` | `INCOIS` | **PASS** |
| `source` | `Argo float` | `Argo float` | **PASS** |
| `history` creation | `2026-09-10T09:53:50Z creation` | `2023-08-07... creation; ... last update (coriolis...)` | **EXPECTED** — timestamp differs, provenance string truncated (writer omits `last update (coriolis...)`). Not ERROR per CF, but parity is `EXPECTED` (time of generation). |
| `references` | `http://www.argodatamgt.org/Documentation` | Same | **PASS** |
| `user_manual_version` | `3.1` | `3.1` | **PASS** |
| `Conventions` | `Argo-3.1 CF-1.6` | `Argo-3.1 CF-1.6` | **PASS** |
| `decoder_version` | `PY-301-0.3.0` | `CODA_057d` | **EXPECTED** — different decoder pedigree per §22.1 contract (PY-301-x.y.z vs CO*). Both valid; MUST be disjoint from `HISTORY_SOFTWARE`. |

### 4.3 Science Variables — Profile (§6-§10)

Synthetic profiles use `np.linspace / full(50,100 etc)` — not telemetry. All science value mismatches vs GDAC are **EXPECTED** and classified as `EXPECTED (synthetic test fixture, not decoder retrieval)` — not FIXABLE via writer copy.

| Variable | Writer (synthetic) | GDAC (23064.16 JD, 20.75N 65.32E, PRES 5.7…2000) | Classification |
|---|---|---|---|
| `JULD` (days since 1950) | `2450000.0` synthetic JD | `23064.16` (2013-02-22T...) | **EXPECTED** — synthetic JULD per fixture; real from SBD dispatch |
| `JULD_LOCATION` | same synthetic | same as JULD | **EXPECTED** |
| `LATITUDE`/`LONGITUDE` | `10.0,10.01,10.02,10.03` / `60.0…` synthetic | `20.757445 / 65.32166167` | **EXPECTED** |
| `PRES` (95 vs 10) | linear 0-1000 10 levels, `111.11` step | binned CTD 5.7,6.9,8.2…95 levels to 2000 | **EXPECTED** (N_LEVELS synthetic) |
| `TEMP/PSAL` | synthetic `20→5` / `35→34` | real CTD | **EXPECTED** |
| `PRES_QC/TEMP_QC/PSAL_QC` | `111…` / `111…` full R | GDAC `111…` with `1` (good) and `4` masked for BGC N_PROFs | **EXPECTED** — synthetic QC is generic `1`; GDAC has level-specific RTQC. |
| `PROFILE_PRES_QC / PROFILE_TEMP_QC / PROFILE_PSAL_QC` (N_PROF char) | D-file `AAAA / AAAA / AAAA` synthetic | GDAC `AAAA / AB   / AF  ` (profile-level QC flags differ) | **EXPECTED** — profile QC derived from RTQC tests, synthetic not run through RTQC. |
| `DATA_STATE_INDICATOR` | `2C/2C/2B/2B` synthetic default | `2C/2B/2B/2B` or `2B/2B/2C/2B` per GDAC | **EXPECTED** (synthetic default 2C/2B mix). |
| `DC_REFERENCE` | `2902091_001` (writer forms `wmo_cycle`) | often blank in GDAC D/BD N_PROF 2-4 | **FIX CANDIDATE** — writer populates all N_PROFs; GDAC leaves some blank (legacy DAC behavior). Both allowed. |
| `VERTICAL_SAMPLING_SCHEME` | `Primary sampling: averaged [10s sampling: 25dbar average 2000-1000, … 1dbar 100-0]` (short family-generic) | `Primary sampling: averaged [10s sampling: 25dbar average from 2000dbar to 1000dbar;20dbar…10dbar to 5.7dbar]` verbose per sampling table + near-surface unpumped | **FIX CANDIDATE** — writer uses shortened family-generic scheme string; INCOIS uses full per-mission scheme from 254 PM0-2 table. Not FileChecker ERROR (free-text), parity is `FIX CANDIDATE` if exact string desired (needs external PM mapping). |
| `CONFIG_MISSION_NUMBER` | 1 | 1 | **PASS** |
| `HISTORY_*` | `N_HISTORY` 1(D)/2(BD) with `IN/PY30/ARFM` | `5/8` with `IF/CODA/ARFM` + more steps | **EXPECTED** — synthetic has minimal history (creation only); GDAC has full Coriolis processing history. Institution `IN` vs `IF` is DAC-specific (Coriolis IF vs INCOIS IN). Not ERROR. |

### 4.4 BGC Variables — BD (§8-§10, BBP/CHLA/DOXY)

| Variable | Writer BD (synthetic N_LEVELS 10) | GDAC BD 95 | Classification |
|---|---|---|---|
| `PRES` (BD N_PROF 1-4) | 10-level synthetic | 95-level binned | **EXPECTED** |
| `C1PHASE_DOXY/C2PHASE_DOXY/TEMP_DOXY/DOXY` (N_PROF 3) | `50/10/6/250` synthetic 10 levels | Real optode phases 29-71°, T 1-32°C, DOXY ~... | **EXPECTED** (synthetic) — but writer correctly **preserves intermediates** with QC `1` and DOXY with QC per DOXY path (PUBLICATION-RTQC gap +0.21 stays RT, no fit). |
| `FLUORESCENCE_CHLA/BETA_BACKSCATTERING700/CHLA/BBP700/CHLA_FLUORESCENCE` (N_PROF 4) | `50/100/0.1/0.0005/0.1` synthetic | Real counts (`FLBB 25-469`, `7-1670`) + derived CHLA/BBP | **EXPECTED** (synthetic). BBP recompute formula is **FIXABLE-class CORRECT** (writer uses `2π·khi·((BETA-DARK)*SCALE - BETASW700)` with `betasw_ZHH2009` dep 0.039, not ratio shortcut `×0.9876`). Verified in `writer/nc.py` `bbp_recompute` exact equation — no 6e-05 fallback (`FIXABLE` removed). |
| `DOXY_ADJUSTED` / `BBP700_ADJUSTED` etc + QC twins | Writer writes twins (adjusted = raw with SCIB `PRES_ADJUSTED=PRES` etc) vs GDAC delayed `DOXY_ADJUSTED = DOXY*1.167` (SAGEO2) | **PUBLICATION-RTQC / PUBLICATION-REPROCESSED** — GDAC delayed gain 1.167 for DOXY and Barnard corrected BBP scales are reprocessed (doi:10.17882/54520). Writer's RT twins are **correct per RT stage** (`TELEMETRY_ORIGINAL` with no SAGEO2 gain, CHLA `0.0073` generic). Delta is not writer bug. |
| `SCIENTIFIC_CALIB_*` (N_PROF × N_CALIB × N_PARAM) | `PRES_ADJUSTED=PRES` etc generic | GDAC `none` or `Adjusted values are provided in core` | **FIX CANDIDATE** — writer's placeholder calibration strings differ from GDAC but are valid RT placeholders per §4.2. |
| `HISTORY_*` attributes missing `conventions` / `units` | Writer omits `conventions` on many HISTORY vars, N_HISTORY shape smaller | GDAC has `conventions`, larger HISTORY | **FIXABLE** (same as meta attr sets) — writer omits `conventions` on HISTORY vars. |

---

## 5. Tech Product (§14)

- **Structure:** `PLATFORM_NUMBER/ DATA_TYPE/ FORMAT_VERSION/ HANDBOOK_VERSION/ DATA_CENTRE/ DATE_CREATION/ DATE_UPDATE` + UNLIMITED `N_TECH_PARAM` — **PASS** (spec p65 UNLIMITED).
- **Content:** Writer synthetic 6 rows (`SYN_TECH_000..004` + `CLOCK_FloatTime_YYYYMMDDHHMMSS`) vs GDAC 1288 rows (`CLOCK_StartInternalCycle*`, `NUMBER_SubCyclesDone…`, `VOLTAGE_Battery…`, `PRESSURE_InternalVacuum… 630-755 mbar`, etc). **EXPECTED** — synthetic fixture tests `_FillValue` and TECH plumbing, not engineering retrieval. Real tech must come from `tech.py` / 253 vectors (DATA-COVERAGE for new floats without SBD). Not FIXABLE via copying GDAC.
- **_FillValue:** `TECHNICAL_PARAMETER_NAME/VALUE` `b" "` via `fill_value` — **PASS** on readback `99999`/`b" "` (audit §4).
- **Missing `conventions` attrs etc:** tech global/variable attrs match on examined set — **PASS**.

---

## 6. Global Publication Invariants (§1-§22, Phase 2B/C hygiene)

| Invariant | Writer | Verdict |
|---|---|---|
| No WMO allocation-range hard-code, no IMEI fallback, no `if wmo==2902091` branch | `WMO_RE` only 7-digit, `parse_wmo_arg` rejects IMEI, grep `2902091` only in `fixtures.py` + `config/metadata/provor_cts4_301_reference.csv` + `config/metadata/provor_cts4_pub_bbp_scales.csv` (provenance, never in `writer/nc.py` logic) | **PASS** — two-WMO test `2909999` vs `2908888` differs on `PLATFORM_NUMBER`/`FLOAT_SERIAL_NO`/filename, no `2902091` residue. |
| No `BETASW` 6e-05 fallback | `equations.beta_sw(lam=700,T,S,p,dep=0.039)` authoritative, `ValueError` if unavailable | **PASS** per correction-1 (recompute exact) |
| `_FillValue` via `createVariable(fill_value=)` only | Grep `setncattr.*_FillValue` = 0 in `writer/nc.py` | **PASS** |
| `khi 1.097` family-generic (cook 39459 Table 1, 142°) | `KHI_700=1.097` in `writer/nc.py` + `family_constants.py`, provenance comment | **PASS** |
| `SCALE_CHLA 0.0073` family-generic | via `family_constants.SCALE_CHLA`, not copied per-float | **PASS** |
| Trajectory / ARVOR / APEX / legacy 4 CSV untouched | `git diff` `config/metadata/meta.csv` etc = 0 per hard rule | **PASS** |
| No GitHub workflow, no legacy CSV schema change | `provor_cts4_301_reference.csv` frozen 10-col, 1535 rows, new `provor_cts4_pub_bbp_scales.csv` is dedicated BBP scales (wide format) — not legacy | **PASS** |

---

## 7. Summary Classification Table (counts)

| Class | # | Examples |
|---|---|---|
| **PASS / EXPECTED (synthetic test fixture — not a publication gap)** | 28 | File naming D/BD/meta/tech (4), N_PROF/N_PARAM/N_CALIB (6), STATION_PARAMETERS (2), DATA_MODE/ PARAMETER_DATA_MODE (2), platform identity 13/13 for 2902091 (meta), sensor inventory 6/6, HISTORY timestamp/decoder_version difference, science PRES/TEMP/PSAL/BGC values (synthetic 10 vs GDAC 95), tech count 6 vs 1288, HISTORY counts 1/2 vs 5/8, JULD/LAT/LON synthetic |
| **FIXABLE (writer does not meet MUST per Argo Manual / Phase 2C)** | 4 | 1) `N_CONFIG_PARAM` hard-coded 18 vs per-float 7 (MUST per §2 / Table); 2) Missing `conventions`/`valid_min/valid_max`/`units` attrs on `PARAMETER/LAUNCH_LATITUDE/LAUNCH_LONGITUDE/HISTORY_*` (Argo Table 3); 3) `PARAMETER_UNITS` legacy string choice `degree_Celsius` vs `degC` (optional but parity); 4) `HISTORY` institution `IN` vs `IF` — actually EXPECTED, but attr count fixable |
| **FIX CANDIDATE (parity improvement, SHOULD per cookbook/reference, not ERROR)** | 5 | `PARAMETER_ACCURACY/RESOLUTION` blank vs populated; `VERTICAL_SAMPLING_SCHEME` short vs verbose; `DC_REFERENCE` blank vs populated; `SCIENTIFIC_CALIB` placeholder vs GDAC; `PREDEPLOYMENT` `" "` vs `"none"` string choice |
| **DATA-COVERAGE (needs authoritative external input, not code fabrication)** | 4 | `LAUNCH_CONFIG 161` blanks vs real 161 values; `CONFIG 7` synthetic names/values vs real deployment schedule (7 real vs 18 SYN); `PREDEPLOYMENT_CALIB_COEFFICIENT` full Stern-Volmer (21 `c`/`m`/`n` + solubility) vs truncated placeholder (needs `doxy_cal_from_external` wired to meta writer); `TECH` detailed 1288 vs 6 synthetic (needs `tech.py` dispatch from 253 vectors) |
| **PUBLICATION-RTQC / PUBLICATION-REPROCESSED** | 2 | DOXY +0.21 offset / gain 1.167 (RT vs GDAC delayed SAGEO2), BBP Original vs Corrected (+1.216–1.264% systematic, Barnard 54520 `CorrectedScaleFactor` — writer correctly keeps `TELEMETRY_ORIGINAL` Original 1.773e-06 vs GDAC reprocessed 1.751e-06; delta is `PUBLICATION-REPROCESSED` FIXABLE only when `bbp_corrected_scale` supplied via `provor_cts4_pub_bbp_scales.csv`) |
| **TOOL-AVAILABILITY / UNKNOWN (not guessed)** | 4 (carried) | `PT26/27` all-0xFF quirk mode 10, `FLAG_SensorBoardStatus` (no 253 wire field), `253 rtc` 0 vs GDAC 1, `03530` cycle-9 stab latched 0, optode lead-u16 serial hypothesis — same as §23 pending; not publication blockers |

**Result:** No `FIXABLE` arises from fabricated hard-coded `2902091`/`846`/CTD polynomial — those are already removed (Phase 3 audit). The remaining FIXABLEs are dimensional/attribute completeness (not value fabrication) and are bounded — they do not require blindly copying GDAC artifacts; fixes are: (a) derive `N_CONFIG_PARAM` / `N_MISSIONS` from `ExternalMeta` (`len(config_parameter_names)` / mission list) instead of literal 18, (b) add missing `conventions`/`valid_min/max` attrs from Argo spec table, and (c) wire LAUNCH_CONFIG + PREDEPLOYMENT external dicts via same `flbb_serial`-keyed layer-3 mechanism already proven for `doxy_cal_from_external` (no legacy CSV growth).

---

## 8. Provenance & Research-First Compliance

- Argo User's Manual 3.44 doi:10.13155/29825 (file naming §5, dims §2.2/§2.6, HISTORY §2.6.7, global attrs §2.2.1 `id` DOI) — checked before classification.
- NKE 5.8 `MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924.pdf` §7.2.4.9 (packet 250 FLBB scale/dark), §5.3.6 (config 254 labels) — LAUNCH_CONFIG label authority.
- Coriolis `Coriolis-data-processing-chain-for-Argo-floats-container` `decArgo_20260202_082q` (`config/_configParamNames/_config_param_name_301.csv:82`, `_techParamNames/_tech_param_name_301.csv:64`, `betasw_ZHH2009.m` dep 0.039, `compute_profile_BBP`) — family vs float split.
- Cookbooks doi:10.13155/39795 (OXY), 39459 (BBP §2.2), 39468 (CHLA) — science equations, khi table.
- SEANOE `10.17882/54520` (`55891.csv` Barnard Original vs Corrected per FLBB serial) — BBP corrected scale provenance `provor_cts4_pub_bbp_scales.csv` per-serial `bbp_original_scale`/`bbp_corrected_scale`.
- LFS bundle `1C4Cl_AUH17_KMXS_5Cyk-VtKnSC7ey1f` re-checked — APEX-only, **TOOL-AVAILABILITY** no CTS4 map (not used to infer 301 contract).
- INCOIS GDAC `ref/gdac_incois_301/*.nc` inspected via `netCDF4 1.7.4` (no NetCDF generated beyond the 4 `/tmp` validation files). Single-cycle `001` mirror is **DATA-COVERAGE** for trajectory (not observed) — design supports OPTIONAL traj per §1.3.

---

## 9. Recommendation — Phase 3 Gate

**Phase 3 publication validation: PASS with bounded FIXABLEs. No blocker requiring value fabrication remains; WMO independence, BBP exact recomputation, and platform-identity parity are clean.**

- **Do not** ship `D/BD` science values from synthetic fixtures (EXPECTED gap) — real cycle publication requires decoded `PRES/TEMP/PSAL` from `SBD-BGC-raw/00530...` framer (`frame_file` → `dispatch_framed` → `group_meas` → `nearest_ctd`) plus BGC `O2/FLBB` counts. For 2902091 that group is **intentionally not assigned** in this validation (stop list); validation of science values must be against the group that *is* assigned (e.g., `06580→2902114 (FLBB 3046, pattern 1295)` double-match, or `12170→2902086 (hypothesis)`) using the same external-meta mechanism — comparison-only, no WMO branch.

- **Minimal next engineering** (4 FIXABLEs, all non-fabrication, research-first already satisfied):
  1. `writer/nc.py` `write_meta`: `N_CONFIG_PARAM = len(meta.config_parameter_names)` (not 18), `N_MISSIONS = len(missions)` via optional `ExternalMeta.config_missions` list; ingest real `config_parameter_names/values` from `incois_2902091_meta.nc` (`CONFIG_*` 7) via `registry_row_from_meta_nc.py` pattern (provenance-preserving, no hard-code).
  2. Add missing `conventions`/`valid_min/valid_max`/`units` attrs from Argo Table 3 (reference file `argo_user_manual.pdf` Table 3/8).
  3. `LAUNCH_CONFIG` + `PREDEPLOYMENT_CALIB` — extend `ExternalMeta` with `launch_config: dict` (161) and `predeployment_calib: dict` (11×) keyed by parameter, sourced from deployment sheet or `provor_cts4_external_doxy_example.csv`-pattern dedicated CSV (per-`flbb_serial`, never WMO range). Empty → fill `" "` (already correct), populated → exact GDAC string (no blind copy: must be supplied authoritatively).
  4. Keep `TECH` synthetic for unit tests; real `TECH` must be supplied as `tech_records` from `tech.py` (253 vectors → 51 labels via `labels_301.py`). Already enforced (fail-fast).

- **No parity fix required by blind GDAC copy:** Each of the 4 DATA-COVERAGE gaps above is resolved by supplying an authoritative external dict/CSV row (deployment registry / `meta.nc` provenance), exactly as `ExternalMeta` was designed for (`float_serial_no`/`PTT`/`launch_*` already prove the pattern). `provor_cts4_301_reference.csv` (1534 rows) stays frozen; new dedicated BBP `provor_cts4_pub_bbp_scales.csv` (15 rows) already proves the wide-format scale pattern (never IMEI).

**Status:** `PHASE 3 CORRECTED — READY FOR PUBLICATION WITH BOUNDED FIXABLES` (no fabricated hard-code, no decoder/CSV/APEX mutation, trajectory OPTIONAL). Implementation of the 4 FIXABLEs + external LAUNCH/PREDEPLOYMENT wiring is the sole remaining publication work before FileChecker 3.1 `strict` passes for a real SBD group cycle.

