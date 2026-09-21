import React from "react";
import {
  Compass,
  Radio,
  FileCheck,
  FolderTree,
  Cpu,
  Layers,
  Info,
  Calendar,
  Waves,
} from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";

export const LeftPanel: React.FC = () => {
  const { selectedPreset, currentRun, isRunning } = useDecoderStore();

  const wmo = currentRun?.wmo || selectedPreset?.wmo || 2901304;
  const platformType = currentRun?.float_type || selectedPreset?.platform_type || "APEX";
  const transmissionType = currentRun?.transmission_type || selectedPreset?.transmission_type || "ARGOS";
  const decoderId = currentRun?.decoder_id || selectedPreset?.decoder_id || 1005;
  const decoderVersion = currentRun?.decoder_version || selectedPreset?.decoder_version || "020811";
  const metaBackend = selectedPreset?.metadata_backend || "csv";
  const inputFilesCount = currentRun?.total_files || selectedPreset?.input_file_count || 5;

  return (
    <aside className="w-[19.5%] min-w-[240px] max-w-[285px] bg-[#276095] border-r border-[#1d4972] flex flex-col h-full overflow-hidden select-none shrink-0 text-white">
      {/* Platform Context Header */}
      <div className="h-11 px-3 bg-[#1d4972] border-b border-[#163857] flex items-center justify-between text-white shadow-2xs">
        <div className="flex items-center space-x-2 font-mono text-xs font-bold tracking-wider">
          <Compass className="w-4 h-4 text-sky-200" />
          <span className="uppercase">PLATFORM CONTEXT</span>
        </div>
        <span className="text-[11px] font-mono px-2 py-0.5 bg-white text-[#276095] rounded font-extrabold shadow-2xs">
          WMO {wmo}
        </span>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 text-xs bg-[#276095]">
        {/* Section 1: Float Hardware Identification */}
        <div className="border border-white/20 rounded bg-[#1e4e7c] overflow-hidden shadow-2xs">
          <div className="bg-[#183f65] px-2.5 py-1.5 text-[11px] font-bold text-sky-100 border-b border-white/10 flex items-center justify-between font-mono">
            <span>PLATFORM SPECIFICATION</span>
            <Radio className="w-3.5 h-3.5 text-sky-200" />
          </div>
          <table className="w-full text-left font-mono text-[11px]">
            <tbody className="divide-y divide-white/10">
              <tr>
                <td className="py-1.5 px-2.5 text-sky-200 font-medium">Platform Family</td>
                <td className="py-1.5 px-2.5 font-bold text-white">{platformType}</td>
              </tr>
              <tr>
                <td className="py-1.5 px-2.5 text-sky-200 font-medium">Carrier & Telemetry</td>
                <td className="py-1.5 px-2.5">
                  <span className="px-1.5 py-0.2 bg-amber-400 text-slate-950 font-bold rounded text-[10px] shadow-2xs">
                    {transmissionType}
                  </span>
                </td>
              </tr>
              <tr>
                <td className="py-1.5 px-2.5 text-sky-200 font-medium">Decoder ID</td>
                <td className="py-1.5 px-2.5 font-bold text-white">{decoderId}</td>
              </tr>
              <tr>
                <td className="py-1.5 px-2.5 text-sky-200 font-medium">Decoder Firmware</td>
                <td className="py-1.5 px-2.5 text-sky-100 font-semibold">{decoderVersion}</td>
              </tr>
              <tr>
                <td className="py-1.5 px-2.5 text-sky-200 font-medium">Metadata Source</td>
                <td className="py-1.5 px-2.5 uppercase font-bold text-white">{metaBackend}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Section 2: Telemetry Input Archive */}
        <div className="border border-white/20 rounded bg-[#1e4e7c] overflow-hidden shadow-2xs">
          <div className="bg-[#183f65] px-2.5 py-1.5 text-[11px] font-bold text-sky-100 border-b border-white/10 flex items-center justify-between font-mono">
            <span>INPUT TELEMETRY ARCHIVE</span>
            <FolderTree className="w-3.5 h-3.5 text-sky-200" />
          </div>
          <div className="p-2.5 space-y-2 font-mono text-[11px]">
            <div>
              <span className="text-[10px] text-sky-200 block uppercase font-bold">Input Root Path</span>
              <div className="p-1.5 bg-[#163857] border border-white/15 rounded text-sky-100 text-[10px] break-all">
                {selectedPreset?.input_path || "Auto-detected project telemetry archive"}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-1.5 text-[11px]">
              <div className="p-1.5 bg-[#163857] border border-white/15 rounded">
                <span className="text-[9px] text-sky-200 block font-bold">RAW FILES</span>
                <span className="font-bold text-white">{inputFilesCount}</span>
              </div>
              <div className="p-1.5 bg-[#163857] border border-white/15 rounded">
                <span className="text-[9px] text-sky-200 block font-bold">DETECTED CYCLES</span>
                <span className="font-bold text-white">{currentRun?.total_cycles || "—"}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Section 3: Float Deployment Description */}
        {selectedPreset?.description && (
          <div className="border border-white/20 rounded bg-[#1e4e7c] overflow-hidden shadow-2xs">
            <div className="bg-[#183f65] px-2.5 py-1.5 text-[11px] font-bold text-sky-100 border-b border-white/10 flex items-center space-x-1.5 font-mono">
              <Info className="w-3.5 h-3.5 text-sky-200" />
              <span>DEPLOYMENT CONTEXT</span>
            </div>
            <div className="p-2.5 text-[11px] text-sky-100 leading-relaxed font-sans">
              {selectedPreset.description}
            </div>
          </div>
        )}

        {/* Section 4: Mission Pipeline Stages Summary */}
        <div className="border border-white/20 rounded bg-[#1e4e7c] overflow-hidden shadow-2xs">
          <div className="bg-[#183f65] px-2.5 py-1.5 text-[11px] font-bold text-sky-100 border-b border-white/10 flex items-center justify-between font-mono">
            <span>PIPELINE EXECUTION STATE</span>
            <Layers className="w-3.5 h-3.5 text-sky-200" />
          </div>
          <div className="p-2.5 space-y-1.5 font-mono text-[11px]">
            <div className="flex justify-between items-center">
              <span className="text-sky-200">Active Stage:</span>
              <span
                className={`font-bold ${
                  isRunning
                    ? "text-amber-300 animate-pulse"
                    : currentRun?.status === "completed"
                    ? "text-emerald-300"
                    : currentRun?.status === "error"
                    ? "text-rose-300"
                    : "text-white"
                }`}
              >
                {currentRun?.active_stage ? currentRun.active_stage.replace("_", " ") : "STANDBY"}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sky-200">Completed Cycles:</span>
              <span className="font-bold text-white">
                {currentRun?.completed_cycles || 0} / {currentRun?.total_cycles || "—"}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sky-200">Generated Deliverables:</span>
              <span className="font-bold text-emerald-300">
                {currentRun?.output_files?.length || 0} Products
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Footer Info */}
      <div className="h-8 px-3 border-t border-[#163857] bg-[#1d4972] flex items-center justify-between text-[10px] text-sky-200 font-mono">
        <span>INCOIS ARPY OBSERVATORY</span>
        <span>ADMT v3.1 CONFORMANT</span>
      </div>
    </aside>
  );
};
