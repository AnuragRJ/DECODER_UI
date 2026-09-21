# Platform plugins

Platform plugins decode raw float frames into in-memory xarray Datasets.
They are selected **entirely by the decoder table** (Guardrails §7
"tables not code, plugins not if/else") — there are no
`if decoder_id == N` chains in the pipeline.

## Plugin interface

All plugins subclass :class:`argo_decoder.platforms.base.PlatformDecoder`
and are registered with the `@register_decoder` decorator. A plugin
implements:

* `can_handle(info, meta) -> bool` — returns ``True`` if this plugin can
  decode a float described by the supplied ``FloatInfo``/``FloatMeta``.
  Implementations consult the decoder table rather than hard-coding IDs.
* `decode_float(wmo, info, meta, cycles) -> DecodeResult` — consumes a
  list of :class:`argo_decoder.domain.frames.CycleData` (already grouped
  by cycle by the pipeline) and returns a :class:`DecodeResult` with
  per-cycle xarray Datasets.

The pipeline iterates registered plugins (skipping ``NullDecoder`` until
last) and instantiates the first one whose ``can_handle()`` returns
``True``; ``NullDecoder`` is always the final fallback.

## Dispatch flow

```
Pipeline runner
    │
    ├─► discover()            # rsync/input file enumeration
    ├─► MetadataLoader        # CSV/JSON/SQLite -> FloatInfo + FloatMeta
    ├─► group by cycle        # CycleData list of RawFrames
    └─► get_decoder(info, meta, config)
            │
            ▼ iterate registered plugins (NullDecoder last)
            │
            ├─► ProvorIridiumSbdDecoder  (Phase 2/3)
            ├─► ApexArgosDecoder         (Phase 4A: WRC/APEX ARGOS CTD)
            ├─► Future platform plugins  (NEMO/NOVA/Remocean/RUDICS)
            └─► NullDecoder (fallback)
```

## Provor / Arvor Iridium SBD plugin

The first real plugin ships in Phase 2 Slice 1
(``argo_decoder.platforms.provor_ir_sbd``). It handles
NKE Provor / Arvor / Arvor Deep CTS4 floats on Iridium SBD
(``transmission = "IRIDIUM_SBD"``).

### Module layout

```
platforms/provor_ir_sbd/
├── __init__.py        # public re-exports
├── decoder.py         # ProvorIridiumSbdDecoder plugin
└── frames.py          # BitReader, packet types, unpack_packet
```

`io/sbd_email.py` provides the MIME-aware e-mail parser that extracts
session metadata (MOMSN, GPS fix, CEPradius) and the 300-byte binary
payload from each ``co_*.txt`` file.

### Packet model

Each 300-byte SBD payload starts with a 1-byte ``packType`` tag,
followed by 299 bytes of bit-packed data. Supported types in Phase 2
Slice 1 (structural decoding only):

| packType | Meaning              | Dataclass    | Bins          |
|---------:|----------------------|--------------|---------------|
| 0        | Technical packet #1  | Tech1Packet  | — (GPS, time) |
| 1,2,3,13,14 | CTD (P, PT, PTS) | CtdPacket    | 15            |
| 4        | Technical packet #2  | SbdPacket    | —             |
| 5, 7     | Parameter packets    | SbdPacket    | —             |
| 6        | Pump / EV packet     | SbdPacket    | —             |
| 8–12     | CTD + Optode packets | CtdoPacket   | 7             |

Bit unpacking uses :class:`BitReader` — an MSB-first cursor that
matches MATLAB's ``get_bits()`` (1-indexed bits, MSB of the first byte
is bit 1).

### Sensors

Science conversion is delegated to sensor modules. Phase 2 Slice 1
ships a CTD skeleton (``sensors/ctd.py``) with calibration-coefficient
dataclasses and a placeholder linear conversion; the full
Sea-Bird polynomial + TEOS-10 salinity calculation lands in a later
slice, gated by oracle comparison.

### Files produced

Slice 1 emits one structural NetCDF per cycle with attributes
describing the unpacked packet mix (``n_tech1_packets``,
``n_ctd_packets``, ``n_ctdo_packets``, ``n_gps_fixes``,
``first_gps_lat``/``first_gps_lon``, decoder metadata). Science
variables (``PRES``, ``TEMP``, ``CNDC``, ``PSAL``, ``PRES_QC``, …) are
added in subsequent slices as sensor modules come online and are
validated against the MATLAB oracle.

## WRC/APEX ARGOS plugin

Phase 4A adds ``argo_decoder.platforms.apex_argos`` for WRC/APEX CTD
floats using ARGOS telemetry. The supported registry rows at Phase 4A
closure are:

| WMO | PTT | decoder_id | decoder_version | profile_class |
| ---: | ---: | ---: | --- | --- |
| 2901339 | 102510 | 1005 | 61810 | apf9_ctd_23 |
| 2902201 | 152399 | 1010 | 091515 | apf9_ctd_19 |
| 2902222 | 152389 | 1010 | 091615 | apf9_ctd_19 |
| 2902223 | 152382 | 1010 | 091615 | apf9_ctd_19 |

The plugin implements:

* CLS/Coriolis ARGOS format-1 multiline text parsing.
* WRC/APEX CRC validation and bit-majority reconstruction.
* MATLAB-equivalent message redundancy selection.
* APF9 CTD profile layouts for decoder IDs 1005 and 1010.
* Payload-derived output cycle numbers, including duplicate/superseded
  raw-file handling.
* Core CTD profile science output (PRES/TEMP/PSAL plus derived CNDC)
  through the shared NetCDF writer.

Raw/GDAC science audit coverage at Phase 4A closure:

* 82 supplied target raw ARGOS files audited.
* 77 pass against GDAC references.
* 2 are duplicate/superseded raw files for output cycles that another raw
  file matches.
* 3 decode successfully but lack public GDAC references at audit time
  (WMO 2902201 output cycles 359/360/361).

The plugin is **not** a universal ARGOS decoder for all manufacturers.
Future Phase 4 sub-slices must add separate table rows/plugins or profile
classes for Provor/NKE ARGOS, NEMO, NOVA, Remocean, and RUDICS families.

## Adding a new platform

1. Add the relevant rows to ``config/decoder_table.yaml`` (one per
   ``(platform_type, decoder_version)`` pair the plugin handles).
2. Create ``platforms/<platform_family>/`` with a ``decoder.py``
   containing a ``@register_decoder``-decorated subclass of
   :class:`PlatformDecoder`.
3. Import the package from ``platforms/__init__.py`` so registration
   fires at import time.
4. Add unit tests (plugin selection via ``get_decoder`` and at least one
   round-trip packet-decode test against a real sample from the demo
   corpus).
