# MIGRATION DOCUMENT — ARVOR-I Decoder, Mid-Phase-4A Handoff

**Written:** 2026-08-26 (user timezone Asia/Calcutta)
**Purpose:** Give a NEW chat complete context to continue this project exactly where it stands. The new chat receives this workspace (via Google Drive link). This document + the phase reports + the code are the source of truth. Nothing outside `/home/user/argo_workspace` survives.
**Current state in one line:** Phases 1–3 (raw decode → cycle reconstruction → scientific objects) are COMPLETE, tested (1887 passing) and documented; **Phase 4A (`_tech.nc` product) is ~40% investigated and 0% implemented** — all needed Coriolis MATLAB sources are now vendored into the repo (see §7), the exact parameter-emission rules of the three `_tech.nc` store functions are extracted (§8), and the next action is §9 step 1.

---

## 1. Project mission (long-running)

Python re-implementation of the Coriolis (Ifremer) Argo float decoder for the **ARVOR-I / PROVOR-Iridium-SBD family (decoder IDs 222-family and 232)**, validated against two real floats, with strict evidence rules: nothing is invented, Coriolis MATLAB is the reference but raw-telemetry/manual evidence overrides it when they disagree (and the disagreement is then documented).

**Floats:**
- **6990711** — dead float, launch 2025-03-02 05:16 UTC, 7 complete cycles, final burst 2025-05-01/02 transmits buffered cycles 5/6 after cycle 7.
- **7902408** — active float, launch 2026-03-25 17:44 UTC, complete cycles {1,4,9,12}, incomplete {2,3,5,6,7,8,10,11,13}, cycles 14/15 pending/unreceived; pre-launch factory (2025-09-19, 2025-11-20) and deck-test (2026-03-25 morning) transmissions form cycle −1 param-only buffer.

Raw data (read-only): `arvor_raw/ARVOR-I-raw-files/20260819/{6990711,7902408}/*.eml` (+ .sbd).

## 2. The current task — Phase 4A (user's spec, binding)

Implement ONLY the ARVOR-I **`_tech.nc`** product from the existing scientific/intermediate data.

**Decisions fixed by the user:**
- `_prof.nc` is NOT an implementation target (GDAC generates it from mono-profile products). Do NOT write a local prof.nc writer.
- Do NOT implement: `_Rtraj.nc`, trajectory interpolation, metadata product, unobserved packet types, unrelated families.
- Support the proven ARVOR-I engine/layout family first: decId 222 family and decId 232; reuse common definitions where layouts are proven identical; no WMO-specific branches.
- Architecture: `ArvorScienceResult → technical product model → _tech.nc writer` (clean separation; the NetCDF writer must NOT parse raw SBD packets).
- Investigate FIRST (done — see §8), create mapping `ArvorScienceResult source | Coriolis source | _tech.nc parameter | conversion/rule | evidence` with PROVEN/INFERRED/UNKNOWN per row.
- Validate on both floats: exact parameter names, order, count, values, units, fill values, cycle alignment, timestamps, firmware-dependent differences, incomplete/missing packets. GDAC comparison with scientific keys where available (note: NO PROVOR GDAC `_tech.nc` exists in the workspace — see §8.1 — so GDAC comparison is DATA-COVERAGE-limited; compare against raw telemetry + operator spreadsheets where applicable).
- Run: full pytest, ruff check, ruff format, mypy for modified files if configured (check `pyproject.toml`; mypy was not part of phases 1–3), FileChecker if available (jar NOT in workspace — ask user or reuse prior phase approach, §8.6).
- Classify every discrepancy FIXABLE / NOT FIXABLE / EXPECTED / DATA-COVERAGE / UNKNOWN.
- Regression proof: Phase 1/2/3 behavior unchanged (except explicit interface additions); APF9 and CTS4/221 decoder families untouched.
- Docs: `docs/phase_reports/ARVOR_I_PHASE4A_TECH_*.md` + append-only entry in `IMPLEMENTATION_PROGRESS.md` (never rewrite previous entries).
- **Stop boundary: do NOT begin `_Rtraj.nc`/trajectory after this phase.** End with implementation summary, parameter mapping, both-float validation, GDAC comparison, FileChecker result, regressions, recommended Phase 4B.
- If too large, split: (1) technical mapping (2) writer (3) real-float validation (4) GDAC/FileChecker validation. "Do not rush or guess."

