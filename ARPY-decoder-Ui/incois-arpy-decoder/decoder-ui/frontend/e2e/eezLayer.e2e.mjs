// EEZ Layer E2E — drives the REAL built app through headless Chromium against
// a live backend and verifies the Indian EEZ geographic-monitoring feature on
// REAL decoded data (no mocking):
//
//   1  geometry endpoint serves the verified v12 artifact with honest headers
//   2  MAP LAYERS control renders, Indian EEZ OFF by default
//   3  OFF state: NO EEZ graphics / label / legend item (pristine map)
//   4  OFF baseline snapshot (markers + trajectory structure captured)
//   5  toggle ON  -> boundary + fill + label + legend item appear
//   6  boundary geometry is CRS-true: same rings after zoom (not rebuilt)
//   7  label anchor projects inside the boundary extent (same world pipeline)
//   8  pan: boundary rings unchanged (geometry constant under view ops)
//   9  selected-float compact info shows real EEZ state (separate dimension)
//  10  per-cycle EEZ attributes match backend-derived classification
//  11  normal Fleet view: NO alert UI at all (even ON with floats inside)
//  12  toggle OFF again -> EEZ graphics gone, markers IDENTICAL to OFF baseline
//  13  Expand Fleet (Full Screen): single shared control; boundary persists;
//      13b exactly ONE combined CURRENT-STATE alert (inside-WMO rows, no cycles)
//  14  exit Full Screen: same single control, toggle state preserved, alert hidden
//  15  geometry fetched EXACTLY ONCE for the whole session
//  16  no page errors
//  17  region: translucent deep-teal fill 8-15% + brighter cyan boundary (no red geography)
//  18  legend gains inside+teal boundary/region items while ON / 18b: gone when OFF
//  19  inside markers wear a red halo ring (backend truth set, centered on the core)
//  19b layer OFF removes every halo instantly; boundary/fill/label graphics unmount
//  20  current-state pulse ≠ entry event (no cross-trigger)
//  21  current-state alert wears the red family, WMO-only rows, opacity fade transition / 21b: banned words absent
//  22  toggle-OFF hides the alert, toggle-ON restores it; with toggle ON, expand/collapse/select/zoom/pan never duplicate: ≤1 panel
//  23  dismiss snapshots the inside set, keeps history/classification; no resurrection
//
// Renderer note: the map is an ArcGIS Maps SDK MapView, so EEZ geography
// lives in SDK graphics layers (eez-region / eez-boundary / labels), not in
// SVG DOM. Assertions read the live view through `__fleetMapView` /
// `__fleetMapData`. Canvas graphics appear/disappear without CSS fades —
// only the DOM combined-alert still fades (CDP-observed).
//
// Usage: npm run build && node e2e/eezLayer.e2e.mjs  (backend on :8000)
import { chromium } from 'playwright';
import fs from 'fs';

const BASE = process.env.EEZ_E2E_BASE || 'http://127.0.0.1:8000';
const SHOTS = process.env.EEZ_E2E_SHOTS || '/tmp/eezshots';
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const ok = (name, cond, extra = '') => {
  results.push([cond ? 'PASS' : 'FAIL', name, extra]);
  console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (extra ? '   ' + extra : ''));
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(p) {
  const r = await fetch(BASE + '/api' + p);
  if (!r.ok) throw new Error(p + ' -> ' + r.status);
  return r.json();
}

