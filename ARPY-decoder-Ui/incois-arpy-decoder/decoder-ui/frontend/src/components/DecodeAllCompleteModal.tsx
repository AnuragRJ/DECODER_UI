import React from "react";
import { X, FileSpreadsheet, RefreshCw, CheckCircle2 } from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";

/**
 * "Today's fleet decoding is already complete" notice.
 *
 * Shown when the backend answers Decode-All with status "already_complete":
 * every currently detected/eligible float already has a genuinely successful
 * decode from today, so NO duplicate batch was started. The user chooses:
 *   [ View Results ]  → open the existing completed Results view,
 *   [ Re-run All ]    → explicit, intentional fresh batch over everything.
 */
export const DecodeAllCompleteModal: React.FC = () => {
  const {
    decodeAllAlreadyComplete: notice,
    clearDecodeAllAlreadyComplete,
    syncBatch,
    setActiveView,
    startDecodeAll,
  } = useDecoderStore();

  if (!notice) return null;

  if (!notice) return null;

  const viewResults = async () => {
    clearDecodeAllAlreadyComplete();
    if (notice.batchId) {
      await syncBatch(notice.batchId);
    }
    setActiveView("results");
  };

  const reRunAll = async () => {
    clearDecodeAllAlreadyComplete();
    await startDecodeAll(true);
  };

  return (
    <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-2xs z-50 flex items-center justify-center p-4 select-none font-mono text-slate-800">
      <div
        role="dialog"
        aria-label="Fleet decoding already complete"
        className="bg-white border border-slate-300 w-full max-w-lg rounded shadow-xl flex flex-col overflow-hidden"
      >
        <div className="h-10 px-4 bg-emerald-50/80 border-b border-emerald-200 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            <span className="font-bold text-xs uppercase tracking-wider text-emerald-900">
              Fleet decoding already complete
            </span>
          </div>
          <button
            onClick={clearDecodeAllAlreadyComplete}
            className="p-1 hover:bg-emerald-100 rounded text-slate-500 hover:text-slate-800 cursor-pointer"
            title="Dismiss"
            aria-label="Dismiss notice"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <p className="text-sm leading-relaxed text-slate-700">{notice.message}</p>
          <p className="text-[11px] leading-relaxed text-slate-500">
            No new decoder batch was started — already-completed work is never
            processed twice. Open the existing results, or deliberately
            reprocess every float.
          </p>

          <div className="flex items-center justify-end space-x-2 pt-1">
            <button
              onClick={viewResults}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-bold font-mono tracking-wide transition border shadow-xs cursor-pointer bg-[#276095] hover:bg-[#1f4e7a] text-white border-[#276095]"
              title="Open the existing completed Results view"
            >
              <FileSpreadsheet className="w-3.5 h-3.5" />
              <span>[ View Results ]</span>
            </button>
            <button
              onClick={reRunAll}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-bold font-mono tracking-wide transition border shadow-xs cursor-pointer bg-amber-600 hover:bg-amber-700 text-white border-amber-700"
              title="Deliberately re-decode EVERY float again today in a fresh batch (bypasses CACHED reuse)"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>[ Re-run All ]</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DecodeAllCompleteModal;
