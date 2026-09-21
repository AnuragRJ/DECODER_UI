# Coriolis demo-container removal + decoder-ui de-dependency

**Date:** 2026-09-21 · **Repo:** `/home/user/ARPY-decoder-Ui` (root) · **Scope edited:** `incois-arpy-decoder/decoder-ui`, `incois-arpy-decoder/config` · `src/argo_decoder/` **not touched**

---

## 1. What the folder was

`incois-arpy-decoder/Coriolis-data-processing-chain-for-Argo-floats-container/` — a 432-file,
477,796-byte (≈1.7 MB) tracked copy of the upstream Euro-Argo `decArgo_demo` layout:

| Content | Files | Purpose |
| --- | --- | --- |
| `decArgo_demo/config/decoder_conf.json` | 1 | Coriolis MATLAB-chain config (`/mnt/data/...` paths) |
| `decArgo_demo/config/decArgo_config_floats/json_float_info/` | 2 | JSON decode parameters for **6902892** (`6902892_300234065895840_info.json`) and **6903014** (`6903014_300234068508780_info.json`) |
| `decArgo_demo/config/decArgo_config_floats/json_float_meta_ir_sbd/` | 2 | `<WMO>_meta.json` for the same two floats |
| `decArgo_demo/input/rsync_list/300234065895840/` | 70 | Iridium rsync listing files (2020-06 → 2021-xx) |
| `decArgo_demo/input/rsync_list/300234068508780/` | 354 | Iridium rsync listing files (2020-09 → 2024-02) |
| `.gitkeep` placeholders | 3 | — |

Both floats are **IFREMER/SHOM Coriolis floats**, not INCOIS floats, and both are absent from
`dac/incois` (they were the two `NO DATA` rows in Float Status). Their only local decode
metadata and raw-input material lived inside this folder — verified: `sample_data/config_floats`
(the shared JSON preset directory) does **not** contain these WMOs, and the two `config/registry*.csv`
rows were literally annotated `bootstrapped from legacy json_float_info/json_float_meta`.

## 2. Dependency map (established before deleting anything)

| Dependency class | Finding |
| --- | --- |
| Presets selectable in the UI | 6902892 (`ARVOR_D`/`IRIDIUM_SBD`, PTT 589584, decoder 221) and 6903014 (`ARVOR`/`IRIDIUM_SBD`, PTT 850878, decoder 212), built from `config/registry.csv` + `config/registry_apf9.csv` |
| Code paths pointing into the folder | **only** 4 lines in `decoder-ui/service/path_resolver.py` — dead fallback candidates for `json_float_info` / `json_float_meta_ir_sbd` (the shared `sample_data/config_floats` directories already won, so they resolved to nothing even before deletion) |
| Input paths | no decoder-ui preset or runtime record pointed at `decArgo_demo/**`; the folder's `input/rsync_list/<IMEI>` trees were never wired into `find_raw_input_directories()` |
| Cached records | checked-in `decoder-ui/data/fleet_status/cache.json` (2 rows, `in_incois_dac=false`, no profiles, no trajectory) + preview runtime cache, run records and batch items |
| Tests / fixtures | profile-recency fixture row (2 floats), identity-map test, cache-record tests, fleet-size assertions |
| Everything else in the container | demo config + raw listings only, referenced by nothing in decoder-ui |

## 3. Removed (this task)

**Repository**

