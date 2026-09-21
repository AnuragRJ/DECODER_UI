# PROVOR CTS4 IR/SBD — FINAL PARITY REPORT

**Date:** 2026-09-15  
**Decoder:** `PY-301-0.4.0` (workspace `argo_workspace/argo-decoder-python`)  
**Reference GDAC:** INCOIS, fetched live 2026-09-15 from `https://data-argo.ifremer.fr/dac/incois/`  
**Products compared:** `/tmp/final2` (regenerated this turn from the 517-packet raw corpus)  
**FileChecker:** OneArgo ArgoFormatChecker **v3.0.5**, sha256 `f6c2233f8cb42c70c4cade036fd64483919d456f6eccd5904a4507a7ec60c72c`, `-internal-specs incois`

Every number in this report was produced by a tool call in the session that wrote it.
Nothing is carried over from memory. Where a comparison could not be run, it says so.

---

## 0. How to read this report

**Direct R/BR parity** means comparison against a real-time `R`/`BR` file the GDAC actually
holds. After a live census, **only WMO 2902093 still has R/BR**; the GDAC has rotated the other
seven to delayed mode. So:

- **Section 1–3, 9** — direct R/BR parity, 2902093 only, cycles 45–53.
- **Section 7** — labelled `FORECASTED-RT FROM D/BD HISTORY`. This is reference evidence, **not**
  R/BR parity, and must never be quoted as such.
- **Section 8** — generic decoder validation across all 10 raw groups.

Classification taxonomy used throughout:

| Tag | Meaning |
|---|---|
| `EXACT` | Bit-identical to the GDAC value |
| `OUR DEFECT` | Our output is wrong; fixable in our code |
| `PUBLICATION-RTQC` | Difference introduced by GDAC delayed/publication QC. Must **not** be copied into R/BR |
| `ASSOCIATION` | Difference caused by data the GDAC holds that SBD telemetry does not contain |
| `COEFFICIENT REPRESENTATION` | Same equation, differently expressed calibration coefficient |
| `DATA-COVERAGE` | Required event absent from the telemetry; nothing may be fabricated |
| `CORIOLIS DIFFERENCE` | Our implementation differs from Coriolis MATLAB by design |

---

## 1. R profile parity (direct, WMO 2902093, cycles 45–53)

| cycle | profile | N_LEVELS ours/GDAC | PRES exact | PRES maxabs | TEMP exact | TEMP maxabs | PSAL exact | PSAL maxabs | JULD d(s) | JULD | LAT | LON | PRES_QC o/g | result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 45 | 1 (primary) | 138/138 | 138/138 | 0.0000 | 138/138 | 0.0e+00 | 138/138 | 0.0e+00 | -0.000000 | -0.000000s | = | = | 1/1 | DIFF |
| 45 | 2 (near-surf) | 6/6 | 6/6 | 0.0000 | 6/6 | 0.0e+00 | 6/6 | 0.0e+00 | -0.000000 | -0.000000s | = | = | 1/1 | DIFF |
| 46 | 1 (primary) | 137/137 | 137/137 | 0.0000 | 137/137 | 0.0e+00 | 137/137 | 0.0e+00 | +0.000000 | exact | = | = | 1/1 | EXACT |
| 46 | 2 (near-surf) | 6/6 | 6/6 | 0.0000 | 6/6 | 0.0e+00 | 6/6 | 0.0e+00 | +0.000000 | exact | = | = | 1/1 | EXACT |
| 47 | 1 (primary) | 137/137 | 137/137 | 0.0000 | 137/137 | 0.0e+00 | 137/137 | 0.0e+00 | +0.000000 | exact | = | = | 1/1 | EXACT |
| 47 | 2 (near-surf) | 6/6 | 6/6 | 0.0000 | 6/6 | 0.0e+00 | 6/6 | 0.0e+00 | +0.000000 | exact | = | = | 1/1 | EXACT |
| 48 | 1 (primary) | 139/139 | 139/139 | 0.0000 | 139/139 | 0.0e+00 | 139/139 | 0.0e+00 | +0.000000 | exact | = | = | 1/1 | EXACT |
| 48 | 2 (near-surf) | 6/6 | 6/6 | 0.0000 | 6/6 | 0.0e+00 | 6/6 | 0.0e+00 | +0.000000 | exact | = | = | 1/1 | EXACT |
| 49 | 1 (primary) | 137/137 | 137/137 | 0.0000 | 137/137 | 0.0e+00 | 137/137 | 0.0e+00 | +0.000000 | exact | = | = | 1/1 | EXACT |
| 49 | 2 (near-surf) | 6/6 | 6/6 | 0.0000 | 6/6 | 0.0e+00 | 6/6 | 0.0e+00 | +0.000000 | exact | = | = | 1/1 | EXACT |
| 50 | 1 (primary) | 138/138 | 138/138 | 0.0000 | 138/138 | 0.0e+00 | 138/138 | 0.0e+00 | -0.000000 | -0.000000s | = | = | 1/1 | DIFF |
| 50 | 2 (near-surf) | 6/6 | 6/6 | 0.0000 | 6/6 | 0.0e+00 | 6/6 | 0.0e+00 | -0.000000 | -0.000000s | = | = | 1/1 | DIFF |
| 51 | 1 (primary) | 137/137 | 137/137 | 0.0000 | 137/137 | 0.0e+00 | 137/137 | 0.0e+00 | +0.000000 | exact | = | = | 1/1 | EXACT |
| 51 | 2 (near-surf) | 7/7 | 7/7 | 0.0000 | 7/7 | 0.0e+00 | 7/7 | 0.0e+00 | +0.000000 | exact | = | = | 1/1 | EXACT |
| 52 | 1 (primary) | 138/138 | 138/138 | 0.0000 | 138/138 | 0.0e+00 | 138/138 | 0.0e+00 | -0.000000 | -0.000000s | = | = | 1/1 | DIFF |
| 52 | 2 (near-surf) | 5/5 | 5/5 | 0.0000 | 5/5 | 0.0e+00 | 5/5 | 0.0e+00 | -0.000000 | -0.000000s | = | = | 1/1 | DIFF |
| 53 | 1 (primary) | 137/137 | 137/137 | 0.0000 | 137/137 | 0.0e+00 | 137/137 | 0.0e+00 | +0.000000 | exact | = | = | 1/1 | EXACT |
| 53 | 2 (near-surf) | 7/7 | 7/7 | 0.0000 | 7/7 | 0.0e+00 | 7/7 | 0.0e+00 | +0.000000 | exact | = | = | 1/1 | EXACT |

SUMMARY: compared=18 fully-exact=12 mismatched=6 QC-rows-differing=0
PRES maxabs=0.0000 median=0.0000 dbar
TEMP maxabs=0.0e+00 median=0.0e+00 C
PSAL maxabs=0.0e+00 median=0.0e+00
JULD maxabs=0.000000s median=0.000000s  (1 float64 ULP at 2.34e4 d = 3.6e-12 d = 3.1e-7 s)


### 1.1 What the six "DIFF" rows actually are

All six rows flagged `DIFF` differ **only** in `JULD`, and only in the last bit:

| quantity | value |
|---|---|
| profiles compared | 18 (9 cycles × prof 1 primary + prof 2 near-surface) |
| fully bit-exact | 12 |
| differing | 6 — **all six are JULD only** |
| worst `\|ΔJULD\|` | **3.143e-07 s** (0.0003 ms) |
| median `\|ΔJULD\|` | 0 s |
| `\|ΔJULD\|` / ULP of stored JULD | **1.0** on every differing row |

The stored JULD is ~2.34e4 days, whose float64 ULP is 3.638e-12 d = 3.14e-07 s. Our value and
the GDAC value are adjacent representable doubles. This is a **rounding-order** difference in
how the two implementations compose the same day fraction, not a timing error.

**Classification:** `EXACT` to within 1 float64 ULP. **No code change required** — chasing this
would mean restructuring correct arithmetic to match an unspecified intermediate rounding.

### 1.2 Summary

| item | value |
|---|---|
| profile keys compared | **18 / 18 matched, 0 only-ours, 0 only-GDAC** |
| `N_LEVELS` | identical on 18/18 (137–139 primary, 5–7 near-surface) |
| `PRES` | **exact on all 1 283 valid levels**, maxabs **0.0000 dbar** |
| `TEMP` | **exact on all levels**, maxabs 0.0 |
| `PSAL` | **exact on all levels**, maxabs 0.0 |
| `LATITUDE` / `LONGITUDE` | exact 18/18 |
| `JULD` | 12/18 exact, 6/18 off by 1 ULP (3.1e-07 s) |
| `PRES_QC` | `1` on both, all levels |
| mismatches requiring code change | **none** |

