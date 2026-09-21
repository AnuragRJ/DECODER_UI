# ARVOR-I `_Rtraj.nc` — Remaining-Fixes Pass (Phase 9)

**Date:** 2026-08-31 · **Basis:** the Phase 8 final-standards report's mismatch list (no new broad investigation) · **Scope:** `_Rtraj.nc` only · **Rule:** generic fixes only; never copy GDAC for parity.

---

## 1. Headline

* **FIXABLE decoder defects remaining: 0. FIX CANDIDATES investigated: 1 (CLOCK_OFFSET) — resolved as *correct behavior*, with a correction to the Phase 7/8 record (§2). No code change was warranted; none made.**
* All validation re-certified fresh: pytest **2042 passed**, ruff clean, rtraj validator **35/35**, tech 54/54, meta 54/54, prof 207/207, FileChecker 1.17 **0 decoder-unique findings**.
* Parity quantified with honest tolerance buckets (§4): every non-exact cell is decomposed into representation-level (≤0.5 s), reception-skew (≤60 s), legacy integer-day, fill-vs-value, or class-difference buckets — each mapped to its proven cause (§3).

## 2. FIX CANDIDATE investigated: CLOCK_OFFSET (classification CORRECTED)

Phase 7/8 recorded: *"ours exactly 0 (emitter double-division collapse) vs GDAC 3–54 s estimates."* **That attribution was wrong and is corrected here.**

Fresh root-cause (vendored MATLAB, full chain):

1. `decode_prv_data_ir_sbd_{222_223_225,232}.m` L143–147: `tabTech1(73) = twos_complement_dec_argo(tabTech1(73),16)`; stored **only when item 61 (valid GPS fix)** via `store_clock_offset_prv_ir(cycleNum, floatTime, tabTech1(73))`.
2. `get_clock_offset_value_prv_ir.m`: exact-cycle **mean** of stored events, else **linear interpolation** at the cycle reference time between the last prior and first later event (rounded to 1 s).
3. `adjust_clock_offset_prv_ir.m`: applies it to measurements and `cycleTimeData.cycleClockOffset`.
4. Emitter L392: `clockOffset = cycleClockOffset/86400` (days) → the netCDF `CLOCK_OFFSET` variable.

Our port implements every step (`collect_clock_offset_events` — including the item-61 gate; `clock_offset_for_cycle` — mean + interpolation; `apply_clock_offset`; emitter L392 port). Measured on raw telemetry:

| float | Tech#1 item-73 events (cycle → offset) | per-cycle applied offset |
|---|---|---|
| 6990711 | c1 −5 s, c2 −23 s, c3 −23 s, c4 −23 s, c7 −69 s (c5/c6 interpolated: −38, −54) | −5, −23, −23, −23, −38, −54, −69 s |
| 7902408 | c1 −3 s, c2–c12 −18 s each (c13–15: no Tech#1 → None → fill) | −3, −18 ×11, fill ×3 |

**GDAC's published `CLOCK_OFFSET` is a literal `0.0` on every cycle of both floats.** (The "3–54 s GDAC values" in the earlier reports were an artifact of my Phase 7 dump rounding *our* day-unit values to one decimal — `−5 s = −5.8e−5 d → "−0.0"` — which inverted the attribution.)

**Final classification: NOT FIXABLE (ours correct).** Our values are the raw-derived, MATLAB-faithful float-clock offsets; GDAC's zeros are their legacy generator dropping the field. Copying GDAC would delete real measurements. No change. *(Related note: the emitter's minute-level double-division collapse — `floatClockDriftMin` — remains real and correctly ported; it affects only skeleton `JULD_ADJUSTED`, which stays equal to `JULD`.)*

## 3. Full classification of every remaining mismatch (Phase 8 list)