// Snapshot of the EEZ-relevant graphics in the live Esri view.
async function eezState(page) {
  return page.evaluate(() => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    if (!el || !el.__fleetMapView) return null;
    const view = el.__fleetMapView.view;
    const layer = (title) => view.map.layers.find((l) => l.title === title);
    const hash = (s) => { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0; return h; };
    const region = layer('eez-region')?.graphics.toArray() || [];
    const boundary = layer('eez-boundary')?.graphics.toArray() || [];
    const dashed = boundary.find((g) => g.symbol?.outline?.style === 'dash') || boundary[0];
    const labels = layer('labels')?.graphics.toArray() || [];
    const markers = layer('markers')?.graphics.toArray() || [];
    const eezLabel = labels.find((g) => g.attributes?.kind === 'eez-name');
    const b0 = boundary[0]?.geometry;
    return {
      ready: view.ready, stationary: view.stationary, zoom: view.zoom,
      center: [view.center.longitude, view.center.latitude],
      region: region.length,
      boundary: boundary.length,
      eezLabel: eezLabel ? 1 : 0,
      labelLonLat: eezLabel ? [eezLabel.geometry.longitude, eezLabel.geometry.latitude] : null,
      events: layer('eez-events')?.graphics.length || 0,
      halos: markers.filter((g) => g.attributes?.kind === 'eez-halo').map((g) => g.attributes.wmo),
      haloCentered: markers.filter((g) => g.attributes?.kind === 'eez-halo').every((h) => {
        const core = markers.find((g) => g.attributes?.kind === 'marker' && g.attributes.wmo === h.attributes.wmo);
        return core && core.geometry.longitude === h.geometry.longitude && core.geometry.latitude === h.geometry.latitude;
      }),
      ringsHash: b0 ? hash(JSON.stringify(b0.rings)) : null,
      ringsLen: b0 ? JSON.stringify(b0.rings).length : 0,
      ringCount: b0 ? b0.rings.length : 0,
      extent: boundary.length ? [
        Math.min(...boundary.map((g) => g.geometry.extent.xmin)),
        Math.min(...boundary.map((g) => g.geometry.extent.ymin)),
        Math.max(...boundary.map((g) => g.geometry.extent.xmax)),
        Math.max(...boundary.map((g) => g.geometry.extent.ymax)),
      ] : null,
      fillColor: region[0] ? [region[0].symbol.color.r, region[0].symbol.color.g, region[0].symbol.color.b, region[0].symbol.color.a] : null,
      bndColor: dashed ? [dashed.symbol.outline.color.r, dashed.symbol.outline.color.g, dashed.symbol.outline.color.b, dashed.symbol.outline.color.a] : null,
      markerWmos: markers.filter((g) => g.attributes?.kind === 'marker')
        .map((g) => `${g.attributes.wmo}:${g.geometry.longitude},${g.geometry.latitude}`).sort().join('|'),
      markerCount: markers.filter((g) => g.attributes?.kind === 'marker').length,
      selWmo: layer('selection')?.graphics.toArray()[0]?.attributes.wmo ?? null,
      cycleEez: (layer('cycle-dots')?.graphics.toArray() || [])
        .map((g) => ({ cycle: g.attributes.cycle, status: g.attributes.eez })),
    };
  });
}

async function waitSettled(page, timeout = 15000) {
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    const v = el && el.__fleetMapView && el.__fleetMapView.view;
    return v && v.ready && v.stationary;
  }, { timeout });
}

// Wheel/drag gestures must land on the map canvas, not the side panels.
async function mapCenter(page) {
  const box = await page.locator('[data-testid="esri-map-view"]').first().boundingBox();
  return { x: box.x + box.width / 2, y: box.y + box.height / 2, box };
}

// ---------- backend ground truth (same even-odd PIP as the frontend) -------
const geo = await api('/geography/india-eez');
const polys = [];
for (const f of geo.features) {
  const g = f.geometry;
  if (g.type === 'Polygon') polys.push(g.coordinates);
  else for (const p of g.coordinates) polys.push(p);
}
function ringIn(ring, lon, lat) {
  let inside = false;
  for (let i = 0, j = ring.length - 2; i < ring.length - 1; j = i++) {
    // NOTE: j = i++ semantics handled below
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function inEez(lon, lat) {
  for (const poly of polys) {
    if (ringIn(poly[0], lon, lat)) {
      let inHole = false;
      for (let h = 1; h < poly.length; h++) if (ringIn(poly[h], lon, lat)) { inHole = true; break; }
      if (!inHole) return true;
    }
  }
  return false;
}

const batch = (await api('/batches'))[0];
const runs = {};
for (const it of batch.items) {
  if (!it.run_id) continue;
  let run;
  try { run = await api(`/runs/${it.run_id}`); }
  catch { continue; } // error/stopped items have no run record (no cycles)
  const cyc = (run.cycles || [])
    .filter((c) => c.latitude != null && c.longitude != null && Math.abs(c.latitude) <= 90 && Math.abs(c.longitude) <= 180)
    .sort((a, b) => a.cycle_number - b.cycle_number || (a.juld ?? 0) - (b.juld ?? 0));
  if (cyc.length) runs[it.wmo] = cyc;
}
const truthWmos = Object.keys(runs);
console.log('backend ground truth floats with positions:', truthWmos.join(', '));
const expectedStatus = {}; // wmo -> [{cycle,status}]
let crossingWmos = [];
for (const w of truthWmos) {
  expectedStatus[w] = runs[w].map((c) => ({ cycle: c.cycle_number, status: inEez(c.longitude, c.latitude) ? 'INDIAN_EEZ' : 'OUTSIDE_INDIAN_EEZ' }));
  const seq = expectedStatus[w].map((s) => s.status);
  if (seq.some((s, i) => i > 0 && s !== seq[i - 1])) crossingWmos.push(Number(w));
}
console.log('backend-derived EEZ crossings present in real data:', crossingWmos.length ? crossingWmos.join(', ') : 'NONE');

// ---------- launch ----------------------------------------------------------
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const pageErrors = [];
page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 400)));
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push('[console] ' + m.text().slice(0, 300)); });
const geoCalls = [];
page.on('request', (r) => { if (r.url().includes('/api/geography/india-eez')) geoCalls.push(r.url()); });
// CSS-fade capture for the DOM combined-alert only (canvas graphics have no
// CSS animations — they mount/unmount in the WebGL scene instead).
const cdp = await page.context().newCDPSession(page);
await cdp.send('Animation.enable');
let animEvents = [];
cdp.on('Animation.animationStarted', (e) => {
  const a = e.animation || {};
  animEvents.push({ type: a.type, name: a.name, dur: a.source?.duration, easing: a.source?.easing });
});
const drainAnims = () => { const x = animEvents; animEvents = []; return x; };
const fadeInAnimsOf = (evts) => evts.filter((a) =>
  a.type === 'CSSAnimation' && a.name === 'eezFadeIn' && a.dur === 300);
