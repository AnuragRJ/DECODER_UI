#!/usr/bin/env python3
"""Per-latitude-band best shift (NE-110m vs basemap), edge-focused."""
import json, numpy as np
from PIL import Image, ImageDraw

TW, TH = 1920, 960
ASSET = "/home/user/incois-arpy-decoder/decoder-ui/frontend/src/assets/fleet_basemap.jpg"
RINGS = json.load(open("/tmp/land_rings.json"))

def rasterize_ne():
    mask = Image.new("L", (TW, TH), 0)
    dr = ImageDraw.Draw(mask)
    def px(lon, lat): return ((lon + 180) / 360 * TW, (90 - lat) / 180 * TH)
    for r in RINGS:
        segs, cur, prev = [], [], None
        for lon, lat in r:
            if prev is not None and abs(lon - prev) > 180:
                segs.append(cur); cur = []
            cur.append((lon, lat)); prev = lon
        segs.append(cur)
        for s in segs:
            if len(s) < 3: continue
            if max(x for x,_ in s) - min(x for x,_ in s) > 350: continue
            pts = [px(lon, lat) for lon, lat in s]
            dr.polygon(pts, fill=255, outline=255)
            dr.polygon([(x-TW, y) for x, y in pts], fill=255, outline=255)
            dr.polygon([(x+TW, y) for x, y in pts], fill=255, outline=255)
    return np.array(mask) > 0

def land_mask(img):
    r = img[...,0].astype(np.int16); g = img[...,1].astype(np.int16); b = img[...,2].astype(np.int16)
    return ((r > b + 12) | (g > b + 22)) & ~(r > 200)

def dilate(a, k):
    out = a.copy()
    for dx in range(-k, k+1):
        for dy in range(-k, k+1):
            out |= np.roll(np.roll(a, dy, 0), dx, 1)
    return out

def erode(a, k):
    out = a.copy()
    for dx in range(-k, k+1):
        for dy in range(-k, k+1):
            out &= np.roll(np.roll(a, dy, 0), dx, 1)
    return out

ne = rasterize_ne()
bma = land_mask(np.asarray(Image.open(ASSET).convert("RGB")))
edge = dilate(ne, 4) & ~erode(ne, 4)      # ~16px wide coastal band
print(f"edge band px: {edge.sum()}")

rows_table = []
for latc in range(82, -83, -5):
    j0 = int((90 - (latc + 2.5)) / 180 * TH); j1 = int((90 - (latc - 2.5)) / 180 * TH)
    sel = edge[j0:j1]
    if sel.sum() < 300: continue
    a = ne[j0:j1]; b = bma[j0:j1]
    best = (1e9, 0, 0)
    for dy in range(-60, 61):
        bs = np.roll(b, dy, 0)
        m = float((a ^ bs)[sel].mean())
        if m < best[0]: best = (m, dy, 0)
    # refine dx around best dy
    m0, dy0, _ = best
    for dx in range(-30, 31):
        bs = np.roll(np.roll(b, dy0, 0), dx, 1)
        m = float((a ^ bs)[sel].mean())
        if m < best[0]: best = (m, dy0, dx)
    m, dys, dxs = best
    zero = float((a ^ b)[sel].mean())
    rows_table.append((latc, dys, dxs, m, zero))
    print(f"lat {latc:+4d}  best dy={dys:+3d}px dx={dxs:+3d}px  mismatch {m:.4f} (zero-shift {zero:.4f})")

# fit: content true lat phi appears at row row_exp(phi) - dy*  =>
# the BUILD put source-row ys0(phi)=379-130.35*z(phi) content there.
# True source georef: s = A - B*z(phi). Fit A,B from (ys0 at apparent row, phi_true)
import math
zs, ss = [], []
for latc, dys, dxs, m, zero in rows_table:
    if dys == 0 and abs(dxs) == 0:  # ambiguous (already aligned or no signal)
        pass
    phi_app = latc                                   # row centre of the band
    phi = math.radians(phi_app)
    # apparent -> true: raster content of true lat phi_true sits at band(phi_app)
    # asset row j maps content from source row ys0 = 379 - 130.35*z(lat_j)
    # actually needed: source row where this content lives: s0 = H/2 - P*z(phi_app)/(2pi)
    s0 = 379 - 819 * math.log(math.tan(math.pi/4 + math.radians(phi_app)/2)) / (2*math.pi)
    # that content's TRUE lat: lat(row below by dy): true = apparent - dy*180/960  (moving bm UP by -dy increases lat of content relative to frame)
    phi_true = phi_app - dys * 180 / 960
    zt = math.log(math.tan(math.pi/4 + math.radians(phi_true)/2))
    if math.isfinite(zt) and abs(phi_true) < 86:
        zs.append(zt); ss.append(s0)
zs = np.array(zs); ss = np.array(ss)
A = np.vstack([np.ones_like(zs), -zs]).T
coef, *_ = np.linalg.lstsq(A, ss, rcond=None)
print(f"\nrecovered source Mercator georef: s = {coef[0]:.2f} - {coef[1]:.2f}*z  (assumed was 379.00 - 130.35*z)")
# implied band edges of screenshot y=0,H=758
for y in (0, 758):
    z = (coef[0] - y) / coef[1]
    phi = 2*math.atan(math.exp(z)) - math.pi/2
    print(f"  screenshot row {y}: true lat {math.degrees(phi):+.2f} deg")
