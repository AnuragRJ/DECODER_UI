# ABP exact-Coriolis verification — parser discrepancy resolved

**Date:** 2026-08-18 · **Type:** investigation only — no production code,
test, or configuration modified.

**Supersedes:** the rule-sweep tables in
`docs/ABP_COPY_SELECTION_INVESTIGATION.md` (those came from an ad-hoc
parser with two defects; see §3). The per-copy *distributions* reported
there were correct (the ad-hoc parser's frame extraction matched the
trusted parser); the *aggregation* numbers were not. This document is the
authoritative measurement.

**Parsing basis:** the project's trusted parser
(`argo_decoder.platforms.apex_argos.frames`: `split_transmission_text` +
`iter_argos_messages_from_payload` + `check_crc`) for **all** frame
extraction. The Coriolis selection logic was re-implemented separately and
faithfully (§4). Raw evidence: the operator-provided bundle
(Direct link `1NQRBUJnn-umHevX-VMMKPP2zk0Tei7oF`), extracted read-only to
`/tmp/abp_raw` (407 entries; the five 1010 PTT directories md5-identical
to the workspace copies).

---

## 1. Selected trace case — 2902201 / cycle 358 (project parser)

File `152399_2025-12-25_2902201_358.txt`: 1 transmission, 134 messages
parsed (message-number distribution: 1×5, 2×11, 3×8, 4×10, 5×10, 6×9,
7×11, 8×11, 9×9, 10×10, 11×9, 12×7, 13×5, 14×8, 15×11).

**Every Message-3 copy (all 8 CRC-valid, occurrence-expanded):**

| # | received (UTC) | VAC | ABP | frame (31 bytes, hex) |
|---|---|---|---|---|
| 0 | 2025-12-25 12:52:26 | 82 | 123 | `9d03527b0a9624d80000275f0d1b00004e230e5c00004a310ffc0000465012` |
| 1 | 2025-12-25 14:35:56 | 82 | 123 | `9d03527b0a9624d80000275f0d1b00004e230e5c00004a310ffc0000465012` |
| 2 | 2025-12-25 18:37:26 | 82 | 122 | `ad03527a0a9624d80000275f0d1b00004e230e5c00004a310ffc0000465012` |
| 3 | 2025-12-25 23:24:28 | 83 | 125 | `e403537d08dc0a468753275708c888194a37090c8810465309348807426709` |
| 4 | 2025-12-25 19:23:26 | 82 | 122 | `ad03527a0a9624d80000275f0d1b00004e230e5c00004a310ffc0000465012` |
| 5 | 2025-12-25 18:37:26 | 82 | 122 | `ad03527a0a9624d80000275f0d1b00004e230e5c00004a310ffc0000465012` |
| 6 | 2025-12-25 23:24:28 | 83 | 125 | `e403537d08dc0a468753275708c888194a37090c8810465309348807426709` |
| 7 | 2025-12-25 19:23:26 | 82 | 122 | `ad03527a0a9624d80000275f0d1b00004e230e5c00004a310ffc0000465012` |

(byte 0 = CRC, byte 1 = MSG=03, byte 2 = VAC, byte 3 = ABP, bytes 4–5 = PMT,
bytes 6–… = park sample. All occurrence counts = 1.)

**Resulting distributions (crc-ok):**
- ABP: **122×4, 123×2, 125×2** — identical to the previously trusted
  analysis of the same file.
- VAC: **82×6, 83×2**.

**Conclusion: the trusted parser's extraction is reproduced exactly; the
previously trusted ABP distribution for this cycle is confirmed.**

## 2. Why the ad-hoc script produced impossible values (9/10/12)

Two defects in the discarded `/tmp/abp_analysis.py`:

