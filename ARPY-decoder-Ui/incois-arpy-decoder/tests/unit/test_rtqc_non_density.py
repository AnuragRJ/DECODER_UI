"""Phase 3 M2: unit tests for non-density RTQC tests."""

from __future__ import annotations

import numpy as np

from argo_decoder.domain.qc import QcFlag
from argo_decoder.rtqc.non_density import (
    deepest_pressure_test,
    digit_rollover_test,
    global_range_test,
    gradient_test,
    near_surface_pressure_test,
    pressure_increasing_test,
    run_non_density_tests,
    spike_test,
    stuck_value_test,
)


def _mk_smooth_profile() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pres = np.arange(0.0, 1000.0, 10.0)
    temp = np.linspace(20.0, 2.0, len(pres))
    psal = np.full(len(pres), 35.0)
    return pres, temp, psal


class TestGlobalRange:
    def test_flags_out_of_range_temp(self) -> None:
        p, t, _s = _mk_smooth_profile()
        t[5] = np.nan  # undefined level -> NO_QC, never BAD
        t[20] = 50.0  # too hot
        out = global_range_test("TEMP", p, t)
        assert int(out.per_level[5]) == QcFlag.NO_QC
        assert int(out.per_level[20]) == QcFlag.BAD
        assert out.n_flagged == 1

    def test_all_good_profile(self) -> None:
        p, t, _s = _mk_smooth_profile()
        out = global_range_test("TEMP", p, t)
        assert out.n_flagged == 0
        assert out.profile_flag == QcFlag.GOOD


class TestPressureIncreasing:
    def test_flags_reversal_beyond_tolerance(self) -> None:
        # QC Manual v3.9 / Coriolis: a reversal only counts once it
        # exceeds 20 dbar (PRESURE_INVERSION_TOL_DB), and it condemns
        # both ends of the reversed pair.
        pres = np.array([0.0, 50.0, 20.0, 60.0])  # 50 -> 20 = 30 dbar drop
        out = pressure_increasing_test(pres)
        assert int(out.per_level[1]) == QcFlag.BAD
        assert int(out.per_level[2]) == QcFlag.BAD
        assert int(out.per_level[0]) == QcFlag.GOOD

    def test_small_reversal_within_tolerance_passes(self) -> None:
        pres = np.array([0.0, 10.0, 5.0, 20.0])  # 5 dbar wobble
        out = pressure_increasing_test(pres)
        assert out.n_flagged == 0

    def test_monotonic_passes(self) -> None:
        p, _, _ = _mk_smooth_profile()
        out = pressure_increasing_test(p)
        assert out.n_flagged == 0


class TestSpike:
    def test_single_spike_flagged(self) -> None:
        p, t, _ = _mk_smooth_profile()
        t[10] += 20.0  # huge spike
        out = spike_test("TEMP", p, t)
        assert int(out.per_level[10]) >= int(QcFlag.PROBABLY_BAD)

    def test_smooth_profile_passes(self) -> None:
        p, t, _ = _mk_smooth_profile()
        out = spike_test("TEMP", p, t)
        assert out.n_flagged == 0


class TestGradient:
    def test_excessive_gradient_flagged(self) -> None:
        # v3.9 triplicate form: the judged level is the middle one and
        # the test value is |V2 - (V3 + V1)/2|.
        p = np.array([0.0, 1.0, 2.0])
        t = np.array([20.0, 30.0, 2.0])  # |30 - 11| = 19 > 9 (shallow)
        out = gradient_test("TEMP", p, t)
        assert int(out.per_level[1]) == int(QcFlag.BAD)
        assert int(out.per_level[0]) == int(QcFlag.GOOD)
        assert int(out.per_level[2]) == int(QcFlag.GOOD)

    def test_gradient_at_threshold_passes(self) -> None:
        p = np.array([0.0, 1.0, 2.0])
        t = np.array([20.0, 20.0, 2.0])  # |20 - 11| = 9 -> not > 9
        out = gradient_test("TEMP", p, t)
        assert out.n_flagged == 0


