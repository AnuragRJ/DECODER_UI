from pathlib import Path
from datetime import datetime
import json, subprocess, hashlib, csv
R=Path('/home/user/profile-recency-update')
repo=Path('/home/user/ARPY-decoder-Ui');prefix='incois-arpy-decoder/decoder-ui/'
records=json.loads((R/'verification.json').read_text())
payload=json.loads((R/'live-payload.json').read_text())
ui=json.loads((R/'browser/verification.json').read_text())
assert len(ui['uiRows'])==32 and all(t['passed'] for t in ui['results'])
scope=json.loads((R/'scope-verification.json').read_text())

def date(v):
    return datetime.fromisoformat(v).strftime('%Y-%m-%d %H:%M:%S UTC') if v else '—'

def value(v):return '—' if v is None else str(v)

examples=[]
for w in [2902223,1902844,2904082,7902408,2902224,2902203,2902086,6902892]:
    r=next(x for x in records if x['wmo']==w)
    examples.append('| '+' | '.join([str(w),date(r['last_profile_date_utc']),date(r['expected_next_profile_utc']),
        '—' if r['days_since_last_profile'] is None else f"{r['days_since_last_profile']:.6f}",value(r['approx_profiles_missed']),r['data_status']])+' |')

purposes={
 'service/fleet_status.py':'Profile-only monitoring calculation; independent primary profile refresh; source provenance and aggregate-lag notice. Existing position selector preserved.',
 'service/api.py':'Route documentation updated to describe profile/data recency.',
 'frontend/src/components/FloatStatusPage.tsx':'Requested labels, Data Status badges/filters, approximate estimate and exact tooltip, complete drawer fields, source-lag notice; same page design/navigation.',
 'frontend/src/types/index.ts':'Explicit profile-recency API fields and FleetDataStatus union; old monitoring fields are not reused with new meanings.',
 'frontend/src/utils/fleetStatus.ts':'New data-status ranking and sort fields; shared exact approximation note; existing UTC/coordinate/null formatting preserved.',
 'frontend/src/utils/fleetStatus.test.ts':'Update helper regression expectations to the new profile contract.',
 'frontend/src/components/FloatStatusPage.ssr.test.tsx':'New terminology/null/tooltip/map-input presentation regressions.',
 'frontend/e2e/fleetStatus.e2e.mjs':'Browser verifies all real profile chains, drawer fields, map behavior, interactions, source identity, outage warning and UTC display.',
 'tests/test_fleet_status.py':'Update existing service fixtures and assertions to use the full profile product for monitoring.',
 'tests/test_fleet_status_audit.py':'Retain parsing/position/cache regressions; adapt monitoring expectations and ensure old caches do not fall back to other products.',
 'tests/test_profile_recency.py':'New explicit source, boundary, approximation, null/fill/future and independent-refresh tests, including all 32 real-WMO fixture records.',
 'tests/fixtures/fleet_profile_recency.json':'Compact independently extracted public-profile evidence for 32 WMOs; URLs/hashes/dates only, no private operational identifiers.',
 'FLEET_STATUS.md':'Current source/selection/formula/API/UI/cache/test contract and limitations.'}
files=[]
for path in scope['changed_since_task_start']+scope['added_this_task']:
    name=path.split('decoder-ui/',1)[1]
    files.append(f'| `{name}` | {purposes[name]} |')

