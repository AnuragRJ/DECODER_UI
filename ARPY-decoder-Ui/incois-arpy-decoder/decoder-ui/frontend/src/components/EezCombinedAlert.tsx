import React, { useMemo } from "react";
import { AlertTriangle, X } from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";
import { useFadePresence } from "../utils/useFadePresence";

/**
 * EezCombinedAlert — exactly ONE aggregated RED operational-warning panel
 * answering ONLY: "which floats are currently inside the Indian EEZ?"
 *
 * Pipeline (all derived from cached real-data classification, never
 * appended-to):
 *
 *   real float data
 *     → latest valid classified position per WMO (store `eezByWmo`)
 *     → filter CURRENT `INDIAN_EEZ` state
 *     → unique sorted WMO list
 *     → drop dismissed (`inside|<wmo>` snapshot keys)
 *     → render ONE panel
 *
 * CURRENT STATE ONLY: no cycle numbers, no C100 → C101 pairs, no JULD, no
 * trajectory details, no historical Entry/Exit events. A float appears here
 * if and only if its latest valid real position classifies inside the
 * verified EEZ polygon right now. Historical transitions remain available in
 * MAP LAYERS → EEZ events (session history) but never populate this alert.
 *
 * Visibility (alert ONLY in Expanded / Full Screen Fleet Map, layer ON):
 *
 *   - normal compact Fleet view (`expanded === false`) → renders NOTHING
 *     (no toast, no popup, no floating count);
 *   - Indian EEZ toggle OFF → renders NOTHING (the layer owns this alert);
 *   - expanded / Full Screen + layer ON + ≥1 currently-inside float → the
 *     single panel, anchored bottom-left of the map (300 ms opacity fade
 *     in/out on toggle — same treatment as the EEZ boundary + region);
 *   - zero floats inside → NO alert;
 *   - collapsing hides the panel WITHOUT deleting classification; expanding
 *     shows the same single panel (no duplicates — derivation is pure).
 *
 * Dismiss snapshots the currently-inside WMOs; history/classification stay
 * intact and only a NEWLY inside WMO can re-surface the panel.
 *
 * Styling is the restrained red operational family (red accent, subtle red
 * border, dark translucent background, readable light text) — a geographic
 * monitoring event, NEVER a decoder failure / crash / critical error look.
 * Wording stays strictly neutral-scientific (no legal/enforcement terms).
 */
const MAX_ROWS = 6;

export interface EezCombinedAlertProps {
  expanded: boolean;
  /** Deterministic overrides for SSR/unit tests only — the live app always
   *  omits these and subscribes to the store (React 19 `useSyncExternalStore`
   *  SSR snapshots the store's initial state, so server-rendered tests must
   *  inject the derived state as props instead). */
  insideWmos?: number[];
  dismissed?: Record<string, true>;
  layerOn?: boolean;
}

