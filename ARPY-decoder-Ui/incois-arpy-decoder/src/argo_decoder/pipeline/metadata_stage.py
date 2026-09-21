"""Metadata materialization stage.

Runs before the decoder stage: picks a metadata loader from the config,
optionally materialises ``info.json`` / ``meta.json`` into a per-run
meta-cache directory, and returns a :class:`MetadataLoader` pointed at
that cache.

This keeps the decoder itself (platforms/sensors/rtqc) completely
oblivious to whether the metadata came from CSV, SQLite, PostgreSQL, or
an existing JSON tree.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from argo_decoder.config.models import DecoderConfig, MetadataBackend
from argo_decoder.metadata import JsonLoader, MetadataLoader
from argo_decoder.metadata.csv_loader import CsvLoader
from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader
from argo_decoder.util.logging import get_logger

_log = get_logger().bind(stage="metadata")


def _materialized_dirs(config: DecoderConfig) -> tuple[Path, Path]:
    """Return (info, meta) JSON cache directories, creating them."""
    base = config.metadata.materialized_dir or (
        Path(tempfile.gettempdir()) / "argo_decoder" / "meta_cache"
    )
    info_dir = base / "json_float_info"
    meta_dir = base / "json_float_meta_ir_sbd"
    info_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    return info_dir, meta_dir


def build_metadata_loader(config: DecoderConfig) -> MetadataLoader:
    """Construct the appropriate loader for ``config.metadata.backend``.

    For the ``csv``/``sqlite``/``postgres`` backends the materialised JSON
    files are written into a per-run cache directory (``.meta_cache`` under
    ``paths.temporary_dir``) so the decoder reads a stable on-disk shape.
    """
    backend = config.metadata.backend
    if backend == MetadataBackend.JSON or backend == "json":
        _log.info("metadata_backend", backend="json")
        return JsonLoader(config.paths.float_info_dir, config.paths.float_meta_dir)

    if backend == MetadataBackend.CSV4 or backend == "csv4":
        metadata_dir = config.metadata.registry_path
        if metadata_dir is None:
            raise ValueError("metadata.backend=csv4 but metadata.registry_path is not set")
        info_dir, meta_dir = _materialized_dirs(config)
        loader4: MetadataLoader = MultiCsvLoader(
            metadata_dir,
            materialized_dir=info_dir,
            strict=False,
        )
        wrapped: MetadataLoader = cast(MetadataLoader, _MetaMaterializer(loader4, meta_dir))
        config.paths.float_info_dir = info_dir
        config.paths.float_meta_dir = meta_dir
        _log.info("metadata_backend", backend="csv4", metadata_dir=str(metadata_dir))
        return wrapped

    if backend == MetadataBackend.CSV or backend == "csv":
        registry = config.metadata.registry_path
        if registry is None:
            raise ValueError("metadata.backend=csv but metadata.registry_path is not set")
        materialized_dir = config.metadata.materialized_dir or (
            Path(tempfile.gettempdir()) / "argo_decoder" / "meta_cache"
        )
        materialized_dir_info = materialized_dir / "json_float_info"
        materialized_dir_meta = materialized_dir / "json_float_meta_ir_sbd"
        materialized_dir_info.mkdir(parents=True, exist_ok=True)
        materialized_dir_meta.mkdir(parents=True, exist_ok=True)
        csv_loader: MetadataLoader = CsvLoader(
            registry,
            materialized_dir=materialized_dir_info,
            strict=False,
        )
        # The CSV loader writes info JSONs directly; for meta JSONs we need
        # to wire the meta materialized dir via a small proxy.
        loader: MetadataLoader = cast(
            MetadataLoader, _MetaMaterializer(csv_loader, materialized_dir_meta)
        )
        # Rewire cfg paths so downstream decoder IO reads from the cache.
        config.paths.float_info_dir = materialized_dir_info
        config.paths.float_meta_dir = materialized_dir_meta
        _log.info(
            "metadata_backend",
            backend="csv",
            registry=str(registry),
            materialized_dir=str(materialized_dir),
        )
        return loader

    raise ValueError(f"Unsupported metadata backend: {backend!r}")


class _MetaMaterializer:
    """Proxy loader that also writes meta.json via the builder."""

    def __init__(self, inner: MetadataLoader, meta_dir: Path) -> None:
        from argo_decoder.metadata import builder as _builder

        self._inner = inner
        self._meta_dir = meta_dir
        self._builder = _builder
        self._wmos_materialized: set[int] = set()

    def name(self) -> str:
        return f"meta-materializer:{self._inner.name() if hasattr(self._inner, 'name') else '?'}"

    def get_float(self, wmo: int) -> Any:
        return self._inner.get_float(wmo)

    def iter_floats(self, wmos: Iterable[int] | None = None) -> Iterable[Any]:
        return self._inner.iter_floats(wmos)

    def load_info(self, wmo: int) -> Any:
        return self._inner.load_info(wmo)

    def load_meta(self, wmo: int) -> Any:
        # First ensure the inner loader materialises info; then explicitly
        # write meta to our meta_dir for the first access.
        meta = None
        row = self.get_float(wmo)
        if row is not None and wmo not in self._wmos_materialized:
            meta_obj = self._builder.build_meta(row)
            self._builder.write_meta_json(meta_obj, self._meta_dir)
            self._wmos_materialized.add(wmo)
            meta = meta_obj
        if meta is None:
            try:
                meta = self._inner.load_meta(wmo)
            except (FileNotFoundError, NotImplementedError, AttributeError):
                meta = JsonLoader(
                    self._meta_dir.parent / "json_float_info", self._meta_dir
                ).load_meta(wmo)
        return meta
