#!/usr/bin/env python3
"""Extract one clean world from image-1.png (user's screenshot of the
satellite basemap, which contains ~2.5 wrapped world copies plus small UI
artifacts in the corners), and reproject it from Web-Mercator to the
equirectangular 2:1 layout the fleet map uses (linear lon/lat mapping).

Pipeline:
1. Auto-detect the horizontal wrap period (SSD over interior scanlines).
2. Recover the phase of -180° by aligning the dateline (open-Pacific
   column) — brute search near the expected offset.
3. Average all periodic copies (denoise), mask + patch corner UI artifacts.
4. Web-Mercator -> equirectangular resample (bilinear), clamping the
   top/bottom polar rows that are outside the screenshot's visible band.
5. Save a JPEG basemap.
"""
from PIL import Image
import numpy as np
import math, sys

SRC = "/home/user/uploads/image-1.png"
OUT = "/home/user/incois-arpy-decoder/decoder-ui/frontend/src/assets/fleet_basemap.jpg"

img = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32)
H, W = img.shape[:2]
print(f"source {W}x{H}")

# --- 1. wrap period via minimum SSD -------------------------------------
rows = [100, 200, 300, 400, 500, 600]
best = (1e18, 0)
for P in range(650, 960):
    ssd = 0.0
    for r in rows:
        a = img[r, : W - P]
        b = img[r, P:]
        ssd += float(((a - b) ** 2).mean())
    if ssd < best[0]:
        best = (ssd, P)
_, P = best
print("wrap period:", P, "px")

# --- 2. phase of -180 lon ------------------------------------------------
# The dateline column is open Pacific near the left edge in this render
# (Alaska ~60-70px to its right). Search x0 in a window that gives the
# cleanest match against ALL copies: for candidate x0, average pixel
# distance between col x0+dx and its shifted copies should be minimal on
# LAND-FEATURE rows (strong match anywhere works because of periodicity,
# what we really need is consistency: pick x0 so that the crop window
# [x0, x0+P) contains NO partial-copy seams).
# We additionally bias x0 near 30 (identified from Alaska position).
def window_seam_error(x0):
    # the crop [x0, x0+P) must lie fully within [0, W); measure mismatch of
    # the 8 columns around the expected seam vs their copies
    errs = []
    for dx in range(0, 24):
        x = x0 + dx
        if x + P < W:
            a = img[:, x]; b = img[:, x + P]
            errs.append(float(((a - b) ** 2).mean()))
    return sum(errs) / max(1, len(errs))

FORCE_X0 = int(sys.argv[1]) if len(sys.argv) > 1 else -1
if FORCE_X0 >= 0:
    x0 = FORCE_X0
    print("forced crop x0:", x0)
else:
    bestx = (1e18, 0)
    for x0c in range(0, W - P):
        e = window_seam_error(x0c)
        if e < bestx[0] - 1e-9 and abs(x0c - 30) < 25:
            bestx = (e, x0c)
    x0 = bestx[1]
print("crop window:", x0, "..", x0 + P)

# --- 3. average periodic copies -----------------------------------------
world = None
count = 0
for s in (0, P, 2 * P):
    lo, hi = x0 - s, x0 - s + P
    if lo < 0 or hi > W:
        continue
    world = img[:, lo:hi] if world is None else world + img[:, lo:hi]
    count += 1
world = (world / count).astype(np.float32)
print("copies averaged:", count)

# UI artifact masks (in the source frame); patch by borrowing the same
# pixel from the nearest unmasked periodic copy.
def masked_regions():
    regs = []
    regs.append((0, 0, 46, 30))          # "km" badge top-left
    regs.append((0, H - 20, 90, H))      # "2000 km" scale text bottom-left
    regs.append((W - 45, 60, W, 160))    # right-edge round icons
    regs.append((W - 120, H - 80, W, H)) # bottom-right minimap/overview
    return regs

def in_mask(x, y):
    for (xa, ya, xb, yb) in masked_regions():
        if xa <= x < xb and ya <= y < yb:
            return True
    return False

patched = 0
for (xa, ya, xb, yb) in masked_regions():
    for x in range(max(0, xa), min(xb, W)):
        col = (x - x0) % P
        for s in (P, -P, 2 * P, -2 * P):
            xs = x + s
            if not (0 <= xs < W):
                continue
            # accept the copy if its rows of interest are all unmasked
            if all(not in_mask(xs, y) for y in range(max(0, ya), min(yb, H), 8)):
                world[max(0, ya):min(yb, H), col] = img[max(0, ya):min(yb, H), xs]
                patched += 1
                break
