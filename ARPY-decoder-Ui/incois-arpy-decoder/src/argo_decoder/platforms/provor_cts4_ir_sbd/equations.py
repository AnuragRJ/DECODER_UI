"""Raw→calibrated BGC equations for PROVOR CTS4 / decoder-301 (Phase 2A).

Authority stack (project scientific rule): official Argo standards → NKE spec
→ Coriolis/reference logic → raw telemetry → GDAC publication behavior. Every
function takes EXPLICIT coefficient arguments: there are no hidden defaults
and no metadata reads. Coefficient VALUES with provenance live in
``config/metadata/provor_cts4_301_reference.csv`` (dedicated Phase-2A schema);
this module is pure math.

DOXY chain — Aanderaa optode-4330 standard-foil method. Three independent
authorities agree term-for-term:

* INCOIS GDAC ``PREDEPLOYMENT_CALIB_EQUATION`` for ``DOXY`` (e.g. 2902091
  ``meta.nc``, as-implemented; preserved at
  ``provor_bio_irsbd/ref/gdac_incois_301/``);
* Coriolis ``calcoxy_aanderaa4330_aanderaa.m`` + ``calcoxy_salcomp.m`` +
  ``calcoxy_prescomp.m`` + ``compute_DOXY_27_bis.m`` (reference decoder);
* the oxygen cookbook §4.2.2.1 ("Aanderaa polynomial standard calibration",
  ``cook_oxy.pdf``), with ``Pcoef1 = 0.1`` (§4.2.2) and the note that
  ``PhaseCoef2``/``PhaseCoef3`` are usually zero.

Chain (``T`` = optode temperature °C, ``P`` = pressure dbar, ``S`` = salinity):

1. ``TPHASE = C1 - C2`` (phase degrees)
2. ``Phase_Pcorr = TPHASE + Pcoef1 * P / 1000``
3. ``CalPhase = PhaseCoef0 + PhaseCoef1*Pp + PhaseCoef2*Pp² + PhaseCoef3*Pp³``
4. ``deltaP = Σ_i foil_c[i] * T^m[i] * CalPhase^n[i]`` (28 foil terms)
5. ``AirSat = deltaP*100 / ((nomAirPress - pVapour(T)) * nomAirMix)`` with
   ``pVapour = exp(52.57 - 6690.9/(T+273.15) - 4.681*ln(T+273.15))``
6. ``ln(Cstar) = Σ_k A[k]*Ts^k``, ``Ts = ln((298.15-T)/(273.15+T))``;
   ``MOLAR = Cstar * 44.614 * AirSat / 100`` [µmol/L]
7. ``O2 = MOLAR * Scorr * Pcorr`` [µmol/L] with the Garcia-Gordon-style
   salinity correction ``Scorr`` (``B0..B3``, ``C0``, ``D0..D3``, ``Spreset``)
   and the pressure correction ``Pcorr`` (``Pcoef2``, ``Pcoef3``)
8. ``DOXY = O2 / rho`` [µmol/kg]; ``rho`` (potential density, kg/L) is an
   EXPLICIT caller input — it needs CTD temperature/salinity plus position and
   is a Phase-2B publication input, not decoder state.

CHLA (cookbook + GDAC equation verbatim)::

    CHLA = (FLUORESCENCE_CHLA - DARK_CHLA) * SCALE_CHLA

BBP700 (cookbook eq. 3 + GDAC equation verbatim)::

    BBP700 = 2*pi*khi*((BETA_BACKSCATTERING700 - DARK) * SCALE - BETASW700)

with ``BETASW700`` from Zhang et al. (2009): :func:`beta_sw` is a scalar
transcription of the Coriolis ``betasw_ZHH2009.m`` reference (itself the
Zhang/Hu/He code, depolarization default 0.039 per Farinato & Roswell 1976).

NOT implemented, by design: the ``TEMP_DOXY`` thermistor polynomial
(``T0..T5`` over thermistor millivolts) is optode-firmware-internal — the
telemetry temperature is already converted °C (NKE §7.2.4.2), so that equation
has no telemetry input. Its coefficients are preserved as reference values in
the Phase-2A CSV only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: µmol of O2 per mL at STP (22414 mL/mol): converts ``Cstar`` [mL/L] to
#: [µmol/L]. Physical constant; appears identically in the GDAC equation and
#: the Coriolis reference.
MOLAR_VOLUME_UMOL_PER_ML = 44.614
#: Terms of the Aanderaa foil polynomial (only terms with nonzero ``c`` and
#: nonzero exponents contribute; GDAC floats carry c21..c27 = 0).
N_FOIL_TERMS = 28


@dataclass(frozen=True)
class PhaseCoefs:
    """Calibrated-phase cubic coefficients (``PhaseCoef0..3``)."""

    c0: float
    c1: float
    c2: float
    c3: float


@dataclass(frozen=True)
class FoilCoefs:
    """Aanderaa 28-term foil polynomial: coefficients + T/CalPhase exponents."""

    c: tuple[float, ...]
    m: tuple[int, ...]
    n: tuple[int, ...]

    def __post_init__(self) -> None:
        for name in ("c", "m", "n"):
            if len(getattr(self, name)) != N_FOIL_TERMS:
                raise ValueError(
                    f"foil {name} must have {N_FOIL_TERMS} terms, "
                    f"got {len(getattr(self, name))}"
                )


@dataclass(frozen=True)
class SolubilityConsts:
    """Universal gas-solubility constants of the DOXY chain.

    Values are identical across the GDAC reference floats (2902086, 2902091,
    2902113) and match the Coriolis/Garcia-Gordon/Weiss/Benson-Krause
    literature forms; they are arguments (not module state) so every call
    site stays explicit.
    """

    a: tuple[float, ...]  #: Cstar log-polynomial ``A0..A5`` (6 terms).
    b: tuple[float, ...]  #: salinity-correction ``B0..B3`` (4 terms).
    c0: float  #: salinity-correction ``C0``.
    d: tuple[float, ...]  #: water-vapour ``D0..D3`` (4 terms).
    spreset: float  #: reference salinity inside the vapour factor ``A``.
    pcoef1: float  #: phase pressure compensation (°/1000 dbar).
    pcoef2: float  #: quenching pressure compensation (1/(°C·1000 dbar)).
    pcoef3: float  #: quenching pressure compensation (1/1000 dbar).
    nom_air_press: float  #: nominal air pressure (mbar).
    nom_air_mix: float  #: nominal O2 air mixing ratio.

    def __post_init__(self) -> None:
        if len(self.a) != 6:
            raise ValueError(f"solubility A must have 6 terms, got {len(self.a)}")
        if len(self.b) != 4:
            raise ValueError(f"solubility B must have 4 terms, got {len(self.b)}")
        if len(self.d) != 4:
            raise ValueError(f"solubility D must have 4 terms, got {len(self.d)}")


@dataclass(frozen=True)
class DoxyResult:
    """Every intermediate of the DOXY chain plus the final values."""

    tphase_deg: float
    phase_pcorr_deg: float
    calphase_deg: float
    delta_p: float
    airsat_percent: float
    cstar_ml_l: float
    molar_umol_l: float
    scorr: float
    pcorr: float
    o2_umol_l: float
    doxy_umol_kg: float | None


def tphase(c1_deg: float, c2_deg: float) -> float:
    """Uncalibrated phase difference ``TPHASE = C1 - C2`` (degrees)."""
    return c1_deg - c2_deg


def phase_pcorr(tphase_deg: float, pres_dbar: float, pcoef1: float) -> float:
    """Pressure-compensated phase (cookbook §4.2.2, ``Pcoef1 = 0.1``)."""
    return tphase_deg + pcoef1 * pres_dbar / 1000.0


def calphase(phase_pcorr_deg: float, phase: PhaseCoefs) -> float:
    """Calibrated phase: cubic in the compensated phase (cookbook §4.2.2)."""
    p = phase_pcorr_deg
    return phase.c0 + phase.c1 * p + phase.c2 * p**2 + phase.c3 * p**3


def foil_delta_p(calphase_deg: float, temp_c: float, foil: FoilCoefs) -> float:
    """Foil polynomial ``Σ c[i]*T^m[i]*CalPhase^n[i]`` (cookbook §4.2.2.1)."""
    return sum(
        c * temp_c**m * calphase_deg**n for c, m, n in zip(foil.c, foil.m, foil.n)
    )


def vapour_pressure(temp_c: float) -> float:
    """Saturation vapour pressure [mbar] (Aanderaa form, Coriolis reference)."""
    tk = temp_c + 273.15
    return math.exp(52.57 - 6690.9 / tk - 4.681 * math.log(tk))


def air_saturation(
    delta_p: float, temp_c: float, nom_air_press: float, nom_air_mix: float
) -> float:
    """Air saturation [%] from the foil ``deltaP`` (GDAC equation verbatim)."""
    return (
        delta_p
        * 100.0
        / ((nom_air_press - vapour_pressure(temp_c)) * nom_air_mix)
    )


def ts_ratio(temp_c: float) -> float:
    """Scaled temperature ``Ts = ln((298.15-T)/(273.15+T))`` (Benson-Krause)."""
    return math.log((298.15 - temp_c) / (273.15 + temp_c))


def cstar(temp_c: float, a: tuple[float, ...]) -> float:
    """O2 solubility ``Cstar`` [mL/L] (``ln(Cstar) = Σ A[k]*Ts^k``)."""
    ts = ts_ratio(temp_c)
    return math.exp(sum(coef * ts**k for k, coef in enumerate(a)))


def molar_doxy(cstar_ml_l: float, airsat_percent: float) -> float:
    """Molar concentration [µmol/L] (GDAC equation verbatim)."""
    return cstar_ml_l * MOLAR_VOLUME_UMOL_PER_ML * airsat_percent / 100.0


def p_h2o(temp_c: float, psal: float, d: tuple[float, ...]) -> float:
    """Water vapour partial pressure [mbar] (Weiss form, Coriolis reference)."""
    tk = temp_c + 273.15
    return 1013.25 * math.exp(
        d[0] + d[1] * (100.0 / tk) + d[2] * math.log(tk / 100.0) + d[3] * psal
    )


def salinity_correction(
    temp_c: float,
    psal: float,
    b: tuple[float, ...],
    c0: float,
    d: tuple[float, ...],
    spreset: float,
) -> float:
    """Salinity correction ``Scorr`` (Garcia-Gordon form, GDAC equation)."""
    ts = ts_ratio(temp_c)
    a_factor = (1013.25 - p_h2o(temp_c, spreset, d)) / (
        1013.25 - p_h2o(temp_c, psal, d)
    )
    exponent = (
        psal * (b[0] + b[1] * ts + b[2] * ts**2 + b[3] * ts**3) + c0 * psal**2
    )
    return a_factor * math.exp(exponent)


def pressure_correction(
    temp_c: float, pres_dbar: float, pcoef2: float, pcoef3: float
) -> float:
    """Quenching pressure correction ``Pcorr`` (Uchida form, GDAC equation)."""
    return 1.0 + ((pcoef2 * temp_c) + pcoef3) * pres_dbar / 1000.0


def doxy_umol_kg(o2_umol_l: float, rho_kg_l: float) -> float:
    """Convert [µmol/L] to [µmol/kg] (``DOXY = O2 / rho``).

    ``rho`` is potential density in kg/L from CTD data (a Phase-2B publication
    input); it is an explicit argument precisely so no density model hides
    inside the equation layer.
    """
    return o2_umol_l / rho_kg_l


def doxy_chain(
    c1_deg: float,
    c2_deg: float,
    temp_c: float,
    pres_dbar: float,
    psal: float,
    phase: PhaseCoefs,
    foil: FoilCoefs,
    sol: SolubilityConsts,
    rho_kg_l: float | None = None,
) -> DoxyResult:
    """Full raw→DOXY chain; every intermediate is returned for audit.

    Args:
        c1_deg, c2_deg: optode phases (degrees).
        temp_c: optode temperature (°C).
        pres_dbar: pressure (dbar).
        psal: salinity from the associated CTD (practical salinity).
        phase, foil, sol: explicit coefficient containers (no defaults).
        rho_kg_l: potential density (kg/L), or None to stop at [µmol/L].
    """
    tph = tphase(c1_deg, c2_deg)
    ppc = phase_pcorr(tph, pres_dbar, sol.pcoef1)
    cal = calphase(ppc, phase)
    delta = foil_delta_p(cal, temp_c, foil)
    airsat = air_saturation(delta, temp_c, sol.nom_air_press, sol.nom_air_mix)
    cst = cstar(temp_c, sol.a)
    molar = molar_doxy(cst, airsat)
    scorr = salinity_correction(temp_c, psal, sol.b, sol.c0, sol.d, sol.spreset)
    pcorr = pressure_correction(temp_c, pres_dbar, sol.pcoef2, sol.pcoef3)
    o2 = molar * scorr * pcorr
    return DoxyResult(
        tphase_deg=tph,
        phase_pcorr_deg=ppc,
        calphase_deg=cal,
        delta_p=delta,
        airsat_percent=airsat,
        cstar_ml_l=cst,
        molar_umol_l=molar,
        scorr=scorr,
        pcorr=pcorr,
        o2_umol_l=o2,
        doxy_umol_kg=doxy_umol_kg(o2, rho_kg_l) if rho_kg_l is not None else None,
    )


def chla_ug_l(fluo_counts: float, dark_chla: float, scale_chla: float) -> float:
    """Chlorophyll-a [µg/L] (cookbook + GDAC equation verbatim)."""
    return (fluo_counts - dark_chla) * scale_chla


def _rinw(
    wavelength_nm: float, temp_c: float, psal: float
) -> tuple[float, float]:
    """Seawater refractive index + d(n)/dS (Quan & Fry 1994; Ciddor 1996 air).

    Verbatim scalar transcription of ``RInw`` in ``betasw_ZHH2009.m``.
    """
    lam = wavelength_nm
    n_air = 1.0 + (
        5792105.0 / (238.0185 - 1.0 / (lam / 1e3) ** 2)
        + 167917.0 / (57.362 - 1.0 / (lam / 1e3) ** 2)
    ) / 1e8
    n0 = 1.31405
    n1 = 1.779e-4
    n2 = -1.05e-6
    n3 = 1.6e-8
    n4 = -2.02e-6
    n5 = 15.868
    n6 = 0.01155
    n7 = -0.00423
    n8 = -4382
    n9 = 1.1455e6
    t = temp_c
    nsw = (
        n0
        + (n1 + n2 * t + n3 * t**2) * psal
        + n4 * t**2
        + (n5 + n6 * psal + n7 * t) / lam
        + n8 / lam**2
        + n9 / lam**3
    )
    nsw = nsw * n_air
    dnswds = (n1 + n2 * t + n3 * t**2 + n6 / lam) * n_air
    return nsw, dnswds


def _betat(temp_c: float, psal: float) -> float:
    """Isothermal compressibility [1/Pa] (verbatim from ``betasw_ZHH2009.m``)."""
    t = temp_c
    kw = (
        19652.21
        + 148.4206 * t
        - 2.327105 * t**2
        + 1.360477e-2 * t**3
        - 5.155288e-5 * t**4
    )
    a0 = 54.6746 - 0.603459 * t + 1.09987e-2 * t**2 - 6.167e-5 * t**3
    b0 = 7.944e-2 + 1.6483e-2 * t - 5.3009e-4 * t**2
    ks = kw + a0 * psal + b0 * psal**1.5
    return 1.0 / ks * 1e-5


def _rhou_sw(temp_c: float, psal: float) -> float:
    """Seawater density [kg/m³] (UNESCO 1981; verbatim transcription)."""
    t = temp_c
    a0 = 8.24493e-1
    a1 = -4.0899e-3
    a2 = 7.6438e-5
    a3 = -8.2467e-7
    a4 = 5.3875e-9
    a5 = -5.72466e-3
    a6 = 1.0227e-4
    a7 = -1.6546e-6
    a8 = 4.8314e-4
    b0 = 999.842594
    b1 = 6.793952e-2
    b2 = -9.09529e-3
    b3 = 1.001685e-4
    b4 = -1.120083e-6
    b5 = 6.536332e-9
    density_w = b0 + b1 * t + b2 * t**2 + b3 * t**3 + b4 * t**4 + b5 * t**5
    return density_w + (
        (a0 + a1 * t + a2 * t**2 + a3 * t**3 + a4 * t**4) * psal
        + (a5 + a6 * t + a7 * t**2) * psal**1.5
        + a8 * psal**2
    )


def _dlnasw_ds(temp_c: float, psal: float) -> float:
    """d(ln water activity)/dS (Millero & Leung 1976 fit; verbatim)."""
    t = temp_c
    return (
        (-5.58651e-4 + 2.40452e-7 * t - 3.12165e-9 * t**2 + 2.40808e-11 * t**3)
        + 1.5
        * (1.79613e-5 - 9.9422e-8 * t + 2.08919e-9 * t**2 - 1.39872e-11 * t**3)
        * psal**0.5
        + 2 * (-2.31065e-6 - 1.37674e-9 * t - 1.93316e-11 * t**2) * psal
    )


def _pmh(n_wat: float) -> float:
    """Density derivative of refractive index, PMH model (verbatim)."""
    n_wat2 = n_wat**2
    return (n_wat2 - 1) * (
        1 + 2 / 3 * (n_wat2 + 2) * (n_wat / 3 - 1 / 3 / n_wat) ** 2
    )


def beta_sw(
    temp_c: float,
    psal: float,
    wavelength_nm: float,
    theta_deg: float,
    delta: float,
) -> float:
    """Pure-seawater volume scattering function [m⁻¹sr⁻¹] (Zhang et al. 2009).

    Scalar transcription of the Coriolis ``betasw_ZHH2009.m`` reference (the
    Zhang/Hu/He code). All optical parameters are explicit arguments: the
    INCOIS reference floats use 700 nm / 142° / 0.039 (meta.nc
    ``PREDEPLOYMENT_CALIB`` + cookbook Table 1 / annex), but nothing here
    assumes them.
    """
    na = 6.0221417930e23
    kbz = 1.3806503e-23
    tk = temp_c + 273.15
    m0 = 18e-3
    lam_m = wavelength_nm * 1e-9
    rad = theta_deg * math.pi / 180.0
    nsw, dnds = _rinw(wavelength_nm, temp_c, psal)
    isocomp = _betat(temp_c, psal)
    density_sw = _rhou_sw(temp_c, psal)
    dlnawds = _dlnasw_ds(temp_c, psal)
    dfri = _pmh(nsw)
    beta_df = (
        math.pi**2
        / 2.0
        * lam_m**-4
        * kbz
        * tk
        * isocomp
        * dfri**2
        * (6 + 6 * delta)
        / (6 - 7 * delta)
    )
    flu_con = psal * m0 * dnds**2 / density_sw / (-dlnawds) / na
    beta_cf = (
        2 * math.pi**2 * lam_m**-4 * nsw**2 * flu_con * (6 + 6 * delta) / (6 - 7 * delta)
    )
    beta90sw = beta_df + beta_cf
    return beta90sw * (1 + (math.cos(rad)) ** 2 * (1 - delta) / (1 + delta))


def bbp700_m1(
    beta_counts: float,
    temp_c: float,
    psal: float,
    dark: float,
    scale: float,
    khi: float,
    wavelength_nm: float,
    theta_deg: float,
    delta: float,
) -> float:
    """Particulate backscattering [m⁻¹] (cookbook eq. 3 + GDAC equation)."""
    beta = (beta_counts - dark) * scale
    betasw = beta_sw(temp_c, psal, wavelength_nm, theta_deg, delta)
    return 2 * math.pi * khi * (beta - betasw)


__all__ = [
    "MOLAR_VOLUME_UMOL_PER_ML",
    "N_FOIL_TERMS",
    "DoxyResult",
    "FoilCoefs",
    "PhaseCoefs",
    "SolubilityConsts",
    "air_saturation",
    "bbp700_m1",
    "beta_sw",
    "calphase",
    "chla_ug_l",
    "cstar",
    "doxy_chain",
    "doxy_umol_kg",
    "foil_delta_p",
    "molar_doxy",
    "p_h2o",
    "phase_pcorr",
    "pressure_correction",
    "salinity_correction",
    "tphase",
    "ts_ratio",
    "vapour_pressure",
]
