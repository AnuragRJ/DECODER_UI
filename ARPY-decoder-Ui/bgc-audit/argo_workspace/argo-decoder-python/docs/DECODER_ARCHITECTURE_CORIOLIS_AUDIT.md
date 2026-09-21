# Are we building this decoder in the right direction?

**Short answer: yes — verdict A/B, closer to A.**

The architecture matches the Coriolis processing model on every major axis.
There is **no float-specific logic in the executable code path** (verified:
zero WMO comparisons in `src/`), and no decoder decision is made by looking at
GDAC output. Two things are *misplaced* rather than wrong, and one genuine
bug (C1) is now root-caused precisely.

Audited 2026-08-13 against the full Coriolis MATLAB source
(`euroargodev/Coriolis-data-processing-chain-for-Argo-floats`, cloned this
session — 1 598 files in `decArgo_soft/soft/sub/`) and the Argo manuals.

---

## A. Architectural assessment

**Sound.** The layering is:

```
io/            discover raw files, group by float          generic
domain/        RawFrame, CycleData, QcFlag                 generic
config/        decoder_table.yaml -> (platform, firmware)  generic, table-driven
metadata/      4 loader backends behind one Protocol       generic
platforms/     per-family decoders (registry + can_handle) family-specific
  apex_argos/  frames, profile, engineering, trajectory    APF9/ARGOS
  provor_ir_sbd/                                           PROVOR/SBD
sensors/       CTD -> profile dataset + RTQC invocation    generic
rtqc/          TEST002..019, cross-cycle, bathymetry       generic
derived/       cndc, density, doxy                         generic
nc/            ADMT writers: mono, multi, tech, traj, meta generic
pipeline/      runner, metadata stage, xml report          generic
```

Evidence the layering is real, not aspirational:

| check | result |
|---|---|
| WMO-specific branches in `src/` | **0** (`grep "wmo ==" → 0 matches`) |
| generic packages importing `platforms/` at runtime | **0** (the one import in `nc/technical.py` is `TYPE_CHECKING`-only) |
| decoder decisions taken from GDAC files | **0** — all GDAC mentions are comments recording evidence |
| named constants instead of magic numbers | all 37 audited constants are named and documented |

The plugin registry (`platforms/base.py`: `register_decoder` + `can_handle`)
is the correct generalisation of Coriolis's `g_decArgo_floatTransType` switch
in `decode_argo_2_nc_rt.m:129-160`.

---

## B. Coriolis correspondence

| Coriolis concept | source | our module | faithful? |
|---|---|---|---|
| Transmission-type dispatch (`floatTransType` 1/2/3) | `decode_argo_2_nc_rt.m:129` | `config/models.py: TransmissionType` + `pipeline/runner.py` | **yes** |
| Per-decoder static parameters | `_techParamNames/*.json` (212 files), `init_float_config_*` | `config/decoder_table.yaml` | **yes — and better** (one table vs a file per decoder) |
| Family trajectory builder | **34** `process_trajectory_data_*.m` | `platforms/apex_argos/trajectory.py` | **yes** |
| Shared N_CYCLE record | `get_traj_n_cycle_init_struct.m` | `nc/trajectory.py: TrajCycle` | **yes** — field-for-field concept match |
| Shared profile record | `get_profile_init_struct.m` | `sensors/ctd.py` profile dataset | yes |
| Generic trajectory writer | `create_nc_traj_file_3_1.m` | `nc/trajectory.py: build_trajectory_dataset` | **yes** |
| Family tech extraction | `store_tech_data_for_nc_apx_argos.m` | `nc/technical.py: build_technical_records` | concept yes, **placement wrong** (see C1-arch) |
| Generic tech writer | `create_nc_tech_file_3_1.m` | `nc/technical.py: build_technical_dataset` | yes |
| Measurement codes | `init_measurement_codes.m` (`g_MC_* = 100…903`) | `nc/trajectory.py: TrajMeasurementCode` | yes, values identical |
| RTQC suite | `add_rtqc_to_profile_file.m` | `rtqc/` + `sensors/ctd.py` | yes (coverage below) |
| Test-not-run semantics | `testFlagList(4) = 0` when GEBCO absent (`add_rtqc_to_profile_file.m:498-513`) | `_tests_performed()` omits the bit | **exact semantic match** |
| Argos file splitting | `split_argos_file.m` | `frames.py: split_transmission_text` | **concept yes, algorithm differs — this is C1** |
| Cycle-number determination | `rename_argos_input_file.m:650-895` | `apex_argos/decoder.py` (telemetered id + `np0`) | partial — see D |

### RTQC coverage

