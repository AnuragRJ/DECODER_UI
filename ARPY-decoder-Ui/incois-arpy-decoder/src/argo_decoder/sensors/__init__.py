"""Per-sensor decoders (CTD, DOXY, CHLA, BBP, PH, NITRATE, PAR, IRRADIANCE, ...).

Phase 2 Slice 2 ships a working CTD fast-path for NKE Provor/Arvor CTS4
Iridium SBD floats (linear count->unit conversion matching MATLAB output
for decoder_ids 201-232). Phase 3 M4 adds Aanderaa optode dissolved oxygen
(DOXY) support.  Other sensors land in subsequent slices.
"""

from __future__ import annotations

from argo_decoder.sensors.ctd import (
    COUNT_FILL,
    PRES_FILL,
    PSAL_FILL,
    TEMP_FILL,
    CtdCalibration,
    CtdProfile,
    attach_doxy,
    convert_counts,
    decode_pres,
    decode_psal,
    decode_temp,
    profile_to_dataset,
)

__all__ = [
    "COUNT_FILL",
    "PRES_FILL",
    "PSAL_FILL",
    "TEMP_FILL",
    "CtdCalibration",
    "CtdProfile",
    "attach_doxy",
    "convert_counts",
    "decode_pres",
    "decode_psal",
    "decode_temp",
    "profile_to_dataset",
]