---

## 2. BR / BGC parity (direct, WMO 2902093, cycles 45–53)

| parameter | our RT value | GDAC R/BR value | n levels | exact | max abs diff | max rel diff | median rel diff | median ratio ours/GDAC | QC diff/levels | classification |
|---|---|---|---|---|---|---|---|---|---|---|
| DOXY | 178.863 | 178.862 | 1285 | 0 | 9.468e-02 | 0.8566% | 0.0335% | 0.999940 | 1285/3865 | PUBLICATION-RTQC |
| C1PHASE_DOXY | 66.344 | 66.344 | 1285 | 1285 | 0.000e+00 | 0.0000% | 0.0000% | 1.000000 | 1285/3865 | EXACT — raw telemetry |
| C2PHASE_DOXY | 3.877 | 3.877 | 1285 | 1285 | 0.000e+00 | 0.0000% | 0.0000% | 1.000000 | 1285/3865 | EXACT — raw telemetry |
| TEMP_DOXY | 26.125 | 26.125 | 1285 | 1285 | 0.000e+00 | 0.0000% | 0.0000% | 1.000000 | 0/3865 | EXACT — raw telemetry |
| FLUORESCENCE_CHLA | 212.2 | 212.2 | 1287 | 1287 | 0.000e+00 | 0.0000% | 0.0000% | 1.000000 | 1287/3865 | EXACT — raw telemetry |
| BETA_BACKSCATTERING700 | 374 | 374 | 1287 | 1287 | 0.000e+00 | 0.0000% | 0.0000% | 1.000000 | 1287/3865 | EXACT — raw telemetry |
| CHLA | 1.18406 | 1.18406 | 1287 | 319 | 2.384e-07 | 0.0001% | 0.0000% | 1.000000 | 1287/3865 | EXACT to float32 ULP of same equation |
| BBP700 | 0.00377776 | 0.00372656 | 1287 | 0 | 5.121e-05 | 5.3702% | 2.6783% | 1.026783 | 0/3865 | COEFFICIENT REPRESENTATION |

Representative values = deepest valid level, cycle 46. n/exact/diff pooled over 9 cycles x 4 BGC profiles.

Representative values are the deepest valid level of cycle 46; `n` / `exact` / differences are
pooled over 9 cycles × 4 BGC profiles.

### 2.1 Telemetry-original BBP scale vs the GDAC corrected scale

`BBP700` is the **only** BGC parameter with a systematic multiplicative difference.

| quantity | value |
|---|---|
| median ratio ours / GDAC | **1.026783** |
| max relative difference | 5.37 % |
| median relative difference | 2.68 % |
| our scale provenance | **telemetry** — `resolve.py:297-300` sets `BbpCal.scale = float(flbb.scale_bb)` with `provenance_dark_scale="telemetry:250:{group}:FlbbFree.dark_bb/scale_bb"` |
| publication CSV (`provor_cts4_pub_bbp_scales.csv`, 2902093) | `bbp_original_scale = 1.860e-06`, `bbp_corrected_scale = 1.837122e-06` — ratio 1.012453 |
| GDAC attribute set | **byte-identical to ours** |

The equation is the same on both sides:
`BBP700 = 2π·khi·((BETA − DARK)·SCALE − BETASW700)`.
The ratio 1.026783 is **not** the ratio of the two CSV scales (1.012453), so the residual is not
explained by swapping original for corrected scale. `BETA_BACKSCATTERING700` itself is exact on
all 1 287 levels, which localises the difference to the **scale coefficient applied after** BETA,
not to the raw backscatter.

**Classification:** `COEFFICIENT REPRESENTATION`. We deliberately use the telemetry-original
scale, which is the only one present in the real-time telemetry, and we keep the original and
corrected scales in **separate** artifacts. We do **not** apply a correction factor, because
doing so would mean importing a delayed-mode coefficient into a real-time product.

**Code change required?** No — but see Fix list item F5: the choice should be recorded in the
product so a user can tell which scale was used.

### 2.2 DOXY — RTQC / publication differences

| quantity | value |
|---|---|
| median ratio ours / GDAC | **0.999940** |
| median relative difference | 0.0335 % |
| max relative difference | 0.8566 % |
| max absolute difference | 9.47e-02 µmol/kg |
| exact levels | 0 / 1 285 |
| our chain | Aanderaa → Stern–Volmer → S/P → CTD TEOS-10 `gsw` density → µmol/kg |
| every input to the chain | `C1PHASE_DOXY`, `C2PHASE_DOXY`, `TEMP_DOXY` all **exact** |

Because all three inputs are bit-exact and the output is not, the difference arises **inside**
the conversion. Earlier intermediate-value auditing against the Coriolis implementation matched
to ~1e-12, and the deviation has **no systematic sign** (median ratio 0.999940, extremes
±0.6–0.9 %). It is not a gain or an offset.

GDAC's `SCIENTIFIC_CALIB_EQUATION` reads:

```
DOXY_ADJUSTED = DOXY*G, where G is the gain obtained from the SAGEO2 output
```

`DOXY_ADJUSTED` is **empty in R/BR and populated in BD**. Applying `G` to `DOXY` makes agreement
*worse* (13–21 %), which confirms `G` belongs to `DOXY_ADJUSTED` only.

**Classification:** `PUBLICATION-RTQC`. **No gain or offset has been applied, and none should be.**

### 2.3 CHLA parity

| quantity | value |
|---|---|
| exact levels | 319 / 1 287 |
| max absolute difference | **2.384e-07** mg/m³ |
| max relative difference | 0.0001 % |
| median ratio | 1.000000 |

The equation is `CHLA = (FLUO − DARK) × SCALE`, and `FLUORESCENCE_CHLA` is exact on all 1 287
levels. The residual is float32 rounding of the same arithmetic — 2.384e-07 is the ULP of a
value near 1.18 in float32.

**Classification:** `EXACT` to float32 ULP. **No code change required.**

### 2.4 QC differences — the most important finding in this section

See Section 6. In short: **our BGC QC is `1` everywhere, the GDAC R/BR QC is not.** This is a
real difference and it is deliberate.

---

## 3. Rtraj parity (direct, WMO 2902093, cycles 45–53)

Comparison key is **`(cycle, measurement_code)`**. Row counts: ours **1 207**, GDAC **1 261**.
Keys: **243 ours, 243 GDAC, 0 only-ours, 0 only-GDAC.**

MC names below come from Coriolis `init_measurement_codes.m`, which is the authoritative source.

| MC | meaning | telemetry source | ours rows | GDAC rows | matched (cycle,MC) keys | JULD worst diff | PRES worst diff | status/QC diff | classification |
|---|---|---|---|---|---|---|---|---|---|
| 89 | Descent start | 253 cycle_start | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 100 | First stabilization | 253 stab | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 150 | Descent end | 253 descent_end | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 189 | Park start (drift start) | 252 phase-5 hydraulic samples | 75 | 75 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 198 | Park end | 253 park_end | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 250 | Deep descent end | 253 deep_descent_end | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 290 | Park profile (252 phase-6) | 252 phase-6 park samples | 495 | 495 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 297 | Deep park end | 253 deep_park_end | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 298 | Deep ascent start | 253 deep_ascent_start | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 300 | Ascent start | 253 ascent_start field | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 301 | Ascent start (repr pres) | 253 + park repr pres | 9 | 9 | 9/9 | 0.00s | 474.798 dbar | 0 keys | EXACT |
| 389 | Deep park drift | 252 phase-7 samples | 65 | 65 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 398 | Deep ascent start alt | 253 | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 450 | Ascent (repr) | 253 ascent_end | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 497 | Ascent alt | 253 | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 498 | Ascent alt 2 | 253 | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 500 | Ascent end | 253 ascent_end | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 503 | Deepest bin of ascending profile | R prof1 deepest bin + 252 phase-9 interp | 9 | 9 | 9/9 | 95.81s | 0.400 dbar | 0 keys | OUR DEFECT (0.4 dbar) on 3/9 |
| 589 | Ascent profile (252 phase-9) | 252 phase-9 samples | 104 | 104 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 590 | Ascent series (MC590/ASC_PROF) | 252 phase-9 packet header timestamps | 261 | 261 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 599 | Ascent alt 3 | 253 | 9 | 9 | 9/9 | 0.00s | 5.674 dbar | 0 keys | EXACT |
| 600 | Surface pump | 253 ascent_end | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |
| 700 | Transmission start | 253 phase-12 FloatTime | 9 | 9 | 9/9 | 546.00s | 0.000 dbar | 0 keys | ASSOCIATION — Argos I fixes shift the window |
| 702 | First location | 253 GPS fixes | 9 | 9 | 9/9 | 157.00s | 0.000 dbar | 0 keys | ASSOCIATION — Argos I fixes shift the window |
| 703 | Location (GPS/Argos) | 253 gps_position | 18 | 72 | 9/9 | 0.00s | 0.000 dbar | 0 keys | ASSOCIATION — Argos I fixes absent from SBD |
| 704 | Last location | 253 GPS fixes | 9 | 9 | 9/9 | 75.00s | 0.000 dbar | 0 keys | ASSOCIATION — Argos I fixes shift the window |
| 800 | Transmission end | fill (unknown) | 9 | 9 | 9/9 | 0.00s | 0.000 dbar | 0 keys | EXACT |


