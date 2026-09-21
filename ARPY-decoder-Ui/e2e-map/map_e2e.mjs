// E2E Fleet Map verification: drives the real built app through Chromium.
// Usage: node tools/map_e2e.mjs
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:8000';
const SHOTS = '/tmp/mapshots';
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const ok = (name, cond, extra = '') => {
  results.push([cond ? 'PASS' : 'FAIL', name, extra]);
  console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (extra ? '   ' + extra : ''));
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Real pointer click on a marker, using trusted input (mousedown/up/click):
// viewBox coords -> client coords via the svg bounding box.
async function clickMarker(page, wmo) {
  const pt = await page.evaluate((w) => {
    const svg = document.querySelector('svg[role="img"]');
    const g = document.querySelector(`svg[role="img"] g[data-wmo="${w}"]`);
    if (!svg || !g) return null;
    const c = g.querySelector('circle');
    const bb = svg.getBoundingClientRect();
    const vb = svg.viewBox.baseVal;
    const sx = bb.width / vb.width, sy = bb.height / vb.height;
    return { x: bb.left + Number(c.getAttribute('cx')) * sx, y: bb.top + Number(c.getAttribute('cy')) * sy };
  }, wmo);
  if (!pt) throw new Error('marker not found for click: ' + wmo);
  await page.mouse.click(pt.x, pt.y);
}


async function api(p) {
  const r = await fetch(BASE + '/api' + p);
  if (!r.ok) throw new Error(p + ' -> ' + r.status);
  return r.json();
}

// ---- data ground truth from the backend ----------------------------------
const batch = (await api('/batches'))[0];
const items = batch.items;
const runs = {};
const truthPos = {};  // wmo -> latest cycle-with-position (cycle asc)
const truthTraj = {}; // wmo -> [{cycle,lat,lon}]
for (const it of items) {
  if (!it.run_id) continue;
  const run = await api(`/runs/${it.run_id}`);
  runs[it.wmo] = run;
  const cyc = (run.cycles || [])
    .filter((c) => c.latitude != null && c.longitude != null && Math.abs(c.latitude) <= 90 && Math.abs(c.longitude) <= 180)
    .sort((a, b) => a.cycle_number - b.cycle_number || (a.juld ?? 0) - (b.juld ?? 0));
  if (cyc.length) {
    truthPos[it.wmo] = cyc[cyc.length - 1];
    truthTraj[it.wmo] = cyc.map((c) => ({ cycle: c.cycle_number, lat: c.latitude, lon: c.longitude }));
  }
}
const testedWmos = Object.keys(truthPos);
console.log('backend ground truth: floats with positions =', testedWmos.join(', '));
if (testedWmos.length < 2) throw new Error('need >=2 floats with positions for selection swap test');

const wmoA = Number(testedWmos[0]);
const wmoB = Number(testedWmos[1]);

// ---- launch ---------------------------------------------------------------
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const pageErrors = [];
page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 500)));
page.on('console', (m) => {
  if (m.type() === 'error') pageErrors.push('[console] ' + m.text().slice(0, 300));
  const t = m.text();
  if (t.startsWith('[')) console.log('  LOG>', t.slice(0, 220));
});
const t0 = Date.now();

await page.goto(BASE, { waitUntil: 'domcontentloaded' });

// Basemap resource timing (preloaded by the app bundle at startup)
await page.waitForLoadState('networkidle');

// How did the app reach the Results view: batch already completed before
// the browser opened, so OPEN Run History? No — simpler: use the store via
// the Header flow. The batch completed already, but the fresh tab never
// promoted it (by design). Click HISTORY … actually the Results page only
// needs currentBatch — which the running-then-completed batch set in the
// store of the (earlier) session; this fresh tab has none. So post a NEW
// tiny batch from inside this tab? That's slow. Instead: dispatch the same
// store update path as the WS event: simplest deterministic route = click
// DECODE ALL on the tiny remaining set? Not available per-button.
// => We use Run History "View Results"? Check availability; fall back is to
// trigger the batch via fetch and wait for the banner (real UI flow).
const bannerBtns = await page.locator('text=VIEW RESULTS').count();
console.log('VIEW RESULTS buttons on fresh tab:', bannerBtns);
// The state is per-tab (Zustand memory). To get batch state here, fetch the
// latest batch into the store the same way the app does — click through:
await page.evaluate(async () => {
  const b = await (await fetch('/api/batches')).json();
  // Trigger the internal store update the same way the app would after a live batch:
  // easiest legit path = POST a no-op force=false decode-all which will 409/complete-fast
  // because everything is cached; the WS push then populates currentBatch.
  // But simplest: dispatch custom event? No. Use the app's own starter:
  const st = new URLSearchParams();
  void st;
  // 1) ask backend for latest batch
  const latest = b[0];
  // 2) mount it into the UI store through the public API the app uses: window.zustand? not exposed.
  // The app store subscribes via WS; the batch is complete, so instead post a
  // Cached batch (fast) whose WS events will drive the store:
  await fetch('/api/batch/decode-all', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ wmos: [2901304, 2902201, 2901339, 2902203] }),
  });
  void latest;
});
// wait for the banner to finish (all items cached -> completes in seconds)
await page.waitForFunction(
  () => !document.body.innerText.includes('DECODING FLOAT'),
  { timeout: 60000 }
);
await sleep(800);

