# ARVOR-I Phase 2 — Packet-Grouping & Cycle Reconstruction

**Date:** 2026-08-24 · **Scope:** structured packets → session grouping → per-cycle
decoding buffers → completion/delayed/deep/GO classification → ordered
reconstructed cycles. **Status:** COMPLETE (validation targets met; regression
1850/1850, ruff clean).

Deliverable: `src/argo_decoder/platforms/provor_ir_sbd/arvor_i_cycles.py`
(+ 35 unit tests `tests/unit/test_arvor_i_cycles.py`, 15 integration tests
`tests/integration/test_arvor_i_cycle_reconstruction.py`).  No Phase-1 file
was modified; APF9 and CTS4/221 paths untouched.

---

## 0. Boundary

Phase 2 stops at buffer classification. **Not done (Phase-3 boundary):**
NetCDF writers, GDAC parity, mission-parameter semantics, full Param#1/2
interpretation, unobserved packet types (7–14 decoders), trajectory
generation, profile-date finalization.  Missing telemetry remains a
DATA/COVERAGE limitation — nothing is inferred or back-filled.

## 1. MATLAB call chain (PROVEN — vendored under `tests/data/arvor_i/coriolis_src/`)

```
decode_provor_iridium_sbd_delayed.m          (sub/)  delayed-mode driver
  └─ get_list_files_info_ir_sbd.m            (sub/)  mail list, **chronologically
             │                                       sorted by session date** (L86–88)
  └─ decode_prv_data / decode_prv_data_provor … (Phase-1 ported equivalents)
  └─ create_decoding_buffers.m               dispatcher: {222,223,225,232} →
      └─ create_decoding_buffers_222_223_225_232.m   (1837 lines, J.-P. Rannou,
                                                      created 04/02/2025)
            └─ local check_buffer(...)  completion test per buffer
```

Mail ordering: the driver iterates files sorted by the **mail-file timestamp**
(transport time), i.e. session/e-mail time, **not** float time.  The Python
port sorts the packet stream by `(session_time_utc, MOMSN, row_index)`
— same ordering evidence, and it keeps transport metadata separate from
float data (email timestamps ≠ float timestamps).

`g_decArgo_processRemainingBuffers` (driver config) toggles the go=2
emission path; the port exposes it as `process_remaining_buffers=False`
(default, Coriolis conservative behaviour).

## 2. Algorithm as ported (every rule = MATLAB line evidence)

| # | Rule (MATLAB evidence) | Port |
|---|---|---|
| R1 | **Pre-launch override**: any packet whose session date < LAUNCH_DATE gets `cyNumRaw=−1` (decode_prv_data); **pre-launch deletion** (buffer file L50–64): if any *post-launch* type-5/7 with cyNum==0 exists → delete ALL −1 packets; else keep the **last** type-5 and last type-7 among them, delete the rest | `build_packet_stream` flags `pre_launch`; `reconstruct_stream` implements both branches; discarded/kept lists on the result |
| R2 | **Reset handling** (L94+): rising `lastReset` across type-4s → `tabCyNum(firstPack:end) = tabCyNumRaw + max(prior cycles)+1` (re-based from **raw**, non-accumulating); warning if first post-reset cycle ≠ 0 | rising-reset detection; `ResetEvent` recorded (offset may be 0 → informational) |
| R3 | **Session numbering** (L155+): sessions seeded at type 0/4/5; new session when a later packet is (a) type 0/4/5 with **higher cycle AND later date**, or (b) **type-0, same cycle, later date** | `_segment_sessions` |
| R4 | **0.5-day split** (L186+): inter-packet gap > 0.5 d within a session splits it (reason `0.5-day-split`) | same |
| R5 | **10-minute merge** (L168+): a session-starting base packet < 10 min after the previous packet **whose cycle differs** merges back (reason `merged-10-min`). This is exactly the dead-float final-burst pattern | same |
| R6 | **EOL split** (L199–206): every EOL-flagged packet adjacent to its predecessor starts a new session — note: **consecutive EOL packets split repeatedly** (as-coded) | same; `eol-split` reason |
| R7 | **Deep-session numbering** (L225+): `tabSessionDeep` = session numbers, shifted −1 from the first packet of every session **without** measurement packets (types 1/2/3/8/9/10/11/13) | same |
| R8 | **Main loop** (L243–293): per session, the **first packet's cycle** forms `idForCheck`; same-cycle packets in strictly later sessions are appended, **truncated before the first 0/4/5 among them** (delayed=2); completed → rank, go=1; else if `max(tabSessionDeep) − min(deep# of buffer) ≥ NB_SESSION_MAX−1 = 2` → forced emission (go=1, completed=0); else pending (done=1, go=0; go=2 only with processRemainingBuffers — delayed stays = local value 0/2) | `reconstruct_stream` main loop |
| R9 | **Remaining loop** (L295–365): leftover (session, cycle) pairs (merged-burst extras) → delayed=1 (`tabIceDelayed`), completed re-checked, same forcing, go=2 path sets delayed=1 | remaining loop |
| R10 | **EOL retransmission dedup** (L368–390): if the *nominal* transmission of an EOL cycle was completed → the EOL buffer's non-{0,4,5,7} packets get rank −1 (dropped), deep cleared | ported; dropped packets retained on the result with reason — **never silently discarded** |
| R11 | **EOL param duplication** (L392–403): within a rank held by EOL packets (unique(tabRank(idEol)), **including −1** as-coded), keep only the **last** type-5 / type-7 | ported as-coded |
| R12 | **Second Iridium session split** (L405+): a buffer mixing `irSession` 0 and 1 packets is split; second-session part (+ trailing type-5/7) gets a new rank; first part forced deep; go=1 | ported; note: a T1/T2 of a later session can never be appended into an earlier buffer (the R8 cut stops at any 0/4/5), so the mix arises only from second attempts **inside one session** — trigger UNOBSERVED in our data (all irSession=0) |
| R13 | **rankByCycle** (L1349–1365): final renumbering — cycle ascending, original rank order within cycle; `tabCompleted` **re-evaluated per emitted buffer** via check_buffer | same; `buffer_id` = rankByCycle number |

