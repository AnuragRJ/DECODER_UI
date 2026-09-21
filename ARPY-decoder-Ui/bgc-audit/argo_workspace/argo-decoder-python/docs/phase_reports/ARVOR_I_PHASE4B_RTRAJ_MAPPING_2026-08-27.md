# ARVOR-I Phase 4B — `_Rtraj.nc` Investigation & Mapping (decIds 222/232)

**Date:** 2026-08-27
**Scope:** Coriolis MATLAB emitter → finalization → `_Rtraj.nc` writer chain,
end-to-end, for decIds 222/232; GDAC reference availability assessment;
input-availability audit against our Phase 1–3 model. Source of truth for
the Phase 4B implementation.

---

## 1. Chain map (all sources read end-to-end)

```
decode_provor_2_nc.m → decode_provor.m
  └─ transType 3, decId ∈ {212,214,216,217,218,221..223,224..227,228,229,230,222,231,232}
     → decode_provor_iridium_sbd_delayed.m          [vendored]
        ├─ g_decArgo_gpsData pre-seeded with launch fix (cycle −1) when a
        │  launch position exists (decode_provor.m)
        ├─ o_tabTrajNMeas = add_launch_data_ir_sbd   (MC 0 row, cycle −1)
        ├─ per buffer: process_decoded_data.m case {222}/{223,225}
        │   ├─ store_gps_data_ir_sbd(tabTech1, cyc, decId)
        │   │    valid fixes (item 61 == 1) → gpsData{1..9,13};
        │   │    JAMSTEC QC (compute_jamstec_qc) when EOL flag (item 66) == 0;
        │   │    sort by date.  GPS date/lon/lat = Tech#1 cols end−3/end−2/end−1
        │   │    = our fields 74/75/76 (float_time, gpsLon, gpsLat).
        │   └─ process_trajectory_data_222_223_225_231_232.m   [vendored]
        │        rows → sort_trajectory_data (get_mc_order_list order)
        ├─ finalize: fill_empty_profile_locations_ir_sbd (prof only)
        ├─ update_output_cycle_number_ir_sbd          (IDENTITY in 076a:
        │   output cycle == transmitted cycle)
        ├─ finalize_trajectory_data_ir_sbd.m          [vendored]
        ├─ set_n_cycle_vs_n_meas_consistency.m        [vendored]
        ├─ finalize_technical_data_ir_sbd (Phase 4A)
        └─ compute_rt_adjusted_param (no adjusted params for these floats)
     → create_nc_traj_file.m → create_nc_traj_file_3_1.m
        → create_nc_traj_c_file_3_1.m  (the `<wmo>_Rtraj.nc` writer)
```

All newly vendored under `tests/data/arvor_i/coriolis_src/`:
`process_trajectory_data_222_223_225_231_232.m`, `sort_trajectory_data.m`,
`add_launch_data_ir_sbd.m`, `finalize_trajectory_data_ir_sbd.m`,
`set_n_cycle_vs_n_meas_consistency.m`, `update_output_cycle_number_ir_sbd.m`,
`create_nc_traj_file{,_3_1,_3_2,_c_file_3_1,_b_file_3_1}.m`,
`init_measurement_codes.m`, `check_ice_algorithm_arvor.m`,
`compute_rt_adjusted_param.m`, `report_rt_adjusted_profile_data_in_trajectory.m`,
`get_mc_order_list.m`, `get_traj_{n_meas,n_cycle,one_meas}_init_struct.m`,
`create_one_meas_{surface,float_time,float_time_ter}.m`,
`get_netcdf_param_attributes.m`, `get_config_mission_number_ir_sbd.m`,
`set_status_of_n_cycle_juld.m`.
Toolbox version: decArgo 20250516_076a (SEANOE 120353.7z, re-fetched).

## 2. Measurement codes (init_measurement_codes.m; Argo table 15)

0 Launch · 89 CycleStart · 100 DST · 150 FST · 190 DescProf · 198 MaxPresInDescToPark
· 200 DET · 203 DescProfDeepestBin · 250 PST · 289 SpyAtPark · 290 DriftAtPark
· 297/298 Min/MaxPresInDriftAtPark · 300 PET · 301 RPP · 389 SpyInDescToProf
· 398 MaxPresInDescToProf · 400 DDET · 450 DPST · 489 SpyAtProf · 497/498 Min/MaxPresInDriftAtProf
· 500 AST · 503 AscProfDeepestBin · 589 SpyInAscProf · 590 AscProf · 593 IceAscentAbort
· 599 LastAscPumpedCtd · 600 AET · 700 TST · 702 FMT · 703 Surface · 704 LMT
· 710 InWaterNearSurface(TST) · 711 InAirNearSurface(TST) · 800 TET · 901 Grounded.

