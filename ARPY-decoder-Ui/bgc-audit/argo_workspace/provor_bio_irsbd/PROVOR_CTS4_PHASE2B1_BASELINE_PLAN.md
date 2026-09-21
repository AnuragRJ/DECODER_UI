# PROVOR CTS4 (decoder 301 / format 5.8) — Phase 2B-1 BASELINE & PLAN

**Status:** BASELINE — READ-ONLY, no implementation  
**Date:** 2026-09-10 (Asia/Calcutta)  
**Workspace:** restored from `phase-6-1-7.8-migration.zip` → `/home/user/` (517 .sbd + refs + code + tests)  
**Rule:** This is a state migration from a corrupted chat. No GitHub workflow, no schema changes, no WMO hacks, no ARVOR-I/APEX edits. `IMPLEMENTATION_PROGRESS.md` remains append-only (no entry appended here).

---

## 1. Workspace inspection (required by prompt — do not assume)

**Top-level after restore (`/home/user/`):**

- `argo-decoder-python/` — Python decoder (src, tests, config, docs, scripts)
- `provor_bio_irsbd/` — CTS4 family work (raw_telemetry, ref, 3 design notes)
- `Coriolis-data-processing-chain-for-Argo-floats-container/` — MATLAB reference (read-only, 39 MB)
- `arvor_raw/`, `gdac_arvor_i_ref/`, `ref2902224/`, `final_*`, `validation_*`, `parity_6990711_2026-09-09/` — ARVOR-I/APEX frozen artefacts (preserved, not touched)
- `APF9_PARITY_STATE.md`, `IMPLEMENTATION_PROGRESS.md` (668 KB, 13 800+ lines), `handoff.md` etc.

**Workspace/tmp cleanliness:**  
- Migration zip removed from `/home/user/` after restore. `/tmp/unzip` removed. `/tmp/arena-workspace/baseline*.json` was `{"files":{}}` (empty snapshot) before restore — now populated by the zip. No generated `node_modules/.venv/dist/build` artefacts persisted. Raw telemetry, manuals, GDAC refs, reports and tests preserved per rule.

**Frozen metadata architecture — verified byte-identical to pre-migration:**

```
argo-decoder-python/config/metadata/meta.csv          — 15 WMO rows (APEX+ARVOR-I), 15-column join schema, unchanged
argo-decoder-python/config/metadata/sensor-info.csv   — same 15 rows, unchanged
argo-decoder-python/config/metadata/calib.csv         — same 15 rows (SBE-polynomial only), unchanged
argo-decoder-python/config/metadata/config_params.csv — same 15 rows, unchanged
```

Tests pin the exact 15-WMO join; any CTS4 row would be silently dropped — hence the dedicated reference CSV is required (see §4).

---

## 2. Phase-2A design / completion documentation (read)

- **Phase-0:** `provor_bio_irsbd/PROVOR_BIO_IRSBD_PHASE0_INVESTIGATION.md` — family identification (PROVOR CTS4 Ir-SBD BGC, decoder 301), 140-byte framing hypothesis, cycle attribution open problem, PSAL unknown.
- **Phase-1 baseline:** `provor_bio_irsbd/PROVOR_CTS4_PHASE1_DESIGN_NOTE.md` — cycle attribution solved (u16 BE header @2-3), PSAL gated, NKE 5.8 manual still TOOL-AVAILABILITY at that point, scope framer→dispatch→attribution→raw CTD.
- **Phase-1 implementation + NKE correction:** `IMPLEMENTATION_PROGRESS.md` entries (ak) 2026-09-09 (design baseline), (an) 2026-09-09 (42/42 → 53/53 after NKE correction (aq)), plus probes (ao)/(ap). Byte authority **CLOSED** via `NKE 5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924` §7 (PDF+TXT+SHA256SUMS in `provor_bio_irsbd/ref/`).
- **Phase-2A design note (authoritative for this baseline):** `provor_bio_irsbd/PROVOR_CTS4_PHASE2A_DESIGN_NOTE.md` — COMPLETE 2026-09-09. Scope: packets 250/252/253/254/255 per NKE 5.8, 301 label-table mapping, BGC raw extraction (O2 subtype 3, FLBB subtype 6), raw→calibrated equations (DOXY Stern-Volmer, CHLA, BBP700+Zhang2009 beta-sw), 301 label coverage, reverse-bootstrapped INCOIS evidence. STOP LIST: no NetCDF, no R/BD publication, no WMO assignment, no CSV schema change, no broad refactor.