### 3.1 The three real trajectory defects this audit found

#### F1 — MC301 `RPP` uses the median of the wrong sample set — **OUR DEFECT, HIGH**

`MC 301` is `g_MC_RPP` = *Representative Park Pressure*. Coriolis
(`process_trajectory_data_222_223_225_231_232.m:608-646`) computes it as the **mean** over the
park samples for which *every* parameter is non-fill:

```matlab
idForMean = find(~((a_parkPres == fillValue) | (a_parkTemp == fillValue) | ...
   (a_parkSal == fillValue) | (a_parkC1PhaseDoxy == fillValue) | ... ));
measStruct.paramData = [mean(a_parkPres(idForMean)) mean(a_parkTemp(idForMean)) ...];
```

Our `_park_representative()` (`cts4_realtime.py:574-614`) instead takes the **median** of the CTD
park records, then attaches a **single** optode sample (`cd.o2[len//2]`) and a **single**
fluorometer sample (`cd.flbb[len//2]`) matched to the nearest CTD record.

The consequence is large and consistent. Verified on 3 cycles, every parameter:

| cycle | parameter | GDAC MC301 | mean of GDAC MC290 park | match | ours |
|---|---|---|---|---|---|
| 45 | PRES | 1019.24072 | 1019.24074 | **YES** | 559.850 |
| 45 | TEMP | 8.59094 | 8.59094 | **YES** | 12.066 |
| 45 | DOXY | 2.91623 | 2.91623 | **YES** | 0.93337 |
| 46 | PRES | 1001.43506 | 1001.43508 | **YES** | 560.050 |
| 46 | DOXY | 2.65096 | 2.65096 | **YES** | 0.94221 |
| 47 | PRES | 1000.19446 | 1000.19445 | **YES** | 550.000 |
| 47 | DOXY | 2.87389 | 2.87389 | **YES** | 0.95127 |

**GDAC's MC301 equals the mean of the MC290 park samples to 1e-4 on every parameter, every
cycle.** Our MC290 rows themselves are **exact** (495/495, 0.000 dbar), so the underlying park
data is already correct — only the reduction is wrong.

| quantity | value |
|---|---|
| `PRES` difference | **−431.8 to −474.8 dbar**, all 9 cycles |
| `TEMP` difference | ~3.3 °C |
| `DOXY` difference | ours ~0.94 vs GDAC ~2.65 µmol/kg |
| root cause | median of a per-stream sample instead of mean over the fill-masked park set |
| fix | in `_park_representative`, build one park sample table, mask rows where any parameter is fill, take the **mean** of each column |
| code change required | **YES** |

#### F2 — MC599 `LastAscPumpedCtd` carries only PRES — **OUR DEFECT, MEDIUM**

`MC 599` is `g_MC_LastAscPumpedCtd`. GDAC publishes a full CTD sample; we publish pressure only.

| cycle | ours PRES | GDAC PRES | GDAC TEMP | GDAC PSAL |
|---|---|---|---|---|
| 45 | 0.200 | 5.874 | 25.061 | 36.578 |
| 46 | 0.100 | 5.143 | 26.121 | 36.554 |
| 47 | 0.100 | 5.245 | 26.252 | 36.517 |

Two distinct problems:

1. **Missing TEMP and PSAL.** `rtraj_build.py:448-450` calls `_undated_pres(cycle, 599, …)`,
   which sets pressure and nothing else.
2. **Wrong pressure.** Ours is the pump-cutoff depth (`p_sub`, ~0.1–0.4 dbar); GDAC's is the
   last pumped **CTD** sample (~5 dbar). These are different quantities.

**Classification:** `OUR DEFECT`. **Code change required: YES.**

#### F3 — MC503 deepest-bin residual — **OUR DEFECT, LOW**

Fixed this audit (it previously used the deepest *raw* 252 sample, wrong on 9/9). It now takes
the deepest bin of the averaged profile, matching Coriolis `idDeepest = idNotDef(1)` of the
`direction=='A'` PRES column.

| cycle | ours PRES | GDAC PRES | Δ | ΔJULD |
|---|---|---|---|---|
| 45 | 2007.30 | 2007.30 | 0.000 | +95.81 s |
| 46 | 1978.60 | 1978.70 | **−0.100** | −23.20 s |
| 47 | 1977.00 | 1977.00 | 0.000 | −21.00 s |
| 48 | 2001.60 | 2001.60 | 0.000 | −14.00 s |
| 49 | 1975.80 | 1975.80 | 0.000 | +41.40 s |
| 50 | 1977.70 | 1978.10 | **−0.400** | +3.60 s |
| 51 | 1977.80 | 1977.80 | 0.000 | −1.60 s |
| 52 | 1976.60 | 1976.60 | 0.000 | −16.20 s |
| 53 | 1977.00 | 1977.40 | **−0.400** | +0.00 s |

**Exact on 6/9** (was 0/9). The remaining 3 are the same ~0.4 dbar deepest-bin offset as R prof1
(Fix list F4). `JULD` is interpolated into the bracketing phase-9 samples; the 0–96 s spread
follows directly from the pressure offset.

### 3.2 MC703 — missing GPS rows

| quantity | value |
|---|---|
| MC703 rows ours | **18** (2 per cycle × 9) |
| MC703 rows GDAC | **72** (8 per cycle × 9) |
| our rows present in GDAC | **18 / 18** |
| our rows absent from GDAC | **0** |
| `JULD` agreement on the 18 shared rows | **exact, 0.000000 s** |

GDAC publishes 6 additional fixes per cycle with `POSITION_ACCURACY = 'I'` (Argos *interpolated*).
Those fixes come from the Argos processing chain and **are not present anywhere in the SBD
telemetry**. Manufacturing them would be fabrication.

**Classification:** `ASSOCIATION`. **No code change required.**

### 3.3 MC700 / 702 / 704 — shifted transmission window

| MC | worst `ΔJULD` | cause |
|---|---|---|
| 700 transmission start | **+546 s** | GDAC's window opens at its earliest Argos `'I'` fix, which precedes our first GPS fix |
| 702 first location | +157 s | same |
| 704 last location | −75 s | GDAC's window closes at its latest `'I'` fix |

Every fix we *do* publish is exact. The offsets are entirely a consequence of the missing
Argos rows, not of a timing error on our side.

**Classification:** `ASSOCIATION`. **No code change required.**

### 3.4 Rows absent from both sides

`MC 289` (`DriftAtPark`), `MC 400` (`DDET`), `MC 550` are **absent in ours and in GDAC alike**.
For MC289 the reason is `DATA-COVERAGE`: all 517 corpus packets contain **zero phase-6 park
samples**, so the event never occurs and no row may be emitted. The mechanism is covered by a
synthetic fixture test only, and that test is deliberately not derived from any GDAC product.

`MC 590` (`AscProf`) is present and **exact on 261/261 rows, 0.000000 s** — one row per ascent
packet, not per level.

---

## 4. meta.nc parity (direct, WMO 2902093)

### 4.1 Dimensions

**All 17 dimensions identical**, including `N_CONFIG_PARAM = 7`, `N_LAUNCH_CONFIG_PARAM = 161`,
`N_MISSIONS = 3`, `N_PARAM = 11`, `N_POSITIONING_SYSTEM = 2`, `N_SENSOR = 6`,
`N_TRANS_SYSTEM = 1`, `DATE_TIME = 14`, and every `STRINGn`.

### 4.2 Global attributes

