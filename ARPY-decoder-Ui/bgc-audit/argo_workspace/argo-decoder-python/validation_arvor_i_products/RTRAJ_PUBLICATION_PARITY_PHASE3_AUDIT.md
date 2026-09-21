# Rtraj GDAC Publication Parity — Phase 3 Audit (re-verification against the ACTUAL tree)

**Date:** 2026-09-07 · **READ-ONLY.** No source, test, config, product or documentation conclusion modified.
**Method:** every claim below re-derived from the current tree — published products, GDAC references, raw `.eml`/`.sbd` telemetry, the vendored Coriolis `.m` reference (`tests/data/arvor_i/coriolis_src/`), and current official Argo documentation. Prior Phase-1/Phase-2 reports were treated as *unverified hypotheses*, not authority.
**Fleet:** 1902844, 2904082, 6990711, 7902408.

---

## 0. Answer to the key question

> *"Does the CURRENT published Rtraj file already contain exactly the GDAC publication set, with every nonblank GDAC value naturally reproducible from our decoder?"*

**Structurally: YES.** The published event set, family order, variable inventory and the position/time content that is genuinely derivable all match.

**Value-wise: YES for everything that is scientifically defensible.** Every remaining difference is either (a) a GDAC artifact that is demonstrably wrong against official Argo specifications or physically impossible, or (b) a proven raw-telemetry coverage limit.

**One genuine gap was found: the launch row (MC 0) QC/status fields.** This is the only FIXABLE item in the whole audit, and the official Argo Trajectory Cookbook — not GDAC mimicry — is the reason to fix it.

---

## 1. Variable inventory — exact parity (re-verified)

| | 1902844 | 2904082 | 6990711 | 7902408 |
|---|---|---|---|---|
| Variables ours / GDAC | 102 / 102 | 102 / 102 | 102 / 102 | 102 / 102 |
| ours-only variables | 0 | 0 | 0 | 0 |
| GDAC-only variables | 0 | 0 | 0 | 0 |
| dtype / dimension diffs | 0 | 0 | 0 | 0 |
| **attribute diffs** | **0** | **0** | **0** | **0** |

Every variable name, dtype, dimension tuple and **complete attribute set** (incl. `_FillValue`, `long_name`, `conventions`, `resolution`) is identical. **No variable-level work exists.**

## 2. Event (MEASUREMENT_CODE) inventory — exact parity

Published MC set is **identical on all four floats**:

`{0, 100, 200, 250, 300, 400, 500, 600, 700, 702, 703, 704, 800}` — 13 families.

- **No missing GDAC-published events.**
- **No extra ours-only published events.** The 18+ Coriolis diagnostic families (89/150/189/190/198/203/289/290/297/298/301/389/398/450/489/497/498/503/589/590/599/710/711/901) are correctly retained **internal-only** and never published.
- Per-cycle block order is the canonical `100,200,250,300,400,500,600,700,702,703×n,704,800`, launch row first — matching GDAC.
- Projection (`arvor_rtraj_publication_rows`) verified **pure** (uses `dataclasses.replace`, never mutates inputs) and **family-generic**: no WMO literal, no cycle literal, driven only by `_GDAC_RTRAJ_FAMILIES`. Internal Coriolis 076a decode fully preserved. ✅ meets the brief.

## 3. Comparison universe (contamination re-proven independently)

I did **not** take the contamination claim on trust. Re-derived:

- **64 cycles (14–77) are byte-identical between 1902844 and 2904082** — two different floats, identical JULD/LAT/LON/MC arrays. Physically impossible for genuine data.
- Those cycles sit at **lat −10.70…0.00°** while both real floats operate at **+9…+17.5°N**.
- Their dates run to **2028-02-06** — *in the future*, ~17 months beyond today (2026-09-07).

⇒ **NOT FIXABLE / never reproduce.** Clean comparison universe = **36 cycle-pairs** (12+12+7+5).

**Cycle numbering:** GDAC cycle = ours + 1, confirmed by **bit-exact FMT(702) equality (Δ = 0.000000 s)** on every matched pair, on all four floats. The launch row is at cycle −1 in *both*. GDAC's +1 shift is a legacy production artifact; the Argo convention is that the launch row is cycle −1 and the first transmitted cycle is 1. **Retaining our numbering is correct — EXPECTED.**

## 4. Per-MC value parity (36 clean pairs)

