"""Isolated audit server; monitor scheduled cache commits without triggering sync."""
import json, threading, time
from datetime import datetime, timezone
from pathlib import Path
import uvicorn
ROOT=Path('/home/user/float-status-audit')
START=datetime.now(timezone.utc)
(ROOT/'api-started-at.txt').write_text(START.isoformat())
def observe():
    seen=set(); n=0
    while True:
        try:
            cache=json.loads((ROOT/'runtime/fleet_status/cache.json').read_text())
            sync=cache.get('sync',{});attempt=sync.get('last_attempt_at')
            if attempt and datetime.fromisoformat(attempt)>=START and attempt not in seen:
                seen.add(attempt);n+=1
                (ROOT/'scheduled-sync'/f'cycle-{n:02d}.json').write_text(json.dumps(cache,indent=2))
                print('FLEET_SCHEDULED_CACHE_COMMIT', json.dumps({'cycle':n,'version':cache.get('version'),'sync':sync,'rows':len(cache.get('rows',{}))}),flush=True)
                if n==2: print('FLEET_TWO_SCHEDULED_CYCLES_OBSERVED',flush=True)
        except (OSError,ValueError,TypeError): pass
        time.sleep(2)
threading.Thread(target=observe,daemon=True).start()
uvicorn.run('main:app',host='0.0.0.0',port=8000,app_dir='service',log_level='info')
