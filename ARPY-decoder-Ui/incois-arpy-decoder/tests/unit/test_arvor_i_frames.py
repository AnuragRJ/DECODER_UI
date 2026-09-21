"""Unit tests for the ARVOR-I raw decoding foundation (layout family 222/223/225/232).

Fixtures are the real read-only telemetry supplied for the investigation:
two floats — 6990711 (dead/end-of-mission, fw 5.47 → decoder id 222 family)
and 7902408 (active, fw 5.54 → decoder id 232) — plus the vendored Coriolis
MATLAB sources under ``tests/data/arvor_i/coriolis_src/`` used to verify the
bit-width tables mechanically.

Every expected value in these tests was derived independently during the
read-only investigation (raw bytes + MATLAB + NKE manual 33-16-033 Rev14 +
operator CTD reference files).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from argo_decoder.platforms.provor_ir_sbd.arvor_i import (
    CTD_WIDTHS,
    FIRMWARE_CHECKSUM_TO_DECODER_IDS,
    PARAM1_WIDTHS_222_FAMILY,
    PARAM1_WIDTHS_232,
    PUMP_EV_WIDTHS,
    TECH1_WIDTHS,
    TECH2_WIDTHS,
    ArvorIEngine,
    ArvorTech2Packet,
    SbdFramingError,
    UnsupportedEngineError,
    counts_to_pres,
    counts_to_psal,
    counts_to_temp,
    decode_arvor_i_sbd,
    decode_packet,
    find_identical_payloads,
    frame_sbd_payload,
    momsn_from_filename,
    read_arvor_i_eml,
    resolve_engine,
    twos_complement,
)

# conftest convention: repo root = argo-decoder-python, workspace = its parent
ARGO_PY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ARGO_PY_ROOT.parent
RAW_ROOT = WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819"
CORIOLIS_SRC = ARGO_PY_ROOT / "tests" / "data" / "arvor_i" / "coriolis_src"

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# ---------------------------------------------------------------------------
# Width tables vs the vendored MATLAB sources (bit-for-bit)
# ---------------------------------------------------------------------------


def _parse_tabnbbits(src: str) -> list[list[int]]:
    out: list[list[int]] = []
    idx = 0
    while True:
        m0 = re.search(r"tabNbBits\s*=\s*\[", src[idx:])
        if m0 is None:
            break
        lb = idx + m0.end() - 1
        depth = 0
        end = None
        for i in range(lb, len(src)):
            if src[i] == "[":
                depth += 1
            elif src[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        assert end is not None
        body = src[lb + 1 : end]
        body = re.sub(r"%[^\n]*", "", body).replace("...", " ")

        def _rep_scalar(m: re.Match) -> str:
            return " ".join([m.group(1)] * int(m.group(2)))

        def _rep_array(m: re.Match) -> str:
            return " ".join(m.group(1).split() * int(m.group(2)))

        body = re.sub(r"repmat\(\[([\d\s]+)\],\s*1,\s*(\d+)\)", _rep_array, body)
        body = re.sub(r"repmat\((\d+),\s*1,\s*(\d+)\)", _rep_scalar, body)
        out.append([int(t) for t in body.split() if t.isdigit()])
        idx = end + 1
    return out


@pytest.mark.parametrize(
    ("matlab_file", "param1_widths"),
    [
        ("decode_prv_data_ir_sbd_222_223_225.m", PARAM1_WIDTHS_222_FAMILY),
        ("decode_prv_data_ir_sbd_232.m", PARAM1_WIDTHS_232),
    ],
)
def test_width_tables_match_matlab_source(matlab_file: str, param1_widths: list[int]) -> None:
    """Python width tables are bit-for-bit identical to the MATLAB engines.

    Vector order in both .m files: [0]=Tech#1, [1]=Tech#2, [2]=CTD,
    [3]=CTDO (not implemented), [4]=Param#1, [5]=Param#2 (not implemented),
    [6]=hydraulic.
    """

    tables = _parse_tabnbbits((CORIOLIS_SRC / matlab_file).read_text())
    assert len(tables) == 7
    assert tables[0] == TECH1_WIDTHS
    assert tables[1] == TECH2_WIDTHS
    assert tables[2] == CTD_WIDTHS
    assert tables[4] == param1_widths
    assert tables[6] == PUMP_EV_WIDTHS
    # every table consumes exactly the 99 bytes after the type byte
    for t in (TECH1_WIDTHS, TECH2_WIDTHS, CTD_WIDTHS, param1_widths, PUMP_EV_WIDTHS):
        assert sum(t) == 792
    # the two engines' parameter tables differ only TEXTUALLY in the .m
    # sources (trailing run grouped "16 16 + 8x6" vs "16 16 8 + 8x5"); the
    # flat bit layout — and therefore the decoding — is identical.
    assert PARAM1_WIDTHS_222_FAMILY == PARAM1_WIDTHS_232
    assert sum(PARAM1_WIDTHS_222_FAMILY) == sum(PARAM1_WIDTHS_232) == 792


def test_firmware_checksum_table_matches_check_decoder_id() -> None:
    """Checksum→decoder-id table mirrors check_decoder_id.m exactly."""

    src = (CORIOLIS_SRC / "check_decoder_id.m").read_text()  # noqa: F841
    expected = {
        212: {38844, 47305},
        214: {47305},
        217: {47305},
        222: {11415},
        223: {11415},
        225: {11415},
        224: {43931},
        226: {43079},
        231: {43079},
        227: {64629},
        232: {13872},
    }
    for dec_id, checksums in expected.items():
        for cs in checksums:
            assert dec_id in FIRMWARE_CHECKSUM_TO_DECODER_IDS[cs]
    assert FIRMWARE_CHECKSUM_TO_DECODER_IDS[11415] == frozenset({222, 223, 225})
    assert FIRMWARE_CHECKSUM_TO_DECODER_IDS[13872] == frozenset({232})


# ---------------------------------------------------------------------------
# Engine identification
# ---------------------------------------------------------------------------


def test_resolve_engine_both_floats() -> None:
    engine, ids = resolve_engine(11415)  # 6990711: fw 5900A05 (5.47)
    assert engine is ArvorIEngine.FAMILY_222_223_225
    assert ids == frozenset({222, 223, 225})
    engine, ids = resolve_engine(13872)  # 7902408: fw 5900A05B (5.54)
    assert engine is ArvorIEngine.ENGINE_232
    assert ids == frozenset({232})


@pytest.mark.parametrize("checksum", [38844, 47305, 43931, 43079, 64629])
def test_resolve_engine_rejects_other_families(checksum: int) -> None:
    with pytest.raises(UnsupportedEngineError):
        resolve_engine(checksum)


def test_resolve_engine_unknown_checksum() -> None:
    with pytest.raises(UnsupportedEngineError):
        resolve_engine(99999)


# ---------------------------------------------------------------------------
# Framing (decode_sbd_file.m behaviour)
# ---------------------------------------------------------------------------


def test_framing_padding_rows() -> None:
    row = bytes([3]) + bytes(99)
    pad1a = bytes([0x1A]) * 100
    pad00 = bytes(100)
    packets, padding = frame_sbd_payload(row + pad1a + pad00)
    assert packets == [row]
    assert padding == [1, 2]


def test_framing_length_must_be_multiple_of_100() -> None:
    with pytest.raises(SbdFramingError):
        frame_sbd_payload(b"\x00" * 250)
    assert frame_sbd_payload(b"") == ([], [])


def test_framing_real_payload_three_rows() -> None:
    payload = (RAW_ROOT / "6990711" / "redacted_imei_170_000067.sbd").read_bytes()
    packets, padding = frame_sbd_payload(payload)
    assert len(packets) + len(padding) == 3
    assert all(len(r) == 100 for r in packets)


# ---------------------------------------------------------------------------
# Endianness / sign handling (MSB-first, big-endian, two's complement)
# ---------------------------------------------------------------------------


def test_twos_complement_and_scaling() -> None:
    # pressure: 0x2623 = 9763 -> (9763 + 10000)/10 = 1976.3 dbar
    assert counts_to_pres(0x2623) == pytest.approx(1976.3)
    # negative pressure engineering value: 55622 = 0xD926 -> 8.6 dbar
    assert counts_to_pres(55622) == pytest.approx(8.6)
    # temperature: 182 -> 0.182 degC ; 0xFB90 -> -1136 -> -1.136 degC
    assert counts_to_temp(182) == pytest.approx(0.182)
    assert counts_to_temp(0xFB90) == pytest.approx(-1.136)
    # salinity (unsigned): 34684 -> 34.684
    assert counts_to_psal(34684) == pytest.approx(34.684)
    assert twos_complement(0xFFFB, 16) == -5
    assert twos_complement(0x80, 8) == -128


def test_msb_first_bit_order() -> None:
    from argo_decoder.platforms.provor_ir_sbd.frames import BitReader

    r = BitReader(b"\x80\x00")
    assert r.read(1) == 1  # first bit of first byte
    r2 = BitReader(b"\x01")
    assert r2.read(8) == 1  # last bit of byte only


# ---------------------------------------------------------------------------
# .eml handling (transport metadata separate from float data)
# ---------------------------------------------------------------------------


def test_eml_header_only_with_sidecar_payload() -> None:
    eml = RAW_ROOT / "6990711" / "redacted_imei_170_000067.eml"
    msg = read_arvor_i_eml(eml)
    assert msg.session.momsn == 67
    assert msg.session.mtmsn == 0
    assert msg.session.session_time_utc == datetime(2025, 3, 4, 6, 6, 39, tzinfo=UTC)
    assert msg.session.gps_lat == pytest.approx(-64.53367)
    assert msg.session.gps_lon == pytest.approx(70.08814)
    assert msg.session.cep_radius_km == 3
    assert msg.session.message_size_bytes == 300
    # payload comes from the sidecar .sbd and equals it byte-for-byte
    assert msg.payload == eml.with_suffix(".sbd").read_bytes()
    assert len(msg.payload) == 300
    assert momsn_from_filename(eml.name) == 67


def test_eml_rejects_size_mismatch(tmp_path: Path) -> None:
    eml = RAW_ROOT / "6990711" / "redacted_imei_170_000067.eml"
    bad = tmp_path / "redacted_imei_170_000067.eml"
    bad.write_bytes(eml.read_bytes().replace(b"300", b"299", 1))
    (tmp_path / "redacted_imei_170_000067.sbd").write_bytes(eml.with_suffix(".sbd").read_bytes())
    with pytest.raises(ValueError, match="Message Size"):
        read_arvor_i_eml(bad)


# ---------------------------------------------------------------------------
# Tech#1 (type 0) — byte-for-byte against investigation values
# ---------------------------------------------------------------------------


def _packet(float_dir: str, momsn: int, pack_type: int):
    d = RAW_ROOT / float_dir
    p = next(d.glob(f"*_{momsn:06d}.sbd"))
    dec = decode_arvor_i_sbd(p.read_bytes())
    return next(pk for pk in dec.packets if pk.pack_type == pack_type)


def test_tech1_dead_float_first_transmission() -> None:
    pk = _packet("6990711", 67, 0)
    assert pk.cycle == 1
    assert pk.iridium_session == 0
    assert pk.firmware_checksum == 11415  # 0x2C97 -> fw 5900A05 -> decId 222
    assert pk.serial_number == 24022  # NKE serial from operator sheet
    assert pk.float_time == datetime(2025, 3, 4, 6, 6, 32, tzinfo=UTC)
    assert pk.gps_lat == pytest.approx(-64.5429, abs=1e-4)
    assert pk.gps_lon == pytest.approx(70.0833, abs=1e-4)
    assert pk.gps_valid == 1
    assert pk.eol_flag == 0
    assert pk.clock_offset_s == -5
    assert pk.pressure_offset_db is not None


def test_tech1_active_float_factory_session() -> None:
    pk = _packet("7902408", 32, 0)
    assert pk.cycle == 0
    assert pk.firmware_checksum == 13872  # 0x3630 -> fw 5900A05B -> decId 232
    assert pk.serial_number == 25016
    assert pk.float_time == datetime(2025, 9, 19, 9, 56, 42, tzinfo=UTC)
    assert pk.gps_lat == pytest.approx(17.5281, abs=1e-4)  # Hyderabad (INCOIS)
    assert pk.gps_lon == pytest.approx(78.4004, abs=1e-4)
    assert pk.clock_offset_s == -1


def test_tech1_stale_position_when_gps_invalid() -> None:
    """Cycles 5/6 of the dead float reused cycle 4's fix bit-for-bit."""

    c4 = _packet("6990711", 86, 0)
    c5 = _packet("6990711", 97, 0)
    c6 = _packet("6990711", 101, 0)
    assert c4.gps_valid == 1
    for later in (c5, c6):
        assert later.gps_valid == 0
        assert later.gps_lat == c4.gps_lat
        assert later.gps_lon == c4.gps_lon


