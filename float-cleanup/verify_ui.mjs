// Post-cleanup UI verification: float selection list + Float Status fleet rows.
// Real dev app (vite :3000) + real backend (:8000). No mocks.
import { chromium } from '/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/frontend/node_modules/playwright/index.mjs';
import fs from 'fs';

const BASE = process.env.CLEANUP_E2E_BASE || 'http://127.0.0.1:3000';
const SHOTS = '/home/user/float-cleanup/after';
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const check = (name, cond, extra = '') => {
  results.push({ name, pass: !!cond, extra });
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${name}${extra ? '   ' + extra : ''}`);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
const pageErrors = [];
page.on('pageerror', (e) => pageErrors.push(String(e)));

await page.goto(BASE, { waitUntil: 'networkidle' });

// --- 1. Header float selector (the Float/input selection UI) ---
const select = page.locator('select[aria-label="Select Float Preset"]');
await select.waitFor({ timeout: 30000 });
const options = await select.locator('option').allTextContents();
const values = await select.locator('option').evaluateAll((els) => els.map((e) => e.value));
check('float selector rendered', options.length > 0, `${options.length} options`);
check('selector has 30 floats', options.length === 30, `got ${options.length}`);
check('removed float 6902892 absent from selector', !options.join('|').includes('6902892'));
check('removed float 6903014 absent from selector', !options.join('|').includes('6903014'));
check('no Coriolis/ARVOR_D demo entry remains',
  !options.some((o) => /6902892|6903014/.test(o)),
  options.slice(0, 3).join(' / '));

// The currently selected preset must still be a real INCOIS float.
const selectedText = await select.locator('option:checked').textContent().catch(() => null);
check('a remaining float is selected by default', !!selectedText && !/690/.test(selectedText), selectedText || '');

// Left panel shows the selected preset's input path — must not be a decArgo_demo path.
const bodyText = await page.locator('body').innerText();
check('no decArgo_demo path anywhere on the page', !/decArgo_demo/.test(bodyText));
check('no Coriolis-container path anywhere on the page', !/Coriolis-data-processing-chain/.test(bodyText));
check('no removed WMO rendered on the decoder view', !/6902892|6903014/.test(bodyText));
await page.screenshot({ path: `${SHOTS}/01-decoder-view.png` });

// --- 2. Float Status page ---
await page.getByTitle('Open Dedicated Results & Oceanographic Analysis Workspace').click();
await page.waitForTimeout(1200);
await page.getByRole('button', { name: '[ Float Status ]', exact: true }).click();
await page.getByTestId('float-status-page').waitFor({ timeout: 60000 });
await page.waitForFunction(() => document.querySelectorAll('[data-testid^="fleet-row-"]').length > 0, null, { timeout: 60000 });

const rows = [];
const readPage = async () => rows.push(...await page.locator('[data-testid^="fleet-row-"]').evaluateAll((els) =>
  els.map((e) => e.getAttribute('data-testid').replace('fleet-row-', ''))));
await readPage();
for (const sel of ['Next page']) {
  let guard = 0;
  while (guard++ < 10) {
    const next = page.getByTitle(sel, { exact: true });
    if (!(await next.count()) || !(await next.isEnabled())) break;
    const before = rows.length;
    await next.click();
    await page.waitForTimeout(700);
    await readPage();
    if (rows.length === before) break;
  }
}
check('Float Status renders 30 rows', rows.length === 30, `got ${rows.length}`);
check('6902892 row absent', !rows.includes('6902892'));
check('6903014 row absent', !rows.includes('6903014'));

const metrics = await page.getByTestId('fleet-status-metrics').innerText();
check('metrics page has no removed WMO', !/6902892|6903014/.test(metrics));
const apiSummary = await (await page.request.get(BASE + '/api/fleet-status')).json();
check('API summary reports 30 floats and 0 NO DATA',
  apiSummary.summary.total === 30 && apiSummary.summary.no_data === 0,
  JSON.stringify(apiSummary.summary).slice(0, 160));

const pageText = await page.getByTestId('float-status-page').innerText();
check('removed WMOs absent from Float Status page', !/6902892|6903014/.test(pageText));
check('banned wording still absent', !/Last Communication|No Transmission|\bdead\b/i.test(pageText));
await page.screenshot({ path: `${SHOTS}/02-float-status.png`, fullPage: true });

// Filter by the removed WMO must return nothing.
await page.getByPlaceholder('Search WMO / internal ID…').fill('6902892');
await page.waitForTimeout(600);
const filtered = await page.locator('[data-testid^="fleet-row-"]').count();
check('searching 6902892 yields zero rows', filtered === 0, `${filtered} rows`);
await page.getByPlaceholder('Search WMO / internal ID…').fill('2901328');
await page.waitForTimeout(600);
const filtered2 = await page.locator('[data-testid^="fleet-row-"]').count();
check('searching a remaining float still works', filtered2 === 1, `${filtered2} rows`);
await page.screenshot({ path: `${SHOTS}/03-filter-remaining-float.png` });

check('no page errors', pageErrors.length === 0, pageErrors.join('; '));

fs.writeFileSync(`${SHOTS}/ui-verification.json`, JSON.stringify({
  base: BASE, options, rows, metrics: metrics.split('\n'), results,
}, null, 2));
await browser.close();

const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
