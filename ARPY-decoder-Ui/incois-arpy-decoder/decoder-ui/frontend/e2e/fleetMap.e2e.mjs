// Fleet Map E2E — drives the REAL built app through headless Chromium
// against a live backend and verifies the fleet-ocean-map behavior on real
// decoded data (15 checks).
//
// Renderer: ArcGIS Maps SDK MapView (Esri World Imagery + Boundaries &
// Places). Markers/trajectories/cycle dots are SDK graphics, so assertions
// read the live view through the `__fleetMapView`/`__fleetMapData` handles
// and project with view.toScreen — never DOM scraping.
//
// Usage:
//   npm run build && npm run test:e2e
// Env:
//   MAP_E2E_BASE   backend URL          (default http://127.0.0.1:8000)
//   MAP_E2E_SHOTS  screenshot output dir (default /tmp/mapshots)
// Requires: `npx playwright install chromium` once, and a backend serving
// at least one completed batch with >= 2 floats that have valid positions.
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.MAP_E2E_BASE || 'http://127.0.0.1:8000';
const SHOTS = process.env.MAP_E2E_SHOTS || '/tmp/mapshots';
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const ok = (name, cond, extra = '') => {
  results.push([cond ? 'PASS' : 'FAIL', name, extra]);
  console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (extra ? '   ' + extra : ''));
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// One round-trip snapshot of everything the checks need from the live view.
async function mapState(page) {
  return page.evaluate(() => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    if (!el || !el.__fleetMapView) return null;
    const view = el.__fleetMapView.view;
    const rect = el.getBoundingClientRect();
    const layer = (title) => view.map.layers.find((l) => l.title === title);
    const shot = (g) => {
      const p = view.toScreen(g.geometry);
      return { lon: g.geometry.longitude, lat: g.geometry.latitude, x: p.x, y: p.y };
    };
    const markers = layer('markers')
      ? layer('markers').graphics.toArray().filter((g) => g.attributes?.kind === 'marker')
        .map((g) => ({ wmo: g.attributes.wmo, ...shot(g) }))
      : [];
    const sel = layer('selection')?.graphics.toArray().find((g) => g.attributes?.kind === 'selection');
    const traj = layer('trajectory-line')?.graphics.toArray().find((g) => g.attributes?.kind === 'trajectory');
    const dots = layer('cycle-dots')
      ? layer('cycle-dots').graphics.toArray().map((g) => ({
        cycle: g.attributes.cycle, lon: g.geometry.longitude, lat: g.geometry.latitude,
        x: view.toScreen(g.geometry).x, y: view.toScreen(g.geometry).y,
      }))
      : [];
    return {
      ready: view.ready, stationary: view.stationary, zoom: view.zoom,
      center: [view.center.longitude, view.center.latitude],
      viewW: rect.width, viewH: rect.height,
      basemap: view.map.basemap
        ? [view.map.basemap.title, ...view.map.basemap.baseLayers.toArray().map((l) => l.title)]
        : [],
      canvases: el.querySelectorAll('canvas').length,
      markers, selWmo: sel ? sel.attributes.wmo : null,
      traj: traj ? { wmo: traj.attributes.wmo, points: traj.attributes.points } : null,
      dots,
    };
  });
}

// Real pointer click on a marker: project its map point to page coords.
async function clickMarker(page, wmo) {
  const pt = await page.evaluate((w) => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    const view = el.__fleetMapView.view;
    const g = view.map.layers.find((l) => l.title === 'markers').graphics
      .toArray().find((m) => m.attributes?.kind === 'marker' && m.attributes.wmo === w);
    if (!g) return null;
    const p = view.toScreen(g.geometry);
    const r = el.getBoundingClientRect();
    return { x: r.left + p.x, y: r.top + p.y };
  }, wmo);
  if (!pt) throw new Error('marker not found for click: ' + wmo);
  await page.mouse.click(pt.x, pt.y);
}

async function waitSettled(page, timeout = 15000) {
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    const v = el && el.__fleetMapView && el.__fleetMapView.view;
    return v && v.ready && v.stationary;
  }, { timeout });
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
  let run;
  try { run = await api(`/runs/${it.run_id}`); }
  catch { continue; } // error/stopped items have no run record (no cycles)
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

