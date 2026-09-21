import React, { useEffect, useState } from "react";
import {
  X,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  FileSpreadsheet,
  Layers,
  Search,
  ChevronRight,
  ExternalLink,
  ShieldCheck,
  Ban,
  RotateCcw,
  Square,
  Zap,
  Trash2,
  AlertCircle,
  Mail,
  Sparkles,
} from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";
import { BatchFloatItem, NodeStatus, TriageItem } from "../types";

export const BatchResultsModal: React.FC = () => {
  const {
    isBatchSummaryModalOpen,
    setBatchSummaryModalOpen,
    currentBatch,
    allBatches,
    viewRun,
    batchRunning,
    isStopping,
    stopDecode,
    clearBatchSummary,
    triageResults,
    fetchTriage,
  } = useDecoderStore();

  const [statusFilter, setStatusFilter] = useState<"all" | "completed" | "error" | "stopped">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [showConfirmClear, setShowConfirmClear] = useState(false);

  // Agentic triage: fetch per-float recommendations whenever the summary opens
  // for a batch that has non-completed floats (read-only backend analysis).
  const batchIdForTriage = currentBatch?.batch_id || null;
  const hasNonCompleted = (currentBatch?.items || []).some((i) => i.status !== "completed");
  useEffect(() => {
    if (isBatchSummaryModalOpen && batchIdForTriage && hasNonCompleted) {
      fetchTriage(batchIdForTriage);
    }
  }, [isBatchSummaryModalOpen, batchIdForTriage, hasNonCompleted, fetchTriage]);

  const triageByWmo = new Map<number, TriageItem>(
    (triageResults || []).map((t) => [t.wmo, t])
  );

  if (!isBatchSummaryModalOpen) return null;

  const batch = currentBatch;
  const items = batch?.items || [];

  const filteredItems = items.filter((item) => {
    if (statusFilter === "completed" && item.status !== "completed") return false;
    if (statusFilter === "error" && item.status !== "error") return false;
    if (statusFilter === "stopped" && item.status !== "stopped" && item.status !== "cancelled") return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchWmo = item.wmo.toString().includes(q);
      const matchPlatform = item.platform_type.toLowerCase().includes(q);
      const matchTrans = item.transmission_type.toLowerCase().includes(q);
      const matchErr = item.error_message?.toLowerCase().includes(q);
      if (!matchWmo && !matchPlatform && !matchTrans && !matchErr) return false;
    }
    return true;
  });

  const getStatusBadge = (status: NodeStatus, cached?: boolean) => {
    switch (status) {
      case "completed":
        return cached ? (
          <span
            className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded text-[11px] font-mono font-bold bg-sky-50 text-sky-800 border border-sky-300"
            title="Already successfully decoded today — reused without re-decoding"
          >
            <CheckCircle2 className="w-3 h-3 text-sky-600 shrink-0" />
            <span>CACHED</span>
          </span>
        ) : (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded text-[11px] font-mono font-bold bg-emerald-50 text-emerald-800 border border-emerald-300">
            <CheckCircle2 className="w-3 h-3 text-emerald-600 shrink-0" />
            <span>SUCCESS</span>
          </span>
        );
      case "error":
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded text-[11px] font-mono font-bold bg-rose-50 text-rose-800 border border-rose-300">
            <XCircle className="w-3 h-3 text-rose-600 shrink-0" />
            <span>FAILED</span>
          </span>
        );
      case "stopped":
      case "cancelled":
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded text-[11px] font-mono font-bold bg-amber-50 text-amber-900 border border-amber-300">
            <Ban className="w-3 h-3 text-amber-600 shrink-0" />
            <span>STOPPED</span>
          </span>
        );
      case "active":
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded text-[11px] font-mono font-bold bg-amber-100 text-amber-950 border border-amber-400 animate-pulse">
            <RotateCcw className="w-3 h-3 text-amber-800 animate-spin shrink-0" />
            <span>RUNNING</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-slate-100 text-slate-600 border border-slate-200">
            <Clock className="w-3 h-3 text-slate-400 shrink-0" />
            <span>PENDING</span>
          </span>
        );
    }
  };

  const handleInspectRun = (item: BatchFloatItem, focusError: boolean = false) => {
    if (item.run_id) {
      viewRun(item.run_id, focusError, undefined, { fallbackError: item.error_message ?? null });
      setBatchSummaryModalOpen(false);
    }
  };

  const handleExecuteClear = () => {
    clearBatchSummary();
    setShowConfirmClear(false);
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
      {/* Confirmation Dialog Overlay */}
      {showConfirmClear && (
        <div className="fixed inset-0 z-60 bg-slate-950/70 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in duration-100">
          <div className="bg-white rounded-lg shadow-2xl border border-slate-200 w-full max-w-md p-5 space-y-4 font-mono select-none">
            <div className="flex items-start space-x-3">
              <div className="w-10 h-10 rounded-full bg-amber-100 border border-amber-300 flex items-center justify-center text-amber-700 shrink-0">
                <AlertCircle className="w-5 h-5" />
              </div>
              <div className="space-y-1">
                <h3 className="font-bold text-sm text-slate-900">
                  Clear Results Summary View?
                </h3>
                <p className="text-xs text-slate-600 font-sans leading-relaxed">
                  Clear the current view? Your saved run history will not be deleted.
                </p>
              </div>
            </div>

            <div className="p-2.5 bg-slate-50 border border-slate-200 rounded text-[11px] text-slate-500 font-sans">
              ℹ This action only clears the currently visible summary from the UI. All NetCDF files, XML reports, and persistent run records remain safely stored on disk.
            </div>

            <div className="flex items-center justify-end space-x-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowConfirmClear(false)}
                className="px-3.5 py-1.5 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-xs font-bold transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleExecuteClear}
                className="px-3.5 py-1.5 bg-rose-600 hover:bg-rose-700 text-white font-bold rounded text-xs transition flex items-center space-x-1.5 shadow-2xs cursor-pointer"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>[ Clear Summary ]</span>
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white rounded-lg shadow-2xl border border-slate-200 w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header Bar */}
        <div className="px-6 py-4 bg-[#276095] text-white flex items-center justify-between shrink-0 shadow-xs">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded bg-white/10 flex items-center justify-center border border-white/20">
              <FileSpreadsheet className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h2 className="text-base font-bold font-mono tracking-wide">
                  TODAY'S DECODING SUMMARY & BATCH RESULTS
                </h2>
                {batchRunning && (
                  <span className="bg-amber-400 text-slate-950 font-mono text-[10px] font-black px-2 py-0.5 rounded uppercase animate-pulse">
                    LIVE EXECUTION ACTIVE
                  </span>
                )}
              </div>
              <p className="text-xs text-sky-100 font-mono mt-0.5">
                {batch ? (
                  <>
                    Batch ID: {batch.batch_id || "batch-today"} • Created:{" "}
                    {batch.created_at ? new Date(batch.created_at).toLocaleTimeString() : "Today"}
                  </>
                ) : (
                  "No active summary loaded"
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            {batch && !batchRunning && (
              <div className="flex items-center space-x-1.5 px-2.5 py-1 bg-white/10 border border-white/20 rounded font-mono text-[11px]">
                {batch.email_status === "sent" ? (
                  <>
                    <Mail className="w-3.5 h-3.5 text-emerald-300 shrink-0" />
                    <span className="text-emerald-200 font-bold">Email sent</span>
                  </>
                ) : batch.email_status === "failed" ? (
                  <>
                    <AlertTriangle className="w-3.5 h-3.5 text-rose-300 shrink-0" />
                    <span
                      className="text-rose-200 font-bold"
                      title={batch.email_error || "SMTP delivery error"}
                    >
                      Email failed
                    </span>
                  </>
                ) : (
                  <>
                    <Mail className="w-3.5 h-3.5 text-sky-200 shrink-0" />
                    <span className="text-sky-200">Not sent</span>
                  </>
                )}
              </div>
            )}

            {(batchRunning || isStopping) ? (
              <button
                onClick={stopDecode}
                disabled={isStopping}
                className={`px-3 py-1.5 text-white text-xs font-mono font-bold rounded flex items-center space-x-1.5 transition shadow-xs ${
                  isStopping
                    ? "bg-amber-600 cursor-wait opacity-90"
                    : "bg-rose-600 hover:bg-rose-700 cursor-pointer"
                }`}
              >
                <Square className={`w-3.5 h-3.5 fill-current ${isStopping ? "animate-spin" : ""}`} />
                <span>{isStopping ? "STOPPING BATCH..." : "STOP BATCH"}</span>
              </button>
            ) : batch ? (
              <button
                onClick={() => setShowConfirmClear(true)}
                className="px-3 py-1.5 bg-white/10 hover:bg-rose-600 text-white hover:text-white border border-white/20 hover:border-rose-600 rounded text-xs font-mono font-bold transition flex items-center space-x-1.5 shadow-xs cursor-pointer"
                title="Clear current summary from view (saved history is preserved)"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>[ Clear Summary ]</span>
              </button>
            ) : null}
            <button
              onClick={() => setBatchSummaryModalOpen(false)}
              className="p-1.5 rounded text-white/80 hover:text-white hover:bg-white/10 transition cursor-pointer"
              title="Close summary modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* When summary is empty / cleared */}
        {!batch ? (
          <div className="p-12 text-center flex flex-col items-center justify-center space-y-3 font-mono">
            <div className="w-14 h-14 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-400">
              <FileSpreadsheet className="w-7 h-7" />
            </div>
            <div className="space-y-1 max-w-md">
              <h3 className="font-bold text-sm text-slate-900">
                Results Summary Cleared
              </h3>
              <p className="text-xs text-slate-500 font-sans leading-relaxed">
                The visible results summary has been cleared from your view. All decoded deliverables, NetCDF files, and complete execution logs remain saved in persistent history.
              </p>
            </div>
            <div className="pt-2">
              <button
                onClick={() => setBatchSummaryModalOpen(false)}
                className="px-4 py-1.5 bg-[#276095] hover:bg-[#1f4e7a] text-white font-bold rounded text-xs transition shadow-2xs cursor-pointer font-mono"
              >
                CLOSE WINDOW
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* Summary Metrics Banner */}
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2.5 p-4 bg-slate-50 border-b border-slate-200 shrink-0 font-mono">
              <div className="bg-white p-2.5 rounded border border-slate-200 shadow-2xs">
                <span className="text-[10px] text-slate-500 font-bold block uppercase">Total Floats</span>
                <span className="text-xl font-black text-slate-900">{batch?.total_floats || items.length}</span>
              </div>

              <div className="bg-emerald-50/60 p-2.5 rounded border border-emerald-200 shadow-2xs">
                <span className="text-[10px] text-emerald-800 font-bold block uppercase">Successful</span>
                <span className="text-xl font-black text-emerald-700">{batch?.completed_floats || 0}</span>
                {(batch?.cached_floats || 0) > 0 && (
                  <span className="text-[10px] text-sky-700 font-bold block" title="Reused from today's earlier successful decodes (not re-decoded)">
                    {batch.cached_floats} cached
                  </span>
                )}
              </div>

              <div className="bg-rose-50/60 p-2.5 rounded border border-rose-200 shadow-2xs">
                <span className="text-[10px] text-rose-800 font-bold block uppercase">Failed</span>
                <span className="text-xl font-black text-rose-700">{batch?.failed_floats || 0}</span>
              </div>

              <div className="bg-amber-50/60 p-2.5 rounded border border-amber-200 shadow-2xs">
                <span className="text-[10px] text-amber-900 font-bold block uppercase">Stopped</span>
                <span className="text-xl font-black text-amber-800">{batch?.stopped_floats || 0}</span>
              </div>

              <div className="bg-sky-50/60 p-2.5 rounded border border-sky-200 shadow-2xs">
                <span className="text-[10px] text-sky-800 font-bold block uppercase">Profiles Gen</span>
                <span className="text-xl font-black text-sky-700">{batch?.total_profiles_generated || 0}</span>
              </div>

              <div className="bg-slate-100 p-2.5 rounded border border-slate-200 shadow-2xs">
                <span className="text-[10px] text-slate-600 font-bold block uppercase">Profiles Miss</span>
                <span className="text-xl font-black text-slate-700">{batch?.total_profiles_missing || 0}</span>
              </div>

              <div className="bg-indigo-50/60 p-2.5 rounded border border-indigo-200 shadow-2xs">
                <span className="text-[10px] text-indigo-800 font-bold block uppercase">Total Outputs</span>
                <span className="text-xl font-black text-indigo-700">{batch?.total_output_files || 0}</span>
              </div>
            </div>

            {/* Filter and Search Controls */}
            <div className="px-5 py-2.5 bg-white border-b border-slate-200 flex flex-wrap items-center justify-between gap-3 shrink-0">
              {/* Status Filter Tabs */}
              <div className="flex items-center space-x-1.5 font-mono text-xs">
                <button
                  onClick={() => setStatusFilter("all")}
                  className={`px-3 py-1 rounded font-bold transition cursor-pointer ${
                    statusFilter === "all"
                      ? "bg-[#276095] text-white shadow-2xs"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  ALL ({items.length})
                </button>
                <button
                  onClick={() => setStatusFilter("completed")}
                  className={`px-3 py-1 rounded font-bold transition cursor-pointer ${
                    statusFilter === "completed"
                      ? "bg-emerald-600 text-white shadow-2xs"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  SUCCESS ({items.filter((i) => i.status === "completed").length})
                </button>
                <button
                  onClick={() => setStatusFilter("error")}
                  className={`px-3 py-1 rounded font-bold transition cursor-pointer ${
                    statusFilter === "error"
                      ? "bg-rose-600 text-white shadow-2xs"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  FAILED ({items.filter((i) => i.status === "error").length})
                </button>
                <button
                  onClick={() => setStatusFilter("stopped")}
                  className={`px-3 py-1 rounded font-bold transition cursor-pointer ${
                    statusFilter === "stopped"
                      ? "bg-amber-600 text-white shadow-2xs"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  STOPPED ({items.filter((i) => i.status === "stopped" || i.status === "cancelled").length})
                </button>
              </div>

              {/* Search Box */}
              <div className="relative w-64">
                <Search className="w-4 h-4 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Search WMO or platform..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-8 pr-3 py-1 text-xs font-mono bg-slate-50 border border-slate-300 rounded focus:outline-none focus:ring-1 focus:ring-[#276095] focus:bg-white"
                />
              </div>
            </div>

            {/* Results Table */}
            <div className="flex-1 overflow-y-auto p-4 select-text">
              {filteredItems.length === 0 ? (
                <div className="text-center py-12 text-slate-400 font-mono">
                  <Layers className="w-8 h-8 mx-auto mb-2 text-slate-300" />
                  <p className="text-xs">No float records matching current filters.</p>
                </div>
              ) : (
                <div className="border border-slate-200 rounded overflow-hidden shadow-2xs">
                  <table className="w-full text-left text-xs font-mono">
                    <thead className="bg-slate-100 text-slate-700 font-bold border-b border-slate-200 text-[11px] uppercase tracking-wider">
                      <tr>
                        <th className="py-2.5 px-3">Float (WMO)</th>
                        <th className="py-2.5 px-3">Platform / Telemetry</th>
                        <th className="py-2.5 px-3">Status</th>
                        <th className="py-2.5 px-3 text-center">Cycles</th>
                        <th className="py-2.5 px-3 text-center">Profiles</th>
                        <th className="py-2.5 px-3 text-center">Outputs</th>
                        <th className="py-2.5 px-3 text-center">Duration</th>
                        <th className="py-2.5 px-3">Error / Notes</th>
                        <th className="py-2.5 px-3 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 bg-white">
                      {filteredItems.map((item) => {
                        const isFailed = item.status === "error";
                        const triage = triageByWmo.get(item.wmo);
                        return (
                          <React.Fragment key={item.wmo}>
                          <tr
                            className={`hover:bg-slate-50/80 transition-colors ${
                              isFailed ? "bg-rose-50/30" : ""
                            }`}
                          >
                            {/* WMO */}
                            <td className="py-2.5 px-3 font-bold text-slate-900">
                              <span className="text-[#276095]">{item.wmo}</span>
                            </td>

                            {/* Platform */}
                            <td className="py-2.5 px-3 text-slate-600">
                              <span className="font-semibold">{item.platform_type || "APEX"}</span>
                              <span className="text-slate-400 ml-1">/ {item.transmission_type || "ARGOS"}</span>
                            </td>

                            {/* Status */}
                            <td className="py-2.5 px-3">{getStatusBadge(item.status, item.cached)}</td>

                            {/* Cycles */}
                            <td className="py-2.5 px-3 text-center text-slate-700 font-semibold">
                              {item.cycles_count}
                            </td>

                            {/* Profiles */}
                            <td className="py-2.5 px-3 text-center font-bold text-sky-800">
                              {item.profiles_count}
                              {item.missing_profiles > 0 && (
                                <span className="text-[10px] text-slate-400 block font-normal">
                                  ({item.missing_profiles} miss)
                                </span>
                              )}
                            </td>

                            {/* Outputs */}
                            <td className="py-2.5 px-3 text-center font-bold text-indigo-700">
                              {item.outputs_count}
                            </td>

                            {/* Duration */}
                            <td className="py-2.5 px-3 text-center text-slate-500">
                              {item.duration_seconds > 0 ? `${item.duration_seconds.toFixed(2)}s` : "-"}
                            </td>

                            {/* Error (Clickable!) */}
                            <td className="py-2.5 px-3">
                              {item.error_message ? (
                                <button
                                  onClick={() => handleInspectRun(item, true)}
                                  className="text-left font-semibold text-rose-700 hover:text-rose-900 hover:underline flex items-center space-x-1 max-w-xs truncate cursor-pointer group"
                                  title="Click to inspect this error in live event logs"
                                >
                                  <AlertTriangle className="w-3.5 h-3.5 text-rose-600 shrink-0 group-hover:scale-110 transition-transform" />
                                  <span className="truncate">{item.error_message}</span>
                                </button>
                              ) : item.status === "completed" ? (
                                <span className="text-slate-400">-</span>
                              ) : item.status === "stopped" ? (
                                <span className="text-amber-800 font-medium">Stopped by user</span>
                              ) : (
                                <span className="text-slate-400">Awaiting execution</span>
                              )}
                            </td>

                            {/* Action: View Run */}
                            <td className="py-2.5 px-3 text-right">
                              {item.run_id ? (
                                <button
                                  onClick={() => handleInspectRun(item, false)}
                                  className="px-2.5 py-1 bg-white hover:bg-slate-100 text-[#276095] border border-slate-300 hover:border-[#276095] rounded text-[11px] font-bold font-mono transition shadow-2xs inline-flex items-center space-x-1 cursor-pointer"
                                  title="Replay and view full pipeline & logs for this run"
                                >
                                  <span>VIEW RUN</span>
                                  <ChevronRight className="w-3 h-3" />
                                </button>
                              ) : (
                                <span className="text-slate-300 text-[11px]">-</span>
                              )}
                            </td>
                          </tr>

                          {/* Agentic triage row (failed floats only) */}
                          {isFailed && triage && (
                            <tr className="bg-indigo-50/40">
                              <td colSpan={9} className="px-4 py-2.5">
                                <div className="flex flex-col gap-1.5">
                                  <div className="flex items-center flex-wrap gap-2">
                                    <span className="inline-flex items-center space-x-1 text-[10px] font-black tracking-wider text-indigo-700">
                                      <Sparkles className="w-3.5 h-3.5" />
                                      <span>TRIAGE</span>
                                    </span>
                                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${
                                      triage.category === "DECODER_ERROR" || triage.category === "UNCLASSIFIED"
                                        ? "bg-rose-50 text-rose-800 border-rose-300"
                                        : triage.category === "USER_STOPPED"
                                          ? "bg-slate-100 text-slate-700 border-slate-300"
                                          : "bg-amber-50 text-amber-900 border-amber-300"
                                    }`}>
                                      {triage.category_label.toUpperCase()}
                                    </span>
                                    <span className="text-[10px] text-slate-500 font-mono">
                                      {triage.category}
                                    </span>
                                  </div>
                                  <div className="text-[11px] text-slate-700 leading-snug">
                                    <span className="font-bold text-slate-600">Root cause (as reported): </span>
                                    <span className="font-mono text-rose-800">“{triage.root_cause}”</span>
                                  </div>
                                  <div className="text-[11px] text-slate-700 leading-snug">
                                    <span className="font-bold text-indigo-700">Recommended: </span>
                                    {triage.recommended_action}
                                  </div>
                                  {triage.evidence.length > 0 && (
                                    <div
                                      className="text-[10px] text-slate-500 font-mono"
                                      title={triage.evidence.map((e) => `${e.source}: ${e.detail}`).join("\n")}
                                    >
                                      Evidence: {triage.evidence.map((e) => e.source).join(" • ")}
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-5 py-3 bg-slate-100 border-t border-slate-200 flex items-center justify-between shrink-0 text-xs font-mono">
              <div className="text-slate-600 flex items-center space-x-2">
                <ShieldCheck className="w-4 h-4 text-emerald-600" />
                <span>All decoding metrics verified from real Python execution history.</span>
              </div>
              <div className="flex items-center space-x-2">
                {!batchRunning && (
                  <button
                    onClick={() => setShowConfirmClear(true)}
                    className="px-3.5 py-1.5 bg-white hover:bg-rose-50 text-slate-700 hover:text-rose-700 border border-slate-300 hover:border-rose-300 font-bold rounded transition shadow-2xs cursor-pointer flex items-center space-x-1"
                    title="Clear current summary from view"
                  >
                    <Trash2 className="w-3.5 h-3.5 text-rose-600" />
                    <span>[ Clear Summary ]</span>
                  </button>
                )}
                <button
                  onClick={() => setBatchSummaryModalOpen(false)}
                  className="px-4 py-1.5 bg-[#276095] hover:bg-[#1f4e7a] text-white font-bold rounded transition shadow-2xs cursor-pointer"
                >
                  CLOSE SUMMARY
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};
