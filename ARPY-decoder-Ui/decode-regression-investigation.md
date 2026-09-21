# Decode regression investigation (2026-09-17, read-only — no code changed)

Fleet: 32 floats. Baseline `batch-1789620037-fec0` (04:40:37 UTC): 21 COMPLETED / 11 ERROR.
Current `batch-1789628039-4b81` (06:53:59 UTC): 10 COMPLETED / 22 ERROR.
11 floats flipped COMPLETED → ERROR. No file was modified during this investigation.

## Timeline (established from batch records, output dirs, mtimes)

- **Sep 16 11:37–11:40** — genuine decodes: all 10 flipped CTS4 floats decoded
  with decoder 301 (15–39 outputs each); 2-float batch `1789558657` (1902844 +
  2902086) 2/2 fresh. Same 11 pre-existing errors as baseline, identical strings.
- **Sep 17 04:38–04:40** — genuine decodes incl. 2901339 (77 outputs),
  2901304 (25), 2902222 (8); 04:40:37 batch served **21/21 cached**
  (`cached=True`, `dur_s=0.0`) + the same 11 errors. CTS4 `meta.nc` files
  PROVEN present at 04:40 (pre-existing CTS4-5 errors cited only the SBD-group
  problem, so the meta.nc check passed).
- **06:50:03** — workspace restore (every restored file mtime 06:50). Restored:
  batch records, `output/` (ARGOS complete; CTS4 profile outputs mostly absent),
  SBD groups, PARTIAL `phase4_reference/raw/raw-files` (7 dirs), PARTIAL
  `sample_data/uploads` + `sample_data/argos`. NOT restored: `runs/*.json`,
  old PDFs, `data/cts4/ref/gdac_incois_301/` (all `incois_*_meta.nc`), raw dirs
  102510/152389(raw-files)/152390/102526/102507/75415, ~15 of 2901304's files,
  2 of 2902222's files. No post-restore deletions (all input-dir mtimes = 06:50).
- **06:53:59** — decode-all with empty cache (no run records → `bus.find_cached_successful_run`
  finds nothing) → all 32 genuinely decoded → 10 real successes + 22 errors.
- **07:13** — background ingestion poll touched `ingestion.json` (unrelated).

## Root cause (single, common — NOT a code regression)

**Input + run-record loss at the 06:50 workspace restore, unmasked by cache
evaporation.** The "21 successes" baseline was 100% cache; the current run is
the first genuine full decode since the restore, exposing inputs that are no
longer on disk. Three independent exonerations of the decoder stack:

1. Same stack (incl. G2) decoded all 10 flipped CTS4 floats on Sep 16.
2. 7 control floats reproduce cached outputs EXACTLY (1902844 27/23,
   2904082 28/24, 6990711 11/7, 7902408 19/15, 2902201/03/06 + 2902223 8/3);
   1902844 `meta.nc` old-vs-new is byte-identical except run-stamped
   DATE_CREATION/DATE_UPDATE/history.
3. All 22 failures occur in staging/discovery/metadata-load, BEFORE any
   decoder/writer invocation. G2 is writer-only (`src/argo_decoder/writer/nc.py`,
   single file) and cannot produce MissingInput/DISCOVERY/CONFIGURATION errors.
   Decoder routing identical for all 32 WMOs baseline → current.

## Failure classes

| # | WMOs | Error | Stage | Missing input |
|---|------|-------|-------|---------------|
| 10 (flipped) | 2902086/87/88/92/93/2114/2115/2118/2130/2131 | `MissingInput: CTS4 GDAC meta.nc missing: (none staged)` | Pre-decode staging gate (`api.py:_cts4_missing_inputs`, HTTP 400; run_id minted, no run record) | `data/cts4/ref/gdac_incois_301/incois_<wmo>_meta.nc` (whole subtree gone; SBD groups intact, 517 files) |
| 1 (flipped) | 2901339 (APEX/ARGOS, dec 1005) | `no input files found … phase4_reference/raw/raw-files` | DISCOVERY (`runner.py` ~L150-219; meta.nc+xml still emitted) | raw group `102510` (had 77 outputs from 04:38 real decode) |
| 4 (pre-existing, failing since ≥Sep 16) | 2901305/28/50 (1005), 2902224 (1010) | same discovery error, identical strings | DISCOVERY | raw groups 102526/102507/75415/152390 (never in this workspace state) |
| 5 (pre-existing, ≥Sep 16) | 2902089/90/91/2113/2120 (301) | SBD group missing (+ meta.nc missing now) | Staging gate | no SBD group ever staged (supplier set has 10 groups) + meta.nc |
| 2 (pre-existing, ≥Sep 16) | 6902892 (221), 6903014 (212) | `FileNotFoundError: No info JSON … sample_data/config_floats/json_float_info` (`json_loader.py:79` via `runner.py:100`) | CONFIGURATION / metadata load | info JSONs (dir holds only 9 files for other floats) |

Diminished-but-completed (same cause, partial inputs): 2901304
(`sample_data/uploads`: 5 files now vs 20 cycles before → 4 outputs, 0 profiles)
and 2902222 (`sample_data/argos/152389`: 1 file now vs 3 cycles → 6 outputs,
1 profile). Surviving files keep identical naming/format — counts only.

Notes: (a) previous-success RUN records are gone (only batch summaries +
`output/` artifacts survive), so log-vs-log comparison was batch+output based.
(b) CTS4 old output dirs hold ≤6 files vs 15–39 claimed by Sep-16 run records —
old CTS4 profile outputs were pruned separately; irrelevant to decode ability.
(c) README lists 13 meta.nc (excl. 2902130/2131) yet both decoded Sep 16 → list
is imprecise; 15 were needed. (d) 6903014's message format differs (bare vs
traceback) but raise site/line numbers are identical — cosmetic.
(e) `find /home/user` confirms missing inputs exist NOWHERE (not relocated);
`incois_*_meta.nc` absent workspace-wide; supplier zip deleted per README.

## Responsible files/components

- Data (cause): `data/cts4/ref/` (absent), `phase4_reference/raw/raw-files/`
  (partial), `sample_data/uploads` + `sample_data/argos` (partial),
  `sample_data/config_floats/json_float_info` (standing gap),
  `decoder-ui/data/runs/` (pre-06:54 records absent → cache empty).
- Code (correct behavior, failure sites only): `service/api.py`
  `_cts4_missing_inputs` + `_start_cts4_decode`, `src/argo_decoder/pipeline/runner.py`
  discovery + `load_info` call, `src/argo_decoder/metadata/json_loader.py:79`,
  `service/event_bus.py` `find_cached_successful_run`/`_load_from_disk`,
  `service/path_resolver.py` `build_dynamic_float_presets`/`find_cts4_meta_dir`.

## Recommended fix (after investigation; nothing changed yet)

1. Re-stage inputs from the authoritative restore source (Drive snapshot):
   full `data/cts4/ref/gdac_incois_301/` (all 15 `incois_*_meta.nc`), missing
   raw-files groups (102510/102526/102507/75415/152389/152390),
   `sample_data/uploads` + `sample_data/argos` balance, and (if those floats
   matter) 6902892/6903014 info JSONs — or formally descope them.
2. Re-run decode-all; expect 21+ real successes. No code changes required.
3. Optional hardening: startup input-inventory check warning on unstaged
   groups; keep run records in restore snapshots; UI already labels
   cached-vs-fresh (keep it prominent).
