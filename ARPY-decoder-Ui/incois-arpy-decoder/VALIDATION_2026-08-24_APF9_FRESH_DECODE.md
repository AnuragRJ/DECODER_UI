# VALIDATION — Fresh APF9 baseline re-verification (2026-08-24)

**Type:** validation only — **no source, test, config, YAML, decoder logic, or
existing documentation modified.** Fresh decode from raw telemetry with the
current source; comparison against live GDAC fetched 2026-08-24 from
`https://data-argo.ifremer.fr/dac/incois/` (2 922 files: 44 main products +
2 878 mono profiles, full holdings).

This is a **new, standalone record** — not part of the append-only
`IMPLEMENTATION_PROGRESS.md` log, and no existing file was edited.

Environment note (regeneration): deps installed at run time
(`pydantic xarray netCDF4 gsw scipy …`), package used via `PYTHONPATH=src`
(no editable install; repo tree untouched). Decode entry point:
`python scripts/generate_apex_argos_nc.py --raw-root <raw> --registry
config/metadata --output-root <tmp> --wmo <WMO>`.

---

## 1. Workspace / repository setup status

- Workspace ZIP `phase-6-1-6.5.zip` (125 426 250 B, 7 238 files) downloaded
  from the provided Google Drive link and extracted to `argo_workspace/`:
  `argo-decoder-python/` (decoder + docs + tests),
  `Coriolis-data-processing-chain-for-Argo-floats-container/` (MATLAB
  reference + manuals), `ref2902224/` (raw + GDAC for 2902224),
  `apf9_docs/`, `profan/`, `uploads/`. No `.git` metadata in the export.
- Python 3.13.14; dependencies resolved per `pyproject.toml`; suite run with
  `PYTHONPATH=src python -m pytest`. Nothing in the repository was modified.

## 2. Expected baseline — `docs/APF9_FINAL_PARITY_BASELINE.md` (2026-08-21)

342 outputs, 342/342 `NETCDF3_CLASSIC`; mono science 49 008 cells /
0 mismatches / 119 recovered / 0 lost; `_meta.nc` 65/65 variables identical
sequence on 11/11; `_tech.nc` 14/14 names everywhere, 30 classified value
cells; `_Rtraj.nc` PRES 0 mismatches, 2901304 323/323 JULD-exact, MC 0
epoch error (−2 433 282.5 d) on 8 floats, MC 702/703 reception-set diffs;
2902224 cycles 325/326 GDAC-exact on MC 702/703/704; FileChecker 33/44;
**FIXABLE: none remaining**; verdict **ready to FROZEN**.

## 3. Current project stage — `IMPLEMENTATION_PROGRESS.md`

Append-only log (10 559 lines, 40+ phases). Final entry = **“FINAL APF9
PARITY BASELINE (2026-08-21, validation only)”** — fleet validated, verdict
“APF9 core-CTD (1005+1010) ready to be FROZEN; move to the next float
family.” Last *code* phases are the three 2026-08-19 fixes (cycle-collision,
multi-burst mono-JULD anchoring, multi-burst Rtraj union); nothing after
08-21. `APF9_PARITY_STATE.md` (08-19 edition) and `handoff.md` (08-12)
remain consistent with this.

## 4. Fresh-decode results (this run, 2026-08-24)

### 4.1 Decode status and file counts

| WMO | raw source | raw files | nc files | baseline | match |
|---|---|---|---|---|---|
| 2901304 | bundle PTT 102525 | 25 | 24 | 25/24 | ✓ |
| 2901305 | **raw absent in this snapshot** | — | (31 retained) | 81/31 | ⚠ data gap |
| 2901328 | bundle PTT 102507 | 127 | 97 | 127/97 | ✓ |
| 2901339 | bundle PTT 102510 | 73 | 76 | 73/76 | ✓ |
| 2901350 | **raw absent in this snapshot** | — | (72 retained) | 70/72 | ⚠ data gap |
| 2902201 | bundle PTT 152399 | 3 | 7 | 3/7 | ✓ |
| 2902203 | bundle PTT 152398 | 3 | 7 | 3/7 | ✓ |
| 2902206 | bundle PTT 152397 | 3 | 7 | 3/7 | ✓ |
| 2902222 | bundle PTT 152389 | 3 | 7 | 3/7 | ✓ |
| 2902223 | bundle PTT 152382 | 3 | 7 | 3/7 | ✓ |
| 2902224 | `ref2902224/` PTT 152390 | 6 | 7 | 6/7 | ✓ |

