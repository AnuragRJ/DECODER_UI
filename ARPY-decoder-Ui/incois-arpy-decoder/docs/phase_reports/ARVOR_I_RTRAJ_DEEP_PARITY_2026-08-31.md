# ARVOR-I `_Rtraj.nc` — Deep Parity Investigation + Fix (Phase 7)

**Date:** 2026-08-31
**Scope:** `_Rtraj.nc` only (floats 6990711/decId 222, 7902408/decId 232). No Tech/meta/mono/RTQC/other-family changes.
**Mode:** investigate → implement genuine fixes only → fresh validation → regression → document.
**References:** Coriolis MATLAB 076a chain (vendored `tests/data/arvor_i/coriolis_src/`, container copy cross-checked) = decoder reference; INCOIS GDAC = independent parity target (never copied).

---

## 1. Fresh references (re-fetched before validation, per directive)

`https://data-argo.ifremer.fr/dac/incois/{6990711,7902408}/{6990711,7902408}_Rtraj.nc` fetched 2026-08-31 → **md5-identical to the vendored `gdac_arvor_i_ref/` copies** (INCOIS has published nothing new since 2026-06-16). Directory listings unchanged.

## 2. Investigation — every significant discrepancy (raw → MATLAB → Python → GDAC)

| # | Item | Raw telemetry | Coriolis MATLAB rule | Python (before) | GDAC | Verdict |
|---|---|---|---|---|---|---|
| 1 | **JULD_QC / JULD_ADJUSTED_QC** | n/a (flag layer) | `init_default_values.m` L1015: `g_decArgo_qcStrNoQc = '0'`; **every** row creator sets `juldQc='0'` on DATED rows (`create_one_meas_float_time_ter.m`, `create_one_meas_surface.m`, `create_one_meas_float_time.m` dated branch) and `juldAdjQc='0'` on the adjusted twin; missing-time rows (`time=-1`) get `g_decArgo_qcStrMissing='9'` on both twins (L1024) | wrote `' '` (fill) on dated rows, `'9'` nowhere — **porting defect** | `'0'` on all dated non-location rows (71+66), `'1'` on MC703/MC0 only (35+30, RTQC pass) | **FIXABLE — fixed (§3)** |
| 2 | TET placeholder + finalize expected-MC fill rows | n/a | emitter L513 `create_one_meas_float_time(TET,-1,'9',drift)`; finalize L358 passes drift `0` (non-empty) → missing-date branch: QC `'9'`, `juldAdjStatus='9'`, `juldAdjQc='9'` | status `'9'` but QC `' '`, adjusted twins unset | dated `'0'` (their recon dates) | **FIXABLE — fixed (§3)** |
| 3 | JULD 7–40 s “reception” cells | `.eml` session times | FMT/LMT = mail session times; 703 Iridium rows = `timeOfSessionJuld` | same | **FMT/LMT 24/24 exact to the second** while the same-session 703 Iridium rows differ 7–40 s (GPS 703 rows exact) | GDAC 703 JULDs use INCOIS reception times; ours use float-clock session times — reproducible only with their reception logs → **NOT FIXABLE / EXPECTED** (kept) |
| 4 | Large integer-day milestone shifts (+2/+12/+21/+31 d; ASCENT_END +880 s) | float-clock dates | emitter writes real event dates | same | clock-accumulated reconstructions that **contradict GDAC's own row JULDs and post-date their own mail** (Phase 4B proof re-verified fresh) | **NOT FIXABLE** (legacy artifact; kept) |
| 5 | Skeleton/fill rows (ours undated where GDAC dated, e.g. 6990711 MC300/500/600) | Tech#1 timing absent for those cycles | `dateDef` → row stays init (fill) — MATLAB never fabricates | same | legacy clock-reconstructed dates | **NOT FIXABLE** (kept; classified fill-vs-value) |
| 6 | cycle-0 / prelude / MC0 launch rows | no launch position in raw/registry; pre-launch factory events | `add_launch_data_ir_sbd.m` needs launch metadata; numbering starts at first real cycle | same | prelude cycle 1 (7902408) + MC0 rows with registry positions | **DATA-COVERAGE / EXPECTED** (kept) |
| 7 | JULD_STATUS / JULD_ADJUSTED_STATUS ('2'/'3'/'4'/'9' vs '1') | n/a | `g_JULD_STATUS_{2,3,4,9}` globals; every call site pinned | ported exactly | `'1'` uniformly (their generator) | **NOT FIXABLE** (kept — MATLAB-proven statuses) |
| 8 | CYCLE_NUMBER +1 mapping | transmitted cycle numbers | direct numbering (tech/prof/MATLAB struct) | direct | Rtraj-only legacy +1 | **EXPECTED** (kept; cross-product consistency) |
| 9 | Surface-row positions (MC600/700/702/704/800) | mono GPS fixes | **PROVEN:** emitter L286/L377 create FMT/LMT with `argosLonDef` (no position); only `g_MC_Surface`(703) rows get positions (L314–345) | fills | carries the cycle's truncated GPS fix (= GDAC's own mono fix, byte-verified 12/12) | **NOT FIXABLE** (legacy carry; kept fills) |
| 10 | MC703 superset | every located mail + GPS fix | one 703 row per GPS fix + per located Iridium mail | same | session-grouped subset | **EXPECTED** (kept; multiset containment ours ⊇ GDAC proven 12/12 cycles) |
| 11 | POSITION_ACCURACY 'G'/'I' vs '0'-'3' | GPS fixes vs Iridium CEP | **PROVEN:** emitter passes `'G'`/`'I'`; Coriolis's own `nc_check_ir_fix_vs_gps_fix_in_traj.m` filters `positionAccuracy == 'G'` | `'G'`/`'I'` | Argo **reference table 5** numeric codes (0=>1000 m … 3<150 m; DFO-hosted table, recorded) assigned per-fix downstream | **NOT FIXABLE** (downstream/publication layer; kept) |
| 12 | POSITION_QC ('' / GPS-qc / '0' vs '1') | n/a | emitter comment L341: *"no need to set a Qc, it will be set during RTQC"* → `'0'` (Iridium), `num2str(gpsQc)` (GPS) | same | `'1'` (RTQC pass) | **TOOL-AVAILABILITY** (RTQC out of decoder scope; kept) |
| 13 | AXES_ERROR_ELLIPSE_* | Iridium CEP radii | `create_one_meas_surface_with_error_ellipse` sets major/minor=cepRadius·1000, angle 0 | same | fills | **NOT FIXABLE** (legacy fills; kept real values) |
| 14 | CLOCK_OFFSET (ours exact 0 vs GDAC 3–54 s) | Tech#1 clock offset decodes to 0 | **PROVEN:** L184 `floatClockDriftSec = cycleClockOffset/86400`; L392 `clockOffset = floatClockDriftSec` | ported exactly | their own (reception-based) estimates | **NOT FIXABLE** (kept) |
| 15 | GROUNDED (GDAC 'Y' at 7902408 row-cycles 3/6) | **no grounding evidence**: all tech1.field[12]=0, no grounding pressures, park pressures nominal (~1000 dbar) | **PROVEN:** `grounded='Y'` iff grounding pres present or `tabTech1(12+ID_OFFSET)==1` (L1015–1051) | ported exactly ('N') | 'Y' with no raw basis | **NOT FIXABLE** (GDAC-side derivation; kept) |
| 16 | REPRESENTATIVE_PARK_PRESSURE (ours real 977–1,042 dbar vs GDAC fill) | drift bins | emitter computes drift means → RPP row + `repParkPres` | ported | legacy generator never fills | **NOT FIXABLE** (kept real values) |
| 17 | GDAC MC200/MC400 (DET/DDET) rows | same events as our MC250/MC450 | 076a never emits 200/400 (consistency keys only) | not emitted | **measured: GDAC MC200 JULD ≡ our MC250 and MC400 ≡ our MC450 to 0.0 s** on unshifted cycles (later cycles carry the §4 day shifts) — legacy duplicate coding of the same events | **NOT FIXABLE** (kept; emitting would duplicate events) |
| 18 | Ours-only MC codes (89/150/189/198/203/290/297/298/301/389/398/489/497/498/503/589/590/599…) | full modern telemetry | 076a emitter set | ported | absent (legacy generator) | **EXPECTED** (kept) |