**Emission semantics:** `go` = 0 pending / 1 emitted / 2 emitted only because
processRemainingBuffers; `delayed` = 0 nominal / 1 leftover (session, cycle)
("ice delayed") / 2 same-cycle data appended from later sessions;
`deep` = buffer contains measurement packets.

## 3. Completion logic and expected-count interpretation

`check_buffer` (L1595–1723) as ported:

1. Exactly one Tech#1 (type 0) and one Tech#2 (type 4); **Prog#1 (type 5) is
   waived for the 222/223/225/232 family** (MATLAB forces `idPackProg = -1`,
   which MATLAB treats as "present"). Multiples → not completed, why stays
   empty (diagnostics only printed).
2. All three expected counts zero → **surface cycle** → completed.
3. Otherwise completed iff `received ≥ expected` for descent {1,8}, drift
   {2,9}, ascent {3,10}; any measurement packet → deep. Why-strings
   (`"N descending/drift/ascending data packets are MISSING/NOT EXPECTED"`,
   `"Tech1/Tech2 packet is missing"`) match MATLAB verbatim and are emitted
   only when incomplete.

**Expected-count mapping — explicit statement (as required).** The primary
`completed` flag uses the **corrected** mapping: Tech#2 items **3/4/5 =
expected descent/drift/ascent** counts (manual 33-16-033 Rev14 §6.3, agreeing
with raw telemetry; Phase-1 finding). The Coriolis code reads items **4/5/6**
(off-by-one). Both are computed per buffer:

- `expected_counts` / `completed` — corrected (authoritative);
- `expected_counts_coriolis_as_coded` / `completed_coriolis_as_coded` —
  Coriolis-as-coded reading, exposed for parity, **not** used for anything.

As-coded consequences on the evidence floats (PROVEN in tests): cycle-1
expects (1,7,0) instead of (4,1,7), cycles 2+ expect (2,7,0) instead of
(0,2,7); with zero descent packets ever received, **as-coded completion is
unreachable for every deep cycle of both floats** — which contradicts the
observed operator/GDAC output where these cycles are complete. This is the
dated Phase-1 correction, kept visible rather than re-introduced.

## 4. Data model (no-loss guarantees)