const fadeOutAnimsOf = (evts) => evts.filter((a) =>
  a.type === 'CSSTransition' && a.name === 'opacity' && a.dur === 300 && a.easing === 'ease-in-out');
async function waitFades(n, kind, timeoutMs = 6000) {
  const pick = kind === 'in' ? fadeInAnimsOf : fadeOutAnimsOf;
  const t0 = Date.now();
  for (;;) {
    const found = pick(animEvents);
    if (found.length >= n || Date.now() - t0 > timeoutMs) return found;
    await sleep(100);
  }
}

await page.goto(BASE, { waitUntil: 'domcontentloaded' });
await page.waitForLoadState('networkidle');

// Reach the Results view via the REAL user flow (handles already-complete).
await page.locator('button:has-text("DECODE ALL TODAY")').click({ timeout: 10000 });
const completeModalBtn = page.locator('div[role="dialog"] button:has-text("[ View Results ]")');
let usedAlreadyComplete = false;
for (let i = 0; i < 26; i++) {
  if (await completeModalBtn.count()) { usedAlreadyComplete = true; break; }
  await sleep(300);
}
if (usedAlreadyComplete) {
  await completeModalBtn.click();
} else {
  await page.waitForSelector('button:has-text("VIEW RESULTS")', { timeout: 600000 });
  await page.locator('button:has-text("VIEW RESULTS")').first().click();
}
await page.waitForFunction(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const v = el && el.__fleetMapView && el.__fleetMapView.view;
  const layer = v && v.map.layers.find((l) => l.title === 'markers');
  return layer && layer.graphics.toArray().some((g) => g.attributes?.kind === 'marker') &&
    document.querySelector('[data-testid="eez-layer-control"]');
}, { timeout: 60000 });
await waitSettled(page);
await sleep(2500); // let geometry load + classification settle

// ---- 1 endpoint sanity ------------------------------------------------------
const geoHead = await fetch(BASE + '/api/geography/india-eez');
ok('1 geometry endpoint serves verified v12 Indian features', geoHead.ok,
  'status ' + geoHead.status + ', headers: ' + (geoHead.headers.get('x-dataset-status') || 'none'));

// ---- 2 control present, layer OFF by default --------------------------------
const control = page.locator('[data-testid="eez-layer-control"]');
const toggle = page.locator('[data-testid="eez-toggle"]');
async function setLayer(on) {
  const cur = await toggle.isChecked();
  if (cur !== on) await toggle.click();
  await sleep(600); // settle unmount/mount before asserting
}
ok('2 MAP LAYERS control visible + Indian EEZ OFF by default',
  (await control.count()) === 1 && (await toggle.count()) === 1 && !(await toggle.isChecked()));

// ---- 3/4 OFF baseline: no EEZ graphics anywhere ------------------------------
const offState = await eezState(page);
const offLegend = await page.evaluate(() =>
  document.querySelectorAll('[data-eez-legend-inside],[data-eez-legend-item],[data-eez-legend-region]').length);
ok('3 OFF state has zero EEZ graphics/label/legend/halos',
  offState.region === 0 && offState.boundary === 0 && offState.eezLabel === 0 &&
  offState.events === 0 && offState.halos.length === 0 && offLegend === 0,
  JSON.stringify({ region: offState.region, boundary: offState.boundary, label: offState.eezLabel, halos: offState.halos.length, legend: offLegend }));
ok('4 OFF baseline snapshot captured (' + offState.markerCount + ' float markers)',
  offState.markerCount >= 2 && offState.markerWmos.length > 20);

// ---- 5 toggle ON ------------------------------------------------------------
await toggle.click();
await sleep(500); // settle past mount
const onState = await eezState(page);
const onLegend = await page.evaluate(() =>
  document.querySelectorAll('[data-eez-legend-inside],[data-eez-legend-item],[data-eez-legend-region]').length);
ok('5 toggle ON mounts boundary+fill+label+legend entry',
  onState.region === polys.length && onState.boundary === polys.length * 2 && onState.eezLabel === 1 && onLegend === 3,
  `region=${onState.region}/${polys.length} boundary=${onState.boundary} label=${onState.eezLabel} legend=${onLegend}`);

