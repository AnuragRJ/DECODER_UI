"""Start unchanged API; record the completion of its ordinary startup sync."""
from pathlib import Path
from datetime import datetime,timezone
import json,threading,time
import uvicorn
ROOT=Path('/home/user/profile-recency-update');OUT=ROOT/'follow-up'
started=datetime.now(timezone.utc)
def observe():
    while True:
        try:
            data=json.loads((ROOT/'runtime/fleet_status/cache.json').read_text())
            attempt=data['sync'].get('last_attempt_at')
            if attempt and datetime.fromisoformat(attempt)>=started:
                (OUT/'cache-after-sync.json').write_text(json.dumps(data,indent=2))
                print('PROFILE_REFRESH_COMPLETED',json.dumps(data['sync']),flush=True)
                return
        except (OSError,ValueError,TypeError):pass
        time.sleep(2)
threading.Thread(target=observe,daemon=True).start()
uvicorn.run('main:app',app_dir='service',host='0.0.0.0',port=8000)
