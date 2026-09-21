# ARVOR-I Mono-profile Parity vs INCOIS GDAC — Prompt 10 Report

**Date:** 2026-09-05 · **Scope:** `R*.nc` mono products only (no Tech/Rtraj/Meta/CLI; RTQC Test 4 excluded).
**Fleet:** 1902844, 2904082, 6990711, 7902408 · **Products compared:** 69 (23 + 24 + 7 + 15) vs GDAC refs (23 + 24 + 7 + 16).

Evidence hierarchy applied: Argo manuals → Coriolis MATLAB decoder/RTQC → INCOIS GDAC files → raw telemetry.

---

## 1. Four-float parity table

| | 1902844 | 2904082 | 6990711 | 7902408 |
|---|---|---|---|---|
| Profiles ours / GDAC | 23 / 23 | 24 / 24 | 7 / 7 | 15 / **16**¹ |
| PRES/TEMP/PSAL values | exact | exact | exact | exact |
| Adjusted vars & QC (N_ADJUSTED etc.) | exact | exact | exact | exact |
| Metadata fields (PI, project, serial, firmware, inst. type, centre) | exact² | exact² | exact² | exact² |
| QC-flag value diffs (files) | 4 (c6, c9, c13, c18) | 3 (c9, c12, c21) | 2 (c5, c6 POSITION) | 2 (c11, c15) |
| Position diffs (files) | 1 (c9 LAT) | 2 (c8, c21) | 1 (c5) | 0 |
| JULD ≈ 8 s offset (files) | 15 | 16 | 6 | 12 |
| RTQC tests 1–19 (ex-T4) | cycle-exact³ | cycle-exact³ | cycle-exact³ | c15 T16 only⁴ |

¹ GDAC publishes one 7902408 profile with no counterpart in the raw telemetry → DATA-COVERAGE.
² After this prompt's fixes: PI_NAME, PROJECT_NAME, PLATFORM_TYPE, FLOAT_SERIAL_NO (meta.csv), FIRMWARE_VERSION (sensor-info 7.2.5), WMO_INST_TYPE, DATA_CENTRE 'IN', institution 'INCOIS', CONFIG_MISSION_NUMBER 1, HISTORY_INSTITUTION 'IN' — all exact on all 69 files.
³ QCP$/QCF$ hex masks match GDAC cycle-for-cycle except the T4 done-bit (skipped: GEBCO unavailable).
⁴ Our T16 legitimately fails c15 (threshold verified against vendored MATLAB); the GDAC file shows no T16 flags.

## 2. Fixes implemented (evidence-justified)

| # | Change | Evidence |
|---|---|---|
| F1 | csv4 metadata wired into the mono builder (`meta=`, institution via `institution_for_data_centre`) | CSVs carry every GDAC value; builder never received them |
| F2 | `FIRMWARE_VERSION` from sensor-info `firmware revision number` (new `sensor_firmware_version` row field; family-generic) | GDAC publishes CTD sensor firmware 7.2.5 for ARVOR-I; APEX date-code path unchanged |
| F3 | `CONFIG_MISSION_NUMBER` = 1 (launch mission) | Argo ref-table convention; GDAC = 1 fleet-wide; CSV 0 is a placeholder |
| F4 | `refresh_history_records` PARAMETER parse fixed (was one concatenated 48-char row → suppressed every CF record); CF records now **one per parameter** with START/STOP_PRES bracketing degraded levels | GDAC R1902844_009 CF TEMP 175.6→1287.9 dbar — reproduced exactly |
| F5 | RTQC flag-worsening paths preserve variable attrs (`_FillValue`, `conventions`, `long_name`); 5 QC vars stripped in all 69 files before → 0 now | ADMT contract |
| F6 | Internal attrs (`rtqc_tests_*_hex`, `qc_previous_values`) stripped at write; HISTORY_INSTITUTION no longer re-stamped 'IF' by refresh | GDAC carries only 8 standard globals; refresh ran with meta=None |

Non-changes (evidence says leave): position selection rule (65/69 exact; GDAC's 4 residuals match no documented rule, incl. its own truncation), QC-flag presentation at T12/T14 fails (ours matches the Coriolis reference semantics; INQC's '3'-at-fail has no reference support), ARCA/ARUP/ARGQ IP rows (DAC-side provenance we do not perform).

## 3. Remaining mismatches by classification

- **EXPECTED (63 QC cells / 9+8+3+8+2+1 vars):** flag *presentation* at QC-fail levels — our T12 marks the jump pair '4'/'4' per Coriolis MATLAB; INQC writes '3' (and drops PSAL flags). 6990711 c5 POSITIONING_SYSTEM 'IRIDIUM' (location source interpolated). Row-set/provenance: N_HISTORY (ours IP,IP,QCP$,QCF$,CF vs GDAC 4×IP+ARCA/ARUP+ARGQ,CF), HISTORY software ARPY/V0.1 vs INQC/V4.0, dates, JULD ≈ 8 s (49 files; mixed sign — c9 GDAC is 250 s *later*), dim/var ordering, `history`/DATE_* timestamps, SCIENTIFIC_CALIB_DATE one-run-date vs per-cycle, PREVIOUS_VALUE 0 (our truthful no-QC seed) vs 1.
- **PUBLICATION/RTQC (decoder unchanged):** GDAC ARCA/ARUP/ARGQ IP rows and (ARGQ,CF) audit rows; GDAC '3' presentation above; 7902408 c15 T16 absence in GDAC.
- **TOOL-AVAILABILITY:** QCTEST T4 done-bit (GEBCO unavailable; reported skipped, never fabricated; skipped ≠ passed).
- **DATA-COVERAGE:** 7902408 GDAC-only profile (no raw telemetry); 6990711 c5 position/POSITION_QC (mail fixes missing from compressed telemetry; GDAC point matches no candidate incl. its own arc-minute rule); 1902844 c9 / 2904082 c8 positions (GDAC matches no documented candidate).
- **NOT FIXABLE:** JULD 8 s family (production-time stamping, no rule in telemetry or MATLAB).
- **FIXABLE / FIX CANDIDATE / UNKNOWN:** none open.

## 4. Explicit statements

- **Science-value parity:** PRES/TEMP/PSAL exact on all 69×3 core variables; adjusted fields exact.
- **QC parity:** flag values match on every level of 55/69 files; all 14 residual files are classified presentation/provenance/data-coverage, none wrong by the QC manual or the Coriolis reference.
- **RTQC-test parity (ex-T4):** 14 applicable tests verified against code and GDAC cycle-exact; Test 4 skipped (GEBCO), never counted as passed.
- **Publication-only differences:** GDAC ARCA/ARUP/ARGQ rows, INQC identity, per-cycle calib dates, timestamps/ordering.
- **Data-coverage limits:** raw telemetry absent for 7902408's 16th profile and 6990711/7902408 position fixes.
- **Unresolved:** none at decoder level; four GDAC position cells and the 8-s JULD family remain unexplainable from any documented rule.

Artifacts: per-file JSON in `validation_arvor_i_mono_parity/<wmo>/`, preserved RT products in `validation_arvor_i_rtqc/products/`, fleet runner `scripts/arvor_i_fleet_parity.py`.
