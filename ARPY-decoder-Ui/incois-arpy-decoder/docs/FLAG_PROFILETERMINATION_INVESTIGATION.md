# FLAG_ProfileTermination_hex — copy-selection re-analysis

**Issue:** `FLAG_ProfileTermination_hex` on APF9 floats. Previously documented
cells of disagreement: 2901304 cyc20 (GDAC `61` vs ours `01`), 2901305 cyc27
(0x0001 vs 0x0601 copy split), 2901328 cyc85 (`01D` vs `1D`).

**Date:** 2026-08-17 · **Type:** investigation only — no source, test, or
configuration file modified. GDAC files were fetched live from
`https://data-argo.ifremer.fr/dac/incois/` on this date.

---

## A. What `FLAG_ProfileTermination_hex` represents — specification evidence

**The value is the message-1 STATUS word ("Float status word").**

- **061810 manual** (`20100618_V061810_1772.A_rev20100907`, "Data Message 1",
  p.20 and STATUS table p.21): spec bytes `7–8 STATUS Float status word - 16
  bits, see below`; bit table: `0x0001 DeepPrf` … `0x0200 Sbe41Exception`,
  `0x0400 Sbe41Unreliable`, `0x2000 AirSysBypass`, `0x4000 WatchDogAlarm`,
  `0x8000 PrfIdOverFlow`, `0x0800/0x1000 not used yet`.
- **110613 manual** p.21–22 and **090413 manual** p.21–22 (decoder 1010):
  identical tables (`0x1000 TelonicsException` additionally defined).
- **071807 FormatNotes** (D7): the older bit names for the same word
  (`0x0200 Sbe41PFail`, `0x0400 Sbe41PtFail` — renamed in 061810+ manuals to
  `Sbe41Exception` / `Sbe41PUnreliable`; same bits).
- **ApexCoDecoder** 061810 rows 21/89 and 110613 rows 21/128: `STATUS | Float
  status word 16 bits | techId 100` and `STATUS | Same as the Test Message 1
  Status word | techId 1001`, both mapped to **`FLAG_FloatStatus_hex`**.
- **Position (verified):** payload bytes 5–6 (big-endian 16-bit) = spec bytes
  7–8. This is the offset our `decode_engineering_message_1` reads, and it
  equals Coriolis's `decData(5)` (below). The earlier naive readings of the
  byte tables (SP "at spec byte 11") are the known manual-numbering quirk
  already documented in `engineering.py` — the verified offsets reproduce
  GDAC on 1000+ rows and must not be "corrected".
- **Nature:** an *engineering/status* field, transmitted in every message-1
  copy; **each copy carries a fresh STATUS sample** (the float re-samples
  status per message block — verified: the value legitimately changes within
  one transmission pass, see §C). The INCOIS label `FLAG_ProfileTermination_hex`
  is INCOIS's own name for this STATUS word (Coriolis's name:
  `FLAG_FloatStatus_hex`); the "termination" reading is informal — the bits
  are the profile-termination-cause flags (timeouts, piston-full-extension,
  SBE41 failure, watchdog…).
- **No documented transformation** exists for the published value other than
  the `PrfIdOverflow` re-pack our `format_termination_flag` implements
  (bit 15 → bit 11) and hex formatting. GDAC's fleet-wide value set is fully
  reproduced by `f"{packed:02X}"` with that repack — except one string-width
  anomaly (§F.2).

## B. Coriolis verification (GitHub `main`, fetched 2026-08-17)

- `decArgo_soft/soft/sub/decode_data_apx_1_5.m` (decoder 1005), message-1
  branch: `tabNbBits = [1 2 1 1 2 2 ...]*8` at `firstBit = 17` →
  `decData(5)` = bits 33–48 of `msgData` = **payload bytes 5–6 = STATUS**
  (same byte pair we read; `decData(2)`=Float ID, `(3)`=profile number,
  `(4)`=profile length confirm the layout registration).