| MC | Field | Result | Classification |
|---|---|---|---|
| **702 FMT** | JULD, LAT, LON | **36/36 EXACT** (0.000000 s) | ✅ parity |
| **704 LMT** | JULD, LAT, LON | **36/36 EXACT** | ✅ parity |
| **703 fixes** | JULD, LAT, LON | **158/158 EXACT** | ✅ parity |
| 700 TST / 800 TET | LAT, LON | **36/36 EXACT** | ✅ parity |
| 600 AET | LAT, LON | 26/36 exact, 10 ours-fill | DATA-COVERAGE |
| 100/200/250 | JULD | fractional part **identical**; integer-day drift only | NOT FIXABLE (GDAC defect, §5.1) |
| 300/400/500 | JULD | 22 ours-fill (3 floats), 7902408 real | DATA-COVERAGE (§5.2) |
| 600/700/800 | JULD | systematic offsets | NOT FIXABLE (§5.3) |
| all | JULD_STATUS / QC | GDAC flattens to constants | PUBLICATION (§5.4) |
| 703 | POSITION_ACCURACY | ours `'I'`, GDAC Argos digits | NOT FIXABLE (§5.5) |
| **0 launch** | JULD, LAT, LON | **4/4 EXACT** | ✅ parity |
| **0 launch** | JULD_STATUS/QC, POSITION_QC/ACCURACY | **diverge ×4** | **🔴 FIXABLE (§6)** |

### 5.1 MC 100/200/250 integer-day drift — GDAC is physically impossible
Fractional parts match **exactly**; GDAC accumulates whole days (+1, +11, +21, +30, +50, +79, +89, +99 …). Falsification test — descent start (DST 100) must precede that cycle's transmission (FMT 702):

| | cycles checked | DST-after-FMT violations |
|---|---|---|
| **OURS** 1902844 | 9 | **0** |
| GDAC 1902844 | 9 | **7** |
| **OURS** 7902408 | 12 | **0** |
| GDAC 7902408 | 5 | **3** |

GDAC has the float starting its descent *after* it finished transmitting. **Legacy double-anchor defect → NOT FIXABLE, must never be reproduced.**