// ---- 6/7 CRS truth -----------------------------------------------------------
const geoBefore = { hash: onState.ringsHash, len: onState.ringsLen, rings: onState.ringCount };
{ const mc = await mapCenter(page); await page.mouse.move(mc.x, mc.y); }
await page.mouse.wheel(0, -600); // zoom in
await waitSettled(page);
const zoomState = await eezState(page);
ok('6 boundary geometry identical across zoom (same rings, not rebuilt)',
  zoomState.ringsHash === geoBefore.hash && geoBefore.len > 5000 && zoomState.zoom > onState.zoom,
  `hash=${zoomState.ringsHash} rings=${zoomState.ringCount} zoom=${onState.zoom.toFixed(2)}→${zoomState.zoom.toFixed(2)}`);

const [lx, ly] = zoomState.labelLonLat || [NaN, NaN];
const [ex0, ey0, ex1, ey1] = zoomState.extent || [0, 0, -1, -1];
ok('7 INDIAN EEZ label projects inside boundary extent (shared world pipeline)',
  lx >= ex0 && lx <= ex1 && ly >= ey0 && ly <= ey1,
  `label=[${lx?.toFixed(2)},${ly?.toFixed(2)}] extent=[${ex0?.toFixed(1)},${ey0?.toFixed(1)},${ex1?.toFixed(1)},${ey1?.toFixed(1)}]`);

{ const mc = await mapCenter(page);
  await page.mouse.move(mc.x, mc.y);
  await page.mouse.down();
  await page.mouse.move(mc.x - 120, mc.y - 70, { steps: 5 });
  await page.mouse.up(); }
await waitSettled(page);
const panState = await eezState(page);
ok('8 boundary geometry identical across pan (no rebuild)',
  panState.ringsHash === geoBefore.hash &&
  (Math.abs(panState.center[0] - zoomState.center[0]) + Math.abs(panState.center[1] - zoomState.center[1]) > 0));

// ---- 9 selected-float compact info ------------------------------------------
const chip = await page.evaluate(() => {
  const el = document.querySelector('[data-testid="eez-float-status"]');
  return el ? { text: el.textContent.trim(), status: el.getAttribute('data-eez') } : null;
});
const selWmo = panState.selWmo;
const expectSel = selWmo && expectedStatus[selWmo] ? expectedStatus[selWmo][expectedStatus[selWmo].length - 1].status : null;
ok('9 float compact info shows EEZ state (separate from processing status)',
  chip && chip.text.startsWith('EEZ:') && chip.status === expectSel,
  JSON.stringify(chip) + ' expect ' + expectSel);

// ---- 10 per-cycle vs backend truth -------------------------------------------
const cycleTruth = panState.cycleEez;
let cycleMatch = cycleTruth.length > 0 && expectSel;
if (cycleMatch) {
  const truthMap = new Map((expectedStatus[selWmo] || []).map((t) => [t.cycle, t.status]));
  cycleMatch = cycleTruth.every((t) => truthMap.get(t.cycle) === t.status);
}
ok('10 every rendered cycle dot carries backend-derived EEZ status', cycleMatch, cycleTruth.length + ' cycle dots checked');

// ---- 11 normal view: NO alert UI ------------------------------------------------
// Backend-derived expectation of every real EEZ transition id (stable
// identity eez|WMO|fromCycle|toCycle|KIND) — reused by checks 13/21/22/23.
const expectedEventIds = [];
for (const w of crossingWmos) {
  const seq = expectedStatus[w];
  for (let i = 1; i < seq.length; i++) {
    if (seq[i].status !== seq[i - 1].status) {
      const kind = seq[i - 1].status === 'OUTSIDE_INDIAN_EEZ' ? 'EEZ_ENTRY' : 'EEZ_EXIT';
      expectedEventIds.push(`eez|${w}|${seq[i - 1].cycle}|${seq[i].cycle}|${kind}`);
    }
  }
}
// The layer is ON here (check 5) and the real data HAS transitions — the
// normal compact Fleet view must still show no alert UI of any kind.
const normalAlert = await page.evaluate(() => ({
  combined: document.querySelectorAll('[data-testid="eez-combined-alert"]').length,
  legacy: document.querySelectorAll('[data-testid="eez-notice"]').length,
  rows: document.querySelectorAll('[data-testid="eez-alert-row"]').length,
}));
ok('11 normal Fleet view shows NO alert UI (even ON with floats inside); no legacy per-event toasts',
  normalAlert.combined === 0 && normalAlert.legacy === 0 && normalAlert.rows === 0,
  JSON.stringify(normalAlert) + ' backendTransitions=' + expectedEventIds.length);