| # | Item (cells) | Class | Reason / evidence | What would be needed to close (if data-bound) |
|---|---|---|---|---|
| 1 | JULD/JULD_ADJUSTED, 25+17 cells ≤0.5 s (μs-scale) | EXPECTED | representation-level float differences (their MATLAB datenum arithmetic); scientifically equivalent | — |
| 2 | JULD/JULD_ADJUSTED, 29+26 cells 7–40 s (MC703 Iridium rows; FMT/LMT are 0 s) | DATA-COVERAGE | GDAC 703 JULDs = INCOIS mail **reception** times; ours = float-clock session times (MATLAB `timeOfSessionJuld`) | INCOIS mail-server reception logs |
| 3 | JULD/JULD_ADJUSTED, 14+19 cells integer-day (+2…+31 d; MC100/250/300 etc.) | NOT FIXABLE | GDAC legacy clock-accumulation reconstruction; proven impossible dates (post-date their own mail; contradict GDAC's own row JULDs) | — (artifact) |
| 4 | JULD, 6+5 cells "other" (880 s ascent-end class; 9.75 d April cycle) | NOT FIXABLE / DATA-COVERAGE | 880 s = GDAC legacy ascent-end definition; 9.75 d = missing April 2025 mails (6990711 c5) | the April–May 2025 `.eml` set for 6990711 |
| 5 | JULD, 20+20 cells fill-vs-value | NOT FIXABLE | GDAC fabricates dates on rows our (MATLAB-faithful) timing correctly leaves undated | Tech#1 packets absent from raw (same April mails) |
| 6 | JULD_STATUS / JULD_ADJUSTED_STATUS, 162+162 ('2'/'3'/'4'/'9' vs '1') | NOT FIXABLE | ours = MATLAB `g_JULD_STATUS_*` semantics per creator; GDAC uniform '1' legacy | — |
| 7 | JULD_QC / JULD_ADJUSTED_QC, 55+23 residual ('0'/' ' vs GDAC '1'/'0') | PUBLICATION/RTQC | GDAC rewrites QC to '1' on location rows in its downstream RTQC pass (their QC='1' confined to MC703/MC0 — proven); decoder stays pre-RTQC per 076a source comment. Local execution of standard tests 002/003/005/006 (Phase 8) shows all our rows pass — outcome-consistent | GDAC's RTQC stage itself |
| 8 | POSITION_QC, 65+43 | PUBLICATION/RTQC | same RTQC pass ('1' on positioned rows) | as above |
| 9 | POSITION_ACCURACY, 35+23 ('G'/'I' vs table-5 numerics) | PUBLICATION (downstream) | ours = MATLAB emitter encoding ('G'/'I'); Coriolis's own reader filters `positionAccuracy == 'G'`; GDAC numerics = Argo ref-table-5 classification applied downstream | — (would break Coriolis-native semantics) |
| 10 | CYCLE_NUMBER, 162 (+1 offset) | EXPECTED | GDAC Rtraj legacy numbering; mono/tech/prof + MATLAB use direct | — |
| 11 | LATITUDE/LONGITUDE surface rows (35+25 fill-vs-value on MC600/700/702/704/800) | NOT FIXABLE | MATLAB never positions non-703 surface rows (creators called with `argosLonDef`); GDAC carries copies of the mono fix (proven = GDAC's own mono values, which our mono product reproduces) | — (fabrication otherwise) |
| 12 | LATITUDE/LONGITUDE MC703 pairing remainder | EXPECTED | our 703 set ⊇ GDAC per cycle (multiset-proven); occurrence pairing artifact only | — |
| 13 | AXES_ERROR_ELLIPSE_*, 30+18 fill-vs-value | NOT FIXABLE | ours = real Iridium CEP ellipses (MATLAB `create_one_meas_surface_with_error_ellipse`); GDAC legacy fills | — |
| 14 | CLOCK_OFFSET, 12 cycles | **NOT FIXABLE (corrected — §2)** | ours = raw Tech#1 item-73 offsets; GDAC literal 0.0 | — |
| 15 | GROUNDED, 2 cycles (GDAC 'Y') | NOT FIXABLE | zero raw grounding evidence (item-12 = 0 everywhere, no grounding pressures, park ~1000 dbar); MATLAB rule gives 'N' | — (GDAC-side derivation unknown, raw-contradicted) |
| 16 | REPRESENTATIVE_PARK_PRESSURE (+_STATUS), 12 cycles | NOT FIXABLE | ours = MC301 drift-mean (MATLAB emitter); GDAC legacy fills | — |
| 17 | Milestone per-cycle dates (integer-day pattern etc.) | NOT FIXABLE | same class as #3 (legacy reconstruction), per-variable detail in Phase 7 §5.3 | — |
| 18 | GDAC-only rows: MC0 ×2 | DATA-COVERAGE | launch position is registry metadata (`<WMO>_meta.json`, not public); optional `launch_position` input exists | INCOIS/CORIOLIS registry `*_meta.json` |
| 19 | GDAC-only rows: MC200/400 ×24 | NOT FIXABLE | proven legacy duplicate coding (GDAC MC200 ≡ our MC250, MC400 ≡ our MC450 at 0.0 s); 076a never emits them (consistency keys); emitting would duplicate events against the Coriolis reference | — |
| 20 | GDAC-only rows: 7902408 prelude ×18 | NOT FIXABLE / EXPECTED | GDAC cycle-1 prelude = factory/deck rows incl. 18230.0 placeholder dates; our numbering starts at cycle 1 | — |
| 21 | Ours-only rows 269 + 823 | EXPECTED | modern 076a MC set + MC703 superset + cycles beyond GDAC staleness (7902408 c6+; GDAC file stale since 2026-06-16) | GDAC republication |
| 22 | Header: DATA_STATE_INDICATOR '2B', registry strings, ' 3.1' leading space, DATE_* | NOT FIXABLE / DATA-COVERAGE / EXPECTED | publication/registry layer (unchanged classification) | registry json |

**FIXABLE: 0 · FIX CANDIDATE: 1 → resolved NOT FIXABLE (record corrected) · DATA-COVERAGE: 4 items · TOOL-AVAILABILITY: subsumed in PUBLICATION/RTQC (GDAC stage) · PUBLICATION/RTQC: 3 items · EXPECTED: 5 items · NOT FIXABLE: 9 items.**

## 4. Fresh quantitative parity (2026-09-02; GDAC re-fetched, byte-identical to vendored — nothing new published)

Semantic keys `(cycle, MC)` + occurrence-by-JULD, GDAC cycle = ours + 1. No code change this pass → values identical to Phase 8; buckets are the added resolution:

| Metric | 6990711 | 7902408 |
|---|---|---|
| rows ours / GDAC / matched | 363 / 107 / **94** | 891 / 97 / **68** |
| ours-only / GDAC-only rows | 269 / 13 | 823 / 29 |
| row-variable cells exact | **2,144 / 3,008** | **1,598 / 2,176** |
| mismatched cells | 864 | 578 |
| — of which ≤0.5 s (representation) | 50 (JULD-family) | 34 |
| — ≤60 s (reception skew) | 59 | 56 |
| — integer-day legacy / other legacy & April-cycle | 27 + 12 | 38 + 10 |
| — fill-vs-value (their fabricated dates / our real values) | 80 | 63 |
| — class/encoding differences (status, QC, accuracy, cycle#, pairing) | 636 | 377 |
| fully-exact row variables | 18/32 | 18/32 |
| per-cycle FIRST/LAST_MESSAGE | to-the-second exact (μs-level representation diffs only) | same |

Per-parameter mismatch counts are tabulated in §3 (cells per class); the raw ledger is `/tmp/rtraj9/parity.json` (removed post-certification, numbers embedded here).

**Before/after:** identical by design — this pass's investigation vindicated the current implementation (zero fixes warranted), so parity is unchanged from Phase 8 and every residual now carries both a class and, where data-bound, the exact missing-input statement (§3 last column).

## 5. Certification runs (fresh)

* Fresh GDAC: both `_Rtraj.nc` **byte-identical to vendored refs** (re-fetched this pass).
* `pytest`: **2042 passed** (nothing changed, nothing weakened).
* `ruff check` + `ruff format --check`: clean (160 files).
* Validators: rtraj **35/35** (incl. QC-semantics and GDAC QC-equality checks), tech **54/54**, meta **54/54**, prof **207/207** — cross-product regressions intact (mono P/T/S 5,436/5,436; tech common values exact; meta unchanged; `process_remaining_buffers=True` behavior unchanged).
* **FileChecker 1.17** (`formatcheckerClassic-1.17`, rules `Argo_Traj_c_v3.1_AUM_3.1_20201104.xml`, official Seanoe bundle): both fresh files → the same **4 shared attribute errors as GDAC's own published files** (control experiment, Phase 8) and **zero decoder-unique findings**; `N_MEASUREMENT` record-dim fix from Phase 8 holds.

## 6. Conclusion — freeze eligibility

* **Generic fixes applicable: none remained.** The single candidate (CLOCK_OFFSET) was investigated to root cause and proven already-correct (with the Phase 7/8 record corrected — the earlier "ours is zero" statement was a diagnostic artifact, not a decoder property).
* **Two-float evidence:** all §3 classes verified on both floats; parity values stable across Phase 7 → 8 → 9.
* **Natural-parity ceiling reached:** every remaining difference requires either external data we provably lack (INCOIS reception logs; April 2025 mails; registry json; GDAC republication) or is a GDAC legacy/publication artifact that Coriolis/Argo semantics forbid copying.
* Per the directive, **no freeze declaration is made here**: no substantial unresolved issue remains from the decoder side; `_Rtraj.nc` is **freeze-eligible**, with this report as the quantified closure basis.

## 7. Hygiene

Workspace ≈ 148 MB throughout. Removed post-certification: `/tmp/rtraj9` (fresh GDAC copies, fresh products, parity JSON, FileChecker bundle + XMLs — all regenerable). Retained: raw telemetry, vendored GDAC refs (re-verified byte-identical today), source/tests/docs/reports, validator-refreshed products, `IMPLEMENTATION_PROGRESS.md` (append-only entry below).
