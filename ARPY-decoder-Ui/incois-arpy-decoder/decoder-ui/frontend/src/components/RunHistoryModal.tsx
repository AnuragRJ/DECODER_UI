import React, { useState, useEffect } from "react";
import {
  X,
  History,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  Ban,
  RotateCcw,
  Search,
  ChevronRight,
  ShieldCheck,
  FileSpreadsheet,
} from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";
import { NodeStatus, RunSummary } from "../types";

export const RunHistoryModal: React.FC = () => {
  const {
    isRunHistoryModalOpen,
    setRunHistoryModalOpen,
    allRuns,
    allBatches,
    fetchAllRuns,
    fetchAllBatches,
    viewRun,
    loadBatchSummary,
    setActiveView,
    activeRunId,
  } = useDecoderStore();

  const [historyTab, setHistoryTab] = useState<"runs" | "batches">("runs");
  const [searchQuery, setSearchQuery] = useState("");
  const [filterStatus, setFilterStatus] = useState<"all" | "completed" | "error" | "stopped">("all");

  useEffect(() => {
    if (isRunHistoryModalOpen) {
      fetchAllRuns();
      fetchAllBatches();
    }
  }, [isRunHistoryModalOpen]);

  if (!isRunHistoryModalOpen) return null;

  const filteredRuns = allRuns.filter((run) => {
    if (filterStatus === "completed" && run.status !== "completed") return false;
    if (filterStatus === "error" && run.status !== "error") return false;
    if (filterStatus === "stopped" && run.status !== "stopped" && run.status !== "cancelled") return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchWmo = run.wmo.toString().includes(q);
      const matchId = run.run_id.toLowerCase().includes(q);
      const matchPlatform = run.float_type.toLowerCase().includes(q);
      if (!matchWmo && !matchId && !matchPlatform) return false;
    }
    return true;
  });

  const getStatusBadge = (status: NodeStatus) => {
    switch (status) {
      case "completed":
        return (
          <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10.5px] font-mono font-bold bg-emerald-50 text-emerald-800 border border-emerald-300">
            <CheckCircle2 className="w-3 h-3 text-emerald-600 shrink-0" />
            <span>SUCCESS</span>
          </span>
        );
      case "error":
        return (
          <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10.5px] font-mono font-bold bg-rose-50 text-rose-800 border border-rose-300">
            <XCircle className="w-3 h-3 text-rose-600 shrink-0" />
            <span>FAILED</span>
          </span>
        );
      case "stopped":
      case "cancelled":
        return (
          <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10.5px] font-mono font-bold bg-amber-50 text-amber-900 border border-amber-300">
            <Ban className="w-3 h-3 text-amber-600 shrink-0" />
            <span>STOPPED</span>
          </span>
        );
      case "active":
        return (
          <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10.5px] font-mono font-bold bg-amber-100 text-amber-950 border border-amber-400 animate-pulse">
            <RotateCcw className="w-3 h-3 text-amber-800 animate-spin shrink-0" />
            <span>ACTIVE</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10.5px] font-mono font-semibold bg-slate-100 text-slate-600 border border-slate-200">
            <Clock className="w-3 h-3 text-slate-400 shrink-0" />
            <span>PENDING</span>
          </span>
        );
    }
  };

  const handleSelectRun = (runId: string) => {
    viewRun(runId, false);
    setRunHistoryModalOpen(false);
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-2xl border border-slate-200 w-full max-w-4xl max-h-[85vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="px-5 py-3.5 bg-[#276095] text-white flex items-center justify-between shrink-0 shadow-xs">
          <div className="flex items-center space-x-2.5">
            <div className="w-8 h-8 rounded bg-white/10 flex items-center justify-center border border-white/20">
              <History className="w-4 h-4 text-white" />
            </div>
            <div>
              <h2 className="text-sm font-bold font-mono tracking-wide">
                DECODING RUN HISTORY (PERSISTENT LOG ARCHIVE)
              </h2>
              <p className="text-[11px] text-sky-100 font-mono">
                {allRuns.length} Single Runs • {allBatches.length} Fleet Batches Saved on Disk
              </p>
            </div>
          </div>

          <button
            onClick={() => setRunHistoryModalOpen(false)}
            className="p-1 rounded text-white/80 hover:text-white hover:bg-white/10 transition cursor-pointer"
            title="Close modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Switcher: Runs vs Batches */}
        <div className="bg-slate-100 px-5 pt-2 border-b border-slate-200 flex items-center space-x-2 font-mono text-xs shrink-0">
          <button
            onClick={() => setHistoryTab("runs")}
            className={`px-3 py-1.5 rounded-t font-bold transition flex items-center space-x-1.5 border-t border-x cursor-pointer ${
              historyTab === "runs"
                ? "bg-white text-slate-900 border-slate-300 border-b-transparent shadow-2xs"
                : "bg-transparent text-slate-600 hover:text-slate-900 border-transparent"
            }`}
          >
            <History className="w-3.5 h-3.5 text-[#276095]" />
            <span>INDIVIDUAL RUNS ({allRuns.length})</span>
          </button>

          <button
            onClick={() => setHistoryTab("batches")}
            className={`px-3 py-1.5 rounded-t font-bold transition flex items-center space-x-1.5 border-t border-x cursor-pointer ${
              historyTab === "batches"
                ? "bg-white text-slate-900 border-slate-300 border-b-transparent shadow-2xs"
                : "bg-transparent text-slate-600 hover:text-slate-900 border-transparent"
            }`}
          >
            <FileSpreadsheet className="w-3.5 h-3.5 text-[#276095]" />
            <span>BATCH SUMMARIES ({allBatches.length})</span>
          </button>
        </div>

        {/* Filter & Search Bar */}
        <div className="px-5 py-2.5 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-2 shrink-0">
          <div className="flex items-center space-x-1.5 font-mono text-xs">
            <button
              onClick={() => setFilterStatus("all")}
              className={`px-2.5 py-1 rounded font-bold transition cursor-pointer ${
                filterStatus === "all"
                  ? "bg-[#276095] text-white shadow-2xs"
                  : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-100"
              }`}
            >
              ALL ({historyTab === "runs" ? allRuns.length : allBatches.length})
            </button>
            <button
              onClick={() => setFilterStatus("completed")}
              className={`px-2.5 py-1 rounded font-bold transition cursor-pointer ${
                filterStatus === "completed"
                  ? "bg-emerald-600 text-white shadow-2xs"
                  : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-100"
              }`}
            >
              SUCCESS (
              {historyTab === "runs"
                ? allRuns.filter((r) => r.status === "completed").length
                : allBatches.filter((b) => b.status === "completed").length}
              )
            </button>
            <button
              onClick={() => setFilterStatus("error")}
              className={`px-2.5 py-1 rounded font-bold transition cursor-pointer ${
                filterStatus === "error"
                  ? "bg-rose-600 text-white shadow-2xs"
                  : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-100"
              }`}
            >
              FAILED (
              {historyTab === "runs"
                ? allRuns.filter((r) => r.status === "error").length
                : allBatches.filter((b) => b.status === "error").length}
              )
            </button>
            <button
              onClick={() => setFilterStatus("stopped")}
              className={`px-2.5 py-1 rounded font-bold transition cursor-pointer ${
                filterStatus === "stopped"
                  ? "bg-amber-600 text-white shadow-2xs"
                  : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-100"
              }`}
            >
              STOPPED (
              {historyTab === "runs"
                ? allRuns.filter((r) => r.status === "stopped" || r.status === "cancelled").length
                : allBatches.filter((b) => b.status === "stopped" || b.status === "cancelled").length}
              )
            </button>
          </div>

          <div className="relative w-64">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder={historyTab === "runs" ? "Search by WMO or Run ID..." : "Search by Batch ID..."}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-8 pr-3 py-1 text-xs font-mono bg-white border border-slate-300 rounded focus:outline-none focus:ring-1 focus:ring-[#276095]"
            />
          </div>
        </div>

        {/* Content Area: Runs List or Batches List */}
        <div className="flex-1 overflow-y-auto p-4 select-text font-mono">
          {historyTab === "runs" ? (
            filteredRuns.length === 0 ? (
              <div className="text-center py-12 text-slate-400">
                <History className="w-8 h-8 mx-auto mb-2 text-slate-300" />
                <p className="text-xs">No saved execution runs matching filters.</p>
              </div>
            ) : (
              <div className="border border-slate-200 rounded overflow-hidden shadow-2xs">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-100 text-slate-700 font-bold border-b border-slate-200 text-[11px] uppercase tracking-wider">
                    <tr>
                      <th className="py-2.5 px-3">Run ID</th>
                      <th className="py-2.5 px-3">WMO Float</th>
                      <th className="py-2.5 px-3">Status</th>
                      <th className="py-2.5 px-3">Started</th>
                      <th className="py-2.5 px-3 text-center">Duration</th>
                      <th className="py-2.5 px-3 text-center">Cycles</th>
                      <th className="py-2.5 px-3 text-center">Outputs</th>
                      <th className="py-2.5 px-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {filteredRuns.map((run) => {
                      const isSelected = activeRunId === run.run_id;
                      return (
                        <tr
                          key={run.run_id}
                          className={`hover:bg-slate-50 transition-colors ${
                            isSelected ? "bg-sky-50/50" : ""
                          }`}
                        >
                          <td className="py-2.5 px-3 font-semibold text-slate-700">
                            <span className="truncate block max-w-xs">{run.run_id}</span>
                          </td>
                          <td className="py-2.5 px-3 font-bold text-[#276095]">
                            WMO {run.wmo}
                            <span className="text-slate-400 font-normal text-[10.5px] ml-1">
                              ({run.float_type || "APEX"})
                            </span>
                          </td>
                          <td className="py-2.5 px-3">{getStatusBadge(run.status)}</td>
                          <td className="py-2.5 px-3 text-slate-500 text-[11px]">
                            {run.start_time ? new Date(run.start_time).toLocaleString() : "-"}
                          </td>
                          <td className="py-2.5 px-3 text-center text-slate-700 font-medium">
                            {run.duration_seconds > 0 ? `${run.duration_seconds.toFixed(2)}s` : "-"}
                          </td>
                          <td className="py-2.5 px-3 text-center font-semibold text-slate-800">
                            {run.completed_cycles} / {run.total_cycles}
                          </td>
                          <td className="py-2.5 px-3 text-center font-bold text-indigo-700">
                            {run.output_files?.length || 0}
                          </td>
                          <td className="py-2.5 px-3 text-right">
                            <button
                              onClick={() => handleSelectRun(run.run_id)}
                              className="px-2.5 py-1 bg-white hover:bg-[#276095] hover:text-white text-[#276095] border border-slate-300 hover:border-[#276095] rounded text-[11px] font-bold transition shadow-2xs inline-flex items-center space-x-1 cursor-pointer"
                              title="Replay historical execution view"
                            >
                              <span>VIEW RUN</span>
                              <ChevronRight className="w-3 h-3" />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )
          ) : (
            allBatches.length === 0 ? (
              <div className="text-center py-12 text-slate-400">
                <FileSpreadsheet className="w-8 h-8 mx-auto mb-2 text-slate-300" />
                <p className="text-xs">No historical batch runs recorded.</p>
              </div>
            ) : (
              <div className="border border-slate-200 rounded overflow-hidden shadow-2xs">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-100 text-slate-700 font-bold border-b border-slate-200 text-[11px] uppercase tracking-wider">
                    <tr>
                      <th className="py-2.5 px-3">Batch ID</th>
                      <th className="py-2.5 px-3">Status</th>
                      <th className="py-2.5 px-3">Created</th>
                      <th className="py-2.5 px-3 text-center">Floats</th>
                      <th className="py-2.5 px-3 text-center">Profiles</th>
                      <th className="py-2.5 px-3 text-center">Duration</th>
                      <th className="py-2.5 px-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {allBatches.map((b) => (
                      <tr key={b.batch_id} className="hover:bg-slate-50 transition-colors">
                        <td className="py-2.5 px-3 font-semibold text-slate-700">
                          {b.batch_id}
                        </td>
                        <td className="py-2.5 px-3">{getStatusBadge(b.status)}</td>
                        <td className="py-2.5 px-3 text-slate-500 text-[11px]">
                          {b.created_at ? new Date(b.created_at).toLocaleString() : "-"}
                        </td>
                        <td className="py-2.5 px-3 text-center font-bold text-slate-900">
                          {b.completed_floats}/{b.total_floats} done
                          {b.failed_floats > 0 && (
                            <span className="text-rose-600 ml-1">({b.failed_floats} fail)</span>
                          )}
                        </td>
                        <td className="py-2.5 px-3 text-center font-bold text-sky-800">
                          {b.total_profiles_generated}
                        </td>
                        <td className="py-2.5 px-3 text-center text-slate-700 font-medium">
                          {b.duration_seconds > 0 ? `${b.duration_seconds.toFixed(2)}s` : "-"}
                        </td>
                        <td className="py-2.5 px-3 text-right whitespace-nowrap">
                          <button
                            onClick={() => {
                              loadBatchSummary(b);
                              setActiveView("results");
                              setRunHistoryModalOpen(false);
                            }}
                            className="px-2.5 py-1 bg-white hover:bg-[#276095] hover:text-white text-[#276095] border border-slate-300 hover:border-[#276095] rounded text-[11px] font-bold transition shadow-2xs inline-flex items-center space-x-1 cursor-pointer mr-1.5"
                            title="Load this batch summary into the Results workspace"
                          >
                            <span>LOAD IN RESULTS</span>
                            <ChevronRight className="w-3 h-3" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 bg-slate-100 border-t border-slate-200 flex items-center justify-between shrink-0 text-xs font-mono">
          <div className="text-slate-600 flex items-center space-x-2">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            <span>Historical events stored persistently on disk in JSON format.</span>
          </div>
          <button
            onClick={() => setRunHistoryModalOpen(false)}
            className="px-4 py-1.5 bg-[#276095] hover:bg-[#1f4e7a] text-white font-bold rounded transition shadow-2xs cursor-pointer"
          >
            CLOSE
          </button>
        </div>
      </div>
    </div>
  );
};
