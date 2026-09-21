"""Independent prof.nc -> live API verification; isolated outage experiment."""
from pathlib import Path
from urllib.request import urlopen
from datetime import datetime, timedelta
import copy, csv, ftplib, importlib.util, json, math, shutil

R=Path('/home/user/profile-recency-update')
oracle={r['wmo']:r for r in json.loads((R/'profile-oracle.json').read_text())['floats']}
before={r['wmo']:r for r in json.loads((R/'baseline/payload.json').read_text())['floats']}
with urlopen('http://127.0.0.1:3000/api/fleet-status',timeout=25) as resp:
    payload=json.load(resp)
assert payload['source']['monitoring']=='profile-recency'
assert payload['source']['product']=='dac/incois/<wmo>/<wmo>_prof.nc'
assert payload['sync']['status']=='ok' and not payload['sync']['stale'] and not payload['sync']['running'],payload['sync']
cache=json.loads((R/'runtime/fleet_status/cache.json').read_text())
now=datetime.fromisoformat(payload['generated_at'])
# Compare the unchanged position/inventory selector on identical CURRENT
# source blocks. Three new individual profile files appeared after baseline.
spec=importlib.util.spec_from_file_location('before_profile_monitor',R/'baseline/service/fleet_status.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
position_expected=[]
for w,b in before.items():
    position_expected.append(module.FleetSyncRegistry._serve_row(w,cache['rows'].get(str(w)),
        {'platform_type':b['float_type'],'transmission_type':b['transmission_type']},
        {'ptt':b['ptt'] or '', 'imei':b['imei'] or ''},now))
(R/'same-source-position-baseline.json').write_text(json.dumps({'generated_at':payload['generated_at'],'floats':position_expected},indent=2))
position_expected={r['wmo']:r for r in position_expected}
records=[]
for row in payload['floats']:
    w=row['wmo'];expected=oracle[w];old=before[w];same_source=position_expected[w]
    assert 'last_tx_iso' not in row and 'days_since_last_tx' not in row
    assert row['last_profile_iso']==expected['last_profile_iso'],(w,'date')
    assert row['last_profile_index']==expected['last_profile_index'],(w,'N_PROF index')
    assert row['last_profile_file']==f'{w}_prof.nc'
    assert row['last_profile_field']=='JULD'
    for key in ('internal_id','float_type','prof_num','lat','lon','pos_source','pos_qc','position_iso','position_file'):
        assert row[key]==same_source[key],(w,key,'position/inventory rule changed on identical source data')
    if expected['last_profile_iso'] is not None:
        date=datetime.fromisoformat(expected['last_profile_iso']);days=(now-date).total_seconds()/86400
        next_date=(date+timedelta(days=10)).isoformat();missed=math.floor(days/10)
        status='ACTIVE / RECENT PROFILE' if days<=10 else 'PROFILE OVERDUE' if days<60 else 'NO RECENT PROFILE DATA 60+ DAYS'
        assert row['last_profile_juld']==expected['last_profile_juld']
        assert cache['rows'][str(w)]['profile_aggregate']['sha256']==expected['source']['sha256'],(w,'FTP/HTTPS byte mismatch')
    else:
        days=None;next_date=None;missed=None;status='NO DATA'
    assert row['expected_next_profile_iso']==next_date
    assert row['days_since_last_profile']==days
    assert row['approx_profiles_missed']==missed
    assert row['data_status']==status
    records.append({'wmo':w,'source_url':expected['source']['url'],'source_http_status':expected['source']['status'],
                    'source_sha256':expected['source'].get('sha256'),'raw_profile_juld':expected['last_profile_juld'],
                    'n_prof_index':expected['last_profile_index'],'last_profile_date_utc':row['last_profile_iso'],
                    'expected_next_profile_utc':next_date,'days_since_last_profile':days,'approx_profiles_missed':missed,
                    'data_status':status,'inventory_prof_num':row['prof_num'],'exact_inventory_gap_count':row['profiles_missing'],
                    'previous_rtraj_message_utc':old['last_tx_iso'],'previous_status':old['status'],
                    'position_rule_unchanged':True,'upstream_position_changed_since_baseline':row['lat']!=old['lat'] or row['lon']!=old['lon'],
                    'aggregate_lagging_latest_file':row.get('profile_history_lagging_latest_file'),
                    'latest_individual_profile':(row.get('latest_profile') or {}).get('file'),
                    'latest_individual_profile_date':(row.get('latest_profile') or {}).get('juld_iso'),'calculated_at_utc':payload['generated_at'],'result':'PASS'})
assert len(records)==32
assert payload['summary']['approx_profiles_missed_total']==sum(r['approx_profiles_missed'] or 0 for r in records)
(R/'live-payload.json').write_text(json.dumps(payload,indent=2))
(R/'verification.json').write_text(json.dumps(records,indent=2))
with (R/'verification.csv').open('w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
print('PASS: all 32 prof.nc JULD -> date -> expected next -> elapsed -> floor estimate -> data status chains')
print('PASS: 30 independently retrieved HTTPS products match the live FTP cache byte hashes')
print('PASS: all identities, Prof# and positions match the unchanged selector on identical current sources')
print('SUMMARY',payload['summary'])
for row in records:
    if row['wmo'] in (2902223,1902844,2904082,7902408,2902224,2902203,6902892):print(row)

# Real TCP refusal injected into an independent registry/cache copy only.
import fleet_status as fs
path=R/'controlled-outage/cache.json';path.parent.mkdir(exist_ok=True)
shutil.copyfile(R/'runtime/fleet_status/cache.json',path)
registry=fs.FleetSyncRegistry(state_path=path,enabled=True)
original=copy.deepcopy(registry._rows);last_success=registry.payload()['sync']['last_success_at']
def refused():
    ftp=ftplib.FTP(timeout=1);ftp.connect('127.0.0.1',9);return ftp
registry._connect=refused
outcome=registry.sync_now()
assert outcome['status']=='error'
assert registry._rows==original
assert registry.payload()['sync']['last_success_at']==last_success
outage=registry.payload();assert outage['sync']['stale']
(R/'controlled-outage-payload.json').write_text(json.dumps(outage,indent=2))
(R/'controlled-outage/result.json').write_text(json.dumps({'test':'Isolated loopback TCP refusal, not an Ifremer outage','rows_preserved':True,'last_success_preserved':True,'outcome':outcome},indent=2))
print('PASS: controlled FTP outage preserved all real cached observations and full-success timestamp')
