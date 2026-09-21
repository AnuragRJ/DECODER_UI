"""Cross-cycle RTQC: TEST005 (speed), TEST016 (drift), TEST018 (frozen).

These are the three tests INCOIS runs that this decoder previously did
not. INCOIS's own ``HISTORY_QCTEST`` ``QCP$`` mask for WMO 2901304 is
``D7B7E`` on cycles 2-20 and ``C7B7E`` on cycle 1 -- the same set minus
test 16, because cycle 1 has no predecessor to compare against. That
distinction is asserted here: a test without its inputs must be recorded
as *not run*, not as run-and-passed.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from argo_decoder.domain.qc import QcFlag
from argo_decoder.rtqc.cross_cycle import (
    frozen_profile_test,
    great_circle_metres,
    gross_sensor_drift_test,
    impossible_speed_test,
)
from argo_decoder.rtqc.cross_cycle_pass import apply_cross_cycle_rtqc

_DAY = 1.0


def _profile(
    *,
    juld: float,
    lat: float,
    lon: float,
    temp_offset: float = 0.0,
    psal_offset: float = 0.0,
    n: int = 20,
) -> xr.Dataset:
    """A clean synthetic profile with all-good QC."""
    pres = np.linspace(10.0, 1000.0, n)
    temp = np.linspace(18.0, 3.0, n) + temp_offset
    psal = np.linspace(35.0, 34.6, n) + psal_offset
    good = np.full(n, int(QcFlag.GOOD), dtype=np.int8)
    return xr.Dataset(
        {
            "PRES": (("N_LEVELS",), pres),
            "TEMP": (("N_LEVELS",), temp),
            "PSAL": (("N_LEVELS",), psal),
            "PRES_QC": (("N_LEVELS",), good.copy()),
            "TEMP_QC": (("N_LEVELS",), good.copy()),
            "PSAL_QC": (("N_LEVELS",), good.copy()),
            "JULD": ((), np.float64(juld)),
            "LATITUDE": ((), np.float64(lat)),
            "LONGITUDE": ((), np.float64(lon)),
            "POSITION_QC": ((), np.array(b"1", dtype="|S1")),
        },
        attrs={"rtqc_tests_done_hex": "0", "rtqc_tests_failed_hex": "0"},
    )


# ---------------------------------------------------------------------------
# TEST005 -- impossible speed
# ---------------------------------------------------------------------------


class TestImpossibleSpeed:
    def test_ordinary_drift_passes(self) -> None:
        """~0.1 m/s over ten days is normal Argo drift."""
        qc, ran = impossible_speed_test(
            juld=10.0,
            latitude=-55.0,
            longitude=57.5,
            previous_juld=0.0,
            previous_latitude=-55.5,
            previous_longitude=57.0,
        )
        assert ran is True
        assert qc == b"1"

    def test_teleport_is_flagged(self) -> None:
        """Half the globe in one day cannot be a drifting float."""
        qc, ran = impossible_speed_test(
            juld=1.0,
            latitude=55.0,
            longitude=0.0,
            previous_juld=0.0,
            previous_latitude=-55.0,
            previous_longitude=0.0,
        )
        assert ran is True
        assert qc == b"4"

    def test_missing_previous_position_means_not_run(self) -> None:
        """No predecessor is 'not run', which is not the same as 'passed'."""
        qc, ran = impossible_speed_test(
            juld=10.0,
            latitude=-55.0,
            longitude=57.5,
            previous_juld=None,
            previous_latitude=None,
            previous_longitude=None,
        )
        assert ran is False
        assert qc is None

    def test_zero_elapsed_time_defines_no_speed(self) -> None:
        qc, ran = impossible_speed_test(
            juld=5.0,
            latitude=-55.0,
            longitude=57.5,
            previous_juld=5.0,
            previous_latitude=-50.0,
            previous_longitude=57.5,
        )
        assert ran is False
        assert qc is None

    def test_great_circle_matches_a_known_separation(self) -> None:
        """One degree of latitude is ~111 km anywhere on the globe."""
        d = great_circle_metres(0.0, 0.0, 1.0, 0.0)
        assert d == pytest.approx(111195.0, rel=1e-3)


# ---------------------------------------------------------------------------
# TEST016 -- gross sensor drift
# ---------------------------------------------------------------------------


class TestGrossSensorDrift:
    def test_stable_deep_water_passes(self) -> None:
        pres = np.linspace(10.0, 1000.0, 20)
        psal = np.linspace(35.0, 34.6, 20)
        flags, ran = gross_sensor_drift_test(
            pres=pres,
            values=psal,
            previous_pres=pres,
            previous_values=psal + 0.01,
            threshold=0.5,
        )
        assert ran is True
        assert flags is not None
        assert np.all(flags == int(QcFlag.GOOD))

    def test_large_deep_offset_degrades_the_whole_parameter(self) -> None:
        """A drifting sensor is wrong at every level, not just at depth."""
        pres = np.linspace(10.0, 1000.0, 20)
        psal = np.linspace(35.0, 34.6, 20)
        flags, ran = gross_sensor_drift_test(
            pres=pres,
            values=psal + 1.3,
            previous_pres=pres,
            previous_values=psal,
            threshold=0.5,
        )
        assert ran is True
        assert flags is not None
        # Probably bad ('3'), per the manual -- not bad ('4').
        assert np.all(flags == int(QcFlag.PROBABLY_BAD))

    def test_no_previous_profile_means_not_run(self) -> None:
        pres = np.linspace(10.0, 1000.0, 20)
        flags, ran = gross_sensor_drift_test(
            pres=pres,
            values=np.linspace(35.0, 34.6, 20),
            previous_pres=None,
            previous_values=None,
            threshold=0.5,
        )
        assert ran is False
        assert flags is None


# ---------------------------------------------------------------------------
# TEST018 -- frozen profile
# ---------------------------------------------------------------------------


class TestFrozenProfile:
    def test_identical_replay_is_frozen(self) -> None:
        pres = np.linspace(10.0, 1000.0, 40)
        temp = np.linspace(18.0, 3.0, 40)
        psal = np.linspace(35.0, 34.6, 40)
        frozen, ran = frozen_profile_test(
            pres=pres,
            temp=temp,
            psal=psal,
            previous_pres=pres,
            previous_temp=temp,
            previous_psal=psal,
        )
        assert ran is True
        assert frozen is True

    def test_an_ocean_that_changed_is_not_frozen(self) -> None:
        pres = np.linspace(10.0, 1000.0, 40)
        temp = np.linspace(18.0, 3.0, 40)
        psal = np.linspace(35.0, 34.6, 40)
        frozen, ran = frozen_profile_test(
            pres=pres,
            temp=temp + 0.5,
            psal=psal + 0.05,
            previous_pres=pres,
            previous_temp=temp,
            previous_psal=psal,
        )
        assert ran is True
        assert frozen is False

    def test_uniform_small_offset_is_not_frozen(self) -> None:
        """The min-difference condition is what makes the test specific.

        A uniform shift of 0.003 sits below every max and mean bound, so
        max/mean alone would call this frozen. Only the *minimum*
        condition (< 0.001) rejects it -- a genuinely stuck sensor
        reproduces at least one slab exactly, whereas a real ocean that
        merely changed a little does not.
        """
        pres = np.linspace(10.0, 1000.0, 40)
        temp = np.linspace(18.0, 3.0, 40)
        psal = np.linspace(35.0, 34.6, 40)
        frozen, ran = frozen_profile_test(
            pres=pres,
            temp=temp + 0.003,
            psal=psal + 0.003,
            previous_pres=pres,
            previous_temp=temp,
            previous_psal=psal,
        )
        assert ran is True
        assert frozen is False

    def test_no_previous_profile_means_not_run(self) -> None:
        pres = np.linspace(10.0, 1000.0, 40)
        frozen, ran = frozen_profile_test(
            pres=pres,
            temp=np.linspace(18.0, 3.0, 40),
            psal=np.linspace(35.0, 34.6, 40),
            previous_pres=None,
            previous_temp=None,
            previous_psal=None,
        )
        assert ran is False
        assert frozen is False


# ---------------------------------------------------------------------------
# The whole-float pass
# ---------------------------------------------------------------------------


class TestCrossCyclePass:
    def test_first_cycle_records_no_cross_cycle_tests(self) -> None:
        """Mirrors INCOIS: cycle 1 is C7B7E, later cycles are D7B7E.

        The difference is exactly test 16, which cannot run without a
        predecessor.
        """
        datasets = {
            1: _profile(juld=0.0, lat=-55.0, lon=57.0),
            2: _profile(juld=10.0, lat=-55.1, lon=57.1, temp_offset=0.4, psal_offset=0.05),
        }
        apply_cross_cycle_rtqc(datasets)
        first = int(datasets[1].attrs["rtqc_tests_done_hex"], 16)
        second = int(datasets[2].attrs["rtqc_tests_done_hex"], 16)
        for test in (5, 16, 18):
            assert not first & (1 << test), f"cycle 1 must not claim test {test}"
            assert second & (1 << test), f"cycle 2 must claim test {test}"

    def test_sensor_drift_degrades_the_offending_cycle_only(self) -> None:
        # Cycles must differ a little, else TEST018 correctly calls them
        # a frozen replay and the drift verdict is masked.
        datasets = {
            1: _profile(juld=0.0, lat=-55.0, lon=57.0),
            2: _profile(juld=10.0, lat=-55.1, lon=57.1, temp_offset=0.4, psal_offset=0.05),
            3: _profile(juld=20.0, lat=-55.2, lon=57.2, temp_offset=0.8, psal_offset=1.3),
        }
        failures = apply_cross_cycle_rtqc(datasets)
        assert 16 in failures.get(3, set())
        assert np.all(datasets[3]["PSAL_QC"].values == int(QcFlag.PROBABLY_BAD))
        # Untouched neighbours stay good.
        assert np.all(datasets[2]["PSAL_QC"].values == int(QcFlag.GOOD))
        # TEMP was not the parameter that drifted.
        assert np.all(datasets[3]["TEMP_QC"].values == int(QcFlag.GOOD))

    def test_impossible_speed_condemns_both_ends_of_the_leg(self) -> None:
        datasets = {
            1: _profile(juld=0.0, lat=-55.0, lon=57.0),
            2: _profile(juld=0.5, lat=40.0, lon=57.0),
        }
        apply_cross_cycle_rtqc(datasets)
        assert datasets[1]["POSITION_QC"].values.item() == b"4"
        assert datasets[2]["POSITION_QC"].values.item() == b"4"

    def test_a_condemned_profile_is_not_used_as_the_drift_reference(self) -> None:
        """TEST016 compares against the previous *good* profile.

        Without this, one bad cycle drags its successor down: cycle 3 is
        a genuine outlier, and cycle 4 -- back to normal -- would be
        flagged for differing from cycle 3.
        """
        datasets = {
            1: _profile(juld=0.0, lat=-55.0, lon=57.0),
            2: _profile(juld=10.0, lat=-55.1, lon=57.1, temp_offset=0.4, psal_offset=0.05),
            3: _profile(juld=20.0, lat=-55.2, lon=57.2, temp_offset=0.8, psal_offset=1.35),
            4: _profile(juld=30.0, lat=-55.3, lon=57.3, temp_offset=1.2, psal_offset=0.15),
        }
        failures = apply_cross_cycle_rtqc(datasets)
        assert 16 in failures.get(3, set())
        assert 16 not in failures.get(4, set())
        assert np.all(datasets[4]["PSAL_QC"].values == int(QcFlag.GOOD))

    def test_clean_float_is_left_untouched(self) -> None:
        """No false positives on an ordinary drifting float."""
        datasets = {
            n: _profile(
                juld=10.0 * n,
                lat=-55.0 - 0.1 * n,
                lon=57.0 + 0.1 * n,
                temp_offset=0.02 * n,
                psal_offset=0.01 * n,
            )
            for n in range(1, 6)
        }
        failures = apply_cross_cycle_rtqc(datasets)
        assert failures == {}
        for ds in datasets.values():
            assert np.all(ds["TEMP_QC"].values == int(QcFlag.GOOD))
            assert np.all(ds["PSAL_QC"].values == int(QcFlag.GOOD))

    def test_flags_are_only_ever_degraded(self) -> None:
        """A pre-existing bad flag must survive the cross-cycle pass.

        TEST016 writes '3' across the whole parameter when it fires. A
        level already at '4' from a per-profile test must stay '4' --
        the pass merges worst-case, it does not overwrite.
        """
        datasets = {
            1: _profile(juld=0.0, lat=-55.0, lon=57.0),
            2: _profile(juld=10.0, lat=-55.1, lon=57.1, temp_offset=0.4, psal_offset=0.05),
            3: _profile(juld=20.0, lat=-55.2, lon=57.2, temp_offset=0.8, psal_offset=1.3),
        }
        # Cycle 3 will be degraded to '3' wholesale by TEST016; this one
        # level is already '4' and must not be improved to '3'.
        datasets[3]["PSAL_QC"].values[3] = int(QcFlag.BAD)
        failures = apply_cross_cycle_rtqc(datasets)
        assert 16 in failures.get(3, set())
        assert datasets[3]["PSAL_QC"].values[3] == int(QcFlag.BAD)
        assert datasets[3]["PSAL_QC"].values[0] == int(QcFlag.PROBABLY_BAD)


def test_drift_test_ignores_a_truncated_dive() -> None:
    """A short dive must not read as sensor drift.

    Regression for WMO 2901328 cycle 37, which reached 1248.7 dbar after
    a 1899.4 dbar cycle. Averaging each profile's own deepest 100 dbar
    compared 1250 m water against 1900 m water and produced an apparent
    +2.69 degC drift against a 1.0 degC threshold, condemning every level
    of eleven cycles that GDAC flags good.
    """
    import numpy as np

    from argo_decoder.rtqc.cross_cycle import DRIFT_THRESHOLD_TEMP, gross_sensor_drift_test

    # One consistent water column sampled to two different depths. The
    # profile must be *curved* like real ocean temperature, and curved
    # steeply enough to reproduce the field failure: with a straight line
    # (or a shallow exponential) the mean over 1150-1250 dbar sits close
    # to the mean over 1800-1900 dbar, the old per-profile band passes by
    # luck, and the test does not discriminate the two implementations.
    # These constants put the old rule at +1.85 degC -- comparable to the
    # +2.69 measured on 2901328 cycle 37 -- against a 1.0 threshold.
    def column(deepest: float) -> tuple[np.ndarray, np.ndarray]:
        pres = np.arange(10.0, deepest + 1.0, 10.0)
        temp = 2.0 + 28.0 * np.exp(-pres / 500.0)
        return pres, temp

    deep_pres, deep_temp = column(1900.0)
    short_pres, short_temp = column(1250.0)

    flags, ran = gross_sensor_drift_test(
        pres=short_pres,
        values=short_temp,
        previous_pres=deep_pres,
        previous_values=deep_temp,
        threshold=DRIFT_THRESHOLD_TEMP,
    )
    assert ran is True
    assert flags is not None
    assert int(np.max(flags)) == int(QcFlag.GOOD)


def test_drift_test_still_catches_a_real_offset() -> None:
    """A genuine sensor offset at the same depth must still fire."""
    import numpy as np

    from argo_decoder.rtqc.cross_cycle import DRIFT_THRESHOLD_PSAL, gross_sensor_drift_test

    pres = np.arange(10.0, 1901.0, 10.0)
    psal = np.full_like(pres, 34.9)
    flags, ran = gross_sensor_drift_test(
        pres=pres,
        values=psal + 1.3,  # the 2901304 cycle-20 style jump
        previous_pres=pres,
        previous_values=psal,
        threshold=DRIFT_THRESHOLD_PSAL,
    )
    assert ran is True
    assert flags is not None
    assert int(np.max(flags)) == int(QcFlag.PROBABLY_BAD)


def test_drift_test_declines_to_run_above_the_thermocline() -> None:
    """Two shallow casts cannot support a deep-stability argument."""
    import numpy as np

    from argo_decoder.rtqc.cross_cycle import DRIFT_THRESHOLD_TEMP, gross_sensor_drift_test

    pres = np.arange(5.0, 61.0, 5.0)
    flags, ran = gross_sensor_drift_test(
        pres=pres,
        values=np.full_like(pres, 25.0),
        previous_pres=pres,
        previous_values=np.full_like(pres, 18.0),
        threshold=DRIFT_THRESHOLD_TEMP,
    )
    assert ran is False
    assert flags is None


def test_drift_test_ignores_a_dive_deeper_than_the_previous_one() -> None:
    """The band must stay inside *both* casts, not just the current one.

    The complementary case to a truncated dive: when this cycle goes
    deeper than the last, a band taken from the current profile alone
    falls past the end of the previous one, where interpolation flat-
    lines at its deepest sample and manufactures a large offset.
    """
    import numpy as np

    from argo_decoder.rtqc.cross_cycle import DRIFT_THRESHOLD_TEMP, gross_sensor_drift_test

    def column(deepest: float) -> tuple[np.ndarray, np.ndarray]:
        pres = np.arange(10.0, deepest + 1.0, 10.0)
        return pres, 2.0 + 28.0 * np.exp(-pres / 500.0)

    shallow_pres, shallow_temp = column(1250.0)
    deep_pres, deep_temp = column(1900.0)

    flags, ran = gross_sensor_drift_test(
        pres=deep_pres,
        values=deep_temp,
        previous_pres=shallow_pres,
        previous_values=shallow_temp,
        threshold=DRIFT_THRESHOLD_TEMP,
    )
    assert ran is True
    assert flags is not None
    assert int(np.max(flags)) == int(QcFlag.GOOD)
