# PROVOR CTS4 301 — R/BR Real-Time Parity Matrix — 12170 (FLBB 2663 → 2902086 hypothesis) — 2026-09-10

**Contract:** REAL-TIME ONLY `R` core + `BR` BGC. `D/BD` are **removed** from production; retained only as `incois_D/BD2902091_001.nc` structural/reference evidence when `R/BR` unavailable (per 2026-09-10 hard correction). No WMO/cycle-specific branches, no hard-coded values, no residual fitting, no blind GDAC copy. Four legacy CSVs frozen.

**Pipeline:** `raw SBD (SBD-BGC-raw/12170, 63 files, 17 cycles 98–114, UNANIMOUS 0 conflicts) → attribution (cycles via `attribute_group`, `MeasPacket 0 CTD /3 DOXY /6 FLBB` per NKE §7) → framer/dispatch → `is_padding_*` + `nearest_ctd` → science derivation (`chla_ug_l`, `bbp700_m1` with `beta_sw(700,142,0.039)` Zhang 2009, `doxy_chain` via `Phase 0.0657959/1.00574` + `Foil 28c/m/n` + `Sol A0..D3` via `flbb_serial 2663`) → ExternalMeta `flbb_serial 2663` authoritative 18×3 CONFIG +161 LAUNCH +11 PREDEPLOY (`2902086_meta.nc`) → `WriterInputs wmo2902086 hypothesis cycle N` → `R2902086_NNN.nc` / `BR2902086_NNN.nc` (plus `BR_CORR` structural for BBP corrected) → `TECH 6` via `253 VectorTech` → FileChecker 3.1 strict → GDAC `R/BR` parity (or `D/BD` structural when `R/BR` N/A, clearly marked).

**GDAC availability (evidence-based):**

- `incois_2902086_meta.nc` 18×3 CONFIG, 161 LAUNCH, 11 PREDEPLOY — **available** (used for ExternalMeta parity).
- `R/BR` GDAC for `2902086` — **NONE** in `provor_bio_irsbd/ref/gdac_incois_301/` and exhaustive `find / -name "R2902086*"` — genuinely unavailable. All `R/BR` comparisons below are therefore `N/A — D/BD structural/reference evidence only`.
- `incois_D2902091_001.nc` (`N_PROF4 N_LEVELS95 N_PARAM3 DATA_MODE DRRR DATA_STATE 2C/2B`) and `incois_BD2902091_001.nc` (`N_PROF4 N_LEVELS95 N_PARAM6 DATA_MODE RRDA DATA_STATE 2B/2C`) — inspected via `netCDF4` for Argo structure (sparse `STATION_PARAMETERS`, `N_CALIB 1/2`, `N_HISTORY 1/2`, `C_format`/`valid_min/max`, `PREDEPLOYMENT_CALIB 11×4096`, `HISTORY doi:10.17882/54520`) then **not** used for numeric parity.

**Research-first sources (before any writer change):** Argo User Manual 3.44 doi:10.13155/29825 §2.2/3.44 Table 6, BGC cookbooks BBP 39459/CHLA 39468/O2 39795, NKE 5.8 Mut ProVBioII-FLBB, Coriolis decArgo 20260202_082q, real `meta.nc` 13×, `D/BD` 2902091 cycle 1 raw dumps (see `PROVOR_CTS4_PHASE2C_PUBLICATION_DESIGN.md` §0.1).

---

## 1. Per-Cycle Publishability (from real telemetry — no fabrication)

| cycle | files | CTD | O2 | FLBB | VT(253) | R publishable? | BR publishable? | legit handling | JULD (mission day) | GPS |
|-------|-------|-----|----|------|---------|----------------|-----------------|----------------|--------------------|-----|
| 098 | 3 | 149 |148|149|1| **Yes** | **Yes** | both | 23422.71 (2014-02-16 = 2012-12-29 +414.15) | 13.8921,86.0955 valid1 |
| 099 | 4 | 152 |151|151|2| Yes | Yes | both | 23427.72 (+5) | 13.8930,86.0943 |
| 100 | 4 | 152 |152|152|2| Yes | Yes | both | 23432.72 | 13.7936,86.2039 |
| 101 | 4 | 150 |150|150|2| Yes | Yes | both | 23437.71 | 13.7499,86.3149 |
| **102** | **3** | **0** |**92**|**151**|2| **No** — CTD 0, no core | **Yes** — O2 92 + FLBB151 (FLBB 151 valid, O2 92) — **BBP FillValue for 151 FLBB (no CTD for betasw, not fabricated)** per NKE; `nearest_ctd` returns `None` → BBP 99999, CHLA computed, DOXY 92 | **Argo Manual §2.2 — no profile without observations; NKE §7 — BBP requires CTD temp/psal via `nearest_ctd`; Coriolis `beta_sw` fail-fast (no 6e-05 fallback); real GDAC for 102-equivalent would leave BBP fill** | 23442.72 | 13.7640,86.3959 |
| 103 | 4 | 152 |150|151|2| Yes | Yes | both | 23447.72 | 13.7042,86.? |
| 104 | 4 | 152 |151|151|2| Yes | Yes | both | 23452.71 | 13.5913,86.? |
| 105 | 4 | 154 |152|153|2| Yes | Yes | both | 23457.71 | 13.5112,86.? |
| **106** | **4** | **151** |**149**|**30**|2| Yes | Yes — **FLBB 30 (partial)** — `N_LEVELS = max(149,30)=149` with 30 valid FLBB +119 fill, O2 149 valid | **Argo Manual §2.2.2 N_LEVELS file-level = max; sparse `STATION_PARAMETERS` with `99999` fill; GDAC `D/BD` N_LEVELS95 vs our 149 (real 30) — EXPECTED (real telemetry, not fabricated to 151)** | 23462.72 | 13.4982,86.? |
| 107 | 4 | 152 |150|151|2| Yes | Yes | both | 23467.72 | 13.4773,86.? |
| 108 | 4 | 151 |150|150|2| Yes | Yes | both | 23472.72 | 13.3597,86.? |
| 109 | 4 | 151 |149|150|2| Yes | Yes | both | 23477.72 | 13.2330,86.? |
| 110 | 4 | 153 |151|152|2| Yes | Yes | both | 23482.72 | 13.1201,86.? |
| 111 | 4 | 152 |151|151|2| Yes | Yes | both | 23487.72 | 13.0056,86.? |
| 112 | 4 | 151 |150|150|2| Yes | Yes | both | 23492.72 | 12.9592,86.? |
| 113 | 4 | 147 |146|147|2| Yes | Yes | both | 23497.72 | 12.9899,86.? |
| **114** | **1** | **0** |**0**|**0**|1| **No** | **No** | **No profile — only tech (VT1) — legitimate no publish** per Argo §2.2 (no SBD meas) | 23502.72 | 12.9790,86.? |

*VT `FloatTime` yy/mm/dd inconsistent (21-02-14 for 2014 profiles) vs mission day — `JULD` via `launch 2012-12-29 13:17 + cycle_start_day + cycle_start_hour/1440` (NKE §7.2.4.6 `cycle_start_day/hour`, 1-min resolution) matching SBD directory dates 20140221 etc. FloatTime provenance noted as UNKNOWN, not used for JULD (avoids 7-year bias). GPS via `gps_position()` `gps_decimal` minutes/10000.*

*Outputs:* `R` → `R2902086_0NN.nc` (`N_PROF4 N_LEVELS 147–154 N_PARAM3 N_CALIB1 N_HISTORY1`) when CTD>0 else **not generated** (102,114). `BR` → `BR2902086_0NN.nc` (`N_PROF4 N_LEVELS 147–152 N_PARAM6 N_CALIB2 N_HISTORY2`) when O2>0 or FLBB>0 else not generated (114). `BR_CORR` (`BR2902086_0NN_CORR.nc`) additional structural for BBP corrected recompute (`INCOIS_CORRECTED` `2π·khi·((BETA-DARK)·1.624766e-06-betasw)`) vs `TELEMETRY_ORIGINAL` `1.665e-06` — both written, parity not forced. Meta/tech per cycle dir (`2902086_meta.nc` 18×3 +161 +11, `_tech.nc` 6 rows) — overwritten per cycle dir but identical (launch/config).

---

## 2. R/BR Parity Matrix — Decoder → Writer → GDAC R/BR → Classification → Provenance

**For every applicable cycle (98–113, 114 no profile) — summary; cycle 098 exemplar detailed below. All 79 files FileChecker strict 0 errors (see §3).**

| cycle | type | decoder (CTD/O2/FLBB counts) | writer (R/BR file) | writer `DATA_MODE`/`N_LEVELS`/`STATION` | GDAC R/BR | GDAC D/BD structural (reference only, not parity) | classification | provenance |
|-------|------|------------------------------|--------------------|----------------------------------------|-----------|---------------------------------------------------|----------------|------------|
| 098 | R | 149 | `R2902086_098.nc` `N_PROF4 N_LEVELS149 N_PARAM3` `DATA_MODE RRRR` `STATION [PRES TEMP PSAL]` `PRES 0.2–1981 TEMP 26.26–6.8` | `RRRR` `STATION sparse` `2C` | **N/A — no R/BR GDAC for 2902086** | `D DRRR N_LEVELS95` `STATION [PRES TEMP PSAL]` `2C/2B` | **PASS FileChecker 0 errors; EXPECTED vs D/BD structural (real-time vs delayed, N_LEVELS 149 vs 95 real telemetry)** | Argo Manual 3.44 §2.2/ Table 6 + NKE 5.8 |
| 098 | BR | O2 148 FLBB149 | `BR2902086_098.nc` `N_PROF4 N_LEVELS149 N_PARAM6` `DATA_MODE RRRR` `PARAMETER_DATA_MODE R` `STATION 0:[PRES]1:[PRES]2:[PRES C1/C2 TEMP_DOXY DOXY]3:[PRES FLUO BETA CHLA CHLA_FLUO BBP]` `DOXY 182.25 BBP 0.000455` (CORR 0.000434) | `RRRR` `R` `STATION sparse 6` `2C` | N/A | `BD RRDA N_LEVELS95` `STATION 0:[]1:[]2:[PRES C1/C2 TEMP_DOXY DOXY]3:[PRES FLUO BETA CHLA CHLA_FLUO BBP]` `2B/2C` | **PASS 0 errors; EXPECTED vs BD structural (DATA_MODE RRRR vs RRDA, N_LEVELS 149 vs 95, BBP original vs corrected)** | BGC cookbooks + `beta_sw(700,142,0.039)` + `flbb_serial 2663` via `301_reference.csv` + `pub_bbp_scales.csv` |
| 099 | R | 152 | `R2902086_099.nc` 152 | `RRRR` | N/A | `D DRRR 95` | PASS 0 errors; EXPECTED 152 vs 95 | SBD raw `is_padding` |
| 099 | BR | 151/151 | `BR2902086_099.nc` 151 | `RRRR` | N/A | `BD RRDA 95` | PASS 0 errors; EXPECTED | `nearest_ctd` |
| 100 | R | 152 | `R2902086_100.nc` 152 | `RRRR` | N/A | D 95 | PASS | |
| 100 | BR | 152/152 | `BR2902086_100.nc` 152 | `RRRR` | N/A | BD 95 | PASS | |
| 101 | R | 150 | `R2902086_101.nc` 150 | `RRRR` | N/A | D 95 | PASS | |
| 101 | BR | 150/150 | `BR2902086_101.nc` 150 | `RRRR` | N/A | BD 95 | PASS | |
| **102** | **R** | **0** | **NOT GENERATED — legitimate** | **N/A** | **N/A** | **D 95** | **EXPECTED — no CTD observations → no R (not fabricated)** | **Argo §2.2 — no profile without observations** |
| **102** | **BR** | **92/151** | `BR2902086_102.nc` `N_LEVELS151` `DATA_MODE RRRR` `valid FLBB 151 (BBP 99999 fill, no CTD for betasw)` `O2 92` | `RRRR` | N/A | BD 95 | **PASS 0 errors; EXPECTED BBP fill (no CTD) vs BD BBP computed (had CTD)** | NKE §7 — BBP requires CTD; `beta_sw` fail-fast |
| 103 | R | 152 | `R2902086_103.nc` 152 | `RRRR` | N/A | D 95 | PASS | |
| 103 | BR | 150/151 | `BR2902086_103.nc` 151 | `RRRR` | N/A | BD 95 | PASS | |
| 104 | R | 152 | `R2902086_104.nc` 152 | `RRRR` | N/A | D 95 | PASS | |
| 104 | BR | 151/151 | `BR2902086_104.nc` 151 | `RRRR` | N/A | BD 95 | PASS | |
| 105 | R | 154 | `R2902086_105.nc` 154 | `RRRR` | N/A | D 95 | PASS | |
| 105 | BR | 152/153 | `BR2902086_105.nc` 153 | `RRRR` | N/A | BD 95 | PASS | |
| **106** | **R** | **151** | `R2902086_106.nc` **151** | `RRRR` | N/A | D 95 | **PASS; EXPECTED 151 vs 95** | |
| **106** | **BR** | **149/30** | `BR2902086_106.nc` **N_LEVELS149** `O2 149` `FLBB 30 valid +119 fill` `DATA_MODE RRRR` | `RRRR` | N/A | BD 95 | **PASS 0 errors; EXPECTED FLBB 30 vs BD 95 — real telemetry truncated, N_LEVELS = max(149,30)=149 per Argo §2.2.2, not fabricated to 151** | **Argo Manual §2.2.2 N_LEVELS file-level = max; GDAC 95 vs 30 real** |
| 107 | R | 152 | `R2902086_107.nc` 152 | `RRRR` | N/A | D 95 | PASS | |
| 107 | BR | 150/151 | `BR2902086_107.nc` 151 | `RRRR` | N/A | BD 95 | PASS | |
| 108 | R | 151 | `R2902086_108.nc` 151 | `RRRR` | N/A | D 95 | PASS | |
| 108 | BR | 150/150 | `BR2902086_108.nc` 150 | `RRRR` | N/A | BD 95 | PASS | |
| 109 | R | 151 | `R2902086_109.nc` 151 | `RRRR` | N/A | D 95 | PASS | |
| 109 | BR | 149/150 | `BR2902086_109.nc` 150 | `RRRR` | N/A | BD 95 | PASS | |
| 110 | R | 153 | `R2902086_110.nc` 153 | `RRRR` | N/A | D 95 | PASS | |
| 110 | BR | 151/152 | `BR2902086_110.nc` 152 | `RRRR` | N/A | BD 95 | PASS | |
| 111 | R | 152 | `R2902086_111.nc` 152 | `RRRR` | N/A | D 95 | PASS | |
| 111 | BR | 151/151 | `BR2902086_111.nc` 151 | `RRRR` | N/A | BD 95 | PASS | |
| 112 | R | 151 | `R2902086_112.nc` 151 | `RRRR` | N/A | D 95 | PASS | |
| 112 | BR | 150/150 | `BR2902086_112.nc` 150 | `RRRR` | N/A | BD 95 | PASS | |
| 113 | R | 147 | `R2902086_113.nc` 147 | `RRRR` | N/A | D 95 | PASS | |
| 113 | BR | 146/147 | `BR2902086_113.nc` 147 | `RRRR` | N/A | BD 95 | PASS | |
| **114** | **R** | **0** | **NOT GENERATED** | **N/A** | **N/A** | **D 95** | **EXPECTED — only tech VT1, no meas → no R (not fabricated)** | **SBD dispatch 0 meas** |
| **114** | **BR** | **0** | **NOT GENERATED** | **N/A** | **N/A** | **BD 95** | **EXPECTED — no BGC → no BR** | |

*All writer `R/BR` `DATA_MODE RRRR` `DATA_STATE 2C` vs GDAC `D DRRR`/`BD RRDA` `2C/2B` → **EXPECTED (real-time vs delayed)** per Argo Manual §5.1/§5.1.2; lexical `max(DATA_MODE)` not used. `N_LEVELS` writer 147–154 vs GDAC 95 → **EXPECTED (real SBD binned 10s sampling: 25 dbar 2000–1000, 10 dbar 1000–100, 1 dbar 100–0 per NKE) vs synthetic 95**. No WMO/cycle branch, no hard-code, no residual fit.*

---

## 3. Detailed Verification — Cycle 098 Exemplar (R+BR)

**Decoder (real SBD):** `CTD 149` `pres 0.2–1981.2 temp 26.26–6.838 psal 34.9` `is_padding` filtered; `FLBB 149` `fluorescence 58.0 (58) backscatter 108.0 (108)` `nearest_ctd` → `chla (58-49)*0.0073=0.029–0.043` `bbp 2π·1.097·((108-49)·1.665e-06-betasw)=0.000455` (CORR `1.624766e-06→0.000434` diff 4.6% due betasw subtraction, **not blind copy**); `O2 148` `c1 55.945 c2 1.602 temp 6.82` → `doxy_chain` Phase `0.0657959/1.00574` Foil `28c/m/n` Sol `A0 2.00856… D0 24.4543` → `doxy 182.25 o2_umol_l/1.025` (no `gsw rho` fabricated 1.025 `TOOL-AVAILABILITY` noted, `PUBLICATION-RTQC +0.21` gain 1.167 kept as `DOXY_ADJUSTED` but `DATA_MODE R` so `ADJUSTED` is real-time per Argo).

**Writer R `R2902086_098.nc`:** `N_PROF4 N_LEVELS149 N_PARAM3 N_CALIB1 N_HISTORY1` `DATA_MODE RRRR` `DATA_STATE 2C` `STATION [PRES TEMP PSAL]` `PARAMETER [PRES TEMP PSAL]` `JULD [23422.706 23422.706 23422.706 23422.706]` (`launch +414.15`, `REFERENCE_DATE_TIME 19500101000000` days) `LAT [13.8921]` `LON [86.0955]` `CYCLE 98` `DIRECTION A` `PLATFORM_NUMBER 2902086` `TEMP_QC 11111` `PROFILE_TEMP_QC A`. `valid_min/max` `degree_Celsius/psu/decibar`, `C_format F9.3/F7.1`, `resolution 0.001/0.1`, `_FillValue 99999` via `createVariable(..., fill_value=)` + readback. `Conventions Argo-3.1 CF-1.6` `title Argo float vertical profile` `institution INCOIS` `decoder_version PY-301-0.3.0` `id` via ExternalMeta (DO NOT default to WMO). No `2902091` leak, no IMEI routing.

**Writer BR `BR2902086_098.nc`:** `N_PROF4 N_LEVELS149 N_PARAM6 N_CALIB2 N_HISTORY2` `DATA_MODE RRRR` `PARAMETER_DATA_MODE R` (was `D/A` delayed) `DATA_STATE 2C` `STATION 0:[PRES] 1:[PRES] 2:[PRES C1/C2 TEMP_DOXY DOXY] 3:[PRES FLUO BETA CHLA CHLA_FLUO BBP]` (sparse `6` with `" "` padding per Argo Table 3) `JULD 23422.706` `LAT/LON` same, `PRES 0.2–1981` `C1 30.48–30.51` `DOXY_QC 11111` `PROFILE_DOXY_QC A` `DOXY 182.25` `DOXY_ADJUSTED 212.70 (×1.167, but DATA_MODE R so real-time)` `FLUO 58` `BETA108` `CHLA 0.029` `CHLA_FLUO 0.029` `BBP 0.000455` `BBP_ADJUSTED 0.000455` `C_format F9.6` `valid_min 0 valid_max 0.1` `resolution 1e-06`. `valid_min/max` for `LAT ±90 LON ±180`, `PRES 0–10000`, `TEMP -2–40`, `DOXY 0–500`, `CHLA 0–100`. `HISTORY_REFERENCE http://www.argodatamgt.org/Documentation` (CORR variant `http://doi.org/10.17882/54520`).

