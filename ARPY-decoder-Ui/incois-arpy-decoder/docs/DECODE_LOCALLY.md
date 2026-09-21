# Decoding APEX APF9 floats locally

Every command below was executed in this workspace and its output verified.
Linux/macOS shown; Windows notes at the end.

---

## 0. One-time setup

```bash
cd argo-decoder-python
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev,gsw]"
argo-decoder version
```

`gsw` is not optional in practice: it computes CNDC and drives the TEST014
density-inversion check. Without it CNDC comes out as fill.

---

## 1. Pick the right metadata backend — this matters

There are two, and they are **not** equivalent. Choose by float, not by taste.

| backend | how to select | floats covered |
|---|---|---|
| four-CSV (`config/metadata/`) | `scripts/generate_apex_argos_nc.py --registry config/metadata` | 2901304, 2901305, 2902222, 2902223, 2902224 |
| single registry (`config/registry.csv`) | `argo-decoder ... --metadata-backend csv --registry config/registry.csv` | 2901339, 2902201, 2902222, 2902223 (+2 non-APF9) |

Measured difference on the *same float* (2902222, same raw files):

| | `N_CONFIG_PARAM` | `PREDEPLOYMENT_CALIB_EQUATION` | RTQC `QCP$` |
|---|---|---|---|
| single registry | 1 (none named) | empty | `57B6E` — 13 tests, **no TEST019** |
| four-CSV | **14 named** | populated | `D7B6E` — **14 tests incl. TEST019** |

TEST019 (deepest pressure) needs `CONFIG_ProfilePressure_dbar`, which only the
four-CSV backend supplies. **Prefer four-CSV when the float is in it.**

> Known limitation: the `argo-decoder` CLI declares `--registry` as
> `dir_okay=False`, so it cannot reach the four-CSV backend. Use the script
> for those floats until that is lifted.

---

## 2. Decode — four-CSV backend (preferred)

```bash
python scripts/generate_apex_argos_nc.py \
  --raw-root phase4_reference/raw/raw-files \
  --registry config/metadata \
  --output-root output/local \
  --wmo 2902222 --wmo 2902223
```

`--wmo` repeats for multiple floats. Passing a **directory** to `--registry`
is what selects the four-CSV backend; a **file** selects the single registry.

For 2901304 the raw files are not in the repo — point `--raw-root` at a
directory containing `102525/`:

```bash
python scripts/generate_apex_argos_nc.py \
  --raw-root /path/to/raw1304 \
  --registry config/metadata \
  --output-root output/local_2901304 \
  --wmo 2901304
```

## 3. Decode — CLI (single registry)

```bash
argo-decoder decode-float 2902222 \
  -i phase4_reference/raw/raw-files \
  -o output/local_cli \
  --metadata-backend csv \
  --registry config/registry.csv
```

`-i` detects an ARGOS archive structurally (a numeric `<ptt>/` child holding
`*.txt`), so point it at the **parent** of `152389/`, not at `152389/` itself.
Add `-l DEBUG` for per-message logging; `--json-logs` for machine-readable output.

---

## 4. Raw-file naming — the trap that silently corrupts cycles

| form | cycle comes from |
|---|---|
| `<ptt>_<YYYY-MM-DD>.txt` | telemetry |
| `<ptt>_<YYYY-MM-DD>_<wmo>_<NNN>.txt` | the filename |

For **2901304 use the short form**. With the long form two files both parse to
cycle `000`, collide, and yield cycles `[2,3,16]` instead of `[1,2,3]`.

---

## 5. What you get

```
output/local/
├── nc/<wmo>/
│   ├── <wmo>_meta.nc  <wmo>_tech.nc  <wmo>_Rtraj.nc  <wmo>_prof.nc
│   └── profiles/R<wmo>_<NNN>.nc
├── xml/   log/   csv/
```

Sanity check:

```bash
python -c "
import netCDF4,glob
for f in sorted(glob.glob('output/local/nc/2902222/profiles/*.nc')):
    d=netCDF4.Dataset(f); print(f.split('/')[-1], 'levels', d.dimensions['N_LEVELS'].size); d.close()"
```

---

## 6. Compare against the GDAC

```bash
# fetch reference
mkdir -p ref/2902222/profiles && cd ref/2902222
for v in Rtraj meta tech; do
  curl -sO "https://data-argo.ifremer.fr/dac/incois/2902222/2902222_$v.nc"; done
cd profiles && for c in 327 328 329; do
  curl -sfO "https://data-argo.ifremer.fr/dac/incois/2902222/profiles/R2902222_$c.nc"; done
cd ../../..

# QC comparison
python scripts/audit_qc_diffs.py \
  --float "2902222=output/local/nc/2902222=ref/2902222"
```

⚠️ For **2901304 and 2901339 the GDAC serves D-files** (delayed mode). Raw
per-level QC diffs against those are inflated — 2901304 reports 98 cells, of
which **90 are Coriolis delayed-mode re-flagging from 2013**, not real-time
disagreement. Reconstruct real-time state from `HISTORY_PREVIOUS_VALUE` before
judging. See `QC_DIFF_REPORT.md`.

Other audits:

```bash
python scripts/audit_mono_profile_values.py   # 1813/1813 bit-identical
python scripts/audit_technical_admt.py        # 817/817
python scripts/audit_trajectory_admt.py
python scripts/audit_metadata_admt.py
```

---

## 7. Onboarding a float that is in neither backend

```bash
curl -sO "https://data-argo.ifremer.fr/dac/incois/<WMO>/<WMO>_meta.nc"
python scripts/registry_row_from_meta_nc.py <WMO>_meta.nc            # preview
python scripts/registry_row_from_meta_nc.py <WMO>_meta.nc --append   # commit
```

Every field is copied from the official metadata — nothing invented, blanks
stay blank. It currently omits `profile_count_offset`; add it manually
(`0` unless the float is known to offset).

---

## 8. Checks before committing

```bash
ruff check src tests scripts && ruff format --check src tests scripts
mypy --strict src
pytest -q
```

Current baseline: **680 passed**, ruff/format clean on 124 files,
`mypy --strict` clean on 71 source files.

---

## 9. Windows

Use `.venv\Scripts\activate`; everything else is identical (all paths go
through `pathlib`). See `docs/RUN_LOCALLY_WINDOWS.md`. Use `curl.exe` in
PowerShell — bare `curl` is an alias for `Invoke-WebRequest`.

## 10. Troubleshooting

| symptom | cause |
|---|---|
| `argo-decoder: command not found` | venv not active, or `pip install -e` not run |
| `ModuleNotFoundError: structlog` | same |
| `no_input_files`, exit 1 | `-i` pointed at `<ptt>/` instead of its parent |
| cycles `[2,3,16]` on 2901304 | long-form filenames — see §4 |
| `PREDEPLOYMENT_CALIB_*` empty | single-registry backend; use four-CSV (§1) |
| TEST019 missing from `QCP$` | same |
| CNDC all fill | `gsw` missing — reinstall with `.[dev,gsw]` |
