# How the cycle number is determined

## Short answer

It is **telemetered**, not computed — the APF9 sends a profile-id counter in
message 1 of every transmission. But that counter is 8-bit, it saturates on
the first transmission after deployment, and it does not survive a missed
cycle, so both Coriolis and we treat it as *primary evidence to be validated
against time*, not as gospel.

---

## 1. What the satellite data actually contains

The profile id is a real field in the frame, read at a fixed bit offset in
message 1 (`profile_number_field_index` in the layout table). Decoded
straight from the raw ARGOS hex:

| WMO 2901304 (decoder 1005) | id | WMO 2902222 (decoder 1010) | id |
|---|---|---|---|
| `102525_2010-11-30.txt` | **16** | `..._2902222_327.txt` | 71 |
| `102525_2010-12-15.txt` | **16** | `..._2902222_328.txt` | 72 |
| `102525_2011-02-13.txt` | **16** | `..._2902222_329.txt` | 73 |
| `102525_2011-02-24.txt` | 2 | | |
| `102525_2011-03-06.txt` | 3 | | |

Two things are visible immediately:

* **2902222 sends 71, 72, 73 for cycles 327, 328, 329.** The counter is 8-bit
  and has rolled once: `327 = 71 + 256`.
* **2901304's first three files all report 16.** That is the saturated
  sentinel the APF9 sends before its first real profile — the
  `profile_id_overflow` status bit is set alongside it. Publishing 16 as a
  cycle number would be wrong three times over.

So the raw id needs three corrections: the **roll-over**, the **sentinel**,
and a **deployment offset** (`np0`) when the archive starts before cycle 1.

---

## 2. How Coriolis does it

From `decArgo_soft/soft/util/move_and_rename_apx_argos_files.m` — the stage
that assigns a cycle number to each ARGOS file before decoding.

**Step 1 — decode the id from telemetry, with a redundancy check.**

```matlab
[cycleNumber, cycleNumberCount] = decode_apex_cycle_number( ...
   argosFileName, floatDecId, floatArgosId, checkTestMsg);
```

`cycleNumberCount` is how many copies agreed. The number is only trusted when
`cycleNumberCount > 1` — a single unconfirmed copy is set aside.

**Step 2 — unwrap the 8-bit counter against the previous cycle.**

```matlab
if (cycleNumberCount > 1)
   if (~isempty(tabCycleNumber))
      idPrevCycle = find(tabLastMsgDate < firstArgosMsgDate);
      if (~isempty(idPrevCycle))
         idPrevCycle = idPrevCycle(end);
         while (cycleNumber < tabCycleNumber(idPrevCycle))
            cycleNumber = cycleNumber + 256;
         end
      end
   end
```

Note what this is: `+256` is applied **only while the decoded id is lower than
the previous cycle already assigned**. It is a monotonicity repair driven by
the float's own history, *never* a constant added to every cycle.

**Step 3 — for files whose id was not trustworthy, infer from elapsed time.**

```matlab
nbCycles = round((lastArgosMsgDate - tabLastMsgDate(idPrevCycle))*24/cycleDuration);
if ((nbCycles == 0) && (gap*24 >= MIN_NON_TRANS_DURATION_FOR_NEW_CYCLE))
   nbCycles = 1;   % a long silence means a new cycle even if timing says 0
end
cycleNumber = prevNum + nbCycles;
```

and, when there is no neighbour at all, from launch metadata:

```matlab
firstProfileEndDate = launchDate + preludeDuration/24 + dpfFirstDeepCycleDuration/24;
cycleNumber = round((firstArgosMsgDate - firstProfileEndDate)*24/cycleDuration) + 1;
```

with explicit handling of the DPF (deep-profile-first) cycle 0 / cycle 1
ambiguity.

**Step 4 — cross-check and warn on disagreement.**

```matlab
if ((remainingFileCycleNumber(idFile) ~= -1) && (remainingFileCycleNumber(idFile) ~= cycleNumber))
   fprintf('WARNING: float #%d: computed cycle number (=%d) differs from decoded one (=%d)...
```

