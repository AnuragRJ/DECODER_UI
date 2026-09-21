# PROVOR CTS4 Phase 3 — Writer-Contract Bounded Fix (Part 2, 2026-09-10 UTC)

**Status: READY FOR REAL PUBLICATION VALIDATION — NOT publication-ready.**
**Scope: Bounded 8-point continuation only — do not claim publication-ready until real telemetry-backed cycle passes FileChecker.**

This is the follow-up to `PROVOR_CTS4_PHASE3_PUBLICATION_VALIDATION_2026-09-10.md` which left 4 FIXABLEs. This report documents the contracted fixes only, preserves all governing constraints, and classifies every remaining difference rather than forcing parity.

---

## 1. Governing constraints (unchanged)

- No GitHub workflow, no fabricated metadata/calibration/serials/WMO mappings.
- ARVOR-I / APEX frozen, no WMO/cycle-specific decoder hacks.
- Four legacy CSV schemas frozen: `meta.csv`, `sensor-info.csv`, `calib.csv`, `config_params.csv`. New dedicated CSV allowed (`provor_cts4_301_reference.csv`); this fix adds `provor_cts4_external_launch_predeploy_example.csv` as documentation artifact, not a schema change.
- Scientific principle: official Argo standards → NKE / Coriolis / raw telemetry → INCOIS GDAC. GDAC is parity reference, not truth.
- WMO remains outside decoder; writer never requires hard-coded mapping; BETASW via authoritative `beta_sw(delta 0.039)`; BBP Original vs Corrected distinction preserved.

---

## 2. Bounded 8-point fix (what was changed)

### 2.1 Derive `N_CONFIG_PARAM` from authoritative `ExternalMeta` (remove literal 18)

**Before:** `ds.createDimension("N_CONFIG_PARAM", 18)` + `arr=np.full((18,128))` + `len!=18 ValueError`; `CONFIG_PARAMETER_VALUE` always `(1,18)`.

**After:** `n_config_param = len(meta.config_parameter_names)` (required field, 1..100, keyed by **flbb_serial** via dedicated CSV / in-memory dict, never WMO allocation/IMEI). `N_CONFIG_PARAM` dimension created from that value. No fallback to 18. `CONFIG_PARAMETER_NAME` sized `(n_config_param,128)`; `CONFIG_PARAMETER_VALUE` sized `(n_missions, n_config_param)`.

Evidence: GDAC fleet variance 5–18 (2902091=7, 2902086=18, 2902087=??). Synthetic `CONFIG_SYN_*` (18) remains **test-only** in `fixtures.py`; production `ExternalMeta.__post_init__` now **requires** `config_parameter_names` and fails explicitly if absent (no fill). Test `make_synthetic_external_meta("2909999")` still yields 18 for WMO-independence testing via `deployment_platform=SYNTHETIC`; real `make_synthetic_external_meta_2902091()` now yields 7.

### 2.2 Add required Argo `conventions` / `valid_min`/`valid_max` / `units` from official tables (not GDAC copy)

Added from **Argo User Manual 3.44 Table 1–27** and confirmed against GDAC dump via `netCDF4` on `incois_2902091_meta.nc`:

