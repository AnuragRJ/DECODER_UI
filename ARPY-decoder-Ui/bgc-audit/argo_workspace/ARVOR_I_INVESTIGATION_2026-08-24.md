# ARVOR-I / Core-Iridium Decoder Investigation — READ-ONLY Report
**Date:** 2026-08-24 · **Status:** Stages 1–5 complete · **No source/raw files were modified**

Evidence classes used throughout: **[R]** observed in raw telemetry · **[M]** Coriolis MATLAB source behavior · **[D]** Coriolis/NKE documentation (manual, version tables) · **[S]** operator spreadsheet metadata · **[I]** inference/hypothesis. Each conclusion is tagged **PROVEN / INFERRED / UNKNOWN**.

---

## 1. Inventory

| Item | 6990711 | 7902408 |
|---|---|---|
| Files | 35 eml + 35 sbd + ctd/ (7 Asc, 1 Desc, 7 Sub) | 64 eml + 64 sbd + ctd/ (15 Asc, 1 Desc, 15 Sub) |
| Region | Southern Ocean (−64.5, 70.0E), RV Agulhas | Bay of Bengal (2.99N, 83.0E), RV Sindhu Sadhana |
| Operator (sheet) | Incois, NKE SN 24022, order 572 | Incois, NKE SN 25016, order 615 |
| Launch [S] | 2025-03-02 05:16 | 2026-03-25 17:44 |
| Sessions (eml) | 2025-03-04 → **2025-05-02** (35) | 2025-09-19 (factory, 3) + 2026-03-25 (deck, 4) + cycles (57) |
| MOMSN range | 67…105 (gaps: 73, 79, 85, 91) | 32…135 (many gaps, §8) |
| Cycles in data | 1–7 | 0 (pre-mission) + 1–15 |
| Status | **DEAD** (silent since 2025-05-02, 16 mo) | **ACTIVE** (last tx 2026-08-11; snapshot 2026-08-19) |

- All `.sbd` are exactly 300 B = 3×100 B packets [R]. Padding packets = all-`0x1A` (type-26 appearance) or all-`0x00` [R].
- Stage-1 note corrected: 6990711 transmissions extend to 2025-05-02 (the "Mar 4–Apr 2" window was the *cycle-1..4* window only) [R].
- Firmware (checksum in type-0 item 3 [R]): 6990711 = 11415 = 0x2C97 → **5900A05 → fw 5.47 → decId 222**; 7902408 = 13872 = 0x3630 → **5900A05B → fw 5.54 → decId 232** (mapping via `check_decoder_id.m` [M] + `_CoriolisArgoFloatVersions.xlsx` [D]) — PROVEN.

## 2. `.eml` → `.sbd` relationship — PROVEN [M][R]

> **Correction (2026-08-24, during Phase-1 implementation):** the supplied `.eml` files are
> **header-only** (exactly 200 bytes: `MOMSN`/`MTMSN`/`Time of Session`/`Session Status`/
> `Message Size`/`Unit Location`/`CEPradius`, CRLF, no MIME part). The base64 payload is **not**
> inside them; it lives in the sidecar `.sbd` file of the same stem. The MIME-with-`filename=
> "…NNNNNN.sbd"` structure described below is the **upstream Coriolis mail format** that
> `read_mail_and_extract_attachment.m` consumes (and which the exporter of this dataset had
> already split). All field-level statements below remain PROVEN and are byte-identical in the
> supplied files. The Phase-1 reader supports both forms.

Each `.eml` is the RockBLOCK/Iridium email wrapper for exactly one 300 B SBD:
- Headers: `MOMSN`, `MTMSN`, `Time of Session (UTC)`, `Unit Location:` (lat/lon + `CEPradius`), then MIME multipart with `filename="…NNNNNN.sbd"` attachment, base64-decoded to the paired `.sbd` [M] (supplied files: header text + sidecar `.sbd`, see correction above) [R].
- Coriolis `read_mail_and_extract_attachment.m` parses exactly these fields; validates `size == Message Size (bytes)`; `timeOfSessionJuld = datenum('mmm dd HH:MM:SS yyyy') − offset`; unit-location lat/lon with NaN→cepRadius=0 [M].
- File naming here is `redacted_imei_XXX_<MOMSN>` — the true IMEI is redacted; MOMSN is recoverable both from the filename and the `MOMSN:` header [R]. Session time comes from the **email header** (ground-station reception of session), not the float clock [R].
- Pairs are 1:1 (35+35, 64+64); no orphan sbd/eml [R].

