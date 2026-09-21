# Post-START_DATE parity investigation — Parts 1 & 2 (complete)

**Audit only. No code changed.** Suite 1722 passed, ruff clean, `mypy --strict`
clean. Code verified unchanged (`TRANSMISSION_GAP_HOURS = 6.0`,
`GROUNDED_PRESSURE_MARGIN_DBAR = 100.0`, `_cycle_one_start_date` present).

Validation set: the **full decodable APF9 fleet** (10 floats), with deeper
work on 2902203/2902206/2902222/2902223. Metadata: corrected four-CSV only.
GDAC re-fetched and used **only** as cross-check.

---

## Final answer

**No genuine decoder bug remains.** Every remaining difference is explained by
incomplete telemetry, delayed-mode reference data, operator metadata, a
published convention, or a GDAC defect we correctly decline to copy.

Two findings actively **reverse earlier suspicions**:

* **C2 is not a modelling error.** Where the archive contains cycle 1, our
  schedule chain reproduces GDAC to **0.0 s on all 8 timing fields × 23
  cycles**. It is purely an *anchor* limitation.
* **The Rtraj "LAT/LON differences" from Part 1 were an artefact of my own
  comparison** (positional pairing). Matched by timestamp, **266/266 fixes are
  bit-identical**, including all 234 on 2901304.

---

## Fleet-wide summary

| measure | result | note |
|---|---|---|
| Science cells | **49 168 / 49 287 (99.76 %)** | **0 true mismatches** |
| N_MEASUREMENT rows compared | 732 | keyed on `(cycle, MC)` |
| — `PRES` | **732 / 732 (100 %)** | |
| — Argos fixes matched by time | **266 / 266 identical** | lat/lon/accuracy |
| — `JULD` @1 ms | 663 / 732 | all 69 explained below |
| QC cells | 49 007 / 49 287 (99.43 %) | all delayed-mode or fill-related |
| Technical cells | 5 133 / 5 142 (99.82 %) | |
| meta variables | 614 / 630 (97.46 %) | |
| GROUNDED · DATA_MODE | **35/35 · 35/35** | |
| Measurement-code sets | **no MC missing or extra** | any float |
| 2901304 (only float with full fmt-3.1 overlap) | **536/536 rows exact on every field** | |

---

## Classified findings

### 🟢 Expected / correct

| item | evidence |
|---|---|
| **Schedule chain fill on 5 mid-mission floats** (12 cells each) | `STATUS='9'` = *"not immediately known"* (UM table 19). Coriolis's `process_trajectory_data_apx_argos.m` assigns **0** of these 7 fields; the PROVOR builder assigns them. **We already exceed the reference.** SOURCE CONFIRMED |
| **Schedule accuracy where cycle 1 exists** | 2901304: `DESCENT_START`, `PARK_START`, `PARK_END`, `TRANSMISSION_END`, `ASCENT_END`, `TRANSMISSION_START`, `FIRST_MESSAGE`, `LAST_MESSAGE` — **median and max \|Δ\| = 0.0 s over 23 cycles** |
| **`*_ADJUSTED` all fill** | UM §2.2.5 line 1215: *"When a profile has DATA_MODE='R' … the adjusted section should be filled with FillValue."* GDAC's own R-mode profiles do the same (0/59 filled). SOURCE CONFIRMED |
| **HISTORY steps `ARFM` + `ARGQ` only** | Coriolis writes **zero** `ARCA`/`ARUP` anywhere in the chain. UM table 12: `ARCA` = calibration performed, `ARUP` = archived and sent to GDAC — DAC actions we do not perform. SOURCE CONFIRMED |
| **`START_DATE` fill on 5 floats** | by design; UM §2.4.9 does not list it as mandatory |
| **119 extra science cells** | every level we publish is CRC-valid telemetry |

### ⚪ GDAC-specific — must NOT be reproduced

| item | evidence |
|---|---|
| **MC 0 (launch) JULD off by exactly `2433282.5`** on **7 floats** | `2433282.5` is the 1950 epoch as an astronomical Julian Day — GDAC never subtracted it. **Our value equals `LAUNCH_DATE` exactly** on every float checked. GDAC is defective here. SOURCE CONFIRMED |
| QC `4/3 → 1/3` (191 cells, 5 floats) | every affected float is `DATA_MODE='D'` in GDAC (2901304 D×20, 2901305 D×27, 2901328 D×92, 2901350 D×301); ours correctly `'R'` |
| QC `9 → 1` (89 cells, 2 floats) | overlap is **exact** (10/10, 10/10, 19/19): every GDAC `9` sits on a level GDAC left as fill and we recovered. Table 2: `9` = missing value |
| GDAC `ARCA`/`ARUP` history rows | see above |

