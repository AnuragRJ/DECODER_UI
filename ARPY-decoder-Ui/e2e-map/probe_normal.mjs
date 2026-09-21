import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1600 } });
await page.goto('http://127.0.0.1:8000', { waitUntil: 'domcontentloaded' });
await page.waitForLoadState('networkidle');
await page.evaluate(async () => {
  await fetch('/api/batch/decode-all', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ wmos: [2901304, 2902201, 2901339, 2902203] }) });
});
await page.waitForFunction(() => !document.body.innerText.includes('DECODING FLOAT'), { timeout: 60000 });
await new Promise(r => setTimeout(r, 800));
await page.getByText('VIEW RESULTS').first().click();
await page.waitForSelector('svg g[data-wmo]', { timeout: 30000 });
await new Promise(r => setTimeout(r, 2500)); // all animations settle
console.log('normal transform:', await page.evaluate(() => document.querySelector('svg[role="img"] g[data-world-transform]')?.getAttribute('transform')));
await page.screenshot({ path: '/tmp/mapshots/normal_settled.png' });
// click FIT chip in the normal band
const band = await page.evaluate(() => {
  const chip = document.querySelector('[data-fit-chip]');
  if (!chip) return null;
  const bb = chip.getBoundingClientRect();
  return { x: bb.x + bb.width / 2, y: bb.y + bb.height / 2 };
});
if (band) { await page.mouse.click(band.x, band.y); await new Promise(r => setTimeout(r, 900)); }
console.log('after FIT:', await page.evaluate(() => document.querySelector('svg[role="img"] g[data-world-transform]')?.getAttribute('transform')));
await page.screenshot({ path: '/tmp/mapshots/normal_fit.png' });
await browser.close();