## 3. Environment bootstrap (NEW CHAT MUST DO THIS FIRST)

Packages are NOT persisted between chats; files under `/home/user/argo_workspace` ARE. `/tmp` contents (including the extracted Coriolis archive) are GONE in a new chat — which is why everything needed was vendored into the repo (§7).

```bash
cd /home/user/argo_workspace/argo-decoder-python
pip install -e .          # required or imports fail (ModuleNotFoundError: argo_decoder)
pip install netCDF4 gsw ruff pytest py7zr   # gsw needed by 16 unit tests; netCDF4 for nc validation
python3 -m pytest tests/ -q                 # must be 1887 passed before any Phase-4A edit
python3 -m ruff check <files> && python3 -m ruff format <files>
```

If the Coriolis toolbox archive is ever needed again (NOT needed for 4A — vendored): open-access download `https://www.seanoe.org/data/00345/45589/data/120353.7z` (version 20250516_076a, ~98 MB), extract with `py7zr`.

There is no git repo (`.git` absent) — the workspace itself is the version control; never delete/rewrite existing files that earlier phases produced.

## 4. Workspace map

```
argo_workspace/
├─ argo-decoder-python/                    # THE repo
│  ├─ IMPLEMENTATION_PROGRESS.md           # append-only progress log (phases 1–3 not yet appended as one block; APF9-era entries exist)
│  ├─ src/argo_decoder/
│  │  ├─ platforms/provor_ir_sbd/
│  │  │  ├─ arvor_i.py                     # Phase 1: .eml/.sbd → packets. fields list is 1-INDEXED: fields[k] == MATLAB item k, fields[0]=0 placeholder
│  │  │  ├─ arvor_i_cycles.py              # Phase 2: sessions → cycle buffers, completion classification
│  │  │  ├─ arvor_i_science.py             # Phase 3 (~1270 L): ArvorScienceResult, timing, GPS/JAMSTEC, profiles, drift
│  │  │  └─ (frames/mission/profile/decoder.py — PROVOR legacy, mostly untouched)
│  │  └─ nc/                               # EXISTING NetCDF writer infra (built for the APEX/APF9 family, phases 4–6A)
│  │     ├─ admt.py                        # ADMT layout helpers (dims STRING2..128/DATE_TIME, fills, write_admt_dataset) — REUSE for ARVOR tech.nc
│  │     ├─ technical.py                   # APEX-family _tech.nc writer (Phase 6A.4) — the pattern to mirror, not to modify into ARVOR
│  │     └─ writer.py, mono_profile.py, trajectory.py, metadata_file.py
│  ├─ tests/
│  │  ├─ unit/test_arvor_i_science_rules.py          # Phase 3 unit (14)
│  │  ├─ integration/test_arvor_i_science_reconstruction.py  # Phase 3 integration (22)
│  │  ├─ integration/test_arvor_i_cycle_reconstruction.py    # Phase 2 (launch dates pinned here)
│  │  ├─ unit/test_technical_nc.py                   # APEX tech writer tests — DO NOT weaken
│  │  └─ data/arvor_i/coriolis_src/        # vendored Coriolis MATLAB (44 .m + _techParamNames/ + _argo_decoder_conf.json) — see §7
│  ├─ docs/phase_reports/ARVOR_I_PHASE1_RAW_2026-08-24.md, ARVOR_I_PHASE2_CYCLE_RECONSTRUCTION_2026-08-24.md, ARVOR_I_PHASE3_SCIENCE_RECONSTRUCTION_2026-08-25.md
│  ├─ phase5_reference/gdac_reference_dataset/<wmo>/meta/*_tech.nc   # 6 GDAC tech.nc refs — ALL APEX (2901339/2902201/03/06/2902222/23)
│  └─ parity_fresh_nc3/_filechecker_results/*.filecheck              # prior FileChecker outputs (APEX family)
├─ arvor_raw/ARVOR-I-raw-files/20260819/{6990711,7902408}/   # raw .eml/.sbd (read-only)
├─ Coriolis-data-processing-chain-for-Argo-floats-container/  # container clone (subset; lacks PROVOR store_* sources)
├─ uploads/ (operator txt for 2901304 etc.), ref2902224/ (APEX float 2902224 raw+GDAC nc — NOT ARVOR)
└─ ARVOR_I_INVESTIGATION_2026-08-24.md     # the original phase-1 investigation doc
```

