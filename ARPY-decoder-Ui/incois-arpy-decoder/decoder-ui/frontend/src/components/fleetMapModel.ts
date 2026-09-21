/**
 * fleetMapModel — pure, SDK-free data builders for the fleet map.
 *
 * The map renders through the ArcGIS Maps SDK (see esriFleetView.ts), which
 * paints to canvas and needs a browser. EVERYTHING testable about the map's
 * data logic therefore lives here as pure functions over lon/lat:
 * chronological trajectory order, marker/selection styling decisions, the
 * cycle-label declutter rule, EEZ treatment + gating, transition diamonds,
 * antimeridian-safe paths, and frame/fit extents. The Esri view module is a
 * thin renderer over these descriptors; the vitest suite pins them.
 *
 * Visual constants are the single source of truth: they preserve the exact
 * established workstation palette (yellows, sky trajectory, teal/cyan EEZ,
 * red operational family) so the basemap swap changes imagery, not meaning.
 */

import {
  findInteriorAnchor,
  type ClassifiedCycle,
  type EezStatus,
  type EezTransition,
  type IndiaEez,
} from "../utils/indiaEez";

export interface FleetMapFloat {
  wmo: number;
  platform: string;
  status: string;
  lat: number;
  lon: number;
  cyclesCount: number;
  runId?: string;
}

export interface FleetMapTrajectoryPoint {
  cycle: number;
  lat: number;
  lon: number;
  posQc?: string | number;
  juld?: number | null;
}

/** Rendering order, bottom → top. The trajectory always paints above
 *  fleet markers so clustered cycle dots can never hide beneath them.
 *  "prediction" (optional layer, OFF by default) sits above the trajectory
 *  and below the markers: the predicted point must never hide the float's
 *  REAL position. */
export const LAYER_ORDER = [
  "eez-region",
  "eez-boundary",
  "trajectory-line",
  "cycle-dots",
  "prediction",
  "eez-events",
  "markers",
  "selection",
  "labels",
] as const;

export const MAP_COLORS = {
  markerFill: "#fbbf24",
  markerFillSelected: "#fde047",
  markerStroke: "#0d2a47",
  markerStrokeSelected: "#a16207",
  markerHalo: "rgba(10,35,56,0.75)",
  selectionRing: "#fde047",
  labelFill: "#ffffff",
  labelFillSelected: "#fde68a",
  labelHalo: "#0d2a47",
  trajectoryLine: "#7dd3fc",
  cycleDot: "#7dd3fc",
  cycleDotLast: "#fbbf24",
  cycleDotStroke: "#0d2a47",
  cycleLabel: "#e0f2fe",
  eezFill: "rgba(20,160,150,0.11)",
  eezUnderStroke: "rgba(103,232,249,0.22)",
  eezBoundary: "rgba(103,232,249,0.85)",
  eezLabel: "rgba(103,232,249,0.95)",
  eezHalo: "rgba(248,113,113,0.6)",
  operationalRed: "rgba(248,113,113,0.95)",
  darkOutline: "#0a2338",
  /** Prediction layer (experimental): cyan family, deliberately distinct from
   *  the yellow "real position" markers. */
  predictionFill: "rgba(56,189,248,0.10)",
  predictionRing: "rgba(125,211,252,0.9)",
  predictionMarker: "rgba(13,42,71,0.9)",
  predictionMarkerStroke: "#7dd3fc",
  predictionMarkerSelected: "#e0f2fe",
  predictionLink: "rgba(125,211,252,0.5)",
} as const;

/** Constant screen sizes (px @ 96dpi) — readable at every zoom. */
export const MAP_SIZES = {
  markerDiameter: 8,
  markerHitDiameter: 26,
  selectionRingDiameter: 15,
  eezHaloDiameter: 17,
  cycleDotDiameter: 4.6,
  cycleDotLastDiameter: 8,
  trajectoryLineWidth: 2,
  eezBoundaryWidth: 1.15,
  eezUnderStrokeWidth: 3,
  eezDiamondSize: 9.2,
  markerLabelFont: 10,
  markerLabelFontSelected: 11.5,
  cycleLabelFont: 8,
  eezLabelFont: 10,
  predictionMarkerSize: 10.5,
  predictionRingWidth: 1.2,
  predictionLinkWidth: 1.1,
} as const;

