import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
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
await new Promise(r => setTimeout(r, 1000));
const dump = () => page.evaluate(() => {
  const svg = document.querySelector('svg[role="img"]');
  if (!svg) return 'no svg';
  const chain = [];
  let el = svg;
  while (el && chain.length < 8) {
    const bb = el.getBoundingClientRect();
    chain.push(`${el.tagName}.${String(el.className?.baseVal ?? el.className ?? '').slice(0, 60)} = ${Math.round(bb.width)}x${Math.round(bb.height)}`);
    el = el.parentElement;
  }
  return { viewBox: svg.getAttribute('viewBox'), chain };
});
console.log(JSON.stringify(await dump(), null, 1));
await page.getByText('[ Expand Fleet ]').click();
await new Promise(r => setTimeout(r, 1200));
console.log(JSON.stringify(await dump(), null, 1));
await browser.close();