Ours: TEST 1,2,3,4,5,6,8,9,11,12,13,14,16,18,19,57.
Coriolis: 1-9,11-16,18,19,21-26,56,57,59-63.

The gap is **BGC and Iridium-only tests** (21-26 = near-surface/in-air,
56/59-63 = DOXY/CHLA/BBP/NITRATE). For a core-Argo CTD ARGOS float our set is
complete except **TEST 7 (regional range)** and **TEST 15 (grey list)**, both
of which need external reference files we do not currently ship. That is a
known gap, not a design error.

---

## C. Important deviations

### C-arch-1 · `CYCLE_MEASUREMENT_TEMPLATE` lives in the generic writer · **P2**

`nc/trajectory.py:101` defines the per-cycle event order. That ordering is an
**APEX/ARGOS mission-shape fact**, not an ADMT fact — Coriolis puts exactly
this knowledge in the 34 family-specific `process_trajectory_data_*.m` files
and keeps `create_nc_traj_file_3_1.m` free of it.

Currently harmless (only `apex_argos/trajectory.py` imports it) but it is the
seam that will break when a second family needs a trajectory: PROVOR has
DEEP_PARK / spy-level codes APEX never emits. **Classification: STRONG
INFERENCE** — the Coriolis file layout is unambiguous, but nothing is broken
today.

### C-arch-2 · `build_technical_records` is APF9 logic in `nc/` · **P2**

`nc/technical.py:488` takes `dict[int, ApexEngineeringData]` and hardcodes 42
APF9 parameter-name strings. Coriolis splits this in two:
`store_tech_data_for_nc_apx_argos.m` (family) → `create_nc_tech_file_3_1.m`
(generic), with the vocabulary loaded per decoder id from
`config/_techParamNames/_tech_param_name_<decid>.json`.

Ours is a *thin writer* by intent (its own docstring says so) but the mapping
from engineering fields to ADMT names is family knowledge. **STRONG
INFERENCE.** Runtime layering is still clean — the import is `TYPE_CHECKING`.

### C-arch-3 · No time-based cycle-number fallback · **P2**

Coriolis has a full fallback ladder in `rename_argos_input_file.m:802-895`:
transmitted id → previous/next known cycle ± `round(Δt / cycleDuration)` →
launch-date + prelude + DPF-duration arithmetic, with a
`MIN_NON_TRANS_DURATION_FOR_NEW_CYCLE = 3 h` rule. We use the transmitted
profile id plus `np0`, with transmission-order recovery only for the
saturated-sentinel case.

This is why a wrong `np0` in the operator sheet shifted three floats by two
cycles undetected (found in the previous session). A time-based cross-check
would have caught it. **SOURCE-CONFIRMED** that Coriolis does more than we do.

### Not a deviation: our missing float-specific hacks

Coriolis contains `if (floatNum == 3901639) cycleNumber = -1;`
(`rename_argos_input_file.m:701`) and a commented-out 48-row hardcoded cycle
table for float 3901663. **We have none of that.** On the specific axis the
user was worried about — accumulating per-float patches — we are *cleaner
than the reference implementation.*

---

## D. APF9 assessment

APF9 is implemented in the right place. Everything family-specific
(`frames.py` message parsing + CRC + redundancy, `profile.py` bit layouts,
`engineering.py` calibrated counts, `trajectory.py` MC template filling) is
inside `platforms/apex_argos/`. Everything generic it uses
(`nc/`, `rtqc/`, `sensors/`, `derived/`) is shared with PROVOR.

Two APF9 behaviours were checked specifically for "special case that should be
generic, or vice versa":

* **`GROUNDED` derivation** — correctly in `platforms/apex_argos/trajectory.py`.
  It depends on `CONFIG_ProfilePressure_dbar` and ascent shape, which are
  float-family facts. Coriolis likewise decides `grounded` inside each
  `process_trajectory_data_*.m`, hardcoding `'U'` for APEX-ARGOS
  (`process_trajectory_data_apx_argos.m:104`). Ours does better than the
  reference here, legitimately (see §E).
* **Cycle splitting** — currently in `platforms/apex_argos/`
  (`frames.split_transmission_text` + `decoder._split_multi_transmission_cycles`).
  Coriolis puts it in the *pre-processing* stage
  (`rename_argos_input_file` → `split_argos_file`), before decoding. Ours runs
  inside the decoder. **This is a defensible difference** — Coriolis physically
  renames files on disk, we work in memory — but see C1 below.

---

## E. Known parity issues — genuine bug vs expected

