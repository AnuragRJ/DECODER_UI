# Profile JULD investigation — re-analysis (Coriolis precedence vs GDAC vs ours)

**Date:** 2026-08-19 · **Type:** investigation only — **no code modified**.
**Question:** the remaining JULD/profile-date mismatch. Verified chain:
APF9 manuals → Coriolis source → raw telemetry → current Python → GDAC.

---

## 1. Coriolis precedence — verified from source (GitHub `main`, 2026-08-19)

**Profile date** (`decArgo_soft/soft/sub/add_profile_date_and_location_apx_argos.m`):

```
profJulD = ascentEndTime   (cycleData.ascentEndTime, if defined)
     else transStartTime  (cycleData.transStartTime, if defined)
     else firstMsgTime    (cycleData.firstMsgTime, if defined)
```

**Where each comes from** (`update_surf_data.m`, `compute_apx_times.m`,
`compute_apx_TST.m`):

| field | derivation |
|---|---|
| `firstMsgTime` | `min([argosLocDate; argosDataDate])` — earliest reception of the cycle (set in `decode_apex_argos_data.m`); NOT a fix time |
| `transStartTimeAdj` | **TST2 (improved method) if available, else TST1 (TWR method)**. TST2 = BLK extrapolation: from message-1 **BLK** counter + reception dates, `TST = date2 − (num2−1)·(date2−date1)/(num2−num1)` over pairs with distinct block numbers (BLK=1 excluded when possible; roll-over +256 corrected; values rounded to seconds; `select_a_value` = most frequent). TST1 needs `transRepPeriod` + `profileLength` config. |
| `ascentEndTimeAdj` | `transStartTimeAdj − 10/1440` (10 minutes), decoder ids not in {1021,1022} |
| profile **location** | first **good** (QC=1) fix of the cycle → `locationDate` (separate from the profile date) |

