# ARVOR-I Phase 6 — `meta.nc` Implementation & Validation

**Date:** 2026-08-27 · **Status:** COMPLETE — STOP after this phase
**Directive:** implement `<WMO>_meta.nc` per `ARVOR_I_META_NC_MAPPING_2026-08-27.md`,
reusing the project's APF9 CSV→JSON metadata architecture where applicable;
no APF9/CTS4 modification; no GDAC copying; classify every divergence.
**Baseline preserved:** `_tech.nc`/`_Rtraj.nc`/`R*.nc` products and
`process_remaining_buffers=True` untouched (regression suite green).

## 1. Architecture (APF9 reference → ARVOR-I input path)

The project's existing metadata stack (studied, not modified):

```
APF9:    operator CSV → FloatRegistryRow → metadata.builder.build_meta → FloatMeta
                        (CsvLoader; optional materialized <wmo>_meta.json tree)
ARVOR-I: Coriolis registry <WMO>_meta.json → FloatMeta.from_json_file   ← same contract
         (metadata/json_loader.JsonLoader serves this format project-wide)
both:    FloatMeta → nc.metadata_file.build_metadata_dataset (65-var ADMT-3.1)
         → write_metadata_file → <WMO>_meta.nc
```

`FloatMeta` is a documented mirror of `<wmo>_meta.json`, so ARVOR-I needs **no
separate metadata system**: the registry json (when the user supplies one —
production makes it mandatory, this workspace has none) loads through the
same model, and telemetry-derived fields merge on top in the adapter.

## 2. Implementation (smallest clean integration)

New adapter only — `src/argo_decoder/platforms/provor_ir_sbd/arvor_i_meta.py`
(`build_arvor_float_meta` / `build_arvor_meta_nc` / `write_arvor_meta_nc`);
`metadata_file.py`, `writer.py`, `metadata/*`, APF9/CTS4 code all untouched.