1. **Group-seeding index bug (the spurious 9/10/12).** When a new masked
   group was created, the script seeded the group's ABP list with
   `frame[4]` (0-based) instead of `frame[3]`:
   ```python
   groups.append([dt, masked, [frame[4]], [frame]])  # frame[4] = payload[2] = PMT high byte
   ```
   `frame[4]` is **not ABP** — it is the **PMT (pump-motor time) high
   byte** (payload[2]). The "ABP=9/10/12" copies were PMT high bytes, not
   ABP readings. Proof — the spurious value on each float equals that
   float's first Message-3 PMT high byte exactly:

   | float | spurious value in buggy run | frame[4] (=PMT high byte) of first msg3 copy |
   |---|---|---|
   | 2902201 | 10 | 10 (0x0A) → PMT 2710 s |
   | 2902203 | 10 | 10 (0x0A) → PMT 2677 s |
   | 2902206 | 12 | 12 (0x0C) → PMT 3127 s |
   | 2902222 | 9 | 9 (0x09) → PMT 2318 s |
   | 2902223 | 8 | 8 (0x08) → PMT 2268 s |

   (The first buggy run also had the ABP offset wrong by one byte; the
   9/10/12 values persisted across both bugs because the seed line kept
   `frame[4]` until the second fix.)

2. **Grouping key included the CRC byte.** Coriolis groups copies by
   **payload only** (`sensor(3:end)` in `get_apex_data_sensor.m`), with
   the frozen ABP byte zeroed. The ad-hoc script masked only the ABP byte
   but compared **full frames** (CRC included), so copies that differ only
   in CRC fell into different groups, corrupting the "most redundant
   group" selection. This affected the aggregation numbers in the earlier
   rule-sweep (now superseded).

Neither defect affects the project parser (which was never used for the
buggy aggregation) — and the corrected exact-Coriolis calculation in §4
uses the project parser throughout.

## 3. Exact Coriolis-equivalent algorithm (as implemented, investigation-only)

Per the Coriolis sources (GitHub `main`, fetched 2026-08-17):

1. `get_bytes_to_freeze.m`, decoder 1010: msg3 frozen frame byte = `[4]`
   (1-based) = **ABP** — zeroed during redundancy grouping.
2. `get_apex_data_sensor.m`: CRC-valid copies only; group by payload
   (frame bytes 3..31) with the frozen byte zeroed; select the **most
   redundant** group (occurrence-weighted; ties → earliest first-seen,
   because MATLAB `max` returns the first maximum).
3. `decode_data_apx_10.m` techId 1022: `num2str(round(mean(tabBladPres)))`
   over the selected group's copies, with MATLAB `round` (half away from
   zero).

