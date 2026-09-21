# Metadata Management Architecture

> Phase 1 deliverable. This document describes the central metadata
> registry introduced in Phase 1 and how the decoder stays backend-agnostic.

## Why a central registry

The legacy MATLAB pipeline scatters per-float metadata across many
hand-edited JSON files under `decArgo_config_floats/json_float_info/` and
`json_float_meta_*/`. Adding a float means editing several files in
lock-step; drift between them (e.g. `PLATFORM_TYPE` in `_meta.json`
disagreeing with `FLOAT_TYPE` in `_info.json`) has caused silent
production bugs.

Phase 1 introduces a **single source of truth** — the central metadata
registry — while preserving the exact `*_info.json` / `*_meta.json`
contract the decoder consumes.

```
              ┌────────────────────────────────┐
              │   Central Metadata Registry    │
              │   registry.csv (one row/WMO)   │
              └───────────────┬────────────────┘
                              │ MetadataLoader
                              ▼
              ┌────────────────────────────────┐
              │ argo_decoder.metadata          │
              │  loader / builder / validators │
              └─────┬──────────────────────┬───┘
                    │                      │
                    ▼                      ▼
              meta.json               info.json    ← same schema as today
                    │                      │
                    └──────────┬───────────┘
                               ▼
                        Python Decoder            ← never imports csv/sqlite
```

The decoder only ever imports `FloatInfo` / `FloatMeta` from
`argo_decoder.metadata.models`. It never imports `csv_loader` or any
future SQLite/Postgres backend. Swapping storage backends is a
one-line config change.

## Package layout

```
argo_decoder/metadata/
├── models.py        FloatRegistryRow, FloatInfo, FloatMeta, SensorEntry, ...
├── loader.py        MetadataLoader Protocol
├── csv_loader.py    CsvLoader (reads registry.csv)
├── builder.py       build_info / build_meta / materialize (row → JSON)
├── validators.py    per-row + cross-row validation
└── json_loader.py   JsonLoader (legacy layout, kept for tests/compat)
```

### `MetadataLoader` Protocol

Every backend implements:

| Method | Returns | Purpose |
|--------|---------|---------|
| `get_float(wmo) -> FloatRegistryRow | None` | one row | O(1) WMO lookup |
| `iter_floats(wmos=None) -> Iterable[FloatRegistryRow]` | stream of rows | bulk operations |
| `load_info(wmo) -> FloatInfo` | info record | materialises on demand |
| `load_meta(wmo) -> FloatMeta` | meta record | materialises on demand |

### CSV schema (v1)

One row per WMO. Columns (see `models.FloatRegistryRow` for the
authoritative list and types):

- Identity: `wmo`, `ptt`, `imei`, `platform_maker`, `platform_type`, `platform_family`, `transmission_type`
- Decoder routing: `decoder_id`, `decoder_version`, `firmware_version`, `manual_version`
- Mission parameters: `frame_length`, `cycle_length_hours`, `drift_sampling_period_hours`, `delay_before_mission_minutes`
- Launch/reference times: `launch_date_utc`, `launch_lon`, `launch_lat`, `launch_qc`, `start_date_utc`, `reference_day`, `end_decoding_date`, `dm_flag`
- Argo bookkeeping: `argo_user_manual_version`, `wmo_inst_type`, `data_centre`, `pi_name`, `project_name`, `float_owner`, `operating_institution`
- Hardware: `battery_type`, `battery_packs`, `controller_board_primary_type`, `controller_board_primary_serial`, `float_serial_no`, `deployment_platform`, `deployment_cruise_id`, `deployment_station_id`
- Sensors/configuration: `sensors` (JSON list), `transmission_system` (JSON list), `positioning_system` (JSON list), `config_profile_ref`
- Audit: `notes`, `registry_schema_version`, `registry_row_updated_utc`

The bootstrap script `scripts/bootstrap_registry.py` converts existing
JSON trees into an initial `registry.csv` for floats already in the
legacy config.

## Pipeline integration

```
Raw Files ──► io/rsync ──┐
                        ▼
config.metadata.backend ──► build_metadata_loader() ──► loader.load_info/load_meta
                                                                │
                                                                ▼
                                                  platforms/ sensors/ derived/ rtqc/
                                                                │
                                                                ▼
                                                           nc/ + xml/ + log/
```

`pipeline/metadata_stage.py` selects the backend from
`config.metadata.backend`. For the `csv` backend it writes materialised
JSONs into a per-run meta-cache (a temp directory), then redirects
`cfg.paths.float_info_dir` / `float_meta_dir` to that cache so the
decoder reads the generated files exactly as if they came from the
legacy tree.

## Adding a new float (operational workflow)

1. Add one row to `registry.csv`. `sensors` is a JSON list of sensor
   descriptors; other columns are plain CSV.
2. Run `argo-decoder metadata validate config/registry.csv` — CI also
   runs this on every PR and blocks merges on errors.
3. (Optional) Run `argo-decoder metadata materialize config/registry.csv
   --out decArgo_config_floats/` to regenerate the JSON tree for MATLAB
   or for debugging.
4. Deploy. No JSON editing, no multi-file commits.

## Future backends

Because the decoder depends only on the `MetadataLoader` Protocol, the
CSV implementation can be swapped for SQLite, PostgreSQL, or an HTTP
API by adding a single `*_loader.py` module and a new case in
`pipeline/metadata_stage.build_metadata_loader`. No decoder code
changes.

## Validation rules (summary)

See `metadata/validators.py` for the full list.

- WMO must be a 1–7 digit positive integer.
- PTT is required.
- `transmission_type` ∈ {1 (ARGOS), 2 (IRIDIUM_RUDICS), 3 (IRIDIUM_SBD), 4 (IRIDIUM_SBD_REMOCEAN)}.
- `platform_family` ∈ {FLOAT, FLOAT_DEEP, FLOAT_BGC, FLOAT_ICE}.
- `decoder_id` > 0 and `decoder_version` non-empty.
- `frame_length`, `cycle_length_hours`, `drift_sampling_period_hours` > 0.
- `launch_lon` ∈ [-180,180]; `launch_lat` ∈ [-90,90].
- `end_decoding_date` must not precede `launch_date_utc`.
- Cross-row: no duplicate WMOs; no duplicate IMEIs; duplicate PTTs warn
  (PTTs can legitimately repeat across reflashed floats).

Unknown `platform_maker`, `platform_type`, `data_centre`, etc. emit
**warnings** (so the registry does not break when a new platform is
added), not errors.
