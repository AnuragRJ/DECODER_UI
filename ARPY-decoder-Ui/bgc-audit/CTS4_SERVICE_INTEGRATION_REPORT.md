# CTS4/301 decoder-ui service-integration phase — report (2026-09-16)

Scope honored: **decoder-ui only**. `src/argo_decoder/` untouched (verified:
no working-tree change under `src/` by this phase). No G2/G3 backend fixes. No
frontend/UI changes (the frontend was only rebuilt from unchanged sources so
the preview serves). No BGC charts/tables/cards. Existing APEX/ARVOR behavior
verified byte-identical to baselines.

Standing discrepancy noted, not acted on: the prior-phase summary claimed the
decoder integration was committed as `4d94b37`; the tree actually holds those
files **uncommitted** (`M src/argo_decoder/cli/main.py` + untracked
`platforms/provor_cts4_ir_sbd/`, `writer/`, `rtqc/cts4.py`, `rtqc/medd.py`,
`nc/rtraj_cts4.py`, 4 `config/metadata/provor_cts4_*.csv`). Per this phase's
freeze they were left exactly as found; the commit below contains decoder-ui
paths only.

---

## A. Files changed in `decoder-ui`

| File | Change |
|---|---|
| `decoder-ui/service/path_resolver.py` | **Additive**: `import threading`; CTS4 section appended — `find_cts4_data_root / find_cts4_sbd_root / find_cts4_meta_dir`, cached `scan_cts4_groups()` (WMO derived from telemetry via frozen `decode_group`+`resolve_group`, never from dir names), `_discover_cts4_presets()` (one preset per reference WMO, honest readiness description); one guarded hook call in `build_dynamic_float_presets()`. No existing function body touched. |
| `decoder-ui/service/cts4_runner.py` | **New** (~470 lines): `execute_cts4_with_observability()` + `extract_cts4_artifacts()` + masked-QC-safe `_qc_char()`. Same run lifecycle as legacy (stages, events, STOPPED/ERROR paths, C-2 context clearing). Reuses shared helpers from `runner_instrumentation` by import (no copies). |
| `decoder-ui/service/api.py` | **Insertions only**: `from cts4_runner import …`; `_is_cts4_preset / _cts4_missing_inputs / _run_cts4_worker / _start_cts4_decode / _run_cts4_batch_item`; one branch in `start_decode`, one branch in `_run_batch_worker`. Zero legacy-line edits. |
| `decoder-ui/data/cts4/` | **New**: 517 staged `.sbd` (10 groups) + 13 GDAC `meta.nc` + provenance `README.md` (531 files, 4.9 MB). Verbatim extracts, nothing authored. |
| `decoder-ui/frontend/dist/` | Rebuilt from **unchanged** sources (build artifact, gitignored). |

---

## B. CTS4 service/decode flow implemented

```
GET /presets ──► build_dynamic_float_presets() ──► +15 CTS4 presets (8 decode-ready)
POST /decode ──► _is_cts4_preset? ──► YES: _start_cts4_decode
    │   inputs absent → HTTP 400 naming the exact missing file(s); nothing starts
    │   inputs present → RunSummary(ACTIVE) → thread_pool → execute_cts4_with_observability
    │   NO: unchanged legacy DecoderConfig path (byte-identical behavior)
Batch worker ──► same predicate per item; missing inputs fail the ITEM (MissingInput),
                 never the batch; sequential execution (no concurrency exposure)
```

`execute_cts4_with_observability(wmo, group_dir, meta_nc, out_root, run_id)` runs
the supplier's canonical frozen chain, in order, with service-side lifecycle
events carrying only observed data (origin honestly `service/cts4_runner.py`,
since the frozen backend emits no logs):

1. `decode_group(group_dir)` → event: internal cycles / SBD count (DISCOVERY)
2. `resolve_group(group_dir)` → event: FLBB serial → WMO, DOXY-cal kind
   (`DoxyCal` vs `KeyError` surfaced verbatim — the G3 observable) (WMO_MAPPING);
   WMO-mismatch / unresolvable serial → run ERROR, nothing published
3. `build_external_meta_from_gdac(meta_nc, wmo)` → event: serial, config
   params/missions (METADATA)
