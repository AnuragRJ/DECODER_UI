"""Preview launcher; observe, but do not trigger, scheduled profile sync."""
import json,threading,time
from pathlib import Path
from datetime import datetime,timezone
import uvicorn
R=Path('/home/user/profile-recency-update');start=datetime.now(timezone.utc)
(R/'server-started-at.txt').write_text(start.isoformat())
def observe():
    while True:
        try:
            d=json.loads((R/'runtime/fleet_status/cache.json').read_text());s=d['sync']
            attempt=s.get('last_attempt_at')
            if attempt and datetime.fromisoformat(attempt)>=start:
                (R/'live-sync-cache.json').write_text(json.dumps(d,indent=2))
                print('PROFILE_HISTORY_SYNC_FINISHED',json.dumps(s),flush=True)
                return
        except (OSError,ValueError,TypeError):pass
        time.sleep(2)
threading.Thread(target=observe,daemon=True).start()
uvicorn.run('main:app',app_dir='service',host='0.0.0.0',port=8000)