**Phase-2A key contracts (still normative):**

- Authoritative CTS4 byte interpretation (NKE 5.8 §7): type-00 header `bytes 2–3 = cycle u16 BE`, `byte 4 = profile`, `byte 5 = phase`, records start at byte 10, order P/T/S, `P = s16/10 dbar`, `T = (u16-2000)/1000 °C`, `S = u16/1000 PSU`, MOMSN ≠ cycle key.
- Packet types: 255 mission, 254 PT tech, 253 vector tech, 252 pressure, 251 sensor params (absent from corpus), 250 sensor tech; BGC subtypes 3=O2, 6=FLBB, 0=CTD; 253 phases 0/1/12/16 (two-session scheme), type-0 phases 6/9.
- PSAL resolved as **single encoding `raw/1000`** (the earlier `+33` was FLBB chlorophyll counts mis-framed as S).
- GDAC publication behavior: INCOIS CTS4/Ir-SBD BGC refs 2902086–93, 2902113/14/15/18/20 (PROVOR_III, 836, 5.8, IRIDIUM, D/BD N_PROF=4 N_LEVELS=95, 11 BGC params) — see `provor_bio_irsbd/ref/gdac_incois_301/` (13 meta.nc + tech + D/BD).

**Unresolved items carried forward (do not silently convert to facts):**

- DOXY ~+0.21 µmol/kg publication offset → **PUBLICATION-RTQC** (clean residual max 0.5157, fitted gain 1.0017/offset +0.2076 on 2902091 c1; CHLA/BBP exact)
- PT26/PT27 semantics → **UNKNOWN** (PT26 ÷1000 hypothesis, PT27 ~442 coef2 hypothesis, unproven)
- `FLAG_SensorBoardStatus_NUMBER` derivation → **UNKNOWN** (no 253 wire field; presumably derived from 250 statuses)
- 253 rtc flag (wire 0 vs GDAC 1) → **UNKNOWN**
- 03530 cycle-9 stab latched 0 → **UNKNOWN**
- Optode lead-u16 = serial hypothesis → **supported but unproven** (double-match evidence, see §6)
- Any other Phase-2A report items

---

## 3. Dedicated CTS4 reference CSV — verified

**Path:** `argo-decoder-python/config/metadata/provor_cts4_301_reference.csv`  
**Schema (FROZEN, NEW file — not one of the four legacy CSVs):** `scope,wmo,sensor_model,sensor_serial,parameter,coefficient,value,source_file,source_variable,interpretation`  
**Rows:** 1534 = 118 coefficients × 13 INCOIS 301 floats (`2902086/87/88/89/90/91/92/93`, `2902113/14/15/18/20` — see `cut -d, -f2 | uniq -c`).  
**Provenance:** every row carries WMO + source `incois_*_meta.nc` + `PREDEPLOYMENT_CALIB_COEFFICIENT` + interpretation; generic vs float-specific flagged at write time; no WMO-keyed decoder logic.

**Numeric generic vs float-specific (float-aware, string-formatting-insensitive):**

- **88 family-generic distinct coefficients** (identical float value in all 13 floats): `Spreset, Pcoef2/3, B0-3, C0, A0-5, D0-3, PhaseCoef2/3=0`, all 56 `m/n` exponents, `c21-27=0`, `T4/5=0`, `SCALE_CHLA=0.0073`, `khi=1.097` etc. String-level variants (e.g. `2.98831e-06` vs `2.8228e-06` is genuinely specific; `1.839203e-03` vs `0.0018392` is same value — preserved verbatim, compared numerically).
- **30 float-specific distinct coefficients** (vary across floats): `DARK_BACKSCATTERING700, SCALE_BACKSCATTERING700, DARK_CHLA, PhaseCoef0/1, c0-20 (in ~4 foil batches), T0-3`. Values: DARK ∈ {48,49,50,51,52}, SCALE_BB ∈ {1.369,1.387,1.413,1.441,1.601}e-6 etc.

**Per-sensor serials in the CSV:**

- FLBB serials: `2658,2659,2660,2661,2662,2663,2664,2666,3042,3045,3046,3065,3066` (13 floats; CTD serial = `n/a` for all CTS4 — on-board conversion)
- OPTODE serials: `1294,1295,1329,1331` (only 4 of 13 floats expose it in GDAC meta; others `n/a` — hence the lead-u16 hypothesis)

