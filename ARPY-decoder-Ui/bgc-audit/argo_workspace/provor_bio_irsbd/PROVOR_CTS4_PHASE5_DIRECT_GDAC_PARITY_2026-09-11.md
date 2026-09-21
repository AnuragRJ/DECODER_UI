# PROVOR CTS4/BGC — Phase 5: Direct INCOIS GDAC Parity Validation

**Date:** 2026-09-11
**Scope:** Final bounded validation phase. Architecture (R/BR + float-level
meta/tech + accumulating tech + accumulating Rtraj) accepted as-is; no
redesign.
**Products compared:** `/tmp/cts4_17960k/2902093/` (regenerated from raw SBD
telemetry this session) against the live INCOIS GDAC at
`https://data-argo.ifremer.fr/dac/incois/2902093/`.

> **Two claims from the (bg) progress entry written earlier today are
> retracted below** — the `p_sub` "9/9" result and the "BBP700 EXACT" result.
> Both were wrong. See §6.

---

## 1. Headline result

Direct R/BR parity against a real GDAC product is now **demonstrated**, not
inferred. For float 2902093 (group 17960), cycles 45–53:

| Aspect | Result |
|---|---|
| R prof1 core CTD (PRES/TEMP/PSAL) | **exact, 0.000 on 9/9 cycles** |
| R prof2 near-surface (PRES/TEMP/PSAL) | **exact, 0.000 on 9/9 cycles** |
| BR level counts | **exact 36/36** |
| C1PHASE / C2PHASE / TEMP_DOXY / FLUORESCENCE_CHLA / BETA_BACKSCATTERING700 | **bit-exact (maxabs 0)** |
| CHLA / CHLA_FLUORESCENCE | maxabs 2.4e-07 (float32 ulp); 319/1287 bit-exact |
| `VERTICAL_SAMPLING_SCHEME` | **exact 72/72 strings** |
| Rtraj event JULDs (MC 89/100/150/250/300/450/500/600) | **exact, worst 0.0000 min over 72 pairs** |
| tech rows (95/cycle, GDAC order) | **93/95 exact**; 2 = documented UNKNOWN |
| FileChecker v3.0.5, INCOIS internal specs | **21/21 FILE-ACCEPTED, 0 errors, 0 warnings** |
| DOXY | maxabs 0.0947 µmol/kg, maxrel 0.86% — **unresolved** |
| BBP700 | maxrel 3.8–5.4% — **explained**, coefficient provenance (§5) |
| R prof3/prof4 reference levels | counts off by 1–2 on 13/18 pairs — **unresolved** |
| Rtraj MC 290 / 590 | absent from our output — **290 adjudicated & implementable; 590 not yet** |

---

## 2. Which floats can be validated at all

I fetched the `profiles/` listing for all 12 INCOIS WMOs. R/BR files exist
for exactly one of them:

| WMO | R | BR | Mode |
|---|---|---|---|
| **2902093** | **702** | **468** | **R234 / BR234 / SR234, cycles 001–234 complete** |
| 2902086 | 0 | 732 | D/BD only |
| 2902087 | 0 | 969 | D/BD only |
| 2902088 | 0 | 684 | D/BD only |
| 2902089 | 0 | 386 | D/BD only |
| 2902090 | 0 | 48 | D/BD only |
| 2902091 | 0 | 39 | D/BD only |
| 2902092 | 0 | 446 | D/BD only |
| 2902114 | 0 | 852 | D/BD only |
| 2902115 | 0 | 714 | D/BD only |
| 2902118 | 0 | 783 | D/BD only |
| 2902116 / 2902117 | 0 | 0 | no profiles |

**Consequence for the second group.** The instruction was to validate group
**06580 / FLBB 3046**, which resolves to **WMO 2902114**. 2902114 publishes
**852 D/BD files and zero R/BR**. Direct R/BR parity for the second group is
therefore **genuinely unavailable from the GDAC** — and this was established
by actively checking the live route, not by assuming it. D/BD are
Coriolis-reprocessed delayed-mode products; using them as a real-time parity
target is a category error, so they are retained only as
PUBLICATION-REPROCESSED evidence.

2902093 (group 17960) is the only float in the fleet where a real-time R/BR
target exists, so it carries the entire direct-parity claim.

