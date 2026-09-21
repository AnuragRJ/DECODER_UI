# CLI reference — `argo-decoder`

The Python decoder is invoked through the `argo-decoder` Typer CLI
(installed into the virtual environment by `pip install -e .`). On
Windows the entry point is `argo-decoder.exe`; if it isn't on PATH, use
`python -m argo_decoder.cli.main ...` as a fallback.

Global options (apply to all subcommands):

| Flag | Purpose |
|------|---------|
| `-l`, `--log-level LEVEL` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` (default `INFO`). |
| `--json-logs` | Emit JSON-structured log lines (for production/aggregation). |
| `--help` | Show help. |

## `argo-decoder decode-float` — decode a single float

```
argo-decoder decode-float WMO [OPTIONS]
```

Required argument:

* `WMO` (int) — Argo float WMO number.

Options:

| Flag | Purpose |
|------|---------|
| `-c`, `--config PATH` | Path to a legacy `decoder_conf.json`. Optional; OS-appropriate defaults apply when omitted. |
| `--xml-name NAME` | Override XML report filename (default: `co041404_<timestamp>_<wmo>.xml`). |
| `--null-decoder` | Use the structural NullDecoder (used for plumbing tests). |
| `-i`, `--input DIR` | Override input root (`archive/cycle/` + `rsync_list/`). |
| `-o`, `--out DIR` | Override output root (`nc/`, `xml/`, `log/`, `csv/` are created below it). |
| `--info-dir DIR` | Override directory of `*_info.json` files (only used with the `json` metadata backend). |
| `--meta-dir DIR` | Override directory of `*_meta.json` files. |
| `--ref DIR` | Override RTQC reference-data directory. |
| `--tmp DIR` | Override temporary directory. |
| `--metadata-backend {json,csv}` | Metadata backend to use (default `json`). |
| `--registry PATH` | Path to `registry.csv` (used when `--metadata-backend=csv`). |

Exit codes: `0` success, `1` decode errors, `2` usage/config error.

## `argo-decoder validate-config PATH`

Load a `decoder_conf.json`, validate it, and print the resolved
configuration as JSON. Exit code `1` on validation failure.

## `argo-decoder dual-run WMO` — shadow/harness

Runs both Python and the oracle (MATLAB container or pre-captured golden
files) against the same inputs, then compares outputs.

| Flag | Purpose |
|------|---------|
| `-c`, `--config PATH` | Optional config path (auto-materialised when omitted). |
| `-i`, `--input DIR` | (required) Input root. |
| `-o`, `--out DIR` | (required) Output root (`python/` and `oracle/` subdirs created). |
| `--oracle SPEC` | Oracle: `docker:<image>` (default `ghcr.io/euroargodev/...:082m`) or `file:<path>` for offline golden comparison. |
| `--runtime DIR` | MATLAB Runtime root (docker oracle only). |
| `--ref DIR` | RTQC reference-data directory. |
| `--info-dir`, `--meta-dir` | Override metadata directories. |
| `--null-decoder / --no-null-decoder` | Use NullDecoder (default on for Phase 0/1 plumbing). |
| `--report PATH` | Write a JSON diff report to this file. |

Exit codes: `0` outputs match, `2` mismatches present.

## `argo-decoder metadata validate` — validate a registry CSV

```
argo-decoder metadata validate REGISTRY.csv [--report report.json] [--strict]
```

Runs all per-row and cross-row checks (duplicates, enum membership,
range checks, chronological sanity). Exit `1` if any error (or any
warning if `--strict`).

## `argo-decoder metadata materialize` — generate JSON tree from CSV

```
argo-decoder metadata materialize REGISTRY.csv --out DIR [--wmo N ...] [--meta-subdir NAME]
```

Writes `<out>/json_float_info/<wmo>_<ptt>_info.json` and
`<out>/<meta-subdir>/<wmo>_meta.json` for every row in the registry
(or only for `--wmo`-specified floats). Used to generate the legacy
JSON layout for debugging or for feeding MATLAB during transition.

## `argo-decoder version`

Print the package version.
