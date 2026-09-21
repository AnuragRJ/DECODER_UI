# `process_remaining_buffers` — Decision Report (pre-mono-profile)

**Date:** 2026-08-27 · READ-ONLY investigation, no code modified · **STOP after this report**
**Question:** architecture for the ARVOR-I reconstruction default — (1) global `True`, (2) explicit
output-mode setting, (3) retain `False` + classify. Evidence below is labelled
PROVEN / INFERRED / UNKNOWN and attributed (Coriolis-chain / GDAC-publication / raw-telemetry / our-chain).

## 1. Coriolis production setting — traced (PROVEN, vendored source)

- `decode_provor_2_nc.m` L45–46 **and** `decode_provor_2_nc_dm.m` L52–53 both hard-set
  `g_decArgo_processRemainingBuffers = 1` — real-time **and** delayed-mode production drivers alike.
- `init_config_values.m` contains **no** occurrence → there is no config-file default or user knob.
  It is a production constant, not a mode. (PROVEN, grep over the full vendored set.)
- `decode_provor_iridium_sbd.m` L774: remaining buffers are processed when the **last spool file**
  is reached and the flag is set (end-of-data trigger).
- `create_decoding_buffers_222_223_225_232.m` L278–296 (general branch): a trailing buffer with
  session spread < 3 gets `rank` (→ becomes an output cycle), `tabCompleted = 0`, `tabGo = 2`,
  and `tabDelayed` **keeps its computed value**. The `delayed = 1` variant (L347–358) sits inside the
  float-6903800 special-case block → not applicable to our floats. (PROVEN structure; our empirical
  `delayed = 0` for c14/c15 matches the general branch.)
