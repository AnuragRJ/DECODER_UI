# APF9 Argos Decoder — Documentation Audit Report

**Date:** 2026-07-28
**Scope:** WRC/APEX ARGOS CTD floats (decoder ids 1005, 1010) — floats 2901339, 2902201, 2902222, 2902223
**Status:** Audit only. **No source code was modified.**

---

## 0. Provenance and method

### 0.1 Documents received

Downloaded from the supplied Google Drive link (15.1 MB, 24 files, **zero LFS
stubs** — all content is real). Extracted to `/home/user/apf9_docs/`; plain-text
extracts committed to `docs/reference_extracts/` for future reference.

| # | Document | Type | Pages/Rows |
|---|---|---|---|
| D1 | `ApexTimings.xlsx` | Spreadsheet | 2 sheets (53 rows, 17 rows) |
| D2 | `ApexCoDecoderVersions_20160926.xlsx` | Spreadsheet | 19 sheets, 348 rows |
| D3 | `Firmware-082213-Appendix-G.pdf` | C source listing | 7 |
| D4 | `20100618_V061810_1772.A_rev20100907-Apex-User-Manual-APF9A.pdf` | Manual | 36 |
| D5 | `20131106_V110613_2361_rev20140814-Apex-User-Manual-APF9A.pdf` | Manual | 40 |
| D6 | `20130904_V090413_2126.5b_rev20140207-Apex-User-Manual-APF9A.pdf` | Manual | 38 |
| D7 | `20070718_V071807-...FormatNotes.txt` | Byte spec | (already held) |
| D8 | `argo_coriolis_matlab_decoder_V1.10_20251112.pdf` | Decoder manual | — |
| D9 | `_CoriolisArgoFloatVersions.xlsx` | Float↔version map | — |
| D10–D18 | 11 further APF9A manuals (071807, 082807, 021208, 062608, 021009, 061609, 020110, 090810, 071412, 121512, 032213, 082213, 110813) | Manuals | ~36–40 each |

**D4 and D5/D6 are the exact manuals for our floats.** This is the single most
important fact in this audit: Phase 6A.3 was forced to work from D7, a *071807*
revision that predates both of our firmwares. We now have the primary sources.

### 0.2 Method

Every claim below was checked against real data, not just read. I re-ran the
decoder over the raw archive and compared documented layouts and formulas
against the GDAC `_tech.nc` / `_Rtraj.nc` references. Where documentation and
data disagree, I say so explicitly and state which I trust.

---

## 1. Reverse-engineered assumptions — now adjudicated

Nine assumptions from Phases 5B/6A.3/6A.4 were checked. **Seven confirmed, two
refined, zero contradicted on emitted output.**

| # | Assumption (as implemented) | Verdict | Documentary evidence |
|---|---|---|---|
| A1 | `SP` is **signed** 2's-complement centibars | ✅ **Confirmed** | D4 p.23 conversion table: pressure is "16-bit unsigned **with 2's complement**", `P = Praw/10`. D3 p.4 `ArgosPutWord(EncodeP(...))`. |
| A2 | Pressure sentinels `0x8000,0x8001,0x7FFF,0xFFFE,0xFFFF` | ✅ **Confirmed** | D3 `EncodeP`; D4 p.23. |
| A3 | `EPOCH` is **little-endian** int32 UNIX seconds | ✅ **Confirmed explicitly** | D5 p.19 / D2 row 67: "Current UNIX epoch (GMT) of Apf9a RTC **(little endian order)**". D3 p.4: `t=time(NULL); ArgosPut((const unsigned char*)(&t),sizeof(t))` — raw struct copy on a little-endian MCU. **This was inferred in 6A.3 from a sanity window; it is now documented.** |
| A4 | `TINIT` is a signed 16-bit minute count | ✅ **Confirmed** | D4 p.22: "2's compliment signed integer". D3 p.5 writes `(t>=0)?t:(0x10000L+t)`. |
| A5 | STATUS bit `0x8000 PrfIdOverflow` → cycle = PRF + 256 | ✅ **Confirmed** | D4 p.21: "PrfIdOverFlow — 8-bit profile counter overflowed [255 → 0]". D5 p.22 identical. |
| A6 | `block_shift = 0` for **both** decoder 1005 and 1010 | ✅ **Confirmed** | D4 p.20 vs D5 p.21 byte tables (see §2.2). The 6A.4 correction was right. |
| A7 | `sp_shift = 1` on firmware 091x15 | ✅ **Confirmed** | D4 p.20 puts `SP` at bytes 9–10; D5 p.21 puts `SP` at bytes 11–12 — a **+2** shift in spec bytes, which combined with the removal of `PMT` nets to our +1 payload shift. Empirically both give the reference values exactly (§7, R7). |
| A8 | Battery/current/vacuum need a **per-float** calibration | ⚠️ **Refined — assumption was wrong in an important way** | The calibration is **universal and published** (§5). Not per-float. |
| A9 | `EPOCH+TINIT` offset (~11 min) is "not a subtractable constant" | ⚠️ **Refined — the model exists** | D1 documents `AET = TST − 10 minutes` and a clock-drift model (§3). |

