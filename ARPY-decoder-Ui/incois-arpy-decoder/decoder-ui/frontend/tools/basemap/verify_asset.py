#!/usr/bin/env python3
"""Score the REBUILT asset directly in plate-carree frame (app's render frame):
for every NE boundary sample point, distance to the raster's land/sea edge.
Old asset score table is printed for comparison if old file provided."""
import os, pathlib
import json, math, sys, numpy as np
from PIL import Image, ImageDraw

TW, TH = 1920, 960
NEW = os.environ.get("BASEMAP_ASSET", str(pathlib.Path(__file__).resolve().parents[2] / "src/assets/fleet_basemap.jpg"))
rings = json.load(open(os.environ.get("NE_RINGS", "/tmp/land_rings.json")))

def frame_scores(path):
    img = np.asarray(Image.open(path).convert("RGB"))
    r = img[...,0].astype(np.int16); g = img[...,1].astype(np.int16); b = img[...,2].astype(np.int16)
    lm = ((r > b + 12) | (g > b + 22)) & ~(r > 200)
    def dilate1(a):
        o = a.copy()
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
            o |= np.roll(np.roll(a, dy, 0), dx, 1)
        return o
    edge = dilate1(lm) & dilate1(~lm)
    cap = 12
    D = np.full(edge.shape, cap, np.int16); D[edge] = 0
    for d in range(1, cap):
        grown = dilate1(edge)
        D[grown & ~edge & (D == cap)] = d
        edge = grown
    pts = []
    for rr in rings:
        for i in range(0, len(rr), 2):
            lon, lat = rr[i]
            if abs(lat) < 83.5: pts.append((lon, lat))
    pts = pts[::2][:60000]
    lons = np.array([p[0] for p in pts]); lats = np.array([p[1] for p in pts])
    xs = np.clip(np.round((lons + 180) / 360 * TW - 0.5).astype(int), 0, TW - 1)
    ys = np.clip(np.round((90 - lats) / 180 * TH - 0.5).astype(int), 0, TH - 1)
    return D, lons, lats, xs, ys

D, lons, lats, xs, ys = frame_scores(NEW)
sc = D[ys, xs]
regions = {
    "WORLD": (-180, 180, -83, 83),
    "India/Sri Lanka": (68, 92, 5, 35),
    "Africa west": (-20, 55, -35, 37),
    "Europe": (-12, 45, 35, 71),
    "Asia E/Japan": (100, 145, 15, 50),
    "S.America E": (-55, -34, -25, 8),
    "N.America": (-170, -52, 25, 70),
    "Australia/Tasmania": (112, 155, -45, -10),
    "SE Asia": (90, 125, -12, 25),
    "Greenland/N edge": (-60, -15, 58, 83),
}
print(f"{'region':24s} {'mean px-to-raster-coast':>24s} {'>4px %':>8s}")
for name, (lo0, lo1, la0, la1) in regions.items():
    sel = (lons >= lo0) & (lons <= lo1) & (lats >= la0) & (lats <= la1)
    if sel.sum() < 5: continue
    s = sc[sel]
    print(f"{name:24s} {s.mean():24.3f} {(s > 4).mean()*100:7.1f}%")

# world + region composite: asset with red NE outline in plate-carree
def draw():
    base = np.asarray(Image.open(NEW).convert("RGB"))
    img = Image.fromarray(base)
    dr = ImageDraw.Draw(img)
    for rr in rings:
        poly = [((lon + 180) / 360 * TW, (90 - lat) / 180 * TH) for lon, lat in rr]
        if len(poly) > 1: dr.line(poly, fill=(255, 70, 70), width=1, joint="curve")
    return img
img = draw()
img.save("/tmp/asset_aligned_world.jpg", quality=90)
boxes = [
    ("india",     (66, 96, 2, 36), 6),
    ("africa_w",  (-20, 40, -5, 40), 5),
    ("europe",    (-12, 35, 35, 72), 5),
    ("asia_e",    (100, 150, 12, 50), 5),
    ("sam_e",     (-60, -30, -30, 10), 6),
    ("nam_e",     (-100, -60, 22, 55), 5),
    ("se_asia",   (90, 130, -12, 25), 6),
    ("jp",        (125, 150, 27, 48), 7),
    ("antarctica",(-40, 40, -86, -60), 4),
    ("greenland", (-60, -10, 56, 84), 5),
]
items = []
for name, (lo0, lo1, la0, la1), s in boxes:
    x0 = (lo0 + 180) / 360 * TW; x1 = (lo1 + 180) / 360 * TW
    y0 = (90 - la1) / 180 * TH; y1 = (90 - la0) / 180 * TH
    c = img.crop((max(0, x0), max(0, y0), min(TW, x1), min(TH, y1)))
    c = c.resize((int(c.width * s), int(c.height * s)), Image.NEAREST)
    items.append((name, c))
w = max(c.width for _, c in items); h = sum(c.height for _, c in items)
out = Image.new("RGB", (w, h), (16, 24, 32))
y = 0
for name, c in items:
    out.paste(c, (0, y)); y += c.height
out.save("/tmp/asset_aligned_regions.jpg", quality=90)
print("saved /tmp/asset_aligned_world.jpg + /tmp/asset_aligned_regions.jpg")
