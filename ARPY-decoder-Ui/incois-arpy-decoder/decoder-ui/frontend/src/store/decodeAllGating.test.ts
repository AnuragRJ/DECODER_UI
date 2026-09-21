import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useDecoderStore } from "./useDecoderStore";

/**
 * Store-level contract for the Decode-All idempotency gate.
 * The backend owns the decision; the store must
 *   - surface "already_complete" as a user-visible notice (NOT start any
 *     running indicators),
 *   - clear the notice on any new start (incl. the Re-run All path),
 *   - keep following real batches exactly as before otherwise.
 */

const ALREADY_MSG =
  "Today's fleet decoding is already complete. All currently detected floats have already been processed.";

let fetchSpy: ReturnType<typeof vi.fn>;

const okJson = (body: unknown) =>
  ({ ok: true, status: 200, json: async () => body }) as unknown as Response;

beforeEach(() => {
  fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  useDecoderStore.setState({
    decodeAllAlreadyComplete: null,
    batchRunning: false,
    isRunning: false,
    autoFollowBatch: false,
    currentBatch: null,
    timerInterval: null,
    pollInterval: null,
    timerSeconds: 0,
  });
});

afterEach(() => {
  const s = useDecoderStore.getState();
  if (s.timerInterval) clearInterval(s.timerInterval);
  if (s.pollInterval) clearInterval(s.pollInterval);
  vi.unstubAllGlobals();
});

describe("startDecodeAll — already complete gating", () => {
  it("already_complete: sets the notice and never enters a running state", async () => {
    fetchSpy.mockResolvedValue(
      okJson({ status: "already_complete", message: ALREADY_MSG, batch_id: "batch-42" }),
    );

    await useDecoderStore.getState().startDecodeAll(false);
    const s = useDecoderStore.getState();

    expect(s.decodeAllAlreadyComplete).toEqual({ message: ALREADY_MSG, batchId: "batch-42" });
    expect(s.batchRunning).toBe(false);
    expect(s.isRunning).toBe(false);
    expect(s.timerInterval).toBeNull();
    expect(s.pollInterval).toBeNull();
    // exactly the one decode-all request — no batch sync storm
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe("/api/batch/decode-all");
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body)).toEqual({ force: false });
  });

  it("started: follows the real batch and leaves the notice null", async () => {
    fetchSpy
      .mockResolvedValueOnce(okJson({ status: "started", batch_id: "batch-new" }))
      .mockResolvedValue(okJson({
        batch_id: "batch-new",
        status: "active",
        items: [],
        total_floats: 0,
      }));

    await useDecoderStore.getState().startDecodeAll(false);
    const s = useDecoderStore.getState();

    expect(s.decodeAllAlreadyComplete).toBeNull();
    expect(s.batchRunning).toBe(true);
  });

  it("re-run / any new start clears a previous already-complete notice", async () => {
    useDecoderStore.setState({
      decodeAllAlreadyComplete: { message: ALREADY_MSG, batchId: "batch-42" },
    });
    fetchSpy
      .mockResolvedValueOnce(okJson({ status: "started", batch_id: "batch-rerun" }))
      .mockResolvedValue(okJson({
        batch_id: "batch-rerun",
        status: "active",
        items: [],
        total_floats: 0,
      }));

    await useDecoderStore.getState().startDecodeAll(true);
    const s = useDecoderStore.getState();

    expect(s.decodeAllAlreadyComplete).toBeNull();
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body)).toEqual({ force: true });
  });
});
