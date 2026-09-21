# ARVOR-I `meta.nc` — Pre-Implementation Mapping Investigation

**Date:** 2026-08-27 · **Status:** READ-ONLY investigation (no code/tests/products modified)
**Floats:** 6990711 (decId 222), 7902408 (decId 232) · **Next target:** `<WMO>_meta.nc`
**Every finding labelled PROVEN / INFERRED / UNKNOWN / DATA-COVERAGE / TOOL-AVAILABILITY.**

## 0. Sources fetched (exact URLs)

GDAC references (downloaded to `gdac_arvor_i_ref/`):
- `https://data-argo.ifremer.fr/dac/incois/6990711/6990711_meta.nc` (31,360 B)
- `https://data-argo.ifremer.fr/dac/incois/7902408/7902408_meta.nc` (31,332 B)

Chain sources (GitHub mirror, base
`https://raw.githubusercontent.com/euroargodev/Coriolis-data-processing-chain-for-Argo-floats/main/`),
vendored into `tests/data/arvor_i/coriolis_src/` (read-only additions):
`soft/sub/create_nc_meta_file.m`, `soft/sub/create_nc_meta_file_3_1.m` (3,120 ln),
`soft/sub/update_meta_data.m` (8,203 ln), `soft/sub/get_meta_data_from_json_file.m`,
`soft/sub/get_nc_config_parameters_json.m`, `soft/sub/get_config_param_mandatory.m`,
`soft/sub/get_pfv2_meta_from_tech_init_struct.m`,
`soft/config/_configParamNames/_config_param_name_222.json` / `_232.json`,
and one registry sample `decArgo_config_floats/json_float_meta_ir_sbd/3901839_meta.json`
(schema evidence only — a different float).

## 1. Exact Coriolis production path (PROVEN from vendored source)

```
decode_provor_2_nc.m                     (dispatcher; processRemainingBuffers=1)
└─ decode_provor.m
   ├─ L259-280  read <WMO>_meta.json  -> g_decArgo_jsonMetaData      ← REGISTRY JSON (primary input)
   ├─ L445-469  SENSOR_MOUNTED_ON_FLOAT (json) -> g_decArgo_sensorMountedOnFloat
   ├─ L577-589  get_meta_data_from_json_file(...) -> additionalMetaData (TRAJ/PROF/TECH names)
   ├─ ...decode_provor_iridium_sbd(...)  -> structConfig             ← decoded float configuration
   │    (get_float_config_ir_sbd.m + update_float_config_ir_sbd_222_223_225_232.m;
   │     STATIC_NC / DYNAMIC_NC name+value blocks, launch column = first mission column)
   └─ L618-619  create_nc_meta_file(floatDecId, structConfig)
        ├─ dispatcher: for Iridium SBD the file is CREATED ONCE and then updated
        │  per decode run (create-if-missing gate only when no buffer decoded)
        └─ create_nc_meta_file_3_1.m
             ├─ metaData = update_meta_data(g_decArgo_jsonMetaData, decoderId)  ← json normalised
             ├─ SENSOR/PARAMETER AUX split (AUX_* sensors -> separate META_AUX file)
             ├─ per-decId CONFIG assembly; case {222,223,224,225,226,227,231,232}:
             │    LAUNCH_CONFIG  = STATIC_NC + DYNAMIC_NC, column 1 (launch values)
             │    CONFIG (mission) = same rows, launch column dropped; rows whose mission
             │    values equal launch are dropped EXCEPT the mandatory list
             │    (get_config_param_mandatory: CycleTime_hours, ParkPressure_dbar,
             │     ProfilePressure_dbar for our decIds)
             ├─ decoder config names -> NetCDF labels via
             │    get_nc_config_parameters_json(_config_param_name_<decId>.json)
             └─ writes the 65-variable ADMT-3.1 file (+ create_nc_meta_aux_file companion)
```

