# Root-Cause Analysis — Python decoder vs official INCOIS/GDAC mono-profiles

**Date:** 2026-07-29
**Files:** `R2902224_345.nc`, `R2902223_348.nc`
**Objective:** reproduce the official INCOIS output as closely as feasible, not merely pass the FileChecker.

---

## 0. Correction before anything else

**Two of the six reported differences no longer exist.** The local files in the
supplied ZIP were written at `09:29:34` and `09:43:45`, before the CNDC and
float32 fixes landed. Regenerating `R2902224_345.nc` with current code gives:

```
GDAC       N_PARAM=3  N_HISTORY=7  nvars=64  CNDC=NONE  PRES.resolution=np.float32(0.1)
LOCAL-now  N_PARAM=3  N_HISTORY=4  nvars=64  CNDC=NONE  PRES.resolution=np.float32(0.1)
```

`N_PARAM`, the three CNDC variables and all nine `resolution` attributes now
match exactly. Items 1 and 6 below are historical.

---

## 1. Summary table

| # | Difference | Root cause | Evidence | Reproducible? | Code change? | Minimal fix | Risk | Files |
|---|---|---|---|---|---|---|---|---|
| 1 | `N_PARAM` 4 vs 3; `CNDC`/`CNDC_QC`/`PROFILE_CNDC_QC` exported | **Already fixed.** Was incorrect implementation — writer published every science variable on the dataset | `_EXPORTED_PARAMS` at `mono_profile.py:95`; regenerated file has `N_PARAM=3`, no CNDC | Fully reproducible | **Done** | — | — | — |
| 2 | `resolution` float64 vs float32 | **Already fixed.** NetCDF library behaviour: `np.generic.item()` returned a Python float, stored as `NC_DOUBLE` | `admt.py:312` now uses `var.setncattr` | Fully reproducible | **Done** | — | — | — |
| 3 | `JULD` differs 73 min / 93 min | **Incorrect implementation.** We use first-transmission time; GDAC sets `JULD = JULD_LOCATION` | On 2902223_348 our `JULD_LOCATION` equals GDAC `JULD` to **8.8 µs** | Fully reproducible | **Yes** | `mission.py:20-40` — set profile JULD from the selected fix | Low–medium | `mission.py`, `decoder.py` |
| 4 | `LONGITUDE` −29.354 vs −29.381 (2902224 only) | **Missing raw information.** GDAC used an ARGOS fix absent from our file | GDAC fix at 19:51:07; our earliest is 21:07:50 (+76.7 min). Position not in the archive | **Cannot be reproduced** | No | — | — | — |
| 5 | `POSITION_QC` 3 vs 1 (2902223 only) | **Different QC algorithm.** We hardcode `3`; GDAC runs RTQC test 3 | `_LOCATION_CLASS_QC`, `mission.py:54-62`. Class 3 → QC 3 on 2902224 ✓, but 2902223 gets QC 1 | Reproducible with additional metadata | **Yes, conditional** | Derive from CLS class rather than a constant | Medium | `mission.py` |
| 6 | `TEMP_QC` all-1 vs all-3; `PROFILE_TEMP_QC` A vs F | **Different QC algorithm + float history.** GDAC failed RTQC **test 16** | GDAC `QCF$=10008` → tests 3 and 16; `CF` record on TEMP with `previous_value=1.0` | **Requires historical float history** | No (out of scope) | — | — | — |
| 7 | `N_HISTORY` 4 vs 7/6 | **GDAC post-processing.** `ARCA`/`ARUP` are DAC steps; extra `CF` from test 16 | GDAC HISTORY lists `ARFM, ARGQ, ARCA, ARUP, QCP$, QCF$[, CF]` | Not reproducible (correctly) | No | — | — | — |
| 8 | `SCIENTIFIC_CALIB_*` populated vs blank | **GDAC post-processing.** Dated at *their* `DATE_UPDATE` | `SCIENTIFIC_CALIB_DATE = 20260724074640` = GDAC `DATE_UPDATE` | Reproducible with additional metadata | Optional | — | Low | `mono_profile.py` |
| 9 | `HISTORY_SOFTWARE` `ARPY`/`V0.1` vs `INQC`/`V4.0` | **Intentional.** We must not claim to be INCOIS's chain | — | N/A | **No** | — | — | — |
| 10 | `DATE_CREATION`, `DATE_UPDATE`, `history` | Generation timestamps | — | N/A | No | — | — | — |

**Science is unaffected: 351/351 PRES/TEMP/PSAL values bit-identical across both profiles.**

---

## 2. Detailed analysis

### 2.1 Why did we export CNDC? *(answered directly)*

**The Python decoder incorrectly exposed it.** Not an INCOIS suppression, and
not merely internal.

