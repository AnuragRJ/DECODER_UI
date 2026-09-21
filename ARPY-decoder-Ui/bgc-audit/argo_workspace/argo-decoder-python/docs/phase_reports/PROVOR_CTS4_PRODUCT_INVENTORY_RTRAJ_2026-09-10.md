# PROVOR CTS4 301 — Real-Time Product Inventory — R/BR + meta.nc/tech.nc/Rtraj.nc — 2026-09-10

**Date:** 2026-09-10 12:00 UTC (Asia/Calcutta = 17:30 IST)  
**Scope:** Real-time only = `R` core + `BR` BGC. `D/BD` not supported, reference-only.  
**Instruction:** Verify complete real-time inventory `PROVOR-Bio/CTS4` including `R/BR`, `meta.nc`, `tech.nc`, `Rtraj.nc` from authoritative sources before any publication-ready declaration. Prior Gate1 (DOXY gsw) + Gate2 (13-WMO R/BR unavailable) remain suspended pending this verification.  
**Reference bundle:** `https://drive.google.com/file/d/1Tlkt-oqO6SYuTI9m8z6P47f3mx-dASUe` → `/tmp/ref_bundle/argo_workspace` (142 M) treated as external evidence only.

---

## 1. Authoritative sources consulted (research-first)

| Source | Evidence for inventory decision |
|---|---|
| **Argo User Manual 3.44 §4.1.3** file naming | `1900045_Rtraj.nc` = real-time trajectory, `1900045_Dtraj.nc` = delayed. One file per float, prefix `R`/`D` parallels profile files. Trajectory contains core+BGC parameters (§4.1.3 p91). |
| **Argo User Manual 3.44 §2.3 Trajectory (format 3.2)** | Traj is required float-level product: `N_MEASUREMENT` unlimited (dated events) + `N_CYCLE` summary rows, `MEASUREMENT_CODE` Table 15, `JULD_ADJUSTED`/`CLOCK_OFFSET`/`DATA_MODE A`, profile group `N_PARAM`/`N_HISTORY`. Stores all Argos/Iridium positions + cycle timing (§2.3.2 p18-30). |
| **Argo User Manual 3.44 §4.1.4 / §4.1.5** | ` <WMO>_meta.nc` and `<WMO>_tech.nc` are one per float (§92), not per cycle. `meta` = float description, `tech` = name/value/cycle table (`N_TECH_PARAM` unlimited). |
| **Coriolis decArgo `create_nc_traj_file.m` (2014)** | `if transType==3 (Iridium SBD) or 4 (ProvBioII) → create_nc_traj_file_3_1 → create_nc_traj_c_file_3_1` producing `<floatNum>_Rtraj.nc` with dims `N_CYCLE/N_MEASUREMENT/N_PARAM` and 102 variables (header + N_MEASUREMENT + N_CYCLE + HISTORY). `soft/util/decode_meas_cts4` path exists for format 301. |
| **Bundle GDAC trajectory examples** | `validation_arvor_i_rtraj_gdac/6990711_Rtraj.nc` `N_CYCLE7 N_MEASUREMENT113`, `7902408_Rtraj.nc` `N_CYCLE15 N_MEASUREMENT223`, both `DATA_TYPE Argo trajectory` `FORMAT 3.1` `Conventions Argo-3.1`. Vars match `_VAR_SPEC` 102. `ref2902224/2902224_Rtraj.nc` present. ARVOR meta/tech likewise float-level (`validation_phase6_meta/` `N_MISSIONS3`). |
| **Bundle PROVOR CTS4 GDAC mirror `provor_bio_irsbd/ref/gdac_incois_301`** | 13 × `incois_<wmo>_meta.nc` float-level, `incois_2902091_Dnc/BDnc` structural (not used for R/BR publication), **no** `Rtraj.nc` preserved — mirror is incomplete, not evidence of non-requirement (mirrors Gate2 finding: 0×R/BR preserved for 13 WMOs). |
| **NKE PROVOR CTS4 5.8 + SBD telemetry** | Msg type `253 VectorTech` carries per-cycle `cycle_start_day/hour`, `gps_valid`, `gps_lat_deg/min/frac/hem`, `gps_lon_*`; `252` tech, `254` config. `decode_253` → `gps_position()` provides trajectory LAT/LON/JULD. No WMO routing. |

---

## 2. Determination — which real-time files are required for CTS4