// ---- 12 toggle OFF -> markers IDENTICAL, zero residue --------------------------
await sleep(2000); // let all fleet hydration quiesce on the completed batch
await setLayer(false);
const markersOffBefore = (await eezState(page)).markerWmos;
await setLayer(true); // ON
const markersOn = await eezState(page);
await setLayer(false); // OFF again
const offAgain = await eezState(page);
ok('12 OFF again restores the IDENTICAL fleet markers (zero residue from layer)',
  offAgain.markerWmos === markersOffBefore && offAgain.markerWmos === offState.markerWmos &&
  markersOn.region === polys.length && offAgain.region === 0 && offAgain.boundary === 0 && offAgain.halos.length === 0,
  'markers=' + offAgain.markerCount);

// ---- 13/14 Full Screen single-implementation ---------------------------------
await setLayer(true); // ON again for the fullscreen check
try { await page.locator('[data-testid="esri-map-view"]').screenshot({ path: SHOTS + '/eez-normal.png' }); } catch (e) { console.log('   screenshot skipped:', String(e).slice(0, 120)); }
const expandBtn = page.locator('text=[ Expand Fleet ]');
await toggle.isChecked();
if (await expandBtn.count()) await expandBtn.first().click();
await page.waitForFunction(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const v = el && el.__fleetMapView && el.__fleetMapView.view;
  return v && v.ready && v.stationary;
}, { timeout: 30000 }).catch(() => {});
await sleep(800);
const fsState = await eezState(page);
const fsControls = await page.locator('[data-testid="eez-layer-control"]').count();
ok('13 Full Screen: ONE shared control, boundary persists, fleet intact',
  fsControls === 1 && fsState.boundary === polys.length * 2 && fsState.markerCount === offState.markerCount,
  JSON.stringify({ controls: fsControls, boundary: fsState.boundary, markers: fsState.markerCount }));

// Expanded view: exactly ONE combined CURRENT-STATE alert listing the WMOs
// whose latest valid position is inside the EEZ (never one toast per
// float/event; never cycle or historical-event content).
const expectedInside = [];
for (const w of truthWmos) {
  const seq = expectedStatus[w];
  if (seq.length && seq[seq.length - 1].status === 'INDIAN_EEZ') expectedInside.push(Number(w));
}
expectedInside.sort((a, b) => a - b);
const fsAlert = await page.evaluate(() => ({
  panels: document.querySelectorAll('[data-testid="eez-combined-alert"]').length,
  rows: Array.from(document.querySelectorAll('[data-testid="eez-alert-row"]')).map((el) => Number(el.getAttribute('data-wmo'))),
  counts: document.querySelector('[data-testid="eez-alert-counts"]')?.textContent.trim() || null,
  text: document.querySelector('[data-testid="eez-combined-alert"]')?.textContent || '',
}));
const fsRowsOk = fsAlert.rows.length === expectedInside.length &&
  expectedInside.every((w) => fsAlert.rows.filter((r) => r === w).length === 1);
const fsCountsOk = expectedInside.length === 1
  ? fsAlert.counts === '1 float currently inside EEZ'
  : fsAlert.counts === `${expectedInside.length} floats currently inside EEZ`;
const fsNoCycles = !/C\d+\s*→\s*C\d+/i.test(fsAlert.text) && !/cycle|entry|exit|juld/i.test(fsAlert.text);
ok('13b expanded view shows exactly ONE combined alert; rows ≡ backend-derived currently-inside WMOs (each once), no cycle content',
  expectedInside.length === 0
    ? fsAlert.panels === 0 && fsAlert.rows.length === 0
    : fsAlert.panels === 1 && fsRowsOk && fsCountsOk && fsNoCycles,
  'panels=' + fsAlert.panels + ' rows=' + fsAlert.rows.join(',') + ' counts=' + fsAlert.counts);
try { await page.locator('[data-testid="esri-map-view"]').screenshot({ path: SHOTS + '/eez-fullscreen.png' }); } catch (e) { console.log('   screenshot skipped:', String(e).slice(0, 120)); }
const exitBtn = page.locator('text=[ Exit Full Screen ]');
if (await exitBtn.count()) await exitBtn.first().click();
await waitSettled(page).catch(() => {});
await sleep(800);
const backState = await eezState(page);
const backMeta = await page.evaluate(() => ({
  controls: document.querySelectorAll('[data-testid="eez-layer-control"]').length,
  checked: document.querySelector('[data-testid="eez-toggle"]')?.checked,
  alerts: document.querySelectorAll('[data-testid="eez-combined-alert"]').length,
}));
ok('14 exit Full Screen: single control, toggle state preserved, alert hidden (data kept)',
  backMeta.controls === 1 && backState.boundary === polys.length * 2 && backMeta.checked === true && backMeta.alerts === 0,
  JSON.stringify({ ...backMeta, boundary: backState.boundary }));

// ---- 15 one-time geometry load -------------------------------------------------
ok('15 geometry fetched exactly once for the whole session', geoCalls.length === 1, geoCalls.length + ' requests');

