# PROVOR CTS4/BGC — 10-Float Generic Family Decoding + Direct GDAC Parity

**Date:** 2026-09-11
**Scope:** All ten supplied raw PROVOR-Bio/CTS4 SBD groups through one
production code path.

Two conclusions are kept strictly separate throughout, and must not be merged:

- **Generic family decoding — all 10 floats.**
- **Direct R/BR GDAC parity — 2902093 only.**

All ten groups are the same **decoder-301 / NKE 5.8** family. CTD / O2 / FLBB
are internal sensor *packet subtypes*, not separate float families, so no
group receives family-specific handling.

---

## 1. Conclusion A — Generic family decoding: all 10 floats

### 1.1 The 10-float genericity matrix

`raw SBD → generic CTS4 decoder → calibration resolution → R/BR + meta +
tech + Rtraj`, executed by `scripts/run_cts4_realtime_fleet.py`
(`/tmp/cts4_fleet4`).

| raw group | FLBB serial | packet coverage (CTD/O2/FLBB/253) | cycles | published | R | BR | meta | tech | Rtraj | FileChecker | WMO-specific branch? | GDAC R/BR available? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 00530 | 3042 | 2596 / 2571 / 2574 / 38 | 19 | 17 | 17 | 17 | ✔ | 1805 | 858 | ACCEPTED | **no** | no (714 BD) |
| 03530 | 3043 | 2025 / 2009 / 2010 / 29 | 15 | 0 | – | – | – | – | – | n/a | **no** | no WMO at all |
| 03580 | 3044 | 1843 / 1814 / 1808 / 28 | 14 | 0 | – | – | – | – | – | n/a | **no** | no WMO at all |
| 06580 | 3046 | 2586 / 2424 / 2431 / 36 | 19 | 18 | 18 | 18 | ✔ | 1805 | 1067 | ACCEPTED | **no** | no (852 BD) |
| 06640 | 3065 | 1095 / 1087 / 1088 / 22 | 8 | 7 | 7 | 7 | ✔ | 760 | 396 | ACCEPTED | **no** | no (783 BD) |
| 12170 | 2663 | 2269 / 2342 / 2289 / 32 | 17 | 15 | 15 | 16 | ✔ | 1615 | 944 | ACCEPTED | **no** | no (732 BD) |
| **17960** | **2661** | 1458 / 1450 / 1452 / 18 | 10 | 9 | 9 | 9 | ✔ | 950 | 471 | ACCEPTED | **no** | **yes (702 R / 468 BR)** |
| 20000 | 2659 | 1453 / 1443 / 1444 / 18 | 10 | 8 | 8 | 8 | ✔ | 950 | 461 | ACCEPTED | **no** | no (446 BD) |
| 25980 | 2658 | 2258 / 2337 / 2341 / 32 | 17 | 15 | 15 | 16 | ✔ | 1615 | 938 | ACCEPTED | **no** | no (969 BD) |
| 29030 | 2660 | 964 / 1162 / 1282 / 16 | 9 | 6 | 6 | 8 | ✔ | 855 | 463 | ACCEPTED | **no** | no (684 BD) |

Totals: **517 SBD files**, **8 of 8 resolvable floats published**,
**218 netCDF products**, **218/218 FILE-ACCEPTED, 0 errors**.

`tech` = rows; `Rtraj` = measurements. Every published float carries exactly
one `meta`, one `tech`, one `Rtraj`, and **zero D/BD files**.

### 1.2 Proof that the decoder path is identical across all 10 groups

`scripts/prove_cts4_generic_path.py`, and permanently enforced by
`tests/test_provor_cts4_fleet_genericity.py` (8 tests).

**A. Static — no float-identity branch exists.**
AST scan of all 21 modules in
`src/argo_decoder/platforms/provor_cts4_ir_sbd/`:

```
modules scanned        : 21
conditional nodes      : 692
float-identity branches: 0
```

The scan tests every `if` / conditional-expression / `match` subject /
comparison operand for a literal matching any WMO (`2902xxx`), IMEI suffix
(`00530`…`29030`), or FLBB serial (`2658`…`3065`). **Zero matches.** The
float identifiers that do appear in those files are all inside comments and
docstrings as evidence citations.

