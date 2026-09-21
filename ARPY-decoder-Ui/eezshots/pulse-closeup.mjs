// Closeup capture: frame the currently-inside float (WMO 2901339, derived at
// runtime from backend truth — never hardcoded for selection) on the maroon
// EEZ region, then take a FULL-viewport screenshot (clipped captures crash
// headless Chromium while SMIL animates) for later PIL cropping.
import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8000';
const OUT = '/tmp/eezshots/pulse-closeup-full.png';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function api(p) {
  const r = await fetch(BASE + '/api' + p);
  if (!r.ok) throw new Error(p + ' -> ' + r.status);
  return r.json();
}

// Backend truth: which WMO is currently inside (same even-odd PIP as app).
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
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function inEez(lon, lat) {
  for (const poly of polys) {
    if (ringIn(poly[0], lon, lat)) {
      let hole = false;
      for (let h = 1; h < poly.length; h++) if (ringIn(poly[h], lon, lat)) { hole = true; break; }
      if (!hole) return true;
    }
  }
  return false;
}
const batch = (await api('/batches'))[0];
let insideWmo = null;
for (const it of batch.items) {
  if (!it.run_id) continue;
  const run = await api(`/runs/${it.run_id}`);
  const cyc = (run.cycles || [])
    .filter((c) => c.latitude != null && c.longitude != null)
    .sort((a, b) => a.cycle_number - b.cycle_number || (a.juld ?? 0) - (b.juld ?? 0));
  if (cyc.length) {
    const last = cyc[cyc.length - 1];
    if (inEez(last.longitude, last.latitude)) { insideWmo = it.wmo; break; }
  }
}
console.log('inside WMO (backend truth):', insideWmo);
if (!insideWmo) throw new Error('no inside float in real data');

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
await page.goto(BASE, { waitUntil: 'domcontentloaded' });
await page.waitForLoadState('networkidle');
await page.locator('button:has-text("DECODE ALL TODAY")').click({ timeout: 10000 });
const completeModalBtn = page.locator('div[role="dialog"] button:has-text("[ View Results ]")');
let usedAlreadyComplete = false;
for (let i = 0; i < 26; i++) {
  if (await completeModalBtn.count()) { usedAlreadyComplete = true; break; }
  await sleep(300);
}
if (usedAlreadyComplete) await completeModalBtn.click();
else {
  await page.waitForSelector('button:has-text("VIEW RESULTS")', { timeout: 600000 });
  await page.locator('button:has-text("VIEW RESULTS")').first().click();
}
await page.waitForSelector('svg[role="img"] g[data-wmo]', { timeout: 60000 });
await page.waitForSelector('[data-testid="eez-layer-control"]', { timeout: 30000 });
await sleep(2500);

// Select the inside float via its fleet-table row (exact-td match), so the
// map frames its trajectory; then EEZ ON + Expand Fleet.
const rowIdx = await page.evaluate((wmo) => {
  const rows = Array.from(document.querySelectorAll('table tbody tr'));
  return rows.findIndex((r) => r.querySelector('td')?.textContent.trim() === String(wmo));
}, insideWmo);
console.log('table row:', rowIdx);
if (rowIdx >= 0) await page.locator('table tbody tr').nth(rowIdx).click();
await sleep(1500);
const toggle = page.locator('[data-testid="eez-toggle"]');
if (!(await toggle.isChecked())) await toggle.click();
await sleep(400);
const expandBtn = page.locator('text=[ Expand Fleet ]');
if (await expandBtn.count()) await expandBtn.first().click();
await sleep(1200);

// Zoom in on the pulsing marker: find its screen position, wheel-zoom there.
const mpos = await page.evaluate((wmo) => {
  const g = document.querySelector(`svg[role="img"] g[data-wmo="${wmo}"]`);
  if (!g) return null;
  const core = g.querySelector('circle[fill="#fbbf24"], circle[fill="#fde047"]');
  const r = (core || g).getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}, insideWmo);
console.log('marker at:', JSON.stringify(mpos));
if (mpos) {
  await page.mouse.move(mpos.x, mpos.y);
  for (let i = 0; i < 6; i++) { await page.mouse.wheel(0, -400); await sleep(280); }
}
await sleep(800);
const mpos2 = await page.evaluate((wmo) => {
  const g = document.querySelector(`svg[role="img"] g[data-wmo="${wmo}"]`);
  if (!g) return null;
  const r = g.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}, insideWmo);
console.log('marker now at:', JSON.stringify(mpos2), 'JSON:' + JSON.stringify(mpos2));
await page.screenshot({ path: OUT });
console.log('saved', OUT);
await browser.close();
