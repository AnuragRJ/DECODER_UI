# INCOIS ARPY Decoder Workstation — End-to-End Functional Audit Report

**Date:** 2026-09-11 (IST) · **Method:** live black-box + code-level verification against the current workspace as source of truth (no code was modified)
**Stack under test:** FastAPI/uvicorn backend (`decoder-ui/service`, port 8000), Vite/React/Zustand frontend (`decoder-ui/frontend`, port 3000), real Python decoder (`src/argo_decoder`, `run_pipeline`), 17 discovered floats (15 in multi-CSV registry + 2 single-registry ARVOR), largest dataset 87 raw files (ARVOR 1902844).
**Evidence base:** Playwright UI suite (18/18 scenarios pass, run #5), scripted API/WS probes (single decode, batch decode, stop semantics, zero-file floats), persisted run/batch JSON + NetCDF cross-checks, and targeted source reads cited below.

> This is deliberately **not** a blanket "everything passed". The core decode path is real and sound, but the audit found **3 Critical, 5 Major, and 10 Minor** issues with exact root causes.

---

## 1. Executive summary

| Severity | Count | Findings |
|---|---|---|
| **Critical** | 3 | C-1 committed SMTP credentials · C-2 stale-contextvars batch corruption · C-3 Stop Decode silently ignored + UI state deception |
| **Major** | 5 | M-1 completion-stick UI race · M-2 zero-input runs produce contradictory pipeline state · M-3 RTQC modal is a static reference, not run data · M-4 "completed" runs with 0 profiles and no warning · M-5 Clear Logs ineffective during active decode |
| **Minor** | 10 | m-1…m-10 (below) |

Everything else verified in the 14 audit areas works correctly and is backed by real backend data (details in §3).

---

## 2. Findings (with exact root cause)

### CRITICAL

#### C-1 — SMTP credentials hardcoded as source defaults (security)
- **User impact:** Anyone with the code can send mail as the configured account; the password is effectively public.
- **Root cause:** `decoder-ui/service/email_notifier.py:71–76` — `EmailConfig.get_smtp_user()` defaults to a committed Gmail address and `get_smtp_password()` defaults to a committed **Gmail app-password** when the `SMTP_USER`/`SMTP_PASSWORD` env vars are unset:
  - `get_smtp_user()` → `os.environ.get("SMTP_USER", os.environ.get("SMTP_USERNAME", "<gmail address — masked>"))`
  - `get_smtp_password()` → `os.environ.get("SMTP_PASSWORD", os.environ.get("SMTP_PASS", "<app password — masked>"))`
  No `.env` file exists in the workspace, so these defaults are the live credentials. (Per audit constraint, values are masked here; see file/lines.)
- **Aggravating note:** `redact_secrets()` (email_notifier.py:44–52) correctly prevents the password from appearing in logs/email text — so the leak is in the source itself, not in runtime output.
- **Affects:** §9 (Email).

#### C-2 — Stale structlog contextvars corrupt batch preset resolution → intermittent `IsADirectoryError` for ARVOR floats
- **User impact:** Intermittent batch failure: a float that decoded fine in earlier batches errors in ~0.002 s with `IsADirectoryError: [Errno 21] Is a directory: '/home/user/config/metadata'`. Reproduced 3× this session (batches `…1789054372`, `…1789054466`, `…1789054670`); server log shows the swallowed warning `Failed to load multi-csv metadata … : Run run-1902844-… stopped by user request`.
- **Root cause chain (every link verified):**
  1. `runner_instrumentation.py:674` — `structlog.contextvars.bind_contextvars(run_id=run_id, wmo=wmo)` at decode start; **there is no `clear_contextvars()` anywhere** in the function (grep-verified).
  2. `api.py:35` — one shared `ThreadPoolExecutor(max_workers=8)`; threads are reused across tasks, and ContextVars persist per thread. After a **stopped** run on thread T, T's contextvars keep the cancelled `run_id` forever.
  3. `runner_instrumentation.py:89–104` — the UI-bridge structlog processor runs the cooperative-cancellation check on **every** backend log event: `if bus.is_run_cancelled(run_id): raise ExecutionCancelledException`.
  4. `api.py:195` — `_run_batch_worker` (running on a possibly contaminated thread) calls `path_resolver.build_dynamic_float_presets()`; its stage 1 instantiates `MultiCsvLoader`, which logs `multi_csv_loaded` → merge_contextvars injects the **stale** run_id → the bridge raises *for the old run*.
  5. `path_resolver.py` (stage-1 loop, `except Exception` around lines ~360–372) — the raise is swallowed as `Warning: Failed to load multi-csv metadata` → **all 15 csv4 presets are silently lost**.
  6. `api.py:239–240` — worker fallback: `meta_backend = preset["metadata_backend"] if preset else "csv"` → `"csv"`; `reg_path = preset.get("registry_path") if preset else str(reg_file)` with `reg_file = find_registry_csv()` (`api.py:202`).
  7. `path_resolver.py:151–160` — `find_registry_csv()` returns the first metadata **directory** (`/home/user/config/metadata`), not a file.
  8. `src/argo_decoder/metadata/csv_loader.py:100` — `CsvLoader` opens the directory → `IsADirectoryError`.
- **Why single decode is immune:** `api.py:133` — `req.metadata_backend or (…)`: the frontend request body carries the correct backend, so the fallback never triggers.
- **Why it's intermittent:** only threads that previously ran a *stopped* run are contaminated; a fresh thread decodes correctly.
- **Compounding design flaw:** the `backend="csv"` fallback assumes a *file* registry, but `find_registry_csv()` returns a *directory* whenever multi-CSV metadata dirs exist — the fallback path is broken by design for every float absent from the single-file registries.
- **Affects:** §2 (Decode All), §13 (regression: stop → subsequent batch on same thread).

#### C-3 — Stop Decode is silently ignored during no-log-event windows; the run completes; the UI reverts "stopped" → "active" → "completed"
- **User impact:** Pressing **Stop Decode** (or **Stop** on a batch) during the post-decode phase has **no effect**: the run finishes normally (all cycles, all outputs), no `decode_stopped` event is ever emitted, and the UI — which first shows "🛑 DECODE STOPPED BY USER: Execution halted immediately" — reverts to *running* ~150 ms later, then to *completed*. Reproduced twice (batch `…1789049476` item `run-1902844-5760c9`, stop at +6.0 s → completed 7.36 s; and single decode `run-1902844-5bd81b`, stop at +3.5 s → completed 4.83 s, both with 23/23 cycles and no `decode_stopped` event).
- **Root cause chain:**
  1. **Backend — check only fires on structlog events.** Cancellation is checked exclusively in `_structlog_ui_bridge_processor` (`runner_instrumentation.py:102–104`). Between the last backend log and run completion there are **no structlog events**: verified ARVOR 1902844 timeline — last log `pipeline_end` at +2.2 s (warm) / +3.96 s (cold, `run-1902844-5760c9`), while completion takes +4.8–7.4 s because the RTQC-verification phase emits only `bus.emit` LiveEvents (invisible to the bridge). A stop requested in that window is therefore never seen.
  2. **Frontend — optimistic stop is overwritten.** `stopDecode` (`useDecoderStore.ts:1035–1135`) immediately sets `status="stopped"`, `isRunning=false`, appends a **client-fabricated** stop event, *then* 150 ms later `syncRun` fetches the backend (still `active`) and `updateRunSummary` (`useDecoderStore.ts:784`) applies it unconditionally — `isRunning: run.status === "active"` with **no terminal-state guard** — so the UI reverts to *active*; the final `DONE` event then flips it to *completed*.
  3. **Batch scope:** `cancel_batch` (`event_bus.py:129–144`) sets batch `status=STOPPED` immediately (optimistic) and marks pending items stopped, but the running float may still complete → final batch JSON `status=stopped` with `completed_floats=1` (observed in `batch-1789049476-bbba`: "1 completed + 16 stopped"). Results page then shows a **STOPPED** batch containing a **COMPLETED** float.
- **Even when stop works, detection latency is unbounded:** stop is honored only at the *next* structlog log event. Measured on APEX 7902408 (64 files): stop requested at +1.2 s (`e2e_stop.py`), persisted run shows `decode_stopped` at +7.06 s with the last preceding log at +0.49 s — roughly 5.9 s of continued decoding after the user's request.
- **Affects:** §1 (Stop Decode), §2 (batch stop), §13 (stop during processing).

### MAJOR

#### M-1 — UI "completion-stick" race: run shows as running long after DONE (observed 3× in 6 decodes, ~33–50%)
- **User impact:** After a successful decode the UI can stay in the "running" state indefinitely; the only observed release is pressing Stop, which **mislabels the already-completed run as "stopped"**.
- **Root cause:**
  - Backend: the `DONE` event is broadcast while the run summary is still `active`; the **final `bus.store_run` (terminal state) is never broadcast** — `store_run` (`event_bus.py:166–173`) updates the dict and persists, but has no `broadcast_run_update` call.
  - Frontend: the 300 ms status poll races the WS `DONE`; `updateRunSummary` (`useDecoderStore.ts:784`) has no terminal-state guard, so a stale `active` poll processed *after* WS `DONE` (which clears the poll intervals) restores `isRunning=true` with nothing left to clear it.
- **Affects:** §1 (completion display), §3 (UI/backend agreement), §13 (success→next-action sequences).

#### M-2 — Zero-input runs: `run_pipeline` has no early return → contradictory final pipeline state + spurious artifacts
- **User impact:** Decoding a float with no raw files (e.g. 2901305, 2902224) ends as an *error* (correct, with a clear message), but the stage panel shows **`DISCOVERY=error` next to `DONE=completed`, `RTQC=active`, `OUTPUT=active`** — completed-without-evidence and stuck-active in the final state — and the run "produces" 2 deliverables (`<wmo>_meta.nc` + XML `nok`) for a decode that read nothing.
- **Root cause:** `src/argo_decoder/pipeline/runner.py:148–157` — on `if not files:` the pipeline logs `no_input_files` and **continues** (no return); decoder is still selected (line 213), outputs still written (lines 221–244); the error is only appended post-decode (lines 217–220). The instrumentation then marks `DONE` completed on the normal success path. (Prior audit labeled this "CRITICAL A"; on re-verification the run status *is* correctly `error`, so it is reassessed Major — the user is informed, but the stage timeline is self-contradictory.)
- **Evidence:** runs `run-2901305-15272f`, `run-2902224-d6bd14` (fresh, this session): status `error`, 0.05 s, 2 outputs, stage states as above.
- **Affects:** §1 (error display), §4 (pipeline stage integrity).

#### M-3 — RTQC modal is a static reference matrix, not the run's actual results
- **User impact:** The RTQC modal can display tests that were never executed for the current run (and never reflects which pass the run used); users can confuse "tests listed" with "tests executed".
- **Root cause:** `frontend/src/components/RtqcModal.tsx` — content comes from a hard-coded `RTQC_REFERENCE_TESTS` matrix (17 tests across PASS A/B/C/D tabs), default tab hard-coded `useState<RtqcPass>("PASS_A")`; the component has **no reference to `currentRun` or any `rtqc_pass` field**. The service model has `rtqc_pass` (`service/models.py:59`) but **no code path ever sets it**. Genuine per-run RTQC data (executed test IDs from NetCDF `tests_done`, flagged-level counts) is only shown in the RightPanel `RTQC (n)` summary and the `rtqc_verification_complete` event (`RightPanel.tsx:193,229`).
- **Affects:** §5 (RTQC), §1 (error/RTQC display).

#### M-4 — A run that produces **0 profiles** is reported as `completed` with no warning
- **User impact:** 2901304 decodes 5/5 cycles, writes only traj/meta/tech + XML (no profile NetCDF), `profile_count=0`, `missing_profiles=5` — and the run, batch and Results page all say *completed* as if normal. The primary scientific deliverable is silently absent.
- **Root cause:** completion is derived from pipeline status `"ok"` (`runner_instrumentation.py` success path; `PipelineResult.status = "ok" if not decoded.errors`), independent of profile yield; there is no rule demoting or warning on `profile_count == 0 < total_cycles`.
- **Evidence:** fresh run this session (status `completed`, 0.445 s, 5/5 cycles, 0 profiles; 4 deliverables, none a profile).
- **Affects:** §1 (completion), §6 (Results), §5 (RTQC had nothing to inspect — see consistency note below).

#### M-5 — Clear Logs during an active decode is effective for only ~300 ms
- **User impact:** Clicking **Clear Logs** mid-decode clears the panel, then the next 300 ms poll re-fetches the full backend event list and the logs re-populate (observed count 7→8→9→10 within ~1.2 s). For an active run the button is effectively a no-op.
- **Root cause:** `clearLogs` (`useDecoderStore.ts:1175`) clears local state but sets **no suppression flag**; `syncRun` (300 ms interval) unconditionally overwrites `eventsCache`/`events` with the backend's complete list (`useDecoderStore.ts:472–494`). There is no backend support for "events since cursor", so the cleared state cannot survive a poll.
- **Note:** "events continue after clear" (audit criterion) is satisfied — at the cost of the clear itself being ephemeral.
- **Affects:** §11 (Clear Functions).

### MINOR

| ID | Finding | Root cause (file:line / function) |
|---|---|---|
| m-1 | RtqcModal and OutputFilesModal have no Escape-to-close (button only) | `frontend/src/components/RtqcModal.tsx`, `OutputFilesModal.tsx` — no `keydown` listener |
| m-2 | Stale `*.json.tmp` files persist after a server crash (no crash-time cleanup); no data loss (final JSONs exist) | `event_bus.py:83–95` — tmp + `os.replace`, no startup sweep of orphaned tmps (`runs/run-2902203-7d2b92.json.tmp`, `run-2902222-564699.json.tmp`) |
| m-3 | EventDetailDrawer (480 px, z-40) auto-opens on deep-link/`viewRun` and covers header VIEW RESULTS/HISTORY until manually closed | `frontend/src/components/EventDetailDrawer.tsx` + `App.tsx:20–32` startup deep-link effect |
| m-4 | `decode_stopped` event lags the stop by ~1 s (async `emit_sync` → `run_coroutine_threadsafe`); immediate post-stop captures miss it — verify persisted data, not live captures | `runner_instrumentation.py` except-block → `event_bus.emit_sync`/`emit` |
| m-5 | Latent out-of-order persist race: the event snapshot is taken **before** acquiring `_disk_lock`, so a slower persist thread can write an older event list last | `event_bus.py:81` (snapshot) vs `:85` (lock) in `_persist_run_to_disk` |
| m-6 | Branding wording varies across surfaces: header = "INCOIS ARPY DECODER WORKSTATION" (✓); browser title = "INCOIS ARPY **Float Decoder — Real-Time Operations Workstation**" (`index.html:9`); left panel = "INCOIS ARPY **OBSERVATORY**" (`LeftPanel.tsx:158`); email = "INCOIS ARPY **Fleet Decoder Workstation**" / "**DECODER - BATCH PROCESSING REPORT**" (`email_notifier.py:244,293`) | inconsistent literals; exact product name only in `Header.tsx:74` |
| m-7 | Stop Decode injects a **client-side** stop event ("Execution halted immediately") not produced by the backend; normally wiped by the +150 ms sync, but momentarily present and contradicted by later completion events in the C-3 case | `useDecoderStore.ts:1087–1099` (fabricated `LiveEvent`) |
| m-8 | Hardcoded WMOs 2901304/2902223 exist in `path_resolver.py` fallback preset block — but **only** when the registry yields zero floats, plus `is_default` flags; the live fleet list (17 presets) is fully dynamic | `path_resolver.py` stage-0 fallback block (~lines 448–493); working as designed, noted for §2/§7 completeness |
| m-9 | Fresh run JSONs are unreadable for ~0–1 s after start (KeyError/missing file) — async write timing, resolves on its own | `event_bus.py:72–74` daemon-thread persist; API reads file directly |
| m-10 | Batch WS capture in harness tests recorded only a subset of events (3/17) — verified harness/capture timing artifact, **not** backend loss: persisted per-run event files and API `/events` are complete and ordered | Playwright harness connection window; backend re-verified directly |

---

## 3. The 14 audit areas — verification matrix

Legend: ✅ verified working · ⚠️ works with caveats (finding refs) · Evidence = how it was checked.

| # | Audit area | Result | Evidence / notes |
|---|---|---|---|
| 1 | **Single Float Decode** | ⚠️ | ✅ Real `run_pipeline()` executes (pipeline_start → … → pipeline_end all map to real structlog logs in `runner.py`); correct WMO honored; live WS logs ordered with real timestamps; 17 pipeline stages; cycles/profiles read from genuine NetCDF on disk; NC+XML written; error runs display full traceback + per-stage error (verified on 6903014 metadata error, 0.002 s). ⚠️ Stop Decode: C-3 (ignored in post-decode window), M-1 (completion-stick). Zero-input path: M-2. |
| 2 | **Decode All Today's Floats** | ⚠️ | ✅ Float list is dynamic — `build_dynamic_float_presets()` from multi-CSV registry (15) + single-registry merge (2); no hardcoded floats in the live path (m-8 fallback only). Per-float `run_id`; no log/state overwrite between floats (separate event caches verified); logs available after completion; float switching works; counts correct (`completed/failed/stopped` matched batch JSON). ⚠️ C-2 (intermittent preset corruption after a stopped run on a reused thread); C-3 (batch stop vs running float). |
| 3 | **Decoder Logs trace** | ✅ | ✅ Every UI event traced to a backend origin: structlog events (`runner.py:96,145,215,249` etc.) via the bridge, or pipeline actions (RTQC verification, artifacts). Chronology + timestamps monotonic; cycle numbers correct (1902844: 23 cycles); no duplicates/missing/stale in single decode (WS capture matched persisted file event-for-event). ⚠️ Only m-7 (client-fabricated stop event, ephemeral) and m-10 (harness capture artifact — backend complete). |
| 4 | **Right-side pipeline stages** | ⚠️ | ✅ Stage names/order/activation/completion match `run_pipeline()` flow; per-stage error states correct for metadata errors (CONFIGURATION error) and missing files (DISCOVERY error); no cross-run stage leakage (stages rebuilt per run_id). ⚠️ M-2: zero-input error runs end with `DONE=completed`, `RTQC=active`, `OUTPUT=active` (completed-without-evidence / stuck-active in the final state). M-1: UI can stick "running" after real completion. |
| 5 | **RTQC** | ⚠️ | ✅ RTQC genuinely executes (`apply_rtqc_to_profiles`); real QC flags; platform-specific behavior honored (TEST004 "Position on Land" omitted with reason `no_gebco_grid` for 2901304 — no GEBCO grid); post-run verification is consistent with the actual NetCDF output: 1902844 cross-verified 23/23 cycles; 2901304 "0 profiles inspected" matches `profile_count=0` (root cause M-4, not a false claim); RightPanel count comes from genuine `tests_done` (`RightPanel.tsx:193,229`). ⚠️ M-3: modal is a static 17-test reference matrix, default tab PASS_A, never synced to the run (`rtqc_pass` in `models.py:59` is never set). |
| 6 | **Results page** | ✅ | ✅ Batch summary values matched backend JSON; selected-float data belongs to the selected WMO (UI-13/15/16: switching floats swaps charts/counts correctly, no cross-float contamination); counts match `RunSummary`; charts use the correct float/cycle NetCDF data; CTD/RTQC/deliverables panels consistent. ⚠️ Inherits M-4 (a 0-profile run still presents as a normal completed result) and C-3 batch-stop display (STOPPED batch with a COMPLETED float). |
| 7 | **Fleet map** | ✅ | ✅ Fully dynamic: `FleetOceanMap.tsx` is 100 % prop-driven (`positions: FleetMapFloat[]`); basemap = bundled Natural Earth 110 m TopoJSON (`components/worldGeo.ts`, offline import) — legitimate static geography, **no hardcoded WMOs or float coordinates anywhere**; dynamic float count; only valid coords plotted; marker correctness; bidirectional selection sync (marker↔table); per-WMO real trajectories in cycle order; zoom/pan/reset; today's/future float sets work without frontend changes (positions derived from data). |
| 8 | **Full Screen Fleet View** | ✅ | ✅ Expand/exit works; map fills viewport; table functional; selection sync with normal view; search/filters work; View Run and Investigate Error deep-link correctly; no duplicated/stale state on close (UI-18). |
| 9 | **Email** | ⚠️ | ✅ Exactly one summary email per batch completion (single-send guard, `email_notifier.py` lock + call-path dedup); SMTP config from env vars; auth works (real send verified in earlier phase of this audit — not re-sent to avoid spam); `email_status=sent` only after SMTP acceptance; a failed email does not change decoder/batch outcome (status isolated); duplicate prevention verified; failure explanations built from real run data; deep links carry correct `run_id`+`event_id` and open the correct historical run/error (UI-15/16). ⚠️ **C-1: credentials committed as code defaults.** |
| 10 | **Run History** | ✅ | ✅ Runs persist as per-run JSON (`data/runs/run-*.json`, summary + full events); historical log reload complete; historical results match what ran (re-opened runs show identical cycles/outputs/counts); View Run works; no state leakage between historical runs (cache keyed by run_id). ⚠️ m-9 (fresh-file read window ~1 s), m-5 (latent out-of-order persist), m-2 (orphan tmp files). |
| 11 | **Clear Functions** | ⚠️ | ✅ Clear Summary: correctly scoped to the Results view (sessionStorage `argo_summary_cleared`; survives clean-URL reload; no auto-repopulation; does not stop the decoder; text CSS-uppercased to "RESULTS SUMMARY VIEW CLEARED"). ✅ Clear Logs on an idle run: works, history/NC/XML untouched. ⚠️ M-5: Clear Logs during an active decode re-populates on the next 300 ms poll (ephemeral). |
| 12 | **Branding** | ⚠️ | ✅ Core product name in the main header (`Header.tsx:74` "INCOIS ARPY DECODER WORKSTATION"); email/report branding consistent within the email; technical package names and scientific metadata left untouched (correct). ⚠️ m-6: wording varies in browser title, left panel ("INCOIS ARPY OBSERVATORY") and email subject lines — not a single consistent product string. |
| 13 | **Regression / state-integrity sequences** | ⚠️ | ✅ single→batch, batch→historical, success→failed, failed→success, clear-logs-during-decode, float-switch-while-running, open/close Full Screen — no stale Zustand, wrong run_id/WMO, duplication or loss beyond the findings above. ⚠️ **stop-during-processing** exposed C-3 (ignored in post-decode window) and C-2 (stop on a thread → later batch corruption on same thread). UI/backend disagreement windows: M-1 (stuck running), C-3 (stopped→active→completed), C-2 (batch stopped / float erroring). |
| 14 | **This report** | — | Per requirement: not a blanket pass; per-failure root causes with exact file/function. |

---

## 4. Working correctly (consolidated, verified)

1. **Real decode engine** — no simulation: `run_pipeline` with per-platform decoders (ARVOR/IRIDIUM_SBD decoder 232 for 1902844; APEX decoders for PROVOR floats); 1902844 decoded 23/23 cycles with NetCDF cross-verified on disk.
2. **Event pipeline integrity** — Python structlog → bridge processor → EventBus → WS/SSE → Zustand → UI: ordered, complete, no loss for single decodes; every UI event has a backend origin (except the ephemeral m-7 fabrication).
3. **Batch machinery** — dynamic discovery, per-float isolation, correct counting, post-completion log availability, float switching.
4. **Fleet map & full-screen view** — fully dynamic, no hardcoded geography/floats, bidirectional sync, all interactions functional.
5. **Results page data fidelity** — all displayed values traceable to backend run/batch data; no cross-float contamination.
6. **Run history persistence & reload** — complete and stable.
7. **Clear Summary** — correctly scoped, persistent, non-intrusive.
8. **Email functional behavior** — single send, env-var config, correct status transitions, working deep links, outcome isolation (credential handling aside: C-1).
9. **Error surfacing** — failed runs (metadata missing, no input files) show real tracebacks, per-stage errors, and correct `error` status.
10. **Cooperative stop works when log events are imminent** — verified: 7902408 stopped at +7.06 s after a +1.5 s request; 1902844 stopped at +2.07 s after a +2.0 s request (C-3 documents the gap case).

## 5. Not tested (out of scope or not re-executed)

1. **Live SMTP delivery this session** — verified in an earlier phase of this audit (real send + status transitions); not re-sent to avoid spamming the mailbox.
2. **Concurrent multi-user / WS load** — no load testing performed.
3. **Decoder behavior on genuinely new float data** — only the 17 known floats exist in the workspace; "today's/future sets" verified at the UI/discovery level, not with unseen real telemetry.
4. **Scientific validation of decoded physics** — file-level cross-checks done (cycle counts, artifact inventory, RTQC flags vs NetCDF); no independent ground-truth comparison of temperature/salinity values.
5. **Performance with large archives** — largest dataset exercised was 87 files (1902844).

## 6. Recommended remediation order (for the next work phase — no code was changed in this audit)

1. **C-1** — remove hardcoded SMTP defaults (env-var only, fail closed) and **rotate the exposed Gmail app-password immediately**.
2. **C-2** — `structlog.contextvars.clear_contextvars()` in a `finally` in `execute_decoder_with_observability`; make the bridge check skip events that predate the current run; fix the `csv` fallback to reject directory registries (or route to csv4 when a metadata dir is found); log the stage-1 preset failure as an error, not a swallowed warning.
3. **C-3** — add an explicit cancellation check at the start of the post-pipeline phase (before RTQC verification and before `store_run` terminal), or poll `is_run_cancelled` on a timer during long gaps; add a terminal-state guard in `updateRunSummary` and reconcile the UI stop flow with the real backend outcome.
4. **M-1** — broadcast the final terminal `store_run` from the backend (or make the poll respect a local terminal state).
5. **M-2 / M-4 / M-3 / M-5** — early return + consistent terminal stage states for zero-input runs; warn/demote 0-profile completions; bind the RTQC modal to the actual run; add event-cursor support (or poll suppression) for Clear Logs.

---

*All findings were verified live during the audit against the run/batch JSONs under `decoder-ui/data/runs/` and `decoder-ui/data/batches/`, the API/WS endpoints, and the cited source files; the batch JSONs cited above (e.g. `batch-1789049476-bbba.json`) remain in the workspace. (Note: the sandbox's per-turn snapshot restore rolled back part of `data/runs/` after the audit window, so a few individual run files cited — e.g. `run-1902844-5760c9`, `run-1902844-5bd81b` — are no longer on disk, though their event timelines were read and recorded verbatim during verification.) Investigation only — no application code was modified.*
