// Read-only map audit of the experimental prediction layer against the API.
//
//   PREDICTION_MAP_BASE=http://127.0.0.1:3000 node e2e/predictionMap.e2e.mjs
//   Optional: PREDICTION_MAP_SHOTS=<artifact directory>
//
// Verifies, on the real ArcGIS renderer:
//   * the predicted point is exactly the API's predicted lat/lon,
//   * the 50 % / 90 % rings are drawn at exactly the API's r50_km / r90_km
//     (measured as great-circle radius of the rendered polygon vertices),
//   * floats without a usable prediction carry no predicted point and no ring,
//   * the real (observed) float marker is untouched by the prediction layer,
//   * the layer is opt-in and clears completely when switched off.
// Never triggers decoding, sends email, or writes operational source files.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.PREDICTION_MAP_BASE || 'http://127.0.0.1:3000';
const SHOTS = process.env.PREDICTION_MAP_SHOTS || '/tmp/prediction-map-shots';
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const check = (name, condition, details = '') => {
  results.push({ name, passed: Boolean(condition), details });
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${name}${details ? '  ' + details : ''}`);
  if (!condition) throw new Error(name + ': ' + details);
};
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

// Great-circle distance, metres — the same haversine the audit uses in Python.
const EARTH_R = 6371008.8;
const toRad = d => (d * Math.PI) / 180;
const haversineKm = (lat1, lon1, lat2, lon2) => {
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_R * Math.asin(Math.min(1, Math.sqrt(a))) / 1000;
};

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1720, height: 1000 }, timezoneId: 'Asia/Kolkata' });
const page = await context.newPage();
page.setDefaultTimeout(20000);
const pageErrors = [];
page.on('pageerror', error => pageErrors.push(error.message));

async function openStatus(targetPage) {
  await targetPage.goto(BASE, { waitUntil: 'domcontentloaded' });
  await targetPage.getByTitle('Open Dedicated Results & Oceanographic Analysis Workspace').click();
  await targetPage.getByRole('button', { name: '[ Float Status ]', exact: true }).click();
  await targetPage.getByTestId('float-status-page').waitFor();
  await targetPage.locator('[data-testid^="fleet-row-"]').first().waitFor();
}

const readLayers = () => page.getByTestId('esri-map-view').evaluate(el => {
  const view = el.__fleetMapView.view;
  const layer = view.map.layers.find(l => l.title === 'prediction');
  const markerLayer = view.map.layers.find(l => l.title === 'markers');
  const grab = g => ({
    kind: g.attributes?.kind,
    wmo: g.attributes?.wmo,
    radiusKm: g.attributes?.radiusKm ?? null,
    lat: g.geometry?.latitude ?? null,
    lon: g.geometry?.longitude ?? null,
    ring: g.geometry?.rings ? g.geometry.rings[0].map(([x, y]) => [x, y]) : null,
    path: g.geometry?.paths ? g.geometry.paths[0].map(([x, y]) => [x, y]) : null,
  });
  return {
    visible: layer.visible,
    graphics: layer.graphics.toArray().map(grab),
    markers: markerLayer.graphics.toArray().map(grab),
  };
});

try {
  const payload = await (await fetch(BASE + '/api/fleet-status')).json();
  const rows = payload.floats;
  const available = rows.filter(r => r.prediction?.available && r.prediction.predicted_lat != null);
  check('API serves the fleet with predictions for this audit', rows.length > 0 && available.length > 0,
    `${available.length}/${rows.length} floats with an available prediction`);

  await openStatus(page);
  await page.waitForFunction(() => {
    const view = document.querySelector('[data-testid="esri-map-view"]')?.__fleetMapView?.view;
    return view?.ready && view.stationary && !view.updating;
  }, null, { timeout: 90000 });

  const toggle = page.getByTestId('prediction-layer-toggle');
  check('prediction layer is offered but off by default',
    await toggle.isChecked() === false && (await readLayers()).graphics.length === 0);

  await toggle.check();
  await page.waitForFunction(count => {
    const layer = document.querySelector('[data-testid="esri-map-view"]')?.__fleetMapView?.view?.map?.layers
      ?.find(l => l.title === 'prediction');
    return layer && layer.visible && layer.graphics.length >= count;
  }, available.length, { timeout: 30000 });
  await page.screenshot({ path: path.join(SHOTS, 'prediction-layer-on.png') });

  const drawn = await readLayers();
  const points = drawn.graphics.filter(g => g.kind === 'prediction');
  const rings = drawn.graphics.filter(g => g.kind === 'prediction-ring');
  const links = drawn.graphics.filter(g => g.kind === 'prediction-link');

  check('every available prediction draws exactly one predicted point',
    points.length === available.length, `${points.length} points for ${available.length} forecasts`);
  check('predicted points are one per float and cover the same WMOs',
    new Set(points.map(p => String(p.wmo))).size === points.length &&
    available.every(r => points.some(p => String(p.wmo) === String(r.wmo))));

  let worstPointKm = 0;
  let worstRingKm = 0;
  const ringDetail = [];
  for (const row of available) {
    const p = points.find(g => String(g.wmo) === String(row.wmo));
    const km = haversineKm(row.prediction.predicted_lat, row.prediction.predicted_lon, p.lat, p.lon);
    worstPointKm = Math.max(worstPointKm, km);
    const mine = rings.filter(g => String(g.wmo) === String(row.wmo));
    check(`WMO ${row.wmo}: predicted point sits on the API position`, km < 1e-6, `${(km * 1000).toFixed(3)} m`);
    const expected = [row.prediction.r90_km, row.prediction.r50_km].filter(v => Number.isFinite(v) && v > 0);
    check(`WMO ${row.wmo}: one ring per validated radius, none invented`,
      mine.length === expected.length &&
      expected.every(v => mine.some(g => Math.abs(g.radiusKm - v) < 1e-9)),
      `${mine.length} rings for radii ${expected.map(v => v.toFixed(1)).join(' / ')}`);
    for (const ring of mine) {
      // Every vertex of the drawn polygon must sit on the quoted radius.
      const radii = ring.ring.map(([lon, lat]) =>
        haversineKm(row.prediction.predicted_lat, row.prediction.predicted_lon, lat, lon));
      const err = Math.max(...radii.map(r => Math.abs(r - ring.radiusKm)));
      const centerKm = haversineKm(row.prediction.predicted_lat, row.prediction.predicted_lon, ring.ring[0][1], ring.ring[0][0]);
      worstRingKm = Math.max(worstRingKm, err);
      check(`WMO ${row.wmo}: ${ring.radiusKm.toFixed(1)} km ring is drawn at that radius`,
        err <= 0.5 && Math.abs(centerKm - ring.radiusKm) <= Math.max(1, ring.radiusKm * 0.02),
        `max vertex error ${err.toFixed(3)} km over ${ring.ring.length} vertices`);
      ringDetail.push({ wmo: row.wmo, radiusKm: ring.radiusKm, vertices: ring.ring.length, maxErrKm: Number(err.toFixed(4)) });
    }
    check(`WMO ${row.wmo}: ring carries the API radius as its attribute`,
      mine.every(g => [row.prediction.r50_km, row.prediction.r90_km].some(v => Math.abs(v - g.radiusKm) < 1e-9)));
  }
  check('ring geometry matches the quoted radii across the fleet', worstRingKm <= 0.5,
    `worst vertex error ${worstRingKm.toFixed(4)} km`);
  check('the prediction layer links each forecast back to the real position',
    links.length === available.length &&
    links.every(l => {
      const row = available.find(r => String(r.wmo) === String(l.wmo));
      if (!row || !l.path || l.path.length < 2) return false;
      const [startLon, startLat] = l.path[0];
      const [endLon, endLat] = l.path[l.path.length - 1];
      return haversineKm(row.prediction.predicted_lat, row.prediction.predicted_lon, endLat, endLon) < 1e-6 &&
        haversineKm(row.lat, row.lon, startLat, startLon) < 1e-6;
    }), `${links.length} links`);

  const unavailable = rows.filter(r => !(r.prediction?.available && r.prediction.predicted_lat != null));
  check('floats without a usable prediction draw neither point nor ring',
    unavailable.every(r => !points.some(p => String(p.wmo) === String(r.wmo)) &&
      !rings.some(g => String(g.wmo) === String(r.wmo))));

  // The real, observed float markers must be untouched by the optional layer.
  const markers = drawn.markers.filter(m => m.kind === 'marker');
  check('real float markers are unchanged by the prediction layer',
    markers.length === rows.length &&
    rows.every(r => markers.some(m => String(m.wmo) === String(r.wmo) &&
      haversineKm(r.lat, r.lon, m.lat, m.lon) < 1e-6)),
    `${markers.length} observed markers`);
  check('predicted points never coincide with a real marker by construction',
    points.every(p => {
      const row = rows.find(r => String(r.wmo) === String(p.wmo));
      return row && (row.lat !== p.lat || row.lon !== p.lon);
    }));

  await toggle.uncheck();
  await page.waitForFunction(() => {
    const layer = document.querySelector('[data-testid="esri-map-view"]')?.__fleetMapView?.view?.map?.layers
      ?.find(l => l.title === 'prediction');
    return layer && layer.graphics.length === 0;
  }, null, { timeout: 20000 });
  const cleared = await readLayers();
  check('switching the layer off clears every prediction graphic and keeps the real markers',
    cleared.graphics.length === 0 && cleared.markers.filter(m => m.kind === 'marker').length === rows.length);

  // The layer's inputs stay prepared while the toggle is off (no re-fetch, no
  // stubbed data) — the renderer, not the model, is what the toggle gates.
  const prepared = await page.getByTestId('esri-map-view').evaluate(el => ({
    points: el.__fleetMapData?.predictions?.points?.length ?? 0,
    enabled: el.__fleetMapData?.predictions?.visible ?? null,
  }));
  check('prediction inputs stay prepared while the layer is off, and off stays off',
    prepared.points === available.length && prepared.enabled === false,
    `prepared=${prepared.points} enabled=${prepared.enabled}`);
  await page.screenshot({ path: path.join(SHOTS, 'prediction-layer-off.png') });

  check('no runtime page errors during the map audit', pageErrors.length === 0, pageErrors.join(' | '));

  fs.writeFileSync(path.join(SHOTS, 'prediction-map-audit.json'), JSON.stringify({
    base: BASE, generated_at: new Date().toISOString(),
    floats: rows.length, available: available.length,
    worst_point_error_m: Number((worstPointKm * 1000).toExponential(3)),
    worst_ring_vertex_error_km: Number(worstRingKm.toFixed(4)),
    rings: ringDetail, checks: results,
  }, null, 2));
  console.log(`\n${results.filter(r => r.passed).length}/${results.length} checks passed; ` +
    `${available.length} predicted points, ${rings.length} rings audited`);
} catch (error) {
  fs.writeFileSync(path.join(SHOTS, 'prediction-map-audit.json'), JSON.stringify({
    base: BASE, generated_at: new Date().toISOString(), error: String(error), checks: results,
  }, null, 2));
  console.error(`\n${results.filter(r => r.passed).length}/${results.length} checks passed; audit aborted`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
