# APEX APF9 — GDAC parity: where the project stands

**Current state: 2026-08-19 — FRESH FLEET-WIDE PARITY BASELINE.**
Every number below was measured this session from a **completely fresh
decode of all 11 APF9 floats** (2901304, 2901305, 2901328, 2901339,
2901350, 2902201, 2902203, 2902206, 2902222, 2902223, 2902224) with the
**current source** (post cycle-collision fix, post multi-burst JULD fix)
from raw telemetry (operator bundle + `ref2902224/`), against **current
GDAC files fetched from `https://data-argo.ifremer.fr/dac/incois/` the
same day** (326 files: 44 main products + 282 mono profiles).

**No source or test code was modified for this report.** This document
supersedes earlier editions as the baseline; the investigation reports
remain the evidence base:

- `docs/VACUUM_1010_REANALYSIS.md` — 1010 vacuum `-28.009`.
- `docs/ABP_EXACT_CORIOLIS_VERIFICATION.md` — 1010 ABP ±1.
- `docs/FLAG_PROFILETERMINATION_PARTB.md` — FLAG copy selection.
- `docs/PROFILE_JULD_INVESTIGATION.md` — profile-JULD convention + the
  multi-burst anchor fix.
- `docs/CYCLE_COLLISION_2902224_INVESTIGATION.md` + `docs/FILENAME_SUFFIX_SEMANTICS.md`
  — cycle identity and suffix semantics.

---

## 1. Headline (fresh baseline, 2026-08-19)

| measure | result |
|---|---|
| Floats decoded fresh | **11 / 11** |
| NetCDF files generated | **342**, all NC3 `NETCDF3_CLASSIC` |
| `_meta.nc` | 65/65 variables, identical sequence on 11/11 |
| `_tech.nc` names | 14/14 on every float |
| **Mono science cells compared** | **48 508 · 0 true mismatches** |
| Science cells recovered (ours valid, GDAC fill) | 119 (2902222 cyc329 ×30; 2902223 cyc328/329 ×89) |
| Science cells lost | 0 |
| `_Rtraj.nc` PRES on shared (cycle,MC) | **0 mismatches on all 9 comparable floats** |
| 2901304 `_tech.nc` | 322/322 value-exact |
| FileChecker v3.0.5 | **33/44 FILE-ACCEPTED** (meta/tech/Rtraj on all 11; 11 `_prof.nc` rejected on pre-existing `VERTICAL_SAMPLING_SCHEME`) |

## 2. Remaining mismatches — grouped by issue/parameter

### 2.1 `_meta.nc` fields (7 fields, all previously classified)