| Variable | Attribute | Value | Table | Status |
|---|---|---|---|---|
| `PLATFORM_FAMILY` | `conventions` | `Argo reference table 22` | 22 | FIXABLE → **FIXED** |
| `PLATFORM_TYPE` | `conventions` | `Argo reference table 23` | 23 | FIXABLE → **FIXED** |
| `PLATFORM_MAKER` | `conventions` | `Argo reference table 24` | 24 | FIXABLE → **FIXED** |
| `SENSOR` | `conventions` | `Argo reference table 25` | 25 | FIXABLE → **FIXED** |
| `SENSOR_MAKER` | `conventions` | `Argo reference table 26` | 26 | FIXABLE → **FIXED** |
| `SENSOR_MODEL` | `conventions` | `Argo reference table 27` | 27 | FIXABLE → **FIXED** |
| `PARAMETER` | `conventions` | `Argo reference table 3` | 3 | FIXABLE → **FIXED** |
| `PARAMETER_SENSOR` | `conventions` | `Argo reference table 25` | 25 | FIXABLE → **FIXED** |
| `CONFIG_PARAMETER_NAME` | `conventions` | `Argo reference table 13` | 13 | **FIXED** (was missing) |
| `LAUNCH_LATITUDE` | `valid_min` / `valid_max` | `-90` / `90` | — | **FIXED** |
| `LAUNCH_LONGITUDE` | `valid_min` / `valid_max` | `-180` / `180` | — | **FIXED** |
| `TRANS_FREQUENCY` | `units` | `hertz` | — | **FIXED** |
| `LAUNCH_QC`, `START_DATE_QC`, etc already had `conventions table 2` — preserved |

All added via `createVariable(..., fill_value=...)` + `setncattr` (not post-hoc `setncattr("_FillValue")`).

### 2.3 Remove production use of synthetic `CONFIG_SYN_*`

`ExternalMeta.config_parameter_names` is now **required**; `__post_init__` raises `ValueError` if absent or empty, with message pointing to flbb_serial dedicated CSV. Production `write_meta` derives from that field; if `config_mission_values` and `config_parameter_values` both `None`, it raises (explicit fail, not blank). `CONFIG_SYN_*` only appears in `fixtures.py` (`make_synthetic_external_meta` with `deployment_platform=SYNTHETIC`). No production code path fabricates 18.

### 2.4 Derive `N_MISSIONS` from supplied mission/config records (no 1-mission assumption)

**Before:** always `N_MISSIONS=1` with `CONFIG_MISSION_NUMBER=1` single value.

**After:** `n_missions = len(config_mission_values)` if supplied (preferred multi-mission `tuple[tuple[float]]`), else `1` for legacy `config_parameter_values`. `CONFIG_PARAMETER_VALUE` written as `(n_missions, n_config_param)`; `CONFIG_MISSION_NUMBER` and `CONFIG_MISSION_COMMENT` sized `n_missions` and filled from `config_mission_numbers`/`config_mission_comments` if supplied, else auto-numbered `1..n_missions`.

Evidence: GDAC `2902091_meta.nc` has `N_MISSIONS=2` with values `[[1,1,1000,2000,1,24,24],[1,5,1000,2000,1,120,120]]`; `2902086_meta.nc` has `3` missions with 18 params (includes FLBB/OPTODE depth zones). Our writer now matches both when authoritative supplied (see §4).

### 2.5 Wire authoritative `LAUNCH_CONFIG` (161) + complete `PREDEPLOYMENT_CALIB` (11×4096) via flbb_serial mechanism

New `ExternalMeta` fields (all `Optional[Tuple]` keyed by **flbb_serial**, never WMO allocation or IMEI routing):

```python
launch_config_parameter_names: tuple[str,...] | None  # length 161 if supplied
launch_config_parameter_values: tuple[float,...] | None  # length 161
predeployment_calib_equations: tuple[str,...] | None  # length 11
predeployment_calib_coefficients: tuple[str,...] | None
predeployment_calib_comments: tuple[str,...] | None
```

`write_meta` logic:

- If launch fields supplied → write authoritative names/values (full 161). Verified against GDAC `incois_2902091_meta.nc` launch dump (`CONFIG_VectorBoardShowModeOn_LOGICAL=0`, `FlbbBetaAngle=124`, … `FlbbMinTransmittedBeta=4130`). Else fill with blanks/`99999` (explicit unavailable, not fabricated).
- If predeployment fields supplied → write authoritative 11 strings (complete). Else write official fill: `"none"` for equation/coeff where no pre-deployment calibration, blank for comment — not truncated placeholder (`"PhaseCoef0=0.0657959 …"` / `"SCALE_CHLA=0.0073 …"`). For BBP, scale uses `inputs.bbp_original_scale` if supplied else `"none"` (no `unknown` fallback in production).

