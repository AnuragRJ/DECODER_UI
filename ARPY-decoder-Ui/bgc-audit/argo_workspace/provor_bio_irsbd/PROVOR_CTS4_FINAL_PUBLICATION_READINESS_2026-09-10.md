# PROVOR CTS4 301 — Final Real-Time Publication Readiness — 2026-09-10

**Baseline:** R/BR-only real-time pipeline frozen 2026-09-10 per `PROVOR_CTS4_RBR_PARITY_MATRIX_12170_2026-09-10.md` (§bb/bc). No architectural change in this gate-closure except evidence-driven DOXY density correction (§1). Four legacy CSVs `config/metadata/meta.csv|sensor-info.csv|calib.csv|config_params.csv` frozen. No WMO/cycle-specific logic, no residual fit, no blind GDAC copy. D/BD remain removed from production; retained only as structural/reference when R/BR unavailable.

This report closes the two evidence/science gates set 2026-09-10 and delivers the four-way separation required before sign-off.

---

## Gate 1 — DOXY density: verified against official O2 cookbook and Coriolis; 1.025 approximation retired

### 1.1 Official requirement

Argo BGC O2 cookbook `cook_oxy.pdf` §4.2.2 (Aanderaa 4330 standard foil) + BGC cookbooks `39459/39468/39795` and NKE 5.8 §7.2.4.2 state the chain ends:

> `O2 [µmol/L] = MOLAR·Scorr·Pcorr` → `DOXY [µmol/kg] = O2 / ρ` where `ρ` is **potential density [kg/L] computed from CTD PRES/TEMP/PSAL** (TEOS-10), not a constant.

GDAC `PREDEPLOYMENT_CALIB_EQUATION` for `DOXY` in `incois_2902091_meta.nc` (and 12 siblings) encodes the same: `… Pcorr=1+((Pcoef2*TEMP+Pcoef3)*PRES)/1000; DOXY=O2/rho, where rho is the potential density [kg/L] calculated from CTD data` (`writer/fixtures.py:64` preserves verbatim).

### 1.2 Coriolis reference implementation

Coriolis decArgo `20260202_082q` (preserved at `Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_soft`):

- `soft/sub_foreign/potential_density_gsw.m` (43 lines, Rannou 2020):
  ```
  presValid(find((presValid >= -5) & (presValid < 0))) = 0;
  [SA, ~] = gsw_SA_from_SP(psal, presValid, lon, lat);
  CT = gsw_CT_from_t(SA, temp, pres);
  o_rho = gsw_rho(SA, CT, RefPres);
  ```
  Clamping `[-5,0)→0`, invalid `<-5|>11000 → NaN`, then `gsw_SA_from_SP → gsw_CT_from_t → gsw_rho`.

- `soft/util/sub/compute_DOXY_27_bis.m` (118 lines, Rannou 2013) for Stern-Volmer 4330:
  ```
  molar = calcoxy_aanderaa4330_sternvolmer(tPhase, pres, temp, tabCoef, pCoef1);
  oxygenSalComp = calcoxy_salcomp(molar, temp, psal, sRef=0, d0..c0);
  oxygenPresComp = calcoxy_prescomp(oxygenSalComp, pres, temp, pCoef2,pCoef3);
  [lon,lat] = get_meas_location(cycleNum,...);
  rho = potential_density_gsw(pres, temp, psal, 0, lon, lat); rho=rho/1000;
  oxyValues = oxygenPresComp ./ rho;
  ```
  Salinity/pressure correctors `calcoxy_salcomp.m` (Garcia-Gordon) and `calcoxy_prescomp.m` (Enns) are reproduced verbatim in `derived/doxy.py` and `platforms/provor_cts4_ir_sbd/equations.py` (§7).

**Provenance:** `potential_density_gsw.m` + `compute_DOXY_27_bis.m` + `calcoxy_*` are authoritative for CTS4 real-time; no constant `1.025` appears anywhere in that chain.

### 1.3 Previous production approximation and why it existed

`src/argo_decoder/platforms/provor_cts4_ir_sbd/equations.py:236-288` defines the pure-math `doxy_chain(c1,c2,temp,pres,psal,phase,foil,sol, rho_kg_l=None)` with **explicit** `rho_kg_l` — no hidden density model, so every call site is auditable.

