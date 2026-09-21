# Post-C1 + corrected-metadata fleet baseline

**Audit only — no code was modified.** C1 verified unchanged
(`TRANSMISSION_GAP_HOURS = 6.0`, `_named_burst_index` present); 1708 tests
pass.

Measured 2026-08-13. Backend: **four-CSV only** (the operator's corrected
sheets). No `registry.csv`, no `registry_apf9.csv`, no inferred fallback.
GDAC files re-downloaded the same day and used **only as a cross-check**.

---

## 1. The corrected CSVs: what changed, and what still needs a fix

### Fixed by the operator ✅
`launch date` and `end mission date` are now full 14-digit stamps. The Excel
scientific-notation corruption (`2.01E+13`, which our loader silently
expanded into the fabricated date `2010-00-00T00:00:00Z`) is **gone**. All
11 launch dates match the values we previously reconstructed from in-repo
sources, which independently confirms both sets.

### Format issues handled during ingest (not decoder bugs)
`meta.csv` and `calib.csv` arrived as **tab-separated** files with a leading
blank line and a spurious banner row; `calib.csv` has no real header (only
`column_1…column_33`). `sensor-info.csv` and `config_params.csv` are normal
CSV. All four were normalised to comma-CSV before use; `calib.csv` reuses the
repository header after verifying both are the same 33-column schema.

### Still wrong: `np0` sign on three floats · **metadata problem** · HIGH
The sheets give `np0 = +1` for **2901328, 2901339, 2901350**; the correct
value is **−1**.

Proven from telemetry alone, without reference to GDAC numbering:

```
102510_2011-12-27_2901339_001.txt   telemetered profile id = 2
102510_2012-01-06_2901339_002.txt   telemetered profile id = 3
102510_2012-01-16_2901339_003.txt   telemetered profile id = 4
```

`cycle = profile_id + np0`, and file `_001` is cycle 1, so `np0 = −1`.
Cross-check: decoding with `+1` as supplied puts every cycle **exactly +2**
too high on all 227 shared surfacings across the three floats (offset set
`{2}`, no scatter). Two independent lines of evidence agree.

**The baseline below uses `np0 = −1`.** This is a data correction, not a code
change; the sheets should be amended at source.

### Missing column: `end mission date`
The new `meta.csv` has 31 columns; the repository copy has 32. The absent one
is `end mission date`, which we previously held for 2901304
(`20110922051440`) and 2901305 (`20130813144956`). It is an operator-declared
fact that cannot be computed from telemetry, so those two floats now publish
an empty `END_MISSION_DATE`. Restoring the column would close 2 of the 19
remaining meta cells.

---

## 2. Fleet baseline

10 floats decoded (2902224 has metadata but **no raw telemetry** — PTT 152390
is absent from the bundle, so it cannot be decoded).

| measure | result |
|---|---|
| **Science cells** (PRES/TEMP/PSAL) | **49 168 / 49 287 = 99.76 %** |
| QC cells | 49 007 / 49 287 = 99.43 % |
| **Technical cells** | **5 133 / 5 142 = 99.82 %** |
| meta variables | 611 / 630 = 96.98 % |

Per float:

| WMO | cycles ours/GDAC/overlap | science | QC | tech | meta | JULD exact |
|---|---|---|---|---|---|---|
| 2901304 | 20 / 20 / 20 | **3510/3510** | 3412/3510 | **322/322** | 62/63 | 16/20 |
| 2901305 | 27 / 27 / 27 | **4734/4734** | 4726/4734 | 1075/1078 | 62/63 | 0/27 |
| 2901328 | 93 / 92 / 92 | **15264/15264** | 15252/15264 | 1660/1666 | 61/63 | 1/92 |
| 2901339 | 72 / 329 / 71 | **12459/12459** | **12459/12459** | **994/994** | 60/63 | 0/71 |
| 2901350 | 68 / 301 / 67 | **11745/11745** | 11709/11745 | **938/938** | 58/63 | 0/67 |
| 2902201 | 3 / 350 / 0 | n/a¹ | n/a¹ | n/a¹ | 61/63 | n/a¹ |
| 2902203 | 3 / 366 / 3 | **525/525** | 522/525 | **36/36** | 62/63 | **3/3** |
| 2902206 | 3 / 352 / 0 | n/a¹ | n/a¹ | **36/36** | 61/63 | n/a¹ |
| 2902222 | 3 / 348 / 3 | 495/525² | 494/525 | **36/36** | 62/63 | 1/3 |
| 2902223 | 3 / 345 / 3 | 436/525² | 433/525 | **36/36** | 62/63 | 0/3 |

¹ GDAC has not published cycles 359–361 for these floats (their last
published cycles are 350 and 352). A data-availability gap, not a decoder
problem.
² **Not errors** — 30 and 89 cells where GDAC published fill and we recovered
a real measurement. Every level present on both sides is bit-identical.

**Science is 100 % on every float with comparable cycles.**

`GROUNDED` **23/23 + 3/3 + 3/3 + 3/3 + 3/3 = 35/35** on all comparable
cycles. `DATA_MODE` 35/35. 2901304 `Rtraj` N_CYCLE **920/920 (100 %)**.

---

## 3. Genuine problems found, ranked

### P1 · `START_DATE` is anchored on the archive window, not the deployment · **decoder bug** · HIGH

The clearest systematic defect in this baseline. Wrong on **8 of 10 floats**.

