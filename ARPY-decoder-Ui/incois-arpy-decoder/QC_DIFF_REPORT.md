# QC differences vs GDAC — all APF9 floats

Generated with `scripts/audit_qc_diffs.py` (new, generic: takes any number of
`WMO=our_dir=ref_dir` triples). Reference = IFREMER/INCOIS GDAC, fetched today.
Levels are matched on **PRES**, so levels we recovered but GDAC never published
are reported separately instead of shifting the comparison.

## 0. Coverage

| WMO | decoder | raw cycles we hold | GDAC cycles overlapping | ref mode |
|---|---|---|---|---|
| 2901304 | 1005 | 1–23 | 20 | D |
| 2901339 | 1005 | 0–71 | 71 | D |
| 2902201 | 1010 | 359–361 | **0** (GDAC stops at 350) | — |
| 2902203 | 1010 | 359–361 | 3 | R |
| 2902206 | 1010 | 359–361 | **0** (GDAC stops at 352) | — |
| 2902222 | 1010 | 327–329 | 3 | R |
| 2902223 | 1010 | 327–329 | 3 | R |

2902201 / 2902206 cannot be QC-compared at all yet — the cycles in our raw
bundle have not been published. That is a data-availability gap, not a decoder
gap.

## 1. Per-level `<PARAM>_QC` — 111 of 17,427 cells differ (99.36 %)

| WMO | cells | identical | diffs | where |
|---|---|---|---|---|
| 2901304 | 3510 | 3412 | **98** | cycle 20 (94), cycle 4 (4) |
| 2901339 | 12459 | 12459 | **0** | — |
| 2902203 | 525 | 522 | **3** | cycle 361 (TEMP) |
| 2902222 | 495 | 493 | **2** | cycle 329 |
| 2902223 | 438 | 430 | **8** | cycles 328, 329 |

Four distinct root causes:

### 1a. TEST016 action severity — 94 cells (2901304 cycle 20)
Both sides independently detect the gross salinity drift (deep PSAL mean jumps
**+1.309 psu**). GDAC `QCF$ = 14000` → tests 14 + 16 failed, and it condemns
**the whole profile, both TEMP and PSAL, with QC `4`**. We emit `QCF$ = 10200`
→ tests 9 + 16, PSAL `3` whole-profile (per QC Manual v3.9, which prescribes
flag 3) plus TEMP/PSAL `4` on the 12 levels our spike test caught.
So: 47 TEMP cells `4→1`, 47 PSAL cells `4→3`.
**Classification:** policy divergence, not a bug. Copying it means overriding
the written spec and propagating a salinity test onto temperature.

### 1b. TEST014 sensitivity — 4 cells (2901304 cycle 4), 1 cell (2902223 cycle 329)
GDAC flags TEMP+PSAL `4` at 90.1/100.6 dbar. Measured inversion there is
**0.005 kg/m³**; the manual (and our implementation) threshold is
**0.03 kg/m³**, so we do not fire. Swept the threshold over all 7 floats:

| threshold | matches GDAC | new false positives |
|---|---|---|
| 0.030 | 0 | 0 |
| 0.010 | 0 | 4 |
| **0.005** | **2** | **18** |
| 0.001 | 2 | 192 |

Lowering the threshold is not the answer — their rule is something else
(different reference pressure or a smoothing pass). **Unresolved, evidence
logged.**

### 1c. Recovered levels flagged `9` upstream — 7 cells (2902222/23)
GDAC published those levels as FillValue with QC `9` (messages it never
received); we decoded real values from CRC-valid frames and flag them `1`.
Plus 10 (2902222) / 29 (2902223) levels that exist only in our files.
**Ours is strictly better. Not a defect.**

### 1d. Unattributable INCOIS flags — 3 cells (2902203 cycle 361)
TEMP `3` on three levels at the top of a sharp thermocline. GDAC's mask names
test 14, but **PSAL is FillValue on that whole profile** (the float is
greylisted, see §6), so a density inversion is mathematically uncomputable
there. The mask and the data contradict each other. **Cannot be reproduced
truthfully.**

## 2. `PROFILE_<PARAM>_QC` — 6 of 291 differ
Purely downstream of §1 (the letter grade is the % of good levels). No
independent cause.

## 3. Mono-profile `POSITION_QC` — 6 of 100 differ (2902222/23 only)

GDAC = `3`, ours = `1`, on all three overlapping cycles of both floats.

**Decisive evidence this is a DAC-side artefact:** for 2902222 cycle 329 the
profile position is `-54.115, -156.827` at JULD `27772.53662`. That is
byte-identical to a fix in GDAC's *own* `_Rtraj.nc`, where the same fix carries
`POSITION_QC = '1'` and `POSITION_ACCURACY = '1'`. GDAC's two files disagree
with each other about the same fix.

Onset is sticky per cycle range, not per fix:

| WMO | `POSITION_QC` history | speed at the switch |
|---|---|---|
| 2902222 | `1` cycles 1–294, `3` cycles 295–348 | 0.094 m/s |
| 2902223 | `1` 1–190, `3` 191–345, `1` 346–347, `3` 348 | 0.205 / 0.218 / 0.327 m/s |

