/**
 * Unit tests for the Indian EEZ classification + transition logic.
 *
 *  - Fixture geometry exercises the pure algorithms (spec permits fixtures
 *    in tests only).
 *  - The REAL verified artifact at ../../../data/geography/india_eez.geojson
 *    is additionally parsed and probed, so the frontend classifier can never
 *    drift away from the exact dataset the backend serves.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  EEZ_ALERT_TITLES,
  classifyPoint,
  classifyTrajectory,
  deriveEezTransitions,
  findInteriorAnchor,
  parseIndiaEez,
  pointInIndiaEez,
  type EezPosition,
} from "./indiaEez";

// ---------------------------------------------------------------------------
// Fixture geometry: a tiny fabricated "EEZ zone" used ONLY to test the
// algorithms. Marked letters remind: not geography, never shipped to the UI.
// ---------------------------------------------------------------------------
const SQUARE = [
  [0, 0], [10, 0], [10, 10], [0, 10], [0, 0],
] as number[][];
// hole fully inside the square
const HOLE = [
  [3, 3], [7, 3], [7, 7], [3, 7], [3, 3],
] as number[][];
// second distinct square far away
const FAR_SQUARE = [
  [20, 20], [30, 20], [30, 30], [20, 30], [20, 20],
] as number[][];

function fixtureEez(mrgids: [number, number]) {
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {
          MRGID: mrgids[0],
          GEONAME: "TEST zone A",
          POL_TYPE: "200NM",
          TERRITORY1: "India",
          SOVEREIGN1: "India",
        },
        geometry: { type: "MultiPolygon", coordinates: [[SQUARE, HOLE], [FAR_SQUARE]] },
      },
      {
        type: "Feature",
        properties: {
          MRGID: mrgids[1],
          GEONAME: "TEST zone B",
          POL_TYPE: "200NM",
          TERRITORY1: "India",
          SOVEREIGN1: "India",
        },
        geometry: { type: "Polygon", coordinates: [FAR_SQUARE] },
      },
    ],
  };
}

// The parser deliberately refuses non-India extents (anti-substitution
// defense), so algorithmic fixtures use a tiny hand-built geometry object
// through the exported low-level API, while parse() is exercised separately.
const FIXTURE_GEOM = {
  polygons: [
    [SQUARE, HOLE],
    [FAR_SQUARE],
  ],
} as const;

describe("point-in-polygon (fixture geometry)", () => {
  it("classifies inside/outside/hole exactly", () => {
    expect(pointInIndiaEez(FIXTURE_GEOM as any, 1, 1)).toBe(true);   // in outer, outside hole
    expect(pointInIndiaEez(FIXTURE_GEOM as any, 5, 5)).toBe(false);  // inside hole
    expect(pointInIndiaEez(FIXTURE_GEOM as any, 9.5, 9.5)).toBe(true);
    expect(pointInIndiaEez(FIXTURE_GEOM as any, 15, 15)).toBe(false);
    expect(pointInIndiaEez(FIXTURE_GEOM as any, 25, 25)).toBe(true); // second polygon
    expect(pointInIndiaEez(FIXTURE_GEOM as any, -1, 5)).toBe(false);
  });

  it("rejects malformed coordinates instead of guessing", () => {
    expect(pointInIndiaEez(FIXTURE_GEOM as any, NaN, 5)).toBe(false);
    expect(pointInIndiaEez(FIXTURE_GEOM as any, 5, Infinity)).toBe(false);
    expect(pointInIndiaEez(FIXTURE_GEOM as any, 200, 5)).toBe(false);
    expect(pointInIndiaEez(FIXTURE_GEOM as any, 5, 95)).toBe(false);
  });

  it("maps to the INDIAN_EEZ / OUTSIDE_INDIAN_EEZ status pair", () => {
    expect(classifyPoint(FIXTURE_GEOM as any, 1, 1)).toBe("INDIAN_EEZ");
    expect(classifyPoint(FIXTURE_GEOM as any, 15, 15)).toBe("OUTSIDE_INDIAN_EEZ");
    expect(classifyPoint(FIXTURE_GEOM as any, 25, 25)).toBe("INDIAN_EEZ");
  });
});

describe("parseIndiaEez validation", () => {
  it("rejects non-FeatureCollection, empty and non-polygon artifacts", () => {
    expect(() => parseIndiaEez(null)).toThrow("not a FeatureCollection");
    expect(() => parseIndiaEez({ type: "FeatureCollection", features: [] })).toThrow("no features");
    const badGeom = fixtureEez([8333, 8480]);
    (badGeom.features[0] as any).geometry = { type: "LineString", coordinates: [[0, 0], [1, 1]] };
    expect(() => parseIndiaEez(badGeom)).toThrow("unsupported geometry");
  });

  it("rejects wrong feature sets, non-India sovereigns and unclosed rings", () => {
    const wrongId = fixtureEez([8333, 9999]);
    expect(() => parseIndiaEez(JSON.parse(JSON.stringify(wrongId)))).toThrow();

    const foreign: any = fixtureEez([8333, 8480]);
    foreign.features[1].properties.SOVEREIGN1 = "Maldives";
    expect(() => parseIndiaEez(foreign)).toThrow();

    const unclosed: any = fixtureEez([8333, 8480]);
    unclosed.features[0].geometry.coordinates[0][0] = SQUARE.slice(1); // remove closing vertex
    expect(() => parseIndiaEez(unclosed)).toThrow();
  });

  it("rejects non-India extents (anti-substitution guard)", () => {
    const z: any = fixtureEez([8333, 8480]); // squares at 0..30 => not India extent
    expect(() => parseIndiaEez(z)).toThrow("India-only");
  });
});

describe("classification + transition derivation (fixture geometry)", () => {
  const pts: EezPosition[] = [
    { cycle: 1, lon: 15, lat: 5, juld: 100 },   // OUT
    { cycle: 2, lon: 15, lat: 6, juld: 110 },   // OUT
    { cycle: 3, lon: 5, lat: 2, juld: 120 },    // IN  -> entry 2->3
    { cycle: 4, lon: 25, lat: 25, juld: 121 },  // IN
    { cycle: 5, lon: 15, lat: 7, juld: 130 },   // OUT -> exit 4->5
    { cycle: 6, lon: 15, lat: 8, juld: 140 },   // OUT
  ];

  it("assigns per-cycle status — a separate dimension, never touching decode state", () => {
    const classified = classifyTrajectory(FIXTURE_GEOM as any, pts);
    expect(classified.map((c) => c.eezStatus)).toEqual([
      "OUTSIDE_INDIAN_EEZ",
      "OUTSIDE_INDIAN_EEZ",
      "INDIAN_EEZ",
      "INDIAN_EEZ",
      "OUTSIDE_INDIAN_EEZ",
      "OUTSIDE_INDIAN_EEZ",
    ]);
    // input objects untouched
    expect((pts[0] as any).eezStatus).toBeUndefined();
  });

  it("emits entry/exit transitions ONLY on actual consecutive status flips", () => {
    const transitions = deriveEezTransitions(2901234, classifyTrajectory(FIXTURE_GEOM as any, pts));
    expect(transitions).toHaveLength(2);
    const [entry, exit] = transitions;
    expect(entry.eventType).toBe("EEZ_ENTRY");
    expect([entry.fromCycle, entry.toCycle]).toEqual([2, 3]);
    expect(exit.eventType).toBe("EEZ_EXIT");
    expect([exit.fromCycle, exit.toCycle]).toEqual([4, 5]);
  });

  it("keeps quiet on monotonic journeys (no flips, no events)", () => {
    const allIn = pts.map((p) => ({ ...p, lon: 25, lat: 25 }));
    expect(deriveEezTransitions(1, classifyTrajectory(FIXTURE_GEOM as any, allIn))).toEqual([]);
    const allOut = pts.map((p) => ({ ...p, lon: 15, lat: 6 }));
    expect(deriveEezTransitions(1, classifyTrajectory(FIXTURE_GEOM as any, allOut))).toEqual([]);
  });

  it("uses STABLE identities: rerun derive -> identical ids (dedupe-ready)", () => {
    const a = deriveEezTransitions(2901234, classifyTrajectory(FIXTURE_GEOM as any, pts));
    const b = deriveEezTransitions(2901234, classifyTrajectory(FIXTURE_GEOM as any, [...pts].reverse()));
    expect(b.map((t) => t.id)).toEqual(a.map((t) => t.id));
    expect(a[0].id).toBe("eez|2901234|2|3|EEZ_ENTRY");
  });

  it("sorts by CYCLE_NUMBER with JULD tiebreak (input order never trusted)", () => {
    const jumbled: EezPosition[] = [
      { cycle: 3, lon: 5, lat: 2, juld: 120 },
      { cycle: 1, lon: 15, lat: 5, juld: 100 },
      { cycle: 2, lon: 15, lat: 6, juld: 110 },
    ];
    const transitions = deriveEezTransitions(7, classifyTrajectory(FIXTURE_GEOM as any, jumbled));
    expect(transitions).toHaveLength(1);
    expect(transitions[0].id).toBe("eez|7|2|3|EEZ_ENTRY");
  });

  it("drops cycles without valid coordinates rather than classifying them elsewhere", () => {
    const withGaps: EezPosition[] = [
      { cycle: 1, lon: 15, lat: 5 },
      { cycle: 2, lon: NaN, lat: NaN },
      { cycle: 3, lon: 5, lat: 2 },
      { cycle: 4, lon: 200, lat: 10 }, // invalid range -> filtered
      { cycle: 5, lon: 15, lat: 9 },
    ];
    const classified = classifyTrajectory(FIXTURE_GEOM as any, withGaps);
    expect(classified.map((c) => c.cycle)).toEqual([1, 3, 5]);
    const transitions = deriveEezTransitions(9, classified);
    // 1(OUT) -> 3(IN) entry, 3(IN) -> 5(OUT) exit; cycle 2/4 must be invisible
    expect(transitions.map((t) => t.id)).toEqual(["eez|9|1|3|EEZ_ENTRY", "eez|9|3|5|EEZ_EXIT"]);
  });

  it("uses only neutral scientific wording + sanctioned alert titles", () => {
    const transitions = deriveEezTransitions(2901234, classifyTrajectory(FIXTURE_GEOM as any, pts));
    for (const t of transitions) {
      expect(EEZ_ALERT_TITLES[t.eventType]).toMatch(/^Indian EEZ (Entry|Exit) Detected$/);
      expect(t.description).toBe(
        `WMO 2901234 ${t.eventType === "EEZ_ENTRY" ? "entered" : "exited"} the Indian EEZ ` +
          `between Cycle ${t.fromCycle} and Cycle ${t.toCycle} based on the available decoded positions`
      );
      const banned = /illegal|violation|unauthorized|intrusion|breach/i;
      expect(EEZ_ALERT_TITLES[t.eventType]).not.toMatch(banned);
      expect(t.description).not.toMatch(banned);
      // never claims an exact crossing location/time
      expect(t.description).not.toMatch(/at \(\d| at \d|UTC|local/);
    }
  });
});

describe("real verified artifact (dataset truth)", () => {
  const artifact = JSON.parse(
    readFileSync(
      fileURLToPath(new URL("../../../data/geography/india_eez.geojson", import.meta.url)),
      "utf8"
    )
  );

  it("parses the production geometry with declared provenance", () => {
    const eez = parseIndiaEez(artifact);
    expect(eez.meta.mrgids).toEqual([8333, 8480]);
    expect(eez.meta.featureCount).toBe(2);
    expect(eez.geometry.polygons.length).toBeGreaterThanOrEqual(2);
  });

  it("yields a deterministic anchor that really is inside the EEZ", () => {
    const eez = parseIndiaEez(artifact);
    const a = findInteriorAnchor(eez.geometry);
    const b = findInteriorAnchor(eez.geometry);
    expect(a).toEqual(b); // deterministic, memo-safe
    expect(pointInIndiaEez(eez.geometry, a.lon, a.lat)).toBe(true); // real interior lon/lat
  });

  it("classifies canonical ocean points against the real Indian EEZ", () => {
    const eez = parseIndiaEez(artifact);
    // Internally consistent, geographically meaningful probes (validated
    // against three independent extractions of the same dataset).
    expect(classifyPoint(eez.geometry, 71.0, 19.0)).toBe("INDIAN_EEZ");     // off Mumbai
    expect(classifyPoint(eez.geometry, 87.5, 20.5)).toBe("INDIAN_EEZ");     // off Odisha
    expect(classifyPoint(eez.geometry, 81.0, 12.0)).toBe("INDIAN_EEZ");     // off Chennai
    expect(classifyPoint(eez.geometry, 94.5, 12.0)).toBe("INDIAN_EEZ");     // Andaman Sea
    expect(classifyPoint(eez.geometry, 67.5, 15.0)).toBe("OUTSIDE_INDIAN_EEZ"); // deep Arabian Sea (>200 NM)
    expect(classifyPoint(eez.geometry, 77.5, 2.0)).toBe("OUTSIDE_INDIAN_EEZ");  // far south
    expect(classifyPoint(eez.geometry, 96.5, 13.0)).toBe("OUTSIDE_INDIAN_EEZ"); // Thai zone
    expect(classifyPoint(eez.geometry, 80.2, 13.1)).toBe("OUTSIDE_INDIAN_EEZ"); // on land: never in EEZ
  });
});
