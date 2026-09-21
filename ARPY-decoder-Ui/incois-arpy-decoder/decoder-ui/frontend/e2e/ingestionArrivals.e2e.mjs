/**
 * E2E — incoming-data ingestion → NEW DATA in the Fleet UI (real backend).
 *
 * Simulates ONLY the mechanics of a new arrival (a real raw telemetry file
 * is dropped into the local landing zone — the same DataSource interface
 * the future INCOIS FTP feed will use), then verifies through the REAL
 * backend + REAL browser:
 *
 *   1. new incoming data detected → WMO resolved via real metadata (PTT)
 *   2. normalized record exposed over /api/ingestion/arrivals
 *   3. Fleet UI shows the float with a 🟡 NEW DATA badge (panel + table row)
 *   4. header source pill is honest (LOCAL / DEV SOURCE; never FTP CONNECTED)
 *   5. NO decoder batch is started automatically at any point
 *   6. "View float" selects the float in the Decoder workspace (manual decode)
 *   7. "Mark seen" acknowledges the arrival (badge clears; history kept)
 *
 * Env: MAP_E2E_BASE (default http://127.0.0.1:8000), SHOTS (screenshots dir)
 *      INGEST_ZONE (landing zone; default <repo>/decoder-ui/data/incoming)
 */
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.MAP_E2E_BASE || 'http://127.0.0.1:8000';
const SHOTS = process.env.SHOTS || '/tmp/ingestion-shots';
const ZONE = process.env.INGEST_ZONE || '/home/user/incois-arpy-decoder/decoder-ui/data/incoming';
const REAL_RAW = '/home/user/incois-arpy-decoder/sample_data/uploads/102525_2010-12-15_2901304_000.txt';
const WMO = 2901304;
let failures = 0;
const results = [];
function record(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`);
  if (!ok) failures++;
}
fs.mkdirSync(SHOTS, { recursive: true });

const api = async (p, o) => {
  const r = await fetch(BASE + p, o);
  let body = null;
  try { body = await r.json(); } catch {}
  return { status: r.status, body };
};
const listBatches = async () => (await api('/api/batches')).body || [];

// ---------------------------------------------------------------------
// Setup: a fresh, unique NEW arrival (real file, new name ⇒ new fingerprint)
// ---------------------------------------------------------------------
const runTag = `burst-${Date.now()}`;
const dropDir = path.join(ZONE, '102525');            // PTT identity of WMO 2901304
fs.mkdirSync(dropDir, { recursive: true });
fs.copyFileSync(REAL_RAW, path.join(dropDir, `${runTag}.txt`));
console.log(`dropped arrival: ${dropDir}/${runTag}.txt (real raw telemetry content)`);

const batchesBefore = await listBatches();
const scan = await api('/api/ingestion/scan', { method: 'POST' });
await new Promise((r) => setTimeout(r, 500));
const freshNew = (await api('/api/ingestion/arrivals?state=new')).body || [];
const mine = freshNew.find((a) => a.wmo === WMO);
record('arrival detected + normalized by backend (WMO resolved via real metadata)', !!mine && mine.source_kind === 'local',
  mine ? `wmo=${mine.wmo} platform=${mine.platform} files=${mine.files} src=${mine.source_id}` : 'not found');
record('normalized fields honest (cycle/JULD/coords unset — nothing invented)',
  !!mine && mine.cycle_number === null && mine.juld === null && mine.latitude === null && mine.longitude === null);
const batchesAfterScan = await listBatches();
record('NO decoder batch auto-started by detection', batchesAfterScan.length === batchesBefore.length,
  `batches ${batchesBefore.length} → ${batchesAfterScan.length}`);

// ---------------------------------------------------------------------
// Browser: Fleet UI must show the NEW DATA state
// ---------------------------------------------------------------------
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
await page.goto(BASE, { waitUntil: 'networkidle' });

// Header data-source pill — honest labels only
const pill = page.getByTestId('data-source-pill');
await pill.waitFor({ state: 'visible', timeout: 15000 });
const pillText = (await pill.innerText()).replace(/\s+/g, ' ');
record('header data-source pill present + LOCAL', pillText.includes('LOCAL'), pillText);
record('source labelled as DEV SOURCE in local mode', /DEV SOURCE/i.test(pillText));
record('UI NEVER claims FTP CONNECTED without a real session', !/FTP CONNECTED/i.test(pillText));
const countChip = page.getByTestId('new-data-count');
record('header shows NEW DATA count badge', await countChip.isVisible().catch(() => false),
  (await countChip.innerText().catch(() => '')).trim());

// Go to the Results/Fleet view
await page.getByRole('button', { name: /VIEW RESULTS/i }).click();
await page.waitForTimeout(1500);

// Load the latest completed batch summary (operator flow: Run History →
// LOAD IN RESULTS) so the fleet table renders for the row-badge check.
await page.getByRole('button', { name: /Open Run History/i }).first().click();
await page.waitForTimeout(1200);
await page.getByRole('button', { name: /BATCH SUMMARIES/i }).click();
await page.waitForTimeout(800);
await page.getByRole('button', { name: /LOAD IN RESULTS/i }).first().click();
await page.waitForTimeout(1500);

// Arrivals panel with the float + badge
const panel = page.getByTestId('new-arrivals-panel');
await panel.waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});
record('Incoming-data arrivals panel visible in Fleet view', await panel.isVisible().catch(() => false));
const card = panel.locator(`[data-arrival-wmo="${WMO}"]`).first();
await card.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
const cardText = (await card.innerText().catch(() => '')).replace(/\s+/g, ' ');
record('fleet panel shows WMO + NEW DATA badge', cardText.includes(`WMO ${WMO}`) && cardText.includes('NEW DATA'), cardText.slice(0, 140));
record('panel surfaces real metadata (platform, received time)', cardText.includes('APEX') && /received \d/.test(cardText));
const opaqueNow = await page.getByTestId('opaque-arrivals').innerText().catch(() => '');
record('unidentified source associations are labelled, never assigned a WMO',
  opaqueNow === '' || /unidentified float/i.test(opaqueNow), opaqueNow.slice(0, 110));
await page.screenshot({ path: path.join(SHOTS, '1-new-data-panel.png'), fullPage: false });

// Fleet table row badge
const row = page.locator(`tbody tr:has(td:text-is("${WMO}"))`).first();
const rowBadge = row.getByTestId('row-new-data-badge');
record('fleet TABLE row shows 🟡 NEW DATA badge for the float', await rowBadge.isVisible().catch(() => false));
await page.screenshot({ path: path.join(SHOTS, '2-table-badge.png') });

// View float → decoder workspace (manual decode remains the user's choice)
await card.getByRole('button', { name: /View float/i }).click();
await page.waitForTimeout(1200);
const decoderPreset = await page.locator('select').first().inputValue().catch(() => '');
const onDecoderView = await page.getByRole('button', { name: /DECODE FLOAT/i }).isVisible().catch(() => false);
record('View float opens Decoder workspace with the float selected (decode stays manual)',
  onDecoderView && String(decoderPreset) === String(WMO), `select=${decoderPreset}`);
record('still NO auto decode after View float', (await listBatches()).length === batchesBefore.length);
await page.screenshot({ path: path.join(SHOTS, '3-view-float-decoder.png') });

// Back to Fleet; Mark seen clears the badge (visibility-only ack)
await page.getByRole('button', { name: /VIEW RESULTS/i }).first().click();
await page.waitForTimeout(1000);
const panel2 = page.getByTestId('new-arrivals-panel');
const card2 = panel2.locator(`[data-arrival-wmo="${WMO}"]`).first();
await card2.getByRole('button', { name: /Mark seen/i }).click();
await page.waitForTimeout(1500);
const stillThere = await panel2.locator(`[data-arrival-wmo="${WMO}"]`).first().count();
record('Mark seen clears the NEW DATA card', stillThere === 0);
const apiNew = (await api('/api/ingestion/arrivals?state=new')).body || [];
record('ack persisted server-side (arrival now seen, history kept)',
  !apiNew.some((a) => a.wmo === WMO) &&
  (await api('/api/ingestion/arrivals')).body.some((a) => a.wmo === WMO && a.state === 'seen'));
await page.screenshot({ path: path.join(SHOTS, '4-after-ack.png') });

record('final: batches count unchanged through the whole flow (no auto-decode)',
  (await listBatches()).length === batchesBefore.length);

await browser.close();
console.log(`\n${failures ? failures + ' CHECK(S) FAILED' : 'ALL CHECKS PASSED'} (${results.length} checks)`);
fs.writeFileSync(path.join(SHOTS, 'results.json'), JSON.stringify(results, null, 2));
process.exit(failures ? 1 : 0);