| Question | Answer | Evidence |
|---|---|---|
| **Is `{WMO}_Rtraj.nc` required for CTS4 real-time?** | **YES** — one per float, real-time `R` (delayed `D` out-of-scope). | Manual §4.1.3 names `Rtraj` for every float; §2.3 defines it as core trajectory product; Coriolis chain creates it for SBD types 3/4; ARVOR-I Rtraj analog with same chain proves production contract. Absence in `gdac_incois_301` mirror = incomplete snapshot, not non-requirement. |
| **Under what telemetry conditions?** | Whenever float transmits positions or cycle boundaries — for CTS4 Iridium SBD this is **every cycle with a valid GPS fix** (`253` `gps_valid==1`). Even cycles with invalid GPS must emit a placeholder MC with `_FillValue` + `STATUS 9` (not invented). No telemetry = no measurement row, but trajectory file still exists with launch + fill rows. |
| **Filename / dims / vars / attrs** | Filename `<WMO>_Rtraj.nc` (§4.1.3). Dims `N_MEASUREMENT unlimited`, `N_CYCLE = n_cycles`, `N_PARAM` (3 PRES/TEMP/PSAL for CTS4), `N_HISTORY` (1 blank on creation), plus `DATE_TIME/STRING*`. Vars 102 in fixed order: 17 header scalars + 31 N_MEASUREMENT (JULD/JULD_STATUS/LATITUDE/LONGITUDE/MEASUREMENT_CODE…PRES/TEMP/PSAL+adjusted) + 40 N_CYCLE (JULD_DESCENT_START…CLOCK_OFFSET…DATA_MODE) + 14 HISTORY. Globals `title Argo float trajectory file`, `Conventions Argo-3.1 CF-1.6`, `FORMAT_VERSION 3.1`, `HANDBOOK_VERSION 3.1`, `featureType trajectory`, `DATA_STATE_INDICATOR 2B`. |
| **Derivation from `253`/`252`/`254`/VectorTech** | `253` is authoritative for `JULD` (cycle_start_day/hour + launch epoch) + `LATITUDE/LONGITUDE` (gps_position arc-min→deg) + `MEASUREMENT_CODE 703` surface fix. `252` contributes tech/pressure for `REPRESENTATIVE_PARK_PRESSURE` if present (otherwise fill). `254` config not trajectory. Cycle association via `cycle_number` in packet header; no WMO-specific branch. |
| **meta/tech per-float vs per-cycle regeneration** | **One per float**, regenerated/overwritten per cycle (accumulating). Manual §4.1.4/4.1.5 single filename; bundle confirms `7902408_meta.nc` + `7902408_tech.nc` one each, `tech` `N_TECH_PARAM 264/154` increasing with cycles. Per-cycle copies are not GDAC-compliant. |
| **R/BR mono-cycle naming** | One per cycle per Manual §4.1.1 + bundle: `R<WMO>_<XXX>.nc` core, `BR<WMO>_<XXX>.nc` BGC-merge, with `XXX` zero-padded `001..999` (4 digits >999). Dimensions `N_LEVELS` variable, `N_CALIB`, `N_HISTORY`. `DATA_MODE R` for real-time. No descent `D` suffix in R/BR real-time. |

---

## 3. Product inventory vs current writer/pipeline

| Product | Required? | Current implementation (commit `rbr_all_cycles.py` + `nc/mono_profile.py`) | Evidence | Action |
|---|---|---|---|---|
| **`R<WMO>_<XXX>.nc` core real-time, mono-cycle** | **YES** | Implemented: 79 files cycles 98–114, mono-cycle, FileChecker 79 OK 0 FAIL, TEOS-10 gsw density. Produced in per-cycle dirs `cycleXXX_RBR/R2902086_XXX.nc` — **layout non-compliant** (GDAC expects float-level `profiles/` or flat float dir, not per-cycle dir with copies). Content correct. | Manual §4.1.1; bundle `R2902223_004.nc` mono-cycle; Gate2 census. | **Refactor output layout to GDAC float-level**: `<wmo>/profiles/R<wmo>_XXX.nc` (or flat float dir) single file per cycle, no per-cycle meta/tech duplicates. Content unchanged. |
| **`BR<WMO>_<XXX>.nc` BGC real-time, mono-cycle** | **YES** | Implemented: `BR2902086_XXX.nc` + corr branch, sparse `STATION_PARAMETERS` (no BBP filler), DOXY via gsw. Same layout issue as R. | Manual §4.1.2.1; `BR` prefix; BGC cookbook. | Same layout refactor as R. |
| **`<WMO>_meta.nc` float-level** | **YES** | **Non-compliant**: identical file duplicated per cycle `cycleXXX_RBR/2902086_meta.nc` (234 kB ×17). Content 65 vars correct, but regeneration duplicates instead of single float file overwritten per cycle. | Manual §4.1.4 single file; bundle `7902408_meta.nc` N_MISSIONS3 single; validation_phase6_meta. | **Write once per float** `2902086_meta.nc` at float base dir, updated per cycle (overwrite/extend N_MISSIONS if new mission). Remove per-cycle copies. Done interim: copied cycle098 → `/tmp/pub_validation_rbr_12170_all/2902086_meta.nc` (234 kB, 65 vars). |
| **`<WMO>_tech.nc` float-level accumulating** | **YES** | **Non-compliant**: per-cycle duplicate `2902086_tech.nc` 29 kB, N_TECH_PARAM 6 (one cycle only). True float-level must accumulate over cycles (bundle ARVOR `N_TECH_PARAM 264`). | Manual §4.1.5; bundle `7902408_tech.nc` N_TECH_PARAM var; `N_TECH_PARAM` unlimited. | **Regenerate as accumulating float file** `2902086_tech.nc` at base dir, appending per-cycle `TECHNICAL_PARAMETER_NAME/VALUE` rows. Interim copy exists but needs accumulation fix (see §5). |
| **`<WMO>_Rtraj.nc` float-level real-time** | **YES** | **MISSING** (was 0 files). Writer `nc/rtraj_arvor.py` existed for ARVOR only; no CTS4 trajectory call in `rbr_all_cycles.py`. | Manual §4.1.3 + §2.3; Coriolis `create_nc_traj_file.m` for type 3/4; ARVOR Rtraj 6990711/7902408 proof; `253` telemetry provides GPS/JULD. | **Implemented generic CTS4 builder** (§4) `2902086_Rtraj.nc` now at float base dir, `N_CYCLE17 N_MEASUREMENT18`, 102 vars, no WMO hardcode, raw 253→JULD/LAT/LON. Embed into pipeline (§5). |