* **Telemetry/transport-derived** (always emitted): `PLATFORM_NUMBER`;
  `TRANS_SYSTEM='IRIDIUM'` (.eml transport, PROVEN);
  `POSITIONING_SYSTEM='GPS'` (Tech#1 fixes, PROVEN, single system — §4);
  `PLATFORM_FAMILY='FLOAT'` (ADMT constant); `PLATFORM_MAKER='NKE'`
  (decoderIdListNke membership — PROVEN family fact); `PLATFORM_TYPE='ARVOR'`
  (decId 222/232 Arvor family per the writer case comments — INFERRED
  family-level, resolved from the decoded stream; blank when no Tech#1);
  `LAUNCH_DATE` (the established launch constants, GDAC-equal — PROVEN).
* **Registry-supplied** (only with `meta_json_path`): everything the Coriolis
  registry owns (PTT, serials, firmware/manual/format ids, WMO_INST_TYPE,
  project/PI/centre/owner, hardware, deployment, launch position, START_DATE,
  sensor/parameter/calibration tables, CONFIG blocks).  Registry wins where it
  speaks; telemetry identity always applies.
* **No-fabrication blanks** (no registry): `LAUNCH_LATITUDE/LONGITUDE` =
  99999.0 fill (pre-launch mails are factory deck tests, not the deployment
  site); `START_DATE`/`START_DATE_QC` blank (nearest raw evidence 14 s from
  the registry value — not equal, not emitted); library defaults that would
  publish unproven values are explicitly blanked (`data_centre='IF'`,
  `float_owner='IFREMER'`); all CONFIG/SENSOR/PARAMETER blocks stay fills.
* `DATA_CENTRE` blank + global `institution='CORIOLIS'` when no registry —
  the same documented MATLAB default the 4A/4B/5 products carry
  (`nc/technical_arvor.py`); with a registry json the registry `DATA_CENTRE`
  drives both via the generic builder.

## 3. Evidence / manual / chain decisions (all recorded)

1. **`update_meta_data.m` injects no platform defaults** for our decIds —
   maker/type/family in GDAC are registry values.  Only two generic rules
   exist: the GPS→+IRIDIUM positioning addition (L270–283) and a
   SENSOR_MAKER←PLATFORM_MAKER fallback.  The addition rule is **not
   applied**: its exclusion lists (`decoderIdListNkeCts4/Cts5/Pfv2…`) are not
   resolvable for 222/232 from any public source (checked
   `_argo_decoder_conf.json` — no id lists) and both production GDAC files
   carry a single positioning system.  Classification: UNKNOWN; production
   behavior followed.
2. **`WMO_INST_TYPE` '844' not emitted**: Argo reference table 8 family
   mapping for ARVOR could not be PROVEN from an authoritative table in the
   time box (web check returned only vendor pages confirming ARVOR-I = NKE,
   GPS, Iridium SBD — consistent with our derived fields but not the code);
   per the no-GDAC-copy rule the field stays blank (DATA-COVERAGE).
3. **`'n/a'` normalization**: the generic builder blanks `'n/a'` tokens
   (`_NOT_AVAILABLE`) while GDAC files carry literal `'n/a'` in
   TRANS_SYSTEM_ID/FREQUENCY.  Pre-existing generic behavior, semantically
   equivalent (fill); not changed (smallest-change rule); documented —
   relevant only if a registry json is supplied later.
4. **`CONFIG_MISSION_NUMBER=1`** on empty registry input is the generic
   builder's documented 1-based normalization (`np.arange(1, n+1)`); it
   coincides with GDAC — EXPECTED, not copied.
5. **START_DATE semantics**: ADMT/user-manual distinction between LAUNCH_DATE
   and START_DATE already documented in `metadata/builder.py` (START_DATE =
   first-descent date; never defaulted from launch) — the adapter follows it.

## 4. Validation (`scripts/validate_arvor_i_meta.py`: 54/54, exit 0)

Products rebuilt into `validation_phase6_meta/` for both floats.

| Check family | Result |
|---|---|
| NETCDF3_CLASSIC / 65-var exact GDAC order / dtypes | PASS both floats |
| Per-variable attributes | **0 diffs** both floats |
| Global attribute keys / N_MISSIONS=1 unlimited | PASS |
| Derived values == GDAC | 18/18 vars × 2 floats (PLATFORM_NUMBER, TRANS/POSITIONING systems, FAMILY/TYPE/MAKER, LAUNCH_DATE exact to the second, LAUNCH_QC, DATA_TYPE/FORMAT/HANDBOOK, END_MISSION/STARTUP/ANOMALY blanks, CONFIG_MISSION_NUMBER) |
| Registry gaps = proper fills | PASS (LAUNCH_LAT/LON 99999.0; 45 registry fields blank; CONFIG/SENSOR/PARAM blocks fill-only) |
| institution global | 'CORIOLIS' (documented chain default) |

## 5. Classified divergence ledger (vs GDAC)

| Class | Items |
|---|---|
| **DATA-COVERAGE** (registry `<wmo>_meta.json` absent, not public) | PTT 664170/339490, FLOAT_SERIAL_NO 24022/25016, SENSOR tables + serials, PREDEPLOYMENT_CALIB sheets, FIRMWARE '160414'/MANUAL '070120'/STANDARD '001020'/DAC '1024', WMO_INST_TYPE '844', PROJECT 'Argo INDIA'/PI/DATA_CENTRE 'IN'/owner 'INCOIS', battery/controller, DEPLOYMENT_PLATFORM, LAUNCH_LAT/LON, START_DATE |
| **TOOL-AVAILABILITY** | published CONFIG blocks: 10/14 legacy names absent from current public `_config_param_name_222/232.json`; 6990711 additionally has zero Param#1 packets in raw |
| **EXPECTED** | DATE_CREATION/DATE_UPDATE + history (run stamps); institution 'CORIOLIS' vs 'INCOIS'; clamped 1-row CONFIG/SENSOR/PARAM dims vs registry-populated 14/14/3/3 |
| **UNKNOWN** (documented, not applied) | `update_meta_data.m` L270-283 GPS+IRIDIUM positioning addition (exclusion lists unresolvable; production files single-system) |

## 6. Regression & deliverables

* Full suite **2035 passed** = 2020 baseline + 15 new (8 unit
  `tests/unit/test_arvor_i_meta.py`, 6 integration
  `tests/integration/test_arvor_i_meta_nc.py`, +1 architecture
  auto-parametrization picking up the new module).  No existing test
  weakened/deleted; `ruff check` + `ruff format` clean on all changed files.
* Files: adapter (above), tests, `scripts/validate_arvor_i_meta.py`
  (supports `--meta-json <wmo>=<path>` for the future full-parity path),
  products `validation_phase6_meta/{6990711,7902408}_meta.nc`.

**STOP — meta.nc implementation and validation complete.  No further product
or phase started, per directive.**