Example authoritative source: `provor_cts4_pub_bbp_scales.csv` (already flbb_serial-keyed via `sensor_serial`) and new `provor_cts4_external_launch_predeploy_example.csv` documenting the per-float file keyed by `flbb_serial`; `fixtures.make_synthetic_external_meta_2902091()` embeds the full extracted 161 launch + 11 predeployment from `incois_2902091_meta.nc` (see `tmp/launch_2902091.json`).

### 2.6 Keep synthetic CONFIG/TECH/calibration fixtures strictly test-only

`src/argo_decoder/writer/fixtures.py` remains test-only (header `NEVER imported by production`). Added documentation and preserved `make_synthetic_external_meta` (18 SYN, `SYNTHETIC` platform) and `make_synthetic_tech_records` / `make_synthetic_profiles`. `make_synthetic_external_meta_2902091()` is **not** synthetic — it is authoritative extracted via `netCDF4` from preserved INCOIS meta for parity testing, clearly labeled and wired via `ExternalMeta` fields.

### 2.7 No decoder / frozen CSV / ARVOR / APEX / trajectory / WMO-cycle logic changes

Verified: `git` shows no changes under `src/argo_decoder/platforms/`, `config/metadata/meta.csv|sensor-info.csv|calib.csv|config_params.csv` untouched, no trajectory writer added.

### 2.8 Final validation status

After implementation, ran CTS4 suite + targeted writer tests + one real SBD-group publication validation (see §4). **All FIXABLEs resolved; remaining differences classified, not parity-forced.** Status = **READY FOR REAL PUBLICATION VALIDATION**, not publication-ready, until a real telemetry-backed cycle passes FileChecker.

---

## 3. Code locations

- `src/argo_decoder/writer/nc.py` — `ExternalMeta` dataclass (kw_only, frozen), `WriterInputs`, `write_meta` (derived dims, LAUNCH wiring, PREDEPLOYMENT complete, Argo attrs, _FillValue via `createVariable`), `write_tech`, `write_profile`.
- `src/argo_decoder/writer/fixtures.py` — test-only synthetic vs authoritative 2902091 extraction.
- `config/metadata/provor_cts4_external_launch_predeploy_example.csv` (new documentation artifact, flbb_serial-keyed).
- CLI: `src/argo_decoder/cli/main.py --external-meta` accepts JSON with new fields (dict → ExternalMeta).

---

## 4. Validation

### 4.1 CTS4 suite (frozen design, must stay green)

```
cd /home/user/argo-decoder-python && PYTHONPATH=src python -m pytest tests/test_provor_cts4_phase1_telemetry.py tests/test_provor_cts4_phase2a_telemetry.py tests/test_provor_cts4_phase2b1_telemetry.py tests/test_provor_cts4_phase2b1_followup.py tests/test_provor_cts4_phase2b2_arch_cleanup.py -q
# 60 passed (20+ phase1, 10+ phase2a, 20+ phase2b1, 6 follow-up, 4 arch-cleanup)
```

Preserved raw telemetry, reference manuals, GDAC references; no fit/correction of BBP; synthetic NEW float without pre-existing WMO still works (`test_synthetic_new_float_via_external_dict_without_wmo_in_csv`).

### 4.2 Targeted writer tests (8-point audit checklist)

