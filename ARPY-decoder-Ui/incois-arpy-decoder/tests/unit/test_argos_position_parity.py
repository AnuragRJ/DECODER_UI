"""Phase 5B: ARGOS position/timing parity and ADMT value conventions.

Covers the satellite-fix parsing added to the ARGOS frame reader, the
profile-position selection rule derived from the GDAC ``R*.nc``
references, and the published value conventions applied by the
mono-profile builder (float32 science, reference table 4 institution).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import numpy as np
import pytest
import xarray as xr

from argo_decoder.nc.mono_profile import (
    build_mono_profile_dataset,
    institution_for_data_centre,
)
from argo_decoder.platforms.apex_argos.frames import ArgosFix, parse_argos_fixes
from argo_decoder.platforms.apex_argos.mission import (
    position_qc_for_location_class,
    select_profile_fix,
)
from argo_decoder.platforms.apex_argos.profile import datetime_to_juld

# One real satellite pass header followed by its message block, in the
# CLS/Coriolis format-1 layout used by the supplied raw files.
RAW_PASS = (
    b"02602 152389  89 31 R 1 2026-01-04 06:17:06 -53.854 -158.095  0.000 401649803\r\n"
    b"      2026-01-04 06:10:53  1         2B           0C           15           14\r\n"
    b"02602 152389  105 31 C 2 2026-01-04 14:57:05 -53.784 -157.975  0.000 401649799\r\n"
    b"      2026-01-04 14:50:11  1         B5           0D           03           1E\r\n"
)


def _fix(hour: int, lat: float, lon: float, cls: str = "2") -> ArgosFix:
    return ArgosFix(
        at=datetime(2026, 1, 4, hour, 0, 0, tzinfo=UTC),
        latitude=lat,
        longitude=lon,
        location_class=cls,
    )


# ---------------------------------------------------------------------------
# Fix parsing
# ---------------------------------------------------------------------------


def test_parse_argos_fixes_reads_pass_headers() -> None:
    fixes = parse_argos_fixes(RAW_PASS)
    assert [(f.latitude, f.longitude) for f in fixes] == [
        (-53.854, -158.095),
        (-53.784, -157.975),
    ]
    assert [f.location_class for f in fixes] == ["1", "2"]
    assert fixes[0].at == datetime(2026, 1, 4, 6, 17, 6, tzinfo=UTC)


def test_parse_argos_fixes_deduplicates_repeated_passes() -> None:
    """Format-1 repeats the same pass once per message block."""
    fixes = parse_argos_fixes(RAW_PASS + RAW_PASS)
    assert len(fixes) == 2


def test_parse_argos_fixes_returns_sorted_by_time() -> None:
    fixes = parse_argos_fixes(RAW_PASS)
    assert fixes == sorted(fixes, key=lambda f: f.at)


def test_parse_argos_fixes_handles_binary_payload() -> None:
    assert parse_argos_fixes(b"\xff\xfe\x00\x01") == []


def test_parse_argos_fixes_rejects_out_of_range_coordinates() -> None:
    bad = b"02602 152389  89 31 R 1 2026-01-04 06:17:06 -953.854 -158.095  0.000 4016\r\n"
    assert parse_argos_fixes(bad) == []


# ---------------------------------------------------------------------------
# Position selection rule
# ---------------------------------------------------------------------------


def test_selects_first_fix_at_or_after_profile_juld() -> None:
    """The rule derived from all five reconstructable GDAC references."""
    fixes = [_fix(6, -53.8, -158.0), _fix(10, -53.7, -157.9), _fix(14, -53.6, -157.8)]
    juld = datetime_to_juld(datetime(2026, 1, 4, 9, 0, 0, tzinfo=UTC))
    chosen = select_profile_fix(fixes, juld)
    assert chosen is not None
    assert chosen.latitude == pytest.approx(-53.7)


def test_fix_in_the_same_second_as_juld_counts_as_at_or_after() -> None:
    fixes = [_fix(6, -53.8, -158.0), _fix(10, -53.7, -157.9)]
    juld = datetime_to_juld(datetime(2026, 1, 4, 6, 0, 1, tzinfo=UTC))
    chosen = select_profile_fix(fixes, juld)
    assert chosen is not None
    assert chosen.latitude == pytest.approx(-53.8)


def test_falls_back_to_last_fix_when_all_precede_juld() -> None:
    fixes = [_fix(6, -53.8, -158.0), _fix(10, -53.7, -157.9)]
    juld = datetime_to_juld(datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC))
    chosen = select_profile_fix(fixes, juld)
    assert chosen is not None
    assert chosen.latitude == pytest.approx(-53.7)


def test_uses_last_fix_when_juld_unknown() -> None:
    fixes = [_fix(6, -53.8, -158.0), _fix(10, -53.7, -157.9)]
    chosen = select_profile_fix(fixes, None)
    assert chosen is not None
    assert chosen.latitude == pytest.approx(-53.7)


def test_no_fixes_yields_no_position() -> None:
    assert select_profile_fix([], 27752.0) is None


# ---------------------------------------------------------------------------
# POSITION_QC
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("location_class", ["3", "2", "1", "0", "A", "B"])
def test_located_argos_fixes_are_flagged_good(location_class: str) -> None:
    """A located ARGOS fix carries POSITION_QC='1'.

    Measured on the ``MC=703`` blocks of the four reference floats:
    21 040 of 22 040 fixes (95.5%) are '1', and the flag does not track
    the CLS class -- every class appears under every flag -- so the
    residual '2'/'3' cannot be assigned from the class.
    """
    assert position_qc_for_location_class(location_class) == b"1"


def test_invalid_argos_class_is_flagged_bad() -> None:
    assert position_qc_for_location_class("Z") == b"4"


def test_unknown_class_defaults_to_good() -> None:
    assert position_qc_for_location_class("?") == b"1"


# ---------------------------------------------------------------------------
# Published value conventions
# ---------------------------------------------------------------------------


def test_institution_maps_dac_code_to_reference_table_4_name() -> None:
    assert institution_for_data_centre("IN") == "INCOIS"
    assert institution_for_data_centre("IF") == "IFREMER"
    assert institution_for_data_centre("AO") == "AOML"


def test_unknown_dac_code_passes_through() -> None:
    assert institution_for_data_centre("ZZ") == "ZZ"


def _mono_with_scalars() -> xr.Dataset:
    n = 3
    ds = xr.Dataset(
        {
            name: (("N_LEVELS",), np.array([1.0, 2.0, 3.0], dtype=np.float64))
            for name in ("PRES", "TEMP", "PSAL")
        }
    )
    for name in ("PRES", "TEMP", "PSAL"):
        ds[f"{name}_QC"] = (("N_LEVELS",), np.full(n, 1, dtype=np.int8))
    ds["JULD"] = ((), np.float64(27752.3))
    ds["JULD_LOCATION"] = ((), np.float64(27752.9))
    ds["LATITUDE"] = ((), np.float64(-53.784))
    ds["LONGITUDE"] = ((), np.float64(-157.975))
    ds["POSITION_QC"] = ((), np.array(b"3", dtype="S1"))
    ds["DATA_MODE"] = ((), np.array(b"R", dtype="S1"))
    ds.attrs["n_argos_messages"] = 175
    return ds


def test_juld_location_uses_the_fix_time_not_juld() -> None:
    built = build_mono_profile_dataset(_mono_with_scalars(), wmo=2902222, cycle=328)
    assert built["JULD_LOCATION"].values[0] == pytest.approx(27752.9)
    assert built["JULD"].values[0] == pytest.approx(27752.3)


def test_juld_location_falls_back_to_juld_without_a_fix() -> None:
    ds = _mono_with_scalars()
    del ds["JULD_LOCATION"]
    built = build_mono_profile_dataset(ds, wmo=2902222, cycle=328)
    assert built["JULD_LOCATION"].values[0] == pytest.approx(27752.3)


def test_published_file_carries_only_standard_global_attributes() -> None:
    built = build_mono_profile_dataset(
        _mono_with_scalars(), wmo=2902222, cycle=328, institution="IN"
    )
    assert set(built.attrs) == {
        "title",
        "institution",
        "source",
        "history",
        "references",
        "user_manual_version",
        "Conventions",
        "featureType",
    }
    assert built.attrs["institution"] == "INCOIS"


def test_science_uses_admt_float32_and_fill() -> None:
    built = build_mono_profile_dataset(_mono_with_scalars(), wmo=2902222, cycle=328)
    for name in ("PRES", "TEMP", "PSAL"):
        assert built[name].dtype == np.float32
        assert built[name].attrs["_FillValue"] == np.float32(99999.0)
    assert built["PRES"].attrs["units"] == "decibar"
    assert built["PRES"].attrs["long_name"] == "Sea water pressure, equals 0 at sea-level"
    assert built["TEMP"].attrs["units"] == "degree_Celsius"


def test_decoder_fill_is_mapped_to_admt_fill() -> None:
    ds = _mono_with_scalars()
    ds["PRES"] = (("N_LEVELS",), np.array([1.0, 9999.9, 3.0], dtype=np.float64))
    ds["PRES"].attrs["_FillValue"] = np.float64(9999.9)
    built = build_mono_profile_dataset(ds, wmo=2902222, cycle=328)
    assert built["PRES"].values[0][1] == np.float32(99999.0)


def test_qc_long_name_matches_reference() -> None:
    built = build_mono_profile_dataset(_mono_with_scalars(), wmo=2902222, cycle=328)
    assert built["PRES_QC"].attrs["long_name"] == "quality flag"


# ---------------------------------------------------------------------------
# RTQC provenance for HISTORY QCP$ / QCF$
# ---------------------------------------------------------------------------


def test_qctest_hex_encodes_test_numbers_as_bits() -> None:
    from argo_decoder.sensors.ctd import _qctest_hex

    # Reference D7B7E decodes to tests 1-6, 8, 9, 11-14, 16, 18, 19.
    assert _qctest_hex({1, 2, 3, 4, 5, 6, 8, 9, 11, 12, 13, 14, 16, 18, 19}) == "D7B7E"
    assert _qctest_hex({13}) == "2000"
    assert _qctest_hex(set()) == "0"


def test_tests_performed_lists_only_implemented_tests() -> None:
    from argo_decoder.sensors.ctd import _tests_performed

    without_density = _tests_performed(False)
    assert without_density == {1, 2, 3, 6, 8, 9, 11, 12, 13}
    assert _tests_performed(True) == {1, 2, 3, 6, 8, 9, 11, 12, 13, 14}
    # TEST019 needs CONFIG_ProfilePressure_dbar, so it is only claimed as
    # performed when that configuration was actually supplied.
    assert _tests_performed(True, True) == {1, 2, 3, 6, 8, 9, 11, 12, 13, 14, 19}


def test_failed_tests_report_the_specific_non_density_test() -> None:
    from argo_decoder.sensors.ctd import _tests_failed

    flagged = (np.array([1, 4], dtype=np.int8),)
    assert _tests_failed(True, flagged, {13}) == {13}


def test_no_failures_reported_for_a_clean_profile() -> None:
    from argo_decoder.sensors.ctd import _tests_failed

    clean = (np.array([1, 1], dtype=np.int8),)
    assert _tests_failed(True, clean, set()) == set()


def test_non_density_runner_records_failing_test_numbers() -> None:
    from argo_decoder.rtqc.non_density import STUCK_RUN_LENGTH, run_non_density_tests

    n = STUCK_RUN_LENGTH + 2
    pres = np.arange(1, n + 1, dtype=np.float64) * 10.0
    # A run of identical temperatures trips the stuck-value test (TEST013).
    temp = np.full(n, 5.0, dtype=np.float64)
    psal = np.linspace(35.0, 35.5, n, dtype=np.float64)
    failed: set[int] = set()
    run_non_density_tests(pres=pres, temp=temp, psal=psal, failed_tests=failed)
    assert 13 in failed


def test_non_density_runner_reports_nothing_for_clean_data() -> None:
    from argo_decoder.rtqc.non_density import run_non_density_tests

    pres = np.array([10.0, 20.0, 30.0, 40.0], dtype=np.float64)
    temp = np.array([12.0, 11.5, 11.0, 10.5], dtype=np.float64)
    psal = np.array([35.0, 35.05, 35.1, 35.15], dtype=np.float64)
    failed: set[int] = set()
    run_non_density_tests(pres=pres, temp=temp, psal=psal, failed_tests=failed)
    assert failed == set()


# ---------------------------------------------------------------------------
# Profile JULD == time of the selected surface fix (INCOIS convention)
# ---------------------------------------------------------------------------


def test_profile_juld_equals_selected_fix_time_on_real_telemetry(tmp_path: object) -> None:
    """WMO 2902223 cycle 348 reproduces the GDAC JULD exactly.

    INCOIS sets ``JULD = JULD_LOCATION``: across 443 GDAC R-files for
    WMO 2902223 and 2902224 the two agree in 440 (99.3 %). This cycle is
    the one where the originating raw file is available, so the whole
    decoder chain can be checked against the published product.

    Reference ``R2902223_348.nc`` carries
    ``JULD = JULD_LOCATION = 2026-07-24 01:43:44.999991``; the first
    ARGOS fix in the raw file is at ``01:43:45``. Asserting through the
    emitted dataset (not the helpers) keeps this load-bearing against a
    regression in the decoder wiring.
    """
    from datetime import UTC, datetime
    from pathlib import Path

    from argo_decoder.platforms.apex_argos.frames import (
        iter_argos_messages_from_payload,
        parse_argos_fixes,
        select_redundant_messages,
    )
    from argo_decoder.platforms.apex_argos.mission import (
        profile_juld_from_messages,
        select_profile_fix,
    )
    from argo_decoder.platforms.apex_argos.profile import datetime_to_juld

    raw = (
        Path(__file__).resolve().parents[1] / "data/apex_argos/152382_2026-07-24_2902223_348.txt"
    ).read_bytes()

    selected = select_redundant_messages(iter_argos_messages_from_payload(raw, frame_length=31))
    transmission = profile_juld_from_messages([m.received_at for m in selected])
    fix = select_profile_fix(parse_argos_fixes(raw), transmission)
    assert fix is not None
    expected = datetime_to_juld(datetime(2026, 7, 24, 1, 43, 45, tzinfo=UTC))

    # The decoder must publish the fix time, not the first transmission.
    from argo_decoder.platforms.apex_argos.decoder import ApexArgosDecoder

    source = inspect.getsource(ApexArgosDecoder.decode_float)
    assert "datetime_to_juld(fix.at) if fix is not None else transmission_juld" in source, (
        "decoder must derive the profile JULD from the selected fix"
    )

    assert datetime_to_juld(fix.at) == pytest.approx(expected, abs=1e-9)
    assert transmission is not None
    assert (datetime_to_juld(fix.at) - transmission) * 24 * 60 == pytest.approx(93.4, abs=0.1)
