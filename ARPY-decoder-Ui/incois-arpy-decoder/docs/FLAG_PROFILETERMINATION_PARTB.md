# Part B — FLAG_ProfileTermination complete re-analysis

**Date:** 2026-08-18 · **Type:** investigation only — no source, test, or
configuration file modified.
**Scope:** the five decoder-1005 APF9 floats, using the operator-provided
raw bundle (Drive `1NQRBUJnn-umHevX-VMMKPP2zk0Tei7oF`, read-only, extracted
to `/tmp/abp_raw`) with the **project's trusted parser**, the APF9A
manuals, ApexCoDecoder extracts, the Coriolis source (GitHub `main`), and
the current GDAC references (fetched 2026-08-18).

This re-analysis independently re-derives everything from the primary
evidence; the previous report (`docs/FLAG_PROFILETERMINATION_INVESTIGATION.md`)
is treated as a hypothesis to verify, not as truth.

---

## 1. Specification evidence — what the flag is, bit by bit

**Field:** the message-1 **STATUS word** ("Float status word"), 16 bits,
big-endian, at **payload bytes 5–6** (= spec bytes 7–8; = frame columns
7–8, 1-based). Present in every Message-1 copy; the float re-samples it
per message block, so copies within one pass can legitimately differ.

- **061810 manual** p.21 ("Test Message 1 – Status Word – 16 bits" — the
  same table governs Data Message 1):
  `0x0001 DeepPrf · 0x0002 ShallowWaterTrap · 0x0004 Obs25Min ·
  0x0008 PistonFullExt · 0x0010 AscentTimeOut · 0x0020 TestMsg ·
  0x0040 PreludeMsg · 0x0080 PActMsg · 0x0100 BadSeqPnt · 0x0200
  Sbe41Exception · 0x0400 Sbe41Unreliable · 0x0800/0x1000 not used ·
  0x2000 AirSysBypass · 0x4000 WatchDogAlarm · 0x8000 PrfIdOverFlow`
- **110613 manual** p.22 and **090413 manual** p.22: identical table
  (0x1000 additionally = `TelonicsException`). **071807 FormatNotes (D7):**
  the older names for the same two bits — `0x0200 Sbe41PFail`,
  `0x0400 Sbe41PtFail` (renamed in 061810+; same bits, no value change).
- **Meaning of `0x0600` (= 0x0200 | 0x0400):** `Sbe41Exception` +
  `Sbe41PUnreliable` — the SBE41 CTD reported an exception and unreliable
  pressure. This is a **real engineering state**, not corruption.
- **ApexCoDecoder** 061810 rows 21/89 (and 110613 rows 21/128): `STATUS |
  Float status word 16 bits | techId 100` (test) / `techId 1001` (data),
  name **`FLAG_FloatStatus_hex`**. The INCOIS label
  `FLAG_ProfileTermination_hex` is INCOIS's own name for this same word;
  no separate "profile termination" field exists in any manual or
  spreadsheet extract.
- **No documented transformation** of the word before publication other
  than the bit-15→11 `PrfIdOverflow` re-pack and hex formatting (this is
  what our `format_termination_flag` implements, and it reproduces GDAC's
  entire fleet-wide value set except one string-width anomaly, §6).

## 2. Coriolis evidence — exact extraction and selection

- **Extraction** (`decode_data_apx_1_5.m`, decoder 1005, message 1):
  `tabNbBits = [1 2 1 1 2 2 ...]*8` at `firstBit = 17`; STATUS =
  `decData(5)` = payload bytes 5–6 (verified by registration: decData(2)
  = Float ID 7319, decData(3) = profile number, decData(4) = profile
  length). Published as `sprintf('%#X', decData(5))`, techId 1001 —
  **pure formatting; no masking, no averaging, no bit operation**.
- **Selection** (`get_apex_data_sensor.m`): CRC-valid copies only; grouped
  by payload with **frozen bytes zeroed**; most-redundant group
  (occurrence-weighted); ties → earliest first-seen (MATLAB `max`
  semantics); the published value comes from that group's **representative
  copy** (the first copy seen of the group).
- **Frozen bytes** (`get_bytes_to_freeze.m`, case {1001, 1005}, data
  message 1): frame columns **`[3 12 26:31]`** (1-based) = payload indices
  **{0, 9, 23–28}** (FLT low byte, VAC, and the air-pump battery/ABP/VSAP
  tail). **STATUS (cols 7–8) is NOT frozen.**
- Consequence: copies that differ only in STATUS *and* frozen bytes merge
  into one group; the representative is the first copy of the largest such
  group — i.e., on a clean two-way STATUS split, **Coriolis's rule
  effectively selects the STATUS majority** (verified empirically, §5).
