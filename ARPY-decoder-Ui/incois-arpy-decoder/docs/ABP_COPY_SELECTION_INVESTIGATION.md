# ABP copy-selection re-analysis — `PRESSURE_AirBladder_COUNT` on decoder 1010

> **CORRECTION (2026-08-18).** The rule-sweep tables in §D of this report
> were produced by an ad-hoc analysis script that had two defects (wrong
> group-seeding index — the spurious "ABP=9/10/12" values were PMT high
> bytes — and a grouping key that included the CRC byte). The per-copy
> distributions in §C are unaffected (they match the project parser
> exactly), but **the aggregation numbers in §D are superseded** by
> `docs/ABP_EXACT_CORIOLIS_VERIFICATION.md`, which re-runs everything with
> the project's trusted parser and the faithful Coriolis-equivalent
> algorithm. Authoritative result: **exact Coriolis `round(mean)` matches
> GDAC 6/12; current Python 8/12**. The exact Coriolis rule differs from
> the current Python output on **exactly two cells** (2902203/361,
> 2902206/360 — both currently match GDAC), so adopting it would change
> two currently-correct cells and reduce parity from 8/12 to 6/12 (net
> regression of 2). **NOT FIXABLE — no code change; the exact INCOIS
> aggregation algorithm has not been established.**

**Issue:** 4 of 12 GDAC-comparable `PRESSURE_AirBladder_COUNT` cells differ
from our Python output by exactly ±1 count (2902206 cyc361; 2902222 cyc328
and cyc329; 2902223 cyc329).

**Date:** 2026-08-17 · **Type:** investigation only — no source, test, or
configuration file modified.

**Primary raw-telemetry evidence:** the operator-provided bundle
(Drive `1NQRBUJnn-umHevX-VMMKPP2zk0Tei7oF`, 7-zip, 407 entries) — full raw
telemetry for all ten APF9 floats (`075415`=2901350 and `102526`=2901305
were previously missing from the workspace) plus the four metadata CSVs.
The five 1010 PTT directories are byte-identical (md5) to the workspace
copies; the bundle's copies were used for every measurement below.
**Nothing in the bundle was modified.**

---

## A. What the parameter is — specification evidence

- **APF9A 110613 manual** p.25 ("Data Message 3 – N"): spec bytes
  `0 CRC, 1 MSG, 2 VAC, 3 ABP, 4–5 PMT` → **ABP = payload byte 1**.
  Same table in the **090413 manual** p.25.
- **Manual wording — the crucial line:** ABP = *"The air bladder pressure
  [counts] recorded just after each argos transmission."* I.e. the float
  **re-samples ABP for every transmission** — copies of Message 3 within
  one pass legitimately carry different ABP values. (Compare VAC, which is
  sampled once per park phase and is identical in every copy.)
- **ApexCoDecoder** `110613_090413` row 193: spec byte 04 → `ABP`, techId
  **1022**, annotation **"store average of decoded values"** — the
  spreadsheet documents an averaging rule for this parameter.
- **ApexCoDecoder** row 192: VAC (techId 1021) carries **no** averaging
  annotation — consistent with VAC being constant across copies.

## B. Coriolis implementation — the exact rule (GitHub `main`, fetched 2026-08-17)

Chain of three files:

1. **`get_bytes_to_freeze.m`**, decoder 1010: `dataMsgBytesToFreeze{3,2} =
   [4]` — for Message 3 the frozen frame byte is **column 4 (1-based) =
   ABP**. Frozen bytes are zeroed before redundancy grouping, i.e. copies
   are grouped *ignoring their ABP value*.
2. **`get_apex_data_sensor.m`**: for each message number, only **CRC-valid**
   copies are kept; they are grouped by payload with frozen bytes zeroed;
   the **most redundant** group is selected (occurrence-weighted; ties →
   earliest first-seen). For Message 3, since every copy is identical
   except CRC and ABP, all CRC-valid copies fall into **one** group.
3. **`decode_data_apx_10.m`** (techId 1022):
   ```matlab
   tabBladPres = [];
   for id = 1:length(idListFB)
      tabBladPres(end+1) = decDataBis(id, 2);   % ABP of each used copy
   end
   dataStruct.value = num2str(round(mean(tabBladPres)));
   ```
   → **`PRESSURE_AirBladder_COUNT` = round(mean(ABP over all CRC-valid
   Message-3 copies of the cycle, occurrence-weighted))**.