*D/BD remain removed — 0 production D-mode paths, 0 BD writers, 0 D/BD tests. `ref/gdac_incois_301` D/BD kept reference-only.*

---

## 4. Rtraj derivation from real telemetry — generic `raw SBD → trajectory` (no WMO logic)

**Input:** `raw_telemetry/SBD-BGC-raw/12170/cycle{098..114}/` SBD frames → `dispatch_framed(frame_file(p)).packets` → `decode_253(OpaquePacket)` (`VectorTech: cycle, gps_valid, gps_lat_deg/min/frac, gps_lon_*`, `cycle_start_day/hour`).

**Per-cycle:**
1. Collect `253` packets per `fa.cycle`; pick first `gps_valid==1` (else first packet).
2. `JULD = launch_juld + cycle_start_day + cycle_start_hour/1440`, `launch_juld` from epoch 1950-01-01 + launch `2012-12-29 13:17 UTC` (from `meta.nc` LAUNCH_DATE or config). Generic: uses `meta.csv` launch_date, not if-else WMO.
3. `LAT/LON = vt.gps_position()` (arc-min decode → decimal deg), hemisphere applied.
4. Emit `N_MEASUREMENT` row `MEASUREMENT_CODE 703` (surface fix, Table 15), `CYCLE_NUMBER = fa.cycle`, `JULD_STATUS 2` (float-clock transmitted) if valid else `9`, `JULD_QC 1` if valid else `9`, `POSITION_QC 1` if valid else `9`, `POSITION_ACCURACY A` if valid else blank. Launch row `MC 0` at `CYCLE -1` with `LAUNCH_LATITUDE/LONGITUDE`.
5. `N_CYCLE` summary rows: `JULD_FIRST_LOCATION/LAST_LOCATION/FIRST_MESSAGE/LAST_MESSAGE/ASCENT_START/...` = per-cycle JULD where available else `999999.0` with `STATUS 2`/` ` matching; `DATA_MODE R`, `CLOCK_OFFSET 999999.0` (not yet adjusted), `GROUNDED blank`.

**File:** `netCDF4.Dataset(..., format NETCDF4)` with dims `N_MEASUREMENT unlimited`, `N_CYCLE 17`, `N_PARAM3`, `N_HISTORY1`, `DATE_TIME14`, `STRING*` as per `_VAR_SPEC`. 102 vars in reference order, dtypes `S1/f8/f4/i4`, fill values `99999.0/999999.0/99999/space`. Globals `title`, `Conventions Argo-3.1 CF-1.6`, `institution IN`, `history` timestamp, `DATA_STATE_INDICATOR 2B`, `FORMAT_VERSION 3.1`. No `g_decArgo_floatNum` branch, no `if wmo==2902086`, no IMEI routing, no fitted residuals.

