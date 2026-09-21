# PROVOR-Bio IrSBD — Phase 0 family / decoder / publication investigation

**Date:** 2026-09-09 · **Analysis only — no implementation.** ARVOR-I frozen code untouched.
**Raw bundle preserved at:** `provor_bio_irsbd/raw_telemetry/` (517 `.sbd` + original archive)

> **No parity claimed. Family not declared complete.** This is the first analysis pass.

---

## 1. Family definition

| Attribute | Finding | Evidence |
|---|---|---|
| Manufacturer / family | **NKE PROVOR CTS4** (BGC "Bio" variant) | Coriolis `generate_json_float_meta_prv_cts4_ir_sbd.m` — the only vendored generator matching *PROVOR + Iridium-SBD + BGC* |
| Telemetry | **Iridium SBD**, binary `.sbd` only | 517 files, no `.eml` |
| **Frame size** | **140 bytes** (ARVOR-I is 100) | every file is an exact multiple of 140 |
| Byte order | **little-endian** floats; big-endian 16-bit counters | proven §3.3 |
| Floats in bundle | **10** (IMEI-suffix dirs `00530, 03530, 03580, 06580, 06640, 12170, 17960, 20000, 25980, 29030`) | — |
| Coverage | ~8–19 cycles each; 2014 era | §3.4 |
| CTD | SBE41-class, T/S/P triplets | §3.3 |
| **BGC suite** | **DOXY-class + 2 optical channels (FLBB: CHLA + BBP700)** — uniform across all 10 floats | §3.3, §3.5 |

**Naming note.** The task calls this "Provor-Bio". The Coriolis/Argo designation for this
hardware+telemetry combination is **PROVOR CTS4 Ir-SBD**. Treated as the same family; the
decoder profile class should be named from the CSV signature, not from either label.

### ⚠️ Variant caution
All 10 floats show the **same three data kinds**, so this bundle evidences **one variant
only**. NKE BGC floats also ship with NITRATE (SUNA), pH, CDOM and radiometry. **Do not
generalise this sensor suite to the family.** Variant detection must be data-driven.

---

## 2. Raw packet map (derived from telemetry, not assumed)

Every file is a whole number of 140-byte packets. **Byte 0 = packet type.**

| Type | Count | Role | Cycle field | Notes |
|---|---|---|---|---|
| `0xFF` 255 | 270 | Technical #1 | **byte 8** | bytes 1–6 = `DD MM YY HH MM SS` |
| `0xFE` 254 | 270 | Technical #2 | **byte 8** | same date header |
| `0xFD` 253 | 270 | Parameter / config | **byte 10** | |
| `0xFC` 252 | 201 | Parameter / config #2 | **byte 10** | |
| `0xFA` 250 | 256 | **Calibration / surface block** | — | little-endian float32 payload |
| `0x00` 0 | **4 092** | **Measurement data** | — | sub-typed by byte 1 |

**Date header proven:** `11 02 0e 0a 37 09` → 17/02/2014 10:55:09, consistent across floats
and monotonic with directory dates.

### Type-0 sub-types (byte 1) — the sensor discriminator

| byte1 | Count | Stream | Record layout (stride **6**, from offset 12) |
|---|---|---|---|
| **0** | 1 098 | **CTD** | `T=u16/1000` °C · `S=u16/1000` PSU · `P=u16/10` dbar |
| **3** | 2 001 | **DOXY-class** (paired rows) | alternating rows; non-zero col A ≈ 7.47–8.17 |
| **6** | 993 | **Optics (FLBB)** | two channels 0.50–3.71 · shared `P=u16/10` |

Byte 3 is a within-cycle sequence counter.

---

## 3. Decoded telemetry evidence

### 3.1 CTD (byte1 = 0) — physically validated
| Float | T (°C) | S (PSU) | P (dbar) | n |
|---|---|---|---|---|
| 00530 | 4.656 – 21.062 | 34.300 – 35.381 | 0.0 – 1962.8 | 2 596 |

Deep values ~0.53 °C / ~34.13 PSU at 1500–2000 dbar (using the +33 PSU offset form,
§3.2) are textbook Southern-Ocean deep water. Pressure decreases monotonically by
~25 dbar per record on ascent. **CTD decoding is solved.**

### 3.2 Two salinity encodings observed
Some records give `S = raw/1000` directly (34.3–35.4). Others need `S = raw/1000 + 33`
(raw 1120–1170 → 34.12–34.17). Both yield oceanographically correct values in their own
records. **This must be resolved against the Coriolis CTS4 scaling table before
implementation — it is currently UNKNOWN and is a decoding risk, not a cosmetic detail.**

### 3.3 Calibration block (type 250) — little-endian float32
`00530`: `[-0.06, 5.4788, 16.5029, 34.9289]` · `12170`: `[0.15, 6.2541, 26.2277, 32.2986]`

Reads as *(pressure offset dbar, ~5–6 dbar, temperature °C, salinity PSU)* — a surface or
park reference set, **plus embedded per-float coefficients**. Byte 13 varies (1, 8, 18)
and correlates with float — a probable **sensor/variant id**. Critical: this means **some
calibration data is available from telemetry**, reducing (not removing) CSV dependence.

