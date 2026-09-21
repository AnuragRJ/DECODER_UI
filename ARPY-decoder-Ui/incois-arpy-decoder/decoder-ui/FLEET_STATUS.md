# Float Status — published profile/data-recency monitoring

Float Status now monitors the age of the latest **published profile**, not
telecom activity. The page retains its existing layout, navigation, filters,
sorting, pagination, drawer and verified position/map behavior.

The same page carries one additive, clearly-labelled companion feature — the
experimental **Next Profile Location** prediction block and its opt-in map
layer. It never replaces a monitoring field and never changes any status
wording; its contract, refusal rules and uncertainty provenance are documented
in [PREDICTION.md](PREDICTION.md).

## Authoritative monitoring source

For every existing local WMO preset, the configured source is:

```text
ftp://ftp.ifremer.fr/ifremer/argo/dac/incois/<WMO>/<WMO>_prof.nc
```

The corresponding public HTTPS product used for independent verification is:

```text
https://data-argo.ifremer.fr/dac/incois/<WMO>/<WMO>_prof.nc
```

The configured DAC remains `incois`. No new WMO, private identity or alternative
DAC is introduced. The monitored fleet is exactly the set of floats discovered
from the shared local metadata presets (`config/metadata` CSV4 set plus
`config/registry*.csv`); every float in that set resolves to a `<WMO>_prof.nc`
product in this configured DAC.

**Only `JULD[N_PROF]` in this complete `_prof.nc` history drives monitoring.**
There is no fallback to a highest-cycle individual profile, a trajectory
message field, location time, local decoder result, file-arrival time,
`DATE_UPDATE`, file mtime or cache update time.

## Exact JULD selection

`service/fleet_status.py:parse_profile(raw, wmo, filename_cycle=None)`:

1. Open the upstream NetCDF product and verify its `PLATFORM_NUMBER` values
   against the requested WMO.
2. Require `JULD` to use the `N_PROF` dimension, supported Argo epoch units
   (days since 1950-01-01 00:00:00 UTC) and a supported Gregorian calendar.
3. Read `JULD` with NetCDF masks respected; masked/fill values become NaN.
4. Exclude nonfinite, negative, fill/sentinel (`>=90000`) and future values.
   Missing `JULD` or no eligible value produces no profile date.
5. Select the **maximum valid JULD across all profile rows**. Do not assume
   array order or cycle-number order is chronological. Repeated BGC grids do
   not alter the maximum.
6. Convert the selected value to timezone-qualified UTC. Normalize only
   sub-millisecond floating-point noise around whole seconds, avoiding an
   accidental preceding-minute display. Retain its `N_PROF` index and cycle
   as provenance.

If a newer individual profile exists before it appears in the aggregate, a
small detail warning states that the history product is behind. The warning
never changes the selected date, formulas or status. This distinction was
observed live during verification for 1902844, 2904082 and 7902408.

This is a date-validity rule, not a requirement that every scientific
measurement or position pass QC. Profile time is independent of position QC
and `JULD_LOCATION`. Missing or invalid position information must not suppress
an otherwise usable profile date. An unreadable/foreign/time-axis-invalid
product is a source error, not permission to fabricate another date.

## Monitoring formulas and labels

Let `t` be the selected profile time and `now` the API snapshot's current UTC
clock (`generated_at`). All calculations use unrounded elapsed time.

Let `i` be the float's **observed cycle interval**, measured from its own
published profile-date spacings (`service/profile_cycle.py`). The 10-day Argo
nominal cycle is only the documented *fallback* when no sufficient history
exists, so a 5-day float is no longer judged with 10-day expectations.

| Displayed field | API field | Calculation |
|---|---|---|
| Last Profile Date | `last_profile_iso` | Maximum valid `_prof.nc:JULD`, converted to UTC |
| Observed cycle interval | `expected_interval_days` (+ `expected_interval_source`, `expected_interval_samples`) | Median of the accepted consecutive `JULD` spacings (0.5–60 d window, clamped 1–45 d); ≥ 3 usable spacings required, else the `_Rtraj.nc` cycle spacing, else the 10-day default |
| Expected Next Profile | `expected_next_profile_iso` | `t + i` |
| Days Since Last Profile | `days_since_last_profile` | `(now - t).total_seconds() / 86400` |
| Approx. Profiles Missed | `approx_profiles_missed` | `floor(days_since_last_profile / i)` |
| Data Status | `data_status` | Thresholds below |

