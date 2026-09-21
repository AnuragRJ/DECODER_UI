# PROVOR CTS4 301 — Phase-2C Correction Report (pre-implementation, design-only)

**Date:** 2026-09-10 UTC (Asia/Calcutta)  
**Scope:** Correction pass on `PROVOR_CTS4_PHASE2C_PUBLICATION_DESIGN.md` — 10 items. **No NetCDF writer implemented, no NetCDF generated.**  
**Sources re-checked this pass:** Argo User's Manual 3.44.0 (2025-07-10, doi:10.13155/29825, p65 `N_TECH_PARAM = UNLIMITED`), NKE 5.8 `MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924.pdf` §5.3.6/§7.2.4.9, BGC cookbooks doi:10.13155/39459 (BBP) / 39795 (OXY v2.3.4) / 39468 (CHLA), Coriolis `decArgo_20260202_082q` (`compute_profile_BBP` + `betasw_ZHH2009.m` dep 0.039, `_config/_tech_param_name_301` label tables), SEANOE Barnard doi:10.17882/54520 `55891.csv` (Original vs Corrected per FLBB serial), preserved `ref/gdac_incois_301/*.nc` inspected via `netCDF4`.

---

## 1. Changed contracts (8) — before → after + evidence

| # | Instruction | Before (in 2026-09-10 design) | After (corrected) | Evidence |
|---|-------------|-------------------------------|-------------------|----------|
| **1** | BBP corrected-mode must recompute from raw `BETA`, `DARK`, corrected scale, `BETASW`, `khi`; no `BBP×ratio` shortcut | §19.1 spoke of `factor 1/1.0126≈0.9876`, §15.2 Option A said "applies CorrectedScaleFactor for BETA→BBP", §24.6 test asserted `BBP = telemetry×0.9876` | **Recompute:** `BBP700 = 2·π·khi·((BETA-DARK)·CorrectedScaleFactor - BETASW700)` with `khi=1.097`, per-float `DARK` and `BETASW` (Zhang 2009 dep 0.039). Ratio shortcut is **MUST NOT** — bias at low turbidity (BETASW subtraction order). | BBP cookbook §2.2 equation + χ Table 1 (FLBB 142°→1.097) + Zhang BETASW; NKE 5.8 §7.2.4.9 (LE-float scale/dark in packet 250 free-zone); SEANOE 54520 per-serial Original/Corrected (2663 1.67→1.65, 3046 1.40→1.39, median 0.989, corpus +1.216–1.264% but BBP delta +1.4–3.1% pressure-dependent); Coriolis `compute_profile_BBP` + `betasw_ZHH2009.m` |
| **2** | `N_LEVELS` is one file-level dimension = `max(len(PRES_i))` across `N_PROF` in that output file | §2.1/§2.2 said "max bins across N_PROF for that cycle" (cycle-scoped), §22.1 said "per profile", §14.1 listed dimensions without noting per-file | **File-level fixed dimension** per Argo §2.2.2/§2.6. D-file `N_LEVELS` and BD-file `N_LEVELS` are computed separately (both 95 for cycle 001 are two maxima, not global). Shorter profiles masked to that file's max. | User's Man §2.2.2/§2.6 `N_LEVELS` definition; GDAC D (95 fixed) & BD (95 fixed) confirm file-level; NKE transmission fragmentation independent |
| **3** | Synthetic `99999/88888` DOXY examples stay strictly in dedicated test/example CSVs; never in `301_reference.csv` | §21.2 said synthetic rows "to be promoted to `301_reference`", §27 checklist implied promotion | **Authoritative `301_reference.csv` stays INCOIS-only** (`source_file=incois_<WMO>_meta.nc`, 118 rows in 1534-row file); synthetics live strictly in `provor_cts4_external_doxy_example.csv` (`synthetic:` provenance, PhaseCoef0+1e-4). | 4-layer proof established `doxy_cal_from_external(dict)` for synthetics; authoritative `301_reference.csv` provenance is GDAC meta rows — promotion would pollute deployment registry |
| **4** | Remove hard-coded WMO allocation range; 7-digit numeric validated against external metadata; never derive from IMEI | `WriterInputs.wmo` docstring and §22.1 pre-condition enforced `2900000–3999999 / 290xxxx` | **`WMO ∈ /^[0-9]{7}$/`**, validated against deployment registry/DAC inventory; **no allocation-range gate, no IMEI derivation** (fail-fast). | PLATFORM_NUMBER is `STRING8` WMO per reference table; allocation ranges are operational policy, not spec (§5.1). Dispatcher never derives WMO — it is external input |
| **5** | Freeze one canonical `decoder_version = PY-301-x.y.z`, distinct from `HISTORY_SOFTWARE = PY301` | §12/§16/§22 mentioned "e.g. PY-301-0.3.0" and "e.g. PY301" without freezing | **Frozen:** global attr `decoder_version = PY-301-x.y.z` (regex `/^PY-301-\d+\.\d+\.\d+$/`), HISTORY `SOFTWARE = PY301` (4-char). Tokens disjoint by design. | User's Man §2.2.1 vs §2.6.7 distinguish global `decoder_version` from HISTORY `SOFTWARE`; Coriolis precedent `CODA_057d` vs `CODA` already disjoint |
| **6** | Missing DOXY calib: preserve `C1/C2/TEMP_DOXY` intermediates; only `DOXY` fill/QC=9 | §22.1 said "emits O2 without DOXY", §27 checklist said "omits DOXY" | **Preserve intermediates** `C1PHASE/C2PHASE/TEMP_DOXY` with values+QC; **only** `DOXY`/`DOXY_ADJUSTED` → `_FillValue=99999.0` + `QC=9` (`PARAMETER_DATA_MODE` stays `R`), `DATA-COVERAGE` logged. No fabricated Stern-Volmer. | BGC §2.6.6 intermediates are independent `STATION_PARAMETERS` entries (BD N_PROF=3); INCOIS BD files carry `C1/C2/TEMP_DOXY` as own parameters — suppressing them discards measured data |
| **7** | Internal FLBB model retains raw `BETA` counts + original scale/dark/khi/BETASW for recomputation | §25.1 said "telemetry-only numbers" generically | **Explicit:** `InternalModel` MUST retain `BETA` counts, `DARK`, `Original SCALE`, `khi=1.097`, `BETASW700` (Zhang) alongside cached `BBP_original`; corrected publication recomputes from raw. | NKE 5.8 §7.2.4.9 (raw BETA in MEASUREMENT, scale/dark in `250`), BBP cookbook equation needs all four inputs; caching only BBP loses BETASW ordering → invalid recomputation (links to #1) |
| **8** | Do not make `N_TECH_PARAM` unlimited unless spec/evidence requires it | §14.1/§2.1 said "UNL-like grows" without citing spec; listed UNLIMITED only for `N_CONFIG`/`N_MISSIONS` | **Per spec:** User's Man §2.5.2 p65 verbatim `N_TECH_PARAM = UNLIMITED` and GDAC `incois_2902091_tech.nc` shows `N_TECH_PARAM 1288 unlimited` → **MUST be UNLIMITED**. Conversely `N_LEVELS`, `N_PARAM`, `N_PROF`, `N_CALIB` remain **fixed**; `N_HISTORY`, `N_MISSIONS`/`N_CONFIG` also UNLIMITED (evidence + spec). | `pymupdf` extract p65: `N_TECH_PARAM = UNLIMITED; Number of technical parameters.` + `netCDF4` inspection: `N_TECH_PARAM 1288 unlimited`, `N_HISTORY 5/8 unlimited` |

Housekeeping **9–10:** All 8 changes re-checked against the 5 evidence families above (no NetCDF/writer/CSV/APEX mutation). Corrections appended to `IMPLEMENTATION_PROGRESS.md` §av (append-only; prior history preserved).

---

## 2. Unresolved UNKNOWN / DATA-COVERAGE (carried forward, not guessed)

- **UNKNOWN (spec/tool gaps, NOT guessed):** `PT26/27` per-group tech pairs, `FLAG_SensorBoardStatus` (no 253 wire field; presumably derived from 250 statuses), `253 rtc` byte-order, `03530` cycle-9 stab `0`, optode lead-`u16` serial hypothesis, `TEMP_DOXY T4/T5=0` (reference-only), `gsw rho` fallback `1.025 TOOL-AVAILABILITY`.
- **DATA-COVERAGE (needs authoritative input, not code):** `03530:3043` / `03580:3044` have no row in 13-WMO `301_reference` (but Barnard `2902130/2902131` exist in 54520 — ingest would close); `12170→2902086` remains hypothesis-only; DOXY without optode sheet → intermediates preserved per #6; trajectory `Rtraj` for 301 not observed in mirror.
- **PUBLICATION-RTQC:** DOXY `+0.2076` / `gain 1.0017` on `2902091` cycle-1 BD probe (literal chain vs GDAC) — stays RTQC, writer does not fit.
- **PUBLICATION-REPROCESSED:** BBP `+1.216–1.264%` orig/corr (8/8, median 0.989) is now correctly recomputed (#1) but still **PUBLICATION-REPROCESSED FIXABLE** pending Barnard `CorrectedScaleFactor` ingest.

---

## 3. Ready for Phase 3 writer?

**YES — design is now ready for Phase 3 writer implementation.**

All publication contracts (§1–17) are present with MUST/SHOULD/REFERENCE/OPTIONAL distinction and evidence:

- File types `D/BD` split vs `S/Traj` OPTIONAL, `N_PROF=4` / `N_LEVELS` file-level, 11-param meta order, 6-param BGC split, `PARAMETER_DATA_MODE`, QC/ADJUSTED twins, PREDEPLOYMENT `SCIENTIFIC_CALIB` + Barnard provenance, Tech `N_TECH_PARAM UNLIMITED`, naming, global attrs `Argo-3.1 CF-1.6` with `decoder_version PY-301-x.y.z` vs `PY301`, fill `99999`, FLBB raw retention, DOXY intermediate preservation, WMO external-only.

**Single gate for full parity tests:** ingest Barnard `55891.csv` `CorrectedScaleFactor` into authoritative `301_reference.csv` for corrected-mode `test_phase2c_bbp_corrected.py`; without it, corrected-mode logs `DATA-COVERAGE` as designed and `TELEMETRY_ORIGINAL` mode remains verified.

No writer code, no NetCDF, no legacy CSV schema change, no ARVOR/APEX change was made in this correction pass.

