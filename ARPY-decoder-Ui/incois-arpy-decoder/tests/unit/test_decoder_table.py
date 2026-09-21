"""Unit tests for config/decoder_table.py and metadata/validators cross-checks."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from argo_decoder.config import (
    DecoderTable,
    DecoderTableEntry,
    get_decoder_table,
    load_decoder_table,
)
from argo_decoder.config.decoder_table import _DEFAULT_TABLE_PATH
from argo_decoder.metadata.models import FloatRegistryRow, SensorEntry
from argo_decoder.metadata.validators import validate_registry

# ---------------------------------------------------------------------------
# Bundled-table loading
# ---------------------------------------------------------------------------


def test_default_table_loads() -> None:
    table = load_decoder_table()
    assert isinstance(table, DecoderTable)
    # At minimum the two Phase-1 demo entries must be present.
    ids = table.all_decoder_ids()
    assert 212 in ids
    assert 221 in ids


def test_default_table_path_matches_package_resource() -> None:
    assert _DEFAULT_TABLE_PATH.exists()
    assert _DEFAULT_TABLE_PATH.name == "decoder_table.yaml"


def test_cached_table_same_object() -> None:
    a = get_decoder_table()
    b = get_decoder_table()
    assert a is b  # lru_cache returns identical instance


def test_lookup_by_platform_version() -> None:
    table = get_decoder_table()
    entry = table.by_platform_version("ARVOR_D", "5.67")
    assert entry.decoder_id == 221
    assert entry.platform_family == "FLOAT_DEEP"
    assert entry.transmission == "IRIDIUM_SBD"
    assert entry.frame_length == 31
    assert "CTD_PRES" in entry.sensors
    assert "OPTODE_DOXY" in entry.sensors


def test_lookup_by_decoder_id() -> None:
    table = get_decoder_table()
    entry = table.by_decoder_id(212)
    assert entry.platform_type == "ARVOR"
    assert entry.decoder_version == "5.45"
    assert entry.sensors == ["CTD_PRES", "CTD_TEMP", "CTD_CNDC"]


def test_lookup_missing_raises() -> None:
    table = get_decoder_table()
    with pytest.raises(KeyError):
        table.by_platform_version("ARVOR", "9.99")
    with pytest.raises(KeyError):
        table.by_decoder_id(99999)


# ---------------------------------------------------------------------------
# Schema validation (Pydantic enforces field constraints)
# ---------------------------------------------------------------------------


def test_invalid_platform_family_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "decoders:\n"
        "  - platform_type: ARVOR\n"
        '    decoder_version: "1.0"\n'
        "    decoder_id: 1\n"
        "    platform_family: NOT_A_FAMILY\n"
        "    transmission: IRIDIUM_SBD\n"
        "    frame_length: 31\n"
        "    sensors: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_decoder_table(bad)


def test_invalid_transmission_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "decoders:\n"
        "  - platform_type: ARVOR\n"
        '    decoder_version: "1.0"\n'
        "    decoder_id: 1\n"
        "    platform_family: FLOAT\n"
        "    transmission: SMOKE_SIGNAL\n"
        "    frame_length: 31\n"
        "    sensors: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_decoder_table(bad)


def test_extra_keys_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "decoders:\n"
        "  - platform_type: ARVOR\n"
        '    decoder_version: "1.0"\n'
        "    decoder_id: 1\n"
        "    platform_family: FLOAT\n"
        "    transmission: IRIDIUM_SBD\n"
        "    frame_length: 31\n"
        "    sensors: []\n"
        "    not_a_real_field: oops\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_decoder_table(bad)


def test_entry_is_frozen() -> None:
    entry = DecoderTableEntry(
        platform_type="ARVOR",
        decoder_version="1.0",
        decoder_id=1,
        platform_family="FLOAT",
        transmission="IRIDIUM_SBD",
        frame_length=31,
        sensors=[],
    )
    with pytest.raises((TypeError, ValidationError)):
        entry.decoder_id = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Cross-validation: registry rows <-> decoder table
# ---------------------------------------------------------------------------


def _row(
    *,
    wmo: int = 6902892,
    ptt: str = "000000",
    platform_type: str = "ARVOR_D",
    platform_family: str = "FLOAT_DEEP",
    decoder_id: int = 221,
    decoder_version: str = "5.67",
) -> FloatRegistryRow:
    return FloatRegistryRow(
        wmo=wmo,
        ptt=ptt,
        platform_type=platform_type,
        platform_family=platform_family,
        transmission_type=3,
        decoder_id=decoder_id,
        decoder_version=decoder_version,
        frame_length=31,
        cycle_length_hours=24,
        drift_sampling_period_hours=3.0,
        launch_date_utc=datetime(2021, 1, 1, tzinfo=UTC),
        reference_day=date(2021, 1, 1),
        sensors=[SensorEntry(sensor="CTD_PRES")],
    )


def test_registry_valid_against_table() -> None:
    table = get_decoder_table()
    rows = [
        _row(),
        _row(
            wmo=6903014,
            ptt="000001",
            platform_type="ARVOR",
            platform_family="FLOAT",
            decoder_id=212,
            decoder_version="5.45",
        ),
    ]
    report = validate_registry(rows, decoder_table=table)
    assert report.ok, report.issues
    assert report.n_errors == 0


def test_registry_unknown_decoder_id_flagged() -> None:
    """When decoder_id is totally absent from the table AND the key is unknown
    we get both DECODER_VERSION_UNKNOWN and DECODER_ID_UNKNOWN."""
    table = get_decoder_table()
    rows = [_row(platform_type="NOPE", decoder_version="0.0", decoder_id=99999)]
    report = validate_registry(rows, decoder_table=table)
    codes = {i.code for i in report.issues if i.level == "error"}
    assert "DECODER_ID_UNKNOWN" in codes
    assert "DECODER_VERSION_UNKNOWN" in codes
    assert "DECODER_ID_MISMATCH" not in codes


def test_registry_unknown_version_flagged() -> None:
    table = get_decoder_table()
    rows = [_row(decoder_version="9.99", decoder_id=221)]
    report = validate_registry(rows, decoder_table=table)
    codes = {i.code for i in report.issues if i.level == "error"}
    # 221 IS a known id (for ARVOR_D/5.67), but version is wrong -> version unknown,
    # but decoder_id itself IS known, so no DECODER_ID_UNKNOWN.
    assert "DECODER_VERSION_UNKNOWN" in codes
    assert "DECODER_ID_UNKNOWN" not in codes
    assert "DECODER_ID_MISMATCH" not in codes


def test_registry_id_version_mismatch_flagged() -> None:
    """decoder_version matches a row but decoder_id disagrees -> MISMATCH."""
    table = get_decoder_table()
    # ARVOR_D / 5.67 expects decoder_id=221; supply 212 instead.
    rows = [_row(decoder_id=212)]
    report = validate_registry(rows, decoder_table=table)
    codes = {i.code for i in report.issues if i.level == "error"}
    assert "DECODER_ID_MISMATCH" in codes
    assert "DECODER_ID_UNKNOWN" not in codes
    assert "DECODER_VERSION_UNKNOWN" not in codes


def test_registry_crosscheck_skipped_when_no_table() -> None:
    rows = [_row(decoder_id=99999, decoder_version="bogon")]
    report = validate_registry(rows, decoder_table=None)
    codes = {i.code for i in report.issues}
    assert "DECODER_ID_UNKNOWN" not in codes
    assert "DECODER_VERSION_UNKNOWN" not in codes
    assert "DECODER_ID_MISMATCH" not in codes
