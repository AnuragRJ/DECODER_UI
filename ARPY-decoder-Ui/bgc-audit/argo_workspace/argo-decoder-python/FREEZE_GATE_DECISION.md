# CTS4 FREEZE-GATE DECISION

**Date:** 2026-09-15 · **Decoder:** PROVOR-Bio / PROVOR-CTS4 Iridium-SBD, decoder-301 family
**Scope reviewed:** every difference reported by all prior parity audits, re-derived from a
fresh run in this session.

## Validation run (fresh, this session)

All 10 raw SBD groups → generic decoder → R/BR + meta + tech + Rtraj → FileChecker v3.0.5
(internal INCOIS specs) → direct GDAC comparison where products exist.

| Gate | Result |
|---|---|
| Raw corpus | 517 `.sbd` packets, 10 groups |
| Decode | **10/10 groups OK** (was 8/10 before this session) |
| Products | **274 files**: 120 R + 124 BR + 10 meta + 10 tech + 10 Rtraj |
| `pytest tests/ -q` | **2381 passed, 1 skipped** |
| FileChecker v3.0.5 | **274/274 FILE-ACCEPTED, 0 FORMAT-ERRORS, 0 checks skipped** |
| FileChecker warnings | **10** — all `PI_NAME` (see row 3) |
| Genericity | `static=PASS dynamic=PASS` |
| Mission-clock anchors | all 10 floats, spread ≤ 1.1e-3 d |

Fleet: 00530→2902115 · 03530→**2902130** · 03580→**2902131** · 06580→2902114 ·
06640→2902118 · 12170→2902086 · 17960→2902093 · 20000→2902092 · 25980→2902087 ·
29030→2902088.

## Three defects found and fixed during this review

These were not in the prior report. Each was found by re-deriving the difference
rather than accepting the earlier classification.

1. **`JULD_FIRST_LOCATION` / `JULD_LAST_LOCATION` counted the previous session's
   GPS fix** (`rtraj_build.py::build_cycle_summaries`). The N_CYCLE location times
   were derived from the unanchored packet buffer while the MC 703 rows correctly
   used the anchored session window, so 2902092 cycles 47 and 52 published a
   location time with no MC 703 row to match. This was the source of all 4
   MC703 FileChecker warnings. Fixed; those 4 warnings are gone.
2. **The mission-clock anchor estimator used a phase-1 packet when a cycle had no
   phase-12 packet** (`mission_clock.py::derive_mission_clock`). Group 03530's
   launch cycle transmits only phases 0 and 1, so one of its 14 anchor estimates
   was biased by 0.536 d while the other 13 agreed to 2.7e-4 d — the consistency
   check rejected the whole float. Fixed; 03530 now decodes.
3. **`CONFIG_MISSION_NUMBER` was published as `1` in every profile file**
   (`writer/nc.py`). That asserts the first configuration for every cycle, which
   is false for all three floats that have changed configuration. Now FillValue.

## Final decision table

