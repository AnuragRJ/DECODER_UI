# MIGRATION BASELINE REPORT — PROVOR-Bio / CTS4 (decoder 301)
**Written:** 2026-09-10 (user timezone Asia/Calcutta)
**Purpose:** Establish the verified baseline of the migrated workspace for the continuation of the PROVOR-Bio / CTS4 / Iridium-SBD investigation. READ-ONLY baseline — no source code, metadata, or reference artifact was modified during this investigation (environment package installation only; recorded in §3).
**Active project:** NKE PROVOR-Bio / CTS4 Ir-SBD BGC floats — real-time Argo processing (R/BR mono-cycle profiles + `<WMO>_meta.nc` / `<WMO>_tech.nc` / `<WMO>_Rtraj.nc`). No D/BD processing or publication. APEX / ARVOR-I code = frozen reference implementations for generic architecture only.

---

## 1. Workspace migration — provenance and integrity

| Item | Value |
|---|---|
| Source | Google Drive file `1Tlkt-oqO6SYuTI9m8z6P47f3mx-dASUe` → `phase-6-1-7.8-migration.zip` |
| Size | 141,706,627 bytes (135 MiB), zip `compression method=store` |
| SHA256 | `0192aa3610156be9eac25b44b40ec4c9f980b8dcb13270f81bbd298fb69f6bcb` |
| `unzip -t` | No errors detected (all entries OK) |
| Extracted to | `/home/user/argo_workspace/` (147 MB, 6,915 files) + `/home/user/uploads/image-1.png` |
| Migration mechanism | Plain HTTP download + unzip. **No Git/GitHub workflow used or created**, per project rule. |

The Drive archive remains the authoritative recovery artifact (link + SHA256 above). Note: the extracted workspace (~147 MB) exceeds the sandbox's best-effort turn-snapshot cap (~128 MB); if any file ever appears missing in a future session, re-fetch from Drive and verify the SHA256 before anything else.

**PROVOR-Bio/CTS4 progress IS present in this workspace** (Phases 0, 1, 2A — code, tests, design notes, reports, raw telemetry, references). See §9 for the specific user-described items that are NOT in this snapshot.

## 2. Workspace map (top level, all preserved)

```
argo_workspace/
├─ argo-decoder-python/                  # THE decoder repo (src, tests, config, docs, scripts)
│   ├─ IMPLEMENTATION_PROGRESS.md        # append-only log, 13,821 lines, last entry (aq) 2026-09-09
│   ├─ src/argo_decoder/platforms/
│   │   ├─ provor_cts4_ir_sbd/           # ACTIVE family: framer, packets, cycles, ctd,
│   │   │                                #   params, tech, bgc, equations, assoc, labels_301
│   │   ├─ provor_ir_sbd/                # ARVOR-I (FROZEN, certified reference)
│   │   └─ apex_argos/                   # APEX (FROZEN reference)
│   ├─ config/metadata/                  # 4 FROZEN CSVs + provor_cts4_301_reference.csv (CTS4-dedicated)
│   ├─ config/metadata_backup/           # pre-ARVOR-I snapshot (5 rows) — headers identical to live
│   ├─ nc/                               # mono_profile / rtraj_arvor / technical_arvor / metadata_file
│   │                                    # (+ legacy multi_profile = APEX-era; NOT used by CTS4, no D/BD path)
│   ├─ scripts/                          # audits + probe_cts4_phase2a_gdac.py (CTS4 validator)
│   └─ docs/phase_reports/PROVOR_CTS4_PHASE2A_DECODE_2026-09-09.md
├─ provor_bio_irsbd/
│   ├─ raw_telemetry/SBD-BGC-raw/        # 517 .sbd files, 10 groups (+ original 7z bundle)
│   ├─ PROVOR_BIO_IRSBD_PHASE0_INVESTIGATION.md
│   ├─ PROVOR_CTS4_PHASE1_DESIGN_NOTE.md
│   ├─ PROVOR_CTS4_PHASE2A_DESIGN_NOTE.md   # authoritative Phase-2A state document
│   └─ ref/                              # NKE 5.8 manual PDF+TXT (sha256-VERIFIED OK),
│                                        # Argo User's Manual, cook_oxy.pdf, cook_bbp.pdf,
│                                        # gdac_incois_301/ (13 meta.nc + 1 tech.nc + D/BD 2902091)
├─ Coriolis-data-processing-chain-.../   # Coriolis reference (LOAD-BEARING name: conftest DEMO_ROOT)
│   └─ decArgo_soft/                     # 301 label tables ✓, betasw_ZHH2009.m ✓, calcoxy_* ✓,
│                                        # decode_sbd_file_cts4.m test tool ✓; core sub/ decode_* still ABSENT
├─ arvor_raw/, gdac_arvor_i_ref/, validation_*, final_*, parity_6990711_2026-09-09/,
│  filechecker results/                  # ARVOR-I/APEX evidence (frozen)
├─ ref2902224/, profan/, uploads/, apf9_docs/  # APEX-era references (frozen)
└─ MIGRATION_NEW_CHAT_PHASE4A.md         # previous migration precedent document
```