- Status emission: `dataStruct.label = 'Float status word';
  dataStruct.value = sprintf('%#X', decData(5)); techId = 1001` (and techId
  100 in the test-message decoder). **Pure formatting (`%#X` adds an `0X`
  prefix) — no masking, no averaging, no bit operation.**
- `sensor_2_value…`-style conversion: none — the value is published as-is.
- **Coriolis cannot turn `0x0601` into `0x0061`** by any operation in its
  source. (`FLAG_ProfileTermination_hex` itself is absent from the Coriolis
  1005 vocabulary — the audit already established INCOIS runs its own chain;
  the underlying field is the same STATUS word.)
- Coriolis's per-copy handling: it processes every received copy
  (occurrence-weighted) and reads STATUS from each selected row; the final
  published value follows its tech-collection pipeline. Since INCOIS's
  published files use their own label and their own values, Coriolis's exact
  dedup rule is not the binding reference here — the binding facts are the
  field position, the bit semantics, and the absence of any transformation.

## C. 2901304 cycle 20 — exhaustive analysis

Raw file `102525_2011-08-23.txt`, 1 transmission, 154 messages, **11
message-1 copies** (10 CRC-valid, 1 CRC-bad):

| # | received (UTC) | STATUS | CRC | redundancy-weighted rows |
|---|---|---|---|---|
| 1 | 2011-08-23 00:38:54 | `0x0001` | OK | 1 |
| 2 | 00:50:24 | `0x0001` | OK | 1 |
| 3 | 01:24:54 | `0x0001` | BAD | 1 |
| 4 | 01:24:54 | `0x0001` | OK | 1 |
| 5 | 02:22:24 | `0x0001` | OK | 1 |
| 6 | 03:08:26 | `0x0601` | OK | 1 |
| 7 | 03:54:26 | `0x0601` | OK | 1 |
| 8 | 04:05:56 | `0x0601` | OK | 1 |
| 9 | 05:37:56 | `0x0601` | OK | 1 |
| 10 | 07:09:56 | `0x0601` | OK | 1 |
| 11 | 08:53:26 | `0x0601` | OK | 1 |

- Distribution: **4× `0x0001` (00:38–02:22) then 6× `0x0601` (03:08–08:53)**
  — a clean **time-ordered transition**, not corruption: every copy is
  CRC-valid (except one duplicate at 01:24), and the change is monotone.
- `0x0061` (GDAC's old published value) **occurs at no byte offset of any
  copy of any message** in this file. A whole-archive scan of **all 25
  2901304 raw files** (every transmission, every message, every byte, plus
  the deployment-era test messages read at both the data-layout and the
  test-layout STATUS offsets) finds **zero occurrences of `0x0061` as a
  STATUS word in either layout**. The only `0x0061` byte-pairs anywhere are
  interior bytes of hydrographic T/S data in one unrelated cycle's messages
  (`… 01 93 00 61 …` — a temperature/salinity boundary, not a flag).
- No legitimate transformation of any observed copy produces `0x0061`:
  `0x0001`→`01`, `0x0601`→`601` under the documented repack; byte-swaps,
  shifts, masks and mis-offset reads were each checked against the copies
  and none yields `0x0061`.
- Interpretation of `0x0061`: bits `0x0040 PreludeMsg | 0x0020 TestMsg |
  0x0001 DeepPrf` — a **mission-prelude test message** signature. Cycle 20
  was a normal mission surfacing of a failing CTD (the SBE41 bits turned on
  mid-pass); no prelude/test transmission exists anywhere near it. `0x0061`
  is not a plausible state of this float at this time.
- **Our emitted value:** `01` (the earliest CRC-valid copy — our selection
  rule, see §D). **Current GDAC value: `01`.** The mismatch is **gone**.

### Why GDAC's old `61` disappeared

The current `2901304_tech.nc` carries `DATE_UPDATE = 20260813054608` —
**INCOIS regenerated the file on 2026-08-13 05:46**, the same day the
previous agent's `OPEN_ISSUES_2901304.md` recorded `61` (their fetch
pre-dated or raced the regeneration; the 08-14 parity audit already
measured the regenerated file at 322/322). The current file has `01` at
cycle 20, matching our decode exactly. The old `61` was a GDAC-side value
with **no telemetry basis** (it exists in no transmitted copy, in no
message, at no offset, in the entire archive). **Closed — externally
resolved by GDAC; nothing to fix; do not fabricate `61`.**