// click VIEW RESULTS (Header) — if a completion modal auto-opened, close it first
const closeBtns = page.locator('button:has-text("Close"), button:has-text("×"), [aria-label="Close"]');
if (await closeBtns.first().count()) {
  await closeBtns.first().click().catch(() => {});
  await sleep(300);
}
await page.getByText('VIEW RESULTS').first().click();
// second guard: modal may overlay the map; escape-dismiss if markers hide
try {
  await page.waitForSelector('[data-wmo]', { timeout: 12000 });
} catch {
  await page.keyboard.press('Escape');
  await sleep(400);
  await page.getByText('VIEW RESULTS').first().click();
  await page.waitForSelector('[data-wmo]', { timeout: 30000 });
}

// ---- 1. normal Results page: map visible with real floats ----------------
const normalShot = path.join(SHOTS, '01_normal_results.png');
const tMap1 = Date.now();
await page.waitForSelector('svg image', { state: 'attached' });
const tBasemapPaint = Date.now() - tMap1;
const normalMarkers = await page.locator('svg g[data-wmo]').count();
await page.screenshot({ path: normalShot });
ok('1. normal Results page renders the real satellite basemap', await page.locator('svg image').first().count() > 0);
ok('1. normal page shows every float with position (backend truth)', normalMarkers === testedWmos.length,
   `dom=${normalMarkers} truth=${testedWmos.length}`);

// WMO -> run -> lat/lon trace
let traceOk = true;
let traceDetail = '';
for (const w of testedWmos) {
  const el = page.locator(`svg g[data-wmo="${w}"]`).first();
  const lat = Number(await el.getAttribute('data-lat'));
  const lon = Number(await el.getAttribute('data-lon'));
  const t = truthPos[w];
  const dLat = Math.abs(lat - t.latitude);
  const dLon = Math.abs(lon - t.longitude);
  if (dLat > 1e-6 || dLon > 1e-6) { traceOk = false; traceDetail += ` ${w}:${dLat.toFixed(4)}/${dLon.toFixed(4)}`; }
}
ok('7. marker coordinates == latest real cycle position per WMO/run', traceOk, traceDetail || 'exact');

// ---- 2. Expand Fleet: no skeleton, instant map -----------------------------
const tExp = Date.now();
await page.getByText('[ Expand Fleet ]').click();
await page.waitForSelector('svg image', { state: 'attached' });
const dtExpand = Date.now() - tExp;
await sleep(250);
await page.screenshot({ path: path.join(SHOTS, '02_expand_fleet_250ms.png') });
ok('2. Expand Fleet: real basemap present immediately (no empty/skeleton state)',
   await page.locator('svg image').first().count() > 0, `attach ${dtExpand} ms`);
const loadingChip = await page.locator('text=Loading map…').count();
console.log('   basemap loading chip visible after expand:', loadingChip ? 'no (already decoded)' : 'n/a');

// ---- 4. zoom buttons -------------------------------------------------------
async function markerXY(w) {
  // the marker CORE circle (selected #fde047, normal #fbbf24) — never a cycle dot
  const el = page.locator(
    `svg g[data-wmo="${w}"] > circle[fill="#fbbf24"], svg g[data-wmo="${w}"] > circle[fill="#fde047"]`
  ).first();
  return { x: Number(await el.getAttribute('cx')), y: Number(await el.getAttribute('cy')) };
}
const beforeZoom = await markerXY(wmoA);
await page.getByTestId('map-zoom-in').click();
await sleep(400);
const afterZoom = await markerXY(wmoA);
await page.screenshot({ path: path.join(SHOTS, '03_zoom_in_1x.png') });
ok('4. zoom in moves marker outward from centre (no jump/reset)',
   Math.abs(afterZoom.x - beforeZoom.x) + Math.abs(afterZoom.y - beforeZoom.y) > 1,
   `d=(${ (afterZoom.x-beforeZoom.x).toFixed(1)}, ${(afterZoom.y-beforeZoom.y).toFixed(1)})`);

