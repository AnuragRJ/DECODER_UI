/**
 * Indian EEZ classification — pure, dependency-free geographic logic.
 *
 * Consumes the VERIFIED reference geometry (Marine Regions World EEZ v12,
 * 2023-10-25 — Indian features MRGID 8480 + MRGID 8333, EPSG:4326; see
 * decoder-ui/data/geography/README.md) and provides:
 *
 *  - one-time, validated geometry parsing (declares provenance inline);
 *  - exact point-in-polygon classification of real decoded float positions
 *    (union test over both Indian features, even-odd ring rule = the same
 *    fill rule the SVG renderer uses, so the map and the classifier can
 *    never disagree);
 *  - per-cycle EEZ status (`INDIAN_EEZ` / `OUTSIDE_INDIAN_EEZ`) as a
 *    dimension completely separate from processing status;
 *  - EEZ entry/exit transition derivation with STABLE identities
 *    (WMO + previous cycle + current cycle + event type), rerun-safe
 *    dedupe, and strictly neutral scientific wording. The module never
 *    fabricates a crossing location or timestamp.
 *
 * No date-line handling is needed for this dataset: every Indian-EEZ
 * coordinate lies in 65.64°E..95.70°E.
 */

export type EezStatus = "INDIAN_EEZ" | "OUTSIDE_INDIAN_EEZ";

export interface EezPosition {
  cycle: number;
  lat: number;
  lon: number;
  juld?: number | null;
}

export interface EezTransition {
  /** Stable, collision-free identity: rerun/idempotency + dedupe key. */
  id: string;
  wmo: number;
  eventType: "EEZ_ENTRY" | "EEZ_EXIT";
  fromCycle: number;
  toCycle: number;
  fromStatus: EezStatus;
  toStatus: EezStatus;
  /** Exact neutral scientific phrasing (single source of truth). */
  description: string;
}

interface EezGeometry {
  /** Each element is one polygon: outer ring + optional holes. */
  polygons: number[][][][];
}

export interface IndiaEez {
  geometry: EezGeometry;
  /** Dataset provenance, parsed from the artifact (never invented). */
  meta: {
    mrgids: number[];
    geonames: string[];
    featureCount: number;
  };
}

const MAX_ABS_COORD = { lon: 180, lat: 90 };

// ---------------------------------------------------------------------------
// Geometry parsing + strict validation
// ---------------------------------------------------------------------------

function asRingList(coords: unknown, what: string): number[][][] {
  if (!Array.isArray(coords) || coords.length === 0) {
    throw new Error(`EEZ artifact: ${what} is empty`);
  }
  const rings: number[][][] = [];
  for (const ring of coords as unknown[]) {
    if (!Array.isArray(ring) || ring.length < 4) {
      throw new Error(`EEZ artifact: ${what} has a degenerate ring`);
    }
    const pts: number[][] = [];
    for (const c of ring as unknown[]) {
      if (!Array.isArray(c) || c.length !== 2) {
        throw new Error(`EEZ artifact: ${what} has a malformed coordinate`);
      }
      const [lon, lat] = c as unknown[];
      if (
        typeof lon !== "number" ||
        typeof lat !== "number" ||
        !Number.isFinite(lon) ||
        !Number.isFinite(lat) ||
        Math.abs(lon) > MAX_ABS_COORD.lon ||
        Math.abs(lat) > MAX_ABS_COORD.lat
      ) {
        throw new Error(`EEZ artifact: ${what} coordinate out of range`);
      }
      pts.push([lon, lat]);
    }
    const first = pts[0];
    const last = pts[pts.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) {
      throw new Error(`EEZ artifact: ${what} ring is not closed`);
    }
    rings.push(pts);
  }
  return rings;
}

/**
 * Parse + validate the artifact. Throws on ANY structural defect — the
 * caller must treat a parse failure as "layer unavailable" and hide every
 * dependent affordance (nothing is approximated).
 */