| issue | classification | severity | evidence |
|---|---|---|---|
| **C1 multi-day ARGOS dumps** | **genuine decoder bug** | **HIGH** | root cause found, below |
| Cycle 0 published (2901328/39/50) | intentional difference | LOW | full 59-level valid profile; GDAC starts at 1 |
| 10 extra levels (2902222/23) | intentional difference | LOW | shared levels bit-identical (max ΔPRES **0.0000**) |
| `GROUNDED` 2902206 cyc360 | **GDAC not justifiable** | LOW | our profile reaches 2000.3 dbar vs 2000 target ⇒ not grounded; GDAC publishes no profile for that cycle |
| TEST004 bit absent (`D7B6E` vs `D7B7E`) | expected | LOW | no GEBCO grid configured; Coriolis clears the same bit at `add_rtqc_to_profile_file.m:506` |
| TEST019 now active fleet-wide | working as intended | — | needs `CONFIG_ProfilePressure_dbar`, now present for all 11 floats |
| QC `4` vs our `1`/`3` | GDAC-specific (delayed mode) | LOW | GDAC comparables are `DATA_MODE='D'` |
| `FIRMWARE_VERSION` `061810` vs `61810` | intentional | LOW | manufacturer `MMDDYY` needs the leading zero |
| `END_MISSION_DATE` 2901328 blank | metadata gap | LOW | not derivable; copying = invented provenance |
| Rtraj `JULD_*` schedule on 1010 floats | symptom of C1 | MEDIUM | resolves when cycles are split correctly |
| Profile `JULD` anchor (C3) | design decision pending | MEDIUM | we use first fix, GDAC uses computed ascent end |

### C1 root cause — precisely located, **not** an architectural flaw

`frames.py:382-388` cuts a burst when a timestamp exceeds a **running maximum**
by > 6 h. The comment explains it was introduced because ARGOS dumps are not
strictly chronological.

Measured on `152397_2026-01-10_2902206_360.txt`:

```
294 message blocks, 262 of 293 steps go BACKWARDS in time
file order  : starts 2026-01-10 12:41  ends 2026-01-10 14:31
actual span : 2026-01-05 13:39 .. 2026-01-10 14:31
running-max cuts found: 0        <-- splitter returns 1 burst
```

The file **begins with the newest pass**, so the high-water mark is saturated
on line 1 and no later line can ever exceed it. All 3 surfacings merge; the
earliest reception then wins `JULD_FIRST_MESSAGE`, which is why every affected
cycle is *early, never late* (2902206 −119 h, 2902222 −67 h, 2902203 −19 h).

**Coriolis's algorithm does not have this failure mode.** `split_argos_file.m:47-51`:

```matlab
diffArgosDataDates = diff(argosDataDate);
firstFileLastDateId = find(diffArgosDataDates == max(diffArgosDataDates));
firstFileLastDate = argosDataDate(firstFileLastDateId);
```

— split at the **largest gap**, then assign each satellite pass by comparing
its **`min(dataDateList)`** against the split date (lines 74-88), i.e. by
*time*, not by file position.

Verified: sorting the timestamps before differencing recovers the correct
bursts on all four test files, and each burst's own telemetered profile id
then decodes independently:

| file | bursts recovered | burst spans | profile ids |
|---|---|---|---|
| 2902206 `_360` | 3 | 01-05, 01-08, **01-10 12:41** | 104, –, **104** |
| 2902222 `_329` | 3 | 01-11, 01-13, **01-14 07:17** | –, **74**, **73** |
| 2902203 `_360` | 2 | 01-04, **01-05 15:43** | –, **104** |
| 2901304 `_2011-02-13` | 2 | 02-13, 02-14 | (already worked) |

The last burst of each now matches GDAC's `JULD_FIRST_MESSAGE` for the named
cycle (2902206 → 2026-01-10 12:41 ✓, 2902203 → 2026-01-05 ✓). Note 2902222
carries **two different profile ids (74 and 73)** in one file — proof these
are genuinely separate surfacings, decided from telemetry alone.

**Verdict: C1 is an isolated algorithmic bug in one function, not a symptom of
a deeper architectural problem.** The surrounding design (split → per-burst
decode → telemetered id → cycle) is exactly Coriolis's. Only the gap-detection
rule is wrong.

---

## F. Recommended action

### P0 — architectural/scientific issues that must be fixed first
**None.** No P0 found.

