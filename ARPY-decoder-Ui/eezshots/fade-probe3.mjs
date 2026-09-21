// Probe 3: capture Animation-domain events around EEZ toggle ON/OFF.
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
const seen = new Map();
for (const ev of ['Animation.animationCreated', 'Animation.animationStarted']) {
  cdp.on(ev, (e) => {
    const a = e.animation || {};
    if (!seen.has(a.id)) seen.set(a.id, { ev, type: a.type, dur: a.source?.duration, easing: a.source?.easing, name: a.name });
  });
}
const toggle = page.locator('[data-testid="eez-toggle"]');
seen.clear();
await toggle.click();
await sleep(900);
console.log('ON events:', JSON.stringify(Array.from(seen.values())));
seen.clear();
await toggle.click();
await sleep(900);
console.log('OFF events:', JSON.stringify(Array.from(seen.values())));
await browser.close();
