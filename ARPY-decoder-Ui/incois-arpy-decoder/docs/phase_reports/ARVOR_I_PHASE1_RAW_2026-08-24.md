# ARVOR-I Phase 1 — Raw Decoding Foundation (eml → packets)

**Date:** 2026-08-24 · **Status:** COMPLETE — 1799/1799 tests pass (baseline 1741 + 58 new), ruff clean
**Scope discipline:** investigation first, implement second; nothing outside the stated Phase-1
boundary was implemented; no existing decoder code was modified.

## 0. Phase-1 boundary (as stated before implementation)

```
.eml → MIME/attachment extraction → .sbd binary payload → packet identification →
packet framing (100-B rows) → structured decoded packet objects
```

Implemented **only** for the PROVEN layout family **222/223/225/232** (fw 5900A05/A05B;
floats 6990711 = fw 5.47 → decId 222, 7902408 = fw 5.54 → decId 232), for the packet
types **actually observed** in the evidence data: **0, 1, 2, 3, 4, 5, 6** (+ padding rows).
Everything else is explicitly deferred (§4).

## 1. Implementation summary

### Files added (nothing existing modified except additive `__init__` exports)

| File | Content |
|---|---|
| `src/argo_decoder/platforms/provor_ir_sbd/arvor_i.py` | The ARVOR-I raw foundation: engine identification (`resolve_engine`, checksum table from `check_decoder_id.m`), bit-width tables (verbatim from the two MATLAB engines), framing (`frame_sbd_payload` = `decode_sbd_file.m` behaviour), packet dispatch (`decode_packet` / `decode_arvor_i_sbd`), structured packet dataclasses (types 0/1/2/3/4/5/6 + `ArvorUnsupportedPacket`), linear counts→physical conversions, `.eml` reader (`read_arvor_i_eml`, header-only+sidecar **or** true MIME), duplicate flagging (`find_identical_payloads` — flag only, never discard) |
| `tests/unit/test_arvor_i_frames.py` | 30 unit tests (bit-level, byte-for-byte, endianness/sign, fill values, framing, engine id, duplicates) |
| `tests/integration/test_arvor_i_raw_decode.py` | 27 integration tests over the complete real telemetry of both floats (histograms, parity with operator CTD files, active-float sequences, dead-float end-of-mission behaviour, MOMSN gaps) |
| `tests/data/arvor_i/coriolis_src/*.m` | Vendored Coriolis sources used as executable evidence: `decode_prv_data_ir_sbd_222_223_225.m`, `decode_prv_data_ir_sbd_232.m`, `decode_sbd_file.m`, `check_decoder_id.m` |
| `scripts/verify_arvor_i_tables.py` | Mechanical bit-for-bit verification of the Python width tables against the vendored `.m` sources (also asserted inside the unit tests) |
| `docs/phase_reports/ARVOR_I_PHASE1_RAW_2026-08-24.md` | This report |

`src/argo_decoder/platforms/provor_ir_sbd/__init__.py` gained **additive** exports only
(`ArvorTech1Packet`, `decode_arvor_i_sbd`, `resolve_engine`, …). The pre-existing CTS4/221
implementation (`frames.py`, `decoder.py`, `mission.py`, `profile.py`) and all APF9 code are
untouched.

### New components (architecture)

* `ArvorIridiumMessage` — one delivery: **transport metadata** (`SbdSessionInfo`: MOMSN, session
  time UTC, unit location, CEP — ground-station data) strictly separated from the float-generated
  **payload bytes**. Email timestamps are never exposed as float timestamps.
* `ArvorSbdDecode` — framing result: original payload preserved verbatim, decoded packets,
  padding-row indices (padding is recorded, not silently vanished).
* Packet dataclasses with 1-indexed raw `fields` (MATLAB convention, `fields[0] == 0`) **plus**
  typed properties for every PROVEN field; `raw` bytes always preserved.
* `ArvorIEngine` — provenance enum (`FAMILY_222_223_225` / `ENGINE_232`); the two engines' bit
  layouts are **semantically identical** (the `type-5` vectors differ only in how the trailing
  8-bit run is grouped — `16 16 + 8x6` vs `16 16 8 + 8x5`; proven by the mechanical comparison).

### Supported packet types