- Test-message STATUS (techId 100) exists only in prelude/activation
  transmissions; those are skipped by our pipeline (as GDAC's empty FLAG
  rows confirm) and are irrelevant to the affected cycles.
- **Coriolis cannot produce `0x0061`** from `0x0001`/`0x0601` by any
  operation in its source.

## 3. Raw telemetry — the affected cycles, copy by copy (trusted parser)

**2901304 cycle 20** — `102525_2011-08-23.txt`, 11 Message-1 rows, 10
CRC-valid:

| received (UTC) | STATUS | CRC | note |
|---|---|---|---|
| 2011-08-23 00:38:54 | 0x0001 | OK | |
| 00:50:24 | 0x0001 | OK | differs from 00:38 only in frozen byte |
| 01:24:54 | 0x0001 | OK | |
| 02:22:24 | 0x0001 | OK | |
| 03:08:26 | **0x0601** | OK | SBE41 fail bits turn on |
| 03:54:26 | **0x0601** | OK | |
| 04:05:56 | **0x0601** | OK | |
| 05:37:56 | **0x0601** | OK | |
| 07:09:56 | **0x0601** | OK | |
| 08:53:26 | **0x0601** | OK | |
| 01:24:54 | 0x0001 | BAD | duplicate of the 01:24 OK row |

Distribution: **4× 0x0001 → 6× 0x0601**, a clean time-ordered transition
(matches the cycle's bad science: GDAC delayed-mode blanket-rejected the
profile; PSAL 35.863–37.154). All 10 frames are pairwise distinct
(full-frame grouping: ten singleton groups).

**2901305 cycle 27** — `102526_2011-11-02.txt`, 17 CRC-valid Message-1
copies: **9× 0x0001 vs 8× 0x0601**. Full-frame grouping is *not* all
singletons: group sizes {1×8, 2×3, 3×1} — the largest group is a 3-copy
0x0601 group (16:33), then three 2-copy groups.

**2901328 cycle 85** — `102507_2012-10-28.txt`, 7 CRC-valid copies, all
**0x001D** (9 rows incl. 2 CRC-bad, all 0x001D). No split.

**Fleet scan for other splits** (all five 1005 floats, prelude-era files
excluded): genuine mission-cycle splits exist only at 2901305 PRF 50
(60× 0x0615 vs 1× 0x0635), 2901305 PRF 83 (25× 0x0615 vs 1× 0xAAAA),
2901339 PRF 47 (6× 0x0001 vs 1× 0x4109) — all **overwhelming majorities**
— plus the two near-even splits (cyc20, cyc27) above.

**0x0061 existence check:** the whole-archive scan (all 25 files of
2901304, every message, every byte, both the data-layout and test-layout
STATUS offsets; re-verified) finds **zero** occurrences of `0x0061` as a
STATUS word; the only `0x0061` byte-pairs anywhere are interior bytes of
hydrographic data. `0x0061` (= PreludeMsg|TestMsg|DeepPrf) is also not a
plausible state for a normal mission surfacing. **No legitimate
transformation of any transmitted copy produces `0x0061`.**

## 4. Current Python behaviour

Selection (`select_redundant_messages`, no frozen bytes): group by full
31-byte frame, most-redundant group, ties → earliest reception. STATUS is
excluded from the per-byte majority path (`_MAJORITY_BYTE_OFFSETS` =
analogue channels only). Result per affected cycle:

- cyc20: all frames unique → earliest (00:38, 0x0001) → **"01"**.
- cyc27: largest full-frame group = x3 0x0601 (16:33) → **"601"**.
- cyc85: unanimous 0x001D → **"1D"**.

## 5. Exact Coriolis-equivalent rule vs GDAC vs ours — fleet-wide

Coriolis rule applied per cycle (frozen payload {0,9,23–28}, masked
grouping, first-of-most-redundant representative), all five floats, all
cycles shared with GDAC:

| float | shared | **ours** mismatches vs GDAC | **Coriolis rule** mismatches vs GDAC |
|---|---|---|---|
| 2901304 | 22 | **0** | 1 (cyc20: 601 vs GDAC 01) |
| 2901305 | 74 | 1 (cyc27: 601 vs GDAC 01) | **0** |
| 2901328 | 119 | 1 (cyc85: `1D` vs `01D` — same value 0x001D, string width) | 1 (same) |
| 2901339 | 71 | 0 | 0 |
| 2901350 | 67 | 0 | 0 |
| **total** | **353** | **2** (1 value + 1 formatting) | **2** (1 value, *swapped*, + 1 formatting) |

