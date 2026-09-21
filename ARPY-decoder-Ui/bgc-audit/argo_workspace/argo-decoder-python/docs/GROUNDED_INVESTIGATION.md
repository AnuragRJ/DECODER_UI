# GROUNDED — exhaustive falsification pass

**Date:** 2026-08-13
**Question asked:** before accepting "GROUNDED is not derivable", try once more to falsify that
conclusion. Find either the real derivation or a citable reason it is DAC-side-only.

**Answer: the earlier conclusion was WRONG. GROUNDED *is* derivable.**
The derivation is documented in the Argo DAC Trajectory Cookbook and reproduces INCOIS's
published flags on **2305 / 2315 cycles (99.57 %)** across 8 floats, with all 10 residuals being
cycles for which INCOIS has not published a profile file at all.

---

## 1. Why the earlier negative result was wrong

The prior investigation compared **park pressure** (`MC 290` / `MC 296`, ~1000 dbar) between
GDAC's `Y` and `N` cycles and correctly found no signal. It never compared the **deepest
ascending-profile pressure** against the **programmed profile target**.

| what was compared before | median `Y` | median `N` | separation |
|---|---|---|---|
| `MC290` park PRES, 2901304 | 1005 | 1003 | none (AUC 0.63) |
| `MC296` park mean PRES | 1000 | 1001 | none |

| what should have been compared | max `Y` | min `N` | separation |
|---|---|---|---|
| **max PRES of the ascent profile**, 2901304 | 1899.7 | 1900.2 | **clean** |
| same, 2901339 | 1899.9 | 1900.0 | **clean** |
| same, 2902222 | 1899.9 | 1900.0 | **clean** |

The park phase is at 1000 dbar and is unaffected by a 2000 dbar seabed, so it carries no
grounding signal. The profile phase is where the float hits bottom.

`shallow_water_trap` (0x0002) genuinely is `False` on all `Y` cycles — that check was correct
but was testing the wrong hypothesis. It is a **park-phase** trap, not a profile-phase one.

---

## 2. The citable source

**Argo DAC trajectory cookbook**, v6.1, November 2022 (Scanderbeg, Rannou, Buck, Schmid,
Gilson, Swift), DOI [10.13155/29824](https://doi.org/10.13155/29824), Annex D §5.2 *APEX float
ascending velocity*, p. 161:

> As this information was not stored in the DEP data set, only profiles for which the following
> is true could be used:
> `| deepest bin pressure - PROFILE pressure | < 150 dbar.`
> (these data are in green in the following figures).
> **If `| deepest bin pressure - PROFILE pressure | > 150 dbar`, the cycle can be flagged
> "grounded"** (blue stars) or not (red stars).

Same document, §2.5 *GROUNDED Flags*, p. 129:

> There are two different ways to determine grounding: **1) based on float performance and
> technical data** or 2) based on checks with bathymetry.

So the spec explicitly sanctions a **non-bathymetric, float-performance derivation**, and gives
the APEX-Argos form of it: *the float failed to reach its programmed profile pressure*.