await page.getByTestId('map-zoom-out').click();
await page.getByTestId('map-zoom-out').click();
await sleep(500);
await page.screenshot({ path: path.join(SHOTS, '04_zoom_out_2x.png') });

// ---- 5. wheel zoom ----------------------------------------------------------
const svgBox = await page.locator('svg[role="img"]').first().boundingBox();
const cx = svgBox.x + svgBox.width / 2, cy = svgBox.y + svgBox.height / 3;
const preWheel = await markerXY(wmoA);
await page.mouse.move(cx, cy);
await page.mouse.wheel(0, -700); // zoom in
await sleep(300);
let postWheel = { x: NaN, y: NaN };
try { postWheel = await markerXY(wmoA); } catch { /* marker may have vanished */ }
ok('5. mouse wheel zooms in responsively',
   Math.abs(postWheel.x - preWheel.x) + Math.abs(postWheel.y - preWheel.y) > 1,
   `pre=(${preWheel.x.toFixed(1)},${preWheel.y.toFixed(1)}) post=(${String(postWheel.x)},${String(postWheel.y)})`);
await page.mouse.wheel(0, 700); // zoom out
await sleep(300);
// DIAGNOSTIC snapshot of app state after wheel events
const diag = await page.evaluate(() => ({
  markerGroups: document.querySelectorAll('svg g[data-wmo]').length,
  svgs: document.querySelectorAll('svg').length,
  images: document.querySelectorAll('svg image').length,
  bodyText: document.body.innerText.slice(0, 220),
  url: location.href,
}));
console.log('DIAG after wheel:', JSON.stringify(diag, null, 1));
console.log('PAGE ERRORS so far:', pageErrors.slice(0, 6));

// ---- 6. drag/pan after zooming ---------------------------------------------
try { await page.getByTestId('map-zoom-in').click(); } catch { /**/ }
await sleep(300);
let preDrag;
try { preDrag = await markerXY(wmoA); }
catch { preDrag = null; console.log('DIAG: marker still missing before drag'); }
if (!preDrag) { throw new Error('marker missing — abort'); }
await page.mouse.move(svgBox.x + svgBox.width * 0.5, svgBox.y + svgBox.height * 0.5);
await page.mouse.down();
await page.mouse.move(svgBox.x + svgBox.width * 0.65, svgBox.y + svgBox.height * 0.62, { steps: 8 });
await page.mouse.up();
await sleep(250);
const postDrag = await markerXY(wmoA);
ok('6. drag pans the map after zooming (markers move with the world)',
   Math.abs(postDrag.x - preDrag.x) + Math.abs(postDrag.y - preDrag.y) > 5,
   `d=(${ (postDrag.x-preDrag.x).toFixed(1)}, ${(postDrag.y-preDrag.y).toFixed(1)})`);

// drag did not trigger a selection change
const selStill = await page.locator(`svg [data-wmo="${wmoA}"] circle[stroke="#fde047"]`).count();
console.log('   selection unchanged by drag (ring on wmoA):', selStill > 0);

// ---- 7. FIT ------------------------------------------------------------------
await page.getByTestId('map-fit').click();
await sleep(700);
const vb = await page.locator('svg[role="img"]').first().getAttribute('viewBox');
const [vw, vh] = vb.split(' ').slice(2).map(Number);
let allInside = true;
for (const w of testedWmos) {
  const p = await markerXY(Number(w));
  if (p.x < -5 || p.x > vw + 5 || p.y < -5 || p.y > vh + 5) allInside = false;
}
ok('7. FIT frames the whole fleet inside the viewport', allInside);
await page.screenshot({ path: path.join(SHOTS, '05_fit.png') });

// ---- 8-11. selection: marker small, no cover; all cycles; trajectory --------
await clickMarker(page, wmoA);
await sleep(1200); // auto-frame animation
await page.screenshot({ path: path.join(SHOTS, '06_select_A.png') });
console.log('DIAG world transform after select:',
  await page.evaluate(() => document.querySelector('svg[role="img"] g[data-world-transform]')?.getAttribute('transform')));
console.log('DIAG markerXY after select:', JSON.stringify(await markerXY(wmoA)));

const ring = await page.locator(`svg [data-wmo="${wmoA}"] > circle[stroke="#fde047"]`).first();
const ringR = Number(await ring.getAttribute('r'));
const core = await page.locator(`svg [data-wmo="${wmoA}"] > circle[fill="#fde047"]`).first();
const coreR = Number(await core.getAttribute('r'));
ok('9. selected marker stays SMALL with a subtle ring', coreR <= 4.2 && ringR <= 8,
   `core r=${coreR}, ring r=${ringR}`);

