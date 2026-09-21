"""Central metadata registry and JSON builder.

Submodules
----------
models:
    Pydantic models for the central ``FloatRegistryRow`` schema and the
    byte-compatible ``FloatInfo``/``FloatMeta`` JSON contracts.
loader:
    Abstract ``MetadataLoader`` Protocol — every backend (CSV, SQLite, ...)
    implements this interface; the decoder imports **only** against this
    protocol so it stays storage-agnostic.
csv_loader:
    CSV-backed loader (Phase 1 default). Reads ``registry.csv`` with one
    row per WMO and materialises info/meta JSON on demand.
builder:
    Translate a ``FloatRegistryRow`` into ``FloatInfo``/``FloatMeta`` and
    write legacy-compatible JSON files.
validators:
    Per-row and cross-row validation (WMO ranges, enum membership,
    duplicate IMEIs, chronological sanity, required fields).
json_loader:
    Loader against the existing ``json_float_info/`` + ``json_float_meta_*/``
    tree (kept for legacy compatibility and tests).

Backends not yet implemented but reserved by the Protocol:
``sqlite_loader``, ``postgres_loader``.
"""

from __future__ import annotations

from argo_decoder.metadata import builder, csv_loader, validators
from argo_decoder.metadata.json_loader import JsonLoader
from argo_decoder.metadata.loader import MetadataLoader
from argo_decoder.metadata.models import FloatInfo, FloatMeta, FloatRegistryRow

__all__ = [
    "FloatInfo",
    "FloatMeta",
    "FloatRegistryRow",
    "JsonLoader",
    "MetadataLoader",
    "builder",
    "csv_loader",
    "validators",
]
