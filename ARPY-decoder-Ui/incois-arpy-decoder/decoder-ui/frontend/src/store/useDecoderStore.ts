import { create } from "zustand";
import {
  BatchSummary,
  FloatPreset,
  IngestionArrival,
  IngestionStatus,
  LiveEvent,
  NodeStatus,
  OutputFileInfo,
  RtqcTestInfo,
  RunInvestigation,
  RunSummary,
  StageId,
  StageState,
  TriageItem,
} from "../types";
import {
  classifyTrajectory,
  deriveEezTransitions,
  parseIndiaEez,
  type ClassifiedCycle,
  type EezTransition,
  type IndiaEez,
} from "../utils/indiaEez";

export const STAGE_ORDER: StageId[] = [
  "INPUT_FILES",
  "CONFIGURATION",
  "METADATA",
  "DISCOVERY",
  "WMO_MAPPING",
  "CYCLE_GROUPING",
  "DECODER_SELECTION",
  "PLATFORM_PROCESSING",
  "RAW_PROCESSING",
  "DECODE",
  "PROFILE",
  "RTQC",
  "POST_PROCESSING",
  "CROSS_CYCLE_RTQC",
  "PRODUCT_BUILDING",
  "OUTPUT",
  "DONE",
];

export const createCleanStages = (): Record<StageId, StageState> => {
  return STAGE_ORDER.reduce((acc, id) => {
    acc[id] = {
      id,
      name: id.replace(/_/g, " "),
      status: "pending",
      active_operation: "",
      detail: "",
      updated_at: new Date().toISOString(),
    };
    return acc;
  }, {} as Record<StageId, StageState>);
};

export const createEmptyRun = (preset: FloatPreset | null, wmo: number): RunSummary => ({
  run_id: "",
  wmo: wmo || preset?.wmo || 0,
  float_type: preset?.platform_type || "APEX",
  platform_family: "FLOAT",
  transmission_type: preset?.transmission_type || "ARGOS",
  decoder_id: preset?.decoder_id,
  decoder_version: preset?.decoder_version || "",
  status: "pending",
  start_time: "",
  duration_seconds: 0,
  total_files: preset?.input_file_count || 0,
  total_cycles: 0,
  completed_cycles: 0,
  profile_count: 0,
  missing_profiles: 0,
  active_stage: "INPUT_FILES",
  active_operation: "Ready to decode",
  stages: createCleanStages(),
  cycles: [],
  output_files: [],
  errors: [],
});

interface DecoderStore {
  // View routing
  activeView: "decoder" | "results" | "fleet-status";
  setActiveView: (view: "decoder" | "results" | "fleet-status") => void;
  selectedResultWmo: number | null;
  setSelectedResultWmo: (wmo: number | null) => void;

  // Presets & Selection
  presets: FloatPreset[];
  selectedPreset: FloatPreset | null;
  customWmo: number | null;
  activeRunId: string | null;
  fetchPresets: () => Promise<void>;
  selectPreset: (preset: FloatPreset) => void;
  setCustomWmo: (wmo: number) => void;

  // Run State & Persistence Map
  currentRun: RunSummary | null;
  allRuns: RunSummary[];
  runsCache: Record<string, RunSummary>;
  eventsCache: Record<string, LiveEvent[]>;
  isRunning: boolean;
  isStopping: boolean;
  timerSeconds: number;
  timerInterval: any;
  pollInterval: any;
  startDecode: () => Promise<void>;
  stopDecode: () => Promise<void>;
  resetRun: () => void;
  syncRun: (runId: string) => Promise<void>;
  viewRun: (
    runId: string,
    focusError?: boolean,
    targetEventId?: string | null,
    opts?: { fallbackError?: string | null; viaEmail?: boolean },
  ) => Promise<void>;
  // Visible feedback for email deep links: set when a linked run/event could
  // not be resolved, cleared when a deep link lands successfully.
  deepLinkNotice: string | null;
  setDeepLinkNotice: (msg: string | null) => void;
  // Error Investigation (interactive Error Detail): renders above the Decoder
  // Log in the center column. Opened by any viewRun(..., focusError=true).
  investigationRunId: string | null;
  investigation: RunInvestigation | null;
  investigationLoading: boolean;
  investigationError: string | null;
  // Set when an Investigate entry targets a run with no record at all: the
  // "Decoder run not started" variant (never a fabricated run).
  investigationMissing: { runId: string; wmo: number; knownError: string } | null;
  openInvestigation: (runId: string) => Promise<void>;
  // keepFocus=true returns to the focused log; unfocusError=true returns to
  // the plain run view (clears the error focus).
  closeInvestigation: (opts?: { unfocusError?: boolean }) => void;
  fetchAllRuns: () => Promise<void>;

  // Batch State (Decode All Today's Floats)
  batchRunning: boolean;
  autoFollowBatch: boolean;
  setAutoFollowBatch: (val: boolean) => void;
  currentBatch: BatchSummary | null;
  allBatches: BatchSummary[];
  /** Start a fleet batch. force=true = explicit RE-RUN ALL (bypasses today's
   *  cached successes and decodes every float again in a fresh batch).
   *  When every eligible float is already processed today the backend
   *  creates NO batch and answers "already_complete": this is surfaced as
   *  decodeAllAlreadyComplete so the UI can offer View Results / Re-run All. */
  startDecodeAll: (force?: boolean) => Promise<void>;
  /** Set when the backend reports Decode-All as already complete today. */
  decodeAllAlreadyComplete: { message: string; batchId: string | null } | null;
  clearDecodeAllAlreadyComplete: () => void;
  fetchAllBatches: () => Promise<void>;
  syncBatch: (batchId: string) => Promise<void>;
  selectBatchFloat: (wmo: number, runId?: string | null) => Promise<void>;
  // Agentic triage of the active batch's failed/stopped floats (fetched on demand)
  triageResults: TriageItem[] | null;
  fetchTriage: (batchId: string) => Promise<void>;

  // Incoming-data ingestion: normalized arrival records from the active
  // DataSource (local/development source or the future INCOIS FTP feed).
  // Purely observational — ingestion NEVER starts decoding; the explicit
  // Decode workflow stays the user's choice.
  ingestionStatus: IngestionStatus | null;
  ingestionArrivals: IngestionArrival[];
  fetchIngestion: () => Promise<void>;
  ackIngestionArrival: (identifier: string) => Promise<void>;

