# Float Status — field contract and verification

Float Status displays **recorded upstream observations**, not decoder activity or a
physical diagnosis of a float. Identity comes from the existing local fleet;
communication and positions come only from the configured Ifremer GDAC source.
All changes for this audit are confined to `decoder-ui`.

## 1. Source scope

- Anonymous FTP: `ftp.ifremer.fr:21`, root `/ifremer/argo`.
- Configured DAC: **`dac/incois`**. Fleet membership is the existing local preset
  list; an unrelated cached WMO cannot silently extend that list.
- Communication: `dac/incois/<wmo>/<wmo>_Rtraj.nc`.
- Position history: the trajectory above and `dac/incois/<wmo>/<wmo>_prof.nc`.
- Profile inventory: `dac/incois/<wmo>/profiles/`.
- Latest individual profile: a recognized file at the highest published cycle
  in that inventory. Delayed core is preferred to real-time core on a tie,
  followed by delayed/real-time B and S products.
- Public HTTPS mirror used for independent audit checks:
  `https://data-argo.ifremer.fr/` (FTP and HTTPS bytes were hash-compared).

**Scope is not global unavailability.** Existing WMOs 6902892 and 6903014 are
absent from `dac/incois`, but public `_Rtraj.nc` files were confirmed under
`dac/coriolis` during the 2026-09-21 IST audit. The source-scope clarification
was skipped, so the existing INCOIS-only policy was retained, not silently
expanded. They display `NO DATA` **in the configured DAC**, with that reason
shown. No additional floats or operational identities are introduced.

## 2. Exact displayed-field lineage

All rows are delivered through `GET /api/fleet-status`, the
`useFleetStatusStore` store, and `FloatStatusPage.tsx`.

| Field | Source and transformation | Missing / display behavior |
|---|---|---|
| WMO ID | `path_resolver.build_dynamic_float_presets()[].wmo`; csv4 `meta.csv` → `WMO id`, registry CSV → `wmo`, or CTS4 reference → `wmo`. Upstream `PLATFORM_NUMBER` must agree before parsing observations. | Configured WMOs remain visible even if their configured DAC has no data. |
| Internal ID | `datasources.local.build_wmo_identity_map()`: csv4 `load_info().ptt` (`meta.csv: Argos number`, else `sensor-info.csv: Comms ID`) and `load_meta().IMEI`; single-file registry `ptt` / `imei` fill gaps. Display PTT, else IMEI. | `null` / `—` when absent or redacted. No recovery from sanitized filenames, sensor serials or upstream identities. Local registry agreement is not private operational verification. |
| Float Type | Preset `platform_type`. csv4 loader maps canonical manufacturer NKE to ARVOR, otherwise APEX; registry CSV provides `platform_type`; CTS4 discovery supplies `PROVOR_III`. | Preserve the existing application family labels. Audit cross-checked all 30 INCOIS types against public `_meta.nc: PLATFORM_TYPE`. |
| Latitude / Longitude | Paired `LATITUDE[i]` / `LONGITUDE[i]`, accepted `POSITION_QC[i]` and location time from the **same observation row**. Select the newest usable position among trajectory, complete profile history and the latest individual profile. | Neither coordinate is manufactured from another row or local telemetry. Invalid, fill, future or unapproved-QC candidates are excluded. Table and map receive the same pair. Three decimals and explicit N/S/E/W in the table. |
| Last Transmission | Maximum valid `JULD_LAST_MESSAGE[N_CYCLE]`; use `JULD_TRANSMISSION_END[N_CYCLE]` only if no valid last-message value exists. Source field, array index, cycle and status flag are retained. | No qualifying last-message/end value → `null` / `—`, independently of available profiles or positions. |
| Expected Next Communication | Last Transmission + **10 exact UTC days**. | Null if Last Transmission is unavailable. Shown in the detail drawer and transmission tooltip. |
| No Communication / days | `(generated_at UTC − Last Transmission UTC) / 86400`. Do not round before status calculation or integer-day display. | Table: completed days (`floor`); drawer: three decimals. Null is `—`, not zero. |
| Communication Status | Approved 10/60-day rules in §4. | `NO DATA` if no valid qualifying communication timestamp. |
| Prof# | Highest cycle in recognized upstream profile filenames, **not** a profile count. | `—` when no highest cycle can be established. |
| Available profile count | `profile_count`: count of distinct positive published cycles, deduplicated across R/D/BR/BD/SR/SD families and ascent/descent files. Summary and map tooltip use this, not Prof#. | Known empty listing → zero available cycles; unavailable listing → null. Summary totals only known listings, with coverage in the tooltip. |
| Profiles Missing | Cycles absent from the union of recognized filenames in **1..Prof#**. Cycle 0 is excluded. | Unknown inventory → `—`, not zero. These are file-cycle gaps, not failed decodes, missing BGC sensor grids, missing communications, or inferred future cycles. |