export const STATUS_LABEL: Record<string, string> = {
  completed: "SUCCESS",
  error: "FAILED",
  stopped: "STOPPED",
  cancelled: "STOPPED",
  active: "RUNNING",
};

/** Cycle labels render only when uncluttered: 2–64 dots and the two
 *  closest consecutive dots ≥ 9 px apart (screen space). */
export const MAX_LABELLED_CYCLES = 64;
export const MIN_LABEL_SPACING_PX = 9;

/** Chronological order: cycle ascending, juld as the tiebreak.
 *  The input order is never trusted (callers may shuffle). */
export function sortTrajectoryChronologically(
  points: readonly FleetMapTrajectoryPoint[]
): FleetMapTrajectoryPoint[] {
  const pts = [...points];
  pts.sort((a, b) => a.cycle - b.cycle || (a.juld ?? 0) - (b.juld ?? 0));
  return pts;
}

/**
 * Antimeridian-safe paths: a naive lon trace across ±180° draws a
 * across-the-world chord. Split wherever consecutive points jump more
 * than 180° of longitude. Returns one path per continuous piece.
 */
export function splitAntimeridianPath(
  points: ReadonlyArray<{ lon: number; lat: number }>
): Array<Array<{ lon: number; lat: number }>> {
  const paths: Array<Array<{ lon: number; lat: number }>> = [];
  let current: Array<{ lon: number; lat: number }> = [];
  let prevLon: number | null = null;
  for (const p of points) {
    if (prevLon !== null && Math.abs(p.lon - prevLon) > 180) {
      if (current.length > 0) paths.push(current);
      current = [];
    }
    current.push(p);
    prevLon = p.lon;
  }
  if (current.length > 0) paths.push(current);
  return paths;
}

export interface MarkerDescriptor {
  wmo: number;
  lon: number;
  lat: number;
  isSelected: boolean;
  /** True only while the EEZ layer is ON and this float's latest valid
   *  position is currently inside — a geographic state, never an event. */
  insideEez: boolean;
  label: string;
  title: string;
}

/** One descriptor per float with a decoded position. Nothing is
 *  fabricated: floats without positions never reach this builder. */
export function buildMarkerDescriptors(
  positions: readonly FleetMapFloat[],
  selectedWmo: number | null,
  currentStatus: Record<number, EezStatus | undefined> | undefined,
  eezLayerOn: boolean
): MarkerDescriptor[] {
  return positions.map((fp) => {
    const isSelected = fp.wmo === selectedWmo;
    const insideEez = eezLayerOn === true && currentStatus?.[fp.wmo] === "INDIAN_EEZ";
    const title =
      `WMO ${fp.wmo} · ${fp.platform} · ${STATUS_LABEL[fp.status] || fp.status.toUpperCase()}` +
      (insideEez ? " · currently inside Indian EEZ" : "");
    return { wmo: fp.wmo, lon: fp.lon, lat: fp.lat, isSelected, insideEez, label: String(fp.wmo), title };
  });
}

/** Prediction input for the optional map layer (one per float). Only floats
 *  whose prediction is AVAILABLE and inside valid coordinate ranges arrive
 *  here — an unavailable prediction is never drawn as a marker. */
export interface FleetMapPrediction {
  wmo: number;
  lat: number;
  lon: number;
  /** Current (observed) position, used for the dashed connector. */
  fromLat?: number | null;
  fromLon?: number | null;
  r50Km: number | null;
  r90Km: number | null;
  methodLabel?: string | null;
  targetTimeIso?: string | null;
}

export interface PredictionDescriptor {
  wmo: number;
  lon: number;
  lat: number;
  /** Dashed link back to the real position, when it is known. */
  link: { lon: number; lat: number } | null;
  r50Km: number | null;
  r90Km: number | null;
  isSelected: boolean;
  label: string;
  title: string;
}

function validLonLat(lon: unknown, lat: unknown): boolean {
  return (
    typeof lon === "number" &&
    typeof lat === "number" &&
    Number.isFinite(lon) &&
    Number.isFinite(lat) &&
    Math.abs(lon) <= 180 &&
    Math.abs(lat) <= 90
  );
}