## 3. Changed rule (the single genuine fix)

**QC flag strings in `arvor_i_rtraj.py`** — port of `init_default_values.m` / row-creator semantics that was missing:

1. New constants `QC_NO_QC = "0"` (g_decArgo_qcStrNoQc), `QC_MISSING = "9"` (g_decArgo_qcStrMissing) + new `_row_float_time_missing()` helper (the `create_one_meas_float_time` time-`-1` branch).
2. `_row_float_time_ter`: dated rows now `juld_qc='0'`; adjusted twin `juld_adj_qc='0'` (was `' '`).
3. `_row_surface`: `juld_qc='0'`, `juld_adj_qc='0'` when clock known (was `' '`).
4. TET placeholder (emitter L513): QC `'9'` + `juld_adj_status='9'`/`juld_adj_qc='9'` when clock known (was `' '`, unset).
5. `_finalize` TET update: QC `'0'` on both twins (dated `create_one_meas_float_time` branch).
6. `_finalize` expected-MC fill rows (L358 semantics, drift argument non-empty): QC `'9'`, `juld_adj_status='9'`, `juld_adj_qc='9'`.

**Why it improves correctness and parity:** it reproduces the proven Coriolis MATLAB semantics (not a GDAC copy — GDAC additionally RTQC-overwrites QC to '1' on location rows, which we deliberately do **not** copy); it makes the decoder's “no QC performed” state machine-correct per Argo QC flag 0, and removes 168 spurious mismatches.