// Chosen AFTER fit below: the pair of floats whose markers are spatially
// separable on screen (marker clicks are real pointer events — an overlapped
// marker would intercept the click of a neighbour).
let wmoA = Number(testedWmos[0]);
let wmoB = Number(testedWmos[1]);

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
let tilesOk = 0, tilesFail = 0;
page.on('response', (r) => {
  if (r.url().includes('server.arcgisonline.com') && r.url().includes('/tile/')) {
    if (r.ok()) tilesOk++; else tilesFail++;
  }
});

await page.goto(BASE, { waitUntil: 'domcontentloaded' });
await page.waitForLoadState('networkidle');

// Drive the REAL user action: Decode All Today's Floats. The backend now
// decides from CURRENT state — start a fresh batch OR, when every eligible
// float is already processed today, answer "already complete" (no duplicate
// batch) and let the UI offer View Results / Re-run All. Both paths end on
// the Results view; this harness must work either way.
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
  // a real batch is running — wait for it to finish, then open Results
  await page.waitForFunction(
    () => !document.body.innerText.includes('DECODING FLOAT'),
    { timeout: 60000 }
  );
  await sleep(800);
}

// click VIEW RESULTS (Header). If a completion modal opened, it contains
// its own RESULTS action inside the dialog; otherwise the header button.
const tryViewResults = async () => {
  const modalBtn = page.locator('div[role="dialog"] button:has-text("VIEW RESULTS"), div[role="dialog"] button:has-text("View Results")');
  if (await modalBtn.first().count()) {
    await modalBtn.first().click();
    return true;
  }
  const btns = await page.locator('button:has-text("VIEW RESULTS")').count();
  const texts = await page.locator('text=VIEW RESULTS').count();
  console.log('   VIEW RESULTS locators — buttons:', btns, 'text matches:', texts);
  if (btns > 0) {
    await page.locator('button:has-text("VIEW RESULTS")').first().click({ timeout: 5000 });
    return true;
  }
  if (texts > 0) {
    await page.getByText('VIEW RESULTS').first().click({ timeout: 5000 });
    return true;
  }
  return false;
};
await tryViewResults();
// guard: modal may overlay the map; escape-dismiss if markers hide
const markersPredicate = `() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const v = el && el.__fleetMapView && el.__fleetMapView.view;
  if (!v || !v.ready) return false;
  const layer = v.map.layers.find((l) => l.title === 'markers');
  return !!layer && layer.graphics.toArray().some((g) => g.attributes && g.attributes.kind === 'marker');
}`;
try {
  await page.waitForFunction(new Function('return ' + markersPredicate)(), { timeout: 30000 });
} catch {
  console.log('   markers not visible after VIEW RESULTS; body text sample:',
    (await page.evaluate(() => document.body.innerText.slice(0, 300))).replace(/\n/g, ' | '));
  await page.keyboard.press('Escape');
  await sleep(400);
  await tryViewResults();
  await page.waitForFunction(new Function('return ' + markersPredicate)(), { timeout: 30000 });
}
await waitSettled(page);
await sleep(2500); // let Esri tiles stream in

// ---- 1. normal Results page: map visible with real floats ----------------
const normalShot = path.join(SHOTS, '01_normal_results.png');
const s1 = await mapState(page);
await page.screenshot({ path: normalShot });
const hasHybrid = s1.basemap.includes('Esri Imagery Hybrid');
ok('1. normal Results page renders the real Esri satellite basemap',
  hasHybrid && s1.canvases === 1 && tilesOk > 0 && tilesFail === 0,
  `layers=[${s1.basemap.join('|')}] canvases=${s1.canvases} tiles ok=${tilesOk} fail=${tilesFail}`);
ok('1. normal page shows every float with position (backend truth)',
  s1.markers.length === testedWmos.length,
  `map=${s1.markers.length} truth=${testedWmos.length}`);

// WMO -> run -> lat/lon trace
let traceOk = true;
let traceDetail = '';
for (const w of testedWmos) {
  const m = s1.markers.find((m) => m.wmo === Number(w));
  const t = truthPos[w];
  if (!m) { traceOk = false; traceDetail += ` ${w}:missing`; continue; }
  const dLat = Math.abs(m.lat - t.latitude);
  const dLon = Math.abs(m.lon - t.longitude);
  if (dLat > 1e-6 || dLon > 1e-6) { traceOk = false; traceDetail += ` ${w}:${dLat.toFixed(4)}/${dLon.toFixed(4)}`; }
}
ok('7. marker coordinates == latest real cycle position per WMO/run', traceOk, traceDetail || 'exact');

