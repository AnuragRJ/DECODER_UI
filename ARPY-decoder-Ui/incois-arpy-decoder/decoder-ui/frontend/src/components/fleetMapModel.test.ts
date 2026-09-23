import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  LAYER_ORDER,
  MAP_COLORS,
  buildEezRegionDescriptor,
  buildMarkerDescriptors,
  buildPredictionDescriptors,
  buildTrajectoryDescriptor,
  circleRing,
  buildTransitionDescriptors,
  cycleLabelsVisible,
  frameExtentFor,
  sortTrajectoryChronologically,
  splitAntimeridianPath,
} from "./fleetMapModel";
import {
  parseIndiaEez,
  classifyTrajectory,
  deriveEezTransitions,
} from "../utils/indiaEez";

// Fixtures from REAL decoded runs (wmo 2901304 / 2901339 / 2902201 /
// 2902203 shape). All coordinates are genuine cycle locations.
const POSITIONS = [
  { wmo: 2901304, platform: "APEX", status: "cached", lat: -59.913, lon: 69.366, cyclesCount: 20 },
  { wmo: 2901339, platform: "APEX", status: "cached", lat: 55.482, lon: 11.727, cyclesCount: 72 },
  { wmo: 2902201, platform: "APEX", status: "cached", lat: 58.906, lon: -3.521, cyclesCount: 3 },
  { wmo: 2902203, platform: "APEX", status: "cached", lat: 59.732, lon: -5.801, cyclesCount: 3 },
];

// deliberately shuffled — builders must sort chronologically
const TRAJECTORY = [
  { cycle: 3, lat: -55.848, lon: 60.93 },
  { cycle: 1, lat: -55.937, lon: 58.515 },
  { cycle: 20, lat: -59.913, lon: 69.366 },
  { cycle: 2, lat: -55.834, lon: 60.041 },
  { cycle: 19, lat: -59.757, lon: 69.501 },
];

const artifact = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../../../data/geography/india_eez.geojson", import.meta.url)),
    "utf8"
  )
);
const eezGeom = parseIndiaEez(artifact);

describe("trajectory order", () => {
  it("sorts shuffled input chronologically (cycle asc, juld tiebreak)", () => {
    const ordered = sortTrajectoryChronologically(TRAJECTORY);
    expect(ordered.map((p) => p.cycle)).toEqual([1, 2, 3, 19, 20]);
  });

  it("dots carry every point with real, unmodified coordinates; latest flagged", () => {
    const ordered = sortTrajectoryChronologically(TRAJECTORY);
    const traj = buildTrajectoryDescriptor(ordered, 2901304, null)!;
    expect(traj.wmo).toBe(2901304);
    expect(traj.dots).toHaveLength(TRAJECTORY.length);
    expect(traj.dots.map((d) => d.cycle)).toEqual([1, 2, 3, 19, 20]);
    expect(traj.dots[4]).toMatchObject({ cycle: 20, lat: -59.913, lon: 69.366, isLast: true });
    expect(traj.dots.slice(0, 4).every((d) => !d.isLast)).toBe(true);
  });

  it("returns null below two points (no line to draw)", () => {
    expect(buildTrajectoryDescriptor([], 1, null)).toBeNull();
    expect(buildTrajectoryDescriptor([{ cycle: 1, lat: 0, lon: 0 }], 1, null)).toBeNull();
  });

  it("attaches per-cycle EEZ states from the workspace classification", () => {
    const pts = classifyTrajectory(eezGeom.geometry, [
      { cycle: 100, lon: 62.0, lat: 18.0, juld: 1 },
      { cycle: 101, lon: 69.5, lat: 18.5, juld: 2 },
    ]);
    const traj = buildTrajectoryDescriptor(sortTrajectoryChronologically(pts), 2901339, pts)!;
    expect(traj.dots.map((d) => d.eez)).toEqual(["OUTSIDE_INDIAN_EEZ", "INDIAN_EEZ"]);
  });
});

describe("antimeridian safety", () => {
  it("splits paths on >180° jumps instead of drawing across-the-world chords", () => {
    const paths = splitAntimeridianPath([
      { lon: 178, lat: 10 },
      { lon: 179.5, lat: 10 },
      { lon: -179.5, lat: 10 },
      { lon: -178, lat: 10 },
    ]);
    expect(paths).toHaveLength(2);
    expect(paths[0]).toHaveLength(2);
    expect(paths[1]).toHaveLength(2);
  });

  it("leaves ordinary tracks whole", () => {
    expect(splitAntimeridianPath(TRAJECTORY)).toHaveLength(1);
  });
});