Evidence-integrity checks run this session: NKE 5.8 PDF+TXT `sha256sum -c` → **OK**; raw telemetry count → **517/517 .sbd**; `gdac_incois_301/` → 16 files present; four frozen CSV headers byte-identical to `metadata_backup/` (content differs only by pre-freeze ARVOR-I rows: 16 vs 6 lines — **schema freeze intact**).

## 3. Environment bootstrap (only intervention performed)

```bash
cd /home/user/argo_workspace/argo-decoder-python
pip3 install -q -e ".[dev,gsw]"     # exit 0
```

Installed: Python 3.13.14 · pytest 8.4.2 · netCDF4 1.7.4 · xarray/ pydantic 2.13.4 · gsw 3.6.23 · ruff 0.16.6 · mypy 2.3.1. **No workspace file was edited to make the environment runnable.**

## 4. Current CTS4 decoder state (source of truth: Phase-2A design note + code inspection)

**Family pin:** Coriolis decoder 301 = DAC_FORMAT_ID 5.8 = NKE PROVOR CTS4 (FLBB) / PROVOR_III / WMO_INST_TYPE 836, INCOIS DAC, Iridium SBD. Byte authority: **NKE 5.8 manual §7 (first-party)**, recovered via Wayback, hash-pinned in `provor_bio_irsbd/ref/`.

**Modules (`src/argo_decoder/platforms/provor_cts4_ir_sbd/`):**
- `framer.py` — 140-byte packet framing (untouched since Phase 1).
- `packets.py` — dispatch: type-0 measurement (subtypes 0=CTD, 3=O2/optode, 6=FLBB), 250 SENSOR_TECH, 251 SENSOR_PARAMS (0xFB never sent — synthetic tests only), 252 PRESSURE, 253 VECTOR_TECH, 254 TECH_PARAMS, 255 MISSION_PARAMS (NKE naming, proven inverted vs Phase-0 labels).
- `cycles.py` — per-packet-header cycle attribution (type-0 u16@2-3, 255/254@7-8, 253@11-12, 252@1-2, 250@2-3); CycleBasis UNANIMOUS/MULTI_CYCLE/NO_CYCLE_INFO/CONFLICT; MOMSN never read as cycle.
- `ctd.py` — records @10, `(P s16, T u16, S u16)`; P=s16/10 dbar, T=(u16−2000)/1000 °C, S=u16/1000 PSU (NKE §7.2.4.1-3; the "+33 second PSAL encoding" was an artifact — resolved at (ap)).
- `params.py` — 255 mission (PV/PM) + 254 tech params (PT0–27).
- `tech.py` — 253 vector tech (serial, cycle, GPS, battery, vacuum, rtc…), 252 pressure samples (27×5B), 251 sensor-param changes, 250 sensor halves (CTD/Optode/FLBB free zones, X∈{0,1,4}, 0xFF filler).
- `bgc.py` — O2 (10×12B) + FLBB (21×6B) record extraction, minutes-hours date semantics, SBD_EPOCH 2000-01-01.
- `assoc.py` — `group_meas` by (cycle, profile, phase), `is_padding_ctd/o2/flbb`, `nearest_ctd` BGC→CTD matching.
- `equations.py` — pure math, explicit coefficients, no defaults: Aanderaa-4330 DOXY chain (TPHASE→Phase_Pcorr→CalPhase→28-term foil→AirSat→Weiss Cstar→MOLAR×44.614→Scorr×Pcorr→÷rho), CHLA=(FLUO−DARK)·SCALE, BBP700=2π·khi·((BETA−DARK)·SCALE−BETASW700), `beta_sw` = Zhang-2009 transcription of Coriolis `betasw_ZHH2009.m`. `rho` is an EXPLICIT caller input (Phase-2B publication input — gsw/TEOS-10 not yet wired into the CTS4 path).
- `labels_301.py` — 301 config/tech label tables (82+64 names, verbatim from container CSVs) + coverage audit.

