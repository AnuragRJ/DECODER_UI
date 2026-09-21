"""Decoder routing table.

The routing table replaces the proliferation of MATLAB
``init_float_config_prv_ir_sbd_<ver>.m`` dispatch files with a single
declarative YAML file (``config/decoder_table.yaml``).  It maps a
``(platform_type, decoder_version)`` pair to the static parameters that
a platform plugin needs in order to decode SBD frames for that firmware
release.

Phase 1 ships a minimal table covering the two demo floats (WMO 6902892
and 6903014).  Phases 2-4 expand the table by parsing the existing
MATLAB initialisation scripts (see ``scripts/extract_decoder_table.py``,
added in Phase 2).

Design rules (Guardrails §7 - "tables not code")
------------------------------------------------
* No ``if decoder_id == N`` chains in science modules.
* Sensor lists are declarative, not hard-coded per firmware.
* Adding a firmware version is a one-row YAML edit + a matching plugin
  (if behaviour actually differs); there is no code-change required for
  a firmware that reuses an existing ``profile_class``.
* The table is loaded once and passed around explicitly; no module-level
  globals.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enumerations (validated against the YAML)
# ---------------------------------------------------------------------------

PlatformFamily = Literal["FLOAT", "FLOAT_DEEP", "FLOAT_BGC", "FLOAT_ICE"]
TransmissionKind = Literal[
    "IRIDIUM_SBD",
    "IRIDIUM_RUDICS",
    "ARGOS",
    "IRIDIUM_SBD_REMOCEAN",
]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DecoderTableEntry(BaseModel):
    """One row of the decoder routing table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    platform_type: str
    decoder_version: str
    decoder_id: int = Field(gt=0)
    platform_family: PlatformFamily
    transmission: TransmissionKind
    frame_length: int = Field(gt=0)
    profile_class: str | None = None
    """Python plugin class name (``None`` until Phase 2 ships the plugin)."""
    sensors: list[str] = Field(default_factory=list)
    notes: str = ""

    @property
    def key(self) -> tuple[str, str]:
        """Lookup key: ``(platform_type, decoder_version)``."""
        return (self.platform_type, self.decoder_version)


class DecoderTable(BaseModel):
    """Top-level YAML document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decoders: list[DecoderTableEntry] = Field(default_factory=list)

    # ----- Derived lookups --------------------------------------------------
    def by_platform_version(self, platform_type: str, decoder_version: str) -> DecoderTableEntry:
        """Look up an entry by ``(platform_type, decoder_version)``.

        Raises :class:`KeyError` if no matching row exists.
        """
        for entry in self.decoders:
            if entry.platform_type == platform_type and entry.decoder_version == decoder_version:
                return entry
        raise KeyError(
            f"No decoder_table entry for platform_type={platform_type!r} "
            f"decoder_version={decoder_version!r}"
        )

    def entries_for_profile_class(self, profile_class: str) -> list[DecoderTableEntry]:
        """All entries implementing one wire-protocol family."""
        return [e for e in self.decoders if e.profile_class == profile_class]

    def by_decoder_id(self, decoder_id: int) -> DecoderTableEntry:
        """Look up an entry by numeric ``decoder_id``."""
        for entry in self.decoders:
            if entry.decoder_id == decoder_id:
                return entry
        raise KeyError(f"No decoder_table entry for decoder_id={decoder_id}")

    def all_decoder_ids(self) -> set[int]:
        return {e.decoder_id for e in self.decoders}

    def all_platform_version_keys(self) -> set[tuple[str, str]]:
        return {e.key for e in self.decoders}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_DEFAULT_TABLE_PATH = Path(__file__).with_name("decoder_table.yaml")
"""Path to the YAML file shipped inside the ``argo_decoder.config`` package."""


def load_decoder_table(path: str | Path | None = None) -> DecoderTable:
    """Load and validate the decoder routing table.

    Parameters
    ----------
    path:
        Optional path to a YAML file.  When ``None`` the bundled
        ``config/decoder_table.yaml`` shipped with the package is used.
    """
    p = Path(path) if path is not None else _DEFAULT_TABLE_PATH
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if raw is None:
        return DecoderTable()
    if not isinstance(raw, dict):
        raise ValueError(
            f"decoder_table YAML at {p} must be a mapping at top level, got {type(raw).__name__}"
        )
    return DecoderTable.model_validate(raw)


@lru_cache(maxsize=4)
def _cached_table(path: str) -> DecoderTable:
    """Cache helper keyed by absolute path string (hashable)."""
    return load_decoder_table(Path(path))


def get_decoder_table(path: str | Path | None = None) -> DecoderTable:
    """Return a cached :class:`DecoderTable`.

    Uses the bundled default when ``path`` is ``None``.  Cache is keyed
    by absolute path so reloading an explicit path returns the same
    validated object on subsequent calls.
    """
    p = Path(path) if path is not None else _DEFAULT_TABLE_PATH
    return _cached_table(str(p.resolve()))


__all__ = [
    "DecoderTable",
    "DecoderTableEntry",
    "PlatformFamily",
    "TransmissionKind",
    "get_decoder_table",
    "load_decoder_table",
]
