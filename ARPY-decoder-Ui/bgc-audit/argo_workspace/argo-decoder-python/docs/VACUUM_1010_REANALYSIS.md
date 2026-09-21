# 1010 VACUUM RE-ANALYSIS

**Issue:** `PRESSURE_InternalVacuum_inHg` on the APF9 decoder-1010 family — GDAC publishes a frozen `-28.009` where our Part A decoder publishes the converted Message-3 VAC byte (−5.4…−6.3 inHg).

**Date:** 2026-08-17 · **Type:** investigation only — no source, test, or config file modified.
**Scope of evidence:** all six 1010 floats (2902201, 2902203, 2902206, 2902222, 2902223, 2902224), all raw telemetry in the workspace (41 transmissions, 649 message-3 copies), committed GDAC `_tech.nc` references, APF9A manual extracts, and the Coriolis MATLAB source fetched from the official GitHub repository (`euroargodev/Coriolis-data-processing-chain-for-Argo-floats`, branch `main`).

---

## 1. Specification evidence

**Message-3 layout — identical in both 1010-family manuals:**

`20131106_V110613_2361_rev20140814-Apex-User-Manual-APF9A.pdf` p.25 ("Data Message 3 – N"):

```
Byte(s) Mnemonic Description
0      CRC     Message CRC
1      MSG     Message ID ... will be a 2 for Data Message 2
2      VAC     The internal vacuum [counts] recorded when the park
               phase of the mission cycle terminated.
3      ABP     The air bladder pressure [counts] recorded just after
               each argos transmission.
4 - 5  PMT     The total length of time [seconds] that the pump motor
               ran during the current profile cycle.
Next, the hydrographic data are transmitted ... The sample taken at the
end of the park phase will be transmitted first ...
```

`20130904_V090413_2126.5b_rev20140207-Apex-User-Manual-APF9A.pdf` p.25: **byte-identical table** (VAC spec byte 2, ABP spec byte 3, PMT 4–5, park sample first).

The ApexCoDecoder spreadsheet extract (`xls_ApexCoDecoder__110613_090413.txt`, "Data #3" section rows 189–194) confirms the same byte mapping in the machine-readable format table: spec byte 03 → `VAC` (techId 1021, "Internal vacuum at end of Park phase"), byte 04 → `ABP` (techId 1022), byte 05 → `PMT` (techId 1023). The `Co Apex formats` extract shows the same VAC/ABP at spec bytes 03/04 of message 3 for the 110613/090413-family columns.

Since `payload` (our convention) excludes the CRC and MSG bytes, **spec byte 2 = payload byte 0**. This is exactly what Part A reads (`APF9_ENG_1010.msg3_vacuum_offset = 0`).

**Conversion formula — identical in both manuals:**

- 061810 manual p.28: `V = (Vraw * 0.293) - 29.767` with worked example `Vacuum 0x56 → Vraw = 86 → V ≈ -4.5 inHg`.
- 110613 manual p.28 (same section): `V = (V * 0.293) - 29.767 → -4.5 inHg` (86 counts).

**No sentinel/fill convention exists for VAC** in either manual — every 8-bit count converts linearly. There is no documented "6 counts" default anywhere in the 1010-family documentation.

## 2. Coriolis evidence (fetched from GitHub `main`)

**`decArgo_soft/soft/sub/sensor_2_value_for_apex_apf9_vacuum.m`** (25 lines, created 09/23/2015):

```matlab
function [o_value] = sensor_2_value_for_apex_apf9_vacuum(a_sensorValue)
o_value = a_sensorValue*0.293 - 29.767;
```

Identical to our `_VACUUM_SCALE_OFFSET = (0.293, -29.767)` and to the manuals.

**`decArgo_soft/soft/sub/decode_data_apx_10.m`** (decoder 1010), message-3 branch (lines ~783–860):

```matlab
elseif (msgNum == 3)
    % first item bit number
    firstBit = 17;
    % item bit lengths
    tabNbBits = [1 1 2 2 2 2]*8;        % VAC, ABP, PMT, park T, park S, park P
    decData = get_bits(firstBit, tabNbBits, msgData);
    ...
    dataStruct.label = 'Internal vacuum at end of Park phase';
    dataStruct.techId = 1021;
    dataStruct.value = num2str(sensor_2_value_for_apex_apf9_vacuum(decData(1)));
```

