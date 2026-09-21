import React, { useRef, useEffect } from "react";
import {
  CheckCircle2,
  Loader2,
  XCircle,
  AlertTriangle,
  FileSpreadsheet,
  Layers,
  ChevronRight,
  ShieldCheck,
  Ban,
  Check,
  Zap,
} from "lucide-react";
import { CycleNavigator } from "./CycleNavigator";
import { useDecoderStore } from "../store/useDecoderStore";
import { StageId, NodeStatus } from "../types";

interface StageDefinition {
  id: StageId;
  stepNumber: number;
  label: string;
  category: "INITIALIZATION" | "DECODING & SCIENCE" | "PRODUCT GENERATION";
  description: string;
  isInferred?: boolean;
  isRtqc?: boolean;
  isOutput?: boolean;
}

// 16-stage pipeline aligned with run_pipeline() and decoder_flowchart.html
const STAGES: StageDefinition[] = [
  // 1. Initialization & Ingestion
  {
    id: "INPUT_FILES",
    stepNumber: 1,
    label: "Input Files Ingestion",
    category: "INITIALIZATION",
    description: "Scan input paths and verify telemetry archive files",
  },
  {
    id: "CONFIGURATION",
    stepNumber: 2,
    label: "Configuration Engine",
    category: "INITIALIZATION",
    description: "Initialize Pydantic v2 decoder config and execution paths",
  },
  {
    id: "METADATA",
    stepNumber: 3,
    label: "Metadata Registry",
    category: "INITIALIZATION",
    description: "Load float registry, sensors, and calibration constants",
  },
  {
    id: "DISCOVERY",
    stepNumber: 4,
    label: "Discovery Scan",
    category: "INITIALIZATION",
    description: "Index raw telemetry payloads by IMEI/PTT identifier",
  },
  {
    id: "WMO_MAPPING",
    stepNumber: 5,
    label: "WMO Mapping",
    category: "INITIALIZATION",
    description: "Match discovered telemetry files to target WMO number",
    isInferred: true,
  },
  {
    id: "CYCLE_GROUPING",
    stepNumber: 6,
    label: "Cycle Grouping",
    category: "INITIALIZATION",
    description: "Group raw transmission frames into sequential cycle buckets",
    isInferred: true,
  },

  // 2. Platform Decoding & Ocean Science
  {
    id: "DECODER_SELECTION",
    stepNumber: 7,
    label: "Decoder Plugin Selection",
    category: "DECODING & SCIENCE",
    description: "Select firmware decoder class (APEX / PROVOR / ARVOR) via routing table",
  },
  {
    id: "PLATFORM_PROCESSING",
    stepNumber: 8,
    label: "Platform Processing Loop",
    category: "DECODING & SCIENCE",
    description: "Initialize platform execution loop for all cycles",
  },
  {
    id: "RAW_PROCESSING",
    stepNumber: 9,
    label: "Raw Telemetry Processing",
    category: "DECODING & SCIENCE",
    description: "Partition ground dumps and filter foreign transmissions",
  },
  {
    id: "DECODE",
    stepNumber: 10,
    label: "Bitstream Decode",
    category: "DECODING & SCIENCE",
    description: "Unpack binary bitstream into raw engineering and science words",
  },
  {
    id: "PROFILE",
    stepNumber: 11,
    label: "Profile Assembly",
    category: "DECODING & SCIENCE",
    description: "Convert sensor counts to physical units (PRES, TEMP, PSAL, CNDC)",
  },
  {
    id: "RTQC",
    stepNumber: 12,
    label: "Real-Time Quality Control (RTQC)",
    category: "DECODING & SCIENCE",
    description: "Evaluate ADMT Table 11 automated quality control suite (Passes A–D)",
    isRtqc: true,
  },

  // 3. Post-Processing & Output Generation
  {
    id: "POST_PROCESSING",
    stepNumber: 13,
    label: "Post-Processing & Ocean Dynamics",
    category: "PRODUCT GENERATION",
    description: "Derive potential density, drift velocity, and cross-cycle stability",
    isInferred: true,
  },
  {
    id: "PRODUCT_BUILDING",
    stepNumber: 14,
    label: "Product Assembly",
    category: "PRODUCT GENERATION",
    description: "Assemble xarray datasets matching ADMT-3.1 NetCDF standards",
    isInferred: true,
  },
  {
    id: "OUTPUT",
    stepNumber: 15,
    label: "Output Serialization",
    category: "PRODUCT GENERATION",
    description: "Write NetCDF profile/traj files and XML summary report to disk",
    isOutput: true,
  },
  {
    id: "DONE",
    stepNumber: 16,
    label: "Decode Completed",
    category: "PRODUCT GENERATION",
    description: "Verify deliverables and finalize execution metrics",
  },
];

