# CTS4 Metadata / Publication-Contract Closure — Final Table

Phase 10, 2026-09-15. Scope: the seven remaining publication-contract items.
P0 decoder work was already accepted and closed; the decoder was not redesigned.

Evidence hierarchy used throughout: **RAW TELEMETRY FACT / MANUAL-SPEC / NKE DOC /
CORIOLIS-MATLAB / GDAC OBSERVED / INFERENCE**. Nothing below is classified above
its actual evidence level, and no value was copied from GDAC or invented.

---

## Final table

| Issue | Root cause | Evidence | Fix | Direct GDAC result (2902093) | All-10 result | Final classification |
|---|---|---|---|---|---|---|
| **F6** `PARAMETER_ACCURACY` / `PARAMETER_RESOLUTION` hard-blanked | Writer emitted blank strings for both fields for all 11 parameters, although Argo requires a sensor specification and the values are published constants for this family | **MANUAL-SPEC**: UM 3.1 §2.4.7 p61 — free-text *sensor* figures, "not necessarily equivalent to the resolution ... through telemetry", no controlled vocabulary. **NKE DOC**: DOC 33-16-016 Rev3 §8 Sensors p61 — PRES ±2.4 dbar/0.1; TEMP ±0.002 °C/0.001; PSAL ±0.005 PSU/0.001; O2 ±8 µM/l or 5% / <1 µM/l. **CORIOLIS-MATLAB**: `generate_csv_meta.m:836-869` defaults exactly PRES/TEMP/PSAL/DOXY. **GDAC OBSERVED**: identical bytes across all 13 INCOIS meta.nc | `writer/nc.py`: new `PARAMETER_ACCURACY_SPEC` / `PARAMETER_RESOLUTION_SPEC` + write loops. Channels with **no NKE figure left blank**, not invented (C1PHASE_DOXY, C2PHASE_DOXY, FLUORESCENCE_CHLA, BETA_BACKSCATTERING700, BBP700) | **11/11 exact** on both fields | Same constants for all 8 publishable floats (parameter-level, not float-specific) | **FIXED** — partial by design: blank where no authoritative figure exists |
| **F7** `PARAMETER_UNITS` "mismatch" | Not a defect. We publish NVS R03 terms; INCOIS's own `meta.nc` uses two abbreviations that contradict its own profile files | **MANUAL-SPEC**: UM p63 requires non-empty per NVS R03, example `degree_Celsius`; UM §3.3.2 p78 "DOXY unit: micromole/kg". **GDAC OBSERVED**: profile-level `units` match us exactly (`degree_Celsius`, `psu`, `micromole/kg`, `mg/m3`, `m-1`) | **No code change** | 9/11 match; the 2 "differences" are INCOIS `meta.nc` abbreviations `degC` / `umol/kg` that contradict INCOIS's own profile files | Unchanged for all floats | **NOT A DEFECT** — GDAC metadata is internally inconsistent; UM is the authority |
| **F8** `id` published the WMO | `external_meta_io` set `id=wmo`, asserting a DOI string the source never claimed | **MANUAL-SPEC**: UM p17 — `id` = "The Argo GDAC data DOI: https://doi.org/10.17882/42182". **GDAC OBSERVED**: 41 INCOIS files carry it, 58 do not; R/BR always carry it, D/BD never | `external_meta_io.py`: new `_read_id(ds)` reads the value from authoritative metadata; absent → nothing published | **Exact match** `https://doi.org/10.17882/42182` | Reads each float's own metadata; no hard-coded DOI | **FIXED** |
| **F9** `FLAG_RTCStatus_LOGICAL` published raw byte | We published telemetry byte 25 verbatim. That byte is the RTC **error** indicator; the Argo field is inverted. Previously mis-classified NOT-REPRODUCIBLE-FROM-TELEMETRY | **CORIOLIS-MATLAB**: `_tech_param_name_301.csv:13` — decoder id 109, msg 253, "**1= OK, 0=not OK**" (the same CSV that is our 301 format standard). Sibling decoder already inverts: `provor_ir_sbd/arvor_i_tech.py:489,537` → `0 if raw else 1`. **RAW TELEMETRY FACT**: byte 25 = `0` on **269/269 packets, all 10 groups**. **GDAC OBSERVED**: `1` on 491/491 rows over 3 floats. Independent corroboration: MC589 cy47 JULD `23443.913194` bit-identical to INCOIS | `tech_build.py:220`: `str(vt.rtc)` → `"0" if vt.rtc else "1"` | **10/10 cycles exact**; tech.nc row comparison went **94/95 → 95/95 exact** on cycle 45, **zero residual differences** | Inversion applied identically for all 10 groups | **FIXED** — was a real defect, not a telemetry limitation |
| **F10** signed-zero offset rendered `-0` | `f"{-0.0:g}"` → `'-0'`, so a genuinely zero offset published as a malformed negative zero | **RAW TELEMETRY FACT**: cycle 53 offset is exactly 0. **GDAC OBSERVED**: `0` | `tech_build.py:197`: `f"{float(free.offset_p):g}"` → `f"{float(free.offset_p) + 0.0:g}"` (IEEE-754 identity; changes signed zero only) | **10/10 exact**, including cy53 `0` | Applied for all floats | **FIXED** |
| **F12** `START_DATE` fell back to `launch_date` | START_DATE, LAUNCH_DATE and STARTUP_DATE are three distinct events; substituting the launch time published a minute the telemetry never carried | **MANUAL-SPEC**: UM p54 — START_DATE = first descent, STARTUP_DATE = activation, both ≠ launch. UM reference table 2 p76 — `9` = "Missing value. Data parameter will record FillValue". **GDAC OBSERVED**: across 13 INCOIS CTS4 floats the true START_DATE precedes LAUNCH_DATE by **−17 to −152 min**; `STARTUP_DATE` empty and its QC blank on **13/13**. **RAW TELEMETRY FACT**: the 253 clock is a float-day offset from mission start; earliest cycle held for 2902093 is cycle 45 / float-day 349 — no deployment-era absolute timestamp exists | `writer/nc.py`: publish the authoritative value or FillValue; `*_QC` = `1` only when a real value exists, else **`9`** (blank QC is itself a FileChecker error: `START_DATE_QC: ' ' Status: Invalid`) | `STARTUP_DATE` + both QCs match; `START_DATE` differs from GDAC by design (we publish FillValue, not a fabricated minute) | Same for all 10; no float gets an invented date | **LEGITIMATE REAL-TIME LIMITATION** — published as unavailable per table 2, never fabricated |
| **TRANS_FREQUENCY / TRANS_SYSTEM_ID** | `TRANS_SYSTEM_ID` was written from the PTT (`061796`) — a different field; `TRANS_FREQUENCY` was blank instead of `n/a` | **MANUAL-SPEC**: UM p51 — `TRANS_SYSTEM_ID` = telecommunication **subscription** program id; "DACs can use N/A ... when not applicable (**e.g.: Iridium or Orbcomm**)". UM p63 — default `n/a` when absent. These are Iridium floats | `writer/nc.py`: both → `n/a` | **Both exact match** | Same for all 10 Iridium floats | **FIXED** |

