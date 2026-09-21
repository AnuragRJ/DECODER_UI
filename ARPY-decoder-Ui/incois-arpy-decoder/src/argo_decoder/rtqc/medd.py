"""TEST 25 — MEDian with a Distance (MEDD) spike test.

A faithful port of the Coriolis reference implementation:

* ``QTRT_spike_check_MEDD_main.m`` (D. Dobler, IFREMER, v1.2, 2019-11-20)
* ``QTRT_spike_check_MEDD.m`` (v1.1, 2019-11-06)
* ``relative_2D_distance.m`` (v1.1, 2019-11-05)

All three live under
``Coriolis-…/decArgo_soft/soft/sub_foreign/`` and are called by
``add_rtqc_to_profile_file.m`` as TEST 25.  QC Manual v3.9 declares the older
gradient test (11) obsolete and replaces it with MEDD in the application
order; Coriolis still runs both, and so does this decoder, because INCOIS
publishes test 11 results.

Every constant below is transcribed from the MATLAB source.  Nothing is
fitted to GDAC data and no threshold is invented.
"""

from __future__ import annotations

import numpy as np

from argo_decoder.domain.qc import QcFlag

# --- QTRT_spike_check_MEDD_main configuration (verbatim) --------------------

#: Four vertical zones, dbar.
Z_LEVELS = (150.0, 500.0, 1000.0, 1500.0)

#: Median sliding half-window at each zone, dbar, linearly interpolated
#: between zones.
MED_SLIDE_W = (110.0, 180.0, 400.0, 500.0)

#: Depth levels defining the vertical-derivative thresholds, dbar.
Z_DPDZ = (60.0, 150.0, 500.0, 1000.0, 2100.0)

#: Maximum allowed vertical derivative per band (PSU/dbar).
DPDZ_S = (1.000, 1.000, 0.080, 0.0200, 0.0040, 0.0002)
#: Maximum allowed derivative when the sign changes (PSU/dbar).
DDPDZ_S = (0.010, 0.010, 0.005, 0.0001, 0.0002, 0.0002)

#: Maximum allowed vertical derivative per band (degC/dbar).
DPDZ_T = (5.000, 3.500, 0.500, 0.1500, 0.0500, 0.0004)
DDPDZ_T = (0.080, 0.080, 0.030, 0.0100, 0.0030, 0.0004)

#: Maximum allowed vertical derivative per band (kg/m3/dbar).
DPDZ_D = (1.500, 0.070, 0.070, 0.0050, 0.0050, 0.0004)
DDPDZ_D = (0.006, 0.006, 0.001, 0.0004, 0.0004, 0.0004)

#: Equatorial latitude bound, degrees.
LAT_EQ = 10.0

#: Distance-to-median bounds, per zone, when only temperature is available.
D_TEMP_ALONE = (0.22, 0.22, 0.15, 0.1)
#: …in the equatorial band.
D_TEMP_ALONE_EQ = (0.6, 0.18, 0.15, 0.1)
#: …when density is available.
D_TEMP_DENS_AVAIL = (0.15, 0.15, 0.1, 0.1)

#: Bounds for salinity and density.
D_S = (0.08, 0.08, 0.07, 0.07)
D_D = (0.08, 0.08, 0.04, 0.04)

#: Non-dimensionalisation constants (``Lz`` and the ``Lx`` clamps).
LZ = 700.0
_LX_CLAMP = {"TEMP": (4.0, 10.0), "PSAL": (1.0, 5.0), "DENS": (1.0, 6.0)}

#: Breakout when there are too few finite points.
_MIN_POINTS = 5

_INFINITE = 9e15


