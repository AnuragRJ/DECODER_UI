"""ARVOR-I registry/routing representation (metadata stage only).

Established by the 2026-09-04 baseline decode: the Tech#1 firmware
checksum (``resolve_engine``, mirroring ``check_decoder_id.m``) gives
13872 -> 232 for WMOs 7902408/1902844/2904082 and 11415 ->
{222, 223, 225} for WMO 6990711 (registered as 222). The sheet firmware
string "7.2.5" is the SBE41CP sensor firmware and spans both engines,
so it must never key a decoder.

The dedicated ARVOR-I plugin (ArvorISbdDecoder, an adapter around the
validated Phase 3-9 stack) routes these floats via the PROFILE_CLASS the
four CSVs derive from the sheet family signature; the NKE demo decoder
must never claim the ``arvor_i_sbe41cp`` profile class. These tests also
pin that registry.csv provides nothing for ARVOR-I floats: the sheets are
their only metadata/routing authority.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from argo_decoder.config import DecoderConfig
from argo_decoder.config.decoder_table import get_decoder_table
from argo_decoder.metadata.csv_loader import CsvLoader
from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader
from argo_decoder.platforms.base import NullDecoder, get_decoder
from argo_decoder.platforms.provor_ir_sbd.arvor_i_decoder import ArvorISbdDecoder
from argo_decoder.platforms.provor_ir_sbd.decoder import ProvorIridiumSbdDecoder

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "config" / "registry.csv"
METADATA_DIR = REPO_ROOT / "config" / "metadata"

#: Checksum-proven decoder ids (Tech#1 item 3, verified 2026-09-04).
ARVOR_I_DECODER_IDS = {1902844: 232, 2904082: 232, 6990711: 222, 7902408: 232}

pytestmark = pytest.mark.skipif(
    not (REGISTRY.exists() and (METADATA_DIR / "meta.csv").exists()),
    reason="registry.csv / four-CSV metadata not present",
)


@pytest.fixture(scope="module")
def registry() -> CsvLoader:
    return CsvLoader(REGISTRY, strict=False)


def test_registry_provides_nothing_for_arvor_i() -> None:
    """registry.csv carries no ARVOR-I rows: sheets-only architecture."""
    registry_wmos = {r.wmo for r in CsvLoader(REGISTRY, strict=False).iter_floats()}
    assert not (registry_wmos & set(ARVOR_I_DECODER_IDS))


def test_sheets_carry_the_arvor_i_family_signature() -> None:
    """The four CSVs derive the wire-protocol family for all four floats."""
    loader = MultiCsvLoader(METADATA_DIR)
    for wmo in ARVOR_I_DECODER_IDS:
        row = loader.get_float(wmo)
        assert row is not None, f"WMO {wmo} missing from the four CSVs"
        assert row.platform_type == "ARVOR"
        assert row.platform_maker == "NKE"
        assert row.frame_length == 100
        assert row.profile_class == "arvor_i_sbe41cp"
        # The numeric engine id is telemetry-derived, never sheet-derived.
        assert row.decoder_id == 0
        assert row.decoder_version == ""
        info = loader.load_info(wmo)
        assert info.profile_class == "arvor_i_sbe41cp"


def test_decoder_table_knows_the_arvor_i_family() -> None:
    table = get_decoder_table()
    for decoder_id in (222, 232):
        entry = table.by_decoder_id(decoder_id)
        assert entry.profile_class == "arvor_i_sbe41cp"
        assert entry.transmission == "IRIDIUM_SBD"
        assert entry.frame_length == 100  # decode_sbd_file.m 100-byte rows


def test_routing_selects_the_arvor_i_plugin() -> None:
    """Sheets-derived PROFILE_CLASS routes ARVOR-I to ArvorISbdDecoder.

    The expected flow: four CSVs -> FloatMeta/FloatInfo (family
    signature) -> generic routing -> ArvorISbdDecoder -> existing ARVOR-I
    stack. The NKE demo decoder declines the ``arvor_i_sbe41cp`` profile
    class; the numeric engine id (checksum-proven 222/232) is resolved
    from telemetry inside the stack, not from metadata.
    """
    config = DecoderConfig()
    loader = MultiCsvLoader(METADATA_DIR)
    for wmo in ARVOR_I_DECODER_IDS:
        info = loader.load_info(wmo)
        assert not ProvorIridiumSbdDecoder(config).can_handle(info, None)
        selected = get_decoder(info, None, config)
        assert isinstance(selected, ArvorISbdDecoder)

    # A family signature absent from the decoder table must not be
    # claimed; an unknown class falls through to NullDecoder.
    unknown_info = loader.load_info(1902844).model_copy(
        update={"profile_class": "some_future_protocol"}
    )
    assert not ArvorISbdDecoder(config).can_handle(unknown_info, None)
    assert isinstance(get_decoder(unknown_info, None, config), NullDecoder)


def test_nke_demo_route_unchanged(registry: CsvLoader) -> None:
    """The NKE demo float (6902892, decoder 221) still selects its decoder."""
    config = DecoderConfig()
    info = registry.load_info(6902892)
    assert info.decoder_id == 221
    assert ProvorIridiumSbdDecoder(config).can_handle(info, None)
    assert isinstance(get_decoder(info, None, config), ProvorIridiumSbdDecoder)


def test_no_wmo_specific_selection_conditions() -> None:
    """No fleet WMO literal may appear in decoder-selection source code.

    Selection keys on float-intrinsic evidence (registry decoder ids,
    firmware maps, checksums), so a WMO literal in the selection code
    would indicate a per-float hack rather than a generic rule.
    """
    sources = [
        REPO_ROOT / "src" / "argo_decoder" / "metadata" / "multi_csv_loader.py",
        REPO_ROOT / "src" / "argo_decoder" / "metadata" / "csv_loader.py",
        REPO_ROOT / "src" / "argo_decoder" / "metadata" / "builder.py",
        REPO_ROOT / "src" / "argo_decoder" / "platforms" / "base.py",
        REPO_ROOT / "src" / "argo_decoder" / "platforms" / "provor_ir_sbd" / "decoder.py",
        REPO_ROOT / "src" / "argo_decoder" / "platforms" / "provor_ir_sbd" / "arvor_i_decoder.py",
        REPO_ROOT / "src" / "argo_decoder" / "config" / "decoder_table.py",
        REPO_ROOT / "src" / "argo_decoder" / "io" / "rsync.py",
        REPO_ROOT / "src" / "argo_decoder" / "pipeline" / "metadata_stage.py",
    ]
    for path in sources:
        text = path.read_text()
        for wmo in ARVOR_I_DECODER_IDS:
            assert str(wmo) not in text, f"{path.name} references WMO {wmo}"
