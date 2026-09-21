# ARVOR-I Tech / Rtraj / Meta — Exhaustive Bidirectional Parameter Inventory vs INCOIS GDAC

**Date:** 2026-09-07 (Prompt 12; consolidated post-parity state in §0 after Tech + Rtraj Phase 2. Supersedes the 2026-09-05 parity report, whose parity tables remain valid below the inventory)
**Method:** raw telemetry → Coriolis-equivalent decoding → our output; GDAC = publication comparison target, **not** an authority to copy. Evidence: vendored Coriolis MATLAB (`tests/data/arvor_i/coriolis_src/`), the four CSVs (`config/metadata/`), raw .eml telemetry, GDAC refs. No registry.csv used. Mono untouched (verified: 69-file residual inventory byte-identical before/after).

---

## 0. Post-parity consolidated state (2026-09-07, after Tech Phase 2 + Rtraj Phase 2)

*This section supersedes the operational conclusions of §1–§5 below (the Prompt-12 inventories remain the evidence base). Full detail: `TECH_PUBLICATION_PARITY_PHASE2.md`, `RTRAJ_PUBLICATION_PARITY_PHASE1.md`, `RTRAJ_PUBLICATION_PARITY_PHASE2.md`.*

**Both projected products now publish exactly the GDAC set, with values naturally derived from raw telemetry through the decoder (nothing copied, nothing hardcoded per WMO/cycle); the full Coriolis 076a decode is retained internally and projected only at the publication layer.**

### TECH — closed (Prompt 14)
- Published = GDAC's exact 21-name / fixed 22-slot-per-cycle structure (order, duplicate vacuum slot, 3 blank placeholders) for the whole ARVOR-I family via one generic slot table; internal 71-name decode retained.
- Parity ×4 floats, all overlapping cycles: **958/968 slot cells string-identical, 0 order mismatches**; the 10 residuals are exactly the SurfaceOffset cells (GDAC publishes raw counts = ours×10 under a `_dbar` name — sanctioned divergence, correct dbar value kept).
- HHMM→decimal-hours with GDAC's formatting rule; FloatTime h/m/s from decoded items 41–46; pre-mission block not fabricated (DATA-COVERAGE). Validators: tech-GDAC 32/32, tech-4A 56/56.
- Supersedes §1b/§1c operationally: the 16 "GDAC-only" names are now all published (renames/transforms at the projection); the 66 "ours-only" names are now internal-only.

