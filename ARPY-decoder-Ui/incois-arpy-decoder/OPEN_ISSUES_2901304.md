# WMO 2901304 — open GDAC parity issues

Re-measured **2026-08-13** against a freshly fetched INCOIS GDAC tree.
"Ours" is the user's **local Windows decode against the real
GEBCO_2026 grid** (7,466,018,396 bytes), not a sandbox synthetic, and it
now includes the `GROUNDED` derivation. NetCDF reads used
`set_auto_maskandscale(False)` so `_FillValue` char fields are not turned
into `'0'` by masking.

> **Tolerance correction (2026-08-13).** The two `Rtraj` rows in the
> previous scoreboard were labelled "1 ms tol" but had actually been
> measured at **1 minute**. Re-running the old comparison at a true 1 ms
> reproduces neither figure; at 1 minute it reproduces both exactly
> (`823 − 20` GROUNDED cells now fixed = the 803 previously recorded).
> The table below therefore states **both** tolerances explicitly. No
> decoder behaviour changed — only the honesty of the label.

```
raw:  phase4_reference/raw/raw-files   (102525/, 25 files)
ours: python scripts/generate_apex_argos_nc.py `
        --raw-root phase4_reference\raw\raw-files `
        --registry config\metadata `
        --output-root output\local_2901304 `
        --ref argo-ref --wmo 2901304        # argo-ref\gebco.nc -> GEBCO_2026.nc
gdac: https://data-argo.ifremer.fr/dac/incois/2901304/
      2901304_{meta,tech,Rtraj}.nc + D2901304_001..020.nc
```

**TEST004 confirmed live on the real grid: bit 4 set on 20/20 cycles.**
The sandbox reproduced the Windows output exactly — QCP$ identical on
20/20 cycles — so the entry point behaves the same on both platforms.

Science is **exact**. Every remaining difference is a timestamp, a
real-time vs delayed-mode flag, a GDAC defect we decline to copy, or a
value that is not in the CRC-valid telemetry.

---

## Scoreboard

| file | metric | result |
|---|---|---|
| `meta.nc` | variables identical | **63 / 65** |
| `tech.nc` | rows / cycle+name order | **322 / 322, order identical** |
| `tech.nc` | values identical | **321 / 322** |
| `Rtraj.nc` | N_MEASUREMENT / N_CYCLE | **536 / 536**, **23 / 23** |
| `Rtraj.nc` | row keys (cycle, MC) and their order | **536 / 536 identical** |
| `Rtraj.nc` | N_MEAS JULD, 1 min tol | 472 / 536 (88.1 %) |
| `Rtraj.nc` | N_MEAS JULD, true 1 ms tol | 419 / 536 (78.2 %) |
| `Rtraj.nc` | N_CYCLE cells, 1 min JULD tol | **823 / 920 (89.5 %)** ← was 803 |
| `Rtraj.nc` | N_CYCLE cells, true 1 ms JULD tol | 774 / 920 (84.1 %) |
| `Rtraj.nc` | `GROUNDED` | **23 / 23** — derivation implemented 2026-08-13 |
| profiles | science levels vs GDAC | **1170 / 1170 (100 %)** |
| profiles | science cells (PRES+TEMP+PSAL) | **3510 / 3510 (100 %)** |
| profiles | QC cells vs GDAC D-files | 3412 / 3510 (97.21 %) |
| profiles | **`QCP$` mask** | **19 / 20 exact** |
| profiles | `QCF$` mask | 18 / 20 exact |
| profiles | `POSITION_QC` | **20 / 20** — TEST004 flagged no ocean position as land |
| profiles | JULD exact | 16 / 20 |

Closed since the previous edition of this file: **M3** `END_MISSION_DATE`,
**R8.2** `GROUNDED` encoding (`U` instead of an invalid fill/`'0'`),
**R8.1 `GROUNDED` Y/N — now fully closed at 23 / 23**, and
**the `QCP$` mask gap** — see below.

### `QCP$` closed by TEST004

Before the GEBCO slice we emitted `D7B6E` on every cycle: the INCOIS mask
minus bit 4. With the grid configured we emit `D7B7E`, matching GDAC
exactly on **19 of 20** cycles.

| cycle | ours | GDAC | match |
|---|---|---|---|
| 1 | `87B5E` | `C7B7E` | no |
| 2–20 | **`D7B7E`** | `D7B7E` | **yes** |

Cycle 1 is a correct disagreement, not a gap: it has no predecessor, so
the cross-cycle tests (5, 16, 18) genuinely cannot run and their bits are
properly absent. Claiming them would be false provenance.

Without `--ref` the mask reverts to `D7B6E`, which is also correct — an
unavailable grid must report TEST004 as *not run*, never as passed.

### Verified on the user's real GEBCO run, 2026-08-13

