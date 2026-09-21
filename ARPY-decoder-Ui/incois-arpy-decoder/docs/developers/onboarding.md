# Developer onboarding

Welcome to the Coriolis Argo float Python decoder. This document walks
a new engineer through setting up a development environment, running
tests/lint/type-check, and understanding where to look for things.

## Prerequisites

- Python 3.11+ (3.12 recommended; 3.13 is also supported and used in CI).
- [`uv`](https://github.com/astral-sh/uv) — `pip install uv`.
- Git.
- Docker Desktop (optional; only needed for `--oracle docker:` shadow
  runs against the MATLAB container).

The codebase is fully supported on Linux and Windows. See
[`docs/user/running_locally.md`](../user/running_locally.md) for
Windows-specific setup notes.

## Get the code

```bash
git clone <python-repo-url> argo-decoder-python
git clone https://github.com/euroargodev/Coriolis-data-processing-chain-for-Argo-floats-container.git
cd argo-decoder-python
```

Put the MATLAB container repo as a **sibling** directory so the demo
data paths in `tests/conftest.py` resolve.

## Create a virtual environment and install

```bash
# Linux / macOS
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev,gsw]"

# Windows PowerShell
uv venv --python 3.12 .venv
.venv\Scripts\Activate.ps1
uv pip install -e ".[dev,gsw]"
```

## Tooling cheatsheet

| Task | Command |
|------|---------|
| Run unit + integration tests | `pytest -q` |
| Run tests with coverage | `pytest --cov=argo_decoder --cov-report=term-missing` |
| Lint | `ruff check src tests` |
| Auto-fix lint issues | `ruff check --fix src tests` |
| Format | `ruff format src tests` |
| Check format | `ruff format --check src tests` |
| Type-check | `mypy src` (Phase 1 goal: strict-clean; Phase 0 baseline has known errors) |
| CLI help | `argo-decoder --help` |

These commands are identical on Linux, macOS, and Windows (PowerShell/cmd).

## Project layout

```
argo-decoder-python/
├── pyproject.toml                # build, deps, tool config
├── IMPLEMENTATION_PROGRESS.md    # append-only engineering log
├── config/
│   └── registry.csv              # bootstrapped demo registry (Phase 1+)
├── scripts/
│   └── bootstrap_registry.py     # one-off: legacy JSON → registry.csv
├── src/argo_decoder/
│   ├── cli/                      # Typer CLI (main + metadata subcommands)
│   ├── config/                   # Pydantic DecoderConfig
│   ├── metadata/                 # registry loaders + builder + validators
│   ├── io/                       # rsync discovery, NetCDF/XML writers
│   ├── domain/                   # pure dataclasses (frames, QC flags)
│   ├── platforms/                # per-platform decoder plugins
│   ├── sensors/                  # per-sensor decoders (Phase 3+)
│   ├── derived/                  # derived parameters (Phase 3+)
│   ├── rtqc/                     # real-time QC tests (Phase 3+)
│   ├── nc/                       # Argo NetCDF writers
│   ├── pipeline/                 # runner + oracle + dual_run + comparator + metadata_stage
│   └── util/                     # logging, time, hashing
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── golden/                   # reference outputs (populated in Phase 1+)
├── docs/
│   ├── architecture/
│   ├── developers/
│   ├── scientific/
│   ├── user/
│   ├── api/
│   └── phase_reports/
└── deploy/                       # Dockerfile, compose overlays (Phase 1+)
```

## Quick smoke test against the demo data

```bash
# JSON backend (legacy files):
argo-decoder decode-float 6902892 \
  --input ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/input \
  --info-dir ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/config/decArgo_config_floats/json_float_info \
  --meta-dir ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/config/decArgo_config_floats/json_float_meta_ir_sbd \
  --out ./out --null-decoder

# CSV backend (central registry):
argo-decoder decode-float 6902892 \
  --metadata-backend csv --registry config/registry.csv \
  --input ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/input \
  --out ./out_csv --null-decoder
```

Both should log `n_cycles=2215 n_files=2215` and produce one NetCDF per
cycle under `out*/nc/6902892/`.

## Metadata tooling

```bash
# Validate the central registry:
argo-decoder metadata validate config/registry.csv

# Materialize a decArgo_config_floats/ JSON tree from the registry:
argo-decoder metadata materialize config/registry.csv --out /tmp/gen_config
```

## Adding a new platform or sensor

1. Add a module under `platforms/<platform_family>/` or `sensors/<sensor>/`.
2. Implement the appropriate Protocol (`PlatformDecoder`, `SensorDecoder` — see existing docstrings).
3. Register via the `register_decoder` / `register_sensor` decorator.
4. Add a test fixture to `tests/unit/` with a golden-frame pair.
5. Run `pytest` and confirm the comparator reports zero mismatches on the
   relevant golden subset.

The decoder never imports platform/sensor modules directly — plugins are
discovered by importing their package (they self-register via the
decorator at import time). Adding a new platform never requires changes
to pipeline or config code beyond enabling the plugin.

## Coding standards

- All public functions have type hints and docstrings.
- No module-level mutable state besides loggers and caches.
- No `if decoder_id == 221: ... elif decoder_id == 222: ...` chains — use
  `decoder_table.yaml` rows.
- Science modules (`platforms/`, `sensors/`, `derived/`, `rtqc/`) MUST NOT
  import any concrete metadata loader (`csv_loader`, future sqlite/postgres
  loaders). They import only from `metadata.models` (`FloatInfo`,
  `FloatMeta`). This is enforced in code review.
- Determinism: sort order, NaN handling, and fill values are defined by
  helpers in `domain/`; do not hand-roll them in platform code.

## Documentation

Every phase appends a section to `IMPLEMENTATION_PROGRESS.md` and
updates relevant docs under `docs/`. PRs that add code without updating
the log fail review.
