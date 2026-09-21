"""Four-CSV metadata backend.

The backend joins ``meta.csv``, ``sensor-info.csv``, ``calib.csv`` and
``config_params.csv`` on WMO and projects them onto the existing
``FloatRegistryRow``, so the decoder keeps consuming the unchanged
``info.json`` / ``meta.json`` contract.

Every expected value below is taken from the official INCOIS GDAC
``<wmo>_meta.nc`` references, not from the spreadsheets, so these tests
pin *published* behaviour rather than restating the input.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from argo_decoder.metadata import builder
from argo_decoder.metadata.csv_loader import CsvLoader
from argo_decoder.metadata.multi_csv_loader import (
    FIRMWARE_TO_DECODER,
    INCOIS_DEFAULT_ACCURACY,
    INCOIS_DEFAULTS,
    SBE41_CALIB_EQUATIONS,
    MultiCsvLoader,
    _sensors_from_rows,
    build_accuracy,
    build_calibrations,
    build_config_parameters,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
METADATA_DIR = REPO_ROOT / "config" / "metadata"

pytestmark = pytest.mark.skipif(
    not (METADATA_DIR / "meta.csv").exists(), reason="four-CSV metadata not present"
)


@pytest.fixture(scope="module")
def loader() -> MultiCsvLoader:
    return MultiCsvLoader(METADATA_DIR)


def test_all_sheet_floats_are_joined(loader: MultiCsvLoader) -> None:
    """All fifteen INCOIS fleet floats are present in the four-CSV backend.

    Expanded from five on 2026-08-13 when the operator supplied sheets
    covering the whole APF9 fleet, and to fifteen on 2026-09-04 with the
    four ARVOR-I SBE41CP hulls (1902844, 2904082, 6990711, 7902408).
    Every WMO must join across all four CSVs; a float present in only
    some of them must not appear.
    """
    wmos = sorted(row.wmo for row in loader.iter_floats())
    assert wmos == [
        1902844,
        2901304,
        2901305,
        2901328,
        2901339,
        2901350,
        2902201,
        2902203,
        2902206,
        2902222,
        2902223,
        2902224,
        2904082,
        6990711,
        7902408,
    ]


def test_decoder_id_comes_from_firmware_not_float_subtype(loader: MultiCsvLoader) -> None:
    """``Float subtype`` is the Argo DAC_FORMAT_ID, never the decoder id.

    meta.csv records subtype 1021 for 2902222 and 1010 for 2901304, but
    the floats decode with 1010 and 1005 respectively. Selecting on the
    spreadsheet column would route both to the wrong decoder.
    """
    apf9g = loader.get_float(2902222)
    apf9a = loader.get_float(2901304)
    assert apf9g is not None and apf9a is not None
    # ``decoder_version`` is the format revision that selects the decoder.
    assert (apf9g.decoder_version, apf9g.decoder_id) == ("091615", 1010)
    assert (apf9a.decoder_version, apf9a.decoder_id) == ("061810", 1005)
    # ``firmware_version`` is the *published* label and differs on the
    # 1005 float: GDAC reports 020811 there. Routing on it would select
    # decoder 1010, which decodes that hull's pressure as -3079 dbar.
    assert apf9g.firmware_version == "091615"
    assert apf9a.firmware_version == "020811"
    assert apf9a.firmware_version != apf9a.decoder_version
    # The subtype is preserved, but only as DAC_FORMAT_ID.
    assert apf9g.dac_format_id == "1021"
    assert apf9g.dac_format_id != str(apf9g.decoder_id)


def test_decoder_routing_comes_from_sheets_not_registry(loader: MultiCsvLoader) -> None:
    """Decoder routing is sheets-only: family signature -> PROFILE_CLASS.

    ARVOR-I SBE41CP hulls must never resolve through
    ``FIRMWARE_TO_DECODER``: their sensor-info "firmware revision number"
    is the SBE41CP *sensor* firmware ("7.2.5"), which spans engines
    5900A05 (checksum 11415 -> {222, 223, 225}) and 5900A05B (checksum
    13872 -> 232), verified 2026-09-04 from Tech#1 checksums, so no
    single decoder id can be keyed on it. The sheets instead carry the
    wire-protocol family (``arvor_i_sbe41cp``) and the engine is chosen
    from the telemetry checksum at decode time. registry.csv is not a
    metadata/routing authority for these floats at all.
    """
    # The SBE41CP sensor-firmware string must never become a map key.
    assert "7.2.5" not in FIRMWARE_TO_DECODER
    # The APF9 map itself is unchanged.
    assert FIRMWARE_TO_DECODER == {
        "061810": 1005,
        "110613": 1010,
        "090413": 1010,
        "102015": 1010,
        "091515": 1010,
        "091615": 1010,
        "100410": 1010,
        "020811": 1010,
    }

    arvor_i = {1902844, 2904082, 6990711, 7902408}
    for row in loader.iter_floats():
        if row.wmo in arvor_i:
            # Family detection, never the APF9 firmware map.
            assert row.platform_type == "ARVOR"
            assert row.platform_maker == "NKE"
            assert row.frame_length == 100
            assert row.decoder_id == 0
            assert row.decoder_version == ""
            assert row.profile_class == "arvor_i_sbe41cp"
        else:
            assert row.decoder_version in FIRMWARE_TO_DECODER
            assert row.decoder_id > 0
            assert row.profile_class == ""

    # registry.csv must NOT provide routing/metadata for ARVOR-I floats.
    registry_wmos = {
        r.wmo for r in CsvLoader(REPO_ROOT / "config" / "registry.csv", strict=False).iter_floats()
    }
    assert not (registry_wmos & arvor_i)


def test_config_parameters_reproduce_the_gdac_block(loader: MultiCsvLoader) -> None:
    """The 14 populated CONFIG_* cells are the 14 GDAC entries, in order.

    Verified against ``2902222_meta.nc`` LAUNCH_CONFIG_PARAMETER_NAME.
    """
    row = loader.get_float(2902222)
    assert row is not None
    pairs = list(row.config_parameters)
    assert [name for name, _ in pairs] == [
        "CONFIG_TransmissionRepetitionPeriod_seconds",
        "CONFIG_ParkTime_hours",
        "CONFIG_AscentTime_hours",
        "CONFIG_SurfaceTime_HH",
        "CONFIG_ParkPressure_dbar",
        "CONFIG_UpTime_hours",
        "CONFIG_ProfilePressure_dbar",
        "CONFIG_MissionPreludeTime_hours",
        "CONFIG_DownTime_hours",
        "CONFIG_TripInterval_hours",
        "CONFIG_CycleTime_hours",
        "CONFIG_PistonPark_COUNT",
        "CONFIG_PistonProfile_COUNT",
        "CONFIG_DepthTable_NUMBER",
    ]
    assert [value for _, value in pairs] == [
        "0",
        "222",
        "5.4",
        "6.6",
        "1000",
        "12",
        "2000",
        "6",
        "222",
        "1",
        "240",
        "66",
        "25",
        "67",
    ]


def test_empty_config_cells_are_not_emitted() -> None:
    pairs = build_config_parameters(
        {"WMO id": "1", "CONFIG_ParkTime_hours": "222", "CONFIG_IceDetection_degC": ""}
    )
    assert pairs == [("CONFIG_ParkTime_hours", "222")]


def test_pressure_coefficients_match_gdac_byte_for_byte() -> None:
    """The published string is reproduced exactly, formatting included.

    Taken verbatim from ``2902222_meta.nc``
    PREDEPLOYMENT_CALIB_COEFFICIENT[0]: magnitudes >= 1 carry four
    decimals (25.1785, -19.3599) while smaller ones use five significant
    digits (-0.043144, -3.3056e-08).
    """
    row = {
        "WMO id": "2902222",
        "SBE serial number": "6672",
        "PA0": "-0.04314358",
        "PA1": "0.1397197",
        "PA2": "-3.305634e-08",
        "PTCA0": "-19.35985",
        "PTCA1": "-0.003776541",
        "PTCA2": "-0.0004912132",
        "PTCB0": "25.1785",
        "PTCB1": "-0.0011",
        "PTCB2": "0",
        "PTHA0": "-73.25506",
        "PTHA1": "0.04943863",
        "PTHA2": "-1.833335e-07",
    }
    calibrations = build_calibrations(row)
    assert calibrations[0].comment == (
        "ser# = 6672 pressure coeffs: PA0 = -0.043144 PA1 = 0.13972 PA2 = -3.3056e-08 "
        "PTCA0 = -19.3599 PTCA1 = -0.0037765 PTCA2 = -0.00049121 PTCB0 = 25.1785 "
        "PTCB1 = -0.0011 PTCB2 = 0 PTHA0 = -73.2551 PTHA1 = 0.049439 PTHA2 = -1.8333e-07"
    )


def test_pressure_formatting_is_five_significant_digits_not_repr() -> None:
    """WMO 2902223 discriminates the rounding rule from a plain ``%g``.

    From ``2902223_meta.nc``: GDAC publishes ``PA0 = 0.10848``, whereas
    Python's default ``%g`` would emit ``0.108478``. A formatter that
    merely round-trips the float therefore does not match the reference.
    """
    calibrations = build_calibrations(
        {
            "WMO id": "2902223",
            "SBE serial number": "6348",
            "PA0": "0.1084775",
            "PA1": "0.1405354",
            "PA2": "-3.716536e-08",
        }
    )
    assert calibrations[0].comment == (
        "ser# = 6348 pressure coeffs: PA0 = 0.10848 PA1 = 0.14054 PA2 = -3.7165e-08"
    )


def test_temperature_coefficients_use_the_sea_bird_labels() -> None:
    """GDAC prints ``A0..A3`` even though the sheet column is ``TA0..TA3``."""
    calibrations = build_calibrations(
        {
            "WMO id": "2902222",
            "SBE serial number": "6672",
            "TA0": "9.818357e-05",
            "TA1": "0.0002662343",
            "TA2": "-1.849021e-06",
            "TA3": "1.365519e-07",
        }
    )
    assert calibrations[0].comment == (
        "ser# = 6672 temperature coeffs: A0 =   0.0001 A1 =   0.0003 A2 =  -0.0000 A3 =   0.0000"
    )


def test_calibration_equations_are_shared_per_measured_parameter() -> None:
    """Constant per sensor model, verified across 11 INCOIS GDAC floats."""
    row = MultiCsvLoader(METADATA_DIR).get_float(2902222)
    assert row is not None
    by_parameter = {c.parameter: c.equation for s in row.sensors for c in s.calibration}
    assert by_parameter["PRES"] == SBE41_CALIB_EQUATIONS["PRES"]
    assert by_parameter["TEMP"] == SBE41_CALIB_EQUATIONS["TEMP"]
    assert by_parameter["PSAL"] == SBE41_CALIB_EQUATIONS["PSAL"]
    assert by_parameter["PRES"].startswith("y=thermistor output;")


def test_missing_calibration_emits_equations_but_never_invents_coefficients(
    tmp_path: Path,
) -> None:
    """A float with no calib row still publishes the equations.

    The equations are a property of the SBE41 sensor model, byte-identical
    across all eleven sampled INCOIS floats, so emitting them asserts
    nothing about the individual instrument. The coefficients are genuinely
    per-float and must stay empty rather than being guessed.

    Driven through a metadata directory whose ``calib.csv`` holds only its
    header, so the assertion tracks the *absent-row* code path rather than
    whichever floats happen to be un-calibrated in the shipped sheets.
    """
    for name in ("meta.csv", "sensor-info.csv", "config_params.csv"):
        (tmp_path / name).write_bytes((METADATA_DIR / name).read_bytes())
    header = (METADATA_DIR / "calib.csv").read_bytes().split(b"\r\n")[0]
    (tmp_path / "calib.csv").write_bytes(header + b"\r\n")

    row = MultiCsvLoader(tmp_path).get_float(2901304)
    assert row is not None
    meta = builder.build_meta(row)
    equations = [v for entry in meta.PREDEPLOYMENT_CALIB_EQUATION for v in entry.values()]
    assert equations[0].startswith("y=thermistor output;")
    assert "ITS-90" in equations[1]
    assert "Conductivity" in equations[2]
    # "n/a" is the JSON contract's not-available token; the writer renders
    # it as a blank NC_CHAR field, matching a reference with no value.
    coefficients = [v for entry in meta.PREDEPLOYMENT_CALIB_COEFFICIENT for v in entry.values()]
    assert coefficients == ["n/a", "n/a", "n/a"]
    assert all(not calibration.coefficients for s in row.sensors for calibration in s.calibration)


def test_apf9a_calibration_reproduces_the_published_gdac_strings(
    loader: MultiCsvLoader,
) -> None:
    """Pins the 2901304/2901305 coefficients to their GDAC ``_meta.nc``.

    Both expected strings are copied from the published references, not
    from ``calib.csv``, so this fails if the formatting rules regress. The
    ``%8.4f`` temperature/conductivity fields are lossy in the reference
    (``TA0 = 1.86e-05`` prints as ``0.0000``), which is exactly why the
    coefficients had to come from the calibration sheet.
    """
    expected = {
        2901304: (
            "ser# = 5234 pressure coeffs: PA0 = 0.314 PA1 = 0.14 PA2 = -4.16e-08 "
            "PTCA0 = 53.9 PTCA1 = 0.179 PTCA2 = -0.00348 PTCB0 = 25.3 PTCB1 = 0.0001 "
            "PTCB2 = 0 PTHA0 = -73.7 PTHA1 = 0.0493 PTHA2 = -7.68e-08",
            "ser# = 5234 temperature coeffs: A0 =   0.0000 A1 =   0.0003 "
            "A2 =  -0.0000 A3 =   0.0000",
            "ser# = 5234 conductivity coeffs: G =  -1.0500 H =   0.1460 I =  -0.0004 "
            "J =   0.0000 CPCOR =  -0.0000 CTCOR =   0.0000 WBOTC =  -0.0000",
        ),
        2901305: (
            "ser# = 5238 pressure coeffs: PA0 = 0.0366 PA1 = 0.14 PA2 = -4.04e-08 "
            "PTCA0 = 34.4 PTCA1 = 0.129 PTCA2 = -0.0054 PTCB0 = 25.3 PTCB1 = -0.00115 "
            "PTCB2 = 0 PTHA0 = -76 PTHA1 = 0.0509 PTHA2 = -5.21e-07",
            "ser# = 5238 temperature coeffs: A0 =   0.0000 A1 =   0.0003 "
            "A2 =  -0.0000 A3 =   0.0000",
            "ser# = 5238 conductivity coeffs: G =  -1.0200 H =   0.1470 I =  -0.0004 "
            "J =   0.0000 CPCOR =  -0.0000 CTCOR =   0.0000 WBOTC =  -0.0000",
        ),
    }
    for wmo, published in expected.items():
        row = loader.get_float(wmo)
        assert row is not None, wmo
        meta = builder.build_meta(row)
        emitted = [v for entry in meta.PREDEPLOYMENT_CALIB_COEFFICIENT for v in entry.values()]
        assert tuple(emitted) == published, wmo


def test_conductivity_equation_keeps_its_published_leading_space() -> None:
    """GDAC emits the SBE41 conductivity equation with a leading space.

    Byte-identical (md5 7b62fc10) on 2901304, 2901305, 2901339, 2902201,
    2902222, 2902223 and 2902224. Stripping it -- which the generic
    metadata cleaner used to do -- shifted every character of the block.
    """
    assert SBE41_CALIB_EQUATIONS["PSAL"].startswith(" f = inst freq")
    assert not SBE41_CALIB_EQUATIONS["PRES"].startswith(" ")
    assert not SBE41_CALIB_EQUATIONS["TEMP"].startswith(" ")


def test_end_mission_date_is_copied_from_the_sheet_not_derived(
    loader: MultiCsvLoader,
) -> None:
    """Dead-float dates come from the sheet; live floats stay blank.

    Values are the official INCOIS ``END_MISSION_DATE`` stamps, verified
    today against ``2901304_meta.nc`` and ``2901305_meta.nc``. They are
    not last-message times: 2901305's date is 650 days after its last
    published profile, so deriving it would fabricate an operational fact.
    """
    dead = loader.get_float(2901304)
    other_dead = loader.get_float(2901305)
    live = loader.get_float(2902222)
    assert dead is not None and other_dead is not None and live is not None
    assert dead.end_mission_date == "20110922051440"
    assert other_dead.end_mission_date == "20130813144956"
    assert live.end_mission_date == ""
    meta = builder.build_meta(dead)
    assert meta.end_mission_date == "20110922051440"
    live_meta = builder.build_meta(live)
    assert live_meta.end_mission_date == ""


def test_end_mission_date_stays_blank_when_the_sheet_has_no_value(
    tmp_path: Path,
) -> None:
    """An empty cell must not be filled from last telemetry or Status."""
    for name in ("meta.csv", "sensor-info.csv", "calib.csv", "config_params.csv"):
        (tmp_path / name).write_bytes((METADATA_DIR / name).read_bytes())
    text = (tmp_path / "meta.csv").read_text(encoding="utf-8")
    text = text.replace("20110922051440", "")
    (tmp_path / "meta.csv").write_text(text, encoding="utf-8")
    row = MultiCsvLoader(tmp_path).get_float(2901304)
    assert row is not None
    assert row.end_mission_status == "T"
    assert row.end_mission_date == ""
    assert builder.build_meta(row).end_mission_date == ""


def test_dac_wide_defaults_are_applied(loader: MultiCsvLoader) -> None:
    """Verified invariant across an 11-float INCOIS GDAC sample."""
    for row in loader.iter_floats():
        assert row.data_centre == INCOIS_DEFAULTS["data_centre"] == "IN"
        assert row.pi_name == "M Ravichandran"
        assert row.project_name == "Argo INDIA"


def test_controller_board_type_is_derived_from_the_serial_prefix(loader: MultiCsvLoader) -> None:
    """9A-/9G- serials are APF9 boards on 9/9 sampled GDAC floats."""
    apf9g = loader.get_float(2902222)
    apf9a = loader.get_float(2901304)
    assert apf9g is not None and apf9a is not None
    assert apf9g.controller_board_primary_type == "APF9"
    assert apf9a.controller_board_primary_type == "APF9"
    # GDAC lower-cases the serial.
    assert apf9g.controller_board_primary_serial == "9g-10795"


def test_info_json_contract_is_unchanged(loader: MultiCsvLoader) -> None:
    """The decoder-facing info.json keys must not drift."""
    info = builder.build_info(loader.get_float(2902222))
    payload = info.model_dump(by_alias=True)
    assert set(payload) == {
        "WMO",
        "PTT",
        "FLOAT_TYPE",
        "DECODER_VERSION",
        "DECODER_ID",
        # Added 2026-09-04: family-level wire-protocol routing key derived
        # from the sheet signature (empty for every APF9 float).
        "PROFILE_CLASS",
        "FRAME_LENGTH",
        "CYCLE_LENGTH",
        "DRIFT_SAMPLING_PERIOD",
        "DELAI",
        "LAUNCH_DATE",
        "LAUNCH_LON",
        "LAUNCH_LAT",
        "REFERENCE_DAY",
        "DM_FLAG",
        "END_DECODING_DATE",
        # Per-deployment cycle offset (``np0``). Additive: absent from a
        # registry row it defaults to 0, so the decoder sees the same
        # cycle numbers as before.
        "NP0",
    }
    assert str(payload["DECODER_ID"]) == "1010"
    assert str(payload["PTT"]) == "152389"


def test_accuracy_defaults_to_the_dac_convention_without_a_calib_row() -> None:
    """A float with no calibration sheet still publishes the DAC's zeros.

    All six sampled INCOIS APEX floats carry
    ``PARAMETER_ACCURACY = PARAMETER_RESOLUTION = 0, 0, 0``, including
    2901304 and 2901305 which have no ``calib.csv`` row. Falling back to
    the manufacturer specification there would report a precision the DAC
    does not claim.
    """
    assert build_accuracy({}) == {
        "PRES": INCOIS_DEFAULT_ACCURACY,
        "TEMP": INCOIS_DEFAULT_ACCURACY,
        "PSAL": INCOIS_DEFAULT_ACCURACY,
    }
    row = MultiCsvLoader(METADATA_DIR).get_float(2901304)
    assert row is not None
    assert [getattr(s, "accuracy", None) for s in row.sensors] == ["0", "0", "0"]


# ---------------------------------------------------------------------------
# SENSOR_MAKER / SENSOR_MODEL coherence (Argo reference tables 26 and 27)
# ---------------------------------------------------------------------------

#: The one legal ``SENSOR_MAKER`` for each ``SENSOR_MODEL`` we emit.
#:
#: Not a convention we chose: reference table 27 links every model to
#: exactly one maker via SKOS ``broader``
#: (``R27::DRUCK -> R26::DRUCK``, ``R27::SBE41 -> R26::SBE``), and the
#: GDAC file checker rejects any other pairing in check ``CK_0164``
#: (``ArgoMetadataFileValidator.java:1032``). The historical INCOIS 2016
#: references publish ``DRUCK``/``SBE`` and are themselves rejected, so
#: these expectations deliberately do **not** follow GDAC.
_MODEL_TO_LEGAL_MAKER = {
    "DRUCK": "DRUCK",
    "KISTLER": "KISTLER",
    "SBE41": "SBE",
}


def test_sensor_firmware_revision_is_exposed_separately(loader: MultiCsvLoader) -> None:
    """sensor-info's "firmware revision number" rides along as its own field.

    For the ARVOR-I SBE41CP fleet it is the CTD sensor firmware ("7.2.5")
    -- the label GDAC publishes in FIRMWARE_VERSION -- while the row's
    ``firmware_version`` stays the float-engine date-code used for
    routing/publication. Both must survive the csv4 load.
    """
    arvor = loader.get_float(1902844)
    assert arvor is not None
    assert arvor.firmware_version == "160414"  # engine date-code (config_params)
    assert arvor.sensor_firmware_version == "7.2.5"  # CTD sensor (sensor-info)


def test_pressure_sensor_keeps_its_own_maker(loader: MultiCsvLoader) -> None:
    """The Druck/Kistler transducer is not made by Sea-Bird.

    ``SENSOR_MAKER`` names the firm that built the transducer, not the
    firm that integrated it into the CTD. Publishing ``SBE`` here is what
    produced ``SENSOR_MODEL/SENSOR_MAKER[3]: Inconsistent:
    'DRUCK'/'SBE'`` on every INCOIS APEX ``_meta.nc``.
    """
    row = loader.get_float(2901304)
    assert row is not None
    pres = next(s for s in row.sensors if s.sensor == "CTD_PRES")
    assert (pres.model, pres.make) == ("DRUCK", "DRUCK")

    # A Kistler hull must track its own maker too, not fall back to SBE.
    kistler = loader.get_float(2901350)
    assert kistler is not None
    pres = next(s for s in kistler.sensors if s.sensor == "CTD_PRES")
    assert (pres.model, pres.make) == ("KISTLER", "KISTLER")


def test_every_sensor_row_is_a_physically_coherent_instrument(
    loader: MultiCsvLoader,
) -> None:
    """No row may pair a model with a maker that did not build it.

    Guards the whole ``N_SENSOR`` block rather than the single index the
    checker happened to report first, so a future row-shift or a new
    transducer added to the sheets cannot reintroduce the defect.
    """
    offenders = []
    for row in loader.iter_floats():
        for entry in row.sensors:
            expected = _MODEL_TO_LEGAL_MAKER.get(entry.model)
            if expected is not None and entry.make != expected:
                offenders.append((row.wmo, entry.sensor, entry.model, entry.make))
    assert offenders == []


def test_ctd_module_stays_sea_bird(loader: MultiCsvLoader) -> None:
    """The fix must not push the transducer maker onto the CTD rows.

    ``CTD_TEMP`` and ``CTD_CNDC`` are the Sea-Bird module itself, so they
    keep ``SBE`` and the CTD serial while only ``CTD_PRES`` changes.
    """
    row = loader.get_float(2901304)
    assert row is not None
    ctd = [s for s in row.sensors if s.sensor in {"CTD_TEMP", "CTD_CNDC"}]
    assert len(ctd) == 2
    assert {(s.make, s.model, s.serial) for s in ctd} == {("SBE", "SBE41", "5234")}


def test_unknown_pressure_maker_is_passed_through_not_forced_to_sbe() -> None:
    """An unrecognised transducer must not be relabelled Sea-Bird.

    Silently attributing an unknown transducer to SBE is exactly the
    defect being fixed; passing the sheet value through lets the file
    checker report it instead of hiding it behind a plausible-looking
    but wrong manufacturer.
    """
    entries = _sensors_from_rows(
        {
            "CTD mfg": "SeaBird",
            "CTD Sensor Type": "SBE41",
            "CTD serial number": "1",
            "Pressure sensor mfg": "AMETEK",
            "Pressure sensor serial #": "2",
        },
        [],
    )
    pres = next(e for e in entries if e.sensor == "CTD_PRES")
    assert (pres.model, pres.make) == ("AMETEK", "AMETEK")