**Why the four legacy CSVs were not changed (hard rule, still enforced):** `calib.csv` is SBE-polynomial-only and has no BGC columns; `config_params.csv` lacks the 301 inventory (64 PT + 82 PV/PM names); CTS4 CTD coefficients are `n/a` everywhere authoritative; the existing loader join test pins the exact 15-WMO list — partial CTS4 rows would be dead authority. The dedicated 301 reference CSV is the correct, provenance-carrying home (EXPECTED, not a gap).

---

## 4. Current CTS4 code / tests — verified

**Package:** `argo-decoder-python/src/argo_decoder/platforms/provor_cts4_ir_sbd/` (stdlib-only, ruff + mypy-strict clean for the package per (aq))

| module | responsibility | Phase |
|---|---|---|
| `framer.py` | 140-byte framing, size validation, blank-row drop (Coriolis all-0/all-26 rule) | 1 |
| `packets.py` | dispatch by byte0 (`00/FA/FC/FD/FE/FF`), subtype routing (0/3/6), rejects unknown | 1 |
| `cycles.py` | header-cycle attribution (u16 BE @2-3 for type-00, @7-8 for 255/254, @11-12 for 253, @1-2 for 252, @2-3 h1 for 250), unanimous file cycle / conflict handling, cycle-0 genuine, MOMSN never read | 1 (aq correction) |
| `ctd.py` | CTD record `@10 (P s16,T u16,S u16)>hHH`, `pres=s16/10`, `temp=(u16-2000)/1000`, `psal=u16/1000`, tail 4B | 1 (aq correction: start 12→10, P/T/S order) |
| `params.py` | `decode_255` MissionParams (PV/PM), `decode_254` TechParams (PT0-27) | 2A |
| `tech.py` | `decode_253` VectorTech (140 B), `decode_252` PressurePacket (27×5 B), `decode_251` SensorParams (absent from corpus, synthetic-only), `decode_250` SensorTechPacket (2×70 B halves, LE free zones: CTD 4×f32, FLBB serial+scale/dark, Optode raw) | 2A |
| `bgc.py` | `extract_o2` (10×(P,C1,C2,T)+10B tail), `extract_flbb` (21×(P,CHL,BB)+4B tail), scales `P=s16/10`, `C1/C2=u16/100`, `T=(u16-2000)/1000` | 2A |
| `equations.py` | Pure-math raw→calibrated: DOXY Stern-Volmer + CalPhase cubic + 28-term foil (c/m/n) + AirSat/Weiss/Garcia-Gordon/pressure correction → `DOXY=O2/rho` (rho caller-supplied), `CHLA=(FLUO-DARK)·SCALE`, `BBP700=2π·khi·((BETA-DARK)·SCALE − BETASW700)` via `beta_sw` (Zhang2009, depolarization 0.039). No defaults. `TEMP_DOXY` preserved reference-only. | 2A |
| `assoc.py` | `group_meas` by (cycle,profile,phase), `nearest_ctd` | 2A |
| `labels_301.py` | Verbatim `_config_param_name_301.csv` (82) + `_tech_param_name_301.csv` (64) coverage: 23 PT (19,20,23,24,25 unmapped), 8 PM, 23 PV, 51 253-fields | 2A |

**Reference probes:**

- `scripts/probe_cts4_phase2a_gdac.py` — recomputes BD/D from raw inputs vs `incois_D2902091_001.nc`/`BD*` (CHLA 1.19e-07 µg/L, BBP 5.35e-09 m-1 exact; DOXY PUBLICATION-RTQC residual documented; beta_sw independent confirmation 7.67e-10).

**Test baseline — re-validated 2026-09-10:**

```
pip install -e ".[dev,gsw]" (re-run per session, container has no persistence)
python -m pytest -q → 2219 passed, 1 skipped (pre-existing structural_parity), 8 warnings
```

Breakdown:

- `tests/unit/test_provor_cts4_phase1_units.py` — 30 unit (framer 5, dispatch 9, attribution 8 incl. MOMSN behavioral + cycle-0 genuine + multi/conflict, CTD 8 incl. start-10/order/T-2000/signed-P/no-+33)
- `tests/test_provor_cts4_phase1_telemetry.py` — 23 telemetry (RAW 5359, KEPT 5236, header-cycle 1:1 verbatim, file unanimity 514/517 + 3 opaque-only, 255==254 269/269, CTD 20475 recs, S [31076,36698] etc.)
- `tests/unit/test_provor_cts4_phase2a_units.py` — 27 unit (layouts, 2902091 GDAC vectors, 3 reference-CSV integrity)
- `tests/test_provor_cts4_phase2a_telemetry.py` — 16 integration (corpus census §6 + label coverage)
- `ARVOR-I / APEX` 0 regressions (`python -m pytest -q` without filter: other 999 unit tests pass; ruff clean; mypy-strict 0 errors in `provor_cts4_ir_sbd`).