# ---------------------------------------------------------------------------
# Tech#2 (type 4) — corrected expected-count mapping
# ---------------------------------------------------------------------------


def test_tech2_expected_counts_corrected_mapping() -> None:
    pk = _packet("6990711", 67, 4)
    assert isinstance(pk, ArvorTech2Packet)
    assert pk.cycle == 1
    # manual §6.3 + raw evidence: items 3/4/5 = descent/drift/ascent packets
    assert pk.n_descent_packets == 4
    assert pk.n_drift_packets == 1
    assert pk.n_ascent_packets == 7
    assert pk.n_near_surface_packets == 0
    assert pk.n_in_air_packets == 0
    # Coriolis-as-coded (items 4/5/6) kept for parity comparison
    assert pk.coriolis_exp_nb_desc_drift_asc == (1, 7, 0)
    assert pk.last_reset == datetime(2025, 3, 2, 5, 4, 58, tzinfo=UTC)
    assert pk.hydraulic_type == 0  # ARVOR hydraulics
    assert pk.ice_flag == 0


def test_tech2_expected_counts_match_received_packets() -> None:
    """The corrected mapping must be consistent with actually-received
    packets for every complete cycle of the dead float (cycles 1-7)."""

    d = RAW_ROOT / "6990711"
    received: dict[int, dict[int, int]] = {}
    expected: dict[int, tuple[int, int, int]] = {}
    for p in sorted(d.glob("*.sbd")):
        for pk in decode_arvor_i_sbd(p.read_bytes()).packets:
            if pk.pack_type in (1, 2, 3):
                received.setdefault(pk.cycle, {}).setdefault(pk.pack_type, 0)
                received[pk.cycle][pk.pack_type] += 1
            elif pk.pack_type == 4:
                expected[pk.cycle] = (
                    pk.n_descent_packets,
                    pk.n_drift_packets,
                    pk.n_ascent_packets,
                )
    for cycle in range(1, 8):
        exp = expected[cycle]
        rec = received.get(cycle, {})
        assert (rec.get(1, 0), rec.get(2, 0), rec.get(3, 0)) == exp, cycle


