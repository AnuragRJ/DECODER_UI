import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FleetStatusPayload } from "../types";
import { useFleetStatusStore } from "./useFleetStatusStore";

// Transport-only test double; deliberately no operational float observations.
const snapshot = { generated_at: "2026-09-21T00:00:00Z", floats: [] } as unknown as FleetStatusPayload;

describe("Float Status transport/cache behavior", () => {
  beforeEach(() => {
    useFleetStatusStore.setState({ payload: snapshot, loading: false, fetchError: null, syncStarting: false });
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it("retains the last payload when fetching fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network unavailable")));
    await useFleetStatusStore.getState().fetchFleetStatus();
    expect(useFleetStatusStore.getState().payload).toBe(snapshot);
    expect(useFleetStatusStore.getState().fetchError).toContain("network unavailable");
    expect(useFleetStatusStore.getState().loading).toBe(false);
  });

  it("times out a hung fetch and permits later refreshes", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url, opts) => new Promise((_resolve, reject) => {
      opts.signal.addEventListener("abort", () => reject(new Error("request aborted")));
    })));
    const task = useFleetStatusStore.getState().fetchFleetStatus();
    expect(useFleetStatusStore.getState().loading).toBe(true);
    await vi.advanceTimersByTimeAsync(15000);
    await task;
    expect(useFleetStatusStore.getState().payload).toBe(snapshot);
    expect(useFleetStatusStore.getState().loading).toBe(false);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => snapshot }));
    await useFleetStatusStore.getState().fetchFleetStatus();
    expect(useFleetStatusStore.getState().fetchError).toBeNull();
  });

  it("does not issue overlapping cache fetches", async () => {
    useFleetStatusStore.setState({ loading: true });
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    await useFleetStatusStore.getState().fetchFleetStatus();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("reports a failed sync trigger without dropping valid data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    expect(await useFleetStatusStore.getState().triggerSync()).toBe("error");
    expect(useFleetStatusStore.getState().payload).toBe(snapshot);
    expect(useFleetStatusStore.getState().fetchError).toContain("503");
    expect(useFleetStatusStore.getState().syncStarting).toBe(false);
  });
});
