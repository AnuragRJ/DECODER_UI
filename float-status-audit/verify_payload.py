"""Compare final served values, persisted FTP cache and independent HTTPS oracle.
Create a separately isolated, explicit FTP-refusal experiment. Does not change
any repository data or the running server's cache.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen
import copy, csv, ftplib, json, math, os, shutil, sys

ROOT=Path('/home/user/float-status-audit')
expected={r['wmo']:r for r in json.loads((ROOT/'expected-upstream.json').read_text())['floats']}
with urlopen('http://127.0.0.1:8000/api/fleet-status',timeout=20) as r: payload=json.load(r)
(ROOT/'final-payload.json').write_text(json.dumps(payload,indent=2))
cache=json.loads((ROOT/'runtime/fleet_status/cache.json').read_text())
assert payload['sync']['status']=='ok' and not payload['sync']['stale'] and not payload['sync']['running'],payload['sync']
assert len(payload['floats'])==len(expected)==32
asof=datetime.fromisoformat(payload['generated_at'])
comparisons=[]
labels={'wmo':'WMO ID','internal_id':'Internal ID','float_type':'Float Type','lat':'Latitude','lon':'Longitude',
        'last_tx_iso':'Last Transmission','expected_next_iso':'Expected Next Communication',
        'days_since_last_tx':'No Communication / elapsed days','status':'Communication Status',
        'prof_num':'Prof# (highest cycle)','profiles_missing':'Profiles Missing'}
for actual in payload['floats']:
    w=actual['wmo']; truth=expected[w];stored=cache['rows'][str(w)]
    tx=datetime.fromisoformat(truth['last_tx_iso']) if truth['last_tx_iso'] else None
    days=(asof-tx).total_seconds()/86400 if tx else None
    want=dict(truth, expected_next_iso=(tx+timedelta(days=10)).isoformat() if tx else None,
              days_since_last_tx=days,status='NO DATA' if days is None else 'ACTIVE' if days<=10 else 'OVERDUE' if days<60 else 'NO COMMUNICATION 60+ DAYS')
    if truth['in_incois_dac']:
        rtraj=stored['rtraj'];profiles=stored['profiles']
        download=next(r for r in json.loads((ROOT/'upstream-downloads.json').read_text())['floats'] if r['wmo']==w)
        assert rtraj['sha256']==download['rtraj']['sha256'],(w,'FTP/HTTPS Rtraj byte mismatch')
        assert profiles['latest_parse']['sha256']==truth['profile_evidence']['sha256'],(w,'FTP/HTTPS profile byte mismatch')
        assert stored['profile_aggregate']['sha256']==truth['full_profile_evidence']['sha256'],(w,'FTP/HTTPS full profile byte mismatch')
        if truth['last_tx_iso']:
            assert actual['last_tx_index']==truth['communication_evidence']['index']
            assert actual['last_tx_status_rt19']==truth['communication_evidence']['field_status']
        assert actual['position_file']==truth['position_evidence']['file'],(w,'position file',actual['position_file'],truth['position_evidence']['file'])
        assert actual['position_time_field']==truth['position_evidence']['time_field']
    assert actual['profile_count']==truth['profile_count']
    assert actual['profiles_missing_list']==truth['profiles_missing_list']
    for field,label in labels.items():
        a,b=actual[field],want[field]
        if field in ('lat','lon','days_since_last_tx') and a is not None and b is not None:
            passed=abs(a-b)<1e-8
        elif field in ('last_tx_iso','expected_next_iso') and a and b:
            passed=abs((datetime.fromisoformat(a)-datetime.fromisoformat(b)).total_seconds())<=0.001
        else: passed=a==b
        assert passed,(w,field,a,b)
        if field in ('wmo','internal_id','float_type'):
            source=truth['local_sources'][field]
            verification='LOCAL SOURCE MATCH (sanitized/unavailable)' if field=='internal_id' and b is None else 'LOCAL SOURCE MATCH'
            if field in ('wmo','float_type') and truth['meta_evidence']:
                source += ' | '+truth['meta_evidence']['url']+' ['+('PLATFORM_NUMBER' if field=='wmo' else 'PLATFORM_TYPE')+']'
                verification='LOCAL + UPSTREAM VERIFIED'
        elif field in ('lat','lon'):
            e=truth['position_evidence']
            source=(e['url']+f" [{'LATITUDE' if field=='lat' else 'LONGITUDE'} index {e['index']}; {e['time_field']}; POSITION_QC={e['qc']}]") if e else truth.get('availability_note','unavailable')
            verification='UPSTREAM VERIFIED' if e else 'VERIFIED UNAVAILABLE IN CONFIGURED DAC'
        elif field in ('prof_num','profiles_missing'):
            e=truth['profile_evidence']; source=e['listing_url']+' [recognized filenames; distinct positive cycles]' if e else truth.get('availability_note','unavailable')
            verification='UPSTREAM LISTING VERIFIED' if e else 'VERIFIED UNAVAILABLE IN CONFIGURED DAC'
        else:
            e=truth['communication_evidence']
            source=e['url']+f" [{e['field']} index {e['index']}; raw JULD={e['raw_juld']}]" if e else truth.get('availability_note','unavailable')
            verification='UPSTREAM VERIFIED' if field=='last_tx_iso' and e else 'POLICY CALCULATION VERIFIED' if e else 'UNAVAILABLE; NOT INFERRED'
        comparisons.append({'wmo':w,'field':label,'api_field':field,'api_value':a,'independent_value':b,
                            'source':source,'verification':verification,'passed':passed,'calculated_at_utc':payload['generated_at']})
print('PASS:',len(comparisons),'requested field comparisons across all 32 existing WMOs')
print('PASS: 90 FTP/HTTPS byte-hash comparisons (30 Rtraj + 30 latest-profile + 30 full-history products)')
print('SUMMARY',payload['summary'])
with (ROOT/'field-comparisons.csv').open('w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(comparisons[0]));writer.writeheader();writer.writerows(comparisons)
(ROOT/'field-comparisons.json').write_text(json.dumps(comparisons,indent=2))

# Frozen-clock BEFORE/AFTER comparison: read baseline implementation from the
# original Git object, not by changing source files in the repository.
import importlib.util, subprocess
source=subprocess.check_output(['git','show','HEAD:incois-arpy-decoder/decoder-ui/service/fleet_status.py'],cwd='/home/user/ARPY-decoder-Ui',text=True)
file=ROOT/'baseline/original_fleet_status.py';file.write_text(source)
spec=importlib.util.spec_from_file_location('original_fleet_status_for_audit',file)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module._utcnow=lambda:asof
oldreg=module.FleetSyncRegistry(state_path=ROOT/'baseline/cache.json', enabled=False)
oldpayload=oldreg.payload();(ROOT/'baseline/fixed-clock-payload.json').write_text(json.dumps(oldpayload,indent=2))
oldrows={r['wmo']:r for r in oldpayload['floats']}
changes=[]
for row in payload['floats']:
    old=oldrows[row['wmo']]
    for field in labels:
        if old[field]!=row[field]:
            significant = not (field in ('last_tx_iso','expected_next_iso') and old[field] and row[field] and
                               abs((datetime.fromisoformat(old[field])-datetime.fromisoformat(row[field])).total_seconds())<0.001)
            changes.append({'wmo':row['wmo'],'field':field,'before':old[field],'after':row[field],'significant':significant})
(ROOT/'before-after.json').write_text(json.dumps({'as_of':asof.isoformat(),'before_summary':oldpayload['summary'],
    'after_summary':payload['summary'],'changes':changes},indent=2))
print('Changed coordinate pairs:',len({r['wmo'] for r in changes if r['field'] in ('lat','lon')}))
print('Communication timestamps made unavailable instead of substituted:',[r['wmo'] for r in changes if r['field']=='last_tx_iso' and r['after'] is None])

# Real TCP refusal as a deliberate transport-boundary failure, not a claim
# that Ifremer is down. The production cache/server are never changed.
import fleet_status as fs
failure=ROOT/'failure-experiment/cache.json';failure.parent.mkdir(exist_ok=True)
shutil.copyfile(ROOT/'runtime/fleet_status/cache.json',failure)
reg=fs.FleetSyncRegistry(state_path=failure, enabled=True, interval_s=21600)
before=copy.deepcopy(reg._rows);success=reg.payload()['sync']['last_success_at']
def refused_transport():
    conn=ftplib.FTP(timeout=1)
    conn.connect('127.0.0.1',9)
    return conn
reg._connect=refused_transport
outcome=reg.sync_now();after=json.loads(failure.read_text())
assert outcome['status']=='error' and before==after['rows']
assert reg.payload()['sync']['last_success_at']==success
outage=reg.payload();assert outage['sync']['stale']
(ROOT/'controlled-outage-payload.json').write_text(json.dumps(outage,indent=2))
(ROOT/'failure-experiment/result.json').write_text(json.dumps({'experiment':'Controlled loopback TCP port 9 refusal injected at FTP transport boundary; NOT a live Ifremer outage',
    'outcome':outcome,'rows_unchanged':True,'last_success_unchanged':True,'record_count':len(before)},indent=2))
print('PASS: controlled FTP TCP refusal preserved all 32 valid cached rows and the previous full-success timestamp')
