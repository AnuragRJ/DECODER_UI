# ARVOR-I Phase 4A — `_tech.nc` Technical Mapping (investigation, pre-implementation)

**Date:** 2026-08-26 · **Status:** investigation complete, mapping fixed. No implementation yet.
**Scope:** ONLY the ARVOR-I `_tech.nc` product (user-fixed decision). `_prof.nc`, `_Rtraj.nc`,
metadata, and the **`_tech_aux.nc` file itself are NOT implementation targets** of Phase 4A
(aux rows are computed as intermediates and filtered at write time, exactly as the MATLAB
writer does; they are not written to any file in this phase).
**Inputs:** vendored Coriolis MATLAB (toolbox 20250516_076a, SEANOE DOI 10.17882/45589) under
`tests/data/arvor_i/coriolis_src/` + the same-version archive re-downloaded this session for the
five functions not previously vendored (see §1). All rows below PROVEN unless labelled.

---

## 1. Emitter inventory — CLOSED (dated correction to MIGRATION_NEW_CHAT_PHASE4A §8.3)

Actual driver chain for decIds {212, 214, 216–218, 221–231, 232} (i.e. our 222-family AND 232),
read end-to-end this session:

```
decode_provor.m  (transType 3, decId in {212,222,214,216,217,218,221,223..231,232})
 └─ decode_provor_iridium_sbd_delayed.m        ← the driver for our family (NOT decode_provor_iridium_sbd.m,
 │                                               which is the RT path with its own inline copies)
     ├─ per buffer, rankByCycle asc: process_decoded_data.m  case {222} (L1431) / case {232} (L3354)
     │    ├─ get_decoded_data.m case {212,222,231} / {214,217,223,225,232}:
     │    │    reset packet counters → clean_duplicates_in_received_data (keep first) → build
     │    │    tabTech1/tabTech2 rows "[packType item1 item2 ...]" → NKE grounding-day fix →
     │    │    first type-7 packet sets g_decArgo_7TypePacketReceivedCyNum
     │    ├─ cycle −1 buffer → early return (NO tech rows of any kind)
     │    └─ NetCDF branch, per buffer, in this order:
     │         store_received_packet_type_info_for_nc(decId, deep)   → 1001–1010 (ALL aux)
     │         store_tech1_data_for_nc_222_to_227_231_232(t1, deep)  → 100–136 / 10xxx
     │         store_tech2_data_for_nc_212_214_217_222_223_225_232(t2, deep) → 200–243 / 20x+10xxx
     │         store_misc_tech_data_for_nc_212_214_216_to_218_222_to_232    → 1012–1015 (ALL aux)
     │         → append to buffer table; globals reset per buffer
     ├─ update_output_cycle_number_ir_sbd.m  = IDENTITY (outputCycleNumber := cycleNumber; tech index untouched)
     └─ finalize_technical_data_ir_sbd.m     → 6-col index [-1 cyc -1 -1 paramId cyc];
          zero-fill missing statistical params 1001–1010 (all aux); SORT ALL ROWS by label-table
          position == alphabetical by TECHNICAL_PARAMETER_NAME (stable)
 └─ check_ice_algorithm_arvor.m             → NO-OP for both floats (gate: a type-7 packet was
 │                                            ever received — none in either dataset, verified on raw)
 └─ manage_erroneous_resetoffset.m          → NO-OP for both floats (gate: resetOffsetData with an
 │                                            untransmitted cycle; no resets in either dataset)
 └─ create_nc_tech_file.m (dispatcher) → create_nc_tech_file_3_1.m  (transType ∈ {2,3,4} → 3_1)
```

Functions NOT previously vendored, read this session from the re-downloaded 20250516_076a
archive (kept in /tmp only, not re-vendored — this doc records their behaviour):
`finalize_technical_data_ir_sbd.m`, `update_output_cycle_number_ir_sbd.m`, `create_nc_tech_file.m`,
`check_ice_algorithm_arvor.m`, `manage_erroneous_resetoffset.m`, `get_nc_tech_statistical_parameter_list.m`.

## 2. The TECH_AUX routing rule (biggest single finding)

