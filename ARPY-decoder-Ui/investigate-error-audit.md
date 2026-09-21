# "Investigate Error" audit (2026-09-17, read-only — no code changed)

Scope: full flow error → capture → button → destination → operator-visible
information, across every failure category the system can produce.
Method: code trace (frontend + service + pipeline) + live Playwright
click-through of 3 REAL failure shapes + live triage endpoint output.
Labels: LIVE = observed in this deployment; TRACED = code path verified, no
live instance available. Nothing was modified.

## A. Complete current flow

1. **Capture (backend).** Three disjoint mechanisms:
   - Run record (`RunSummary` in `runs/*.json` + bus memory): status,
     `errors[]` strings, stage chips with `detail`, `active_operation`.
   - Events (`LiveEvent[]` per run): structlog→UI bridge maps KNOWN names to
     rich events; unknown names get generic mapping (level preserved);
     wrapper `except` paths emit `pipeline_error` / `cts4_pipeline_error`
     WITH `traceback.format_exc()` in `error_details`.
   - Batch item (`BatchFloatItem`): `status/error_message/error_type/run_id`.
     Legacy: `error_message = run.errors[-1]`, `error_type` unset. Outer
     `except` (pre-run failures): `str(exc)` + `type(exc).__name__`. CTS4
     staging gate: `"; ".join(problems)` + `"MissingInput"` — NO run/events.
2. **Triage (backend, separate surface).** `GET /batch/{id}/triage` classifies
   each non-completed item by regex over evidence (7 categories) + quoted
   root cause + recommended action. Shown ONLY in BatchResultsModal, NOT in
   the Investigate flow.
3. **Button (ResultsWorkspace).** Two sites, both require a run id: row button
   (`isFail && item.run_id`) and error-banner button (`activeRun?.run_id`).
   Both call `viewRun(runId, focusError=true)` + go to Decoder view.
4. **Destination (Decoder view).** `viewRun` fetches run + events(5000);
   selects targetEvent ?? first error event ?? LAST event; sets
   `logFilter="errors"`. CenterPanel shows ✕ banner (`run.errors[0]`), the
   errors-filtered log (selected event scrolled into view), and the
   EventDetailDrawer (stage/message/what_happened/source/cycle/traceback/
   payload). No run → `deepLinkNotice` + STALE current view.

## B. Error categories actually supported

Triage regexes: MISSING_FLOAT_INFO, MISSING_INPUT_FILES, CORRUPTED_INPUT
(`corrupt|checksum`), CONFIG_PATH_ERROR, DECODER_ERROR (traceback fallback),
USER_STOPPED, UNCLASSIFIED. Investigate mechanism itself is category-blind
(first error event + errors filter + banner).

## C. Verified to work (LIVE)

- Missing input/raw (2901339): banner + focused DISCOVERY error event. ✓
- Missing info JSON (6902892): banner + pipeline_error + traceback drawer. ✓
- Unexpected exception: same traceback path (6902892 IS one). ✓
- Triage quotes root cause + correct action for the above. ✓

## D. Fall back to generic logs (TRACED: no error EVENTS emitted)

Decoder `result.errors`-only failures (unsupported decoder id, ARVOR per-file
parse failures, `reconstruct_science` failure, unsupported firmware): run flips
ERROR with strings only. Investigate then shows: banner `errors[0]` (visible ✓),
errors-filtered log EMPTY ("No log events match"), drawer auto-opened on the
LAST (non-error) event with NO "not the error" signal. Operator can easily
misread the drawer as the cause. Compounded by errors[0]-vs-errors[-1]
inconsistency (decoder banner shows FIRST, Results row shows LAST).

## E. Not properly investigated

1. **Pre-run failures with no run record (LIVE, 2902086):** button shows
   (run_id minted) → 404 → notice mislabeled ("email deep link", "predate/
   cleaned up" — the run NEVER existed) + STALE wrong-float view (6902892's
   banner!). The real error text is left behind on Results. Affects all 15
   CTS4 staging failures + any mkdir/config pre-run failure.
