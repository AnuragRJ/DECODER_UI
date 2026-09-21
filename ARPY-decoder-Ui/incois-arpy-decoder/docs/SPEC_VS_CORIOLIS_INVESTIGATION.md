# Spec vs Coriolis vs our decoder — investigation of the remaining baseline issues

**Investigation only. No code changed.**

Method, applied to every item:

```
RAW TELEMETRY → APF9 meaning → Argo specification → Coriolis implementation
              → our Python implementation → GDAC output
```

Coriolis is treated as a *reference implementation*, not as the specification.
GDAC is treated as a cross-check, not as ground truth.

Primary sources used:

* Argo User Manual **v3.3** (`argo_user_manual_v3.3a.pdf`), §2.4 `meta.nc` tables
* Coriolis MATLAB source (`euroargodev/Coriolis-data-processing-chain-for-Argo-floats`)
* APF9A **FormatNotes** (`20070718_V071807-Apex-User-Manual_APF9A-Ido-071807.FormatNotes.txt`)
* Raw ARGOS telemetry for the 10 decodable floats

---

## Summary of conclusions

| # | Item | Verdict on our code | Class | Confidence |
|---|---|---|---|---|
| 1 | `START_DATE` | **INCORRECT** — violates the manual's definition | A: decoder bug | **SOURCE CONFIRMED** |
| 2 | `END_MISSION_STATUS` | **Defensible but unsourced** | B: metadata | **STRONG INFERENCE** |
| 3 | `PRESSURE_InternalVacuum_inHg` | **Correct** (offset + formula) | F: unresolved data | **SOURCE CONFIRMED** for our logic |
| 4 | `FLAG_ProfileTermination_hex` — 2901328 cyc85 | **Cosmetic only** | C: GDAC-specific | **SOURCE CONFIRMED** |
| 5 | `FLAG_ProfileTermination_hex` — 2901305 cyc27 | **Arguably wrong tie-break** | F: unresolved | **STRONG INFERENCE** |

Only item 1 is a genuine decoder defect. **Correction to the previous
baseline:** I earlier reported both `FLAG_*` cells as "genuine value
differences". That was wrong for 2901328 — see item 4.

---

## 1. `START_DATE` — our implementation is incorrect · **SOURCE CONFIRMED**

### The specification says
**Argo User Manual v3.3, §2.4 `meta.nc`, lines 3897-3906:**

> `START_DATE:long_name = "Date (UTC) of the first descent of the float"`
> *"Date and time (UTC) of the first descent of the float. Format:
> YYYYMMDDHHMISS"*

A **deployment property**, fixed for the life of the float.

### What Coriolis does
`create_nc_meta_file_3_1.m:2696` carries the identical `long_name`. Crucially,
Coriolis **never computes it**. A fleet-wide grep for `START_DATE` outside
variable-definition code finds only 1:1 field mappings in the
`generate_json_float_meta_*` family, e.g. the APEX-Argos one at
`generate_json_float_meta_apx_argos_.m:1015`:

```matlab
'START_DATE', 'START_DATE', ...
```

i.e. it is copied straight from the operator database into the float's JSON
metadata, and `create_nc_meta_file_3_1.m:2974-2983` merely reformats it
alongside `LAUNCH_DATE`, `STARTUP_DATE` and `END_MISSION_DATE`.

Confirmed in real Coriolis metadata shipped with the repository
(`decArgo_config_floats/json_float_meta_argos/6902687_meta.json`):

```
LAUNCH_DATE = '28/05/2016 12:54:00'
START_DATE  = '28/05/2016 21:45:00'      # ~9 h later, from the operator DB
```

### What we do
`platforms/apex_argos/decoder.py:114` `_first_cycle_start_date()` returns
*"`YYYYMMDDHHMMSS` of the earliest decoded cycle's JULD"* — the earliest cycle
**in the current run**.

### Why that is wrong
The value depends on which files happen to be decoded. A three-file archive
starting at cycle 327 yields a 2025 date for a float deployed in 2017. A
deployment fact must not move with the input set.

Measured against GDAC on 10 floats — wrong on **8**:

| WMO | GDAC | ours | error |
|---|---|---|---|
| 2902206 | 2016-03-13 04:42 | 2025-12-31 13:04 | **+9.8 yr** |
| 2902201 | 2016-03-07 11:28 | 2025-12-25 12:55 | **+9.8 yr** |
| 2902203 | 2016-03-08 12:27 | 2025-12-26 15:55 | **+9.8 yr** |
| 2902222 | 2017-01-21 04:26 | 2025-12-25 07:34 | **+8.9 yr** |
| 2902223 | 2017-01-21 20:38 | 2025-12-26 00:21 | **+8.9 yr** |
| 2901350 | 2012-02-08 11:09 | 2012-01-29 10:08 | −10.0 d |
| 2901339 | 2011-12-27 21:30 | 2011-12-17 21:39 | −10.0 d |
| 2901328 | 2011-09-04 12:19 | 2011-08-30 10:59 | −5.1 d |

2901304 and 2901305 are correct **only because their archives start at
cycle 1**.

### Is GDAC's value itself derivable?
Not from anything we hold, and this matters for the fix:

* `START_DATE − LAUNCH_DATE` ranges from **16.6 h to 264 h** across the fleet —
  no constant, and not the 6 h `CONFIG_MissionPreludeTime_hours` all these
  floats carry.
* `START_DATE` equals the JULD of GDAC's own **cycle 1** *exactly* on 2901304,
  2902201, 2902203, 2902206, 2902222, 2902223 (0.00 h), and within 0.6–6.8 h
  on the four DPF floats — consistent with the separate C3 profile-JULD anchor
  question rather than a different rule.
* GDAC publishes `START_DATE_QC = '1'` ("seems correct") throughout.

So GDAC's value behaves like *first descent ≈ cycle 1*, which agrees with the
manual. It is **not** reproducible from `LAUNCH_DATE` plus configuration.

### Where the specification and Coriolis differ
They do not conflict — but Coriolis **sources** the field rather than deriving
it, and our four-CSV backend has **no `start date` column** (verified: 31
columns, none of them a start date). We therefore cannot follow Coriolis's
approach with the metadata we are given.

### Proposed fix (not implemented)
Emit `START_DATE` **only when the decoded run actually contains cycle 1**;
otherwise leave the `_FillValue`. Rationale:

* it satisfies the manual — cycle 1's descent *is* the first descent;
* it removes the archive-window dependence, which is the actual defect;
* it never publishes a value we cannot justify.

This makes 2901304/2901305 keep their current exact values, and turns the
eight wrong values into honest fill. Adding a `start date` column to the
operator sheets would be the fuller fix and would match Coriolis exactly.

**Severity: HIGH** — a wrong deployment date is a data-integrity problem and
is the kind of field a GDAC consistency check inspects.

---

## 2. `END_MISSION_STATUS` — defensible, unsourced · **STRONG INFERENCE**

We publish `T` on 2901339, 2901350, 2902201, 2902206; GDAC leaves them blank.

**Manual (v3.3 lines 3993-4003):** `conventions = "T:No more transmission
received, R:Retrieved"`. No rule is given for *when* a DAC must set it.

**Coriolis:** defines the variable (`create_nc_meta_file_3_1.m:2748`) and
sources it from metadata; it does not derive it.

Our `T` is driven by the sheet's `Status` column marking these floats dead,
which is a truthful reading of `T` ("no more transmission received"). GDAC's
blank is equally permissible. **Not a bug**; it is a policy choice about
whether the operator's `Status` column should populate this field. Worth an
explicit decision, not a fix.

---

## 3. `PRESSURE_InternalVacuum_inHg` — our decoding is correct · **SOURCE CONFIRMED**

7 cells across 2901305 and 2901328.

**APF9A FormatNotes, data message #1, line 143:**

```
11        VAC    The internal vacuum [counts] recorded when the park
                 phase of the mission cycle terminated.
```

**Coriolis** `sensor_2_value_for_apex_apf9_vacuum.m:23`:

```matlab
o_value = a_sensorValue*0.293 - 29.767;
```

**Ours** `engineering.py:447` reads `payload[9 + shift]`; the payload excludes
the 2-byte CRC+MSG header, so payload 9 = **frame byte 11** — verified
directly (`raw[11] == payload[9]` on every copy). The scaling constants are
identical to Coriolis.