## 3. Packet/message types — PROVEN [M][D][R]

100-byte packets, MSB-first bit packing, first byte = type. Types present in these floats [R]:
`0` Tech#1 · `1` Descent CTD · `2` Drift/park CTD · `3` Ascent CTD · `4` Tech#2 · `5` Prog#1 (params, sent only when changed — fw ≥5900A05) · `6` Hydraulic (valve/pump/EV actions). Types `8–12` = CTDO variants + NS/IA (oxygen floats), `13/14` = CTD Near-Surface / In-Air — **absent here** [R], consistent with SBE41CP-no-O₂ config [S].
Histograms: 6990711 {0:7, 1:4, 2:13, 3:49, 4:7, 6:15, 26:10}; 7902408 {0:19, 1:4, 2:23, 3:74, 4:19, 5:7, 6:38, 26:8} [R]. Session combos: (0,4,6), (3,3,3), (6,2,2)…; 7902408 type-5 only in cycle-0 sessions (0,4,5) [R].

## 4. Coriolis MATLAB call chain — PROVEN [M]

**Delayed mode (matches this dataset):**
`decode_provor_iridium_sbd_delayed.m` (mail spool loop; per-float date skip lists; duplicate-mail removal) → `read_mail_and_extract_attachment.m` → `decode_sbd_file.m` (checks `size mod 100 == 0`; reshapes 100 B rows; drops all-0x00/all-0x1A rows; dispatches on decoderId) → `decode_prv_data_ir_sbd_222_223_225.m` / `…_232.m` (per-packet bit decode) → `create_decoding_buffers.m` → `create_decoding_buffers_222_223_225_232.m` (sessions/buffers/completion/ranking) → `process_decoded_data.m` (per-family branch: 222 → `create_prv_{drift,profile}_212_222_231`; 223/225/232 → `…_214_217_223_225_232`; conversion via `sensor_2_value_for_{pressure,temp,salinity}_2xx…`; dates via `compute_prv_dates_212_214_217`; GPS via `store_gps_data_ir_sbd`; ice via `store_ice_information_arvor`).
**Real-time:** `decode_argo_2_nc_rt` (transType 3) → `parse_input_param_iridium_sbd_rt` (`co_<ts>Z_<IMEI>_<MOMSN>_<MTMSN>_<size>.txt`) → `decode_argo` → `decode_provor` → `decode_provor_iridium_sbd` → same byte decoders.
Decoder-id dispatch + one-shot firmware-checksum validation: `check_decoder_id.m` (global flag `g_decArgo_decIdCheckFlag`).

## 5. Byte/field layouts + formulas (types 0,4,5,6,7,CTD) — PROVEN [M], verified against raw [R] and manual [D]

Identical layouts for engines 222_223_225 and 232 (verified in both `.m` files and empirically on 99 messages).

**Type 0 — Tech#1 (74 items / 792 bits).** Key items (MATLAB 1-based): 1 cycle(16b) · 2 Iridium-session#(8b) · 3 fw checksum(16b) · 4 serial(16b) → reads 24022/25016 ✓[R] · 5–7 start d/m/y · 8 rel start day(16b) → `julD2FloatDayOffset` · 9 start time(min) · 41–46 float time `HHMMSSddmmyy` · 47 pressure-sensor offset (8b twos /10) · **lat = ±(53° + (54′+55/10⁴)/60)**, sign 56 · **lon = ±(57° + (58′+59/10⁴)/60)**, sign 60 · 61 GPS valid · 66 EOL flag · 73 clock retiming (16b twos, seconds; stored only if item 61 valid).
**Type 4 — Tech#2 (59 items).** 1 cycle · 2 session# · **3 #descent CTD packets · 4 #drift · 5 #ascent · 6 #NS · 7 #IA** · 46–51 last-reset HHMMSSddmmyy · 58 hydraulic type · 59 ice-detection flag.
**CTD types {1,2,3,13,14}**: `[16 16 8 8 | 45×16 | 3×8]` = cycle(16b), first-measurement time H(16b)/M(8b)/S(8b) (fraction of day), **15 PTS triplets (16b each)**, 3 spare bytes. All-zero triplet → fill; fully-empty packet → warning+drop [M].
**CTDO {8–12}**: 7 PTSO sextets (adds C1/C2 phase, optode T) — unused here.
**Type 5 — Prog#1 (70 items)**; floatTime items 3–8; item69/1000; item70 <32768→−x else 65536−x. **Type 7 — Prog#2 (25 outputs)**; item15 twos/1000. **Type 6 — Hydraulic**: refDay(16b)+refMin(16b), 13×(actionType(8b), refTime(16b), pressure(16b twos), duration(16b)); type 0 = EV else pump [M].
Pre-launch rule: any packet with `sbdFileDate < launchDate` → `cyNumRaw = −1` [M].

