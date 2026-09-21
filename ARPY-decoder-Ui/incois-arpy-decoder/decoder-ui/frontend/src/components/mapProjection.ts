/**
 * Pure, testable world/projection/view math for the fleet map.
 *
 * The map renders a constant 360×180 WORLD space in *degree units*
 * (x = lon + 180, y = 90 − lat). Two stacked transforms produce screen
 * coordinates:
 *
 *   1. `base`  — data-INDEPENDENT placement of the world inside the
 *      map viewport: uniform scale + offset. CONTAIN for the normal
 *      framed view, COVER for the full-surface (fill) view so the
 *      satellite imagery reaches every edge with no letterbox.
 *   2. `view`  — user pan/zoom `{ tx, ty, k }`, in base screen units:
 *      screen = (world * baseScale + baseOffset) * k + (tx, ty)
 *
 * Keeping the base independent of the decoded data is what fixes the
 * "empty map until every run finished hydrating" problem and removes
 * every refit/rescale jump when positions arrive or the container
 * resizes.
 */

export interface BaseTransform {
  /** px (screen, pre-view) per degree of world space */
  scale: number;
  /** offset so the world is centred (contain) / filling (cover) */
  ox: number;
  oy: number;
}

export interface ViewState {
  tx: number;
  ty: number;
  k: number;
}

export interface LonLat {
  lon: number;
  lat: number;
}

export const WORLD_W = 360; // degrees of longitude
export const WORLD_H = 180; // degrees of latitude

export const MIN_K_NORMAL = 0.5;
export const MAX_K = 14;

export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/** Longitude/latitude → the constant world space (degrees). */
export function worldX(lon: number): number {
  return lon + 180;
}
export function worldY(lat: number): number {
  return 90 - lat;
}
export function lonFromWorldX(x: number): number {
  return x - 180;
}
export function latFromWorldY(y: number): number {
  return 90 - y;
}

/**
 * Compute the data-independent base placement of the world in a
 * viewport of `w`×`h` px.
 *  - Normal (fill=false): the whole 360×180 world is CONTAINED inside
 *    the plot area (viewport minus `pad`), letterboxing over the dark
 *    ocean background. This preserves the classic framed composition.
 *  - Fill (cover): the world COVERS the entire viewport — imagery
 *    touches every edge. The smallest uniform scale that fills both
 *    dimensions is used, and the overflow is centred.
 */
export function computeBase(
  w: number,
  h: number,
  fill: boolean,
  pad: number
): BaseTransform {
  if (w <= 0 || h <= 0) return { scale: 1, ox: 0, oy: 0 };
  if (fill) {
    const s = Math.max(w / WORLD_W, h / WORLD_H);
    return { scale: s, ox: (w - WORLD_W * s) / 2, oy: (h - WORLD_H * s) / 2 };
  }
  const aw = Math.max(8, w - 2 * pad);
  const ah = Math.max(8, h - 2 * pad);
  const s = Math.min(aw / WORLD_W, ah / WORLD_H);
  return { scale: s, ox: (w - WORLD_W * s) / 2, oy: (h - WORLD_H * s) / 2 };
}

/** World → base screen coordinates (before the user view transform). */
export function toBase(pt: LonLat, base: BaseTransform): { x: number; y: number } {
  return { x: worldX(pt.lon) * base.scale + base.ox, y: worldY(pt.lat) * base.scale + base.oy };
}

/** World → final screen coordinates (base + view). */
export function toScreen(
  pt: LonLat,
  base: BaseTransform,
  view: ViewState
): { x: number; y: number } {
  const b = toBase(pt, base);
  return { x: b.x * view.k + view.tx, y: b.y * view.k + view.ty };
}

/** Screen pixel (x,y) → lon/lat. Inverse of toScreen. */
export function fromScreen(
  x: number,
  y: number,
  base: BaseTransform,
  view: ViewState
): LonLat {
  const bx = (x - view.tx) / view.k;
  const by = (y - view.ty) / view.k;
  return {
    lon: lonFromWorldX((bx - base.ox) / base.scale),
    lat: latFromWorldY((by - base.oy) / base.scale),
  };
}

/**
 * Zoom around an anchor point (screen px). The anchor stays fixed:
 * k' = clamp(k*factor); offsets follow (a - (a - t) * k'/k).
 */
export function zoomAt(
  view: ViewState,
  factor: number,
  ax: number,
  ay: number,
  minK: number,
  maxK: number
): ViewState {
  const k = clamp(view.k * factor, minK, maxK);
  const ratio = k / view.k;
  return {
    k,
    tx: ax - (ax - view.tx) * ratio,
    ty: ay - (ay - view.ty) * ratio,
  };
}

/**
 * Pan by a screen delta.
 */
export function panBy(view: ViewState, dx: number, dy: number): ViewState {
  return { k: view.k, tx: view.tx + dx, ty: view.ty + dy };
}

