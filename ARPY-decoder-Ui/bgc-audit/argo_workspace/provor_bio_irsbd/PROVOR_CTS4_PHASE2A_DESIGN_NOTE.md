# PROVOR CTS4 (Coriolis decoder 301) — Phase-2A Design Note

Status: COMPLETE 2026-09-09. Scope: Phase 2A ONLY — decode packets
250/252/253/254/255 per NKE 5.8, map fields to the 301 config/tech label
tables, decode observed BGC measurement packets (DOXY/optode, FLBB CHLA,
BBP700), build raw→calibrated equations, reverse-bootstrap coefficients
from INCOIS GDAC evidence. STOP LIST (not done, not started): NetCDF
emission, R/BD publication, WMO assignment, CSV-schema changes, final
publication decisions, broad decoder refactor.

Authority stack (project scientific rule): official Argo standards →
NKE spec → Coriolis/reference logic → raw telemetry → GDAC publication
behavior. GDAC is the publication/parity reference, never byte-scale
authority; known GDAC artifacts are never reproduced to kill diffs.

## 1. Packet layouts (NKE 5.8 Mut_ProvorBioII-FLBB)

All layouts §7.2.4.x of `5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924`
(extracted text at `/tmp/nke58_manual.txt`, NOT workspace-persistent;
section numbers are the durable citation).

* 255 mission (§7.2.4.4) → `params.decode_255` / `MissionParams`.
  PV section: n_durations=1, eol_period_min=60, second_session_wait_min=10
  fleet-wide; 5 duration blocks (first = mission period, rest 24 h,
  all ending 31/12/99). PM section: n_profiles=1,
  delay_before_mission (PM1: 0, 30 for group 17960), reference_day
  (PM2: 0/1, flips mid-life in 03530/06640); 10 profile blocks.
  PM5/PM6 are parking/profile depths read as **dbar** (wire 1000/2000
  in all 2700 slots; the manual labels them Bar but 1000/2000 Bar is
  unphysical and GDAC CONFIG pressures are dbar).
* 254 tech params (§7.2.4.5) → `params.decode_254` / `TechParams`
  (28 raw u16 PT0..PT27 + 74-byte zero spare).
* 253 vector tech (§7.2.4.6, 140 B) → `tech.decode_253` / `VectorTech`.
  Offsets verified to sum to 140 with a 33-byte zero spare.
* 252 pressure (§7.2.4.7) → `tech.decode_252`: cycle u16 + 27 samples
  × (phase, profile, is_pump, pressure_bar, reltime_min).
* 251 sensor params (§7.2.4.8) → `tech.decode_251`: up to 12 change
  records. ABSENT from the corpus (no 0xFB row in 517 files);
  unit-tested on synthetic fixtures only.
* 250 sensor tech (§7.2.4.9) → `tech.decode_250`: two 70-byte halves,
  each opening 0xFA + sensor id X at offset 1
  (0=CTD, 1=Optode, 4=FLBB, 0xFF=filler), free zone at offset 20
  (little-endian): CTD = 4 float32 (offset_p, p_sub, t_sub °C,
  s_sub PSU) + 34 spare; FLBB = serial u16 + scale_chl f32 +
  dark_chl u16 + scale_bb f32 + dark_bb u16 + scale_chl_2 f32 (=0)
  + 32 spare; Optode = 50 bytes raw (manual: empty).

## 2. Phase table (NKE §7.2.2) and the two-session scheme

Phases 0..16: 0 pre-mission, 1 surface, 2 init cycle, 3 init profile,
4 buoyancy reduction, 5 descent parking, 6 parking drift, 7 descent
profile, 8 drift profile, 9 ascent, 10 emergence, 11 data treatment,
12 satellite transmission, 13 end profile, 14 end of life,
15 emergency, 16 user dialog. PV2=10 (second_session_wait_min) arms
TWO SBD sessions per surfacing: session 1 → phase-1 253, session 2
(10 min later, with updated GPS fix per §7.4) → phase-12 253. This
explains the corpus 253 phase census {0:5, 1:132, 12:128, 16:5}
(alternating 1/12 per surfacing), type-0 phases {6,9} (drift/ascent
sampling), 252 phases {5,7,8,9,10} (hydraulic action phases), and
cycle-0 phase-0+16 bench rows.