class TestStuckValue:
    def test_stuck_sensor_flagged(self) -> None:
        p = np.arange(0.0, 200.0, 10.0)
        t = np.full(len(p), 4.5)  # completely stuck
        out = stuck_value_test(p, t)
        assert int(out.per_level[0]) == QcFlag.BAD
        assert out.n_flagged == len(p)

    def test_changing_values_pass(self) -> None:
        p, t, _ = _mk_smooth_profile()
        out = stuck_value_test(p, t)
        assert out.n_flagged == 0


class TestRunNonDensity:
    def test_returns_all_param_arrays(self) -> None:
        p, t, s = _mk_smooth_profile()
        out = run_non_density_tests(pres=p, temp=t, psal=s, cndc=np.full(len(p), 3.5))
        assert set(out) == {"PRES", "TEMP", "PSAL", "CNDC"}
        for _k, arr in out.items():
            assert arr.dtype == np.int8
            assert len(arr) == len(p)

    def test_fill_samples_stay_no_qc(self) -> None:
        """Prompt-8 contract: un-defined levels are NO_QC ('0'), never BAD."""
        p, t, s = _mk_smooth_profile()
        t[0] = np.nan
        out = run_non_density_tests(pres=p, temp=t, psal=s)
        assert int(out["TEMP"][0]) == QcFlag.NO_QC


# ---------------------------------------------------------------------------
# Specification conformance for the tests corrected/added in this slice
# ---------------------------------------------------------------------------


class TestStuckValueIsWholeProfile:
    """QC Manual v3.9 Test 13 is about the *whole* profile, not a run.

    The earlier run-of-eight rule wrongly condemned isothermal layers:
    on WMO 2901304 it flagged 37 levels the reference calls good.
    """

    def test_constant_profile_flags_every_level(self) -> None:
        pres = np.arange(0.0, 100.0, 10.0)
        values = np.full(len(pres), 4.321)
        out = stuck_value_test(pres, values)
        assert np.all(out.per_level == int(QcFlag.BAD))

    def test_isothermal_layer_inside_a_varying_profile_is_good(self) -> None:
        """The discriminating case: a long identical run that recovers."""
        pres = np.arange(0.0, 200.0, 10.0)
        values = np.full(len(pres), 1.705)
        values[:3] = [8.0, 6.0, 4.0]
        values[-3:] = [1.2, 0.9, 0.6]
        out = stuck_value_test(pres, values)
        assert np.all(out.per_level == int(QcFlag.GOOD))
        assert out.n_flagged == 0

    def test_run_screen_can_be_re_enabled_explicitly(self) -> None:
        pres = np.arange(0.0, 200.0, 10.0)
        values = np.full(len(pres), 1.705)
        values[:3] = [8.0, 6.0, 4.0]
        values[-3:] = [1.2, 0.9, 0.6]
        out = stuck_value_test(pres, values, run_length=8)
        assert out.n_flagged > 0


class TestDigitRollover:
    """QC Manual v3.9 Test 12."""

    def test_temperature_jump_over_ten_degrees_flags_both_levels(self) -> None:
        pres = np.array([10.0, 20.0, 30.0])
        temp = np.array([15.0, 1.0, 0.9])  # 14 degC step
        out = digit_rollover_test("TEMP", pres, temp)
        assert out.per_level[0] == int(QcFlag.BAD)
        assert out.per_level[1] == int(QcFlag.BAD)
        assert out.per_level[2] == int(QcFlag.GOOD)

    def test_salinity_threshold_is_five_psu(self) -> None:
        pres = np.array([10.0, 20.0])
        assert digit_rollover_test("PSAL", pres, np.array([35.0, 39.0])).n_flagged == 0
        assert digit_rollover_test("PSAL", pres, np.array([35.0, 41.0])).n_flagged == 2

    def test_unknown_parameter_is_not_screened(self) -> None:
        pres = np.array([10.0, 20.0])
        assert digit_rollover_test("CNDC", pres, np.array([1.0, 99.0])).n_flagged == 0