**Provisional file evidence (2026-09-10 17:30):**
```
2902086_Rtraj.nc  179 kB  N_MEASUREMENT18 N_CYCLE17 N_PARAM3 N_HISTORY1
JULD [23008.5, 23422.7, 23427.7 … 23502.7]  CYCLE_NUMBER [-1, 98 …114]  MC [0, 703×17]
LAT [12.1155 launch, 13.892 …12.979]  LON [79.701 launch, 86.09 …86.68]
DATA_MODE N_CYCLE [R]×17   Conventions Argo-3.1 CF-1.6
```

File passes dimensional/global/102-var inventory checks; full FileChecker requires `tools` jar (not in snapshot) — interim verified against `_VAR_SPEC` and ARVOR references.

---

## 5. Comparison delta & required pipeline change

| Dimension | Current (`cycleXXX_RBR/` per-cycle + no traj) | Required (GDAC float-level) | Gap |
|---|---|---|---|
| Layout | `cycle098_RBR/R2902086_098.nc` + duplicate `2902086_meta.nc`×17 + `2902086_tech.nc`×17 | `<wmo>/2902086_meta.nc`, `<wmo>/2902086_tech.nc` (one, accumulating), `<wmo>/2902086_Rtraj.nc` (one, accumulating), `<wmo>/profiles/R2902086_XXX.nc`, `BR…` per cycle | **Layout refactor** |
| Trajectory | none | one `Rtraj` per float from 253, generic | **Implemented provisional** `/tmp/build_rtraj_cts4_nc4.py` (direct netCDF4, replicates `_VAR_SPEC`). To promote: `src/argo_decoder/nc/rtraj_cts4.py` + `platforms/provor_cts4_ir_sbd/provor_cts4_rtraj.py` product model (like ARVOR `arvor_i_rtraj.py`) + pipeline call `build_cts4_rtraj_dataset()` per cycle accumulation. |
| Tech accumulation | N_TECH_PARAM 6 (single cycle) repeated | N_TECH_PARAM grows: cycle N appends rows for params `VOLTAGE_*`, `PRES_SurfaceOffset*`, etc. (vocab-driven, no guess scale) | **Fix tech builder** to append, not overwrite. |
| R/BR content | OK (sparse params, gsw DOXY, FLAG_SensorBoardStatus 2 vs 1 explained, 03530 UNKNOWN) | OK — no change except layout | — |

**Next code change (no WMO hack, four CSVs frozen, no D/BD):**
1. Create `src/argo_decoder/platforms/provor_cts4_ir_sbd/provor_cts4_rtraj.py` — dataclasses `Cts4RtrajRow/Cycle`, `NCYCLE_FIELD_BY_MC` mapping, pure `build_rows(cycles_gps_juld)` (no WMO).
2. Create `src/argo_decoder/nc/rtraj_cts4.py` — `build_cts4_rtraj_nc_dataset()` + `write_cts4_rtraj_file()` mirroring `rtraj_arvor.py` but driven by CTS4 MC set (launch 0 + 703 per cycle, extensible to 700/702/704 when transmission logs added).
3. Refactor `rbr_all_cycles.py` (or writer entry) to: `for each cycle → decode → profile R/BR → after loop → write float-level meta/tech once + write accumulating Rtraj` (remove per-cycle meta/tech copy).
4. Add `tests/test_cts4_rtraj.py` (two-WMO WMO-independence, FillValue, no hardcode) and `tests/test_cts4_no_dbd.py` already exists.
5. Re-run `pytest` 8 publication tests (150/150, writer, two-WMO, missing-metadata, BBP exact, DOXY, FillValue, 2902091 shadow).

Four legacy CSVs unchanged; `provor_cts4_301_reference.csv` remains only CTS4 artifact.

---

## 6. Publication-ready statement (still SUSPENDED)

* Gates: **DOXY gsw** ✓ (79 files 0 FAIL), **13-WMO R/BR inventory** ✓ (0×R/BR preserved, D/BD reference-only).
* **This product-inventory gate**: R/BR, meta, tech identified as required and partially compliant; **Rtraj now provisionally built (179 kB, 102 vars) but pipeline not yet refactored to accumulate tech + produce Rtraj per-cycle + float-level layout.** Therefore overall publication readiness **remains SUSPENDED** until §5 code refactor lands, `pytest` 8-point passes, and `gdac_filechecker` (tools jar) confirms `Rtraj/meta/tech` 0 errors.

Append-only `IMPLEMENTATION_PROGRESS.md` will be updated with this inventory.

---
*Evidence files:* `argo_user_manual.pdf §4.1.3 p91 §2.3 p18-30`, `Coriolis create_nc_traj_file.m L12-20`, `6990711_Rtraj.nc N_CYCLE7`, `7902408_Rtraj.nc N_CYCLE15`, `incois_2902086_meta.nc N_MISSIONS3`, `/tmp/pub_validation_rbr_12170_all/2902086_Rtraj.nc` (new).