## D. The `0x0601` vs `0x0001` split — what `0x0600` means

- `0x0600` = `0x0200 Sbe41Exception` + `0x0400 Sbe41PUnreliable` (061810/
  110613/090413 STATUS tables) — **SBE41 failure indicators**, not
  corruption and not a format artefact.
- The split is **time-varying status**: in cycle 20 the SBE41 began failing
  at ~03:08 and stayed failed for the rest of the pass (all later copies
  `0x0601`). This matches the cycle's science: GDAC blanket-rejected the
  cycle-20 profile in delayed mode and the salinity is visibly wrong
  (PSAL 35.863…37.154 vs ~35.96 deep).
- The two candidate values are both *genuine transmitted words*; the
  question is purely which copy the decoder publishes.
- **Our selection rule** (`select_redundant_messages`, message 1): largest
  group of identical masked frames, ties → earliest reception; the STATUS
  word is deliberately **excluded** from the per-byte majority path
  (`_MAJORITY_BYTE_OFFSETS = {9, 18–25}` — analogue channels only), because
  STATUS is a flag word, not a re-sampled analogue channel.
- **No single deterministic rule reproduces GDAC on both observed cases:**

  | rule | 2901304 cyc20 (4×0001 / 6×0601) | 2901305 cyc27 (9×0001 / 8×0601) |
  |---|---|---|
  | earliest copy (our rule) | `01` = **GDAC** ✓ | `601` ≠ GDAC `01` ✗ |
  | per-byte majority | `601` ≠ GDAC `01` ✗ | `01` = **GDAC** ✓ |
  | latest copy | `601` ✗ | ? |

  Since our rule already matches GDAC on cyc20 (and on 23/23 rows of that
  float today), and the majority rule would *break* cyc20 to fix cyc27,
  **no rule change is justified**. GDAC's own reception set/order is not
  ours (its chain had different satellite coverage in 2013/2016), so its
  per-cycle choice is not reproducible in general.

## E. 2901305 cycle 27 — second independent case

- Raw telemetry for 2901305 (PTT 102526) is **not present in this
  workspace** (only its GDAC files are). The previously documented split
  (17 CRC-valid copies: `0x0001` ×9 vs `0x0601` ×8 — `SPEC_VS_CORIOLIS_INVESTIGATION.md`
  §5, and `APF9_PARITY_STATE.md` §7) is the only raw-level evidence.
- Our on-record decode (`parity_fresh_nc3/2901305_tech.nc`, same selection
  logic as current code) publishes **`601`**; the current GDAC file
  (`DATE_UPDATE = 20161219144105`, unchanged since 2016) has **`01`**
  (= `0x0001`, the majority by one copy).
- The split behaves identically to 2901304 cyc20 (0x0001 vs 0x0601, i.e.,
  SBE41 failure bits on some copies) — same mechanism, same irreducibility.
- GDAC's `2901305` file contains **no `61` anywhere** (values: `01`, `615`,
  `4615`, one empty prelude row) — confirming `61` was unique to the old
  2901304 file.

## F. GDAC comparison — current state (fetched 2026-08-17)

Fleet-wide `FLAG_ProfileTermination_hex`, ours vs current GDAC, keyed on
`(cycle)`:

| Float | shared rows | FLAG mismatches | details |
|---|---|---|---|
| 2901304 | 23 | **0** | cyc20 `01`/`01` — resolved (GDAC regenerated 08-13) |
| 2901328 | 119 | **1** | cyc85 `1D` vs `01D` — identical value, width only |
| 2901339 | 71 | 0 | |
| 2902201 | 0 (no cycle overlap) | — | |
| 2902203/06/2222/2223 | 3 each | 0 | all shared cycles |
| 2902224 | 2 | 0 | |
| 2901305 | 77 | **1** | cyc27 `601` vs `01` — copy split (§E); raw unavailable to re-derive |

- GDAC's fleet-wide FLAG value set is otherwise **fully reproduced by our
  formatter**: `01, 03, 05, 0D, 4D, 21, 201, 615, 801, 805, 809, 821, 829,
  84D, 901, A01, 4615` — every one equals `f"{packed:02X}"` under the
  documented bit-15→11 repack.
- **`01D` (2901328 cyc85):** all 9 message-1 copies (7 CRC-valid) carry
  `0x001D` = 29 — the same number our `1D` represents. GDAC's `01D` is its
  **only** 3-digit-with-leading-zero value in ~2 900 rows fleet-wide
  (`0D`, `4D` are 2-digit; `801`, `615`, `A01`, `84D` are not padded); no
  formatting rule reproduces it without a per-value special case.
  **GDAC-side representation anomaly; value identical; do not chase.**

## G. Classification

**Overall: NOT FIXABLE — no code change justified.** Confidence **HIGH**
(manual + ApexCoDecoder + Coriolis source + exhaustive raw scans + current
GDAC files all agree).

| Sub-item | Class | Evidence |
|---|---|---|
| 2901304 cyc20 old `61` | **Resolved externally** (GDAC regenerated file 2026-08-13 05:46; now `01` = ours). The old value had no telemetry basis — `0x0061` never transmitted anywhere in the archive, no transformation produces it, Coriolis cannot produce it. | §C; whole-archive scan; `DATE_UPDATE` |
| 2901305 cyc27 `601` vs `01` | **NOT FIXABLE** — near-even copy split; both values are real transmitted STATUS words; no selection rule reproduces GDAC on both cyc20 and cyc27 (majority would break the now-matching cyc20); GDAC's reception set is not ours. Raw unavailable to re-derive (documented 9-vs-8 split). | §D, §E |
| 2901328 cyc85 `1D` vs `01D` | **NOT FIXABLE** — numerically identical value (0x001D=29, all 9 copies); GDAC string-width one-off; no honest formatter reproduces it. | §F |

**Exact proposed code change:** none. The current implementation — STATUS
read at payload 5–6, `format_termination_flag` bit-15→11 repack, `%02X`
output, STATUS excluded from per-byte majority — is specification-correct,
Coriolis-correct, and matches the current GDAC on every decodable shared
row except the two irreducibles above. Changing the selection rule or the
formatting would trade real parity for fabricated parity.

**What would change the classification:** (1) raw telemetry for 2901305
cycle 27 (to confirm the split and copy order); (2) INCOIS's FLAG
derivation rule; (3) a GDAC regeneration of 2901305/2901328. Data requests,
not code.

## H. Relationship to prior records

- `SPEC_VS_CORIOLIS_INVESTIGATION.md` §4–5 already classified the two live
  cells (Class C `01D` one-off; Class F cyc27 coin-flip) — **confirmed** by
  this session's fresh fleet comparison; note §5 quotes the *071807* bit
  names (`Sbe41PFail`/`Sbe41PtFail`); the current-manual names for the same
  bits are `Sbe41Exception`/`Sbe41PUnreliable` (naming only, no value
  effect).
- `OPEN_ISSUES_2901304.md` T1 (cyc20 `61`) is a dated snapshot (08-13,
  pre-regeneration); the cell is **resolved** — `APF9_PARITY_STATE.md`'s
  08-14 table (322/322) already reflects the regenerated file. No state
  document was modified this session (per instruction, the report stands
  alone pending your review).

*Investigation only. No source, test, configuration, or generated NC file
was modified.*