### 3.4 Cycle census

| Float | cycles w/ data | example range |
|---|---|---|
| 00530 | 18 | 0–18 |
| 03530 | 14 | 0–14 |
| 03580 | 13 | 0–13 |
| 06580 | 18 | 16–34 |
| 06640 | 6 | 1–8 |
| 12170 | 16 | 98–114 |
| 17960 | 9 | 44–53 |
| 20000 | 9 | 45–54 |
| 25980 | 16 | 116–132 |
| 29030 | 8 | 43–51 |

Partial lifetimes, as stated. Several floats start mid-life (98, 116) — **no cycle-1
context**, so first-descent/launch-derived values are unavailable for those.

### 3.5 ⚠️ Open problem: cycle attribution for data-only files

**245 of 517 files (47 %) contain no tech packet.** With no `.eml` session headers, the
only temporal keys are the directory date (`YYYYMMDD`) and the `momsn` in the filename.

Attribution therefore needs a momsn/date ordering model equivalent to ARVOR-I's
mail-store logic. **This is the single largest decoder unknown** and directly determines
whether profiles can be assembled correctly. It must be solved in Phase 1.

---

## 4. Coriolis decoder map — partial, and honestly limited

| Need | Status |
|---|---|
| `generate_json_float_meta_prv_cts4_ir_sbd.m` | ✅ present (metadata JSON generator) |
| Sensor list / calib-coef file references | ✅ referenced (FLBB, DOXY paths) |
| **Core CTS4 SBD packet decoders (`sub/decode_*`)** | ❌ **ABSENT from the container** |

The vendored container ships `util/` and `util2/` only — the same gap hit on ARVOR-I,
where the needed `.m` files had to be sourced separately into
`tests/data/arvor_i/coriolis_src/`. **The equivalent CTS4 sources must be obtained before
the packet map can be validated against the reference decoder.** Until then the map in §2
rests on telemetry evidence alone: strong for CTD, provisional for BGC scaling.

---

## 5. GDAC publication contract

### 5.1 ⚠️ No BGC reference products exist in the workspace
Scanned **516 `.nc` files**: **zero** contain `DOXY`, `CHLA`, `BBP700`, `NITRATE` or
`PH_IN_SITU_TOTAL`. There are **no BR/BD files at all**.

**The R/BR publication contract cannot be pinned to actual INCOIS products yet.** The
rules below come from the current standard; the *specific INCOIS realisation* — exactly
which parameters they publish for this family — is **BLOCKED until GDAC BGC references
are supplied**.

### 5.2 What the standard requires (Argo User's Manual **3.44.0**, §2.6)

> "A B-Argo profile/trajectory file contains all the parameters from a float, **except the
> core-Argo parameters temperature, salinity, conductivity (TEMP, PSAL, CNDC)**. A float
> that performs only CTD measurements does not have B-Argo data files."

| Rule | Source | Consequence |
|---|---|---|
| `PRES` is the **only** parameter duplicated in core and B files | §2.6.1 | our BR must carry PRES |
| `PRES_ADJUSTED`, `PRES_QC`, `PROFILE_PRES_QC`, `PRES_ADJUSTED_ERROR` **not** duplicated in B | §2.6.1 | must be omitted from BR |
| Same `N_PROF`, same order, same PRES levels in both | §2.6.1 | R and BR are level-locked |
| `PARAMETER_DATA_MODE(N_PROF, N_PARAM)` required in B files | §2.6.4 | per-parameter R/A/D |
| `N_PARAM` = max parameters per pressure sample, not total unique | §2.6.5 | |
| B PARAM split into 3 groups (ocean-state / intermediate / raw) with differing QC obligations | §2.6.6 | governs which `_ADJUSTED`/`_QC` exist |
| `PARAMETER`/`PARAMETER_SENSOR` widened to 64/128 chars | §2.6.7 | |
| `DATA_TYPE` widened 16→32 chars | §2.6.8 | |
| Naming: `R<WMO>_NNN.nc` core, `BR<WMO>_NNN.nc` BGC | §2.7 / ref table 1 | |

---

## 6. Parameter derivation mapping — current state

| GDAC param | File | Telemetry source | Conversion | Derivable **now**? |
|---|---|---|---|---|
| `PRES` | R + BR | type-0 col C | `u16 / 10` dbar | ✅ **Yes** — proven |
| `TEMP` | R | type-0 k0 col A | `u16 / 1000` °C | ✅ **Yes** — proven |
| `PSAL` | R | type-0 k0 col B | `/1000` **or** `/1000 + 33` | ⚠️ **scaling ambiguity (§3.2)** |
| `DOXY` | BR | type-0 k3 col A | **unknown** — raw 7.47–8.17 | ❌ needs calib + Coriolis eq |
| `CHLA` | BR | type-0 k6 ch1 | needs `SCALE_CHLA`, `DARK_CHLA` | ❌ **BLOCKED — calib.csv** |
| `BBP700` | BR | type-0 k6 ch2 | needs χ, dark counts, angle | ❌ **BLOCKED — calib.csv** |
| `*_QC` | both | RTQC stage | ref table 2 | ⚠️ Phase 5 |
| `*_ADJUSTED*` | R core only | — | — | R-mode ⇒ fill |
| All identity/metadata | R + BR | — | — | ❌ **BLOCKED — four CSVs** |

