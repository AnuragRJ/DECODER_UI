# Fleet basemap toolchain

Provenance, calibration and verification for
`frontend/src/assets/fleet_basemap.jpg` — the offline satellite/terrain
world the Fleet Map renders (plate‑carrée 1920×960, lon −180…+180 → x,
lat +90…−90 → y, the same frame the Natural Earth vector overlay uses, so
both layers stay *registered*, i.e. drawn with the identical transform).

## Source & projection model

The source is a screenshot (`/home/user/uploads/image-1.png`, 1687×758,
not versioned — override its location via `BASEMAP_SRC`) that shows ~2.5
horizontally wrapped copies of a Web‑Mercator world (period `P=819` px,
x‑crop 54 px), plus small UI artifacts in the corners.

Web‑Mercator georeference of the source world copy:

```
source col = P*(lon+180)/360 + C        P=819, C=+1.75 px (lon phase)
source row = A − B·z(lat)               z = ln tan(π/4 + φ/2)
```

| parameter | WRONG assumption (old asset) | CALIBRATED (current asset) |
|---|---|---|
| A (row of equator) | 379.0 (= H/2, “equator‑centred band”) | **411.0** |
| B (z‑scale) | 819/2π = 130.35 | **130.25** |
| C (lon phase) | 0.0 | **+1.75** |

The original `build_basemap.py` assumed the band was centred on the
equator. Fitting Natural‑Earth 110 m coastlines onto the source frame
(`calibrate_basemap.py`, chamfer distance to the raster land/sea edge,
staged coarse→fine grid: score 7.56 → 2.28) showed the band is offset
~+32 source px — latitude bounds are +85.1°…−82.0°, not ±83.75°. Fitted
B ≈ P/2π confirms pure Web Mercator: only the *registration* was wrong,
producing a ~6° latitude‑varying displacement baked into the old asset.

## Usage

```bash
# 0. Natural Earth boundary rings (needs frontend node_modules):
node -e "
const fs=require('fs');const world=require('world-atlas/land-110m.json');
const topojson=require('topojson-client');
const mesh=topojson.mesh(world,world.objects.land);
const rings=[];const c=(x)=>{if(Array.isArray(x[0])&&typeof x[0][0]==='number'){rings.push(x);return;}x.forEach(c);};
c(mesh.coordinates);fs.writeFileSync('/tmp/land_rings.json',JSON.stringify(rings));"
#   (override location via NE_RINGS)

# 1. (already done) re-derive A/B/C if the source ever changes:
python3 tools/basemap/calibrate_basemap.py

# 2. regenerate the deployed asset (identical pipeline to the original
#    build — period detect/phase align/copy averagine/artifact patching —
#    with the calibrated georeference):
python3 tools/basemap/rebuild_basemap.py           # -> src/assets/fleet_basemap.jpg

# 3. verify in the app's plate-carrée frame (prints per-region mean
#    NE-boundary → raster-coast distances; emits /tmp/asset_aligned_*.jpg):
python3 tools/basemap/verify_asset.py
```

`rebuild_basemap.py` reproduces the currently committed asset
**byte‑identically** (sha256) — the asset is self-documenting, not a
hand-tuned blob.

`verify_calib.py` compares old‑vs‑new georeference per region on the
source frame and writes `/tmp/align_source_compare.jpg`.

`build_basemap.py` is kept (with its band‑centring assumption) as the
historical reference — use `rebuild_basemap.py` to regenerate.

## Measured registration (this asset, `verify_asset.py`)

| region | mean px to raster coast |
|---|---|
| India/Sri Lanka | 0.69 |
| Africa west | 1.19 |
| Europe | 1.70 |
| Asia E/Japan | 1.42 |
| S. America E | 1.08 |
| N. America | 1.99 |
| Australia/Tasmania | 1.39 |
| SE Asia | 2.01 |
| Greenland/N edge (band edge) | 5.67 |

(Old asset: ~11–25 asset px, latitude‑varying — visibly offset.)

## Notes / dead ends

- Full‑mask or edge‑band xor probes (`probe_align*.py`) are noise‑dominated
  at 110 m generalisation scale and were abandoned; the decisive metric is
  chamfer distance from NE boundary samples to the raster coast.
- The app draws the asset through the same plate‑carrée frame as the
  vector overlay and splits NE rings at antimeridian jumps — see the
  commit history (`4ab6a70`) and `e2e/geoVerify.mjs` for browser‑level
  verification (asset hash, seam integrity, region screenshots).