---

## 3. Full discrepancy matrix

Keyed by `(cycle, profile)` for profiles and `(cycle, MC)` for Rtraj — never
by array position. "Compared?" = did an actual array/field comparison run
this session.

### 3.1 Profile files (R and BR)

| Item | Our output | INCOIS reference | Compared? | Exact differences | Classification |
|---|---|---|---|---|---|
| File inventory, cycles 45–53 | 9 R + 9 BR | 9 R + 9 BR | yes | none | **GDAC PARITY VERIFIED** |
| Cycle numbers | 45–53 | 45–53 | yes | none (after §6 fix) | **GDAC PARITY VERIFIED** |
| N_PROF (R and BR) | 4 | 4 | yes | none | **GDAC PARITY VERIFIED** |
| N_PARAM | R 3 / BR 6 | R 3 / BR 6 | yes | none | **GDAC PARITY VERIFIED** |
| Profile 1 = primary CTD, `PRES > p_sub` | ✔ | ✔ | yes | none | **GDAC PARITY VERIFIED** |
| Profile 2 = near-surface, `PRES ≤ p_sub` | ✔ | ✔ | yes | none | **GDAC PARITY VERIFIED** |
| Profiles 3/4 = pressure-only reference levels | ✔ | ✔ | yes | structure only | **GDAC PARITY VERIFIED** (structure) |
| R prof1 PRES/TEMP/PSAL | 143–144 levels | 143–144 levels | yes | **0.000 / 0.000 / 0.000** | **GDAC PARITY VERIFIED** |
| R prof2 PRES/TEMP/PSAL | 6 levels | 6 levels | yes | **0.000 / 0.000 / 0.000** | **GDAC PARITY VERIFIED** |
| R prof3/prof4 level counts | 144 | 143 (cyc45 p3) | yes | ±1–2 on 13/18 pairs | **UNKNOWN** (§4) |
| R prof3/prof4 pressures | — | — | yes | maxdPRES 0.4–0.7 dbar; ~78 our-only vs ~77 GDAC-only | **UNKNOWN** (§4) |
| BR level counts | 36 | 36 | yes | none | **GDAC PARITY VERIFIED** |
| C1PHASE_DOXY | — | — | yes | **maxabs 0** | **GDAC PARITY VERIFIED** |
| C2PHASE_DOXY | — | — | yes | **maxabs 0** | **GDAC PARITY VERIFIED** |
| TEMP_DOXY | — | — | yes | **maxabs 0** | **GDAC PARITY VERIFIED** |
| FLUORESCENCE_CHLA | — | — | yes | **maxabs 0** | **GDAC PARITY VERIFIED** |
| BETA_BACKSCATTERING700 | — | — | yes | **maxabs 0** | **GDAC PARITY VERIFIED** |
| CHLA | — | — | yes | maxabs 2.4e-07; 319/1287 bit-exact | **GDAC PARITY VERIFIED** (float32 ulp) |
| CHLA_FLUORESCENCE | derived CHLA | identical to CHLA | yes | maxabs 2.4e-07 | **GDAC PARITY VERIFIED** |
| BBP700 | telemetry scale 1.883e-06 | certificate scale 1.86e-06 | yes | maxrel 3.8–5.4%, median 2.68% | **EXPECTED** (§5) |
| DOXY | gsw in-situ density chain | — | yes | maxabs 0.0947, maxrel 0.86% | **UNKNOWN** (§4) |
| `VERTICAL_SAMPLING_SCHEME` | generated from own grid | per-profile | yes | **72/72 exact** | **GDAC PARITY VERIFIED** |
| QC strings | blank where data present | blank where data present | yes | none | **GDAC PARITY VERIFIED** |
| `PRES_QC` | absent | absent | yes | none | **GDAC PARITY VERIFIED** |
| DATA_MODE | all `R` | 3×`R` + 1×`A` on BR044 | yes | 1 profile/cycle | **PUBLICATION-RTQC** (§3.4) |
| Cycle 54 profiles | not written | not written | yes | n/a | **DATA-COVERAGE** |

### 3.2 Float-level products

