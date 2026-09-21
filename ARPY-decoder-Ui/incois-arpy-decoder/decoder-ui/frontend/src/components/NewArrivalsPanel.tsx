import React from "react";
import { Radio, FileSearch, Eye, CheckCheck } from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";

/**
 * NEW DATA — incoming-data arrivals panel.
 *
 * Renders normalized arrival records produced by the backend ingestion
 * layer (LocalDataSource now; INCOIS FTP later via the same contract).
 * Display rules:
 *  - "🟡 NEW DATA" badge per float with state=new, with the facts the
 *    source actually provided (WMO, platform, received time, cycle number
 *    only when genuinely present) — nothing is invented.
 *  - Opaque source objects (parser_pending, no resolved WMO) are grouped
 *    in a muted section labelled "awaiting real INCOIS format/parser".
 *  - Every action is visibility-only: "View float" selects the float in
 *    the Decoder workspace (where the user may choose Decode), "Mark seen"
 *    acknowledges the arrival. Detection NEVER starts decoding.
 */
export const NewArrivalsPanel: React.FC = () => {
  const {
    ingestionArrivals,
    presets,
    selectPreset,
    setActiveView,
    ackIngestionArrival,
  } = useDecoderStore();

  const freshAll = ingestionArrivals.filter((a) => a.state === "new" && !a.parser_pending && a.wmo !== null);
  const opaque = ingestionArrivals.filter((a) => a.state === "new" && (a.parser_pending || a.wmo === null));
  // One card per float: the LATEST arrival owns the badge; older ones for
  // the same float collapse into a counter (no duplicate float cards).
  const freshByWmo = new Map<number, (typeof freshAll)[number]>();
  const extrasByWmo = new Map<number, number>();
  for (const a of freshAll) {
    const prev = freshByWmo.get(a.wmo as number);
    if (!prev || a.ingested_at >= prev.ingested_at) {
      if (prev) extrasByWmo.set(a.wmo as number, (extrasByWmo.get(a.wmo as number) ?? 0) + 1);
      freshByWmo.set(a.wmo as number, a);
    } else {
      extrasByWmo.set(a.wmo as number, (extrasByWmo.get(a.wmo as number) ?? 0) + 1);
    }
  }
  const fresh = [...freshByWmo.values()];

  if (fresh.length === 0 && opaque.length === 0) return null;

  const when = (a: (typeof ingestionArrivals)[number]) => {
    const t = a.arrived_at || a.ingested_at;
    if (!t) return "—";
    const d = new Date(t);
    return Number.isNaN(d.getTime()) ? t : d.toLocaleString();
  };

  return (
    <div
      data-testid="new-arrivals-panel"
      className="border-y border-amber-300 bg-amber-50/90 px-3 py-2.5 shrink-0 font-mono select-none"
    >
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center space-x-1.5 text-[11px] font-bold uppercase tracking-wider text-amber-800">
          <Radio className="w-3.5 h-3.5 text-amber-600 animate-pulse" />
          <span>Incoming data arrivals</span>
          <span className="px-1.5 py-0.2 bg-amber-200/80 border border-amber-300 rounded text-amber-900">
            {fresh.length + opaque.length}
          </span>
        </div>
        <span className="text-[10px] text-amber-700/80" title="Discovery is observational only — no decoding is started automatically">
          auto-discovery · decode stays manual
        </span>
      </div>

      <div className="space-y-1.5 max-h-40 overflow-y-auto pr-0.5">
        {fresh.map((a) => {
          const preset = a.wmo !== null ? presets.find((p) => p.wmo === a.wmo) : undefined;
          return (
            <div
              key={a.fingerprint}
              data-arrival-wmo={a.wmo}
              className="flex items-center justify-between gap-2 bg-white border border-amber-200 rounded px-2.5 py-1.5 shadow-2xs"
            >
              <div className="flex items-center space-x-2 min-w-0">
                <span className="w-2 h-2 rounded-full bg-amber-400 ring-2 ring-amber-200 shrink-0" />
                <div className="min-w-0">
                  <div className="flex items-center space-x-2">
                    <span className="text-[12.5px] font-bold text-[#276095]">WMO {a.wmo}</span>
                    <span
                      data-testid="new-data-badge"
                      className="px-1.5 py-0.2 rounded bg-amber-100 border border-amber-300 text-amber-800 text-[10px] font-bold tracking-wide"
                      title={`Newly arrived source data ingested at ${a.ingested_at} (${a.source_id})`}
                    >
                      NEW DATA
                    </span>
                    {a.is_new_wmo && (
                      <span className="px-1.5 py-0.2 rounded bg-emerald-100 border border-emerald-300 text-emerald-800 text-[10px] font-bold">
                        NEW FLOAT
                      </span>
                    )}
                    {(extrasByWmo.get(a.wmo as number) ?? 0) > 0 && (
                      <span className="text-[9.5px] text-amber-700/80" title="Earlier arrivals for the same float (same NEW DATA state)">
                        +{extrasByWmo.get(a.wmo as number)} earlier
                      </span>
                    )}
                  </div>
                  <div className="text-[10.5px] text-slate-500 truncate">
                    {a.platform ? `platform ${a.platform} · ` : ""}
                    received {when(a)}
                    {a.cycle_number !== null && a.cycle_number !== undefined ? ` · cycle ${a.cycle_number}` : ""}
                    {` · ${a.files} file(s)`}
                  </div>
                </div>
              </div>
              <div className="flex items-center space-x-1.5 shrink-0">
                <button
                  onClick={() => {
                    if (preset) {
                      selectPreset(preset);
                      setActiveView("decoder");
                    }
                  }}
                  disabled={!preset}
                  className="flex items-center space-x-1 px-2 py-1 rounded text-[10.5px] font-bold border shadow-2xs bg-[#276095] hover:bg-[#1f4e7a] text-white border-[#276095] disabled:bg-slate-100 disabled:text-slate-400 disabled:border-slate-200 cursor-pointer disabled:cursor-not-allowed"
                  title={preset ? "Select this float in the Decoder workspace (decode stays a manual choice)" : "Float not present in the discovered preset registry"}
                >
                  <Eye className="w-3 h-3" />
                  <span>View float</span>
                </button>
                <button
                  onClick={() => ackIngestionArrival(String(a.wmo ?? a.identifier))}
                  className="flex items-center space-x-1 px-2 py-1 rounded text-[10.5px] font-bold border shadow-2xs bg-white hover:bg-slate-50 text-slate-600 border-slate-300 cursor-pointer"
                  title="Acknowledge this arrival (clears the NEW DATA badge; never deletes history)"
                >
                  <CheckCheck className="w-3 h-3" />
                  <span>Mark seen</span>
                </button>
              </div>
            </div>
          );
        })}

        {opaque.length > 0 && (
          <div className="bg-slate-50 border border-slate-200 rounded px-2.5 py-1.5" data-testid="opaque-arrivals">
            <div className="flex items-center space-x-1.5 text-[10.5px] text-slate-500">
              <FileSearch className="w-3 h-3" />
              <span>
                {opaque.length} unparsed source association(s) with unidentified float ({opaque.map((o) => o.identifier).join(", ")})
              </span>
            </div>
            <p className="text-[9.5px] text-slate-400 mt-0.5">
              Awaiting the real INCOIS source specification/parser — no WMO is claimed for unidentified data.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default NewArrivalsPanel;