describe("markers", () => {
  it("emits one descriptor per float with real coordinates", () => {
    const markers = buildMarkerDescriptors(POSITIONS, null, undefined, false);
    expect(markers.map((m) => m.wmo)).toEqual([2901304, 2901339, 2902201, 2902203]);
    expect(markers[0]).toMatchObject({ lon: 69.366, lat: -59.913, isSelected: false });
    expect(markers.every((m) => !m.insideEez)).toBe(true);
  });

  it("marks exactly the selected float", () => {
    const markers = buildMarkerDescriptors(POSITIONS, 2901339, undefined, false);
    expect(markers.filter((m) => m.isSelected).map((m) => m.wmo)).toEqual([2901339]);
  });

  it("inside-EEZ flag needs layer ON + ready current state (never an event)", () => {
    const current = { 2901339: "INDIAN_EEZ" as const, 2902201: "OUTSIDE_INDIAN_EEZ" as const };
    const on = buildMarkerDescriptors(POSITIONS, null, current, true);
    expect(on.find((m) => m.wmo === 2901339)!.insideEez).toBe(true);
    expect(on.find((m) => m.wmo === 2902201)!.insideEez).toBe(false);
    const off = buildMarkerDescriptors(POSITIONS, null, current, false);
    expect(off.every((m) => !m.insideEez)).toBe(true);
    const label = on.find((m) => m.wmo === 2901339)!.title;
    expect(label).toContain("currently inside Indian EEZ");
    expect(off.find((m) => m.wmo === 2901339)!.title).not.toContain("inside Indian EEZ");
  });

  it("EEZ marker blinking: only inside floats blink when toggle is ON; all static when OFF", () => {
    const current = { 2901339: "INDIAN_EEZ" as const, 2902201: "OUTSIDE_INDIAN_EEZ" as const };
    // Toggle ON -> only inside float has isBlinking true
    const on = buildMarkerDescriptors(POSITIONS, null, current, true);
    expect(on.find((m) => m.wmo === 2901339)!.isBlinking).toBe(true);
    expect(on.find((m) => m.wmo === 2902201)!.isBlinking).toBe(false);
    expect(on.filter((m) => m.isBlinking).map((m) => m.wmo)).toEqual([2901339]);

    // Toggle OFF -> all markers must remain static (isBlinking is false for all)
    const off = buildMarkerDescriptors(POSITIONS, null, current, false);
    expect(off.every((m) => m.isBlinking === false)).toBe(true);
    expect(off.find((m) => m.wmo === 2901339)!.isBlinking).toBe(false);
  });

  it("blinking updates automatically as float positions change", () => {
    // Float initially outside Indian EEZ
    const floatA = { wmo: 5900001, platform: "ARVOR", status: "completed", lat: 25.0, lon: 60.0, cyclesCount: 1 };
    const initial = buildMarkerDescriptors([floatA], null, undefined, true, eezGeom);
    expect(initial[0].insideEez).toBe(false);
    expect(initial[0].isBlinking).toBe(false);

    // Float reports new verified position inside Indian EEZ polygon
    const floatAMoved = { ...floatA, lat: 18.236, lon: 69.731 };
    const updated = buildMarkerDescriptors([floatAMoved], null, undefined, true, eezGeom);
    expect(updated[0].insideEez).toBe(true);
    expect(updated[0].isBlinking).toBe(true);

    // Toggle switched OFF -> marker reverts to static immediately
    const toggleOff = buildMarkerDescriptors([floatAMoved], null, undefined, false, eezGeom);
    expect(toggleOff[0].insideEez).toBe(false);
    expect(toggleOff[0].isBlinking).toBe(false);
  });

  it("titles use the neutral status wording", () => {
    const markers = buildMarkerDescriptors(
      [{ wmo: 1, platform: "APEX", status: "completed", lat: 0, lon: 0, cyclesCount: 1 }],
      null, undefined, false
    );
    expect(markers[0].title).toContain("SUCCESS");
  });
});