`get_nc_tech_parameters_json.m` (L44–56): for every decoder NOT in (ApexApf11Iridium ∪ NkePfv2Iridium)
— i.e. ALL PROVOR/ARVOR decIds — every label-table entry is DUPLICATED at load time with
`id + 10000` and name `TECH_AUX_SURFACE_<NAME>` (or `TECH_AUX_` → `TECH_AUX_SURFACE_`).
In `create_nc_tech_file_3_1.m` (L49–77) every emitted row whose resolved label starts with
`TECH_AUX` is moved to the **aux** file, and rows starting `META_` are deleted. Neither reaches
`_tech.nc`.

For decIds 222/232 the label table (`_techParamNames/_tech_param_name_222.json` = `..._232.json`,
106 entries, identical) therefore routes to the AUX file (NOT `_tech.nc`):

* **1000** TECH_AUX_FLAG_GPSValidFix_LOGICAL (deep tech1, emitted between 131 and 132)
* **1001–1010** packet-type received counts (incl. deep-gated 1001–1004, type-7-gated 1010)
* **1012–1015** store_misc flags (ICE activated / deep / delayed / completed)
* **243** TECH_AUX_FLAG_FloatIceDetected_NUMBER (already aux-prefixed in the BASE table)
* **400–405, 408, 409** (check_ice_algorithm_arvor / manage_erroneous_resetoffset outputs; inert here)
* the whole +10000 "non-deep" emissions (10127–10136, 11000, 10227–10233, 10236–10242) → they
  resolve to the duplicated `TECH_AUX_SURFACE_*` labels → aux file. **The non-deep branch of
  store_tech1/store_tech2 can therefore NEVER write into `_tech.nc`.**
* statistical zero-fills 1001–1010 (finalize) → aux only, and all appended on ONE cycle
  (the last row's cycle), table-wide `setdiff`, as-coded.

`_tech.nc` rows for our family consequently come from EXACTLY TWO emitters:
**store_tech1 (deep) and store_tech2 (deep)** — params 100–136 (minus 1000) and 200–242 (minus 243),
plus — only for floats with ICE/reset anomalies — 406 `PRES_IceAvoidance_dbar` and
407 `FLAG_IceDetected_bit` from check_ice_algorithm_arvor (both inert for 6990711/7902408).

## 3. Item-indexing correction (dated correction to MIGRATION doc §8.2)

`decode_prv_data_ir_sbd_*.m` stores rows as `[packType, item1, item2, …]` (L149/L190), so
MATLAB `tabTechN(k + ID_OFFSET)`, `ID_OFFSET=1`, reads **item k** (col j = item j−1). The
migration doc's §8.2 store_**tech1** table already matches this. Its store_**tech2** table is
**off by one**: correct mapping is below, cross-verified three ways — (a) the code, (b) the label
table's independent `TECH_PARAM_MSG_ID` column, (c) Phase-1 PROVEN item semantics (items 3/4/5 =
expected descent/drift/ascent counts ↔ 200/201/202 NUMBER_Descent/Park/AscentIridiumPackets;
item 7 = in-air count ↔ 204 NUMBER_InAirIridiumPackets; item 59 ice flag ↔ 243).

NOTE: `TECH_PARAM_MSG_ID` follows the **manual (NKE 33-16-033) numbering**, which equals the
MATLAB item numbering up to item ~42 and is +4 above it (e.g. param 127: msg=43 ↔ item 47).
The code (MATLAB items) is authoritative for emission.

## 4. Mapping table — `_tech.nc` rows, ARVOR-I decIds 222-family/232