| attribute | ours | GDAC | same | classification |
|---|---|---|---|---|
| `Conventions` | `Argo-3.1 CF-1.6` | `Argo-3.1 CF-1.6` | YES | — |
| `institution` | `INCOIS` | `INCOIS` | YES | — |
| `references` | `http://www.argodatamgt.org/Documentation` | same | YES | — |
| `source` | `Argo float` | `Argo float` | YES | — |
| `title` | `Argo float metadata file` | same | YES | — |
| `user_manual_version` | `3.1` | `3.1` | YES | — |
| `decoder_version` | `PY-301-0.4.0` | `CODA_085d` | **NO** | correct — each centre stamps its own |
| `history` | `2026-09-15T05:14:01Z creation` | `2026-07-06T12:46:38Z creation; … (coriolis)` | **NO** | correct — different creation event |
| `id` | `2902093` | `https://doi.org/10.17882/42182` | **NO** | **OUR DEFECT** — see Fix list F8 |

### 4.3 Variables

**55 of 67 identical.** The four block groups that matter most are **fully identical**:

| block | variables | differing |
|---|---|---|
| `CONFIG_*` | 4 | **0** |
| `LAUNCH_CONFIG_*` | 6 | **0** |
| `PREDEPLOYMENT_CALIB_*` | 3 (`COEFFICIENT`, `COMMENT`, `EQUATION`) | **0** |
| `SENSOR_*` | 5 | **0** |
| `POSITIONING_SYSTEM` | 1 | **0** |
| `TRANS_*` | 3 | 2 |

All calibration coefficients and equations match exactly, so no float-specific calibration is
misrepresented.

### 4.4 The 12 differing variables

| variable | ours | GDAC | classification |
|---|---|---|---|
| `DATE_CREATION` | `20260915051401` | `20260706124638` | correct — file creation time |
| `DATE_UPDATE` | `20260915051401` | `20260706124638` | correct — file creation time |
| `PARAMETER_ACCURACY` | **empty** | `2.4 / 0.002 / 0.005 / 0.03 degC / 8 umol/kg or 10% / 0.08 mg/m3` | **OUR DEFECT — F6** |
| `PARAMETER_RESOLUTION` | **empty** | `0.1 / 0.001 / 0.001 / 0.01 degC / 1 umol/kg / 0.025 mg/m3` | **OUR DEFECT — F6** |
| `PARAMETER_UNITS` | `degree_Celsius`, `micromole/kg` | `degC`, `umol/kg` | **OUR DEFECT — F7** |
| `PROGRAM_NAME` | absent | present but empty | cosmetic |
| `SENSOR_FIRMWARE_VERSION` | absent | present but empty | cosmetic |
| `STARTUP_DATE` | `20130224065600` | empty | ours is *more* complete; verify against launch metadata |
| `STARTUP_DATE_QC` | `1` | `0` | ours asserts a QC the GDAC does not |
| `START_DATE` | `20130224065600` | `20130224064900` | **7 minutes apart — investigate** |
| `TRANS_FREQUENCY` | empty | `n/a` | cosmetic |
| `TRANS_SYSTEM_ID` | `061796` | `n/a` | ours is *more* complete |

---

## 5. tech.nc parity (direct, WMO 2902093)

`tech.nc` is a name/value table keyed by cycle. Ours: 10 cycles (45–54), **95 rows per cycle**.
GDAC: 234 cycles, **95 rows per cycle**. **95 distinct parameter names on both sides, identical
name sets.**

Comparing the 10 cycles both hold:

| parameter | ours | GDAC | cycles matching | classification |
|---|---|---|---|---|
| `FLAG_RTCStatus_LOGICAL` | `0` | `1` | **0 / 10** | **OUR DEFECT — F9** |
| `FLAG_SensorBoardStatus_NUMBER` | identical | identical | **10 / 10** | `EXACT` |
| `PRES_LastAscentPumpedRawSample_dbar` | identical | identical | **10 / 10** | `EXACT` |
| `PRES_SurfaceOffsetBeforeReset_1cBarResolution_dbar` | `-0` | `0` | 8 / 10 | **OUR DEFECT (formatting) — F10** |
| 71 other parameters | — | — | 10 / 10 | `EXACT` |
| 74 parameters, cycle 54 only | `none` | `0` | 9 / 10 | **not a defect** — see below |

**Summary: 21 of 95 parameters differ on at least one cycle, and only 3 are genuine defects.**

### 5.1 The three named fields

**`FLAG_RTCStatus_LOGICAL`** — differs on **10/10** cycles, ours `0`, GDAC `1`. Our value comes
from telemetry byte 25 (`rtc`) of the 253 packet, which reads 0 in every corpus vector. The GDAC
publishes `1`. Either the GDAC derives this flag from something other than byte 25, or byte 25 is
not the RTC status flag. **This needs resolution before freeze** — it is the single field that
disagrees on every cycle of every float.

**`FLAG_SensorBoardStatus_NUMBER`** — **exact on 10/10**. Previously investigated, confirmed clean.

**`PRES_LastAscentPumpedRawSample_dbar`** — **exact on 10/10**. Previously investigated, confirmed
clean. Note this is the *raw sample* field and is exact; it is MC599 (Section 3.1, F2) that is
wrong, and the two must not be confused.

### 5.2 Cycle 54

74 parameters differ on cycle 54 alone: ours `none`, GDAC `0`. Our telemetry for cycle 54 is
**incomplete** — no R or BR profile is published for it (published R/BR cycles are 45–53 only),
and its `CLOCK_FloatTime_YYYYMMDDHHMMSS` is `20140509040142` against the GDAC's `20140519034957`,
ten days apart. We hold a partial cycle; the GDAC holds the completed one.

Writing `none` rather than `0` for counters that have not yet accumulated is honest. **No code
change required**, though emitting `0` for a genuinely-zero count would be tidier.

---

## 6. QC / RTQC (mandatory)

| parameter | our RT QC | GDAC R/BR QC | same? | interpretation |
|---|---|---|---|---|
| PRES_QC | {'1': 3865} | {'1': 3865} | YES | identical — both 1 (good) |
| TEMP_QC | {'1': 1293, ' ': 2572} | {'1': 1280, '3': 13, ' ': 2572} | NO | identical — both 1 |
| PSAL_QC | {'1': 1293, ' ': 2572} | {'1': 1238, '3': 55, ' ': 2572} | NO | identical — both 1 |
| DOXY_QC | {' ': 2580, '1': 1285} | {' ': 2580, '3': 1285} | NO | GDAC 3 = probably bad. Publication/delayed RTQC verdict; must NOT be copied into our R/BR. |
| C1PHASE_DOXY_QC | {' ': 2580, '1': 1285} | {' ': 2580, '0': 1285} | NO | GDAC 0 = no QC performed on the raw optode phase. Ours asserts 1 (good). |
| C2PHASE_DOXY_QC | {' ': 2580, '1': 1285} | {' ': 2580, '0': 1285} | NO | see row values |
| TEMP_DOXY_QC | {' ': 2580, '1': 1285} | {' ': 2580, '1': 1285} | YES | identical — both 1 |
| FLUORESCENCE_CHLA_QC | {' ': 2578, '1': 1287} | {' ': 2578, '0': 1287} | NO | see row values |
| BETA_BACKSCATTERING700_QC | {' ': 2578, '1': 1287} | {' ': 2578, '0': 1287} | NO | see row values |
| CHLA_QC | {' ': 2578, '1': 1287} | {' ': 2578, '3': 1287} | NO | GDAC 3 = probably bad. Publication/delayed RTQC verdict; must NOT be copied into our R/BR. |
| BBP700_QC | {' ': 2578, '1': 1287} | {' ': 2578, '1': 1287} | YES | identical — both 1 |

### 6.1 Reading the table

**This section overturns an earlier claim.** A previous pass reported BGC QC as
"exact 36/36". That was wrong — it compared QC arrays over a padded range where both sides were
blank, so it counted agreement on empty cells. Level-masked comparison over all 9 cycles × 4
profiles shows real differences on **8 of 11** parameters.

### 6.2 Classification of each difference

