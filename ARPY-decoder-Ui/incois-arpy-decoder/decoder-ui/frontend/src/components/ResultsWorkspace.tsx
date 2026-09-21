import React, { useState, useEffect, useMemo, useRef } from "react";
import { createPortal } from "react-dom";
import {
  ArrowLeft,
  Trash2,
  FileSpreadsheet,
  FileText,
  XCircle,
  CheckCircle2,
  Search,
  Satellite,
  ChevronRight,
  ShieldCheck,
  Copy,
  Check,
  AlertTriangle,
  Database,
  Waves,
  FileCode,
  Layers,
  Activity,
  Mail,
  Maximize2,
  Minimize2,
} from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";
import { primaryError, primaryErrorSuffix } from "../utils/investigate";
import {
  BatchFloatItem,
  CycleRecord,
  NodeStatus,
  RunSummary,
} from "../types";
import FleetOceanMap, { EezMapOverlays, FleetMapFloat, FleetMapTrajectoryPoint } from "./FleetOceanMap";
import NewArrivalsPanel from "./NewArrivalsPanel";
import ScientificProfileChart, { CtdRecord, ProfileSample, decimalsForSpan, qcLabel } from "./ScientificProfileChart";

/**
 * ResultsWorkspace — Fleet → Float → Cycle → Profile → QC → Deliverables.
 *
 * Every number, position, flag and file shown here is read from the real
 * backend run/batch history. Nothing is synthesized. The page is a separate
 * full-page workspace (not a popup) and all actions reuse the existing
 * run-history / deep-link architecture.
 */

/** Canonical Argo / Coriolis Table 11 test names (same set used by the
 *  backend observability layer and the in-app RTQC reference modal). */
const TABLE11: Record<number, string> = {
  1: "Platform Identification",
  2: "Impossible Date",
  3: "Impossible Location",
  4: "Position on Land",
  5: "Impossible Speed",
  6: "Global Range",
  8: "Pressure Increasing",
  9: "Spike",
  11: "Gradient",
  12: "Digit Rollover",
  13: "Stuck Value",
  14: "Density Inversion",
  16: "Gross Sensor Drift",
  18: "Frozen Profile",
  19: "Deepest Pressure",
};

/** Core parameters are never treated as BGC sensor channels (rule-based, so a
 *  core-only BR profile can never be mislabeled BGC — mirrors the service). */
const CORE_PARAM_SET = new Set(["PRES", "TEMP", "PSAL"]);

/** Processing history milestones — read from the real run stage states. */
const STAGE_CHAIN: Array<{ label: string; stageId: keyof RunSummary["stages"] }> = [
  { label: "INPUT", stageId: "INPUT_FILES" },
  { label: "METADATA", stageId: "METADATA" },
  { label: "DECODE", stageId: "DECODE" },
  { label: "RTQC", stageId: "RTQC" },
  { label: "OUTPUT", stageId: "OUTPUT" },
];

function normStatus(s: string | undefined | null): string {
  return (s || "").toLowerCase();
}

function isTerminalStopped(s: string): boolean {
  const n = normStatus(s);
  return n === "stopped" || n === "cancelled";
}