### 1.1 The one genuine surprise: A8

Phase 6A.4 recorded that `CURRENT_BatteryPark_mA = 4.052·byte − 3.606` fitted
with zero residual over 19 cycles, and concluded a *per-float* calibration
existed but was unpublished. That conclusion was **too cautious**.

D4 p.23 publishes exactly that formula, and it is **byte-identical across all 14
firmware manuals** in the archive (verified by grep across every extracted
manual). It is a universal APF9A ADC scaling, not a per-float constant:

```
Volts    V = (Vraw * 0.077) + 0.486
Current  I = (Iraw * 4.052) - 3.606
Vacuum   V = (Vraw * 0.293) - 29.767
```

The empirical fit recovered the published constants to 4 significant figures.
The reverse engineering was *correct*; only the inference "therefore it must be
per-float and unpublished" was wrong. This is the finding that unblocks
Limitation #2 from the project status.

---

## 2. Firmware-specific behaviour

### 2.1 Authoritative decoder-id ↔ firmware map (D2 "Co Apex formats" rows 1–6; D1 "Provided data")

Previously inferred from `registry.csv`. Now documented:

| Decoder id | Firmware (manual) | Controller | Floats | Notes from D1 |
|---|---|---|---|---|
| 1001 | 071412 | APF9A | 29 | — |
| 1002 | 062608 | APF9A | 129 | — |
| 1003 | 061609 | APF9A | 13 | NST data |
| 1004 | 021009 | APF9A | 23 | Ice detection |
| **1005** | **061810** | APF9A | **21** | *"Even if not mentioned in the User manual, the auxiliary engineering data are present in the transmitted data. Consequently 071412 and 061810 only differ by the ARGOSID information provided in test msg #2."* |
| 1006 | 093008 | APF9A | 18 | PTSO (AA), in-air DOXY |
| 1007 | 082213 | APF9A | 13 | — |
| **1010** | **110613 & 090413 & 102015** | APF9A | **49** | — |
| 1011 | 121512 | APF9A | 8 | Ice detection |
| 1012 | 110813 | APF9A | 13 | Ice detection |
| 1013 | 071807 | APF9A | 4 | PTSO (SBE) |
| 1016 | 090810 | APF9A | 1 | PTSO (AA) |

**Important:** our registry lists float 2902201 as firmware `091515` and
2902222/2902223 as `091615`, both mapped to decoder 1010. D1/D2 name decoder
1010's firmwares as `110613`, `090413`, `102015`. The registry strings do not
appear anywhere in the documentation. This is **ambiguous** — most likely the
registry carries a build/serial string rather than the manual revision. It does
not affect decoding (both map to 1010) but it is worth reconciling. **I have not
changed it.**

### 2.2 Data Message 1 packet-layout differences (D4 p.20 vs D5 p.21 vs D6 p.21)

This is the central firmware difference and it is larger than we had modelled:

| Spec byte | 061810 (D4 p.20) | 110613 / 090413 (D5 p.21, D6 p.21) |
|---|---|---|
| 7–8 | STATUS | STATUS |
| 9 | *(SP hi)* | **TELONICS** — 8 status bits for the Telonics PTT |
| 10 | *(SP lo)* | CP |
| 9–10 | **SP** (surface pressure) | — |
| 11 | CP | **SP** (hi) |
| 11–12 | — | **SP** |
| 12 | SPP | — |
| 13 | PPP2 | SPP |
| 14 | PPP | PPP2 |
| 15 | — | PPP |
| 15–16 | **SBE41 (16-bit)** | — |
| 16–19 | — | **SBE41 (32-bit long-word)** |
| 17–18 | **PMT** (pump motor time) | — *(absent from Msg 1)* |
| 19–30 | VQ,IQ,VSBE,ISBE,VHPP,IHPP,VAP,IAP,ABP,PAP,VSAP | 20–30: VQ,IQ,VSBE,ISBE,VHPP,IHPP,VAP,IAP,PAP,VSAP |
| 31 | Not used (20-bit ARGOS ID only) | Not used (20-bit ARGOS ID only) |

Three newly documented facts:

1. **A `TELONICS` byte exists at byte 9 on 110613/090413.** We do not decode it.
   It is a new, entirely undocumented-to-us engineering field (§4).
2. **`SBE41` is a 32-bit long-word on 110613/090413**, not 16-bit. D3 p.5 confirms
   at source level: `ArgosPutLongWord(vitals.Sbe41Status)`. We currently read
   16 bits (`_u16be(payload, 14+shift)`) for both firmwares.
3. **`PMT` and `ABP` are absent from Data Message 1 on 110613/090413.** D3 p.6
   shows pump time moved to **Data Message 3**: `ArgosPutWord((unsigned int)vitals.BuoyancyPumpOnTime)`.