# ---------------------------------------------------------------------------
# CTD packets — raw counts, conversion, fill values, operator-file parity
# ---------------------------------------------------------------------------


def test_ctd_first_triplets_raw_counts_and_physical() -> None:
    # type 3 (ascent), cycle 1, dead float: counts (9763, 182, 34666)
    pk = _packet("6990711", 70, 3)
    assert pk.cycle == 1
    assert pk.triplets()[0] == (9763, 182, 34666)
    assert pk.pres()[0] == pytest.approx(1976.30)
    assert pk.temp()[0] == pytest.approx(0.182)
    assert pk.psal()[0] == pytest.approx(34.666)
    # operator reference file Ascctd001.txt line 1 == these values
    line1 = (RAW_ROOT / "6990711" / "ctd" / "Ascctd001.txt").read_text().splitlines()[0]
    p, t, s = (float(x) for x in line1.split())
    assert (p, t, s) == (pk.pres()[0], pytest.approx(pk.temp()[0], abs=1e-3), pk.psal()[0])

    # type 2 (drift): Subctd001 = (1042.20, 0.645, 34.684)
    pk2 = _packet("6990711", 70, 2)
    assert pk2.triplets()[0] == (422, 645, 34684)
    assert pk2.pres()[0] == pytest.approx(1042.20)
    assert pk2.temp()[0] == pytest.approx(0.645)
    assert pk2.psal()[0] == pytest.approx(34.684)

    # type 1 (descent): Desctd001 line 1 = (8.60, 0.766, 33.636); negative
    # temperature appears later in the same file (sign handling)
    pk1 = _packet("6990711", 68, 1)
    assert pk1.triplets()[0] == (55622, 766, 33636)
    assert pk1.pres()[0] == pytest.approx(8.60)
    assert pk1.temp()[0] == pytest.approx(0.766)
    assert pk1.psal()[0] == pytest.approx(33.636)
    des = (RAW_ROOT / "6990711" / "ctd" / "Desctd001.txt").read_text().splitlines()
    assert any(float(ln.split()[1]) < 0 for ln in des)  # -1.136 degC present


