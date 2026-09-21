"""CSV-backed metadata registry loader.

Reads a normalised CSV (see :mod:`argo_decoder.metadata.models.FloatRegistryRow`
for the canonical schema) with one row per WMO. The CSV is read once at
construction time and validated into :class:`FloatRegistryRow` instances;
lookups are O(1) from an in-memory dict keyed by WMO.

The loader also presents the same ``load_info`` / ``load_meta`` interface as
:class:`JsonLoader` by materialising the JSON contract on the fly through
:mod:`argo_decoder.metadata.builder`, so a pipeline can swap ``JsonLoader`` for
``CsvLoader`` without any other code change. If an optional
``materialized_dir`` is supplied the generated ``meta.json`` and ``info.json``
files are also written there (useful for debugging and for feeding MATLAB
during transition).
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from pathlib import Path

from argo_decoder.metadata import builder as _builder
from argo_decoder.metadata.models import (
    FloatInfo,
    FloatMeta,
    FloatRegistryRow,
)
from argo_decoder.util.logging import get_logger


class CsvLoader:
    """Load :class:`FloatRegistryRow` records from a CSV file.

    Parameters
    ----------
    csv_path:
        Path to the ``registry.csv`` file.
    materialized_dir:
        If given, the loader writes a ``<wmo>_<ptt>_info.json`` and
        ``<wmo>_meta.json`` pair into this directory the first time a
        WMO is accessed (mirroring the legacy JSON tree).
    strict:
        If ``True`` (default) raise on the first invalid row; otherwise
        log and skip invalid rows.
    """

    def __init__(
        self,
        csv_path: Path | str,
        *,
        materialized_dir: Path | str | None = None,
        strict: bool = True,
    ) -> None:
        self.csv_path = Path(csv_path)
        self.materialized_dir = Path(materialized_dir) if materialized_dir else None
        self.strict = strict
        self._rows: dict[int, FloatRegistryRow] | None = None
        self._log = get_logger().bind(component="CsvLoader")

    # ----- MetadataLoader protocol ---------------------------------------
    def get_float(self, wmo: int) -> FloatRegistryRow | None:
        self._ensure_loaded()
        return self._rows.get(int(wmo))  # type: ignore[union-attr]

    def iter_floats(self, wmos: Iterable[int] | None = None) -> Iterator[FloatRegistryRow]:
        self._ensure_loaded()
        assert self._rows is not None
        wmo_set = {int(w) for w in wmos} if wmos is not None else None
        for wmo, row in self._rows.items():
            if wmo_set is not None and wmo not in wmo_set:
                continue
            yield row

    def load_info(self, wmo: int) -> FloatInfo:
        row = self.get_float(wmo)
        if row is None:
            raise FileNotFoundError(f"WMO {wmo} not present in CSV registry {self.csv_path}")
        info = _builder.build_info(row)
        if self.materialized_dir is not None:
            _builder.write_info_json(info, self.materialized_dir)
        return info

    def load_meta(self, wmo: int) -> FloatMeta:
        row = self.get_float(wmo)
        if row is None:
            raise FileNotFoundError(f"WMO {wmo} not present in CSV registry {self.csv_path}")
        meta = _builder.build_meta(row)
        if self.materialized_dir is not None:
            _builder.write_meta_json(meta, self.materialized_dir)
        return meta

    # ----- internals -----------------------------------------------------
    def _ensure_loaded(self) -> None:
        if self._rows is not None:
            return
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Metadata CSV not found: {self.csv_path}")
        rows: dict[int, FloatRegistryRow] = {}
        with self.csv_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise ValueError(f"Empty CSV: {self.csv_path}")
            for lineno, raw in enumerate(reader, start=2):
                # Strip whitespace from all keys/values up front.
                clean = {
                    (k or "").strip(): (v.strip() if isinstance(v, str) else v)
                    for k, v in raw.items()
                    if k is not None
                }
                # Skip fully-blank lines.
                if not any(str(v) for v in clean.values()):
                    continue
                try:
                    row = FloatRegistryRow.model_validate(clean)
                except Exception as exc:  # pragma: no cover - exercised via tests
                    msg = f"Invalid row at {self.csv_path}:{lineno}: {exc}"
                    if self.strict:
                        raise ValueError(msg) from exc
                    self._log.warning("skip_invalid_row", line=lineno, error=str(exc))
                    continue
                if row.wmo in rows:
                    msg = f"Duplicate WMO {row.wmo} at {self.csv_path}:{lineno}"
                    if self.strict:
                        raise ValueError(msg)
                    self._log.warning("duplicate_wmo", line=lineno, wmo=row.wmo)
                    continue
                rows[row.wmo] = row
        self._rows = rows
        self._log.info(
            "csv_loaded",
            path=str(self.csv_path),
            n_rows=len(rows),
        )


def load_registry_csv(path: Path | str, *, strict: bool = True) -> list[FloatRegistryRow]:
    """Convenience function returning a list of all registry rows."""
    loader = CsvLoader(path, strict=strict)
    return list(loader.iter_floats())
