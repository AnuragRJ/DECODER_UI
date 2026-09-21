# Phase 5 Setup — Reference dataset and readiness

Date: 2026-07-27

## Scope

This setup step prepares the repository for Phase 5 without starting Phase 5 implementation.

The user provided a compact GDAC NetCDF reference dataset for APEX ARGOS development and validation.

## Reference dataset

Downloaded archive from Google Drive and extracted it to:

```text
phase5_reference/gdac_reference_dataset/
```

The dataset includes reference files for:

- 2901339
- 2902201
- 2902203
- 2902206
- 2902222
- 2902223

Included products per float include some combination of:

```text
profiles/*.nc
meta/<wmo>_meta.nc
meta/<wmo>_tech.nc
meta/<wmo>_Rtraj.nc
```

Important known gap from the user:

- GDAC profile files for WMO 2902201 cycles 359, 360, and 361 are not available and are not included.

## Confirmed development preferences

- Python decoder outputs remain `R*.nc` throughout the real-time pipeline.
- If a GDAC `R*.nc` is unavailable, compare science/structure against available `D*.nc` references.
- Preferred raw input layout:

```text
input/archive/cycle/<PTT>/*.txt
```

- Preferred implementation order:
  1. Mono-profile ADMT completeness
  2. JULD/LAT/LON parity
  3. Multi-profile `_prof.nc` revalidation
  4. `_tech.nc`
  5. `_Rtraj.nc`
  6. XML parity

## Environment validation

Commands run after setup:

```bash
pip install -e ".[dev,gsw]" -q
ruff check src tests scripts
ruff format --check src tests scripts
mypy --strict src
pytest -q
python scripts/audit_apex_argos_raw.py --download-missing
python scripts/generate_apex_argos_nc.py
```

Results:

- Ruff check: passed
- Ruff format check: passed (`94 files already formatted`)
- mypy strict: passed (`Success: no issues found in 61 source files`)
- pytest: `256 passed`
- Phase 4 raw audit remains `pass=77`, `superseded_by_pass=2`, `missing_reference=3`
- Phase 4 NetCDF generation still succeeds for all four scoped APEX ARGOS WMOs

## Ready for Phase 5

The repository, supplied raw data, GDAC reference dataset, and development environment are set up and validated. Phase 5 can begin with mono-profile ADMT completeness.
