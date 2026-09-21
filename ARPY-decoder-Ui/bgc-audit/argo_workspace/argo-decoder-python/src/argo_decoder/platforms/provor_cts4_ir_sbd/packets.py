"""Packet dispatch for PROVOR CTS4 / decoder-301 telemetry (Phase 1).

Implementation contract: ``provor_bio_irsbd/PROVOR_CTS4_PHASE1_DESIGN_NOTE.md`` §1/§6.

Byte authority: NKE ``5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924`` §7 (first-party
manual; preserved at ``provor_bio_irsbd/ref/``). Packet naming follows NKE §7.2:

* byte0 ``0x00`` → sensor-data measurement, sub-routed by byte1 (``0`` CTD,
  ``3`` oxygen, ``6`` FLBB). Bytes2-3 = cycle identifier (u16be), byte4 =
  profile number, byte5 = phase number, bytes6-9 = 1st-sample date; sensor
  records start at byte 10 (NKE §7.2.4.1-§7.2.4.3).
* byte0 ``0xFF`` → 255, PV & PM mission parameters (NKE §7.2.4.4).
* byte0 ``0xFE`` → 254, PT technical parameters (NKE §7.2.4.5).
  Both parameter packets share a 10-byte header: date bytes1-6
  (``DD MM YY HH MM SS``), cycle bytes7-8 (u16be), profile byte9. Parameter
  words from byte 10 on are uninterpreted in Phase 1.
* byte0 ``0xFD`` → 253, vector technical data (NKE §7.2.4.6; routed, opaque).
* byte0 ``0xFC`` → 252, pressure packet (NKE §7.2.4.7; routed, opaque).
* byte0 ``0xFA`` → 250, sensor technical data (NKE §7.2.4.9; routed, opaque).

Packet 251 (``0xFB``, sensor parameters, NKE §7.2.4.8) is transmitted only when a
parameter changed since the previous session, and is absent from the 517-file
corpus. Any byte0 outside the six observed values raises loudly: Phase 1 has no
silent skips, and a new value is a discovery, not noise.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from argo_decoder.platforms.provor_cts4_ir_sbd.framer import FramedFile

#: Length of the type-0 measurement header in bytes (NKE §7.2.4.1-§7.2.4.3:
#: type, subtype, cycle u16, profile, phase, 1st-sample date u32); sensor
#: records start at this offset for every type-0 subtype (CTD and FLBB alike).
HEADER_LEN = 10

#: Offset of the 1st-sample date field in the type-0 header (NKE §7.2.4.1:
#: "bytes6-9 = 1st-sample date").
HEADER_DATE_OFFSET = 6

#: Days from the 1950-01-01 Argo epoch to 2000-01-01. Exactly 50 x 365 days
#: with the 13 leap days of 1952..1996 — an exact day count, not a fitted
#: constant. The type-0 date field counts SECONDS since 2000-01-01 00:00 UTC.
JULD_EPOCH_OFFSET_DAYS = 18262.0

#: Seconds per day, for converting the type-0 date field to JULD days.
SECONDS_PER_DAY = 86400.0


def meas_first_sample_juld(header: bytes) -> float:
    """Argo JULD of a type-0 packet's first sample, from header bytes6-9.

    NKE §7.2.4.1 documents bytes6-9 of the type-0 measurement header as the
    "1st-sample date". On the 517-file decoder-301 corpus the field is a
    big-endian u32 count of seconds since 2000-01-01 00:00 UTC; Argo JULD is
    days since 1950-01-01, so

        JULD = 18262 + seconds_since_2000 / 86400

    with 18262 d the exact 1950-01-01 -> 2000-01-01 day count.

    Verified on INCOIS 2902093: the reconstructed MC 290 park series matches
    every published JULD exactly (residual 0.000000 s) on all 9 cycles x 3
    sensors (495/495 rows).

    Raises:
        ValueError: if ``header`` is shorter than the type-0 header length.
    """
    if len(header) < HEADER_LEN:
        raise ValueError(f"header too short for a type-0 date field: {len(header)} bytes")
    (seconds,) = struct.unpack_from(">I", header, HEADER_DATE_OFFSET)
    return JULD_EPOCH_OFFSET_DAYS + seconds / SECONDS_PER_DAY


#: Nominal sampling interval of one type-0 record within a packet, in days.
#: 12 h, the park/drift sampling period; every consecutive JULD step in the
#: INCOIS 2902093 MC 290 series is exactly 12.000000 h within a packet block.
MEAS_RECORD_INTERVAL_DAYS = 12.0 / 24.0


def meas_record_julds(header: bytes, n_records: int) -> tuple[float, ...]:
    """Argo JULD for each of a type-0 packet's ``n_records`` record slots.

    The type-0 header date field is the FIRST sample's time (NKE §7.2.4.1);
    subsequent slots in the same packet step by the nominal sampling interval.
    Padding slots are included — the caller drops them by its own padding rule,
    which keeps the JULD of every surviving record pinned to its own packet's
    own timestamp rather than to a count of surviving records.

    Raises:
        ValueError: if ``header`` is shorter than the type-0 header length.
    """
    first = meas_first_sample_juld(header)
    return tuple(first + k * MEAS_RECORD_INTERVAL_DAYS for k in range(n_records))


class PacketType(IntEnum):
    """First-byte packet discriminator (NKE §7.2; complete per corpus census)."""

    MEASUREMENT = 0x00
    SENSOR_TECH = 0xFA
    PRESSURE = 0xFC
    VECTOR_TECH = 0xFD
    TECH_PARAMS = 0xFE
    MISSION_PARAMS = 0xFF


class MeasSubtype(IntEnum):
    """Type-``0x00`` sensor discriminator (byte1; complete per census)."""

    CTD = 0
    DOXY_CLASS = 3
    OPTICS_FLBB = 6


class DispatchError(ValueError):
    """Base class for loud dispatch failures (no silent skips)."""


class UnknownPacketTypeError(DispatchError):
    """Raised for any first-byte value outside the six observed types."""


class UnknownMeasSubtypeError(DispatchError):
    """Raised for any type-``0x00`` byte1 value outside {0, 3, 6}."""


@dataclass(frozen=True)
class PacketDate:
    """Parameter-packet date header bytes1-6 (``DD MM YY HH MM SS``, NKE §7.2.4.4).

    Components are carried WITHOUT century interpretation: no datetime is built,
    so no windowing assumption can leak into decoder logic.
    """

    dd: int
    mm: int
    yy: int
    hh: int
    mi: int
    ss: int
    raw: bytes


@dataclass(frozen=True)
class ParamPacket:
    """Parameter packet: 255 mission params / 254 tech params (NKE §7.2.4.4-5).

    ``cycle`` is the u16be session cycle (bytes7-8); ``profile`` is the profile
    number (byte9). Parameter words from byte 10 on are uninterpreted in Phase 1
    and carried inside ``raw``.
    """

    kind: PacketType
    cycle: int
    profile: int
    date: PacketDate
    raw: bytes


@dataclass(frozen=True)
class MeasPacket:
    """Type-``0x00`` measurement packet (NKE §7.2.4.1-3 shared 10-byte header)."""

    subtype: MeasSubtype
    cycle: int
    profile: int
    phase: int
    header: bytes
    payload: bytes


@dataclass(frozen=True)
class OpaquePacket:
    """Routed-but-uninterpreted packet (``0xFA``/``0xFC``/``0xFD`` in Phase 1)."""

    kind: PacketType
    raw: bytes


Packet = ParamPacket | MeasPacket | OpaquePacket


@dataclass(frozen=True)
class DispatchedFile:
    """One framed file with every row routed to a packet object."""

    path: Path
    packets: tuple[Packet, ...]

    @property
    def kinds(self) -> frozenset[PacketType]:
        """Distinct packet types present (the file-kind signature)."""
        kinds: set[PacketType] = set()
        for packet in self.packets:
            if isinstance(packet, MeasPacket):
                kinds.add(PacketType.MEASUREMENT)
            else:
                kinds.add(packet.kind)
        return frozenset(kinds)


def _u16be(data: bytes) -> int:
    return int.from_bytes(data, "big")


def dispatch_row(row: bytes, *, index: int = 0) -> Packet:
    """Route one 140-byte row to its packet object.

    Raises:
        UnknownPacketTypeError: for any byte0 outside the six observed types.
        UnknownMeasSubtypeError: for any type-``0x00`` byte1 outside {0, 3, 6}.
    """
    try:
        kind = PacketType(row[0])
    except ValueError as exc:
        raise UnknownPacketTypeError(f"row {index}: unknown packet type 0x{row[0]:02X}") from exc
    if kind is PacketType.MEASUREMENT:
        try:
            subtype = MeasSubtype(row[1])
        except ValueError as exc:
            raise UnknownMeasSubtypeError(
                f"row {index}: unknown measurement subtype byte1={row[1]}"
            ) from exc
        return MeasPacket(
            subtype=subtype,
            cycle=_u16be(row[2:4]),
            profile=row[4],
            phase=row[5],
            header=bytes(row[:HEADER_LEN]),
            payload=bytes(row[HEADER_LEN:]),
        )
    if kind is PacketType.MISSION_PARAMS or kind is PacketType.TECH_PARAMS:
        return ParamPacket(
            kind=kind,
            cycle=_u16be(row[7:9]),
            profile=row[9],
            date=PacketDate(
                dd=row[1],
                mm=row[2],
                yy=row[3],
                hh=row[4],
                mi=row[5],
                ss=row[6],
                raw=bytes(row[1:7]),
            ),
            raw=bytes(row),
        )
    return OpaquePacket(kind=kind, raw=bytes(row))


def dispatch_framed(framed: FramedFile) -> DispatchedFile:
    """Route every row of a framed file (raises on the first unknown value)."""
    return DispatchedFile(
        path=framed.path,
        packets=tuple(dispatch_row(row, index=i) for i, row in enumerate(framed.rows)),
    )


__all__ = [
    "HEADER_LEN",
    "DispatchError",
    "DispatchedFile",
    "MeasPacket",
    "MeasSubtype",
    "OpaquePacket",
    "Packet",
    "PacketDate",
    "PacketType",
    "ParamPacket",
    "UnknownMeasSubtypeError",
    "UnknownPacketTypeError",
    "dispatch_framed",
    "dispatch_row",
]