| WMO | GDAC | ours | error |
|---|---|---|---|
| 2902206 | 2016-03-13 04:42 | 2025-12-31 13:04 | **+9.8 years** |
| 2902201 | 2016-03-07 11:28 | 2025-12-25 12:55 | **+9.8 years** |
| 2902203 | 2016-03-08 12:27 | 2025-12-26 15:55 | **+9.8 years** |
| 2902222 | 2017-01-21 04:26 | 2025-12-25 07:34 | **+8.9 years** |
| 2902223 | 2017-01-21 20:38 | 2025-12-26 00:21 | **+8.9 years** |
| 2901350 | 2012-02-08 11:09 | 2012-01-29 10:08 | −10.0 days |
| 2901339 | 2011-12-27 21:30 | 2011-12-17 21:39 | −10.0 days |
| 2901328 | 2011-09-04 12:19 | 2011-08-30 10:59 | −5.1 days |
| 2901304 | — | — | exact |
| 2901305 | — | — | exact |

**Specification.** Coriolis `create_nc_meta_file_3_1.m:2696` defines the
variable as *"Date (UTC) of the first descent of the float"*. It is a
**deployment fact**, fixed for the life of the float.

**Our implementation** (`platforms/apex_argos/decoder.py:114`,
`_first_cycle_start_date`) takes the JULD of *the earliest cycle in the
current run*. For a three-file archive starting at cycle 327 that is a 2025
date for a float deployed in 2017 — the value changes depending on which
files you happen to decode, which a deployment fact must never do.

**Evidence it is anchored on cycle 1.** GDAC's `START_DATE` equals the JULD
of its own cycle 1 exactly on 2901304, 2902203, 2902222 and 2902223. On the
other four it differs by ~1 h, which is the separately-tracked profile-JULD
anchor question (C3), not a different rule.

**Why the two "correct" floats are correct by luck:** 2901304 and 2901305 are
the only archives that actually start at cycle 1.

**Proposed fix (not implemented).** Emit `START_DATE` only when the run
contains cycle 1; otherwise leave it fill rather than publish a value that
depends on the archive window. Deriving it from `LAUNCH_DATE + prelude` is
the alternative, but the prelude is not in our metadata, so the honest fill
is preferable. This also makes 2901328/2901339/2901350 fill rather than
wrong, because their cycle 0 is the DPF descent, not the first cycle.

Classification **A (decoder bug)**. Severity **HIGH** — a wrong deployment
date is a data-integrity issue and is exactly the kind of value a GDAC
format/consistency check inspects.

### P2 · `END_MISSION_STATUS` published as `T` where GDAC leaves it blank · **metadata problem** · LOW
Four floats (2901339, 2901350, 2902201, 2902206). We emit `T` (terminated)
for floats the sheets mark dead. Cosmetic; needs a decision on whether the
sheet's `Status` column should drive this field at all.

### P3 · `PRESSURE_InternalVacuum_inHg` · **unresolved (F)** · LOW
7 cells across 2901305 and 2901328. On 2901328 GDAC reports `−25.665` where
we compute `+44.655` from `counts × 0.293 − 29.767`; the counts imply a value
outside the calibrated range. Pre-existing, unchanged by C1, still not
explained by the APF9 format notes. 7 cells of 5 142.

### P4 · `FLAG_ProfileTermination_hex`, 2 cells · **unresolved (F)** · LOW
2901305 cycle 27 (`01` vs our `601`) and 2901328 cycle 85 (`01D` vs `1D`).
Checked fleet-wide: **this is not a zero-padding convention** — GDAC itself
mixes 2-, 3- and 4-character widths, and only these 2 of 348 comparable cells
disagree. Genuine value differences in individual transmissions.

### Not problems — confirmed correct behaviour

| observation | class | evidence |
|---|---|---|
| 119 extra science cells on 2902222/2902223 | **D — valid extra telemetry** | every shared level bit-identical; extras are CRC-valid frames GDAC left as fill |
| Cycle 0 on 2901328/2901339/2901350 | **D** | full 59-level physically sound profiles (2901339: T 3.204–26.561, S 34.856–36.551); the DPF descent GDAC discards |
| QC `4`→`1`/`3` diffs (280 cells) | **C — GDAC-specific** | GDAC comparables are `DATA_MODE='D'`; ours are correct real-time calls |
| QC `9`→`1` on 2902222/2902223 | **C** | GDAC marks the levels it left as fill "not evaluated"; we measured them |
| Rtraj `JULD_*` schedule fill on 1010 floats | **E — reference convention** | we emit fill with `STATUS='9'` ("not determined") rather than invent times; this is issue C2, archive lacks cycle 1 |
| `FIRMWARE_VERSION` `061810` vs `61810` | **E** | manufacturer's six-digit `MMDDYY` needs the leading zero |
| 2902201/2902206 zero overlap | **C** | GDAC has not published those cycles |

---

## 4. C1 status after the corrected metadata

Unchanged and still correct. `GROUNDED` 35/35, `DATA_MODE` 35/35, 2901304
N_CYCLE 920/920, science 100 % on every comparable float. Nothing in this
baseline contradicts the C1 verification.

---

## 5. What was NOT done, deliberately

* No code changes of any kind.
* C1 untouched; the 6 h threshold and the P2 fallback are as delivered.
* The `np0` correction was applied **to the data only**, in `/tmp`, and is
  reported here for the operator to fix at source.
* No value was altered to improve GDAC parity.

## 6. Reproducing

```bash
for w in 2901304 2901305 2901328 2901339 2901350 \
         2902201 2902203 2902206 2902222 2902223; do
  python scripts/generate_apex_argos_nc.py \
    --raw-root <raw-root> --registry <corrected-4csv-dir> \
    --output-root /tmp/post_c1 --wmo $w
done
```
