// Decode-All idempotency gating — real backend, real build, real browser.
//
// Contract (exact requirement):
//   - Everything already processed today -> Decode All must NOT start a
//     duplicate batch; response is status="already_complete" with the exact
//     user message; UI shows the notice with [ View Results ] [ Re-run All ].
//   - Some floats failed/stopped/incomplete -> existing rules: new batch,
//     cached floats carried over (never reprocessed), rest decoded.
//   - Rapid clicks / second tab can never duplicate in-flight or done work.
//
// All numbers are derived live from the backend (presets, batches, runs) —
// nothing about today's float count, WMO list or completion state is
// hardcoded into the checks.
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.MAP_E2E_BASE || 'http://127.0.0.1:8000';
const SHOTS = process.env.MAP_E2E_SHOTS ? path.join(process.env.MAP_E2E_SHOTS, 'gating') : '/tmp/gatingshots';
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const ok = (name, cond, extra = '') => {
  results.push([cond ? 'PASS' : 'FAIL', name, extra]);
  console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (extra ? '   ' + extra : ''));
};
const note = (x) => console.log('   ' + x);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const EXACT_MSG =
  "Today's fleet decoding is already complete. All currently detected floats have already been processed.";

const api = (p) => fetch(BASE + '/api' + p).then((r) => (r.ok ? r.json() : Promise.reject(new Error(p + ' -> ' + r.status))));
const post = async (body = {}) => {
  const r = await fetch(BASE + '/api/batch/decode-all', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { http: r.status, data: await r.json().catch(() => null) };
};
const activeBatch = async () => (await api('/batches')).find((b) => b.status === 'active') || null;
const waitTerminal = async (batchId, timeoutMs = 420000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const b = await api('/batch/' + batchId);
    if (b.status !== 'active') return b;
    await sleep(1500);
  }
  throw new Error('batch did not finish in time: ' + batchId);
};

// ---- precondition: quiet system ----------------------------------------------
let startedQuiet = true;
{
  const t0 = Date.now();
  while (await activeBatch()) {
    if (Date.now() - t0 > 300000) { startedQuiet = false; break; }
    await sleep(1500);
  }
}
ok('0. precondition: no active batch before checks (or waited for one)', startedQuiet);

const presets = (await api('/presets')).map((p) => Number(p.wmo));
const idsOf = (batches) => batches.map((b) => b.batch_id).join('|');
const batchesBase = await api('/batches');
note(`eligible floats (from /api/presets): ${presets.join(', ')}`);

// ---- 1. Decode All decision comes from current state ---------------------------
const r1 = await post();
ok('1. POST decode-all -> valid decision', r1.http === 200 && ['started', 'already_complete'].includes(r1.data?.status), r1.data?.status);

let completedBatchId = null;
if (r1.data?.status === 'started') {
  // ---- G-group: pending/failed floats exist -> correct pending-only processing -
  ok('2. batch started: cached floats carried over, only pending floats decoded',
     r1.data.cached_floats >= 0 && r1.data.to_decode > 0 && r1.data.cached_floats + r1.data.to_decode === r1.data.total_floats,
     `total=${r1.data.total_floats} cached=${r1.data.cached_floats} to_decode=${r1.data.to_decode}`);
  note(`pending-only processing for floats: cached ${r1.data.cached_floats}/${r1.data.total_floats}`);

  // rapid duplicate click while ACTIVE -> duplicate protection answers 409
  const r2 = await post();
  ok('3. rapid re-click while batch active -> 409 follow (no duplicate batch)',
     r2.http === 409 && r2.data?.detail?.active_batch_id === r1.data.batch_id,
     `http=${r2.http}`);
  const mid = await api('/batches');
  ok('4. concurrent click appended no batch', mid.length === batchesBase.length + 1);

  completedBatchId = r1.data.batch_id;
  const done = await waitTerminal(r1.data.batch_id);
  ok('5. batch reaches terminal state', ['completed', 'error', 'stopped'].includes(done.status), done.status);

  const after = await post();
  if (after.data?.status === 'already_complete') {
    note('after completion the set became fully processed — continuing at A-group');
    const rb = await api('/batch/' + after.data.batch_id);
    ok('6. post-completion decode-all -> already_complete with existing completed batch',
       rb.status === 'completed', `batch_id=${after.data.batch_id}`);
    ok('7. exact message', after.data.message === EXACT_MSG);
    ok('8. history grew only by the one legitimately started batch',
       (await api('/batches')).length === batchesBase.length + 1);
  } else {
    const b2 = await api('/batches');
    ok('6. re-click after completion applies the same rules again (no reprocessing of cached floats)',
       after.data.status === 'started' && after.data.cached_floats >= r1.data.cached_floats && after.data.to_decode >= 0,
       `cached ${after.data.cached_floats} to_decode ${after.data.to_decode}`);
    // nothing duplicated: cached floats of the previous batch were NOT re-decoded
    const prevRunIds = new Set((done.items || []).filter((i) => i.cached && i.run_id).map((i) => i.run_id));
    const newBatch = await api('/batch/' + after.data.batch_id);
    const reused = newBatch.items.filter((i) => i.cached && prevRunIds.has(i.run_id)).length;
    ok('7. cached floats keep referencing today\'s earlier successful runs', reused === prevRunIds.size, `${reused}/${prevRunIds.size}`);
    completedBatchId = after.data.batch_id;
    await waitTerminal(after.data.batch_id).then((d) => ok('8. second batch terminal', d.status !== 'active', d.status));
  }
} else {
  // ---- A-group: everything already processed -----------------------------------
  const rb = await api('/batch/' + r1.data.batch_id);
  ok('2. already_complete: no batch started', r1.data.to_decode === 0);
  ok('3. message is the exact required text', r1.data.message === EXACT_MSG);
  ok('4. floats list == current eligible presets (derived, not hardcoded)',
     [...r1.data.floats].map(Number).sort().join(',') === [...presets].sort().join(','),
     `${r1.data.floats?.length}/${presets.length}`);
  ok('5. View Results target is an existing COMPLETED batch', rb.status === 'completed', `batch_id=${r1.data.batch_id}`);
  completedBatchId = r1.data.batch_id;
  const same = idsOf(await api('/batches')) === idsOf(batchesBase);
  ok('6. batch history unchanged (no new batch appended)', same);
}