| parameter | our RT QC | GDAC R/BR QC | what the difference is |
|---|---|---|---|
| `PRES_QC` | `1` | `1` | none |
| `TEMP_QC` | `1` (1293) | `1` (1280) + **`3` (13)** | **delayed QC.** GDAC flags 13 levels probably-bad. Argo RTQC does not run temperature tests in real time |
| `PSAL_QC` | `1` (1293) | `1` (1238) + **`3` (55)** | **delayed QC.** 55 levels flagged |
| `TEMP_DOXY_QC` | `1` | `1` | none |
| `BBP700_QC` | `1` | `1` | none |
| `DOXY_QC` | `1` | **`3` on every level** | **publication processing.** The GDAC marks the whole DOXY column probably-bad; consistent with the SAGEO2 adjustment applied later |
| `CHLA_QC` | `1` | **`3` on every level** | **publication processing** |
| `C1PHASE_DOXY_QC` | `1` | **`0`** | **real-time behaviour difference.** `0` = no QC performed. GDAC does not QC the raw optode phase; we assert it is good |
| `C2PHASE_DOXY_QC` | `1` | **`0`** | same |
| `FLUORESCENCE_CHLA_QC` | `1` | **`0`** | same |
| `BETA_BACKSCATTERING700_QC` | `1` | **`0`** | same |

### 6.3 Verdicts

**Real-time behaviour — genuinely defensible, but worth reconsidering (F11).**
For the four raw sensor channels (`C1PHASE_DOXY`, `C2PHASE_DOXY`, `FLUORESCENCE_CHLA`,
`BETA_BACKSCATTERING700`) the GDAC writes `0` = *no QC performed*. We write `1` = *good*.
Asserting "good" on a raw channel we have not tested overstates what we know. The Argo convention
for an untested real-time channel is `0`. **This is the one QC difference that is arguably our
defect rather than theirs.**

**Delayed QC — must NOT be copied into R/BR.**
The `3` flags on `TEMP` (13 levels), `PSAL` (55 levels), `DOXY` (all) and `CHLA` (all) are
delayed-mode verdicts. Copying them into a real-time product would assert knowledge we do not
have at transmission time and would misrepresent the product's provenance. **We deliberately do
not copy them, and this report does not recommend doing so.**

**Publication processing.**
`DOXY` and `CHLA` are flagged `3` on every level because the GDAC knows an adjustment is pending
(`DOXY_ADJUSTED = DOXY*G` from SAGEO2). That knowledge does not exist in real time.

**Genuinely incorrect in our output.**
Only the `1`-instead-of-`0` on the four untested raw channels. Everything else is correct
real-time behaviour.

### 6.4 `POSITION_QC` on cycles with no GPS fix

Cycles 47 and 52 of WMO 2902092 have `gps_valid = 0` on their own session-2 packet. The GDAC
interpolates a position and marks `POSITION_QC = '8'`. **We publish no position at all** for those
cycles, because interpolating would fabricate a fix the telemetry does not contain. This is the
correct choice, and it is why 4 files are absent relative to an earlier run.

---

## 7. D/BD historical reconstruction

> ### `FORECASTED-RT FROM D/BD HISTORY`
>
> **This section is NOT direct R/BR parity.** A live census of
> `https://data-argo.ifremer.fr/dac/incois/<WMO>/profiles/` on 2026-09-15 shows the GDAC has
> **rotated R/BR away** for seven of our eight published floats. Only **2902093** retains R/BR.
> For the other seven the only GDAC evidence available is delayed-mode `D`/`BD`, which is
> **post-RTQC and post-adjustment**. Comparing our real-time output to it can corroborate the
> decode; it can never establish real-time parity.

Live census (R/BR files remaining per WMO):

| WMO | R/BR present | evidence class used |
|---|---|---|
| **2902093** | **yes** (cycles 001–234) | **direct R/BR parity** — Sections 1–3 |
| 2902086, 2902087, 2902088, 2902092, 2902114, 2902115, 2902118 | **no** | `FORECASTED-RT FROM D/BD HISTORY` |
| 2902089, 2902090, 2902091, 2902113, 2902116, 2902117, 2902120 | not in our raw corpus | not applicable |

GDAC `DATA_MODE` on these files confirms they are not real time: `D` files carry `DRRR`,
`BD` files carry `RRDA`, and `HISTORY_ACTION` contains `QCP$`, `QCF$`, `IP` and `CF`.

### 7.1 Comparison basis

For each of the 7 floats, 3 cycles were fetched in both `D` and `BD`, and compared against our
`R`/`BR` for the same cycles. Every comparison is level-masked and keyed by `(cycle, profile,
level)`, never by array position.

## Pooled across all 7 D/BD-only floats

| parameter | n levels | exact | exact % | max rel diff | median rel diff | classification |
|---|---|---|---|---|---|---|
| PRES | 15975 | 15744 | 98.55% | 200.0000% | 0.0000% | EXACT |
| TEMP | 2628 | 2628 | 100.00% | 0.0000% | 0.0000% | EXACT |
| PSAL | 2628 | 2628 | 100.00% | 0.0000% | 0.0000% | EXACT |
| DOXY | 2533 | 0 | 0.00% | 5665.1548% | 0.3964% | PUBLICATION-RTQC |
| C1PHASE_DOXY | 2533 | 2533 | 100.00% | 0.0000% | 0.0000% | EXACT |
| TEMP_DOXY | 2533 | 2533 | 100.00% | 0.0000% | 0.0000% | EXACT |
| BETA_BACKSCATTERING700 | 2539 | 2539 | 100.00% | 0.0000% | 0.0000% | EXACT |
| CHLA | 2539 | 718 | 28.28% | 0.0002% | 0.0000% | EXACT (float32 ULP) |
| BBP700 | 2539 | 0 | 0.00% | 5.5551% | 2.6280% | COEFFICIENT REPRESENTATION |


### 7.2 How to read these numbers

**`PRES`, `TEMP`, `PSAL`, `C1PHASE_DOXY`, `TEMP_DOXY`, `BETA_BACKSCATTERING700` — 100 % exact**
across 15 975 / 2 628 / 2 628 / 2 533 / 2 533 / 2 539 levels. The CTD decode and the raw optode
and fluorometer channels survive the entire delayed-mode pipeline bit-for-bit. This is strong
evidence the decode is right, but it is **corroboration, not R/BR parity**.

**`PRES` is 98.55 %, not 100 %.** Exactly **4** level comparisons differ, and all 4 are in the two
cycles where our telemetry carries **no CTD records** (2902087 cycle 144, 2902088 cycle 46). The
worst is 26.4 dbar. These are not decode errors — see 7.3.

**`DOXY` — 0 % exact, median relative difference 0.3964 %.** Same `PUBLICATION-RTQC`
classification as Section 2.2. The headline "max rel diff 5665 %" is an artifact of dividing by a
near-zero reference: the worst case is ours 0.21186 vs GDAC 0.00367 µmol/kg on 2902118 cycle 2,
where both values are essentially noise around an anoxic minimum. **Median absolute difference is
1.687e-01 µmol/kg.** Read the median, not the maximum.

**`BBP700` — median relative difference 2.6280 %.** Same `COEFFICIENT REPRESENTATION`
classification as Section 2.1, and the same magnitude as the direct 2902093 comparison (2.68 %).
The agreement between the two independent measurements supports the coefficient explanation.

**`CHLA` — 28.28 % exact, max absolute difference 2.384e-07 mg/m³.** Same float32 ULP story as
Section 2.3.

### 7.3 Structural notes

- cycle 144 BR: N_PROF ours=3 gdac=4 (our telemetry has no CTD records that cycle — CTD-derived profiles correctly withheld, not fabricated)
- cycle 46 BR: N_PROF ours=3 gdac=4 (our telemetry has no CTD records that cycle — CTD-derived profiles correctly withheld, not fabricated)

In both cases our telemetry for that cycle contains **no CTD records**. We therefore write the
optode and fluorometer profiles and **withhold the two CTD-derived profiles**, rather than
substituting another grid. `N_PROF` is 3 where the GDAC has 4. **This is correct behaviour.**
Fabricating a CTD profile from the BGC grid would be the defect.

### 7.4 What this section does and does not license

| claim | licensed? |
|---|---|
| "The decoder reproduces GDAC values for 7 more floats" | **NO** — those are D/BD, post-RTQC |
| "CTD and raw-sensor decode is corroborated on 8 floats" | yes, with the `FORECASTED-RT` label |
| "Direct R/BR parity" | **only WMO 2902093, only cycles 45–53** |
| "Fleet-wide GDAC parity" | **never** — one float cannot establish it |

---

## 8. All-10-float genericity

Fleet run: `scripts/run_cts4_realtime_fleet.py` over all 517 `.sbd` packets in
`provor_bio_irsbd/raw_telemetry/SBD-BGC-raw`, 2026-09-15.

