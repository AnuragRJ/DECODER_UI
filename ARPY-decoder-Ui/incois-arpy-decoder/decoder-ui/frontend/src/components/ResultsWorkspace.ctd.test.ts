import { describe, expect, it } from "vitest";
import React from "react";
import { renderToString } from "react-dom/server";
import {
  CtdMeasurementRecordsPanel,
  formatHeaderCoord,
  resolveCycleCoordinates,
} from "./ResultsWorkspace";
import type { CycleRecord } from "../types";
import type { CtdRecord } from "./ScientificProfileChart";
import type { FleetMapTrajectoryPoint } from "./fleetMapModel";

describe("ResultsWorkspace - CTD Header Coordinates Resolution", () => {
  const baseCycle: CycleRecord = {
    cycle_number: 5,
    status: "completed",
    messages_received: 10,
    messages_selected: 10,
    levels_count: 50,
    engineering_data: {},
    rtqc_summary: {},
    ctd_samples: [],
    errors: [],
  };

  it("resolves coordinates directly from cycle record when present", () => {
    const cycle: CycleRecord = {
      ...baseCycle,
      latitude: 18.236,
      longitude: 69.731,
    };
    const coords = resolveCycleCoordinates(cycle);
    expect(coords).toEqual({ lat: 18.236, lon: 69.731 });
  });

  it("resolves coordinates from trajectory points matching the selected cycle", () => {
    const cycle: CycleRecord = {
      ...baseCycle,
      latitude: undefined,
      longitude: undefined,
    };
    const trajectory: FleetMapTrajectoryPoint[] = [
      { cycle: 1, lat: 12.0, lon: 65.0 },
      { cycle: 5, lat: 15.421, lon: 71.889 },
      { cycle: 6, lat: 15.892, lon: 72.103 },
    ];
    const coords = resolveCycleCoordinates(cycle, trajectory);
    expect(coords).toEqual({ lat: 15.421, lon: 71.889 });
  });

  it("resolves coordinates from allCycles matching the selected cycle if currentCycle coordinates are missing", () => {
    const cycle: CycleRecord = {
      ...baseCycle,
      cycle_number: 12,
      latitude: undefined,
      longitude: undefined,
    };
    const allCycles: CycleRecord[] = [
      { ...baseCycle, cycle_number: 10, latitude: 10.0, longitude: 60.0 },
      { ...baseCycle, cycle_number: 12, latitude: 11.234, longitude: 61.567 },
    ];
    const coords = resolveCycleCoordinates(cycle, [], allCycles);
    expect(coords).toEqual({ lat: 11.234, lon: 61.567 });
  });

  it("handles missing coordinates gracefully across all sources by returning null", () => {
    const cycle: CycleRecord = {
      ...baseCycle,
      latitude: undefined,
      longitude: undefined,
    };
    expect(resolveCycleCoordinates(cycle, [], [])).toBeNull();
    expect(resolveCycleCoordinates(null)).toBeNull();
    expect(resolveCycleCoordinates(undefined)).toBeNull();
  });

  it("rejects non-finite and out-of-range coordinates", () => {
    const invalidCycle: CycleRecord = {
      ...baseCycle,
      latitude: 195.0, // out of range
      longitude: 70.0,
    };
    expect(resolveCycleCoordinates(invalidCycle)).toBeNull();

    const nanCycle: CycleRecord = {
      ...baseCycle,
      latitude: Number.NaN,
      longitude: 70.0,
    };
    expect(resolveCycleCoordinates(nanCycle)).toBeNull();
  });
});

