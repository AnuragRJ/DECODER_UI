# Rtraj GDAC Publication Parity — Phase 2 (Implementation & Validation)

**Date:** 2026-09-07 · **Status:** implemented, validated, all green. Tech.nc frozen (32/32 unchanged); Mono / Meta / GEBCO / Test-4 untouched (Mono 69-file residual inventory verified identical).

## 1. Implementation (generic, publication-layer only)

`nc/rtraj_arvor.py` gains a pure projection applied at the top of `build_arvor_rtraj_nc_dataset` (the single publication path — decoder, validator and tests all flow through it):

- **`arvor_rtraj_publication_rows(rows)`** — never mutates input rows, so the internal dataset keeps the full Coriolis 076a inventory (all diagnostic families + the GPS fix row):
  - keeps only the 13 GDAC families; launch (MC 0) first, cycles in **transmitted** numbering (the GDAC +1 shift is a legacy production artifact — no Argo/Coriolis publication rule mandates it; not adopted);
  - **synthesizes DET 200 ← PST 250 and DDET 400 ← AST 500** (Phase-1: GDAC 200 ≡ 250 exactly, 400 ≈ 500, every cycle, all floats) — dates stay the decoded float-clock values, never GDAC's;
  - **drops the GPS-'G' MC 703 row** from the publication (GDAC publishes Iridium mail locations only); retained internally;
  - **positions from proven telemetry derivations:** 700/702 ← first published 703 fix, 704/800 ← last, 600 ← `truncate_arc_minutes` of the cycle GPS fix (the dropped 'G' row), position QC carried from the source row; absent source ⇒ fill (nothing fabricated);
  - canonical per-cycle block order `100,200,250,300,400,500,600,700,702,703×N,704,800`.
- **`DATA_STATE_INDICATOR` default → `'2B  '`** (publication contract: all four references declare '2B '; real-time mode + RTQC-on-subset; WMO-independent constant, exact 4-char match).
- No WMO/cycle conditionals, no registry.csv, no GDAC values copied. **PET/AST/AET stay fill where the raw stream has no pack_type-5 Param#1 config** (1902844/2904082/6990711) — DATA-COVERAGE, nothing fabricated.

## 2. Strict bidirectional validation (`scripts/validate_arvor_i_rtraj_gdac.py`, 56/56)

Per float ×4, on freshly built-and-written files vs the GDAC references (clean pairs: GDAC cycle = transmitted + 1, gated by FMT-702 ≤ 30 min + ≥ 1 shared fix):

- **Shape:** family set == GDAC's 13 exactly (zero ours-only, zero GDAC-only) ×4; canonical block order in all 24/24/8/16 cycles; launch row first; 200 ≡ 250 and 400 ≡ 500 file-internally; zero 'G' 703 rows in file (15/14/5/12 retained internally); positioned events carry first/last-703 positions.
- **Header:** DSI '2B  ' exact; institution INCOIS; CONFIG_MISSION_NUMBER: GDAC fill everywhere, ours carries the csv4-launch / config-USE-table-derived mission number 1 (faithful 076a + Prompt-12 wiring; GDAC's fill is the legacy side — classified PUBLICATION, kept).
- **Values:** FMT/LMT **exact on all 34 clean pairs** (0 boundary cases needed); **703 fix sets equal on every clean pair** (incl. the 6990711 mail-span cluster correctly paired to our cycles 6/7); positioned events 600/700/702/704/800 **match GDAC exactly wherever telemetry exists**; every float-clock delta classified — exact (86), integer-day legacy anchors (53), quantified non-integer legacy anchors (43+), DATA-COVERAGE fills (92, exactly the no-Param#1 families), zero unclassified.
- **Unmatched GDAC content quantified:** 65 foreign-block cycles per 2026 float (byte-identical across WMOs — NOT FIXABLE, never reproduced), 7902408 stale prelude cycle 1, 6990711 replicated fix-store fragments.

## 3. Battery

Rtraj Phase-4B **64/64** · Rtraj GDAC strict **56/56** · Tech GDAC **32/32** (frozen) · Tech 4A **56/56** · Meta **108/108** (untouched) · full pytest **2082 passed** (29 Rtraj integration tests incl. the new projection class) · ruff check + format clean · **APEX A/B IDENTICAL** · fleet regenerated (pipeline ok ×4) · **Mono untouched** (69 files, residual inventory identical). Products refreshed in `validation_arvor_i_products/`; strict-validation artifacts in `validation_arvor_i_rtraj_gdac/`.

## 4. Remaining differences (classified)

| Difference | Class |
|---|---|
| Float-clock JULDs (100/250/300/500/600/700/800): GDAC = ours + legacy double-anchor days (integer + 2 quantified non-integer patterns) | Sanctioned divergence — our decoded dates published, GDAC's physically-impossible dates never reproduced |
| PET/AST/AET fill on 1902844/2904082/6990711 (GDAC has values) | DATA-COVERAGE (no Param#1 in raw; GDAC chain held config internally) |
| Status/QC vocabulary (JULD_STATUS '2' vs '1', launch '4' vs '0', POSITION_QC derived vs blanket '1', POSITION_ACCURACY 'G'/'I' vs unknown digits) | PUBLICATION — ours is the faithful 076a decode |
| CLOCK_OFFSET real vs GDAC 0.0; DATA_MODE R on no-offset cycles vs blanket 'A'; TST float-clock vs mail-anchored; TET next-CST vs ≈LMT | PUBLICATION (ours correct/derived) |
| CONFIG_MISSION_NUMBER 1 (csv4/USE-derived) vs GDAC fill | PUBLICATION (kept; GDAC meta itself declares 1) |
| GDAC foreign block (cycles 1, 14–77 on 2026 floats), replicated fix-store fragments, phantom GROUNDED-'Y' | NOT FIXABLE — legacy-chain artifacts, never reproduced |
| institution CSIRO vs INCOIS, history/DATE stamps | EXPECTED |
