// Error Investigation Detail verification — real backend + real dev app.
// 10 cases: results entry, email deep link, log/run/input/output evidence
// actions, run-not-started, multi-error, unavailable root cause (API level),
// and the plain view staying untouched.
import { chromium } from 'playwright';
import fs from 'fs';

const BASE = process.env.INV_E2E_BASE || 'http://127.0.0.1:3000';
const API = process.env.INV_E2E_API || 'http://127.0.0.1:8000';
const SHOTS = process.env.INV_E2E_SHOTS || '/home/user/verify-shots/investigation';
fs.rmSync(SHOTS, { recursive: true, force: true });
fs.mkdirSync(SHOTS, { recursive: true });

const R1 = 'run-6902892-011aef';   // 2 errors, 0 outputs, CONFIGURATION-only events
const R2 = 'run-2901305-399db9';   // 1 error, 2 outputs, DISCOVERY events
const R404 = 'run-2902086-f99ce7'; // no record anywhere
const ROK = 'run-7902408-2a2e88';  // completed, no errors

const results = [];
const ok = (name, cond, extra = '') => {
  results.push([cond ? 'PASS' : 'FAIL', name, extra]);
  console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (extra ? '   ' + extra : ''));
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1657, height: 900 } });

const heading = () => page.locator('h2', { hasText: 'Error Investigation' });
const drawerOpen = () => page.getByText('TECHNICAL EVENT INSPECTOR').count();
const activeFilter = () => page.evaluate(() => {
  const btns = [...document.querySelectorAll('button')].filter((b) =>
    (b.className || '').includes('bg-[#276095]'));
  return btns.map((b) => b.textContent.trim()).join('|');
});
async function waitForPanel(runId) {
  await page.getByText(runId, { exact: false }).first().waitFor({ timeout: 15000 });
  await sleep(400);
}

// --- Case 1: View Result -> Investigate Error --------------------------------
await page.goto(BASE, { waitUntil: 'networkidle' });
await page.locator('[title="Open Persistent Run History"]').click();
await sleep(1000);
await page.getByRole('button', { name: /BATCH SUMMARIES/ }).click();
await sleep(600);
// Load the batch that holds the 6902892 failure, then Investigate that row.
await page.locator('tr', { hasText: 'batch-1789628039-4b81' })
  .getByRole('button', { name: 'LOAD IN RESULTS' }).click();
await sleep(1500);
await page.locator('tr', { hasText: '6902892' }).first()
  .getByRole('button', { name: /INVESTIGATE ERROR/ }).click();
await waitForPanel('run-');
const case1Run = await heading().first().locator('xpath=following-sibling::p[1]').textContent();
ok('1a results Investigate opens the panel', await heading().count() === 1);
const h1 = await heading().first().textContent();
ok('1b panel heads the failed WMO', /WMO \d+/.test(h1 || ''), h1 || '');
for (const label of ['Input', 'Discovery', 'Metadata / Staging', 'Decoder', 'NetCDF', 'RTQC', 'Output']) {
  ok(`1c timeline card "${label}"`, await page.getByText(label, { exact: true }).count() >= 1);
}
ok('1d primary error shown', await page.getByText('Primary error').count() === 1);
ok('1e drawer suppressed while panel open', await drawerOpen() === 0);
await page.screenshot({ path: `${SHOTS}/inv-1-results-investigate.png` });

// --- Case 2: email deep link opens the SAME view ------------------------------
await page.goto(`${BASE}/?run_id=${case1Run.trim()}&focus=error`, { waitUntil: 'networkidle' });
await waitForPanel(case1Run.trim());
const h2 = await heading().first().textContent();
ok('2a deep link opens the panel', await heading().count() === 1);
ok('2b same heading as results entry', h2 === h1, h2 || '');
await page.screenshot({ path: `${SHOTS}/inv-2-email-deeplink.png` });

// --- Case 3: View Decoder Log -> focused log ----------------------------------
await page.getByRole('button', { name: 'View Decoder Log' }).click();
await sleep(600);
ok('3a panel closed', await heading().count() === 0);
ok('3b drawer restored', await drawerOpen() === 1);
ok('3c error focus kept', (await activeFilter()).includes('NOTICES'), await activeFilter());
await page.screenshot({ path: `${SHOTS}/inv-3-decoder-log.png` });