## 3. BGC measurement packets and association

O2 (subtype 3) → `bgc.extract_o2`: 10 records × (P, C1, C2, T) +
10-byte zero tail. FLBB (subtype 6) → `bgc.extract_flbb`: 21 records
× (P, CHL, BB) + 4-byte zero tail. Scales: P=s16/10 dbar,
C1/C2=u16/100 deg, T=(u16−2000)/1000 °C... (NKE §7.2.4.2-3; CTD
P/T/S per the settled type-00 interpretation). `assoc.group_meas`
groups type-0 packets by (cycle, profile, phase); `nearest_ctd`
matches BGC records to CTD rows. The corpus holds NO type-0x01 rows
(dispatch raises on byte0==1, so this is enforced, not assumed).

## 4. Raw→calibrated equations (`equations.py`, pure math, no defaults)

DOXY (Aanderaa 4330 standard-foil; GDAC equation + Coriolis
`calcoxy_*` + oxy cookbook §4.2.2.1 agree term-for-term): TPHASE =
C1−C2; Phase_Pcorr = TPHASE + 0.1·P/1000; CalPhase cubic
(PhaseCoef0..3); 28-term foil polynomial (c/m/n); AirSat with
pVapour; Weiss Cstar (A0..A5) → MOLAR ×44.614; Garcia-Gordon-style
Scorr (B0..B3, C0, D0..D3, Spreset) × Pcorr (Pcoef2/3); DOXY =
O2/rho with EXPLICIT caller-supplied rho (potential density is a
Phase-2B publication input, not decoder state).
CHLA = (FLUO−DARK)·SCALE. BBP700 =
2π·khi·((BETA−DARK)·SCALE − BETASW700), BETASW700 from `beta_sw`
(scalar transcription of Coriolis `betasw_ZHH2009.m`, Zhang 2009,
depolarization 0.039). TEMP_DOXY T0..T5 NOT implemented by design
(optode-firmware-internal; telemetry T is already °C); coefs
preserved in the reference CSV only.

## 5. GDAC equation validation (INCOIS 2902091 cycle 1)

`scripts/probe_cts4_phase2a_gdac.py` recomputes BD/D values from raw
inputs. CHLA max diff 1.192e-07 µg/L, BBP700 5.355e-09 m-1,
implied-βsw vs `beta_sw` 7.676e-10 (independent Zhang confirmation):
EXACT. DOXY: 91 clean levels + 3 garbage levels (L63/64/65 keep the
same garbage structure as the literal chain); clean residual max
0.5157 / mean 0.2571 / median 0.1881 µmol/kg with fitted signature
gain 1.001708 / offset +0.2076 µmol/L. Elimination ruled out CTD-vs-
optode T (±0.04 °C identical), S matchup (±0.05 PSU → 0.03%),
rho/EOS (would need 2.7 kg/m³), C1 offset, float32 rounding;
residual is post-foil additive. `equations.py` stays meta.nc-literal;
the gap is PUBLICATION-RTQC, explicitly unresolved, never fitted.
(SAGEO2 `DOXY_ADJUSTED = DOXY×1.167` is a separate delayed-mode
gain, unrelated to the RT residual.)

## 6. Corpus adjudication ledger (517 files, probes of 2026-09-09)

* Census: 255=254=253=270, 252=201, 250=256; measurement 3969
  (CTD 975, O2 2001, FLBB 993); all spare/tail checks pass 100%.