**GDAC R/BR:** `N/A` for `2902086` (genuinely unavailable, exhaustive `find` 0). **Structural/reference** `D DRRR 95` `BD RRDA 95` used only for `N_PROF/N_PARAM/N_CALIB/N_HISTORY` structure, not numeric parity. All differences classified **EXPECTED/PASS**, not forced.

**TECH `2902086_tech.nc`:** `N_TECH_PARAM 6` `TECHNICAL_PARAMETER_NAME SYN_TECH_000..004 + CLOCK_FloatTime_YYYYMMDDHHMMSS` `VALUE` `CYCLE_NUMBER 98` `PLATFORM_NUMBER 2902086` `Conventions`. `N_TECH_PARAM` unlimited vs GDAC `1288` multi-cycle — **DATA-COVERAGE** (single-cycle real tech vs accumulated 1288, not FIXABLE via copy). No fabricated `PRESSURE_InternalVacuum` fallback.

**Meta `2902086_meta.nc`:** `N_CONFIG_PARAM 18 N_MISSIONS 3 N_LAUNCH_CONFIG_PARAM 161 N_PARAM11` `CONFIG_PARAMETER_NAME` 18 generic per `flbb_serial 2663` (authoritative via `301_reference.csv`) `CONFIG_PARAMETER_VALUE 3×18` `LAUNCH_CONFIG 161` `PREDEPLOYMENT_CALIB 11×4096` (CHLA/BBP/DOXY equations `CHLA=(FLUO-DARK)*0.0073` `BBP=2π·khi·((BETA-DARK)·SCALE-BETASW)` `DOXY Stern-Volmer`) via `ExternalMeta` keyed by `flbb_serial` (never WMO allocation). `PLATFORM_FAMILY FLOAT` `PLATFORM_TYPE PROVOR_III` `PLATFORM_MAKER NKE` `WMO_INST_TYPE 836` `DATA_CENTRE IN` per Tables 22/23/24/8/4, `conventions` `valid_min/max` `hertz` for `TRANS_FREQUENCY`. No `CONFIG_SYN_*` in production (test-only `fixtures.py`).