## 5. Standing rules (user-set, carry across phases)

- No fabrication of telemetry, dates, or technical values; missing telemetry = DATA-COVERAGE, never back-filled.
- Email/mail timestamps are never used as float timestamps (the ONE Coriolis fallback that does — c13 profile date — is kept but explicitly labelled `date_source='iridium-mail'` and ledgered).
- No silent discard/dedup of scientific data; no forced GDAC parity vs raw/manual evidence; no invented packet types (7–14 off-limits without new evidence); preserve payload bytes; transport/session metadata separate from float data.
- Corrected Tech#2 expected-count mapping is PRIMARY (§6); never silently revert to Coriolis-as-coded.
- PROVEN / INFERRED / UNKNOWN labelling; disagreement ledger in reports; four-way disagreement → STOP and report.
- No WMO-specific patches; APF9 and CTS4/221 code and tests untouched; no weakened/deleted tests; regression documented before "complete"; state boundary + evidence before implementing; never contradict documented conclusions (use dated corrections).
- ruff check AND ruff format both run on changed files.
- Reports in `docs/phase_reports/`; `IMPLEMENTATION_PROGRESS.md` append-only.
- Phase boundary: after Phase 4A completes → STOP, recommend Phase 4B, do not start it.

## 6. Phase 1–3 key results (condensed; full detail in the three reports)

**Field indexing (PROVEN):** `fields[k] == MATLAB item k` (fields[0] is a placeholder 0). In MATLAB `tabTechN(k+ID_OFFSET)` with `ID_OFFSET=1` means item k.

**Tech#1 items:** 1=cycle; 5/6/7=dd/mm/yy; 8=float-day counter at cycle start (julD2FloatDayOffset = datenum(items5–7) − item8 = launch date, CONSTANT per float — verified); 9=minutes into day; 20=park day; 27/28=descent-to-prof start/end min; 38/39=ascent start/trans min; 41–46=floatTime; 47=pres offset; 53–60=lat/lon; 61=GPS valid; 62/64/65=status words; 66=EOL flag; 67–72=EOL date/time; 73=clock offset (s).

**Tech#2 items:** 2–13=misc/status + measurement counts; 15/16/17=sub-surface P/T/S (counts); 20=grounding count; 21–30=grounding details; 31–35=deep descriptors; 36–45=misc; 46–51=date/time; 52–57=hydraulic summary values; 58/59=ICE flags.

**nbMeas CORRECTION (user-confirmed PRIMARY):** expected measurement counts = Tech#2 ITEMS 8/9/11/12 (descShallow/descDeep/ascShallow/ascDeep); Coriolis-as-coded reads a_tabTech COLUMNS (items 9/10/12/13) — retained for comparison/provenance only.

**Sensors:** pres=(twos16(counts)+10000)/10 dbar (99999→9999.9 sentinel); psal=/1000; temp conversion in arvor_i.py; defaults dateDef 99999.99999999, presDef 9999.9, temp/salDef 99.999.

**Clock offset (units PROVEN from adjust_clock_offset_prv_ir.m):** measurement dates − s/86400; cycle timing fields − round(s/60)/1440; interpolation between events at transStartDate (fallback ascentEndDate), next event's float time pre-adjusted by its own offset, rounded to 1 s; cycle-0 in-air uses last event. (Coriolis typo `/14410` in adjust_hydrau documented, not copied.)

