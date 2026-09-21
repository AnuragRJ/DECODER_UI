# ARVOR-I Mono-Profile (`R*.nc`) — Pre-Implementation Mapping Investigation

**Date:** 2026-08-27 · **Status:** READ-ONLY investigation (no code modified) · **STOP after this report**
**Floats:** 6990711 (decId 222), 7902408 (decId 232) · **Scope answers Q1–Q6 of the directive; every finding labelled PROVEN / INFERRED / UNKNOWN and attributed to Coriolis-chain vs GDAC-publication vs raw-telemetry evidence.**

## 0. Sources fetched (exact URLs)

- GDAC listings: `https://data-argo.ifremer.fr/dac/incois/6990711/profiles/`, `https://data-argo.ifremer.fr/dac/incois/7902408/profiles/` (bare `dac/<WMO>` 404s; `incois` segment required — consistent with 4B).
- Mono profiles downloaded (23 files → `gdac_arvor_i_ref/profiles/<wmo>/`): `R6990711_001..007.nc` (7), `R7902408_001..016.nc` (16). No `D`-suffix descent files, no delayed-mode (`D`-prefix) files, no `M` files in either listing.
- SEANOE record `https://www.seanoe.org/data/00345/45589/` (Coriolis Argo floats data processing chain; version 20250516_076a, clé 120353; GitHub mirror `https://github.com/euroargodev/Coriolis-data-processing-chain-for-Argo-floats`). Eight previously-unvendored chain files fetched from the mirror into `tests/data/arvor_i/coriolis_src/`: `create_nc_mono_prof_files.m`, `create_nc_mono_prof_files_3_1.m`, `create_nc_mono_prof_b_files_3_1.m`, `create_nc_mono_prof_c_files_3_1.m`, `add_rtqc_to_profile_file.m`, `get_profile_init_struct.m`, `compute_profile_quality_flag.m`, `add_vertical_sampling_scheme_ir_sbd.m`.
- Raw telemetry: `arvor_raw/ARVOR-I-raw-files/20260819/<wmo>/*.eml` (35 / 64 mails; 7902408 window 2025-09-19 → **2026-08-11T07:57:32Z**).

## 1. Q1 — Exact Coriolis profile emitter/writer path (PROVEN)

```
decode_provor_2_nc.m            (dispatcher; sets g_decArgo_processRemainingBuffers = 1  ← production!)
└─ decode_provor.m              (per-float driver)
   ├─ decode_provor_iridium_sbd2(...)   [wrapper; core = vendored decode_provor_iridium_sbd.m]
   │   ├─ create_prv_profile_212_222_231.m   (descProf / ascProf / nearSurf / inAir series)
   │   ├─ compute_prv_dates_222_to_227_231_232.m (cycle timing)
   │   ├─ compute_first_last_msg_time_from_iridium_mail.m (per-cycle mail times)
   │   └─ process_decoded_data.m
   │       └─ process_profiles_222_223_225_231_232.m   (prv → tabProfiles structs, 1:3 idProf split)
   │           └─ get_profile_init_struct.m           (profile struct defaults)
   ├─ check_prof_and_traj_struct_consistency.m
   ├─ remove_data_qc(...)            [only when g_decArgo_applyRtqc == 0]
   ├─ get_meta_data_from_json_file(... wantedMetaNames = PROJECT_NAME, DATA_CENTRE, PI_NAME,
   │                                FLOAT_SERIAL_NO, FIRMWARE_VERSION)   ← float json metadata
   └─ create_nc_mono_prof_files.m
       └─ create_nc_mono_prof_files_3_1.m
           ├─ create_nc_mono_prof_c_files_3_1.m   (c writer FIRST — same order as the traj chain in 4B)
           └─ create_nc_mono_prof_b_files_3_1.m   (b writer second)
```
RTQC is a separate DAC-side pass (`add_rtqc_to_profile_file.m`, 7912 ln). The mono files are
NETCDF3_CLASSIC, ADMT-3.1, 64 variables, dims `N_PROF=1, N_LEVELS, N_CALIB=1, N_PARAM=3, N_HISTORY=6`.

