# Defect-Resolution Matrix — Phase 9 (2026-09-15)

The Phase-8 parity report was accepted as the baseline. The architecture was **not** redesigned; only
the defects confirmed in that report were touched, and the complete parity audit was then re-run.
Every number below was produced by a run in this session against `/tmp/p10` (our fleet output) and the
INCOIS reference at `/tmp/gdac`, `/tmp/gdac_2902093`, `/tmp/gdac_d`.

## Matrix

| Issue | Previous result | Root cause | Fix | Direct GDAC result (2902093) | All-10 regression | Final classification |
|---|---|---|---|---|---|---|
| **P0 MC301 RPP** | PRES 431.8–474.8 dbar too shallow; DOXY 0.94 vs 2.65 | `_park_representative` took a per-stream **median** and used the CTD pressure alone | Fill-masked column **MEAN** over the complete MC290 park table; PRES = mean over every stream's own park pressure | PRES/TEMP/PSAL/C1PHASE/C2PHASE/TEMP_DOXY/`FLUORESCENCE_CHLA`/`BETA_B700`/CHLA/`CHLA_FLUORESCENCE` **exact 9/9, 0.000e+00**; DOXY max 1.965e-03; BBP700 max 9.31e-06 | 8/8 publish, identical cycle/profile counts, `static=PASS dynamic=PASS`, 1 distinct trace | **FIXED / EXACT** (DOXY, BBP700 residual = PUBLICATION-RTQC, COEFFICIENT REPRESENTATION) |
| **P0 MC599 LastAscPumpedCtd** | Binned-profile pressure (0.1–0.4 dbar off), no TEMP/PSAL | `p_sub` (the 253 pump cutoff) *is* the pressure and is already published verbatim as tech row 17 `PRES_LastAscentPumpedRawSample_dbar`; the emitter ignored it and never carried the CTD sample | `last_ctd_pres = p_sub`; `build_cycle_rows(..., last_ascent_ctd_sample=(TEMP, PSAL))` from the raw **ascent-phase** CTD record nearest `p_sub` | **PRES exact 9/9, 0.000e+00**; TEMP max 5.00e-04, PSAL max 5.00e-04 = exactly half a telemetry LSB | same | **FIXED / EXACT to one telemetry LSB** — raw `t_raw` is an integer at /1000, so GDAC's 26.1209 is not representable from it (Coriolis float32 rounding) |
| **P1 MC503 deepest bin** | PRES 0.1–0.4 dbar too shallow on 3/9; JULD 10–96 s off on 9/9 | Two independent errors. (a) The bin was read from prof1 alone, but the GDAC quotes the deepest bin **across all published grids** of the cycle — on cy46/50/53 the optode grid (prof3) is 0.1–0.4 dbar deeper than the CTD grid. (b) The date was interpolated across the 252 phase-9 hydraulic series | (a) `prof_deepest_pres_by_cycle[cyc] = max(deepest bin over every published core grid)`; (b) the date is the **latest MC590 ascent row at that pressure**, whichever sensor produced it | **PRES exact 9/9 and JULD exact 9/9 — both 0.000e+00 / 0.0000 s** | same | **FIXED / EXACT** — rule derived from telemetry structure; no GDAC pressure copied |
| **P1 MC301 `CHLA_FLUORESCENCE`** *(newly found this phase)* | 58.33 where the GDAC publishes 0.0608 (factor ≈960) | `CHLA_FLUORESCENCE` (units `ru`) was mirrored from `FLUORESCENCE_CHLA` (units `count`) | Source it from the `ru` column the CHLA science chain already computes — `(counts/10 − dark)·scale` — and average **that** column | **exact 9/9, 0.000e+00**; implied factory coefficients dark 5.0 / scale 0.073 consistent across all 9 cycles | same | **FIXED / EXACT** — averaging first and rescaling after is *not* equivalent, because dark is subtracted inside the per-sample chain |
| **P1 QC raw-channel convention (F11)** | Ours `1` vs GDAC `0` on `C1PHASE_DOXY_QC`, `C2PHASE_DOXY_QC`, `FLUORESCENCE_CHLA_QC`, `BETA_BACKSCATTERING700_QC` | `_write_qc_vars` hard-coded `b"1"` (= *good*) for every parameter. Argo table 2 `0` = *no QC was performed*; Coriolis initialises every parameter to `'0'` after decoding and only RTQC upgrades it | `_NO_QC_PERFORMED_PARAMS` shared by the R/BR writer and the Rtraj writer | **36/36 exact on all four** in R/BR and Rtraj; `TEMP_DOXY_QC` stays `1` and matches | same | **FIXED / EXACT** — derived from `init_default_values.m:1015-1016` and `add_rtqc_to_profile_file.m:1809-1816`, not copied from the GDAC |

## MC503 evidence (the rule was derived, not copied)

GDAC MC503 PRES equals `max(deepest(prof1), deepest(prof3), deepest(prof4))` exactly on 9/9:

| cycle | prof1 | prof3 | prof4 | MC503 | which grid wins |
|---|---|---|---|---|---|
| 45 | 2007.30 | 2007.10 | 2007.30 | **2007.30** | prof1 / prof4 |
| 46 | 1978.60 | **1978.70** | 1978.60 | **1978.70** | prof3 (optode) |
| 50 | 1977.70 | **1978.10** | 1977.70 | **1978.10** | prof3 (optode) |
| 53 | 1977.00 | **1977.40** | 1977.00 | **1977.40** | prof3 (optode) |

