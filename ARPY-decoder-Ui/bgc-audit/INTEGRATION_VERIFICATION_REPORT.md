# Decoder-Backend Integration + Verification Report

- **Date:** 2026-09-16 · **Commit:** `4d94b37` (tree clean) · **Server:** :8000 UP, frontend rebuilt (`dist/`, build-only, zero source changes)
- **Scope kept:** decoder backend replaced; **zero** decoder-ui frontend/service changes (verified: `git status` shows only `src/argo_decoder/**` + 4 `config/metadata/provor_cts4_*.csv`).
- **Baseline method:** pre-existing persisted runs (`decoder-ui/data/runs/run-*-*.json`) + pre-existing outputs (`output/<wmo>/run_*`) + pristine-HEAD worktree for unit-test comparison.

## 1. Integration status: COMPLETE, additive-only

The supplied decoder proved to be a strict superset of the in-repo backend:

| Area | Change | Existing-functionality impact |
|---|---|---|
| `src/argo_decoder/` | **27 files added** (`platforms/provor_cts4_ir_sbd/` ×21, `writer/` ×3, `rtqc/{cts4,medd}.py`, `nc/rtraj_cts4.py`); **1 file extended** (`cli/main.py` +117 lines: `publish-cts4` only); **0 files deleted, 0 existing lines altered** | None — post-copy `diff -rq` old-vs-new = empty |
| `config/` | **4 files added** (`provor_cts4_*.csv`); 10 modified-looking CSVs proven **content-identical** (`diff --strip-trailing-cr`, line-endings only) → kept byte-as-was | None |
| `pyproject.toml` | Identical (no new dependencies; `gsw` is lazily imported) | None |
| `platforms/__init__.py` registry | Unchanged (APEX + ARVOR-I only; CTS4 not registered — carried-over gap G1, see issue I-1) | None |

## 2. Regression results: all-green (existing floats bit-identical)

| Check | Result |
|---|---|
| Single decode ARVOR 1902844 (`run-1902844-a057df`) | **completed, 23 cycles / 27 outputs** — cycle numbers, lat/lon, level counts, output filenames, RTQC masks (`qcp 87B4E`, tests 1,2,3,6,8,9,11,12,13,14,19), sample values, 17/17 stages — all **exactly equal** to baseline `run-1902844-113265` |
| NetCDF values 1902844 (cycles 001/012/023 + meta/tech/Rtraj) | **64/64 vars identical** except timestamp-only vars (`DATE_UPDATE/CREATION`, `HISTORY_DATE`, `SCIENTIFIC_CALIB_DATE`); global attrs identical; file inventory identical |
| Single decode APEX 2902222 (`run-2902222-0c933f`) | **completed, cycles 327/328/329 (58/59/58 lvls), 8 outputs** — matches baseline; R files + Rtraj (N_MEASUREMENT 63=63) **zero non-timestamp diffs** |
| Batch `decode-all` (force, 2 floats) | **completed 2/2**, PDF generated (`pdf_status: generated`), triage `[]`, batch persisted |
| Email/report flow | `email-config` OK; **2 real sends accepted** by SMTP (batch-completion auto-send + explicit `POST send-email` to configured recipient) with PDF attach (24,604 B) |
| APIs used by UI | `/api/health, /presets (17), /runs, /runs/{id}, /runs/{id}/events (10), /runs/{id}/cycles/{n}, /runs/{id}/outputs/{f}, /ingestion/*, /batch/*` — all 200, schemas unchanged |
| Map data / selected-float / profiles / RTQC / trajectories / logs / run status / persistence | Cycle lat/lon + `ctd_samples` + `rtqc_summary` payloads identical to baseline; structured pipeline logs streaming; runs/batches persist to `data/` |
| Repo unit tests (`tests/unit`: 997 passed / 24 failed) | **Failure list byte-identical on pristine-HEAD worktree** → all 24 pre-existing/environmental (e.g. hardcoded `/home/user/arvor_raw/...` absolute paths), zero caused by integration |
| New CTS4 unit tests (run against integrated tree) | **81 passed** (phase1/2a/4 + derived-doxy); integration tests skip cleanly (no raw corpus) |
| New-decoder entry points in-tree | `publish-cts4 --allow-synthetic` writes meta+tech; synthetic **BR file verified**: N_PROF=4/N_PARAM=6, correct STATION_PARAMETERS, all BGC vars+QCs, DATA_MODE RRRR; `run_cts4_rtqc` runs BGC tests 57/62/63; `load_reference` loads 15 WMOs from repo `config/` |
| Metadata loaders vs new CSVs | `MultiCsvLoader` loads 15 floats, ignores the 4 new CSVs (fixed filenames) — no warnings |

## 3. Per-issue reports (6-point format)