print(f"corner UI artifacts patched ({patched} patch-borrows)")

# --- 4. Web-Mercator -> equirectangular ----------------------------------
# Visible vertical band: world square of side P px; screenshot height H
# shows the central band -> lat range = 2*atan(exp(pi*(1 - 2*f))) - pi/2
# with f = (P - H) / (2P).
f = (P - H) / (2 * P)
phi_max = 2 * math.atan(math.exp(math.pi * (1 - 2 * f))) - math.pi / 2
print(f"visible Mercator band: ±{math.degrees(phi_max):.2f} deg")

def merc_y(phi):   # normalized 0..1 top->bottom within the BAND
    z = math.log(math.tan(math.pi / 4 + phi / 2))
    zmax = math.log(math.tan(math.pi / 4 + phi_max / 2))
    return 0.5 * (1 - z / zmax)

TW, TH = 1920, 960
out = np.zeros((TH, TW, 3), np.float32)
xs = (np.arange(TW) + 0.5) / TW * P          # sample cols in world img
for j in range(TH):
    lat = 90 - (j + 0.5) / TH * 180          # equirect target latitude
    phi = math.radians(lat)
    if abs(phi) > phi_max:
        t = 0.0 if phi > 0 else 1.0          # clamp polar rows to band edge
    else:
        t = merc_y(phi)
    ys = t * H - 0.5
    y0 = int(math.floor(ys)); fy = ys - y0
    y0 = max(0, min(H - 2, y0))
    a = world[y0]; b = world[y0 + 1]
    row = a + (b - a) * fy
    xi = xs.copy()
    xi0 = np.floor(xi).astype(int); fx = xi - xi0
    xi0 = np.clip(xi0, 0, P - 2)
    p1 = row[xi0]; p2 = row[xi0 + 1]
    out[j] = p1 + (p2 - p1) * fx[:, None]

# --- 5. phase autocorrect: align lon=-180 to the left edge ---------------
# Land vs ocean discriminator: land is generally tan/green (R > B or G > B),
# ocean is deep teal (B clearly dominant).
def land_mask(arr):
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    return (r > b + 12) | ((g > b + 18) & (r > b))

def coast_x(arr, lat_deg, which):
    # find the land-sea boundary x at a given latitude row band
    j = (90 - lat_deg) / 180 * TH
    band = land_mask(arr[max(0, int(j) - 4):int(j) + 5]).mean(axis=0)
    xs = np.arange(TW)
    if which == "west_africa":
        # first land x to the RIGHT of open Atlantic (search 500..1000)
        seg = band[500:1050]
        idx = int(np.argmax(seg > 0.4)) + 500
        return idx
    if which == "japan_east":
        # last land x to the LEFT of open Pacific (search 1400..1850)
        seg = band[1400:1850]
        nz = np.nonzero(seg > 0.4)[0]
        return int(nz[-1]) + 1400 if len(nz) else -1
    return -1

# Kanyakumari-less robust pair: Senegal west tip lon=-17.53 deg at lat 14.74N
# and Honshu Pacific coast lon=141.0 at lat 36N -> two measurements averaged.
x_sen = coast_x(out, 14.74, "west_africa")
x_jp = coast_x(out, 36.0, "japan_east")
exp_sen = (-17.53 + 180) / 360 * TW
exp_jp = (141.0 + 180) / 360 * TW
deltas = []
if 300 < x_sen < 1200:
    deltas.append(x_sen - exp_sen)
if x_jp > 1200:
    deltas.append(x_jp - exp_jp)
print("phase probes: senegal", x_sen, "exp", exp_sen, "| japan", x_jp, "exp", exp_jp)
if deltas:
    d_out = float(np.mean(deltas))
    d_world = int(round(d_out / TW * P))
    if abs(d_world) >= 2:
        x0c = x0 - d_world
        if x0c < 0:
            x0c += P
        if x0c >= P:
            x0c -= P
        # ensure corrected window lies fully inside the source frame
        while x0c + P > W:
            x0c -= P
        print(f"NEEDS phase correction: {d_out:+.1f}px out -> rerun with x0={x0c}")
        sys.exit(2)
else:
    print("phase probes failed — keeping crop window")

out_img = Image.fromarray(out.astype(np.uint8), "RGB")
out_img.save(OUT, quality=88, optimize=True)
print("saved", OUT, out_img.size)