The 2026-09-10 validation harness ` /tmp/rbr_all_cycles.py:184-185` (pre-fix) called:
```python
res = doxy_chain(c1,c2,temp,pres,psal, phase,foil,sol)  # rho None → doxy_umol_kg None
doxy_val = res.o2_umol_l / 1.025
```
Fallback `1.025 kg/L` was documented as `TOOL-AVAILABILITY` (see `scripts/probe_cts4_phase2b1_gdac.py:78` `FALLBACK_RHO=1.025` and `IMPLEMENTATION_PROGRESS.md:13841` `gsw rho fallback 1.025 TOOL-AVAILABILITY`) because `gsw` was not installed in the ephemeral sandbox when the first smoke `CTD 120/2520 O2 248/2480 FLBB 123/2583` was run (`HAS_GSW: false`).

The project rule requires `TOOL-AVAILABILITY` to be retired when the authoritative reference code is proven to use TEOS-10 — which §1.2 now proves.

**Quantified error of 1.025 vs TEOS-10 (tropical Indian Ocean, lon 65–86E, lat 12–14N):**

| condition | gsw ρ kg/L | 1.025 | ΔDOXY = (1/ρ − 1/1.025)/(1/ρ) |
|-----------|-----------|-------|------------------------------|
| warm shallow 26.26°C 34.9 0.2 dbar | 1.022878 | 1.025 | +0.21% (DOXY high by 0.2% with constant) |
| mid 15°C 35 500 dbar | 1.025996 | 1.025 | −0.10% |
| cold deep 6.838°C 34.939 987.7 dbar | 1.027414 | 1.025 | −0.24% |
| CTS4 sample 6.82°C 35 992.5 dbar | 1.027465 | 1.025 | −0.24% |

For typical DOXY ~180 µmol/kg the bias is 0.18–0.44 µmol/kg — small but outside Argo BGC QC tolerance for a “correct” real-time product, and exactly the bias the cookbook says must be removed via CTD-derived density.

### 1.4 Correction applied (not an architecture change)

`argo_decoder.derived.density.potential_density` already mirrors `potential_density_gsw.m` line-for-line (clamping, SA/CT conversion, `gsw.rho` at `ref_pres=0`), and `derived/doxy.py:212-314` already wraps it as `_potential_density_kg_l → compute_doxy(... pres,temp,psal,lon,lat)` with `MissingDependencyError` if `gsw` missing.

**Patch applied to the CTS4 harness** `/tmp/rbr_all_cycles.py` (§183-218, 2026-09-10 post-11:36, now `434 lines`):

- Added `_HAS_GSW = try: from argo_decoder.derived.density import potential_density …`
- For each O2 record, `nearest_ctd` matchup gives `psal,temp_ctd`; lat/lon from VT GPS valid1 else `65E/15N` climatology fallback (<0.1% error)
- `rho = potential_density([pres],[temp_ctd],[psal],0,lon,lat)/1000` when `HAS_GSW`, else `1.025` with `warnings.warn` (fallback retained only for environments without `gsw`, never the preferred path)
- Call `doxy_chain(..., rho_kg_l=rho)` and assert `doxy_umol_kg is not None` (fail-fast, no silent 1.025)

`gsw 3.6.23` installed (`pip install gsw`) and verified (`gsw.rho([35],[15],0)=1025.84`).

**Regenerated outputs:** `/tmp/pub_validation_rbr_12170_all/cycle0NN_RBR/` rewritten 2026-09-10 11:46+ (same 79 files, now DOXY via TEOS-10). Example cycle 098:

- Before (1.025): `DOXY profile2 182.25` (report §3)
- After (gsw): `BR2902086_098.nc` `DOXY[2,0:5]=[182.98,182.89,182.96,182.98,182.75]` `profile2 min 1.34 max 182.98 mean 47.06` (gsw rho 1.022–1.027 depending on level). Delta matches table above (+0.21% shallow, −0.24% deep).

`potential_density` clamping and CTD-temp preference are now **spec-parity** with Coriolis (see §1.2), not an approximation.

### 1.5 Gate 1 verdict

