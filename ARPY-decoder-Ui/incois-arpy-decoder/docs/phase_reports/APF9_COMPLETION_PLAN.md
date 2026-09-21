# APF9 Completion Plan

**Date:** 2026-07-28
**Input specification:** `docs/phase_reports/DOCUMENTATION_AUDIT_REPORT.md` (authoritative)
**Baseline at time of writing:** 520 tests pass, `ruff`/`mypy --strict` clean, all four ADMT products generated.
**Status of this document:** Stage 1 deliverable — plan only. **No source code modified yet.**

---

## 0. How this plan was produced

I did not plan from the audit text alone. Before estimating anything I ran a
set of feasibility probes against the raw archive and the GDAC references, so
that every milestone below is backed by a decode I have actually performed.
Three of those probes changed the plan materially, and one **overturned an
audit recommendation**. Those findings are in §2.

---

## 1. Stage 1 — Review of R1–R13

### 1.1 Per-recommendation assessment

Difficulty and risk are 1–5 (5 = hardest / riskiest). "Science risk" means risk
of altering PRES/TEMP/PSAL values, which are currently 1813/1813 bit-identical
and must stay that way.

| R | Objective | Diff. | Tech. risk | Science risk | Impact | Dependencies | Regression requirement |
|---|---|---|---|---|---|---|---|
| **R2** | Firmware-aware `STATUS` bit names (`0x0200`–`0x1000`) | 1 | 1 | **None** | Correctness of internal naming; prevents future misreading | none | Full suite; assert no `_tech.nc` value changes |
| **R7** | Confirm `sp_shift`/`block_shift` correct; document | 1 | 1 | **None** | Locks in a verified result against future "fixes" | none | Full suite unchanged |
| **R6** | Cite D5 p.21 for the `ABP` withholding guard | 1 | 1 | **None** | Turns an empirical guard into a documented one | none | Full suite unchanged |
| **R12** | ARGOS position/CRC statistics in `_tech.nc` | 2 | 2 | None | +8 documented `_tech.nc` params, no telemetry needed | none | `audit_technical_admt` |
| **R3** | 32-bit SBE41 long-word on decoder 1010 | 2 | 2 | None | Correct engineering status; 16 extra documented bits | R2 (shared table) | Byte-level test on all 6 cycles |
| **R9** | Surface raw `TELONICS` byte | 1 | 1 | None | Preserves a field we currently discard | R3 (same parser) | New unit test |
| **R8** | `CP` current pressure → `PRES_Now_dbar` | 2 | 3 | None | +1 `_tech.nc` param | **R5 averaging rule** | Blocked — see §2.3 |
| **R11** | Park statistics + park-end sample → MC 290/296/300 | 3 | 2 | **None** (new MCs only) | **Largest single parity gain** — see §2.1 | none | `audit_trajectory_admt` |
| **R1** | `AET = TST − 10 min`, `AST_float = EPOCH + TPI` | 3 | 4 | **Yes — changes JULD** | Fixes profile `JULD`, ~11 N_CYCLE columns, 5 MCs | R10 (`TPI`) | Full re-audit of all 4 products |
| **R10** | Auxiliary engineering block (`PDIVMAX`,`TPI`,`VAC`,`NPMK`,`PMK*`) | 4 | 3 | None | Unblocks R1; +4 tech params; MC 190 | R11 (msg-3 tail parser) | Trajectory + technical audits |
| **R4** | `PMT` from message 3 on decoder 1010 | 2 | 3 | None | Possibly none — see §2.2 | R11 | Technical audit |
| **R5** | Emit voltage/current/vacuum using published formulas | 3 | **5** | None | 7 withheld params | **Averaging rule (unsolved)** | Must reach 100 % or stay withheld |
| **R13** | Reconcile registry firmware strings | 1 | 1 | None | Documentation hygiene only | none | None (data file) |

### 1.2 Re-prioritisation — where I disagree with the audit's ordering

The audit listed R1, R2, R3, R5 as the four 🔴 items. Having probed the data I
**do not** think that is the right implementation order:

1. **R5 must be demoted, not promoted.** It is the highest-risk item in the set.
   The conversion constants are certain, but §2.3 shows the aggregation rule is
   still unsolved after four further hypotheses were tested and rejected. R5
   stays in Stage 5 and may legitimately never ship.

2. **R11 should be promoted.** The audit filed park statistics as a 🟡
   "recommended enhancement". The probes show it is the **single largest
   verifiable parity gain available**, it is fully documented, it carries no
   science risk, and I have already matched the reference values exactly (§2.1).
   It moves to Stage 3.

3. **R1 must follow R10, not lead.** `AST_float = EPOCH + TPI` needs `TPI`,
   which lives in the auxiliary block (R10). Implementing R1's `AET` half alone
   is possible but leaves the model half-built; better to do R10 → R1 together.

4. **R4 may be a non-issue.** See §2.2 — the reference reports `0`, and our
   current code also produces `0`. Verify before changing anything.

---

## 2. Feasibility findings that changed the plan

### 2.1 R11 is bigger and more certain than the audit implied ✅

The audit noted park statistics exist. The probes establish they are
**decodable now and match the GDAC reference exactly**.

Correct frame convention (the audit did not state this, and my first probe got
it wrong): use `SelectedArgosMessage.matlab_row[1:]`, so **spec byte *n* is
`frame[n−1]`**. Indexing the raw payload directly yields nonsense
(−2611 dbar), which is what made the first attempt look unpromising.

Decoded from message 2, WMO 2902222 cycle 327:

| Field | Spec byte | Decoded | GDAC reference |
|---|---|---|---|
| `PRKN` | 9–10 | 216 | — |
| `TMEAN` | 11–12 | **2.750 °C** | MC 296 `TEMP` = **2.75** ✅ |
| `PMEAN` | 13–14 | **1000.9 dbar** | MC 296 `PRES` = **1000.9** ✅ |
| `SDT` | 15–16 | 0.031 °C | — |
| `SDP` | 17–18 | 3.1 dbar | — |
| `TMIN`/`TMINP` | 19–22 | 2.705 °C / 998.3 dbar | — |
| `TMAX`/`TMAXP` | 23–26 | 2.846 °C / 984.6 dbar | — |
| `PMIN`/`PMAX` | 27–30 | 978.9 / 1007.8 dbar | — |

And from message 3 (decoder 1010), the park-end sample:

| Field | Spec byte | Decoded | GDAC MC 290 |
|---|---|---|---|
| `PRKT` | 6–7 | **2.731 °C** | **2.731** ✅ |
| `PRKS` | 8–9 | 34.548 | **34.548** ✅ |
| `PRKP` | 10–11 | **1004.2 dbar** | **1004.2** ✅ |

**Current state:** we already emit MC 290/296/300 rows but leave every value at
`_FillValue` (verified: `TEMP at MC296: 0 non-fill of 3`). The reference
populates MC 290 and 296. So this is a pure, measurable gain with no risk to
existing science.

### 2.2 R4 is probably a non-issue ⚠️

`TIME_PumpMotor_seconds` in the reference is **0 for all six comparable
cycles**, and our current decode also produces 0. An exhaustive offset scan
found "6/6 exact" at eleven different offsets — a degenerate result caused
entirely by the target being zero. **No offset can be validated against a
constant-zero reference.** Message 3 spec bytes 4–5 give 2318/2325/2312 s,
which is physically plausible for pump run-time but contradicts the reference's
0. I will **not** change `PMT` on the strength of this. Recorded as
*unverifiable with current references*.

### 2.3 R5 remains blocked, and I now have stronger evidence 🔴→⛔

Four further hypotheses for the "store average of decoded values" rule were
tested and **all rejected**: mean-then-convert, convert-then-mean, rounded mean,
ceil/floor of mean, median, last copy, and max copy. On decoder 1010 an
exhaustive single-offset scan over messages 1–3 found **no exact source at all**
for `PRESSURE_AirBladder_COUNT`, `PRESSURE_InternalVacuum_inHg` or
`NUMBER_AirPumpPulsesToInflateBladder_COUNT`.