Sources per cycle: `ArvorCycle.tech1` / `.tech2` (StreamPackets; `fields[k]` == MATLAB item k),
buffer `deep` flag (`ArvorCycle.deep`), LAST Tech#1/Tech#2 in the buffer after Phase-3 dedup
(MATLAB rule: several Tech#1 in buffer → warn + use last — identical outcome, both take last).
Conversions use the same helpers as Phase 1 (`twos8/10`, `counts_to_pres/temp`, hhmm/mmss below).

**hhmm(x)** = `format_time_hhmm_dec_argo` (input decimal hours; negatives +24; seconds rounded;
carry at 60; **trailing "00" seconds dropped** → `HHMM` (4 ch) when s==0 else `HHMMSS` (6 ch)).
**mmss(x)** = `format_time_mmss_dec_argo` (input decimal hours; `MM:SS` with MM=total minutes;
negative → `"- MM:SS"` — sign, space, then digits, as-coded).

### 4.1 From Tech#1 (store_tech1_data_for_nc_222_to_227_231_232.m, read in full)

| Param | TECHNICAL_PARAMETER_NAME | Source (item) | Rule | Gate | Class |
|---|---|---|---|---|---|
| 100 | CLOCK_InitialValveActionDescentToPark_YYYYMMDD | 7,6,5 | `sprintf('%04d%02d%02d', i7+2000, i6, i5)` | always | PROVEN |
| 101 | …_FloatDay | 8 | raw | always | PROVEN |
| 102 | …_HHMM | 9 | hhmm(i9/60) | always | PROVEN |
| 103 | TIME_ValveActionsAtSurface_seconds | 10 | raw | always | PROVEN |
| 104 | NUMBER_ValveActionsAtSurfaceDuringDescent_COUNT | 11 | raw | always | PROVEN |
| 105 | FLAG_Beached_NUMBER | 12 | raw | always | PROVEN |
| 106–108 | CLOCK_StartDescentProfile / InitialStabilization… / EndDescentToPark _HHMM | 13/14/15 | hhmm(i/60) | deep | PROVEN |
| 109 | NUMBER_ValveActionsDuringDescentToPark_COUNT | 16 | raw | deep | PROVEN |
| 110 | NUMBER_PumpActionsDuringDescentToPark_COUNT | 17 | raw | deep | PROVEN |
| 111 | CLOCK_EndDescentToPark_DD | 20 | `sprintf('%02d', i20)` **string** | deep | PROVEN |
| 112/113 | NUMBER_DescentToParkEntriesInParkMargin / RepositionsDuringPark _COUNT | 21/22 | raw | deep | PROVEN |
| 114/115 | NUMBER_Valve/PumpActionsDuringPark_COUNT | 25/26 | raw | deep | PROVEN |
| 116/117 | CLOCK_Start/EndDescentToProfile_HHMM | 27/28 | hhmm(i/60) | deep | PROVEN |
| 118/119 | NUMBER_Valve/PumpActionsDuringDescentToProfile_COUNT | 29/30 | raw | deep | PROVEN |
| 120 | NUMBER_DescentToProfileEntriesInProfileMargin_COUNT | 32 | raw | deep | PROVEN |
| 121/122/123 | NUMBER_RepositionsAtProfileDepth / ValveActionsDuringProfileDrift / PumpActions… _COUNT | 33/34/35 | raw | deep | PROVEN |
| 124/125 | CLOCK_StartAscentToSurface / TransmissionStart _HHMM | 38/39 | hhmm(i/60) | deep | PROVEN |
| 126 | NUMBER_PumpActionsDuringAscentToSurface_COUNT | 40 | raw | deep | PROVEN |
| 127 | PRES_SurfaceOffsetCorrectedNotResetNegative_1cBarResolution_dbar | 47 | twos8(i47)/10 | deep | PROVEN |
| 128 | PRESSURE_InternalVacuumAtSurface_mbar | 48 | i48 × 5 | deep | PROVEN |
| 129 | VOLTAGE_BatteryPumpStartProfile_volts | 49 | 15 − i49/10 | deep | PROVEN |
| 130 | FLAG_RTCStatus_LOGICAL | 50 | **inverted**: i50==0 → 1 else 0 | deep | PROVEN |
| 131 | NUMBER_CTDError_COUNT | 51 | raw | deep | PROVEN |
| (1000) | (TECH_AUX_FLAG_GPSValidFix — aux, never in tech.nc) | 61 | raw | deep | PROVEN |
| 132/133/134 | TIME_IridiumGPSFix_seconds / TIME_PumpActionsAdditional…_seconds / FLAG_AntennaStatus_NUMBER | 62/64/65 | raw | deep | PROVEN |
| 135 | CLOCK_EOLStart_YYYYMMDDHHMMSS | 72,71,70,67,68,69 | `sprintf('%04d%02d%02d%02d%02d%02d', i72+2000, i71, i70, i67, i68, i69)` | deep **and i66==1** (deep gate is `==1`; non-deep gate is nonzero — divergence as-coded) | PROVEN |
| 136 | CLOCK_FloatTimeCorrection_MMSS | 73 | mmss(i73_signed/3600) | deep **and i61==1** | PROVEN |

Non-deep branch (surface cycles; → aux names 10127–10136/11000; **no surface cycles exist in
either dataset — every Tech#1/2-bearing buffer contains measurement packets → deep**): 10127–10136
same rules/gates as 127–136 (135 gate: i66 nonzero). Implemented for family completeness;
UNOBSERVED in evidence data.

### 4.2 From Tech#2 (store_tech2_data_for_nc_212_214_217_222_223_225_232.m, read in full)

| Param | TECHNICAL_PARAMETER_NAME | Source (item) | Rule | Gate | Class |
|---|---|---|---|---|---|
| 200–211 | NUMBER_Descent/Park/Ascent/NearSurface/InAirIridiumPackets + DescendingProfileReduction U/L + ParkCTDSamplesInternal + AscendingProfileReduction U/L + NearSurface/InAirSamples _COUNT | items 3–14 | raw passthrough (NOTE: raw items, NOT the corrected-expected-counts reinterpretation — §6 correction does not apply to emission) | deep | PROVEN |
| 212 | PRES_LastAscentPumpedRawSample_dbar | 15 (16,17 tested) | `counts_to_pres(i15)`; emitted only if any(pres,temp,psal)≠0 with temp=`counts_to_temp(i16)`, psal=i17/1000 | deep + condition | PROVEN |
| 213 | FLAG_Grounded_NUMBER | 21 | raw | deep | PROVEN |
| 214–217 | CLOCK_TimeGrounded_FloatDay / _HHMM / FLAG_FirstGroundingCyclePhase / NUMBER_ValveActionsForFirstGroundingDetection | 23/24/25/26 | 214 raw (**after grounding-day fix**, §5); 215 hhmm(i24/60) | i21>0 | PROVEN |
| 218–221 | (second grounding: same four) | 28/29/30/31 | 218 raw (**after fix**); 219 hhmm(i29/60) | i21>1 | PROVEN |
| 222 | NUMBER_EmergencyAscents_COUNT | 32 | raw | deep | PROVEN |
| 223–226 | CLOCK_TimeOfFirstEmergencyAscent_HHMM / PRES_FirstEmergencyAscent_dbar / NUMBER_PumpActionsOnFirstEmergencyAscent / CLOCK_…_FloatDay | 33/34/35/36 | 223 hhmm(i33/60); 224 `counts_to_pres(i34)` | i32>0 | PROVEN |
| 227–233 | FLAG_RemoteControl… / NUMBER_… / TIME_PreviousIridiumSession / NUMBER_IridiumMessagesReceived/SentPreviousSession | 37–43 | raw | deep | PROVEN |
| 234 | NUMBER_PumpActionsToStartAscent_COUNT | 44 | raw | deep | PROVEN |
| 235 | PRESSURE_InternalVacuumProfileStart_mbar | 45 | i45 × 5 | deep | PROVEN |
| 236 | CLOCK_LastReset_YYYYMMDDHHMMSS | 51,50,49,46,47,48 | `sprintf('%04d%02d%02d%02d%02d%02d', i51+2000, i50, i49, i46, i47, i48)` | deep | PROVEN |
| 237–242 | FLAG_InitialCheckError L/N / FLAG_InitialMemoryIntegrityCheck / FLAG_StatusBladderStateAtLaunch / FLAG_CTDStatus / FLAG_CTDErrorCyclePhase | 52–57 | raw | deep | PROVEN |
| (243) | (TECH_AUX_FLAG_FloatIceDetected — aux, never in tech.nc) | 59 | raw | type-7 ever received AND IC00≠0 — **INERT for both floats (no type-7 packets, PROVEN on raw)** | PROVEN |

Non-deep branch: 204 (i7), 211 (i14), then 10227–10233, 10236–10242 → aux names. UNOBSERVED here.

### 4.3 Emission order vs final file order

Per-buffer emission order (packet-type → tech1 → tech2 → misc) is **NOT** the final row order.
`finalize_technical_data_ir_sbd` sorts ALL rows by label-table position = alphabetical by
TECHNICAL_PARAMETER_NAME (stable). The writer (`create_nc_tech_file_3_1` L248–276) then iterates
output cycle number ascending (col 6 = buffer cycle number; `update_output_cycle_number_ir_sbd`
is identity) and, within a cycle, preserves table order. **Final order: cycles ascending; within
a cycle, rows alphabetically by TECHNICAL_PARAMETER_NAME** (tech1- and tech2-derived rows
interleaved alphabetically). Cycles with no rows (e.g. 7902408 cycle 13, and its cycle −1 buffer,
which returns before emission) simply contribute no rows — no fabrication.

## 5. Pre-emission transformations of items (get_decoded_data, per buffer)

1. `clean_duplicates_in_received_data` — byte-identical duplicate rows dropped, keep first
   (Phase 3 `_dedup_buffer` port — same behaviour; "LAST Tech#1/Tech#2" below refers to the
   last SURVIVING row).
2. **NKE grounding-day fix** (get_decoded_data L166–184): if `item21 > 0` and `item25 == 2`
   then `item23 −= item8_of_FIRST_Tech#1_in_buffer`; if `item21 > 1` and `item31 == 2` then
   `item28 −= item8(first Tech#1)`. (Phase-2 grounding semantics: phase 2 reports absolute
   float-day, others relative.) Applied BEFORE store_tech2 → affects params 214/218 only.
3. decode_prv_data in-place conversions (Phase 1 already models these): item47 twos8/10;
   item73 twos16 signed (136 formats the SIGNED seconds); item15/34 via sensor conversions
   at emission time (212/224).

## 6. Writer layout — `create_nc_tech_file_3_1.m` (read in full; authoritative ARVOR dims)

* Dimensions: `DATE_TIME=14`, `STRING128`, `STRING32`, `STRING8`, `STRING4`, `STRING2`,
  `N_TECH_PARAM` = UNLIMITED. No `N_TECH_MEASUREMENT` section for our family (tabTechNMeas
  is passed `[]` by decode_provor for SBD floats).
* TECHNICAL_PARAMETER_NAME / _VALUE: NC_CHAR dims (N_TECH_PARAM, STRING128) — MATLAB
  `defVar(..., fliplr([nTechParam string128]))` = STRING128 fastest-varying, matching the
  APEX GDAC reference files already proven in this repo.
* CYCLE_NUMBER: NC_INT, `_FillValue 99999`, conventions
  `"0...N, 0 : launch cycle (if exists), 1 : first complete cycle"`.
* Values: strings (100, 111, 135, 236, all hhmm/mmss outputs) stored as-is; numerics via
  MATLAB `num2str` — repo convention proven against GDAC APEX outputs of this same toolbox:
  integer-valued → `str(int(v))`, else `%g` (`nc/technical.py::_format_number`).
* Header variables: PLATFORM_NUMBER = WMO; DATA_TYPE = `"Argo technical data"`;
  FORMAT_VERSION = `"3.1"`; HANDBOOK_VERSION = `"1.2"`; DATA_CENTRE from float meta JSON
  (fallback `" "`); DATE_CREATION (preserved on re-run) / DATE_UPDATE = now UTC `yyyymmddHHMMSS`.
* Global attributes: title `"Argo float technical data file"`, institution ←
  `get_institution_from_data_centre(DATA_CENTRE)`, source `"Argo float"`, history
  `"<T> creation; <T> last update (coriolis float real time data processing)"`, references
  `http://www.argodatamgt.org/Documentation`, user_manual_version `"3.1"`,
  Conventions `"Argo-3.1 CF-1.6"`, decoder_version `"CODA_076a"` (init_default_values L516),
  id `"https://doi.org/10.17882/42182"`.

## 7. Dataset-specific expectations (both floats, to be asserted in validation)

* **6990711** (decId 222): 7 buffers, ALL deep (contain measurements — Phase 2 PROVEN; dated
  correction of migration §8.5 which expected non-deep) → cycles 1–7 each emit the full
  100–136 (minus 1000; 135 absent — no EOL flags, item66=0 on all 21 Tech#1 of both floats;
  136 only on cycles with item61==1) + 200–242 conditional set. No type-5/7 packets →
  7TypePacketReceived empty → ICE paths inert. No resets → reset paths inert.
* **7902408** (decId 232): emitted buffers incl. incomplete ones (2,3,5,6,7,8,10,11) each emit
  rows from their LAST Tech#1/Tech#2; **cycle 13 emits NO tech rows** (no Tech#1/Tech#2 — and
  its misc/aux rows are aux-only anyway); cycle −1 (pre-launch param buffer) emits nothing
  (early return before the store block); cycles 14/15 pending (go=0, not emitted — Phase 2).
  No type-7 packets (PROVEN on raw this session: histograms {T1:19, CTD:101, T2:19, P1:7,
  HYD:38}) → ICE paths inert despite Param#1-derived config presence.
* Both: multiple identical Tech#1/Tech#2 → last-after-dedup (MATLAB warn+last ≡ same row).
  **Interface note (validated this session):** `ArvorCycle.tech1/.tech2` hold the FIRST
  Tech#1/Tech#2 of the buffer (`arvor_i_science.py` `t1s[0]`), while the MATLAB emitters use the
  LAST. On both evidence floats every buffer carries exactly one Tech#1 and one Tech#2 after
  Phase-3 dedup, so first == last here; the Phase-4A builder will select the LAST from
  `ArvorCycle.buffer` packets itself (no Phase-3 change, no interface break).
  Also note `res.cycles` excludes the cycle −1 param-only buffer (it is in `param_only_cycles`),
  matching the MATLAB early-return: no tech rows for cycle −1 either way.
* GDAC comparison: DATA-COVERAGE-limited (no PROVOR/ARVOR GDAC `_tech.nc` in workspace — §8.1
  of migration doc); layout parity via `nc/admt.py` conventions already proven on APEX refs;
  values validated against raw `fields` by hand-decode spot checks.

### 7.1 Live-data validation of this mapping (run 2026-08-26, Phase-3 API, read-only)

Decoded both floats via `reconstruct_science` and inspected every cycle's LAST Tech#1/Tech#2:

* **6990711** — 7 cycles, ALL `deep=1`, each with exactly 1 Tech#1 + 1 Tech#2.
  `item66=0` on all cycles → param **135 absent everywhere**. `item61=1` on c1–c4, c7 →
  **136 present on those 5 only** (c5/c6 stale-GPS cycles have item61=0). `item21=0`
  (no grounding) → **214–221 absent**; `item32=0` → **223–226 absent**; sub-surface triplet
  non-zero on all cycles (e.g. (55588, 654, 33652)) → **212 present on all 7**.
  → expected row count: 7 × (35 tech1 + 31 tech2) + 5 × 1 (param 136) = **467 rows**.
* **7902408** — 13 cycles reconstructed; c1–c12 ALL have Tech#1+Tech#2 and `deep=1`
  (incomplete cycles included — completion does NOT gate tech emission); **c13 has neither →
  no rows**; `item61=1` on all 12 → 136 present on all; item21=0, item32=0, sub≠0 as above;
  `item66=0` → no 135.
  → expected row count: 12 × 66 + 12 × 1 = **804 rows**.
* Both floats: no type-5 (6990711) / no type-7 (both) → all ICE/aux gates inert, as derived.

## 8. Open items for implementation (Step 4+)

1. Writer placement per migration §8.6: new `platforms/provor_ir_sbd/arvor_i_tech.py` (product
   model: per-cycle records (param_id, name, value_str, cycle) with the table above as its
   docstring) + ARVOR branch in a new `nc/technical_arvor.py` reusing `nc/admt.py`
   (`write_admt_dataset`), APEX `nc/technical.py` untouched.
2. Row filtering mirrors the MATLAB writer: build ALL rows (incl. aux-destined ones), then drop
   `TECH_AUX*`/`META_*` at write time; record dropped counts in notes (no silent data loss).
3. FileChecker jar still absent from workspace (§8.4) — ask user or classify the gap.
4. mypy not configured in Phase 1–3 → do not add (check pyproject at implementation time).
