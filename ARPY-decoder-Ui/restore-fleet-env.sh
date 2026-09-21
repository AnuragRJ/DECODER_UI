#!/bin/bash
# Restore the Float Status dev environment after a sandbox reboot.
# (Only /home/user persists: processes, site-packages, node_modules, dist/
#  and Playwright browsers are wiped on every reboot.)
# Usage: bash /home/user/restore-fleet-env.sh
# Note: start the server separately via the process tools, then wait for the
# GDAC sync (fast skip-sync from decoder-ui/data/fleet_status/cache.json).
set -u
ROOT=/home/user/incois-arpy-decoder
UI=$ROOT/decoder-ui

echo "=== 1/5 pip deps ==="
pip install -r $UI/service/requirements.txt 2>&1 | tail -1
python3 -c "import fastapi, netCDF4; print('py deps OK')"

echo "=== 2/5 npm deps ==="
(cd $UI/frontend && npm install 2>&1 | tail -1)
ls $UI/frontend/node_modules/.bin/tsc >/dev/null && echo "node deps OK"

echo "=== 3/5 backend suite ==="
(cd $UI && PYTHONPATH=service:$ROOT/src python3 -m pytest tests/ -q 2>&1 | tail -1)

echo "=== 4/5 frontend build + suite ==="
(cd $UI/frontend && npm run build 2>&1 | tail -1)
(cd $UI/frontend && npx vitest run 2>&1 | grep -E "Test Files|Tests ")

echo "=== 5/5 playwright chromium (for npm run test:fleet) ==="
(cd $UI/frontend && npx playwright install chromium 2>&1 | tail -1)
(cd $UI/frontend && (sudo -n npx playwright install-deps chromium 2>&1 | tail -1 || true))
echo RESTORE-DONE
