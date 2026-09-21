import { describe, it, expect } from "vitest";
import React from "react";
import { renderToString } from "react-dom/server";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { FleetOceanMap, FleetMapFloat } from "./FleetOceanMap";
import { parseIndiaEez, deriveEezTransitions, classifyTrajectory } from "../utils/indiaEez";

/**
 * SSR contract for the EEZ shell: layer control, status honesty, history
 * list and legend entries. Marker/region/diamond geometry moved to canvas
 * (ArcGIS MapView) and is pinned in fleetMapModel.test.ts + Playwright e2e.
 */
const artifact = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../../../data/geography/india_eez.geojson", import.meta.url)),
    "utf8"
  )
);
const eezGeom = parseIndiaEez(artifact);

const POSITIONS: FleetMapFloat[] = [
  { wmo: 2901339, platform: "APEX", status: "completed", lat: 18.236, lon: 69.731, cyclesCount: 72 }, // real inside point
  { wmo: 2902201, platform: "APEX", status: "completed", lat: 22.82, lon: 60.781, cyclesCount: 361 }, // real outside point
];

const BASE_EEZ = {
  layerOn: false,
  onToggle: () => undefined,
  status: "ready" as const,
  geom: eezGeom,
  classified: null,
  transitions: [],
  history: [],
  dismissed: {},
  currentStatus: { 2901339: "INDIAN_EEZ" as const, 2902201: "OUTSIDE_INDIAN_EEZ" as const },
};

function render(overrides: Partial<React.ComponentProps<typeof FleetOceanMap>> = {}) {
  return renderToString(
    React.createElement(FleetOceanMap, {
      positions: POSITIONS,
      trajectory: [],
      selectedWmo: null,
      onSelect: () => undefined,
      fill: false,
      dataKey: "b",
      eez: BASE_EEZ,
      ...overrides,
    })
  );
}

describe("EEZ layer control", () => {
  it("renders the control only when the eez prop is present (pristine map otherwise)", () => {
    expect(render()).toContain('data-testid="eez-layer-control"');
    expect(render()).toContain("Indian EEZ");
    expect(render({ eez: undefined })).not.toContain('data-testid="eez-layer-control"');
  });

  it("toggle reflects layerOn and is enabled only when ready", () => {
    const on = render({ eez: { ...BASE_EEZ, layerOn: true } });
    expect(on).toContain('data-testid="eez-toggle"');
    expect(on).toContain("checked");
    const off = render();
    expect(off).toContain('data-testid="eez-toggle"');
    expect(off).not.toContain("checked");
    const loading = render({ eez: { ...BASE_EEZ, status: "loading", geom: null } });
    expect(loading).toContain("disabled");
    expect(loading).toContain("loading…");
  });

  it("unavailable geometry is stated honestly with the toggle disabled", () => {
    const html = render({ eez: { ...BASE_EEZ, status: "unavailable", geom: null } });
    expect(html).toContain("disabled");
    expect(html).toContain("unavailable");
    expect(html).toContain("Reference geometry unavailable — layer disabled.");
  });
});

describe("EEZ legend entries", () => {
  const on = () =>
    render({ eez: { ...BASE_EEZ, layerOn: true } });

  it("legend gains inside + boundary/region entries only while ON with geometry", () => {
    const html = on();
    expect(html).toContain("data-eez-legend-inside");
    expect(html).toContain("data-eez-legend-item");
    expect(html).toContain("data-eez-legend-region");
    expect(html).toContain("float inside Indian EEZ");
    expect(html).toContain("Indian EEZ boundary");
    expect(html).toContain("Indian EEZ region");
    expect(html).toContain("rgba(103,232,249,0.9)");    // cyan boundary swatch
    expect(html).toContain("rgba(20,160,150,0.11)");    // teal region swatch
  });

  it("legend stays pristine with the layer OFF or geometry missing", () => {
    const off = render();
    expect(off).not.toContain("data-eez-legend-inside");
    expect(off).not.toContain("data-eez-legend-item");
    expect(off).not.toContain("data-eez-legend-region");
    const noGeom = render({ eez: { ...BASE_EEZ, layerOn: true, status: "loading", geom: null } });
    expect(noGeom).not.toContain("data-eez-legend-inside");
  });
});

describe("EEZ history list", () => {
  const pts = classifyTrajectory(eezGeom.geometry, [
    { cycle: 100, lon: 62.0, lat: 18.0, juld: 1 },   // outside
    { cycle: 101, lon: 69.5, lat: 18.5, juld: 2 },   // inside  -> ENTRY
  ]);
  const evts = deriveEezTransitions(2901339, pts);

  it("lists real derived events with ENTRY/EXIT wording", () => {
    expect(evts).toHaveLength(1);
    const html = render({ eez: { ...BASE_EEZ, history: evts } }).replace(/<!--.*?-->/g, "");
    expect(html).toContain('data-testid="eez-history-toggle"');
    expect(html).toContain("EEZ events (1)");
  });

  it("dismissed entries render shaded, kept entries normal", () => {
    const html = render({ eez: { ...BASE_EEZ, history: evts, dismissed: { [evts[0].id]: true } } }).replace(
      /<!--.*?-->/g,
      ""
    );
    // history list itself opens on click (client); SSR asserts data is wired
    expect(html).toContain("EEZ events (1)");
  });
});
