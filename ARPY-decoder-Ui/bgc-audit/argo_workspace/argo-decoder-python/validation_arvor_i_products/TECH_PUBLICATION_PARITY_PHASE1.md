# Tech.nc GDAC Publication-Parameter Parity — Phase 1 (Mapping & Plan)

**Date:** 2026-09-07 · **Status:** investigation complete, **no code changed** (per instruction).
**Target:** published `<wmo>_tech.nc` contains **exactly** the GDAC ARVOR-I parameter set — no ours-only names, no GDAC-only names — with values **naturally derived** (no hardcoding/copying). Decoder internals are not deleted; decoding is separated from publication.
**Scope guard:** Mono / Rtraj / Meta untouched. GEBCO/Test-4 untouched.

---

## 0. GDAC publication shape (measured, all 4 refs)

- **21 unique names, 22 rows per cycle, fixed order** (captured from cycle 1 of 1902844, identical on all floats):

| idx | name | idx | name |
|---|---|---|---|
| 0 | VOLTAGE_BatteryInitialAtProfileDepth_volts | 11 | CLOCK_EndAscentToSurface_hours |
| 1 | PRESSURE_InternalVacuum_inHg | 12 | NUMBER_PumpActionsAtSurface_COUNT |
| 2 | FLAG_ProfileTermination_hex | 13 | CLOCK_FloatTime_hours |
| 3 | CLOCK_StartDescentToPark_hours | 14 | CLOCK_FloatTime_minutes |
| 4 | NUMBER_ValveActionsAtSurfaceDuringDescent_COUNT | 15 | CLOCK_FloatTime_seconds |
| 5 | CLOCK_InitialStabilizationDuringDescentToPark_hours | 16 | PRES_SurfaceOffsetNotTruncated_dbar |
| 6 | NUMBER_ValveActionsDuringDescentToPark_COUNT | 17 | PRESSURE_InternalVacuum_inHg *(2nd slot — blank in GDAC)* |
| 7 | NUMBER_PumpActionsDuringDescentToPark_COUNT | 18 | NUMBER_AscentArgosMessages_COUNT |
| 8 | CLOCK_EndDescentToPark_hours | 19 | NUMBER_AscentSamples_COUNT |
| 9 | NUMBER_RepositionsDuringPark_COUNT | 20 | NUMBER_ParkArgosMessages_COUNT |
| 10 | NUMBER_PumpActionsDuringAscentToSurface_COUNT | 21 | NUMBER_ParkSamples_COUNT |

- Values stored as **text** (our writer already uses NC_CHAR/STRING128 — same class; blank = `''`).
- 3 columns **all-blank** in every GDAC file: idx 2, 12, 19. Slot 17 blank everywhere.
- GDAC also publishes a **pre-mission block** (cycle 0 on 1902844/2904082/7902408, CYCLE_NUMBER=99999 on 6990711; 18/22 fields filled). Our raw has **no such buffer** (no cycles ≤ 0, no pre-launch mails) → **DATA-COVERAGE**; also resolves Prompt-12's meta START_DATE UNKNOWN (GDAC START_DATE = the pre-mission dump's float-time date — e.g. 7902408 12:08:16 — unavailable to us).
- GDAC cycles extend beyond our raw window on the merged/stale refs (coverage, unchanged).

## 1. Complete 21-parameter mapping table

Categories: **(1)** rename of existing decoded param · **(2)** unit conversion · **(3)** different formatting · **(4)** genuinely missing from our Tech output · **(5)** publication-specific (deliberate mapping).

