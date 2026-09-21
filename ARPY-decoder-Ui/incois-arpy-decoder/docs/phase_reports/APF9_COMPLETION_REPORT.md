# APF9 Completion Report

**Date:** 2026-07-28
**Input roadmap:** `docs/phase_reports/APF9_COMPLETION_PLAN.md`
**Specification:** `docs/phase_reports/DOCUMENTATION_AUDIT_REPORT.md`

| | Before | After |
|---|---|---|
| Tests | 520 | **553** |
| `ruff` / `ruff format` / `mypy --strict` | clean | **clean** |
| Science levels bit-identical | 1813/1813 | **1813/1813** |
| `_tech.nc` emitted-value agreement | 531/531 | **531/531** |
| Trajectory MC 290/296 hydrography | 0/36 (all fill) | **36/36 (100 %)** |
| `N_CYCLE` timing columns populated | 4 | **6** |

---

## 1. Milestones completed

| M | Scope | Status |
|---|---|---|
| **M1** | Firmware-aware status-bit naming; documented provenance | ✅ Complete — zero output change |
| **M2** | Zero-telemetry ARGOS statistics | ⛔ **Deliberately not implemented** (§2) |
| **M3** | 32-bit SBE41 long-word; `TELONICS` byte | ✅ Complete — zero output change |
| **M4** | Park statistics + park-end sample → MC 296 / MC 290 | ✅ Complete — **36/36 exact** |
| **M5** | Auxiliary engineering block | ✅ Complete — decoded on both firmwares |
| **M6** | Cycle-timing model (`AET = TST − 10 min`) | ✅ Complete — 6 columns populated |
| **M7** | Telemetry-bound remainder | ⏸ Not implemented, as instructed |

---

## 2. M2: an evidence-based decision *not* to implement

The plan called for emitting eight ARGOS position/CRC statistics documented in
D2 rows 239–249. Before writing code I checked what the DAC actually publishes:

```
2901339: 14 distinct params, ARGOS-statistics params: NONE
2902201: 14 distinct params, ARGOS-statistics params: NONE
2902203: 14 distinct params, ARGOS-statistics params: NONE
2902206: 14 distinct params, ARGOS-statistics params: NONE
2902222: 14 distinct params, ARGOS-statistics params: NONE
2902223: 14 distinct params, ARGOS-statistics params: NONE
```

All six references use **the same fixed 14-name vocabulary**. D2 documents the
Coriolis vocabulary in general, not what this DAC publishes for APEX ARGOS
floats. Emitting these would have added rows the reference does not contain —
reducing parity — and their counting convention (which passes qualify, how
duplicates are handled) cannot be validated against anything available.

Recorded as `DAC_OMITTED_TECH_PARAMETERS` with a guard test asserting they never
reach `TECH_PARAMETER_ORDER`. The same test was applied to the six new M4/M5
parameters, with the same outcome (`DAC_OMITTED_ENGINEERING_PARAMETERS`).

**This is a publication choice, not a decoding gap.** The values are decoded,
validated and carried on `ApexEngineeringData`; the park statistics reach
`_Rtraj.nc`, where the references *do* publish them.

---

## 3. Files modified

| File | Change |
|---|---|
| `src/argo_decoder/platforms/apex_argos/engineering.py` | Firmware-aware `STATUS` tables; `sbe41_width`; `telonics_offset`; `park_sample_offset`; `aux_has_vacuum`; park-statistic and park-end fields; `decode_engineering_message_3()`; `decode_auxiliary_engineering()`; T/S/P decoders; primary-source docstrings |
| `src/argo_decoder/platforms/apex_argos/trajectory.py` | `ArgosCycleTelemetry.engineering`; MC 290/296 population; M6 timing derivation |
| `src/argo_decoder/platforms/apex_argos/profile.py` | `ApexArgosDecodedProfile.auxiliary_bytes` |
| `src/argo_decoder/platforms/apex_argos/decoder.py` | Passes engineering into telemetry; invokes the auxiliary decoder |
| `src/argo_decoder/nc/trajectory.py` | `TrajCycle.juld_ascent_end` / `juld_transmission_start`; both added to `_DERIVABLE_CYCLE_JULD` |
| `src/argo_decoder/nc/technical.py` | Corrected calibration/`ABP` reasons; `DAC_OMITTED_TECH_PARAMETERS`; `DAC_OMITTED_ENGINEERING_PARAMETERS` |
| `tests/unit/test_apex_engineering.py` | +26 tests (M1, M3, M4, M5) |
| `tests/unit/test_trajectory_nc.py` | +3 tests (M6) |
| `tests/unit/test_technical_nc.py` | +2 tests (M2 guards) |
| `IMPLEMENTATION_PROGRESS.md` | Appended phase entry (append-only respected) |

