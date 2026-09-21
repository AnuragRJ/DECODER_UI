"""Derived oceanographic variables.

Phase 3 adds CNDC (M3), Aanderaa optode DOXY (M4), and TEOS-10 density
(M2 pass 2 / TEST014).  Submodules expose pure numpy routines so they
can be unit tested in isolation and reused by any platform plugin
without importing sensor or pipeline code.
"""

from argo_decoder.derived.cndc import (
    CNDC_FILL,
    MissingDependencyError,
    conductivity_from_sp,
)
from argo_decoder.derived.density import (
    DENSITY_FILL,
    in_situ_density,
    potential_density,
    sigma0,
)
from argo_decoder.derived.doxy import DOXY_FILL, OptodeCalibration, compute_doxy

__all__ = [
    "CNDC_FILL",
    "DENSITY_FILL",
    "DOXY_FILL",
    "MissingDependencyError",
    "OptodeCalibration",
    "compute_doxy",
    "conductivity_from_sp",
    "in_situ_density",
    "potential_density",
    "sigma0",
]