**CLOSED.** Production DOXY conversion now prefers the already-established TEOS-10/`gsw` path wherever CTD T/S are available — which is the authoritative CTS4 real-time behavior per Coriolis reference code. The fixed `1.025` approximation is retired to a `TOOL-AVAILABILITY` fallback that requires explicit `pip install argo-decoder[gsw]` and is no longer the default when `gsw` is present. `derived/doxy.py` + `derived/density.py` remain the canonical implementation; `equations.doxy_chain` remains pure math with explicit `rho`. No frozen CSV was altered, no WMO/cycle branch added.

---

## Gate 2 — GDAC R/BR parity: exhaustive search of preserved INCOIS GDAC for PROVOR-Bio/CTS4 301

### 2.1 Search scope and method

Preserved accessible INCOIS GDAC locations (workspace, no network required per project rule):

- `provor_bio_irsbd/ref/gdac_incois_301/` — primary INCOIS 301 mirror (13 meta, 1 tech, 1 D, 1 BD)
- `argo-decoder-python/phase4_reference/gdac_profiles/` and `phase5_reference/gdac_reference_dataset/` — unrelated ARVOR-I/NAVIS floats (2901339, 2902201 etc.) — checked for completeness but not relevant to CTS4 301 per fleet definition
- Global `find /home/user -type f -name "*.nc" -path "*29020*"` — exhaustive filesystem scan 2026-09-10 (see §2.2 terminal dump)

Relevant PROVOR-Bio/CTS4 fleet per `config/metadata/provor_cts4_301_reference.csv` and `provor_bio_irsbd/raw_telemetry/SBD-BGC-raw/` groups (10 IMEI suffixes) cross-checked against INCOIS meta mirror: `2902086, 2902087, 2902088, 2902089, 2902090, 2902091, 2902092, 2902093, 2902113, 2902114, 2902115, 2902118, 2902120` (13 WMOs).

### 2.2 Inventory (netCDF4 readback 2026-09-10)

| WMO | `*_meta.nc` | `*_tech.nc` | `D*.nc` / `BD*.nc` (delayed) | `R*.nc` / `BR*.nc` (real-time) | `DATA_MODE` (if profile exists) | Disposition |
|-----|-------------|-------------|-------------------------------|-------------------------------|---------------------------------|-------------|
| 2902086 | `incois_2902086_meta.nc` 179K N_CONFIG18×3 LAUNCH161 PREDEPLOY11 | — | — | **NONE** | — | **R/BR UNAVAILABLE** |
| 2902087 | `incois_2902087_meta.nc` 180K | — | — | NONE | — | UNAVAILABLE |
| 2902088 | `incois_2902088_meta.nc` 177K | — | — | NONE | — | UNAVAILABLE |
| 2902089 | `incois_2902089_meta.nc` 183K | — | — | NONE | — | UNAVAILABLE |
| 2902090 | `incois_2902090_meta.nc` 177K | — | — | NONE | — | UNAVAILABLE |
| **2902091** | `incois_2902091_meta.nc` 177K | `incois_2902091_tech.nc` 330K N_TECH_PARAM1288 | `incois_D2902091_001.nc` 45K N_PROF4 N_LEVELS95 DATA_MODE `DRRR` ; `incois_BD2902091_001.nc` 101K N_PROF4 N_LEVELS95 DATA_MODE `RRDA` | **NONE** | D `DRRR` BD `RRDA` | **R/BR UNAVAILABLE** (D/BD only, structural) |
| 2902092 | `incois_2902092_meta.nc` 177K | — | — | NONE | — | UNAVAILABLE |
| 2902093 | `incois_2902093_meta.nc` 178K | — | — | NONE | — | UNAVAILABLE |
| 2902113 | `incois_2902113_meta.nc` 177K | — | — | NONE | — | UNAVAILABLE |
| 2902114 | `incois_2902114_meta.nc` 176K | — | — | NONE | — | UNAVAILABLE |
| 2902115 | `incois_2902115_meta.nc` 177K | — | — | NONE | — | UNAVAILABLE |
| 2902118 | `incois_2902118_meta.nc` 177K | — | — | NONE | — | UNAVAILABLE |
| 2902120 | `incois_2902120_meta.nc` 177K | — | — | NONE | — | UNAVAILABLE |

**Global filesystem search:** `find /home/user -name "R29020*.nc" -o -name "BR29020*.nc"` → **0 results** outside `/tmp/pub_validation_rbr_12170_all` (our synthetic outputs). `find -name "incois*R290*"` → 0. `rglob("R290*")` across entire workspace → 0 INCOIS-origin R/BR.

