# Float Status correctness audit — completed

**Date:** 21 September 2026, Asia/Calcutta (retrieval/test timestamps below are UTC).  
**Repository baseline:** `60dc4c12cf3e3c00ca2d77e526f0e31dffb8d07d`.  
**Reference API snapshot:** `2026-09-20T21:32:36.247717+00:00`. Before/after values were calculated at that same instant.  
**Scope:** every existing float — **32 WMOs × 11 requested fields = 352 comparisons**. Changes are limited to `incois-arpy-decoder/decoder-ui/`.

## Executive result

- **22 displayed latitude/longitude pairs corrected** to the newest accepted upstream position.
- **2 unsupported legacy Last Transmission values removed** rather than relabeling measurement time as communication.
- **5,647 → 5,625 available profile cycles** in the summary. The original 22 published-file gaps were correct; Prof# is a maximum cycle, not a count.
- Old/disabled/failed caches are visibly qualified. Last full-success time is no longer advanced by partial failure, and failed cache writes are visible.
- **352/352 independent field checks, 90/90 FTP–HTTPS product-hash comparisons, 184 backend tests, 140 frontend tests, TypeScript, scoped Ruff and 256/256 browser checks passed.**
- Original layout, navigation and map renderer were preserved. `src/argo_decoder/`, registries, raw inputs and the checked-in fleet cache are unchanged. No private operational identifiers were added.

### Corrected configured-DAC snapshot

| Total | ACTIVE | OVERDUE | NO COMMUNICATION 60+ DAYS | NO DATA | Available profile cycles | File-cycle gaps |
|---:|---:|---:|---:|---:|---:|---:|
| 32 | 1 | 1 | 26 | 4 | 5,625 (30 available inventories) | 22 |

**Important qualification:** NO DATA is source/field-specific, not proof that no Argo data exists. WMOs **6902892 and 6903014 have public Coriolis records**, but are outside this page's configured INCOIS DAC. The source-scope question was skipped, so the existing INCOIS-only policy was retained and made explicit. The other two NO DATA cases are legacy files lacking a qualifying last-message/end timestamp. See §I.

**Detailed deliverables:** [352-field UI/API/source/calculation ledger](field-comparisons.csv) · [Eight real-WMO field-by-field comparisons](WMO_COMPARISONS.md) · [All source evidence](expected-upstream.json).

## A. Exact source per field

