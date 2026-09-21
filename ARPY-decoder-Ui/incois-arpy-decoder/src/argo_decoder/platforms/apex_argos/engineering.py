"""APEX APF9 engineering / technical message decoder.

Single authoritative source of engineering information for APEX ARGOS
floats. Products (``_tech.nc``, ``_Rtraj.nc``, ``_prof.nc``) consume the
decoded objects here rather than parsing messages themselves.

Evidence
--------

Byte layouts are now backed by the **primary firmware manuals** for the
supported revisions, retrieved from Git LFS and audited in
``docs/phase_reports/DOCUMENTATION_AUDIT_REPORT.md``:

* **D4** ``20100618_V061810_1772.A_rev20100907-Apex-User-Manual-APF9A.pdf``
  -- decoder 1005 (firmware ``061810``): layout p.20, ``STATUS`` p.21,
  SBE41 pp.21-22, unit conversions p.23.
* **D5/D6** ``20131106_V110613_...pdf`` / ``20130904_V090413_...pdf``
  -- decoder 1010: layout p.21, ``STATUS`` p.22.
* **D3** ``Firmware-082213-Appendix-G.pdf`` -- the University of
  Washington C source that constructs the messages.
* **D7** ``20070718_V071807-...FormatNotes.txt`` -- the earlier revision
  this module was originally written against; retained only as the
  fallback ``STATUS`` table for unknown firmware.

The audit confirmed the following, which had previously been inferred:

* ``SP`` is a **signed** 2's-complement centibar value (D4 p.23: pressure
  is "16-bit unsigned with 2's complement", ``P = Praw/10``; D3 p.4
  ``EncodeP``). Read unsigned it yields 6553 dbar; signed it yields the
  -0.3 to -0.5 dbar offsets seen across every cycle of WMO 2901339.
* ``EPOCH`` is **little-endian** (D5 p.19 states "little endian order"
  explicitly; D3 p.4 copies the ``time_t`` struct verbatim).
* ``PrfIdOverflow`` (``0x8000``) means the 8-bit profile counter wrapped
  (D4 p.21), which is why the cycle number is ``PRF + 256``.
* The field offsets used here reproduce the GDAC ``_tech.nc`` reference
  exactly. Note that reading the D5 byte table *literally* places ``SP``
  at spec byte 11 and yields -137.3 dbar against a reference of -0.4:
  the manual's byte numbering is relative to the on-air frame, whereas
  ``payload`` here starts at the message id. The offsets below are the
  verified ones and must not be "corrected" to match the table naively.

Fields the specification does not document for our firmware revisions
are left undecoded. Nothing here is inferred.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from argo_decoder.platforms.apex_argos.frames import SelectedArgosMessage

# ---------------------------------------------------------------------------
# Status bitfields (verbatim from the specification)
# ---------------------------------------------------------------------------

#: Engineering ``STATUS`` word, message 1 bytes 7-8, as defined by the
#: **071807** FormatNotes (D7). Bits 0x0200-0x1000 were redefined by later
#: firmware; see :data:`STATUS_BITS_061810`.
STATUS_BITS_071807: Mapping[str, int] = {
    "deep_profile": 0x0001,
    "shallow_water_trap": 0x0002,
    "sample_timeout_25min": 0x0004,
    "piston_full_extension": 0x0008,
    "ascent_timeout": 0x0010,
    "test_message": 0x0020,
    "prelude_message": 0x0040,
    "pressure_activation_message": 0x0080,
    "bad_sequence_point": 0x0100,
    "sbe41_p_fail": 0x0200,
    "sbe41_pt_fail": 0x0400,
    "sbe41_pts_fail": 0x0800,
    "sbe41_p_unreliable": 0x1000,
    "air_system_bypass": 0x2000,
    "watchdog_alarm": 0x4000,
    "profile_id_overflow": 0x8000,
}

#: ``STATUS`` word for firmware **061810** (decoder 1005) and **110613 /
#: 090413** (decoder 1010).
#:
#: Evidence: ``20100618_V061810_1772.A_rev20100907-Apex-User-Manual-APF9A.pdf``
#: p.21 and ``20131106_V110613_2361_rev20140814-Apex-User-Manual-APF9A.pdf``
#: p.22 list identical tables. Twelve bits match the 071807 FormatNotes
#: exactly; four differ:
#:
#: =======  =========================  ==============================
#: Mask     071807 (D7)                061810 / 110613 (D4 p.21, D5 p.22)
#: =======  =========================  ==============================
#: 0x0200   ``Sbe41PFail``             ``Sbe41Exception``
#: 0x0400   ``Sbe41PtFail``            ``Sbe41PUnreliable``
#: 0x0800   ``Sbe41PtsFail``           *"Not used yet"*
#: 0x1000   ``Sbe41PUnreliable``       *"Not used yet"*
#: =======  =========================  ==============================
#:
#: The two reserved masks are deliberately absent rather than renamed:
#: the manuals state they carry no meaning on these revisions, so
#: reporting a named flag for them would be an invented interpretation.
STATUS_BITS_061810: Mapping[str, int] = {
    "deep_profile": 0x0001,
    "shallow_water_trap": 0x0002,
    "sample_timeout_25min": 0x0004,
    "piston_full_extension": 0x0008,
    "ascent_timeout": 0x0010,
    "test_message": 0x0020,
    "prelude_message": 0x0040,
    "pressure_activation_message": 0x0080,
    "bad_sequence_point": 0x0100,
    "sbe41_exception": 0x0200,
    "sbe41_p_unreliable": 0x0400,
    "air_system_bypass": 0x2000,
    "watchdog_alarm": 0x4000,
    "profile_id_overflow": 0x8000,
}

#: Backwards-compatible default: the 071807 table.
#:
#: ``format_termination_flag`` and the cycle-number rule depend only on
#: the twelve stable bits and on ``0x8000``, so the emitted ``_tech.nc``
#: values are unaffected by which table is selected.
STATUS_BITS: Mapping[str, int] = STATUS_BITS_071807

#: Firmware-specific ``STATUS`` tables, keyed by MATLAB decoder id.
_STATUS_BITS_BY_DECODER: Mapping[int, Mapping[str, int]] = {
    1001: STATUS_BITS_061810,
    1005: STATUS_BITS_061810,
    1010: STATUS_BITS_061810,
}


def status_bits_for_decoder(decoder_id: int | None) -> Mapping[str, int]:
    """Return the documented ``STATUS`` bit table for a decoder id.

    Falls back to the 071807 FormatNotes table for unknown firmware,
    which is the most conservative choice: it names no bit that any
    APF9A revision leaves reserved.
    """
    if decoder_id is None:
        return STATUS_BITS_071807
    return _STATUS_BITS_BY_DECODER.get(int(decoder_id), STATUS_BITS_071807)


#: SBE41-specific status word, message 1 bytes 16-17.
SBE41_STATUS_BITS: Mapping[str, int] = {
    "p_pedantic_exception": 0x0001,
    "p_pedantic_fail": 0x0002,
    "p_regex_fail": 0x0004,
    "p_null_arg": 0x0008,
    "p_regex_exception": 0x0010,
    "p_no_response": 0x0020,
    "pts_pedantic_exception": 0x0100,
    "pts_pedantic_fail": 0x0200,
    "pts_regex_fail": 0x0400,
    "pts_null_arg": 0x0800,
    "pts_regex_exception": 0x1000,
    "pts_no_response": 0x2000,
}

#: Pressure sentinels defined by the spec's ``EncodeP``.
#:
#: ``0xFFFE`` and ``0xFFFF`` were previously listed here, but the
#: surface-pressure field is *signed* centibars, and as signed words
#: those are -2 and -1 cb, i.e. -0.2 and -0.1 dbar -- ordinary small
#: negative offsets rather than markers. The GDAC reference confirms it:
#: every WMO 2901304 cycle whose raw word is ``0xFFFE`` (1, 2, 3, 6, 9)
#: is published as ``PRES_SurfaceOffsetNotTruncated_dbar = -0.2``.
#: Treating them as sentinels silently dropped five of twenty-three
#: cycles. Only the saturation values at the ends of the signed range
#: remain, where a real reading of +/-3276 dbar is impossible.
_PRES_SENTINELS = {0x8000, 0x8001, 0x7FFF}


def decode_status_flags(word: int, bits: Mapping[str, int]) -> dict[str, bool]:
    """Expand a status word into named booleans."""
    return {name: bool(word & mask) for name, mask in bits.items()}


@dataclass(frozen=True)
class ApexEngineeringLayout:
    """Byte offsets of the message-1 engineering block for one firmware.

    ``block_shift`` is applied to every field after ``SP``; firmware
    ``061810`` packs that region one byte earlier than ``091615``.
    """

    decoder_ids: tuple[int, ...]
    #: Offset of the ``SP`` word relative to the documented layout.
    sp_shift: int
    #: Offset of the block after ``SP`` relative to the documented layout.
    block_shift: int
    notes: str
    #: Width in bytes of the ``SBE41`` status field. Firmware 061810
    #: transmits a 16-bit word (D4 p.20 "SBE41 status word - 16 bits");
    #: 110613/090413 transmit a 32-bit long-word (D5 p.21 "This
    #: long-word records the state of 32 status bits", corroborated by
    #: D3 p.5 ``ArgosPutLongWord(vitals.Sbe41Status)``).
    sbe41_width: int = 2
    #: Whether the auxiliary engineering block carries a ``VAC`` byte
    #: between ``TPI`` and ``NPMK``. D2 row 232 lists "Internal vacuum
    #: recorded when the park phase terminated" for firmware 061810;
    #: 110613/090413 omit it. Confirmed on every archived cycle.
    aux_has_vacuum: bool = True
    #: Payload offset of the park-end hydrographic sample in message 3.
    #: 061810 places it at the very start of the payload (offset 0);
    #: 110613/090413 prepend engineering fields, shifting it (D3 p.6).
    #: Verified on WMO 2901304 against the GDAC ``MC=290`` triplets: at
    #: offset 0 twenty of twenty-three cycles decode exactly, and the
    #: other three are all-filler payloads. Offset 1 matches none.
    park_sample_offset: int = 1
    #: Payload offset of the ``TELONICS`` PTT status byte, or ``None``
    #: when the firmware does not transmit one. Present only on
    #: 110613/090413 (D5 p.21 byte 9).
    telonics_offset: int | None = None
    #: Offset of the ``VAC``/``ABP`` pair inside the message-3 payload, or
    #: ``None`` when this firmware does not carry them there.
    #:
    #: Firmware 110613/091x15 moves both fields out of message 1 and into
    #: the head of message 3. The APF9A manual for 110613 (p.25, "Data
    #: Message 3 - N") gives ``2 VAC`` / ``3 ABP`` against a table whose
    #: bytes 0 and 1 are ``CRC`` and ``MSG``, so they are payload bytes 0
    #: and 1. Coriolis reads the same pair as fields 1 and 2 of
    #: ``tabNbBits = [1 1 2 2 2 2]`` at ``firstBit = 17``
    #: (``decode_data_apx_10.m:784``), which is the identical position.
    #:
    #: The 061810 message-3 table has no such prefix -- its park sample
    #: starts immediately -- so the offset stays ``None`` there.
    msg3_vacuum_offset: int | None = None


#: Firmware 061810 (MATLAB decoder id 1005) — the documented FormatNotes
#: offsets, confirmed field-by-field against the GDAC ``_tech.nc``
#: reference: piston positions and air-bladder pressure match on 11/11
#: comparable cycles of WMO 2901339.
APF9_ENG_1005 = ApexEngineeringLayout(
    decoder_ids=(1001, 1005),
    sp_shift=0,
    block_shift=0,
    notes="FormatNotes offsets as documented (firmware 061810).",
    park_sample_offset=0,
)

#: Firmware 091515 / 091615 (MATLAB decoder id 1010) — the block matches
#: the specification, but ``SP`` sits one byte later. Both halves are
#: confirmed against the GDAC ``_tech.nc`` reference for WMO 2902222:
#: at ``sp_shift=1`` the surface offset reads -0.4 dbar (reference
#: -0.4), and at ``block_shift=0`` the piston positions read 163/83/30
#: and pump time 0 s, all exactly matching the reference.
APF9_ENG_1010 = ApexEngineeringLayout(
    decoder_ids=(1010,),
    sp_shift=1,
    block_shift=0,
    notes="FormatNotes offsets, with SP one byte later (firmware 091x15).",
    sbe41_width=4,
    telonics_offset=7,
    park_sample_offset=4,
    aux_has_vacuum=False,
    msg3_vacuum_offset=0,
)

_ENG_LAYOUTS = (APF9_ENG_1005, APF9_ENG_1010)
_ENG_BY_DECODER = {
    decoder_id: layout for layout in _ENG_LAYOUTS for decoder_id in layout.decoder_ids
}


def engineering_layout_for_decoder(decoder_id: int) -> ApexEngineeringLayout | None:
    """Return the engineering layout for a MATLAB decoder id, if known."""
    return _ENG_BY_DECODER.get(int(decoder_id))


@dataclass
class ApexEngineeringData:
    """Decoded engineering state for one APEX cycle.

    Every field is ``None`` when the source message was absent or the
    value carried a documented sentinel. Nothing is defaulted to a
    plausible-looking number.
    """

    # --- message 1: identity ---
    profile_id: int | None = None
    profile_id_overflow: bool = False
    n_samples: int | None = None
    float_id: int | None = None

    # --- message 1: status ---
    status_word: int | None = None
    status_flags: dict[str, bool] = field(default_factory=dict)
    sbe41_status_word: int | None = None
    #: Raw TELONICS PTT status byte (decoder 1010 only). Bit meanings
    #: are not defined in any available document, so it is carried
    #: verbatim and never interpreted.
    telonics_status_byte: int | None = None
    sbe41_status_flags: dict[str, bool] = field(default_factory=dict)

    # --- message 1: engineering measurements ---
    surface_pressure_dbar: float | None = None
    vacuum_counts: int | None = None
    air_bladder_pressure_counts: int | None = None
    piston_position_surface_counts: int | None = None
    piston_position_park_end_counts: int | None = None
    piston_position_deep_descent_counts: int | None = None
    pump_motor_time_s: int | None = None
    battery_voltage_quiescent_counts: int | None = None
    battery_current_quiescent_counts: int | None = None
    battery_voltage_sbe41_counts: int | None = None
    battery_current_sbe41_counts: int | None = None
    battery_voltage_pump_counts: int | None = None
    battery_current_pump_counts: int | None = None
    battery_voltage_air_pump_counts: int | None = None
    battery_current_air_pump_counts: int | None = None
    air_pump_pulses: int | None = None
    air_pump_volt_seconds: int | None = None

    # --- message 2: cycle timing ---
    down_time_expiry: datetime | None = None
    telemetry_init_minutes: int | None = None
    n_park_ballast_adjustments: int | None = None

    # --- message 2: park-phase statistics (D4 pp.22-23; D3 p.6) ---
    park_sample_count: int | None = None
    park_temperature_mean: float | None = None
    park_pressure_mean: float | None = None
    park_temperature_stddev: float | None = None
    park_pressure_stddev: float | None = None
    park_temperature_min: float | None = None
    park_temperature_min_pressure: float | None = None
    park_temperature_max: float | None = None
    park_temperature_max_pressure: float | None = None
    park_pressure_min: float | None = None
    park_pressure_max: float | None = None

    # --- message 3: sample taken at the end of the park phase ---
    park_end_temperature: float | None = None
    park_end_salinity: float | None = None
    park_end_pressure: float | None = None

    # --- message 3 head, firmware 110613/091x15 only ---------------
    #: ``VAC`` -- internal vacuum [counts] recorded when the park phase
    #: terminated. Message-3 payload byte 0 on the firmware that carries
    #: it there; ``None`` on 061810, where the same quantity arrives in
    #: the auxiliary block as :attr:`park_end_vacuum_counts`.
    msg3_vacuum_counts: int | None = None
    #: ``ABP`` -- air bladder pressure [counts] recorded just after each
    #: Argos transmission. Message-3 payload byte 1, same firmware.
    msg3_air_bladder_counts: int | None = None

    # --- auxiliary engineering block (D3 p.7; D2 rows 228-237) ---
    pressure_divergence_dbar: float | None = None
    profile_init_offset_minutes: int | None = None
    park_end_vacuum_counts: int | None = None
    n_descent_pressure_marks: int | None = None
    descent_pressure_marks_bar: tuple[int, ...] = ()

    # --- ARGOS reception statistics (D2 rows 239-249) ---
    #
    # Derived from the received satellite data rather than from float
    # telemetry, so they are available for every cycle with a raw file.
    # ``argos_position_classes`` counts CLS quality classes verbatim.
    n_argos_positions: int | None = None
    argos_position_classes: Mapping[str, int] = field(default_factory=dict)
    n_transmission_frames: int | None = None
    n_transmission_frames_crc_ok: int | None = None

    # --- provenance ---
    decoder_id: int | None = None
    block_shift: int = 0
    messages_decoded: tuple[int, ...] = ()

    @property
    def is_deep_profile(self) -> bool:
        return bool(self.status_flags.get("deep_profile"))

    @property
    def hit_ascent_timeout(self) -> bool:
        return bool(self.status_flags.get("ascent_timeout"))

    @property
    def telemetry_init(self) -> datetime | None:
        """Absolute time telemetry was initiated, when both parts exist."""
        if self.down_time_expiry is None or self.telemetry_init_minutes is None:
            return None
        from datetime import timedelta

        return self.down_time_expiry + timedelta(minutes=self.telemetry_init_minutes)

    def as_dict(self) -> dict[str, object]:
        """Flat mapping of the populated scalar fields, for logging/attrs."""
        out: dict[str, object] = {}
        for key, value in self.__dict__.items():
            if key in ("status_flags", "sbe41_status_flags", "messages_decoded"):
                continue
            if value is None:
                continue
            out[key] = value.isoformat() if isinstance(value, datetime) else value
        return out


def _u8(payload: bytes, index: int) -> int | None:
    return payload[index] if 0 <= index < len(payload) else None


def _u16be(payload: bytes, index: int) -> int | None:
    if index < 0 or index + 2 > len(payload):
        return None
    return int.from_bytes(payload[index : index + 2], "big")


def _uint_be(payload: bytes, index: int, width: int) -> int | None:
    """Read a big-endian unsigned integer of ``width`` bytes."""
    if index < 0 or index + width > len(payload):
        return None
    return int.from_bytes(payload[index : index + width], "big")


def _decode_surface_pressure(payload: bytes, index: int) -> float | None:
    """Decode ``SP`` as signed centibars, honouring the spec sentinels."""
    raw = _u16be(payload, index)
    if raw is None or raw in _PRES_SENTINELS:
        return None
    signed: int = struct.unpack(">h", payload[index : index + 2])[0]
    return float(signed) / 10.0


#: Sentinel bands, matching the profile decoder.
_TS_SENTINELS = frozenset({0xF000, 0xEFFF, 0xF001})


def _decode_temperature(payload: bytes, index: int) -> float | None:
    raw = _u16be(payload, index)
    if raw is None or raw in _TS_SENTINELS:
        return None
    return (raw if raw < 0xEFFF else raw - 0x10000) / 1000.0


def _decode_salinity(payload: bytes, index: int) -> float | None:
    raw = _u16be(payload, index)
    if raw is None or raw in _TS_SENTINELS:
        return None
    return (raw if raw < 0xEFFF else raw - 0x10000) / 1000.0


def _decode_pressure(payload: bytes, index: int) -> float | None:
    raw = _u16be(payload, index)
    if raw is None or raw in _PRES_SENTINELS:
        return None
    return (raw if raw < 0x7FFF else raw - 0x10000) / 10.0


def decode_engineering_message_1(
    payload: bytes, layout: ApexEngineeringLayout, out: ApexEngineeringData
) -> None:
    """Decode the message-1 engineering block in place.

    ``payload`` is the message payload (frame bytes 2 onward), so spec
    byte ``n`` is ``payload[n - 2]``.
    """
    shift = layout.block_shift
    out.float_id = _u16be(payload, 1)
    out.profile_id = _u8(payload, 3)
    out.n_samples = _u8(payload, 4)

    status = _u16be(payload, 5)
    if status is not None:
        out.status_word = status
        out.status_flags = decode_status_flags(status, status_bits_for_decoder(out.decoder_id))
        out.profile_id_overflow = out.status_flags["profile_id_overflow"]

    out.surface_pressure_dbar = _decode_surface_pressure(payload, 7 + layout.sp_shift)
    out.vacuum_counts = _u8(payload, 9 + shift)
    out.air_bladder_pressure_counts = _u8(payload, 10 + shift)
    out.piston_position_surface_counts = _u8(payload, 11 + shift)
    out.piston_position_park_end_counts = _u8(payload, 12 + shift)
    out.piston_position_deep_descent_counts = _u8(payload, 13 + shift)

    # SBE41 status: 16-bit on firmware 061810, 32-bit long-word on
    # 110613/090413 (D5 p.21; D3 p.5 ``ArgosPutLongWord``). Only the low
    # 16 bits have documented meanings, so the extra bits are preserved
    # in the word but not expanded into invented flag names.
    sbe = _uint_be(payload, 14 + shift, layout.sbe41_width)
    if sbe is not None:
        out.sbe41_status_word = sbe
        out.sbe41_status_flags = decode_status_flags(sbe & 0xFFFF, SBE41_STATUS_BITS)

    # TELONICS PTT status byte, present only on 110613/090413 (D5 p.21
    # byte 9). The manuals define the field's existence but not its bit
    # meanings, so the raw byte is preserved and left uninterpreted.
    if layout.telonics_offset is not None:
        out.telonics_status_byte = _u8(payload, layout.telonics_offset)

    out.pump_motor_time_s = _u16be(payload, 16 + shift)
    out.battery_voltage_quiescent_counts = _u8(payload, 18 + shift)
    out.battery_current_quiescent_counts = _u8(payload, 19 + shift)
    out.battery_voltage_sbe41_counts = _u8(payload, 20 + shift)
    out.battery_current_sbe41_counts = _u8(payload, 21 + shift)
    out.battery_voltage_pump_counts = _u8(payload, 22 + shift)
    out.battery_current_pump_counts = _u8(payload, 23 + shift)
    out.battery_voltage_air_pump_counts = _u8(payload, 24 + shift)
    out.battery_current_air_pump_counts = _u8(payload, 25 + shift)
    out.air_pump_pulses = _u8(payload, 26 + shift)
    out.air_pump_volt_seconds = _u16be(payload, 27 + shift)


def decode_engineering_message_2(
    payload: bytes, layout: ApexEngineeringLayout, out: ApexEngineeringData
) -> None:
    """Decode the message-2 cycle-timing header in place.

    ``EPOCH`` is a signed 4-byte **little-endian** UNIX timestamp, as the
    specification states; big-endian decoding yields dates decades away
    from the deployment and is rejected here by a sanity window.
    """
    # Message 2 is not affected by the message-1 block shift: EPOCH sits
    # at payload offset 0 on both firmware revisions (verified against
    # 061810 and 091615 raw messages).
    del layout
    start = 0
    if start + 4 > len(payload):
        return
    epoch = struct.unpack("<i", payload[start : start + 4])[0]
    # Accept only timestamps inside the Argo programme's lifetime.
    if 946684800 < epoch < 2524608000:  # 2000-01-01 .. 2050-01-01
        out.down_time_expiry = datetime.fromtimestamp(epoch, UTC)
    if start + 6 <= len(payload):
        out.telemetry_init_minutes = struct.unpack(">h", payload[start + 4 : start + 6])[0]
    if start + 7 <= len(payload):
        out.n_park_ballast_adjustments = payload[start + 6]

    # Park-phase statistics, D4 pp.22-23 (spec bytes 9-30) and D3 p.6.
    # ``payload`` excludes the message id, so spec byte n is
    # ``payload[n - 2]``. Verified against the GDAC reference: for WMO
    # 2902222 cycle 327 TMEAN/PMEAN decode to 2.750 degC / 1000.9 dbar,
    # which the reference reports verbatim at MC 296.
    out.park_sample_count = _u16be(payload, 7)
    out.park_temperature_mean = _decode_temperature(payload, 9)
    out.park_pressure_mean = _decode_pressure(payload, 11)
    out.park_temperature_stddev = _decode_temperature(payload, 13)
    out.park_pressure_stddev = _decode_pressure(payload, 15)
    out.park_temperature_min = _decode_temperature(payload, 17)
    out.park_temperature_min_pressure = _decode_pressure(payload, 19)
    out.park_temperature_max = _decode_temperature(payload, 21)
    out.park_temperature_max_pressure = _decode_pressure(payload, 23)
    out.park_pressure_min = _decode_pressure(payload, 25)
    out.park_pressure_max = _decode_pressure(payload, 27)


def decode_engineering_message_3(
    payload: bytes, layout: ApexEngineeringLayout, out: ApexEngineeringData
) -> None:
    """Decode the park-end hydrographic sample from message 3.

    D4 p.23 states the end-of-park sample is transmitted first, in bytes
    2-7 of message 3, as T (2 bytes), S (2 bytes), P (2 bytes). On
    firmware 110613/090413 the message opens with two extra engineering
    fields before that sample (D3 p.6), which shifts it by three bytes.

    Verified against the GDAC reference: WMO 2902222 cycle 327 decodes
    to 2.731 degC / 34.548 / 1004.2 dbar, exactly the reference MC 290
    triplet.
    """
    if layout.msg3_vacuum_offset is not None:
        index = layout.msg3_vacuum_offset
        out.msg3_vacuum_counts = _u8(payload, index)
        out.msg3_air_bladder_counts = _u8(payload, index + 1)

    base = layout.park_sample_offset
    out.park_end_temperature = _decode_temperature(payload, base)
    out.park_end_salinity = _decode_salinity(payload, base + 2)
    out.park_end_pressure = _decode_pressure(payload, base + 4)


def decode_auxiliary_engineering(
    tail: bytes, layout: ApexEngineeringLayout, out: ApexEngineeringData
) -> None:
    """Decode the auxiliary engineering block in place.

    The block occupies whatever room is left in the final message after
    the hydrographic profile (D3 p.7). Its fields are written in a fixed
    order, each only if there is space:

    ``PDIVMAX`` (2 bytes, centibars), ``TPI`` (2 bytes, signed minutes),
    optionally ``VAC`` (1 byte, firmware 061810 only -- D2 row 232),
    ``NPMK`` (1 byte) and then ``NPMK`` single-byte descent pressure
    marks in bar (D2 rows 234-237).

    ``0xFF`` is the documented filler, so a field that reads as filler is
    treated as absent rather than as a value.
    """
    if len(tail) < 2:
        return
    out.pressure_divergence_dbar = _decode_pressure(tail, 0)
    if len(tail) < 4:
        return
    out.profile_init_offset_minutes = struct.unpack(">h", tail[2:4])[0]

    index = 4
    if layout.aux_has_vacuum:
        if len(tail) <= index:
            return
        vacuum = tail[index]
        out.park_end_vacuum_counts = None if vacuum == 0xFF else vacuum
        index += 1

    if len(tail) <= index:
        return
    count = tail[index]
    index += 1
    if count == 0xFF:
        return
    out.n_descent_pressure_marks = count
    marks = [b for b in tail[index : index + count] if b != 0xFF]
    out.descent_pressure_marks_bar = tuple(marks)


def decode_engineering(
    selected_messages: Sequence[SelectedArgosMessage],
    *,
    decoder_id: int,
) -> ApexEngineeringData | None:
    """Decode all available engineering content for one cycle.

    Returns ``None`` when the firmware has no known engineering layout,
    so callers can distinguish "unsupported" from "decoded but empty".
    """
    layout = engineering_layout_for_decoder(decoder_id)
    if layout is None:
        return None
    by_number = {msg.message_number: msg for msg in selected_messages}
    out = ApexEngineeringData(decoder_id=decoder_id, block_shift=layout.block_shift)
    decoded: list[int] = []
    if 1 in by_number:
        decode_engineering_message_1(by_number[1].payload, layout, out)
        decoded.append(1)
    if 2 in by_number:
        decode_engineering_message_2(by_number[2].payload, layout, out)
        decoded.append(2)
    if 3 in by_number:
        decode_engineering_message_3(by_number[3].payload, layout, out)
        decoded.append(3)
    if not decoded:
        return None
    out.messages_decoded = tuple(decoded)
    return out


__all__ = [
    "APF9_ENG_1005",
    "APF9_ENG_1010",
    "SBE41_STATUS_BITS",
    "STATUS_BITS",
    "STATUS_BITS_061810",
    "STATUS_BITS_071807",
    "ApexEngineeringData",
    "ApexEngineeringLayout",
    "decode_auxiliary_engineering",
    "decode_engineering",
    "decode_engineering_message_1",
    "decode_engineering_message_2",
    "decode_engineering_message_3",
    "decode_status_flags",
    "engineering_layout_for_decoder",
    "status_bits_for_decoder",
]