**Metadata:** four frozen CSVs untouched (0 CTS4 rows — EXPECTED per design note §8: the frozen backend has an exact-join contract CTS4 rows cannot honestly join). All CTS4 coefficients live in the dedicated `config/metadata/provor_cts4_301_reference.csv`: **1534 rows = 118 coefficients × 13 INCOIS 301 floats**, fully provenanced (scope, wmo, sensor_model, sensor_serial, parameter, coefficient, value, source_file, source_variable, interpretation); 88 family-generic vs 30 float-specific (PhaseCoef0/1, foil c0–20, T0–3, DARKs, per-unit SCALE_BBP) by numeric-constancy audit.

**WMO↔IMEI mapping: NOT performed (stop list, NOT FIXABLE from available evidence).** Serial corroborations recorded as Phase-2B leads (8/10 FLBB serials match GDAC floats; optode lead-u16 pattern hypothesis — supported, unproven). No output file may be named until an authoritative mapping exists.

**No CTS4 wiring exists in CLI/pipeline** (verified: zero CTS4 references in `cli/` and `pipeline/`) — library + tests only, per the Phase-2A stop list.

## 5. Current R/BR / meta / tech / Rtraj state

- **CTS4: none implemented.** Phase-2A stop list explicitly excluded NetCDF emission, R/BD publication, WMO assignment, CSV-schema changes, final publication decisions, broad refactor. This is the expected state of the snapshot.
- **Established (knowledge, not code):** the R/BR contract from Argo User's Manual 3.44 §2.6 (B excludes TEMP/PSAL/CNDC; PRES the only duplicated parameter; no PRES_ADJUSTED/PRES_QC/PROFILE_PRES_QC/PRES_ADJUSTED_ERROR in B; same N_PROF/order/levels; PARAMETER_DATA_MODE(N_PROF,N_PARAM) required; N_PARAM = max per pressure sample; PARAMETER/PARAMETER_SENSOR 64/128 chars; DATA_TYPE 32 chars) — captured at entry (aj). GDAC structural references: `incois_D2902091_001.nc` / `incois_BD2902091_001.nc` (D/BD, reference-only per project rule — INCOIS has no R/BR for these 2014 floats locally), `incois_2902091_tech.nc` (95 rows/cycle from cycle 1, no cycle 0), 13× meta.nc, and one GDAC Rtraj (2023-regen) which carries BGC (no BRtraj file).
- **Reference implementations (frozen, reusable architecture):** ARVOR-I `nc/mono_profile.py` (R/BR mono-cycle), `nc/rtraj_arvor.py`, `nc/technical_arvor.py`, `nc/metadata_file.py` + `platforms/provor_ir_sbd/arvor_i_{prof,rtraj,tech,meta}.py` — certified against INCOIS GDAC and FileChecker v3.0.5 (entries (q)–(z), (ac); 81/81 ACCEPTED at (z)). Target float layout: `<WMO>/<WMO>_{meta,tech,Rtraj}.nc + profiles/R|BR<WMO>_<XXX>.nc` — no per-cycle duplicate meta/tech.
- Legacy `nc/multi_profile.py` (APEX-era D-file lineage) remains in the codebase, unused by ARVOR-I and CTS4; no D/BD path exists for the active family.

## 6. Test state (run this session, post-migration)

| Suite | Result |
|---|---|
| CTS4 Phase-1 units | 30/30 pass |
| CTS4 Phase-2A units | 27/27 pass (incl. 3 reference-CSV integrity tests) |
| CTS4 Phase-1 telemetry (517-file corpus) | 23/23 pass |
| CTS4 Phase-2A telemetry | 16/16 pass |
| **Full suite (`pytest tests -q -n auto`)** | **2219 passed, 1 skipped** (pre-existing golden-tree skip), 80 s |

The recorded "2216 passed" (design note §11) vs today's 2219 is **fully accounted for**: the 3 reference-CSV integrity tests were added after that count line was written (27 = 24 + 3; per-file counts today match the documented inventory exactly). NOT a regression.