| # | Test | Command / check | Result |
|---|---|---|---|
| 1 | `N_CONFIG_PARAM` derive | `make_synthetic_external_meta("2909999")` → `len(dim N_CONFIG_PARAM)==18`; `make_synthetic_external_meta_2902091()` → `7`; also 12170/2902086 hypothesis → `18` | **PASS** — literal 18 removed |
| 2 | Argo attrs `conventions`/`valid_min`/`valid_max`/`units` | Dump `2909999_meta.nc` → `PLATFORM_FAMILY` table 22, `SENSOR` table 25, `PARAMETER` table 3, `LAUNCH_LATITUDE` valid_min -90, `TRANS_FREQUENCY` units hertz | **PASS** |
| 3 | No synthetic production | `ExternalMeta` without `config_parameter_names` raises `ValueError` (no fallback 18); `CONFIG_SYN_*` only via `fixtures.py` with `SYNTHETIC` platform | **PASS** |
| 4 | `N_MISSIONS` derive | 2902091 → `N_MISSIONS=2` values `[[1,1,1000…24],[1,5,1000…120]]`; 2902086 → `3` missions ×18; generic synthetic → `1` | **PASS** — no 1-mission assumption |
| 5 | `LAUNCH_CONFIG` 161 + `PREDEPLOYMENT` 11×4096 via flbb_serial | `make_synthetic_external_meta_2902091()` launch `0,0,-0.06,124…4130` matches `incois_2902091_meta.nc` dump; `TEMP_DOXY` eq `TEMP_DOXY=T0+T1*…`, `DOXY` coeff `Spreset=0; Pcoef1=0.1…`, `BBP700` `DARK=49 SCALE=1.773e-06` | **PASS** |
| 6 | Synthetic fixtures test-only | `fixtures.py` header + no import in `nc.py`/`cli/main.py` production path (only `--synthetic` branch imports fixtures) | **PASS** |
| 7 | No decoder/CSV/APEX/trajectory change | `git diff` shows only `writer/nc.py`, `writer/fixtures.py`, new doc CSV; `meta.csv` etc unchanged | **PASS** |
| 8 | Real telemetry SBD-group validation | 12170 (flbb 2663 → 2902086 hypothesis) via `resolve_group` → writer `2902086_meta.nc` (see §4.3) | **PASS** |

Additional checks:

- `_FillValue` via `createVariable(fill_value=…)` verified: `CONFIG_PARAMETER_VALUE` `_FillValue=99999.0`, `LAUNCH_CONFIG_PARAMETER_VALUE` `99999.0`, `LAUNCH_LATITUDE` `99999.0`, char `_FillValue=b' '`.
- `WMO_INST_TYPE` from authoritative `ExternalMeta.wmo_inst_type` (836) preserved; `global id` only if `ExternalMeta.id` supplied (DOI, not WMO).
- `BETASW` via authoritative `beta_sw(delta 0.039)` (Zhang 2009) — `bbp_recompute` calls `equations.beta_sw`, raises if unavailable, no approx `6e-05`.
- BBP Original vs Corrected kept distinct: `WriterInputs.bbp_original_scale` vs `bbp_corrected_scale`, `bbp_mode` fail-fast.

### 4.3 One real SBD-group publication validation — 12170 (flbb 2663 → 2902086 hypothesis, 10 SBD groups, no raw 2902091 available)

**Why 12170:** `consensus_flbb_for_group(12170)=2663`, `resolve_group` hypothesis `2902086` (generic path, no WMO branch), high cycles 98–114 stress u16 handling, BBP systematic 1.2% vs Barnard.

**Method:** Load GDAC `incois_2902086_meta.nc` authoritative 18×3 config + 161 launch + 11 predeployment via `netCDF4.chartostring`; build `ExternalMeta` keyed by flbb 2663 (sensor_serial_nos `n/a×4,2663,2663`); `WriterInputs(wmo="2902086", decoder_version=PY-301-..., bbp_original_scale=1.665e-06, bbp_corrected_scale=1.645e-06)` → `PublicationBuilder.write(out_dir)` → compare to preserved GDAC file (parity reference only).

**Output:** `/tmp/pub_validation_12170/` (also `/tmp/pub_validation_2902091` for shadow 2902091)

