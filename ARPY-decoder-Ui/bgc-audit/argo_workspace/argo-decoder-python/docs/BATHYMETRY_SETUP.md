# GEBCO bathymetry — what to download and how to wire it in

This unblocks two open items that are currently stuck on one missing dataset:

* **`GROUNDED`** in `Rtraj.nc` — we emit `'0'` on every cycle of every float
  (see the caveat in §6: `'0'` is not even a valid code)
* **RTQC TEST004** (position on land) — the last test INCOIS runs that we do
  not

---

## 1. Which file to download

**`GEBCO_2026 Grid (ice surface elevation)` → `netCDF`**
4 GB zipped, 7.0 GB uncompressed.

Direct link (from the GEBCO download page):

```
https://dap.ceda.ac.uk/bodc/gebco/global/gebco_2026/ice_surface_elevation/netcdf/GEBCO_2026.zip?download=1
```

That is row 1, column 1 of the table on the download page.

### Why each choice

**netCDF, not GeoTIFF or Esri ASCII — this is the decisive one.**
Coriolis reads the global netCDF directly and sub-sets it by coordinate. From
`decArgo_soft/soft/util/sub/get_gebco_elev_zone.m`:

```matlab
lonVarId  = netcdf.inqVarID(fCdf, 'lon');
latVarId  = netcdf.inqVarID(fCdf, 'lat');
elevVarId = netcdf.inqVarID(fCdf, 'elevation');
```

The function takes a lon/lat box and reads only that window. netCDF supports
random access, so a point lookup costs a few hundred bytes instead of loading
7 GB. Esri ASCII is **18.2 GB of text** and must be parsed linearly — unusable
for point queries.

**Global file, not the 8 tiles.**
Our floats span the entire globe: longitude **−180.0 to +179.9**, latitude
**−60.3 to +23.0** across 32,305 measured positions. They would cross most
tiles anyway, and stitching adds seam-handling code for no benefit. One file
also matches Coriolis's layout.

**Ice surface, not sub-ice.**
The two differ only beneath the Antarctic and Greenland ice sheets. Sub-ice
gives the rock below the ice; ice-surface gives the surface a float would
actually meet. For "is this position on land?" and "did the float touch
bottom?", ice-surface is the correct semantic. Only 195 of our 32,305
positions are south of −60°, so in practice the grids are near-identical for
this fleet — but ice-surface is right in principle and matches Coriolis.

**Skip the TID grid.** Type IDentifier describes each cell's provenance
(measured vs interpolated). Useful for uncertainty work, not for a land or
grounding test.

### Version note

Coriolis pins `GEBCO_2024.nc`; the site now offers **2026**. Newer is fine —
same variable names (`lon`, `lat`, `elevation`) and same structure. Record
which version was used, because a grounding flag can change if the bathymetry
changes.

---

## 2. Grid facts worth knowing

| property | value |
|---|---|
| resolution | 15 arc-seconds = 240 cells per degree ≈ 0.46 km |
| global shape | 43,200 rows × 86,400 cols = **3.73 G cells** |
| variables | `lon`, `lat`, `elevation` (metres, **positive up**) |
| sign convention | seabed is **negative**; land is **positive** |

`elevation > 0` therefore means land — that is the whole of TEST004.

---

## 3. Where to put it

The configuration slot **already exists**; nothing needs inventing:

```python
# src/argo_decoder/config/models.py
class RtqcReferenceFiles(BaseModel):
    gebco_file: Path = Path("/mnt/ref/gebco.nc")
    ...


class RtqcTestFlags(BaseModel):
    position_on_land: bool = True
```

and the environment/JSON key is `TEST004_GEBCO_FILE`.

So the whole install is:

The decoder looks for a file **named `gebco.nc`** inside a reference
directory, so point a link (or a copy) at your extracted grid:

```bash
# 1. unzip somewhere with ~8 GB free (outside the repository)
unzip GEBCO_2026.zip -d /data/ref/

# 2. expose it under the expected name
mkdir -p ~/argo-ref
ln -sfn /data/ref/GEBCO_2026.nc ~/argo-ref/gebco.nc

# 3a. normal decoding entry point
python scripts/generate_apex_argos_nc.py \
  --raw-root phase4_reference/raw/raw-files \
  --registry config/metadata \
  --output-root output/local \
  --ref ~/argo-ref --wmo 2901304

# 3b. or the CLI - same convention, same result
argo-decoder decode-float 2901304 \
  -i phase4_reference/raw/raw-files -o output/local --ref ~/argo-ref
```

