# Real-WMO field-by-field comparisons

Actual rendered UI versus the served API and independent source evidence. The full CSV covers all 32 WMOs (352 requested fields).
All dates are UTC. “Verified” means agreement with the specified source, not independent proof of physical float condition. Local/sanitized identities are explicitly distinguished.

## WMO 2902223 — APEX / ACTIVE
API calculation time: `2026-09-20T21:44:51.578991+00:00`.

Communication source: [2902223_Rtraj.nc](https://data-argo.ifremer.fr/dac/incois/2902223/2902223_Rtraj.nc), `JULD_LAST_MESSAGE[342]` (zero-based).

Position: [2902223_Rtraj.nc](https://data-argo.ifremer.fr/dac/incois/2902223/2902223_Rtraj.nc), `LATITUDE/LONGITUDE[9383]`, `JULD`, QC `1`.

| Field | Rendered UI | decoder-ui/API | Independent source / calculated value | Verification |
|---|---|---|---|---|
| WMO ID | 2902223 | 2902223 | 2902223 | LOCAL + UPSTREAM VERIFIED |
| Internal ID | 152382 | 152382 | 152382 | LOCAL SOURCE MATCH |
| Float Type | APEX | APEX | APEX | LOCAL + UPSTREAM VERIFIED |
| Latitude | 45.719°S | -45.719 | -45.719 | UPSTREAM VERIFIED |
| Longitude | 8.043°E | 8.043 | 8.043 | UPSTREAM VERIFIED |
| Last Transmission | 2026-09-12 06:10 UTC | 2026-09-12T06:10:30+00:00 | 2026-09-12T06:10:30+00:00 | UPSTREAM VERIFIED |
| Expected Next Communication | 2026-09-22 06:10 UTC | 2026-09-22T06:10:30+00:00 | 2026-09-22T06:10:30+00:00 | POLICY CALCULATION VERIFIED |
| No Communication / elapsed days | 8 d | 8.64886087 | 8.64886087 | POLICY CALCULATION VERIFIED |
| Communication Status | ACTIVE | ACTIVE | ACTIVE | POLICY CALCULATION VERIFIED |
| Prof# (highest cycle) | 353 | 353 | 353 | UPSTREAM LISTING VERIFIED |
| Profiles Missing | 3 | 3 | 3 | UPSTREAM LISTING VERIFIED |

Internal-ID source: `config/metadata/meta.csv:3 [Argos number, else imei]`.
Prof# `353`; **available profile cycles `350`**; missing-file cycles `158, 161, 345`.

## WMO 2902222 — APEX / OVERDUE
API calculation time: `2026-09-20T21:44:51.578991+00:00`.

Communication source: [2902222_Rtraj.nc](https://data-argo.ifremer.fr/dac/incois/2902222/2902222_Rtraj.nc), `JULD_LAST_MESSAGE[339]` (zero-based).

Position: [2902222_Rtraj.nc](https://data-argo.ifremer.fr/dac/incois/2902222/2902222_Rtraj.nc), `LATITUDE/LONGITUDE[10835]`, `JULD`, QC `1`.

| Field | Rendered UI | decoder-ui/API | Independent source / calculated value | Verification |
|---|---|---|---|---|
| WMO ID | 2902222 | 2902222 | 2902222 | LOCAL + UPSTREAM VERIFIED |
| Internal ID | 152389 | 152389 | 152389 | LOCAL SOURCE MATCH |
| Float Type | APEX | APEX | APEX | LOCAL + UPSTREAM VERIFIED |
| Latitude | 59.985°S | -59.985 | -59.985 | UPSTREAM VERIFIED |
| Longitude | 132.847°W | -132.847 | -132.847 | UPSTREAM VERIFIED |
| Last Transmission | 2026-08-12 15:22 UTC | 2026-08-12T15:22:42+00:00 | 2026-08-12T15:22:42+00:00 | UPSTREAM VERIFIED |
| Expected Next Communication | 2026-08-22 15:22 UTC | 2026-08-22T15:22:42+00:00 | 2026-08-22T15:22:42+00:00 | POLICY CALCULATION VERIFIED |
| No Communication / elapsed days | 39 d | 39.26538865 | 39.26538865 | POLICY CALCULATION VERIFIED |
| Communication Status | OVERDUE | OVERDUE | OVERDUE | POLICY CALCULATION VERIFIED |
| Prof# (highest cycle) | 350 | 350 | 350 | UPSTREAM LISTING VERIFIED |
| Profiles Missing | 1 | 1 | 1 | UPSTREAM LISTING VERIFIED |

Internal-ID source: `config/metadata/meta.csv:2 [Argos number, else imei]`.
Prof# `350`; **available profile cycles `349`**; missing-file cycles `349`.

## WMO 1902844 — ARVOR / NO COMMUNICATION 60+ DAYS
API calculation time: `2026-09-20T21:44:51.578991+00:00`.

Communication source: [1902844_Rtraj.nc](https://data-argo.ifremer.fr/dac/incois/1902844/1902844_Rtraj.nc), `JULD_LAST_MESSAGE[12]` (zero-based).

Position: [R1902844_025.nc](https://data-argo.ifremer.fr/dac/incois/1902844/profiles/R1902844_025.nc), `LATITUDE/LONGITUDE[0]`, `JULD_LOCATION`, QC `1`.

| Field | Rendered UI | decoder-ui/API | Independent source / calculated value | Verification |
|---|---|---|---|---|
| WMO ID | 1902844 | 1902844 | 1902844 | LOCAL + UPSTREAM VERIFIED |
| Internal ID | 123230 | 123230 | 123230 | LOCAL SOURCE MATCH |
| Float Type | ARVOR | ARVOR | ARVOR | LOCAL + UPSTREAM VERIFIED |
| Latitude | 9.853°N | 9.85295 | 9.85295 | UPSTREAM VERIFIED |
| Longitude | 65.997°E | 65.99677 | 65.99677 | UPSTREAM VERIFIED |
| Last Transmission | 2026-05-04 07:00 UTCTRAJ LAG | 2026-05-04T07:00:15+00:00 | 2026-05-04T07:00:15+00:00 | UPSTREAM VERIFIED |
| Expected Next Communication | 2026-05-14 07:00 UTC | 2026-05-14T07:00:15+00:00 | 2026-05-14T07:00:15+00:00 | POLICY CALCULATION VERIFIED |
| No Communication / elapsed days | 139 d | 139.61431226 | 139.61431226 | POLICY CALCULATION VERIFIED |
| Communication Status | NO COMMUNICATION 60+ DAYS | NO COMMUNICATION 60+ DAYS | NO COMMUNICATION 60+ DAYS | POLICY CALCULATION VERIFIED |
| Prof# (highest cycle) | 25 | 25 | 25 | UPSTREAM LISTING VERIFIED |
| Profiles Missing | 1 | 1 | 1 | UPSTREAM LISTING VERIFIED |

Internal-ID source: `config/metadata/meta.csv:13 [Argos number, else imei]`.
Prof# `25`; **available profile cycles `24`**; missing-file cycles `22`.

## WMO 2902086 — PROVOR_III / NO COMMUNICATION 60+ DAYS
API calculation time: `2026-09-20T21:44:51.578991+00:00`.

Communication source: [2902086_Rtraj.nc](https://data-argo.ifremer.fr/dac/incois/2902086/2902086_Rtraj.nc), `JULD_LAST_MESSAGE[244]` (zero-based).

Position: [2902086_Rtraj.nc](https://data-argo.ifremer.fr/dac/incois/2902086/2902086_Rtraj.nc), `LATITUDE/LONGITUDE[27995]`, `JULD`, QC `1`.

| Field | Rendered UI | decoder-ui/API | Independent source / calculated value | Verification |
|---|---|---|---|---|
| WMO ID | 2902086 | 2902086 | 2902086 | LOCAL + UPSTREAM VERIFIED |
| Internal ID | — | — | — | LOCAL SOURCE MATCH (sanitized/unavailable) |
| Float Type | PROVOR_III | PROVOR_III | PROVOR_III | LOCAL + UPSTREAM VERIFIED |
| Latitude | 18.330°N | 18.33004 | 18.33004 | UPSTREAM VERIFIED |
| Longitude | 84.768°E | 84.76787 | 84.76787 | UPSTREAM VERIFIED |
| Last Transmission | 2016-02-16 04:34 UTC | 2016-02-16T04:34:35+00:00 | 2016-02-16T04:34:35+00:00 | UPSTREAM VERIFIED |
| Expected Next Communication | 2016-02-26 04:34 UTC | 2016-02-26T04:34:35+00:00 | 2016-02-26T04:34:35+00:00 | POLICY CALCULATION VERIFIED |
| No Communication / elapsed days | 3869 d | 3869.71546966 | 3869.71546966 | POLICY CALCULATION VERIFIED |
| Communication Status | NO COMMUNICATION 60+ DAYS | NO COMMUNICATION 60+ DAYS | NO COMMUNICATION 60+ DAYS | POLICY CALCULATION VERIFIED |
| Prof# (highest cycle) | 244 | 244 | 244 | UPSTREAM LISTING VERIFIED |
| Profiles Missing | 0 | 0 | 0 | UPSTREAM LISTING VERIFIED |

Internal-ID source: `No PTT/IMEI in local identity registries (sanitized CTS4 data)`.
Prof# `244`; **available profile cycles `244`**; missing-file cycles `none`.

## WMO 2901305 — APEX / NO DATA
API calculation time: `2026-09-20T21:44:51.578991+00:00`.

No last-message or transmission-end field. Generic measurement JULD is not used.

Position: [2901305_Rtraj.nc](https://data-argo.ifremer.fr/dac/incois/2901305/2901305_Rtraj.nc), `LATITUDE/LONGITUDE[969]`, `JULD`, QC `1`.

| Field | Rendered UI | decoder-ui/API | Independent source / calculated value | Verification |
|---|---|---|---|---|
| WMO ID | 2901305 | 2901305 | 2901305 | LOCAL + UPSTREAM VERIFIED |
| Internal ID | 102526 | 102526 | 102526 | LOCAL SOURCE MATCH |
| Float Type | APEX | APEX | APEX | LOCAL + UPSTREAM VERIFIED |
| Latitude | 62.021°S | -62.021 | -62.021 | UPSTREAM VERIFIED |
| Longitude | 60.694°E | 60.694 | 60.694 | UPSTREAM VERIFIED |
| Last Transmission | — | — | — | UNAVAILABLE; NOT INFERRED |
| Expected Next Communication | — | — | — | UNAVAILABLE; NOT INFERRED |
| No Communication / elapsed days | — | — | — | UNAVAILABLE; NOT INFERRED |
| Communication Status | NO DATA | NO DATA | NO DATA | UNAVAILABLE; NOT INFERRED |
| Prof# (highest cycle) | 27 | 27 | 27 | UPSTREAM LISTING VERIFIED |
| Profiles Missing | 0 | 0 | 0 | UPSTREAM LISTING VERIFIED |

Internal-ID source: `config/metadata/meta.csv:6 [Argos number, else imei]`.
Prof# `27`; **available profile cycles `27`**; missing-file cycles `none`.

## WMO 2901328 — APEX / NO DATA
API calculation time: `2026-09-20T21:44:51.578991+00:00`.

No last-message or transmission-end field. Generic measurement JULD is not used.

Position: [D2901328_098.nc](https://data-argo.ifremer.fr/dac/incois/2901328/profiles/D2901328_098.nc), `LATITUDE/LONGITUDE[0]`, `JULD_LOCATION`, QC `1`.

| Field | Rendered UI | decoder-ui/API | Independent source / calculated value | Verification |
|---|---|---|---|---|
| WMO ID | 2901328 | 2901328 | 2901328 | LOCAL + UPSTREAM VERIFIED |
| Internal ID | 102507 | 102507 | 102507 | LOCAL SOURCE MATCH |
| Float Type | APEX | APEX | APEX | LOCAL + UPSTREAM VERIFIED |
| Latitude | 11.826°N | 11.826 | 11.826 | UPSTREAM VERIFIED |
| Longitude | 80.065°E | 80.065 | 80.065 | UPSTREAM VERIFIED |
| Last Transmission | — | — | — | UNAVAILABLE; NOT INFERRED |
| Expected Next Communication | — | — | — | UNAVAILABLE; NOT INFERRED |
| No Communication / elapsed days | — | — | — | UNAVAILABLE; NOT INFERRED |
| Communication Status | NO DATA | NO DATA | NO DATA | UNAVAILABLE; NOT INFERRED |
| Prof# (highest cycle) | 98 | 98 | 98 | UPSTREAM LISTING VERIFIED |
| Profiles Missing | 6 | 6 | 6 | UPSTREAM LISTING VERIFIED |

Internal-ID source: `config/metadata/meta.csv:7 [Argos number, else imei]`.
Prof# `98`; **available profile cycles `92`**; missing-file cycles `81, 86, 87, 88, 89, 92`.

## WMO 2902224 — APEX / NO COMMUNICATION 60+ DAYS
API calculation time: `2026-09-20T21:44:51.578991+00:00`.

Communication source: [2902224_Rtraj.nc](https://data-argo.ifremer.fr/dac/incois/2902224/2902224_Rtraj.nc), `JULD_LAST_MESSAGE[333]` (zero-based).

Position: [2902224_Rtraj.nc](https://data-argo.ifremer.fr/dac/incois/2902224/2902224_Rtraj.nc), `LATITUDE/LONGITUDE[10497]`, `JULD`, QC `1`.

| Field | Rendered UI | decoder-ui/API | Independent source / calculated value | Verification |
|---|---|---|---|---|
| WMO ID | 2902224 | 2902224 | 2902224 | LOCAL + UPSTREAM VERIFIED |
| Internal ID | 152390 | 152390 | 152390 | LOCAL SOURCE MATCH |
| Float Type | APEX | APEX | APEX | LOCAL + UPSTREAM VERIFIED |
| Latitude | 42.097°S | -42.097 | -42.097 | UPSTREAM VERIFIED |
| Longitude | 33.661°W | -33.661 | -33.661 | UPSTREAM VERIFIED |
| Last Transmission | 2026-05-02 02:32 UTCTRAJ LAG | 2026-05-02T02:32:49+00:00 | 2026-05-02T02:32:49+00:00 | UPSTREAM VERIFIED |
| Expected Next Communication | 2026-05-12 02:32 UTC | 2026-05-12T02:32:49+00:00 | 2026-05-12T02:32:49+00:00 | POLICY CALCULATION VERIFIED |
| No Communication / elapsed days | 141 d | 141.80002985 | 141.80002985 | POLICY CALCULATION VERIFIED |
| Communication Status | NO COMMUNICATION 60+ DAYS | NO COMMUNICATION 60+ DAYS | NO COMMUNICATION 60+ DAYS | POLICY CALCULATION VERIFIED |
| Prof# (highest cycle) | 348 | 348 | 348 | UPSTREAM LISTING VERIFIED |
| Profiles Missing | 3 | 3 | 3 | UPSTREAM LISTING VERIFIED |

Internal-ID source: `config/metadata/meta.csv:4 [Argos number, else imei]`.
Prof# `348`; **available profile cycles `345`**; missing-file cycles `297, 338, 347`.

## WMO 6902892 — ARVOR_D / NO DATA
API calculation time: `2026-09-20T21:45:51.293639+00:00`.

No record in configured dac/incois; public dac/coriolis Rtraj independently confirmed by HEAD (not used without scope approval).

| Field | Rendered UI | decoder-ui/API | Independent source / calculated value | Verification |
|---|---|---|---|---|
| WMO ID | 6902892 | 6902892 | 6902892 | LOCAL SOURCE MATCH |
| Internal ID | 589584 | 589584 | 589584 | LOCAL SOURCE MATCH |
| Float Type | ARVOR_D | ARVOR_D | ARVOR_D | LOCAL SOURCE MATCH |
| Latitude | — | — | — | VERIFIED UNAVAILABLE IN CONFIGURED DAC |
| Longitude | — | — | — | VERIFIED UNAVAILABLE IN CONFIGURED DAC |
| Last Transmission | — | — | — | UNAVAILABLE; NOT INFERRED |
| Expected Next Communication | — | — | — | UNAVAILABLE; NOT INFERRED |
| No Communication / elapsed days | — | — | — | UNAVAILABLE; NOT INFERRED |
| Communication Status | NO DATA | NO DATA | NO DATA | UNAVAILABLE; NOT INFERRED |
| Prof# (highest cycle) | — | — | — | VERIFIED UNAVAILABLE IN CONFIGURED DAC |
| Profiles Missing | — | — | — | VERIFIED UNAVAILABLE IN CONFIGURED DAC |

Internal-ID source: `config/registry_apf9.csv:2 [ptt, else imei]`.
Prof# `—`; **available profile cycles `—`**; missing-file cycles `none`.
