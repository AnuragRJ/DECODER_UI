/**
 * esriFleetView — the fleet map's ArcGIS Maps SDK renderer.
 *
 * Thin by design: every data decision (order, gating, colors, framing)
 * lives in fleetMapModel.ts as pure, unit-tested builders. This module
 * only translates descriptors into MapView graphics and exposes the
 * camera/frame operations the component needs.
 *
 * Loading: this module is lazy-imported by FleetOceanMap inside an
 * effect, so the SDK (+ its CSS) code-splits out of the main bundle and
 * SSR/unit tests never touch browser-only code.
 *
 * Basemap: keyless Esri raster services — World Imagery (one-metre-or-
 * better satellite/aerial) with the Boundaries & Places reference
 * overlay. No API key, no proxy; attribution stays visible in the view.
 */
import Map from "@arcgis/core/Map";
import MapView from "@arcgis/core/views/MapView";
import Basemap from "@arcgis/core/Basemap";
import TileLayer from "@arcgis/core/layers/TileLayer";
import GraphicsLayer from "@arcgis/core/layers/GraphicsLayer";
import Graphic from "@arcgis/core/Graphic";
import Point from "@arcgis/core/geometry/Point";
import Polyline from "@arcgis/core/geometry/Polyline";
import Polygon from "@arcgis/core/geometry/Polygon";
import Extent from "@arcgis/core/geometry/Extent";
import { simplify } from "@arcgis/core/geometry/geometryEngine";
import SimpleMarkerSymbol from "@arcgis/core/symbols/SimpleMarkerSymbol";
import SimpleLineSymbol from "@arcgis/core/symbols/SimpleLineSymbol";
import SimpleFillSymbol from "@arcgis/core/symbols/SimpleFillSymbol";
import TextSymbol from "@arcgis/core/symbols/TextSymbol";
import Font from "@arcgis/core/symbols/Font";
import "@arcgis/core/assets/esri/themes/dark/main.css";
import {
  MAP_COLORS,
  MAP_SIZES,
  circleRing,
  cycleLabelsVisible,
  type EezRegionDescriptor,
  type LonLatExtent,
  type MarkerDescriptor,
  type PredictionDescriptor,
  type TrajectoryDescriptor,
  type TransitionDescriptor,
} from "./fleetMapModel";

const IMAGERY_URL =
  "https://server.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer";
const REFERENCE_URL =
  "https://server.arcgisonline.com/arcgis/rest/services/Reference/World_Boundaries_and_Places/MapServer";

/** Esri symbol sizes are points (1pt ≈ 1.333 screen px @96dpi). */
const pt = (px: number) => px / 1.333333;

const WGS84 = { wkid: 4326 };

export interface FleetViewData {
  markers: MarkerDescriptor[];
  trajectory: TrajectoryDescriptor | null;
  /** Optional experimental prediction layer (OFF by default in the UI). */
  predictions: { visible: boolean; points: PredictionDescriptor[] };
  eez: {
    visible: boolean;
    region: EezRegionDescriptor | null;
    transitions: TransitionDescriptor[];
  };
}

export interface FleetViewCallbacks {
  onMarkerClick: (wmo: number) => void;
  onUserInteract: () => void;
}

export interface FleetMapViewHandle {
  view: MapView;
  whenReady: Promise<void>;
  update: (data: FleetViewData) => void;
  frameExtent: (ext: LonLatExtent | null, durationMs?: number) => void;
  frameWorld: (durationMs?: number) => void;
  zoomBy: (factor: number) => void;
  destroy: () => void;
}

