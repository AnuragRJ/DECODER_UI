// Read-only browser audit of the actual Float Status page and ArcGIS renderer.
// Covers the observed-cycle-interval formulas and the experimental next-profile
// prediction block (drawer + optional map layer) as served by the live API.
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
const baseline = process.env.FLEET_E2E_BASELINE
  ? new Map(JSON.parse(fs.readFileSync(process.env.FLEET_E2E_BASELINE)).floats.map(r => [r.wmo, r])) : null;
const NOTE_DEFAULT = 'Approximate estimate based on the expected 10-day profile cycle.';
// The tooltip is the API's own interval_note; recompute it independently so a
// drifted backend string fails instead of being copied.
const approxNote = r => {
  if (r.interval_note) {
    const observed = /^Approximate estimate based on the observed ([\d.]+)-day profile cycle \(median of (\d+) (published profile dates|trajectory cycles)\)\.$/.exec(r.interval_note);
    const fallback = r.interval_note === 'Approximate estimate based on the expected 10-day profile cycle (no sufficient observed cycle history).';
    if (!observed && !fallback) return null;
    if (observed) {
      if (r.expected_interval_source === 'default 10-day cycle') return null;
      if (Number(observed[1]) !== Number(Number(r.expected_interval_days).toFixed(1))) return null;
      if (Number(observed[2]) !== r.expected_interval_samples) return null;
    }
    return r.interval_note;
  }
  const days = r.expected_interval_days;
  if (days == null || !Number.isFinite(days) || !r.expected_interval_source ||
      r.expected_interval_source === 'default 10-day cycle') return NOTE_DEFAULT;
  const where = r.expected_interval_source === 'profile history' ? 'published profile dates' : 'trajectory cycles';
  return `Approximate estimate based on the observed ${days.toFixed(1)}-day profile cycle (median of ${r.expected_interval_samples ?? 0} ${where}).`;
};
const intervalOf = r => Number.isFinite(r.expected_interval_days) && r.expected_interval_days > 0 ? r.expected_interval_days : 10;
const results = [], uiRows = [];
const check = (name, condition, details = '') => {
  results.push({ name, passed: Boolean(condition), details });
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${name}${details ? '  ' + details : ''}`);
  if (!condition) throw new Error(name + ': ' + details);
};
const utc = value => value ? new Date(value).toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : '—';
const coord = (value, kind) => value == null ? '—' : Math.abs(value).toFixed(3) + '°' +
  (kind === 'lon' ? value < 0 ? 'W' : 'E' : value < 0 ? 'S' : 'N');
const statusAt = (profileDate, asOf, intervalDays) => {
  if (!profileDate) return 'NO DATA';
  const days = (Date.parse(asOf) - Date.parse(profileDate)) / 86400000;
  const interval = Number.isFinite(intervalDays) && intervalDays > 0 ? intervalDays : 10;
  return days <= interval ? 'ACTIVE / RECENT PROFILE' : days < 60 ? 'PROFILE OVERDUE' : 'NO RECENT PROFILE DATA 60+ DAYS';
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
  check('monitoring source is prof.nc JULD', payload.source.monitoring === 'profile-recency' && payload.source.product.endsWith('<wmo>_prof.nc') && payload.source.field.startsWith('JULD'));
  check('source metadata states the observed-interval policy', typeof payload.source.interval_policy === 'string' && /observed cycle interval/i.test(payload.source.interval_policy));

  // ---- experimental prediction contract (payload level) -------------------
  const summary = payload.prediction;
  const predictRows = payload.floats.filter(r => r.prediction && r.prediction.available);
  check('fleet-wide prediction summary matches the rows', !!summary &&
    summary.available === predictRows.length && summary.unavailable === payload.floats.length - summary.available,
    `${summary?.available}/${payload.floats.length} available`);
  check('every row carries an explicit prediction status', payload.floats.every(r =>
    r.prediction && typeof r.prediction.status === 'string' && Array.isArray(r.prediction.issues)));
  check('prediction label is present and not a communication claim', payload.floats.every(r =>
    r.prediction.label === 'Experimental prediction — not a communication signal'));
  check('validation-derived radii, never fabricated', payload.floats.every(r => !r.prediction.available || (
    Number.isFinite(r.prediction.r50_km) && Number.isFinite(r.prediction.r90_km) &&
    r.prediction.r90_km >= r.prediction.r50_km && r.prediction.validation_samples > 0 && !!r.prediction.validation_source)));
  check('unavailable predictions carry a null position and a reason', payload.floats.every(r => r.prediction.available || (
    r.prediction.predicted_lat == null && r.prediction.predicted_lon == null && !!r.prediction.status_message)));
  check('calibration artefact is advertised with its own provenance', !!summary?.calibration?.available === false ||
    (summary.calibration.available === true && typeof summary.calibration.generated_at === 'string' && !!summary.calibration.path));
  check('absent current provider is stated identically on every row', !!summary && typeof summary.currents === 'string' &&
    payload.floats.every(r => r.prediction.currents === summary.currents));
  check('ML rung is never claimed', payload.floats.every(r => r.prediction.method !== 'ml_residual'));

  // ---- fleet-wide diagnostics: what Stage-0 actually used -----------------
  const diag = summary && summary.diagnostics;
  const byMethod = payload.floats.reduce((acc, r) => {
    acc[r.prediction.method] = (acc[r.prediction.method] || 0) + 1; return acc;
  }, {});
  const byRung = payload.floats.reduce((acc, r) => {
    if (r.prediction.fallback_rung != null) acc[r.prediction.fallback_rung] = (acc[r.prediction.fallback_rung] || 0) + 1; return acc;
  }, {});
  check('diagnostics report the same methods as the rows', !!diag &&
    JSON.stringify(diag.methods) === JSON.stringify(byMethod), JSON.stringify(diag && diag.methods));
  check('diagnostics report the same fallback rungs as the rows', !!diag &&
    JSON.stringify(diag.rungs) === JSON.stringify(Object.fromEntries(
      Object.entries(byRung).sort((a, b) => Number(a[0]) - Number(b[0])))));
  check('diagnostics separate persistence-only from higher-rung floats',
    !!diag && diag.persistence_only === payload.floats.filter(r => r.prediction.method === 'persistence').length &&
    diag.history_prior === payload.floats.filter(r => r.prediction.method === 'history_prior').length &&
    diag.trajectory_extrapolation === payload.floats.filter(r => r.prediction.method === 'trajectory_extrapolation').length);
  check('diagnostics state how much trajectory history each float actually used',
    !!diag && diag.trajectory_transitions && diag.floats === payload.floats.length &&
    diag.trajectory_history_available === payload.floats.filter(r => r.prediction.trajectory_transitions > 0).length &&
    diag.trajectory_transitions.min <= diag.trajectory_transitions.median &&
    diag.trajectory_transitions.median <= diag.trajectory_transitions.max &&
    payload.floats.every(r => r.prediction.trajectory_transitions >= 0));
  check('an input advisory never invents a refusal',
    payload.floats.every(r => r.prediction.available ||
      !(r.prediction.issues || []).some(i => /observed hop is/.test(i))));

  const nextLocation = await fetch(BASE + '/api/floats/' + payload.floats[0].wmo + '/next-location');
  const nextBody = await nextLocation.json().catch(() => null);
  const firstRow = payload.floats[0];
  check('per-float prediction endpoint agrees with the fleet payload', nextLocation.status === 200 && !!nextBody &&
    nextBody.wmo === firstRow.wmo && nextBody.label === 'Experimental prediction — not a communication signal' &&
    nextBody.prediction.predicted_lat === firstRow.prediction.predicted_lat &&
    nextBody.prediction.predicted_lon === firstRow.prediction.predicted_lon &&
    nextBody.prediction.r90_km === firstRow.prediction.r90_km &&
    nextBody.prediction.status === firstRow.prediction.status &&
    nextBody.prediction_summary.available === summary.available);
  const unmonitored = await fetch(BASE + '/api/floats/9999999/next-location');
  check('per-float prediction endpoint refuses an unmonitored WMO', unmonitored.status === 404);

  // ---- forward test: the audit that keeps the radii honest ----------------
  const forward = summary && summary.forward_test;
  check('forward-test audit is present and reports its own file', !!forward &&
    forward.enabled === true && typeof forward.path === 'string' && typeof forward.note === 'string');
  check('forward test records one prediction per float without inflating the audit',
    forward.issued >= predictRows.length && forward.scored + forward.pending === forward.issued,
    `issued=${forward.issued} scored=${forward.scored} pending=${forward.pending}`);
  check('forward-test metrics are only claimed once predictions have been scored',
    forward.scored === 0 ? forward.overall == null :
      (forward.overall.n === forward.scored && forward.overall.median_km >= 0 &&
       forward.overall.within_r90_pct != null));
  check('the audit is disabled or honest, never silently empty',
    forward.enabled === false ? /disabled/.test(forward.note || '') : forward.issued > 0);
  check('scored predictions are attributed to the float they belong to',
    Object.keys(forward.floats || {}).every(wmo => payload.floats.some(r => String(r.wmo) === wmo)));

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

  // Every real row: prof.nc JULD -> dates -> elapsed days -> estimate -> data status.
  for (const original of payload.floats) {
    const wmo = original.wmo;
    await page.getByPlaceholder('Search WMO / internal ID…').fill(String(wmo));
    const row = page.getByTestId(`fleet-row-${wmo}`);
    await row.waitFor();
    check(`WMO ${wmo}: search selects exactly one row`, await tableRows().count() === 1);
    // A polling response may arrive while the drawer is being opened. Keep
    // each row and its calculation clock from the same immutable snapshot.
    const rowPayload = displayedPayload || payload;
    const asOf = rowPayload.generated_at;
    const r = rowPayload.floats.find(r => r.wmo === wmo);
    const cells = await row.evaluate(el => Object.fromEntries([...el.querySelectorAll('[data-field]')].map(x => [x.dataset.field, x.textContent.trim()])));
    const wanted = {
      wmo: String(wmo), internal_id: r.internal_id || '—', prof_num: r.prof_num == null ? '—' : String(r.prof_num),
      lon: coord(r.lon, 'lon'), lat: coord(r.lat, 'lat'), float_type: r.float_type, data_status: r.data_status,
      days_since_last_profile: r.days_since_last_profile == null ? '—' : Math.floor(r.days_since_last_profile) + ' d',
      approx_profiles_missed: r.approx_profiles_missed == null ? '—' : String(r.approx_profiles_missed),
    };
    const differences = Object.entries(wanted).filter(([key, value]) =>
      key === 'wmo' ? !cells[key].startsWith(value) : cells[key] !== value);
    check(`WMO ${wmo}: table fields match API`, differences.length === 0, JSON.stringify(differences));
    check(`WMO ${wmo}: Last Profile Date is UTC`, cells.last_profile_iso.startsWith(utc(r.last_profile_iso)));
    check(`WMO ${wmo}: status follows the exact observed-interval / 60-day policy`, r.data_status === statusAt(r.last_profile_iso, asOf, r.expected_interval_days));
    await row.click();
    const drawer = page.getByTestId('fleet-detail');
    await drawer.waitFor();
    const recency = drawer.getByTestId('detail-section-recency');
    const predicted = drawer.getByTestId('detail-section-prediction');
    const expectedText = await recency.locator('[data-detail-label="Expected Next Profile"] > span').last().textContent();
    const interval = intervalOf(r);
    const expected = r.last_profile_iso ? new Date(Date.parse(r.last_profile_iso) + interval * 86400000).toISOString() : null;
    check(`WMO ${wmo}: Expected Next Profile = Last Profile Date + observed interval (${interval.toFixed(2)} d)`,
      expectedText === utc(expected) && (r.expected_next_profile_iso == null ||
        Math.abs(Date.parse(r.expected_next_profile_iso) - Date.parse(expected)) < 1000));
    const days = r.last_profile_iso == null ? null :
      (Date.parse(asOf) - Date.parse(r.last_profile_iso)) / 86400000;
    check(`WMO ${wmo}: unrounded elapsed days and floor(days / observed interval)`, days == null ?
      r.days_since_last_profile == null && r.approx_profiles_missed == null :
      Math.abs(r.days_since_last_profile-days) < 2e-8 && r.approx_profiles_missed === Math.floor(days/interval));
    const note = approxNote(r);
    check(`WMO ${wmo}: estimate tooltip states the observed interval and its source`, note != null &&
      await row.locator('[data-field="approx_profiles_missed"]').getAttribute('title') === note, String(note));
    const intervalRow = await recency.locator('[data-detail-label="Observed cycle interval"] > span').last().textContent().catch(() => '');
    check(`WMO ${wmo}: drawer states the interval used and its provenance`,
      intervalRow.startsWith(`${interval.toFixed(2)} d (`) && intervalRow.includes(r.expected_interval_source || 'unknown source'));
    const detailStatus = await recency.locator('[data-detail-label="Data Status"] > span').last().textContent();
    const detailMissed = await recency.locator('[data-detail-label="Approx. Profiles Missed"] > span').last().textContent();
    check(`WMO ${wmo}: drawer status and estimate agree`, detailStatus === r.data_status && detailMissed === (r.approx_profiles_missed == null ? '—' : String(r.approx_profiles_missed)));
    const sectionFields = [
      ['detail-section-identity', ['WMO', 'Internal ID', 'Float Type']],
      ['detail-section-position', ['Latitude', 'Longitude']],
      ['detail-section-inventory', ['Prof#']],
      ['detail-section-recency', ['Last Profile Date', 'Expected Next Profile', 'Days Since Last Profile', 'Approx. Profiles Missed', 'Data Status', 'Observed cycle interval']],
    ];
    for (const [sectionTestId, labels] of sectionFields) {
      for (const label of labels) {
        check(`WMO ${wmo}: drawer ${sectionTestId.replace('detail-section-', '')} shows ${label}`,
          await drawer.getByTestId(sectionTestId).locator(`[data-detail-label="${label}"]`).count() === 1);
      }
    }

    // ---- experimental next-profile prediction block (present for every row) --
    const prediction = r.prediction || null;
    check(`WMO ${wmo}: drawer has the experimental prediction block`,
      await drawer.getByText('NEXT PROFILE LOCATION (PREDICTED)', { exact: true }).count() === 1 &&
      await predicted.getByTestId('prediction-section').count() + await predicted.getByTestId('prediction-absent').count() === 1);
    const predictionLabel = await predicted.getByTestId('prediction-label').textContent().catch(() => '');
    check(`WMO ${wmo}: prediction block is labelled experimental, not a telemetry claim`,
      predictionLabel.trim().toLowerCase() === 'experimental prediction — not a communication signal', predictionLabel.trim());
    if (prediction && prediction.available) {
      const shownLat = await predicted.locator('[data-detail-label="Predicted Latitude"] > span').last().textContent();
      const shownLon = await predicted.locator('[data-detail-label="Predicted Longitude"] > span').last().textContent();
      check(`WMO ${wmo}: predicted position matches the API`,
        shownLat === coord(prediction.predicted_lat, 'lat') && shownLon === coord(prediction.predicted_lon, 'lon'),
        `${shownLat} ${shownLon}`);
      const method = await predicted.locator('[data-detail-label="Prediction Method"] > span').last().textContent();
      const rung = await predicted.locator('[data-detail-label="Fallback rung"] > span').last().textContent();
      const samples = await predicted.locator('[data-detail-label="Validation Sample Count"] > span').last().textContent();
      const status = await predicted.locator('[data-detail-label="Prediction Status"] > span').last().textContent();
      const r50 = await predicted.locator('[data-detail-label="R50 (empirical)"] > span').last().textContent();
      const r90 = await predicted.locator('[data-detail-label="R90 (empirical)"] > span').last().textContent();
      const trajAvailable = await predicted.locator('[data-detail-label="Trajectory history available"] > span').last().textContent();
      const stage = await predicted.locator('[data-detail-label="Predictor stage"] > span').last().textContent();
      const trajTransitions = await predicted.locator('[data-detail-label="Trajectory transitions"] > span').last().textContent();
      const radiusNote = await predicted.getByTestId('prediction-radius-note').textContent();
      const horizon = await predicted.locator('[data-detail-label="Prediction Horizon"] > span').last().textContent();
      check(`WMO ${wmo}: method, rung, samples and status match the API`,
        method.trim() === prediction.method_label && rung.trim().startsWith(String(prediction.fallback_rung)) &&
        samples.trim() === String(prediction.validation_samples) && status.trim() === 'AVAILABLE');
      check(`WMO ${wmo}: R50 is quoted as an empirical radius with the exact required wording`,
        r50.trim() === `R50: ${prediction.r50_km.toFixed(1)} km — 50% of historical validation prediction errors were within this distance.`,
        r50.trim());
      check(`WMO ${wmo}: R90 is quoted as an empirical radius with the exact required wording`,
        r90.trim() === `R90: ${prediction.r90_km.toFixed(1)} km — 90% of historical validation prediction errors were within this distance.`,
        r90.trim());
      check(`WMO ${wmo}: drawer states the empirical caveat and never claims a probability`,
        radiusNote.includes('These are empirical uncertainty radii calculated from historical validation errors, not a probability guarantee for this individual prediction.') &&
        !/90\s?%\s?(confidence|probability|probable|chance)/i.test(radiusNote) && !/confidence interval/i.test(radiusNote));
      check(`WMO ${wmo}: drawer names the predictor stage and never implies a stage swap`,
        // Stage-0 baseline is named by default; a Stage-1 payload must also show its step
        // and the note that Stage-0 remains the shipped baseline with its own radii.
        stage.trim() === (prediction.predictor_stage_label ||
          'Stage-0 baseline (last-hop step) — no stage reported by this payload') &&
        (prediction.predictor_stage === 'stage1'
          ? (await predicted.getByTestId('prediction-stage-note').count() === 1 &&
             await predicted.locator('[data-detail-label="Cycle-scale step basis"]').count() === 1)
          : (await predicted.getByTestId('prediction-stage-note').count() === 0 &&
             await predicted.locator('[data-detail-label="Cycle-scale step basis"]').count() === 0)),
        stage.trim());
      check(`WMO ${wmo}: drawer reports the trajectory history behind the method`,
        trajAvailable.trim().startsWith((prediction.trajectory_transitions ?? 0) > 0 ? 'yes —' : 'no —') &&
        trajTransitions.trim() === String(prediction.trajectory_transitions));
      check(`WMO ${wmo}: horizon states the lead time behind the prediction`,
        horizon.trim() === `+${Number(prediction.prediction_horizon_days).toFixed(2)} d` &&
        Math.abs(prediction.prediction_horizon_days - interval) <= 0.005001, horizon.trim());
      check(`WMO ${wmo}: drawer quotes the calibration basis behind the radius`,
        (await predicted.locator('[data-detail-label="Calibration basis"] > span').last().textContent()).trim() === prediction.validation_source);
    } else {
      check(`WMO ${wmo}: unavailable prediction states the refusal, not a position`,
        await predicted.getByTestId('prediction-unavailable').count() + await predicted.getByTestId('prediction-absent').count() >= 1 &&
        await predicted.locator('[data-detail-label="Predicted Latitude"]').count() === 0 &&
        await predicted.locator('[data-detail-label="R50 (empirical)"]').count() === 0 &&
        await predicted.locator('[data-detail-label="R90 (empirical)"]').count() === 0 &&
        await predicted.getByTestId('prediction-radius-note').count() === 0);
    }
    if (oracle) {
      const truth = oracle.get(wmo);
      check(`WMO ${wmo}: prof.nc JULD -> API date`, !!truth &&
        r.last_profile_field === 'JULD' && r.last_profile_file === `${wmo}_prof.nc` &&
        r.last_profile_index === truth.last_profile_index &&
        (r.last_profile_iso == null ? truth.last_profile_iso == null :
          Math.abs(Date.parse(r.last_profile_iso) - Date.parse(truth.last_profile_iso)) <= 1));
    }
    if (baseline) {
      const before = baseline.get(wmo);
      check(`WMO ${wmo}: identity, Prof# and verified positions unchanged`, !!before &&
        r.internal_id === before.internal_id && r.float_type === before.float_type &&
        r.prof_num === before.prof_num && r.lat === before.lat && r.lon === before.lon &&
        r.pos_source === before.pos_source && r.pos_qc === before.pos_qc &&
        r.position_iso === before.position_iso && r.position_file === before.position_file);
    }
    const visible = await page.getByTestId('float-status-page').innerText();
    check(`WMO ${wmo}: profile wording only`, !/Last Communication|Last Transmission|No Transmission|No Communication|\bdead\b/i.test(visible));
    uiRows.push({ wmo, cells, expected_next: expectedText, api: r, generated_at: asOf });
    if ([2902223, 2902222, 1902844, 2902203, 2902086, 2901328].includes(wmo)) {
      await page.screenshot({ path: path.join(SHOTS, `detail-${wmo}.png`) });
    }
    await page.getByTitle('Close detail', { exact: true }).click();
  }

  await clear();

  // ---- experimental prediction layer: opt-in, additive, never a substitute --
  const predictionFloats = (displayedPayload || payload).floats.filter(r => r.prediction && r.prediction.available &&
    r.prediction.predicted_lat != null && r.prediction.predicted_lon != null && r.prediction.r90_km != null);
  const layerState = () => page.getByTestId('esri-map-view').evaluate(el => {
    const view = el.__fleetMapView.view;
    const prediction = view.map.layers.find(l => l.title === 'prediction');
    const markers = view.map.layers.find(l => l.title === 'markers');
    const graphics = prediction ? prediction.graphics.toArray().map(g => ({
      kind: g.attributes?.kind, wmo: g.attributes?.wmo, symbol: g.symbol?.type, style: g.symbol?.style,
      lon: g.geometry.longitude ?? g.geometry.extent?.center?.longitude ?? null,
      lat: g.geometry.latitude ?? g.geometry.extent?.center?.latitude ?? null,
    })) : [];
    return {
      enabled: el.__fleetMapData?.predictions?.visible === true,
      points: el.__fleetMapData?.predictions?.points?.length ?? 0,
      graphics, markers: markers ? markers.graphics.length : 0,
    };
  });
  const toggle = page.getByTestId('prediction-layer-toggle');
  const before = await layerState();
  check('prediction layer is an explicit opt-in control, unchecked by default',
    await toggle.count() === 1 && !(await toggle.isChecked()));
  check('prediction data is ready but nothing is painted until the operator opts in',
    before.enabled === false && before.graphics.length === 0 && before.points === predictionFloats.length,
    `enabled=${before.enabled} painted=${before.graphics.length} prepared=${before.points}`);
  check('prediction toggle quotes the number of floats that actually have one',
    (await toggle.evaluate(el => el.parentElement?.textContent || '')).includes(`Predicted next profile (${predictionFloats.length})`));
  await toggle.check();
  await page.waitForFunction(n => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    const layer = el?.__fleetMapView?.view.map.layers.find(l => l.title === 'prediction');
    return el?.__fleetMapData?.predictions?.visible === true && (layer?.graphics.length ?? 0) >= n;
  }, predictionFloats.length * 2, { timeout: 60000 });
  await page.waitForFunction(() => {
    const view = document.querySelector('[data-testid="esri-map-view"]')?.__fleetMapView?.view;
    return view?.stationary && !view.updating;
  }, null, { timeout: 60000 });
  const after = await layerState();
  const diamonds = after.graphics.filter(g => g.kind === 'prediction');
  const rings = after.graphics.filter(g => g.kind === 'prediction-ring');
  const links = after.graphics.filter(g => g.kind === 'prediction-link');
  check('every validated prediction is drawn exactly once as its own marker',
    diamonds.length === predictionFloats.length && new Set(diamonds.map(g => g.wmo)).size === diamonds.length,
    `${diamonds.length} predicted positions`);
  check('predicted positions use a distinct symbol style from real float markers',
    diamonds.every(g => g.style === 'diamond') && after.markers > 0 &&
    after.graphics.every(g => g.kind !== 'marker'), diamonds.map(g => g.style).join(','));
  check('predicted positions cannot be mistaken for real markers on the same layer',
    after.graphics.every(g => ['prediction', 'prediction-ring', 'prediction-link'].includes(g.kind)));
  check('each prediction carries its 50 % and 90 % uncertainty rings', rings.length === predictionFloats.length * 2,
    `${rings.length} ring graphics`);
  check('a dashed connector is drawn only where a real position exists',
    links.length === predictionFloats.filter(r => r.lat != null && r.lon != null).length, `${links.length} connectors`);
  check('enabling the layer never hides or moves the real float markers',
    after.markers === before.markers && before.markers > 0, `${after.markers} real markers`);
  for (const r of predictionFloats) {
    const g = diamonds.find(d => d.wmo === r.wmo);
    check(`WMO ${r.wmo}: drawn prediction equals the API position`, !!g &&
      Math.abs(g.lon - r.prediction.predicted_lon) < 1e-9 && Math.abs(g.lat - r.prediction.predicted_lat) < 1e-9);
  }
  const clickTarget = diamonds.find(g => predictionFloats.some(r => r.wmo === g.wmo))?.wmo;
  await page.getByRole('button', { name: 'FIT', exact: true }).click();
  await page.waitForFunction(wmo => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    const view = el?.__fleetMapView?.view;
    if (!view?.stationary || view.updating) return false;
    const graphic = view.map.layers.find(l => l.title === 'prediction')?.graphics.toArray()
      .find(g => g.attributes?.kind === 'prediction' && g.attributes?.wmo === wmo);
    if (!graphic) return false;
    const point = view.toScreen(graphic.geometry);
    return point && point.x > 0 && point.y > 0 && point.x < el.clientWidth && point.y < el.clientHeight;
  }, clickTarget, { timeout: 60000 });
  const predictedScreen = await page.getByTestId('esri-map-view').evaluate((el, wmo) => {
    const view = el.__fleetMapView.view;
    const graphic = view.map.layers.find(l => l.title === 'prediction').graphics.toArray()
      .find(g => g.attributes?.kind === 'prediction' && g.attributes?.wmo === wmo);
    const point = view.toScreen(graphic.geometry);
    return { x: point.x, y: point.y };
  }, clickTarget);
  await page.getByTestId('esri-map-view').click({ position: predictedScreen });
  await page.getByTestId('fleet-detail').waitFor();
  check('clicking a predicted position selects the same float',
    (await page.getByTestId('fleet-detail').textContent()).includes(`WMO ${clickTarget}`));
  await page.getByTitle('Close detail', { exact: true }).click();
  await toggle.uncheck();
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="esri-map-view"]');
    const layer = el?.__fleetMapView?.view.map.layers.find(l => l.title === 'prediction');
    return el?.__fleetMapData?.predictions?.visible === false && (layer?.graphics.length ?? 0) === 0;
  }, null, { timeout: 60000 });
  const restored = await layerState();
  check('disabling the layer removes every prediction graphic and keeps the real markers',
    restored.graphics.length === 0 && restored.markers === before.markers, `${restored.markers} real markers`);

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
  for (const status of ['ACTIVE / RECENT PROFILE', 'PROFILE OVERDUE', 'NO RECENT PROFILE DATA 60+ DAYS', 'NO DATA']) {
    await page.getByTitle('Filter by data status', { exact: true }).selectOption(status);
    const shown = await collectPages();
    const expected = payload.floats.filter(r => r.data_status === status).map(r => r.wmo).sort();
    check(`data-status filter ${status}`, JSON.stringify(shown.sort()) === JSON.stringify(expected));
  }
  await clear();
  const sorts = [
    ['WMO ID', r => r.wmo, 'asc'], ['Last Profile Date', r => r.last_profile_iso ? Date.parse(r.last_profile_iso) : null, 'desc'],
    ['Days Since Last Profile', r => r.days_since_last_profile, 'desc'], ['Prof#', r => r.prof_num, 'desc'],
    ['Approx. Profiles Missed', r => r.approx_profiles_missed, 'desc'],
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
    check('failed sync retains the real last valid profile date', (await page.getByTestId('fleet-row-2902223').locator('[data-field="last_profile_iso"]').textContent()).startsWith(utc(oracle?.get(2902223)?.last_profile_iso || payload.floats.find(r => r.wmo === 2902223).last_profile_iso)));
    await page.screenshot({ path: path.join(SHOTS, 'controlled-ftp-failure-stale-cache.png') });
    await page.unroute('**/api/fleet-status');
  }
  await page.getByRole('button', { name: '[ Back to Results ]', exact: true }).click();
  check('Back returns to Results without redesigning navigation', await page.getByText('DECODER RESULTS', { exact: true }).count() === 1);
  check('no runtime page errors', pageErrors.length === 0, pageErrors.join(' | '));

  // A second browser timezone must not change the displayed UTC profile date.
  const otherContext = await browser.newContext({ viewport: { width: 1440, height: 900 }, timezoneId: 'America/Los_Angeles' });
  const other = await otherContext.newPage();
  await openStatus(other);
  await other.getByPlaceholder('Search WMO / internal ID…').fill('2902223');
  const text = await other.getByTestId('fleet-row-2902223').locator('[data-field="last_profile_iso"]').textContent();
  check('UTC presentation is identical in Kolkata and Los Angeles', text.startsWith(utc(payload.floats.find(r => r.wmo === 2902223).last_profile_iso)));
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