report=f'''# Float Status — profile-recency update completed

**Scope:** implementation changes confined to `incois-arpy-decoder/decoder-ui`.  
**Reference live API snapshot:** `{payload['generated_at']}`.  
**Result:** the page now monitors the newest valid profile `JULD` from the configured full `_prof.nc` history. It no longer calculates Data Status from trajectory message time.

## 1. What changed

The page now shows:

- **Last Profile Date**
- **Expected Next Profile**
- **Days Since Last Profile**
- **Data Status**
- **Approx. Profiles Missed**

WMO ID, Internal ID, Prof#, coordinates, Float Type, search, type/status filters,
sorting, pagination, row selection, marker selection and navigation remain.
The existing map renderer and coordinate-selection rule were not replaced.

The estimate's exact tooltip/note is:

> Approximate estimate based on the expected 10-day profile cycle.

The table/drawer no longer presents the exact published-file gap count as this
estimate. The exact inventory computation remains separate internally. No
profile timestamp is described as a telecom event.

## 2. Exact source and JULD selection

The primary monitoring product is:

```text
ftp://ftp.ifremer.fr/ifremer/argo/dac/incois/<WMO>/<WMO>_prof.nc
```

Independent verification used the same public product over HTTPS:

```text
https://data-argo.ifremer.fr/dac/incois/<WMO>/<WMO>_prof.nc
```

Selection, implemented in `service/fleet_status.py`:

1. Validate the NetCDF product and matching `PLATFORM_NUMBER` values.
2. Require `JULD[N_PROF]`, supported Argo UTC epoch units (days since 1950-01-01)
   and a supported Gregorian calendar.
3. Respect NetCDF masks/fill handling. Reject nonfinite, negative,
   sentinel/fill (`>=90000`) and future values.
4. Choose the **maximum valid JULD over every profile row**. Array order,
   highest cycle number and repeated BGC sensor grids do not choose the date.
5. Convert to aware UTC and retain the raw JULD, selected N_PROF index,
   measurement cycle and exact product filename. Sub-millisecond numerical
   noise around whole seconds is normalized consistently.

There is **no monitoring fallback** to an individual profile file,
`JULD_LOCATION`, Rtraj fields, file publication/processing timestamps, cache
timestamps or decoder-local data. In particular, `JULD_LAST_MESSAGE` is not
used by the monitoring formulas or status selector.

Date validity is not tied to a usable map position or successful scientific
parameter QC. A valid profile date can remain available with invalid/missing
coordinates; a valid coordinate can remain visible with no usable profile date.

## 3. Exact formulas and status boundaries

For selected profile time `t` and the API's current UTC `generated_at`:

```text
Last Profile Date       = max(valid prof.nc JULD)
Expected Next Profile   = t + 10 days
Days Since Last Profile = (generated_at - t).total_seconds() / 86400
Approx. Profiles Missed = floor(Days Since Last Profile / 10)
```

Calculations use **unrounded** elapsed days. The table shows completed days;
the drawer shows three decimal places. That display formatting does not feed
back into the estimate or status.

| Data Status | Rule |
|---|---|
| ACTIVE / RECENT PROFILE | 0 ≤ days ≤ 10 |
| PROFILE OVERDUE | 10 < days < 60 |
| NO RECENT PROFILE DATA 60+ DAYS | days ≥ 60 |
| NO DATA | No valid profile JULD from the configured history |

At exactly 10 days the status is still ACTIVE / RECENT PROFILE, while the
explicit requested formula gives an estimate of 1. At exactly 60 days the
status changes to NO RECENT PROFILE DATA 60+ DAYS and the estimate is 6.
Both boundaries are regression-tested.

No valid date means null date/expected-date/days/estimate fields and `—` in the
UI, with NO DATA. No value is fabricated. A valid old observation retained
through an outage remains labeled as cached/stale rather than replaced with a
made-up current date.

## 4. Real-WMO verification

For **all 32 configured WMOs**, the full chain was independently checked:

```text
public prof.nc JULD
  → Last Profile Date
  → Expected Next Profile
  → Days Since Last Profile
  → floor(days / 10)
  → Data Status
```

Thirty profile products were successfully downloaded; two configured-DAC
products returned 404. The 30 live FTP cache hashes match the independent HTTPS
product hashes. The following values are from the recorded live API snapshot,
not fixed demonstration dates:

| WMO | Last Profile Date | Expected Next Profile | Elapsed days | Approx. missed | Data Status |
|---|---|---|---:|---:|---|
{chr(10).join(examples)}

**Old trajectory/newer profile case:** 1902844 still has the old Rtraj message
value `2026-05-04T07:00:15+00:00`, but its monitoring date is now the aggregate
profile JULD `2026-09-08T14:04:11+00:00`. Its result is PROFILE OVERDUE because
that profile is more than 10 days old at the snapshot—not the former 60+ day
trajectory-based classification. Equivalent source independence was verified
for 2904082 and 7902408.

**Estimate versus inventory:** 2902223 has Prof# 353 and three published-file
gaps, but **Approx. Profiles Missed is 0** at this snapshot. 2902203 has eight
published-file gaps but **Approx. Profiles Missed is 11**. Neither gap list nor
local decode failures is used in the time-based estimate.

The full 32-WMO chain, raw source JULD/index/hash, exact inventory context and
calculation timestamp are in `verification.csv` / `verification.json`.

### Snapshot totals

| Total floats | Recent profile | Profile overdue | No recent profile data 60+ days | No data | Sum of known approximate estimates |
|---:|---:|---:|---:|---:|---:|
| {payload['summary']['total']} | {payload['summary']['recent_profile']} | {payload['summary']['profile_overdue']} | {payload['summary']['no_recent_profile_60']} | {payload['summary']['no_data']} | {payload['summary']['approx_profiles_missed_total']} |

The approximate total is **not an exact missing-file inventory**. Large values
for very old profiles follow the formula and do not establish a float's
physical state or an actual number of failed cycles.

## 5. Important live-source limitation found during this update

While verification was running, new individual profile files appeared for
three WMOs. The configured aggregate histories had not caught up:

| WMO | Date still in the configured prof.nc | New individual file | Its profile measurement date |
|---|---|---|---|
'''
for r in records:
    if r['aggregate_lagging_latest_file']:
        report+=f"| {r['wmo']} | {date(r['last_profile_date_utc'])} | `{r['latest_individual_profile']}` | {date(r['latest_individual_profile_date'])} |\n"
