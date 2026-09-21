# Phase 6A.3 — APEX engineering / technical message map

Date: 2026-07-27

Stage 1 (reverse engineering) and Stage 2 (gap analysis), recorded
before implementation.

## Sources searched

| Source | Result |
| --- | --- |
| `decArgo_soft/soft/sub/` (MATLAB decoders) | **absent** — the container ships only `util/`, `util2/`, `sub_foreign/`; `decode_data_apx_10.m`, `decode_data_apx_1_5.m`, `get_apex_data_sensor.m`, `check_crc_apx.m` are all missing |
| `extract_conf_tech_apx_ir_sbd.m` / `_rudics.m` | present but target **Iridium** text `.msg` files, a different transport, and depend on the absent `sub/` helpers |
| `decArgo_doc/float_user_manuals/APEX_floats/Argos/*.pdf` | **Git LFS pointers** (131 bytes each), content never fetched |
| `20070718_...FormatNotes.txt` | **REAL, 24 KB** — authoritative byte-level APF9A format specification |
| `...APF9A-Optode.doc` | real 1.7 MB Word document (2008 revision) |
| GDAC `_Rtraj.nc` / `_tech.nc` | populated engineering-derived fields, usable as ground truth |
| Archived ARGOS raw files | 82 files across 4 floats, 2 firmware revisions |

The FormatNotes file is the primary evidence for this phase. It
documents firmware `Apf9aSbe41Ido-071807`; our floats run `061810` and
`091615`, so **every field was re-validated against the real bytes**
rather than assumed to carry over.

## Message 1 — engineering block (validated)

Spec byte offsets are relative to the on-air frame
`[CRC, MSG, BLK, ...]`. Our `payload` property strips the first two
bytes, so `payload[i] == frame[i + 2]`.

| Frame byte | Field | Encoding | Units | Destination |
| ---: | --- | --- | --- | --- |
| 0 | CRC | uint8 | — | integrity (already implemented) |
| 1 | MSG | uint8 | — | message routing |
| 2 | BLK | uint8 | — | block id |
| 3,4 | FLT | uint16 BE | — | float/ARGOS id |
| 5 | PRF | uint8 | — | profile id mod 256 |
| 6 | LEN | uint8 | — | TSP sample count |
| 7,8 | STATUS | uint16 BE bitfield | — | status flags (below) |
| 9,10 | SP | **int16 BE**, centibars | dbar/10 | surface-pressure offset |
| 11 | VAC | uint8 counts | counts | internal vacuum |
| 12 | ABP | uint8 counts | counts | air-bladder pressure |
| 13 | SPP | uint8 counts | counts | piston at surface detection |
| 14 | PPP2 | uint8 counts | counts | piston at park end |
| 15 | PPP | uint8 counts | counts | piston at deep-descent end |
| 16,17 | SBE41 | uint16 BE bitfield | — | SBE41 status flags |
| 18,19 | PMT | uint16 BE | seconds | pump-motor run time |
| 20-27 | VQ,IQ,VSBE,ISBE,VHPP,IHPP,VAP,IAP | uint8 counts | counts | battery volt/current |
| 28 | PAP | uint8 | pulses | air-pump 6 s pulses |
| 29,30 | VSAP | uint16 BE | volt-seconds | air volume pumped |

### STATUS bits (reference table from the spec)

`0x0001 DeepPrf`, `0x0002 ShallowWaterTrap`, `0x0004 Obs25Min`,
`0x0008 PistonFullExt`, `0x0010 AscentTimeOut`, `0x0020 TestMsg`,
`0x0040 PreludeMsg`, `0x0080 PActMsg`, `0x0100 BadSeqPnt`,
`0x0200 Sbe41PFail`, `0x0400 Sbe41PtFail`, `0x0800 Sbe41PtsFail`,
`0x1000 Sbe41PUnreliable`, `0x2000 AirSysBypass`,
`0x4000 WatchDogAlarm`, `0x8000 PrfIdOverflow`.

