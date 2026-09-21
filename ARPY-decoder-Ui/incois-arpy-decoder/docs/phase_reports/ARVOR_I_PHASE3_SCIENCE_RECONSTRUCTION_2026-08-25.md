# ARVOR-I Phase 3 — Scientific Intermediate Reconstruction

**Date:** 2026-08-25
**Scope:** `CycleReconstructionResult` → scientific objects (`ArvorCycle`, `ArvorProfile`, `ArvorMeasurement`, `GpsRecord`, `CycleTimeData`, `FloatMissionConfig`). No NetCDF writers (Phase 4, not started).
**Implementation:** `src/argo_decoder/platforms/provor_ir_sbd/arvor_i_science.py` (1268 lines)
**Tests:** `tests/unit/test_arvor_i_science_rules.py` (14), `tests/integration/test_arvor_i_science_reconstruction.py` (22); full suite 1887 passed; `ruff check` + `ruff format` clean.

---

## 1. MATLAB downstream call-chain map (buffers → science)

| MATLAB function | Purpose | Implemented | Classification |
|---|---|---|---|
| `process_decoded_data` | loop over buffers, dispatch per packet role | `reconstruct_science` | PROVEN (read) |
| `update_float_config_ir_sbd_222_223_225_232` | MC/TC/IC ← Param#1/#2 items (MC←10..41, TC←42..71 [30 for 232], IC←Param2 10..25); MC002/MC011/MC012 mission-1/2 bookkeeping; MC08 static reset | `FloatMissionConfig.from_stream` (mapping only) | PROVEN mapping; mission bookkeeping NOT PORTED (config display only, no scientific dates) |
| `compute_prv_dates_222_to_227_231_232` | Tech#1 items → cycle time structure | `build_cycle_timing` | PROVEN (incl. cycle-1-short rule, item-20 day reconciliation, MC29-mod in-air branch, ICE ascent-abort date swaps) |
| `store_clock_offset_prv_ir` / `get_clock_offset_value_prv_ir` / `adjust_clock_offset_prv_ir` | clock-offset events, selection/interpolation, application | `collect_clock_offset_events`, `clock_offset_for_cycle`, `apply_clock_offset` | PROVEN (all three sub-functions read to the end this phase) |
| `get_nb_meas_list_from_tech` | expected measurement counts ← Tech#2 | expected counts in profile builder | PROVEN, corrected mapping (items 8/9/11/12; Coriolis column-read retained as comparison only) |
| `get_pres_cut_off_prof` | deep/shallow split pressure | `pres_cutoff` in profile builder | PROVEN (Tech#2 items 15/16/17 sub-surface P, else CONFIG_PX02_, else 5.5 dbar) |
| `create_prv_drift_212_222_231` / `create_prv_profile_212_222_231` | CTD triplets → drift/profile measurements; drift dates from MC09 spacing; profile first-meas date transmitted | drift + profile builders | PROVEN core; INFERENCE on sort details (below) |
| `store_gps_data_ir_sbd` / `compute_jamstec_qc` | GPS records (item-61 gate), JAMSTEC QC | `GpsRecord`, `jamstec_qc` | PROVEN (full read incl. iterative passes; discrimination branch partially ported — Argos-class specific) |
| `compute_profile_location_from_iridium_locations_ir_sbd` | mail CEP<5 km, 1/r² weighted mean | `_iridium_mail_location` | PROVEN |
| `compute_profile_location2_from_iridium_locations_ir_sbd` | second (fallback) Iridium location | NOT PORTED | UNKNOWN — no float in this dataset needed it (see ledger #6) |
| `add_profile_date_and_location_201_to_230_40x` | profile JULD/position chain | `_profile_date`, `_assign_locations` | PROVEN (D: descentToParkStart(−adj) → lastMsgTime(c−1); A: ascentEnd(−adj) → transStart → firstMsgTime(c)) |
| `fill_empty_profile_locations_ir_sbd` | interpolate/extrapolate missing locations | fill pass in `_assign_locations` | PROVEN algorithm (read this phase); launch-GPS anchor NOT REPRODUCIBLE (see ledger #2) |
| `compute_first_last_msg_time_from_iridium_mail` | min/max session time per cycle | `_first_msg_time` / `_last_msg_time` | PROVEN |
| `store_ice_information_arvor` | ICE aborted-cycle detection | `_ice_aborted` | PROVEN |
| `clean_duplicates_in_received_data` | byte-identical duplicate rows | `_dedup_buffer` | PROVEN (keep first, log drops) |
| `update_mail_data_ir_sbd(_delayed)` | mail → cycle tagging | `MailInfo` | PROVEN (delayed-mode override tables are for other WMOs — no patch) |
| `assign_CTD_measurements` | nearest-in-time P/T/S association | NOT PORTED | Phase-4 (trajectory product only) |
| `compute_interpolated_CTD_measurements` | CTD interpolation onto regular grid | NOT PORTED | Phase-4 (trajectory product only) |
| `process_trajectory_data_222_223_225_231_232` / `finalize_trajectory_data_ir_sbd` | trajectory assembly | NOT PORTED | Phase-4 |
| `process_profiles_*`, `decode_provor_2_nc*` | NetCDF emission | NOT PORTED | Phase-4 |

## 2. Date/timestamp provenance model

Five distinct clocks, never mixed:

| Clock | Source | Role | Label |
|---|---|---|---|
| Float RTC | Tech#1 float-day counter + items 5/6/7 (dd/mm/yy), minutes item 9 | ALL scientific dates | RAW TELEMETRY |
| Float RTC at CTD | first-measurement time in each CTD packet | anchors every measurement series | RAW TELEMETRY |
| Iridium session | .eml transport headers | CEP location fallback, first/lastMsgTime, c13 date fallback | TRANSPORT (kept separate; see ledger #4) |
| Email reception | mailbox headers | never used | — |
| GPS | Tech#1 items 53–61 | position + cycle-tag date | RAW TELEMETRY |

* `julD2FloatDayOffset` = datenum(T1 items 5–7) − item 8 — verified CONSTANT per float (6990711: 2025-03-02; 7902408: 2026-03-25).
* Clock offset (Tech#1 item 73, seconds): measurement dates − s/86400 (**PROVEN**, `adjust_meas`); cycle timing fields − round(s/60)/1440 (**PROVEN**, `adjust_time`); interpolation between events at transStartDate (fallback ascentEndDate), rounded to 1 s, next event's float time pre-adjusted by its own offset (**PROVEN**, `get_clock_offset_value_prv_ir`).
* No timestamp is ever invented: every date is transmitted, or derived from a transmitted date + a transmitted/config spacing, or absent with a recorded reason (`CycleTimeData.reasons`, `ArvorProfile.date_source`).

## 3. CTD aggregation rules (descent/drift/ascent separate)

1. Packet roles: type 2 = drift (park), type 3 = descent profile, type 4 = ascent profile. Kept in three separate structures; never merged (`ArvorCycle.drift`, `profiles[descent|ascent_deep|ascent_shallow]`).
2. Slot order preserved as transmitted; profiles sorted by pressure (descending for ascent, ascending for descent) — packet transmission order never corrupts logical order (validated on 6990711 burst).
3. Byte-identical duplicate rows dropped, keep-first, logged (`clean_duplicates_in_received_data` port).
4. Sentinels preserved: pres 9999.9 dbar / T,S 99.999 stay as-is in `ArvorMeasurement`; raw counts kept (`pres_counts` etc.) alongside physical values.
5. Measurement dates: first slot carries the transmitted first-measurement time; subsequent slots spaced by cycle config (drift: MC09 hours; profile: computed from counts/TC04/TC22 chain). Empty date → `None`, never interpolated.
6. Deep/shallow split at `presCutOffProf` (sub-surface pressure from Tech#2 items 15/16/17 when non-zero, else 5.5 dbar); engine-232 `>=` vs `<` resolved by firmware checksum (Phase-1 evidence).
7. Expected counts (corrected mapping, PRIMARY): descent = items 8+9, ascent = items 11+12; `profile_completed = expected − received`; incomplete cycles stay incomplete (no back-fill).

## 4. GPS handling rules

1. GpsRecord only when Tech#1 item 61 == 1 (MATLAB gate). 6990711 c5/c6 re-transmitted the c4 fix byte-identically with item61=0 → **no record, no re-dating, no flag** — the fix is simply not emitted (PROVEN).
2. JAMSTEC QC (`compute_jamstec_qc`, fully read): chain per cycle from the previous cycle's last qc=1 fix; speed ≤ 3 m/s; within-cycle duplicate = identical lat AND lon AND date; within-cycle gap > 1 day → qc 4; dt floor 1 s; iterative passes (net-equivalent to the implemented single pass for ≤1 fix/cycle); unanchored first fix stays qc 1.
3. Cross-cycle byte-identical reuse with a later date is ACCEPTED when the implied speed ≤ 3 m/s (0 m/s for a stationary re-transmission).
4. Position chain: GPS (qc 1) → Iridium mail CEP<5 km 1/r²-weighted mean (qc 1) → fill_empty interpolation/extrapolation (qc 8). Pre-launch (factory/deck) mails never feed positions or dates.

## 5. Implementation summary

`reconstruct_science(messages, launch_date)` → `ArvorScienceResult`:
per cycle: `FloatMissionConfig` extraction (also from param-only/pre-launch buffers), `CycleTimeData` (all Coriolis date fields + adjusted twins + reasons), clock-offset events & application, `GpsRecord` + JAMSTEC QC, drift measurements (MC09 spacing), profiles (expected counts, split, dates, locations), ICE abort detection, notes everywhere a value is missing and why. `ArvorMeasurement` keeps raw counts, physical values, slot index, packet reference, float date, adjusted date, date source.

## 6. Validation (both floats, read-only raw)

**6990711** (launch 2025-03-02 05:16 UTC): 7 complete cycles; c1 start 05:10 (items), descent 54/54, ascent 96+6/102; drift 1 then 17×6; GPS qc 1 on c1–c4, c7; c5/c6 no GpsRecord (stale fix) → locations interpolated qc 8; c1 descent extrapolated qc 8; clock offsets −5, −23×3, −69 s; no Param#1 → ascent_end None (reason recorded), ascent dates = transStart(−adj); profile dates precede GPS fix times by 1–2 min (consistent: fix acquired at transmission start).

**7902408** (launch 2026-03-25 17:44 UTC): complete {1,4,9,12} / incomplete {2,3,5,6,7,8,10,11,13}; c13 forced incomplete, no expected counts (no Tech#2), mail-session date (labelled); config MC09=12, MC29=0, MC31=5, TC04=28000, TC22=33000 → ascent_end computed for all timed cycles; c1 descent 52/52, ascent 99+5/104; pending counts 30/28/…/72/45 on incomplete cycles; pre-launch mails (7 sessions incl. 2025-09-19 factory + 2025-11-20 + deck tests) flagged and excluded — the factory-location bug (c1 descent at 11.56°N 80.31°E) was caught and fixed this phase; cycles 14/15 remain pending (Phase-2 `go=0`), not reconstructed, no fabrication.

## 7. Disagreement ledger

| # | Topic | Coriolis-as-coded | This implementation | Resolution |
|---|---|---|---|---|
| 1 | Tech#2 expected counts | column read (items 4/5/6) | corrected items 8/9/11/12 | user correction is PRIMARY (retained; never revert) |
| 2 | fill_empty leading edge | launch GPS anchor (cycle −1), QC 3/8 | extrapolation from first two surfacings, QC 8 | launch position not in dataset → DATA-COVERAGE, labelled |
| 3 | `adjust_hydrau` divisor | `/14410` (typo for 1440) | `round(s/60)/1440` | deviation documented; max effect ≈ 8.6 s on hydraulic dates |
| 4 | c13 profile date | firstMsgTime (mail session) | same, `date_source='iridium-mail'` | Coriolis behaviour vs "no email timestamps as float timestamps": kept with explicit label; only fires when float timing absent |
| 5 | JAMSTEC discrimination branch | Argos accuracy classes (posAcc) | flags current record (conservative) | never triggered on this dataset (GPS, 1 fix/cycle) |
| 6 | Loop-4 second Iridium location | locationDate2 fallback | not ported | no profile needed it on either float |
| 7 | update_float_config MC002/MC011/MC012 mission bookkeeping | mission-1/2 config copies | not ported | affects config display fields only, no dates/measurements |

## 8. PROVEN / INFERRED / UNKNOWN

* **PROVEN:** field→item mapping; julD2FloatDayOffset constancy; clock-offset units + interpolation + rounding; expected-count mapping (validated on both floats); presCutOffProf; profile date chain; GPS gate + JAMSTEC rules (incl. stale reuse); mail CEP fallback; fill_empty algorithm; ICE abort gates; sensor conversions; duplicate handling.
* **INFERRED:** profile sort beyond packet order (pressure sort); fill_empty edge strategy without launch position (ledger #2); jamstec discrimination branch shape (ledger #5).
* **UNKNOWN / not reproducible:** launch GPS position (not in dataset); cycles 14–15 of 7902408 (telemetry not received); Phase-4 functions (trajectory, NetCDF) unread beyond purpose.

## 9. Phase-4 recommendation (NOT begun)

Proceed to NetCDF emission (`_prof.nc` first, then `_tech.nc`/`_Rtraj.nc`) consuming `ArvorScienceResult`, porting `process_profiles_*` + `decode_provor_2_nc` mappings, after obtaining: launch metadata (position, WMO/install metadata) to resolve ledger #2, and GDAC reference NetCDFs for both floats to extend validation beyond operator CTD files. Trajectory product requires `assign_CTD_measurements` + `compute_interpolated_CTD_measurements` ports. Stop point respected: no Phase-4 code has been written.