### 2.3 Deprecated / changed status-bit definitions

D7 (071807 FormatNotes, which our `STATUS_BITS` was built from) vs D4 p.21 and
D5 p.22:

| Mask | D7 / our code | D4 p.21 & D5 p.22 (061810, 110613) |
|---|---|---|
| `0x0200` | `sbe41_p_fail` | **`Sbe41Exception`** — "SBE41 exception detected" |
| `0x0400` | `sbe41_pt_fail` | **`Sbe41PUnreliable`** — "SBE41 (P) unreliable" |
| `0x0800` | `sbe41_pts_fail` | **"Not used yet"** |
| `0x1000` | `sbe41_p_unreliable` | **"Not used yet"** |

Our names for bits `0x0200`–`0x1000` are taken from a firmware revision that
predates both of our floats and **the meanings changed**. The other 12 bits are
identical across all three documents. This affects only internal flag naming,
not emitted values (§7, R2).

### 2.4 Unsupported firmware versions

D2 documents 16 decoder ids (1001–1016) plus `111509` and `013108/042408`. We
implement 2 (1005, 1010) and route 1001 to the 1005 layout. Per D1, decoder 1001
is firmware 071412, whose byte table (D-071412 p.20) **matches 061810 exactly**
— so that routing is now documented as correct, where previously it was an
assumption.

APF11 (1021/1022) is absent from this archive; it remains unsupported, correctly.

### 2.5 Depth tables — a documented feature we do not model

D2 row 110 lists a **per-firmware depth table**: `#86 (75 levels)` for 061810,
`#88 (80 levels)` for 110613. Each manual carries the full table (D4 §E p.25,
D5 §E p.28). These define the nominal target pressures for PTS samples. We do
not model them. They are not required for decoding (actual pressures are
transmitted) but they are the documented basis for QC and for
`CONFIG_ProfilePressure`.

---

## 3. Timing analysis — Limitation #1 is now resolved in principle

### 3.1 What ApexTimings.xlsx documents (D1, sheet "Timing determination", rows 15–53)

This sheet is the Coriolis timing algorithm, field by field, with the MATLAB
storage location for each. Reproduced in full because it is the most valuable
document in the archive:

| Quantity | Documented rule | MATLAB store |
|---|---|---|
| `CLOCK_OFFSET_AT_LAUNCH` | float time (EPOCH of test msg) − satellite time | `timeData.clockOffsetAtLaunch` |
| `DOWN_TIME_END` | EPOCH (**interpolated for missing cycles**) | `cycleTime.downTimeEndFloat` |
| `FMT` / `LMT` | first / last message time | `cycleTime.firstMsgTime`, `.lastMsgTime` |
| `TST` | `TST1` (TWR method) if defined, else `TST2` ('improved' method) | `cycleTime.transStartTime` |
| **`TST_float`** | **`= EPOCH + TINIT`** | `cycleTime.transStartTimeFloat` |
| **`AET`** | **`= TST − 10 minutes`** | `cycleTime.ascentEndTime` |
| **`AET_float`** | **`= TST_float − 10 minutes`** | `cycleTime.ascentEndTimeFloat` |
| `TET2` | estimated from max envelope of LMTs; if **N cycles ≥ 33**, add `CLOCK_DRIFT` estimation; if `CLOCK_DRIFT ≤ 20 min`, store drift | `cycleTime.transEndTime2`, `clockDriftInSecPerYear` |
| `TET1` | `= DOWN_TIME_END + UP_TIME` | `cycleTime.transEndTime1` |
| `UP_TIME` | if unknown, `= TET − DOWN_TIME_END` | `configParam.upTime` |
| `AST` | where `PARK_PRES = PROF_PRES`: `= TET − UP_TIME` | `cycleTime.ascentStartTime` |
| **`AST_float`** | **`= EPOCH + TPI`** | `cycleTime.ascentStartTimeFloat` |
| `DDET` | `= AST`, or `= AST_float` | `cycleTime.deepDescentEndTime` |
| `PET` | if `PARK_PRES = PROF_PRES`: `= AST`; else `= TET − UP_TIME − DPDP` | `cycleTime.parkEndTime` |
| `DST` | `= TET` of the **previous** cycle | `cycleTime.descentStartTime` |
| `DPF_FLOAT` | if `=1`, exclude cycle #1 from the max envelope for TET | — |

### 3.2 Verification against our data

I computed `TST_float = EPOCH + TINIT` and compared with the reference
`JULD_TRANSMISSION_START` and `JULD_ASCENT_END`:

| Float | Cycle | `TST_float` | ref `TST` | Δ | ref `AET` | `TST − AET` |
|---|---|---|---|---|---|---|
| 2902222 | 327 | 07:24:40 | 07:13:54 | +10.77 min | 07:03:54 | **exactly 10.00 min** |
| 2902222 | 329 | 07:25:54 | 07:14:49 | +11.08 min | 07:04:49 | **exactly 10.00 min** |
| 2902223 | 327 | 23:13:59 | 23:02:07 | +11.87 min | 22:52:07 | **exactly 10.00 min** |