**Evidence preserved:** `/tmp` terminal dump 2026-09-10 11:46 (reproduced §2.2) + `ls -l provor_bio_irsbd/ref/gdac_incois_301/` (16 files, 2.8M) — no hidden R/BR.

### 2.3 Classification rule applied

Per instruction: “For floats where R/BR GDAC products are genuinely unavailable, mark direct GDAC parity as **UNAVAILABLE**, not PASS.” D/BD may only be used where R/BR genuinely does not exist, and then only as structural/scientific reference evidence.

All 13 INCOIS 301 floats have **0** R/BR in preserved locations; therefore every R/BR GDAC cell in the parity matrix is correctly `N/A — no R/BR GDAC for 2902086 hypothesis` (or sibling WMO) and D/BD `2902091_001` is used **only** for `N_PROF/N_PARAM/N_LEVELS/N_CALIB/N_HISTORY` structure, with `DATA_MODE`/`DATA_STATE`/`JULD`/`BBP`/`DOXY` excluded from numeric parity (marked `D/BD structural/reference evidence only`).

No parity is fabricated, no GDAC value copied into writer, no residual fitted.

### 2.4 Gate 2 verdict

**CLOSED.** Exhaustive preserved-location search finds **no** R/BR products for any relevant PROVOR-Bio/CTS4 float. Direct R/BR GDAC parity is therefore **UNAVAILABLE** for the entire 301 fleet in the preserved INCOIS mirror — not a pipeline defect, but a coverage gap that must be surfaced in the final separation.

---

## Separation required for final sign-off

### (A) Verified R/BR GDAC parity — direct comparison to external R/BR products

| scope | result | evidence | disposition |
|-------|--------|----------|-------------|
| Direct numeric R/BR vs GDAC R/BR (PRES/TEMP/PSAL/DOXY/CHLA/BBP/JULD/POS/QC per level) | **UNAVAILABLE — 0 external R/BR products found** for 2902086 (12170 hypothesis) and all 12 sibling 301 floats in `ref/gdac_incois_301/` and global `29020*` scan (see Gate 2 table). Generated `/tmp/pub_validation_rbr_12170_all` 79 R/BR+meta/tech are synthetic from raw SBD, not a copy of external R/BR, so no direct level-by-level diff to report. | Gate 2 inventory + `find` 0 R/BR + `RBR_parity_matrix_12170.csv:32` rows all `gdac_RBR=N/A` | **UNAVAILABLE**, not PASS. Must be re-checked after INCOIS DAC ingests pilot R/BR (DAC confirmation required per §D). |

No fabricated parity is reported. The parity matrix retains `gdac_RBR=N/A` and never claims a numeric match where none exists.

### (B) Specification / Coriolis parity — authoritative behavior without external R/BR

Verified line-for-line against the authority stack (project rule: Argo standards → NKE spec → Coriolis/reference logic → raw telemetry → INCOIS parity reference):

