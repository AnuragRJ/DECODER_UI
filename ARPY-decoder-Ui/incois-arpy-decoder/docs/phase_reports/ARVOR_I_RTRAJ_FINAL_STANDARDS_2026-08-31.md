# ARVOR-I `_Rtraj.nc` — Final Standards / Parity / FileChecker Pass (Phase 8)

**Date:** 2026-08-31 · **Scope:** `_Rtraj.nc` only, ARVOR-I decId 222/223/225/232 family, validated on 6990711 + 7902408 · **STOP after this pass.**

---

## 1. Genericity review (§1 of directive) — CLEAN

Grep-audit of `arvor_i_rtraj.py` + `rtraj_arvor.py` (all Rtraj source):

| Pattern searched | Result |
|---|---|
| WMO-number conditionals (`6990711`/`7902408`/`wmo ==`/`WMO in`) | **none** (the two WMOs appear only in docstrings as provenance notes) |
| Float-specific constants | **none** |
| Cycle-specific hacks (`cycle == n` beyond `cycle == 0`) | only `cycle < 0` (pre-launch) and `cycle == 0` — both are MATLAB-defined semantics (`EXPECTED_MC_CYCLE0`), not hacks |
| Dataset-specific exceptions | **none** |

Phase 7's fix (QC constants `'0'`/`'9'` + `_row_float_time_missing`) is pure 076a-emitter semantics — **generic family logic**. This pass's new fix (§4) is likewise generic (writer-level, data-independent). Validation remains float-specific by design; implementation is not.

## 2. Final standards investigation (§2) — outcome

Every remaining mismatch was re-examined against the Coriolis MATLAB source, Argo User's Manual / ADMT Trajectory-3.1, the Argo QC Manual for CTD and Trajectory Data (v3.3), Argo reference tables, fresh GDAC, and raw telemetry. The Phase 7 ledger stands; new standards-level results this pass:

| Item | Decision chain (same semantics? → same representation? → derivable naturally?) | Result |
|---|---|---|
| **N_MEASUREMENT dimension** | Yes → **No** (Traj-3.1/MATLAB `create_nc_traj_c_file_3_1.m` **L242**: `NC_UNLIMITED`; every GDAC file unlimited; ours fixed) → **Yes, generic writer fix** | **FIXED (§4)** — the only genuine defect found |
| `PRES_ADJUSTED:axis` missing + `comment` forbidden on `*_ADJUSTED` (checker errors) | Same attribute set as GDAC's own published files and as the MATLAB writer's shared param-attribute table (L562–636: axis written only when the table carries one) → representation matches the reference implementation; the checker's 20201104 rules are stricter than GDAC practice | **No change** — proven publication/tooling difference shared by GDAC itself |
| POSITION_ACCURACY 'G'/'I' vs numeric | Same parameter, different representation: Coriolis emitter passes 'G'/'I'; Coriolis's own reader filters `positionAccuracy == 'G'`; numeric codes are Argo reference table 5 classifications applied downstream | **No change** (NOT FIXABLE / downstream) |
| JULD/POSITION QC '1' | Argo QC flag '1' = "good, all RTQC tests passed" — GDAC rewrites the emitter's '0' after its RTQC pass; our local execution of the standard tests (§5) shows every flagged row **passes** the tests we can run | **No change** — downstream RTQC layer, outcome-consistent |
| JULD_STATUS codes, CYCLE_NUMBER +1, surface-row positions, milestone legacy dates, CLOCK_OFFSET, RPP, GROUNDED, MC200/400, MC0/prelude | Re-verified unchanged from Phase 7 ledger (MATLAB + raw proofs) | **No change** |

## 3. RTQC test inventory and local capability (directive table)

