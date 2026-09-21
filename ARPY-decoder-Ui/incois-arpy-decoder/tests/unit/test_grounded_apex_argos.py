"""GROUNDED (Argo reference table 20) derivation for APEX/ARGOS floats.

APF9 telemetry carries no grounding status bit, but the flag is still
derivable from float *performance*: a cycle whose ascending profile stops
short of the programmed profile pressure hit the seabed.

Rule, and the evidence for it, in ``docs/GROUNDED_INVESTIGATION.md``::

    T    = CONFIG_ProfilePressure_dbar
    Pmax = deepest PRES of the ascending profile

    'U' if Pmax or T is unavailable
    'Y' if Pmax < T - GROUNDED_PRESSURE_MARGIN_DBAR
    'N' otherwise

These tests pin the classifier, the boundary, the unknown paths, and the
end-to-end wiring through ``build_argos_trajectory_records``.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pytest
import xarray as xr

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.trajectory import build_trajectory_dataset
from argo_decoder.platforms.apex_argos.decoder import _max_ascent_pressures
from argo_decoder.platforms.apex_argos.frames import ArgosFix
from argo_decoder.platforms.apex_argos.trajectory import (
    GROUNDED_PRESSURE_MARGIN_DBAR,
    ArgosCycleTelemetry,
    build_argos_trajectory_records,
    grounded_flag,
)

TARGET = 2000.0


# ---------------------------------------------------------------------------
# Fixtures mirroring a real INCOIS APEX/ARGOS float
# ---------------------------------------------------------------------------


def _meta(*, profile_pressure: str | None = "2000") -> FloatMeta:
    """A 2000 dbar APEX float, optionally without the profile target."""
    names: dict[str, str] = {"LAUNCH_CONFIG_PARAMETER_NAME_1": "CONFIG_ParkPressure_dbar"}
    values: dict[str, str] = {"LAUNCH_CONFIG_PARAMETER_VALUE_1": "1000"}
    if profile_pressure is not None:
        names["LAUNCH_CONFIG_PARAMETER_NAME_2"] = "CONFIG_ProfilePressure_dbar"
        values["LAUNCH_CONFIG_PARAMETER_VALUE_2"] = profile_pressure
    return FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "2901304",
            "PLATFORM_TYPE": "APEX",
            "DATA_CENTRE": "IN",
            "FLOAT_SERIAL_NO": "5386",
            "FIRMWARE_VERSION": "020811",
            "WMO_INST_TYPE": "846",
            "LAUNCH_DATE": "20101104120000",
            "LAUNCH_LATITUDE": -56.0,
            "LAUNCH_LONGITUDE": 84.0,
            "LAUNCH_CONFIG_PARAMETER_NAME": [names],
            "LAUNCH_CONFIG_PARAMETER_VALUE": [values],
        }
    )


def _telemetry(cycle: int) -> ArgosCycleTelemetry:
    return ArgosCycleTelemetry(
        cycle_number=cycle,
        fixes=[
            ArgosFix(
                at=datetime(2011, 1, 1 + (cycle % 20), 7, 0, 0, tzinfo=UTC),
                latitude=-56.0,
                longitude=84.0,
                location_class="3",
            )
        ],
        message_times=[datetime(2011, 1, 1 + (cycle % 20), 6, 30, 0, tzinfo=UTC)],
    )


def _grounded_by_cycle(
    deepest: dict[int, float],
    *,
    cycles: list[int] | None = None,
    meta: FloatMeta | None = None,
) -> dict[int, str]:
    """Run the real builder and read GROUNDED back per cycle."""
    order = cycles if cycles is not None else sorted(deepest)
    records = build_argos_trajectory_records(
        [_telemetry(c) for c in order],
        meta=meta if meta is not None else _meta(),
        max_ascent_pressure_dbar=deepest,
    )
    return {c.cycle_number: c.grounded for c in records.cycles}


def _profile_ds(pressures: list[float], *, direction: str = "A") -> xr.Dataset:
    """A minimal stand-in for a decoded mono-profile dataset."""
    return xr.Dataset(
        {
            "PRES": (("N_PROF", "N_LEVELS"), np.array([pressures], dtype=np.float32)),
            "DIRECTION": ((), np.array(direction.encode("ascii"), dtype="|S1")),
        }
    )


# ---------------------------------------------------------------------------
# 1. WMO 2901304 -- the published INCOIS classification
# ---------------------------------------------------------------------------

# Deepest ascending PRES per cycle, read from our own decoder's output for
# WMO 2901304 (``2901304_prof.nc``). These are decoder outputs, not GDAC
# values: the point of the test is that our pressures drive the rule.
# Cycles 21-23 decode to zero profile levels and so are absent.
WMO_2901304_MAX_ASCENT_PRESSURE: dict[int, float] = {
    1: 1899.3,
    2: 1998.4,
    3: 2000.2,
    4: 1899.7,
    5: 1999.5,
    6: 2000.0,
    7: 1900.4,
    8: 1999.1,
    9: 1900.2,
    10: 1999.1,
    11: 1899.7,
    12: 1998.2,
    13: 1900.2,
    14: 2000.7,
    15: 1900.4,
    16: 2000.5,
    17: 1899.7,
    18: 1999.0,
    19: 1899.7,
    20: 2000.3,
}

# INCOIS's published GROUNDED on 2901304 (``2901304_Rtraj.nc``): Y*5, N*15,
# U*3. Held as the expected classification, never as decoder input.
WMO_2901304_EXPECTED_Y = (1, 4, 11, 17, 19)
WMO_2901304_EXPECTED_U = (21, 22, 23)
WMO_2901304_CYCLES = tuple(range(1, 24))


def test_2901304_reproduces_published_grounded_classification() -> None:
    """All 23 cycles of WMO 2901304, from our own decoded pressures."""
    flags = _grounded_by_cycle(
        WMO_2901304_MAX_ASCENT_PRESSURE,
        cycles=list(WMO_2901304_CYCLES),
    )
    expected = {
        cycle: (
            "U"
            if cycle in WMO_2901304_EXPECTED_U
            else "Y"
            if cycle in WMO_2901304_EXPECTED_Y
            else "N"
        )
        for cycle in WMO_2901304_CYCLES
    }
    assert flags == expected


def test_2901304_flag_counts_match_the_reference() -> None:
    """Y*5, N*15, U*3 -- the counts INCOIS publishes."""
    flags = _grounded_by_cycle(
        WMO_2901304_MAX_ASCENT_PRESSURE,
        cycles=list(WMO_2901304_CYCLES),
    )
    counts = {code: sum(1 for v in flags.values() if v == code) for code in "YNU"}
    assert counts == {"Y": 5, "N": 15, "U": 3}


def test_2901304_grounded_cycles_are_exactly_the_shallow_ones() -> None:
    """Y is not arbitrary: every Y cycle stopped >100 dbar short, no N did.

    Guards against a mutant that classifies on cycle number or ordering
    rather than on pressure.
    """
    flags = _grounded_by_cycle(
        WMO_2901304_MAX_ASCENT_PRESSURE,
        cycles=list(WMO_2901304_CYCLES),
    )
    yes = [p for c, p in WMO_2901304_MAX_ASCENT_PRESSURE.items() if flags[c] == "Y"]
    no = [p for c, p in WMO_2901304_MAX_ASCENT_PRESSURE.items() if flags[c] == "N"]
    assert max(yes) < TARGET - GROUNDED_PRESSURE_MARGIN_DBAR
    assert min(no) >= TARGET - GROUNDED_PRESSURE_MARGIN_DBAR
    # The classes really are separated by the margin, not merely ordered.
    assert min(no) - max(yes) == pytest.approx(0.5, abs=0.3)


def test_2901304_grounded_reaches_the_written_netcdf() -> None:
    """The derivation survives serialisation into ``<wmo>_Rtraj.nc``."""
    records = build_argos_trajectory_records(
        [_telemetry(c) for c in WMO_2901304_CYCLES],
        meta=_meta(),
        max_ascent_pressure_dbar=WMO_2901304_MAX_ASCENT_PRESSURE,
    )
    ds = build_trajectory_dataset(records, wmo=2901304, meta=_meta(), institution="IN")
    written = [bytes(v).decode("ascii") for v in np.asarray(ds["GROUNDED"].values)]
    assert written.count("Y") == 5
    assert written.count("N") == 15
    assert written.count("U") == 3
    index = list(np.asarray(ds["CYCLE_NUMBER_INDEX"].values))
    for cycle in WMO_2901304_EXPECTED_Y:
        assert written[index.index(cycle)] == "Y"
    for cycle in WMO_2901304_EXPECTED_U:
        assert written[index.index(cycle)] == "U"


# ---------------------------------------------------------------------------
# 2. Boundary behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pmax", "expected"),
    [
        (TARGET - GROUNDED_PRESSURE_MARGIN_DBAR - 0.1, "Y"),
        (TARGET - GROUNDED_PRESSURE_MARGIN_DBAR, "N"),
        (TARGET - GROUNDED_PRESSURE_MARGIN_DBAR + 0.1, "N"),
    ],
)
def test_boundary_is_strictly_below_target_minus_margin(pmax: float, expected: str) -> None:
    """Exactly on ``target - margin`` is N; only strictly below is Y."""
    assert grounded_flag(pmax, TARGET) == expected


def test_boundary_holds_end_to_end_through_the_builder() -> None:
    """The strict comparison is not lost between classifier and record."""
    edge = TARGET - GROUNDED_PRESSURE_MARGIN_DBAR
    flags = _grounded_by_cycle({1: edge - 0.1, 2: edge, 3: edge + 0.1})
    assert flags == {1: "Y", 2: "N", 3: "N"}


def test_margin_is_one_hundred_dbar() -> None:
    """Pin the INCOIS constant.

    Not the 150 dbar figure from the cookbook's ascent-rate annex: the
    investigation measured 150 as materially worse (165 errors versus 78
    across 12 518 cycles).
    """
    assert GROUNDED_PRESSURE_MARGIN_DBAR == 100.0
    # A float 120 dbar short is grounded under the verified rule and would
    # not be under a 150 dbar margin.
    assert grounded_flag(TARGET - 120.0, TARGET) == "Y"


def test_margin_scales_with_the_configured_target_not_a_fixed_depth() -> None:
    """A 1000 dbar float is judged against 900, not against 1900.

    Guards against a mutant that hardcodes the 1900 dbar boundary seen on
    the 2000 dbar reference fleet.
    """
    assert grounded_flag(1899.0, 1000.0) == "N"
    assert grounded_flag(850.0, 1000.0) == "Y"
    assert grounded_flag(950.0, 1000.0) == "N"


# ---------------------------------------------------------------------------
# 3./4./5. Unknown inputs must never become Y or N
# ---------------------------------------------------------------------------


def test_missing_target_pressure_is_unknown() -> None:
    """No CONFIG_ProfilePressure_dbar means no verdict."""
    assert grounded_flag(500.0, None) == "U"


def test_missing_target_pressure_is_unknown_end_to_end() -> None:
    """A metadata backend without the target reports U, never a guess.

    The pressures used here would all be Y against a 2000 dbar target, so
    a mutant that inferred the target from the data would be caught.
    """
    flags = _grounded_by_cycle(
        {1: 800.0, 2: 900.0, 3: 1899.7},
        meta=_meta(profile_pressure=None),
    )
    assert flags == {1: "U", 2: "U", 3: "U"}


def test_no_ascending_profile_levels_is_unknown() -> None:
    """A cycle absent from the pressure mapping is U, not N."""
    assert grounded_flag(None, TARGET) == "U"
    assert _grounded_by_cycle({1: 1899.7}, cycles=[1, 2]) == {1: "Y", 2: "U"}


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_pressure_is_unknown(bad: float) -> None:
    """NaN/inf are missing values, not shallow profiles."""
    assert grounded_flag(bad, TARGET) == "U"


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_non_finite_target_is_unknown(bad: float) -> None:
    assert grounded_flag(bad, bad) == "U"
    assert grounded_flag(1500.0, bad) == "U"


def test_empty_and_fill_only_profiles_do_not_produce_a_false_yes() -> None:
    """A profile of nothing but fill is U -- it is not a 0 dbar cast.

    This is the dangerous mutant: treating fill as a real pressure makes
    ``max`` either huge (N) or, once filtered wrongly, zero (a false Y on
    a cycle the float may have flown perfectly).
    """
    datasets = {
        1: _profile_ds([99999.0, 99999.0]),
        2: _profile_ds([]),
        3: _profile_ds([math.nan, math.nan]),
    }
    assert _max_ascent_pressures(datasets) == {}
    assert _grounded_by_cycle({}, cycles=[1, 2, 3]) == {1: "U", 2: "U", 3: "U"}


def test_fill_levels_do_not_inflate_the_deepest_pressure() -> None:
    """A short cast padded with fill is still recognised as short."""
    datasets = {4: _profile_ds([10.4, 900.2, 1899.7, 99999.0, 99999.0])}
    assert _max_ascent_pressures(datasets) == pytest.approx({4: 1899.7})
    assert _grounded_by_cycle(_max_ascent_pressures(datasets)) == {4: "Y"}


# ---------------------------------------------------------------------------
# 6. Park pressure must not drive the flag
# ---------------------------------------------------------------------------


def test_park_pressure_alone_cannot_determine_grounded() -> None:
    """Park samples (MC 290/296) carry no grounding signal.

    This is the error the original investigation made: on the reference
    floats the park phase sits at ~1000 dbar on grounded and ungrounded
    cycles alike (median 1005 vs 1003 dbar on 2901304). Two cycles with
    identical park pressure but different profile depth must classify
    differently, so nothing about the park phase can be deciding it.
    """
    park = 1003.0
    flags = _grounded_by_cycle({1: 1899.7, 2: 2000.3})
    assert flags == {1: "Y", 2: "N"}
    # Feeding the park pressure as the profile depth would call both Y,
    # which is exactly the failure mode being excluded.
    assert grounded_flag(park, TARGET) == "Y"
    assert grounded_flag(park, TARGET) != flags[2]


def test_only_ascending_profiles_are_measured() -> None:
    """A descending cast is not evidence about the profile target."""
    datasets = {
        1: _profile_ds([10.0, 1899.7], direction="A"),
        2: _profile_ds([10.0, 800.0], direction="D"),
    }
    assert _max_ascent_pressures(datasets) == pytest.approx({1: 1899.7})


def test_negative_provisional_cycles_are_ignored() -> None:
    """Unresolved transmissions carry a negative key and are not cycles."""
    datasets = {-1: _profile_ds([10.0, 500.0]), 3: _profile_ds([10.0, 1999.0])}
    assert _max_ascent_pressures(datasets) == pytest.approx({3: 1999.0})


# ---------------------------------------------------------------------------
# 7. Independence from the bathymetry path
# ---------------------------------------------------------------------------


def test_grounded_does_not_depend_on_bathymetry_configuration() -> None:
    """GROUNDED is performance-derived; TEST004/GEBCO is a separate path.

    INCOIS publishes ``Y``/``N``; reference table 20 reserves ``B``/``C``
    for the bathymetry-database route, so the two must not be entangled.
    The classifier takes only two pressures -- there is no bathymetry
    argument to pass, and this test pins that signature.
    """
    import inspect

    params = set(inspect.signature(grounded_flag).parameters)
    assert params == {"max_ascent_pressure_dbar", "target_pressure_dbar"}
    assert "bathymetry" not in inspect.signature(build_argos_trajectory_records).parameters
    # And the emitted codes stay inside the performance half of table 20.
    produced = set(_grounded_by_cycle({1: 1899.7, 2: 2000.3, 3: math.nan}).values())
    assert produced <= {"Y", "N", "U"}
    assert not produced & {"B", "C"}