Local source files are read only. For the current fleet: 15 WMOs come from the
four-CSV metadata set, 2 from the single-file registries, and 15 from the CTS4
reference. Seventeen Internal IDs are locally supplied; the 15 CTS4 Internal
IDs remain unavailable/sanitized.

## 3. Time and position validity

### Communication

The actual GDAC fields identify their semantics as:

- `JULD_LAST_MESSAGE`: **Date of latest float message received**.
- `JULD_TRANSMISSION_END`: **Transmission end date**.

Their units must be the Argo epoch, days since 1950-01-01 00:00:00 UTC, with a
supported Gregorian calendar. Parsing validates the per-cycle dimension and
WMO. Masked/fill, nonfinite, negative and future dates are rejected. ISO output
is timezone-qualified UTC. Sub-millisecond floating-point noise around a
whole second is normalized to avoid displaying a spurious preceding minute.
RT19 flags are recorded as supplied; upstream estimates are not promoted to
independent proof of physical float activity.

**Never substitute:** measurement `JULD`, profile `JULD`, `JULD_LOCATION`,
`DATE_CREATION`, `DATE_UPDATE`, FTP mtime, local processing time, file arrival,
or a decoder run time.

Legacy WMOs **2901305 and 2901328** have format-2.2 trajectories without a
last-message/end field. Their estimated `JULD_START_TRANSMISSION` values are
**start** estimates, not the latest received message or transmission end.
They are not relabeled Last Transmission. The old generic measurement-JULD
fallback is removed, including when serving an old cache. These floats may
still have valid upstream coordinates and profile inventories while their
communication status is `NO DATA`.

### Position

- Trajectory position time: `JULD[N_MEASUREMENT]`.
- Profile position time: **`JULD_LOCATION[N_PROF]`**, not profile measurement
  `JULD`.
- Require finite paired coordinates, latitude within ±90°, longitude within
  ±180°, and `POSITION_QC` **1 (good) or 2 (probably good)**.
- Do not claim unassessed, interpolated, probably-bad, bad or missing locations
  are verified fixes. Exclusion is explained in the detail view.
- Read the full `_prof.nc` history so an earlier cycle can supply the newest
  good position, including after a cycle reset or a bad latest profile.
- Include the highest-cycle individual profile in the comparison in case the
  aggregate product lags. Break equal-time ties in favor of a trajectory fix.
- If the full-history product is absent, state the restricted position-search
  scope. A formerly valid full-history block is not erased on a failed stat
  or download.
- Publish the selected position's time, file, time field and QC. A recently
  checked historical position is not described as a new observation.

A newer profile measurement than the recorded transmission is shown as
**recency disagreement between upstream products**. It does not prove a
specific DAC failure, and does not change the communication timestamp/status.

## 4. Approved communication policy

Computed backend-side at serve time, using unrounded elapsed days:

- **ACTIVE:** `0 ≤ days ≤ 10`.
- **OVERDUE:** `10 < days < 60`.
- **NO COMMUNICATION 60+ DAYS:** `days ≥ 60`.
- **NO DATA:** no valid qualifying upstream communication timestamp.

The application does not label floats “dead.” Profile gaps have no role in
this classification. Cache freshness is a separate indicator, not a fifth
communication state.

## 5. Synchronization, migration and failure behavior

- Immediate scheduled cycle on backend startup, then a start-to-start interval
  of six hours by default (`FLEET_SYNC_INTERVAL_S`, minimum 300 seconds).
  Worker-thread sync never blocks the cache API. Cycles cannot overlap.