def test_ctd_first_measurement_time_fraction() -> None:
    pk = _packet("6990711", 70, 3)
    # H/24 + M/1440 + S/86400 (MATLAB formula)
    h = pk.fields[2]
    m = pk.fields[3]
    s = pk.fields[4]
    assert pk.first_meas_time_day_fraction == pytest.approx(h / 24 + m / 1440 + s / 86400)


def test_ctd_fill_sentinel() -> None:
    pk = _packet("6990711", 70, 3)
    trip = list(pk.triplets())
    idx = trip.index((0, 0, 0)) if (0, 0, 0) in trip else None
    if idx is not None:
        assert pk.valid_mask()[idx] is False
        assert pk.pres()[idx] is None
    else:  # construct synthetically
        from argo_decoder.platforms.provor_ir_sbd.arvor_i import ArvorCtdPacket

        synth = ArvorCtdPacket(pack_type=3, raw=pk.raw, fields=[0, 1, 0, 0, 0, 1, 2, 3] + [0] * 44)
        assert synth.valid_mask() == [True] + [False] * 14
        assert synth.pres()[0] == pytest.approx(1000.1)  # (1+10000)/10
        assert synth.is_empty is False
        # fully-empty packet is flagged, not silently dropped
        empty = ArvorCtdPacket(pack_type=3, raw=pk.raw, fields=[0, 1] + [0] * 50)
        assert empty.is_empty is True
        assert all(v is None for v in empty.pres())
    assert pk.is_empty is False


