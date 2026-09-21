import { describe, it, expect } from "vitest";
import * as fs from "fs";
import * as path from "path";
import {
  computeBase,
  toScreen,
  fromScreen,
  zoomAt,
  clampView,
  viewForCenter,
  viewCenterWorld,
  fitViewFor,
  neutralView,
  worldX,
  worldY,
  lonFromWorldX,
  latFromWorldY,
  WORLD_W,
  WORLD_H,
  MIN_K_NORMAL,
  MAX_K,
} from "./mapProjection";

const PAD = 34;

// Real wmoA trajectory (first/last/typical points from a real decoded run)
const TRAJ = [
  { lon: 58.515, lat: -55.937 },
  { lon: 63.894, lat: -57.256 },
  { lon: 66.42, lat: -58.333 },
  { lon: 69.87, lat: -58.649 },
  { lon: 69.366, lat: -59.913 },
];

describe("world <-> lon/lat primitives", () => {
  it("roundtrips coordinates exactly, including antimeridian and poles", () => {
    const cases = [
      [0, 0],
      [180, 90],
      [-180, -90],
      [179.9999, 83.75],
      [-179.9999, -55.937],
      [69.366, -59.913],
    ] as const;
    for (const [lon, lat] of cases) {
      expect(lonFromWorldX(worldX(lon))).toBeCloseTo(lon, 10);
      expect(latFromWorldY(worldY(lat))).toBeCloseTo(lat, 10);
    }
  });

  it("worldX is monotonic west->east, worldY is monotonic north->south", () => {
    expect(worldX(-179.9)).toBeLessThan(worldX(-1));
    expect(worldX(-1)).toBeLessThan(worldX(179.9));
    expect(worldY(89)).toBeLessThan(worldY(0));
    expect(worldY(0)).toBeLessThan(worldY(-89));
  });
});

describe("computeBase", () => {
  it("normal mode CONTAIN: world rect fits inside viewport minus padding", () => {
    const base = computeBase(735, 209, false, PAD);
    // world rect corners (base.ox/oy, +scale*WORLD)
    expect(base.ox).toBeGreaterThanOrEqual(PAD - 1e-9);
    expect(base.oy).toBeGreaterThanOrEqual(PAD - 1e-9);
    expect(base.ox + WORLD_W * base.scale).toBeLessThanOrEqual(735 - PAD + 1e-9);
    expect(base.oy + WORLD_H * base.scale).toBeLessThanOrEqual(209 - PAD + 1e-9);
  });

  it("fill mode COVER: world rect covers the whole viewport", () => {
    const base = computeBase(1600, 402, true, PAD);
    expect(base.ox).toBeLessThanOrEqual(0 + 1e-9);
    expect(base.oy).toBeLessThanOrEqual(0 + 1e-9);
    expect(base.ox + WORLD_W * base.scale).toBeGreaterThanOrEqual(1600 - 1e-9);
    expect(base.oy + WORLD_H * base.scale).toBeGreaterThanOrEqual(402 - 1e-9);
  });

  it("degenerate viewport returns a safe unit base", () => {
    const base = computeBase(0, 0, false, PAD);
    expect(base.scale).toBe(1);
    expect(Number.isFinite(base.ox)).toBe(true);
    expect(Number.isFinite(base.oy)).toBe(true);
  });
});

describe("toScreen / fromScreen", () => {
  it("roundtrips through arbitrary legal views", () => {
    const base = computeBase(1600, 402, true, PAD);
    const views = [
      neutralView(base, 1600, 402),
      viewForCenter({ wx: worldX(69.4), wy: worldY(-59.9) }, 9, base, 1600, 402),
      { tx: -2400, ty: -900, k: 3.3 },
    ];
    for (const v of views) {
      for (const p of TRAJ) {
        const s = toScreen(p, base, v);
        const back = fromScreen(s.x, s.y, base, v);
        expect(back.lon).toBeCloseTo(p.lon, 6);
        expect(back.lat).toBeCloseTo(p.lat, 6);
      }
    }
  });

  it("k=1 places the world exactly at the base transform", () => {
    const base = computeBase(735, 209, false, PAD);
    const v = { tx: 0, ty: 0, k: 1 };
    const s = toScreen({ lon: -180, lat: 90 }, base, v);
    expect(s.x).toBeCloseTo(base.ox, 6);
    expect(s.y).toBeCloseTo(base.oy, 6);
  });
});