**GPS/JAMSTEC (fully read):** GpsRecord only when item61==1; qc chain per cycle anchored on previous cycle's last qc=1 fix; ≤3 m/s; within-cycle duplicate = identical lat AND lon AND date → qc4; within-cycle gap >1 day → qc4; unanchored first fix stays qc=1; cross-cycle byte-identical reuse at later date ACCEPTED (6990711 c5/c6 re-sent c4's fix with item61=0 → no record at all).

**Locations:** GPS (qc1) → Iridium-mail CEP<5 km 1/r²-weighted mean (qc1, at-sea mails only — `MailInfo.pre_launch` flag excludes factory/deck mails) → fill_empty interpolation/extrapolation (qc8, anchors deduped per distinct date; Coriolis anchors leading edges with the launch GPS position which is NOT in this dataset — DATA-COVERAGE, documented).

**6990711 validated:** 7 complete cycles; c1 descent 54/54, ascent 96+6/102; drift 1 then 17×6; clock offsets −5,−23×3,−69 s; no Param#1 → ascent_end=None (reason recorded), ascent dates = transStart(−adj).

**7902408 validated:** complete {1,4,9,12}; c1 descent 52/52, ascent 99+5/104; pending counts 30/28/72/45 on incomplete cycles; c13 forced incomplete, no Tech#2 → no expected counts, mail-sourced labelled date; config from Param#1: MC09=12, MC29=0, MC31=5, TC04=28000, TC22=33000; param-only pre-launch buffer cycle −1.

**Phase 3 API surface (what Phase 4A consumes):** `reconstruct_science(messages, launch_date)` / `reconstruct_science_from_directory(dir, launch)` → `ArvorScienceResult{cycles[], gps_records[], clock_offset_events[], float_config, mails[], param_only_cycles[], ref_day_offset, notes}`; `ArvorCycle{cycle_number, buffer, completed, delayed, ice_delayed, deep, go, timing(CycleTimeData), tech1, tech2, gps, drift[], profiles[], hydraulic[], params[], notes}`; `ArvorProfile{kind(descent|ascent_deep|ascent_shallow), direction, measurements[], date/date_adj/date_source, location, expected_n_meas, profile_completed, ...}`; `ArvorMeasurement` keeps raw counts + slot + packet + float date + adjusted date. NOTE: `tech1`/`tech2`/`hydraulic`/`params` hold `StreamPacket`s (packet objects with `.fields`); `ArvorCycle.deep` exists per cycle (drives the deep/shallow tech parameter split — see §8).

## 7. Vendored Coriolis sources (NEW — persisted this session)

All in `argo-decoder-python/tests/data/arvor_i/coriolis_src/` (previously 29 files; now 44 .m + `_argo_decoder_conf.json` + `_techParamNames/` (199 files: per-index-bucket JSON+CSV label tables `TECH_PARAM_DEC_ID → TECH_PARAM_NAME / MSG_LABEL / DESCRIPTION`)). Toolbox version 20250516_076a from SEANOE DOI 10.17882/45589.

Newly vendored, key for Phase 4A:
- `store_tech1_data_for_nc_222_to_227_231_232.m`, `store_tech2_data_for_nc_212_214_217_222_223_225_232.m`, `store_misc_tech_data_for_nc_212_214_216_to_218_222_to_232.m` (the three ARVOR-I emitters — fully read, §8)
- `decode_provor_2_nc.m` (thin driver → `decode_provor.m`), `decode_provor.m` (642 L orchestrator — NOT yet fully read), `create_nc_tech_file_3_1.m` (418 L, the actual `_tech.nc` writer — NOT yet fully read), `create_nc_tech_aux_file.m`
- `init_default_values.m` (globals incl. outputNcParam* defaults), `get_nc_tech_parameters_json.m` (label-table loader), `store_received_packet_type_info_for_nc.m` (packet-type count params — NOT yet read)
- `format_time_hhmm_dec_argo.m`, `format_time_mmss_dec_argo.m` (value formatters), `get_float_config_ir_sbd.m`, `get_config_value.m`, `sensor_2_value_for_temp_2xx_*.m` (pressure twin already vendored)
- `_argo_decoder_conf.json` (toolbox config)

