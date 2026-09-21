"""TEST004 (position on land) and the GEBCO grid reader.

The real GEBCO grid is a ~7 GB external dependency that is deliberately
never committed. These tests build a tiny synthetic grid with the same
structure (``lon`` / ``lat`` / ``elevation``, metres positive up) so the
reader is exercised for real -- coordinate lookup, longitude wrapping,
fill handling and the land threshold -- without the download.
"""

from __future__ import annotations

from pathlib import Path

import netCDF4
import numpy as np
import pytest

from argo_decoder.rtqc.bathymetry import (
    BathymetryUnavailableError,
    GebcoGrid,
    open_gebco,
)
from argo_decoder.rtqc.profile_scalar import run_profile_scalar_tests

# A position that is unambiguously ocean, and one that is unambiguously
# land, in the synthetic grid built below.
OCEAN = (-53.0, 68.0)
LAND = (20.0, 78.0)


def _make_grid(path: Path, *, elevation_name: str = "elevation") -> Path:
    """Write a small GEBCO-shaped grid: land north of the equator."""
    lons = np.arange(-180.0, 180.0, 1.0, dtype=np.float64)
    lats = np.arange(-90.0, 90.0, 1.0, dtype=np.float64)
    elev = np.full((lats.size, lons.size), -4000.0, dtype=np.float32)
    elev[lats > 0.0, :] = 250.0  # northern hemisphere is land
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("lon", lons.size)
        ds.createDimension("lat", lats.size)
        ds.createVariable("lon", "f8", ("lon",))[:] = lons
        ds.createVariable("lat", "f8", ("lat",))[:] = lats
        ds.createVariable(elevation_name, "f4", ("lat", "lon"))[:] = elev
    return path


@pytest.fixture
def grid_path(tmp_path: Path) -> Path:
    return _make_grid(tmp_path / "gebco.nc")


# ---------------------------------------------------------------------------
# Grid reader
# ---------------------------------------------------------------------------


def test_elevation_is_negative_at_sea_and_positive_on_land(grid_path: Path) -> None:
    with GebcoGrid(grid_path) as grid:
        assert grid.elevation_at(*OCEAN) == pytest.approx(-4000.0)
        assert grid.elevation_at(*LAND) == pytest.approx(250.0)


def test_is_on_land_follows_the_sea_level_threshold(grid_path: Path) -> None:
    with GebcoGrid(grid_path) as grid:
        assert grid.is_on_land(*OCEAN) is False
        assert grid.is_on_land(*LAND) is True


def test_longitude_beyond_180_is_wrapped_into_the_grid(grid_path: Path) -> None:
    """A float reported at 292 degE must resolve to the same cell as -68."""
    with GebcoGrid(grid_path) as grid:
        assert grid.elevation_at(-53.0, 292.0) == grid.elevation_at(-53.0, -68.0)


def test_out_of_range_or_non_finite_positions_return_none(grid_path: Path) -> None:
    with GebcoGrid(grid_path) as grid:
        assert grid.elevation_at(float("nan"), 68.0) is None
        assert grid.elevation_at(-53.0, float("inf")) is None
        assert grid.elevation_at(99.0, 68.0) is None


def test_missing_grid_raises_rather_than_guessing(tmp_path: Path) -> None:
    with pytest.raises(BathymetryUnavailableError):
        GebcoGrid(tmp_path / "does-not-exist.nc")


def test_grid_without_an_elevation_variable_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.nc"
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("lon", 2)
        ds.createVariable("lon", "f8", ("lon",))[:] = [0.0, 1.0]
    with pytest.raises(BathymetryUnavailableError):
        GebcoGrid(path)


def test_open_gebco_returns_none_when_unconfigured_or_absent(tmp_path: Path) -> None:
    """A missing grid must degrade to 'cannot run', not raise into the pipeline."""
    assert open_gebco(None) is None
    assert open_gebco(tmp_path / "nope.nc") is None


def test_open_gebco_returns_a_usable_grid(grid_path: Path) -> None:
    grid = open_gebco(grid_path)
    assert grid is not None
    try:
        assert grid.is_on_land(*LAND) is True
    finally:
        grid.close()


# ---------------------------------------------------------------------------
# TEST004 wiring
# ---------------------------------------------------------------------------


def test_test004_flags_a_position_on_land(grid_path: Path) -> None:
    with GebcoGrid(grid_path) as grid:
        out = run_profile_scalar_tests(
            juld=22323.0, latitude=LAND[0], longitude=LAND[1], bathymetry=grid
        )
    assert "TEST004_POSITION_ON_LAND" in out.tests_done
    assert "TEST004_POSITION_ON_LAND" in out.tests_failed
    assert out.position_qc == b"4"


def test_test004_passes_a_position_at_sea(grid_path: Path) -> None:
    with GebcoGrid(grid_path) as grid:
        out = run_profile_scalar_tests(
            juld=22323.0, latitude=OCEAN[0], longitude=OCEAN[1], bathymetry=grid
        )
    assert "TEST004_POSITION_ON_LAND" in out.tests_done
    assert "TEST004_POSITION_ON_LAND" not in out.tests_failed
    assert out.position_qc == b"1"


