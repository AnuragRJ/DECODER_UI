#!/usr/bin/env python3
"""Rebuild fleet_basemap.jpg with the CALIBRATED Web-Mercator georeference
recovered by fitting Natural Earth 110m coastlines onto the source frame:
    source col  = P*(lon+180)/360 + C      (P=819, C=1.75)
    source row  = A - B*z(lat)             (A=411.0, B=130.25 z-scale)
vs the original extraction which assumed the equator-centred band
(A=379, B=819/2pi, C=0) -> misregistration of ~32 source px in z.
Projection & raster pipeline identical to build_basemap.py; only the
georeference parameters changed.
"""
from PIL import Image
import numpy as np
import math

SRC = "/home/user/uploads/image-1.png"
OUT = "/home/user/incois-arpy-decoder/decoder-ui/frontend/src/assets/fleet_basemap.jpg"
P, X0, Hv = 819, 54, 758
A_FIT, B_FIT, C_FIT = 411.0, 130.25, 1.75

img = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32)
H, W = img.shape[:2]
world = img[:, X0:X0 + P]

# same UI-artifact patch as the original build (borrow nearest clean copy)
def masked_regions():
    return [(0, 0, 46, 30), (0, H - 20, 90, H), (W - 45, 60, W, 160), (W - 120, H - 80, W, H)]
def in_mask(x, y):
    return any(xa <= x < xb and ya <= y < yb for (xa, ya, xb, yb) in masked_regions())
for (xa, ya, xb, yb) in masked_regions():
    for x in range(max(0, xa), min(xb, W)):
        col = (x - X0) % P
        for s in (P, -P, 2 * P, -2 * P):
            xs = x + s
            if not (0 <= xs < W): continue
            if all(not in_mask(xs, y) for y in range(max(0, ya), min(yb, H), 8)):
                world[max(0, ya):min(yb, H), col] = img[max(0, ya):min(yb, H), xs]
                break

TW, TH = 1920, 960
out = np.zeros((TH, TW, 3), np.float32)
xs = (np.arange(TW) + 0.5) / TW * P + C_FIT - 0.5   # incl. calibrated lon phase
xi0 = np.floor(xs).astype(int); fx = xs - xi0
xi0 = np.clip(xi0, 0, P - 2)
for j in range(TH):
    lat = 90 - (j + 0.5) / TH * 180
    phi = math.radians(lat)
    zt = math.log(math.tan(math.pi / 4 + phi / 2))
    ys = A_FIT - B_FIT * zt                    # calibrated Mercator georef
    ys = max(0.0, min(Hv - 1.0, ys))           # clamp polar rows to source band
    y0 = int(math.floor(ys)); fy = ys - y0
    y0 = max(0, min(Hv - 2, y0))
    row = world[y0] + (world[y0 + 1] - world[y0]) * fy
    out[j] = row[xi0] + (row[xi0 + 1] - row[xi0]) * fx[:, None]

Image.fromarray(out.astype(np.uint8), "RGB").save(OUT, quality=88, optimize=True)
print("saved", OUT)