CNDC is a genuine, non-deprecated Argo reference-table-3 parameter
(`NVS/R03.jsonld`, `owl:deprecated: false`), so exporting it was *legal* — but
the INCOIS core profiles carry PRES/TEMP/PSAL only. The writer had no concept of
"computed but not published": `science_params` was every `N_LEVELS` variable on
the dataset, and CNDC is derived during PSAL processing, so it fell through.

That created a trap: omit CNDC from `STATION_PARAMETERS` and FileChecker CK_0032
rejects the file ("Does not specify 'CNDC'. Variable contains data."); advertise
it and diverge from GDAC. Not exporting it resolves both.

**Fixed** at `mono_profile.py:95` and `:898`. CNDC is still computed and remains
on the in-memory dataset for the trajectory and audit layers.

### 2.2 Why is JULD different? — the most important finding

Tracing raw → decoder → NetCDF, the divergence is at
`mission.profile_juld_from_messages()` (`mission.py:20-40`), called from
`decoder.py:147`. It returns `min(received_at)` — the first CRC-valid
transmission.

Its docstring says the true ADMT JULD is the float's ascent-end clock, which is
"unavailable here". **That is now stale** — M6 decodes `EPOCH` and `TINIT`. But
the interesting result is that the float clock is *not* what GDAC uses either:

```
GDAC  JULD                = 2026-07-20 19:51:07
LOCAL JULD (1st message)  = 2026-07-20 21:04:32   (+73.4 min)
AET_float = EPOCH+TINIT-10min = 2026-07-20 18:25:11   (-85.9 min)
```

**The decisive evidence:** in *both* GDAC files, `JULD` is bit-identical to
`JULD_LOCATION`:

| File | GDAC `JULD` | GDAC `JULD_LOCATION` | Equal |
|---|---|---|---|
| R2902224_345 | 19:51:07.000008 | 19:51:07.000008 | **yes** |
| R2902223_348 | 01:43:44.999991 | 01:43:44.999991 | **yes** |

And on 2902223_348 — where we hold the same fix — **our `JULD_LOCATION`
reproduces GDAC's `JULD` to 8.8 microseconds**:

```
GDAC  JULD           = 2026-07-24 01:43:44.999991
LOCAL JULD_LOCATION  = 2026-07-24 01:43:45.000000
difference           = 0.0000088 s
```

So INCOIS's real-time rule is **JULD = time of the selected ARGOS position fix**.
Our position-selection logic is already correct; only the JULD source is wrong.

**Specification conflict, stated explicitly.** The Argo User's Manual defines
profile `JULD` as the time of the *measurement* (ascent end), and `JULD_LOCATION`
as the time of the position fix. Setting them equal is a DAC simplification, not
what the spec intends. **The specification and the official GDAC output
disagree.** Since the stated objective is to reproduce INCOIS output, matching
GDAC is right here — but this is a case where we would be deliberately adopting
a less-correct value, and it should be a conscious decision. Recommend `JULD_QC`
stays `1` (GDAC uses `1`).

**Minimal fix** (`mission.py`, `decoder.py:147-158`): after `select_profile_fix()`
resolves the fix, set the profile JULD from `fix.at` rather than
`min(received_at)`. Keep the first-transmission value as the fallback when no fix
exists.

**Side effects:** `JULD` and `JULD_LOCATION` become equal; `_prof.nc` inherits
the change; trajectory `MC=703` rows are unaffected (they already use fix times).
Ordering matters — `select_profile_fix()` currently *takes* JULD as input, so the
fallback path must be kept to avoid circularity.

### 2.3 Why is LONGITUDE different?

Not decoder logic, not interpolation, not QC. **The DAC had data we do not.**

```
GDAC position: lat -41.960  lon -29.381  at 19:51:07
Our fixes:     21:07:50 (cls 1, -29.354), 21:57:11, 23:21:24, 23:46:41,
               00:53:00, 00:55:18, 01:14:28
GDAC's fix time present in our raw archive?     False
GDAC's position present in our raw archive?     False
```

Our earliest reception is **76.7 minutes after** GDAC's. Scanning the entire
2902224 archive confirms neither the timestamp nor the coordinate appears
anywhere. The DAC received an earlier ARGOS satellite pass.

This is the same root cause as difference 3's magnitude on 2902224 and explains
why 2902223 (where we hold the same fix) matches lat/lon exactly.

**Cannot be reproduced from available APF9 raw data.** No code change.

### 2.4 Why are QC flags different?

Decoding both `QCP$` masks with our own bit convention (`ctd.py:268-277`,
test *N* at bit *N*):

```
GDAC QCP$ D7B7E -> tests 1,2,3,4,5,6,8,9,11,12,13,14,16,18,19
OURS QCP$ 6B4E  -> tests 1,2,3,6,8,9,11,13,14
GDAC runs, we don't: 4, 5, 12, 16, 18, 19
We run, GDAC doesn't: (none)
```