export const EezCombinedAlert: React.FC<EezCombinedAlertProps> = ({
  expanded,
  insideWmos: insideWmosProp,
  dismissed: dismissedProp,
  layerOn: layerOnProp,
}) => {
  const eezByWmo = useDecoderStore((s) => s.eezByWmo);
  const storeDismissed = useDecoderStore((s) => s.eezDismissed);
  const storeLayerOn = useDecoderStore((s) => s.eezLayerOn);
  const dismissAllEezNotices = useDecoderStore((s) => s.dismissAllEezNotices);

  // Latest valid classified position per WMO → currently-inside set. One
  // memo over cached classification: rerenders, map repaints, toggle flips,
  // zoom/pan/resize, selection changes and Full Screen transitions all
  // re-derive this same list — they can never append another alert, and no
  // point-in-polygon work happens here (classification is cached upstream).
  const storeInsideWmos = useMemo(() => {
    const out: number[] = [];
    for (const [key, classified] of Object.entries(eezByWmo)) {
      if (!classified || classified.length === 0) continue;
      if (classified[classified.length - 1].eezStatus !== "INDIAN_EEZ") continue;
      const wmo = Number(key);
      if (!Number.isFinite(wmo)) continue;
      if (!out.includes(wmo)) out.push(wmo);
    }
    out.sort((a, b) => a - b);
    return out;
  }, [eezByWmo]);

  const insideWmos = insideWmosProp ?? storeInsideWmos;
  const dismissed = dismissedProp ?? storeDismissed;
  const visible = useMemo(() => {
    const seen = new Set<number>();
    const out: number[] = [];
    for (const w of insideWmos) {
      if (seen.has(w)) continue;
      seen.add(w);
      if (!dismissed[`inside|${w}`]) out.push(w);
    }
    return out;
  }, [insideWmos, dismissed]);

  // Toggle/expansion gate with a smooth 300 ms fade: collapsing, exiting Full
  // Screen, or switching the layer OFF fades the panel out before it unmounts;
  // expanding / toggling back ON fades the same single panel back in. Dismiss
  // and zero-inside still hide instantly (unchanged behavior).
  const layerOn = layerOnProp ?? storeLayerOn;
  const { present, shown } = useFadePresence(expanded && layerOn, 300);
  if (!present) return null;
  // Zero floats currently inside → NO alert.
  if (visible.length === 0) return null;

  const rows = visible.slice(0, MAX_ROWS);
  const overflow = visible.length - rows.length;
  const summary =
    visible.length === 1
      ? "1 float currently inside EEZ"
      : `${visible.length} floats currently inside EEZ`;

  return (
    <div
      className="absolute bottom-3 left-3 z-50 w-[320px] pointer-events-none eez-fade-in"
      style={{ opacity: shown ? 1 : 0, transition: "opacity 300ms ease-in-out" }}
      data-testid="eez-combined-alert-wrap"
      role="region"
      aria-label="Indian EEZ notifications"
    >
      <div
        className="pointer-events-auto rounded-md border border-red-400/40 bg-[#230d12]/95 shadow-xl backdrop-blur-sm px-3 py-2.5"
        data-testid="eez-combined-alert"
        role="alert"
      >
        <div className="flex items-start gap-2.5">
          <div className="mt-0.5 w-7 h-7 rounded bg-red-400/15 border border-red-400/45 flex items-center justify-center shrink-0">
            <AlertTriangle className="w-3.5 h-3.5 text-red-300" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-mono text-[11.5px] font-bold tracking-wide text-red-200">
              Indian EEZ Alert
            </div>
            <p
              className="font-mono text-[10.5px] leading-snug text-rose-50/85 mt-0.5"
              data-testid="eez-alert-counts"
            >
              {summary}
            </p>
          </div>
          <button
            type="button"
            onClick={() => dismissAllEezNotices()}
            className="shrink-0 w-5 h-5 flex items-center justify-center rounded text-red-300/70 hover:text-white hover:bg-white/10 cursor-pointer"
            data-testid="eez-alert-dismiss"
            aria-label="Dismiss EEZ alert (classification stays intact)"
            title="Dismiss (classification and history stay intact)"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
        <ul className="mt-1.5 space-y-1">
          {rows.map((wmo) => (
            <li
              key={wmo}
              className="flex items-center gap-1.5 font-mono text-[10.5px] text-red-200/85"
              data-testid="eez-alert-row"
              data-wmo={wmo}
              title={`WMO ${wmo} is currently inside the Indian EEZ (latest valid position)`}
            >
              <span aria-hidden>•</span>
              <span className="px-1 rounded-sm border border-red-300/30">WMO {wmo}</span>
            </li>
          ))}
        </ul>
        {overflow > 0 && (
          <p
            className="mt-1 font-mono text-[9.5px] text-red-200/60"
            data-testid="eez-alert-overflow"
          >
            +{overflow} more
          </p>
        )}
        <div className="mt-1.5 flex items-center gap-1.5 font-mono text-[9px] text-sky-200/50">
          <span className="px-1 rounded-sm border border-white/15">200NM EEZ REF</span>
          <span>external reference · not official INCOIS</span>
        </div>
      </div>
    </div>
  );
};

export default EezCombinedAlert;