This is an important negative result: it **independently re-confirms the Phase
6A.4 decision to withhold**, and shows the DAC applies a transformation we
cannot reconstruct from the telemetry we hold. R5 stays blocked.

### 2.4 An audit recommendation is overturned 🔄

The audit (§4.1, R6) recorded, from D3 p.6, that message 3 begins with
`VAC` (internal vacuum). **The data contradict the documentation.** Applying
the documented vacuum formula to message 3 spec byte 3 gives +6.27 inHg where
the reference says −28.009 inHg — physically wrong (a vacuum must be negative
on this scale). But that same byte reads **123, 123, 123, 125** against
reference `PRESSURE_AirBladder_COUNT` of **123, 122, 123, 126** — matching
exactly on 3 of 6 cycles and within ±1 on the rest.

Per General Principle 2 (*real telemetry has priority when documentation is
demonstrably incorrect*), message 3 byte 3 on decoder 1010 is **`ABP`, not
`VAC`**. The residual ±1 is the same unresolved averaging rule as §2.3, so this
does **not** unblock emitting `ABP` for 1010 — but it does explain the Phase
6A.4 mystery ("matches no byte and no constant offset"), and the guard should
be re-documented accordingly.

---

## 3. Milestones

Each milestone is independently shippable, independently regression-tested, and
ordered so that no milestone depends on a later one.

### M1 — Documentation-backed naming and provenance (Stage 2)
**Contains:** R2, R7, R6 (re-documented per §2.4), R13
**Difficulty:** 1 · **Technical risk:** 1 · **Science risk:** none
Firmware-aware `STATUS` bit table (071807 vs 061810/110613 semantics); docstring
citations replacing "inferred" language with D-references; correct the `ABP`
guard comment to state the field is absent from message 1 **and** that message 3
byte 3 is `ABP` but subject to the unresolved averaging rule.
**Acceptance:** every emitted value byte-identical; 520 → ~530 tests.
**Regression:** full suite + all six audits, expecting *zero* changes.

### M2 — Zero-telemetry technical parameters (Stage 2)
**Contains:** R12
**Difficulty:** 2 · **Technical risk:** 2 · **Science risk:** none
Eight ARGOS statistics (`NUMBER_ArgosPositions_COUNT`, per-class counts 0/1/2/3/A/B/Z,
CRC-ok counts) computed from data we already parse (D2 rows 239–249).
**Acceptance:** new params appear; existing 531/531 agreement unchanged.
**Risk note:** these are DAC-convention counts; if our definition cannot be
verified against the reference, emit nothing rather than guess.

### M3 — Message-1 parser corrections (Stage 3)
**Contains:** R3, R9
**Difficulty:** 2 · **Technical risk:** 2 · **Science risk:** none
32-bit SBE41 long-word for 110613/090413 (16-bit retained for 061810);
`TELONICS` raw byte captured, **no bit interpretation invented**.
**Acceptance:** SBE41 word differs only for decoder 1010; `_tech.nc` values unchanged.

### M4 — Park statistics and park-end sample (Stage 3) ★ highest value
**Contains:** R11
**Difficulty:** 3 · **Technical risk:** 2 · **Science risk:** none
Decode message 2 bytes 9–30 (11 statistics) and the message-3 park sample;
populate MC 296 (TMEAN/PMEAN) and MC 290 (PRKT/PRKS/PRKP), which are currently
all-fill. Per-firmware offsets: 1005 park sample at spec bytes 3/5/7; 1010 at 6/8/10.
**Acceptance:** MC 290 and 296 match the reference exactly on all 6 comparable
cycles; profile science untouched (1813/1813).

### M5 — Auxiliary engineering block (Stage 4)
**Contains:** R10
**Difficulty:** 4 · **Technical risk:** 3 · **Science risk:** none
Parse the variable-length tail per D3 p.7: `PDIVMAX`, `TPI`, `VAC`, `NPMK`,
`PMK1..N`. Emit `PRES_MaxDifferencePvsPTorPTSSamples_dbar`,
`CLOCK_AscentInitiationFromDownTimeExpiryOffset_minutes`,
`PRESSURE_InternalVacuumParkEnd_inHg`, `NUMBER_PRESSamplesDuringDescentToPark_COUNT`,
and MC 190 descent marks.
**Risk:** the block only exists when the last message has spare bytes; presence
must be detected, never assumed. If absent in our archive, report that plainly.

