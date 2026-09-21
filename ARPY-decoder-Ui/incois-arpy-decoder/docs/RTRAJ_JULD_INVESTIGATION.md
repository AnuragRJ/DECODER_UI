# Rtraj JULD parity investigation — read-only

**Date:** 2026-08-19 · **No source/test/config/output modified.**
**Scope:** remaining `_Rtraj.nc` JULD differences across the 11 APF9
floats, compared per `(cycle, MC)` (never positional).

---

## 1. Our JULD generation (raw → `_Rtraj.nc`)

- **MC 702** = `first_message_juld` = minimum **CRC-valid reception time**
  of the cycle's frames (`ArgosCycleTelemetry.message_times`).
- **MC 703** = one row per **parsed ARGOS fix** (`parse_argos_fixes`),
  JULD = fix time.
- **MC 704** = `last_message_juld` = maximum CRC-valid reception time.
- Multi-burst (repeated-suffix demoted) output cycles: the mono JULD was
  already fixed to the earliest fix across bursts (2026-08-19); the Rtraj
  telemetry per output cycle still keeps the **richest single burst**
  (`len(entry_tel.fixes) >= len(prior.fixes)`), not the union.

## 2. Coriolis reference

Coriolis's profile date precedence is `ascentEndTime → transStartTime →
firstMsgTime` (`add_profile_date_and_location_apx_argos.m`), where
`firstMsgTime = min(received dates)` of the cycle's file. For Rtraj,
Coriolis emits MC 702/703/704 from the same per-cycle file's reception
and fix lists (`process_trajectory_data_apx_argos.m`). The convention is
"first/last received message of the cycle's file" — identical to ours.
The differences below are therefore not a convention mismatch; they are
differences in **which receptions each side's file contains**.

## 3. Remaining JULD mismatches — table (fresh decode, current source)

### 3a. MC 0 (launch) — 8 floats (known, do not fix)

| float | ours | GDAC | delta |
|---|---|---|---|
| 2901339/2901350/2902201/2902203/2902206/2902222/2902223/2902224 | `LAUNCH_DATE` | `LAUNCH_DATE` + **2433282.5 d** | +2 433 282.5 d |

GDAC left the 1950 epoch as an astronomical Julian Day. **NOT FIXABLE —
approved GDAC error; do not copy.**

### 3b. MC 702 / MC 703 — 4 floats, 15 cells (reception-set)

| float | cyc | MC | ours | GDAC | Δ | GDAC time in our raw? |
|---|---|---|---|---|---|---|
| 2902203 | 360 | 702 | 15:44:14 | 13:42:30 | −2 h 02 m | **NO** (in a 21 h reception gap) |
| 2902206 | 359 | 702 | 13:04:14 | 07:11:26 | −5 h 53 m | **NO** (in a 113 h gap) |
| 2902206 | 359 | 703 | 13:04:22 | 07:14:23 | −5 h 50 m | NO (GDAC had morning fixes we lack) |
| 2902206 | 361 | 702 | 12:23:47 | 14:02:29 | +1 h 39 m | **YES** (start of a later pass cluster) |
| 2902206 | 361 | 703 | 12:28:22 | 14:08:05 | +1 h 40 m | GDAC's only fix = later cluster's |
| 2902222 | 328 | 702 | 06:10:53 | 12:58:37 | +6 h 48 m | YES (start of later cluster; GDAC lacks 06:10–12:58) |
| 2902222 | 328 | 703 | 06:17:06 | 14:57:05 | +8 h 40 m | GDAC's only fix is the afternoon's |
| 2902222 | 329 | 702 | 07:17:42 | 12:49:54 | +5 h 32 m | YES (GDAC lacks morning pass) |
| 2902222 | 329 | 703 | 07:22:27 | 12:52:44 | +5 h 30 m | same |
| 2902223 | 327 | 702 | 00:18:22 | 00:01:34 | −16 m 48 s | **NO** (GDAC had 00:01–00:18 we lack) |
| 2902223 | 327 | 703 | 00:21:36 | 00:06:07 | −15 m 29 s | same |
| 2902223 | 328 | 702 | 00:11:27 | 05:58:42 | +5 h 47 m | YES (GDAC lacks 00:11–05:58) |
| 2902223 | 328 | 703 | 00:13:08 | 05:58:42 | +5 h 46 m | GDAC's only fix is the late one |
| 2902223 | 329 | 702 | 00:07:20 | 05:40:32 | +5 h 33 m | YES (GDAC lacks 00:07–05:40) |
| 2902223 | 329 | 703 | 00:09:59 | 05:44:41 | +5 h 35 m | same |

### 3c. MC 704 — 2902224 cyc325/326 (multi-burst union)

| cyc | ours | GDAC | Δ |
|---|---|---|---|
| 325 | Jan-1 23:49:25 | Jan-2 **03:11:46** | +3 h 22 m |
| 326 | Jan-11 23:41:00 | Jan-12 **02:09:44** | +2 h 29 m |

### 3d. 1005 floats — no value mismatch exists

| float | GDAC Rtraj coverage | our coverage | comparability |
|---|---|---|---|
| 2901304 | cycles 1–23 (v3.1) | 1–23 | **full overlap · 323 shared keys · 0 JULD diffs** |
| 2901305 / 2901328 | v2.2 (no MC) | — | not comparable (GDAC legacy) |
| 2901339 | cycles **114–329** | 0–71 | **no overlap** (GDAC Rtraj starts at 114) |
| 2901350 | cycles **110–301** | 0–67 | **no overlap** (GDAC Rtraj starts at 110) |
| 2902201 | cycles 2–350 | 359–361 | **no overlap** (GDAC ends at 350) |

## 4. Candidate source analysis & evidence

- **MC 702/703 (3b):** every GDAC value is a genuine reception/fix time —
  sometimes **present in our raw** (GDAC's file simply started at a later
  pass cluster), sometimes **absent entirely** (GDAC had passes we do not
  hold). Both sides use the same rule (first/last CRC-valid message,
  per-fix rows). Proof of convention identity: on every cycle where the
  reception sets match, **ours equals GDAC to the second** — 2901304
  323/323; 2902203 cyc359/361; 2902206 cyc360; 2902222 cyc327;
  2902224 cyc325/326 (MC 702). The mismatches are purely **different
  per-cycle reception sets** (INCOIS's ARGOS delivery vs our archive),
  in both directions (we lack their early passes on 3 cells; they lack
  our morning passes on 12 cells).
- **MC 704 (3c):** GDAC's value = the surfacing's **last** reception
  (Jan-2 03:11:46 = end of the Jan-2 pass; Jan-12 02:09:44 = end of the
  Jan-12 pass). Ours = last message of the **kept richest burst only**
  (Jan-1 23:49 / Jan-11 23:41). GDAC's MC703 lists confirm the union:
  cyc325 = 7 fixes = 3 (Jan-1 `_011`) + 3 (Jan-2 `_011`) + 1 (Jan-1
  `_001`); cyc326 = 8 = 4 + 4. **This is the multi-burst aggregation
  nuance**, the Rtraj counterpart of the mono-JULD fix already
  implemented — our Rtraj per-cycle telemetry does not yet union the
  bursts that map to one output cycle.
- **3d:** coverage gaps in GDAC's own Rtraj files (their 2901339/2901350
  Rtraj begin at cycles 114/110; 2902201's ends at 350) — nothing to
  fix in our decoder; 2901304 proves our 1005 JULD is GDAC-identical on
  full overlap.

## 5. Classification

| item | class |
|---|---|
| MC 0 (8 floats) | **NOT FIXABLE** — GDAC 1950-epoch error (approved; do not copy) |
| MC 702/703 (2902203/2206/2222/2223, 15 cells) | **NOT FIXABLE** — reception/copy-set difference (both directions; convention identical; GDAC times present-or-absent in our raw per §3b) |
| MC 704 (2902224 cyc325/326) | **FIXABLE (generic)** — multi-burst Rtraj telemetry union (see §6) |
| 1005 Rtraj (2901339/2901350/2902201) | **NOT FIXABLE** — GDAC cycle-coverage gaps (no overlap); 2901305/2901328 legacy v2.2 |
| 2901304 | full parity (0 diffs on 323 keys) |

**Fleet conclusion:** our JULD logic (first/last CRC-valid message, per-fix
rows) is **identical in convention to GDAC** wherever the same telemetry
is available (2901304 323/323, plus every matched-set cycle on the
1010s). The only genuinely fixable remaining item is the **multi-burst
Rtraj aggregation** on 2902224 (MC703/MC704), which is a generic gap, not
a per-float patch.

## 6. Proposed generic fix (NOT implemented — for approval)

**Change:** in `apex_argos/decoder.py`, for output cycles assembled from
more than one distinct raw key (the same `raw_keys_by_cycle` gate used by
the mono-JULD fix), **aggregate the `ArgosCycleTelemetry` across all
bursts**: union of fixes (dedup by time) and union of `message_times`
(so MC 702 = min over union, MC 704 = max over union, MC 703 = all
fixes), instead of keeping the richest single burst.

**Expected effect:**
- 2902224 cyc325: MC703 3 → **7 fixes (GDAC-exact times)**; MC704 →
  Jan-2 03:11:46 (**GDAC exact**).
- 2902224 cyc326: MC703 4 → **8 fixes**; MC704 → Jan-12 02:09:44
  (**GDAC exact**).
- No other float/cycle changes (verified: 2902224 is the only float with
  repeated-suffix demotion; all other output cycles are single-burst, so
  the union == the single burst).

**Regression-test plan:**
1. Unit: two bursts mapping to one output cycle → Rtraj MC703 = union of
   fixes, MC704 = max message time, MC702 = min (unchanged).
2. Integration (2902224): MC703 counts 7/8 with GDAC-exact fix times;
   MC704 equals GDAC's; mono JULD (already fixed) unchanged.
3. Regression: 2901304 (323/323), 2902203 (exact 359/361), 2902206
   cyc360, 2902222 cyc327, 2902224 cyc325/326 MC702 — all unchanged;
   full `pytest` suite; NC3 342/342; FileChecker 33/44 (unchanged).

**Do not change:** the first-fix convention, MC 0, the reception-set
cells (impossible from our telemetry), or the 1005 coverage gaps.

## 7. Additional evidence needed (for the NOT-FIXABLE items)

1. INCOIS's actual ARGOS delivery (per-cycle reception sets) for
   2902203/2902206/2902222/2902223 — would confirm exactly which passes
   each side held and rule out any missed local bug.
2. INCOIS's Rtraj generation for 2901339/2901350 (why the files begin at
   cycles 114/110) — data request, not a decoder issue.

*No file was modified. Evidence retained: this report; raw telemetry and
GDAC references preserved.*
