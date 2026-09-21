import React from "react";
import {
  Play,
  RotateCcw,
  Activity,
  Layers,
  FileCode,
  ShieldCheck,
  CheckCircle2,
  Clock,
  Radio,
  FileSpreadsheet,
  Square,
  History,
  Ban,
  Sparkles,
  RefreshCw,
} from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";

export const Header: React.FC = () => {
  const {
    presets,
    selectedPreset,
    selectPreset,
    customWmo,
    setCustomWmo,
    currentRun,
    isRunning,
    isStopping,
    batchRunning,
    timerSeconds,
    startDecode,
    startDecodeAll,
    stopDecode,
    resetRun,
    wsConnected,
    setRtqcModalOpen,
    setOutputModalOpen,
    setFlowchartModalOpen,
    setBatchSummaryModalOpen,
    setRunHistoryModalOpen,
    currentBatch,
    setActiveView,
    ingestionStatus,
  } = useDecoderStore();

  const isAnyRunning = isRunning || batchRunning;

  const handlePresetChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const wmo = parseInt(e.target.value, 10);
    const found = presets.find((p) => p.wmo === wmo);
    if (found) {
      selectPreset(found);
    }
  };

  const handleCustomWmoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseInt(e.target.value, 10);
    if (!isNaN(val)) {
      setCustomWmo(val);
    }
  };

  return (
    <header className="h-14 bg-white border-b border-slate-200 px-3.5 flex items-center justify-between select-none shrink-0 shadow-xs">
      {/* Left: Brand & Mission Control Title */}
      <div className="flex items-center space-x-3">
        <div className="flex items-center space-x-2.5">
          <div className="w-8 h-8 bg-[#276095] rounded flex items-center justify-center text-white font-bold text-xs shadow-2xs">
            IN
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-bold text-sm tracking-tight text-slate-900 font-mono">
                INCOIS ARPY DECODER WORKSTATION
              </span>
              <span className="text-[10px] font-mono px-1.5 py-0.2 bg-[#276095]/10 text-[#276095] border border-[#276095]/20 rounded font-bold">
                ADMT v3.1
              </span>
            </div>
          </div>
        </div>

        <div className="h-6 w-px bg-slate-200 mx-1 hidden sm:block" />

        {/* Live Backend Connection Indicator */}
        <div className="hidden md:flex items-center space-x-1.5 text-xs font-mono">
          <span
            className={`w-2 h-2 rounded-full ${
              wsConnected ? "bg-emerald-500" : "bg-rose-500 animate-ping"
            }`}
          />
          <span className="text-[11px] text-slate-600 font-medium">
            {wsConnected ? "STREAM ACTIVE" : "DISCONNECTED"}
          </span>
        </div>
      </div>

      {/* Center: Operational Actions & Target Selection */}
      <div className="flex items-center space-x-2">
        {/* Float Selector */}
        <div className="flex items-center space-x-1.5 bg-slate-50 border border-[#276095]/30 rounded px-2 py-1 focus-within:border-[#276095]">
          <span className="text-[11px] font-bold text-[#276095] font-mono">FLOAT:</span>
          <select
            value={selectedPreset?.wmo || 2901304}
            onChange={handlePresetChange}
            disabled={isAnyRunning}
            aria-label="Select Float Preset"
            className="bg-transparent text-xs font-bold text-slate-900 border-none outline-none focus:ring-0 cursor-pointer disabled:opacity-50 max-w-[190px] truncate"
          >
            {presets.map((p) => (
              <option key={p.wmo} value={p.wmo} className="bg-white text-slate-900">
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <div className="hidden lg:flex items-center space-x-1 bg-slate-50 border border-slate-300 rounded px-2 py-1">
          <span className="text-[11px] font-mono text-slate-600 font-bold">WMO:</span>
          <input
            type="number"
            value={customWmo || ""}
            onChange={handleCustomWmoChange}
            disabled={isAnyRunning}
            placeholder="WMO ID"
            className="w-18 bg-transparent text-xs font-mono font-bold text-[#276095] border-none outline-none focus:ring-0 disabled:opacity-50"
          />
        </div>

        {/* 1. Single Float Decode Button (Unchanged) */}
        <button
          onClick={startDecode}
          disabled={isAnyRunning}
          className={`flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-bold font-mono tracking-wide transition border shadow-xs cursor-pointer ${
            isAnyRunning
              ? "bg-slate-100 text-slate-400 border-slate-200 cursor-not-allowed"
              : "bg-[#276095] hover:bg-[#1f4e7a] text-white border-[#276095]"
          }`}
          title="Decode selected float telemetry with real backend"
        >
          <Play className={`w-3.5 h-3.5 ${isRunning && !batchRunning ? "animate-spin" : "fill-current"}`} />
          <span>{isRunning && !batchRunning ? "DECODING..." : "DECODE FLOAT"}</span>
        </button>

        {/* 2. Decode All Today's Floats Button — floats already successfully
            decoded today are carried over as COMPLETED/CACHED (not re-decoded);
            failed / stopped / incomplete floats are always decoded. */}
        <button
          onClick={() => startDecodeAll(false)}
          disabled={isAnyRunning}
          className={`flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-bold font-mono tracking-wide transition border shadow-xs cursor-pointer ${
            isAnyRunning
              ? "bg-slate-100 text-slate-400 border-slate-200 cursor-not-allowed"
              : "bg-indigo-700 hover:bg-indigo-800 text-white border-indigo-700"
          }`}
          title="Batch decode today's floats. Skips floats already successfully decoded today (reused as CACHED; failed/stopped floats are retried). When everything is already processed, shows an 'already complete' notice with View Results / Re-run All instead of starting a duplicate batch"
        >
          <Layers className={`w-3.5 h-3.5 ${batchRunning ? "animate-spin" : ""}`} />
          <span>{batchRunning ? "BATCH RUNNING..." : "DECODE ALL TODAY'S FLOATS"}</span>
        </button>

        {/* 2b. RE-RUN ALL — explicit, deliberate full reprocessing of every
            float today, bypassing the cached-success skip (fresh batch + fresh run ids). */}
        <button
          onClick={() => startDecodeAll(true)}
          disabled={isAnyRunning}
          className={`flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-bold font-mono tracking-wide transition border shadow-xs cursor-pointer ${
            isAnyRunning
              ? "bg-slate-100 text-slate-400 border-slate-200 cursor-not-allowed"
              : "bg-amber-600 hover:bg-amber-700 text-white border-amber-700"
          }`}
          title="Deliberately re-decode EVERY float again today, even those already successfully decoded (bypasses CACHED reuse; creates a fresh batch)"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>RE-RUN ALL</span>
        </button>

        {/* 3. Stop Decode Button (Enabled whenever decoding is running or stopping) */}
        {isAnyRunning || isStopping ? (
          <button
            onClick={stopDecode}
            disabled={isStopping}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded border text-xs font-mono font-bold transition shadow-xs ${
              isStopping
                ? "bg-amber-600 border-amber-700 text-white cursor-wait opacity-90"
                : "bg-rose-600 hover:bg-rose-700 text-white border-rose-700 animate-pulse cursor-pointer"
            }`}
            title="Safely stop the active decoding execution"
          >
            <Square className={`w-3.5 h-3.5 fill-current ${isStopping ? "animate-spin" : ""}`} />
            <span>{isStopping ? "STOPPING..." : "STOP DECODE"}</span>
          </button>
        ) : (
          <button
            onClick={resetRun}
            className="flex items-center space-x-1 px-2.5 py-1.5 rounded bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 text-xs font-mono font-semibold transition cursor-pointer"
            title="Reset Pipeline View"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>RESET</span>
          </button>
        )}
      </div>

      {/* Right: Status Pill & Summary/History Modal Triggers */}
      <div className="flex items-center space-x-2">
        {/* Data-Source Pill: honest source identity. FTP CONNECTED is only
            ever shown after a real, successful FTP session; the local
            development source is always labelled as such. NEW DATA count
            reflects normalized arrivals from the ingestion registry. */}
        {(() => {
          const st = ingestionStatus;
          const isFtp = st?.mode === "ftp";
          const base = "flex items-center space-x-1.5 rounded px-2.5 py-1 text-[11px] font-mono border";
          let cls = "bg-slate-50 border-slate-200 text-slate-600";
          let dot = "bg-slate-400";
          let label = "LOCAL";
          let sub = st?.test_mode ? "DEV SOURCE" : "";
          if (isFtp) {
            if (!st?.configured) {
              label = "FTP NOT CONFIGURED";
            } else if (st.connected) {
              label = "FTP CONNECTED";
              cls = "bg-emerald-50 border-emerald-300 text-emerald-900 shadow-2xs";
              dot = "bg-emerald-600";
            } else {
              label = "FTP NOT CONNECTED";
              cls = "bg-amber-50 border-amber-300 text-amber-900 shadow-2xs";
              dot = "bg-amber-500 animate-pulse";
            }
            sub = "";
          } else if (st?.connected) {
            cls = "bg-sky-50 border-sky-300 text-sky-900 shadow-2xs";
            dot = "bg-sky-600";
          }
          return (
            <div
              data-testid="data-source-pill"
              className={`${base} ${cls}`}
              title={
                st?.last_error
                  ? `${st.detail || "Ingestion source"} — last scan error: ${st.last_error}`
                  : st?.detail || "Ingestion source"
              }
            >
              <span className={`w-1.5 h-1.5 rounded-full inline-block ${dot}`} />
              <span className="font-bold">{label}</span>
              {sub && <span className="text-[9px] uppercase opacity-75 font-bold">({sub})</span>}
              {(st?.new_arrivals ?? 0) > 0 && (
                <span
                  data-testid="new-data-count"
                  className="ml-1 px-1.5 py-0.2 rounded bg-amber-100 border border-amber-300 text-amber-800 font-bold"
                  title={`${st!.new_arrivals} float(s) with newly arrived source data (NEW DATA) — see Fleet list`}
                >
                  NEW DATA: {st!.new_arrivals}
                </span>
              )}
            </div>
          );
        })()}

        {/* Status Pill */}
        <div
          className={`flex items-center space-x-2 rounded px-2.5 py-1 text-xs font-mono border ${
            isStopping
              ? "bg-amber-100 border-amber-400 text-amber-950 shadow-2xs"
              : isAnyRunning
              ? "bg-amber-50 border-amber-300 text-amber-950 shadow-2xs"
              : currentRun?.status === "completed"
              ? "bg-emerald-50 border-emerald-300 text-emerald-900 shadow-2xs"
              : currentRun?.status === "stopped" || currentRun?.status === "cancelled"
              ? "bg-amber-50 border-amber-300 text-amber-900 shadow-2xs"
              : currentRun?.status === "error"
              ? "bg-rose-50 border-rose-300 text-rose-900 shadow-2xs"
              : "bg-slate-50 border-slate-200 text-slate-600"
          }`}
        >
          <span className="text-[10px] opacity-75 uppercase font-bold">STATUS:</span>
          <span className="font-bold text-[11px] uppercase flex items-center space-x-1.5">
            <span
              className={`w-1.5 h-1.5 rounded-full inline-block ${
                isStopping
                  ? "bg-amber-600 animate-ping"
                  : isAnyRunning
                  ? "bg-amber-500 animate-pulse"
                  : currentRun?.status === "completed"
                  ? "bg-emerald-600"
                  : currentRun?.status === "stopped" || currentRun?.status === "cancelled"
                  ? "bg-amber-600"
                  : currentRun?.status === "error"
                  ? "bg-rose-600"
                  : "bg-slate-400"
              }`}
            />
            <span>
              {isStopping
                ? "STOPPING..."
                : isAnyRunning
                ? `ACTIVE (${timerSeconds.toFixed(1)}s)`
                : currentRun?.status === "completed"
                ? `SUCCESS (${currentRun.duration_seconds.toFixed(2)}s)`
                : currentRun?.status === "stopped" || currentRun?.status === "cancelled"
                ? `STOPPED (${currentRun.duration_seconds.toFixed(2)}s)`
                : currentRun?.status === "error"
                ? "FAILED"
                : "STANDBY"}
            </span>
          </span>
        </div>

        {/* Decode Results / Summary Workspace Button */}
        <button
          onClick={() => setActiveView("results")}
          className="px-2.5 py-1 bg-sky-50 hover:bg-sky-100 text-[#276095] border border-sky-300 rounded text-xs font-mono font-bold transition flex items-center space-x-1 shadow-2xs cursor-pointer"
          title="Open Dedicated Results & Oceanographic Analysis Workspace"
        >
          <FileSpreadsheet className="w-3.5 h-3.5 text-[#276095]" />
          <span className="hidden sm:inline">VIEW RESULTS</span>
        </button>

        {/* Run History Button */}
        <button
          onClick={() => setRunHistoryModalOpen(true)}
          className="px-2.5 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-xs font-mono font-bold transition flex items-center space-x-1 shadow-2xs cursor-pointer"
          title="Open Persistent Run History"
        >
          <History className="w-3.5 h-3.5 text-slate-600" />
          <span className="hidden sm:inline">HISTORY</span>
        </button>

        {/* Flowchart Architecture Button */}
        <button
          onClick={() => setFlowchartModalOpen(true)}
          className="px-2 py-1 bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 rounded text-xs font-mono font-bold transition flex items-center space-x-1"
          title="View Decoder Architecture Flowchart"
        >
          <FileCode className="w-3.5 h-3.5 text-slate-600" />
        </button>
      </div>
    </header>
  );
};
