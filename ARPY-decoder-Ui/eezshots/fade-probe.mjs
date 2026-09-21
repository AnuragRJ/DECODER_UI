// Probe: does headless-shell animate the CSS opacity transition? Samples the
// live computed opacity series right after toggle ON and toggle OFF.
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

async function sample(sel, n, gap) {
  const out = [];
  for (let i = 0; i < n; i++) {
    out.push(await page.evaluate((s) => {
      const el = document.querySelector(s);
      if (!el) return 'x';
      const cs = getComputedStyle(el);
      return cs.opacity + '/' + cs.transitionProperty + '/' + cs.transitionDuration + '/anim=' + el.getAnimations().length;
    }, sel));
    await sleep(gap);
  }
  return out;
}
const toggle = page.locator('[data-testid="eez-toggle"]');
await toggle.click(); // ON
console.log('ON :', JSON.stringify(await sample('[data-eez-layer]', 30, 15)));
await sleep(600);
await toggle.click(); // OFF
console.log('OFF:', JSON.stringify(await sample('[data-eez-layer]', 30, 15)));
await browser.close();
