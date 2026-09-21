"""Authoritative BGC raw extraction for PROVOR CTS4 / decoder-301 (Phase 2A).

Implementation contract: ``provor_bio_irsbd/PROVOR_CTS4_PHASE1_DESIGN_NOTE.md``
§1/§6 as extended by the Phase-2A scope (raw decode only; calibration
coefficients and derived equations live in :mod:`equations`).

Byte authority: NKE ``5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924`` §7.2.4.2
(oxygen) and §7.2.4.3 (FLBB). Both share the 10-byte type-0 header already
split by :mod:`packets` (type, subtype, cycle u16, profile, phase, 1st-sample
date u32 = seconds since 2000-01-01); sensor records start at byte 10.

Oxygen average (subtype 3, NKE §7.2.4.2.1): 10 stride-12 records
``(P s16be, C1 s32be, C2 s32be, T u16be)`` + 10-byte zero complement::

    pres_dbar = P_raw / 10            (cBar, signed INT — same wire field and
                                       divisor as the settled CTD extraction)
    c1_phase_deg = C1_raw / 1000      (millidegrees, signed LONG INT)
    c2_phase_deg = C2_raw / 1000      (millidegrees, signed LONG INT)
    temp_c = (T_raw - 2000) / 1000    (m°C with 2000 m°C offset)

FLBB average (subtype 6, NKE §7.2.4.3.1): 21 stride-6 records
``(P s16be, Chl u16be, BB u16be)`` + 4-byte zero complement::

    pres_dbar = P_raw / 10            (cBar, signed INT)
    fluorescence_counts = Chl_raw / 10   ("Chlorophyll: in Count * 10")
    backscatter_counts = BB_raw / 10     ("Backscatter: in Count * 10")

The ``/ 10`` count scaling is the NKE resolution statement, independently
confirmed by GDAC reference ``BD2902091_001.nc`` profile 3, whose
``FLUORESCENCE_CHLA`` / ``BETA_BACKSCATTERING700`` values carry 0.1-count
resolution (e.g. 175.2 / 146.3; evidence in
``provor_bio_irsbd/ref/gdac_incois_301/``).

All-zero records are short-profile padding (same convention as :mod:`ctd`):
carried with formula-applied values, never physical measurements. The
1st-sample date (bytes6-9) is carried as the raw second count; use
:func:`sample_datetime` for an explicit epoch interpretation (no windowing:
the epoch is fixed at 2000-01-01 by the manual).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from argo_decoder.platforms.provor_cts4_ir_sbd.packets import MeasPacket, MeasSubtype

if TYPE_CHECKING:
    from argo_decoder.platforms.provor_cts4_ir_sbd.packets import DispatchedFile

#: Offset where type-0 sensor records begin (NKE §7.2.4.2-3: 10-byte header).
BGC_HEADER_LEN = 10

#: Bytes per oxygen record: ``(P s16be, C1 s32be, C2 s32be, T u16be)``.
O2_RECORD_STRIDE = 12
#: Records per 140-byte packet: ``(140 - 10 - 10) // 12``.
O2_RECORDS_PER_PACKET = 10
#: Trailing zero complement after the last record; preserved.
O2_TAIL_LEN = 10

#: Bytes per FLBB record: ``(P s16be, Chl u16be, BB u16be)``.
FLBB_RECORD_STRIDE = 6
#: Records per 140-byte packet: ``(140 - 10 - 4) // 6``.
FLBB_RECORDS_PER_PACKET = 21
#: Trailing zero complement after the last record; preserved.
FLBB_TAIL_LEN = 4

#: NKE §7.2.4.2-3 resolution: cBar → dbar (same convention as :mod:`ctd`).
BGC_PRES_DIVISOR = 10.0
#: NKE §7.2.4.2 resolution: millidegrees → degrees (C1/C2 phase).
O2_PHASE_DIVISOR = 1000.0
#: NKE §7.2.4.2 resolution: optode temperature offset in m°C.
O2_TEMP_OFFSET = 2000
#: NKE §7.2.4.2 resolution: m°C → °C.
O2_TEMP_DIVISOR = 1000.0
#: NKE §7.2.4.3 resolution: "Count * 10" → counts.
FLBB_COUNT_DIVISOR = 10.0

#: Epoch of the type-0 1st-sample date: 2000-01-01T00:00:00Z (NKE §7.2.4.1-3).
SBD_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


def sample_datetime(sample_date_s: int) -> datetime:
    """Interpret a type-0 1st-sample date as an aware UTC datetime.

    The epoch is fixed by the manual (2000-01-01); there is no century
    windowing anywhere in this conversion.
    """
    return SBD_EPOCH + __import__("datetime").timedelta(seconds=sample_date_s)


@dataclass(frozen=True)
class O2Record:
    """One oxygen record: wire-order raw fields + NKE-scaled values."""

    p_raw: int
    c1_raw: int
    c2_raw: int
    t_raw: int
    pres_dbar: float
    c1_phase_deg: float
    c2_phase_deg: float
    temp_c: float


@dataclass(frozen=True)
class O2PacketData:
    """Oxygen content of one type-``0x00``/byte1==3 packet."""

    packet_index: int
    cycle: int
    profile: int
    phase: int
    sample_date_s: int
    records: tuple[O2Record, ...]
    tail: bytes


@dataclass(frozen=True)
class FlbbRecord:
    """One FLBB record: wire-order raw fields + NKE-scaled values."""

    p_raw: int
    chl_raw: int
    bb_raw: int
    pres_dbar: float
    fluorescence_counts: float
    backscatter_counts: float


@dataclass(frozen=True)
class FlbbPacketData:
    """FLBB content of one type-``0x00``/byte1==6 packet."""

    packet_index: int
    cycle: int
    profile: int
    phase: int
    sample_date_s: int
    records: tuple[FlbbRecord, ...]
    tail: bytes


def _packet_date_s(packet: MeasPacket) -> int:
    return int.from_bytes(packet.header[6:10], "big")


def extract_o2(packet: MeasPacket, *, packet_index: int = 0) -> O2PacketData:
    """Extract oxygen records from a type-``0x00``/byte1==3 packet.

    Raises:
        ValueError: if the packet is not an oxygen (byte1==3) packet.
    """
    if packet.subtype is not MeasSubtype.DOXY_CLASS:
        raise ValueError(f"packet {packet_index}: not an O2 packet (subtype={packet.subtype})")
    payload = packet.header + packet.payload
    records: list[O2Record] = []
    for record_no in range(O2_RECORDS_PER_PACKET):
        offset = BGC_HEADER_LEN + record_no * O2_RECORD_STRIDE
        p_raw, c1_raw, c2_raw, t_raw = struct.unpack_from(">hiiH", payload, offset)
        records.append(
            O2Record(
                p_raw=p_raw,
                c1_raw=c1_raw,
                c2_raw=c2_raw,
                t_raw=t_raw,
                pres_dbar=p_raw / BGC_PRES_DIVISOR,
                c1_phase_deg=c1_raw / O2_PHASE_DIVISOR,
                c2_phase_deg=c2_raw / O2_PHASE_DIVISOR,
                temp_c=(t_raw - O2_TEMP_OFFSET) / O2_TEMP_DIVISOR,
            )
        )
    tail = bytes(payload[BGC_HEADER_LEN + O2_RECORDS_PER_PACKET * O2_RECORD_STRIDE :])
    return O2PacketData(
        packet_index=packet_index,
        cycle=packet.cycle,
        profile=packet.profile,
        phase=packet.phase,
        sample_date_s=_packet_date_s(packet),
        records=tuple(records),
        tail=tail,
    )


def extract_flbb(packet: MeasPacket, *, packet_index: int = 0) -> FlbbPacketData:
    """Extract FLBB records from a type-``0x00``/byte1==6 packet.

    Raises:
        ValueError: if the packet is not an FLBB (byte1==6) packet.
    """
    if packet.subtype is not MeasSubtype.OPTICS_FLBB:
        raise ValueError(
            f"packet {packet_index}: not an FLBB packet (subtype={packet.subtype})"
        )
    payload = packet.header + packet.payload
    records: list[FlbbRecord] = []
    for record_no in range(FLBB_RECORDS_PER_PACKET):
        offset = BGC_HEADER_LEN + record_no * FLBB_RECORD_STRIDE
        p_raw, chl_raw, bb_raw = struct.unpack_from(">hHH", payload, offset)
        records.append(
            FlbbRecord(
                p_raw=p_raw,
                chl_raw=chl_raw,
                bb_raw=bb_raw,
                pres_dbar=p_raw / BGC_PRES_DIVISOR,
                fluorescence_counts=chl_raw / FLBB_COUNT_DIVISOR,
                backscatter_counts=bb_raw / FLBB_COUNT_DIVISOR,
            )
        )
    tail = bytes(payload[BGC_HEADER_LEN + FLBB_RECORDS_PER_PACKET * FLBB_RECORD_STRIDE :])
    return FlbbPacketData(
        packet_index=packet_index,
        cycle=packet.cycle,
        profile=packet.profile,
        phase=packet.phase,
        sample_date_s=_packet_date_s(packet),
        records=tuple(records),
        tail=tail,
    )


def o2_records_for_file(dispatched: DispatchedFile) -> tuple[O2Record, ...]:
    """All oxygen records in a dispatched file, in packet order."""
    records: list[O2Record] = []
    for index, packet in enumerate(dispatched.packets):
        if isinstance(packet, MeasPacket) and packet.subtype is MeasSubtype.DOXY_CLASS:
            records.extend(extract_o2(packet, packet_index=index).records)
    return tuple(records)


def flbb_records_for_file(dispatched: DispatchedFile) -> tuple[FlbbRecord, ...]:
    """All FLBB records in a dispatched file, in packet order."""
    records: list[FlbbRecord] = []
    for index, packet in enumerate(dispatched.packets):
        if isinstance(packet, MeasPacket) and packet.subtype is MeasSubtype.OPTICS_FLBB:
            records.extend(extract_flbb(packet, packet_index=index).records)
    return tuple(records)


__all__ = [
    "BGC_HEADER_LEN",
    "BGC_PRES_DIVISOR",
    "FLBB_COUNT_DIVISOR",
    "FLBB_RECORDS_PER_PACKET",
    "FLBB_RECORD_STRIDE",
    "FLBB_TAIL_LEN",
    "O2_PHASE_DIVISOR",
    "O2_RECORDS_PER_PACKET",
    "O2_RECORD_STRIDE",
    "O2_TAIL_LEN",
    "O2_TEMP_DIVISOR",
    "O2_TEMP_OFFSET",
    "SBD_EPOCH",
    "FlbbPacketData",
    "FlbbRecord",
    "O2PacketData",
    "O2Record",
    "extract_flbb",
    "extract_o2",
    "flbb_records_for_file",
    "o2_records_for_file",
    "sample_datetime",
]