**Exact bit location:** `msgData = a_sensorData(idL, :)` with `msgData(1) = msgRed`, `msgData(2) = msgNum` (decode_data_apx_10.m:111–113). `get_bits` (fetched) is 1-based bit indexing over the row; `firstBit = 17` with bits 1–16 occupied by redundancy + message number ⇒ **decData(1) = the first payload byte = payload[0] = VAC**. This is the same byte Part A reads.

**Key behavioural facts from the Coriolis source:**
1. **VAC (techId 1021) is read from the redundancy-selected message's payload byte 0 and converted directly — no averaging, no default, no sentinel handling.** (Matches the ApexCoDecoder annotation: row 192 VAC has an empty aggregation column, unlike ABP.)
2. **ABP (techId 1022) is *averaged over all received copies*: `num2str(round(mean(tabBladPres)))`** — a genuine Coriolis rule we did not previously know, directly relevant to the ABP ±1 issue (Issue 2, not this task).

Coriolis therefore computes the vacuum exactly as Part A does. **No Coriolis code path produces −28.009 from any byte value that occurs in telemetry** (it would require decData(1) = 6).

## 3. Raw telemetry evidence — full archive scan

All 41 transmissions / 649 message-3 copies across the six 1010 floats were parsed with the in-repo frame parser (`split_transmission_text` + `iter_argos_messages_from_payload`, 31-byte frames, WRC CRC per `check_crc`). Per-copy VAC = `payload[0]`.

| Float | Files (cycles) | msg3 copies (CRC-ok / bad) | VAC counts, CRC-ok copies | VAC counts, CRC-bad copies | count 6 | count 0xFF |
|---|---|---|---|---|---|---|
| 2902201 | 358–360 | 78 / 0 | 82 (73×), 83 (5×) | — | **0** | **0** |
| 2902203 | 359–361 | 56 / 22 | 82 (56×) | 82 (14×), 114 (2×), 35 (8×) | **0** | **0** |
| 2902206 | 359–361 | 40 / 10 | 81 (25×), 82 (15×), 83 (2×) | 82 (1×), 114 (1×), 81 (8×) | **0** | **0** |
| 2902222 | 327–329 | 158 / 29 | 80 (151×), 83 (7×) | 80 (27×), 83 (2×) | **0** | **0** |
| 2902223 | 326–328 | 75 / 20 | 83 (75×) | 83 (14×), 123 (6×) | **0** | **0** |
| 2902224 | 325, 345 | 127 / 32 | 83 (127×) | 83 (32×) | **0** | **0** |
| **ALL** | | **534 / 113** | 80–83 | 80–83 (+corrupted 35/114/123) | **0** | **0** |

- **Count 6 occurs in exactly zero message-3 VAC bytes** — not in any CRC-valid copy, not in any CRC-bad copy, across all six floats.
- **0xFF also never occurs** at the VAC position (the documented filler byte is not used here).
- A positional scan of *every* byte of every message found no constant-6 byte in messages 1/2/3 that any decoder could be reading instead; value 6 does occur in other messages but only in **oceanographic/profile T/S data and battery-current bytes** (varying values, not a plausible vacuum source; also not constant).
- 11 of 41 transmissions contain no message 3 at all (short bursts) — but every *cycle* in our archive that GDAC also covers has complete CRC-valid message-3 copies (see §5). No partial/short message-3 payloads exist (all 31-byte frames, 0 short).
- VAC counts are per-float stable (80 for 2902222, 82 for 2902201/2902203, 81–82 for 2902206, 83 for 2902223/2902224) — a slowly drifting hull vacuum, physically the expected behaviour for a sealed APF9 hull (small leak over ~9 years: 2902223 went 81→83 counts between 2017 and 2026, per §6).

## 4. Concrete telemetry examples (overlap cycles — raw telemetry held, GDAC value published)

| # | Float / cycle | Raw file | msg3 copies (CRC-ok) | VAC counts (CRC-ok) | Our value | GDAC value |
|---|---|---|---|---|---|---|
| 1 | 2902222 / 327 | `152389_2025-12-25_2902222_327.txt` | 8 | 80 ×8 | −6.327 | **−28.009** |
| 2 | 2902203 / 360 | `152398_2026-01-05_2902203_360.txt` | 31 | 82 ×31 | −5.741 | **−28.009** |
| 3 | 2902223 / 327 | `152382_2026-01-05_2902223_327.txt` | 41 | 83 ×41 | −5.448 | **−28.009** |
| 4 | 2902224 / 345 | `152390_2026-07-20_2902224_345.txt` | 8 | 83 ×8 | −5.448 | **−28.009** |
| 5 | 2902206 / 359 | `152397_2025-12-31_2902206_359.txt` | 22 | 81 ×14, 82 ×6, 83 ×2 | −6.034/−5.741 | **−28.009** |