### I-1. 301/new floats cannot decode via decoder-ui — NO REGRESSION, pre-existing design gap
1. **Worked unchanged:** server stays up; run reaches clean `error` status; error persisted + served via API; identical handling for any unknown WMO.
2. **Stopped working:** nothing — 301 floats never decoded via UI (no registry entries, no raw corpus, CTS4 absent from `run_pipeline` registry).
3. **Exact behavior:** `POST /decode {"wmo":2902093}` → `IsADirectoryError: [Errno 21] Is a directory: '.../config/metadata'`, traceback `api.start_decode → run_pipeline(runner.py:100) → metadata_stage.py:125 → csv_loader.py:100 _ensure_loaded → path.open()`. Control `9999999` fails **identically**.
4. **Layer:** decoder-ui service/backend (preset-less fallback) + API/data contract (no 301 path). NOT the new decoder backend (its code is never invoked), NOT frontend.
5.. **Responsible:** `decoder-ui/service/path_resolver.py:152-161` (`find_registry_csv` returns the metadata **directory** first) combined with `api.py:start_decode` defaulting preset-less requests to backend `"csv"` with that path.
6. **Next phase:** (a) dedicated CTS4 service path wrapping `process_float` (or pipeline registration); (b) 301 presets + registry/metadata authoring incl. hand-authored `ExternalMeta` (BGC-report G4); (c) `.sbd` corpus ingestion; (d) service fallback should return a clear "float unknown/unsupported" error instead of `IsADirectoryError`; (e) fix backend BGC-report G2 (N_PROF≠4 template masking) + G3 (KeyError→AttributeError) **before** any UI consumes BR files.

### I-2. BGC capabilities present but unreachable + no real BR producible in-project
1. **Worked unchanged:** n/a (new capability; writer/equations/RTQC/reference verified working in-tree — §2 row 10).
2. **Stopped working:** nothing.
3. **Exact behavior:** `process_float` raises clean `FileNotFoundError: no .sbd under <group>` (`resolve.py:564`) — no CTS4 raw telemetry exists anywhere in the project; UI extraction is CTD/N_PROF-0-only so even a BR file on disk would surface zero BGC science (only its var names via the generic `variables[]` indexer).
4. **Layer:** API/data contract + missing input data (no code defect).
5.. **Responsible:** absence of `provor_bio_irsbd/raw_telemetry/SBD-BGC-raw/*` corpus (excluded from the supplied extraction) + `runner_instrumentation.extract_run_artifacts` CTD-only reader (by current design).
6. **Next phase:** ingest a CTS4 raw group (+GDAC meta.nc for `ExternalMeta`) to produce the first real BR; then implement BGC-report §M items 1–9 (service extraction, models, chart, types, modal, PDF wording).

### I-3. 24 repo unit-test failures — pre-existing, environmental, zero integration impact
1. **Worked unchanged:** 997 pass; all E2E decoder-ui flows green (§2).
2. **Stopped working:** nothing (identical failures on pristine HEAD worktree).
3. **Exact behavior:** e.g. `FileNotFoundError: /home/user/arvor_raw/...` — tests hardcode absolute paths absent from this machine; files: `test_arvor_i_frames` (14), `test_provor_ir_sbd` (4), `test_rtqc_trajectory` (3), metadata loaders (3).
4. **Layer:** repo tests/environment. NOT decoder backend, NOT decoder-ui.
5.. **Responsible:** `tests/unit/**` data-path assumptions (+ any genuinely stale golden; not investigated — out of scope).
6. **Next phase:** repoint test data paths to repo-relative fixtures if these tests are to gate CI; no decoder-ui change needed.

### I-4. Email really sends (observation, not a defect)
Real SMTP sends succeeded twice during verification (batch auto-send + explicit endpoint). Pre-existing behavior (`email_notifier.py` untouched). Next phase: consider a dry-run/test-mode guard for verification runs; no functional change required.

## 4. End summary

- **Integration status:** ✅ complete, committed (`4d94b37`), purely additive, tree clean.
- **Regression results:** ✅ zero regressions — existing ARVOR/APEX E2E outputs bit-identical (science), all UI APIs green, unit-test failures proven pre-existing.
- **Working features:** decode flow, run status/stages/events/logs, cycles, trajectories, map data (lat/lon), selected-float payloads, profiles/measurements, legacy RTQC masks, NetCDF outputs, batch + PDF + triage + email, ingestion, presets, run/batch persistence, new `publish-cts4` CLI, new writer/RTQC/equations/reference mechanism in-tree.
- **Broken features:** none newly broken. Still-absent (pre-existing): any 301/BGC decode via UI (I-1), real BR production for lack of corpus (I-2).
- **New BGC capabilities detected (in-tree, UI-unreachable):** full CTS4 telemetry→R/BR/meta/tech/Rtraj chain, Stern-Volmer DOXY + CHLA + BBP700 equations, 301 reference DB (15 WMOs), BGC RTQC tests 57/62/63 + MEDD-25, BGC publication writer (BR template, units, QC-9/0 policies, TELEMETRY_ORIGINAL/CORRECTED BBP modes).
- **Exact decoder-ui changes required next (no speculative fixes made):** ① CTS4 service path + 301 presets/registry + `.sbd` ingestion + `ExternalMeta` authoring (I-1⑥a–c); ② preset-less fallback error clarity (I-1⑥d); ③ N_PROF-aware BR reader + `CycleRecord` BGC slots + R/BR-split counts (BGC-report §M.1–2); ④ chart `paramKey` extension + results/table/columns (M.6–8); ⑤ RTQC modal BGC catalogue + PDF wording (M.4/M.9); ⑥ backend-first G2/G3 fixes with regression tests before any BR is displayed.