describe("ResultsWorkspace - CTD Header Coordinate Formatting", () => {
  it("formats positive latitude with N and negative with S", () => {
    expect(formatHeaderCoord(18.236, "lat")).toBe("18.236°N");
    expect(formatHeaderCoord(-12.5, "lat")).toBe("12.500°S");
    expect(formatHeaderCoord(0, "lat")).toBe("0.000°N");
  });

  it("formats positive longitude with E and negative with W", () => {
    expect(formatHeaderCoord(69.731, "lon")).toBe("69.731°E");
    expect(formatHeaderCoord(-45.123, "lon")).toBe("45.123°W");
    expect(formatHeaderCoord(0, "lon")).toBe("0.000°E");
  });

  it("handles null, undefined, NaN, and out-of-bound values with em-dash", () => {
    expect(formatHeaderCoord(null, "lat")).toBe("—");
    expect(formatHeaderCoord(undefined, "lon")).toBe("—");
    expect(formatHeaderCoord(Number.NaN, "lat")).toBe("—");
    expect(formatHeaderCoord(100, "lat")).toBe("—"); // > 90
    expect(formatHeaderCoord(-200, "lon")).toBe("—"); // < -180
  });
});

describe("ResultsWorkspace - CTD Measurement Records Panel Component Rendering", () => {
  const cycle: CycleRecord = {
    cycle_number: 3,
    status: "completed",
    messages_received: 8,
    messages_selected: 8,
    levels_count: 2,
    engineering_data: {},
    rtqc_summary: {},
    ctd_samples: [],
    errors: [],
  };

  const samples: CtdRecord[] = [
    {
      level: 1,
      PRES: 5.4,
      TEMP: 28.123,
      PSAL: 35.456,
      CNDC: 5.892,
      PRES_QC: "1",
      TEMP_QC: "1",
      PSAL_QC: "1",
    },
    {
      level: 2,
      PRES: 10.8,
      TEMP: 27.981,
      PSAL: 35.498,
      CNDC: 5.854,
      PRES_QC: "1",
      TEMP_QC: "1",
      PSAL_QC: "2",
    },
  ];

  it("renders latitude and longitude next to the selected cycle identifier when available", () => {
    const html = renderToString(
      React.createElement(CtdMeasurementRecordsPanel, {
        currentCycle: cycle,
        coordinates: { lat: 18.236, lon: 69.731 },
        samples,
      })
    );

    expect(html).toContain("CTD measurement records");
    expect(html).toContain("— cycle C3");
    expect(html).toContain('data-testid="ctd-cycle-coordinates"');
    expect(html).toContain("Latitude:");
    expect(html).toContain("18.236°N");
    expect(html).toContain("Longitude:");
    expect(html).toContain("69.731°E");
  });

  it("handles missing coordinates gracefully in the header", () => {
    const html = renderToString(
      React.createElement(CtdMeasurementRecordsPanel, {
        currentCycle: cycle,
        coordinates: null,
        samples,
      })
    );

    expect(html).toContain("CTD measurement records");
    expect(html).toContain("— cycle C3");
    expect(html).toContain('data-testid="ctd-cycle-coordinates"');
    expect(html).toContain("Latitude:</span><span class=\"text-slate-400\">—</span>");
    expect(html).toContain("Longitude:</span><span class=\"text-slate-400\">—</span>");
  });

  it("completely removes CNDC column from table header and data cells", () => {
    const html = renderToString(
      React.createElement(CtdMeasurementRecordsPanel, {
        currentCycle: cycle,
        coordinates: { lat: 18.236, lon: 69.731 },
        samples,
      })
    );

    // Assert CNDC (S/m) is completely removed from the header and rows
    expect(html).not.toContain("CNDC");
    expect(html).not.toContain("S/m");
    expect(html).not.toContain("5.892"); // CNDC sample value must not appear in table
    expect(html).not.toContain("5.854"); // CNDC sample value must not appear in table

    // Assert all other columns exist
    expect(html).toContain("Level");
    expect(html).toContain("PRES (dbar)");
    expect(html).toContain("TEMP (°C)");
    expect(html).toContain("PSAL (psu)");
    expect(html).toContain("PRES QC");
    expect(html).toContain("TEMP QC");
    expect(html).toContain("PSAL QC");

    // Assert measurement values appear
    expect(html).toContain("5.40");
    expect(html).toContain("28.123");
    expect(html).toContain("35.456");
  });
});
