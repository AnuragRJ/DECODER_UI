# Phase 4 ARGOS — APEX/WRC parser and raw-sample parity

Date: 2026-07-26

## What works

- WRC/APEX ARGOS raw files parse from CLS/Coriolis format-1 text.
- APEX CRC and redundancy selection are implemented.
- APF9 MATLAB decoder `1005` and `1010` CTD payload layouts decode PRES/TEMP/PSAL.
- APF11 `1021`/`1022` layout is implemented for future raw samples.
- Payload-derived output cycle numbers are used for filenames, fixing raw archive/GDAC cycle shifts.
- Decoded raw sample science matches GDAC profile NetCDF files for regression samples.
- Full local test suite is green: 252 passed.

## Files added/updated

- `src/argo_decoder/platforms/apex_argos/`
- `src/argo_decoder/io/rsync.py`
- `src/argo_decoder/config/decoder_table.yaml`
- `src/argo_decoder/metadata/models.py`
- `src/argo_decoder/platforms/__init__.py`
- `config/registry.csv`
- `tests/unit/test_apex_argos.py`
- `tests/unit/test_rsync_argos.py`
- `tests/integration/test_apex_argos_raw_parity.py`
- `tests/unit/test_metadata_csv.py`

## Phase 4 routing

- WMO 2901339 / PTT 102510 -> decoder `1005`, version `61810`, frame length `31`
- WMO 2902201 / PTT 152399 -> decoder `1010`, version `091515`, frame length `31`
- WMO 2902222 / PTT 152389 -> decoder `1010`, version `091615`, frame length `31`
- WMO 2902223 / PTT 152382 -> decoder `1010`, version `091615`, frame length `31`

## Raw references

- `phase4_reference/raw/raw-files/` contains the supplied ARGOS text files.
- `phase4_reference/gdac_profiles/` contains GDAC reference NetCDF profiles used by tests.

## Validation

```bash
ruff check src tests scripts
ruff format --check src tests scripts
mypy --strict src
pytest -q
```

Result: all green, 252 passing tests.

## Full supplied raw-cycle audit

Added `scripts/audit_apex_argos_raw.py` and generated:

- `docs/phase_reports/phase4_argos_raw_audit.json`
- `docs/phase_reports/phase4_argos_raw_audit.md`

Audit command:

```bash
python scripts/audit_apex_argos_raw.py --download-missing
```

Audit result across all 82 supplied target raw ARGOS files:

- `pass`: 77
- `superseded_by_pass`: 2
- `missing_reference`: 3
- hard science failures after duplicate/superseded handling: 0

The three missing references are the 2902201 / PTT 152399 output cycles 359/360/361, for which matching INCOIS GDAC profile files were not available at audit time. The raw files decode successfully and are reported separately as `missing_reference`, not as science failures.

## Generated NetCDF output bundle

Added `scripts/generate_apex_argos_nc.py`.

Command:

```bash
python scripts/generate_apex_argos_nc.py
```

Generated outputs are under:

```text
phase4_outputs/apex_argos_nc/
```

Summary:

- `2901339`: 71 mono profiles plus `2901339_prof.nc`
- `2902201`: 3 mono profiles plus `2902201_prof.nc`
- `2902222`: 3 mono profiles plus `2902222_prof.nc`
- `2902223`: 3 mono profiles plus `2902223_prof.nc`

Generation metadata/checksums are in:

```text
phase4_outputs/apex_argos_nc/phase4_argos_generation_summary.json
```

These NetCDF files are scientifically validated for core CTD profile values via the raw/GDAC audit, but full production ADMT/MATLAB metadata, tech, trajectory, auxiliary, HISTORY, and CALIB parity remains deferred.

## Duplicate output-cycle handling

The supplied WMO 2901339 raw archive includes duplicate/superseded raw records that decode to the same payload output cycle. `ApexArgosDecoder` now uses an explicit selection policy rather than last-write-wins:

1. prefer the candidate with more decoded levels,
2. then more selected ARGOS messages,
3. then more CRC-clean messages.

When a candidate replaces an earlier duplicate, the kept dataset records the earlier raw cycle in `superseded_raw_cycle_number`. The raw filename/archive cycle of the kept profile remains in `raw_cycle_number`.

A unit regression covers this policy, and the all-raw audit still reports:

- `pass`: 77
- `superseded_by_pass`: 2
- `missing_reference`: 3
- hard science failures after duplicate handling: 0
