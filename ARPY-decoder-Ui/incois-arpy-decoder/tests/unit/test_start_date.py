"""``START_DATE`` precedence for APEX/ARGOS.

``START_DATE`` is *"Date (UTC) of the first descent of the float"* (Argo
User Manual v3.3 §2.4; same wording in Coriolis
``create_nc_meta_file_3_1.m:2696``). It is a **deployment property**, so
it must not depend on which cycles happen to be in the archive being
decoded -- Coriolis's output is identical whether one cycle or three
hundred are processed, because it only ever copies the field from the
operator database (``generate_json_float_meta_apx_argos_.m:1015``).

Precedence implemented here:

1. an operator-declared value from the metadata backend;
2. else cycle 1's ``JULD_LOCATION`` -- a DAC convention, **not** the
   literal "first descent" (it is the first fix *after the first
   ascent*);
3. else the ``_FillValue``, which the manual permits: ``_FillValue = " "``
   is declared and §2.4.9 "Mandatory meta-data parameters" does not list
   ``START_DATE``.

Forbidden derivations, each pinned by a test below: the earliest cycle in
the archive, ``LAUNCH_DATE`` (+ prelude), and extrapolation from cycle N.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from argo_decoder.platforms.apex_argos.decoder import _cycle_one_start_date

# 2011-02-14 02:12:23 -- WMO 2901304 cycle 1's first surface fix.
_CYCLE1_LOCATION_JULD = 22324.09193287037
_CYCLE1_LOCATION_STAMP = "20110214021223"
_JULD_FILL = 999999.0


def _profile(juld_location: float | None, juld: float | None = None) -> xr.Dataset:
    """A minimal stand-in for a decoded mono-profile dataset."""
    data: dict[str, tuple[tuple[()], np.ndarray]] = {}
    if juld_location is not None:
        data["JULD_LOCATION"] = ((), np.array(juld_location, dtype=np.float64))
    if juld is not None:
        data["JULD"] = ((), np.array(juld, dtype=np.float64))
    return xr.Dataset(data)


# ---------------------------------------------------------------------------
# Rule 2 -- cycle 1 present
# ---------------------------------------------------------------------------


def test_full_archive_uses_cycle_one_location() -> None:
    """A run containing cycle 1 reports that cycle's first fix."""
    datasets = {1: _profile(_CYCLE1_LOCATION_JULD), 2: _profile(_CYCLE1_LOCATION_JULD + 10)}
    assert _cycle_one_start_date(datasets) == _CYCLE1_LOCATION_STAMP


def test_cycle_one_is_used_even_when_it_is_not_the_lowest_key() -> None:
    """Cycle 0 (the DPF descent) must not displace cycle 1.

    WMO 2901328/2901339/2901350 publish a cycle 0. Taking the lowest key
    dated 2901339's START_DATE ten days early.
    """
    datasets = {
        0: _profile(_CYCLE1_LOCATION_JULD - 10.0),
        1: _profile(_CYCLE1_LOCATION_JULD),
    }
    assert _cycle_one_start_date(datasets) == _CYCLE1_LOCATION_STAMP


def test_location_is_preferred_over_profile_juld() -> None:
    """The convention is ``JULD_LOCATION``, not ``JULD``.

    On the four DPF floats the two differ by 0.6-6.8 h, and it is
    ``JULD_LOCATION`` that reproduces every INCOIS reference exactly.
    """
    datasets = {1: _profile(_CYCLE1_LOCATION_JULD, juld=_CYCLE1_LOCATION_JULD - 0.28)}
    assert _cycle_one_start_date(datasets) == _CYCLE1_LOCATION_STAMP


# ---------------------------------------------------------------------------
# Rule 3 -- cycle 1 absent or unusable
# ---------------------------------------------------------------------------


def test_partial_archive_without_cycle_one_returns_none() -> None:
    """A late-life archive has no evidence of the first descent.

    WMO 2902222's archive starts at cycle 327; deriving from it published
    a 2025 date for a float deployed in 2017.
    """
    datasets = {327: _profile(30000.0), 328: _profile(30010.0), 329: _profile(30020.0)}
    assert _cycle_one_start_date(datasets) is None


def test_no_extrapolation_backwards_from_cycle_n() -> None:
    """Cycle 2 must not be walked back one cycle to invent cycle 1."""
    datasets = {2: _profile(_CYCLE1_LOCATION_JULD + 10.0)}
    assert _cycle_one_start_date(datasets) is None


def test_empty_archive_returns_none() -> None:
    assert _cycle_one_start_date({}) is None


def test_cycle_one_without_location_returns_none() -> None:
    """No fix means no observed evidence, so no value."""
    assert _cycle_one_start_date({1: _profile(None, juld=_CYCLE1_LOCATION_JULD)}) is None


@pytest.mark.parametrize("bad", [_JULD_FILL, np.nan, np.inf])
def test_fill_or_non_finite_location_returns_none(bad: float) -> None:
    """A fill JULD is a missing value, not a timestamp."""
    assert _cycle_one_start_date({1: _profile(bad)}) is None


def test_provisional_negative_cycle_is_not_cycle_one() -> None:
    """Unresolved transmissions carry negative keys and are not cycles."""
    assert _cycle_one_start_date({-1: _profile(_CYCLE1_LOCATION_JULD)}) is None


# ---------------------------------------------------------------------------
# Rule 1 -- the metadata backend wins, and never echoes the launch date
# ---------------------------------------------------------------------------


def test_backend_start_date_is_empty_when_the_sheets_do_not_state_one() -> None:
    """The four-CSV backend must not substitute the launch time.

    ``LAUNCH_DATE``, ``STARTUP_DATE`` and ``START_DATE`` are three
    distinct instants in the manual. Echoing the launch published a value
    the operator never gave.
    """
    from argo_decoder.metadata.multi_csv_loader import _start_datetime

    assert _start_datetime({"launch date": "20170120084400"}) == ""


def test_backend_reads_a_genuine_start_date_column_when_present() -> None:
    """The hook Coriolis relies on: an operator-declared value wins."""
    from argo_decoder.metadata.multi_csv_loader import _start_datetime

    assert _start_datetime({"start date": "20170121042620"}) == "2017-01-21T04:26:20Z"


def test_row_start_date_is_not_defaulted_to_launch() -> None:
    """``build_meta`` must leave START_DATE empty rather than reuse launch.

    Exercised through the real four-CSV backend, so the assertion covers
    the whole metadata path rather than a hand-built row.
    """
    from pathlib import Path

    from argo_decoder.metadata.builder import build_meta
    from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader

    repo_root = Path(__file__).resolve().parents[2]
    metadata_dir = repo_root / "config" / "metadata"
    if not (metadata_dir / "meta.csv").is_file():
        pytest.skip("four-CSV metadata not present")

    row = MultiCsvLoader(metadata_dir).get_float(2902222)
    assert row is not None
    assert row.launch_date_utc is not None
    # The sheets carry no start-date column, so the field must stay unset
    # rather than inherit the launch time.
    assert row.start_date_utc is None
    assert build_meta(row).start_date == ""