Both entry points resolve `--ref <dir>` to `<dir>/gebco.nc`, so TEST004
behaves identically whichever one launches the decode.

**Note:** `export TEST004_GEBCO_FILE=...` does **not** work. That key is
read from the `decoder_conf.json` dictionary, not from the environment.
Use `--ref`, or set `"TEST004_GEBCO_FILE"` inside a config file passed
with `--config`.

**Treat the grid as an external dependency, not a repo file.** 7 GB must not
go into the workspace or git.

---

## 4. Storage options

The full grid is the right choice for production, but it is large. Measured
alternatives:

| option | global size (int16) | resolution | verdict |
|---|---|---|---|
| 15 arc-sec (native) | 7.5 GB | 0.46 km | **production** |
| 30 arc-sec | 1.9 GB | 0.93 km | good compromise |
| 1 arc-min | 0.47 GB | 1.85 km | fine for tests |
| 2 arc-min | 0.12 GB | 3.70 km | too coarse near coasts |

A latitude-band subset saves less than expected: restricting to lat −61..24
still leaves **3.5 GB**, because our floats occupy every longitude.

**Recommended split**

* **Production** — full 15 arc-sec grid on disk, path via config.
* **Tests/CI** — a small committed extract (a few MB) around a handful of
  known positions, so `TEST004` has deterministic fixtures without the 7 GB
  dependency.

---

## 5. How to use it in code

Mirror Coriolis: open once, read a small window per query, never load the
whole array.

```python
import netCDF4, numpy as np


class GebcoGrid:
    """Point lookups against the global GEBCO grid.

    Reads a 1x1 cell window per query rather than loading the array, so
    memory stays flat regardless of grid size.
    """

    def __init__(self, path):
        self._ds = netCDF4.Dataset(path)
        self._lon = self._ds.variables["lon"][:]
        self._lat = self._ds.variables["lat"][:]
        self._elev = self._ds.variables["elevation"]

    def elevation(self, lat, lon):
        if lon > 180.0:
            lon -= 360.0
        i = int(np.abs(self._lat - lat).argmin())
        j = int(np.abs(self._lon - lon).argmin())
        return float(self._elev[i, j])  # metres, positive = land
```

Only `lon`/`lat` (a few MB) are held in memory; `elevation` stays on disk.

Then the two consumers:

```python
# TEST004 - position on land
on_land = grid.elevation(lat, lon) > 0.0  # QC flag 4

# GROUNDED - did the float reach the seabed?
seabed_depth = -grid.elevation(lat, lon)  # metres, positive down
grounded = "Y" if max_pres_dbar >= seabed_depth - TOLERANCE else "N"
```

`TOLERANCE` must be calibrated, not guessed — see below.

---

## 6. Two cautions before implementing

**`GROUNDED` encoding is done.** We now write `'U'` (table 20 unknown)
when grounding cannot be decided. Do not invent `Y`/`N` without a
calibrated GEBCO comparison. Historical audits that reported `'0'` were
reading a netCDF4-masked space fill (`MaskedArray.filled(0)`).

**Calibrate the grounding threshold against the labels we already have.**
GDAC publishes `Y`/`N` for these floats — 2901339 has `Y`×54 / `N`×162,
2902222 has `Y`×116 / `N`×223. Those are ground truth for tuning `TOLERANCE`.
An earlier crude max-pressure heuristic scored only 13/16 on 2902222, so the
threshold genuinely needs fitting and cross-checking on more than one float.
Do not ship a guessed constant — that is exactly the hardcoded-constant
pattern that caused the earlier defects.

---

## 7. Checklist

- [ ] Download `GEBCO_2026.zip` (ice surface elevation, netCDF), ~4 GB
- [ ] Unzip to a stable path with ~8 GB free
- [ ] Set `TEST004_GEBCO_FILE` (or `rtqc.reference_files.gebco_file`)
- [ ] Record the grid version used
- [ ] Fix `GROUNDED` → `'U'` first — no GEBCO needed
- [ ] Add a small committed extract for tests
- [ ] Implement TEST004 (`elevation > 0` → QC 4)
- [ ] Calibrate the `GROUNDED` tolerance against GDAC's `Y`/`N` labels on at
      least three floats
