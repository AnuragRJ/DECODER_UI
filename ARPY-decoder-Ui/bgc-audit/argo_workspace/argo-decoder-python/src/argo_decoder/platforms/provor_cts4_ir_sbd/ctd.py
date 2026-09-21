"""Authoritative CTD extraction for PROVOR CTS4 / decoder-301 telemetry (Phase 1).

Implementation contract: ``provor_bio_irsbd/PROVOR_CTS4_PHASE1_DESIGN_NOTE.md`` §4/§6.

Byte authority: NKE ``5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924`` §7.2.4.1
(first-party manual; preserved at ``provor_bio_irsbd/ref/``). Type-``0x00``/
byte1==0 packets carry 21 stride-6 records from offset 10 — ``(P_raw, T_raw,
S_raw)`` as (signed s16 pressure, u16 temperature, u16 salinity), big-endian —
followed by the 4-byte zero complement, which is preserved, never dropped.

Scaling (NKE resolution statements, §7.2.4.1):

* ``pres_dbar = P_raw / 10`` (pressure in cBar, signed INT);
* ``temp_c = (T_raw - 2000) / 1000`` (temperature in m°C with 2000 m°C offset);
* ``psal = S_raw / 1000`` (salinity in mPSU — single encoding; no ``+33``
  interpretation exists anywhere in this package).

All-zero records are short-profile padding: they are carried with formula-applied
values (``pres=0``, ``temp=-2``, ``psal=0``) and Phase 2 drops them per the
reference delete rule — they are never physical measurements. No BGC unit
conversion exists in Phase 1 (counts only; calibration is Phase-2+ work).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from argo_decoder.platforms.provor_cts4_ir_sbd.packets import MeasPacket, MeasSubtype

if TYPE_CHECKING:
    from argo_decoder.platforms.provor_cts4_ir_sbd.packets import DispatchedFile

#: Offset where type-0 sensor records begin (NKE §7.2.4.1: 10-byte header).
CTD_HEADER_LEN = 10
#: Bytes per CTD record: ``(P s16be, T u16be, S u16be)`` (NKE §7.2.4.1).
CTD_RECORD_STRIDE = 6
#: Records per 140-byte packet: ``(140 - 10 - 4) // 6``.
CTD_RECORDS_PER_PACKET = 21
#: Trailing zero complement after the last record (NKE §7.2.4.1); preserved.
CTD_TAIL_LEN = 4

#: NKE §7.2.4.1 resolution: temperature offset in m°C.
CTD_TEMP_OFFSET = 2000
#: NKE §7.2.4.1 resolution: m°C → °C.
CTD_TEMP_DIVISOR = 1000.0
#: NKE §7.2.4.1 resolution: cBar → dbar.
CTD_PRES_DIVISOR = 10.0
#: NKE §7.2.4.1 resolution: mPSU → PSU (single PSAL encoding).
CTD_PSAL_DIVISOR = 1000.0


@dataclass(frozen=True)
class CtdRecord:
    """One CTD record: wire-order raw triplet + NKE-scaled physical values."""

    p_raw: int
    t_raw: int
    s_raw: int
    pres_dbar: float
    temp_c: float
    psal: float


@dataclass(frozen=True)
class CtdPacketData:
    """CTD content of one type-``0x00``/byte1==0 packet."""

    packet_index: int
    cycle: int
    records: tuple[CtdRecord, ...]
    tail: bytes


def extract_ctd(packet: MeasPacket, *, packet_index: int = 0) -> CtdPacketData:
    """Extract CTD records from a type-``0x00``/byte1==0 packet.

    Raises:
        ValueError: if the packet is not a CTD (byte1==0) measurement packet.
    """
    if packet.subtype is not MeasSubtype.CTD:
        raise ValueError(f"packet {packet_index}: not a CTD packet (subtype={packet.subtype})")
    payload = packet.header + packet.payload
    records: list[CtdRecord] = []
    for record_no in range(CTD_RECORDS_PER_PACKET):
        offset = CTD_HEADER_LEN + record_no * CTD_RECORD_STRIDE
        p_raw, t_raw, s_raw = struct.unpack_from(">hHH", payload, offset)
        records.append(
            CtdRecord(
                p_raw=p_raw,
                t_raw=t_raw,
                s_raw=s_raw,
                pres_dbar=p_raw / CTD_PRES_DIVISOR,
                temp_c=(t_raw - CTD_TEMP_OFFSET) / CTD_TEMP_DIVISOR,
                psal=s_raw / CTD_PSAL_DIVISOR,
            )
        )
    tail = bytes(payload[CTD_HEADER_LEN + CTD_RECORDS_PER_PACKET * CTD_RECORD_STRIDE :])
    return CtdPacketData(
        packet_index=packet_index,
        cycle=packet.cycle,
        records=tuple(records),
        tail=tail,
    )


def ctd_records_for_file(dispatched: DispatchedFile) -> tuple[CtdRecord, ...]:
    """All CTD records in a dispatched file, in packet order."""
    records: list[CtdRecord] = []
    for index, packet in enumerate(dispatched.packets):
        if isinstance(packet, MeasPacket) and packet.subtype is MeasSubtype.CTD:
            records.extend(extract_ctd(packet, packet_index=index).records)
    return tuple(records)


__all__ = [
    "CTD_HEADER_LEN",
    "CTD_PRES_DIVISOR",
    "CTD_PSAL_DIVISOR",
    "CTD_RECORDS_PER_PACKET",
    "CTD_RECORD_STRIDE",
    "CTD_TAIL_LEN",
    "CTD_TEMP_DIVISOR",
    "CTD_TEMP_OFFSET",
    "CtdPacketData",
    "CtdRecord",
    "ctd_records_for_file",
    "extract_ctd",
]