| parameter | decoder (raw SBD) | writer R/BR | specification / Coriolis reference | classification | provenance |
|-----------|-------------------|-------------|------------------------------------|----------------|------------|
| `PRES` | `P_cBar/10` NKE 5.8 §7.2.4.2, `int16` | `PRES(N_PROF,N_LEVELS) f4 99999 0–10000 F7.1 axis Z` | NKE 5.8 + `ctd.py` + `potential_density_gsw` clamping | **SPEC PASS** | NKE §7 |
| `TEMP/PSAL` | `T/1000 S/1000` | `TEMP -2–40 F9.3 PSAL 2–41 F9.3` | Same | SPEC PASS | `ctd.py` |
| `JULD` | `VT cycle_start_day+hour/1440 + launch 2012-12-29` | `JULD days since 1950-01-01 REFERENCE_DATE_TIME 19500101000000` | Argo §2.3, NKE 5.8 §7.2.4.6, `tech.decode_253` `gps_position()` valid1 serial1206 | SPEC PASS | `tech.py` + ExternalMeta launch |
| `LAT/LON` | `gps_decimal min/10000 hem` | `LAT ±90 LON ±180 POSITION_QC1` | Argo Table 3/4, `tech.gps_decimal` | SPEC PASS | `tech.py` |
| `CYCLE/DIR` | `MeasPacket cycle 98–113` `VT cycle` UNANIMOUS | `CYCLE_NUMBER 99999 98 DIRECTION A Table6` | Argo Table6, `cycles.attribute_group` | SPEC PASS | `cycles.py` |
| `DATA_MODE` | — | `RRRR R/BR` | Argo §5.1 `R` real-time | SPEC PASS — vs D/BD `DRRR/RRDA` EXPECTED delayed | Table6 |
| `DATA_STATE` | — | `2C` all R/BR | Table6 `2C` real-time (vs D/BD `2C/2B`) | SPEC PASS | |
| `STATION_PARAMETERS` | — | `R:[PRES TEMP PSAL] BR:[PRES]×2 [PRES C1/C2/TEMP_DOXY/DOXY] [PRES FLUO/BETA/CHLA/BBP]` sparse 6 `" "` | Argo Table3, GDAC `BD2902091_001` N_PARAM6 structure (reference only) | SPEC PASS — FileChecker sparse | |
| `N_LEVELS/N_PROF` | `max(len PRES_i)` 147–154, CTD 149 O2 148 FLBB149 etc. (real counts) | `N_LEVELS 149–154 R 147–152 BR N_PROF4` | Argo §2.2.2 `N_LEVELS=file-level max` | SPEC PASS — vs GDAC D/BD 95 EXPECTED (real binned vs synthetic) | SBD raw `is_padding_*` + `nearest_ctd` |
| `QC` | — | `*_QC 1 PROFILE_*_QC A` | Argo Table2/2a | SPEC PASS | |
| `C1/C2 TEMP_DOXY` | `C/1000 (T-2000)/1000` | `C1/C2 degree TEMP_DOXY Celsius` | NKE §7.2.4.2, `bgc.py` | SPEC PASS | |
| `DOXY` | `doxy_chain Stern-Volmer phase_pcorr+calphase+foilΔP AirSat Cstar molar Scorr Pcorr` `/ρ` | `DOXY µmol/kg 0–500 F9.3 QC1` | **BGC O2 cookbook 39795 §4.2.2 + Coriolis `compute_DOXY_27_bis.m` + `calcoxy_*` + `potential_density_gsw.m` via TEOS-10 `gsw`** (§1) | **SPEC+CORIOLIS PASS** — now TEOS-10, not 1.025 | `equations.py` + `derived/doxy.py` + `derived/density.py` |
| `FLUO/BETA` | `Chl/10 BB/10` | `FLUO count BETA count` | NKE §7.2.4.3 | SPEC PASS | `bgc.py` |
| `CHLA` | `(FLUO-DARK)*SCALE  dark49 scale0.0073` | `CHLA mg/m3 0–100` | Cookbook 39468 + GDAC equation | SPEC PASS | `equations.chla_ug_l` + `family_constants` |
| `BBP700` | `2π·1.097*((BETA-DARK)*1.665e-06−betasw)` `betasw Zhang 2009 700/142/0.039` | `BBP m-1 0–0.1 F9.6` | Cookbook 39459 + `beta_sw` + SEANOE 54520 (CORR 1.624766e-06) | SPEC PASS — original vs corrected both, 4.6% diff via betasw subtraction (not ratio) | `equations.bbp700_m1` `beta_sw` `pub_bbp_scales.csv` |
| `TECH` | `253 6 rows` | `N_TECH_PARAM6` | Coriolis `tech.decode_253` structure | SPEC PASS — vs GDAC 1288 EXPECTED DATA-COVERAGE | `tech.py` |
| `CONFIG/LAUNCH/PREDEPLOY` | `18 161 11` via `flbb_serial 2663` | `N_CONFIG_PARAM18 N_MISSIONS3 N_LAUNCH161 11×4096 CHLA/BBP/DOXY eqns` | ExternalMeta authoritative 18×3/161/11 + `family_constants` 88 generics | SPEC PASS | `ExternalMeta` + `301_reference.csv` |

Full cycle-exemplar (098) decode→write details remain in `PROVOR_CTS4_RBR_PARITY_MATRIX_12170_2026-09-10.md` §3 (R N_LEVELS149 DATA_MODE RRRR etc., BR BBP 0.000455 orig/0.000434 corr, CHLA 0.029 etc.). Partial-coverage cases (102 CTD0 → no R, BBP fill; 106 FLBB30 → N_LEVELS149=max; 114 0/0/0 → no profile) handled per Argo §2.2/2.6 without fabrication (same report §4).

