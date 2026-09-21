// Probe 2: slow CSS transitions via CDP Animation.setPlaybackRate, then sample.
import { chromium } from 'playwright';
const BASE = 'http://127.0.0.1:8000';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
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

const cdp = await page.context().newCDPSession(page);
await cdp.send('Animation.enable');
await cdp.send('Animation.setPlaybackRate', { playbackRate: 0.1 });
console.log('playback slowed to 0.1x');

async function sample(sel, n, gap) {
  const out = [];
  for (let i = 0; i < n; i++) {
    out.push(await page.evaluate((s) => {
      const el = document.querySelector(s);
      return el ? getComputedStyle(el).opacity : 'x';
    }, sel));
    await sleep(gap);
  }
  return out;
}
const toggle = page.locator('[data-testid="eez-toggle"]');
await toggle.click(); // ON
console.log('ON :', JSON.stringify(await sample('[data-eez-layer]', 12, 100)));
await cdp.send('Animation.setPlaybackRate', { playbackRate: 1 });
await sleep(800);
await cdp.send('Animation.setPlaybackRate', { playbackRate: 0.1 });
await toggle.click(); // OFF
console.log('OFF:', JSON.stringify(await sample('[data-eez-layer]', 12, 100)));
await browser.close();
