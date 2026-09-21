# PROVOR CTS4 Rtraj ADJUDICATION — 2026-09-11 (Phase-4, evidence-complete)

**Scope:** adjudicate every Rtraj semantic (MC set, N_MEASUREMENT, N_CYCLE,
JULD, position, status/QC, DATA_MODE, accumulation) BEFORE finalizing the
implementation, per instruction. The recovered provisional builder's 9-MC/
JULD-duplication shortcut is **rejected**; the rules below replace it.

## 1. Evidence base

| Source | Role |
|---|---|
| **GDAC `2902086_Rtraj.nc`** (INCOIS, fetched 2026-09-10, 245 cycles, 27,999 measurements, Argo-3.2, Coriolis COPQ 2023-regen) | PRIMARY structural reference for decoder-301 trajectories |
| Argo trajectory spec (User's Manual §2.3, Table 15 MC codes; FileChecker `-internal-specs` trajectory v3.1/v3.2 CDLs) | normative dims/attrs/valid ranges |
| Coriolis `create_nc_traj_file*` chain (container `decArgo_soft`) | real-time generation pattern (R mode, per-cycle rebuild) |
| ARVOR-I `nc/rtraj_arvor.py` (validated, FileChecker-accepted, GDAC-parity) | architecture reference only |
| CTS4 telemetry: 253 (NKE §7.2.4.6), 252 (NKE §7.2.4.7: "Relative Time (minutes / phase start)") | the only first-party time sources |
| 12170 cycles 98–114 ↔ GDAC 2902086 cycles 99–115 | verification corpus (+1 cycle offset, GDAC-corroborated via its own `NUMBER_InternalCycle_NUMBER='98'` tech row) |

## 2. Mission clock (the keystone)

253 day/hour fields are **relative to mission start** (NKE wording). The
mission-start epoch is NOT transmitted; it is derived from telemetry alone:

    anchor = median_N [ FloatTime(last 253 of cycle N) − (cycle_start_day(N+1) + cycle_start_hour(N+1)/1440) ]

using the identity "next cycle starts when the previous transmission window
closes". 12170: 16/16 estimates agree within **66 s**; median 23007.9993
rounds to **23008.0 = midnight UTC of launch day** (launch 2012-12-29) and
reproduces GDAC tech `CLOCK_StartInternalCycle_YYYYMMDDHHMMSS='20140216034000'`
for (FloatDay 414, 0340) exactly. Midnight rounding fires only when the
estimates cluster within 0.02 d of an integer (guard: else raw median,
else raise `AnchorInconsistentError`). No GDAC value enters the derivation.

**FloatTime byte order is DD MM YY HH MM SS** (same encoding proven at
Phase-0 on type-0 headers). `decode_253` previously mislabeled yy↔dd — the
defect that produced the (ba)/(bb)/(bc) "25977 (year 2021)" artifact. FIXED
this phase; regression test pins `20140221035709 ↔ JULD 23427.1646875`
(exact GDAC match).

## 3. Adjudicated MC set (per cycle) — all verified 0-residual vs GDAC

| MC | Meaning | Source | JULD status | Verified |
|---|---|---|---|---|
| 0 (cycle −1) | launch | ExternalMeta LAUNCH_DATE (external, authoritative) | 4 | row exists in GDAC |
| 89 | cycle start (GDAC convention = buoyancy-reduction start) | 253 `buoy_start_day/hour` | 2 | **±0.00 min, 16/16 cycles** |
| 100 | descent start | 253 `park_desc_start` | 2 | exact |
| 150 | first stabilization | 253 `stab` | 2 | **±0.00 min, 16/16** |
| 189 ×n | buoyancy actions during descent-to-park | 252 phase-5 samples, anchored at `park_desc_start` | 2 | **counts equal, 0.000 min resid** |
| 198 | max pressure descent-to-park | 253 `max_pres_desc_park_bar`×10 | ' ' (no date) | value exact |
| 250 | park descent end | 253 `park_desc_end` | 2 | exact |
| 297/298 | min/max drift pressure at park | 253 drift-park min/max ×10 | ' ' | values exact |
| 300 | profile descent start | 253 `prof_desc_start` | 2 | exact |
| 301 | representative park measurement (PRES+BGC+CTD) | phase-6 telemetry; per-stream median (documented rule; GDAC's internal rule unknown → comparison approximate) | ' ' | structure matches |
| 389 ×n | buoyancy actions during descent-to-profile | 252 phase-7, anchored at `prof_desc_start` | 2 | counts equal, 0.000 min |
| 398 | max pressure descent-to-profile | 253 ×10 | ' ' | exact |
| 450 | profile descent end | 253 `prof_desc_end` | 2 | exact |
| 497/498 | min/max drift pressure at profile depth | 253 ×10 | ' ' | exact |
| 500 | ascent start | 253 `ascent_start` | 2 | exact |
| 503 | ascending-profile deepest level | 252 phase-9 max-pressure sample (time+pres) | 2 | structure matches |
| 589 ×n | buoyancy actions during ascent | 252 phase-9, anchored at `ascent_start` | 2 | counts equal, 0.000 min |
| 589 (+1) | closing surface pump action | 253 `ascent_end`, PRES 0.0 | 2 | **reproduces GDAC's +1 row/cycle 16/16** (was the sole count mismatch) |
| 599 | last pumped ascent CTD sample | last non-padding CTD record pressure | ' ' | structure matches |
| 600 | surfacing | `ascent_end − 10 min` (NKE: float waits 10 min after <1 bar) | 2 | ±0.00 min |
| 700 | first message | earliest cycle FloatTime | 3 (telemetry) | within window |
| 702/704 | first/last location time | first/last valid-fix FloatTime (no coordinates, per GDAC) | 4 | within window |
| 703 ×k | GPS fixes | each `gps_valid==1` 253: FloatTime + lat/lon, POSITION_QC 1 | 4 | ours = per-cycle 253 count (1–2); GDAC has ~8 (full Iridium location stream — DATA-COVERAGE, documented) |
| 800 | transmission end | unknown → fill, status 9 | 9 | identical to GDAC |

**Rejected (recovered provisional behavior):** 9-MC/cycle set with GPS JULD
duplicated onto DESCENT/PARK/ASCENT/TRANSMISSION rows — fabrication of event
times; replaced by the table above. **Deferred (documented, not fabricated):**
MC 290 drift series (phase-8 samples absent from the 252 corpus —
DATA-COVERAGE), MC 190/203/590 dated profile-level series (needs 10 s
ascent dating design; GDAC thins to ~28/cycle with an unknown rule) —
next bounded step if desired.

## 4. File-level rules (adjudicated)

* **One `<WMO>_Rtraj.nc` per float, accumulating**: rebuilt over ALL
  attributed cycles on every run (idempotent; matches ARVOR-I pattern and
  Coriolis `create_nc_traj_file` regeneration semantics). No per-cycle files.
* **N_MEASUREMENT** unlimited; **N_CYCLE** = 1 launch row (cycle −1) +
  cycles; N_PARAM = 12 BGC trajectory parameters (GDAC 301 set, Table 3).
* **FORMAT_VERSION 3.2 / Conventions Argo-3.2 CF-1.6** — required: v3.2 adds
  STRING256 + N_CALIB_PARAM/N_CALIB_JULD (GDAC 301 Rtraj is 3.2). FileChecker
  v3.0.5 `-internal-specs`: **FILE-ACCEPTED**.
* JULD_STATUS codes per Table 19 (2 interpolated-from-float-counter,
  3 telemetry, 4 satellite/external, 9 missing, ' ' n/a); JULD_QC 1/9/' '.
* DATA_MODE (N_CYCLE) all 'R' (real-time only; no D anywhere).
* CYCLE_NUMBER = telemetry cycle numbers (98–114). GDAC's +1 renumbering is
  documented corroboration, NEVER applied (no GDAC fitting).
* N_CYCLE summary block: JULD_* columns filled from the same first-party
  fields; unknowns keep fill + status ' '/'9'. SCIENTIFIC_CALIB from
  ExternalMeta predeployment strings; JULD_CALIB blank.

## 5. Verification summary (12170 → 2902086, cycles 98–114 ↔ 99–115)

* Event JULDs 89/150/250/450/500/600: **max |Δ| = 0.00 min** (all cycles).
* 189/389/589 series: counts equal after the closing-row rule; **0.000 min**
  JULD residuals.
* Pressure extremes 198/297/298/398/497/498: exact dbar matches.
* Tech corroboration: `NUMBER_InternalCycle_NUMBER='98'`,
  `CLOCK_FloatTime='20140221035709'`, vacuum 740 mbar, battery 9.5 V — the
  WMO hypothesis + clock semantics are GDAC-corroborated, still never used
  as routing logic.
* FileChecker v3.0.5 (jar sha256 `f6c2233f…c72c`): Rtraj FILE-ACCEPTED.

**Classifications:** MC-703 count gap = DATA-COVERAGE (location stream not in
our corpus); MC 290/590 series = deferred design step; 301 representative
rule = documented choice (GDAC rule UNKNOWN); everything else verified.
