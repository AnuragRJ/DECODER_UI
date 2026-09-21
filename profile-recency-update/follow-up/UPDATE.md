# Follow-up: aggregate profile products have caught up

**Verified at:** `2026-09-21T08:46:33.862637+00:00`. All dates are UTC.

The configured Ifremer `_prof.nc` products for **1902844, 2904082 and 7902408** were updated upstream at **08:24:12, 08:27:56 and 08:30:17 UTC on 21 September 2026**, respectively. Their latest profile JULD values now include the previously newer individual profiles.

The unchanged application's normal startup synchronization completed at `2026-09-21T08:44:59.090996+00:00`:

- **3 updated / 29 unchanged / 0 failed**.
- The three aggregate-lag notices are now cleared.
- Monitoring still uses only the specified `_prof.nc:JULD` source and the approved 10/60-day rules.
- **No additional implementation changes** were made: all **2710 repository file hashes** match the start of this follow-up.

## Updated real values

| WMO | Last Profile Date | Expected Next Profile | Days since profile | Approx. Profiles Missed | Data Status |
|---|---|---|---:|---:|---|
| 1902844 | 2026-09-18T08:55:55+00:00 | 2026-09-28T08:55:55+00:00 | 2.993505 | 0 | ACTIVE / RECENT PROFILE |
| 2904082 | 2026-09-19T09:06:17+00:00 | 2026-09-29T09:06:17+00:00 | 1.986306 | 0 | ACTIVE / RECENT PROFILE |
| 7902408 | 2026-09-19T12:07:01+00:00 | 2026-09-29T12:07:01+00:00 | 1.860797 | 0 | ACTIVE / RECENT PROFILE |

These are source-data updates, not a fallback to individual-profile dates or trajectory timestamps.

## Current fleet summary

| Total | Recent | Profile overdue | No recent profile data 60+ days | No data |
|---:|---:|---:|---:|---:|
| 32 | 4 | 2 | 24 | 2 |

## Verification performed in this follow-up

- Independently downloaded and parsed the three changed profile histories plus 2902223 as an unchanged control.
- Confirmed the four product hashes match the new FTP cache.
- Rechecked all **32** source-date → expected-date → elapsed-days → approximate-estimate → Data Status chains.
- Ran **17 browser checks**, confirming four recent-profile rows, the three corrected dates/statuses, their expected-next dates, zero approximate misses, and absence of the old aggregate-lag notices.
- No browser runtime errors were observed.
- Restored and started the API and Vite UI; the preview is available below.

[Open the updated preview](https://3000-iqia9n4bhypfcir8g69w2.e2b.app) → **View Results → Float Status**.

The earlier completion report and its CSV remain historical verification snapshots. The earlier aggregate-product lag was real at that time; it has now resolved for these three floats following upstream publication and normal synchronization.

Evidence: `fresh-profile-values.json`, `cache-before.json`, `cache-after-sync.json`, `live-payload.json`, `verification.json`, `browser-verification.json`, `updated-1902844.png`, and `four-recent-profiles.png`.
