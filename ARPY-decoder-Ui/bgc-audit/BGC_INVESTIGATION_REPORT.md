# BGC Backend Audit — Investigation Report (decoder-301 / PROVOR CTS4)

- **Date:** 2026-09-16 · **Phase:** investigation only — no UI and no `src/argo_decoder/` changes
- **Primary source of truth:** updated Python decoder from the user-supplied Drive link
  (`phase-6-2-1.1.zip`, Drive id `1d3Uw4av2wro0bsVoyHQerzYiNhXwBmJM`, 134,458,703 B, 6761 files),
  selectively extracted to `/home/user/bgc-audit/argo_workspace/argo-decoder-python/` (268 files, 7.9 MB).
  The zip was deleted after extraction. Nothing in this report is assumed from generic Argo/BGC
  conventions — every claim cites audited code, config, tests, or real data below.
- **Path shorthands:** `NEWROOT` = `/home/user/bgc-audit/argo_workspace/argo-decoder-python/`,
  `REPO` = `/home/user/incois-arpy-decoder` (existing decoder + decoder-ui).

---

## A. Supported BGC parameters (found in code — nothing else claimed)

The new decoder's production chain (`cts4_realtime.process_float` → `writer.nc.write_profile`
with `is_bgc=True`) emits **exactly these BGC quantities**, no others:

| # | Parameter (NetCDF name) | Kind | Produced from | Equation location |
|---|---|---|---|---|
| 1 | `DOXY` | derived | O2 subtype records + CTD T/S + per-float foil cals + gsw density | `platforms/provor_cts4_ir_sbd/equations.py:246` `doxy_chain` |
| 2 | `CHLA` | derived | FLBB subtype records + telemetry dark + generic scale | `equations.py` `chla_ug_l` |
| 3 | `BBP700` | derived | FLBB subtype records + CTD T/S + telemetry dark/scale + generic khi | `equations.py` `bbp700_m1` |
| 4 | `CHLA_FLUORESCENCE` | derived (= CHLA value) | identical to CHLA by construction | `cts4_realtime.py` (`fl_vals`, `"chla_fluorescence": bg["chla"]`) |
| 5 | `C1PHASE_DOXY` | raw passthrough | O2 C1 / 1000 | `bgc.py:17,170` |
| 6 | `C2PHASE_DOXY` | raw passthrough | O2 C2 / 1000 | `bgc.py:18,171` |
| 7 | `TEMP_DOXY` | raw passthrough | O2 thermistor `(T−2000)/1000` | `bgc.py:19,172` |
| 8 | `FLUORESCENCE_CHLA` | raw passthrough | FLBB Chl / 10 | `bgc.py:25` |
| 9 | `BETA_BACKSCATTERING700` | raw passthrough | FLBB BB / 10 | `bgc.py:26` |

Explicitly **NOT** produced: `DOXY2`, `CHLA2`, `BBP532`, `NITRATE`, `PH`, `DOWN_IRRADIANCE`,
`UP_RADIANCE`, or any `_ADJUSTED` science (real-time `*_ADJUSTED` stays FillValue by design,
`writer/nc.py:1828-1833`). `TEMP_DOXY` coefficients T0–T5 exist in the reference CSV but the
polynomial is **not implemented by design** — the published `TEMP_DOXY` is the raw optode
thermistor reading (`equations.py` docstring; `resolve.py` `_DOXY_EXTERNAL_REQUIRED` still
lists T0–T3 as required external metadata for provenance completeness).

Two DOXY implementations exist in the tree — only one serves this platform:
- `platforms/provor_cts4_ir_sbd/equations.py` — used by the CTS4/BR chain (this report).
- `derived/doxy.py` — legacy ARVOR-I/APEX path (`platforms/provor_ir_sbd/decoder.py:126`,
  `sensors/ctd.py:482 attach_doxy`, meta-JSON `CALIBRATION_COEFFICIENT[0].OPTODE`). Identical
  old-vs-new (`diff` clean); never imported by the CTS4 platform. Do not mix the two.

---

## B. Exact field names (wire → Python → profile-dict → NetCDF)

**B.1 Raw record dataclasses** (`platforms/provor_cts4_ir_sbd/bgc.py`):
- `O2Record` (`bgc.py:95-105`): `pres_dbar`, `c1_phase_deg`, `c2_phase_deg`, `temp_c`
  (from meas subtype 3 "DOXY_CLASS", 10 records/packet, 12-byte stride; `bgc.py:57-61`).
- `FlbbRecord` (`bgc.py:122-130`): `chl_raw: int`, `bb_raw: int`, `pres_dbar`,
  `fluorescence_counts`, `backscatter_counts` (subtype 6 "OPTICS_FLBB", 21 records/packet,
  6-byte stride; `bgc.py:64-66`).
- Wire scalings (`bgc.py:71-79` + docstring lines 15-26): `P/10` dbar; `C1/1000`, `C2/1000`
  degrees; `(T−2000)/1000` °C; `Chl/10`, `BB/10` counts.

**B.2 Per-cycle container** (`cts4_realtime.py:120-147` `CycleDecode`): `cycle`, `ctd/o2/flbb`
record lists, index-aligned `ctd_juld/o2_juld/flbb_juld` (each from its own type-0 packet
timestamp — never synthesized), `ctd_slot/o2_slot/flbb_slot` (packet index within the
sensor run), `vectors`, `pressures`, `halves`.