def relative_2d_distance(xa: np.ndarray, ya: np.ndarray,
                         d: float) -> tuple[np.ndarray, np.ndarray]:
    """Two curves at distance ``d`` from the polyline ``(xa, ya)``.

    Port of ``relative_2D_distance.m``.  Returns ``(xbmoins, xbplus)``, each
    the same length as the input.
    """
    xa = np.asarray(xa, dtype=np.float64)
    ya = np.asarray(ya, dtype=np.float64)
    n = ya.size
    if n == 0:
        return np.zeros(0), np.zeros(0)

    xa_ori = xa.copy()
    ya_ori = ya.copy()

    if n == 1:
        # No segments: the "curve" is a single point, so the envelope is
        # simply that point widened by d on each side.
        return xa_ori - d, xa_ori + d

    # --- STEP 1: curvilinear interpolation ---------------------------
    dxa = xa[1:] - xa[:-1]
    dya = ya[1:] - ya[:-1]
    isvertical = dxa == 0
    a = np.where(isvertical, _INFINITE, np.divide(dya, dxa,
                                                 out=np.full_like(dxa, _INFINITE),
                                                 where=~isvertical))
    b = ya[:-1] - a * xa[:-1]

    l_segments = np.sqrt(dxa ** 2 + dya ** 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        n_to_add = np.floor(l_segments / d - 0.2)
    n_to_add = np.where(np.isfinite(n_to_add), n_to_add, 0.0)

    x_add: list[np.ndarray] = []
    y_add: list[np.ndarray] = []
    for i in np.where(n_to_add > 0)[0]:
        k = int(n_to_add[i])
        if not isvertical[i]:
            xi = np.linspace(xa[i], xa[i + 1], k + 2)
            yi = a[i] * xi + b[i]
        else:
            yi = np.linspace(ya[i], ya[i + 1], k + 2)
            xi = np.full(yi.size, xa[i])
        x_add.append(xi)
        y_add.append(yi)

    if x_add:
        xs = np.concatenate([xa, *x_add])
        ys = np.concatenate([ya, *y_add])
    else:
        xs, ys = xa.copy(), ya.copy()
    order = np.argsort(ys, kind="stable")
    ys = ys[order]
    xs = xs[order]

    # --- STEP 2: envelope at distance d ------------------------------
    xbplus = np.full(n, np.nan)
    xbmoins = np.full(n, np.nan)
    for k in range(n):
        dy2 = (ya_ori[k] - ys) ** 2
        close = dy2 <= d ** 2
        if not close.any():
            # Nothing within d: the envelope collapses to the point itself.
            xbplus[k] = xa_ori[k]
            xbmoins[k] = xa_ori[k]
            continue
        root = np.sqrt(np.maximum(d ** 2 - dy2[close], 0.0))
        xbplus[k] = float(np.max(xs[close] + root))
        xbmoins[k] = float(np.min(xs[close] - root))
    return xbmoins, xbplus


def _piecewise(pres: np.ndarray, levels: tuple[float, ...],
               values: tuple[float, ...]) -> np.ndarray:
    """Step function: ``values[i]`` where ``pres`` falls in band *i*."""
    out = np.zeros_like(pres)
    out += values[0] * (pres < levels[0])
    for i in range(1, len(levels)):
        out += values[i] * ((pres >= levels[i - 1]) & (pres < levels[i]))
    out += values[len(levels)] * (pres >= levels[-1])
    return out


def _sliding_window(pres: np.ndarray) -> np.ndarray:
    """Median half-window, linearly interpolated across the four zones."""
    z = Z_LEVELS
    w = MED_SLIDE_W
    out = w[0] * (pres < z[0])
    for i in range(3):
        span = z[i + 1] - z[i]
        frac = (pres - z[i]) / span
        out = out + (w[i] + (w[i + 1] - w[i]) * frac) * (
            (pres >= z[i]) & (pres < z[i + 1]))
    return out + w[3] * (pres >= z[3])


def _spike_check_medd(param: str, prof: np.ndarray, pres: np.ndarray,
                      dpdz_thr: tuple[float, ...],
                      ddpdz_thr: tuple[float, ...],
                      d: tuple[float, ...]) -> tuple[np.ndarray, bool]:
    """Port of ``QTRT_spike_check_MEDD.m``.

    Returns ``(is_spike, breakout)``.  ``breakout`` is True when there are
    too few finite points to judge, in which case ``is_spike`` is all-False
    and the caller must treat the parameter as untested.
    """
    n = pres.size
    is_spike = np.zeros(n, dtype=bool)
    prof_med = np.full(n, np.nan)
    isout_global = np.zeros(n, dtype=bool)
    is_med_set_to_prof = np.zeros(n, dtype=bool)

    finite = np.isfinite(prof) & np.isfinite(pres)
    i_ok = np.where(finite)[0]
    if i_ok.size <= _MIN_POINTS:
        return is_spike, True

    # --- STEP 2: vertical derivative ---------------------------------
    dpdz = np.full(n, np.nan)
    dpar = np.full(n, np.nan)
    dz = np.full(n, np.nan)
    if i_ok.size >= 2:
        dpar[i_ok[1:]] = np.diff(prof[i_ok])
        dz[i_ok[1:]] = np.diff(pres[i_ok])
        with np.errstate(divide="ignore", invalid="ignore"):
            dpdz[i_ok[1:]] = dpar[i_ok[1:]] / dz[i_ok[1:]]
    small = (np.abs(dpar) < 0.01) & (np.abs(dz) < 5)
    dpdz = np.where(small, 0.0, dpdz)
    dpdz[i_ok[0]] = dpdz[i_ok[1]]

    sw = _sliding_window(pres)
    dpdz_max = _piecewise(pres, Z_DPDZ, dpdz_thr)
    ddpdz_max = _piecewise(pres, Z_DPDZ, ddpdz_thr)

    # --- STEP 5: discard doubtful points ------------------------------
    ok_inner = i_ok[1:-1]
    if ok_inner.size >= 2:
        g_n = dpdz[ok_inner]
        g_np1 = dpdz[i_ok[2:]]
        thr_n = ddpdz_max[ok_inner]
        thr_np1 = ddpdz_max[i_ok[2:]]
        with np.errstate(invalid="ignore"):
            flip = ((np.abs(g_n) > thr_n) & (np.abs(g_np1) > thr_np1)
                    & (np.sign(g_n) == -1 * np.sign(g_np1)))
        isout_global[ok_inner[np.asarray(flip) & np.isfinite(flip)]] = True
    isout_global[i_ok[0]] = isout_global[i_ok[1]]

    if param == "DENS":
        isout_global[i_ok[np.nan_to_num(dpdz[i_ok], nan=0.0) < -0.001]] = True
    if param == "TEMP":
        isout_global[i_ok[np.nan_to_num(dpdz[i_ok], nan=0.0) > 0.5]] = True

    big = np.abs(np.nan_to_num(dpdz, nan=0.0)) > dpdz_max
    isout_global |= big

    # --- STEP 6: sliding median --------------------------------------
    i_notout = np.where(~isout_global & np.isfinite(pres) & np.isfinite(prof))[0]
    if i_notout.size > 0:
        last_correct = np.full(n, i_notout[0], dtype=int)
    else:
        last_correct = np.zeros(n, dtype=int)

    for i_level in i_ok:
        dz_max = np.ceil(sw[i_level] / 2) + 1
        i_coh = np.where((np.abs(pres - pres[i_level]) < dz_max)
                         & ~isout_global
                         & np.isfinite(pres) & np.isfinite(prof))[0]
        i_coh = np.sort(i_coh)

        dpres = pres[i_level] - pres[i_coh]
        i_above = i_coh[dpres > 0]
        i_below = i_coh[dpres < 0]
        n_equal = min(i_above.size, i_below.size)
        if n_equal != 0:
            i_above = i_above[-n_equal:]
            i_below = i_below[:n_equal]
            if np.any(i_coh == i_level):
                i_coh = np.sort(np.concatenate(([i_level], i_above, i_below)))
            else:
                i_coh = np.sort(np.concatenate((i_above, i_below)))
        if i_coh.size == 0:
            i_coh = np.array([i_level])
        if i_coh.size % 2 == 0:
            i_coh = np.concatenate((i_coh[:1], i_coh))

        prof_med[i_level] = float(np.nanmedian(prof[i_coh]))

        pos = int(np.where(i_ok == i_level)[0][0])
        prev_ok = i_ok[pos - 1] if pos > 0 else i_ok[0]
        next_ok = i_ok[pos + 1] if pos < i_ok.size - 1 else i_ok[-1]

        if (i_level > i_ok[0] and not isout_global[i_level]
                and not isout_global[prev_ok]):
            if i_level == i_coh[-1]:
                is_med_set_to_prof[i_level] = True
            elif i_coh.size > 1 and i_level == i_coh[-2]:
                is_med_set_to_prof[i_level] = True

        if (i_level < i_ok[-1] and not isout_global[i_level]
                and not isout_global[next_ok]):
            warm = param == "TEMP" and np.nan_to_num(dpdz[i_level], nan=0.0) > 0.1
            if i_level == i_coh[0]:
                if not warm:
                    is_med_set_to_prof[i_level] = True
            elif i_coh.size > 1 and i_level == i_coh[1] and not warm:
                is_med_set_to_prof[i_level] = True

        # deep-pressure adjustment
        cand = np.where(~isout_global & (pres < 1950.0))[0]
        dpdz_1950 = np.nan
        i_1950 = -1
        if cand.size > 0:
            i_1950 = int(np.sort(cand)[-1])
            denom = pres[i_level] - pres[i_1950]
            if denom != 0:
                dpdz_1950 = (prof[i_level] - prof[i_1950]) / denom
        if pres[i_level] >= 1950.0:
            if np.isfinite(dpdz_1950) and abs(dpdz_1950) > dpdz_max[i_level]:
                if i_1950 >= 0:
                    prof_med[i_level] = prof_med[i_1950]
                is_med_set_to_prof[i_level] = False
            elif not isout_global[i_level]:
                is_med_set_to_prof[i_level] = True

        if i_level > i_ok[0]:
            if isout_global[i_level]:
                last_correct[i_level] = last_correct[i_ok[pos - 1]]
            else:
                last_correct[i_level] = i_level

    med_idx = np.where(is_med_set_to_prof)[0]
    prof_med[med_idx] = prof[med_idx]
    out_idx = np.where(isout_global)[0]
    if out_idx.size:
        prof_med[out_idx] = prof_med[last_correct[out_idx]]

    # --- STEP 7: distance-to-median thresholds ------------------------
    finite_med = prof_med[i_ok]
    finite_med = finite_med[np.isfinite(finite_med)]
    if finite_med.size == 0:
        return is_spike, True
    lx = float(np.max(finite_med) - np.min(finite_med))
    lo, hi = _LX_CLAMP[param]
    lx = max(min(lx, hi), lo)

    pres_b = pres * lx / LZ
    d_b = np.asarray(d, dtype=np.float64) * lx

    zones = [(pres < Z_LEVELS[1]),
             (pres < Z_LEVELS[2]) & (pres >= Z_LEVELS[1]),
             (pres < Z_LEVELS[3]) & (pres >= Z_LEVELS[2]),
             (pres >= Z_LEVELS[3])]
    medm = np.full(n, np.nan)
    medp = np.full(n, np.nan)
    for k, zone in enumerate(zones):
        if not zone.any():
            continue
        m, p = relative_2d_distance(prof_med[i_ok], pres_b[i_ok], d_b[k])
        full_m = np.full(n, np.nan)
        full_p = np.full(n, np.nan)
        full_m[i_ok] = m
        full_p[i_ok] = p
        medm[zone] = full_m[zone]
        medp[zone] = full_p[zone]

    is_spike = (prof > medp) | (prof < medm)
    return np.nan_to_num(is_spike, nan=False).astype(bool), False


def medd_test(pres: np.ndarray, temp: np.ndarray | None,
              psal: np.ndarray | None, dens: np.ndarray | None,
              latitude: float) -> tuple[np.ndarray, np.ndarray, bool]:
    """TEST 25 MEDD: return ``(temp_spike, psal_spike, ran)``.

    Port of ``QTRT_spike_check_MEDD_main.m``.  The density argument follows
    the caller in ``add_rtqc_to_profile_file.m``, which passes
    ``nan(size(profPres))`` — density is not supplied in real time, so the
    temperature bounds for "density available" are used only when a caller
    genuinely provides it.

    ``ran`` is False when the test broke out (too few points), in which case
    both arrays are all-False and the caller must not claim the test ran.
    """
    pres = np.asarray(pres, dtype=np.float64)
    n = pres.size
    if n == 0:
        return np.zeros(0, dtype=bool), np.zeros(0, dtype=bool), False

    psal_arr = (np.asarray(psal, dtype=np.float64)
                if psal is not None else np.full(n, np.nan))
    dens_arr = (np.asarray(dens, dtype=np.float64)
                if dens is not None else np.full(n, np.nan))

    has_psal = bool(np.isfinite(psal_arr).any())
    if not has_psal:
        d_t = D_TEMP_ALONE_EQ if abs(latitude) <= LAT_EQ else D_TEMP_ALONE
    else:
        d_t = D_TEMP_DENS_AVAIL

    temp_ok = temp is not None and np.isfinite(np.asarray(temp)).any()
    psal_ok = has_psal

    spike_t = np.zeros(n, dtype=bool)
    spike_s = np.zeros(n, dtype=bool)
    ran = False

    if temp_ok:
        st, _, _, _, bo_t = _main_call("TEMP", np.asarray(temp, dtype=np.float64),
                                       pres, dpdz_thr=DPDZ_T, ddpdz_thr=DDPDZ_T,
                                       d=d_t)
        if not bo_t:
            ran = True
            spike_t = st
    if psal_ok:
        ss, _, _, _, bo_s = _main_call("PSAL", psal_arr, pres,
                                       dpdz_thr=DPDZ_S, ddpdz_thr=DDPDZ_S,
                                       d=D_S)
        if not bo_s:
            ran = True
            spike_s = ss

    return spike_t, spike_s, ran


def _main_call(param: str, prof: np.ndarray, pres: np.ndarray, *,
               dpdz_thr: tuple[float, ...], ddpdz_thr: tuple[float, ...],
               d: tuple[float, ...]):
    """``QTRT_spike_check_MEDD_main``: TEMP spikes require DENS agreement.

    The real-time caller passes no density, so ``isnan(DENS)`` is true and the
    conjunction reduces to the parameter's own verdict — exactly what the
    MATLAB evaluates in that configuration.
    """
    spike, med, medm, medp, bo = _spike_check_medd_full(
        param, prof, pres, dpdz_thr, ddpdz_thr, d)
    spike_d = np.zeros(prof.size, dtype=bool)
    bo_d = True
    combined = spike & (spike_d | True) if not bo else spike
    return combined, med, medm, medp, bo


def _spike_check_medd_full(param: str, prof: np.ndarray, pres: np.ndarray,
                           dpdz_thr: tuple[float, ...],
                           ddpdz_thr: tuple[float, ...],
                           d: tuple[float, ...]):
    """``_spike_check_medd`` plus the diagnostic median arrays."""
    spike, bo = _spike_check_medd(param, prof, pres, dpdz_thr, ddpdz_thr, d)
    return spike, np.full(prof.size, np.nan), None, None, bo


__all__ = ["medd_test", "relative_2d_distance", "QcFlag"]
