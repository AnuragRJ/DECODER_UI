# Running the Python decoder locally

The Python reference implementation of the Coriolis Argo float decoder is
designed to run on **both Linux and Windows** developer laptops with no
Docker or MATLAB Runtime required for the plumbing/null-decoder path.
Scientific decoding (real PROVOR/ARVOR/etc. frame parsing) is added in
later phases; the instructions below work for all currently-shipped
plumbing.

## Prerequisites

| Tool | Minimum | Notes |
|------|---------|-------|
| Python | 3.11 (tested on 3.12, 3.13) | The official `python.org` installer works on Windows. |
| [`uv`](https://github.com/astral-sh/uv) | latest | `pip install uv` on any OS. On Windows, a `uv.exe` shim is placed on `PATH`. |
| Git | any | To clone the two sibling repositories. |
| Docker Desktop (optional) | latest | Only required for `--oracle docker:` shadow runs against the MATLAB container. On Windows enable the WSL2 backend. |

## 1. Clone the repositories

The MATLAB container repository holds the demo dataset used throughout
Phase 0–1; put it as a **sibling** of the Python tree so the relative
paths in the examples below work.

### Linux / macOS

```bash
git clone https://github.com/euroargodev/Coriolis-data-processing-chain-for-Argo-floats-container.git
git clone <python-repo-url> argo-decoder-python
cd argo-decoder-python
```

### Windows (PowerShell)

```powershell
git clone https://github.com/euroargodev/Coriolis-data-processing-chain-for-Argo-floats-container.git
git clone <python-repo-url> argo-decoder-python
cd argo-decoder-python
```

## 2. Create a virtual environment and install

### Linux / macOS

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev,gsw]"
```

### Windows (PowerShell)

```powershell
uv venv --python 3.12 .venv
.venv\Scripts\Activate.ps1
uv pip install -e ".[dev,gsw]"
```

### Windows (cmd.exe)

```cmd
uv venv --python 3.12 .venv
.venv\Scripts\activate.bat
uv pip install -e ".[dev,gsw]"
```

If `python 3.12` is not found, substitute `3.11` or `3.13`. The project
supports all three.

## 3. Verify the CLI

```bash
argo-decoder --help
argo-decoder version
```

On Windows the entry point is `argo-decoder.exe` (created automatically
by `pip install -e`); if it is not on PATH you can invoke
`python -m argo_decoder.cli.main ...` as a fallback.

## 4. Run the null decoder against the demo data

The CLI now accepts explicit `--input`, `--out`, `--info-dir`,
`--meta-dir`, and `--ref` flags so you never have to rely on the
container's `/mnt/...` paths.

### Linux / macOS

```bash
argo-decoder --log-level INFO decode-float 6902892 \
  --input ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/input \
  --info-dir ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/config/decArgo_config_floats/json_float_info \
  --meta-dir ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/config/decArgo_config_floats/json_float_meta_ir_sbd \
  --out ./out \
  --null-decoder
```

### Windows (PowerShell)

```powershell
argo-decoder --log-level INFO decode-float 6902892 `
  --input ..\Coriolis-data-processing-chain-for-Argo-floats-container\decArgo_demo\input `
  --info-dir ..\Coriolis-data-processing-chain-for-Argo-floats-container\decArgo_demo\config\decArgo_config_floats\json_float_info `
  --meta-dir ..\Coriolis-data-processing-chain-for-Argo-floats-container\decArgo_demo\config\decArgo_config_floats\json_float_meta_ir_sbd `
  --out .\out `
  --null-decoder
```

### Windows (cmd.exe)

```cmd
argo-decoder --log-level INFO decode-float 6902892 ^
  --input ..\Coriolis-data-processing-chain-for-Argo-floats-container\decArgo_demo\input ^
  --info-dir ..\Coriolis-data-processing-chain-for-Argo-floats-container\decArgo_demo\config\decArgo_config_floats\json_float_info ^
  --meta-dir ..\Coriolis-data-processing-chain-for-Argo-floats-container\decArgo_demo\config\decArgo_config_floats\json_float_meta_ir_sbd ^
  --out .\out ^
  --null-decoder
```

Expected: the log ends with `pipeline_end ... n_cycles=2215 n_files=2215`
and `out\nc\6902892\` contains one NetCDF per Iridium SBD cycle, plus
`out\xml\co041404_<timestamp>_6902892.xml`.

> **Note:** WMO 6902892 is the smaller of the two demo floats (2215 SBD
> files). WMO 6903014 has 3634 files and is a good next check after the
> plumbing run succeeds.

## 5. Run tests and linting

```bash
pytest -q
ruff check src tests
ruff format --check src tests
mypy src    # strict mode; Phase 0 has known errors — see IMPLEMENTATION_PROGRESS.md
```

These commands are identical on Linux and Windows.

## 6. Dual-run (shadow) mode

To run the Python decoder side-by-side against the MATLAB container
(Docker required):

```bash
argo-decoder dual-run 6902892 \
  --input ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/input \
  --config ../Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/config/decoder_conf.json \
  --oracle docker:ghcr.io/euroargodev/coriolis-data-processing-chain-for-argo-floats-container:082m \
  --out ./out_shadow \
  --report ./out_shadow/report.json
```

On Windows with Docker Desktop + WSL2 this works transparently:
`Path.resolve()` produces canonical Windows paths and Docker Desktop
translates them into the Linux VM.

For offline/CI use, substitute `--oracle file:<path-to-golden>` to
compare against previously-captured reference outputs.

## Known Windows-specific notes

- Long paths (>260 characters) are enabled by default on Windows 10
  1607+ when the application is manifested; if you hit `ENOENT` on very
  deep output trees, enable long paths via
  `Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Value 1`
  (administrator PowerShell).
- All paths inside the codebase use `pathlib.Path`, so forward slashes
  on the command line also work on Windows.
- The Docker oracle passes `--user <uid>:<gid>` only on POSIX; on
  Windows that flag is skipped because Docker Desktop handles file
  ownership through the SMB/WSL2 share.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `No metadata found for WMO` | `--info-dir` / `--meta-dir` point to the wrong directory | Point at the `json_float_info` / `json_float_meta_ir_sbd` directories directly. |
| `input_files n=0` | Input layout mismatch | The `--input` root must contain `archive/cycle/<IMEI>/...` and `rsync_list/...`; the demo layout puts SBD files directly under `input/cycle/` — the CLI auto-detects that case. |
| `argo-decoder` not found on Windows | The virtualenv is not activated, or `Scripts\` isn't on PATH | Activate `.venv\Scripts\Activate.ps1`, or use `python -m argo_decoder.cli.main ...`. |
| Docker mount error on Windows | File not shared in Docker Desktop settings | Enable the drive containing the repo under Docker Desktop → Settings → Resources → File Sharing. |