| Displayed field | Exact source / transformation | Validation and null behavior |
|---|---|---|
| WMO ID | `path_resolver.build_dynamic_float_presets()[].wmo`: csv4 `config/metadata/meta.csv: WMO id` (15), registry CSV `wmo` (2), or `provor_cts4_301_reference.csv: wmo` (15). | Matches all 32 configured presets; public `PLATFORM_NUMBER` agrees for the 30 INCOIS records. |
| Internal ID | `datasources.local.build_wmo_identity_map()`: csv4 `load_info().ptt` (`Argos number`, else `sensor-info.csv: Comms ID`), else `load_meta().IMEI`; single-file `registry_apf9.csv` / `registry.csv` `ptt`/`imei` fill gaps. Display PTT, else IMEI. | All 17 supplied IDs match local records; all 15 CTS4 IDs remain null. No reconstruction from redacted telemetry or public metadata. |
| Float Type | Preset `platform_type`: csv4 manufacturer mapping (NKE → ARVOR, otherwise APEX), registry `platform_type`, or CTS4 discovery → `PROVOR_III`. | All 30 accessible INCOIS `_meta.nc: PLATFORM_TYPE` values match. The two out-of-scope types are local-registry checks only. |
| Latitude | Same-row `LATITUDE`, `LONGITUDE`, `POSITION_QC` and time, selected by newest valid observation across `_Rtraj.nc`, full `_prof.nc` history and latest individual profile. | WMO/range/QC checks; accepted position QC 1/2 only. Never a decoder-local coordinate. |
| Longitude | Same selected upstream row as Latitude. Trajectory time is `JULD`; profile location time is `JULD_LOCATION`, not profile measurement `JULD`. | Table and actual map graphics agree for all 30 positioned floats. Display three decimals with N/S/E/W; full precision retained in API. |
| Last Transmission | `dac/incois/<wmo>/<wmo>_Rtraj.nc`: max valid `JULD_LAST_MESSAGE[N_CYCLE]`; `JULD_TRANSMISSION_END` only if canonical field has no valid values. | Validate WMO, dimension, Argo UTC epoch, mask/fill/finite/future dates. No profile/measurement/processing/mtime substitution; unsupported old-cache values are withheld too. |
| Expected Next Communication | Valid Last Transmission + exactly 10 UTC days. | Null if transmission unavailable. UI drawer and tooltip show UTC to the minute. |
| No Communication / elapsed days | `(payload.generated_at UTC − Last Transmission UTC) / 86400`, unrounded. | UI table floors completed days; drawer shows three decimals. Missing is `—`, not zero. |
| Communication Status | ACTIVE ≤10 days; OVERDUE >10 and <60; NO COMMUNICATION 60+ DAYS ≥60; NO DATA without valid timestamp. | Calculated from unrounded elapsed days at serve time; not a physical “dead/alive” diagnosis. Cache freshness is separate. |
| Prof# / profile count | `profiles/` recognized filenames: Prof# is highest published cycle; `profile_count` is distinct positive available cycles. R/D/BR/BD/SR/SD union, ascent/descent and 3-/4-digit cycles supported. | Existing Prof# values are retained. Summary now uses available cycles, not maxima or BGC sensor-row counts. |
| Profiles Missing | Absent cycles in the published-file union over `1..Prof#`; exclude launch cycle 0. | All 22 existing gaps verified. No inference from decoder failures, communication gaps or an unpublished trajectory-cycle tail. Unknown inventory remains null. |

The service source is `service/fleet_status.py` (`parse_rtraj`, `parse_profile`, `summarize_profiles`, `FleetSyncRegistry._refresh_float`, `_serve_row`, `payload`). The API routes are `GET /api/fleet-status` and `POST /api/fleet-status/sync` in `service/api.py`. Startup calls `fleet_sync.start()` in `service/main.py`. The browser reads the payload through `useFleetStatusStore.ts`; `FloatStatusPage.tsx` passes **the same row coordinates** to the table and shared `FleetOceanMap`.

No displayed communication value comes from local decoding, run histories, local profile generation, processing dates or file-arrival times. Sync/row timestamps are separately labeled metadata. Positions use `JULD_LOCATION` for profiles; profile `JULD` remains measurement evidence only.

## B. What was already correct

1. **WMO/preset membership and local identity priority:** all 32 WMOs matched current data. All 17 provided Internal IDs matched their local registry sources; missing CTS4 identities were already honestly blank.
2. **Float types:** all 30 accessible INCOIS public metadata types agreed with the current labels. The two non-INCOIS presets agreed with their local registry labels; their types were not claimed as independently verified against Coriolis metadata.
3. **Communication for 28 INCOIS records:** their cached `JULD_LAST_MESSAGE` maxima agreed with independently downloaded upstream data. They remain the communication source, including where newer profiles exist.
4. **The approved status inequalities and +10-day rule:** the original basic ACTIVE/OVERDUE/60+ logic was correct. Incorrect source timestamps and rounding/invalid-input edge cases could still produce misleading output; those were fixed.
5. **Prof# and the current missing-cycle lists:** all 30 current directory inventories matched the cache, including all 22 gaps. The error was treating maxima as available counts, not the existing real gap lists.
6. **Map/table shared data path:** both already used fleet-status row coordinates. Their agreement did not mean that the selected upstream coordinate was the newest usable one; that selection is now corrected and independently checked.
7. **Basic FTP connectivity and unchanged-file detection:** the original live check completed `0 updated / 32 unchanged / 0 failed`. Existing cache availability was not used as a substitute for this live check.

## C. Incorrect or misleading values found