Reference table 20 (NVS `R20`, and Argo User's Manual §3.20) confirms the flag semantics —
`Y` = grounded by float-performance evidence, `B`/`C` = grounded *by bathymetry database*.
**INCOIS publishes `Y`, not `B`.** That alone rules out the bathymetry hypothesis the previous
session spent its effort on: had GEBCO been the method, the correct flag would have been `B`.

---

## 3. Why Coriolis MATLAB says `'U'` and why that misled us

Full decoder source obtained this session (`decArgo_soft/soft/sub/`, absent from the container
repo, cloned from `github.com/euroargodev/Coriolis-data-processing-chain-for-Argo-floats`).

`sub/process_trajectory_data_apx_argos.m:104`:

```matlab
trajNCycleStruct.grounded = 'U';
```

Hardcoded, never reassigned anywhere in that file. Coriolis simply **does not compute**
GROUNDED for APEX Argos. It does compute it for other families:

| file | logic |
|---|---|
| `process_trajectory_data_4_19_25.m:539` | `if a_tabTech(27)==0 -> 'N' else 'Y'` (tech word) |
| `process_trajectory_data_32.m:571` | `a_tabTech1(18)>0`, or a grounding date exists, or surface grounding |
| `process_trajectory_data_apx_apf11_ir.m:1336` | `'N'` unless `a_grounding` non-empty (APF11 logs groundings) |
| `process_trajectory_data_40x.m:223` | `'N'` unless `a_cycleTimeData.groundingDate` exists |
| `set_n_cycle_vs_n_meas_consistency.m:324` | promote to `'Y'` if any `MC 901` row exists |

Every one of those depends on a **grounding field the float telemeters**. APF9/Argos has no such
field (confirmed against APF9 format notes, below), so Coriolis abstains.

**INCOIS is not running the Coriolis decoder for these floats.** Their `_prof.nc` history records
`HISTORY_SOFTWARE = INQC`, `HISTORY_SOFTWARE_RELEASE = V4.0`, `HISTORY_INSTITUTION = IN` — an
in-house chain. So "Coriolis says U" was never evidence about what INCOIS does.

---

## 4. APF9 firmware: confirmed there is NO grounding status bit

Checked the 16-bit `STATUS` word documented in
`decArgo_doc/float_user_manuals/APEX_floats/Argos/20070718_V071807-Apex-User-Manual_APF9A-Ido-071807.FormatNotes.txt`
(data message #1, bytes 7–8), and all 16 APF9A user manuals 2007–2013 (text-extracted and
grepped for `ground`):

```
DeepPrf          0x0001   ShallowWaterTrap 0x0002   Obs25Min         0x0004
PistonFullExt    0x0008   AscentTimeOut    0x0010   TestMsg          0x0020
PreludeMsg       0x0040   PActMsg          0x0080   BadSeqPnt        0x0100
Sbe41PFail       0x0200   Sbe41PtFail      0x0400   Sbe41PtsFail     0x0800
Sbe41PUnreliable 0x1000   AirSysBypass     0x2000
```

**No grounding bit.** The only `ground` hits in the manuals are *electrical* hull ground. The
`FLAG_ProfileTermination_hex` values also fail to separate the classes:

| float | `N` cycles | `Y` cycles |
|---|---|---|
| 2902222 | `01`×163, `05`×1, `801`×56, `901`×3 | `01`×65, `05`×20, `4D`×2, `0D`×1, `801`×27, `805`×1 |
| 2901339 | `01`×107, `801`×55 | `01`×34, `801`×20 |
| 2901304 | `01`×14, `61`×1 | `01`×5 |

So the flag is **not self-reported by the float** — it is DAC-computed from float *performance*,
exactly as the cookbook says.

---

## 5. The rule, and its measured accuracy

```
T = CONFIG_ProfilePressure_dbar          (target profile pressure)
Pmax = max(PRES) over the ascending profile

GROUNDED = 'U'   if the cycle produced no ascent profile levels
         = 'Y'   if Pmax <  T - 100
         = 'N'   otherwise
```

### 5a. Against INCOIS, per float (GDAC's own PRES)

| WMO | cycles | Y | N | U | exact | mismatch |
|---|---|---|---|---|---|---|
| 2901304 | 23 | 5 | 15 | 3 | **23** | 0 |
| 2901339 | 216 | 54 | 162 | 0 | **216** | 0 |
| 2902201 | 348 | 117 | 231 | 0 | **348** | 0 |
| 2902203 | 361 | 76 | 285 | 0 | **361** | 0 |
| 2902206 | 357 | 95 | 262 | 0 | 348 | 9¹ |
| 2902222 | 339 | 116 | 223 | 0 | **339** | 0 |
| 2902223 | 337 | 111 | 226 | 0 | **337** | 0 |
| 2902224 | 334 | 93 | 241 | 0 | 333 | 1¹ |
| **total** | **2315** | | | | **2305 (99.57 %)** | **10** |

¹ Every one of the 10 is a cycle where the rule predicts `U` because no profile exists in
`<wmo>_prof.nc`, while GDAC's Rtraj carries a `Y`/`N`. Verified by direct fetch — 
`profiles/R2902206_353.nc` … `_361.nc` and `R2902224_297.nc` all return **HTTP 404**. INCOIS
holds profile data we cannot see. This is a **data-availability gap, not a rule failure**, and
`U` is the honest output when the profile is absent.

### 5b. Against **our own decoder's** pressures

This is the number that matters — the rule must work on values *we* produce, not GDAC's.

| WMO | cycles we cover | match | mismatch |
|---|---|---|---|
| 2901304 | 20 | **20** | 0 |
| 2902222 | 3 | **3** | 0 |
| 2902223 | 3 | **3** | 0 |
| **total** | **26** | **26 (100 %)** | **0** |

2901304's three `U` cycles (21–23) are also correct: they decode to zero profile levels, so the
rule emits `U` and GDAC has `U`. That is the first time we have matched those three.

### 5c. Fleet-wide, 69 INCOIS APEX floats, 12 518 cycles

Using the target inferred from the data (mode of `N`-cycle `Pmax`, rounded to 100 dbar):

| K | errors | accuracy |
|---|---|---|
| 25 | 453 | 96.38 % |
| 50 | 240 | 98.08 % |
| 75 | 87 | 99.31 % |
| 95 | 79 | 99.37 % |
| **100** | **78** | **99.38 %** |
| 101 | 127 | 98.99 % |
| 150 | 165 | 98.68 % |
| 200 | 171 | 98.63 % |

**K = 100 dbar is the exact optimum**, and the error curve is sharply asymmetric around it
(78 → 127 between K=100 and K=101), which is the signature of a deterministic threshold rather
than a fitted one. 59 of 69 floats are perfect.

The boundary in the raw histogram is absolute — across all floats whose metadata target agrees
with their observed modal depth, **not one cycle** has a deficit in `(90, 100]`:

```
deficit = T - Pmax     N cycles   Y cycles
  [ 80,  90)                  3          0
  [ 90, 100)                  0          0   <-- empty
  [100, 110)                  0         77
```

### 5d. The 10 imperfect floats are all metadata errors, not rule errors

| WMO | target in meta.nc | target implied by the data | errors |
|---|---|---|---|
| 2900335 | 1000 | 3100 | 15/146 |
| 2902174 | 200 | 2000 | 13/404 |
| 2902175 | 200 | 2000 | 13/356 |
| 2900226 | 1000 | 3100 | 11/125 |
| 2900344 | 2000 | 3100 | 10/129 |
| 2900256 | 2000 | 3100 | 7/54 |
| 2900228 | 1000 | 1200 | 6/461 |

The Argo QC manual warns about precisely this for Test 19: *"DACs are reminded to check that
these records are correct; otherwise, profiles will fail or pass this test erroneously."* None
of these 7 floats are ours; all 11 of our APF9 floats have `CONFIG_ProfilePressure_dbar = 2000`
and it agrees with the observed depth.

---

## 6. Independent physical corroboration (not circular)

The rule was derived from the cookbook, then tested. Two checks confirm the `Y` cycles are real
groundings and not a decoding artefact:

1. **Spatial/temporal coherence.** On 2902222 the `Y` cycles with `Pmax` well short of target
   form a continuous track (cycles 19→47) whose depth drifts smoothly — median
   `|ΔPmax|` between `Y` cycles ≤3 apart is **102 dbar**, versus the several-hundred-dbar
   spread expected if the shortfall were random message loss. The float is following a
   shoaling seabed across the Kerguelen Plateau (lat ≈ −53.4, lon 71.5 → 77.4).
2. **Not truncated telemetry.** If `Y` cycles were merely missing their deepest Argos message,
   they would show a bin gap. Measured max deep-bin gap is **~100.6 dbar on both classes**
   (fraction of profiles with a gap > 150 dbar: **0.000** for both `Y` and `N`). The `Y`
   profiles are complete — they genuinely stop shallow.

---

## 7. Implementation (completed 2026-08-13)

Shipped exactly as scoped above. Result on 2901304: `GROUNDED` **0/23 → 23/23**, including the
three `U` cycles.

### Where it lives

| file | change |
|---|---|
| `platforms/apex_argos/trajectory.py` | `GROUNDED_PRESSURE_MARGIN_DBAR = 100.0`, `GROUNDED_YES/NO/UNKNOWN`, `grounded_flag()`; `build_argos_trajectory_records(..., max_ascent_pressure_dbar=)` |
| `platforms/apex_argos/decoder.py` | `FLOAT_FILL_THRESHOLD_DBAR`, `_max_ascent_pressures()`; passes the mapping into the builder |
| `nc/trajectory.py` | `TrajCycle.grounded` docstring only — the default stays `"U"` for platforms with no derivation |

`grounded_flag()` is a pure function of two floats. The target comes from the existing
`config_parameter(meta, "CONFIG_ProfilePressure_dbar")` helper — the same value TEST019 already
uses — so no new metadata plumbing was needed.

### Decisions taken during implementation

- **Pressures are used as decoded — QC flags are *not* applied.** Measured both ways against the
  eight reference floats: raw gives 2 305/2 315, screening out `PRES_QC ∈ {4, 9}` first collapses
  it to **1 816/2 315**. The deep levels of a short cycle are exactly the ones the deepest-pressure
  and grey-list tests flag, so filtering by QC removes the evidence. The question is how deep the
  float went, not how good the sample was.
- **Only `DIRECTION == 'A'` counts.** `GROUNDED` asks whether the float reached its programmed
  *profile* pressure, which is a property of the ascent.
- **Fill (`>= 99999.0`) and non-finite values are dropped**; a cycle left with no usable level is
  omitted from the mapping and reported `U`, never as a 0 dbar cast.
- **Negative provisional cycle keys are skipped** — they are unattributed transmissions, not
  positions in the float's sequence.
- **Strict `<`.** A cycle landing exactly on `target - 100` is `N`.

### Validation

| check | result |
|---|---|
| Full suite | **740 passed** (716 before; +24 new) |
| `ruff check` / `ruff format` | clean, 129 files |
| `mypy --strict src` | clean, 72 source files |
| Mutation testing | **9 mutants, 9 killed** |
| 2901304 vs freshly fetched GDAC | **23/23**, Y×5 N×15 U×3 |
| 2902222 / 2902223 (four-CSV) | **3/3 each** on the cycles we hold |
| Blast radius | A/B of identical code with and only with this change: **`GROUNDED` is the only variable that moves** in `Rtraj`; `tech.nc`, `meta.nc`, `prof.nc`, per-cycle profiles and all QC arrays are byte-identical apart from `DATE_CREATION`/`DATE_UPDATE`/`HISTORY_DATE`/`SCIENTIFIC_CALIB_DATE` |

Mutants killed: margin 100→150; `<`→`<=`; missing target→`N`; missing `Pmax`→`N`; hardcoded 1900
boundary; `DIRECTION` filter accepting `D`; fill not filtered; negative cycles included; builder
reverted to always-`U`.

### Remaining limitations

1. **Single-registry backend emits `U` on every cycle.** `config/registry_apf9.csv` has no
   `CONFIG_ProfilePressure_dbar` column, so the target is unavailable and the rule correctly
   abstains. Confirmed: 2901339 (72 cycles), 2902203, 2902222, 2902223 all report `U` there,
   while the same floats on the four-CSV backend classify correctly. Closing this is a metadata
   task, not a `GROUNDED` task — **do not infer the target from the data to work around it.**
   This caps 2901339 at 0/216 until its metadata moves to the four-CSV backend.
2. **A wrong `CONFIG_ProfilePressure_dbar` produces wrong flags**, exactly as the QC manual warns
   for Test 19. All 11 of our APF9 floats are correct at 2000 dbar; 7 of the 69 fleet-wide floats
   are not (§5d).
3. **Cycles with no decoded profile report `U`.** Where INCOIS holds telemetry we do not, they may
   publish `Y`/`N` where we say `U` — 10 such cycles across the reference floats.
4. **The 100 dbar margin is INCOIS-calibrated**, not an Argo-wide constant (§8).
5. **`B`/`C` (bathymetry-derived) are never emitted.** Out of scope; INCOIS does not use them.

## 8. Caveats to keep on the record

- The 100 dbar constant is **read from the cookbook family** (which states 150 dbar as the
  cutoff used for the ascent-rate study) and **confirmed at 100 by measurement**. The cookbook
  does not state 100 explicitly for the flag itself; it says a cycle *"can be flagged grounded"*
  and leaves the DAC the threshold. 100 is INCOIS's choice, evidenced by 12 518 cycles.
  This should be a named, configurable constant, not a magic number.
- The rule is **INCOIS-calibrated**. A sample of 28 AOML APEX-Argos floats publishes `U` on
  every cycle, so there is no cross-DAC confirmation of the exact constant. Our golden
  reference is INCOIS, so this is the right target, but the constant must not be presented as
  an Argo-wide standard.
- `B`/`C` (bathymetry-derived) remain out of scope and INCOIS does not use them.
- Nothing here justifies retro-fitting the previous GEBCO/TEST004 work — that work stands on
  its own for position-on-land QC and is unrelated.

## 9. Sources

- Argo DAC trajectory cookbook v6.1, DOI 10.13155/29824 — §2.5 GROUNDED Flags (p. 129);
  Annex D §5.2 (p. 161).
- Argo reference table 20 / NVS `R20` — <http://vocab.nerc.ac.uk/collection/R20/current/>
- Argo User's Manual v3.1+ §3.20 — GROUNDED variable definition.
- Argo QC Manual for CTD and Trajectory Data — Test 19, on `CONFIG_ProfilePressure_dbar`
  reliability.
- `euroargodev/Coriolis-data-processing-chain-for-Argo-floats`, `decArgo_soft/soft/sub/` —
  `process_trajectory_data_apx_argos.m`, `process_trajectory_data_4_19_25.m`,
  `process_trajectory_data_32.m`, `process_trajectory_data_40x.m`,
  `process_trajectory_data_apx_apf11_ir.m`, `set_n_cycle_vs_n_meas_consistency.m`,
  `init_measurement_codes.m` (`g_MC_Grounded = 901`).
- APF9A format notes + 16 APEX APF9A user manuals, `decArgo_doc/float_user_manuals/APEX_floats/Argos/`.
- INCOIS GDAC `<wmo>_Rtraj.nc` / `_prof.nc` / `_meta.nc`, 69 floats.
