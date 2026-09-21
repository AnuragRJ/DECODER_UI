"""Real-time QC (RTQC) pipeline.

Phase 3 M2 implements the per-profile RTQC tests for NKE Provor/Arvor
CTS4 Iridium SBD floats.  Two passes are defined over vertical arrays
plus one set of scalar checks:

* **Pass 1 (non-density)** — :mod:`argo_decoder.rtqc.non_density`
  covers TEST006 (global range), TEST008 (pressure increasing),
  TEST009 (spike), TEST011 (gradient) and TEST013 (stuck value).
* **Pass 2 (density inversion)** — :mod:`argo_decoder.rtqc.density_inversion`
  implements TEST014 on top of TEOS-10 potential density
  (gsw.SA_from_SP + gsw.CT_from_t + gsw.rho at the mid-point
  reference pressure between adjacent levels).
* **Profile-scalar tests** — :mod:`argo_decoder.rtqc.profile_scalar`
  covers TEST001 (platform identification), TEST002 (impossible
  date) and TEST003 (impossible location) which operate on whole-profile
  scalars (JULD, LATITUDE, LONGITUDE).

Each test lives in a dedicated module and operates on plain numpy
arrays / Python scalars (no xarray / file IO) so it can be unit tested
in isolation.
"""

from argo_decoder.rtqc.bathymetry import (
    LAND_ELEVATION_M,
    BathymetryUnavailableError,
    GebcoGrid,
    open_gebco,
)
from argo_decoder.rtqc.cross_cycle import (
    DRIFT_BAND_DBAR,
    DRIFT_THRESHOLD_PSAL,
    DRIFT_THRESHOLD_TEMP,
    FROZEN_SLAB_DBAR,
    MAX_DRIFT_SPEED_M_S,
    CrossCycleOutcome,
    frozen_profile_test,
    great_circle_metres,
    gross_sensor_drift_test,
    impossible_speed_test,
)
from argo_decoder.rtqc.cross_cycle_pass import apply_cross_cycle_rtqc
from argo_decoder.rtqc.density_inversion import (
    DENSITY_INVERSION_THRESHOLD,
    density_inversion_test,
)
from argo_decoder.rtqc.non_density import (
    DEEPEST_PRESSURE_FRACTION,
    DEEPEST_PRESSURE_MIN_TOL_DBAR,
    GLOBAL_RANGE,
    GRADIENT_PRESSURE_SPLIT_DBAR,
    GRADIENT_THRESHOLD_DEEP,
    GRADIENT_THRESHOLD_SHALLOW,
    PRESSURE_INVERSION_TOL_DB,
    ROLLOVER_THRESHOLD,
    SPIKE_PRESSURE_SPLIT_DBAR,
    SPIKE_THRESHOLD_DEEP,
    SPIKE_THRESHOLD_SHALLOW,
    STUCK_RUN_LENGTH,
    QcTestOutcome,
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
from argo_decoder.rtqc.profile_pipeline import apply_rtqc_to_profiles
from argo_decoder.rtqc.profile_scalar import (
    LandCheck,
    ScalarQcOutcome,
    run_profile_scalar_tests,
)

__all__ = [
    "DEEPEST_PRESSURE_FRACTION",
    "DEEPEST_PRESSURE_MIN_TOL_DBAR",
    "DENSITY_INVERSION_THRESHOLD",
    "DRIFT_BAND_DBAR",
    "DRIFT_THRESHOLD_PSAL",
    "DRIFT_THRESHOLD_TEMP",
    "FROZEN_SLAB_DBAR",
    "GLOBAL_RANGE",
    "GRADIENT_PRESSURE_SPLIT_DBAR",
    "GRADIENT_THRESHOLD_DEEP",
    "GRADIENT_THRESHOLD_SHALLOW",
    "LAND_ELEVATION_M",
    "MAX_DRIFT_SPEED_M_S",
    "PRESSURE_INVERSION_TOL_DB",
    "ROLLOVER_THRESHOLD",
    "SPIKE_PRESSURE_SPLIT_DBAR",
    "SPIKE_THRESHOLD_DEEP",
    "SPIKE_THRESHOLD_SHALLOW",
    "STUCK_RUN_LENGTH",
    "BathymetryUnavailableError",
    "CrossCycleOutcome",
    "GebcoGrid",
    "LandCheck",
    "QcTestOutcome",
    "ScalarQcOutcome",
    "apply_cross_cycle_rtqc",
    "apply_rtqc_to_profiles",
    "deepest_pressure_test",
    "density_inversion_test",
    "digit_rollover_test",
    "frozen_profile_test",
    "global_range_test",
    "gradient_test",
    "great_circle_metres",
    "gross_sensor_drift_test",
    "impossible_speed_test",
    "near_surface_pressure_test",
    "open_gebco",
    "pressure_increasing_test",
    "run_non_density_tests",
    "run_profile_scalar_tests",
    "spike_test",
    "stuck_value_test",
]
