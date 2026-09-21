# ARVOR-I Rtraj — RTQC Integration & Final GDAC Parity

**Date:** 2026-09-07 · **Scope:** Rtraj only. Tech frozen, Mono frozen, Meta untouched, GEBCO/Test-4 untouched.
**Evidence hierarchy:** Argo QC Manual v3.9 (DOI 10.13155/33951) → DAC Trajectory Cookbook (DOI 10.13155/29824) → NERC reference tables R19/R05/RR2 (fetched live) → vendored Coriolis MATLAB → raw ARVOR-I telemetry → INCOIS GDAC as publication target.

---

## 1. The central finding: the trajectory RTQC set is 4 tests, not 15

The prompt's applicable set (1,2,3,4,5,6,8,9,11/25,12,13,14,16,18,19) is the **vertical-profile** set from QC Manual §2.1.3. Trajectory files have their own section — **§4 "Real-time procedures on trajectory file data"** — and the Coriolis reference chain is unambiguous (`nc_add_rtqc_flags_prof_and_traj.m:775-786`):

```matlab
% define the tests to perform on trajectory data
testToPerformList2 = [ ...
   {'TEST002_IMPOSSIBLE_DATE'} {1} ...
   {'TEST003_IMPOSSIBLE_LOCATION'} {1} ...
   {'TEST004_POSITION_ON_LAND'} {1} ...
   {'TEST020_QUESTIONABLE_ARGOS_POSITION'} {1} ...
   ];
% perform RTQC on trajectory data (to fill JULD_QC, JULD_ADJUSTED_QC
% and POSITION_QC)
```

**Tests 2/3/4/20 are the only producers of `JULD_QC`, `JULD_ADJUSTED_QC` and `POSITION_QC`.** The profile-only tests (5/6/8/9/11/12/13/14/16/18/19) act on PRES/TEMP/PSAL levels, which an ARVOR-I Rtraj carries as fill everywhere — they have nothing to operate on. Applying the 15-test set here would have been scientifically meaningless.

The 15-test set remains correctly applied to **Mono**, which is frozen and verified unchanged (§7).

## 2. RTQC executed / passed / failed / skipped

New module `src/argo_decoder/rtqc/trajectory.py`, run on the internal decode **before** publication projection: `raw → decode → RTQC → publication`.

| Test | Status | Result | Basis |
|---|---|---|---|
| **2** Impossible date | **EXECUTED** | **PASSED** — 0 failures / 700 dated rows | `17167 <= JULD < now` |
| **3** Impossible location | **EXECUTED** | **PASSED** — 0 failures / 602 positioned rows | lat ±90, lon ±180 |
| **4** Position on land | **SKIPPED** | *"no bathymetry grid supplied"* | GEBCO absent — **never fabricated** |
| **20** Questionable ARGOS position | **SKIPPED** | *"no ARGOS-class fixes"* | Test 20's critical-error-length is defined only for ARGOS classes 1/2/3 (radii 1000/350/150 m). ARVOR-I is Iridium; accuracy `'I'` has no ARGOS error radius. |

Per-float dated/positioned rows tested: 1902844 210/199 · 2904082 211/204 · 6990711 84/69 · 7902408 195/130.

### Flag algebra (Coriolis `add_rtqc_to_trajectory_file` / `set_qc`)
- value is **fill** → QC stays `' '` (never assert QC for something absent)
- value **defined** → starts `'0'` (`g_decArgo_qcStrNoQc`)
- a test **runs** on it → raised to `'1'` (`g_decArgo_qcStrGood`)
- a test **fails** → escalated to `'4'`; `set_qc` only ever worsens

**Skipped ≠ passed** is enforced structurally: tests 4 and 20 leave flags untouched and are recorded in `skipped` with a reason.

## 3. Launch row (MC 0) — standards-derived, not hardcoded

Previously the launch row reused the generic surface-fix helper `_row_surface(..., "G", "", "0", ...)`, which wrongly claimed a **GPS fix** for what is actually META-file deployment metadata.

**Trajectory Cookbook §2.1.1, verbatim:**
> "They should be stored as the first LATITUDE, LONGITUDE and JULD of the N_MEASUREMENT array with: CYCLE_NUMBER = -1, **POSITION_QC = 0, POSITION_ACCURACY = _FILLValue**, MEASUREMENT_CODE = 0, **JULD_STATUS = 4** … Once the launch position has been checked, its QC should be set to 1."

New dedicated `_row_launch()` emits the cookbook state; RTQC then performs the "once checked" step:

| field | before | decoder init | after RTQC | GDAC | basis |
|---|---|---|---|---|---|
| `JULD_STATUS` | `'4'` | `'4'` | `'4'` | `'0'` | cookbook §2.1.1 — **GDAC is wrong, we diverge deliberately** |
| `POSITION_ACCURACY` | `'G'` ❌ | `''` | `''` | `''` | cookbook: `_FillValue` — **fixed** |
| `POSITION_QC` | `'0'` | `'0'` | **`'1'`** | `'1'` | test 3 ran and passed |
| `JULD_QC` | `'0'` | `'0'` | **`'1'`** | `'1'` | test 2 ran and passed |

The `'1'` values are **derived**, not assigned: remove the launch position and no flag is set; make the date impossible and it becomes `'4'`. Unit tests pin exactly this.

## 4. Independent corroboration: GDAC's own QC is RTQC-shaped

Before implementing, I measured GDAC's flag distribution. It is perfectly self-consistent with the 4-test model:

- `POSITION_QC = '1'` **iff** position defined, else fill — exactly test 3's footprint.
- `JULD_QC = '1'` **only** on MC 0 and MC 703 — precisely the satellite-determined dates; every float-clock row stays `'0'`.