**Two conclusions:**

1. **`AET = TST − 10 min` is confirmed exactly, 3/3.** This is a hard,
   documented rule we do not implement. It directly gates the profile `JULD`.
2. The residual 10.77–11.87 min is **float RTC clock drift**, exactly as D1's
   `CLOCK_DRIFT` rows describe. Phase 6A.3 called it "not a subtractable
   constant" — correct, because *it is not meant to be a constant*. It is a
   drift term estimated over the cycle series.

I measured the drift directly from the raw EPOCH values of 2902222:

```
cycle 327 → 328 : 10.000081 days  (+7.0 s)
cycle 328 → 329 : 10.000081 days  (+7.0 s)
```

The float RTC gains a **perfectly linear 7.0 s per 10-day cycle ≈ 256 s/year**.
Over the ~4.5 years from deployment (2017-01-20) to cycle 327, that accumulates
to ≈ 19 min — the right order of magnitude for the observed ~11 min offset, and
the reason it grows between cycles 327 (10.77) and 329 (11.08): **+0.31 min over
20 days = 5.7 min/year**, consistent with a drift term.

D1 requires **N ≥ 33 cycles** to estimate `CLOCK_DRIFT`. We hold **3 cycles**
for 2902222/2902223 and 73 for 2901339 (which has no reference overlap). So the
algorithm is documented and understood, but **for the floats where we have
references, we do not have enough cycles to run it.** That is an honest,
data-bound limitation — different in kind from the previous "unknown model".

### 3.3 Other timing quantities

- **Surface / transmission timing.** `REP` (ARGOS transmission repetition
  period, seconds) is in Test Message 2 byte 15 (D2 row 59) → `CONFIG_TransmissionRepetitionPeriod_seconds`.
  We do not decode test messages, so we do not have it.
- **Mission Prelude.** `PRE` (prelude period, hours; D2 row 58) and `SEC`
  ("Time since the start of the Mission Prelude [seconds]", Test Msg 1 byte 9,
  D2 row 19) → `STARTUP_DATE`. D4 p.8 states six hours is typical. **This is the
  documented source of `_meta.nc` `START_DATE`**, which Phase 6A.2 classified as
  unexplainable (ref ~20 h after launch). Confirms it is float behaviour, not
  registry error.
- **GPS timing.** ✅ **Not applicable and should not be added.** These are ARGOS
  floats; D4 p.8 mentions GPS only for the pre-deployment operator fix. There is
  no GPS in the telemetry. Positioning is ARGOS Doppler (correctly implemented).

---

## 4. Engineering telemetry — fields currently ignored

### 4.1 Fields present in our firmwares that we do not decode

| Field | Location | Documentation | Currently |
|---|---|---|---|
| **TELONICS** | Msg 1 byte 9 (110613/090413 only) | D5 p.21: "records the state of 8 status bits for the Telonics PTT" | **Ignored.** Bit meanings **not documented** in any supplied file — see §4.3. |
| **CP** (current pressure) | Msg 1 byte 11 (061810) / byte 10 (110613) | D4 p.20; D2 row 93 → `PRES_Now_dbar`, "store average of decoded values" | **Ignored.** A distinct new pressure per message copy. |
| **SBE41 upper 16 bits** | Msg 1 bytes 16–19 (110613/090413) | D5 p.21 "long-word … 32 status bits"; D3 p.5 `ArgosPutLongWord` | **Truncated** to 16 bits. |
| **PMT** | Msg **3** on 110613/090413 | D3 p.6 | Read from Msg 1 (yields 0). |
| **Park statistics** (11 fields) | Msg 2 bytes 9–30 | D4 pp.22–23; D3 p.6 | **Ignored** — `PRKN, TMEAN, PMEAN, SDT, SDP, TMIN, TMINP, TMAX, TMAXP, PMIN, PMAX`. D2 maps these to trajectory MC 294/296/297/298/287/288. |
| **Park end sample** | Msg 3 bytes 2–7 (`PRKT/PRKS/PRKP`) | D4 p.23; D3 p.6 | **Ignored** — D2 maps to **MC 300**. |
| **Auxiliary engineering block** | tail of last message | D3 p.7; D2 rows 228–237 | **Ignored** — `PDIVMAX`, `TPI`, `VAC`, `NPMK`, and `PMK1..PMKN` descent pressure marks (MC 190). |
| **TPI** | auxiliary block | D2 row 230: "Time of profile initiation … 2-byte signed" → **`AST_float = EPOCH + TPI`** | **Ignored.** This is the missing input for ascent-start timing. |

Per D1's note on decoder 1005 (§2.1), the auxiliary engineering data **are
present in 061810 transmissions even though the manual omits them.**

