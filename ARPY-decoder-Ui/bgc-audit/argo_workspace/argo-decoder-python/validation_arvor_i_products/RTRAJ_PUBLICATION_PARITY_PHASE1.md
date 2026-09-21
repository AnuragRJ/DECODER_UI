# Rtraj GDAC Publication Parity — Phase 1 (Investigation & Mapping)

**Date:** 2026-09-07 · **Read-only.** No source, test, config or product modified. Tech.nc frozen (Prompt-14 result untouched); Mono/Meta/GEBCO/Test-4 untouched.
**Method:** all 4 GDAC refs (`gdac_arvor_i_ref/<wmo>_Rtraj.nc`) vs our products (`validation_arvor_i_products/<wmo>_Rtraj.nc`) vs raw `.eml` streams vs the Phase-4B mapping (`docs/phase_reports/ARVOR_I_PHASE4B_RTRAJ_MAPPING_2026-08-27.md`, MATLAB 076a semantics §2–§4). Cycle alignment by FMT-702 mail time (±30 min), clock-independent. Scripts: `/tmp/rtraj_phase1/*` (ephemeral; results below).

---

## 0. Cycle alignment & comparison universe

- **GDAC cycle = transmitted cycle + 1 — confirmed on all 4 floats** (1902844: GDAC 2–13 ↔ ours 1–12; 2904082: GDAC 2–13 ↔ ours 1–12; 6990711: GDAC 2–6 ↔ ours 1–5; 7902408: GDAC 2–6 ↔ ours 1–5). Join key 702 (absolute mail time) — unambiguous.
- **Reference contamination (PROVEN):** in the 1902844 and 2904082 GDAC files, cycles 1 and 14–77 are **byte-identical between the two different WMOs** (64/64 block cycles identical on JULD/LAT/LON/MC/ADJ/PQ/ACC; cycle 1 differs = float-specific prelude mixed with foreign content). Foreign block: 64 cycles, 2024-04-11→2026-02-04, continuous 10-day series, positions in the **southern** Indian Ocean (−9.5…−10.3°S, 72–86°E) while both real floats ride at +9…+11°N; dates precede the 2026 launches. Legacy-chain merge/contamination — **never reproducible, never to be reproduced.** All GDAC-only cycles are foreign or stale ⇒ zero genuine GDAC coverage beyond our decode.
- Coverage asymmetries: ours 13–24 (1902844/2904082) post-date the GDAC file (2026-06-16); ours 6–15 (7902408) post-date the stale ref (its own tech shows 17 cycles); 6990711 GDAC 7–8 are legacy fix-store fragments (mail spanning our cycles 5/6). ⇒ DATA-COVERAGE.
- Comparison universe: **34 clean cycle-pairs** (12+12+5+5).

## 1. Variable inventory — exact parity already

102 = 102 variables on every float: same names, dtypes, dimensions, attributes, order; `_FillValue` semantics equal. Global attributes differ only in `institution` (GDAC 'CSIRO' artifact vs ours 'INCOIS' per csv4 — classified in Prompt-12) and `history`/DATE_* stamps. **No variable-level work needed.**

## 2. GDAC event (MEASUREMENT_CODE) inventory & publication grammar

GDAC publishes **exactly 13 event families**, uniform across all 4 floats (contaminated block included):

| MC | meaning | fields filled | n (1902844) |
|---|---|---|---|
| 0 | launch (cycle −1) | JULD, JULD_STATUS '0', JULD_QC, LAT/LON, POSITION_QC | 1 |
| 100 | DST | JULD(+status/QC) + ADJ twins | 73 |
| 200 | DET | JULD + twins — **≡ 250 JULD exactly, every cycle, all floats** | 73 |
| 250 | PST | JULD + twins | 73 |
| 300 | PET | JULD + twins | 73 |
| 400 | DDET | JULD + twins — **ascent-start date ≈ 500** (Δ ∈ {−0.7…−40 min} or exactly the legacy integer-day anchor inconsistency: −6.0/−8.0/+3.99 d) | 73 |
| 500 | AST | JULD + twins | 73 |
| 600 | AET | JULD + twins + **LAT/LON/PQ** | 77 |
| 700 | TST | idem | 77 |
| 702 | FMT | idem | 77 |
| 703 | surface fixes | + **POSITION_ACCURACY** (digits) | 372 |
| 704 | LMT | idem 600 | 77 |
| 800 | TET | idem 600 | 77 |

