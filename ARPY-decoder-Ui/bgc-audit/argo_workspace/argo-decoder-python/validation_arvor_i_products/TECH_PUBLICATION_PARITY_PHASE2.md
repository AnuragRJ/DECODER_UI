# Tech.nc GDAC Publication Parity — Phase 2 (Implementation & Validation)

**Date:** 2026-09-07 · **Status:** implemented, validated, all green. Mono / Rtraj / Meta / GEBCO-Test-4 untouched (Mono 69-file residual inventory verified identical).

## 1. Before / after published inventory

| | Before (canonical) | After (GDAC projection) |
|---|---|---|
| Unique parameter names | 71 (Coriolis-canonical) | **21 (= GDAC exactly, all 4 floats)** |
| Rows per cycle | 44–67 (telemetry-dependent) | **22 fixed slots** |
| Internal-only names leaked | 66 | **0** |
| GDAC names missing | 16 | **0** |
| Duplicate vacuum slot | — | **present (blank, as GDAC)** |
| Placeholder blank columns | — | **3, exactly as GDAC** |

Internal decode unchanged: `ArvorTechDataset.tech_rows` still carries all 71 canonical names (item ids 100–242) — Phase-4A validator now checks the internal model (467/804 rows etc.) **and** the projected file separately.

## 2. Implementation (generic, evidence-backed)

- `nc/technical_arvor.py`: `_GDAC_TECH_SLOTS` — one family-generic 22-slot table (GDAC name → internal row → representation: identity / HHMM→decimal-hours / float-time components / blank) + pure `arvor_tech_publication_rows()`; both tech build paths project, so **every current or future ARVOR-I SBE41CP/Iridium float** through the shared write path gets the shape. No WMO/cycle conditionals (registry-routing guard test passes).
- `arvor_i_tech.py`: `ArvorTechDataset.float_times` retains the decoded float clock (Tech#1 items 41–46, LAST packet) internally; the projection splits it into `CLOCK_FloatTime_hours/_minutes/_seconds`.
- HHMM→hours formatter rule recovered from every GDAC hour cell: 4 decimals, extended to 5 significant digits when shorter, trailing zeros trimmed (`2043→'20.7167'`, `0005→'0.083333'`, `1200→'12'`).
- Renames per the Phase-1 mapping (Argos-style message names kept for publication compatibility; battery/vacuum/samples/messages/park counts). **SurfaceOffset keeps the correct Coriolis twos8/10 dbar value** — GDAC's ×10 raw-count publication (unit error, verified fleet-wide) is NOT reproduced (sanctioned divergence). Duplicate vacuum slot published blank exactly as GDAC structures it. Pre-mission block not fabricated (DATA-COVERAGE).
- Values derive exclusively from raw telemetry through the decoder; nothing is copied or hardcoded from GDAC.

## 3. Proof of parity (validator `validate_arvor_i_tech_gdac.py`, strict, 32/32)

Per float — 1902844 (15 cycles), 2904082 (14), 6990711 (7), 7902408 (12):

- **Name set == GDAC's 21 exactly**; no internal-only name leaks.
- **Fixed 22-slot order in every cycle** (0 order mismatches), duplicate slot 17 blank, placeholders (FLAG_ProfileTermination_hex, NUMBER_AscentSamples_COUNT, NUMBER_PumpActionsAtSurface_COUNT) blank.
- **Slot values, positional string-equality on every overlapping cycle: 958/968 exact, 0 mismatches**; the 10 non-identical cells are all `PRES_SurfaceOffsetNotTruncated_dbar`, each satisfying **GDAC = 10 × ours** (the classified unit-error divergence).
- Globals: DATA_CENTRE 'IN' / institution INCOIS == GDAC.
- Phase-4A validator: 56/56 (internal model + projection checks). Pipeline integration test asserts the 22×N/21-name shape end-to-end (genericity proof).

## 4. Remaining differences (classified)

| Difference | Class |
|---|---|
| SurfaceOffset: ours '0.1'–'0.5' dbar vs GDAC '1'–'5' (×10, 10 cells) | **Sanctioned divergence** — GDAC unit error; correct Coriolis decode preserved |
| GDAC pre-mission (cycle 0 / 99999) block absent | DATA-COVERAGE (no such buffer in raw; never fabricated) |
| GDAC cycles beyond our raw windows (merged/stale refs) | DATA-COVERAGE |
| GDAC blank cells inside its stale-window cycles (our corresponding cells carry decoded values) | EXPECTED (we publish the decode wherever telemetry exists) |
| DATE_CREATION/UPDATE, history run stamps | EXPECTED |

## 5. WMO/cycle independence

The projection is one family-constant slot table plus a pure function in the shared tech write path; decoder selection and metadata remain four-CSV-only (registry.csv untouched); no WMO or cycle literal appears in the projection (`test_no_wmo_specific_selection_conditions` green). The pipeline test proves any float decoded through the ARVOR-I path receives the identical GDAC shape automatically.

## 6. Verification battery

Fleet rerun (23/24/7/15 profiles, pipeline ok); Mono parity unchanged (69 files, residual inventory identical); validators: tech-GDAC **32/32**, tech-4A **56/56**, meta **108/108**, rtraj **64/64**; full pytest **2069 passed**; ruff check + format clean; **APEX A/B non-regression IDENTICAL** (78 fingerprints). Preserved artifacts regenerated: `validation_arvor_i_products/<wmo>_tech.nc` (pipeline products), `validation_arvor_i_tech_gdac/`.