| Finding | Observed effect | Correction |
|---|---|---|
| Generic trajectory measurement JULD used as Last Transmission | 2901305 and 2901328 were labeled long-silent using a nonqualifying timestamp. | Last Transmission / expected-next / elapsed become unavailable; status becomes NO DATA. Their valid positions and profiles remain usable. |
| Profile position always preferred to trajectory | Older or questionable profile coordinates displaced newer good fixes: 22 actual coordinate pairs changed. | Date-rank accepted upstream positions; validate paired row, WMO, location time and QC. |
| Bad/QC-3 coordinates accepted; BGC QC characters concatenated | 2902222 / 2902224 used probably-bad profile positions. Multi-row BGC profiles could expose strings such as `1111` rather than a selected-row flag. | Accept QC 1/2 only for verified fixes; keep same-row evidence and explain rejected candidates. |
| “Total Profiles” summed Prof# | Displayed 5,647 although only 5,625 distinct positive cycles were available. | Summary/map count uses `profile_count`; Prof# remains the highest published cycle. |
| Freshness based only on error status | An old successful cache could stay green indefinitely; disabled caches were not age-qualified. | Backend per-row and global expiry plus browser frozen-snapshot/error warning. |
| Partial failure advanced last_success_at | A completed but degraded cycle could look like a fully successful refresh. | Separate completion from full success; retain previous success on partial/persistence failure. |
| UTC/invalid-value/rounding edge cases | Future grace, naïve cache timestamps, premature day rounding and invalid numbers could be treated as observations. | UTC-qualified valid values only; reject future/invalid data; unrounded policy math, finite formatting and null-safe sorting. |
| Coarse semantic/presentation labels | Longitude/latitude headings implied E/N only; a five-minute test cadence displayed as 0 h. | Explicit hemispheres and neutral coordinate headings; exact 5 min / 6 h labels; count/gap/source tooltips. |

Rows whose values were already correct were not overwritten with local-decoder substitutes. For example, ARVOR 1902844 still uses the May communication even though a September profile supplies the newer position.

## D. Root causes and safeguards

- **Semantic conflation:** generic measurement JULD was called communication, and maximum cycle was called profile count. Separate fields/contracts now prevent both substitutions.
- **Priority instead of chronology:** selecting a profile by product priority, not comparing valid position dates, was not a latest-position policy. The selector now reads full profile history as well, so it is not dependent on cycle numbers being chronological or the highest-cycle location being good.
- **Incomplete validation:** profile latitude, longitude, JULD and QC were read independently. They now share an observation row; foreign WMO, wrong cycle, missing location time and rejected QC cannot silently supply a point.
- **Version-insensitive cache reuse:** unchanged upstream fingerprints could preserve an old parsing mistake forever. Legacy caches are immediately qualified and unsafe timestamps withheld; parser/full-inventory guards force source revalidation.
- **Success/freshness conflation:** a recent API response is not an upstream refresh, and a partial refresh is not full success. Separate `checked_at`, `updated_at`, `last_completed_at`, `last_success_at` and stale state now express those differences.
- **Failure suppression / destructive absence assumptions:** write errors were swallowed, and bad listings could look empty. Atomic writes remain, but commit failures are surfaced and invalid inventories cannot erase valid rows.
- **Scheduler drift:** sleeping the interval after a download made start-to-start cadence equal interval plus work time. The corrected loop honors start-to-start cadence, prevents overlap and avoids a tight loop on overrun.
- **Tests encoded the old behavior:** generic-JULD fallback and bad-QC acceptance were explicitly expected by some old tests. Those expectations were replaced with the verified field contract, real-format fixture units/identity, and independent live evidence—not merely loosened to make tests pass.

## E. Files changed

All paths below are relative to `incois-arpy-decoder/decoder-ui/`.

