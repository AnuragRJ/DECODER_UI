// Stage-1 live evidence capture.
//
//   FLEET_E2E_BASE=http://127.0.0.1:3000 node audit/capture_stage1_case.mjs
//
// Requires the API to be serving Stage 1 (PREDICTION_CYCLE_STEP=window with the
// candidate artefact present). Read-only: it opens Float Status, selects a float
// whose payload says predictor_stage = "stage1", records the prediction block's
// rendered rows, screenshots the drawer, enables the opt-in prediction layer and
// screenshots the map, then restores the toggle. No decoding, no runtime writes.
//
// The point of this capture is the Stage-0/Stage-1 distinction during validation:
// the drawer must name the active stage, show the cycle-scale step it used, state
// that Stage-0 remains the shipped baseline, and quote Stage-1's own R50/R90.
import { chromium } from '/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.FLEET_E2E_BASE || 'http://127.0.0.1:3000';
const SHOTS = process.env.FLEET_E2E_SHOTS || '/home/user/prediction-validation/e2e-shots';
fs.mkdirSync(SHOTS, { recursive: true });

const payload = await (await fetch(`${BASE}/api/fleet-status`)).json();
const stageCounts = payload.floats.reduce((acc, r) => {
  const key = r.prediction?.predictor_stage ?? 'none';
  acc[key] = (acc[key] || 0) + 1;
  return acc;
}, {});
const row = payload.floats.find(r => r.prediction?.predictor_stage === 'stage1');
if (!row) {
  throw new Error(`no float is serving Stage 1 (stages: ${JSON.stringify(stageCounts)}); is PREDICTION_CYCLE_STEP=window set on the API?`);
}
const p = row.prediction;
const WMO = String(row.wmo);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1720, height: 1000 } });
page.setDefaultTimeout(30000);

await page.goto(BASE, { waitUntil: 'domcontentloaded' });
await page.getByTitle('Open Dedicated Results & Oceanographic Analysis Workspace').click();
await page.getByRole('button', { name: '[ Float Status ]', exact: true }).click();
await page.getByTestId('float-status-page').waitFor();
await page.waitForFunction(() => document.querySelector('[data-testid="esri-map-view"]')?.__fleetMapView?.view?.ready, null, { timeout: 90000 });
await page.getByPlaceholder('Search WMO / internal ID…').fill(WMO);
await page.getByTestId(`fleet-row-${WMO}`).waitFor();
await page.getByTestId(`fleet-row-${WMO}`).click();
const section = page.getByTestId('detail-section-prediction');
await section.waitFor();

const rows = await section.evaluate(el => {
  const out = {};
  el.querySelectorAll('[data-detail-label]').forEach(node => {
    out[node.dataset.detailLabel] = (node.querySelectorAll('span')[1]?.textContent ?? '').trim();
  });
  return out;
});
const stageNote = await section.getByTestId('prediction-stage-note').textContent();
await section.screenshot({ path: path.join(SHOTS, `stage1-${WMO}-drawer.png`) });

// the opt-in prediction layer, so the Stage-1 rings drawn on the map are captured.
// The drawer overlay covers the layer control, so close the drawer first.
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
await page.getByTestId('esri-map-view').screenshot({ path: path.join(SHOTS, `stage1-${WMO}-map.png`) });
const rings = await page.getByTestId('esri-map-view').evaluate((el, wmo) => {
  const layer = el.__fleetMapView.view.map.layers.find(l => l.title === 'prediction');
  const kinds = layer.graphics.toArray()
    .filter(g => String(g.attributes?.wmo) === wmo)
    .map(g => g.attributes?.kind);
  return { kinds, graphics: layer.graphics.length };
}, WMO);
await toggle.uncheck();
await browser.close();

const evidence = {
  captured_at: new Date().toISOString(),
  base: BASE,
  wmo: Number(WMO),
  fleet_stage_counts: stageCounts,
  payload: {
    predictor_stage: p.predictor_stage,
    predictor_stage_label: p.predictor_stage_label,
    method: p.method,
    method_label: p.method_label,
    fallback_rung: p.fallback_rung,
    validation_samples: p.validation_samples,
    validation_source: p.validation_source,
    r50_km: p.r50_km,
    r90_km: p.r90_km,
    step_basis: p.step_basis,
    step_span_days: p.step_span_days,
    step_ratio: p.step_ratio,
    step_cycles: p.step_cycles,
    target_time_iso: p.target_time_iso,
    prediction_horizon_days: p.prediction_horizon_days,
    issued_from_iso: p.issued_from_iso,
  },
  drawer_rows: rows,
  stage_note: (stageNote || '').trim().replace(/\s+/g, ' '),
  map_point_keys: rings,
  checks: {
    stage_row_names_stage1: rows['Predictor stage'] === p.predictor_stage_label,
    step_basis_row_present: typeof rows['Cycle-scale step basis'] === 'string' && rows['Cycle-scale step basis'].length > 0,
    step_basis_matches_payload: (rows['Cycle-scale step basis'] || '').startsWith(p.step_basis || '\u0000'),
    note_keeps_stage0_as_baseline: /Stage-0 \(last-hop step\) remains the shipped baseline/.test((stageNote || '')),
    note_denies_radius_reuse: /R50\/R90 are not reused here/.test((stageNote || '')),
    r50_row_is_stage1_radius: rows['R50 (empirical)'] === `R50: ${Number(p.r50_km).toFixed(1)} km — 50% of historical validation prediction errors were within this distance.`,
    r90_row_is_stage1_radius: rows['R90 (empirical)'] === `R90: ${Number(p.r90_km).toFixed(1)} km — 90% of historical validation prediction errors were within this distance.`,
    samples_row_matches_payload: rows['Validation Sample Count'] === String(p.validation_samples),
  },
};
fs.writeFileSync(path.join(SHOTS, `stage1-${WMO}-evidence.json`), JSON.stringify(evidence, null, 2));
const failed = Object.entries(evidence.checks).filter(([, ok]) => !ok).map(([k]) => k);
console.log(JSON.stringify({ wmo: WMO, fleet_stage_counts: stageCounts, checks: evidence.checks }, null, 2));
if (failed.length) {
  console.error(`FAILED checks: ${failed.join(', ')}`);
  process.exit(1);
}
console.log(`Stage-1 capture OK -> ${SHOTS}/stage1-${WMO}-{drawer.png,map.png,evidence.json}`);
