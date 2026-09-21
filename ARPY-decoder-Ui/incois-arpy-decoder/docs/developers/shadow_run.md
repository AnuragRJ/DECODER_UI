# Phase 3 Shadow Run HOWTO

Phase 3 is validated end-to-end against the MATLAB reference running inside
the official Euro-Argo Coriolis Docker + MCR image
(`ghcr.io/euroargodev/coriolis-data-processing-chain-for-argo-floats-container:082m`).
The `shadow` CLI command is the primary developer entry point: it drives
the MATLAB oracle **and** the Python decoder against the same inputs, then
compares NetCDF outputs on a per-variable, per-tolerance basis.

This document describes how to run shadow comparisons locally and how to
interpret the results.

## Prerequisites

* Docker installed and running (Docker Desktop on Windows/macOS, `docker`
  package on Linux). The user running `argo-decoder` must be able to
  `docker run` without `sudo` (or invoke from an elevated shell on
  Windows).
* The Euro-Argo container pulled locally:

  ```bash
  docker pull ghcr.io/euroargodev/coriolis-data-processing-chain-for-argo-floats-container:082m
  ```

* The decoder installed in editable mode with dev + GSW extras:

  ```bash
  pip install -e ".[dev,gsw]"
  ```

* Demo / test inputs: a tree containing `archive/cycle/<imei>/co_*.txt`
  and `rsync_list/`, plus the companion metadata
  (`decArgo_config_floats/json_float_info/<wmo>_<imei>_info.json` and
  `json_float_meta_ir_sbd/<wmo>_meta.json`).

## Running a shadow comparison (Docker oracle)

From the project root, using the bundled demo data:

```bash
argo-decoder shadow 6902892 \
    --input  /path/to/decArgo_demo/input \
    --out    ./out/shadow_6902892 \
    --config /path/to/decArgo_demo/config/decoder_conf.json \
    --info-dir /path/to/decArgo_demo/config/decArgo_config_floats/json_float_info \
    --meta-dir /path/to/decArgo_demo/config/decArgo_config_floats/json_float_meta_ir_sbd
```

Or equivalently, using the explicit `dual-run` subcommand:

```bash
argo-decoder dual-run 6902892 \
    --input  ... --out ... \
    --oracle docker:ghcr.io/euroargodev/coriolis-data-processing-chain-for-argo-floats-container:082m
```

Output layout:

```
out/shadow_6902892/
  oracle/nc/6902892/*.nc   # MATLAB reference NetCDFs
  oracle/xml/*.xml         # MATLAB XML report
  python/nc/6902892/*.nc   # Python NetCDFs
  python/xml/*.xml         # Python XML report
```

The CLI exits with code `0` when there are zero error-severity mismatches
and with code `2` (and a structured log line per mismatch) otherwise. Pass
`--report report.json` to also emit a machine-readable JSON diff report.

## Offline / CI mode (file oracle)

When Docker is unavailable (sandboxed CI, offline workstation), point the
dual-run harness at a pre-generated reference corpus using the
`file:<path>` oracle spec:

```bash
argo-decoder dual-run 6902892 \
    --input  ./demo/input --out ./out/shadow \
    --oracle file:./tests/golden/6902892_ref
```

The file oracle simply copies every `nc/<wmo>/*.nc` and `xml/*_<wmo>.xml`
file from the reference directory into the oracle output tree before the
comparator runs. A small golden reference corpus may be added at a later
Phase-3 milestone to accelerate CI smoke tests; it is **not** a
prerequisite for starting Phase 3 work (Docker/MCR remains the
authoritative oracle).

## Tolerances

The comparator enforces the tolerance policy defined in the migration
plan:

| Variable         | rtol / atol                              |
|------------------|------------------------------------------|
| QC flags         | exact character match                    |
| `PRES`           | rtol 1e-3 dbar                           |
| `TEMP`/`CNDC`/`PSAL` | rtol 1e-6                            |
| `DOXY`           | rtol 1e-2 µmol/kg                        |
| `JULD`           | atol 1 ms (in days)                      |
| `LATITUDE`/`LONGITUDE` | atol 1e-7 degrees                   |
| Dimensions, variable set, global attributes, NaN/fill mask | exact |

Additional BGC variables are registered with defaults as they land in
M3/M4 and are tightened against the oracle.

## Phase 3 milestone gating

Each M-slice (M1 harness, M3 GSW/CNDC, M2 RTQC, M4 Optode DOXY,
M5 trajectory, M6 multi-profile) is gated on a clean shadow run over the
WMO 6902892 corpus: **zero error-severity mismatches** across every
variable implemented so far. Any deviation from MATLAB that exceeds the
registered tolerance must be:

1. Reproduced on at least one cycle via `shadow`,
2. Signed off by a scientist with an explicit tolerance-bump entry in
   `pipeline/comparator.py` (see `_DEFAULT_RTOL` / `_DEFAULT_ATOL`),
3. Logged in `IMPLEMENTATION_PROGRESS.md`.

## Cross-platform notes

* All paths are constructed with `pathlib.Path`. No shell invocation is
  used (`subprocess.run(..., shell=False)` everywhere); paths are passed
  to Docker as explicit `-v` mount args.
* On Windows, Docker Desktop handles UID/GID translation automatically;
  the `--user` flag is only added on POSIX systems.
* Temporary directories default to `tempfile.gettempdir()`. Override
  with `--tmp` if you need a scratch drive with sufficient space for a
  full 2215-cycle run.
* On Linux you may need to add your user to the `docker` group once:
  `sudo usermod -aG docker $USER && newgrp docker`.
