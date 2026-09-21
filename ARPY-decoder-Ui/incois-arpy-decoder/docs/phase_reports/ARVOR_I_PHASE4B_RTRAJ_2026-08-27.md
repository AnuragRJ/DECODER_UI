# ARVOR-I Phase 4B — `_Rtraj.nc` Implementation Report

**Date:** 2026-08-27
**Predecessor:** `ARVOR_I_PHASE4B_RTRAJ_MAPPING_2026-08-27.md` (investigation + mapping; this report implements it)
**Status:** COMPLETE — 29/29 validation checks pass; full suite 1991 passed; ruff clean.

---

## 1. What was built

| Artifact | Role |
|---|---|
| `src/argo_decoder/platforms/provor_ir_sbd/arvor_i_rtraj.py` | product model: `RtrajRow` / `RtrajCycleRecord` / `RtrajAuxRow` / `ArvorRtrajDataset`, the 222-emitter port (`process_trajectory_data_222_223_225_231_232.m`), `finalize_trajectory_data_ir_sbd` port, `set_n_cycle_vs_n_meas_consistency` port, `build_arvor_rtraj_dataset()` |
| `src/argo_decoder/nc/rtraj_arvor.py` | ADMT Trajectory-3.1 writer: 102-variable table transcribed from `create_nc_traj_c_file_3_1.m` + both GDAC references; `build_arvor_rtraj_nc_dataset()`, `write_arvor_rtraj_file()`, `write_arvor_rtraj_nc()` |
| `tests/unit/test_arvor_i_rtraj.py` | 20 focused unit tests (row factories, bin status rules, finalize TET/fill/mail-only rules, consistency pass, launch-row optionality) |
| `tests/integration/test_arvor_i_rtraj_nc.py` | 15 integration tests over both raw datasets + written-layout tests against the GDAC references |
| `scripts/validate_arvor_i_rtraj.py` | formal validation + direct GDAC comparison (29 checks + classification ledger) |
| `validation_phase4b_rtraj/{6990711,7902408}_Rtraj.nc` | written products (63,960 / 113,720 bytes) |

Reuse: `nc/admt.py` primitives (`char_column`, `flag_column`, `scalar_char`,
`date_char`, `write_admt_dataset`, DAC-institution table) and the Phase-3
science model (`CycleTimeData`, `GpsRecord`+JAMSTEC, `MailInfo`, drift /
descent / ascent / near-surface series, hydraulic packets in buffers).
APEX `nc/trajectory.py` and `nc/technical.py` untouched (ARGOS subset
serves a different layout; no shared writer code was forced).

## 2. Emitter coverage (076a chain, PROVEN sources)