| File | Purpose |
|---|---|
| `FLEET_STATUS.md` | Replaced misleading source/fallback/count/sync claims with the tested field contract and explicit limitations. |
| `frontend/e2e/fleetStatus.e2e.mjs` | Replace obsolete SVG assertion; check all float fields, real ArcGIS geometry/selection, filters/sorts/pages/timezones and captured outage state. |
| `frontend/src/components/FloatStatusPage.tsx` | Same layout; correct coordinate/counter labels, explicit provenance/time/QC and source limitations, visible stale/failure state. |
| `frontend/src/store/useFleetStatusStore.ts` | Abort stalled cache GET after 15 seconds; retain valid payload on failure. |
| `frontend/src/types/index.ts` | Additive typed freshness, provenance and available-count fields. |
| `frontend/src/utils/fleetStatus.test.ts` | Boundary, UTC, invalid/null values, cache expiry, coordinate and cadence regressions. |
| `frontend/src/utils/fleetStatus.ts` | Finite/range/null-safe formatting/sorting, shared position predicate, cache expiry and exact cadence labels. |
| `service/fleet_status.py` | Communication source guards, coherent/date-ranked QC positions, full profile history, distinct cycle counts, cache migration/freshness/persistence and scheduling fixes. |
| `tests/test_fleet_status.py` | Correct tests that previously endorsed generic-JULD communication and bad-QC positions; add real-format units/identity/location-time fixtures. |
| `frontend/src/store/useFleetStatusStore.test.ts` | New transport-retention, timeout, overlap and failed-trigger tests. |
| `tests/test_fleet_status_audit.py` | New 32-real-cache-record and edge-case regression suite; test-only synthetic NetCDF data. |

**Scope proof:** all **2,705 originally tracked file hashes** were compared. Exactly **9 tracked files changed and 2 files were added**, all under `decoder-ui`. The other 2,696 tracked files are unchanged, including every tracked `src/argo_decoder/` file and `decoder-ui/data/fleet_status/cache.json`. No dependencies, registry values, raw data, private identities or decoder algorithms were changed. Changes are in the working tree; no commit or push was made. See `scope-verification.json` and `git-status.txt`.

## F. Real WMO before/after examples

Coordinates below are **latitude, longitude**, signed decimal degrees. Communication dates are UTC.

| WMO | Type | Before | After | Explanation |
|---|---|---|---|---|
| 2902223 | APEX | lat/lon -45.723, 7.971 | lat/lon -45.719, 8.043 | Use newer valid trajectory position, not an older profile. Prof# remains 353; available count is 350; gaps are 158, 161, 345. |
| 2902222 | APEX | lat/lon -59.978, -132.902 | lat/lon -59.985, -132.847 | Reject profile POSITION_QC=3; select newest accepted QC 1/2 position, with its actual age shown. |
| 2901304 | APEX | lat/lon -59.913, 69.366 | lat/lon -58.87, 72.648 | Use newer valid trajectory position, not an older profile. |
| 2901305 | APEX | Last Tx 2012-08-28 17:15 UTC; NO COMMUNICATION 60+ DAYS | Last Tx —; Expected Next —; elapsed —; NO DATA | Old generic measurement JULD was not last-message/end evidence; valid profile/position data remains available. |
| 2901328 | APEX | Last Tx 2012-12-27 20:55 UTC; NO COMMUNICATION 60+ DAYS | Last Tx —; Expected Next —; elapsed —; NO DATA | Old generic measurement JULD was not last-message/end evidence; valid profile/position data remains available. |
| 2902086 | PROVOR_III | lat/lon 18.323, 84.77337333 | lat/lon 18.33004, 84.76787 | Use newer valid trajectory position, not an older profile. CTS4 Internal ID stays unavailable; no private ID inferred. |
| 2902224 | APEX | lat/lon -41.588, -26.359 | lat/lon -42.097, -33.661 | Reject profile POSITION_QC=3; select newest accepted QC 1/2 position, with its actual age shown. |
| 1902844 | ARVOR | Last Tx 2026-05-04 07:00 UTC; profile 2026-09-08 14:04 UTC | Communication date retained; newer profile coordinates retained; recency disagreement visible | The September measurement cannot replace the May communication. Prof# 25, available 24, missing cycle 22. |
| 6902892 | ARVOR_D | NO DATA (not in INCOIS) | NO DATA, explicitly outside configured DAC | Coriolis Rtraj exists, but no automatic source-scope expansion was approved. Same applies to 6903014. |