| Item | Our output | INCOIS reference | Compared? | Exact differences | Classification |
|---|---|---|---|---|---|
| One meta / tech / Rtraj per float | ✔ | ✔ | yes | none | **GDAC PARITY VERIFIED** |
| No D/BD in production | ✔ | n/a | yes | none | **SPEC/CORIOLIS PASS** |
| tech rows per cycle | 95 | 95 | yes | none | **GDAC PARITY VERIFIED** |
| tech row values (cyc45) | 93/95 exact | 95 | yes | 2 rows (§3.3) | **GDAC PARITY VERIFIED** |
| `CLOCK_FloatTime_YYYYMMDDHHMMSS` | matches | matches | yes | none | **GDAC PARITY VERIFIED** |
| `PRES_LastAscentPumpedRawSample_dbar` | `p_sub` from telemetry | `p_sub` | yes | **25/25 exact** (2 floats) | **GDAC PARITY VERIFIED** (§6) |
| `FLAG_RTCStatus_LOGICAL` | `0` | `1` | yes | 1 row | **UNKNOWN** (§3.3) |
| `FLAG_SensorBoardStatus_NUMBER` | `none` | `0` | yes | 1 row | **UNKNOWN** (§3.3) |
| Rtraj N_PARAM | 12 | — | yes | — | **SPEC/CORIOLIS PASS** |
| Rtraj DATA_MODE | all `R` | all `R` | yes | none | **GDAC PARITY VERIFIED** |

### 3.3 The two remaining tech UNKNOWNs

Both survive a targeted search of the Argo manuals, the NKE PROVOR-II
PROVBIO-II manual, the Coriolis chain, the telemetry itself, and the GDAC
files. Neither field is carried in any msg-250/253 payload we receive, and no
specification defines the value INCOIS writes. They remain explicit
fill/`none` with the evidence recorded. Classification: **UNKNOWN** — retained
deliberately rather than guessed. `FLAG_SensorBoardStatus_NUMBER` is emitted
as the literal string `none`, never as a fabricated `0`.

### 3.4 RTQC contamination in the reference

GDAC `BR2902093_044.nc` profile 4 carries `DATA_MODE = 'A'` with
`HISTORY_ACTION = 'QCP$QCP$QCP$QCP$'` and `'QCF$QCF$QCF$QCF$'`. That is
Coriolis real-time QC post-processing applied **after** publication. Our
pipeline is real-time-only and must not reproduce it. Classification:
**PUBLICATION-RTQC**. This is the one place where "our file differs from the
GDAC file" is the *correct* outcome.

---

## 4. Unresolved items

### 4.1 DOXY, maxrel 0.86%

Symmetric ±0.8% residual, not a one-sided scale error. Tested and **rejected**:
the sigma-0 density hypothesis (re-scaling our DOXY by ρ_in-situ/σ₀ makes it
*worse*, 0.87–1.05%). Correlations: r = −0.10 vs C1PHASE, r = 0.01 vs
TEMP_DOXY, r = 0.04 vs PRES — no explanatory variable found. Our TEOS-10
in-situ density is the closer of the two formulations tested.

### 4.2 R prof3/prof4 reference-level selection

These are pressure-only levels (TEMP and PSAL entirely 99999 in both files).
Our counts run 1–2 high on 13 of 18 profile pairs, maxdPRES 0.4–0.7 dbar,
with ~78 our-only vs ~77 GDAC-only pressures. The *set* of pressures differs,
so this is a selection-rule difference, not a precision difference. Not yet
pinned.

### 4.3 Rtraj MC 590

See §7.

---

## 5. BBP700 — explained, deliberately not "fixed"

GDAC `2902093_meta.nc` publishes:

```
BBP700=2*pi*khi*((BETA_BACKSCATTERING700-DARK_BACKSCATTERING700)
                 *SCALE_BACKSCATTERING700-BETASW700)
SCALE_BACKSCATTERING700=1.86e-06, DARK_BACKSCATTERING700=51, khi=1.097
```

The float's own msg-250 `FlbbFree` carries **`scale_bb = 1.883e-06`**
(`dark_bb = 51`, matching). Our chain uses the telemetry value; GDAC used the
Wetlabs factory certificate value. Substituting 1.86e-06 into **our own**
chain collapses the residual to float32 noise on all nine cycles:

| cycle | telemetry scale | certificate scale |
|---|---|---|
| 45 | 3.7749% | 0.00048% |
| 46 | 4.1561% | 0.00018% |
| 47 | 3.9962% | 0.03670% |
| 48 | 5.3702% | 0.00014% |
| 49 | 4.2332% | 0.00112% |
| 50 | 3.9304% | 0.00047% |
| 51 | 4.0127% | 0.00169% |
| 52 | 4.0823% | 0.00019% |
| 53 | 3.9441% | 0.00159% |

Independent confirmation that `BETASW700` is **not** the cause: solving
GDAC's own BBP700 back for BETASW700 reproduces our `equations.beta_sw` to
six significant figures at every sampled depth (6.01489e-05 vs 6.0149e-05 at
the surface; 6.21324e-05 vs 6.2132e-05 at 1462 dbar).

**Classification: EXPECTED.** A documented coefficient-provenance difference.
Overwriting the transmitted calibration with the published coefficient would
be blind GDAC copying, which the constraints forbid, and the telemetry value
is the authoritative record of how the float was actually configured. The
telemetry value is kept; both are reported.

---

## 6. Retractions — two (bg) claims were false

### 6.1 `p_sub` was not being published at all

The (bg) entry claimed `p_sub` matched GDAC on 9/9 cycles. That was tested on
one float, and — more importantly — **the code never used it**. Tech row 17
was populated from `float(cd.ctd[-1].pres_dbar)`, the shallowest CTD sample
(~0.2 dbar), so every published value was wrong on both floats.

After the fix (row 17 now takes `CtdFree.p_sub`):

| Float | Cycles | Exact |
|---|---|---|
| 2902093 | 45–53 | **9/9**, difference 0.000000 |
| 2902086 | 99–114 | **16/16**, difference 0.000000 |
| both | c54, c115 | `none` vs a GDAC value — tech-only cycles, no CTD packet, no `p_sub` in telemetry (**DATA-COVERAGE**) |

25/25 exact where the telemetry carries the field, on two independent floats.

### 6.2 BBP700 was never exact

The (bg) entry recorded "BBP700 EXACT (maxabs ≤ 2.4e-7)". That figure belongs
to CHLA. Measured properly on BR profile 4, 1287 levels across 9 cycles:
**0 bit-exact**, maxabs 5.12e-05, maxrel 5.37%. The wrong figure was present
in the earlier runs too (`…17960f/j/k` all identical), so the mis-measurement
predates this session and was recorded as a pass. Corrected in §5.

### 6.3 A change tried and reverted

Restricting the CTD→BGC nearest-pressure association to the profile phase
(excluding 18 park-band records at 1008–1028 dbar) was implemented and
measured to be a **no-op** — maxrel identical to five decimals on cyc45/46
both ways. Park pressures are never the nearest match for a profile-phase BGC
level. The change was reverted rather than left as dead complexity.

---

## 7. Rtraj MC 290 / 590 adjudication

The (bg) claim that both are unimplementable is **falsified for MC290**.

### 7.1 MC 290 — fully derivable, verified against telemetry

Structure per cycle: 3 rows × N park samples (2902093 cyc45 → 18 samples →
54 rows). Within a triplet the rows are 1–8 s apart and each carries exactly
one sensor group:

- row A → DOXY only
- row B → CHLA + BBP700 only
- row C → TEMP + PSAL only

JULD is 12-h spaced across triplets, anchored on the cycle's first park
sample (first MC290 JULD − MC250 JULD = 0.005–0.017 h). `JULD_STATUS = '2'`,
LAT/LON = 99999.

**PRES verified exact against telemetry park CTD on cyc45, 18/18 in all three
streams:**

```
CTD  rows: [1013.4, 1008.3, 1016.7, 1013.0, 1012.4, 1020.0, ...]  == ours
O2   rows: [1008.3, 1016.7, 1013.0, 1012.4, 1012.4, 1020.0, ...]  == ours, shifted by one
FLBB rows: [1008.3, 1016.7, 1013.0, 1012.4, 1012.4, 1020.0, ...]  == ours, shifted by one
```

The one-sample offset of the DOXY and FLBB triplets relative to the CTD
triplet is part of the published product and must be reproduced, not
simplified.

**Verdict: implementable from telemetry alone. No external input needed.**
Not yet coded.

### 7.2 MC 590 — mechanism not yet pinned

