# PROVOR CTS4 (Coriolis decoder 301) — Phase-1 Design Note

**Date:** 2026-09-09 · **Status:** READ-ONLY design from collected evidence. No code written, no CSVs
modified, no products emitted, ARVOR-I/APEX untouched.
**CORRECTION (aq) 2026-09-09:** §§1, 4, 5, 6 superseded by first-party NKE byte authority
(`5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924` §7, preserved at `provor_bio_irsbd/ref/`);
corrections annotated inline, original text retained for history.
**Sources:** `PROVOR_BIO_IRSBD_PHASE0_INVESTIGATION.md`, log entries (aj)/(ak)/(al),
`provor_bio_irsbd/raw_telemetry/` (517 `.sbd`), vendored Coriolis container sources,
INCOIS GDAC inspections of 2902086–93 / 2902113/14/15/18/20 (see (ak) for full detail).

---

## 1. Confirmed generic packet/cycle relationship (observed family rule)

Measured over all 517 files / 5,359 packets; every file an exact multiple of 140 bytes
(420–1960). First byte values observed: ONLY `00 FA FC FD FE FF`.

| item | evidence |
|---|---|
| `FF` bytes7–10 (BE) | `0xCCCC0001` in ALL 270 tech files; low word constant `1` |
| `FE` bytes7–10 (BE) | `0xCCCC000A` in ALL 270 tech files; low word constant `10` |
| high word | cycle number, contiguous per group |
| **type-`00` byte3 == `FF` high word** | **0 mismatches / 138 tech+data files / 10 of 10 groups** |
| data-only files (246) | byte3 ⊆ group FF-cycles ∪ {0} — data-only files DO carry cycle |
| byte3max = FFmax−1 | all 10 groups (latest tech has no data yet) |
| tech-bearing files | 271; tech-less 246 (recount corrected aj's 245) |
| oddballs (8) | incl. ONE FE-without-FF file (`12170/..._000652.sbd`); must be tolerated, not hardcoded |

**CORRECTION (aq) 2026-09-09:** the byte3 key is SUPERSEDED. NKE §7 defines the cycle as
the u16be header field (type-`00` bytes2-3; 255/254 bytes7-8); byte2 is its high byte (0 for
all cycles < 256 in the corpus). File cycles are unanimous header cycles (514/517 files; 3
opaque-only files carry no decoder-visible cycle). Cycle 0 is genuine. The filename numeric
suffix is the Iridium MOMSN, never the cycle. The standing rule and UNKNOWN byte3=0 below
are retained for history and NO LONGER NORMATIVE.

**Standing rule (SUPERSEDED, see above):** byte3 was the family-generic cycle key. Phase-1 tests MUST re-validate the
0/138 relationship and the subset constraint on every run — it is an observed rule under
test, NOT a WMO/cycle hack. Do NOT hardcode the 00530 4-file tech/data rhythm (observed only).
**UNKNOWN:** byte3=0 population present in every tech+data file (semantics unresolved).

Packet-type naming caution (ak): reference 301 label tables route TECH←msg 253+250 and
CONFIG←msg 255+254+251, against aj's "255 tech#1 / 254 tech#2 / 253 param" shorthand.
Msg 251 (`0xFB`) NEVER appears in the 517 files. Naming to be re-examined against bytes.
RESOLVED (aq): NKE §7.2 names 255 = PV/PM mission parameters, 254 = PT technical
parameters, 253 = vector tech, 252 = pressure packet, 251 = sensor parameters
(sent only-on-modification — hence 0 observed), 250 = sensor tech. The 301 label tables
were right; the aj shorthand was inverted. The decoder uses NKE names.

## 2. Confirmed INCOIS reference contract (decoder 301 floats)

**Batches:** 2902086–93 (OIN-12IND-FLBB, launched Dec-12–Feb-13; FLBB-08 9th float unlocated;
2902116/117 absent) and 2902113/114/115/118/120 (OIN-13IND-S4, Nov-13–Mar-14).
Decoder 301 = Coriolis 5.8 = "PROVOR CTS4 (FLBB)", INCOIS DAC only, Iridium.

- **Platform/sensors:** `PLATFORM_TYPE=PROVOR_III`, `WMO_INST_TYPE=836`, `DAC_FORMAT_ID=5.8`,
  6 sensors: SBE41CP + AANDERAA OPTODE 4330 + ECO_FLBB (+pressure). No PPOX in GDAC.
- **Files:** `meta.nc`, `tech.nc` (95 rows/cycle, starts at cycle 1, NO cycle 0),
  `D*.nc` + `BD*.nc` (not R/BR — delayed-mode era files), `Rtraj.nc` **carries BGC**,
  **no `BRtraj` file**.
- **Structure:** D/BD `N_PROF=4` (primary / near-surface / 2 secondary), `N_LEVELS=95`,
  level-locked; PRES-only duplication in B; no `PRES_ADJUSTED` in B; `PARAMETER_DATA_MODE`
  present — matches UM 3.1 B-file rules.
- **BGC parameter inventory/order (11):** PRES, TEMP, PSAL, C1PHASE_DOXY, C2PHASE_DOXY,
  TEMP_DOXY, DOXY, FLUORESCENCE_CHLA, BETA_BACKSCATTERING700, CHLA, BBP700.
  DOXY = Stern-Volmer on C1−C2 with pressure + CalPhase terms.
- **Metadata/calib variables:** foil c0–c27, PhaseCoef0/1 + TempCoef (TempCoef per-float),
  CHLA SCALE/DARK, BB DARK/SCALE/khi/wavelengths, launch config 161 params (names identical
  across floats; only InternalPressureCalib1/2 + Optode/Flbb power modes differ).

**Generic vs float-specific split (measured on 3 floats):**

| generic (same all floats) | float-specific (differs) |
|---|---|
| foil c0–c27 IDENTICAL | TempCoef T0–T3 |
| CHLA SCALE 0.0073 | PhaseCoef0/1 |
| BBP khi 1.097 @142° | CHLA-DARK 48/50/49, BB-DARK 49/50/49 |
| launch-config names + ~all values | BB-SCALE 1.773/1.74/1.645e-6 |

**Conflicts — record only, resolve by authority, never by fiat:** container-JSON 2902091
(BB-SCALE 1.795e-6 / khi 1.076 / 124°) vs its meta.nc (1.773e-6 / 1.097 / 142°); meta.nc
internal LAUNCH FlbbBetaAngle=124 vs calib comment 142°; container JSON carries PPOX_DOXY,
GDAC has none; BD/Rtraj carry CHLA_FLUORESCENCE which meta.nc PARAMETER lacks (GDAC quirk
candidate — DO NOT COPY without UM authority).

## 3. Reverse-population: what is safe NOW (with provenance)

Provenance rule: every value records WMO/file/variable; family-generic vs float-specific
flagged at write time; no WMO-keyed decoder logic ever.

| CSV | SAFE now (generic, GDAC-evidenced) | FLOAT-SPECIFIC (per-float rows only) | UNAVAILABLE (leave null, never fabricate) |
|---|---|---|---|
| `meta.csv` | platform/sensor identity, PROJECT/owner, LAUNCH_* shape, makers/models (SBE41CP/AANDERAA-4330/ECO_FLBB), IRIDIUM | WMO, PTT, FLOAT_SERIAL_NO, LAUNCH position/date, serials | deploy-order no., np0, WMO↔IMEI link |
| `sensor-info.csv` | maker/model slots, comms=IRIDIUM | serial numbers (only FLBB serial evidenced) | SBE/pressure/oxy serials |
| `calib.csv` | foil c0–c27, CHLA SCALE 0.0073, khi 1.097 — AFTER schema work | TempCoef, PhaseCoef, all DARKs, BB-SCALE | — |
| `config_params.csv` | 301 names from label tables; values from meta.nc launch config | InternalPressureCalib1/2, power modes | full 161+7 inventory |

**Schema gaps (must precede any BGC writes):** `calib.csv` is SBE-ONLY today and CANNOT hold
BGC — needs new columns + conflict resolution; `config_params.csv` APEX/ARVOR columns are
insufficient — needs the 301 inventory. CTD coefs are 'none' everywhere (on-board conversion).
**Hard block:** WMO↔IMEI is NOT FIXABLE from available evidence (redacted names, no IMEI in
GDAC, container IMEI=PTT stub) — no output file may be named until authoritative metadata exists.

## 4. PSAL gate (RESOLVED (aq) — single encoding raw/1000)

PRE-CORRECTION RECORD (superseded): two apparent encodings (raw/1000 vs raw/1000+33),
both oceanographically valid-looking in their own records, unadjudicated — no Coriolis CTS4
scaling table found at the time.

RESOLUTION: NKE §7.2.4.1 specifies salinity in mPSU: **PSAL = S_raw/1000**, single encoding.
The `+33`/raw-1120–1170 population was FLBB chlorophyll raw (counts×10) pooled as CTD-S under
the wrong record frame — an artifact, not an encoding. Verified: all 18,547 non-padding CTD
records fall in raw S [31076, 36698] (31.076–36.698 PSU, Bay-of-Bengal↔Arabian dipole). The ARVOR
`ctd.py` fast-path remains decoder-2xx ONLY and NOT transferable to 301. No BGC calibration is
implemented in Phase 1.

## 5. Coriolis source status (TOOL-AVAILABILITY retained for byte decode)

Re-audited 2026-09-09. PRESENT: `decode_sbd_file_cts4.m` (confirms 140-byte framing,
1024→980 truncation, blank-row filtering — authoritative framing reference); `init_float_config_*`
(sensor IDs CTD=0/OPTODE=1/ECO=2–5, FoilCoef+TempCoef inventory); 2395-line BGC derived-parameter
module (C1/C2PHASE_DOXY + TEMP_DOXY → DOXY chain — reference for Phase 2+, post-decode only);
301 config/tech label tables (names + MSG routing, NO byte offsets/scaling); metadata generators.
ABSENT: `decode_prv_data_ir_rudics_cts4_*`, `get_decoded_data_cts4`, `process_profiles_*`
(all of `soft/sub/`); CTD value conversion itself (`sensor_2_value_*`) lives in the missing core;
all NKE manuals incl. CTS4 3.0x are 131-byte LFS pointers. Note the present test tool targets
decoders **111/113–116** (RUDICS), not 301 (SBD) — the 301 byte core was never in this slice.
**Byte-level 301 decode stays TOOL-AVAILABILITY. Telemetry-derived Phase 1 proceeds without it.**
CORRECTION (aq): CLOSED — the NKE 5.8 manual §7 (recovered via Wayback,
`provor_bio_irsbd/ref/`) is the first-party byte authority; Phase-1 geometry and scaling
now follow it.

## 6. Phase-1 implementation/test scope (proposed, NOT started)

**Pipeline:** raw `.sbd` → **framer** → **packet dispatch** → **cycle attribution** → **raw CTD
extraction**. Family-generic code only; no WMO/cycle branches; no ARVOR-I/APEX modification.

| module | does | does NOT do |
|---|---|---|
| framer | 140-byte rows, size validation, blank-row drop (Coriolis rule: all-0/all-26) | no interpretation |
| dispatch | route by byte0 (`00/FA/FC/FD/FE/FF`); type-`00` sub-route by byte1 (0/3/6); reject unknown first bytes loudly | no silent skips |
| cycle attribution | unanimous u16be header cycles (00@2-3, 255/254@7-8); multi-cycle recorded, never forced; filename MOMSN never used | no date invention; data-only JULD/position deferred (FIX CANDIDATE bracketing model, later) |
| raw CTD | stride-6 (P s16, T u16, S u16) records from offset 10; TEMP=(u16-2000)/1000, PRES=s16/10, PSAL=u16/1000 per NKE §7.2.4.1 | NO BGC unit conversion (counts only); no BGC calibration |

**Tests (all read-only vs workspace telemetry + committed fixtures):** framing multiples on all
517 files; dispatch census == 5,359 packets with exact per-type counts; header-cycle 1:1 verbatim
check + file unanimity (514/517, 0 conflicts); 250/252/253 raw-cycle consistency; oddball tolerance
(single-param files, byte5∈{0,6,9}); CTD geometry/scaling regression pins (start 10, P/T/S order,
T-2000, S/1000, header cycle, no MOMSN, no +33); CTD physical-plausibility bounds; PSAL
single-encoding pins (exact non-pad raw bands).

**Non-goals / exit criteria:** no `.nc` emission, no WMO naming, no BGC calibration, no JULD/
position synthesis, no CSV writes until schema gaps close. Exit = all tests green on the 517
workspace files + review of any byte3=0 semantics discovered along the way.

---

## Provenance appendix (evidence locations)

- Telemetry: `provor_bio_irsbd/raw_telemetry/` · Phase-0 report: `provor_bio_irsbd/…PHASE0…md`
- Baseline detail: `argo-decoder-python/IMPLEMENTATION_PROGRESS.md` entries (aj) 2026-09-09,
  (ak) 2026-09-09 · Smoke gate: (al) 2026-09-09 PASS
- Coriolis framing/init/derived sources: `…/decArgo_soft/soft/util/decode_meas_cts4/…`
- 301 label tables: `…/decArgo_soft/config/_configParamNames/_config_param_name_301.*`,
  `…/_techParamNames/_tech_param_name_301.*`
- GDAC refs used: INCOIS 2902086–93, 2902113/14/15/18/20 (official
  `https://data-argo.ifremer.fr/dac/incois/<WMO>/` route; inspection notes in (ak))
- First-party byte authority (aq): NKE `5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924` §7
  (`provor_bio_irsbd/ref/`, PDF+TXT+SHA256SUMS; recovered via Wayback 2026-09-09, live
  Coriolis URLs dead)