class TestDeepestPressure:
    """QC Manual v3.9 Test 19: probably-bad ('3'), not bad."""

    def test_levels_beyond_target_plus_tolerance_are_suspect(self) -> None:
        pres = np.array([500.0, 2000.0, 2500.0])
        out = deepest_pressure_test(pres, 2000.0)
        # tolerance = max(10% of 2000, 100) = 200 -> limit 2200
        assert out.per_level[1] == int(QcFlag.GOOD)
        assert out.per_level[2] == int(QcFlag.PROBABLY_BAD)

    def test_shallow_targets_use_the_flat_100_dbar_tolerance(self) -> None:
        pres = np.array([100.0, 250.0])
        out = deepest_pressure_test(pres, 200.0)
        # 10% of 200 is 20, but the floor is 100 -> limit 300
        assert out.n_flagged == 0

    def test_unknown_configuration_flags_nothing(self) -> None:
        pres = np.array([100.0, 5000.0])
        assert deepest_pressure_test(pres, None).n_flagged == 0


class TestNearSurfacePressure:
    """QC Manual v3.9 Test 6 pressure action: two bands, not one limit."""

    def test_bands(self) -> None:
        pres = np.array([-6.0, -3.0, -1.0, 10.0])
        out = near_surface_pressure_test(pres)
        assert out.per_level[0] == int(QcFlag.BAD)  # < -5
        assert out.per_level[1] == int(QcFlag.PROBABLY_BAD)  # -5 .. -2.4
        assert out.per_level[2] == int(QcFlag.GOOD)  # ordinary offset
        assert out.per_level[3] == int(QcFlag.GOOD)


class TestCrossParameterRules:
    """Manual section 2.2.4(b)/(c) propagation rules."""

    def test_bad_temperature_degrades_salinity_at_the_same_level(self) -> None:
        pres = np.arange(0.0, 100.0, 10.0)
        temp = np.linspace(20.0, 12.0, len(pres))
        psal = np.linspace(35.0, 35.4, len(pres))
        temp[5] = 500.0  # out of global range -> TEMP bad
        out = run_non_density_tests(pres=pres, temp=temp, psal=psal)
        assert out["TEMP"][5] == int(QcFlag.BAD)
        assert out["PSAL"][5] == int(QcFlag.BAD)

    def test_bad_salinity_does_not_degrade_temperature(self) -> None:
        """The rule is one-way: a bad cell says nothing about the thermistor."""
        pres = np.arange(0.0, 100.0, 10.0)
        temp = np.linspace(20.0, 12.0, len(pres))
        psal = np.linspace(35.0, 35.4, len(pres))
        psal[5] = 100.0  # out of global range -> PSAL bad
        out = run_non_density_tests(pres=pres, temp=temp, psal=psal)
        assert out["PSAL"][5] == int(QcFlag.BAD)
        assert out["TEMP"][5] == int(QcFlag.GOOD)

    def test_bad_pressure_degrades_every_parameter_at_that_level(self) -> None:
        pres = np.arange(0.0, 100.0, 10.0)
        pres[4] = -50.0  # below -5 dbar -> PRES bad
        temp = np.linspace(20.0, 12.0, len(pres))
        psal = np.linspace(35.0, 35.4, len(pres))
        out = run_non_density_tests(pres=pres, temp=temp, psal=psal)
        assert out["PRES"][4] == int(QcFlag.BAD)
        assert out["TEMP"][4] == int(QcFlag.BAD)
        assert out["PSAL"][4] == int(QcFlag.BAD)

    def test_cndc_qc_tracks_psal_qc(self) -> None:
        pres = np.arange(0.0, 100.0, 10.0)
        temp = np.linspace(20.0, 12.0, len(pres))
        psal = np.linspace(35.0, 35.4, len(pres))
        cndc = np.linspace(4.0, 3.6, len(pres))
        psal[5] = 100.0
        out = run_non_density_tests(pres=pres, temp=temp, psal=psal, cndc=cndc)
        assert np.array_equal(out["CNDC"], out["PSAL"])