- **9/11 decoded fresh, all `status=ok`, counts exactly per baseline.**
- **2901305 (PTT 102526) and 2901350 (PTT 75415): raw telemetry is not in
  this workspace export** (no such PTT directory anywhere in the ZIP;
  only `metadata_migration_output/json/2901305_102526_info.json` exists).
  Fresh decode impossible → classified **DATA/COVERAGE LIMITATION
  (workspace export), not a decoder issue.** Their retained outputs were
  verified instead (§4.3–4.6).
- **NC3:** 239 fresh outputs — 239/239 `NETCDF3_CLASSIC`; retained tree
  336/336 `NETCDF3_CLASSIC`. (Fresh 239 + 103 for the two unavailable
  floats = 342 = baseline total.)

### 4.2 Test suite / lint

- `pytest`: **1 741 passed**, 0 failed, 0 skipped-error — exactly the count
  in the final log entry. `ruff check .`: clean.

### 4.3 Mono-profile science (key: (cycle, direction); PRES/TEMP/PSAL)

| WMO | source | shared | cells | mismatches | recovered | lost |
|---|---|---|---|---|---|---|
| 2901304 | fresh | 20 | 3 510 | 0 | 0 | 0 |
| 2901305 | retained 08-14 | 27 | 4 734 | 0 | 0 | 0 |
| 2901328 | fresh | 92 | 15 264 | 0 | 0 | 0 |
| 2901339 | fresh | 71 | 12 459 | 0 | 0 | 0 |
| 2901350 | retained 08-14 | 67 | 11 745 | 0 | 0 | 0 |
| 2902201 | fresh | 0 | — | — | — | — (no GDAC overlap) |
| 2902203 | fresh | 3 | 350 | 0 | 0 | 0 |
| 2902206 | fresh | 0 | — | — | — | — (no GDAC overlap) |
| 2902222 | fresh | 3 | 525 | 0 | **30** (cyc 329) | 0 |
| 2902223 | fresh | 3 | 525 | 0 | **89** (cyc 328/329) | 0 |
| 2902224 | fresh | 3 | 528 | 0 | 0 | 0 |
| **total** | | | **49 640** | **0** | **119** | **0** |

- **0 mismatches; recovered = exactly the documented 119 (2902222 cyc 329
  ×30; 2902223 cyc 328/329 ×89); 0 lost.** Per-float cells match the
  baseline table exactly for every float except 2901328 (15 264 vs 14 928)
  and 2902224 (528 vs 351): GDAC has *more valid cells today* than at the
  08-21 fetch (delayed-mode/RT republication on the GDAC side) — more cells
  compared, still zero mismatches. Not a decoder-side change.
- Bonus QC re-check (not a headline baseline measure): 280 differing QC
  cells, **the exact count documented** in the Part-2 audit (49 007/49 287),
  same kinds (`9→1` = the recovered levels; `4/3` on GDAC-D-mode files).

### 4.4 `_meta.nc`

- **65/65 variables, identical sequence, on 11/11 floats.**
- Differing fields = exactly the documented set, same per-float
  distribution: `SENSOR_MAKER` 11/11 (approved divergence);
  `START_DATE` 6 (2201/03/06/2222/23/24, sheet gap);
  `PREDEPLOYMENT_CALIB_COEFFICIENT` 3 (2201/03/06, sheet precision);
  `END_MISSION_DATE` 1 (2901328, sheet gap); `END_MISSION_STATUS` 4
  (1339/1350/2201/2206, GDAC `0.0` oddity); `FIRMWARE_VERSION` 2 +
  `MANUAL_VERSION` 1 (zero-padding, expected). (`DATE_CREATION/UPDATE` =
  run stamps.)