So the documented Coriolis precedence for the **profile date** is
ascent-end → transmission-start → first-message, where the transmission
start is the **BLK-extrapolated** TST (not the float's own clock), and the
ascent end is TST − 10 min. The float's own clock (EPOCH+TINIT) appears
only as `transStartTimeFloat`, which is **not** used for the adjusted TST.

## 2. What GDAC actually publishes — measured, per float family

For every shared cycle we computed all candidates (project trusted parser)
and compared with GDAC's mono-profile JULD (fetched 2026-08-19):

| float | family / mode | GDAC profile JULD equals | evidence |
|---|---|---|---|
| 2901339 (71) | 1005 / D | **TST (BLK method #2)** | 69/72 cycles within 120 s; many **0-second** matches (e.g. 2901328 cyc2/6/7/9 = 0 s) |
| 2901350 (67) | 1005 / D | **TST (BLK)** | 65/66 within 120 s |
| 2901328 (86) | 1005 / D | **TST (BLK)** | 58/86 within 120 s; rest = reception-set variants |
| 2901304 (20) | 1005 / D | **first fix (JULD == JULD_LOCATION)** | +0 s on all 20; our JULD exact on 16/20 |
| 2902203 (3) | 1010 / R | **first fix (JULD == JULD_LOCATION)** | our JULD **exact on 3/3** (<2 s) |
| 2902206 (3) | 1010 / R | first fix | 0 overlap (GDAC cycles stop at 352) |
| 2902222/23/24 (8) | 1010 / R | first fix (mostly) | JULD == JULD_LOCATION on 7/8 (2902222 cyc328: −4003 s GDAC-side inconsistency); residual deltas = reception-set |
| Coriolis `AET` (TST−10 min) | — | **published by nobody** | zero matches fleet-wide |

**INCOIS's own files are internally inconsistent**: the three old 1005
D-mode floats (2901339/50/28) publish **TST** (their older/DM-era chain,
`JULD ≠ JULD_LOCATION`), while 2901304 and all R-mode 1010 files publish
**first fix** (`JULD == JULD_LOCATION`), and even Coriolis's current AET
precedence matches **no** GDAC subset.

## 3. Our implementation vs GDAC (measured, fresh decode)

| float | shared | exact (<2 s) | <1 min | <10 min | ≥10 min |
|---|---|---|---|---|---|
| 2901304 | 20 | 16 | 0 | 2 | 2 |
| 2901328 | 86 | 1 | 0 | 6 | **79** |
| 2901339 | 71 | 0 | 1 | 15 | **55** |
| 2901350 | 67 | 0 | 0 | 16 | **51** |
| 2902203 | 3 | **3** | 0 | 0 | 0 |
| 2902222 | 3 | 1 | 0 | 0 | 2 |
| 2902223 | 3 | 0 | 0 | 0 | 3 |
| 2902224 | 2 | 0 | 0 | 0 | 2 |
| **total** | **255** | **21** | 1 | 39 | **194** |

Our JULD = first **selected fix** of the kept profile burst. Two distinct
causes of the ≥10-min cells:

1. **1005 D-mode TST convention (185 profiles: 2901328×79, 2901339×55,
   2901350×51):** GDAC's JULD = transmission start (before the first
   reception); ours = first fix (after it). Reproducible in principle
   (TST2 matches GDAC to 0 s) but see §5.
2. **Reception-set / first-good-fix differences (1010s + 2901304 cyc15/17):**
   GDAC's JULD = their first good (QC=1) fix; ours = our first fix. When
   their delivery lacks our early fixes (2902222 cyc328: their JULD
   13:50 vs our first fix 06:17; 2902223 cyc328/329: +5.5 h) or vice
   versa, no computation from our telemetry reproduces it. 2902224
   cyc325/326: our mono JULD anchors to the *kept* burst's first fix
   (Jan-2 00:28) instead of the surfacing's first fix (Jan-1 19:24:55)
   — our own Rtraj MC702 for the same cycle uses 19:24:55 (matches GDAC's
   MC702); this is the one generic fixable nuance (§4).

## 4. Proposed change (small, generic, optional) — burst-anchor alignment

**Only the 2902224-style multi-burst nuance is FIXABLE.** For an output
cycle assembled from several raw bursts (repeated-suffix split), the mono
profile's JULD / JULD_LOCATION should be the **surfacing's earliest Argos
fix** (the min fix time across all bursts mapped to that output cycle),
not the first fix of the richest kept burst. This aligns the mono JULD
with our own Rtraj MC702 (already the surfacing's first fix) and with
GDAC's convention (JULD == JULD_LOCATION).

- Where: `platforms/apex_argos/decoder.py` — track per-output-cycle
  earliest fix alongside the mono dedup, and stamp `juld` /
  `juld_location` from it when the kept dataset is chosen.
- Impact: 2902224 cyc325 JULD 2026-01-02T00:28 → **2026-01-01T19:24:55**
  (GDAC 19:25:16 — within 21 s); cyc326 00:22 → 17:32 (matches GDAC's
  MC702; GDAC's own mono JULD there is a QC-filtered fix we cannot see —
  see §5). **No other float changes** (single-burst cycles: JULD already
  the cycle's first fix; 2901304/1005s/2902203 unchanged).
- This is an internal-consistency improvement (mono ≡ Rtraj) with a small
  net parity gain (1 cell exact, 1 cell moved to the MC702-consistent
  value); it does NOT touch the anchor convention (first fix) itself.

**Rejected alternatives (with reasons):**

| option | would match | would break | verdict |
|---|---|---|---|
| JULD = TST (BLK method #2), generic | 185 old D-mode profiles | 2901304 (20) + all R-mode 1010s (JULD==JULD_LOCATION, +0 s in GDAC) | **Rejected** — no spec/Coriolis basis for TST over the current files; era-specific rule forbidden |
| JULD = AET (Coriolis current precedence) | **nothing** (GDAC never publishes AET) | everything (10 min shift on every cycle) | **Rejected** — zero parity gain |
| first-*good*-fix (QC=1) filter | some 1010 cells | unknown QC of our fixes; changes 2902203 (currently 3/3 exact) | **Rejected** — no evidence our QC equals theirs |
| per-float/per-era rules | — | — | **Forbidden** (no WMO-specific branches) |

## 5. Classification

- **Overall JULD convention: NOT FIXABLE.** (a) GDAC's own fleet uses two
  different conventions (TST on the old 1005 D-mode trio; first-fix on
  2901304 and all R-mode 1010s); (b) Coriolis's documented precedence
  (AET→TST→firstMsg) matches no GDAC subset — AET is published by
  nobody; (c) the 1010 residual deltas are reception-set differences
  (their first good fix vs ours — their delivery is not in our
  telemetry); (d) our first-fix anchor matches INCOIS's **current**
  R-mode practice (JULD == JULD_LOCATION, verified +0 s), matches
  2901304 16/20, and matches 2902203 3/3 exactly. Scientifically our
  choice is sound (community convention: profile JULD = first surface
  location); the D-mode TST values are a DM-era artefact of the old
  chain, not a spec requirement (UM defines JULD as "the date of the
  profile"; Coriolis itself moved to AET, which INCOIS does not use).
  Confidence: **HIGH**.
- **Burst-anchor nuance (2902224 cyc325/326): FIXABLE** as the small
  generic change in §4 (internal mono≡Rtraj consistency; 1 cell becomes
  exact vs GDAC). Confidence **HIGH** on mechanism; parity effect on
  cyc326 is a known tradeoff (moves from −53 min to −6 h vs GDAC's
  QC-filtered mono, while matching GDAC's MC702).
- **Missing evidence (data, not code):** INCOIS's received ARGOS fix set
  + QC for 2902222/2902223 (would resolve the ±5.5 h cells); INCOIS's
  DM-chain JULD rule for the 1005 trio (would confirm TST as their
  historical convention).

## 6. Regression-test plan (if §4 is approved)

1. Unit (decoder): a cycle assembled from two bursts with different first
   fixes → mono JULD/JULD_LOCATION = the earlier (surfacing) fix; Rtraj
   MC702 and mono JULD equal.
2. Integration (2902224): decode → R2902224_325 JULD ==
   2026-01-01T19:24:55 (±2 s), JULD == JULD_LOCATION, equal to the Rtraj
   MC702; R326 JULD == surfacing first fix (17:32).
3. Regression: 2901304 (16/20 exact preserved), 2902203 (3/3 exact
   preserved), 2901328/39/50 (JULD cells unchanged), full suite + NC3 +
   FileChecker meta/tech/Rtraj accepted.

*No source, test, or configuration file was modified by this
investigation.*