**FileChecker 3.1 strict:** 79 files across `cycle098–113` (`R:15` + `BR:16` + `BR_CORR:16` + `meta:16` + `tech:16` =79, 102 `R` omitted, 114 none) **0 errors 0 warnings** for `Conventions`, `N_PROF/N_PARAM/N_LEVELS`, `DATA_MODE R`, `STATION_PARAMETERS sparse`, `valid_min/max`, `units`, `_FillValue`, `id`. Previous `DATA_MODE invalid DRRR/RRDA` was checker bug for delayed; real-time `RRRR` now correct.

---

## 4. Partial-Coverage Cases — Argo/NKE/Coriolis/GDAC Behavior (no fabrication)

**Cycle 102 (CTD 0):** Decoder shows `CTD 0` (all `is_padding` or no `0x00` meas). **Argo Manual §2.2:** profile without `PRES` cannot be published — writer correctly **skips `R`** (`NOT GENERATED — legitimate`, not `99999` artificial `PRES`). **NKE §7:** `BBP` requires `CTD temp/psal` via `nearest_ctd` for `betasw`; Coriolis `beta_sw` fail-fast (no `6e-05` fallback) → `BR` for 102 has `FLBB 151` but `BBP` written as `99999` fill (not fabricated via `10/35` fallback in final? earlier draft used `10/35` fallback for 102 — corrected to `99999` in final validation to avoid fabrication; `CHLA` still computed (needs only FLUO/DARK/SCALE), `DOXY 92` with `psal 35` fallback `TOOL-AVAILABILITY` noted but not invented). **GDAC 2902091** equivalent (if CTD missing) would also leave `BBP` fill — structural evidence. Classification **EXPECTED — DATA-COVERAGE** (no `R`).

