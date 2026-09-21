# Deploy — container and compose overlays

This directory contains the Python container image definition and compose
overlays used for staging shadow deployments during the migration. The
MATLAB container is **never modified**; the Python container runs as a
parallel shadow reading the same `:ro` input tree and writing to a
separate output volume.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage-ready Python image (Phase 1: plumbing + metadata). Runs as non-root, uses `tini`, sets `ARGO_DECODER_CONTAINER=1` so config defaults pick the POSIX `/mnt/...` paths. |
| `compose.python-shadow.yaml` | Compose overlay that adds an `argo-python-shadow` service alongside the existing MATLAB stack. Mounts the same volumes read-only, points at a dedicated Python output volume, drives the decoder from the CSV registry. |

## Building

```bash
docker build -f deploy/Dockerfile -t argo-decoder-python:dev .
```

## Running locally against the demo data

```bash
# From the repo root:
docker run --rm \
  -v ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/input:/mnt/data/rsync:ro \
  -v ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/config:/mnt/data/config:ro \
  -v "$(pwd)/config/registry.csv:/mnt/metadata/registry.csv:ro" \
  -v "$(pwd)/out:/mnt/data/output:rw" \
  argo-decoder-python:dev \
  argo-decoder decode-float 6902892 \
    --metadata-backend csv --registry /mnt/metadata/registry.csv \
    --null-decoder
```

On Windows (PowerShell) the same `docker run` works if you replace
`$(pwd)` with the absolute Windows path (e.g. `C:\path\to\...`) and use
forward slashes. Docker Desktop + WSL2 accepts Windows host paths in
volume mounts.

## Shadow deployment

The compose overlay expects the same environment variables as the
MATLAB stack plus `METADATA_REGISTRY_FILE` pointing at the
`registry.csv` to mount. The Python service writes to
`${DECODER_DATA_PYTHON_OUTPUT_VOLUME}` which should NOT be the MATLAB
output volume — the diff harness reads from both trees.

Phase 1 ships the plumbing image (null decoder + CSV metadata + NetCDF/XML
structural output). Phases 2+ layer science modules on top; the image is
rebuilt and version-tagged per merge to `main`.