Per-cycle row order (canonical block): `100,200,250,300,400,500,600,700,702,703×n,704,800`; launch row first (cycle −1); 2–5 partial blocks per file = legacy surface-only fragments `(600,700,702,703×n,704,800)`.
**Everywhere fill in GDAC:** PRES/TEMP/PSAL (+QC/ADJ), SATELLITE_NAME, error-ellipse axes, JULD_ADJUSTED_STATUS beyond twins. **JULD_ADJUSTED == JULD on every dated row** (2581/2581 across the 4 files) — our skeleton rows already satisfy this via the 076a double-division quirk.
Header/N_CYCLE: `DATA_STATE_INDICATOR = '2B '` (STRING4; RT mode); `CONFIG_MISSION_NUMBER` fill (→ **CMN resolved: both fill, stays fill**); `DATA_MODE = 'A'`; `CLOCK_OFFSET = 0.0` on every cycle; `GROUNDED` ∈ N/U/Y.

## 3. Ours-only inventory (18 diagnostic families) — all PROVEN 076a outputs

`89, 150, 189, 190, 198, 203, 289, 290, 297, 298, 301, 389, 398, 450, 489, 497, 498, 503, 589, 590, 599, 710, 901` (per-float presence varies with raw content; e.g. 1902844 emits 18 of them, 7902408 21). Every one is a faithful port of a documented emitter behaviour (Phase-4B §3: cycle-start/FST skeleton, hydraulic Spy rows bucketed [CST,PST)/[PST,PET)/…, profile bins 190/590, park drift 290 + RPP 301, deepest bins 203/503, Tech#1/2 misc 198/297/298/398/497/498/599, near-surface 710, grounding 901).
**Determination:** true decoder outputs (not artifacts); GDAC's legacy chain simply never published them. → keep internally (full Coriolis-compatible decode), **project out at the publication layer**. Classification: PUBLICATION (ours-only published rows removed).

## 4. GDAC-only inventory (200, 400) — derivable

- **MC 200 (DET):** GDAC JULD ≡ its own 250 (PST) exactly — a duplicate event row of the park-arrival date. 076a has 200 only as an N_CYCLE-consistency key. → publication: **duplicate of our PST row** (date/status), value = our decoded park date (sanctioned legacy-anchor divergence applies, same as 250). FIXABLE.
- **MC 400 (DDET):** GDAC ≈ 500 (ascent start) within minutes, except cycles where GDAC's own anchoring disagrees with itself by exact integer days (−6/−8/+3.99 — the §7.2 inconsistency). → publication: **our AST date**. FIXABLE.
- Values are *naturally derived* (both trace to decoded float-clock dates); GDAC's exact numbers additionally carry the double-anchor and are not reproduced (documented divergence, as locked for float-clock JULDs).

## 5. Mandate items — findings per family

- **MC 0 launch:** JULD + LAT/LON exact ×4 (csv4 wiring). Convention diffs: ours JULD_STATUS '4' vs GDAC '0', JULD_QC '0' vs '1', POSITION_ACCURACY 'G' vs blank, POSITION_QC '0' vs '1' → PUBLICATION (vocabulary). GDAC blank CYCLE −1 GROUNDED 'U'.
- **100/250:** GDAC = ours + **exact integer days = item8** RTC drift per cycle (1902844 anchors {0,1,11,21,30,50,79,89,99}; 2904082 {0,1,11,21,40,89,99}; 6990711 {0,2,12,21,51,71} + 2 non-integer legacy-inconsistent cycles (50.83/70.64); 7902408 {0,2,12,21,31}) — legacy double-anchor, physically impossible dates; NOT reproduced (sanctioned divergence, Prompt-12/§7.2). Our values correct.
- **300/500/600:** on **7902408** ours dated — 500 delta **0.0 ×5 (exact)**; 300 {0,−6,+4,+13,+23} mixed legacy anchoring; 600 +0.0102 d (mail-anchored legacy ≈ FMT−minutes). On **1902844/2904082/6990711 ours are fill** — see gap G1.
- **702/704:** **exact (0.0) on every clean cycle-pair** (29/29); 6990711 two cycles ±0.0007 d (≈1 min) = the mail spanning cycles 5/6 attributed to first tagged cycle (INFERRED §8, PUBLICATION).
- **703:** GDAC set = **ours minus exactly the cycle's GPS-'G' fix row** (verified: all dropped first-rows are 'G', 9+7+6+5 drops; cycles whose first row is 'I' are set-equal). Every GDAC 703 row is value-identical to ours (lat/lon/juld) incl. GDAC's extra per-cycle first-fix — ours is the superset. 6990711 GDAC 7/8 fragment rows = legacy replicated fix-store (§7.4) — NOT FIXABLE artifacts.
- **Positions on 600/700/702/704/800** (GDAC fills, ours blank — structure gap G3), derivations **proven**: 700=702=**first** 703 fix (exact ×4); 704=800=**last** 703 fix (exact ×4); 600=**truncate_arc_minutes(cycle Tech#1 GPS fix)** (5/5 exact on 1902844; matches 2904082/6990711/7902408 samples). All three derivations use data our decoder already holds (`GpsRecord`, `truncate_arc_minutes`).
- **DET/DDET/TST/TET/GROUNDED:** 200/400 as §4; TST: GDAC ≈ FMT+1.6–4 min (mail-anchored) vs ours decoded transStartDate; TET: GDAC ≈ LMT+0–10 min vs ours next-CST (076a finalize) — PUBLICATION semantics, ours 076a-faithful; GROUNDED: GDAC 'Y' on cycles with **no raw grounding events** (prelude/foreign-related cycles 1&5 patterns; our real grounding cycle 1902844-c1 isn't even marked by GDAC) → GDAC artifact NOT FIXABLE; ours raw-derived.
- **CMN:** fill both sides — resolved, stays fill.
- **DATA_STATE_INDICATOR:** GDAC '2B ' vs ours blank → FIX CANDIDATE (publication-mode constant, WMO-independent; not raw-derived but a file-mode declaration like DATA_TYPE).
- **Position/QC fields:** POSITION_QC GDAC blanket '1' vs ours '1'(GPS)/'0'(Iridium, 076a `num2str(gpsQc)`) → PUBLICATION (ours semantically faithful). POSITION_ACCURACY GDAC digits {0,1,2,3} (1902844: 0×94,1×30,2×41,3×207) — **semantics UNKNOWN** (no raw counterpart; not CEP, not fix count) → UNKNOWN; ours 'G'/'I' (076a) kept, classified.
- **Float-clock timing / +item8 legacy:** fully quantified ×4 (§5 100/250 anchors; the mechanism calendar+item8+hhmm from §7.2). Ours never reproduces it. GDAC `CLOCK_OFFSET=0.0` on all cycles vs ours measured drift (−2.3e−5…−2.7e−4 d, null when no offset event → our DATA_MODE 'R' on those cycles vs GDAC blanket 'A') → ours correct/derived; GDAC artifact; PUBLICATION.
- **Internal-fidelity observation (GDAC-agnostic):** our undated expected-skeleton rows carry JULD_STATUS ' ' where 076a §4.6 fill-in rows use '9' — FIX CANDIDATE side-fix (affects 9/10/3-cycle floats' 100/250/700 rows; cosmetic 076a faithfulness, not GDAC-driven).

## 6. Genuine implementation gaps

| # | Gap | Root cause | Class |
|---|---|---|---|
| G1 | PET(300)/DPST(450)/AST(500)/AET(600) dates **fill on all cycles** of 1902844/2904082/6990711 (GDAC publishes values) | **No pack_type-5 Param#1 packet in those raw streams** (stream census: types {0,1,2,3,4,6} vs 7902408 which has 5×7 → 62 config keys → dates computed). `MC29` gate parks the whole `ascent_end→ascent_start→d2p_end→d2p_start` chain. Coriolis reads config from internal float metadata, not raw; our csv4 `config_params.csv` lacks MC29/MC31/TC22/TC04. Pipeline PROVEN correct where config exists (500: 5/5 exact on 7902408). | **DATA-COVERAGE** (missing input; reopen as FIX CANDIDATE if mission config ever enters the four-CSV set — never hardcode) |
| G2 | DATA_STATE_INDICATOR blank vs '2B ' | writer leaves fill | FIX CANDIDATE (RT-mode constant) |
| G3 | no positions on 600/700/702/704/800 | 076a does not position them; GDAC legacy does | **FIXABLE** (3 proven derivations) |
| G4 | 200/400 rows absent | 076a emits them only as consistency keys | **FIXABLE** (duplicate-of-PST / AST) |
| G5 | ours publishes the GPS-'G' 703 row | 076a `create_one_meas_surface` | PUBLICATION (drop at projection to match GDAC set exactly; keep internally) |
| G6 | status/QC/accuracy vocabularies, CLOCK_OFFSET≠0, DATA_MODE A/R, TST/TET semantics, cycle +1 | legacy vs 076a conventions | PUBLICATION (keep ours; classified) / UNKNOWN (accuracy digits) |
| G7 | GDAC refs contain a foreign 65-cycle block (+prelude oddities) | legacy-chain contamination (byte-identical across WMOs) | NOT FIXABLE (never reproduce; restricts comparison universe) |

## 7. Value-parity summary (34 clean cycle-pairs)

- Exact: 702/704 (×29 clean), 703 rows (every GDAC row ∈ ours, identical), launch JULD/position, 7902408 MC 500 (×5), JULD_ADJUSTED==JULD semantics, variable/attr layer (×4 floats).
- Classified divergences: 100/250 +item8 integer days (sanctioned); 300/600 legacy anchoring; 700/800 mail-vs-float-clock semantics; G1 fills on 3 floats; vocabulary fields (§5).
- Ours superset: 703 GPS row; cycles beyond the refs (12+12+0+10).

## 8. Phase-2 implementation plan (projection at the publication layer, tech.nc-style)

1. Pure, family-generic `arvor_rtraj_publication_rows(rows, cycles)` in the Rtraj writer path (no WMO/cycle conditionals, no registry.csv; internal dataset untouched — full 076a decode retained):
   - keep families {0,100,250,300,500,600,700,702,703,704,800}; project out the 18 diagnostics;
   - synthesize **200 ← 250 row**, **400 ← 500 row** (status twins);
   - 703: Iridium rows only (drop the 'G' GPS row);
   - positions: 600 ← truncate_arc_minutes(cycle `GpsRecord`), 700/702 ← first 703, 704/800 ← last 703; PQ '1' on positioned rows per GDAC (or keep ours — decision);
   - canonical block order, launch first; blanks stay blank only where GDAC blank (PRES/TEMP/PSAL/satellite/ellipse).
2. Decision points to lock with user before code: (a) **cycle numbering** — keep transmitted (recommended; +1 is a legacy production artifact and would break cross-product consistency) vs adopt +1; (b) status/JULD_QC/POSITION_QC vocabulary — ours 076a-faithful (recommended) vs GDAC '1'/'0'; (c) DSI '2B ' — publish constant (recommended) vs blank; (d) POSITION_ACCURACY — keep 'G'/'I' (recommended; GDAC digits UNKNOWN); (e) G1 fills — publish fill rows (no values fabricable).
3. Validation: strict GDAC validator (family set/order/block structure, positional parity on the 34 clean cycle-pairs with the classified-divergence ledger, contamination excluded by construction), Phase-4B validator update, integration tests incl. family-generic projection test, full pytest, ruff, APEX A/B, artifact regen.

## 9. Classification ledger (8-way)

- **FIXABLE:** G3 (positioned 600/700/702/704/800), G4 (200/400 rows).
- **FIX CANDIDATE:** G2 (DSI '2B '), G1-reopen (if mission config enters CSVs), undated-row status '9' fidelity note.
- **DATA-COVERAGE:** G1 (Param#1 absent from raw on 3 floats); GDAC refs' missing our later cycles; ours beyond refs.
- **PUBLICATION:** ours-only diagnostics (§3); GPS-'G' 703 row; +item8 anchors (sanctioned divergence — GDAC values wrong); TST/TET/CLOCK_OFFSET/DATA_MODE/GROUNDED-U,Y vocabularies & artifacts; cycle +1; mail-boundary attribution (6990711 c5/6).
- **EXPECTED:** institution, history stamps.
- **NOT FIXABLE:** G7 contamination; GDAC replicated fix-store rows (6990711 c7/8); GDAC GROUNDED-'Y' phantom flags.
- **UNKNOWN:** POSITION_ACCURACY digit semantics.
- **TOOL-AVAILABILITY:** none new.

## 10. PROVEN / INFERRED / UNKNOWN

- **PROVEN:** §0 join & contamination (byte-identity); §1 variable parity; §2 grammar (uniform ×4); 200≡250; 400≈500 with anchor inconsistencies; 703 subset rule incl. 'G'-row identity; 600/700/702/704/800 position derivations; G1 root cause (pack-type census + 7902408 control); +item8 anchors ×4; DSI/CMN/CLOCK_OFFSET/GROUNDED/DATA_MODE values.
- **INFERRED:** none used.
- **UNKNOWN:** GDAC POSITION_ACCURACY digits; legacy chain internals (unchanged §10 stance — not reverse-engineered beyond numeric proof).
