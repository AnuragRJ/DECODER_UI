"""Read-only, independent oracle from downloaded public netCDF and local CSVs.
No import of fleet_status.py or its transformation helpers.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv, json, math, re
import netCDF4
import numpy as np

ROOT = Path('/home/user/float-status-audit')
PROJECT = Path('/home/user/ARPY-decoder-Ui/incois-arpy-decoder')
manifest = json.loads((ROOT/'upstream-downloads.json').read_text())
presets = {r['wmo']:r for r in json.loads((ROOT/'local-presets.json').read_text())}
baseline = {r['wmo']:r for r in json.loads((ROOT/'baseline/payload.json').read_text())['floats']}
aggregates = {r['wmo']:r for r in json.loads((ROOT/'aggregate-profile-downloads.json').read_text())}
EPOCH = datetime(1950,1,1,tzinfo=timezone.utc)
NOW = datetime.fromisoformat(manifest['audit_as_of'])
JNOW = (NOW-EPOCH).total_seconds()/86400
identity = {}
local_sources = {}
for rel, wcol, idcol in [('config/metadata/meta.csv','WMO id','Argos number'),
                        ('config/registry_apf9.csv','wmo','ptt'), ('config/registry.csv','wmo','ptt')]:
    with (PROJECT/rel).open(encoding='utf-8-sig',newline='') as f:
        for line,row in enumerate(csv.DictReader(f),2):
            text=(row.get(wcol) or '').strip()
            if not text.isdigit(): continue
            w=int(text)
            if w not in identity:
                v=(row.get(idcol) or row.get('imei') or '').strip()
                identity[w]=v or None
                local_sources[w]={'wmo':f'{rel}:{line} [{wcol}]',
                                  'internal_id':f'{rel}:{line} [{idcol}, else imei]'}
            if rel=='config/registry.csv' and w in presets and presets[w]['metadata_backend']!='csv4':
                local_sources[w]['float_type']=f'{rel}:{line} [platform_type]'


def number(var):
    return np.ma.asarray(var[:],dtype=float).filled(np.nan).reshape(-1)


def text(var):
    return np.ma.filled(var[:], b' ').tobytes().decode(errors='replace').strip()


def flags(ds,name,n):
    if name not in ds.variables: return ['']*n
    return np.ma.filled(ds[name][:],b' ').astype('U1').reshape(-1).tolist()


def utc(day):
    # Normalize sub-millisecond floating-point noise around a whole second.
    dt=EPOCH+timedelta(days=float(day))
    if dt.microsecond<1000: dt=dt.replace(microsecond=0)
    elif dt.microsecond>999000: dt=(dt+timedelta(seconds=1)).replace(microsecond=0)
    return dt.isoformat()


def valid(x): return math.isfinite(x) and 0<=x<90000 and x<=JNOW


def details(var):
    return {'dimensions':list(var.dimensions), 'shape':list(var.shape),
            'long_name':str(getattr(var,'long_name','')), 'units':str(getattr(var,'units','')),
            'fill_value':str(getattr(var,'_FillValue',''))}


def position_rows(ds,time_name,required_cycle=None):
    if any(n not in ds.variables for n in (time_name,'LATITUDE','LONGITUDE','POSITION_QC')):return []
    t,lat,lon=number(ds[time_name]),number(ds['LATITUDE']),number(ds['LONGITUDE'])
    q=flags(ds,'POSITION_QC',len(lat));cycles=number(ds['CYCLE_NUMBER']) if 'CYCLE_NUMBER' in ds.variables else []
    rows=[]
    for i,(time,la,lo) in enumerate(zip(t,lat,lon)):
        if not valid(time) or not(math.isfinite(la) and math.isfinite(lo) and abs(la)<=90 and abs(lo)<=180):continue
        if q[i] not in ('1','2'): continue
        if required_cycle is not None and (i>=len(cycles) or cycles[i]!=required_cycle):continue
        rows.append({'juld':float(time),'iso':utc(time),'lat':float(la),'lon':float(lo),
                     'qc':q[i],'index':i,'cycle':int(cycles[i]) if i<len(cycles) and math.isfinite(cycles[i]) else None,
                     'time_field':time_name})
    return rows

rows=[]
for item in manifest['floats']:
    w=item['wmo'];local=presets[w]
    sources=local_sources.get(w,{'wmo':'config/metadata/provor_cts4_301_reference.csv [wmo]; path_resolver._discover_cts4_presets',
                                 'internal_id':'No PTT/IMEI in local identity registries (sanitized CTS4 data)'})
    sources.setdefault('float_type', 'service/path_resolver.py:_discover_cts4_presets [platform_type=PROVOR_III]' if local['metadata_backend']=='cts4' else
                       'config/metadata/meta.csv + MultiCsvLoader.load_info(wmo).float_type → preset.platform_type')
    out={'wmo':w,'internal_id':identity.get(w),'float_type':local['platform_type'],'local_sources':sources,
         'in_incois_dac':item['rtraj']['status']==200,'last_tx_iso':None,'last_tx_field':None,
         'lat':None,'lon':None,'prof_num':None,'profile_count':None,'profiles_missing':None,'profiles_missing_list':[],
         'communication_evidence':None,'position_evidence':None,'profile_evidence':None,'meta_evidence':None}
    assert out['internal_id']==baseline[w]['internal_id'],(w,'identity mismatch')
    if item['rtraj']['status']!=200:
        assert item['listing']['status']==404 and str(w) not in manifest['membership']['wmos']
        out['availability_note']='No record in configured dac/incois; public dac/coriolis Rtraj independently confirmed by HEAD (not used without scope approval).'
        rows.append(out);continue
    with netCDF4.Dataset(item['rtraj']['path']) as ds:
        assert text(ds['PLATFORM_NUMBER'])==str(w)
        for field in ('JULD_LAST_MESSAGE','JULD_TRANSMISSION_END'):
            if field not in ds.variables:continue
            var=ds[field]; values=number(var)
            assert var.dimensions==('N_CYCLE',)
            assert str(var.units)=='days since 1950-01-01 00:00:00 UTC'
            valid_indices=[i for i,v in enumerate(values) if valid(float(v))]
            if not valid_indices:continue
            idx=max(valid_indices,key=lambda i:values[i]);value=float(values[idx])
            flag=flags(ds,field+'_STATUS',len(values))[idx]
            out['last_tx_iso']=utc(value);out['last_tx_field']=field
            out['communication_evidence']={'url':item['rtraj']['url'],'sha256':item['rtraj']['sha256'],
                'field':field,'index':idx,'raw_juld':value,'field_status':flag,**details(var)}
            break
        if out['last_tx_iso'] is None:
            out['availability_note']='No last-message or transmission-end field. Generic measurement JULD is not used.'
            if 'JULD_START_TRANSMISSION' in ds.variables:
                a=number(ds['JULD_START_TRANSMISSION']);ix=[i for i,x in enumerate(a) if valid(float(x))]
                if ix:
                    i=max(ix,key=lambda k:a[k])
                    out['other_upstream_evidence_not_used']={'field':'JULD_START_TRANSMISSION','raw_juld':float(a[i]),
                        'iso':utc(a[i]),'status':flags(ds,'JULD_START_TRANSMISSION_STATUS',len(a))[i],
                        'status_conventions':str(getattr(ds['JULD_START_TRANSMISSION_STATUS'],'conventions','')),
                        'reason':'Estimated transmission START, not the latest received message or transmission END.'}
        pos=position_rows(ds,'JULD')
        trajectory=max(pos,key=lambda p:p['juld']) if pos else None
        if trajectory:trajectory.update(source='traj',file=Path(item['rtraj']['path']).name,url=item['rtraj']['url'],sha256=item['rtraj']['sha256'])
    inventory=item['listing_summary']
    out.update(prof_num=inventory['max_cycle'],profile_count=inventory['available_cycles'],
               profiles_missing=len(inventory['missing']),profiles_missing_list=inventory['missing'])
    # Independently choose official core delayed before real-time, followed by B/S.
    priority={'D':0,'R':1,'BD':2,'BR':3,'SD':4,'SR':5}
    choices=[p for p in item['latest_profile_files'] if p['status']==200]
    latest=min(choices,key=lambda p:(priority[re.match(r'([A-Z]+)\d',Path(p['path']).name)[1]],Path(p['path']).name.endswith('D.nc'))) if choices else None
    profile_position=None
    if latest:
        with netCDF4.Dataset(latest['path']) as ds:
            pn=np.ma.filled(ds['PLATFORM_NUMBER'][:],b' ')
            for v in pn.reshape((-1,pn.shape[-1])):assert v.tobytes().decode().strip()==str(w)
            pp=position_rows(ds,'JULD_LOCATION',out['prof_num'])
            profile_position=max(pp,key=lambda p:p['juld']) if pp else None
            if profile_position:profile_position.update(source='profile',file=Path(latest['path']).name,url=latest['url'],sha256=latest['sha256'])
            profile_dates=[float(v) for v in number(ds['JULD']) if valid(float(v))]
            out['profile_evidence']={'file':Path(latest['path']).name,'url':latest['url'],'sha256':latest['sha256'],
                'listing_url':item['listing']['url'],'listing_sha256':item['listing']['sha256'],
                'max_cycle':out['prof_num'],'available_cycles':out['profile_count'],'missing':inventory['missing'],
                'measurement_iso':utc(max(profile_dates)) if profile_dates else None,
                'position_qc_values':flags(ds,'POSITION_QC',len(ds.dimensions['N_PROF'])),
                'lat_values':[float(x) if math.isfinite(x) else None for x in number(ds['LATITUDE'])],
                'lon_values':[float(x) if math.isfinite(x) else None for x in number(ds['LONGITUDE'])]}
    aggregate=aggregates[w]
    with netCDF4.Dataset(aggregate['path']) as ds:
        ap=position_rows(ds,'JULD_LOCATION')
        aggregate_position=max(ap,key=lambda p:p['juld']) if ap else None
        if aggregate_position:
            aggregate_position.update(source='profile',file=Path(aggregate['path']).name,url=aggregate['url'],sha256=aggregate['sha256'])
        out['full_profile_evidence']={'url':aggregate['url'],'sha256':aggregate['sha256'],
            'profile_rows':len(ds.dimensions['N_PROF']),'latest_valid_position':aggregate_position}
    positions=[p for p in (trajectory,profile_position,aggregate_position) if p]
    selected=max(positions,key=lambda p:(datetime.fromisoformat(p['iso']),p['source']=='traj')) if positions else None
    if selected:out.update(lat=selected['lat'],lon=selected['lon'],position_evidence=selected)
    with netCDF4.Dataset(item['meta']['path']) as ds:
        typ=text(ds['PLATFORM_TYPE']);pn=text(ds['PLATFORM_NUMBER'])
        assert pn==str(w) and typ==out['float_type'],(w,pn,typ,out['float_type'])
        out['meta_evidence']={'url':item['meta']['url'],'sha256':item['meta']['sha256'],
                              'PLATFORM_NUMBER':pn,'PLATFORM_TYPE':typ}
    rows.append(out)

result={'audit_as_of':manifest['audit_as_of'],'scope':'32 existing local presets; configured Ifremer DAC=incois',
        'oracle':'Independent numeric extraction: public HTTPS raw products + local CSV identity fields; no service parser imports',
        'floats':rows}
(ROOT/'expected-upstream.json').write_text(json.dumps(result,indent=2))
print('Independent evidence generated for all',len(rows),'WMOs')
print('WMO + Float Type match verified public metadata:',sum(r['meta_evidence'] is not None for r in rows))
print('Locally supplied Internal IDs matched:',sum(r['internal_id'] is not None for r in rows),'sanitized/unavailable:',sum(r['internal_id'] is None for r in rows))
print('Genuine latest-message timestamps:',sum(r['last_tx_iso'] is not None for r in rows))
print('Available profile cycles:',sum(r['profile_count'] or 0 for r in rows),'gaps:',sum(r['profiles_missing'] or 0 for r in rows))