| # | Item | Change |
| --- | --- | --- |
| 1 | `incois-arpy-decoder/Coriolis-data-processing-chain-for-Argo-floats-container/` | **deleted** — `git rm -r`, 432 tracked files (staged `D`) |
| 2 | `decoder-ui/service/path_resolver.py` | −4 lines: the two `…Coriolis-data-processing-chain-for-Argo-floats-container…/json_float_info` and two `…/json_float_meta_ir_sbd` fallback candidates |
| 3 | `config/registry.csv` | rows `6902892`, `6903014` removed (7 → 5 lines) |
| 4 | `config/registry_apf9.csv` | rows `6902892`, `6903014` removed (12 → 10 lines) |
| 5 | `decoder-ui/data/fleet_status/cache.json` | 2 stale rows removed (32 → 30 rows) |
| 6 | `decoder-ui/tests/fixtures/fleet_profile_recency.json` | 2 float entries removed (32 → 30) |
| 7 | `decoder-ui/tests/test_fleet_status.py` | identity-map assertions moved to remaining floats (2901304 PTT 102525, 2901328 PTT 102507, empty IMEI) — the single-file-registry parse path is still exercised |
| 8 | `decoder-ui/tests/test_fleet_status_audit.py` | docstring, `test_all_32_existing_float_cache_records` → `test_all_cached_float_records_are_honest_before_recheck`, `NO DATA` count 32 → 30 (cycle sums 5625/5647/22 are unchanged — the two removed rows carried no profile data) |
| 9 | `decoder-ui/tests/test_profile_recency.py` | `…_all_32_wmos` → `…_all_30_wmos` |
| 10 | `decoder-ui/FLEET_STATUS.md` | the "6902892/6903014 show NO DATA" paragraph replaced by the fleet-definition statement; "32-WMO fixture" → "30-WMO fixture" |
| 11 | `decoder-ui/frontend/e2e/fleetStatus.e2e.mjs` | screenshot float list: removed 6902892 → 2901328 |

**Preview runtime state (outside the repo, `profile-recency-update/runtime/`)**

* `runs/` — 6 per-float run records deleted (`run-6902892-{095594,a557c8,e066f0}`, `run-6903014-{0637c3,5e6d1c,f13fca}`).
* `batches/*.json` — the two floats' `error` items removed from all 3 batches; `total_floats` 32 → 30, `failed_floats` 22 → 20, profile/output totals unchanged (those items produced none).
* `fleet_status/cache.json` — 2 rows removed, then rewritten by a **real** sync (see §5).

## 4. Deliberately preserved (untouched)

`config/metadata` CSV4 set (15 INCOIS floats) · remaining `config/registry.csv` / `registry_apf9.csv`
rows (2901304, 2901328, 2901339, 2901350, 2902201, 2902203, 2902206, 2902222, 2902223) ·
`sample_data/config_floats` JSON presets (shared, incl. all `json_float_meta_*` variants) ·
`data/cts4/` (518 files, 517 SBDs, README) · `data/geography`, `data/reports` ·
`service/fleet_status.py`, `service/api.py`, the profile-recency implementation and its contracts ·
`decoder-ui/data/fleet_status/cache.json` other 30 rows · **`src/argo_decoder/` — zero changes**.

**Fleet composition:** 30 WMOs — `1902844`; `2901304, 2901305, 2901328, 2901339, 2901350`;
`2902086–2902093`; `2902113, 2902114, 2902115, 2902118, 2902120`; `2902130, 2902131`;
`2902201, 2902203, 2902206`; `2902222, 2902223, 2902224`; `2904082`; `6990711`; `7902408`.

## 5. Verification (all live, 2026-09-21)