**So both the offset and the formula match the manufacturer's notes and the
reference implementation.** The disagreement is in the *counts*, and the raw
telemetry shows why. For 2901328 cycle 8 (`102507_2011-10-09.txt`), the four
CRC-valid copies of message 1 carry:

```
copy0 VAC=1   copy1 VAC=254   copy2 VAC=0   copy3 VAC=254
```

Majority → 254 → `+44.655 inHg`. GDAC's `−25.665` implies counts **14**,
which **appears in none of the CRC-valid copies**. Inverting all seven cells
gives GDAC counts of exactly 14 on every 2901328 case — a single repeated
value across cycles 8, 51, 61, 70, 72, which does not look like a per-cycle
measurement either.

**Verdict:** our value is the honest majority of the CRC-valid telemetry we
hold. The byte is genuinely unstable on this float (values 0, 1, 254 within
one transmission). GDAC's 14 is not reproducible from our frames.
**Class F (unresolved)** — do not change the decoder to match it. 7 cells of
5 142 (0.14 %).

---

## 4. `FLAG_ProfileTermination_hex`, 2901328 cycle 85 — cosmetic · **SOURCE CONFIRMED**

**This corrects my previous baseline entry**, which called it a value
difference.

All **7** CRC-valid copies agree on `STATUS = 0x001D`. GDAC prints `01D`; we
print `1D`. **Same number, different text width.**

Our `format_termination_flag()` (`nc/technical.py:349`) pads to two hex
digits. Checking GDAC's own output fleet-wide shows its formatting is
**internally inconsistent**:

```
'01' x1658   '0D' x1     '01D' x1
'801' x518   '615' x51   'A01' x46   '201' x120   '84D' x1
```

`01D` is padded to 3 digits while `801`, `615`, `A01`, `84D` are not, and
`0D` is padded to 2. There is no width rule to follow — `01D` is a one-off.
Fleet totals: **value-equal 365/366, text-equal 364/366.**

**Class C (GDAC-specific).** Not a defect. Do not chase it.

---

## 5. `FLAG_ProfileTermination_hex`, 2901305 cycle 27 — real ambiguity · **STRONG INFERENCE**

The only remaining genuine value disagreement in the technical file.

Raw telemetry, 17 CRC-valid copies of message 1:

```
STATUS = 0x0001 x9      STATUS = 0x0601 x8
```

A near-even split. We select `0x0601` (published `601`); GDAC has `0x0001`
(`01`), which is the **majority by one copy**. The differing bits are
`0x0600` = bits 9 and 10 = `Sbe41PFail` (0x0200) and `Sbe41PtFail` (0x0400)
per the FormatNotes status table.

Our whole-frame redundancy selector picks the largest identical group, then
breaks ties on reception time; the status word is deliberately **excluded**
from the per-byte majority path (`_MAJORITY_BYTE_OFFSETS` covers the analogue
channels 9 and 18-25 only), with the documented reason that it is a flag word
rather than a re-sampled analogue channel.

Coriolis's own selector (`decode_apex_cycle_number` / redundancy handling)
also works on whole frames, so this is not a Coriolis-vs-us divergence — it
is a coin-flip on this particular transmission.

**Class F (unresolved).** 1 cell of 5 142. I would **not** change the
tie-break on this evidence: a 9-vs-8 split is not a rule, and switching to a
per-byte majority for the status word would alter a flag field on every
float to fix one cell.

---

## What must not change

1. **`PRESSURE_InternalVacuum_inHg`** — offset and formula are confirmed
   against both the APF9A FormatNotes and Coriolis. The residual is unstable
   telemetry.
2. **`FLAG_ProfileTermination_hex` padding** — GDAC's own widths are
   inconsistent; there is no convention to adopt.
3. **The status-word redundancy rule** — one ambiguous cell is not evidence.
4. Everything already classified in `POST_C1_FLEET_BASELINE.md` §"Confirmed
   correct": extra recovered levels, cycle 0, delayed-mode QC diffs, Rtraj
   schedule fill with `STATUS='9'`, `FIRMWARE_VERSION` zero-padding.

## Recommended next action

Fix **`START_DATE`** only (item 1) — it is the single item where our output
contradicts the Argo User Manual. Items 2-5 are either policy choices or
irreducible telemetry ambiguity, together accounting for 8 cells out of
5 142 technical and 19 of 630 metadata values.