export async function createFleetMapView(
  container: HTMLDivElement,
  cb: FleetViewCallbacks
): Promise<FleetMapViewHandle> {
  const imagery = new TileLayer({ url: IMAGERY_URL, title: "Esri World Imagery" });
  const reference = new TileLayer({
    url: REFERENCE_URL,
    title: "Boundaries and Places",
  });
  const basemap = new Basemap({
    baseLayers: [imagery],
    referenceLayers: [reference],
    title: "Esri Imagery Hybrid",
  });
  const map = new Map({ basemap });

  // Painter's order, bottom → top (see LAYER_ORDER in fleetMapModel).
  const eezRegionLayer = new GraphicsLayer({ title: "eez-region" });
  const eezBoundaryLayer = new GraphicsLayer({ title: "eez-boundary" });
  const trajLineLayer = new GraphicsLayer({ title: "trajectory-line" });
  const cycleDotLayer = new GraphicsLayer({ title: "cycle-dots" });
  const eezEventLayer = new GraphicsLayer({ title: "eez-events" });
  const predictionLayer = new GraphicsLayer({ title: "prediction" });
  const markerLayer = new GraphicsLayer({ title: "markers" });
  const selectionLayer = new GraphicsLayer({ title: "selection" });
  const labelLayer = new GraphicsLayer({ title: "labels" });
  map.addMany([
    eezRegionLayer,
    eezBoundaryLayer,
    trajLineLayer,
    cycleDotLayer,
    predictionLayer,
    eezEventLayer,
    markerLayer,
    selectionLayer,
    labelLayer,
  ]);

  const view = new MapView({
    container,
    map,
    center: [0, 20],
    zoom: 2,
    constraints: { minZoom: 1, maxZoom: 16, rotationEnabled: false, snapToZoom: false },
    popupEnabled: false,
    background: { color: "#0d2a47" },
    padding: { top: 28, right: 28, bottom: 28, left: 28 },
  });
  // No default widgets (custom +/−/FIT controls live in the component);
  // Esri/data attribution renders separately and stays visible.
  view.ui.components = [];

  view.on("click", (event) => {
    // Predicted markers select the same float as its real marker; the hit
    // test is additive, so existing click behavior is unchanged.
    view.hitTest(event, { include: [markerLayer, predictionLayer] }).then((res) => {
      const hit = res.results.find((r) => r.type === "graphic") as
        | { graphic?: Graphic }
        | undefined;
      const wmo = hit?.graphic?.attributes?.wmo as number | undefined;
      if (typeof wmo === "number" && !Number.isNaN(wmo)) cb.onMarkerClick(wmo);
    });
  });
  view.on("drag", () => cb.onUserInteract());
  view.on("mouse-wheel", () => cb.onUserInteract());
  view.on("double-click", () => cb.onUserInteract());

  let current: FleetViewData = {
    markers: [],
    trajectory: null,
    predictions: { visible: false, points: [] },
    eez: { visible: false, region: null, transitions: [] },
  };

  const refreshCycleLabels = () => {
    const traj = current.trajectory;
    if (!traj) {
      labelLayer.graphics.forEach((g) => {
        if (g.attributes?.kind === "cycle") g.visible = false;
      });
      return;
    }
    let pts: Array<{ x: number; y: number }> = [];
    try {
      pts = traj.dots.map((d) => {
        const s = view.toScreen(new Point({ longitude: d.lon, latitude: d.lat }));
        return { x: s.x, y: s.y };
      });
    } catch {
      return;
    }
    const show = cycleLabelsVisible(pts);
    labelLayer.graphics.forEach((g) => {
      if (g.attributes?.kind === "cycle") g.visible = show;
    });
  };
  view.watch("stationary", (stationary) => {
    if (stationary) refreshCycleLabels();
  });

  // Hover-revealed WMO label: a single transient graphic that follows the
  // hovered marker (the selected marker already shows its persistent
  // label, so it is skipped here). Markers themselves are untouched —
  // same points, same hit discs, same click behavior.
  let hoverWmo: number | null = null;
  const clearHover = () => {
    hoverWmo = null;
    labelLayer.graphics
      .filter((g) => g.attributes?.kind === "marker-hover")
      .forEach((g) => labelLayer.remove(g));
    view.container.style.cursor = "";
  };
  view.on("pointer-move", (event) => {
    view.hitTest(event, { include: [markerLayer] }).then((res) => {
      const hit = res.results.find((r) => r.type === "graphic") as
        | { graphic?: Graphic }
        | undefined;
      const wmo = hit?.graphic?.attributes?.wmo as number | undefined;
      if (typeof wmo !== "number" || Number.isNaN(wmo)) {
        clearHover();
        return;
      }
      const selectedWmo = current.markers.find((m) => m.isSelected)?.wmo ?? null;
      if (wmo === selectedWmo) {
        clearHover();
        view.container.style.cursor = "pointer";
        return;
      }
      if (wmo === hoverWmo) {
        view.container.style.cursor = "pointer";
        return;
      }
      const m = current.markers.find((mm) => mm.wmo === wmo);
      if (!m) {
        clearHover();
        return;
      }
      clearHover();
      view.container.style.cursor = "pointer";
      hoverWmo = wmo;
      labelLayer.add(
        new Graphic({
          geometry: new Point({ longitude: m.lon, latitude: m.lat }),
          symbol: new TextSymbol({
            text: m.label,
            color: MAP_COLORS.labelFill,
            haloColor: MAP_COLORS.labelHalo,
            haloSize: pt(2.8),
            xoffset: 8,
            yoffset: 2,
            horizontalAlignment: "left",
            verticalAlignment: "middle",
            font: new Font({
              size: pt(MAP_SIZES.markerLabelFont),
              family: "monospace",
              weight: "normal",
            }),
          }),
          attributes: { kind: "marker-hover", wmo },
        })
      );
    });
  });
  view.container.addEventListener("pointerleave", clearHover);

  let pulseRafId: number | null = null;
  let pulseStartTime: number = performance.now();

  const stopPulse = () => {
    if (pulseRafId !== null) {
      cancelAnimationFrame(pulseRafId);
      pulseRafId = null;
    }
  };

  const tickPulse = () => {
    const elapsed = performance.now() - pulseStartTime;
    const period = 1300;
    const t = (elapsed % period) / period;

    const haloAlpha = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * 2 * Math.PI));
    const pulseSize = pt(MAP_SIZES.eezHaloDiameter + t * 13);
    const pulseAlpha = Math.max(0.01, 0.8 * (1 - t));

    markerLayer.graphics.forEach((g) => {
      const kind = g.attributes?.kind;
      if (kind === "eez-halo") {
        const sym = g.symbol as SimpleMarkerSymbol;
        if (sym) {
          const next = sym.clone();
          next.outline.color = [248, 113, 113, haloAlpha] as unknown as any;
          g.symbol = next;
        }
      } else if (kind === "eez-pulse") {
        const sym = g.symbol as SimpleMarkerSymbol;
        if (sym) {
          const next = sym.clone();
          next.size = pulseSize;
          next.outline.color = [248, 113, 113, pulseAlpha] as unknown as any;
          g.symbol = next;
        }
      }
    });

    pulseRafId = requestAnimationFrame(tickPulse);
  };

  const startPulse = () => {
    if (pulseRafId !== null) return;
    pulseStartTime = performance.now();
    pulseRafId = requestAnimationFrame(tickPulse);
  };

  const update = (data: FleetViewData) => {
    current = data;
    (container as unknown as Record<string, unknown>).__fleetMapData = data;
    // A data refresh invalidates hover geometry — drop the transient label.
    clearHover();

    // ---- EEZ region (one graphic per disjoint polygon) ----------------
    eezRegionLayer.removeAll();
    eezBoundaryLayer.removeAll();
    eezEventLayer.removeAll();
    if (data.eez.visible && data.eez.region) {
      for (const rings of data.eez.region.polygons) {
        // Normalize through the geometry engine: the reference rings are
        // valid GeoJSON but carry duplicate/self-touching vertices that
        // break polygon triangulation unless cleaned (verified live:
        // raw rings never paint, simplified ones do).
        const shape = simplify(
          new Polygon({ rings, spatialReference: WGS84 })
        ) as Polygon;
        eezRegionLayer.add(
          new Graphic({
            geometry: shape,
            symbol: new SimpleFillSymbol({
              color: MAP_COLORS.eezFill,
              style: "solid",
              outline: { color: [0, 0, 0, 0], width: 0 },
            }),
          })
        );
        eezBoundaryLayer.add(
          new Graphic({
            geometry: shape,
            symbol: new SimpleFillSymbol({
              color: [0, 0, 0, 0],
              style: "solid",
              outline: {
                color: MAP_COLORS.eezUnderStroke,
                width: pt(MAP_SIZES.eezUnderStrokeWidth),
                style: "solid",
              },
            }),
          })
        );
        eezBoundaryLayer.add(
          new Graphic({
            geometry: shape,
            symbol: new SimpleFillSymbol({
              color: [0, 0, 0, 0],
              style: "solid",
              outline: {
                color: MAP_COLORS.eezBoundary,
                width: pt(MAP_SIZES.eezBoundaryWidth),
                style: "dash",
              },
            }),
          })
        );
      }
      const anchor = data.eez.region.anchor;
      labelLayer.graphics
        .filter((g) => g.attributes?.kind === "eez-name")
        .forEach((g) => labelLayer.remove(g));
      labelLayer.add(
        new Graphic({
          geometry: new Point({ longitude: anchor.lon, latitude: anchor.lat }),
          symbol: new TextSymbol({
            text: "INDIAN EEZ",
            color: MAP_COLORS.eezLabel,
            haloColor: MAP_COLORS.darkOutline,
            haloSize: pt(2.6),
            font: new Font({ size: pt(MAP_SIZES.eezLabelFont), family: "monospace", weight: "bold" }),
          }),
          attributes: { kind: "eez-name" },
        })
      );
    } else {
      labelLayer.graphics
        .filter((g) => g.attributes?.kind === "eez-name")
        .forEach((g) => labelLayer.remove(g));
    }
    for (const t of data.eez.visible ? data.eez.transitions : []) {
      eezEventLayer.add(
        new Graphic({
          geometry: new Point({ longitude: t.lon, latitude: t.lat }),
          symbol: new SimpleMarkerSymbol({
            style: "diamond",
            color: MAP_COLORS.operationalRed,
            size: pt(MAP_SIZES.eezDiamondSize),
            outline: { color: MAP_COLORS.darkOutline, width: 1 },
          }),
          attributes: { kind: "eez-event", id: t.id, eventType: t.eventType, description: t.description },
        })
      );
    }

    // ---- trajectory line + cycle dots ---------------------------------
    trajLineLayer.removeAll();
    cycleDotLayer.removeAll();
    labelLayer.graphics
      .filter((g) => g.attributes?.kind === "cycle")
      .forEach((g) => labelLayer.remove(g));
    const traj = data.trajectory;
    if (traj) {
      if (traj.paths.length > 0) {
        trajLineLayer.add(
          new Graphic({
            geometry: new Polyline({
              paths: traj.paths.map((path) => path.map((p) => [p.lon, p.lat])),
              spatialReference: WGS84,
            }),
            symbol: new SimpleLineSymbol({
              color: MAP_COLORS.trajectoryLine,
              width: pt(MAP_SIZES.trajectoryLineWidth),
              style: "dash",
            }),
            attributes: { kind: "trajectory", wmo: traj.wmo, points: traj.dots.length },
          })
        );
      }
      for (const d of traj.dots) {
        cycleDotLayer.add(
          new Graphic({
            geometry: new Point({ longitude: d.lon, latitude: d.lat }),
            symbol: new SimpleMarkerSymbol({
              style: "circle",
              color: d.isLast ? MAP_COLORS.cycleDotLast : MAP_COLORS.cycleDot,
              size: pt(d.isLast ? MAP_SIZES.cycleDotLastDiameter : MAP_SIZES.cycleDotDiameter),
              outline: { color: MAP_COLORS.cycleDotStroke, width: 1 },
            }),
            attributes: { kind: "cycle-dot", cycle: d.cycle, eez: d.eez ?? null },
          })
        );
      }
      traj.dots.forEach((d, i) => {
        labelLayer.add(
          new Graphic({
            geometry: new Point({ longitude: d.lon, latitude: d.lat }),
            symbol: new TextSymbol({
              text: `C${i + 1}`,
              color: MAP_COLORS.cycleLabel,
              haloColor: MAP_COLORS.darkOutline,
              haloSize: pt(2),
              xoffset: 5,
              yoffset: -5,
              horizontalAlignment: "left",
              verticalAlignment: "bottom",
              font: new Font({ size: pt(MAP_SIZES.cycleLabelFont), family: "monospace" }),
            }),
            attributes: { kind: "cycle", cycle: d.cycle },
          })
        );
      });
    }

    // ---- predicted next-profile layer (optional; OFF by default) -------
    predictionLayer.removeAll();
    if (data.predictions.visible) {
      for (const p of data.predictions.points) {
        if (p.link) {
          predictionLayer.add(
            new Graphic({
              geometry: new Polyline({
                paths: [[[p.link.lon, p.link.lat], [p.lon, p.lat]]],
                spatialReference: WGS84,
              }),
              symbol: new SimpleLineSymbol({
                color: MAP_COLORS.predictionLink,
                width: pt(MAP_SIZES.predictionLinkWidth),
                style: "short-dash",
              }),
              attributes: { kind: "prediction-link", wmo: p.wmo },
            })
          );
        }
        // Nested validated radii: the 90% circle (dashed) and the 50% circle.
        for (const ring of [
          { radius: p.r90Km, style: "dash" as const },
          { radius: p.r50Km, style: "solid" as const },
        ]) {
          if (ring.radius == null || !(ring.radius > 0)) continue;
          const ringGeometry = new Polygon({
            rings: [circleRing(p.lon, p.lat, ring.radius)],
            spatialReference: WGS84,
          });
          predictionLayer.add(
            new Graphic({
              geometry: ringGeometry,
              symbol: new SimpleFillSymbol({
                color: MAP_COLORS.predictionFill,
                style: "solid",
                outline: {
                  color: MAP_COLORS.predictionRing,
                  width: pt(MAP_SIZES.predictionRingWidth),
                  style: ring.style,
                },
              }),
              attributes: { kind: "prediction-ring", wmo: p.wmo, radiusKm: ring.radius },
            })
          );
        }
        // Deliberately distinct symbol: a hollow diamond, never the yellow
        // circle used for the float's real (observed) position.
        predictionLayer.add(
          new Graphic({
            geometry: new Point({ longitude: p.lon, latitude: p.lat }),
            symbol: new SimpleMarkerSymbol({
              style: "diamond",
              color: MAP_COLORS.predictionMarker,
              size: pt(MAP_SIZES.predictionMarkerSize),
              outline: {
                color: p.isSelected
                  ? MAP_COLORS.predictionMarkerSelected
                  : MAP_COLORS.predictionMarkerStroke,
                width: 1.3,
              },
            }),
            attributes: { kind: "prediction", wmo: p.wmo, title: p.title },
          })
        );
      }
    }

    // ---- fleet markers + selection + labels ---------------------------
    markerLayer.removeAll();
    selectionLayer.removeAll();
    labelLayer.graphics
      .filter((g) => g.attributes?.kind === "marker")
      .forEach((g) => labelLayer.remove(g));
    data.markers.forEach((m, idx) => {
      const ptGeom = new Point({ longitude: m.lon, latitude: m.lat });
      // generous invisible hit disc (forgiving click target)
      markerLayer.add(
        new Graphic({
          geometry: ptGeom,
          symbol: new SimpleMarkerSymbol({
            style: "circle",
            color: [0, 0, 0, 0],
            size: pt(MAP_SIZES.markerHitDiameter),
            outline: { color: [0, 0, 0, 0], width: 0 },
          }),
          attributes: { kind: "hit", wmo: m.wmo },
        })
      );
      if (m.insideEez || m.isBlinking) {
        markerLayer.add(
          new Graphic({
            geometry: ptGeom,
            symbol: new SimpleMarkerSymbol({
              style: "circle",
              color: [0, 0, 0, 0],
              size: pt(MAP_SIZES.eezHaloDiameter),
              outline: { color: MAP_COLORS.eezHalo, width: 1.2 },
            }),
            attributes: { kind: "eez-halo", wmo: m.wmo },
          })
        );
        markerLayer.add(
          new Graphic({
            geometry: ptGeom,
            symbol: new SimpleMarkerSymbol({
              style: "circle",
              color: [0, 0, 0, 0],
              size: pt(MAP_SIZES.eezHaloDiameter),
              outline: { color: [248, 113, 113, 0.75], width: 1.4 },
            }),
            attributes: { kind: "eez-pulse", wmo: m.wmo },
          })
        );
      }
      // dark under-halo keeps yellow readable over bright terrain
      markerLayer.add(
        new Graphic({
          geometry: ptGeom,
          symbol: new SimpleMarkerSymbol({
            style: "circle",
            color: MAP_COLORS.markerHalo,
            size: pt(MAP_SIZES.markerDiameter + 4),
            outline: { color: [0, 0, 0, 0], width: 0 },
          }),
          attributes: { kind: "under", wmo: m.wmo },
        })
      );
      markerLayer.add(
        new Graphic({
          geometry: ptGeom,
          symbol: new SimpleMarkerSymbol({
            style: "circle",
            color: m.isSelected ? MAP_COLORS.markerFillSelected : MAP_COLORS.markerFill,
            size: pt(MAP_SIZES.markerDiameter),
            outline: {
              color: m.isSelected ? MAP_COLORS.markerStrokeSelected : MAP_COLORS.markerStroke,
              width: 1.1,
            },
          }),
          attributes: { kind: "marker", wmo: m.wmo, title: m.title },
        })
      );
      if (m.isSelected) {
        selectionLayer.add(
          new Graphic({
            geometry: ptGeom,
            symbol: new SimpleMarkerSymbol({
              style: "circle",
              color: [0, 0, 0, 0],
              size: pt(MAP_SIZES.selectionRingDiameter),
              outline: { color: MAP_COLORS.selectionRing, width: 1.6 },
            }),
            attributes: { kind: "selection", wmo: m.wmo },
          })
        );
      }
      // WMO labels are revealed, not persistent: only the selected
      // (clicked) marker carries its label. Hover shows a transient
      // label for any other marker (see the pointer-move handler).
      if (m.isSelected) {
        const labelRight = idx % 2 === 0;
        labelLayer.add(
          new Graphic({
            geometry: ptGeom,
            symbol: new TextSymbol({
              text: m.label,
              color: MAP_COLORS.labelFillSelected,
              haloColor: MAP_COLORS.labelHalo,
              haloSize: pt(2.8),
              xoffset: labelRight ? 8 : -8,
              yoffset: 2,
              horizontalAlignment: labelRight ? "left" : "right",
              verticalAlignment: "middle",
              font: new Font({
                size: pt(MAP_SIZES.markerLabelFontSelected),
                family: "monospace",
                weight: "bold",
              }),
            }),
            attributes: { kind: "marker", wmo: m.wmo },
          })
        );
      }
    });

    refreshCycleLabels();

    const hasBlinking = data.markers.some((m) => m.insideEez || m.isBlinking);
    if (hasBlinking) {
      startPulse();
    } else {
      stopPulse();
    }
  };

  const frameExtent = (ext: LonLatExtent | null, durationMs = 380) => {
    if (!ext) {
      frameWorld(durationMs);
      return;
    }
    view
      .goTo(
        new Extent({
          xmin: ext.xmin,
          ymin: ext.ymin,
          xmax: ext.xmax,
          ymax: ext.ymax,
          spatialReference: WGS84,
        }),
        { duration: durationMs }
      )
      .catch(() => undefined);
  };

  const frameWorld = (durationMs = 380) => {
    view.goTo({ center: [0, 20], zoom: 2 }, { duration: durationMs }).catch(() => undefined);
  };

  const zoomBy = (factor: number) => {
    view
      .goTo({ center: view.center, zoom: view.zoom + Math.log2(factor) }, { duration: 200 })
      .catch(() => undefined);
  };

  const whenReady = view.when().then(() => undefined);

  const handle: FleetMapViewHandle = {
    view,
    whenReady,
    update,
    frameExtent,
    frameWorld,
    zoomBy,
    destroy: () => {
      stopPulse();
      view.container.removeEventListener("pointerleave", clearHover);
      view.destroy();
    },
  };
  (container as unknown as Record<string, unknown>).__fleetMapView = handle;
  return handle;
}
