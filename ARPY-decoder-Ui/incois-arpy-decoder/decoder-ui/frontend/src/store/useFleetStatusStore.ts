import { create } from "zustand";
import type { FleetStatusPayload } from "../types";

/** Server-data slice for the Float Status page (zustand, mirroring the app
 *  store patterns). Holds ONLY the cached backend payload + fetch state.
 *  View state (search/filter/sort/page/selection) lives in the page
 *  component. Polling hits the cache endpoint (no FTP from the browser). */

interface FleetStatusState {
  payload: FleetStatusPayload | null;
  loading: boolean;
  fetchError: string | null;
  syncStarting: boolean;
  fetchFleetStatus: () => Promise<void>;
  triggerSync: () => Promise<string>;
}

let pollTimer: number | null = null;

export const useFleetStatusStore = create<FleetStatusState>()((set, get) => ({
  payload: null,
  loading: false,
  fetchError: null,
  syncStarting: false,

  fetchFleetStatus: async () => {
    // Skip overlapping refreshes; the cache endpoint is cheap but there is
    // no reason to stack requests while a sync-heavy backend is busy.
    if (get().loading) return;
    set({ loading: true });
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const res = await fetch("/api/fleet-status", { signal: controller.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: FleetStatusPayload = await res.json();
      set({ payload: data, fetchError: null });
    } catch (err) {
      set({
        fetchError:
          err instanceof Error ? err.message : "fleet-status fetch failed",
      });
    } finally {
      clearTimeout(timeout);
      set({ loading: false });
    }
  },

  triggerSync: async () => {
    if (get().syncStarting) return "already-running";
    set({ syncStarting: true });
    try {
      const res = await fetch("/api/fleet-status/sync", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      // Refresh at once so the SYNCING progress shows without waiting for
      // the next poll tick.
      await get().fetchFleetStatus();
      return typeof data?.status === "string" ? data.status : "started";
    } catch (err) {
      set({
        fetchError:
          err instanceof Error ? err.message : "fleet sync trigger failed",
      });
      return "error";
    } finally {
      set({ syncStarting: false });
    }
  },
}));

/** Page-level polling lifecycle (started on mount, stopped on unmount). */
export function startFleetStatusPolling(intervalMs = 60000): void {
  if (typeof window === "undefined") return;
  if (pollTimer !== null) return;
  pollTimer = window.setInterval(() => {
    void useFleetStatusStore.getState().fetchFleetStatus();
  }, intervalMs);
}

export function stopFleetStatusPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}
