"""Unit tests for Provor/Arvor Iridium SBD parsing (Phase 2 Slice 1).

These tests use real demo-data SBD e-mails from WMO 6902892
(IMEI 300234065895840). They exercise:

* Filename parsing
* E-mail MIME parsing (text body + optional binary attachment)
* MSB-first bit reader against known vectors
* Packet type dispatch
* Tech#1 packet decoding (cycle number + GPS fix from bit-packed fields)
* CTD packet bin extraction
* Plugin routing via the decoder table
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest

from argo_decoder.config import get_decoder_table
from argo_decoder.config.models import DecoderConfig
from argo_decoder.io.sbd_email import parse_filename, parse_sbd_email
from argo_decoder.metadata.models import FloatInfo
from argo_decoder.platforms import NullDecoder, ProvorIridiumSbdDecoder, get_decoder
from argo_decoder.platforms.provor_ir_sbd import (
    BitReader,
    BitReaderEofError,
    SbdPacketType,
    Tech1Packet,
    unpack_packet,
)

DEMO_DIR = (
    Path(__file__).resolve().parents[2]
    / ".."
    / "Coriolis-data-processing-chain-for-Argo-floats-container"
    / "decArgo_demo"
    / "input"
    / "archive"
    / "cycle"
    / "300234065895840"
)


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------


def test_parse_filename_well_formed() -> None:
    r = parse_filename("co_20200629T083108Z_300234065895840_000005_000000_21079.txt")
    assert r is not None
    imei, cycle, profile, size, ts = r
    assert imei == "300234065895840"
    assert cycle == 5
    assert profile == 0
    assert size == 21079
    assert ts.year == 2020 and ts.month == 6 and ts.day == 29


def test_parse_filename_bad() -> None:
    assert parse_filename("not_an_sbd_file.txt") is None


# ---------------------------------------------------------------------------
# E-mail parsing against real demo data
# ---------------------------------------------------------------------------


def _first_payload_file() -> Path:
    files = sorted(glob.glob(str(DEMO_DIR / "co_*_000005_*.txt")))
    assert files, "demo data not available"
    return Path(files[0])


def test_parse_sbd_email_zero_payload_ping() -> None:
    """Cycle 4 in the demo set is a 0-byte session ping."""
    files = sorted(glob.glob(str(DEMO_DIR / "co_*_000004_*.txt")))
    assert files
    msg = parse_sbd_email(files[0])
    assert msg.imei == "300234065895840"
    assert msg.cycle == 4
    assert msg.has_payload is False
    assert len(msg.payload) == 0
    assert msg.session.momsn == 4
    assert msg.session.message_size_bytes == 0
    # Session GPS fix should be present in the text body.
    assert msg.session.gps_lat is not None
    assert msg.session.gps_lon is not None
    assert 40.0 < msg.session.gps_lat < 60.0, f"lat={msg.session.gps_lat}"
    assert -10.0 < msg.session.gps_lon < 10.0, f"lon={msg.session.gps_lon}"


def test_parse_sbd_email_with_payload() -> None:
    fp = _first_payload_file()
    msg = parse_sbd_email(fp)
    assert msg.has_payload is True
    assert len(msg.payload) == 300  # NKE 300-byte payloads
    assert msg.cycle == 5
    # First byte of payload = packet type.
    assert 0 <= msg.payload[0] <= 14


# ---------------------------------------------------------------------------
# Bit reader — verify MSB-first unpacking
# ---------------------------------------------------------------------------


def test_bitreader_byte_aligned() -> None:
    # 0x1234 followed by 0xAB in 3 bytes
    r = BitReader(bytes.fromhex("1234ab"))
    assert r.read(4) == 0x1
    assert r.read(4) == 0x2
    assert r.read(8) == 0x34
    assert r.read(8) == 0xAB
    assert r.remaining == 0


def test_bitreader_crossing_bytes() -> None:
    # Pack 0b101_00110_1100 across 2 bytes: 1010 0110 1100 xxxx = 0xA6C0
    r = BitReader(bytes([0xA6, 0xC0]))
    assert r.read(3) == 0b101
    assert r.read(5) == 0b00110
    assert r.read(4) == 0b1100


def test_bitreader_eof() -> None:
    r = BitReader(b"\xff\xff")
    r.read(12)
    with pytest.raises(BitReaderEofError):
        r.read(8)  # only 4 bits remain


# ---------------------------------------------------------------------------
# Unpack a real payload and check Tech#1 fields
# ---------------------------------------------------------------------------


def _first_payload_bytes() -> bytes:
    return parse_sbd_email(_first_payload_file()).payload


def test_unpack_tech_packet_from_real_data() -> None:
    """Scan all demo payloads for a Tech#1 (type 0) and verify GPS/cycle."""
    found = 0
    for fp in sorted(glob.glob(str(DEMO_DIR / "co_*.txt")))[:200]:
        msg = parse_sbd_email(fp)
        if not msg.has_payload:
            continue
        if msg.payload[0] != 0:
            continue
        pkt = unpack_packet(msg.payload)
        assert isinstance(pkt, Tech1Packet)
        assert pkt.pack_type == SbdPacketType.TECHNICAL_1
        assert pkt.cycle_number is not None
        assert pkt.cycle_number >= 0
        # The GPS fix decoded from bit-packed fields should be a reasonable
        # lat/lon if the packet carried a fix (sign bits zero/one).
        if pkt.gps_lat is not None:
            assert -90.0 <= pkt.gps_lat <= 90.0
        if pkt.gps_lon is not None:
            assert -180.0 <= pkt.gps_lon <= 180.0
        found += 1
        if found >= 3:
            break
    assert found >= 1, "expected at least one Tech#1 packet in first 200 SBDs"


