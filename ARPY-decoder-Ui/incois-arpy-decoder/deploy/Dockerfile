# syntax=docker/dockerfile:1.6
#
# Python Argo decoder image.
#
# This image provides the ``argo-decoder`` CLI and is designed to run as a
# shadow container alongside the MATLAB container per the Direct Migration
# plan (Strategy A+). It mounts the same input tree read-only and writes
# to a separate shadow output tree.
#
# Build:
#   docker build -f deploy/Dockerfile -t argo-decoder-python:dev .
#
# Run:
#   docker run --rm \
#     -v /path/to/rsync:/mnt/data/rsync:ro \
#     -v /path/to/config:/mnt/data/config:ro \
#     -v /path/to/registry.csv:/mnt/metadata/registry.csv:ro \
#     -v /path/to/ref:/mnt/ref:ro \
#     -v /path/to/output:/mnt/data/output:rw \
#     argo-decoder-python:dev \
#     argo-decoder decode-float 6902892 \
#       --metadata-backend csv --registry /mnt/metadata/registry.csv \
#       --null-decoder
#
# Phase 1 ships the plumbing image; science modules are added in later phases.

FROM python:3.12-slim AS base

# Set container-mode flag: tells config defaults to use the POSIX /mnt paths.
ENV ARGO_DECODER_CONTAINER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1

# System deps for netCDF4 / numpy / lxml
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libhdf5-dev libnetcdf-dev libxml2-dev libxslt1-dev \
        ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app

# Install Python deps (cached layer)
COPY pyproject.toml README.md ./
RUN uv pip install --system --no-cache-dir -e ".[gsw]"

# Copy source
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/
RUN uv pip install --system --no-cache-dir -e "."

# Runtime mount points:
#   /mnt/data/rsync   - input SBD rsync tree (read-only)
#   /mnt/data/config  - decoder_conf.json and legacy json_float_info/ (read-only)
#   /mnt/metadata     - registry.csv (read-only)
#   /mnt/ref          - RTQC reference data (read-only)
#   /mnt/runtime      - MATLAB runtime (only used by docker-oracle, not here)
#   /mnt/data/output  - shadow outputs (read-write)
RUN mkdir -p /mnt/data/rsync /mnt/data/config /mnt/metadata /mnt/ref \
             /mnt/runtime /mnt/data/output /mnt/data/tmp

WORKDIR /mnt/data

# Use tini for PID 1 signal handling
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["argo-decoder", "--help"]