**B. Dynamic — every published group records the identical call trace.**
The production entry points were wrapped to record the ordered call sequence:

```
00530: decode_group -> resolve_group -> build_external_meta_from_gdac -> process_float -> decode_group
06580: decode_group -> resolve_group -> build_external_meta_from_gdac -> process_float -> decode_group
06640: decode_group -> resolve_group -> build_external_meta_from_gdac -> process_float -> decode_group
12170: decode_group -> resolve_group -> build_external_meta_from_gdac -> process_float -> decode_group
17960: decode_group -> resolve_group -> build_external_meta_from_gdac -> process_float -> decode_group
20000: decode_group -> resolve_group -> build_external_meta_from_gdac -> process_float -> decode_group
25980: decode_group -> resolve_group -> build_external_meta_from_gdac -> process_float -> decode_group
29030: decode_group -> resolve_group -> build_external_meta_from_gdac -> process_float -> decode_group

groups reaching publication : 8
distinct traces             : 1
RESULT: static=PASS dynamic=PASS
```

**One distinct trace across eight floats.** Any per-float divergence would
appear as a second trace; none did.

### 1.3 The only permitted per-float variation

Every difference between floats comes from that float's own telemetry or from
externally supplied authoritative metadata — never from code:

| source | what it supplies |
|---|---|
| telemetry msg-250 `FlbbFree` | FLBB serial, `DARK_CHLA`, `SCALE_CHLA`, `DARK_BB`, `SCALE_BB` |
| telemetry msg-250 `CtdFree.p_sub` | pump-cutoff depth → primary/near-surface split |
| telemetry msg-253 | cycle numbering, event times, GPS, mission counters |
| INCOIS `meta.nc` (external) | WMO, launch config, PI, DOXY foil/phase coefficients |
| `provor_cts4_301_reference.csv` | FLBB serial → WMO, and DOXY coefficients for floats whose telemetry does not carry them |

`SCALE_CHLA` is `0.0073` on all ten (family-generic). `SCALE_BB` differs on
all ten — 1.384e-06 to 1.883e-06 — which demonstrates the value is read from
telemetry rather than hard-coded. Ten distinct FLBB serials, no collision.

**WMO resolution.** `WMO = FLBB_serial → authoritative metadata`. The IMEI
suffix is never mapped to a WMO, and `process_float` rejects any non-7-digit
WMO. Groups 03530 (serial 3043) and 03580 (serial 3044) have **no row in any
INCOIS `meta.nc`** — verified by reading `SENSOR_SERIAL_NO` on the ECO_FLBB
rows of all 13 available INCOIS meta files. They are therefore reported as
DATA-COVERAGE and publish nothing, rather than being given an invented WMO.

### 1.4 FileChecker v3.0.5 on the full fleet

Re-confirmed as the latest release via the GitHub releases API this session.
Jar sha256 `f6c2233f8cb42c70c4cade036fd64483919d456f6eccd5904a4507a7ec60c72c`.

```
java -jar file_checker_exec-3.0.5.jar -text-result -internal-specs incois <out> <in>
```

**218/218 FILE-ACCEPTED, 0 errors, 8 warnings.**

| product | files | warnings | files with errors |
|---|---|---|---|
| R | 95 | **0** | 0 |
| BR | 99 | **0** | 0 |
| tech | 8 | **0** | 0 |
| Rtraj | 8 | **0** | 0 |
| meta | 8 | 8 | 0 |

The 8 remaining warnings are one `PI_NAME : 'M Ravichandran' Status: Invalid
(not in NVS R40 table)` per meta file. Our `PI_NAME` is **byte-identical to
GDAC's own** `2902093_meta.nc` value, so the warning fires on the reference
product too. Classification: **EXPECTED**.

> **Correction to an earlier claim.** I previously reported "21/21 ACCEPTED,
> 0 errors, 0 warnings". That was wrong: I parsed the wrong section names
> (`ERRORS:`/`WARNINGS:` instead of `FORMAT-ERRORS:`/`FORMAT-WARNINGS:`) and
> silently saw nothing. The true starting figure was **1188 warnings**, all
> genuine. See §3.

---

## 2. Conclusion B — DIRECT GDAC PARITY: 2902093 ONLY

**This is a single-float result. It is not fleet-wide GDAC parity and must
not be reported as such.**