In every one of these cycles **every CRC-valid copy** carries 80–83 counts; the value 6 appears in **no copy at any byte offset that any documented layout reads as VAC**. The raw files are the float's own transmissions (PTT-matched, CRC-valid), so the transmitted value for these cycles is unambiguously 80–83 counts → −5.4…−6.3 inHg.

## 5. GDAC comparison — the complete picture

Fleet-wide distribution of GDAC `PRESSURE_InternalVacuum_inHg` (committed GDAC `_tech.nc` files):

| Float | GDAC rows | `−28.009` | non-frozen | empty |
|---|---|---|---|---|
| 2902201 | 350 | 349 | 1 (cyc 339: **−5.741**) | 0 |
| 2902203 | 374 | 366 | 0 | 8 (launch/prelude rows) |
| 2902206 | 361 | 361 | 0 | 0 |
| 2902222 | 348 | 344 | 4 (cyc 26/30/34/36: **−6.327**) | 0 |
| 2902223 | 347 | 341 | 3 (cyc 11/12: **−6.034**; cyc 156: **−5.448**) | 3 |
| 2902224 | 345 | 342 | 2 (cyc 288: **−5.741**; cyc 296: **−5.448**) | 1 |

**Overlap cycles where GDAC = −28.009 and we hold the raw telemetry: 14 cycles** (2902203: 359–361; 2902206: 359–361; 2902222: 327–329; 2902223: 327–329; 2902224: 325, 345). In all 14, every CRC-valid message-3 copy reads 80–83 counts.

**GDAC's own non-frozen values decode to exactly the counts we observe:**

| GDAC value | inverse conversion → counts | our observed counts |
|---|---|---|
| −6.327 | (29.767−6.327)/0.293 = **80.000** | 80 (2902222, incl. 2026 telemetry) |
| −6.034 | … = **81.000** | 81 (2902223 early life; 2902206) |
| −5.741 | … = **82.000** | 82 (2902201, 2902203, 2902224@288) |
| −5.448 | … = **83.000** | 83 (2902223, 2902224, incl. 2026 telemetry) |
| **−28.009** | … = **6.000** | **never transmitted** |

All four non-frozen GDAC values are exact integer-count inversions within the transmitted range, and the 2902223 series (81 at 2017 → 83 at 2019 → 83 at 2026) is monotone with a slowly leaking hull. GDAC's file therefore contains, on the same floats, both (a) correct decodes of the very byte we read and (b) the frozen −28.009 constant elsewhere. GDAC's own fill convention for an absent value is an **empty string** (the masked-cycle prelude rows), not −28.009 — so −28.009 is a *computed* value, not a "missing" marker.

## 6. Count-6 investigation — verdict

1. **Does count 6 occur in transmitted telemetry?** At the message-3 VAC byte: **never** (0/649 copies, CRC-valid and CRC-bad, all six floats). Byte value 6 does occur in other bytes of other messages (profile T/S/P data — normal ocean values — and battery-current bytes), but at no position any documented layout or the Coriolis source reads as VAC, and at no constant position.
2. **Does count 6 occur only in non-selected/invalid copies?** It does not occur at the VAC byte in *any* copy, selected or not, valid or not.
3. **Or never?** Never — at the VAC byte.
4. **Evidence sufficiency:** sufficient. −28.009 = 6 counts under the only documented conversion; 6 counts is not transmitted; therefore −28.009 is not a decoded value of any transmitted message on any of these floats.

**Physical cross-check (supporting, not primary):** −28.009 inHg ≈ 0.064 atm absolute — a near-perfect vacuum that would require the sealed hull to become ~12× more evacuated over the mission (measured values sit at 0.78–0.81 atm absolute). The APF9 has no mechanism that evacuates the hull; the measured series moves the *other* way (vacuum slowly relaxes). A bit-identical −28.009 on 342–366 consecutive cycles per float (≈9 years) is not a measurement.

## 7. Classification

