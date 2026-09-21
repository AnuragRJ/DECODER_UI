# argo-decoder (Python)

Python reference implementation of the Coriolis Argo float real-time decoder.
This is a Phase-0 skeleton of the direct greenfield migration described in
[MIGRATION_DIRECT_PLAN.md](../Coriolis-data-processing-chain-for-Argo-floats-container/MIGRATION_DIRECT_PLAN.md).

Status: **pre-Alpha (Phase 0 skeleton, cross-platform hardened)** — runs the
end-to-end plumbing pipeline (config → metadata → rsync discovery → null
decoder → NetCDF/XML write) on **Linux and Windows**, and supports a dual-run
harness comparing outputs against either the MATLAB container or a file-based
oracle for CI.

## Quick start (Linux / macOS)

```bash
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev,gsw]"

# Null-decoder smoke test against the in-repo demo data (no Docker needed):
argo-decoder --log-level INFO decode-float 6902892 \
    --input ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/input \
    --info-dir ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/config/decArgo_config_floats/json_float_info \
    --meta-dir ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/config/decArgo_config_floats/json_float_meta_ir_sbd \
    --out ./out \
    --null-decoder
```

## Quick start (Windows PowerShell)

```powershell
uv venv --python 3.12
.venv\Scripts\Activate.ps1
uv pip install -e ".[dev,gsw]"

argo-decoder --log-level INFO decode-float 6902892 `
    --input ..\Coriolis-data-processing-chain-for-Argo-floats-container\decArgo_demo\input `
    --info-dir ..\Coriolis-data-processing-chain-for-Argo-floats-container\decArgo_demo\config\decArgo_config_floats\json_float_info `
    --meta-dir ..\Coriolis-data-processing-chain-for-Argo-floats-container\decArgo_demo\config\decArgo_config_floats\json_float_meta_ir_sbd `
    --out .\out `
    --null-decoder
```

The CLI supports `--input/-i`, `--out/-o`, `--info-dir`, `--meta-dir`,
`--ref`, and `--tmp` overrides so you never need to edit the MATLAB JSON
config or rely on `/mnt/...` container paths. Full copy-pasteable guides
for bash, PowerShell, and cmd.exe live in
[`docs/user/running_locally.md`](docs/user/running_locally.md).

## Dual-run (shadow) mode

```bash
argo-decoder dual-run 6902892 \
    --input ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/input \
    --config ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/config/decoder_conf.json \
    --oracle docker:ghcr.io/euroargodev/coriolis-data-processing-chain-for-argo-floats-container:082m \
    --out ./out_shadow \
    --report ./out_shadow/report.json
```

Use `--oracle file:<path>` for CI / offline use when Docker is unavailable.

## Tests and lint

```bash
pytest -q
ruff check src tests
ruff format --check src tests
mypy src
```

## Layout

```
src/argo_decoder/
├── cli/          Typer CLI (decode-float, dual-run, validate-config, version)
├── config/       Pydantic DecoderConfig (OS-aware defaults)
├── metadata/     MetadataLoader protocol + JSON backend (CSV/SQLite/Postgres later)
├── io/           fs/rsync/xml_report writers
├── domain/       Pure dataclasses (frames, QC flags)
├── platforms/    PlatformDecoder plugin registry + NullDecoder
├── sensors/      (Phase 3–4)
├── derived/      (Phase 3)
├── rtqc/         (Phase 3)
├── nc/           xarray NetCDF writer
├── pipeline/     runner + oracle + dual_run + comparator
└── util/         logging, hashing, time
```

## Engineering log

Implementation progress, per-phase architecture notes, validation results, and
known limitations are maintained in
[`IMPLEMENTATION_PROGRESS.md`](IMPLEMENTATION_PROGRESS.md) (append-only).