**B.3 Profile-dict keys → NetCDF variables** (`writer/nc.py:1352-1360` `_RTQC_SOURCE_KEY`
and `write_profile` `is_bgc` branch ~1812-1810):
`pres`→`PRES`, `c1phase`→`C1PHASE_DOXY`, `c2phase`→`C2PHASE_DOXY`,
`temp_doxy`→`TEMP_DOXY`, `doxy`→`DOXY`, `fluorescence`→`FLUORESCENCE_CHLA`,
`beta`→`BETA_BACKSCATTERING700`, `chla`→`CHLA`, `chla_fluorescence`→`CHLA_FLUORESCENCE`,
`bbp`→`BBP700`. Core R files use `pres/temp/psal` only.

**B.4 Trajectory (Rtraj) parameter order** (`nc/rtraj_cts4.py:30-35` `TRAJ_PARAMS`,
N_PARAM=12): `PRES, FLUORESCENCE_CHLA, BETA_BACKSCATTERING700, CHLA, CHLA_FLUORESCENCE,
BBP700, C1PHASE_DOXY, C2PHASE_DOXY, TEMP_DOXY, DOXY, TEMP, PSAL`.
`ADJUSTED` twins exist for `CHLA, CHLA_FLUORESCENCE, BBP700, DOXY, TEMP, PSAL` (line 36-38).
BGC measurement codes (`platforms/provor_cts4_ir_sbd/rtraj_build.py`): MC 590 ascent series
(one row per transmitted packet per sensor), MC 290 park series (3 rows/sample: CTD / optode
DOXY / FLBB CHLA+BBP700), MC 301 representative park mean (PRES/TEMP/PSAL/C1/C2/TEMP_DOXY/
DOXY/FLUO/BETA/CHLA/BBP700 + CHLA_FLUORESCENCE), plus MC 503/599/600/703 engineering rows.

**B.5 Meta file parameter order** (`writer/nc.py:80-91`, N_PARAM=11): `PRES, TEMP, PSAL,
C1PHASE_DOXY, C2PHASE_DOXY, TEMP_DOXY, DOXY, FLUORESCENCE_CHLA, BETA_BACKSCATTERING700,
CHLA, BBP700` (sensor map line 791; units lines 116-124).

---

## C. Units (exact strings published)

From `writer/nc.py:116-124` `PARAMETER_UNITS` (also `nc/rtraj_cts4.py:40-53`):

| Variable | Units string | Note |
|---|---|---|
| `PRES` | `decibar` | |
| `C1PHASE_DOXY`, `C2PHASE_DOXY` | `degree` | |
| `TEMP_DOXY` | `degree_Celsius` | raw thermistor |
| `DOXY` | `micromole/kg` | `doxy_chain` output `doxy_umol_kg` |
| `FLUORESCENCE_CHLA`, `BETA_BACKSCATTERING700` | `count` | wire counts ÷ 10 |
| `CHLA` | `mg/m3` | numerically = µg/L from `(FLUO−DARK)×0.0073` |
| `CHLA_FLUORESCENCE` | `ru` | relative units; value identical to CHLA |
| `BBP700` | `m-1` | |
| `TEMP` / `PSAL` | `degree_Celsius` / `psu` | core, for association context |

Valid ranges published on BR vars (`writer/nc.py`): C1 10–70, C2 0–15, TEMP_DOXY −2–40,
DOXY −5–600, CHLA_FLUORESCENCE −0.2–100; **no** valid_min/max on CHLA/BBP700 (INCOIS spec
forbids them). C_format/FORTRAN_format/resolution per var are in the same block.

---

## D. Data structure (files, profiles, alignment)

**D.1 Float directory layout** (`cts4_realtime.py` docstring + `process_float`):
`<out>/<WMO>/{WMO}_meta.nc, {WMO}_tech.nc, {WMO}_Rtraj.nc, profiles/R<WMO>_<CCC>.nc,
profiles/BR<WMO>_<CCC>.nc`. Real-time only — no D/BD outputs (integration test asserts
their absence; `test_provor_cts4_phase4_products_integration.py:63-64`).

**D.2 BR N_PROF layout** (`writer/nc.py:97-101` `BGC_STATION_PARAMETERS_TEMPLATE`,
N_PARAM=6, N_CALIB=2):
- N_PROF=1: primary CTD pressure grid, BGC fill (`[PRES,"","","","",""]`)
- N_PROF=2: near-surface CTD grid (≤ pump cutoff), BGC fill — **omitted entirely when the
  cycle sampled nothing above the cutoff** (`cts4_realtime.py`, `del bgc[1]`), yielding
  N_PROF=3 files (observed: 2902086×1, 2902087×1, 2902088×2, 2902114×2 per
  `PROVOR_CTS4_10FLOAT_GENERICITY_AND_GDAC_PARITY_2026-09-11.md`)
- N_PROF=3: optode profile `[PRES, C1PHASE_DOXY, C2PHASE_DOXY, TEMP_DOXY, DOXY, ""]` —
  emitted only if the optode recorded profile-phase samples, on the **optode's own**
  ascending pressure grid (never the CTD grid)