2902093 (group 17960) is the only WMO in the INCOIS fleet whose live
directory publishes real-time R and BR profiles. Comparisons are keyed by
`(cycle, profile)` and `(cycle, MC)`, never by array position. References
re-fetched from `https://data-argo.ifremer.fr/dac/incois/2902093/`.
Enforced by `tests/test_provor_cts4_direct_gdac_parity.py` (19 tests).

| Item | Ours | INCOIS 2902093 | Compared? | Exact differences | Classification |
|---|---|---|---|---|---|
| R prof1 PRES/TEMP/PSAL | 143–144 lev | 143–144 lev | yes | **0.000 / 0.000 / 0.000, 9/9** | **GDAC PARITY VERIFIED** |
| R prof2 PRES/TEMP/PSAL | 6 lev | 6 lev | yes | **0.000 / 0.000 / 0.000, 9/9** | **GDAC PARITY VERIFIED** |
| BR level counts | 36 | 36 | yes | none | **GDAC PARITY VERIFIED** |
| C1PHASE_DOXY | — | — | yes | **maxabs 0 (1285/1285 exact)** | **GDAC PARITY VERIFIED** |
| C2PHASE_DOXY | — | — | yes | **maxabs 0 (1285/1285 exact)** | **GDAC PARITY VERIFIED** |
| TEMP_DOXY | — | — | yes | **maxabs 0 (1285/1285 exact)** | **GDAC PARITY VERIFIED** |
| FLUORESCENCE_CHLA | — | — | yes | **maxabs 0 (1287/1287 exact)** | **GDAC PARITY VERIFIED** |
| BETA_BACKSCATTERING700 | — | — | yes | **maxabs 0 (1287/1287 exact)** | **GDAC PARITY VERIFIED** |
| CHLA / CHLA_FLUORESCENCE | — | — | yes | maxabs 2.4e-07 (float32 ulp) | **GDAC PARITY VERIFIED** |
| `VERTICAL_SAMPLING_SCHEME` | generated | per-profile | yes | **72/72 byte-identical** | **GDAC PARITY VERIFIED** |
| Rtraj event JULDs (8 MC × 9 cyc) | — | — | yes | **72/72, worst 2e-12 d (~0.2 µs)** | **GDAC PARITY VERIFIED** |
| tech rows, cycle 45 | 93/95 | 95 | yes | 2 rows (§4.1) | **GDAC PARITY VERIFIED** |
| tech row 17 `PRES_LastAscentPumpedRawSample_dbar` | telemetry `p_sub` | `p_sub` | yes | **9/9 exact** (25/25 across 2 floats) | **GDAC PARITY VERIFIED** |
| BBP700 | telemetry scale 1.883e-06 | certificate 1.86e-06 | yes | maxrel 3.8–5.4% | **EXPECTED** (§4.2) |
| DOXY | gsw in-situ density | — | yes | maxabs 0.0947, maxrel 0.73% | **UNKNOWN** (§4.3) |
| R prof3/prof4 reference levels | 144 | 143 | yes | ±1–2 on 13/18 pairs | **UNKNOWN** (§4.4) |
| Rtraj MC 289 / 290 / 590 | absent | present | yes | 756 rows over 9 cycles | **UNKNOWN** (§4.5) |
| BR044 prof4 `DATA_MODE` | `R` | `A` + `QCP$/QCF$` | yes | 1 profile | **PUBLICATION-RTQC** |

---

## 3. FileChecker warnings fixed this session

All four were real deviations from the INCOIS spec, found by comparing our
variable attributes against GDAC's own BR file.

| Warning | Count | Cause | Fix |
|---|---|---|---|
| `CHLA:valid_min/valid_max: Attribute is not allowed *** WILL BECOME AN ERROR ***` | 214 (BR + Rtraj + `_ADJUSTED`) | We emitted `0.0`/`100.0`; the spec permits no `valid_*` on CHLA, and GDAC publishes none | Removed; also aligned `C_format` to `%.4f` and `resolution` to `0.025` |
| `BBP700:valid_min/valid_max: Attribute is not allowed *** WILL BECOME AN ERROR ***` | 198 | Same, on BBP700 | Removed; `C_format` `%.7f`, `resolution` `1e-07` |
| `DOXY:valid_min: Accepted; not standard value` | 198 | We emitted `0.0`; spec and GDAC both say `-5.0` | Changed to `-5.0` (also on `DOXY_ADJUSTED`) |
| `C2PHASE_DOXY:valid_min/max: Accepted; not standard value` | 198 | `"PHASE" in pname` gave C1's range (10–70) to C2; GDAC publishes 0–15 | Per-variable range table |
| `user_manual_version: Definitions differ` | 8 | Rtraj declared `Conventions='Argo-3.2'` but `user_manual_version='3.1'` — self-inconsistent; the checker regex requires 3.4+ | Set to `3.4`, matching GDAC |