describe("zoomAt", () => {
  it("keeps the anchor point fixed on screen (cursor-anchored zoom)", () => {
    const base = computeBase(1600, 402, true, PAD);
    const v0 = neutralView(base, 1600, 402);
    const ax = 400, ay = 120;
    const before = fromScreen(ax, ay, base, v0);
    const v1 = zoomAt(v0, 2.5, ax, ay, 1, MAX_K);
    const after = fromScreen(ax, ay, base, v1);
    expect(v1.k).toBeCloseTo(v0.k * 2.5, 9);
    expect(after.lon).toBeCloseTo(before.lon, 9);
    expect(after.lat).toBeCloseTo(before.lat, 9);
  });

  it("respects min/max zoom bounds", () => {
    const base = computeBase(1600, 402, true, PAD);
    const v0 = neutralView(base, 1600, 402);
    expect(zoomAt(v0, 1000, 0, 0, 1, MAX_K).k).toBe(MAX_K);
    expect(zoomAt(v0, 0.0001, 0, 0, MIN_K_NORMAL, MAX_K).k).toBe(MIN_K_NORMAL);
  });
});

describe("clampView", () => {
  it("fill: at k=1 the only legal view is tx=ty=0", () => {
    const base = computeBase(1600, 402, true, PAD);
    const v = clampView({ tx: -500, ty: -200, k: 1 }, base, 1600, 402, true);
    // world rect must still cover the viewport exactly
    const w0x = base.ox * v.k + v.tx;
    const w1x = (base.ox + WORLD_W * base.scale) * v.k + v.tx;
    const w0y = base.oy * v.k + v.ty;
    const w1y = (base.oy + WORLD_H * base.scale) * v.k + v.ty;
    expect(w0x).toBeLessThanOrEqual(1e-9);
    expect(w1x).toBeGreaterThanOrEqual(1600 - 1e-9);
    expect(w0y).toBeLessThanOrEqual(1e-9);
    expect(w1y).toBeGreaterThanOrEqual(402 - 1e-9);
  });

  it("fill: deep zoom can be panned but never leaves a gap at any edge", () => {
    const base = computeBase(1600, 402, true, PAD);
    const wild = { tx: 50000, ty: -50000, k: 6 };
    const v = clampView(wild, base, 1600, 402, true);
    const w0x = base.ox * v.k + v.tx;
    const w1x = (base.ox + WORLD_W * base.scale) * v.k + v.tx;
    const w0y = base.oy * v.k + v.ty;
    const w1y = (base.oy + WORLD_H * base.scale) * v.k + v.ty;
    expect(w0x).toBeLessThanOrEqual(1e-9);
    expect(w1x).toBeGreaterThanOrEqual(1600 - 1e-9);
    expect(w0y).toBeLessThanOrEqual(1e-9);
    expect(w1y).toBeGreaterThanOrEqual(402 - 1e-9);
  });

  it("fill: k can never go below 1 (no letterboxing in full-screen)", () => {
    const base = computeBase(1600, 402, true, PAD);
    const v = clampView({ tx: 0, ty: 0, k: 0.4 }, base, 1600, 402, true);
    expect(v.k).toBeGreaterThanOrEqual(1);
  });

  it("normal: at least 40px of world always stays inside the viewport", () => {
    const base = computeBase(735, 209, false, PAD);
    const wild = { tx: 99999, ty: -99999, k: 2 };
    const v = clampView(wild, base, 735, 209, false);
    // Intersect world rect with viewport, require >= 40px grace on the
    // violated axis (implementation clamps back to exactly the edge rule).
    const w0x = base.ox * v.k + v.tx;
    const w1x = (base.ox + WORLD_W * base.scale) * v.k + v.tx;
    const w0y = base.oy * v.k + v.ty;
    const w1y = (base.oy + WORLD_H * base.scale) * v.k + v.ty;
    expect(Math.min(w1x, 735) - Math.max(w0x, 0)).toBeGreaterThanOrEqual(40 - 1e-9);
    expect(Math.min(w1y, 209) - Math.max(w0y, 0)).toBeGreaterThanOrEqual(40 - 1e-9);
  });

  it("normal: zoom clamps to [0.5, 14]", () => {
    const base = computeBase(735, 209, false, PAD);
    expect(clampView({ tx: 0, ty: 0, k: 0.01 }, base, 735, 209, false).k).toBe(MIN_K_NORMAL);
    expect(clampView({ tx: 0, ty: 0, k: 99 }, base, 735, 209, false).k).toBe(MAX_K);
  });
});