So the documented, source-confirmed Coriolis rule is **not** modal and
**not** single-copy: it is the occurrence-weighted mean rounded to the
nearest integer over the CRC-valid copies.

## C. Copy-level evidence from the operator bundle (12 GDAC-comparable cycles)

For every cycle: all Message-3 copies parsed from the bundle, CRC-checked
(WRC), ABP = payload byte 1. In every cycle the copies differ **only** in
the CRC byte and the ABP byte (verified frame-by-frame — e.g. 2902223
cyc329: three distinct frames differing at indices 0 and 3 only).

| float | cyc | CRC-ok copies | ABP distribution (counts) | GDAC |
|---|---|---|---|---|
| 2902203 | 359 | 8 | 122×2, **123×6** | 123 |
| 2902203 | 360 | 31 | 122×1, **123×22**, 124×8 | 123 |
| 2902203 | 361 | 17 | **121×6**, 122×5, 123×6 | 121 |
| 2902206 | 359 | 22 | **122×14**, 123×7, 125×1 | 122 |
| 2902206 | 360 | 16 | **121×8**, 123×8 | 121 |
| 2902206 | 361 | 2 | 121×1, 122×1 | 121 |
| 2902222 | 327 | 8 | **123×7**, 124×1 | 123 |
| 2902222 | 328 | 81 | 96×1, 122×8, **123×40**, 124×32 | 122 |
| 2902222 | 329 | 69 | 96×6, 121×7, 122×7, **123×42**, 125×7 | 122 |
| 2902223 | 327 | 10 | 122×2, **123×6**, 124×2 | 123 |
| 2902223 | 328 | 41 | 96×1, 122×8, **123×24**, 124×8 | 123 |
| 2902223 | 329 | 24 | 123×6, **125×12**, 126×6 | 126 |

(bold = modal value; occurrence counts are 1 per row in these files, so
row weighting = occurrence weighting.)

## D. Rule sweep — which aggregation reproduces GDAC? (answer: none)

Each candidate rule evaluated over our copy set on the 12 cells:

| rule | matches GDAC |
|---|---|
| **mode, tie → lowest** | **9/12** |
| **current Python** (most-redundant identical-frame copy, tie → earliest reception) | **8/12** |
| median (CRC-valid) | 7/12 |
| last CRC-valid copy | 7/12 |
| **Coriolis `round(mean)` over CRC-valid copies (occurrence-weighted)** | **5/12** |
| round-mean, unweighted | 5/12 |
| round-mean over ALL copies incl. CRC-bad | 4/12 |

The current Python value per cell (from a fresh decode with the current
code): 2902203 359/360/361 ✓✓✓; 2902206 359/360 ✓, 361 ✗ (122 vs 121);
2902222 327 ✓, 328 ✗ (123 vs 122), 329 ✗ (123 vs 122); 2902223 327/328 ✓,
329 ✗ (125 vs 126) → **8/12**.

**Key results:**
1. **No rule over our copy set reproduces GDAC on all 12 cells.** The four
   disputed GDAC values (121, 122, 122, 126) are *real transmitted values*
   present in our copy set, but always as **minorities** (1/2, 8/81, 7/69,
   6/24) — no mode/mean/median/first/last rule selects them.
2. **The documented Coriolis rule performs worse than our current output**
   (authoritative re-measurement with the trusted parser and the faithful
   Coriolis-equivalent algorithm: **6/12 vs 8/12** — see
   `docs/ABP_EXACT_CORIOLIS_VERIFICATION.md`; the sweep numbers printed in
   the original §D table below are superseded). The exact Coriolis
   calculation differs from the current Python output on exactly two
   cells (2902203/361 121→122, 2902206/360 121→123), both currently
   matching GDAC. Implementing it would be a **parity regression**, not a
   fix.
3. **Even the best rule (mode-tie-low, 9/12) is not justified**: it is not
   the Coriolis rule, has no specification basis, fixes only one cell
   (2902206 cyc361), and still fails the same three 2902222/2902223 cells.