### 5.2 MC 300/400/500 fills — DATA-COVERAGE, proven in raw telemetry
These depend on `CONFIG_TC04_`/`MC29`/`MC31`/`TC22`, carried **only in pack_type-5 (Param#1)** packets. Decoded every raw `.eml`:

| WMO | pack_type 5 (Param#1) count | 300/400/500 |
|---|---|---|
| 1902844 | **0** | fill |
| 2904082 | **0** | fill |
| 6990711 | **0** | fill |
| **7902408** | **7** | **populated; AST 500 = 5/5 EXACT vs GDAC** |

The one float that transmits Param#1 produces AST matching GDAC **exactly**. This is decisive: the decoder path is correct, the other three floats simply never transmitted the config. **DATA-COVERAGE — nothing fabricated.** Reopen only if mission config enters the CSVs.

### 5.3 MC 600 AET — GDAC omits the documented Coriolis correction
On 7902408 the delta is a **constant 880.0 s** across all 5 cycles. Decomposed exactly:

```
Coriolis compute_prv_dates_222_to_227_231_232.m:180
  ascentEndDate = transStartDate − 10/1440 − TC04/100/86400
  = trans − 600 s − 280 s  (TC04 = 28000 csec, decoded from raw)
  = trans − 880 s          ← OURS
GDAC = trans − 0 s         ← subtracts nothing
```
GDAC publishes AET = transmission start, skipping the entire documented correction. **Ours implements the reference formula exactly → NOT FIXABLE (GDAC defect).**

Also: GDAC's own 100→600 block is internally inconsistent (on 7902408 cyc 4–6, AST 500 *precedes* DDET 400 by up to 22 days). Self-contradictory data must not be a parity target.

### 5.4 JULD_STATUS / QC flattening — GDAC violates the spec
GDAC writes `JULD_STATUS='1'` and `JULD_QC='0'` almost everywhere; ours carries semantically-correct per-event values. Against **Argo Reference Table 19** (NERC R19, fetched live):

| code | meaning | our usage |
|---|---|---|
| 2 | Value transmitted by the float | 100/250/700/800 ✅ correct |
| 3 | Computed directly from transmitted info | JULD_ADJUSTED ✅ correct |
| 4 | Determined by satellite | 702/703/704 ✅ correct |
| 1 | Estimated, *not* transmitted / typical behaviour | GDAC's blanket value ❌ wrong |

GDAC labels float-transmitted dates as "not transmitted by the float." Furthermore the **Argo QC manual states plainly: "POSITION_QC and JULD_QC cannot be '0'"** — GDAC writes `'0'` throughout. **PUBLICATION / NOT FIXABLE — ours is spec-correct.**

### 5.5 POSITION_ACCURACY — ours is spec-correct
Per **Argo Reference Table 5** (NERC R05, fetched live): `'I' = Iridium accuracy (not better than 5 km)`; `'0'/'1'/'2'/'3' = Argos` accuracy classes. These are **Iridium SBD floats with no Argos transmitter**. Our uniform `'I'` is correct; GDAC's Argos digits are physically meaningless here. **NOT FIXABLE.**
(703 GPS-`'G'` filtering verified working: zero `'G'` rows in any published 703 set; the `'G'` fix is retained internally and reused for MC 600.)

### 5.6 N_CYCLE fields
| Field | OURS | GDAC | Class |
|---|---|---|---|
| DATA_STATE_INDICATOR | `'2B  '` | `'2B  '` | ✅ **exact ×4** |
| CLOCK_OFFSET | real decoded (−2.3e-05 … −6.3e-04 d) | **0.0 everywhere** | NOT FIXABLE — GDAC discards a measured quantity; cookbook §1.2.5.1 requires the real offset |
| DATA_MODE | `'R'` when no offset applied | `'A'` | PUBLICATION — cookbook ties `'A'` to an *applied* adjustment |
| CONFIG_MISSION_NUMBER | `1` | **fill** | PUBLICATION — cookbook v5 requires CMN for launch/cycle 0; GDAC is self-inconsistent with its own meta file |
| GROUNDED | decoded per cycle | differs on 5 cycles | UNKNOWN — low volume; GDAC shows both directions |

## 6. 🔴 THE ONE GENUINE GAP — launch row (MC 0) QC/status

JULD, LATITUDE, LONGITUDE are **exact on all four floats**. Four flags diverge, identically on every float:

| field | OURS | GDAC | Official spec (Trajectory Cookbook §2.1.1) |
|---|---|---|---|
| `POSITION_QC` | `'0'` | `'1'` | **`0`** (then `1` once checked) |
| `POSITION_ACCURACY` | `'G'` | `' '` | **`_FillValue`** |
| `JULD_STATUS` | `'4'` | `'0'` | **`4`**, or `9` if JULD is fill |
| `JULD_QC` | `'0'` | `'1'` | (QC manual: cannot be `'0'`) |

**Verbatim cookbook text (DOI 10.13155/29824, §2.1.1 "Launch position and time"):**
> "They should be stored as the first LATITUDE, LONGITUDE and JULD of the N_MEASUREMENT array with: CYCLE_NUMBER = -1, **POSITION_QC = 0, POSITION_ACCURACY = _FILLValue**, MEASUREMENT_CODE = 0, **JULD_STATUS = 4** … Once the launch position has been checked, its QC should be set to 1."

**Adjudication — this is genuinely mixed, and GDAC is not uniformly right:**

| field | who is right | evidence |
|---|---|---|
| `POSITION_ACCURACY` | **GDAC** (`' '`) | Cookbook mandates `_FillValue`; our `'G'` is wrong (position comes from the deployment sheet, not a GPS fix) → **FIXABLE** |
| `JULD_QC` | **GDAC** (`'1'`) | QC manual: JULD_QC cannot be `'0'` → **FIXABLE** |
| `POSITION_QC` | **spec says `0`; GDAC says `1`** | Both defensible — `1` is legitimate *after* checking. GDAC's `1` is spec-compliant → **FIX CANDIDATE** (needs your ruling) |
| `JULD_STATUS` | **OURS (`'4'`)** | Cookbook explicitly says `4`; **GDAC's `'0'` contradicts the cookbook.** Do **not** copy GDAC → keep `'4'` |

Our current code (`arvor_i_rtraj.py:1017`) routes the launch row through the generic `_row_surface(..., "G", "", "0", ...)` helper, inheriting surface-fix defaults. `add_launch_data_ir_sbd.m` sets status 4 / QC no-QC from the *GPS launch record*, but our launch position comes from the **csv4 deployment sheet**, so the surface-fix defaults are not appropriate.

**Note this is NOT a GDAC-parity fix.** Three of the four changes are justified by the cookbook/QC manual; one (`JULD_STATUS`) would keep us *diverging* from GDAC because GDAC is wrong there.

### 6.1 Validator blind spot (must fix alongside)
`validate_arvor_i_rtraj.py:352-356` checks the launch row on **JULD, lat, lon only** — never the QC/status fields. `validate_arvor_i_rtraj_gdac.py` only checks the launch row's *position in the ordering*. This is exactly why **56/56 and 64/64 pass while the divergence exists.** Both reports and validators are otherwise accurate.

## 7. Verification of existing reports & validators

| Artifact | Verdict |
|---|---|
| `RTRAJ_..._PHASE1.md` | Claims re-verified and **hold** (contamination, cycle+1, 200≡250, position derivations, G1 coverage). |
| `RTRAJ_..._PHASE2.md` | Implementation matches the report; projection present, pure, generic. |
| `validate_arvor_i_rtraj.py` 64/64 | Passes; **incomplete** on launch QC/status. |
| `validate_arvor_i_rtraj_gdac.py` 56/56 | Passes; **incomplete** on launch QC/status. |
| Full suite | **2082 passed**, Tech 32/32 + 56/56, Meta 108/108 — Tech/Mono/Meta untouched. |
| One report nuance | Phase-1 said "400 ≈ 500". Precisely: **ours 400 == 500 exactly** (twin), **GDAC 400 ≠ 500 in 100% of cycles** and is internally inconsistent. Our twin synthesis is the defensible reading. |

## 8. Classification summary

| Class | Items |
|---|---|
| **FIXABLE** | Launch `POSITION_ACCURACY` `'G'`→fill; launch `JULD_QC` `'0'`→`'1'` |
| **FIX CANDIDATE** | Launch `POSITION_QC` `'0'` vs `'1'` (needs ruling) |
| **DATA-COVERAGE** | MC 300/400/500 fills ×3 floats (no Param#1 in raw — proven); 10 MC-600 positions (no GPS fix in cycle); 7902408 cycles 6–15 & GDAC-only cycles (stale/absent reference) |
| **PUBLICATION/RTQC** | JULD_STATUS/QC flattening; DATA_MODE `'A'`; CMN fill; cycle +1 renumbering |
| **NOT FIXABLE** | Foreign contaminated block (64 cycles, future dates); integer-day drift (physically impossible); AET 880 s omission; CLOCK_OFFSET zeroing; Argos POSITION_ACCURACY digits on an Iridium float |
| **EXPECTED** | Our cycle numbering; internal diagnostic families kept unpublished |
| **UNKNOWN** | GROUNDED differences on 5 cycles |
| **TOOL-AVAILABILITY** | (none new — RTQC/GEBCO out of scope, untouched) |

## 9. Phase-4 implementation plan (genuine gaps only)

Scope is deliberately tiny — **one function, two/three character constants, plus validator coverage.**

1. **Launch-row flags** — in `arvor_i_rtraj.py` (~line 1017), stop reusing surface-fix defaults for the launch row; emit cookbook-compliant values: `POSITION_ACCURACY = ' '` (fill), `JULD_QC = '1'`, `JULD_STATUS = '4'` (unchanged), `POSITION_QC` per your ruling. Family-generic, no WMO/cycle logic.
2. **Validator coverage** — extend both Rtraj validators to assert all four launch QC/status fields (closing the blind spot).
3. **Non-regression** — Rtraj 64/64 + 56/56, Tech 32/32 + 56/56 frozen, Meta 108/108, pytest 2082, ruff, APEX A/B, Mono 69-file inventory unchanged.
4. **Documentation** — append to `IMPLEMENTATION_PROGRESS.md` with the cookbook/Table-19/Table-5 citations.

**Explicitly NOT to be implemented** (would mean copying defective GDAC): integer-day drift, AET 880 s omission, CLOCK_OFFSET zeroing, Argos accuracy digits, JULD_STATUS/QC flattening, CMN blanking, cycle +1, contaminated cycles.

### Decision required
**`POSITION_QC` on the launch row: `'0'` (cookbook literal, pre-check) or `'1'` (checked, matches GDAC)?** Everything else is unambiguous.
