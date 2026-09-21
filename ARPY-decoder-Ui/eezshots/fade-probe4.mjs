// Probe 4: reproduce check-22 toggle OFF->ON in expanded view; inspect opacity,
// rAF health, and animation events after the ON toggle.
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
let animEvents = [];
cdp.on('Animation.animationStarted', (e) => {
  const a = e.animation || {};
  animEvents.push({ type: a.type, name: a.name, dur: a.source?.duration });
});
const toggle = page.locator('[data-testid="eez-toggle"]');
if (!(await toggle.isChecked())) await toggle.click();
await sleep(800);
const expandBtn = page.locator('text=[ Expand Fleet ]');
if (await expandBtn.count()) await expandBtn.first().click();
await sleep(1000);

async function state(tag) {
  const s = await page.evaluate(() => {
    const q = (sel) => {
      const el = document.querySelector(sel);
      return el ? getComputedStyle(el).opacity : 'x';
    };
    return {
      layer: q('[data-eez-layer]'),
      label: q('[data-eez-label-layer]'),
      alert: q('[data-testid="eez-combined-alert-wrap"]'),
      panels: document.querySelectorAll('[data-testid="eez-combined-alert"]').length,
    };
  });
  const raf = await page.evaluate(() => new Promise((res) => {
    const t0 = performance.now();
    requestAnimationFrame(() => requestAnimationFrame(() => res(Math.round(performance.now() - t0))));
  }));
  console.log(tag, JSON.stringify(s), 'doubleRafMs=' + raf);
}

animEvents = [];
await toggle.click(); // OFF
await sleep(1200);
console.log('OFF events:', JSON.stringify(animEvents));
await state('afterOFF');
animEvents = [];
await toggle.click(); // ON
await sleep(300);
await state('afterON+300ms');
await sleep(900);
console.log('ON events:', JSON.stringify(animEvents));
await state('afterON+1200ms');
await browser.close();