- N_PROF=4: fluorometer profile `[PRES, FLUORESCENCE_CHLA, BETA_BACKSCATTERING700, CHLA,
  CHLA_FLUORESCENCE, BBP700]` — emitted only if the FLBB recorded profile-phase samples,
  on the **FLBB's own** ascending grid

R files mirror this with N_PARAM=3 (`writer/nc.py:103-108`): primary / near-surface /
optode-grid-ref (pressure-only) / FLBB-grid-ref (pressure-only).

**D.3 Cross-sensor association** (`cts4_realtime.py:_bgc_values`, `_ascent_samples`,
`_park_samples`): BGC levels keep their own pressures; CTD TEMP/PSAL are attached per BGC
level via `nearest_ctd` (nearest-pressure match over the whole CTD series). DOXY additionally
needs per-level TEOS-10 potential density (`derived.density.potential_density`, gsw,
ref 0 dbar) at the cycle's lon/lat — the constant-1.025 shortcut is not used.

**D.4 Cycle numbering:** published `CYCLE_NUMBER` = 253-vector `total_profiles`
(`NUMBER_SubCyclesDoneSinceDeployment`), not the float-internal counter (which is one
lower and lives only in tech row 50). `DATA_MODE` is `R` everywhere; `DATA_STATE_INDICATOR`
`2B`; `JULD` = surfacing time (ascent end − 10 min NKE wait via `MissionClock`).

---

## E. Float types (no uniform-BGC assumption)

- **Family:** NKE PROVOR CTS4, decoder-301, telemetry format 5.8 (`dac_format_id "5.8"`),
  Iridium SBD; `PLATFORM_FAMILY "FLOAT"`, `PLATFORM_TYPE "PROVOR_III"`, maker NKE
  (`writer/nc.py` ExternalMeta defaults + module docstring).
- **Sensors** (`writer/nc.py:250-253`, reference CSV `sensor_model` column):
  CTD `SBE41CP` (PRES/TEMP/CNDC) · optode `AANDERAA_OPTODE_4330` (DOXY family) ·
  optics `ECO_FLBB` (CHLA/BBP700 family). 142° scattering geometry, khi=1.097
  (`family_constants.py:75`), 700 nm.
- **Reference coefficient coverage** (`config/metadata/provor_cts4_301_reference.csv`,
  1770 rows; schema `scope,wmo,sensor_model,sensor_serial,parameter,coefficient,value,
  source_file,source_variable,interpretation`): all 15 WMOs carry the same 4-parameter set
  `{BBP700, CHLA, DOXY, TEMP_DOXY}` —
  real INCOIS 301 floats `2902086–2902093, 2902113, 2902114, 2902115, 2902118, 2902120`
  (13) plus `2902130/2902131` (hypothetical — also the only 2 rows flagged hypothetical in
  `provor_cts4_pub_bbp_scales.csv`). DOXY has 107 coefficients/float (Stern-Volmer foil
  c0–27/m/n, PhaseCoef0–3, solubility A/B/C/D, Pcoef1–3, Spreset); CHLA 2; BBP700 3
  (DARK/SCALE/khi); TEMP_DOXY 6 (T0–T5).
