import { chromium } from '/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 950 } });
const errors = [];
const failedRequests = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('requestfailed', r => failedRequests.push({url:r.url(), error:r.failure()?.errorText}));
let exit = 0;
try {
  await page.goto('http://127.0.0.1:3000/', { waitUntil: 'domcontentloaded' });
  await page.getByTitle('Open Dedicated Results & Oceanographic Analysis Workspace').waitFor({timeout:30000});
  console.log('PASS root UI rendered');
  await page.getByTitle('Open Dedicated Results & Oceanographic Analysis Workspace').click();
  await page.getByRole('button', {name:'[ Float Status ]'}).click();
  await page.getByTestId('float-status-page').waitFor();
  console.log('PASS Results → Float Status navigation');
  await page.getByTestId('esri-map-view').waitFor({timeout:30000});
  console.log('PASS ArcGIS map container mounted (the repository fleet E2E still expects an SVG)');
  await page.waitForFunction(() => {
    const h = document.querySelector('[data-testid="esri-map-view"]')?.__fleetMapView;
    return h?.view?.ready && !h.view.updating;
  }, null, {timeout:60000});
  const state = await page.evaluate(() => {
    const el=document.querySelector('[data-testid="esri-map-view"]');
    const view=el.__fleetMapView.view;
    return {ready:view.ready, updating:view.updating, basemap:view.map.basemap?.id,
      canvasCount:el.querySelectorAll('canvas').length,
      layers:view.map.layers.toArray().map(l=>({title:l.title,count:l.graphics?.length,loadStatus:l.loadStatus}))};
  });
  console.log('MAP_STATE',JSON.stringify(state));
  console.log('PASS ArcGIS MapView ready and settled');
  if (errors.length) exit=1;
} catch(e) {
  exit=1;
  console.log('BROWSER_SMOKE_INCOMPLETE',String(e));
} finally {
  const inspection=await page.evaluate(()=>{
    const el=document.querySelector('[data-testid="esri-map-view"]');
    const h=el?.__fleetMapView;
    return {mapContainer:!!el, handle:!!h, ready:h?.view?.ready, updating:h?.view?.updating,
      canvases:el?.querySelectorAll('canvas').length,
      mapText:el?.parentElement?.innerText?.slice(0,1000)};
  }).catch(()=>null);
  console.log('MAP_INSPECTION',JSON.stringify(inspection));
  console.log('PAGE_ERRORS',JSON.stringify(errors));
  console.log('FAILED_REQUESTS',JSON.stringify(failedRequests));
  fs.writeFileSync('/home/user/repository-verification/browser-smoke.json',JSON.stringify({inspection,errors,failedRequests,exit},null,2));
  await page.screenshot({path:'/home/user/.cache/argo-verification/fleet-map-smoke.png'}).catch(()=>{});
  await browser.close();
}
process.exit(exit);
