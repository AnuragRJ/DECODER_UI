# Investigate-Error Targeted Fixes — Final Report

Date: 2026-09-17. Scope: `decoder-ui` ONLY (plus this report). `src/argo_decoder/` untouched.
Audit baseline: `/home/user/investigate-error-audit.md` (gaps G1–G8). Screenshots: `/home/user/verify-shots/`.

## 1. Files changed

**Backend — `decoder-ui/service/`**
- `models.py` — added `BatchFloatItem.error_count: int = 0` (drives the "(+N more)" suffix).
- `event_bus.py` — added pure `build_prerun_failure_record()` (ERROR summary + one error event per
  pre-run problem) and the `EventBus.record_prerun_failure()` wrapper (registers events, then the
  standard terminal store/persist path). No changes to `store_run`/persist/emit semantics.
- `api.py` — CTS4 staging gate now persists a pre-run ERROR record (`MissingInput`, per-problem
  stage via new `_cts4_problem_stage`); CTS4 + legacy batch `except` paths backfill a record only
  when none exists (`bus.get_run(run_id) is None` guard); `error_count` accounting on all item
  paths; cached items reset it to 0.
- `runner_instrumentation.py` — new `writer_errors_from_checksums()` (`*_error` keys in an
  otherwise-"ok" result force ERROR + OUTPUT stage; writer itself untouched); new
  `decoder_error_events_needed()` + bridged `decoder_error` events (labeled
  `data_sample={"bridged": True, ...}`) when `res.errors` has no error-level event; stage detail /
  `active_operation` now use the latest error (`errors[-1]`) instead of the first.
- `triage.py` — new categories `STAGED_INPUT_MISSING`, `WRITER_OUTPUT`, `UNSUPPORTED_PLATFORM`
  (+labels/actions); `UNSUPPORTED_*` signals checked before a narrowed `CORRUPTED_INPUT` regex so
  "unsupported firmware checksum N" is a mapping problem, not damage; `error_type="MissingInput"`
  hook; event `operation` added to evidence text; run-aware `DECODER_ERROR`/`UNCLASSIFIED` actions
  that never point at a nonexistent log when `run is None`.

**Frontend — `decoder-ui/frontend/src/`**
- `utils/investigate.ts` (new) + `utils/investigate.test.ts` (new) — `primaryError()` (latest
  meaningful error + remainder count) and `primaryErrorSuffix()` (" (+N more)").
- `types/index.ts` — `BatchFloatItem.error_count`.
- `components/ResultsWorkspace.tsx` — `activeRun` binds by EXACT `run_id` only (same-WMO stale
  fallback removed); run-detail fetch only when uncached and only by exact id; each row resolves
  its OWN run for the primary-error suffix; detail banner uses primary+suffix; all Investigate/VIEW
  callers pass the item's error as `fallbackError`. Also fixed two pre-existing infinite-fetch
  loops this work exposed (detail effect re-fetching zero-cycle runs; hydration effect with
  `runsCache` in deps re-triggering `fetchAllRuns()`): 528→0 and 78→0 `/api/runs*` reqs/9s.
- `components/CenterPanel.tsx` — decoder banner uses primary error + suffix.
- `store/useDecoderStore.ts` — `viewRun(runId, focus, eventId?, {fallbackError?, viaEmail?})`:
  missing runs now RESET to an empty context (never a stale run) with run-aware wording, incl. the
  known-error variant; error focus without any error event is labeled
  "Latest event shown — no error event was recorded".
- `App.tsx` (passes `viaEmail`), `components/BatchResultsModal.tsx` (passes `fallbackError`).
- `components/EventDetailDrawer.tsx` — `fixed top-14 bottom-0` (header is `h-14`; nav clickable).
- `components/Header.tsx` — ingestion pill tooltip appends `last_error` when present (fix 7 wiring;
  the backend `SourceStatus.last_error` → `status_payload` path already existed).

**Tests**
- `decoder-ui/tests/test_investigate.py` (new, 17 tests) — pre-run builder (single/multi/unknown
  stage), bus persist round-trip to tmp dirs, writer/bridge helpers, all new triage categories with
  REAL observed texts, firmware-vs-corruption split, `error_type` hook, run-aware no-run actions,
  plus 2 `execute_decoder_with_observability` integration tests (service-level monkeypatched
  `run_pipeline` — writer-`ok`→ERROR/OUTPUT+bridge, and errors-without-events→bridged events).

## 2. Fixes vs the 10 items
1. Pre-run/no-run failures persist a minimal ERROR record + ≥1 error event (CTS4 staging gate,
   CTS4/legacy raise-before-persist backfill); Investigate opens the exact failure; no same-WMO
   fallback; neutral wording with the real error inline for historical no-record cases.
