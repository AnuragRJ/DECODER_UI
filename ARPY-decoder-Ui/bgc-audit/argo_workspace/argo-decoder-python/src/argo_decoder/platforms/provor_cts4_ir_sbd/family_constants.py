"""Authoritative family-generic constants for PROVOR CTS4 / decoder-301 (5.8).

This module is the single source of truth for coefficients that are
numerically identical across the 13 INCOIS 301 meta.nc (see
``config/metadata/provor_cts4_301_reference.csv`` - 88 values, audit
``test_reference_csv_scope_labels``).  They are *decoder-family* constants,
not per-float metadata, and the decoder no longer needs a WMO whitelist to
obtain them.

Authority stack (scientific rule: Argo standards -> NKE spec -> Coriolis
reference -> raw telemetry -> GDAC publication):

* **NKE 5.8 Mut_ProVBioII-FLBB** S5.3.6 / S7.2.4.9
  (``5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924.pdf``):
  free-zone layout 50 B, FLBB ``Serial 2 UI + ScaleFactor Chlorophyll
  4 FLOAT LE + Dark 2 UI + ScaleFactor Turbidity 4 FLOAT LE + Dark 2 UI
  + ScaleFactor Chlorophyll 4 FLOAT LE``; ``PC 4 1 7..11`` define the five
  FLBB PC parameters.

* **BGC-Argo cookbooks** (``argodatamgt.org/Documentation``):
  - BBP ``doi:10.13155/39459`` v1.4 S2.2:
    ``BBP700 = 2*pi*chi*[(BETA-DARK)*SCALE-BETASW700]`` with
    ``chi = 1.097`` for FLBB 142 deg (Boss/Roesler, Table 1).
    ``BETASW700`` via Zhang et al. 2009 (``betasw_ZHH2009.m``, depol 0.039).
  - CHLA ``doi:10.13155/39468``:
    ``CHLA = (FLUORESCENCE_CHLA-DARK_CHLA)*SCALE_CHLA`` with
    ``SCALE_CHLA = 0.0073`` ug/L per count.
  - Oxygen ``doi:10.13155/39795`` S4.2.2: Aanderaa 4330 standard-foil
    polynomial with 28 ``c/m/n`` exponents and Weiss/Garcia-Gordon
    solubility constants; ``Pcoef1 = 0.1`` etc., ``PhaseCoef2/3 = 0``,
    ``c21..27 = 0``, ``T4/T5 = 0`` are structural zeros of the method.

* **INCOIS GDAC 13 x ``incois_2902*_meta.nc``**
  (``provor_bio_irsbd/ref/gdac_incois_301``):
  ``PREDEPLOYMENT_CALIB_COEFFICIENT`` for each WMO; the 88 generic values
  are byte-identical across all 13 (max |Delta| < 1e-12; probe
  ``scripts/probe_cts4_phase2a_gdac.py`` + audit).
  ``SCALE_BACKSCATTERING700`` and ``DARK_*`` are *float-specific* and live
  in telemetry (OriginalScaleFactor; see SEANOE ``doi:10.17882/54520``
  Barnard table - corrected factor is publication-reprocessed, not used
  for telemetry truth).

* **Coriolis decArgo**
  (``Coriolis-data-processing-chain-for-Argo-floats-container``):
  ``compute_profile_derived_parameters_ir_rudics.m`` / ``calcoxy_*`` /
  ``betasw_ZHH2009.m`` consume the same constants;
  ``generate_json_float_meta_prv_cts4_ir_sbd*.m`` carries them verbatim
  from GDAC meta.

The dedicated ``provor_cts4_301_reference.csv`` therefore remains as
*provenance / bootstrap / audit* (source_file / source_variable per row),
not as a whitelist for these 88 numbers.  A new float needs only its FLBB
250 telemetry plus its own per-float DOXY metadata (PhaseCoef0/1, c0-20,
T0-3); the 88 family numbers come from this module and work for any WMO.

Do NOT add a WMO branch here.  If a future INCOIS batch changed a family
constant (e.g. a new FLBB geometry with different chi), this file would be
versioned with a decoder-family guard, not a per-WMO branch.

All floats in the current batch were calibrated 2012-2013 with FLBB 142 deg
and the same Aanderaa 4330 foil geometry, so the 88-value invariant holds
for the whole fleet.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Scalar family-generic constants — single source of truth
# ---------------------------------------------------------------------------

# FLBB optics — cookbook doi:10.13155/39459 Table 1 + doi:10.13155/39468
SCALE_CHLA: float = 0.0073
# scale_chl_2 is unused second chlorophyll channel (NKE §7.2.4.9 scale_chl_2)
SCALE_CHLA_2: float = 0.0
KHI_700: float = 1.097  # Boss/Roesler χ for 142° FLBB

# DOXY solubility — Weiss Cstar (A0-5) + Garcia-Gordon B0-3/C0 + vapour D0-3 + Spreset
A0: float = 2.00856
A1: float = 3.224
A2: float = 3.99063
A3: float = 4.80299
A4: float = 0.978188
A5: float = 1.71069
B0: float = -0.00624523
B1: float = -0.00737614
B2: float = -0.010341
B3: float = -0.00817083
C0: float = -4.88682e-07
D0: float = 24.4543
D1: float = -67.4509
D2: float = -4.8489
D3: float = -0.000544
Spreset: float = 0.0
Pcoef1: float = 0.1
Pcoef2: float = 0.00022
Pcoef3: float = 0.0419
PhaseCoef2: float = 0.0
PhaseCoef3: float = 0.0

# Aanderaa foil polynomial structural exponents and zero terms
# m0-27 / n0-27 are the method's fixed exponents (INCOIS meta carries them
# verbatim but they are decoder-method constants).
M: tuple[int, ...] = (
    1, 0, 0, 0, 1, 2, 0, 1, 2, 3, 0, 1, 2, 3, 4, 0, 1, 2, 3, 4, 5, 0, 0, 0, 0, 0, 0, 0,
)
N: tuple[int, ...] = (
    4, 5, 4, 3, 3, 3, 2, 2, 2, 2, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
)
# c21-27 are unused foil terms (zero)
C21_27_ZERO: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

# Optode thermistor T4/T5 are structural zeros (T0-3 are float-specific)
TEMP_DOXY_T4: float = 0.0
TEMP_DOXY_T5: float = 0.0

# ---------------------------------------------------------------------------
# Full family-generic map — 88 entries, identical across 13 INCOIS meta.nc
# ---------------------------------------------------------------------------

FAMILY_GENERIC: dict[tuple[str, str], float] = {
    ("BBP700", "khi"): KHI_700,
    ("CHLA", "SCALE_CHLA"): SCALE_CHLA,
    ("DOXY", "A0"): A0,
    ("DOXY", "A1"): A1,
    ("DOXY", "A2"): A2,
    ("DOXY", "A3"): A3,
    ("DOXY", "A4"): A4,
    ("DOXY", "A5"): A5,
    ("DOXY", "B0"): B0,
    ("DOXY", "B1"): B1,
    ("DOXY", "B2"): B2,
    ("DOXY", "B3"): B3,
    ("DOXY", "C0"): C0,
    ("DOXY", "D0"): D0,
    ("DOXY", "D1"): D1,
    ("DOXY", "D2"): D2,
    ("DOXY", "D3"): D3,
    ("DOXY", "Pcoef1"): Pcoef1,
    ("DOXY", "Pcoef2"): Pcoef2,
    ("DOXY", "Pcoef3"): Pcoef3,
    ("DOXY", "PhaseCoef2"): PhaseCoef2,
    ("DOXY", "PhaseCoef3"): PhaseCoef3,
    ("DOXY", "Spreset"): Spreset,
    ("DOXY", "c21"): 0.0,
    ("DOXY", "c22"): 0.0,
    ("DOXY", "c23"): 0.0,
    ("DOXY", "c24"): 0.0,
    ("DOXY", "c25"): 0.0,
    ("DOXY", "c26"): 0.0,
    ("DOXY", "c27"): 0.0,
    ("DOXY", "m0"): 1.0,
    ("DOXY", "m1"): 0.0,
    ("DOXY", "m10"): 0.0,
    ("DOXY", "m11"): 1.0,
    ("DOXY", "m12"): 2.0,
    ("DOXY", "m13"): 3.0,
    ("DOXY", "m14"): 4.0,
    ("DOXY", "m15"): 0.0,
    ("DOXY", "m16"): 1.0,
    ("DOXY", "m17"): 2.0,
    ("DOXY", "m18"): 3.0,
    ("DOXY", "m19"): 4.0,
    ("DOXY", "m2"): 0.0,
    ("DOXY", "m20"): 5.0,
    ("DOXY", "m21"): 0.0,
    ("DOXY", "m22"): 0.0,
    ("DOXY", "m23"): 0.0,
    ("DOXY", "m24"): 0.0,
    ("DOXY", "m25"): 0.0,
    ("DOXY", "m26"): 0.0,
    ("DOXY", "m27"): 0.0,
    ("DOXY", "m3"): 0.0,
    ("DOXY", "m4"): 1.0,
    ("DOXY", "m5"): 2.0,
    ("DOXY", "m6"): 0.0,
    ("DOXY", "m7"): 1.0,
    ("DOXY", "m8"): 2.0,
    ("DOXY", "m9"): 3.0,
    ("DOXY", "n0"): 4.0,
    ("DOXY", "n1"): 5.0,
    ("DOXY", "n10"): 1.0,
    ("DOXY", "n11"): 1.0,
    ("DOXY", "n12"): 1.0,
    ("DOXY", "n13"): 1.0,
    ("DOXY", "n14"): 1.0,
    ("DOXY", "n15"): 0.0,
    ("DOXY", "n16"): 0.0,
    ("DOXY", "n17"): 0.0,
    ("DOXY", "n18"): 0.0,
    ("DOXY", "n19"): 0.0,
    ("DOXY", "n2"): 4.0,
    ("DOXY", "n20"): 0.0,
    ("DOXY", "n21"): 0.0,
    ("DOXY", "n22"): 0.0,
    ("DOXY", "n23"): 0.0,
    ("DOXY", "n24"): 0.0,
    ("DOXY", "n25"): 0.0,
    ("DOXY", "n26"): 0.0,
    ("DOXY", "n27"): 0.0,
    ("DOXY", "n3"): 3.0,
    ("DOXY", "n4"): 3.0,
    ("DOXY", "n5"): 3.0,
    ("DOXY", "n6"): 2.0,
    ("DOXY", "n7"): 2.0,
    ("DOXY", "n8"): 2.0,
    ("DOXY", "n9"): 2.0,
    ("TEMP_DOXY", "T4"): TEMP_DOXY_T4,
    ("TEMP_DOXY", "T5"): TEMP_DOXY_T5,
}

# Keep a frozen view for the resolver's self-documenting audit set.
FAMILY_GENERIC_KEYS: frozenset[tuple[str, str]] = frozenset(FAMILY_GENERIC.keys())

__all__ = [
    "A0",
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "B0",
    "B1",
    "B2",
    "B3",
    "C0",
    "C21_27_ZERO",
    "D0",
    "D1",
    "D2",
    "D3",
    "FAMILY_GENERIC",
    "FAMILY_GENERIC_KEYS",
    "KHI_700",
    "SCALE_CHLA",
    "SCALE_CHLA_2",
    "TEMP_DOXY_T4",
    "TEMP_DOXY_T5",
    "M",
    "N",
    "Pcoef1",
    "Pcoef2",
    "Pcoef3",
    "PhaseCoef2",
    "PhaseCoef3",
    "Spreset",
]