- Manual refresh: `POST /api/fleet-status/sync`; an existing cycle returns
  `already-running`. No browser-to-FTP traffic.
- Use DAC membership, Rtraj/full-profile MDTM+size, and profile-listing
  fingerprints. Download changed products only. Filenames, hashes, sizes and
  mtimes are provenance/change evidence, never communication time.
- `checked_at` advances on a successful upstream check even if data is
  unchanged. `updated_at` identifies when the contents were read/assembled.
- `last_success_at` means a **fully successful, persisted** fleet cycle.
  A partial failure updates `last_completed_at`, not the full-success time.
- Cache writes use a temporary file + atomic replace, with JSON nonfinite
  values prohibited. Persistence errors are visible; the previous disk cache
  remains valid. A failed refresh retains valid observations and their old
  verification timestamps.
- Invalid/empty DAC responses and malformed profile listings are errors, not
  permission to erase a fleet or replace an inventory with zero.
- Version-1 caches remain readable, but unsupported communication timestamps
  are immediately withheld. Legacy profile positions without a verified
  location time are not treated as current. Parser/inventory revision guards
  force source revalidation even if upstream fingerprints did not change.
- Cache data path: `$ARGO_UI_DATA_DIR/fleet_status/cache.json`, normally
  `decoder-ui/data/fleet_status/cache.json`. The **checked-in cache is not
  rewritten by the audit**; live runs use an isolated external runtime.
- Disable: `FLEET_SYNC_ENABLED=0`. Disabled does not mean fresh. Old checks,
  incomplete sync, errors and invalidated legacy records remain visibly stale.
- Configurable transport: `FLEET_FTP_HOST`, `FLEET_FTP_PORT`, `FLEET_FTP_ROOT`,
  `FLEET_FTP_TIMEOUT_S`. Anonymous credentials only.

The UI polls the cache every 60 seconds. A hung GET is aborted after 15 seconds
so subsequent refreshes remain possible. Failed fetches retain the previous
payload with an explicit warning. A frozen API snapshot also expires visually;
its old status calculation is not presented as a new verification.

## 6. Current audit observations (2026-09-21 IST)

Independent public HTTPS retrieval covered 30 INCOIS Rtraj files, 30 metadata
files, all 32 configured-DAC membership cases, profile directory inventories,
latest profile families and all 30 full-profile history files. Live anonymous
FTP synchronization was exercised separately, including recurring scheduled
cycles. Selected source files were hash-compared across both transports.

At the audit snapshot the corrected configured-DAC fleet has **32 floats**:
**1 ACTIVE, 1 OVERDUE, 26 NO COMMUNICATION 60+ DAYS and 4 NO DATA**.
There are **5,625 available positive profile cycles** and **22 file-cycle gaps**
across the 30 available inventories. The previous 5,647 “total profiles” was the
sum of highest cycle numbers, not the number available.

The complete A–I audit report, 32-WMO field ledger, captured browser evidence,
source manifests and reproducibility scripts are delivered separately. Claims
of unavailable communication refer to the specified source/field policy, not
to a universal absence of data or proof that a float has stopped operating.

## 7. Tests and reproducibility

```bash
# decoder-ui; tests use temporary state and no live FTP
PYTHONPATH=service:../src python -m pytest tests -q

# frontend; unit tests and standalone type check
npm test
npx tsc --noEmit

# Browser audit against the running API + Vite (or built app)
FLEET_E2E_BASE=http://127.0.0.1:3000 npm run test:fleet
```

`tests/test_fleet_status_audit.py` checks all 32 existing cache records plus
boundary/timezone/null handling, source guards, coordinate coherence, bad QC,
full-history chronology, profile-cycle semantics, old-cache revalidation,
unchanged checks, scheduler cadence, outages and atomic persistence failure.
Synthetic edge cases are explicitly test-only and never enter operational data.

The browser audit checks all displayed fields for every row, actual ArcGIS
marker geometries, search/type/status filters, all sortable columns in both
directions, pagination, drawer calculations and UTC presentation in two browser
timezones. Optional `FLEET_E2E_EXPECTED`, `FLEET_E2E_OUTAGE` and
`FLEET_E2E_REQUIRE_FRESH` enable independent-source and controlled-outage checks.
A cached/disabled smoke test is never called a completed live synchronization.
