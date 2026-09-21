# 1005 internal-vacuum parity — investigation (read-only)

**Date:** 2026-08-19 · **No source/test/config/output modified.**
**Issue:** `PRESSURE_InternalVacuum_inHg` differs from GDAC in 7 cells
(2901328 ×5, 2901305 ×2). Prior classification: UNKNOWN.

---

## 1. Specification (061810 manual)

- **Test Message 1** table (p.18): spec byte 14 = `VAC` "Vacuum measured
  during self tests [counts]" — a **self-test** field, not the mission
  value.
- **Data Message 1** table (p.20): **no VAC field at all.** Bytes 9–10 =
  `SP` surface pressure (2 bytes), byte 11 = `CP` current pressure, 12 =
  SPP, 13 = PPP2, 14 = ppp.
- Conversion (p.23): `V = (Vraw * 0.293) - 29.767`, worked example
  86 → −4.5 inHg.
- **Implication:** the only *internal-vacuum* quantity the APF9 defines
  for the mission is in the **auxiliary engineering block** ("Internal
  vacuum at end of Park phase", ApexCoDecoder 061810 row 232, techId
  1024) — not in Data Message 1. The message-1 "vacuum" byte our code
  reads at `payload[9]` is actually the **second byte of the SP surface
  pressure** word (a pressure, not a vacuum).

## 2. Coriolis 1005 (`decode_data_apx_1_5.m`)

- The only vacuum tech parameter Coriolis emits for 1005 is **techId
  1024 "Internal vacuum at end of Park phase"**, from the **auxiliary
  block** `decData(3)` (after PDIVMAX 2B + TPI 2B), guarded by
  `receivedData(3)==255` (fill). Conversion identical.
- Coriolis does **not** emit any message-1 "vacuum" for 1005.

## 3. Current Python

- `_VACUUM_SOURCE_ATTRS[1005] = "vacuum_counts"` = **message-1
  `payload[9]`** (the SP second byte), converted with the same formula.
- `park_end_vacuum_counts` (the aux-block VAC — Coriolis's source) is
  decoded but **not published** for the 1005 family.
- **This is a source divergence from Coriolis** for the *field* (we read
  the SP byte; Coriolis reads the aux VAC). However: **no 2901328 or
  2901305 cycle has any aux VAC at all** (`park_end_vacuum_counts` is
  None on every cycle of both floats — verified), so Coriolis's techId
  1024 would be **empty** for these floats; GDAC's values cannot come
  from the aux block either. The message-1 byte is the only vacuum-like
  value in the telemetry, and it is what GDAC's values trace to (see §4).

## 4. Raw telemetry — the 7 cells + fleet context

`message-1 payload[9]` (= our source) per cell, CRC-valid copies:

| WMO | cyc | our value | GDAC | our p9 counts | GDAC-implied count | in raw? |
|---|---|---|---|---|---|---|
| 2901328 | 8 | 44.655 | −25.665 | {254:4} | **14** | **NO** |
| 2901328 | 51 | 44.655 | −25.665 | {0:2, 254:5} | **14** | **NO** |
| 2901328 | 61 | −29.767 | −25.665 | {0:3, 1:1, 254:2} | **14** | **NO** |
| 2901328 | 70 | 44.655 | −25.665 | {0:2, 1:1, 254:5} | **14** | **NO** |
| 2901328 | 72 | 44.655 | −25.665 | {0:1, 254:7} | **14** | **NO** |
| 2901305 | 21 | 43.776 | 43.19 | {249:4, 250:4, 251:5, 252:1} | **249** | **YES** (×4, not modal) |
| 2901305 | 27 | 39.088 | 43.776 | {235:8, 252:7, 253:2} | **251** | **NO** |

**Fleet-wide 2901328 analysis (117 cycles with GDAC vacuum):** GDAC's
values are almost all `44.655` (254) or `−29.767` (0) — exactly the
message-1 `payload[9]` sentinel bytes — but the implied count **fails to
match the modal byte on 28 cycles** in both directions (GDAC picks 254
when 0 dominates, and 0 when 254 dominates), and the **5 `−25.665` cells
imply count 14, which appears in no copy of any of those cycles**.
GDAC follows **no consistent selection rule**: first-copy 71/117,
last-copy 75/117, majority 89/117 — none reproduces it.
2901305: PRF21 implied 249 exists but is not modal; PRF27 implied 251 is
absent.

## 5. Reverse-GDAC

- `−25.665` ⇔ count **14**: absent from every raw copy of all 5 cells.
  **GDAC-side value with no telemetry basis** (like the 1010 `−28.009`).
- `43.19` ⇔ 249 (2901305/21): present (×4) but not modal — a
  copy-selection difference, unreproducible by any documented rule.
- `43.776` ⇔ 251 (2901305/27): absent.
- Matching cells (e.g. 2901328 cyc 4/7/9–13, 44.655⇔254 modal) confirm
  the message-1 byte is the quantity both sides read; the disagreements
  are selection choices on mixed-copy cycles plus the count-14 anomaly.

## 6. Selection hypotheses (tested)

| rule | 2901328 match rate (117 cyc) |
|---|---|
| modal (ours) | 89/117 |
| first CRC-valid copy | 71/117 |
| last CRC-valid copy | 75/117 |
| Coriolis aux-VAC (techId 1024) | **0/117** (no aux VAC exists on these floats) |

No documented rule reproduces GDAC. The count-14 cells are unreproducible
from telemetry under any rule.

## 7. Classification

| WMO | cyc | class | evidence |
|---|---|---|---|
| 2901328 | 8, 51, 61, 70, 72 | **NOT FIXABLE — GDAC/reference discrepancy** | GDAC −25.665 ⇔ count 14; count 14 absent from every raw copy (all CRC-valid and invalid) |
| 2901305 | 21 | **NOT FIXABLE — missing reception/copy-set evidence** | GDAC 249 exists (×4) but is not modal; no rule (first/last/majority/aux) selects it |
| 2901305 | 27 | **NOT FIXABLE — GDAC/reference discrepancy** | GDAC 251 absent from all copies |

**Fleet-level conclusion:** the 1005 vacuum discrepancy is **not a
decoder error**. (a) The field both sides read is the message-1 `SP`
second byte (our `payload[9]`); the manual's only true vacuum is the aux
block, which is **absent on these floats** (Coriolis techId 1024 would be
empty). (b) Our modal selection is the most defensible rule (89/117 best
of all candidates); GDAC follows no consistent rule on mixed-copy cycles.
(c) Six of the seven cells are **GDAC-side values whose implied counts
are absent from the telemetry** (count 14 ×5, count 251 ×1) — the same
class as the approved 1010 `−28.009` divergence; one cell (2901305/21) is
a copy-selection difference with no reproducible rule. **Scientific
correctness favors keeping our modal message-1 value.** Changing the
source to the aux VAC would be wrong (no aux VAC exists); changing the
selection rule to match GDAC would be curve-fitting.

## 8. Additional evidence needed (if the issue must be closed further)

1. **INCOIS's actual 1005 processing chain** (the code/algorithm that
   produced their `_tech.nc` vacuum column) — would confirm whether the
   erratic 254/0 choices and the count-14 values are a specific copy or
   a stored/default artifact.
2. **The full 2901305/2901328 ARGOS delivery** (all receptions INCOIS
   received, including any our archive lacks) — would settle whether
   counts 14/251 ever existed on their side.

*No file was modified. Evidence retained: this report.*
