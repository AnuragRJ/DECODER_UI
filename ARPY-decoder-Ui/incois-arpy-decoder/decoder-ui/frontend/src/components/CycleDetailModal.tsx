import React from "react";
import { X, Layers, MapPin, Calendar, ShieldCheck, FileText } from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";

export const CycleDetailModal: React.FC = () => {
  const { isCycleModalOpen, setCycleModalOpen, selectedCycle, currentRun } = useDecoderStore();

  if (!isCycleModalOpen || selectedCycle === null || !currentRun) return null;

  const cycleRecord = currentRun.cycles.find((c) => c.cycle_number === selectedCycle);

  const formatQcBadge = (qc: number) => {
    if (qc === 1) {
      return (
        <span className="px-1.5 py-0.2 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded font-bold">
          1
        </span>
      );
    }
    if (qc === 2) {
      return (
        <span className="px-1.5 py-0.2 bg-sky-50 text-sky-800 border border-sky-200 rounded font-bold">
          2
        </span>
      );
    }
    if (qc === 3) {
      return (
        <span className="px-1.5 py-0.2 bg-amber-50 text-amber-900 border border-amber-200 rounded font-bold">
          3
        </span>
      );
    }
    if (qc === 4) {
      return (
        <span className="px-1.5 py-0.2 bg-rose-50 text-rose-800 border border-rose-200 rounded font-bold">
          4
        </span>
      );
    }
    return (
      <span className="px-1.5 py-0.2 bg-slate-100 text-slate-500 border border-slate-200 rounded">
        9
      </span>
    );
  };

  return (
    <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-2xs z-50 flex items-center justify-center p-4 select-none font-mono text-slate-800">
      <div className="bg-white border border-slate-300 w-full max-w-5xl max-h-[88vh] rounded shadow-xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="h-10 px-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Layers className="w-4 h-4 text-sky-700" />
            <span className="font-bold text-xs uppercase tracking-wider text-slate-900">
              CYCLE {selectedCycle >= 0 ? `${selectedCycle}`.padStart(2, "0") : `c${selectedCycle}`} :: PHYSICAL PROFILE & TELEMETRY
            </span>
            <span className="px-1.5 py-0.5 text-[10px] font-bold bg-emerald-50 text-emerald-800 border border-emerald-200 rounded">
              {cycleRecord?.levels_count || 0} LEVELS
            </span>
          </div>
          <button
            onClick={() => setCycleModalOpen(false)}
            className="p-1 hover:bg-slate-200 text-slate-500 hover:text-slate-900 transition rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Position & Time Metadata Bar */}
        <div className="grid grid-cols-4 gap-2 p-2.5 bg-slate-50 border-b border-slate-200 text-[11px]">
          <div className="bg-white p-2 border border-slate-200 rounded flex items-center space-x-2">
            <MapPin className="w-3.5 h-3.5 text-sky-700 shrink-0" />
            <div>
              <span className="text-slate-500 text-[9px] block uppercase font-bold">LAT / LON</span>
              <span className="text-slate-900 font-bold">
                {cycleRecord?.latitude !== undefined ? `${cycleRecord.latitude.toFixed(3)}°N` : "N/A"},{" "}
                {cycleRecord?.longitude !== undefined ? `${cycleRecord.longitude.toFixed(3)}°E` : "N/A"}
              </span>
            </div>
          </div>

          <div className="bg-white p-2 border border-slate-200 rounded flex items-center space-x-2">
            <Calendar className="w-3.5 h-3.5 text-amber-700 shrink-0" />
            <div>
              <span className="text-slate-500 text-[9px] block uppercase font-bold">JULD JULIAN DAY</span>
              <span className="text-slate-900 font-bold">
                {cycleRecord?.juld !== undefined ? `${cycleRecord.juld.toFixed(4)}` : "N/A"}
              </span>
            </div>
          </div>

          <div className="bg-white p-2 border border-slate-200 rounded flex items-center space-x-2">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
            <div>
              <span className="text-slate-500 text-[9px] block uppercase font-bold">POSITION QC</span>
              <span className="text-emerald-700 font-bold">FLAG {cycleRecord?.position_qc || "1"}</span>
            </div>
          </div>

          <div className="bg-white p-2 border border-slate-200 rounded flex items-center space-x-2">
            <Layers className="w-3.5 h-3.5 text-indigo-700 shrink-0" />
            <div>
              <span className="text-slate-500 text-[9px] block uppercase font-bold">MAX DEPTH</span>
              <span className="text-indigo-900 font-bold">
                {cycleRecord?.ctd_samples?.length
                  ? `${cycleRecord.ctd_samples[cycleRecord.ctd_samples.length - 1].PRES.toFixed(1)} dbar`
                  : "N/A"}
              </span>
            </div>
          </div>
        </div>

        {/* BGC provenance strip (301 floats only; real BR file facts) */}
        {cycleRecord?.bgc_source_file && (
          <div className="px-2.5 py-2 bg-slate-50 border-b border-slate-200 text-[11px] flex items-center gap-2 flex-wrap">
            <span className="text-slate-500 text-[9px] uppercase font-bold">BGC</span>
            <span className="text-slate-900 font-bold">{cycleRecord.bgc_source_file}</span>
            {cycleRecord.bgc_n_prof != null && (
              <span className="text-slate-500">N_PROF {cycleRecord.bgc_n_prof}</span>
            )}
            <span className="text-slate-500">
              {(cycleRecord.bgc_profiles || []).length} profiles
            </span>
            {cycleRecord.has_core === false && (
              <span className="px-1.5 py-0.5 text-[10px] font-bold bg-amber-50 text-amber-900 border border-amber-300 rounded">
                BGC-ONLY — NO CORE R PROFILE
              </span>
            )}
            {cycleRecord.matches_g2_signature && (
              <span className="px-1.5 py-0.5 text-[10px] font-bold bg-amber-50 text-amber-900 border border-amber-300 rounded">
                ⚠ SENSOR DATA ABSENT — SUSPECTED WRITER ARTIFACT
              </span>
            )}
          </div>
        )}

        {/* CTD Measurement Profile Table */}
        <div className="flex-1 overflow-y-auto p-3 select-text bg-white">
          {!cycleRecord?.ctd_samples || cycleRecord.ctd_samples.length === 0 ? (
            <div className="h-48 flex flex-col items-center justify-center text-slate-400 space-y-1.5 select-none font-mono">
              <FileText className="w-6 h-6 text-slate-300" />
              <p className="text-xs">
                {cycleRecord?.has_core === false
                  ? "BGC-only cycle (no core CTD profile — BGC series are shown in the Results workspace)"
                  : "Engineering telemetry only (no CTD profile levels recorded for this transmission)"}
              </p>
            </div>
          ) : (
            <div className="border border-slate-200 rounded overflow-hidden">
              <table className="w-full text-left text-[11px]">
                <thead className="bg-slate-50 text-slate-600 uppercase text-[10px] tracking-wider border-b border-slate-200 select-none">
                  <tr>
                    <th className="py-1.5 px-2.5">LEVEL</th>
                    <th className="py-1.5 px-2.5">PRES (dbar)</th>
                    <th className="py-1.5 px-2.5">TEMP (°C)</th>
                    <th className="py-1.5 px-2.5">PSAL (psu)</th>
                    <th className="py-1.5 px-2.5">CNDC (S/m)</th>
                    <th className="py-1.5 px-2.5 text-center">PRES QC</th>
                    <th className="py-1.5 px-2.5 text-center">TEMP QC</th>
                    <th className="py-1.5 px-2.5 text-center">PSAL QC</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {cycleRecord.ctd_samples.map((s) => (
                    <tr key={s.level} className="hover:bg-slate-50/80">
                      <td className="py-1.5 px-2.5 text-slate-400 font-bold">{s.level}</td>
                      <td className="py-1.5 px-2.5 text-sky-800 font-bold">{s.PRES.toFixed(2)}</td>
                      <td className="py-1.5 px-2.5 text-amber-900 font-medium">{s.TEMP.toFixed(3)}</td>
                      <td className="py-1.5 px-2.5 text-emerald-800 font-medium">{s.PSAL.toFixed(3)}</td>
                      <td className="py-1.5 px-2.5 text-indigo-800">{s.CNDC !== undefined ? s.CNDC.toFixed(3) : "—"}</td>
                      <td className="py-1.5 px-2.5 text-center">{formatQcBadge(s.PRES_QC)}</td>
                      <td className="py-1.5 px-2.5 text-center">{formatQcBadge(s.TEMP_QC)}</td>
                      <td className="py-1.5 px-2.5 text-center">{formatQcBadge(s.PSAL_QC)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="h-9 px-4 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-[11px] text-slate-600">
          <span>QC FLAG LEGEND: 1=GOOD, 2=PROBABLY GOOD, 3=DOUBTFUL, 4=BAD, 9=MISSING</span>
          <button
            onClick={() => setCycleModalOpen(false)}
            className="px-3 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-[10px] font-bold uppercase transition shadow-2xs"
          >
            Close Inspector
          </button>
        </div>
      </div>
    </div>
  );
};
