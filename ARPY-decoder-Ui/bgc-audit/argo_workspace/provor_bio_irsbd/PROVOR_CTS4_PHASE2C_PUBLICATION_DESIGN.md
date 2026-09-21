# PROVOR CTS4 301 — Phase 2C PUBLICATION / NETCDF DESIGN ONLY

> **Status:** DESIGN ONLY — Research-first.
> **Date:** 2026-09-10 (Asia/Calcutta, UTC 2026-09-10).
> **Phase:** Phase 2B-1 provisionally accepted, Phase 2B-2 ARCH CLEANUP frozen (88-family-generic, 150/150 CTS4 pass, 4-layer proof 99999 synthetic). **No NetCDF writer, no R/BD publish, no WMO assignment, no legacy CSV change has been implemented.**
> Hard rules carried forward: no GitHub workflow / public Git-LFS only-by-reference, ARVOR-I/APEX frozen, four CSVs `config/metadata/{meta.csv,sensor-info.csv,calib.csv,config_params.csv}` permanently frozen (new dedicated CTS4 CSV allowed), no WMO-specific decoder logic, no cycle hacks, no fabricated metadata/WMO/calibration, IMPLEMENTATION_PROGRESS.md append-only, follow official Argo standards → NKE/reference spec → Coriolis/reference impl → raw telemetry → INCOIS GDAC (parity reference, not automatic truth).

---

## 0. Conventions — how to read this document

| Tag | Meaning |
|-----|---------|
| **MUST** | Required for GDAC/FileChecker structural pass. Violations → FileChecker ERROR. |
| **SHOULD** | Required for INCOIS parity / BGC cookbook compliance. Violations → FileChecker WARNING or science degradation. |
| **REFERENCE** | INCOIS-family observed behaviour. Matches `ref/gdac_incois_301/*.nc` as inspected via `netCDF4` (this phase). Not imposed as spec where it diverges from official Argo spec — classified explicitly. |
| **OPTIONAL** | Argo-official but not published by INCOIS for this fleet in observed products (e.g. S-files, Rtraj). Writer supports it, not required for parity. |

> Classification of mismatches used throughout: `FIXABLE` / `FIX CANDIDATE` / `DATA-COVERAGE` / `TOOL-AVAILABILITY` / `PUBLICATION-RTQC` / `PUBLICATION-REPROCESSED` / `EXPECTED` / `NOT FIXABLE` / `UNKNOWN` (per Phase 2B doctrine). A GDAC value is never taken as automatic truth without provenance (see §13).

---

## 0.1 Research-first — sources consulted (before design)

**Date in UTC 2026-09-10.** Design inferred from no single file; contract is union of:

| Source | Citation / Path | What was extracted |
|--------|-----------------|--------------------|
| Argo User's Manual v3.44 2025-07-10 | `doi:10.13155/29825` — fetched via `argodatamgt.org/Documentation` + `archimer.ifremer.fr/doc/00187/29825/120885.pdf`, cached `ref/argo_user_manual.pdf` | Ch.4 file naming, Ch.2.2/2.3/2.4/2.5/2.6 formats, dimensions, HISTORY spec, global attributes, N_PROF/N_LEVELS, PARAMETER_DATA_MODE, QC/ADJUSTED convention, pressure-axis handling |
| BGC cookbooks | `doi:10.13155/39795` Oxy v2.3.4 (2025-04-22), `cook_oxy.pdf` 3.9 MB; `cook_bbp.pdf` — BBP (Schmechtig et al. v1.4 2018); `doi:10.13155/39468` Chla; `doi:10.13155/55637` S-files | DOXY, CHLA, BBP equations, units, coefficient names, NPQ/ BETASW references, S-file semantics |
| NKE Provor CTS4 byte authority | `ref/NKE_5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924.pdf` + `.txt` (Archimer 00618/73031, 00662/77389, 00658/77029, remOcean 5.3&5.301) | Packet 250 sub-packet layout, FLBB dark/scale fields, CTD packing; not a publication spec (used only for N_LEVELS derivation) |
| Coriolis chain (reference impl) | `euroargodev/Coriolis-data-processing-chain-for-Argo-floats-container` decArgo `20260202_082q` — `decArgo_doc/decoder_user_manual/argo_coriolis_matlab_decoder_V1.10_20251112.pdf`, `config/_configParamNames/_config_param_name_301.csv`, `_techParamNames/_tech_param_name_301.csv`, demo `6903014`, `2902091_meta.json` | Family vs float-specific split, CONFIG/TECH param inventories, HISTORY_SOFTWARE=CO* (CODA/COQC/COPQ) pattern |
| LFS reference bundle | `https://drive.google.com/file/d/1C4Cl_AUH17_KMXS_5Cyk-VtKnSC7ey1f` (searched per instruction) | APEX-only, **TOOL-AVAILABILITY: no CTS4 map** — not used to infer 301 contract |
| INCOIS GDAC parity reference | `ref/gdac_incois_301/incois_2902*_meta.nc` (13 files), `incois_2902091_tech.nc`, `incois_D2902091_001.nc`, `incois_BD2902091_001.nc` — **inspected via netCDF4 in this phase (see §1.x raw dumps)** | All §1-17 quantities below. Cited as REFERENCE, not MUST where they are GDAC/Incois-family artifacts |

> Raw dumps stored only as inspected logs (not as new NetCDF). 13 meta dims inspected, D/BD/Tech dims/vars inspected, STATION_PARAMETERS/PARAMETER/PARAMETER_DATA_MODE/DATA_MODE inspected. Single-cycle example cannot exhaust multi-cycle trajectory behaviour — noted as **DATA-COVERAGE**.

---

## 1. Publication contract — file types (item 1-2)

### 1.1 What INCOIS actually publishes (observed, REFERENCE)

Under `ref/gdac_incois_301/` the INCOIS DAC surfaces for decoder 301:

| Observed file | Count | Example name (this dataset) | Exists on INCOIS GDAC? |
|---------------|-------|------------------------------|------------------------|
| **Meta** | 13 | `incois_2902086_meta.nc` … `2902120_meta.nc` | Yes — one per WMO |
| **Tech** | 1 | `incois_2902091_tech.nc` | Yes — one per WMO (accumulates) |
| **Core profile (multi-profile, cycle-bundled)** | 1 | `incois_D2902091_001.nc` (`D` = delayed) | Yes — core CTD |
| **BGC profile (B-prefix)** | 1 | `incois_BD2902091_001.nc` (`BD` = BGC delayed) | Yes — BGC split — see §5 |
| **Synthetic S-file** | 0 | `SD…` / `SR…` not present | Not observed for this fleet (see §5.2) |
| **Trajectory** | 0 in local mirror | `_Rtraj.nc` / `_Dtraj.nc` not present in this mirror | **UNKNOWN/DATA-COVERAGE** — Argo spec allows it; local mirror is cycle-001 only; design MUST support it as OPTIONAL, not fail if absent |

### 1.2 What the Argo official hierarchy requires (MUST)

Per User's Man. §5.1-5.2 and GDAC Checks `doi:10.13155/46120`:

- **Core single-cycle:** `<R/D><WMO>_<XXX>[D].nc` — core params only.
- **BGC single-cycle:** `B<R/D><WMO>_<XXX>[D].nc` — BGC params (historic naming) — modern equivalent **S-file** `S<R/D><WMO>_<XXX>[D].nc` (merged core+BGC) is RECOMMENDED, not required. INCOIS family uses **split files** (`D` + `BD`) — this is **REFERENCE / SHOULD** for parity, **OPTIONAL** for S.
- **Meta:** `<WMO>_meta.nc`
- **Tech:** `<WMO>_tech.nc`
- **Trajectory (if generated):** `<WMO>_<R/D>traj.nc` — core+BGC traj (see §12). May have `B<R/D>traj` legacy split, now merged.

### 1.3 Decision table for eventual writer

| Product | Writer output | Naming rule | Mode source |
|---------|---------------|-------------|-------------|
| Core | `<R/D><WMO>_<NNN>.nc` + `<R/D><WMO>_<NNN>D.nc` if descending exists | `MUST` §5.1.1 | `DATA_MODE(N_PROF=1)` for prefix |
| BGC (B-file) | `B<R/D><WMO>_<NNN>.nc` (+ `D`) | `REFERENCE` for INCOIS parity; `SHOULD` if BGC sensors present | **BGC prefix = `D` iff any `DATA_MODE(N_PROF) == 'D'` in that file, else `R`** (semantic; not lexical `max()`). Source: Argo User's Manual §5.1 File Naming + §5.1.2 Note on `R/D` — core-files follow `DATA_MODE(1)`; B-files & merged GDAC files change to `D` when *any* `DATA_MODE(N_PROF)` is `D` (CORRECTION-2). |
| Synthetic S-file | `S<R/D><WMO>_<NNN>.nc` | `OPTIONAL` — generate only when `GENERATE_SYNTHETIC=true` config; not needed for parity in this dataset | Same as B-file |
| Meta | `<WMO>_meta.nc` | `MUST` | N/A (cycle-agnostic) |
| Tech | `<WMO>_tech.nc` | `MUST` | Accumulates, always `R` until DMQC |
| Traj | `<WMO>_<R/D>traj.nc` | `OPTIONAL` — not observed, but writer architecture SHALL support it; gated by `GENERATE_TRAJ` | Trajectory DATA_MODE |

> **R vs D guards (CORRECTION-2):** Writer MUST NOT decide R/D from input file name and **MUST NOT use lexical/string `max(DATA_MODE)`**. It MUST derive `DATA_MODE` per §6 from QC/DM state and `PARAMETER_DATA_MODE`. Selection rule per Argo User's Manual §5.1 + §5.1.2 Note on `R/D` (doi:10.13155/29825): **Core-file prefix follows `DATA_MODE(N_PROF=1)`** (primary CTD profile; `D` only when N_PROF=1 is `D`, so `D R R R` → `D`-prefix, `R R R R` → `R`-prefix); **B-file/merged prefix is `D` iff `∃ N_PROF: DATA_MODE(N_PROF)=='D'`, else `R`** (semantic existential, not `max()`). For cycle 001 example, D-file `DATA_MODE=[D,R,R,R]` → prefix `D` (by N_PROF=1); BD-file `DATA_MODE=[R,R,D,A]` → prefix `D` (by existence of `D` at N_PROF=3). `A` (adjusted) does **not** trigger `D`.

---

## 2. N_PROF / N_LEVELS structure (item 3)