**Several complete comparisons:** `WMO_COMPARISONS.md` contains every requested field for eight representative real WMOs (ACTIVE, OVERDUE, long-silent, unavailable, missing-profile, CTS4/BGC and legacy APEX/ARVOR cases). `field-comparisons.csv` extends the same UI → API → source → calculated-value ledger to **all 32 WMOs**. Each browser comparison includes its actual API calculation timestamp; elapsed-day differences between separately captured snapshots are not treated as upstream changes.

### All 32 floats — corrected reference snapshot

| WMO | Type | Status | Last Transmission UTC | Lat, Lon | Prof# | Available | Gaps |
|---|---|---|---|---|---:|---:|---:|
| 1902844 | ARVOR | NO COMMUNICATION 60+ DAYS | 2026-05-04 07:00 UTC | 9.85295, 65.99677 | 25 | 24 | 1 |
| 2901304 | APEX | NO COMMUNICATION 60+ DAYS | 2011-09-22 08:47 UTC | -58.87, 72.648 | 20 | 20 | 0 |
| 2901305 | APEX | NO DATA | — | -62.021, 60.694 | 27 | 27 | 0 |
| 2901328 | APEX | NO DATA | — | 11.826, 80.065 | 98 | 92 | 6 |
| 2901339 | APEX | NO COMMUNICATION 60+ DAYS | 2020-12-20 06:39 UTC | 10.536, 70.362 | 329 | 329 | 0 |
| 2901350 | APEX | NO COMMUNICATION 60+ DAYS | 2020-04-26 18:09 UTC | -51.059, -114.149 | 301 | 301 | 0 |
| 2902086 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2016-02-16 04:34 UTC | 18.33004, 84.76787 | 244 | 244 | 0 |
| 2902087 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2016-08-14 04:15 UTC | 12.24699, 80.7311 | 323 | 323 | 0 |
| 2902088 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2019-03-20 04:35 UTC | -4.27467, 86.89816 | 228 | 228 | 0 |
| 2902089 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2013-10-29 14:21 UTC | -22.13373, 61.94348 | 130 | 130 | 0 |
| 2902090 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2013-05-13 04:06 UTC | -57.09159, 53.10369 | 16 | 16 | 0 |
| 2902091 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2013-12-24 12:49 UTC | 4.38251, 84.44005 | 13 | 13 | 0 |
| 2902092 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2016-12-14 06:51 UTC | 18.74924, 67.03563 | 149 | 149 | 0 |
| 2902093 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2019-04-23 04:30 UTC | 14.18155, 67.68236 | 234 | 234 | 0 |
| 2902113 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2013-11-23 13:44 UTC | 18.0931, 89.58427 | 2 | 2 | 0 |
| 2902114 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2017-10-09 12:36 UTC | 14.6323, 87.54756 | 284 | 284 | 0 |
| 2902115 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2020-05-16 12:33 UTC | -53.66326, 172.83744 | 238 | 238 | 0 |
| 2902118 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2021-04-21 12:26 UTC | 12.0285, 65.07857 | 261 | 261 | 0 |
| 2902120 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2021-05-12 12:41 UTC | 13.07015, 69.17182 | 262 | 262 | 0 |
| 2902130 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2019-02-19 12:07 UTC | -52.58553, 102.86184 | 189 | 189 | 0 |
| 2902131 | PROVOR_III | NO COMMUNICATION 60+ DAYS | 2016-08-23 11:53 UTC | -42.69385, 42.20141 | 97 | 97 | 0 |
| 2902201 | APEX | NO COMMUNICATION 60+ DAYS | 2025-09-26 20:21 UTC | 22.495, 61.077 | 350 | 350 | 0 |
| 2902203 | APEX | NO COMMUNICATION 60+ DAYS | 2026-05-15 20:59 UTC | 13.802, 65.138 | 374 | 366 | 8 |
| 2902206 | APEX | NO COMMUNICATION 60+ DAYS | 2026-01-20 14:14 UTC | 9.376, 67.639 | 352 | 352 | 0 |
| 2902222 | APEX | OVERDUE | 2026-08-12 15:22 UTC | -59.985, -132.847 | 350 | 349 | 1 |
| 2902223 | APEX | ACTIVE | 2026-09-12 06:10 UTC | -45.719, 8.043 | 353 | 350 | 3 |
| 2902224 | APEX | NO COMMUNICATION 60+ DAYS | 2026-05-02 02:32 UTC | -42.097, -33.661 | 348 | 345 | 3 |
| 2904082 | ARVOR | NO COMMUNICATION 60+ DAYS | 2026-05-05 07:14 UTC | 10.26666667, 63.43333333 | 25 | 25 | 0 |
| 6902892 | ARVOR_D | NO DATA | — | — | — | — | — |
| 6903014 | ARVOR | NO DATA | — | — | — | — | — |
| 6990711 | ARVOR | NO COMMUNICATION 60+ DAYS | 2025-05-02 00:01 UTC | -64.70572, 69.86632 | 7 | 7 | 0 |
| 7902408 | ARVOR | NO COMMUNICATION 60+ DAYS | 2026-05-05 09:58 UTC | 3.33145, 81.106 | 18 | 18 | 0 |

