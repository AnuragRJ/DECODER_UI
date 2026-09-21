import React, { useMemo, useRef, useState, useEffect, useCallback } from "react";
import { Layers, MapPin } from "lucide-react";
import EezCombinedAlert from "./EezCombinedAlert";
import type { FleetMapViewHandle, FleetViewData } from "./esriFleetView";
import {
  buildEezRegionDescriptor,
  buildMarkerDescriptors,
  buildPredictionDescriptors,
  buildTrajectoryDescriptor,
  buildTransitionDescriptors,
  frameExtentFor,
  sortTrajectoryChronologically,
  type EezRegionDescriptor,
  type FleetMapFloat,
  type FleetMapPrediction,
  type FleetMapTrajectoryPoint,
  type LonLatExtent,
  type MarkerDescriptor,
  type TrajectoryDescriptor,
  type TransitionDescriptor,
} from "./fleetMapModel";
import {
  type ClassifiedCycle,
  type EezStatus,
  type EezTransition,
  type IndiaEez,
} from "../utils/indiaEez";

export type { FleetMapFloat, FleetMapPrediction, FleetMapTrajectoryPoint };

/** Stable empty default so the memo never re-runs from a fresh array. */
const EMPTY_PREDICTIONS: FleetMapPrediction[] = [];

/**
 * FleetOceanMap
 * -------------
 * Oceanographic fleet overview on crisp Esri satellite Earth imagery
 * (World Imagery + Boundaries & Places reference, keyless raster
 * services) rendered through the ArcGIS Maps SDK MapView.
 *
 * Architecture notes:
 *  - Props, header, legend, layer controls, zoom/FIT controls and every
 *    behaviour (initial fleet fit, selection auto-frame, refine-on-
 *    hydrate, user-takeover, re-click-to-reinspect) are preserved from
 *    the previous renderer; only the map engine changed (SVG world →
 *    MapView canvas).
 *  - All data decisions live in fleetMapModel.ts as pure builders; the
 *    SDK module (esriFleetView.ts, lazy-loaded) only paints graphics.
 *  - Markers, waypoints and trajectory lines are built ONLY from real
 *    decoded cycle positions. Nothing is hardcoded or fabricated.
 *    Clicking a float marker selects it everywhere else in Results.
 */

/** Indian EEZ overlay contract for the map (presentational, prop-driven).
 *  Everything here is VISUALIZATION-ONLY: deriving these values never
 *  touches decode/run state, and toggling never recomputes anything. */
export interface EezMapOverlays {
  /** MAP LAYERS toggle (OFF by default). */
  layerOn: boolean;
  onToggle: (on: boolean) => void;
  /** Geometry lifecycle — the layer only exists when "ready"; on
   *  "unavailable" the control says so honestly (no approximation). */
  status: "idle" | "loading" | "ready" | "unavailable";
  /** Parsed, validated reference geometry (ready-only). */
  geom: IndiaEez | null;
  /** Per-cycle EEZ states of the SELECTED float (chronological). */
  classified: ClassifiedCycle[] | null;
  /** EEZ transitions derived for the SELECTED float. */
  transitions: EezTransition[];
  /** All session-derived EEZ transitions (history; shown on demand). */
  history: EezTransition[];
  /** Ids the operator already dismissed (history view shades them). */
  dismissed: Record<string, true>;
  /** CURRENT (latest valid-cycle) EEZ state per float — derived from real
   *  decoded positions only. Purely geographic state: it is NOT an
   *  entry/exit event and never implies one. */
  currentStatus: Record<number, EezStatus | undefined>;
}

interface Props {
  positions: FleetMapFloat[];
  trajectory: FleetMapTrajectoryPoint[];
  selectedWmo: number | null;
  onSelect: (wmo: number) => void;
  /** Optional experimental prediction layer (empty => control hidden and the
   *  layer never draws). Predictions are server-derived; the map only paints. */
  predictions?: FleetMapPrediction[];
  /** True in Fleet full-screen mode: the map fills the whole area and
   *  zoom buttons are shown. */
  fill?: boolean;
  /** Identity of the fleet dataset (batch id). A change marks the next
   *  positions arrival as a NEW fleet -> one initial fit is performed. */
  dataKey?: string | null;
  /** Optional Indian EEZ overlay state (absent => pristine original map). */
  eez?: EezMapOverlays;
  /** Header/footer wording overrides. Defaults preserve the original
   *  decode-run captions exactly; the Float Status page passes upstream
   *  captions since its positions come from Ifremer GDAC, not decodes. */
  title?: string;
  subtitleNoun?: string;
  footerNote?: string;
}