## E. Why GDAC differs — assessment

- GDAC's value is always a **genuine transmitted count** (never an
  invented number), and always within ±1 of ours — consistent with a
  near-stable count whose per-transmission samples vary by a few counts.
- The most probable explanation is that **INCOIS's reception set
  (CLS/ARGOS deliveries) differed from ours**: their chain saw a different
  number of receptions of each distinct transmitted message (our files
  capture a subset of the same passes), so any aggregation over *their*
  copy set can land on a value that is only a minority in *our* set. This
  is consistent with the earlier ABP finding that GDAC's value always
  exists somewhere in our copies.
- **The exact INCOIS rule/copy set cannot be reconstructed from available
  evidence** (we hold neither their ARGOS delivery nor their processing
  chain).

## F. Classification

| Question | Answer |
|---|---|
| Is the emitted field/byte correct? | **Yes** — Message-3 payload byte 1 is ABP on decoder 1010 (manuals p.25 both revisions; ApexCoDecoder row 193; Coriolis `decData(2)`); Part A's emission is correct. |
| Does Coriolis's documented `round(mean)` explain GDAC's values? | **No** — it reproduces only 5/12 on our copy set and is *worse* than our current 8/12. |
| Does any rule over our telemetry reproduce GDAC? | **No** — best is 9/12 (mode-tie-low), failing the same 3 cells. |
| Is the residual ±1 a decoder error? | **No** — both values are real transmitted counts; the difference is which copy/copy-set is aggregated. |
| **Final classification** | **UNKNOWN mechanism (INCOIS-side), NOT FIXABLE as parity from available evidence.** Confidence **HIGH** that no code change is justified (spec + Coriolis source + exhaustive copy analysis + rule sweep all agree); confidence **MEDIUM** on the specific "different reception set" explanation (directly unverifiable). |
| Code change justified? | **No.** |

**Exact reason for no change:** (1) implementing the Coriolis `round(mean)`
rule would change two currently-correct cells (2902203/361, 2902206/360)
and drop parity from 8/12 to 6/12 — a net regression of 2 (authoritative
measurement in `docs/ABP_EXACT_CORIOLIS_VERIFICATION.md`; the 5/12 and
"seven cells" figures in the original sweep above are superseded); (2)
mode-tie-low (9/12) is a +1 gain with no Coriolis or specification basis
and would alter the selection semantics of a real transmitted value on
every cycle, to fix one cell; (3) the disputed cells cannot be reproduced
honestly from our telemetry by any documented rule — chasing them would
mean inventing an aggregation rule to match a reference, which the
project rules forbid. **Part A implementation remains unchanged.**

**Evidence still missing (data, not code):** INCOIS's received-copy set /
derivation rule for these floats (would settle whether their value is a
majority or mean over a different set); an early-life archive for one
091x15 float would also enlarge the ABP sample beyond 12 cells.

## G. Bonus confirmations enabled by the bundle (no code impact)

1. **2901305 cycle 27 FLAG split — now verified from actual raw telemetry**
   (`102526_2011-11-02.txt`): 17 CRC-valid Message-1 copies,
   **9× `0x0001` vs 8× `0x0601`**, `0x0061` nowhere — exactly the split
   documented in `SPEC_VS_CORIOLIS_INVESTIGATION.md` §5 and cited in the
   FLAG investigation as its one pending data request. The FLAG
   classification (NOT FIXABLE, copy-set coin-flip) is now backed by the
   raw evidence.
2. **1005-family ABP** (Message-1, 2901305/2901350 — previously
   unverifiable): raw ABP counts 147–169 across mission cycles, matching
   the ApexCoDecoder's "approx 148 COUNT" and consistent with the already
   measured 1005 tech parity (2901305 1075/1078 with only vacuum/FLAG
   cells; 2901350 938/938 exact). No ABP issue exists on decoder 1005.
3. The bundle's metadata CSVs are the same source data as the workspace's
   processed 4-CSV (differences are only Excel number formatting, e.g.
   `2.02E+13` vs expanded datetimes); the workspace revision remains the
   canonical decoder input.

---

*Investigation only. No source, test, configuration, or generated NC file
was modified. The operator-provided bundle was used read-only.*