cy47/48/49/51/52 have all three grids agreeing. Our prof3 deepest bin already matched the GDAC before
this change, so the value is produced by our own optode grid. The deepest raw ascent CTD sample is
1980.00 / 2010.00 on every cycle, so MC503 is not the raw maximum either.

GDAC MC503 JULD equals the **last** MC590 row at that pressure exactly on 9/9. On cy45/47/48/49/51/52
three sensors transmit at the deepest bin and the CTD row is the latest; on cy46/50/53 the optode row
is the only one there.

## Gates re-run after the fixes

| Gate | Result |
|---|---|
| `pytest tests/ -q` | **2375 passed, 1 skipped** |
| `tests/test_provor_cts4_position_time_regression.py` | **14 passed** |
| Mutation verification | 4 guards, each revert produces a failure: mean→median, first-match-wins MC503, `CHLA_FLUORESCENCE`→count mirror, `BETA_BACKSCATTERING700` removed from the QC set. All files restored and `diff`-confirmed IDENTICAL |
| `ruff check` | `rtraj_build.py` and the test file clean; `cts4_realtime.py` down to the 2 pre-existing findings (`UP037`, `F841 base_pres`) after removing the now-unused `statistics.median` import; `writer/nc.py` 205 findings before and after the edit; `nc/rtraj_cts4.py` 4 findings, all on untouched lines |
| Fleet, 10 groups / 517 SBD | 8/8 reach publication with identical cycle/profile counts; 03530 / 03580 still `DATA-COVERAGE` (FLBB 3043 / 3044 in no INCOIS `meta.nc`) |
| Generic path | `static=PASS dynamic=PASS`, 8 groups, **1 distinct trace**, coefficients from telemetry msg-250 only |
| OneArgo FileChecker v3.0.5 | **214/214 ACCEPTED, 0 REJECTED, 0 FORMAT-ERRORS, 0 files reporting "Remaining checks skipped"**, 12 warnings (8 × `PI_NAME`, 4 × MC703 `JULD_*_LOCATION` on 2902092) |
| Rtraj parity cy45–53 | 243/243 (cycle, MC) keys, 0 only-ours, 0 only-gdac; **7041/9414 both-populated cells identical (74.79%)**, up from 7005 (74.41%) |
| R/BR parity 2902093 | 18/18 profile keys; PRES 7730/7730, TEMP/PSAL 1293/1293, LAT/LON 72/72, `BETA_B700`/`C1PHASE`/`C2PHASE`/`TEMP_DOXY`/`FLUORESCENCE_CHLA` exact |
| MC290 park | 495/495 pressures exact (CTD/O2/FL 165 each), row-count parity 9/9 |
| tech.nc | 950 rows compared, 84 differing — unchanged |
| meta.nc | dims equal, 6/9 global attrs identical, 55/67 vars identical — unchanged |
| D/BD corroboration | 7 floats, 40 profile pairs; TEMP/PSAL/C1PHASE/C2PHASE/TEMP_DOXY/`FLUORESCENCE_CHLA`/`BETA_B700` 100%, PRES 98.55%, 2 known 3-vs-4 profile-count cycles |

## Remaining differences — all previously classified, none newly introduced

* `JULD_DATA_MODE` (1126 cells): the GDAC Rtraj is `DATA_MODE='A'` (RTQC-adjusted, `HISTORY_ACTION`
  `QCP$`/`QCF$`); we correctly publish `'R'`. **Not a defect.**
* `DOXY` (309 cells, max 8.298e-02), `BBP700` (228 cells, max 3.737e-05): PUBLICATION-RTQC and
  COEFFICIENT REPRESENTATION. **Do not correct.**
* `DOXY_QC` / `CHLA_QC` = `3` (363 cells): delayed-mode RTQC. **Never copied into R/BR.**
* MC703 / 700 / 702 / 704 (63 cells): Argos `'I'` fixes absent from the SBD stream. **ASSOCIATION.**
* MC589 / MC600 `JULD` (6 cells): 1 float64 ULP (3.143e-07 s).
* MC599 TEMP/PSAL (17 cells): 5.00e-04 = half a telemetry LSB.

## Still open

| Ref | Issue | Status |
|---|---|---|
| F6 | `PARAMETER_ACCURACY` / `PARAMETER_RESOLUTION` empty | OPEN |
| F7 | `PARAMETER_UNITS` wording (`degree_Celsius` vs `degC`) | OPEN |
| F8 | `id` should be the DOI, not the WMO | OPEN |
| F9 | `FLAG_RTCStatus_LOGICAL` ours `0` vs GDAC `1` on 10/10 | **OPEN — still not derivable** from any NKE / Coriolis / telemetry evidence available in this workspace. Left explicitly unresolved rather than fitted to the GDAC. |
| F10 | `-0` vs `0` on `PRES_SurfaceOffsetBeforeReset…` cy53/54 | OPEN |
| F12 | `START_DATE` / `STARTUP_DATE` 7 min apart, `STARTUP_DATE_QC` | OPEN |
| — | `TRANS_FREQUENCY` / `TRANS_SYSTEM_ID` = `n/a` | OPEN |
| F5 | BBP700 median ratio 1.026783 | DOCUMENTED — coefficient representation, not to be corrected |

**Not declared publication-ready. Not frozen.** The freeze gate requires both P0 defects fixed (done)
*and* the remaining P1 issues resolved from authoritative evidence or explicitly justified as
non-defects; F6–F10 and F12 are neither yet.