Status wordings are unchanged; only the first boundary is now the float's own
interval:

- **ACTIVE / RECENT PROFILE:** `0 <= days <= i`.
- **PROFILE OVERDUE:** `i < days < 60`.
- **NO RECENT PROFILE DATA 60+ DAYS:** `days >= 60`.
- **NO DATA:** no valid profile JULD from the configured history product.

At exactly `i` days the inclusive status is still ACTIVE / RECENT PROFILE and
the estimate is already `floor(i / i) = 1`. At exactly 60 days the status is
NO RECENT PROFILE DATA 60+ DAYS. These outcomes follow the requested formulas;
no independent rounding is applied first. For a float whose measured interval is
exactly 10 days the behaviour is identical to the previous fixed-10-day rule.

The interval and its provenance are visible in the drawer (`9.79 d (profile
history, 24 intervals)`) and in the tooltip of the estimate.

When no valid date exists, all four date/elapsed/estimate fields are null and
the page displays `—`; the status is `NO DATA`. Missing is never converted to
zero or a guessed expected date. A failed refresh may retain a previously
validated cached profile date, but it is visibly stale and its old verification
time is retained.

The table shows completed elapsed days (`floor(days)`), while the drawer shows
three decimal places. Dates are displayed to the minute in explicit UTC; the
API retains the timestamp precision.

The estimate's tooltip/note names the float's own cycle and its source:

> Approximate estimate based on the observed 9.8-day profile cycle (median of
> 24 published profile dates).

and falls back to the documented wording only when the history is insufficient:

> Approximate estimate based on the expected 10-day profile cycle (no sufficient
> observed cycle history).

It is **not an exact missing-file inventory**, a count of failed processing
jobs, or a conclusion about whether the float is transmitting. Old floats can
have large estimates; no mission end or expected future profile is invented.

## Prof# and the exact inventory stay separate

The existing published-file inventory remains based on
`dac/incois/<WMO>/profiles/`:

- `prof_num` / **Prof#** is the highest recognized published cycle.
- `profile_count` is the count of distinct positive available cycles.
- Internally, `profiles.missing` and the API's `profiles_missing` /
  `profiles_missing_list` retain the exact file-cycle gaps in `1..Prof#`.
- R/D/BR/BD/SR/SD families and ascent/descent files are deduplicated by cycle;
  cycle 0 is excluded from positive-cycle counts/gap estimates.

The page does **not** use those gap fields for Approx. Profiles Missed or Data
Status. The former gap column and summary metric are replaced by the explicit
approximate estimate. The separate profile-cycle count remains available in
the inventory section; nothing counts BGC sensor rows as additional cycles.

## Positions and identity — unchanged authority

The existing coordinate selection is preserved:

- Trajectory position time is measurement-row `JULD` in `_Rtraj.nc`.
- Profile position time is `JULD_LOCATION`, not profile measurement `JULD`.
- Choose the newest valid, paired, finite/range-checked QC 1/2 position from
  trajectory fixes, full profile history and the latest individual profile.
- Preserve source file, position time, field and QC; trajectory wins equal-time
  ties. No local decoder coordinate is substituted.
- The table and map consume the same coordinate pair. The map now receives
  the profile-derived Data Status as its descriptive status string; its
  renderer, styling and geographic behavior are unchanged.

WMO, Internal ID and Float Type remain from the existing preset/registry
sources. Missing/sanitized identifiers remain unavailable. No private
operational data is reconstructed.

## Cache and refresh behavior

The API is still `GET /api/fleet-status`; manual refresh remains
`POST /api/fleet-status/sync`. The service lifecycle starts a background worker
immediately and uses the existing six-hour start-to-start schedule (minimum
300 seconds). The UI polls the cached API; it never contacts FTP directly.

The source blocks refresh independently:

1. **Profile history first:** stat/fingerprint, fetch when changed or requiring
   the new profile-recency revalidation, parse, cache and set
   `profile_checked_at`.
2. **Trajectory position evidence:** refresh separately. A missing or failing
   trajectory cannot stop a newer profile date from reaching the page.
3. **Published inventory/latest-file position candidate:** refresh separately.
   Its failure cannot redefine the profile date or approximate estimate.

