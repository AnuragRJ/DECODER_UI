"""Integration tests: ARVOR-I ``_tech.nc`` product over both raw datasets.

Phase 4A validation, pinned to the expectations fixed in
``docs/phase_reports/ARVOR_I_PHASE4A_TECH_MAPPING_2026-08-26.md`` §7.1:

* 6990711 — 7 deep cycles, all Tech#1/Tech#2 present, EOL flag never set
  (param 135 absent everywhere), GPS valid on cycles 1-4 and 7 (param 136
  present there, absent on 5/6), no grounding/emergency events, sub-surface
  triplet always non-zero (212 always present) -> 5 cycles x 67 + 2 x 66 =
  467 ``_tech.nc`` rows.
* 7902408 — cycles 1-12 all carry Tech#1/Tech#2 (incomplete cycles emit
  tech rows too), item61 = 1 everywhere; cycle 13 has neither tech message
  (no rows; its packet-count/misc rows are TECH_AUX and never reach the
  file); cycle -1 is parameter-only (no rows) -> 12 x 67 = 804 rows.
* no type-7 packet exists in either dataset (PROVEN on the raw stream), so
  the ICE paths (params 1010/1012 flag/243, check_ice_algorithm_arvor) are
  inert; values are cross-checked against the packet ``fields`` directly.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import netCDF4
import numpy as np
import pytest

from argo_decoder.nc.technical_arvor import write_arvor_tech_nc
from argo_decoder.platforms.provor_ir_sbd.arvor_i import (
    counts_to_pres,
    read_arvor_i_eml,
    twos_complement,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import reconstruct_science
from argo_decoder.platforms.provor_ir_sbd.arvor_i_tech import (
    build_arvor_tech_dataset,
    format_hhmm_dec_argo,
    format_mmss_dec_argo,
)

ARGO_PY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ARGO_PY_ROOT.parent
RAW_ROOT = WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819"

LAUNCH_6990711 = datetime(2025, 3, 2, 5, 16, tzinfo=UTC)
LAUNCH_7902408 = datetime(2026, 3, 25, 17, 44, tzinfo=UTC)


@pytest.fixture(scope="module")
def science_6990711() -> object:
    msgs = [read_arvor_i_eml(p) for p in sorted((RAW_ROOT / "6990711").glob("*.eml"))]
    return reconstruct_science(msgs, LAUNCH_6990711)


@pytest.fixture(scope="module")
def science_7902408() -> object:
    msgs = [read_arvor_i_eml(p) for p in sorted((RAW_ROOT / "7902408").glob("*.eml"))]
    return reconstruct_science(msgs, LAUNCH_7902408)


@pytest.fixture(scope="module")
def tech_6990711(science_6990711: object) -> object:
    return build_arvor_tech_dataset(science_6990711, wmo=6990711)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def tech_7902408(science_7902408: object) -> object:
    return build_arvor_tech_dataset(science_7902408, wmo=7902408)  # type: ignore[arg-type]


def rows_of(dataset: object) -> list:
    return dataset.tech_rows  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Row counts and cycle alignment (mapping doc §7.1)
# ---------------------------------------------------------------------------


def test_6990711_row_count_is_467(tech_6990711: object) -> None:
    assert len(rows_of(tech_6990711)) == 467


def test_7902408_row_count_is_804(tech_7902408: object) -> None:
    assert len(rows_of(tech_7902408)) == 804


def test_6990711_per_cycle_counts(tech_6990711: object) -> None:
    rows = rows_of(tech_6990711)
    per = Counter(r.cycle_number for r in rows)
    assert dict(per) == {c: (67 if c in (1, 2, 3, 4, 7) else 66) for c in range(1, 8)}


def test_7902408_per_cycle_counts_and_c13_absent(tech_7902408: object) -> None:
    rows = rows_of(tech_7902408)
    per = Counter(r.cycle_number for r in rows)
    assert dict(per) == {c: 67 for c in range(1, 13)}
    assert 13 not in per  # no Tech#1/Tech#2 -> nothing fabricated


def test_cycle_ordering_is_ascending_then_alphabetical(tech_6990711: object) -> None:
    rows = rows_of(tech_6990711)
    cycles = [r.cycle_number for r in rows]
    assert cycles == sorted(cycles)
    for start, end in ((0, 67), (67, 134)):
        names = [r.name for r in rows[start:end]]
        assert names == sorted(names)


def test_cycle_minus_one_and_pending_emit_nothing(tech_7902408: object) -> None:
    cycles = {r.cycle_number for r in rows_of(tech_7902408)}
    assert -1 not in cycles and 14 not in cycles and 15 not in cycles


# ---------------------------------------------------------------------------
# Parameter presence / absence (no fabricated rows)
# ---------------------------------------------------------------------------


def test_6990711_param_id_set(tech_6990711: object) -> None:
    ids = {r.param_id for r in rows_of(tech_6990711)}
    assert ids == (
        set(range(100, 106))
        | set(range(106, 135))
        | {136}
        | set(range(200, 214))
        | {213, 222}
        | set(range(227, 243))
    )


def test_7902408_param_id_set(tech_7902408: object) -> None:
    ids = {r.param_id for r in rows_of(tech_7902408)}
    assert ids == (
        set(range(100, 106))
        | set(range(106, 135))
        | {136}
        | set(range(200, 214))
        | {213, 222}
        | set(range(227, 243))
    )


def test_never_emitted_params_absent(tech_6990711: object, tech_7902408: object) -> None:
    for ds in (tech_6990711, tech_7902408):
        ids = {r.param_id for r in rows_of(ds)}
        # 135: EOL flag (item 66 == 0 on every Tech#1 of both floats)
        # 214-221: grounding rows (item 21 == 0 everywhere)
        # 223-226: emergency-ascent rows (item 32 == 0 everywhere)
        # 243: no type-7 packet ever received (PROVEN on the raw stream)
        # 1000/1012-1015/1001-1010: TECH_AUX-prefixed -> aux file only
        assert 135 not in ids
        assert not (set(range(214, 222)) & ids)
        assert not (set(range(223, 227)) & ids)
        assert 243 not in ids
        assert not ({1000, *range(1001, 1016)} & ids)


def test_param_136_follows_gps_valid_flag(tech_6990711: object, tech_7902408: object) -> None:
    got = {r.cycle_number for r in rows_of(tech_6990711) if r.param_id == 136}
    assert got == {1, 2, 3, 4, 7}  # cycles 5/6 re-sent a stale fix (item61=0)
    got = {r.cycle_number for r in rows_of(tech_7902408) if r.param_id == 136}
    assert got == set(range(1, 13))


def test_no_tech_aux_names_in_tech_rows(tech_6990711: object, tech_7902408: object) -> None:
    for ds in (tech_6990711, tech_7902408):
        assert all(not r.name.startswith(("TECH_AUX", "META_")) for r in rows_of(ds))


def test_aux_rows_are_bookkept_not_discarded(tech_6990711: object, tech_7902408: object) -> None:
    # 6990711: 7 cycles x (1001-1004, 1000, 1005-1009, 1012-1015) + one
    # zero-filled 1010 = 99; 7902408 (production default since 2026-08-27,
    # trailing buffers 14/15 emitted): same 14 per cycle x 12 + cycle 13's
    # counts/misc rows (12, its ParameterMessage2 row re-attributed to
    # cycle 15) + cycle 14's 13 rows + cycle 15's 14 rows + zero-filled
    # 1010 = 208.
    assert len(tech_6990711.aux_rows) == 99  # type: ignore[attr-defined]
    assert len(tech_7902408.aux_rows) == 208  # type: ignore[attr-defined]
    aux_cycles = {r.cycle_number for r in tech_7902408.aux_rows}  # type: ignore[attr-defined]
    assert 13 in aux_cycles  # c13 emits aux rows only
    assert 14 in aux_cycles and 15 in aux_cycles  # trailing-buffer cycles


# ---------------------------------------------------------------------------
# Values re-derived independently from the packet fields
# ---------------------------------------------------------------------------


def test_6990711_cycle1_values_match_fields(tech_6990711: object, science_6990711: object) -> None:
    rows = {r.param_id: r.value for r in rows_of(tech_6990711) if r.cycle_number == 1}
    cyc = next(c for c in science_6990711.cycles if c.cycle_number == 1)  # type: ignore[attr-defined]
    t1, t2 = cyc.tech1.fields, cyc.tech2.fields

    assert rows[100] == f"{t1[7] + 2000:04d}{t1[6]:02d}{t1[5]:02d}"
    assert rows[101] == str(t1[8])
    assert rows[102] == format_hhmm_dec_argo(t1[9])
    assert rows[111] == f"{t1[20]:02d}"
    assert rows[127] == f"{twos_complement(t1[47], 8) / 10:g}"
    assert rows[128] == str(t1[48] * 5)
    assert rows[129] == f"{15 - t1[49] / 10:g}"
    assert rows[130] == "0" if t1[50] else "1"
    assert rows[132] == str(t1[62])
    assert rows[136] == format_mmss_dec_argo(twos_complement(t1[73], 16))
    assert rows[200] == str(t2[3])  # descent packets: item 3, NOT item 2
    assert rows[204] == str(t2[7])  # in-air packets: item 7
    assert rows[212] == f"{counts_to_pres(t2[15]):g}"
    assert rows[236] == (
        f"{t2[51] + 2000:04d}{t2[50]:02d}{t2[49]:02d}{t2[46]:02d}{t2[47]:02d}{t2[48]:02d}"
    )
    assert rows[242] == str(t2[57])


def test_7902408_cycle12_values_match_fields(tech_7902408: object, science_7902408: object) -> None:
    rows = {r.param_id: r.value for r in rows_of(tech_7902408) if r.cycle_number == 12}
    cyc = next(c for c in science_7902408.cycles if c.cycle_number == 12)  # type: ignore[attr-defined]
    t1, t2 = cyc.tech1.fields, cyc.tech2.fields
    assert rows[100] == f"{t1[7] + 2000:04d}{t1[6]:02d}{t1[5]:02d}"
    assert rows[211] == str(t2[14])
    assert rows[235] == str(t2[45] * 5)
    assert rows[136] == format_mmss_dec_argo(twos_complement(t1[73], 16))


def test_cycle_numbers_use_buffer_cycles(tech_6990711: object, tech_7902408: object) -> None:
    assert {r.cycle_number for r in rows_of(tech_6990711)} == set(range(1, 8))
    assert {r.cycle_number for r in rows_of(tech_7902408)} == set(range(1, 13))


# ---------------------------------------------------------------------------
# NetCDF writer round-trip
# ---------------------------------------------------------------------------


VAR_ORDER = [
    "PLATFORM_NUMBER",
    "DATA_TYPE",
    "FORMAT_VERSION",
    "HANDBOOK_VERSION",
    "DATA_CENTRE",
    "DATE_CREATION",
    "DATE_UPDATE",
    "TECHNICAL_PARAMETER_NAME",
    "TECHNICAL_PARAMETER_VALUE",
    "CYCLE_NUMBER",
]


def read_rows(path: Path) -> tuple[netCDF4.Dataset, list[str], list[str], np.ndarray]:
    nc = netCDF4.Dataset(path)
    nc.set_auto_mask(False)
    names = [bytes(row).decode("ascii").rstrip() for row in nc["TECHNICAL_PARAMETER_NAME"][:]]
    values = [bytes(row).decode("ascii").rstrip() for row in nc["TECHNICAL_PARAMETER_VALUE"][:]]
    cycles = np.asarray(nc["CYCLE_NUMBER"][:])
    return nc, names, values, cycles


@pytest.mark.parametrize(
    ("fixture_name", "wmo", "n_rows"),
    [("tech_6990711", 6990711, 154), ("tech_7902408", 7902408, 264)],
)
def test_written_file_layout(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    fixture_name: str,
    wmo: int,
    n_rows: int,
) -> None:
    dataset = request.getfixturevalue(fixture_name)
    path = tmp_path / f"{wmo}_tech.nc"
    write_arvor_tech_nc(
        dataset,
        path,
        date_creation="20260827000000",
        date_update="20260827120000",
    )

    nc = netCDF4.Dataset(path)
    assert nc.data_model == "NETCDF3_CLASSIC"
    assert list(nc.dimensions) == [
        "DATE_TIME",
        "STRING128",
        "STRING32",
        "STRING8",
        "STRING4",
        "STRING2",
        "N_TECH_PARAM",
    ]
    assert len(nc.dimensions["DATE_TIME"]) == 14
    assert nc.dimensions["N_TECH_PARAM"].isunlimited()
    assert list(nc.variables) == VAR_ORDER

    nc.set_auto_mask(False)
    assert bytes(nc["PLATFORM_NUMBER"][:]).decode().rstrip() == str(wmo)
    assert bytes(nc["DATA_TYPE"][:]).decode().rstrip() == "Argo technical data"
    assert bytes(nc["FORMAT_VERSION"][:]).decode().rstrip() == "3.1"
    assert bytes(nc["HANDBOOK_VERSION"][:]) == b"1.2 "  # left-aligned (MATLAB)
    assert bytes(nc["DATA_CENTRE"][:]) == b"  "  # single-space fallback
    assert bytes(nc["DATE_CREATION"][:]) == b"20260827000000"
    assert bytes(nc["DATE_UPDATE"][:]) == b"20260827120000"
    assert nc["CYCLE_NUMBER"].dtype == np.int32

    attrs = {k: nc.getncattr(k) for k in nc.ncattrs()}
    assert attrs["title"] == "Argo float technical data file"
    assert attrs["institution"] == "CORIOLIS"
    assert attrs["source"] == "Argo float"
    assert attrs["history"] == (
        "2026-08-27T00:00:00Z creation; "
        "2026-08-27T12:00:00Z last update (coriolis float real time data processing)"
    )
    assert attrs["references"] == "http://www.argodatamgt.org/Documentation"
    assert attrs["user_manual_version"] == "3.1"
    assert attrs["Conventions"] == "Argo-3.1 CF-1.6"
    assert attrs["decoder_version"] == "CODA_076a"
    assert attrs["id"] == "https://doi.org/10.17882/42182"

    # variable attributes as in create_nc_tech_file_3_1.m
    assert nc["PLATFORM_NUMBER"].long_name == "Float unique identifier"
    assert nc["PLATFORM_NUMBER"].conventions == "WMO float identifier : A9IIIII"
    assert nc["CYCLE_NUMBER"].long_name == "Float cycle number"
    assert nc["CYCLE_NUMBER"].conventions == (
        "0...N, 0 : launch cycle (if exists), 1 : first complete cycle"
    )
    assert nc["CYCLE_NUMBER"]._FillValue == np.int32(99999)
    assert nc["TECHNICAL_PARAMETER_NAME"]._FillValue == b" "
    assert nc["TECHNICAL_PARAMETER_NAME"].dimensions == ("N_TECH_PARAM", "STRING128")
    nc.close()

    nc, names, values, cycles = read_rows(path)
    assert len(names) == n_rows  # published GDAC slots: 22 x n_cycles
    # The file carries the GDAC publication projection of the internal
    # rows (Prompt 13); the internal canonical rows remain on the model.
    from argo_decoder.nc.technical_arvor import arvor_tech_publication_rows

    published = arvor_tech_publication_rows(rows_of(dataset), dataset.float_times)
    assert names == [r.name for r in published]
    assert values == [r.value for r in published]
    assert cycles.tolist() == [r.cycle_number for r in published]
    # space padding (never NUL), like the GDAC references
    raw_row = bytes(nc["TECHNICAL_PARAMETER_NAME"][0])
    assert raw_row.rstrip() == raw_row[: len(raw_row.rstrip())] and set(
        raw_row[len(raw_row.rstrip()) :]
    ) <= {0x20}
    nc.close()


def test_written_file_excludes_aux_rows(tech_7902408: object, tmp_path: Path) -> None:
    path = write_arvor_tech_nc(tech_7902408, tmp_path / "7902408_tech.nc")
    nc, names, _, _ = read_rows(path)
    assert len(names) == 264  # 12 cycles x 22 GDAC publication slots
    assert not any(n.startswith("TECH_AUX") for n in names)
    assert not any(n.startswith("META_") for n in names)
    nc.close()


def test_published_file_is_the_gdac_slot_projection(tech_6990711: object) -> None:
    """Published _tech.nc carries exactly the GDAC shape, family-generically.

    21 unique names in the fixed 22-slot order (blank duplicate vacuum
    slot included), no internal-only names, and the FloatTime rows derived
    from the decoded float clock (items 41-46) rather than copied.
    """
    from argo_decoder.nc.technical_arvor import _GDAC_TECH_SLOTS

    slots = [n for n, _, _ in _GDAC_TECH_SLOTS]
    assert len(slots) == 22 and len(set(slots)) == 21
    path = write_arvor_tech_nc(tech_6990711, Path(tempfile.mkdtemp()) / "t.nc")
    nc, names, values, cycles = read_rows(path)
    n_cyc = len(set(cycles.tolist()))
    assert len(names) == 22 * n_cyc
    for i in range(n_cyc):
        block = names[i * 22 : (i + 1) * 22]
        assert block == slots
    # canonical Coriolis names must not leak into the published file
    assert all(n in set(slots) for n in names)
    # FloatTime rows carry the decoded clock, e.g. cycle 1 of this float
    ft = [v for v, n in zip(values, names, strict=True) if n == "CLOCK_FloatTime_hours"]
    assert ft and all(v.isdigit() for v in ft)
    nc.close()


def test_data_centre_override_maps_institution(tech_6990711: object, tmp_path: Path) -> None:
    from argo_decoder.nc.technical_arvor import (
        build_arvor_tech_nc_dataset_from_product,
        write_arvor_tech_file,
    )

    ds = build_arvor_tech_nc_dataset_from_product(tech_6990711, data_centre="IF")
    path = tmp_path / "6990711_tech.nc"
    write_arvor_tech_file(ds, path)
    nc = netCDF4.Dataset(path)
    nc.set_auto_mask(False)
    assert bytes(nc["DATA_CENTRE"][:]) == b"IF"
    assert nc.institution == "IFREMER"  # Argo reference table 4
    nc.close()
