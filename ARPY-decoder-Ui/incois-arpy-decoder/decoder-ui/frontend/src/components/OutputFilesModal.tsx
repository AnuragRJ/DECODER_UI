import React, { useState } from "react";
import { X, Layers, Hash, Copy, Check, FileSpreadsheet } from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";
import { OutputFileInfo } from "../types";

export const OutputFilesModal: React.FC = () => {
  const {
    isOutputModalOpen,
    setOutputModalOpen,
    currentRun,
    selectedOutputFile,
    setSelectedOutputFile,
  } = useDecoderStore();
  const [copiedHash, setCopiedHash] = useState<string | null>(null);

  if (!isOutputModalOpen || !currentRun) return null;

  const files = currentRun.output_files || [];
  const activeFile: OutputFileInfo | null = selectedOutputFile || files[0] || null;

  const handleCopyHash = (hash: string) => {
    navigator.clipboard.writeText(hash);
    setCopiedHash(hash);
    setTimeout(() => setCopiedHash(null), 2000);
  };

  return (
    <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-2xs z-50 flex items-center justify-center p-4 select-none font-mono text-slate-800">
      <div className="bg-white border border-slate-300 w-full max-w-6xl max-h-[88vh] rounded shadow-xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="h-10 px-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <FileSpreadsheet className="w-4 h-4 text-sky-700" />
            <span className="font-bold text-xs uppercase tracking-wider text-slate-900">
              ADMT-3.1 OUTPUT DELIVERABLES & NETCDF INSPECTOR
            </span>
            <span className="px-1.5 py-0.5 text-[10px] font-bold bg-sky-50 text-sky-800 border border-sky-200 rounded">
              {files.length} PRODUCTS
            </span>
          </div>
          <button
            onClick={() => setOutputModalOpen(false)}
            className="p-1 hover:bg-slate-200 text-slate-500 hover:text-slate-900 transition rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content Body: Left File List + Right File Inspector */}
        <div className="flex-1 flex overflow-hidden">
          {/* File Selector Sidebar */}
          <div className="w-80 border-r border-slate-200 bg-slate-50/50 overflow-y-auto p-2 space-y-1 text-xs">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 px-1 block pb-1 border-b border-slate-200">
              GENERATED FILES ({files.length})
            </span>
            {files.length === 0 ? (
              <div className="p-3 text-[11px] text-slate-400 italic">No files generated yet.</div>
            ) : (
              files.map((f) => {
                const isSelected = activeFile?.filename === f.filename;
                return (
                  <button
                    key={f.filename}
                    onClick={() => setSelectedOutputFile(f)}
                    className={`w-full text-left p-2 border rounded transition flex flex-col space-y-1 ${
                      isSelected
                        ? "bg-sky-50 border-sky-400 text-slate-900 shadow-2xs"
                        : "bg-white border-slate-200 text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold truncate text-[11px] text-slate-900">{f.filename}</span>
                      <span className="text-[9px] px-1 uppercase bg-slate-100 text-slate-600 border border-slate-200 rounded">
                        {f.category}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[10px] text-slate-500">
                      <span>{(f.filesize_bytes / 1024).toFixed(1)} KB</span>
                      <span className="text-emerald-700 font-mono">
                        SHA: {f.checksum_sha256.slice(0, 8)}...
                      </span>
                    </div>
                  </button>
                );
              })
            )}
          </div>

          {/* Detailed File Inspector */}
          <div className="flex-1 overflow-y-auto p-3 space-y-3 text-xs select-text bg-white">
            {activeFile ? (
              <>
                {/* File Overview Card */}
                <div className="p-2.5 bg-slate-50 border border-slate-200 rounded space-y-2">
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="font-bold text-xs text-sky-800">{activeFile.filename}</h4>
                      <p className="text-[10px] text-slate-500 font-mono">{activeFile.filepath}</p>
                    </div>
                    <span className="px-2 py-0.5 text-[10px] font-bold bg-white text-slate-700 border border-slate-200 rounded">
                      {(activeFile.filesize_bytes / 1024).toFixed(2)} KB
                    </span>
                  </div>

                  <div className="flex items-center justify-between bg-white p-1.5 border border-slate-200 rounded text-[10px]">
                    <span className="text-slate-500 flex items-center space-x-1">
                      <Hash className="w-3 h-3 text-amber-600" />
                      <span>SHA-256 CHECKSUM:</span>
                    </span>
                    <div className="flex items-center space-x-2">
                      <code className="text-emerald-700">{activeFile.checksum_sha256}</code>
                      <button
                        onClick={() => handleCopyHash(activeFile.checksum_sha256)}
                        className="p-0.5 hover:bg-slate-100 text-slate-500 hover:text-slate-900 rounded"
                        title="Copy Checksum"
                      >
                        {copiedHash === activeFile.checksum_sha256 ? (
                          <Check className="w-3 h-3 text-emerald-600" />
                        ) : (
                          <Copy className="w-3 h-3" />
                        )}
                      </button>
                    </div>
                  </div>
                </div>

                {/* NetCDF Dimensions */}
                {Object.keys(activeFile.dimensions).length > 0 && (
                  <div className="space-y-1">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600 block">
                      NETCDF DIMENSIONS
                    </span>
                    <div className="grid grid-cols-4 gap-1.5 text-[10px]">
                      {Object.entries(activeFile.dimensions).map(([dim, val]) => (
                        <div key={dim} className="bg-slate-50 p-1.5 border border-slate-200 rounded">
                          <span className="text-slate-500 text-[9px] block">{dim}</span>
                          <span className="text-amber-900 font-bold">{val}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Variables List */}
                {activeFile.variables.length > 0 && (
                  <div className="space-y-1">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600 block">
                      VARIABLES ({activeFile.variables.length})
                    </span>
                    <div className="p-2 bg-slate-50 border border-slate-200 rounded flex flex-wrap gap-1 text-[10px]">
                      {activeFile.variables.map((v) => (
                        <span
                          key={v}
                          className="px-1.5 py-0.5 bg-white border border-slate-200 rounded text-slate-700"
                        >
                          {v}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Global Attributes */}
                {Object.keys(activeFile.global_attrs).length > 0 && (
                  <div className="space-y-1">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600 block">
                      GLOBAL ATTRIBUTES
                    </span>
                    <div className="p-2 bg-slate-50 border border-slate-200 rounded text-[10px] space-y-1 max-h-48 overflow-y-auto">
                      {Object.entries(activeFile.global_attrs).map(([k, v]) => (
                        <div
                          key={k}
                          className="flex justify-between border-b border-slate-100 pb-0.5"
                        >
                          <span className="text-sky-800 font-medium">{k}:</span>
                          <span className="text-slate-700 truncate max-w-[380px]">{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* XML Content if XML report */}
                {activeFile.xml_content && (
                  <div className="space-y-1">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600 block">
                      CORIOLIS XML REPORT BODY
                    </span>
                    <pre className="p-2 bg-slate-50 border border-slate-200 rounded text-[10px] text-slate-800 overflow-x-auto max-h-60 font-mono">
                      {activeFile.xml_content}
                    </pre>
                  </div>
                )}
              </>
            ) : (
              <div className="h-48 flex items-center justify-center text-slate-400">
                <span>Select a file from the list to inspect metadata</span>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="h-9 px-4 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-[11px] text-slate-600">
          <span>NETCDF3_CLASSIC • ADMT v3.1 CONVENTIONS</span>
          <button
            onClick={() => setOutputModalOpen(false)}
            className="px-3 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-[10px] font-bold uppercase transition shadow-2xs"
          >
            Close Viewer
          </button>
        </div>
      </div>
    </div>
  );
};