## 8. Phase 4A investigation findings SO FAR (this session, from the vendored .m)

### 8.1 GDAC reference situation
- NO PROVOR/ARVOR GDAC `_tech.nc` exists in the workspace: the six `phase5_reference` refs AND `ref2902224` are all **APEX/WRC** floats. → GDAC parity comparison for ARVOR `_tech.nc` is DATA-COVERAGE-limited; the file LAYOUT (10 variables, dims incl. N_TECH_PARAM, STRING32/128, DATE_TIME=14) is fleet-standard and already proven in this repo by `nc/admt.py` + `nc/technical.py` against those APEX GDAC files. Reuse `write_admt_dataset` conventions; mirror `technical.py` structure for the ARVOR model.
- 2902224_tech.nc (APEX) inspection confirmed the standard shape: vars DATE_CREATION, DATE_UPDATE, PLATFORM_NUMBER, DATA_CENTRE, DATA_TYPE, FORMAT_VERSION, HANDBOOK_VERSION, TECHNICAL_PARAMETER_NAME(STRING128!), TECHNICAL_PARAMETER_VALUE(STRING128), CYCLE_NUMBER(int32, dim N_TECH_PARAM). NOTE: in that file TECHNICAL_PARAMETER_NAME dims were (N_TECH_PARAM, STRING128) — check `create_nc_tech_file_3_1.m` for the authoritative ARVOR dims/order.

### 8.2 The three ARVOR-I emitters (PROVEN, read end-to-end)
All append rows `(cycleNum, paramIndex)` + value to globals `g_decArgo_outputNcParamIndex/Value`; `tabTechN(k+1)` == item k.

**store_misc_tech_data_for_nc (per cycle, always):**
- `1012` ICE-mode activation flag: 1 if first-cycle-a-type-7-packet-received (`g_decArgo_7TypePacketReceivedCyNum`) ≤ current cycle, else 0 — NOT emitted for decoderId 216 (Arvor Deep IFREMER).
- `1013` deep cycle flag (unique of buffer `deep`), `1014` delayed flag, `1015` transmission-completed flag.

