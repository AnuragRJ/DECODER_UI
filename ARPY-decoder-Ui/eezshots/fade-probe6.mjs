// Probe 6: capture instrumented hook logs around OFF->ON in expanded view.
import { chromium } from 'playwright';
const BASE = 'http://127.0.0.1:8000';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const logs = [];
page.on('console', (m) => { if (m.text().startsWith('[fade]')) logs.push(m.text()); });
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
const toggle = page.locator('[data-testid="eez-toggle"]');
if (!(await toggle.isChecked())) await toggle.click();
await sleep(800);
const expandBtn = page.locator('text=[ Expand Fleet ]');
if (await expandBtn.count()) await expandBtn.first().click();
await sleep(1000);
logs.length = 0;
console.log('--- OFF ---');
await toggle.click();
await sleep(1200);
console.log('--- ON ---');
await toggle.click();
await sleep(1500);
for (const l of logs.slice(-46)) console.log(l);
await browser.close();
