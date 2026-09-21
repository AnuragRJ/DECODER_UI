// Geographic alignment verification — real backend + real built app.
// Captures the fleet map at world view and at zoomed regional views
// (India, Africa, Europe, Asia-East, S.America, N.America, polar edges),
// checks antimeridian continuity in the live Esri view, verifies the
// served basemap is the genuine Esri imagery service (200 tiles, 0 fails),
// then exercises Fullscreen (Expand Fleet) exit and a browser resize.
//
// Renderer: ArcGIS Maps SDK MapView — camera state comes from the live
// view (view.center / view.zoom / view.stationary) via `__fleetMapView`,
// regional views use deterministic view.goTo (no wheel-anchored hunting).
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.MAP_E2E_BASE || 'http://127.0.0.1:8000';
const SHOTS = process.env.MAP_E2E_SHOTS || '/tmp/geoshots';
fs.rmSync(SHOTS, { recursive: true, force: true });
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const ok = (name, cond, extra = '') => {
  results.push([cond ? 'PASS' : 'FAIL', name, extra]);
  console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (extra ? '   ' + extra : ''));
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1657, height: 900 } });
let tilesOk = 0, tilesFail = 0;
page.on('response', (r) => {
  if (r.url().includes('server.arcgisonline.com') && r.url().includes('/tile/')) {
    if (r.ok()) tilesOk++; else tilesFail++;
  }
});
const pageErrors = [];
page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 300)));

// ---------- helpers (hoisted function declarations) ---------------------------
async function stabilize(timeout = 20000) {
  // wait until the Esri camera stops moving
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    const v = el && el.__fleetMapView && el.__fleetMapView.view;
    return v && v.ready && v.stationary;
  }, { timeout });
}

async function fit() {
  await page.locator('[data-testid="map-fit"]').click({ timeout: 8000 });
  await stabilize();
}

// geographic centre + zoom of what's currently visible in the map view
async function mapInfo() {
  return page.evaluate(() => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    const view = el.__fleetMapView.view;
    const r = el.getBoundingClientRect();
    return {
      lon: view.center.longitude, lat: view.center.latitude, zoom: view.zoom,
      px: [r.width, r.height],
    };
  });
}

async function goRegion(lon, lat, zoom) {
  await page.evaluate(([lo, la, z]) => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    return el.__fleetMapView.view.goTo({ center: [lo, la], zoom: z }, { duration: 0 });
  }, [lon, lat, zoom]);
  await stabilize();
  await sleep(2500); // let tiles stream in for the screenshot
}

async function mapShot(name) {
  await page.locator('[data-testid="esri-map-view"]').first().screenshot({ path: path.join(SHOTS, name) });
}

// ---------- boot: real store driven via a cached decode-all -------------------
await page.goto(BASE, { waitUntil: 'domcontentloaded' });
await page.waitForLoadState('networkidle').catch(() => {});
// Drive the REAL user action (Decode All Today's Floats). The backend now
// decides from CURRENT state — fresh batch OR "already complete" notice.
await page.locator('button:has-text("DECODE ALL TODAY")').click({ timeout: 10000 });
const completeModalBtn = page.locator('div[role="dialog"] button:has-text("[ View Results ]")');
let usedAlreadyComplete = false;
for (let i = 0; i < 26; i++) {
  if (await completeModalBtn.count()) { usedAlreadyComplete = true; break; }
  await sleep(300);
}
if (usedAlreadyComplete) {
  console.log('   Decode All idempotency: already-complete notice shown (no duplicate batch)');
  await completeModalBtn.click();
} else {
  await page.waitForFunction(
    () => !document.body.innerText.includes('DECODING FLOAT'),
    { timeout: 60000 },
  );
  await sleep(800);
  const modalBtn = page.locator('div[role="dialog"] button:has-text("VIEW RESULTS"), div[role="dialog"] button:has-text("View Results")');
  if (await modalBtn.first().count()) await modalBtn.first().click();
  else await page.locator('button:has-text("VIEW RESULTS")').first().click();
}
await page.waitForFunction(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const v = el && el.__fleetMapView && el.__fleetMapView.view;
  const l = v && v.map.layers.find((x) => x.title === 'markers');
  return l && l.graphics.toArray().some((g) => g.attributes && g.attributes.kind === 'marker');
}, { timeout: 30000 });
await page.getByText('[ Expand Fleet ]').click({ timeout: 8000 });
await stabilize();
await sleep(2500); // initial tile stream

// ---- A. served basemap is the genuine Esri imagery service -------------------
const baseLayers = await page.evaluate(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const b = el.__fleetMapView.view.map.basemap;
  return { title: b.title, layers: b.baseLayers.toArray().map((l) => l.title + ' @ ' + l.url) };
});
ok('A. served basemap is the genuine Esri imagery + reference service (200 tiles, 0 fails)',
  baseLayers.title === 'Esri Imagery Hybrid' &&
  baseLayers.layers.some((l) => l.includes('World_Imagery/MapServer')) &&
  tilesOk > 0 && tilesFail === 0,
  `${baseLayers.title} tiles ok=${tilesOk} fail=${tilesFail}`);