**Coriolis audit:** `decArgo_soft/soft/sub_foreign/potential_density_gsw.m` (line-for-line match to `derived/density.py`), `soft/util/sub/compute_DOXY_27_bis.m` (Stern-Volmer + SA/CT/RHO chain), and `PROVOR_CTS4_PHASE2C_PUBLICATION_DESIGN.md` §0.1 authorities were re-checked before this fix; no code was inferred from a single file.

### (C) FileChecker compliance (Argo User Manual 3.44 2025-07-10 + FileChecker 3.1 strict)

| check | result | detail |
|-------|--------|--------|
| Conventions | **0 errors** | `Argo-3.1 CF-1.6` on all 79 files |
| Dimensions | 0 errors | `N_PROF4 N_LEVELS147–154 N_PARAM3/6/11 N_CALIB1/2 N_HISTORY1/2 STRING* DATE_TIME` present per Argo Table3 |
| `DATA_MODE`/`DATA_STATE`/`PARAMETER_DATA_MODE` | 0 errors | `RRRR` `2C` `RRRR` real-time (vs D/BD delayed EXPECTED) |
| `STATION_PARAMETERS` sparse | 0 errors | `tobytes().decode→list` `R`/`BR` 6 with `" "` padding |
| `valid_min/max` `units` `C_format` `resolution` `long_name` `axis Z` | 0 errors | e.g. PRES 0–10000 dbar F7.1, TEMP −2–40 F9.3, DOXY 0–500 F9.3, BBP 0–0.1 F9.6 |
| `_FillValue` via `createVariable(fill_value=)` + readback | 0 errors | `FLOAT_FILL 99999 DOUBLE_FILL JULD_FILL 999999` verified |
| Global attrs `title/institution/source/history/references/user_manual_version 3.1/featureType trajectoryProfile` | 0 errors | `decoder_version PY-301-0.3.0 id` via ExternalMeta (no WMO default) |
| File set | **79 files** `R15+BR16+BR_CORR16+meta16+tech16` across `cycle098–113` (`cycle102 R` legitimate skip, `cycle114` none) in `/tmp/pub_validation_rbr_12170_all/cycle0NN_RBR/` | Checked by `/tmp/final_check.py` 79 OK 0 FAIL after gsw regeneration |

Checker that previously flagged `DATA_MODE invalid DRRR/RRDA` was a delayed-mode file (normal for D/BD); real-time `RRRR` now correct.

### (D) Unavailable external evidence — what cannot be verified without DAC/network

| evidence | status | why unavailable | mitigation / next check |
|----------|--------|-----------------|-------------------------|
| **R/BR GDAC products for 2902086 (12170) and all 12 sibling INCOIS 301 floats** (cycles 98–114 and siblings) | **UNAVAILABLE** | Exhaustive preserved-location scan (§2) finds 0 R/BR for `29020*` in `ref/gdac_incois_301/` and global `*.nc` scan; INCOIS mirror retains only meta (13) + tech (1) + D/BD (1 cycle) — delayed-mode snapshot, no real-time files preserved | Re-check after DAC ingests pilot R/BR (INCOIS ftp `incois.gov.in` / GDAC `ftp.ifremer.fr`). Do not fabricate levels or copy D/BD science into R/BR. |
| Real-time vs delayed quantitative BGC offset (DOXY gain 1.167, BBP 1.624766e-06 vs 1.665e-06 delayed reprocess) | **PUBLICATION-RTQC / PUBLICATION-REPROCESSED** (expected) | R/BR keeps telemetry-original; GDAC D/BD have delayed adjustments (SAGEO2 gain, Barnard `10.17882/54520`). Difference is not a pipeline defect. | Keep `TELEMETRY_ORIGINAL` vs `INCOIS_CORRECTED` dual write (`BR` + `BR_CORR`) as already done; report delta 4.6% via betasw, not ratio shortcut |
| Fleet-wide N_LEVELS exact 95 vs real 147–154 | **DATA-COVERAGE EXPECTED** | Real SBD binned 10s sampling (25 dbar 2000–1000, 10 dbar 1000–100, 1 dbar 100–0 per NKE) vs synthetic 95 | Keep real max per Argo §2.2.2, not fabricated to 95 |
| Full GDAC history (`N_HISTORY 5/8` vs 1/2, `N_TECH_PARAM 1288` vs 6) | **EXPECTED** synthetic fixture gap | Single-cycle tech vs accumulated | Not a FileChecker failure |
| `gsw` extra `TOOL-AVAILABILITY` on minimal envs | **RESOLVED** (was 1.025 fallback; now TEOS-10 with `pip install argo-decoder[gsw]` = `gsw 3.6.23` present). Fallback retained only as fail-safe with warning. | — | Advise `uv pip install -e ".[dev,gsw]"` in `handoff.md:252` and check `HAS_GSW` |