// ---- 2. Expand Fleet: same live view, fleet intact --------------------------
const tExp = Date.now();
await page.getByText('[ Expand Fleet ]').click();
await page.waitForFunction(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const v = el && el.__fleetMapView && el.__fleetMapView.view;
  return v && v.ready && v.stationary && el.querySelectorAll('canvas').length === 1;
}, { timeout: 30000 });
const dtExpand = Date.now() - tExp;
await sleep(250);
await page.screenshot({ path: path.join(SHOTS, '02_expand_fleet_250ms.png') });
const s2 = await mapState(page);
ok('2. Expand Fleet: same live Esri view reparented (no reload, fleet intact)',
  s2.canvases === 1 && s2.markers.length === testedWmos.length && s2.basemap.includes('Esri Imagery Hybrid'),
  `attach ${dtExpand} ms markers=${s2.markers.length}`);

// ---- 4. zoom buttons -------------------------------------------------------
const beforeZoom = (await mapState(page)).markers.find((m) => m.wmo === wmoA);
const zBefore = (await mapState(page)).zoom;
await page.getByTestId('map-zoom-in').click();
await waitSettled(page);
const sZoom = await mapState(page);
const afterZoom = sZoom.markers.find((m) => m.wmo === wmoA);
await page.screenshot({ path: path.join(SHOTS, '03_zoom_in_1x.png') });
const movedOut = Math.abs(afterZoom.x - sZoom.viewW / 2) + Math.abs(afterZoom.y - sZoom.viewH / 2) >=
  Math.abs(beforeZoom.x - sZoom.viewW / 2) + Math.abs(beforeZoom.y - sZoom.viewH / 2) - 2;
ok('4. zoom in steps the camera without jumping (marker pushed outward)',
  Math.abs(sZoom.zoom - zBefore - 1) < 0.6 && movedOut,
  `zoom ${zBefore.toFixed(2)}→${sZoom.zoom.toFixed(2)} d=(${(afterZoom.x - beforeZoom.x).toFixed(1)}, ${(afterZoom.y - beforeZoom.y).toFixed(1)})`);

await page.getByTestId('map-zoom-out').click();
await page.getByTestId('map-zoom-out').click();
await waitSettled(page);
await sleep(500);
await page.screenshot({ path: path.join(SHOTS, '04_zoom_out_2x.png') });

// ---- 5. wheel zoom ----------------------------------------------------------
const viewBox = await page.locator('[data-testid="esri-map-view"]').first().boundingBox();
const cx = viewBox.x + viewBox.width / 2, cy = viewBox.y + viewBox.height / 3;
const preWheel = await mapState(page);
await page.mouse.move(cx, cy);
await page.mouse.wheel(0, -700); // zoom in
await waitSettled(page);
const postWheel = await mapState(page);
const wobA = (id, s) => s.markers.find((m) => m.wmo === id);
ok('5. mouse wheel zooms in responsively',
  postWheel.zoom > preWheel.zoom + 0.3 &&
  Math.abs(wobA(wmoA, postWheel).x - wobA(wmoA, preWheel).x) + Math.abs(wobA(wmoA, postWheel).y - wobA(wmoA, preWheel).y) > 1,
  `zoom ${preWheel.zoom.toFixed(2)}→${postWheel.zoom.toFixed(2)}`);
await page.mouse.wheel(0, 700); // zoom out
await waitSettled(page);

// ---- 6. drag/pan after zooming ---------------------------------------------
try { await page.getByTestId('map-zoom-in').click(); } catch { /**/ }
await waitSettled(page);
const preDrag = await mapState(page);
await page.mouse.move(viewBox.x + viewBox.width * 0.5, viewBox.y + viewBox.height * 0.5);
await page.mouse.down();
await page.mouse.move(viewBox.x + viewBox.width * 0.65, viewBox.y + viewBox.height * 0.62, { steps: 8 });
await page.mouse.up();
await waitSettled(page);
const postDrag = await mapState(page);
const dragD = Math.abs(wobA(wmoA, postDrag).x - wobA(wmoA, preDrag).x) + Math.abs(wobA(wmoA, postDrag).y - wobA(wmoA, preDrag).y);
ok('6. drag pans the map after zooming (markers move with the world)',
  dragD > 5 && (Math.abs(postDrag.center[0] - preDrag.center[0]) + Math.abs(postDrag.center[1] - preDrag.center[1]) > 0),
  `d=(${(wobA(wmoA, postDrag).x - wobA(wmoA, preDrag).x).toFixed(1)}, ${(wobA(wmoA, postDrag).y - wobA(wmoA, preDrag).y).toFixed(1)})`);

