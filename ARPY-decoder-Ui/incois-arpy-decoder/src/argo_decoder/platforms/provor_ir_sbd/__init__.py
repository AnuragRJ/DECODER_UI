"""Provor / Arvor Iridium SBD platform plugin package."""

from __future__ import annotations

from argo_decoder.platforms.provor_ir_sbd.arvor_i import (
    ArvorCtdPacket,
    ArvorHydraulicPacket,
    ArvorIEngine,
    ArvorIPacket,
    ArvorIridiumMessage,
    ArvorParam1Packet,
    ArvorSbdDecode,
    ArvorTech1Packet,
    ArvorTech2Packet,
    ArvorUnsupportedPacket,
    SbdFramingError,
    UnsupportedEngineError,
    decode_arvor_i_sbd,
    read_arvor_i_eml,
    resolve_engine,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_decoder import ArvorISbdDecoder
from argo_decoder.platforms.provor_ir_sbd.decoder import ProvorIridiumSbdDecoder
from argo_decoder.platforms.provor_ir_sbd.frames import (
    BitReader,
    BitReaderEofError,
    CtdoPacket,
    CtdPacket,
    Param1Packet,
    Param2Packet,
    SbdPacket,
    SbdPacketType,
    Tech1Packet,
    Tech2Packet,
    unpack_packet,
)
from argo_decoder.platforms.provor_ir_sbd.mission import (
    MissionConfig,
    compute_ascent_end_offset_minutes,
    compute_profile_datetime,
    compute_trans_start_date,
)
from argo_decoder.platforms.provor_ir_sbd.profile import (
    ProfileMeta,
    assemble_profile_meta,
    datetime_to_juld,
    juld_to_datetime,
)

__all__ = [
    "ArvorCtdPacket",
    "ArvorHydraulicPacket",
    "ArvorIEngine",
    "ArvorIPacket",
    "ArvorISbdDecoder",
    "ArvorIridiumMessage",
    "ArvorParam1Packet",
    "ArvorSbdDecode",
    "ArvorTech1Packet",
    "ArvorTech2Packet",
    "ArvorUnsupportedPacket",
    "BitReader",
    "BitReaderEofError",
    "CtdPacket",
    "CtdoPacket",
    "MissionConfig",
    "Param1Packet",
    "Param2Packet",
    "ProfileMeta",
    "ProvorIridiumSbdDecoder",
    "SbdFramingError",
    "SbdPacket",
    "SbdPacketType",
    "Tech1Packet",
    "Tech2Packet",
    "UnsupportedEngineError",
    "assemble_profile_meta",
    "compute_ascent_end_offset_minutes",
    "compute_profile_datetime",
    "compute_trans_start_date",
    "datetime_to_juld",
    "decode_arvor_i_sbd",
    "juld_to_datetime",
    "read_arvor_i_eml",
    "resolve_engine",
    "unpack_packet",
]
