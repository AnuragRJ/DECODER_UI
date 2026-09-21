# Project Status — How to Test, and What Remains

Generated 2026-07-28. Scope: the codebase itself. Deployment, Docker and
containerisation are deliberately excluded.

This document is **descriptive, not a phase entry** — it does not modify
`IMPLEMENTATION_PROGRESS.md`, which stays append-only.

---

## 1. How to test current progress

### 1.1 One-time setup per session

The sandbox does not persist installed packages. Always start with:

```bash
cd /home/user/argo-decoder-python
pip install -e ".[dev,gsw]" -q
python -c "import netCDF4, gsw; print('deps ok')"
```

If `import netCDF4` fails, the environment was reset — reinstall.

> The sibling directory name
> `Coriolis-data-processing-chain-for-Argo-floats-container/` is
> **load-bearing**: `tests/conftest.py` resolves `DEMO_ROOT` from it.
> Renaming it silently degrades 8 tests into confusing failures.

### 1.2 The full gate (run in this order)

```bash
ruff check src tests scripts          # lint
ruff format --check src tests scripts # formatting
mypy --strict src                     # types
pytest -q                             # unit + integration + golden
python scripts/generate_apex_argos_nc.py   # produce all NetCDF outputs
python scripts/audit_mono_profile_admt.py    # R<wmo>_<CCC>.nc structure
python scripts/audit_mono_profile_values.py  # R<wmo>_<CCC>.nc values
python scripts/audit_trajectory_admt.py      # <wmo>_Rtraj.nc
python scripts/audit_metadata_admt.py        # <wmo>_meta.nc
python scripts/audit_technical_admt.py       # <wmo>_tech.nc
python scripts/audit_engineering_decode.py   # engineering message decode
```

### 1.3 Expected output — verified by re-running everything today

| Gate | Expected | Observed 2026-07-28 |
|---|---|---|
| `ruff check` | All checks passed | ✅ pass |
| `ruff format --check` | 113 files already formatted | ✅ pass |
| `mypy --strict src` | no issues, 68 source files | ✅ pass |
| `pytest -q` | 520 passed | ✅ **520 passed** (35.7 s) |
| `generate_apex_argos_nc.py` | 2901339→75 nc; other three→7 nc each | ✅ all `status=ok` |
| `audit_mono_profile_admt` | `{'pass': 11, 'missing_reference': 69}` | ✅ exact |
| `audit_mono_profile_values` | 0 dtype diffs, 0 attr diffs, 1813/1813 | ✅ exact |
| `audit_trajectory_admt` | `structural_parity: 4`, `not_generated_no_raw_data: 2` | ✅ exact |
| `audit_metadata_admt` | `structural_parity: 4` + 2 | ✅ `match=28 both_blank=11 blank_in_py=17 differs=7` per float |
| `audit_technical_admt` | `structural_parity: 4` + 2 | ✅ **531/531 (100.0 %)** |
| `audit_engineering_decode` | 0 unexplained | ✅ `{'prelude_message': 1, 'decoded': 77, 'sentinel_value': 4}` |

**Everything currently passes and is reproducible from a clean environment.**

### 1.4 Reading the audit vocabulary

These statuses are honest classifications, not failures:

- `missing_reference` (69 of 80 mono profiles) — we generate a cycle the
  GDAC reference set does not contain. Only **26** reference profiles
  exist locally, and only **6** are `R*.nc`; the rest are `D*.nc`.
  11 of our profiles overlap a reference, and all 11 pass.
- `not_generated_no_raw_data` (2902203, 2902206) — references exist but
  we hold no raw ARGOS input, so nothing is generated. Correct behaviour.
- `not emitted` (24 per float in the tech audit) — parameters we
  deliberately withhold because the count→engineering-unit calibration is
  unpublished. Withholding is the truthful option.

### 1.5 Interpreting a failure

Follow the established methodology:
**Difference → investigate → root cause → truthful fix → recompare.**
Reference hierarchy on any discrepancy:
1. GDAC `R*.nc` / reference files (the migration target)
2. Argo ADMT specification
3. Coriolis MATLAB implementation (only when 1 and 2 are insufficient)

### 1.6 Coverage snapshot

`pytest --cov=argo_decoder` reports **84 % total** (5624 statements).
Fully or near-fully covered: `nc/technical.py` 100 %, `nc/trajectory.py`
99 %, `rtqc/profile_scalar.py` 99 %, `apex_argos/engineering.py` 98 %,
`nc/metadata_file.py` 95 %, `nc/mono_profile.py` 94 %, `nc/admt.py` 94 %.

Lowest-covered, and this is the honest signal of what is untested:

| Module | Cover | Why |
|---|---|---|
| `cli/main.py` | **0 %** | No CLI-level tests at all |
| `cli/metadata_cli.py` | **0 %** | No CLI-level tests at all |
| `io/fs.py` | **0 %** | Never exercised by a test |
| `util/logging.py` | 41 % | Config paths untested |
| `pipeline/dual_run.py` | 44 % | Needs the Docker oracle |
| `util/time.py` | 50 % | Helper branches untested |
| `config/loader.py` | 56 % | Error paths untested |

