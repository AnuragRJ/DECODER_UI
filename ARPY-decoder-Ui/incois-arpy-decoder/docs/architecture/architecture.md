# Architecture overview

The Python decoder is a layered, plugin-based application whose
dependency direction is strictly inward:

```
cli/ ──► pipeline/ ──► {config, metadata, io, platforms, sensors,
                         derived, rtqc, nc}
                            │
                            ▼
                        domain/  (pure dataclasses, QC enums)
                        util/    (logging, hashing, time)
```

Key properties:

* **No globals.** Per-run state flows through an explicit
  `DecoderConfig` and `PipelineResult`.
* **Plugins, not if/else.** Per-platform and per-sensor decoders
  register themselves via decorators; selection is driven by
  metadata (platform type + decoder id + version).
* **Decoder is storage-agnostic.** The decoder imports `FloatInfo`
  and `FloatMeta` from `argo_decoder.metadata.models` only. It never
  imports CSV/SQLite/Postgres loaders; the metadata stage materialises
  those Pydantic objects (or their on-disk JSON equivalents) before
  the decoder runs.
* **Oracle-validated.** Every change is gated by the dual-run harness
  (see `oracle_harness.md`).
* **Structured logging.** All log lines are key-value pairs via
  `structlog`; human or JSON output selected by `--log-format`.
* **Cross-platform.** Pure Python, no POSIX-only code paths outside
  the Docker oracle. `pathlib.Path`, `tempfile.gettempdir()`, and
  `subprocess` with list arguments are used throughout.

See also:

* `metadata.md` — central metadata registry
* `oracle_harness.md` (to be written in Phase 2, after CTD parity) —
  dual-run harness and comparators
* `platforms.md` (Phase 2) — platform plugin interface