### RTRAJ — closed (Prompt 16)
- Published = GDAC's exact 13-family set in canonical block order `100,200,250,300,400,500,600,700,702,703×N,704,800` + launch row; transmitted cycle numbering kept (GDAC's +1 proven a legacy production artifact); DSI `'2B  '` at the publication layer.
- **200 ← PST 250, 400 ← AST 500** synthesized twins (Phase-1 proof: GDAC 200 ≡ 250 exactly on every cycle of all 4 floats; 400 ≈ 500); GPS-'G' 703 row internal-only; positions on 600/700/702/704/800 from proven derivations (600 = arc-minute-truncated cycle GPS fix — exact; 700/702 = first 703; 704/800 = last 703). Supersedes §2a's "200/400 not emitted → PUBLICATION" and §2c's DSI row.
- Values on the 34 clean cycle pairs: **FMT/LMT exact ×34; 703 fix sets equal per pair**; positioned events match GDAC exactly where telemetry exists; every float-clock delta classified (integer-day +item8 anchors, quantified non-integer anchors, 92 DATA-COVERAGE fills — no Param#1 mission-config packet in the raw of 1902844/2904082/6990711, which also refines §4.7's PET/AST/AET entry).
- GDAC-reference contamination proven (cycles 1 & 14–77 byte-identical across the two 2026 floats' files — foreign southern-ocean trajectory, 2024–2026): NOT FIXABLE, excluded from comparison, never reproduced. Validators: rtraj-GDAC 56/56, rtraj-4B 64/64.

### META — unchanged, decisions pending
65=65 vars, 58 exact (§3 stands). Open fix candidates awaiting user direction: `POSITIONING_SYSTEM` 'IRIDIUM' vs 'GPS' (would need a positioning column in the four-CSV set), `START_DATE` anchor (UNKNOWN — no single rule across floats), TRANS_* placeholders (EXPECTED).

### Current verification battery
Mono untouched (69-file residual inventory identical) · validators **32/56/108/64/56** (tech-GDAC / tech-4A / meta / rtraj-4B / rtraj-GDAC) · full pytest **2082** · ruff check+format clean · APEX A/B **IDENTICAL** · fleet pipeline ok ×4 · products regenerated in `validation_arvor_i_products/`.

---

## 1. TECH — bidirectional inventory

**Name sets** (union across 4 floats): ours 71 names, GDAC 21, shared 5.

### 1a. Shared (5) — value-exact
`NUMBER_{PumpActionsDuringAscentToSurface, PumpActionsDuringDescentToPark, RepositionsDuringPark, ValveActionsAtSurfaceDuringDescent, ValveActionsDuringDescentToPark}_COUNT` — all Coriolis-canonical (222 table); **75/70/15/60 cells exact, 0 mismatches** in overlapping cycles.

### 1b. GDAC-only (16) — every name resolved

| GDAC name | Resolution | Relationship (verified) | Coriolis? | Class |
|---|---|---|---|---|
| CLOCK_EndDescentToPark_hours | rename+format of ours `CLOCK_EndDescentToPark_HHMM` (item 118) | GDAC = HH+MM/60 of our HHMM; **15/14/3/12 cycles exact** | ours canonical | EXPECTED |
| CLOCK_StartDescentToPark_hours | = ours `CLOCK_StartDescentProfile_HHMM` (item 115) | same conversion; exact ×4 floats | ours canonical | EXPECTED |
| CLOCK_InitialStabilizationDuringDescentToPark_hours | = ours item 116 HHMM | same conversion; exact | ours canonical | EXPECTED |
| CLOCK_EndAscentToSurface_hours | = ours `CLOCK_TransmissionStart_HHMM` (item 127) | same conversion; exact | ours canonical | EXPECTED |
| NUMBER_AscentArgosMessages_COUNT | = ours `NUMBER_AscentIridiumPackets_COUNT` | identity; exact | ours canonical; "Argos" naming on an Iridium float | PUBLICATION rename |
| NUMBER_ParkArgosMessages_COUNT | = ours `NUMBER_ParkIridiumPackets_COUNT` | identity; exact | 〃 | PUBLICATION rename |
| NUMBER_ParkSamples_COUNT | = ours `NUMBER_ParkCTDSamplesInternal_COUNT` | identity; exact | ours canonical | PUBLICATION rename |
| VOLTAGE_BatteryInitialAtProfileDepth_volts | = ours `VOLTAGE_BatteryPumpStartProfile_volts` (item 129, 15−i/10 V) | identity; exact | ours canonical | PUBLICATION rename |
| PRES_SurfaceOffsetNotTruncated_dbar | = ours `PRES_SurfaceOffset…1cBarResolution_dbar` (item 127, twos8/10) | **GDAC = ours × 10** on every nonzero cell (2.0 vs 0.2, 3.0 vs 0.3, 5.0 vs 0.5); ours = raw×0.1 dbar (1 cbar = 0.1 dbar, per decode table `twos8/10`); GDAC publishes the raw count under a `_dbar` label | ours canonical name **and** value | PUBLICATION — GDAC unit error; ours scientifically correct |
| PRESSURE_InternalVacuum_inHg | = ours `PRESSURE_InternalVacuumAtSurface_mbar` (item 128, ×5 mbar) | identity 15/14/3/12; values 620–640 = **mbar** (inHg would be ≈18–19); GDAC's 2nd per-cycle row blank (drops item 235 ProfileStart) | ours canonical | PUBLICATION rename + unit mislabel |
| CLOCK_FloatTime_hours / _minutes / _seconds (3) | = our `ArvorTech1Packet.float_time` h/m/s | verified **to the second**, 5/5 sampled cycles (c1 14:01:53 … c5 17:54:22); we decode it and publish via Rtraj clock rows | decoded by our chain (`float_time`, used by clock-offset logic) | EXPECTED — same value, split presentation |
| FLAG_ProfileTermination_hex, NUMBER_AscentSamples_COUNT, NUMBER_PumpActionsAtSurface_COUNT | **all-blank columns** in GDAC (`''` × 77 rows each) | nothing to derive; no Coriolis table entry | absent from 222 table | PUBLICATION placeholders |

### 1c. Ours-only (66) — all Coriolis-canonical
Every name is present in the vendored `_tech_param_name_222.csv` decoder table (item ids 100–242), incl. `TIME_PumpActionsAdditionalAtSurfaceForGPSAcquisition_seconds` (item 133/60 — its CSV row has a trailing space, first pass missed it). They are the full Coriolis tech decode; GDAC publishes a reduced/renamed subset → **EXPECTED** (richer, canonical).

**Tech conclusion:** zero genuine decoder gaps; zero unexplained GDAC names.

---

## 2. RTRAJ — bidirectional inventory

**Variables: 102 = 102 identical** (names, dtypes, dims, per-variable attrs) on all four floats. Globals differ only `history` (run stamp) and `institution` (ours INCOIS vs GDAC 'CSIRO' — a GDAC artifact on INCOIS files → PUBLICATION).

### 2a. Event (MEASUREMENT_CODE) families

| Family | Ours | GDAC | Verdict |
|---|---|---|---|
| Base phases 100 DST, 250 PST, 300 PET, 500 AST, 600 AET, 700 TST, 800 TET | emitted | emitted | see values below |
| 702 FMT / 704 LMT / 703 surface | emitted | emitted | **exact** (24/24, 14/14, 10/10, 48/48, 35/35, 23/23 rows; validated) |
| **0 LAUNCH** | **now emitted** (this prompt's fix) | emitted | **exact ×4 floats**: ours (csv4 lat/long + launch JULD) == GDAC to 1e-6 (e.g. 27773.5625 / 11.00 / 66.87) |
| 200 DET, 400 DDET | not emitted | emitted | **not in the Coriolis 222-family order list** (`get_mc_order_list.m` case {210…232}; DET/DDET belong to other decoder families). GDAC's values mostly match nothing in our chain (1/22 and 0–1/22 JULD identities; its first 200 duplicates our PST=250 instant) → PUBLICATION (INQC-generic events) |
| Coriolis diagnostics: 89 CycleStart, 150 FST, 189/190/198/203 descent family, 289/290/297/298 park family, 301 RPP, 389/398, 450 DPST, 489, 497/498, 503, 589/590/599 ascent family, 710 InWater, 901 Grounded | emitted (subset per telemetry) | absent | every code is in the Coriolis family list (`get_mc_order_list.m`) → **EXPECTED** (canonical decoder output GDAC drops) |
| 711 InAir | absent | absent | no in-air sampling in raw → DATA-COVERAGE |

### 2b. Value comparison on shared clock codes
- **MC 100/250** (+1 cycle map): GDAC carries the documented legacy **+item8 integer-day double-anchor** (shifts 1/11/21/31 d; mapping-report §7.2) → NOT reproduced (no Coriolis/raw support), classified as before.
- **MC 700 TST**: GDAC−ours = +92…+241 s (mail-anchor vs decode-anchor choice); **MC 800 TET**: −2…+64 s → EXPECTED (both anchors defensible; ours telemetry-derived).
- **MC 300/500/600 (PET/AST/AET)**: ours real where the engine transmits the clock items — 7902408: 12/15 cycles real; 1902844 & 6990711: fill (items absent from telemetry) → DATA-COVERAGE. GDAC's stand-in 200/400 rows are the PUBLICATION events above.

### 2c. Fields
- `CONFIG_MISSION_NUMBER`: ours 1 (launch mission; = GDAC's own meta/mono) vs GDAC Rtraj 0 → PUBLICATION (GDAC self-inconsistent; not replicated).
- `DATA_STATE_INDICATOR`: ours '' vs GDAC '2B' → PUBLICATION (DAC-side data-state stamp).
- `POSITION_QC`/param QC: ours blank vs GDAC RTQC '1's → TOOL-AVAILABILITY (RTQC pass out of trajectory-product scope, unchanged).

---

## 3. META — bidirectional inventory

**Variables: 65 = 65 identical** (pipeline product, csv4-materialized). Values: **58/65 exact** — incl. PI_NAME, PROJECT_NAME, PLATFORM_*, FLOAT_SERIAL_NO, WMO_INST_TYPE, DATA_CENTRE, CONFIG_MISSION_NUMBER, the full SENSOR/PREDEPLOYMENT_CALIB/CONFIG blocks, LAUNCH_DATE/QC, POSITIONING dates. GDAC values for these are exactly what the four CSVs produce (derivation demonstrated by the csv4 materialization).

| Field | Ours | GDAC | Trace / derivation | Class |
|---|---|---|---|---|
| CONTROLLER_BOARD_TYPE_PRIMARY | 'APF0' | 'n/a' | ours derived from meta.csv controller-serial prefix (loader rule); GDAC placeholder | EXPECTED |
| POSITIONING_SYSTEM | 'IRIDIUM' | 'GPS' | ours = csv4 Comms system (no positioning column exists in any CSV); GDAC = its update_meta_data GPS rule; telemetry could arbitrate (mono per-cycle source GPS-dominant) | FIX CANDIDATE (semantics choice; no CSV source) |
| START_DATE | '' | per-float stamp | 6990711 = launch exactly; 1902844 ≈ first transmission (Δ≈12 s from GDAC c1 LMT); 7902408 = neither (12:08 vs launch 17:44) — **no single anchor rule** | UNKNOWN (partially derivable) |
| TRANS_FREQUENCY | '' | 'n/a' | Argos-only field; Iridium float | EXPECTED (placeholder token) |
| TRANS_SYSTEM_ID | sheet transceiver id | 'n/a' | ours carries the csv4 value; GDAC Argos-oriented placeholder | EXPECTED |
| DATE_CREATION / DATE_UPDATE | run stamps | GDAC stamps | — | EXPECTED |

---

## 4. Nine-category summary

1. **Exact & value-exact:** tech — 5 shared names (205 cells, 0 mismatch) + 9 renamed pairs (all overlap cycles, 4 floats); rtraj — 102 vars, FMT/LMT/703 rows, launch row (new); meta — 58/65 vars.
2. **Ours-only:** tech 66 names (all Coriolis-canonical, item ids 100–242); rtraj 24 diagnostic MC codes (all in the Coriolis family order list); meta 0.
3. **GDAC-only:** tech 16 names — all resolved (renames / presentation / blanks / unit errors); rtraj MC 200/400 (INQC-generic, non-canonical for family 222/232); meta 0.
4. **Equivalent-but-renamed (10 pairs):** the 4 HHMM→hours clocks, Ascent/Park messages (Argos→Iridium), ParkSamples, Battery, InternalVacuum (+SurfaceOffset under 5).
5. **Equivalent-but-unit-converted:** HHMM→decimal hours (exact); PRES_SurfaceOffset **GDAC = ours×10** (GDAC publishes raw counts as dbar; ours applies the Coriolis twos8/10 cbar→dbar scale); InternalVacuum label-only mislabel (values mbar-identical).
6. **Publication-only:** blank tech columns (FLAG_ProfileTermination_hex, AscentSamples, PumpActionsAtSurface); DET/DDET rows; DATA_STATE_INDICATOR '2B'; GDAC Rtraj CMN 0; 'CSIRO' institution; +item8 legacy clock anchor; TST/TET anchor choice.
7. **Data-coverage:** PET/AST/AET fill JULDs on 1902844/6990711 (clock items not transmitted); InAir 711; GDAC merged/stale reference histories; 7902408's GDAC-only 16th profile; 6990711 config Param#1 absence.
8. **Genuine implementation gaps:** **one — the Rtraj launch row (MC 0)**. The builder path existed (`add_launch_data_ir_sbd` semantics) but was never fed: Prompt-4B's "no launch position in metadata" is refuted by meta.csv `lat`/`long`. **Implemented this prompt** (csv4 lat/long + launch JULD → `_launch_position` in the decoder): matches GDAC exactly on all four floats. Complete comparison rerun after the change.
9. **Unresolved UNKNOWNs:** meta START_DATE anchor (inconsistent across floats). (Mono-scope residuals — JULD ≈8 s family, 4 GDAC position cells — remain as classified in the Mono report; untouched by scope rule.)

## 5. Verification (after the one justified change)

- Mono untouched: 69-file parity residual inventory **identical** before/after (20 classes).
- Validators: tech-GDAC **20/20**, tech **54/54**, meta **108/108**, rtraj **64/64** (now incl. launch-row == GDAC checks) — all four floats.
- Full pytest **2068 passed**; ruff check + format clean; APEX A/B non-regression **IDENTICAL** (78 fingerprints; change was platform-scoped, no shared code touched).
- Artifacts: `validation_arvor_i_products/` (12 regenerated pipeline products), `validation_arvor_i_products/inventory/tech_cells.json` (raw cell inventory), fleet runner report unchanged.

*The 2026-09-05 parity tables (§1–§5 of the previous report) remain accurate except: Rtraj validator count 60→64 (launch-row checks added), the MC 0 classification moves from DATA-COVERAGE to derived-and-matching, and the tech name inventory is superseded by the resolved table above.*
