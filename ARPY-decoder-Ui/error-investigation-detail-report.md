# Error Investigation Detail — implementation report

Date: 2026-09-17. Scope: `decoder-ui` ONLY. `src/argo_decoder/` untouched
(verified: every write this session targeted `decoder-ui/` paths only; no
standalone app; decoder log/event viewer, View Result page, RTQC, history,
controls, navigation and styling preserved).

## What was built

`View Result → Investigate Error` and `Email → View in Decoder` now open the
SAME interactive Error Detail view: WHAT happened first, then an optional
`View Decoder Log`. One rule drives every entry point: any
`viewRun(..., focusError=true)` opens the investigation above the log; plain
views never do. Zero caller changes — Results rows, batch inspection, and the
email deep link (`/?run_id=…&focus=error`) all funnel through that flag.

### Backend (`decoder-ui/service/`)

- `triage.py`: new pure builder `build_run_investigation(run, events)` —
  reuses the batch-triage engine (`triage_failed_float`, error-type hook) so
  Results, email and triage can never disagree. Returns category + label,
  root cause + recommended action + evidence, primary error (latest
  meaningful) + count + full list, `root_cause_available` (true only from
  ERROR evidence — recorded errors or an error-level event — never from the
  latest-event focus fallback), failure stage, per-stage states, focus event
  (error event preferred, else latest), run facts, `outputs_count`,
  `is_prerun`.
- `api.py`: `GET /api/runs/{run_id}/investigation` — thin lookup (404 when
  the run is gone) + builder. Read-only.

### Frontend (`decoder-ui/frontend/src/`)

- `types/index.ts`: `RunInvestigation`, `InvestigationFocusEvent`,
  `InvestigationStageState`.
- `utils/investigate.ts`: `buildProcessingTimeline` — the fixed 7-step
  Input → Discovery → Metadata/Staging → Decoder → NetCDF → RTQC → Output
  rollup (error → failed; active → active; all completed → completed; else
  not-reached; unknown keys ignored, never invented) + `timelineStepForStage`.
- `store/useDecoderStore.ts`: `investigation*` state, `openInvestigation`
  (fetch + supersede guard + honest fetch-error message),
  `closeInvestigation` (keep-focus → focused log; `{unfocusError:true}` →
  plain run view), `investigationMissing` for the run-not-started variant;
  wired into `viewRun` (focus opens incl. the 404 branch, plain closes) and
  cleared on `resetRun` / `startDecode` / `selectBatchFloat`.
- `components/ErrorInvestigationPanel.tsx` (new): fact grid (WMO, cycle,
  run id, status, failure stage, input source, failure time — `—` when
  absent, never invented), primary error + `(+N more)` + expandable full
  list with the primary marked, 7-card timeline, root cause
  (What/Where/Why + recommended action + evidence, else the exact line
  `Root cause unavailable`), gated evidence actions (`View Decoder Log`,
  `View Run`, `View Input` only with an input-stage event, `View Output`
  only with outputs), loading / fetch-error-with-retry / `Decoder run not
  started` (exact run id, no timeline, `Back to Results`) variants.
- `components/CenterPanel.tsx`: investigation slot — early return after
  hooks, same section wrapper; the 404 variant opens on its own flag
  (it has no active run).
- `components/EventDetailDrawer.tsx`: suppressed while the panel is open,
  restored on close. The log behind the panel keeps its error focus.

## The 10 verification cases (Playwright, 34/34 checks)

Script: `decoder-ui/frontend/e2e/investigationDetail.e2e.mjs`;
screenshots: `/home/user/verify-shots/investigation/`.

| # | Case | Result |
|---|------|--------|
| 1 | Results → batch → `[ INVESTIGATE ERROR ]` (WMO 6902892) opens the panel: heading, category, facts, primary error, all 7 timeline cards, drawer suppressed | PASS (11 checks, `inv-1-…`) |
| 2 | Email deep link `?run_id=…&focus=error` opens the SAME heading/view | PASS (2, `inv-2-…`) |
| 3 | `View Decoder Log` → panel closes, drawer + `NOTICES & ERRORS` focus restored | PASS (3, `inv-3-…`) |
| 4 | `View Run` → panel closes, focus cleared to `ALL EVENTS`, latest event selected | PASS (2, `inv-4-…`) |
| 5 | `View Output` hidden with 0 outputs (6902892), opens `ADMT-3.1 OUTPUT DELIVERABLES` with 2 (2901305) | PASS (3, `inv-5-…`) |
| 6 | `View Input` hidden without input events, opens the log at the DISCOVERY event with them (2901305) | PASS (3, `inv-6-…`) |
| 7 | Unknown run + focus → exact `Decoder run not started` + exact run id, no timeline, `Back to Results` | PASS (4, `inv-7-…`) |
| 8 | Multi-error: `(+1 more)`, `Show all 2 errors`, full list with primary marked | PASS (2, `inv-8-…`) |
| 9 | Completed run (no errors/events of error level): `root_cause_available=false`, empty primary, count 0 (API level — no Investigate entry exists for clean runs by design) | PASS (2) |
| 10 | Plain deep link (no focus): no panel, log + drawer render unchanged | PASS (2, `inv-10-…`) |

## Tests

- pytest: **102/102** (5 new `build_run_investigation` tests: multi-error,
  pre-run record, errors-without-error-events, empty, completed).
- vitest: **106/106** (5 new timeline tests, 6 new store flow tests).
- `tsc --noEmit`: clean.
- Live endpoint check: `/api/runs/run-6902892-011aef/investigation` returns
  `MISSING_FLOAT_INFO`, primary = latest traceback, count 2, focus
  `pipeline_error/CONFIGURATION`, stages-error `['CONFIGURATION']`; unknown
  id → 404.

## Email flow

No template change needed: the notifier already links
`/?run_id={run_id}&focus=error`. The store rule now lands that link on the
investigation view for the exact run (case 2 proves identity with the
Results entry); a shed/unknown run lands on the not-started variant with
the existing deep-link notice intact (case 7 screenshot).

## Pre-run

A persisted pre-run record investigates uniformly (builder test); a run id
with no record at all opens `Decoder run not started` with the exact id,
the reported error when one traveled along, and no fabricated log,
timeline, or run (cases 1-first-click and 7 both exercised this live).

## Known limits

- Case 9 is API + unit level: clean runs have no Investigate entry, so the
  `Root cause unavailable` panel variant renders only if opened
  programmatically; its render path is the same component, gated on the
  verified payload flag.
- `View Input` focuses the run's input-stage log event (no separate input
  file browser exists to reuse); it is hidden when the run has no such
  event.
- The investigation payload is fetched on open, not live-refreshed; the
  log behind it keeps streaming/polling as before.
- `src/`-untouched is evidenced by the session's write log (all writes
  under `decoder-ui/`), not by git (workspace is not a repo) or mtimes
  (reset by the workspace restore).