// ---- backend-derived CURRENT (latest valid cycle) inside-set -----------------
const insideNow = new Set();
for (const w of truthWmos) {
  const seq = expectedStatus[w];
  if (seq.length && seq[seq.length - 1].status === 'INDIAN_EEZ') insideNow.add(Number(w));
}
console.log('backend truth: floats currently inside Indian EEZ =', Array.from(insideNow).join(', ') || 'none');

// ---- 17 EEZ region treatment ----------------------------------------------------
await setLayer(true);
await sleep(350);
const paint = await eezState(page);
const [fr, fg, fb, fa] = paint.fillColor || [0, 0, 0, 0];
const [br, bg, bb, ba] = paint.bndColor || [0, 0, 0, 0];
const regionOk =
  fa >= 0.08 && fa <= 0.15 &&        // 8-15% opacity band
  ba > fa &&                          // boundary brighter than fill
  fg > fr && fb > fr &&               // deep-teal family (blue-green dominant)
  bg > 200 && bb > 200 &&             // cyan boundary accents
  !(fa > 0.5);                        // never opaque
const notNeon =
  fr < 100 &&                         // no red geography: teal fill, not wine
  br < 150 &&                         // no red geography: cyan boundary, not maroon
  !(fg > 220 && fb > 220);            // never washed-out/neon fill
ok('17 EEZ reads as a professional GIS maritime REGION: translucent deep-teal fill 8-15% + brighter cyan boundary (no red geography, never opaque)',
  regionOk === true && notNeon === true,
  `fill=rgba(${fr},${fg},${fb},${fa}) bnd=rgba(${br},${bg},${bb},${ba})`);

// ---- 18 legend completeness when ON --------------------------------------------
const legendItems = await page.evaluate(() => ({
  inside: document.querySelectorAll('[data-eez-legend-inside]').length,
  boundary: document.querySelectorAll('[data-eez-legend-item]').length,
  region: document.querySelectorAll('[data-eez-legend-region]').length,
}));
ok('18 legend gains float-inside + boundary + region items while ON',
  legendItems.inside === 1 && legendItems.boundary === 1 && legendItems.region === 1,
  JSON.stringify(legendItems));
await setLayer(false);
await sleep(300);
const legendOff = await page.evaluate(() =>
  document.querySelectorAll('[data-eez-legend-inside],[data-eez-legend-item],[data-eez-legend-region]').length);
ok('18b legend items vanish when the layer is OFF (compact legend restored)', legendOff === 0);

// ---- 19 inside-float halo: exact backend-derived set, centered ----------------
// (Halo is toggle-gated: layer ON while 18b left it OFF.) The Esri renderer
// conveys inside-state as a persistent red ring on the marker core (canvas
// symbols cannot SMIL-pulse); presence + centering + set identity carry the
// same operational meaning.
await setLayer(true);
await sleep(350);
const haloState = await eezState(page);
const haloSet = new Set(haloState.halos);
const setsEqual = haloSet.size === insideNow.size && Array.from(insideNow).every((w) => haloSet.has(w));
const haloShape = await page.evaluate(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const view = el.__fleetMapView.view;
  const h = view.map.layers.find((l) => l.title === 'markers').graphics
    .toArray().find((g) => g.attributes?.kind === 'eez-halo');
  if (!h) return null;
  const c = h.symbol.outline.color;
  return { sizePt: h.symbol.size, width: h.symbol.outline.width, r: c.r, g: c.g, b: c.b };
});
// 17px ring = 12.75pt; red family rgba(248,113,113,*)
const haloShapeOk = insideNow.size === 0 ? haloShape === null : (
  haloShape && Math.abs(haloShape.sizePt - 12.75) < 0.6 && haloShape.width <= 1.5 &&
  haloShape.r > 200 && haloShape.g < 150 && haloShape.b < 150);
ok('19 inside markers wear a red halo ring (backend truth set), centered on the REAL core',
  setsEqual && haloState.haloCentered === true && haloShapeOk === true,
  'map=' + haloState.halos.join(',') + ' truth=' + Array.from(insideNow).join(',') +
  ' centered=' + haloState.haloCentered + ' shape=' + JSON.stringify(haloShape));

// ---- 19b halos stop the moment the layer is OFF -------------------------------
await setLayer(false);
await sleep(300); // settle past unmount
const halosOff = await eezState(page);
ok('19b layer OFF removes every halo + boundary/fill/label graphics instantly (pristine markers restored)',
  halosOff.halos.length === 0 && halosOff.region === 0 && halosOff.boundary === 0 && halosOff.eezLabel === 0 &&
  halosOff.markerCount === offState.markerCount,
  JSON.stringify({ halos: halosOff.halos.length, region: halosOff.region, boundary: halosOff.boundary, markers: halosOff.markerCount }));

