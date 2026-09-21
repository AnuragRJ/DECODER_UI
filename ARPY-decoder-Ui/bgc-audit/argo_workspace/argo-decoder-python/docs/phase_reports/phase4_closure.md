# Phase 4A Closure — WRC/APEX ARGOS CTD parser

Date: 2026-07-26

## Scope closed

This closes the Phase 4 slice requested in the handoff: ARGOS parsers for the WRC/APEX floats:

- WMO 2901339 / PTT 102510
- WMO 2902201 / PTT 152399
- WMO 2902222 / PTT 152389
- WMO 2902223 / PTT 152382

This closure means **WRC/APEX ARGOS CTD profile science** is implemented and validated for the supplied raw files. It does not mean every platform in the original migration plan is implemented, and it does not mean all ADMT production products are complete.

## Features implemented

- `src/argo_decoder/platforms/apex_argos/` plugin registered through the platform registry.
- CLS/Coriolis ARGOS format-1 raw text parser.
- APEX CRC validation from MATLAB `check_crc_apx.m`.
- Bit-majority reconstruction from MATLAB `combine_bits_apx.m`.
- Redundancy selection equivalent to MATLAB `get_apex_data_sensor.m` behavior.
- APF9 CTD layouts:
  - decoder `1005`, firmware/version `61810`, profile class `apf9_ctd_23`.
  - decoder `1010`, firmware/version `091515` / `091615`, profile class `apf9_ctd_19`.
- APF11 layout `1021`/`1022` implemented for future raw samples, but not used by the four target rows.
- Payload-derived output cycle numbers.
- Duplicate/superseded raw file selection policy.
- ARGOS file discovery in `io/rsync.py`.
- CSV registry and decoder table routing for the four target floats.
- Batch generation script: `scripts/generate_apex_argos_nc.py`.
- All-raw audit script: `scripts/audit_apex_argos_raw.py`.

## Validation performed

### Raw/GDAC science audit

Command:

```bash
python scripts/audit_apex_argos_raw.py --download-missing
```

Result across 82 supplied target ARGOS raw files:

- `pass`: 77
- `superseded_by_pass`: 2
- `missing_reference`: 3
- hard science failures after duplicate/superseded handling: 0

The missing references are WMO 2902201 output cycles 359/360/361; those raw files decode and generate NetCDF outputs, but matching public INCOIS GDAC profile files were not available at audit time.

### NetCDF generation

Command:

```bash
python scripts/generate_apex_argos_nc.py
```

Generated outputs under:

```text
phase4_outputs/apex_argos_nc/
```

Summary:

- 2901339: 71 mono profiles plus `2901339_prof.nc`.
- 2902201: 3 mono profiles plus `2902201_prof.nc`.
- 2902222: 3 mono profiles plus `2902222_prof.nc`.
- 2902223: 3 mono profiles plus `2902223_prof.nc`.

### Quality gates

```bash
ruff check src tests scripts
ruff format --check src tests scripts
mypy --strict src
pytest -q
```

Final result:

- Ruff check: pass
- Ruff format check: pass
- mypy strict: pass
- pytest: 253 passed

## What works

For the four scoped WRC/APEX ARGOS floats, the Python decoder can:

1. discover ARGOS raw text files,
2. parse messages,
3. validate CRCs,
4. select redundant messages,
5. decode CTD profile science,
6. compute payload output cycles,
7. handle duplicate/superseded raw files,
8. write mono-profile NetCDF files,
9. write multi-profile `_prof.nc` files,
10. audit core science against GDAC references where references exist.

Validated core science parameters:

- PRES
- TEMP
- PSAL
- derived CNDC through the existing CTD/derived path

## Known limitations intentionally deferred

The generated NetCDF files are accurate for core CTD profile science but are not yet full production-equivalent MATLAB/ADMT products. Deferred items:

- Full ARGOS trajectory (`*_Rtraj.nc`).
- ARGOS tech NetCDF (`*_tech.nc`).
- ARGOS meta/auxiliary NetCDF products.
- Full ADMT HISTORY and CALIB groups in mono profiles.
- Full XML report parity.
- Wider platform support: Provor/NKE ARGOS, NEMO, NOVA, Remocean, RUDICS, and other non-APEX families.
- Phase 7 Buffer Manager.

## Relation to original migration plan

The original plan's Phase 4 is broad: "Other platforms & transmission types." This closure covers **Phase 4A: WRC/APEX ARGOS CTD**. The architecture follows the plan's guardrails:

- plugin-based platform decoder,
- table-driven routing,
- metadata-backend agnostic decoder code,
- deterministic tests/audits,
- no MATLAB edits.

Future Phase 4 sub-slices should add other platform/transmission families in the same pattern rather than extending APEX-specific logic into a universal parser.

## Next phase recommendation

Move to the next planned product-completeness phase:

1. ADMT mono-profile completeness (file-level scalars, HISTORY, CALIB).
2. ARGOS profile date/location parity from ARGOS locations and transmitted timing fields.
3. ARGOS tech/meta/traj product writers.
4. Eventually Phase 7 Buffer Manager for SBD aggregation.