The bundle decoded on Windows with `--ref argo-ref` (hardlinked to the
7.4 GB `GEBCO_2026.nc`) was re-diffed cell by cell against a GDAC tree
fetched the same day. Two facts worth recording:

* **`GROUNDED` is 23 / 23 on the real grid**, cycle for cycle — `Y` on
  1, 4, 11, 17, 19; `N` on the other fifteen; `U` on 21–23. The
  derivation is *not* bathymetric, so this is confirmation it survives a
  real end-to-end run, not evidence that GEBCO contributed to it.
* **The GEBCO build and a sandbox build without `--ref` produce
  byte-identical `Rtraj.nc`** apart from `DATE_CREATION` / `DATE_UPDATE`.
  Bathymetry touches the QC masks only, exactly as designed; it does not
  leak into the trajectory.

Everything in the scoreboard above is from that run.

---

## `meta.nc` — 2 open, neither actionable

65 variables both sides; same dimensions (`N_CONFIG_PARAM=14`, `N_PARAM=3`).

| # | variable | ours | GDAC | class | fix |
|---|---|---|---|---|---|
| M1 | `DATE_CREATION` | run time | `20120831102309` | expected | none — correct for a new file |
| M2 | `DATE_UPDATE` | run time | `20161216095027` | expected | none — correct for a new file |
| M3 | `END_MISSION_DATE` | `20110922051440` | `20110922051440` | **closed** | four-CSV column |
| — | `END_MISSION_STATUS` | `T` | `T` | closed | already was |
| — | `LAUNCH_DATE` | `20110213075000` | same | closed | |
| — | `START_DATE` | `20110214021223` | same | closed | |
| — | `FIRMWARE_VERSION` | `020811` | same | closed | |
| — | `MANUAL_VERSION` | `061810` | same | closed | |

Ceiling: **63 / 65**. The two remaining fields *should* differ.

---

## `tech.nc` — 1 open, unreachable

322 rows, same `(cycle, name)` order, cycles 1–23 both sides.

| # | cell | ours | GDAC | class |
|---|---|---|---|---|
| T1 | cycle 20 `FLAG_ProfileTermination_hex` | `01` | `61` | **unreachable** |

Re-decoded `102525_2011-08-23.txt`. The 10 CRC-valid message-1 copies
split **6× `0x0601`** / **4× `0x0001`**. `0x0061` occurs at **no byte
offset** of any CRC-valid copy.

Whole-frame selection (the status word is deliberately excluded from
per-byte majority) emits `0x0001` → `"01"`. Majority-of-status would
emit `"601"`, which is still not GDAC's `"61"`. The rest of this float's
GDAC flags (`01`, `4615`, `615`) are the packed hex of a STATUS word
that *is* in the telemetry. `"61"` is not.

**Do not fabricate `61`.**

Everything else: 321 / 322 values identical.

---

## `Rtraj.nc`

Same measurement-code multiset (536 rows, 23 cycles, 102 variables).
Every remaining difference is a **timestamp** or a **flag**, never a
missing/extra measurement and never a science value.

### N_MEASUREMENT — by measurement code

JULD compared as a bag per `(cycle, MC)`, 1 ms tolerance:

Re-measured 2026-08-13 at a **true 1 ms** tolerance (the previous edition
of this table used 1 min under a "1 ms" label — see the note at the top):

| # | MC | exact @1 ms | differ | class |
|---|---|---|---|---|
| R1 | 290, 296 | 0 / 46 | 46 | **GDAC 480 h defect** — do not copy |
| R2 | 0 | 0 / 1 | 1 | GDAC astronomical JD — do not copy |
| R3 | 702 | 13 / 23 | 10 | ours earlier / extra telemetry (see R6) |
| R4 | 600, 700 | 2 / 46 | 44 | ≤ **50 s**; not a decoder bug (below) |
| R5 | 703 | 220 / 236 | 16 | all sub-minute; ours better ordered |
| — | 100, 250, 300, 400, 500, 800, 903 | 161 / 161 | 0 | closed |
| — | 704 | 23 / 23 | 0 | closed |

Total 419 / 536 at 1 ms, 472 / 536 at 1 min. The 53-row difference
between the two is entirely R4 (MC 600/700) plus the sub-minute tail of
R5 — i.e. rows already classified below as reference-instant noise, not
new failures.

**R1 — MC 290/296 inherit the 480 h chain.** Our park timestamps step
240.0 h; GDAC's step **480.0 h**. PRES/TEMP/PSAL on those rows are
byte-identical. Confirmed fleet-wide: 2901304 is the only INCOIS APF9
file with a doubled chain. We decline to reproduce it.