| Issue | Current behavior | Evidence | Real defect? | Blocks RT pilot? | Final classification |
|---|---|---|---|---|---|
| **1. Remaining 7 `meta.nc` differences** | `decoder_version`, `history`, `DATE_CREATION`, `DATE_UPDATE`, `DEPLOYMENT_PLATFORM`, `PARAMETER_UNITS`, `START_DATE`/`_QC` differ; all other variables and all 9 global attrs match | Our own build metadata (4) cannot match a Coriolis build. `DEPLOYMENT_PLATFORM` is a deployment-log field absent from telemetry. The other 2 are rows 3 and 5 below. Was 11 differences before Phase 10 | No | No | **EXPECTED** (4 build metadata) + **DATA-COVERAGE** (1) + rows 3 & 5 |
| **2. `START_DATE` representation** | FillValue with `START_DATE_QC` = `9`; `STARTUP_DATE` empty, its QC `9` | UM p54: START_DATE = first descent ≠ LAUNCH_DATE. Across 13 INCOIS floats the true START_DATE precedes LAUNCH_DATE by **−17 to −152 min**. Argo table 2 (UM p76): `9` = "Missing value. Data parameter will record FillValue." Telemetry has no deployment-era absolute timestamp (253 clock is a mission-relative float-day offset; earliest cycle held = 45 / float-day 349). Blank QC is itself a FileChecker error | No — the previous `launch_date` fallback **was** a defect and is fixed | No | **UNAVAILABLE** (real-time limitation, published honestly per table 2) |
| **3. `PI_NAME` FileChecker warnings (10)** | Publishes `M Ravichandran`, byte-identical to INCOIS on all 10 floats | Warning text is `Invalid (not in NVS R40 table)`. Reproduced on INCOIS's **own untouched** `incois_2902093_meta.nc`: same warning, still FILE-ACCEPTED. `PI_NAME` is a scalar variable, not a global attribute | No — INCOIS-side vocabulary registration | No | **NOT A DEFECT** |
| **4. MC703 missing Argos fixes** | We emit one MC 703 row per real GPS fix with `POSITION_ACCURACY` = `G`; no `I` rows | GDAC additionally carries `I` (Argos-interpolated) fixes that are **not present in the SBD telemetry** — fabricating them would be inventing data. All 4 `JULD_*_LOCATION` MC703 warnings were a separate defect (row 8) and are now gone. Orphan-cycle check: **0 orphans** across all 10 Rtraj; GDAC's own single orphan is the cycle-0 launch row | No | No | **UNAVAILABLE** (Argos fixes absent from telemetry) |
| **5. `PARAMETER_UNITS` (F7)** | `degree_Celsius`, `micromole/kg`, `psu`, `mg/m3`, `m-1` | UM p63 requires non-empty per NVS R03, example `degree_Celsius`; UM §3.3.2 p78 states "DOXY unit: micromole/kg". Our **profile-level** `units` match GDAC exactly. INCOIS's own `meta.nc` abbreviations (`degC`, `umol/kg`) contradict INCOIS's own profile files | No — the GDAC metadata is internally inconsistent | No | **NOT A DEFECT** |
| **6. DOXY publication difference** | 0/1285 cells byte-exact on 2902093 BR; max abs 9.468e-02 µmol/kg (0.857%); **median ratio exactly 1.000000000**, CV 0.105% | Not a systematic scale — the median ratio is 1. Differs on **BR profiles only**; R profiles carry no DOXY. Chain re-computes Aanderaa → Stern-Volmer → S/P → TEOS-10 density → µmol/kg rather than replaying a DAC binary. Same signature on all 10 floats and in all 40 D/BD pairs (max 0.7416). No gain/offset is fitted | No — and matching it would require fitting a correction, which is prohibited | No | **PUBLICATION-REPROCESSED** |
| **7. BBP700 original vs corrected coefficient** | Uses `SCALE_BACKSCATTERING700` = 1.86e-06 for 2902093, taken from **INCOIS's own `meta.nc`** `PREDEPLOYMENT_CALIB_COEFFICIENT` | `BETA_BACKSCATTERING700` is **bit-identical** to GDAC on 1287/1287 cells, so the raw channel is right. On 2902093 BR profile 2 (optode grid) all 143 levels are byte-exact; profile 3 (fluorometer grid) differs at ratio ~1.0265, implying ~1.812e-06. One float cannot have two values for one factory coefficient, so GDAC's profile 3 is the inconsistent side. We publish their authoritative number and do not back-solve a different one | No | No | **NOT A DEFECT** (GDAC internal inconsistency) |
| **8. Remaining Rtraj MC differences** | 243/243 (cycle, MC) keys match. All non-identical cells classified | `JULD_DATA_MODE` 1126 (ours `R` vs GDAC `A` — correct for R/BR); `DOXY` 309 ≤8.298e-02; `BBP700` 228 ≤3.737e-05; `CHLA` 23 ≤1.192e-07; QC rows 363; MC703/700/702/704 Argos 81; MC589/600 JULD 6 at 1 ULP; MC599 TEMP/PSAL 17 at 5.00e-04 (half an LSB). The 4 MC703 location warnings were a **real defect**, fixed this session | **Yes — was** (now fixed) | No | **FIXED** (row 8 defect) + **EXPECTED** / **UNAVAILABLE** for the remainder |
| **9. 03530 / 03580 metadata coverage** | **Both now decode and publish.** 03530 (FLBB 3043) → WMO **2902130**, 14 R + 14 BR. 03580 (FLBB 3044) → WMO **2902131**, 13 R + 13 BR | The prior DATA-COVERAGE classification was **wrong**. The live GDAC carries both: `https://data-argo.ifremer.fr/dac/incois/2902130/` and `.../2902131/`, both PROVOR_III / `WMO_INST_TYPE` 836 with the identical 11-parameter BGC set. Found by scanning the live GDAC `SENSOR_SERIAL_NO` across the family range. Their authoritative metadata and 118 calibration coefficients each were added to the reference CSV from their own `meta.nc`; the serial→WMO mechanism was **not** changed. D/BD corroboration: raw optode channels **100% exact** on both | **Yes** — a false negative that suppressed 2 floats | **Was blocking**; resolved | **DATA-COVERAGE** (resolved) |
| **10. `CONFIG_MISSION_NUMBER`** | FillValue (99999) in profile files and Rtraj; the authoritative 3-mission table in `meta.nc` matches GDAC **exactly** | UM §2.4.6.1 p57 defines it as the mission a profile belongs to. A spacing-based derivation was built and tested: 11/11 exact on 2902093, 13/15 on 2902131, but only **3/16 on 2902130**, whose missions 1 and 2 share a 24 h cycle time — the only differing parameter is `CONFIG_FloatReferenceDay_FloatDay`, not observable in cycle spacing. Reverted rather than ship a wrong number | **Yes — was** (the `1` default asserted a false mission) | No | **FIXED** (now FillValue) + **UNAVAILABLE** for the per-cycle value |
| **11. `FLAG_RTCStatus_LOGICAL`** | Publishes the **inverse** of telemetry byte 25 → `1` (clock OK) | `_tech_param_name_301.csv:13` (decoder id 109, msg 253): "1= OK, 0=not OK". Byte 25 = `0` on 269/269 packets, all 10 groups. Sibling decoder `arvor_i_tech.py:489,537` already inverts. **95/95 tech rows exact** on cycle 45, 0 residual differences | **Yes — was** | No | **FIXED** |
| **12. QC on derived BGC channels** | `1` (good) on DOXY/CHLA/BBP700; `0` (no QC performed) on the raw channels | Coriolis `init_default_values.m:1015-1016` and `add_rtqc_to_profile_file.m:1809-1816`. GDAC publishes `3` (probably bad) on the same rows — that is a **delayed-mode** judgement; R/BR cannot make it | No | No | **PUBLICATION-RTQC** |
| **13. `DATA_MODE` / `PARAMETER_DATA_MODE`** | `R` / `RRRRRR` | GDAC shows `A` / `RRRAAA` because it has already applied adjustments. R/BR output is real-time by definition | No | No | **EXPECTED** |
| **14. `TRANS_FREQUENCY` / `TRANS_SYSTEM_ID`** | Both `n/a` | UM p51: `TRANS_SYSTEM_ID` is the subscription programme id; "DACs can use N/A … when not applicable (e.g.: Iridium or Orbcomm)". These are Iridium floats. We previously wrote the PTT (`061796`) — a different field | **Yes — was** | No | **FIXED** |
| **15. `PARAMETER_ACCURACY` / `_RESOLUTION`** | NKE sensor figures published; blank where no figure exists | NKE DOC 33-16-016 Rev3 §8 p61. Corroborated by `generate_csv_meta.m:836-869`. All 11 parameters match INCOIS on both fields | **Yes — was** (hard-blanked) | No | **FIXED** |
| **16. `id`** | `https://doi.org/10.17882/42182` | UM p17: `id` is the Argo GDAC data DOI, not the WMO. We previously published `2902093` | **Yes — was** | No | **FIXED** |