---

## 2. What remains, at whole-project level

The project has achieved its stated Phase 5/6A goal: **GDAC parity for
WRC/APEX ARGOS CTD floats across all four ADMT products.** What follows
is everything still open beyond that slice.

### 2.1 Blocked on external data or specification (not fixable by coding)

These are already conclusively classified in `IMPLEMENTATION_PROGRESS.md`.
They are listed here because they gate real functionality, not because
they are defects.

| # | Limitation | What it gates | Unblocker |
|---|---|---|---|
| 1 | **Cycle-timing model.** `EPOCH + TINIT` lands +10.77/+11.08/+11.87 min after reference `JULD_TRANSMISSION_START` — consistent in sign (fields read correctly) but varying 1.1 min, so not a subtractable constant. | Profile `JULD` offset, ~11 `N_CYCLE` trajectory columns, 5 measurement codes (290/296/600/700/903) | A later APF9A firmware spec revision |
| 2 | **Count→engineering-unit calibration** for 3 voltage + 3 current + internal-vacuum channels. A per-float linear fit demonstrably exists (`CURRENT_BatteryPark_mA = 4.052·byte − 3.606`, zero residual over 19 cycles) but coefficients are unpublished. | 7 withheld `_tech.nc` parameters | Manufacturer calibration sheet, or `Firmware-082213-Appendix-G.pdf` |
| 3 | **Differing DAC input.** Reference ARGOS passes absent from our archive; 39 GDAC profile levels removed by undocumented DAC post-processing. Verified by scanning the entire archive. | Residual trajectory/profile diffs | Nothing — not a defect, not reproducible |
| 4 | **Test/prelude message decoding.** Layout is now understood; our archive holds only data-message cycle files. | `_meta.nc` `CONFIG_*` (currently blank) | Prelude/test message files |

**A concrete, cheap unblocker for #1 and #2:** the container ships
**138 Git-LFS pointer stubs** (~131 bytes each) out of 3806 files —
`.gitattributes` filters `*.pdf`, `*.docx`, `*.xlsx`, `*.test`. The APEX
user manuals and `_argo_decoder_versions.xlsx` are all stubs (the xlsx
fails to open as a zip, confirming it). Fetching LFS content would very
likely resolve limitations 1 and 2 outright. **This is the single
highest-leverage remaining action on the whole project.**

### 2.2 Platform coverage — the largest remaining body of work

Only **2 of the ~10** MATLAB platform families are implemented.

| Family | Status |
|---|---|
| **WRC/APEX ARGOS CTD** (1001/1005/1010) | ✅ Complete, all four ADMT products, GDAC-validated |
| **PROVOR Iridium SBD** (212/221) | ⚠️ Partial — profiles only |
| APEX APF11 (1021/1022) | ❌ Different format; layout table returns `None` rather than guessing |
| PROVOR / NKE ARGOS | ❌ Not started |
| Remocean / Iridium RUDICS | ❌ Not started |
| NEMO, NOVA/DOVA, ARVOR Deep/Ice | ❌ Not started |

The registry holds **6 floats**; the MATLAB reference carries 523 `.m`
files across dozens of decoder ids. The `config/decoder_table.yaml`
mechanism ("tables not code", Guardrails §7.5) exists and is the right
lever, but it is populated for the demo floats only.

> **Decoder routing:** the selector is `sensor-info.csv` →
> `firmware revision number`, **never** `Float subtype` (which is the Argo
> `DAC_FORMAT_ID` and collides numerically with Coriolis decoder ids on
> 11/11 floats). Authoritative table and evidence:
> [`docs/DECODER_ROUTING_AUTHORITY.md`](DECODER_ROUTING_AUTHORITY.md).

### 2.3 PROVOR SBD is the clearest in-scope functional gap

`platforms/provor_ir_sbd/` (1634 lines) produces mono- and multi-profile
output and does trajectory *binning*, but **emits no `_Rtraj.nc`,
`_meta.nc` or `_tech.nc`**. The shared ADMT layer (`nc/admt.py`,
`nc/trajectory.py`, `nc/metadata_file.py`, `nc/technical.py`) was built
platform-agnostically in Phase 6A precisely so a second platform could
reuse it. This is the highest-value work that is **not** blocked on
external data.

Note the deliberate design decision to preserve: `trajectory/binning.py`
is **not** reused by the APEX trajectory writer, because its
`MeasurementCodes` maps 703 to "emergency ascent", contradicting Argo
reference table 15. Any PROVOR trajectory work must resolve that
inconsistency rather than paper over it.

### 2.4 BGC sensors