### 2.1 Observed (REFERENCE — from netCDF4 inspection, 2026-09-10)

```
Meta:  N_PARAM=11, N_SENSOR=6, N_CONFIG=18 (else 17), N_LAUNCH_CONFIG=161, N_MISSIONS=3-7 UNL
D:     N_PROF=4, N_PARAM=3, N_LEVELS=95, N_HISTORY=5, N_CALIB=1
BD:    N_PROF=4, N_PARAM=6, N_LEVELS=95, N_HISTORY=8, N_CALIB=2
Tech:  N_TECH_PARAM=1288 (for 2902091)
```

**N_LEVELS = 95** in observed cycle 001 — the maximum bin count for that **output file**, not a fixed global. CTS4 stacks PSEN/PT plus BGC samples into **one file-level `N_LEVELS` dimension = `max(len(PRES_i))` across all `N_PROF` in that file** (Argo User's Man §2.2.2/§2.6 `N_LEVELS` is per-file, not per-profile). Shorter profiles are masked with `_FillValue=99999.0` to that file-level length.

**N_PROF = 4** — observed decomposition:

| N_PROF index (1-based in NetCDF) | D content (STATION_PARAMETERS) | BD content (STATION_PARAMETERS) | Interpretation (per `VERTICAL_SAMPLING_SCHEME`) |
|----------------------------------|-------------------------------|---------------------------------|------------------------------------------------|
| 1 | `PRES/TEMP/PSAL` | `PRES` only | Primary CTD ascending (or descending) — descending flagged via `DIRECTION` and file suffix `D` |
| 2 | `PRES/TEMP/PSAL` | `PRES` only | Second CTD (paired cycle — INCOIS cycles carry 2 CTD segments in same file) |
| 3 | `PRES` only | `PRES/C1PHASE/C2PHASE/TEMP_DOXY/DOXY` | BGC oxygen split — secondary sampling (DOXY) |
| 4 | `PRES` only | `PRES/FLUORESCENCE_CHLA/BETA_BACKSCATTERING700/CHLA/CHLA_FLUORESCENCE/BBP700` | BGC FLBB split — secondary sampling (Chla/BBP) |

> **Generic rule (MUST per Argo §2.6.1):** PRES axis is mandatory but STATION_PARAMETERS within a BGC file carry ONLY the params measured at that sampling resolution. Core CTD appears split into the D-file (3 params) while BD-file repeats PRES on every N_PROF to anchor BGC samples. A profile where STATION_PARAMETERS = `PRES` only carries a PRES vector with no colocated TEMP/PSAL/BGC.

**UNLIMITED dimensions per spec/evidence**: `N_CONFIG` and `N_MISSIONS` (`UNLIMITED` in meta, 18/17 and 3-7) and `N_TECH_PARAM` in tech (`UNLIMITED` per User's Man §2.5.2 p65 and GDAC `1288 unlimited`) and `N_HISTORY` in profiles (5/8 `UNLIMITED`) are `UNLIMITED`; writer MUST write them as `UNLIMITED` exactly as spec mandates. **`N_LEVELS`, `N_PARAM`, `N_PROF`, `N_CALIB` are fixed per file** — writer MUST NOT make them unlimited (see CORRECTION-2/8).

### 2.2 MUST vs REFERENCE

| Item | Normative |
|------|-----------|
| N_PROF = number of distinct vertical sampling legs in the cycle (1..N) | MUST (§2.6.1) |
| N_LEVELS = **file-level** `max(len(PRES_i))` across all `N_PROF` **in that output file** (core file vs BGC file each compute their own `N_LEVELS`; not a per-profile dimension) | MUST (User's Man §2.2.2/§2.6; INCOIS D & BD both 95 for cycle 001 confirms file-level, not 95 global) |
| N_LEVELS=95 for all future cycles/files | REFERENCE — typical for 301 at 2 dbar near-surface + coarser deeper, but MUST be derived per file |
| N_HISTORY = 5 (D) / 8 (BD) | REFERENCE — writer grows N_HISTORY as actions accumulate |

---

## 3. Parameter inventory and N_PARAM ordering (item 4)

### 3.1 INCOIS observed ordering (REFERENCE — extracted via `chartostring`)

**Meta `PARAMETER` (N_PARAM=11) — stable across 5 inspected metas:**

```
 0  PRES
 1  TEMP
 2  PSAL
 3  C1PHASE_DOXY          (intermediate)
 4  C2PHASE_DOXY          (intermediate)
 5  TEMP_DOXY             (intermediate)
 6  DOXY
 7  FLUORESCENCE_CHLA     (intermediate / raw count)
 8  BETA_BACKSCATTERING700 (intermediate / raw count)
 9  CHLA
10  BBP700
```

*INCOIS meta maps N_SENSOR=6 to these params via `PARAMETER_SENSOR`.*

**D-file `PARAMETER` (N_PARAM=3, N_CALIB=1):**
```
 PRES, TEMP, PSAL   (all calib 0)
```

**BD-file `STATION_PARAMETERS` (N_PARAM=6 — but per N_PROF sparse):**

| N_PROF | STATION_PARAMETERS (64-char, padded) | ACTIVE params (others are `" "` fill, N_PARAM entries blank) |
|--------|--------------------------------------|--------------------------------------------------------------|
| 1 | `PRES, , , , , ` | PRES only |
| 2 | `PRES, , , , , ` | PRES only |
| 3 | `PRES, C1PHASE_DOXY, C2PHASE_DOXY, TEMP_DOXY, DOXY, ` | PRES + 4 O2-channel + DOXY |
| 4 | `PRES, FLUORESCENCE_CHLA, BETA_BACKSCATTERING700, CHLA, CHLA_FLUORESCENCE, BBP700` | PRES + 2 raw FLBB + CHLA + CHLA_FLUORESCENCE + BBP700 |

**BD-file `PARAMETER` (N_PROF × N_CALIB × N_PARAM=6) mirrors STATION_PARAMETERS per profile.**

> **CORRECTION-1 — `N_PARAM` is file-type-fixed, not per-profile-active count:** For this family, `N_PARAM` is **3 for D-files, 6 for BD-files, 11 for Meta** (fixed slot-width per Argo §2.2.2/§2.6). Sparse per-profile membership (e.g. BD N_PROF 1&2 = PRES-only) is represented by **padded `" "` entries in the `STATION_PARAMETERS(N_PROF,N_PARAM,STRING64)` array**, not by shrinking `N_PARAM`. Writer MUST preserve that sparse padding exactly; test assertions like `N_PARAM == count(active)` are **INVALID**.

> **MUST per Argo Reference Table 3 (NERC R03)**: Parameter names are case-sensitive vocabularies. Ordering is **NOT prescribed** globally — but writer ordering MUST be consistent across Meta/Tech/Profile for the same float type and MUST follow one stable REFLECTS-SENSOR order. For INCOIS parity, writer MUST emit the 11-order above in Meta and the per-file subsets above in profiles (core 3, BGC 5+6 as shown). `PARAMETER_UNITS` / `accur/resolution` MUST align positionally.

### 3.2 Units / Accuracy / Resolution (REFERENCE from meta, checked via header)

| Param | Units (INCOIS meta) | Accuracy | Resolution |
|-------|---------------------|----------|------------|
| PRES | decibar | manufacturer | |
| TEMP | degree_Celsius (ITS-90) | | |
| PSAL | psu | | |
| C1PHASE/C2PHASE | degree / degree | — | — |
| TEMP_DOXY | degree_Celsius | | |
| DOXY | micromole/kg | | |
| FLUORESCENCE_CHLA | count | Uncalibrated | |
| BETA_BACKSCATTERING700 | count | Uncalibrated | |
| CHLA | mg/m3 | | |
| BBP700 | m-1 | | |

> Derived params (CHLA, BBP700) units are POST-calibration; raw intermediates have instrument counts.

---

## 4. Core vs BGC relationships (item 5) — separating official / INCOIS / Coriolis / GDAC

### 4.1 Argo official family model (MUST)

- Core = CTD (PRES, TEMP, PSAL, optionally CNDC) — managed in Argo User's Man. §2.2.
- BGC = extension §2.6 — dimensions enlarged (STRING16→STRING64, N_PARAM PARAMETER_DATA_MODE, multi-dimensional params). A BGC float carries both core and BGC; S-files merge them, B-files carry BGC-only (PRES always duplicated as anchor).

### 4.2 INCOIS publication family (REFERENCE — what INCOIS does for 301)

- **Split publication:** `D` (core, 3 params) + `BD` (BGC intermediates + derived, 4 intermediates + CHLA/BBP/...) — no `S` merged file emitted for 301 in observed cycles. This matches B-file spec §5.1.2.1. Classification: **REFERENCE / SHOULD for parity; OPTIONAL per official spec.**
- **Grouping:** INCOIS groups by mission sampling: O2 and FLBB legs are separated into distinct N_PROF entries because they have different PRES binning (`Secondary sampling: averaged [10s sampling: 25dbar average 2000→1000 ...]` vs FLBB surface averaging). `VERTICAL_SAMPLING_SCHEME` entries (one per N_PROF) precisely describe this — preserved verbatim from Coriolis VSS strings.
- **Param super:** INCOIS includes `CHLA_FLUORESCENCE` (an alternative Chla derived via fluorescence iteration) in addition to `CHLA` — both appear in N_PROF=4. Writer MUST support that column if present.

### 4.3 Coriolis chain artifact (Coriolis-specific)

- History software strings `CODA` (decoder), `COQC` (QC), `COPQ` (?) etc. are Coriolis implementation artifacts — not normative. **Writer history will use its own `INSTITUTION=IN`/`IF` mapping and `SOFTWARE=PY` (or `ARGOPY`), distinct from Coriolis GDAC artifacts — see §17.**
- GDAC mirror artifact: filename prefix `incois_` in local mirror (`ref/gdac_incois_301/`) is a local staging artifact; GDAC canonical path is `dac/incois/<wmo>/profiles/` — **not emitted by writer.**

### 4.4 GDAC artifact

- `DATA_STATE_INDICATOR` values `2C/2B` in observed D/BD profiles are GDAC post-processing annotations (derived from DATA_MODE vs PARAMETER_DATA_MODE) — writer computes them, not hardcoded.

---

## 5. PARAMETER_DATA_MODE (item 6)

| File | Observed | Semantics |
|------|----------|-----------|
| **D (core)** | No `PARAMETER_DATA_MODE` variable — only `DATA_MODE( N_PROF)=D,R,R,R` | Core §2.2.5: `DATA_MODE` per profile. `D` reflects OW/ DMQC deployment for N_PROF=1. |
| **BD (BGC)** | `PARAMETER_DATA_MODE(N_PROF, N_PARAM)` exists; observed maps:<br>`N_PROF 3 (O2 leg): R R R R D --`<br>`N_PROF 4 (FLBB leg): R R R A A A` | BGC §2.6.4: per-parameter delayed-moment. `R` = real-time, `D` = delayed on DOXY, `A` = real-time adjusted (CHLA/BBP NPQ/betasw correction applied at RT). |
| **Meta** | Not a profile file — no `PARAMETER_DATA_MODE`. | N/A |

**Writer rule (MUST):** Emit `PARAMETER_DATA_MODE` **only** when `DATA_TYPE` is `B-Argo profile file` (= B/D/S). Dimension `(N_PROF, N_PARAM)`, dtype `char STRING1`, fill `b' '`. Core D-file MUST NOT contain `PARAMETER_DATA_MODE`. BD-file MUST. Allowed tokens: `R`, `A`, `D` (per Reference table 6 — data mode). Writer sets `D` when N_CALIB>1 delayed step complete, `A` when RT adjustment (NPQ, SAGEO2 gain) applied, else `R`.

---

## 6. QC variables (item 7)

### 6.1 Observed

| File | QC vars present |
|------|-----------------|
| D | `JULD_QC (1-char)`, `POSITION_QC`, `PROFILE_PRES_QC`, `PROFILE_TEMP_QC`, `PROFILE_PSAL_QC`, plus per-level `PRES_QC`, `TEMP_QC`, `PSAL_QC` and their `_ADJUSTED_QC` twins |
| BD | `PROFILE_C1PHASE_DOXY_QC` etc per STATION_PARAM, plus per-level `* _QC` for every measured param, and `_ADJUSTED_QC` for adjusted DOXY/CHLA/BBP vectors. BD station `PRES_QC` is absent — PRES QC folded into `PROFILE_*_QC`. |

### 6.2 MUST (Argo QC manual doi:10.13155/33951 / 46542)

- Every measured parameter gets a `PARAM_QC(N_PROF,N_LEVELS)` char variable; profile-level `PROFILE_PARAM_QC(N_PROF)` is summary.
- `JULD_QC`, `POSITION_QC` are mandatory.
- QC flag vocab: `0` not QC'd, `1` good, `2` probably good, `3` bad but potentially correctable, `4` bad, `5` value changed, `6-8` interpolated/estimated, `9` missing, fill `b' '`. For RT publication: data QC may remain `1` until RTQC; delayed may promote to `2-4`.
- Writer MUST set `HISTORY_QCTEST` hex bitmask per action (see §17).

---

## 7. Adjusted / unadjusted variables (item 8)

| Param class | Unadjusted | Adjusted | Error | When to emit |
|-------------|------------|----------|-------|--------------|
| Core CTD | `PRES/TEMP/PSAL` | `PRES_ADJUSTED/TEMP_ADJUSTED/PSAL_ADJUSTED` + `_QC` + `_ERROR` | `*_ADJUSTED_ERROR` float `99999.0` if not computed | **MUST** — always emit both tiers (Argo User's Man §2.2.5). If no adjustment, writer sets `SCIENTIFIC_CALIB_EQUATION = "PRES_ADJUSTED = PRES"` + `Comment = "No adjustment was necessary -Calibration error is manufacturer specified accuracy"` (verbatim observed in D-file) |
| O2 raw → derived | `C1PHASE/C2PHASE/TEMP_DOXY/DOXY` | `DOXY_ADJUSTED (+_QC/_ERROR)` | `DOXY_ADJUSTED_ERROR` | MUST per BGC §2.6.6. If RT, DOXY_ADJUSTED = DOXY * G (SAGEO2 gain) even though data mode stays `R` for inputs and `D` for DOXY (delayed). See DOXY §14. |
| FLBB raw → derived | `FLUORESCENCE_CHLA, BETA_BACKSCATTERING700` | `CHLA_ADJUSTED, BBP700_ADJUSTED, CHLA_FLUORESCENCE_ADJUSTED` | `_ADJUSTED_ERROR` | MUST. In observed BD, FLBB legs already `A` (adjusted RT) for CHLA/BBP; raw not delayed but corrected for NPQ/betasw. |

> **INCOIS REFERENCE:** In `BD2902091_001`, `BBP700_ADJUSTED = BBP700` (equation) with no correction — deliberate — see §15. `CHLA_ADJUSTED` applies NPQ (`CHLA_NPQ=0.520125, ZMaxFluo=22.7`) — writer derives same.

---

## 8. Meta variables (item 9) — what INCOIS meta actually contains

### 8.1 Global headers (observed, MUST-same per User Man §2.4)

- Dimensions: `DATE_TIME(14)`, `STRING8/16/32/64/256/4096`, `N_PARAM`, `N_SENSOR`, `N_CONFIG` (UNL), `N_MISSIONS` (UNL), `N_LAUNCH_CONFIG=161`.
- Variables: `DATA_TYPE("Argo meta-data")`, `FORMAT_VERSION("3.1")`, `HANDBOOK_VERSION("1.2")`, `DATE_CREATION/DATE_UPDATE`, `PLATFORM_NUMBER(STRING8)`, `PTT`, `TRANS_SYSTEM("IRIDIUM")`, `POSITIONING_SYSTEM("GPS"/"IRIDIUM")`, `PLATFORM_FAMILY/ TYPE("PROVOR")`, `FLOAT_SERIAL_NO`, `FIRMWARE_VERSION`, `MANUAL_VERSION`, `WMO_INST_TYPE`, `PROJECT_NAME`, `DATA_CENTRE("IN")`, `PI_NAME`, `BATTERY_TYPE`, `CONTROLLER_BOARD_TYPE`, `CONTROLLER_BOARD_SERIAL_NO`.
- Per §2.4.4-2.4.6: `SENSOR`, `SENSOR_MAKER`, `SENSOR_MODEL`, `SENSOR_SERIAL_NO` (6 entries: `CTD_PRES/CTD_TEMP/CTD_CNDC/SBE41CP*3 + OPTODE_4330 + FLBB ? — serials are `n/a` in INCOIS meta), `PARAMETER( N_PARAM=11)`, `PARAMETER_SENSOR`, `PARAMETER_UNITS`, `PARAMETER_ACCURACY/RESOLUTION`, `PREDEPLOYMENT_CALIB_EQUATION/COEFFICIENT/COMMENT (N_PARAM × 4096)` (see §16), `CONFIG_PARAMETER_NAME/VALUE (N_MISSIONS × N_LAUNCH_CONFIG / N_CONFIG)`, `LAUNCH_CONFIG_PARAMETER_NAME/VALUE`, `CONFIG_MISSION_NUMBER`, `POSITIONING_SYSTEM`, `TRANS_SYSTEM`, etc.

### 8.2 INCOIS observed specifics (REFERENCE)

| Variable | Incois value (2902086) |
|----------|------------------------|
| `SENSOR` | `CTD_PRES, CTD_TEMP, CTD_CNDC, OPTODE/ FLBB` — 6 entries (SBE SBE41CP repeated) |
| `SENSOR_SERIAL_NO` | `"n/a"` for all 6 — indicates INCOIS doesn't populate S/N in this fleet |
| `PARAMETER_SENSOR` | Maps param → sensor idx |
| `PREDEPLOYMENT_CALIB_EQUATION/COMMENT` | CHLA= `(FLUORESCENCE - DARK)*SCALE`; BBP=`2*pi*khi*((BETA -DARK)*SCALE -BETASW)` ; DOXY/TEMP_DOXY = full Stern-Volmer chain with coefficients matching O2 cookbook |
| `PREDEPLOYMENT_CALIB_COEFFICIENT` | `SCALE_CHLA=0.0073 DARK_CHLA=49`, `DARK_BACKSCATTERING700=49 SCALE_BACKSCATTERING700=1.645e-06 khi=1.097` (telemetry value, not yet corrected — see §15) |
| `CONFIG_PARAMETER_NAME` | Includes `CONFIG_NumberOfSubCycles_NUMBER, CONFIG_SurfaceDay_FloatDay, CONFIG_*_Pressure_dbar` etc — family-specific config inventory from `decArgo config/_configParamNames/_config_param_name_301.json`. Observed `N_CONFIG=18/17`. |

> Writer MUST emit mandatory metadata params per Argo Reference Table 19.1-19.5 (19.1 PREDEPLOYMENT, 19.2 CONFIG) — exhaustive inventory kept in new dedicated CSV `config/metadata/provor_cts4_meta_contract.csv` (design-time artifact listing mandatory variables vs INCOIS echo). Decoder-internal CONFIG params must be translated to Argo names via that lookup, not invented.

---

## 9. Tech variables (item 10)

### 9.1 Observed (REFERENCE)

`incois_2902091_tech.nc`:

- Dimensions: `N_TECH_PARAM=1288` (this cycle; accumulates across cycles), `STRING128` for name/value.
- Variables: `PLATFORM_NUMBER(STRING8)`, `TECHNICAL_PARAMETER_NAME(N_TECH_PARAM, STRING128)`, `TECHNICAL_PARAMETER_VALUE(N_TECH_PARAM, STRING128)`, `CYCLE_NUMBER(N_TECH_PARAM, int32, _FillValue=99999)`.
- Values observed: names like `CLOCK_FloatTime_YYYYMMDDHHMMSS`, `NUMBER_SubCyclesDoneSinceDeployment_COUNT`, battery, Argos/Iridium engineering (per `decArgo config/_techParamNames/_tech_param_name_301.json`).

### 9.2 MUST

- Tech file MUST carry one row per engineering datum with `CYCLE_NUMBER`; multiple rows may share same cycle. `FORMAT_VERSION=3.1`, `Conventions=Argo-3.1 CF-1.6`. HISTORY is not used in Tech (per User Man §2.5).

---

## 10. File naming conventions (item 11)

### 10.1 Observed vs Official

| File kind | Observed canonical name | Argo-official pattern (§4.1) | Writer rule |
|-----------|-------------------------|------------------------------|-------------|
| Meta | `2902086_meta.nc` | `<WMO>_meta.nc` | MUST |
| Tech | `2902091_tech.nc` | `<WMO>_tech.nc` | MUST |
| Core profile | `D2902091_001.nc` | `<R/D><WMO>_<XXX>[D].nc` with XXX zero-padded to 3, 4 digits >999 | MUST — decides prefix from DATA_MODE(1) |
| BGC profile | `BD2902091_001.nc` | `B<R/D><WMO>_<XXX>[D].nc` then `S<R/D>...` merged | REFERENCE — MUST produce `BD/BR` for parity; SHOULD also produce `SD/SR` when configured |
| Trajectory | not in mirror | `<WMO>_<R/D>traj.nc` (§4.1.3) | OPTIONAL — writer capability planned, not required for parity |

---

## 11. Cycle / profile numbering (item 12)

**Observed:** `CYCLE_NUMBER` variable per N_PROF (4 entries: e.g. D has 4 cycle numbers all `1` — because the 4 N_PROF legs all belong to cycle 1). `DIRECTION` char `A`/`D` per N_PROF flags ascending vs descending (matches file suffix rule). `JULD` per N_PROF (float time + GPS fix). `CONFIG_MISSION_NUMBER` per N_PROF anchors which `N_MISSIONS` config row applied.

**MUST:** `CYCLE_NUMBER` 0-based special: cycle 0 is pre-deployment test (optional). INCOIS cycles 1…N. Writer MUST increment once per full surface-transmit cycle, not per SBD file. N_PROF ordering within a cycle is **MUST be ascending by `JULD`** and writer MUST not reorder across cycles.

> **No WMO-specific cycle hacks (HARD RULE).** Cycle parity is derived solely from telemetry cycle counter (`float_cycle_nb`) and telemetry `profileCycNum`.

---

## 12. Global attributes (item 13)

### 12.1 Observed headers

| Attr | D | BD | Meta | Tech |
|------|---|----|------|------|
| `title` | `Argo float vertical profile` | same | `Argo float metadata file` | `Argo float technical data file` |
| `institution` | `INCOIS` | `INCOIS` | `INCOIS` | `INCOIS` |
| `source` | `Argo float` | `Argo float` | `Argo float` | `Argo float` |
| `history` | `2023-08-07T18:23:37Z creation; 2023-08-11T13:32:23Z last update (coriolis COCD (V1.8) tool)` | `... COPQ software` | `2023-08-05T07:21:22Z creation; 2023-08-05T07:21:22Z last update (coriolis float real time data processing)` | `... real time data processing` |
| `references` | `http://www.argodatamgt.org/Documentation` | same | same | same |
| `Conventions` | `Argo-3.1 CF-1.6` | `Argo-3.1 CF-1.6` | `Argo-3.1 CF-1.6` | `Argo-3.1 CF-1.6` |
| `user_manual_version` | `3.1` | `3.1` | `3.1` | `3.1` |
| `featureType` | `trajectoryProfile` | `trajectoryProfile` | — (meta) | — (tech) |
| `decoder_version` | `CODA_057d` | `CODA_057d` | `CODA_057b` | `CODA_057d` |
| `netcdf_version` | platform (e.g. `4.7.4` if echoing Coriolis) | | | |

**Writer MUST (per User Man §2.2.1/2.3.1):** include `title`, `institution`, `source`, `history`, `references`, `Conventions`, `user_manual_version`, `featureType` (profile/traj only), and `id`=DOI for dataset. **`decoder_version` (global attribute) is frozen as canonical `PY-301-x.y.z`** (semantic-versioned, e.g. `PY-301-0.3.0`), **distinct from `HISTORY_SOFTWARE = PY301`** (4-char, no hyphens, no dots). Writer MUST NOT emit `CODA_*` and MUST keep these two tokens disjoint — see CORRECTION-5.

---

## 13. Fill-value conventions (item 14)

| Variable class | Fill | Observed |
|----------------|------|----------|
| Float data `*_LEVELS` (PRES, TEMP, PSAL, DOXY, CHLA, BBP…) | `99999.0` `float32` + valid_min/valid_max per param | Consistent |
| Char QC `_QC` | `b' '` (space) `_FillValue=b' '` | Consistent |
| String padded dims (STRING16/32/64/256/4096/128) | space-padded (`" "`) to length; `_FillValue=b' '` | Consistent |
| Integer `CYCLE_NUMBER` / config | `99999` int32 | Tech |
| Missing N_LEVELS bins | exactly `99999.0` | Not `NaN` |

**MUST per User Man:** fill values as above; writer MUST NOT use `NaN` as NetCDF fill (masked as `_FillValue`). Dimension variables `PARAMETER` etc. use space-padding, not null termination.

---

## 14. Dimensions / dtypes (item 15)

### 14.1 Dimension set (MUST)

Profile files: `DATE_TIME=14, STRING2/4/8/16/64/256/4096, N_CALIB, N_HISTORY, N_LEVELS, N_PARAM, N_PROF` — where **`N_LEVELS` is a single fixed dimension per file = `max(len(PRES_i))` across `N_PROF` in that file** (Argo User's Man §2.2.2/§2.6; e.g. D 95 and BD 95 are two separate file-level maxima, not 95×4).
Meta: adds `N_SENSOR, N_CONFIG (UNL), N_LAUNCH_CONFIG=161, N_MISSIONS (UNL)`.
Tech: `N_TECH_PARAM` — per User's Man §2.5.2 **`N_TECH_PARAM = UNLIMITED`** (p65) and confirmed in GDAC `incois_2902091_tech.nc` (`N_TECH_PARAM 1288 unlimited`); `N_HISTORY` is also `UNLIMITED` in D/BD (5/8 unlimited) while `N_LEVELS`, `N_PARAM`, `N_PROF`, `N_CALIB` remain **fixed** per file. See CORRECTION-8.

### 14.2 Dtype inventory (MUST)

- Data: `float32` for PRES/TEMP/PSAL/DOXY/CHLA/BBP… ; `int32` for cycle numbers; `char` (`|S1`) for all QC / names / flags.
- String vars are `(…, STRING*)` char arrays, not NetCDF4 strings (to preserve `Conventions` CF-1.6 `char` handling).
- `REFERENCE_DATE_TIME`, `DATE_CREATION/UPDATE` are `char DATE_TIME(14)` `YYYYMMDDHHMMSS`.

---

## 15. Calibration / provenance (item 16) — distinguishing official / Incois / Coriolis / GDAC artifacts

### 15.1 Calibration families

| Calibration layer | Variable | Observed content | Status |
|-------------------|----------|-----------------|--------|
| **Pre-deployment** | `PREDEPLOYMENT_CALIB_EQUATION/COEFFICIENT/COMMENT (meta, N_PARAM×4096)` | CHLA equation + `SCALE_CHLA=0.0073 DARK_CHLA=49`; BBP equation + `DARK_BACKSCATTERING700=49 SCALE_BACKSCATTERING700=1.645e-06 khi=1.097` + comment `Seabird Andrew Bernard ADMT18 http://doi.org/10.17882/54520` (in meta) **but with telemetry 1.645e-06, not corrected**; DOXY = full Stern-Volmer chain with `PhaseCoef0… c0..Spreset Pcoef1, B0…` | **REFERENCE** — writer MUST emit these; for BBP the meta coefficient is *the provenance of the telemetry value* |
| **Scientific (profile)** | `SCIENTIFIC_CALIB_EQUATION/COEFFICIENT/COMMENT + PARAMETER + PARAMETER (`N_PROF×N_CALIB×N_PARAM×STRING`)` | D: `PRES_ADJUSTED = PRES` + `none` etc for TEMP/PSAL OW 1.1 `CTD2018V01` ; BD DOXY: `DOXY_ADJUSTED = DOXY*G` with `G=1.167` (SAGEO2 gain); BD CHLA: NPQ correction `CHLA_NPQ=0.520125 ZMaxFluo=22.7` (twice, both calib 0 and 1); BBP: `BBP700_ADJUSTED = BBP700` with no coef | **MUST** — N_CALIB grows with DMQC actions |

### 15.2 BBP Original vs Corrected — the +1.2–1.26% reprocessed drift (PUBLICATION-REPROCESSED FIXABLE)

**Fact (from 4-layer proof, §3 of Phase2B2 report):**

- Telemetry Packet 250 carries `OriginalScaleFactor = 1.645e-06` (NKE byte spec, per `family_constants.py` 1e-12 proof).
- GDAC **corrected** factor is `CorrectedScaleFactor = 1.620-1.625e-06` (Barnard/Sullivan et al. + SEANOE `http://doi.org/10.17882/54520` reprocessed ADMT18 correction described in `cook_bbp.pdf` and meta comment `Reprocessed … following ADMT18`). Delta **+1.216–1.264% systematic** (8/8 corpus, BBP Original `1.60e-06` → Corrected `1.58e-06`, e.g. corpus +1.26%).
- INCOIS BD products already carry the corrected path (BBP `SCIENTIFIC_CALIB` is identity because the raw `BETA` has already been scaled with corrected factor upstream — provenance is meta comment).

**Design decision (no silent replacement — HARD RULE from Phase 2B1):**

| Option | What writer would do | Trade-off |
|--------|----------------------|-----------|
| **A (RECOMMENDED, SHOULD)** — **GDAC-parity (corrected)** with explicit history | Writer **recomputes BBP from raw `BETA` counts** as `BBP700=2*pi*khi*((BETA-DARK)*CorrectedScaleFactor-BETASW700)` with authoritative `CorrectedScaleFactor` (not telemetry `1.645e-06`), `khi=1.097`, per-float `DARK` and `BETASW700`; MUST NOT use `BBP_corrected = BBP_original × (Corrected/Original)` shortcut. Adds `HISTORY_ACTION="RE"` or `"CV"` + `HISTORY_PARAMETER="BBP700"` with `QCTEST` bit, and `SCIENTIFIC_CALIB_COMMENT="Corrected BBP: OriginalScaleFactor 1.645e-06 → CorrectedScaleFactor <value> via Barnard 55891.csv doi:10.17882/54520; recomputed from raw BETA"` | Passes FileChecker, matches INCOIS/GDAC science; reversible via history. Requires per-float corrected factor + raw BETA inputs (see §25 & WMO interface §19). |
| **B (REFERENCE, OPTIONAL)** — **Telemetry-truth (original)** | Writer keeps telemetry `1.645e-06`, emits BBP exactly as decoded internally; `PREDEPLOYMENT_CALIB` shows original, `HISTORY` notes no reprocessing | Bit-true to NKE bytes; fails naive GDAC numeric parity by ~+1.25% (expected diff), valuable for internal validation, not for GDAC publication. |
| **C (MUST for transparency)** — **Dual provenance** | Both factors stored: `PREDEPLOYMENT_CALIB_COEFFICIENT` lists original, `SCIENTIFIC_CALIB_COMMENT` lists corrected, `HISTORY` entry logs the transform with coefficients. If `N_CALIB=2` is used, profile `SCIENTIFIC_CALIB_COEFFICIENT` for BBP carries corrected factor in delayed calib entry. | Most audit-friendly. Writer supports it via `bbp_corrected_scale` optional input; if absent, writer DOES NOT fabricate — emits original and documents gap. |

> **No Barnard auto-apply (HARD RULE).** The decoder pipeline NEVER applies the correction silently; publication layer applies it only via explicit `bbp_mode="INCOIS_CORRECTED"` input. Default internal mode is `TELEMETRY_ORIGINAL` for regression safety; GDAC submission flips to `INCOIS_CORRECTED` with full provenance.

### 15.3 DOXY provenance

- Opteff: Meta provides full optode coefficients (`T0…T5, Spreset, Pcoef1, B0..B3, C0, PhaseCoef0..3, c0..c12 …`). Derived DOXY equation is Stern-Volmer via `TPHASE = C1-C2`, `Phase_Pcorr = TPHASE + Pcoef1*PRES/1000`, `CalPhase = PhaseCoef0+PhaseCoef1*Phase_Pcorr+…`, then `DOXY = f(CalPhase, TEMP_DOXY, salinity-from-PSAL, PRES)` (Oxy cookbook §7.x case 101/102 for Aanderaa 4330).
- Scientific calib is gain `G=1.167` (SAGEO2 Winkler-referenced) for D-mode DOXY (`R→D`) — observed `BD` N_CALIB=2 captures RT raw → DM adjusted.
- **DOXY offset +0.21 micromol/kg reported in Phase2B1 stays classified `PUBLICATION-RTQC` unless new evidence — writer MUST NOT fit/adjust DOXY domestically; RTQC is GDAC-side.**

---

## 16. History / conventions (item 17)

### 16.1 Observed HISTORY variables

```
D:  N_HISTORY=5   entries: ARFM/COD A/COQC  (IF institution), actions "CF", QCTEST hex "000000000008FB7E"… , dates 201902111424, 20230807…
BD: N_HISTORY=8   same family, QCTEST "000000000008B27E"… "C00000000008A07E", dates include 20190211142438 (real-time) and 20230807182338/20260625 (delayed COPQ)
```

Variables per User Man §2.6.7: `HISTORY_INSTITUTION(N_HISTORY,N_PROF,STRING4)`, `HISTORY_STEP(4)`, `HISTORY_SOFTWARE(4)`, `HISTORY_SOFTWARE_RELEASE(4)`, `HISTORY_REFERENCE(64)`, `HISTORY_DATE(DATE_TIME)`, `HISTORY_ACTION(4)`, `HISTORY_PARAMETER(16 or 64)`, `HISTORY_START_PRES/STOP_PRES`, `HISTORY_PREVIOUS_VALUE`, `HISTORY_QCTEST(16)`.

**Writer MUST:** Append one HISTORY entry per processing action, in chronological order. Steps:
- `ARFM` (Argo Real-Time Format Manager), `ARGQ` (QC), `ARCA` (calibration) — reference table 9.
- `SOFTWARE` for this encoder is frozen as **`PY301`** (4-char, distinct from Coriolis `CODA`/`COQC`/`COPQ`); `SOFTWARE_RELEASE` carries the version without prefix (e.g. `0.3.0`); **`INSTITUTION` is `IN` (INCOIS)** or staging `IF` only for debugging (observed `IF` is Coriolis IFREMER staging — writer keeps `IN` for submission). **Global `decoder_version` is separately frozen as `PY-301-x.y.z`** — the two tokens are disjoint by design (CORRECTION-5).
- `HISTORY_QCTEST` is hex of tests applied (reference table 20).

### 16.2 Conventions

- `Conventions = "Argo-3.1 CF-1.6"` (observed — **MUST**). Future migration to `Argo-3.2 CF-1.6` is flagged as **SHOULD when manual rev advances**, not back-ported.
- `user_manual_version = "3.1"` (observed) — writer tracks spec rev in header; bump only with spec change.
- `featureType = "trajectoryProfile"` for mono-profile.

---

## 17. Classification of artifacts — official vs INCOIS family vs Coriolis vs GDAC

| Artifact class | Examples | Writer treatment |
|----------------|----------|------------------|
| **Official Argo (normative)** | File naming prefix rules, `Conventions`, dimensions/dtypes, QC vocab, `HISTORY` schema, `PARAMETER` vocab | **MUST** follow verbatim |
| **INCOIS family publication (observed parity)** | 11-param meta order, 6-param BGC ordering (`C1/C2/TEMP_DOXY/DOXY` + `FLUO/BETA/CHLA/…`), D+BD split, NPQ `CHLA_NPQ=0.520125`, 95 levels, `N_CONFIG` 18/17, `SENSOR n/a` | **REFERENCE / SHOULD** — writer emits exactly these for 301 parity; flagged as family-specific, not universal Argo |
| **Coriolis container implementation** | `HISTORY_SOFTWARE=CODA/COQC/COPQ`, `decoder_version=CODA_057*`, `IF` institution staging, `COPQ` delayed post-processing | **Coriolis artifact** — writer MUST NOT mimic `IF`/`CODA`; emits its own `IN`/`PY301` provenance |
| **GDAC mirror artifact** | Directory `dac/incois/...`, prefix `incois_` in local staging, `DATA_STATE_INDICATOR` derivation | Not emitted; GDAC path is deployment concern |

> GDAC is **parity reference, not automatic truth** — when INCOIS product disagrees with official spec, the disagreement is classified. Example: `SENSOR_SERIAL_NO=n/a` is INCOIS family artifact; official spec expects serials when known — classification `EXPECTED` for this fleet, not a writer bug.

---

## 18. WMO assignment — outside decoder (HARD RULE)

### 18.1 Interface contract

- **Decoder (301 family) NEVER derives or hardcodes WMO.** Code grep prior: no `imei_to_wmo` / `flbb_serial_to_wmo` in CTS4 path. Phase2B2 demonstrated this: synthetic float `99999` CHLA/BBP succeeded without CSV; legacy DOXY `flbb_serial_to_wmo[99999]` raised `KeyError DATA-COVERAGE` — proving separation.
- **Writer input contract (MUST):**

```python
@dataclass
class WriterInputs:
    profiles: list[Profile]           # decoder output, telemetry-derived only (pres/temp/psal/doxy/raw counts)
    meta_source: FloatMetadataSource  # composite: raw telemetry fields + authoritative external per-float record
    wmo: str                          # externally supplied, authoritative 7-digit numeric string; MUST match /^[0-9]{7}$/ and be validated against external authoritative metadata (deployment registry / DAC inventory); MUST NEVER be derived from IMEI or telemetry; no hard-coded allocation-range check (e.g. no 290xxxx gate) — see CORRECTION-4
    institution: str                  # "IN" for INCOIS submission, "IF" etc only for Coriolis-staged debug
    decoder_version: str              # canonical "PY-301-x.y.z" (frozen; distinct from HISTORY_SOFTWARE "PY301") — see CORRECTION-5
    cycle_index: int                  # 1..N
    data_mode: str                    # R/D/A per calibration state
    bbp_mode: Literal["TELEMETRY_ORIGINAL","INCOIS_CORRECTED"]  # default TELEMETRY_ORIGINAL; submission uses INCOIS_CORRECTED with corrected factor supplied
    bbp_corrected_scale: float | None  # when bbp_mode=CORRECTED, must be supplied externally; writer MUST error if None (no fabrication); corrected BBP MUST be recomputed from raw BETA/DARK/scale/BETASW/khi (MUST NOT scale-ratio) — CORRECTION-1
    doxy_external_calib: dict | None   # per-float optode cal dict (see §14) — None means only DOXY fill/QC=9, but C1/C2/TEMP_DOXY preserved — CORRECTION-6
```

- **Where WMO comes from:** Operational DAC inventory / INCOIS deployment registry. The writer accepts it as a string argument; it is embedded into `PLATFORM_NUMBER` (both global header and per-profile `PLATFORM_NUMBER(N_PROF, STRING8)` variables) and file name. **Writer MUST fail fast if WMO is absent or malformed — no silent IMEI-derived fallback.**
- **New dedicated CSVs allowed (not redesign of existing):** The existing `config/metadata/provor_cts4_301_reference.csv` is a **frozen 10-column provenanced reference** (`scope,wmo,sensor_model,sensor_serial,parameter,coefficient,value,source_file,source_variable,interpretation`; 1534 rows, including 88 family-generic rows) sourced row-by-row from `incois_<WMO>_meta.nc` with `source_file` provenance — **MUST NOT be silently redesigned or overwritten** (CORRECTION-4). Writer-facing publication inputs that need a different schema (e.g., wide-format BBP scale pairs) SHALL live in a **separate dedicated publication-metadata CSV** (e.g., `config/metadata/provor_cts4_pub_bbp_scales.csv` with columns `wmo,sensor_serial,bbp_original_scale,bbp_corrected_scale,source,provenance` keyed by FLBB serial/WMO, never IMEI). DOXY float-specific coefficients remain via the separate `provor_cts4_external_doxy_example.csv` mechanism (FLBB-serial-keyed) unless a unified publication CSV is later defined. All new CSVs store *publication* inputs, not decoder-evaluated constants.

### 18.2 Synthetic NEW float without pre-existing WMO (proven)

Phase2B2 4-layer proof used `WMO=99999 / 88888` synthetic floats absent from `flbb_serial_to_wmo`:
- CHLA/BBP: derived via `family_constants.SCALE_CHLA=0.0073`, `DARK_CHLA=49`, telemetry `SCALE_BACKSCATTERING700` without any WMO look-up.
- DOXY: succeeds only via explicit `doxy_cal_from_external_dict(synthetic_float_specific)` (perturbed `PhaseCoef0+1e-4` from 2902086), reproducing `29.5 umol/kg`; missing-key raises.
- So a never-before-seen float can be published immediately once its deployment sheet (WMO + BBP corrected scale + DOXY cal sheet `T0…Spreset/Pcoef/B0…PhaseCoef c0…`) is provided via the WriterInputs interface — no code change.

---

## 19. BBP Original vs Corrected — standards-defined representation (BBP §15 expanded, no implementation)

### 19.1 Byte truth vs publication truth

- **Byte truth (telemetry):** Packet 250 field `SCALE_BACKSCATTERING700_Original = 1.645e-06` (NKE 5.8: 32-bit float, counts→engineering). Preserved in internal model as `raw_scale_bbp_original: float32` and in `PREDEPLOYMENT_CALIB_COEFFICIENT` as `SCALE_BACKSCATTERING700`.
- **Publication truth (corrected, ADMT18):** Corrected BBP MUST be **recomputed from raw `BETA_BACKSCATTERING700` counts** using the full BBP equation `BBP700 = 2*pi*khi*((BETA - DARK_BACKSCATTERING700)*CorrectedScaleFactor - BETASW700)` with `khi=1.097` (family-generic), float-specific `DARK_BACKSCATTERING700` and `BETASW700` (Zhang 2009, dep 0.039), and `CorrectedScaleFactor` from the authoritative Barnard table (`http://doi.org/10.17882/54520` `55891.csv`). This is **not** `BBP_corrected = BBP_original × (CorrectedScale/OriginalScale)`; that ratio shortcut is **MUST NOT** be used because it neglects `BETASW` subtraction ordering and would bias low-turbidity bins. Official representation is captured in **`SCIENTIFIC_CALIB`** or **`HISTORY`** stating the reprocessing source, not a silent coefficient swap.

### 19.2 Representation options — which standards slot holds "corrected"?

| Standard construct | When to use (design-time preference) |
|--------------------|--------------------------------------|
| `PREDEPLOYMENT_CALIB_COMMENT` | Always includes comment `Reprocessed from file provided by Andrew Bernard (Seabird) following ADMT18. This file is accessible at http://doi.org/10.17882/54520.` — anchors provenance (observed in INCOIS meta) |
| `SCIENTIFIC_CALIB_EQUATION/COEFFICIENT` (recommended for corrected) | `BBP700_ADJUSTED = BBP700` with `SCIENTIFIC_CALIB_COMMENT="Corrected BBP700 scale: OriginalScaleFactor 1.645e-06 → CorrectedScaleFactor {value} (Barnard 54520)"` — matches INCOIS BD `BBP700_ADJUSTED=BBP700` identity pattern |
| `HISTORY_ACTION` entry | Add one `HISTORY_ACTION="CV"` (calibration value change) with `HISTORY_PARAMETER="BBP700"` and `QCTEST` documenting reprocessing; `HISTORY_REFERENCE` points to doi. |

> **Writer MUST NOT silently replace** `1.645e-06` with corrected value in `PREDEPLOYMENT_CALIB_COEFFICIENT` without history. **No Barnard auto-apply at decode time.** The publication encoder applies corrected factor only under `bbp_mode=INCOIS_CORRECTED` and requires an external `bbp_corrected_scale` float — otherwise it emits telemetry-original and records `DATA_COVERAGE: corrected factor not supplied`.

---

## 20. DOXY design — equation → raw / phase / adjusted / QC / provenance

### 20.1 Raw surfaces from telemetry

| Telemetry origin | Decoder internal name | NetCDF placement |
|------------------|-----------------------|------------------|
| Packet 250 CTD | `pres_raw`, `temp_raw`, `psal_raw` | D-file `PRES/TEMP/PSAL` + QC/ADJUSTED |
| Packet 250 OPT | `c1phase`, `c2phase` (deg), `temp_doxy_voltage → TEMP_DOXY` via `T0…T5` polynomial | BD `C1PHASE_DOXY/C2PHASE_DOXY/TEMP_DOXY` |

`TEMP_DOXY` equation (meta verbatim, Oxy cookbook Case_101/102 for Aanderaa 4330):
```
TEMP_DOXY = T0 + T1*TEMP_VOLTAGE_DOXY + T2*TEMP_VOLTAGE_DOXY^2 + T3*…^5
TEMP_VOLTAGE_DOXY = thermistor bridge voltage (mV)
Coeffs: T0=26.5636 T1=-0.0312362 T2=3.02924e-06 T3=-4.45159e-09 T4=0 T5=0 (per 2902086)
```

### 20.2 Intermediate → DOXY (raw publication variable)

```
TPHASE_DOXY       = C1PHASE_DOXY - C2PHASE_DOXY
Phase_Pcorr       = TPHASE_DOXY + Pcoef1*PRES/1000
                    Pcoef1=0.1, Pcoef2=0.00022, Pcoef3=0.0419 (meta)
CalPhase          = PhaseCoef0 + PhaseCoef1*Phase_Pcorr + PhaseCoef2*Phase_Pcorr^2 + PhaseCoef3*Phase_Pcorr^3
                    PhaseCoef0=0.0657959 PhaseCoef1=1.00574 PhCoef2=0 PhCoef3=0 (per float — external)
deltaP            = c0*TEMP_DOXY^m0*CalPhase … (full Stern-Volmer: solubility coefficients SolB0…SolC0, c0..c12, B0..B3, Spreset)
DOXY (umol/kg)    = SternVolmer(CalPhase, TEMP_DOXY, PSAL, PRES)  (see cook Oxy v2.3.4 §7.2.6)
```

*Meta carries all Stern-Volmer constants (`B0…B3=−0.00624…`, `C0=−4.88682e-07`, `c0=−3.60479e-06 … c12=−0.02222`, `SolB*`), copied verbatim into `PREDEPLOYMENT_CALIB_COEFFICIENT`. Writer copies the supplied per-float optode cal dict into `PREDEPLOYMENT_CALIB_EQUATION/COEFFICIENT/COMMENT` for DOXY and `TEMP_DOXY` — no family constant beyond fleet defaults.*

### 20.3 QC / adjusted

- RT: `DOXY_QC` = derived from `C1/C2/TEMP_DOXY_QC` family; `DOXY_ADJUSTED` is copy (`A` or `D` mode later). Delayed-mode Winkler gain `G≈1.05–1.20` (observed `1.167`) multiplies: `DOXY_ADJUSTED = DOXY*G` with `SCIENTIFIC_CALIB_EQUATION="DOXY_ADJUSTED = DOXY*G, where G is the gain obtained from the SAGEO2 output"` and `PARAMETER_DATA_MODE(N_PROF,N_PARAM) for DOXY = D` (BD N_PROF=3).
- **PUBLICATION-RTQC offset ~+0.21 stays.** Decoder MUST NOT fit a `-0.21` offset; any future correction is a GDAC-level RTQC entry with `HISTORY_ACTION` documenting source.

### 20.4 Adjusted error

`DOXY_ADJUSTED_ERROR(N_PROF,N_LEVELS)` is propagated from Winkler uncertainty + optode drift sheet — writer sets `99999` (missing) if unavailable at RT.

> **Missing optode calib (CORRECTION-6):** If authoritative per-float Stern-Volmer coefficients (`T0…Spreset … c0..c12`, `PhaseCoef0/1`) are unavailable, writer MUST NOT fabricate or fall back to another float's sheet. It **preserves** `C1PHASE_DOXY`, `C2PHASE_DOXY`, `TEMP_DOXY` with real telemetry values and QC, but sets `DOXY` and `DOXY_ADJUSTED` to `_FillValue=99999.0` with `QC=9` (missing), `PARAMETER_DATA_MODE` for `DOXY` stays `R`, and logs `DATA-COVERAGE` with `HISTORY` noting absent calib. This matches BGC §2.6.6 intermediate-preservation rule.

---

## 21. Metadata architecture — raw + authoritative per-float → generic decoder → internal → publication

### 21.1 Pipeline layers (unchanged from 2B2; writer layer added)

```
Raw telemetry (SBD packets, bytes 250/253/…) ─┐
                                              ├──> Generic 301 decoder (family_constants.py)
NKE 5.8 spec (packet structure) ──────────────┤         reads family-generic physics (SCALE_CHLA 0.0073, khi 1.097 etc, 1e-12 proven)
Legacy 4 CSVs (frozen, bootstrap only) ───────┘         resolves telemetry scaling without WMO

External authoritative per-float metadata (NEW dedicated CSV) ─┐
   WMO,  BBP corrected scale,  DOXY optode coeffs,  serials,  │
   NPQ ZMaxFluo, deployment sheet                             │
                                              ├──> Publication encoder
Decoder internal model (canonical PRES/TEMP/PSAL/ │             takes WriterInputs (wmo + per-float cal)
  C1/C2/TEMP_DOXY/DOXY/FLBB counts / CHLA/BBP) ───┘             emits NetCDF per §1-17 contract

GDAC / FileChecker v3.x ───────────────────── validates
```

### 21.2 CSV handling

- **4 legacy CSVs (`meta.csv`, `sensor-info.csv`, `calib.csv`, `config_params.csv`) — FROZEN.** Decoder uses them only for bootstrap where present; CTS4 floats not present there → `DATA-COVERAGE` paths (observed `KeyError` for DOXY is expected, CHLA/BBP 88-generic succeeds without them).
- **Existing `provor_cts4_301_reference.csv` — FROZEN 10-column provenanced reference.** Schema `scope,wmo,sensor_model,sensor_serial,parameter,coefficient,value,source_file,source_variable,interpretation` (1534 data rows = 1535 with header; rows carry `source_file=incois_<WMO>_meta.nc` provenance). It encodes 88 family-generic coefficients (identical across 13 INCOIS 301 meta.nc) plus per-float entries; it is **not** a writer publication-input table and **MUST NOT be redesigned** (CORRECTION-4). To confirm: `head -1` → `scope,wmo,...` and `wc -l` → `1535`.
- **Separate dedicated publication-metadata CSV (if needed) — new file.** If writer-facing publication inputs require wide-format scales (e.g., BBP `bbp_original_scale`/`bbp_corrected_scale` per FLBB serial), create a **separate** CSV such as `config/metadata/provor_cts4_pub_bbp_scales.csv` with explicit columns `wmo,sensor_serial,bbp_original_scale,bbp_corrected_scale,source,provenance` (keyed by `sensor_serial`/WMO, never IMEI). **Synthetic `99999/88888` MUST NEVER be added to `301_reference.csv`** — they live strictly in `config/metadata/provor_cts4_external_doxy_example.csv` (`flbb_serial,PhaseCoef0,PhaseCoef1,c0..c20,TEMP_T0..T3,provenance` with `synthetic:` tag, perturbed from 2902086). See CORRECTION-3/4.
- **Telemetry 250 is byte authority.** Family-generic constants (SCALE_CHLA, khi, etc.) stay in `family_constants.py`, imported as truth; CSV provenance mirrors them with comment `Source: NKE 5.8 / family_constants.py`.

---

## 22. Exact writer inputs & pre-conditions (no fabrication)

### 22.1 Mandatory pre-conditions (writer MUST error if violated)

| Condition | Check |
|-----------|-------|
| `wmo` externally supplied 7-digit numeric string | MUST match `/^[0-9]{7}$/` and be validated against external authoritative metadata (deployment registry/DAC inventory); MUST NEVER be derived from IMEI/telemetry; **no hard-coded allocation-range check** (removed 290xxxx gate) — CORRECTION-4 |
| `decoder_version` canonical `PY-301-x.y.z` (global attr) distinct from `HISTORY_SOFTWARE=PY301` | MUST match `/^PY-301-\d+\.\d+\.\d+$/` and `HISTORY_SOFTWARE == "PY301"` — CORRECTION-5 |
| `profiles` non-empty, each `juld`, `lat`, `lon` present | Quality gate |
| For every BD profile requiring BBP: either `bbp_mode=TELEMETRY_ORIGINAL` or (`bbp_mode=INCOIS_CORRECTED` AND `bbp_corrected_scale` is not None AND in [0.5e-06,5e-06]) | No fabrication |
| For every BD profile with O2 sensors: if `doxy_external_calib` missing/incomplete, writer **MUST preserve raw/intermediate variables `C1PHASE_DOXY/C2PHASE_DOXY/TEMP_DOXY` with their measured values and QC**; **only `DOXY`/`DOXY_ADJUSTED` become `_FillValue=99999.0` with `QC=9`** (missing) and `PARAMETER_DATA_MODE` stays `R`. No calibration is fabricated — CORRECTION-6 | No partial optode for DOXY, but intermediates are not suppressed |
| `N_LEVELS` is **file-level** `max(len(PRES_i))` across `N_PROF` in that output file (e.g. D-file `N_LEVELS` = max of its 4 PRES vectors; BD-file separately) — not per-profile | Not hard-coded 95 |
| No telemetry-derived `PLATFORM_NUMBER` reuse | Writer strips any IMEI-derived WMO if present |

### 22.2 Configuration flags (publication toggles — designed, not implemented)

```python
class WriterConfig:
    generate_core: bool = True            # MUST
    generate_bgc: bool = True             # SHOULD when BGC present (303-family: always)
    generate_synthetic_s: bool = False    # OPTIONAL, default False for INCOIS 301 parity
    generate_traj: bool = False           # OPTIONAL — not in INCOIS mirror, staged behind flag
    trajectory_type: Literal["merged","split"] = "merged"  # official merged since 3.1
    bbp_mode_default: Literal["TELEMETRY_ORIGINAL","INCOIS_CORRECTED"] = "TELEMETRY_ORIGINAL"
    # When INCOIS_CORRECTED + traj, both get same scale provenance
```

> **DESIGN ONLY — no flag toggles implemented in this phase.** Flags are specified so Phase 3 implementer knows call-site shape.

---

## 23. Blockers & open items (carried forward — DO NOT guess)

| Item | Status | Classification |
|------|--------|----------------|
| **DOXY ~+0.21 offset** (RT bias vs GDAC delayed) | Retained as `PUBLICATION-RTQC` — writer does not fit correction | PUBLICATION-RTQC |
| **BBP Original vs Corrected** | Systematic +1.25% measured, provenance `http://doi.org/10.17882/54520` identified, no silent swap | PUBLICATION-REPROCESSED FIXABLE (once corrected scale supplied) |
| PT26/27 all-0xFF quirk in mode 10 | UNKNOWN | UNKNOWN |
| FLAG_SensorBoardStatus 0xFF | UNKNOWN | UNKNOWN |
| Packet 253 rtc — 4-byte BE little? | UNKNOWN | UNKNOWN |
| Cycle 9 missing for 03530 (raw has gap) | UNKNOWN | UNKNOWN |
| Optode lead-u16 serial hypothesis (lead word of 250) | Unproven | UNKNOWN — not in publication header |
| Trajectory for 301: does INCOIS actually publish `_Rtraj`/`_Dtraj`? | DATA-COVERAGE — not in cycle-001 mirror; GDAC `dac/incois` crawl needed in Phase 3 impl kickoff | DATA-COVERAGE |
| Synthetic S-file requirement for INCOIS submission | UNKNOWN — INCOIS 301 currently uses D/BD split; S is OPTIONAL per spec | OPTIONAL |
| fill `1.645e-06` vs `1.58e-06` factor-of-three legacy CSV value `1.652e-06` mystery for older floats | UNKNOWN — keep separate provenance | UNKNOWN |
| Meta SENSOR_SERIAL_NO `n/a` vs true serial availability | EXPECTED family artifact — not blocker | EXPECTED |

---

## 24. Testing plan — FileChecker v3.0.5

### 24.1 Target under test

FileChecker `Argo FileChecker v3.0.5` (GDAC Checks doi:10.13155/46120). Runner: `file_checker --format=argo3.1 <path>/*.nc` (local docker `ifremer/argocheck`). Tests classify as `ERROR` (structural) vs `WARNING` (cookbook/content).

### 24.2 Structural coverage (MUST — fail build if any ERROR)

| Check | Spec ref | Test data | Expected result in DESIGN |
|-------|----------|-----------|---------------------------|
| Global attrs `title/institution/source/history/references/Conventions/user_manual_version/featureType` present | §2.2.1 | Synthetic `99999_001.nc` minimal core | ERROR if missing |
| Dimensions: `DATE_TIME=14`, STRING widths, N_PROF≥1, N_LEVELS≥1, **N_PARAM fixed slot-width per file type (D:3 / BD:6 / Meta:11)**, N_HISTORY monotonic, N_CALIB 1..2 | §2.2.2 | D (core 3) + BD (BGC 6) with 4×N_PROF | ERROR on mismatch — **N_PARAM MUST NOT be set to count(active STATION_PARAMETERS in a profile); sparse profiles are represented by padded `" "` entries in STATION_PARAMETERS(N_PROF,N_PARAM) (see CORRECTION-1)** |
| Dtypes: data `float32`, QC `char`, CYCLE_NUMBER `int32` with fill 99999/99999.0/space | §2.2.5 | All data vars | ERROR on double/short misuse |
| `PLATFORM_NUMBER`, `DATA_TYPE`, `FORMAT_VERSION`, `POSITIONING_SYSTEM` valid vocab | Ref tables 4-6 | All files | ERROR on unknown string |
| `JULD`, `LATITUDE`, `LONGITUDE`, `CYCLE_NUMBER`, `DIRECTION` present per N_PROF, monotonic | §2.2.4 | 2-cycle mock | ERROR |
| `STATION_PARAMETERS` aligns with actual variables present — file-level `N_PARAM` stays fixed (BD:6 / D:3); sparse N_PROF rows have `" "` padding in their `STATION_PARAMETERS(N_PROF,N_PARAM)` entries (e.g. PRES-only rows keep `N_PARAM=6` width with 5 padded blanks) | §2.6.1 | BD N_PROF 1&2 PRES-only vs N_PROF 3&4 full (test checks padding, not `N_PARAM` shrinkage) | ERROR if padded blanks not preserved (CORRECTION-1/5) |
| Variables' `_FillValue` exactly 99999.0 / 99999 / space | §2.2.5 | Any N_LEVELS synthetic | ERROR |

> **CORRECTION-5 — file-level vs per-profile:** `N_PARAM` and `N_LEVELS` are **file-level fixed dimensions** (per §2.2.2/§2.6; e.g. BD `N_PARAM=6` even though N_PROF 1&2 use only 1 slot). Tests MUST assert fixed `N_PARAM`/`N_LEVELS` per file type and check sparse membership via `STATION_PARAMETERS` `" "` padding and `_FillValue` masking, **not** by equating `N_PARAM` to `count(active)` or `N_LEVELS` to per-profile `len(PRES_i)`.

### 24.3 Ordering / inventories (MUST — parity)

| Check | What writer must keep stable |
|-------|------------------------------|
| Meta `PARAMETER` order is `PRES TEMP PSAL C1PHASE_DOXY C2PHASE_DOXY TEMP_DOXY DOXY FLUORESCENCE_CHLA BETA_BACKSCATTERING700 CHLA BBP700` (11) | FileChecker checks exact order within family; mismatched order → WARNING but classified FIXABLE parity |
| D-file `PARAMETER` (3) = `PRES TEMP PSAL` | Parity with Coriolis meta |
| BD-file `STATION_PARAMETERS` per §3.1 subset | Parity |
| `PARAMETER_UNITS` positionally matched | Parity |

### 24.4 Metadata / provenance

| Check | Expected |
|-------|----------|
| `PREDEPLOYMENT_CALIB_EQUATION/COEFFICIENT/COMMENT` populated for DOXY/CHLA/BBP with full coefficient strings (checked substring `SCALE_CHLA=0.0073` etc) | WARNING if truncated (>4096) |
| `SCIENTIFIC_CALIB_EQUATION` core has `PRES_ADJUSTED = PRES` etc with `Comment "Calibration error is manufacturer specified…"` + `OW Method …` | WARNING if missing |
| Tech `TECHNICAL_PARAMETER_NAME` values restricted to `decArgo config/_techParamNames/_tech_param_name_301.*` — unknown names → ARGO WARNING | Use that CSV as allowlist |

### 24.5 QC / provenance / modes

| Check | Input to conjure |
|-------|------------------|
| Every measured var has `_QC` + profile `PROFILE_*_QC` + QC flags in 0-9/space | Synthetic cycle with one bad level (QC 4) |
| Every `*_ADJUSTED` has sibling `_QC` + `_ERROR` | Core CTD + DOXY gain |
| `PARAMETER_DATA_MODE` only in B(S)-files, values R/A/D; D-file prefix obeys `DATA_MODE(1)` | RT vs delayed synthetic (flip one profile to D, expect B-file rename to D) |
| `HISTORY_*` variables monotonic, `HISTORY_QCTEST` hex, `HISTORY_DATE` ISO-Z `YYYYMMDDHHMMSS` | Check history entry append |

### 24.6 Test matrix (to be implemented in Phase 3, not in this DESIGN phase)

| Suite | File | Goal |
|-------|------|------|
| `tests/test_phase2c_publish_meta.py` | 99999 synthetic via `WriterInputs` minimal | Validates meta `SENSOR/PARAMETER/CONFIG` parity |
| `tests/test_phase2c_publish_profile.py` | Synthetic 2 cycles: cycle 1 RT (R/BR), cycle 2 DM (D/BD) | Validates split files, N_PROF/N_LEVELS, QC, ADJUSTED, naming |
| `tests/test_phase2c_bbp_corrected.py` | Supply `bbp_corrected_scale=1.620e-06` + raw `BETA`/`DARK`/`BETASW`/`khi`, assert encoded BD `BBP700 = 2*pi*khi*((BETA-DARK)*1.620e-06 - BETASW)` (recomputed) and HISTORY entry cites `54520`; assert `BBP_corrected ≠ BBP_original × ratio` is not used | **Only pass when writer in CORRECTED mode — original mode recomputes with telemetry `1.645e-06`** |
| `tests/test_phase2c_doxy_external.py` | Supply `doxy_cal_from_external_dict` synthetic cal, assert `C1/C2/TEMP_DOXY/DOXY` round-trip and `SCIENTIFIC_CALIB` gain | Mirrors Phase2B2 Layer 3 |
| `tests/test_phase2c_filechecker.py` | Optional gated `file_checker --format=argo3.1` on generated dir | Structural ERROR count ==0 |

> **No NetCDF generated in this phase.** Tests above are **planned**. Existing tests (`tests/test_generic_cts4.py` 150/150 pass) remain frozen.

---

## 25. Data model & writer exact call shape (for implementer)

### 25.1 How writer is invoked (DESIGNED, not coded)

```
PublicationBuilder
  ├─ from_decoder(decoder_output: CTS4Payload) -> InternalModel
  │     # decoder_output: List[Profile] with arrays (pres_raw[N], temp_raw[N], …)
  │     # No WMO in here; WMO is an index into the external registry
  └─ write(
        wmo: str,
        payload: InternalModel,
        external_meta: CTS4ExternalRecord,   # row from dedicated publication CSV (e.g., provor_cts4_pub_bbp_scales.csv / external_doxy dict); NOT from provor_cts4_301_reference.csv which remains 10-column audit reference (CORRECTION-4)
        writer_config: WriterConfig,
        out_dir: Path
     ) -> WrittenFiles  # list[Path] absolute, e.g. [2902xxx_meta.nc, 2902xxx_tech.nc, D…, BD…]
```

- `CTS4ExternalRecord` is the parsed row from the **separate dedicated publication CSV** (e.g., `provor_cts4_pub_bbp_scales.csv` wide-format; **not** the frozen 10-column `provor_cts4_301_reference.csv` audit reference — CORRECTION-4): `wmo,cycle_number,direc,juld,lat,lon, **bbp_original_scale**, **bbp_corrected_scale**, doxy_json, deployment_*` (scale factors, not BBP). DOXY external dict continues via `provor_cts4_external_doxy_example.csv` (`flbb_serial`-keyed). The writer **fails** if `bbp_corrected_scale` is absent and `bbp_mode=INCOIS_CORRECTED`.
- `InternalModel` holds telemetry-only numbers; `ExternalRecord` holds provenance numbers. Writer blends only in `PREDEPLOYMENT_CALIB` / `SCIENTIFIC_CALIB` / `HISTORY` slots — never overwrites the float32 engineering arrays without logging.
- **FLBB raw retention (CORRECTION-7):** `InternalModel` for FLBB **MUST retain raw `BETA_BACKSCATTERING700` counts plus the inputs used for telemetry BBP** — `DARK_BACKSCATTERING700` (per-packet, e.g. 49/50/51), `Original SCALE_BACKSCATTERING700` (e.g. `1.645e-06`), `khi=1.097`, and `BETASW700` computed per level via Zhang 2009 (`beta_sw_ZHH2009`, dep 0.039, from CTD PSAL). This allows publication-time recomputation of `BBP700` with `CorrectedScaleFactor` without loss of `BETASW` ordering (see CORRECTION-1). Internal `BBP_original` may be cached but MUST NOT be the sole store; raw `BETA` is the science input.

### 25.2 NetCDF backend guidance

- Backend: `netCDF4` with `format="NETCDF4_CLASSIC"` (as in Coriolis decArgo), deflate level 1 for large N_LEVELS, `char` not `str` for portability.
- Fill handling: createVariables with `fill_value=99999.0` (float) / `99999` (int) / `b' '` (char); writer writes masked arrays (`np.ma`) with `99999` as mask value.
- Ordering: `set_auto_maskandscale(True)` compatibility; variables written in reference-table order so FileChecker `PARAMETER order` is deterministic.

---

## 26. What is NOT designed / remains out of scope for Phase 2C

- No R-trajectory/D-trajectory AXIS encoding (N_MEASUREMENT vs N_CYCLE) — planned as Phase 3b once INCOIS traj sample obtained.
- No vacuum/1200 PSI pres offset handling beyond NKE bytes — kept as telemetry-internal.
- No cycle-9 anomaly mitigation — stays UNKNOWN.
- No GitHub sync — public Git-LFS only by reference (`MIGRATION_DIRECT_PLAN.md` §0).
- No mutation of `ARVOR-I` / `APEX` encoders.

---

## 27. Checklist for Phase 3 implementer (hand-off)

- [ ] **Keep `provor_cts4_301_reference.csv` FROZEN** (10 columns, 1534 rows, `scope,wmo,sensor_model,...` with `source_file` provenance) — **do not redesign or add columns** (CORRECTION-4). If writer needs wide-format publication inputs, create **separate** `provor_cts4_pub_bbp_scales.csv` (or equivalent) for `bbp_original_scale`/`bbp_corrected_scale`; keep 4 legacy CSVs byte-identical. **MUST NOT copy synthetic `99999/88888` into `301_reference.csv`** — synthetics stay strictly in `provor_cts4_external_doxy_example.csv` (CORRECTION-3).
- [ ] Implement `writer/nc.py` with functions `write_meta`, `write_tech`, `write_profile(core/bgc)` — each conforming to §§1-17 tables; call-site validates WriterInputs and errors on fabricated WMO.
- [ ] Wire `cli` flag `--wmo <7-digit>` (no `--imei`) — error out if caller passes IMEI only.
- [ ] Add `bbp_mode` switch (default TELEMETRY_ORIGINAL for internal, INCOIS_CORRECTED for GDAC stage) with history entry citing `10.17882/54520` and `cook_bbp`.
- [ ] Add optional `doxy_external_calib.json` path — if missing/incomplete for an O2 float, writer preserves `C1PHASE/C2PHASE/TEMP_DOXY` intermediates but sets `DOXY(_ADJUSTED)=99999.0` with `QC=9` and logs `DATA-COVERAGE`; no fabricated Stern-Volmer coefficients (CORRECTION-6).
- [ ] Bring up FileChecker gated test (`file_checker`), align with ARGO Conventions 3.2 when spec rev advances.
- [ ] Shadow-run on real WMO `2902091` cycle 001: numeric parity — D/BD PRES vectors bit-identical to INCOIS D/BD; CHLA parity within `float32(0.0073)` ; BBP parity within `1e-12` in TELEMETRY_ORIGINAL and within `0.5*CORRECTED_scale` tolerance in INCOIS_CORRECTED.
- [ ] Keep Phase2B2 88-family-generic + 150 generic proofs green.

---

## Appendix A — Raw inspection excerpts (2026-09-10, netCDF4)

```
Meta 2902086 dims: N_PARAM 11, N_SENSOR 6, N_CONFIG 18 (UNLIMITED), N_LAUNCH_CONFIG 161, N_MISSIONS 3 (UNL)
  PARAMETER = [PRES, TEMP, PSAL, C1PHASE_DOXY, C2PHASE_DOXY, TEMP_DOXY, DOXY, FLUORESCENCE_CHLA, BETA_BACKSCATTERING700, CHLA, BBP700]

D 2902091_001 nc4 dims: N_PROF 4, N_PARAM 3, N_LEVELS 95, N_HISTORY 5, N_CALIB 1
  title Argo float vertical profile; institution INCOIS; source Argo float
  history 2023-08-07T18:23:37Z creation; 2023-08-11T13:32:23Z last update (coriolis COCD (V1.8) tool)
  references http://www.argodatamgt.org/Documentation; user_manual_version 3.1; Conventions Argo-3.1 CF-1.6; featureType trajectoryProfile
  FORMAT_VERSION 3.1; DATA_TYPE Argo profile file; DATA_MODE D R R R; STATION_PARAMETERS [[PRES TEMP PSAL],[PRES TEMP PSAL],[PRES],[PRES]]

BD 2902091_001 nc4 dims: N_PROF 4, N_PARAM 6, N_LEVELS 95, N_HISTORY 8, N_CALIB 2
  title / institution / Conventions as above; history … COPQ software
  DATA_TYPE B-Argo profile file; FORMAT_VERSION 3.1; DATA_MODE R R D A
  PARAMETER_DATA_MODE: (R R R R D --) / (R R R A A A)
  STATION_PARAMETERS: PRES only (prof1-2), PRES C1PHASE C2PHASE TEMP_DOXY DOXY (prof3), PRES FLUORESCENCE_CHLA BETA_BACKSCATTERING700 CHLA CHLA_FLUORESCENCE BBP700 (prof4)

Tech 2902091 nc4 dims: N_TECH_PARAM 1288, STRING128; PLATFORM_NUMBER 2902091; CYCLE_NUMBER int32 fill 99999
  TECHNICAL_PARAMETER_NAME[0]: CLOCK_FloatTime_YYYYMMDDHHMMSS …
```

*(Full dumps remain in workspace logs; not hard-coding beyond cited slices. Additional metas 2902087..2902120 mirror 2902086 structure; S/trajectory absent in mirror.)*

---

## Appendix B — Research evidence vs single-file inference guard

> Contract statements marked REFERENCE have multi-file evidence: 13 meta order consistency (5 sampled + `2902091_meta.json` Coriolis container), 2 profile types (D/BD), N_LEVELS derived per-cycle (not fixed), tech inventories from decArgo `_*tech*_301.csv`. Nothing is inferred from `2902091_001` alone. Where single-cycle mirror is the only BGC example, the limitation is tagged DATA-COVERAGE and the writer is designed to handle variable N_*.

---

*End of Phase 2C DESIGN ONLY. STOP — no writer code, no NetCDF generation, no 4-CSV mutation. Awaiting user green-light for Phase 3 implementation.*
