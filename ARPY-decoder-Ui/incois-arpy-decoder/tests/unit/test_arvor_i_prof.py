"""Unit tests: ARVOR-I mono-profile adapter (``arvor_i_prof``).

Covers the Coriolis production rules implemented by the adapter — level
assembly, first-mail JULD, arc-minute GPS truncation, the first-mail-fix
Iridium position rule, Coriolis per-level/profile QC semantics, writer
variable order, and the descent publication policy — on synthetic data.
End-to-end parity against the raw datasets and GDAC references is pinned
in ``tests/integration/test_arvor_i_prof_nc.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from argo_decoder.platforms.provor_ir_sbd.arvor_i_prof import (
    PUBLISH_DESCENT_PROFILES,
    VERTICAL_SAMPLING_SCHEME,
    apply_coriolis_profile_qc,
    apply_coriolis_var_order,
    ascent_measurement_rows,
    build_arvor_mono_profiles,
    coriolis_profile_qc,
    descent_measurement_rows,
    first_mail_fix,
    first_mail_time,
    truncate_arc_minutes,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import (
    ArvorCycle,
    ArvorMeasurement,
    ArvorProfile,
    ArvorScienceResult,
    ProfileLocation,
)


@dataclass
class _FakeMail:
    """Duck-typed MailInfo stand-in (only transport fields are read)."""

    cycles: list[int]
    time_of_session: float
    lat: float | None = None
    lon: float | None = None
    cep_radius_km: float | None = None
    pre_launch: bool = False


def _cycle(
    number: int,
    deep: list[float] | None = None,
    shallow: list[float] | None = None,
    descent: list[float] | None = None,
    location: ProfileLocation | None = None,
) -> ArvorCycle:
    profiles: list[ArvorProfile] = []
    for kind, pressures in (
        ("descent", descent),
        ("ascent_deep", deep),
        ("ascent_shallow", shallow),
    ):
        if pressures:
            rows = [
                ArvorMeasurement(pres=p, temp=10.0 + p / 100.0, psal=34.0 + p / 1000.0, slot=0)
                for p in pressures
            ]
            profiles.append(
                ArvorProfile(
                    kind=kind,
                    direction="D" if kind == "descent" else "A",
                    cycle_number=number,
                    measurements=rows,
                    location=location or ProfileLocation(),
                )
            )
    return ArvorCycle(cycle_number=number, profiles=profiles)


# ---------------------------------------------------------------------------
# Arc-minute truncation (mapping §4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("deg", "expected"),
    [
        (2.9410316, 2.0 + 56 / 60),  # GDAC R7902408_001 latitude
        (-64.54295, -(64.0 + 32 / 60)),  # GDAC R6990711_001 latitude
        (70.08330, 70.0 + 4 / 60),  # truncation, not rounding
        (-0.02, -(1.0 / 60.0)),  # 1.2 arc-min truncates to 1
        (2.5, 2.5),  # exact arc-minute is a fixed point
    ],
)
def test_truncate_arc_minutes(deg: float, expected: float) -> None:
    assert truncate_arc_minutes(deg) == pytest.approx(expected, abs=1e-12)


def test_truncate_arc_minutes_sub_minute_is_zero() -> None:
    assert truncate_arc_minutes(-0.0001) == 0.0


# ---------------------------------------------------------------------------
# First-mail JULD and Iridium fix
# ---------------------------------------------------------------------------


def test_first_mail_time_selects_earliest_leading_tag_mail() -> None:
    mails = [
        _FakeMail(cycles=[6], time_of_session=100.0),
        _FakeMail(cycles=[5], time_of_session=98.0),
        _FakeMail(cycles=[5, 6], time_of_session=99.0),  # c5 not leading
        _FakeMail(cycles=[5], time_of_session=101.0, pre_launch=True),  # excluded
    ]
    assert first_mail_time(mails, 5) == 98.0
    assert first_mail_time(mails, 6) == 100.0  # [5,6] does not lead with 6


def test_first_mail_time_missing_returns_none() -> None:
    assert first_mail_time([_FakeMail(cycles=[4], time_of_session=1.0)], 5) is None


def test_first_mail_fix_skips_unusable_and_takes_earliest() -> None:
    mails = [
        _FakeMail(cycles=[7], time_of_session=200.0, lat=1.0, lon=2.0, cep_radius_km=0),
        _FakeMail(cycles=[7], time_of_session=201.0, lat=None, lon=None, cep_radius_km=3),
        _FakeMail(cycles=[7], time_of_session=202.0, lat=3.5, lon=80.5, cep_radius_km=415),
        _FakeMail(cycles=[7], time_of_session=203.0, lat=9.9, lon=9.9, cep_radius_km=1),
    ]
    assert first_mail_fix(mails, 7) == (3.5, 80.5)  # cep 415 still usable (GDAC _006)


def test_first_mail_fix_missing_returns_none() -> None:
    assert first_mail_fix([_FakeMail(cycles=[3], time_of_session=1.0)], 3) is None


# ---------------------------------------------------------------------------
# Coriolis profile QC letter (compute_profile_quality_flag.m port)
# ---------------------------------------------------------------------------


def test_coriolis_profile_qc_all_no_qc_is_blank() -> None:
    assert coriolis_profile_qc(np.array([b"0"] * 30, dtype="S1")) == " "
    assert coriolis_profile_qc(np.array([b"0", b" ", b"9"], dtype="S1")) == " "
    assert coriolis_profile_qc(np.array([], dtype="S1")) == " "


def test_coriolis_profile_qc_ratio_letters() -> None:
    assert coriolis_profile_qc(np.frombuffer(b"1111", dtype="S1")) == "A"
    assert coriolis_profile_qc(np.frombuffer(b"1114", dtype="S1")) == "B"  # 75%
    assert coriolis_profile_qc(np.frombuffer(b"1144", dtype="S1")) == "C"  # 50%
    assert coriolis_profile_qc(np.frombuffer(b"0044", dtype="S1")) == "F"  # 0% of useful


# ---------------------------------------------------------------------------
# Level assembly
# ---------------------------------------------------------------------------


def test_ascent_rows_strictly_ascending_shallow_first() -> None:
    # Science blocks are stored deep-first (descending pressure).
    cyc = _cycle(
        1,
        deep=[2000.0, 1500.0, 1000.0, 600.0],
        shallow=[10.0, 5.0, 2.0],
    )
    rows = ascent_measurement_rows(cyc)
    assert [r.pres for r in rows] == [2.0, 5.0, 10.0, 600.0, 1000.0, 1500.0, 2000.0]


def test_ascent_rows_deep_only_cycle() -> None:
    cyc = _cycle(3, deep=[1900.0, 1300.0])
    assert [r.pres for r in ascent_measurement_rows(cyc)] == [1300.0, 1900.0]


def test_descent_rows_reversed_to_ascending() -> None:
    cyc = _cycle(1, descent=[500.0, 400.0, 100.0])
    assert [r.pres for r in descent_measurement_rows(cyc)] == [100.0, 400.0, 500.0]


# ---------------------------------------------------------------------------
# End-to-end synthetic build
# ---------------------------------------------------------------------------


def _result() -> ArvorScienceResult:
    gps = ProfileLocation(lat=2.9410316, lon=82.9899, qc=1, system="GPS")
    gps.source = "gps"
    cycle1 = _cycle(1, deep=[100.0, 50.0], shallow=[3.0, 1.0], descent=[70.0, 20.0], location=gps)
    cycle2 = _cycle(2, deep=[90.0, 40.0], location=ProfileLocation())  # no GPS
    mails = [
        _FakeMail(cycles=[1], time_of_session=27456.25, lat=2.94, lon=82.98, cep_radius_km=2),
        _FakeMail(cycles=[2], time_of_session=27466.5, lat=3.10, lon=82.50, cep_radius_km=3),
        _FakeMail(cycles=[2], time_of_session=27466.9, lat=3.11, lon=82.51, cep_radius_km=3),
    ]
    return ArvorScienceResult(
        cycles=[cycle1, cycle2],
        mails=mails,  # type: ignore[arg-type]
        notes=[],
    )


def test_build_records_semantics() -> None:
    records = build_arvor_mono_profiles(_result(), wmo=7902408)
    asc = {r.cycle: r for r in records if r.direction == "A"}
    assert sorted(asc) == [1, 2]
    assert all(r.direction == "A" for r in records)

    r1 = asc[1]
    assert r1.filename == "R7902408_001.nc"
    assert r1.juld == pytest.approx(27456.25)
    assert r1.position_source == "gps-truncated"
    assert r1.positioning_system == "GPS"
    assert r1.dataset["LATITUDE"].values.item() == pytest.approx(2.0 + 56 / 60)
    ds = r1.dataset
    assert ds.sizes["N_LEVELS"] == 4
    assert ds.sizes["N_PROF"] == 1 and ds.sizes["N_PARAM"] == 3
    assert list(np.asarray(ds["PRES_QC"].values).reshape(-1)) == [b"0"] * 4
    assert all(ds[f"PROFILE_{p}_QC"].values.item() == b" " for p in ("PRES", "TEMP", "PSAL"))
    assert ds["DIRECTION"].values.item() == b"A"
    assert ds["DATA_MODE"].values.item() == b"R"
    assert ds["JULD_LOCATION"].values.item() == pytest.approx(r1.juld)
    assert ds["JULD_QC"].values.item() == b"1"
    assert ds["POSITION_QC"].values.item() == b"1"
    # Launch mission (GDAC reference publishes 1; 99999 was a placeholder).
    assert int(ds["CONFIG_MISSION_NUMBER"].values.item()) == 1
    vss = bytes(np.asarray(ds["VERTICAL_SAMPLING_SCHEME"].values).reshape(-1)).decode()
    assert vss.strip() == VERTICAL_SAMPLING_SCHEME

    r2 = asc[2]
    assert r2.position_source == "first-mail-fix"
    assert r2.positioning_system == "IRIDIUM"
    assert r2.dataset["LATITUDE"].values.item() == pytest.approx(3.10)
    assert r2.dataset["LONGITUDE"].values.item() == pytest.approx(82.50)


def test_build_descent_policy_flag() -> None:
    result = _result()
    records = build_arvor_mono_profiles(result, wmo=7902408)
    assert PUBLISH_DESCENT_PROFILES is False
    assert not any(r.direction == "D" for r in records)  # default: suppressed

    with_desc = build_arvor_mono_profiles(result, wmo=7902408, publish_descent=True)
    d = [r for r in with_desc if r.direction == "D"]
    assert [r.filename for r in d] == ["R7902408_001D.nc"]
    assert d[0].n_levels == 2
    assert d[0].dataset["DIRECTION"].values.item() == b"D"


def test_apply_var_order_matches_coriolis_layout() -> None:
    records = build_arvor_mono_profiles(_result(), wmo=7902408)
    names = list(records[0].dataset.data_vars)
    assert names.index("PROFILE_PRES_QC") == names.index("POSITIONING_SYSTEM") + 1
    assert names.index("PROFILE_PSAL_QC") < names.index("VERTICAL_SAMPLING_SCHEME")
    assert names.index("PSAL_ADJUSTED_ERROR") < names.index("PARAMETER")
    assert names.index("PSAL_ADJUSTED_QC") < names.index("PRES_ADJUSTED_ERROR")
    assert names[-1] == "HISTORY_QCTEST"
    assert names[-2] == "HISTORY_PREVIOUS_VALUE"


def test_apply_coriolis_profile_qc_noop_without_params() -> None:
    import xarray as xr

    ds = xr.Dataset({"PRES": xr.DataArray(np.zeros(3), dims=("N_LEVELS",))})
    out = apply_coriolis_profile_qc(ds)
    assert "PROFILE_PRES_QC" not in out.data_vars
    assert apply_coriolis_var_order(out) is not None