**1188 warnings → 8**, and the surviving 8 are `PI_NAME`, byte-identical to
GDAC's own value.

R and BR are now **completely warning-free**.

---

## 4. Unresolved and classified items

### 4.1 Two tech UNKNOWNs
`FLAG_RTCStatus_LOGICAL` (ours `0`, GDAC `1`) and
`FLAG_SensorBoardStatus_NUMBER` (ours `none`, GDAC `0`). Neither field exists
in any msg-250/253 payload, and no manual defines what INCOIS writes. Kept as
explicit fill / `none` with evidence recorded. **UNKNOWN**.

### 4.2 BBP700 — coefficient provenance, **EXPECTED**
GDAC's meta publishes `SCALE_BACKSCATTERING700=1.86e-06` (Wetlabs
certificate); our telemetry msg-250 carries `1.883e-06`. Substituting the
certificate value into **our own** chain collapses the residual on all nine
cycles (3.7749% → 0.00048%, 5.3702% → 0.00014%, …). `BETASW700` is exonerated:
solving GDAC's BBP700 backwards reproduces our `equations.beta_sw` to six
significant figures at every depth. The telemetry value is kept — overwriting
it with the published coefficient would be blind GDAC copying.

### 4.3 DOXY 0.73% — **UNKNOWN**
Symmetric residual. The sigma-0 density hypothesis was tested and **rejected**
(it makes the mismatch worse, 0.87–1.05%). No explanatory correlation found
(r = −0.10 vs C1PHASE, 0.01 vs TEMP_DOXY, 0.04 vs PRES).

### 4.4 R prof3/prof4 level selection — **UNKNOWN**
Pressure-only reference levels (TEMP/PSAL all fill in both files). Counts run
1–2 high on 13 of 18 pairs, maxdPRES 0.4–0.7 dbar, ~78 our-only vs ~77
GDAC-only pressures. A selection-rule difference, not a precision one.

### 4.5 Rtraj MC 289 / 290 / 590 — **UNKNOWN**, 290 adjudicated
Our Rtraj emits 26 MC codes; GDAC has 29.
- **MC290 fully adjudicated and implementable**: 3 rows × N park samples; row
  A = DOXY, row B = CHLA+BBP700, row C = TEMP+PSAL; 12-h spaced triplets
  anchored on the first park sample; `JULD_STATUS='2'`, LAT/LON 99999. All
  three PRES streams verified **exact 18/18** against telemetry park CTD, with
  the DOXY and FLBB triplets offset one sample from the CTD triplet. Not yet
  coded.
- **MC590**: 10-sample-stride decimation of the ascent CTD, but only 21/29
  GDAC pressures match ours at 0.05 dbar. Rule not pinned; implementing it
  now would mean copying one GDAC product.
- **MC289**: sporadic — 12 of 235 cycles, 27 rows total. An event code, not a
  per-cycle one. Not yet adjudicated.

Total missing rows across the nine validated cycles: **756**.

### 4.6 DATA-COVERAGE skips (never fabricated)

| group | cycles skipped | reason |
|---|---|---|
| 00530 | 1, 19 | cycle 1 = 15-sample shallow commissioning dive (0.6–21.5 dbar), no profile phase; 19 = tech-only |
| 06580 | 35 | tech-only |
| 06640 | 8 | tech-only |
| 12170 | 103, 115 | 103 = no CTD records; 115 = tech-only |
| 17960 | 54 | tech-only |
| 20000 | 48, 55 | tech-only |
| 25980 | 144, 159 | tech-only |
| 29030 | 46, 50, 52 | tech-only |