### 4.5 `_tech.nc`

- **14/14 names on every float; name set identical to GDAC.**
- Value-exact: 2901304 **322/322**, 2901339 **994/994**, 2901350 **938/938**
  (retained outputs vs today’s GDAC) — all exactly as documented.
- Value mismatches: **30 cells total** — same four classified issues:
  - 1010 `PRESSURE_InternalVacuum_inHg` vs frozen GDAC `-28.009`: **15
    cells** (2203×3, 2206×3, 2222×3, 2223×3, **2224×3**) — NOT FIXABLE
    (approved GDAC divergence). Baseline table said `2224×2`; today GDAC
    also carries cycle 345’s frozen value, giving ×3 — the baseline’s own
    headline (30 cells) is reproduced exactly; sub-table delta is a
    GDAC-side refresh, same class.
  - 1005 vacuum: **7 cells** (2901328×5 incl. cyc51 sentinel −29.767,
    2901305×2) — NOT FIXABLE (documented).
  - `PRESSURE_AirBladder_COUNT`: **6 cells** (2206/361, 2222/328+329,
    2223/329, 2224/325+326, all ±1) — NOT FIXABLE (copy-set).
  - `FLAG_ProfileTermination_hex`: **2 cells** (1305/27 `601`vs`01`;
    1328/85 `1D`vs`01D`) — NOT FIXABLE (copy split / GDAC width).

### 4.6 `_Rtraj.nc` (key: (cycle, MC) — never positional)

- **PRES: 0 mismatches on every comparable float.**
- **2901304: 323 shared (cycle,MC) keys · 0 JULD differences** (baseline:
  323/323 exact — reproduced).
- **MC 0 on 8 floats:** GDAC off by exactly **−2 433 282.5 d** (1950-epoch
  error) — approved GDAC error, not copied (reproduced on all 8).
- **MC 702/703 (2203/2206/2222/2223):** reception-set differences only
  (fix-count and 0.01–0.36 d cells), exactly the documented NOT FIXABLE set;
  convention proven identical by 2901304’s 323/323.
- 2901305/2901328: GDAC legacy v2.2, no `MEASUREMENT_CODE` → not comparable
  (EXPECTED). 2901339/2901350/2902201: no cycle overlap (GDAC Rtraj
  coverage) → DATA/COVERAGE LIMITATION.

### 4.7 2902224 multi-burst MC 702/703/704 (baseline §7)

| cycle | MC702 | MC703 fixes | MC704 |
|---|---|---|---|
| 325 | 2026-01-01T19:24:55 = GDAC exact | **7 = GDAC 7** | JULD 27760.133171 = GDAC identical |
| 326 | 2026-01-11T17:33:00 = GDAC exact | **8 = GDAC 8** | JULD 27770.090093 = GDAC identical |
| 345 | 2026-07-20T21:04:32 | 7 | 2026-07-21T02:40:20 (GDAC Rtraj ends earlier — coverage) |

Mono JULD: cyc325 = GDAC **exact (Δ 0.0 s)**; cyc326 = first-parsed-fix
convention (GDAC mono 23:29 inconsistency documented); cyc345 = GDAC exact.
**Multi-burst fix intact — fully GDAC-exact where GDAC covers.**

### 4.8 `prof.nc`

64/64 variables, same set, on 11/11; **variable order differs from GDAC**
— the single documented FIXABLE (cosmetic) item, deliberately unimplemented.
Unchanged.

## 5. Fresh-vs-retained (`parity_fresh_nc3/`) — regression check