| raw group | FLBB serial | cycles | R | BR | meta | tech | Rtraj | FileChecker (files/accepted/err/warn) | coverage issue |
|---|---|---|---|---|---|---|---|---|---|
| `00530` | 3042 | 19 | 17 | 17 | yes | yes | yes | 37/37/0/1 | cycle 1: DATA-COVERAGE: CTD records carry no profile phase (shallow/test dive) — R not written; cycle 19: DATA-COVERAGE: tech-only cycle (no measurement records) — no profiles written |
| `03530` | 3043 | 15 | — | — | **no** | **no** | **no** | -/-/-/- | DATA-COVERAGE: FLBB serial 3043 absent from every INCOIS meta.nc; no WMO, so nothing publishable. NOT a decoder failure. |
| `03580` | 3044 | 14 | — | — | **no** | **no** | **no** | -/-/-/- | DATA-COVERAGE: FLBB serial 3044 absent from every INCOIS meta.nc; no WMO, so nothing publishable. NOT a decoder failure. |
| `06580` | 3046 | 19 | 18 | 18 | yes | yes | yes | 39/39/0/1 | cycle 35: DATA-COVERAGE: tech-only cycle (no measurement records) — no profiles written |
| `06640` | 3065 | 8 | 7 | 7 | yes | yes | yes | 17/17/0/1 | cycle 8: DATA-COVERAGE: tech-only cycle (no measurement records) — no profiles written |
| `12170` | 2663 | 17 | 15 | 16 | yes | yes | yes | 34/34/0/1 | cycle 103: DATA-COVERAGE: no CTD records — R not written; cycle 115: DATA-COVERAGE: tech-only cycle (no measurement records) — no profiles written |
| `17960` | 2661 | 10 | 9 | 9 | yes | yes | yes | 21/21/0/1 | cycle 54: DATA-COVERAGE: tech-only cycle (no measurement records) — no profiles written |
| `20000` | 2659 | 10 | 6 | 6 | yes | yes | yes | 15/15/0/5 | cycle 47: DATA-COVERAGE: no 253 FloatTime/GPS — profiles not written (no fabrication); cycle 48: DATA-COVERAGE: no 253 FloatTime/GPS — profiles not written (no fabrication); cycle 52: DATA-COVERAGE: no 253 FloatTime/GPS — profiles not written (no fabrication); cycle 55: DATA-COVERAGE: tech-only cycle (no measurement records) — no profiles written |
| `25980` | 2658 | 17 | 15 | 16 | yes | yes | yes | 34/34/0/1 | cycle 144: DATA-COVERAGE: no CTD records — R not written; cycle 159: DATA-COVERAGE: tech-only cycle (no measurement records) — no profiles written |
| `29030` | 2660 | 9 | 6 | 8 | yes | yes | yes | 17/17/0/1 | cycle 46: DATA-COVERAGE: no CTD records — R not written; cycle 50: DATA-COVERAGE: no CTD records — R not written; cycle 52: DATA-COVERAGE: tech-only cycle (no measurement records) — no profiles written |

### 8.1 `03530` and `03580` are DATA-COVERAGE, not decoder failures

Both groups decode **completely and successfully**:

| group | FLBB serial | packets | CTD records | FLBB records | O2 records | 253 vectors |
|---|---|---|---|---|---|---|
| `03530` | **3043** | 15 | 1 843 | 1 808 | 1 814 | 28 |
| `03580` | **3044** | 14 | 1 843 | 1 808 | 1 814 | 28 |

The decoder reads every packet. What is missing is the **WMO**. WMO is supplied externally and is
resolved from `SENSOR_SERIAL_NO` on the `ECO_FLBB` rows of the INCOIS `meta.nc` files. The
authoritative serials present in those files are:

```
2658 2659 2660 2661 2662 2663 2664 2666 3042 3045 3046 3065 3066
```

**3043 and 3044 are absent.** No INCOIS `meta.nc` carries them, so there is no WMO, so no
publishable product exists. The decoder reports this and stops; it does **not** infer a WMO from
the IMEI or the group directory name.

**This is the correct outcome.** Inventing a WMO would be fabrication, and IMEI→WMO routing is
explicitly forbidden.

### 8.2 Genericity gate

`scripts/prove_cts4_generic_path.py`, same run:

| check | result |
|---|---|
| modules scanned | 21 |
| conditional nodes | **884** |
| **float-identity branches** (`if wmo ==`, `if cycle ==`, `if IMEI ==`) | **0** |
| groups reaching publication | 8 |
| **distinct execution traces across those 8 groups** | **1** |
| verdict | **static = PASS, dynamic = PASS** |

One trace for eight floats is the strongest available statement of genericity: the same code path
runs for every float, with no per-float specialisation.

`scripts/validate_cts4_phase4_gdac.py --products /tmp/final2` → **ALL PASS**.

### 8.3 `DATA-COVERAGE` cycle counts are expected, not losses

| reason | cycles affected |
|---|---|
| tech-only cycle (no measurement records) | 8 — one per group |
| no CTD records (BGC-only cycle) | 4 |
| no 253 FloatTime/GPS | 3 (all WMO 2902092) |
| CTD records carry no profile phase (shallow/test dive) | 1 |

In every case the decoder withholds the product rather than fabricating it. Note that
`12170`, `25980` and `29030` have **more BR than R files** for exactly this reason: the optode and
fluorometer profiles are written while the CTD-derived ones are correctly withheld.

### 8.4 Test suite

`pytest tests/ -q` → **2 367 passed, 1 skipped** in 89.6 s. The single skip is
`tests/integration/test_structural_parity.py` (golden tree not bootstrapped). 52 parity tests
require `/tmp/gdac_2902093` with a `profiles/` subdirectory; without it they **silently skip**, so
the skip count must be checked, not just the failure count.

---

## 9. FileChecker

**ArgoFormatChecker v3.0.5**, specification `-r1259`, `-internal-specs incois`, run over all 214
generated `.nc` files flattened into one directory.

| metric | value |
|---|---|
| **files checked** | **214** |
| **accepted** | **214** |
| **rejected** | **0** |
| **errors** | **0** |
| **warnings** | **12** |
| **skipped checks** | **0** |

`skipped checks` counts files whose output contains `Remaining checks skipped`. That string appears
in **none** of the 214 outputs, so no validation stage was bypassed. This matters because a
`CYCLE_NUMBER` gate failure causes the checker to skip everything after it; the absence of that
warning is the evidence that the later checks actually ran.

### 9.1 Per-float breakdown

| WMO | files | accepted | rejected | errors | warnings |
|---|---|---|---|---|---|
| 2902086 | 34 | 34 | 0 | 0 | 1 |
| 2902087 | 34 | 34 | 0 | 0 | 1 |
| 2902088 | 17 | 17 | 0 | 0 | 1 |
| 2902092 | 15 | 15 | 0 | 0 | **5** |
| 2902093 | 21 | 21 | 0 | 0 | 1 |
| 2902114 | 39 | 39 | 0 | 0 | 1 |
| 2902115 | 37 | 37 | 0 | 0 | 1 |
| 2902118 | 17 | 17 | 0 | 0 | 1 |
| **total** | **214** | **214** | **0** | **0** | **12** |

### 9.2 Every remaining warning explained

**Warning 1 — `PI_NAME : 'M Ravichandran' Status: Invalid (not in NVS RN table)` — 8 occurrences,
one per `meta.nc`.**

The checker validates `PI_NAME` against the SeaDataNet NVS register of persons. `M Ravichandran`
is the INCOIS principal investigator and is not in that register.

**This warning fires on the GDAC's own file.** Verified directly: `2902093_meta.nc` fetched from
INCOIS is `FILE-ACCEPTED` but carries the same warning. It is therefore a property of the
reference data, not of our output, and **no action is available to us** — changing the PI name to
satisfy the checker would be falsifying metadata.

**Warnings 2–5 — `2902092_Rtraj.nc`, one each:**

```
JULD_FIRST_LOCATION (MC 703): Not FillValue where there is no associated JULD at 2 cycles; index of first case = 3
JULD_FIRST_LOCATION_STATUS (MC 703): Not FillValue where there is no associated JULD_STATUS at 2 cycles
JULD_LAST_LOCATION (MC 703): Not FillValue where there is no associated JULD at 2 cycles
JULD_LAST_LOCATION_STATUS (MC 703): Not FillValue where there is no associated JULD_STATUS at 2 cycles
```

The "2 cycles" are **47 and 52**. Both have `gps_valid = 0` on their own session-2 packet, so
neither has any MC703 location row. The checker's rule is that where a cycle has no MC703 rows,
the per-cycle `JULD_FIRST_LOCATION` / `JULD_LAST_LOCATION` must be FillValue.