A failed block retains its last valid cached data and is retried. Successful
blocks can advance even during a partial failure. Partial rows remain visibly
stale/degraded; `checked_at` and the fleet-wide `last_success_at` advance only
on complete successful verification. `updated_at` means row assembly, not an
observation timestamp. The full-success timestamp is not advanced by a cache
commit failure. Atomic tmp/replace and nonfinite-JSON guards are retained.

The source metadata now advertises `monitoring="profile-recency"`,
`product="dac/incois/<wmo>/<wmo>_prof.nc"`, `field="JULD (maximum valid value
over N_PROF)"`, the documented 10-day fallback, and an `interval_policy` string
stating that Expected Next / Approx. Missed / Data Status use each float's
observed profile cycle. API consumers must use the new profile-specific fields
and `data_status`; the old monitoring aliases are not reused with a different
meaning. Deploy/restart the service and frontend together for this API contract
change.

Existing version-2 verified profile-history blocks can serve immediately.
The first new sync revalidates their profile history even if its fingerprint
is unchanged (`profile_recency_version`). An old cache without `_prof.nc`
evidence cannot derive recency from its individual-profile or trajectory
records: it remains NO DATA until the primary product is available.

The cached trajectory block that the experimental prediction reads keeps up to
`PREDICTION_FIX_HISTORY = 400` QC'd one-per-cycle fixes (was 8). Eight was too
few to serve the documented history rung: on the real thirty-float audit the
bounded ring gave a 200-transition pool and pushed every float onto
`trajectory_extrapolation`, while the same code over the full public history
(5,294 transitions, 4-361 usable fixes per float) resolved nine floats with the
prior. `PARSER_VERSION` was raised with it so existing caches are re-parsed
rather than served with the old, truncated block. The ring is a cache bound, not
a rule: no threshold, radius or ladder condition changed.

Runtime state remains under `$ARGO_UI_DATA_DIR/fleet_status/cache.json`.
Verification uses an isolated runtime; the checked-in historical cache and
previous investigation evidence are not overwritten.

## Prediction inputs read from this page

`prediction.diagnostics` (see `PREDICTION.md`) reports what the ladder used, and
each row adds an `issues` entry when the float's most recent observed hop is not
cycle-scale (< 0.5x or > 2x its own interval) — an input advisory that never
changes the method, rung or radius. Three of the thirty monitored floats trigger
it today; one float (2902113) has no observable cycle interval and is served
with the documented 10-day fallback plus an explicit issue.

## Verification

```bash
# decoder-ui (no network in unit tests)
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=service:../src \
  env -u FLEET_SYNC_ENABLED python -m pytest tests -q

# decoder-ui/frontend
npm test
npx tsc --noEmit
FLEET_E2E_BASE=http://127.0.0.1:3000 npm run test:fleet
```

`test_profile_recency.py` covers the entire monitoring chain, exact boundaries,
null/future/fill handling, unordered histories, source identity, no fallback,
independence from trajectory timestamps and positions, partial refreshes,
retained stale history, and separation from exact inventory gaps.
`test_profile_cycle.py` pins the observed-interval rules themselves (minimum
sample count, gap/duplicate rejection, clamping, the source ladder and every
status boundary), because Float Status and the experimental prediction target
time share that module. `test_forward_test.py` covers the prediction audit
(recorded once per float and cycle, scored only against a strictly newer verified
fix, never fatal to the payload), which is additive to, and separate from, this
monitoring contract. A compact 30-WMO fixture contains independently
extracted public product values and source hashes, with no private identifiers.

The browser harness checks table/drawer fields and terminology, the precise
approximation note (now interval-aware), all filters/sorts/pages, actual
map-marker geometries, selection, source provenance and UTC behavior, plus the
`NEXT PROFILE LOCATION (PREDICTED)` block and its opt-in map layer — see
[PREDICTION.md](PREDICTION.md) for that contract. Optional environment
variables:

- `FLEET_E2E_EXPECTED`: independent profile-JULD oracle.
- `FLEET_E2E_BASELINE`: prior payload for identity/Prof#/position invariance.
- `FLEET_E2E_OUTAGE`: captured controlled failure response.
- `FLEET_E2E_REQUIRE_FRESH=1`: require a real successful upstream check.

The separate completion report records actual live cases, test outcomes and
remaining product/access limitations. No new production bundle is claimed
unless that build is actually completed; the resource limitation recorded in
the earlier repository verification is not concealed.