**Independent confirmation:** WMO 2902222 cycle 327 decodes
`STATUS = 0x8001` (`DeepPrf | PrfIdOverflow`) with `PRF = 71`.
71 + 256 = 327, exactly the output cycle our Phase 4A decoder already
derives via `cycle_number_offset=256`. WMO 2901339 cycle 1 decodes
`STATUS = 0x0001` (no overflow) with `PRF = 2`. The spec's overflow bit
therefore *explains* a rule Phase 4A had derived empirically — strong
mutual validation of both the spec and our existing layout table.

## Firmware-dependent offset (discovered, not assumed)

Reading the block at the documented offsets gives plausible values for
firmware `091615` but nonsense for `061810` (6553 dbar surface pressure,
55 237 s pump time). Two corrections were established from the data:

1. **`SP` is signed.** The spec's `EncodeP` uses 2's-complement, so
   `0xFFFC` is −0.4 dbar, not 65 532 cbar. With signed decoding, WMO
   2901339 yields −0.3 to −0.5 dbar consistently across 10 cycles — a
   textbook surface-pressure offset.
2. **Firmware `061810` shifts the post-`SP` block one byte earlier.**
   With `shift = -1`, pump-motor time becomes 1635-1751 s (varying
   per cycle, physically sensible) and the SBE41 status word becomes
   `0x0000` (clean) instead of `0x0006`. This is corroborated
   independently by our existing profile layouts, where
   `first_profile_slice` is 12 for decoder 1010 and 8 for decoder 1005.

Both firmwares are therefore described by one table plus a per-decoder
offset, exactly as the profile layouts already are.

## Message 2 — cycle timing (validated)

| Payload byte | Field | Encoding | Units |
| ---: | --- | --- | --- |
| 0-3 | EPOCH | **int32 little-endian** | UNIX seconds |
| 4,5 | TINIT | int16 BE | minutes after EPOCH |
| 6 | NADJ | uint8 | ballast adjustments |
| 7+ | hydrographic samples | — | already decoded by Phase 4A |

`EPOCH` decodes to 2025-12-25 01:32:40 for 2902222 cycle 327 and
2011-12-27 16:41:55 for 2901339 cycle 1 — both plausible for their
deployment eras, on both firmwares, using little-endian as the spec
states. Big-endian yields year 2000/2014, i.e. wrong.

## Stage 2 — Gap analysis

### What this decoder can supply

| Product | Field | Status |
| --- | --- | --- |
| `_tech.nc` | surface pressure, vacuum, air-bladder pressure, 3 piston positions, pump-motor time, 8 battery counts, air-pump pulses, air volume, 16 STATUS bits, 16 SBE41 bits, NADJ | **decodable** |
| `_Rtraj.nc` | `CLOCK_OFFSET` inputs, down-time expiry (EPOCH), telemetry-init offset (TINIT) | **decodable** |
| `_meta.nc` | — | none; the config block is mission programming, carried in *test* messages, not data messages |
| `_prof.nc` | surface-pressure offset for `PRES_ADJUSTED` | **decodable** |

### What it cannot supply, with evidence

`EPOCH + TINIT` lands 10.8 min after the reference
`JULD_TRANSMISSION_START` for 2902222 cycle 327 and 11.9 min after it
for 2902223 cycle 327 — consistent between floats, so the fields are
being read correctly, but the DAC applies further firmware-specific
timing corrections (ascent-rate model, transmission-start lag) that this
2007 spec revision does not document. The precise
`JULD_ASCENT_END` / `JULD_TRANSMISSION_START` / `JULD_PARK_*` values
therefore remain out of reach, and profile `JULD` with them.

Mission-programming values (`CONFIG_*` in `_meta.nc`) live in **test
messages**, transmitted during the mission prelude. Our archive contains
only data-message cycle files, so those remain unavailable.

## Implementation decision

Implement the fields the evidence supports — the full Message 1
engineering block, the STATUS/SBE41 bitfields, and Message 2
EPOCH/TINIT/NADJ — as a single reusable decoder that products consume.
Do **not** synthesise `JULD_ASCENT_END` and friends from EPOCH+TINIT:
the residual is real and undocumented, and writing a value 11 minutes
wrong would be worse than leaving the ADMT fill in place.