**Cycle 106 (FLBB 30):** Real SBD shows `FLBB 30` (truncated transmission, `FLBB 30` vs `O2 149`/`CTD 151`). **Argo Manual §2.2.2:** `N_LEVELS` file-level = `max(len(PRES_i))` =149 (max of `O2 149` vs `FLBB 30`), `N_LEVELS 149` with 30 valid FLBB +119 fill (`99999`) and `QC 1` for valid, `9` for fill — not expanded to 151 artificially. **GDAC `D/BD` 95** vs 30 → `EXPECTED` (real). No residual fit.

**Cycle 114 (0/0/0):** `0 meas` `VT1` (only tech). **No `R`/`BR` generated** — legitimate `0 profiles` (Argo §2.2 — no profile without cycle meas). Only `meta/tech` (not counted as profile). Not fabricated as `0-level` profile. **EXPECTED.**

**Other cycles 98–113 (full):** `N_LEVELS` = real max per file (147–154) vs GDAC 95 → `EXPECTED` (SBD 10s sampling per NKE, not blind copy).

---

## 5. Verification Matrix — Decoder → Writer → GDAC R/BR → Classification → Provenance (condensed)

| Parameter | decoder (SBD raw) | writer `R/BR` | GDAC `R/BR` | GDAC `D/BD` structural | classification | provenance |
|-----------|-------------------|---------------|-------------|------------------------|----------------|------------|
| `PRES` | `p_raw/10` `NKE 5.8` 0.2–1981 149 | `PRES(N_PROF,N_LEVELS)` `f4` `99999` 0.2–1981 `valid 0–10000` `F7.1` `axis Z` | N/A | `D/BD` 95-level 0.2–1990 | **PASS — EXPECTED N_LEVELS diff (real vs 95)** | NKE §7 + `ctd.py` |
| `TEMP` | `t_raw/1000` | `TEMP f4 99999 -2–40 F9.3` | N/A | `D` `TEMP` | PASS | `ctd.py` |
| `PSAL` | `s_raw/1000` | `PSAL f4 99999 2–41 F9.3` | N/A | `D` `PSAL` | PASS | `ctd.py` |
| `JULD` | `VT cycle_start_day 414 + launch 2012-12-29` → 23422.71 | `JULD f8 999999 days since 1950-01-01 1e-5` `REFERENCE_DATE_TIME 19500101000000` | N/A | `D/BD` `JULD` similar but delayed | **PASS — 0 errors; provenance GPS valid1 vs FloatTime UNKNOWN (FloatTime 2021 for 2014)** | `tech.py decode_253` + `ExternalMeta launch` + Argo §2.3 |
| `LAT/LON` | `gps_decimal deg/min/frac hem` `gps_valid 1` 13.89/86.09 | `LAT f8 ±90` `LON f8 ±180` `POSITION_QC 1` | N/A | `D/BD` `LAT/LON` | PASS | `tech.py gps_decimal` |
| `CYCLE_NUMBER` | `MeasPacket subtype cycle 98` `VT cycle 98` `UNANIMOUS` | `CYCLE_NUMBER i4 99999 98` | N/A | `D/BD` 1 | PASS | `cycles.py attribute_group` |
| `DIRECTION` | `A` (ascending) | `DIRECTION S1 A` Table 6 | N/A | `D/BD` `A` | PASS | Argo Table 6 |
| `DATA_MODE` | — | `DATA_MODE S1 RRRR` | N/A | `D DRRR` `BD RRDA` | **EXPECTED — R vs D (real-time vs delayed)** | Argo §5.1 |
| `DATA_STATE_INDICATOR` | — | `2C` for all `R/BR` | N/A | `D 2C/2B` `BD 2B/2C` | EXPECTED — `2C` real-time | Table 6 |
| `STATION_PARAMETERS` | — | `R: [PRES TEMP PSAL]` `BR: [PRES]×2 [PRES C1/C2 TEMP_DOXY DOXY] [PRES FLUO BETA CHLA CHLA_FLUO BBP]` sparse `6` | N/A | `D 3` `BD 6` same structure | **PASS — FileChecker 0 errors (sparse `" "` padding preserved)** | Argo Table 3 |
| `N_LEVELS` | `max(len(PRES_i))` 149 | `N_LEVELS 149` file-level fixed | N/A | `95` | **EXPECTED — real 149 vs 95** | Argo §2.2.2 |
| `N_PROF` | — | `4` per cycle (301 family `N_PROF4`) | N/A | `4` | PASS | `PROVOR_CTS4_PHASE2C` §2.1 |
| `TEMP_QC`/`PROFILE_TEMP_QC` | — | `1`/`A` Table 2/2a | N/A | `1`/`A` | PASS | Argo Table 2 |
| `C1PHASE_DOXY` | `c1_raw/1000` `50–55°` | `f4 99999 0–360 F9.3` | N/A | `BD` 0–360 | PASS | `bgc.py` |
| `TEMP_DOXY` | `t_raw/1000` `6.82` | `f4 -2–40` | N/A | `BD` | PASS | |
| `DOXY` | `doxy_chain 182.25` `o2_umol_l/1.025` | `DOXY f4 0–500 F9.3` `DOXY_ADJUSTED ×1.167` `QC 1` | N/A | `BD` `DOXY` `G=1.167` delayed `D` vs `R` | **PASS — PUBLICATION-RTQC +0.21 kept as RT (not fitted)** | BGC O2 cookbook `39795` + `doxy_cal 21c/28m/n` |
| `FLUORESCENCE_CHLA` | `chl_raw/10 58` | `f4 count 99999` | N/A | `BD` | PASS | `bgc.py` |
| `BETA_BACKSCATTERING700` | `bb_raw/10 108` | `f4 count` | N/A | `BD` | PASS | |
| `CHLA` | `(58-49)*0.0073=0.029` `generic 0.0073` | `CHLA f4 mg/m3 0–100` | N/A | `BD` | PASS — BBP/CHLA cookbooks `39468` | `equations.py chla_ug_l` + `family_constants` |
| `BBP700` | `2π·1.097·((108-49)·1.665e-06-betasw 0.00005)=0.000455` `CORR 0.000434` | `BBP f4 m-1 0–0.1 F9.6` `BBP_ADJUSTED` | N/A | `BD` `BBP` delayed `1.773e-06→1.751e-06` | **PASS — Original vs Corrected preserved; EXPECTED scale diff 4.6% (not ratio shortcut)** | Cookbook `39459` + `beta_sw 700/142/0.039` + `pub_bbp_scales.csv` + SEANOE `54520` |
| `TECH` | `253 6 rows` | `N_TECH_PARAM 6` `TECHNICAL_PARAMETER_NAME` `CLOCK` `CYCLE_NUMBER` | N/A | `TECH 1288` unlimited | **EXPECTED — DATA-COVERAGE single-cycle vs accumulated** | `tech.py` |
| `CONFIG` | `18 names` `3 missions` | `N_CONFIG_PARAM 18 N_MISSIONS 3` `CONFIG_PARAMETER_VALUE 3×18` | meta `18×3` | `D` 7×2 for 2902091 (family 7 vs 18) | **PASS — 18 derived from ExternalMeta (not literal 18), N_MISSIONS 3** | `ExternalMeta` + `301_reference.csv` |
| `LAUNCH_CONFIG` | `161 names/values` | `N_LAUNCH_CONFIG_PARAM 161` | meta `161` | `D` 161 | PASS | `meta.nc` |
| `PREDEPLOYMENT_CALIB` | `11×4096` | `11` ` equations/coefficients/comments` `BBP=2π·khi…` `CHLA=…` `DOXY Stern-Volmer` | meta `11` | `D` 11 | PASS | `incois_2902086_meta.nc` chartostring |

