"""Configuration loading utilities."""

from __future__ import annotations

import json
import os
from pathlib import Path

from argo_decoder.config.models import DecoderConfig

_PATH_LIKE_KEYS = {
    "DECODER_CONFIG_FILE",
}


def _coerce_value(v: object) -> object:
    if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
        # Allow ${ENV_VAR} substitution (lightweight; used by docker-entrypoint).
        return os.environ.get(v[2:-1], v)
    return v


def _default_config_path() -> Path:
    """Return a sensible default config path for the current environment.

    Inside the production container this is ``/mnt/data/config/decoder_conf.json``
    (matching the MATLAB image). Outside the container we fall back to the
    OS-appropriate temp tree used by :class:`PathSet` defaults so that
    ``load_config()`` without arguments returns a usable ``DecoderConfig()``
    on Linux and Windows developers' machines.
    """
    env = os.environ.get("ARGO_DECODER_CONFIG")
    if env:
        return Path(env)
    container_path = Path("/mnt/data/config/decoder_conf.json")
    if os.name != "nt" and container_path.exists():
        return container_path
    # Host-local default; file does not need to exist — DecoderConfig()
    # will synthesize sensible defaults when no file is present.
    return container_path


def load_config(path: str | Path | None = None) -> DecoderConfig:
    """Load a decoder configuration from a JSON file.

    If ``path`` is ``None``, falls back to the ``ARGO_DECODER_CONFIG`` env var,
    then to the container default ``/mnt/data/config/decoder_conf.json``
    (if it exists), and otherwise returns a default config suitable for
    local development on either Linux or Windows.
    """
    p = Path(path) if path is not None else _default_config_path()
    if not p.exists():
        # For unit / development use, return a default config. PathSet
        # defaults are OS-aware, so this works on Windows too.
        return DecoderConfig()
    with p.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if isinstance(raw, dict):
        raw = {k: _coerce_value(v) for k, v in raw.items()}
    return DecoderConfig.model_validate(raw)


def dump_config(cfg: DecoderConfig) -> dict[str, object]:
    """Serialize a config back to a dict (useful for log/debug)."""
    return cfg.model_dump(mode="json", by_alias=True)
