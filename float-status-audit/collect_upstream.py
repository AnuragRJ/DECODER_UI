"""Download public Ifremer audit evidence only; never writes into the repository.
Downloads are separated from subsequent (single-threaded) netCDF inspection.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import hashlib
import json
import re

ROOT = Path('/home/user/float-status-audit')
RAW = Path('/home/user/.cache/float-status-audit/upstream')
RAW.mkdir(parents=True, exist_ok=True)
BASE = 'https://data-argo.ifremer.fr/dac/incois/'
NOW = datetime.now(timezone.utc).isoformat()
WMOS = sorted(int(w) for w in json.loads((ROOT/'baseline/cache.json').read_text())['rows'])
PROFILE = re.compile(r'^(BD|BR|SD|SR|D|R)(\d{7})_(\d{3,4})(D?)\.nc$')

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.names=[]
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for k,v in attrs:
                if k=='href' and v:
                    self.names.append(unquote(urlparse(v).path).rstrip('/').rsplit('/',1)[-1])


def get(url, file):
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        with urlopen(Request(url,headers={'User-Agent':'Argo-Float-Status-ReadOnly-Audit/1.0'}), timeout=25) as r:
            body=r.read(); headers=dict(r.headers)
            file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(body)
            return {'url':url,'status':r.status,'retrieved_at':stamp,'headers':headers,
                    'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body),'path':str(file)}
    except HTTPError as e:
        return {'url':url,'status':e.code,'retrieved_at':stamp,'error':str(e)}
    except Exception as e:
        return {'url':url,'status':None,'retrieved_at':stamp,'error':f'{type(e).__name__}: {e}'}


def one(wmo):
    folder=RAW/str(wmo); out={'wmo':wmo}
    for key,name in (('rtraj',f'{wmo}_Rtraj.nc'),('meta',f'{wmo}_meta.nc')):
        out[key]=get(BASE+f'{wmo}/{name}', folder/name)
    out['listing']=get(BASE+f'{wmo}/profiles/',folder/'profiles.html')
    if out['listing']['status']==200:
        p=Links();p.feed((folder/'profiles.html').read_text(errors='replace'))
        names=sorted(set(n for n in p.names if PROFILE.fullmatch(n) and int(PROFILE.fullmatch(n)[2])==wmo))
        out['profile_names']=names
        cycles=sorted(set(int(PROFILE.fullmatch(n)[3]) for n in names))
        maxcycle=max(cycles) if cycles else None
        # Retrieve all products at the highest listed cycle to expose any family disagreement.
        latest=[n for n in names if int(PROFILE.fullmatch(n)[3])==maxcycle]
        out['latest_profile_files']=[get(BASE+f'{wmo}/profiles/{n}',folder/n) for n in latest]
        out['listing_summary']={'max_cycle':maxcycle,'available_cycles':len([c for c in cycles if c>0]),
            'unique_cycles_including_zero':len(cycles),'file_count':len(names),
            'missing':[c for c in range(1,(maxcycle or 0)+1) if c not in cycles],
            'cycle_zero':0 in cycles}
    return out

membership=get(BASE,RAW/'incois-membership.html')
if membership.get('status')==200:
    p=Links();p.feed((RAW/'incois-membership.html').read_text(errors='replace'))
    membership['wmos']=sorted(set(n for n in p.names if re.fullmatch(r'\d{7}',n)))
records=[]
with ThreadPoolExecutor(max_workers=4) as pool:
    futures={pool.submit(one,w):w for w in WMOS}
    for future in as_completed(futures):
        row=future.result();records.append(row)
        print(row['wmo'],'Rtraj',row['rtraj']['status'],'meta',row['meta']['status'],
              'listing',row['listing']['status'],row.get('listing_summary'),flush=True)
result={'audit_as_of':NOW,'retrieved_by':'independent public HTTPS retrieval; no service parsing functions used',
        'membership':membership,'floats':sorted(records,key=lambda r:r['wmo'])}
(ROOT/'upstream-downloads.json').write_text(json.dumps(result,indent=2))
print('Saved evidence manifest for',len(records),'existing WMOs',flush=True)