2. Exact-`run_id` binding in Results (`activeRun`, fetch, row run lookup); stale display impossible
   (missing → null → "Run pending" + item error text, never another run's data).
3. Bridged `decoder_error` events when `run.errors[]` lacks error events, labeled as bridged; UI
   labels the latest-event fallback for pre-fix historical runs.
4. Writer `*_error` keys → run ERROR + OUTPUT stage + Investigate availability; writer untouched.
5. Primary = latest meaningful + "(+N more)" unified across row, Results banner, decoder banner,
   and `active_operation`/stage detail (`error_count` carried on the batch item).
6. Triage: `STAGED_INPUT_MISSING`, `WRITER_OUTPUT`, `UNSUPPORTED_FIRMWARE/PLATFORM` split ordered
   before narrowed `CORRUPTED_INPUT`; run-aware `UNCLASSIFIED`/`DECODER_ERROR` actions.
7. Investigation stays source-agnostic (run/event records); ingestion failures remain traceable via
   the existing `SourceStatus.last_error` object, now surfaced in the pill tooltip.
8. Decoder Log / Event Inspector flow preserved — same components, same open/focus mechanics
   (verified open with traceback + bridged/pre-run events in screenshots).
9. Drawer no longer covers header nav (verified clickable + screenshot).
10. Verification below.

## 3. Tests run
- `pytest decoder-ui/tests/`: **97 passed** (17 new).
- `vitest run`: **95 passed** (5 new). `tsc --noEmit`: clean.
- Playwright UI suite (scratch, since removed): **14/14 passed** (A1–E3). Screenshots kept.

## 4. Verification matrix (LIVE = observed on running servers 2026-09-17)
| Case | Result |
|---|---|
| CTS4 staging failure → record + error event + Investigate → triage/action | LIVE (batch-1789637790-c147 → run-2902086-b3f7fe; UI E0–E3; triage `STAGED_INPUT_MISSING`) |
| Missing input files (2901339) | LIVE (same batch; `MISSING_INPUT_FILES`; record + `no_input_files` event) |
| Missing info JSON (6902892) | LIVE (UI C1–C4; triage `MISSING_FLOAT_INFO`; two-error `(+1 more)` chain) |
| `result.errors` without error events → bridged events | INTEGRATION TEST + unit (no live decoder repro without corrupting inputs) |
| Writer `*_error` → ERROR + OUTPUT + Investigate | INTEGRATION TEST + unit (writer sabotage out of scope) |
| Unsupported firmware ≠ corrupted input | UNIT with real decoder template (no such float in fleet; data untouched) |
| Email deep link for pre-run record | LIVE (`?run_id=run-2902086-b3f7fe&focus=error` opens the run, no 404) |
| 404 deep link (old `run-2902086-f99ce7`) | LIVE (neutral notice + empty context, no stale run) |
| Multi-error `(+N more)` row/banner/investigation | LIVE (C1–C3) |
| Drawer/header overlap | LIVE (drawer below header in screenshot; header click with drawer open) |
| Decoder Log / Event Inspector preserved | LIVE (C4/E screenshots; those files unmodified) |
| Ingestion `last_error` surfacing | CODE-TRACED (tooltip renders it; live source currently healthy) |
| Success path / no-regression | LIVE (1902844 single decode 23/23 COMPLETED) + full suites |

One real summary email was sent (first 2-float verification batch); the post-recycle re-run used a
sinked SMTP host so no second email went out (email subsystem already proven). Servers left running
with the normal environment: backend :8000, frontend :3000.

## 5. Investigable failure categories (post-fix)
`MISSING_FLOAT_INFO`, `STAGED_INPUT_MISSING` (new), `MISSING_INPUT_FILES`, `WRITER_OUTPUT` (new),
`UNSUPPORTED_PLATFORM` (new), `CORRUPTED_INPUT` (narrowed), `CONFIG_PATH_ERROR`, `DECODER_ERROR`,
`USER_STOPPED`, `UNCLASSIFIED` (run-aware). Historical 32-float batch re-triage: 15 staged, 5
missing-input, 2 missing-info, 0 unclassified.

## 6. Remaining limits (explicit)
- PDF/email report body still quotes `errors[0]` (`report_data.py:287`) — outside the mandated
  row/banner/investigation surfaces; unify later if wanted.
- Theoretical `emit_sync`→persist race for bridged events is shared with the pre-existing
  `pipeline_error` path (async emit vs async persist threading); in-memory state is always correct.
- Single-float CTS4 API decode still returns HTTP 400 inline without a run record (API-surface
  error, shown directly to the caller); the batch path is the investigation context.
- Pre-fix historical failures can never gain records; they are handled via the fallback notice +
  run-aware triage, not hidden.
- No committed Playwright e2e (hardcoded batch ids + email side effects); regression protection is
  pytest + vitest. Re-run the UI click-throughs after future Results/decoder changes.
- OPERATIONAL: workspace is ~321 MB vs a ~128 MB snapshot cap — a recycle demonstrably dropped
  large run-JSON files (code small files survived). Archive/prune `output/` or accept shedding;
  treat email/PDF artifacts as the durable record for old batches.

## 7. `src/argo_decoder/` untouched — confirmation
Every write/edit operation in this session targeted `decoder-ui/`, `/home/user/*.md`,
`/tmp/*`, or `/home/user/verify-shots/`; zero tool calls referenced `src/`. (File mtimes are
uniform snapshot-extraction times and cannot serve as evidence either way.) Decoder
`runner.py`/`json_loader.py` re-parsed OK. No decoder behavior was changed; all failure-consumption
(writer keys, synthetic bridging) lives strictly in the service layer.