/** Predicted next-profile positions. Nothing is fabricated: invalid
 *  coordinates or a missing radius simply produce no descriptor. */
export function buildPredictionDescriptors(
  predictions: readonly FleetMapPrediction[],
  selectedWmo: number | null
): PredictionDescriptor[] {
  const out: PredictionDescriptor[] = [];
  for (const p of predictions) {
    if (!validLonLat(p.lon, p.lat)) continue;
    const link =
      p.fromLon != null && p.fromLat != null && validLonLat(p.fromLon, p.fromLat)
        ? { lon: p.fromLon, lat: p.fromLat }
        : null;
    const isSelected = p.wmo === selectedWmo;
    const title =
      `WMO ${p.wmo} · predicted next profile${p.methodLabel ? ` · ${p.methodLabel}` : ""}` +
      (p.r90Km != null ? ` · 90% radius ${p.r90Km} km` : "") +
      (p.targetTimeIso ? ` · target ${p.targetTimeIso}` : "");
    out.push({
      wmo: p.wmo,
      lon: p.lon,
      lat: p.lat,
      link,
      r50Km: p.r50Km ?? null,
      r90Km: p.r90Km ?? null,
      isSelected,
      label: `P${p.wmo}`,
      title,
    });
  }
  return out;
}

/** Closed ring approximating a great-circle radius in degrees.
 *  Pure and unit-tested: the map paints it, but nothing about the geometry is
 *  ArcGIS-specific, so the uncertainty area can be asserted without a browser.
 *  `segments` controls smoothness only (36 ≈ 10° steps). */
/**
 * Mean Earth radius (metres -> km) used to place uncertainty-ring vertices.
 * Matches the haversine radius used by the prediction validation code.
 */
const EARTH_RADIUS_KM = 6371.0088;

export function circleRing(
  lon: number,
  lat: number,
  radiusKm: number,
  segments = 36
): number[][] {
  const ring: number[][] = [];
  if (!(radiusKm > 0)) return ring;
  // Geodesic circle: vertices are placed by the spherical destination-point
  // formula, so every vertex is exactly ``radiusKm`` from the centre on the
  // sphere. A local equirectangular approximation drifts by >1 % of the radius
  // at high latitudes, which would draw the 50 %/90 % uncertainty rings at the
  // wrong distance from the predicted point.
  const angular = radiusKm / EARTH_RADIUS_KM;
  const sinAngular = Math.sin(angular);
  const cosAngular = Math.cos(angular);
  const phi1 = (lat * Math.PI) / 180;
  const lambda1 = (lon * Math.PI) / 180;
  const sinPhi1 = Math.sin(phi1);
  const cosPhi1 = Math.cos(phi1);
  for (let i = 0; i <= segments; i += 1) {
    const theta = (2 * Math.PI * i) / segments;
    const sinPhi2 = sinPhi1 * cosAngular + cosPhi1 * sinAngular * Math.cos(theta);
    const phi2 = Math.asin(Math.max(-1, Math.min(1, sinPhi2)));
    const lambda2 =
      lambda1 +
      Math.atan2(
        Math.sin(theta) * sinAngular * cosPhi1,
        cosAngular - sinPhi1 * sinPhi2
      );
    const ringLat = Math.max(-90, Math.min(90, (phi2 * 180) / Math.PI));
    const ringLon = ((((lambda2 * 180) / Math.PI) + 180) % 360 + 360) % 360 - 180;
    ring.push([ringLon, ringLat]);
  }
  return ring;
}

export interface TrajectoryDotDescriptor {
  cycle: number;
  lon: number;
  lat: number;
  isLast: boolean;
  /** Per-cycle EEZ state when the workspace classified this trajectory. */
  eez?: EezStatus;
}

export interface TrajectoryDescriptor {
  wmo: number | null;
  /** Antimeridian-split line paths (chronological within each piece). */
  paths: Array<Array<{ lon: number; lat: number }>>;
  dots: TrajectoryDotDescriptor[];
}

/** The selected float's real trajectory, chronological. Returns null
 *  when fewer than 2 points exist (no line to draw). */
