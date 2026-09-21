import React from "react";
import {
  Layers,
  RotateCcw,
  CheckCircle2,
  XCircle,
  Ban,
  Clock,
  Square,
  FileSpreadsheet,
  Radio,
  ExternalLink,
  Trash2,
  X,
  Mail,
  AlertTriangle,
} from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";

export const BatchProgressBanner: React.FC = () => {
  const {
    currentBatch,
    batchRunning,
    isStopping,
    stopDecode,
    setBatchSummaryModalOpen,
    setActiveView,
    activeRunId,
    currentRun,
    selectBatchFloat,
    autoFollowBatch,
    clearBatchSummary,
  } = useDecoderStore();

  if (!currentBatch) return null;

  const total = currentBatch.total_floats || currentBatch.items?.length || 0;
  const completed = currentBatch.completed_floats || 0;
  const failed = currentBatch.failed_floats || 0;
  const stopped = currentBatch.stopped_floats || 0;
  const pending = currentBatch.pending_floats || 0;
  const runningWmo = currentBatch.running_wmo;

  const finishedCount = completed + failed + stopped;
  const progressPercent = total > 0 ? Math.round((finishedCount / total) * 100) : 0;

  return (
    <div className="bg-slate-900 text-white px-3.5 py-2 border-b border-slate-800 shrink-0 font-mono text-xs flex flex-wrap items-center justify-between gap-2.5 shadow-xs select-none">
      {/* Left: Overall Fleet Summary Badge & Clickable Float Chips */}
      <div className="flex items-center space-x-3 overflow-x-auto py-0.5 max-w-full">
        {/* Fleet Total Pill */}
        <div className="flex items-center space-x-1.5 text-sky-400 font-bold shrink-0">
          <Layers className="w-4 h-4 shrink-0" />
          <span className="uppercase tracking-wider">FLEET ({total})</span>
        </div>

        <div className="h-4 w-px bg-slate-700 shrink-0" />

        {/* Clickable Float Status Chips */}
        <div className="flex items-center space-x-1.5 overflow-x-auto py-0.5">
          {currentBatch.items?.map((item) => {
            const isSelected =
              (activeRunId && item.run_id && activeRunId === item.run_id) ||
              (!activeRunId && currentRun?.wmo === item.wmo) ||
              (item.run_id && currentRun?.run_id === item.run_id);

            const isCompleted = item.status === "completed";
            const isActive = item.status === "active";
            const isFailed = item.status === "error";
            const isStopped = item.status === "stopped" || item.status === "cancelled";
            const isPending = item.status === "pending" || !item.status;

            return (
              <button
                key={item.wmo}
                onClick={() => selectBatchFloat(item.wmo, item.run_id)}
                className={`px-2.5 py-1 rounded-md font-mono text-xs font-bold transition-all flex items-center space-x-1.5 cursor-pointer shrink-0 border ${
                  isSelected
                    ? "bg-[#276095] text-white border-sky-400 ring-2 ring-sky-400/80 shadow-md scale-[1.02]"
                    : isCompleted
                    ? "bg-slate-800/90 hover:bg-slate-700 text-emerald-300 border-emerald-600/50 hover:border-emerald-400"
                    : isActive
                    ? "bg-amber-950/80 hover:bg-amber-900 text-amber-300 border-amber-500/70 animate-pulse hover:border-amber-400"
                    : isFailed
                    ? "bg-rose-950/80 hover:bg-rose-900 text-rose-300 border-rose-500/60 hover:border-rose-400"
                    : isStopped
                    ? "bg-amber-950/80 hover:bg-amber-900 text-amber-300 border-amber-600/50 hover:border-amber-400"
                    : "bg-slate-800/40 hover:bg-slate-800/80 text-slate-400 border-slate-700/60 hover:border-slate-500"
                }`}
                title={`WMO ${item.wmo} (${item.platform_type || "APEX"})\nStatus: ${item.status.toUpperCase()}${item.cached ? " (CACHED — reused today's earlier successful decode, not re-decoded in this batch)" : ""}${
                  item.run_id ? `\nRun ID: ${item.run_id}` : ""
                }${item.cycles_count ? `\nCycles: ${item.cycles_count}` : ""}${
                  item.profiles_count ? `\nProfiles: ${item.profiles_count}` : ""
                }${item.duration_seconds > 0 ? `\nDuration: ${item.duration_seconds.toFixed(2)}s` : ""}${
                  item.error_message ? `\nError: ${item.error_message}` : ""
                }\n\nClick to display full historical log and pipeline state.`}
              >
                {/* Status Glyphs: ✓ (cached = sky), ●, ✕, ⊘, ○ */}
                {isCompleted && item.cached && (
                  <span className="text-sky-400 font-black text-xs leading-none" title="Reused today's successful decode">⇄</span>
                )}
                {isCompleted && !item.cached && (
                  <span className="text-emerald-400 font-black text-xs leading-none">✓</span>
                )}
                {isActive && (
                  <RotateCcw className="w-3 h-3 text-amber-300 animate-spin shrink-0" />
                )}
                {isFailed && (
                  <span className="text-rose-400 font-black text-xs leading-none">✕</span>
                )}
                {isStopped && (
                  <span className="text-amber-400 font-bold text-xs leading-none">⊘</span>
                )}
                {isPending && (
                  <span className="text-slate-400 text-[11px] leading-none">○</span>
                )}

                {/* Float WMO */}
                <span>{item.wmo}</span>

                {/* Duration indicator if completed */}
                {item.duration_seconds > 0 && !isSelected && (
                  <span className="text-[10px] opacity-60 ml-0.5">
                    {item.duration_seconds.toFixed(1)}s
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Live Follow indicator or Jump-to-Live button if batch is active and user looked at historical float */}
        {batchRunning && runningWmo && !autoFollowBatch && (
          <button
            onClick={() => selectBatchFloat(runningWmo, currentBatch.running_run_id)}
            className="px-2 py-0.5 bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold rounded text-[11px] flex items-center space-x-1 animate-pulse cursor-pointer shadow-xs shrink-0"
            title="Return to actively decoding live float"
          >
            <RotateCcw className="w-3 h-3 animate-spin" />
            <span>JUMP TO LIVE (WMO {runningWmo})</span>
          </button>
        )}
      </div>

      {/* Right: Progress bar & Actions */}
      <div className="flex items-center space-x-2.5 shrink-0 ml-auto">
        {/* Quick Fleet Counts */}
        <div className="hidden xl:flex items-center space-x-2 text-[11px] text-slate-400">
          <span className="text-emerald-400 font-semibold">{completed} done</span>
          {(currentBatch.cached_floats || 0) > 0 && (
            <span className="text-sky-400 font-semibold" title="Floats reused from today's earlier successful decodes (not re-decoded in this batch)">
              {currentBatch.cached_floats} cached
            </span>
          )}
          {failed > 0 && <span className="text-rose-400 font-semibold">{failed} fail</span>}
          {stopped > 0 && <span className="text-amber-400 font-semibold">{stopped} stop</span>}
          {pending > 0 && <span>{pending} pend</span>}
        </div>

        {/* Visual Progress Bar */}
        <div className="w-24 bg-slate-800 rounded-full h-2 overflow-hidden border border-slate-700 hidden md:block">
          <div
            className={`h-full transition-all duration-300 ${
              batchRunning ? "bg-amber-400 animate-pulse" : "bg-emerald-500"
            }`}
            style={{ width: `${progressPercent}%` }}
          />
        </div>

        {/* Email Status Indicator */}
        {!batchRunning && currentBatch.email_status && (
          <div className="flex items-center space-x-1 px-2 py-0.5 rounded text-[10.5px] bg-slate-800 border border-slate-700">
            {currentBatch.email_status === "sent" ? (
              <span className="text-emerald-400 font-bold flex items-center space-x-1">
                <Mail className="w-3 h-3" />
                <span>Email sent</span>
              </span>
            ) : currentBatch.email_status === "failed" ? (
              <span
                className="text-rose-400 font-bold flex items-center space-x-1"
                title={currentBatch.email_error || "SMTP delivery error"}
              >
                <AlertTriangle className="w-3 h-3" />
                <span>Email failed</span>
              </span>
            ) : (
              <span className="text-slate-400 flex items-center space-x-1">
                <Mail className="w-3 h-3" />
                <span>Not sent</span>
              </span>
            )}
          </div>
        )}

        <button
          onClick={() => setActiveView("results")}
          className="px-2.5 py-1 bg-white/10 hover:bg-white/20 text-sky-200 border border-white/20 rounded font-bold text-[11px] transition flex items-center space-x-1 shadow-2xs cursor-pointer"
          title="Open dedicated Results & Oceanographic Workstation"
        >
          <FileSpreadsheet className="w-3 h-3 text-sky-400" />
          <span>VIEW RESULTS</span>
        </button>

        {!batchRunning && (
          <button
            onClick={clearBatchSummary}
            className="px-2 py-1 bg-white/10 hover:bg-rose-900/60 text-slate-300 hover:text-rose-200 border border-white/15 hover:border-rose-500/50 rounded font-bold text-[11px] transition flex items-center space-x-1 shadow-2xs cursor-pointer"
            title="Clear batch summary and dismiss banner"
          >
            <Trash2 className="w-3 h-3 text-rose-400" />
            <span className="hidden sm:inline">CLEAR SUMMARY</span>
          </button>
        )}

        {(batchRunning || isStopping) && (
          <button
            onClick={stopDecode}
            disabled={isStopping}
            className={`px-2.5 py-1 rounded font-bold text-[11px] transition flex items-center space-x-1 shadow-2xs ${
              isStopping
                ? "bg-amber-600 text-white cursor-wait opacity-90"
                : "bg-rose-600 hover:bg-rose-700 text-white cursor-pointer"
            }`}
            title="Stop the entire batch decode execution"
          >
            <Square className={`w-3 h-3 fill-current ${isStopping ? "animate-spin" : ""}`} />
            <span>{isStopping ? "STOPPING..." : "STOP BATCH"}</span>
          </button>
        )}
      </div>
    </div>
  );
};