# ---------------------------------------------------------------------------
# Param#1 (type 5) and hydraulic (type 6)
# ---------------------------------------------------------------------------


def test_param1_both_engine_tables() -> None:
    pk = _packet("7902408", 32, 5)  # cycle-0 factory session, engine 232
    assert pk.cycle == 0
    assert pk.float_time == datetime(2025, 9, 19, 9, 56, 42, tzinfo=UTC)


def test_hydraulic_packet() -> None:
    pk = _packet("6990711", 67, 6)
    assert pk.cycle == 1
    assert pk.ref_day == 0 and pk.ref_min == 310
    acts = pk.actions()
    assert len(acts) == 13
    first = acts[0]
    assert (first.action_type, first.ref_time_min, first.pressure_db, first.duration_s) == (
        0,
        317,
        423,
        5,
    )
    assert first.is_pump is False  # action_type 0 = electro-valve
    assert sum(a.is_pump for a in acts) == 4


def test_unsupported_packet_type_preserved() -> None:
    row = bytes([7]) + bytes(99)  # type 7 never observed; layout not transcribed
    pk = decode_packet(row)
    assert type(pk).__name__ == "ArvorUnsupportedPacket"
    assert pk.pack_type == 7
    assert pk.raw == row


# ---------------------------------------------------------------------------
# Duplicates: flag only, never discard
# ---------------------------------------------------------------------------


def test_no_duplicate_payloads_in_real_data() -> None:
    for flt in ("6990711", "7902408"):
        msgs = [read_arvor_i_eml(p) for p in sorted((RAW_ROOT / flt).glob("*.eml"))]
        assert find_identical_payloads(msgs) == []


def test_identical_payloads_flagged_not_dropped(tmp_path: Path) -> None:
    src = RAW_ROOT / "6990711" / "redacted_imei_170_000067.eml"
    m1 = read_arvor_i_eml(src)
    m2 = read_arvor_i_eml(src)
    m2 = type(m2)(source_path=tmp_path / "dup.eml", session=m2.session, payload=m2.payload)
    groups = find_identical_payloads([m1, m2])
    assert len(groups) == 1 and len(groups[0]) == 2
    # both payloads still decode — nothing discarded
    assert len(decode_arvor_i_sbd(m1.payload).packets) >= 1
    assert len(decode_arvor_i_sbd(m2.payload).packets) >= 1