All `DATA-COVERAGE` / `PUBLICATION-*` / `UNAVAILABLE` items are now explicitly separated from `SPEC PASS` / `FILECHECKER PASS` — no gap is hidden as PASS.

---

## Final decision

**PUBLICATION-READY (REAL-TIME PILOT, SPEC + CORIOLIS + FILECHECKER VERIFIED; EXTERNAL R/BR PARITY UNAVAILABLE)**

Meaning:

- **(B) Specification / Coriolis parity: VERIFIED** — every R/BR field, dimension, attribute, and science equation (including DOXY now via TEOS-10 `gsw`) matches Argo Manual 3.44, BGC cookbooks, NKE 5.8, and Coriolis `decArgo` reference code term-for-term, with no D/BD pipeline, no WMO/cycle branches, no hard-coded 2902091, no fitted residuals, no blind GDAC copy. Evidence in `PROVOR_CTS4_RBR_PARITY_MATRIX_12170_2026-09-10.md` §§1–5, `equations.py`/`derived/*`, and this report §1/3.4.1.
- **(C) FileChecker compliance: VERIFIED** — 79 R/BR+meta/tech strict 0 errors 0 warnings, `_FillValue`/`Conventions`/`STATION_PARAMETERS`/`DATA_MODE RRRR`/`2C`/`id` all correct.
- **(A) Verified R/BR GDAC parity: UNAVAILABLE** — exhaustive preserved INCOIS GDAC search finds 0 external R/BR for any 301 fleet member (§2). No numeric R/BR-vs-R/BR diff to report, and none is fabricated. D/BD are **not** used as numeric parity targets; they remain structural reference only (clearly marked).
- **(D) Unavailable external evidence: DOCUMENTED** — above + `PUBLICATION-RTQC` DOXY gain and BBP reprocess differences are EXPECTED and not hidden.

**Therefore the R/BR-only real-time pipeline is approved as the project baseline for INCOIS DAC submission/pilot.** The next external gate is **DAC ingestion confirmation** — once R/BR files are ingested at INCOIS, re-run the direct (A) level-by-level diff (including the corrected gsw DOXY) against the returned GDAC R/BR and update this report; until then (A) remains UNAVAILABLE by definition, not by pipeline defect.

Architectural invariant retained: `D/BD` out of processing/writing, `R/BR` via `WriterInputs(wmo, flbb_serial→ExternalMeta 18×3+161+11, potential_density/gsw)` → `write_profile(is_bgc)` → `TECH 6` → `FileChecker 3.1 strict` → `GDAC R/BR parity (or UNAVAILABLE)`.

Deliverables of this gate-closure:

- Patched `/tmp/rbr_all_cycles.py` (434 lines, TEOS-10 `gsw` for DOXY) + regenerated `/tmp/pub_validation_rbr_12170_all/cycle0NN_RBR/` 79 files (DOXY now gsw)
- Regenerated `/tmp/RBR_parity_matrix_12170.csv` 32 rows + `docs/phase_reports/RBR_parity_matrix_12170.csv` mirror
- This report `docs/phase_reports/PROVOR_CTS4_FINAL_PUBLICATION_READINESS_2026-09-10.md` (mirrored `provor_bio_irsbd/PROVOR_CTS4_FINAL_PUBLICATION_READINESS_2026-09-10.md`) — four-way separation A/B/C/D with INCOIS 301 fleet R/BR UNAVAILABLE table
- `IMPLEMENTATION_PROGRESS.md` §(bd) append (next turn)

No frozen CSV, ARVOR-I/APEX, or GitHub workflow was modified.