Implementation notes: copies are sorted chronologically before grouping
(Coriolis sorts received data by date); occurrence expansion is handled by
the project parser itself (`iter_argos_messages_from_payload` expands each
line by its occurrence count, matching `read_argos_file`'s duplication);
all 1010 files here carry occurrence = 1, so expansion is a no-op.

## 4. The 12 GDAC-comparable cells — raw distributions vs exact Coriolis vs current Python vs GDAC

| float | cyc | raw ABP dist (crc-ok, occ-expanded) | **exact Coriolis** | **current Python** | **GDAC** | C=G | O=G |
|---|---|---|---|---|---|---|---|
| 2902203 | 359 | 122×2, 123×6 | 123 | 123 | 123 | ✓ | ✓ |
| 2902203 | 360 | 122×1, 123×22, 124×8 | 123 | 123 | 123 | ✓ | ✓ |
| 2902203 | 361 | 121×6, 122×5, 123×6 | 122 | 121 | 121 | ✗ | ✓ |
| 2902206 | 359 | 122×14, 123×7, 125×1 | 122 | 122 | 122 | ✓ | ✓ |
| 2902206 | 360 | 121×8, 123×8 | 123 | 121 | 121 | ✗ | ✓ |
| 2902206 | 361 | 121×1, 122×1 | 122 | 122 | 121 | ✗ | ✗ |
| 2902222 | 327 | 123×7, 124×1 | 123 | 123 | 123 | ✓ | ✓ |
| 2902222 | 328 | 96×1, 122×8, 123×40, 124×32 | 123 | 123 | 122 | ✗ | ✗ |
| 2902222 | 329 | 96×6, 121×7, 122×7, 123×42, 125×7 | 123 | 123 | 122 | ✗ | ✗ |
| 2902223 | 327 | 122×2, 123×6, 124×2 | 123 | 123 | 123 | ✓ | ✓ |
| 2902223 | 328 | 96×1, 122×8, 123×24, 124×8 | 123 | 123 | 123 | ✓ | ✓ |
| 2902223 | 329 | 123×6, 125×12, 126×6 | 125 | 125 | 126 | ✗ | ✗ |

**Totals: exact Coriolis-equivalent matches GDAC 6/12; current Python
matches GDAC 8/12.**

Notes on group composition (why some groups are smaller than the full
CRC-valid set): copies also differ in VAC on some cycles (VAC is sampled
once per park phase but its byte still varies on a few cycles — e.g.
2902206/360 splits 8×VAC=81 vs 8×VAC=82, a tie resolved by Coriolis to
the earliest-first-seen group = ABP 123; 2902222/328–329 exclude the
VAC=83 minority copies which carry the ABP=96 outliers).

## 5. Does the exact Coriolis rule reproduce GDAC?

**No.** 6/12. The four cells where both fail (2902206/361, 2902222/328,
2902222/329, 2902223/329) have GDAC values (121, 122, 122, 126) that are
real transmitted counts but **minorities** in our copy set (1/2, 8/81,
7/69, 6/24). No documented rule — Coriolis's own, modal, median, first,
last, or any mean variant — selects those values from our copy set.

Equally important: the exact Coriolis rule is **worse** than the current
Python implementation on this sample (6/12 vs 8/12). The exact Coriolis
calculation differs from the current Python output on **exactly two
cells**, both of which currently match GDAC:

- 2902203 / cycle 361: Coriolis 122 vs ours 121 (GDAC 121)
- 2902206 / cycle 360: Coriolis 123 vs ours 121 (GDAC 121)

So adopting the exact Coriolis rule would change **two currently-correct
cells** and reduce parity from 8/12 to 6/12 — a net regression of 2.

## 6. Classification

**NOT FIXABLE.**

- The current implementation reads the correct byte (Message-3 payload
  byte 1, specification p.25 both 1010-family manuals; ApexCoDecoder
  row 193; Coriolis `decData(2)`) and its copy-selection reproduces GDAC
  on 8/12 cells — better than the exact Coriolis-equivalent rule (6/12).
- The residual 4-cell ±1 difference cannot be reproduced from the
  available evidence by any documented rule. GDAC's values are genuine
  transmitted counts that are minorities in our copy set; the difference
  is most plausibly explained by INCOIS's received copy set / derivation
  differing from ours, but **the exact INCOIS aggregation algorithm has
  not been established** — we do not hold their ARGOS delivery or their
  processing chain, and we do not claim to have proven it.
- Confidence: **HIGH** that no code change is justified. The current
  implementation is supported by the available specification, Coriolis
  source, and telemetry evidence: it reads the correct byte, and adopting
  the exact Coriolis rule would change two currently-correct cells and
  reduce GDAC parity from 8/12 to 6/12 (net regression of 2).
- **No code change.** The Coriolis `round(mean)` rule must **not** be
  implemented: it is source-documented but demonstrably does not
  reproduce the INCOIS reference on our copy set, and would change two
  currently-matching cells for the worse. Part A's ABP emission remains
  unchanged.

**Evidence still missing (data, not code):** (1) INCOIS's actual received
ARGOS copy set and aggregation for these floats (would settle the rule);
(2) an early-life archive for one 091x15 float to enlarge the
GDAC-comparable ABP sample beyond 12 cells.

---

*Investigation only. No source, test, configuration, or generated NC file
was modified. The operator-provided bundle was used read-only.*