| # | GDAC name | Raw telemetry | Coriolis logic | Our source (spec id → module) | Value relation (verified) | Cat |
|---|---|---|---|---|---|---|
| 1 | VOLTAGE_BatteryInitialAtProfileDepth_volts | Tech#1 item 49 | `15-i/10` volts | spec **129** `VOLTAGE_BatteryPumpStartProfile_volts` (arvor_i_tech) | **identity**, exact every overlap cycle (4 floats) | 1 |
| 2 | PRESSURE_InternalVacuum_inHg (slot 1) | T1 item 48 | `x5` mbar | spec **128** `PRESSURE_InternalVacuumAtSurface_mbar` | **identity** (620–640 = mbar; GDAC label “inHg” wrong) | 1 (+GDAC unit-label error) |
| 2b | 〃 (slot 17) | T1/T2 item 235 | mbar | spec **235** `PRESSURE_InternalVacuumProfileStart_mbar` | GDAC **blank**; ours derives a value (625) → decision D2 | 5 |
| 3 | FLAG_ProfileTermination_hex | — none | not in `_tech_param_name_222` | — | GDAC blank ×all rows; publish blank row | 5 |
| 4 | CLOCK_StartDescentToPark_hours | T1 item 13 | `hhmm` | spec **106** `CLOCK_StartDescentProfile_HHMM` | `GDAC = HH + MM/60`; exact (15/14/3/12 cycles × 4 clocks) | 3 |
| 5 | NUMBER_ValveActionsAtSurfaceDuringDescent_COUNT | T1 item 11 | raw | spec **104**, same name | identity (shared name) | — |
| 6 | CLOCK_InitialStabilizationDuringDescentToPark_hours | T1 item 14 | `hhmm` | spec **107** `…_HHMM` | `HH + MM/60`, exact | 3 |
| 7 | NUMBER_ValveActionsDuringDescentToPark_COUNT | T1 item 16 | raw | spec **109**, same name | identity | — |
| 8 | NUMBER_PumpActionsDuringDescentToPark_COUNT | T1 item 17 | raw | spec **110**, same name | identity | — |
| 9 | CLOCK_EndDescentToPark_hours | T1 item 15 | `hhmm` | spec **108** `…_HHMM` | `HH + MM/60`, exact | 3 |
| 10 | NUMBER_RepositionsDuringPark_COUNT | T1 item 22 | raw | spec **113**, same name | identity | — |
| 11 | NUMBER_PumpActionsDuringAscentToSurface_COUNT | T1 item 40 | raw | spec **126**, same name | identity | — |
| 12 | CLOCK_EndAscentToSurface_hours | T1 item 39 | `hhmm` | spec **125** `CLOCK_TransmissionStart_HHMM` | `HH + MM/60`, exact | 3 |
| 13 | NUMBER_PumpActionsAtSurface_COUNT | — none (canonical item 133 is a *duration*, not a count) | not in table | — | GDAC blank; publish blank row | 5 |
| 14–16 | CLOCK_FloatTime_hours / _minutes / _seconds | **T1 items 41–46** (HHMMSSddmmyy) | float-time parse | `ArvorTech1Packet.float_time` (arvor_i.py:315) — **decoded today, not published as tech rows** | components match GDAC **to the second** (5/5 cycles; c0 blocks GDAC-only) | **4** |
| 17 | PRES_SurfaceOffsetNotTruncated_dbar | T1 item 47 | `twos8/10` → dbar | spec **127** `PRES_SurfaceOffset…1cBarResolution_dbar` | **GDAC = ours × 10** on 44/44 cells incl. all 10 nonzero (GDAC publishes the raw centibar **count** under a `_dbar` name — unit error) → decision D1 | 2 (GDAC-side error) |
| 18 | NUMBER_AscentArgosMessages_COUNT | Tech#2 item 202 | raw | spec **202** `NUMBER_AscentIridiumPackets_COUNT` | identity, exact | 1 |
| 19 | NUMBER_AscentSamples_COUNT | — none mapped (canonical candidates 208/209/520 exist) | not in table | — | GDAC blank; publish blank row | 5 |
| 20 | NUMBER_ParkArgosMessages_COUNT | T2 item 201 | raw | spec **201** `NUMBER_ParkIridiumPackets_COUNT` | identity, exact | 1 |
| 21 | NUMBER_ParkSamples_COUNT | T2 item 207 | raw | spec **207** `NUMBER_ParkCTDSamplesInternal_COUNT` | identity, exact | 1 |