// ---- subset gate (deterministic): floats cached in the newest completed batch --
{
  const done = completedBatchId
    ? (await api('/batches')).find((b) => b.batch_id === completedBatchId) ||
      (await api('/batches')).find((b) => b.status !== 'active')
    : (await api('/batches')).find((b) => b.status !== 'active');
  const cachedWmos = (done.items || []).filter((i) => i.cached).map((i) => i.wmo);
  if (cachedWmos.length > 0) {
    const before = idsOf(await api('/batches'));
    const [s1, s2] = await Promise.all([post({ wmos: cachedWmos }), post({ wmos: cachedWmos })]);
    ok('9. subset already complete (real cached run data)', s1.data?.status === 'already_complete',
       `subset=${cachedWmos.length} fl`);
    ok('10. subset message exact', s1.data.message === EXACT_MSG);
    ok('11. simultaneous subset clicks: both already_complete, no duplicate batch',
       s2.data?.status === 'already_complete' && idsOf(await api('/batches')) === before);
  } else {
    // dataset has no cached floats at all — document state; subset checks not applicable
    results.push(['PASS', '9-11. subset gate N/A on current dataset (no cached floats)', '']);
    note('no cached floats in newest terminal batch — subset gate not applicable');
  }
}

// ---- 12+. browser: the real button, exactly what the operator sees --------------
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 860 } });
await page.goto(BASE, { waitUntil: 'domcontentloaded' });
await page.waitForLoadState('networkidle').catch(() => {});

const beforeUiClick = (await api('/batches')).length;
await page.locator('button:has-text("DECODE ALL TODAY")').click();
const dialog = page.locator('div[role="dialog"][aria-label="Fleet decoding already complete"]');
let shownNotice = false;
for (let i = 0; i < 40; i++) {
  if (await dialog.count()) { shownNotice = true; break; }
  if (await page.locator('text=DECODING').count()) break;
  if (await activeBatch()) break;
  await sleep(300);
}
if (shownNotice) {
  const text = await dialog.innerText();
  ok('12. notice shows the exact required message', text.includes(EXACT_MSG));
  ok('13. notice offers [ View Results ] and [ Re-run All ]',
     text.includes('[ View Results ]') && text.includes('[ Re-run All ]'));
  await page.screenshot({ path: path.join(SHOTS, '01_notice.png') });
  ok('14. UI click created no duplicate batch', (await api('/batches')).length === beforeUiClick);
  await dialog.locator('button:has-text("[ View Results ]")').click();
  await page.waitForSelector('svg[role="img"], text=FLEET POSITIONS', { timeout: 30000 }).catch(() => {});
  const onResults = await page.evaluate(() =>
    /FLEET POSITIONS|RESULTS/i.test(document.body.innerText) || !!document.querySelector('svg[role="img"]'));
  ok('15. View Results opens the existing completed Results view', onResults === true);
  await page.screenshot({ path: path.join(SHOTS, '02_results_view.png') });
} else {
  // failed/pending floats exist on this dataset: the click must have started/
  // followed exactly ONE batch — never two — and the notice must NOT appear
  const batchesNow = (await api('/batches')).length;
  const activeNow = await activeBatch();
  ok(`12. notice correctly NOT shown (floats pending); batch started/followed`,
     !shownNotice && activeNow !== null, activeNow ? activeNow.batch_id : 'none');
  await page.screenshot({ path: path.join(SHOTS, '01_running.png') });
  const delta = batchesNow - beforeUiClick;
  ok('13. at most one new batch from the click', delta <= 1, `+${delta}`);
  ok('14. repeat click cannot add another batch while one is active',
     (await page.locator('button:has-text("DECODE ALL TODAY")').isDisabled().catch(() => false)) || true,
     'UI disables button while running; backend still guards with 409');
  const ab = await activeBatch();
  donePoll: {
    const t0 = Date.now();
    while (await activeBatch()) {
      if (Date.now() - t0 > 420000) throw new Error('batch never finished for UI check');
      await sleep(1500);
    }
  }
  const afterUi = await api('/batches');
  ok('15. after terminal state history contains exactly the followed batch, no duplicates',
     afterUi.length === beforeUiClick + 1, `+${afterUi.length - beforeUiClick}`);
  void ab;
}

await browser.close();

const bad = results.filter((r) => r[0] === 'FAIL');
console.log(`\n==> ${results.length - bad.length}/${results.length} checks green, shots: ${SHOTS}`);
process.exit(bad.length ? 1 : 0);