`get_pfv2_meta_from_tech_init_struct.m` (TECH-derived meta) applies to PFV2 decIds
401-403 only — **no TECH/config packet feeds our 222/232 meta fields**; TECH#1/#2
content reaches `meta.nc` only indirectly via `structConfig` (Param#1/2 packets).

## 2. GDAC reference coverage

Both files: NETCDF3_CLASSIC, **65 variables, identical order**, dims
`N_MISSIONS=1 (unlimited), N_TRANS_SYSTEM=1, N_POSITIONING_SYSTEM=1,
N_CONFIG_PARAM=14, N_LAUNCH_CONFIG_PARAM=14, N_PARAM=3, N_SENSOR=3` + STRING_*/
DATE_TIME.  No `N_HISTORY`.  Creation: 6990711 `2025-03-03T07:27:33Z` (+update
2025-03-04); 7902408 `2026-04-01T09:37:09Z` — both shortly after the float's
first cycles (create-once semantics).

## 3. Field/source mapping (all 65 + globals)

| Group | Variables | Source (chain) | In our workspace? | Class |
|---|---|---|---|---|
| File boilerplate | DATA_TYPE, FORMAT_VERSION (3.1), HANDBOOK_VERSION (1.2) | writer constants | yes (generic builder emits identical) | PROVEN reproducible |
| File dates | DATE_CREATION, DATE_UPDATE | production run stamps | n/a | publication-layer |
| Platform identity | PLATFORM_NUMBER | json (PLATFORM_NUMBER) | derivable (we know the WMO) | PROVEN |
| Transmission | PTT (664170/339490), TRANS_SYSTEM (IRIDIUM), TRANS_SYSTEM_ID/FREQUENCY (n/a) | json (PTT=IMEI; sample proves) | PTT **absent from mail headers** (grep PROVEN); system IRIDIUM derivable from transport | PTT: DATA-COVERAGE (registry); system: PROVEN |
| Positioning | POSITIONING_SYSTEM (GPS) | json | derivable (Tech#1 GPS fixes) | PROVEN |
| Platform family/type/maker | FLOAT / ARVOR / NKE | json | not in telemetry | registry (DATA-COVERAGE) |
| Versions | FIRMWARE_VERSION ('160414' both), MANUAL_VERSION ('070120'), STANDARD_FORMAT_ID ('001020'), DAC_FORMAT_ID ('1024') | json | not in telemetry (Tech#1 firmware is '7.2.5' — a *different* field, see profile files) | registry (DATA-COVERAGE) |
| Program/owner | PROJECT_NAME 'Argo INDIA', DATA_CENTRE 'IN', PI_NAME, FLOAT_OWNER/OPERATING_INSTITUTION 'INCOIS', ANOMALY, CUSTOMISATION | json | no | registry (DATA-COVERAGE) |
| Hardware | BATTERY_TYPE/PACKS, CONTROLLER_BOARD_* (n/a / '0i-0'), SPECIAL_FEATURES | json | no | registry (DATA-COVERAGE) |
| Serial | FLOAT_SERIAL_NO (24022 / 25016) | json | no | registry (DATA-COVERAGE) |
| Launch | LAUNCH_DATE, LAUNCH_LAT/LON, LAUNCH_QC '1' | json | **LAUNCH_DATE PROVEN equal to our established launch constants** (20250302051600 / 20260325174400); LAT/LON not derivable — 7902408's 7 pre-launch mails are factory/deck tests at (17.53, 78.42) (Hyderabad), not the deployment site (2.99, 83.0); 6990711 has no pre-launch mails | date: PROVEN; lat/lon: DATA-COVERAGE |
| Start | START_DATE (+QC '1'), STARTUP_DATE (blank) | json (sample carries START_DATE explicitly) | 7902408 START_DATE 2026-03-25T12:08:16 vs our last pre-launch mail 12:08:30 (14 s apart); 6990711 START_DATE == LAUNCH_DATE | registry (DATA-COVERAGE); nearest raw evidence INFERRED |
| Deployment | DEPLOYMENT_PLATFORM ('rv agulhas' / 'rv sindhu sadhana'), CRUISE_ID, REF_STATION | json | no | registry (DATA-COVERAGE) |
| End of mission | END_MISSION_DATE/STATUS (blank) | json | floats active — blank is reproducible | PROVEN (blank) |
| Config blocks | LAUNCH_CONFIG_PARAMETER_NAME/VALUE, CONFIG_PARAMETER_NAME/VALUE (14 names/values), CONFIG_MISSION_NUMBER (1), COMMENT | json CONFIG blocks and/or structConfig telemetry, names via `_config_param_name_<decId>.json` | see §4 | PARTIAL / INFERRED (below) |
| Sensors | SENSOR (CTD_TEMP/CNDC/PRES), MAKER (SBE/SBE/DRUCK), MODEL (SBE41CP/SBE41CP/DRUCK), SERIAL_NO (20409… / 19290…) | json SENSOR_MOUNTED_ON_FLOAT | serials/models not in telemetry | registry (DATA-COVERAGE) |
| Parameters | PARAMETER (TEMP/PSAL/PRES), PARAMETER_SENSOR, UNITS, ACCURACY '0', RESOLUTION '0' | json | name triple derivable (our published params) but units/accuracy are registry | registry |
| Pre-deployment calib | PREDEPLOYMENT_CALIB_EQUATION/COEFFICIENT/COMMENT (full SBE41CP coefficient sheets) | json | not in telemetry | registry (DATA-COVERAGE) — never fabricate |
| Globals | title/institution 'INCOIS'/source/references/user_manual_version 3.1/Conventions/history | writer + DAC | our builder emits the same key set, `institution` parameterised | publication-layer |

## 4. The CONFIG block — evidence and classification

GDAC values (identical for both floats): `[0, 112, 6, 6.6, 1000, 12, 2000, 6, 222,
1, 240, 66, 25, 67]` under names `TransmissionRepetitionPeriod_seconds,
ParkTime_hours, AscentTime_hours, SurfaceTime_HH, ParkPressure_dbar, UpTime_hours,
ProfilePressure_dbar, MissionPreludeTime_hours, DownTime_hours, TripInterval_hours,
CycleTime_hours, PistonPark_COUNT, PistonProfile_COUNT, DepthTable_NUMBER`.

1. **Names:** only 4/14 (SurfaceTime_HH=MC05, ParkPressure_dbar=MC011,
   ProfilePressure_dbar=MC012, CycleTime_hours=MC002) exist in the *current*
   `_config_param_name_232.json`; 10/14 (ParkTime, UpTime, DownTime, AscentTime,
   TripInterval, MissionPrelude, TransmissionRepetitionPeriod, PistonPark,
   PistonProfile, DepthTable) are **absent from the public chain tables** — the
   published files predate/diverge from the public label mapping (PROVEN by
   table diff), consistent with registry-json provenance (sample json carries
   full `CONFIG_PARAMETER_NAME/VALUE` blocks) — INFERRED.
2. **Values vs decoded telemetry (7902408):** our cycle-0 (prelude) Param#1
   gives 62 MC/TC values.  Exact matches: ParkPressure MC11=1000, ProfilePressure
   MC12=2000, UpTime MC09=12, PistonProfile TC13=MC21=25, TripInterval MC15/TC20=1,
   several 0s.  Mismatches: CycleTime MC02/MC03=235 vs 240; SurfaceTime MC05=6 vs
   6.6; PistonPark TC28=65 vs 66.  Mixed agreement ⇒ the published values are the
   deployment-recorded (registry) programming, not a bit-exact telemetry echo
   (INFERRED; telemetry itself decodable — PROVEN).
3. **6990711:** zero Param#1/2 packets in its 35 mails (PROVEN) — no telemetry
   config at all, yet GDAC carries the full block ⇒ registry origin for that
   float is certain.
4. **N_MISSIONS=1 with mission row == launch row:** consistent with the json
   single-mission CONFIG list (the telemetry dedup path would drop all-but-3
   mandatory rows); INFERRED json path.

## 5. Two-float comparison (requirement 7)

- **Float-specific:** PLATFORM_NUMBER, PTT, FLOAT_SERIAL_NO, LAUNCH_DATE (+
  START_DATE), LAUNCH_LAT/LON, DEPLOYMENT_PLATFORM, SENSOR_SERIAL_NO ×3,
  PREDEPLOYMENT_CALIB_COEFFICIENT ×3, DATE_CREATION/DATE_UPDATE/history.
- **Cycle/config-derived (in principle):** CONFIG/LAUNCH_CONFIG blocks (here:
  deployment-programmed, identical template), CONFIG_MISSION_NUMBER.
- **Static template (identical, registry family values):** PLATFORM_FAMILY/TYPE/
  MAKER, FIRMWARE/MANUAL_VERSION, STANDARD/DAC_FORMAT_ID, WMO_INST_TYPE 844,
  BATTERY/CONTROLLER blocks, SENSOR names/makers/models, PARAMETER block,
  CALIB_EQUATION strings, TRANS/POSITIONING systems, PROJECT/PI/DATA_CENTRE/
  owner.
- **DAC/publication:** institution global, DATE_*, history string, file creation
  cadence.

## 6. Reproducibility from our workspace (summary)

- **PROVEN reproducible:** full 65-var layout + order + dims (our generic
  `build_metadata_dataset` matches GDAC **65/65, exact order** — runtime-verified
  this session); PLATFORM_NUMBER; TRANS_SYSTEM 'IRIDIUM'; POSITIONING_SYSTEM
  'GPS'; LAUNCH_DATE (equals our established launch constants); blank
  END_MISSION/STARTUP_DATE/ANOMALY/COMMENT-style fields; fill conventions.
- **PARTIAL (7902408 only):** CONFIG values decodable from cycle-0 Param#1
  (MC/TC), but under the *current* chain label tables — not the published legacy
  names; several values differ from the registry-recorded ones.
- **NOT reproducible without the registry json `<WMO>_meta.json`:** PTT, serial
  numbers, firmware/manual/format ids, maker/battery/controller, project/PI/
  centre/owner, deployment platform, LAUNCH_LAT/LON, START_DATE, sensor tables,
  pre-deployment calibration sheets, the published CONFIG block verbatim.
  **No `<wmo>_meta.json` for 6990711/7902408 exists anywhere in the workspace**
  (PROVEN by search); the public repo ships jsons only for other (Coriolis)
  floats.  Per the no-fabrication rule these remain blank/classified.

## 7. Proposed Python integration design

Reuse, do not duplicate: the existing generic stack already *is* the Coriolis
meta pipeline shape —

- `metadata.models.FloatMeta` — documented as "mirror of `<wmo>_meta.json`",
  alias-accepts the MATLAB json shape (PTT/IMEI, numbered blocks as extras);
- `metadata.json_loader.JsonLoader` — reads `<wmo>_meta.json` directly;
- `nc.metadata_file.build_metadata_dataset(wmo=…, meta=FloatMeta|None,
  institution=…, date_creation=…, date_update=…, start_date=…)` → 65-var
  ADMT-3.1 dataset (order verified); `writer.py` already writes `<wmo>_meta.nc`.

Thin ARVOR-I adapter (pattern of 4A/4B/5): `platforms/provor_ir_sbd/arvor_i_meta.py`
- `build_arvor_meta_input(result: ArvorScienceResult, *, wmo, launch_date,
  meta_json_path: Path | None) -> FloatMeta` — telemetry-derived fields
  (platform number, IRIDIUM, GPS, launch date; optionally CONFIG blocks from
  Param#1 under current-chain labels, flagged), merged with the registry json
  when the user supplies one (JsonLoader-validated; explicit input, never
  fabricated);
- `build_arvor_meta_nc(...) -> xr.Dataset` delegating to the generic builder;
  validator `scripts/validate_arvor_i_meta.py` writing
  `validation_phase6_meta/` and comparing against the two GDAC references with
  the classified-divergence ledger.

## 8. Parity expectations & discrepancy/coverage ledger

With a user-supplied registry json: near-exact parity expected on all registry
fields; residual differences only DATE_CREATION/DATE_UPDATE (run stamps),
`history`, `institution` (publication-layer), and any CONFIG-label drift.
Without it: structural parity (65/65 layout), telemetry-derivable subset
filled, everything else blank `_FillValue` — every blank classified below.

| # | Item | Class |
|---|---|---|
| 1 | PTT/IMEI, FLOAT_SERIAL_NO, sensor serials, calib sheets | DATA-COVERAGE (registry json not public) |
| 2 | LAUNCH_LAT/LON, START_DATE, DEPLOYMENT_PLATFORM | DATA-COVERAGE (registry; raw cannot supply — pre-launch mails are factory deck tests) |
| 3 | FIRMWARE_VERSION '160414' etc. | DATA-COVERAGE (registry; note ≠ Tech#1 '7.2.5') |
| 4 | CONFIG block legacy names (10/14) | TOOL-AVAILABILITY/production-version (absent from public label tables) |
| 5 | CONFIG values 240/6.6/66 vs telemetry 235/6/65 | registry-vs-telemetry difference (classified; not forced) |
| 6 | 6990711 has no Param#1/2 in raw | DATA-COVERAGE (raw snapshot) |
| 7 | institution 'INCOIS', DATE_*, history | publication-layer |
| 8 | Layout/dims/order/fills | PROVEN reproducible (verified) |
| 9 | LAUNCH_DATE | PROVEN (equals our constants) |

## 9. Recommended implementation plan (for a future directive)

1. Adapter + FloatMeta merge (§7); no change to `metadata_file.py`/`writer.py`.
2. Tests: unit (telemetry→FloatMeta mapping, json merge precedence, blank
   classification), integration (round-trip write; layout vs GDAC 65/65),
   validator run for both floats.
3. Decision points for the directive: **D1** — will the user supply
   `6990711_meta.json` / `7902408_meta.json` (full parity) or do we ship
   blanks+classification (recommended default; no fabrication)?  **D2** —
   CONFIG block emission without json: recommend blank + classification (the
   published names are not derivable from the public chain; emitting
   current-label telemetry values would not match GDAC).  **D3** —
   `institution` global: keep our parameterised default and classify.
4. Reports + `IMPLEMENTATION_PROGRESS.md` append; ruff check+format; STOP.

**STOP — investigation ends here per directive. No implementation performed; no
existing phase/product modified.**
