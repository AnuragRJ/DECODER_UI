import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useDecoderStore } from "./useDecoderStore";

/**
 * Store-level contract for the interactive Error Investigation view.
 *   - viewRun(..., focusError=true) opens the investigation above the log;
 *   - plain viewRun closes it;
 *   - closeInvestigation keeps the error focus, {unfocusError:true} ("View
 *     Run") returns to the plain run view;
 *   - Investigate on a run with no record opens the "Decoder run not
 *     started" variant instead of fabricating a run.
 */

const RUN_ID = "run-6902892-011aef";

const RUN_JSON = {
  run_id: RUN_ID,
  wmo: 6902892,
  status: "error",
  duration_seconds: 3,
};

const ERROR_EVENT = {
  id: "evt-err-1",
  run_id: RUN_ID,
  stage: "CONFIGURATION",
  operation: "pipeline_error",
  level: "error",
  status: "error",
  message: "boom",
};

const INVESTIGATION_JSON = {
  run_id: RUN_ID,
  wmo: 6902892,
  status: "error",
  category: "MISSING_FLOAT_INFO",
  category_label: "Missing float info config",
  root_cause: "No info JSON for WMO 6902892.",
  recommended_action: "Add the float info file.",
  evidence: [{ source: "errors", detail: "boom" }],
  primary_error: "boom",
  error_count: 2,
  all_errors: ["first", "boom"],
  root_cause_available: true,
  failure_stage: "CONFIGURATION",
  stages: { CONFIGURATION: { status: "error", detail: "boom", active_operation: "" } },
  focus_event: null,
  started_at: "",
  ended_at: null,
  duration_seconds: 3,
  total_files: 0,
  total_cycles: 0,
  outputs_count: 0,
  is_prerun: false,
};

let fetchSpy: ReturnType<typeof vi.fn>;

const okJson = (body: unknown) =>
  ({ ok: true, status: 200, json: async () => body }) as unknown as Response;
const notFound = () => ({ ok: false, status: 404, json: async () => ({}) }) as unknown as Response;

function routeFetch(runBody: unknown, eventsBody: unknown, invBody: unknown) {
  fetchSpy.mockImplementation(async (url: string) => {
    if (String(url).endsWith("/investigation")) return okJson(invBody);
    if (String(url).includes("/events")) return okJson(eventsBody);
    return runBody === null ? notFound() : okJson(runBody);
  });
}

beforeEach(() => {
  fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  useDecoderStore.setState({
    runsCache: {},
    eventsCache: {},
    presets: [],
    activeRunId: null,
    currentRun: null,
    events: [],
    selectedEvent: null,
    logFilter: "all",
    investigationRunId: null,
    investigation: null,
    investigationLoading: false,
    investigationError: null,
    investigationMissing: null,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("investigation open/close", () => {
  it("viewRun with focusError opens the panel and keeps the focused log behind it", async () => {
    routeFetch(RUN_JSON, [ERROR_EVENT], INVESTIGATION_JSON);

    await useDecoderStore.getState().viewRun(RUN_ID, true);
    const s = useDecoderStore.getState();

    expect(s.activeRunId).toBe(RUN_ID);
    expect(s.investigationRunId).toBe(RUN_ID);
    expect(s.investigationLoading).toBe(false);
    expect(s.investigation?.run_id).toBe(RUN_ID);
    expect(s.investigation?.error_count).toBe(2);
    expect(s.investigationMissing).toBeNull();
    // focused log behind the panel is untouched
    expect(s.logFilter).toBe("errors");
    expect(s.selectedEvent?.id).toBe("evt-err-1");
    expect(fetchSpy.mock.calls.some((c) => String(c[0]).endsWith("/investigation"))).toBe(true);
  });

  it("plain viewRun closes the panel and never fetches the investigation", async () => {
    routeFetch(RUN_JSON, [ERROR_EVENT], INVESTIGATION_JSON);
    useDecoderStore.setState({ investigationRunId: RUN_ID });

    await useDecoderStore.getState().viewRun(RUN_ID, false);
    const s = useDecoderStore.getState();

    expect(s.investigationRunId).toBeNull();
    expect(s.investigation).toBeNull();
    expect(s.logFilter).toBe("all");
    expect(fetchSpy.mock.calls.some((c) => String(c[0]).endsWith("/investigation"))).toBe(false);
  });

  it("closeInvestigation returns to the focused log", async () => {
    routeFetch(RUN_JSON, [ERROR_EVENT], INVESTIGATION_JSON);
    await useDecoderStore.getState().viewRun(RUN_ID, true);

    useDecoderStore.getState().closeInvestigation();
    const s = useDecoderStore.getState();

    expect(s.investigationRunId).toBeNull();
    expect(s.investigation).toBeNull();
    expect(s.logFilter).toBe("errors");
    expect(s.selectedEvent?.id).toBe("evt-err-1");
  });

  it("closeInvestigation({unfocusError:true}) returns to the plain run view", async () => {
    const latest = { ...ERROR_EVENT, id: "evt-latest", level: "info", status: "active" };
    routeFetch(RUN_JSON, [ERROR_EVENT, latest], INVESTIGATION_JSON);
    await useDecoderStore.getState().viewRun(RUN_ID, true);

    useDecoderStore.getState().closeInvestigation({ unfocusError: true });
    const s = useDecoderStore.getState();

    expect(s.investigationRunId).toBeNull();
    expect(s.logFilter).toBe("all");
    expect(s.selectedEvent?.id).toBe("evt-latest");
  });
});

describe("investigation on a run with no record", () => {
  it("focus + 404 opens the run-not-started variant with the exact id", async () => {
    routeFetch(null, [], INVESTIGATION_JSON);

    await useDecoderStore.getState().viewRun(RUN_ID, true, null, { fallbackError: "boom" });
    const s = useDecoderStore.getState();

    expect(s.activeRunId).toBeNull();
    expect(s.investigationRunId).toBe(RUN_ID);
    expect(s.investigation).toBeNull();
    expect(s.investigationMissing).toEqual({ runId: RUN_ID, wmo: 6902892, knownError: "boom" });
  });

  it("plain view + 404 keeps the legacy empty view with no panel", async () => {
    routeFetch(null, [], INVESTIGATION_JSON);

    await useDecoderStore.getState().viewRun(RUN_ID, false);
    const s = useDecoderStore.getState();

    expect(s.investigationRunId).toBeNull();
    expect(s.investigationMissing).toBeNull();
  });
});
