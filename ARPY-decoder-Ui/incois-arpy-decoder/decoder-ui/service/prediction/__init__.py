"""Next Profile Location prediction (server-side, decoder-ui).

Everything here is a pure computation over data already cached from the
existing Ifremer/Argo GDAC products:

* ``<WMO>_prof.nc`` — published profile history (recency + observed cycle
  interval + profile positions),
* ``<WMO>_Rtraj.nc`` — trajectory fixes, cycle-phase times, parking depth.

There is no local historical-profile database: the only persisted artefacts are
the existing fleet-status cache (a bounded ring of recent fixes per float) and
``data/fleet_status/prediction_calibration.json``, which holds *aggregate*
validation statistics (uncertainty radii, validation metrics, a sparse
regional/seasonal drift grid) produced by ``python -m prediction.validate``.

The browser never talks to a current-model provider: ``currents.py`` is a
server-side provider interface and the shipped default is "no provider
configured", which selects the validated history/prior baseline.
"""

from prediction.predict import predict_fleet, predict_float  # noqa: F401

__all__ = ["predict_float", "predict_fleet"]
