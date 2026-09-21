import { describe, it, expect } from "vitest";
import React from "react";
import { renderToString } from "react-dom/server";
import {
  FleetOceanMap,
  FleetMapFloat,
  FleetMapTrajectoryPoint,
} from "./FleetOceanMap";

// Fixtures built from a REAL decoded run (wmo 2901304 / 2901339 / 2902201 /
// 2902203 shape). All coordinates are genuine cycle locations.
const POSITIONS: FleetMapFloat[] = [
  { wmo: 2901304, platform: "APEX", status: "cached", lat: -59.913, lon: 69.366, cyclesCount: 20 },
  { wmo: 2901339, platform: "APEX", status: "cached", lat: 55.482, lon: 11.727, cyclesCount: 72 },
  { wmo: 2902201, platform: "APEX", status: "cached", lat: 58.906, lon: -3.521, cyclesCount: 3 },
  { wmo: 2902203, platform: "APEX", status: "cached", lat: 59.732, lon: -5.801, cyclesCount: 3 },
];

const TRAJECTORY: FleetMapTrajectoryPoint[] = [
  { cycle: 3, lat: -55.848, lon: 60.93 },
  { cycle: 1, lat: -55.937, lon: 58.515 },
  { cycle: 20, lat: -59.913, lon: 69.366 },
  { cycle: 2, lat: -55.834, lon: 60.041 },
  { cycle: 19, lat: -59.757, lon: 69.501 },
];

const noop = () => undefined;

function renderMap(overrides: Partial<React.ComponentProps<typeof FleetOceanMap>> = {}) {
  return renderToString(
    React.createElement(FleetOceanMap, {
      positions: POSITIONS,
      trajectory: [],
      selectedWmo: null,
      onSelect: noop,
      fill: false,
      dataKey: "batch-test",
      ...overrides,
    })
  );
}

describe("FleetOceanMap SSR (Esri shell contract)", () => {
  // The ArcGIS MapView paints to canvas in the browser only (lazy effect);
  // SSR renders the shell: surface container, header, controls, legend.
  // Marker/trajectory/EEZ geometry logic is pinned in fleetMapModel.test.ts
  // and the live canvas is covered by the Playwright e2e.
  it("renders the Esri map surface with role/aria labelling", () => {
    const html = renderMap();
    expect(html).toContain('data-testid="esri-map-view"');
    expect(html).toContain('role="img"');
    expect(html).toContain("aria-label");
    expect(html).toContain("Esri");
  });

  it("shows the honest loading chip until the view initializes", () => {
    const html = renderMap();
    expect(html).toContain("Loading map…");
  });

  it("renders the header count copy even with ZERO positions", () => {
    const html = renderMap({ positions: [] }).replace(/<!--.*?-->/g, "");
    expect(html).toContain("with valid decoded positions");
    expect(html).toContain("0 floats");
  });

  it("announces the selected trajectory in the header", () => {
    const html = renderMap({ selectedWmo: 2901304, trajectory: TRAJECTORY });
    expect(html).toContain("trajectory WMO 2901304");
    const none = renderMap({ selectedWmo: 2901304, trajectory: [] });
    expect(none).not.toContain("trajectory WMO");
  });

  it("shows the FIT chip in normal mode with positions (never in fill mode)", () => {
    expect(renderMap()).toContain("data-fit-chip");
    expect(renderMap({ fill: true })).not.toContain("data-fit-chip");
    expect(renderMap({ positions: [] })).not.toContain("data-fit-chip");
  });

  it("zoom buttons + FIT exist in full-screen (fill) mode", () => {
    const html = renderMap({ fill: true });
    expect(html).toContain('data-testid="map-zoom-in"');
    expect(html).toContain('data-testid="map-zoom-out"');
    expect(html).toContain('data-testid="map-fit"');
    const normal = renderMap();
    expect(normal).not.toContain('data-testid="map-zoom-in"');
  });

  it("legend always explains float positions; trajectory entry only with a track", () => {
    const html = renderMap({ selectedWmo: 2901304, trajectory: TRAJECTORY });
    expect(html).toContain("float position");
    expect(html).toContain("trajectory");
    expect(html).toContain("positions &amp; tracks from decode run history");
    const noTraj = renderMap();
    expect(noTraj).toContain("float position");
    expect(noTraj).not.toContain("trajectory");
  });

  it("keeps the map surface empty server-side (no SDK, no network from SSR)", () => {
    const html = renderMap();
    expect(html).not.toContain("esri-view");
    expect(html).not.toContain("<canvas");
  });
});

describe("FleetOceanMap prediction layer (optional, OFF by default)", () => {
  const PREDICTIONS = [
    { wmo: 2901304, lat: -59.9, lon: 69.4, fromLat: -59.8, fromLon: 69.3, r50Km: 22.0, r90Km: 70.0,
      methodLabel: "History + Prior", targetTimeIso: "2026-10-01T00:00:00Z" },
  ];

  it("hides the layer control when no float has a prediction", () => {
    expect(renderMap()).not.toContain('data-testid="prediction-layer-toggle"');
  });

  it("offers an unchecked (OFF by default) toggle and leaves existing layers untouched", () => {
    const html = renderMap({ predictions: PREDICTIONS });
    expect(html).toContain('data-testid="prediction-layer-toggle"');
    expect(html).toContain("Predicted next profile (");
    // The toggle is rendered UNCHECKED (no checked attribute in SSR output):
    // enabling the experimental layer is an explicit operator action.
    expect(html).toMatch(/<input type="checkbox"[^>]*data-testid="prediction-layer-toggle"\/>/);
    // Existing surfaces are unchanged.
    expect(html).toContain('data-testid="esri-map-view"');
    expect(html).toContain("Fleet positions");
  });
});