**Counts→physical (PROVEN [M], numerically cross-validated [R]):**
- `PRES_dbar = (twos16(counts) + 10000) / 10`
- `TEMP_°C = twos16(counts) / 1000`
- `PSAL = counts / 1000` (unsigned)
Calibration coefficients (operator calib sheet / SBE41CP) are applied **inside the float** — the Coriolis decoder applies only these linear scalings. Exact parity achieved vs operator CTD txts: e.g. 6990711 c1 type-3 meas#1 → (1976.30, 0.182, 34.666) ≡ Ascctd001 line 1; likewise type-2≡Subctd001, type-1≡Desctd001, and 7902408 c1 → (2033.80, 2.780, 34.788) ≡ Ascctd001 line 1 — to the last decimal.

## 6. Cycle reconstruction (buffers) — PROVEN [M]

`create_decoding_buffers_222_223_225_232.m`:
1. **Reset handling**: increasing `lastReset` among type-4 packets → on-sea reset; cycle numbers after reset += max(previous)+1. (7902408 had 4 resets but all during cycle 0 → no renumbering; traced.)
2. **cyNum=−1** packets deleted unless a type 5/7 with cyNum==0 exists (pre-launch config).
3. **Session segmentation**: new session at type 0/4/5 with higher cycle & later date, or type-0 same-cycle later date; plus >0.5-day transmission gap; minus <10-min merge; EOL flag forces split.
4. **Buffers per (session, cycle)**: main loop takes first cycle of each session; leftover (session, cycle) pairs processed in a second loop with `delayed=1`. Same-cycle packets in *later* sessions are appended (cut at next 0/4/5) with `delayed=2`.
5. **Completion (`check_buffer` local subfunction — fully read)**: requires exactly one Tech#1 and one Tech#2 (type-5 requirement **exempted** for 222/223/225/232); if exp counts all 0 → surface cycle, complete; else complete iff `recDesc≥expDesc ∧ recDrift≥expDrift ∧ recAsc≥expAsc` (deep flag set by any meas packet). Diagnostics list missing items.
6. **Emission (`tabGo`)**: complete → go=1; else after ≥ `NB_SESSION_MAX−1` (=2) further deep sessions → go=1, completed=0; else go=2 only if `processRemainingBuffers`. EOL retransmissions of already-complete cycles are discarded (rank −1); duplicated type-5/7 keep last; second-Iridium-session (irSession=1) data split into own buffer.
7. **rankByCycle** re-sorts output buffers by cycle number. Extensive per-float hack blocks exist (3901997, 6903800, …; neither of our WMOs appears).

## 7. CTD / technical / trajectory decoding — PROVEN [M]

