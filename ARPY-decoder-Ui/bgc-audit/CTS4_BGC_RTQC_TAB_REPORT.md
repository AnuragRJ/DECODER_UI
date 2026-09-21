# CTS4 BGC RTQC tab + G2 design — continuation report (2026-09-16)

Commit: `1cb3526` in `/home/user/incois-arpy-decoder`. Server left running
on :8000 with the rebuilt frontend. All approval-free BGC work is now
complete; the only remaining items are the approval-gated ones (§E).

## A. RTQC modal BGC reference tab (done)

Read-only inspection of the frozen backend found the 301 pipeline DOES run
real BGC RTQC (`rtqc/cts4.py`, wired via `writer/nc.py:1397`): test 57 on
DOXY (raw→QC3 by construction, storage drift), test 62 on BBP700 (five
sub-tests), test 63 on CHLA (raw→QC3), plus common 6/9/11/12/13 on BGC
channels. The modal is a static reference ("ACTIVE IN PIPELINE" + source
pointers), so documenting these tests is honest — with one boundary kept:

- Added `PASS BGC` tab with TEST057/062/063 entries (real rules, real
  thresholds, real `ctqc/cts4.py::_run_*` pointers), `RtqcPass` union
  extended (sole consumer is the modal), header now `TABLE 11 + BGC QC`.
- NO per-run BGC test status: `_build_rtqc_levels` keeps only level flags
  and discards `tests_done`/`tests_failed` at the writer boundary, so
  per-test execution evidence does not exist in 301 files. The missing
  dependency for per-run status is a writer change (publish test numbers,
  e.g. HISTORY QCP/QCF) — a `src/` change, gated. Reported, not built.

## B. G2 fix design (analysis only, no `src/` changes)

`bgc-audit/G2_FIX_DESIGN.md` code-locates the mechanism: positional
`BGC_STATION_PARAMETERS_TEMPLATE` rows + `if pname not in template[i]`
masking in `writer/nc.py` mislabels and wipes profile 2 whenever the
profile order deviates from the 4-row assumption (cycle 103:
[primary,near,FL] vs [PRES,PRES,DOXY-row]). Specifies the fix
(measured-presence keying) with byte-parity acceptance criteria. G3 has no
reproducing case and is explicitly NOT bundled.

## C. E2E verification ledger

| Check | Result |
|---|---|
| Forced batch `batch-1789556908-12b3` | 2/2: 2902086 16/15/1/34, 1902844 23/23/0/27, email sent, PDF 26,850 B |
| 301 run payload | 16 cycles; C103 BR-only + G2; C99 full BGC + 141 CTD |
| PDF text | BGC findings + sensor-absent + N_PROF present |
| `tsc` + build | Clean; bundle has PASS BGC / TEST057/062/063 / header |
| Restore recovery | 3rd snapshot drop (commit + :8000 + dist + pip + recent history); tree + staged data intact, all markers re-audited OK before + after |

## D. Audited and deliberately deferred

`GET /api/runs` is 16 MB over 734 runs — a PRE-EXISTING condition from
embedded CTD samples (zero BGC runs in the restored history), fetched only
on app init / batch-complete / stop (0.14 s locally). BGC adds ~1.5 MB per
301 run, proportional, not a new class of problem. Restructuring (light
mode + hydration) touches shared paths for little current gain — not done.

## E. What remains (all gated — approval requested)

1. **G2 backend fix** per `G2_FIX_DESIGN.md` (§4 acceptance incl.
   byte-parity + full E2E re-run). Touches `src/argo_decoder/writer/` only.
2. **Concurrency guard** (serialize `/decode` — the HDF5 crash fix; legacy
   single-run behavior unchanged, only concurrent load affected).
3. Per-run BGC test status — blocked on a writer change (see §A); part of
   the `src/` conversation, not separable.