// drag did not trigger a selection change
console.log('   selection unchanged by drag (sel still on wmoA):', postDrag.selWmo === preDrag.selWmo);

// ---- 7. FIT ------------------------------------------------------------------
// FIT frames the whole fleet: afterwards every marker must project inside
// the viewport (the Esri view has no cover clamp — any zoom is reachable).
await page.getByTestId('map-fit').click();
await waitSettled(page);
await sleep(700);
const sFit = await mapState(page);
const outside = sFit.markers.filter((m) => m.x < -5 || m.x > sFit.viewW + 5 || m.y < -5 || m.y > sFit.viewH + 5);
ok('7. FIT frames the whole fleet inside the viewport',
  outside.length === 0 && sFit.zoom < postDrag.zoom,
  outside.length ? 'outside=' + outside.map((m) => m.wmo).join(',') : `zoom=${sFit.zoom.toFixed(2)}`);
await page.screenshot({ path: path.join(SHOTS, '05_fit.png') });

// Pick the test pair by MARKER ISOLATION at the fitted view: each chosen
// float must have no other marker close enough to intercept its click
// (generous 26px hit disc — neighbours within ~28px would steal the pointer).
{
  const pts = sFit.markers;
  const iso = (p) => Math.min(...pts.filter((q) => q.wmo !== p.wmo).map((q) => Math.hypot(q.x - p.x, q.y - p.y)));
  const isolated = pts.filter((p) => iso(p) >= 30).sort((a, b) => iso(b) - iso(a));
  if (isolated.length >= 2) {
    wmoA = isolated[0].wmo;
    const bi = isolated.slice(1).sort((a, b) =>
      Math.hypot(b.x - isolated[0].x, b.y - isolated[0].y) - Math.hypot(a.x - isolated[0].x, a.y - isolated[0].y))[0];
    wmoB = bi.wmo;
  } else {
    const best = pts.flatMap((p) => pts.map((q) => p.wmo < q.wmo ? { p, q, d: Math.hypot(p.x - q.x, p.y - q.y) } : null)).filter(Boolean).sort((x, y) => y.d - x.d)[0];
    console.log(`   markers cluster at fit (iso<30px); widest pair sep=${best.d.toFixed(1)}px`);
    wmoA = best.p.wmo; wmoB = best.q.wmo;
  }
  console.log(`   test pair by real screen separation: wmoA=${wmoA} wmoB=${wmoB} (iso ok)`);
}

// ---- 7b. WMO labels hidden until hover/click ---------------------------------
// Persistent marker labels: exactly one (the selected float) or none when
// nothing is selected. Hovering an isolated non-selected marker reveals a
// transient label with its WMO; moving to a marker-free spot removes it.
const sFit2 = await mapState(page);
const labelInfo = await page.evaluate(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  return el.__fleetMapView.view.map.layers.find((l) => l.title === 'labels').graphics
    .toArray().filter((g) => g.attributes?.kind === 'marker').map((g) => g.attributes.wmo);
});
const persistOk = sFit2.selWmo == null
  ? labelInfo.length === 0
  : labelInfo.length === 1 && labelInfo[0] === sFit2.selWmo;