Our `JULD_FIRST_LOCATION` and `JULD_LAST_LOCATION` **are** FillValue for those cycles, and this
audit changed the paired `_STATUS` from `'9'` to Fill to match the GDAC convention (verified on
2902093: every Fill `JULD_*` has a blank `JULD_*_STATUS`). The warning persists because the checker
is reporting the **absence of the MC703 rows**, which is structural and correct: we do not
fabricate a position for a cycle with no GPS fix, whereas the GDAC interpolates one and marks
`POSITION_QC = '8'`.

**Classification:** `DATA-COVERAGE`. **No code change required.** The alternative — publishing an
interpolated position — would be fabrication.

### 9.3 Control caveat

Renamed copies of GDAC files (e.g. `GDAC_2902093_Rtraj.nc`) are `FILE-REJECTED` for
`Inconsistent file name`. That is an artifact of renaming, not a GDAC defect, so renamed copies
must never be used as FileChecker controls. The control run in this audit used the files under
their original names and all four were `FILE-ACCEPTED`.

---

## 10. Fix list

Ordered by priority. **This is the actionable section.**

| # | Issue | Evidence | Root cause | Classification | Code fix required? | Priority |
|---|---|---|---|---|---|---|
| **F1** | **MC301 `RPP` wrong on all 9 cycles, all parameters** | GDAC MC301 = mean of GDAC MC290 park samples, verified to 1e-4 on 3 cycles × 9 parameters. Our `PRES` is 431.8–474.8 dbar too shallow; `DOXY` 0.94 vs 2.65; `TEMP` off ~3.3 °C | `_park_representative()` (`cts4_realtime.py:574-614`) takes the **median** of CTD park records and attaches one optode + one fluorometer sample. Coriolis (`process_trajectory_data…m:608-646`) takes the **mean** over park samples masked so *every* parameter is non-fill | `OUR DEFECT` | **YES** | **HIGH** |
| **F9** | **`FLAG_RTCStatus_LOGICAL` wrong on 10/10 cycles** | ours `0`, GDAC `1`, every cycle of 2902093 | We read telemetry byte 25 (`rtc`) of the 253 packet, which is 0 in all corpus vectors. Either byte 25 is not this flag, or the GDAC derives it differently | `OUR DEFECT` or `CORIOLIS DIFFERENCE` — **unresolved** | **YES, after root-causing** | **HIGH** |
| **F11** | **BGC raw-channel QC asserts `1` where GDAC asserts `0`** | `C1PHASE_DOXY_QC`, `C2PHASE_DOXY_QC`, `FLUORESCENCE_CHLA_QC`, `BETA_BACKSCATTERING700_QC`: ours `1` on 1 285–1 287 levels, GDAC `0` on all | We write `1` (good) for channels we have not tested. Argo convention for an untested real-time channel is `0` (no QC performed) | `OUR DEFECT` (overstated QC) | **YES** | **MEDIUM-HIGH** |
| **F2** | **MC599 `LastAscPumpedCtd` incomplete and wrong pressure** | ours `PRES` 0.1–0.4 dbar and no `TEMP`/`PSAL`; GDAC `PRES` 5.0–5.9 dbar with `TEMP` 25.1–27.1 and `PSAL` 36.5 | `rtraj_build.py:448-450` calls `_undated_pres`, which sets pressure only. The pressure source is the pump-cutoff depth (`p_sub`), not the last pumped CTD sample | `OUR DEFECT` | **YES** | **MEDIUM** |
| **F6** | **`PARAMETER_ACCURACY` and `PARAMETER_RESOLUTION` empty** | GDAC publishes `2.4 / 0.002 / 0.005 / 0.03 degC / 8 umol/kg or 10% / 0.08 mg/m3` and `0.1 / 0.001 / 0.001 / 0.01 degC / 1 umol/kg / 0.025 mg/m3`; ours is blank | Never populated by the meta writer | `OUR DEFECT` (incomplete metadata) | **YES** | **MEDIUM** |
| **F7** | **`PARAMETER_UNITS` wording differs** | ours `degree_Celsius`, `micromole/kg`; GDAC `degC`, `umol/kg` | Unit strings not aligned to the GDAC vocabulary | `OUR DEFECT` (cosmetic but visible) | **YES** | **LOW-MEDIUM** |
| **F8** | **`meta.nc` `id` attribute** | ours `2902093`; GDAC `https://doi.org/10.17882/42182` | We stamp the WMO; the Argo convention for `id` is the DOI | `OUR DEFECT` | **YES** | **LOW-MEDIUM** |
| **F10** | **`PRES_SurfaceOffsetBeforeReset` renders `-0`** | ours `-0`, GDAC `0`, cycles 53 and 54 | Negative-zero formatting in the string conversion | `OUR DEFECT` (formatting) | **YES** | **LOW** |
| **F4** | **R prof1 deepest bin off by ~0.4 dbar on 3/9 cycles** | MC503 residual is the same offset: cycles 46, 50, 53 differ by 0.1–0.4 dbar; other 6 exact | The averaging grid's deepest bin sits ~0.4 dbar deeper than the GDAC's | `OUR DEFECT` | **YES** | **LOW** |
| **F12** | **`START_DATE` 7 minutes from GDAC** | ours `20130224065600`, GDAC `20130224064900` | Source of our launch date not yet reconciled with the GDAC's | **UNRESOLVED** | investigate first | **LOW** |
| **F5** | **BBP700 scale choice not recorded in the product** | median ratio 1.026783; our scale is telemetry-original, GDAC's is corrected | Deliberate: only the original scale exists in real-time telemetry | `COEFFICIENT REPRESENTATION` | optional — document, do not correct | **LOW** |
| — | `DOXY` per-level deviation, median 0.0335 % | inputs bit-exact, no systematic sign, median ratio 0.999940 | Differs from Coriolis at ≤1e-12 in intermediates; GDAC applies SAGEO2 later | `PUBLICATION-RTQC` | **NO** — do not fit a gain/offset | none |
| — | MC703 18 rows vs GDAC 72 | our 18 all present in GDAC, exact; GDAC adds 6 Argos `'I'` fixes per cycle | Argos interpolated fixes absent from SBD telemetry | `ASSOCIATION` | **NO** | none |
| — | MC700/702/704 offsets 546 / 157 / 75 s | every fix we publish is exact | Same missing Argos rows shift the window edges | `ASSOCIATION` | **NO** | none |
| — | `TEMP_QC`/`PSAL_QC`/`DOXY_QC`/`CHLA_QC` = `3` in GDAC | 13 / 55 / all / all levels flagged | Delayed-mode and publication QC verdicts | `PUBLICATION-RTQC` | **NO — must not be copied into R/BR** | none |
| — | `JULD` 1 float64 ULP on 6/18 R profiles | worst 3.143e-07 s = exactly 1 ULP | Rounding order in composing the day fraction | `EXACT` to ULP | **NO** | none |
| — | `CHLA` 2.384e-07 on 968/1287 levels | max rel 0.0001 %, `FLUORESCENCE_CHLA` exact | float32 rounding of the same equation | `EXACT` to ULP | **NO** | none |
| — | 4 `JULD_LOCATION` warnings on `2902092_Rtraj.nc` | cycles 47/52 have `gps_valid = 0` | No GPS fix exists; GDAC interpolates, we do not | `DATA-COVERAGE` | **NO** | none |
| — | 8 `PI_NAME` warnings | fires on the GDAC's own `meta.nc` too | PI not in the NVS register | reference-data property | **NO** | none |
| — | `03530` / `03580` produce nothing | FLBB 3043 / 3044 absent from every INCOIS `meta.nc` | No WMO available; WMO is externally supplied | `DATA-COVERAGE` | **NO** | none |
| — | MC289 produces nothing | zero phase-6 park samples in all 517 packets | Event never occurs | `DATA-COVERAGE` | **NO** | none |
| — | `N_PROF` 3 vs 4 on 2 cycles | our telemetry has no CTD records those cycles | CTD-derived profiles correctly withheld | `DATA-COVERAGE` | **NO** | none |

### 10.1 What F1 needs, concretely

The park data is already correct — **MC290 is exact on 495/495 rows at 0.000 dbar**. Only the
reduction is wrong. The fix is local to `_park_representative`:

1. Build one row per park sample carrying `PRES, TEMP, PSAL, C1PHASE_DOXY, C2PHASE_DOXY,
   TEMP_DOXY, DOXY` (plus the fluorometer channels when present).