- `go`/`completed` feed `is_buffer_completed_ir_sbd` (file not vendored; UNKNOWN internals) → the
  timing chain falls back for incomplete buffers; empirically c14/c15 (no Tech#1) take first-mail
  dates and mail-weighted locations — exactly the GDAC mono-profile convention. (PROVEN effect,
  INFERRED mechanism link.)
- All product emitters (tech/traj/prof) consume the **same** ranked buffer stream — the flag is not
  and cannot be per-product. (PROVEN, `decode_provor.m` flow.)

## 2. How 7902408 cycles 13–15 are emitted

| Cycle | Coriolis/production (evidence) | Our chain `False` | Our chain `True` (in-memory, no writes) |
|---|---|---|---|
| 13 | normal buffer (closed by c14-tagged packets; no Tech#1) → prof `_013` 30 lev; GDAC tech c13 = 22 all-fill placeholder rows | emitted: 19 Rtraj rows, tech rows, 30-lev profile == `_013` | **identical** to `False` (verified field-level) |
| 14 | trailing buffer, `go=2, completed=0` → prof `_014` 15 lev 1687.8–2028.7; GDAC tech c14 = all-fill placeholder rows present | **dropped**: unranked (go==0), 6 packets; Rtraj mail-only rows 702/704 ('U' semantics) | emitted: `delayed=0, go=2, completed=False, deep=True`; profile 15 lev 1687.8–2028.7 **== GDAC `_014` EXACT**; first-mail date; IRIDIUM mail-weighted location (== GDAC conventions) |
| 15 | trailing buffer → prof `_015` 73 lev 0.1–1287.8; GDAC tech c15 = placeholder rows | **dropped**: 8 packets; mail-only 702/704 | emitted: deep 67 lev 5.8–1287.8 + shallow 6 lev 0.1–4.7 = 73 lev 0.1–1287.8 **== GDAC `_015` EXACT**; same date/loc conventions |

GDAC tech corroboration (PROVEN): cycles 0–16 present; 13/14/15 are 22-row **all-fill** placeholder
entries (no Tech packets); cycle **16** carries full values (2026-08-21 surfacing — beyond our raw
snapshot, last mail 2026-08-11). Production emitted trailing cycles into tech as fill placeholders —
consistent with `go=2` semantics, not with dropping them.

## 3. Blast radius of enabling `True` (PROVEN, in-memory diff; `False` reproduces shipped 4B exactly)

- **6990711: ZERO change.** No trailing open buffers (0 unranked packets); buffers 1–7, science,
  tech (566 rows, 0 diffs), Rtraj (363 rows) identical in both modes.
- **7902408 shared cycles 1–13: identical** (science fields, profiles, Rtraj rows) with one ledgered
  exception: tech aux re-attribution — the cycle-13 `ParameterMessage2Received` count row moves to
  cycle 15 (trailing packets re-ranked into their own buffer): **−1 row @c13, +Param1/Param2 count
  rows @c14/c15**.
- **`_tech.nc` (4A product): 986 → 1012 rows** (+26 net): +13/+14 `TECH_AUX_*` flag/count rows for
  c14/c15 (incl. `TransmissionCompleted`, `TransmissionDelayed`, per-type packet counts — real
  bookkeeping values from the buffer). GDAC tech cannot row-compare here (legacy 22-name table,
  4A-classified).
- **`_Rtraj.nc` (4B product): 824 → 891 rows** (+67): c14 2→34, c15 2→37. The mail-only '702/704
  U' rows are replaced by full cycles (skeleton 89…800, drift 290×17/×15, deepest-bin 503, profile
  590×1/×5, RPP 301, mail-loc 703×2/×3). GDAC Rtraj is stale at 6 cycles → **row-level parity for
  c14/c15 is UNKNOWN (no reference)**; the mechanism is the already-validated 4B emitter running on
  newly ranked buffers (PROVEN mechanism, UNKNOWN reference parity).
- Phase-3 science semantics for pre-existing cycles: **unchanged** (verified field-level).

## 4. Options

1. **Global `True`** — exact production parity (§1); recovers c14/c15 with exact GDAC prof parity
   (§2); no effect when no trailing buffers exist (§3, 6990711); honors "nothing silently
   discarded" (today 14 raw packets are unranked). Cost: regenerates two validated 7902408 products
   (tech +26/−1; Rtraj +67) → needs a separately directed change with re-validation, transparent
   test-expectation updates, and report addenda. 4B's "c14/15 mail-only" classification becomes
   "c14/15 trailing-buffer cycles (go=2)" — a correction of our earlier classification, not a GDAC
   discrepancy.
2. **Explicit output-mode setting** — the MATLAB has no per-product mode (§1); a prof-True /
   traj-tech-False hybrid would match neither Coriolis nor GDAC (GDAC tech **has** c13–15 rows;
   prof has `_013–015`). As API surface the knob already exists
   (`reconstruct_cycles(process_remaining_buffers=…)` injectable via `reconstruct_science(cycles_result=…)`),
   so "option 2" adds nothing except keeping a default that is wrong for production parity.
   REJECTED on evidence; the only open question is the default.
3. **Retain `False` + classify** — zero churn, but a **self-inflicted DATA-COVERAGE gap**: the raw
   data exists, production publishes it (prof exact levels, tech placeholder rows), and the upcoming
   mono-profile phase could not reproduce `_014`/`_015` at all. Contradicts the no-silent-discard
   standing rule. REJECTED.

## 5. Recommendation

**Option 1: make `process_remaining_buffers=True` the global ARVOR reconstruction default** — it is
the Coriolis production constant (both RT and DM drivers), it is product-agnostic by construction,
its effect is exactly bounded (§3), and it is *required* for mono-profile `_014`/`_015` parity.

Execution guardrails (for a future directive — NOT done now):
1. One-line default change + full-suite run; transparently update the affected test expectations
   (7902408 counts only; no weakened assertions — expectations change because behaviour changes).
2. Regenerate 4A/4B products for 7902408 (tech 1012 rows; Rtraj 891 rows; 6990711 products must stay
   byte-identical — that identity is itself a check), re-run both validation scripts, append report
   addenda reclassifying "c14/15 mail-only 'U'" as trailing-buffer cycles (`go=2`, `completed=0`).
3. Then implement the mono-profile adapter on the corrected baseline.

**STOP — no implementation performed or started.**