| field | floats | ours | GDAC | class |
|---|---|---|---|---|
| `SENSOR_MAKER` (CTD_PRES) | 11/11 | `DRUCK`/`KISTLER` | `SBE` | **NOT FIXABLE — approved GDAC divergence** (FileChecker rejects GDAC, accepts ours; R27/CK_0164; Coriolis requires DRUCK/KISTLER) |
| `START_DATE` | 6 (2201/03/06/2222/23/24) | empty | populated | **NOT FIXABLE with current data** — sheets carry no `start date` column (operator data request) |
| `PREDEPLOYMENT_CALIB_COEFFICIENT` | 3 (2201/03/06) | 3 s.f. | 5 s.f. | **NOT FIXABLE with current data** — sheet precision |
| `FIRMWARE_VERSION` | 2 (1339/50) | `061810` | `61810` | EXPECTED representation (zero-padding) |
| `MANUAL_VERSION` | 1 (2901350) | `031411` | `31411` | EXPECTED representation |
| `END_MISSION_DATE` | 1 (2901328) | empty | `20130605073745` | **NOT FIXABLE with current data** — sheet gap |
| `END_MISSION_STATUS` | 4 (1339/50/2201/2206) | `T` | `0.0` | **NOT FIXABLE — approved GDAC oddity** (numeric 0.0 in status field; INCOIS's own other floats use `T`) |

### 2.2 `_tech.nc` parameters (4 parameters, 30 cells total)

| parameter | cells | detail | class |
|---|---|---|---|
| `PRESSURE_InternalVacuum_inHg` | **22** | 1010: 14 cells (2902203×3, 2206×3, 2222×3, 2223×3, 2224×2) — GDAC `-28.009` (count 6 never transmitted); 1005: 7 cells (2901328×5 `44.655/-29.767` vs GDAC `-25.665`; 2901305×2 `43.776/39.088` vs `43.19/43.776`) | **NOT FIXABLE** (1010: GDAC-side divergence, approved); **NOT FIXABLE** (1005: 6 cells GDAC-implied count absent from telemetry — count 14 ×5, count 251 ×1; 1 cell (2901305/21) copy-selection with no reproducible rule; our modal p9 = best rule 89/117; `docs/VACUUM_1005_INVESTIGATION.md`) |
| `PRESSURE_AirBladder_COUNT` | **6** | 2902206/361, 2902222/328+329, 2902223/329, 2902224/325+326 — all ±1 count; exact-Coriolis round-mean = 6/12 < ours 8/12; no rule reproduces GDAC on our copy set | **NOT FIXABLE** (copy-set; INCOIS reception set unknown) |
| `FLAG_ProfileTermination_hex` | **2** | 2901305/27 `601` vs `01` (genuine 9-vs-8 copy split); 2901328/85 `1D` vs `01D` (identical value 0x001D, GDAC string width) | **NOT FIXABLE** (copy-set swap; GDAC formatting one-off) |
| *(2901304 tech: 322/322 exact; 2901339/2901350: 994/994 and 938/938 exact)* | | | |

### 2.3 `_Rtraj.nc` (all PRES exact; JULD diffs only)

| issue | floats | detail | class |
|---|---|---|---|
| MC 0 (launch) JULD | 8 (1339/50/2201/03/06/2222/23/24) | GDAC off by exactly `-2433282.5` d (1950 epoch) — our MC0 = LAUNCH_DATE | **NOT FIXABLE — approved GDAC error** (do not copy) |
| MC 702/703 profile-fix JULD | 2902203×1, 2206×4, 2222×4, 2223×6 | 0.01–0.36 d; reception-set difference (GDAC times present-or-absent in our raw; convention identical — 2901304 323/323 exact) | **NOT FIXABLE** — reception/copy-set (`docs/RTRAJ_JULD_INVESTIGATION.md`) |
| MC 704 + MC703 (2902224 325/326) | 2 + 9 | multi-burst Rtraj telemetry = richest burst only; GDAC = union of all bursts (MC703 7/8 fixes, MC704 = surfacing last message) | **FIXED 2026-08-19** — generic union of fixes/message-times across bursts (same `raw_keys_by_cycle` gate as the mono-JULD fix); 2902224 cyc325 MC703 7/7 exact + MC704 exact; cyc326 8/8 exact + MC704 exact; no other float changed (`docs/RTRAJ_JULD_INVESTIGATION.md` §6) |
| GDAC legacy v2.2 | 2901305/2901328 | GDAC Rtraj lacks MEASUREMENT_CODE — not comparable | EXPECTED (GDAC not regenerated) |

### 2.4 Profiles (mono science — perfect parity)

- **48 508 cells compared across 8 floats with shared mono profiles:
  0 mismatches.** 119 recovered levels (GDAC fill), 0 lost.
- 2902201/2902206 have **zero** mono overlap with GDAC (GDAC stops at
  350/352; our archive starts 358/359) — coverage, not a defect.
- `prof.nc`: 64/64 variables; **variable order** differs from GDAC on all
  floats (`PROFILE_*_QC` placement, `HISTORY_QCTEST` position) —
  **FIXABLE (cosmetic)**; not yet implemented (needs its own approval).
- `DATA_MODE` R vs D (1005s + early 1010s), `*_ADJUSTED` fill: EXPECTED
  (real-time vs delayed mode; UM §2.2.5).

## 3. Issue register — consolidated classification

| # | Issue | Scope | Class | Confidence |
|---|---|---|---|---|
| 1 | 1010 vacuum `-28.009` | 14 cells | **NOT FIXABLE — approved GDAC divergence** | HIGH |
| 2 | 1005 vacuum | 7 cells (2901328×5, 2901305×2) | **NOT FIXABLE** — 6 cells GDAC-implied count absent from telemetry (14×5, 251×1); 1 cell copy-selection, no reproducible rule (`docs/VACUUM_1005_INVESTIGATION.md`) | HIGH |
| 3 | 1010 ABP ±1 | 6 cells | **NOT FIXABLE** (copy-set; exact-Coriolis worse) | HIGH |
| 4 | FLAG cyc27 / cyc85 | 2 cells | **NOT FIXABLE** (copy swap; width one-off) | HIGH |
| 5 | MC0 JULD | 8 floats | **NOT FIXABLE — approved GDAC error** | HIGH |
| 6 | MC 702/703 JULD | 4 floats (15 cells) | **NOT FIXABLE / open design** (reception-set; needs INCOIS data) | MEDIUM |
| 7 | `SENSOR_MAKER` | 11 floats | **NOT FIXABLE — approved divergence** | HIGH |
| 8 | `START_DATE`/`END_MISSION_DATE`/calib precision | 6/1/3 floats | **NOT FIXABLE with current data** (sheet gaps) | HIGH |
| 9 | `END_MISSION_STATUS` `T` vs `0.0` | 4 floats | **NOT FIXABLE — approved GDAC oddity** | MEDIUM |
| 10 | prof.nc variable order | 11 floats | **FIXABLE (cosmetic, not yet approved/implemented)** | HIGH |
| 11 | `_prof.nc` FileChecker warning | 11 floats | **NOT FIXABLE without a spec decision** (fleet-wide `VERTICAL_SAMPLING_SCHEME`; GDAC's own prof files fail differently) | MEDIUM |

**FIXABLE items:** only #10 (prof.nc variable order) — a presentation
change with no value impact; implementation deliberately not started
(requires approval).

## 4. What must not be changed to chase parity

1. `SENSOR_MAKER` = DRUCK/KISTLER (approved; checker-validated).
2. MC 0 JULD = LAUNCH_DATE (GDAC epoch defect).
3. 1010 vacuum (count 6 never transmitted) and 1010 ABP (no rule).
4. FLAG copy selection and `01D` width.
5. The 119 recovered science levels.
6. `*_ADJUSTED` fill and `DATA_MODE='R'`.
7. The `_tech.nc` 14-name restriction.

## 5. Reproducing this report

```bash
python scripts/generate_apex_argos_nc.py --raw-root <raw> \
  --registry config/metadata --output-root /tmp/fresh --wmo <WMO>
# GDAC: https://data-argo.ifremer.fr/dac/incois/<wmo>/{meta,tech,Rtraj,prof}.nc
#       + profiles/{R,D}<wmo>_NNN.nc for overlap cycles
# FileChecker: java -jar ValidateSubmit.jar -internal-specs -text-result \
#              incois out/ in/
```

**Comparison rule:** key on `(cycle, direction)` / `(cycle, MC)` — never
positional.

---

*Only documentation was modified for this edition. No source, test,
configuration, or generated NC file was changed.*