4. `process_float(group, wmo, out_root, external_meta)` → event: R/BR cycle
   lists, tech/Rtraj row counts (OUTPUT); each `skipped` entry → warning event
   with the backend's verbatim DATA-COVERAGE reason
5. `extract_cts4_artifacts(out_root/wmo, wmo)`: R files → CycleRecords
   (position/JULD/CTD samples/HISTORY masks via shared helpers); R→`mono_profile`,
   BR→`multi_profile`, `{wmo}_{meta,tech,Rtraj}.nc`→`meta/tech/traj` with
   sha256+dims+vars+attrs. No XML exists for 301 — none expected, none invented.
6. Terminal COMPLETED/STOPPED/ERROR + persistence, mirroring legacy math
   (`profile_count` = R files only, so R/BR counts never conflate — G6 avoided
   by construction).

Cancellation is cooperative at stage boundaries (before resolve, before/after
publication); the synchronous `process_float` call itself (~2–5 s) is not
interruptible mid-call — same class of guarantee as the legacy bridge, minus
per-log-line checks (the backend emits no log lines to hook).

---

## C. Whether a real 301/BGC float was decoded

**Yes — four distinct real floats, all through the workstation APIs:**

| Run | WMO (group) | Result | files/cyc/prof/outputs |
|---|---|---|---|
| `run-2902093-4fbe7a` (+ batch `run-2902093-420bdc`) | 2902093 (17960) | COMPLETED | 36 / 9 / 9 / 21 |
| `run-2902086-13e6ca` | 2902086 (12170) | COMPLETED | 63 / 15 / 15 / 34 |
| `run-2902115-9cc396` | 2902115 (00530) | STOPPED by user race-test, 17 cyc / 37 partials preserved | 72 / 17 / 17 / 37 |
| batch `batch-1789548652-8c9a` force `[2902093, 1902844]` | mixed CTS4+ARVOR | 2/2 COMPLETED, PDF 24,872 B, email sent | — |

An earlier `run-2902093-dbf607` completed with `cycles=0` due to a service-side
masked-QC parse bug (I-0, fixed, re-verified). Positions are real ocean fixes
(e.g. 2902093 cyc 45: 18.3727 N, 67.1806 E Arabian Sea; 2902086 cyc 104:
13.5892 N, 86.6927 E Bay of Bengal).

**Honestly not decodable (missing staged inputs, refused with exact 400s):**
2902130/2902131 (groups resolve, GDAC meta.nc absent from snapshot),
2902089/2902090/2902091/2902113/2902120 (meta staged, no raw group).

---

## D. Exact output files produced

Per successful run under `output/<wmo>/run_<ts>/<wmo>/` (gitignored runtime):

- `profiles/R<wmo>_<ccc>.nc` — core files (N_PROF 3–4, N_PARAM 3 PRES/TEMP/PSAL)
- `profiles/BR<wmo>_<ccc>.nc` — BGC files (N_PROF 3–4, N_PARAM 6; §G for the
  N_PROF=3 case); full channel set + per-level `_QC` + `PROFILE_*_QC` +
  `_ADJUSTED` triplets + `SCIENTIFIC_CALIB_*` + HISTORY (verified var list in
  §G/BGC note)
- `<wmo>_meta.nc` (N_PARAM 11 incl. all BGC params, N_SENSOR 6, N_MISSIONS 3),
  `<wmo>_tech.nc` (e.g. 950 rows), `<wmo>_Rtraj.nc` (e.g. N_MEASUREMENT 1228,
  N_CYCLE 11, MCs incl. BGC 290/301/589/590/599/700–704; DOXY 309 / CHLA 237 /
  BBP700 237 non-fill trajectory values)
- No XML (the 301 backend produces none; discovery expects none)

Service-run BR census: **67 BR files, 66× N_PROF=4 healthy, 1× N_PROF=3**
(`BR2902086_103.nc` — the G2 reproduction, §G).

**BGC data actually available (nothing invented):** every healthy BR carries
full water-column C1PHASE/C2PHASE/TEMP_DOXY/DOXY on the optode grid and
FLUORESCENCE/BETA/CHLA/CHLA_FLUORESCENCE/BBP700 on the fluorometer grid
(~140 levels/cycle, e.g. BR2902093_045: DOXY 143/143 on prof2, CHLA/BBP700
143/143 on prof3), each with level QC; Rtraj carries BGC park/RPP/surface/
ascent-sample series; meta/tech carry the BGC sensor inventory + 950-scale tech
rows. Gaps: N_PROF=3 BRs lose all sensor values (§G/G2); BR-only cycles
(no-CTD) have no R file and hence no CycleRecord (cycle API 404s, e.g.
`/cycles/103` — outputs API still serves the BR).