| Check | Result |
| --- | --- |
| Folder on disk | gone (`git status`: 432 staged deletions) |
| Preset discovery | **30** presets; zero container paths; zero `decArgo_demo` input paths; `find_provor_config_directories()` → shared `sample_data/config_floats/**` |
| `GET /api/presets` (direct + via UI proxy) | HTTP 200, 30 floats, 6902892/6903014 absent |
| UI float selector (`select[aria-label="Select Float Preset"]`) | **30 options**, no removed floats; default selection = 2901304; no `decArgo_demo`/container path rendered |
| Float Status page | **30 rows** (paginated 20+10), removed WMOs absent, 0 `NO DATA`, banned wording absent; search "6902892" → 0 rows, search "2901328" → 1 row |
| Live upstream sync | `last_success_at 2026-09-21T11:33:42Z`, `total 30 · updated 0 · unchanged 30 · failed 0`, 60.7 s |
| Summary now | `total 30, recent_profile 4, profile_overdue 2, no_recent_profile_60 24, no_data 0, approx_profiles_missed_total 7344, total_profiles 5628` (was 32/4/2/24/2/7344/5628) |
| decoder-ui backend tests | **248 passed** (0 failed) |
| Frontend unit tests / TypeScript | **144 passed** (14 files) / `tsc --noEmit` clean |
| Browser: post-cleanup script | **19/19** checks (`after/ui-verification.json`, screenshots `after/01–03*.png`) |
| Browser: existing `npm run test:fleet` harness | **661/661** checks, 30 floats field-checked (was 769 with 32 floats; the delta is exactly the removed floats' per-float checks) |
| App start-up | API `:8000` + UI `:3000` start clean; no page errors |
| Real decode, APEX float | **2902223 completed** — 3 cycles / 3 profiles / run `run-2902223-fd8bb4` |
| CTS4/BGC float | 2902086 correctly returned the documented HTTP 400 "CTS4 GDAC meta.nc missing (none staged)" — CTS4 data (517 SBDs) intact, behaviour unchanged |
| Core test parity (out-of-scope files) | **identical to baseline**: same 8 failures / 10 passes / 3 skips (`test_csv_metadata_pipeline`, `test_null_pipeline`, `test_structural_parity`, `test_metadata_loader`, `test_provor_ir_sbd`, `test_provor_sbd_decode`) → **the deletion causes no new core failure** |

## 6. Consequential notes

1. **The two floats are no longer anywhere in the UI**, including Fleet Status (their rows derive
   from the same presets). `NO DATA` metric went 2 → 0.
2. **Out-of-scope references still naming the folder** (not modified — outside `decoder-ui`,
   and `src/argo_decoder` + core tests are protected): `tests/conftest.py`,
   `tests/unit/test_metadata_loader.py`, `tests/unit/test_provor_ir_sbd.py`,
   `tests/integration/test_{csv_metadata_pipeline,provor_sbd_decode,null_pipeline,structural_parity}.py`,
   `scripts/bootstrap_golden.py`, `deploy/README.md` (docker `-v ../Coriolis-…/decArgo_demo/…` mounts),
   historical docs (`docs/*.md`, `README.md`, `IMPLEMENTATION_PROGRESS.md`, `MIGRATION_STATE_REPORT.md`,
   `handoff.md`), `src/argo_decoder/platforms/provor_cts4_ir_sbd/family_constants.py` (docstring only).
   These are either historical records of the upstream GitHub project or already-broken
   path computations (measured: no change in test outcome, §5). Say the word and I will update the
   deployment/script paths.
3. **Retained synthetic placeholders:** a few decoder-ui tests use the *number* `6902892` as an
   arbitrary sample token (`test_triage.py`, `test_investigate.py`, `test_email_deeplink.py`,
   `frontend/src/store/investigation.test.ts`, `frontend/src/utils/fleetStatus.test.ts`) and
   `e2e/investigationDetail.e2e.mjs` navigates to a stored run record of that WMO. They depend on
   no file from the deleted folder and create no selectable float; left untouched to keep the diff
   honest. Easy to re-token them if you prefer the number gone entirely.
4. `bgc-audit/argo_workspace/argo-decoder-python/` (an older full workspace copy used for the BGC
   audit) still contains the two registry rows and the folder name — it is a separate frozen
   artifact outside this repo, so it was left alone.
5. **Rollback:** `git checkout HEAD -- incois-arpy-decoder/Coriolis-data-processing-chain-for-Argo-floats-container incois-arpy-decoder/config incois-arpy-decoder/decoder-ui` restores everything
   (the tree is staged-deleted, not committed, and the prior task's uncommitted edits are preserved
   in the same working tree).

## 7. Evidence index

`before/folder-manifest.txt`, `before/folder-tracked-files.txt` (432), `before/json-sha256.txt`,
`before/presets-before.json` (32 floats), `before/git-status-before.txt` ·
`after/presets-after.json` (30 floats), `after/ui-verification.json`, `after/01-decoder-view.png`,
`after/02-float-status.png`, `after/03-filter-remaining-float.png`, `after/fleet-e2e.log` (661/661),
`after/backend-tests.log` (248), `after/frontend-tests.log` (144), `after/tsc.log`,
`after/cleanup.diff.patch`, `after/git-status-after.txt`, `verify_ui.mjs`.

Live now: API `:8000` (process "API server") and UI `:3000` (process "Decoder Workstation UI") —
the preview attached to the UI shows the 30-float fleet.