| Type | Name | Structured fields exposed |
|---|---|---|
| 0 | Tech#1 | cycle, iridium_session, firmware_checksum, serial_number, float_time (UTC), pressure_offset_db, gps_lat/lon + gps_valid, eol_flag, clock_offset_s |
| 1/2/3 (13/14*) | CTD descent/drift/ascent | cycle, first_meas_time_day_fraction, 15 raw PTS triplets, validity mask (all-zero = fill), physical P/T/S |
| 4 | Tech#2 | cycle, **corrected** expected counts (items 3/4/5 = descent/drift/ascent; 6/7 = NS/IA), last_reset, hydraulic_type, ice_flag; `coriolis_exp_nb_desc_drift_asc` exposes the as-coded (shifted) reading for parity |
| 5 | Param#1 | cycle, float_time; raw items only (rest deferred) |
| 6 | Hydraulic | cycle, ref_day/ref_min, 13 actions (type, ref_time_min, pressure_db twos16, duration_s; type 0 = EV else pump) |
| — | padding | all-0x00 / all-0x1A 100-B rows detected and recorded |
| other | `ArvorUnsupportedPacket` | type + raw bytes only, never dropped |

*13/14 layouts are identical to 1/2/3 in the family but were never observed; they decode via the
shared CTD table if they ever appear (no invented semantics beyond the shared layout).

## 2. Evidence mapping (field → four-way agreement)

Legend — **Raw**: observed in supplied telemetry; **Manual**: NKE 33-16-033 Rev14 (fw 5.54);
**Coriolis**: MATLAB source; **Py**: this implementation. All rows PROVEN unless noted.
"raw bytes" = the exact fixture bytes each assertion is pinned to (see tests).