def test_unpack_nonzero_payloads_do_not_crash() -> None:
    """Walking the first 200 payloads must produce packets without raising."""
    unpacked = 0
    for fp in sorted(glob.glob(str(DEMO_DIR / "co_*.txt")))[:200]:
        msg = parse_sbd_email(fp)
        if not msg.has_payload:
            continue
        pkt = unpack_packet(msg.payload)
        assert pkt.pack_type in SbdPacketType
        unpacked += 1
    assert unpacked > 50


# ---------------------------------------------------------------------------
# Plugin dispatch via decoder table
# ---------------------------------------------------------------------------


def _make_info(
    platform_type: str,
    decoder_version: str,
    decoder_id: int,
    ptt: str = "589584",
) -> FloatInfo:
    from datetime import date, datetime

    return FloatInfo(
        wmo=6902892,
        ptt=ptt,
        float_type=platform_type,
        decoder_version=decoder_version,
        decoder_id=decoder_id,
        frame_length=31,
        cycle_length_hours=240,
        drift_sampling_period_hours=3.0,
        launch_date=datetime(2021, 3, 13),
        launch_lon=-47.0613,
        launch_lat=-47.0137,
        reference_day=date(2021, 3, 13),
    )


def test_provor_plugin_handles_arvor_d_5_67() -> None:
    cfg = DecoderConfig()
    info = _make_info("ARVOR_D", "5.67", 221)
    decoder = get_decoder(info, None, cfg)
    assert isinstance(decoder, ProvorIridiumSbdDecoder)


def test_provor_plugin_handles_arvor_5_45() -> None:
    cfg = DecoderConfig()
    info = _make_info("ARVOR", "5.45", 212, ptt="850878")
    decoder = get_decoder(info, None, cfg)
    assert isinstance(decoder, ProvorIridiumSbdDecoder)


def test_unknown_version_falls_back_to_null() -> None:
    cfg = DecoderConfig()
    info = _make_info("ARVOR", "9.99", 999)
    decoder = get_decoder(info, None, cfg)
    assert isinstance(decoder, NullDecoder)


def test_provor_plugin_can_handle_method() -> None:
    cfg = DecoderConfig()
    plugin = ProvorIridiumSbdDecoder(cfg)
    assert plugin.can_handle(_make_info("ARVOR_D", "5.67", 221), None) is True
    assert plugin.can_handle(_make_info("ARVOR", "5.45", 212, ptt="850878"), None) is True
    # Apex floats should NOT be handled by this plugin.
    assert plugin.can_handle(_make_info("APEX_APF11", "1.0", 900), None) is False


def test_decoder_table_populated_for_demo() -> None:
    table = get_decoder_table()
    assert 221 in table.all_decoder_ids()
    assert 212 in table.all_decoder_ids()
    e = table.by_decoder_id(221)
    assert e.transmission == "IRIDIUM_SBD"
    assert "CTD_PRES" in e.sensors