Only CTD is decoded. `derived/doxy.py` exists (93 % covered) but there is
no BGC decode path: no `DOXY` from raw optode frames, no `CHLA`,
`BBP700`, `NITRATE`, `PH_IN_SITU_TOTAL`, `IRRADIANCE`. `_SCIENCE_VARS` in
`nc/multi_profile.py` leaves DOXY untouched. The Argo B-file products
(`B<wmo>_<CCC>.nc`, `BR*.nc`, `BD*.nc`, `S-prof`) do not exist at all.
This is MIGRATION_DIRECT_PLAN Phase 3, entirely unstarted.

### 2.5 Product completeness

| Product | Status |
|---|---|
| `R<wmo>_<CCC>.nc` mono-profile | ✅ Complete |
| `<wmo>_prof.nc` multi-profile | ✅ Complete |
| `<wmo>_Rtraj.nc` | ✅ Complete |
| `<wmo>_meta.nc` | ✅ Complete (17 fields blank — registry holds `n/a`) |
| `<wmo>_tech.nc` | ✅ Complete (7 params withheld — §2.1 #2) |
| **`<wmo>_Dtraj.nc`** | ❌ Delayed-mode trajectory not produced |
| **B-files / S-prof** | ❌ No BGC (§2.4) |
| **XML decoding report** | ⚠️ **Stub.** `io/xml_report.py` is 61 lines; its own docstring says "Phase 0: minimal valid document … body is filled in by the real decoder in Phases 2-5." It emits an envelope with no per-cycle body. Listed in the original Phase 5 ordering, never started. |

### 2.6 Engineering hygiene (small, cheap, unblocked)

- **No CI.** `.github/workflows/` does not exist. The full gate in §1.2 is
  run by hand every time. A workflow running lint → format → mypy → pytest
  → the six audits would make regressions impossible to miss. Highest
  value-per-hour item on this list.
- **CLI is completely untested** (`cli/main.py` and `cli/metadata_cli.py`
  both at 0 %). Five commands ship — `decode-float`, `validate-config`,
  `dual-run`, `shadow`, `version` — with no test asserting they work.
  Typer's `CliRunner` makes this straightforward.
- **`io/fs.py` at 0 %** — 30 statements never executed by any test.
- **README is stale.** It still says *"Status: pre-Alpha (Phase 0
  skeleton)"* and describes `sensors/`, `derived/`, `rtqc/` as
  "(Phase 3–4)" — all three now exist and are well covered. It documents
  the null decoder but never mentions the APEX ARGOS pipeline, the four
  ADMT products, or any audit script.
- **Five overlapping handoff documents** at repo root (`HANDOFF.md`,
  `PHASE3_HANDOFF.md`, `PHASE4_HANDOFF.md`, `PHASE5_MIGRATION_HANDOFF.md`,
  plus the 5410-line `IMPLEMENTATION_PROGRESS.md`). Not harmful, but a new
  contributor has no single entry point.
- **`docs/api/`, `docs/scientific/` are README-only placeholders.**

### 2.7 Explicitly out of scope (per standing instruction)

Phase 7 Buffer Manager; deployment/Docker/containerisation; broadening
beyond WRC/APEX ARGOS CTD without a new instruction.

---

## 3. Suggested ordering

Grouped by what unblocks the most, given the standing constraints.

| Priority | Item | Blocked? | Rationale |
|---|---|---|---|
| 1 | **Fetch Git-LFS content** (138 stubs) | External | Single action; likely resolves limitations 1 **and** 2 |
| 2 | **CI workflow** | No | Locks in the 520-test / 6-audit gate permanently |
| 3 | **CLI tests** (0 % → covered) | No | Five shipped commands with zero assertions |
| 4 | **PROVOR SBD → traj/meta/tech** | No | Reuses the Phase 6A shared ADMT layer; proves it is genuinely platform-agnostic |
| 5 | **XML report body** | No | Named in the original Phase 5 ordering; still a Phase-0 stub |
| 6 | **README refresh** | No | Currently misdescribes the project as a Phase 0 skeleton |
| 7 | BGC sensors + B-files | Partly | Large; MIGRATION_DIRECT_PLAN Phase 3 |
| 8 | Further platform families | Needs data | Largest total effort |

Items 2, 3, 5 and 6 are self-contained and need no new external data.
Item 4 is the most substantial unblocked engineering work.

---

## 4. Bottom line

The APEX ARGOS CTD migration target is **met and reproducibly verified**:
520 tests pass, lint/format/types are clean, all four ADMT products
generate, and every audit reports parity or an evidence-backed
classification — 1813/1813 science levels bit-identical, 531/531 technical
values agreeing, zero unexplained engineering-decode outcomes.

What remains is not correctness debt in the delivered slice. It is
**breadth** (8 platform families, BGC, delayed-mode trajectory, XML
report body), **four externally-blocked data gaps**, and a short list of
**cheap hygiene wins** — CI, CLI tests, and a README that no longer
describes the project as a Phase 0 skeleton.
