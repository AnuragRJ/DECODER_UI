# scripts/

Utility scripts for development, bootstrapping, and nightly oracle validation.

| Script | Purpose |
|--------|---------|
| `bootstrap_registry.py` | Convert a legacy `json_float_info/` + `json_float_meta_ir_sbd/` tree into a populated `registry.csv` (one-off for onboarding existing floats). |
| `bootstrap_golden.py` | Generate `tests/golden/expected/` reference outputs by running the Python null decoder against the demo data. Replaced by true MATLAB golden outputs once Docker oracle parity is captured. |
| `shadow_nightly.py` | **Phase 3 M1b.** Iterate over every WMO in `registry.csv`, invoke `argo-decoder shadow` against the Docker/MCR oracle, and emit a combined `shadow_nightly_summary.json` report. Returns exit status 0 only when the cutover gate (zero error mismatches) passes across the whole registry. |

All scripts are meant to be run from a virtual environment with the
package installed in editable mode. See module docstrings for usage.