report+='''
**The implementation follows the requested product strictly.** It does not
replace the aggregate date with those newer individual dates. The drawer
shows a small explicit source-lag notice. The estimate and Data Status remain
based solely on `_prof.nc:JULD` until that product advances and is refreshed.

Prof# and the map legitimately picked up the newly published files/positions,
because their existing inventory and verified-position sources were kept.
Therefore their latest measurement time can differ from the aggregate
monitoring date; the drawer makes the distinction visible.

Position preservation was checked two ways:

- Against the identical pre-change cached inputs, all 32 identity/Prof#/
  coordinate/source/time fields were unchanged.
- Against the live refreshed inputs, the new application was compared with the
  **original position/inventory selector on the same refreshed source blocks**.
  All 32 agreed. Three actual coordinate/Prof# changes were explained by new
  upstream files, not a change in geographic selection behavior.

## 6. Refresh and failure behavior

The primary `_prof.nc` refresh is now independent of trajectory and individual
profile-inventory refreshes. A valid newer profile can reach the page even if
Rtraj or the inventory request fails. Each failing source retains its last
validated block, partial failures remain visible, and the whole-fleet
full-success timestamp is not advanced for a partial failure.

The first live update cycle revalidated 30 profile histories and verified two
configured-DAC absences: **30 updated / 2 unchanged / 0 failed**, completed at
`2026-09-21T07:30:36.906349+00:00`. A subsequent live check completed at
`2026-09-21T07:39:51.615071+00:00` with **0 updated / 32 unchanged / 0 failed**.

A separate copied registry/cache was subjected to a controlled loopback TCP
refusal at its FTP transport boundary. The real cached observations and last
full-success timestamp were retained, and the captured response displayed a
stale notice in the browser. This was an injected test, not an asserted live
Ifremer outage, and it did not replace the preview's working cache.

Old caches without full `_prof.nc` evidence cannot fabricate a date from
individual profiles or trajectories. Existing verified full-history cache
blocks remain readable and the new refresh contract revalidates them.

## 7. Files changed in this task

Paths are relative to `incois-arpy-decoder/decoder-ui/`:

| File | Change |
|---|---|
'''+chr(10).join(files)+'''

Scope was checked against hashes captured **before this change**, preserving
the prior authorized work already in the checkout. All changed/added source
files are inside decoder-ui. Every checked `src/argo_decoder/` file and the
checked-in historical `data/fleet_status/cache.json` remain unchanged. The map
renderer/model files are unchanged. No commit or push was performed.

Live preview/testing used `/home/user/profile-recency-update/runtime`, not the
checked-in cache or the preserved investigation caches. Existing preview
history was copied forward. The browser verification does not invoke batch decoding; the preview's mail
transport remains disabled via loopback/blank configuration.

## 8. Tests performed

| Check | Result |
|---|---|
| Backend/service pytest | **252 passed**, 55 dependency/fixture deprecation warnings |
| Frontend Vitest | **144 passed / 14 files** |
| TypeScript | **Pass** — `tsc --noEmit` |
| Ruff, changed Python parser/tests | **Pass** |
| Raw profile chain vs live API | **32/32 WMOs passed**, all five derived monitoring fields checked |
| Independent HTTPS vs live FTP products | **30/30 SHA-256 matches** |
| Browser E2E | **769/769 checks passed**, all 32 rows checked, no runtime page errors |
| Real map graphics | Coordinates match the API/table; verified selection rules preserved |
| Interactions | WMO/Internal ID search, all type/status filters, every sortable column both directions, pagination, actual marker click/FIT, drawer and back navigation |
| Terminology | New labels and approximation note checked; prohibited legacy monitoring labels absent from the page |
| Null/source safeguards | Missing/fill/nonfinite/future JULD, wrong product/WMO/units/dimension, no fallback, independent date/position validity |
| Formula boundaries | 0, just below/at/above 10, 20, just below/at 60, long gaps; exact floor estimate, UTC month/day arithmetic |
| Source independence | Mutating or removing Rtraj message metadata cannot change profile monitoring results |
| Cache failures | Profile/inventory/trajectory failures, partial success, stale retention, atomic persistence and controlled TCP refusal |

One initial browser assertion mixed a row from one response with the next
poll's calculation clock. The harness was corrected to keep each row and
`generated_at` from the same snapshot; no application formula change was
needed. The final full run passed.

Commands used:

```bash
# decoder-ui
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=service:../src \\
  env -u FLEET_SYNC_ENABLED python -m pytest tests -q
ruff check service/fleet_status.py tests/test_fleet_status.py \\
  tests/test_fleet_status_audit.py tests/test_profile_recency.py

# decoder-ui/frontend
npx tsc --noEmit
npm test
FLEET_E2E_BASE=http://127.0.0.1:3000 \\
FLEET_E2E_EXPECTED=/home/user/profile-recency-update/profile-oracle.json \\
FLEET_E2E_BASELINE=/home/user/profile-recency-update/same-source-position-baseline.json \\
FLEET_E2E_OUTAGE=/home/user/profile-recency-update/controlled-outage-payload.json \\
FLEET_E2E_REQUIRE_FRESH=1 npm run test:fleet
```

## 9. Remaining limitations

1. **Aggregate publication lag:** newer individual files can precede their
   aggregate update. The mandated aggregate remains authoritative for the new
   formulas; the page warns rather than silently changing products.
2. **Configured DAC:** 6902892 and 6903014 are unavailable in `dac/incois`.
   Other-DAC data is not silently substituted.
3. **Approximation:** the missed-profile number is elapsed-time arithmetic
   only; it is not the exact published-file gap count, a transmission metric,
   or a claim that a float actually attempted every estimated cycle.
4. **Source quality/currency:** this monitors available published profile
   dates, not live physical activity. Outages retain explicitly stale cached
   values. Scientific/position quality is not conflated with profile recency.
5. **Contract deployment:** the API fields and status strings changed to
   profile-specific names; frontend and backend must be deployed together.
6. **Build environment:** relevant tests, type checking and the actual Vite/
   browser app passed. A production bundle was not claimed; the earlier
   sandbox production-build memory limitation was not retried or concealed.

### Deliverables and evidence

- `verification.csv` / `.json`: complete 32-WMO source-to-formula chain.
- `profile-oracle.json`: independent raw-NetCDF maxima, indices and hashes.
- `live-payload.json`, `live-sync-cache*.json`: actual updated service evidence.
- `cached-comparison.log`, `same-source-position-baseline.json`: unchanged
  position/inventory behavior verification and explicit upstream changes.
- `backend-tests.log/.xml`, `frontend-tests.log`, `typecheck.log`, `ruff.log`.
- `browser-e2e.log`, `browser/verification.json`, `browser/*.png`: current page,
  full drawer cases and controlled-failure presentation.
- `scope-verification.json`: decoder-ui-only change proof.

The current preview remains available with the updated profile-recency logic.
'''
(R/'REPORT.md').write_text(report)
print('Completion report written:',len(report),'characters')
print('Verification rows:',len(records),'browser checks:',len(ui['results']))
print('Changed files:',len(scope['changed_since_task_start']),'new files:',len(scope['added_this_task']))