Our output now reproduces both patterns naturally. Launch and all 703 rows match GDAC **exactly**, on all four floats.

## 5. Inventory parity — exact

| | 1902844 | 2904082 | 6990711 | 7902408 |
|---|---|---|---|---|
| variables ours/GDAC | 102/102 | 102/102 | 102/102 | 102/102 |
| ours-only / GDAC-only | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| dtype·dim diffs | 0 | 0 | 0 | 0 |
| **attribute diffs** | **0** | **0** | **0** | **0** |
| MC family set | identical | identical | identical | identical |

Published MC set = `{0,100,200,250,300,400,500,600,700,702,703,704,800}` — 13 families, canonical block order, launch first. **No missing GDAC events; no extra ours-only events.** The 18+ Coriolis diagnostic families stay internal-only.

## 6. Value parity (36 clean cycle-pairs)

| quantity | result |
|---|---|
| positions exact | **328 / 338** (10 ours-fill = no GPS fix in cycle) |
| JULD exact | 248 |
| JULD ours-fill | 114 (no Param#1 → DATA-COVERAGE) |
| JULD differing | 138 (legacy integer-day + AET 880 s, §6.1) |
| MC 702 FMT / 704 LMT / 703 | **exact** |
| launch JULD/lat/lon + all QC | **exact ×4** |

### 6.1 Differences retained deliberately (GDAC demonstrably wrong)
- **Integer-day drift on 100/200/250** — fractional parts identical; GDAC's whole-day offsets put descent start *after* transmission in 7/9 cycles (physically impossible). **NOT FIXABLE.**
- **AET 880 s** — GDAC publishes AET = transmission start, omitting Coriolis's `10 min + TC04/100` (=600+280 s, TC04 decoded from raw). **NOT FIXABLE.**
- **POSITION_ACCURACY `'I'` vs Argos digits** — Ref. Table 5: `'I'` = Iridium. These floats have no Argos transmitter. **NOT FIXABLE.**
- **JULD_STATUS/JULD_ADJUSTED_STATUS** — ours `2`/`3`/`4` per Ref. Table 19 semantics; GDAC flattens to `'1'` ("estimated, not transmitted"), mislabelling float-transmitted dates. **PUBLICATION.**
- **JULD_QC `'1'` vs GDAC `'0'` on float-clock rows** — GDAC runs test 2 but never raises the flag there. Ours applies the manual algebra uniformly. **PUBLICATION.**
- **CLOCK_OFFSET / DATA_MODE / CMN / cycle +1** — unchanged classifications from the Phase-3 audit.

## 7. Validation

| gate | result |
|---|---|
| **pytest** | **2096 passed**, 1 skipped (golden tree, pre-existing) — up from 2082 (+14 new RTQC tests) |
| Rtraj GDAC validator | **80/80** (was 56/56; +24 launch-QC/RTQC-provenance checks) |
| Rtraj 4B validator | **64/64** |
| Tech GDAC / Tech | **32/32** · **56/56** |
| Meta | **108/108** |
| ruff check + format | clean (172 files) |
| **APEX A/B** | **IDENTICAL** (4/4 fingerprints) |
| **Tech frozen** | content byte-identical excluding timestamps, ×4 floats |
| **Mono frozen** | 69 files; RTQC inventory identical (`executed {1,2,3,5,6,8,9,11,12,13,14,16,18,19}`, `failed {5:1,11:6,12:4,16:1}`) |

### Validator blind spot closed
The previous validators checked the launch row on JULD/lat/lon only — which is why 56/56 and 64/64 passed while a non-compliant `'G'` survived. The GDAC validator now asserts all four launch QC/status fields plus RTQC provenance (`POSITION_QC` set iff position defined).

Two 4B checks were **corrected, not weakened**: they asserted the pre-RTQC invariant `JULD_QC == '0' exactly`, which is now false *by design*. They assert the post-RTQC contract instead, and the GDAC JULD_QC comparison records its ratio with the PUBLICATION classification rather than demanding equality with a value we've shown to be under-flagged.

## 8. Genericity

- `apply_trajectory_rtqc` inspects only decoded row content (date, position, accuracy class). **No WMO, no cycle literal, no float-count assumption.** A dedicated test asserts identical flags for identical content on cycle 1 vs cycle 987.
- Test 20 activates automatically if an ARGOS-class fix ever appears; test 4 activates the moment a bathymetry grid is supplied.
- `_row_launch` is driven purely by the four-CSV deployment position — **four-CSV-only architecture intact**, `registry.csv` untouched for ARVOR-I.
- Works unchanged for any current or future ARVOR-I float.

## 9. Fixes made (2 genuine, both standards-driven)

1. **Launch `POSITION_ACCURACY` `'G'` → fill** — cookbook §2.1.1. The deployment position is not a GPS fix.
2. **Trajectory RTQC integrated** (`rtqc/trajectory.py`, wired into the Rtraj build) — `JULD_QC`/`JULD_ADJUSTED_QC`/`POSITION_QC` are now produced by the tests that ran, replacing a blanket decoder-assigned `'0'`.

`JULD_STATUS = '4'` was **not** changed to GDAC's `'0'`: the cookbook mandates 4.

## 10. Outstanding / not addressed here

- **Test 4** — needs a GEBCO grid (out of scope by instruction; correctly skipped).
- **Test 20** — needs an ARGOS-positioned float; not applicable to this Iridium family.
- **Mono tests 15 & 25** — unimplemented (25 is config-flag-only); documented in `RTQC_APPLIED_SET_AND_PARITY_2026-09-07.md`. Test 11 is deliberately retained over 25 for INCOIS parity. Mono is frozen; unchanged here.