**Phase-2A GDAC validator re-run** (`scripts/probe_cts4_phase2a_gdac.py`, read-only): reproduces the recorded numbers exactly — CHLA max diff 1.192e-07 µg/L, BBP700 5.355e-09 m⁻¹, implied-βsw vs `beta_sw` 7.676e-10, DOXY clean-level residual max 0.515717 / mean 0.257091 / median 0.188100 µmol/kg, fitted signature gain 1.001708 / offset +0.207603 (indicative only, never applied). The migrated environment is bit-faithful to the validated state.

## 7. Quality gates — tool-version drift (classified, not fixed)

Baseline rule: no source changes during baseline investigation. The freshly installed tools are NEWER than those used in the previous session, and their verdicts differ cosmetically:

| Gate | Recorded state | Today (ruff 0.16.6 / mypy 2.3.1) | Classification |
|---|---|---|---|
| ruff check (CTS4 pkg) | clean at (aq) | 12 findings (I001/F401/RUF022/UP017/B905/RUF002 — import order, `__all__` sorting, `datetime.UTC`, `zip(strict=)`, ambiguous `×`) | TOOL-VERSION artifact; cosmetic; FIXABLE in a later bounded change |
| ruff format --check | clean at (aq) | 6 files would reformat (line-joining only) | TOOL-VERSION artifact; cosmetic |
| mypy --strict (CTS4 pkg) | 0 errors at (aq) | 32 errors: 28× `[no-untyped-call]` (all = the `u16 = lambda off: ...` idiom in `tech.py`/`params.py`) + 4× `[no-any-return]` in `equations.py` | TOOL-VERSION artifact (mypy 2.x strictness); no functional impact — all tests pass |
| mypy --strict (whole src) | 76 pre-existing | 107 (75 non-CTS4 + 32 CTS4) | same drift; pre-existing count consistent |
| pytest | 2216+1 | 2219+1 pass | no regression (see §6) |

Recommendation (for a later bounded task, not done now): either pin tool versions to the previous session's, or apply the mechanical fixes (ruff `--fix` + lambda→def) with the full test suite as the gate.

## 8. FileChecker state

- **Results preserved:** `filechecker results/` — 51 result files across 7 runs (v2.9.4-SNAPSHOT historical + v3.0.5 latest, ours vs INCOIS GDAC control) for ARVOR-I 6990711, with `SUMMARY.csv` index. Latest build: all ACCEPTED (only the known NVS PI_NAME warning on meta, also present in the GDAC control).
- **Tool availability:** the FileChecker binary is NOT installed in the migrated environment (classification: TOOL-AVAILABILITY; previously fetched from GitHub as an external reference tool — reinstall when CTS4 products exist to check).

## 9. Discrepancies between the task-brief's described CTS4 state and this snapshot

The task brief lists several items as "already established" that are **NOT present in this snapshot**. The snapshot is at the Phase-2A boundary (2026-09-09, "STOPPING — no Phase 2 without/after instruction" → Phase 2A completed same day per its report). If the previous chat continued past this point, that later work **did not make it into the zip**:

| Brief item | Snapshot state | Assessment |
|---|---|---|
| `is_padding_*`, `nearest_ctd` | present (`assoc.py`) | ✓ matches |
| Packet subtypes 0/3/6, packets 250/252/253/254/255, cycle attribution from headers | present (Phase 1 + 2A) | ✓ matches |
| CHLA / BBP700 / Aanderaa-4330 DOXY chains | present (`equations.py`, GDAC-validated) | ✓ matches |
| Float-specific calibration keyed by sensor serial / authoritative metadata | present (`provor_cts4_301_reference.csv`, 1534 provenanced rows) | ✓ matches |
| **"ExternalMeta architecture"** | **no `ExternalMeta` symbol/file anywhere in the workspace** | ABSENT — the external-metadata LAYER exists as the reference CSV, but no ExternalMeta module/class. Either user-side terminology for the CSV layer, or post-snapshot work. |
| **"Barnard original vs corrected BBP scale distinction"** | **zero occurrences of "Barnard"** | ABSENT — snapshot distinguishes telemetry `scale_bb` (packet 250, 10 distinct) from GDAC per-unit SCALE_BBP, but carries no Barnard adjudication. Post-snapshot finding or external knowledge. |
| **"real-time R/BR output semantics"** | contract knowledge captured at (aj); **no CTS4 R/BR writer** | semantics ✓, code ABSENT (stop-listed) |
| **"TEOS-10 density via gsw" as production path** | gsw used only in legacy `derived/cndc.py` / `derived/density.py` (APEX-era); `equations.py` takes explicit rho; design note defers gsw density to Phase-2B | partially — dependency installed, CTS4 wiring ABSENT (planned) |
| **CTS4 meta/tech/Rtraj/R-BR writers, FileChecker runs on CTS4 products** | none | ABSENT (stop-listed) |