---

## E. Existing decoder-ui functionality that still works

- **Presets**: 17 legacy presets unchanged + 15 new CTS4 (32 total); cached
  rebuild ~170 ms; 2901304 default logic untouched.
- **Legacy decodes byte-exact**: 1902844 → 87 files / 23 cyc / 23 prof /
  27 outputs; 2902222 → 3 / 327-329 (58/59/58 lvls) / 8 outputs — both match
  prior baselines exactly, incl. `active_stage=RTQC`-on-completed quirk parity.
- **Run lifecycle on CTS4 runs**: creation, status, 7 lifecycle events,
  `/cycles/{n}`, `/outputs/{file}`, persistence JSON (400 KB), orphan recovery
  (`-> interrupted` verified for CTS4 runs after each crash), stop endpoint
  (STOPPED + partials on the race test).
- **Batch**: mixed CTS4+legacy batch 2/2, PDF generated, triage `[]`,
  summary email sent (1 real auto-send, recorded).
- **400 contract**: missing-meta (2902130) and missing-group (2902091) refuse
  with the exact missing file; no run created.
- **Frontend**: serves (GET / 200); category strings render as labels; no
  frontend code touched.

---

## F. Failures and their exact layer

### I-0. Masked-QC parse failure — service (mine) — FIXED + re-verified
1. Symptom: first CTS4 run completed with `cycles=0`; log:
   `Error inspecting CTS4 R profile NetCDF …: attributes of masked are not writeable` ×9.
2. Cause: `.tobytes()` on masked (fill-level) S1 QC elements raises
   AttributeError; legacy files never had masked QC tails so legacy never hit it.
3. Layer: **decoder-ui service** (new `cts4_runner.py` parser), not the backend
   (files are correct) and not legacy code (untouched).
4. Fix (service-only, allowed): masked-aware `_qc_char()` — masked levels read
   QC `"9"` (missing), never fabricated good/bad.
5. Verified: re-run 9/9 cycles with real samples; 2902086 15/15.
6. Regression risk: none — new file only; legacy parser untouched.

### I-1. SIGSEGV/SIGBUS on concurrent legacy+CTS4 decodes — service-threading + native lib — REPORTED, not fixed
1. Symptom: two simultaneous `POST /decode` (2902222 + 2902086) kill the server
   process 3/3 (exit 135 SIGBUS once, 139 SIGSEGV twice); in-flight runs lose
   terminal state (orphan recovery marks them `interrupted` on restart).
2. Evidence: faulthandler trace — faulting thread in frozen
   `writer/nc.py:1256 _write_history` (CTS4 `process_float`) while the sibling
   thread was in frozen `nc/admt.py:292 write_admt_dataset` (legacy
   `write_outputs`): **two threads inside concurrent netCDF4/HDF5 writes to
   different files**. Varying signals (SIGBUS/SIGSEGV) at the same overlap =
   textbook non-threadsafe-HDF5 global-state corruption; the pip HDF5 build is
   not compiled threadsafe. Solo runs of both floats are always green;
   sequential batch is unaffected.
3. Counter-tests: parallel legacy+legacy (different floats AND same float
   1902844×2) survived 2/2 — consistent with a racy window (the CTS4 writer
   hammers HDF5 with 21–34 larger files, widening the collision window), not
   with a logic defect in either writer.
