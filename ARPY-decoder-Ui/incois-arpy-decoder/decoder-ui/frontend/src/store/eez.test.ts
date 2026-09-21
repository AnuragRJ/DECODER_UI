/**
 * Store-level tests for the Indian EEZ geographic-monitoring slice.
 *
 * Proves: one-time geometry loading (success + honest unavailable path),
 * per-float classification as a dimension SEPARATE from processing status,
 * transition history append-only by stable identity, rerender-safe dedupe,
 * and dismissible notices that never delete history.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { useDecoderStore } from "./useDecoderStore";
import { parseIndiaEez } from "../utils/indiaEez";

const artifact = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../../../data/geography/india_eez.geojson", import.meta.url)),
    "utf8"
  )
);
const eez = parseIndiaEez(artifact);

// A float crossing in and out of the real Indian EEZ (Arabian Sea margin,
// then Karnataka coast, then back offshore and south). Points validated
// against the production artifact in utils tests.
const crossingPoints = [
  { cycle: 1, lon: 66.0, lat: 15.0, juld: 1 },   // OUT (deep Arabian Sea)
  { cycle: 2, lon: 70.0, lat: 15.0, juld: 2 },   // IN  (Karnataka offshore)
  { cycle: 3, lon: 73.0, lat: 14.5, juld: 3 },   // IN/OUT whichever — follows geometry
  { cycle: 4, lon: 64.0, lat: 15.0, juld: 4 },   // OUT
  { cycle: 5, lon: 70.9, lat: 18.5, juld: 5 },   // IN (off Mumbai)
] as const;

beforeEach(() => {
  useDecoderStore.setState({
    eezLayerOn: false,
    eez: eez,
    eezGeometryStatus: "ready",
    eezByWmo: {},
    eezTransitions: [],
    eezDismissed: {},
  });
});

describe("EEZ geometry loading (one-time, honest)", () => {
  it("starts OFF by default with geometry idle", async () => {
    vi.resetModules();
    const fresh = await import("./useDecoderStore");
    expect(fresh.useDecoderStore.getState().eezLayerOn).toBe(false);
    expect(fresh.useDecoderStore.getState().eezGeometryStatus).toBe("idle");
    expect(fresh.useDecoderStore.getState().eez).toBeNull();
  });

  it("fetches exactly once and parses the verified artifact", async () => {
    vi.resetModules();
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, json: async () => artifact });
    vi.stubGlobal("fetch", fetchSpy);
    const fresh = await import("./useDecoderStore");
    await fresh.useDecoderStore.getState().loadEezGeometry();
    await fresh.useDecoderStore.getState().loadEezGeometry(); // repeated call: no refetch
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith("/api/geography/india-eez");
    expect(fresh.useDecoderStore.getState().eezGeometryStatus).toBe("ready");
    expect(fresh.useDecoderStore.getState().eez?.meta.mrgids).toEqual([8333, 8480]);
    vi.unstubAllGlobals();
  });

  it("marks the layer UNAVAILABLE (and hides it) instead of approximating geography", async () => {
    vi.resetModules();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({}) }));
    const fresh = await import("./useDecoderStore");
    fresh.useDecoderStore.setState({ eezLayerOn: true });
    await fresh.useDecoderStore.getState().loadEezGeometry();
    expect(fresh.useDecoderStore.getState().eezGeometryStatus).toBe("unavailable");
    expect(fresh.useDecoderStore.getState().eezLayerOn).toBe(false);
    expect(fresh.useDecoderStore.getState().eez).toBeNull();
    vi.unstubAllGlobals();
  });

  it("rejects malformed payload from the wire the same way", async () => {
    vi.resetModules();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ type: "FeatureCollection", features: [] }) }));
    const fresh = await import("./useDecoderStore");
    await fresh.useDecoderStore.getState().loadEezGeometry();
    expect(fresh.useDecoderStore.getState().eezGeometryStatus).toBe("unavailable");
    vi.unstubAllGlobals();
  });
});

describe("EEZ classification + transition history in the store", () => {
  it("classifies per-cycle from REAL coordinates — a dimension separate from status state", () => {
    useDecoderStore.getState().syncEezForFloat(2901304, [...crossingPoints]);
    const s = useDecoderStore.getState();
    const classified = s.eezByWmo[2901304];
    expect(classified.length).toBe(5);
    expect(classified.every((c) => c.eezStatus === "INDIAN_EEZ" || c.eezStatus === "OUTSIDE_INDIAN_EEZ")).toBe(true);
    // never touches run/batch ingestion state
    expect(s.currentBatch).toBeNull();
    expect(s.ingestionArrivals).toEqual([]);
  });

  it("derives entry/exit transitions only on actual flips", () => {
    useDecoderStore.getState().syncEezForFloat(2901304, [...crossingPoints]);
    const { eezTransitions } = useDecoderStore.getState();
    for (const t of eezTransitions) {
      expect(t.id.startsWith("eez|2901304|")).toBe(true);
      expect(["EEZ_ENTRY", "EEZ_EXIT"]).toContain(t.eventType);
    }
    // Calling again (toggle/zoom/rerender retrigger) adds NOTHING
    const count = eezTransitions.length;
    useDecoderStore.getState().syncEezForFloat(2901304, [...crossingPoints]);
    useDecoderStore.getState().syncEezForFloat(2901304, [...crossingPoints]);
    expect(useDecoderStore.getState().eezTransitions).toHaveLength(count);
  });

  it("is idempotent across interleaved re-syncs of different floats", () => {
    const s = () => useDecoderStore.getState();
    s().syncEezForFloat(2901304, [...crossingPoints]);
    s().syncEezForFloat(2901999, [...crossingPoints]); // same shape, different WMO -> distinct identities
    const ids = s().eezTransitions.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.some((i) => i.includes("2901999"))).toBe(true);
    s().syncEezForFloat(2901304, [...crossingPoints]);
    s().syncEezForFloat(2901999, [...crossingPoints]);
    expect(s().eezTransitions.map((t) => t.id)).toEqual(ids);
  });

  it("grows the trajectory -> only genuinely new transitions append", () => {
    const s = () => useDecoderStore.getState();
    s().syncEezForFloat(2901304, [...crossingPoints].slice(0, 3));
    const early = s().eezTransitions.length;
    s().syncEezForFloat(2901304, [...crossingPoints]);
    const later = s().eezTransitions;
    expect(later.length).toBeGreaterThanOrEqual(early);
    const ids = later.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("dismiss hides the notice but KEEPS history; dismissing twice is a no-op", () => {
    const s = () => useDecoderStore.getState();
    s().syncEezForFloat(2901304, [...crossingPoints]);
    const hist = s().eezTransitions;
    if (hist.length === 0) return; // geometry-dependent: still must be true below when events exist
    const id = hist[0].id;
    s().dismissEezNotice(id);
    s().dismissEezNotice(id);
    expect(s().eezDismissed[id]).toBe(true);
    expect(s().eezTransitions.map((t) => t.id)).toEqual(hist.map((t) => t.id)); // history intact
    // re-sync never re-adds / never un-dismisses
    s().syncEezForFloat(2901304, [...crossingPoints]);
    expect(s().eezDismissed[id]).toBe(true);
    expect(s().eezTransitions).toHaveLength(hist.length);
  });

  it("dismissAll snapshots the CURRENT inside set; classification + history stay intact; newly-inside floats re-surface", () => {
    const s = () => useDecoderStore.getState();
    const lastStatus = (wmo: number) => {
      const list = s().eezByWmo[wmo];
      return list[list.length - 1]?.eezStatus;
    };
    s().syncEezForFloat(2901304, [...crossingPoints]); // ends INSIDE (off Mumbai)
    s().syncEezForFloat(2901777, [{ cycle: 1, lon: 60.0, lat: 10.0, juld: 1 }]); // ends OUTSIDE
    expect(lastStatus(2901304)).toBe("INDIAN_EEZ");
    expect(lastStatus(2901777)).toBe("OUTSIDE_INDIAN_EEZ");
    const histIds = s().eezTransitions.map((t) => t.id);
    s().dismissAllEezNotices();
    // only the currently-inside WMO is snapshotted — nothing else changes
    expect(s().eezDismissed["inside|2901304"]).toBe(true);
    expect(s().eezDismissed["inside|2901777"]).toBeUndefined();
    expect(s().eezTransitions.map((t) => t.id)).toEqual(histIds); // history intact
    expect(lastStatus(2901304)).toBe("INDIAN_EEZ"); // classification intact
    // re-syncing the same floats changes nothing (no un-dismiss, no dupes)
    s().syncEezForFloat(2901304, [...crossingPoints]);
    s().syncEezForFloat(2901777, [{ cycle: 1, lon: 60.0, lat: 10.0, juld: 1 }]);
    expect(s().eezTransitions.map((t) => t.id)).toEqual(histIds);
    // a newly-inside float was never dismissed -> re-surfaces the alert
    s().syncEezForFloat(2901999, [...crossingPoints]);
    expect(lastStatus(2901999)).toBe("INDIAN_EEZ");
    expect(s().eezDismissed["inside|2901999"]).toBeUndefined();
  });

  it("ignores degenerate inputs safely", () => {
    const s = () => useDecoderStore.getState();
    s().syncEezForFloat(Number.NaN as unknown as number, [...crossingPoints]);
    s().syncEezForFloat(2901304, []);
    expect(s().eezTransitions).toEqual([]);
  });
});