Two new honest-degradation paths were added this session rather than raising
or inventing data: a cycle whose CTD carries no profile phase writes no R, and
a cycle with no samples above the pump cutoff omits `N_PROF=2` instead of
emitting a zero-length profile. That is why some files carry `N_PROF=3`
(2902086 ×1, 2902087 ×1, 2902088 ×2, 2902114 ×2).

---

## 5. Other-float GDAC status: R/BR available/unavailable per WMO

Established by fetching each WMO's `profiles/` listing from the live INCOIS
directory on 2026-09-11 — not assumed.

| WMO | group | R | BR | published as | R/BR parity |
|---|---|---|---|---|---|
| 2902093 | 17960 | **702** | **468** | R / BR / SR | **VERIFIED (this report)** |
| 2902115 | 00530 | 0 | 714 | D/BD | **GDAC PARITY UNAVAILABLE** |
| 2902114 | 06580 | 0 | 852 | D/BD | **GDAC PARITY UNAVAILABLE** |
| 2902118 | 06640 | 0 | 783 | D/BD | **GDAC PARITY UNAVAILABLE** |
| 2902086 | 12170 | 0 | 732 | D/BD | **GDAC PARITY UNAVAILABLE** |
| 2902092 | 20000 | 0 | 446 | D/BD | **GDAC PARITY UNAVAILABLE** |
| 2902087 | 25980 | 0 | 969 | D/BD | **GDAC PARITY UNAVAILABLE** |
| 2902088 | 29030 | 0 | 684 | D/BD | **GDAC PARITY UNAVAILABLE** |
| — | 03530 | – | – | FLBB 3043 in no INCOIS meta | **DATA-COVERAGE** (no WMO) |
| — | 03580 | – | – | FLBB 3044 in no INCOIS meta | **DATA-COVERAGE** (no WMO) |

D/BD are Coriolis-reprocessed delayed-mode products. Using them as a
real-time parity target is a category error, so they are retained only as
**PUBLICATION-REPROCESSED** reference evidence.

---

## 6. Gates

| Gate | Result |
|---|---|
| `pytest tests/` | **2322 passed, 1 skipped, 0 failed** |
| `tests/test_provor_cts4_fleet_genericity.py` | **8 passed** — all 10 groups, static + dynamic genericity |
| `tests/test_provor_cts4_direct_gdac_parity.py` | **19 passed** — 2902093 direct parity + other-float census |
| `scripts/validate_cts4_phase4_gdac.py` | **RESULT: ALL PASS** |
| `scripts/prove_cts4_generic_path.py` | **static=PASS dynamic=PASS** |
| FileChecker v3.0.5, INCOIS specs | **218/218 ACCEPTED, 0 errors, 8 warnings** |

New permanent tests: 27 (8 genericity + 19 direct parity).

---

## 7. Recommendation

**Generic family decoding: demonstrated for all 10 floats.** One code path,
zero float-identity branches, one identical call trace across the 8 published
floats, 218 products, 218/218 FileChecker-accepted with 0 errors. The only
per-float variation is the calibration each float transmits itself.

**Direct R/BR GDAC parity: demonstrated for 2902093 only.** Core CTD exact,
five BGC parameters bit-exact, CHLA exact to float32 ulp, all 72 scheme
strings exact, all 72 Rtraj event JULDs exact to ~0.2 µs, 93/95 tech rows
exact.

**These two claims are separate and neither substitutes for the other.**
Specifically:

1. The nine other floats have **no R/BR target in the GDAC**, so their
   real-time products are validated only against the spec, Coriolis
   conventions, and FileChecker. That is **spec/Coriolis parity**, not GDAC
   parity.
2. Two groups (03530, 03580) cannot be published at all without fabricating a
   WMO, because their FLBB serials appear in no authoritative metadata.
3. 2902093's own parity is incomplete: DOXY (0.73%) and R prof3/4 level
   selection are unexplained, BBP700 parity requires the certificate scale,
   and 756 Rtraj rows (MC 289/290/590) are absent.

**Not publication-ready.** Blockers, in order: MC290 implementation (evidence
complete, work is mechanical), MC590/MC289 adjudication, the DOXY residual,
and R prof3/4 level selection. Resolving the missing WMOs for 03530/03580
requires an external authoritative source we do not have.