The retained tree is a single run stamped **2026-08-14 09:40**
(`DATE_CREATION` in every file), i.e. it **predates** the 08-17/08-19
changes; the 08-21 final run’s outputs were not retained (regenerable).
All fresh-vs-retained differences are exactly the documented post-08-14
changes, and nothing else:

| difference vs retained | owning documented change | class |
|---|---|---|
| 1010 `_tech.nc` 12→14 params (5 floats) | 1010 VAC/ABP emission (“Part A”, pre-08-17 re-analysis) | EXPECTED (documented fix) |
| 2901328 cycle 0: mono/prof JULD 22521.458→22218.456; Rtraj MC703 13→24 fixes (strict superset, first 13 identical); MC704 22218.99→22521.86 | 2026-08-19 multi-burst union + first-fix anchoring (gate: >1 distinct raw key; cycle 0 spans many date-only pre-launch files) | EXPECTED (documented fix); current output internally coherent (retained MC704 preceded 11 of its own MC703 fixes — impossible ordering) |
| 2902224 outputs absent from retained tree (only `_meta.nc`) | post-08-14 fixes; artifacts removed as regenerable | EXPECTED |

2901304/2901339 and all other cycles of 2901328: **value-identical**
(barring run stamps) to retained. **No unexplained difference → no
regression.**

## 6. Deviations from the documented final baseline

All deviations are GDAC-side data refresh or workspace-export gaps — none
is a decoder-behavior change, none newly fixable:

1. Mono compared cells 49 640 vs 49 008 — GDAC now publishes more valid
   cells (2901328 +336, 2902224 +177); still 0 mismatches. GDAC-side.
2. 1010 vacuum 15 cells vs 14 in the baseline sub-table (2224 cyc 345 now
   filled on GDAC); headline 30 cells reproduced. GDAC-side.
3. 2901305/2901350 not re-decodable here (raw absent) — workspace export
   gap. Their retained outputs still verify perfectly against today’s GDAC
   (science 4 734/0 and 11 745/0; tech 938/938 exact for 2901350).
4. FileChecker not re-runnable (jar absent) — see §7.

## 7. Missing data / dependencies / tooling

| item | status | impact |
|---|---|---|
| Raw telemetry 2901305 (PTT 102526), 2901350 (PTT 75415) | **absent from workspace export** | fresh decode of 2/11 floats impossible (verified via retained outputs instead) |
| GDAC references for 2901304/2901305/2901328/2901350 | absent in-workspace | **mitigated**: fetched live 2026-08-24 from ifremer GDAC |
| FileChecker `ValidateSubmit.jar` (+ Java) | absent; only 10 retained `.filecheck` meta results (all FILE-ACCEPTED) | 33/44 status **not re-verifiable today** |
| GEBCO/WOA reference grids (`--ref`) | absent (never stored in repo, per `docs/BATHYMETRY_SETUP.md`) | TEST004 not exercised (consistent with documented no-bathymetry behavior) |
| `.git` metadata | not in export | code dating via logs/stamps only |

## 8. Verdict

**APF9 remains FROZEN-ready / validated.** Every re-verifiable measure of
the 2026-08-21 final baseline is reproduced exactly by a completely fresh
decode (9/11 floats from raw; 2/11 blocked by a workspace-export data gap,
their retained outputs verifying cleanly): science 0 mismatches with the
same 119 recovered levels, meta 65/65, tech 14/14 with the same classified
cell set, Rtraj PRES/JULD behaviour identical including the 2902224
multi-burst exactness, 1 741/1 741 tests, NC3 everywhere. Remaining
differences are the established NOT FIXABLE / EXPECTED / DATA-LIMITATION
set — **no new decoder defect, no regression, nothing newly fixable.**
The only FIXABLE item stays the deliberately-unimplemented `prof.nc`
variable order (cosmetic, awaiting approval).

---

*Validation only. Source tree unchanged: no src/test/config/YAML/existing-doc
file was modified (verified). Fresh outputs and fetched GDAC kept in `/tmp`
(regenerable); the sole new persistent artifact is this report.*