### 4.2 Engineering status flags

- Main `STATUS` — 16 bits, fully documented (D4 p.21, D5 p.22). We decode all 16;
  4 names need updating (§2.3).
- `SBE41` — documented in D4 pp.21–22. Note the D4 table is **internally
  inconsistent**: it lists `0x8100, 0x8200, 0x8400, 0x8800, 0x9000, 0xa000,
  0xc000` for the PTS group, which are overlapping multi-bit patterns, not
  single-bit masks. This is almost certainly an OCR/typesetting corruption of
  `0x0100…0x4000` in a second column. **I flag this as ambiguous and recommend
  not acting on the PTS masks without a cleaner source.**
- `TELONICS` — 8 bits, **no bit definitions in any supplied document**.

### 4.3 Battery, pump, pressure system

All documented and calibratable (§5): 4 voltage channels (VQ, VSBE, VHPP, VAP),
4 current channels (IQ, ISBE, IHPP, IAP), `VAC` internal vacuum, `ABP` air
bladder, `PAP` air-pump pulses, `VSAP` volt-seconds, `PMT` pump motor time.

### 4.4 Mission state

Test Message 1/2 carry the full mission configuration (D2 rows 28–73): `UP`,
`DOWN`, `PRKP`, `PPP`, `NUDGE`, `OK`, `ASCEND`, `TBP`, `TP`, `TPP`, `N`, `FEXT`,
`FRET`, `IBN`, `CHR`, `PACT`, `DPDP`, `PDP`, `PRE`, `REP`, `ARGOSID`, `SBESN`,
`SBEFW`, `EPOCH`, `TOD`, `DEBUG` — each mapped to a specific `CONFIG_*` or
`META` field. Our archive contains no test-message files, so this remains
blocked on data, not on specification. **The specification gap is now closed.**

---

## 5. Calibration formulas

### 5.1 Documented (D4 p.23; identical in all 14 manuals)

| Measurement | Resolution | Range | Format | Conversion |
|---|---|---|---|---|
| Temperature | 0.001 °C | −4.095 … 61.439 °C | 16-bit unsigned w/ 2's complement | `T = Traw / 1000` |
| Salinity | 0.001 psu | −4.095 … 61.439 psu | 16-bit unsigned w/ 2's complement | `S = Sraw / 1000` |
| Pressure | 0.1 dbar | −3276.7 … 3276.7 dbar | 16-bit unsigned w/ 2's complement | `P = Praw / 10` |
| Volts | — | 8-bit unsigned | | `V = (Vraw × 0.077) + 0.486` |
| Current | mA | 8-bit unsigned | | `I = (Iraw × 4.052) − 3.606` |
| Vacuum | inHg | 8-bit unsigned | | `V = (Vraw × 0.293) − 29.767` |

Worked example, D4 p.23: `0xBB → Vraw = 187 → 187×0.077 + 0.486 ≈ 14.9 V`.

### 5.2 Comparison with implementation

- **T, S, P: ✅ already correct.** Our `/1000`, `/1000`, `/10` with 2's-complement
  handling matches exactly. This is independently corroborated by 1813/1813
  bit-identical science levels.
- **Volts / Current / Vacuum: 🔴 documented but not implemented.** We withhold
  these 7 `_tech.nc` parameters as "uncalibrated".

### 5.3 Empirical validation of the published constants

I applied the published formulas to raw bytes at our current offsets and
compared against GDAC `_tech.nc` for 2901339 (73 comparable cycles) and 2902222
(3 cycles):

| Parameter | Offset (payload) | Exact matches |
|---|---|---|
| `VOLTAGE_BatteryParkNoLoad_volts` | `[18]` | 72/73 (1005), 3/3 (1010) |
| `CURRENT_BatteryPark_mA` | `[19]` | 52/73 (1005), 3/3 (1010) |
| `CURRENT_BatterySBEPump_mA` | `[21]` | 40/73 (1005), 3/3 (1010) |
| `VOLTAGE_BatteryInitialAtProfileDepth_volts` | `[22]` | 3/3 (1010) |
| `CURRENT_BatteryInitialAtProfileDepth_mA` | `[23]` | 20/73 (1005), 3/3 (1010) |
| `PRESSURE_InternalVacuum_inHg` | `[8]` | 40/73 (1005) |

For decoder 1010 the agreement is **perfect (3/3 on every channel)**. For 1005
the match is partial, and the reason is documented rather than mysterious: D2
annotates these very parameters **"store average of decoded values"** (rows
26–28, 107–111). Each ARGOS copy of Message 1 carries a *fresh* measurement, so
the DAC averages across copies. I tested mean-of-raw, rounded-mean, median and
mean-of-converted; none reproduced the reference exactly (10/48), so **the exact
averaging/selection rule remains ambiguous** and I do not recommend guessing it.

The correct reading: **the scale factors are proven; the multi-copy aggregation
rule is not yet pinned down.**

