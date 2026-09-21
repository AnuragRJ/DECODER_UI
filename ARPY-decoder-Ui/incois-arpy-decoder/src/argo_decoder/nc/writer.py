"""NetCDF writing.

Writes the in-memory xarray Datasets produced by decoders into the
standard Argo directory layout under ``<output_dir>/nc/<wmo>/``:

* Mono profiles go into ``<wmo>/profiles/R<wmo>_<CCC>.nc`` (ADMT-3.1
  standard; ``R`` prefix denotes real-time).  This matches the MATLAB
  oracle layout exactly so the comparator pairs files 1:1 without
  requiring prefix-stripping fallbacks.  The flat decoder dataset is
  promoted to the ADMT ``(N_PROF, N_LEVELS)`` shape with fixed Argo
  dimensions and metadata variables by ``nc/mono_profile.py``.
* The multi-profile file ``<wmo>/<wmo>_prof.nc`` is assembled from the
  mono-profile datasets (M6), padding to the global ``N_LEVELS`` max
  and carrying the full set of ADMT-required profile-level metadata
  strings and global attributes.
* Auxiliary products (``<wmo>_meta.nc``, ``<wmo>_tech.nc``,
  ``<wmo>_traj.nc`` / ``<wmo>_Rtraj.nc``) are written at the float
  root if the decoder produced them.

Attributes written to NetCDF must be str/Number/ndarray/list/tuple/bytes;
dicts and other non-primitive types are JSON-serialized defensively so
future additions to ``ds.attrs`` (e.g. debug counters) cannot crash the
pipeline with ``Invalid value for attr`` TypeErrors from xarray/netCDF4.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from argo_decoder.config.models import DecoderConfig
from argo_decoder.nc.metadata_file import write_metadata_file
from argo_decoder.nc.mono_profile import build_mono_profile_dataset, write_mono_profile
from argo_decoder.nc.multi_profile import build_multi_profile_dataset, write_multi_profile
from argo_decoder.nc.technical import write_technical_file
from argo_decoder.nc.trajectory import write_trajectory
from argo_decoder.platforms.base import DecodeResult
from argo_decoder.util.hashing import sha256_file
from argo_decoder.util.logging import get_logger

log = get_logger(__name__)


def _is_publishable_cycle(cycle: int, ds: Any) -> bool:
    """Should this cycle be written as a profile file?

    Two cases are held back, both specific to real telemetry decoders:

    *Engineering-only transmissions.* A float sends messages 1-2 for the
    pre-deployment self test and 1-3 after the mission ends. They decode
    cleanly but carry zero CTD levels, so they belong in the technical
    and trajectory products only -- the DAC publishes no profile for
    them, and feeding one to the multi-profile stacker raises a
    concatenation error (N_PARAM 0 against 3) that loses the whole file.

    *Unresolved cycle numbers.* A negative cycle means no cycle number
    could be established, which would emit an out-of-convention name
    such as ``R<wmo>_-01.nc``.

    Emptiness cannot be judged from the dimensions: xarray drops
    ``N_LEVELS`` entirely when it is zero, so an engineering-only APEX
    cycle and a NullDecoder placeholder both present ``sizes == {}``.
    The reliable signal is which decoder produced the dataset. The
    NullDecoder emits structural placeholders and nothing else, so those
    are still written (flat, unpromoted); any real telemetry decoder
    that reports no levels genuinely has no profile to publish.
    """
    if cycle < 0:
        return False
    attrs = getattr(ds, "attrs", {})
    if attrs.get("decoder", "null") == "null":
        return True
    return bool(getattr(ds, "sizes", {}).get("N_LEVELS", 0))


def _sanitize_attrs(ds: object) -> None:
    """Coerce non-NetCDF-serializable attribute values to JSON strings.

    Operates in-place on ``ds.attrs``. Anything that is not a string, a
    number, an ndarray, a list, a tuple, or bytes gets dumped via
    ``json.dumps`` so the write path never crashes on a debug counter
    or structured log payload.
    """
    import xarray as xr

    if not isinstance(ds, xr.Dataset):
        return
    for k, v in list(ds.attrs.items()):
        if v is None:
            ds.attrs[k] = ""
            continue
        if isinstance(v, (str, bytes, np.ndarray, list, tuple)):
            continue
        if isinstance(v, (bool, int, float)):
            continue
        if isinstance(v, np.ScalarType):
            continue
        # Fallback: JSON serialize dicts / lists-of-dicts / other objects.
        try:
            ds.attrs[k] = json.dumps(v, default=str, sort_keys=True)
        except (TypeError, ValueError):
            ds.attrs[k] = str(v)


def _out_dir(config: DecoderConfig, wmo: int) -> Path:
    out = Path(config.paths.nc_dir) / str(wmo)
    out.mkdir(parents=True, exist_ok=True)
    # ADMT mono profiles live in the ``profiles/`` subdirectory (same as
    # the MATLAB oracle), so ensure it exists before we start writing.
    (out / "profiles").mkdir(parents=True, exist_ok=True)
    return out


def write_outputs(result: DecodeResult, config: DecoderConfig) -> dict[str, str]:
    """Write DecodeResult datasets to the configured NC output directory.

    Returns a dict mapping ``{product_type: file_checksum}`` for every file
    written.

    On-disk layout (ADMT-3.1)::

        nc/<wmo>/
            <wmo>_prof.nc            # M6 multi-profile (N_PROF x N_LEVELS)
            <wmo>_meta.nc            # auxiliary (if produced)
            <wmo>_tech.nc            # auxiliary (if produced)
            <wmo>_traj.nc            # M5 trajectory (placeholder)
            profiles/
                R<wmo>_NNN.nc        # mono profile, real-time
    """
    out_root = _out_dir(config, result.wmo)
    profiles_dir = out_root / "profiles"
    written: dict[str, str] = {}

    # ------------------------------------------------------------------
    # 1) Mono profiles -> profiles/R<wmo>_<CCC>.nc
    #    (R prefix = real-time, matching the MATLAB oracle exactly).
    # ------------------------------------------------------------------
    science_datasets = {
        cycle: ds
        for cycle, ds in result.mono_profile_datasets.items()
        if _is_publishable_cycle(cycle, ds)
    }
    skipped = sorted(set(result.mono_profile_datasets) - set(science_datasets))
    if skipped:
        # Test and end-of-life transmissions carry engineering only: the
        # float sends messages 1-2 (pre-deployment self test) or 1-3
        # (post-mission) with no CTD block. They still belong in the
        # technical and trajectory products, but a profile file with no
        # levels is not a profile, and the DAC does not publish one.
        log.info("mono_profile_skipped_no_science", cycles=skipped, n=len(skipped))
    for cycle, ds in sorted(science_datasets.items()):
        _sanitize_attrs(ds)
        path = profiles_dir / f"R{result.wmo}_{cycle:03d}.nc"
        # NullDecoder placeholders carry no N_LEVELS at all; they are
        # written flat rather than promoted to the ADMT layout.
        if "N_LEVELS" not in ds.sizes:
            ds.to_netcdf(path, engine="netcdf4", format="NETCDF4")
            written[f"mono_{cycle:03d}"] = sha256_file(path)
            log.debug("nc_write", path=str(path), bytes=path.stat().st_size)
            continue
        try:
            admt_ds = build_mono_profile_dataset(
                ds,
                wmo=result.wmo,
                cycle=cycle,
                meta=result.meta,
                institution=result.institution,
            )
            _sanitize_attrs(admt_ds)
            write_mono_profile(admt_ds, path)
        except Exception as exc:  # pragma: no cover - defensive
            # Never lose science because the ADMT metadata layer failed:
            # fall back to the flat decoder dataset.
            log.error("mono_profile_admt_build_failed", cycle=cycle, error=str(exc))
            ds.to_netcdf(path, engine="netcdf4", format="NETCDF4")
        written[f"mono_{cycle:03d}"] = sha256_file(path)
        log.debug("nc_write", path=str(path), bytes=path.stat().st_size)

    # ------------------------------------------------------------------
    # 2) Multi-profile file  (M6)  ->  <wmo>_prof.nc
    #    Built from the mono datasets if the decoder did not already
    #    provide one. We always (re)build here so the on-disk file is
    #    consistent with the mono profiles that were just written. The
    #    multi file is written with netCDF4 directly (via
    #    ``write_multi_profile``) rather than via xarray.to_netcdf so
    #    NC_CHAR variables do NOT acquire the spurious trailing
    #    ``string1`` dimension that xarray injects for |S1 arrays.
    # ------------------------------------------------------------------
    if science_datasets:
        try:
            multi_ds = result.multi_profile_dataset
            if multi_ds is None:
                # Stack only the science-bearing cycles. Feeding an
                # engineering-only placeholder here raises a concatenation
                # error (N_PARAM 0 vs 3) and loses the whole file.
                multi_ds = build_multi_profile_dataset(
                    science_datasets,
                    meta=result.meta,
                    wmo=result.wmo,
                    decoder_version=result.decoder_version,
                    institution=result.institution,
                )
            _sanitize_attrs(multi_ds)
            prof_path = out_root / f"{result.wmo}_prof.nc"
            write_multi_profile(multi_ds, prof_path)
            written["multi_profile"] = sha256_file(prof_path)
            log.debug("nc_write", path=str(prof_path), bytes=prof_path.stat().st_size)
        except Exception as exc:  # pragma: no cover - defensive
            log.error("multi_profile_build_failed", error=str(exc))
            written["multi_profile_error"] = str(exc)

    # ------------------------------------------------------------------
    # 3) Trajectory -> <wmo>_Rtraj.nc  (R = real time, as the GDAC does).
    #    Written through the ADMT writer so NC_CHAR variables keep their
    #    reference shape and the fixed dimensions are emitted in order.
    # ------------------------------------------------------------------
    if result.traj_dataset is not None:
        try:
            traj_ds = result.traj_dataset
            _sanitize_attrs(traj_ds)
            traj_path = out_root / f"{result.wmo}_Rtraj.nc"
            write_trajectory(traj_ds, traj_path)
            written["traj_dataset"] = sha256_file(traj_path)
            log.debug("nc_write", path=str(traj_path), bytes=traj_path.stat().st_size)
        except Exception as exc:  # pragma: no cover - defensive
            log.error("trajectory_write_failed", error=str(exc))
            written["traj_error"] = str(exc)

    # ------------------------------------------------------------------
    # 4) Metadata -> <wmo>_meta.nc, written through the ADMT writer so
    #    NC_CHAR variables keep their reference shape and the fixed
    #    dimensions are emitted in reference order.
    # ------------------------------------------------------------------
    if result.meta_dataset is not None:
        try:
            meta_ds = result.meta_dataset
            _sanitize_attrs(meta_ds)
            meta_path = out_root / f"{result.wmo}_meta.nc"
            write_metadata_file(meta_ds, meta_path)
            written["meta_dataset"] = sha256_file(meta_path)
            log.debug("nc_write", path=str(meta_path), bytes=meta_path.stat().st_size)
        except Exception as exc:  # pragma: no cover - defensive
            log.error("metadata_write_failed", error=str(exc))
            written["meta_error"] = str(exc)

    # ------------------------------------------------------------------
    # 5) Technical -> <wmo>_tech.nc, via the ADMT writer.
    # ------------------------------------------------------------------
    if result.tech_dataset is not None:
        try:
            tech_ds = result.tech_dataset
            _sanitize_attrs(tech_ds)
            tech_path = out_root / f"{result.wmo}_tech.nc"
            write_technical_file(tech_ds, tech_path)
            written["tech_dataset"] = sha256_file(tech_path)
            log.debug("nc_write", path=str(tech_path), bytes=tech_path.stat().st_size)
        except Exception as exc:  # pragma: no cover - defensive
            log.error("technical_write_failed", error=str(exc))
            written["tech_error"] = str(exc)

    return written
