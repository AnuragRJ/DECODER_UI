// Captures visual evidence of the experimental prediction UI (drawer + map layer).
// Read-only: opens the existing Float Status page, toggles the opt-in layer,
// screenshots, and restores the page state. No decoding, no data writes.
// Playwright is resolved from the frontend install (ESM needs the absolute path).
import { chromium } from '/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.FLEET_E2E_BASE || 'http://127.0.0.1:3000';
const SHOTS = process.env.FLEET_E2E_SHOTS || '/home/user/prediction-validation/e2e-shots';
fs.mkdirSync(SHOTS, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1720, height: 1000 } });
page.setDefaultTimeout(30000);
await page.goto(BASE, { waitUntil: 'domcontentloaded' });
await page.getByTitle('Open Dedicated Results & Oceanographic Analysis Workspace').click();
await page.getByRole('button', { name: '[ Float Status ]', exact: true }).click();
await page.getByTestId('float-status-page').waitFor();
await page.waitForFunction(() => document.querySelector('[data-testid="esri-map-view"]')?.__fleetMapView?.view?.ready, null, { timeout: 90000 });

// 1. Drawer block for a float whose prediction is available (trajectory rung).
await page.locator('[data-testid^="fleet-row-"]').first().waitFor();
await page.getByPlaceholder('Search WMO / internal ID…').fill('1902844');
await page.getByTestId('fleet-row-1902844').waitFor();
await page.getByTestId('fleet-row-1902844').click();
await page.getByTestId('detail-section-prediction').waitFor();
await page.getByTestId('detail-section-prediction').screenshot({ path: path.join(SHOTS, '04-drawer-prediction-1902844.png') });

// Read back the drawer rows that explain the empirical uncertainty and the
// trajectory history behind the method, and confirm the exact required wording.
const drawerRows = await page.getByTestId('detail-section-prediction').evaluate(el => {
  const out = {};
  el.querySelectorAll('[data-detail-label]').forEach(node => {
    out[node.dataset.detailLabel] = (node.querySelectorAll('span')[1]?.textContent ?? '').trim();
  });
  return out;
});
const radiusNote = (await page.getByTestId('prediction-radius-note').textContent()).replace(/\s+/g, ' ').trim();
const textOk = {
  r50: drawerRows['R50 (empirical)'] === 'R50: ' + drawerRows['R50 (empirical)']?.match(/R50: ([\d.]+) km/)?.[1] +
    ' km — 50% of historical validation prediction errors were within this distance.',
  r90: drawerRows['R90 (empirical)'] === 'R90: ' + drawerRows['R90 (empirical)']?.match(/R90: ([\d.]+) km/)?.[1] +
    ' km — 90% of historical validation prediction errors were within this distance.',
  caveat: radiusNote.startsWith('These are empirical uncertainty radii calculated from historical validation errors, ' +
    'not a probability guarantee for this individual prediction.'),
  noProbabilityClaim: !/90\s?%\s?(confidence|probability|probable|chance)/i.test(JSON.stringify(drawerRows) + radiusNote),
};
await page.screenshot({ path: path.join(SHOTS, '04b-drawer-full.png') });
await page.getByTitle('Close detail', { exact: true }).click();
await page.getByRole('button', { name: 'Clear', exact: true }).click();

// 2. Opt-in prediction layer, enabled.
const toggle = page.getByTestId('prediction-layer-toggle');
const label = await toggle.evaluate(el => el.parentElement?.textContent?.trim());
await toggle.check();
await page.waitForFunction(() => {
  const el = document.querySelector('[data-testid="esri-map-view"]');
  const layer = el?.__fleetMapView?.view.map.layers.find(l => l.title === 'prediction');
  return el?.__fleetMapData?.predictions?.visible === true && (layer?.graphics.length ?? 0) > 0;
}, null, { timeout: 60000 });
await page.waitForFunction(() => {
  const view = document.querySelector('[data-testid="esri-map-view"]')?.__fleetMapView?.view;
  return view?.stationary && !view.updating;
}, null, { timeout: 60000 });
await page.getByRole('button', { name: 'FIT', exact: true }).click();
await page.waitForTimeout(2500);
await page.screenshot({ path: path.join(SHOTS, '05-map-prediction-layer-on.png') });
const counts = await page.getByTestId('esri-map-view').evaluate(el => {
  const layer = el.__fleetMapView.view.map.layers.find(l => l.title === 'prediction');
  const kinds = layer.graphics.toArray().map(g => g.attributes?.kind);
  return { diamonds: kinds.filter(k => k === 'prediction').length, rings: kinds.filter(k => k === 'prediction-ring').length, links: kinds.filter(k => k === 'prediction-link').length };
});
await page.screenshot({ path: path.join(SHOTS, '06-map-prediction-layer-off.png') });
await toggle.uncheck();
fs.writeFileSync(path.join(SHOTS, 'drawer-audit.json'), JSON.stringify({ drawerRows, radiusNote, textOk }, null, 2));
console.log(JSON.stringify({ toggleLabel: label, counts, textOk, drawerRows }, null, 2));
await browser.close();
