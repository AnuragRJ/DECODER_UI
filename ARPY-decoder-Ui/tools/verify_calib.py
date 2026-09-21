#!/usr/bin/env python3
"""Region-level score before/after + visual overlay crops of the SOURCE
world frame with the NE coastline drawn at assumed vs recovered georef."""
import json, math, numpy as np
from PIL import Image, ImageDraw

SRC = "/home/user/uploads/image-1.png"
P, X0 = 819, 54
B0 = P / (2 * math.pi)
A_FIT, B_FIT, C_FIT = 411.0, 130.25, 1.75

img = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32)
H, W = img.shape[:2]
world = img[:, X0:X0 + P]

def land_mask_merc(arr):
    r = arr[...,0]; g = arr[...,1]; b = arr[...,2]
    return ((r > b + 12) | (g > b + 22)) & ~(r > 200)

lm = land_mask_merc(world)
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

def score_region(A, B, C, lon0, lon1, lat0, lat1):
    sel = (lons >= lon0) & (lons <= lon1) & (lats >= lat0) & (lats <= lat1)
    zz = z[sel]; xx = xs0[sel]
    ys = np.clip(np.round(A - B * zz).astype(int), 0, H-1)
    xs = np.clip(np.round(xx + C).astype(int), 0, P-1)
    return float(D[ys, xs].mean()), int(sel.sum())

regions = {
    "WORLD": (-180, 180, -83, 83),
    "India/Sri Lanka": (68, 92, 5, 35),
    "Africa west": (-20, 55, -35, 37),
    "Europe": (-12, 45, 35, 71),
    "Asia E/Japan": (100, 145, 15, 50),
    "S.America E": (-55, -34, -25, 8),
    "S.America W": (-83, -68, -55, 12),
    "N.America E": (-100, -52, 25, 60),
    "N.America W": (-170, -120, 30, 65),
    "Australia/Tasmania": (112, 155, -45, -10),
    "SE Asia": (90, 125, -12, 25),
    "Greenland/N pole edge": (-60, -15, 58, 83),
    "Antarctica edge": (-180, 180, -75, -63),
}
print(f"{'region':24s} {'score old(A0,B0)':>16s} {'score new(A*,B*,C*)':>19s} {'n':>6s}")
for name, (lo0, lo1, la0, la1) in regions.items():
    s_old, n = score_region(379, B0, 0, lo0, lo1, la0, la1)
    s_new, _ = score_region(A_FIT, B_FIT, C_FIT, lo0, lo1, la0, la1)
    print(f"{name:24s} {s_old:16.3f} {s_new:19.3f} {n:6d}")

# visual crops: paste NE outline in red on the world frame at fitted georef,
# and a second frame at old georef, upscale 2x for landmark review
from PIL import Image as PILImage
frame = PILImage.fromarray(world.astype(np.uint8))
def draw_outline(A, B, C, color):
    fr = frame.copy()
    dr = ImageDraw.Draw(fr)
    for r in rings:
        poly = []
        for lon, lat in r:
            x = P * (lon + 180) / 360 + C
            y = A - B * math.log(math.tan(math.pi/4 + math.radians(lat)/2))
            poly.append((x, y))
        if len(poly) > 1: dr.line(poly, fill=color, width=1, joint="curve")
    return fr

fr_new = draw_outline(A_FIT, B_FIT, C_FIT, (255, 60, 60))
fr_old = draw_outline(379, B0, 0, (255, 60, 60))
def crop(fr, lon0, lon1, lat0, lat1, scale=3):
    x0 = P*(lon0+180)/360; x1 = P*(lon1+180)/360
    y0 = A_FIT - B_FIT*math.log(math.tan(math.pi/4+math.radians(lat1)/2))
    y1 = A_FIT - B_FIT*math.log(math.tan(math.pi/4+math.radians(lat0)/2))
    return fr.crop((max(0,x0), max(0,y0), min(P,x1), min(H,y1))).resize(
        (int((x1-x0)*scale), int(max(1,y1-y0)*scale)), PILImage.NEAREST)
strip = []
for name, box in [("india", (66, 96, 2, 36)), ("africa_w", (-20, 20, 10, 38)),
                  ("sam_e", (-58, -32, -28, 6)), ("japan", (128, 148, 28, 46)),
                  ("europe", (-12, 18, 35, 60)), ("tasmania", (142, 152, -45, -37))]:
    cn = crop(fr_new, *box); co = crop(fr_old, *box)
    strip.append((f"{name}_OLD.jpg", co)); strip.append((f"{name}_NEW.jpg", cn))
w = max(a.width + b.width for a, b in strip); h = sum(a.height for a, b in strip)
outimg = PILImage.new("RGB", (w, h), (16, 24, 32))
y = 0
for (na, a), (nb, b) in strip:
    outimg.paste(a, (0, y)); outimg.paste(b, (a.width, y)); y += a.height
outimg.save("/tmp/align_source_compare.jpg", quality=90)
print("saved /tmp/align_source_compare.jpg (left NEW fit, right OLD georef)")