export function parseIndiaEez(raw: unknown): IndiaEez {
  const doc = raw as {
    type?: string;
    features?: Array<{
      type?: string;
      properties?: Record<string, unknown>;
      geometry?: { type?: string; coordinates?: unknown };
    }>;
  };
  if (!doc || doc.type !== "FeatureCollection" || !Array.isArray(doc.features)) {
    throw new Error("EEZ artifact: not a FeatureCollection");
  }
  if (doc.features.length === 0) {
    throw new Error("EEZ artifact: no features");
  }
  const polygons: number[][][][] = [];
  const mrgids: number[] = [];
  const geonames: string[] = [];
  for (const f of doc.features) {
    if (!f || f.type !== "Feature" || !f.geometry) {
      throw new Error("EEZ artifact: malformed feature");
    }
    const g = f.geometry;
    const what = `MRGID ${String(f.properties?.MRGID ?? "?")}`;
    if (g.type === "Polygon") {
      polygons.push(asRingList(g.coordinates, what));
    } else if (g.type === "MultiPolygon") {
      if (!Array.isArray(g.coordinates) || (g.coordinates as unknown[]).length === 0) {
        throw new Error(`EEZ artifact: ${what} MultiPolygon is empty`);
      }
      for (const poly of g.coordinates as unknown[]) {
        polygons.push(asRingList(poly, what));
      }
    } else {
      throw new Error(`EEZ artifact: unsupported geometry type ${String(g.type)}`);
    }
    const mrgid = Number(f.properties?.MRGID);
    if (!Number.isInteger(mrgid) || f.properties?.SOVEREIGN1 !== "India") {
      throw new Error(`EEZ artifact: unexpected non-India feature ${what}`);
    }
    mrgids.push(mrgid);
    if (typeof f.properties?.GEONAME === "string") geonames.push(f.properties.GEONAME);
  }
  mrgids.sort((a, b) => a - b);
  if (mrgids.length !== 2 || mrgids[0] !== 8333 || mrgids[1] !== 8480) {
    throw new Error(
      `EEZ artifact: expected exactly the Indian features MRGID 8333 + 8480, got [${mrgids.join(", ")}]`
    );
  }
  // India-only extent guard (well inside Eurasian longitudes, far from any date-line logic)
  let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
  for (const poly of polygons) {
    for (const ring of poly) {
      for (const [lon, lat] of ring) {
        if (lon < minLon) minLon = lon;
        if (lon > maxLon) maxLon = lon;
        if (lat < minLat) minLat = lat;
        if (lat > maxLat) maxLat = lat;
      }
    }
  }
  if (!(minLon > 63 && maxLon < 100 && minLat > 2 && maxLat < 25)) {
    throw new Error("EEZ artifact: extent is not India-only");
  }
  return {
    geometry: { polygons },
    meta: { mrgids, geonames, featureCount: doc.features.length },
  };
}

// ---------------------------------------------------------------------------
// Point-in-polygon (exact even-odd rule over the union of both features)
// ---------------------------------------------------------------------------

function ringContains(ring: number[][], lon: number, lat: number): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 2; i < ring.length - 1; j = i, i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function polygonContains(poly: number[][][], lon: number, lat: number): boolean {
  if (!ringContains(poly[0], lon, lat)) return false;
  for (let h = 1; h < poly.length; h++) {
    if (ringContains(poly[h], lon, lat)) return false;
  }
  return true;
}

export function pointInIndiaEez(geom: EezGeometry, lon: number, lat: number): boolean {
  if (
    !Number.isFinite(lon) ||
    !Number.isFinite(lat) ||
    Math.abs(lon) > MAX_ABS_COORD.lon ||
    Math.abs(lat) > MAX_ABS_COORD.lat
  ) {
    return false;
  }
  for (const poly of geom.polygons) {
    if (polygonContains(poly, lon, lat)) return true;
  }
  return false;
}

export function classifyPoint(geom: EezGeometry, lon: number, lat: number): EezStatus {
  return pointInIndiaEez(geom, lon, lat) ? "INDIAN_EEZ" : "OUTSIDE_INDIAN_EEZ";
}

// ---------------------------------------------------------------------------
// Per-cycle classification + transition derivation
// ---------------------------------------------------------------------------

export interface ClassifiedCycle extends EezPosition {
  eezStatus: EezStatus;
}

/**
 * Classify a float's real decoded positions. Input is assumed sorted by the
 * caller's canonical order (CYCLE_NUMBER, JULD tiebreak) — the sorter below
 * enforces it exactly so callers can pass any cycle collection.
 */
export function classifyTrajectory(geom: EezGeometry, points: EezPosition[]): ClassifiedCycle[] {
  const ordered = [...points]
    .filter(
      (p) =>
        Number.isFinite(p.lon) &&
        Number.isFinite(p.lat) &&
        Math.abs(p.lon) <= MAX_ABS_COORD.lon &&
        Math.abs(p.lat) <= MAX_ABS_COORD.lat
    )
    .sort((a, b) => a.cycle - b.cycle || (a.juld ?? 0) - (b.juld ?? 0));
  return ordered.map((p) => ({
    ...p,
    eezStatus: classifyPoint(geom, p.lon, p.lat),
  }));
}

function transitionId(wmo: number, fromCycle: number, toCycle: number, t: "EEZ_ENTRY" | "EEZ_EXIT"): string {
  return `eez|${wmo}|${fromCycle}|${toCycle}|${t}`;
}

function describe(wmo: number, fromCycle: number, toCycle: number, t: "EEZ_ENTRY" | "EEZ_EXIT"): string {
  const verb = t === "EEZ_ENTRY" ? "entered" : "exited";
  return (
    `WMO ${wmo} ${verb} the Indian EEZ between Cycle ${fromCycle} and Cycle ${toCycle} ` +
    `based on the available decoded positions`
  );
}

