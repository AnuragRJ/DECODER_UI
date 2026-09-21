import React from "react";
import { X, FileCode } from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";

export const FlowchartModal: React.FC = () => {
  const { isFlowchartModalOpen, setFlowchartModalOpen } = useDecoderStore();

  if (!isFlowchartModalOpen) return null;

  return (
    <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-2xs z-50 flex items-center justify-center p-4 select-none font-mono text-slate-800">
      <div className="bg-white border border-slate-300 w-full max-w-6xl h-[88vh] rounded shadow-xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="h-10 px-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <FileCode className="w-4 h-4 text-sky-700" />
            <span className="font-bold text-xs uppercase tracking-wider text-slate-900">
              CORIOLIS ARGO DECODER FLOWCHART SPECIFICATION
            </span>
          </div>
          <button
            onClick={() => setFlowchartModalOpen(false)}
            className="p-1 hover:bg-slate-200 text-slate-500 hover:text-slate-900 transition rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Embedded Iframe */}
        <div className="flex-1 bg-white">
          <iframe
            src="/decoder_flowchart.html"
            title="Decoder Flowchart"
            className="w-full h-full border-0"
          />
        </div>

        {/* Footer */}
        <div className="h-9 px-4 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-[11px] text-slate-600">
          <span>Authoritative pipeline architecture & sequence specification</span>
          <button
            onClick={() => setFlowchartModalOpen(false)}
            className="px-3 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-[10px] font-bold uppercase transition shadow-2xs"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