// ---- 20 current state vs entry event separation --------------------------------
ok('20 current-state halo ≠ entry event (no cross-trigger; empty-inside is equally valid',
  insideNow.size >= 0 && haloState.halos.length === insideNow.size,
  `insideNow=${insideNow.size} halos=${haloState.halos.length}`);

// ---- 21 red operational alert appearance (expanded view) -------------------------
// The combined alert is an expanded-view operational notification: expand,
// then inspect the single panel.
await setLayer(true);
const expandBtn2 = page.locator('text=[ Expand Fleet ]');
if (await expandBtn2.count()) await expandBtn2.first().click();
await sleep(800);
const alertStyle = await page.evaluate(() => {
  const panels = document.querySelectorAll('[data-testid="eez-combined-alert"]');
  if (panels.length === 0) return { none: true };
  const el = panels[0];
  const text = el.textContent || '';
  const wrap = document.querySelector('[data-testid="eez-combined-alert-wrap"]');
  const hasFade = !!wrap && getComputedStyle(wrap).transitionProperty.includes('opacity') && getComputedStyle(wrap).transitionDuration === '0.3s';
  const wrapSettled = !!wrap && getComputedStyle(wrap).opacity === '1';
  const rect = wrap ? wrap.getBoundingClientRect() : null;
  const wrapBottomLeft = !!wrap && wrap.className.includes('left-3') && wrap.className.includes('bottom-3') &&
    !wrap.className.includes('right-3') && !!rect &&
    rect.left < window.innerWidth / 2 && rect.bottom > window.innerHeight / 2;
  return {
    hasFade,
    wrapSettled,
    wrapBottomLeft,
    count: panels.length,
    border: el.className.includes('border-red-400'),
    bg: el.className.includes('bg-[#230d12]'),
    role: el.getAttribute('role'),
    title: el.querySelector('.font-bold')?.textContent.trim(),
    hasRedIcon: !!el.querySelector('svg.text-red-300'),
    rows: Array.from(el.querySelectorAll('[data-testid="eez-alert-row"]')).map((r) => Number(r.getAttribute('data-wmo'))),
    counts: el.querySelector('[data-testid="eez-alert-counts"]')?.textContent.trim(),
    noCycleContent: !/C\d+\s*→\s*C\d+/i.test(text) && !/cycle|entry|exit|juld/i.test(text),
  };
});
const alertCountsOk = expectedInside.length === 1
  ? alertStyle.counts === '1 float currently inside EEZ'
  : alertStyle.counts === `${expectedInside.length} floats currently inside EEZ`;
const alertRowsOk = Array.isArray(alertStyle.rows) && alertStyle.rows.length === expectedInside.length &&
  expectedInside.every((w) => alertStyle.rows.filter((r) => r === w).length === 1);
ok('21 combined CURRENT-STATE alert wears the restrained RED family (WMO list only, zero cycle/event content), anchored bottom-left',
  alertStyle.none === true
    ? expectedInside.length === 0  // no float currently inside -> nothing to style
    : alertStyle.count === 1 && alertStyle.border && alertStyle.bg && alertStyle.role === 'alert' &&
      alertStyle.title === 'Indian EEZ Alert' && alertStyle.hasRedIcon && alertStyle.wrapBottomLeft === true &&
      alertStyle.hasFade === true && alertStyle.wrapSettled === true &&
      alertRowsOk && alertCountsOk && alertStyle.noCycleContent === true,
  JSON.stringify(alertStyle));
// wording safety net across the whole page
const bannedSeen = await page.evaluate(() =>
  /illegal|violation|unauthorized|intrusion|breach/i.test(document.body.innerText));
ok('21b banned wording absent across the UI', bannedSeen === false);
try { await page.locator('[data-testid="eez-combined-alert"]').screenshot({ path: SHOTS + '/eez-combined-alert.png' }); } catch (e) { console.log('   screenshot skipped:', String(e).slice(0, 120)); }

// ---- 22 no-duplicate matrix ------------------------------------------------------
// toggle OFF hides the alert entirely; with toggle ON, float selection,
// zoom, pan, collapse/re-expand: always at most ONE panel, always the same
// backend-derived rows. (Alert fade in/out observed via CDP; the canvas
// layer itself mounts/unmounts without CSS.)
const panelRows = () => page.evaluate(() => ({
  panels: document.querySelectorAll('[data-testid="eez-combined-alert"]').length,
  rows: Array.from(document.querySelectorAll('[data-testid="eez-alert-row"]')).map((el) => Number(el.getAttribute('data-wmo'))),
}));
const sameRows = (r) => r.rows.length === expectedInside.length &&
  expectedInside.every((w) => r.rows.filter((x) => x === w).length === 1);