Expected Phase-2A suite was 27+16=43; observed is 30+23+27+16=96 total CTS4 tests (Phase-1 had 30+23=53 after aq; Phase-2A added 27+16=43; total 96). The full-suite delta 2216→2219 is +3 from the aq correction (was 42→53). **Gates pass.**

**ARVOR-I / APEX work remains frozen** — no file in `provor_ir_sbd/` or `apex_argos/` modified since the migration (git status clean for those subpackages by inspection).

---

## 5. Raw telemetry — verified still exists

**Root:** `provor_bio_irsbd/raw_telemetry/SBD-BGC-raw/` (plus `SBD-BGC-raw-bundle.7z` preserved)  
**Files:** 517 `.sbd` (plus `bundle.7z` = 518 total) — every file size multiple of 140 (`420..1960`), no other first-byte values.  
**Packet census (Phase-1/2A pinned):** `00×4092, FA×256, FC×201, FD×270, FE×270, FF×270` → 5359 rows, 5236 KEPT after blank-row drop; measurement `3969` (CTD 975, O2 2001, FLBB 993); all spare/tail checks 100%.

**10 IMEI-suffix groups (NOT WMO) — suffix = directory name, MOMSN ≠ cycle:**

| suffix | files | cycles (header u16) | FLBB serial (telemetry, via 250 free LE) | Optode pattern (telemetry, via 250 free LE u16) | notes |
|---|---|---|---|---|---|
| 00530 | 72 | 0–18 (19 cycles) | 3042 | 0x0506 = 1286 | earliest (2014-02-17); daily→10-daily transition (PM/period 24→240 h mid-life) |
| 03530 | 58 | 0–14 | 3043 | 0x0508 = 1288 | PM2 0→1 flip mid-life |
| 03580 | 53 | 0–13 | 3044 | 0x050D = 1293 | |
| 06580 | 70 | 16–34 | 3046 | 0x050F = 1295 | double-match candidate (see §6) |
| 06640 | 36 | 0–7 | 3065 | 0x0531 = 1329 | double-match candidate |
| 12170 | 63 | 98–114 | 2663 | 0x0466 = 1126 | high cycles |
| 17960 | 36 | 44–53 | 2661 | 0x02CE = 718 | PM1=30 only group |
| 20000 | 36 | 45–54 | 2659 | 0x02C6 = 710 | |
| 25980 | 63 | 116–132 | 2658 | 0x017A = 378 | |
| 29030 | 30 | 43–51 | 2660 | 0x02C8 = 712 | smallest group |

File kinds: `[00]×243, [fd,fe,ff]×142, full [00,fa,fc,fd,fe,ff]×124, plus 8 oddballs (1 FF-only, 1 FE-only)`. All per-file header cycles unanimous (`514/517 +3 opaque-only`) — **the byte3 cycle-key hypothesis is superseded by the u16 header** (still documented for history).

---

## 6. Best 2–3 telemetry groups for Phase 2B-1 — selection (with evidence)

**Task:** Prove this is a **GENERIC family decoder**, not one that only works for reference floats. For each selected group, run the **SAME generic path** (no WMO branches): `raw SBD → framing/packet parsing → cycle/profile/phase → configuration/calibration resolution → CTD → DOXY → CHLA → BBP700`. Determine for each coefficient: family-generic vs float-specific, what telemetry reconstructs vs what genuinely requires external per-float metadata, via `provor_cts4_301_reference.csv` + decoded telemetry/configuration.

**Selection criteria applied (generic-decoder relevance, not cherry-picking):**

1. **Serial corroboration strength** (Phase-2A §9: 8 of 10 FLBB serials match GDAC; optode lead-u16 double-match is the strongest signal).
2. **Coverage of generic vs float-specific diversity** (generic PT0-25 / PV/PM heads vs float-specific DARKs/SCALEs / PhaseCoef / foil batches / PT26-27 pairs).
3. **Corpus diversity** (daily vs 10-daily period, cycle span, file count) to stress the generic attribution/config path.
4. **GDAC comparison feasibility** (a hypothesized GDAC counterpart must exist for BGC parity — but the hypothesis is explicitly marked unproven; no hard WMO assignment will be performed).