* Hours are MINUTES (u16 minutes-since-midnight, NKE "resolution: 1
  minute"): max 1392, 345/2700 slots impossible as HHMM.
* 253 fill rule (EXACT, 0 breaks/270): session-1 vectors carry fill
  pressure extremes (min 250 / max 0); session-2 (phase-12) vectors
  carry real ones — extremes are latched during phase-11 data
  treatment between sessions. Mission phase-12 ranges: park 40–107
  (shakedown cycles dive shallow), profile 182–201, stab 0–106.
* Bench rows: 18 cycle-0 253s; phase ∈ {0,16} ⟺ cycle 0 for those 10;
  4 cycle-0 phase-12 rows carry shallow bench extremes (min_park 1).
* 253 identity: 1:1 serial per group (1301/1302/1303/1305/1306/
  1206/1204/1202/1201/1203); vacuum raw 126–151 (×5 = 630–755 mbar);
  battery raw {0:5 bench} + 45–57 (≈9.3–10.5 V); GPS 265/270 valid
  (Indian-Ocean tracks); rtc flag 0 in ALL 270 (GDAC publishes 1 —
  UNRESOLVED); remote (2,0) in 4 vectors; no grounding/emergency.
* 255: first-period {24,120,240} h; 00530/03530/03580 changed
  daily→10-daily mid-life; per-group profile-1/surfacing slots and
  (PM0,PM1,PM2,PV1,PV2) heads pinned (PM1=30 only 17960; PM2 flips
  0→1 in 03530/06640).
* 254: PT0–PT25 constant fleet-wide
  [2700,15,60,2,30,400,2000,40000,30,2100,4,8,2,0,100,200,50,50,30,
  0,10,83,90,10,0,10]; one PT26/PT27 pair per group (10 pairs).
* 252: 5427 samples / 3767 nonzero / 1654 pump; phases {5,7,8,9,10};
  profile always 0; P ≤ 201 Bar.
* 250: pairing (CTD,Optode):128 + (FLBB,filler):128 files; 384
  present halves, status all 1; tx descent 0, drift ∈ {1,2}, ascent
  ∈ {1,2,4,6,7,11,13,14,15} (modes 7/15); CTD free bounds
  off_p ±1, p_sub ≤7, t_sub ≤40 °C, s_sub ≤45 PSU; FLBB serials
  1:1 per group (3042/3043/3044/3046/3065/2663/2661/2659/2658/2660),
  scale_chl 0.0073 universal, scale_chl_2 = 0, 10 distinct scale_bb;
  Optode free = per-group-constant LE u16 + 48 zeros (pattern set
  {0x0506,0x0508,0x050D,0x050F,0x0531,0x0466,0x02CE,0x02C6,0x017A,
  0x02C8}; group pairing NOT pinned — encounter-order inference).
* 250/253 cycle membership: 378/378 in files carrying 253s; two
  06580 files (cycles 16/32) carry 250s with no 253 (SBD
  fragmentation across messages). (Supersedes the interim "384/384"
  claim, which missed the fragmented pair.)
* BGC: O2 20010 recs / 1371 pad, C1 29–71°, C2 1–10°, T 1–32 °C;
  FLBB 20853 / 2134 pad, fluorescence 25.0–469.8, backscatter
  7.0–1670.6 counts; dates 2014-02/05; all tails zero.
* Association: 618 groups, 248 with CTD; type-0 (subtype,phase)
  census {(0,6):124,(0,9):851,(3,6):165,(3,9):1836,(6,6):128,
  (6,9):865}.

## 7. 301 label-table mapping (`labels_301.py`)

Verbatim authority: container `_config_param_name_301.csv` (82) +
`_tech_param_name_301.csv` (64). Coverage: 23 PT (unmapped 19,20,23,
24,25 — no 254 label), 8 PM, 23 PV slots, 51 253-fields; all config
labels covered. `FLAG_SensorBoardStatus_NUMBER` (msg 253) has NO 253
wire field — the 140-byte budget is exhausted — presumably derived
from 250 statuses by an UNKNOWN rule (UNRESOLVED). Derived-only
labels (FloatTime formatting etc.) are excluded from coverage by
construction, not by failure.

## 8. Metadata decision

The four CSV schemas are FROZEN and byte-untouched: they are an
APEX/ARVOR-I backend whose join test pins the exact 15-WMO list and
requires every WMO to join across all four sheets. CTS4 rows cannot
join honestly — `calib.csv` is SBE-polynomial-only and no
authoritative source publishes CTS4 SBE41CP coefficients (GDAC
lists the CTD serial as n/a) — and partial rows would be silently
dropped by the join, i.e. dead authority. EXPECTED, not a gap.
All reverse-bootstrapped values live in the NEW dedicated
`config/metadata/provor_cts4_301_reference.csv` (schema:
scope,wmo,sensor_model,sensor_serial,parameter,coefficient,value,
source_file,source_variable,interpretation): 118 coefficients × 13
INCOIS 301 floats = 1534 rows, every row carrying WMO + source file
+ variable + interpretation. Scope rule: family_generic ⟺
numerically identical in all 13 meta.nc → 88 generic (Spreset,
Pcoef1/2/3, B0-3, C0, A0-5, D0-3, PhaseCoef2/3=0, all 56 m/n
exponents, c21-27=0, T4/5=0, SCALE_CHLA, khi) vs 30 float-specific
(PhaseCoef0/1, c0-20 in ~4 foil batches, T0-3 per-unit, DARKs,
SCALE_BBP per-unit). Note: m/n VALUES are generic but two floats
(2902089, 2902093) print them in scientific notation — verbatim
strings preserved, comparison is numeric. Equations are identical
strings in all 13 files. TEMP_DOXY T0-5 included reference-only.

## 9. Serial corroborations (evidence, NOT WMO assignment)

No WMO mapping was performed (stop list). Noted for Phase 2B: 8 of
10 SBD groups share their FLBB serial with one of the 13 GDAC
floats (e.g. 00530↔2902115/3042, 06580↔2902114/3046,
06640↔2902118/3065, 12170↔2902086/2663, 17960↔2902093/2661,
20000↔2902092/2659, 25980↔2902087/2658, 29030↔2902088/2660);
GDAC optode serials 1295/1329 exactly match two SBD Optode lead-u16
patterns, 1293/1294 are adjacent, and groups 06580 (FLBB 3046 +
pattern 1295) and 06640 (FLBB 3065 + pattern 1329) double-match
2902114/2902118 — supporting (not proving) the lead-u16-as-serial
hypothesis. GDAC optode serial is otherwise n/a.

## 10. Unresolved items (mismatch classes)

* PUBLICATION-RTQC: DOXY +0.21 µmol/L-style INCOIS adjustment (§5).
* UNKNOWN: 173 FLAG_SensorBoardStatus derivation; 253 rtc 0-vs-1;
  03530 cycle-9 stab latched 0 (single field); Optode lead-u16
  = serial (supported hypothesis); PT26 (÷1000 strong hypothesis,
  1442–1776 → 1.4–1.8 units?) and PT27 (magnitude matches GDAC
  coef2 ~442 but mapping unproven).
* EXPECTED: 4-CSV non-population (§8); 251 absent from corpus
  (synthetic tests only); TEMP_DOXY reference-only; SBE41CP
  coefficients unavailable anywhere authoritative.
* DATA-COVERAGE: none outstanding within 2A (13/13 meta.nc local).
* FIXABLE/FIX CANDIDATE/NOT FIXABLE: none arising in 2A.
* PT12 raw = 2 (254-phase-TX-count) is a semantic conflict between
  NKE text and wire value; pinned as-is, flagged for the manual
  errata watch, NOT a decoder issue.

## 11. Test inventory

* `tests/unit/test_provor_cts4_phase2a_units.py`: 27 tests —
  synthetic layout/equation units, 2902091 GDAC vectors, 3 reference-
  CSV integrity tests (schema+provenance, scope-label audit,
  agreement with validated constants).
* `tests/test_provor_cts4_phase2a_telemetry.py`: 16 integration tests
  pinning §6 + label coverage (marked `integration`).
* Full suite 2026-09-09: 2216 passed, 1 skipped (pre-existing
  structural-parity skip). Phase 1 untouched and green.

## Provenance appendix

NKE 5.8 §7.2.2/§7.2.4.x (section citation; extracted text
ephemeral). Container label tables
`decArgo_soft/config/_configParamNames/_config_param_name_301.csv`,
`.../_techParamNames/_tech_param_name_301.csv`. Cookbooks
`provor_bio_irsbd/ref/cook_oxy.pdf`, `cook_bbp.pdf`, manual
`argo_user_manual.pdf`. GDAC refs
`provor_bio_irsbd/ref/gdac_incois_301/` (13 `incois_*_meta.nc`,
`incois_2902091_tech.nc`, `incois_BD2902091_001.nc`,
`incois_D2902091_001.nc`). Coriolis `betasw_ZHH2009.m`,
`calcoxy_*.m`, `decode_sbd_file_cts4.m`. Implementation
`src/argo_decoder/platforms/provor_cts4_ir_sbd/`
(params/tech/bgc/equations/assoc/labels_301). Validator
`scripts/probe_cts4_phase2a_gdac.py`. Corpus
`provor_bio_irsbd/raw_telemetry/SBD-BGC-raw` (517 files, 10 groups).
