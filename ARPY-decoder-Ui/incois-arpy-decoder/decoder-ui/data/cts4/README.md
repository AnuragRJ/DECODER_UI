# CTS4 / decoder-301 workstation inputs

Raw Iridium-SBD telemetry groups and GDAC metadata files that let the
decoder-ui service exercise the frozen CTS4/301 backend path
(`process_float`) on real floats. No file here is edited, renamed, or
re-generated: everything is staged verbatim from the supplier archive.

## Layout (mirrors the supplier tree)

- `SBD-BGC-raw/<group>/**.sbd` — 10 IMEI-suffix raw telemetry groups
  (`00530`, `03530`, `03580`, `06580`, `06640`, `12170`, `17960`, `20000`,
  `25980`, `29030`; 517 `.sbd` files total). A group directory name is only a
  label: the WMO is derived from the telemetry itself (FLBB serial from the
  250 free zone → `config/metadata/provor_cts4_301_reference.csv`), never from
  the directory name.
- `ref/gdac_incois_301/incois_<wmo>_meta.nc` — 13 INCOIS 301 GDAC metadata
  files (`2902086`–`2902093`, `2902113`–`2902115`, `2902118`, `2902120`).
  Each is the authoritative external source the backend reads via
  `build_external_meta_from_gdac` — no metadata is authored or inferred by
  the service.

## Provenance

| Field | Value |
|---|---|
| Source archive | `phase-6-2-1.1.zip` (supplier Drive file id `1d3Uw4av2wro0bsVoyHQerzYiNhXwBmJM`) |
| Archive size | 134,458,703 bytes (verified at download) |
| Staged | 2026-09-16: only the two subtrees above were extracted; the zip was deleted afterwards |
| Selection rule | `argo_workspace/provor_bio_irsbd/raw_telemetry/SBD-BGC-raw/*` (all groups) + `argo_workspace/provor_bio_irsbd/ref/gdac_incois_301/incois_*_meta.nc` (13 files) |

## Coverage notes (observed, not assumed)

- Groups `03530`/`03580` resolve to WMO `2902130`/`2902131`. Their GDAC
  `meta.nc` files were absent from the supplier snapshot and were fetched
  separately from the live GDAC (`https://data-argo.ifremer.fr/dac/incois/…`,
  verified PLATFORM_NUMBER match, PROVOR_III / WMO_INST_TYPE 836, N_PARAM 11)
  on 2026-09-16 — all 10 staged groups are now decodable.
- WMOs `2902089`, `2902090`, `2902091`, `2902113`, `2902120` have metadata but
  no staged raw group — likewise not decodable until telemetry arrives.
- Decodability is evaluated from these files at every `/presets` call; see
  `service/path_resolver.py` (CTS4 section) and `service/api.py` (CTS4 branch).