  // -------------------------------------------------------------------
  // INDIAN EEZ geographic monitoring — a SEPARATE dimension from decode
  // processing status. Nothing here reads, writes, merges or alters
  // SUCCESS/FAILED/NEW DATA or any run state. All values derive from the
  // ONE verified external reference geometry served at
  // /api/geography/india-eez (Marine Regions World EEZ v12, 2023-10-25 —
  // MRGID 8480 + 8333; external reference, NOT official INCOIS).
  // -------------------------------------------------------------------
  /** Visualization-only map toggle. OFF by default; toggling never
   *  recomputes, destroys or re-fires anything. */
  eezLayerOn: boolean;
  setEezLayerOn: (on: boolean) => void;
  /** One-time geometry lifecycle. "unavailable" hides the layer affordance
   *  (honest failure — never approximate geography). */
  eezGeometryStatus: "idle" | "loading" | "ready" | "unavailable";
  /** Parsed + validated reference geometry (module-level singleton). */
  eez: IndiaEez | null;
  /** Idempotent one-time load; safe to call from any mount path. */
  loadEezGeometry: () => Promise<void>;
  /** Per-float per-cycle classification cache (memoized upstream). */
  eezByWmo: Record<number, ClassifiedCycle[]>;
  /** All derived EEZ transitions — session HISTORY, append-only by stable
   *  identity; dismissal never removes entries here. */
  eezTransitions: EezTransition[];
  /** Notice ids the operator dismissed (shown-as-read state only). */
  eezDismissed: Record<string, true>;
  /** Classify a float's real decoded cycle positions and derive any new
   *  EEZ entry/exit transitions. Idempotent across every caller
   *  (toggle/zoom/pan/resize/Full Screen/rerender can never duplicate an
   *  event): (wmo, fromCycle, toCycle, eventType) first-occurrence wins. */
  syncEezForFloat: (wmo: number, points: { cycle: number; lat: number; lon: number; juld?: number | null }[]) => void;
  dismissEezNotice: (id: string) => void;
  /** Dismiss the ONE combined current-state EEZ alert: marks every WMO
   *  currently inside the EEZ (`inside|<wmo>`) dismissed in a single atomic
   *  update. Classification + transition history are untouched; only a NEWLY
   *  inside WMO (never dismissed) arriving later can re-surface the alert.
   *  Collapse/expand, toggle, selection, zoom/pan/resize and rerenders never
   *  un-dismiss. */
  dismissAllEezNotices: () => void;

  // Real-time Events
  events: LiveEvent[];
  wsConnected: boolean;
  initWebSocket: () => void;
  addEvent: (evt: LiveEvent) => void;
  updateRunSummary: (run: RunSummary) => void;
  updateBatchSummary: (batch: BatchSummary) => void;

  // UI state & Modals
  selectedEvent: LiveEvent | null;
  setSelectedEvent: (evt: LiveEvent | null) => void;

  selectedRtqcTest: RtqcTestInfo | null;
  setSelectedRtqcTest: (test: RtqcTestInfo | null) => void;
  isRtqcModalOpen: boolean;
  setRtqcModalOpen: (open: boolean) => void;

  selectedCycle: number | null;
  setSelectedCycle: (cycle: number | null) => void;
  isCycleModalOpen: boolean;
  setCycleModalOpen: (open: boolean) => void;

  selectedOutputFile: OutputFileInfo | null;
  setSelectedOutputFile: (file: OutputFileInfo | null) => void;
  isOutputModalOpen: boolean;
  setOutputModalOpen: (open: boolean) => void;

  isFlowchartModalOpen: boolean;
  setFlowchartModalOpen: (open: boolean) => void;

  isBatchSummaryModalOpen: boolean;
  setBatchSummaryModalOpen: (open: boolean) => void;

  isRunHistoryModalOpen: boolean;
  setRunHistoryModalOpen: (open: boolean) => void;

  // Center Log controls
  logFilter: "all" | "rtqc" | "errors" | "outputs";
  setLogFilter: (filter: "all" | "rtqc" | "errors" | "outputs") => void;
  logSearch: string;
  setLogSearch: (search: string) => void;
  autoScroll: boolean;
  setAutoScroll: (val: boolean) => void;
  clearLogs: () => void;
  clearBatchSummary: () => void;
  loadBatchSummary: (batch: BatchSummary) => void;
  clearRunSummary: () => void;
}

// Module-level connection singletons
let globalSocket: WebSocket | null = null;
let globalEventSource: EventSource | null = null;
let globalReconnectTimeout: any = null;

// ---------------------------------------------------------------------------
// EEZ module-level singletons: the verified geometry is fetched/parsed ONCE
// per page session (one-time geometry load) and classification results are
// memoized so pan/zoom/toggle/remount never recomputes them.
// ---------------------------------------------------------------------------
let eezLoadPromise: Promise<IndiaEez | null> | null = null;
let eezSingleton: IndiaEez | null = null;
const eezClassifyMemo = new Map<string, ClassifiedCycle[]>();
const eezTransitionMemo = new Map<string, EezTransition[]>();

function eezFingerprint(points: { cycle: number; lat: number; lon: number; juld?: number | null }[]): string {
  return points
    .map((p) => `${p.cycle}:${p.lat}:${p.lon}:${p.juld ?? ""}`)
    .join("|");
}

