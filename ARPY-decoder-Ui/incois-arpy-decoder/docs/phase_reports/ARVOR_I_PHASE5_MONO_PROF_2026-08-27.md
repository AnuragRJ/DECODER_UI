# ARVOR-I Phase 5 — Mono-Profile (`R*.nc`) Implementation & Validation

**Date:** 2026-08-27 · **Status:** COMPLETE — STOP after this phase (no `meta.nc`)
**Directive:** implement the ascent mono-profile product per the approved
investigation (`ARVOR_I_MONO_PROFILE_MAPPING_2026-08-27.md`) on the corrected
`process_remaining_buffers=True` baseline; descent `R<WMO>_<NNN>D.nc` files are
**not published** (explicit policy decision, §3); validate against the INCOIS
GDAC references for both floats; classify genuine publication-layer
differences instead of copying them.

## 1. Baseline (verified this session, before any new code)

Suite 1991 passed; tech validator 54/54; rtraj validator 29/29; products
6990711 467/99 + 363/19, 7902408 804/208 + 891/261 — unchanged by this phase
(no 4A/4B file touched; `mono_profile.py`, `writer.py`, `decoder.py`,
`arvor_i_science.py`, `arvor_i_cycles.py` all unmodified).

## 2. Implementation (smallest clean integration)

One new adapter module — `src/argo_decoder/platforms/provor_ir_sbd/arvor_i_prof.py`
(4A/4B pattern) — plus tests, validator, and one vendored MATLAB source:

* `build_arvor_mono_profiles(result, *, wmo, publish_descent=False)` →
  `ArvorProfRecord` list; `write_arvor_mono_profiles(records, out_dir)` →
  `R<WMO>_<NNN>.nc` files via the **unmodified** generic
  `build_mono_profile_dataset` / `write_mono_profile`.
* Rules implemented (mapping report §2–§6): direct cycle numbering;
  shallow-then-deep strictly pressure-ascending level merge (science blocks
  are stored deep-first and are reversed); JULD = first non-pre-launch mail
  of the cycle (leading packet-cycle tag; retransmissions keep the
  retransmission date); `JULD_LOCATION=JULD`, `JULD_QC=POSITION_QC='1'`;
  Tech#1 GPS fix truncated to arc-minutes (`GPS`); per-level QC `'0'` with
  fill levels `' '`; `VERTICAL_SAMPLING_SCHEME='Primary sampling: averaged []'`;
  `CONFIG_MISSION_NUMBER` explicit fill 99999 (builder attr default 1
  overridden — never fabricated); adjusted/calib blocks left to the generic
  builder (all-fill).
* Three post-build adapter steps compensate generic-builder choices with
  chain-accurate ones (§4) — the shared writer stays untouched.

## 3. Descent publication policy (explicit decision, per directive)

`PUBLISH_DESCENT_PROFILES = False`.  Raw telemetry carries cycle-1 descents
(6990711: 54 levels; 7902408: 52 levels) and the science layer reconstructs
them; the Coriolis writer supports `D` files; but INCOIS GDAC publishes no
`R*_001D.nc` for either float (mapping §7.3, UNKNOWN whether publication
omission or a production descProf drop).  The suppression is a documented
policy flag at the top of the adapter — flip it to emit `R<WMO>_<NNND>.nc` —
and the capability is exercised by unit + integration tests (no dead code;
descent data handling in the science layer untouched).

## 4. Uncertain decisions resolved against authoritative sources

1. **`PROFILE_<P>_QC` letter.**  Vendored `compute_profile_quality_flag.m`
   L30–37: when every flag is `' '`, `'0'` or `'9'` the function returns
   `qcStrDef` = `' '` without computing a ratio.  The generic builder's
   percentage-of-good helper would emit `'F'` for Coriolis no-QC columns.
   Decision: exact port (`coriolis_profile_qc`) applied post-build; generic
   helper untouched.  PROVEN vs source.
2. **Iridium-located position rule.**  The mapping report §4 recorded the
   CEP-weighted mean (`compute_profile_location_from_iridium_locations_ir_sbd`,
   CEP<5 km) as "PROVEN" only via cycle 13 (a single-fix degenerate).  Full
   validation showed the weighted mean (and the min-CEP variant
   `compute_profile_location2_from_iridium_locations_ir_sbd`, fetched from the
   GitHub mirror and vendored — exact URL:
   `https://raw.githubusercontent.com/euroargodev/Coriolis-data-processing-chain-for-Argo-floats/main/decArgo_soft/soft/sub/compute_profile_location2_from_iridium_locations_ir_sbd.m`)
   does **not** reproduce GDAC on 7902408 `_014`/`_015` or 6990711 `_006`
   with the full mail snapshot.  All five IRIDIUM-position files equal the
   **first mail's own fix** — including `_006`, whose fix carries CEP 415 km
   (excluded by both CEP rules) — and each file's `DATE_CREATION` is the
   first-mail day: production computed the location when only the first mail
   had arrived, where both MATLAB rules degenerate to that single fix.
   Decision (INFERRED, 5/5 GDAC-exact): `first_mail_fix` — the cycle's first
   non-pre-launch, non-zero-CEP mail's own lat/lon, full precision,
   `PSYS='IRIDIUM'`.  Recorded in `IMPLEMENTATION_PROGRESS.md`.