/**
 * Derive EEZ entry/exit transitions from ACTUAL consecutive valid
 * classified cycles only. Consecutive means adjacent entries of the
 * (sorted, valid-position) trajectory: transitions appear strictly where
 * the point-in-polygon outcome flips between two real decoded positions.
 * No interpolation, no guessed crossing point or time — it is impossible
 * for the same (wmo, fromCycle, toCycle, type) pair to appear twice.
 */
export function deriveEezTransitions(wmo: number, classified: ClassifiedCycle[]): EezTransition[] {
  const out: EezTransition[] = [];
  for (let i = 1; i < classified.length; i++) {
    const prev = classified[i - 1];
    const cur = classified[i];
    if (prev.eezStatus === cur.eezStatus) continue;
    const t: "EEZ_ENTRY" | "EEZ_EXIT" =
      prev.eezStatus === "OUTSIDE_INDIAN_EEZ" && cur.eezStatus === "INDIAN_EEZ"
        ? "EEZ_ENTRY"
        : "EEZ_EXIT";
    out.push({
      id: transitionId(wmo, prev.cycle, cur.cycle, t),
      wmo,
      eventType: t,
      fromCycle: prev.cycle,
      toCycle: cur.cycle,
      fromStatus: prev.eezStatus,
      toStatus: cur.eezStatus,
      description: describe(wmo, prev.cycle, cur.cycle, t),
    });
  }
  return out;
}

export const EEZ_ALERT_TITLES: Record<EezTransition["eventType"], string> = {
  EEZ_ENTRY: "Indian EEZ Entry Detected",
  EEZ_EXIT: "Indian EEZ Exit Detected",
};

export function descriptionForTransition(tr: EezTransition): string {
  return tr.description;
}

// ---------------------------------------------------------------------------
// Presentation helpers (pure, deterministic)
// ---------------------------------------------------------------------------

/**
 * Deterministic interior anchor for the compact layer label: a coarse
 * pole-of-inaccessibility search inside the polygon with the largest shell.
 * Works in plain lon/lat degrees (the Indian EEZ is far from the date line),
 * so the returned anchor is a REAL interior lon/lat that the map projects
 * through its own transform — never a pixel offset.
 */
export function findInteriorAnchor(geom: EezGeometry): { lon: number; lat: number } {
  let best: { lon: number; lat: number; score: number } | null = null;
  for (const poly of geom.polygons) {
    const shell = poly[0];
    let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
    for (const [lon, lat] of shell) {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
    const area = (maxLon - minLon) * (maxLat - minLat);
    if (best && area < best.score * 0.25) continue; // skip tiny parts once a big one exists
    const step = 0.5;
    const refine = (cx: number, cy: number, s: number, depth: number): { lon: number; lat: number } => {
      let cand: { lon: number; lat: number } | null = null;
      let bestDist = -1;
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          const lon = cx + dx * s;
          const lat = cy + dy * s;
          if (!polygonContains(poly, lon, lat)) continue;
          // distance to the nearest shell vertex-sample (cheap clearance proxy)
          let d = Infinity;
          for (let i = 0; i < shell.length - 1; i += 3) {
            const dd = Math.hypot(lon - shell[i][0], lat - shell[i][1]);
            if (dd < d) d = dd;
          }
          if (d > bestDist) {
            bestDist = d;
            cand = { lon, lat };
          }
        }
      }
      if (cand && depth > 0 && bestDist > s * 0.35) return refine(cand.lon, cand.lat, s / 2, depth - 1);
      return cand ?? { lon: cx, lat: cy };
    };
    let cx = (minLon + maxLon) / 2;
    let cy = (minLat + maxLat) / 2;
    let anchor = polygonContains(poly, cx, cy) ? { lon: cx, lat: cy } : null;
    if (!anchor) {
      outer: for (let lon = minLon + step / 2; lon < maxLon; lon += step) {
        for (let lat = minLat + step / 2; lat < maxLat; lat += step) {
          if (polygonContains(poly, lon, lat)) {
            anchor = { lon, lat };
            break outer;
          }
        }
      }
    }
    if (!anchor) continue;
    const refined = refine(anchor.lon, anchor.lat, Math.min((maxLon - minLon), (maxLat - minLat)) / 6, 3);
    if (!best || area > best.score) best = { ...refined, score: area };
  }
  if (!best) {
    // geometry validated upstream; an anchor must exist — but never crash the
    // UI: fall back to the first ring vertex midpoint.
    const r0 = geom.polygons[0][0];
    const mid = r0[Math.floor(r0.length / 2)];
    return { lon: mid[0], lat: mid[1] };
  }
  return { lon: best.lon, lat: best.lat };
}