// --- Case 4: View Run -> plain run view ---------------------------------------
await page.goto(`${BASE}/?run_id=${R1}&focus=error`, { waitUntil: 'networkidle' });
await waitForPanel(R1);
await page.getByRole('button', { name: 'View Run' }).click();
await sleep(600);
ok('4a panel closed', await heading().count() === 0);
ok('4b focus cleared to all events', (await activeFilter()).includes('ALL EVENTS'), await activeFilter());
await page.screenshot({ path: `${SHOTS}/inv-4-view-run.png` });

// --- Case 5: View Output gating -----------------------------------------------
ok('5a no View Output without outputs', await page.goto(`${BASE}/?run_id=${R1}&focus=error`, { waitUntil: 'networkidle' }).then(async () => {
  await waitForPanel(R1);
  return await page.getByRole('button', { name: 'View Output' }).count();
}) === 0);
await page.goto(`${BASE}/?run_id=${R2}&focus=error`, { waitUntil: 'networkidle' });
await waitForPanel(R2);
ok('5b View Output present with outputs', await page.getByRole('button', { name: 'View Output' }).count() === 1);
await page.getByRole('button', { name: 'View Output' }).click();
await sleep(600);
ok('5c output modal opens', await page.getByText('ADMT-3.1 OUTPUT DELIVERABLES').count() === 1);
await page.screenshot({ path: `${SHOTS}/inv-5-output.png` });
await page.keyboard.press('Escape');
await sleep(300);

// --- Case 6: View Input gating -------------------------------------------------
await page.goto(`${BASE}/?run_id=${R1}&focus=error`, { waitUntil: 'networkidle' });
await waitForPanel(R1);
ok('6a no View Input without input events', await page.getByRole('button', { name: 'View Input' }).count() === 0);
await page.goto(`${BASE}/?run_id=${R2}&focus=error`, { waitUntil: 'networkidle' });
await waitForPanel(R2);
ok('6b View Input present with input events', await page.getByRole('button', { name: 'View Input' }).count() === 1);
await page.getByRole('button', { name: 'View Input' }).click();
await sleep(600);
ok('6c log opens at the input event', await heading().count() === 0 && await drawerOpen() === 1);
await page.screenshot({ path: `${SHOTS}/inv-6-input.png` });

// --- Case 7: run not started ----------------------------------------------------
await page.goto(`${BASE}/?run_id=${R404}&focus=error`, { waitUntil: 'networkidle' });
await sleep(1000);
ok('7a exact not-started line', await page.getByText('Decoder run not started').count() >= 1);
ok('7b exact run id shown', await page.getByText(R404).count() >= 1);
ok('7c no timeline invented', await page.getByText('Processing timeline').count() === 0);
await page.screenshot({ path: `${SHOTS}/inv-7-not-started.png` });
await page.getByRole('button', { name: 'Back to Results' }).click();
await sleep(800);
ok('7d back to results', await heading().count() === 0);

// --- Case 8: multi-error ---------------------------------------------------------
await page.goto(`${BASE}/?run_id=${R1}&focus=error`, { waitUntil: 'networkidle' });
await waitForPanel(R1);
ok('8a (+1 more) suffix', await page.getByText('(+1 more)').count() >= 1);
await page.getByRole('button', { name: /Show all 2 errors/ }).click();
await sleep(300);
ok('8b full list with primary marked', await page.getByText('primary', { exact: false }).count() >= 1);
await page.screenshot({ path: `${SHOTS}/inv-8-multi-error.png` });

// --- Case 9: unavailable root cause (API level: no errors, no events) -----------
{
  const res = await fetch(`${API}/api/runs/${ROK}/investigation`);
  const inv = await res.json();
  ok('9a completed run investigates gracefully', res.status === 200 && inv.status === 'completed');
  ok('9b root cause unavailable shape', inv.root_cause_available === false && inv.primary_error === '' && inv.error_count === 0);
}

// --- Case 10: plain view untouched ----------------------------------------------
await page.goto(`${BASE}/?run_id=${R1}`, { waitUntil: 'networkidle' });
await sleep(1000);
ok('10a no panel on plain view', await heading().count() === 0);
ok('10b log + drawer render', (await drawerOpen()) === 1);
await page.screenshot({ path: `${SHOTS}/inv-10-plain-view.png` });

const fails = results.filter(([s]) => s === 'FAIL');
console.log(`\n==== ${results.length - fails.length}/${results.length} checks passed ====`);
await browser.close();
if (fails.length) process.exit(1);
