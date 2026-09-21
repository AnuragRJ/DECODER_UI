// Evidence capture for the anchor finding (Stage-0 report finding #8).
//
//   FLEET_E2E_BASE=http://127.0.0.1:3000 node audit/capture_anchor_case.mjs
//
// Read-only: opens Float Status, selects the float whose prediction anchor is
// much older than its displayed position, screenshots the drawer, then enables
// the opt-in prediction layer and screenshots the map so the dashed connector
// length is visible. Restores the toggle. No decoding, no writes to the runtime.
import { chromium } from '/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.FLEET_E2E_BASE || 'http://127.0.0.1:3000';
const SHOTS = process.env.FLEET_E2E_SHOTS || '/home/user/prediction-validation/e2e-shots';
const WMO = process.env.ANCHOR_WMO || '2901350';
fs.mkdirSync(SHOTS, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1720, height: 1000 } });
page.setDefaultTimeout(30000);

const payload = await (await fetch(`${BASE}/api/fleet-status`)).json();
const row = payload.floats.find(r => String(r.wmo) === WMO);
if (!row) throw new Error(`${WMO} is not in the monitored fleet`);
const p = row.prediction;

await page.goto(BASE, { waitUntil: 'domcontentloaded' });
await page.getByTitle('Open Dedicated Results & Oceanographic Analysis Workspace').click();
await page.getByRole('button', { name: '[ Float Status ]', exact: true }).click();
await page.getByTestId('float-status-page').waitFor();
await page.waitForFunction(() => document.querySelector('[data-testid="esri-map-view"]')?.__fleetMapView?.view?.ready, null, { timeout: 90000 });
await page.locator('[data-testid^="fleet-row-"]').first().waitFor();
await page.getByPlaceholder('Search WMO / internal ID…').fill(WMO);
await page.getByTestId(`fleet-row-${WMO}`).waitFor();
await page.getByTestId(`fleet-row-${WMO}`).click();
await page.getByTestId('detail-section-prediction').waitFor();
await page.getByTestId('detail-section-prediction').screenshot({ path: path.join(SHOTS, `anchor-${WMO}-drawer.png`) });

const rows = await page.getByTestId('detail-section-prediction').evaluate(el => {
  const out = {};
  el.querySelectorAll('[data-detail-label]').forEach(node => {
    out[node.dataset.detailLabel] = (node.querySelectorAll('span')[1]?.textContent ?? '').trim();
  });
  return out;
});

// Map: enable the layer, fit, and measure the drawn connector for this float.
await page.getByTitle('Close detail', { exact: true }).click();
const toggle = page.getByTestId('prediction-layer-toggle');
await toggle.check();
await page.waitForFunction(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const layer = el?.__fleetMapView?.view.map.layers.find(l => l.title === 'prediction');
  return (layer?.graphics.length ?? 0) > 0;
}, null, { timeout: 60000 });
await page.getByRole('button', { name: 'FIT', exact: true }).click();
await page.waitForTimeout(3000);
const measured = await page.getByTestId('esri-map-view').evaluate((el, wmo) => {
  const layer = el.__fleetMapView.view.map.layers.find(l => l.title === 'prediction');
  const FAR = 6371.0088;
  const rad = d => (d * Math.PI) / 180;
  const gc = (la1, lo1, la2, lo2) => {
    const a = Math.sin(rad(la2 - la1) / 2) ** 2 + Math.cos(rad(la1)) * Math.cos(rad(la2)) * Math.sin(rad(lo2 - lo1) / 2) ** 2;
    return 2 * FAR * Math.asin(Math.min(1, Math.sqrt(a)));
  };
  const link = layer.graphics.toArray().find(g => g.attributes?.kind === 'prediction-link' && String(g.attributes?.wmo) === wmo);
  const dot = layer.graphics.toArray().find(g => g.attributes?.kind === 'prediction' && String(g.attributes?.wmo) === wmo);
  if (!link) return null;
  const [[x1, y1], [x2, y2]] = [link.geometry.paths[0][0], link.geometry.paths[0][link.geometry.paths[0].length - 1]];
  return {
    drawnLinkKm: Number(gc(y1, x1, y2, x2).toFixed(1)),
    predictedPoint: [dot.geometry.latitude, dot.geometry.longitude],
    from: [y1, x1], to: [y2, x2],
  };
}, WMO);
await page.screenshot({ path: path.join(SHOTS, `anchor-${WMO}-map.png`) });
await toggle.uncheck();

const evidence = {
  generated_at: new Date().toISOString(),
  base: BASE,
  wmo: Number(WMO),
  displayed_position: [row.lat, row.lon],
  last_profile_iso: row.last_profile_iso,
  data_status: row.data_status,
  prediction: {
    issued_from_iso: p.issued_from_iso,
    issued_from_position: p.issued_from_position,
    predicted: [p.predicted_lat, p.predicted_lon],
    method: p.method,
    r50_km: p.r50_km,
    r90_km: p.r90_km,
    issues: p.issues,
  },
  drawer_rows: rows,
  map: measured,
};
fs.writeFileSync(path.join(SHOTS, `anchor-${WMO}-evidence.json`), JSON.stringify(evidence, null, 2));
console.log(JSON.stringify(evidence, null, 2));
await browser.close();