- `StreamPacket` — packet + message + `row_index` + transport `date`
  (+ `pre_launch` flag). `cycle_raw` = effective cycle (−1 pre-launch or
  unsupported type), `ir_session`/`eol_flag` default 0 (only Tech#1 carries
  EOL; only Tech#1/2 carry the session indicator — PROVEN from layouts).
- `BufferResult` — `buffer_id` (rankByCycle), `cycle_number`, packets,
  `session_ids`, original `rank`, `delayed`/`ice_delayed`, `deep`, `go`,
  `completed` (+ as-coded twin), expected/received counts (desc, drift, asc),
  `why_incomplete`.
- `CycleReconstructionResult` — ordered buffers, `sessions` (with split
  reasons), `resets`, `pre_launch_discarded`, `kept_pre_launch_param_packets`,
  `dropped_packets` (with reasons), `unranked_packets` (pending).
- **Conservation invariant** (tested on both floats): every stream packet
  appears exactly once across buffers + unranked + discarded + kept-params +
  dropped.

## 5. Validation on the raw datasets

### 5.1 6990711 (dead float; launch 2025-03-02 05:16Z) — TARGET MET

- 95 packets → **5 sessions** → **7 logical cycles, ALL complete**, go=1,
  deep; cycle 1 (4,1,7) received exactly; cycles 2–7 (0,2,7) exact.
- No EOL flags, no pre-launch packets, no resets, nothing dropped/pending.
- **Final burst (2025-05-01/02) order 7→5→6 explained:** the float surfaced
  dead and transmitted the current cycle 7 first, then buffered cycles 5/6
  minutes later. All three arrive < 10 min apart with cycle changes between
  base packets → the 10-minute merge (R5) keeps them in **one session**; the
  main loop takes the session's first cycle (7, delayed=0); cycles 5/6 are
  leftover (session, cycle) pairs → remaining loop → **delayed=1**. Original
  ranks 5<6<7 for cycles 7<5<6 preserve transmission order; `rankByCycle`
  still emits buffers in cycle order 1…7.
- As-coded completion: False on all 7 (unreachable, §3).

### 5.2 7902408 (active float; launch 2026-03-25 17:44Z) — TARGET MET

- 184 packets → **16 sessions** → 14 buffers + 2 pending cycles.
- **Pre-launch:** factory tests 2025-09-19 (MOMSN 32/34/36, 9 packets) and
  the four launch-day deck-test sessions (MOMSN 38/40/42/44, all before
  17:44Z, 12 packets) are pre-launch → deleted, **keeping only the last
  type-5 (MOMSN 44, 12:08:30Z)**; it forms a forced-incomplete cycle −1
  buffer (Tech#1/Tech#2 missing). *Note:* earlier notes placing MOMSN 38–44
  post-launch were wrong — their e-mail dates (03:57–12:08Z on 2026-03-25)
  precede the 17:44Z launch; no post-launch cycle-0 parameter packet exists,
  which is what triggers keep-last. (Session-memory correction, dated.)
- **Completion pattern exactly as mandated:** complete {1,4,9,12}; incomplete
  {2,3,5,6,7,8,10,11} with received counts matching the MOMSN-gap analysis
  (e.g. cycle 8 = (0,2,2), truncated at 1263 dbar even in operator data;
  cycle 11 = (0,2,4)); cycle 13 force-emitted incomplete (two later deep
  sessions) with *Tech1+Tech2 missing*; **cycles 14/15 pending (go=0)** —
  metadata-less transmissions whose first sessions (MOMSN 118–125/128–131)
  were never received — DATA/COVERAGE, packets retained in
  `unranked_packets`. With `process_remaining_buffers=True` they emit as
  go=2, delayed=0 (main-loop branch keeps the local delayed).
- Sessions 14–16 (cycles 13–15) exist only via the 0.5-day split (no base
  packets) — reason recorded.

### 5.3 Disagreement ledger (Py / MATLAB / manual / raw)

| Item | Python | Coriolis as-coded | Manual | Raw | Class |
|---|---|---|---|---|---|
| Expected counts mapping | items 3/4/5 (primary) | items 4/5/6 | 3/4/5 (§6.3) | 3/4/5 (counts match received) | PROVEN (Coriolis off-by-one, dated correction) |
| 6990711 cycles 1–7 complete | yes | no (unreachable) | yes | yes | PROVEN |
| 7902408 complete set | {1,4,9,12} (+c−1 param buffer incomplete) | would differ per above | {1,4,9,12} | matches received counts | PROVEN |
| Cycle 13 emission | forced incomplete | same rule | — (gap) | no Tech packets | PROVEN (rule) |
| Cycles 14/15 | pending, retained | go=0 (or go=2 config) | — (gap) | no Tech packets | PROVEN (rule), DATA/COVERAGE |
| irSession-split trigger | ported, inert (all 0) | fires for some fleet floats | — | all 0 | UNKNOWN (trigger unobserved) |

No four-way disagreement arose → no STOP condition.

## 6. Evidence classes

- **PROVEN:** mail-date ordering (get_list_files_info L86–88); pre-launch rule
  (buffer file L50–64 + decode_prv_data date check); session rules R3–R7
  (line-pinned); main/remaining loops incl. delayed-append cut and forcing
  (L243–365); check_buffer incl. Prog waiver and why-strings (L1595–1723);
  EOL dedup/param rules (L368–403); irSession split (L405+); rankByCycle +
  final completed re-evaluation (L1349–1365); both validation outcomes.
- **INFERRED:** `iridium_session` defaults 0 for packets that do not carry
  the field (MATLAB init-struct default; consistent with inert rule);
  launch dates from operator metadata (investigation §launch row) feeding
  R1 exactly as Coriolis would take LAUNCH_DATE from fleet metadata.
- **UNKNOWN:** real-world trigger of R12 (second-attempt-in-one-session mix);
  behaviour for packet types 7–14 (out of scope); why the float transmitted
  cycle 7 before 5/6 (hardware-state explanation beyond telemetry).

## 7. Deferred (Phase-3 boundary)

NetCDF writers (_prof/_tech/_Rtraj/_meta), GDAC parity (including
`g_decArgo_processRemainingBuffers` operational setting), mission-parameter
semantics / Param#1&2, unobserved packet types 7–14, trajectory generation,
profile-date finalization.  MOMSN-gap→missing-email mapping stays report-level
(Phase-1 tests already pin the gap lists).

## 8. Regression

- Before Phase 2: 1799 passed, ruff clean (Phase-1 report).
- After Phase 2: **1850 passed** (35 unit + 15 integration new; +1 count
  discrepancy vs arithmetic identical in sign to the Phase-1 +58-vs-57 quirk —
  stable and green, not chased), `ruff check` + `ruff format` clean.
- Phase-1 decoding untouched (`arvor_i.py` unmodified; all Phase-1 tests
  unchanged and passing); APF9 and CTS4/221 untouched; no test weakened or
  deleted.

---

## Addendum (2026-08-27, later same project): `process_remaining_buffers`
default flipped to `True`

Per the directive following
`ARVOR_I_REMAINING_BUFFERS_DECISION_2026-08-27.md` (§5 guardrails):

* **Change (smallest generic, no WMO branches):** the three public
  signatures in `src/argo_decoder/platforms/provor_ir_sbd/arvor_i_cycles.py`
  (`reconstruct_cycles`, `reconstruct_stream`,
  `reconstruct_from_directory`) now default
  `process_remaining_buffers: bool = True`, matching Coriolis
  `decode_provor_2_nc.m` L45–46 / `decode_provor_2_dm.m` L52–53
  (`create_decoding_buffers` L278–296), which process remaining buffers
  unconditionally.  Rationale docstring added at `reconstruct_cycles`.
  The legacy `config/models.py` `OutputFlags.process_remaining_buffers`
  field is untouched (unused by this chain; grep-verified no other
  consumers).  `False` remains explicitly requestable (pinned by tests).
* **Effect (PROVEN, product-level):** 7902408 trailing-buffer cycles 14/15
  — previously unranked ("mail-only" stubs, `GROUNDED='U'`) because the
  mail stream never sets the flag — now rank as trailing buffers with
  `go=2, completed=0` and emit incomplete cycles carrying hydraulic
  (MC290/590) and GPS (MC703) data.  The old "mail-only U" status label
  is **retired**; reclassified as trailing-buffer `go=2, completed=0`
  per the decision report.  6990711 has no trailing buffers: zero
  behavioral change (product identity verified in the 4A/4B addenda).
* **Tests:** exactly the 8 genuinely-changed expectations updated
  (`test_arvor_i_cycles.py` ×4, integration cycle/science/tech/rtraj
  ×4; the True-semantics unit test already existed and passes
  unchanged); none weakened or deleted; legacy-`False` behavior still
  pinned.  Full suite **1991 passed** (== pre-change baseline count);
  `ruff check` + `ruff format` clean on all changed files.