4. Layer: **decoder-ui service pre-existing design** (`ThreadPoolExecutor(8)`
   always permitted concurrent decodes; the UI's own flows never overlap) **+
   environment (HDF5 build)**. NOT decoder-backend logic (both writers correct
   serially), NOT CTS4 service logic (no threading decisions added; identical
   crash reachable from legacy-only pairs with unlucky timing).
5. Impact: only concurrent API clients; normal workstation use (single decode,
   sequential batch) can never trigger it.
6. Fix direction (explicitly NOT this phase — would change legacy execution
   behavior): serialize decode execution with a service-side lock, run decodes
   in subprocesses, or ship a threadsafe HDF5 build.

### I-2. Prior-phase commit claim vs tree — process note, no failure
Memory claimed integration committed as `4d94b37`; the tree holds it
uncommitted. Left untouched per freeze; this phase commits decoder-ui only.

---

## G. Whether G2/G3 were actually reproduced

### G2 — REPRODUCED on the real service path (reported, not fixed)
- Service-produced `BR2902086_103.nc`: N_PROF=3, DOXY 0/429, CHLA 0/429 —
  **all BGC sensor values fill** while STATION_PARAMETERS labels prof2 with the
  optode template; N_PROF=4 control (`BR2902086_104`) carries real data.
- Mechanism confirmed against frozen code (read-only): the cycle's o2 stream
  has zero profile-phase records, so the pipeline emits `[primary, near, fl]`;
  the writer's positional template `[r0,r1,r2]` labels the FLBB profile as
  optode and masks every FLBB channel (`pname not in template[i]` →
  `FLOAT_FILL`). A second layout, `[primary, o2, fl]` (near-surface deleted,
  e.g. corpus `BR2902114_017/_033`), masks the o2 profile PRES-only and the
  FLBB profile to the optode template. 6 corpus BRs affected (103, 144, 046,
  050, 017, 033); R-side shows only the minor STATION_PARAMETERS over-claim on
  the shifted ref profile (verified on `R2902114_017/_033`).
- Correction to the earlier hypothesis: `[primary,near,o2]` was predicted to
  survive, and no such file occurred; the observed losses are exactly the two
  predicted-loss layouts. No backend change made.

### G3 — NOT reproduced (trigger absent from the real corpus)
- All 10 staged groups resolve `cals["doxy"] = DoxyCal` (service event for
  2902093 records `DOXY cal: DoxyCal`); the `KeyError`-in-`cals["doxy"]` path
  is never taken, so the `is not None` → `.phase/.foil/.sol` AttributeError
  cannot fire.
- The report's original trigger (03530/03580 unknown FLBB serials) no longer
  exists — both serials are now in the 15-WMO reference (→ 2902130/2902131).
  Those two floats instead stop earlier on genuinely missing GDAC meta.nc
  (missing-data 400, §C). G3 remains a latent landmine only for a future
  group whose serial is absent from the reference AND whose meta.nc is staged.
  No backend change made.

---

## H. What the next UI phase will need for BGC support

1. **N_PROF-aware BR reader (service)**: per-profile grids/QC extraction from
   BR files (optode vs fluorometer profiles, N_PROF 1–4 layouts) — the current
   CycleRecord models N_PROF-1 CTD only; BR files are indexed, not parsed.
2. **BR-only cycle representation**: cycles with BR but no R (103, 144, 046,
   050…) need a cycle-level record or explicit UI treatment (currently 404).
3. **BGC model slots**: service/frontend/PDF fields for DOXY/CHLA/BBP700 series
   + BGC QC + Rtraj BGC MC series; RTQC catalogue extension for tests 57/62/63
   (current catalogue is CTD-only; HISTORY carries no QCP masks — level QCs
   are the source of truth).
4. **G2 backend fix first** (frozen-backend phase, with regression tests on
   N_PROF=3 `[primary,near,fl]` + `[primary,o2,fl]`): no BGC UI should be built
   on BRs that silently fill sensor data. G3 hardening (`isinstance DoxyCal`
   + graceful DATA-COVERAGE) whenever an unreferenced serial appears.
5. **Concurrency guard** (service, touches legacy execution timing — needs
   explicit approval): decode serialization or subprocess isolation per I-1.
6. **Metadata authoring flow** (G4, unchanged): new floats without GDAC meta.nc
   need a hand-authored ExternalMeta path; the service correctly refuses to
   invent it today.
7. **Data growth**: stage raw groups for 2902089/2902090/2902091/2902113/2902120
   and meta.nc for 2902130/2902131 (live GDAC) to unlock the remaining 7 presets.

---

## Verification ledger (all through workstation APIs unless noted)

Single decodes: 2902093 ×2 (+1 pre-fix), 1902844 ×4 (incl. parallel pair),
2902222 ×3 (incl. parallel pairs), 2902086 ×2, 2902115 stop-race ×1,
400-refusals ×
...[truncated 202 chars]