def test_deepest_pressure_is_reported_in_failed_tests() -> None:
    """HISTORY_QCTEST must name TEST019 when it fires."""
    pres = np.array([100.0, 500.0, 3000.0])
    temp = np.array([15.0, 10.0, 4.0])
    psal = np.array([35.0, 35.1, 34.9])
    failed: set[int] = set()
    run_non_density_tests(
        pres=pres, temp=temp, psal=psal, failed_tests=failed, profile_pressure_dbar=2000.0
    )
    assert 19 in failed


# ---------------------------------------------------------------------------
# Prompt-8 threshold corrections (QC Manual v3.9 / Coriolis chain):
# TEST006 40.0 degC ceiling, TEST009 split thresholds, NO_QC fills.
# ---------------------------------------------------------------------------


class TestPromptEightThresholds:
    """The three deliberate Prompt-8 threshold semantics."""

    def test_t6_temp_ceiling_is_40_degrees(self) -> None:
        p, t, _s = _mk_smooth_profile()
        t[10] = 40.5  # above the manual's 40.0 ceiling (old code allowed 42)
        t[20] = 39.9  # inside
        out = global_range_test("TEMP", p, t)
        assert int(out.per_level[10]) == QcFlag.BAD
        assert int(out.per_level[20]) == QcFlag.GOOD

    def test_t9_shallow_temp_spike_limit_is_six_degrees(self) -> None:
        pres = np.array([90.0, 100.0, 110.0])  # shallow band (< 500 dbar)
        base = np.array([15.0, 15.1, 15.2])
        spiked = base.copy()
        spiked[1] += 4.0  # residual spike 4.0 < 6.0 -> passes
        assert spike_test("TEMP", pres, spiked).n_flagged == 0
        spiked[1] += 3.0  # residual spike 7.0 > 6.0 -> BAD at V2 only
        out = spike_test("TEMP", pres, spiked)
        assert int(out.per_level[1]) == QcFlag.BAD
        assert out.per_level[0] == int(QcFlag.GOOD)
        assert out.per_level[2] == int(QcFlag.GOOD)

    def test_t9_deep_temp_spike_limit_is_two_degrees(self) -> None:
        pres = np.array([790.0, 800.0, 810.0])  # deep band (>= 500 dbar)
        base = np.array([4.0, 4.1, 4.2])
        spiked = base.copy()
        spiked[1] += 1.5  # < 2.0 deep threshold -> passes
        assert spike_test("TEMP", pres, spiked).n_flagged == 0
        spiked[1] += 1.0  # 2.5 > 2.0 -> BAD
        assert int(spike_test("TEMP", pres, spiked).per_level[1]) == QcFlag.BAD

    def test_t9_salinity_split_thresholds(self) -> None:
        shallow = np.array([100.0, 110.0, 120.0])
        deep = np.array([800.0, 810.0, 820.0])
        base = np.array([35.00, 35.01, 35.02])
        spiked = base.copy()
        spiked[1] += 0.6  # < 0.9 shallow, > 0.3 deep
        assert spike_test("PSAL", shallow, spiked).n_flagged == 0
        assert int(spike_test("PSAL", deep, spiked).per_level[1]) == QcFlag.BAD

    def test_t9_gap_breaks_the_triple(self) -> None:
        """A fill between levels splits the defined slice: the levels
        across the gap carry no spike/gradient judgement (NO_QC)."""
        pres = np.array([100.0, 110.0, 120.0, 130.0])
        values = np.array([15.0, np.nan, 25.0, 15.1])
        out = spike_test("TEMP", pres, values)
        assert int(out.per_level[1]) == QcFlag.NO_QC
        # Neither defined level forms a complete triple across the gap.
        assert out.n_flagged == 0

    def test_gradient_deep_threshold_is_three_degrees(self) -> None:
        deep = np.array([800.0, 810.0, 820.0])
        values = np.array([4.0, 4.0, 12.0])  # |4 - 8| = 4 > 3 (deep)
        out = gradient_test("TEMP", deep, values)
        assert int(out.per_level[1]) == int(QcFlag.BAD)
        ok = np.array([4.0, 4.0, 10.0])  # |4 - 7| = 3 -> not > 3
        assert gradient_test("TEMP", deep, ok).n_flagged == 0