Verification basis: cell-level comparison across all overlapping cycles of all four floats (Prompt-12 inventory `inventory/tech_cells.json` + this phase's ×10/blank/order audits). "Exact" = equality on every comparable cell (tolerance 1e-6 for derived hours; string-equal storage).

## 2. Conversion formulas (exact)

- **HHMM → decimal hours:** `hours = floor(HHMM/100) + (HHMM mod 100)/60`. GDAC text formatting = 4 decimals, trailing zeros trimmed (`20.7167`, `3.85`, `0.15`). Verified bit-consistent on every overlap cycle of every float for all four clocks.
- **SurfaceOffset:** ours = `raw_item47 / 10` dbar (1 cbar = 0.1 dbar; Coriolis `twos8/10`). GDAC's number = `raw` (centibar count) → `gdac = 10 × ours`, 44/44 cells. **Ours is the physically correct dbar value.**
- **Battery:** both `15-i/10` V — identical by construction.
- **Vacuum:** both item 48 `×5` mbar — identical; GDAC's `_inHg` label is a mislabel (values 620–640 mbar ≈ 18.4–19.0 inHg if converted — GDAC did not convert).
- **FloatTime:** `hours = float_time.hour`, `minutes = .minute`, `seconds = .second` (ints) — no conversion freedom; matched to the second.

## 3. Ours-only parameters (66) — publication removal list

**All 66 leave the published file; none are removed from the decoder.** `ArvorTechDataset.tech_rows` keeps the full Coriolis-canonical set (item ids 100–242) because:
- **No other product consumes them** (grep-proven: `tech_rows` referenced only by the tech writer and tech tooling; Rtraj/Meta/Mono consume the science result / packet objects directly).
- The Phase-4A validator (54/54) and audit tooling validate the canonical decode — they move to (or keep targeting) the **internal model**, not the published file.
- They remain the scientifically complete Coriolis decode (GDAC publishes a reduced/renamed subset).

## 4. Genuinely missing implementation work

1. **FloatTime rows (3 params)** — the only true decode gap in the *publication*: value already decoded (`float_time`), needs 3 row emissions per cycle (cat 4).
2. **Publication projection layer** — internal rows → GDAC-shape rows: name map (10 renames), HHMM→hours conversion, fixed 22-row order (replaces the writer's alphabetical-within-cycle rule **for the published file only**), numeric text formatting, 3 blank placeholders (+slot-17 policy).
3. **Not implementable from available raw:** the pre-mission (cycle 0 / 99999) block — no such buffer exists in any of the four floats' telemetry (DATA-COVERAGE; GDAC's START_DATE tie-in documented in §0).

## 5. Implementation plan (phased; nothing implemented yet)

- **Phase A — projection (pure, tested):** new pure function (e.g. `publication_rows_gdac(tech_rows_or_dataset, float_times)`) producing the 22-row × N-cycle publication set; unit tests for every mapping row, conversion, order, blanks. Decoder's tech write path switches to projected rows; `tech_rows` unchanged.
- **Phase B — formatting:** GDAC-compatible numeric text (hours 4-dp trimmed; counts integer; volts/battery 1-dp trimmed — already matching; blanks `''`).
- **Phase C — validators:** `validate_arvor_i_tech_gdac.py` upgraded to strict set-equality (21 names / 22-row order) + per-cell value parity with formulas; Phase-4A validator retargeted at the internal model; pipeline test asserts published names == GDAC names.
- **Phase D — decision items (need your sign-off before Phase A):**
  - **D1 SurfaceOffset:** publish our correct dbar (0.2 — diverges from GDAC's 2.0) **[recommended; standing rule: never reproduce GDAC unit errors]** vs strict numeric parity (×10).
  - **D2 Vacuum slot 17:** publish our derived ProfileStart mbar (625) vs GDAC's blank **[recommended: natural derivation; blanking suppresses decoded data]**.
  - **D3 placeholders (idx 2/12/19):** publish blank rows for name parity **[recommended; blank = honest absence of any source item]**.
- **Phase E — verification:** fleet rerun; Mono untouched (69-file residual inventory identical); Rtraj/Meta validators re-green (must be unaffected); full pytest; ruff; APEX A/B (no shared code touched — expected identical).

## 6–7. Scope compliance

Mono/Rtraj/Meta untouched (this phase changed no code at all). No GDAC value copied or hardcoded anywhere in the plan — every published value flows from raw items through the existing decode; only representation transforms (renames, HHMM→hours, text formatting) are new.