| Packet field (raw bytes fixture) | Raw | Manual | Coriolis | Py | Confidence |
|---|---|---|---|---|---|
| Packet type = byte 0 of each 100-B row (e.g. `0x00`,`0x03`,`0x04`) | ✓ | §6.1 | `decode_sbd_file.m` | ✓ | PROVEN |
| SBD = N×100 B rows; all-0x00/all-0x1A rows dropped (all 99 payloads = 3 rows) | ✓ | §6.1 | `decode_sbd_file.m` | ✓ | PROVEN |
| Tech1 cycle (items 1, 16 b) — 6990711 M67 = 1; 7902408 M32 = 0 | ✓ | §6.2 | ✓ | ✓ | PROVEN |
| Tech1 fw checksum (item 3, 16 b) — 11415 / 13872 | ✓ | — | `check_decoder_id.m` | ✓ | PROVEN |
| Checksum→decId table {38844/47305→212/214/217; 11415→222/223/225; 43931→224; 43079→226/231; 64629→227; 13872→232} | ✓ (2 ids) | — | `check_decoder_id.m` | ✓ | PROVEN (observed subset verified on raw; rest transcribed) |
| Tech1 serial (item 4) — 24022 / 25016 = operator sheet MSN | ✓ | §6.2 item 4 | stored, unused | ✓ | PROVEN |
| Tech1 float time (items 41–46 HHMMSSddmmyy) — 2025-03-04 06:06:32 / 2025-09-19 09:56:42 | ✓ | §6.2 items 41-42 | `datenum('HHMMSSddmmyy')` | ✓ | PROVEN (2-digit-year pivot ≤49→2000s documented) |
| Tech1 pres offset (item 47, 8 b twos, /10) | ✓ | §6.2 item 43 | ✓ | ✓ | PROVEN |
| GPS lat/lon (items 53-56 / 57-60; deg + (min + minfrac/10⁴)/60; sign flag) — −64.5429/70.0833; 17.5281/78.4004 | ✓ | §6.2 items 49-56 | ✓ | ✓ | PROVEN |
| GPS valid flag (item 61); stale-fix reuse when 0 (c5/c6 bit-identical to c4) | ✓ | §6.2 item 57 | gates clock offset | ✓ | PROVEN |
| EOL flag (item 66) — 0 on all 21 Tech#1 packets of both floats | ✓ | §6.2 item 62 | ✓ | ✓ | PROVEN |
| Clock retiming (item 73, 16 b twos, s) — −5, −1, −156 observed | ✓ | §6.2 item 65 | ✓ (gated) | ✓ | PROVEN |
| Tech2 expected counts: items 3/4/5 = descent/drift/ascent — (4,1,7) c1; (0,2,7) c2+ | ✓ | §6.3 items 3-5 | **items 4/5/6 (off-by-one)** | corrected + as-coded exposed | PROVEN (manual+raw agree; Coriolis shift documented) |
| Tech2 last reset (items 46–51) — 2025-03-02 05:04:58 | ✓ | §6.3 items 46-51 | ✓ | ✓ | PROVEN |
| Tech2 hydraulic type (item 58) = 0 (ARVOR) | ✓ | §6.3 item 58 | ✓ | ✓ | PROVEN |
| Tech2 ice flag (item 59) = 0 everywhere | ✓ | §6.3 item 59 | read | ✓ | PROVEN |
| CTD cycle (item 1); first-meas time items 2-4 = H(16 b)/M(8 b)/S(8 b) → day fraction | ✓ | §6.4 | `ctdValues(2)/24+(3)/1440+(4)/86400` | ✓ | PROVEN |
| CTD 15 PTS triplets, items 5–49, 16 b each | ✓ | §6.4 | ✓ | ✓ | PROVEN |
| All-zero triplet = fill/sentinel; all-empty packet flagged (MATLAB warns+drops — kept with `is_empty=True`, documented divergence) | ✓ | — | ✓ | ✓ (flag) | PROVEN |
| PRES = (twos16 + 10000)/10 — 9763→1976.30 dbar; 55622→8.60 dbar | ✓ | — | `sensor_2_value_for_pressure_2xx_*` | ✓ | PROVEN (exact parity w/ operator files) |
| TEMP = twos16/1000 — 182→0.182 °C; 0xFB90→−1.136 °C | ✓ | — | `sensor_2_value_for_temp_2xx_*` | ✓ | PROVEN |
| PSAL = u16/1000 (unsigned) — 34666→34.666 | ✓ | — | `sensor_2_value_for_salinity_2xx_*` | ✓ | PROVEN |
| Param1 cycle + float time (items 1, 3–8) — c0 2025-09-19 09:56:42 | ✓ | §6.15 | ✓ | ✓ | PROVEN |
| Param1 remaining 60+ items (raw preserved) | ✓ | §6.15 | ✓ | raw only | PROVEN (layout) / deferred (semantics) |
| Hydraulic: ref day/min (items 2-3); 13 × (type 8 b, refTime 16 b, pres 16 b twos, dur 16 b); type 0 = EV | ✓ | §6.16 | ✓ | ✓ | PROVEN |
| eml session headers (MOMSN/MTMSN/time/unit location/CEP) are transport metadata, not float times | ✓ | — | `read_mail_and_extract_attachment.m` | ✓ | PROVEN |
| Supplied `.eml` = header-only + sidecar `.sbd` (correction appended to investigation §2) | ✓ | — | upstream format = MIME | both supported | PROVEN |
| Mail-level duplicates: flag only; content retransmissions preserved | ✓ (none present) | — | `ignore_duplicated_mail_files.m` | ✓ | PROVEN (behaviour transcribed; no real duplicates in dataset) |

**Four-way agreement rule:** every implemented field agrees across raw bytes, manual, Coriolis
source and Python — with the single documented exception of the Tech#2 expected-count mapping,
where Coriolis itself disagrees with manual+raw (off-by-one). Per instructions, the
implementation was **not** forced to match Coriolis there; it exposes both readings.

## 3. Validation results

* **Tests added:** 30 unit + 27 integration = **57** (+1 mechanical script), all passing.
* **Full suite:** `1799 passed` vs pre-change baseline `1741 passed` (fresh-sandbox note: 16
  baseline failures were observed before installing the optional `gsw` extra — after
  `pip install gsw` the untouched baseline was 1741/1741 green; after this phase: 1799/1799).
* **Lint:** `ruff check src tests scripts` → all checks passed (pre-existing files were already
  clean; new files held to the same standard).
