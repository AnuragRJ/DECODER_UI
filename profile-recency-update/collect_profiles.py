"""Independent, read-only public profile oracle. Does not import service code."""
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import hashlib, json, math
import netCDF4
import numpy as np

ROOT=Path('/home/user/profile-recency-update')
RAW=Path('/home/user/.cache/profile-recency-update');RAW.mkdir(parents=True,exist_ok=True)
cache=json.loads((ROOT/'baseline/runtime-cache.json').read_text())
wmos=sorted(int(w) for w in cache['rows'])
now=datetime.now(timezone.utc)
epoch=datetime(1950,1,1,tzinfo=timezone.utc)
now_j=(now-epoch).total_seconds()/86400

def retrieve(wmo):
    url=f'https://data-argo.ifremer.fr/dac/incois/{wmo}/{wmo}_prof.nc'
    out={'wmo':wmo,'url':url,'retrieved_at':datetime.now(timezone.utc).isoformat()}
    try:
        with urlopen(Request(url,headers={'User-Agent':'Argo-profile-recency-verification/1.0'}),timeout=30) as r:
            data=r.read();file=RAW/f'{wmo}_prof.nc';file.write_bytes(data)
            out.update(status=r.status,path=str(file),bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),last_modified=r.headers.get('Last-Modified'))
    except HTTPError as exc:out.update(status=exc.code,error=str(exc))
    except Exception as exc:out.update(status=None,error=str(exc))
    return out

with ThreadPoolExecutor(max_workers=4) as pool:
    files=list(pool.map(retrieve,wmos))
records=[]
for source in files:
    w=source['wmo'];record={'wmo':w,'source':source,'last_profile_juld':None,'last_profile_iso':None,'last_profile_index':None,'last_profile_cycle':None}
    if source['status']==200:
        with netCDF4.Dataset(source['path']) as ds:
            assert ds['JULD'].dimensions==('N_PROF',)
            assert str(ds['JULD'].units)=='days since 1950-01-01 00:00:00 UTC'
            p=np.ma.filled(ds['PLATFORM_NUMBER'][:],b' ')
            for chars in p.reshape((-1,p.shape[-1])):
                assert chars.tobytes().decode().strip()==str(w)
            a=np.ma.asarray(ds['JULD'][:],dtype=float).filled(np.nan).ravel()
            valid=[(i,float(v)) for i,v in enumerate(a) if math.isfinite(v) and 0<=v<90000 and v<=now_j]
            record.update(n_prof=len(a),valid_juld_count=len(valid),juld_units=str(ds['JULD'].units),juld_long_name=str(ds['JULD'].long_name))
            if valid:
                i,j=max(valid,key=lambda v:v[1])
                # Independent CF time conversion, then normalize <1 ms float jitter.
                cf=netCDF4.num2date(j,ds['JULD'].units,only_use_cftime_datetimes=False)
                dt=datetime(cf.year,cf.month,cf.day,cf.hour,cf.minute,cf.second,cf.microsecond,tzinfo=timezone.utc)
                if dt.microsecond<1000:dt=dt.replace(microsecond=0)
                elif dt.microsecond>999000:dt=(dt+timedelta(seconds=1)).replace(microsecond=0)
                c=ds['CYCLE_NUMBER'][i] if 'CYCLE_NUMBER' in ds.variables else None
                c=int(c) if c is not None and not np.ma.is_masked(c) and 0<=c<99999 else None
                record.update(last_profile_juld=j,last_profile_iso=dt.isoformat(),last_profile_index=i,last_profile_cycle=c)
    records.append(record)
    print(w,source['status'],record['last_profile_iso'],flush=True)
(ROOT/'profile-oracle.json').write_text(json.dumps({'retrieved_as_of':now.isoformat(),'selection':'Independent raw *_prof.nc JULD maximum over valid N_PROF entries','floats':records},indent=2))
print('Completed',len(records),'real WMOs;',sum(r['source']['status']==200 for r in records),'published profile products')