export const useDecoderStore = create<DecoderStore>((set, get) => ({
  activeView: "decoder",
  setActiveView: (view) => set({ activeView: view }),
  selectedResultWmo: null,
  setSelectedResultWmo: (wmo) => set({ selectedResultWmo: wmo }),

  presets: [],
  selectedPreset: null,
  customWmo: null,
  activeRunId: null,
  currentRun: null,
  ingestionStatus: null,
  ingestionArrivals: [],
  allRuns: [],
  runsCache: {},
  eventsCache: {},
  isRunning: false,
  isStopping: false,
  timerSeconds: 0,
  timerInterval: null,
  pollInterval: null,
  events: [],
  wsConnected: false,

  batchRunning: false,
  autoFollowBatch: true,
  currentBatch: null,
  allBatches: [],
  decodeAllAlreadyComplete: null,
  clearDecodeAllAlreadyComplete: () => set({ decodeAllAlreadyComplete: null }),

  // -----------------------------------------------------------------
  // Indian EEZ geographic monitoring (separate dimension — see above)
  // -----------------------------------------------------------------
  eezLayerOn: false,
  setEezLayerOn: (on) => set({ eezLayerOn: on }),
  eezGeometryStatus: "idle",
  eez: null,
  loadEezGeometry: async () => {
    if (eezSingleton) {
      if (get().eezGeometryStatus !== "ready") set({ eez: eezSingleton, eezGeometryStatus: "ready" });
      return;
    }
    const current = get().eezGeometryStatus;
    if (current === "loading" || current === "ready" || current === "unavailable") return;
    set({ eezGeometryStatus: "loading" });
    try {
      if (!eezLoadPromise) {
        eezLoadPromise = (async () => {
          const res = await fetch("/api/geography/india-eez");
          if (!res.ok) return null;
          const payload = await res.json();
          return parseIndiaEez(payload); // strict validation; any defect -> unavailable
        })();
      }
      const parsed = await eezLoadPromise;
      if (!parsed) throw new Error("EEZ geometry unavailable");
      eezSingleton = parsed;
      set({ eez: parsed, eezGeometryStatus: "ready" });
    } catch {
      eezLoadPromise = null;
      set({ eez: null, eezGeometryStatus: "unavailable", eezLayerOn: false });
    }
  },
  eezByWmo: {},
  eezTransitions: [],
  eezDismissed: {},
  syncEezForFloat: (wmo, points) => {
    const state = get();
    const eez = state.eez ?? eezSingleton;
    if (!eez || !Number.isFinite(wmo)) return;
    const fp = eezFingerprint(points);
    const classifyKey = `${wmo}|${fp}`;
    let classified = eezClassifyMemo.get(classifyKey);
    if (!classified) {
      classified = classifyTrajectory(eez.geometry, points);
      eezClassifyMemo.set(classifyKey, classified);
    }
    let transitions = eezTransitionMemo.get(classifyKey);
    if (!transitions) {
      transitions = deriveEezTransitions(wmo, classified);
      eezTransitionMemo.set(classifyKey, transitions);
    }
    // Classification refresh: replace per-float entry when it changed
    if (state.eezByWmo[wmo] !== classified) {
      set({ eezByWmo: { ...get().eezByWmo, [wmo]: classified } });
    }
    // Append-only history by STABLE identity — first occurrence wins,
    // so any UI retrigger can never duplicate or re-fire an event.
    if (transitions.length > 0) {
      const have = new Set(get().eezTransitions.map((t) => t.id));
      const fresh = transitions.filter((t) => !have.has(t.id));
      if (fresh.length > 0) {
        set({ eezTransitions: [...get().eezTransitions, ...fresh] });
      }
    }
  },
  dismissEezNotice: (id) =>
    set({ eezDismissed: { ...get().eezDismissed, [id]: true } }),
  dismissAllEezNotices: () => {
    // Current-state alert dismissal: snapshot the WMOs whose LATEST valid
    // classified position is inside the EEZ right now. Transition history
    // (eezTransitions) and classification (eezByWmo) are untouched.
    const byWmo = get().eezByWmo;
    const dismissed = { ...get().eezDismissed };
    let changed = false;
    for (const [key, classified] of Object.entries(byWmo)) {
      if (!classified || classified.length === 0) continue;
      if (classified[classified.length - 1].eezStatus !== "INDIAN_EEZ") continue;
      const k = `inside|${key}`;
      if (!dismissed[k]) {
        dismissed[k] = true;
        changed = true;
      }
    }
    if (changed) set({ eezDismissed: dismissed });
  },

  selectedEvent: null,
  selectedRtqcTest: null,
  isRtqcModalOpen: false,
  selectedCycle: null,
  isCycleModalOpen: false,
  selectedOutputFile: null,
  isOutputModalOpen: false,
  isFlowchartModalOpen: false,
  isBatchSummaryModalOpen: false,
  isRunHistoryModalOpen: false,
  logFilter: "all",
  logSearch: "",
  autoScroll: true,
  deepLinkNotice: null,
  setDeepLinkNotice: (msg) => set({ deepLinkNotice: msg }),
  investigationRunId: null,
  investigation: null,
  investigationLoading: false,
  investigationError: null,
  investigationMissing: null,
  openInvestigation: async (runId: string) => {
    set({
      investigationRunId: runId,
      investigation: null,
      investigationError: null,
      investigationMissing: null,
      investigationLoading: true,
    });
    try {
      const res = await fetch(`/api/runs/${runId}/investigation`);
      if (get().investigationRunId !== runId) return; // superseded
      if (!res.ok) {
        set({
          investigationLoading: false,
          investigationError:
            res.status === 404
              ? `Run “${runId}” is no longer available in this workstation's history, so its investigation could not be loaded.`
              : `Could not load the error investigation (HTTP ${res.status}).`,
        });
        return;
      }
      set({ investigation: await res.json(), investigationLoading: false });
    } catch (err) {
      if (get().investigationRunId !== runId) return;
      console.error("Failed to load error investigation:", err);
      set({
        investigationLoading: false,
        investigationError: "Could not load the error investigation — the service did not respond.",
      });
    }
  },
  closeInvestigation: (opts?: { unfocusError?: boolean }) => {
    const cleared = {
      investigationRunId: null,
      investigation: null,
      investigationLoading: false,
      investigationError: null,
      investigationMissing: null,
    };
    if (opts?.unfocusError) {
      // "View Run": back to the plain run view — latest event, unfiltered log.
      const events = get().events;
      set({
        ...cleared,
        logFilter: "all",
        selectedEvent: events.length > 0 ? events[events.length - 1] : get().selectedEvent,
      });
    } else {
      set(cleared);
    }
  },

  triageResults: null,
  fetchTriage: async (batchId: string) => {
    try {
      const res = await fetch(`/api/batch/${batchId}/triage`);
      if (!res.ok) return;
      const data = await res.json();
      set({ triageResults: data.items || [] });
    } catch (err) {
      console.error("Failed to fetch batch triage:", err);
    }
  },

  fetchPresets: async () => {
    try {
      const res = await fetch("/api/presets");
      if (res.ok) {
        const data: FloatPreset[] = await res.json();
        const defaultPreset = data.find((p) => p.is_default) || data[0] || null;

        // Startup restore policy (fresh-workspace cleanliness):
        //   * Only a GENUINELY ACTIVE run/batch is promoted into the live
        //     console — that state means a backend execution is in progress
        //     right now (e.g. the browser was refreshed mid-decode), so
        //     reattaching is the correct recovery.
        //   * Completed/error/stopped records are HISTORY. They remain fully
        //     available via HISTORY / VIEW RESULTS, but are never promoted
        //     into currentRun/currentBatch on startup, so a fresh download or
        //     a new day opens on a clean STANDBY console with an empty log.
        let initialRun: RunSummary | null = null;
        let runsList: RunSummary[] = [];
        const initialRunsCache: Record<string, RunSummary> = {};
        const initialEventsCache: Record<string, LiveEvent[]> = {};

        try {
          const runsRes = await fetch("/api/runs");
          if (runsRes.ok) {
            runsList = await runsRes.json();
            for (const r of runsList) {
              initialRunsCache[r.run_id] = r;
            }
            if (runsList && runsList.length > 0 && runsList[0].status === "active") {
              initialRun = runsList[0];
              // Fetch events for the live run we are reattaching to
              const evRes = await fetch(`/api/runs/${initialRun.run_id}/events?limit=5000`);
              if (evRes.ok) {
                const evData: LiveEvent[] = await evRes.json();
                initialEventsCache[initialRun.run_id] = evData;
              }
            }
          }
        } catch {
          // ignore
        }

        // Fetch latest batch; only a live (active) batch is reattached.
        let latestBatch: BatchSummary | null = null;
        let batchesList: BatchSummary[] = [];
        try {
          const batchRes = await fetch("/api/batches");
          if (batchRes.ok) {
            batchesList = await batchRes.json();
            if (batchesList && batchesList.length > 0) {
              const firstBatch = batchesList[0];
              const isCleared = typeof window !== "undefined" && window.sessionStorage?.getItem("argo_summary_cleared") === "true";
              if (firstBatch.status === "active" && !isCleared) {
                latestBatch = firstBatch;
              }
            }
          }
        } catch {
          // ignore
        }

        const activePreset = initialRun
          ? data.find((p) => p.wmo === initialRun?.wmo) || defaultPreset
          : defaultPreset;

        set({
          presets: data,
          allRuns: runsList,
          runsCache: initialRunsCache,
          eventsCache: initialEventsCache,
          allBatches: batchesList,
          currentBatch: latestBatch,
          selectedPreset: activePreset,
          customWmo: initialRun?.wmo || defaultPreset?.wmo || null,
          activeRunId: initialRun?.run_id || null,
          events: (initialRun && initialEventsCache[initialRun.run_id]) || [],
          currentRun: initialRun || createEmptyRun(defaultPreset, defaultPreset?.wmo || 0),
        });
      }
    } catch (err) {
      console.error("Failed to fetch presets:", err);
    }
  },

  // Incoming-data ingestion: fetch status + normalized arrivals from the
  // active DataSource. Read-only observability; nothing here may trigger
  // decoding (spec: arrivals surface as NEW DATA, user chooses Decode).
  fetchIngestion: async () => {
    try {
      const [stRes, arRes] = await Promise.all([
        fetch("/api/ingestion/status"),
        fetch("/api/ingestion/arrivals"),
      ]);
      const st = stRes.ok ? ((await stRes.json()) as IngestionStatus) : null;
      const ar = arRes.ok ? ((await arRes.json()) as IngestionArrival[]) : [];
      set({ ingestionStatus: st, ingestionArrivals: ar });
    } catch (err) {
      console.error("Failed to fetch ingestion status:", err);
    }
  },

  ackIngestionArrival: async (identifier: string) => {
    try {
      await fetch("/api/ingestion/ack", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier }),
      });
    } catch (err) {
      console.error("Failed to acknowledge arrival:", err);
    } finally {
      await get().fetchIngestion();
    }
  },

  fetchAllRuns: async () => {
    try {
      const res = await fetch("/api/runs");
      if (res.ok) {
        const data: RunSummary[] = await res.json();
        set((state) => {
          const updatedCache = { ...state.runsCache };
          for (const r of data) {
            updatedCache[r.run_id] = r;
          }
          return { allRuns: data, runsCache: updatedCache };
        });
      }
    } catch (e) {
      console.error("Failed to fetch runs:", e);
    }
  },

  fetchAllBatches: async () => {
    try {
      const res = await fetch("/api/batches");
      if (res.ok) {
        const data: BatchSummary[] = await res.json();
        set({ allBatches: data });
      }
    } catch (e) {
      console.error("Failed to fetch batches:", e);
    }
  },

  selectPreset: (preset) => {
    const { timerInterval, pollInterval } = get();
    if (timerInterval) clearInterval(timerInterval);
    if (pollInterval) clearInterval(pollInterval);

    set({
      selectedPreset: preset,
      customWmo: preset.wmo,
      activeRunId: null,
      autoFollowBatch: false,
      isRunning: false,
      timerSeconds: 0,
      timerInterval: null,
      pollInterval: null,
      events: [],
      selectedEvent: null,
      selectedRtqcTest: null,
      selectedCycle: null,
      selectedOutputFile: null,
      currentRun: createEmptyRun(preset, preset.wmo),
    });
  },

  setCustomWmo: (wmo) => {
    const { selectedPreset, timerInterval, pollInterval } = get();
    if (timerInterval) clearInterval(timerInterval);
    if (pollInterval) clearInterval(pollInterval);

    set({
      customWmo: wmo,
      activeRunId: null,
      autoFollowBatch: false,
      isRunning: false,
      timerSeconds: 0,
      timerInterval: null,
      pollInterval: null,
      events: [],
      selectedEvent: null,
      selectedRtqcTest: null,
      selectedCycle: null,
      selectedOutputFile: null,
      currentRun: createEmptyRun(selectedPreset, wmo),
    });
  },

  setAutoFollowBatch: (val: boolean) => {
    set({ autoFollowBatch: val });
  },

  initWebSocket: () => {
    if (
      globalSocket &&
      (globalSocket.readyState === WebSocket.OPEN ||
        globalSocket.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    if (globalReconnectTimeout) {
      clearTimeout(globalReconnectTimeout);
      globalReconnectTimeout = null;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws`;

    const startSseFallback = () => {
      if (globalEventSource) return;
      try {
        globalEventSource = new EventSource("/api/sse");
        globalEventSource.onopen = () => {
          set({ wsConnected: true });
        };
        globalEventSource.onmessage = (e) => {
          try {
            const msg = JSON.parse(e.data);
            if (msg.type === "event") {
              get().addEvent(msg.data);
            } else if (msg.type === "run_update") {
              get().updateRunSummary(msg.data);
            } else if (msg.type === "batch_update") {
              get().updateBatchSummary(msg.data);
            }
          } catch (err) {
            console.error("SSE parse error:", err);
          }
        };
        globalEventSource.onerror = () => {
          set({ wsConnected: false });
        };
      } catch (err) {
        console.error("SSE init error:", err);
      }
    };

    const connectWs = () => {
      try {
        if (
          globalSocket &&
          (globalSocket.readyState === WebSocket.OPEN ||
            globalSocket.readyState === WebSocket.CONNECTING)
        ) {
          return;
        }

        const socket = new WebSocket(wsUrl);
        globalSocket = socket;

        socket.onopen = () => {
          set({ wsConnected: true });
          if (globalEventSource) {
            globalEventSource.close();
            globalEventSource = null;
          }
        };

        socket.onmessage = (e) => {
          try {
            const msg = JSON.parse(e.data);
            if (msg.type === "event") {
              get().addEvent(msg.data);
            } else if (msg.type === "run_update") {
              get().updateRunSummary(msg.data);
            } else if (msg.type === "batch_update") {
              get().updateBatchSummary(msg.data);
            }
          } catch (err) {
            console.error("WS parse error:", err);
          }
        };

        socket.onclose = () => {
          set({ wsConnected: false });
          globalSocket = null;
          startSseFallback();
          globalReconnectTimeout = setTimeout(connectWs, 3000);
        };

        socket.onerror = () => {
          set({ wsConnected: false });
          globalSocket = null;
          startSseFallback();
        };
      } catch (e) {
        set({ wsConnected: false });
        globalSocket = null;
        startSseFallback();
        globalReconnectTimeout = setTimeout(connectWs, 3000);
      }
    };

    connectWs();
  },

  syncRun: async (runId: string) => {
    try {
      const [runRes, eventsRes] = await Promise.all([
        fetch(`/api/runs/${runId}`),
        fetch(`/api/runs/${runId}/events?limit=5000`),
      ]);

      if (runRes.ok) {
        const runData: RunSummary = await runRes.json();
        get().updateRunSummary(runData);
      }

      if (eventsRes.ok) {
        const eventsData: LiveEvent[] = await eventsRes.json();
        set((state) => {
          const newEventsCache = { ...state.eventsCache, [runId]: eventsData };
          if (state.activeRunId === runId) {
            return {
              eventsCache: newEventsCache,
              events: eventsData,
            };
          }
          return { eventsCache: newEventsCache };
        });
      }
    } catch {
      // Ignore sync network errors
    }
  },

  syncBatch: async (batchId: string) => {
    try {
      const res = await fetch(`/api/batch/${batchId}`);
      if (res.ok) {
        const batchData: BatchSummary = await res.json();
        get().updateBatchSummary(batchData);
      }
    } catch {
      // Ignore batch sync error
    }
  },

  viewRun: async (
    runId: string,
    focusError: boolean = false,
    targetEventId?: string | null,
    opts?: { fallbackError?: string | null; viaEmail?: boolean },
  ) => {
    try {
      let runData = get().runsCache[runId];
      let eventsData = get().eventsCache[runId];

      if (!runData || !eventsData || eventsData.length === 0) {
        const [runRes, eventsRes] = await Promise.all([
          fetch(`/api/runs/${runId}`),
          fetch(`/api/runs/${runId}/events?limit=5000`),
        ]);

        if (runRes.ok) {
          runData = await runRes.json();
        }
        if (eventsRes.ok) {
          eventsData = await eventsRes.json();
        }
      }

      if (!runData) {
        // No run record exists for this id: NEVER leave a stale, unrelated
        // run on screen — it reads as this float's failure. Reset to an
        // empty context and explain with the known error when the caller
        // supplied one (e.g. a pre-run failure from the Results table).
        const wmoGuess = /^run-(\d+)-/.exec(runId);
        const wmoNum = wmoGuess ? Number(wmoGuess[1]) : 0;
        const empty = createEmptyRun(null, wmoNum);
        empty.run_id = runId;
        const emptyPreset = get().presets.find((p) => p.wmo === wmoNum) || null;
        const knownError = (opts?.fallbackError ?? "").trim();
        set({
          activeView: "decoder",
          activeRunId: null,
          currentRun: empty,
          events: [],
          selectedEvent: null,
          selectedPreset: emptyPreset,
          customWmo: wmoNum,
          isRunning: false,
          timerSeconds: 0,
          logFilter: "all",
          isBatchSummaryModalOpen: false,
          isRunHistoryModalOpen: false,
          deepLinkNotice: knownError
            ? `Run “${runId}” has no decoder log in this workstation's history — the failure happened before a run record was created. Reported error: ${knownError}`
            : opts?.viaEmail
              ? `The linked run “${runId}” is not available in this workstation's history, so the email deep link could not open it. ` +
                `Its run data may predate persistent run storage or was cleaned up.`
              : `Run “${runId}” is not available in this workstation's history. ` +
                `Its run data may predate persistent run storage or was cleaned up.`,
          // Investigate intent on a run with no record: the "Decoder run not
          // started" variant (exact run id, no fabricated log/timeline).
          investigationRunId: focusError ? runId : null,
          investigation: null,
          investigationLoading: false,
          investigationError: null,
          investigationMissing: focusError ? { runId, wmo: wmoNum, knownError } : null,
        });
        return;
      }
      eventsData = eventsData || [];

      // Match preset
      const preset = get().presets.find((p) => p.wmo === runData.wmo) || null;

      // Find target event if specified or focus error
      let selectedEvt: LiveEvent | null = null;
      const targetFound = targetEventId ? eventsData.some((e) => e.id === targetEventId) : false;
      if (targetEventId) {
        selectedEvt = eventsData.find((e) => e.id === targetEventId) || null;
      }
      // Error focus prefers a real error event; when the run recorded none
      // (historical runs predate bridged error events), the latest event is
      // shown instead and LABELED as such — never presented as the error.
      const errorEvt = focusError
        ? eventsData.find((e) => e.level === "error" || e.status === "error") || null
        : null;
      if (!selectedEvt && focusError) {
        selectedEvt = errorEvt || (eventsData.length > 0 ? eventsData[eventsData.length - 1] : null);
      }
      if (!selectedEvt && eventsData.length > 0) {
        selectedEvt = eventsData[eventsData.length - 1];
      }
      // If the exact event from the deep link is gone, say so instead of
      // silently focusing a different event.
      const eventNotice =
        targetEventId && !targetFound
          ? selectedEvt
            ? `Event “${targetEventId}” was not found in run “${runId}” — the run's error event is shown instead.`
            : `Event “${targetEventId}” was not found in run “${runId}” and this run has no log events to display.`
          : null;
      const focusNotice =
        !targetEventId && focusError && !errorEvt && selectedEvt
          ? `Latest event shown — no error event was recorded for run “${runId}”.`
          : null;

      set((state) => ({
        activeView: "decoder",
        activeRunId: runId,
        autoFollowBatch: false,
        currentRun: runData,
        events: eventsData,
        selectedPreset: preset,
        customWmo: runData.wmo,
        isRunning: runData.status === "active",
        timerSeconds: runData.duration_seconds || 0,
        selectedEvent: selectedEvt,
        logFilter: focusError ? "errors" : "all",
        isBatchSummaryModalOpen: false,
        isRunHistoryModalOpen: false,
        deepLinkNotice: eventNotice ?? focusNotice,
        runsCache: { ...state.runsCache, [runId]: runData },
        eventsCache: { ...state.eventsCache, [runId]: eventsData },
        investigationMissing: null,
        investigationError: null,
      }));
      // Investigate entries open the interactive Error Detail above the log;
      // plain views close it. One rule, every entry point.
      if (focusError) {
        await get().openInvestigation(runId);
      } else {
        get().closeInvestigation();
      }
    } catch (err) {
      console.error("Failed to view historical run:", err);
    }
  },

  selectBatchFloat: async (wmo: number, runId?: string | null) => {
    const { presets, runsCache, eventsCache, currentBatch } = get();
    const preset = presets.find((p) => p.wmo === wmo) || null;

    // If this is the currently running float in the active batch, enable auto-following
    const isCurrentlyRunning = currentBatch?.running_run_id && currentBatch.running_run_id === runId;

    if (runId) {
      let runData = runsCache[runId];
      let eventsData = eventsCache[runId];

      if (!runData || !eventsData || eventsData.length === 0) {
        try {
          const [runRes, eventsRes] = await Promise.all([
            fetch(`/api/runs/${runId}`),
            fetch(`/api/runs/${runId}/events?limit=5000`),
          ]);
          if (runRes.ok) {
            runData = await runRes.json();
          }
          if (eventsRes.ok) {
            eventsData = await eventsRes.json();
          }
        } catch (err) {
          console.error("Error loading batch float run:", err);
        }
      }

      if (!runData) {
        runData = createEmptyRun(preset, wmo);
        runData.run_id = runId;
      }
      if (!eventsData) {
        eventsData = [];
      }

      set((state) => ({
        activeRunId: runId,
        autoFollowBatch: isCurrentlyRunning ? true : false,
        selectedPreset: preset,
        customWmo: wmo,
        currentRun: runData,
        events: eventsData,
        isRunning: runData.status === "active",
        timerSeconds: runData.duration_seconds || 0,
        deepLinkNotice: null,
        investigationRunId: null,
        investigation: null,
        investigationLoading: false,
        investigationError: null,
        investigationMissing: null,
        selectedEvent: eventsData.length > 0 ? eventsData[eventsData.length - 1] : null,
        selectedRtqcTest: null,
        selectedCycle: null,
        selectedOutputFile: null,
        runsCache: { ...state.runsCache, [runId]: runData },
        eventsCache: { ...state.eventsCache, [runId]: eventsData },
      }));
    } else {
      // Pending float in batch queue
      const freshRun = createEmptyRun(preset, wmo);
      freshRun.active_operation = "Awaiting execution in batch queue...";
      set({
        activeRunId: null,
        autoFollowBatch: false,
        deepLinkNotice: null,
        investigationRunId: null,
        investigation: null,
        investigationLoading: false,
        investigationError: null,
        investigationMissing: null,
        selectedPreset: preset,
        customWmo: wmo,
        currentRun: freshRun,
        events: [],
        isRunning: false,
        timerSeconds: 0,
        selectedEvent: null,
        selectedRtqcTest: null,
        selectedCycle: null,
        selectedOutputFile: null,
      });
    }
  },

  addEvent: (evt) => {
    const runId = evt.run_id;
    if (!runId) return;

    set((state) => {
      // 1. Ingest event into eventsCache for this specific run_id
      const existingEvents = state.eventsCache[runId] || [];
      if (evt.id && existingEvents.some((e) => e.id === evt.id)) {
        // Event already ingested into eventsCache — typically because the
        // poll's /events fetch won the race against this WS delivery (the
        // server appends the event to the run's list before broadcasting it,
        // so a poll snapshot can already contain it). Do not duplicate the
        // event card, but a terminal event must still apply its run-state
        // transition, otherwise the UI misses the pipeline_end flip and
        // keeps showing "decoding" until the next poll/summary push.
        const isTerminalEvt =
          (evt.stage === "DONE" &&
            (evt.status === "completed" || evt.status === "stopped" || evt.status === "cancelled")) ||
          evt.status === "stopped" ||
          evt.status === "cancelled";
        const cached = state.runsCache[runId];
        if (isTerminalEvt && cached) {
          const alreadyTerminal =
            ["completed", "error", "stopped", "cancelled"].includes(cached.status);
          if (!alreadyTerminal) {
            const run: RunSummary = {
              ...cached,
              status: evt.status === "completed" ? "completed" : "stopped",
              active_operation:
                evt.status === "completed" ? "Pipeline completed successfully" : "Stopped by user",
            };
            const newRunsCache = { ...state.runsCache, [runId]: run };
            const isActive = state.activeRunId === runId;
            const shouldStopTimers = isActive && !state.batchRunning;
            if (shouldStopTimers) {
              if (state.timerInterval) clearInterval(state.timerInterval);
              if (state.pollInterval) clearInterval(state.pollInterval);
            }
            return {
              runsCache: newRunsCache,
              ...(isActive ? { currentRun: run, isRunning: run.status === "active" } : {}),
              isStopping: false,
              timerInterval: shouldStopTimers ? null : state.timerInterval,
              pollInterval: shouldStopTimers ? null : state.pollInterval,
            };
          }
        }
        return state;
      }
      const updatedEvents = [...existingEvents, evt];
      const newEventsCache = { ...state.eventsCache, [runId]: updatedEvents };

      // 2. Lookup or create RunSummary for this run_id
      let run = state.runsCache[runId] ? { ...state.runsCache[runId] } : null;
      if (!run) {
        let wmo = 0;
        if (state.currentBatch?.items) {
          const matchItem = state.currentBatch.items.find((i) => i.run_id === runId);
          if (matchItem) wmo = matchItem.wmo;
        }
        if (!wmo && state.activeRunId === runId) {
          wmo = state.customWmo || state.selectedPreset?.wmo || 0;
        }
        const preset = state.presets.find((p) => p.wmo === wmo) || state.selectedPreset;

        run = {
          run_id: runId,
          wmo: wmo || preset?.wmo || 0,
          float_type: preset?.platform_type || "APEX",
          platform_family: "FLOAT",
          transmission_type: preset?.transmission_type || "ARGOS",
          decoder_id: preset?.decoder_id,
          decoder_version: preset?.decoder_version || "",
          status: "active",
          start_time: evt.timestamp,
          duration_seconds: 0,
          total_files: preset?.input_file_count || 0,
          total_cycles: 0,
          completed_cycles: 0,
          profile_count: 0,
          missing_profiles: 0,
          active_stage: evt.stage || "INPUT_FILES",
          active_operation: evt.operation || evt.message,
          stages: createCleanStages(),
          cycles: [],
          output_files: [],
          errors: [],
        };
      } else {
        run.stages = { ...run.stages };
      }

      if (run.status === "stopped" || run.status === "cancelled") {
        if (evt.status !== "stopped" && evt.status !== "cancelled" && evt.level !== "warning") {
          return { eventsCache: newEventsCache };
        }
      }

      run.run_id = runId;

      if (evt.stage) {
        const stage = run.stages[evt.stage]
          ? { ...run.stages[evt.stage] }
          : {
              id: evt.stage,
              name: evt.stage.replace(/_/g, " "),
              status: "pending" as NodeStatus,
              active_operation: "",
              detail: "",
              updated_at: evt.timestamp,
            };

        stage.status = evt.status;
        stage.active_operation =
          evt.status === "completed" || evt.status === "stopped" ? "" : evt.operation || "";
        if (evt.cycle !== undefined) stage.current_cycle = evt.cycle;
        stage.detail = evt.message;
        stage.updated_at = evt.timestamp;

        run.stages[evt.stage] = stage;
        run.active_stage = evt.stage;
        run.active_operation =
          evt.status === "completed" || evt.status === "stopped" ? "" : evt.operation || evt.message;
      }

      let isFinished = false;
      if (
        (evt.stage === "DONE" && (evt.status === "completed" || evt.status === "stopped" || evt.status === "cancelled")) ||
        evt.status === "stopped" ||
        evt.status === "cancelled"
      ) {
        run.status = evt.status === "completed" ? "completed" : "stopped";
        run.active_operation =
          evt.status === "completed" ? "Pipeline completed successfully" : "Stopped by user";
        for (const stgKey of STAGE_ORDER) {
          if (run.stages[stgKey]) {
            run.stages[stgKey].active_operation = "";
          }
        }
        isFinished = true;
      }

      if (evt.level === "error") {
        run.errors = [...run.errors, evt.error_details || evt.message];
      }

      const newRunsCache = { ...state.runsCache, [runId]: run };

      // 3. If currently visible run matches this event, update visible state live
      if (state.activeRunId === runId) {
        const shouldStopTimers = isFinished && !state.batchRunning;
        if (shouldStopTimers) {
          if (state.timerInterval) clearInterval(state.timerInterval);
          if (state.pollInterval) clearInterval(state.pollInterval);
        }

        return {
          eventsCache: newEventsCache,
          runsCache: newRunsCache,
          events: updatedEvents,
          currentRun: run,
          isRunning: run.status === "active",
          isStopping: isFinished ? false : state.isStopping,
          timerInterval: shouldStopTimers ? null : state.timerInterval,
          pollInterval: shouldStopTimers ? null : state.pollInterval,
        };
      }

      return {
        eventsCache: newEventsCache,
        runsCache: newRunsCache,
      };
    });
  },

  updateRunSummary: (run) => {
    if (!run || !run.run_id) return;

    set((state) => {
      const runId = run.run_id;
      const isFinished =
        run.status === "completed" ||
        run.status === "error" ||
        run.status === "stopped" ||
        run.status === "cancelled";

      // Terminal-state monotonicity: once a run has reached a terminal status
      // (completed/error/stopped/cancelled) it must NEVER be reverted to
      // active/pending by a stale poll snapshot. The final backend RunSummary
      // is stored after the pipeline_end event, so a /api/runs response
      // captured in that window still reports "active"; if it lands after the
      // client has already applied the terminal state, applying it would make
      // the UI stuck "decoding" forever (polling is already cleared and no
      // other update follows). Only another terminal snapshot may refresh a
      // terminal run.
      const cachedRun = state.runsCache[runId];
      const TERMINAL_STATUSES: NodeStatus[] = ["completed", "error", "stopped", "cancelled"];
      if (
        cachedRun &&
        TERMINAL_STATUSES.includes(cachedRun.status) &&
        !TERMINAL_STATUSES.includes(run.status)
      ) {
        return {};
      }

      if (run.status === "completed" || run.status === "stopped" || run.status === "cancelled") {
        for (const stgKey of STAGE_ORDER) {
          if (run.stages[stgKey]) {
            run.stages[stgKey].active_operation = "";
          }
        }
      }

      const newRunsCache = { ...state.runsCache, [runId]: run };

      if (state.activeRunId === runId) {
        if (isFinished && !state.batchRunning) {
          if (state.timerInterval) clearInterval(state.timerInterval);
          if (state.pollInterval) clearInterval(state.pollInterval);
        }

        return {
          runsCache: newRunsCache,
          currentRun: run,
          isRunning: run.status === "active",
          isStopping: isFinished ? false : state.isStopping,
          timerInterval: isFinished && !state.batchRunning ? null : state.timerInterval,
          pollInterval: isFinished && !state.batchRunning ? null : state.pollInterval,
        };
      }

      return {
        runsCache: newRunsCache,
      };
    });
  },

  updateBatchSummary: (batch) => {
    try {
      if (typeof window !== "undefined" && window.sessionStorage) {
        window.sessionStorage.removeItem("argo_summary_cleared");
      }
    } catch {}

    set((state) => {
      const isFinished =
        batch.status === "completed" ||
        batch.status === "error" ||
        batch.status === "stopped" ||
        batch.status === "cancelled";

      if (isFinished) {
        if (state.timerInterval) clearInterval(state.timerInterval);
        if (state.pollInterval) clearInterval(state.pollInterval);
      }

      const updatedRunsCache = { ...state.runsCache };
      if (batch.items) {
        for (const item of batch.items) {
          if (item.run_id && !updatedRunsCache[item.run_id]) {
            const preset = state.presets.find((p) => p.wmo === item.wmo) || null;
            const fresh = createEmptyRun(preset, item.wmo);
            fresh.run_id = item.run_id;
            fresh.status = item.status;
            updatedRunsCache[item.run_id] = fresh;
          }
        }
      }

      // If batch switched to a new running float and autoFollowBatch is enabled, switch active run!
      if (batch.running_run_id && batch.running_run_id !== state.activeRunId && state.autoFollowBatch) {
        const preset = state.presets.find((p) => p.wmo === batch.running_wmo) || null;
        let targetRun = updatedRunsCache[batch.running_run_id];
        if (!targetRun) {
          targetRun = createEmptyRun(preset, batch.running_wmo || 0);
          targetRun.run_id = batch.running_run_id;
          targetRun.status = "active";
          targetRun.active_operation = "Decoding telemetry...";
          updatedRunsCache[batch.running_run_id] = targetRun;
        }

        const targetEvents = state.eventsCache[batch.running_run_id] || [];

        return {
          currentBatch: batch,
          batchRunning: !isFinished,
          isStopping: isFinished ? false : state.isStopping,
          activeRunId: batch.running_run_id,
          selectedPreset: preset,
          customWmo: batch.running_wmo || null,
          currentRun: targetRun,
          events: targetEvents,
          isRunning: true,
          runsCache: updatedRunsCache,
          timerInterval: isFinished ? null : state.timerInterval,
          pollInterval: isFinished ? null : state.pollInterval,
        };
      }

      return {
        currentBatch: batch,
        batchRunning: !isFinished,
        isStopping: isFinished ? false : state.isStopping,
        runsCache: updatedRunsCache,
        timerInterval: isFinished ? null : state.timerInterval,
        pollInterval: isFinished ? null : state.pollInterval,
      };
    });

    if (batch.status === "completed" || batch.status === "stopped") {
      get().fetchAllRuns();
      get().fetchAllBatches();
    }
  },

  startDecode: async () => {
    const { selectedPreset, customWmo, timerInterval, pollInterval } = get();
    if (timerInterval) clearInterval(timerInterval);
    if (pollInterval) clearInterval(pollInterval);

    const wmo = customWmo || selectedPreset?.wmo || 2901304;
    const generatedRunId = `run-${wmo}-${Date.now().toString(36)}-${Math.random().toString(36).substring(2, 6)}`;

    const freshRun = createEmptyRun(selectedPreset, wmo);
    freshRun.run_id = generatedRunId;
    freshRun.status = "active";
    freshRun.active_operation = "Initiating decode execution...";

    const tInterval = setInterval(() => {
      set((s) => ({ timerSeconds: s.timerSeconds + 0.1 }));
    }, 100);

    const pInterval = setInterval(async () => {
      const { isRunning, isStopping, activeRunId } = get();
      if ((!isRunning && !isStopping) || !activeRunId) {
        clearInterval(pInterval);
        return;
      }
      await get().syncRun(activeRunId);
    }, 300);

    set((state) => ({
      activeRunId: generatedRunId,
      autoFollowBatch: false,
      isRunning: true,
      isStopping: false,
      timerSeconds: 0,
      timerInterval: tInterval,
      pollInterval: pInterval,
      events: [],
      selectedEvent: null,
      selectedRtqcTest: null,
      selectedCycle: null,
      selectedOutputFile: null,
      currentRun: freshRun,
      investigationRunId: null,
      investigation: null,
      investigationLoading: false,
      investigationError: null,
      investigationMissing: null,
      runsCache: { ...state.runsCache, [generatedRunId]: freshRun },
      eventsCache: { ...state.eventsCache, [generatedRunId]: [] },
    }));

    try {
      const res = await fetch("/api/decode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          wmo,
          run_id: generatedRunId,
          input_path: selectedPreset?.input_path,
          metadata_backend: selectedPreset?.metadata_backend || "csv",
          registry_path: selectedPreset?.registry_path,
          info_dir: selectedPreset?.info_dir,
          meta_dir: selectedPreset?.meta_dir,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        console.error("Decode request failed:", err);
      } else {
        setTimeout(() => {
          get().syncRun(generatedRunId);
        }, 150);
      }
    } catch (e) {
      console.error("Failed to trigger decode:", e);
    }
  },

  startDecodeAll: async (force: boolean = false) => {
    // Any new start (or Re-run All) supersedes a previous "already complete"
    // notice; the server will re-decide from current state below.
    set({ decodeAllAlreadyComplete: null });
    try {
      if (typeof window !== "undefined" && window.sessionStorage) {
        window.sessionStorage.removeItem("argo_summary_cleared");
      }
    } catch {}

    const { timerInterval, pollInterval } = get();
    if (timerInterval) clearInterval(timerInterval);
    if (pollInterval) clearInterval(pollInterval);

    const tInterval = setInterval(() => {
      set((s) => ({ timerSeconds: s.timerSeconds + 0.1 }));
    }, 100);

    const batchPollInterval = setInterval(async () => {
      const { batchRunning, isStopping, currentBatch, activeRunId } = get();
      if ((!batchRunning && !isStopping) || !currentBatch) {
        clearInterval(batchPollInterval);
        return;
      }
      await get().syncBatch(currentBatch.batch_id);
      const runningRunId = get().currentBatch?.running_run_id;
      if (runningRunId) {
        await get().syncRun(runningRunId);
      } else if (activeRunId) {
        await get().syncRun(activeRunId);
      }
    }, 350);

    set({
      batchRunning: true,
      isRunning: true,
      autoFollowBatch: true,
      isStopping: false,
      timerSeconds: 0,
      timerInterval: tInterval,
      pollInterval: batchPollInterval,
    });

    try {
      const res = await fetch("/api/batch/decode-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data?.status === "already_complete") {
          // No new batch was created — today's floats all already have
          // successful decodes. Unwind the optimistic "running" state and
          // surface the View Results / Re-run All notice instead.
          if (tInterval) clearInterval(tInterval);
          if (batchPollInterval) clearInterval(batchPollInterval);
          set({
            batchRunning: false,
            isRunning: false,
            autoFollowBatch: false,
            timerInterval: null,
            pollInterval: null,
            decodeAllAlreadyComplete: {
              message:
                typeof data.message === "string"
                  ? data.message
                  : "Today's fleet decoding is already complete. All currently detected floats have already been processed.",
              batchId: typeof data.batch_id === "string" ? data.batch_id : null,
            },
          });
          return;
        }
        if (data.batch_id) {
          get().syncBatch(data.batch_id);
        }
        return;
      }

      if (res.status === 409) {
        // A fleet batch is already running on the backend (this was a second
        // tab, a repeated request, or a racing click). Do NOT error the UI:
        // follow the batch that is actually executing instead.
        let activeId: string | null = null;
        try {
          const err = await res.json();
          activeId = err?.detail?.active_batch_id || null;
        } catch {
          // ignore parse failure
        }
        if (activeId) {
          set({ autoFollowBatch: true });
          await get().syncBatch(activeId);
          if (!get().currentBatch) {
            get().fetchAllBatches();
          }
        } else {
          set({
            batchRunning: false,
            isRunning: false,
            timerInterval: null,
            pollInterval: null,
          });
          if (tInterval) clearInterval(tInterval);
          if (batchPollInterval) clearInterval(batchPollInterval);
        }
        return;
      }

      // Other failure: unwind the optimistic "running" state.
      set({ batchRunning: false, isRunning: false, timerInterval: null, pollInterval: null });
      if (tInterval) clearInterval(tInterval);
      if (batchPollInterval) clearInterval(batchPollInterval);
    } catch (err) {
      console.error("Failed to start batch decode:", err);
      set({ batchRunning: false, isRunning: false, timerInterval: null, pollInterval: null });
      if (tInterval) clearInterval(tInterval);
      if (batchPollInterval) clearInterval(batchPollInterval);
    }
  },

  stopDecode: async () => {
    const { currentBatch, batchRunning, currentRun, timerInterval, pollInterval, events, timerSeconds, activeRunId } = get();
    
    if (timerInterval) clearInterval(timerInterval);
    if (pollInterval) clearInterval(pollInterval);

    const runId = currentRun?.run_id || activeRunId;
    const batchId = currentBatch?.batch_id;

    const updatedRun = currentRun ? { ...currentRun } : null;
    if (updatedRun) {
      updatedRun.status = "stopped";
      updatedRun.active_operation = "Stopped by user";
      if (updatedRun.duration_seconds === 0) {
        updatedRun.duration_seconds = Math.round(timerSeconds * 100) / 100;
      }
      for (const stgKey of STAGE_ORDER) {
        if (updatedRun.stages[stgKey]) {
          if (updatedRun.stages[stgKey].status === "active") {
            updatedRun.stages[stgKey].status = "stopped";
          }
          updatedRun.stages[stgKey].active_operation = "";
        }
      }
    }

    const updatedBatch = currentBatch ? { ...currentBatch } : null;
    if (updatedBatch) {
      updatedBatch.status = "stopped";
      updatedBatch.running_wmo = null;
      updatedBatch.running_run_id = null;
      if (updatedBatch.items) {
        updatedBatch.items = updatedBatch.items.map((item) => {
          if (item.status === "pending" || item.status === "active") {
            return {
              ...item,
              status: "stopped" as NodeStatus,
              error_message: "Batch stopped by user",
            };
          }
          return item;
        });
        updatedBatch.stopped_floats = updatedBatch.items.filter(
          (i) => i.status === "stopped" || i.status === "cancelled"
        ).length;
        updatedBatch.pending_floats = 0;
      }
    }

    const stopEvent: LiveEvent = {
      id: `evt-stop-${Date.now()}`,
      run_id: runId || "run-current",
      timestamp: new Date().toISOString(),
      level: "warning",
      message: "🛑 DECODE STOPPED BY USER: Execution halted immediately. Progress preserved.",
      stage: updatedRun?.active_stage || "DONE",
      operation: "Stopped by user",
      status: "stopped",
      what_happened: "User clicked Stop Decode. Execution halted immediately.",
      input_summary: "",
      processing_details: "Stop requested by user",
      output_summary: "",
      python_file: "service/runner_instrumentation.py",
      python_function: "execute_decoder_with_observability",
    };

    const newEvents = [...events, stopEvent];

    set((state) => ({
      isRunning: false,
      batchRunning: false,
      autoFollowBatch: false,
      isStopping: false,
      timerInterval: null,
      pollInterval: null,
      currentRun: updatedRun,
      currentBatch: updatedBatch,
      events: newEvents,
      runsCache: runId && updatedRun ? { ...state.runsCache, [runId]: updatedRun } : state.runsCache,
      eventsCache: runId ? { ...state.eventsCache, [runId]: newEvents } : state.eventsCache,
    }));

    if (batchRunning && batchId) {
      fetch(`/api/batch/${batchId}/stop`, { method: "POST" }).catch((e) =>
        console.error("Failed to stop batch:", e)
      );
    }

    if (runId) {
      fetch(`/api/runs/${runId}/stop`, { method: "POST" }).catch((e) =>
        console.error("Failed to stop run:", e)
      );
    }

    setTimeout(() => {
      if (runId) get().syncRun(runId);
      if (batchId) get().syncBatch(batchId);
      get().fetchAllRuns();
      get().fetchAllBatches();
    }, 150);
  },

  resetRun: () => {
    const { timerInterval, pollInterval, selectedPreset, customWmo } = get();
    if (timerInterval) clearInterval(timerInterval);
    if (pollInterval) clearInterval(pollInterval);
    const wmo = customWmo || selectedPreset?.wmo || 0;
    set({
      activeRunId: null,
      autoFollowBatch: false,
      currentRun: createEmptyRun(selectedPreset, wmo),
      events: [],
      isRunning: false,
      isStopping: false,
      timerSeconds: 0,
      timerInterval: null,
      pollInterval: null,
      selectedEvent: null,
      selectedRtqcTest: null,
      selectedCycle: null,
      selectedOutputFile: null,
      currentBatch: null,
      batchRunning: false,
      investigationRunId: null,
      investigation: null,
      investigationLoading: false,
      investigationError: null,
      investigationMissing: null,
    });
  },

  setSelectedEvent: (evt) => set({ selectedEvent: evt }),
  setSelectedRtqcTest: (test) => set({ selectedRtqcTest: test }),
  setRtqcModalOpen: (open) => set({ isRtqcModalOpen: open }),
  setSelectedCycle: (cycle) => set({ selectedCycle: cycle }),
  setCycleModalOpen: (open) => set({ isCycleModalOpen: open }),
  setSelectedOutputFile: (file) => set({ selectedOutputFile: file }),
  setOutputModalOpen: (open) => set({ isOutputModalOpen: open }),
  setFlowchartModalOpen: (open) => set({ isFlowchartModalOpen: open }),
  setBatchSummaryModalOpen: (open) => set({ isBatchSummaryModalOpen: open }),
  setRunHistoryModalOpen: (open) => set({ isRunHistoryModalOpen: open }),
  setLogFilter: (filter) => set({ logFilter: filter }),
  setLogSearch: (search) => set({ logSearch: search }),
  setAutoScroll: (val) => set({ autoScroll: val }),

  clearLogs: () => {
    const { activeRunId, eventsCache } = get();
    const newEventsCache = activeRunId ? { ...eventsCache, [activeRunId]: [] } : eventsCache;
    set({
      events: [],
      selectedEvent: null,
      logSearch: "",
      eventsCache: newEventsCache,
    });
  },

  clearBatchSummary: () => {
    const { timerInterval, pollInterval } = get();
    if (get().batchRunning) {
      if (timerInterval) clearInterval(timerInterval);
      if (pollInterval) clearInterval(pollInterval);
    }
    try {
      if (typeof window !== "undefined" && window.sessionStorage) {
        window.sessionStorage.setItem("argo_summary_cleared", "true");
      }
    } catch {}
    set({
      currentBatch: null,
      selectedResultWmo: null,
      batchRunning: false,
      isStopping: false,
      isBatchSummaryModalOpen: false,
    });
  },

  loadBatchSummary: (batch: BatchSummary) => {
    try {
      if (typeof window !== "undefined" && window.sessionStorage) {
        window.sessionStorage.removeItem("argo_summary_cleared");
      }
    } catch {}
    set({
      currentBatch: batch,
      selectedResultWmo: batch.items && batch.items.length > 0 ? batch.items[0].wmo : null,
    });
  },

  clearRunSummary: () => {
    const { selectedPreset, customWmo, timerInterval, pollInterval } = get();
    if (timerInterval) clearInterval(timerInterval);
    if (pollInterval) clearInterval(pollInterval);
    const wmo = customWmo || selectedPreset?.wmo || 0;
    set({
      activeRunId: null,
      autoFollowBatch: false,
      currentRun: createEmptyRun(selectedPreset, wmo),
      events: [],
      selectedEvent: null,
      selectedRtqcTest: null,
      selectedCycle: null,
      selectedOutputFile: null,
      isRunning: false,
      isStopping: false,
      timerSeconds: 0,
      timerInterval: null,
      pollInterval: null,
    });
  },
}));