describe("transitions", () => {
  it("diamonds sit on the real to-cycle point and keep the exact description", () => {
    const pts = classifyTrajectory(eezGeom.geometry, [
      { cycle: 100, lon: 62.0, lat: 18.0, juld: 1 },
      { cycle: 101, lon: 69.5, lat: 18.5, juld: 2 },
    ]);
    const evts = deriveEezTransitions(2901339, pts);
    expect(evts).toHaveLength(1);
    const byCycle = new Map(pts.map((p) => [p.cycle, { lon: p.lon, lat: p.lat }]));
    const diamonds = buildTransitionDescriptors(evts, byCycle);
    expect(diamonds).toHaveLength(1);
    expect(diamonds[0]).toMatchObject({ eventType: "EEZ_ENTRY", lon: 69.5, lat: 18.5 });
    expect(diamonds[0].description).toContain("entered the Indian EEZ between Cycle 100 and Cycle 101");
  });

  it("drops transitions whose to-cycle point is missing (never guessed)", () => {
    const pts = classifyTrajectory(eezGeom.geometry, [
      { cycle: 100, lon: 62.0, lat: 18.0, juld: 1 },
      { cycle: 101, lon: 69.5, lat: 18.5, juld: 2 },
    ]);
    const evts = deriveEezTransitions(2901339, pts);
    expect(buildTransitionDescriptors(evts, new Map())).toHaveLength(0);
  });
});

describe("EEZ region", () => {
  it("passes the real disjoint polygons through with an interior anchor", () => {
    const region = buildEezRegionDescriptor(eezGeom);
    expect(region.polygons.length).toBeGreaterThan(0);
    expect(region.anchor.lon).toBeGreaterThan(60);
    expect(region.anchor.lon).toBeLessThan(100);
    expect(region.anchor.lat).toBeGreaterThan(0);
    expect(region.anchor.lat).toBeLessThan(30);
  });

  it("keeps the restrained teal/cyan treatment (no neon, no maroon)", () => {
    expect(MAP_COLORS.eezFill).toBe("rgba(20,160,150,0.11)");
    expect(MAP_COLORS.eezBoundary).toBe("rgba(103,232,249,0.85)");
    expect(MAP_COLORS.eezUnderStroke).toBe("rgba(103,232,249,0.22)");
    const palette = Object.values(MAP_COLORS).join(" ");
    expect(palette).not.toContain("rgba(0,255,");
    expect(palette).not.toContain("rgba(122,31,42");
    expect(palette).not.toContain("rgba(205,105,115");
  });

  it("keeps the established marker/trajectory/operational palette", () => {
    expect(MAP_COLORS.markerFill).toBe("#fbbf24");
    expect(MAP_COLORS.markerFillSelected).toBe("#fde047");
    expect(MAP_COLORS.selectionRing).toBe("#fde047");
    expect(MAP_COLORS.trajectoryLine).toBe("#7dd3fc");
    expect(MAP_COLORS.cycleDot).toBe("#7dd3fc");
    expect(MAP_COLORS.cycleDotLast).toBe("#fbbf24");
    expect(MAP_COLORS.operationalRed).toBe("rgba(248,113,113,0.95)");
  });
});

describe("layer order", () => {
  it("trajectory paints above fleet markers so it can never hide", () => {
    expect(LAYER_ORDER.indexOf("trajectory-line")).toBeGreaterThan(-1);
    expect(LAYER_ORDER.indexOf("markers")).toBeGreaterThan(-1);
    expect(LAYER_ORDER.indexOf("trajectory-line")).toBeLessThan(LAYER_ORDER.indexOf("markers"));
    expect(LAYER_ORDER.indexOf("cycle-dots")).toBeLessThan(LAYER_ORDER.indexOf("markers"));
    expect(LAYER_ORDER.indexOf("labels")).toBe(LAYER_ORDER.length - 1);
  });
});

describe("cycle-label declutter", () => {
  it("shows labels only when consecutive dots are >= 9 px apart", () => {
    expect(cycleLabelsVisible([{ x: 0, y: 0 }, { x: 9, y: 0 }])).toBe(true);
    expect(cycleLabelsVisible([{ x: 0, y: 0 }, { x: 8.9, y: 0 }])).toBe(false);
  });

  it("needs at least 2 dots and refuses more than 64", () => {
    expect(cycleLabelsVisible([])).toBe(false);
    expect(cycleLabelsVisible([{ x: 0, y: 0 }])).toBe(false);
    const many = Array.from({ length: 65 }, (_, i) => ({ x: i * 20, y: 0 }));
    expect(cycleLabelsVisible(many)).toBe(false);
  });
});

