import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useDecoderStore } from "./useDecoderStore";

/**
 * Store-level contract for incoming-data ingestion (phase 1):
 *   - fetchIngestion stores status + normalized arrivals verbatim,
 *   - arrivals NEVER trigger any decode/running state,
 *   - ackIngestionArrival posts to /api/ingestion/ack and refreshes.
 */

const STATUS = {
  kind: "local", configured: true, connected: true, detail: "watching",
  mode: "local", test_mode: true, poll_interval_s: 60, scans: 3,
  last_scan_at: "2026-09-15T00:00:00Z", last_scan_records: 12,
  last_new_arrivals: 1, arrivals_total: 2, new_arrivals: 1, last_error: null,
};

const ARRIVAL = {
  fingerprint: "abc", identifier: "1902844", wmo: 1902844, platform: "APEX",
  cycle_number: null, juld: null, latitude: null, longitude: null,
  source_id: "incoming/1902844", source_kind: "local", arrived_at: "2026-09-15T00:00:00Z",
  files: 2, parser_pending: false, ingested_at: "2026-09-15T00:00:01Z",
  state: "new", is_new_wmo: false,
};

let fetchSpy: ReturnType<typeof vi.fn>;
const okJson = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as unknown as Response;

beforeEach(() => {
  fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  useDecoderStore.setState({
    ingestionStatus: null, ingestionArrivals: [], batchRunning: false, isRunning: false,
  });
});

afterEach(() => { vi.unstubAllGlobals(); });

describe("fetchIngestion — normalized arrivals surface as NEW DATA state", () => {
  it("stores status + arrivals without touching any running state", async () => {
    fetchSpy.mockImplementation(async (url: string) =>
      url.includes("/status") ? okJson(STATUS) : okJson([ARRIVAL]));
    await useDecoderStore.getState().fetchIngestion();
    const s = useDecoderStore.getState();
    expect(s.ingestionStatus?.mode).toBe("local");
    expect(s.ingestionStatus?.test_mode).toBe(true);
    expect(s.ingestionArrivals).toHaveLength(1);
    expect(s.ingestionArrivals[0].state).toBe("new");
    expect(s.ingestionArrivals[0].wmo).toBe(1902844);
    // discovery must NEVER auto-start decoding
    expect(s.batchRunning).toBe(false);
    expect(s.isRunning).toBe(false);
    expect(fetchSpy.mock.calls.filter(([u]) => String(u).includes("/api/batch"))).toHaveLength(0);
  });

  it("is resilient to backend errors (keeps prior state shape)", async () => {
    fetchSpy.mockRejectedValue(new Error("offline"));
    await useDecoderStore.getState().fetchIngestion();
    const s = useDecoderStore.getState();
    expect(s.ingestionArrivals).toEqual([]);
    expect(s.batchRunning).toBe(false);
  });
});

describe("ackIngestionArrival", () => {
  it("posts the identifier and refreshes from the backend", async () => {
    fetchSpy.mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).includes("/ack")) return okJson({ cleared: 1 });
      if (String(url).includes("/status")) return okJson({ ...STATUS, new_arrivals: 0 });
      return okJson([{ ...ARRIVAL, state: "seen" }]);
    });
    await useDecoderStore.getState().ackIngestionArrival("1902844");
    const ackCall = fetchSpy.mock.calls.find(([u]) => String(u).includes("/ack"));
    expect(ackCall).toBeTruthy();
    expect(JSON.parse(String(ackCall![1]?.body))).toEqual({ identifier: "1902844" });
    const s = useDecoderStore.getState();
    expect(s.ingestionArrivals[0].state).toBe("seen");
    expect(s.ingestionStatus?.new_arrivals).toBe(0);
  });
});
