# Decoder Routing Table (`decoder_table.yaml`)

## Purpose

The MATLAB decoder ships **21 firmware-version-specific initialisation files**
named `init_float_config_prv_ir_sbd_<ver>.m`. Each of these files hard-codes
the mission parameters, frame layout and sensor roster for one
`(platform_type, decoder_version)` combination and is selected at runtime by
a cascade of `if strcmp(decoder_version, '5.67') ... elseif ...` chains.

The Python port replaces this **code-as-configuration** anti-pattern (Guardrails
§7 — "tables not code") with a single declarative YAML file:

```
src/argo_decoder/config/decoder_table.yaml
```

Adding a new firmware version is a **one-row edit** plus (only when the
on-wire format actually differs) a matching platform plugin. No `if
decoder_id == N` chains exist in science code.

## Schema

Each entry under the top-level `decoders:` list has:

| Field             | Type            | Description                                                                 |
|-------------------|-----------------|-----------------------------------------------------------------------------|
| `platform_type`   | string          | e.g. `ARVOR_D`, `ARVOR`, `PROVOR` — matches `platform_type` in registry    |
| `decoder_version` | string          | Firmware version e.g. `"5.67"` (string to preserve leading zeros/`"X.YY"`) |
| `decoder_id`      | positive int    | Numeric ID matching `DECODER_ID` in `*_info.json`                           |
| `platform_family` | enum            | `FLOAT` / `FLOAT_DEEP` / `FLOAT_BGC` / `FLOAT_ICE`                          |
| `transmission`    | enum            | `IRIDIUM_SBD` / `IRIDIUM_RUDICS` / `ARGOS` / `IRIDIUM_SBD_REMOCEAN`        |
| `frame_length`    | positive int    | Bytes per SBD frame                                                         |
| `profile_class`   | string \| null  | Python plugin class name; `null` until the plugin ships (Phase 2+)          |
| `sensors`         | list[string]    | Sensor short names mounted on this version (e.g. `CTD_PRES`, `OPTODE_DOXY`) |
| `notes`           | string          | Free text                                                                   |

The schema is enforced by a Pydantic model (`DecoderTableEntry`) with
`extra="forbid"` — unknown keys raise a `ValidationError` at load time
rather than silently being ignored.

## Loading API

```python
from argo_decoder.config import get_decoder_table, load_decoder_table

# Cached, bundle-default:
table = get_decoder_table()

# Explicit path (used by tests and by operators maintaining a fork):
table = load_decoder_table("/etc/argo/decoder_table.yaml")

# Lookups:
entry = table.by_platform_version("ARVOR_D", "5.67")  # KeyError if missing
entry = table.by_decoder_id(221)  # KeyError if missing
entry.decoder_id  # 221
entry.frame_length  # 31
entry.sensors  # ["CTD_PRES", "CTD_TEMP", "CTD_CNDC", "OPTODE_DOXY"]
```

`get_decoder_table()` is cached via `functools.lru_cache` keyed on absolute
path, so repeated calls are cheap. The table object is immutable
(`frozen=True` on both `DecoderTable` and `DecoderTableEntry`) — code
receives a read-only view and cannot mutate routing state at runtime.

## Referential integrity with the registry

`argo_decoder.metadata.validators.validate_registry(rows, decoder_table=...)`
now performs three cross-checks per registry row when a table is supplied:

1. **`DECODER_VERSION_UNKNOWN`** — `(platform_type, decoder_version)` not in
   the table.
2. **`DECODER_ID_UNKNOWN`** — `decoder_id` not present anywhere in the table
   (emitted only when the version is also unknown).
3. **`DECODER_ID_MISMATCH`** — version key is known but the numeric
   `decoder_id` disagrees with the table entry (catches copy-paste errors).

The CLI wires this up automatically:

```bash
# Uses the bundled table by default:
argo-decoder metadata validate config/registry.csv

# Override the table path:
argo-decoder metadata validate config/registry.csv \
    --decoder-table /path/to/my_table.yaml

# Skip cross-checks (fast, for ad-hoc CSV authoring):
argo-decoder metadata validate config/registry.csv --no-decoder-table
```

## Phase 1 scope

Phase 1 ships only the two demo float entries needed for development
and CI (WMO 6902892 Arvor Deep 5.67 and WMO 6903014 Arvor 5.45). The
remainder of MATLAB's 21 init files are extracted automatically by the
`scripts/extract_decoder_table.py` script, scheduled for Phase 2 as
part of the Provor Iridium SBD CTD plugin work.

## Files

| Path                                           | Role                                 |
|------------------------------------------------|--------------------------------------|
| `src/argo_decoder/config/decoder_table.yaml`   | Data (shipped in the wheel)          |
| `src/argo_decoder/config/decoder_table.py`     | Models + loaders                     |
| `src/argo_decoder/config/__init__.py`          | Re-exports public API                |
| `src/argo_decoder/metadata/validators.py`      | Cross-checks against registry        |
| `src/argo_decoder/cli/metadata_cli.py`         | CLI flags `--decoder-table/--no-decoder-table` |
| `tests/unit/test_decoder_table.py`             | Unit tests for loader + validators   |
| `pyproject.toml`                               | `force-include` for the YAML; `pyyaml` dep |
