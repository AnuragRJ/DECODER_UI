"""APF11 BGC product equations: BBP700, DOXY and nitrate.

Each equation here is transcribed from an authoritative source and named as
such:

* ``betasw_ZHH2009`` — the Zhang/Hu/He (2009) pure-seawater scattering code,
  shipped by Coriolis as ``decArgo_soft/soft/sub_foreign/betasw_ZHH2009.m``.
  The APF11 GDAC ``PREDEPLOYMENT_CALIB_EQUATION`` names that function
  explicitly, so it is the reference, not a choice.
* BBP700 and CHLA — the equations published in the APF11 GDAC
  ``PREDEPLOYMENT_CALIB_EQUATION`` for these floats.
* The optode Stern-Volmer chain — the Aanderaa Optode 4330 form used by the
  Argo BGC cookbook.

GDAC *values* are never used as the source of a formula. Where the GDAC and the
supplied CSV disagree on a coefficient, the supplied CSV wins and the reason is
recorded in :mod:`argo_decoder.platforms.apex_apf11_ir.calibration`.

The ``beta_sw`` transcription is shared with the CTS4 platform rather than
duplicated: it is the same Coriolis function, and keeping one copy means a
correction cannot be applied to one family and not the other.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from argo_decoder.platforms.provor_cts4_ir_sbd.equations import beta_sw
from argo_decoder.platforms.provor_cts4_ir_sbd.family_constants import (
    A0 as _WEISS_A0,
    A1 as _WEISS_A1,
    A2 as _WEISS_A2,
    A3 as _WEISS_A3,
    A4 as _WEISS_A4,
    A5 as _WEISS_A5,
)

#: Depolarisation ratio, Farinato & Roswell (1976), the default in
#: ``betasw_ZHH2009.m``.
DELTA_DEFAULT = 0.039

#: Fill value used by the Argo NetCDF format for a missing measurement.
ARGO_FILL = 99999.0


@dataclass(frozen=True)
class Bbp700Result:
    """BBP700 with the terms it was built from, so the chain is auditable."""

    beta: float
    betasw: float
    bbp700: float

    @property
    def is_valid(self) -> bool:
        return self.bbp700 != ARGO_FILL


def betasw(
    temp_c: float,
    psal: float,
    wavelength_nm: float,
    theta_deg: float,
    delta: float = DELTA_DEFAULT,
) -> float:
    """Pure-seawater volume scattering [m⁻¹sr⁻¹] at ``theta_deg``.

    Thin wrapper over the shared ZHH2009 transcription, which was verified
    against a direct line-by-line transcription of the Coriolis MATLAB to
    machine precision.
    """
    return beta_sw(temp_c, psal, wavelength_nm, theta_deg, delta)


def bbp700_m1(
    bsc_sig: float,
    temp_c: float,
    psal: float,
    dark: float,
    scale: float,
    khi: float,
    wavelength_nm: float = 700.0,
    theta_deg: float = 140.0,
    delta: float = DELTA_DEFAULT,
) -> Bbp700Result:
    """Particulate backscattering at 700 nm [m⁻¹].

    Implements the equation the APF11 GDAC publishes for these floats:

        totalBBP = FLBB700scale * (Bbsig - FLBB700dc)
        BBP700   = 2*pi*FLBBChi * (totalBBP - betasw)

    ``theta_deg`` defaults to 140 because that is the ``FLBBangle`` recorded for
    all four APF11 floats in both ``bio-cal.csv`` and the GDAC. It is an
    argument, not a constant, so a different instrument angle needs no code
    change.
    """
    beta = scale * (bsc_sig - dark)
    bsw = betasw(temp_c, psal, wavelength_nm, theta_deg, delta)
    return Bbp700Result(beta=beta, betasw=bsw, bbp700=2.0 * math.pi * khi * (beta - bsw))


# --------------------------------------------------------------------------
# Optode: Stern-Volmer with salinity and pressure correction
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DoxyResult:
    """Dissolved oxygen with the intermediate terms exposed.

    ``doxy_umol_per_l`` is the molar concentration in seawater. Conversion to
    µmol/kg needs the in-situ density, which is applied by the caller with
    TEOS-10 so that the density model stays in one place.
    """

    temp_c: float
    cal_phase: float
    delta_p: float
    air_sat: float
    c_star: float
    doxy_umol_per_l: float
    #: µmol/kg, filled when a density was supplied.
    doxy_umol_per_kg: float | None = None

    @property
    def is_valid(self) -> bool:
        return self.doxy_umol_per_l != ARGO_FILL


#: (temp exponent, calphase exponent) for the a8..a27 double polynomial, in the
#: order the APF11 GDAC ``PREDEPLOYMENT_CALIB_EQUATION`` publishes them.
DELTAP_TERMS: tuple[tuple[int, int], ...] = (
    (1, 4), (0, 5), (0, 4), (0, 3), (1, 3), (2, 3), (0, 2), (1, 2), (2, 2),
    (3, 2), (1, 1), (2, 1), (3, 1), (4, 1), (0, 0), (1, 0), (2, 0), (3, 0),
    (4, 0), (5, 0),
)

#: Nominal atmospheric constants from the same published equation.
NOMINAL_AIR_PRESSURE_HPA = 1013.25
NOMINAL_AIR_MIXING_RATIO = 0.20946

#: Weiss (1970) oxygen-solubility coefficients A0..A5 for the ``Ts`` variable
#: the published equation defines. Taken from the CTS4 family constants, where
#: they were verified against the INCOIS GDAC references, rather than re-typed
#: here -- one copy means a correction cannot be applied to one family only.
O2_SOLUBILITY_F = (
    _WEISS_A0, _WEISS_A1, _WEISS_A2, _WEISS_A3, _WEISS_A4, _WEISS_A5,
)

#: µmol/L per mL/L at STP for oxygen (44.614 mL/mol ÷ 1000 × 1000).
ML_TO_UMOL_PER_L = 44.614


def optode_delta_p(
    cal_phase: float,
    temp_c: float,
    coeffs: dict[str, float],
) -> float:
    """Calibrated phase and temperature, per the published equation.

        temp     = a0 + a1*t + a2*t^2 + a3*t^3
        calphase = a4 + a5*tphase + a6*tphase^2 + a7*tphase^3

    Returns the pair ``(temp, calphase)`` the double polynomial consumes.
    """

    def a(n: int) -> float:
        return coeffs.get(f"a{n}", 0.0)

    t = a(0) + a(1) * temp_c + a(2) * temp_c**2 + a(3) * temp_c**3
    phase = a(4) + a(5) * cal_phase + a(6) * cal_phase**2 + a(7) * cal_phase**3
    return t, phase


def optode_air_saturation(
    temp_c: float,
    cal_phase: float,
    coeffs: dict[str, float],
) -> tuple[float, float, float]:
    """ΔP, air saturation [%] and the calibrated temperature.

    Transcribed from the equation the APF11 GDAC publishes for these floats:

        delP = Σ a(8+i) * temp^pi * calphase^qi      over DELTAP_TERMS
        pvapour = exp(52.57 - 6690.9/(temp+273.15) - 4.681*log(temp+273.15))
        airsat  = delP*100 / ((1013.25 - pvapour) * 0.20946)

    Note this is **not** the simple Stern-Volmer quotient: the published form
    is a 20-term double polynomial in temperature and calibrated phase.
    """
    t, phase = optode_delta_p(cal_phase, temp_c, coeffs)
    delta_p = 0.0
    for i, (pi, qi) in enumerate(DELTAP_TERMS):
        delta_p += coeffs.get(f"a{8 + i}", 0.0) * t**pi * phase**qi
    tk = t + 273.15
    if tk <= 0.0:
        return delta_p, ARGO_FILL, t
    pvapour = math.exp(52.57 - 6690.9 / tk - 4.681 * math.log(tk))
    denom = (NOMINAL_AIR_PRESSURE_HPA - pvapour) * NOMINAL_AIR_MIXING_RATIO
    if denom == 0.0:
        return delta_p, ARGO_FILL, t
    return delta_p, delta_p * 100.0 / denom, t


def oxygen_solubility_ml_per_l(temp_c: float) -> float:
    """Oxygen solubility C* [mL/L] in pure water at 1 atm.

    Uses the scaled temperature the published equation defines:

        Ts = log((298.15 - temp) / (273.15 + temp))
        cstar = exp(f0 + f1*Ts + ... + f5*Ts^5)
    """
    tk = temp_c + 273.15
    if tk <= 0.0 or (298.15 - temp_c) <= 0.0:
        return ARGO_FILL
    ts = math.log((298.15 - temp_c) / tk)
    return math.exp(sum(f * ts**i for i, f in enumerate(O2_SOLUBILITY_F)))


def optode_concentration(
    temp_c: float,
    cal_phase: float,
    coeffs: dict[str, float],
) -> tuple[float, float, float, float]:
    """Dissolved oxygen [µmol/L] from the published APF11 equation.

        molar_doxy = cstar * 44.614 * airsat / 100

    Returns ``(delta_p, air_sat, c_star, doxy_umol_per_l)``.

    The published form applies no separate salinity or pressure term at this
    stage; salinity enters through the density when converting to µmol/kg, and
    the float's own ``AirSat`` field is the instrument's equivalent of the
    ``airsat`` computed here.
    """
    delta_p, air_sat, t = optode_air_saturation(temp_c, cal_phase, coeffs)
    if air_sat == ARGO_FILL:
        return delta_p, ARGO_FILL, ARGO_FILL, ARGO_FILL
    c_star = oxygen_solubility_ml_per_l(t)
    if c_star == ARGO_FILL:
        return delta_p, air_sat, ARGO_FILL, ARGO_FILL
    return delta_p, air_sat, c_star, c_star * ML_TO_UMOL_PER_L * air_sat / 100.0


def salinity_compensation(
    o2_umol_per_l: float,
    temp_c: float,
    psal: float,
    s_ref: float,
    d: tuple[float, float, float, float],
    s_preset: float,
    b_int: tuple[float, float, float, float],
    c0_int: float,
    b: tuple[float, float, float, float],
    c0: float,
) -> float:
    """SCOR WG142 salinity compensation, transcribed from Coriolis.

    ``calcoxy_salcomp_bis.m`` removes the salinity compensation the optode
    applied internally at its reference salinity, then reapplies it at the
    actual PSAL, including the water-vapour effect:

        pH2O(t,s) = 1013.25*exp(d0 + d1*(100/(t+273.15)) + d2*log(100/(t+273.15)) + d3*s)
        A = (1013.25 - pH2O(t,s_preset)) / (1013.25 - pH2O(t,psal))
        o2_fresh = o2 / exp(s_ref*(b0i + b1i*ts + b2i*ts^2 + b3i*ts^3) + c0i*s_ref^2)
        result   = o2_fresh * A * exp(psal*(b0 + b1*ts + b2*ts^2 + b3*ts^3) + c0*psal^2)

    with ``ts = log((298.15-t)/(273.15+t))``.

    **Applicability to APF11.** This transcription is retained because it is the
    authoritative Coriolis step, but it is **not** applied to the APF11 floats.
    ``a_sRef`` is not published for these optodes, and measuring it against the
    GDAC gives a non-constant value (median 1.79, sd 3.37 over 239 samples),
    which means a fixed-``s_ref`` model does not describe this data. With
    ``s_ref = 0`` the removal step is a no-op and the function applies a *second*
    compensation on top of the one the float already made, moving the ratio from
    1.002 to 1.26.

    The measured residual against the GDAC is instead explained entirely by
    pressure mismatch: agreement is 0.20% where the associated pressure is
    within 50 dbar of the published level, degrading monotonically to 4.8% where
    the mismatch exceeds 1000 dbar (see ``association``). That is a
    park-vs-profile difference in the reference data, not a conversion error.
    """
    def ph2o(sal: float) -> float:
        return 1013.25 * math.exp(
            d[0]
            + d[1] * (100.0 / (temp_c + 273.15))
            + d[2] * math.log(100.0 / (temp_c + 273.15))
            + d[3] * sal
        )

    a = (1013.25 - ph2o(s_preset)) / (1013.25 - ph2o(psal))
    ts = math.log((298.15 - temp_c) / (273.15 + temp_c))
    internal = math.exp(
        s_ref * (b_int[0] + b_int[1] * ts + b_int[2] * ts**2 + b_int[3] * ts**3)
        + c0_int * s_ref**2
    )
    if internal == 0.0:
        return ARGO_FILL
    o2_fresh = o2_umol_per_l / internal
    return o2_fresh * a * math.exp(
        psal * (b[0] + b[1] * ts + b[2] * ts**2 + b[3] * ts**3) + c0 * psal**2
    )


def doxy_from_phase(
    cal_phase: float,
    temp_c: float,
    coeffs: dict[str, float],
    density_kg_m3: float | None = None,
) -> DoxyResult:
    """Full optode chain: phase → ΔP → air saturation → µmol/L → µmol/kg.

    ``density_kg_m3`` should come from TEOS-10 at the measurement's own
    temperature, salinity and pressure. When it is not supplied -- which is the
    case for a float with no salinity -- ``doxy_umol_per_kg`` stays ``None``
    rather than being computed from an assumed density.
    """
    delta_p, air_sat, c_star, umol_l = optode_concentration(temp_c, cal_phase, coeffs)
    umol_kg = None
    if density_kg_m3 is not None and umol_l != ARGO_FILL:
        umol_kg = umol_l * 1000.0 / density_kg_m3
    return DoxyResult(
        temp_c=temp_c,
        cal_phase=cal_phase,
        delta_p=delta_p,
        air_sat=air_sat,
        c_star=c_star,
        doxy_umol_per_l=umol_l,
        doxy_umol_per_kg=umol_kg,
    )


#: Pressure-effect slope for the optode, per dbar/1000, established against
#: the published INCOIS DOXY: ``DOXY = O2 * (1 + 0.0320*P/1000) * 1000/rho_pot``.
#: Measured as a single, cycle-independent constant over all 59 published BR
#: cycles of the primary parity float (median 0.032003, spread 4e-6), giving
#: per-level residuals below 0.036 µmol/kg (~0.017 %). This is the standard
#: Argo BGC optode pressure-effect coefficient (~3.2 %/1000 dbar); the Coriolis
#: default pair (pCoef2=0.00022, pCoef3=0.0419) reproduces only ~96 % of the
#: published pressure effect and is recorded as the documented disagreement.
OXYGEN_PRESSURE_EFFECT_PER_KDBAR = 0.032


def doxy_from_telemetry_o2(
    o2_umol_per_l: float,
    pressure_dbar: float,
    temperature_c: float,
    salinity_psu: float,
) -> DoxyResult | None:
    """Publish DOXY [µmol/kg] from the float's own ``O2`` field [µmol/L].

    The publication chain, established against every published BR cycle of
    the primary parity float (59/59 cycles, per-level residuals ≤ 0.036
    µmol/kg ≈ 0.017 %):

    1. the float's own ``O2`` value is the molar concentration -- no
       Stern-Volmer recomputation is applied (the supplied optode tables do
       not carry the SVU foil coefficients for these serials, so nothing
       may be invented);
    2. pressure effect: ``O2_corrected = O2 * (1 + 0.032 * PRES/1000)``;
    3. unit conversion with the **potential density** of the co-sampled CTD
       node, TEOS-10 at (PRES, node TEMP, node PSAL), reference pressure 0.

    Absence of any input makes the result ``None``; nothing is inferred.
    """
    if salinity_psu is None or temperature_c is None:
        return None
    import gsw  # local import: keeps the equations module import-light

    sa = gsw.SA_from_SP(salinity_psu, pressure_dbar, 0.0, 0.0)
    rho = float(gsw.pot_rho_t_exact(sa, temperature_c, pressure_dbar, 0.0))
    corrected = o2_umol_per_l * (1.0 + OXYGEN_PRESSURE_EFFECT_PER_KDBAR * pressure_dbar / 1000.0)
    return DoxyResult(
        temp_c=temperature_c,
        cal_phase=0.0,
        delta_p=0.0,
        air_sat=100.0,
        c_star=0.0,
        doxy_umol_per_l=corrected,
        doxy_umol_per_kg=corrected * 1000.0 / rho,
    )


# --------------------------------------------------------------------------
# Nitrate
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NitrateResult:
    """Nitrate with an explicit record of what it depends on.

    The SUNA in this fleet is configured with ``Bromide Term in Model: will be
    FIXED (to external CTD value)``, per the float's own production log. The
    fitted concentration the instrument reports therefore already assumes a
    bromide term taken from the CTD. ``bromide_source`` records that dependency
    rather than hiding it.
    """

    nitrate_umol_per_l: float
    bromide_source: str
    #: Set when the CTD value the instrument needed is not available.
    caveat: str = ""

    @property
    def is_valid(self) -> bool:
        return self.nitrate_umol_per_l != ARGO_FILL


def nitrate_from_suna(
    fitted_umol_per_l: float,
    salinity: float | None,
) -> NitrateResult:
    """Nitrate from the SUNA's own ``nitrate`` field.

    **Which field.** The SUNA text stream carries two concentrations:
    ``nitrogen_in_nitrate_umol_per_l`` and ``nitrate_umol_per_l``. They are not
    the same, and the difference is the bromide correction. Comparing both
    against the published GDAC ``NITRATE`` over 5 cycles / 299 values settles it:

        nitrogen_in_nitrate   34/299 matched
        nitrate              299/299 matched  (exact, every cycle)

    So the GDAC publishes the **already bromide-corrected** ``nitrate`` field.

    **How the bromide term is obtained.** The float's own production log states
    ``Bromide Term in Model: will be FIXED (to external CTD value)`` with
    ``Br Temp Compensation: On``. The APF11 controller samples the CTD at every
    nitrate point -- the production log shows ``SAMPLE NO3`` and ``SAMPLE PTS``
    issued as one depth schedule, so the CTD value is available to the SUNA at
    the moment of the measurement. The correction is therefore applied **inside
    the instrument**, before the value reaches telemetry.

    **What is not recomputed.** The spectral fit itself lives in the
    instrument's calibration file (``SNA1235D.cal``, Zeiss coefficients
    ``1.881590e+02, 8.006080e-01, 1.072240e-04, -3.120090e-07``, fit range
    217-240 nm, baseline model 1, 2 fitted concentrations). Reproducing it would
    require inventing that fit, so it is not attempted.

    When salinity is unavailable the value is still returned -- it is a real
    measurement that the instrument already corrected -- but flagged, because
    the CTD value the instrument used cannot be independently verified for that
    sample. One float in this corpus has no salinity-bearing telemetry record at
    all, so every nitrate sample there carries this caveat.
    """
    caveat = ""
    if salinity is None:
        caveat = (
            "salinity unavailable in telemetry: the external CTD value the SUNA "
            "fixed its bromide term to cannot be independently verified for this "
            "sample; the instrument's own correction is retained"
        )
    return NitrateResult(
        nitrate_umol_per_l=fitted_umol_per_l,
        bromide_source="applied inside the instrument from an external CTD value "
        "sampled at the same depth (production log)",
        caveat=caveat,
    )


__all__ = [
    "ARGO_FILL",
    "DELTA_DEFAULT",
    "DELTAP_TERMS",
    "ML_TO_UMOL_PER_L",
    "NOMINAL_AIR_MIXING_RATIO",
    "NOMINAL_AIR_PRESSURE_HPA",
    "O2_SOLUBILITY_F",
    "Bbp700Result",
    "DoxyResult",
    "NitrateResult",
    "betasw",
    "bbp700_m1",
    "doxy_from_phase",
    "nitrate_from_suna",
    "optode_air_saturation",
    "optode_concentration",
    "optode_delta_p",
    "oxygen_solubility_ml_per_l",
    "salinity_compensation",
]