## Direct GDAC comparison — 2902093 (the only float with R/BR products)

18/18 (cycle, profile) keys matched, `only-ours=0 only-gdac=0`. Pressure-matched cells:

| Variable | Exact | Max abs diff |
|---|---|---|
| `PRES` | **7730/7730 (100%)** | 0 |
| `TEMP` | **1293/1293 (100%)** | 0 |
| `PSAL` | **1293/1293 (100%)** | 0 |
| `TEMP_DOXY` | **1285/1285 (100%)** | 0 |
| `C1PHASE_DOXY` | **1285/1285 (100%)** | 0 |
| `C2PHASE_DOXY` | **1285/1285 (100%)** | 0 |
| `FLUORESCENCE_CHLA` | **1287/1287 (100%)** | 0 |
| `BETA_BACKSCATTERING700` | **1287/1287 (100%)** | 0 |
| `CHLA` | 319/1287 | 2.384e-07 |
| `DOXY` | 0/1285 | 9.468e-02 |
| `BBP700` | 0/1287 | 5.121e-05 |

`CHLA` differs by exactly 1–2 float32 ULP (2.384e-07 = 2⁻²²) on cells where
`FLUORESCENCE_CHLA` is **bit-identical** — the same arithmetic, different
rounding order. `LATITUDE`/`LONGITUDE` 72/72 exact. `tech.nc` **95/95 rows exact**
on cycle 45. `meta.nc` 7 differing variables (all classified above).

