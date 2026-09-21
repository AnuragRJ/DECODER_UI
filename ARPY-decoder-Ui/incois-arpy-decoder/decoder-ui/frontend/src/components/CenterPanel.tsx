import React, { useRef, useEffect, useState } from "react";
import {
  Terminal,
  Search,
  Filter,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  FileCode,
  ShieldCheck,
  ChevronRight,
  ArrowDown,
  Ban,
  ChevronDown,
  ChevronUp,
  Code2,
  Trash2,
  X,
  AlertCircle,
} from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";
import { LiveEvent } from "../types";
import { stripAnsi } from "../utils/ansi";
import { primaryError, primaryErrorSuffix } from "../utils/investigate";
import { ErrorInvestigationPanel } from "./ErrorInvestigationPanel";

export const CenterPanel: React.FC = () => {
  const {
    events,
    selectedEvent,
    setSelectedEvent,
    logFilter,
    setLogFilter,
    logSearch,
    setLogSearch,
    autoScroll,
    setAutoScroll,
    currentRun,
    isRunning,
    batchRunning,
    currentBatch,
    selectBatchFloat,
    clearLogs,
    investigationRunId,
    investigationMissing,
    activeRunId,
  } = useDecoderStore();

  const scrollRef = useRef<HTMLDivElement>(null);
  const selectedEventRef = useRef<HTMLDivElement>(null);
  const [expandedDetails, setExpandedDetails] = useState<Record<string, boolean>>({});
  const [showConfirmClear, setShowConfirmClear] = useState(false);

  // Auto-scroll on new events if autoScroll enabled
  useEffect(() => {
    if (autoScroll && scrollRef.current && !selectedEvent) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events, autoScroll, selectedEvent]);

  // Scroll to selected event when selectedEvent changes
  useEffect(() => {
    if (selectedEvent && selectedEventRef.current) {
      selectedEventRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [selectedEvent?.id]);

  const toggleInlineDetails = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedDetails((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  // Filter events
  const filteredEvents = events.filter((e) => {
    if (logFilter === "rtqc" && e.level !== "rtqc" && e.stage !== "RTQC" && e.stage !== "CROSS_CYCLE_RTQC") return false;
    if (logFilter === "errors" && e.level !== "error" && e.status !== "error") return false;
    if (logFilter === "outputs" && e.stage !== "OUTPUT") return false;

    if (logSearch) {
      const q = logSearch.toLowerCase();
      const matchMsg = e.message?.toLowerCase().includes(q);
      const matchStage = e.stage?.toLowerCase().includes(q);
      const matchPy = e.python_file?.toLowerCase().includes(q);
      const matchOp = e.operation?.toLowerCase().includes(q);
      const matchWhat = e.what_happened?.toLowerCase().includes(q);
      if (!matchMsg && !matchStage && !matchPy && !matchOp && !matchWhat) return false;
    }
    return true;
  });

  const getEventBadge = (evt: LiveEvent) => {
    if (evt.level === "error" || evt.status === "error") {
      return (
        <span className="px-2 py-0.5 bg-rose-100 text-rose-800 border border-rose-300 rounded font-mono font-bold text-[10px] uppercase tracking-wider">
          ERROR
        </span>
      );
    }
    if (evt.level === "warning") {
      return (
        <span className="px-2 py-0.5 bg-amber-100 text-amber-900 border border-amber-300 rounded font-mono font-bold text-[10px] uppercase tracking-wider">
          NOTICE
        </span>
      );
    }
    if (evt.level === "success" || evt.status === "completed") {
      return (
        <span className="px-2 py-0.5 bg-emerald-50 text-emerald-800 border border-emerald-300 rounded font-mono font-bold text-[10px] uppercase tracking-wider">
          SUCCESS
        </span>
      );
    }
    if (evt.level === "rtqc" || evt.stage === "RTQC") {
      return (
        <span className="px-2 py-0.5 bg-amber-50 text-amber-900 border border-amber-300 rounded font-mono font-bold text-[10px] uppercase tracking-wider">
          RTQC
        </span>
      );
    }
    return (
      <span className="px-2 py-0.5 bg-sky-50 text-sky-800 border border-sky-200 rounded font-mono font-bold text-[10px] uppercase tracking-wider">
        INFO
      </span>
    );
  };

  const getEventGlyph = (evt: LiveEvent) => {
    if (evt.level === "error" || evt.status === "error") {
      return <span className="text-rose-600 font-bold shrink-0">✕</span>;
    }
    if (evt.level === "warning") {
      return <span className="text-amber-600 font-bold shrink-0">⚠</span>;
    }
    if (evt.level === "success" || evt.status === "completed") {
      return <span className="text-emerald-600 font-bold shrink-0">✓</span>;
    }
    return <span className="text-sky-700 font-bold shrink-0">ℹ</span>;
  };

  const isStopped = currentRun?.status === "stopped" || currentRun?.status === "cancelled";
  const isFailed = currentRun?.status === "error";

  // Check if viewing a previous float while batch is actively decoding another float
  const isViewingHistoricalWhileBatchRunning =
    batchRunning &&
    currentBatch?.running_wmo &&
    currentRun?.wmo &&
    currentRun.wmo !== currentBatch.running_wmo;

  const handleExecuteClear = () => {
    clearLogs();
    setShowConfirmClear(false);
  };

  // Investigate entries replace the log with the interactive Error Detail
  // (same column, same wrapper) — WHAT first, log one click away. The
  // run-not-started variant has no active run, so it opens on its own flag.
  const investigationOpen =
    investigationRunId !== null &&
    (investigationRunId === activeRunId || investigationMissing !== null);
  if (investigationOpen) {
    return (
      <section className="w-[51.5%] flex-1 bg-[#F4F7F9] border-r border-slate-200 flex flex-col h-full overflow-hidden select-none text-slate-800 min-w-0 relative">
        <ErrorInvestigationPanel />
      </section>
    );
  }

  return (
    <section className="w-[51.5%] flex-1 bg-[#F4F7F9] border-r border-slate-200 flex flex-col h-full overflow-hidden select-none text-slate-800 min-w-0 relative">
      {/* Confirmation Dialog Overlay for Clear Logs */}
      {showConfirmClear && (
        <div className="absolute inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in duration-100">
          <div className="bg-white rounded-lg shadow-2xl border border-slate-200 w-full max-w-sm p-4 space-y-3 font-mono select-none">
            <div className="flex items-start space-x-2.5">
              <div className="w-9 h-9 rounded-full bg-amber-100 border border-amber-300 flex items-center justify-center text-amber-700 shrink-0">
                <AlertCircle className="w-4 h-4" />
              </div>
              <div className="space-y-1">
                <h3 className="font-bold text-xs text-slate-900">
                  Clear Decoder Logs View?
                </h3>
                <p className="text-xs text-slate-600 font-sans leading-relaxed">
                  Clear the current view? Your saved run history will not be deleted.
                </p>
              </div>
            </div>

            <div className="p-2 bg-slate-50 border border-slate-200 rounded text-[10.5px] text-slate-500 font-sans">
              ℹ If decoding is currently active, new backend events will continue streaming normally.
            </div>

            <div className="flex items-center justify-end space-x-2 pt-1 border-t border-slate-100">
              <button
                onClick={() => setShowConfirmClear(false)}
                className="px-3 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-xs font-bold transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleExecuteClear}
                className="px-3 py-1 bg-rose-600 hover:bg-rose-700 text-white font-bold rounded text-xs transition flex items-center space-x-1 shadow-2xs cursor-pointer"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>[ Clear Logs ]</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Panel Header */}
      <div className="h-11 px-4 border-b border-slate-200 bg-[#F4F7F9] flex items-center justify-between shrink-0">
        <div className="flex items-center space-x-2 font-mono text-xs font-bold text-slate-800 truncate">
          <Terminal className="w-4 h-4 text-[#276095] shrink-0" />
          <span className="uppercase tracking-wider truncate">
            DECODING EXECUTION LOG {currentRun?.wmo ? `(WMO ${currentRun.wmo})` : ""}
          </span>
          {currentRun?.run_id && (
            <span
              className="text-slate-400 font-mono text-[11px] font-normal hidden lg:inline truncate max-w-[220px]"
              title={currentRun.run_id}
            >
              [{currentRun.run_id}]
            </span>
          )}
        </div>
        <div className="flex items-center space-x-2 text-xs font-mono shrink-0">
          <span className="text-slate-500 font-medium">EVENTS:</span>
          <span className="font-bold text-[#276095] bg-white border border-slate-200 rounded px-2.5 py-0.5 shadow-2xs">
            {filteredEvents.length} / {events.length}
          </span>
          {events.length > 0 && (
            <button
              onClick={() => setShowConfirmClear(true)}
              className="px-2 py-0.5 bg-white hover:bg-rose-50 text-slate-500 hover:text-rose-700 border border-slate-200 hover:border-rose-300 rounded text-[11px] font-bold transition flex items-center space-x-1 cursor-pointer shadow-2xs"
              title="Clear current visible logs (saved history is preserved)"
            >
              <Trash2 className="w-3 h-3 text-rose-600" />
              <span>[ Clear Logs ]</span>
            </button>
          )}
        </div>
      </div>

      {/* Banner when viewing another float while batch is actively decoding in background */}
      {isViewingHistoricalWhileBatchRunning && (
        <div className="bg-sky-50 border-b border-sky-200 px-4 py-1.5 flex items-center justify-between text-xs font-mono text-sky-950 shrink-0">
          <div className="flex items-center space-x-2 truncate">
            <span className="w-2 h-2 rounded-full bg-amber-500 animate-ping shrink-0" />
            <span className="truncate">
              Viewing log for WMO {currentRun?.wmo}. Batch actively decoding{" "}
              <strong>WMO {currentBatch.running_wmo}</strong> in background.
            </span>
          </div>
          <button
            onClick={() =>
              selectBatchFloat(currentBatch.running_wmo!, currentBatch.running_run_id)
            }
            className="px-2 py-0.5 bg-[#276095] hover:bg-[#1f4e7a] text-white rounded text-[11px] font-bold transition flex items-center space-x-1 cursor-pointer shrink-0 shadow-2xs ml-2"
          >
            <span>LIVE FLOAT →</span>
          </button>
        </div>
      )}

      {/* Special Context Banners for Stopped or Failed Run */}
      {isStopped && (
        <div className="bg-amber-100 border-b border-amber-300 px-4 py-2 flex items-center justify-between text-xs font-mono text-amber-950 shrink-0">
          <div className="flex items-center space-x-2 font-bold truncate">
            <Ban className="w-4 h-4 text-amber-700 shrink-0" />
            <span className="truncate">
              🛑 DECODE STOPPED BY USER: WMO {currentRun?.wmo} ({currentRun?.duration_seconds.toFixed(2)}s). All events and partial outputs preserved.
            </span>
          </div>
          <span className="text-[11px] text-amber-800 font-medium shrink-0 ml-2">
            Run ID: {currentRun?.run_id}
          </span>
        </div>
      )}

      {isFailed && (
        <div className="bg-rose-100 border-b border-rose-300 px-4 py-2 flex items-center justify-between text-xs font-mono text-rose-950 shrink-0">
          <div className="flex items-center space-x-2 font-bold truncate">
            <XCircle className="w-4 h-4 text-rose-700 shrink-0" />
            <span className="truncate">
              ✕ DECODE FAILED: WMO {currentRun?.wmo} — {(() => {
                const primary = primaryError(currentRun?.errors);
                return primary.text
                  ? stripAnsi(primary.text) + primaryErrorSuffix(primary.extra)
                  : "Backend error";
              })()}
            </span>
          </div>
          <span className="text-[11px] text-rose-800 font-medium shrink-0 ml-2">
            Run ID: {currentRun?.run_id}
          </span>
        </div>
      )}

      {/* Filter, Search, and Clear Bar */}
      <div className="px-4 py-2 border-b border-slate-200 bg-[#F4F7F9] flex items-center justify-between gap-2.5 shrink-0">
        <div className="flex items-center space-x-1.5 font-mono text-xs">
          {(
            [
              { id: "all", label: "ALL EVENTS" },
              { id: "rtqc", label: "RTQC QUALITY" },
              { id: "outputs", label: "DELIVERABLES" },
              { id: "errors", label: "NOTICES & ERRORS" },
            ] as const
          ).map((f) => (
            <button
              key={f.id}
              onClick={() => setLogFilter(f.id)}
              className={`px-3 py-1 rounded text-[11px] font-bold tracking-wider transition border cursor-pointer ${
                logFilter === f.id
                  ? "bg-[#276095] text-white border-[#276095] shadow-2xs"
                  : "bg-white text-slate-600 border-slate-200 hover:bg-slate-100"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="flex items-center space-x-2 flex-1 max-w-md">
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
            <input
              type="text"
              value={logSearch}
              onChange={(e) => setLogSearch(e.target.value)}
              placeholder="Filter log (discovery, cycle, QC, NetCDF)..."
              className="w-full pl-8 pr-7 py-1.5 bg-white border border-slate-300 rounded text-xs font-mono text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-[#276095] focus:ring-1 focus:ring-[#276095]"
            />
            {logSearch && (
              <button
                onClick={() => setLogSearch("")}
                className="absolute right-2 top-2 text-slate-400 hover:text-slate-700 cursor-pointer"
                title="Clear search filter"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`px-2.5 py-1.5 rounded border text-xs font-mono font-bold flex items-center space-x-1.5 cursor-pointer transition shrink-0 ${
              autoScroll
                ? "bg-amber-100 text-amber-900 border-amber-300 font-bold"
                : "bg-white text-slate-500 border-slate-200 hover:bg-slate-50"
            }`}
            title="Toggle Auto-Scroll"
          >
            <ArrowDown className="w-3.5 h-3.5" />
            <span className="text-[11px] hidden sm:inline">AUTO-SCROLL</span>
          </button>

          <button
            onClick={() => setShowConfirmClear(true)}
            disabled={events.length === 0}
            className={`px-2.5 py-1.5 rounded border text-xs font-mono font-bold flex items-center space-x-1 transition shrink-0 cursor-pointer ${
              events.length > 0
                ? "bg-white hover:bg-rose-50 text-slate-600 hover:text-rose-700 border-slate-300 hover:border-rose-300 shadow-2xs"
                : "bg-slate-100 text-slate-300 border-slate-200 cursor-not-allowed"
            }`}
            title="Clear all events from current log view"
          >
            <Trash2 className="w-3.5 h-3.5 text-rose-600" />
            <span className="text-[11px]">[ Clear Logs ]</span>
          </button>
        </div>
      </div>

      {/* Main Two-Layer Log List */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-3.5 space-y-2.5 font-mono select-text bg-[#F4F7F9]"
      >
        {filteredEvents.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-400 space-y-2.5 select-none font-mono py-16">
            <Terminal className="w-9 h-9 text-slate-300" />
            <p className="text-xs font-medium text-slate-500">
              {isRunning || batchRunning
                ? "Streaming live decoder telemetry and scientific derivations..."
                : events.length === 0
                ? "Decoder logs cleared from current view (saved history is preserved)"
                : "No log events match current search or filters"}
            </p>
            {events.length === 0 && !isRunning && !batchRunning && (
              <span className="text-[11px] text-slate-400 font-sans">
                Ready for next execution. New events will appear here automatically.
              </span>
            )}
          </div>
        ) : (
          filteredEvents.map((evt) => {
            const isSelected = selectedEvent?.id === evt.id;
            const isExpanded = expandedDetails[evt.id] || false;

            return (
              <div
                key={evt.id}
                ref={isSelected ? selectedEventRef : null}
                onClick={() => setSelectedEvent(evt)}
                className={`p-3 rounded border transition cursor-pointer text-left select-none ${
                  isSelected
                    ? "bg-amber-50/90 border-amber-500 shadow-xs ring-2 ring-amber-300"
                    : "bg-white border-slate-200 hover:border-slate-300 hover:bg-slate-50/90"
                }`}
              >
                {/* Layer 1 Top Bar: Timestamp + Stage Badge + Cycle + Level Tag */}
                <div className="flex items-center justify-between text-[11px] pb-1.5 mb-1.5 border-b border-slate-100">
                  <div className="flex items-center space-x-2 truncate">
                    <span className="text-slate-500 font-semibold shrink-0">
                      {evt.timestamp ? evt.timestamp.slice(11, 19) : ""}
                    </span>
                    {evt.stage && (
                      <span className="font-bold text-[#276095] bg-sky-50 border border-sky-200 px-2 py-0.5 rounded text-[10.5px] uppercase shrink-0">
                        [{evt.stage}]
                      </span>
                    )}
                    {evt.cycle !== undefined && (
                      <span className="text-amber-900 font-bold bg-amber-50 border border-amber-200 rounded px-2 py-0.5 text-[10.5px] shrink-0">
                        CYCLE {evt.cycle}
                      </span>
                    )}
                  </div>
                  <div className="shrink-0 ml-2">
                    {getEventBadge(evt)}
                  </div>
                </div>

                {/* Layer 1 Primary View: Plain-Language Headline & Short Explanation */}
                <div className="space-y-1">
                  <div className="flex items-start space-x-1.5 text-slate-900 font-mono font-bold text-[13px] leading-snug">
                    {getEventGlyph(evt)}
                    <span>{stripAnsi(evt.message)}</span>
                  </div>

                  {evt.what_happened && (
                    <p className="text-xs text-slate-600 font-sans leading-relaxed pl-4">
                      {stripAnsi(evt.what_happened)}
                    </p>
                  )}
                </div>

                {/* Layer 2: Technical Details Bar & Drawer Trigger */}
                <div className="mt-2 pt-1.5 border-t border-slate-100 flex items-center justify-between text-[11px] font-mono">
                  <div className="flex items-center space-x-2 text-slate-500 truncate">
                    <span className="text-slate-400 font-sans text-[10.5px]">Backend:</span>
                    <code className="text-slate-700 font-semibold bg-slate-100 border border-slate-200 px-1.5 py-0.5 rounded text-[10px] truncate max-w-xs">
                      {stripAnsi(evt.operation || evt.python_function)}
                    </code>
                  </div>

                  <div className="flex items-center space-x-2 shrink-0 ml-2">
                    <button
                      onClick={(e) => toggleInlineDetails(evt.id, e)}
                      className="text-slate-500 hover:text-slate-800 text-[10.5px] flex items-center space-x-0.5 cursor-pointer py-0.5 px-1 rounded hover:bg-slate-100"
                      title="Toggle quick parameters"
                    >
                      <span>Parameters</span>
                      {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                    </button>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedEvent(evt);
                      }}
                      className="text-[#276095] font-bold text-[11px] uppercase hover:underline flex items-center space-x-1 cursor-pointer"
                    >
                      <span>[ View technical details ]</span>
                    </button>
                  </div>
                </div>

                {/* Optional Quick Inline Technical Parameter Table */}
                {isExpanded && evt.data_sample && (
                  <div className="mt-2 p-2 bg-slate-50 border border-slate-200 rounded text-[10.5px] font-mono space-y-1">
                    <div className="text-[9.5px] font-bold text-slate-500 uppercase tracking-wider mb-1">
                      Exact Backend Event Payload:
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 text-slate-700">
                      {Object.entries(evt.data_sample).map(([k, v]) => (
                        <div key={k} className="bg-white border border-slate-200 p-1 rounded">
                          <span className="text-slate-400 block text-[9px]">{stripAnsi(k)}</span>
                          <span className="font-bold text-slate-900 truncate block">
                            {stripAnsi(typeof v === "object" ? JSON.stringify(v) : String(v))}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Live Ticker Footer */}
      <div className="h-9 px-4 border-t border-slate-200 bg-[#F4F7F9] flex items-center justify-between text-[11px] font-mono text-slate-600 shrink-0">
        <div className="flex items-center space-x-2.5 truncate max-w-2xl">
          <span
            className={`w-2.5 h-2.5 rounded-full shrink-0 ${
              isRunning || batchRunning
                ? "bg-amber-500 animate-pulse ring-2 ring-amber-300"
                : currentRun?.status === "completed"
                ? "bg-emerald-600"
                : currentRun?.status === "stopped" || currentRun?.status === "cancelled"
                ? "bg-amber-600"
                : currentRun?.status === "error"
                ? "bg-rose-600"
                : "bg-slate-400"
            }`}
          />
          <span className="font-bold text-slate-800 uppercase truncate">
            {isRunning
              ? stripAnsi(currentRun?.active_operation) || "PROCESSING TELEMETRY PACKETS..."
              : batchRunning
              ? `BATCH IN PROGRESS (CURRENT: WMO ${currentBatch?.running_wmo || "..."})`
              : currentRun?.status === "completed"
              ? `DECODE COMPLETE: WMO ${currentRun?.wmo} (${currentRun?.completed_cycles} CYCLES, ${currentRun?.profile_count || 0} PROFILES)`
              : currentRun?.status === "stopped" || currentRun?.status === "cancelled"
              ? `EXECUTION STOPPED BY USER (WMO ${currentRun?.wmo})`
              : currentRun?.status === "error"
              ? "EXECUTION HALTED WITH ERROR"
              : "STANDBY"}
          </span>
        </div>
        <span className="text-slate-500 font-sans italic text-[11px] hidden sm:inline">
          Click any event card or [ View technical details ] for full inspection
        </span>
      </div>
    </section>
  );
};