export function buildTrajectoryDescriptor(
  ordered: readonly FleetMapTrajectoryPoint[],
  selectedWmo: number | null,
  classified: readonly ClassifiedCycle[] | null
): TrajectoryDescriptor | null {
  if (ordered.length < 2) return null;
  const byCycle = new Map<number, EezStatus>();
  if (classified) for (const c of classified) byCycle.set(c.cycle, c.eezStatus);
  return {
    wmo: selectedWmo,
    paths: splitAntimeridianPath(ordered),
    dots: ordered.map((p, i) => ({
      cycle: p.cycle,
      lon: p.lon,
      lat: p.lat,
      isLast: i === ordered.length - 1,
      eez: byCycle.get(p.cycle),
    })),
  };
}

/** Screen-space declutter rule for C1..Cn labels. */
export function cycleLabelsVisible(screenPts: ReadonlyArray<{ x: number; y: number }>): boolean {
  const n = screenPts.length;
  if (n < 2 || n > MAX_LABELLED_CYCLES) return false;
  let minD = Infinity;
  for (let i = 1; i < n; i++) {
    const d = Math.hypot(screenPts[i].x - screenPts[i - 1].x, screenPts[i].y - screenPts[i - 1].y);
    if (d < minD) minD = d;
  }
  return minD >= MIN_LABEL_SPACING_PX;
}

export interface TransitionDescriptor {
  id: string;
  eventType: "EEZ_ENTRY" | "EEZ_EXIT";
  lon: number;
  lat: number;
  description: string;
}

/** Entry/exit diamonds sit on the REAL to-cycle position. Transitions
 *  whose to-cycle has no trajectory point are dropped (never guessed). */
export function buildTransitionDescriptors(
  transitions: readonly EezTransition[],
  trajectoryByCycle: ReadonlyMap<number, { lon: number; lat: number }>
): TransitionDescriptor[] {
  const out: TransitionDescriptor[] = [];
  for (const t of transitions) {
    const p = trajectoryByCycle.get(t.toCycle);
    if (p) out.push({ id: t.id, eventType: t.eventType, lon: p.lon, lat: p.lat, description: t.description });
  }
  return out;
}

export interface EezRegionDescriptor {
  /** One ring-list per disjoint polygon (outer + holes each). */
  polygons: number[][][][];
  anchor: { lon: number; lat: number };
}

export function buildEezRegionDescriptor(geom: IndiaEez): EezRegionDescriptor {
  return { polygons: geom.geometry.polygons, anchor: findInteriorAnchor(geom.geometry) };
}

export interface LonLatExtent {
  xmin: number;
  ymin: number;
  xmax: number;
  ymax: number;
}

/**
 * Lon/lat frame for a set of real points: symmetric `padFrac` breathing
 * room, never smaller than `minSpanDeg` per axis (tiny clusters stay
 * inspectable). The view fits the aspect; null when there is nothing
 * real to frame (callers fall back to the neutral world view).
 */
export function frameExtentFor(
  pts: ReadonlyArray<{ lon: number; lat: number }>,
  padFrac: number,
  minSpanDeg: number
): LonLatExtent | null {
  if (pts.length === 0) return null;
  const xs = pts.map((p) => p.lon);
  const ys = pts.map((p) => p.lat);
  let xmin = Math.min(...xs);
  let xmax = Math.max(...xs);
  let ymin = Math.min(...ys);
  let ymax = Math.max(...ys);
  // Antimeridian-spanning sets (e.g. 179° and −179°) must frame the short
  // way, not the whole planet: shift the set into a continuous window.
  if (xmax - xmin > 180) {
    const shifted = xs.map((x) => (x < 0 ? x + 360 : x));
    xmin = Math.min(...shifted);
    xmax = Math.max(...shifted);
  }
  let spanX = Math.max(xmax - xmin, minSpanDeg);
  let spanY = Math.max(ymax - ymin, minSpanDeg);
  const cx = (xmin + xmax) / 2;
  const cy = (ymin + ymax) / 2;
  spanX *= 1 + padFrac;
  spanY *= 1 + padFrac;
  let exmin = cx - spanX / 2;
  let exmax = cx + spanX / 2;
  if (exmin >= 180) {
    exmin -= 360;
    exmax -= 360;
  }
  return {
    xmin: Math.max(-180, exmin),
    ymin: Math.max(-90, cy - spanY / 2),
    xmax: Math.min(540, exmax),
    ymax: Math.min(90, cy + spanY / 2),
  };
}