---

## Verification run after the fixes

| Gate | Result |
|---|---|
| All 10 raw SBD groups (517 packets) | 8 OK. `03530` / `03580` = **DATA-COVERAGE**: FLBB serials 3043 / 3044 appear in no INCOIS `meta.nc`, so there is no WMO and no publishable product. Not inferred from IMEI |
| `pytest tests/ -q` | **2379 passed, 1 skipped** |
| OneArgo FileChecker v3.0.5, 214 files | **214/214 FILE-ACCEPTED, 0 FORMAT-ERRORS, 0 checks skipped**. 12 warnings: 8 × `PI_NAME`, 4 × MC703 `JULD_*_LOCATION` on `2902092_Rtraj.nc` |
| `meta.nc` vs INCOIS GDAC (2902093) | differing variables **11 → 7**. Closed: `PARAMETER_ACCURACY`, `PARAMETER_RESOLUTION`, `TRANS_FREQUENCY`, `TRANS_SYSTEM_ID`; `id` now matches |
| `tech.nc` vs INCOIS GDAC | **95/95 rows exact on cycle 45**. Fleet-wide 73 differing rows, **all on cycle 54** (incomplete in our corpus) |
| R/BR direct parity, 18/18 (cycle, profile) keys | PRES 7730/7730, TEMP/PSAL 1293/1293, LAT/LON 72/72 exact |
| Genericity (`prove_cts4_generic_path.py`) | **static=PASS dynamic=PASS** |

**Remaining 7 `meta.nc` differences, all legitimately non-reproducible:**
`decoder_version`, `history`, `DATE_CREATION`, `DATE_UPDATE` (our own build
metadata), `DEPLOYMENT_PLATFORM`, `PARAMETER_UNITS` (F7 — GDAC self-inconsistent),
`START_DATE` / `START_DATE_QC` (F12 — published as table-2 missing).

**Regression guards added** to `tests/test_provor_cts4_position_time_regression.py`:
RTC inversion (both polarities), NKE accuracy/resolution constants plus the
not-invented blanks, `id` = GDAC DOI ≠ WMO, and table-2 code `9` for absent
dates.

---

## Status

All seven metadata / publication-contract items are closed: five FIXED, one
adjudicated NOT A DEFECT (F7), one a legitimate real-time limitation published
honestly per Argo table 2 (F12). **F9 is resolved as a genuine defect, not an
irreproducible telemetry field** — the prior classification is withdrawn.

**CTS4 is NOT declared publication-ready and is NOT frozen.** The freeze gate
requires a separate, explicit decision.