**R2 — MC 0 holds an astronomical Julian Day.** GDAC `2455605.826`;
ours `22323.326` = 2011-02-13 07:50 (launch). Offset is exactly
`2433282.5` (1950 epoch as an astronomical JD). Fleet-wide, inert
(`CYCLE_NUMBER = -1`). We keep the spec-conformant value.

**R4 — MC 600/700 differ by at most 50.075 s** (median **0.0 s**).
Both sides use `TST = EPOCH + TINIT`, `AET = TST − 10 min` (the two
codes move together). On every cycle checked, **all CRC-valid message-2
copies agree** on `(EPOCH, TINIT)`. Cycle 16 matches GDAC exactly.
GDAC's TST often has a fractional second (cycle 3 `…12.075 s`, cycle 20
`…23.719 s`) that an integer UNIX `EPOCH` plus an integer minute
`TINIT` cannot produce. DAC reference-instant / interpolation
convention. **Not ours to "fix".**

**R5 — MC 703 is effectively identical.** 236 fixes both sides. Sorted
`(JULD, lat, lon)` triples differ on at most 2 rows by ~20 µs. **Our
block is time-ascending on every cycle; GDAC's is not** (cycles 6, 14,
16, 17, 21). Do not round to hide that.

### N_CYCLE — 774 / 920 at a true 1 ms, 823 / 920 at 1 min

(Was 754 / 920 before the `GROUNDED` derivation landed; the +20 is
exactly the twenty classifiable cycles of R8.)

| # | field | cells | class |
|---|---|---|---|
| R1 | `JULD_PARK_END` / `JULD_TRANSMISSION_END` | 0 / 23 each | **GDAC 480 h** |
| R1 | `JULD_DESCENT_START` / `JULD_PARK_START` | 0 / 23 each | **GDAC 480 h** |
| R4 | `JULD_ASCENT_END` / `JULD_TRANSMISSION_START` | 1 / 23 each @1 ms; max diff **50.1 s** | not a bug |
| R6 | `JULD_FIRST_MESSAGE` | 13 / 23 within 0.01 s; **10 real** | ours earlier or extra telemetry |
| R7 | `DATA_MODE` | **21 / 23** | we `R`; GDAC `A` on cycles 4 and 5 |
| R8 | `GROUNDED` | **23 / 23** | **closed** — performance-derived |
| — | all `*_STATUS`, `CLOCK_OFFSET`, park-pressure, mission index | 23 / 23 | closed |
| — | `JULD_FIRST_LOCATION` / `LAST_MESSAGE` / `LAST_LOCATION` | 23 / 23 at 1 ms | float noise only |

**R6 — `JULD_FIRST_MESSAGE`, 10 cycles.** Largest gaps: cycle 7
**−5486 s**, cycle 6 **−3650 s**, cycle 8 **−2079 s**, cycle 3
**−1748 s**, cycle 21 **−674 s** (ours earlier). Verified in the raw
file: we ingest CRC-valid frames GDAC did not. More data, not wrong
data. Also explains R3 (MC 702). A few cycles differ by 1–24 s the
other way (13, 15, 17, 18, 23) — same class as R4, not a missing frame.

**R7 — `DATA_MODE` on cycles 4 and 5.** We write `R`, GDAC writes `A`.
Delayed-mode adjustment. A real-time decoder must emit `R`.

**R8 — `GROUNDED`. CLOSED 2026-08-13 at 23 / 23** (`Y`×5, `N`×15, `U`×3,
cycle for cycle against freshly fetched GDAC).

> **The 2026-08-12 entry below is SUPERSEDED.** It concluded `Y`/`N` was
> "not derivable". That conclusion was **wrong**, and it was wrong for a
> specific, instructive reason: it measured the **park** phase (MC 290 /
> 296, ~1000 dbar) and never the **ascending profile** against the
> programmed profile target. A 1000 dbar park cannot feel a 2000 dbar
> seabed, so of course no signal was there. The profile phase separates
> the classes perfectly. Kept in full, unedited, as the record of the
> error.
>
> *Superseded text:* Ours: `U` ×23 (valid table-20 unknown). GDAC:
> `Y`×5, `N`×15, `U`×3. Encoding is closed.
>
> **Reclassified 2026-08-12: `Y`/`N` is _not derivable_, and GEBCO does not
> unblock it.** With the grid now in hand this was tested directly and the
> bathymetry hypothesis failed:
>
> * **No depth signal.** Max PRES per cycle by GDAC's own flag —
>   `N` median 1004 dbar vs `Y` median 1005 dbar on this float; 1002 vs
>   1003 on 2901339; 1003 vs 1003 on 2902222. Indistinguishable. These are
>   1000 dbar park floats in water kilometres deep, so `Y` cannot mean
>   "reached the seabed".
> * **Geographically interleaved.** On 2902222 both classes span the same
>   region cycle to cycle, so a bathymetry lookup returns the same answer
>   for neighbours GDAC flags differently.
> * **No engineering field separates them.** Every numeric field was tested
>   against GDAC's `Y` cycles [4, 11, 17, 19]: none splits the classes
>   without overlap. The obvious candidate, the `shallow_water_trap` status
>   bit (0x0002), is **False on all four**.
>
> `GROUNDED` is therefore a DAC-side determination. `U` stays. Closing this
> needs INCOIS's rule or a per-cycle flag we have not located in the frame —
> not a bigger grid. Do not guess from max pressure.

