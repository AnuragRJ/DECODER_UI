# Running the decoder locally on Windows (uv)

End-to-end: environment → metadata materialisation → decode → verify.
PowerShell syntax; `cmd.exe` differences are noted where they matter.

## 0. Prerequisites

- Python 3.11+ (3.13 used in development)
- [uv](https://docs.astral.sh/uv/) — install once:
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

## 1. Create and activate the virtual environment

```powershell
cd C:\path\to\argo-decoder-python

uv venv --python 3.13
.\.venv\Scripts\Activate.ps1
```

`cmd.exe` instead: `.\.venv\Scripts\activate.bat`

If PowerShell blocks the script:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 2. Install the package

```powershell
uv pip install -e ".[dev,gsw]"
```

`gsw` is required — without it the CNDC/density/DOXY paths silently skip.

Verify:
```powershell
python -c "import argo_decoder, gsw, netCDF4; print('ok')"
```

## 3. Metadata: the four CSVs

Live in `config\metadata\`:

```
config\metadata\meta.csv
config\metadata\sensor-info.csv
config\metadata\calib.csv
config\metadata\config_params.csv
```

They must be **real UTF-8 CSVs**, not renamed Excel workbooks. To convert
`.xlsx` exports:

```powershell
uv pip install openpyxl
python - <<'PY'
import openpyxl, csv, pathlib
SRC = pathlib.Path("path/to/xlsx"); OUT = pathlib.Path("config/metadata")
OUT.mkdir(parents=True, exist_ok=True)
# (source stem, output name, 0-based header row, 0-based first data row)
for stem, name, hdr, start in [
    ("meta", "meta.csv", 1, 2),
    ("sensor-info", "sensor-info.csv", 0, 1),
    ("calib", "calib.csv", 1, 2),
]:
    ws = openpyxl.load_workbook(SRC / f"{stem}.xlsx", data_only=True)["Sheet1"]
    rows = [[("" if c is None else str(c).strip()) for c in r]
            for r in ws.iter_rows(values_only=True)]
    n = max(len(r) for r in rows)
    pad = lambda r: list(r) + [""] * (n - len(r))
    with (OUT / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(pad(rows[hdr]))
        w.writerows(pad(r) for r in rows[start:] if any(r))
# config-params has a two-tier header: official CONFIG_* names win.
ws = openpyxl.load_workbook(SRC / "config-params.xlsx", data_only=True)["Sheet1"]
rows = [[("" if c is None else str(c).strip()) for c in r]
        for r in ws.iter_rows(values_only=True)]
n = max(len(r) for r in rows)
pad = lambda r: list(r) + [""] * (n - len(r))
r0, r1 = pad(rows[0]), pad(rows[1])
hdr = [r1[i] if r1[i].startswith("CONFIG_") else (r0[i] or r1[i] or f"col{i}")
       for i in range(n)]
with (OUT / "config_params.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(hdr)
    w.writerows(pad(r) for r in rows[2:] if any(r))
PY
```

### Materialise `info.json` / `meta.json`

The decoder consumes JSON, not CSV. This step is normally implicit
(the pipeline materialises into a cache), but run it explicitly when you
want to feed the JSON back in via `--info-dir` / `--meta-dir`:

```powershell
argo-decoder metadata materialize config\metadata -o meta_out --flat --wmo 2901304
```

Produces `2901304_102525_info.json` and `2901304_meta.json` side by side
in `meta_out`, which is the layout `--info-dir`/`--meta-dir` expect when
both point at the same directory. Drop `--flat` for the MATLAB-style
`json_float_info/` + `json_float_meta_*/` tree.

> **Pass the metadata *directory*, not a CSV.** `config\metadata` selects
> the four-CSV backend, which is the only one carrying the pre-deployment
> calibration. Materialising from the legacy single `registry.csv` writes
> `"n/a"` into every `PREDEPLOYMENT_CALIB_*` field, and the Argo file
> checker then rejects the resulting `_meta.nc` with six `Empty` errors.
> **Re-run this step whenever the CSVs change** — stale JSON is silently
> accepted.

A `multi_csv_incomplete` warning means a float is missing from one of the
sheets — expected, not fatal.

## 4. Lay out the raw files

Group by PTT (the Argos number), one directory per float:

```
raw\102525\102525_2011-02-13.txt
raw\102525\102525_2011-02-24.txt
...
```

Both naming conventions are recognised:
- `<ptt>_<YYYY-MM-DD>_<wmo>_<cycle>.txt` — cycle from the file name
- `<ptt>_<YYYY-MM-DD>.txt` — cycle taken from the telemetry

## 5. Decode

```powershell
python scripts\generate_apex_argos_nc.py `
    --raw-root  raw `
    --registry  config\metadata `
    --output-root out `
    --wmo 2901304
```

`--registry` pointing at a **directory** selects the four-CSV backend;
pointing at a **file** keeps the legacy single `registry.csv`.
Omit `--wmo` to run every float in the sheets.

The `argo-decoder` CLI is equivalent, and reads the same ARGOS layout:

```powershell
argo-decoder decode-float 2901304 -i raw -o out `
    --info-dir meta_out --meta-dir meta_out
```

`-i` accepts either an Iridium tree (`archive\cycle` + `rsync_list`) or an
ARGOS archive (one `<ptt>\` directory of `*.txt` per transmitter) and
detects which it was given. A decode that discovers **no** files for the
requested WMO now exits non-zero with `no_input_files`, naming the
directory it searched — it no longer reports success after writing only
`<wmo>_meta.nc`.

Outputs land in `out\nc\<wmo>\`:

```
out\nc\2901304\2901304_meta.nc
out\nc\2901304\2901304_tech.nc
out\nc\2901304\2901304_Rtraj.nc
out\nc\2901304\2901304_prof.nc
out\nc\2901304\profiles\R2901304_001.nc ...
```

## 6. Verify

```powershell
# Format: must be NETCDF3_CLASSIC with one record dimension
python - <<'PY'
import netCDF4, glob
for f in sorted(glob.glob("out/nc/**/*.nc", recursive=True)):
    with netCDF4.Dataset(f) as d:
        unl = [n for n, x in d.dimensions.items() if x.isunlimited()]
    assert d.data_model == "NETCDF3_CLASSIC", f
    assert open(f, "rb").read(4) == b"CDF\x01", f
    assert len(unl) == 1, (f, unl)
print("all NETCDF3_CLASSIC, single record dim")
PY

# Regression suite
python -m pytest -q

# Audits (need the reference tree under phase5_reference/)
python scripts\audit_metadata_admt.py
python scripts\audit_mono_profile_values.py
python scripts\audit_technical_admt.py
```

## 7. Compare against GDAC

```powershell
$wmo = 2901304
New-Item -ItemType Directory -Force gdac | Out-Null
foreach ($p in "meta","tech","Rtraj","prof") {
  Invoke-WebRequest "https://data-argo.ifremer.fr/dac/incois/$wmo/${wmo}_$p.nc" `
      -OutFile "gdac\${wmo}_$p.nc"
}
```

Then diff field-by-field:

```powershell
python - <<'PY'
import netCDF4, numpy as np
def val(d, v):
    a = d.variables[v][:]; arr = np.atleast_1d(np.asarray(a))
    if arr.dtype.kind == "S":
        return [str(x).strip() for x in np.atleast_1d(netCDF4.chartostring(a)).ravel()]
    return [f"{x:g}" for x in arr.ravel()]
a = netCDF4.Dataset("out/nc/2901304/2901304_meta.nc")
b = netCDF4.Dataset("gdac/2901304_meta.nc")
common = sorted(set(a.variables) & set(b.variables))
diff = [v for v in common if val(a, v) != val(b, v)]
print(f"{len(common)-len(diff)}/{len(common)} fields match; differ: {diff}")
a.close(); b.close()
PY
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `raw_files=0` | Raw directory not named after the PTT, or filenames unrecognised |
| `multi_csv_incomplete` warning | Float missing from one sheet — check `calib.csv` |
| `ModuleNotFoundError: gsw` | Install with the `[gsw]` extra |
| Binary junk when opening a CSV | It is a renamed `.xlsx`; convert it (step 3) |
| `multi_profile_build_failed` | Known issue — see the limitations note |
