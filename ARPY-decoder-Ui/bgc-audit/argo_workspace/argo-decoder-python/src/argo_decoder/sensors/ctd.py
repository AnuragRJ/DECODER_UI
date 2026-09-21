"""CTD (Conductivity-Temperature-Depth) sensor decoding for NKE Provor/Arvor
Iridium SBD (CTS4 generation, decoder ids 201-232).

For this firmware generation the on-board controller already performs the
Sea-Bird polynomial and reports **scaled integers** in the SBD payload. The
ground-segment conversion is therefore a simple linear scaling on the 16-bit
raw counts; no calibration coefficients are required for the core P/T/S
conversion (they are baked into the float firmware at deployment time).

Conversion rules (from MATLAB, e.g.
`sensor_2_value_for_pressure_201_203_215_216_218_221_228_229_230.m`):

* Pressure: ``(twos_complement_16(pres_counts) + 30000) / 10``   [dbar]
* Temperature: ``twos_complement_16(temp_counts) / 1000``          [degC, ITS-90]
* Salinity: ``(sal_counts + 10000) / 1000``                       [PSU, unsigned]

A count value of ``COUNT_FILL = 99999`` is mapped to the Argo fill value
``9999.9`` dbar / ``99.999`` degC / ``99.999`` psu. Because pressure and
temperature are two's-complement signed 16-bit (max 32767), 99999 can never
appear in valid data and is therefore an unambiguous sentinel.

Calibration coefficients are still carried in the ``CtdCalibration``
dataclass for future use (RTQC adjustments, delayed-mode reprocessing,
CTS5/Rudics floats that do send raw frequencies) but they are not
exercised by the CTS4 Iridium SBD fast-path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import xarray as xr

# ---------------------------------------------------------------------------
# Constants (from MATLAB init_default_values.m)
# ---------------------------------------------------------------------------

COUNT_FILL = 99999
"""Sentinel count indicating missing / invalid sample."""

PRES_FILL = 9999.9
TEMP_FILL = 99.999
PSAL_FILL = 99.999

# ---------------------------------------------------------------------------
# Calibration structure
# ---------------------------------------------------------------------------


@dataclass
class CtdCalibration:
    """Per-float CTD calibration coefficients.

    For CTS4 Iridium SBD floats these are not used in the fast conversion
    path (the float applies calib on-board); the fields are retained so
    delayed-mode reprocessing and future CTS5/Rudics plugins (which do
    receive raw frequency counts) can attach calibration without schema
    changes.
    """

    # Pressure sensor
    p_a0: float = 0.0
    p_a1: float = 0.0
    p_a2: float = 0.0
    p_b0: float = 0.0
    p_b1: float = 0.0
    p_c0: float = 0.0
    p_c1: float = 0.0
    p_c2: float = 0.0
    p_d0: float = 0.0
    p_d1: float = 0.0
    p_t1: float = 0.0
    p_t2: float = 0.0
    p_t3: float = 0.0
    p_t4: float = 0.0
    p_t5: float = 0.0
    p_offset: float = 0.0

    # Temperature sensor
    t_a0: float = 0.0
    t_a1: float = 0.0
    t_a2: float = 0.0
    t_a3: float = 0.0
    t_a4: float = 0.0
    t_a5: float = 0.0
    t_a6: float = 0.0
    t_a7: float = 0.0

    # Conductivity sensor
    c_g: float = 0.0
    c_h: float = 0.0
    c_i: float = 0.0
    c_j: float = 0.0
    c_cpcor: float = 0.0
    c_ctcor: float = 0.0
    c_cslope: float = 0.0

    # Sensor metadata
    calibration_date: str = ""
    serial_number: str = ""


@dataclass
class CtdProfile:
    """Decoded CTD profile - lists of samples in acquisition order.

    ``conductivity_S_m`` is populated on demand (see
    :func:`derived.cndc.conductivity_from_sp`) and is ``None`` until
    :meth:`compute_conductivity` is called.  Keeping it optional lets the
    fast decoding path skip the gsw dependency when only P/T/S are
    needed.
    """

    pressure_dbar: list[float] = field(default_factory=list)
    temperature_deg_c: list[float] = field(default_factory=list)
    salinity_psu: list[float] = field(default_factory=list)
    conductivity_s_m: list[float] | None = None

    def compute_conductivity(self) -> list[float]:
        """Populate ``conductivity_s_m`` from P/T/S via TEOS-10.

        Idempotent: if conductivity has already been computed the existing
        list is returned unchanged.
        """
        if self.conductivity_s_m is not None:
            return self.conductivity_s_m
        from argo_decoder.derived.cndc import conductivity_from_sp

        c = conductivity_from_sp(
            np.asarray(self.salinity_psu, dtype=np.float64),
            np.asarray(self.temperature_deg_c, dtype=np.float64),
            np.asarray(self.pressure_dbar, dtype=np.float64),
        )
        # Convert NaNs back to Argo fill so downstream writers that don't
        # understand NaN can still emit fill values.  The xarray variable
        # itself uses NaN as _FillValue.
        out: list[float] = []
        for v in c.tolist():
            out.append(99.9999 if (v is None or not np.isfinite(v)) else float(v))
        self.conductivity_s_m = out
        return out


# ---------------------------------------------------------------------------
# Two's complement helper
# ---------------------------------------------------------------------------


def _twos_complement_16(value: int) -> int:
    """Interpret an unsigned 16-bit integer as a signed 16-bit integer."""
    value = int(value) & 0xFFFF
    if value >= 0x8000:
        value -= 0x10000
    return value


# ---------------------------------------------------------------------------
# Scalar converters
# ---------------------------------------------------------------------------


def decode_pres(count: int) -> float:
    """Convert one pressure count to dbar (CTS4 Iridium SBD linear scaling)."""
    if count == COUNT_FILL:
        return PRES_FILL
    return (_twos_complement_16(count) + 30000) / 10.0


def decode_temp(count: int) -> float:
    """Convert one temperature count to degC (CTS4 Iridium SBD linear scaling)."""
    if count == COUNT_FILL:
        return TEMP_FILL
    return _twos_complement_16(count) / 1000.0


def decode_psal(count: int) -> float:
    """Convert one salinity count to psu (CTS4 Iridium SBD linear scaling)."""
    if count == COUNT_FILL:
        return PSAL_FILL
    return (int(count) + 10000) / 1000.0


# ---------------------------------------------------------------------------
# Vector conversion -> CtdProfile
# ---------------------------------------------------------------------------


def convert_counts(
    *,
    pres_counts: list[int],
    temp_counts: list[int],
    sal_counts: list[int] | None = None,
    cal: CtdCalibration | None = None,
) -> CtdProfile:
    """Convert arrays of raw CTD counts to a :class:`CtdProfile`.

    ``cal`` is accepted for API symmetry but is not consulted by the
    CTS4 fast path (see module docstring).  ``sal_counts`` may be
    ``None`` for P/T-only packets; salinity values are then emitted as
    fill.
    """
    del cal  # unused in CTS4 linear fast-path
    n = min(len(pres_counts), len(temp_counts))
    if sal_counts is None:
        sal_counts = [COUNT_FILL] * n
    else:
        # Pad/truncate salinity to the same length
        if len(sal_counts) < n:
            sal_counts = list(sal_counts) + [COUNT_FILL] * (n - len(sal_counts))
    prof = CtdProfile()
    for i in range(n):
        prof.pressure_dbar.append(decode_pres(pres_counts[i]))
        prof.temperature_deg_c.append(decode_temp(temp_counts[i]))
        prof.salinity_psu.append(decode_psal(sal_counts[i]))
    return prof


# ---------------------------------------------------------------------------
# xarray variable construction
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Real-time QC provenance for ADMT HISTORY QCP$ / QCF$ records
# ---------------------------------------------------------------------------

# Argo reference table 11 numbers of the tests this decoder executes.
# TEST001/002/003 are the profile-scalar tests (platform identification,
# impossible date, impossible location) run in add_profile_scalars;
# TEST006/008/009/011/013 are the non-density tests; TEST014 is the
# density inversion, which only runs when a position is available.
_SCALAR_TESTS = (1, 2, 3)
_NON_DENSITY_TESTS = (6, 8, 9, 11, 12, 13)
_DENSITY_TEST = 14
# TEST019 only runs when CONFIG_ProfilePressure_dbar is known, so it is
# reported as performed conditionally rather than unconditionally.
_DEEPEST_PRESSURE_TEST = 19


def _tests_performed(density_test_run: bool, deepest_test_run: bool = False) -> set[int]:
    performed = {*_SCALAR_TESTS, *_NON_DENSITY_TESTS}
    if density_test_run:
        performed.add(_DENSITY_TEST)
    if deepest_test_run:
        performed.add(_DEEPEST_PRESSURE_TEST)
    return performed


def _tests_failed(
    density_test_run: bool,
    qc_arrays: tuple[np.ndarray, ...],
    non_density_failures: set[int] | None = None,
) -> set[int]:
    """Return the numbers of tests that flagged at least one level.

    Only tests whose own outcome flagged data are reported. When the
    per-test breakdown is unavailable the set is empty rather than
    guessed, because HISTORY_QCTEST must not assert an untrue failure.
    """
    failed: set[int] = set(non_density_failures or ())
    # Density inversion is the only test that can raise TEMP/PSAL flags
    # after the non-density pass; attribute a failure to it only when the
    # non-density tests did not already explain the flagged levels.
    unexplained = not failed and any(
        int(np.max(arr, initial=1)) > 1 for arr in qc_arrays if arr.size
    )
    if density_test_run and unexplained:
        failed.add(_DENSITY_TEST)
    return failed


def _qctest_hex(tests: set[int]) -> str:
    """Encode Argo test numbers as the ADMT HISTORY_QCTEST hex mask.

    Test N occupies bit N, matching the references (``D7B7E`` decodes to
    tests 1-6, 8, 9, 11-14, 16, 18, 19).
    """
    mask = 0
    for number in tests:
        mask |= 1 << int(number)
    return format(mask, "X") if mask else "0"


def profile_to_dataset(
    prof: CtdProfile,
    *,
    wmo: int,
    cycle: int,
    platform_type: str,
    decoder_version: str,
    decoder_id: int,
    latitude: float | None = None,
    longitude: float | None = None,
    profile_pressure_dbar: float | None = None,
    extra_attrs: dict[str, object] | None = None,
) -> xr.Dataset:
    """Build an xarray Dataset with PRES/TEMP/PSAL (+ ``*_QC``) as 1-D N_LEVELS arrays.

    Fill values are encoded with the standard Argo QC fill sentinels
    (``9999.9`` / ``99.999``) so they round-trip through the NetCDF
    writer without special handling. Pressure is sorted ascending
    (shallowest bin first) matching the Argo mono-profile convention.
    ``<PARAM>_QC`` variables are populated by the RTQC modules in
    Phase 3.

    Electrical conductivity (``CNDC``, S/m) is derived from P/T/S via
    TEOS-10 (``gsw.C_from_SP``), matching the MATLAB real-time path in
    :file:`compute_rt_adjusted_param.m`.  Fill-value samples propagate
    as NaN and are encoded with the Argo CNDC fill (``99.9999``).

    Density inversion (TEST014) additionally requires a profile
    location (``latitude``/``longitude``) to compute Absolute Salinity.
    When either is ``None`` the test is skipped rather than producing
    bogus flags.
    """
    from argo_decoder.derived.cndc import CNDC_FILL, conductivity_from_sp

    n = len(prof.pressure_dbar)
    order = np.argsort(prof.pressure_dbar) if n > 0 else np.array([], dtype=int)
    p = np.array([prof.pressure_dbar[i] for i in order], dtype=np.float64)
    t = np.array([prof.temperature_deg_c[i] for i in order], dtype=np.float64)
    s = np.array([prof.salinity_psu[i] for i in order], dtype=np.float64)

    # Derive conductivity.  Guard against environments without gsw
    # (e.g. minimal CI) by emitting NaN-filled CNDC.
    try:
        c = conductivity_from_sp(s, t, p)
    except Exception as exc:  # pragma: no cover - defensive
        import warnings

        warnings.warn(f"CNDC computation failed, emitting fill: {exc}", stacklevel=2)
        c = np.full(n, np.nan, dtype=np.float64)

    # Run non-density RTQC (TEST006/008/009/011/012/013/019) so the
    # initial QC flags reflect basic physical-plausibility checks.
    # TEST019 needs CONFIG_ProfilePressure_dbar; when the caller does not
    # supply it the test reports all-good rather than guessing a limit.
    from argo_decoder.rtqc import run_non_density_tests

    non_density_failures: set[int] = set()
    qc_map = run_non_density_tests(
        pres=p,
        temp=t,
        psal=s,
        cndc=c,
        failed_tests=non_density_failures,
        profile_pressure_dbar=profile_pressure_dbar,
    )
    qc_pres = qc_map["PRES"].astype(np.int8)
    qc_temp = qc_map["TEMP"].astype(np.int8)
    qc_psal = qc_map["PSAL"].astype(np.int8)
    qc_cndc = qc_map["CNDC"].astype(np.int8)

    # Density inversion (TEST014) requires a profile position to compute
    # Absolute Salinity.  When the caller does not supply lat/lon (e.g.
    # unit tests, synthetic profiles) we skip the test rather than
    # defaulting to (0, 0) which would silently mis-flag polar or
    # Mediterranean water.
    from argo_decoder.rtqc import density_inversion_test

    density_test_run = False
    if latitude is not None and longitude is not None:
        try:
            t_outcome, s_outcome = density_inversion_test(
                pres=p,
                temp=t,
                psal=s,
                lat=float(latitude),
                lon=float(longitude),
                pres_qc=qc_pres,
                temp_qc=qc_temp,
                psal_qc=qc_psal,
            )
            qc_temp = np.maximum(qc_temp, t_outcome.per_level.astype(np.int8))
            qc_psal = np.maximum(qc_psal, s_outcome.per_level.astype(np.int8))
            density_test_run = True
        except Exception as exc:  # pragma: no cover - defensive
            import warnings

            warnings.warn(
                f"density_inversion test failed, skipping TEST014: {exc}",
                stacklevel=2,
            )

    ds = xr.Dataset(
        {
            "PRES": (
                ("N_LEVELS",),
                p,
                {
                    "long_name": "Sea pressure",
                    "units": "dbar",
                    "valid_min": -5.0,
                    "valid_max": 12000.0,
                    "_FillValue": PRES_FILL,
                },
            ),
            "TEMP": (
                ("N_LEVELS",),
                t,
                {
                    "long_name": "Sea temperature in-situ ITS-90",
                    "units": "degC",
                    "valid_min": -2.5,
                    "valid_max": 42.0,
                    "_FillValue": TEMP_FILL,
                },
            ),
            "PSAL": (
                ("N_LEVELS",),
                s,
                {
                    "long_name": "Practical salinity",
                    "units": "psu",
                    "valid_min": 2.0,
                    "valid_max": 41.0,
                    "_FillValue": PSAL_FILL,
                },
            ),
            "CNDC": (
                ("N_LEVELS",),
                c,
                {
                    "long_name": "Electrical conductivity",
                    "standard_name": "sea_water_electrical_conductivity",
                    "units": "S/m",
                    "valid_min": 0.0,
                    "valid_max": 8.5,
                    "_FillValue": np.float64(CNDC_FILL),
                },
            ),
            "PRES_QC": (
                ("N_LEVELS",),
                qc_pres,
                {"long_name": "Quality on pressure", "conventions": "Argo reference table 2"},
            ),
            "TEMP_QC": (
                ("N_LEVELS",),
                qc_temp,
                {"long_name": "Quality on temperature", "conventions": "Argo reference table 2"},
            ),
            "PSAL_QC": (
                ("N_LEVELS",),
                qc_psal,
                {"long_name": "Quality on salinity", "conventions": "Argo reference table 2"},
            ),
            "CNDC_QC": (
                ("N_LEVELS",),
                qc_cndc,
                {"long_name": "Quality on conductivity", "conventions": "Argo reference table 2"},
            ),
        },
        attrs={
            "wmo": wmo,
            "cycle": cycle,
            "decoder": "provor_ir_sbd",
            "platform_type": platform_type,
            "decoder_version": decoder_version,
            "decoder_id": decoder_id,
            "convention": "Argo SBD CTS4 linear counts (fast path)",
            "data_state_indicator": "A",  # real-time ('R') after QC
            # Real-time QC provenance, used to emit truthful ADMT
            # HISTORY QCP$/QCF$ records. Only the numbered Argo tests
            # this code path actually executes are listed.
            "rtqc_tests_done_hex": _qctest_hex(
                _tests_performed(density_test_run, profile_pressure_dbar is not None)
            ),
            "rtqc_tests_failed_hex": _qctest_hex(
                _tests_failed(
                    density_test_run,
                    (qc_pres, qc_temp, qc_psal),
                    non_density_failures,
                )
            ),
            **(extra_attrs or {}),
        },
    )
    return ds


def attach_doxy(
    ds: xr.Dataset,
    doxy: np.ndarray,
) -> xr.Dataset:
    """Attach a DOXY (μmol/kg) series and its QC vector to an existing CTD
    profile dataset produced by :func:`profile_to_dataset`.

    The caller is responsible for ensuring ``doxy`` is already in the same
    ascending-pressure order as the dataset's N_LEVELS dimension.  Fill
    samples should be passed as NaN; they are encoded with the standard
    Argo DOXY fill value via the variable's ``_FillValue`` attribute.
    """
    from argo_decoder.derived.doxy import DOXY_FILL
    from argo_decoder.domain.qc import QcFlag
    from argo_decoder.rtqc.non_density import global_range_test

    doxy = np.asarray(doxy, dtype=np.float64)
    n = ds.sizes.get("N_LEVELS", 0)
    if doxy.shape != (n,):
        raise ValueError(f"DOXY length {doxy.shape[0]} does not match N_LEVELS={n}")

    qc = np.full(n, int(QcFlag.GOOD), dtype=np.int8)
    invalid = ~np.isfinite(doxy)
    fill_pres = ds["PRES"].values >= 9999.0
    bad = invalid | fill_pres
    qc[bad] = int(QcFlag.BAD)
    # Global range test (0..500 μmol/kg is the Argo RTQC range for DOXY)
    rt = global_range_test("DOXY", ds["PRES"].values, doxy, vmin=-5.0, vmax=600.0)
    qc = np.maximum(qc, rt.per_level.astype(np.int8))

    ds["DOXY"] = (
        ("N_LEVELS",),
        doxy,
        {
            "long_name": "Dissolved oxygen",
            "standard_name": "moles_of_oxygen_per_unit_mass_in_sea_water",
            "units": "micromole/kg",
            "valid_min": -5.0,
            "valid_max": 600.0,
            "_FillValue": np.float64(DOXY_FILL),
        },
    )
    ds["DOXY_QC"] = (
        ("N_LEVELS",),
        qc,
        {"long_name": "Quality on dissolved oxygen", "conventions": "Argo reference table 2"},
    )
    return ds


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