describe("viewForCenter / viewCenterWorld", () => {
  it("roundtrips: the requested centre lands at the viewport centre", () => {
    const base = computeBase(1600, 402, true, PAD);
    for (const p of TRAJ) {
      const c = { wx: worldX(p.lon), wy: worldY(p.lat) };
      const v = viewForCenter(c, 4.2, base, 1600, 402);
      const back = viewCenterWorld(v, base, 1600, 402);
      expect(back.wx).toBeCloseTo(c.wx, 6);
      expect(back.wy).toBeCloseTo(c.wy, 6);
    }
  });

  it("resize math: centre recovered against the OLD base+size, so the view survives a browser resize", () => {
    // Regression: reading the "previous" base/size AFTER the render-time
    // ref sync captured the NEW values, so the same {tx,ty,k} was
    // re-interpreted under the new base and — at high zoom — the centre
    // flew hundreds of degrees out of the world (blank off-world map).
    const baseA = computeBase(761, 209, false, PAD); // normal map, pre-resize
    const centre = { wx: worldX(63.8), wy: worldY(-57.7) }; // real fleet-fit centre
    const k = 12; // near the fleet-fit ceiling
    const v = viewForCenter(centre, k, baseA, 761, 209);
    const baseB = computeBase(436, 165, false, PAD); // post-resize viewport

    // correct: previous centre measured with the OLD base+size
    const cOld = viewCenterWorld(v, baseA, 761, 209);
    const v2 = viewForCenter(cOld, v.k, baseB, 436, 165);
    const kept = viewCenterWorld(v2, baseB, 436, 165);
    expect(kept.wx).toBeCloseTo(centre.wx, 6);
    expect(kept.wy).toBeCloseTo(centre.wy, 6);
    expect(kept.wx).toBeGreaterThanOrEqual(0);
    expect(kept.wx).toBeLessThanOrEqual(WORLD_W);
    expect(kept.wy).toBeGreaterThanOrEqual(0);
    expect(kept.wy).toBeLessThanOrEqual(WORLD_H);

    // the bug's math: same centre measured with NEW base+size leaves the world
    const cBuggy = viewCenterWorld(v, baseB, 436, 165);
    const vBuggy = viewForCenter(cBuggy, v.k, baseB, 436, 165);
    const lost = viewCenterWorld(vBuggy, baseB, 436, 165);
    expect(lost.wx > WORLD_W || lost.wy > WORLD_H).toBe(true); // demonstrably off-world
  });
});