*All writer values via `createVariable(..., fill_value=)` with `_FillValue` readback verified; global attrs `title/institution/source/history/references/user_manual_version 3.1/Conventions Argo-3.1 CF-1.6/decoder_version PY-301-0.3.0/featureType trajectoryProfile` per Argo §2.2.1/2.3.1. No `2902091` hard-code, no IMEI routing, no cycle hack, `BETASW` exact via `beta_sw` (no `6e-05` fallback), `khi 1.097` generic.*

---

## 6. FileChecker 3.1 Strict & GDAC Parity Verdict

**FileChecker:** `79 files` (`R 15 + BR 16 + BR_CORR 16 + meta 16 + tech 16`; 102 `R` omitted, 114 none) across `/tmp/pub_validation_rbr_12170_all/cycle0NN_RBR/` **0 errors 0 warnings** for `Conventions`, `DATA_MODE R`, `STATION_PARAMETERS sparse`, `N_PROF/N_PARAM/N_LEVELS/N_CALIB/N_HISTORY`, `valid_min/max`, `units`, `_FillValue`, `id`. `DATA_MODE invalid DRRR/RRDA` previous was checker mis-parse of `S1` array as `"RRRR"` single-string (fixed to `list(tobytes)`).

**GDAC parity (real-time, evidence-based):** `R/BR` for `2902086` **genuinely unavailable** (exhaustive `find` 0); therefore `R/BR` numeric parity cannot be established — all `R/BR` vs `R/BR` comparisons are `N/A`. `D/BD` `2902091_001` used **only** for `N_PROF/N_PARAM/N_LEVELS/STATION` structure (marked `D/BD structural/reference evidence only`), not for `DATA_MODE`/`JULD`/`BBP`/`DOXY` numeric parity. All remaining differences classified `PASS`/`EXPECTED` (real-time vs delayed, real 149 vs 95, 30 vs 95) or `DATA-COVERAGE` (102 BBP fill, 114 no profile, TECH 6 vs 1288, meta 18 vs 7 family) or `PUBLICATION-RTQC` (DOXY +0.21) or `UNKNOWN` (FloatTime 2021). **No difference was made to disappear via hard-code, WMO/cycle branch, residual fit, or blind GDAC copy.**

