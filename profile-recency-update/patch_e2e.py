from pathlib import Path
p=Path('/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/frontend/e2e/fleetStatus.e2e.mjs');s=p.read_text()
s=s.replace('const results = [], uiRows = [];','''const baseline = process.env.FLEET_E2E_BASELINE
  ? new Map(JSON.parse(fs.readFileSync(process.env.FLEET_E2E_BASELINE)).floats.map(r => [r.wmo, r])) : null;
const NOTE = 'Approximate estimate based on the expected 10-day profile cycle.';
const results = [], uiRows = [];''')
s=s.replace('const statusAt = (tx, asOf) => {\n  if (!tx)', 'const statusAt = (profileDate, asOf) => {\n  if (!profileDate)').replace('Date.parse(tx)', 'Date.parse(profileDate)')
s=s.replace("'NO COMMUNICATION 60+ DAYS'", "'NO RECENT PROFILE DATA 60+ DAYS'").replace("'ACTIVE'", "'ACTIVE / RECENT PROFILE'").replace("'OVERDUE'", "'PROFILE OVERDUE'")
s=s.replace('r.last_tx_iso','r.last_profile_iso').replace('r.days_since_last_tx','r.days_since_last_profile').replace('r.profiles_missing','r.approx_profiles_missed').replace('r.last_tx_field','r.last_profile_field')
s=s.replace('r.status','r.data_status')
s=s.replace('status: r.data_status','data_status: r.data_status')
s=s.replace('days_since_last_tx:', 'days_since_last_profile:').replace('profiles_missing:', 'approx_profiles_missed:')
s=s.replace('cells.last_tx_iso','cells.last_profile_iso').replace('last_tx_iso','last_profile_iso')
s=s.replace('Last Transmission','Last Profile Date').replace('No Communication','Days Since Last Profile').replace('# Profs Missing','Approx. Profiles Missed')
s=s.replace('Filter by communication status','Filter by data status').replace('communication filter','data-status filter').replace('last valid communication value','last valid profile date').replace('UTC transmission','UTC profile date')
s=s.replace('[data-detail-label="Expected next (+10 days)"]', '[data-detail-label="Expected Next Profile"]')
s=s.replace('Expected Next = upstream Last Profile Date +10 days','Expected Next Profile = Last Profile Date +10 days')
a=s.index('    if (oracle) {');b=s.index('    uiRows.push(',a)
s=s[:a]+'''    const days = r.last_profile_iso == null ? null :
      (Date.parse((displayedPayload || payload).generated_at) - Date.parse(r.last_profile_iso)) / 86400000;
    check(`WMO ${wmo}: unrounded elapsed days and floor(days/10)`, days == null ?
      r.days_since_last_profile == null && r.approx_profiles_missed == null :
      Math.abs(r.days_since_last_profile-days) < 2e-8 && r.approx_profiles_missed === Math.floor(days/10));
    check(`WMO ${wmo}: estimate tooltip is explicit`, await row.locator('[data-field="approx_profiles_missed"]').getAttribute('title') === NOTE);
    const detailStatus = await drawer.locator('[data-detail-label="Data Status"] > span').last().textContent();
    const detailMissed = await drawer.locator('[data-detail-label="Approx. Profiles Missed"] > span').last().textContent();
    check(`WMO ${wmo}: drawer status and estimate agree`, detailStatus === r.data_status && detailMissed === (r.approx_profiles_missed == null ? '—' : String(r.approx_profiles_missed)));
    for (const label of ['WMO','Internal ID','Float Type','Prof#','Latitude','Longitude','Last Profile Date','Expected Next Profile','Days Since Last Profile','Approx. Profiles Missed','Data Status']) {
      check(`WMO ${wmo}: drawer includes ${label}`, await drawer.locator(`[data-detail-label="${label}"]`).count() === 1);
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
    check(`WMO ${wmo}: profile wording only`, !/Last Communication|Last Transmission|No Transmission|No Communication|\\bdead\\b/i.test(visible));
'''+s[b:]
s=s.replace('''if ([2902223, 2902222, 1902844, 2902086, 2901305, 6902892].includes(wmo))''','''if ([2902223, 2902222, 1902844, 2902203, 2902086, 6902892].includes(wmo))''')
s=s.replace("'published profiles? source'", "'published profiles? source'")
s=s.replace('// Every row, all 11 requested fields. Expected Next is in the detail drawer.', '// Every real row: prof.nc JULD -> dates -> elapsed days -> estimate -> data status.')
s=s.replace('''  payload = displayedPayload || payload;
''','''  payload = displayedPayload || payload;
  check('monitoring source is prof.nc JULD', payload.source.monitoring === 'profile-recency' && payload.source.product.endsWith('<wmo>_prof.nc') && payload.source.field.startsWith('JULD'));
''')
p.write_text(s)