const hoverTarget = [wmoB, wmoA].find((w) => w !== sFit2.selWmo) ?? wmoB;
const sFit2T = sFit2.markers.find((m) => m.wmo === hoverTarget);
const isoT = Math.min(...sFit2.markers.filter((m) => m.wmo !== hoverTarget).map((m) => Math.hypot(m.x - sFit2T.x, m.y - sFit2T.y)));
const viewRect = await page.locator('[data-testid="esri-map-view"]').first().boundingBox();
await page.mouse.move(viewRect.x + sFit2T.x, viewRect.y + sFit2T.y);
await sleep(600); // pointer-move -> hitTest round trip
const hoverWmo = await page.evaluate(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const g = el.__fleetMapView.view.map.layers.find((l) => l.title === 'labels').graphics
    .toArray().find((x) => x.attributes?.kind === 'marker-hover');
  return g ? g.attributes.wmo : null;
});
const hoverOk = hoverTarget !== sFit2.selWmo
  ? (isoT >= 30 ? hoverWmo === hoverTarget : sFit2.markers.some((m) => m.wmo === hoverWmo))
  : hoverWmo === null; // selected marker needs no hover label (persistent one shown)
// move to a marker-free spot of the view: the hover label must vanish
const corners = [
  [8, 8], [sFit2.viewW - 8, 8], [8, sFit2.viewH - 8], [sFit2.viewW - 8, sFit2.viewH - 8],
  [sFit2.viewW / 2, 8], [sFit2.viewW / 2, sFit2.viewH - 8],
];
const clear = corners.find(([x, y]) => sFit2.markers.every((m) => Math.hypot(m.x - x, m.y - y) >= 40));
let unhoverOk = true, unhoverNote = 'skipped (no clear spot)';
if (clear) {
  await page.mouse.move(viewRect.x + clear[0], viewRect.y + clear[1]);
  await sleep(600);
  const hoverAfter = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    return el.__fleetMapView.view.map.layers.find((l) => l.title === 'labels').graphics
      .toArray().filter((x) => x.attributes?.kind === 'marker-hover').length;
  });
  unhoverOk = hoverAfter === 0;
  unhoverNote = `hover graphics after unhover=${hoverAfter}`;
}
ok('7b. WMO labels hidden until hover/click (persistent: selected only; hover reveals + clears)',
  persistOk && hoverOk && unhoverOk,
  `persistent=[${labelInfo.join(',')}] sel=${sFit2.selWmo} hover=${hoverWmo} (target=${hoverTarget} iso=${isoT.toFixed(0)}px) ${unhoverNote}`);

// ---- 8-11. selection: marker small, no cover; all cycles; trajectory --------
await clickMarker(page, wmoA);
await page.waitForFunction((w) => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const g = el.__fleetMapView.view.map.layers.find((l) => l.title === 'selection').graphics.toArray()[0];
  return g && g.attributes.wmo === w;
}, wmoA, { timeout: 10000 });
await waitSettled(page); // auto-frame animation
await sleep(400);
await page.screenshot({ path: path.join(SHOTS, '06_select_A.png') });
const sA = await mapState(page);

const selShape = await page.evaluate(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const view = el.__fleetMapView.view;
  const sel = view.map.layers.find((l) => l.title === 'selection').graphics.toArray()[0];
  const core = view.map.layers.find((l) => l.title === 'markers').graphics
    .toArray().find((g) => g.attributes?.kind === 'marker' && g.attributes.wmo === sel.attributes.wmo);
  return { ringPt: sel.symbol.size, ringW: sel.symbol.outline.width, corePt: core.symbol.size };
});
// sizes are points (1pt ≈ 1.333px): core 8px=6pt, ring 15px=11.25pt
ok('9. selected marker stays SMALL with a subtle ring',
  sA.selWmo === wmoA && selShape.corePt <= 6.5 && selShape.ringPt <= 12 && selShape.ringW <= 2,
  `core=${selShape.corePt}pt ring=${selShape.ringPt}pt/${selShape.ringW}pt`);

const expA = truthTraj[wmoA]?.length || 0;
ok('10/11. trajectory belongs to the selected WMO and contains ALL real cycle points',
  sA.traj && sA.traj.wmo === wmoA && sA.traj.points === expA && sA.dots.length === expA,
  `wmo=${sA.traj?.wmo} map=${sA.traj?.points} backend=${expA}`);

// cycle dots carry the real cycle lat/lon (sorted, unmodified)
const truthA = truthTraj[wmoA] || [];
const posOk = sA.dots.length === truthA.length &&
  sA.dots.every((d) => {
    const t = truthA.find((t) => String(t.cycle) === String(d.cycle));
    return t && Math.abs(t.lat - d.lat) < 1e-9 && Math.abs(t.lon - d.lon) < 1e-9;
  });