So Coriolis uses **telemetry first, time as the fallback, and compares the
two** — with a hardcoded per-float escape hatch (`if a_floatNum == 3901639`)
where even that fails.

---

## 3. How we do it

The same shape, with the roll-over derived rather than repaired:

| step | Coriolis | ours |
|---|---|---|
| read id from message 1 | `decode_apex_cycle_number` | `_decode_header` → `profile_number` |
| redundancy | `cycleNumberCount > 1` | `select_redundant_messages` + per-byte majority |
| sentinel (id 16) | `checkTestMsg` | `profile_id_overflow` bit → `_resolve_sentinel_cycles` |
| roll-over | `while (cycle < prev) cycle += 256` | `cycle_number_wrap_for(elapsed, cycle_length)` |
| deployment offset | float metadata | `profile_count_offset` (`np0`) in the registry |
| time fallback | `round(Δt / cycleDuration)` | not implemented — see gap below |

`cycle = profile_id + wrap + np0`, where

```python
completed_cycles = elapsed_hours / cycle_length_hours
wraps = int(completed_cycles // counter_modulus)  # counter_modulus = 256
```

This was the subject of the last fix. The wrap used to be a constant `256` on
the 1010 layout, which mislabelled WMO 2901328 as cycles 257–355 against
GDAC's 1–98. Deriving it from elapsed deployment time fixes that float and
every future one still inside its first counter period.

**Where we are weaker than Coriolis:** we have no time-based fallback when the
telemetered id is unreadable, and no explicit DPF cycle-0/1 disambiguation.
Coriolis can number a file with a corrupt message 1; we cannot.

---

## 4. The 480 h question — it is GDAC, and here is the proof

Your instinct that GDAC is unlikely to be wrong is the right default. In this
one case the file is internally inconsistent, and it can be shown without any
reference to our decoder.

**Only the modelled schedule steps at 480 h. The observed telemetry does not:**

| field in GDAC's own `2901304_Rtraj.nc` | step per cycle |
|---|---|
| `JULD_DESCENT_START` (modelled) | **480.0 h** |
| `JULD_FIRST_MESSAGE` (observed) | 238–241 h |
| `CONFIG_CycleTime_hours` (configured) | **240 h** |

23 cycles span 220.1 days → **240.1 h measured**, matching the configuration
to within 0.1 h. The 480 h chain is exactly double, and it disagrees with the
same file's own observations.

**It produces three impossibilities inside that one file:**

1. `JULD_DESCENT_START` lands **after** `JULD_ASCENT_END` on **21 of 23
   cycles** — the float starts descending after it has finished ascending:

   ```
   cyc 4  DESCENT_START 2011-03-26 09:12   ASCENT_END 2011-03-16 01:57   (+247 h)
   cyc 21 DESCENT_START 2012-02-29 09:12   ASCENT_END 2011-09-02 05:04   (+4300 h)
   ```

2. Cycle 23's `JULD_TRANSMISSION_END` is **2012-04-29**, while its own
   `JULD_LAST_MESSAGE` is **2011-09-22** — transmission ends **220 days**
   after the last message received.

3. The modelled chain runs to April 2012; the float's last actual
   transmission is September 2011.

The observed fields (`FIRST_MESSAGE`, `LAST_MESSAGE`, `ASCENT_END`) are all
consistent and we match them. It is only the *predicted* schedule chain that
doubles.

**Most likely cause:** the schedule was propagated with a cycle length of
480 h — plausibly `DownTime + UpTime` double-counted, or a 240 h cycle applied
twice per cycle — while `CONFIG_CycleTime_hours` stayed 240.

**Our position:** we model the schedule at the configured and observed 240 h
and deliberately do not reproduce the 480 h chain. This is recorded as "a GDAC
defect we decline to copy" rather than a gap on our side, and it is the reason
some `N_CYCLE` schedule cells will never match for this float.

### Checked across the fleet: 2901304 is the only affected float

All 11 INCOIS APEX floats' `_Rtraj.nc` fetched from GDAC and measured:

| WMO | fmt | cycles | `DESCENT_START` step | `FIRST_MESSAGE` step | ratio |
|---|---|---|---|---|---|
| **2901304** | 3.1 | 23 | **480.0 h** | 240.5 h | **2.00** |
| 2901339 | 3.1 | 216 | 240.0 h | 239.8 h | 1.00 |
| 2901350 | 3.1 | 192 | 240.0 h | 240.0 h | 1.00 |
| 2902201 | 3.1 | 348 | 240.0 h | 239.8 h | 1.00 |
| 2902203 | 3.1 | 361 | 240.0 h | 240.1 h | 1.00 |
| 2902206 | 3.1 | 357 | 240.0 h | 239.9 h | 1.00 |
| 2902222 | 3.1 | 339 | 240.0 h | 239.9 h | 1.00 |
| 2902223 | 3.1 | 337 | 240.0 h | 240.0 h | 1.00 |
| 2902224 | 3.1 | 334 | 240.0 h | 240.0 h | 1.00 |

(2901305 and 2901328 are format 2.2 with no `N_CYCLE` block, so they cannot
carry the chain at all.)

The impossibility counts are just as stark:

| WMO | `DESCENT_START` after `ASCENT_END` | `TRANSMISSION_END` > 1 d after `LAST_MESSAGE` |
|---|---|---|
| **2901304** | **21 / 23** | **22 / 23** |
| all 8 others | **0** | **0** |

**So this is a single-file defect, not a GDAC-wide characteristic.** The
earlier caveat is resolved: your instinct that GDAC is generally right holds —
8 of 9 comparable floats are exactly 240.0 h.

### The precise mechanism

The chain *rule* is applied correctly on 2901304 — `DESCENT_START(n+1)` equals
`TRANSMISSION_END(n)` to 0.00 h on every cycle. What is wrong is the
**within-cycle span**:

| | 2901304 | the 8 healthy floats |
|---|---|---|
| `DESCENT_START` → `TRANSMISSION_END` | **480.0 h** | 240.0 h |
| `PARK_START` → `PARK_END` | **456.3 h** | 213–219 h |

Both spans are almost exactly doubled (456.3 ≈ 2 × 222 h `DownTime`, 480 =
2 × 240). The float's configuration is *identical* to the healthy ones —
`CONFIG_CycleTime_hours = 240`, `CONFIG_DownTime_hours = 222`,
`CONFIG_ParkTime_hours = 222` — so the metadata is not the source. The
schedule was propagated with each interval counted twice.

A likely contributing detail: 2901304's `_Rtraj.nc` has an **empty
`DATE_CREATION`** and the oldest `DATE_UPDATE` of the fleet (2015-10-14),
while every other v3.1 file was regenerated in 2016 or later. This looks like
an early-generation artefact that was never reprocessed.

### What our decoder produces

| | median `DS`→`TE` | `DS` after `AE` |
|---|---|---|
| ours, 2901304 | **240.0 h** | **0 / 23** |
| GDAC, 2901304 | 480.0 h | 21 / 23 |

We match the configuration, the float's own observed telemetry, and the eight
healthy floats. We deliberately do not reproduce the doubled chain, and the
resulting `N_CYCLE` schedule differences on this one float are expected.

---

## 5. Failure modes and what protects against each

| failure | symptom | protection |
|---|---|---|
| 8-bit roll-over | cycles off by exactly 256 | wrap derived from elapsed time; `selfcheck` `cycle_epoch` |
| saturated id 16 | pre-deployment file numbered as a real cycle | `profile_id_overflow` bit → withheld |
| missed cycle | id jumps, times do not | Coriolis: time fallback. Ours: **gap** |
| corrupt message 1 | no id at all | Coriolis: time fallback. Ours: **gap** |
| wrong `np0` | every cycle off by a constant | `selfcheck` `cycle_epoch` |

The `cycle_epoch` check in `scripts/selfcheck_output.py` catches the constant-
offset class with no reference file: extrapolate the observed cycle/time line
back to cycle 0 and it must land near the launch date. On the broken 2901328
decode it reported an implied deployment of 2008-02-25 against a launch of
2011-08-29.