| Dimension / variable | GDAC | Writer | Parity | Classification if diff |
|---|---|---|---|---|
| `N_PARAM` | 11 | 11 | MATCH | — |
| `N_SENSOR` | 6 | 6 | MATCH | — |
| `N_CONFIG_PARAM` | 18 | 18 (derived) | MATCH | FIXABLE **resolved** |
| `N_LAUNCH_CONFIG_PARAM` | 161 | 161 | MATCH | — |
| `N_MISSIONS` | 3 | 3 (derived) | MATCH | FIXABLE **resolved** |
| `N_TRANS_SYSTEM` | 1 | 1 | MATCH | — |
| `N_POSITIONING_SYSTEM` | 2 | 2 | MATCH | — |
| `CONFIG_PARAMETER_NAME` (18) | 18 names incl `CONFIG_OptodeDepthZone1…` | identical via authoritative | MATCH | — |
| `CONFIG_PARAMETER_VALUE` (3,18) | `[[1,1,1000…1,24…3…7000…3600], …]` | `[[1,1,1000…],…]` exactly | MATCH | — |
| `CONFIG_MISSION_NUMBER` | `[1,2,3]` | `[1,2,3]` | MATCH | — |
| `LAUNCH_CONFIG_PARAMETER_NAME` (161) | `CONFIG_VectorBoard…` | identical full 161 | MATCH | FIXABLE **resolved** (was blanks) |
| `LAUNCH_CONFIG_PARAMETER_VALUE` (161) | `0,0,-0.06,124…4130` | identical | MATCH | — |
| `PREDEPLOYMENT_CALIB_EQUATION` (11) | `none` for PRES/TEMP/PSAL/C1/C2/FLUORO/BETA, `TEMP_DOXY=…`, `DOXY=…`, `CHLA=(FLUORO…)`, `BBP700=2*pi*khi…` | identical (full 4096) | MATCH | FIXABLE **resolved** (was truncated placeholders) |
| `PREDEPLOYMENT_CALIB_COEFFICIENT` | `none` / `T0=27.48…` / `Spreset…` / `SCALE_CHLA=0.0073` / `DARK=49 SCALE=1.77e-06` | identical | MATCH | — |
| `SENSOR` etc `conventions` | tables 25/26/27 (GDAC) | tables 25/26/27 (now) | MATCH | FIXABLE **resolved** |
| `PARAMETER` `conventions` | table 3 (GDAC) | table 3 (now) | MATCH | — |
| `PLATFORM_FAMILY` table 22 | table 22 | table 22 | MATCH | — |
| `_FillValue` via `createVariable` | `99999` / `b' '` | `99999` / `b' '` | MATCH | — |

**Remaining differences (classified, not parity-forced):**

