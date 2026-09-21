# Migration Completion Report — four-CSV metadata backend

Migrates the metadata storage layer from a single `registry.csv` to four
operational CSVs, leaving the decoder and its JSON contract unchanged.

## 1. Files modified

**New**

| File | Purpose |
|---|---|
| `src/argo_decoder/metadata/multi_csv_loader.py` | Four-CSV backend: join, projection, calibration/config rendering |
| `config/metadata/{meta,sensor-info,calib,config_params}.csv` | Genuine UTF-8 CSVs converted from the supplied workbooks |
| `tests/unit/test_multi_csv_loader.py` | 13 tests, all GDAC-anchored |
| `metadata_migration_output/` | Generated JSON + NetCDF deliverables |

**Modified**

| File | Change |
|---|---|
| `src/argo_decoder/config/models.py` | `csv4` backend enum + literal |
| `src/argo_decoder/pipeline/metadata_stage.py` | `csv4` dispatch; extracted `_materialized_dirs()` |
| `src/argo_decoder/metadata/builder.py` | Emit real calibration, CONFIG/LAUNCH_CONFIG blocks, measured accuracy, DAC identity extras |
| `src/argo_decoder/nc/metadata_file.py` | Keep `PREDEPLOYMENT_CALIB_*` unpermuted (GDAC order) |
| `scripts/generate_apex_argos_nc.py` | `--registry` accepts a directory → selects `csv4` |

**Decoder logic: unchanged.** No edits under `platforms/`, `sensors/`, or
`rtqc/`.

## 2. New architecture

```
meta.csv ─┐
sensor-info.csv ─┼─ join on "WMO id" ─→ MultiCsvLoader ─→ FloatRegistryRow
calib.csv ─┤                                                     │
config_params.csv ─┘                                             ▼
                                            builder.build_info / build_meta
                                                     │
                                          info.json + meta.json  (UNCHANGED schema)
                                                     │
                                                  decoder
```

The existing `MetadataLoader` Protocol is the seam; `csv4` is additive and
`csv` still works, so the six legacy floats are untouched.

## 3. Field mapping (authoritative source per field)

| Field | Source | Evidence |
|---|---|---|
| `CONFIG_*` / `LAUNCH_CONFIG_*` | **config_params.csv** | 14/14 match GDAC `2902222` in value *and* order |
| `FIRMWARE_VERSION`, decoder id | **sensor-info.csv** | matches GDAC; config_params' "firmware date" disagrees (20811 vs 61810) |
| `MANUAL_VERSION` | config_params.csv "manual date" | matches GDAC |
| `PREDEPLOYMENT_CALIB_COEFFICIENT` | **calib.csv** | 9/9 strings byte-identical to GDAC |
| `PARAMETER_ACCURACY/RESOLUTION` | **calib.csv** | zeros, matching GDAC |
| Sensor makers/models/serials | **sensor-info.csv** | — |
| Identity, launch, deployment | **meta.csv** | — |
| `DAC_FORMAT_ID` | meta.csv "Float subtype" | 1021/1010 = GDAC `DAC_FORMAT_ID`, *not* decoder id |

**Duplicated columns in `meta.csv` (reprate/parktime/asctime/surftime/
uptime/pressures) are deliberately unused** — they disagree with
config_params and GDAC sides with config_params (e.g. AscentTime GDAC 5.4,
config_params 5.4, meta.csv 6.94).

## 4. Assumptions

1. **One mission per float** (as directed). `LAUNCH_CONFIG_*` mirrors
   `CONFIG_PARAMETER_*` — verified identical on 10/11 INCOIS floats; the
   exception (2902276) is a reprogrammed BGC float, out of scope.
2. **Decoder identity from firmware**, not the spreadsheet. `Float
   subtype` would route 2902222→1021 and 2901304→1010, both wrong.
3. DAC-wide defaults verified across **11 INCOIS floats** (below).
4. `TRANS_SYSTEM_ID` = Argos programme `02602` (9/9), not the PTT; the
   sheet's `STANDARD` frequency = `401.65 x 10^6` (9/9).

## 5. Reconstructed metadata

**None fabricated.** Two reconstructions, both derived not invented:

| Value | Provenance |
|---|---|
| `CONTROLLER_BOARD_TYPE_PRIMARY` = `APF9` | Derived from serial prefix (`9A-`,`9G-`,`9I-`); 9/9 GDAC floats with a `9x-` serial publish APF9 |
| `BATTERY_TYPE` = `Alkaline` | DAC-wide constant, 11/11 floats, even where packs mention lithium |