### M6 — Timing model (Stage 4)
**Contains:** R1
**Difficulty:** 3 · **Technical risk:** **4** · **Science risk:** **yes (JULD)**
`AET = TST − 10 min`; `AST_float = EPOCH + TPI` (needs M5); `DST` = previous
cycle's `TET`; `PET`/`DDET` per D1. **This is the only milestone that changes an
existing published value**, so it ships alone and last among the implementable set.
**Acceptance:** `AET` reproduces the reference to the second on all 3 verified
cycles; any JULD change is explained cycle-by-cycle before merge.

### M7 — Blocked items: investigate, document, postpone (Stage 5)
**Contains:** R5, R8, R4, clock-drift estimation
**Difficulty:** 5 · **Technical risk:** 5
No implementation. Extend `audit_engineering_decode.py` to record the
averaging-rule search space and its negative results, so the block is
reproducible rather than anecdotal. Clock drift needs ≥33 cycles (D1); we have 3
on the reference-overlapping floats. **Postpone with evidence.**

### Sequencing

```
M1 ──► M2 ──► M3 ──► M4 ──► M5 ──► M6      M7 (parallel, documentation only)
 │      │      │      │      │      │
 └ zero-change ┘      │      └ needs M5 for TPI
        (safe)        └ highest parity gain
```

---

## 4. Regression protocol (applied after every milestone)

```bash
ruff check src tests scripts && ruff format --check src tests scripts
mypy --strict src
pytest -q
python scripts/generate_apex_argos_nc.py
python scripts/audit_mono_profile_admt.py     # expect pass: 11
python scripts/audit_mono_profile_values.py   # expect 1813/1813 bit-identical
python scripts/audit_trajectory_admt.py       # expect structural_parity: 4
python scripts/audit_metadata_admt.py         # expect structural_parity: 4
python scripts/audit_technical_admt.py        # expect 531/531 -> higher
python scripts/audit_engineering_decode.py    # expect 0 unexplained
```

Report per milestone: **changed variables / unchanged variables / improvements /
regressions / remaining differences**. Any unexplained regression halts the
milestone. Mutation testing continues to be used to prove new tests are
load-bearing.

**Invariant for M1–M5:** `audit_mono_profile_values.py` must stay at
**1813/1813 bit-identical**. Only M6 may alter a published value, and only `JULD`.

---

## 5. Expected end state

| Product | Now | After M6 |
|---|---|---|
| `R<wmo>_<CCC>.nc` | pass 11; 1813/1813 | unchanged + corrected `JULD` |
| `<wmo>_Rtraj.nc` | MC 290/296/300 all-fill | MC 290/296 populated & verified; MC 190 where present |
| `<wmo>_meta.nc` | 39/46 fields | unchanged (rest needs test messages) |
| `<wmo>_tech.nc` | 531/531, 7 emitted | + ~13 documented params |

**Limitations that will remain, all telemetry-bound rather than knowledge-bound:**
the multi-copy averaging rule; clock-drift estimation (<33 cycles); `CONFIG_*`
(no test-message files in the archive); DAC-side input differences.

---

## 6. Proposal for this iteration

Per the brief ("begin implementation ONLY with the first milestone after
presenting and justifying the plan"), I propose to implement **M1 only** next.

M1 is the correct starting point because it is provably zero-risk: it changes no
decoded value, so the full audit suite must return byte-identical results. That
makes it a clean test of the regression protocol itself before any milestone
that *can* move numbers.

Two items in this plan warrant your explicit sign-off before I proceed, because
they depart from the audit:

- **R11 promoted** from 🟡 to the highest-value implementable milestone (M4).
- **R5 demoted** from 🔴 to postponed-with-evidence (M7), on the strength of the
  negative results in §2.3.

And one correction for the record: the audit's reading of message 3 byte 3 as
`VAC` is **wrong for decoder 1010** (§2.4); it is `ABP`. The audit report is
otherwise unamended.