**store_tech1 (from the LAST Tech#1 in buffer if several — MATLAB warns+uses last):**
Deep cycle (a_deepCycle==1):
`100`=YYYYMMDD from items 7+2000/6/5 · `101`=item8 · `102`=hh:mm from item9/60 · `103`=item10 · `104`=item11 · `105`=item12 · `106`=hh:mm item13/60 · `107`=hh:mm item14/60 · `108`=hh:mm item15/60 · `109`=item16 · `110`=item17 · `111`=sprintf('%02d',item20) · `112`=item21 · `113`=item22 · `114`=item25 · `115`=item26 · `116`=hh:mm item27/60 · `117`=hh:mm item28/60 · `118`=item29 · `119`=item30 · `120`=item32 · `121`=item33 · `122`=item34 · `123`=item35 · `124`=hh:mm item38/60 · `125`=hh:mm item39/60 · `126`=item40 · `127`=item47 · `128`=item48*5 · `129`=15−item49/10 · `130`=RTC-status INVERTED (item50==0→1 else 0) · `131`=item51 · `1000`=item61 (GPS valid) · `132`=item62 · `133`=item64 · `134`=item65 · `135`=YYYYMMDDHHMMSS from items 72+2000/71/70/67/68/69 — ONLY if item66==1 · `136`=mm:ss from item73/3600 — ONLY if item61==1.
Non-deep: ONLY `204`… no — non-deep emits `10127`=item47, `10128`=item48*5, `10129`=15−item49/10, `10130`=RTC inverted, `10131`=item51, `11000`=item61, `10132`=item62, `10133`=item64, `10134`=item65, `10135`(EOL date, if item66 NONZERO — note ≠ deep gate) and `10136`(mm:ss, if item61==1) — i.e. indexes offset by +10000 and a reduced set.

**store_tech2 (from the LAST Tech#2 in buffer):**
Deep: `200`=item2 · `201`=item3 · `202`=item4 · `203`=item5 · `204`=item6 · `205`=item7 · `206`=item8 · `207`=item9 · `208`=item10 · `209`=item11 · `210`=item12 · `211`=item13 · `212`=sub-surface pressure (sensor_2_value on item15; temp item16/psal item17/1000 computed but only pres emitted) — ONLY if any(pres,temp,psal)≠0 · `213`=item20 · if item20>0: `214`=item22, `215`=hh:mm item23/60, `216`=item24, `217`=item25 · if item20>1: `218`=item27, `219`=hh:mm item28/60, `220`=item29, `221`=item30 · `222`=item31 · if item31>0: `223`=hh:mm item32/60, `224`=pres(item33), `225`=item34, `226`=item35 · `227`=item36 · `228`=item37 · `229`=item38 · `230`=item39 · `231`=item40 · `232`=item41 · `233`=item42 · `234`=item43 · `235`=item44*5 · `236`=YYYYMMDDHHMMSS items 51+2000/50/49/46/47/48 · `237`=item52 · `238`=item53 · `239`=item54 · `240`=item55 · `241`=item56 · `242`=item57 · `243`=item59 ICE-detection flag — ONLY if a type-7 packet was ever received AND CONFIG_IC00 ≠ 0.
Non-deep: `204`=item6, `211`=item13, then +10000 set: `10227`–`10233`=items36–42, `10236`=date, `10237`–`10242`=items52–57.

**Name lookup:** index → `TECHNICAL_PARAMETER_NAME` via `_techParamNames/` JSONs (load all, build dict on TECH_PARAM_DEC_ID). Units/scaling are already IN the name strings (e.g. `_volts`, `_inHg`, `_COUNT`, `_hex`).

### 8.3 NOT yet read (next investigation steps)
1. `decode_provor.m` — the orchestrator: WHERE store_tech1/tech2/misc are called in the cycle loop, what `a_deepCycle` is exactly (buffer deep flag), how `g_decArgo_cycleNum` maps to output cycle number (update_output_cycle_number_ir_sbd.m exists in the online set), whether hydraulic (type-6) packets emit ANY tech.nc params (no store_hydraulic_for_nc exists — likely NOT; confirm), and what indexes 1–19/1001–1029 appear from (store_received_packet_type_info_for_nc.m — packet counts; decode_prv_data may emit 1001–1008 etc.).
2. `create_nc_tech_file_3_1.m` — writer: variable order/dims/dtypes/attributes, row ordering (cycle order? index order within cycle?), value stringification (num2str formats), fill/blank padding, FORMAT_VERSION/HANDBOOK_VERSION values, DATE_CREATION.
3. `init_default_values.m` — g_decArgo_outputNcParamLabel init + defaults (e.g. `g_decArgo_7TypePacketReceivedCyNum` semantics), FORMAT_VERSION strings.
4. `get_nc_tech_parameters_json.m` — how label files map to output label array (may add TECH_AUX/META_ filters seen in create_nc_tech_file_3_1.m).

### 8.4 FileChecker status
Prior phases ran GDAC FileChecker (`ValidateSubmit.jar`, rule -r1324) producing `parity_fresh_nc3/_filechecker_results/*.filecheck`, but the jar is NOT in the workspace (was run via /tmp). For Phase 4A: ask the user to supply the jar or accept MATLAB-parity + layout-convention validation; classify FileChecker gap accordingly.

### 8.5 Expected dataset behavior
- 6990711: 7 cycles, no deep cycles expected (verify `ArvorCycle.deep` — if all False → all cycles emit the NON-deep (10xxx) parameter set + store_misc rows; NOTE this is the big firmware-dependent fork).
- 7902408: 13 cycles incl. c13 WITHOUT Tech#1/Tech#2 → those params absent for c13 (no fabrication); misc rows (1012–1015) still emitted (deep/delayed/completed flags exist from Phase 2); type-7/IC00 gating relevant (Param#2 present → check IC00 value).
- Both floats: multiple Tech#1/#2 duplicates in a buffer → keep LAST (MATLAB rule).

### 8.6 Repo conventions to reuse
`nc/technical.py` (APEX writer, Phase 6A.4) shows the house pattern: thin writer + `build_technical_records(...)` + `technical_records_for_cycle(...)` consuming engineering objects, emitting via `nc/admt.py::write_admt_dataset`. ARVOR should get e.g. `platforms/provor_ir_sbd/arvor_i_tech.py` (product model builder from `ArvorScienceResult`) + an ARVOR branch in a new `nc/technical_arvor.py` (or extend technical.py WITHOUT touching its APEX behavior). Keep writer free of SBD parsing.

## 9. Ordered next steps for the new chat

1. Read the three phase reports (`docs/phase_reports/ARVOR_I_PHASE*.md`) + this doc + `IMPLEMENTATION_PROGRESS.md` tail. Re-run bootstrap (§3), confirm 1887 tests pass.
2. Read §8.3 files (decode_provor.m, create_nc_tech_file_3_1.m, init_default_values.m, get_nc_tech_parameters_json.m, store_received_packet_type_info_for_nc.m) and grep `decode_provor_iridium_sbd.m` (vendored) for every `outputNcParamIndex` write site to close the emitter inventory.
3. Build the compact mapping table (`ArvorScienceResult source | Coriolis source | _tech.nc parameter | conversion | PROVEN/INFERRED/UNKNOWN`) — put it in the report AND as the docstring/table in the new module.
4. Implement: product model (per-cycle technical records with parameter index/name/value/cycle) → writer (10-variable ADMT layout via `nc/admt.py`). Unit-formatted values exactly as MATLAB (`num2str` semantics — check how create_nc_tech_file stringifies numbers; hh:mm/mm:ss/YYYYMMDD… formats already vendored).
5. Validate on 6990711 + 7902408: parameter names/order/count per cycle against the emission tables; values against raw packets (spot-check a cycle by hand from `fields`); cycle alignment; missing-packet behavior (7902408 c13); no fabricated values.
6. Full pytest + ruff check + ruff format (+ mypy only if already configured in pyproject — check, don't add). Prove Phases 1–3 unchanged (Phase-2/3 test files untouched and passing; only additive interface changes if any).
7. Write `docs/phase_reports/ARVOR_I_PHASE4A_TECH_2026-08-DD.md` (mapping table, validation, discrepancy classes FIXABLE/NOT FIXABLE/EXPECTED/DATA-COVERAGE/UNKNOWN, disagreement ledger, Phase-4B recommendation) + append `IMPLEMENTATION_PROGRESS.md` entry.
8. STOP. Do not start Phase 4B / `_Rtraj.nc`.

## 10. Pitfalls (known traps)

- `fields[0]` placeholder trap: `f[k]` == MATLAB item k, always.
- MATLAB `tabTechN(k+ID_OFFSET)`, ID_OFFSET=1 → item k (this confused §8 tables before; they are already corrected to item numbers).
- `/tmp` and pip installs don't persist; workspace does.
- Pre-launch mails: exclude via `MailInfo.pre_launch` (already implemented in Phase 3).
- 6990711 has NO Param#1 → no MC/TC config; `float_config.values` empty. 7902408 has Param#1 (MC09=12 etc.) and Param#2 (IC00 — check actual value before gating param 243).
- Tech#2 "columns vs items" trap for expected counts (§6) — for _tech.nc we pass raw items through (200–211 = items 2–13 raw), so the correction does NOT apply to the tech emission; keep both facts distinct in the report.
- Never modify: APF9 (`platforms/apex_argos/`), CTS4/221 legacy PROVOR modules, existing tests.
- Dates: "today" for the new chat = whatever the platform says; user timezone Asia/Calcutta (Hyderabad).