function fmtBytes(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export const ResultsWorkspace: React.FC = () => {
  const {
    currentBatch,
    allRuns,
    runsCache,
    viewRun,
    setActiveView,
    clearBatchSummary,
    setRunHistoryModalOpen,
    selectedResultWmo,
    setSelectedResultWmo,
    fetchAllRuns,
    ingestionArrivals,
    eezLayerOn,
    setEezLayerOn,
    eezGeometryStatus,
    eez,
    loadEezGeometry,
    eezTransitions,
    eezDismissed,
    syncEezForFloat,
  } = useDecoderStore();

  const [statusFilter, setStatusFilter] = useState<"all" | "completed" | "error" | "stopped">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [showConfirmClear, setShowConfirmClear] = useState(false);
  const [selectedCycleIndex, setSelectedCycleIndex] = useState(0);
  const [hoveredLevel, setHoveredLevel] = useState<number | null>(null);
  const [copiedHash, setCopiedHash] = useState<string | null>(null);
  // Fleet-only full-screen mode: header + summary + map + legend + fleet
  // table expand to the whole viewport; the scientific profile panel is
  // hidden. Same components/state, so exiting restores the exact layout.
  const [fleetFullScreen, setFleetFullScreen] = useState(false);
  const [showPoints, setShowPoints] = useState(true);
  const [showGrid, setShowGrid] = useState(true);

  // SHARED fleet-map instance: one FleetOceanMap is kept mounted for the
  // whole Results session and only RE-PARKED between the normal page slot
  // and the full-screen slot via a React portal. Opening "Expand Fleet"
  // therefore keeps markers, trajectory, selection and the already-decoded
  // basemap (it is preloaded with the app) — no remount, no skeleton view.
  const [normalMapSlot, setNormalMapSlot] = useState<HTMLDivElement | null>(null);
  const [fullMapSlot, setFullMapSlot] = useState<HTMLDivElement | null>(null);

  const batch = currentBatch;
  const items = batch?.items || [];
  const hasBatch = batch !== null && items.length > 0;

  // ------------------------------------------------------------------
  // INDIAN EEZ geographic monitoring — the verified reference geometry is
  // loaded exactly ONCE per session (module singleton in the store); the
  // layer stays visualization-only and OFF until the operator enables it.
  // ------------------------------------------------------------------
  useEffect(() => {
    loadEezGeometry();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Active float (scoped to the current batch summary)
  const activeWmo = hasBatch
    ? selectedResultWmo && items.some((i) => i.wmo === selectedResultWmo)
      ? selectedResultWmo
      : items[0].wmo
    : null;

  const activeItem: BatchFloatItem | null = useMemo(
    () => (hasBatch && activeWmo ? items.find((i) => i.wmo === activeWmo) || null : null),
    [hasBatch, activeWmo, items]
  );

  // Real run summary for the active float (from cache / run list / API).
  // Bound by EXACT run_id only: falling back to another run of the same WMO
  // would display a stale, unrelated run's error as this float's failure.
  const activeRun: RunSummary | null = useMemo(() => {
    if (!hasBatch || !activeWmo) return null;
    const batchItem = items.find((i) => i.wmo === activeWmo);
    if (!batchItem?.run_id) return null;
    if (runsCache[batchItem.run_id]) return runsCache[batchItem.run_id];
    return allRuns.find((r) => r.run_id === batchItem.run_id) || null;
  }, [hasBatch, activeWmo, items, runsCache, allRuns]);

  // Fetch full run detail when it is not cached yet (same pattern as before).
  // Exact run_id only — never a same-WMO stand-in for another run. Fetch
  // ONLY when no run is cached at all: cache/list entries are already
  // complete summaries, so re-fetching a present-but-cycleless run
  // (every failed run) can never add data — it only re-triggers this
  // effect forever via updateRunSummary.
  useEffect(() => {
    if (activeWmo && !activeRun) {
      const matchItem = items.find((i) => i.wmo === activeWmo);
      const targetRunId = matchItem?.run_id;
      if (targetRunId) {
        fetch(`/api/runs/${targetRunId}`)
          .then((res) => (res.ok ? res.json() : null))
          .then((data) => {
            if (data) useDecoderStore.getState().updateRunSummary(data);
          })
          .catch(() => {});
      }
    }
  }, [activeWmo, activeRun, items, allRuns]);

  // When the selected float or its run changes: reset hover and pick the
  // most data-rich cycle (never a fabricated selection).
  useEffect(() => {
    setHoveredLevel(null);
    const cycles = activeRun?.cycles || [];
    if (cycles.length === 0) {
      setSelectedCycleIndex(0);
      return;
    }
    let best = 0;
    let bestLevels = -1;
    cycles.forEach((c, idx) => {
      const n = c.levels_count || c.ctd_samples?.length || 0;
      if (n > bestLevels) {
        bestLevels = n;
        best = idx;
      }
    });
    setSelectedCycleIndex(best);
  }, [activeWmo, activeRun?.run_id]);

  // ------------------------------------------------------------------
  // Filters
  // ------------------------------------------------------------------
  const filteredItems = items.filter((item) => {
    if (statusFilter === "completed" && item.status !== "completed") return false;
    if (statusFilter === "error" && item.status !== "error") return false;
    if (statusFilter === "stopped" && !isTerminalStopped(String(item.status))) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchWmo = item.wmo.toString().includes(q);
      const matchPlatform = (item.platform_type || "").toLowerCase().includes(q);
      const matchTrans = (item.transmission_type || "").toLowerCase().includes(q);
      const matchErr = (item.error_message || "").toLowerCase().includes(q);
      if (!matchWmo && !matchPlatform && !matchTrans && !matchErr) return false;
    }
    return true;
  });

  const handleCopyHash = (hash: string) => {
    navigator.clipboard.writeText(hash);
    setCopiedHash(hash);
    setTimeout(() => setCopiedHash(null), 2000);
  };

  // Existing deep-link architecture: viewRun restores the historical run
  // (logs, events, error focus) and switches to the Decoder page. The batch
  // item's error travels along so a missing run still shows the real failure
  // instead of a misleading generic notice.
  const handleNavigateToRun = (
    runId: string,
    focusError: boolean = false,
    fallbackError?: string | null,
  ) => {
    viewRun(runId, focusError, undefined, { fallbackError: fallbackError ?? null });
    setActiveView("decoder");
  };

  const handleConfirmClear = () => {
    clearBatchSummary();
    setShowConfirmClear(false);
  };

  // ------------------------------------------------------------------
  // Real cycle data for the active float
  // ------------------------------------------------------------------
  const activeCycles: CycleRecord[] = activeRun?.cycles || [];
  const currentCycle: CycleRecord | null =
    activeCycles[selectedCycleIndex] || activeCycles[0] || null;

  const ctdSamples: CtdRecord[] = (currentCycle?.ctd_samples || []).map((s) => ({
    level: s.level,
    PRES: s.PRES ?? null,
    TEMP: s.TEMP ?? null,
    PSAL: s.PSAL ?? null,
    CNDC: s.CNDC ?? null,
    PRES_QC: s.PRES_QC ?? null,
    TEMP_QC: s.TEMP_QC ?? null,
    PSAL_QC: s.PSAL_QC ?? null,
  }));

  const tempData: ProfileSample[] = useMemo(
    () =>
      ctdSamples.map((s) => ({
        level: s.level,
        pres: s.PRES,
        value: s.TEMP,
        qc: s.TEMP_QC !== null && s.TEMP_QC !== undefined ? String(s.TEMP_QC) : null,
      })),
    [ctdSamples]
  );
  const psalData: ProfileSample[] = useMemo(
    () =>
      ctdSamples.map((s) => ({
        level: s.level,
        pres: s.PRES,
        value: s.PSAL,
        qc: s.PSAL_QC !== null && s.PSAL_QC !== undefined ? String(s.PSAL_QC) : null,
      })),
    [ctdSamples]
  );

  // BGC: one chart card per sensor parameter that actually carries data in
  // this cycle's BR profiles (file's own labels/units). All-fill channels
  // are NEVER projected into a card — they surface as missing-data notices.
  // Composite level ids (profile × 100000 + level) keep hover keys unique
  // across the heterogeneous N_PROF grids without colliding with CTD levels.
  const bgcProfiles = currentCycle?.bgc_profiles || [];
  const bgcCards = useMemo(() => {
    const byParam = new Map<
      string,
      { label: string; units: string; data: ProfileSample[] }
    >();
    for (const prof of bgcProfiles) {
      const params = (prof.station_parameters || []).filter(
        (p) => p && !CORE_PARAM_SET.has(p)
      );
      for (const p of params) {
        const rows: ProfileSample[] = (prof.samples || []).map((s) => ({
          level: prof.profile_index * 100000 + Number(s.level || 0),
          pres: typeof s.PRES === "number" ? s.PRES : null,
          value: typeof s[p] === "number" ? (s[p] as number) : null,
          qc: s[`${p}_QC`] !== null && s[`${p}_QC`] !== undefined ? String(s[`${p}_QC`]) : null,
        }));
        if (!rows.some((r) => r.value !== null)) continue;
        const entry = byParam.get(p) || {
          label: prof.param_labels?.[p] || p,
          units: prof.param_units?.[p] || "",
          data: [] as ProfileSample[],
        };
        entry.data.push(...rows);
        byParam.set(p, entry);
      }
    }
    return [...byParam.entries()].map(([param, e]) => ({
      param,
      label: e.label,
      units: e.units,
      data: e.data.sort((a, b) => (a.pres ?? 1e9) - (b.pres ?? 1e9)),
    }));
  }, [bgcProfiles]);
  // Profiles whose labeled sensor channels are entirely fill (never plotted).
  const bgcMissingProfiles = useMemo(
    () => bgcProfiles.filter((p) => !p.sensor_data_present),
    [bgcProfiles]
  );

  // BGC measurement tables: one per profile that carries data, with columns
  // driven by the file's own station parameters (never hardcoded) and
  // per-parameter display decimals adapted to the measured span — the same
  // rule the charts use, so both render identical values.
  const bgcTables = useMemo(() => {
    const tables: Array<{
      profileIndex: number;
      params: string[];
      units: Record<string, string>;
      decimals: Record<string, number>;
      rows: Array<Record<string, number | string | null>>;
    }> = [];
    for (const prof of bgcProfiles) {
      const params = (prof.station_parameters || []).filter(
        (p) => p && !CORE_PARAM_SET.has(p)
      );
      const withData = params.filter((p) =>
        (prof.samples || []).some((s) => typeof s[p] === "number")
      );
      if (withData.length === 0) continue;
      const decimals: Record<string, number> = {};
      for (const p of withData) {
        const vals = (prof.samples || [])
          .map((s) => s[p])
          .filter((v): v is number => typeof v === "number");
        const pspan =
          vals.length > 1 ? Math.max(...vals) - Math.min(...vals) : 0;
        decimals[p] = decimalsForSpan(pspan);
      }
      tables.push({
        profileIndex: prof.profile_index,
        params: withData,
        units: prof.param_units || {},
        decimals,
        rows: prof.samples || [],
      });
    }
    return tables;
  }, [bgcProfiles]);

  // Trajectory for the selected float: ALL its real decoded cycle positions,
  // ordered by the actual cycle number (JULD tiebreak) — never array order,
  // never another float's data.
  const trajectoryPoints: FleetMapTrajectoryPoint[] = useMemo(() => {
    const pts = activeCycles
      .filter(
        (c) =>
          c.latitude !== undefined &&
          c.longitude !== undefined &&
          Math.abs(c.latitude as number) <= 90 &&
          Math.abs(c.longitude as number) <= 180
      )
      .map((c) => ({
        cycle: c.cycle_number,
        lat: c.latitude as number,
        lon: c.longitude as number,
        posQc: c.position_qc,
        juld: c.juld ?? null,
      }));
    pts.sort(
      (a, b) => a.cycle - b.cycle || (a.juld ?? 0) - (b.juld ?? 0)
    );
    return pts;
  }, [activeCycles]);

  // ------------------------------------------------------------------
  // EEZ derivation (separate dimension): classify the real decoded cycle
  // positions of every fleet float — idempotent across every re-render,
  // toggle, zoom, resize and Full Screen transition thanks to stable
  // event identities inside syncEezForFloat.
  // ------------------------------------------------------------------
  const eezGeometryReady = eezGeometryStatus === "ready" && eez !== null;

  // Active float first (drives immediate on-map trajectory state).
  // Same float the map trajectory represents (selected or batch default).
  const activeWmoForEez = activeWmo;
  useEffect(() => {
    if (!eezGeometryReady || activeWmoForEez == null) return;
    syncEezForFloat(activeWmoForEez, trajectoryPoints);
  }, [eezGeometryReady, activeWmoForEez, trajectoryPoints, syncEezForFloat]);

  // Every float of the current batch whose run summary is hydrated.
  useEffect(() => {
    if (!eezGeometryReady || !hasBatch) return;
    for (const item of items) {
      const run =
        (item.run_id ? runsCache[item.run_id] : null) ||
        (item.run_id ? allRuns.find((r) => r.run_id === item.run_id) : null) ||
        allRuns.find((r) => r.wmo === item.wmo) ||
        null;
      if (!run || !run.cycles || run.cycles.length === 0) continue;
      const pts = run.cycles
        .filter(
          (c) =>
            c.latitude !== undefined &&
            c.longitude !== undefined &&
            Math.abs(c.latitude as number) <= 90 &&
            Math.abs(c.longitude as number) <= 180
        )
        .map((c) => ({
          cycle: c.cycle_number,
          lat: c.latitude as number,
          lon: c.longitude as number,
          juld: c.juld ?? null,
        }));
      if (pts.length === 0) continue;
      syncEezForFloat(item.wmo, pts);
    }
  }, [eezGeometryReady, hasBatch, items, runsCache, allRuns, syncEezForFloat]);

  // Compact per-cycle EEZ states of the SELECTED float for the map.
  const eezByWmo = useDecoderStore((s) => s.eezByWmo);
  const activeEezClassified = useMemo(
    () => (activeWmoForEez == null ? undefined : eezByWmo[activeWmoForEez]),
    [eezByWmo, activeWmoForEez]
  );

  // CURRENT (latest valid-cycle) EEZ state per float — drives the marker
  // halo. Pure geography: derived from real decoded positions, identical
  // for every consumer, and NEVER confused with an entry/exit event.
  const eezCurrentStatus = useMemo(() => {
    const out: Record<number, "INDIAN_EEZ" | "OUTSIDE_INDIAN_EEZ"> = {};
    for (const [wmoKey, classified] of Object.entries(eezByWmo)) {
      if (!classified || classified.length === 0) continue;
      out[Number(wmoKey)] = classified[classified.length - 1].eezStatus;
    }
    return out;
  }, [eezByWmo]);
  const selectedEezTransitions = useMemo(
    () =>
      activeWmoForEez == null
        ? []
        : eezTransitions.filter((t) => t.wmo === activeWmoForEez),
    [eezTransitions, activeWmoForEez]
  );

  // Latest-cycle EEZ state for the selected-float header (§ separate from
  // processing status — it only reports geography).
  const activeEezStatus = useMemo(() => {
    if (!activeEezClassified || activeEezClassified.length === 0) return null;
    return activeEezClassified[activeEezClassified.length - 1].eezStatus;
  }, [activeEezClassified]);

  const eezOverlays: EezMapOverlays | undefined = useMemo(() => {
    if (!hasBatch) return undefined;
    return {
      layerOn: eezLayerOn,
      onToggle: setEezLayerOn,
      status: eezGeometryStatus,
      geom: eez,
      classified: activeEezClassified ?? null,
      transitions: selectedEezTransitions,
      history: eezTransitions,
      dismissed: eezDismissed,
      currentStatus: eezCurrentStatus,
    };
  }, [
    hasBatch,
    eezLayerOn,
    setEezLayerOn,
    eezGeometryStatus,
    eez,
    activeEezClassified,
    selectedEezTransitions,
    eezTransitions,
    eezDismissed,
    eezCurrentStatus,
  ]);

  // ------------------------------------------------------------------
  // Data-driven fleet hydration (batch-scoped, never hardcoded)
  // ------------------------------------------------------------------
  // The map must show the SAME float set as the Results table, so for
  // EVERY item of the current batch we ensure its real decoded run
  // summary is loaded from the backend (/api/runs/{run_id}). Which floats
  // exist is decided entirely by the backend discovery result stored in
  // the batch — no WMO list, count or name is written in code. When the
  // backend discovers a different set tomorrow, this same code path
  // adapts automatically because it is driven by `items`.
  const batchId = batch?.batch_id || null;
  const requestedRunIds = useRef<Record<string, Set<string>>>({});
  useEffect(() => {
    if (!batchId || items.length === 0) return;
    // Always keep the full backend run list fresh (real runs only).
    fetchAllRuns();
    const seen = requestedRunIds.current[batchId] || new Set<string>();
    requestedRunIds.current[batchId] = seen;
    for (const item of items) {
      if (!item.run_id) continue; // resolved from run history below
      if (seen.has(item.run_id)) continue;
      const cached = runsCache[item.run_id];
      if (cached && cached.cycles && cached.cycles.length > 0) {
        seen.add(item.run_id);
        continue;
      }
      seen.add(item.run_id);
      fetch(`/api/runs/${item.run_id}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (data) useDecoderStore.getState().updateRunSummary(data);
        })
        .catch(() => {});
    }
    // NOTE: runsCache is deliberately NOT a dep. The per-run `seen` guard
    // above already fetches each run_id once; re-running on every cache
    // update makes the unconditional fetchAllRuns() self-trigger forever
    // (each response writes a new cache object). Hydrate on batch/items
    // change only — the documented intent.
  }, [batchId, items, fetchAllRuns]);

  // Real fleet positions from run history: every float of the current
  // batch that has at least one valid decoded coordinate (the same item
  // list the Results table renders — the map can never show a different
  // float set). Marker position = the float's latest real cycle position.
  const fleetPositions: FleetMapFloat[] = useMemo(() => {
    if (!hasBatch || items.length === 0) return [];
    const list: FleetMapFloat[] = [];
    for (const item of items) {
      const run =
        (item.run_id ? runsCache[item.run_id] : null) ||
        (item.run_id ? allRuns.find((r) => r.run_id === item.run_id) : null) ||
        allRuns.find((r) => r.wmo === item.wmo) ||
        Object.values(runsCache).find(
          (r) => r.wmo === item.wmo && r.cycles && r.cycles.length > 0
        ) ||
        null;
      if (run && run.cycles && run.cycles.length > 0) {
        // Latest real position = highest cycle number (JULD tiebreak).
        const cyclesWithPos = run.cycles
          .filter(
            (c) =>
              c.latitude !== undefined &&
              c.longitude !== undefined &&
              Math.abs(c.latitude as number) <= 90 &&
              Math.abs(c.longitude as number) <= 180
          )
          .sort(
            (a, b) =>
              a.cycle_number - b.cycle_number ||
              (a.juld ?? 0) - (b.juld ?? 0)
          );
        const lastWithPos = cyclesWithPos[cyclesWithPos.length - 1];
        if (lastWithPos) {
          list.push({
            wmo: item.wmo,
            platform: run.float_type || item.platform_type || "—",
            status: item.status || run.status,
            lat: lastWithPos.latitude as number,
            lon: lastWithPos.longitude as number,
            cyclesCount: run.completed_cycles || item.cycles_count || run.cycles.length,
            runId: item.run_id || run.run_id,
          });
        }
      }
    }
    return list;
  }, [hasBatch, items, allRuns, runsCache]);

  // WMOs with NEW incoming source data (backend ingestion registry)
  const newDataWmos = useMemo(
    () => new Set(ingestionArrivals.filter((a) => a.state === "new" && a.wmo !== null).map((a) => a.wmo as number)),
    [ingestionArrivals]
  );

  // ------------------------------------------------------------------
  // Fleet summary metrics (real batch values)
  // ------------------------------------------------------------------
  const totalFloats = hasBatch ? batch?.total_floats || items.length : 0;
  const successFloats = hasBatch
    ? batch?.completed_floats || items.filter((i) => i.status === "completed").length
    : 0;
  const failedFloats = hasBatch
    ? batch?.failed_floats || items.filter((i) => i.status === "error").length
    : 0;
  const stoppedFloats = hasBatch
    ? batch?.stopped_floats ||
      items.filter((i) => isTerminalStopped(String(i.status))).length
    : 0;
  const totalProfilesGen = hasBatch
    ? batch?.total_profiles_generated ||
      items.reduce((acc, i) => acc + (i.profiles_count || 0), 0)
    : 0;
  const totalOutputs = hasBatch
    ? batch?.total_output_files || items.reduce((acc, i) => acc + (i.outputs_count || 0), 0)
    : 0;

  // ------------------------------------------------------------------
  // RTQC summary — strictly from real rtqc_summary records of the run
  // ------------------------------------------------------------------
  const rtqc = useMemo(() => {
    const testsDoneAll = new Set<number>();
    let flaggedAll = 0;
    for (const c of activeCycles) {
      const s = c.rtqc_summary || {};
      const done = Array.isArray(s.tests_done) ? (s.tests_done as number[]) : [];
      done.forEach((t) => testsDoneAll.add(t));
      flaggedAll += Number(s.flagged_levels || 0);
    }
    const sel = currentCycle?.rtqc_summary || {};
    const done = Array.isArray(sel.tests_done) ? (sel.tests_done as number[]) : [];
    const failed = Array.isArray(sel.tests_failed) ? (sel.tests_failed as number[]) : [];
    const flagged = Number(sel.flagged_levels || 0);
    return {
      applicableCount: testsDoneAll.size,
      executedCount: done.length,
      failedCount: failed.length,
      flaggedCount: flagged,
      flaggedAll,
      qcpHex: typeof sel.qcp_hex === "string" ? sel.qcp_hex : "",
      qcfHex: typeof sel.qcf_hex === "string" ? sel.qcf_hex : "",
      failedList: failed,
      doneList: done,
      hasRecords: done.length > 0 || failed.length > 0 || flagged > 0 || testsDoneAll.size > 0,
    };
  }, [activeCycles, currentCycle]);

  // ------------------------------------------------------------------
  // Shared fleet-map element + portal parking
  // ------------------------------------------------------------------
  const fleetMapTarget = fleetFullScreen ? fullMapSlot : normalMapSlot;
  const fleetMapEl = useMemo(
    () =>
      hasBatch ? (
        <FleetOceanMap
          positions={fleetPositions}
          trajectory={trajectoryPoints}
          selectedWmo={activeWmo}
          onSelect={(wmo) => setSelectedResultWmo(wmo)}
          fill={fleetFullScreen}
          dataKey={batchId}
          eez={eezOverlays}
        />
      ) : null,
    [hasBatch, fleetPositions, trajectoryPoints, activeWmo, setSelectedResultWmo, fleetFullScreen, batchId, eezOverlays]
  );

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div className="relative h-screen w-screen flex flex-col bg-[#F4F7F9] text-slate-800 overflow-hidden font-sans select-none">
      {fleetMapTarget && fleetMapEl ? createPortal(fleetMapEl, fleetMapTarget) : null}
      {/* Clear-summary confirmation (only clears the visible view) */}
      {showConfirmClear && (
        <div className="fixed inset-0 z-60 bg-slate-950/70 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in duration-100 font-mono">
          <div className="bg-white rounded shadow-2xl border border-slate-200 w-full max-w-md p-5 space-y-4 select-none">
            <div className="flex items-start space-x-3">
              <div className="w-10 h-10 rounded-full bg-amber-100 border border-amber-300 flex items-center justify-center text-amber-700 shrink-0">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <div className="space-y-1">
                <h3 className="font-bold text-sm text-slate-900">Clear Results Summary View?</h3>
                <p className="text-xs text-slate-600 font-sans leading-relaxed">
                  Clear the current view? Your saved run history will not be deleted.
                </p>
              </div>
            </div>
            <div className="p-2.5 bg-slate-50 border border-slate-200 rounded text-[11px] text-slate-500 font-sans">
              ℹ This action clears only the visible summary workspace. All decoded NetCDF files,
              Coriolis XML reports, and persistent logs remain safely archived on disk.
            </div>
            <div className="flex items-center justify-end space-x-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowConfirmClear(false)}
                className="px-3.5 py-1.5 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-xs font-bold transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmClear}
                className="px-3.5 py-1.5 bg-rose-600 hover:bg-rose-700 text-white font-bold rounded text-xs transition flex items-center space-x-1.5 shadow-2xs cursor-pointer"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>[ Clear Summary ]</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===================== Header ===================== */}
      <header className="h-16 bg-[#163857] text-white border-b border-[#0f2439] px-4 flex items-center justify-between shrink-0 shadow-md">
        <div className="flex items-center space-x-4">
          <button
            onClick={() => setActiveView("decoder")}
            className="px-3.5 py-2 bg-white/10 hover:bg-white/20 text-white border border-white/20 rounded font-mono text-[13px] font-bold transition flex items-center space-x-2 cursor-pointer shadow-2xs"
            title="Return to Live Decoder Workstation"
          >
            <ArrowLeft className="w-4 h-4 text-sky-300" />
            <span>[ Back to Decoder ]</span>
          </button>
          <div className="h-7 w-px bg-white/15 hidden sm:block" />
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="font-mono text-base sm:text-lg font-extrabold tracking-wider uppercase text-white">
                DECODER RESULTS
              </h1>
              <span className="px-2 py-0.5 bg-sky-500/20 text-sky-200 border border-sky-400/30 rounded font-mono text-[11px] font-bold uppercase">
                Fleet Scientific Workspace
              </span>
            </div>
            <p className="text-[13px] font-mono text-sky-200/90 mt-0.5">
              {hasBatch
                ? `${totalFloats} Floats · ${successFloats} Successful · ${failedFloats} Failed · ${stoppedFloats} Stopped`
                : "No Active Summary Loaded"}
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2.5 font-mono text-xs">
          {hasBatch && (
            <div className="flex items-center space-x-1.5 px-3 py-1.5 bg-white/10 border border-white/20 rounded font-mono text-[12px]">
              {batch?.email_status === "sent" ? (
                <>
                  <Mail className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span className="text-emerald-300 font-bold">Email sent</span>
                </>
              ) : batch?.email_status === "failed" ? (
                <>
                  <AlertTriangle className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                  <span className="text-rose-300 font-bold" title={batch.email_error || "SMTP delivery error"}>
                    Email failed
                  </span>
                </>
              ) : (
                <>
                  <Mail className="w-3.5 h-3.5 text-slate-300 shrink-0" />
                  <span className="text-slate-300">Not sent</span>
                </>
              )}
            </div>
          )}
          {hasBatch && (
            <button
              onClick={() => setShowConfirmClear(true)}
              className="px-3.5 py-2 bg-white/10 hover:bg-rose-600 text-white border border-white/20 hover:border-rose-500 rounded font-bold text-[13px] transition flex items-center space-x-1.5 shadow-2xs cursor-pointer"
              title="Clear only the visible summary (saved history is preserved)"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>[ Clear Summary ]</span>
            </button>
          )}
          {hasBatch && (
            <button
              onClick={() => setFleetFullScreen((v) => !v)}
              className={
                fleetFullScreen
                  ? "px-3.5 py-2 bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-400/40 rounded font-bold text-[13px] transition flex items-center space-x-1.5 shadow-2xs cursor-pointer"
                  : "px-3.5 py-2 bg-white/10 hover:bg-white/20 text-white border border-white/20 rounded font-bold text-[13px] transition flex items-center space-x-1.5 shadow-2xs cursor-pointer"
              }
              title={
                fleetFullScreen
                  ? "Exit fleet full-screen and restore the exact previous Results layout"
                  : "Expand only the Fleet Results (header, real-world map, map controls, legend, fleet table) to full screen"
              }
            >
              {fleetFullScreen ? (
                <Minimize2 className="w-3.5 h-3.5" />
              ) : (
                <Maximize2 className="w-3.5 h-3.5" />
              )}
              <span>{fleetFullScreen ? "[ Exit Full Screen ]" : "[ Expand Fleet ]"}</span>
            </button>
          )}
          {/* Fleet communication monitoring (Ifremer GDAC upstream). The ONLY
              addition to this page: opens the dedicated Float Status view. */}
          <button
            onClick={() => setActiveView("fleet-status")}
            className="px-3.5 py-2 bg-white/10 hover:bg-white/20 text-white border border-white/20 rounded font-bold text-[13px] transition flex items-center space-x-1.5 shadow-2xs cursor-pointer"
            title="Open fleet communication monitoring (Ifremer GDAC upstream truth)"
          >
            <Satellite className="w-3.5 h-3.5 text-sky-300" />
            <span>[ Float Status ]</span>
          </button>
        </div>
      </header>

      {/* Incoming-data arrivals (NEW DATA) — source-independent, visible
          whether or not a batch summary is loaded: a brand-new float can
          arrive before any decode exists. Discovery is observational only;
          decoding always stays a manual user decision. */}
      <NewArrivalsPanel />

      {!hasBatch ? (
        /* ===================== Empty state ===================== */
        <div className="flex-1 flex flex-col items-center justify-center p-8 text-center font-mono select-none bg-[#F4F7F9]">
          <div className="w-16 h-16 rounded-2xl bg-[#163857]/5 border border-[#163857]/15 flex items-center justify-center text-[#276095] mb-4 shadow-xs">
            <FileSpreadsheet className="w-8 h-8 text-[#276095]" />
          </div>
          <h2 className="text-base font-bold text-slate-900 uppercase tracking-wide">
            Results Summary View Cleared
          </h2>
          <p className="text-xs text-slate-600 font-sans max-w-md mt-1.5 leading-relaxed">
            The current Results summary workspace has been cleared. All decoded NetCDF files,
            Coriolis XML reports, and persistent logs remain safely archived on disk in Run History.
          </p>
          <div className="flex items-center space-x-3 mt-6">
            <button
              onClick={() => setActiveView("decoder")}
              className="px-4 py-2 bg-[#276095] hover:bg-[#1f4e7a] text-white rounded font-bold text-xs transition flex items-center space-x-1.5 shadow-2xs cursor-pointer font-mono"
            >
              <ArrowLeft className="w-4 h-4 text-sky-200" />
              <span>[ Back to Decoder ]</span>
            </button>
            <button
              onClick={() => setRunHistoryModalOpen(true)}
              className="px-4 py-2 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded font-bold text-xs transition flex items-center space-x-1.5 shadow-2xs cursor-pointer font-mono"
            >
              <Database className="w-4 h-4 text-slate-500" />
              <span>[ Open Run History ]</span>
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* ===================== Fleet status instrument panel =============
               One unified scientific readout — exactly the five fleet
               metrics. Large numbers, small technical labels, thin vertical
               separators, restrained ocean/status colors. All values are
               live batch data (never hardcoded). */}
          {/* Summary metrics stay on the normal Results page; full-screen
              Fleet mode is a pure geographic workspace: header + real-world
              map + controls + legend + fleet table. */}
          {!fleetFullScreen && (
          <section
            className="bg-[#f5f8fb] border-b border-slate-200 px-4 sm:px-8 lg:px-10 py-5 shrink-0"
            data-testid="fleet-status-panel"
          >
            <div className="flex items-stretch w-full font-mono">
              <StatusMetric
                label="TOTAL FLOATS"
                value={String(totalFloats)}
                valueClass="text-[#163857]"
                barClass="bg-[#163857]/60"
              />
              <StatusDivider />
              <StatusMetric
                label={batch?.cached_floats ? `SUCCESSFUL (${batch.cached_floats} CACHED)` : "SUCCESSFUL"}
                value={String(successFloats)}
                valueClass="text-emerald-600"
                barClass="bg-emerald-500/60"
              />
              <StatusDivider />
              <StatusMetric
                label="FAILED"
                value={String(failedFloats)}
                valueClass="text-rose-600"
                barClass="bg-rose-500/60"
              />
              <StatusDivider />
              <StatusMetric
                label="PROFILES GENERATED"
                value={String(totalProfilesGen)}
                valueClass="text-[#276095]"
                barClass="bg-[#276095]/60"
              />
              <StatusDivider />
              <StatusMetric
                label="NETCDF OUTPUTS"
                value={String(totalOutputs)}
                valueClass="text-[#1d547d]"
                barClass="bg-[#1d547d]/60"
              />
            </div>
          </section>
          )}

          {/* ===================== Workspace split ===================== */}
          <div className="flex-1 flex overflow-hidden">
            {/* ---- LEFT: Fleet section ----
                 Normal: 46% column with the profile panel beside it; the
                 framed fleet map sits above the fleet table. Full-screen
                 (Expand Fleet): takes the whole viewport width (scientific
                 panel hidden) and the real world map grows to fill the
                 space above the table. */}
            <div
              className={`flex flex-col bg-white overflow-hidden ${
                fleetFullScreen
                  ? "flex-1 min-w-0"
                  : "w-[46%] border-r border-slate-200 shrink-0 min-w-[420px]"
              }`}
            >
              {/* Real geographic world map. A SINGLE map instance serves
                  both modes (it is parked in whichever slot is active via a
                  React portal): the normal Results page shows the framed
                  fleet map above the fleet controls; "Expand Fleet"
                  re-parks the SAME map in the full-screen slot — selection,
                  trajectory and the decoded basemap are preserved. */}
              {fleetFullScreen && (
                <div className="flex flex-col flex-[5] min-h-[260px]">
                  <div ref={setFullMapSlot} className="flex-1 min-h-0 flex flex-col" />
                </div>
              )}

              {/* Normal-mode fleet map slot (framed variant): compact band
                  above the fleet filters/table — the map is present in the
                  default Results view (verification: map on normal page). */}
              {!fleetFullScreen && (
                <div className="flex flex-col h-[300px] min-h-[240px] border-b border-slate-200 shrink-0">
                  <div ref={setNormalMapSlot} className="flex-1 min-h-0 flex flex-col" />
                </div>
              )}

              {/* Filter & search */}
              <div className="p-3 bg-slate-50 border-y border-slate-200 flex items-center justify-between gap-2 shrink-0 font-mono text-[13px]">
                <div className="flex items-center space-x-1">
                  {(
                    [
                      { id: "all", label: `ALL (${items.length})` },
                      { id: "completed", label: `SUCCESS (${items.filter((i) => i.status === "completed").length})` },
                      { id: "error", label: `FAILED (${items.filter((i) => i.status === "error").length})` },
                      { id: "stopped", label: `STOPPED (${items.filter((i) => isTerminalStopped(String(i.status))).length})` },
                    ] as const
                  ).map((tab) => (
                    <button
                      key={tab.id}
                      onClick={() => setStatusFilter(tab.id)}
                      className={`px-3 py-1.5 rounded text-[12px] font-bold transition border cursor-pointer ${
                        statusFilter === tab.id
                          ? "bg-[#276095] text-white border-[#276095] shadow-2xs"
                          : "bg-white text-slate-600 border-slate-200 hover:bg-slate-100"
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
                <div className="relative w-52">
                  <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
                  <input
                    type="text"
                    placeholder="Search WMO / platform..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-8 pr-2.5 py-1.5 bg-white border border-slate-300 rounded text-[13px] font-mono text-slate-900 focus:outline-none focus:ring-1 focus:ring-[#276095]"
                  />
                </div>
              </div>

              {/* Fleet table — primary fleet overview. On the normal
                  Results page it fills the full width and vertical space
                  of the left Fleet section (no small map above it); in
                  full-screen it keeps its own scrolling/filters/search
                  beneath the world map. */}
              <div
                className={`overflow-y-auto p-2.5 select-text font-mono text-[13px] ${
                  fleetFullScreen ? "flex-[3] min-h-[160px]" : "flex-1"
                }`}
              >
                {filteredItems.length === 0 ? (
                  <div className="p-8 text-center text-slate-400 space-y-2">
                    <Layers className="w-7 h-7 mx-auto text-slate-300" />
                    <p>No float records match current filters</p>
                  </div>
                ) : (
                  <table className="w-full text-left border border-slate-200 rounded overflow-hidden">
                    <thead className="bg-slate-100 text-slate-600 font-bold text-[12px] uppercase tracking-wider border-b border-slate-200">
                      <tr>
                        <th className="py-2.5 px-2.5">WMO</th>
                        <th className="py-2.5 px-2">Platform</th>
                        <th className="py-2.5 px-2">Status</th>
                        <th className="py-2.5 px-2 text-center">Cycles</th>
                        <th className="py-2.5 px-2 text-center">Profiles</th>
                        <th className="py-2.5 px-2 text-center">Outputs</th>
                        <th className="py-2.5 px-2 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 bg-white">
                      {filteredItems.map((item) => {
                        const isSelected = item.wmo === activeWmo;
                        const isSucc = item.status === "completed";
                        const isFail = item.status === "error";
                        const isStop = isTerminalStopped(String(item.status));
                        // Primary error = latest meaningful error + "(+N more)"
                        // (unified with the banners and the investigation view).
                        // Each row resolves its OWN run by exact run_id: activeRun
                        // belongs to the selected float, not to this row.
                        const itemRun = item.run_id
                          ? runsCache[item.run_id] ??
                            allRuns.find((r) => r.run_id === item.run_id) ??
                            null
                          : null;
                        const runPrimary =
                          isFail && itemRun && itemRun.wmo === item.wmo
                            ? primaryError(itemRun.errors)
                            : null;
                        const reasonText = item.error_message || runPrimary?.text || "";
                        const reasonExtra = Math.max(
                          runPrimary?.extra ?? 0,
                          (item.error_count ?? 1) - 1,
                        );
                        const reason = reasonText ? reasonText + primaryErrorSuffix(reasonExtra) : "";
                        return (
                          <tr
                            key={item.wmo}
                            onClick={() => setSelectedResultWmo(item.wmo)}
                            className={`cursor-pointer transition-colors ${
                              isSelected
                                ? "bg-amber-50/90 border-l-4 border-l-amber-500"
                                : "hover:bg-slate-50"
                            }`}
                          >
                            <td className="py-2.5 px-2.5 font-bold text-[#276095]">{item.wmo}</td>
                            <td className="py-2.5 px-2 text-slate-600 text-[12.5px]">{item.platform_type || "APEX"}</td>
                            <td className="py-2 px-2">
                              {isSucc && item.cached && (
                                <span
                                  className="px-2 py-1 bg-sky-50 text-sky-800 border border-sky-300 rounded text-[11px] font-bold"
                                  title={`Already successfully decoded today — this batch reused run ${item.run_id} without re-decoding`}
                                >
                                  ✓ CACHED
                                </span>
                              )}
                              {isSucc && !item.cached && (
                                <span className="px-2 py-1 bg-emerald-50 text-emerald-800 border border-emerald-300 rounded text-[11px] font-bold">
                                  ✓ SUCCESS
                                </span>
                              )}
                              {isFail && (
                                <span className="px-2 py-1 bg-rose-50 text-rose-800 border border-rose-300 rounded text-[11px] font-bold">
                                  ✕ FAILED
                                </span>
                              )}
                              {isStop && (
                                <span className="px-2 py-1 bg-amber-50 text-amber-900 border border-amber-300 rounded text-[11px] font-bold">
                                  ⊘ STOPPED
                                </span>
                              )}
                              {!isSucc && !isFail && !isStop && (
                                <span className="px-2 py-1 bg-slate-100 text-slate-500 rounded text-[11px]">
                                  {item.status === "active" ? "● RUNNING" : String(item.status || "PENDING").toUpperCase()}
                                </span>
                              )}
                              {isFail && reason && (
                                <span
                                  className="block text-[11px] text-rose-700/80 mt-0.5 max-w-[200px] truncate"
                                  title={reason}
                                >
                                  {reason}
                                </span>
                              )}
                              {newDataWmos.has(item.wmo) && (
                                <span
                                  data-testid="row-new-data-badge"
                                  className="inline-block mt-1 px-1.5 py-0.5 rounded bg-amber-100 border border-amber-300 text-amber-800 text-[10px] font-bold tracking-wide"
                                  title="New incoming source data detected for this float (see Incoming data arrivals panel)"
                                >
                                  🟡 NEW DATA
                                </span>
                              )}
                            </td>
                            <td className="py-2.5 px-2 text-center text-slate-700 font-semibold">{item.cycles_count}</td>
                            <td className="py-2.5 px-2 text-center font-bold text-sky-800">{item.profiles_count}</td>
                            <td className="py-2.5 px-2 text-center font-bold text-indigo-700">{item.outputs_count}</td>
                            <td className="py-2.5 px-2 text-right">
                              {isSucc && item.run_id ? (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleNavigateToRun(item.run_id!, false, item.error_message ?? null);
                                  }}
                                  className="px-2.5 py-1.5 bg-white hover:bg-[#276095] hover:text-white text-[#276095] border border-slate-300 hover:border-[#276095] rounded text-[11.5px] font-bold transition flex items-center space-x-0.5 ml-auto cursor-pointer shadow-2xs"
                                  title="Open historical decoder run and full logs"
                                >
                                  <span>[ VIEW RUN ]</span>
                                  <ChevronRight className="w-3 h-3" />
                                </button>
                              ) : isFail && item.run_id ? (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleNavigateToRun(item.run_id!, true, item.error_message ?? null);
                                  }}
                                  className="px-2.5 py-1.5 bg-rose-50 hover:bg-rose-600 hover:text-white text-rose-800 border border-rose-300 hover:border-rose-600 rounded text-[11.5px] font-bold transition ml-auto cursor-pointer shadow-2xs"
                                  title="Return to decoder page, restore logs and focus the error event"
                                >
                                  [ INVESTIGATE ERROR ]
                                </button>
                              ) : (
                                <span className="text-slate-300 text-[11px]">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </div>

            {/* ---- RIGHT: Float → Cycle → Profile → QC → Deliverables ----
                 Hidden in fleet full-screen mode (only the fleet section
                 is expanded; the profile/detail panel is excluded). */}
            {!fleetFullScreen && (
            <div className="flex-1 flex flex-col bg-[#F4F7F9] overflow-hidden">
              <div className="flex-1 overflow-y-auto">
                <div className="p-4 space-y-4">
                  {/* ---------- Selected float header ---------- */}
                  <div className="p-3 bg-white border border-slate-200 rounded flex items-center justify-between shrink-0 font-mono">
                    <div className="flex items-center space-x-3 min-w-0">
                      <div className="w-10 h-10 rounded bg-[#276095] flex items-center justify-center text-white font-bold text-sm shadow-2xs shrink-0">
                        {(activeRun?.float_type || activeItem?.platform_type || "FL").slice(0, 2)}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center space-x-2 flex-wrap">
                          <span className="text-lg font-black text-slate-900">WMO {activeWmo}</span>
                          <span className="px-2.5 py-1 bg-sky-50 text-sky-800 border border-sky-200 rounded text-[12px] font-bold">
                            {activeRun?.float_type || activeItem?.platform_type || "APEX"} /{" "}
                            {activeRun?.transmission_type || activeItem?.transmission_type || "ARGOS"}
                          </span>
                          <RunStatusBadge status={(activeRun?.status || activeItem?.status) as NodeStatus} />
                        </div>
                        <p className="text-[13px] text-slate-500 font-sans mt-0.5 truncate">
                          {eezGeometryReady && activeEezStatus ? (
                            <span
                              className="font-mono text-[11.5px] mr-2 text-teal-700"
                              data-testid="eez-float-status"
                              data-eez={activeEezStatus}
                            >
                              EEZ: {activeEezStatus === "INDIAN_EEZ" ? "Indian EEZ" : "Outside Indian EEZ"} ·
                            </span>
                          ) : null}
                          {activeRun?.run_id ? (
                            <>
                              Run ID: <span className="font-mono">{activeRun.run_id}</span> ·{" "}
                            </>
                          ) : (
                            "Run pending · "
                          )}
                          Duration:{" "}
                          {activeRun?.duration_seconds !== undefined ? activeRun.duration_seconds.toFixed(2) : activeItem?.duration_seconds?.toFixed(2) || "—"}
                          s · {activeCycles.length} Cycles Decoded
                        </p>
                      </div>
                    </div>
                    {activeRun?.run_id && (
                      <button
                        onClick={() => handleNavigateToRun(activeRun.run_id!, false, activeItem?.error_message ?? null)}
                        className="px-4 py-2 bg-[#276095] hover:bg-[#1f4e7a] text-white rounded font-bold text-[13px] transition flex items-center space-x-1.5 shadow-2xs cursor-pointer shrink-0"
                        title="Navigate back to live decoder workstation for this run"
                      >
                        <FileCode className="w-3.5 h-3.5 text-sky-200" />
                        <span>[ VIEW DECODER RUN ]</span>
                      </button>
                    )}
                  </div>

                  {/* ---------- Processing history (real run stage states) ---------- */}
                  <div className="px-3.5 py-2.5 bg-white border border-slate-200 rounded flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] font-bold text-slate-500 uppercase tracking-wider shrink-0">
                      Processing history
                    </span>
                    <div className="flex items-center gap-1.5 font-mono text-[11px] overflow-x-auto">
                      {STAGE_CHAIN.map((st, idx) => {
                        const status = activeRun?.stages?.[st.stageId]?.status;
                        return (
                          <React.Fragment key={st.label}>
                            {idx > 0 && <span className="text-slate-300 text-[10px]">→</span>}
                            <StageChip label={st.label} status={status || null} />
                          </React.Fragment>
                        );
                      })}
                    </div>
                  </div>

                  {/* ---------- Error banner (failed float, real error) ---------- */}
                  {activeItem?.status === "error" && (
                    <div className="bg-rose-50 border border-rose-300 rounded p-3 flex items-start justify-between font-mono text-xs text-rose-950 gap-3">
                      <div className="flex items-start space-x-2 min-w-0">
                        <AlertTriangle className="w-4 h-4 text-rose-700 shrink-0 mt-0.5" />
                        <div className="space-y-0.5 min-w-0">
                          <span className="font-bold block">Execution Notice — WMO {activeWmo}</span>
                          <p className="text-rose-900 font-sans text-xs break-words">
                            {(() => {
                              const runPrimary =
                                activeRun?.wmo === activeItem.wmo ? primaryError(activeRun.errors) : null;
                              const text = activeItem.error_message || runPrimary?.text || "";
                              const extra = Math.max(
                                runPrimary?.extra ?? 0,
                                (activeItem.error_count ?? 1) - 1,
                              );
                              return text
                                ? text + primaryErrorSuffix(extra)
                                : "Run recorded an error (see logs).";
                            })()}
                          </p>
                        </div>
                      </div>
                      {activeRun?.run_id && (
                        <button
                          onClick={() => handleNavigateToRun(activeRun.run_id!, true, activeItem?.error_message ?? null)}
                          className="px-2.5 py-1 bg-rose-600 hover:bg-rose-700 text-white rounded text-[11px] font-bold shrink-0 cursor-pointer shadow-2xs"
                        >
                          [ INVESTIGATE ERROR ]
                        </button>
                      )}
                    </div>
                  )}

                  {/* ---------- Cycle selector (real cycles) ---------- */}
                  {activeCycles.length > 0 ? (
                    <div className="p-2 bg-white border border-slate-200 rounded flex items-center justify-between gap-2 font-mono text-xs">
                      <div className="flex items-center space-x-2 min-w-0">
                        <span className="font-bold text-slate-600 text-[12.5px] uppercase shrink-0">Profile cycle:</span>
                        <div className="flex items-center space-x-1 overflow-x-auto">
                          {activeCycles.map((c, idx) => (
                            <button
                              key={`${c.cycle_number}-${idx}`}
                              onClick={() => {
                                setSelectedCycleIndex(idx);
                                setHoveredLevel(null);
                              }}
                              className={`px-2.5 py-1 rounded text-[12.5px] font-bold transition border cursor-pointer shrink-0 ${
                                selectedCycleIndex === idx
                                  ? "bg-[#276095] text-white border-[#276095] shadow-2xs"
                                  : "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100"
                              }`}
                              title={
                                (c.juld_formatted || `Cycle ${c.cycle_number}`) +
                                (c.has_core === false ? " · BGC-only (no core R profile)" : "") +
                                (c.matches_g2_signature ? " · BGC sensor data absent (flagged)" : "")
                              }
                            >
                              C{c.cycle_number}
                              {c.has_core === false && (
                                <span className="ml-1 px-1 py-px rounded text-[9.5px] bg-amber-100 text-amber-900 border border-amber-300 align-middle">
                                  BGC
                                </span>
                              )}
                            </button>
                          ))}
                        </div>
                      </div>
                      {currentCycle && (
                        <span className="text-slate-500 text-[12.5px] font-medium shrink-0">
                          {currentCycle.levels_count} levels ·{" "}
                          {currentCycle.juld_formatted || `Julian day ${currentCycle.juld ?? "—"}`}
                        </span>
                      )}
                    </div>
                  ) : (
                    <div className="p-2 bg-white border border-slate-200 rounded text-center font-mono text-[11px] text-slate-400">
                      {activeRun ? "No decoded cycles for this float in run history" : "Select a float to load its cycles"}
                    </div>
                  )}

                  {/* ---------- Scientific profile plots ---------- */}
                  {ctdSamples.length > 0 ? (
                    <>
                      <div className="flex items-center justify-between gap-2 font-mono text-[13px] text-slate-500">
                        <span className="text-slate-600 font-bold uppercase text-[11.5px] tracking-wider">
                          Oceanographic profiles — real decoded measurements
                        </span>
                        <span className="flex items-center gap-1.5">
                          <button
                            onClick={() => setShowPoints(!showPoints)}
                            className={`px-2.5 py-1 rounded border text-[11px] font-bold transition cursor-pointer ${
                              showPoints
                                ? "bg-white text-slate-700 border-slate-300"
                                : "bg-slate-100 text-slate-400 border-slate-200"
                            }`}
                          >
                            ◉ points
                          </button>
                          <button
                            onClick={() => setShowGrid(!showGrid)}
                            className={`px-2.5 py-1 rounded border text-[11px] font-bold transition cursor-pointer ${
                              showGrid
                                ? "bg-white text-slate-700 border-slate-300"
                                : "bg-slate-100 text-slate-400 border-slate-200"
                            }`}
                          >
                            # grid
                          </button>
                        </span>
                      </div>
                      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                        <ScientificProfileChart
                          paramKey="TEMP"
                          title="PF / Sea temperature"
                          axisLabel="Sea temperature — degree_Celsius"
                          unitShort="°C"
                          unitLong="degree_Celsius"
                          samples={ctdSamples}
                          data={tempData}
                          hoveredLevel={hoveredLevel}
                          onHover={setHoveredLevel}
                          showPoints={showPoints}
                          showGrid={showGrid}
                        />
                        <ScientificProfileChart
                          paramKey="PSAL"
                          title="PF / Practical salinity"
                          axisLabel="Practical salinity — psu"
                          unitShort="psu"
                          unitLong="psu"
                          samples={ctdSamples}
                          data={psalData}
                          hoveredLevel={hoveredLevel}
                          onHover={setHoveredLevel}
                          showPoints={showPoints}
                          showGrid={showGrid}
                        />
                      </div>
                    </>
                  ) : (
                    <div className="p-10 text-center text-slate-400 bg-white border border-slate-200 rounded font-mono">
                      <Waves className="w-8 h-8 mx-auto text-slate-300 mb-2" />
                      <p className="text-xs">
                        {activeRun
                          ? "No CTD physical samples recorded for this float (engineering telemetry only)"
                          : "No profile data yet — run the decoder to produce profiles"}
                      </p>
                    </div>
                  )}

                  {/* ---------- BGC profiles (real BR series, 301 floats only) ----
                      Cards are data-driven: one per sensor parameter that
                      actually carries measurements in this cycle's BR file,
                      labeled with the file's own long names and units.
                      All-fill channels are reported as missing, never
                      plotted as fake data. */}
                  {(bgcCards.length > 0 ||
                    bgcMissingProfiles.length > 0 ||
                    currentCycle?.bgc_source_file) && (
                    <>
                      <div className="flex items-center justify-between gap-2 font-mono text-[13px] text-slate-500">
                        <span className="text-slate-600 font-bold uppercase text-[11.5px] tracking-wider">
                          BGC profiles — {currentCycle?.bgc_source_file || "BR file"}
                          {currentCycle?.bgc_n_prof != null
                            ? ` · N_PROF ${currentCycle.bgc_n_prof}`
                            : ""}
                        </span>
                        {currentCycle && currentCycle.has_core === false && (
                          <span className="px-2 py-0.5 bg-amber-50 text-amber-900 border border-amber-300 rounded text-[11px] font-bold shrink-0">
                            BGC-ONLY CYCLE — NO CORE R PROFILE
                          </span>
                        )}
                      </div>
                      {currentCycle?.matches_g2_signature && (
                        <div className="bg-amber-50 border border-amber-300 rounded p-3 font-mono text-xs text-amber-950">
                          <span className="font-bold">
                            ⚠ BGC sensor data absent in {currentCycle.bgc_source_file || "this BR file"}
                          </span>
                          <span className="font-sans">
                            {" "}— the labeled sensor channels are entirely fill under a
                            non-standard N_PROF {currentCycle.bgc_n_prof} layout, so no BGC
                            series is plotted. Flagged as a suspected 301 writer
                            artifact for review.
                            {currentCycle.has_core === false
                              ? " No core R profile exists for this cycle either (position/time only)."
                              : " Core CTD data is unaffected."}
                          </span>
                        </div>
                      )}
                      {bgcMissingProfiles.map((p) => (
                        <div
                          key={p.profile_index}
                          className="px-3 py-2 bg-slate-50 border border-slate-200 rounded font-mono text-[11.5px] text-slate-500"
                        >
                          Profile {p.profile_index} (
                          {(p.station_parameters || [])
                            .filter((s) => s && !CORE_PARAM_SET.has(s))
                            .join(", ") || "no sensor channels"}
                          ): no measurements in file — not plotted.
                        </div>
                      ))}
                      {bgcCards.length > 0 && (
                        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                          {bgcCards.map((card) => (
                            <ScientificProfileChart
                              key={card.param}
                              paramKey={card.param}
                              title={`BR / ${card.label}`}
                              axisLabel={`${card.param} — ${card.units || "units not published"}`}
                              unitShort={card.units || ""}
                              unitLong={card.units || "units not published"}
                              samples={[]}
                              data={card.data}
                              hoveredLevel={hoveredLevel}
                              onHover={setHoveredLevel}
                              showPoints={showPoints}
                              showGrid={showGrid}
                              genericParam={{ key: card.param, label: card.param }}
                            />
                          ))}
                        </div>
                      )}
                      {bgcTables.length > 0 && (
                        <div className="bg-white border border-slate-200 rounded p-3 font-mono text-xs">
                          <div className="flex items-center space-x-1.5 pb-2 border-b border-slate-100 mb-2">
                            <Activity className="w-4 h-4 text-[#276095]" />
                            <span className="font-bold text-slate-900 text-xs uppercase">
                              BGC measurement records
                              {currentCycle ? ` — cycle C${currentCycle.cycle_number}` : ""}
                            </span>
                            <span className="text-[11.5px] text-slate-400 ml-auto">
                              {bgcTables.length} profile(s)
                            </span>
                          </div>
                          {bgcTables.map((t) => (
                            <div key={t.profileIndex} className="mb-3 last:mb-0">
                              <div className="text-[11.5px] font-bold text-slate-500 uppercase mb-1">
                                Profile {t.profileIndex} — {t.params.join(", ")} ·{" "}
                                {t.rows.length} levels
                              </div>
                              <div className="max-h-64 overflow-auto select-text border border-slate-100 rounded">
                                <table className="w-full text-left">
                                  <thead className="bg-slate-100 text-slate-700 font-bold text-[10.5px] uppercase border-b border-slate-200 sticky top-0">
                                    <tr>
                                      <th className="py-1.5 px-2.5">Level</th>
                                      <th className="py-1.5 px-2.5">PRES (dbar)</th>
                                      {t.params.map((p) => (
                                        <th key={p} className="py-1.5 px-2.5">
                                          {p}
                                          {t.units[p] ? ` (${t.units[p]})` : ""}
                                        </th>
                                      ))}
                                      {t.params.map((p) => (
                                        <th key={`${p}_QC`} className="py-1.5 px-2.5 text-center">
                                          {p} QC
                                        </th>
                                      ))}
                                    </tr>
                                  </thead>
                                  <tbody className="divide-y divide-slate-100">
                                    {t.rows.map((s) => {
                                      const lvl = Number(s.level || 0);
                                      const cid = t.profileIndex * 100000 + lvl;
                                      const pres = s.PRES;
                                      return (
                                        <tr
                                          key={lvl}
                                          className={`hover:bg-slate-50 ${cid === hoveredLevel ? "bg-sky-50/70" : ""}`}
                                          onMouseEnter={() => setHoveredLevel(cid)}
                                          onMouseLeave={() => setHoveredLevel(null)}
                                        >
                                          <td className="py-1.5 px-2.5 text-slate-400 font-bold">{lvl}</td>
                                          <td className="py-1.5 px-2.5 text-sky-800 font-bold">
                                            {typeof pres === "number" ? pres.toFixed(2) : "—"}
                                          </td>
                                          {t.params.map((p) => (
                                            <td key={p} className="py-1.5 px-2.5 text-slate-700 font-medium">
                                              {typeof s[p] === "number"
                                                ? (s[p] as number).toFixed(t.decimals[p])
                                                : "—"}
                                            </td>
                                          ))}
                                          {t.params.map((p) => (
                                            <td key={`${p}_QC`} className="py-1.5 px-2.5 text-center">
                                              <QcChip value={s[`${p}_QC`] as string | number | null | undefined} />
                                            </td>
                                          ))}
                                        </tr>
                                      );
                                    })}
                                  </tbody>
                                </table>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}

                  {/* ---------- RTQC summary (real rtqc_summary records) ---------- */}
                  <div className="bg-white border border-slate-200 rounded p-3 font-mono text-xs">
                    <div className="flex items-center justify-between pb-2 border-b border-slate-100 mb-2">
                      <div className="flex items-center space-x-1.5">
                        <ShieldCheck className="w-4 h-4 text-[#276095]" />
                        <span className="font-bold text-slate-900 text-xs uppercase">
                          RTQC — Argo Table 11 summary
                        </span>
                      </div>
                      <span className="text-[10px] text-slate-400">
                        {rtqc.qcpHex ? `QCP ${rtqc.qcpHex}` : ""}
                        {rtqc.qcpHex && rtqc.qcfHex ? " · " : ""}
                        {rtqc.qcfHex ? `QCF ${rtqc.qcfHex}` : ""}
                      </span>
                    </div>
                    {rtqc.hasRecords ? (
                      <>
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                          <RqcMetric label="APPLICABLE TESTS" value={String(rtqc.applicableCount)} note="run-wide suite" />
                          <RqcMetric label="EXECUTED TESTS" value={String(rtqc.executedCount)} note="this cycle" />
                          <RqcMetric label="FAILED TESTS" value={String(rtqc.failedCount)} tone={rtqc.failedCount > 0 ? "rose" : "slate"} note="this cycle" />
                          <RqcMetric label="FLAGGED MEASUREMENTS" value={String(rtqc.flaggedCount)} note={`${rtqc.flaggedAll} run-wide`} />
                        </div>
                        {rtqc.executedCount > 0 && (
                          <div className="mt-2 pt-2 border-t border-slate-100">
                            <div className="text-[11.5px] font-bold text-slate-500 uppercase mb-1">
                              Tests on cycle C{currentCycle?.cycle_number ?? "—"}
                            </div>
                            <div className="flex flex-wrap gap-1">
                              {rtqc.doneList.map((t) => (
                                <span
                                  key={t}
                                  className={`px-2 py-1 rounded text-[11px] border ${
                                    rtqc.failedList.includes(t)
                                      ? "bg-rose-50 text-rose-800 border-rose-200"
                                      : "bg-emerald-50 text-emerald-800 border-emerald-200"
                                  }`}
                                  title={TABLE11[t] || `Table 11 test #${t}`}
                                >
                                  {rtqc.failedList.includes(t) ? "✕" : "✓"} T{t} {TABLE11[t] || ""}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </>
                    ) : (
                      <p className="text-slate-400 text-[12.5px]">
                        No RTQC records in this run's data for the selected cycle.
                      </p>
                    )}
                  </div>

                  {/* ---------- CTD measurement records ---------- */}
                  <div className="bg-white border border-slate-200 rounded p-3 font-mono text-xs">
                    <div className="flex items-center space-x-1.5 pb-2 border-b border-slate-100 mb-2">
                      <Activity className="w-4 h-4 text-[#276095]" />
                      <span className="font-bold text-slate-900 text-xs uppercase">
                        CTD measurement records
                        {currentCycle ? ` — cycle C${currentCycle.cycle_number}` : ""}
                      </span>
                      <span className="text-[11.5px] text-slate-400 ml-auto">{ctdSamples.length} levels</span>
                    </div>
                    {ctdSamples.length === 0 ? (
                      <p className="text-slate-400 text-[12.5px]">No profile measurements recorded.</p>
                    ) : (
                      <div className="max-h-64 overflow-y-auto select-text">
                        <table className="w-full text-left">
                          <thead className="bg-slate-100 text-slate-700 font-bold text-[10.5px] uppercase border-b border-slate-200 sticky top-0">
                            <tr>
                              <th className="py-1.5 px-2.5">Level</th>
                              <th className="py-1.5 px-2.5">PRES (dbar)</th>
                              <th className="py-1.5 px-2.5">TEMP (°C)</th>
                              <th className="py-1.5 px-2.5">PSAL (psu)</th>
                              <th className="py-1.5 px-2.5">CNDC (S/m)</th>
                              <th className="py-1.5 px-2.5 text-center">PRES QC</th>
                              <th className="py-1.5 px-2.5 text-center">TEMP QC</th>
                              <th className="py-1.5 px-2.5 text-center">PSAL QC</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {ctdSamples.map((s) => (
                              <tr
                                key={s.level}
                                className={`hover:bg-slate-50 ${s.level === hoveredLevel ? "bg-sky-50/70" : ""}`}
                                onMouseEnter={() => setHoveredLevel(s.level)}
                                onMouseLeave={() => setHoveredLevel(null)}
                              >
                                <td className="py-1.5 px-2.5 text-slate-400 font-bold">{s.level}</td>
                                <td className="py-1.5 px-2.5 text-sky-800 font-bold">
                                  {s.PRES !== null ? s.PRES.toFixed(2) : "—"}
                                </td>
                                <td className="py-1.5 px-2.5 text-rose-800 font-medium">
                                  {s.TEMP !== null ? s.TEMP.toFixed(3) : "—"}
                                </td>
                                <td className="py-1.5 px-2.5 text-cyan-800 font-medium">
                                  {s.PSAL !== null ? s.PSAL.toFixed(3) : "—"}
                                </td>
                                <td className="py-1.5 px-2.5 text-indigo-800">
                                  {s.CNDC !== null ? s.CNDC.toFixed(3) : "—"}
                                </td>
                                <td className="py-1.5 px-2.5 text-center">
                                  <QcChip value={s.PRES_QC} />
                                </td>
                                <td className="py-1.5 px-2.5 text-center">
                                  <QcChip value={s.TEMP_QC} />
                                </td>
                                <td className="py-1.5 px-2.5 text-center">
                                  <QcChip value={s.PSAL_QC} />
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>

                  {/* ---------- Deliverables ---------- */}
                  <div className="bg-white border border-slate-200 rounded p-3 font-mono text-xs">
                    <div className="flex items-center space-x-1.5 pb-2 border-b border-slate-100 mb-2">
                      <Database className="w-4 h-4 text-[#276095]" />
                      <span className="font-bold text-slate-900 text-xs uppercase">
                        Generated deliverables
                      </span>
                      <span className="text-[10px] text-slate-400 ml-auto">
                        {activeRun?.output_files?.length || 0} files
                      </span>
                    </div>
                    {!activeRun?.output_files || activeRun.output_files.length === 0 ? (
                      <p className="text-slate-400 text-[12.5px]">
                        No output deliverables generated yet for this float.
                      </p>
                    ) : (
                      <div className="overflow-x-auto select-text">
                        <table className="w-full text-left">
                          <thead className="bg-slate-100 text-slate-700 font-bold text-[10.5px] uppercase border-b border-slate-200">
                            <tr>
                              <th className="py-2 px-2.5">File</th>
                              <th className="py-2 px-2">Type</th>
                              <th className="py-2.5 px-2">Status</th>
                              <th className="py-2 px-2 text-right">Size</th>
                              <th className="py-2 px-2">Dimensions</th>
                              <th className="py-2 px-2 text-center">Variables</th>
                              <th className="py-2 px-2.5">SHA-256</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {activeRun.output_files.map((file) => (
                              <tr key={file.filename} className="hover:bg-slate-50">
                                <td className="py-2 px-2.5 font-bold text-sky-800 truncate max-w-[220px]" title={file.filepath}>
                                  {file.filename}
                                </td>
                                <td className="py-2 px-2">
                                  <span className="px-2 py-0.5 uppercase bg-slate-100 text-slate-700 border border-slate-200 rounded text-[11px]">
                                    {file.category}
                                  </span>
                                </td>
                                <td className="py-2 px-2">
                                  <span className="text-emerald-700 font-bold text-[10px]">✓ generated</span>
                                </td>
                                <td className="py-2 px-2 text-right text-slate-600 font-medium whitespace-nowrap">
                                  {fmtBytes(file.filesize_bytes)}
                                </td>
                                <td
                                  className="py-2 px-2 text-[11.5px] text-slate-500 max-w-[200px] truncate"
                                  title={Object.entries(file.dimensions || {})
                                    .map(([k, v]) => `${k}=${v}`)
                                    .join(", ")}
                                >
                                  {Object.entries(file.dimensions || {})
                                    .sort((a, b) => (b[1] as number) - (a[1] as number))
                                    .slice(0, 3)
                                    .map(([k, v]) => `${k}:${v}`)
                                    .join(" · ")}
                                  {Object.keys(file.dimensions || {}).length > 3
                                    ? ` +${Object.keys(file.dimensions || {}).length - 3}`
                                    : ""}
                                </td>
                                <td className="py-2 px-2 text-center text-indigo-700 font-bold">
                                  {Array.isArray(file.variables) ? file.variables.length : 0}
                                </td>
                                <td className="py-2 px-2.5 flex items-center gap-1">
                                  <code className="text-[11.5px] text-emerald-700">
                                    {file.checksum_sha256 ? `${file.checksum_sha256.slice(0, 12)}…` : "—"}
                                  </code>
                                  {file.checksum_sha256 && (
                                    <button
                                      onClick={() => handleCopyHash(file.checksum_sha256!)}
                                      className="p-1 hover:bg-slate-200 text-slate-400 hover:text-slate-800 rounded cursor-pointer"
                                      title="Copy full SHA-256"
                                    >
                                      {copiedHash === file.checksum_sha256 ? (
                                        <Check className="w-3 h-3 text-emerald-600" />
                                      ) : (
                                        <Copy className="w-3 h-3" />
                                      )}
                                    </button>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

/* ---------------------------------------------------------------------- */
/* Small presentational helpers (no data logic — all props are real data)  */
/* ---------------------------------------------------------------------- */

/** Thin scientific divider between readouts (hidden on very small widths). */
function StatusDivider() {
  return (
    <div
      className="w-px self-stretch my-1 bg-slate-200/90 hidden sm:block shrink-0"
      aria-hidden="true"
    />
  );
}

/**
 * One readout cell of the fleet-status instrument panel: the metric number
 * is the primary element (large, tabular), the label is small and technical,
 * and a short status color bar ties it to the oceanographic palette.
 */
function StatusMetric({
  label,
  value,
  valueClass,
  barClass,
}: {
  label: string;
  value: string;
  valueClass: string;
  barClass: string;
}) {
  return (
    <div className="flex-1 basis-0 min-w-0 text-center px-1.5 sm:px-3">
      <p
        className={`text-[30px] sm:text-[36px] md:text-[42px] leading-none font-black tabular-nums tracking-tight ${valueClass}`}
      >
        {value}
      </p>
      <p className="mt-2 text-[10.5px] sm:text-[11.5px] md:text-[12.5px] font-bold uppercase tracking-[0.14em] sm:tracking-[0.18em] text-slate-500 leading-tight">
        {label}
      </p>
      <span
        className={`mt-2.5 block mx-auto h-[3px] w-7 sm:w-9 rounded-full ${barClass}`}
        aria-hidden="true"
      />
    </div>
  );
}

function RunStatusBadge({ status }: { status: NodeStatus | null | undefined }) {
  const st = (status || "pending") as string;
  if (st === "completed")
    return (
      <span className="px-2 py-1 bg-emerald-50 text-emerald-800 border border-emerald-300 rounded text-[11.5px] font-bold">
        ✓ SUCCESS
      </span>
    );
  if (st === "error")
    return (
      <span className="px-2 py-1 bg-rose-50 text-rose-800 border border-rose-300 rounded text-[11.5px] font-bold">
        ✕ FAILED
      </span>
    );
  if (st === "stopped" || st === "cancelled")
    return (
      <span className="px-2 py-1 bg-amber-50 text-amber-900 border border-amber-300 rounded text-[11.5px] font-bold">
        ⊘ STOPPED
      </span>
    );
  if (st === "active")
    return (
      <span className="px-2 py-0.5 bg-sky-50 text-sky-800 border border-sky-200 rounded text-[10.5px] font-bold animate-pulse">
        ● RUNNING
      </span>
    );
  return (
    <span className="px-2 py-0.5 bg-slate-100 text-slate-500 border border-slate-200 rounded text-[10.5px] font-bold">
      PENDING
    </span>
  );
}

/** A milestone of the processing chain; status comes from the real run stages. */
function StageChip({ label, status }: { label: string; status: string | null }) {
  const st = normStatus(status || "");
  if (st === "completed")
    return (
      <span className="flex items-center gap-1 px-2 py-1 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded text-[11.5px] font-bold shrink-0">
        <CheckCircle2 className="w-3 h-3" /> {label}
      </span>
    );
  if (st === "active")
    return (
      <span className="flex items-center gap-1 px-2 py-1 bg-sky-50 text-sky-800 border border-sky-200 rounded text-[11.5px] font-bold shrink-0">
        <span className="w-2 h-2 rounded-full bg-sky-500 animate-pulse" /> {label}
      </span>
    );
  if (st === "error")
    return (
      <span className="flex items-center gap-1 px-1.5 py-0.5 bg-rose-50 text-rose-800 border border-rose-200 rounded text-[10px] font-bold shrink-0">
        <XCircle className="w-3 h-3" /> {label}
      </span>
    );
  return (
    <span className="flex items-center gap-1 px-1.5 py-0.5 bg-slate-50 text-slate-400 border border-slate-200 rounded text-[10px] font-bold shrink-0">
      {label}
    </span>
  );
}

function RqcMetric({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: "rose" | "slate";
}) {
  return (
    <div className={`p-2 border rounded ${tone === "rose" ? "bg-rose-50/60 border-rose-200" : "bg-slate-50 border-slate-200"}`}>
      <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block">{label}</span>
      <span className={`text-base font-black ${tone === "rose" ? "text-rose-700" : "text-slate-900"}`}>{value}</span>
      {note && <span className="text-[9px] text-slate-400 block mt-0.5">{note}</span>}
    </div>
  );
}

function QcChip({ value }: { value: string | number | null | undefined }) {
  const label = qcLabel(value);
  const s = value === null || value === undefined ? null : String(value);
  const good = s === "1" || s === "0";
  const bad = s === "3" || s === "4";
  return (
    <span
      className={`px-2 py-1 rounded text-[11px] font-bold border whitespace-nowrap inline-block ${
        bad
          ? "bg-amber-50 text-amber-800 border-amber-300"
          : good
          ? "bg-emerald-50 text-emerald-800 border-emerald-200"
          : "bg-slate-50 text-slate-500 border-slate-200"
      }`}
      title={label}
    >
      {label}
    </span>
  );
}