3. **Writer variable order.**  The generic builder appends `PROFILE_<P>_QC`
   after the science block, places each `<P>_ADJUSTED_ERROR` inside its
   parameter group, and `HISTORY_QCTEST` before `HISTORY_PREVIOUS_VALUE`;
   all 23 GDAC references carry the Coriolis writer order
   (`PROFILE_*_QC` directly after `POSITIONING_SYSTEM`; the three
   `_ADJUSTED_ERROR` variables grouped after the science block;
   `HISTORY_QCTEST` last).  Decision: adapter-level reorder
   (`apply_coriolis_var_order`) — content unchanged; verified 22/22 files
   byte-order-exact.
4. **Fresh-cycle JULD skew.**  Verified not a tagging bug (no earlier
   cycle-tagged mail exists in the snapshot; e.g. 6990711 c1 mails start
   06:06:39, GDAC JULD 06:06:32).  The −7…−32 s residual matches the mapping
   report §4's quantified production reception-timestamp difference —
   classified, not reproduced.

## 5. Validation results (`scripts/validate_arvor_i_prof.py`: 207/207, exit 0)

Products written to `validation_phase5_prof/{6990711,7902408}/` (7 + 15 files).

| Check family | Result |
|---|---|
| Records / naming / direct numbering | 7 + 15 ascent records, `R<WMO>_<NNN>.nc`, no D files |
| Level counts vs GDAC (mapping §8) | **22/22 exact** (incl. c14 = 15, c15 = 73 recovered) |
| `PRES`/`TEMP`/`PSAL` arrays vs GDAC | **22/22 bit-exact (float32)** |
| JULD vs GDAC | exact (≤0.5 s) on `_006`/`_013`/`_014`/`_015`; ≤32 s (classified skew) on the 16 fresh cycles; c5 classified |
| Position + `POSITIONING_SYSTEM` | **21/21 exact** except c5 6990711 (classified) |
| Layout | NETCDF3_CLASSIC; 64 vars in exact GDAC order; dtypes equal; per-variable attrs identical (0 diffs); `N_PROF=1`, `N_PARAM=3`, `N_CALIB=1`, `N_HISTORY` unlimited; 8 standard globals |
| Chain semantics | QC `'0'` ×N + `PROFILE_*_QC=' '`; `DATE_CREATION==JULD`; `DC_REFERENCE=<wmo>/<n>`; DIRECTION `A`, DATA_MODE `R`, `JULD_LOCATION==JULD`; VSS constant; `CONFIG_MISSION_NUMBER` fill; adjusted blocks all-fill |
| `_016` | correctly not produced (beyond raw snapshot) |

## 6. Classified divergences (publication layer; not reproduced)

GDAC level QC `'1'`/`'A'` + the single TEMP `'3'` (R7902408_011 lev 28) —
INCOIS RTQC (TOOL-AVAILABILITY); `CONFIG_MISSION_NUMBER=1` (production USE
table); metadata strings + `institution=INCOIS` + INQC history rows
(N_HISTORY 6 vs our 2 honest ARPY rows) + `DATE_UPDATE` batches; fresh-cycle
JULD reception skew (−7…−32 s); 6990711 c5 JULD/position (April mails absent
from the raw snapshot — DATA-COVERAGE, Phase-1 gap list — plus GDAC's
stale cycle-4 fix reuse); `R7902408_016` beyond raw; no `D` files on GDAC.

## 7. Regression

Full suite **2020 passed** (baseline 1991 + 28 new tests: 19 unit + 9
integration; +1 architecture parametrization that enumerates every `src/`
module — `test_no_concrete_metadata_loader_imports` picked up the new
`arvor_i_prof.py` and passes).  No existing test edited or deleted;
`ruff check` + `ruff format` clean on all changed files.

## 8. Deliverables

* `src/argo_decoder/platforms/provor_ir_sbd/arvor_i_prof.py` (adapter)
* `tests/unit/test_arvor_i_prof.py`, `tests/integration/test_arvor_i_prof_nc.py`
* `scripts/validate_arvor_i_prof.py`; products in `validation_phase5_prof/`
* Vendored: `tests/data/arvor_i/coriolis_src/compute_profile_location2_from_iridium_locations_ir_sbd.m` (83 files total)

**STOP — mono-profile implementation and validation complete.  `meta.nc` and
any subsequent phase are NOT started, per directive.**