Row order within a cycle = `get_mc_order_list` case {…222…}:
0, 89, 100, 189, 150, 190, 203, 198, 250, 289, 290, 300, 297, 298, 301,
389, 398, 450, 489, 500, 497, 498, 503, 589, 590, 599, 593, 600, 710,
711, 700, 702, 703*, 704, 800, 901.  (076a emits 89/100/150/250/300/450/
500/600/700/800 for the cycle skeleton; DET 200 / DDET 400 exist in the
code only as N_CYCLE-consistency keys — see §7.)

## 3. Emitter semantics (process_trajectory_data_222_223_225_231_232.m)

Inputs per buffer: LAST Tech#1/Tech#2 of the buffer (`idF1(end)`), the
cycle-time structure (Phase-3 `CycleTimeData` = full port of
`compute_prv_dates_222_to_227_231_232`), the GPS store, the mail store,
profiles, park/near-surface/in-air series, hydraulic actions.

* **Deep branch** (`deepCycle == 1`), in emission order:
  1. FMT 702 (mail first-msg time, status 4) + `juldFirstMessage`;
  2. GPS fixes of the cycle → Surface 703 rows (`create_one_meas_surface`:
     accuracy 'G', satellite '', `posQc = num2str(gpsQc)`, status 4), plus
     Iridium fixes (cepRadius ≠ 0) as 703 rows with error ellipse; all
     sorted by date; `juldFirst/LastLocation` = min/max;
  3. LMT 704 (mail last-msg time) + `juldLastMessage`;
  4. clock offset known → `clockOffset = offset_s`, `dataMode = 'A'` else 'R';
  5. skeleton rows (create_one_meas_float_time_ter: status 2, and when the
     clock offset is known `juldAdj = juld − round(s/60)/1440`, adjStatus 3;
     N_CYCLE field ← juldAdj when present else juld):
     CST 89 ← cycleStartDate · DST 100 ← descentToParkStartDate ·
     FST 150 ← firstStabDate (+PRES param firstStabPres when dated) ·
     PST 250 ← descentToParkEndDate · PET 300 ← descentToProfStartDate ·
     DPST 450 ← descentToProfEndDate · AST 500 ← ascentStartDate ·
     AET 600 ← ascentEndDate · TST 700 ← transStartDate ·
     TET 800 ← placeholder (status 9; set by finalize from next CST);
  6. profile dated bins: MC 190 (D) / 590 (A), status 2 (trans flag →
     status 1), params = profile paramList, adj −s/86400;
  7. park drift bins MC 290 (status 1/2 by trans flag, adj −s/86400) then
     RPP 301 = mean of non-fill park rows → `repParkPres` (status 1);
  8. near-surface series MC 710, in-air series MC 711;
  9. hydraulic actions (EV type 6 / pump type 7), date = floatday +
     julD2FloatDayOffset, sorted, bucketed into [CST,PST)→189, [PST,PET)→289,
     [PET,DPST)→389, [DPST,AST)→489, [AST,TST)→589: one PRES row per action
     in the TRAJ file + one VALVE/PUMP_ACTION_DURATION row to the TECH-AUX
     stream;
  10. deepest bins MC 203 (D, last non-fill) / 503 (A, first non-fill),
      one per profile kept (max PRES over profiles);
  11. tech misc from Tech#1 items (cols = item+1): MC 198 ← item 19;
      MC 297/298 ← items 23/24 unless (23==2100 and 24==0); MC 398 ← 31;
      MC 497/498 ← 36/37 unless (36==2100 and 37==0); each PRES-only;
  12. MC 599 LastAscPumpedCtd from Tech#2 items 15/16/17 (sensor-converted,
      psal/1000) when any ≠ 0 and iceAscentAbortedFlag == 0;
  13. grounding MC 901 rows (first/second grounding date+pres from the
      cycle-time structure) → `grounded = 'Y'`; 'Y' also when Tech#1
      item 12 (beached) == 1; else 'N'.
* **Surface-only branch** (`deepCycle == 0`): FMT/GPS/LMT (only fixes whose
  `inTrajFlag` == 0 — each fix consumed once), in-air rows, clock offset/
  dataMode, `surfOnly = 1`.
* `configMissionNumber` from `get_config_mission_number_ir_sbd` when the
  config USE table covers the cycle (not applicable to these floats → fill).

## 4. Finalize + consistency (finalize_trajectory_data_ir_sbd.m, set_n_cycle_vs_n_meas_consistency.m)

1. cycles present in the mail store but absent from the TRAJ rows →
   surface-only records with FMT/LMT only, `grounded = 'U'`, previous
   config number;
2. per cycle: >1 deep record → keep first (error log); >1 surface record →
   merge (earliest FMT, latest LMT, GPS sorted);