**Recommended 3 (in priority order; any 2 of these satisfy the task, 3 gives stronger generic proof):**

### A — `06580` (PRIMARY, strongest evidence)

- **Why strongest:** **Double-match** FLBB `3046` **and** optode pattern `0x050F = 1295` both equal GDAC `2902114` (the only group with simultaneous FLBB+optode match besides 06640; Phase-2A design note p.9). This makes it the best-supported case for the lead-u16-as-serial hypothesis **without** asserting it as fact.
- **Size/span:** 70 files, cycles 16–34 (19 cycles, no cycle-0 bench — complements the bench-heavy groups).
- **What it tests generically:** Header-cycle attribution across mid-life cycles (no cycle-0 crutch), FLBB dark/scale reconstruction from 250 free (float-specific but telemetry-present), vector-tech phase-1/12 alternating + pressure-spill logic, and the generic DOXY foil generic constants vs float-specific `PhaseCoef0/1 + c0-20` (needs external).

### B — `06640` (SECOND, equally strong double-match)

- **Why:** **Double-match** FLBB `3065` **and** optode `0x0531 = 1329` = GDAC `2902118` (second double-match). Small clean group (36 files, cycles 0–7) including **genuine bench cycles 0** (phase 0/16, 18 bench 253s corpus-wide) — tests the generic cycle-0 vs profile-0 distinction and the bench-shallow extremes (min_park 1) without WMO logic.
- **Complementary to A:** low cycles vs A’s mid cycles; tests the same generic path on a disjoint cycle band.

### C — `00530` (THIRD, config-diversity anchor)

- **Why:** **Single-match** FLBB `3042` = GDAC `2902115` (the most frequently hypothesized INCOIS deployment date 2014-02-17 = 00530 day-1, but explicitly **hypothesis-only**). Largest group (72 files, cycles 0–18) and the **only group that exercises the mission-period change** (daily `24 h` → `10-daily 240 h` mid-life) — a pure generic config test (PV section first-period change; PM1/PM2 heads are generic 0/1 with one `17960=30` exception). Also has the full `[00,fa,fc,fd,fe,ff]` file kind and both 253 phase-1/12 sessions.
- **Alternative candidate:** `12170` (FLBB `2663` = GDAC `2902086`, cycles 98–114, high-number stress) is an equally valid third if the team prefers cycle-range stress over config-change stress. **Recommendation is 00530** for config diversity; swapping in 12170 is a one-line change to the plan.

**Explicitly NOT selected (and why):** `03530/03580` (FLBB `3043/3044` have no GDAC counterpart among the 13 — weaker corroboration), `17960/20000/25980/29030` (single FLBB match, smaller/overlapping evidence, no double-match). They remain available for later expansion without changing the generic path.

**Selection is provisional and NOT a WMO assignment.** No output file will be named `2902114` etc.; comparison will be labeled **“SBD group 06580 hypothesis → GDAC 2902114”** with the hypothesis flagged as supported-but-unproven.

---

## 7. Phase 2B-1 plan — generic path, coefficient resolution, comparison

### 7.1 Approach (generic-only, frozen schemas untouched)

- **No WMO-specific conditionals.** Coefficient resolution will use either (a) **family-generic hard-coded constants** (the 88 numerically-identical values from the reference CSV) or (b) **per-packet/per-group decoded telemetry** (250 free zones, 255/254/253 fields) or (c) **generic lookup via telemetry-derived serial → dedicated CSV** (e.g. FLBB serial present in 250 → `provor_cts4_301_reference.csv` row selection by `sensor_serial`, never by `if wmo==2902114`). The four legacy CSV schemas are **not read or written** for CTS4 (they remain the APEX/ARVOR-I backend).
- **Research before coding (per scientific principle):** Argo User’s Manual, NKE 5.8 §7, Coriolis `betasw_ZHH2009.m` / `calcoxy_*` / `decode_sbd_file_cts4.m`, BGC cookbooks (O2 10.13155/39795, CHLA 10.13155/39468, BBP 10.13155/39459), real INCOIS GDAC products — citations in §5/§8.
- **GDAC is parity reference, not truth:** differences will be classified `FIXABLE / FIX CANDIDATE / DATA-COVERAGE / TOOL-AVAILABILITY / PUBLICATION-RTQC / EXPECTED / NOT FIXABLE / UNKNOWN`, never fitted away.

### 7.2 Per-group generic pipeline (identical for each selected group)