- **Profiles** (`create_prv_profile_212_222_231` / `…_214_217_223_225_232`): measurement #1 keeps transmitted date (data(1)+refDay); #2–15 have dateDef (unknown exact time) except types 13/14 which interpolate by `CONFIG_MC30` seconds; profiles sorted by PRES descending. Descent = type 1, drift = type 2, ascent = type 3, near-surface = 13, in-air = 14.
- **Drift/park** (`create_prv_drift_*`): meas #1 dated, subsequent spaced by `CONFIG_MC09_` (drift sampling period, from float config via `get_float_config_ir_sbd(cycle)` with walk-back to last applicable config); `parkTransDate` flags transmitted vs inferred.
- **Cycle dates** (`compute_prv_dates_212_214_217`): assembles cycleStartDate (ddmmyy + minutes), descent-to-park start/end, first stabilisation, descent-to-profile, ascent start/end, transmission start, GPS date, groundings, EOL start, emergency ascent — minute-of-day fields with day-rollover (+1 day) heuristics cross-checked against gregorian-day items.
- **Trajectory**: per-cycle GPS (valid-fix gated; clock offset stored only on valid fix; JAMSTEC QC on positions) + drift interpolation; invalid fix → float reuses last valid fix (observed: 6990711 c5/c6 carry c4's coordinates bit-identically [R]).

## 8. Active vs dead float comparison — PROVEN [R]

**6990711 (dead, decId 222):** cycles 1–4 nominal (~10-day). Cycles 5 & 6 completed under water (GPS invalid, stale position, profiles present) but were **not transmitted at their surfaces**; on the cycle-7 surfacing (2025-05-01 23:58) the float transmitted **c7 first, then c5, then c6** — the manual's stored-packet retransmission order ("current cycle, then oldest→newest") [D§6.1]. `ice flag = 0` [R] → delay cause UNKNOWN (comms failure most likely — no ice detection recorded). **No EOL flag on any packet**; float simply never surfaced again (16 months). ⇒ death *without* end-of-life announcement; final burst is **not** corruption and not EOL.
**7902408 (active, decId 232):** factory tests 2025-09-19 at 17.53N/78.40E (Hyderabad/INCOIS) [R]+[S], deck tests on launch day, then cycles 1–15 at 10-day period to 2026-08-11; cycle 16 due ~2026-08-21 (after snapshot). **Incomplete transmissions**: cycles 13–15 lack type-0/4/5 (whole first sessions missing: MOMSN 118–125, 128–131), and cycles 2,3,5,6,7,8,10,11 are missing 1–5 expected measurement packets each (type-4 expected (0,2,7) vs received). MOMSN gaps align exactly with the missing content → **lost/unreceived emails (data-coverage limitation), not float misbehavior** — confirmed by operator Ascctd files showing more points than the shared email set can supply (e.g. Ascctd009 = ascent transmitted **twice**, 206 pts = 2 passes 2002→0 dbar; Ascctd006 = 150 pts). Expected-vs-received (manual mapping, §9): c1 (4,1,7)✓; c4, c9, c12 complete; c8 truncated at 1263 dbar even in operator data.

## 9. Manual says / MATLAB does / Raw shows — triangulation

| Item | Manual 5.54 (33-16-033 Rev14) | Coriolis MATLAB | Raw telemetry |
|---|---|---|---|
| Packet set, 3×100 B, type in 1st byte | ✓ §6.1 | ✓ | ✓ |
| 2nd Iridium session = tech+params only | ✓ §6.1 | ✓ (irSession split) | sess=0 throughout |
| Buffered retransmission order (current, then old→new) | ✓ §6.1 (ice) | ✓ (delayed/EOL logic) | ✓ 6990711 5-1-2025 burst |
| Type-4 items 3/4/5 = #desc/#drift/#asc pkts | ✓ §6.3 Table | **`expNbDesc/Drift/Asc = tabTech2(4)/(5)/(6)` — off-by-one: reads drift/ascent/NS** | item3=4/0 ↔ received t1 4/0; item4=1–2↔t2; item5=7↔t3 — **manual+raw agree, MATLAB is shifted one item** (PROVEN). Consequence: MATLAB completion test pairs wrong expected counts with received counts → ARVOR-I deep cycles complete only via the NB_SESSION_MAX fallback (completed=0), and per-cycle "unexpected/missing" warnings are mislabeled. Coriolis hack blocks for many float IDs are consistent with this systematic mismatch. |
| Type-0 item 4 = serial number | ✓ §6.2 | stored, unused for id | 24022/25016 = sheet MSN ✓ |
| Type-0 item 65 (5.54 numbering) = calendar retiming | ✓ | item 73, gates on GPS valid | clkOff −1…−156 s ✓ |
| Pressure/temp/sal scaling | physical pre-scaled in float | linear twos formulas | exact parity with operator txts |
| GPS deg+min+min/10⁴+orientation | ✓ | ✓ | ✓ (matches deployment coords) |
| fw checksum→format variant | — | `check_decoder_id` | 0x2C97 / 0x3630 ✓ |

6990711's exact manual (fw 5.47) is not in the workspace; nearest are 33-16-007 Rev6 (5.41/5.42) and 33-16-033 Rev8 (5.45/5.46); empirically the 222-engine layout fits all 95 packets with values consistent to the last decimal, so the 5.54-generation format document is adequate for it (INFERRED).

## 10. Decoder identity / format variants — PROVEN

Version↔decoder table [D]: 5.45→212, **5.47→222**, 5.48→223(DO), 5.49→224(RBR), 5.51→226, 5.52→227, 5.53→231, **5.54→232** (ICE-capable "ARVOR ARN Ir Ice", EOL-at-depth). Checksums [M]: 222/223/225→5900A05 (11415); 232→5900A05B (13872). Type-0/4 and CTD layouts are **bit-identical** across 222–232 engines [M, verified both files]; differences live in unused type families (CTDO, NS/IA). Both floats: `ice=0`, `hyd=0` (ARVOR hydraulics) [R]. **The two floats need different decoder engines selected by payload checksum, but a single implementation of the shared layouts decodes both.** Operator sheet's decoder-id column says "222" for both — a template default (metadata), wrong for 7902408 [S vs R].

## 11. Findings register

**PROVEN**
1. Full chain eml→sbd→packets→buffers→profiles/drift/tech (functions named in §4–§7); no reliance on filenames beyond MOMSN recovery (also in headers).
2. Decoder identity: 6990711→222 (fw 5.47), 7902408→232 (fw 5.54), via in-payload firmware checksum; serial numbers corroborate.
3. All packet layouts in §5; linear PTS scaling formulas; exact numeric parity with operator CTD txts on 4 independent checks (both floats, 3 packet types).
4. Coriolis type-4 expected-count off-by-one (items 4/5/6 instead of 3/4/5) — manual + raw agree against MATLAB.
5. 6990711 death without EOL flag after a c7+c5+c6 retransmission burst; c5/c6 GPS-invalid with stale (bit-identical) positions.
6. 7902408 email set incomplete (MOMSN gaps ↔ missing packets ↔ operator txts show extra data incl. a full duplicate ascent); cycles 13–15 lack metadata sessions.
7. Ascctd/Desctd/Subctd txts = raw-derived (operator decode of a superset of the shared emails); sheet launch metadata matches raw (launch positions/dates, cycle-0 deck tests).

**INFERRED**
1. AscctdNNN ↔ cycle N (first-line value match for 6 of 6 probed files, incl. cycles whose metadata emails are missing).
2. 6990711 c5/c6 transmission failure cause = Iridium comms (not ice; not EOL) — root cause UNKNOWN.
3. 5.54-generation format spec covers fw 5.47 adequately for decoding purposes.
4. Operator calib coefficients are used only for float-internal pre-scaling / post-hoc QC, not by the Coriolis decode path.

**UNKNOWN / open questions**
1. Whether the missing 7902408 emails exist in the operator's full mailbox and can be supplied (data coverage).
2. Exact content of `check_buffer` differences for other families (only the 222/232-relevant subfunction read; the generic `is_buffer_completed_ir_sbd` differs for decId 215 etc.).
3. 6990711 failure mode after 2025-05-01 (no telemetry exists — unverifiable).
4. Sheet columns `844`, `np0-ish 572/615` (= deployment order number), manual-date `070120`, firmware-date `160414` semantics (template values; not decode-relevant).
5. Why 6990711 MOMSN 73/79/85/91 are absent (pattern: one per early cycle; no visible data impact).

## 12. Recommended next implementation step (not implemented)

Build a **read-only ARVOR-I Python decoder prototype** in the existing repo skeleton, structured as:
1. `eml` reader (MOMSN, session time, unit location, base64→sbd) mirroring `read_mail_and_extract_attachment`.
2. SBD framing (100 B rows, padding drop) + engine selection by **type-0 item-3 checksum** (11415→222, 13872→232) — the single authoritative selector, replacing sheet guesses.
3. Packet decoders per §5 layouts using an MSB-first bit reader; outputs carry `cycle, irSession, type, raw items, physical values`.
4. Buffer reconstruction per §6 **with the corrected type-4 mapping (items 3/4/5)**, but also emitting the Coriolis-as-coded completion flags for parity comparison.
5. Cross-validation harness against (a) the 15+7 Ascctd/Desctd/Subctd files (exact value parity already demonstrated), (b) per-cycle expected-vs-received tables (§8), (c) GDAC outputs when available.
Decisions to confirm with the user before coding: whether to replicate Coriolis bugs for bit-exact parity or produce corrected outputs (recommended: corrected + parity flags); how to handle 7902408's missing emails (mark cycles incomplete; never fabricate).

---
### Stage evidence & unresolved questions (running log)
- **Stage 1 (inventory/raw):** complete — §1–§3.
- **Stage 2 (MATLAB trace):** complete — §4–§7; all chain functions read from GitHub main; `check_buffer` recovered as local subfunction (lines 1595–1746 of `create_decoding_buffers_222_223_225_232.m`).
- **Stage 3 (manuals/spec):** complete for 5.54 (33-16-033 Rev14, fetched real PDF via raw.githubusercontent; container copies are LFS pointers); 5.47 manual not available — nearest-substitute adequacy INFERRED.
- **Stage 4 (active/dead cross-validation):** complete — §8, §11; independent Python scratch decode (read-only, in /tmp) reproduces operator values exactly.
- **Stage 5 (final decoding specification):** §5–§7 constitute the specification; implementation deferred per user instruction.
