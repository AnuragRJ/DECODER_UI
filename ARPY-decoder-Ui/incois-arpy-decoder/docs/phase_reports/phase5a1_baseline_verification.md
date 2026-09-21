# Phase 5A.1 — Pre-implementation baseline verification

Date: 2026-07-27

Purpose: verify the restored workspace reproduces the documented Phase 4A /
Phase 5 baseline **before** any Phase 5A.1 code changes. No source code was
modified in this step.

## Workspace layout

Both supplied archives were unzipped into the workspace root:

```text
/home/user/argo-decoder-python/                                        # project under modification
/home/user/Coriolis-data-processing-chain-for-Argo-floats-container/   # MATLAB reference (read-only)
```

Note: the sibling directory name of the Coriolis repo is load-bearing.
`tests/conftest.py` resolves the demo dataset as
`<workspace>/Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo`,
and `tests/unit/test_provor_ir_sbd.py`,
`tests/unit/test_metadata_loader.py`,
`tests/integration/test_csv_metadata_pipeline.py`,
`tests/integration/test_structural_parity.py`,
`tests/integration/test_null_pipeline.py`, and
`scripts/bootstrap_golden.py` hardcode the same path. Renaming the directory
silently degrades 8 tests to failures/skips.

The `argo-decoder-python` copy bundled inside the Coriolis archive is
byte-identical to the standalone decoder archive (`diff -rq` clean); the
standalone copy is used.

## Documents reviewed (in the requested order)

1. `PHASE5_MIGRATION_HANDOFF.md`
2. `IMPLEMENTATION_PROGRESS.md` (Phase 4A closure + 2026-07-27 Phase 5 entries)
3. `docs/phase_reports/phase5_mono_profile_admt_baseline.md`
4. `docs/phase_reports/phase4_closure.md`

## Commands run and results

| # | Command | Expected | Actual | Status |
|---|---------|----------|--------|--------|
| 1 | `pip install -e ".[dev,gsw]" -q` | clean install | exit 0, no output | pass |
| 2 | `ruff check src tests scripts` | pass | `All checks passed!` | pass |
| 3 | `ruff format --check src tests scripts` | pass | `95 files already formatted` | pass |
| 4 | `mypy --strict src` | pass | `Success: no issues found in 61 source files` | pass |
| 5 | `pytest -q` | 256 passed | `256 passed in 30.96s` | pass |
| 6 | `python scripts/generate_apex_argos_nc.py` | succeeds | 4 WMOs `status=ok` | pass |
| 7 | `python scripts/audit_mono_profile_admt.py` | reports ADMT gaps | `gap: 11`, `missing_reference: 69` | pass |

### ARGOS NetCDF generation detail

```text
WMO 2901339: status=ok raw_files=73 input_cycles=73 nc_files=72
WMO 2902201: status=ok raw_files=3  input_cycles=3  nc_files=4
WMO 2902222: status=ok raw_files=3  input_cycles=3  nc_files=4
WMO 2902223: status=ok raw_files=3  input_cycles=3  nc_files=4
```

Output tree: `phase4_outputs/apex_argos_nc/nc/` — 80 mono-profile `R*.nc`
files plus 4 `<wmo>_prof.nc` multi-profile files. Real-time `R*.nc` naming is
preserved as required.

### Mono-profile ADMT audit detail

```text
audited 80 mono profiles: {'gap': 11, 'missing_reference': 69}
```

Regenerated `docs/phase_reports/phase5_mono_profile_admt_baseline.{json,md}`
are byte-for-byte identical to the committed baseline — the audit is
deterministic and reproduces the documented starting point exactly.

- 12 missing dimensions, 51 missing variables, uniformly across all 11
  referenced files.
- Science remains within tolerance on all 11 compared files:
  PRES max abs diff `4.88e-05` dbar, TEMP `< 1e-6` degC, PSAL `< 2e-6` psu.
- 69 `missing_reference` records are generated cycles with no compact GDAC
  counterpart in the supplied Phase 5 dataset (mostly 2901339, plus the
  documented 2902201 cycles 359/360/361).

### Concrete structural delta (WMO 2902222 cycle 327)

| | Python `R2902222_327.nc` | GDAC `R2902222_327.nc` |
|---|---|---|
| Dimensions | `N_LEVELS=58` | `N_PROF=1, N_PARAM=3, N_LEVELS=58, N_CALIB=1, N_HISTORY=6` |
| Variable count | 15 | 64 |

Python currently emits only: `PRES/TEMP/PSAL/CNDC` (+ `_QC`), `JULD`,
`JULD_QC`, `LATITUDE`, `LONGITUDE`, `POSITION_QC`, `DATA_MODE`, `DIRECTION`.
Everything else in the reference — file-level scalars, `STRING*`/`DATE_TIME`
dimensions, `STATION_PARAMETERS`, adjusted families, `SCIENTIFIC_CALIB_*`,
`HISTORY_*` — is the Phase 5A.1+ work surface.

## Deviations from the expected state

One, environmental and self-inflicted, now resolved:

- The Coriolis reference repo was initially extracted under a shortened
  directory name, causing 8 demo-data-dependent tests to fail
  (`8 failed, 245 passed, 3 skipped`). Restoring the canonical directory name
  returned the suite to `256 passed`. No code or test change was needed.

No other deviations. No unexpected failures. No warnings-to-errors, no
flaky/slow tests, no dependency resolution problems.

## Baseline confirmation

The repository reproduces the documented baseline exactly and is **ready to
begin Phase 5A.1 — mono-profile ADMT fixed dimensions + scalar/profile
metadata variables**.

Scope guardrails reconfirmed for the next slice:

- Do not modify MATLAB code.
- Do not implement the Phase 7 Buffer Manager.
- Do not broaden Phase 4 to additional platforms.
- Keep real-time outputs named `R*.nc`; compare to `D*.nc` where no `R*.nc`
  reference exists.
- Preserve existing science values; do not extend scope into tech/traj yet.