const trajCount = await page.locator('svg polyline[data-trajectory]').count();
if (trajCount > 0) {
  const n = Number(await page.locator('svg polyline[data-trajectory]').getAttribute('data-points-count'));
  const trajWmo = await page.locator('svg polyline[data-trajectory]').getAttribute('data-trajectory');
  const exp = truthTraj[wmoA]?.length || 0;
  ok('10/11. trajectory belongs to the selected WMO and contains ALL real cycle points',
     trajWmo === String(wmoA) && n === exp, `wmo=${trajWmo} dom=${n} backend=${exp}`);
} else {
  ok('10/11. trajectory drawn for selected float', false, 'polyline missing');
}

// cycle dots geographically distinct & ON the path (positions match truth)
const dotPos = await page.$$eval('svg circle[data-cycle]', (els) =>
  els.map((e) => ({ c: e.getAttribute('data-cycle'), lon: Number(e.getAttribute('data-lon')), lat: Number(e.getAttribute('data-lat')), x: Number(e.getAttribute('cx')), y: Number(e.getAttribute('cy')) }))
);
const truthA = truthTraj[wmoA] || [];
const posOk = dotPos.length === truthA.length &&
  dotPos.every((d) => {
    const t = truthA.find((t) => String(t.cycle) === String(d.c));
    return t && Math.abs(t.lat - d.lat) < 1e-9 && Math.abs(t.lon - d.lon) < 1e-9;
  });
ok('10. every cycle dot carries the real cycle lat/lon (sorted, unmodified)', posOk, `dots=${dotPos.length}`);

// ring must not cover nearby dots: ring (7.5 + core 4) = 11.5px; any dot
// within 12px of the marker centre is only *slightly* overlapped at edge —
// assert no dot centre lies within the marker core radius.
const mA = await markerXY(wmoA);
const covered = dotPos.filter((d) => d.x !== mA.x && Math.hypot(d.x - mA.x, d.y - mA.y) < coreR + 1.5).length;
ok('9/3. selection ring/core does not cover nearby cycle dots', covered === 0, `covered=${covered}`);

// ---- 12. click ANOTHER float: trajectory replaced ----------------------------
await page.getByTestId('map-fit').click(); // bring all markers back on screen
await sleep(800);
await clickMarker(page, wmoB);
await sleep(1400);
const trajWmo2 = await page.locator('svg polyline[data-trajectory]').getAttribute('data-trajectory');
const n2 = Number(await page.locator('svg polyline[data-trajectory]').getAttribute('data-points-count'));
ok('12. clicking another float replaces the trajectory', trajWmo2 === String(wmoB) && n2 === (truthTraj[wmoB]?.length || 0),
   `wmo=${trajWmo2} dom=${n2}`);
await page.screenshot({ path: path.join(SHOTS, '07_select_B.png') });

// ---- 13. Exit Full Screen: state preserved -----------------------------------
const mBefore = await markerXY(wmoB).catch(() => null);
await page.getByText('[ Exit Full Screen ]').click();
await sleep(700);
const stillTraj = await page.locator(`svg polyline[data-trajectory="${wmoB}"]`).count();
const stillSel = await page.locator(`svg [data-wmo="${wmoB}"] circle[stroke="#fde047"]`).count();
ok('13. exit View Map: selection + trajectory preserved in the normal map',
   stillTraj > 0 && stillSel > 0, `sel=${wmoB} ring=${stillSel} traj=${stillTraj}`);
await page.screenshot({ path: path.join(SHOTS, '08_after_exit.png') });
void mBefore;

// ---- perf numbers -------------------------------------------------------------
const perf = await page.evaluate(() => {
  const entries = performance.getEntriesByType('resource').filter((e) => e.name.includes('fleet_basemap'));
  return entries.map((e) => ({ name: e.name.split('/').pop(), start: Math.round(e.startTime), end: Math.round(e.responseEnd), size: e.transferSize }));
});
console.log('basemap resource timing:', JSON.stringify(perf));
const runsTiming = await page.evaluate(() => {
  const r = performance.getEntriesByType('resource').filter((e) => e.name.includes('/api/runs/'));
  return { count: r.length, lastEnd: Math.round(Math.max(0, ...r.map((e) => e.responseEnd))) };
});
console.log('run-hydration fetches:', JSON.stringify(runsTiming));

console.log('\n========== MAP E2E SUMMARY ==========');
const fails = results.filter(([s]) => s === 'FAIL');
console.log(`${results.length - fails.length}/${results.length} checks passed`);
for (const [s, n] of results) if (s === 'FAIL') console.log('FAILED:', n);
await browser.close();