**2901304 / 2901305 calibration: deliberately left absent.** Pressure
coefficients *are* recoverable from GDAC (`%g` printed), but temperature
and conductivity are printed `%8.4f`, which rounds `TA0=9.8e-05`,
`CPCOR=-9.57e-08` etc. to `0.0000`. Reconstruction would fabricate
scientific values, so those floats emit `n/a` and the loader logs
`multi_csv_incomplete`.

## 6. PREDEPLOYMENT_CALIB_EQUATION investigation

**Result: constant per sensor model → implemented as a shared default.**

Across the 11-float INCOIS sample the equation strings are byte-identical
(md5 `72721074` PRES, `f29a4f8a` TEMP, `a02716ed` CNDC) spanning APEX and
PROVOR hulls and firmware 061810→091615. Only the *coefficients* vary per
float, and those stay in `calib.csv`.

Two ordering/formatting facts discovered and reproduced:
- GDAC emits `PREDEPLOYMENT_CALIB_*` in **PRES, TEMP, CNDC** order while
  `SENSOR`/`PARAMETER` use **TEMP, CNDC, PRES** — index 0 pairs
  `SENSOR=CTD_TEMP` with the *pressure* equation.
- Sea-Bird labels temperature coefficients `A0..A3`, though the sheet
  column is `TA0..TA3`.

## 7. Decoder compatibility

`info.json` is **byte-identical** to the registry.csv output (same 15
keys, same values). `meta.json` gains only populated blocks. The decoder
was not modified and runs unchanged.

## 8. Test results

- **608 passed** (595 baseline + 13 new), 0 failures
- `ruff` clean, `ruff format` clean (118 files), `mypy --strict` clean (69 files)
- **Mutation testing: 6 of 7 mutants killed.** The survivor (`%g` vs
  four-decimal rounding on |v|≥1) is *behaviourally equivalent on the
  current archive* — every such coefficient fits in six significant
  digits. Documented in the docstring rather than papered over.

## 9. Regression / audit results

| Audit | Result | vs baseline |
|---|---|---|
| `audit_mono_profile_values` | 0 dtype, 0 attr, **1813/1813 bit-identical** | unchanged |
| `audit_technical_admt` | **531/531 (100.0%)** | unchanged |
| `audit_mono_profile_admt` | `pass: 11` | unchanged |
| `audit_trajectory_admt` | `structural_parity: 4` | unchanged |
| `audit_metadata_admt` | `structural_parity: 4` | unchanged |
| `audit_engineering_decode` | `{prelude:1, decoded:77, sentinel:4}` | unchanged |

**Science invariance:** 60/60 variables identical between csv4 and the
registry.csv baseline. `_tech.nc`, `_Rtraj.nc`, `_prof.nc` byte-size
identical.

**GDAC comparison (`_meta.nc`):**

| | Before | After |
|---|---|---|
| Fields matching GDAC | 52/65 | **62/65** |
| `N_CONFIG_PARAM` | 1 | **14** (= GDAC) |
| `N_LAUNCH_CONFIG_PARAM` | 1 | **14** (= GDAC) |
| File size | 27,796 B | **31,332 B = GDAC exactly** |
| FileChecker errors | 18 | **1** |

The 3 remaining field differences are `DATE_CREATION`/`DATE_UPDATE`
(run timestamps) and `START_DATE` (decoder-derived first transmission,
not spreadsheet data).

**FileChecker:** ~~the single remaining `_meta.nc` error —
`SENSOR_MODEL/SENSOR_MAKER[3]: Inconsistent: 'DRUCK'/'SBE'` — is produced
identically by the official GDAC file. We now match the reference's
checker output exactly.~~

**SUPERSEDED.** Matching a *rejected* reference is not a pass. The
official GDAC file fails the checker because it is wrong: reference
table 27 binds `SENSOR_MODEL` `DRUCK` to `SENSOR_MAKER` `DRUCK`, never
`SBE`. This was our bug (a `DRUCK -> SBE` rewrite in
`multi_csv_loader.py`), now fixed — all ten `_meta.nc` are
`FILE-ACCEPTED`. See the `SENSOR_MODEL/SENSOR_MAKER` entry in
`IMPLEMENTATION_PROGRESS.md`.

## 10. Remaining limitations

1. **2901304/2901305 have no calibration** — unrecoverable at GDAC
   precision. Needs the original Sea-Bird sheets.
2. **One mission per float.** A reprogrammed float needs `N_MISSIONS > 1`;
   the CSV design cannot express it.
3. **`np0` parsed but unused.** `profile_count_offset` is carried on the
   row; wiring it into cycle numbering is the separate open item.
4. **`START_DATE`** stays the launch date, not the first transmission.
5. **BGC floats not covered** — the map is CTD-only; oxygen/FLBB columns
   exist in `sensor-info.csv` but no sampled float populates them.