```
raw .sbd (SBD-BGC-raw/<suffix>/…/*.sbd)
  → framer.frame_file / frame_bytes  (140 B, blank-row drop, size-multiple check)
  → packets.dispatch_framed          (kind routing, subtype 0/3/6, cycle header extraction)
  → cycles.attribute_file / attribute_group (unanimous u16 header cycles, cycle 0 genuine, profile==0, phase∈{6,9} for meas)
  → params.decode_255 / decode_254   (MissionParams PV/PM + TechParams PT0-27; label mapping via labels_301 vs 301 CSVs)
  → tech.decode_253 / decode_252 / decode_250 (VectorTech 33B spare check, Pressure 27×5B, SensorTech 2×70B LE free zones)
  → ctd.extract_ctd / bgc.extract_o2 / extract_flbb (P/T/S scales, O2 10×12B, FLBB 21×3)
  → assoc.group_meas + nearest_ctd    (group by (cycle,profile,phase); pad-record handling)
  → equations.*                      (caller-supplied rho; no hidden defaults)
```

All parsers are **already implemented and tested** (Phase 1 + 2A). Phase 2B-1 will **wire** them into a per-cycle/per-group **calibration resolution** layer and a **comparison harness** — no new packet layouts, no new CSV columns.

### 7.3 Configuration / calibration resolution — what is generic vs what needs external metadata

**From telemetry alone (generic, no CSV needed):**

- **Cycle/profile/phase:** header u16 + type-00 byte 4/5 (fully generic, per-packet)
- **Configuration:** `255` PV (durations, eol_period 60, second_session_wait 10, 5×24 h except first period {24,120,240} + PM heads), `254` PT0-25 fleet-wide constant `[2700,15,60,2,30,400,2000,40000,30,2100,4,8,2,0,100,200,50,50,30,0,10,83,90,10,0,10]` — all generic; PT26/PT27 per-group pair is telemetry-present but semantic UNKNOWN (will be carried raw and flagged, not interpreted)
- **Vector-tech:** 253 fields (serial per group, vacuum/battery/GPS tracks, mission-relative days, pressure extremes with phase-12 latch) — generic layout, values per-group
- **Pressure (252):** cycle + 27 samples — generic
- **CTD subsurface offsets:** 250 CTD half `offset_p, p_sub, t_sub, s_sub` — present but **not needed** for CTD primary (on-board conversion); carried for ledger

**From telemetry but float-specific (generic path reconstructs per-float values without WMO branches):**

- **FLBB dark/scale:** `250` FLBB half → `FlbbFree{serial, scale_chl, dark_chl, scale_bb, dark_bb, scale_chl_2}` — per-group constant (1:1 mapping §5). `scale_chl = 0.0073` generic (exact), `scale_bb` / `dark_chl` / `dark_bb` are **float-specific but reconstructable** from the packet. This is the **existence proof** that a generic decoder can resolve per-float BGC coefficients without a WMO table.
- **Optode lead-u16:** `OptodeFree.raw[0:2]` LE pattern per group (supported-as-serial, unproven) — will be carried as **telemetry-derived identifier**, not as a serial claim; lookup into the dedicated CSV will be by `sensor_serial` **only where the hypothesis is tested**, with provenance and with a fallback that treats it as opaque.

**Genuinely requiring external per-float metadata (DATA-COVERAGE / TOOL-AVAILABILITY, not a decoder bug):**

- **DOXY foil + temperature coefficients:** `PhaseCoef0/1, c0-20 (≈4 foil batches), T0-3` — **NOT present in any 250 free zone** (optode free is `u16+48 zeros`). 88 of the 118 DOXY coefficients are family-generic (hard-codeable), but these 30 are float-specific and must come from external per-float metadata (`provor_cts4_301_reference.csv` or a future float-specific CSV). The dedicated reference CSV **is** that external source, and the generic path will resolve it by **telemetry-derived FLBB serial → CSV** (never by IMEI suffix) where available, with explicit provenance.
- **SBE41CP CTD coefficients:** `n/a` in all authoritative sources (GDAC lists CTD serial as `n/a`); on-board conversion makes them moot — **EXPECTED** empty.
- **WMO ↔ IMEI linkage:** redacted filenames, no IMEI in GDAC, container IMEI=PTT stub — **NOT FIXABLE** from available evidence; output naming remains blocked.

**Resolution rule for Phase 2B-1:**

