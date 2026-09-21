import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
page.on('console', m => { const t = m.text(); if (t.includes('autoframe') || t.includes('ZUSTAND')) console.log('LOG:', t); });
page.on('pageerror', e => console.log('PAGEERROR:', String(e).slice(0, 300)));
await page.goto('http://127.0.0.1:8000', { waitUntil: 'domcontentloaded' });
await page.waitForLoadState('networkidle');
await page.evaluate(async () => {
  await fetch('/api/batch/decode-all', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ wmos: [2901304, 2902201, 2901339, 2902203] }),
  });
});
await page.waitForFunction(() => !document.body.innerText.includes('DECODING FLOAT'), { timeout: 60000 });
await new Promise(r => setTimeout(r, 800));
await page.getByText('VIEW RESULTS').first().click();
await page.waitForSelector('svg g[data-wmo]', { timeout: 30000 });
await page.getByText('[ Expand Fleet ]').click();
await new Promise(r => setTimeout(r, 900));
console.log('markers:', await page.locator('svg[role="img"] g[data-wmo]').count());
await page.evaluate(() => {
  const g = document.querySelector('svg g[data-wmo="2901304"]');
  g.dispatchEvent(new MouseEvent('click', { bubbles: true }));
});
await new Promise(r => setTimeout(r, 1800));
console.log('transform after select:', await page.evaluate(() => document.querySelector('svg[role="img"] g[data-world-transform]')?.getAttribute('transform')));
await browser.close();