Also: **`IMPLEMENTATION_PROGRESS.md` has NO Phase-2A entry** (last entry = (aq), Phase-1 NKE correction). Phase 2A is documented only in `docs/phase_reports/PROVOR_CTS4_PHASE2A_DECODE_2026-09-09.md` + the design note. This baseline report + the appended progress entry (ar) close that log gap without rewriting history.

**Nothing above was re-derived or "fixed" during this baseline.** The Phase-0/1/2A conclusions are treated as validated and preserved per project rules.

## 10. Known remaining gaps (carried forward, unchanged classifications)

- **WMO↔IMEI mapping:** NOT FIXABLE from available evidence — requires authoritative metadata (the four CSVs or equivalent); serial corroborations are leads only.
- **Phase-2B scope (per design note, awaiting instruction):** publication layer — R/BR mono-cycle profiles, meta/tech/Rtraj writers, gsw/TEOS-10 density for DOXY kg-conversion, ExternalMeta-style loader over the reference CSV, WMO resolution.
- **DOXY publication gap:** +0.21 µmol/L-style INCOIS adjustment — PUBLICATION-RTQC, explicitly unresolved, never fitted.
- **UNKNOWN:** FLAG_SensorBoardStatus(173) derivation rule; 253 rtc 0-vs-1 (GDAC publishes 1); 03530 cycle-9 stab latched 0; Optode lead-u16 = serial (supported hypothesis); PT26 (÷1000 strong hypothesis) / PT27 (magnitude matches GDAC coef2 ~442, mapping unproven).
- **EXPECTED:** 4-CSV non-population; 251 absent from corpus; TEMP_DOXY reference-only; SBE41CP coefficients unavailable anywhere authoritative; 252 absent from label tables.
- **TOOL-AVAILABILITY:** Coriolis core `soft/sub/` CTS4 decoders still missing (byte authority CLOSED by NKE manual); FileChecker binary not installed here.
- **Semantic conflict (manual errata watch, not a decoder issue):** PT12 raw = 2 vs NKE text.
- Calib conflicts on record (container-JSON vs meta.nc for 2902091: BBP scale 1.795e-6 vs 1.773e-6, khi 1.076 vs 1.097, angle 124° vs 142°) — recorded, NOT resolved by fiat.

## 11. Regression assessment of the migration

- **No functional regressions:** full suite 2219/1 skipped; CTS4 counts exact; Phase-2A validator bit-identical; evidence hashes verified; frozen CSV schemas intact; raw corpus complete (517/517).
- **Environmental (non-regressions, recorded):** newer ruff/mypy cosmetic verdicts (§7); FileChecker tool absent (§8); packages not persisted between sessions (bootstrap in §3 is the standard start).
- **Log gap:** Phase-2A entry missing from the append-only log — closed by entry (ar) of 2026-09-10.
- **Snapshot-boundary gap:** brief-described items ExternalMeta / Barnard-BBP / CTS4 publication code not in this snapshot (§9) — flagged to the user; NOT re-invented.

## 12. Exact next engineering stage

Per the Phase-2A report's stop boundary and the task brief: **baseline is now established; WAITING for the user's next task.** The natural continuation is **Phase 2B (publication layer)** — in evidence-first order: (1) resolve/obtain authoritative WMO↔IMEI mapping (blocking all file naming); (2) ExternalMeta-style loader over `provor_cts4_301_reference.csv` keyed by sensor serial; (3) gsw/TEOS-10 potential-density path for DOXY µmol/kg; (4) mono-cycle R/BR writer per UM 3.44 §2.6 + ARVOR-I architecture; (5) tech.nc (95-params/cycle per GDAC 2902091) + Rtraj (packet 253/252 evidence) + meta.nc writers; (6) FileChecker + GDAC-parity validation. Any Barnard/ExternalMeta material from the previous chat should be supplied by the user rather than re-derived.
