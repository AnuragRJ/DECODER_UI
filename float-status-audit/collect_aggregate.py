from pathlib import Path
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
import json,hashlib,numpy as np,netCDF4
ROOT=Path('/home/user/float-status-audit'); RAW=Path('/home/user/.cache/float-status-audit/upstream')
items=json.loads((ROOT/'aggregate-profile-sizes.json').read_text())
def fetch(item):
    r=dict(item);r['retrieved_at']=datetime.now(timezone.utc).isoformat()
    with urlopen(r['url'],timeout=25) as response: data=response.read()
    file=RAW/str(r['wmo'])/f"{r['wmo']}_prof.nc";file.write_bytes(data)
    r.update(path=str(file),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data));return r
with ThreadPoolExecutor(max_workers=4) as pool: records=list(pool.map(fetch,items))
(ROOT/'aggregate-profile-downloads.json').write_text(json.dumps(records,indent=2))
old={r['wmo']:r for r in json.loads((ROOT/'expected-upstream.json').read_text())['floats']}
now=(datetime.now(timezone.utc)-datetime(1950,1,1,tzinfo=timezone.utc)).total_seconds()/86400
for row in records:
 with netCDF4.Dataset(row['path']) as d:
  a=lambda n:np.ma.asarray(d[n][:],dtype=float).filled(np.nan).ravel()
  j,la,lo=a('JULD_LOCATION'),a('LATITUDE'),a('LONGITUDE');qc=np.ma.filled(d['POSITION_QC'][:],b' ').astype('U1').ravel()
  mask=(j>=0)&(j<=now)&np.isfinite(j)&np.isfinite(la)&np.isfinite(lo)&(abs(la)<=90)&(abs(lo)<=180)&np.isin(qc,['1','2'])
  ids=np.where(mask)[0]
  if not len(ids): continue
  i=max(ids,key=lambda k:j[k]);prev=old[row['wmo']]['position_evidence']
  if prev is None or j[i]>prev['juld']:
   print('NEWER VALID PROFILE POSITION',row['wmo'],'cycle',int(a('CYCLE_NUMBER')[i]), 'index',int(i),'coords',float(la[i]),float(lo[i]),'location time',(datetime(1950,1,1,tzinfo=timezone.utc)+timedelta(days=float(j[i]))).isoformat(),'vs',prev,flush=True)
print('Downloaded all 30 full-profile products, bytes',sum(r['bytes'] for r in records))