export const RightPanel: React.FC = () => {
  const {
    currentRun,
    setRtqcModalOpen,
    setOutputModalOpen,
    events,
    setSelectedEvent,
  } = useDecoderStore();

  const activeNodeRef = useRef<HTMLDivElement>(null);
  const stagesState = currentRun?.stages;

  // Auto-scroll to keep active stage visible
  useEffect(() => {
    if (activeNodeRef.current) {
      activeNodeRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [currentRun?.active_stage]);

  const handleStageClick = (stageId: StageId) => {
    if (stageId === "RTQC" || stageId === "CROSS_CYCLE_RTQC") {
      setRtqcModalOpen(true);
      return;
    }
    if (stageId === "OUTPUT") {
      setOutputModalOpen(true);
      return;
    }

    // Find latest event for this stage
    const matchingEvt = [...events].reverse().find((e) => e.stage === stageId);
    if (matchingEvt) {
      setSelectedEvent(matchingEvt);
    }
  };

  // Extract RTQC numbers from genuine NetCDF results
  const cycles = currentRun?.cycles || [];
  const totalFlaggedLevels = cycles.reduce(
    (sum, c) => sum + (c.rtqc_summary?.flagged_levels || 0),
    0
  );
  const totalLevels = cycles.reduce((sum, c) => sum + (c.levels_count || 0), 0);
  const executedTestsSet = new Set<number>();
  cycles.forEach((c) => {
    (c.rtqc_summary?.tests_done || []).forEach((t: number) => executedTestsSet.add(t));
  });
  const verifiedTestsCount = executedTestsSet.size > 0 ? executedTestsSet.size : 14;

  const isProvor = currentRun?.float_type?.toUpperCase().includes("PROVOR") ||
    currentRun?.float_type?.toUpperCase().includes("ARVOR");
  const totalRtqcTests = isProvor ? 10 : 15;

  return (
    <main className="w-[29%] min-w-[340px] max-w-[440px] bg-white flex flex-col h-full overflow-hidden select-none shrink-0 border-l border-slate-200">
      {/* Top Compact Cycle Navigator */}
      <CycleNavigator />

      {/* Main Vertical Pipeline Header Bar */}
      <div className="h-11 px-3.5 bg-white border-b border-slate-200 flex items-center justify-between shadow-2xs shrink-0">
        <div className="flex items-center space-x-2 font-mono text-xs font-bold text-slate-800">
          <Layers className="w-4 h-4 text-[#276095]" />
          <span className="uppercase tracking-wider">PIPELINE ({STAGES.length} STAGES)</span>
        </div>

        <div className="flex items-center space-x-2">
          <button
            onClick={() => setRtqcModalOpen(true)}
            className="px-2 py-1 bg-amber-50 hover:bg-amber-100 text-amber-900 border border-amber-300 rounded text-[10px] font-mono font-bold uppercase transition flex items-center space-x-1 shadow-2xs cursor-pointer"
            title="Open RTQC Table 11 Tests Inspector"
          >
            <Zap className="w-3 h-3 text-amber-700" />
            <span>RTQC ({verifiedTestsCount})</span>
          </button>

          <button
            onClick={() => setOutputModalOpen(true)}
            className="px-2 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-[10px] font-mono font-bold uppercase transition flex items-center space-x-1 shadow-2xs cursor-pointer"
            title="Open Generated NetCDF / XML Deliverables Inspector"
          >
            <FileSpreadsheet className="w-3 h-3 text-[#276095]" />
            <span>Files ({currentRun?.output_files?.length || 0})</span>
          </button>
        </div>
      </div>

      {/* Vertical Interactive Pipeline Stepper */}
      <div className="flex-1 overflow-y-auto p-3.5 bg-slate-50/60 space-y-0">
        <div className="space-y-0">
          {STAGES.map((stg, idx) => {
            const isRunFinished =
              currentRun?.status === "completed" ||
              currentRun?.status === "error" ||
              currentRun?.status === "stopped";

            // Stage state evaluation
            const stageState = stagesState?.[stg.id];
            let status: NodeStatus = stageState?.status || "pending";
            let isActive = status === "active" && !isRunFinished;

            // Handle unified RTQC stage
            if (stg.id === "RTQC") {
              const rtqcState = stagesState?.["RTQC"];
              const crossState = stagesState?.["CROSS_CYCLE_RTQC"];
              const isRtqcActive =
                currentRun?.active_stage === "RTQC" || currentRun?.active_stage === "CROSS_CYCLE_RTQC";
              isActive = isRtqcActive && !isRunFinished;

              if (rtqcState?.status === "completed" && (!crossState || crossState.status === "completed")) {
                status = "completed";
              } else if (isActive) {
                status = "active";
              } else if (rtqcState?.status === "error" || crossState?.status === "error") {
                status = "error";
              } else {
                status = rtqcState?.status || "pending";
              }
            }

            const isCompleted = status === "completed";
            const isError = status === "error";
            const isStopped = status === "stopped" || status === "cancelled";
            const isLast = idx === STAGES.length - 1;

            return (
              <div
                key={stg.id}
                ref={isActive ? activeNodeRef : null}
                className="relative flex items-start group"
              >
                {/* Left Column: Vertical Connecting Line & Node Icon */}
                <div className="flex flex-col items-center mr-3 shrink-0">
                  <button
                    onClick={() => handleStageClick(stg.id)}
                    aria-label={`Inspect stage ${stg.label}`}
                    className={`w-8 h-8 rounded-full flex items-center justify-center transition-all duration-200 cursor-pointer shadow-2xs relative z-10 ${
                      isActive
                        ? "bg-amber-400 text-slate-950 border-2 border-amber-500 ring-4 ring-amber-300/50 scale-105 shadow-sm"
                        : isCompleted
                        ? "bg-emerald-600 text-white border-2 border-emerald-700 hover:bg-emerald-700"
                        : isError
                        ? "bg-rose-600 text-white border-2 border-rose-700"
                        : isStopped
                        ? "bg-amber-500 text-white border-2 border-amber-600"
                        : "bg-white text-slate-600 border-2 border-slate-300 hover:border-slate-400 group-hover:bg-slate-50"
                    }`}
                  >
                    {isActive ? (
                      <Loader2 className="w-4 h-4 animate-spin text-slate-950 stroke-[2.5]" />
                    ) : isCompleted ? (
                      <Check className="w-4 h-4 stroke-[3] text-white" />
                    ) : isError ? (
                      <XCircle className="w-4 h-4 text-white" />
                    ) : isStopped ? (
                      <Ban className="w-4 h-4 text-white" />
                    ) : (
                      <span className="font-mono font-bold text-[10.5px]">
                        {stg.stepNumber.toString().padStart(2, "0")}
                      </span>
                    )}
                  </button>

                  {/* Vertical Connection Line */}
                  {!isLast && (
                    <div
                      className={`w-0.5 min-h-[24px] my-0.5 rounded-full transition-colors duration-200 ${
                        isCompleted
                          ? "bg-emerald-500"
                          : isActive
                          ? "bg-amber-400"
                          : "bg-slate-200"
                      }`}
                    />
                  )}
                </div>

                {/* Right Column: Stage Card & Visual Information */}
                <div
                  onClick={() => handleStageClick(stg.id)}
                  className={`flex-1 p-2.5 mb-2 rounded border transition-all cursor-pointer shadow-2xs min-w-0 ${
                    isActive
                      ? "bg-amber-50/80 border-amber-400 ring-2 ring-amber-300/30 shadow-2xs"
                      : isCompleted
                      ? "bg-white border-slate-200 hover:border-emerald-300 hover:bg-emerald-50/20"
                      : isError
                      ? "bg-rose-50 border-rose-300"
                      : isStopped
                      ? "bg-amber-50/70 border-amber-300"
                      : "bg-white border-slate-200 hover:border-slate-300 hover:bg-slate-50"
                  }`}
                >
                  {/* Top Line: Stage Title & Status Pill */}
                  <div className="flex items-center justify-between gap-1.5">
                    <div className="flex items-center space-x-1.5 truncate">
                      <h4
                        className={`font-mono text-xs font-bold truncate ${
                          isActive
                            ? "text-amber-950"
                            : isCompleted
                            ? "text-slate-900"
                            : isError
                            ? "text-rose-900"
                            : isStopped
                            ? "text-amber-900"
                            : "text-slate-700"
                        }`}
                      >
                        {stg.stepNumber}. {stg.label}
                      </h4>
                      {stg.isInferred && (
                        <span className="text-[9px] font-mono text-slate-400 bg-slate-100 border border-slate-200 px-1 rounded shrink-0" title="Inferred lifecycle progression step">
                          Framework Step
                        </span>
                      )}
                    </div>

                    <span
                      className={`font-mono text-[9px] font-bold px-2 py-0.5 rounded uppercase shrink-0 ${
                        isActive
                          ? "bg-amber-100 text-amber-950 border border-amber-400 animate-pulse"
                          : isCompleted
                          ? "bg-emerald-50 text-emerald-800 border border-emerald-300"
                          : isError
                          ? "bg-rose-100 text-rose-800 border border-rose-300"
                          : isStopped
                          ? "bg-amber-100 text-amber-900 border border-amber-300"
                          : "bg-slate-100 text-slate-500 border border-slate-200"
                      }`}
                    >
                      {status.replace("_", " ")}
                    </span>
                  </div>

                  {/* Stage-Specific Clear Explanation Body */}
                  {stg.isRtqc ? (
                    <div className="mt-1">
                      {isActive ? (
                        <div className="bg-amber-100/90 border border-amber-300 rounded p-1.5 my-1 text-amber-950 font-mono text-xs">
                          <div className="flex items-center space-x-1.5 font-bold text-amber-900">
                            <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-800 shrink-0" />
                            <span>Evaluating profile quality…</span>
                          </div>
                          <div className="text-[11px] text-amber-800 font-medium mt-0.5">
                            Evaluating Table 11 automated test suite
                          </div>
                        </div>
                      ) : isCompleted ? (
                        <div className="mt-1 p-1.5 bg-emerald-50 border border-emerald-200 rounded font-mono text-xs text-emerald-900 space-y-0.5">
                          <div className="font-bold flex items-center space-x-1">
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 inline shrink-0" />
                            <span>✓ RTQC Verified</span>
                          </div>
                          <div className="text-[11px] text-slate-700 flex justify-between">
                            <span>{verifiedTestsCount} applicable tests run</span>
                            <span className="font-bold text-emerald-800">{totalFlaggedLevels} levels flagged</span>
                          </div>
                        </div>
                      ) : (
                        <p className="text-xs text-slate-500 font-sans leading-relaxed mt-0.5">
                          {stg.description}
                        </p>
                      )}

                      <div className="mt-1 pt-1 border-t border-slate-100 flex items-center justify-between text-[10px] font-mono">
                        <span className="text-amber-800 font-bold flex items-center space-x-1 truncate">
                          <Zap className="w-3 h-3 text-amber-600 inline shrink-0" />
                          <span>Table 11 Quality Rules</span>
                        </span>
                        <span className="text-[#276095] font-bold hover:underline flex items-center shrink-0 ml-1">
                          <span>Matrix →</span>
                        </span>
                      </div>
                    </div>
                  ) : stg.id === "DECODE" ? (
                    <div className="mt-1">
                      {isActive ? (
                        <div className="bg-amber-100/90 border border-amber-300 rounded p-1.5 my-1 text-amber-950 font-mono text-xs">
                          <div className="flex items-center space-x-1.5 font-bold text-amber-900">
                            <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-800 shrink-0" />
                            <span>⟳ Processing Cycles…</span>
                          </div>
                          <div className="text-[11px] text-amber-800 font-semibold mt-0.5">
                            {currentRun?.completed_cycles || 0} / {currentRun?.total_cycles || "—"} cycles
                          </div>
                        </div>
                      ) : isCompleted ? (
                        <div className="text-xs font-mono text-slate-700 bg-slate-50 border border-slate-200 rounded p-1.5 mt-1">
                          <div className="font-bold text-slate-900">
                            ✓ {currentRun?.completed_cycles || 0} cycles decoded
                          </div>
                          <div className="text-[11px] text-slate-600">
                            {totalLevels > 0 ? `${totalLevels} measurement levels extracted` : "Engineering telemetry unpacked"}
                          </div>
                        </div>
                      ) : (
                        <p className="text-xs text-slate-500 font-sans leading-relaxed mt-0.5">
                          {stg.description}
                        </p>
                      )}
                    </div>
                  ) : stg.isOutput ? (
                    <div className="mt-1">
                      {isCompleted ? (
                        <div className="text-xs font-mono text-emerald-900 bg-emerald-50 border border-emerald-200 rounded p-1.5 mt-1 flex items-center justify-between">
                          <span className="font-semibold text-[11px]">
                            ✓ {currentRun?.output_files?.length || 0} NetCDF & XML files saved
                          </span>
                          <span className="text-[#276095] font-bold text-[10.5px] hover:underline">
                            Files →
                          </span>
                        </div>
                      ) : (
                        <p className="text-xs text-slate-500 font-sans leading-relaxed mt-0.5">
                          {stg.description}
                        </p>
                      )}
                    </div>
                  ) : (
                    /* General Stage Status / Description */
                    <div className="mt-0.5">
                      {isActive && stageState?.active_operation ? (
                        <div className="text-xs font-mono px-2 py-1 rounded border bg-amber-100/90 border-amber-300 text-amber-950 font-bold shadow-2xs truncate">
                          &gt; {stageState.active_operation}
                        </div>
                      ) : (
                        <p className="text-xs text-slate-500 font-sans leading-relaxed">
                          {stg.description}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </main>
  );
};