## G. Ifremer verification results

### Independent source checks

- **Anonymous FTP succeeded** against `ftp.ifremer.fr:21`. The current INCOIS directory listing contained 630 WMO directories; only the existing 32 local presets were audited/displayed.
- HTTPS retrieved all **30 configured-DAC Rtraj files**, **30 metadata files**, current profile directory listings and latest profile families, plus **all 30 full `_prof.nc` history files** (43,936,744 bytes for the full-history products).
- **90 actual product SHA-256 comparisons passed** between the FTP-persisted extraction and independent HTTPS downloads: 30 Rtraj + 30 selected individual profiles + 30 full-profile histories. Metadata/type checks were separately performed over HTTPS.
- Raw netCDF inspection verified field names, long names, dimensions, units, masks and selected indices. The independent oracle does not import the service parser functions.
- All 32 configured-DAC `_Dtraj.nc` checks returned 404. For legacy 2901305/2901328, `_tech.nc` offered only creation/update dates, not usable per-cycle receipt/end times. Their format-2.2 `JULD_START_TRANSMISSION` values are explicitly **estimated start times**, not relabeled Last Transmission.
- INCOIS URLs for 6902892/6903014 returned 404 and those WMOs were absent from its membership list. Their **Coriolis Rtraj URLs returned 200**. Only product availability was checked there; no Coriolis communication values are claimed in the page.

Useful public examples:

- `https://data-argo.ifremer.fr/dac/incois/2902223/2902223_Rtraj.nc`
- `https://data-argo.ifremer.fr/dac/incois/2902223/profiles/R2902223_353.nc`
- `https://data-argo.ifremer.fr/dac/incois/2902223/2902223_prof.nc`
- `https://data-argo.ifremer.fr/dac/incois/1902844/1902844_meta.nc`
- `https://data-argo.ifremer.fr/dac/coriolis/6902892/6902892_Rtraj.nc`
- `https://data-argo.ifremer.fr/dac/coriolis/6903014/6903014_Rtraj.nc`

Full URLs, retrieval times, HTTP metadata, byte hashes, raw JULD values, selected array indices, QC values and listing gaps are in `upstream-downloads.json`, `aggregate-profile-downloads.json` and `expected-upstream.json`.

### Scheduled refresh: actually executed, not inferred

The final implementation ran with an isolated cache and an explicitly shortened **300-second test interval**; the application default remains six hours. Startup and subsequent cycles were scheduled by the real service lifecycle, not manual POSTs. The final run produced **8 successful scheduled cache commits**:

| Cycle | Attempt UTC | Fully successful commit UTC | Updated / unchanged / failed | Duration |
|---:|---|---|---|---:|
| 1 | 2026-09-20T21:21:28.220737+00:00 | 2026-09-20T21:24:52.786519+00:00 | 30/2/0 | 204.6 s |
| 2 | 2026-09-20T21:26:28.221113+00:00 | 2026-09-20T21:27:28.598475+00:00 | 0/32/0 | 60.4 s |
| 3 | 2026-09-20T21:31:28.222049+00:00 | 2026-09-20T21:32:29.269731+00:00 | 0/32/0 | 61.0 s |
| 4 | 2026-09-20T21:36:28.223090+00:00 | 2026-09-20T21:37:30.468097+00:00 | 0/32/0 | 62.2 s |
| 5 | 2026-09-20T21:41:28.224184+00:00 | 2026-09-20T21:42:30.522039+00:00 | 0/32/0 | 62.3 s |
| 6 | 2026-09-20T21:46:28.224969+00:00 | 2026-09-20T21:47:29.792827+00:00 | 0/32/0 | 61.6 s |
| 7 | 2026-09-20T21:51:28.225289+00:00 | 2026-09-20T21:52:28.475114+00:00 | 0/32/0 | 60.2 s |
| 8 | 2026-09-20T21:56:28.226519+00:00 | 2026-09-20T21:57:28.963466+00:00 | 0/32/0 | 60.7 s |

The first final-run cycle added/revalidated full-history position evidence; the earlier initial run had already re-read 30 trajectory/profile records from the original cache. Subsequent unchanged cycles advanced verification timestamps without changing observation timestamps. The first two final-run starts were separated by **300.000376 seconds**. The last completed full-success timestamp retained on disk is `2026-09-20T21:57:28.963466+00:00`.

### Failure preservation

A separate copy of the real 32-record cache was subjected to a **controlled loopback TCP connection refusal at the FTP transport boundary**. It was not a claim that Ifremer itself was down. The refresh reported an error, **all 32 stored rows were unchanged**, and the prior full-success timestamp remained unchanged. The captured failure payload was then rendered in the browser: the stale notice was visible and WMO 2902223 retained its real last valid transmission. The running audit server's valid cache was not replaced by this test.

## H. Tests performed

| Verification | Result |
|---|---|
| All 11 requested fields, every existing WMO | **352/352 independent comparisons passed**; full CSV includes actual UI values and calculation times |
| Cross-transport source integrity | **90/90 SHA-256 matches** |
| Backend/service suite | **184 passed**, 36 dependency/fixture deprecation warnings |
| Frontend unit suite | **140 passed / 13 files** |
| TypeScript | **Pass** (`tsc --noEmit`) |
| Ruff on all changed Python files | **Pass** |
| Browser end-to-end, current ArcGIS implementation | **256/256 checks passed**, all **32 floats** field-checked, no runtime page errors |
| Actual map marker geometry | All **30 positioned floats** match table/API coordinates; 2 genuinely unplotted configured-DAC cases |
| Map visual/render check | Ready and settled view, loaded layers, **70 Esri responses / zero failed requests** in the separate captured check |
| Search / filter / sort / pagination | WMO and Internal ID search; all 4 types; all 4 communication states; all 5 sort keys both directions, nulls last; both pages; empty search |
| Selection / navigation | Actual marker click after FIT opens its matching WMO; row drawers and back navigation work |
| Date/time | Exact 10/60 boundaries, offset normalization, naïve/future/nonfinite rejection, no premature day rounding; identical UTC rendering in Kolkata and Los Angeles |
| Cache/sync | Immediate and recurring live cycles, revision reparse, unchanged check renewal, partial failure, invalid/empty listings, old/disabled freshness, atomic write failure and controlled TCP refusal |
| Scope / sanitization | All original tracked hashes checked; changes only in decoder-ui; original cache, core code and sanitized identities preserved |

The browser harness initially had the old SVG assertion; it now tests the actual ArcGIS canvas/graphics. An added marker-click check initially tried an off-camera point after filtering; it was corrected to use the existing FIT control before clicking, consistent with the map's intentional camera preservation. The final run passed. Visual evidence waits for a settled map rather than photographing an initial loading frame.

Commands used (repository-relative working directories):

