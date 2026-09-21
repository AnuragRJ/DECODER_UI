# ARVOR-I Mono-Profile (`R*.nc`) — Implementation Plan

**Date:** 2026-08-27 · **Status:** PLAN ONLY — no code modified · **STOP after this plan**
**Source of truth:** `ARVOR_I_MONO_PROFILE_MAPPING_2026-08-27.md` (investigation, Q1–Q6 +
ledger §7 + compatibility matrix §8) and `ARVOR_I_REMAINING_BUFFERS_DECISION_2026-08-27.md`
(trailing-buffer flip, implemented and validated earlier today).
**Directive:** plan the smallest mono-profile implementation; no `meta.nc`; no reopening
of 4A/4B unless a concrete regression appears (none did — §1).

---

## 1. Verified corrected baseline (re-verified 2026-08-27, this session)

| Item | Evidence |
|---|---|
| `process_remaining_buffers=True` | 3 signatures in `arvor_i_cycles.py` (L370 `reconstruct_cycles`, L394 `reconstruct_stream`, L720 `reconstruct_from_directory`); legacy `OutputFlags` untouched |
| Full suite | **1991 passed** (0 failed; == post-change baseline) |
| Tech validator | **54/54** (re-run this session; aux expectation 99/208) |
| Rtraj validator | **29/29** (re-run this session; grounded `'N'` ×15) |
| 6990711 `_tech.nc` | 467 file rows + 99 aux (= 566 in-memory); **byte-identical** post-flip |
| 6990711 `_Rtraj.nc` | 363 rows / aux 19; data-identical except run stamps |
| 7902408 `_tech.nc` | 804 file rows (c1–12 ×67) + **208 aux** (c13 12, c14 13, c15 14); content-identical (aux never enters GDAC layout) |
| 7902408 `_Rtraj.nc` | **891 rows** (c14 34, c15 37; GROUNDED `'N'`×15; DATA_MODE A×12+R×3) / aux 261 |
| Cycle state | 6990711: 7 cycles; 7902408: 15 cycles, c14/c15 = trailing buffers `go=2, completed=0` |
| Docs | Phase 2/4A/4B addenda + `IMPLEMENTATION_PROGRESS.md` L10737 entry all present |

No regression → 4A/4B remain closed. Mapping-report ledger §7.1 (our-side c14/c15
DATA-COVERAGE gap) is **resolved** by the flip: mono c14/c15 are now producible and,
per the decision report, match GDAC `_014` (15 lev) / `_015` (73 lev) exactly.

## 2. Existing mono-profile inputs / APIs (nothing new needed below the adapter)

- **Science layer (input):** `reconstruct_science` / `reconstruct_science_from_directory`
  → `ArvorScienceResult`:
  - `cycles[] → ArvorCycle.profiles[]` with `kind ∈ {descent, ascent_deep, ascent_shallow}`,
    `measurements[]` (PRES/TEMP/PSAL per level), `location: ProfileLocation`
    (lat/lon/qc/system/source), `sub_surface_pres`;
  - `mails[] → MailInfo` (`.cycles` packet tags, `.time_of_session`, `.lat/.lon/.cep_radius_km`,
    `.pre_launch`) — supplies the first-mail JULD rule with **no science-layer change**;
  - `gps_records[]`, `float_config`.
- **Generic writer (already ADMT-3.1 / GDAC-shaped):** `nc/mono_profile.py`
  - `build_mono_profile_dataset(ds, *, wmo, cycle, meta, …)` — 64-var layout,
    `DC_REFERENCE='<wmo>/<cycle>'`, `DATA_STATE_INDICATOR='2B'`, VSS + CONFIG_MISSION_NUMBER
    from `ds.attrs`, mode-letter `PROFILE_*_QC` helper, adjusted/calib fill blocks;
  - `write_mono_profile` — NETCDF3_CLASSIC. **Untouched by this plan.**