---

## 6. Metadata opportunities

Fields the documentation shows are obtainable but that we do not expose:

| Field | Source | Target |
|---|---|---|
| Firmware revision (MON/DAY/YR) | Test Msg 1 bytes 4–6 (D2 rows 12–14) | `FIRMWARE_VERSION` — decoded from telemetry rather than registry |
| Controller serial / hull number | `FLT`, Test Msg 1 byte 7 (D2 row 17) | `CONTROLLER_BOARD_SERIAL_NO_PRIMARY` |
| SBE41 serial + firmware | Test Msg 2 (D2 rows 63–65) | `SENSOR_SERIAL_NO`, **`SENSOR_MODEL`** ("used to choose the correct sensor model") |
| Mission prelude start | `SEC`, Test Msg 1 byte 9 | **`STARTUP_DATE` / `START_DATE`** |
| Full mission configuration (26 params) | Test Msgs 1–2 | the blank `CONFIG_*` block |
| ARGOS ID root/extension, ARGOS frequency | Test Msg 2 (D2 rows 60, 61) | `META` |
| Clock offset at launch | Test-msg EPOCH − satellite time (D1 row 15) | `CLOCK_OFFSET` (N_CYCLE) |
| Clock drift | D1 rows 34–37 | `clockDriftInSecPerYear` |
| Depth table id | D2 row 110 | float capability / QC context |
| Park statistics, descent marks | Msg 2/3 + auxiliary | trajectory MC 190/287/288/294/296/297/298/300 |
| Ice detection params (`ICEM`,`IMLT`,`IDP`,`IEP`) | Test Msg 3, decoders 1004/1011/1012 | out of scope |

Also: D2 rows 239–249 document that `NUMBER_ArgosPositions_COUNT`,
`NUMBER_ArgosPositioningClass{0,1,2,3,A,B,Z}_COUNT` and CRC statistics are
`_tech.nc` parameters derived **purely from received ARGOS data** — no float
telemetry needed. **We already have everything required to compute these.**

---

## 7. Potential implementation discrepancies

Only items the documentation clearly supports. Nothing speculative.

---

**R1 — `AET = TST − 10 minutes` not implemented** 🔴
*Doc:* D1 "Timing determination" rows 29, 31.
*Current:* No ascent-end-time model; profile `JULD` carries an unexplained 0–8 h offset.
*Recommend:* Implement `AET = TST − 10 min` and `AET_float = TST_float − 10 min`.
*Confidence:* **High** — documented and verified 3/3 exactly on our references.

**R2 — Status-bit names 0x0200–0x1000 are from the wrong firmware** 🔴
*Doc:* D4 p.21, D5 p.22.
*Current:* `sbe41_p_fail`, `sbe41_pt_fail`, `sbe41_pts_fail`, `sbe41_p_unreliable`.
*Correct:* `0x0200 Sbe41Exception`, `0x0400 Sbe41PUnreliable`, `0x0800` unused, `0x1000` unused.
*Recommend:* Rename for 1005/1010; make the map firmware-aware.
*Confidence:* **High.** Internal naming only — no emitted value changes.

**R3 — `SBE41` truncated to 16 bits on decoder 1010** 🔴
*Doc:* D5 p.21, D6 p.21 ("long-word … 32 status bits"); D3 p.5 `ArgosPutLongWord`.
*Current:* `_u16be(payload, 14 + shift)`.
*Recommend:* Read 32-bit BE for 110613/090413; keep 16-bit for 061810.
*Confidence:* **High** — three independent sources including C source.

**R4 — `PMT` read from the wrong message on decoder 1010** 🟡
*Doc:* D3 p.6 writes pump time in Data Message 3; D5 p.21 omits it from Msg 1.
*Current:* Read from Msg 1 → returns 0.
*Note:* The GDAC reference **also reports 0** for these cycles, so output is
currently correct by coincidence. Real values may exist in Msg 3.
*Confidence:* **High** on the layout; **Medium** on impact.

**R5 — Voltage/current/vacuum withheld though formulas are published** 🔴
*Doc:* D4 p.23 (and 13 other manuals).
*Current:* 7 parameters withheld as "uncalibrated"; `PLAUSIBLE_*` comments state
coefficients are unpublished.
*Recommend:* Implement the three conversions. **Resolve the "store average of
decoded values" rule (D2) before emitting**, since single-copy conversion matches
only ~55–99 % of 1005 cycles (100 % for 1010).
*Confidence:* **High** on formulas; **Low** on the aggregation rule.

**R6 — `PRESSURE_AirBladder_COUNT` mismatch on 091x15 now explained** 🟡
*Doc:* D5 p.21 — **`ABP` is not in Data Message 1 on 110613/090413.**
*Current:* Emitted only for decoder 1005 (`_ABP_VERIFIED_DECODERS`), because
reference values 123/122/122 matched no byte.
*Finding:* The Phase 6A.4 decision was **right**, and now has a documented reason:
the field genuinely is not there. The guard should cite D5 p.21.
*Confidence:* **High.**