describe("frame extents", () => {
  it("frames real points with breathing room, null when empty", () => {
    expect(frameExtentFor([], 0.1, 6)).toBeNull();
    const ext = frameExtentFor(
      [{ lon: 69.366, lat: -59.913 }, { lon: 11.727, lat: 55.482 }],
      0.1, 6
    )!;
    expect(ext.xmin).toBeLessThan(11.727);
    expect(ext.xmax).toBeGreaterThan(69.366);
    expect(ext.ymin).toBeLessThan(-59.913);
    expect(ext.ymax).toBeGreaterThan(55.482);
  });

  it("keeps tiny clusters inspectable via the minimum span", () => {
    const ext = frameExtentFor([{ lon: 70, lat: 18 }, { lon: 70.05, lat: 18.02 }], 0.22, 2.2)!;
    expect(ext.xmax - ext.xmin).toBeGreaterThanOrEqual(2.2);
    expect(ext.ymax - ext.ymin).toBeGreaterThanOrEqual(2.2);
  });

  it("frames antimeridian-spanning sets the short way", () => {
    const ext = frameExtentFor([{ lon: 179, lat: 10 }, { lon: -179, lat: 11 }], 0, 0)!;
    expect(ext.xmax - ext.xmin).toBeLessThan(180);
  });
});

describe("prediction layer descriptors (optional, experimental)", () => {
  const prediction = {
    wmo: 2901304,
    lat: -20.5,
    lon: 65.25,
    fromLat: -20.0,
    fromLon: 65.0,
    r50Km: 22.4,
    r90Km: 71.9,
    methodLabel: "History + Prior",
    targetTimeIso: "2026-10-01T00:00:00Z",
  };

  it("paints only real, validated predictions and never invents coordinates", () => {
    const out = buildPredictionDescriptors(
      [
        prediction,
        { ...prediction, wmo: 2, lat: Number.NaN },
        { ...prediction, wmo: 3, lon: 999 },
        { ...prediction, wmo: 4, lat: 200 },
      ],
      2901304
    );
    expect(out.map((d) => d.wmo)).toEqual([2901304]);
    expect(out[0].isSelected).toBe(true);
    expect(out[0].label).toBe("P2901304");
    expect(out[0].r90Km).toBe(71.9);
    expect(out[0].title).toContain("predicted next profile");
    expect(out[0].title).toContain("History + Prior");
    expect(out[0].title).toContain("90% radius 71.9 km");
  });

  it("keeps the dashed connector only when the real position is known", () => {
    const withLink = buildPredictionDescriptors([prediction], null)[0];
    expect(withLink.link).toEqual({ lon: 65.0, lat: -20.0 });
    const noLink = buildPredictionDescriptors([{ ...prediction, fromLat: null, fromLon: null }], null)[0];
    expect(noLink.link).toBeNull();
    expect(noLink.isSelected).toBe(false);
  });

  it("renders the prediction layer above the trajectory and below the markers", () => {
    const order = [...LAYER_ORDER];
    expect(order.indexOf("prediction")).toBeGreaterThan(order.indexOf("cycle-dots"));
    expect(order.indexOf("prediction")).toBeLessThan(order.indexOf("markers"));
  });

  it("builds a closed uncertainty ring of the requested radius", () => {
    const ring = circleRing(60, -10, 50, 36);
    expect(ring).toHaveLength(37);
    expect(ring[0]).toEqual(ring[ring.length - 1]);
    // Every vertex sits on the requested great-circle radius (geodesic ring).
    const toRad = (d: number) => (d * Math.PI) / 180;
    const haversine = (lat1: number, lon1: number, lat2: number, lon2: number) => {
      const dLat = toRad(lat2 - lat1);
      const dLon = toRad(lon2 - lon1);
      const a = Math.sin(dLat / 2) ** 2 +
        Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
      return 2 * 6371.0088 * Math.asin(Math.min(1, Math.sqrt(a)));
    };
    for (const [lon, lat] of ring) {
      expect(Math.abs(haversine(-10, 60, lat, lon) - 50)).toBeLessThan(0.001);
    }
    // A pole-adjacent ring stays finite and still measures the quoted radius.
    for (const [lon, lat] of circleRing(0, 89.5, 120, 36)) {
      expect(Math.abs(haversine(89.5, 0, lat, lon) - 120)).toBeLessThan(0.01);
    }
    expect(circleRing(60, -10, 0)).toHaveLength(0);
  });
});
