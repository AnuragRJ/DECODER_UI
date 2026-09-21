"""Trajectory file construction for Provor/Arvor Iridium SBD floats (M5).

A trajectory NetCDF collects every *measurement* the float makes during a
cycle (not just the up-cast that goes into the profile file): descent,
park/drift, ascent, in-air, surface GPS fixes, and anomalies like groundings
or emergency ascents.

MATLAB's ``create_prv_trajectory_ir_rudics_2xx.m`` /
``collect_traj_data_from_float_tech_ir_sbd2_201_to_232.m`` do this by
parsing Tech2 packet experiment counters (``exp_nb_desc`` /
``exp_nb_drift`` / ``exp_nb_asc`` / ``exp_nb_near_surface`` /
``exp_nb_in_air``) plus CONFIG_PM08/PARK/PROFILE pressure bins from Param1
to classify each CTD/CTDO sample into one of the Argo measurement codes
(MCs):

  * MC  290 - surface (drift at surface between cycles)
  * MC  291 - descent to park
  * MC  292 - drift at park
  * MC  293 - descent to profile
  * MC  294 - ascent / up-cast
  * MC  295 - in-air before transmission
  * MC  296 - deep descent (if multi-parking)
  * MC  700 - grounding (bottom hit detected)
  * MC  703/704 - emergency ascent / EOL

For decoder_id 221 (Provor/Arvor CTS4, single parking + profile), every
sample is routed to descent->park->ascent->in-air bins based on pressure
reversals detected from the packet stream: packets arriving before the
deepest pressure are descent, the deepest packet(s) mark park/drift,
packets after the deepest (which the float samples while ascending) are
the up-cast; samples with PRES < 10 dbar after the ascent are in-air.

This package exposes a :func:`bin_cycle_samples` helper that, given 1-D
arrays of PRES/TEMP/PSAL/CNDC/DOXY in acquisition order, returns a dict
of :class:`TrajectoryBin` keyed by :class:`MeasurementCodes`. NetCDF
writing of the trajectory dataset lands in a follow-up slice once a
Tech2-bearing float is available for oracle validation; until then
bin counts are attached to each mono-profile dataset under the
``trajectory_bin_counts`` attribute for inspection.

The current implementation works without Tech2 packets: pressure
reversals and bin counts classify samples. When Tech2 experiment
counters are present (``exp_nb_desc`` etc.) they are used to validate
and reconcile the binning (to be wired in a follow-up).
"""

from argo_decoder.trajectory.binning import (
    MeasurementCodes,
    TrajectoryBin,
    bin_cycle_samples,
)

__all__ = [
    "MeasurementCodes",
    "TrajectoryBin",
    "bin_cycle_samples",
]
