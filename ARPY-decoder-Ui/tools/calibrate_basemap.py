#!/usr/bin/env python3
"""Recover the TRUE georeference of the source basemap screenshot by
fitting Natural Earth 110m coastline samples onto the source frame.
Source model (Web Mercator):
    col = P*(lon+180)/360 + C        (P=819px world width, C phase fix)
    row = A - B*z(lat)               (z = Mercator y, ln tan(pi/4+phi/2))
Score = mean min(chamfer-to-coast(px), 12) over NE boundary samples.
"""
import json, math, numpy as np
from PIL import Image

SRC = "/home/user/uploads/image-1.png"
P, X0, A0 = 819, 54, 379.0
B0 = P / (2 * math.pi)

img = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32)
H, W = img.shape[:2]
world = img[:, X0:X0 + P]                      # single complete copy
del img

def land_mask_merc(arr):
    r = arr[...,0]; g = arr[...,1]; b = arr[...,2]
    return ((r > b + 12) | (g > b + 22)) & ~(r > 200)

lm = land_mask_merc(world)
def dilate1(a):
    o = a.copy()
    for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
        o |= np.roll(np.roll(a, dy, 0), dx, 1)
    return o
edge = dilate1(lm) & dilate1(~lm)              # 2-3px coast band
cap = 12
D = np.full(edge.shape, cap, np.int16); D[edge] = 0
for d in range(1, cap):
    grown = dilate1(edge)
    new = grown & ~edge
    D[new & (D == cap)] = d
    edge = grown
print(f"source world {P}x{H}, coast-edge px {int((D==0).sum())}")

# NE boundary samples
rings = json.load(open("/tmp/land_rings.json"))
pts = []
for r in rings:
    for i in range(0, len(r), 2):
        lon, lat = r[i]
        if abs(lat) < 83.5: pts.append((lon, lat))
pts = pts[::2][:60000]
lons = np.array([p[0] for p in pts]); lats = np.array([p[1] for p in pts])
z = np.log(np.tan(math.pi/4 + np.radians(lats)/2))
xs0 = P * (lons + 180) / 360
print(f"NE samples: {len(z)}")

def score(A, B, C):
    ys = np.clip(np.round(A - B * z).astype(int), 0, H - 1)
    xs = np.clip(np.round(xs0 + C).astype(int), 0, P - 1)
    return float(D[ys, xs].mean())

print(f"assumed build params: A={A0}, B={B0:.3f}, C=0 -> score {score(A0, B0, 0):.4f}")
bast = (1e9, A0, B0, 0.0)
for Bc in np.arange(110.0, 141.0, 1.0):
    for Ac in np.arange(350.0, 421.0, 2.0):
        s = score(Ac, Bc, 0.0)
        if s < bast[0]: bast = (s, Ac, Bc, 0.0)
print(f"coarse fit (C=0): score {bast[0]:.4f} A={bast[1]} B={bast[2]}")
b2 = (1e9,)
for Bc in np.arange(bast[2]-2.0, bast[2]+2.01, 0.25):
    for Ac in np.arange(bast[1]-4, bast[1]+4.01, 0.5):
        for Cc in np.arange(-8, 8.01, 1.0):
            s = score(Ac, Bc, Cc)
            if s < b2[0]: b2 = (s, Ac, Bc, Cc)
print(f"refine: score {b2[0]:.4f} A={b2[1]} B={b2[2]} C={b2[3]}")
b3 = (1e9,)
for Bc in np.arange(b2[2]-0.5, b2[2]+0.51, 0.05):
    for Ac in np.arange(b2[1]-1, b2[1]+1.01, 0.1):
        for Cc in np.arange(b2[3]-1.5, b2[3]+1.51, 0.25):
            s = score(Ac, Bc, Cc)
            if s < b3[0]: b3 = (s, Ac, Bc, Cc)
print(f"FINE:   score {b3[0]:.4f} A={b3[1]:.2f} B={b3[2]:.3f} C={b3[3]:.2f}")
s, A, B, C = b3
for y in (0.5, H - 0.5):
    zz = (A - y) / B
    phi = math.degrees(2*math.atan(math.exp(zz)) - math.pi/2)
    print(f"  screenshot row {y}: lat {phi:+.2f} deg")
print(f"assumed A={A0} B={B0:.2f} -> A error {A-A0:+.2f}px (band-centre shift), B error {B/B0-1:+.2%}")