* **Mechanical Coriolis comparison:** `scripts/verify_arvor_i_tables.py` re-parses the vendored
  MATLAB `tabNbBits` vectors and confirms bit-for-bit equality for Tech#1 (74 items), Tech#2
  (79 items incl. unused tail), CTD (52), Param#1 (76, both engines — semantically identical),
  hydraulic (57); every table sums to 792 bits. CTDO and Param#2 tables exist in MATLAB but are
  intentionally not transcribed (unobserved in evidence data).
* **Active float (7902408) raw validation:** all 64 payloads decoded; histogram
  {0:19, 1:4, 2:23, 3:74, 4:19, 5:7, 6:38} + 8 padding rows matches the investigation exactly;
  engine 232 identified consistently from all 19 Tech#1 checksums; cycles 0–15 covered with
  10-day rhythm verified; cycles 13–15 confirmed metadata-less (missing emails); incomplete
  cycles under the corrected mapping = {2,3,5,6,7,8,10,11}, complete = {1,4,9,12} — exactly as
  PROVEN during investigation; MOMSN gap list reproduced.
* **Dead float (6990711) raw validation:** all 35 payloads decoded; histogram
  {0:7, 1:4, 2:13, 3:49, 4:7, 6:15} + 10 padding rows; engine 222 family; all 7 cycles complete
  (received == expected for every cycle); final-burst order c7→c5→c6 on 2025-05-01/02 confirmed;
  no EOL flag on any packet; stale-GPS reuse for cycles 5/6 confirmed byte-identical.
* **Operator ground-truth parity (independent of Coriolis code):** decoded physical triplets
  reproduce the operator reference files exactly — all 7 Ascctd cycles (102–105 pts each),
  Subctd001, Desctd001 (incl. the −1.136 °C negative-temperature case), and 7902408 Ascctd001.

## 4. Explicit limitations (deferred)

1. **Packet types 7, 8–14**: not implemented (never observed in the evidence datasets; MATLAB
   tables exist but are deliberately not transcribed — no invented support).
2. **Cycle reconstruction / buffers** (`create_decoding_buffers_222_223_225_232.m` semantics:
   session segmentation, completion, EOL retransmission dedup, rankByCycle) — deferred to the
   next phase. Phase 1 deliberately stops at structured packets.
3. **NetCDF outputs** (`_prof.nc`, `_tech.nc`, `_Rtraj.nc`, meta) — not started.
4. **Param#1/Param#2 mission-parameter semantics** (CONFIG_* mapping, item 69/70 conventions
   beyond layout) — raw items only.
5. **Cycle-date assembly** (`compute_prv_dates_212_214_217`), GPS JAMSTEC QC, trajectory
   binning, clock-offset application — not in scope.
6. **Decoder-id disambiguation inside {222,223,225}**: checksum alone cannot separate them
   (Coriolis uses float metadata); irrelevant for decoding (shared layout) but relevant for
   provenance — deferred to metadata integration.
7. **`decode_prv_data_ir_sbd_221` (CTS4/Arvor-Deep-Ice) family** — the pre-existing repo plugin
   targets it; its single-packet framing of 300-B payloads deserves re-examination against
   `decode_sbd_file.m` (which frames all families as 100-B rows). Flagged as an observation
   only — no changes made (out of scope).
8. The supplied dataset's missing emails (7902408 cycles 2–15) are a **data-coverage
   limitation**; nothing in the decoder fabricates or back-fills them.

## 5. Recommended next step

**Structured packets → packet grouping → cycle reconstruction** (Phase 2), i.e. a faithful
Python port of `create_decoding_buffers_222_223_225_232.m` *per the corrected Tech#2 mapping*,
producing per-cycle buffers with `completed/delayed/deep/go` flags:

1. session segmentation (new 0/4/5 with higher cycle + later date; 0.5-day gap; 10-min merge;
   EOL split),
2. per-(session, cycle) buffers + `check_buffer` completion rule (Tech#1+Tech#2 required;
   type-5 exempt for this family; rec≥exp per phase),
3. reset handling, EOL retransmission dedup, second-Iridium-session split, rankByCycle,
4. validated against both real datasets: dead float → 7 complete cycles + final-burst ordering;
   active float → the exact complete/incomplete cycle sets recorded in §3.

Dependency order is confirmed by the evidence: cycle metadata (dates, GPS, expected counts)
comes from the packets Phase 1 now produces, and no earlier step is missing.