def test_test004_is_not_run_without_a_grid() -> None:
    """No grid must mean 'not run' -- never a silent pass.

    An absent reference that reported success would certify every
    position as at sea, which is worse than reporting nothing.
    """
    out = run_profile_scalar_tests(juld=22323.0, latitude=LAND[0], longitude=LAND[1])
    assert "TEST004_POSITION_ON_LAND" not in out.tests_done
    assert "TEST004_POSITION_ON_LAND" not in out.tests_failed
    assert out.position_qc == b"1"


def test_test004_does_not_downgrade_an_already_bad_position(grid_path: Path) -> None:
    """A coordinate TEST003 already rejected has no meaningful grid cell."""
    with GebcoGrid(grid_path) as grid:
        out = run_profile_scalar_tests(juld=22323.0, latitude=91.0, longitude=68.0, bathymetry=grid)
    assert "TEST003_IMPOSSIBLE_LOCATION" in out.tests_failed
    assert "TEST004_POSITION_ON_LAND" not in out.tests_done
    assert out.position_qc == b"4"


def test_test004_is_not_marked_done_when_the_grid_cannot_answer(grid_path: Path) -> None:
    """A grid that returns no value must leave the test unreported.

    Marking TEST004 as performed on a cell the grid could not resolve
    would put an untrue claim in HISTORY_QCTEST -- the mask has to record
    what actually ran.
    """

    class _Blind:
        def is_on_land(self, latitude: float, longitude: float) -> bool | None:
            return None

    out = run_profile_scalar_tests(
        juld=22323.0, latitude=OCEAN[0], longitude=OCEAN[1], bathymetry=_Blind()
    )
    assert "TEST004_POSITION_ON_LAND" not in out.tests_done
    assert out.position_qc == b"1"


def test_fill_valued_elevation_cell_is_reported_as_unknown(tmp_path: Path) -> None:
    """A NaN cell must not be read as 0 m and called land.

    This is the masking class of bug already recorded for GROUNDED: a
    fill value coerced through a numeric path silently becomes a real
    reading.
    """
    path = tmp_path / "holey.nc"
    lons = np.array([0.0, 1.0])
    lats = np.array([0.0, 1.0])
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("lon", 2)
        ds.createDimension("lat", 2)
        ds.createVariable("lon", "f8", ("lon",))[:] = lons
        ds.createVariable("lat", "f8", ("lat",))[:] = lats
        ds.createVariable("elevation", "f4", ("lat", "lon"))[:] = np.full((2, 2), np.nan)
    with GebcoGrid(path) as grid:
        assert grid.elevation_at(0.0, 0.0) is None
        assert grid.is_on_land(0.0, 0.0) is None


# ---------------------------------------------------------------------------
# HISTORY_QCTEST mask wiring
# ---------------------------------------------------------------------------


def test_qctest_mask_gains_bit_4_when_a_grid_is_supplied(grid_path: Path) -> None:
    """TEST004 must appear in QCP$ only when it actually ran.

    INCOIS publishes D7B7E for this float; without bit 4 we emitted
    D7B6E. The mask has to record the test as performed, otherwise the
    ADMT provenance record understates what the decoder did.
    """
    import xarray as xr

    from argo_decoder.platforms.apex_argos.profile import add_profile_scalars

    with GebcoGrid(grid_path) as grid:
        ds = xr.Dataset(attrs={"rtqc_tests_done_hex": "7B4E"})
        add_profile_scalars(
            ds, juld=22323.0, latitude=OCEAN[0], longitude=OCEAN[1], bathymetry=grid
        )
    mask = int(str(ds.attrs["rtqc_tests_done_hex"]), 16)
    assert mask & (1 << 4), "TEST004 bit missing from QCP$"
    # the seeded vertical-array bits must survive the merge
    for bit in (1, 2, 3, 6, 9, 11, 13, 14):
        assert mask & (1 << bit), f"bit {bit} lost when merging the scalar outcome"


def test_qctest_mask_omits_bit_4_without_a_grid() -> None:
    """No grid means the bit must stay clear -- never claim an unrun test."""
    import xarray as xr

    from argo_decoder.platforms.apex_argos.profile import add_profile_scalars

    ds = xr.Dataset(attrs={"rtqc_tests_done_hex": "7B4E"})
    add_profile_scalars(ds, juld=22323.0, latitude=OCEAN[0], longitude=OCEAN[1])
    assert not int(str(ds.attrs["rtqc_tests_done_hex"]), 16) & (1 << 4)


def test_failed_qctest_mask_records_a_land_position(grid_path: Path) -> None:
    """A position on land must appear in QCF$, not only QCP$."""
    import xarray as xr

    from argo_decoder.platforms.apex_argos.profile import add_profile_scalars

    with GebcoGrid(grid_path) as grid:
        ds = xr.Dataset(attrs={"rtqc_tests_done_hex": "7B4E"})
        add_profile_scalars(ds, juld=22323.0, latitude=LAND[0], longitude=LAND[1], bathymetry=grid)
    assert int(str(ds.attrs["rtqc_tests_failed_hex"]), 16) & (1 << 4)
    assert bytes(np.asarray(ds["POSITION_QC"].values)) == b"4"