All speeds pass TEST005 comfortably. The other five floats (all eastern
hemisphere, never dateline-crossing) are `1` on every published profile. Onset
coincides with the floats settling into western longitudes.
**We decline to copy an internally inconsistent flag.**

## 4. Trajectory `JULD_ADJUSTED_QC` — 175 of 1,722 matched cells

One rule, zero exceptions across **51,000 rows on all 7 floats**:

> GDAC sets `JULD_ADJUSTED_QC = '0'` on exactly the rows where
> `JULD_ADJUSTED_STATUS` is non-blank.

We already write `JULD_ADJUSTED_STATUS` correctly (92 `'1'` + 23 `'9'` on
2901304, matching cell-for-cell) but leave the QC blank. MCs affected: 100,
250, 300, 500, 800.
**This is the one clean, deterministic, zero-risk fix in the list.**
(115 cells on 2901304, 15 on each 1010 float.)

## 5. Trajectory `POSITION_QC` — 6 of 236 fixes (2901304 only)
GDAC `3`, ours `1`. Not derivable from the CLS location class; a speed screen
separates only 1 of the 6. Known open item.

## 6. Trajectory science QC — 0 diffs
`PRES_QC / TEMP_QC / PSAL_QC` and their `_ADJUSTED` counterparts on the
N_MEASUREMENT block: **3,246 matched cells, 0 differences** across 2901304,
2902222, 2902223, 2902203.

## 7. `HISTORY_QCTEST` masks — 100 of 100 comparable cycles differ

Per-test breakdown of which bits are missing from our `QCP$` (tests performed):

| test | ref-only cycles | reason |
|---|---|---|
| **4** position on land | **100 / 100** | we don't run it — needs GEBCO/ETOPO bathymetry |
| **19** deepest pressure | 74 (2901339 ×71, 2902203 ×3) | `CONFIG_ProfilePressure_dbar` absent from the single-CSV registry backend; present in the four-CSV backend, where we do run it (2901304, 2902222/23 all have bit 19) |
| **5 / 16 / 18** cross-cycle | 1–3 each | first cycle of a contiguous run has no predecessor in our 3-file archives; INCOIS has full history. Structural. |
| 16 (ours-only, 1 cycle) | — | we hold 2901339 cycle 0, GDAC doesn't publish it, so our cycle 1 *has* a predecessor |

`QCF$` (tests failed) diffs: test 14 ref-only ×3 (§1b/1d), test 3 ref-only ×6
(the 2902222/23 position artefact of §3 recorded as "impossible location"),
test 9 ours-only ×1 (2901304 cycle 20 spike, §1a).

**Test 19 is a real gap we own and can close** by populating
`CONFIG_ProfilePressure_dbar` for the registry-backed floats. Test 4 needs
bathymetry (same dataset as `GROUNDED`).

## 8. `<PARAM>_ADJUSTED_QC` — D-mode vs R-mode, not a QC defect
15,969 cells "differ" on 2901304 + 2901339 only because GDAC serves **D-files**
for those floats (adjusted fields populated, QC 1/4) while we emit R-files with
blank adjusted QC. On the three floats where GDAC also serves R-files
(2902203/222/223) the count is **0 / 1,545**.

## 9. Greylist context (external, verified)
`ar_greylist.txt` (usgodae mirror; the IFREMER path 404s):

```
2902203,PSAL,20170522,,4,hard drift and wreckage,IN
2902206,PSAL,20180323,,4,fresh offset and completely wreckage,IN
```

Explains GDAC's blanket `PSAL_QC = 4` on 2902203 — and we already reproduce it
(0 PSAL diffs on that float) because our own tests independently condemn the
salinity. None of the other five floats are greylisted.

## Summary — what is ours to fix

| # | item | cells | verdict |
|---|---|---|---|
| 4 | `JULD_ADJUSTED_QC = '0'` where STATUS set | 175 | **fix — deterministic, 7/7 floats, zero exceptions** |
| 7 | TEST019 on registry-backed floats | 74 cycles of mask | **fix — metadata coverage, not algorithm** |
| 7 | TEST004 position on land | 100 cycles of mask | needs bathymetry (bundle with `GROUNDED`) |
| 1a | TEST016 → `4` on both params | 94 | policy call — contradicts QC Manual v3.9 |
| 1b | TEST014 threshold | 5 | unresolved; threshold sweep rejects the naive fix |
| 1d | unattributable INCOIS TEMP `3` | 3 | uncomputable (PSAL is fill) |
| 3 | profile `POSITION_QC` 1 vs 3 | 6 | GDAC self-contradictory — decline |
| 5 | traj `POSITION_QC` | 6 | open, not derivable from CLS class |
| 1c | recovered levels | 7 (+39 extra) | ours is better |
| 8 | `_ADJUSTED_QC` | 15,969 | R-vs-D artefact, not comparable |