/**
 * Constrain the view so the map never ends up in a meaningless place.
 *  - fill: imagery must always COVER the surface — the world's screen
 *    rect is at least viewport-sized and cannot be dragged past an
 *    edge (at k = 1 the only legal view is tx = ty = 0).
 *  - normal: the world may be panned freely but at least `edgePx` of it
 *    always stays inside the viewport (no "lost the earth" states).
 */
export function clampView(
  view: ViewState,
  base: BaseTransform,
  w: number,
  h: number,
  fill: boolean
): ViewState {
  const k = clamp(view.k, fill ? 1 : MIN_K_NORMAL, MAX_K);
  const wx0 = base.ox * k + view.tx;
  const wy0 = base.oy * k + view.ty;
  const wx1 = (base.ox + WORLD_W * base.scale) * k + view.tx;
  const wy1 = (base.oy + WORLD_H * base.scale) * k + view.ty;

  let tx = view.tx;
  let ty = view.ty;
  if (fill) {
    // cover constraint: world rect must cover [0,w]x[0,h]
    if (wx0 > 0) tx -= wx0;
    if (wy0 > 0) ty -= wy0;
    const ex1 = (base.ox + WORLD_W * base.scale) * k + tx;
    const ey1 = (base.oy + WORLD_H * base.scale) * k + ty;
    if (ex1 < w) tx += w - ex1;
    if (ey1 < h) ty += h - ey1;
  } else {
    const edgePx = 40;
    if (wx1 < edgePx) tx += edgePx - wx1;
    if (wy1 < edgePx) ty += edgePx - wy1;
    if (wx0 > w - edgePx) tx -= wx0 - (w - edgePx);
    if (wy0 > h - edgePx) ty -= wy0 - (h - edgePx);
  }
  return { tx, ty, k };
}

/** The world-space centre currently visible on screen. */
export function viewCenterWorld(
  view: ViewState,
  base: BaseTransform,
  w: number,
  h: number
): { wx: number; wy: number } {
  return {
    wx: ((w / 2 - view.tx) / view.k - base.ox) / base.scale,
    wy: ((h / 2 - view.ty) / view.k - base.oy) / base.scale,
  };
}

/** Build the view state that centres `c` (world units) at zoom k. */
export function viewForCenter(
  c: { wx: number; wy: number },
  k: number,
  base: BaseTransform,
  w: number,
  h: number
): ViewState {
  return {
    k,
    tx: w / 2 - (c.wx * base.scale + base.ox) * k,
    ty: h / 2 - (c.wy * base.scale + base.oy) * k,
  };
}

/**
 * The view that frames a set of real points (float markers, trajectory)
 * with `padFrac` breathing room, never zooming beyond [minK, maxK] and
 * keeping tiny clusters inspectable via `minSpanDeg`.
 */
export function fitViewFor(
  pts: LonLat[],
  base: BaseTransform,
  w: number,
  h: number,
  padFrac: number,
  minSpanDeg: number,
  minK: number,
  maxK: number
): ViewState {
  if (pts.length === 0) {
    // frame the whole world
    return viewForCenter({ wx: WORLD_W / 2, wy: WORLD_H / 2 }, minK, base, w, h);
  }
  if (pts.length === 1) {
    const c = { wx: worldX(pts[0].lon), wy: worldY(pts[0].lat) };
    return viewForCenter(c, clamp(2.2, minK, maxK), base, w, h);
  }
  const xs = pts.map((p) => worldX(p.lon));
  const ys = pts.map((p) => worldY(p.lat));
  let spanX = Math.max(...xs) - Math.min(...xs);
  let spanY = Math.max(...ys) - Math.min(...ys);
  spanX = Math.max(spanX, minSpanDeg);
  spanY = Math.max(spanY, minSpanDeg);
  // expand symmetrically to the viewport aspect so the fit is exact.
  const aspect = w / Math.max(1, h);
  if (spanX / spanY < aspect) spanX = spanY * aspect;
  else spanY = spanX / aspect;
  // k so the (padded) span fits the viewport on both axes
  const kFitW = w / (spanX * base.scale);
  const kFitH = h / (spanY * base.scale);
  const k = clamp(Math.min(kFitW, kFitH) / (1 + padFrac), minK, maxK);
  const c = {
    wx: (Math.min(...xs) + Math.max(...xs)) / 2,
    wy: (Math.min(...ys) + Math.max(...ys)) / 2,
  };
  return viewForCenter(c, k, base, w, h);
}

/** The neutral view: whole world framed per the base (k = 1, centred window). */
export function neutralView(base: BaseTransform, w: number, h: number): ViewState {
  return viewForCenter({ wx: WORLD_W / 2, wy: WORLD_H / 2 }, 1, base, w, h);
}

/** Chose image-space placement (world units) for the georeferenced raster. */
export const BASEMAP_GEOMETRY = {
  x: 0, // lon -180
  y: 0, // lat +90
  w: WORLD_W,
  h: WORLD_H,
} as const;