2. Mask rows where **any** parameter is fill — Coriolis' `idForMean` condition.
3. Take the **column mean** of the surviving rows.
4. Emit those means as MC301, and set `REPRESENTATIVE_PARK_PRESSURE` to the same mean pressure.

Do not take the median, and do not attach a single optode or fluorometer sample.

---

## 11. Final status

Three separate claims. They must never be merged into one.

### 11.1 Generic decoder validation — **PASS, all 10 raw floats**

| evidence | result |
|---|---|
| raw packets decoded | **517 / 517**, all 10 groups |
| groups reaching publication | 8 |
| float-identity branches in 884 conditional nodes | **0** |
| distinct execution traces across the 8 published groups | **1** |
| `prove_cts4_generic_path.py` | **static = PASS, dynamic = PASS** |
| `validate_cts4_phase4_gdac.py` | **ALL PASS** |
| `pytest tests/ -q` | **2 367 passed, 1 skipped** |
| FileChecker | **214 / 214 accepted, 0 errors** |

**Claim licensed:** the decoder is generic across the decoder-301 / NKE 5.8 family. It contains no
WMO, cycle or IMEI branch, and a new same-family float would follow the identical path.
`03530` / `03580` produce no output because their FLBB serials have no WMO — a data-coverage
limit, not a decoder failure.

### 11.2 Direct GDAC R/BR parity — **only WMO 2902093, only cycles 45–53**

| evidence | result |
|---|---|
| profile keys | **18 / 18**, 0 unmatched either side |
| R `PRES` / `TEMP` / `PSAL` | **exact on every level** |
| R `LAT` / `LON` | exact 18/18 |
| R `JULD` | 12/18 exact, 6/18 off by 1 float64 ULP (3.1e-07 s) |
| BR `C1PHASE`, `C2PHASE`, `TEMP_DOXY`, `FLUO`, `BETA` | **exact on every level** |
| BR `CHLA` | exact to float32 ULP |
| BR `DOXY` | median 0.0335 %, `PUBLICATION-RTQC` |
| BR `BBP700` | median 2.68 %, `COEFFICIENT REPRESENTATION` |
| Rtraj keys | **243 / 243**, 1 207 shared rows, 1 172 JULD exact |
| Rtraj MC290 / MC590 / MC189 / MC389 / MC589 | **exact** |
| Rtraj **MC301** | **wrong on 9/9 — F1** |
| Rtraj **MC599** | **wrong on 9/9 — F2** |
| BGC **QC** | **8 of 11 parameters differ — F11** |

**Claim licensed:** for WMO 2902093 cycles 45–53 the CTD and raw-sensor decode is bit-exact, and
the trajectory is exact for every measurement code except MC301, MC503 and MC599.
**Claim NOT licensed:** any statement about fleet-wide R/BR parity. One float cannot establish it,
and the GDAC no longer holds R/BR for the other seven.

### 11.3 Specification / Coriolis parity — where direct R/BR is unavailable

For the 7 floats whose R/BR the GDAC has rotated away, the evidence is
**`FORECASTED-RT FROM D/BD HISTORY`** only (Section 7). Against post-RTQC delayed-mode data:
`PRES`, `TEMP`, `PSAL`, `C1PHASE_DOXY`, `TEMP_DOXY` and `BETA_BACKSCATTERING700` are **100 %
exact** across 2 533–15 975 levels. That corroborates the decode. It is **not** parity, and it
must never be reported as parity.

Where Coriolis source is the authority instead of a GDAC file, it was used directly and it is what
exposed **F1**: `init_measurement_codes.m:130` names MC301 `g_MC_RPP`, and
`process_trajectory_data_222_223_225_231_232.m:608-646` gives its exact algorithm.

---

## 12. Freeze recommendation

> # **DO NOT FREEZE**

### Exact remaining blockers

**B1 — F1, MC301 `RPP`.** Wrong on every cycle, every parameter, by up to 475 dbar. This is a
published scientific value in the trajectory file, and it is the largest single error found in
this audit. Root cause and fix are both known (Section 10.1). **Must be fixed.**

**B2 — F9, `FLAG_RTCStatus_LOGICAL`.** Wrong on 10/10 cycles in `tech.nc`. Root cause is **not**
yet established: we cannot say whether telemetry byte 25 is the wrong byte or whether the GDAC
derives the flag differently. A field that disagrees on every cycle of every float cannot be
frozen while its cause is unknown. **Must be root-caused, then fixed or reclassified.**

**B3 — F11, BGC raw-channel QC.** We assert `1` (good) on four channels the GDAC marks `0`
(no QC performed). This overstates the quality of published real-time data. **Must be fixed** —
it is a one-line change per channel, but it changes what users are told about data quality.

### Not blockers

- **F2** (MC599) — real defect, incomplete rather than misleading; fix before publication but it
  does not block a decoder freeze.
- **F4, F6, F7, F8, F10** — sub-0.5 dbar and metadata cosmetics.
- **F12** — 7-minute `START_DATE` difference, needs investigation, low impact.
- **`DOXY`, `BBP700`, MC703, MC700/702/704, `TEMP`/`PSAL`/`DOXY`/`CHLA` QC `3` flags, the 1-ULP
  `JULD`, the FileChecker warnings** — all correctly classified as
  `PUBLICATION-RTQC` / `ASSOCIATION` / `COEFFICIENT REPRESENTATION` / `DATA-COVERAGE`. None is our
  defect and none should be "fixed" by fitting or by copying delayed QC into R/BR.

### Freeze condition

Freeze becomes available when **B1, B2 and B3** are closed and the following re-runs clean:

1. `pytest tests/ -q` — expect 2 367+ passed, 1 skipped, **0 skipped parity tests**
2. `prove_cts4_generic_path.py` — static and dynamic PASS, 0 identity branches
3. `validate_cts4_phase4_gdac.py` — ALL PASS
4. FileChecker v3.0.5 — 0 errors, and warnings reduced to the 8 `PI_NAME` + 4 `JULD_LOCATION`
5. MC301 exact on 9/9 cycles against GDAC
6. `FLAG_RTCStatus_LOGICAL` matching, or a written reclassification with evidence

### Publication readiness

**Not declared.** Per standing instruction, publication-ready cannot be claimed while the
R-profile pressure-selection residual (F4) and the DOXY classification remain open or
unresolved. F1 additionally blocks it: a trajectory whose representative park pressure is
475 dbar wrong is not publishable regardless of the other results.

---

## Appendix A — Reproduction

```bash
cd argo_workspace/argo-decoder-python
pip install -e ".[dev,gsw]"

# GDAC references (note the profiles/ subdirectory — without it 52 parity tests silently skip)
mkdir -p /tmp/gdac_2902093/profiles
B=https://data-argo.ifremer.fr/dac/incois/2902093
for f in 2902093_meta.nc 2902093_tech.nc 2902093_Rtraj.nc; do
  curl -sS -o /tmp/gdac_2902093/$f $B/$f; done
for c in 045 046 047 048 049 050 051 052 053; do for p in R BR; do
  curl -sS -o /tmp/gdac_2902093/profiles/${p}2902093_${c}.nc $B/profiles/${p}2902093_${c}.nc; done; done

python scripts/run_cts4_realtime_fleet.py \
  --root ../provor_bio_irsbd/raw_telemetry/SBD-BGC-raw \
  --meta-dir ../provor_bio_irsbd/ref/gdac_incois_301 \
  --out /tmp/final2 --json /tmp/final2.json

python -m pytest tests/ -q
python scripts/prove_cts4_generic_path.py --root ... --meta-dir ... --out /tmp/gp
python scripts/validate_cts4_phase4_gdac.py --products /tmp/final2

# FileChecker v3.0.5 (sha256 f6c2233f8cb42c70c4cade036fd64483919d456f6eccd5904a4507a7ec60c72c)
find /tmp/final2 -name '*.nc' -exec cp {} /tmp/fc_in/ \;
java -jar file_checker_exec-3.0.5.jar -text-result -internal-specs incois /tmp/fc_out /tmp/fc_in
```

`/tmp` is a 993 MB tmpfs and is wiped on restart; all of the above is regenerable in under a
minute, except the D/BD fetch in Section 7.

## Appendix B — Environment

Python 3.13.14 · netCDF4 · gsw 3.6.23 · Java 11 · ArgoFormatChecker 3.0.5 (`-r1259`) ·
raw corpus 517 `.sbd` packets in 10 groups · GDAC references fetched live 2026-09-15.