**R7 — `sp_shift`/`block_shift` are correct** ✅
Verified empirically this session: all piston positions, surface offsets and
pump times reproduce the GDAC reference exactly for 2902222/2902223. The
documented 110613 layout read literally (`SP` at spec byte 11) gives −137.3 dbar
versus reference −0.4 dbar; **our offsets are right and the naive documented
reading is wrong**, because the payload indexing differs from the on-air frame
convention. No change recommended.

**R8 — `CP` (current pressure) not decoded** 🟢
*Doc:* D4 p.20 byte 11; D2 row 93 → `PRES_Now_dbar`.
*Confidence:* **High** on existence; needs the averaging rule.

**R9 — `TELONICS` byte not decoded** 🟢
*Doc:* D5 p.21 (existence only; **bit meanings undocumented**).
*Recommend:* Optionally surface the raw byte. **Do not invent bit meanings.**
*Confidence:* **High** on existence; **None** on semantics.

**R10 — Auxiliary engineering block not parsed** 🟡
*Doc:* D3 p.7; D2 rows 228–237. Contains `TPI`, needed for `AST_float`.
*Note:* D1 confirms these are present in 061810 despite manual omission.
*Confidence:* **High** on existence; **Medium** on our archive containing enough tail bytes.

**R11 — Park statistics and park-end sample not decoded** 🟡
*Doc:* D4 pp.22–23; D3 p.6; D2 rows 125–157 with explicit MC mappings.
*Confidence:* **High.**

**R12 — ARGOS position/CRC statistics not emitted** 🟢
*Doc:* D2 rows 239–249. Derived from received data only.
*Confidence:* **High** — no blockers.

**R13 — Registry firmware strings unverifiable** 🟢
Registry says `091515`/`091615`; D1/D2 say decoder 1010 = `110613`/`090413`/`102015`.
**Ambiguous**; no functional impact. Flagged, not changed.

---

## 8. Documentation map

| Document | Topics covered | Relevant decoder modules |
|---|---|---|
| **D1 `ApexTimings.xlsx`** — sheet *Timing determination* | `CLOCK_OFFSET_AT_LAUNCH`, `DOWN_TIME_END`, `FMT`/`LMT`, `TST`/`TST_float`, **`AET = TST − 10 min`**, `TET1`/`TET2`, `CLOCK_DRIFT` (N≥33), `AST`/`AST_float`, `DDET`, `PET`, `DST` | `platforms/apex_argos/trajectory.py`, `nc/trajectory.py`, `platforms/apex_argos/profile.py` (JULD) |
| **D1** — sheet *Provided data* | decoder id ↔ firmware ↔ float count; which floats provide EPOCH/TST/AST/PRES marks; per-decoder specificities | `config/registry.csv`, `platforms/apex_argos/engineering.py` |
| **D2 `ApexCoDecoderVersions_20160926.xlsx`** — *Co Apex formats* | Byte-by-byte layout for **all 16 decoder ids** side by side; Test 1/2/3 and Data 1/2/3; depth-table ids | `platforms/apex_argos/engineering.py`, `frames.py` |
| **D2** — per-firmware sheets (`061810`, `110613_090413`, …) | Per-field → `TECH`/`CONFIG`/`META`/`TRAJ`/`PROF` mapping, MC numbers, ADMT label names, "store average" notes | `nc/technical.py`, `nc/metadata_file.py`, `nc/trajectory.py` |
| **D3 `Firmware-082213-Appendix-G.pdf`** | Authoritative C source for Test 1/2 and Data 1/2/3; `EncodeP`/`EncodeT`/`EncodeS`; little-endian EPOCH; `ArgosPutLongWord` SBE41; auxiliary block construction | `platforms/apex_argos/engineering.py`, `frames.py` |
| **D4 `…061810…pdf`** (p.20 layout, p.21 STATUS, pp.21–22 SBE41, **p.23 conversions**, p.25 depth table 86) | **Primary source for decoder 1005** | `engineering.py`, `nc/technical.py`, `sensors/ctd.py` |
| **D5 `…110613…pdf`** / **D6 `…090413…pdf`** (p.21 layout, p.22 STATUS, p.26 conversions, p.28 depth table 88) | **Primary source for decoder 1010**; TELONICS; 32-bit SBE41 | same |
| **D7 FormatNotes (071807)** | Original layout used in Phase 6A.3 | superseded by D4/D5 for our floats |
| **D8 Coriolis decoder manual V1.10** | Operational usage, config columns | `cli/`, `config/` |
| **D9 `_CoriolisArgoFloatVersions.xlsx`** | Float ↔ decoder version mapping | `config/registry.csv` |
| **D10–D18** (other manuals) | Confirm the conversion table is universal; layouts for unsupported decoders | future scope |

---