- **Naming pattern:** `writer.py` already writes `R<wmo>_<NNN>.nc` under `profiles/`.
- **Separate legacy path (untouched):** `provor_ir_sbd/decoder.py → profile_to_dataset +
  RTQC scalar tests → writer.py` emits mono files with *our* 40x date/interpolated-position
  semantics. This plan adds a **parallel** production-semantics path; no existing module,
  test, or output changes.
- **References (vendored):** 23 GDAC mono files `gdac_arvor_i_ref/profiles/{6990711,7902408}/`
  (7 + 16; `_016` beyond raw); MATLAB chain sources in `tests/data/arvor_i/coriolis_src/`
  (`create_nc_mono_prof_files*.m`, `get_profile_init_struct.m`,
  `compute_profile_quality_flag.m`, `add_vertical_sampling_scheme_ir_sbd.m`,
  `add_rtqc_to_profile_file.m`).

## 3. GDAC differences: decoder/implementation vs publication/RTQC/metadata

**A. Ours to implement (decoder/implementation — handled by the adapter):**
1. §7.1 c14/c15 absence — already fixed by the True flip; validation must confirm
   `_014`/`_015` parity (15 / 73 levels).
2. §7.8 JULD = reception time of the cycle's **first non-pre-launch mail**
   (`min(mails.time_of_session)` over mails tagged with the cycle; retransmitted cycles
   thereby get the retransmission arrival date — matches GDAC `_005`/`_006`).
   `JULD_LOCATION = JULD`; `JULD_QC='1'`.
3. §7.9 GPS position = Tech#1 internal fix **truncated to arc-minutes** (lat and lon),
   `POSITIONING_SYSTEM='GPS'`, `POSITION_QC='1'`; no fresh fix → existing mail-weighted
   `ProfileLocation` (`system='IRIDIUM'`).
4. Per-level QC `'0'` (Coriolis no-QC) — not GDAC's `'1'`s.
5. `VERTICAL_SAMPLING_SCHEME = 'Primary sampling: averaged []'` (PROVEN constant).
6. `CONFIG_MISSION_NUMBER` = explicit **fill 99999** — the generic builder's attr default
   is `1`, which the adapter must override (no USE table in stream; emitting `1` would be
   a fabricated value that coincidentally matches GDAC).
7. Level assembly: `ascent_shallow` (ascending) + `ascent_deep` (reversed to ascending)
   merged into ONE strictly pressure-ascending series; empty cycles skipped;
   `DIRECTION='A'`, `DATA_MODE='R'`.

**B. Not ours (INCOIS publication / RTQC / metadata — classified, not reproduced):**
1. Level QC `'1'`/`'A'` and the single TEMP `'3'` (R7902408_011 lev 28) — INCOIS ARGQ
   re-flags + INQC history rows (TOOL-AVAILABILITY / publication).
2. `CONFIG_MISSION_NUMBER=1` on GDAC (production float-config USE table) — metadata.
3. Metadata strings: `PROJECT_NAME 'Argo INDIA'`, `PI_NAME 'M Ravichandran'`,
   serial 24022, FW 7.2.5, WMO_INST_TYPE 844, DATA_CENTRE 'IN', DATE_UPDATE batches,
   6 INQC HISTORY rows.
4. `R7902408_016` (72 lev) beyond raw snapshot (last mail 2026-08-11) — DATA-COVERAGE.
5. No `R*_001D.nc` published although c1 descents exist in raw (54/52 lev) — UNKNOWN
   (publication or production descProf drop).
6. 6990711 c5 stale-fix / c6 mail-weighted retransmit positions (GDAC reused c4's fix;
   ours has no fresh fix → follows rule A3 → divergence ledgered, not forced).
7. `PRES_ADJUSTED` all-fill (no presOffset in stream) — keep fill.

## 4. Smallest implementation plan