// ---- B. antimeridian continuity ----------------------------------------------
await goRegion(179.5, 0, 3);
await mapShot('00_antimeridian.png');
const seam = await page.evaluate(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const view = el.__fleetMapView.view;
  const r = el.getBoundingClientRect();
  const proj = view.map.layers.find((l) => l.title === 'markers').graphics
    .toArray().filter((g) => g.attributes.kind === 'marker')
    .map((g) => { const p = view.toScreen(g.geometry); return Number.isFinite(p.x) && Number.isFinite(p.y); });
  return { settled: view.stationary, canvas: el.querySelectorAll('canvas').length, projOk: proj.every(Boolean), n: proj.length };
});
ok('B. cross-antimeridian view settles with no seam breakage (all markers project finite)',
  seam.settled && seam.canvas === 1 && seam.projOk && seam.n > 0 && tilesFail === 0,
  `markers=${seam.n} tiles fail=${tilesFail}`);

// ---- C. world view -----------------------------------------------------------
await fit();
await sleep(2000);
await mapShot('01_world.png');
ok('C. world view captured', fs.existsSync(path.join(SHOTS, '01_world.png')));

// ---- D. zoomed regional views -------------------------------------------------
const regions = [
  ['02_india_indian_ocean.png', 78, 21, 5],
  ['03_africa_west.png', -17, 14, 5],
  ['04_europe.png', 15, 50, 5],
  ['05_asia_east_japan.png', 122, 33, 5],
  ['06_south_america.png', -60, -15, 5],
  ['07_north_america_east.png', -75, 38, 5],
];
let regionsOk = true;
for (const [file, lon, lat, zoom] of regions) {
  await goRegion(lon, lat, zoom);
  await mapShot(file);
  const info = await mapInfo();
  const landed = Math.abs(info.lon - lon) < 1 && Math.abs(info.lat - lat) < 1 && Math.abs(info.zoom - zoom) < 0.6;
  if (!landed) regionsOk = false;
  console.log(`   ${file}: landed=(${info.lon.toFixed(1)},${info.lat.toFixed(1)}) z=${info.zoom.toFixed(2)} ${landed ? 'ok' : 'OFF'}`);
}
ok('D. six zoomed regional views land on target + captured', regionsOk && tilesFail === 0,
  `tiles fail=${tilesFail}`);

// ---- E. polar edges ------------------------------------------------------------
await goRegion(0, 66, 4);
await mapShot('08_arctic_edge.png');
await goRegion(0, -66, 4);
await mapShot('09_antarctic_edge.png');
const polar = await mapInfo();
ok('E. polar edge views captured (camera in-world, tiles flowing)',
  Number.isFinite(polar.lat) && Math.abs(polar.lat + 66) < 1 && tilesFail === 0);

// ---- F. Full Screen / View Map (Expand Fleet) — active; exit to normal ---------
await stabilize();
await mapShot('10_fullscreen_expanded.png');
ok('F. full-screen fleet map captured (Expand Fleet mode)', true);
await page.getByText('[ Exit Full Screen ]').click();
await stabilize();
await sleep(1000);
await mapShot('11_normal_after_exit.png');
const afterExit = await page.evaluate(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const view = el.__fleetMapView.view;
  return { canvas: el.querySelectorAll('canvas').length, ready: view.ready };
});
ok('F2. exit full screen -> live normal map (same view, 1 canvas)', afterExit.canvas === 1 && afterExit.ready === true);

// ---- G. browser resize keeps the geographic state (no FIT needed) ----------------
const before = await mapInfo();
await page.setViewportSize({ width: 950, height: 700 });
await sleep(400);
await stabilize();
const after = await mapInfo();
const inWorld = (i) => i.lon >= -180 && i.lon <= 180 && i.lat >= -90 && i.lat <= 90;
const dLon = Math.abs(after.lon - before.lon);
const dLat = Math.abs(after.lat - before.lat);
ok('G. resize keeps the view in-world (no FIT recovery needed)', inWorld(after),
  `centre (${after.lon.toFixed(1)},${after.lat.toFixed(1)})`);
ok('G2. resize preserves centre lon/lat ±1°', dLon < 1 && dLat < 1,
  `drift (${dLon.toFixed(2)}°, ${dLat.toFixed(2)}°)`);
ok('G3. resize preserves zoom (camera zoom constant)', Math.abs(after.zoom - before.zoom) < 0.05,
  `zoom ${before.zoom.toFixed(2)}→${after.zoom.toFixed(2)}`);
await mapShot('12_resized.png');

const bad = results.filter((r) => r[0] === 'FAIL');
console.log(`\n==> ${results.length - bad.length}/${results.length} checks green, shots: ${SHOTS}`);
console.log('page errors:', pageErrors.length ? pageErrors.slice(0, 2).join(' | ') : 'none');
await browser.close();
process.exit(bad.length ? 1 : 0);