## 2. Q2 — One file per (cycle × direction); naming; deep/shallow handling

- **Writer rule (PROVEN, c-writer L125–260):** one file per `(outputCycleNumber, direction)`; name
  `R<WMO>_<%03d>d` + `D.nc` for direction `'D'`, else `R<WMO>_<NNN>.nc`. Primary (flag 1) profile
  required per group; if absent a *default* primary is synthesized. Secondary (flag 2) levels join the
  same file.
- **Ascent split (PROVEN, process_profiles L154–190):** one deep-first ascProf series split at
  `subSurfacePres` (Tech#2; fallback `presCutOffProf` config): primary = prefix `pres > subSurfacePres`
  (decIds `201:218,221:223,225,228,230` — includes **222** — use `>`/`<=`; **232** uses `>=`/`<`),
  near-surface = suffix. Descent (idProf 1) is `flipud`-ed and flagged direction `'D'`.
- **Empirics (PROVEN, 20/20 covered cycles):** every GDAC file is `N_PROF=1, DIRECTION='A'`;
  levels = our `ascent_deep` block + our `ascent_shallow` block merged into ONE strictly
  pressure-ascending series, shallow block first (e.g. 6990711_001: 0.2–4.9 then 5.9–1976.3; 102 lev).
  Deep-only cycles (7902408 c3/c6/c8/c10/c13/c14) carry only the deep block.
- **Descent profiles:** writer supports `D` files, but **no `R*_001D.nc` exists on GDAC** for either
  float although raw telemetry contains c1 descents (ours: 54 lev / 52 lev). → GDAC publication
  omitted them or production dropped descProf for these decIds: **UNKNOWN** (publication layer).
- **Cycle numbering: DIRECT** — `outputCycleNumber` = transmitted cycle (076a identity, 4B finding) —
  see §6.

## 3. Q3 — Per-level QC generation

- **Coriolis semantics (PROVEN, c-writer L1421–1431):** for raw params every non-fill level gets
  `g_decArgo_qcStrNoQc = '0'` ("no QC performed"); fill levels get `qcStrDef`. Explicit `dataQc`
  (only set by RTQC, or removed by `remove_data_qc` when RTQC off) overrides. `PROFILE_<P>_QC` =
  `compute_profile_quality_flag` (%-mode letter).
- **GDAC files (PROVEN):** all levels `'1'`, `PROFILE_*_QC='A'` — 22.999/23 files — plus exactly one
  TEMP level `'3'` (R7902408_011 lev 28, PRES 1287.9 dbar, TEMP 5.179 °C spike vs 14.7/5.0 neighbours).
  HISTORY shows `INQC V4.0` steps `ARFM/ARGQ/ARCA/ARUP/ARGQ`, actions `IP/IP/IP/IP/QCP$/QCF$`,
  QCTEST `D7B7E`. → **the `'1'`s and the single `'3'` are INCOIS RTQC re-flags (GDAC publication
  layer), not Coriolis output** (INFERRED attribution of the '3' to INCOIS ARGQ; INCOIS-only history
  rows support it).
- Implementation target per standing rules: emit **Coriolis semantics (`'0'`)**; classify the GDAC
  `'1'`/`'A'`/`'3'` as publication-layer differences (like 4B RTQC POSITION_QC → TOOL-AVAILABILITY).

## 4. Q4 — JULD / JULD_LOCATION / position / DIRECTION / DATA_MODE

- **JULD = reception time of the FIRST mail of the cycle's Iridium session** — NOT the in-water date:
  - `DATE_CREATION == JULD` to the second (23/23; 12 files +1 s rounding) (PROVEN).
  - `_014` JULD 2026-08-01T13:13:16 = the cycle-14 session's first mail — a Hydraulic-**only** mail —
    exactly; `_015` JULD 07:56:52 = first of three mails exactly (PROVEN).
  - Fresh cycles: GDAC JULD = Rtraj FMT (legacy) − 7…32 s; = our float-clock date + ~2 min (6990711)
    or + 10–17 min after ascent-end (7902408 c1–c12) (PROVEN quantified).
  - **Retransmitted cycles get the retransmission arrival date**: 6990711 `_005` JULD 2025-04-22
    (data measured 2025-04-12, re-sent at the next surfacing); `_006` JULD 2025-05-02 (measured
    04-22). Ours c5/c6 `delayed=1` (PROVEN raw + GDAC agreement).
  - The vendored `add_profile_date_and_location_201_to_230_40x…` (ascent-end → trans-start →
    first-mail fallback) does **not** match production here (production used mail time even where
    ascent-end exists) → production used the IR-SBD mail-time path; classify the 40x-variant rule as
    not-applied for these decIds (INFERRED; the driver calls
    `compute_first_last_msg_time_from_iridium_mail(mails, cycleNum-1)` at 4 sites).
  - Adapter implication: first-mail time is available from `ArvorScienceResult.mails`
    (`MailInfo.cycles`, `time_of_session`, `pre_launch`) — **no science-layer change needed**.
- `JULD_LOCATION == JULD` in 23/23 files (PROVEN) — the fix time is NOT tracked separately.
- **Position (PROVEN):** `PSYS='GPS'` files carry the **Tech#1 internal GPS fix truncated to
  arc-minutes** (ours 2.9410316°→2°56.46′→2.93333° = GDAC `_001`; verified lat+lon on 4 cycles both
  floats; 6990711 c1 −64.54295°/70.08330° → −64.53333/70.06667). `PSYS='IRIDIUM'` files
  (6990711_006; 7902408_013/14/15) carry the full-precision CEP<5 km 1/r² weighted mail location
  (`compute_profile_location_from_iridium_locations_ir_sbd(mails, cycle−1)`); ours c13 =
  2.49729/80.96940 exact. `POSITION_QC='1'`, `JULD_QC='1'` 23/23.
  - 6990711 c5/c6 (retransmitted, no fresh fix): GDAC reused c4's fix (`_005` lat/lon == `_004`) and
    a mail-weighted loc (`_006`); ours interpolated (QC 8) — production difference, ledgered.
- `DIRECTION='A'`, `DATA_MODE='R'` 23/23 (PROVEN). No delayed-mode mono files on GDAC.

## 5. Q5 — VSS / config-mission / fills / required ADMT fields

- **VERTICAL_SAMPLING_SCHEME** (PROVEN source): `add_vertical_sampling_scheme_ir_sbd` →
  `'Primary sampling: averaged [<zone params from CONFIG_PMxx>]'` (flag 1) or
  `'Near-surface sampling: averaged, unpumped'` (flag 2). GDAC value is constant
  `'Primary sampling: averaged []'` (empty zone list) — 23/23 (PROVEN).
- **CONFIG_MISSION_NUMBER** (PROVEN mechanics): `get_config_mission_number_ir_sbd` needs
  `floatConfig.USE` — absent from our decoded config (4B) → MATLAB returns `[]` (with warning) →
  writer leaves NC_INT fill 99999. GDAC files carry `1` → production float-config json had a USE
  table (INFERRED, publication metadata). Do not fabricate; emit fill, classify.
- **Adjusted block (PROVEN):** `PRES/TEMP/PSAL_ADJUSTED` + `_ERROR` all-fill (99999);
  `SCIENTIFIC_CALIB_EQUATION` = static boilerplate ('Pcorrected = Praw - surface offset', 'This
  sensor is subject to hysteresis'…) with empty coefficients; calib dates = DATE_UPDATE. Coriolis
  would fill `PRES_ADJUSTED = PRES − presOffset` when `prof.presOffset` exists (c-writer L1492–97);
  GDAC files have it empty.
- **Metadata strings (PROVEN source = float json meta, publication):** `PROJECT_NAME 'Argo INDIA'`,
  `PI_NAME 'M Ravichandran'`, `FLOAT_SERIAL_NO 24022`, `FIRMWARE_VERSION 7.2.5'`,
  `PLATFORM_TYPE 'ARVOR'`, `WMO_INST_TYPE 844`, `DATA_CENTRE 'IN'`, `DC_REFERENCE '<WMO>/<cycle>'`,
  `DATA_STATE_INDICATOR '2B'`, `institution=INCOIS` (global attr), `HISTORY_*` 6 INQC rows,
  `DATE_UPDATE` = DAC re-issue batch (6990711 all 2025-05-05; 7902408 07-24/08-03/08-12/08-24
  batches — matching its tech.nc refresh 2026-08-24).
- Global attrs: `Conventions 'Argo-3.1 CF-1.6'`, `user_manual_version 3.1`,
  `featureType trajectoryProfile`; `FORMAT_VERSION 3.1`, `HANDBOOK_VERSION 1.2`,
  `REFERENCE_DATE_TIME 19500101000000`.

## 6. Q6 — Cycle numbering: DIRECT for mono profiles (the +1 is Rtraj-legacy only)

**PROVEN (three independent lines):**
1. Level-count/range exact match under direct map for all 20 in-raw cycles (§8) — any shift breaks
   every pairing (7902408 `_013` = our c13: 30 lev, 1287.6–2005.6 dbar, IRIDIUM loc exact).
2. `DC_REFERENCE = '<WMO>/<N>'` equals the filename number N (23/23).
3. 076a `update_output_cycle_number_ir_sbd` is identity for these decIds (4B); writer uses
   `outputCycleNumber`.
The 4B "+1" (GDAC cycle = transmitted + 1, prelude = cycle 1) was the **legacy Rtraj pipeline**
(4B §7); the mono-profile product was produced by the modern chain **without** renumbering.
→ The +1 is **product/pipeline-specific GDAC behavior, not a decoder behavior and not an INCOIS
publication-wide convention** (two GDAC products of the same float disagree — Rtraj +1, prof direct).

## 7. Coverage & disagreement ledger

| # | Finding | Class |
|---|---------|-------|
| 1 | 7902408 c14 (GDAC 15 lev 1687.8–2028.7) & c15 (73 lev 0.1–1287.8): raw mails of 2026-08-01 / 08-11 contain cycle-tagged 14/15 CTD packets (3× type-2, 6× type-2/3); our science layer yields no cycles because `reconstruct_science` uses `process_remaining_buffers=False` while production `decode_provor_2_nc` sets `g_decArgo_processRemainingBuffers = 1` | **PROVEN — our-side reconstruction gap (DATA-COVERAGE in our chain; fix candidate)** |
| 2 | 7902408 `_016` (72 lev, JULD 2026-08-21) beyond raw snapshot (last mail 2026-08-11) | DATA-COVERAGE (raw snapshot) |
| 3 | No `R*_001D.nc` on GDAC though c1 descents exist in raw (54/52 lev) | UNKNOWN (publication or production descProf drop) |
| 4 | GDAC level QC `'1'`/`'A'`/one `'3'` vs Coriolis `'0'`/computed letter | publication (INCOIS ARGQ); TOOL-AVAILABILITY |
| 5 | 6990711 c5 GDAC position = c4's stale fix; c6 = mail-weighted; ours interpolated (QC 8) | production/legacy difference (position rule on retransmits) |
| 6 | `CONFIG_MISSION_NUMBER=1` needs production USE table | TOOL-AVAILABILITY/metadata (emit fill) |
| 7 | PRES_ADJUSTED all-fill on GDAC (Coriolis would fill if presOffset known) | keep fill (no presOffset in stream); classify |
| 8 | JULD = first-mail time (also for retransmits) vs our in-water `profile.date` | convention (adapter: use `mails`; no science change) |
| 9 | GDAC GPS positions minute-truncated | convention (adapter: truncate Tech#1 fix) |
| 10 | VSS `'Primary sampling: averaged []'` | PROVEN constant for these floats |

## 8. Compatibility matrix (ours vs GDAC, direct cycle map) — PROVEN exact

| cyc | 6990711 lev (range) | GDAC | 7902408 lev (range) | GDAC |
|---|---|---|---|---|
| 1 | 102 (0.2–1976.3) | = | 104 (0.3–2033.8) | = |
| 2 | 103 (0.4–2011.2) | = | 73 (0.4–1262.9) | = |
| 3 | 104 (0.3–2026.9) | = | 75 (185.6–2003.1) | = |
| 4 | 104 (0.4–2027.9) | = | 103 (0.1–2008.0) | = |
| 5 | 101 (2.3–2008.6) | = | 73 (0.2–1262.6) | = |
| 6 | 105 (−0.9–2028.4) | = | 75 (185.7–2007.8) | = |
| 7 | 101 (0.0–2005.5) | = | 102 (0.2–2009.6) | = |
| 8 | — | | 30 (1263.1–1980.5) | = |
| 9–12 | — | | 103/75/58/103 | = |
| 13 | — | | 30 (1287.6–2005.6), IRIDIUM loc exact | = |
| 14 | — | | ours: none / GDAC: 15 (1687.8–2028.7) | ledger §7.1 |
| 15 | — | | ours: none / GDAC: 73 (0.1–1287.8) | ledger §7.1 |
| 16 | — | | beyond raw / GDAC: 72 (0.3–1238.1) | ledger §7.2 |

## 9. Recommended implementation plan (NOT implemented — for a future directive)

1. **Adapter module** `nc/profile_arvor.py` (pattern of 4A/4B): `ArvorScienceResult` → per-cycle flat
   dataset → existing generic `build_mono_profile_dataset`/`write_mono_profile` (mono_profile.py
   untouched; it already produces the same 64-var ADMT-3.1 layout).
   - One output per cycle **N** (direct numbering): `R<WMO>_<NNN>.nc`; optional `D` file for c1
     descents (decision point: GDAC publishes none — recommend emitting per MATLAB and classifying,
     or skipping; flag for the directive).
   - Levels: merge `ascent_shallow` (ascending) + `ascent_deep` (reversed to ascending) into one
     series (§2); empty cycles skipped.
   - JULD = first non-pre-launch mail time of the cycle from `res.mails`; `JULD_LOCATION=JULD`;
     `JULD_QC='1'`, `POSITION_QC='1'`.
   - Position/location: Tech#1 GPS fix truncated to arc-minutes (`PSYS='GPS'`); else weighted mail
     location (already in `ProfileLocation`, `system='IRIDIUM'`).
   - Per-level QC `'0'` (Coriolis) with `PROFILE_*_QC` via the existing mode-letter helper;
     `<PARAM>_ADJUSTED*` fills; `VERTICAL_SAMPLING_SCHEME='Primary sampling: averaged []'`;
     `CONFIG_MISSION_NUMBER` fill.
2. **Trailing-buffer decision (ledger §7.1)**: enabling `process_remaining_buffers=True` recovers
   c14/c15 (parity with production) but changes 4B Rtraj outputs ('mail-only U' rows). Options:
   (a) pass True in the prof path only, (b) keep False and classify. **Recommend (a) + re-run 4B
   validation with both modes documented** — requires explicit user sign-off since it touches a
   completed phase's semantics.
3. **Tests**: unit (split/merge order, truncation, mail-time JULD incl. retransmit case, QC rules,
   cycle naming) + integration (round-trip vs writer) + validation script comparing products with the
   23 GDAC refs (layout exact; values exact where proven; divergences classified per §7).
4. Reports + `IMPLEMENTATION_PROGRESS.md` append; ruff check+format; no earlier-phase file modified
   except the two ledgered decisions above.

**STOP — investigation ends here per directive. No implementation performed.**