### P1 — genuine decoder bugs
1. ~~**C1: make burst detection time-ordered.**~~ **DONE 2026-08-13.** Both
   halves fixed (time-sorted grouping *and* time-based assignment of the
   file's cycle number). Mean |Δ| on `JULD_FIRST_MESSAGE` 20.2 h → 2.8 h;
   see `APF9_PARITY_STATE.md` §5 C1. Original recommendation retained below.

   **C1: make burst detection time-ordered.** Sort the reception timestamps
   before differencing (or cluster on sorted times), mirroring
   `split_argos_file.m`. Assign each burst by its own time span and let each
   burst's telemetered profile id set its cycle. Do **not** keep the
   positional "first burst gets the file's name" rule.

### P2 — improvements / refactoring (not urgent, do not block)
2. Move `CYCLE_MEASUREMENT_TEMPLATE` into `platforms/apex_argos/` (C-arch-1).
3. Move the engineering→ADMT name mapping out of `nc/technical.py` into the
   platform package, or make it table-driven per decoder id as Coriolis does
   with `_techParamNames/*.json` (C-arch-2).
4. Add a time-based cycle-number cross-check (`round(Δt / cycleDuration)`) as
   a *validator that warns*, following `rename_argos_input_file.m:838-876`.
   This would have caught the `np0` sign error automatically (C-arch-3).
5. Decide the C3 profile-`JULD` anchor question deliberately.

### P3 — acceptable, do not change
TEST004-not-run without a grid; `FIRMWARE_VERSION` zero-padding; real-time QC
severity vs delayed-mode `4`; cycle 0; extra recovered levels; `GROUNDED` on
2902206 cyc360; blank `END_MISSION_DATE`.

---

## G. What NOT to change

1. **Extra recovered levels** (2902222 cyc329, 2902223 cyc328). Every shared
   level is bit-identical; the extras are real CRC-valid measurements GDAC
   left as fill. Discarding good data to match a fill value is a regression.
2. **Cycle 0** on 2901328/2901339/2901350 — a complete, physically sound
   profile (2901339: P 3.9–2000.6, T 3.204–26.561, S 34.856–36.551).
3. **`GROUNDED` = `N` on 2902206 cycle 360.** Provable from our own decoded
   pressure. GDAC's `Y` is not justifiable from telemetry we can see.
4. **Emitting `GROUNDED` at all for APEX-ARGOS.** Coriolis hardcodes `'U'`
   (`process_trajectory_data_apx_argos.m:104`) because it never implemented
   the derivation — that is an *absence*, not a prohibition. The DAC
   Trajectory Cookbook §2.5 explicitly sanctions the float-performance route,
   and reference table 20 reserves `B`/`C` for the bathymetry route, which is
   why INCOIS's `Y`/`N` confirms the method. Keep ours.
5. **TEST004 reported as not-run when no grid is configured** — identical to
   Coriolis clearing `testFlagList(4)`.
6. **Zero float-specific branches.** Coriolis has `if floatNum == 3901639`;
   we must not start down that road to close parity.
7. **Never populate metadata from GDAC.** Launch dates were repaired from
   in-repo sources and only *cross-checked* against GDAC.

---

## Answer to the question that was actually asked

> "Are we building this Python Argo decoder in the right direction, or are we
> gradually patching it into something that only happens to match GDAC?"

**Right direction.** The evidence against "patching toward GDAC":

* zero WMO-specific branches in executable code (Coriolis itself has some);
* zero decoder decisions derived from GDAC files;
* every RTQC constant traceable to the QC Manual, not to a fitted parity number;
* the three most recent "differences" (cycle 0, extra levels, GROUNDED on
  2902206) were each resolved **in favour of the telemetry and against GDAC** —
  which is the opposite of parity-chasing;
* the one genuine bug (C1) was found by reasoning about what an ARGOS dump
  *is*, and its fix is confirmed by Coriolis's own source.

The two placement issues (C-arch-1, C-arch-2) are the kind of drift worth
correcting before a third platform family lands, but neither is causing wrong
science today.

**Next implementation task: ~~C1~~ — done 2026-08-13. The P2 items in §F remain.**

---

## Verification log

* Coriolis source: cloned `euroargodev/Coriolis-data-processing-chain-for-Argo-floats`;
  read `split_argos_file.m`, `rename_argos_input_file.m`, `decode_argo_2_nc_rt.m`,
  `add_rtqc_to_profile_file.m`, `get_traj_n_cycle_init_struct.m`,
  `get_profile_init_struct.m`, `init_measurement_codes.m`,
  `process_trajectory_data_apx_argos.m`, `get_nc_tech_parameters_json.m`;
  counted 34 `process_trajectory_data_*`, 212 `_techParamNames` files.
* Our code: full module inventory (72 files), import-direction check,
  WMO-branch grep, constant audit (37 constants).
* Raw telemetry: re-parsed the three failing 2026 dumps plus
  `102525_2011-02-13.txt`; measured backward-step counts and gap structure.
* GDAC: fresh `_Rtraj.nc` for 2902206/2902222/2902203 to confirm expected
  burst boundaries.
* No code was modified during this audit.