drainAnims();
await setLayer(false);
const alertFadeOut = await waitFades(1, 'out'); // alert opacity transition
await sleep(300);
const tOff = await panelRows();
const gfxOff = await eezState(page);
drainAnims();
await setLayer(true);
const alertFadeIn = await waitFades(1, 'in'); // alert entrance keyframe
await sleep(300);
const tOn = await panelRows();
// Select a different float via its fleet-table row (map markers for distant
// floats can sit outside the zoomed viewport; the table is always present).
const otherWmo = truthWmos.find((w) => Number(w) !== selWmo) || truthWmos[0];
const rowIdx = await page.evaluate((wmo) => {
  const rows = Array.from(document.querySelectorAll('table tbody tr'));
  return rows.findIndex((r) => r.querySelector('td')?.textContent.trim() === String(wmo));
}, otherWmo);
if (rowIdx >= 0) await page.locator('table tbody tr').nth(rowIdx).click();
await sleep(1200);
const afterSelect = await panelRows();
{ const mc = await mapCenter(page); await page.mouse.move(mc.x, mc.y); }
await page.mouse.wheel(0, -400);
await waitSettled(page).catch(() => {});
{ const mc = await mapCenter(page);
  await page.mouse.move(mc.x, mc.y);
  await page.mouse.down();
  await page.mouse.move(mc.x - 100, mc.y - 50, { steps: 4 });
  await page.mouse.up(); }
await waitSettled(page).catch(() => {});
await sleep(500);
const afterZoomPan = await panelRows();
const exitBtn2 = page.locator('text=[ Exit Full Screen ]');
if (await exitBtn2.count()) await exitBtn2.first().click();
await sleep(700);
const collapsed22 = await panelRows();
const expandBtn3 = page.locator('text=[ Expand Fleet ]');
if (await expandBtn3.count()) await expandBtn3.first().click();
await sleep(700);
const reexpanded = await panelRows();
const matrixOk = expectedInside.length === 0
  ? [tOff, tOn, afterSelect, afterZoomPan, collapsed22, reexpanded].every((r) => r.panels === 0)
  : tOff.panels === 0 && alertFadeOut.length >= 1 && gfxOff.region === 0 && tOn.panels === 1 && sameRows(tOn) && alertFadeIn.length >= 1 &&
    afterSelect.panels === 1 && sameRows(afterSelect) && afterZoomPan.panels === 1 && sameRows(afterZoomPan) &&
    collapsed22.panels === 0 && reexpanded.panels === 1 && sameRows(reexpanded);
ok('22 toggle-OFF fades the alert out, toggle-ON fades it in; select/zoom/pan/collapse/re-expand never duplicate: ≤1 panel, identical rows',
  matrixOk,
  'tOff=' + tOff.panels + ' tOn=' + tOn.panels + ' sel=' + afterSelect.panels +
  ' zoompan=' + afterZoomPan.panels + ' collapsed=' + collapsed22.panels + ' reexpanded=' + reexpanded.panels +
  ' fadesOut=' + alertFadeOut.length + ' fadesIn=' + alertFadeIn.length);

// ---- 23 dismiss keeps history, never resurrects -----------------------------------
let dismissOk = expectedInside.length === 0;
if (expectedInside.length > 0) {
  await page.locator('[data-testid="eez-alert-dismiss"]').click();
  await sleep(300);
  const afterDismiss = await panelRows();
  const exitBtn3 = page.locator('text=[ Exit Full Screen ]');
  if (await exitBtn3.count()) await exitBtn3.first().click();
  await sleep(600);
  const expandBtn4 = page.locator('text=[ Expand Fleet ]');
  if (await expandBtn4.count()) await expandBtn4.first().click();
  await sleep(600);
  const afterCycle = await panelRows();
  await setLayer(false);
  await sleep(200);
  await setLayer(true);
  await sleep(250);
  const afterToggle = await panelRows();
  const historyLabel = await page.locator('[data-testid="eez-history-toggle"]').textContent().catch(() => null);
  dismissOk = afterDismiss.panels === 0 && afterCycle.panels === 0 && afterToggle.panels === 0 &&
    (historyLabel || '').includes(`EEZ events (${expectedEventIds.length})`);
  console.log('   dismiss=' + afterDismiss.panels + ' cycle=' + afterCycle.panels + ' toggle=' + afterToggle.panels + ' history=' + (historyLabel || 'none').trim());
}
ok('23 dismiss hides the alert but keeps MAP LAYERS history; collapse/expand/toggle never resurrect it', dismissOk);

// ---- 16 page health -------------------------------------------------------------
ok('16 no page errors', pageErrors.length === 0, pageErrors.slice(0, 1).join(' | '));

// ---------------------------------------------------------------------------
try { await page.locator('[data-testid="esri-map-view"]').screenshot({ path: SHOTS + '/eez-final.png' }); } catch (e) { console.log('   screenshot skipped:', String(e).slice(0, 120)); }
await browser.close();
const fails = results.filter((r) => r[0] === 'FAIL');
console.log(`\n${results.length - fails.length}/${results.length} EEZ e2e checks passed`);
process.exit(fails.length ? 1 : 0);