export const FleetOceanMap: React.FC<Props> = ({
  positions,
  trajectory,
  selectedWmo,
  onSelect,
  predictions = EMPTY_PREDICTIONS,
  fill = false,
  dataKey = null,
  eez = null,
  title = "Fleet positions — real decoded cycle locations",
  subtitleNoun = "with valid decoded positions",
  footerNote = "positions & tracks from decode run history",
}) => {
  const viewDivRef = useRef<HTMLDivElement | null>(null);
  const apiRef = useRef<FleetMapViewHandle | null>(null);
  const [ready, setReady] = useState(false);
  const [eezHistoryOpen, setEezHistoryOpen] = useState(false);
  // Prediction layer is OPTIONAL and OFF by default: enabling it never
  // changes markers, trajectories, EEZ or framing.
  const [predictionOn, setPredictionOn] = useState(false);

  // Latest props for the stable view callbacks (the MapView outlives
  // renders; callbacks must never close over stale values).
  const cbRef = useRef({ onSelect, selectedWmo, positions, trajectory });
  cbRef.current = { onSelect, selectedWmo, positions, trajectory };

  // ------------------------------------------------------------------
  // Pure descriptors (fleetMapModel) → pushed to the view on change
  // ------------------------------------------------------------------
  const orderedTrajectory = useMemo(
    () => sortTrajectoryChronologically(trajectory),
    [trajectory]
  );
  const markers: MarkerDescriptor[] = useMemo(
    () => buildMarkerDescriptors(positions, selectedWmo, eez?.currentStatus, eez?.layerOn === true),
    [positions, selectedWmo, eez]
  );
  const traj: TrajectoryDescriptor | null = useMemo(
    () => buildTrajectoryDescriptor(orderedTrajectory, selectedWmo, eez?.classified ?? null),
    [orderedTrajectory, selectedWmo, eez]
  );
  const eezRegion: EezRegionDescriptor | null = useMemo(() => {
    if (!eez || eez.status !== "ready" || !eez.geom) return null;
    return buildEezRegionDescriptor(eez.geom);
  }, [eez]);
  const eezVisible = eez?.layerOn === true && eezRegion !== null;
  const transitions: TransitionDescriptor[] = useMemo(() => {
    if (!eez || eez.transitions.length === 0) return [];
    const byCycle = new Map(orderedTrajectory.map((p) => [p.cycle, p]));
    return buildTransitionDescriptors(eez.transitions, byCycle);
  }, [eez, orderedTrajectory]);
  const hasTrajectory = traj !== null;

  // ------------------------------------------------------------------
  // View lifecycle (StrictMode-safe: create → cancel/destroy on cleanup)
  // ------------------------------------------------------------------
  const userInteractedRef = useRef(false);
  const lastAutoSelRef = useRef<number | null>(null); // last wmo auto-framed
  const framedPtsCountRef = useRef(0); // trajectory pts covered by that frame

  const frameFleet = useCallback((durationMs = 380) => {
    const api = apiRef.current;
    if (!api) return;
    const pts = cbRef.current.positions.map((p) => ({ lon: p.lon, lat: p.lat }));
    const ext = frameExtentFor(pts, 0.1, 6);
    if (ext) api.frameExtent(ext, durationMs);
    else api.frameWorld(durationMs);
  }, []);

  const framePoints = useCallback(
    (pts: Array<{ lon: number; lat: number }>, durationMs = 480) => {
      const api = apiRef.current;
      if (!api || pts.length === 0) return;
      let ext: LonLatExtent | null = frameExtentFor(pts, 0.22, 2.2);
      // Density-aware zoom: piled-up cycles become individually
      // inspectable — shrink the frame until the mean consecutive
      // spacing covers ~11 px (the previous renderer's kNeed rule).
      if (ext && pts.length >= 2) {
        let meanSpacing = 0;
        for (let i = 1; i < pts.length; i++) {
          meanSpacing += Math.hypot(pts[i].lon - pts[i - 1].lon, pts[i].lat - pts[i - 1].lat);
        }
        meanSpacing /= pts.length - 1;
        const size = api.view.size as [number, number] | undefined;
        const minPx = size ? Math.min(size[0], size[1]) : 600;
        const span = Math.max(ext.xmax - ext.xmin, ext.ymax - ext.ymin);
        if (meanSpacing > 1e-9 && (meanSpacing / span) * minPx < 11) {
          const target = Math.max((meanSpacing * minPx) / 11, 0.05);
          const cx = (ext.xmin + ext.xmax) / 2;
          const cy = (ext.ymin + ext.ymax) / 2;
          ext = {
            xmin: Math.max(-180, cx - target / 2),
            xmax: Math.min(540, cx + target / 2),
            ymin: Math.max(-90, cy - target / 2),
            ymax: Math.min(90, cy + target / 2),
          };
        }
      }
      if (ext) api.frameExtent(ext, durationMs);
    },
    []
  );

  const reframeSelection = useCallback(() => {
    const { positions: pos, trajectory: trj, selectedWmo: sel } = cbRef.current;
    if (sel == null) return;
    const pts =
      trj.length >= 1
        ? sortTrajectoryChronologically(trj).map((p) => ({ lon: p.lon, lat: p.lat }))
        : [];
    if (pts.length > 0) {
      framePoints(pts, 480);
      return;
    }
    const fp = pos.find((p) => p.wmo === sel);
    if (fp) framePoints([{ lon: fp.lon, lat: fp.lat }], 420);
  }, [framePoints]);

  const reframeSelectionRef = useRef(reframeSelection);
  reframeSelectionRef.current = reframeSelection;

  useEffect(() => {
    let disposed = false;
    let api: FleetMapViewHandle | null = null;
    const el = viewDivRef.current;
    if (el) {
      import("./esriFleetView").then((m) => {
        if (disposed) return;
        m.createFleetMapView(el, {
          onMarkerClick: (wmo: number) => {
            const { onSelect: sel, selectedWmo: cur } = cbRef.current;
            if (wmo !== cur) {
              sel(wmo);
              return;
            }
            // Re-clicking the ALREADY selected float = explicit
            // re-inspect gesture: frame its real trajectory again.
            userInteractedRef.current = false;
            lastAutoSelRef.current = wmo;
            framedPtsCountRef.current = cbRef.current.trajectory.length;
            reframeSelectionRef.current();
          },
          onUserInteract: () => {
            userInteractedRef.current = true;
          },
        }).then((created) => {
          if (disposed) {
            created.destroy();
            return;
          }
          api = created;
          apiRef.current = created;
          created.update(dataRef.current);
          created.whenReady.then(() => {
            if (!disposed) setReady(true);
          });
        });
      });
    }
    return () => {
      disposed = true;
      if (api) {
        api.destroy();
        apiRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push data to the view (also runs once the view is created).
  const predictionDescriptors = useMemo(
    () => buildPredictionDescriptors(predictions, selectedWmo),
    [predictions, selectedWmo]
  );

  const data: FleetViewData = useMemo(
    () => ({
      markers,
      trajectory: traj,
      predictions: {
        visible: predictionOn && predictionDescriptors.length > 0,
        points: predictionDescriptors,
      },
      eez: { visible: eezVisible, region: eezRegion, transitions },
    }),
    [markers, traj, predictionOn, predictionDescriptors, eezVisible, eezRegion, transitions]
  );
  const dataRef = useRef(data);
  dataRef.current = data;
  useEffect(() => {
    apiRef.current?.update(data);
  }, [data]);

  // ------------------------------------------------------------------
  // One-shot behaviours: initial fleet fit (once per dataKey) and
  // selection-driven focus (once per selection change)
  // ------------------------------------------------------------------
  const didInitialFitRef = useRef(false);
  const lastDataKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (lastDataKeyRef.current !== dataKey) {
      lastDataKeyRef.current = dataKey;
      didInitialFitRef.current = false;
    }
  }, [dataKey]);

  useEffect(() => {
    if (!ready) return;
    if (didInitialFitRef.current) return;
    if (positions.length === 0) return;
    didInitialFitRef.current = true;
    frameFleet(420);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [positions.length, ready]);

  useEffect(() => {
    if (!ready) return;
    if (selectedWmo == null) return; // ignore null flicker; keep last frame identity
    const isNewSelection = lastAutoSelRef.current !== selectedWmo;
    if (isNewSelection) userInteractedRef.current = false;
    const fp = positions.find((p) => p.wmo === selectedWmo);
    if (!fp) return;
    const pts: Array<{ lon: number; lat: number }> =
      orderedTrajectory.length >= 1
        ? orderedTrajectory.map((p) => ({ lon: p.lon, lat: p.lat }))
        : [];
    if (isNewSelection) {
      lastAutoSelRef.current = selectedWmo;
      if (pts.length > 0) {
        framedPtsCountRef.current = pts.length;
        framePoints(pts, 480);
      } else {
        // Only the marker position is known yet; centre on it — the refine
        // pass below reframes once the real trajectory arrives.
        framedPtsCountRef.current = 0;
        framePoints([{ lon: fp.lon, lat: fp.lat }], 420);
      }
      return;
    }
    // Same selection: refine ONLY when the trajectory grew and the user has
    // not taken over the map (one upgrade, never a downgrade).
    if (
      !userInteractedRef.current &&
      pts.length >= 2 &&
      pts.length > framedPtsCountRef.current
    ) {
      framedPtsCountRef.current = pts.length;
      framePoints(pts, 480);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedWmo, orderedTrajectory.length, positions, ready]);

  // FIT — the ONLY explicit reframe; frames the whole FLEET
  // (never just the selected trajectory).
  const fitAll = useCallback(() => {
    frameFleet(380);
  }, [frameFleet]);

  const zoomButton = useCallback((factor: number) => {
    userInteractedRef.current = true;
    apiRef.current?.zoomBy(factor);
  }, []);

  // ------------------------------------------------------------------
  // Render — shell (header/controls/legend/alerts) unchanged; the map
  // surface itself is the ArcGIS MapView canvas.
  // ------------------------------------------------------------------
  const loading = !ready;

  return (
    <div className="flex flex-col bg-[#0d2a47] overflow-hidden h-full w-full">
      {/* Map header — unchanged */}
      <div className="px-3.5 py-2 flex items-center justify-between border-b border-white/10 shrink-0">
        <div className="flex items-center space-x-1.5 font-mono text-[13px] font-bold text-sky-100 uppercase tracking-wider">
          <MapPin className="w-3.5 h-3.5 text-sky-300" />
          <span>{title}</span>
        </div>
        <div className="flex items-center gap-2.5 min-w-0">
          {predictionDescriptors.length > 0 && (
            <label
              className="flex items-center gap-1.5 font-mono text-[11px] text-sky-200/90 cursor-pointer whitespace-nowrap"
              title="Experimental prediction layer: predicted next-profile position (hollow diamond) and validated 50 % / 90 % uncertainty areas. Off by default; never hides the float's real position."
            >
              <input
                type="checkbox"
                className="w-3.5 h-3.5 accent-[#7dd3fc] cursor-pointer"
                data-testid="prediction-layer-toggle"
                checked={predictionOn}
                onChange={(e) => setPredictionOn(e.target.checked)}
              />
              <span>Predicted next profile ({predictionDescriptors.length})</span>
            </label>
          )}
          <span className="font-mono text-[12px] text-sky-300/80 whitespace-nowrap">
            {positions.length} float{positions.length === 1 ? "" : "s"} {subtitleNoun}
            {hasTrajectory ? ` · trajectory WMO ${selectedWmo ?? ""}` : ""}
          </span>
        </div>
      </div>

      <div className="relative flex-1 min-h-0">
        <div
          ref={viewDivRef}
          data-testid="esri-map-view"
          className="absolute inset-0"
          role="img"
          aria-label="Fleet map over Esri satellite Earth imagery"
        />

        {!positions.length && ready && (
          <div className="absolute inset-x-0 bottom-4 flex justify-center pointer-events-none">
            <span className="font-mono text-[11.5px] text-[#94c5e5]/55">
              awaiting decoded float positions…
            </span>
          </div>
        )}

        {/* Fit helper chip — normal (framed) mode */}
        {!fill && positions.length > 0 && (
          <button
            type="button"
            onClick={fitAll}
            data-fit-chip
            className="absolute top-2 right-2 z-10 w-[58px] h-5 rounded bg-[#0d2a47]/85 border border-[#94c5e5]/50 font-mono text-[10.5px] font-bold text-[#bae0ff] hover:bg-[#16436e] cursor-pointer"
          >
            FIT
          </button>
        )}

        {/* MAP LAYERS — compact GIS-style floating control (visualization
            toggles only; switching never recomputes data or destroys state).
            Identical component in normal + Full Screen: single source. */}
        {eez && (
          <div
            className="absolute top-3 left-3 z-10 select-none"
            data-testid="eez-layer-control"
          >
            <div className="rounded-md bg-[#0d2a47]/90 border border-sky-300/30 shadow-lg backdrop-blur-sm w-[188px]">
              <div className="flex items-center gap-1.5 px-2.5 py-1.5 border-b border-white/10">
                <Layers className="w-3 h-3 text-sky-300/80" />
                <span className="font-mono text-[10px] font-bold tracking-widest text-sky-200/90 uppercase">
                  Map Layers
                </span>
              </div>
              <div className="px-2.5 py-2 space-y-1.5">
                <label className="flex items-center gap-2 cursor-pointer group">
                  <input
                    type="checkbox"
                    className="w-3.5 h-3.5 accent-[#c06973] cursor-pointer disabled:opacity-40"
                    data-testid="eez-toggle"
                    checked={eez.layerOn}
                    disabled={eez.status !== "ready"}
                    onChange={(e) => eez.onToggle(e.target.checked)}
                  />
                  <span className="font-mono text-[11.5px] text-slate-100/90 group-hover:text-white">
                    Indian EEZ
                  </span>
                  {eez.status !== "ready" && (
                    <span
                      className="ml-auto font-mono text-[9.5px] text-sky-300/60"
                      data-testid="eez-status"
                    >
                      {eez.status === "loading"
                        ? "loading…"
                        : eez.status === "unavailable"
                          ? "unavailable"
                          : ""}
                    </span>
                  )}
                  {eez.status === "ready" && eez.layerOn && (
                    <span
                      className="ml-auto w-4 h-0 border-t border-dashed"
                      style={{ borderColor: "rgba(103,232,249,0.9)" }}
                      aria-hidden
                    />
                  )}
                </label>
                {eez.status === "unavailable" && (
                  <p className="font-mono text-[9.5px] leading-snug text-amber-200/70 pl-5">
                    Reference geometry unavailable — layer disabled.
                  </p>
                )}
                {eez.history.length > 0 && (
                  <button
                    type="button"
                    className="w-full text-left font-mono text-[10px] text-teal-200/85 hover:text-teal-100 cursor-pointer pl-5 pt-0.5"
                    data-testid="eez-history-toggle"
                    onClick={() => setEezHistoryOpen((v) => !v)}
                  >
                    {eezHistoryOpen ? "▾" : "▸"} EEZ events ({eez.history.length})
                  </button>
                )}
                {eezHistoryOpen && eez.history.length > 0 && (
                  <div
                    className="max-h-36 overflow-y-auto space-y-1 pl-1.5 border-l border-white/10 ml-2"
                    data-testid="eez-history"
                  >
                    {eez.history.map((t) => (
                      <div
                        key={t.id}
                        className={`font-mono text-[9.5px] leading-snug ${
                          eez.dismissed[t.id] ? "text-sky-200/40" : "text-sky-100/80"
                        }`}
                        data-eez-history-id={t.id}
                      >
                        <span
                          className={`inline-block px-1 mr-1 rounded-sm border text-[8.5px] border-red-300/40 text-red-200/90`}
                        >
                          {t.eventType === "EEZ_ENTRY" ? "ENTRY" : "EXIT"}
                        </span>
                        WMO {t.wmo} · C{t.fromCycle}→C{t.toCycle}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Honest loading state: only while the Esri view itself is
            initializing — shown INSIDE the map, never an empty skeleton. */}
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="flex items-center space-x-2 px-3.5 py-2 rounded-md bg-[#0d2a47]/85 border border-sky-300/30 shadow-xl">
              <span className="w-3.5 h-3.5 border-2 border-sky-300/70 border-t-transparent rounded-full animate-spin" />
              <span className="font-mono text-[12px] text-sky-100 tracking-wide">Loading map…</span>
            </div>
          </div>
        )}

        {/* Real-map controls (full-screen): + / − / FIT */}
        {fill && (
          <div className="absolute top-3 right-3 z-10 flex flex-col gap-1.5">
            <button
              type="button"
              data-testid="map-zoom-in"
              title="Zoom In"
              onClick={() => zoomButton(1.5)}
              className="w-9 h-9 flex items-center justify-center rounded-md bg-[#0d2a47]/90 border border-sky-300/40 text-sky-100 font-bold text-lg hover:bg-[#16436e] hover:border-sky-300/70 cursor-pointer select-none shadow-lg"
            >
              +
            </button>
            <button
              type="button"
              data-testid="map-zoom-out"
              title="Zoom Out"
              onClick={() => zoomButton(1 / 1.5)}
              className="w-9 h-9 flex items-center justify-center rounded-md bg-[#0d2a47]/90 border border-sky-300/40 text-sky-100 font-bold text-lg hover:bg-[#16436e] hover:border-sky-300/70 cursor-pointer select-none shadow-lg"
            >
              −
            </button>
            <button
              type="button"
              data-testid="map-fit"
              title="Reset / Fit"
              onClick={fitAll}
              className="w-9 h-9 flex items-center justify-center rounded-md bg-[#0d2a47]/90 border border-sky-300/40 text-sky-100 font-bold text-[11px] font-mono tracking-wider hover:bg-[#16436e] hover:border-sky-300/70 cursor-pointer select-none shadow-lg"
            >
              FIT
            </button>
          </div>
        )}

        {/* Combined EEZ alert — rendered INSIDE the map area so `absolute`
            anchors it to the map's bottom-left corner (above the legend),
            in expanded view with the layer ON. */}
        <EezCombinedAlert expanded={fill} />
      </div>

      {/* Legend — yellow float marker + trajectory */}
      <div className="px-3.5 py-2 border-t border-white/10 flex items-center justify-between gap-2 flex-wrap shrink-0">
        <div className="flex items-center gap-3 font-mono text-[11.5px] text-sky-200/90">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full border border-[#0d2a47] bg-[#fbbf24]" />
            float position
          </span>
          {hasTrajectory && (
            <span className="flex items-center gap-1">
              <span className="w-3 h-0.5 border-t border-dashed border-sky-300" />
              trajectory
            </span>
          )}
          {eez?.layerOn && eezRegion && (
            <>
              <span className="flex items-center gap-1.5" data-eez-legend-inside>
                <span className="relative w-2.5 h-2.5 inline-flex items-center justify-center">
                  <span className="absolute w-3 h-3 rounded-full border border-red-400/70" />
                  <span className="w-2 h-2 rounded-full border border-[#0d2a47] bg-[#fbbf24]" />
                </span>
                float inside Indian EEZ
              </span>
              <span className="flex items-center gap-1" data-eez-legend-item>
                <span
                  className="w-3 h-0.5 border-t border-dashed"
                  style={{ borderColor: "rgba(103,232,249,0.9)" }}
                />
                Indian EEZ boundary
              </span>
              <span className="flex items-center gap-1.5" data-eez-legend-region>
                <span
                  className="w-3 h-2.5 rounded-[1px]"
                  style={{
                    background: "rgba(20,160,150,0.11)",
                    border: "1px dashed rgba(103,232,249,0.65)",
                  }}
                />
                Indian EEZ region
              </span>
            </>
          )}
        </div>
        <span className="font-mono text-[11px] text-sky-300/60">
          {footerNote}
        </span>
      </div>
    </div>
  );
};

export default FleetOceanMap;