**2902130 and 2902131 have no R/BR products on the GDAC** — only D/BD/SD
(378/378/378 and 194/194/194). Direct R/BR parity is therefore **UNAVAILABLE** for
them; D/BD corroboration gives raw optode channels 100% exact on both, with the
same DOXY/BBP700 signature as the other floats. Fleet-wide R/BR parity is **not**
claimable from 2902093 alone.

## Blocking defects

**None.**

Every item above is either fixed, an expected real-time/reprocessing difference,
or a documented unavailability published honestly as FillValue rather than
fabricated. No item requires a code change that would assert a value the
telemetry does not carry.

---

# FREEZE CTS4 — READY FOR INCOIS REAL-TIME PILOT

Conditions carried into the pilot:

1. **R/BR only.** D/BD remain reference-only, and are used as corroboration only
   where R/BR is genuinely absent.
2. **No "100% GDAC parity" claim.** Direct R/BR parity is verified for **one**
   float (2902093, 18/18 keys). The other nine are verified by FileChecker,
   genericity, and — for 2902130/2902131 — D/BD corroboration. Fleet-wide parity
   is not established and must not be stated.
3. **DOXY and BBP700 are reprocessed values**, not bit-reproductions of the DAC
   pipeline. Expected agreement is ~0.86% max on DOXY and ~5.4% max on BBP700.
   Any pilot QC threshold must accommodate this.
4. **`START_DATE`, `STARTUP_DATE`, `CONFIG_MISSION_NUMBER` (per-cycle) and the
   Argos `I` fixes are published as unavailable.** They are deployment-log or
   non-telemetry facts. If INCOIS requires them populated, that is a
   metadata-supply question, not a decoder fix.
5. **The 10 `PI_NAME` warnings are expected** and reproduce on INCOIS's own
   files. They do not block acceptance.
6. The four legacy metadata CSVs remain untouched; the reference CSV grew by 236
   rows (2 × 118) sourced from each new float's own `meta.nc`.