**P5.1 — Adapter module** `src/argo_decoder/platforms/provor_ir_sbd/arvor_i_prof.py`
(pattern of `arvor_i_tech.py` / `arvor_i_rtraj.py`; the mapping report §9.1 suggested
`nc/profile_arvor.py` — same content, location follows the established 4A/4B layout;
see decision point D2):

- Input `ArvorScienceResult` (+ WMO, output dir); output: per-cycle flat datasets +
  `R<WMO>_<NNN>.nc` files via the **unmodified** `build_mono_profile_dataset` /
  `write_mono_profile`. Direct cycle numbering (§6 of the mapping report — the +1 is
  Rtraj-legacy only).
- Levels per A7; per-cycle scalars per A2/A3; QC `'0'`s; VSS per A5;
  `CONFIG_MISSION_NUMBER` fill per A6; adjusted/calib blocks left to the generic builder.
- Descent (`D`) files: see decision point D1 (default: skip, classify per B5).

**P5.2 — Validator** `scripts/validate_arvor_i_prof.py` (pattern of the 4A/4B
validators; writes products into `validation_phase5_prof/`):
- Layout exact vs all 23 vendored GDAC refs (dims `N_PROF=1, N_LEVELS, N_CALIB=1,
  N_PARAM=3, N_HISTORY=6`; 64 vars; dtypes; attrs; NETCDF3_CLASSIC).
- Values exact where PROVEN: level counts/ranges for all in-raw cycles per matrix §8
  (now including 7902408 c14 = 15 lev, c15 = 73 lev), JULD first-mail rule (spot-checks
  incl. `_014` hydraulic-only first mail and 6990711 `_005`/`_006` retransmit dates),
  truncated GPS and mail-weighted positions, `DC_REFERENCE`, VSS, DIRECTION, DATA_MODE,
  PSYS, `DATE_CREATION==JULD`.
- Divergences classified per §3B above (expect exactly that set; anything else fails).

**P5.3 — Tests** (new files only; zero existing tests edited):
- Unit: shallow+deep merge order strictly ascending; arc-minute truncation; first-mail
  JULD incl. retransmit pins; QC `'0'`/fills; naming `R<WMO>_<NNN>.nc`; empty-cycle skip;
  CONFIG_MISSION_NUMBER fill override of the builder default.
- Integration: round-trip adapter → writer → file; c14/c15 recovered (7902408).

**P5.4 — Closeout:** `ruff check` + `ruff format` on changed files; full suite
(≥ 1991 + new); Phase 5 report `ARVOR_I_PHASE5_MONO_PROF_2026-08-27.md`;
`IMPLEMENTATION_PROGRESS.md` append; **STOP — no `meta.nc`.**

**Explicitly out of scope:** `meta.nc`; RTQC; any change to `mono_profile.py`,
`writer.py`, `decoder.py`, `arvor_i_science.py`, `arvor_i_cycles.py`, or any 4A/4B file;
fabricating a USE table or metadata strings; forcing GDAC publication values.

**Decision points (defaults chosen for smallest scope; confirm at kickoff):**
- **D1 — Descent `D` files:** recommend **skip** (match GDAC published coverage for
  these floats; classify per §3B5). Alternative: emit per MATLAB writer parity.
- **D2 — Adapter location:** recommend `platforms/provor_ir_sbd/arvor_i_prof.py`
  (4A/4B layout) vs mapping report's `nc/profile_arvor.py`. Cosmetic; content identical.
- **D3 — Existing decoder-path mono outputs:** untouched (they serve the generic CLI
  with our documented semantics); the new production-semantics path is additive.

**Acceptance criteria (proposed):** smallest generic change; no WMO-specific branches;
no weakened/deleted tests; suite green; validator green with divergences exactly = §3B
set; 6990711/7902408 products per §8 matrix; reports + progress appended; stop before
`meta.nc`.

**STOP — plan ends here per directive. No implementation performed.**