| coefficient | scope | source | generic path |
|---|---|---|---|
| CTD `P/T/S` scales | family-generic | NKE 5.8 §7.2.4.2-3 | hard-coded arithmetic (`s16/10`, `(u16-2000)/1000`, `u16/1000`) |
| `A0-5, B0-3, C0, D0-3, Pcoef2/3, Spreset, T4/5=0, m/n exponents, c21-27=0` | family-generic | 13/13 meta.nc identical | hard-coded constants (88 values) |
| `SCALE_CHLA=0.0073, khi=1.097` | family-generic | same | hard-coded |
| `DARK_CHLA, DARK_BB, SCALE_BB` | float-specific **but telemetry-present** | `250` FLBB half free LE | **reconstruct from packet** (no CSV lookup) |
| `PhaseCoef0/1, c0-20 batches, T0-3` | float-specific **telemetry-absent** | `provor_cts4_301_reference.csv` (13 meta.nc provenance) | **generic serial→CSV lookup** (or explicit “requires external” ledger entry) |
| `PT26/PT27` | per-group telemetry-present, semantic unknown | `254` wire u16 | carry raw, flag UNKNOWN |
| `FLAG_SensorBoardStatus` | derived-only | no 253 wire field | flag UNKNOWN |

### 7.4 Scientific comparison (internal vs INCOIS GDAC)

For each selected group (starting with `06580`, then `06640`, then `00530`):

1. **CTD:** `PRES/TEMP/PSAL` arrays per (cycle,profile,phase) — expect bit-exact `psal==s_raw/1000` etc. already pinned by Phase-1 telemetry tests; comparison vs `incois_D*_001.nc` / `BD*` PRES/TEMP/PSAL will be exact within the NKE scales (any `+33` artifact is already dead).
2. **CHLA:** `CHLA = (FLUO − DARK_CHLA)·SCALE_CHLA` — internal uses **telemetry DARK_CHLA** vs GDAC’s meta.nc DARK; expect exact (probe on 2902091: max 1.19e-07 µg/L) when the same DARK is used; when telemetry DARK is used, any delta is a **float-specific coefficient reconstruction test**, not a fudge.
3. **BBP700:** `BBP700 = 2π·khi·((BETA − DARK_BB)·SCALE_BB − BETASW700)` with `BETASW700 = beta_sw(T,S,λ=700,θ)` — same exactness expectation (probe: 5.35e-09 m-1) plus independent `beta_sw` check (7.67e-10).
4. **DOXY:** full Stern-Volmer chain with explicit `rho` (potential density via TEOS-10/gsw, same as probe) — expect the **documented PUBLICATION-RTQC residual** (~+0.21 µmol/kg mean, gain ~1.0017) to reproduce on the selected floats if the float-specific foil batch is resolved correctly; do **not** fit it away. Report per-level residual stats, clean vs garbage (L63-65) structure, and classification.
5. **Association / pressure chain:** `group_meas` census `618 groups / 248 with CTD` will be re-pinned per group; 252 pressure packet not linked to labels (expected).

**Comparison artefacts (read-only, in `/tmp` then summarized in a report):** fetch INCOIS GDAC `D*.nc`/`BD*.nc`/`meta.nc` for the hypothesized WMOs (`2902114/118/115`) via `https://data-argo.ifremer.fr/dac/incois/<WMO>/` (official route), inspect locally under `/tmp/gdac_phase2b1/`, never copy into the workspace. Comparison harness will be `scripts/probe_cts4_phase2b1_gdac.py` (new, additive — no existing file edited).

**Mismatch handling:** every delta gets a class (`PUBLICATION-RTQC` for the DOXY offset, `EXPECTED` for absent `251`/SBE coeffs/TEMP_DOXY, `UNKNOWN` for PT26/27/rtc/FLAG, `DATA-COVERAGE` for any file-count hole). No NetCDF emission in this phase (stop list).

### 7.5 Deliverables for Phase 2B-1 (when implementation starts)

- `src/argo_decoder/platforms/provor_cts4_ir_sbd/resolve.py` (new, thin): `resolve_calibration(cycle, group_flbb_serial, optode_pattern, csv_path)` — generic serial→CSV lookup, family-generic fallbacks, telemetry-derived FLBB dark/scale path; no WMO literals.
- `scripts/probe_cts4_phase2b1_gdac.py` (new): per-group `CTD/CHLA/BBP700/DOXY` recomputation + INCOIS GDAC comparison + residual classification.
- `tests/test_provor_cts4_phase2b1_telemetry.py` (new): 2–3 groups × (framing/dispatch/attribution → calibration resolution → CTD → DOXY/CHLA/BBP generic vs float-specific ledger) — pinned, no WMO branches.
- `provor_bio_irsbd/PROVOR_CTS4_PHASE2B1_REPORT.md` (new): per-group tables (family-generic vs float-specific, telemetry-reconstructable vs external-required, GDAC delta classification).
- No change to `config/metadata/{meta,sensor-info,calib,config_params}.csv`, no change to `ARVOR-I`/`APEX` code, no NetCDF emission, no WMO assignment.