The ascent CTD series decimated by a 10-sample stride (index deltas repeat
−10 with −1/0 pairs at band boundaries), 29 rows/cycle, `JULD_STATUS = '2'`,
no coordinates, first row 115–163 s after MC500. But only **21 of 29** GDAC
pressures are found in our decoded ascent at 0.05 dbar, and the matched
indices are not a clean stride. Implementing it now would mean copying one
GDAC product rather than reproducing a mechanism.

**Verdict: deferred. Not classified as unimplementable — the evidence is
recorded and the gap is specific.**

### 7.3 MC 289 — discovered missing this session

Our output emits 26 MC codes; GDAC has 29. Missing: **289, 290, 590**. MC289
was not on the earlier list. It appears on only **12 of 235 cycles** (44,
119, 120, 150, 151, 160, 162, 192, 193, 198, 217, 223) — 27 rows total — so
it is a sporadic event code, not a per-cycle one. Not yet adjudicated.

Total missing rows across cycles 45–53: 756 (all MC290 + MC590; MC289
contributes 0 in this window).

---

## 8. FileChecker

Version **3.0.5**, re-confirmed as the latest release via the GitHub releases
API this session. Jar sha256 `f6c2233f8cb42c70c4cade036fd64483919d456f6eccd5904a4507a7ec60c72c`.

```
java -jar file_checker_exec-3.0.5.jar -text-result -internal-specs incois <out> <in>
```

On all 21 products: **21/21 `STATUS: FILE-ACCEPTED`, 0 errors, 0 warnings.**
Before the `VERTICAL_SAMPLING_SCHEME` rewrite the same run produced 36
warnings flagged `*** WILL BECOME AN ERROR ***`; those are gone.

---

## 9. Gates

| Gate | Result |
|---|---|
| `pytest tests/` | **2295 passed, 1 skipped, 0 failed** |
| `scripts/validate_cts4_phase4_gdac.py` | **RESULT: ALL PASS** |
| mypy strict (new modules) | 0 errors |
| FileChecker v3.0.5, INCOIS specs | 21/21 ACCEPTED, 0 errors |

`tests/test_provor_cts4_phase4_products_integration.py` was updated to the
**corrected** contract (cycle +1: files 099–114, skips 103/115, BR099 DOXY
140 levels, BBP700 141 levels). The old expectations encoded the off-by-one
and were not restored. `process_float` also now emits no BR profile for a
sensor with zero profile-phase records instead of raising (12170 cycle 103
has no optode stream) — DATA-COVERAGE, never a fabricated grid.

---

## 10. Final recommendation

**GDAC parity is demonstrated** for the real-time product on float 2902093:
R profile 1 and 2 core CTD are bit-exact, five BGC parameters are bit-exact,
CHLA is exact to float32 ulp, `VERTICAL_SAMPLING_SCHEME` is exact on all 72
strings, Rtraj event JULDs are exact on all 72 pairs, 93/95 tech rows are
exact, and FileChecker accepts all 21 files with no warnings.

**That claim is bounded and must not be generalized.** Specifically:

1. **It rests on one float.** 2902093 is the only WMO in the fleet publishing
   R/BR. The requested second group (06580 → 2902114) publishes D/BD only, so
   its R/BR parity is **GDAC PARITY UNAVAILABLE** — established by checking
   the live route, not assumed.
2. **DOXY (0.86%) and R prof3/4 level selection remain unexplained.** Both
   are UNKNOWN, not EXPECTED.
3. **MC290 is adjudicated but not implemented; MC590 and MC289 are not
   implemented.** Our Rtraj is missing 756 rows across the nine validated
   cycles.
4. **BBP700 parity requires the certificate scale.** With the telemetry scale
   we carry, it differs by up to 5.4%.

**Recommendation: not publication-ready.** The blockers, in order, are
MC290 implementation (evidence complete, work is mechanical), MC590/MC289
adjudication, the DOXY residual, and R prof3/4 level selection. Two tech
UNKNOWNs are acceptable to ship with documented evidence.

Spec/Coriolis parity and FileChecker acceptance are **not** being offered as
substitutes for the GDAC comparison anywhere in this report, and the
PUBLICATION-RTQC difference on BR044 profile 4 is a case where differing
from the GDAC file is correct.