**What the flag actually is.** `GROUNDED` is derived from float
*performance*, not from bathymetry and not from a status bit:

```
T    = CONFIG_ProfilePressure_dbar
Pmax = deepest PRES of the ascending profile

'U' if Pmax or T is unavailable
'Y' if Pmax < T - 100 dbar
'N' otherwise
```

Two points confirm the bathymetry route was never the right one. The Argo
DAC trajectory cookbook (v6.1, DOI 10.13155/29824) §2.5 offers *"two
different ways to determine grounding: 1) based on float performance and
technical data or 2) based on checks with bathymetry"*, and Annex D §5.2
gives the APEX/ARGOS performance form directly. And reference table 20
reserves **`B`/`C` for the bathymetry-database route** — INCOIS publishes
`Y`/`N`, so they used method 1. The earlier `shallow_water_trap` finding
was a correct measurement of the wrong hypothesis: it is a *park-phase*
trap.

Coriolis's own `process_trajectory_data_apx_argos.m:104` hardcodes
`grounded = 'U'` — it does not compute the flag for this family at all —
which is why the MATLAB chain gave no hint. INCOIS runs its own `INQC
V4.0` chain, visible in their `HISTORY_SOFTWARE`.

Full evidence, fleet-wide accuracy and the implementation record:
**`docs/GROUNDED_INVESTIGATION.md`**.

**Residual on this float: none.** All 23 cycles agree, including cycles
21–23, which decode to zero profile levels and so are honestly `U`.

---

## What is actually ours to fix (remaining)

| priority | item | effort | effect |
|---|---|---|---|
| — | none on these three files without new data | | |
| ~~later~~ | ~~R8.1 `GROUNDED` Y/N~~ | **DONE 2026-08-13** — performance-derived | **+20 N_CYCLE cells realised** |
| later | TEST014 / profile QC | unknown INCOIS rule | not this file |

Ceiling without new data, re-measured 2026-08-13 at both tolerances:
`meta.nc` **63/65**, `tech.nc` **321/322**, profile science **100 %**,
profile `QCP$` **19/20**, `Rtraj.nc` N_MEAS **88.1 %** / N_CYCLE
**89.5 %** at 1 min — **78.2 %** / **84.1 %** at a true 1 ms.

The gap between the two tolerances is not slack in the model: at 1 ms the
extra misses are MC 600/700 (22 cycles each, ≤50 s reference-instant, R4)
and a few MC 702/703 fixes. Those are sub-minute and already classified
as not-a-bug below.

**The residue is not closeable from this telemetry, and deliberately so:**

* 46 N_MEAS + 4 N_CYCLE fields — GDAC 480 h chain (R1)
* 1 N_MEAS row — GDAC un-subtracted epoch in MC 0 (R2)
* 10 cycles of `JULD_FIRST_MESSAGE` / MC 702 — we hold more telemetry (R6)
* ≤50 s on MC 600/700 — DAC reference instant (R4)
* 1 `tech.nc` cell — `FLAG=61` is in no CRC-valid copy (T1)
* 2 `DATA_MODE` cells — delayed-mode `A` vs real-time `R` (R7)
* 2 `meta.nc` timestamps — file creation time (M1/M2)
* 98 profile QC cells — delayed-mode re-flagging on **2 cycles only**
  (see below); GDAC is `DATA_MODE='D'` on all 20 profiles

### The 98 QC cells, itemised (2026-08-13)

All of them sit on cycles 4 and 20; the other eighteen cycles are exact.

| cycle | cells | pattern | reading |
|---|---|---|---|
| 4 | 4 | GDAC `4`, ours `1` | the known **TEST014 sensitivity** — INCOIS flags a 0.005 kg/m³ inversion against the manual's 0.03 |
| 20 | 94 | GDAC `4` on every level; ours `1` (TEMP) and `3` (PSAL, 47 cells) | GDAC blanket-rejects the profile in delayed mode |

Cycle 20 is **not** a missed detection. We do flag it: our `QCF$` is
`10200` (TEST016 drift + TEST009), and the salinity is visibly wrong —
our PSAL spans 35.863 … 37.154 where the deep levels sit near 35.96. The
difference is severity, `3` ("probably bad") in real time versus `4`
("bad") after delayed-mode review, which is the correct real-time call.