### 7.6 Risks & explicit non-goals (still blocked)

- **WMO assignment** stays blocked (no authoritative WMO↔IMEI link) — comparison uses hypothesis labels only.
- **NetCDF R/BD/BR generation, publication decisions, WMO file naming, broad decoder refactor** — explicitly **DO NOT DO** (prompt stop list).
- **SBE41CP calibration, PPOX, NITRATE/PH** — no INCOIS BGC beyond the 11-param D/BD set; `TEMP_DOXY` reference-only.
- **PT26/PT27, rtc, FLAG_SensorBoardStatus, 03530 stab 0** — remain UNKNOWN; carried raw, never fabricated.

### 7.7 Entry criteria (gates — must stay green)

- `frame_bytes` / `dispatch_framed` / `attribute_file` / `extract_ctd|o2|flbb` / `equations.*` unchanged and tested (53/53 Phase-1 + 43/43 Phase-2A).
- `pytest -q` 2219 passed / 1 skipped before any 2B-1 edit (re-verified 2026-09-10 above).
- `ruff check` / `ruff format --check` / `mypy --strict` clean for `provor_cts4_ir_sbd` (package-level).
- `provor_bio_irsbd/ref/` byte authority present (NKE PDF SHA256 `1200319…9931c63`), GDAC `dac/incois/2902086–93/2902113…` reachable.

---

## 8. Provenance appendix (evidence locations, not assumptions)

- **Raw:** `provor_bio_irsbd/raw_telemetry/SBD-BGC-raw/{00530,…,29030}/*.sbd` (517 files) + `SBD-BGC-raw-bundle.7z` (original archive).
- **Byte authority:** `provor_bio_irsbd/ref/NKE_5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924.pdf` (§7 pp46-61) + `.txt` + `SHA256SUMS`.
- **Coriolis references:** `Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_soft/` (`decode_sbd_file_cts4.m` framing, `init_float_config_*`, `betasw_ZHH2009.m`, `calcoxy_*` not needed) + `decArgo_soft/config/_config_param_name_301.csv` / `_tech_param_name_301.csv`.
- **Cookbooks:** `provor_bio_irsbd/ref/cook_{oxy,bbp}.pdf`, `argo_user_manual.pdf` (UM 3.44 10.13155/29825).
- **GDAC references:** `provor_bio_irsbd/ref/gdac_incois_301/` (13 `incois_*_meta.nc`, `incois_2902091_tech.nc`, `incois_{D,BD}2902091_001.nc`) + live `https://data-argo.ifremer.fr/dac/incois/<WMO>/`.
- **Implementation:** `argo-decoder-python/src/argo_decoder/platforms/provor_cts4_ir_sbd/{framer,packets,cycles,ctd,params,tech,bgc,equations,assoc,labels_301}.py`.
- **Tests:** `tests/unit/test_provor_cts4_phase1_units.py` (30), `tests/test_provor_cts4_phase1_telemetry.py` (23), `tests/unit/test_provor_cts4_phase2a_units.py` (27), `tests/test_provor_cts4_phase2a_telemetry.py` (16).
- **Progress:** `argo-decoder-python/IMPLEMENTATION_PROGRESS.md` append-only (entries aj: Phase-0, ak: decoder-301 baseline, an: Phase-1 implemented, aq: NKE correction, Phase-2A complete).
- **This plan:** `provor_bio_irsbd/PROVOR_CTS4_PHASE2B1_BASELINE_PLAN.md`.

---

## 9. Next step

**Baseline established; implementation on HOLD** per prompt (“Do not start implementation until that baseline is established”).

**Awaiting user confirm on the 3-group selection:**

- **Recommended:** `06580` (1295 double-match) + `06640` (1329 double-match) + `00530` (3042 single-match + config-change diversity)
- **Alternative 3rd:** `12170` (2663, cycles 98–114 high-span) if cycle-range stress is preferred over config-change stress

On confirm, Phase 2B-1 will implement §7.5 (resolve + probe + tests + report) under the frozen-schema / no-WMO-branch / no-NetCDF constraints and append the Phase 2B-1 entry to `IMPLEMENTATION_PROGRESS.md`.