ok('10. every cycle dot carries the real cycle lat/lon (sorted, unmodified)', posOk, `dots=${sA.dots.length}`);

// selection ring must not cover nearby dots: no dot centre (other than the
// marker's own latest-cycle dot) may lie within the core radius + margin —
// UNLESS the two cycles genuinely coincide in the world. A faithful
// renderer MUST overlap dots the float actually revisited: at trajectory
// framing ~1px ≈ 1km, so cycles within 5km (haversine on backend truth)
// are expected to coincide on screen and are reported, not failed.
const havKm = (la1, lo1, la2, lo2) => {
  const r = Math.PI / 180, h = Math.sin((la2 - la1) * r / 2) ** 2 +
    Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin((lo2 - lo1) * r / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
};
const mA = sA.markers.find((m) => m.wmo === wmoA);
const nearDots = sA.dots.filter((d) => {
  const px = Math.hypot(d.x - mA.x, d.y - mA.y);
  return px > 1 && px < 4 + 1.5;
});
const coinciding = nearDots.filter((d) => havKm(d.lat, d.lon, mA.lat, mA.lon) <= 5);
const covered = nearDots.filter((d) => havKm(d.lat, d.lon, mA.lat, mA.lon) > 5);
ok('9/3. selection ring/core does not cover nearby cycle dots', covered.length === 0,
  `covered=${covered.length} data-coincidences=${coinciding.map((d) => 'C' + d.cycle).join(',') || 'none'}`);

// ---- 12. click ANOTHER float: trajectory replaced ----------------------------
await page.getByTestId('map-fit').click(); // bring all markers back on screen
await waitSettled(page);
await clickMarker(page, wmoB);
await page.waitForFunction((w) => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const g = el.__fleetMapView.view.map.layers.find((l) => l.title === 'selection').graphics.toArray()[0];
  return g && g.attributes.wmo === w;
}, wmoB, { timeout: 10000 });
await waitSettled(page);
await sleep(400);
const sB = await mapState(page);
ok('12. clicking another float replaces the trajectory',
  sB.traj && sB.traj.wmo === wmoB && sB.traj.points === (truthTraj[wmoB]?.length || 0),
  `wmo=${sB.traj?.wmo} map=${sB.traj?.points}`);
await page.screenshot({ path: path.join(SHOTS, '07_select_B.png') });

// ---- 13. Exit Full Screen: state preserved -----------------------------------
await page.getByText('[ Exit Full Screen ]').click();
await waitSettled(page);
await sleep(700);
const sExit = await mapState(page);
ok('13. exit View Map: selection + trajectory preserved in the normal map',
  sExit.selWmo === wmoB && sExit.traj?.wmo === wmoB && sExit.canvases === 1,
  `sel=${sExit.selWmo} traj=${sExit.traj?.wmo}`);
await page.screenshot({ path: path.join(SHOTS, '08_after_exit.png') });

// ---- perf numbers -------------------------------------------------------------
const perf = await page.evaluate(() => {
  const entries = performance.getEntriesByType('resource').filter((e) => e.name.includes('arcgisonline'));
  const tiles = entries.filter((e) => e.name.includes('/tile/'));
  return {
    tileCount: tiles.length,
    tileBytes: tiles.reduce((a, e) => a + (e.transferSize || 0), 0),
    lastEnd: Math.round(Math.max(0, ...tiles.map((e) => e.responseEnd))),
  };
});
console.log('esri tile timing:', JSON.stringify(perf), `ok=${tilesOk} fail=${tilesFail}`);
const runsTiming = await page.evaluate(() => {
  const r = performance.getEntriesByType('resource').filter((e) => e.name.includes('/api/runs/'));
  return { count: r.length, lastEnd: Math.round(Math.max(0, ...r.map((e) => e.responseEnd))) };
});
console.log('run-hydration fetches:', JSON.stringify(runsTiming));

console.log('\n========== MAP E2E SUMMARY ==========');
const fails = results.filter(([s]) => s === 'FAIL');
console.log(`${results.length - fails.length}/${results.length} checks passed`);
for (const [s, n] of results) if (s === 'FAIL') console.log('FAILED:', n);
console.log('page errors:', pageErrors.length ? pageErrors.slice(0, 2).join(' | ') : 'none');
await browser.close();
process.exit(fails.length ? 1 : 0);