**Honest position: only PRES and TEMP are fully proven today.** PSAL has a resolvable
ambiguity. No BGC parameter can be converted to physical units without calibration
coefficients — raw counts alone are not publishable.

---

## 7. What is blocked, and by what

### BLOCKED — four CSVs absent
`PLATFORM_NUMBER` (we have IMEI suffixes, **not WMO**), `DATA_CENTRE`, `PI_NAME`,
`PROJECT_NAME`, `PLATFORM_TYPE`, `FLOAT_SERIAL_NO`, `WMO_INST_TYPE`, `LAUNCH_*`,
`SENSOR*`, `PARAMETER_SENSOR`, `PREDEPLOYMENT_CALIB_*`, `CONFIG_*`, and **all BGC
calibration coefficients** (CHLA scale/dark, BBP χ, DOXY coefficients).

**Without WMO we cannot even name an output file** (`R<WMO>_NNN.nc`). This blocks *all*
product generation, not merely metadata fields.

### BLOCKED — GDAC BGC references absent
The exact INCOIS R/BR published parameter set. Cannot satisfy "no less, no extra" without
seeing a real BR file for this family.

### BLOCKED — Coriolis CTS4 decoder sources absent
Validation of the BGC packet map and the official conversion equations.

### UNKNOWN — needs investigation
PSAL scaling (§3.2) · exact type-3 quantity (DOXY? C1PHASE? TPHASE?) · type-250 byte-13
sensor id · cycle attribution for 47 % data-only files (§3.5) · descent vs ascent
discrimination · whether these floats have a `_prof.nc` multi-profile obligation.

---

## 8. Phased implementation plan

### Phase 1 — family detection + telemetry parser · **IMPLEMENT NOW**
- 140-byte framer; packet-type dispatch (255/254/253/252/250/0).
- Date header decode (proven).
- Type-0 sub-type routing by byte 1; 6-byte record iterator.
- CTD conversion (PRES, TEMP proven; PSAL behind a resolved-scaling gate).
- **Solve cycle attribution for data-only files** (§3.5) — highest-value unknown.
- Family detection driven by observed sub-types, **not** hard-coded to this suite.
- Pure decoder + unit tests against these 517 files. **No NetCDF output yet.**

### Phase 2 — core R profile · **PARTIALLY BLOCKED**
Level assembly and pressure-axis logic can be built and tested now.
**Blocked on WMO/metadata for actual file emission.**

### Phase 3 — BGC BR profile · **BLOCKED**
Structure (PRES-only duplication, `PARAMETER_DATA_MODE`, N_PARAM rules) can be
implemented against UM §2.6. **Values blocked on calibration coefficients.**

### Phase 4 — metadata integration · **BLOCKED until four CSVs arrive**
Extend the existing four-CSV loader with BGC sensor/calibration columns.
**`registry.csv` remains forbidden.**

### Phase 5 — RTQC · **PARTIALLY BLOCKED**
Core tests reuse the existing engine. BGC tests (CHLA 57/59, BBP, DOXY 56/57) need the
BGC QC manuals **and** real values, so they follow Phase 3.

### Phase 6 — GDAC parity · **BLOCKED until BGC references arrive**

---

## 9. What additional inputs would unblock most

1. **The four CSVs** (or any authoritative WMO↔IMEI map + BGC calibration) — unblocks Phases 2–4. *Highest value.*
2. **INCOIS BR/R reference files** for one float of this family — defines the publication contract.
3. **Coriolis CTS4 `sub/decode_*.m`** — validates the BGC packet map and conversion equations.
4. **Any `.eml` session headers** for these floats — would resolve §3.5 outright.
5. Telemetry from a float with a **different BGC suite** (NITRATE/pH) — proves variant handling.

---

## 10. Recommended order

1. Resolve **PSAL scaling** and the **cycle-attribution model** (both from existing data).
2. Build the Phase-1 parser + tests — the only substantial work fully unblocked today.
3. In parallel, request the four CSVs and one INCOIS BR reference.
4. Only then attempt R, and after that BR.

**Do not generate any product until a WMO is available from an authoritative source.**
Deriving one from the IMEI suffix would be fabrication.

---

## 11. Status

| Item | State |
|---|---|
| Family identified | ✅ PROVOR CTS4 Ir-SBD, BGC variant |
| Packet map | ✅ types + cycle fields + date header proven; BGC scaling provisional |
| CTD decoding | ✅ PRES, TEMP proven; PSAL ambiguous |
| BGC decoding | ⚠️ streams located, **values not convertible without calibration** |
| GDAC contract | ❌ standard known; **INCOIS realisation unknown** |
| Parity | ❌ **not claimed, not attempted** |
| Family complete | ❌ **no** |