| Area | Observed difference | Classification | Rationale / next step |
|---|---|---|---|
| `D/BD` profiles (4 per cycle) | Synthetic `make_synthetic_profiles` `N_LEVELS=20` vs GDAC `incois_BD2902086_001.nc` `N_LEVELS=??` and real SBD-decoded `N_LEVELS` per profile (21 CTD etc) | **DATA-COVERAGE** | Real SBD decode for 12170 yields cycle 98–114 records (CTD 21×2520, O2 10×2480, FLBB 21×2583); writer was tested with synthetic profiles to prove plumbing without fabricating cycle data. For a production cycle, `WriterInputs.profiles` must be supplied from decoder's `GroupMultiFileResolver` + `calibration` stack (cycle/profile/phase → CTD/DOXY/CHLA/BBP). No decoder change was allowed in this phase; profile generation remains out-of-scope for writer-contract fix. |
| `TECH` (`N_TECH_PARAM`) | Synthetic `SYN_TECH_*` vs GDAC tech file populated from real tech packets (253/250 etc) | **DATA-COVERAGE** | `write_tech` requires `tech_records` authoritative; real tech must be extracted via `platforms/provor_cts4_ir_sbd/tech` (not writer). Synthetic fixtures are test-only. |
| `BBP700` values | Writer's `bbp_mode=TELEMETRY_ORIGINAL` with `scale=1.665e-06` vs GDAC corrected `1.645e-06` (1.20% systematic per Barnard 54520) | **PUBLICATION-RTQC** | Writer preserves `Original vs Corrected` distinction; `bbp_mode=INCOIS_CORRECTED` with `bbp_corrected_scale` triggers exact `bbp_recompute` via `beta_sw` (no ratio shortcut). GDAC is PUBLICATION-REPROCESSED; classification cites `doi:10.17882/54520` + `PREDEPLOYMENT_CALIB_COMMENT` provenance. |
| `DOXY` ~+0.21 µmol/kg offset | Not exercised in this validation (synthetic DOXY) | **PUBLICATION-RTQC** (open item from Phase 3) | Umbrella `SAGEO2` gain etc. remains PUBLICATION-RTQC; not silently corrected (see Phase 0/2A notes). |
| `HISTORY` (N_HISTORY 2 vs 1) | Synthetic BGC history 2 records vs GDAC maybe 5/8 | **TOOL-AVAILABILITY / EXPECTED** | FileChecker history is DAC-specific; writer writes minimal 2 (CF + CV) per spec, not GDAC parity copy. |
| `id` global attr | GDAC has no `id` (or DOI) ; writer writes only if `ExternalMeta.id` supplied | **EXPECTED** | Per Argo Manual `id` is DOI, not WMO; writer is correct to leave absent when not supplied. |
| `TRAJECTORY` | No file generated | **EXPECTED** | Phase-2C design defers trajectory; `generate_traj=false`. |
| `PT26/27`, `FLAG_SensorBoardStatus`, `253 rtc`, `03530` etc | Not in this SBD group | **UNKNOWN** | Remains open per Phase 2B-1 — research before coding (archimer/LFS/Coriolis). |
| ARVOR/APEX | Not modified | **EXPECTED** | Frozen per constraints. |

No remaining FIXABLEs in meta contract; all remaining diffs are objectively not writer-contract failures.

### 4.4 2902091 shadow comparison (synthetic profiles vs GDAC D/BD)

Writer `2902091_meta.nc` (authoritative 7×2, 161, 11) now dimensions-match GDAC (checked §4.2). `D/BD` with synthetic profiles yields structural `N_PROF=4`, `N_PARAM=3/6`, `N_LEVELS=max`, `N_CALIB=1/2`, `N_HISTORY=1/2` per design; values differ as synthetic (DATA-COVERAGE). This was the prior `1700` literals audit: all literals now classified as OFFICIAL STRUCTURAL, FAMILY-GENERIC AUTHORITATIVE, EXTERNALLY SUPPLIED, or TEST-ONLY FIXTURE — none remain FORBIDDEN FABRICATION.

---

## 5. Deliverables & evidence

- **Edited:** `src/argo_decoder/writer/nc.py` (ExternalMeta required config, derived dims, LAUNCH/PREDEPLOYMENT wiring, Argo attrs, _FillValue, BETASW authoritative), `src/argo_decoder/writer/fixtures.py` (authoritative 2902091 extraction, synthetic isolation).
- **New doc artifact:** `config/metadata/provor_cts4_external_launch_predeploy_example.csv` — per-float launch/predeploy keyed by `flbb_serial` (never WMO allocation/IMEI), example rows for 2663/2662 with provenance `incois_2902*_meta.nc` + `doi:10.17882/54520`.
- **Preserved:** `provor_bio_irsbd/ref/gdac_incois_301/*.nc`, `config/metadata/provor_cts4_301_reference.csv` (frozen 10-col, 1535 rows), docs, tests.
- **Tmp validation:** `/tmp/pub_validation_12170/` and `/tmp/pub_validation_2902091/` (outside workspace, `workspace/tmp` kept clean).

---

## 6. How to supply authoritative config/launch/predeploy for a real float (example)

**Per-float dedicated CSV keyed by `flbb_serial` (not WMO):** `provor_cts4_external_launch_predeploy_example.csv` columns `flbb_serial, launch_config_parameter_name, launch_config_parameter_value, predeployment_equation, predeployment_coeff, predeployment_comment, config_parameter_name, config_mission_number, config_value …` Or as JSON for CLI:

```json
{
  "float_serial_no": "OIN-12IND-FLBB-06",
  "wmo_inst_type": "836",
  "launch_date": "20130222172000",
  "launch_latitude": 10.0,
  "launch_longitude": 68.0,
  "project_name": "Indian ARGO",
  "pi_name": "M Ravichandran",
  "sensor_serial_nos": ["n/a","n/a","n/a","n/a","2663","2663"],
  "config_parameter_names": ["CONFIG_NumberOfSubCycles_NUMBER", "...18 names..."],
  "config_mission_values": [[1,1,1000,...], [1,1,1000,...], [1,5,1000,...]],
  "launch_config_parameter_names": ["CONFIG_VectorBoardShowModeOn_LOGICAL", "...161..."],
  "launch_config_parameter_values": [0,0,-0.06,...4130],
  "predeployment_calib_equations": ["none","none",...,"BBP700=2*pi*khi…"],
  "predeployment_calib_coefficients": ["none",...,"DARK_BACKSCATTERING700=49, SCALE=1.645e-06, khi=1.097"],
  "predeployment_calib_comments": ["",...,"Sullivan et al., Zhang et al. http://doi.org/10.17882/42916 … http://doi.org/10.17882/54520"]
}
```

Call: `argo-decoder cts4 --wmo 2902086 --cycle 98 --input SBD-BGC-raw/12170 --external-meta external_2663.json --bbp-mode TELEMETRY_ORIGINAL --out tmp/pub_validation_12170`

Writer will then `createDimension N_CONFIG_PARAM=len(names)` and `N_MISSIONS=len(mission_values)` with zero hard-coded literals.

---

## 7. Final status

**READY FOR REAL PUBLICATION VALIDATION** (meets `PROVOR_CTS4_PHASE2C_PUBLICATION_DESIGN.md` §12 + `PROVOR_CTS4_PHASE3` audit 12-point as bounded).

- All 4 FIXABLEs from `PHASE3_PUBLICATION_VALIDATION_2026-09-10.md` are now **FIXED** and proven via real SBD-group (12170) and GDAC shadow (2902091/2902086) — dimensions, attrs, wiring.
- No `CONFIG_SYN_*` in production, no WMO/IMEI allocation gate for config/launch/predeploy (flbb_serial only).
- No decoder / 4 CSV / ARVOR / APEX / trajectory modifications.
- Remaining diffs are classified DATA-COVERAGE / PUBLICATION-RTQC / TOOL-AVAILABILITY / EXPECTED / UNKNOWN — not forced to parity.
- **Not** publication-ready: requires one real telemetry-backed cycle (SBD → decoder → profiles + tech) passing `argodatamgt` FileChecker for `R`/`D`/`BD`/`meta`/`tech`. Until then, do not claim `PUBLICATION-READY`.

---

## 8. Next step (real publication validation, out-of-scope for this bounded fix)

1. Decode a full cycle from a real SBD group (e.g., 12170 cycle 98, 00530 cycle 1, or NEW synthetic group not in 10) via `resolve_group` → `GroupMultiFileResolver` → `WriterInputs.profiles` (pres/juld/lat/lon/cycle/direction + raw `beta_raw`/`temp_c`/`psal_c` for exact BBP).
2. Supply authoritative `ExternalMeta` for that group's flbb_serial via dedicated CSV (as above) + `bbp_original_scale` from `provor_cts4_pub_bbp_scales.csv` (flbb_serial).
3. Run `PublicationBuilder.write` → present `tmp/pub_validation_<group>_real/` with `meta`, `tech`, `D`/`BD` (and later `traj`).
4. Run `pyargo`/`argodatamgt` FileChecker and record every difference vs GDAC hypothesis, updating this classification.

---

*Generated 2026-09-10 UTC — writer-contract bounded fix, no synthetic production, no trajectory/APEX change, no 2902091 hard-code, no GitHub workflow.*