3. deep+surface for one cycle → keep only the LAST surface record's
   FMT/LMT/Surface rows (replacing the deep record's own), delete other
   surface rows, re-sort;
4. TET(800) of cycle N−1 ← CST(89) of cycle N (juldAdj when offset known);
5. N_CYCLE merge (one record per cycle): min firstMsg/firstLoc, max
   lastLoc/lastMsg; `juldTransmissionEnd`(N−1) ← `juldCycleStart`(N);
6. expected-MC fill-in for cycles ≥ 0: missing of {DST,FST,PST,PET,DPST,
   AST,AET,TST,TET} (cycle 0: {TST,TET}) → fill rows (status 9) and
   N_CYCLE status ← 9 (set_status_of_n_cycle_juld);
7. consistency pass re-derives every N_CYCLE juld from the MC rows
   (juldAdj preferred; FMT min / LMT max across duplicates),
   FIRST/LAST_LOCATION from positioned 703 rows, GROUNDED ← any 901 row;
   surface rows are re-grouped so the file's first/last locations are the
   first/last 703 rows (GDAC checker requirement).

## 5. Writer layout (create_nc_traj_c_file_3_1.m — confirmed cell-for-cell against both GDAC references)

NETCDF3_CLASSIC.  Dims: `DATE_TIME(14) STRING64 STRING32 STRING16 STRING8
STRING4 STRING2 N_PARAM(=#core params, PRES/TEMP mandatory) N_CYCLE(=#cycles)
N_HISTORY(1) N_MEASUREMENT(UNLIMITED)`.  Globals: title/institution (centre
mapped)/source/history/references/user_manual_version '3.1'/Conventions
'Argo-3.1 CF-1.6'/featureType 'trajectory'/comment_on_resolution.
98 variables in the fixed order captured from the references (header block →
N_MEASUREMENT block → N_CYCLE block → HISTORY block); HISTORY blank for a
fresh file.  Fills: char ' ', int32 99999, float32 99999.0, float64
999999.0 (JULD).  Full var order + attrs transcribed in `nc/rtraj_arvor.py`.

## 6. GDAC reference availability (checked 2026-08-27, exact URLs)

* `https://data-argo.ifremer.fr/dac/incois/6990711/` and `.../7902408/`
  EXIST (DAC = INCOIS; the plain `/dac/<WMO>` form 404s).  Downloaded:
  `{6990711,7902408}_Rtraj.nc` (41,288 / 39,696 bytes; both last-modified
  2026-06-16) and `{6990711,7902408}_tech.nc` → `gdac_arvor_i_ref/`.
* 6990711 Rtraj: 107 rows, cycles −1, 2–8.  7902408 Rtraj: 97 rows,
  cycles −1, 1–6 — **stale**: its own tech.nc (updated 2026-08-24) shows 17
  cycles (0–16), i.e. the Rtraj lags the float by ≥ 10 cycles and our raw
  snapshot (2026-08-19, cycles ≤ 13) sits between the two.
* 6990711 tech: 88 rows, cycles 1–3 + 99999-fill rows, last updated
  2025-03-24 (abandoned early).

## 7. Provenance finding: the GDAC files were NOT produced by the 076a chain

PROVEN from the references themselves:

1. **Cycle renumbering +1**: GDAC cycle = transmitted cycle + 1 on both
   floats (6990711 rows 2–8 = transmitted 1–7; 7902408 cycle 1 = the
   prelude/pre-launch sessions, cycles 2–6 = transmitted 1–5).  076a's
   `update_output_cycle_number_ir_sbd` is an identity; the 076a tech chain
   (Phase 4A) numbers cycles as transmitted.
2. **Date double-anchoring**: for every deep cycle, GDAC float-clock JULDs
   = calendar(items 5/6/7) **+ item8 days** + hhmm — e.g. 6990711 GDAC c3
   DST 27458.33194 = transmitted-c2 DST 27456.33194 + item8 = 2.000 exactly
   (same pattern, integer-exact, on 11 of 12 deep cycles of the two floats;
   offsets 0/2/12/21/31/41/51 = item8).  These dates are physically
   impossible (they post-date the mail that carried them).  The mechanism
   is a float-day + RTC mixed anchoring — legacy behaviour, absent from 076a.
3. **Legacy tech pipeline**: the GDAC tech.nc files use a 21-name Argos-era
   table (`CLOCK_StartDescentToPark_hours`, `NUMBER_*ArgosMessages_COUNT`,
   `FLAG_ProfileTermination_hex`…), not the 222/232 table of Phase 4A;
   7902408 tech contains prelude cycle-0 rows and 17 cycles.
4. Other legacy-only content: DET 200 / DDET 400 event rows; N_CYCLE and
   N_MEASUREMENT float-clock statuses written as '1' (076a writes '2'
   derived / '3' adjusted); TST 700 = FMT 702 = first mail time and
   TET 800 = LMT 704 (076a: TST ← transStartDate float time, TET ← next
   CST); GPS fixes replicated per cycle (6990711 GDAC c2 shows six 703
   rows where the raw holds one valid fix); `GROUNDED = 'Y'` on 7902408
   cycles 3/6 (raw: no grounding events — item 21 == 0, beached == 0);
   POSITION_QC 2/3 flags from an RTQC pass we do not run.

**Conclusion:** the public 076a toolbox is the only authoritative
implementation of this chain; the GDAC files for these exact floats come
from a different (legacy) production pipeline whose date anchoring is
provably wrong.  We implement 076a faithfully and treat GDAC as a
reference for LAYOUT (which it fixes exactly) and for the comparison
classifications of §8 — we do not reproduce physically-impossible dates.

## 8. Direct-comparison compatibility matrix

Validated empirically post-implementation (29/29 checks,
``scripts/validate_arvor_i_rtraj.py``; GDAC cycle = ours + 1):

| Aspect | Compatible? | Basis |
|---|---|---|
| File layout (dims/vars/attrs/dtypes, var order) | **YES — exact** | transcribed from references + c-writer |
| FMT 702 / LMT 704 values (mail times) | **YES — 24/24 rows exact** (14 + 10) | mail timestamps, absolute |
| Iridium mail-location 703 rows (lat/lon/juld) | **YES — 58/58 covered rows exact** (35 + 23) | the GDAC "GPS fixes" ARE the Iridium mail locations (§7.4) |
| GPS-fix 703 rows ('G') | NO — GDAC does not carry them (legacy wrote mail locations only) | §7.4 |
| Float-clock JULDs (DST/PST/PET/AST/AET/TET) | NO — legacy +item8 double-anchor (9 integer-day instances proven: 0/2/12/21/31/51; one non-integer instance where the legacy mapping itself is inconsistent on a stale cycle) | §7.2 |
| DET/DDET rows, status '1', TST/FMT=mail, TET=LMT, prelude cycle 1, cycle renumber +1 | NO — legacy-only | §7 |
| Cycle coverage 7902408 > 6 | NO — stale reference (DATA-COVERAGE) | §6 |
| Launch row (MC 0) position/date | position absent from our metadata (DATA-COVERAGE); our launch input 2025-03-02T05:16Z vs GDAC 2025-02-27T05:16 (metadata-input difference, ledgered) | §6 |

Additional chain details pinned during implementation:

* the emitter divides the seconds offset twice
  (``floatClockDriftSec = s/86400`` then ``floatClockDriftMin =
  round(that/60)/1440``), so the cycle-skeleton ``JULD_ADJUSTED`` equals
  ``JULD`` for any realistic offset while measurement bins get a true
  seconds adjustment; ``CLOCK_OFFSET`` stores the seconds offset
  expressed in days.  Both reproduced faithfully.
* ``finalize`` replaces the TET row via ``create_one_meas_float_time``:
  ``JULD = CST(N).juldAdj + prev-offset(days)``, ``JULD_ADJUSTED =
  CST(N).juldAdj`` (status '3').
* the MATLAB mail store carries ONE cycleNumber per mail; a mail whose
  payload spans two cycles (6990711 has one: cycles 5/6) is attributed
  to its first tagged cycle (INFERRED: the store is built from the
  mail's first packet).

## 9. Input audit (our model vs emitter needs)

Present: `CycleTimeData` (all fields + adjusted twins + offset),
`gps_records` + `jamstec_qc`, mail first/last times + Iridium CEP fields,
drift series (MC 290), profiles 'descent' (MC 190) / 'ascent_deep'
(MC 590) / 'ascent_shallow' = near-surface series (MC 710 — the
pres-cutoff split of Phase 3 mirrors the chain's near-surface split),
hydraulic packets in the stream buffers (Spy rows), Tech#1/Tech#2 (misc
rows, MC 599), clock-offset events.
Absent / inert: launch position (no MC 0 row unless supplied);
in-air series (no MC 711 rows — none in the raw); ice abort (none);
config USE table (CONFIG_MISSION_NUMBER stays fill — matches the GDAC
references' fill); adjusted params (none).

## 10. PROVEN / INFERRED / UNKNOWN

* PROVEN: §1–§5 chain semantics; §5 layout; §7 legacy findings (numeric
  evidence above); §9 availability.
* INFERRED: none used by the implementation (no row is emitted without a
  PROVEN 076a source).
* UNKNOWN: the legacy production pipeline's internal logic (not public);
  explicitly NOT reverse-engineered beyond the numeric proof in §7.
