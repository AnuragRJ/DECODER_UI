// Read-only browser audit of the actual Float Status page and ArcGIS renderer.
// FLEET_E2E_BASE=http://127.0.0.1:3000 npm run test:fleet
// Optional: FLEET_E2E_EXPECTED=<independent upstream oracle JSON>
//           FLEET_E2E_OUTAGE=<captured controlled FTP-failure payload JSON>
//           FLEET_E2E_REQUIRE_FRESH=1 (reject disabled/stale caches)
//           FLEET_E2E_SHOTS=<artifact directory>
// Never triggers decoding, sends email, or writes operational source files.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.FLEET_E2E_BASE || 'http://127.0.0.1:8000';
const SHOTS = process.env.FLEET_E2E_SHOTS || '/tmp/fleetshots';
fs.mkdirSync(SHOTS, { recursive: true });
const oracle = process.env.FLEET_E2E_EXPECTED
  ? new Map(JSON.parse(fs.readFileSync(process.env.FLEET_E2E_EXPECTED)).floats.map(r => [r.wmo, r])) : null;
const results = [], uiRows = [];
const check = (name, condition, details = '') => {
  results.push({ name, passed: Boolean(condition), details });
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${name}${details ? '  ' + details : ''}`);
  if (!condition) throw new Error(name + ': ' + details);
};
const utc = value => value ? new Date(value).toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : '—';
const coord = (value, kind) => value == null ? '—' : Math.abs(value).toFixed(3) + '°' +
  (kind === 'lon' ? value < 0 ? 'W' : 'E' : value < 0 ? 'S' : 'N');
const statusAt = (tx, asOf) => {
  if (!tx) return 'NO DATA';
  const days = (Date.parse(asOf) - Date.parse(tx)) / 86400000;
  return days <= 10 ? 'ACTIVE' : days < 60 ? 'OVERDUE' : 'NO COMMUNICATION 60+ DAYS';
};
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1720, height: 1000 }, timezoneId: 'Asia/Kolkata' });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const pageErrors = [];
page.on('pageerror', error => pageErrors.push(error.message));
let displayedPayload = null;
page.on('response', async response => {
  if (response.url().endsWith('/api/fleet-status') && response.status() === 200) {
    displayedPayload = await response.json().catch(() => displayedPayload);
  }
});
const tableRows = () => page.locator('[data-testid^="fleet-row-"]');
const ids = () => tableRows().evaluateAll(rows => rows.map(row => Number(row.dataset.testid.replace('fleet-row-', ''))));
async function clear() {
  const button = page.getByRole('button', { name: 'Clear', exact: true });
  if (await button.count()) await button.click();
}
async function collectPages() {
  let values = await ids();
  const next = page.getByTitle('Next page', { exact: true });
  while (await next.isEnabled()) {
    const first = (await ids())[0];
    await next.click();
    await page.waitForFunction(previous => {
      const el = document.querySelector('[data-testid^="fleet-row-"]');
      return el && Number(el.dataset.testid.replace('fleet-row-', '')) !== previous;
    }, first);
    values.push(...await ids());
  }
  return values;
}
async function openStatus(targetPage) {
  await targetPage.goto(BASE, { waitUntil: 'domcontentloaded' });
  await targetPage.getByTitle('Open Dedicated Results & Oceanographic Analysis Workspace').click();
  await targetPage.getByRole('button', { name: '[ Float Status ]', exact: true }).click();
  await targetPage.getByTestId('float-status-page').waitFor();
  await targetPage.locator('[data-testid^="fleet-row-"]').first().waitFor();
}

try {
  let payload;
  for (let attempt = 0; attempt < 60; attempt++) {
    payload = await (await fetch(BASE + '/api/fleet-status')).json();
    if (!payload.sync.running && payload.floats.length &&
        (!process.env.FLEET_E2E_REQUIRE_FRESH || (!payload.sync.stale && payload.sync.status === 'ok'))) break;
    await delay(5000);
  }
  check('cache endpoint serves the configured fleet', payload.floats.length > 0, `${payload.floats.length} floats; sync=${payload.sync.status}`);
  if (process.env.FLEET_E2E_REQUIRE_FRESH) {
    check('live verification is fresh, not disabled or stale', payload.sync.status === 'ok' && !payload.sync.stale && !payload.sync.running);
  }
  await openStatus(page);
  check('Float Status entry and page preserved', await page.getByTestId('float-status-page').count() === 1);
  check('sync and summary metrics visible', await page.getByTestId('fleet-sync-pill').count() === 1 && await page.getByTestId('fleet-status-metrics').count() === 1);
  await page.waitForFunction(() => document.querySelector('[data-testid="esri-map-view"]')?.__fleetMapView?.view?.ready, null, { timeout: 90000 });
  check('actual ArcGIS map is ready (not obsolete SVG assertion)', await page.getByTestId('esri-map-view').locator('canvas').count() > 0);
  await page.waitForFunction(() => {
    const view = document.querySelector('[data-testid="esri-map-view"]')?.__fleetMapView?.view;
    return view?.ready && view.stationary && !view.updating;
  }, null, { timeout: 90000 });
  check('map basemap layers have loaded before visual evidence', await page.getByTestId('esri-map-view').evaluate(el =>
    el.__fleetMapView.view.map.basemap.baseLayers.toArray().every(layer => layer.loadStatus === 'loaded')));
  await page.screenshot({ path: path.join(SHOTS, '01-float-status.png') });
  payload = displayedPayload || payload;

  // Verify the renderer's actual marker graphics, not only input props.
  const graphics = await page.getByTestId('esri-map-view').evaluate(el =>
    el.__fleetMapView.view.map.allLayers.toArray().flatMap(layer => layer.graphics?.toArray() || [])
      .filter(g => g.attributes?.kind === 'marker' && g.symbol?.type === 'simple-marker')
      .map(g => ({ wmo: g.attributes.wmo, lat: g.geometry.latitude, lon: g.geometry.longitude })));
  const plotted = payload.floats.filter(r => r.lat != null && r.lon != null);
  check('all and only positioned floats have actual map markers', graphics.length === plotted.length, `${graphics.length} markers`);
  for (const r of plotted) {
    const g = graphics.find(g => g.wmo === r.wmo);
    check(`WMO ${r.wmo}: marker/API coordinates agree`, g && Math.abs(g.lat-r.lat) < 1e-9 && Math.abs(g.lon-r.lon) < 1e-9);
  }

  // Every row, all 11 requested fields. Expected Next is in the detail drawer.
  for (const original of payload.floats) {
    const wmo = original.wmo;
    await page.getByPlaceholder('Search WMO / internal ID…').fill(String(wmo));
    const row = page.getByTestId(`fleet-row-${wmo}`);
    await row.waitFor();
    check(`WMO ${wmo}: search selects exactly one row`, await tableRows().count() === 1);
    const r = (displayedPayload || payload).floats.find(r => r.wmo === wmo);
    const cells = await row.evaluate(el => Object.fromEntries([...el.querySelectorAll('[data-field]')].map(x => [x.dataset.field, x.textContent.trim()])));
    const wanted = {
      wmo: String(wmo), internal_id: r.internal_id || '—', prof_num: r.prof_num == null ? '—' : String(r.prof_num),
      lon: coord(r.lon, 'lon'), lat: coord(r.lat, 'lat'), float_type: r.float_type, status: r.status,
      days_since_last_tx: r.days_since_last_tx == null ? '—' : Math.floor(r.days_since_last_tx) + ' d',
      profiles_missing: r.profiles_missing == null ? '—' : String(r.profiles_missing),
    };
    const differences = Object.entries(wanted).filter(([key, value]) =>
      key === 'wmo' ? !cells[key].startsWith(value) : cells[key] !== value);
    check(`WMO ${wmo}: table fields match API`, differences.length === 0, JSON.stringify(differences));
    check(`WMO ${wmo}: Last Transmission is UTC`, cells.last_tx_iso.startsWith(utc(r.last_tx_iso)));
    check(`WMO ${wmo}: status follows exact 10/60-day policy`, r.status === statusAt(r.last_tx_iso, (displayedPayload || payload).generated_at));
    await row.click();
    const drawer = page.getByTestId('fleet-detail');
    await drawer.waitFor();
    const expectedText = await drawer.locator('[data-detail-label="Expected next (+10 days)"] > span').last().textContent();
    const expected = r.last_tx_iso ? new Date(Date.parse(r.last_tx_iso) + 10 * 86400000).toISOString() : null;
    check(`WMO ${wmo}: Expected Next = upstream Last Transmission +10 days`, expectedText === utc(expected));
    if (oracle) {
      const truth = oracle.get(wmo);
      check(`WMO ${wmo}: API agrees with independent upstream/registry evidence`, !!truth &&
        r.internal_id === truth.internal_id && r.float_type === truth.float_type &&
        r.prof_num === truth.prof_num && r.profile_count === truth.profile_count &&
        r.profiles_missing === truth.profiles_missing && r.last_tx_field === truth.last_tx_field &&
        (r.last_tx_iso == null ? truth.last_tx_iso == null : Math.abs(Date.parse(r.last_tx_iso) - Date.parse(truth.last_tx_iso)) <= 1) &&
        (r.lat == null ? truth.lat == null : Math.abs(r.lat-truth.lat) < 1e-9) &&
        (r.lon == null ? truth.lon == null : Math.abs(r.lon-truth.lon) < 1e-9));
    }
    uiRows.push({ wmo, cells, expected_next: expectedText, api: r, generated_at: (displayedPayload || payload).generated_at });
    if ([2902223, 2902222, 1902844, 2902086, 2901305, 6902892].includes(wmo)) {
      await page.screenshot({ path: path.join(SHOTS, `detail-${wmo}.png`) });
    }
    await page.getByTitle('Close detail', { exact: true }).click();
  }

  await clear();
  await page.getByPlaceholder('Search WMO / internal ID…').fill('2902223');
  await page.waitForFunction(() => document.querySelector('[data-testid="esri-map-view"]')?.__fleetMapData?.markers?.length === 1);
  // Filtering intentionally preserves an operator's camera. Use the existing
  // FIT control before asking the browser to click a geographic point.
  await page.getByRole('button', { name: 'FIT', exact: true }).click();
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    const view = el?.__fleetMapView?.view;
    if (!view?.stationary || view.updating) return false;
    const graphic = view.map.allLayers.toArray().flatMap(layer => layer.graphics?.toArray() || [])
      .find(g => g.attributes?.kind === 'marker' && g.attributes?.wmo === 2902223 && g.symbol?.type === 'simple-marker');
    if (!graphic) return false;
    const point = view.toScreen(graphic.geometry);
    return point && point.x > 0 && point.y > 0 && point.x < el.clientWidth && point.y < el.clientHeight;
  }, null, { timeout: 60000 });
  const screen = await page.getByTestId('esri-map-view').evaluate(el => {
    const view = el.__fleetMapView.view;
    const graphic = view.map.allLayers.toArray().flatMap(layer => layer.graphics?.toArray() || [])
      .find(g => g.attributes?.kind === 'marker' && g.attributes?.wmo === 2902223 && g.symbol?.type === 'simple-marker');
    const point = view.toScreen(graphic.geometry);
    return { x: point.x, y: point.y };
  });
  await page.getByTestId('esri-map-view').click({ position: screen });
  await page.getByTestId('fleet-detail').waitFor();
  check('clicking the real map marker opens the matching WMO detail', (await page.getByTestId('fleet-detail').textContent()).includes('WMO 2902223'));
  await page.getByTitle('Close detail', { exact: true }).click();
  await clear();
  check('pagination covers all configured WMOs exactly once', new Set(await collectPages()).size === payload.floats.length);
  await page.getByTitle('Previous page', { exact: true }).click();
  const identityRow = payload.floats.find(r => r.internal_id);
  await page.getByPlaceholder('Search WMO / internal ID…').fill(identityRow.internal_id);
  check('search by Internal ID works', await page.getByTestId(`fleet-row-${identityRow.wmo}`).count() === 1);
  await clear();
  for (const type of [...new Set(payload.floats.map(r => r.float_type))]) {
    await page.getByTitle('Filter by float type', { exact: true }).selectOption(type);
    const shown = await collectPages();
    const expected = payload.floats.filter(r => r.float_type === type).map(r => r.wmo).sort();
    check(`float-type filter ${type}`, JSON.stringify(shown.sort()) === JSON.stringify(expected));
  }
  await clear();
  for (const status of ['ACTIVE', 'OVERDUE', 'NO COMMUNICATION 60+ DAYS', 'NO DATA']) {
    await page.getByTitle('Filter by communication status', { exact: true }).selectOption(status);
    const shown = await collectPages();
    const expected = payload.floats.filter(r => r.status === status).map(r => r.wmo).sort();
    check(`communication filter ${status}`, JSON.stringify(shown.sort()) === JSON.stringify(expected));
  }
  await clear();
  const sorts = [
    ['WMO ID', r => r.wmo, 'asc'], ['Last Transmission', r => r.last_tx_iso ? Date.parse(r.last_tx_iso) : null, 'desc'],
    ['No Communication', r => r.days_since_last_tx, 'desc'], ['Prof#', r => r.prof_num, 'desc'],
    ['# Profs Missing', r => r.profiles_missing, 'desc'],
  ];
  for (const [label, value, firstDirection] of sorts) {
    for (const direction of [firstDirection, firstDirection === 'asc' ? 'desc' : 'asc']) {
      await page.getByTitle(new RegExp('^Sort by ' + label)).click();
      const actual = await collectPages();
      const expected = [...payload.floats].sort((a, b) => {
        const av=value(a), bv=value(b);
        return av == null ? bv == null ? a.wmo-b.wmo : 1 : bv == null ? -1 :
          (direction === 'asc' ? av-bv : bv-av) || a.wmo-b.wmo;
      }).map(r => r.wmo);
      check(`sort ${label} ${direction}, nulls last, across pages`, JSON.stringify(actual) === JSON.stringify(expected));
    }
  }
  await clear();
  await page.getByPlaceholder('Search WMO / internal ID…').fill('no-such-float');
  check('empty search is honest, no fabricated rows', await tableRows().count() === 0);
  await clear();

  if (process.env.FLEET_E2E_OUTAGE) {
    const outage = JSON.parse(fs.readFileSync(process.env.FLEET_E2E_OUTAGE));
    await page.route('**/api/fleet-status', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(outage) }));
    await page.getByRole('button', { name: '[ Back to Results ]', exact: true }).click();
    await page.getByRole('button', { name: '[ Float Status ]', exact: true }).click();
    await page.getByTestId('fleet-freshness-notice').waitFor();
    check('controlled FTP-failure payload shows visible stale cache notice', (await page.getByTestId('fleet-sync-pill').textContent()).includes('Stale cache'));
    await page.getByPlaceholder('Search WMO / internal ID…').fill('2902223');
    check('failed sync retains the real last valid communication value', (await page.getByTestId('fleet-row-2902223').locator('[data-field="last_tx_iso"]').textContent()).startsWith(utc(oracle?.get(2902223)?.last_tx_iso || payload.floats.find(r => r.wmo === 2902223).last_tx_iso)));
    await page.screenshot({ path: path.join(SHOTS, 'controlled-ftp-failure-stale-cache.png') });
    await page.unroute('**/api/fleet-status');
  }
  await page.getByRole('button', { name: '[ Back to Results ]', exact: true }).click();
  check('Back returns to Results without redesigning navigation', await page.getByText('DECODER RESULTS', { exact: true }).count() === 1);
  check('no runtime page errors', pageErrors.length === 0, pageErrors.join(' | '));

  // A second browser timezone must not change the displayed UTC transmission.
  const otherContext = await browser.newContext({ viewport: { width: 1440, height: 900 }, timezoneId: 'America/Los_Angeles' });
  const other = await otherContext.newPage();
  await openStatus(other);
  await other.getByPlaceholder('Search WMO / internal ID…').fill('2902223');
  const text = await other.getByTestId('fleet-row-2902223').locator('[data-field="last_tx_iso"]').textContent();
  check('UTC presentation is identical in Kolkata and Los Angeles', text.startsWith(utc(payload.floats.find(r => r.wmo === 2902223).last_tx_iso)));
  await otherContext.close();
} catch (error) {
  results.push({ name: 'E2E completed', passed: false, details: String(error) });
  console.error(error);
  await page.screenshot({ path: path.join(SHOTS, 'FAIL.png') }).catch(() => {});
} finally {
  await browser.close();
}
fs.writeFileSync(path.join(SHOTS, 'verification.json'), JSON.stringify({ results, uiRows, pageErrors }, null, 2));
const failures = results.filter(r => !r.passed).length;
console.log(`\n${results.length-failures}/${results.length} checks passed; ${uiRows.length} floats field-checked`);
process.exitCode = failures ? 1 : 0;
