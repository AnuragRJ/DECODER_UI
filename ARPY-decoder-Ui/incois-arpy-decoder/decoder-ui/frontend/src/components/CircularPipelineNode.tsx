import React, { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import {
  CheckCircle2,
  Clock,
  Loader2,
  AlertTriangle,
  XCircle,
  Cpu,
  Layers,
  Search,
  Hash,
  Filter,
  FileCheck,
  FileSpreadsheet,
  Binary,
  Compass,
  Zap,
  Ban,
} from "lucide-react";
import { NodeStatus } from "../types";

export interface PipelineNodeData {
  label: string;
  sublabel?: string;
  stageKey: string;
  status: NodeStatus;
  activeOp?: string;
  duration?: number;
  itemCount?: number;
  error?: string;
  selected?: boolean;
  onSelect?: (stageKey: string) => void;
  iconType?: string;
  passInfo?: string;
  isRtqc?: boolean;
}

const getStageIcon = (type?: string, status?: NodeStatus) => {
  if (status === "active") {
    return <Loader2 className="w-4 h-4 animate-spin text-sky-700" />;
  }
  if (status === "error") {
    return <XCircle className="w-4 h-4 text-rose-600" />;
  }
  if (status === "completed") {
    return <CheckCircle2 className="w-4 h-4 text-emerald-600" />;
  }
  if (status === "stopped" || status === "cancelled") {
    return <Ban className="w-4 h-4 text-amber-700" />;
  }

  switch (type) {
    case "input":
      return <Binary className="w-4 h-4 text-slate-500" />;
    case "config":
      return <Cpu className="w-4 h-4 text-slate-500" />;
    case "meta":
      return <FileCheck className="w-4 h-4 text-slate-500" />;
    case "discovery":
      return <Search className="w-4 h-4 text-slate-500" />;
    case "wmo":
      return <Compass className="w-4 h-4 text-slate-500" />;
    case "cycle_group":
      return <Layers className="w-4 h-4 text-slate-500" />;
    case "decoder_select":
      return <Filter className="w-4 h-4 text-slate-500" />;
    case "rtqc":
      return <Zap className="w-4 h-4 text-amber-600" />;
    case "output":
      return <FileSpreadsheet className="w-4 h-4 text-sky-700" />;
    default:
      return <Clock className="w-4 h-4 text-slate-400" />;
  }
};

const getStatusColor = (status: NodeStatus, isSelected?: boolean) => {
  if (isSelected) {
    return "border-amber-400 bg-amber-50/50 text-slate-900 ring-2 ring-amber-300";
  }
  switch (status) {
    case "active":
      return "border-sky-600 bg-sky-50 text-sky-950 ring-2 ring-sky-200";
    case "completed":
      return "border-emerald-500 bg-white text-slate-900";
    case "stopped":
    case "cancelled":
      return "border-amber-500 bg-amber-50/80 text-amber-950";
    case "error":
      return "border-rose-500 bg-rose-50 text-rose-950";
    case "flagged":
      return "border-amber-500 bg-amber-50 text-amber-950";
    case "not_run":
      return "border-slate-200 bg-slate-50 text-slate-400 opacity-60";
    case "pending":
    default:
      return "border-slate-300 bg-white text-slate-700";
  }
};

export const CircularPipelineNode = memo(({ data }: { data: PipelineNodeData }) => {
  const {
    label,
    sublabel,
    stageKey,
    status = "pending",
    activeOp,
    duration,
    itemCount,
    selected,
    onSelect,
    iconType,
    passInfo,
    isRtqc,
  } = data;

  const statusStyles = getStatusColor(status, selected);

  return (
    <div
      onClick={() => onSelect && onSelect(stageKey)}
      className={`group relative flex flex-col items-center cursor-pointer transition-all duration-150 select-none ${
        selected ? "scale-[1.02]" : "hover:scale-[1.01]"
      }`}
      style={{ minWidth: "185px", maxWidth: "220px" }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-2 !h-2 !bg-slate-400 !border !border-white"
      />

      {/* Main Node Card */}
      <div
        className={`w-full p-2.5 border rounded ${statusStyles} shadow-2xs flex flex-col items-center text-center`}
      >
        {/* Top Status Header */}
        <div className="w-full flex items-center justify-between text-[9px] font-mono tracking-wider mb-1.5 pb-1 border-b border-slate-100">
          <span className="uppercase font-semibold text-slate-500">{stageKey.replace("_", " ")}</span>
          {duration !== undefined && duration > 0 ? (
            <span className="text-slate-600">{duration.toFixed(2)}s</span>
          ) : (
            <span
              className={`uppercase font-bold ${
                status === "active"
                  ? "text-sky-700"
                  : status === "completed"
                  ? "text-emerald-700"
                  : status === "error"
                  ? "text-rose-700"
                  : "text-slate-400"
              }`}
            >
              {status}
            </span>
          )}
        </div>

        {/* Circular Icon & Title */}
        <div className="flex items-center space-x-2 my-0.5">
          <div
            className={`w-7 h-7 rounded-full flex items-center justify-center border ${
              status === "active"
                ? "border-sky-500 bg-sky-100/80"
                : status === "completed"
                ? "border-emerald-400 bg-emerald-50"
                : status === "error"
                ? "border-rose-400 bg-rose-50"
                : "border-slate-200 bg-slate-50"
            }`}
          >
            {getStageIcon(iconType, status)}
          </div>
          <div className="text-left">
            <div className="text-xs font-bold font-mono tracking-tight text-slate-900">
              {label}
            </div>
            {sublabel && (
              <div className="text-[9px] font-mono text-slate-500 truncate max-w-[125px]">
                {sublabel}
              </div>
            )}
          </div>
        </div>

        {/* Active Op / Sub-operation display */}
        {activeOp ? (
          <div className="w-full mt-1 px-1.5 py-0.5 bg-sky-100/70 border border-sky-300 rounded text-[9px] font-mono text-sky-900 truncate text-left font-medium">
            &gt; {activeOp}
          </div>
        ) : isRtqc && passInfo ? (
          <div className="w-full mt-1 px-1.5 py-0.5 bg-amber-50 border border-amber-200 rounded text-[9px] font-mono text-amber-900 truncate text-left font-medium">
            Pass: {passInfo}
          </div>
        ) : itemCount !== undefined && itemCount > 0 ? (
          <div className="w-full mt-1 px-1.5 py-0.5 bg-slate-100 border border-slate-200 rounded text-[9px] font-mono text-slate-700 text-left">
            Items: {itemCount}
          </div>
        ) : null}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-2 !h-2 !bg-slate-400 !border !border-white"
      />
    </div>
  );
});

CircularPipelineNode.displayName = "CircularPipelineNode";
