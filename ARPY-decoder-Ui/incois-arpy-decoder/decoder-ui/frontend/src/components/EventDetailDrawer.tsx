import React from "react";
import {
  X,
  FileCode,
  ArrowRight,
  Code2,
  CheckCircle2,
  AlertTriangle,
  Layers,
  Database,
} from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";

export const EventDetailDrawer: React.FC = () => {
  const { selectedEvent, setSelectedEvent, setSelectedRtqcTest, setRtqcModalOpen, investigationRunId, activeRunId } = useDecoderStore();

  // The investigation view replaces the drawer: WHAT first, drawer after close.
  if (!selectedEvent || (investigationRunId !== null && investigationRunId === activeRunId)) return null;

  // top-14: the header is h-14 — the drawer must not cover its navigation.
  return (
    <div className="fixed top-14 bottom-0 right-0 w-[480px] bg-white border-l border-slate-200 shadow-2xl z-40 flex flex-col select-none text-slate-800 font-mono text-xs">
      {/* Header */}
      <div className="h-11 px-4 border-b border-slate-200 bg-[#F4F7F9] flex items-center justify-between shrink-0">
        <div className="flex items-center space-x-2">
          <Code2 className="w-4 h-4 text-[#276095]" />
          <span className="font-bold text-xs uppercase tracking-wider text-slate-900">
            TECHNICAL EVENT INSPECTOR
          </span>
          <span className="text-slate-400 text-[11px]">[{selectedEvent.id}]</span>
        </div>
        <button
          onClick={() => setSelectedEvent(null)}
          className="p-1 hover:bg-slate-200 text-slate-500 hover:text-slate-900 transition rounded cursor-pointer"
          aria-label="Close details"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3.5 bg-slate-50/50">
        {/* Event Top Headline Card */}
        <div className="p-3 bg-white border border-slate-200 rounded shadow-2xs space-y-1.5">
          <div className="flex justify-between items-center text-[11px] text-slate-500">
            <span className="font-semibold">TIMESTAMP: {selectedEvent.timestamp ? selectedEvent.timestamp.slice(11, 19) : ""}</span>
            <span className="text-[#276095] uppercase font-bold bg-sky-50 border border-sky-200 px-2 py-0.5 rounded text-[10.5px]">
              [{selectedEvent.stage || "PIPELINE"}]
            </span>
          </div>
          <p className="font-bold text-[13px] text-slate-900 leading-snug">
            {selectedEvent.message}
          </p>
          {selectedEvent.what_happened && (
            <p className="text-xs text-slate-600 font-sans leading-relaxed pt-1 border-t border-slate-100">
              {selectedEvent.what_happened}
            </p>
          )}
        </div>

        {/* 1. Python Source Location */}
        <div className="border border-slate-200 rounded overflow-hidden bg-white shadow-2xs">
          <div className="bg-[#F4F7F9] px-3 py-1.5 text-[10.5px] font-bold text-slate-700 uppercase tracking-wider border-b border-slate-200 flex items-center space-x-1.5">
            <FileCode className="w-3.5 h-3.5 text-[#276095]" />
            <span>PYTHON BACKEND SOURCE LOCATION</span>
          </div>
          <table className="w-full text-left text-[11px]">
            <tbody className="divide-y divide-slate-100">
              <tr>
                <td className="py-1.5 px-3 text-slate-500 font-medium w-36">Backend Event</td>
                <td className="py-1.5 px-3 text-slate-900 font-bold font-mono">
                  <code>{selectedEvent.operation || selectedEvent.python_function}</code>
                </td>
              </tr>
              <tr>
                <td className="py-1.5 px-3 text-slate-500 font-medium">Source File</td>
                <td className="py-1.5 px-3 text-sky-800 font-bold font-mono">
                  {selectedEvent.python_file || "argo_decoder/pipeline/runner.py"}
                </td>
              </tr>
              <tr>
                <td className="py-1.5 px-3 text-slate-500 font-medium">Function Name</td>
                <td className="py-1.5 px-3 text-amber-800 font-bold font-mono">
                  {selectedEvent.python_function || "run_pipeline"}
                </td>
              </tr>
              {selectedEvent.cycle !== undefined && (
                <tr>
                  <td className="py-1.5 px-3 text-slate-500 font-medium">Target Cycle</td>
                  <td className="py-1.5 px-3 text-[#276095] font-bold">
                    Cycle {selectedEvent.cycle}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* 2. RTQC Test Info if applicable */}
        {selectedEvent.rtqc_test && (
          <div className="border border-amber-300 rounded overflow-hidden bg-amber-50/40 shadow-2xs">
            <div className="bg-amber-100/70 px-3 py-1.5 text-[10.5px] font-bold text-amber-900 uppercase tracking-wider border-b border-amber-200 flex justify-between">
              <span>RTQC TEST :: {selectedEvent.rtqc_test.test_id}</span>
              <span>{selectedEvent.rtqc_test.rtqc_pass}</span>
            </div>
            <div className="p-3 space-y-2 text-[11px]">
              <div className="text-slate-900 font-bold text-xs">{selectedEvent.rtqc_test.name}</div>
              <div className="text-slate-700 text-[10.5px]">
                Rule: <code className="text-amber-900 font-bold bg-amber-100/80 px-1 py-0.5 rounded">{selectedEvent.rtqc_test.rule_applied}</code>
              </div>
              <div className="flex justify-between text-[11px] text-slate-700 pt-1.5 border-t border-amber-200">
                <span>Levels Checked: <strong>{selectedEvent.rtqc_test.levels_checked}</strong></span>
                <span className="text-emerald-700 font-bold">Flagged: {selectedEvent.rtqc_test.levels_flagged}</span>
              </div>
              <button
                onClick={() => {
                  setSelectedRtqcTest(selectedEvent.rtqc_test || null);
                  setRtqcModalOpen(true);
                }}
                className="w-full mt-1 py-1.5 bg-amber-100 hover:bg-amber-200 text-amber-900 border border-amber-300 rounded text-[11px] font-bold uppercase tracking-wider transition flex items-center justify-center space-x-1 cursor-pointer"
              >
                <span>Open in RTQC Matrix</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}

        {/* 3. Error Details if applicable */}
        {selectedEvent.error_details && (
          <div className="border border-rose-300 rounded overflow-hidden bg-rose-50/60 shadow-2xs">
            <div className="bg-rose-100 px-3 py-1.5 text-[10.5px] font-bold text-rose-800 uppercase tracking-wider border-b border-rose-200">
              BACKEND SYSTEM ERROR
            </div>
            <pre className="p-3 text-[10.5px] text-rose-900 whitespace-pre-wrap break-all font-mono">
              {selectedEvent.error_details}
            </pre>
          </div>
        )}

        {/* 4. Exact Structured Event Payload */}
        {selectedEvent.data_sample && (
          <div className="border border-slate-200 rounded overflow-hidden bg-white shadow-2xs">
            <div className="bg-[#F4F7F9] px-3 py-1.5 text-[10.5px] font-bold text-slate-700 uppercase tracking-wider border-b border-slate-200 flex items-center space-x-1.5">
              <Database className="w-3.5 h-3.5 text-[#276095]" />
              <span>EXACT EVENT LOG PAYLOAD (JSON)</span>
            </div>
            <pre className="p-3 text-[11px] text-slate-800 font-mono overflow-x-auto max-h-60 bg-white leading-relaxed">
              {JSON.stringify(selectedEvent.data_sample, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
};
