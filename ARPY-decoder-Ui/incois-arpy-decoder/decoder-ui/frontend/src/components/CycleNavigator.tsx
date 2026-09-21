import React from "react";
import { Check, Loader2, AlertTriangle, Layers } from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";

export const CycleNavigator: React.FC = () => {
  const { currentRun, setSelectedCycle, setCycleModalOpen } = useDecoderStore();

  if (!currentRun || !currentRun.cycles || currentRun.cycles.length === 0) {
    return (
      <div className="bg-white border-b border-slate-200 px-3 py-1.5 flex items-center justify-between text-xs text-slate-500 select-none font-mono">
        <div className="flex items-center space-x-2 text-[11px]">
          <span className="font-bold text-slate-700">CYCLES:</span>
          <span className="text-slate-400">Awaiting telemetry cycle discovery...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white border-b border-slate-200 px-3 py-1.5 flex items-center justify-between select-none">
      <div className="flex items-center space-x-2.5 overflow-x-auto py-0.5">
        <div className="flex items-center space-x-1 font-mono text-[11px] font-bold text-slate-800 shrink-0">
          <Layers className="w-3.5 h-3.5 text-sky-700" />
          <span>CYCLES ({currentRun.completed_cycles}/{currentRun.total_cycles}):</span>
        </div>

        <div className="flex items-center space-x-1">
          {currentRun.cycles.map((c) => {
            const isCompleted = c.status === "completed";
            const isActive = c.status === "active";
            const isError = c.status === "error";

            return (
              <button
                key={c.cycle_number}
                onClick={() => {
                  setSelectedCycle(c.cycle_number);
                  setCycleModalOpen(true);
                }}
                className={`flex items-center space-x-1 px-2 py-0.5 font-mono text-[11px] font-bold border rounded transition ${
                  isCompleted
                    ? "bg-emerald-50 text-emerald-800 border-emerald-300 hover:bg-emerald-100"
                    : isActive
                    ? "bg-sky-50 text-sky-800 border-sky-400 animate-pulse"
                    : isError
                    ? "bg-rose-50 text-rose-800 border-rose-300 hover:bg-rose-100"
                    : "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100"
                }`}
              >
                {isCompleted ? (
                  <Check className="w-3 h-3 text-emerald-600" />
                ) : isActive ? (
                  <Loader2 className="w-3 h-3 text-sky-600 animate-spin" />
                ) : (
                  <span className="w-1.5 h-1.5 bg-slate-400 inline-block rounded-xs" />
                )}
                <span>{c.cycle_number >= 0 ? `${c.cycle_number}`.padStart(2, "0") : `c${c.cycle_number}`}</span>
              </button>
            );
          })}
        </div>
      </div>

      <span className="text-[10px] text-slate-500 font-mono shrink-0 hidden md:inline ml-3 uppercase">
        Click cycle to inspect profile data
      </span>
    </div>
  );
};