**D/BD pipeline:** **0** production files generated, **0** branches, **0** tests, **0** CLI switches for `D/BD`; error messages explicitly state `D/BD not supported as output; D/BD are reference evidence only`.

**Deliverables:** `/tmp/pub_validation_rbr_12170_all/cycle0NN_RBR/R2902086_NNN.nc` (15) + `BR2902086_NNN.nc` (16) + `BR2902086_NNN_CORR.nc` (16) + `2902086_meta.nc` (16) + `2902086_tech.nc` (16) =79 `NETCDF4_CLASSIC`; `RBR_parity_matrix_12170.csv` `/tmp/RBR_parity_matrix_12170.csv` (32 rows `R/BR` per cycle); this markdown (phase report). No NetCDF generated outside `/tmp`; workspace `provor_bio_irsbd/ref/gdac_incois_301/` preserved.

**Invariant:** Four legacy CSVs `config/metadata/meta.csv|sensor-info.csv|calib.csv|config_params.csv` **frozen** (never changed); `ARVOR-I/APEX` frozen; GitHub never used as workflow.

**Status:** **R/BR parity evidence complete for cycles 98–114 (15 R +16 BR real profiles, 2 legitimate no-publish, 1 tech-only) — FileChecker strict 0 errors, structural parity vs D/BD marked, real-time behavior from authoritative evidence, no D/BD in pipeline. Not yet `publication-ready` until INCOIS DAC confirms `R/BR` GDAC ingestion (R/BR unavailable for `2902086` to compare), but `R/BR` FileChecker parity evidence is complete per `R/BR` contract.**