Emitted for these floats: MC 89/100/150/250/300/450/500/600/700/800 skeleton
(with `JULD_STATUS='2'`, `JULD_ADJUSTED=JULD` when the clock offset is
known — the emitter's double division collapses the minute drift to zero),
702/704 mail rows, 703 GPS ('G', JAMSTEC QC) + Iridium mail-location rows
('I', error ellipse, one per mail), 290 drift bins + 301 RPP, 190/590
profile bins (dated only), 710 near-surface bins, 203/503 deepest bins,
198/297/298/398/497/498 Tech#1 misc rows, 599 last-pumped-CTD, 189/289/
389/489/589 hydraulic Spy rows, 901 grounding rows (none in this data),
launch row MC 0 when a launch position is supplied (none — DATA-COVERAGE).
Finalize: mail-only cycles → surface records with `GROUNDED='U'`
(7902408 c14/c15), `TET(N-1) := CST(N)` per `create_one_meas_float_time`
(`JULD = CST.adj + prev-offset-days`, `JULD_ADJUSTED = CST.adj`),
expected-MC status-9 fill rows, N_CYCLE re-derivation preferring adjusted
values, FMT min / LMT max, FIRST/LAST_LOCATION from positioned 703 rows,
GROUNDED consistency.  TECH_AUX-destined VALVE/PUMP_ACTION_DURATION rows
are bookkept on `aux_rows` (19 / 261), never silently discarded.

## 3. Validation summary (29/29 PASS)

* product model: cycles 1–7 (6990711) and 1–15 (7902408: 12 deep +
  c13 no-Tech#1 + c14/15 mail-only), skeletons complete, data modes
  A×12+R×3, aux bookkeeping, TET chain rule on both floats;
* layout: NETCDF3_CLASSIC, identical dimension set, 102-variable order,
  dtypes, dimensions and attributes vs both GDAC references;
* direct GDAC comparison (cycle-mapped GDAC = transmitted + 1):
  FMT/LMT mail times **24/24 exact**; Iridium mail-location 703 rows
  **58/58 exact** (lat/lon/juld); float-clock DST shifts quantified as
  integer days (0/2/12/21/31/51 — the legacy `+item8` double-anchor,
  proven impossible dates, NOT reproduced); 7902408 reference stale at
  cycle 6 (DATA-COVERAGE).

## 4. GDAC comparison classifications (mapping report §7–§8)

| Difference | Class | Action |
|---|---|---|
| GDAC float-clock JULDs = calendar + item8 days (9 integer instances proven; dates post-date their own mail) | legacy production anomaly — NOT FIXABLE from public source | documented + quantified; not reproduced (no fabricated dates) |
| GDAC cycle numbering = transmitted + 1, prelude = cycle 1 | legacy-only | our files keep transmitted numbering (consistent with our tech/prof products) |
| DET 200 / DDET 400 rows; N_MEASUREMENT+CYCLE status '1'; TST 700 = FMT (mail); TET 800 = LMT | legacy-only (076a emits none of these) | not reproduced |
| GDAC "GPS fixes" are the Iridium mail locations; the actual GPS fixes are absent; `GROUNDED='Y'` on 7902408 GDAC cycles 3/6 (no raw grounding events) | legacy-only | our rows carry both GPS and Iridium locations; grounded stays 'N'/'U' |
| 7902408 GDAC coverage stops at cycle 6 (its own tech file, updated 2026-08-24, holds 17 cycles) | DATA-COVERAGE (stale reference) | comparison restricted to covered cycles — all exact |
| launch row MC 0 (GDAC 6990711: 2025-02-27T05:16, −64.49/70.01) | DATA-COVERAGE (no launch position in our metadata; launch-date metadata difference ledgered) | row omitted, note kept; optional `launch_position` input implemented |
| POSITION_QC '2'/'3' and param-QC flags in GDAC (RTQC pass) | TOOL-AVAILABILITY (RTQC outside chain scope) | not applied |
| one dual-cycle mail (6990711, cycles 5/6) attributed to first tagged cycle | INFERRED (MATLAB mail store carries one cycleNumber per mail) | documented |
| GDAC tech.nc uses a legacy 21-name Argos-era table (informational; Phase 4A closed) | legacy-only | no action |

MATLAB parity (076a chain, public source) is the implementation's basis;
GDAC parity holds for layout and for every directly comparable value
class (mail times, Iridium locations) and is explicitly NOT claimed for
the legacy-pipeline artifacts above.

## 5. Tests and hygiene

* 37 new tests (20 unit + 15 integration), all passing; full regression
  **1991 passed** (baseline before Phase 4B: 1954), 8 warnings, ~86 s.
* `ruff check` + `ruff format` clean on all changed files.
* No existing tests weakened or deleted; APEX/APF9/CTS4 modules untouched;
  no WMO-specific branches; the writer never parses raw SBD packets; no
  fabricated values (every emitted number traces to a packet field, a
  mail timestamp, or a chain-computed mean/offset).
* FileChecker jar remains absent (TOOL-AVAILABILITY), as in Phase 4A.

## 6. Deliverables

* `validation_phase4b_rtraj/6990711_Rtraj.nc`, `validation_phase4b_rtraj/7902408_Rtraj.nc`
* GDAC references used (recorded): `https://data-argo.ifremer.fr/dac/incois/6990711/6990711_Rtraj.nc`,
  `https://data-argo.ifremer.fr/dac/incois/7902408/7902408_Rtraj.nc` (both
  2026-06-16), plus the two `_tech.nc` files used for the provenance
  analysis (`gdac_arvor_i_ref/`).

**STOP after Phase 4B** — no further phase or product started.

---

## Addendum (2026-08-27, later same day): regeneration under
`process_remaining_buffers=True`

Products regenerated by re-running `scripts/validate_arvor_i_rtraj.py`
(writes into `validation_phase4b_rtraj/`); **29/29 checks passed** with
updated expectations (grounded `'N'` ×15 for 7902408; aux-261 check
unchanged).

* **6990711 `_Rtraj.nc`: data-identical** to the prior file — every
  variable compares equal except `DATE_CREATION`/`DATE_UPDATE` run
  stamps (expected on regeneration).  363 rows / aux 19, unchanged.
* **7902408 `_Rtraj.nc`: 824 → 891 rows.**  Only cycles 14/15 changed
  (all other per-cycle row counts identical):
  - c14: 2 → **34** rows (MC290 ×17, MC703 GPS ×2 with valid lat/lon,
    16 further event codes ×1);
  - c15: 2 → **37** rows (MC290 ×15, MC590 ×5, MC703 GPS ×3, 14 further
    codes ×1).
  - The 5 MC703 fixes are the GPS rows the float logged in its trailing
    buffers; the old 2-row-per-cycle stubs (mail-arrival JULDs only,
    `POSITION_QC` blank, `GROUNDED='U'`) are **retired**.
* **`GROUNDED`: 'N'×13 + 'U'×2 → 'N'×15.**  `DATA_MODE` unchanged
  (A×12 + R×3).  Old c14/c15 "mail-only 'U'" status is reclassified as
  trailing-buffer `go=2, completed=0` (hydraulic data present, profiles
  incomplete), per `ARVOR_I_REMAINING_BUFFERS_DECISION_2026-08-27.md`.
* Recovery closes the self-inflicted DATA-COVERAGE gap on c14/c15; the
  GDAC-stale-coverage classification (GDAC stops at cycle 6) is
  unaffected.