- **Authority layers** (`resolve.py` docstring — read, don't paraphrase loosely):
  1. `family_constants.py` = authoritative 88 family-generic numbers (SCALE_CHLA 0.0073,
     KHI_700 1.097, solubility consts, structural zeros); the CSV is *verified against
     them* (1e-12), never the source. 2. Telemetry 250 free-zone FLBB half
     (serial/dark_chl/scale_chl/dark_bb/scale_bb/scale_chl_2) — CHLA/BBP need no other
     per-float input. 3. External per-float DOXY foil cals (PhaseCoef0/1, c0–20, T0–T3)
     via FLBB-serial→CSV row (`doxy_cal_for_group`) or explicit dict
     (`doxy_cal_from_external[_dict]`) for new floats. 4. CSV as provenance/audit.
- **Raw corpus → WMO** (10 IMEI-suffix groups,
  `PROVOR_CTS4_10FLOAT_GENERICITY_AND_GDAC_PARITY_2026-09-11.md` §5 — live GDAC census
  2026-09-11, not assumed):

  | WMO | group | GDAC holdings | usable R/BR parity |
  |---|---|---|---|
  | 2902093 | 17960 | 702 R / 468 BR / SR | **yes — the only direct-parity float** (cycles 45–53) |
  | 2902115 / 2902114 / 2902118 / 2902086 / 2902092 / 2902087 / 2902088 | 00530/06580/06640/12170/20000/25980/29030 | D/BD only | no (delayed = reprocessed, not a real-time target) |
  | — (FLBB 3043/3044, no INCOIS meta) | 03530 / 03580 | — | DATA-COVERAGE, nothing publishable |

- **Non-uniformity is structural:** BGC presence varies per cycle (CTD-only / BGC-only /
  tech-only cycles all occur), per sensor (N_PROF=3/4 emitted only for recording sensors),
  and per float (03530/03580 unresolvable). Any UI must treat BGC as per-cycle optional.

---

## F. Per-cycle availability rules (exact skip/publish logic)

From `cts4_realtime.process_float` (all `skipped[cyc]` strings verbatim):
- No 253 FloatTime/GPS → `"DATA-COVERAGE: no 253 FloatTime/GPS — profiles not written
  (no fabrication)"` (no position ⇒ no profiles at all).
- No CTD and no BGC records → `"DATA-COVERAGE: tech-only cycle (no measurement records)
  — no profiles written"`.
- CTD records but no profile phase (e.g. shallow commissioning dive) → `"DATA-COVERAGE:
  CTD records carry no profile phase (shallow/test dive) — R not written"`.
- No CTD → `"DATA-COVERAGE: no CTD records — R not written"` (BR may still be written
  with `with_doxy_bbp=False`: CHLA yes, DOXY/BBP forced to None → fill).
- No BGC profile-phase records → `"DATA-COVERAGE: no BGC profile-phase records — BR not
  written"`.
- Integration-test manifestation (WMO 2902086): 15 R + 16 BR files; cycle 103 skipped
  (no CTD), 115 skipped (tech-only).

Derived-parameter gating inside `_bgc_values`: CHLA needs only FLBB+telemetry dark;
BBP needs CTD (`with_doxy_bbp and ctd`); DOXY needs CTD **and** a resolved `doxy_cal`.
Park (MC 290/301) and ascent (MC 590) series need `nearest_ctd` matches per sample.

---

## G. Missing-value conventions (audited, exact)

- **Fill sentinels** (`writer/nc.py:67-71`): `FLOAT_FILL 99999.0` (f4), `DOUBLE_FILL
  99999.0`, `JULD_FILL 999999.0`, `INT_FILL 99999`, char blank. `_FillValue` is passed to
  `createVariable(..., fill_value=...)` only (module docstring).
- **QC policy** (`writer/nc.py:_write_qc_vars`, `rtqc/cts4.py` docstring):
  - Raw channels (`C1PHASE_DOXY, C2PHASE_DOXY, FLUORESCENCE_CHLA, BETA_BACKSCATTERING700`)
    stay `0` (no QC performed) — verified against INCOIS 2902093.
  - `TEMP_DOXY/DOXY/CHLA` reach `1`/`3` via RTQC; **DOXY and CHLA are denied `1` by their
    own manuals (tests 57/63 mandate `3`)**; GDAC delayed files show `DOXY_QC=3` (confirmed
    on `incois_BD2902091_001.nc`: `DOXY_QC 33333333`, `PROFILE_DOXY_QC B`).
  - QC is blank `' '` exactly where data is fill (FileChecker rule); all-inert profile
    rows yield blank `PROFILE_<PARAM>_QC` (table-2a port `compute_profile_quality_flag`).
  - `doxy_missing` (= `inputs.doxy_external_calib is None`) ⇒ DOXY all-fill with `DOXY_QC
    '9'` and `PROFILE_DOXY_QC '9'` — "preserves C1/C2/TEMP_DOXY but sets DOXY to fill QC 9"
    (`cli/main.py` publish-cts4 docstring; `writer/nc.py:1500-1520,1558,1821-1826`).
- **RTQC battery** (`rtqc/cts4.py:run_cts4_rtqc` + `rtqc/medd.py`): common tests 6
  (ranges: DOXY −5–600, TEMP_DOXY −2.5–40, CHLA/CHLA_FLUORESCENCE −0.2–100; raw channels
  have **no** published range — none applied), 8, 9, 11, 12 (TEMP_DOXY rollover Δ>10 °C),
  13 (raw channels only), 14, 19 (needs CONFIG_ProfilePressure), 21/22 (near-surface),
  25 MEDD (TEMP-only output, CTD params), 5/16/18 cross-cycle (CTD), **57 DOXY, 62 BBP700
  (5 sub-tests incl. 62.5 parking hook needing park pressure; skipped if unknown), 63
  CHLA/CHLA_FLUORESCENCE**. Merge is worst-flag-wins; a test whose input is absent aborts,
  never guesses. BBP manual §2.6 flag policy; no delayed-mode adjustments anywhere
  (NPQ, SAGEO2 gain deliberately unimplemented).
- **Padding:** `is_padding_{ctd,o2,flbb}` (`assoc.py`) filters filler records before any
  science; `nearest_ctd` returns None-safe (callers skip samples without a CTD match).

---

## H. Exact API fields (current surface — no BGC API exists)

**H.1 decoder-ui REST (REPO `decoder-ui/service/api.py`, 834 lines, zero BGC mentions):**
`GET /health`, `/geography/india-eez`, `/presets`, `/runs`, `/runs/{id}`,
`/runs/{id}/events`, `/runs/{id}/cycles/{n}`, `/runs/{id}/outputs/{file}`,
`POST /decode {wmo,…}`, `POST /batch/decode-all {wmos?,force?}`, batch stop/list/triage,
send-email, email-config, ingestion status/arrivals/ack/scan, `/sse` event stream.
Per-cycle science payload = `CycleRecord` (`service/models.py:112-127`):
`cycle_number, raw_cycle_key, status, received_at, juld, juld_formatted, latitude,
longitude, position_qc, messages_received/selected, levels_count, engineering_data,
rtqc_summary{qcp_hex,qcf_hex,tests_done,tests_failed,flagged_levels},
ctd_samples[{level,PRES,TEMP,PSAL,CNDC?,PRES_QC,TEMP_QC,PSAL_QC,CNDC_QC?}], errors`.
`OutputFileInfo` (`models.py:130-144`) carries generic `filename, category, filepath,
filesize_bytes, checksum_sha256, cycle, dimensions{}, variables[], global_attrs{},
qc_stats{}, qcp_hex, qcf_hex, xml_content?` — `variables[]` is populated from
`ds.variables.keys()` (`runner_instrumentation.py:666`) so BGC var names would appear
there automatically, but no per-level BGC data is extracted.

**H.2 New-decoder entry points (no HTTP; programmatic/CLI only):**
- Production: `cts4_realtime.process_float(group_dir, wmo, out_root, external_meta,
  decoder_version="PY-301-0.4.0", institution="IN") -> FloatProducts(wmo, meta_nc,
  tech_nc, rtraj_nc, r_files{}, br_files{}, skipped{}, clock, tech_rows, rtraj_rows)`.
  **No CLI command and no service endpoint invokes it** — only tests import it
  (`test_provor_cts4_fleet_genericity.py`, `test_provor_cts4_phase4_products_integration.py`).
- `ExternalMeta` REQUIRED fields (`writer/nc.py:196-348`, writer raises if absent):
  `float_serial_no, wmo_inst_type, launch_date/latitude/longitude, project_name, pi_name,
  config_parameter_names + config_mission_values (or legacy values), sensor_serial_nos
  (6 entries)`; optional 161-entry launch config, 11-entry predeployment tables,
  `id` (DOI; never defaulted to WMO).
- `ExternalMeta` is built from a GDAC meta.nc
  (`platforms/provor_cts4_ir_sbd/external_meta_io.py:49 build_external_meta_from_gdac(meta_nc, wmo)`;
  legacy copy at `provor_cts4_pipeline.py:58`) — i.e. **decoding a float today requires
  that float's GDAC meta.nc as an input**, a real onboarding dependency for any UI flow.
- CLI `publish-cts4` (`cli/main.py:509-620`, default `--decoder-version PY-301-0.3.0`)
  drives only `PublicationBuilder` (writer-level, needs pre-formed profiles +
  `--external-meta` JSON + `--tech-records` JSON); it does **not** run telemetry decode.
  `decode-float`/`dual-run`/`shadow` drive legacy `run_pipeline`, whose decoder registry
  (`platforms/__init__.py`) contains **only** `apex_argos` + `provor_ir_sbd` — the CTS4
  platform is not registered, so **no current backend path can decode a 301 float**.
- Quarantined (do not use): `platforms/provor_cts4_ir_sbd/provor_cts4_pipeline.py` —
  superseded draft with a fabricated `DOXY=200.0` fallback and wrong `doxy_chain` call,
  explicitly excluded by `cts4_realtime.py`'s docstring.

---

## I. Current decoder-ui parameter handling (audited file:line)

- **Service extraction** (`service/runner_instrumentation.py:497-650
  extract_run_artifacts`): globs `<nc>/<wmo>/profiles/*.nc`, reads **N_PROF index 0 only**
  (`var[0, idx]`), **PRES/TEMP/PSAL/CNDC + QCs only** → `ctd_samples`; fill→None at
  `abs(v) < 99990`; `flagged_levels` counts QC 3/4 over P/T/S only. Everything under
  `profiles/` (R and BR alike) is categorized `mono_profile` and counted into
  `profile_count`/`missing_profiles` (`execute_decoder_with_observability`).
- **Models** (`service/models.py`, `frontend/src/types/index.ts:107-117`): `ctd_samples`
  schema is PRES/TEMP/PSAL/CNDC (+QCs) end to end; no BGC-typed field anywhere.
- **Charts** (`frontend/src/components/ScientificProfileChart.tsx`): `paramKey: "TEMP" |
  "PSAL"` only; `CtdRecord` = PRES/TEMP/PSAL(+CNDC)+QCs; hover/axis/units hardwired to
  °C/psu/dbar. Fed by `ResultsWorkspace.tsx:256-288` (`tempData`/`psalData` memos) and
  rendered twice (TEMP + PSAL) at lines 1176-1195; level table at 1296 maps the same
  CTD-only samples.
- **RTQC modal** (`frontend/src/components/RtqcModal.tsx:6+`): static
  `RTQC_REFERENCE_TESTS` catalogue for PASS_A–D with CTD rules (e.g. TEST006 TEMP/PSAL/
  CNDC ranges, spike/gradient/drift thresholds) — no tests 57/62/63, no BGC ranges.
- **Reports** (`service/pdf_report.py:588-589`, `report_data.py`): fleet narrative counts
  degraded QC "across PRES/TEMP/PSAL"; QCP$/QCF$ masks parsed from HISTORY (`CF/CV`
  actions assumed; CTS4 writer emits `CF`/`CV` — compatible — but mask semantics for
  BGC tests are undisplayed).

---

## J. Limiting assumptions (each verified in code)

1. **N_PROF 0 = the profile.** `var[0, idx]` reads the primary core profile only; BR
   sensor profiles live at N_PROF 2/3 (0-based) and are never touched.
2. **CTD-only sample schema**, backend (`CycleRecord.ctd_samples`) through frontend
   (`CtdRecord`, `paramKey` union) — BGC has no typed slot.
3. **TEMP|PSAL chart union** — adding a parameter means extending the union, colors,
   units, decimals, QC merge (hover merges TEMP_QC+PSAL_QC today).
4. **Static CTD RTQC catalogue** in the modal; BGC tests/ranges/policies (esp. the
   "DOXY/CHLA capped at 3" rule) are unknown to the UI.
5. **BR files counted as core profiles** (`mono_profile` by path substring; profile
   counts and missing-profile math mix R and BR).
6. **Fill threshold `99990`** matches the 99999 sentinel (safe), but QC-blank-on-fill and
   QC-`0`-on-raw-channels semantics are not interpreted (a `0` would display as-is).
7. **Legacy pipeline invocation**: service calls `run_pipeline` (`runner_instrumentation.py`
   `execute_decoder_with_observability`), which cannot select the CTS4 platform at all (§H).
8. **Uniform-float mental model**: batch/fleet views assume every float yields comparable
   per-cycle profiles; CTS4 BGC is per-cycle/per-sensor optional with DATA-COVERAGE skips.

---

## K. Real decoded BGC examples (no fabrication; sources labeled)

**K.1 GDAC-anchored equation vectors** (unit-test fixtures transcribed from GDAC +
meta.nc-literal cals, `tests/unit/test_provor_cts4_phase2a_units.py:640-730`):
- DOXY in: P=107.40 dbar, C1=42.483°, C2=3.504°, T=23.654 °C, S=36.321, ρ=1.024753 kg/L,
  WMO 2902091 PhaseCoefs(−1.60243, 1.01254, 0, 0) + 28-term foil + Weiss solubility →
  out: tphase 38.979°, Δp 83.034, airsat 40.289%, cstar 5.9225 mL/L, molar 106.453 µmol/L,
  scorr 0.81117, pcorr 1.00506 → **DOXY 84.692 µmol/kg** (published 84.920; <0.6 gap
  classified PUBLICATION-RTQC — INCOIS applies an undocumented adjustment the chain
  refuses to fit). Deep vectors: DOXY 0.114 µmol/kg at 197 dbar; 0.102 at 465 dbar.
- CHLA: FLUO 142.8 counts → (142.8−48)×0.0073 = **0.69204 mg/m³ exact** (abs 1e-6).
- BBP700: BETA 146.3, T 24.419 °C, S 36.444 → BETASW 6.0124e-05 → **0.00077466 m⁻¹
  exact** (abs 1e-8), dark 49 / scale 1.773e-06 / khi 1.097 (scales match the 250
  free-zone asserts: serial 2662, scale_chl 0.0073, dark_chl 48, scale_bb 1.773e-06,
  dark_bb 49; lines 463-469).
- `chla_ug_l(123, 48, 0.0073) = 0.5475` (line 575) — exactly the GDAC BD level-0 CHLA below.

**K.2 GDAC delayed reference** (`provor_bio_irsbd/ref/gdac_incois_301/incois_BD2902091_001.nc`,
read directly 2026-09-16; **delayed-mode evidence, not decoder output**): N_PROF=4,
N_PARAM=6, N_LEVELS=95, DATA_MODE `RRDA`, decoder `CODA_057d`; optode grid starts
P 0.4–5.7 dbar with C1≈32.95–33.02°, C2≈3.52°, TEMP_DOXY≈25.20 °C, DOXY≈181.76–182.68
µmol/kg; FLBB grid starts FLUO 123–142, BETA 111–206 counts, CHLA=CHLA_FLUORESCENCE
0.5475–0.6862, BBP700 0.00034–0.00150 m⁻¹; delayed-only equations (SAGEO2 gain G,
NPQ/CHLA_NPQ) present in SCIENTIFIC_CALIB — the real-time decoder deliberately omits them.

**K.3 Fleet-scale run facts:** integration WMO 2902086 → 15 R + 16 BR, cycles 103/115
skipped with DATA-COVERAGE strings (§F); Rtraj N_CYCLE=18 (launch+17), N_PARAM=12, all
DATA_MODE R (`test_provor_cts4_phase4_products_integration.py:51-155`). Direct R/BR
parity exists **only** for 2902093 cycles 45–53 (R: EXACT incl. JULD ±0.000000 s;
BR raw channels EXACT; CHLA exact; DOXY within ~0.09 maxabs w/ PUBLICATION-RTQC class;
BBP700 systematic ratio 1.0268 = telemetry-original vs GDAC-corrected scale, hence the
`TELEMETRY_ORIGINAL`/`INCOIS_CORRECTED` writer modes; `PROVOR_CTS4_FINAL_PARITY_REPORT.md`).

**K.4 No real decoded CTS4 BR/Rtraj files ship in the extracted subset** — the two
`validation_fleet_parity/*_mono.json` are CORE-only (PRES/TEMP/PSAL) oracle comparisons
for ARVOR floats 1902844/7902408, not CTS4 BGC. `2902222` (104 KB) is an unidentified
binary blob (pickle-magic bytes), not decoded output. The closest "real decoded" artifacts
are the K.1 vectors + the tests that run `process_float` against the raw corpus (corpus
`.sbd` files were excluded from extraction; `filelist.txt` inventories the zip).

---

## L. Backend↔UI gaps (severity-ordered; all verified in code)

- **G1 — UI cannot decode any 301 float (blocking).** Service invokes legacy
  `run_pipeline` → registry has only APEX/ARVOR-I (§H). `process_float` has no CLI or
  endpoint. Any BGC UI on live backend data needs a new service path first.
- **G2 — Silent BGC loss in N_PROF≠4 BR files (backend data bug, blocks trust).**
  `write_profile` cycles the 4-row station template positionally (`writer/nc.py`:
  `template = [template[i % 4] ...]` when `n_prof != 4`), but `cts4_realtime` appends
  sensor profiles positionally after deleting the near-surface slot. Any BR with a
  deleted N_PROF=2 ([primary,o2,fl]) gets template rows [r0,r1,r2] ⇒ the O2 profile is
  masked PRES-only and the FLBB profile is masked to the optode template — **all BGC
  values → fill, self-consistently labeled, no error**. Same for [primary,near,fl]
  (o2 absent) and all n_prof=2 layouts; only 4-profile and [primary,near,o2] layouts
  survive. N_PROF=3 files are admitted production output (§D.2), and the affected floats
  are D/BD-only on GDAC so no parity check can catch it. (R files suffer only a minor
  STATION_PARAMETERS over-claim on the shifted ref profile.)
- **G3 — Missing-DOXY-cal crash on the `process_float` path.**
  `resolve_group` stores the `KeyError` object in `cals["doxy"]`
  (`resolve.py:624-672`, typed `DoxyCal | KeyError`), but `cts4_realtime` tests only
  `is not None` (`:263,471,541,691`) and then dereferences `.phase/.foil/.sol` ⇒
  `AttributeError` for any group whose FLBB serial has no reference row (today: 03530/
  03580) instead of the documented QC-9/DATA-COVERAGE path. (The QC-9 path only works via
  `PublicationBuilder` with `doxy_external_calib=None`.)
- **G4 — External-meta chicken-and-egg.** `process_float` needs a fully-populated
  `ExternalMeta` (§H.2), currently built from the float's own GDAC meta.nc. New floats
  (no GDAC meta) need a hand-authored metadata record; no UI/CLI authoring flow exists.
- **G5 — UI reads N_PROF-0 CTD only** (§I): BGC levels, sensor grids, BGC QC, and Rtraj
  MC 290/301/590 series are all invisible to service + frontend + PDF.
- **G6 — Counts conflate R and BR** (`mono_profile` by path; §I) — fleet/profile/missing
  math is wrong the moment BR files exist.
- **G7 — Static CTD RTQC catalogue** (§I) can't represent tests 57/62/63, the QC≤3 cap on
  DOXY/CHLA, QC-0-on-raw-channels, or per-profile `tests_done` sets.
- **G8 (minor) — Fallback predeployment strings invent DARK_CHLA=49** (`writer/nc.py:861`)
  while telemetry+CSV agree on 48 for 2902091 (§K.1) — fallback path only, but the writer's
  "no fabrication" contract says fallbacks must be explicit-unavailable markers.

---

## M. Exact next-phase UI locations (do not implement in this phase)

Service (`REPO/decoder-ui/service/`):
1. `runner_instrumentation.py:497-650` `extract_run_artifacts` — N_PROF-aware reader;
   add BR branch (prof index 2/3 by STATION_PARAMETERS, not position), per-grid samples,
   BGC QC interpretation, R/BR-split categories and counts.
2. `models.py:112-144` — `CycleRecord` BGC slots (e.g. `bgc_samples` per sensor grid),
   `OutputFileInfo.category` R/BR split, `RtqcTestInfo` BGC ranges (tests 57/62/63).
3. `api.py` `/runs/{id}/cycles/{n}` + `/runs/{id}/outputs/{file}` — expose the new slots;
   new endpoint(s) for the CTS4 decode path (G1/G4: group + external-meta inputs).
4. `report_data.py` + `pdf_report.py:588-589` — BGC-aware fleet narrative/QC wording.
5. New service module (suggested `cts4_service.py`) wrapping `process_float` + preflight
   checks for G2/G3/G4 — never call the quarantined `provor_cts4_pipeline.py`.

Frontend (`REPO/decoder-ui/frontend/src/`):
6. `components/ScientificProfileChart.tsx` — extend `paramKey` beyond TEMP|PSAL (units,
   decimals, colors, QC merge per param; per-sensor pressure grids).
7. `components/ResultsWorkspace.tsx:256-288,1176-1195,1296` — BGC memos, chart instances,
   level-table columns; per-cycle BGC presence/absence + DATA-COVERAGE messaging.
8. `types/index.ts:107-117` — `ctd_samples` sibling type(s) for BGC samples.
9. `components/RtqcModal.tsx:6+` — replace/augment static CTD catalogue with BGC tests
   and the QC≤3 / QC-0 policies from §G.

Backend (fix before/with UI; owned by decoder, not UI):
10. `NEWROOT/src/argo_decoder/writer/nc.py` `write_profile` template selection (G2) —
    key template rows by profile content/role, not position; same for
    PARAMETER_DATA_MODE defaults. 11. `NEWROOT/.../cts4_realtime.py` `is not None` →
    `isinstance DoxyCal` + `doxy_calib=None` on KeyError (G3). 12. CLI/service entry for
    `process_float` + external-meta authoring/validation (G1/G4).

---

## N. Recommendations (phased; investigation phase stays read-only)

1. **Do not build BGC UI on the current service path** — G1 makes it impossible and G2
   would display silently-emptied cycles as valid. Sequence: backend entry (G1/G4) →
   G2/G3 fixes with regression tests (N_PROF=3 BR with oe/fl present; unknown-serial
   group ⇒ QC-9, no raise) → service extraction → frontend.
2. **Read BR by STATION_PARAMETERS, never by position** — the only layout-robust rule
   given N_PROF∈{2,3,4} and optional sensors.
3. **Model BGC per sensor grid** (optode grid ≠ FLBB grid ≠ CTD grid); never resample or
   substitute grids in the UI — the backend's own rule (§D.3).
4. **Treat CHLA_FLUORESCENCE as display-alias of CHLA** (identical values, different
   units/semantics: mg/m³ vs ru) and label raw channels as un-QC'd (QC 0) vs derived.
5. **Enforce QC≤3 display cap awareness** for DOXY/CHLA and blank-on-fill; surface
   DATA-COVERAGE skip strings verbatim — they are the backend's honest signal.
6. **Keep real-time/delayed separated**: never compare live BR against GDAC D/BD numbers
   (category error per §E/§K.3); INCOIS_CORRECTED BBP mode is a publication-reprocessing
   lens, default TELEMETRY_ORIGINAL.
7. **Registry/metadata**: 301 floats need metadata-backend entries (JSON/CSV4) before
   any UI "Decode" action can target them; WMO stays externally supplied (7-digit
   validation is load-bearing).

---

## O. Files inspected (primary-source-of-truth set)

New decoder (`NEWROOT`): `src/argo_decoder/platforms/provor_cts4_ir_sbd/{__init__,
bgc, equations, assoc, resolve, family_constants, cts4_realtime, provor_cts4_pipeline
(quarantined), rtraj_build, tech_build, external_meta_io, mission_clock}.py` (full read:
bgc, equations, cts4_realtime, provor_cts4_pipeline, resolve, writer/nc, cli/main);
`src/argo_decoder/writer/nc.py` (1897 lines, full); `src/argo_decoder/nc/rtraj_cts4.py`
(params/units); `src/argo_decoder/rtqc/{cts4, medd}.py`; `src/argo_decoder/cli/main.py`
(full); `src/argo_decoder/platforms/__init__.py`; `src/argo_decoder/derived/doxy.py`
(header + importers); `config/metadata/provor_cts4_301_reference.csv` (1770-row census),
`provor_cts4_pub_bbp_scales.csv`, `provor_cts4_external_doxy_example.csv` (SYNTHETIC —
excluded from all claims); `tests/test_provor_cts4_{fleet_genericity,
phase4_products_integration}.py`, `tests/unit/test_provor_cts4_phase{1,2a,4}_units.py`;
`provor_bio_irsbd/{PROVOR_CTS4_10FLOAT_GENERICITY_AND_GDAC_PARITY_2026-09-11,
PROVOR_CTS4_FINAL_PARITY_REPORT}.md` (+17 sibling phase docs listed, not all read);
`ref/gdac_incois_301/incois_BD2902091_001.nc` + `incois_D2902091_001.nc` (BD header+values
read directly); `validation_fleet_parity/{1902844,7902408}_mono.json` (CORE-only, excluded
as BGC evidence); `IMPLEMENTATION_PROGRESS.md` (CTS4/BGC grep); `2902222` (binary probe).
Existing UI (`REPO/decoder-ui/`): `service/{api, models, runner_instrumentation,
report_data, pdf_report, triage, ingestion}.py`; `frontend/src/{types/index.ts,
components/{ScientificProfileChart, ResultsWorkspace, RtqcModal}.tsx}`.

---

## P. No-change confirmations

- `git -C REPO status --short` → **clean** (verified post-investigation; HEAD `838eb4b`).
- Zero writes under `REPO/` and under `NEWROOT/src/` in this phase — all work product is
  this report at `/home/user/bgc-audit/BGC_INVESTIGATION_REPORT.md` plus the read-only
  extraction in `/home/user/bgc-audit/` (zip deleted). Only environment-side effect:
  `pip install netCDF4` (sandbox site-packages, needed to read the GDAC reference file).
- Backend preview server on :8000 left running per standing instruction (untouched).

## Q. Verification checklist for the next phase (before any BGC UI code)

1. Re-run: `process_float` on group 12170 (WMO 2902086) → expect 15 R + 16 BR, skips
   {103,115}; on 03530/03580 → expect graceful DATA-COVERAGE (currently crashes — G3).
2. N_PROF=3 BR audit: list all BR with N_PROF≠4, confirm sensor data present post-G2-fix.
3. Confirm `variables[]` already surfaces BGC names via the generic indexer (§H.1).
4. Confirm GDAC R/BR census for 2902093 still live before quoting parity (§K.3).
5. New-float onboarding: hand-author one `ExternalMeta` (G4) and decode end-to-end.
6. Re-verify §P (clean tree) immediately before the first UI commit.