---

## 4. Decoder features added

- Firmware-aware `STATUS` semantics with a conservative fallback for unknown firmware.
- 32-bit SBE41 status long-word on decoder 1010; 16-bit retained on 1005.
- `TELONICS` PTT byte captured verbatim, **never interpreted**.
- Eleven park-phase statistics from message 2.
- Park-end hydrographic sample (`PRKT`/`PRKS`/`PRKP`) from message 3.
- Auxiliary engineering block: `PDIVMAX`, `TPI`, `VAC`, `NPMK`, descent marks.
- Documented cycle-timing model producing `JULD_TRANSMISSION_START` and `JULD_ASCENT_END`.

## 5. Engineering parameters added

Decoded and retained on `ApexEngineeringData` (17 new fields):

`park_sample_count`, `park_temperature_mean`, `park_pressure_mean`,
`park_temperature_stddev`, `park_pressure_stddev`, `park_temperature_min`,
`park_temperature_min_pressure`, `park_temperature_max`,
`park_temperature_max_pressure`, `park_pressure_min`, `park_pressure_max`,
`park_end_temperature`, `park_end_salinity`, `park_end_pressure`,
`pressure_divergence_dbar`, `profile_init_offset_minutes`,
`park_end_vacuum_counts`, `n_descent_pressure_marks`,
`descent_pressure_marks_bar`, `telonics_status_byte`.

Published to `_Rtraj.nc`: park mean T/P (MC 296), park-end T/S/P (MC 290).

## 6. Parser improvements

| Improvement | Evidence |
|---|---|
| Per-firmware SBE41 width | D5 p.21; D3 p.5 `ArgosPutLongWord` |
| `TELONICS` byte on 1010 only | D5 p.21 byte 9 |
| Park-sample offset differs per firmware (1 vs 4) | D4 p.23; D3 p.6 |
| Auxiliary `VAC` present on 1005, absent on 1010 | D2 row 232; confirmed on every archived cycle |
| T/S use the `0xEFFF` sentinel band, not `0x8000` | Matches the profile decoder validated on 1813 levels |
| Message 3 byte 3 on 1010 is `ABP`, not `VAC` | Telemetry overrides D3 p.6 (§8) |

## 7. Timing improvements

`TST_float = EPOCH + TINIT` (D1 row 27) and `AET_float = TST_float − 10 min`
(D1 row 31). The 10-minute constant was verified against every reference cycle
publishing both fields — exactly 10.00 min in all cases. `DST = previous cycle's
TET` was also confirmed exact (0.000 min) but is not yet emitted, as `TET`
requires the drift model.

Six `N_CYCLE` columns went from empty to populated.

---

## 8. A documentation error corrected by telemetry

D3 p.6 labels the first byte of message 3 `VAC`. On decoder 1010:

- documented vacuum conversion → **+6.27 inHg**, where the reference reports
  **−28.009 inHg** — not physically possible for a vacuum;
- the same byte reads **123/123/123/125** against reference
  `PRESSURE_AirBladder_COUNT` of **123/122/123/126**.

Per the governing principle that verified telemetry overrides demonstrably
incorrect documentation, that byte is **`ABP`**. This explains the Phase 6A.4
finding that the 091x15 air-bladder value "matches no byte and no constant
offset". It is still withheld: the ±1 residual is the unresolved averaging rule.