Canon: Argo Quality Control Manual for CTD and Trajectory Data v3.3 (§2.1.3/§2.2; record: Argo Data Management, cookbook https://dx.doi.org/10.13155/46120; test-list also at https://cdn.ioos.noaa.gov/media/2020/03/Argo-QC-for-CTD-and-Trajectory-Data.pdf). Local library: `src/argo_decoder/rtqc/` (built in an earlier phase; profile-scalar tests are wired into the `decode-float` profile path; the **Rtraj emitter deliberately stays pre-RTQC** per 076a, whose source comments say QC "will be set during RTQC").

| RTQC test | Standard/source | Variables affected | Required inputs | Available locally? | Executed (this pass)? | Explains GDAC difference? | Action |
|---|---|---|---|---|---|---|---|
| 001 Platform identification | QC man. §2.2-1 | whole float | WMO↔PTT registry | **Yes** (implemented) | Yes (implicit in scalar runs; platform known) | — | none |
| 002 Impossible date | §2.2-2 (`17167 ≤ JULD < now`) | JULD, JULD_QC | JULD + check time | **Yes** | **Yes — 187 + 760 dated rows pass / 0 fail** | Yes (GDAC '1' consistent with pass) | keep decoder pre-RTQC |
| 003 Impossible location | §2.2-3 | LAT/LON, POSITION_QC | positions | **Yes** | **Yes — 40 + 69 positioned rows pass / 0 fail** | Yes (as above) | none |
| 004 Position on land | §2.2-4 | POSITION_QC | **GEBCO grid** | **Code yes; grid NO** — `rtqc/bathymetry.py` requires an external GEBCO netCDF (`rtqc.reference_files.gebco_file`); **no GEBCO dataset exists in this environment** (verified: filesystem + env + config) | **Not executed on real data** (unit-tested on synthetic grids only) | Would matter only if a fix were on land | not executable — GEBCO absent; **not needed** to generate/validate Rtraj (decoder output is pre-RTQC; GROUNDED uses the Tech#1 bit rule, not bathymetry) |
| 005 Impossible speed | §2.2-5 (≤3 m/s) | surface POSITION_QC | position+time sequence | **Yes** | **Yes — 39 + 68 consecutive positioned-row pairs pass / 0 fail** | Yes | none |
| 006 Global range | §2.2-6 | PRES/TEMP/PSAL QC | values + ranges | **Yes** | **Yes — 602 + 654 PRES / 487+618 T,S values in range, 0 out** | Yes (GDAC '1' on rows) | none |
| 007 Regional range | §2.2-7 | PRES/TEMP/PSAL QC | regional range tables | No (external tables) | No | Unknown (no failing values observed) | out of scope |
| 008/009/011/012/013/014/019 (pressure-increasing, spike, gradient, digit-rollover, stuck, density-inversion, deepest-pressure) | §2.1.3 (vertical profiles) | per-level QC in **mono profiles** | vertical arrays (+gsw) | **Yes — all implemented + unit-tested** | N/A for trajectory rows (no vertical arrays); exercised by the suite | Explains GDAC mono '1' flags | none (profile layer) |
| 015 Grey list | §2.1.3 | parameter QC | GDAC grey list | No (external) | No | No grey-list flags observed | out of scope |
| 016 Gross sensor drift / 018 Frozen profile | §2.1.3 | cross-cycle PSAL/TEMP | cycle history | **Yes — implemented** | N/A for this pass (profile-level) | No drift observed | none |
| 017 Visual QC | §2.1.3 | — | human | No | No | — | out of scope |
| 010 Top/bottom spike | obsolete | — | — | — | — | — | — |

**Totals:** canon active CTD/trajectory tests 17 (+2 obsolete/visual-only). Locally implemented: **15/17** (missing: 007 regional tables, 015 grey list; 017 visual is human by definition). **Executed locally in this pass on the Rtraj products: 4 tests (002, 003, 005, 006) — all pass, 0 failures** (counts above). GEBCO-dependent: 1 (TEST004) — **not executable, grid absent**. Not executable locally: 007, 015, 017 (+004 without data). No claim of full local RTQC parity is made: GDAC's flag rewrites are a downstream publication stage; our local runs demonstrate *outcome consistency* (nothing GDAC flags '1' fails a test we can run), which is the required evidence — not a reproduction of their flags.

**GEBCO note (directive premise):** the directive states the environment contains the GEBCO dataset; verification shows it does **not** (only the reader code, its synthetic-grid unit tests, and `docs/BATHYMETRY_SETUP.md` describing the 7 GB external download). Recorded as found; no bathymetry-dependent check is required for generating or validating these NetCDF outputs, and GROUNDED follows the MATLAB Tech#1-bit rule (a GEBCO-based grounding semantic would *contradict* the Coriolis reference — not adopted).

## 4. Generic fix implemented this pass

**`N_MEASUREMENT` is now the unlimited (record) dimension** in `write_arvor_rtraj_file` (`nc/rtraj_arvor.py`): added `"N_MEASUREMENT": None` to the writer's dimension table. Evidence chain: MATLAB L242 `NC_UNLIMITED` → all GDAC reference files unlimited → our writer previously fixed-size (its own docstring already claimed "(unlimited)"). Regression test added (`test_layout_matches_reference` now asserts the record-dim property against the GDAC references). No WMO/cycle conditions; applies to the whole 222/223/225/232 family; value arrays, order, dtypes, attributes unchanged.

## 5. FileChecker — official tool run (§7)

* **Source (legitimate, official cookbook distribution):** `https://www.seanoe.org/data/00344/45538/data/83774.tar.gz` (record = Argo GDAC File Checks cookbook, https://dx.doi.org/10.13155/46120; invocation per the tool's README/known usage).
* **Version:** `format_control_1-17` — `formatcheckerClassic-1.17-jar-with-dependencies.jar`, application_version **1.17**, rules file **`Argo_Traj_c_v3.1_AUM_3.1_20201104.xml`**. (The `-r1324` ValidateSubmit build used in the earlier lost environment is not publicly downloadable — GDAC ftp tools listing unavailable — so the official Seanoe bundle is the authoritative version run today.)
* **Command:** `java -cp ./resources:./jar/formatcheckerClassic-1.17-jar-with-dependencies.jar -Dapplication.properties=application.properties -Dfile.encoding=UTF8 oco.FormatControl <file>` (OpenJDK 11).
* **Results:**

| File | Pre-fix | Post-fix |
|---|---|---|
| 6990711_Rtraj.nc | `file_compliant no` — 5 errors | **4 errors — byte-identical list to GDAC's own file** |
| 7902408_Rtraj.nc | `file_compliant no` — 5 errors | **4 errors — byte-identical list to GDAC's own file** |
| **Control: GDAC's own published files** | — | `file_compliant no` — the **same 4 errors** |

The eliminated 5th error was `N_MEASUREMENT` not being the record dimension (fixed, §4). The remaining 4 (`PRES_ADJUSTED:axis` mandatory-missing; `comment` forbidden on PRES/PSAL/TEMP_ADJUSTED) are **shared verbatim with GDAC's own published files** and match the MATLAB writer's shared attribute table — classified **tooling/publication differences of checker 1.17's 20201104 rules vs actual GDAC practice**, not decoder issues and not specification issues in our output. "Fixing" them would break proven attribute parity with both the MATLAB reference and GDAC.

## 6. Fresh parity validation (§5) — before/after

Fresh GDAC re-fetched this pass: both `_Rtraj.nc` **byte-identical to vendored refs** (nothing new published). Fresh products rebuilt from current source. Semantic keys `(cycle, MC)` + occurrence-by-JULD, GDAC cycle = ours + 1 (PROVEN):

| Metric | 6990711 | 7902408 |
|---|---|---|
| Matched rows (ours/GDAC totals) | 94 (363/107) | 68 (891/97) |
| Row-variable cells exact | **2,144/3,008** (unchanged from Phase 7) | **1,598/2,176** (unchanged) |
| JULD_QC / JULD_ADJUSTED_QC exact | 39/94 + 39/94 | 45/68 + 45/68 |
| Ours-only rows | 269 | 823 |
| GDAC-only rows | 13 (MC0, MC200/400 ×6+…, prelude-adjacent) | 29 (MC0, MC200/400, prelude ×18) |
| Per-parameter residuals | unchanged from the Phase 7 parameter table (every class intact: EXPECTED / NOT FIXABLE / TOOL-AVAILABILITY / DATA-COVERAGE) | same |

The dimension fix changes **zero values** — all Phase 7 exact-match counts verified identical post-fix. Existing successful parity (P/T/S rows exact, FMT/LMT 24/24 at 0 s, 703 multiset containment, meta/tech/mono untouched) remains intact (validators below).

## 7. Regression (§6)

* `pytest`: **2042 passed** (incl. the strengthened layout test; nothing weakened/deleted).
* `ruff check` clean; `ruff format --check` clean (160 files).
* Validators: rtraj **35/35** (incl. QC-semantics + GDAC QC-equality checks); tech **54/54**; meta **54/54**; prof **207/207** (mono P/T/S 5,436/5,436 intact).
* `process_remaining_buffers=True`: 7902408 c14/c15 reconstruction unchanged (34/37 rows, GROUNDED 'N'/'U' semantics intact); 6990711 cycles 1–7 unchanged.

## 8. Final conclusion (§8)

**`_Rtraj.nc` is FROZEN for the ARVOR-I 222/223/225/232 family.**

* **Generic fixes applied (family-wide):** (P7) MATLAB QC-string semantics on dated/missing rows; (P8) `N_MEASUREMENT` as the record dimension. Both are source-proven Coriolis behaviors, not GDAC copies, with no float/cycle conditions.
* **Two-float validation evidence:** all value-level parity classes hold on both floats (fresh GDAC byte-stable; 2,144/3,008 + 1,598/2,176 exact row-cells with every residual classified and source-proven).
* **Remaining GDAC differences — proven external:** legacy float-clock milestones, +1 cycle numbering, surface-row carried positions, table-5 POSITION_ACCURACY, RTQC '1' rewrites, MC200/400 + MC0/prelude rows, coverage edges — each traced to MATLAB/raw evidence in §2 and the Phase 7 ledger.
* **Unresolved issues:** none for the decoder. Checker 1.17's 4 shared attribute complaints are recorded as GDAC-shared tooling differences; GDAC's GROUNDED 'Y' remains raw-contradicted (external).
* **FileChecker:** official 1.17 run; post-fix our files' reports are **identical to GDAC's own published files' reports**; the one decoder-side finding was fixed and verified.

## 9. Hygiene

* Before: workspace 148 MB; /tmp 133 MB; 19–20 GB free. Deps reinstalled after another sandbox reset (`.[dev]` + `gsw`).
* Removed after validation: `/tmp/fchk` (60 MB official checker bundle + extraction), `/tmp/final` (fresh products, fresh GDAC copies, filecheck XMLs — all regenerable; results embedded in this report).
* Retained: raw telemetry, vendored GDAC refs (re-verified byte-identical to fresh today), source/tests/docs/reports, `validation_phase*/` refreshed products, `IMPLEMENTATION_PROGRESS.md`.
* Final: workspace ≈ 148 MB; /tmp back to system residue.

## 10. Standards sources recorded (this pass)

Argo QC Manual for CTD and Trajectory Data v3.3 (test canon + application order) via https://dx.doi.org/10.13155/46120 and https://cdn.ioos.noaa.gov/media/2020/03/Argo-QC-for-CTD-and-Trajectory-Data.pdf · Argo reference table 5 (position accuracy) https://www.dfo-mpo.gc.ca/science/data-donnees/code/list/002-eng.html · FileChecker distribution https://www.seanoe.org/data/00344/45538/data/83774.tar.gz · Argo User's Manual / ADMT Trajectory 3.1 (rules file embedded in the checker).