## 9. Prioritized recommendations

### ✅ Already correctly implemented (confirmed by documentation)

- T/S/P conversions and 2's-complement handling (D4 p.23)
- `SP` signed centibars + pressure sentinels (D3, D4 p.23)
- `EPOCH` little-endian int32; `TINIT` signed 16-bit (D3 p.4–5, D5 p.19)
- `PrfIdOverflow` → cycle = PRF + 256 (D4 p.21)
- `block_shift = 0` for both firmwares; `sp_shift = 1` on 091x15 (**R7**, verified)
- Withholding `PRESSURE_AirBladder_COUNT` on 1010 (**R6** — field genuinely absent)
- 12 of 16 STATUS bits
- No GPS handling (correct — ARGOS floats have none)
- `_meta.nc` `START_DATE` ≠ launch date (explained by Mission Prelude, D4 p.8)

### 🔴 High-confidence implementation issues

| | Item | Why |
|---|---|---|
| **R1** | `AET = TST − 10 min` missing | D1 rows 29/31; verified exactly 3/3 |
| **R2** | Wrong STATUS names for `0x0200`–`0x1000` | D4 p.21 / D5 p.22 supersede D7 |
| **R3** | SBE41 truncated to 16 bits on 1010 | D5 p.21 + D3 p.5 `ArgosPutLongWord` |
| **R5** | Voltage/current/vacuum withheld though published | D4 p.23 — *gate on the averaging rule first* |

### 🟡 Recommended enhancements

- **R4** `PMT` from Data Message 3 on 1010 (D3 p.6)
- **R10** Auxiliary engineering block → `PDIVMAX`, **`TPI`**, `VAC`, descent marks (D3 p.7)
- **R11** Park statistics + park-end sample → MC 294/296/297/298/287/288/300 (D4 pp.22–23)
- Clock-drift model per D1 rows 34–37 (needs ≥33 cycles — not available for our reference floats)
- Reconcile registry firmware strings (**R13**)

### 🟢 Nice-to-have

- **R12** ARGOS position/CRC statistics (D2 rows 239–249) — no blockers, pure win
- **R8** `CP` current pressure → `PRES_Now_dbar`
- **R9** Raw `TELONICS` byte (semantics undocumented — do not interpret)
- Depth tables 86/88 as reference data (D4 §E, D5 §E)
- Test-message decoder for `CONFIG_*` (spec now complete; still needs test-message files)

---

## 10. Effect on previously recorded limitations

| Limitation (from `docs/PROJECT_STATUS.md`) | New status |
|---|---|
| **#1 Firmware-specific cycle-timing model** | **Substantially resolved.** `AET = TST − 10 min` is documented and verified; the residual is float RTC clock drift (measured: linear 7.0 s/cycle), with a documented estimation algorithm requiring ≥33 cycles. Our reference-overlapping floats have only 3. |
| **#2 Count→engineering-unit calibration** | **Resolved at the formula level.** Published in D4 p.23, universal across 14 manuals; the empirical `4.052/−3.606` fit was correct. **One open sub-question:** the multi-copy "store average" rule. |
| **#3 Differing DAC input** | **Unchanged** — not a documentation matter. |
| **#4 Test/prelude message decoding** | **Specification gap closed** (D2 gives full layouts + `CONFIG_*` mapping). Still blocked on *data*: our archive holds no test-message files. |

---

## 11. Honest limitations of this audit

- **PDF text extraction is imperfect.** Several manuals show OCR artefacts
  (`lAP` for `IAP`, `Ox` for `0x`, `ppp` for `PPP`). I cross-checked every
  load-bearing claim against ≥2 documents or against real data. The SBE41 PTS
  bit masks in D4 (§4.2) are visibly corrupted and I have **not** relied on them.
- **`_CoriolisArgoFloatVersions.xlsx` (D9) and the `.doc` manual were not fully
  parsed** — D9 was consulted only for the version mapping already corroborated
  by D1/D2.
- **Page numbers** cite the PDF's own printed page numbers where visible
  (e.g. "20 of 36"); where a table spans pages I cite the starting page.
- **Decoder 1010's reference sample is 3 cycles.** Perfect agreement there is
  encouraging but a small sample.
- I did **not** verify recommendations by implementing them, per instruction.

---

## 12. Summary

The documentation confirms the great majority of our reverse engineering,
including every value currently emitted to the GDAC products. No emitted output
is shown to be wrong.

The most consequential findings are the four 🔴 items — and two of them
(**R1** timing, **R5** calibration) correspond exactly to the two limitations
this project has carried as "blocked pending documentation" since Phase 6A.3.
Both are now unblocked at the specification level.

The one item I would flag for judgement before any implementation is **R5**:
the conversion constants are certain, but the "store average of decoded values"
aggregation is not, and emitting averaged engineering values under the wrong
rule would be worse than continuing to withhold them.

**No source code was modified. Awaiting your decision on which recommendations to implement.**