```bash
# decoder-ui
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=service:../src \
  env -u FLEET_SYNC_ENABLED python -m pytest tests -q
ruff check service/fleet_status.py tests/test_fleet_status.py tests/test_fleet_status_audit.py

# decoder-ui/frontend
npx tsc --noEmit
npm test
FLEET_E2E_BASE=http://127.0.0.1:3000 \
FLEET_E2E_REQUIRE_FRESH=1 \
FLEET_E2E_EXPECTED=/home/user/float-status-audit/expected-upstream.json \
FLEET_E2E_OUTAGE=/home/user/float-status-audit/controlled-outage-payload.json \
npm run test:fleet
```

Live verification used external `ARGO_UI_DATA_DIR`, `DATA_SOURCE=local`, explicit anonymous fleet sync and disabled/blank mail configuration. No decoding or email workflow was triggered. Both audit servers were stopped after verification.

## I. Remaining limitations and decisions

1. **Configured-DAC scope:** 6902892 and 6903014 are not globally unavailable; their Coriolis products exist. Following each preset to its actual DAC remains an explicit source-policy decision. The app was not silently broadened after the clarification was skipped.
2. **Legacy communication unavailable under the receipt/end policy:** 2901305 and 2901328 have measured positions and estimated transmission-start evidence, but no qualifying last-message/end field in the inspected products. Those other timestamps cannot establish the required Last Transmission.
3. **Upstream recency/data quality:** newer profiles and older trajectory communications can coexist. The app exposes that disagreement and uses accepted QC for positions; it cannot establish a later actual transmission, a float's physical condition, or an unreported mission from the public products.
4. **Local/sanitized identity:** the 17 supplied IDs match repository records, not a private operational database. Fifteen CTS4 identities stay unavailable. No private telemetry or identifiers were provisioned.
5. **Metric definition:** profile counts mean distinct published positive cycles, not every vertical sensor grid; missing means gaps within `1..Prof#`. No unpublished tail or missed communication is inferred as a missing profile.
6. **Snapshot and migration:** values are verified as of the recorded checks, not guaranteed forever. The tracked historical cache intentionally remains untouched. On deployment, the updated service must revalidate it; until then legacy/stale data is explicitly qualified and disallowed transmission fields are withheld.
7. **External map assets:** live Esri imagery was verified in this environment; basemap availability still depends on that external service. Observation correctness does not depend on its imagery tiles.
8. **Build/core scope:** the standalone type check and actual dev-browser app passed. A new production bundle was not claimed: the earlier baseline build exhausted this sandbox's memory. Core-decoder tests/algorithms and unrelated baseline issues were outside this authorized fix scope and were not modified.

### Evidence index

- `field-comparisons.csv` — all **352** rendered UI/API/source/calculation rows.
- `WMO_COMPARISONS.md` — full field tables for eight representative real WMOs.
- `expected-upstream.json` — independently derived per-WMO source evidence, indices, QC and hashes.
- `upstream-downloads.json`, `aggregate-profile-downloads.json`, `alternate-products.json` — retrieval evidence.
- `verification.log`, `before-after.json`, `baseline/fixed-clock-payload.json`, `final-payload.json` — reference comparisons.
- `scheduled-sync/cycle-*.json` — actual successful final-run cache commits; earlier startup checks are in `scheduled-sync-initial/`.
- `failure-experiment/result.json`, `controlled-outage-payload.json` — explicitly controlled failure evidence.
- `service-tests.log/.xml`, `frontend-tests.log`, `typescript-final.log`, `scoped-ruff.log`, `browser-e2e.log` — test results.
- `browser/verification.json`, `browser/01-float-status.png`, `browser/02-settled-map.png`, `browser/detail-*.png`, `browser/controlled-ftp-failure-stale-cache.png` — real browser evidence.
- `scope-verification.json`, `git-status.txt`, `git-diff.patch` — change-scope proof and patch.
- `collect_upstream.py`, `collect_aggregate.py`, `independent_expectations.py`, `verify_payload.py` — read-only collection/comparison scripts. Raw public NetCDF downloads were kept in the ephemeral cache rather than added to the sanitized repository; URLs/hashes/extracted evidence persist here.