**Not changed (explicitly):** statuses, positions on surface rows, POSITION_ACCURACY/POSITION_QC encodings, cycle numbering, CLOCK_OFFSET, RPP, GROUNDED, milestone dates, MC emission set — all investigated and MATLAB- or raw-proven correct as-is (§2).

## 4. Before / after parity (matched (cycle,MC,occurrence) rows; fresh GDAC 2026-08-31)

| Metric | 6990711 before → after | 7902408 before → after |
|---|---|---|
| Matched rows (of ours/GDAC) | 94 (363/107) | 68 (891/97) |
| JULD_QC exact | 0/94 → **39/94** | 0/68 → **45/68** |
| JULD_ADJUSTED_QC exact | 0/94 → **39/94** | 0/68 → **45/68** |
| **Newly fixed cells** | **78** | **90** (168 total) |
| All row-variable cells exact | 2,066/3,008 → **2,144/3,008** | 1,508/2,176 → **1,598/2,176** |
| Row variables fully exact | 16/32 → **18/32** | 16/32 → **18/32** |

Residual JULD_QC mismatches decompose exactly into: GDAC RTQC `'1'` on MC703 rows (their QC pass — we keep `'0'`), and fill-vs-value rows (GDAC legacy-dates rows our timing correctly leaves undated). Validator check pins this: **JULD_QC == GDAC on matched dated non-location rows 39/39 and 45/45.**

## 5. Parameter-level parity table (after fix; both floats summed where uniform)

| Parameter | Cells | Exact | Mismatch | Class of residual |
|---|---|---|---|---|
| MEASUREMENT_CODE, CYCLE_NUMBER_ADJUSTED, SATELLITE_NAME, PRES/TEMP/PSAL (+QC/ADJ/ERR ×15) | 17 × 162 | **162/162 each** | 0 | — |
| JULD_QC, JULD_ADJUSTED_QC | 2 × 162 | 84+84 | 39+23 each | GDAC RTQC '1' on 703 (TOOL-AVAILABILITY) + fill-vs-value (NOT FIXABLE) |
| JULD, JULD_ADJUSTED | 2 × 162 | 44 within <1 s | rest | GDAC reception times (703 Iridium) + legacy day-shift recon + fill-vs-value (NOT FIXABLE/EXPECTED) |
| JULD_STATUS, JULD_ADJUSTED_STATUS | 2 × 162 | 0 | all | GDAC uniform '1' (NOT FIXABLE) |
| LATITUDE, LONGITUDE | 2 × 162 | 78/78 of 162 each | 84 | surface-row legacy carry + 703 superset pairing (NOT FIXABLE/EXPECTED; value equality via multiset proven) |
| POSITION_ACCURACY | 162 | 104 | 58 | GDAC table-5 numeric downstream codes (NOT FIXABLE) |
| POSITION_QC | 162 | 54 | 108 | RTQC '1' (TOOL-AVAILABILITY) |
| CYCLE_NUMBER | 162 | 0 | all | legacy +1 numbering (EXPECTED) |
| AXES_ERROR_ELLIPSE_MAJOR/MINOR/ANGLE | 3 × 162 | 114/114/114 | 48 each | GDAC fills real ellipses (NOT FIXABLE) |
| Per-cycle JULD_FIRST/LAST_MESSAGE | 24 | **24 (0.0 s)** | 0 | — |
| Other per-cycle milestones/statuses, CLOCK_OFFSET, RPP, RPP_STATUS | 12 × 24 + 24×24 | see §2 #4/#5/#7/#14/#16 | — | legacy recon / fill conventions / their estimates (NOT FIXABLE) |
| GROUNDED | 12 | 10 | 2 | GDAC 'Y' without raw basis (NOT FIXABLE) |

