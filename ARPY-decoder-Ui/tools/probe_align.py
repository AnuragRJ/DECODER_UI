#!/usr/bin/env python3
"""Quantify misregistration: Natural Earth 110m land polygons (true
plate-carree lon/lat) vs the fleet_basemap raster's land/ocean pixels."""
import json, numpy as np
from PIL import Image, ImageDraw

TW, TH = 1920, 960
ASSET = "/home/user/incois-arpy-decoder/decoder-ui/frontend/src/assets/fleet_basemap.jpg"
RINGS = json.load(open("/tmp/land_rings.json"))

def rasterize_ne():
    mask = Image.new("L", (TW, TH), 0)
    dr = ImageDraw.Draw(mask)
    def px(lon, lat):
        return ((lon + 180) / 360 * TW, (90 - lat) / 180 * TH)
    for r in RINGS:
        # split ring at antimeridian jumps
        segs, cur, prev = [], [], None
        for lon, lat in r:
            if prev is not None and abs(lon - prev) > 180:
                segs.append(cur); cur = []
            cur.append((lon, lat)); prev = lon
        segs.append(cur)
        for s in segs:
            if len(s) < 3: continue
            span = max(x for x,_ in s) - min(x for x,_ in s)
            if span > 350: continue
            pts = [px(lon, lat) for lon, lat in s]
            dr.polygon(pts, fill=255, outline=255)
            # duplicate at +-TW to catch seam-straddling shapes
            pts2 = [(x-TW, y) for x, y in pts]
            dr.polygon(pts2, fill=255, outline=255)
            pts3 = [(x+TW, y) for x, y in pts]
            dr.polygon(pts3, fill=255, outline=255)
    return np.array(mask) > 0

def basemap_land(img):
    r = img[..., 0].astype(np.int16); g = img[..., 1].astype(np.int16); b = img[..., 2].astype(np.int16)
    # ocean = deep teal (B dominant); land green/tan (R or G above B); ice/desert: R dominates
    return ((r > b + 12) | (g > b + 22)) & ~(r > 200) # avoid JPEG clouds handled by r>b anyway

ne = rasterize_ne()
img = np.asarray(Image.open(ASSET).convert("RGB"))
bm = basemap_land(img)
print(f"NE land frac: {ne.mean():.4f}  basemap land frac: {bm.mean():.4f}")

def mismatch(a, b, dx, dy):
    bb = np.roll(np.roll(b, dy, axis=0), dx, axis=1)
    return float((a ^ bb).mean())

# global shift search
best = (1, 0, 0)
for dy in range(-30, 31, 2):
    for dx in range(-30, 31, 2):
        m = mismatch(ne, bm, dx, dy)
        if m < best[0]: best = (m, dx, dy)
    print(f"dy={dy:+d} best-so-far {best}")
m0, dx0, dy0 = best
for dy in range(dy0-2, dy0+3):
    for dx in range(dx0-2, dx0+3):
        m = mismatch(ne, bm, dx, dy)
        if m < best[0]: best = (m, dx, dy)
print(f"\nGLOBAL: zero-shift mismatch={mismatch(ne,bm,0,0):.4f}  best={best[0]:.4f} at dx={best[1]} dy={best[2]}")
print(f"(best global shift in degrees: dlon={best[1]/TW*360:+.2f} dlat={-best[2]/TH*180:+.2f})")

# resample NE mask at shift to compare; then per-latitude residual
m, dx, dy = best
bbs = np.roll(np.roll(bm, dy, axis=0), dx, axis=1)
# dy(lat) drift: for stripe bands of 15 deg, find column-averaged xor vs local dy
print("\nlat-band | mismatch@best-shift | mismatch@zero-shift")
for latc in range(75, -80, -15):
    j0 = int((90 - (latc + 7.5)) / 180 * TH); j1 = int((90 - (latc - 7.5)) / 180 * TH)
    a = ne[j0:j1]; b0 = bm[j0:j1]; bs = bbs[j0:j1]
    # mask out pure-ocean rows to keep signal coastal
    if a.sum() < 500: continue
    print(f"  {latc:+4d}deg  {(a^bs).mean():.4f}   {(a^b0).mean():.4f}")