**Yes — GDAC runs six extra tests.** Ours is a strict subset, so no
contradictory algorithm, only missing coverage.

For `R2902224_345`, `QCF$ = 10008` → **tests 3 and 16 failed**:

- **Test 16, gross salinity/temperature sensor drift** — compares this profile
  against the float's *previous good profile*. This is what set `TEMP_QC = 3` on
  all 59 levels and `PROFILE_TEMP_QC = F`. GDAC's own HISTORY confirms it: one
  `CF` record, `HISTORY_PARAMETER = TEMP`, `HISTORY_PREVIOUS_VALUE = 1.0` — the
  DAC overwrote a value of 1, exactly what we produce.
- **Test 3, impossible location** — relates to the position difference in §2.3.

For `R2902223_348`, `QCF$ = 0`: nothing failed, and our TEMP_QC matches.

Is delayed mode involved? **No** — both files are `DATA_MODE = R`. Does APF9
firmware contain QC decisions? **No** — the SBE41 status word flags sensor
faults, not Argo QC. Does our implementation differ from MATLAB? **Not in
logic** — the tests we do run agree; we simply implement fewer.

**Classification: requires historical float history.** Test 16 needs prior
cycles, which a single-cycle real-time decode does not have. Test 5 (impossible
speed) likewise needs the previous cycle's position and time. Out of scope here.

### 2.5 Why is POSITION_QC different?

`mission.py:54-62` maps **every** CLS class to `3` (except Z → 4). That was
derived from six references that all showed `3`. The new data contradicts it:

| Cycle | GDAC `POSITION_QC` | CLS class of that fix |
|---|---|---|
| 2902224_325 | 3 | 3 |
| 2902224_326 | 3 | 3 |
| 2902224_345 | 3 | not in our raw |
| **2902223_348** | **1** | unknown (no raw held) |

The constant is demonstrably wrong, but I **cannot yet determine the correct
rule**: the one case that disproves it is the one cycle whose raw file we lack.
Two candidate explanations — CLS class drives the flag, or RTQC test 3 does —
and the available data cannot separate them.

**Recommendation: do not change this yet.** Replacing one unjustified constant
with another guess is not an improvement. Supplying raw ARGOS files for
2902223 cycle 348 would settle it in minutes.

### 2.6 Why fewer HISTORY records?

| GDAC step | Meaning | Do we emit it? |
|---|---|---|
| `ARFM` | format conversion | **yes** |
| `ARGQ` | real-time QC | **yes** |
| `ARCA` | DAC archive | **no — correctly** |
| `ARUP` | GDAC update | **no — correctly** |
| `QCP$`/`QCF$` | tests performed/failed | **yes** |
| `CF` | flag change (test 16) | not applicable |

`ARCA` and `ARUP` are performed by the DAC and GDAC during ingestion, not by a
decoder. Claiming them would be false provenance. The extra `CF` follows from
test 16 (§2.4). **This difference is correct behaviour and should not be
"fixed".**

### 2.7 Why were resolution attributes float64?

`nc/admt.py`, in `write_admt_dataset`. The old code was:

```python
if isinstance(avalue, np.generic):
    avalue = avalue.item()  # np.float32(0.1) -> Python float
setattr(var, akey, avalue)  # netCDF4 stores NC_DOUBLE
```

`_PARAM_ATTRS` (`mono_profile.py:460-490`) correctly declares
`np.float32(0.1)`; `.item()` discarded the width, and netCDF4 defaults Python
floats to `NC_DOUBLE`. Hence `0.1` became `0.10000000149011612`.

**Fix (applied, `admt.py:305-313`):** pass numpy scalars straight to
`var.setncattr`, which preserves the declared dtype. `np.float32` was already
correct — the bug was in serialization, not the constant. This corrected 9
attributes per profile across all files.

---

## 3. Recommended actions, in priority order

1. **Implement `JULD = JULD_LOCATION`** (§2.2). Highest-value change: removes the
   73/93-minute difference and is proven to microsecond precision. Note the
   spec conflict — this is deliberate GDAC-matching.
2. **Refresh the stale docstring** at `mission.py:20-36`, which claims the
   engineering clock is unavailable. M6 decodes it.
3. **Obtain raw ARGOS files for 2902223 cycle 348** to resolve `POSITION_QC`.
4. **Do not change** HISTORY provenance, `HISTORY_SOFTWARE`, or test-16 QC.

Not recommended: implementing tests 5/16 would require a cross-cycle history
store — a real feature, not a bug fix.

---

## 4. Verification state

`ruff` / `ruff format` / `mypy --strict` clean · **563 tests pass** · science
**1813/1813 bit-identical** · `_tech.nc` **531/531**. The temporary 2902224
registry row used for this analysis has been removed.