2. **Writer per-file failures (TRACED):** caught → error EVENTS exist but
   `written[*_error]` has NO consumers → run stays COMPLETED → NO Investigate
   offered, triage skips → silent missing deliverables.
3. **Ingestion/source failures (verified absent):** header pill tooltip only;
   NewArrivalsPanel has no error UI and no investigate affordance; decode is
   decoupled from ingestion state.
4. **Stale-run fallback (TRACED):** `activeRun` falls back to ANY run with the
   same WMO → banner button / stage chips / cycles can show the WRONG run
   (e.g. an old success) for a currently-failed float.
5. **Triage action for no-run failures (LIVE):** UNCLASSIFIED action says
   "Open the run's event log (VIEW RUN)" — the log DOES NOT EXIST (404).

## F. Exact gaps

- G1 (LIVE): no-run Investigate → misleading notice + stale wrong-float view;
  error text stranded on Results.
- G2 (TRACED): zero-error-event ERROR runs → drawer presents a non-error event
  as if it were the focus, unlabeled.
- G3 (TRACED): writer failures → COMPLETED; missing deliverables invisible.
- G4 (TRACED): `activeRun` by-WMO fallback can bind the wrong run.
- G5 (LIVE): triage UNCLASSIFIED action points at a nonexistent log for the 15
  CTS4 floats; no MISSING_STAGED_INPUT category.
- G6 (code): `errors[0]` (decoder banner) vs `errors[-1]` (Results row) can
  disagree when >1 error.
- G7 (code): CORRUPTED_INPUT regex `checksum` over-matches ARVOR
  "unsupported firmware checksum" (routing issue, not damage) → wrong action.
- G8 (minor, observed): open inspector drawer overlaps header nav (blocks
  Results button until closed).

## G. Generic enough for future FTP/email/API ingestion?

PARTLY. The in-pipeline path (run record + events + banner + inspector) is
fully source-agnostic and will work unchanged whatever staged the inputs. But
pre-pipeline failures are NOT generic: any future staging gate that fails
without a run record repeats G1, and ingestion-layer failures have no failure
objects or investigate path at all. The architecture covers "decode failed",
not "data never arrived".

## H. Recommended changes (investigation only — NOT implemented)

1. Persist a minimal ERROR run record (+1 error event) for pre-run failures
   (CTS4 staging gate, mkdir/config outer-except) so Investigate + triage have
   a target; keep `error_type` (MissingInput/…) on it.
2. Fix the no-run notice: distinguish "never ran" from "cleaned up", drop the
   "email deep link" wording for in-app clicks, and render the batch item's
   error text inline instead of a stale run.
3. Emit error EVENTS for decoder `result.errors` (or bridge them at wrap-up)
   so focus + errors filter land on the true cause; label drawer fallback
   ("latest event — no error event recorded") when none exists.
4. Fold `written[*_error]` into run status (ERROR or explicit PARTIAL) and
   triage (WRITER_OUTPUT category); never COMPLETED with failed deliverables.
5. Add triage categories: STAGED_INPUT_MISSING (CTS4/meta/SBD-specific action),
   UNSUPPORTED_FIRMWARE/PLATFORM (split from CORRUPTED_INPUT), WRITER_OUTPUT;
   make UNCLASSIFIED action run-aware (no log → say so + quote only).
6. Unify error ends: banner and row show the same string (prefer last +
   count, e.g. "… (+2 more in log)").
7. Tighten `activeRun`: prefer exact run_id; by-WMO fallback only with a
   "stale run" label, never silently.
8. Ingestion: give source failures a first-class error object + pill/panel
   affordance linking to it (future FTP/email/API ready).
9. Minor: drawer should not cover header nav (offset or lower z than header).