## 9. Two intermediate errors, both caught by regression

Recorded because they show the verification worked, not the first guess:

1. Park statistics initially decoded to **−2611 dbar**. Cause: indexing the raw
   payload. `payload` excludes the message id, so spec byte *n* is `payload[n−2]`.
2. Salinity then decoded to **−30.988**. Cause: a generic 2's-complement helper.
   APF9 T/S use a `0xEFFF` sentinel band, already encoded in the profile decoder.

Both were found by comparing against GDAC, not by inspection.

---

## 10. NetCDF parity improvements

Full byte-level diff against the pre-M1 baseline (5876 variables, timestamps
excluded): **39 changed variable instances, all in `_Rtraj.nc`.**

| Product | Result |
|---|---|
| Mono-profile `R<wmo>_<CCC>.nc` | **Byte-identical**; 1813/1813 science levels |
| `<wmo>_prof.nc` | **Byte-identical** |
| `<wmo>_meta.nc` | **Byte-identical** |
| `<wmo>_tech.nc` | **Byte-identical**; 531/531 agreement |
| `<wmo>_Rtraj.nc` | MC 290/296 now **36/36 (100 %)**; 2 timing columns added |

The M1–M5 invariant held throughout: no science value moved. Only M6 altered
published timing values, as authorised.

---

## 11. Remaining differences from GDAC

Classified **A** implementation bug · **B** telemetry unavailable · **C** GDAC
post-processing · **D** unknown DAC algorithm.

| # | Difference | Class | Evidence |
|---|---|---|---|
| 1 | 7 calibrated channels withheld (3 V, 3 mA, vacuum) | **D** | Formulas published (D4 p.23) and verified; the "store average of decoded values" rule is unresolved — mean-of-raw, mean-of-converted, rounded/ceil/floor, median, last and max all rejected |
| 2 | `PRESSURE_AirBladder_COUNT` withheld on 1010 | **D** | Source byte identified (§8); ±1 residual is the same averaging rule |
| 3 | Timing 10.77–11.87 min after reference | **B** | Float RTC drift measured at a linear 7.0 s/cycle; `CLOCK_DRIFT` needs ≥33 cycles (D1 rows 34–37), we hold 3 |
| 4 | `JULD_ASCENT_START` not emitted | **B** | `AST_float = EPOCH + TPI` documented and `TPI` decoded, but the field is **0/339 populated in every reference** — nothing to validate against |
| 5 | `_meta.nc` `CONFIG_*` blank (17 fields) | **B** | Layout fully specified (D2); archive contains no test-message files |
| 6 | ARGOS statistics + 6 aux params absent from `_tech.nc` | **C** | All six references use the same 14-name vocabulary (§2) |
| 7 | 39 GDAC profile levels removed | **C** | Undocumented DAC post-processing; our levels are valid |
| 8 | Reference ARGOS passes absent from our archive | **B** | Whole-archive scan; differing DAC input |
| 9 | 69 mono profiles have no reference | **B** | Only 26 reference profiles exist locally |
| 10 | `history` global differs | **C** | Intentional, as in every prior phase |

**Category A (implementation bug): zero.**

---

## 12. Definition of APF9 complete — assessment

| Criterion | Status |
|---|---|
| All five products generate from supported telemetry | ✅ 96 files across 4 floats |
| All documentation-backed functionality implemented | ✅ M1, M3–M6; M2 correctly declined on evidence |
| Engineering decoding complete where telemetry permits | ✅ every documented field in messages 1–3 and the auxiliary block |
| Timing model understood | ✅ documented, verified; residual is measured drift needing more cycles |
| No implementation-bound parity gaps | ✅ **zero category-A differences** |

Every remaining difference is **B**, **C** or **D** — telemetry that does not
exist, DAC-only processing, or an external algorithm that is documented as
existing but whose rule cannot be recovered from the data we hold.

**APF9 is complete to the limit of the available telemetry.** Nothing was
fabricated, and no value was tuned to match a reference.