Per affected cycle, the Coriolis rule selects: cyc20 → **601** (6-copy
0x0601 group; the four 0x0001 copies merge into a 4-copy group — the
0x0601 family wins); cyc27 → **01** (9-copy 0x0001 group vs 8-copy
0x0601). On the majority-split cycles (PRF50/83, PRF47) both rules match
GDAC.

**Decisive finding: the exact Coriolis rule and the current Python rule
each match GDAC on 352 of 353 shared cells; they differ from each other
on exactly two cells (cyc20, cyc27), and adopting the Coriolis rule would
merely *swap* which of the two cells mismatches — zero net parity gain,
while changing message-1 selection semantics fleet-wide (the
representative copy changes on every cycle where masked grouping merges
copies, which can also move other message-1-derived published values on
such cycles).**

## 6. GDAC comparison and the two open cells

- **cyc20** (2901304): GDAC `01` = the 0x0001 minority of our copy set
  (4/10). The majority of our copies (6× 0x0601) and the exact Coriolis
  rule both give `601`. GDAC's `01` is therefore **not reproducible from
  our copy set by any deterministic rule** (earliest, majority/Coriolis,
  median, first, last, mode all fail: earliest gives 01 only because the
  earliest copy happens to be 0x0001). The only consistent explanation is
  that **INCOIS's received copy set for this 2011 cycle differed from
  ours** (more 0x0001 receptions on their side).
- **cyc27** (2901305): GDAC `01` = the majority (9/17) of our copies —
  reproduced by the Coriolis rule; our earliest-largest-group rule picks
  the x3 0x0601 group and gives `601`.
- **cyc85** (2901328): both sides agree the value is 0x001D (= 29); GDAC's
  `01D` is its only 3-digit-with-leading-zero string in ~2 900 fleet-wide
  rows — a GDAC string-width anomaly with no formatting rule behind it
  (value identical; do not chase).
- The old GDAC cyc20 `61` is moot: the current GDAC file (regenerated
  2026-08-13 05:46) publishes `01`; the historical `61` exists in no
  transmitted copy and was never reproducible.

## 7. The previous "coin-flip" conclusion — revisited

The prior classification (NOT FIXABLE; "copy-selection coin-flip") is
**confirmed in outcome but refined in mechanism**:

- It is **not** an arbitrary coin-flip: two deterministic, documented
  rules (our earliest-group rule; Coriolis's frozen-byte/majority rule)
  each reproduce GDAC on 352/353 shared cells. GDAC's choices on cyc27
  and on every other split cycle found in the fleet are consistent with
  **majority-of-received-copies** (equivalently the exact Coriolis rule).
- The single irreconcilable cell is **cyc20**, where GDAC's `01`
  contradicts the majority of *our* copy set — explainable only by a
  different reception set at INCOIS in 2011. No implementable rule can
  match both cyc20 and cyc27 from our telemetry.
- Therefore the residual is a **copy-set difference on one 2011 cycle**,
  not a decoder defect and not a rule defect.

## 8. Classification

**NOT FIXABLE.**

- **Why:** (1) both candidate values on every split cycle are genuine,
  CRC-valid transmitted STATUS words; (2) the exact Coriolis rule —
  the only specification/source-documented alternative — reproduces GDAC
  no better than our current rule (identical net mismatch count) and
  would change a currently-correct cell (cyc20) to fix a currently-wrong
  one (cyc27): a 1-for-1 swap with zero parity gain; (3) implementing it
  would additionally change message-1 representative-copy selection
  fleet-wide (any cycle where masked grouping merges copies), moving
  other message-1-derived published values on such cycles without
  evidence; (4) the cyc20 cell is not reproducible from our telemetry by
  any documented rule.
- **Missing evidence (data, not code):** INCOIS's actual received ARGOS
  copy set and FLAG derivation for 2901304 cycle 20 (2011 processing).
  With it, the cyc20 value could be re-derived; without it, any change
  would be curve-fitting to a reference.
- **Why changing code is unjustified:** a change would be a net-zero
  parity swap, would alter selection semantics beyond FLAG, and would
  trade a reproducible, spec/Coriolis-consistent rule (current) for one
  that matches GDAC on the same number of cells. The current
  implementation is supported by the available specification and
  telemetry evidence; no code change is justified.
- Confidence: **HIGH** (specification + Coriolis source + trusted-parser
  raw analysis + fleet-wide GDAC comparison all agree). Confidence
  **MEDIUM** on the specific "different reception set for cyc20"
  explanation (not directly verifiable).

**Regression/parity impact of doing nothing:** none — current output is
unchanged and already matches GDAC on 352/353 shared FLAG cells (the two
remaining cells are the documented cyc27 value cell and the cyc85 string
width).

---

*Investigation only. No source, test, configuration, or generated NC file
was modified. The operator bundle was used read-only.*