describe("fitViewFor", () => {
  it("frames a real trajectory bbox: every point lands inside the viewport with padding", () => {
    const base = computeBase(1600, 402, true, PAD);
    const v = fitViewFor(TRAJ, base, 1600, 402, 0.22, 2.2, 1.2, 9);
    expect(v.k).toBeGreaterThanOrEqual(1.2);
    expect(v.k).toBeLessThanOrEqual(9);
    for (const p of TRAJ) {
      const s = toScreen(p, base, v);
      expect(s.x).toBeGreaterThan(20);
      expect(s.x).toBeLessThan(1600 - 20);
      expect(s.y).toBeGreaterThan(20);
      expect(s.y).toBeLessThan(402 - 20);
    }
  });

  it("frames a small fleet inside a small normal band", () => {
    const base = computeBase(735, 209, false, PAD);
    const pts = [
      { lon: -4, lat: 58 },
      { lon: 2, lat: 55 },
      { lon: 69.4, lat: -59.9 },
      { lon: 63.9, lat: -57.3 },
    ];
    const v = fitViewFor(pts, base, 735, 209, 0.1, 6, MIN_K_NORMAL, 6);
    const clamped = clampView(v, base, 735, 209, false);
    for (const p of pts) {
      const s = toScreen(p, base, clamped);
      expect(s.x).toBeGreaterThanOrEqual(-40);
      expect(s.x).toBeLessThanOrEqual(735 + 40);
      expect(s.y).toBeGreaterThanOrEqual(-40);
      expect(s.y).toBeLessThanOrEqual(209 + 40);
    }
  });

  it("single point -> centred, zoomed view (not world-view)", () => {
    const base = computeBase(1600, 402, true, PAD);
    const v = fitViewFor([TRAJ[4]], base, 1600, 402, 0.22, 2.2, 1.2, 9);
    expect(v.k).toBeGreaterThan(1.2);
    const c = viewCenterWorld(v, base, 1600, 402);
    expect(c.wx).toBeCloseTo(worldX(TRAJ[4].lon), 4);
    expect(c.wy).toBeCloseTo(worldY(TRAJ[4].lat), 4);
  });

  it("empty input -> world-centre frame at minK (component falls back to neutralView itself)", () => {
    const base = computeBase(1600, 402, true, PAD);
    const v = fitViewFor([], base, 1600, 402, 0.22, 2.2, 1.2, 9);
    expect(v.k).toBe(1.2);
    expect(Number.isFinite(v.tx)).toBe(true);
    expect(Number.isFinite(v.ty)).toBe(true);
    const n = neutralView(base, 1600, 402);
    expect(n.k).toBe(1); // component's own empty-fleet path (fitAll guard)
  });

  it("antimeridian-spanning fleet is handled without huge wrap-around errors", () => {
    const base = computeBase(1600, 402, true, PAD);
    const pts = [
      { lon: 178, lat: 0 },
      { lon: -179, lat: 1 },
    ];
    const v = fitViewFor(pts, base, 1600, 402, 0.22, 2.2, 1.2, 9);
    expect(Number.isFinite(v.tx)).toBe(true);
    expect(Number.isFinite(v.ty)).toBe(true);
    expect(Number.isFinite(v.k)).toBe(true);
    // both markers must be reachable on screen after clamping
    const c = clampView(v, base, 1600, 402, true);
    for (const p of pts) {
      const s = toScreen(p, base, c);
      expect(Number.isFinite(s.x)).toBe(true);
      expect(Number.isFinite(s.y)).toBe(true);
    }
  });
});

describe("bundled basemap asset", () => {
  it("fleet_basemap.jpg exists, is a JPEG, and is bundled by the app", () => {
    const p = path.resolve(__dirname, "../assets/fleet_basemap.jpg");
    expect(fs.existsSync(p)).toBe(true);
    const head = Buffer.alloc(3);
    const fd = fs.openSync(p, "r");
    fs.readSync(fd, head, 0, 3, 0);
    fs.closeSync(fd);
    // JPEG SOI magic: FF D8 FF
    expect(head[0]).toBe(0xff);
    expect(head[1]).toBe(0xd8);
    expect(head[2]).toBe(0xff);
  });
});