| Question | Answer |
|---|---|
| Is −28.009 a legitimate transmitted/decoded value? | **No.** Count 6 is never transmitted at the VAC byte; −28.009 cannot be produced from any transmitted copy under the documented conversion or the Coriolis algorithm. |
| Is it a GDAC processing/default/fill artefact? | **Effectively proven to be one.** GDAC's own empty-string fill for absent values shows −28.009 is a *computed* constant; its sporadic correct values (10 cells on 4 floats, all matching our decode exactly) show GDAC *does* decode the real byte on some cycles and defaults elsewhere. The precise INCOIS mechanism (stored default of 6 counts in their DB/chain, a constant substitution, or a later processing pass) is **not determinable from public evidence** — but the value's non-telemetry origin is. |
| Is it an unknown GDAC-side algorithm? | The *mechanism* is unknown; the *origin* (not the float) is established. |
| **Final classification** | **NOT FIXABLE — as a parity match.** Our decoder already implements the specification- and Coriolis-correct decode. The 12-cell divergence from GDAC is a GDAC-side artefact that must not be reproduced. |
| Confidence | **HIGH** — specification (two manuals + spreadsheet), Coriolis source (conversion + bit position + algorithm), raw telemetry (649 copies), and GDAC's own internal consistency all agree. |

## 8. Is any code change justified?

**No.** Precisely because:

1. **Reproducing GDAC would require fabricating source information.** Matching −28.009 means emitting counts=6, which no transmitted message contains. The project rules forbid inventing source information to reproduce GDAC, and Part A's whole justification (and the ABP case before it) rested on "the GDAC value matches no byte in the message".
2. **Our value is the specification- and Coriolis-correct decode.** Manual p.25 (both 1010-family revisions) defines payload byte 0 as VAC; both manuals and `sensor_2_value_for_apex_apf9_vacuum.m` define `V = counts×0.293 − 29.767`; `decode_data_apx_10.m` reads `decData(1)` = payload byte 0 of the redundancy-selected message with no averaging. Part A reproduces Coriolis exactly, offset for offset.
3. **GDAC itself publishes our values.** 10 cells across 4 floats show GDAC's own correct decodes identical to ours (bit-for-bit, including the same conversion). Our value set is a subset of GDAC's own value set — we are not introducing an alien representation.
4. **Withholding would regress.** Removing `PRESSURE_InternalVacuum_inHg` from 1010 output would reopen the parameter-count gap against GDAC (14 names vs 12) that Part A deliberately closed, and would hide a real transmitted measurement.

**If a change were nonetheless requested** (not recommended, and **not implemented here**), the exact minimal change would be: delete nothing; leave `_VACUUM_SOURCE_ATTRS[1010] = "msg3_vacuum_counts"`, `_VACUUM_SCALE_OFFSET`, and the emission branch untouched. There is no defensible minimal change — any change moves away from spec/Coriolis/telemetry.

## 9. Part A implementation status

**The current Part A implementation must remain unchanged.** It reads the correct byte (message-3 payload byte 0, `msg3_vacuum_offset = 0`), applies the correct conversion ((0.293, −29.767)), emits the correct INCOIS label (`PRESSURE_InternalVacuum_inHg`), matches Coriolis's `decode_data_apx_10.m` decData(1) exactly, and reproduces GDAC's own real values wherever GDAC has them.

## 10. Recorded findings for later (no action now)

1. **Issue-2 lead (ABP ±1):** Coriolis's techId 1022 is `round(mean(ABP over all received copies))` — a real, documented averaging rule. Our modal-copy emission cannot reproduce it from our copy set (GDAC's copy set differs from ours; round-mean over our copies still differs from GDAC on 8 of 12 cells). Next investigation should quantify whether any copy-set/selection variant closes the gap; expect it to remain a copy-set limitation. **Not part of this task — recorded only.**
2. **Documentation debt (when reports are next updated):** record the −28.009 finding in `APF9_PARITY_STATE.md` (1010 vacuum row: class "PROVEN GDAC-side artefact — approved divergence", evidence pointer to this file) and add the missing Part A entry to `IMPLEMENTATION_PROGRESS.md`. Not done now, per instructions.
3. The Coriolis files cited here (`decode_data_apx_10.m`, `sensor_2_value_for_apex_apf9_vacuum.m`, `decode_apx_argos.m`, `get_bits.m`) are **not in the workspace Coriolis snapshot**; they were fetched from GitHub `main` (2026-08-17). If the snapshot is ever updated, the line numbers (§2) should be re-verified.

---

*Investigation only. No source, test, configuration, or state document was modified.*