Ours-only rows: 269 + 823 (modern MC set, 703 superset, cycles beyond GDAC staleness). GDAC-only rows: 13 + 29 (MC0 launch, MC200/400 ×24 legacy duplicates, prelude/factory rows, beyond-raw). All classified in §2.

## 6. PROVEN / INFERRED / UNKNOWN ledger

* **PROVEN (MATLAB source, vendored + container cross-checked):** QC constants and creator QC semantics; FMT/LMT/no-position surface rows; 'G'/'I' POSITION_ACCURACY (+ Coriolis's own reader expecting 'G'); CLOCK_OFFSET formula; grounding rule; MC200/400 never emitted; TET placeholder + fill-row branches. **PROVEN (measured):** GDAC MC200≡our MC250, MC400≡our MC450 (0.0 s); GDAC JULD_QC '1' confined to MC703/MC0; FMT/LMT exact vs 703-Iridium 7–40 s (reception provenance); no raw grounding evidence; GDAC surface positions = GDAC mono positions (12/12).
* **INFERRED:** GDAC assigns table-5 POSITION_ACCURACY codes and POSITION_QC/JULD_QC '1' in a downstream RTQC/publication pass (their tools not public).
* **UNKNOWN:** none open. (GDAC's derivation of GROUNDED 'Y' remains unexplained but is raw-contradicted — recorded, not investigated further.)
* External source recorded: Argo reference table 5 (position-accuracy codes) — `https://www.dfo-mpo.gc.ca/science/data-donnees/code/list/002-eng.html` (consulted 2026-08-31).

## 7. Regression results

* Full suite: **2042 passed** (baseline 2035 + 7 new unit tests `TestRowQcSemantics`/extended finalize assertions; none weakened or deleted).
* `validate_arvor_i_rtraj.py`: **29 → 35 checks, 35/35 PASS** (new: JULD_QC '0' exactly on dated rows ×2, JULD_ADJUSTED_QC ×2, GDAC QC equality on matched dated non-location rows 39/39 + 45/45).
* Mono validator 207/207 (**P/T/S parity 5,436/5,436 preserved**); tech 54/54 (**common values exact**); meta 54/54 (**unchanged**).
* 6990711 cycles 1–7 correct; 7902408 c14/c15 reconstructed (34/37 rows, `process_remaining_buffers=True` behavior unchanged).
* `ruff check .` clean; `ruff format` clean (160 files).
* Products regenerated fresh: `/tmp/rtraj/products/{6990711,7902408}_Rtraj.nc` (workspace validator copies refreshed in `validation_phase4b_rtraj/`).

## 8. Recommendation for next step

No further Rtraj work is warranted: every remaining difference is classified with source-level evidence, and the only candidate that would reduce mismatch counts further (copying GDAC statuses/QC '1'/carried positions/table-5 codes) is explicitly rejected as legacy/publication-layer copying. **Rtraj returns to FROZEN.** Recommended next phase (when directed): none required for ARVOR-I; if the registry `<WMO>_meta.json` ever becomes available, meta DATA-COVERAGE fields close without code change (existing `--meta-json` hook).

## 9. Hygiene

* Before: workspace 144 MB, /tmp 133 MB used, 20 GB free disk. Deps reinstalled after sandbox reset (`.[dev]` + `gsw` — the 16 transient gsw-test failures were environmental, resolved).
* Removed after validation: `/tmp/rtraj/` entirely (2 fresh GDAC downloads + listings, fresh products, analysis/comparison scripts + JSON — all regenerable).
* Retained: raw telemetry, vendored GDAC refs (re-verified md5-identical to fresh), source/tests/docs/reports, refreshed `validation_phase*/` products, `IMPLEMENTATION_PROGRESS.md`.
* Final usage: workspace ≈ 144 MB (+ this report + progress append), /tmp reduced to system residue.