### 🟡 Explained, no action

| item | evidence |
|---|---|
| **`JULD` @1 ms 663/732** | the 69 are: 7 × MC 0 (GDAC's JD defect), ~48 × MC 290/296/600/700 fill-vs-value on mid-mission floats (C2), and the rest sub-minute reference-instant. No case where both sides hold a value that disagrees materially |
| **Argos fix count differs** (17 only-GDAC, 18 only-ours) | traced to raw telemetry on 2902222 cycle 327: of GDAC's 11 fixes, **7 are in our raw files and we emit all 7 identically**; the other 4 are absent from every raw file we hold. Conversely **23/23 fixes we publish are present in the raw telemetry** — we invent nothing |
| `JULD_ASCENT_END` +499…712 s on mid-mission floats | float RTC drift; **0 s** when the archive starts at cycle 1 |
| Vacuum (7 cells), `FLAG_*` (2 cells) | unchanged from the previous investigation |

### 🟠 / 🔴 Potential or confirmed decoder issues

**None.**

### P2 — documentation only (no output effect)

`platforms/apex_argos/trajectory.py:420-424` states the clock gains
*"4.944 s every cycle"*. Measured: `4.944 × 359 = 1775 s` predicted vs **499 s**
observed; ratio spans **0.28–0.45** across the four 1010 floats. Direction is
right, rate is unsupported. **Classified as a documentation issue** — do not
alter timing logic. STRONG INFERENCE.

---

## Answers to the closing questions

1. **Remaining genuine decoder bugs?** No.
2. **Still faithful to Coriolis?** Yes — and on three counts we do *more*:
   populating `ASCENT_END`/`TRANSMISSION_START`, deriving `GROUNDED`, and
   emitting a correct MC 0.
3. **Consistent with the manuals?** Yes: UM §2.2.5 (adjusted fill), table 12
   (history steps), table 19 (status flags), table 2 (QC), §2.4.9 (optional
   metadata).
4. **Anything scientifically dangerous?** No. Science is 100 % on every
   comparable cycle; `PRES` is 732/732 across all trajectory rows.
5. **Could anything cause GDAC rejection?** Nothing identified. All emitted
   values are spec-legal; fills are permitted where used.
6. **What should be fixed?** No code. Two *data* requests (below), plus the
   optional P2 comment tidy.
7. **What should NOT be changed?** Schedule fill with `STATUS='9'`; extra
   recovered levels and their `QC=1`; real-time QC severity; `*_ADJUSTED` fill;
   history steps; MC 0; vacuum offset/scaling; `FLAG_*` padding;
   `FIRMWARE_VERSION` zero-padding; `START_DATE` fill.
8. **Are C2/C3 real bugs?** **No — acceptable behaviour.** C2 is an anchor
   limitation, not a modelling error (0.0 s accuracy when cycle 1 is present),
   and Coriolis populates none of those fields for this family. C3 is a
   reference-instant convention.
9. **New systematic problems across the wider fleet?** None. The one new
   *systematic* observation is GDAC's MC 0 defect on 7 floats, which is theirs.

---

## Recommended next step — data, not code

1. Ask the operator for the **`start date`** column (moves 5 floats to
   precedence rule 1, matching Coriolis) and restoration of **`end mission
   date`** (closes 3 cells).
2. Obtain an **early-life archive for one 091x15 float**. Every 1010 float we
   hold starts at cycle 327+; one early archive would close C2, C3 and the
   drift-rate question simultaneously and is the single highest-value dataset
   we could add.
3. Optional: soften the §P2 comment next time that file is edited.

---

## Method note / correction

Part 1 reported "LAT/LON diffs" and `POSITION_ACCURACY` diffs on MC 703.
Part 2 shows those were an **artefact of comparing fix lists positionally**
when the two sides hold different numbers of fixes. Re-keyed on timestamp,
**every co-observed fix is identical (266/266)**. The genuine finding is a
difference in *which* fixes each side holds, fully explained by the raw files.
